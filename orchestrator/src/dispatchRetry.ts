/**
 * #598 — generic mechanical retry at the shared dispatch seam.
 *
 * Runner function (a) (ADR 0062 / #604): a worker dispatch that ends in a
 * PROCESS-LEVEL failure (a returned `failed`
 * kind, a thrown exception, or a missing-sidecar / incomplete handoff surfacing as one of
 * those) is retried with a FRESH (non-resume) session for the SAME step, up to a
 * small fixed bound. A result that parsed into a valid, JUDGED shape
 * (`completed` / `escalated`) is returned as-is with ZERO retry, regardless of
 * content — that judgment belongs to the next fresh reviewer pass, never to this
 * mechanical layer. On bounded-consecutive-failure exhaustion the last failure is
 * returned so the caller's existing durable-abort path handles it (no new
 * supervisor, no new stop-reason field).
 *
 * This layer classifies process-level outcomes for mechanical retry:
 * primarily the outcome discriminant (`result.kind`), plus durable host-FS
 * (EISDIR-class) classification on throw / failed `reason` (#1012) so the same
 * host path is not re-dispatched. It never reads worker self-reported content
 * for judgment — that belongs to the next fresh reviewer pass.
 */

import type { ChildProcess } from "node:child_process";

import { isEisdirClassHostFsError } from "./fsErrors.js";
import { isQuotaWaitForResetError } from "./quotaProbe.js";
import { isStructuredOutputParseFailure } from "./receiptRecovery.js";
import { capacityRelayErrorFrom } from "./relayDispatch.js";
import {
  isSandcastleAgentError,
  workerResultFromAgentError,
} from "./sandcastleAgentError.js";
import {
  isWorkerTerminationFailedError,
  terminateSpawnedChild,
  WorkerTerminationFailedError,
  type WorkerMonitorDeps,
} from "./workerMonitor.js";
import type { DispatchContext, WorkerResult, WorkerSpec } from "./types.js";

/**
 * #934 ID-004 / #937: adoption/persist failure after exact-handle terminate.
 * Must not enter process-root mechanical retry (would re-spawn on the same
 * fixed position after the prior instance was already terminated).
 */
export class AdoptionPersistFailedError extends Error {
  readonly reason = "adoption_persist_failed" as const;

  constructor(cause: unknown) {
    const msg = cause instanceof Error ? cause.message : String(cause);
    super(`adoption_persist_failed: ${msg}`);
    this.name = "AdoptionPersistFailedError";
    if (cause instanceof Error) this.cause = cause;
  }
}

export function isAdoptionPersistFailedError(
  err: unknown,
): err is AdoptionPersistFailedError {
  return (
    err instanceof AdoptionPersistFailedError ||
    (typeof err === "object" &&
      err !== null &&
      (err as { readonly name?: unknown }).name === "AdoptionPersistFailedError")
  );
}

/**
 * #934 ID-006 / #937 S1 — single court for spawn-adoption failure cleanup.
 *
 * Exact-handle terminate → wait exitPromise → promote
 * {@link WorkerTerminationFailedError} or wrap {@link AdoptionPersistFailedError}.
 * Shared by single-slice dispatchWorker and family dispatchFamilyWorker so the
 * two call sites cannot drift on monitorDeps / message shaping.
 */
export async function abandonSpawnAfterAdoptionFailure(input: {
  readonly child: ChildProcess;
  readonly exitPromise: Promise<unknown>;
  readonly adoptionError: unknown;
  readonly instanceId: string;
  readonly monitorDeps?: WorkerMonitorDeps;
}): Promise<never> {
  try {
    await terminateSpawnedChild(input.child, input.monitorDeps, {
      instanceId: input.instanceId,
    });
  } catch (termErr) {
    if (isWorkerTerminationFailedError(termErr)) {
      const base =
        input.adoptionError instanceof Error
          ? input.adoptionError.message
          : String(input.adoptionError);
      throw new WorkerTerminationFailedError({
        ...(termErr.pid !== undefined ? { pid: termErr.pid } : {}),
        instanceId: input.instanceId,
        message:
          `${base}; worker_termination_failed` +
          (termErr.pid !== undefined ? ` pid=${termErr.pid}` : "") +
          ` instanceId=${input.instanceId}`,
      });
    }
  }
  try {
    await input.exitPromise;
  } catch {
    // Preserve the original spawn-persist error if child cleanup fails.
  }
  throw new AdoptionPersistFailedError(input.adoptionError);
}

