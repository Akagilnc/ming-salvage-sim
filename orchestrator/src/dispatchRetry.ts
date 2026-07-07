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
 * A dispatch outcome as the retry layer sees it: either the underlying dispatch
 * threw, or it resolved into a {@link WorkerResult}.
 */
export type DispatchOutcome =
  | { readonly kind: "thrown"; readonly error: unknown }
  | { readonly result: WorkerResult };

/**
 * Options that let a caller compose its OWN semantic-retry layer with this generic
 * mechanical layer WITHOUT double-counting (#598 acceptance: "each keeps its own
 * counter, the generic layer firing only after those run").
 */
export interface MechanicalRetryOptions {
  /**
   * Return `true` when THIS failure is owned by the caller's semantic-retry layer
   * (e.g. the reviewer's invalid-output rerun, or CMR's same-worker outcome
   * rewrite) and must NOT be retried here — the generic layer defers it to the
   * caller (re-throws a thrown error, returns a resolved result) so the caller's
   * own bounded loop handles it with its own counter. Everything else (a generic
   * crash / connection drop / process-protocol failure the caller does not own) is
   * retried fresh here. Absent ⇒ nothing is caller-owned; every process failure is
   * retried generically.
   */
  readonly callerOwns?: (outcome: DispatchOutcome) => boolean;
  /**
   * When `true`, a THROWN error that persists across all attempts is RE-THROWN
   * (the last error) instead of being converted to a synthesized `failed` result.
   * Use when the caller already has a domain-specific throw→result converter (e.g.
   * the family CMR `dispatchOrAbort` catch, which stamps a "cmr worker threw on
   * startup" message the gate classifies) — the generic layer retries the crash but
   * leaves the final surfacing to that converter. Default `false`: exhaustion
   * returns the last synthesized `failed`.
   */
  readonly rethrowOnExhaustion?: boolean;
  /**
   * Idempotency hook (#598): reset LOCAL side effects (git HEAD/worktree residue)
   * to the pre-attempt state BEFORE each retry, so a retry never runs on top of an
   * uncleaned side effect the previous crashed attempt left behind. Called only
   * before a retry (never before the first attempt). Remote side effects (pushed
   * branch, opened PR) must be made idempotent or excluded by the caller.
   */
  readonly resetBeforeRetry?: () => Promise<void>;
}

/**
 * Wrap a raw dispatch (`dispatch(spec, ctx)` → `WorkerResult`) with the generic
 * mechanical retry. The first attempt uses the caller's spec/ctx verbatim (may be
 * a resume); every retry is forced fresh (resume id stripped, `session:"fresh"`).
 * A thrown exception is treated as a process failure and retried — UNLESS
 * `opts.callerOwns` claims it, in which case it is re-thrown (thrown outcome) or
 * returned (resolved outcome) for the caller's own semantic layer to handle.
 */
export async function withMechanicalRetry(
  spec: WorkerSpec,
  ctx: DispatchContext,
  dispatch: (spec: WorkerSpec, ctx: DispatchContext) => Promise<WorkerResult>,
  opts?: MechanicalRetryOptions,
): Promise<WorkerResult> {
  let last: WorkerResult | undefined;
  let lastError: unknown;
  let lastAttemptThrew = false;
  for (let attempt = 1; attempt <= MAX_DISPATCH_ATTEMPTS; attempt++) {
    const useSpec = attempt === 1 ? spec : forceFreshSpec(spec);
    const useCtx = attempt === 1 ? ctx : stripResume(ctx);
    // Idempotency: before a RETRY, reset local git residue the crashed attempt may
    // have left, so the fresh re-dispatch starts from the pre-attempt state.
    if (attempt > 1) await opts?.resetBeforeRetry?.();
    let result: WorkerResult;
    try {
      result = await dispatch(useSpec, useCtx);
      lastAttemptThrew = false;
    } catch (err) {
      // A thrown error the caller's semantic layer owns is re-thrown untouched —
      // the generic layer never retries it (no double-count).
      if (opts?.callerOwns?.({ kind: "thrown", error: err }) === true) throw err;
      lastError = err;
      lastAttemptThrew = true;
      last = {
        kind: "failed",
        reason: `dispatch threw: ${err instanceof Error ? err.message : String(err)}`,
      };
      continue;
    }
    if (!isProcessFailure(result)) return result;
    // A process-level failure the caller's semantic layer owns is returned as-is so
    // the caller's own bounded loop retries it with its own counter (#598 sequential
    // composition — the generic layer fires only for failures nobody else owns).
    if (opts?.callerOwns?.({ result }) === true) return result;
    last = result;
  }
  // Exhausted. If the last attempt threw and the caller owns the throw→result
  // conversion, re-throw so its domain converter surfaces the failure.
  if (opts?.rethrowOnExhaustion === true && lastAttemptThrew) throw lastError;
  // Otherwise return the last process-level failure verbatim so the caller's
  // existing durable-abort path surfaces it (no new supervisor / stop reason).
  return last!;
}

/**
 * The generic mechanical retry for a NON-WorkerResult seam that signals a process
 * crash by THROWING (#598 — the merge-conflict resolver's own call site). Retries
 * `fn` up to a bound when it throws; a RETURNED value (even a judged not-ok, e.g. a
 * merger `{resolved:false}`) is never retried — the caller surfaces it. A local
 * side effect the crashed attempt left is reset before each retry via
 * `resetBeforeRetry`. Persistent crash re-throws the last error.
 */
export async function retryProcessCrash<T>(
  fn: () => Promise<T>,
  opts?: {
    readonly maxAttempts?: number;
    readonly resetBeforeRetry?: () => Promise<void>;
  },
): Promise<T> {
  const max = opts?.maxAttempts ?? MAX_DISPATCH_ATTEMPTS;
  let lastError: unknown;
  for (let attempt = 1; attempt <= max; attempt++) {
    if (attempt > 1) await opts?.resetBeforeRetry?.();
    try {
      return await fn();
    } catch (err) {
      lastError = err;
    }
  }
  throw lastError;
}
