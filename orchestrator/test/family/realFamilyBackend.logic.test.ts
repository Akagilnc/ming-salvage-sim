/**
 * #291 RealFamilyBackend — the REAL {@link FamilyBackend} implementation, the
 * "真后端" behind the family seam #293 立 (control flow) leaves unfilled.
 *
 * The family layer's operations are each a few git/file ops or one `sc.run`:
 *   - mergeChildIntoFamilyBase → `git checkout <familyBase>` + `git merge --no-ff`
 *   - resolveMergeConflict     → one `sc.run` under the merger soul (injected seam)
 *   - appendFamilyLedger/read  → a sibling JSONL OUTSIDE the family base worktree
 *   - runFamilyVerify          → `npx tsc --noEmit` + `npx vitest run`
 *   - runIntegratedCmr         → a thin wrap of local `ak-cross-m-review` (seam)
 *   - openFamilyPr             → `gh pr create` (push family base + open PR; STOP)
 *   - recordAborted            → one phase-level `aborted` ledger append
 *   - escalateFamily           → a durable stuck-point record (resume entry)
 *   - ReconcileGit four predicates → `git rev-parse` / `--verify` / `merge-base`
 *
 * PURE / DETERMINISTIC parts (ledger JSONL, the git argv the merge/verify/cmr/pr
 * commands run, the reconcile predicate argv) are unit-tested here with:
 *   - REAL git in a `mktemp` repo (real `git merge` / `rev-parse` / `merge-base`),
 *   - a `sh`-intercepting / `sc.run`-intercepting subclass for the external side
 *     effects (the merger agent / `gh pr create` / `ak-cross-m-review`) — fakes
 *     verify the CALL CONTRACT; no real container, no real GitHub, no real push.
 */

import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import * as sc from "@ai-hero/sandcastle";
import {
  MERGER_SOUL,
  cmrOutcomeFromResult,
  mergerOutcomeFromResult,
  type MergerAuth,
  parseCmrOutcome,
  parseMergerOutcome,
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../src/family/realFamilyBackend.js";
import { familyEscalationState } from "../../src/family/ledger.js";
import { SANDBOX_SKILLS_DIR, SANDBOX_SOUL_ENV } from "../../src/realBackend.js";
import type {
  ConflictResolveRequest,
  FamilyVerifyRequest,
  IntegratedCmrRequest,
  IntegratedCmrResult,
} from "../../src/family/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");

/** Run a real git command in `cwd` and return trimmed stdout. */
function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}

/** Build a real temp git repo with an initial commit; return its path. */
function makeRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "rfb-"));
  git(dir, "init", "-q");
  git(dir, "config", "user.email", "t@t.t");
  git(dir, "config", "user.name", "t");
  git(dir, "config", "commit.gpgsign", "false");
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: dir });
  return dir;
}

/** Commit a file on the current branch; return the new HEAD SHA. */
function commitFile(repo: string, file: string, content: string): string {
  execFileSync("bash", ["-c", `printf '%s' '${content}' > '${join(repo, file)}'`]);
  git(repo, "add", file);
  execFileSync("git", ["commit", "-q", "-m", `add ${file}`], { cwd: repo });
  return git(repo, "rev-parse", "HEAD");
}

let repos: string[] = [];
// online R1 CodeRabbit: `opts()` mints a temp ledger dir per call — track them too,
// else they leak across the suite and accumulate over a long CI run.
let ledgerDirs: string[] = [];
function trackRepo(): string {
  const r = makeRepo();
  repos.push(r);
  return r;
}
afterEach(() => {
  for (const r of repos) rmSync(r, { recursive: true, force: true });
  for (const d of ledgerDirs) rmSync(d, { recursive: true, force: true });
  repos = [];
  ledgerDirs = [];
});

/** Default options pointing the Backend at a real repo + the real prompts dir. */
function opts(workingRepo: string, over: Partial<RealFamilyBackendOptions> = {}): RealFamilyBackendOptions {
  const ledgerDir = mkdtempSync(join(tmpdir(), "rfb-ledger-"));
  ledgerDirs.push(ledgerDir);
  return {
    workingRepo,
    familyBase: "family/293-base",
    ledgerDir,
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: realPromptsDir,
    imageName: "img",
    skillsMount: "/tmp/skills",
    ...over,
  };
}

// ═══════════════════════════════ 1. family ledger ═══════════════════════════

describe("RealFamilyBackend appendFamilyLedger / readFamilyLedger (#291 sibling JSONL)", () => {
  it("appends events to a sibling JSONL and reads them back in write order", async () => {
    const repo = trackRepo();
    const o = opts(repo);
    const b = new RealFamilyBackend(o);
    await b.appendFamilyLedger({ childIssue: 10, status: "merged" });
    await b.appendFamilyLedger({ childIssue: 11, status: "merged", childHead: "abc" });
    const read = await b.readFamilyLedger();
    expect(read).toEqual([
      { childIssue: 10, status: "merged" },
      { childIssue: 11, status: "merged", childHead: "abc" },
    ]);
    // It is a SIBLING file under the ledgerDir, OUTSIDE the family base worktree —
    // a worktree clean can never touch the resume / unblock truth.
    const raw = readFileSync(join(o.ledgerDir, "family-ledger.jsonl"), "utf8");
    expect(raw.trim().split("\n")).toHaveLength(2);
  });

  it("readFamilyLedger returns [] when no ledger exists yet", async () => {
    const b = new RealFamilyBackend(opts(trackRepo()));
    expect(await b.readFamilyLedger()).toEqual([]);
  });

  it("readFamilyLedger FAILS CLOSED on a present-but-unreadable ledger (NOT silently []) (codex R2)", async () => {
    // ENOENT (no file) → []. But a present-but-unreadable ledger (here: the path is
    // a DIRECTORY → EISDIR) must rethrow, never read as "no children merged" — that
    // would make reconcile re-merge already-landed children (decision 5 "不静默吞").
    const o = opts(trackRepo());
    // make the ledger path a directory so readFileSync throws EISDIR (not ENOENT).
    mkdirSync(join(o.ledgerDir, "family-ledger.jsonl"), { recursive: true });
    const b = new RealFamilyBackend(o);
    await expect(b.readFamilyLedger()).rejects.toThrow(/failed to read the family ledger/);
  });

  it("readEscalations FAILS CLOSED through the family ledger (codex R2)", async () => {
    const o = opts(trackRepo());
    mkdirSync(join(o.ledgerDir, "family-ledger.jsonl"), { recursive: true });
    const b = new RealFamilyBackend(o);
    await expect(b.readEscalations()).rejects.toThrow(/failed to read the family ledger/);
  });
});

// ═══════════════════════════════ 2. merge ═══════════════════════════════════

