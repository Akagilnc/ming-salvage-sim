/**
 * #291 Unit B — END-TO-END family-driver effect proof.
 *
 * This is the铁证 that the #291 family orchestration串起来 runs on REAL backends:
 * a REAL git repo, a REAL RealFamilyBackend (real `git merge --no-ff`, real
 * family-ledger JSONL, real reconcile git seam), the REAL spine (`runFamily` via
 * `runFamilyDriver`), real dependency-wave scheduling, real merge commits landing
 * on a real LOCAL family base — and it STOPS at the PR step.
 *
 * What is受控注入 (so we never start a container / open a real PR / burn quota):
 *   - the epic-read `gh` (sub-issues + blocked_by) → an injected `sh`;
 *   - the child fan-out (`sc.run` coder + merger agent) → a container-free
 *     single-slice Backend that does REAL git on the clone (real `git worktree
 *     add` + a real commit), producing a real reviewed child branch the family
 *     merger then REALLY merges;
 *   - the family verify / integrated cmr / ship worker (#336: gstack-ship) → the
 *     RealFamilyBackend's protected seams overridden to controlled outcomes (verify
 *     green, cmr converged, ship a synthetic pr_opened) — so verify+cmr+ship really
 *     gate, and the run STOPS at the PR (the seam is reached, no real container).
 *
 * The MERGE / LEDGER / RECONCILE / WAVE-SCHEDULE are all REAL. Asserted:
 *   1. wave scheduling: a dependency child (#13 blocked_by #12) merges AFTER its
 *      blocker — topological, ledger-driven, multi-wave;
 *   2. a REAL `--no-ff` merge commit per child lands on the LOCAL family base
 *      (the family base HEAD advances; each child's file is present);
 *   3. the family ledger REALLY records each merge (a JSONL sibling file);
 *   4. the run STOPS at the PR (the ship WORKER is dispatched exactly once with
 *      the family base through the #336 gstack-ship worker; status
 *      === "success"; no merge to main).
 */

import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import { runFamilyDriver, type Sh } from "../../../src/familyDriver.js";
import {
  RealFamilyBackend,
  type CmrWorkerOutcome,
} from "../../../src/family/realFamilyBackend.js";
import { shipOutcomeFromResult } from "../../../src/shipOutcome.js";
import type {
  FamilyVerifyRequest,
  IntegratedCmrRequest,
} from "../../../src/family/types.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";
import type {

  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const here = dirname(fileURLToPath(import.meta.url));
const familyPromptsDir = join(here, "..", "..", "..", "prompts");
const familySoulsDir = join(here, "..", "..", "..", "image", "souls");

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}

/** A real temp git repo (the SOURCE the driver clones) with a `main` + root commit. */
function makeSourceRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "e2e-src-"));
  git(dir, "init", "-q", "-b", "main");
  git(dir, "config", "user.email", "t@t.t");
  git(dir, "config", "user.name", "t");
  git(dir, "config", "commit.gpgsign", "false");
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: dir });
  return dir;
}

const cleanups: string[] = [];
function track(p: string): string {
  cleanups.push(p);
  return p;
}
afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

/**
 * The injected `gh`+git `sh`: gh epic-read is FAKED (sub-issues + blocked_by);
 * git is REAL (the family-base cut on the real clone). The epic: children 11, 12
 * (independent) and 13 (blocked_by 12) — so wave 1 = {11,12}, wave 2 = {13}.
 */
function makeSh(): Sh {
  const SUB_ISSUES = JSON.stringify([{ number: 11 }, { number: 12 }, { number: 13 }]);
  const blockedBy: Record<number, string> = {
    11: "[]",
    12: "[]",
    13: JSON.stringify([{ number: 12, state: "open" }]),
  };
  return (file, args) => {
    if (file === "gh") {
      if (args[0] === "api") {
        if (String(args[1]).includes("/sub_issues")) return SUB_ISSUES;
        // .../issues/<n>/dependencies/blocked_by
        const m = /issues\/(\d+)\/dependencies/.exec(args[1] ?? "");
        const n = m ? Number(m[1]) : -1;
        return blockedBy[n] ?? "[]";
      }
      if (args[0] === "issue" && args[1] === "view") {
        return JSON.stringify({
          number: Number(args[2]),
          body: "",
        });
      }
      throw new Error(`unexpected gh call: ${args.join(" ")}`);
    }
    // REAL git (the family-base cut etc.).
    return execFileSync(file, args, { encoding: "utf8" }).trim();
  };
}

