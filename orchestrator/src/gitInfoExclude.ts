/**
 * Local git exclude helpers for orchestrator-owned runtime droppings.
 *
 * These patterns land in `.git/info/exclude` (never repo `.gitignore`) so
 * operational sidecars stay invisible to `git status --untracked-files=all`
 * without entering the review content surface (#1014).
 */

import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
} from "node:fs";
import { dirname, join } from "node:path";

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
 * Append `pattern` to `<repoPath>/.git/info/exclude` if not already present.
 * Best-effort: mock / non-git fixtures must not throw.
 */
export function ensureGitInfoExclude(repoPath: string, pattern: string): void {
  try {
    const abs = join(repoPath, ".git", "info", "exclude");
    mkdirSync(dirname(abs), { recursive: true });
    const existing = existsSync(abs) ? readFileSync(abs, "utf8") : "";
    if (existing.split(/\r?\n/).includes(pattern)) return;
    appendFileSync(
      abs,
      (existing.endsWith("\n") || existing === "" ? "" : "\n") + pattern + "\n",
      "utf8",
    );
  } catch {
    // Best-effort only: production independent clones succeed; unit fixtures
    // that mock the clone path may lack a real .git tree.
  }
}

/** Provision-time exclude for iso operational sidecars (#1014). */
export function ensureIsoOperationalExcludes(repoPath: string): void {
  for (const pattern of ISO_OPERATIONAL_GIT_EXCLUDE_PATTERNS) {
    ensureGitInfoExclude(repoPath, pattern);
  }
}
