/**
 * gitWorktreePreflight.ts — idempotent heal before a shared-clone worktree cut (#1103 H1).
 *
 * Mutex only prevents concurrent writers; a killed/timed-out `git worktree add` can
 * still leave dir-present/metadata-absent (or the reverse) wreckage plus a stale
 * `index.lock`. This preflight runs inside the per-clone exclusive section, before
 * Sandcastle `createWorktree`, and is safe to call repeatedly.
 */

import {
  existsSync,
  realpathSync,
  rmSync,
  statSync,
  unlinkSync,
} from "node:fs";
import { join, resolve } from "node:path";

import { shWithClock } from "./externalCall.js";

/** Sandcastle names the worktree dir as the branch with `/` → `-` (#1103). */
export function sandcastleWorktreePathForBranch(
  repoPath: string,
  branch: string,
): string {
  return join(
    repoPath,
    ".sandcastle",
    "worktrees",
    branch.replace(/\//g, "-"),
  );
}

/** Admin entry under `.git/worktrees/<name>` mirrors the worktree basename. */
export function worktreeAdminDirForBranch(
  repoPath: string,
  branch: string,
): string {
  return join(repoPath, ".git", "worktrees", branch.replace(/\//g, "-"));
}

/**
 * Age above which an `index.lock` is treated as abandoned wreckage and unlinked.
 * Fresh locks are left alone (git worktree add does not require clearing them).
 */
export const INDEX_LOCK_STALE_MS = 120_000;

export type WorktreePreflightGit = (args: readonly string[]) => string;

function defaultGit(repoPath: string, args: readonly string[]): string {
  return shWithClock("git", ["-C", repoPath, ...args], {
    stage: "git-worktree-preflight",
  });
}

/** Normalize for path equality (`/tmp` vs `/private/tmp` on macOS, etc.). */
function normPath(p: string): string {
  try {
    return realpathSync(p);
  } catch {
    return resolve(p);
  }
}

function listedWorktreePaths(
  repoPath: string,
  runGit: WorktreePreflightGit,
): Set<string> {
  const out = runGit(["worktree", "list", "--porcelain"]);
  const paths = new Set<string>();
  for (const line of out.split("\n")) {
    if (line.startsWith("worktree ")) {
      paths.add(normPath(line.slice("worktree ".length).trim()));
    }
  }
  return paths;
}

/**
 * Remove a stale `index.lock` only when clearly abandoned (mtime older than
 * {@link INDEX_LOCK_STALE_MS}). Fresh locks are left in place — never deleted,
 * never fail-loud (#1105 A2: worktree add succeeds even with a live lock).
 */
export function clearStaleIndexLock(
  repoPath: string,
  nowMs: number = Date.now(),
): void {
  const lockPath = join(repoPath, ".git", "index.lock");
  if (!existsSync(lockPath)) return;
  let mtimeMs: number;
  try {
    mtimeMs = statSync(lockPath).mtimeMs;
  } catch {
    return;
  }
  const ageMs = nowMs - mtimeMs;
  if (ageMs < INDEX_LOCK_STALE_MS) return;
  try {
    unlinkSync(lockPath);
  } catch {
    // Raced with another clearer / holder exit — preflight stays idempotent.
  }
}

/**
 * Derive the iso clone root from a Sandcastle resident worktree path
 * (`<clone>/.sandcastle/worktrees/<name>`). Returns `null` when the path is not
 * under that layout.
 */
export function clonePathFromSandcastleWorktree(worktreePath: string): string | null {
  const normalized = worktreePath.replace(/\\/g, "/");
  const marker = "/.sandcastle/worktrees/";
  const idx = normalized.lastIndexOf(marker);
  if (idx <= 0) return null;
  return normalized.slice(0, idx);
}

/**
 * Idempotent preflight before cutting `branch` under `repoPath`:
 * 1. `git worktree prune` (drop dead metadata),
 * 2. heal dir↔metadata skew for the intended Sandcastle path,
 * 3. clear a clearly-stale `index.lock` (fresh locks are left alone).
 *
 * `runGit` defaults to host `git -C repoPath`; RealBackend passes `this.sh` so
 * unit intercepts (worktree-cut / branch-fallback) stay on the same seam.
 */
export function healBeforeWorktreeCut(
  repoPath: string,
  branch: string,
  runGit: WorktreePreflightGit = (args) => defaultGit(repoPath, args),
): void {
  runGit(["worktree", "prune"]);

  const wtPath = sandcastleWorktreePathForBranch(repoPath, branch);
  const listed = listedWorktreePaths(repoPath, runGit);
  const inList = listed.has(normPath(wtPath));
  const dirExists = existsSync(wtPath);

  if (dirExists && !inList) {
    // Directory present / metadata absent — classic half-dead leftover.
    rmSync(wtPath, { recursive: true, force: true });
  } else if (!dirExists && inList) {
    // Metadata present / directory absent — prune again after force-remove attempt.
    try {
      runGit(["worktree", "remove", "--force", wtPath]);
    } catch {
      runGit(["worktree", "prune"]);
    }
  }

  // Orphan admin dir with no registered worktree (prune should clear; belt+suspenders).
  const admin = worktreeAdminDirForBranch(repoPath, branch);
  if (existsSync(admin) && !inList && !existsSync(wtPath)) {
    rmSync(admin, { recursive: true, force: true });
    runGit(["worktree", "prune"]);
  }

  clearStaleIndexLock(repoPath);
}
