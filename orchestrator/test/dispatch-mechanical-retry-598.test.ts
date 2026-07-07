/**
 * #598 — generic mechanical retry MECHANISM (`withMechanicalRetry`).
 *
 * These tests validate the retry mechanism in isolation, at its own seam
 * (`withMechanicalRetry(spec, ctx, dispatch)`), NOT yet wired into
 * `dispatchWorker` / `dispatchFamilyWorker`. Placement relative to the two
 * existing semantic-retry layers (reviewer `MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS`
 * in runner.ts, CMR `OUTCOME_REWRITE_RETRY_CAP` in verifyCmr.ts) is a composition
 * decision the wiring step must get right — a naive innermost placement
 * double-counts those budgets and swallows throws they own. See #598 acceptance
 * "the generic layer firing only after those run".
 *
 * The mechanism reads ONLY the outcome discriminant (`result.kind`) — never
 * worker-reported content. A process-level failure
 * (`failed`/`malformed`/`outcome_protocol_failure` or a thrown exception) retries
 * with a FRESH (non-resume) session for the same step, up to MAX_DISPATCH_ATTEMPTS;
 * a judged `completed`/`escalated` passes through with ZERO retry; bounded
 * exhaustion returns the last failure (runner function (a), #604).
 */

import { describe, expect, it } from "vitest";
import { MAX_DISPATCH_ATTEMPTS, withMechanicalRetry } from "../src/dispatchRetry.js";
import { runOrchestrator } from "../src/runner.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";

function coderSpec(session: WorkerSpec["session"] = "fresh"): WorkerSpec {
  return {
    id: "S2",
    kind: "coder",
    role: "coder",
    host: "claude",
    session,
    contextRetention: "retain",
    skill: "tdd",
    promptFile: "prompts/coder.md",
    completionSignal: "<done>",
    maxIter: 3,
    model: "opus",
    soul: "coder",
    toolchain: [],
  };
}

const COMPLETED: WorkerResult = {
  kind: "completed",
  output: { kind: "coder", committed: true, commitsAdded: 1 },
};

/** A dispatch fn that returns the next scripted result per call (or throws an Error entry). */
function scripted(script: ReadonlyArray<WorkerResult | Error>): {
  dispatch: (spec: WorkerSpec, ctx: DispatchContext) => Promise<WorkerResult>;
  seen: Array<{ spec: WorkerSpec; ctx: DispatchContext }>;
} {
  const seen: Array<{ spec: WorkerSpec; ctx: DispatchContext }> = [];
  let i = 0;
  return {
    seen,
    dispatch: async (spec, ctx) => {
      seen.push({ spec, ctx });
      const step = script[Math.min(i, script.length - 1)];
      i += 1;
      if (step instanceof Error) throw step;
      return step;
    },
  };
}

