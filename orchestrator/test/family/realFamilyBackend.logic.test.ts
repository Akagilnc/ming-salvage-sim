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
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import {
  parseMergerOutcome,
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../src/family/realFamilyBackend.js";
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
function trackRepo(): string {
  const r = makeRepo();
  repos.push(r);
  return r;
}
afterEach(() => {
  for (const r of repos) rmSync(r, { recursive: true, force: true });
  repos = [];
});

/** Default options pointing the Backend at a real repo + the real prompts dir. */
function opts(workingRepo: string, over: Partial<RealFamilyBackendOptions> = {}): RealFamilyBackendOptions {
  return {
    workingRepo,
    familyBase: "family/293-base",
    ledgerDir: mkdtempSync(join(tmpdir(), "rfb-ledger-")),
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

  it("familyBaseStartHead returns the recorded start head", async () => {
    const repo = trackRepo();
    git(repo, "checkout", "-q", "-b", "family/293-base");
    const start = git(repo, "rev-parse", "HEAD");
    const recon = new RealFamilyBackend(opts(repo, { familyBaseStartHead: start })).reconcileGit();
    expect(await recon.familyBaseStartHead()).toBe(start);
  });
});

// ═══════════════════ 4. resolveMergeConflict (sc.run seam) ═══════════════════

/** A subclass that fakes the external seams (merger agent / verify / cmr / sh). */
class FakeSeamsBackend extends RealFamilyBackend {
  mergerOutcome: { resolved: boolean; reason?: string } = { resolved: true };
  mergerCalls: ConflictResolveRequest[] = [];
  verifyOutcome: "green" | "red" = "green";
  verifyCalls: FamilyVerifyRequest[] = [];
  cmrResult: IntegratedCmrResult = { converged: true };
  cmrCalls: IntegratedCmrRequest[] = [];
  shCalls: Array<{ file: string; args: string[] }> = [];
  mergeInProgressFake = false;

  protected override async runMergerAgent(req: ConflictResolveRequest) {
    this.mergerCalls.push(req);
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
  // Intercept the git/gh/npx subprocess seam so no real command runs.
  protected override sh(file: string, args: string[], _cwd?: string): string {
    this.shCalls.push({ file, args });
    if (file === "git" && args[0] === "rev-parse") return "deadbeef";
    if (file === "gh" && args[0] === "pr" && args[1] === "create") {
      return "https://github.com/Akagilnc/ming-salvage-sim/pull/777";
    }
    return "";
  }
}

describe("RealFamilyBackend resolveMergeConflict (#291 sc.run merger seam)", () => {
  it("resolved agent → returns the resolved head (NOT conflicted); runs ONE merger agent", async () => {
    const b = new FakeSeamsBackend(opts(trackRepo()));
    b.mergerOutcome = { resolved: true };
    b.mergeInProgressFake = false; // the agent committed the merge
    const res = await b.resolveMergeConflict({ childIssue: 10, childBranch: "feat/child-10" });
    expect(b.mergerCalls).toEqual([{ childIssue: 10, childBranch: "feat/child-10" }]);
    expect(res.conflicted ?? false).toBe(false);
    expect(res.familyHead).toBe("deadbeef");
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
    const res = await b.openFamilyPr({ familyBase: "family/293-base" });
    expect(res.url).toContain("/pull/777");
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
});

// ═══════════════════════════ 8. recordAborted / escalate ════════════════════

describe("RealFamilyBackend recordAborted (#291 phase-level aborted ledger)", () => {
  it("appends a phase-level aborted entry (no childIssue) carrying reason + head", async () => {
    const b = new RealFamilyBackend(opts(trackRepo()));
    await b.recordAborted({
      phase: "wave",
      familyBase: "family/293-base",
      errorPackage: { reason: "tsc: TS2322 in regionApply" },
      familyHeadAfter: "headAfter",
    });
    const ledger = await b.readFamilyLedger();
    expect(ledger).toEqual([
      {
        status: "aborted",
        event: "aborted",
        phase: "wave",
        reason: "tsc: TS2322 in regionApply",
        familyHeadAfter: "headAfter",
      },
    ]);
    // An aborted entry has NO childIssue → it never unblocks a downstream slice.
    expect(ledger[0]?.childIssue).toBeUndefined();
  });
});

describe("RealFamilyBackend escalateFamily (#291 durable stuck-point)", () => {
  it("persists a durable escalate record readable back (survives the process)", async () => {
    const b = new RealFamilyBackend(opts(trackRepo()));
    await b.escalateFamily({ reason: "integrated cmr did not converge: field mismatch" });
    const recs = await b.readEscalations();
    expect(recs).toHaveLength(1);
    expect(recs[0]?.reason).toContain("cmr did not converge");
    expect(recs[0]?.ts).toMatch(/\d{4}-\d{2}-\d{2}T/);
  });
});