describe("RealFamilyBackend mergeChildIntoFamilyBase (#291 git merge --no-ff)", () => {
  it("clean merge: returns before/after/childHead, NOT conflicted; the merge commit lands", async () => {
    const repo = trackRepo();
    // family base: a branch off root with its own commit.
    git(repo, "checkout", "-q", "-b", "family/293-base");
    const baseBefore = git(repo, "rev-parse", "HEAD");
    // a child branch off root touching a DIFFERENT file (no conflict).
    git(repo, "checkout", "-q", "-b", "feat/child-10", "family/293-base");
    const childHead = commitFile(repo, "child10.txt", "child ten");
    // back on family base, with its OWN unrelated commit so --no-ff is a real merge.
    git(repo, "checkout", "-q", "family/293-base");
    const o = opts(repo);
    const b = new RealFamilyBackend(o);
    const res = await b.mergeChildIntoFamilyBase({ childIssue: 10, childBranch: "feat/child-10" });
    expect(res.conflicted ?? false).toBe(false);
    expect(res.familyHeadBefore).toBe(baseBefore);
    expect(res.childHead).toBe(childHead);
    expect(res.familyHead).toBe(git(repo, "rev-parse", "HEAD"));
    // a --no-ff merge → a NEW merge commit on the family base, distinct from before.
    expect(res.familyHead).not.toBe(baseBefore);
    // the child's file landed on the family base.
    expect(readFileSync(join(repo, "child10.txt"), "utf8")).toBe("child ten");
  });

  it("conflict: leaves the conflict state (no --abort) and returns conflicted:true with before/childHead", async () => {
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    commitFile(repo, "shared.txt", "FAMILY VERSION");
    const baseBefore = git(repo, "rev-parse", "HEAD");
    // child off ROOT (before the family base touched shared.txt) editing the SAME file.
    git(repo, "checkout", "-q", "-b", "feat/child-11", "HEAD~1");
    const childHead = commitFile(repo, "shared.txt", "CHILD VERSION");
    git(repo, "checkout", "-q", "family/293-base");
    const b = new RealFamilyBackend(opts(repo));
    const res = await b.mergeChildIntoFamilyBase({ childIssue: 11, childBranch: "feat/child-11" });
    expect(res.conflicted).toBe(true);
    expect(res.familyHeadBefore).toBe(baseBefore);
    expect(res.childHead).toBe(childHead);
    // NOT aborted — the conflict state is LEFT for resolveMergeConflict (an
    // in-progress merge with MERGE_HEAD present).
    expect(git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")).toBeTruthy();
  });

  it("a NON-conflict git merge failure (dirty worktree, no MERGE_HEAD) RETHROWS — never reported as conflicted", async () => {
    // Catching ALL non-zero `git merge` exits as `conflicted:true` would route a
    // broken/dirty repo into the LLM resolver (codex R1 + agy R1). Here the child
    // branch EXISTS (so the pre-merge rev-parse succeeds), but the family-base
    // worktree has an uncommitted edit to the SAME file the merge would touch →
    // `git merge` refuses ("local changes would be overwritten") and exits non-zero
    // WITHOUT creating a MERGE_HEAD. That must rethrow the git error and abort the
    // wave loudly — not be misreported as a content conflict.
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    commitFile(repo, "shared.txt", "BASE");
    git(repo, "checkout", "-q", "-b", "feat/child-13", "family/293-base");
    commitFile(repo, "shared.txt", "CHILD EDIT");
    git(repo, "checkout", "-q", "family/293-base");
    // dirty the family-base worktree: an uncommitted edit to the file the merge touches.
    execFileSync("bash", ["-c", `printf '%s' 'UNCOMMITTED' > '${join(repo, "shared.txt")}'`]);
    const b = new RealFamilyBackend(opts(repo));
    await expect(
      b.mergeChildIntoFamilyBase({ childIssue: 13, childBranch: "feat/child-13" }),
    ).rejects.toThrow();
    // and the repo was NOT left mid-merge (no MERGE_HEAD → not a false "conflicted").
    expect(() => git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")).toThrow();
  });
});

// ═══════════════════════════════ 3. ReconcileGit ════════════════════════════

describe("RealFamilyBackend ReconcileGit predicates (#291 real git)", () => {
  it("liveFamilyHead / childHeadExists / isAncestor over real history", async () => {
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    const baseHead = git(repo, "rev-parse", "HEAD");
    git(repo, "checkout", "-q", "-b", "feat/child-20", "family/293-base");
    const childHead = commitFile(repo, "c20.txt", "x");
    git(repo, "checkout", "-q", "family/293-base");
    // merge the child so its head is an ancestor of the live family head.
    execFileSync("git", ["merge", "--no-ff", "-m", "merge 20", "feat/child-20"], { cwd: repo });
    const o = opts(repo);
    const b = new RealFamilyBackend(o);
    const recon = b.reconcileGit();
    expect(await recon.liveFamilyHead()).toBe(git(repo, "rev-parse", "HEAD"));
    const exists = await recon.childHeadExists(20, "feat/child-20");
    expect(exists.exists).toBe(true);
    expect(exists.childHead).toBe(childHead);
    // childHead IS an ancestor of the (merged) live family head.
    expect(await recon.isAncestor(childHead, git(repo, "rev-parse", "HEAD"))).toBe(true);
    // baseHead (before the merge) is also an ancestor of live.
    expect(await recon.isAncestor(baseHead, git(repo, "rev-parse", "HEAD"))).toBe(true);
    // a never-merged sibling's head is NOT an ancestor of live.
    git(repo, "checkout", "-q", "-b", "feat/child-21", "family/293-base");
    const sibling = commitFile(repo, "c21.txt", "y");
    expect(await recon.isAncestor(sibling, git(repo, "rev-parse", "family/293-base"))).toBe(false);
  });

  it("childHeadExists reports exists:false for an absent branch", async () => {
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    const recon = new RealFamilyBackend(opts(repo)).reconcileGit();
    const r = await recon.childHeadExists(99, "feat/child-99");
    expect(r.exists).toBe(false);
    expect(r.childHead).toBeUndefined();
  });

  it("isAncestor RE-THROWS an operational git error (bad object → exit 128), never silent false (online R1 CodeRabbit)", async () => {
    // `git merge-base --is-ancestor` exits 1 for a legit NOT-ancestor but 128 for an
    // OPERATIONAL failure (a bad/unknown object, a broken repo). The catch must
    // distinguish: exit 1 → false (the predicate), anything else → re-throw. Else a
    // bad SHA / broken repo reads as "not an ancestor" → reconcile mis-judges the
    // crash window (could re-merge an already-landed child, or trust a stale base).
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    const recon = new RealFamilyBackend(opts(repo)).reconcileGit();
    const live = git(repo, "rev-parse", "HEAD");
    // an all-zero (null) object never resolves → `--is-ancestor` exits 128 (fatal).
    await expect(recon.isAncestor("0".repeat(40), live)).rejects.toThrow();
    // a REAL not-ancestor (a fresh sibling commit) still returns false (exit 1).
    git(repo, "checkout", "-q", "-b", "feat/child-88", "family/293-base");
    const sibling = commitFile(repo, "c88.txt", "z");
    expect(await recon.isAncestor(sibling, live)).toBe(false);
  });

  it("childHeadExists with NO branch derives it from the issue (the production call shape) — the 补账 predicate is not dead", async () => {
    // The production reconcile caller passes only the ISSUE (reconcile.ts:
    // `git.childHeadExists(child.issue)`), no branch. Before the fix this returned
    // `{exists:false}` → every already-landed child read as absent → re-merge
    // (double-merge, codex R1). It must instead derive the runner branch
    // `feat/issue-<n>` (#1: neutral prefix, no hardcoded epic) and find the real head.
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    git(repo, "checkout", "-q", "-b", "feat/issue-77", "family/293-base");
    const childHead = commitFile(repo, "c77.txt", "x");
    git(repo, "checkout", "-q", "family/293-base");
    const recon = new RealFamilyBackend(opts(repo)).reconcileGit();
    const r = await recon.childHeadExists(77); // NO branch — derived from the issue
    expect(r.exists).toBe(true);
    expect(r.childHead).toBe(childHead);
  });

  it("runFamilyVerify runs the project's npm typecheck+test from verifyCwd, NOT the clone root (online R2 Codex P1 / #5)", async () => {
    // The clone is the FULL repo; a project's package.json/scripts live under a
    // subdir (e.g. `<clone>/orchestrator`). The verify commands must run from
    // `verifyCwd`, and (#5) be the PROJECT'S OWN npm scripts, not a hardcoded npx.
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override depsInstalled(_cwd: string): boolean {
        return true; // deps present → focus the assertion on the verify commands
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"]; // orchestrator's scripts
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" })).runVerifyForTest();
    expect(calls.map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
    expect(calls.every((c) => c.cwd === "/clone/root/orchestrator")).toBe(true);
  });

  it("#3: installs deps (npm ci) in verifyCwd BEFORE the npm verify scripts when node_modules is absent", async () => {
    // The dogfood death (#3): verify ran against a FRESH clone with no node_modules
    // → "This is not the tsc command..." → always verify_failed. The fix installs
    // deps first. The spy reports node_modules ABSENT, so a `npm ci` (or install)
    // must precede the project's verify scripts, in the SAME cwd.
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override depsInstalled(_cwd: string): boolean {
        return false; // node_modules ABSENT in the fresh clone
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" })).runVerifyForTest();
    // First command must be the dep install in verifyCwd.
    expect(calls[0].file).toBe("npm");
    expect(["ci", "install"]).toContain(calls[0].args[0]);
    expect(calls[0].cwd).toBe("/clone/root/orchestrator");
    // Then the project's verify scripts, still in verifyCwd.
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
    expect(calls.slice(1).every((c) => c.cwd === "/clone/root/orchestrator")).toBe(true);
  });

  it("#3: skips the dep install when node_modules already exists (idempotent, no re-install churn)", async () => {
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override depsInstalled(_cwd: string): boolean {
        return true; // node_modules present → no install
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" })).runVerifyForTest();
    // No `npm ci`/`npm install` ran — only the project's verify scripts.
    expect(
      calls.some((c) => c.file === "npm" && (c.args[0] === "ci" || c.args[0] === "install")),
    ).toBe(false);
    expect(calls.map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
  });

  it("#5/R1-T3: runs web's OWN scripts — `npm run build` (its tsc check) then `npm test` (jsdom), never raw npx", async () => {
    // #5: web/'s test = `vitest run --environment jsdom`; a hardcoded `npx vitest run`
    // dropped `--environment jsdom` → `document is not defined`. R1 T3 (codex): web/
    // has NO `typecheck` script — its TS check lives in `build` (`tsc -b && vite build`).
    // So type-check must fall back to `npm run build`, NOT be silently skipped (else a
    // web change with TS errors passes verify as long as Vitest does).
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override depsInstalled(_cwd: string): boolean {
        return true;
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["dev", "build", "test", "preview"]; // web's scripts — NO `typecheck`
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/web" })).runVerifyForTest();
    // No `typecheck` script → fall back to `npm run build` (web's tsc check), THEN
    // `npm test` (its own --environment jsdom). NEVER a raw `npx`.
    expect(calls.map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run build",
      "npm test",
    ]);
    expect(calls.some((c) => c.file === "npx")).toBe(false);
    expect(calls.every((c) => c.cwd === "/clone/root/web")).toBe(true);
  });

  it("R1-T2: a diff touching NO Node subproject (cwd undefined) → verify is a no-op, never npm in the clone root", async () => {
    // codex R1 T2: `inferVerifyCwd` returns undefined for a docs/content/root-only
    // diff. The old `?? workingRepo` fallback ran `npm install` + scripts in the clone
    // ROOT (no package.json) → verify_failed for valid non-code changes. Now: skip.
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    // No verifyCwd, and resolveVerifyCwd returns undefined (non-Node diff).
    new SpyBackend(opts("/clone/root", { resolveVerifyCwd: () => undefined })).runVerifyForTest();
    expect(calls).toEqual([]); // nothing installed, nothing run
  });

  it("R3: a SINGLE-project repo (package.json at the clone ROOT) falls back to workingRepo verify", () => {
    // gemini R3: dropping the `?? workingRepo` fallback made single-project repos
    // (package.json at root, no subproject) skip verify entirely. Restore the
    // fallback — but ONLY when the root IS a Node project (multi-project non-Node
    // root still skips, R1 T2).
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true; // the clone root has a package.json (single-project repo)
      }
      protected override depsInstalled(_cwd: string): boolean {
        return true;
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["test"];
      }
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    // No verifyCwd; resolver undefined (no subproject) → root is Node → verify at root.
    new SpyBackend(opts("/clone/root", { resolveVerifyCwd: () => undefined })).runVerifyForTest();
    expect(calls.map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual(["npm test"]);
    expect(calls.every((c) => c.cwd === "/clone/root")).toBe(true);
  });

  it("R1-T3: an EXPLICIT verifyCwd that is NOT a Node project FAILS CLOSED (throws), never silent-passes", () => {
    // codex R1 T3: a docs/content/root-only diff (inferred-undefined) legitimately
    // skips, but an EXPLICITLY-set verifyCwd pointing at a non-Node dir is a caller
    // misconfig — it must NOT be treated like "nothing to verify" and green-light an
    // un-verified merge. (An inference-FAILURE fails closed via familyDiffFiles, which
    // no longer swallows git errors.)
    class SpyBackend extends RealFamilyBackend {
      protected override sh(): string {
        return "";
      }
      protected override isNodeProject(_cwd: string): boolean {
        return false; // explicit cwd has no package.json
      }
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    expect(() =>
      new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/not-node" })).runVerifyForTest(),
    ).toThrow(/not a Node project/i);
  });

  it("R1-T1: depsInstalled is STALE (reinstall) when a manifest is newer than node_modules", () => {
    // gemini R1 T1: a bare node_modules-exists check skips installing a dep a child
    // PR added (package.json/lock newer than the last install) → verify on stale deps.
    const proj = mkdtempSync(join(tmpdir(), "verify-stale-"));
    const nm = join(proj, "node_modules");
    const pkg = join(proj, "package.json");
    mkdirSync(nm, { recursive: true });
    writeFileSync(pkg, "{}");
    class Probe extends RealFamilyBackend {
      depsInstalledForTest(cwd: string): boolean {
        return this.depsInstalled(cwd);
      }
    }
    const be = new Probe(opts("/clone/root"));
    // Deterministic mtimes (R3 coderabbit: don't rely on write-order timing — equal
    // mtimes are possible on some filesystems). manifest NEWER than node_modules → stale.
    utimesSync(nm, new Date(1000), new Date(1000));
    utimesSync(pkg, new Date(2000), new Date(2000));
    expect(be.depsInstalledForTest(proj)).toBe(false); // stale → reinstall
    // node_modules NEWER than the manifest → fresh.
    utimesSync(nm, new Date(3000), new Date(3000));
    expect(be.depsInstalledForTest(proj)).toBe(true);
  });

  it("familyBaseStartHead returns the recorded start head", async () => {
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    const start = git(repo, "rev-parse", "HEAD");
    const recon = new RealFamilyBackend(opts(repo, { familyBaseStartHead: start })).reconcileGit();
    expect(await recon.familyBaseStartHead()).toBe(start);
  });

  it("familyBaseStartHead THROWS when no start head was recorded — never falls back to the live head (codex R3)", async () => {
    // The empty-ledger crash-window net compares liveHead to startHead. Falling back
    // to the CURRENT live head would make them trivially equal → the net is silently
    // disabled (fail-open). With no recorded start head it must throw, not degrade.
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    const recon = new RealFamilyBackend(opts(repo)).reconcileGit(); // no familyBaseStartHead
    await expect(recon.familyBaseStartHead()).rejects.toThrow(/no familyBaseStartHead was recorded/);
  });
});

// ════════ 3b. construction-time prompt validation (gap g, same-type C-3) ═══════
//
// RealBackend (single slice) validates promptsDir at construction (C-3): every
// REFERENCED_PROMPT_FILES entry, derived from the worker specs, must exist or the
// constructor throws — a missing prompt surfaces THERE, not deep in the first
// sandbox.run(). RealFamilyBackend lazily resolves its family prompts
// (integrated CMR pass prompts / family_ship.md / merger_resolve_conflict.md) at dispatch
// time, so a missing one would only blow up at run time. These tests pin the
// SAME construction-time net at the family layer.
describe("RealFamilyBackend construction-time prompt validation (gap g, same-type C-3)", () => {
  /** A promptsDir holding exactly the named family prompt files. */
  function promptsDirWith(files: string[]): string {
    const dir = mkdtempSync(join(tmpdir(), "rfb-prompts-"));
    ledgerDirs.push(dir); // reuse the afterEach cleanup list
    for (const f of files) {
      execFileSync("bash", ["-c", `printf '%s' 'x' > '${join(dir, f)}'`]);
    }
    return dir;
  }

  it("throws when the family promptsDir is missing a family prompt file", () => {
    const repo = trackRepo();
    // Has integrated CMR pass prompts + merger_resolve_conflict.md but NOT family_ship.md.
    const dir = promptsDirWith([
      "integrated_cmr_completeness.md",
      "integrated_cmr_correctness.md",
      "merger_resolve_conflict.md",
    ]);
    expect(() => new RealFamilyBackend(opts(repo, { promptsDir: dir }))).toThrow(
      /family_ship\.md/,
    );
  });

  it("throws when promptsDir is a relative path (Sandcastle resolves promptFile against process.cwd())", () => {
    const repo = trackRepo();
    expect(() => new RealFamilyBackend(opts(repo, { promptsDir: "prompts" }))).toThrow(
      /ABSOLUTE/,
    );
  });

  it("throws when promptsDir does not exist", () => {
    const repo = trackRepo();
    expect(() =>
      new RealFamilyBackend(opts(repo, { promptsDir: join(tmpdir(), "rfb-does-not-exist-xyz") })),
    ).toThrow(/does not exist/);
  });

  it("constructs cleanly when all 3 family prompts are present (the real prompts dir)", () => {
    const repo = trackRepo();
    expect(() => new RealFamilyBackend(opts(repo))).not.toThrow();
  });
});

// ═══════════════════ 4. resolveMergeConflict (sc.run seam) ═══════════════════

/** A subclass that fakes the external seams (merger agent / verify / cmr / sh). */
class FakeSeamsBackend extends RealFamilyBackend {
  mergerOutcome: { resolved: boolean; reason?: string } = { resolved: true };
  mergerCalls: ConflictResolveRequest[] = [];
  verifyOutcome: "green" | "red" = "green";
  verifyCalls: FamilyVerifyRequest[] = [];
  cmrResult: IntegratedCmrResult = { converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] };
  cmrCalls: IntegratedCmrRequest[] = [];
  shCalls: Array<{ file: string; args: string[] }> = [];
  prViewResponse: unknown = {
    baseRefName: "main",
    headRefName: "family/293-base",
    headRefOid: " pr-head-1 ",
    state: "OPEN",
  };
  mergeInProgressFake = false;
  // STATEFUL fake of the family-base ref so the resolve postcondition (the family
  // base ref moved past familyHeadBefore + child is its ancestor) is exercised
  // realistically. `rev-parse <familyBase>` returns familyBaseHeadFake; running the
  // merger ADVANCES it to resolvedHeadFake (a landed merge moves the family base
  // ref). The default models a clean LANDED resolve.
  familyBaseHeadFake = "base-head"; // rev-parse <familyBase> — current value (mutated by the merger)
  resolvedHeadFake = "resolved-head"; // what the family base ref advances to on a landed resolve
  childHeadFake = "child-head"; // rev-parse <childBranch>
  childLandedFake = true; // isAncestorOf(childHead, familyBase ref)
  mergerLandsOnFamilyBase = true; // does running the merger advance the family base ref?

  protected override async runMergerAgent(req: ConflictResolveRequest) {
    this.mergerCalls.push(req);
    // A real landed resolve advances the family base ref; a misbehaving agent that
    // aborted/reset (mergerLandsOnFamilyBase=false) leaves it unmoved.
    if (this.mergerOutcome.resolved && this.mergerLandsOnFamilyBase) {
      this.familyBaseHeadFake = this.resolvedHeadFake;
    }
    return this.mergerOutcome;
  }
  protected override runVerifyCommands(req: FamilyVerifyRequest): void {
    this.verifyCalls.push(req);
    if (this.verifyOutcome === "red") {
      throw new Error("Command failed: npx vitest run\n 3 failed | 507 passed");
    }
  }
  protected override async runCmr(req: IntegratedCmrRequest) {
    this.cmrCalls.push(req);
    return this.cmrResult;
  }
  protected override mergeInProgress(_repo: string): boolean {
    return this.mergeInProgressFake;
  }
  protected override isAncestorOf(_ancestor: string, _descendant: string, _repo: string): boolean {
    return this.childLandedFake;
  }
  // Intercept the git/gh/npx subprocess seam so no real command runs.
  protected override sh(file: string, args: string[], _cwd?: string): string {
    this.shCalls.push({ file, args });
    if (file === "git" && args[0] === "rev-parse") {
      // rev-parse <familyBase> → the (stateful) family base ref; rev-parse HEAD →
      // wherever HEAD is; rev-parse <childBranch> → the child head. The resolve
      // postcondition reads the FAMILY BASE REF (codex R3), so familyHeadBefore and
      // the post-resolve familyHead both come from familyBaseHeadFake — which the
      // merger advances only on a landed resolve.
      if (args[1] === this.familyBase) return this.familyBaseHeadFake;
      if (args[1] === "HEAD") return this.resolvedHeadFake;
      return this.childHeadFake;
    }
    if (file === "gh" && args[0] === "pr" && args[1] === "create") {
      return "https://github.com/Akagilnc/ming-salvage-sim/pull/777";
    }
    if (file === "gh" && args[0] === "pr" && args[1] === "view") {
      return JSON.stringify(this.prViewResponse);
    }
    return "";
  }

  // the configured family base (RealFamilyBackend.opts is protected → accessible).
  private get familyBase(): string {
    return this.opts.familyBase;
  }

  // Expose the protected sandbox-config seam so the merger soul injection +
  // skills-mount path are unit-testable without a real container.
  public sandboxConfig() {
    return this.mergerSandboxConfig({});
  }

  public verifyShipPr(pr: string, familyBase: string) {
    return this.verifyFamilyShipPr({ pr, familyBase });
  }
}

describe("RealFamilyBackend resolveMergeConflict (#291 sc.run merger seam)", () => {
  it("resolved agent → returns the resolved head (NOT conflicted); runs ONE merger agent", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: true };
    b.mergeInProgressFake = false; // the agent committed the merge
    // landed state: HEAD moved past familyHeadBefore + child is an ancestor (defaults).
    const res = await b.resolveMergeConflict({ childIssue: 10, childBranch: "feat/child-10" });
    expect(b.mergerCalls).toEqual([{ childIssue: 10, childBranch: "feat/child-10" }]);
    expect(res.conflicted ?? false).toBe(false);
    expect(res.familyHead).toBe("resolved-head");
  });

  it("agent escalated/failed → THROWS (the merger never records `merged`)", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: false, reason: "needs a product decision on field X" };
    await expect(
      b.resolveMergeConflict({ childIssue: 11, childBranch: "feat/child-11" }),
    ).rejects.toThrow(/did not resolve|product decision/i);
  });

  it("agent CLAIMED resolved but left the merge in-progress → still-conflicted result (never looks clean)", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: true };
    b.mergeInProgressFake = true; // MERGE_HEAD still present
    const res = await b.resolveMergeConflict({ childIssue: 12, childBranch: "feat/child-12" });
    expect(res.conflicted).toBe(true);
  });

  it("agent CLAIMED resolved but the merge did NOT land on the family base (abort/reset) → still-conflicted (codex R2)", async () => {
    // The dangerous false-clean: the agent says resolved:true and there is no
    // MERGE_HEAD, but it actually aborted/reset — the FAMILY BASE REF never moved
    // past familyHeadBefore and the child never landed. The old postcondition (only
    // !mergeInProgress) would return a CLEAN result → merger records a `merged`
    // ledger entry for a child that was never merged. The fix verifies git truth.
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: true };
    b.mergeInProgressFake = false; // no MERGE_HEAD…
    b.mergerLandsOnFamilyBase = false; // …but the family base ref stays at familyHeadBefore
    const res = await b.resolveMergeConflict({ childIssue: 13, childBranch: "feat/child-13" });
    expect(res.conflicted).toBe(true);
  });

  it("agent CLAIMED resolved, family base moved, but the child is NOT its ancestor → still-conflicted (codex R2)", async () => {
    // The family base moved (some commit landed) but it is NOT this child's merge —
    // the child head is not an ancestor of the new family base. Must not look clean.
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: true };
    b.mergeInProgressFake = false;
    b.childLandedFake = false; // family base moved, but the child is not an ancestor
    const res = await b.resolveMergeConflict({ childIssue: 14, childBranch: "feat/child-14" });
    expect(res.conflicted).toBe(true);
  });

  it("agent landed the child on the WRONG ref (HEAD moved, but the FAMILY BASE is unmoved) → still-conflicted (codex R3)", async () => {
    // A misbehaving agent checked out another branch / detached HEAD and committed
    // the child THERE: HEAD moved and the child is an ancestor of HEAD, but the
    // family base ref the next verify checks out is unmoved. Reading the post-state
    // off HEAD (the old fix) would look clean → phantom `merged`. Pinning to the
    // FAMILY BASE REF catches it: the family base did not move → conflicted.
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: true };
    b.mergeInProgressFake = false;
    b.mergerLandsOnFamilyBase = false; // family base ref stays put…
    b.resolvedHeadFake = "landed-on-some-other-ref"; // …even though HEAD moved elsewhere
    b.childLandedFake = true; // and the child IS an ancestor of that wrong HEAD
    const res = await b.resolveMergeConflict({ childIssue: 15, childBranch: "feat/child-15" });
    expect(res.conflicted).toBe(true);
  });
});

