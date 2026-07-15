/**
 * #598 — generic mechanical retry MECHANISM (`withMechanicalRetry`).
 *
 * These tests validate the process-failure retry mechanism at its own seam
 * (`withMechanicalRetry(spec, ctx, dispatch)`). Under ADR 0131, completed worker
 * cargo never enters a retry budget; only a failed result or thrown process
 * exception may trigger this bounded mechanical retry.
 *
 * The mechanism reads ONLY the outcome discriminant (`result.kind`) — never
 * worker-reported content. A process-level failure
 * (`failed` or a thrown process exception) retries with a FRESH (non-resume)
 * session for the same step, up to MAX_DISPATCH_ATTEMPTS. Unusable reviewer
 * receipts are caller-owned decisions; coder receipt content never enters this
 * budget. A `completed`/`escalated` result passes through with ZERO retry; bounded
 * exhaustion returns the last failure (runner function (a), #604).
 */

import { describe, expect, it } from "vitest";
import {
  MAX_DISPATCH_ATTEMPTS,
  retryProcessCrash,
  withMechanicalRetry,
} from "../../src/dispatchRetry.js";
import { MAX_LEG_TRANSIENT_ATTEMPTS } from "../../src/legTransientRetry.js";
import { QuotaWaitForResetError } from "../../src/quotaProbe.js";
import { isCapacityRelayError } from "../../src/relayDispatch.js";
import { runOrchestrator } from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
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
} from "../../src/types.js";

function quotaWaitError(): QuotaWaitForResetError {
  const resetAt = new Date("2026-07-08T16:10:00.000Z");
  return new QuotaWaitForResetError({
    disposition: {
      kind: "wait_for_reset",
      pool: "zai",
      resetAt,
      reason: "quota limited (429); wait for reset",
    },
    applied: {
      killed: false,
      ledgerEntry: {
        event: "quota_wait_for_reset",
        pool: "zai",
        resetAt: resetAt.toISOString(),
        reason: "quota limited (429); wait for reset",
        step: "S1",
        workerPid: 0,
        ts: "2026-07-08T12:00:00.000Z",
      },
    },
    pool: "zai",
    probe: { kind: "quota_limited", resetAt, detail: "429" },
  });
}

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
  it("backs off for 5s then 15s before transient process-failure retries", async () => {
    const delays: number[] = [];
    let attempt = 0;
    const dispatch = async () => {
      attempt++;
      if (attempt === 1) return { kind: "failed", reason: "provider blip" } as const;
      if (attempt === 2) return { kind: "failed", reason: "spawn failure" } as const;
      return COMPLETED;
    };

    const result = await withMechanicalRetry(coderSpec(), {}, dispatch, {
      sleepMs: async (ms) => {
        delays.push(ms);
      },
    });

    expect(result).toEqual(COMPLETED);
    expect(delays).toEqual([5_000, 15_000]);
  });

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

  it("an at-capacity failure bypasses mechanical retry so relay can change checkpoints", async () => {
    const { dispatch, seen } = scripted([
      { kind: "failed", reason: "Selected model is at capacity" },
      COMPLETED,
    ]);
    await expect(withMechanicalRetry(coderSpec(), {}, dispatch)).rejects.toSatisfy(
      isCapacityRelayError,
    );
    expect(seen).toHaveLength(1);
  });

  it("ordinary 503 and non-model capacity failures stay on the mechanical retry path", async () => {
    for (const reason of [
      "HTTP 503 service overloaded",
      "worker queue is at capacity",
    ]) {
      const { dispatch, seen } = scripted([
        { kind: "failed", reason },
        COMPLETED,
      ]);
      await expect(withMechanicalRetry(coderSpec(), {}, dispatch)).resolves.toEqual(
        COMPLETED,
      );
      expect(seen).toHaveLength(2);
    }
  });

  it("callerOwns re-throws a caller-owned thrown error instead of retrying it", async () => {
    let calls = 0;
    const dispatch = async (): Promise<WorkerResult> => {
      calls += 1;
      throw new Error("reviewer structured output error");
    };
    await expect(
      withMechanicalRetry(coderSpec(), {}, dispatch, {
        callerOwns: (o) => "kind" in o && o.kind === "thrown",
      }),
    ).rejects.toThrow("reviewer structured output error");
    // Deferred to the caller on the FIRST attempt — never retried here.
    expect(calls).toBe(1);
  });

  it("#909: QuotaWaitForResetError is rethrown without burning mechanical attempts", async () => {
    let calls = 0;
    const dispatch = async (): Promise<WorkerResult> => {
      calls += 1;
      throw quotaWaitError();
    };
    await expect(withMechanicalRetry(coderSpec(), {}, dispatch)).rejects.toBeInstanceOf(
      QuotaWaitForResetError,
    );
    expect(calls).toBe(1);
  });
});

