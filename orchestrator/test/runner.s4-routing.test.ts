/**
 * End-to-end tests for #250: S4 severity+action routing through runOrchestrator.
 *
 * These tests drive the full runner loop with a fake Backend, injecting
 * different reviewer outputs and asserting what the runner does — which step
 * it reaches, whether it pushes, and which Backend calls are made.
 *
 * S5/S6 fix-loop edges are owned by #254; when route() is asked to leave S5,
 * it throws (the seam is labelled — that's expected). These tests assert the
 * runner *reaches* S5 (via Backend.runStep being called with S5) before the
 * unimplemented route(S5) throws. That is the #250 acceptance criterion:
 * "route转S5，不直接push".
 *
 * Regression: the happy-path (empty findings) must still reach push → success.
 */

import { describe, expect, it } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  Finding,
  IssueMeta,
  IssueSnapshot,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

// ─── Base fake backend ────────────────────────────────────────────────────────

/** Configurable fake: caller provides the reviewer output to return for S3/S6. */
class ConfigurableBackend implements Backend {
  readonly calls: string[] = [];
  readonly runStepIds: string[] = [];
  pushCount = 0;

  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-250",
    base: "main",
    path: "/resident/worktrees/issue-250",
  };

  constructor(
    /** Reviewer output to inject when S3 runs. */
    private readonly reviewerOutput: StepOutput,
  ) {}

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.calls.push(`fetchIssueMeta(${issueNumber})`);
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasAgentBrief: true,
      hasSubIssues: false,
      openBlockedBy: [],
    };
  }

  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    this.calls.push(`fetchIssueSnapshot(${issueNumber})`);
    return {
      number: issueNumber,
      body: "issue body",
      comments: [],
      agentBrief: "## Agent Brief\nimplement the thing",
    };
  }

  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    this.calls.push(`prepareWorktree(${issueNumber}, ${base})`);
    return this.worktree;
  }

  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    this.calls.push(`writeSnapshot(${worktree.branch}, #${snapshot.number})`);
  }

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id}:${spec.role})`);
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      // Both S2 and S5 (fix stub) return a successful coder output.
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    // reviewer (S3 / S6)
    return this.reviewerOutput;
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }
}

// ─── helpers ──────────────────────────────────────────────────────────────────

function finding(
  severity: Finding["severity"],
  action: Finding["action"],
): Finding {
  return {
    severity,
    action,
    category: "test",
    claim_quote: "some quote",
    location: "src/foo.ts:1",
    suggested_fix: "fix it",
  };
}

function reviewerWith(findings: Finding[]): StepOutput {
  return { kind: "reviewer", findings };
}

/**
 * Run the orchestrator with the given reviewer output.
 * Returns { backend } so callers can inspect calls/runStepIds.
 *
 * When S4 routes to S5, route(S5) will throw (fix-loop is #254 scope).
 * Callers that expect S5 routing should use `runExpectingS5` below.
 */
async function runWith(reviewerOutput: StepOutput): Promise<{
  backend: ConfigurableBackend;
  result: Awaited<ReturnType<typeof runOrchestrator>>;
}> {
  const backend = new ConfigurableBackend(reviewerOutput);
  const result = await runOrchestrator({ issueNumber: 250, backend });
  return { backend, result };
}

/**
 * Run the orchestrator expecting it to route to S5 and then throw (because
 * the S5 exit-edge is #254 scope). Returns the backend so callers can assert
 * on runStepIds to confirm S5 was dispatched.
 */
async function runExpectingS5(reviewerOutput: StepOutput): Promise<{
  backend: ConfigurableBackend;
}> {
  const backend = new ConfigurableBackend(reviewerOutput);
  await expect(
    runOrchestrator({ issueNumber: 250, backend }),
  ).rejects.toThrow(/fix loop = #254/);
  return { backend };
}

// ─── Regression: empty findings → push ───────────────────────────────────────

describe("runOrchestrator S4 routing — empty findings regression", () => {
  it("empty findings → push reached, status=success (slice #247 contract intact)", async () => {
    const { backend, result } = await runWith(reviewerWith([]));
    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
    // S5 must NOT be reached
    expect(backend.runStepIds).not.toContain("S5");
  });
});

// ─── P0/P1 present → S5 (not push) ──────────────────────────────────────────

describe("runOrchestrator S4 routing — P0/P1 routes to S5", () => {
  it("critical (P0) finding → S5 dispatched, push NOT reached", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("critical", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(backend.pushCount).toBe(0);
  });

  it("high (P1) finding → S5 dispatched, push NOT reached", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("high", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(backend.pushCount).toBe(0);
  });

  it("P1 + defer P2/P3 → S5 dispatched (P1 trumps defer list)", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("high", "fix_now"), finding("low", "defer")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(backend.pushCount).toBe(0);
  });
});

// ─── fix_now P2/P3 (no P0/P1) → S5 ─────────────────────────────────────────

describe("runOrchestrator S4 routing — fix_now P2/P3 routes to S5", () => {
  it("medium fix_now → S5 dispatched, push NOT reached", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("medium", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(backend.pushCount).toBe(0);
  });

  it("low fix_now → S5 dispatched", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("low", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(backend.pushCount).toBe(0);
  });

  it("clarity fix_now → S5 dispatched", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("clarity", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(backend.pushCount).toBe(0);
  });

  it("mix fix_now + defer P2/P3 (no P0/P1) → S5 dispatched", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("medium", "fix_now"), finding("low", "defer")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(backend.pushCount).toBe(0);
  });
});

// ─── defer-only P2/P3 → S7 push (not blocked) ───────────────────────────────

describe("runOrchestrator S4 routing — defer-only does not block push", () => {
  it("single medium defer → status=success, S5 NOT reached", async () => {
    const { backend, result } = await runWith(
      reviewerWith([finding("medium", "defer")]),
    );
    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
    expect(backend.runStepIds).not.toContain("S5");
  });

  it("multiple defer-only (medium+low+clarity) → push, S5 NOT reached", async () => {
    const { backend, result } = await runWith(
      reviewerWith([
        finding("medium", "defer"),
        finding("low", "defer"),
        finding("clarity", "defer"),
      ]),
    );
    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
    expect(backend.runStepIds).not.toContain("S5");
  });
});

// ─── Routing is deterministic (runner reads JSON, not agent intent) ───────────

describe("runOrchestrator S4 routing — determinism", () => {
  it("same findings → same route outcome on every call", async () => {
    // First run: defer → success
    const run1 = await runWith(reviewerWith([finding("low", "defer")]));
    expect(run1.result.status).toBe("success");

    // Second run with same findings: also defer → success
    const run2 = await runWith(reviewerWith([finding("low", "defer")]));
    expect(run2.result.status).toBe("success");
  });
});
