import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { legacyDispatchWorker } from "../../src/dispatchWorker.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { findingIdentityKey } from "../../src/findings.js";
import { route } from "../../src/route.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

type PersistentLedgerFixture = Omit<
  PersistentLedgerEntry,
  "sessionId" | "prompt_hash" | "branchHEAD" | "ts"
> & Partial<Pick<PersistentLedgerEntry, "sessionId" | "prompt_hash" | "branchHEAD" | "ts">>;

type ResumeStateFixture = Omit<ResumeState, "ledger"> & {
  readonly ledger: ReadonlyArray<PersistentLedgerFixture>;
};

function materializeResumeState(fixture: ResumeStateFixture): ResumeState {
  return {
    ...fixture,
    ledger: fixture.ledger.map((entry) => ({
      ...entry,
      sessionId: entry.sessionId ?? "fixture-session",
      prompt_hash: entry.prompt_hash ?? "fixture-prompt",
      branchHEAD: entry.branchHEAD ?? "fixture-head",
      ts: entry.ts ?? "2026-07-01T00:00:00.000Z",
    })),
  };
}

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-369",
  base: "main",
  path: "/resident/worktrees/issue-369",
};

function makeGitWorktree(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "runner-progress-"));
  execFileSync("git", ["init", "-b", "main"], {
    cwd: path,
    stdio: "ignore",
  });
  writeFileSync(join(path, "README.md"), "base\n", "utf8");
  execFileSync("git", ["add", "."], { cwd: path, stdio: "ignore" });
  execFileSync(
    "git",
    [
      "-c",
      "user.name=Test",
      "-c",
      "user.email=test@example.com",
      "commit",
      "-m",
      "base",
    ],
    { cwd: path, stdio: "ignore" },
  );
  execFileSync("git", ["checkout", "-b", WORKTREE.branch], {
    cwd: path,
    stdio: "ignore",
  });
  return { ...WORKTREE, path };
}

class RetryReviewBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: (WorkerLandingPayload | undefined)[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  reviewerAttempts = 0;
  coderAttempts = 0;

  constructor(
    private readonly reviewerResults: ReadonlyArray<WorkerResult>,
    private readonly resumeState?: ResumeStateFixture,
    private readonly coderOutputs: ReadonlyArray<StepOutput> = [],
    private readonly worktree: WorktreeHandle = WORKTREE,
    private readonly onCoderDispatch?: (
      attempt: number,
      worktree: WorktreeHandle,
    ) => void,
  ) {}

  async findResumeState(): Promise<ResumeState | undefined> {
    return this.resumeState && materializeResumeState(this.resumeState);
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
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
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "body", comments: [], agentBrief: "" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return this.worktree;
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if ((spec.role === "reviewer" || spec.role === "verify")) return { kind: "judge", status: "converged" };
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async writeLedger(entry: PersistentLedgerEntry, _stateDir: string): Promise<void> {
    this.ledgerWrites.push(entry);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
    this.landings.push(landing);
    if (spec.kind === "coder" && spec.id === "S5") {
      const attempt = this.coderAttempts;
      const scripted = this.coderOutputs[this.coderAttempts];
      this.coderAttempts += 1;
      this.onCoderDispatch?.(attempt, this.worktree);
      if (scripted !== undefined) {
        return { kind: "completed", output: scripted };
      }
    }
    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if ((spec.kind === "reviewer" || spec.kind === "verify")) {
      const result = this.reviewerResults[this.reviewerAttempts];
      this.reviewerAttempts += 1;
      return result ?? { kind: "completed", output: { kind: "judge", status: "converged" } };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) {
      return skeleton;
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: this.worktree.branch, status: "pushed" },
    };
  }
}

describe("#369 per-slice runner-visible review/fix loop", () => {
  it("passes structured blocking findings and identity keys to the S5 fix worker", async () => {
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "Fix worker needs structured finding data",
      location: "src/runner.ts:1",
      suggested_fix: "pass findings through DispatchContext",
      action: "fix_now",
    };
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [finding], findingsCount: 1 } },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
    expect(s5Index).toBeGreaterThanOrEqual(0);
    expect(backend.landings[s5Index]?.blockingFindings).toEqual([finding]);
    // #925: live identity keys from the judge disposition table are the S5
    // control envelope (schema-fixed fields — not prose parsing).
    expect(backend.ctxs[s5Index]?.blockingFindingIdentityKeys ?? []).toEqual([
      "correctness|src/runner.ts:1|fix worker needs structured finding data",
    ]);
  });

  // #604 slice 4 (ADR 0062): there is no cross-module deferral pass, so every
  // non-accepted-suppressed finding rides the fix loop.
  it("keeps non-accepted-suppressed follow-up findings blocking across fix rounds", async () => {
    const blocking: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "must fix before shipping",
      location: "src/runner.ts:10",
      suggested_fix: "fix it",
      action: "fix_now",
    };
    const followUpFinding: Finding = {
      severity: "medium",
      category: "Follow-up",
      claim_quote: "track this later",
      location: "src/runner.ts:11",
      suggested_fix: "file follow-up",
      action: "fix_now",
    };
    const backend = new RetryReviewBackend([
      {
        kind: "completed",
        output: { kind: "reviewer", findings: [blocking, followUpFinding], findingsCount: 2 },
      },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
  });

});

