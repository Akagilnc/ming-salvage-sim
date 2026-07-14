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
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as sc from "@ai-hero/sandcastle";
import {
  MERGER_SOUL,
  cmrOutcomeFromResult,
  mergerOutcomeFromResult,
  type MergerAuth,
  parseCmrOutcome,
  parseMergerOutcome,
  REFERENCED_FAMILY_PROMPT_FILES,
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../../src/family/realFamilyBackend.js";
import { FIX_FOCUS_LANDING_FILE } from "../../../src/findingFamilies.js";
import { familyEscalationState } from "../../../src/family/ledger.js";
import { MAX_DISPATCH_ATTEMPTS } from "../../../src/dispatchRetry.js";
import {
  SANDBOX_SKILLS_DIR,
  SANDBOX_SOUL_ENV,
  soulsMount,
} from "../../../src/realBackend.js";
import type {
  ConflictResolveRequest,
  FamilyVerifyRequest,
  IntegratedCmrRequest,
  IntegratedCmrResult,
} from "../../../src/family/types.js";
import { DEFAULT_IMAGE_TAG, resolveImageTag } from "../../../src/familyDriver.js";
import { PROVISION_SUBPROCESS_TIMEOUT_MS } from "../../../src/provisionNodeModules.js";
import type { WorkerSpec } from "../../../src/types.js";
import * as telemetry from "../../../src/telemetry.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

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
function trackTempDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  ledgerDirs.push(dir);
  return dir;
}
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

describe("RealFamilyBackend live officer effort", () => {
  class Probe extends RealFamilyBackend {
    public agentForLiveSpec(spec: WorkerSpec, billingPool?: string): sc.AgentProvider {
      return this.agentForSpec(spec, { billingPool });
    }
  }

  const liveSpec = (overrides: Partial<WorkerSpec>): WorkerSpec => ({
    id: "S3",
    kind: "cmr",
    role: "reviewer",
    host: "claude",
    session: "fresh",
    contextRetention: "clean",
    promptFile: "integrated_cmr_completeness.md",
    completionSignal: "CMR_STEP_COMPLETE",
    maxIter: 1,
    model: "gpt-5.6-sol",
    soul: "cmr",
    toolchain: [],
    ...overrides,
  });

  it("passes xhigh through the family CMR and verify dispatch agent", () => {
    const backend = new Probe(opts(trackRepo()));
    const commandFor = (spec: WorkerSpec) =>
      backend.agentForLiveSpec(spec).buildPrintCommand({ prompt: "test", dangerouslySkipPermissions: false }).command;

    expect(commandFor(liveSpec({ soul: "cmr" }))).toContain(
      'model_reasoning_effort="xhigh"',
    );
    expect(
      commandFor(liveSpec({ id: "S5", kind: "verify", role: "verify", soul: "READ-ONLY" })),
    ).toContain('model_reasoning_effort="xhigh"');
  });

  it("applies the ADR 0124 billing-pool provider binding to family workers", () => {
    const backend = new Probe(opts(trackRepo()));
    const command = backend
      .agentForLiveSpec(liveSpec({ model: "grok-4.5" }), "grok-build")
      .buildPrintCommand({ prompt: "test", dangerouslySkipPermissions: false }).command;
    expect(command).toContain("grok --prompt-file /dev/stdin");
  });
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
    soulsDir: realSoulsDir,
    imageName: "img",
    ...over,
  };
}

describe("RealFamilyBackend telemetry construction", () => {
  it("does not calculate telemetry fingerprints during construction", () => {
    const configure = vi.spyOn(
      telemetry,
      "configureTelemetryFromWorkerImage",
    );

    new RealFamilyBackend(opts(trackRepo()));

    expect(configure).not.toHaveBeenCalled();
  });
});

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

  it("childHeadExists with NO branch falls back to old convention (feat/244-orchestrator-issue-<n>) when current misses (#593)", async () => {
    // A child slice that was cut and merged under the OLD branch-name convention
    // (before PR #365) must still be recognised as already-merged by reconcile —
    // otherwise it would be double-merged (the bug this gate prevents). The old
    // `feat/244-orchestrator-issue-<n>` branch exists, the current
    // `feat/issue-<n>` does NOT, and childHeadExists is called with only the
    // issue number (the `reconcile.ts` production call shape).
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/593-base");
    git(repo, "checkout", "-q", "-b", "feat/244-orchestrator-issue-88", "family/593-base");
    const childHead = commitFile(repo, "c88.txt", "old-convention");
    git(repo, "checkout", "-q", "family/593-base");
    const recon = new RealFamilyBackend(opts(repo)).reconcileGit();
    const r = await recon.childHeadExists(88); // NO branch — falls back to old convention
    expect(r.exists).toBe(true);
    expect(r.childHead).toBe(childHead);
  });

  it("childHeadExists returns exists:false when NEITHER convention matches (#593)", async () => {
    // A genuinely new child slice: neither the current nor the old convention
    // branch exists. Must still return exists:false (the 补账 predicate must NOT
    // break — an absent child is the EXPECTED reconcile case).
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/593-base");
    const recon = new RealFamilyBackend(opts(repo)).reconcileGit();
    const r = await recon.childHeadExists(99);
    expect(r.exists).toBe(false);
    expect(r.childHead).toBeUndefined();
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
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"]; // orchestrator's scripts
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    await new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" })).runVerifyForTest();
    // Unconditional install first (by construction), then project's scripts.
    // (installDeps chooses "ci" or "install" based on whether lockfile exists at the cwd path.)
    expect(calls[0].file).toBe("npm");
    expect(["ci", "install"]).toContain(calls[0].args[0]);
    expect(calls[0].cwd).toBe("/clone/root/orchestrator");
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
    expect(calls.slice(1).every((c) => c.cwd === "/clone/root/orchestrator")).toBe(true);
  });

  it("never appends telemetry reporters or compiler flags to the project's declared verify commands (#786)", async () => {
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }

    await new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" })).runVerifyForTest();
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
  });

  it("#3 + #372 P2: ALWAYS runs installDeps (unconditional, by construction) even when node_modules EXISTS and manifest changed after a wave", async () => {
    // #372 P2: runVerifyCommands must not condition install on depsInstalled presence.
    // Freshness by construction: later waves in family can change package.json / package-lock.json
    // inside the (shared) family clone; verify must still run install (npm ci idempotent) on
    // the (now potentially stale) node_modules. We simulate "node_modules exists + manifest changed"
    // by creating a temp Node project dir with node_modules present, then updating the lock manifest
    // (post-"wave" mutation), and asserting install is STILL invoked before scripts.
    // No mtime/manifest compare is re-introduced (per direction).
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const proj = trackTempDir("verify-uncond-install-");
    const pkg = join(proj, "package.json");
    const lock = join(proj, "package-lock.json");
    const nm = join(proj, "node_modules");
    writeFileSync(pkg, JSON.stringify({ name: "test-proj", version: "0.0.0" }));
    writeFileSync(lock, JSON.stringify({ name: "test-proj", version: "0.0.0", lockfileVersion: 3 }));
    mkdirSync(nm, { recursive: true });
    // Simulate a later wave mutating the manifest (new lock content after node_modules was laid).
    writeFileSync(lock, JSON.stringify({ name: "test-proj", version: "0.0.1", lockfileVersion: 3, "updated-by-wave": true }));

    class SpyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        return "";
      }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    // Note: pass verifyCwd=proj so run reaches install+scripts (isNode true by override).
    // We do NOT override depsInstalled (it no longer exists).
    await new SpyBackend(opts("/clone/root", { verifyCwd: proj })).runVerifyForTest();
    // Install MUST run (first) even though node_modules existed + manifest mutated post-wave.
    expect(calls[0].file).toBe("npm");
    expect(["ci", "install"]).toContain(calls[0].args[0]);
    expect(calls[0].cwd).toBe(proj);
    // Then the project's verify scripts, still in cwd.
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
    expect(calls.slice(1).every((c) => c.cwd === proj)).toBe(true);
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
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["dev", "build", "test", "preview"]; // web's scripts — NO `typecheck`
      }
      protected override isNodeProject(_cwd: string): boolean {
        return true;
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    await new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/web" })).runVerifyForTest();
    // Unconditional install first (even if node_modules "existed"), then web's scripts.
    expect(calls[0].file).toBe("npm");
    expect(["ci", "install"]).toContain(calls[0].args[0]);
    expect(calls[0].cwd).toBe("/clone/root/web");
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual([
      "npm run build",
      "npm test",
    ]);
    expect(calls.some((c) => c.file === "npx")).toBe(false);
    expect(calls.slice(1).every((c) => c.cwd === "/clone/root/web")).toBe(true);
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

  it("R3: a SINGLE-project repo (package.json at the clone ROOT) falls back to workingRepo verify", async () => {
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
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["test"];
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    // No verifyCwd; resolver undefined (no subproject) → root is Node → verify at root.
    await new SpyBackend(opts("/clone/root", { resolveVerifyCwd: () => undefined })).runVerifyForTest();
    // Unconditional: install first, then test.
    expect(calls[0].file).toBe("npm");
    expect(["ci", "install"]).toContain(calls[0].args[0]);
    expect(calls[0].cwd).toBe("/clone/root");
    expect(calls.slice(1).map((c) => `${c.file} ${c.args.join(" ")}`)).toEqual(["npm test"]);
    expect(calls.slice(1).every((c) => c.cwd === "/clone/root")).toBe(true);
  });

  it("R1-T3: an EXPLICIT verifyCwd that is NOT a Node project FAILS CLOSED (throws), never silent-passes", async () => {
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
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/293-base" });
      }
    }
    await expect(
      new SpyBackend(opts("/clone/root", { verifyCwd: "/clone/root/not-node" })).runVerifyForTest(),
    ).rejects.toThrow(/not a Node project/i);
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

  it("family inventory covers every prompt dispatched by the family workflow", () => {
    expect(new Set(REFERENCED_FAMILY_PROMPT_FILES)).toEqual(
      new Set([
        "integrated_cmr_completeness.md",
        "integrated_cmr_correctness.md",
        "coder_fix.md",
        "family_ship.md",
        "merger_resolve_conflict.md",
        "verify.md",
        "fixer.md",
        "docRelease.md",
      ]),
    );
  });

  it("constructs cleanly when all family prompts are present (the real prompts dir)", () => {
    const repo = trackRepo();
    expect(() => new RealFamilyBackend(opts(repo))).not.toThrow();
  });
});

