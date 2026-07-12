/**
 * #879 / #861 D — CMR leg transient retry at the orchestrator backend
 * encapsulation.
 *
 * In this codebase a CMR *leg* is a model×pipe entry in the route's
 * `cmrReview` collection (and the other slot smokes that share the same
 * provider pipes). The orchestrator-owned encapsulation for those legs is
 * route smoke (`RealBackend.smokeModelRoute`): a failed smoke marks the leg
 * unavailable and can kill the run as "required CMR anchor leg unavailable".
 * Classification + bounded retry live HERE so a single connection blip on an
 * anchor leg (e.g. opus) retries ×2 before degrade; 429/quota surfaces with
 * zero retry.
 *
 * Layers deliberately NOT owned by this module:
 * - In-container multi-vendor reviewers spawned by the ak-cross-m-review skill
 *   (their backends have their own degrade chain).
 * - Whole worker process crashes on `dispatchWorker` / family CMR worker
 *   (`#598` mechanical retry — process-level, not provider-error class).
 *
 * This is narrower than #598: the *class* of the provider error decides
 * whether to retry or degrade, instead of retrying every process failure.
 */

/** 1 initial + 2 retries ("重试 ×2") per #861 D / #879. */
export const MAX_LEG_TRANSIENT_ATTEMPTS = 3;

/** Seconds-scale pauses between transient retries (skip under vitest). */
export const LEG_TRANSIENT_RETRY_BACKOFF_MS = [2_000, 5_000] as const;

export type LegFailureClass = "transient" | "quota" | "other";

const defaultSleepMs = (ms: number): Promise<void> =>
  process.env.VITEST === "true"
    ? Promise.resolve()
    : new Promise<void>((resolve) => setTimeout(resolve, ms));

function errorText(error: unknown): string {
  if (error instanceof Error) {
    const cause =
      error.cause !== undefined && error.cause !== null
        ? ` ${errorText(error.cause)}`
        : "";
    return `${error.name} ${error.message}${cause}`;
  }
  return String(error);
}

/**
 * True when free text names an HTTP 5xx status (500/502/503/504 and nearby).
 * Mirrors the spirit of telemetry's 429 matcher but for the 5xx band.
 */
function mentionsHttp5xx(lower: string): boolean {
  return (
    /\b(?:http(?:\/\d+(?:\.\d+)?)?(?:\s+(?:code|error|response\s+code|status(?:\s+code)?))?|status(?:\s+code)?|response\s+(?:status(?:\s+code)?|code))\s*(?:is|was)?\s*(?:=|:)?\s*5\d\d\b(?!\.\d)/.test(
      lower,
    ) ||
    // Common short forms: "HTTP 503", "502 Bad Gateway", "upstream returned 502"
    /\b(?:http\s*)?5(?:0[0-4]|2[26]|3[0135])\b/.test(lower) ||
    lower.includes("bad gateway") ||
    lower.includes("service unavailable") ||
    lower.includes("gateway timeout") ||
    lower.includes("internal server error")
  );
}

function isQuotaFailureText(lower: string, original: string): boolean {
  // Prefer explicit quota / rate-limit phrases; bare "limit" is too broad.
  if (
    lower.includes("rate limit") ||
    lower.includes("rate-limit") ||
    lower.includes("rate_limit") ||
    lower.includes("too many requests") ||
    (lower.includes("quota") && !lower.includes("iteration limit")) ||
    lower.includes("quota wait for reset") ||
    original.includes("额度") ||
    original.includes("余额不足") ||
    original.includes("配额")
  ) {
    return true;
  }
  // HTTP-status 429 (and bare "status 429" / "returned 429")
  if (
    /\b(?:http(?:\/\d+(?:\.\d+)?)?(?:\s+(?:code|error|response\s+code|status(?:\s+code)?))?|status(?:\s+code)?|response\s+(?:status(?:\s+code)?|code)|returned)\s*(?:is|was)?\s*(?:=|:)?\s*429\b(?!\.\d)/.test(
      lower,
    ) ||
    /\bhttp\s*429\b/.test(lower) ||
    /\bstatus\s*429\b/.test(lower)
  ) {
    return true;
  }
  return false;
}

function isTransientFailureText(lower: string): boolean {
  if (
    lower.includes("econnreset") ||
    lower.includes("econnrefused") ||
    lower.includes("etimedout") ||
    lower.includes("enetunreach") ||
    lower.includes("ehostunreach") ||
    lower.includes("epipe") ||
    lower.includes("socket hang up") ||
    lower.includes("stream disconnect") ||
    lower.includes("stream-disconnect") ||
    lower.includes("connection reset") ||
    lower.includes("connection closed") ||
    lower.includes("connection aborted") ||
    lower.includes("connection refused") ||
    lower.includes("connection terminated") ||
    lower.includes("connection interrupted") ||
    lower.includes("network error") ||
    lower.includes("network is unreachable") ||
    lower.includes("fetch failed") ||
    lower.includes("temporarily unavailable") ||
    lower.includes("broken pipe")
  ) {
    return true;
  }
  return mentionsHttp5xx(lower);
}

/**
 * Classify a thrown provider / transport error for leg-level retry policy.
 *
 * - `quota` — 429 / rate-limit / quota wall → immediate degrade, no retry
 * - `transient` — connection reset/close / 5xx → retry up to ×2 then degrade
 * - `other` — auth missing, semantic smoke failure, etc. → no retry
 *
 * Quota is checked first so a "429 + connection closed" message never retries.
 */
export function classifyLegFailure(error: unknown): LegFailureClass {
  const text = errorText(error);
  const lower = text.toLowerCase();
  if (isQuotaFailureText(lower, text)) return "quota";
  if (isTransientFailureText(lower)) return "transient";
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
