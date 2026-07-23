import {
  execFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  vi,
  sc,
  discoverSubprojects,
  MERGER_SOUL,
  cmrOutcomeFromResult,
  mergerOutcomeFromResult,
  MergerAuth,
  parseCmrOutcome,
  REFERENCED_FAMILY_PROMPT_FILES,
  RealFamilyBackend,
  RealFamilyBackendOptions,
  familyEscalationState,
  MAX_DISPATCH_ATTEMPTS,
  SANDBOX_SKILLS_DIR,
  soulsMount,
  ConflictResolveRequest,
  FamilyVerifyRequest,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  DEFAULT_IMAGE_TAG,
  resolveImageTag,
  PROVISION_SUBPROCESS_TIMEOUT_MS,
  WorkerSpec,
  telemetry,
  buildExplicitLandingLiveHooks,
  here,
  realPromptsDir,
  realSoulsDir,
  git,
  makeRepo,
  commitFile,
  tempState,
  trackTempDir,
  trackRepo,
  opts,
  FakeSeamsBackend,
} from "./real-backend.shared.js";
import { ensureGitInfoExclude } from "../../../src/gitInfoExclude.js";

afterEach(() => {
  for (const r of tempState.repos) rmSync(r, { recursive: true, force: true });
  for (const d of tempState.ledgerDirs) rmSync(d, { recursive: true, force: true });
  tempState.repos = [];
  tempState.ledgerDirs = [];
});

describe("RealFamilyBackend live officer effort", () => {
  class Probe extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    public agentForLiveSpec(spec: WorkerSpec, billingPool?: string): sc.AgentProvider {
      return this.agentForSpec(spec, { billingPool });
    }
  }

  const liveSpec = (overrides: Partial<WorkerSpec>): WorkerSpec => ({
    id: "S3",
    kind: "cmr",
    role: "verify",
    host: "claude",
    session: "fresh",
    contextRetention: "clean",
    promptFile: "integrated_cmr_completeness.md",
    maxIter: 1,
    model: "gpt-5.6-sol",
    soul: "verify",
    toolchain: [],
    ...overrides,
  });

  it("dispatches registry medium for gpt-5.6-sol — role/soul cannot force xhigh", () => {
    // #916: effort authority = registry row only. verify/cmr seats on
    // gpt-5.6-sol are medium; no role/soul live-officer override.
    const backend = new Probe(opts(trackRepo()));
    const commandFor = (spec: WorkerSpec) =>
      backend.agentForLiveSpec(spec).buildPrintCommand({ prompt: "test", dangerouslySkipPermissions: false }).command;

    expect(commandFor(liveSpec({ soul: "verify" }))).toContain(
      'model_reasoning_effort="medium"',
    );
    expect(
      commandFor(liveSpec({ id: "S5", kind: "verify", role: "verify", soul: "READ-ONLY" })),
    ).toContain('model_reasoning_effort="medium"');
    expect(commandFor(liveSpec({ soul: "verify" }))).not.toContain(
      'model_reasoning_effort="xhigh"',
    );
  });

  it("dispatches registry low for gpt-5.6-sol-low ship/utility seats", () => {
    const backend = new Probe(opts(trackRepo()));
    const command = backend
      .agentForLiveSpec(
        liveSpec({
          // Production family ship specs use role:"coder" + soul:"ship" (StepRole
          // has no "ship"; see familyShipWorkerSpec / ship-worker tests).
          id: "S8",
          kind: "ship",
          role: "coder",
          soul: "ship",
          model: "gpt-5.6-sol-low",
        }),
      )
      .buildPrintCommand({ prompt: "test", dangerouslySkipPermissions: false }).command;
    expect(command).toContain('model_reasoning_effort="low"');
  });

  it("applies the ADR 0124 billing-pool provider binding to family workers", () => {
    const backend = new Probe(opts(trackRepo()));
    const provider = backend.agentForLiveSpec(
      liveSpec({ model: "grok-4.5" }),
      "grok-build",
    );
    expect(provider.name).toBe("grok");
    const command = provider
      .buildPrintCommand({ prompt: "test", dangerouslySkipPermissions: false }).command;
    expect(command).toContain("prompt_file=$(mktemp)");
    expect(command).toContain('grok --prompt-file "$prompt_file"');
  });
});

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
    tempState.ledgerDirs.push(dir); // reuse the afterEach cleanup list
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

  it("constructs cleanly when all family prompts are present (the real prompts dir)", () => {
    const repo = trackRepo();
    expect(() => new RealFamilyBackend(opts(repo))).not.toThrow();
  });
});

