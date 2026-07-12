/**
 * #879 / #861 D — CMR leg transient retry at the orchestrator backend
 * encapsulation.
 *
 * In this codebase a CMR *leg* is a model×pipe entry in the route's
 * `cmrReview` collection (and the other slot smokes that share the same
 * provider pipes). The orchestrator-owned encapsulation for those legs is
 * route smoke (`RealBackend.smokeModelRoute` → `withLegTransientRetry` around
 * bare-ping): a failed smoke marks the leg unavailable and can kill the run
 * as "required CMR anchor leg unavailable". Classification + bounded retry
 * live HERE so a single connection blip on an anchor leg (e.g. opus) retries
 * ×2 before degrade; 429/quota surfaces with zero retry.
 *
 * Layers deliberately NOT owned by this module:
 * - In-container multi-vendor reviewers spawned by the ak-cross-m-review skill
 *   (their backends have their own degrade chain — out of #879 scope).
 * - Whole worker process crashes on `dispatchWorker` / family CMR worker
 *   (`#598` mechanical retry — process-level, not provider-error class).
 *
 * This is narrower than #598: the *class* of the provider error decides
 * whether to retry or degrade, instead of retrying every process failure.
 */

import { classifyExternalCallFailure } from "./externalCall.js";

/** 1 initial + 2 retries ("重试 ×2") per #861 D / #879. */
export const MAX_LEG_TRANSIENT_ATTEMPTS = 3;

/** Seconds-scale pauses between transient retries (skip under vitest). */
export const LEG_TRANSIENT_RETRY_BACKOFF_MS = [2_000, 5_000] as const;

export type LegFailureClass = "transient" | "quota" | "other";

const defaultSleepMs = (ms: number): Promise<void> =>
  process.env.VITEST === "true"
    ? Promise.resolve()
    : new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Classify a thrown provider / transport error for leg-level retry policy.
 *
 * - `quota` — 429 / rate-limit / quota wall → immediate degrade, no retry
 * - `transient` — connection reset/close / timeout / 5xx → retry up to ×2 then degrade
 * - `other` — auth missing, semantic smoke failure, etc. → no retry
 *
 * Single source: {@link classifyExternalCallFailure} (typed timeout, status-first
 * 5xx-over-quota text, structured status codes). Maps durable → other so the
 * leg helper stays on the three #879 classes without a parallel text court.
 */
export function classifyLegFailure(error: unknown): LegFailureClass {
  const klass = classifyExternalCallFailure(error);
  if (klass === "transient") return "transient";
  if (klass === "quota") return "quota";
  return "other";
}

export interface LegTransientRetryOptions {
  /** Injectable wait so tests and virtual clocks do not sleep. */
  readonly sleepMs?: (ms: number) => Promise<void>;
  /** Absolute attempt number (1-based) just before each `fn` call. */
  readonly onAttempt?: (attempt: number) => void | Promise<void>;
}

/**
 * Run `fn` with the #879 leg-transient policy:
 * - success → return
 * - quota / other throw → rethrow immediately (0 extra attempts)
 * - transient throw → retry up to {@link MAX_LEG_TRANSIENT_ATTEMPTS} total
 *   attempts (1 initial + 2 retries), then rethrow the last error
 */
export async function withLegTransientRetry<T>(
  fn: () => Promise<T>,
  opts?: LegTransientRetryOptions,
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= MAX_LEG_TRANSIENT_ATTEMPTS; attempt++) {
    await opts?.onAttempt?.(attempt);
    try {
      return await fn();
    } catch (err) {
      lastError = err;
      const cls = classifyLegFailure(err);
      if (cls !== "transient") throw err;
      if (attempt >= MAX_LEG_TRANSIENT_ATTEMPTS) throw err;
      const delayMs = LEG_TRANSIENT_RETRY_BACKOFF_MS[attempt - 1] ?? 0;
      const sleepMs = opts?.sleepMs ?? defaultSleepMs;
      await sleepMs(delayMs);
    }
  }
  throw lastError;
}