/**
 * A container-free single-slice Backend producing a REAL committed child branch on
 * the family clone: `prepareWorktree` cuts `feat/child-<n>` from the family base
 * (a real `git worktree add`), `runStep`(coder) commits a UNIQUE file in that
 * worktree (distinct file per child ⇒ clean merges). No `sc.run`, no container.
 */
class RealGitChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly worktrees = new Map<number, string>();
  constructor(private readonly clone: string) {}
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async resumeSession(spec: StepSpec, worktree: WorktreeHandle): Promise<StepOutput> {
    return this.runStep(spec, worktree);
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    const branch = `feat/child-${issueNumber}`;
    const wtPath = join(this.clone, "..", `e2e-wt-${issueNumber}-${Date.now()}`);
    // REAL git worktree add off the LOCAL family base (the cut base the spine passes).
    git(this.clone, "worktree", "add", "-b", branch, wtPath, base);
    this.worktrees.set(issueNumber, wtPath);
    track(wtPath);
    return { branch, base, path: wtPath };
  }
  async runStep(spec: StepSpec, worktree: WorktreeHandle): Promise<StepOutput> {
    if (spec.role === "coder") {
      // Use the run's OWN worktree handle (B7-concurrency-safe: two children run
      // concurrently, each with its own worktree). Commit a UNIQUE file per child
      // (by its branch number) so each merge into the family base is clean.
      const wt = worktree.path;
      const num = Number(/child-(\d+)/.exec(worktree.branch)?.[1] ?? 0);
      execFileSync("bash", ["-c", `printf 'child %s' '${num}' > '${join(wt, `child-${num}.txt`)}'`]);
      git(wt, "config", "user.email", "t@t.t");
      git(wt, "config", "user.name", "t");
      git(wt, "add", "-A");
      execFileSync("git", ["commit", "-q", "-m", `child ${num}`], { cwd: wt });
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

/**
 * A REAL RealFamilyBackend (real merge / ledger / reconcile) whose verify / cmr /
 * PR seams are controlled: verify green, cmr converged, PR a synthetic url (so the
 * run reaches + STOPS at the PR seam without a real remote push). It records the
 * verify / cmr / PR calls so the test can assert the run stopped at the PR.
 */
class E2EFamilyBackend extends RealFamilyBackend {
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

  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly shipCalls: string[] = [];
  protected override async runVerifyCommands(req: FamilyVerifyRequest): Promise<void> {
    this.verifyCalls.push(req); // green: no throw, no real npx.
  }
  // #335: the integrated cmr is a CONTAINER cmr worker via dispatchWorker →
  // runCmrWorker. Override the worker seam (no real container) so the e2e proves
  // the run reaches the cmr step + STOPS at the PR, recording the family base it
  // reviewed (no real cross-model squad, no image).
  protected override async runCmrWorker(
    _spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<CmrWorkerOutcome> {
    this.cmrCalls.push({
      familyBase: ctx.familyBase!,
      ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
    });
    // #919 R8: live green is kind:judge status:converged.
    // residual kind:verdict/cmr + findingsCount:0 is unusable fail-loud (never silent clean).
    return {
      kind: "judge",
      status: "converged",
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      evidencePaths: ["cmr/review-summary.json"],
    };
  }
  // #336: 止于 PR is now a CONTAINER ship WORKER (gstack-ship) via dispatchWorker →
  // runShipWorker. Override the worker seam (no real
  // container) so the e2e proves the run reaches the ship step + STOPS at the PR,
  // recording the family base it shipped (no real gstack-ship, no image, no push).
  protected override async runShipWorker(
    _spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ReturnType<typeof shipOutcomeFromResult>> {
    this.shipCalls.push(ctx.familyBase!);
    return {
      kind: "shipped",
      branch: ctx.familyBase!,
      status: "pr_opened",
      pr: "pr://family/291-base",
    };
  }
  protected override async runFamilyReviewLoopWorker(
    spec: WorkerSpec,
    _ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }
    return { kind: "failed", reason: `unexpected online review worker ${spec.kind}` };
  }
  override async runPostMergeCleanup() {
    return {
      kind: "cleanup" as const,
      terminal: true,
      ok: true,
      branchOutcome: "already_gone" as const,
    };
  }

  // Keep the dedicated clone for post-run assertions; production reclaim still
  // runs through RealFamilyBackend.reapFamilyHost after terminal cleanup.
  override async reapFamilyHost(_familyBase: string): Promise<void> {}
}

describe("#291 Unit B — e2e family driver on real RealFamilyBackend", () => {
  it("schedules waves, REALLY merges each child onto the local family base, writes the ledger, and STOPS at the PR", async () => {
    const source = track(makeSourceRepo());
    const home = track(mkdtempSync(join(tmpdir(), "e2e-home-")));
    const ledgerDir = track(mkdtempSync(join(tmpdir(), "e2e-ledger-")));
    const sh = makeSh();
    const familyBase = "family/291-base";

    let captured: { backend: E2EFamilyBackend; clone: string } | undefined;

    const result = await runFamilyDriver({
      epicIssue: 291,
      sourceRepo: source,
      // local-only source (no remote) — slug degrades to a path hash.
      repo: "Akagilnc/ming-salvage-sim",
      familyBase,
      base: "main",
      promptsDir: familyPromptsDir,
      familyPromptsDir,
      soulsDir: familySoulsDir,
      ledgerDir,
      imageName: "img",
      home,
      sh,
      singleSliceBackendFactory: (clone) => new RealGitChildBackend(clone),
      familyBackendFactory: (clone, startHead) => {
        const b = new E2EFamilyBackend({
          workingRepo: clone,
          familyBase,
          ledgerDir,
          repo: "Akagilnc/ming-salvage-sim",
          base: "main",
          promptsDir: familyPromptsDir,
          soulsDir: familySoulsDir,
          imageName: "img",
          familyBaseStartHead: startHead,
        });
        captured = { backend: b, clone };
        return b;
      },
    });

    expect(captured).toBeDefined();
    const { backend, clone } = captured!;

    // ── 1. honest success: every child merged, the run is success ──────────────
    expect(result.status).toBe("success");
    expect(result.children.map((c) => c.issue).sort()).toEqual([11, 12, 13]);
    expect(result.children.every((c) => c.status === "merged")).toBe(true);

    // ── 2. REAL merge commits on the LOCAL family base ─────────────────────────
    // The family base HEAD is a real --no-ff merge commit (2 parents), and each
    // child's unique file landed on it.
    const familyHead = git(clone, "rev-parse", familyBase);
    expect(result.familyHead).toBe(familyHead);
    // Check out the family base and confirm all three child files are present.
    git(clone, "checkout", "-q", familyBase);
    for (const n of [11, 12, 13]) {
      expect(existsSync(join(clone, `child-${n}.txt`))).toBe(true);
    }
    // The family base advanced past its start head (real merges landed).
    const startHead = await backend.reconcileGit().familyBaseStartHead();
    expect(familyHead).not.toBe(startHead);
    expect(await backend.reconcileGit().isAncestor(startHead, familyHead)).toBe(true);

    // ── 3. #817: the production mergeChild chain really recorded each merge ────
    // This is deliberately the RealFamilyBackend shape used by the driver, not
    // a fake FamilyBackend that can report synthetic heads without landing Git.
    const ledger = await backend.readFamilyLedger();
    const merged = ledger.filter((e) => e.status === "merged");
    expect(merged.map((e) => e.childIssue).sort()).toEqual([11, 12, 13]);
    for (const entry of merged) {
      expect(entry.childBranch).toBeDefined();
      expect(entry.childHead).toBeDefined();
      expect(entry.familyHeadBefore).toBeDefined();
      expect(entry.familyHeadAfter).toBeDefined();
      expect(git(clone, "show", "-s", "--format=%P", entry.familyHeadAfter!)).toMatch(
        /^\S+\s+\S+$/,
      );
    }
    // It is a real sibling JSONL on disk.
    const raw = readFileSync(join(ledgerDir, "family-ledger.jsonl"), "utf8");
    expect(raw.trim().split("\n").length).toBeGreaterThanOrEqual(3);

    // ── 3b. WAVE ORDER: #13 (blocked_by #12) merged AFTER #12 (topological) ─────
    const order = merged.map((e) => e.childIssue!);
    expect(order.indexOf(12)).toBeLessThan(order.indexOf(13));

    // ── 4. the run STOPPED at the PR (ship worker dispatched once, family base) ─
    // verify ran at BOTH barriers (each wave + final), CMR ran as two final passes, the
    // ship WORKER ran once with the family base (#336: gstack-ship, not the inline
    // inline host PR path — and nothing merged to main.
    expect(backend.verifyCalls.length).toBeGreaterThanOrEqual(1);
    expect(backend.verifyCalls.some((v) => v.phase === "final")).toBe(true);
    expect(backend.cmrCalls).toEqual([
      { familyBase, cmrPass: "completeness" },
      { familyBase, cmrPass: "correctness" },
    ]);
    expect(backend.shipCalls).toEqual([familyBase]);
    // The legacy inline push path is DEAD — the ship worker replaced it (#336).
  });
});

/**
 * #939 / #934 ID-011 — public ignition/driver seam proves operational package
 * manifest errors fail closed, while a successful empty verifiable-command set
 * is a legal skip. Production runVerifyCommands/packageScripts run for real;
 * only cmr/ship stay controlled (no container).
 */
class ProductionVerifyE2EFamilyBackend extends RealFamilyBackend {
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

  readonly shipCalls: string[] = [];
  protected override async installDeps(): Promise<void> {
    // Legal empty skips before install; operational errors fail before install.
    // Green script paths are not exercised by the #939 driver cases below.
    throw new Error("installDeps must not run in #939 driver empty/error cases");
  }
  protected override async runCmrWorker(
    _spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<CmrWorkerOutcome> {
    return {
      kind: "judge",
      status: "converged",
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      evidencePaths: ["cmr/review-summary.json"],
    };
  }
  protected override async runShipWorker(
    _spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ReturnType<typeof shipOutcomeFromResult>> {
    this.shipCalls.push(ctx.familyBase!);
    return {
      kind: "shipped",
      branch: ctx.familyBase!,
      status: "pr_opened",
      pr: "pr://family/939-base",
    };
  }
  protected override async runFamilyReviewLoopWorker(
    spec: WorkerSpec,
    _ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return { kind: "failed", reason: `unexpected online review worker ${spec.kind}` };
  }
  override async runPostMergeCleanup() {
    return {
      kind: "cleanup" as const,
      terminal: true,
      ok: true,
      branchOutcome: "already_gone" as const,
    };
  }
  override async reapFamilyHost(_familyBase: string): Promise<void> {}
}

describe("#939 family verify operational error vs legal empty (public driver)", () => {
  it("malformed package.json at verifyCwd → status verify_failed (not empty-command success)", async () => {
    const source = track(makeSourceRepo());
    const home = track(mkdtempSync(join(tmpdir(), "e2e-939-err-home-")));
    const ledgerDir = track(mkdtempSync(join(tmpdir(), "e2e-939-err-ledger-")));
    const verifyCwd = track(mkdtempSync(join(tmpdir(), "e2e-939-err-proj-")));
    writeFileSync(join(verifyCwd, "package.json"), "{not-valid-json");
    const familyBase = "family/939-err-base";
    const sh = makeSh();

    const result = await runFamilyDriver({
      epicIssue: 939,
      sourceRepo: source,
      repo: "Akagilnc/ming-salvage-sim",
      familyBase,
      base: "main",
      promptsDir: familyPromptsDir,
      familyPromptsDir,
      soulsDir: familySoulsDir,
      ledgerDir,
      imageName: "img",
      home,
      sh,
      verifyCwd,
      singleSliceBackendFactory: (clone) => new RealGitChildBackend(clone),
      familyBackendFactory: (clone, startHead) =>
        new ProductionVerifyE2EFamilyBackend({
          workingRepo: clone,
          familyBase,
          ledgerDir,
          repo: "Akagilnc/ming-salvage-sim",
          base: "main",
          promptsDir: familyPromptsDir,
          soulsDir: familySoulsDir,
          imageName: "img",
          familyBaseStartHead: startHead,
          verifyCwd,
        }),
    });

    expect(result.status).toBe("verify_failed");
    // Fail closed on parse, not installDeps pseudo-red (#934 ID-011).
    expect(result.stopSummary?.summary ?? result.stopSummary?.reason ?? "").toMatch(
      /parse package\.json|failed to parse/i,
    );
  });

  it("invalid scripts shape at verifyCwd → status verify_failed (not legal empty skip)", async () => {
    const source = track(makeSourceRepo());
    const home = track(mkdtempSync(join(tmpdir(), "e2e-939-shape-home-")));
    const ledgerDir = track(mkdtempSync(join(tmpdir(), "e2e-939-shape-ledger-")));
    const verifyCwd = track(mkdtempSync(join(tmpdir(), "e2e-939-shape-proj-")));
    writeFileSync(
      join(verifyCwd, "package.json"),
      JSON.stringify({ name: "bad-scripts", version: "0.0.0", scripts: 42 }),
    );
    const familyBase = "family/939-shape-base";
    const result = await runFamilyDriver({
      epicIssue: 939,
      sourceRepo: source,
      repo: "Akagilnc/ming-salvage-sim",
      familyBase,
      base: "main",
      promptsDir: familyPromptsDir,
      familyPromptsDir,
      soulsDir: familySoulsDir,
      ledgerDir,
      imageName: "img",
      home,
      sh: makeSh(),
      verifyCwd,
      singleSliceBackendFactory: (clone) => new RealGitChildBackend(clone),
      familyBackendFactory: (clone, startHead) =>
        new ProductionVerifyE2EFamilyBackend({
          workingRepo: clone,
          familyBase,
          ledgerDir,
          repo: "Akagilnc/ming-salvage-sim",
          base: "main",
          promptsDir: familyPromptsDir,
          soulsDir: familySoulsDir,
          imageName: "img",
          familyBaseStartHead: startHead,
          verifyCwd,
        }),
    });
    expect(result.status).toBe("verify_failed");
    expect(result.stopSummary?.summary ?? result.stopSummary?.reason ?? "").toMatch(
      /scripts.*must be an object/i,
    );
  });

  it("successful empty verifiable scripts → legal skip; driver can complete", async () => {
    const source = track(makeSourceRepo());
    const home = track(mkdtempSync(join(tmpdir(), "e2e-939-empty-home-")));
    const ledgerDir = track(mkdtempSync(join(tmpdir(), "e2e-939-empty-ledger-")));
    const verifyCwd = track(mkdtempSync(join(tmpdir(), "e2e-939-empty-proj-")));
    writeFileSync(
      join(verifyCwd, "package.json"),
      JSON.stringify({
        name: "legal-empty",
        version: "0.0.0",
        scripts: { dev: "echo hi" },
      }),
    );
    const familyBase = "family/939-empty-base";
    const sh = makeSh();
    let backend: ProductionVerifyE2EFamilyBackend | undefined;

    const result = await runFamilyDriver({
      epicIssue: 939,
      sourceRepo: source,
      repo: "Akagilnc/ming-salvage-sim",
      familyBase,
      base: "main",
      promptsDir: familyPromptsDir,
      familyPromptsDir,
      soulsDir: familySoulsDir,
      ledgerDir,
      imageName: "img",
      home,
      sh,
      verifyCwd,
      singleSliceBackendFactory: (clone) => new RealGitChildBackend(clone),
      familyBackendFactory: (clone, startHead) => {
        backend = new ProductionVerifyE2EFamilyBackend({
          workingRepo: clone,
          familyBase,
          ledgerDir,
          repo: "Akagilnc/ming-salvage-sim",
          base: "main",
          promptsDir: familyPromptsDir,
          soulsDir: familySoulsDir,
          imageName: "img",
          familyBaseStartHead: startHead,
          verifyCwd,
        });
        return backend;
      },
    });

    // Legal empty command set after successful read: verify does not fail, and
    // the rest of the production final barrier can complete (#934 ID-011).
    expect(result.status).toBe("success");
    expect(backend?.shipCalls).toEqual([familyBase]);
  });
});
