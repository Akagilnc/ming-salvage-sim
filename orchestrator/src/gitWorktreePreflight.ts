/**
 * gitWorktreePreflight.ts — idempotent heal before shared-clone worktree cut (#1103 H1).
 * Content-bearing orphan dirs are never `rm -rf` (#1105 R4 / constitution §10):
 * move to quarantine (runner-manual posture); empty dirs may be removed.
 */

import {
  existsSync,
  mkdirSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  unlinkSync,
} from "node:fs";
import { basename, join, resolve } from "node:path";

import { shWithClock } from "./externalCall.js";
import { isFileNotFound } from "./fsErrors.js";

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
 * Default quarantine root: `<clone>/.sandcastle/quarantine-orphans`.
 * Last-resort only when no ledgerDir is available — production callers with a
 * durable ledger MUST pass `<ledgerDir>/quarantine-orphans` via opts (#1105 R6).
 */
export function defaultQuarantineOrphansDir(repoPath: string): string {
  return join(repoPath, ".sandcastle", "quarantine-orphans");
}

/**
 * Age above which an `index.lock` is treated as abandoned wreckage and unlinked.
 * Fresh locks are left alone (git worktree add does not require clearing them).
 */
export const INDEX_LOCK_STALE_MS = 120_000;

export type WorktreePreflightGit = (args: readonly string[]) => string;

export type HealBeforeWorktreeCutOptions = {
  /** Isolation root (`<base>/<name>-<ts>`). Prefer `<ledgerDir>/quarantine-orphans`. */
  readonly quarantineBaseDir?: string;
};

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

/** Empty orphan → rm; content-bearing → mv to `<quarantineBase>/<basename>-<ts>`. */
export function quarantineOrRemoveOrphanDir(
  wtPath: string,
  quarantineBaseDir: string,
  nowMs: number = Date.now(),
): string | null {
  let entries: string[];
  try {
    entries = readdirSync(wtPath);
  } catch (err) {
    // Disappearance race only — EACCES / ENOTDIR / IO must propagate so heal
    // fails closed instead of continuing while the conflicting path remains
    // (#1105 R8 → misleading path-exists on later cut).
    if (isFileNotFound(err)) return null;
    throw err;
  }
  if (entries.length === 0) {
    rmSync(wtPath, { recursive: true, force: true });
    return null;
  }
  mkdirSync(quarantineBaseDir, { recursive: true });
  const dest = join(quarantineBaseDir, `${basename(wtPath)}-${nowMs}`);
  renameSync(wtPath, dest);
  return dest;
}

/**
 * Idempotent preflight before cutting `branch` under `repoPath`:
 * 1. heal dir↔metadata skew for the intended Sandcastle path only,
 * 2. clear that branch's orphan admin entry under `.git/worktrees/<name>`,
 * 3. clear a clearly-stale `index.lock` (fresh locks are left alone).
 *
 * Never runs repo-wide `git worktree prune` — in a family wave a sibling's
 * gitdir may look prunable to the host after container path rewrite; pruning
 * would delete the live sibling mid-run (#1105 R7 F1).
 *
 * `runGit` defaults to host `git -C repoPath`; RealBackend passes `this.sh` so
 * unit intercepts (worktree-cut / branch-fallback) stay on the same seam.
 */
export function healBeforeWorktreeCut(
  repoPath: string,
  branch: string,
  runGit: WorktreePreflightGit = (args) => defaultGit(repoPath, args),
  opts?: HealBeforeWorktreeCutOptions,
): void {
  const wtPath = sandcastleWorktreePathForBranch(repoPath, branch);
  const admin = worktreeAdminDirForBranch(repoPath, branch);
  const listed = listedWorktreePaths(repoPath, runGit);
  const inList = listed.has(normPath(wtPath));
  const dirExists = existsSync(wtPath);
  const quarantineBase =
    opts?.quarantineBaseDir ?? defaultQuarantineOrphansDir(repoPath);

  if (dirExists && !inList) {
    // Directory present / metadata absent — classic half-dead leftover.
    // Never rm content-bearing trees (constitution §10).
    quarantineOrRemoveOrphanDir(wtPath, quarantineBase);
  } else if (!dirExists && inList) {
    // Metadata present / directory absent — remove this worktree only.
    try {
      runGit(["worktree", "remove", "--force", wtPath]);
    } catch {
      // Targeted: drop only this name's admin entry (never repo-wide prune).
      if (existsSync(admin)) {
        rmSync(admin, { recursive: true, force: true });
      }
    }
  }

  // Orphan admin dir with no registered worktree for THIS name only.
  // Admin metadata is not worker output — safe to remove.
  if (existsSync(admin) && !listed.has(normPath(wtPath)) && !existsSync(wtPath)) {
    rmSync(admin, { recursive: true, force: true });
  }

  clearStaleIndexLock(repoPath);
}
