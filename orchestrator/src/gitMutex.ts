/**
 * gitMutex.ts — per-clone mutex serialising git-MUTATING operations (#291 B7),
 * upgraded for cross-process exclusivity (#1103 H2 / #1105 R2).
 *
 * Layers (one mechanism, two scopes — not two locks to reason about separately):
 *   1. process-local promise-chain Map keyed on git common-dir (linked worktrees
 *      and the clone root share one FIFO — raw path keys would miss each other)
 *   2. directory lock at `<common-dir>/.orchestrator-git.lock` (mkdir / O_EXCL-style;
 *      shared by the host runner AND spawned hostCliWorkerRunner children)
 *
 * Same-process nesting is reentrant only for the ALS owner token that acquired
 * the lock — a concurrent task must wait (never pierce via depth alone).
 */

import { AsyncLocalStorage } from "node:async_hooks";
import { randomBytes } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { isAbsolute, join, resolve } from "node:path";

import { shWithClock } from "./externalCall.js";

/** Per-common-dir (or in-process-only key) tail promise. */
const tails = new Map<string, Promise<unknown>>();

/** Same-process hold: lockDir → owner token + nesting depth. */
const heldBy = new Map<string, { token: string; depth: number }>();

/** Cached `git rev-parse --git-common-dir` results (fail-closed resolve once). */
const commonDirCache = new Map<string, string>();

/** Async-local owner token so nested sync helpers reenter only the holder. */
const lockOwnerAls = new AsyncLocalStorage<string>();

/** Lock directory name under the clone's git common dir. */
export const ORCHESTRATOR_GIT_LOCK_NAME = ".orchestrator-git.lock";

/** Wait budget when another process/holder owns the lock. */
export const LOCK_WAIT_MS = 120_000;
/** Spin interval while waiting for the lock directory. */
const LOCK_SPIN_MS = 50;
/**
 * A lock dir older than this with a dead/missing pid is treated as abandoned
 * wreckage and reclaimed. Must be strictly below {@link LOCK_WAIT_MS} so a
 * waiter can reclaim before the wait budget self-throws at the boundary.
 */
export const LOCK_STALE_MS = 90_000;

/**
 * Explicit bypass predicate for unit-test Map-only keys (`"cloneA"`).
 * Real clone / worktree paths always contain a separator and take the file lock
 * fail-closed — never a catch-all that swallows spawn/timeout failures.
 */
export function isInProcessOnlyMutexKey(key: string): boolean {
  return !key.includes("/") && !key.includes("\\");
}

/** Normalize `/tmp` vs `/private/tmp` (and symlink clones) to one Map/lock key. */
function normCommonDir(p: string): string {
  try {
    return realpathSync(p);
  } catch {
    return resolve(p);
  }
}

/**
 * Resolve the absolute git common dir for `repoPath` (independent clone or
 * linked worktree — both land on the shared `.git` that must be serialised).
 * Fail-closed: any empty/throwing resolve propagates (no null swallow).
 */
export function resolveGitCommonDir(repoPath: string): string {
  const cached = commonDirCache.get(repoPath);
  if (cached !== undefined) return cached;
  const raw = shWithClock(
    "git",
    ["-C", repoPath, "rev-parse", "--git-common-dir"],
    { stage: "git-mutex-common-dir" },
  );
  if (raw.length === 0) {
    throw new Error(`gitMutex: empty --git-common-dir for ${repoPath}`);
  }
  const absolute = isAbsolute(raw) ? raw : resolve(repoPath, raw);
  const resolved = normCommonDir(absolute);
  commonDirCache.set(repoPath, resolved);
  // Also cache under the resolved path so clone-root vs worktree lookups hit.
  commonDirCache.set(resolved, resolved);
  return resolved;
}

/**
 * Map / file-lock key for `repoPath`: common-dir for real git checkouts;
 * identity for explicit non-git bypasses (in-process-only keys / no `.git`).
 */
export function mutexMapKey(repoPath: string): string {
  if (isInProcessOnlyMutexKey(repoPath)) return repoPath;
  if (!existsSync(join(repoPath, ".git"))) return repoPath;
  return resolveGitCommonDir(repoPath);
}

