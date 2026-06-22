/**
 * End-to-end tests for #250: S4 severity+action routing through runOrchestrator.
 *
 * These tests drive the full runner loop with a fake Backend, injecting
 * different reviewer outputs and asserting what the runner does — which step
 * it reaches, whether it pushes, and which Backend calls are made.
 *
 * #254 wired the S5→S6→S4 fix-loop back-edge, so route(S5) no longer throws.
 * These tests now assert the #250 contract under the working loop: a P0/P1 (or
 * fix_now) finding from the initial review (S3) routes to S5 coder_fix — i.e.
 * S5 is dispatched and push is NOT reached during that fix decision. To keep
 * each test focused on the *single* S4 fan-out decision (not multi-round loop
 * mechanics, which #254's fix-loop.test.ts owns), the fake reviewer returns the
 * configured finding once (S3) and then empty (the S6 re-review) so the loop
 * converges to push after exactly one fix round. The #250 assertion stands:
 * "route转S5，不直接push" — S5 ran before any push.
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
  PersistentLedgerEntry,
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

  // #255: fresh-run defaults (this suite tests S4 routing, not resume).
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {
    // no-op
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    this.calls.push(`fetchIssueMeta(${issueNumber})`);
    return {
      number: issueNumber,
      isReadyForAgent: true,
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

  /** Count of reviewer (S3/S6) dispatches so the loop can converge after S3. */
  private reviewerCalls = 0;

  async runStep(spec: StepSpec): Promise<StepOutput> {
    this.calls.push(`runStep(${spec.id}:${spec.role})`);
    this.runStepIds.push(spec.id);
    if (spec.role === "coder") {
      // Both S2 and S5 (fix) return a successful coder output.
      return { kind: "coder", committed: true, commitsAdded: 1 };
    }
    // reviewer (S3 / S6): the *first* review (S3) returns the configured
    // output (the S4 decision under test); any later S6 re-review returns empty
    // so the fix loop converges to push after one round. This keeps each test
    // on the single S4 fan-out decision rather than multi-round loop mechanics
    // (which #254's fix-loop.test.ts covers). Empty findings always approve.
    this.reviewerCalls += 1;
    if (this.reviewerCalls === 1) return this.reviewerOutput;
    return { kind: "reviewer", findings: [] };
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }

  // #249 integration: writeLedger is part of the Backend seam. This suite
  // asserts S4 routing, not ledger persistence, so it is a no-op.
  async writeLedger(
    _entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    // no-op
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
 * S4 routes to S5 when a fix_now finding is present; the #254 fix-loop then
 * runs the fix + S6 re-review and converges to push. Callers that exercise the
 * S5 fix-loop path use `runExpectingS5` below.
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
 * Run the orchestrator expecting the initial review (S3) to route to S5
 * coder_fix (the #250 S4 fan-out under test). With #254's fix loop wired, the
 * fake converges after one fix round (S6 re-review returns empty), so the run
 * succeeds. The surviving #250 invariant: S5 was dispatched, and it ran BEFORE
 * any push — i.e. the finding drove a fix, not a direct S3→S7 push.
 *
 * Returns the backend and the helper-computed "did push happen before S5?"
 * flag so callers can assert fix-before-push without coupling to the now-
 * converging push count.
 */
async function runExpectingS5(reviewerOutput: StepOutput): Promise<{
  backend: ConfigurableBackend;
  result: Awaited<ReturnType<typeof runOrchestrator>>;
}> {
  const backend = new ConfigurableBackend(reviewerOutput);
  const result = await runOrchestrator({ issueNumber: 250, backend });
  return { backend, result };
}

/** True iff S5 was dispatched strictly before the first push in the timeline. */
function s5RanBeforePush(backend: ConfigurableBackend): boolean {
  const s5At = backend.calls.findIndex((c) => c.startsWith("runStep(S5"));
  const pushAt = backend.calls.findIndex((c) => c.startsWith("push("));
  return s5At >= 0 && (pushAt === -1 || s5At < pushAt);
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
  it("critical (P0) finding → S5 dispatched before any push", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("critical", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(s5RanBeforePush(backend)).toBe(true);
  });

  it("high (P1) finding → S5 dispatched before any push", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("high", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(s5RanBeforePush(backend)).toBe(true);
  });

  it("P1 + defer P2/P3 → S5 dispatched (P1 trumps defer list)", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("high", "fix_now"), finding("low", "defer")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(s5RanBeforePush(backend)).toBe(true);
  });
});

// ─── fix_now P2/P3 (no P0/P1) → S5 ─────────────────────────────────────────

describe("runOrchestrator S4 routing — fix_now P2/P3 routes to S5", () => {
  it("medium fix_now → S5 dispatched before any push", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("medium", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(s5RanBeforePush(backend)).toBe(true);
  });

  it("low fix_now → S5 dispatched", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("low", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(s5RanBeforePush(backend)).toBe(true);
  });

  it("clarity fix_now → S5 dispatched", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("clarity", "fix_now")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(s5RanBeforePush(backend)).toBe(true);
  });

  it("mix fix_now + defer P2/P3 (no P0/P1) → S5 dispatched", async () => {
    const { backend } = await runExpectingS5(
      reviewerWith([finding("medium", "fix_now"), finding("low", "defer")]),
    );
    expect(backend.runStepIds).toContain("S5");
    expect(s5RanBeforePush(backend)).toBe(true);
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

// ─── deferredFindings surfaced in RunResult (PRD #244 US#25) ─────────────────

describe("runOrchestrator S4 routing — deferredFindings in RunResult", () => {
  it("defer-only findings → RunResult.deferredFindings contains those entries", async () => {
    const deferMedium = finding("medium", "defer");
    const deferLow = finding("low", "defer");
    const { result } = await runWith(reviewerWith([deferMedium, deferLow]));
    expect(result.status).toBe("success");
    expect(result.deferredFindings).toHaveLength(2);
    expect(result.deferredFindings).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ severity: "medium", action: "defer" }),
        expect.objectContaining({ severity: "low", action: "defer" }),
      ]),
    );
  });

  it("empty findings → deferredFindings is empty array", async () => {
    const { result } = await runWith(reviewerWith([]));
    expect(result.status).toBe("success");
    expect(result.deferredFindings).toEqual([]);
  });

  it("mix of defer + fix_now P2/P3 → routes to S5; defers from the final review surface", async () => {
    // S3: [defer medium, fix_now low] → S4 routes to S5 (fix_now present). The
    // fix runs, then the S6 re-review (this fake's 2nd reviewer call) returns a
    // lone defer-low → converge to push. The #254 contract: deferredFindings
    // reflects the FINAL review before push (S4 re-collects each loop pass), so
    // the surviving defer is the S6 one. The key #250 fact still holds: a
    // fix_now finding routed to S5 (a fix happened, not a direct push).
    const backend = new ConfigurableBackend(
      reviewerWith([finding("medium", "defer"), finding("low", "fix_now")]),
    );
    const result = await runOrchestrator({ issueNumber: 250, backend });

    // S5 was dispatched — S4 routed to fix, not straight to push.
    expect(backend.runStepIds).toContain("S5");
    expect(s5RanBeforePush(backend)).toBe(true);
    // Converged to success after the fix round.
    expect(result.status).toBe("success");
    // The empty S6 re-review carries no defers → deferredFindings empty (it
    // reflects the last review, not an accumulation across rounds).
    expect(result.deferredFindings).toEqual([]);
  });
});
