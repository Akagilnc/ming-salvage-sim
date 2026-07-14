/**
 * #598 — generic mechanical retry at the shared dispatch seam.
 *
 * Runner function (a) (ADR 0062 / #604): a worker dispatch that ends in a
 * PROCESS-LEVEL failure (a returned `failed`
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

import { isQuotaWaitForResetError } from "./quotaProbe.js";
import {
  capacityRelayErrorFrom,
  isHangWithLivePoolError,
  isSelfReportedRelayError,
} from "./relayDispatch.js";
import type { DispatchContext, WorkerResult, WorkerSpec } from "./types.js";

/**
 * Total dispatch attempts for one step (1 initial + retries) for a PROCESS-LEVEL
 * failure (crash / no-output). #598 owns this number.
 *
 * This is the single process-failure retry budget shared by every worker role.
 * Completed/escalated worker receipts are never retried here; the runner only
 * transports their self-reported gates and counts.
 */
export const MAX_DISPATCH_ATTEMPTS = 3;

/** Seconds-scale pauses for the two retries: enough for brief provider/spawn recovery. */
export const DISPATCH_RETRY_BACKOFF_MS = [5_000, 15_000] as const;

const defaultRetrySleepMs = (ms: number): Promise<void> =>
  process.env.VITEST === "true"
    ? Promise.resolve()
    : new Promise<void>((resolve) => setTimeout(resolve, ms));

/** The `WorkerResult` kinds that are a process-level failure (retryable). */
function isProcessFailure(result: WorkerResult): boolean {
  return result.kind === "failed";
}

/** Force a retry dispatch to be FRESH: a resume dispatch never resumes the old session. */
function forceFreshSpec(spec: WorkerSpec): WorkerSpec {
  return spec.session === "fresh" ? spec : { ...spec, session: "fresh" };
}