/** Non-retryable throws that surface after exact-handle cleanup or durable edge. */
function isNonRetryableDispatchThrow(err: unknown): boolean {
  return (
    isQuotaWaitForResetError(err) ||
    capacityRelayErrorFrom(err) !== undefined ||
    isWorkerTerminationFailedError(err) ||
    isAdoptionPersistFailedError(err) ||
    // #1012: host FS EISDIR (docker dir-placeholder / open on directory) is
    // durable infra — re-dispatch cannot heal the same host path.
    isEisdirClassHostFsError(err)
  );
}

/** #1012: failed WorkerResult whose reason is EISDIR-class — same durable class. */
function isEisdirClassFailedResult(result: WorkerResult): boolean {
  return result.kind === "failed" && isEisdirClassHostFsError(result.reason);
}

/**
 * #1103 / #1105 A6 — deterministic worktree consistency wreckage.
 * Matches `fatal: not a git repository: …/.git/worktrees/…` (and Sandcastle
 * resident paths). Re-dispatch without heal burns the full process-root budget
 * on the same orphan dir (#1084 six-hit).
 */
export function isWorktreeConsistencyFailure(message: string): boolean {
  const lower = message.toLowerCase();
  if (!lower.includes("not a git repository")) return false;
  return (
    lower.includes(".git/worktrees/") ||
    lower.includes(".sandcastle/worktrees/") ||
    /[/\\]worktrees[/\\]/.test(lower)
  );
}

function worktreeConsistencyMessage(outcome: DispatchOutcome): string | undefined {
  if ("kind" in outcome && outcome.kind === "thrown") {
    return outcome.error instanceof Error
      ? outcome.error.message
      : String(outcome.error);
  }
  if ("result" in outcome && outcome.result.kind === "failed") {
    return outcome.result.reason;
  }
  return undefined;
}

function healFailureResult(err: unknown): Extract<WorkerResult, { kind: "failed" }> {
  return {
    kind: "failed",
    reason: `worktree consistency heal failed: ${
      err instanceof Error ? err.message : String(err)
    }`,
  };
}

/**
 * Total process-root dispatch attempts for one fixed position (1 initial +
 * 5 retries) when invocation transport/crash/signal/SO extraction fails and
 * no durable outcome exists yet (#934 ID-004 / #937).
 *
 * This is the single process-failure retry budget shared by every worker role.
 * Completed/escalated worker receipts are never retried here; the runner only
 * transports their self-reported gates and counts.
 */
export const MAX_DISPATCH_ATTEMPTS = 6;

/** Five 15s intervals between the 6 process-root attempts (#934 ID-004). */
export const DISPATCH_RETRY_BACKOFF_MS = [
  15_000,
  15_000,
  15_000,
  15_000,
  15_000,
] as const;

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
   * #1105 A6 / #1092-style deterministic class: before the next attempt after a
   * worktree consistency failure, clear wreckage and rebuild the resident
   * worksite. Invoked at most once per withMechanicalRetry invocation.
   */
  readonly healWorktreeConsistency?: (
    ctx: DispatchContext,
  ) => void | Promise<void>;
}