describe("family CMR prompt output contract", () => {
  it("pins priorFindingDispositions to the parser's status field, not prose-only disposition", () => {
    for (const file of [
      "integrated_cmr_completeness.md",
      "integrated_cmr_correctness.md",
    ]) {
      const prompt = readFileSync(join(realPromptsDir, file), "utf8");
      expect(prompt).toContain('"status":"verified-closed"');
      expect(prompt).toContain("Do not use a field named `disposition`");
      expect(prompt).toContain(
        "Any `priorFindingDispositions` entries in this not-converged shape must use the",
      );
      expect(prompt).toContain(
        'same `{"identityKey":"<key>","status":"...","reason":"<short>"}` contract',
      );
    }
  });
});

// ═══════════════════ 4. resolveMergeConflict (sc.run seam) ═══════════════════

/** A subclass that fakes the external seams (merger agent / verify / cmr / sh). */
class FakeSeamsBackend extends RealFamilyBackend {
  mergerOutcome: ReturnType<typeof mergerOutcomeFromResult> = { resolved: true };
  mergerCalls: ConflictResolveRequest[] = [];
  verifyOutcome: "green" | "red" = "green";
  verifyCalls: FamilyVerifyRequest[] = [];
  cmrResult: IntegratedCmrResult = { converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] };
  cmrCalls: IntegratedCmrRequest[] = [];
  shCalls: Array<{ file: string; args: string[] }> = [];
  prViewResponse: unknown = {
    number: 777,
    url: "https://github.com/Akagilnc/ming-salvage-sim/pull/777",
    baseRefName: "main",
    headRefName: "family/293-base",
    headRefOid: " pr-head-1 ",
    headRepositoryOwner: { login: "Akagilnc" },
    state: "OPEN",
    mergeStateStatus: "CLEAN",
  };
  prListResponse: unknown = [];
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
  protected override async runVerifyCommands(req: FamilyVerifyRequest): Promise<void> {
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
  protected override isMergeCommit(_commit: string, _repo: string): boolean {
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
      return JSON.stringify({
        number: 777,
        url: "https://github.com/Akagilnc/ming-salvage-sim/pull/777",
        mergeStateStatus: "CLEAN",
        ...(this.prViewResponse as Record<string, unknown>),
      });
    }
    if (file === "gh" && args[0] === "pr" && args[1] === "list") {
      return JSON.stringify(this.prListResponse);
    }
    return "";
  }

  // the configured family base (RealFamilyBackend.opts is protected → accessible).
  private get familyBase(): string {
    return this.opts.familyBase;
  }

  // Expose the protected sandbox-config seam so the merger soul injection +
  // skills-mount path are unit-testable without a real container.
  public sandboxConfig(auth: any = {}) {
    return this.mergerSandboxConfig(auth);
  }

  // Expose for family-coder souls mount assertion (#372).
  public familyCoderConfig() {
    return this.familyCoderSandboxConfig(
      { codexAuthDir: "/tmp/codex", claudeToken: "tok" } as any,
      "sonnet",
      {} as any,
      { path: "/tmp/land.json", sandboxPath: ".land.json" },
    );
  }

}