describe("RealFamilyBackend resolveMergeConflict (#291 sc.run merger seam)", () => {
  it("checks conflict markers only in files introduced or modified by the merge", () => {
    class MarkerScopeBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

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
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

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

// #596 F2: family-side decode seam test (raw through parse*Outcome)
// #919 CR N1: cargo parsers no longer ring classifyDecisionGate bells.
describe("#596 F2: family-side real decode (parseVerifyOutcome etc) for review-loop kinds (raw, not fake)", () => {
  it.each([
    ["verify", "parseVerifyOutcome"],
    ["fixer", "parseFixerOutcome"],
    ["cleanup", "parseCleanupOutcome"],
    ["landing", "parseLandingOutcome"],
  ] as const)(
    "%s cargo with nested escalate is opaque cargo (no decision-gate dual)",
    async (tag, parser) => {
      const mod = await import("../../../src/family/realFamilyBackend.js");
      const out = mod[parser](
        `<${tag}>${JSON.stringify({
          unrelatedCargo: { wrong: [1, 2, 3] },
          escalate: { reason: "owner choice", diagnosis: "family contract fork" },
        })}</${tag}>`,
      );
      // #919 CR N1: receiptDecisionBell DELETED — escalate-only/off-shape is cargo.
      expect(out).toMatchObject({ kind: "cargo" });
    },
  );

  it.each(["verify", "fixer", "cleanup", "landing"] as const)(
    "fails family %s when typed decision Output.object is absent",
    async (role) => {
      // #899: SO seat without result.output must not become cargo/no-gate success.
      const reviewLoopSpec = (kind: typeof role): WorkerSpec => ({
        id: "S9",
        kind,
        role: "coder",
        host: "claude",
        session: "fresh",
        contextRetention: "clean",
        promptFile: "x.md",
        maxIter: 1,
        model: "sonnet",
        soul: "coder",
        toolchain: [],
      });
      class Harness extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

        public classify(
          result: {
            output?: unknown;
            stdout: string;
            iterations?: ReadonlyArray<{ readonly sessionId?: string }>;
          },
          kind: typeof role,
          outcomePath: string,
        ) {
          return this.familyReviewLoopResultFromRun(
            {
              stdout: result.stdout,
              iterations: [...(result.iterations ?? [])],
              ...(result.output !== undefined ? { output: result.output } : {}),
            },
            reviewLoopSpec(kind),
            outcomePath,
          );
        }
      }
      const dir = trackTempDir(`review-loop-missing-typed-${role}-`);
      const outcomePath = join(dir, "outcome.json");
      writeFileSync(outcomePath, JSON.stringify({ converged: true }), "utf8");
      const be = new Harness({
        workingRepo: dir,
        familyBase: "fb",
        ledgerDir: dir,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
        familyBaseStartHead: "abc",
      });
      expect(() =>
        be.classify({ stdout: "" }, role, outcomePath),
      ).toThrow(/typed traffic signal missing/);
    },
  );

  class FamilyCoderDecodeHarness extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    public classify(
      result: {
        output?: unknown;
        stdout: string;
        iterations?: ReadonlyArray<{ readonly sessionId?: string }>;
      },
      outcomePath: string,
    ) {
      return this.familyCoderResultFromRun(
        {
          stdout: result.stdout,
          commits: [],
          iterations: [...(result.iterations ?? [])],
          ...(result.output !== undefined ? { output: result.output } : {}),
        },
        {
          id: "S5",
          kind: "coder",
          role: "coder",
          host: "claude",
          session: "fresh",
          contextRetention: "clean",
          promptFile: "x.md",
          maxIter: 1,
          model: "sonnet",
          soul: "coder",
          toolchain: [],
        },
        outcomePath,
      );
    }
  }

  function familyCoderDecodeHarness(dir: string): FamilyCoderDecodeHarness {
    return new FamilyCoderDecodeHarness({
      workingRepo: dir,
      familyBase: "fb",
      ledgerDir: dir,
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc",
    });
  }

  it.each(["verify", "fixer", "cleanup", "landing"] as const)(
    "does not let sidecar bells override a schema-validated typed %s decision signal",
    async (role) => {
      // #899 finding: when typed Output.object exists it is the sole fate channel;
      // sidecar escalate must not enter the human loop for any review-loop role.
      const reviewLoopSpec = (kind: typeof role): WorkerSpec => ({
        id: "S9",
        kind,
        role: "coder",
        host: "claude",
        session: "fresh",
        contextRetention: "clean",
        promptFile: "x.md",
        maxIter: 1,
        model: "sonnet",
        soul: "coder",
        toolchain: [],
      });
      class Harness extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

        public classify(
          result: {
            output?: unknown;
            stdout: string;
            iterations?: ReadonlyArray<{ readonly sessionId?: string }>;
          },
          kind: typeof role,
          outcomePath: string,
        ) {
          return this.familyReviewLoopResultFromRun(
            {
              stdout: result.stdout,
              iterations: [...(result.iterations ?? [])],
              ...(result.output !== undefined ? { output: result.output } : {}),
            },
            reviewLoopSpec(kind),
            outcomePath,
          );
        }
      }
      const dir = trackTempDir(`review-loop-typed-vs-sidecar-${role}-`);
      const outcomePath = join(dir, "outcome.json");
      // Typed T2 onlineReview completed. Role cargo + a spoof escalate
      // ride on the sidecar; only cargo is admitted (escalate cannot override).
      const cargo: Record<string, unknown> =
        role === "verify"
          ? { converged: true }
          : role === "fixer"
            ? { committed: true }
            : role === "cleanup"
              ? { terminal: true, ok: true }
              : { released: true };
      writeFileSync(
        outcomePath,
        JSON.stringify({
          ...cargo,
          escalate: { reason: "sidecar spoof", diagnosis: "must not win" },
        }),
        "utf8",
      );
      const be = new Harness({
        workingRepo: dir,
        familyBase: "fb",
        ledgerDir: dir,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
        familyBaseStartHead: "abc",
      });
      const out = be.classify(
        {
          output: { station: "onlineReview", status: "completed" },
          stdout: "",
        },
        role,
        outcomePath,
      );
      expect(out.kind).toBe("completed");
      if (out.kind === "completed") {
        expect(out.output.kind).toBe(role);
      }
    },
  );

  it.each(["verify", "fixer", "cleanup", "landing"] as const)(
    "family %s T2 onlineReview escalate still parks decision",
    async (role) => {
      const reviewLoopSpec = (kind: typeof role): WorkerSpec => ({
        id: "S9",
        kind,
        role: "coder",
        host: "claude",
        session: "fresh",
        contextRetention: "clean",
        promptFile: "x.md",
        maxIter: 1,
        model: "sonnet",
        soul: "coder",
        toolchain: [],
      });
      class Harness extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

        public classify(
          result: {
            output?: unknown;
            stdout: string;
            iterations?: ReadonlyArray<{ readonly sessionId?: string }>;
          },
          kind: typeof role,
          outcomePath: string,
        ) {
          return this.familyReviewLoopResultFromRun(
            {
              stdout: result.stdout,
              iterations: [...(result.iterations ?? [])],
              ...(result.output !== undefined ? { output: result.output } : {}),
            },
            reviewLoopSpec(kind),
            outcomePath,
          );
        }
      }
      const dir = trackTempDir(`review-loop-t2-escalate-${role}-`);
      const outcomePath = join(dir, "outcome.json");
      writeFileSync(outcomePath, JSON.stringify({}), "utf8");
      const be = new Harness({
        workingRepo: dir,
        familyBase: "fb",
        ledgerDir: dir,
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
        familyBaseStartHead: "abc",
      });
      const out = be.classify(
        {
          output: {
            station: "onlineReview",
            status: "escalate",
            reason: "owner choice",
            diagnosis: "review fork",
          },
          stdout: "",
        },
        role,
        outcomePath,
      );
      expect(out).toMatchObject({
        kind: "escalated",
        escalation: { reason: "owner choice", diagnosis: "review fork" },
      });
    },
  );

});

