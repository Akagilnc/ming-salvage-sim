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
import type { DispatchContext, WorkerResult, WorkerSpec } from "../src/types.js";

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
});