/**
 * Absolute path of the orchestrator lock directory for `repoPath`'s clone.
 * Fail-closed when `repoPath` looks like a git checkout (`.git` present) —
 * resolve errors / spawn timeouts throw, never catch-swallowed.
 * Returns `null` only for explicit non-git bypasses:
 *   - {@link isInProcessOnlyMutexKey} unit Map keys (`"cloneA"`)
 *   - paths with no `.git` entry (synthetic fixtures / not-yet-provisioned dirs)
 */
export function orchestratorGitLockPath(repoPath: string): string | null {
  if (isInProcessOnlyMutexKey(repoPath)) return null;
  if (!existsSync(join(repoPath, ".git"))) return null;
  return join(resolveGitCommonDir(repoPath), ORCHESTRATOR_GIT_LOCK_NAME);
}

function sleepSync(ms: number): void {
  const sab = new SharedArrayBuffer(4);
  const ia = new Int32Array(sab);
  Atomics.wait(ia, 0, 0, ms);
}

function lockPidPath(lockDir: string): string {
  return join(lockDir, "pid");
}

function lockTokenPath(lockDir: string): string {
  return join(lockDir, "owner");
}

function newOwnerToken(): string {
  return randomBytes(16).toString("hex");
}

/**
 * `process.kill(pid, 0)` probe: ESRCH ⇒ dead; EPERM ⇒ alive (no permission to
 * signal, but the process exists — never treat as reclaimable wreckage).
 */
