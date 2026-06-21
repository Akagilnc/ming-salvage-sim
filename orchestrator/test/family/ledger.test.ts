/**
 * family-ledger — append-only merged-child event ledger (ADR 0022 decision 5,
 * #293 seam 3).
 *
 * #293 records the thinnest entry `{childIssue, status:"merged"}` per merged
 * child, appended through the {@link FamilyBackend} seam (the real impl writes a
 * sibling file OUTSIDE the family base worktree). This module owns:
 *   - `recordMerged(backend, childIssue)` — append one merged event;
 *   - `mergedSet(entries)` — derive the set of merged child issue numbers the
 *     commander's unblock predicate (ADR 0022 decision 6②) reads.
 *
 * #298 extends the ENTRY schema + adds reconcile by growing THIS module, not the
 * spine — the spine only calls recordMerged / mergedSet.
 */

import { describe, expect, it } from "vitest";
import { mergedSet, recordMerged } from "../../src/family/ledger.js";
import type { FamilyBackend, FamilyLedgerEntry } from "../../src/family/types.js";

/** A zero-IO fake family backend that keeps the ledger in memory. */
class FakeFamilyBackend implements FamilyBackend {
  readonly appended: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
    return { familyHead: "head" };
  }
  // #295 conflict-fallback seam `resolveMergeConflict` is OPTIONAL — this ledger
  // test never merges with a conflict, so the fake omits it entirely.
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.appended.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.appended;
  }
}

describe("family-ledger.recordMerged (#293 seam 3)", () => {
  it("appends a thin {childIssue, status:'merged'} entry per merged child", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, 10);
    await recordMerged(backend, 11);
    expect(backend.appended).toEqual([
      { childIssue: 10, status: "merged" },
      { childIssue: 11, status: "merged" },
    ]);
  });

  it("is append-only: a second record for the same child appends, never mutates", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, 10);
    await recordMerged(backend, 10);
    // Append-only — both events are retained (reconcile dedup is #298, not #293).
    expect(backend.appended).toHaveLength(2);
    expect(backend.appended.every((e) => e.childIssue === 10)).toBe(true);
  });
});

describe("family-ledger.mergedSet (#293 seam 3)", () => {
  it("derives the set of merged child issue numbers", () => {
    const entries: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged" },
      { childIssue: 11, status: "merged" },
    ];
    const set = mergedSet(entries);
    expect(set.has(10)).toBe(true);
    expect(set.has(11)).toBe(true);
    expect(set.has(12)).toBe(false);
  });

  it("an empty ledger yields an empty merged set", () => {
    expect(mergedSet([]).size).toBe(0);
  });
});