/**
 * Wrap a raw dispatch (`dispatch(spec, ctx)` → `WorkerResult`) with the generic
 * mechanical retry. The first attempt uses the caller's spec/ctx verbatim (may be
 * a resume); every retry is forced fresh (resume id stripped, `session:"fresh"`).
 * A thrown exception is treated as a process failure and retried — UNLESS
 * `opts.callerOwns` claims it, in which case it is re-thrown (thrown outcome) or
 * returned (resolved outcome) for the caller's own semantic layer to handle.
 *
 * #686/#937: resource failures (quota / capacity) and adoption/termination
 * failures are NEVER retried here. Process-root redispatch preserves the current
 * scene — never reset/checkout/clean Git residue (#934 ID-004/006; resetBeforeRetry deleted).
 * On process-failure exhaustion the result is the phase's canonical failed
 * edge (#934 ID-004) — runner escalateTermination, not a baton handoff.
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
        `(after ${MAX_DISPATCH_ATTEMPTS} dispatch attempts)`,
    };
  }
  let last: WorkerResult | undefined;
  let lastError: unknown;
  let lastAttemptThrew = false;
  // Absolute attempt index of the last dispatch actually performed (for the
  // exhaustion suffix — heal/resume short-circuits must not report MAX).
  let attemptsPerformed = attemptsAlreadyUsed;
  // #1092: SO parse failure on a resumed session is deterministic (YAML habit /
  // missing schema on hot resume). After the first such failure, allow exactly
  // one fresh attempt then stop — do not burn the remaining process-root budget
  // on six identical resume retries.
  let resumeSoParseFailed = false;
  // #1105 A6: worktree consistency wreckage is deterministic — heal once, allow
  // one post-heal attempt, then stop (same short-circuit shape as #1092).
  let worktreeConsistencyHealDone = false;
  /** #1105 R7 F2: heal throw → failed channel (never escape withMechanicalRetry). */
  const runConsistencyHeal = async (
    useCtx: DispatchContext,
    attempt: number,
  ): Promise<"healed" | "heal-failed" | "skip"> => {
    if (worktreeConsistencyHealDone || !opts?.healWorktreeConsistency) {
      return "skip";
    }
    try {
      await opts.healWorktreeConsistency(useCtx);
      worktreeConsistencyHealDone = true;
      return "healed";
    } catch (healErr) {
      worktreeConsistencyHealDone = true;
      last = healFailureResult(healErr);
      lastAttemptThrew = false;
      await opts?.onFailure?.({ result: last }, attempt);
      return "heal-failed";
    }
  };
  for (
    let attempt = attemptsAlreadyUsed + 1;
    attempt <= MAX_DISPATCH_ATTEMPTS;
    attempt++
  ) {
    attemptsPerformed = attempt;
    const firstAttemptThisInvocation = attempt === attemptsAlreadyUsed + 1;
    const useSpec = firstAttemptThisInvocation ? spec : forceFreshSpec(spec);
    const useCtx = firstAttemptThisInvocation ? ctx : stripResume(ctx);
    const attemptHadResume = typeof useCtx.resumeSessionId === "string";
    // #934 ID-004/006 / #937: process-root redispatch preserves the current
    // scene — never reset/checkout/clean Git residue (resetBeforeRetry deleted).
    // #1105 A6 is the narrow exception: worktree consistency heal clears orphan
    // dir↔metadata wreckage before the next attempt (not a broad Git reset).
    // Sleep binds to absolute attempt index (not first-in-this-process): a
    // durable re-entry with attemptsAlreadyUsed>0 must still honor the 15s
    // interval before the next dispatch (five 15s slots across six attempts).
    if (attempt > 1) {
      const delayMs = DISPATCH_RETRY_BACKOFF_MS[attempt - 2];
      if (delayMs !== undefined) {
        const sleepMs = opts?.sleepMs ?? defaultRetrySleepMs;
        await sleepMs(delayMs);
      }
    }
    // #934 ID-004 / #937: durable attempt markers are written only after a
    // process-level failure classification. Explicit 429/quota / capacity /
    // resource throws must not burn process-root budget (onAttempt used to
    // write mechanical_redispatch_attempt before dispatch).
    let result: WorkerResult;
    try {
      result = await dispatch(useSpec, useCtx);
      lastAttemptThrew = false;
    } catch (err) {
      // #964: AgentError → Action-typed failure for this invocation only.
      // Same dead credentials / agent death will not recover on re-dispatch —
      // convert once and return (do not burn process-root budget).
      const agentFailure = workerResultFromAgentError(err, spec.kind);
      if (agentFailure !== undefined) return agentFailure;
      // #683/#686/#937: resource / adoption / termination — never mechanical-retry.
      if (isNonRetryableDispatchThrow(err)) throw err;
      // A thrown error the caller's semantic layer owns is re-thrown untouched —
      // the generic layer never retries it (no double-count).
      if (opts?.callerOwns?.({ kind: "thrown", error: err }) === true) throw err;
      lastError = err;
      lastAttemptThrew = true;
      last = {
        kind: "failed",
        reason: `dispatch threw: ${err instanceof Error ? err.message : String(err)}`,
      };
      await opts?.onAttempt?.(attempt);
      await opts?.onFailure?.({ kind: "thrown", error: err }, attempt);
      if (
        attemptHadResume &&
        isStructuredOutputParseFailure(err)
      ) {
        resumeSoParseFailed = true;
        continue;
      }
      if (resumeSoParseFailed && !attemptHadResume) {
        // One fresh attempt after resume SO parse-fail already ran — stop.
        break;
      }
      const thrownMsg = worktreeConsistencyMessage({ kind: "thrown", error: err });
      if (
        thrownMsg !== undefined &&
        isWorktreeConsistencyFailure(thrownMsg)
      ) {
        const heal = await runConsistencyHeal(useCtx, attempt);
        if (heal === "healed") continue;
        break;
      }
      continue;
    }
    const capacityError =
      result.kind === "failed" ? capacityRelayErrorFrom(new Error(result.reason)) : undefined;
    if (capacityError !== undefined) throw capacityError;
    if (!isProcessFailure(result)) return result;
    // #1012: hostCliWorkerRunner converts EISDIR throws into failed results;
    // do not empty-spin the process-root budget on the same host-FS error.
    if (isEisdirClassFailedResult(result)) return result;
    // A process-level failure the caller's semantic layer owns is returned as-is so
    // the caller's own bounded loop retries it with its own counter (#598 sequential
    // composition — the generic layer fires only for failures nobody else owns).
    if (opts?.callerOwns?.({ result }) === true) return result;
    last = result;
    await opts?.onAttempt?.(attempt);
    await opts?.onFailure?.({ result }, attempt);
    if (resumeSoParseFailed && !attemptHadResume) {
      break;
    }
    const failedMsg = worktreeConsistencyMessage({ result });
    if (
      failedMsg !== undefined &&
      isWorktreeConsistencyFailure(failedMsg)
    ) {
      const heal = await runConsistencyHeal(useCtx, attempt);
      if (heal === "healed") continue;
      break;
    }
  }
  // Exhausted. If the last attempt threw and the caller owns the throw→result
  // conversion, re-throw so its domain converter surfaces the failure.
  if (opts?.rethrowOnExhaustion === true && lastAttemptThrew) throw lastError;
  // #934 ID-004 / #937: exhaustion is the phase's canonical failed edge —
  // attempt count only (no relay-candidate / baton handoff vocabulary).
  // #1105 R4 F-P2: report attempts actually performed (heal short-circuit = 2,
  // not always MAX_DISPATCH_ATTEMPTS).
  return {
    ...(last as Extract<WorkerResult, { reason: string }>),
    reason: `${(last as { reason: string }).reason} (after ${attemptsPerformed} dispatch attempts)`,
  };
}