export function isPidAlive(pid: number): boolean {
  if (!Number.isFinite(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    const code =
      err && typeof err === "object" && "code" in err
        ? String((err as { code: unknown }).code)
        : "";
    if (code === "EPERM") return true;
    return false;
  }
}

/**
 * Stale reclaim with ABA protection: rename-then-verify-token-then-rm.
 * Two reclaimers cannot both delete and then both recreate without serialising
 * on the rename of the same directory.
 */
export function tryReclaimStaleLock(lockDir: string, nowMs: number): boolean {
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
  let expectedToken = "";
  try {
    expectedToken = readFileSync(lockTokenPath(lockDir), "utf8").trim();
  } catch {
    expectedToken = "";
  }
  const reclaimPath = `${lockDir}.reclaim.${newOwnerToken()}`;
  try {
    renameSync(lockDir, reclaimPath);
  } catch {
    return false;
  }
  if (expectedToken.length > 0) {
    try {
      const got = readFileSync(lockTokenPath(reclaimPath), "utf8").trim();
      if (got !== expectedToken) {
        // Lost the race — put it back if we can; otherwise leave for the winner.
        try {
          renameSync(reclaimPath, lockDir);
        } catch {
          /* winner owns the name */
        }
        return false;
      }
    } catch {
      // No token after rename — treat as abandoned wreckage and remove.
    }
  }
  try {
    rmSync(reclaimPath, { recursive: true, force: true });
    return true;
  } catch {
    return false;
  }
}

function acquireFileLock(lockDir: string, token: string): void {
  const held = heldBy.get(lockDir);
  const alsOwner = lockOwnerAls.getStore();
  if (held !== undefined && held.token === token && alsOwner === token) {
    heldBy.set(lockDir, { token, depth: held.depth + 1 });
    return;
  }
  const deadline = Date.now() + LOCK_WAIT_MS;
  for (;;) {
    try {
      mkdirSync(lockDir);
      try {
        writeFileSync(lockPidPath(lockDir), `${process.pid}\n`, "utf8");
        writeFileSync(lockTokenPath(lockDir), `${token}\n`, "utf8");
      } catch (writeErr) {
        // A5: mkdir succeeded but pid/token write failed — do not leave a
        // depth-less lock dir that blocks the clone for the full wait budget.
        try {
          rmSync(lockDir, { recursive: true, force: true });
        } catch {
          /* best-effort */
        }
        throw writeErr;
      }
      heldBy.set(lockDir, { token, depth: 1 });
      return;
    } catch (err) {
      const code =
        err && typeof err === "object" && "code" in err
          ? String((err as { code: unknown }).code)
          : "";
      if (code !== "EEXIST") throw err;
      tryReclaimStaleLock(lockDir, Date.now());
      // A4 WAIT==STALE boundary: if reclaim (or the holder) freed the dir,
      // retry mkdir even when the wait budget has elapsed.
      if (!existsSync(lockDir)) continue;
      if (Date.now() > deadline) {
        // One last reclaim before self-throw at the WAIT boundary.
        if (tryReclaimStaleLock(lockDir, Date.now()) || !existsSync(lockDir)) {
          continue;
        }
        throw new Error(
          `gitMutex: timed out after ${LOCK_WAIT_MS}ms waiting for ${lockDir}`,
        );
      }
      sleepSync(LOCK_SPIN_MS);
    }
  }
}

function releaseFileLock(lockDir: string, token: string): void {
  const held = heldBy.get(lockDir);
  if (held === undefined || held.token !== token) {
    // Not our hold — never delete another owner's lock.
    return;
  }
  if (held.depth > 1) {
    heldBy.set(lockDir, { token, depth: held.depth - 1 });
    return;
  }
  heldBy.delete(lockDir);
  try {
    const onDisk = readFileSync(lockTokenPath(lockDir), "utf8").trim();
    if (onDisk !== token) return;
    rmSync(lockDir, { recursive: true, force: true });
  } catch {
    // Best-effort release; next waiter may reclaim via stale detection.
  }
}

function runWithFileLockSync<T>(lockDir: string, fn: () => T): T {
  const existing = lockOwnerAls.getStore();
  const held = heldBy.get(lockDir);
  if (existing !== undefined && held !== undefined && held.token === existing) {
    acquireFileLock(lockDir, existing);
    try {
      return fn();
    } finally {
      releaseFileLock(lockDir, existing);
    }
  }
  const token = newOwnerToken();
  return lockOwnerAls.run(token, () => {
    acquireFileLock(lockDir, token);
    try {
      return fn();
    } finally {
      releaseFileLock(lockDir, token);
    }
  });
}

async function runWithFileLockAsync<T>(
  lockDir: string,
  fn: () => Promise<T> | T,
): Promise<T> {
  const existing = lockOwnerAls.getStore();
  const held = heldBy.get(lockDir);
  if (existing !== undefined && held !== undefined && held.token === existing) {
    acquireFileLock(lockDir, existing);
    try {
      return await fn();
    } finally {
      releaseFileLock(lockDir, existing);
    }
  }
  const token = newOwnerToken();
  return lockOwnerAls.run(token, async () => {
    acquireFileLock(lockDir, token);
    try {
      return await fn();
    } finally {
      releaseFileLock(lockDir, token);
    }
  });
}

/**
 * Run `fn` with EXCLUSIVE access to the git mutations of clone `key`, serialising
 * it after any already-queued section for the same common-dir (FIFO). Different
 * common-dirs run concurrently. Cross-process writers on the same clone also
 * serialise via the file lock. The section's result/throw is returned/propagated;
 * a throw never blocks later waiters on the same key.
 */
export async function runExclusive<T>(
  key: string,
  fn: () => Promise<T> | T,
): Promise<T> {
  const mapKey = mutexMapKey(key);
  const prior = tails.get(mapKey) ?? Promise.resolve();
  const run = prior.then(
    () => {
      const lockDir = orchestratorGitLockPath(key);
      if (lockDir === null) return fn();
      return runWithFileLockAsync(lockDir, fn);
    },
    () => {
      const lockDir = orchestratorGitLockPath(key);
      if (lockDir === null) return fn();
      return runWithFileLockAsync(lockDir, fn);
    },
  );
  const tail = run.then(
    () => undefined,
    () => undefined,
  );
  tails.set(mapKey, tail);
  void tail.finally(() => {
    if (tails.get(mapKey) === tail) tails.delete(mapKey);
  });
  return run;
}

/**
 * Synchronous exclusive section for sync git / exclude RMW callers (#1103 H3).
 * Same file lock as {@link runExclusive}; reentrant only for the ALS owner.
 * Concurrent sync callers while another task holds the lock wait — never pierce.
 */
export function runExclusiveSync<T>(key: string, fn: () => T): T {
  const lockDir = orchestratorGitLockPath(key);
  if (lockDir === null) return fn();
  return runWithFileLockSync(lockDir, fn);
}

/**
 * Reset all mutex state (tests only) — so a test's queued sections do not leak
 * into the next. Never used on the production path.
 */
export function _resetGitMutex(): void {
  tails.clear();
  heldBy.clear();
  commonDirCache.clear();
}

/**
 * The number of LIVE keys currently tracked (tests only). After all sections on a
 * key have settled, that key must be removed (no unbounded growth across a long
 * family run) — this lets a test assert the Map does not leak settled keys.
 */
export function _mutexKeyCount(): number {
  return tails.size;
}
