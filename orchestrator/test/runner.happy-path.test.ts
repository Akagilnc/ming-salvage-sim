import { afterEach, describe, expect, it, vi } from "vitest";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";

/**
 * Happy-path fake Backend: records every call in order, returns canned
 * outputs that drive the runner straight down
 * S0→S1→S2→S3→S4→S7→S8 (ADR 0030: per-slice review is a runner-visible
 * reviewer worker, and S4 is the visible classification boundary).
 *
 *   - S0/S1 read a compliant issue (rfa ∧ no sub-issues ∧ no open blocked_by)
 *     → gate passes.
 *   - S2 build worker → { committed: true, commitsAdded: 1 } (per-slice cmr
 *     already converged inside the worker's own session).
 *   - S7 ship succeeds → S8 handoff(status=success)
 */
class HappyPathBackend implements Backend {
  /** Ordered log of every Backend method invoked (the call timeline). */
  readonly calls: string[] = [];
  /** Ordered log of every agent step actually dispatched to a sandbox. */
  readonly runStepIds: string[] = [];
  /** Vitest mock call-order marker for sandbox dispatch. */
  readonly markRunStep = vi.fn();
  /** Number of times push() was invoked. */
  pushCount = 0;
  /** The single resident worktree handed out (asserts persistence/reuse). */
  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-247",
    base: "main",
    path: "/resident/worktrees/issue-247",
  };

  // #255: fresh-run defaults (this suite is the happy-path regression).
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
      isClosed: false,
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
    this.markRunStep();
    this.calls.push(`runStep(${spec.id}:${spec.role}:${spec.promptFile})`);
    this.runStepIds.push(spec.id);
    if (spec.role === "reviewer") {
      return { kind: "reviewer", findings: [] };
    }
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }

  async push(worktree: WorktreeHandle): Promise<void> {
    this.calls.push(`push(${worktree.branch})`);
    this.pushCount += 1;
  }

  // #249: writeLedger is part of the Backend seam; the happy-path fake is a
  // no-op stub so existing tests keep passing without asserting ledger details.
  async writeLedger(
    _entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    // no-op in the happy-path fake
  }
}

describe("runOrchestrator — happy path skeleton (ADR 0030)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("prints the resolved model route lineup before the first worker dispatch", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const backend = new HappyPathBackend();
    const info = vi.spyOn(console, "info").mockImplementation(() => {});

    await runOrchestrator({ issueNumber: 247, backend });

    expect(info).toHaveBeenCalledWith(
      [
        "[orchestrator] model route lineup",
        "route=normal",
        "coder=gpt-5.5",
        "reviewer=gpt-5.5",
        "coderFix=gpt-5.5",
        "ship=sonnet",
        "merger=opus",
        "cmrCompleteness=opus",
        "cmrCorrectness=opus",
        "cmrReview=[codex:gpt-5.5,claude:opus,agy:agy]",
      ].join("\n"),
    );
    expect(info.mock.invocationCallOrder[0]).toBeLessThan(
      backend.markRunStep.mock.invocationCallOrder[0]!,
    );
  });

  it("runs S0→S1→S2→S7→S8 in order and hands off status=success", async () => {
    const backend = new HappyPathBackend();

    const result = await runOrchestrator({ issueNumber: 247, backend });

    // Final state: success handoff pointing at the pushed resident branch.
    expect(result.status).toBe("success");
    expect(result.branch).toBe("feat/orchestrator/issue-247");

    // Exactly one push, no PR / no merge (the fake exposes neither — proving
    // the runner never reaches for those actions).
    expect(backend.pushCount).toBe(1);

    // The step ledger records the runner's decisions in canonical order —
    // S3 is the fresh full-diff reviewer and S4 records the runner classification.
    expect(result.stepLedger.map((e) => e.step)).toEqual([
      "S0",
      "S1",
      "S2",
      "S3",
      "S4",
      "S7",
      "S8",
    ]);
  });

  it("dispatches implementation and review steps to the sandbox", async () => {
    const backend = new HappyPathBackend();

    await runOrchestrator({ issueNumber: 247, backend });

    // S4/S7/S8 are runner/ship boundaries; S2 and S3 are agent workers.
    expect(backend.runStepIds).toEqual(["S2", "S3"]);
  });

  it("calls Backend actions in the canonical S0→S8 sequence", async () => {
    const backend = new HappyPathBackend();

    await runOrchestrator({ issueNumber: 247, backend });

    expect(backend.calls).toEqual([
      "fetchIssueMeta(247)", // S0 input_gate (lightweight metadata)
      "fetchIssueSnapshot(247)", // S1 load_context (full snapshot)
      "prepareWorktree(247, main)", // S1 resident worktree, base=main
      "writeSnapshot(feat/orchestrator/issue-247, #247)", // S1 clean-room snapshot
      "runStep(S2:coder:coder_implement.md)", // S2 implementation
      "runStep(S3:reviewer:reviewer_review.md)", // S3 fresh full-diff review
      // S4 classify, S7 ship, S8 handoff below — S4/S8 are pure TS.
      "push(feat/orchestrator/issue-247)", // S7 ship
    ]);
  });

  it("the build output is {committed,commitsAdded} and a committed build routes to ship", async () => {
    const backend = new HappyPathBackend();

    const result = await runOrchestrator({ issueNumber: 247, backend });

    // The ledger captures the structured S2 output route() consumed.
    const s2 = result.stepLedger.find((e) => e.step === "S2");
    expect(s2?.output).toEqual({ kind: "coder", committed: true, commitsAdded: 1 });

    // A committed build plus clean independent review → ship reached, success.
    expect(result.status).toBe("success");
    expect(backend.pushCount).toBe(1);
  });

  it("only takes an issue number as input and uses versioned promptFiles (no ad-hoc prompts)", async () => {
    const backend = new HappyPathBackend();

    await runOrchestrator({ issueNumber: 247, backend });

    // The single agent step dispatched a fixed, versioned promptFile (recorded
    // in the call log) — no step assembled an inline prompt string.
    const runCalls = backend.calls.filter((c) => c.startsWith("runStep("));
    expect(runCalls).toEqual([
      "runStep(S2:coder:coder_implement.md)",
      "runStep(S3:reviewer:reviewer_review.md)",
    ]);
  });

  it("commits accumulate on a single resident worktree/branch (base=main), not a throwaway sandbox", async () => {
    const backend = new HappyPathBackend();

    const result = await runOrchestrator({ issueNumber: 247, backend });

    // prepareWorktree was called exactly once → one resident worktree reused
    // across the whole run; its base is main; the pushed branch is that same
    // resident branch.
    const prepareCalls = backend.calls.filter((c) =>
      c.startsWith("prepareWorktree("),
    );
    expect(prepareCalls).toEqual(["prepareWorktree(247, main)"]);
    expect(result.branch).toBe(backend.worktree.branch);
  });
});