describe("RealFamilyBackend resolveMergeConflict (#291 sc.run merger seam)", () => {
  it("checks conflict markers only in files introduced or modified by the merge", () => {
    class MarkerScopeBackend extends RealFamilyBackend {
      hasMarkers(before: string, after: string): boolean {
        return this.hasConflictMarkers(before, after, this.opts.workingRepo);
      }
    }

    const repo = trackRepo();
    const marker = "<<<<<<< archived fixture\n=======\n>>>>>>> archived fixture\n";
    mkdirSync(join(repo, "docs"));
    mkdirSync(join(repo, "src"));
    commitFile(repo, "docs/fixture.md", marker);
    const before = git(repo, "rev-parse", "HEAD");
    commitFile(repo, "src/touched.ts", "export const touched = true;\n");
    const after = git(repo, "rev-parse", "HEAD");

    expect(new MarkerScopeBackend(opts(repo)).hasMarkers(before, after)).toBe(false);
  });

  it("rejects a two-parent merge commit that still contains conflict markers", async () => {
    class MarkerLeavingMergerBackend extends RealFamilyBackend {
      protected override async runMergerAgent(req: ConflictResolveRequest) {
        writeFileSync(
          join(this.opts.workingRepo, "shared.txt"),
          "<<<<<<< HEAD\nFAMILY VERSION\n=======\nCHILD VERSION\n>>>>>>> child\n",
          "utf8",
        );
        git(this.opts.workingRepo, "add", "shared.txt");
        execFileSync("git", ["commit", "-q", "-m", `bad resolution ${req.childIssue}`], {
          cwd: this.opts.workingRepo,
        });
        return { resolved: true };
      }
    }

    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    commitFile(repo, "shared.txt", "FAMILY VERSION");
    const baseBefore = git(repo, "rev-parse", "HEAD");
    git(repo, "checkout", "-q", "-b", "feat/child-24", "HEAD~1");
    const childHead = commitFile(repo, "shared.txt", "CHILD VERSION");
    git(repo, "checkout", "-q", "family/293-base");

    const backend = new MarkerLeavingMergerBackend(opts(repo));
    const deterministic = await backend.mergeChildIntoFamilyBase({
      childIssue: 24,
      childBranch: "feat/child-24",
    });
    expect(deterministic.conflicted).toBe(true);

    const result = await backend.resolveMergeConflict({
      childIssue: 24,
      childBranch: "feat/child-24",
    });

    expect(result).toMatchObject({
      familyHeadBefore: baseBefore,
      childHead,
      conflicted: true,
    });
    expect(() => git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")).toThrow();
  });

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

  it("agent escalated/failed → leaves the merge unresolved (the merger never records `merged`)", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: false, reason: "needs a product decision on field X" };
    await expect(
      b.resolveMergeConflict({ childIssue: 11, childBranch: "feat/child-11" }),
    ).resolves.toMatchObject({ conflicted: true });
  });

  it("a sparse merger decision bell parks instead of becoming a conflicted retry", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = mergerOutcomeFromResult({
      stdout: '<merger>{"resolved":false,"escalate":{}}</merger>',
    });

    await expect(
      b.resolveMergeConflict({ childIssue: 111, childBranch: "feat/child-111" }),
    ).resolves.toMatchObject({
      escalation: {
        reason: "",
        diagnosis: "",
        escalationKind: "decision",
        phase: "wave",
      },
    });
    expect(b.mergerCalls).toHaveLength(1);
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

  // ── #598: generic mechanical retry at the merge-resolver call site ──────────────

  it("#598 a merger agent that CRASHES (throws) once then resolves is retried fresh on current state", async () => {
    class CrashOnceBackend extends FakeSeamsBackend {
      crashesLeft = 1;
      protected override async runMergerAgent(req: ConflictResolveRequest): Promise<{ resolved: boolean; reason?: string }> {
        if (this.crashesLeft > 0) {
          this.crashesLeft -= 1;
          this.mergerCalls.push(req);
          throw new Error("merger container connection dropped mid-resolve");
        }
        return super.runMergerAgent(req);
      }
    }
    const b = new CrashOnceBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: true };
    b.mergeInProgressFake = false;
    const res = await b.resolveMergeConflict({ childIssue: 20, childBranch: "feat/child-20" });
    // The crash was retried fresh → a clean landed resolve (not conflicted).
    expect(res.conflicted ?? false).toBe(false);
    expect(b.mergerCalls).toHaveLength(2);
  });

  it("#598 a merger agent that RETURNS {resolved:false} is not a git resolve (one call)", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: false, reason: "needs a product decision on field X" };
    await expect(
      b.resolveMergeConflict({ childIssue: 21, childBranch: "feat/child-21" }),
    ).resolves.toMatchObject({ conflicted: true });
    // A judged non-resolve is surfaced, never retried.
    expect(b.mergerCalls).toHaveLength(1);
  });

  it("#598 a persistently CRASHING merger agent re-throws after the bounded attempts", async () => {
    class AlwaysCrashBackend extends FakeSeamsBackend {
      protected override async runMergerAgent(req: ConflictResolveRequest): Promise<{ resolved: boolean; reason?: string }> {
        this.mergerCalls.push(req);
        throw new Error("merger keeps crashing");
      }
    }
    const b = new AlwaysCrashBackend(opts(trackRepo()));
    const err = await b
      .resolveMergeConflict({ childIssue: 22, childBranch: "feat/child-22" })
      .then(() => undefined)
      .catch((e: unknown) => e as Error);
    expect(err?.message).toMatch(/keeps crashing/);
    // #598 crit 6 (r4 codexB): the exhausted merger crash names the attempt count.
    expect(err?.message).toMatch(
      new RegExp(`after ${MAX_DISPATCH_ATTEMPTS} dispatch attempts`),
    );
    expect(b.mergerCalls).toHaveLength(MAX_DISPATCH_ATTEMPTS);
  });

  it("#598 idempotency: a merger that COMMITTED the merge then crashed is NOT re-run — the landed child is recognized", async () => {
    // The dangerous idempotency gap (cmr codexB): the agent resolves + COMMITS the
    // merge (advances the family base ref), then the sc.run crashes before returning.
    // A naive retry would `git merge --abort` (no-op after a commit) + re-merge
    // ("already up to date", no conflict) and run the merger agent on a NO-CONFLICT
    // state — failing a child that was already correctly merged. The retry must
    // instead recognize the child already landed (git truth) and NOT re-run the merger.
    class CommitThenCrashBackend extends FakeSeamsBackend {
      crashesLeft = 1;
      protected override async runMergerAgent(req: ConflictResolveRequest) {
        this.mergerCalls.push(req);
        // The agent committed the merge (the family base ref advances) …
        this.familyBaseHeadFake = this.resolvedHeadFake;
        this.mergeInProgressFake = false;
        // … then the sc.run crashed before returning.
        if (this.crashesLeft > 0) {
          this.crashesLeft -= 1;
          throw new Error("sc.run crashed after the merge commit landed");
        }
        return this.mergerOutcome;
      }
    }
    const b = new CommitThenCrashBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: true };
    b.childLandedFake = true; // the committed child is an ancestor of the advanced base
    const res = await b.resolveMergeConflict({ childIssue: 23, childBranch: "feat/child-23" });
    // The already-landed merge is returned as a clean (non-conflicted) resolve …
    expect(res.conflicted ?? false).toBe(false);
    expect(res.familyHead).toBe("resolved-head");
    // … WITHOUT re-running the merger agent on the no-conflict state.
    expect(b.mergerCalls).toHaveLength(1);
  });
});

