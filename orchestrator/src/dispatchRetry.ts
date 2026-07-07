/**
 * #598 — generic mechanical retry at the shared dispatch seam.
 *
 * Runner function (a) (ADR 0062 / #604): a worker dispatch that ends in a
 * PROCESS-LEVEL failure (a returned `failed`/`malformed`/`outcome_protocol_failure`
 * kind, a thrown exception, or a "no completion signal" case surfacing as one of
 * those) is retried with a FRESH (non-resume) session for the SAME step, up to a
 * small fixed bound. A result that parsed into a valid, JUDGED shape
 * (`completed` / `escalated`) is returned as-is with ZERO retry, regardless of
 * content — that judgment belongs to the next fresh reviewer pass, never to this
 * mechanical layer. On bounded-consecutive-failure exhaustion the last failure is
 * returned so the caller's existing durable-abort path handles it (no new
 * supervisor, no new stop-reason field).
 *
 * This layer reads ONLY the outcome discriminant (`result.kind`) — never the
 * worker's self-reported content.
 */

import type { DispatchContext, WorkerResult, WorkerSpec } from "./types.js";

/**
 * Total dispatch attempts for one step (1 initial + retries). Aligned with the
 * reviewer's existing `MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS` small bound so no
 * role is treated specially (#592). #598 owns this number.
 */
export const MAX_DISPATCH_ATTEMPTS = 3;

/** The `WorkerResult` kinds that are a process-level failure (retryable). */
function isProcessFailure(result: WorkerResult): boolean {
  return (
    result.kind === "failed" ||
    result.kind === "malformed" ||
    result.kind === "outcome_protocol_failure"
  );
}

/** Force a retry dispatch to be FRESH: a resume dispatch never resumes the old session. */
function forceFreshSpec(spec: WorkerSpec): WorkerSpec {
  return spec.session === "fresh" ? spec : { ...spec, session: "fresh" };
}

/** Strip the resume session id so a retry opens a brand-new session (#598). */
function stripResume(ctx: DispatchContext): DispatchContext {
  if (ctx.resumeSessionId === undefined) return ctx;
  const { resumeSessionId: _drop, ...rest } = ctx;
  return rest;
}

/**
 * Wrap a raw dispatch (`dispatch(spec, ctx)` → `WorkerResult`) with the generic
 * mechanical retry. The first attempt uses the caller's spec/ctx verbatim (may be
 * a resume); every retry is forced fresh (resume id stripped, `session:"fresh"`).
 * A thrown exception is treated as a `failed` outcome and retried.
 */
export async function withMechanicalRetry(
  spec: WorkerSpec,
  ctx: DispatchContext,
  dispatch: (spec: WorkerSpec, ctx: DispatchContext) => Promise<WorkerResult>,
): Promise<WorkerResult> {
  let last: WorkerResult | undefined;
  for (let attempt = 1; attempt <= MAX_DISPATCH_ATTEMPTS; attempt++) {
    const useSpec = attempt === 1 ? spec : forceFreshSpec(spec);
    const useCtx = attempt === 1 ? ctx : stripResume(ctx);
    let result: WorkerResult;
    try {
      result = await dispatch(useSpec, useCtx);
    } catch (err) {
      result = {
        kind: "failed",
        reason: `dispatch threw: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
    if (!isProcessFailure(result)) return result;
    last = result;
  }
  // Exhausted: return the last process-level failure verbatim so the caller's
  // existing durable-abort path surfaces it (no new supervisor / stop reason).
  return last!;
}