describe("RealFamilyBackend mergerSandbox baked-soul injection (#291 F28 / ADR 0022)", () => {
  // F28: the merger conflict fallback follows the "one mirror new soul" model —
  // the merger soul must be selected the SAME way coder/reviewer are: a baked soul
  // ACTIVATED via the ORCHESTRATOR_SOUL env (RealBackend.box), NOT a prompt-only
  // role. Before the fix mergerSandbox() injected NO env, so ORCHESTRATOR_SOUL was
  // never set → the merger ran under whatever default soul the image entrypoint
  // picked, not the merger soul.
  it("injects ORCHESTRATOR_SOUL=merger via the same env mechanism as coder/reviewer", () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    const cfg = b.sandboxConfig();
    expect(cfg.env?.[SANDBOX_SOUL_ENV]).toBe(MERGER_SOUL);
    expect(MERGER_SOUL).toBe("merger");
  });

  it("uses the profile image and does NOT mount host skills (baked skills win, #334)", () => {
    // #334 (ADR 0026 / cross-slice note): the runtime host skills bind-mount onto
    // SANDBOX_SKILLS_DIR is DROPPED — the 2b image BAKES `resolving-merge-conflicts`
    // (+ its closure), so a runtime mount there would SHADOW the baked skill,
    // pulling the merger back to host state (the reproducibility regression). The
    // merger soul finds the skill in the IMAGE, not a host mount.
    const o = opts(trackRepo(), { imageName: "profile-img", skillsMount: "/host/skills" });
    const b = new FakeSeamsBackend(o);
    const cfg = b.sandboxConfig();
    expect(cfg.imageName).toBe("profile-img");
    expect(
      cfg.mounts.some((m) => m.sandboxPath === SANDBOX_SKILLS_DIR),
    ).toBe(false);
  });
});