/** Strip the resume session id so a retry opens a brand-new session (#598). */
function stripResume(ctx: DispatchContext): DispatchContext {
  // Robust guard (typeof === "string"): treat explicit null (or non-string) as
  // absent so retry always forces fresh. Matches the dispatchWorker decision
  // and the runner construction. (Presence of a real string id is what is
  // load-bearing; null must not be "kept as resume".)
  if (typeof ctx.resumeSessionId !== "string") return ctx;
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
 * Options for the shared process-failure retry layer.
 */
export interface MechanicalRetryOptions {
  /** Injectable retry wait so tests and callers with virtual clocks do not sleep. */
  readonly sleepMs?: (ms: number) => Promise<void>;
  /**
   * Durable attempts already consumed for this step before the current runner
   * process started.  The retry budget is global to the durable step, not this
   * one invocation of `withMechanicalRetry`.
   */
  readonly attemptsAlreadyUsed?: number;
  /** Called immediately before each real worker dispatch with its absolute attempt number. */
  readonly onAttempt?: (attempt: number) => Promise<void>;
  /** Persist/observe a failed attempt before the same step is retried. */
  readonly onFailure?: (outcome: DispatchOutcome, attempt: number) => Promise<void>;
  /**
   * Optional escape hatch for an outcome that is not a process failure and must
   * surface unchanged. Callers that own a domain-specific throw→result converter
   * claim the outcome so the generic layer does not double-count it.
   * #899: StructuredOutputError after maxRetries is a process-level failure for
   * #598, not a caller-owned path that feeds empty cargo to the fixer.
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
 *
 * #686: resource failures (quota wall / hang-with-live-pool) are NEVER retried
 * here and NEVER trigger `resetBeforeRetry` — they surface for relay disposition.
 * On process-failure exhaustion the annotated result is a relay *candidate*
 * (caller may hand off via roster+pool lookup) rather than a silent durable abort.
 */
export async function withMechanicalRetry(
  spec: WorkerSpec,
  ctx: DispatchContext,
  dispatch: (spec: WorkerSpec, ctx: DispatchContext) => Promise<WorkerResult>,
  opts?: MechanicalRetryOptions,
): Promise<WorkerResult> {
  const attemptsAlreadyUsed = opts?.attemptsAlreadyUsed ?? 0;
  if (!Number.isInteger(attemptsAlreadyUsed) || attemptsAlreadyUsed < 0) {
    throw new Error(
      `withMechanicalRetry: attemptsAlreadyUsed must be a non-negative integer (received ${attemptsAlreadyUsed})`,
    );
  }
  if (attemptsAlreadyUsed >= MAX_DISPATCH_ATTEMPTS) {
    return {
      kind: "failed",
      reason:
        `mechanical redispatch budget already exhausted ` +
        `(after ${MAX_DISPATCH_ATTEMPTS} dispatch attempts; relay candidate)`,
    };
  }
  let last: WorkerResult | undefined;
  let lastError: unknown;
  let lastAttemptThrew = false;
  for (
    let attempt = attemptsAlreadyUsed + 1;
    attempt <= MAX_DISPATCH_ATTEMPTS;
    attempt++
  ) {
    const firstAttemptThisInvocation = attempt === attemptsAlreadyUsed + 1;
    const useSpec = firstAttemptThisInvocation ? spec : forceFreshSpec(spec);
    const useCtx = firstAttemptThisInvocation ? ctx : stripResume(ctx);
    // Idempotency: before a RETRY, reset local git residue the crashed attempt may
    // have left, so the fresh re-dispatch starts from the pre-attempt state.
    // #598 r4 (codexB): if the reset FAILS (git lock / permissions), the worktree is
    // in an unknown/dirty state — do NOT dispatch on it (that would run the worker on
    // top of an uncleaned side effect, the exact idempotency violation). Instead SKIP
    // this attempt's dispatch, record a synthetic reset failure, and let the loop retry
    // the reset next iteration (a transient reset failure recovers; a persistent one
    // exhausts into the durable abort below — the worker never runs on a dirty state).
    // #686: only process-level retries reach here; resource failures throw above and
    // never invoke resetBeforeRetry.
    if (!firstAttemptThisInvocation) {
      const delayMs = DISPATCH_RETRY_BACKOFF_MS[attempt - 2];
      const sleepMs = opts?.sleepMs ?? defaultRetrySleepMs;
      await sleepMs(delayMs);
      try {
        await opts?.resetBeforeRetry?.();
      } catch (err) {
        last = {
          kind: "failed",
          reason: `retry reset failed, worker not dispatched on un-reset state: ${
            err instanceof Error ? err.message : String(err)
          }`,
        };
        lastAttemptThrew = false;
        continue;
      }
    }
    await opts?.onAttempt?.(attempt);
    let result: WorkerResult;
    try {
      result = await dispatch(useSpec, useCtx);
      lastAttemptThrew = false;
    } catch (err) {
      // #683/#686: resource failures park/relay — never mechanical-retry
      // (would thrash the same pool / destroy uncommitted drift via reset).
      if (isQuotaWaitForResetError(err)) throw err;
      const capacityError = capacityRelayErrorFrom(err);
      if (capacityError !== undefined) throw capacityError;
      if (isHangWithLivePoolError(err)) throw err;
      if (isSelfReportedRelayError(err)) throw err;
      // A thrown error the caller's semantic layer owns is re-thrown untouched —
      // the generic layer never retries it (no double-count).
      if (opts?.callerOwns?.({ kind: "thrown", error: err }) === true) throw err;
      lastError = err;
      lastAttemptThrew = true;
      last = {
        kind: "failed",
        reason: `dispatch threw: ${err instanceof Error ? err.message : String(err)}`,
      };
      await opts?.onFailure?.({ kind: "thrown", error: err }, attempt);
      continue;
    }
    const capacityError =
      result.kind === "failed" ? capacityRelayErrorFrom(new Error(result.reason)) : undefined;
    if (capacityError !== undefined) throw capacityError;
    if (!isProcessFailure(result)) return result;
    // A process-level failure the caller's semantic layer owns is returned as-is so
    // the caller's own bounded loop retries it with its own counter (#598 sequential
    // composition — the generic layer fires only for failures nobody else owns).
    if (opts?.callerOwns?.({ result }) === true) return result;
    last = result;
    await opts?.onFailure?.({ result }, attempt);
  }
  // Exhausted. If the last attempt threw and the caller owns the throw→result
  // conversion, re-throw so its domain converter surfaces the failure.
  if (opts?.rethrowOnExhaustion === true && lastAttemptThrew) throw lastError;
  // Otherwise return the last process-level failure, ANNOTATING the reason with the
  // generic dispatch attempt count (#598 crit 6 — durable abort names the failed
  // step [added by the caller] AND the attempt count, using the existing
  // stop-reason vocabulary, no new field). #686: exhaustion is a relay *candidate*
  // (board depth) rather than a silent durable abort — the annotation keeps the
  // existing vocabulary while signalling the caller may hand off.
  const attempts = MAX_DISPATCH_ATTEMPTS;
  return {
    ...(last as Extract<WorkerResult, { reason: string }>),
    reason: `${(last as { reason: string }).reason} (after ${attempts} dispatch attempts; relay candidate)`,
  };
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
  // Sourcery r2: fail loudly on a misconfigured bound rather than silently skipping
  // the loop and throwing on an uninitialized error.
  if (max <= 0) {
    throw new Error(
      `retryProcessCrash: maxAttempts must be a positive integer (received ${max})`,
    );
  }
  let lastError: unknown;
  for (let attempt = 1; attempt <= max; attempt++) {
    if (attempt > 1) {
      // #598 r4 (codexB): a failed reset means the state is unknown/dirty — do NOT run
      // `fn` on it. Record the reset failure and retry the reset next iteration (a
      // transient one recovers; a persistent one exhausts into the re-throw below —
      // `fn` never runs on an un-reset state).
      try {
        await opts?.resetBeforeRetry?.();
      } catch (err) {
        lastError = err;
        continue;
      }
    }
    try {
      return await fn();
    } catch (err) {
      lastError = err;
    }
  }
  // #598 crit 6: name the generic dispatch attempt count on exhaustion (the
  // merge-resolver seam re-throws; its caller stamps the domain message).
  // Sourcery r2: preserve the original error (stack/object) via `cause` so infra
  // failures stay debuggable.
  const annotated =
    lastError instanceof Error
      ? new Error(`${lastError.message} (after ${max} dispatch attempts)`, {
          cause: lastError,
        })
      : new Error(`${String(lastError)} (after ${max} dispatch attempts)`, {
          cause: lastError,
        });
  throw annotated;
}
