/**
 * Local git exclude helpers for orchestrator-owned runtime droppings.
 *
 * These patterns land in `.git/info/exclude` (never repo `.gitignore`) so
 * operational sidecars stay invisible to `git status --untracked-files=all`
 * without entering the review content surface (#1014).
 *
 * Single write primitive for orchestrator info/exclude updates — callers
 * choose best-effort ({@link ensureGitInfoExclude}) or throw-through
 * ({@link appendGitInfoExclude}).
 */

import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
} from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";

import { shWithClock } from "./externalCall.js";

/**
 * Directory trees the runner writes inside the dedicated iso clone:
 * - `.ledger-<issue>/` — single-slice telemetry + worker-logs at iso root
 * - `.sandcastle/` — sandcastle worktrees / steps / scratch
 *
 * Trailing slash = directory-only gitignore match (matches live #985 shape).
 */
export const ISO_OPERATIONAL_GIT_EXCLUDE_PATTERNS = [
  ".ledger-*/",
  ".sandcastle/",
] as const;

/**
 * Resolve the repo's local `info/exclude` path via `git rev-parse --git-path`
 * (worktree-safe; matches prior dispatchWorker / family-backend siblings).
 * Subprocess goes through the #884 externalCall chokepoint.
 */
function resolveGitInfoExcludePath(repoPath: string): string {
  const excludePath = shWithClock(
    "git",
    ["-C", repoPath, "rev-parse", "--git-path", "info/exclude"],
    { stage: "git-info-exclude" },
  );
  if (excludePath.length === 0) {
    throw new Error("git rev-parse --git-path info/exclude returned empty");
  }
  return isAbsolute(excludePath) ? excludePath : resolve(repoPath, excludePath);
}

/**
 * Append `pattern` to the repo's local info/exclude if not already present
 * (idempotent, CRLF-safe). Throws on resolve / IO failure.
 */
export function appendGitInfoExclude(
  repoPath: string,
  pattern: string,
): void {
  const abs = resolveGitInfoExcludePath(repoPath);
  mkdirSync(dirname(abs), { recursive: true });
  const existing = existsSync(abs) ? readFileSync(abs, "utf8") : "";
  if (existing.split(/\r?\n/).includes(pattern)) return;
  appendFileSync(
    abs,
    (existing.endsWith("\n") || existing === "" ? "" : "\n") + pattern + "\n",
    "utf8",
  );
}

/**
 * Best-effort append of `pattern` to `<repoPath>`'s local info/exclude.
 * Mock / non-git fixtures must not throw (silent swallow matches siblings).
 */
export function ensureGitInfoExclude(repoPath: string, pattern: string): void {
  try {
    appendGitInfoExclude(repoPath, pattern);
  } catch {
    // Best-effort only: production independent clones succeed; unit fixtures
    // that mock the clone path may lack a real .git tree.
  }
}

/**
 * Provision-time exclude for iso operational sidecars (#1014).
 * Throw-through: AC1 requires patterns present after provision — fail closed
 * so callers never mark the working repo ready without the excludes written.
 */
export function ensureIsoOperationalExcludes(repoPath: string): void {
  for (const pattern of ISO_OPERATIONAL_GIT_EXCLUDE_PATTERNS) {
    appendGitInfoExclude(repoPath, pattern);
  }
}
