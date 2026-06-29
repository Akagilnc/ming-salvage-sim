import { describe, expect, it } from "vitest";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { legacyDispatchWorker } from "../src/dispatchWorker.js";
import {
  adjudicatePriorClaimedFixedFindings,
  classifyFindings,
  findingIdentityKey,
} from "../src/findings.js";
import { route } from "../src/route.js";
import { runOrchestrator } from "../src/runner.js";
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
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-369",
  base: "main",
  path: "/resident/worktrees/issue-369",
};

class RetryReviewBackend implements Backend {
  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  reviewerAttempts = 0;

  constructor(
    private readonly reviewerResults: ReadonlyArray<WorkerResult>,
    private readonly resumeState?: ResumeState,
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
    return WORKTREE;
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

  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
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
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
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
    expect(backend.ctxs[s5Index]?.blockingFindings).toEqual([finding]);
    expect(backend.ctxs[s5Index]?.blockingFindingIdentityKeys).toEqual([
      "correctness|src/runner.ts:1|fix worker needs structured finding data",
    ]);
  });

  it("preserves deferred findings across blocking fix rounds", async () => {
    const blocking: Finding = {
      severity: "high",
      category: "Correctness",
      claim_quote: "must fix before shipping",
      location: "src/runner.ts:10",
      suggested_fix: "fix it",
      action: "fix_now",
    };
    const deferred: Finding = {
      severity: "medium",
      category: "Follow-up",
      claim_quote: "track this later",
      location: "src/runner.ts:11",
      suggested_fix: "file follow-up",
      action: "defer",
    };
    const backend = new RetryReviewBackend([
      { kind: "completed", output: { kind: "reviewer", findings: [blocking, deferred] } },
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
          ],
        },
      },
    ]);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(result.deferredFindings).toEqual([deferred]);
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

  it("fails closed when a still-active prior key has no finding payload", () => {
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
    ).toThrow(/no active or prior finding payload/);
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
    expect(backend.ctxs[s6Index]?.blockingFindings).toEqual([blocking]);
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
          findings: [{ ...acceptedRisk, action: "fix_now" }],
          priorFindingDispositions: [
            { identityKey: blockingKey, status: "verified-closed" },
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
    ]);
    const firstS4Write = backend.ledgerWrites.find((entry) => entry.step === "S4");
    expect(firstS4Write?.findingDispositions).toEqual([
      {
        identityKey:
          "correctness|src/runner.ts:736|accepted risk remains same severity",
        status: "wont_fix",
        reason: "Accepted as out of scope for this slice",
        severity: "medium",
        reopenAttempts: 0,
      },
    ]);
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
    expect(backend.ctxs[s5Index]?.blockingFindings).toEqual([finding]);
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
    expect(backend.ctxs[s5Index]?.blockingFindings).toEqual([finding]);
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
    ]);
    expect(backend.ctxs[0]?.blockingFindings).toEqual([finding]);
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
    const acceptedRisk: Finding = {
      severity: "medium",
      category: "Correctness",
      claim_quote: "accepted risk survives resume",
      location: "src/runner.ts:971",
      suggested_fix: "do not reopen at the same severity",
      action: "wont_fix",
      disposition_reason: "Accepted outside this slice",
    };
    const acceptedRiskKey =
      "correctness|src/runner.ts:971|accepted risk survives resume";
    const acceptedRiskDisposition = {
      identityKey: acceptedRiskKey,
      status: "wont_fix" as const,
      reason: "Accepted outside this slice",
      severity: "medium" as const,
      reopenAttempts: 0,
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
            findings: [{ ...acceptedRisk, action: "fix_now" }],
            priorFindingDispositions: [
              { identityKey: blockingKey, status: "verified-closed" },
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
    ]);
  });

  it("rebuilds deferred findings when re-feeding a terminal resumed run", async () => {
    const deferred: Finding = {
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
        { step: "S3", output: { kind: "reviewer", findings: [deferred] } },
        { step: "S4" },
        { step: "S7" },
        { step: "S8", handoffStatus: "success" },
      ] as ReadonlyArray<PersistentLedgerEntry>,
    };
    const backend = new RetryReviewBackend([], resumeState);

    const result = await runOrchestrator({ issueNumber: 369, backend });

    expect(result.status).toBe("success");
    expect(result.deferredFindings).toEqual([deferred]);
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

  it("preserves generic reviewer backend exceptions as S8 errors without retrying", async () => {
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
    expect(backend.reviewerAttempts).toBe(1);
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

  it("classifies blocking findings and exposes their identity keys together", () => {
    const classification = classifyFindings([finding]);

    expect(classification.blocking).toEqual([finding]);
    expect(classification.deferred).toEqual([]);
    expect(classification.blockingIdentityKeys).toEqual([
      "correctness|src/runner.ts:120|missing full diff review",
    ]);
  });

  it("persists wont-fix and rejected dispositions with identity and rationale", () => {
    const classification = classifyFindings([
      {
        ...finding,
        action: "wont_fix",
        disposition_reason: "Accepted as outside this slice",
      },
      {
        ...finding,
        claim_quote: "  Already covered by existing invariant ",
        action: "rejected",
        disposition_reason: "The claim is false on the current full diff",
      },
    ]);

    expect(classification.deferred).toEqual([]);
    expect(classification.dispositions).toEqual([
      {
        identityKey: "correctness|src/runner.ts:120|missing full diff review",
        status: "wont_fix",
        reason: "Accepted as outside this slice",
        severity: "medium",
        reopenAttempts: 0,
      },
      {
        identityKey:
          "correctness|src/runner.ts:120|already covered by existing invariant",
        status: "rejected",
        reason: "The claim is false on the current full diff",
        severity: "medium",
        reopenAttempts: 0,
      },
    ]);
  });

  it("reopens a suppressed finding on severity upgrade but caps reopen attempts at four", () => {
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
          status: "wont_fix",
          reason: "previously accepted risk",
          severity: "medium",
          reopenAttempts: 3,
        },
      ],
    );

    expect(classification.blocking).toHaveLength(1);
    expect(classification.dispositions).toEqual([
      {
        identityKey: findingIdentityKey(finding),
        status: "wont_fix",
        reason: "previously accepted risk",
        severity: "high",
        reopenAttempts: 4,
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
          status: "wont_fix",
          reason: "previously accepted risk",
          severity: "medium",
          reopenAttempts: 0,
        },
      ],
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
        status: "wont_fix",
        reason: "previously accepted risk",
        severity: "medium",
        reopenAttempts: 0,
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

    const result = await legacyDispatchWorker(backend, spec, {
      worktree,
      stateDir,
      blockingFindings: [finding],
      blockingFindingIdentityKeys: ["correctness|src/x.ts:1|fix me"],
    });

    expect(result.kind).toBe("completed");
    expect(observedLanding).toEqual({
      blockingFindings: [finding],
      blockingFindingIdentityKeys: ["correctness|src/x.ts:1|fix me"],
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

    await legacyDispatchWorker(backend, spec, {
      worktree,
      stateDir,
      blockingFindings: [finding],
      blockingFindingIdentityKeys: ["correctness|src/x.ts:2|mount me"],
    });

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
      skill: "/review",
      promptFile: "reviewer_review.md",
      completionSignal: "REVIEWER_STEP_COMPLETE",
      maxIter: 1,
      model: "gpt-5.5",
      soul: "READ-ONLY",
      toolchain: [],
    };

    await legacyDispatchWorker(backend, spec, {
      worktree,
      stateDir,
      blockingFindings: [finding],
      blockingFindingIdentityKeys: ["correctness|src/x.ts:3|verify me"],
    });

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
