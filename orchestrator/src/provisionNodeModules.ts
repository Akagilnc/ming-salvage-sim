/**
 * provisionNodeModules.ts — #746 host-side Node deps provisioning.
 *
 * ## Why shared-template clonefile (not a worktree pool)
 *
 * Issue #746 floated a warm worktree pool (N pre-provisioned trees, claim/return).
 * This MVP deliberately does **not** pool worktrees. Instead it clonefiles
 * (`cp -cR` / APFS clonefile(2)) a lockfile-matching `node_modules` from the
 * already-warm monorepo at `sourceRepo` (or family `depsTemplateRoot`) into the
 * slice worktree after the git cut.
 *
 * Reasons:
 * - The ~90s tax is almost entirely `npm ci`, not `git worktree add`. Swapping
 *   only the deps step removes that tax without a pool size policy, warm-up
 *   scheduler, claim/return protocol, or inventory GC.
 * - ADR 0024 keeps **one resident worktree per slice** as commit + crash-resume
 *   truth (ADR 0017). A pool of disposable/reusable trees would invent a second
 *   lifecycle next to that resident model (who owns dirty trees? when reclaim?).
 * - The host monorepo already has warm `node_modules`; clonefile is CoW-cheap on
 *   APFS and needs no long-lived pool state.
 *
 * Out of scope for this module: pool daemon, config surface, warm-up scheduler.
 *
 * ## Dirty-cache / staleness criterion
 *
 * Sole freshness signal = **SHA-256 of `package-lock.json` file bytes** on target
 * vs template (`lockfileFingerprint`). Match **and** template `node_modules`
 * present as a directory ⇒ clonefile allowed. Boundaries:
 * - No lock on either side → not clonefile (target uses `npm install`).
 * - Lock present but hashes differ → `npm ci` (wave mutated the lock; template
 *   tree is wrong deps).
 * - Template lacks `node_modules` / not a dir → `npm ci`/`install`.
 * - Clonefile command throws (non-APFS, no `cp -c`, I/O) → fall through to npm.
 * - **Never** mtime, presence-of-`node_modules` alone, or package.json hash.
 *
 * ## Relation to ADR 0024 resident worktree reap / clean
 *
 * This is host-side **deps only**. It does not create, dispose, pool, or prune
 * worktrees. Lifecycle stays ADR 0024 / 0017:
 * - Prepare still: find existing → fail-closed residue clean (`reset --hard` +
 *   `clean -fd`, **no** repo-level `worktree prune`) → return path; else cut
 *   resident worktree and **do not** `.close()` it.
 * - Reap only on terminal-success GC, never via normal-path disposal.
 * - Provision runs on **both** fresh cut and resident-reuse (after residue clean)
 *   so a reused tree whose modules were wiped by `clean -fd` (or never installed)
 *   is re-ensured without a full `npm ci` when the lock still matches source.
 * - Sandcastle prune stays Sandcastle's job inside the dedicated clone; the
 *   template root is the driver's `sourceRepo`, not a pooled worktree.
 */

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  existsSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
} from "node:fs";
import { isAbsolute, join, relative, resolve } from "node:path";

/** Same host-command seam shape as RealBackend / RealFamilyBackend `sh`. */
export type Sh = (file: string, args: string[], cwd?: string) => string;

export type ProvisionMethod = "clonefile" | "npm-ci" | "npm-install";

export interface ProvisionResult {
  readonly method: ProvisionMethod;
  readonly elapsedMs: number;
}

export interface ProvisionNodeModulesOptions {
  /** Project dir whose node_modules is the clone source (same package as target). */
  readonly templateProjectDir?: string;
  /** Host command runner; defaults to execFileSync. */
  readonly sh?: Sh;
}

function defaultSh(file: string, args: string[], cwd?: string): string {
  return execFileSync(file, args, {
    cwd,
    stdio: ["ignore", "pipe", "pipe"],
    encoding: "utf8",
  }).trim();
}

/**
 * SHA-256 of `package-lock.json` contents, or `undefined` when the lock is absent.
 * Used as the sole freshness signal (lockfile-exact — never mtime / presence heuristics).
 */
export function lockfileFingerprint(projectDir: string): string | undefined {
  const lockPath = join(projectDir, "package-lock.json");
  if (!existsSync(lockPath)) return undefined;
  try {
    const buf = readFileSync(lockPath);
    return createHash("sha256").update(buf).digest("hex");
  } catch {
    return undefined;
  }
}

/**
 * Map a target project dir onto the same relative path under `templateRoot`.
 * Returns undefined when the target is outside `targetRoot` or roots are missing.
 */