describe("mergerOutcomeFromResult (#291 structured telemetry parser, pure)", () => {

  it("production merger attaches T2 merger station receipt (not decision-gate dual)", async () => {
    // #919 CR S2: SO tag is merger + thin completed|escalate schema.
    const repo = trackRepo();
    const ledgerDir = mkdtempSync(join(tmpdir(), "merger-t2-attach-"));
    tempState.ledgerDirs.push(ledgerDir);
    const calls: Parameters<typeof sc.run>[0][] = [];
    class AttachBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

      public run(req: ConflictResolveRequest) {
        return this.runMergerAgent(req);
      }
      protected override mountMergerAuth(): MergerAuth {
        return { claudeToken: "tok" };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        calls.push(options);
        return {
          branch: "family/293-base",
          stdout: "<merger>{}</merger>",
          commits: [],
          iterations: [],
          output: { station: "merger", status: "completed" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new AttachBackend(opts(repo, { ledgerDir }));
    await b.run({ childIssue: 496, childBranch: "feat/child" });
    expect(calls).toHaveLength(1);
    expect(calls[0]!.output).toMatchObject({ tag: "merger" });
    expect(calls[0]!.output).not.toMatchObject({ tag: "decision" });
  });
});

describe("RealFamilyBackend merger outcome sidecar cleanup", () => {
  it("removes the temporary outcome sidecar directory after parsing the merger result", async () => {
    const repo = trackRepo();
    const ledgerDir = mkdtempSync(join(tmpdir(), "merger-cleanup-ledger-"));
    tempState.ledgerDirs.push(ledgerDir);
    let outcomePathAtRun: string | undefined;
    class CleanupBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

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
          branch: "family/293-base",
          stdout: "<merger>{}</merger>",
          commits: [],
          iterations: [],
          // Typed T2 merger completed (SO was attached on this seat).
          output: { station: "merger", status: "completed" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new CleanupBackend(opts(repo, { ledgerDir }));
    const out = await b.run({ childIssue: 496, childBranch: "feat/child" });

    expect(out.resolved).toBe(true);
    expect(outcomePathAtRun).toBeDefined();
    expect(existsSync(dirname(outcomePathAtRun as string))).toBe(false);
  });

  it("fails merger when typed decision Output.object is absent", async () => {
    // #899: SO seat without result.output must not complete from cargo alone.
    const repo = trackRepo();
    const ledgerDir = mkdtempSync(join(tmpdir(), "merger-missing-typed-ledger-"));
    tempState.ledgerDirs.push(ledgerDir);
    class MissingTypedMergerBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

      public run(req: ConflictResolveRequest) {
        return this.runMergerAgent(req);
      }
      protected override mountMergerAuth(): MergerAuth {
        return { claudeToken: "tok" };
      }
      protected override async runAgentSandbox(
        _options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        return {
          branch: "family/293-base",
          stdout: '<merger>{"resolved": true}</merger>',
          commits: [],
          iterations: [],
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const b = new MissingTypedMergerBackend(opts(repo, { ledgerDir }));
    await expect(
      b.run({ childIssue: 496, childBranch: "feat/child" }),
    ).rejects.toThrow(/typed traffic signal missing/);
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
      reason: "merger_worker left child #10 conflict unresolved on the family base",
      familyHeadAfter: "conflicted-10",
      escalationKind: "failure",
      phase: "wave",
    });

    expect(await b.readFamilyLedger()).toEqual([
      expect.objectContaining({
        status: "escalated",
        event: "escalated",
        phase: "wave",
        reason: "merger_worker left child #10 conflict unresolved on the family base",
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

  it("#934: legacy escalation off-shape / invalid JSON fails closed (no silent cast)", async () => {
    const o = opts(trackRepo());
    mkdirSync(o.ledgerDir, { recursive: true });
    writeFileSync(
      join(o.ledgerDir, "family-escalations.jsonl"),
      "not-json-at-all\n",
      "utf8",
    );
    const b = new RealFamilyBackend(o);
    await expect(b.readEscalations()).rejects.toThrow(/not valid JSON|fail closed/i);

    writeFileSync(
      join(o.ledgerDir, "family-escalations.jsonl"),
      `${JSON.stringify({ reason: 42 })}\n`,
      "utf8",
    );
    await expect(b.readEscalations()).rejects.toThrow(
      /not a valid FamilyEscalationRecord shape|fail closed/i,
    );
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
  it("treats CRLF exclude entries as existing lines instead of appending duplicates", () => {
    const repo = trackRepo();
    const excludePath = join(repo, ".git", "info", "exclude");
    writeFileSync(excludePath, ".orchestrator-outcome.json\r\n", "utf8");

    ensureGitInfoExclude(repo, ".orchestrator-outcome.json");

    expect(readFileSync(excludePath, "utf8")).toBe(".orchestrator-outcome.json\r\n");
  });

  it("treats CRLF exclude entries as existing lines in the CMR exclude helper too", () => {
    class Probe extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

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

/**
 * #909/#937 — family sandbox shares single-slice silence contract (ID-007):
 * Sandcastle idle rethrows without quota probe/park. Explicit 429 is separate.
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
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    public sandcastleReached = false;

    protected override async invokeSandcastleRun(
      options: Parameters<typeof sc.run>[0],
    ): Promise<never> {
      this.sandcastleReached = true;
      void options;
      throw idleTimeoutError();
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

  it("family runAgentSandbox idle rethrows without QuotaWait (#937 ID-007)", async () => {
    const { QuotaWaitForResetError } = await import("../../../src/quotaProbe.js");
    const backend = makeFamilyIdleBackend();
    await expect(
      backend.exposeRunAgentSandbox({
        name: "family-idle",
        idleTimeoutSeconds: 600,
        cwd: "/tmp",
        sandbox: {} as never,
        agent: {} as never,
        maxIterations: 1,
        branchStrategy: { type: "head" },
        promptFile: "x.md",
      }),
    ).rejects.toThrow(/Agent idle for 600/);
    expect(backend.sandcastleReached).toBe(true);
    await expect(
      backend.exposeRunAgentSandbox({
        name: "family-idle",
        idleTimeoutSeconds: 600,
        cwd: "/tmp",
        sandbox: {} as never,
        agent: {} as never,
        maxIterations: 1,
        branchStrategy: { type: "head" },
        promptFile: "x.md",
      }),
    ).rejects.not.toBeInstanceOf(QuotaWaitForResetError);
  });

  it("shipContainerRun idle rethrows without QuotaWait (#937 ID-007)", async () => {
    const { QuotaWaitForResetError } = await import("../../../src/quotaProbe.js");
    const backend = makeFamilyIdleBackend();

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
        maxIter: 1,
        model: "gpt-5.6-terra",
        soul: "ship",
        toolchain: [],
      }),
    ).rejects.toThrow(/Agent idle for 600/);

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
        maxIter: 1,
        model: "gpt-5.6-terra",
        soul: "ship",
        toolchain: [],
      }),
    ).rejects.not.toBeInstanceOf(QuotaWaitForResetError);
  });

});