describe("parseMergerOutcome (#291 pure)", () => {
  it("parses a resolved tag", () => {
    expect(
      parseMergerOutcome('blah\n<merger>{"resolved": true, "tradeoffs": ""}</merger>\nMERGER_STEP_COMPLETE'),
    ).toEqual({ resolved: true });
  });
  it("parses an escalate tag, surfacing the reason", () => {
    const out = parseMergerOutcome(
      '<merger>{"resolved": false, "escalate": {"reason": "ambiguous", "diagnosis": "needs decision"}}</merger>',
    );
    expect(out.resolved).toBe(false);
    expect(out.reason).toContain("ambiguous");
  });
  it("no tag → not resolved", () => {
    expect(parseMergerOutcome("nothing here").resolved).toBe(false);
  });
  it("takes the LAST tag when the agent iterated", () => {
    const out = parseMergerOutcome(
      '<merger>{"resolved": false, "escalate": {"reason": "first"}}</merger>' +
        '<merger>{"resolved": true}</merger>',
    );
    expect(out).toEqual({ resolved: true });
  });
  it("a non-object JSON payload (null / true / number) is unresolved, NOT a crash", () => {
    // `JSON.parse("null")` succeeds and returns null; the old code then read
    // `parsed.resolved` → TypeError OUTSIDE the try/catch, crashing the parent
    // (agy R1). Any non-object payload must be a safe unresolved-with-reason.
    expect(parseMergerOutcome("<merger>null</merger>")).toEqual({
      resolved: false,
      reason: "merger agent <merger> tag was not a JSON object",
    });
    expect(parseMergerOutcome("<merger>true</merger>").resolved).toBe(false);
    expect(parseMergerOutcome("<merger>42</merger>").resolved).toBe(false);
  });

  // ── Finding A (integ-cmr int-r1): STRICT shape, mirroring shipOutcome ─────────
  // merger_resolve_conflict.md: "must match the shape above exactly". A
  // resolved:true carrying extra/mixed keys (e.g. an escalate verdict) must NOT
  // count as a clean resolve — fail-CLOSED to unresolved.
  describe("Finding A — strict shape (resolved:true rejects extra/mixed keys)", () => {
    it("resolved:true carrying an escalate ⇒ NOT resolved (mixed payload)", () => {
      const out = parseMergerOutcome(
        '<merger>{"resolved": true, "escalate": {"reason": "r", "diagnosis": "d"}}</merger>',
      );
      expect(out.resolved).toBe(false);
    });

    it("resolved:true carrying an unknown EXTRA key ⇒ NOT resolved (strict)", () => {
      expect(
        parseMergerOutcome('<merger>{"resolved": true, "junk": 1}</merger>').resolved,
      ).toBe(false);
    });

    it("resolved as a NON-boolean ⇒ NOT resolved", () => {
      expect(parseMergerOutcome('<merger>{"resolved": "true"}</merger>').resolved).toBe(
        false,
      );
    });

    it("still accepts the LEGAL success shapes (regression: with/without tradeoffs)", () => {
      expect(parseMergerOutcome('<merger>{"resolved": true}</merger>')).toEqual({
        resolved: true,
      });
      expect(
        parseMergerOutcome('<merger>{"resolved": true, "tradeoffs": "picked left"}</merger>'),
      ).toEqual({ resolved: true });
    });

    it("still surfaces a legal escalate (regression)", () => {
      const out = parseMergerOutcome(
        '<merger>{"resolved": false, "escalate": {"reason": "ambiguous", "diagnosis": "needs decision"}}</merger>',
      );
      expect(out.resolved).toBe(false);
      expect(out.reason).toContain("ambiguous");
    });
  });
});

