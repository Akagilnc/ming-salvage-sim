/**
 * gitMutex.ts — a process-wide, per-clone async mutex serialising git-MUTATING
 * operations (#291 B7 wave concurrency).
 *
 * B7 turns the family spine's per-wave fan-out from serial `for…await` into
 * concurrent `Promise.allSettled(wave.map(runChild))` (runner.ts:314, the
 * deferred US7 work). The wave's children share ONE dedicated clone (ADR 0024:
 * the family RealBackend keyed by the parent epic), so concurrent
 * `git worktree add` / ref updates on that one `.git` contend on
 * `.git/index.lock` and per-ref locks — a genuine race the distinct child
 * BRANCHES do NOT isolate (logical isolation ≠ git-level lock isolation).
 *
 * The fix (runner.ts:314 comment): LLM work runs concurrently, but the
 * git-MUTATING critical sections (the single-slice `prepareWorktree` cut, the
 * family `git merge --no-ff`) are serialised by a process-wide mutex KEYED ON
 * the clone path — so two children of the SAME clone never touch its `.git`
 * concurrently, while two DIFFERENT clones (e.g. two unrelated family runs in the
 * same process) never block each other.
 *
 * It is a tiny promise-chain mutex (no dependency): each `runExclusive` appends
 * its critical section to the key's tail promise and awaits the prior one, so the
 * sections run strictly one-at-a-time per key, FIFO. A section that throws does
 * NOT poison the chain — the tail advances regardless (the next waiter still
 * runs), and the throw propagates to ITS caller.
 */

/** Per-key tail promise: the last-queued critical section for that clone path. */
const tails = new Map<string, Promise<unknown>>();

/**
 * Run `fn` with EXCLUSIVE access to the git mutations of clone `key`, serialising
 * it after any already-queued section for the same key (FIFO). Different keys run
 * concurrently. The section's result/throw is returned/propagated to the caller;
 * a throw never blocks later waiters on the same key.
 */
export async function runExclusive<T>(
  key: string,
  fn: () => Promise<T> | T,
): Promise<T> {
  // The section may only START after the prior queued one SETTLES (resolve OR
  // reject) — `.then(settle, settle)` so a prior throw does not break the chain.
  const prior = tails.get(key) ?? Promise.resolve();
  const run = prior.then(
    () => fn(),
    () => fn(),
  );
  // Advance the tail to THIS section's settle, so the next waiter queues behind
  // it. Swallow the result/throw on the tail copy (the real one goes to `run`),
  // so an unhandled rejection is never raised on the bookkeeping promise.
  const tail = run.then(
    () => undefined,
    () => undefined,
  );
  tails.set(key, tail);
  // Reap the key once THIS section settles — but ONLY when it is still the tail
  // (no later waiter has queued behind it). Otherwise a long family run accretes a
  // settled-but-never-removed entry per clone key (the #291 r2 leak). The
  // `tails.get(key) === tail` identity guard means a section that has a successor
  // queued behind it does NOT delete the key out from under that successor.
  void tail.finally(() => {
    if (tails.get(key) === tail) tails.delete(key);
  });
  return run;
}

/**
 * Reset all mutex state (tests only) — so a test's queued sections do not leak
 * into the next. Never used on the production path.
 */
export function _resetGitMutex(): void {
  tails.clear();
}

/**
 * The number of LIVE keys currently tracked (tests only). After all sections on a
 * key have settled, that key must be removed (no unbounded growth across a long
 * family run) — this lets a test assert the Map does not leak settled keys.
 */
export function _mutexKeyCount(): number {
  return tails.size;
}