describe("RealFamilyBackend mergerSandbox soul injection (#291 F28 / ADR 0022)", () => {
  it("#905: merger sandbox has no opencode auth mount", () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    expect(
      b.sandboxConfig({}).mounts.some((m: { sandboxPath: string }) =>
        m.sandboxPath.includes("opencode"),
      ),
    ).toBe(false);
  });
  // F28: the merger conflict fallback follows the "one mirror new soul" model —
  // the merger soul must be selected the SAME way coder/reviewer are: activated
  // via the ORCHESTRATOR_SOUL env (RealBackend.box), NOT a prompt-only role.
  // Before the fix mergerSandbox() injected NO env, so ORCHESTRATOR_SOUL was
  // never set → the merger ran under whatever default soul the image entrypoint
  // picked, not the merger soul. (Souls themselves are live-mounted per #372.)
  it("injects ORCHESTRATOR_SOUL=merger via the same env mechanism as coder/reviewer", () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    const cfg = b.sandboxConfig();
    expect(cfg.env?.[SANDBOX_SOUL_ENV]).toBe(MERGER_SOUL);
    expect(MERGER_SOUL).toBe("merger");
  });

  it("mergerSandboxConfig includes soulsMount() shape (hostPath/sandboxPath/readonly:true) (#372)", () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    const cfg = b.sandboxConfig();
    const expected = soulsMount(realSoulsDir);
    expect(cfg.mounts).toContainEqual(expected);
  });

  it("familyCoderSandboxConfig includes soulsMount() shape (hostPath/sandboxPath/readonly:true) (#372)", () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    const cfg = b.familyCoderConfig();
    const expected = soulsMount(realSoulsDir);
    expect(cfg.mounts).toContainEqual(expected);
  });

  it("uses the profile image and does NOT mount host skills (baked skills win, #334)", () => {
    // #334 (ADR 0026 / cross-slice note): the runtime host skills bind-mount onto
    // SANDBOX_SKILLS_DIR is DROPPED — the 2b image BAKES `resolving-merge-conflicts`
    // (+ its closure), so a runtime mount there would SHADOW the baked skill,
    // pulling the merger back to host state (the reproducibility regression). The
    // merger soul finds the skill in the IMAGE, not a host mount.
    const o = opts(trackRepo(), { imageName: "profile-img" });
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

// #596 F2: family-side decode seam test (raw through parse*Outcome, using isValid* guards)
describe("#596 F2: family-side real decode (parseVerifyOutcome etc) for review-loop kinds (raw, not fake)", () => {
  it.each([
    ["verify", "parseVerifyOutcome"],
    ["fixer", "parseFixerOutcome"],
    ["cleanup", "parseCleanupOutcome"],
    ["docRelease", "parseDocReleaseOutcome"],
  ] as const)("%s receipt rings its decision bell before unrelated cargo is decoded", async (tag, parser) => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod[parser](
      `<${tag}>${JSON.stringify({
        unrelatedCargo: { wrong: [1, 2, 3] },
        escalate: { reason: "owner choice", diagnosis: "family contract fork" },
      })}</${tag}>`,
    );
    expect(out).toMatchObject({
      kind: "escalate",
      escalation: { reason: "owner choice", diagnosis: "family contract fork" },
    });
  });

  // import here via the file's re-export or direct (the test file imports some parses)
  // we will require the module symbols via the existing pattern; use dynamic to avoid top-edit
  it("feeds RAW valid verify tag through real parseVerifyOutcome (family seam)", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const raw = `<verify>{"converged": true}</verify>`;
    const out = mod.parseVerifyOutcome(raw);
    expect(out).toEqual({ kind: "verify", converged: true });
  });

  it("feeds RAW valid-but-false verify through real parse (AC2: false flag passes shape)", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseVerifyOutcome(`<verify>{"converged": false}</verify>`);
    expect(out).toEqual({ kind: "verify", converged: false });
  });

  it("unreadable verify bytes remain cargo instead of becoming a process failure", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    expect(mod.parseVerifyOutcome("no tag here").kind).toBe("cargo");
    expect(mod.parseVerifyOutcome("<verify>notjson</verify>").kind).toBe("cargo");
    expect(mod.parseVerifyOutcome(`<verify>{"converged": 1}</verify>`).kind).toBe("cargo");
  });

  it("feeds RAW valid fixer through real parseFixerOutcome (family-side kind)", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const sha = "a".repeat(40);
    const out = mod.parseFixerOutcome(
      `<fixer>{"committed": true, "fixCommitSha": "${sha}"}</fixer>`,
    );
    expect(out).toEqual({ kind: "fixer", committed: true, fixCommitSha: sha });
  });

  it("falls back to readable stdout buttons when the sidecar cargo is unreadable", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const dir = trackTempDir("review-loop-outcome-fallback-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");
    const sha = "a".repeat(40);

    expect(mod.parseVerifyOutcome('<verify>{"converged": true}</verify>', outcomePath))
      .toEqual({ kind: "verify", converged: true });
    expect(
      mod.parseFixerOutcome(
        `<fixer>{"committed": true, "fixCommitSha": "${sha}"}</fixer>`,
        outcomePath,
      ),
    ).toEqual({ kind: "fixer", committed: true, fixCommitSha: sha });
    expect(
      mod.parseCleanupOutcome('<cleanup>{"terminal": true, "ok": true}</cleanup>', outcomePath),
    ).toEqual({ kind: "cleanup", terminal: true, ok: true });
    expect(
      mod.parseDocReleaseOutcome('<docRelease>{"released": true}</docRelease>', outcomePath),
    ).toEqual({ kind: "docRelease", released: true });
  });

  it("rings a review-loop stdout decision bell before parseable sidecar cargo", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const dir = trackTempDir("review-loop-outcome-bell-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, JSON.stringify({ unrelatedCargo: true }), "utf8");

    expect(mod.parseVerifyOutcome(
      '<verify>{"bad": 1, "escalate": {"reason": "owner choice", "diagnosis": "review fork"}}</verify>',
      outcomePath,
    )).toMatchObject({
      kind: "escalate",
      escalation: { reason: "owner choice", diagnosis: "review fork" },
    });
  });

  it("keeps fixer completion even when fixCommitSha cargo is absent", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseFixerOutcome(`<fixer>{"committed": true}</fixer>`);
    expect(out).toEqual({ kind: "fixer", committed: true });
  });

  it("RAW extra keys on verify remain cargo", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseVerifyOutcome(`<verify>{"converged": true, "extra": "nope"}</verify>`);
    expect(out.kind).toBe("verify");
  });

  it("RAW extra keys on fixer remain cargo", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseFixerOutcome(`<fixer>{"committed": false, "foo": 1, "bar": {}}</fixer>`);
    expect(out.kind).toBe("fixer");
  });

  it("RAW extra keys on cleanup remain cargo", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseCleanupOutcome(
      `<cleanup>{"terminal": true, "ok": true, "unexpected": true}</cleanup>`,
    );
    expect(out).toEqual({ kind: "cleanup", terminal: true, ok: true });
  });

  it("drops malformed optional cargo without discarding worker buttons", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    expect(
      mod.parseVerifyOutcome(
        `<verify>{"converged": true, "threadReplies": "chatty"}</verify>`,
      ),
    ).toEqual({ kind: "verify", converged: true });
    expect(
      mod.parseCleanupOutcome(
        `<cleanup>{"terminal": true, "ok": true, "issuesClosed": ["chatty"]}</cleanup>`,
      ),
    ).toEqual({ kind: "cleanup", terminal: true, ok: true });
  });

  it("RAW extra keys on docRelease remain cargo", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    const out = mod.parseDocReleaseOutcome(`<docRelease>{"released": true, "x": 9}</docRelease>`);
    expect(out.kind).toBe("docRelease");
  });

  // === pinning the canonical family last-complete-block semantics ===
  it("conversational prefix mentioning the tag before the real block → still decodes the real block", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    // prose mention of <verify> (as in real model chatter) must not poison extraction
    const raw =
      '我会把最终结果放在 <verify> 里。\n' +
      '<verify>{"converged": true}</verify>\n' +
      'done';
    const out = mod.parseVerifyOutcome(raw);
    expect(out).toEqual({ kind: "verify", converged: true });
  });

  it("multiple complete tag blocks → the family parser takes the last one", async () => {
    const fam = await import("../../../src/family/realFamilyBackend.js");
    const raw =
      '<verify>{"converged": false}</verify>\n' +
      'chatter between\n' +
      '<verify>{"converged": true}</verify>';
    const outFam = fam.parseVerifyOutcome(raw);
    expect(outFam).toEqual({ kind: "verify", converged: true });
  });

  it("unclosed trailing tag mention after a complete block → last complete wins (actual observed behavior)", async () => {
    const mod = await import("../../../src/family/realFamilyBackend.js");
    // trailing open-mention with no close must be ignored; we take the prior complete
    const raw =
      '<verify>{"converged": false}</verify>\n' +
      'later mention without close: see <verify> for details';
    const out = mod.parseVerifyOutcome(raw);
    expect(out).toEqual({ kind: "verify", converged: false });
  });
});