describe("parseCmrOutcome accepted suppression contract", () => {
  it("prefers a runner-owned outcome sidecar over malformed cmr stdout", () => {
    const dir = mkdtempSync(join(tmpdir(), "cmr-outcome-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        converged: true,
        successfulLegs: ["gpt-5.5"],
        skippedLegs: [
          { slug: "opus", reason: "not configured for this test" },
          { slug: "agy", reason: "not configured for this test" },
        ],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        evidencePaths: ["cmr/review.json"],
      }) + "\n",
      "utf8",
    );

    const outcome = cmrOutcomeFromResult({
      completionSignal: "CMR_STEP_COMPLETE",
      stdout: "<cmr>not json</cmr>\nCMR_STEP_COMPLETE",
      outcomePath,
      cmrReviewLegs: [
        { family: "claude", slug: "opus" },
        { family: "codex", slug: "gpt-5.5" },
        { family: "gemini", slug: "agy" },
      ],
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      successfulLegs: ["gpt-5.5"],
    });
  });

  it("parses cmr sidecar payloads directly when free-form text contains a cmr tag delimiter", () => {
    const dir = mkdtempSync(join(tmpdir(), "cmr-outcome-delimiter-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        escalate: {
          reason: "review unavailable",
          diagnosis: "diagnosis quoted the literal </cmr> delimiter",
        },
      }) + "\n",
      "utf8",
    );

    const outcome = cmrOutcomeFromResult({
      completionSignal: "CMR_STEP_COMPLETE",
      stdout: "<cmr>not json</cmr>\nCMR_STEP_COMPLETE",
      outcomePath,
    });

    expect(outcome).toEqual({
      kind: "escalate",
      reason: "review unavailable",
      diagnosis: "diagnosis quoted the literal </cmr> delimiter",
    });
  });

  it("fails closed instead of falling back to stdout when the cmr outcome sidecar is malformed", () => {
    const dir = mkdtempSync(join(tmpdir(), "cmr-outcome-bad-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const outcome = cmrOutcomeFromResult({
      completionSignal: "CMR_STEP_COMPLETE",
      stdout:
        '<cmr>{"converged": true, "successfulLegs": ["gpt-5.5"], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": []}</cmr>',
      outcomePath,
      cmrReviewLegs: [{ family: "codex", slug: "gpt-5.5" }],
    });

    expect(outcome.kind).toBe("malformed");
    if (outcome.kind === "malformed") expect(outcome.reason).toContain("sidecar");
  });

  it("derives redundant accepted_suppressed finding fields from the finding payload", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: false,
      reason: "accepted suppression remains",
      successfulLegs: ["gpt-5.5"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      evidencePaths: ["cmr/review.json"],
      findings: [
        {
          severity: "medium",
          category: "correctness",
          claim_quote: "Known accepted gap",
          location: "orchestrator/src/family/verifyCmr.ts:42",
          suggested_fix: "keep the bounded suppression",
          action: "wont_fix",
          disposition: {
            kind: "accepted_suppressed",
            source: "#445 owner answer",
            scope: "orchestrator family CMR",
            reason: "Owner accepted this bounded risk.",
            boundedReopen: "reopen if the same scope regresses",
          },
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      converged: false,
      findings: [
        expect.objectContaining({
          disposition_reason: "Owner accepted this bounded risk.",
          disposition: expect.objectContaining({
            kind: "accepted_suppressed",
            findingIdentity:
              "correctness|orchestrator/src/family/verifycmr.ts:42|known accepted gap",
          }),
        }),
      ],
    });
  });

  it("normalizes accepted_suppressed findings with canonical disposition reason first", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: false,
      reason: "accepted suppression remains",
      successfulLegs: ["gpt-5.5"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      evidencePaths: ["cmr/review.json"],
      findings: [
        {
          severity: "medium",
          category: "correctness",
          claim_quote: "Known accepted gap",
          location: "orchestrator/src/family/verifyCmr.ts:42",
          suggested_fix: "keep the bounded suppression",
          action: "wont_fix",
          disposition_reason: "legacy fallback should not win",
          disposition: {
            kind: "accepted_suppressed",
            source: "#445 owner answer",
            scope: "orchestrator family CMR",
            reason: "Owner accepted this bounded risk.",
            boundedReopen: "reopen if the same scope regresses",
          },
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.findings?.[0]?.disposition_reason).toBe(
      "Owner accepted this bounded risk.",
    );
  });

  it("rejects accepted_suppressed prior dispositions that omit reason", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.5"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: ["correctness|src/x.ts:1|accepted"],
      evidencePaths: ["cmr/review.json"],
      priorFindingDispositions: [
        {
          identityKey: "correctness|src/x.ts:1|accepted",
          status: "accepted_suppressed",
          source: "#445 owner answer",
          scope: "runner review/fix loop",
          boundedReopen: "reopen if the same scope regresses",
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      kind: "malformed",
      reason: expect.stringContaining(
        "cmr worker <cmr> tag matched no valid shape",
      ),
    });
  });

  it("rejects converged CMR verdicts that omit evidence paths", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.5"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      kind: "malformed",
      reason: expect.stringContaining(
        "cmr worker <cmr> tag matched no valid shape",
      ),
    });
  });

  it("rejects not-converged CMR verdicts that omit evidence paths", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: false,
      reason: "blocking findings remain",
      successfulLegs: ["gpt-5.5"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      findings: [
        {
          severity: "medium",
          category: "correctness",
          claim_quote: "missing evidence paths should not be accepted",
          location: "orchestrator/src/family/realFamilyBackend.ts",
          suggested_fix: "include review artifact evidence paths",
          action: "fix_now",
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      kind: "malformed",
      reason: expect.stringContaining(
        "cmr worker <cmr> tag matched no valid shape",
      ),
    });
  });

  it("strips legacy disposition aliases even when status is already present", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.5"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: ["correctness|src/x.ts:1|accepted"],
      evidencePaths: ["cmr/review.json"],
      priorFindingDispositions: [
        {
          identityKey: "correctness|src/x.ts:1|accepted",
          status: "verified-closed",
          disposition: "accepted_suppressed",
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      converged: true,
      priorFindingDispositions: [
        {
          identityKey: "correctness|src/x.ts:1|accepted",
          status: "verified-closed",
        },
      ],
    });
  });
});

