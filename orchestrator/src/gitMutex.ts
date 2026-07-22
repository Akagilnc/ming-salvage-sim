/**
 * gitMutex.ts — per-clone mutex serialising git-MUTATING operations (#291 B7),
 * upgraded for cross-process exclusivity (#1103 H2).
 *
 * Layers (one mechanism, two scopes — not two locks to reason about separately):
 *   1. process-local promise-chain Map (same-key FIFO inside one Node process)
 *   2. keyed-on-clone directory lock at `<clone>/.git/.orchestrator-git.lock`
 *      (mkdir / O_EXCL-style; shared by the host runner AND spawned
 *      hostCliWorkerRunner children that otherwise hold empty Maps)
 *
 * Same-process nesting is reentrant via a per-lock depth counter so a section
 * already holding the file lock (e.g. mergeChildLocked) can call
 * {@link runExclusiveSync} helpers (exclude RMW / checkout) without deadlocking.
 */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { isAbsolute, join, resolve } from "node:path";

import { shWithClock } from "./externalCall.js";

/** Per-key tail promise: the last-queued critical section for that clone path. */
const tails = new Map<string, Promise<unknown>>();

/** Same-process reentrancy depth for an acquired lock directory. */
const heldDepth = new Map<string, number>();

/** Lock directory name under the clone's `.git` (common dir). */
export const ORCHESTRATOR_GIT_LOCK_NAME = ".orchestrator-git.lock";

/** Wait budget when another process holds the lock. */
const LOCK_WAIT_MS = 120_000;
/** Spin interval while waiting for the lock directory. */
const LOCK_SPIN_MS = 50;
/**
 * A lock dir older than this with a dead/missing pid is treated as abandoned
 * wreckage and reclaimed. Conservative — live holders keep the dir present.
 */
const LOCK_STALE_MS = 120_000;

/**
 * Resolve the absolute git common dir for `repoPath` (independent clone or
 * linked worktree — both land on the shared `.git` that must be serialised).
 */
export function resolveGitCommonDir(repoPath: string): string {
  const raw = shWithClock(
    "git",
    ["-C", repoPath, "rev-parse", "--git-common-dir"],
    { stage: "git-mutex-common-dir" },
  );
  if (raw.length === 0) {
    throw new Error(`gitMutex: empty --git-common-dir for ${repoPath}`);
  }
  return isAbsolute(raw) ? raw : resolve(repoPath, raw);
}

/**
 * Absolute path of the orchestrator lock directory for `repoPath`'s clone.
 * Returns `null` when `repoPath` is not a git repo (unit-test keys like
 * `"cloneA"` keep the in-process Map only — no file lock to create under cwd).
 */
export function orchestratorGitLockPath(repoPath: string): string | null {
  try {
    return join(resolveGitCommonDir(repoPath), ORCHESTRATOR_GIT_LOCK_NAME);
  } catch {
    return null;
  }
}

function sleepSync(ms: number): void {
  // Host git calls are sync (execFileSync); keep lock acquire on the sync stack.
  const sab = new SharedArrayBuffer(4);
  const ia = new Int32Array(sab);
  Atomics.wait(ia, 0, 0, ms);
}

function lockPidPath(lockDir: string): string {
  return join(lockDir, "pid");
}