describe("parseCmrOutcome accepted suppression contract", () => {
  it("normalizes a missing stdout before reading a valid cmr sidecar", () => {
    const dir = trackTempDir("cmr-outcome-missing-stdout-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        converged: true,
        successfulLegs: ["gpt-5.6-sol"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        evidencePaths: ["cmr/review.json"],
      }) + "\n",
      "utf8",
    );

    const outcome = cmrOutcomeFromResult({
      stdout: undefined,
      outcomePath,
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
    });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("preserves cmr verdict and findings sentinel semantics after trimming CRLF stdout", () => {
    const outcome = cmrOutcomeFromResult({
      stdout:
        "\r\n  <cmr>" + JSON.stringify({
          converged: false,
          reason: "two findings remain",
          successfulLegs: ["gpt-5.6-sol"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          evidencePaths: ["cmr/review.json"],
        }) + "</cmr>\r\nfindings = 2\r\n  ",
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: false,
      reason: "two findings remain",
      findingsCount: 2,
    });
  });

  it("prefers a runner-owned outcome sidecar over malformed cmr stdout", () => {
    const dir = trackTempDir("cmr-outcome-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        converged: true,
        successfulLegs: ["gpt-5.6-sol"],
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
      stdout: "<cmr>not json</cmr>\nfindings = 0\nCMR_STEP_COMPLETE",
      outcomePath,
      cmrReviewLegs: [
        { slug: "opus" },
        { slug: "gpt-5.6-sol" },
        { slug: "agy" },
      ],
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
    });
  });

  it("treats a guarded cmr sidecar as completion even when Sandcastle omits the completion signal", () => {
    const dir = trackTempDir("cmr-outcome-sidecar-complete-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        converged: false,
        reason: "same-module budget summary label mismatch remains",
        successfulLegs: ["opus", "gpt-5.6-sol"],
        skippedLegs: [{ slug: "agy", reason: "no active conversation" }],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        findings: [
          {
            severity: "low",
            category: "correctness",
            claim_quote: '"中央军饷", "太仓亏空", "宗室禄米", "官俸", "工部",',
            location: "ming_sim/db.py:3985",
            suggested_fix: "Use 百官俸禄 as the matched budget item name.",
            // #604 slice 4 (ADR 0062): route kinds were removed; a fix_now finding
            // carries no disposition. (Was `disposition:{kind:"same_module"}`.)
            action: "fix_now",
          },
        ],
        evidencePaths: ["cmr/step6-correctness/review-summary.json"],
      }) + "\n",
      "utf8",
    );

    const outcome = cmrOutcomeFromResult({
      completionSignal: undefined,
      stdout:
        "CMR correctness gate completed through the outcome guard.\n" +
        "findings = 1\n" +
        "Reached max iterations (1).\n",
      outcomePath,
      cmrReviewLegs: [
        { slug: "opus" },
        { slug: "gpt-5.6-sol" },
        { slug: "agy" },
      ],
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: false,
      reason: "same-module budget summary label mismatch remains",
      findings: [expect.objectContaining({ location: "ming_sim/db.py:3985" })],
    });
  });

  it("parses cmr sidecar payloads directly when free-form text contains a cmr tag delimiter", () => {
    const dir = trackTempDir("cmr-outcome-delimiter-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({
        escalate: {
          reason: "review unavailable",
          diagnosis: "diagnosis quoted the literal </cmr> delimiter",
          escalationKind: "decision",
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

  it("falls back to CMR stdout cargo when the sidecar is unreadable", () => {
    const dir = trackTempDir("cmr-outcome-bad-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const outcome = cmrOutcomeFromResult({
      completionSignal: "CMR_STEP_COMPLETE",
      stdout:
        '<cmr>{"converged": true, "successfulLegs": ["gpt-5.6-sol"], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review.json"]}</cmr>',
      outcomePath,
      cmrReviewLegs: [{ slug: "gpt-5.6-sol" }],
    });

    expect(outcome).toMatchObject({ kind: "verdict", converged: true });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("falls back to stdout when the cmr outcome sidecar is blank", () => {
    const dir = trackTempDir("cmr-outcome-blank-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "   \n", "utf8");

    const outcome = cmrOutcomeFromResult({
      completionSignal: "CMR_STEP_COMPLETE",
      stdout:
        '<cmr>{"converged": true, "successfulLegs": ["gpt-5.6-sol"], "skippedLegs": [{"slug": "opus", "reason": "not configured for this test"}, {"slug": "agy", "reason": "not configured for this test"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review.json"]}</cmr>\nfindings = 0\n',
      outcomePath,
      cmrReviewLegs: [
        { slug: "opus" },
        { slug: "gpt-5.6-sol" },
        { slug: "agy" },
      ],
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
    });
  });

  it("falls back to signaled cmr stdout only when no outcome sidecar path exists", () => {
    const outcome = cmrOutcomeFromResult({
      completionSignal: "CMR_STEP_COMPLETE",
      stdout:
        '<cmr>{"converged": true, "successfulLegs": ["gpt-5.6-sol"], "skippedLegs": [{"slug": "opus", "reason": "not configured for this test"}, {"slug": "agy", "reason": "not configured for this test"}], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review.json"]}</cmr>\nfindings = 0\n',
      cmrReviewLegs: [
        { slug: "opus" },
        { slug: "gpt-5.6-sol" },
        { slug: "agy" },
      ],
    });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
    });
  });

  it("keeps completion telemetry out of unreadable-sidecar cargo fallback", () => {
    const dir = trackTempDir("cmr-outcome-bad-unsignaled-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const outcome = cmrOutcomeFromResult({
      completionSignal: undefined,
      stdout:
        '<cmr>{"converged": true, "successfulLegs": ["gpt-5.6-sol"], "claimedFixedFindingIdentityKeys": [], "priorFindingDispositions": [], "evidencePaths": ["cmr/review.json"]}</cmr>',
      outcomePath,
      cmrReviewLegs: [{ slug: "gpt-5.6-sol" }],
    });

    expect(outcome).toMatchObject({ kind: "verdict", converged: true });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("derives redundant accepted_suppressed finding fields from the finding payload", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: false,
      reason: "accepted suppression remains",
      successfulLegs: ["gpt-5.6-sol"],
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
      successfulLegs: ["gpt-5.6-sol"],
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

    expect(outcome.kind).toBe("verdict");
    expect(outcome.kind === "verdict" ? outcome.findings?.[0]?.disposition_reason : undefined).toBe(
      "Owner accepted this bounded risk.",
    );
  });

  it("#875: converged verdict omitting claim/disposition prose fields still parses (no closure shape court)", () => {
    // Pre-#875 / residual court: cmrClosureSchema required
    // claimedFixedFindingIdentityKeys + priorFindingDispositions arrays; omitting
    // them made the whole verdict malformed before three-channel routing.
    // Post-#875: those fields are optional worker prose.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      evidencePaths: ["cmr/review.json"],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.converged).toBe(true);
      expect(outcome.successfulLegs).toEqual(["gpt-5.6-sol"]);
      expect(outcome.claimedFixedFindingIdentityKeys).toBeUndefined();
      expect(outcome.priorFindingDispositions).toBeUndefined();
    }
  });

  it("#875: incomplete accepted_suppressed prior disposition prose still parses as a verdict (not malformed death)", () => {
    // Pre-#875: parse-time superRefine killed incomplete accepted_suppressed
    // prior dispositions as malformed before verifyCmr could three-channel route.
    // Post-#875: prior dispositions are worker prose at parse; finding.disposition
    // governance (cmrDispositionEvidenceSchema) stays strict.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
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
          // deliberately incomplete — missing reason/source/scope/boundedReopen
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.converged).toBe(true);
      expect(outcome.priorFindingDispositions).toEqual([
        {
          identityKey: "correctness|src/x.ts:1|accepted",
          status: "accepted_suppressed",
        },
      ]);
    }
  });

  it("#875 kill-axis: chatty/non-array leg lists still parse; empty successfulLegs land as verdict prose", () => {
    // r11 high: successfulLegs/skippedLegs z.array courts shape-killed before floor.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: "not-an-array",
      skippedLegs: [
        { slug: "agy", reason: "quota" },
        { slug: "opus", note: "chatty incomplete skip — drop" },
        "bare-string-skip",
      ],
      evidencePaths: ["cmr/review.json"],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.successfulLegs).toEqual([]);
      expect(outcome.skippedLegs).toEqual([
        { slug: "agy", reason: "quota" },
      ]);
    }
  });

  it("#875 kill-axis: non-array claim/disposition top-level values still parse as a verdict", () => {
    // codex high r10: z.array(...) still shape-killed object/string/null before
    // soft-parse. Accept unknown top-level shape; discard unusable prose.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      evidencePaths: ["cmr/review.json"],
      claimedFixedFindingIdentityKeys: { note: "reviewer freeform" },
      priorFindingDispositions: "chatty prose not an array",
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.converged).toBe(true);
      expect(outcome.claimedFixedFindingIdentityKeys).toEqual([]);
      expect(outcome.priorFindingDispositions).toEqual([]);
    }
  });

  it("#875 kill-axis: chatty prior dispositions (unknown status / extra keys) do not malformed the whole verdict", () => {
    // Pre-kill-axis residual: one disposition with unknown status or extra prose
    // key failed cmrFindingDispositionSchema → entire <cmr> malformed → rewrite
    // → durable abort. Post: soft-drop unparseable entries; well-formed neighbors
    // still land; envelope survives as a verdict.
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      evidencePaths: ["cmr/review.json"],
      priorFindingDispositions: [
        {
          identityKey: "correctness|src/x.ts:1|chatty",
          status: "probably-closed-ish",
          note: "reviewer freeform prose",
        },
        {
          identityKey: "correctness|src/x.ts:2|ok",
          status: "verified-closed",
        },
        {
          identityKey: "correctness|src/x.ts:3|extra",
          status: "still-active",
          extraProse: "more chatter",
        },
      ],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome.kind).toBe("verdict");
    if (outcome.kind === "verdict") {
      expect(outcome.converged).toBe(true);
      expect(outcome.priorFindingDispositions).toEqual([
        {
          identityKey: "correctness|src/x.ts:2|ok",
          status: "verified-closed",
        },
      ]);
    }
  });

  it("drops missing evidence-path cargo without rejecting a converged field", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
      skippedLegs: [
        { slug: "opus", reason: "not part of this parser unit" },
        { slug: "agy", reason: "not part of this parser unit" },
      ],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
    })}</cmr>\nCMR_STEP_COMPLETE`);

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      evidencePaths: [],
    });
  });

  it("keeps not-converged cargo when evidence paths are absent", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: false,
      reason: "blocking findings remain",
      successfulLegs: ["gpt-5.6-sol"],
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
      kind: "verdict",
      converged: false,
      reason: "blocking findings remain",
      evidencePaths: [],
    });
  });

  it("strips legacy disposition aliases even when status is already present", () => {
    const outcome = parseCmrOutcome(`<cmr>${JSON.stringify({
      converged: true,
      successfulLegs: ["gpt-5.6-sol"],
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

describe("mergerOutcomeFromResult (#291 structured telemetry parser, pure)", () => {
  it("prefers a runner-owned outcome sidecar over malformed merger stdout", () => {
    const dir = trackTempDir("merger-outcome-");
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
    const dir = trackTempDir("merger-outcome-delimiter-");
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

  it("treats a non-empty malformed merger sidecar as a protocol failure", () => {
    const dir = trackTempDir("merger-outcome-bad-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");

    const outcome = mergerOutcomeFromResult({
      completionSignal: "MERGER_STEP_COMPLETE",
      stdout: '<merger>{"resolved": true}</merger>',
      outcomePath,
    });

    expect(outcome).toMatchObject({
      resolved: false,
      reason: expect.stringContaining("sidecar protocol failure"),
    });
  });

  it("falls back to stdout when the merger outcome sidecar is blank", () => {
    const dir = trackTempDir("merger-outcome-blank-");
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "   \n", "utf8");

    const outcome = mergerOutcomeFromResult({
      completionSignal: "MERGER_STEP_COMPLETE",
      stdout: '<merger>{"resolved": true}</merger>',
      outcomePath,
    });

    expect(outcome).toEqual({ resolved: true });
  });

  it("falls back to signaled merger stdout only when no outcome sidecar path exists", () => {
    expect(
      mergerOutcomeFromResult({
        completionSignal: "MERGER_STEP_COMPLETE",
        stdout: '<merger>{"resolved": true}</merger>',
      }),
    ).toEqual({ resolved: true });
  });

  it("a signaled run delegates to parseMergerOutcome (resolved)", () => {
    expect(
      mergerOutcomeFromResult({
        completionSignal: "MERGER_STEP_COMPLETE",
        stdout: '<merger>{"resolved": true}</merger>',
      }),
    ).toEqual({ resolved: true });
  });
  it("keeps a valid merger result available for git-truth adjudication without a signal", () => {
    // The compatibility signal is telemetry only. The caller must still verify
    // the merge commit and conflict state before recording a landed merge.
    const out = mergerOutcomeFromResult({
      completionSignal: undefined,
      stdout: '<merger>{"resolved": true}</merger>',
    });
    expect(out).toEqual({ resolved: true });
  });
  it("a wrong completion signal is unresolved", () => {
    expect(
      mergerOutcomeFromResult({
        completionSignal: "SOME_OTHER_SIGNAL",
        stdout: '<merger>{"resolved": true}</merger>',
      }).resolved,
    ).toBe(true);
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
  it("gives declared npm build/test verification the provision-class subprocess budget", async () => {
    const commands: Array<{
      file: string;
      args: string[];
      timeoutMs: number | undefined;
    }> = [];
    class LongVerifyBackend extends RealFamilyBackend {
      protected override sh(
        file: string,
        args: string[],
        _cwd?: string,
        timeoutMs?: number,
      ): string {
        commands.push({ file, args, timeoutMs });
        return "";
      }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["build", "test"];
      }
    }
    const backend = new LongVerifyBackend(
      opts("/clone/root", { verifyCwd: "/clone/root/web" }),
    );

    await expect(backend.runFamilyVerify({
      phase: "final",
      familyBase: "family/293-base",
    })).resolves.toEqual({ ok: true });

    expect(commands.filter((command) => command.file === "npm")).toEqual([
      {
        file: "npm",
        args: ["run", "build"],
        timeoutMs: PROVISION_SUBPROCESS_TIMEOUT_MS,
      },
      {
        file: "npm",
        args: ["test"],
        timeoutMs: PROVISION_SUBPROCESS_TIMEOUT_MS,
      },
    ]);
  });

  it("records unknown counts without rewriting the project's typecheck or wave-unit commands", async () => {
    const commands: Array<{ file: string; args: string[] }> = [];
    class ObservedVerifyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], _cwd?: string): string {
        commands.push({ file, args });
        if (args.includes("test")) {
          return JSON.stringify({ numTotalTests: 507 });
        }
        return "";
      }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const options = opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" });
    const backend = new ObservedVerifyBackend(options);

    await expect(backend.runFamilyVerify({
      phase: "wave",
      familyBase: "family/293-base",
      runId: "run-786",
      issue: 786,
    })).resolves.toEqual({ ok: true });
    await backend.waitForStamps();

    const rows = telemetry.readTelemetryRecords(options.ledgerDir).filter(
      (record): record is telemetry.TelemetryVerificationRecord =>
        record.phase === "verification",
    );
    expect(rows).toMatchObject([
      { runId: "run-786", issue: 786, verification: "typecheck", passed: true, count: null },
      { runId: "run-786", issue: 786, verification: "unit", passed: true, count: null },
    ]);
    expect(rows.every((row) => typeof row.duration_ms === "number")).toBe(true);
    expect(commands).toContainEqual({
      file: "npm",
      args: ["run", "typecheck"],
    });
    expect(commands).toContainEqual({ file: "npm", args: ["test"] });
  });

  it("keeps later verification stamps flowing after one unexpected stamp failure", async () => {
    class ObservedVerifyBackend extends RealFamilyBackend {
      protected override sh(): string { return ""; }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const options = opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" });
    vi.spyOn(telemetry, "recordVerificationStamp").mockImplementationOnce(async () => {
      throw new Error("unexpected verification telemetry failure");
    });
    const backend = new ObservedVerifyBackend(options);

    await expect(backend.runFamilyVerify({
      phase: "wave",
      familyBase: "family/293-base",
    })).resolves.toEqual({ ok: true });
    await expect(backend.waitForStamps()).resolves.toBeUndefined();

    expect(telemetry.recordVerificationStamp).toHaveBeenCalledTimes(2);
    expect(telemetry.readTelemetryRecords(options.ledgerDir)).toContainEqual(expect.objectContaining({
      phase: "verification",
      verification: "unit",
      passed: true,
    }));
  });

  it("keeps a failed typecheck count unknown instead of parsing its diagnostic prose", async () => {
    class FailedTypecheckBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], _cwd?: string): string {
        if (file === "npm" && args.includes("typecheck")) {
          const error = new Error("Command failed: npm run typecheck") as Error & {
            stderr?: string;
          };
          error.stderr = [
            "src/one.ts(1,1): error TS2322: first",
            "src/two.ts(2,2): error TS2345: second",
          ].join("\n");
          throw error;
        }
        return "";
      }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const options = opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" });
    const backend = new FailedTypecheckBackend(options);

    await expect(backend.runFamilyVerify({
      phase: "wave",
      familyBase: "family/293-base",
      runId: "run-786",
      issue: 786,
    })).resolves.toMatchObject({ ok: false });
    await backend.waitForStamps();

    expect(telemetry.readTelemetryRecords(options.ledgerDir)).toContainEqual(expect.objectContaining({
      phase: "verification",
      verification: "typecheck",
      passed: false,
      count: null,
    }));
  });

  it("records a failed final observation and preserves the verification verdict", async () => {
    class FailedObservedVerifyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], _cwd?: string): string {
        if (file === "npm" && args[0] === "test") throw new Error("plain test output");
        return "";
      }
      protected override async installDeps(_cwd: string): Promise<void> {}
      protected override isNodeProject(_cwd: string): boolean { return true; }
      protected override packageScripts(_cwd: string): readonly string[] {
        return ["typecheck", "test"];
      }
      public waitForStamps(): Promise<void> { return this.waitForVerificationStamps(); }
    }
    const options = opts("/clone/root", { verifyCwd: "/clone/root/orchestrator" });
    const backend = new FailedObservedVerifyBackend(options);

    await expect(backend.runFamilyVerify({
      phase: "final",
      familyBase: "family/293-base",
      runId: "run-786",
      issue: 786,
    })).resolves.toMatchObject({ ok: false });
    await backend.waitForStamps();

    const rows = telemetry.readTelemetryRecords(options.ledgerDir).filter(
      (record): record is telemetry.TelemetryVerificationRecord =>
        record.phase === "verification",
    );
    expect(rows.map((row) => [row.verification, row.passed])).toEqual([
      ["typecheck", true],
      ["full", false],
    ]);
  });

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
      protected override async runVerifyCommands(): Promise<void> {
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
      protected override async runVerifyCommands(): Promise<void> {
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
    await b.escalateFamily({
      reason: "integrated cmr did not converge: field mismatch",
      escalationKind: "decision",
    });
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

  it("preserves a merger failure's wave shape through the real backend seam", async () => {
    const b = new RealFamilyBackend(opts(trackRepo()));
    await b.escalateFamily({
      reason: "merger step for child #10 exhausted bounded still-conflicted retries",
      familyHeadAfter: "conflicted-10",
      escalationKind: "failure",
      phase: "wave",
    });

    expect(await b.readFamilyLedger()).toEqual([
      expect.objectContaining({
        status: "escalated",
        event: "escalated",
        phase: "wave",
        reason: "merger step for child #10 exhausted bounded still-conflicted retries",
        familyHeadAfter: "conflicted-10",
        escalationKind: "failure",
      }),
    ]);
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
    await b.escalateFamily({
      reason: "new ledger cmr pause",
      escalationKind: "decision",
    });

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
  it("removes a stale fix-focus file when no family brief is mounted", () => {
    class Probe extends RealFamilyBackend {
      public clearFixFocus(landing?: Parameters<RealFamilyBackend["writeFamilyFixFocusFile"]>[0]) {
        return this.writeFamilyFixFocusFile(landing);
      }
    }
    const repo = trackRepo();
    const focusPath = join(repo, FIX_FOCUS_LANDING_FILE);
    writeFileSync(focusPath, "stale interrupted brief\n", "utf8");
    const b = new Probe(opts(repo));

    expect(b.clearFixFocus()).toBeUndefined();
    expect(existsSync(focusPath)).toBe(false);
  });

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

describe("resolveImageTag / DEFAULT_IMAGE_TAG pin (#372 R2)", () => {
  it("provides identical tag for build and dispatch (single source of truth)", () => {
    // Small assertion: launcher + driver read the same resolver/default.
    // Ensures when IMAGE_TAG=... is set, dispatch uses it (not a different default).
    expect(resolveImageTag(undefined)).toBe(DEFAULT_IMAGE_TAG);
    expect(resolveImageTag("")).toBe(DEFAULT_IMAGE_TAG);
    expect(resolveImageTag("ming-orchestrator-coder:latest")).toBe("ming-orchestrator-coder:latest");
    expect(resolveImageTag("custom:tag-xyz")).toBe("custom:tag-xyz");
    // The default is the one build.sh also defaults to.
    expect(DEFAULT_IMAGE_TAG).toBe("ming-orchestrator-coder:latest");
  });
});

/**
 * #909 — family sandbox path must share single-slice idle → quota-probe
 * disposition (wait/relay on 429; do not kill the leg as hang).
 *
 * Seams:
 *   1. RealFamilyBackend.runAgentSandbox + quotaProbe → QuotaWaitForResetError
 *   2. Production family call sites thread quotaProbe (ship via runAgentSandbox)
 *   3. Shared helper only — no second cloned catch body
 */
describe("#909 RealFamilyBackend runAgentSandbox quota/idle parity", () => {
  function idleTimeoutError(): Error {
    return Object.assign(
      new Error(
        "Agent idle for 600 seconds — no output received. Consider increasing the idle timeout with --idle-timeout.",
      ),
      { name: "AgentIdleTimeoutError", _tag: "AgentIdleTimeoutError" },
    );
  }

  class FamilyIdleBackend extends RealFamilyBackend {
    public probeResult: import("../../../src/quotaProbe.js").QuotaProbeResult = {
      kind: "ok",
    };
    public sandcastleReached = false;
    public lastQuotaProbe: import("../../../src/realBackend.js").AgentSandboxRunOptions["quotaProbe"];

    protected override idleNow(): Date {
      return new Date("2026-07-08T12:00:00.000Z");
    }

    protected override async runQuotaProbe(): Promise<
      import("../../../src/quotaProbe.js").QuotaProbeResult
    > {
      return this.probeResult;
    }

    protected override async invokeSandcastleRun(
      options: Parameters<typeof sc.run>[0],
    ): Promise<never> {
      this.sandcastleReached = true;
      void options;
      throw idleTimeoutError();
    }

    protected override async runAgentSandbox(
      options: import("../../../src/realBackend.js").AgentSandboxRunOptions,
    ): Promise<Awaited<ReturnType<typeof sc.run>>> {
      this.lastQuotaProbe = options.quotaProbe;
      expect(options.quotaProbe?.workerPid).toBeUndefined();
      return super.runAgentSandbox(options);
    }

    public exposeRunAgentSandbox(
      options: import("../../../src/realBackend.js").AgentSandboxRunOptions,
    ) {
      return this.runAgentSandbox(options);
    }

    public exposeShipContainerRun(spec: WorkerSpec) {
      return this.shipContainerRun(spec, {
        claudeToken: "tok",
        codexAuthDir: undefined,
        grokAuthDir: undefined,
        ghToken: "gh",
      });
    }
  }

  function makeFamilyIdleBackend(): FamilyIdleBackend {
    return new FamilyIdleBackend(opts(trackRepo()));
  }

  it("429 via family runAgentSandbox → QuotaWaitForResetError; no hang kill", async () => {
    const { QuotaWaitForResetError } = await import("../../../src/quotaProbe.js");
    const backend = makeFamilyIdleBackend();
    const resetAt = new Date("2026-07-08T16:10:00.000Z");
    backend.probeResult = {
      kind: "quota_limited",
      resetAt,
      detail: "429 wall",
    };

    let thrown: unknown;
    try {
      await backend.exposeRunAgentSandbox({
        name: "family-coder-fix",
        idleTimeoutSeconds: 600,
        cwd: "/tmp/family",
        sandbox: {} as import("../../../src/realBackend.js").AgentSandboxRunOptions["sandbox"],
        agent: {} as import("../../../src/realBackend.js").AgentSandboxRunOptions["agent"],
        maxIterations: 1,
        completionSignal: "CODER_STEP_COMPLETE",
        branchStrategy: { type: "head" },
        promptFile: join(realPromptsDir, "coder_fix.md"),
        quotaProbe: {
          modelRef: "zai/glm-5.2",
          step: "S5",
          worktreePath: "/tmp/family",
          issueNumber: 909,
        },
      });
    } catch (err) {
      thrown = err;
    }

    expect(thrown).toBeInstanceOf(QuotaWaitForResetError);
    const qw = thrown as InstanceType<typeof QuotaWaitForResetError>;
    expect(backend.sandcastleReached).toBe(true);
    expect(qw.applied.ledgerEntry).toMatchObject({
      event: "quota_wait_for_reset",
      resetAt: "2026-07-08T16:10:00.000Z",
      step: "S5",
    });
    expect(backend.lastQuotaProbe).toMatchObject({
      modelRef: "zai/glm-5.2",
      step: "S5",
      issueNumber: 909,
    });
  });

  it("probe ok via family Sandcastle fallback rethrows idle (fail-safe hang)", async () => {
    const backend = makeFamilyIdleBackend();
    backend.probeResult = { kind: "ok" };

    await expect(
      backend.exposeRunAgentSandbox({
        name: "family-cmr",
        idleTimeoutSeconds: 600,
        cwd: "/tmp/family",
        sandbox: {} as import("../../../src/realBackend.js").AgentSandboxRunOptions["sandbox"],
        agent: {} as import("../../../src/realBackend.js").AgentSandboxRunOptions["agent"],
        maxIterations: 1,
        completionSignal: "CMR_STEP_COMPLETE",
        branchStrategy: { type: "head" },
        promptFile: join(realPromptsDir, "integrated_cmr_correctness.md"),
        quotaProbe: { modelRef: "gpt-5.6-terra", step: "S3" },
      }),
    ).rejects.toThrow(/Agent idle for 600/);
  });

  it("without quotaProbe context, idle error rethrows with no probe", async () => {
    const backend = makeFamilyIdleBackend();
    backend.probeResult = {
      kind: "quota_limited",
      resetAt: new Date("2026-07-08T16:10:00.000Z"),
    };

    await expect(
      backend.exposeRunAgentSandbox({
        name: "family-ship",
        idleTimeoutSeconds: 600,
        cwd: "/tmp/family",
        sandbox: {} as import("../../../src/realBackend.js").AgentSandboxRunOptions["sandbox"],
        agent: {} as import("../../../src/realBackend.js").AgentSandboxRunOptions["agent"],
        maxIterations: 1,
        completionSignal: "SHIP_STEP_COMPLETE",
        branchStrategy: { type: "head" },
        promptFile: join(realPromptsDir, "family_ship.md"),
        quotaProbe: undefined,
      }),
    ).rejects.toThrow(/Agent idle for 600/);
  });

  it("shipContainerRun routes through runAgentSandbox with quotaProbe", async () => {
    const { QuotaWaitForResetError } = await import("../../../src/quotaProbe.js");
    const backend = makeFamilyIdleBackend();
    backend.probeResult = {
      kind: "quota_limited",
      resetAt: new Date("2026-07-08T16:10:00.000Z"),
      detail: "429",
    };

    await expect(
      backend.exposeShipContainerRun({
        id: "S7",
        kind: "ship",
        role: "coder",
        host: "codex",
        session: "fresh",
        contextRetention: "clean",
        skill: "gstack-ship",
        promptFile: "family_ship.md",
        completionSignal: "SHIP_STEP_COMPLETE",
        maxIter: 5,
        model: "gpt-5.6-terra",
        soul: "ship",
        toolchain: [],
      }),
    ).rejects.toBeInstanceOf(QuotaWaitForResetError);

    expect(backend.lastQuotaProbe).toMatchObject({
      modelRef: "gpt-5.6-terra",
      step: "S7",
    });
  });

  it("family + single-slice both call shared withIdleQuotaProbeDisposition (no second clone)", () => {
    const familySrc = readFileSync(
      join(here, "..", "..", "..", "src", "family", "realFamilyBackend.ts"),
      "utf8",
    );
    const realSrc = readFileSync(
      join(here, "..", "..", "..", "src", "realBackend.ts"),
      "utf8",
    );
    expect(familySrc).toMatch(/withIdleQuotaProbeDisposition/);
    expect(realSrc).toMatch(/withIdleQuotaProbeDisposition/);
    // Family must not re-clone the idle-name catch body beside the shared helper.
    const familyCatchBody = familySrc.slice(
      familySrc.indexOf("protected async runAgentSandbox"),
      familySrc.indexOf("protected async resolveIdleAfterQuotaProbe"),
    );
    expect(familyCatchBody).toMatch(/withIdleQuotaProbeDisposition/);
    expect(familyCatchBody).not.toMatch(/isAgentIdleTimeoutError/);
  });
});