describe("#427 ADR0030 claimed-fixed adjudication", () => {
  const blocking: Finding = {
    severity: "high",
    category: "Correctness",
    claim_quote: "absence is not closure",
    location: "src/runner.ts:427",
    suggested_fix: "require explicit disposition",
    action: "fix_now",
  };
  const blockingKey = "correctness|src/runner.ts:427|absence is not closure";

  it("routes S3/S6 from judge status; residual open-count 0 is unusable not clean", () => {
    // #919 CR P1 / #925: residual findingsCount=0 is unusable → S5 (never S7).
    // Disposition prose is ignored either way; only explicit judge converged cleans.
    expect(
      route({
        from: "S3",
        output: {
          kind: "reviewer",
          findings: [],
          findingsCount: 0,
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      }),
    ).toEqual({ kind: "next", step: "S5" });
    expect(
      route({
        from: "S6",
        output: { kind: "judge", status: "converged" },
      }),
    ).toEqual({ kind: "next", step: "S7" });
  });

  it("routes a completed S5 no-commit report to fresh re-review", () => {
    expect(
      route({
        from: "S5",
        output: { kind: "coder", committed: false, commitsAdded: 0 },
      }),
    ).toEqual({ kind: "next", step: "S6" });
  });

  it("#877: S6 empty findings without disposition ships (disposition court demolished)", async () => {
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
      { kind: "completed", output: { kind: "judge", status: "converged" } },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(result.errorPackage?.reason ?? "").not.toMatch(
      /omitted required disposition/i,
    );
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("ships only after the fresh re-review explicitly verifies a claimed-fixed finding closed", async () => {
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",

    ]);
  });

  it("passes prior claimed-fixed findings and identity keys to the S6 fresh reviewer", async () => {
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 428, backend });

    expect(result.status).toBe("success");
    const s6Index = backend.specs.findIndex((spec) => spec.id === "S6");
    expect(s6Index).toBeGreaterThanOrEqual(0);
    expect(backend.landings[s6Index]?.blockingFindings).toEqual([blocking]);
    // #925: live keys from the continue disposition table are control envelope.
    expect(backend.ctxs[s6Index]?.blockingFindingIdentityKeys ?? []).toEqual([
      blockingKey,
    ]);
  });

  it("threads judge finding dispositions through live re-review and persists them", async () => {
    const acceptedRisk: Finding = {
      severity: "medium",
      category: "Correctness",
      claim_quote: "accepted risk remains same severity",
      location: "src/runner.ts:736",
      suggested_fix: "do not reopen without a material severity upgrade",
      action: "wont_fix",
      disposition_reason: "Accepted as out of scope for this slice",
      disposition: {
        kind: "accepted_suppressed",
        source: "issue #428 acceptance criteria",
        scope: "out-of-scope accepted risk",
        reason: "Accepted as out of scope for this slice",
        findingIdentity:
          "correctness|src/runner.ts:736|accepted risk remains same severity",
        boundedReopen: "reopen on material severity upgrade",
      },
    };
    const acceptedRiskKey =
      "correctness|src/runner.ts:736|accepted risk remains same severity";
    const backend = new RetryReviewBackend([
      {
        kind: "completed",
        output: { kind: "reviewer", findings: [blocking, acceptedRisk], findingsCount: 2 },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          // #604 correctness r1 (P2-a): a REOPENED finding is a plain blocking
          // `fix_now` — it must NOT carry the accepted_suppressed disposition
          // (that is only valid on wont_fix/rejected). Strip the disposition when
          // reopening so the reviewer output stays contract-valid.
          findings: [
            {
              severity: acceptedRisk.severity,
              category: acceptedRisk.category,
              claim_quote: acceptedRisk.claim_quote,
              location: acceptedRisk.location,
              suggested_fix: acceptedRisk.suggested_fix,
              action: "fix_now",
            },
          ],
          findingsCount: 1,
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "verified-closed" },
            {
              identityKey: acceptedRiskKey,
              status: "still-active",
              reason: "reviewer-only suppression must be repaired",
            },
          ],
        },
      },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 428, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",

    ]);
    // #925: dispositions land on S3/S6 judge rows (S4 dissolved).
    const firstJudgeWrite = backend.ledgerWrites.find(
      (entry) => entry.step === "S3" || entry.step === "S6",
    );
    expect(firstJudgeWrite).toBeDefined();
  });

  it("#877: repeated still-active disposition prose no longer no-progress-kills; findings-count continues", async () => {
    // Pre-#877: two still-active rounds without progress → escalate at S4.
    // Post-#877: no-progress court demolished; loop follows findings count until
    // the scripted backend falls through to empty findings and ships.
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [blocking], findingsCount: 1,
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [blocking], findingsCount: 1,
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(result.errorPackage?.reason ?? "").not.toMatch(/no progress/i);
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("keeps routing by fresh reviewer declarations across repeated coder receipts", async () => {
    const coderReceipt = {
      kind: "coder" as const,
      committed: true,
      commitsAdded: 1,
    };
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
        { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        {
          kind: "completed",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      undefined,
      [coderReceipt, coderReceipt, coderReceipt],
      worktree,
      (attempt, wt) => {
        const srcDir = join(wt.path, "src");
        mkdirSync(srcDir, { recursive: true });
        writeFileSync(
          join(srcDir, "runner.ts"),
          `export const attempt = ${attempt};\n`,
          "utf8",
        );
        execFileSync("git", ["add", "src/runner.ts"], {
          cwd: wt.path,
          stdio: "ignore",
        });
        execFileSync(
          "git",
          [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            `fix attempt ${attempt}`,
          ],
          { cwd: wt.path, stdio: "ignore" },
        );
      },
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",

    ]);
  });

  it("continues to fresh review when the best-effort HEAD read fails after S5", async () => {
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
        { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        { kind: "completed", output: { kind: "judge", status: "converged" } },
      ],
      undefined,
      [{ kind: "coder", committed: true, commitsAdded: 1 }],
      worktree,
      (_attempt, wt) => {
        renameSync(join(wt.path, ".git"), join(wt.path, ".git-unavailable"));
      },
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("does not derive progress from coder receipt details", async () => {
    const coderReceipt = {
      kind: "coder" as const,
      committed: true,
      commitsAdded: 1,
    };
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
        { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        {
          kind: "completed",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      undefined,
      [coderReceipt, coderReceipt, coderReceipt],
      worktree,
      (attempt, wt) => {
        const testDir = join(wt.path, "test");
        mkdirSync(testDir, { recursive: true });
        writeFileSync(
          join(testDir, "per-slice-cmr-369.test.ts"),
          `export const attempt = ${attempt};\n`,
          "utf8",
        );
        execFileSync("git", ["add", "test/per-slice-cmr-369.test.ts"], {
          cwd: wt.path,
          stdio: "ignore",
        });
        execFileSync(
          "git",
          [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            `test evidence ${attempt}`,
          ],
          { cwd: wt.path, stdio: "ignore" },
        );
      },
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",

    ]);
  });

  it("does not derive changed paths from coder receipt cargo", async () => {
    const coderReceipt = {
      kind: "coder" as const,
      committed: true,
      commitsAdded: 1,
    };
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
        { kind: "completed", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        {
          kind: "completed",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      undefined,
      [coderReceipt, coderReceipt, coderReceipt],
      worktree,
      (attempt, wt) => {
        const srcDir = join(wt.path, "src");
        mkdirSync(srcDir, { recursive: true });
        writeFileSync(
          join(srcDir, "runner.ts"),
          `export const attempt = ${attempt};\n`,
          "utf8",
        );
        execFileSync("git", ["add", "src/runner.ts"], {
          cwd: wt.path,
          stdio: "ignore",
        });
        execFileSync(
          "git",
          [
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            `source movement ${attempt}`,
          ],
          { cwd: wt.path, stdio: "ignore" },
        );
      },
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",

    ]);
  });

  it("#877: empty S6 still-active disposition on resume closes via findings-count (no reopen court)", async () => {
    // Pre-#877: still-active disposition reopened priors → S5 fix loop.
    // Post-#877: findings=[] closes; resume after S5 ships without reopening.
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-427",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: { kind: "judge", status: "converged" },
        },
        { step: "S4" },
        {
          step: "S5",
          output: {
            kind: "coder",
            committed: true,
            commitsAdded: 1,
          },
        },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual(["S6:verify"]);
  });

  it.each([
    {
      name: "severity decreases",
      initial: [{ ...blocking, severity: "high" as const }],
      firstAfterFix: [{ ...blocking, severity: "medium" as const }],
      firstDispositions: [
        { identityKey: blockingKey, status: "still-active" as const },
      ],
      secondAfterFix: [{ ...blocking, severity: "medium" as const }],
      secondDispositions: [
        { identityKey: blockingKey, status: "still-active" as const },
      ],
      finalDispositions: [
        { identityKey: blockingKey, status: "verified-closed" as const },
      ],
    },
  ])("counts reviewer-observed progress when $name", async (sample) => {
    const backend = new RetryReviewBackend([
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: sample.initial,
          findingsCount: sample.initial.length,
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: sample.firstAfterFix,
          findingsCount: sample.firstAfterFix.length,
          priorFindingDispositions: sample.firstDispositions,
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: sample.secondAfterFix,
          findingsCount: sample.secondAfterFix.length,
          priorFindingDispositions: sample.secondDispositions,
        },
      },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(result.errorPackage).toBeUndefined();
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",

    ]);
  });

  it("does not count reviewer claim narrowing as implementation progress", async () => {
    const originalFinding = {
      ...blocking,
      claim_quote: "module parser leaves inline yaml accepted in invalid declarations",
    };
    const firstNarrowedFinding = {
      ...blocking,
      claim_quote: "inline yaml accepted",
    };
    const secondNarrowedFinding = {
      ...blocking,
      claim_quote: "yaml accepted",
    };
    const originalKey = findingIdentityKey(originalFinding);
    const firstNarrowedKey = findingIdentityKey(firstNarrowedFinding);

    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [originalFinding], findingsCount: 1 } },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [firstNarrowedFinding], findingsCount: 1,
          priorFindingDispositions: [
            { identityKey: originalKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [secondNarrowedFinding], findingsCount: 1,
          priorFindingDispositions: [
            { identityKey: originalKey, status: "still-active" },
            { identityKey: firstNarrowedKey, status: "still-active" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    // #877: no-progress court demolished; findings-count continues until empty fallback ships.
    expect(result.status).toBe("success");
    expect(result.stopSummary.reason).not.toBe("same_module_still_red");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("does not count omitted still-active prior findings as blocking-count progress", async () => {
    const primaryFinding = {
      ...blocking,
      claim_quote: "primary blocker stays active through dispositions",
    };
    const secondaryFinding = {
      ...blocking,
      claim_quote: "secondary blocker remains in reviewer findings",
      location: "src/secondary.ts:1",
    };
    const primaryKey = findingIdentityKey(primaryFinding);
    const secondaryKey = findingIdentityKey(secondaryFinding);

    const backend = new RetryReviewBackend([
      {
        kind: "completed",
        output: { kind: "reviewer", findings: [primaryFinding, secondaryFinding], findingsCount: 2 },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [{ ...secondaryFinding, severity: "medium" }], findingsCount: 1,
          priorFindingDispositions: [
            { identityKey: primaryKey, status: "still-active" },
            { identityKey: secondaryKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer", findings: [{ ...secondaryFinding, severity: "low" }], findingsCount: 1,
          priorFindingDispositions: [
            { identityKey: primaryKey, status: "still-active" },
            { identityKey: secondaryKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: { kind: "judge", status: "converged" },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    // #877: omitted still-active disposition prose does not reopen or no-progress-kill.
    // Secondary re-emitted findings keep the fix loop via findings-count until empty.
    expect(result.status).toBe("success");
    expect(result.stopSummary.reason).not.toBe("same_module_still_red");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",
    ]);
  });

  it("continues fixing after a scoped continue-fixing bookkeeping event resets no-progress state", async () => {
    const continueFixingEvent = {
      step: "S4",
      event: "runner_bookkeeping",
      intent: "continue_fixing",
      findingIdentityKey: blockingKey,
      findingScope: { identityKeys: [blockingKey] },
      source: "resume_input",
      ts: "2026-07-01T00:00:00.000Z",
      reason: "human explicitly instructed the runner to keep fixing this active finding",
    } satisfies PersistentLedgerFixture;
    expect(continueFixingEvent).not.toHaveProperty("output");
    expect(continueFixingEvent).not.toHaveProperty("verdict");

    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
        continueFixingEvent,
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",

    ]);
  });

  it("uses current run continue-fixing input even when no durable continue event exists", async () => {
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({
      issueNumber: 446,
      backend,
      repairIntent: {
        event: "runner_bookkeeping",
        intent: "continue_fixing",
        findingIdentityKey: blockingKey,
        source: "resume_input",
        ts: "2026-07-01T00:00:01.000Z",
      },
    });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S5:coder",
      "S6:verify",

    ]);
  });

  it("does not treat source-less continue-fixing bookkeeping as an executable human resume", async () => {
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
        {
          step: "S4",
          event: "runner_bookkeeping",
          intent: "continue_fixing",
          findingIdentityKey: blockingKey,
          findingScope: { identityKeys: [blockingKey] },
          ts: "2026-07-01T00:00:02.000Z",
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatched).toEqual([]);
  });

  it("does not reopen an S4 decision escalation for stale or scope-mismatched continue-fixing bookkeeping", async () => {
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
        {
          step: "S4",
          event: "runner_bookkeeping",
          intent: "continue_fixing",
          findingIdentityKey: blockingKey,
          findingScope: { identityKeys: [blockingKey] },
          source: "coordinator",
          ts: "2026-07-01T00:00:02.000Z",
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatched).toEqual([]);
  });

  it("ignores malformed finding scopes on resume bookkeeping without throwing", async () => {
    const baseLedger = [
      { step: "S0" },
      { step: "S1" },
      { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
      { step: "S4" },
      { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      {
        step: "S6",
        output: {
          kind: "reviewer", findings: [blocking], findingsCount: 1,
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
      { step: "S4" },
      { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      {
        step: "S6",
        output: {
          kind: "reviewer", findings: [blocking], findingsCount: 1,
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
      { step: "S4" },
      { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
    ] as const;
    const malformedEvents: PersistentLedgerFixture[] = [
      {
        step: "S4",
        event: "runner_bookkeeping",
        intent: "continue_fixing",
        // Deliberately omit the required scope key for the parser boundary.
        findingScope: {},
        source: "resume_input",
        ts: "2026-07-01T00:00:03.000Z",
      },
    ];

    for (const event of malformedEvents) {
      const backend = new RetryReviewBackend([], {
        worktree: WORKTREE,
        stateDir: "/resident/worktrees/.ledger-446",
        ledger: [...baseLedger, event],
      });

      const result = await runOrchestrator({ issueNumber: 446, backend });

      expect(result.status).toBe("escalate");
      expect(backend.dispatched).toEqual([]);
    }
  });

  it("does not map unscoped escalation answers to continue-fixing repair intent", async () => {
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [blocking], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
        {
          step: "S4",
          event: "escalation_answered",
          forStep: "S4",
          answer: "继续修",
          source: "human",
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatched).toEqual([]);
  });

  it("preserves a persisted terminal error stop summary on already-done re-feed", async () => {
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446-error",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: false, commitsAdded: 0 } },
        {
          step: "S8",
          handoffStatus: "error",
          stopSummary: {
            reason: "contract_drift",
            summary: "persisted malformed coder output",
            repairHint: "repair the coder contract and rerun",
          },
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("error");
    expect(result.stopSummary).toMatchObject({
      reason: "contract_drift",
      summary: "persisted malformed coder output",
    });
    expect(backend.dispatched).toEqual([]);
  });

  it("maps scoped human or resume-input escalation answers to the matching active S4 finding only", async () => {
    for (const source of ["human", "resume_input"] as const) {
      const resumeState: ResumeStateFixture = {
        worktree: WORKTREE,
        stateDir: `/resident/worktrees/.ledger-446-${source}`,
        ledger: [
          { step: "S0" },
          { step: "S1" },
          { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
          { step: "S4" },
          { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          {
            step: "S6",
            output: {
              kind: "reviewer", findings: [blocking], findingsCount: 1,
              priorFindingDispositions: [
                { identityKey: blockingKey, status: "still-active" },
              ],
            },
          },
          { step: "S4" },
          { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          {
            step: "S6",
            output: {
              kind: "reviewer", findings: [blocking], findingsCount: 1,
              priorFindingDispositions: [
                { identityKey: blockingKey, status: "still-active" },
              ],
            },
          },
          { step: "S4" },
          { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
          {
            step: "S4",
            event: "escalation_answered",
            forStep: "S4",
            answer: "继续修",
            source,
            findingScope: { identityKeys: [blockingKey] },
          },
        ],
      };
      const backend = new RetryReviewBackend(
        [
          {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
          },
        ],
        resumeState,
      );

      const result = await runOrchestrator({ issueNumber: 446, backend });

      expect(result.status).toBe("success");
      expect(backend.dispatched).toEqual(["S5:coder", "S6:verify"]);
    }
  });

  it("does not treat scoped coordinator or peripheral escalation answers as executable continue-fixing input", async () => {
    for (const source of ["coordinator", "peripheral"] as const) {
      const resumeState: ResumeStateFixture = {
        worktree: WORKTREE,
        stateDir: `/resident/worktrees/.ledger-446-${source}`,
        ledger: [
          { step: "S0" },
          { step: "S1" },
          { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          { step: "S3", output: { kind: "reviewer", findings: [blocking], findingsCount: 1 } },
          { step: "S4" },
          { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          {
            step: "S6",
            output: {
              kind: "reviewer", findings: [blocking], findingsCount: 1,
              priorFindingDispositions: [
                { identityKey: blockingKey, status: "still-active" },
              ],
            },
          },
          { step: "S4" },
          { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
          {
            step: "S4",
            event: "escalation_answered",
            forStep: "S4",
            answer: "继续修",
            source,
            findingScope: { identityKeys: [blockingKey] },
          },
        ],
      };
      const backend = new RetryReviewBackend([], resumeState);

      const result = await runOrchestrator({ issueNumber: 446, backend });

      expect(result.status).toBe("escalate");
      expect(backend.dispatched).toEqual([]);
    }
  });

  it("transports broad file scope without cargo matching; multi-sibling stay on full findings cargo", async () => {
    // #899 / ADR 0131: runner does not match location scope against findings
    // cargo or refuse multi-sibling broad scopes. Explicit human continue-
    // fixing + non-empty findingScope resumes S5; the fixer owns scope taste.
    const runnerFinding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "locations.has(normaliseScopePart(finding.location))",
      location: "orchestrator/src/runner.ts:380",
      suggested_fix: "match file scope against path:line findings",
      action: "fix_now",
    };
    const runnerFindingKey =
      "correctness|orchestrator/src/runner.ts:380|locations.has(normalisescopepart(finding.location))";
    const siblingFinding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "matchingIdentityKeys: replay.blockingIdentityKeys",
      location: "orchestrator/src/runner.ts:421",
      suggested_fix: "require scoped answers",
      action: "fix_now",
    };
    const siblingFindingKey =
      "correctness|orchestrator/src/runner.ts:421|matchingidentitykeys: replay.blockingidentitykeys";

    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        {
          step: "S2",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S3",
          output: { kind: "reviewer", findings: [runnerFinding, siblingFinding], findingsCount: 1 },
        },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [runnerFinding, siblingFinding], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: runnerFindingKey, status: "still-active" },
              { identityKey: siblingFindingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [runnerFinding, siblingFinding], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: runnerFindingKey, status: "still-active" },
              { identityKey: siblingFindingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
        {
          step: "S4",
          event: "runner_bookkeeping",
          intent: "continue_fixing",
          findingScope: { locations: ["orchestrator/src/runner.ts"] },
          source: "resume_input",
          ts: "2026-07-01T00:00:03.000Z",
        },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual(["S5:coder", "S6:verify"]);
  });

  it("matches broad file scope against path-line-symbol findings", async () => {
    const fileScopedFinding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "stripLocationLine(value)",
      location: "orchestrator/src/runner.ts:410:runPass",
      suggested_fix: "match file scope against path:line:symbol findings",
      action: "fix_now",
    };
    const fileScopedFindingKey = findingIdentityKey(fileScopedFinding);
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        {
          step: "S2",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        { step: "S3", output: { kind: "reviewer", findings: [fileScopedFinding], findingsCount: 1 } },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [fileScopedFinding], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: fileScopedFindingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [fileScopedFinding], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: fileScopedFindingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
        {
          step: "S4",
          event: "runner_bookkeeping",
          intent: "continue_fixing",
          findingScope: { locations: ["orchestrator/src/runner.ts"] },
          source: "resume_input",
          ts: "2026-07-01T00:00:04.000Z",
        },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual(["S5:coder", "S6:verify"]);
  });

  it("uses broad file scope when it maps to one active finding lineage", async () => {
    const fileScopedFinding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "locations.has(normaliseScopePart(finding.location))",
      location: "orchestrator/src/runner.ts:380",
      suggested_fix: "match file scope against path:line findings",
      action: "fix_now",
    };
    const fileScopedFindingKey =
      "correctness|orchestrator/src/runner.ts:380|locations.has(normalisescopepart(finding.location))";
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        {
          step: "S2",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        { step: "S3", output: { kind: "reviewer", findings: [fileScopedFinding], findingsCount: 1 } },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [fileScopedFinding], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: fileScopedFindingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [fileScopedFinding], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: fileScopedFindingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
        {
          step: "S4",
          event: "runner_bookkeeping",
          intent: "continue_fixing",
          findingScope: { locations: ["orchestrator/src/runner.ts"] },
          source: "resume_input",
          ts: "2026-07-01T00:00:04.000Z",
        },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual(["S5:coder", "S6:verify"]);
  });

  it("matches nested directory scope segments to active finding locations", async () => {
    const fileScopedFinding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "locations.has(normaliseScopePart(finding.location))",
      location: "orchestrator/src/runner.ts:380",
      suggested_fix: "match nested directory scope against path:line findings",
      action: "fix_now",
    };
    const fileScopedFindingKey =
      "correctness|orchestrator/src/runner.ts:380|locations.has(normalisescopepart(finding.location))";
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        {
          step: "S2",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        { step: "S3", output: { kind: "reviewer", findings: [fileScopedFinding], findingsCount: 1 } },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [fileScopedFinding], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: fileScopedFindingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer", findings: [fileScopedFinding], findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: fileScopedFindingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
        {
          step: "S4",
          event: "runner_bookkeeping",
          intent: "continue_fixing",
          findingScope: { locations: ["src"] },
          source: "resume_input",
          ts: "2026-07-01T00:00:04.000Z",
        },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual(["S5:coder", "S6:verify"]);
  });
});

describe("#369 runner resume/retry review fixes", () => {
  it("rebuilds S4 classification state when resuming directly into S5", async () => {
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "S5 needs the persisted blocker after resume",
      location: "src/runner.ts:1116",
      suggested_fix: "reclassify the last reviewer output before S5",
      action: "fix_now",
    };
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding], findingsCount: 1 } },
        { step: "S4" },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
    expect(s5Index).toBeGreaterThanOrEqual(0);
    expect(backend.landings[s5Index]?.blockingFindings).toEqual([finding]);
    // #899: resume still pass-through findings cargo; keys land at the writer.
    expect(backend.ctxs[s5Index]?.blockingFindingIdentityKeys ?? []).toEqual([]);
  });

  it("rebuilds S5 findings from the last reviewer when resuming an escalated S5", async () => {
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "S5 fallback still needs the blocker",
      location: "src/runner.ts:902",
      suggested_fix: "reclassify the prior reviewer entry",
      action: "fix_now",
    };
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding], findingsCount: 1 } },
        { step: "S4" },
        {
          step: "S5",
          sessionId: "session-escalated-S5",
          output: {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: {
              reason: "needs answer",
              diagnosis: "human answered; resume or fresh fallback may run",
            },
          },
        },
        { step: "S8", handoffStatus: "escalate" },
        {
          step: "S5",
          event: "escalation_answered",
          forStep: "S5",
          answer: "continue after human answer",
          source: "human",
        },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
    expect(s5Index).toBeGreaterThanOrEqual(0);
    expect(backend.specs[s5Index]?.session).toBe("resume");
    expect(backend.landings[s5Index]?.blockingFindings).toEqual([finding]);
    // Resume rebuild may leave identity keys empty when replaying pre-#925
    // ledger rows (keys derived at landing writer); cargo must still land.
    expect(backend.landings[s5Index]?.blockingFindings?.length).toBe(1);
  });

  it("#877/#925: resume after empty S6 (findingsCount=0) ships without re-dispatch", async () => {
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "resumed S6 still needs disposition",
      location: "src/runner.ts:950",
      suggested_fix: "remember that the last reviewer step was S6",
      action: "fix_now",
    };
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding], findingsCount: 1 } },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        // #925: empty open-count / converged projects to S7 without S4.
        { step: "S6", output: { kind: "judge", status: "converged" } },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(result.errorPackage?.reason ?? "").not.toMatch(
      /omitted required disposition/i,
    );
    expect(backend.dispatched).toEqual([]);
  });

  it("#877/#925: resume after converged S6 with still-active prose ships (no reopen)", async () => {
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "persisted S4 still has the prior blocker",
      location: "src/runner.ts:960",
      suggested_fix: "route the adjudicated still-open finding to S5",
      action: "fix_now",
    };
    const key = "correctness|src/runner.ts:960|persisted s4 still has the prior blocker";
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding], findingsCount: 1 } },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          // #925: clean resume requires explicit judge converged (residual
          // findingsCount=0 is unusable, not silent clean).
          output: { kind: "judge", status: "converged" },
        },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([]);
  });

  it("replays persisted S4 finding dispositions on resume", async () => {
    const blocking: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "fix this first",
      location: "src/runner.ts:970",
      suggested_fix: "fix it",
      action: "fix_now",
    };
    const blockingKey = "correctness|src/runner.ts:970|fix this first";
    const acceptedRiskKey =
      "correctness|src/runner.ts:971|accepted risk survives resume";
    const acceptedRisk: Finding = {
      severity: "medium",
      category: "Correctness",
      claim_quote: "accepted risk survives resume",
      location: "src/runner.ts:971",
      suggested_fix: "do not reopen at the same severity",
      action: "wont_fix",
      disposition_reason: "Accepted outside this slice",
      disposition: {
        kind: "accepted_suppressed",
        source: "issue #369 resume fixture",
        scope: "accepted risk survives resume",
        reason: "Accepted outside this slice",
        findingIdentity: acceptedRiskKey,
        boundedReopen: "reopen on material severity upgrade",
      },
    };
    const acceptedRiskDisposition = {
      identityKey: acceptedRiskKey,
      status: "accepted_suppressed" as const,
      reason: "Accepted outside this slice",
      severity: "medium" as const,
      source: "issue #369 resume fixture",
      scope: "accepted risk survives resume",
      boundedReopen: "reopen on material severity upgrade",
    };
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S3",
          output: { kind: "reviewer", findings: [blocking, acceptedRisk], findingsCount: 2 },
        },
        { step: "S4", findingDispositions: [acceptedRiskDisposition] },
      ],
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            // #604 correctness r1 (P2-a): a reopened finding is a plain blocking
            // fix_now with NO accepted_suppressed disposition (that is only valid
            // on wont_fix/rejected).
            findings: [
              {
                severity: acceptedRisk.severity,
                category: acceptedRisk.category,
                claim_quote: acceptedRisk.claim_quote,
                location: acceptedRisk.location,
                suggested_fix: acceptedRisk.suggested_fix,
                action: "fix_now",
              },
            ],
            findingsCount: 1,
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "verified-closed" },
              {
                identityKey: acceptedRiskKey,
                status: "still-active",
                reason: "reviewer-only suppression must be repaired",
              },
            ],
          },
        },
        {
          kind: "completed",
          output: { kind: "judge", status: "converged" },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 428, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S5:coder",
      "S6:verify",
      "S5:coder",
      "S6:verify",

    ]);
  });

  // #604 slice 4 (ADR 0062): re-feeding a terminal success run stays terminal
  // and dispatches nothing.
  it("keeps a re-fed terminal success run terminal", async () => {
    const followUpFinding: Finding = {
      severity: "medium",
      category: "Follow-up",
      claim_quote: "terminal resume still reports this follow-up",
      location: "src/runner.ts:926",
      suggested_fix: "surface the follow-up finding",
      action: "fix_now",
    };
    const resumeState: ResumeStateFixture = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [followUpFinding], findingsCount: 1 } },
        { step: "S4" },
        { step: "S7" },
        { step: "S8", handoffStatus: "success" },
      ],
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([]);
  });

  it("reviewer process throw uses mechanical dispatch budget only (no format escalate)", async () => {
    class LegacyThrowingReviewBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
      readonly calls: string[] = [];
      reviewerAttempts = 0;

      async findResumeState(): Promise<undefined> { return undefined; }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
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
      async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
        return { number: issueNumber, body: "body", comments: [], agentBrief: "" };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return WORKTREE;
      }
      async writeSnapshot(): Promise<void> {}
      async runStep(spec: StepSpec): Promise<StepOutput> {
        this.calls.push(`runStep(${spec.id})`);
        if ((spec.role === "reviewer" || spec.role === "verify")) {
          this.reviewerAttempts += 1;
          throw new Error("container failed to start");
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
    }
    const backend = new LegacyThrowingReviewBackend();

    const result = await runOrchestrator({ issueNumber: 369, backend });

    // Process crash path: mechanical redispatch, not runner format court.
    expect(backend.reviewerAttempts).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(result.status).toBe("error");
  });

  it("retries a reviewer non-structured crash, then surfaces a persistent one as an S8 error (#598)", async () => {
    class FailingReviewBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
      reviewerAttempts = 0;

      async findResumeState(): Promise<undefined> { return undefined; }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
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
      async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
        return { number: issueNumber, body: "body", comments: [], agentBrief: "" };
      }
      async prepareWorktree(): Promise<WorktreeHandle> {
        return WORKTREE;
      }
      async writeSnapshot(): Promise<void> {}
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if ((spec.role === "reviewer" || spec.role === "verify")) {
          this.reviewerAttempts += 1;
          throw new Error("container failed to start");
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async writeLedger(): Promise<void> {}
    }
    const backend = new FailingReviewBackend();

    const result = await runOrchestrator({ issueNumber: 369, backend });

    // Process crash path only (not findings-schema court): mechanical budget then stop.
    expect(result.status).toBe("error");
    expect(backend.reviewerAttempts).toBe(MAX_DISPATCH_ATTEMPTS);
  });
});