describe("mergerOutcomeFromResult (#291 completion-signal gate, pure)", () => {
  it("prefers a runner-owned outcome sidecar over malformed merger stdout", () => {
    const dir = mkdtempSync(join(tmpdir(), "merger-outcome-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ resolved: true, tradeoffs: "preserved both sides" }) + "\n",
      "utf8",
    );

    expect(
      mergerOutcomeFromResult({
        completionSignal: "MERGER_STEP_COMPLETE",
        stdout: "<merger>not json</merger>\nMERGER_STEP_COMPLETE",
        outcomePath,
      }),
    ).toEqual({ resolved: true });
  });

  it("parses merger sidecar payloads directly when free-form text contains a merger tag delimiter", () => {
    const dir = mkdtempSync(join(tmpdir(), "merger-outcome-delimiter-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        resolved: true,
        tradeoffs: "resolution notes quoted the literal </merger> delimiter",
      }) + "\n",
      "utf8",
    );

    expect(
      mergerOutcomeFromResult({
        completionSignal: "MERGER_STEP_COMPLETE",
        stdout: "<merger>not json</merger>\nMERGER_STEP_COMPLETE",
        outcomePath,
      }),
    ).toEqual({ resolved: true });
  });

  it("fails closed instead of falling back to stdout when the merger outcome sidecar is malformed", () => {
    const dir = mkdtempSync(join(tmpdir(), "merger-outcome-bad-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const outcome = mergerOutcomeFromResult({
      completionSignal: "MERGER_STEP_COMPLETE",
      stdout: '<merger>{"resolved": true}</merger>',
      outcomePath,
    });

    expect(outcome.resolved).toBe(false);
    expect(outcome.reason).toContain("sidecar");
  });

  it("a signaled run delegates to parseMergerOutcome (resolved)", () => {
    expect(
      mergerOutcomeFromResult({
        completionSignal: "MERGER_STEP_COMPLETE",
        stdout: '<merger>{"resolved": true}</merger>',
      }),
    ).toEqual({ resolved: true });
  });
  it("an UNSIGNALED run is unresolved even when stdout claims resolved (codex R1)", () => {
    // maxIterations hit mid-resolution: no completion signal, but an earlier
    // `<merger>{"resolved":true}</merger>` rode in. The gate must NOT accept it.
    const out = mergerOutcomeFromResult({
      completionSignal: undefined,
      stdout: '<merger>{"resolved": true}</merger>',
    });
    expect(out.resolved).toBe(false);
    expect(out.reason).toMatch(/did not fire its completion signal/);
  });
  it("a wrong completion signal is unresolved", () => {
    expect(
      mergerOutcomeFromResult({
        completionSignal: "SOME_OTHER_SIGNAL",
        stdout: '<merger>{"resolved": true}</merger>',
      }).resolved,
    ).toBe(false);
  });
});

