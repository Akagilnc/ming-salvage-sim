import { describe, expect, it } from "vitest";
import { classifyFindings, findingIdentityKey } from "../src/findings.js";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
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
  reviewerAttempts = 0;

  constructor(private readonly reviewerResults: ReadonlyArray<WorkerResult>) {}

  async findResumeState(): Promise<undefined> {
    return undefined;
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
  async writeLedger(_entry: PersistentLedgerEntry, _stateDir: string): Promise<void> {}

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
      { kind: "malformed", reason: "missing <reviewer> tag" },
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
      { kind: "completed", output: { kind: "reviewer", findings: [] } },
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
});