export function resolveTemplateProjectDir(
  targetProjectDir: string,
  opts: { readonly templateRoot?: string; readonly targetRoot?: string },
): string | undefined {
  const { templateRoot, targetRoot } = opts;
  if (templateRoot === undefined || targetRoot === undefined) return undefined;
  // Remote / non-path template sources cannot supply a local node_modules.
  if (templateRoot.includes("://")) return undefined;
  const absTarget = resolve(targetProjectDir);
  const absRoot = resolve(targetRoot);
  const rel = relative(absRoot, absTarget);
  if (rel === "" ) return resolve(templateRoot);
  if (rel.startsWith("..") || isAbsolute(rel)) return undefined;
  return join(resolve(templateRoot), rel);
}

/**
 * Node project directories under a monorepo root: the root itself (if it has a
 * package.json) plus each immediate child with a package.json. Skips missing
 * roots and non-directories. Used by prepareWorktree multi-package provision.
 */
export function listNodeProjectDirs(repoRoot: string): string[] {
  if (!existsSync(repoRoot)) return [];
  let isDir = false;
  try {
    isDir = statSync(repoRoot).isDirectory();
  } catch {
    return [];
  }
  if (!isDir) return [];

  const out: string[] = [];
  if (existsSync(join(repoRoot, "package.json"))) {
    out.push(repoRoot);
  }
  try {
    for (const e of readdirSync(repoRoot, { withFileTypes: true })) {
      if (!e.isDirectory()) continue;
      const name = String(e.name);
      if (name === "node_modules" || name.startsWith(".")) continue;
      const child = join(repoRoot, name);
      if (existsSync(join(child, "package.json"))) {
        out.push(child);
      }
    }
  } catch {
    return out;
  }
  return out;
}

/**
 * Whether target may safely receive template's node_modules via clonefile:
 * template has node_modules, both have package-lock.json, fingerprints equal.
 */
export function canClonefileNodeModules(
  targetProjectDir: string,
  templateProjectDir: string,
): boolean {
  const templateNm = join(templateProjectDir, "node_modules");
  if (!existsSync(templateNm)) return false;
  try {
    if (!statSync(templateNm).isDirectory()) return false;
  } catch {
    return false;
  }
  const targetHash = lockfileFingerprint(targetProjectDir);
  const templateHash = lockfileFingerprint(templateProjectDir);
  if (targetHash === undefined || templateHash === undefined) return false;
  return targetHash === templateHash;
}

/**
 * Ensure `targetProjectDir/node_modules` is ready for typecheck/test.
 *
 * 1. If a lockfile-matching template node_modules exists → `cp -cR` (APFS clonefile).
 * 2. Else → `npm ci` (lock present) or `npm install` (no lock).
 * 3. Clonefile failure → fall through to npm (non-APFS / permission / missing cp -c).
 */
export function provisionNodeModules(
  targetProjectDir: string,
  options: ProvisionNodeModulesOptions = {},
): ProvisionResult {
  const sh = options.sh ?? defaultSh;
  const started = Date.now();
  const hasLock = existsSync(join(targetProjectDir, "package-lock.json"));
  const template = options.templateProjectDir;

  if (template !== undefined && canClonefileNodeModules(targetProjectDir, template)) {
    const src = join(template, "node_modules");
    const dest = join(targetProjectDir, "node_modules");
    try {
      if (existsSync(dest)) {
        rmSync(dest, { recursive: true, force: true });
      }
      // macOS BSD cp: -c = clonefile(2), -R = recursive. Order `-cR` matches man examples.
      sh("cp", ["-cR", src, dest]);
      return { method: "clonefile", elapsedMs: Date.now() - started };
    } catch {
      // Non-APFS host, missing cp -c, or I/O fault → real install below.
    }
  }

  const npmArgs = hasLock ? (["ci"] as const) : (["install"] as const);
  sh("npm", [...npmArgs], targetProjectDir);
  return {
    method: hasLock ? "npm-ci" : "npm-install",
    elapsedMs: Date.now() - started,
  };
}

/**
 * Provision every Node subproject under `repoRoot`, mapping each onto the same
 * relative path under `templateRoot` (typically the source monorepo with warm
 * node_modules). Best-effort: missing template roots simply npm-install per project.
 */
export function provisionRepoNodeModules(
  repoRoot: string,
  options: {
    readonly templateRoot?: string;
    readonly sh?: Sh;
  } = {},
): readonly ProvisionResult[] {
  const projects = listNodeProjectDirs(repoRoot);
  const results: ProvisionResult[] = [];
  for (const project of projects) {
    const templateProjectDir = resolveTemplateProjectDir(project, {
      templateRoot: options.templateRoot,
      targetRoot: repoRoot,
    });
    results.push(
      provisionNodeModules(project, {
        templateProjectDir,
        sh: options.sh,
      }),
    );
  }
  return results;
}