describe("RealFamilyBackend merger outcome sidecar cleanup", () => {
  it("removes the temporary outcome sidecar directory after parsing the merger result", async () => {
    const repo = trackRepo();
    const ledgerDir = mkdtempSync(join(tmpdir(), "merger-cleanup-ledger-"));
    ledgerDirs.push(ledgerDir);
    let outcomePathAtRun: string | undefined;
    class CleanupBackend extends RealFamilyBackend {
      public run(req: ConflictResolveRequest) {
        return this.runMergerAgent(req);
      }
      protected override mountMergerAuth(): MergerAuth {
        return { claudeToken: "tok" };
      }
      protected override prepareMergerOutcomeLanding(): { path: string; sandboxPath: string } {
        const landing = super.prepareMergerOutcomeLanding();
        outcomePathAtRun = landing.path;
        return landing;
      }
      protected override async runAgentSandbox(
        _options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomePathAtRun === undefined) throw new Error("missing outcome sidecar path");
        writeFileSync(outcomePathAtRun, JSON.stringify({ resolved: true }), "utf8");
        return {
          completionSignal: "MERGER_STEP_COMPLETE",
          stdout: "<merger>{}</merger>",
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new CleanupBackend(opts(repo, { ledgerDir }));
    const out = await b.run({ childIssue: 496, childBranch: "feat/child" });

    expect(out.resolved).toBe(true);
    expect(outcomePathAtRun).toBeDefined();
    expect(existsSync(dirname(outcomePathAtRun as string))).toBe(false);
  });
});

// ═══════════════════════════ 5. runFamilyVerify ═════════════════════════════

describe("RealFamilyBackend runFamilyVerify (#291 tsc + vitest)", () => {
  it("GREEN → {ok:true}; runs verify scoped to the phase against the family base", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.verifyOutcome = "green";
    const res = await b.runFamilyVerify({ phase: "wave", familyBase: "family/293-base" });
    expect(res).toEqual({ ok: true });
    expect(b.verifyCalls).toEqual([{ phase: "wave", familyBase: "family/293-base" }]);
  });
  it("RED → {ok:false, errorPackage:{reason}} carrying the failing summary", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.verifyOutcome = "red";
    const res = await b.runFamilyVerify({ phase: "final", familyBase: "family/293-base" });
    expect(res.ok).toBe(false);
    expect(res.errorPackage?.reason).toMatch(/final/);
    expect(res.errorPackage?.reason).toMatch(/vitest|failed/);
  });

  it("RED via an execFileSync-style error captures err.stderr (the real failure reason), not just err.message", async () => {
    // execFileSync on a non-zero exit throws an Error whose `.message` is only the
    // status line ("Command failed: npx tsc --noEmit"); the ACTUAL tsc/test output
    // is on `.stderr` (string or Buffer). Reading only `.message` would drop the
    // locatable reason from the ledger (agy R1). summarizeError must append it.
    class StderrRed extends FakeSeamsBackend {
      protected override runVerifyCommands(): void {
        const e = new Error("Command failed: npx tsc --noEmit") as Error & {
          stderr?: Buffer;
        };
        e.stderr = Buffer.from("src/region.ts(42,7): error TS2322: Type 'number' is not assignable");
        throw e;
      }
    }
    const b = new StderrRed(opts(trackRepo()));
    const res = await b.runFamilyVerify({ phase: "wave", familyBase: "family/293-base" });
    expect(res.ok).toBe(false);
    // the actual compiler error (from .stderr) is in the ledger reason, not lost.
    expect(res.errorPackage?.reason).toMatch(/TS2322/);
  });

  it("captures BOTH stderr AND stdout — the failure body on stdout is not dropped when stderr has noise (codex R3)", async () => {
    // Some tools put warnings on stderr and the real failure body on stdout (vitest
    // prints the failing assertions to stdout). Taking stderr-OR-stdout would drop
    // the stdout reason; summarizeError must append both.
    class BothStreamsRed extends FakeSeamsBackend {
      protected override runVerifyCommands(): void {
        const e = new Error("Command failed: npx vitest run") as Error & {
          stderr?: string;
          stdout?: string;
        };
        e.stderr = "warning: deprecated flag"; // noise
        e.stdout = "FAIL test/x.test.ts > the real assertion that failed"; // the body
        throw e;
      }
    }
    const b = new BothStreamsRed(opts(trackRepo()));
    const res = await b.runFamilyVerify({ phase: "final", familyBase: "family/293-base" });
    expect(res.ok).toBe(false);
    // BOTH the stderr noise and the stdout failure body are present.
    expect(res.errorPackage?.reason).toMatch(/the real assertion that failed/);
    expect(res.errorPackage?.reason).toMatch(/deprecated flag/);
  });
});

// ═══════════════════════════ 6. runIntegratedCmr ════════════════════════════

describe("RealFamilyBackend runIntegratedCmr (#291 ak-cross-m-review seam)", () => {
  it("delegates to the cmr seam and forwards the verdict", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.cmrResult = { converged: false, reason: "field-name mismatch across slices" };
    const res = await b.runIntegratedCmr({ familyBase: "family/293-base", llmResolvedChildren: [10] });
    expect(b.cmrCalls).toEqual([{ familyBase: "family/293-base", llmResolvedChildren: [10] }]);
    expect(res).toEqual({ converged: false, reason: "field-name mismatch across slices" });
  });
});

// ═══════════════════════════ 7. openFamilyPr ════════════════════════════════