describe("#909 retryProcessCrash must not thrash on quota wait", () => {
  it("QuotaWaitForResetError rethrows on first attempt (no mechanical retry)", async () => {
    let calls = 0;
    let resets = 0;
    await expect(
      retryProcessCrash(
        async () => {
          calls += 1;
          throw quotaWaitError();
        },
        {
          maxAttempts: MAX_DISPATCH_ATTEMPTS,
          resetBeforeRetry: async () => {
            resets += 1;
          },
        },
      ),
    ).rejects.toBeInstanceOf(QuotaWaitForResetError);
    expect(calls).toBe(1);
    expect(resets).toBe(0);
  });

  it("ordinary process crash still retries up to the bound", async () => {
    let calls = 0;
    await expect(
      retryProcessCrash(async () => {
        calls += 1;
        throw new Error("merger agent crashed mid-resolve");
      }),
    ).rejects.toThrow(/after 3 dispatch attempts/);
    expect(calls).toBe(MAX_DISPATCH_ATTEMPTS);
  });
});

// ── #598 integration: coder/ship inherit process-failure retry ──

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
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  coderDispatches = 0;
  constructor(private readonly coderFailures: number) {}

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
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
  async writeLedger(): Promise<void> {}

  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    // #919: S3/S6 seats are role/kind "verify" but court traffic is T2
    // kind:"judge". Skeleton verify cargo is family role-outcome only — must
    // not short-circuit single-slice judge seats before the judge fixture.
    if (spec.id === "S3" || spec.id === "S6") {
      return { kind: "completed", output: { kind: "judge", status: "converged" } };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    if (spec.kind === "coder" && spec.id === "S2") {
      this.coderDispatches += 1;
      if (this.coderDispatches <= this.coderFailures) {
        return { kind: "failed", reason: "coder container crashed mid-run" };
      }
      return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
    }
    if (spec.kind === "reviewer") {
      return { kind: "completed", output: { kind: "judge", status: "converged" } };
    }
    if (spec.kind === "ship") {
      return { kind: "completed", output: { kind: "ship", branch: RUN_WORKTREE.branch, status: "pushed" } };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

describe("#598 integration — a coder (S2) process crash retries fresh", () => {
  it("a coder that crashes once then succeeds no longer aborts the run — S2 dispatched twice", async () => {
    const backend = new CoderCrashBackend(1);
    const result = await runOrchestrator({ issueNumber: 598, backend });
    // Before #598 a single coder crash durably aborted (zero retry). Now it retries.
    expect(result.status).not.toBe("error");
    expect(backend.coderDispatches).toBe(2);
  });
});

/**
 * A backend whose S3 reviewer dispatch THROWS a non-structured crash (a container/
 * connection failure) `reviewerFailures` times before completing; everything else
 * completes. The reviewer's own structured-output loop does NOT own a non-structured
 * crash, so the generic layer retries it (#598 replay: connection drops recover).
 */
class ReviewerCrashBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  reviewerDispatches = 0;
  constructor(private readonly reviewerFailures: number) {}

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
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
  async writeLedger(): Promise<void> {}

  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    // #919: single-slice judge seats (S3/S6) use role/kind "verify" but must
    // return T2 kind:"judge" traffic — not skeleton family verify cargo.
    if (spec.id === "S3" || spec.id === "S6" || spec.kind === "reviewer") {
      this.reviewerDispatches += 1;
      if (this.reviewerDispatches <= this.reviewerFailures) {
        throw new Error("reviewer container connection dropped mid-run");
      }
      return { kind: "completed", output: { kind: "judge", status: "converged" } };
    }
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    if (spec.kind === "ship") {
      return { kind: "completed", output: { kind: "ship", branch: RUN_WORKTREE.branch, status: "pushed" } };
    }
    return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
  }
}

describe("#598 integration — a transient reviewer non-structured crash recovers (replay)", () => {
  it("a reviewer whose container drops once then succeeds does not abort — the run proceeds", async () => {
    const backend = new ReviewerCrashBackend(1);
    const result = await runOrchestrator({ issueNumber: 598, backend });
    // A transient reviewer connection drop is retried instead of aborting on the
    // first crash; the run proceeds past S3.
    expect(result.status).not.toBe("error");
    expect(backend.reviewerDispatches).toBeGreaterThanOrEqual(2);
  });

  it("a coder whose worker IDLE-TIMES-OUT once then succeeds recovers (replay: idle timeout)", async () => {
    // #598 replay criterion names idle-timeout alongside connection-drop. An idle
    // timeout surfaces as a thrown crash from the dispatch — retried fresh.
    class IdleTimeoutCoderBackend extends CoderCrashBackend {
      constructor() {
        super(0);
      }
      private idleLeft = 1;
      override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "coder" && spec.id === "S2") {
          this.coderDispatches += 1;
          if (this.idleLeft > 0) {
            this.idleLeft -= 1;
            throw new Error("worker exceeded idle timeout (no output for 600s)");
          }
          return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } };
        }
        return super.dispatchWorker(spec);
      }
    }
    const backend = new IdleTimeoutCoderBackend();
    const result = await runOrchestrator({ issueNumber: 598, backend });
    expect(result.status).not.toBe("error");
    expect(backend.coderDispatches).toBe(2);
  });
});