function isPidAlive(pid: number): boolean {
  if (!Number.isFinite(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function tryReclaimStaleLock(lockDir: string, nowMs: number): boolean {
  if (!existsSync(lockDir)) return false;
  let mtimeMs: number;
  try {
    mtimeMs = statSync(lockDir).mtimeMs;
  } catch {
    return false;
  }
  if (nowMs - mtimeMs < LOCK_STALE_MS) return false;
  let pid = 0;
  try {
    pid = Number(readFileSync(lockPidPath(lockDir), "utf8").trim());
  } catch {
    pid = 0;
  }
  if (isPidAlive(pid)) return false;
  try {
    rmSync(lockDir, { recursive: true, force: true });
    return true;
  } catch {
    return false;
  }
}

function acquireFileLock(lockDir: string): void {
  const depth = heldDepth.get(lockDir) ?? 0;
  if (depth > 0) {
    heldDepth.set(lockDir, depth + 1);
    return;
  }
  const deadline = Date.now() + LOCK_WAIT_MS;
  for (;;) {
    try {
      mkdirSync(lockDir);
      writeFileSync(lockPidPath(lockDir), `${process.pid}\n`, "utf8");
      heldDepth.set(lockDir, 1);
      return;
    } catch (err) {
      const code =
        err && typeof err === "object" && "code" in err
          ? String((err as { code: unknown }).code)
          : "";
      if (code !== "EEXIST") throw err;
      tryReclaimStaleLock(lockDir, Date.now());
      if (Date.now() > deadline) {
        throw new Error(
          `gitMutex: timed out after ${LOCK_WAIT_MS}ms waiting for ${lockDir}`,
        );
      }
      sleepSync(LOCK_SPIN_MS);
    }
  }
}

function releaseFileLock(lockDir: string): void {
  const depth = heldDepth.get(lockDir) ?? 0;
  if (depth > 1) {
    heldDepth.set(lockDir, depth - 1);
    return;
  }
  heldDepth.delete(lockDir);
  try {
    rmSync(lockDir, { recursive: true, force: true });
  } catch {
    // Best-effort release; next waiter may reclaim via stale detection.
  }
}

async function runExclusiveHoldingFileLock<T>(
  key: string,
  fn: () => Promise<T> | T,
): Promise<T> {
  const lockDir = orchestratorGitLockPath(key);
  if (lockDir === null) {
    return await fn();
  }
  acquireFileLock(lockDir);
  try {
    return await fn();
  } finally {
    releaseFileLock(lockDir);
  }
}

/**
 * Run `fn` with EXCLUSIVE access to the git mutations of clone `key`, serialising
 * it after any already-queued section for the same key (FIFO). Different keys run
 * concurrently. Cross-process writers on the same clone also serialise via the
 * file lock. The section's result/throw is returned/propagated to the caller;
 * a throw never blocks later waiters on the same key.
 */
export async function runExclusive<T>(
  key: string,
  fn: () => Promise<T> | T,
): Promise<T> {
  const prior = tails.get(key) ?? Promise.resolve();
  const run = prior.then(
    () => runExclusiveHoldingFileLock(key, fn),
    () => runExclusiveHoldingFileLock(key, fn),
  );
  const tail = run.then(
    () => undefined,
    () => undefined,
  );
  tails.set(key, tail);
  void tail.finally(() => {
    if (tails.get(key) === tail) tails.delete(key);
  });
  return run;
}

/**
 * Synchronous exclusive section for sync git / exclude RMW callers (#1103 H3).
 * Same file lock as {@link runExclusive}; reentrant when already held in-process.
 * Non-git keys skip the file lock (in-process callers still serialise via their
 * own stack — production paths always pass a real clone).
 */
export function runExclusiveSync<T>(key: string, fn: () => T): T {
  const lockDir = orchestratorGitLockPath(key);
  if (lockDir === null) {
    return fn();
  }
  acquireFileLock(lockDir);
  try {
    return fn();
  } finally {
    releaseFileLock(lockDir);
  }
}

/**
 * Reset all mutex state (tests only) — so a test's queued sections do not leak
 * into the next. Never used on the production path.
 */
export function _resetGitMutex(): void {
  tails.clear();
  heldDepth.clear();
}

/**
 * The number of LIVE keys currently tracked (tests only). After all sections on a
 * key have settled, that key must be removed (no unbounded growth across a long
 * family run) — this lets a test assert the Map does not leak settled keys.
 */
export function _mutexKeyCount(): number {
  return tails.size;
}