describe("RealFamilyBackend openFamilyPr (#291 push + gh pr create, 止于 PR)", () => {
  it("pushes the family base, opens a PR against the configured base, returns the url", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo(), { base: "integ/291-wave3" }));
    b.prViewResponse = {
      baseRefName: "integ/291-wave3",
      headRefName: "family/293-base",
      headRefOid: "pr-head-777",
      state: "OPEN",
    };
    const res = await b.openFamilyPr({ familyBase: "family/293-base" });
    expect(res.url).toContain("/pull/777");
    expect(res.prHead).toBe("pr-head-777");
    // The SOLE remote push is here.
    const push = b.shCalls.find((c) => c.file === "git" && c.args[0] === "push");
    expect(push?.args).toEqual(["push", "-u", "origin", "family/293-base"]);
    // gh pr create targets the configured base (integration branch), head = family base.
    const pr = b.shCalls.find((c) => c.file === "gh" && c.args[1] === "create");
    expect(pr?.args).toContain("--base");
    expect(pr?.args).toContain("integ/291-wave3");
    expect(pr?.args).toContain("--head");
    expect(pr?.args).toContain("family/293-base");
  });

  it("verifies PR metadata with base/head/state/head OID and returns the trimmed head OID", () => {
    const b = new FakeSeamsBackend(opts(trackRepo(), { base: "integ/291-wave3" }));
    b.prViewResponse = {
      baseRefName: "integ/291-wave3",
      headRefName: "family/293-base",
      headRefOid: " pr-head-777 ",
      state: "OPEN",
    };

    expect(b.verifyShipPr("https://github.com/Akagilnc/ming-salvage-sim/pull/777", "family/293-base")).toEqual({
      ok: true,
      headOid: "pr-head-777",
    });
    const view = b.shCalls.find((c) => c.file === "gh" && c.args[0] === "pr" && c.args[1] === "view");
    expect(view?.args).toContain("baseRefName,headRefName,headRefOid,state");
  });

  it("rejects PR metadata when the PR is not OPEN or lacks a non-empty head OID", () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));

    b.prViewResponse = {
      baseRefName: "main",
      headRefName: "family/293-base",
      headRefOid: "pr-head-1",
      state: "MERGED",
    };
    expect(b.verifyShipPr("pr://closed", "family/293-base")).toMatchObject({
      ok: false,
    });

    b.prViewResponse = {
      baseRefName: "main",
      headRefName: "family/293-base",
      headRefOid: "   ",
      state: "OPEN",
    };
    expect(b.verifyShipPr("pr://blank-head", "family/293-base")).toMatchObject({
      ok: false,
    });
  });

  it("resume PR verification requires the PR head OID to still match the current family HEAD", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.prViewResponse = {
      baseRefName: "main",
      headRefName: "family/293-base",
      headRefOid: "pr-head-1",
      state: "OPEN",
    };

    await expect(
      b.verifyFamilyShippedPr({
        pr: "pr://current",
        familyBase: "family/293-base",
        expectedHead: "pr-head-1",
      }),
    ).resolves.toEqual({ ok: true });
    await expect(
      b.verifyFamilyShippedPr({
        pr: "pr://stale",
        familyBase: "family/293-base",
        expectedHead: "new-head",
      }),
    ).resolves.toMatchObject({ ok: false });
  });
});

// ═══════════════════════════ 8. recordAborted / escalate ════════════════════

describe("RealFamilyBackend recordAborted (#291 in-memory seam, NOT the durable writer)", () => {
  it("does NOT append to the durable ledger — the durable abort is recordDurableAbort's job (no double-write)", async () => {
    // verifyCmr.ts records a red verify by calling BOTH `recordAborted?` AND
    // `recordDurableAbort` (ledger.ts). Only the latter appends the PHASE-LEVEL
    // durable entry; wiring-aborted-durable-291 fixes the contract at exactly ONE
    // durable aborted entry per red verify. If RealFamilyBackend.recordAborted ALSO
    // appended (the pre-fix behaviour), the real spine wrote TWO duplicate aborted
    // entries (codex R1). So this seam must be a durable no-op.
    const b = new RealFamilyBackend(opts(trackRepo()));
    await b.recordAborted({
      phase: "wave",
      familyBase: "family/293-base",
      errorPackage: { reason: "tsc: TS2322 in regionApply" },
      familyHeadAfter: "headAfter",
    });
    // The seam wrote NOTHING durable on its own — no double-write against the spine.
    expect(await b.readFamilyLedger()).toEqual([]);
  });
});

describe("RealFamilyBackend escalateFamily (#291 durable stuck-point)", () => {
  it("persists a durable family-ledger decision escalation readable back", async () => {
    const b = new RealFamilyBackend(opts(trackRepo()));
    await b.escalateFamily({ reason: "integrated cmr did not converge: field mismatch" });
    expect(await b.readFamilyLedger()).toMatchObject([
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        reason: "integrated cmr did not converge: field mismatch",
        escalationKind: "decision",
        stopSummary: {
          reason: "infra_failure",
          repairHint: "inspect this escalation row and repair before rerun",
        },
      },
    ]);
    const recs = await b.readEscalations();
    expect(recs).toHaveLength(1);
    expect(recs[0]?.reason).toContain("cmr did not converge");
    expect(recs[0]?.escalationKind).toBe("decision");
  });

  it("keeps legacy family-escalations.jsonl stuck-points readable during migration", async () => {
    const o = opts(trackRepo());
    mkdirSync(o.ledgerDir, { recursive: true });
    writeFileSync(
      join(o.ledgerDir, "family-escalations.jsonl"),
      `${JSON.stringify({
        reason: "legacy cmr pause",
        ts: "2026-06-01T00:00:00.000Z",
      })}\n`,
      "utf8",
    );
    const b = new RealFamilyBackend(o);

    const recs = await b.readEscalations();

    expect(recs).toEqual([
      {
        reason: "legacy cmr pause",
        ts: "2026-06-01T00:00:00.000Z",
      },
    ]);
  });

  it("orders legacy escalations before newer ledger answers so migration can reopen", async () => {
    const o = opts(trackRepo());
    mkdirSync(o.ledgerDir, { recursive: true });
    writeFileSync(
      join(o.ledgerDir, "family-escalations.jsonl"),
      `${JSON.stringify({
        reason: "legacy cmr pause",
        ts: "2026-06-01T00:00:00.000Z",
      })}\n`,
      "utf8",
    );
    const b = new RealFamilyBackend(o);
    await b.appendFamilyLedger({
      status: "escalation_answered",
      event: "escalation_answered",
      phase: "final",
      answer: "continue-after-legacy-pause",
      source: "human",
    });

    expect(familyEscalationState(await b.readFamilyLedger())).toMatchObject({
      escalation: { reason: "legacy cmr pause" },
      answer: {
        event: "escalation_answered",
        answer: "continue-after-legacy-pause",
        source: "human",
      },
    });
  });

  it("orders legacy escalation records before newer ledger escalation records", async () => {
    const o = opts(trackRepo());
    mkdirSync(o.ledgerDir, { recursive: true });
    writeFileSync(
      join(o.ledgerDir, "family-escalations.jsonl"),
      `${JSON.stringify({
        reason: "legacy cmr pause",
        ts: "2026-06-01T00:00:00.000Z",
      })}\n`,
      "utf8",
    );
    const b = new RealFamilyBackend(o);
    await b.escalateFamily({ reason: "new ledger cmr pause" });

    expect(await b.readEscalations()).toEqual([
      {
        reason: "legacy cmr pause",
        ts: "2026-06-01T00:00:00.000Z",
      },
      {
        reason: "new ledger cmr pause",
        escalationKind: "decision",
      },
    ]);
  });
});

describe("RealFamilyBackend runtime file git excludes", () => {
  it("treats CRLF exclude entries as existing lines instead of appending duplicates", () => {
    class Probe extends RealFamilyBackend {
      public exclude(filename: string): void {
        this.excludeOptionalRuntimeFileFromGit(filename);
      }
    }
    const repo = trackRepo();
    const excludePath = join(repo, ".git", "info", "exclude");
    writeFileSync(excludePath, ".orchestrator-outcome.json\r\n", "utf8");
    const b = new Probe(opts(repo));

    b.exclude(".orchestrator-outcome.json");

    expect(readFileSync(excludePath, "utf8")).toBe(".orchestrator-outcome.json\r\n");
  });

  it("treats CRLF exclude entries as existing lines in the CMR exclude helper too", () => {
    class Probe extends RealFamilyBackend {
      public excludeCmr(filename: string): void {
        this.excludeFromGit(filename);
      }
    }
    const repo = trackRepo();
    const excludePath = join(repo, ".git", "info", "exclude");
    writeFileSync(excludePath, ".cmr-route.json\r\n", "utf8");
    const b = new Probe(opts(repo));

    b.excludeCmr(".cmr-route.json");

    expect(readFileSync(excludePath, "utf8")).toBe(".cmr-route.json\r\n");
  });
});