describe("#598 withMechanicalRetry", () => {
  it("a returned `failed` on attempt 1 then `completed` on attempt 2 → completed, dispatched twice", async () => {
    const { dispatch, seen } = scripted([
      { kind: "failed", reason: "worker crashed mid-run" },
      COMPLETED,
    ]);
    const result = await withMechanicalRetry(coderSpec(), { }, dispatch);
    expect(result.kind).toBe("completed");
    expect(seen).toHaveLength(2);
  });

  it("`completed` on attempt 1 → returned as-is with ZERO retry (one dispatch)", async () => {
    const { dispatch, seen } = scripted([COMPLETED, COMPLETED]);
    const result = await withMechanicalRetry(coderSpec(), {}, dispatch);
    expect(result.kind).toBe("completed");
    expect(seen).toHaveLength(1);
  });

  it("`escalated` (a JUDGED signal) on attempt 1 → passed through with ZERO retry", async () => {
    const escalated: WorkerResult = {
      kind: "escalated",
      escalation: { reason: "design decision needed", diagnosis: "human must rule" },
    };
    const { dispatch, seen } = scripted([escalated, COMPLETED]);
    const result = await withMechanicalRetry(coderSpec(), {}, dispatch);
    expect(result.kind).toBe("escalated");
    expect(seen).toHaveLength(1);
  });

  it("a THROWN exception on attempt 1 then `completed` → treated as failure and retried", async () => {
    const { dispatch, seen } = scripted([
      new Error("connection dropped mid-dispatch"),
      COMPLETED,
    ]);
    const result = await withMechanicalRetry(coderSpec(), {}, dispatch);
    expect(result.kind).toBe("completed");
    expect(seen).toHaveLength(2);
  });

  it("persistent process failure → durably returns the failure after the bounded attempts", async () => {
    const { dispatch, seen } = scripted([{ kind: "malformed", reason: "no completion signal" }]);
    const result = await withMechanicalRetry(coderSpec(), {}, dispatch);
    expect(result.kind).toBe("malformed");
    expect(seen).toHaveLength(MAX_DISPATCH_ATTEMPTS);
  });

  it("a retry originating from a RESUME dispatch is forced fresh (resume id stripped)", async () => {
    const { dispatch, seen } = scripted([
      { kind: "outcome_protocol_failure", reason: "no signal", attempts: 1 },
      COMPLETED,
    ]);
    const ctx: DispatchContext = { resumeSessionId: "sess-abc" };
    const result = await withMechanicalRetry(coderSpec("resume"), ctx, dispatch);

    expect(result.kind).toBe("completed");
    expect(seen).toHaveLength(2);
    // Attempt 1 kept the resume id + resume session mode.
    expect(seen[0]!.ctx.resumeSessionId).toBe("sess-abc");
    expect(seen[0]!.spec.session).toBe("resume");
    // The RETRY stripped the resume id and forced a fresh session.
    expect(seen[1]!.ctx.resumeSessionId).toBeUndefined();
    expect(seen[1]!.spec.session).toBe("fresh");
  });

  it("callerOwns re-throws a caller-owned thrown error instead of retrying it", async () => {
    let calls = 0;
    const dispatch = async (): Promise<WorkerResult> => {
      calls += 1;
      throw new Error("reviewer structured output error");
    };
    await expect(
      withMechanicalRetry(coderSpec(), {}, dispatch, {
        callerOwns: (o) => o.kind === "thrown",
      }),
    ).rejects.toThrow("reviewer structured output error");
    // Deferred to the caller on the FIRST attempt — never retried here.
    expect(calls).toBe(1);
  });

  it("callerOwns returns a caller-owned process-failure result without retrying", async () => {
    const { dispatch, seen } = scripted([{ kind: "malformed", reason: "reviewer output invalid" }]);
    const result = await withMechanicalRetry(coderSpec(), {}, dispatch, {
      callerOwns: (o) => "result" in o && o.result.kind === "malformed",
    });
    expect(result.kind).toBe("malformed");
    // Deferred to the caller's own bounded loop — one dispatch, no generic retry.
    expect(seen).toHaveLength(1);
  });
});

// ── #598 integration: coder/ship inherit the generic retry (the #592 asymmetry) ──

const RUN_WORKTREE: WorktreeHandle = {
  branch: "feat/issue-598",
  base: "main",
  path: "/resident/worktrees/issue-598",
};

/**
 * A runOrchestrator backend where the S2 coder dispatch fails (a process-level
 * crash) `coderFailures` times before completing; every other worker completes
 * cleanly. Counts coder dispatches so the test can assert a retry happened.
 */
class CoderCrashBackend implements Backend {
  coderDispatches = 0;
  constructor(private readonly coderFailures: number) {}

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
  async resumeSession(): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async fetchIssueMeta(n: number): Promise<IssueMeta> {
    return { number: n, isReadyForAgent: true, hasSubIssues: false, isClosed: false, openBlockedBy: [] };
  }
  async fetchIssueSnapshot(n: number): Promise<IssueSnapshot> {
    return { number: n, body: "body", comments: [], agentBrief: "" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return RUN_WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(): Promise<StepOutput> {
    return { kind: "coder", committed: true, commitsAdded: 1 };
  }
  async push(): Promise<void> {}
  async writeLedger(): Promise<void> {}

  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    if (spec.kind === "coder" && spec.id === "S2") {
      this.coderDispatches += 1;
      if (this.coderDispatches <= this.coderFailures) {
        return { kind: "failed", reason: "coder container crashed mid-run" };
      }
      return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
    }
    if (spec.kind === "reviewer") {
      return { kind: "completed", output: { kind: "reviewer", findings: [] } };
    }
    if (spec.kind === "ship") {
      return { kind: "completed", output: { kind: "ship", branch: RUN_WORKTREE.branch, status: "pushed" } };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

describe("#598 integration — a coder (S2) process crash retries fresh (the #592 asymmetry)", () => {
  it("a coder that crashes once then succeeds no longer aborts the run — S2 dispatched twice", async () => {
    const backend = new CoderCrashBackend(1);
    const result = await runOrchestrator({ issueNumber: 598, backend });
    // Before #598 a single coder crash durably aborted (zero retry). Now it retries.
    expect(result.status).not.toBe("error");
    expect(backend.coderDispatches).toBe(2);
  });
});