/**
 * The generic mechanical retry for a NON-WorkerResult seam that signals a process
 * crash by THROWING (#598 — the merge-conflict resolver's own call site). Retries
 * `fn` up to a bound when it throws; a RETURNED value (even a judged not-ok, e.g. a
 * merger `{resolved:false}`) is never retried — the caller surfaces it.
 * #937: no local-git reset court — scene is preserved across retries.
 */
export async function retryProcessCrash<T>(
  fn: () => Promise<T>,
  opts?: {
    readonly maxAttempts?: number;
    /** Injectable wait between attempts (same contract as withMechanicalRetry). */
    readonly sleepMs?: (ms: number) => Promise<void>;
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
      // #934 ID-004: five 15s intervals between the six process-root attempts
      // (same clock contract as withMechanicalRetry). No Git reset court.
      const delayMs = DISPATCH_RETRY_BACKOFF_MS[attempt - 2];
      if (delayMs !== undefined) {
        const sleepMs = opts?.sleepMs ?? defaultRetrySleepMs;
        await sleepMs(delayMs);
      }
    }
    try {
      return await fn();
    } catch (err) {
      // #964: AgentError is Action-typed failure for this invocation — never
      // re-burn process-root retries on the same dead credentials. Rethrow so
      // the seat court (merger) / outer converter surfaces structured failure.
      if (isSandcastleAgentError(err)) throw err;
      // #683/#686/#909/#937: resource / adoption / termination — NEVER retry.
      if (isNonRetryableDispatchThrow(err)) throw err;
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
