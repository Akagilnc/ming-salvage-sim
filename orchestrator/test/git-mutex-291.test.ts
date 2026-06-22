/**
 * #291 B7 — per-clone git mutex (gitMutex.ts).
 *
 * The wave fan-out runs children CONCURRENTLY (Promise.allSettled), but the
 * git-MUTATING critical sections (prepareWorktree cut / family merge) on the ONE
 * shared clone must run STRICTLY one-at-a-time per clone — concurrent
 * `git worktree add` / ref updates contend on `.git/index.lock`. This proves the
 * mutex serialises same-key sections (no overlap), runs different keys
 * concurrently, preserves FIFO, and survives a throwing section.
 */

import { afterEach, describe, expect, it } from "vitest";
import { _mutexKeyCount, _resetGitMutex, runExclusive } from "../src/gitMutex.js";

afterEach(() => _resetGitMutex());

/** A controllable critical section: records its overlap against a shared counter. */
function makeSection(state: { active: number; maxActive: number; order: number[] }) {
  return async (id: number, holdMs: number): Promise<void> => {
    state.active += 1;
    state.maxActive = Math.max(state.maxActive, state.active);
    state.order.push(id);
    await new Promise((r) => setTimeout(r, holdMs));
    state.active -= 1;
  };
}

describe("#291 B7 gitMutex", () => {
  it("serialises sections on the SAME key — never two active at once", async () => {
    const state = { active: 0, maxActive: 0, order: [] as number[] };
    const section = makeSection(state);
    await Promise.all([
      runExclusive("cloneA", () => section(1, 30)),
      runExclusive("cloneA", () => section(2, 5)),
      runExclusive("cloneA", () => section(3, 5)),
    ]);
    // Strict serialisation: the peak concurrency on one key is 1.
    expect(state.maxActive).toBe(1);
    // FIFO: queued in call order despite different hold times.
    expect(state.order).toEqual([1, 2, 3]);
  });

  it("runs DIFFERENT keys concurrently (they do not block each other)", async () => {
    const state = { active: 0, maxActive: 0, order: [] as number[] };
    const section = makeSection(state);
    await Promise.all([
      runExclusive("cloneA", () => section(1, 20)),
      runExclusive("cloneB", () => section(2, 20)),
    ]);
    // Two distinct keys overlap → peak concurrency 2.
    expect(state.maxActive).toBe(2);
  });

  it("a throwing section does NOT poison the chain — later waiters still run", async () => {
    const ran: number[] = [];
    const p1 = runExclusive("cloneA", async () => {
      throw new Error("boom");
    });
    const p2 = runExclusive("cloneA", async () => {
      ran.push(2);
    });
    await expect(p1).rejects.toThrow(/boom/);
    await p2;
    expect(ran).toEqual([2]);
  });

  it("returns the section's resolved value to its caller", async () => {
    const v = await runExclusive("cloneA", async () => 42);
    expect(v).toBe(42);
  });

  it("does NOT leak settled keys — the tails Map is emptied once a key's sections all settle (#291 r2)", async () => {
    // The Map is per-clone keyed; a long family run touches many keys but each
    // clone's git ops eventually settle. A settled key must be DELETED, else the
    // Map grows without bound across the run. After both keys settle, the live key
    // count is 0.
    await Promise.all([
      runExclusive("cloneA", async () => undefined),
      runExclusive("cloneB", async () => undefined),
    ]);
    // Let the bookkeeping `.then`/`.finally` microtasks flush.
    await Promise.resolve();
    expect(_mutexKeyCount()).toBe(0);
  });

  it("a THROWING section's key is also cleaned up (no leak on the error path)", async () => {
    await runExclusive("cloneA", async () => {
      throw new Error("boom");
    }).catch(() => undefined);
    await Promise.resolve();
    expect(_mutexKeyCount()).toBe(0);
  });

  it("does NOT delete a key that still has a QUEUED section behind the settled one", async () => {
    // The cleanup must only fire when THIS section is still the tail; a later
    // waiter that re-set the tail must not be wiped when the earlier one settles.
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const first = runExclusive("cloneA", () => gate); // holds the lock open
    const second = runExclusive("cloneA", async () => undefined); // queued behind it
    // While the first is still in-flight, the key is live.
    expect(_mutexKeyCount()).toBe(1);
    release();
    await Promise.all([first, second]);
    await Promise.resolve();
    // Both settled now → key removed.
    expect(_mutexKeyCount()).toBe(0);
  });
});