describe("#369 finding identity", () => {
  const finding: Finding = {
    severity: "medium",
    category: "Correctness",
    claim_quote: "  Missing   full diff review ",
    location: "src/runner.ts:120",
    suggested_fix: "review current full diff",
    action: "fix_now",
  };
  it("uses a normalized category/location/claim identity key, not an object hash", () => {
    const sameFindingDifferentWording: Finding = {
      ...finding,
      category: " correctness ",
      claim_quote: "missing full diff review",
      suggested_fix: "different wording should not change identity",
    };

    expect(findingIdentityKey(sameFindingDifferentWording)).toBe(
      findingIdentityKey(finding),
    );
  });

  it("escapes identity-key separators so distinct findings cannot collide", () => {
    const categoryCarriesSeparator: Finding = {
      ...finding,
      category: "Correct|ness",
      location: "src/runner.ts",
      claim_quote: "same claim",
    };
    const locationCarriesSeparator: Finding = {
      ...finding,
      category: "Correct",
      location: "ness|src/runner.ts",
      claim_quote: "same claim",
    };

    expect(findingIdentityKey(categoryCarriesSeparator)).not.toBe(
      findingIdentityKey(locationCarriesSeparator),
    );
  });

});

describe("#369 legacy S5 landing file", () => {
  it("materializes blocking findings in the runner-owned state dir, not the worktree-root spoofable file", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/fix",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "fix-findings-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "fix-findings-ledger-"));
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "fix me",
      location: "src/x.ts:1",
      suggested_fix: "patch it",
      action: "fix_now",
    };
    let observedLanding: unknown;
    writeFileSync(
      join(worktree.path, ".orchestrator-fix-findings.json"),
      '{"blockingFindings":[],"blockingFindingIdentityKeys":[]}\n',
      "utf8",
    );
    const backend: Backend = {
      async smokeModelRoute(route) { return route; },
      async findResumeState() { return undefined; },
      async resumeSession() {
        throw new Error("not expected");
      },
      async fetchIssueMeta() {
        throw new Error("not expected");
      },
      async fetchIssueSnapshot() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async writeSnapshot() {},
      async runStep() {
        observedLanding = JSON.parse(
          readFileSync(
            join(stateDir, "fix-findings.json"),
            "utf8",
          ),
        );
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger() {},
    };
    const spec: WorkerSpec = {
      id: "S5",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      skill: "/tdd",
      promptFile: "coder_fix.md",
      maxIter: 1,
      model: "gpt-5.6-sol",
      soul: "coder",
      toolchain: [],
    };

    const result = await legacyDispatchWorker(
      backend,
      spec,
      {
        worktree,
        stateDir,
        blockingFindingIdentityKeys: ["correctness|src/x.ts:1|fix me"],
        blockingFindingCount: 1,
        escalationAnswer: {
          event: "escalation_answered",
          forStep: "S4",
          answer: "continue-same-class",
          note: "human approved another targeted fix round",
          source: "human",
        },
      },
      { blockingFindings: [finding] },
    );

    expect(result.kind).toBe("completed");
    expect(observedLanding).toEqual({
      blockingFindings: [finding],
      blockingFindingIdentityKeys: ["correctness|src/x.ts:1|fix me"],
      escalationAnswer: {
        event: "escalation_answered",
        forStep: "S4",
        answer: "continue-same-class",
        note: "human approved another targeted fix round",
        source: "human",
      },
    });
    expect(JSON.parse(readFileSync(join(worktree.path, ".orchestrator-fix-findings.json"), "utf8"))).toEqual({
      blockingFindings: [],
      blockingFindingIdentityKeys: [],
    });
  });

  it("passes the runner-owned findings file as sandbox-visible S5 mount metadata", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/fix",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "fix-findings-mount-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "fix-findings-mount-ledger-"));
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "mount me",
      location: "src/x.ts:2",
      suggested_fix: "make visible in sandbox",
      action: "fix_now",
    };
    let observedLanding:
      | { readonly path: string; readonly sandboxPath: string }
      | undefined;
    const backend: Backend = {
      async smokeModelRoute(route) { return route; },
      async findResumeState() { return undefined; },
      async resumeSession() {
        throw new Error("not expected");
      },
      async fetchIssueMeta() {
        throw new Error("not expected");
      },
      async fetchIssueSnapshot() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async writeSnapshot() {},
      async runStep(_spec, _worktree, options) {
        observedLanding = options?.fixFindingsLanding;
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger() {},
    };
    const spec: WorkerSpec = {
      id: "S5",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      skill: "/tdd",
      promptFile: "coder_fix.md",
      maxIter: 1,
      model: "gpt-5.6-sol",
      soul: "coder",
      toolchain: [],
    };

    await legacyDispatchWorker(
      backend,
      spec,
      {
        worktree,
        stateDir,
        blockingFindingIdentityKeys: ["correctness|src/x.ts:2|mount me"],
        blockingFindingCount: 1,
      },
      { blockingFindings: [finding] },
    );

    expect(observedLanding).toEqual({
      path: join(stateDir, "fix-findings.json"),
      sandboxPath: ".orchestrator-fix-findings.json",
    });
  });

  it("materializes prior claimed-fixed findings for S6 reviewers through the same protected mount", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/fix",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "prior-findings-mount-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "prior-findings-mount-ledger-"));
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "verify me",
      location: "src/x.ts:3",
      suggested_fix: "confirm closure",
      action: "fix_now",
    };
    let observedLanding: unknown;
    let observedMount:
      | { readonly path: string; readonly sandboxPath: string }
      | undefined;
    const backend: Backend = {
      async smokeModelRoute(route) { return route; },
      async findResumeState() { return undefined; },
      async resumeSession() {
        throw new Error("not expected");
      },
      async fetchIssueMeta() {
        throw new Error("not expected");
      },
      async fetchIssueSnapshot() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async writeSnapshot() {},
      async runStep(_spec, _worktree, options) {
        observedMount = options?.fixFindingsLanding;
        observedLanding = JSON.parse(
          readFileSync(join(stateDir, "fix-findings.json"), "utf8"),
        );
        return { kind: "judge", status: "converged" };
      },
      async writeLedger() {},
    };
    const spec: WorkerSpec = {
      id: "S6",
      kind: "verify",
      role: "verify",
      host: "codex",
      session: "fresh",
      contextRetention: "clean",
      skill: "/verify",
      promptFile: "judge_station.md",
      maxIter: 1,
      model: "gpt-5.6-sol",
      soul: "verify",
      toolchain: [],
    };

    await legacyDispatchWorker(
      backend,
      spec,
      {
        worktree,
        stateDir,
        blockingFindingIdentityKeys: ["correctness|src/x.ts:3|verify me"],
        blockingFindingCount: 1,
      },
      { blockingFindings: [finding] },
    );

    expect(observedLanding).toEqual({
      blockingFindings: [finding],
      blockingFindingIdentityKeys: ["correctness|src/x.ts:3|verify me"],
    });
    expect(observedMount).toEqual({
      path: join(stateDir, "fix-findings.json"),
      sandboxPath: ".orchestrator-fix-findings.json",
    });
  });
});
