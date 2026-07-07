import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { legacyDispatchWorker } from "../src/dispatchWorker.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
import { MAX_DISPATCH_ATTEMPTS } from "../src/dispatchRetry.js";
import {
  adjudicatePriorClaimedFixedFindings,
  classifyFindings,
  findingIdentityKey,
} from "../src/findings.js";
import { route } from "../src/route.js";
import { runOrchestrator } from "../src/runner.js";
import {
  isValidFinding,
  isValidPriorFindingDisposition,
} from "../src/validate.js";
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
} from "../src/types.js";

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
  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: (WorkerLandingPayload | undefined)[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  reviewerAttempts = 0;
  coderAttempts = 0;

  constructor(
    private readonly reviewerResults: ReadonlyArray<WorkerResult>,
    private readonly resumeState?: ResumeState,
    private readonly coderOutputs: ReadonlyArray<StepOutput> = [],
    private readonly worktree: WorktreeHandle = WORKTREE,
    private readonly onCoderDispatch?: (
      attempt: number,
      worktree: WorktreeHandle,
    ) => void,
  ) {}

  async findResumeState(): Promise<ResumeState | undefined> {
    return this.resumeState;
  }
  async cleanResidue(): Promise<void> {}
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
    if (spec.role === "reviewer") return { kind: "reviewer", findings: [] };
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async push(): Promise<void> {}
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
    if (spec.kind === "reviewer") {
      const result = this.reviewerResults[this.reviewerAttempts];
      this.reviewerAttempts += 1;
      return result ?? { kind: "completed", output: { kind: "reviewer", findings: [] } };
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
  it("reruns an invalid reviewer output once, then succeeds on a clean full-diff review", async () => {
    const backend = new RetryReviewBackend([
      { kind: "malformed", reason: "missing <review> tag" },
      { kind: "completed", output: { kind: "reviewer", findings: [] } },
    ]);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S3:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
    expect(backend.specs.filter((s) => s.id === "S3").every((s) => s.session === "fresh")).toBe(true);
  });

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
      { kind: "completed", output: { kind: "reviewer", findings: [finding] } },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            {
              identityKey:
                "correctness|src/runner.ts:1|fix worker needs structured finding data",
              status: "verified-closed",
            },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
    expect(s5Index).toBeGreaterThanOrEqual(0);
    expect(backend.landings[s5Index]?.blockingFindings).toEqual([finding]);
    expect(backend.ctxs[s5Index]?.blockingFindingIdentityKeys).toEqual([
      "correctness|src/runner.ts:1|fix worker needs structured finding data",
    ]);
  });

  // #604 slice 4 (ADR 0062): the former cross-module defer is now blocking, so
  // both findings ride the fix loop and deferredFindings is always empty.
  it("keeps former cross-module defers blocking across fix rounds", async () => {
    const blocking: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "must fix before shipping",
      location: "src/runner.ts:10",
      suggested_fix: "fix it",
      action: "fix_now",
    };
    const formerCrossModuleDefer: Finding = {
      severity: "medium",
      category: "Follow-up",
      claim_quote: "track this later",
      location: "src/runner.ts:11",
      suggested_fix: "file follow-up",
      action: "defer",
    };
    const backend = new RetryReviewBackend([
      {
        kind: "completed",
        output: { kind: "reviewer", findings: [blocking, formerCrossModuleDefer] },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            {
              identityKey: "correctness|src/runner.ts:10|must fix before shipping",
              status: "verified-closed",
            },
            {
              identityKey: "follow-up|src/runner.ts:11|track this later",
              status: "verified-closed",
            },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(result.deferredFindings).toEqual([]);
  });

  it("escalates after the bounded reviewer-output retry budget is exhausted", async () => {
    const backend = new RetryReviewBackend([
      { kind: "malformed", reason: "truncated JSON" },
      { kind: "malformed", reason: "truncated JSON again" },
    ]);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S3:reviewer",
    ]);
    const s3 = result.stepLedger.find((entry) => entry.step === "S3");
    expect(s3?.output?.kind).toBe("reviewer");
    expect(s3?.output?.escalate?.reason).toMatch(/bounded reruns/i);
  });

  // #604 correctness r1 (P1-a ①): a RUNNER-synthesized escalate from exhausted
  // malformed reviewer reruns is a PROTOCOL FAILURE, not a worker-proactive
  // decision. Its persisted S8 handoff must be escalationKind:"failure"
  // (A-class), never "decision" (B-class park) — even though its
  // reason/diagnosis are well-formed strings.
  it("maps an exhausted-malformed synthesized escalate to escalationKind:failure, not decision", async () => {
    const backend = new RetryReviewBackend([
      { kind: "malformed", reason: "truncated JSON" },
      { kind: "malformed", reason: "truncated JSON again" },
    ]);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("escalate");
    // The synthesized escalate carries the protocol-failure marker.
    const s3 = result.stepLedger.find((entry) => entry.step === "S3");
    expect(s3?.output?.escalate?.synthesizedFailure).toBe(true);
    // The persisted S8 handoff entry is tagged FAILURE, not decision.
    const s8Escalate = backend.ledgerWrites.find(
      (entry) => entry.step === "S8" && entry.handoffStatus === "escalate",
    );
    expect(s8Escalate).toBeDefined();
    expect(s8Escalate?.escalationKind).toBe("failure");
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

  it("routes S4 from the runner-adjudicated blocking set, not only reviewer findings", () => {
    expect(
      route({
        from: "S4",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
        pendingBlockingFindings: [blocking],
      }),
    ).toEqual({ kind: "next", step: "S5" });
  });

  it("#551 keeps per-slice S5 no-commit output on the existing terminal error edge", () => {
    expect(
      route({
        from: "S5",
        output: { kind: "coder", committed: false, commitsAdded: 0 },
      }),
    ).toEqual({ kind: "handoff", status: "error" });
  });

  it("fails closed when a fresh re-review omits disposition for a prior claimed-fixed finding", async () => {
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking] } },
      { kind: "completed", output: { kind: "reviewer", findings: [] } },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S4");
    expect(result.errorPackage?.reason).toMatch(/omitted required disposition/i);
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
    ]);
  });

  it("fails closed when prior claimed-fixed finding keys and payloads drift", () => {
    const orphanKey = "correctness|src/runner.ts:404|missing finding payload";

    expect(() =>
      adjudicatePriorClaimedFixedFindings({
        priorFindings: [],
        priorIdentityKeys: [orphanKey],
        review: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: orphanKey, status: "still-active" },
          ],
        },
      }),
    ).toThrow(/finding\/key count mismatch/);
  });

  it("ships only after the fresh re-review explicitly verifies a claimed-fixed finding closed", async () => {
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking] } },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "verified-closed" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
  });

  it("passes prior claimed-fixed findings and identity keys to the S6 fresh reviewer", async () => {
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking] } },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "verified-closed" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 428, backend });

    expect(result.status).toBe("success");
    const s6Index = backend.specs.findIndex((spec) => spec.id === "S6");
    expect(s6Index).toBeGreaterThanOrEqual(0);
    expect(backend.landings[s6Index]?.blockingFindings).toEqual([blocking]);
    expect(backend.ctxs[s6Index]?.blockingFindingIdentityKeys).toEqual([
      blockingKey,
    ]);
  });

  it("threads S4 finding dispositions through live re-review classification and persists them", async () => {
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
        output: { kind: "reviewer", findings: [blocking, acceptedRisk] },
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
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: acceptedRiskKey, status: "verified-closed" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 428, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
    const firstS4Write = backend.ledgerWrites.find((entry) => entry.step === "S4");
    expect(firstS4Write?.findingDispositions).toEqual([]);
  });

  it("bounds repeated still-active findings instead of looping forever", async () => {
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking] } },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [blocking],
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [blocking],
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("escalate");
    expect(result.errorPackage?.failedStep).toBe("S4");
    expect(result.errorPackage?.reason).toMatch(/no progress/i);
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
    ]);
    expect(backend.ledgerWrites.at(-1)).toEqual(
      expect.objectContaining({
        step: "S8",
        handoffStatus: "escalate",
        escalationKind: "decision",
      }),
    );
  });

  it("requires observable scope-local repair evidence before counting a still-active round as progress", async () => {
    const scopedEvidence = {
      kind: "coder" as const,
      committed: true,
      commitsAdded: 1,
      repairEvidence: {
        findingScope: {
          identityKeys: [blockingKey],
          locations: ["src/runner.ts"],
        },
        changedFiles: ["src/runner.ts"],
        tests: ["npm test -- --run test/per-slice-cmr-369.test.ts"],
      },
    };
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
        { kind: "completed", output: { kind: "reviewer", findings: [blocking] } },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [blocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [blocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "verified-closed" },
            ],
          },
        },
      ],
      undefined,
      [scopedEvidence, scopedEvidence, scopedEvidence],
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
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
  });

  it("counts scoped test-file repair evidence as observable progress", async () => {
    const scopedTestEvidence = {
      kind: "coder" as const,
      committed: true,
      commitsAdded: 1,
      repairEvidence: {
        findingScope: { identityKeys: [blockingKey] },
        tests: ["test/per-slice-cmr-369.test.ts"],
      },
    };
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
        { kind: "completed", output: { kind: "reviewer", findings: [blocking] } },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [blocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [blocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "verified-closed" },
            ],
          },
        },
      ],
      undefined,
      [scopedTestEvidence, scopedTestEvidence, scopedTestEvidence],
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
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
  });

  it("does not treat command-valued tests repair evidence as declared changed paths", async () => {
    const commandOnlyTestEvidence = {
      kind: "coder" as const,
      committed: true,
      commitsAdded: 1,
      repairEvidence: {
        findingScope: { identityKeys: [blockingKey] },
        tests: ["npm test -- --run test/per-slice-cmr-369.test.ts"],
      },
    };
    const worktree = makeGitWorktree();
    const backend = new RetryReviewBackend(
      [
        { kind: "completed", output: { kind: "reviewer", findings: [blocking] } },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [blocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [blocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "verified-closed" },
            ],
          },
        },
      ],
      undefined,
      [commandOnlyTestEvidence, commandOnlyTestEvidence, commandOnlyTestEvidence],
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
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
  });

  it("restores resume repair movement paths before judging still-active no-progress", async () => {
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-427",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking] } },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        {
          step: "S5",
          output: {
            kind: "coder",
            committed: true,
            commitsAdded: 1,
            repairEvidence: {
              findingScope: { identityKeys: [blockingKey] },
              changedFiles: ["src/runner.ts"],
              tests: ["npm test -- --run test/per-slice-cmr-369.test.ts"],
            },
          },
          repairMovementPaths: ["src/runner.ts"],
        },
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "verified-closed" },
            ],
          },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
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
      { kind: "completed", output: { kind: "reviewer", findings: sample.initial } },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: sample.firstAfterFix,
          priorFindingDispositions: sample.firstDispositions,
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: sample.secondAfterFix,
          priorFindingDispositions: sample.secondDispositions,
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: sample.finalDispositions,
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("success");
    expect(result.errorPackage).toBeUndefined();
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
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
      { kind: "completed", output: { kind: "reviewer", findings: [originalFinding] } },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [firstNarrowedFinding],
          priorFindingDispositions: [
            { identityKey: originalKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [secondNarrowedFinding],
          priorFindingDispositions: [
            { identityKey: originalKey, status: "still-active" },
            { identityKey: firstNarrowedKey, status: "still-active" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("escalate");
    expect(result.stopSummary.reason).toBe("same_module_still_red");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
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
        output: { kind: "reviewer", findings: [primaryFinding, secondaryFinding] },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [{ ...secondaryFinding, severity: "medium" }],
          priorFindingDispositions: [
            { identityKey: primaryKey, status: "still-active" },
            { identityKey: secondaryKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [{ ...secondaryFinding, severity: "low" }],
          priorFindingDispositions: [
            { identityKey: primaryKey, status: "still-active" },
            { identityKey: secondaryKey, status: "still-active" },
          ],
        },
      },
      {
        kind: "completed",
        output: {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            { identityKey: primaryKey, status: "verified-closed" },
            { identityKey: secondaryKey, status: "verified-closed" },
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 427, backend });

    expect(result.status).toBe("escalate");
    expect(result.stopSummary.reason).toBe("same_module_still_red");
    expect(backend.dispatched).toEqual([
      "S2:coder",
      "S3:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
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
    } as unknown as PersistentLedgerEntry;
    expect(continueFixingEvent).not.toHaveProperty("output");
    expect(continueFixingEvent).not.toHaveProperty("verdict");

    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking] } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [blocking],
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
            kind: "reviewer",
            findings: [blocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
        continueFixingEvent,
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [blocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "verified-closed" },
            ],
          },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
  });

  it("uses current run continue-fixing input even when no durable continue event exists", async () => {
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking] } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [blocking],
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
            kind: "reviewer",
            findings: [blocking],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
        { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "verified-closed" },
            ],
          },
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
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
  });

  it("does not treat source-less continue-fixing bookkeeping as an executable human resume", async () => {
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking] } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [blocking],
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
            kind: "reviewer",
            findings: [blocking],
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
        } as unknown as PersistentLedgerEntry,
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatched).toEqual([]);
  });

  it("does not reopen an S4 decision escalation for stale or scope-mismatched continue-fixing bookkeeping", async () => {
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking] } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [blocking],
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
            kind: "reviewer",
            findings: [blocking],
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
        } as unknown as PersistentLedgerEntry,
      ] as ReadonlyArray<PersistentLedgerEntry>,
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
      { step: "S3", output: { kind: "reviewer", findings: [blocking] } },
      { step: "S4" },
      { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      {
        step: "S6",
        output: {
          kind: "reviewer",
          findings: [blocking],
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
          kind: "reviewer",
          findings: [blocking],
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "still-active" },
          ],
        },
      },
      { step: "S4" },
      { step: "S8", handoffStatus: "escalate", escalationKind: "decision" },
    ] as const;
    const malformedEvents = [
      {
        step: "S4",
        event: "runner_bookkeeping",
        intent: "continue_fixing",
        findingScope: { identityKeys: "not-an-array" },
        source: "resume_input",
        ts: "2026-07-01T00:00:03.000Z",
      },
      {
        step: "S4",
        event: "escalation_answered",
        forStep: "S4",
        answer: "继续修",
        source: "human",
        findingScope: { locations: [7] },
      },
    ];

    for (const event of malformedEvents) {
      const backend = new RetryReviewBackend([], {
        worktree: WORKTREE,
        stateDir: "/resident/worktrees/.ledger-446",
        ledger: [...baseLedger, event] as ReadonlyArray<PersistentLedgerEntry>,
      });

      const result = await runOrchestrator({ issueNumber: 446, backend });

      expect(result.status).toBe("escalate");
      expect(backend.dispatched).toEqual([]);
    }
  });

  it("does not map unscoped escalation answers to continue-fixing repair intent", async () => {
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [blocking] } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [blocking],
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
            kind: "reviewer",
            findings: [blocking],
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
        } as unknown as PersistentLedgerEntry,
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatched).toEqual([]);
  });

  it("preserves a persisted terminal error stop summary on already-done re-feed", async () => {
    const resumeState: ResumeState = {
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
      ] as ReadonlyArray<PersistentLedgerEntry>,
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
      const resumeState: ResumeState = {
        worktree: WORKTREE,
        stateDir: `/resident/worktrees/.ledger-446-${source}`,
        ledger: [
          { step: "S0" },
          { step: "S1" },
          { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          { step: "S3", output: { kind: "reviewer", findings: [blocking] } },
          { step: "S4" },
          { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          {
            step: "S6",
            output: {
              kind: "reviewer",
              findings: [blocking],
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
              kind: "reviewer",
              findings: [blocking],
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
          } as unknown as PersistentLedgerEntry,
        ] as ReadonlyArray<PersistentLedgerEntry>,
      };
      const backend = new RetryReviewBackend(
        [
          {
            kind: "completed",
            output: {
              kind: "reviewer",
              findings: [],
              priorFindingDispositions: [
                { identityKey: blockingKey, status: "verified-closed" },
              ],
            },
          },
        ],
        resumeState,
      );

      const result = await runOrchestrator({ issueNumber: 446, backend });

      expect(result.status).toBe("success");
      expect(backend.dispatched).toEqual(["S5:coder", "S6:reviewer", "S7:ship", "S9:verify", "S10:fixer", "S11:cleanup", "S12:docRelease"]);
    }
  });

  it("does not treat scoped coordinator or peripheral escalation answers as executable continue-fixing input", async () => {
    for (const source of ["coordinator", "peripheral"] as const) {
      const resumeState: ResumeState = {
        worktree: WORKTREE,
        stateDir: `/resident/worktrees/.ledger-446-${source}`,
        ledger: [
          { step: "S0" },
          { step: "S1" },
          { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          { step: "S3", output: { kind: "reviewer", findings: [blocking] } },
          { step: "S4" },
          { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
          {
            step: "S6",
            output: {
              kind: "reviewer",
              findings: [blocking],
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
          } as unknown as PersistentLedgerEntry,
        ] as ReadonlyArray<PersistentLedgerEntry>,
      };
      const backend = new RetryReviewBackend([], resumeState);

      const result = await runOrchestrator({ issueNumber: 446, backend });

      expect(result.status).toBe("escalate");
      expect(backend.dispatched).toEqual([]);
    }
  });

  it("matches broad file scope against path-line findings without resetting sibling findings", async () => {
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

    const resumeState: ResumeState = {
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
          output: { kind: "reviewer", findings: [runnerFinding, siblingFinding] },
        },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [runnerFinding, siblingFinding],
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
            kind: "reviewer",
            findings: [runnerFinding, siblingFinding],
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
        } as unknown as PersistentLedgerEntry,
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("escalate");
    expect(backend.dispatched).toEqual([]);
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
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        {
          step: "S2",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        { step: "S3", output: { kind: "reviewer", findings: [fileScopedFinding] } },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [fileScopedFinding],
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
            kind: "reviewer",
            findings: [fileScopedFinding],
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
        } as unknown as PersistentLedgerEntry,
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: fileScopedFindingKey, status: "verified-closed" },
            ],
          },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual(["S5:coder", "S6:reviewer", "S7:ship", "S9:verify", "S10:fixer", "S11:cleanup", "S12:docRelease"]);
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
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        {
          step: "S2",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        { step: "S3", output: { kind: "reviewer", findings: [fileScopedFinding] } },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [fileScopedFinding],
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
            kind: "reviewer",
            findings: [fileScopedFinding],
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
        } as unknown as PersistentLedgerEntry,
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: fileScopedFindingKey, status: "verified-closed" },
            ],
          },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual(["S5:coder", "S6:reviewer", "S7:ship", "S9:verify", "S10:fixer", "S11:cleanup", "S12:docRelease"]);
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
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-446",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        {
          step: "S2",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        { step: "S3", output: { kind: "reviewer", findings: [fileScopedFinding] } },
        { step: "S4" },
        {
          step: "S5",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [fileScopedFinding],
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
            kind: "reviewer",
            findings: [fileScopedFinding],
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
        } as unknown as PersistentLedgerEntry,
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: fileScopedFindingKey, status: "verified-closed" },
            ],
          },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 446, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual(["S5:coder", "S6:reviewer", "S7:ship", "S9:verify", "S10:fixer", "S11:cleanup", "S12:docRelease"]);
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
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding] } },
        { step: "S4" },
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              {
                identityKey:
                  "correctness|src/runner.ts:1116|s5 needs the persisted blocker after resume",
                status: "verified-closed",
              },
            ],
          },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    const s5Index = backend.specs.findIndex((spec) => spec.id === "S5");
    expect(s5Index).toBeGreaterThanOrEqual(0);
    expect(backend.landings[s5Index]?.blockingFindings).toEqual([finding]);
    expect(backend.ctxs[s5Index]?.blockingFindingIdentityKeys).toEqual([
      "correctness|src/runner.ts:1116|s5 needs the persisted blocker after resume",
    ]);
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
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding] } },
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
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              {
                identityKey:
                  "correctness|src/runner.ts:902|s5 fallback still needs the blocker",
                status: "verified-closed",
              },
            ],
          },
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
    expect(backend.ctxs[s5Index]?.blockingFindingIdentityKeys).toEqual([
      "correctness|src/runner.ts:902|s5 fallback still needs the blocker",
    ]);
  });

  it("preserves S6 adjudication requirements when resuming into S4", async () => {
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "resumed S6 still needs disposition",
      location: "src/runner.ts:950",
      suggested_fix: "remember that the last reviewer step was S6",
      action: "fix_now",
    };
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding] } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S6", output: { kind: "reviewer", findings: [] } },
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S4");
    expect(result.errorPackage?.reason).toMatch(/omitted required disposition/i);
    expect(backend.dispatched).toEqual([]);
  });

  it("routes a persisted S4 after still-active S6 back to S5 on resume", async () => {
    const finding: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "persisted S4 still has the prior blocker",
      location: "src/runner.ts:960",
      suggested_fix: "route the adjudicated still-open finding to S5",
      action: "fix_now",
    };
    const key = "correctness|src/runner.ts:960|persisted s4 still has the prior blocker";
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [finding] } },
        { step: "S4" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S6",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: key, status: "still-active" },
            ],
          },
        },
        { step: "S4" },
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend(
      [
        {
          kind: "completed",
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: key, status: "verified-closed" },
            ],
          },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
    expect(backend.landings[0]?.blockingFindings).toEqual([finding]);
    expect(backend.ctxs[0]?.blockingFindingIdentityKeys).toEqual([key]);
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
      reopenAttempts: 0,
      source: "issue #369 resume fixture",
      scope: "accepted risk survives resume",
      boundedReopen: "reopen on material severity upgrade",
    };
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        {
          step: "S3",
          output: { kind: "reviewer", findings: [blocking, acceptedRisk] },
        },
        { step: "S4", findingDispositions: [acceptedRiskDisposition] },
      ] as ReadonlyArray<PersistentLedgerEntry>,
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
          output: {
            kind: "reviewer",
            findings: [],
            priorFindingDispositions: [
              { identityKey: acceptedRiskKey, status: "verified-closed" },
            ],
          },
        },
      ],
      resumeState,
    );

    const result = await runOrchestrator({ issueNumber: 428, backend });

    expect(result.status).toBe("success");
    expect(backend.dispatched).toEqual([
      "S5:coder",
      "S6:reviewer",
      "S5:coder",
      "S6:reviewer",
      "S7:ship",
      "S9:verify",
      "S10:fixer",
      "S11:cleanup",
      "S12:docRelease",
    ]);
  });

  // #604 slice 4 (ADR 0062): deferredFindings is always empty now; re-feeding a
  // terminal success run stays terminal and dispatches nothing, but rebuilds an
  // empty deferred bucket rather than the former cross-module defer.
  it("rebuilds an empty deferred bucket when re-feeding a terminal resumed run", async () => {
    const formerCrossModuleDefer: Finding = {
      severity: "medium",
      category: "Follow-up",
      claim_quote: "terminal resume still reports this defer",
      location: "src/runner.ts:926",
      suggested_fix: "surface the deferred finding",
      action: "defer",
    };
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: "/resident/worktrees/.ledger-369",
      ledger: [
        { step: "S0" },
        { step: "S1" },
        { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
        { step: "S3", output: { kind: "reviewer", findings: [formerCrossModuleDefer] } },
        { step: "S4" },
        { step: "S7" },
        { step: "S8", handoffStatus: "success" },
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(result.deferredFindings).toEqual([]);
    expect(backend.dispatched).toEqual([]);
  });

  it("bounded-retries legacy reviewer parse exceptions before succeeding", async () => {
    class LegacyThrowingReviewBackend implements Backend {
      readonly calls: string[] = [];
      reviewerAttempts = 0;

      async findResumeState(): Promise<undefined> { return undefined; }
      async cleanResidue(): Promise<void> {}
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
        if (spec.role === "reviewer") {
          this.reviewerAttempts += 1;
          if (this.reviewerAttempts === 1) {
            throw new Error("StructuredOutputError: missing <review> tag");
          }
          return { kind: "reviewer", findings: [] };
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async push(): Promise<void> {}
      async writeLedger(): Promise<void> {}
    }
    const backend = new LegacyThrowingReviewBackend();

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(backend.calls).toEqual(["runStep(S2)", "runStep(S3)", "runStep(S3)"]);
    expect(backend.reviewerAttempts).toBe(2);
  });

  it("retries a reviewer non-structured crash, then surfaces a persistent one as an S8 error (#598)", async () => {
    class FailingReviewBackend implements Backend {
      reviewerAttempts = 0;

      async findResumeState(): Promise<undefined> { return undefined; }
      async cleanResidue(): Promise<void> {}
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
        if (spec.role === "reviewer") {
          this.reviewerAttempts += 1;
          throw new Error("container failed to start");
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      async push(): Promise<void> {}
      async writeLedger(): Promise<void> {}
    }
    const backend = new FailingReviewBackend();

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.failedStep).toBe("S3");
    expect(result.errorPackage?.reason).toContain("container failed to start");
    // #598: a reviewer NON-structured crash (a container/connection failure, not a
    // structured-output error) is now retried by the generic mechanical layer up to
    // MAX_DISPATCH_ATTEMPTS before the reviewer loop surfaces the persistent crash as
    // S8 — a transient crash would recover instead of aborting on the first failure.
    expect(backend.reviewerAttempts).toBe(MAX_DISPATCH_ATTEMPTS);
  });
});

describe("#369 finding identity and classification", () => {
  const finding: Finding = {
    severity: "medium",
    category: "Correctness",
    claim_quote: "  Missing   full diff review ",
    location: "src/runner.ts:120",
    suggested_fix: "review current full diff",
    action: "fix_now",
  };
  const findingKey = "correctness|src/runner.ts:120|missing full diff review";
  const acceptedSource = {
    source: "issue #448 acceptance criteria",
    scope: "same documented non-goal",
    reason: "Accepted as outside this slice",
    findingIdentity: findingKey,
    boundedReopen: "reopen on severity upgrade, new evidence, or wider scope",
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

  it("classifies blocking findings and exposes their identity keys together", () => {
    const classification = classifyFindings([finding]);

    expect(classification.blocking).toEqual([finding]);
    expect(classification.deferred).toEqual([]);
    expect(classification.blockingIdentityKeys).toEqual([
      "correctness|src/runner.ts:120|missing full diff review",
    ]);
  });

  it("persists wont-fix and rejected dispositions with identity and rationale", () => {
    const first: Finding = {
        ...finding,
        action: "wont_fix",
        disposition_reason: "legacy fallback should not win",
        disposition: {
          kind: "accepted_suppressed",
          ...acceptedSource,
        },
      };
    const secondSource = {
      source: "ADR 0030 accepted scope",
      scope: "existing invariant",
      reason: "The claim is false on the current full diff",
      findingIdentity:
        "correctness|src/runner.ts:120|already covered by existing invariant",
      boundedReopen: "reopen if reviewer shows new failing evidence",
    };
    const second: Finding = {
        ...finding,
        claim_quote: "  Already covered by existing invariant ",
        action: "rejected",
        disposition_reason: "The claim is false on the current full diff",
        disposition: {
          kind: "accepted_suppressed",
          ...secondSource,
        },
      };
    const classification = classifyFindings([first, second], [], {
      acceptedSuppressionSources: [acceptedSource, secondSource],
    });

    expect(classification.deferred).toEqual([]);
    expect(classification.dispositions).toEqual([
      {
        identityKey: findingKey,
        status: "accepted_suppressed",
        reason: "Accepted as outside this slice",
        severity: "medium",
        reopenAttempts: 0,
        source: acceptedSource.source,
        scope: acceptedSource.scope,
        boundedReopen: acceptedSource.boundedReopen,
      },
      {
        identityKey:
          "correctness|src/runner.ts:120|already covered by existing invariant",
        status: "accepted_suppressed",
        reason: "The claim is false on the current full diff",
        severity: "medium",
        reopenAttempts: 0,
        source: secondSource.source,
        scope: secondSource.scope,
        boundedReopen: secondSource.boundedReopen,
      },
    ]);
  });

  it("derives accepted_suppressed rationale and finding identity when workers omit redundant fields", () => {
    const suppressed: Finding = {
      ...finding,
      action: "wont_fix",
      disposition: {
        kind: "accepted_suppressed",
        source: acceptedSource.source,
        scope: acceptedSource.scope,
        reason: acceptedSource.reason,
        boundedReopen: acceptedSource.boundedReopen,
      },
    };

    expect(isValidFinding(suppressed)).toBe(true);
    expect(
      classifyFindings([suppressed], [], {
        acceptedSuppressionSources: [acceptedSource],
      }).dispositions,
    ).toEqual([
      {
        identityKey: findingKey,
        status: "accepted_suppressed",
        reason: acceptedSource.reason,
        severity: "medium",
        reopenAttempts: 0,
        source: acceptedSource.source,
        scope: acceptedSource.scope,
        boundedReopen: acceptedSource.boundedReopen,
      },
    ]);
  });

  it("does not let reviewer text fabricate an accepted suppression", () => {
    const suppressed: Finding = {
      ...finding,
      action: "wont_fix",
      disposition: {
        kind: "accepted_suppressed",
        ...acceptedSource,
      },
    };

    const classification = classifyFindings([suppressed]);

    expect(classification.blocking).toEqual([suppressed]);
    expect(classification.dispositions).toEqual([]);
  });

  it("rejects critical/high findings unless they are fix-now", () => {
    expect(
      isValidFinding({
        ...finding,
        severity: "high",
        action: "defer",
      }),
    ).toBe(false);
    expect(
      isValidFinding({
        ...finding,
        severity: "critical",
        action: "wont_fix",
        disposition_reason: "not allowed for P0",
      }),
    ).toBe(false);
    expect(
      isValidFinding({
        ...finding,
        severity: "high",
        action: "fix_now",
      }),
    ).toBe(true);
  });

  // #604 slice 4 (ADR 0062): the same_module disposition kind is gone. A bare
  // action:"defer" finding is classified as blocking (never passes S4), and
  // because a defer with no valid non-accepted-suppression disposition is now a
  // contract-invalid reviewer output, route() fails it closed to S8(error)
  // rather than ever letting S4 pass to ship.
  it("keeps a bare defer blocking instead of letting S4 pass", () => {
    const bareDefer: Finding = {
      ...finding,
      action: "defer",
    };

    const classification = classifyFindings([bareDefer]);

    expect(classification.blocking).toEqual([bareDefer]);
    expect(classification.deferred).toEqual([]);
    expect(
      route({
        from: "S4",
        output: { kind: "reviewer", findings: [bareDefer] },
      }),
    ).toEqual({ kind: "handoff", status: "error" });
  });

  // #604 slice 4 (ADR 0062): the cross_module disposition and its deferred→S7
  // pass path are gone. A former cross-module defer is now a bare defer:
  // classifyFindings treats it as blocking, and since it carries no valid
  // non-accepted-suppression disposition it is a contract-invalid reviewer
  // output, so route() fails it closed to S8(error) — the deferred→S7 pass path
  // no longer exists.
  it("treats a former cross-module defer as blocking", () => {
    const formerCrossModuleDefer: Finding = {
      ...finding,
      action: "defer",
    };

    const classification = classifyFindings([formerCrossModuleDefer]);

    expect(classification.blocking).toEqual([formerCrossModuleDefer]);
    expect(classification.deferred).toEqual([]);
    expect(
      route({
        from: "S4",
        output: { kind: "reviewer", findings: [formerCrossModuleDefer] },
      }),
    ).toEqual({ kind: "handoff", status: "error" });
  });

  // #604 slice 4 (ADR 0062): the owning_issue_still_red disposition kind is gone.
  // classifyFindings still treats a bare action:"defer" finding as blocking; the
  // deleted-kind isValidFinding sub-assertions are removed because no routing
  // disposition kinds remain to construct.
  it("records a defer finding as blocking", () => {
    const stillRed: Finding = {
      ...finding,
      action: "defer",
    };

    const classification = classifyFindings([stillRed]);

    expect(classification.blocking).toEqual([stillRed]);
    expect(classification.deferred).toEqual([]);
    expect(isValidFinding(finding)).toBe(true);
  });

  // #604 slice 4 (ADR 0062): the spec_conflict / infra_failure disposition kinds
  // are gone. Both were fail-closed defers; as bare defers they remain blocking,
  // so there is no longer a "separate" classification to assert. The deleted-kind
  // isValidFinding sub-assertions are removed (no routing disposition kinds remain).
  it("classifies former spec/infra findings as blocking", () => {
    const specConflict: Finding = {
      ...finding,
      action: "defer",
    };
    const infraFailure: Finding = {
      ...finding,
      claim_quote: "gh auth failed",
      action: "defer",
    };

    const classification = classifyFindings([specConflict, infraFailure]);

    expect(classification.blocking).toEqual([specConflict, infraFailure]);
    expect(classification.deferred).toEqual([]);
  });

  it("requires sourced accepted suppression and reopens it when evidence exceeds the bound", () => {
    const acceptedSuppressed: Finding = {
      ...finding,
      action: "wont_fix",
      disposition_reason: "Accepted by issue text as out of scope",
      disposition: {
        kind: "accepted_suppressed",
        source: "issue #448 acceptance criteria",
        scope: "cross-module target already tracked",
        reason: "Accepted by issue text as out of scope",
        findingIdentity: findingIdentityKey(finding),
        boundedReopen: "reopen on higher severity, new evidence, or different scope",
      },
    };

    const acceptedSuppressions = [
      {
        source: "issue #448 acceptance criteria",
        scope: "cross-module target already tracked",
        reason: "Accepted by issue text as out of scope",
        findingIdentity: findingIdentityKey(finding),
        boundedReopen: "reopen on higher severity, new evidence, or different scope",
      },
    ];
    const suppressed = classifyFindings([acceptedSuppressed], [], {
      acceptedSuppressionSources: acceptedSuppressions,
    });

    expect(suppressed.blocking).toEqual([]);
    expect(suppressed.dispositions).toEqual([
      {
        identityKey: findingIdentityKey(finding),
        status: "accepted_suppressed",
        reason: "Accepted by issue text as out of scope",
        severity: "medium",
        reopenAttempts: 0,
        source: "issue #448 acceptance criteria",
        scope: "cross-module target already tracked",
        boundedReopen: "reopen on higher severity, new evidence, or different scope",
      },
    ]);
    expect(
      isValidFinding({
        ...acceptedSuppressed,
        disposition: {
          kind: "accepted_suppressed",
          source: "issue #448 acceptance criteria",
          reason: "missing scope, identity, and reopen condition",
        },
      }),
    ).toBe(false);

    const reopened = classifyFindings(
      [{ ...finding, severity: "high", action: "fix_now" }],
      suppressed.dispositions,
      { acceptedSuppressionSources: acceptedSuppressions },
    );

    expect(reopened.blocking).toEqual([
      { ...finding, severity: "high", action: "fix_now" },
    ]);
    expect(reopened.dispositions[0]).toMatchObject({
      status: "accepted_suppressed",
      severity: "high",
      reopenAttempts: 1,
    });
  });

  it("treats accepted_suppressed prior claimed-fixed dispositions as terminal closure", () => {
    const key = findingIdentityKey(finding);

    const adjudication = adjudicatePriorClaimedFixedFindings({
      priorFindings: [finding],
      priorIdentityKeys: [key],
      acceptedSuppressionSources: [
        {
          source: "issue #448 acceptance criteria",
          scope: "same claimed-fixed finding",
          reason: "accepted by the owner for this bounded scope",
          findingIdentity: key,
          boundedReopen: "reopen on higher severity or different scope",
        },
      ],
      review: {
        kind: "reviewer",
        findings: [],
        priorFindingDispositions: [
          {
            identityKey: key,
            status: "accepted_suppressed",
            source: "issue #448 acceptance criteria",
            scope: "same claimed-fixed finding",
            reason: "accepted by the owner for this bounded scope",
            boundedReopen: "reopen on higher severity or different scope",
          },
        ],
      },
    });

    expect(adjudication.stillOpen).toEqual([]);
    expect(adjudication.verifiedClosedIdentityKeys).toEqual([key]);
  });

  it("keeps high prior claimed-fixed findings open even with accepted_suppressed disposition", () => {
    const highFinding: Finding = {
      ...finding,
      severity: "high",
      action: "fix_now",
    };
    const key = findingIdentityKey(highFinding);

    const adjudication = adjudicatePriorClaimedFixedFindings({
      priorFindings: [highFinding],
      priorIdentityKeys: [key],
      acceptedSuppressionSources: [
        {
          source: "issue #448 acceptance criteria",
          scope: "same claimed-fixed finding",
          reason: "accepted by the owner for this bounded scope",
          findingIdentity: key,
          boundedReopen: "reopen on higher severity or different scope",
        },
      ],
      review: {
        kind: "reviewer",
        findings: [],
        priorFindingDispositions: [
          {
            identityKey: key,
            status: "accepted_suppressed",
            source: "issue #448 acceptance criteria",
            scope: "same claimed-fixed finding",
            reason: "accepted by the owner for this bounded scope",
            boundedReopen: "reopen on higher severity or different scope",
          },
        ],
      },
    });

    expect(adjudication.stillOpen).toEqual([highFinding]);
    expect(adjudication.verifiedClosedIdentityKeys).toEqual([]);
  });

  it("does not treat reviewer-created accepted_suppressed prior dispositions as terminal closure", () => {
    const key = findingIdentityKey(finding);

    const adjudication = adjudicatePriorClaimedFixedFindings({
      priorFindings: [finding],
      priorIdentityKeys: [key],
      review: {
        kind: "reviewer",
        findings: [],
        priorFindingDispositions: [
          {
            identityKey: key,
            status: "accepted_suppressed",
            source: "reviewer judgement",
            scope: "same claimed-fixed finding",
            reason: "the reviewer decided this is acceptable",
            boundedReopen: "maybe reconsider later",
          },
        ],
      },
    });

    expect(adjudication.stillOpen).toEqual([finding]);
    expect(adjudication.verifiedClosedIdentityKeys).toEqual([]);
  });

  it("requires accepted_suppressed prior dispositions to carry the suppression reason", () => {
    const baseDisposition = {
      identityKey: "correctness|src/runner.ts:427|accepted by owner",
      status: "accepted_suppressed" as const,
      source: "#427 owner answer",
      scope: "runner review/fix loop",
      boundedReopen: "reopen if the same runner path regresses",
    };

    expect(isValidPriorFindingDisposition(baseDisposition)).toBe(false);
    expect(
      isValidPriorFindingDisposition({
        ...baseDisposition,
        reason: "Owner accepted this bounded risk.",
      }),
    ).toBe(true);
    expect(
      isValidPriorFindingDisposition({
        ...baseDisposition,
        source: "reviewer judgement",
        reason: "Reviewer accepted this bounded risk.",
      }),
    ).toBe(false);
    expect(
      isValidPriorFindingDisposition({
        ...baseDisposition,
        reason: "Owner accepted this bounded risk.",
        boundedReopen: "maybe later",
      }),
    ).toBe(false);
    expect(
      isValidPriorFindingDisposition({
        ...baseDisposition,
        source: { issue: "#427" },
        reason: "Owner accepted this bounded risk.",
      }),
    ).toBe(false);
  });

  it("fails closed when prior dispositions lack sourced accepted-suppression evidence", () => {
    const priorDispositions = [
      {
        identityKey: findingIdentityKey(finding),
        status: "wont_fix" as const,
        reason: "legacy unsourced acceptance",
        severity: "medium" as const,
        reopenAttempts: 0,
        disputeAttempts: 1,
      },
      {
        identityKey: findingIdentityKey({
          ...finding,
          claim_quote: "legacy rejected finding",
        }),
        status: "rejected" as const,
        reason: "legacy unsourced rejection",
        severity: "medium" as const,
        reopenAttempts: 0,
        disputeAttempts: 1,
      },
      {
        identityKey: findingIdentityKey({
          ...finding,
          claim_quote: "incomplete accepted suppression",
        }),
        status: "accepted_suppressed" as const,
        reason: "missing source/scope/bounded reopen",
        severity: "medium" as const,
        reopenAttempts: 0,
        disputeAttempts: 1,
        source: "issue #448",
      },
    ];
    const findings = [
      { ...finding, action: "fix_now" as const },
      {
        ...finding,
        claim_quote: "legacy rejected finding",
        action: "fix_now" as const,
      },
      {
        ...finding,
        claim_quote: "incomplete accepted suppression",
        action: "fix_now" as const,
      },
    ];

    const classification = classifyFindings(findings, priorDispositions);

    expect(classification.blocking).toEqual(findings);
    expect(classification.deferred).toEqual([]);
  });

  it("reopens a suppressed finding on severity upgrade but caps reopen attempts at four", () => {
    const acceptedSuppressionSources = [
      {
        source: "issue #448 acceptance criteria",
        scope: "same finding identity",
        reason: "previously accepted risk",
        findingIdentity: findingIdentityKey(finding),
        boundedReopen: "reopen on severity upgrade",
      },
    ];
    const classification = classifyFindings(
      [
        {
          ...finding,
          severity: "high",
          action: "fix_now",
        },
      ],
      [
        {
          identityKey: findingIdentityKey(finding),
          status: "accepted_suppressed",
          reason: "previously accepted risk",
          severity: "medium",
          reopenAttempts: 3,
          source: "issue #448 acceptance criteria",
          scope: "same finding identity",
          boundedReopen: "reopen on severity upgrade",
        },
      ],
      { acceptedSuppressionSources },
    );

    expect(classification.blocking).toHaveLength(1);
    expect(classification.dispositions).toEqual([
      {
        identityKey: findingIdentityKey(finding),
        status: "accepted_suppressed",
        reason: "previously accepted risk",
        severity: "high",
        reopenAttempts: 4,
        source: "issue #448 acceptance criteria",
        scope: "same finding identity",
        boundedReopen: "reopen on severity upgrade",
      },
    ]);

    const capped = classifyFindings(
      [
        {
          ...finding,
          severity: "critical",
          action: "fix_now",
        },
      ],
      classification.dispositions,
      { acceptedSuppressionSources },
    );

    expect(capped.blocking).toEqual([
      {
        ...finding,
        severity: "critical",
        action: "fix_now",
      },
    ]);
    expect(capped.deferred).toEqual([]);
    expect(capped.dispositions[0]?.reopenAttempts).toBe(4);
  });

  it("allows one same-severity dispute of a suppressed finding, then suppresses repeats", () => {
    const acceptedSuppressionSources = [
      {
        source: "issue #448 acceptance criteria",
        scope: "same finding identity",
        reason: "previously accepted risk",
        findingIdentity: findingIdentityKey(finding),
        boundedReopen: "reopen on same-severity dispute once",
      },
    ];
    const disputed = classifyFindings(
      [
        {
          ...finding,
          severity: "medium",
          action: "fix_now",
        },
      ],
      [
        {
          identityKey: findingIdentityKey(finding),
          status: "accepted_suppressed",
          reason: "previously accepted risk",
          severity: "medium",
          reopenAttempts: 0,
          source: "issue #448 acceptance criteria",
          scope: "same finding identity",
          boundedReopen: "reopen on same-severity dispute once",
        },
      ],
      { acceptedSuppressionSources },
    );

    expect(disputed.blocking).toEqual([
      {
        ...finding,
        severity: "medium",
        action: "fix_now",
      },
    ]);
    expect(disputed.dispositions).toEqual([
      {
        identityKey: findingIdentityKey(finding),
        status: "accepted_suppressed",
        reason: "previously accepted risk",
        severity: "medium",
        reopenAttempts: 0,
        source: "issue #448 acceptance criteria",
        scope: "same finding identity",
        boundedReopen: "reopen on same-severity dispute once",
        disputeAttempts: 1,
      },
    ]);

    const repeated = classifyFindings(
      [
        {
          ...finding,
          severity: "medium",
          action: "fix_now",
        },
      ],
      disputed.dispositions,
      { acceptedSuppressionSources },
    );

    expect(repeated.blocking).toEqual([]);
    expect(repeated.deferred).toEqual([]);
    expect(repeated.dispositions).toEqual(disputed.dispositions);
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
      async findResumeState() { return undefined; },
      async cleanResidue() {},
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
      async push() {},
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
      completionSignal: "CODER_STEP_COMPLETE",
      maxIter: 5,
      model: "gpt-5.5",
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
      async findResumeState() { return undefined; },
      async cleanResidue() {},
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
      async push() {},
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
      completionSignal: "CODER_STEP_COMPLETE",
      maxIter: 5,
      model: "gpt-5.5",
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
      async findResumeState() { return undefined; },
      async cleanResidue() {},
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
        return {
          kind: "reviewer",
          findings: [],
          priorFindingDispositions: [
            {
              identityKey: "correctness|src/x.ts:3|verify me",
              status: "verified-closed",
            },
          ],
        };
      },
      async push() {},
      async writeLedger() {},
    };
    const spec: WorkerSpec = {
      id: "S6",
      kind: "reviewer",
      role: "reviewer",
      host: "codex",
      session: "fresh",
      contextRetention: "clean",
      skill: "/code-review",
      promptFile: "reviewer_review.md",
      completionSignal: "REVIEWER_STEP_COMPLETE",
      maxIter: 1,
      model: "gpt-5.5",
      soul: "READ-ONLY",
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
