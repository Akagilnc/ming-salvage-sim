/**
 * #884 — external-call clocks + transient retry (S8 / 873 survival hygiene).
 *
 * Every wait that leaves the process must carry a clock:
 *   - subprocess seam: execFile(Sync) + timeout → kill child → typed error
 *   - in-process provider/HTTP seam: AbortSignal.timeout (probe band 60–120s)
 *
 * Timeout disposition (S5-family classification; self-contained until #879
 * merges): transient → retry ×2 (3 total attempts); quota → no retry (park);
 * durable → surface immediately. Durable records always carry a **stage name**.
 */

import { execFile, execFileSync } from "node:child_process";

/** Probe-class provider/HTTP wall budget (owner band 60–120s). */
export const DEFAULT_PROVIDER_TIMEOUT_MS = 90_000;

/** Default host subprocess wall budget (gh/git short ops). */
export const DEFAULT_SUBPROCESS_TIMEOUT_MS = 120_000;

/**
 * Effective subprocess wall budget. Under vitest, clamp hard so a real-network
 * hang cannot burn minutes of retry budget in unit tests (production stays 120s).
 */
export function effectiveSubprocessTimeoutMs(
  requested: number = DEFAULT_SUBPROCESS_TIMEOUT_MS,
): number {
  if (process.env.VITEST === "true") {
    return Math.min(requested, 2_000);
  }
  return requested;
}

/**
 * Total attempts for a transient external failure: 1 initial + 2 retries
 * (matches the #879 / S5 "瞬断重试 ×2" contract).
 */
export const EXTERNAL_CALL_MAX_ATTEMPTS = 3;

/** Seconds-scale pauses between transient retries (skipped under vitest). */
export const EXTERNAL_CALL_RETRY_BACKOFF_MS = [1_000, 3_000] as const;

export type ExternalFailureClass = "transient" | "quota" | "durable";

export type ExternalCallSeam = "subprocess" | "provider";

export interface ExternalCallAttemptRecord {
  readonly stage: string;
  readonly attempt: number;
  readonly outcome: "ok" | "retry" | "exhausted" | "quota" | "durable";
  readonly error?: string;
  readonly ts: string;
}

export class ExternalCallTimeoutError extends Error {
  readonly stage: string;
  readonly timeoutMs: number;
  readonly seam: ExternalCallSeam;

  constructor(input: {
    readonly stage: string;
    readonly timeoutMs: number;
    readonly seam: ExternalCallSeam;
    readonly cause?: unknown;
  }) {
    const causeMsg =
      input.cause instanceof Error
        ? input.cause.message
        : input.cause !== undefined
          ? String(input.cause)
          : undefined;
    super(
      `external call timed out at stage ${input.stage} after ${input.timeoutMs}ms` +
        ` (${input.seam})` +
        (causeMsg !== undefined ? `: ${causeMsg}` : ""),
    );
    this.name = "ExternalCallTimeoutError";
    this.stage = input.stage;
    this.timeoutMs = input.timeoutMs;
    this.seam = input.seam;
  }
}

export class ExternalCallExhaustedError extends Error {
  readonly stage: string;
  readonly attempts: number;
  readonly lastError: unknown;

  constructor(input: {
    readonly stage: string;
    readonly attempts: number;
    readonly lastError: unknown;
  }) {
    const last =
      input.lastError instanceof Error
        ? input.lastError.message
        : String(input.lastError);
    super(
      `external call exhausted ${input.attempts} attempts at stage ${input.stage}: ${last}`,
    );
    this.name = "ExternalCallExhaustedError";
    this.stage = input.stage;
    this.attempts = input.attempts;
    this.lastError = input.lastError;
  }
}

/**
 * S5-family classification for external failures.
 * Transient (timeout / connection drop / 5xx) may retry; quota never retries;
 * everything else is durable and surfaces immediately.
 */
export function classifyExternalCallFailure(err: unknown): ExternalFailureClass {
  if (err instanceof ExternalCallTimeoutError) return "transient";
  if (err !== null && typeof err === "object") {
    const e = err as {
      readonly name?: unknown;
      readonly code?: unknown;
      readonly message?: unknown;
      readonly status?: unknown;
      readonly statusCode?: unknown;
    };
    if (e.name === "ExternalCallTimeoutError" || e.name === "TimeoutError" || e.name === "AbortError") {
      return "transient";
    }
    if (e.code === "ETIMEDOUT" || e.code === "ECONNRESET" || e.code === "ECONNREFUSED" || e.code === "EPIPE") {
      return "transient";
    }
    const status =
      typeof e.status === "number"
        ? e.status
        : typeof e.statusCode === "number"
          ? e.statusCode
          : undefined;
    if (status === 429) return "quota";
    if (status !== undefined && status >= 500 && status <= 599) return "transient";
  }
  const msg = err instanceof Error ? err.message : String(err);
  const lower = msg.toLowerCase();
  if (
    lower.includes("429") ||
    lower.includes("rate limit") ||
    lower.includes("rate-limit") ||
    lower.includes("rate_limit") ||
    lower.includes("too many requests") ||
    lower.includes("quota") ||
    msg.includes("额度") ||
    msg.includes("余额不足") ||
    msg.includes("配额")
  ) {
    return "quota";
  }
  if (
    lower.includes("etimedout") ||
    lower.includes("econnreset") ||
    lower.includes("econnrefused") ||
    lower.includes("socket hang up") ||
    lower.includes("network") ||
    lower.includes("timed out") ||
    lower.includes("timeout") ||
    lower.includes("aborted") ||
    /\b5\d\d\b/.test(lower) ||
    lower.includes("http 5")
  ) {
    return "transient";
  }
  return "durable";
}

function defaultSleepMs(ms: number): Promise<void> {
  if (process.env.VITEST === "true") return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function defaultSleepSync(ms: number): void {
  if (process.env.VITEST === "true") return;
  // Busy-wait is avoided; Atomics.wait on a SharedArrayBuffer is the portable
  // sync sleep without pulling in child_process. 1 Int32 is enough.
  const sab = new SharedArrayBuffer(4);
  const view = new Int32Array(sab);
  Atomics.wait(view, 0, 0, ms);
}

function isTimeoutLikeExecError(err: unknown): boolean {
  if (err === null || typeof err !== "object") return false;
  const e = err as {
    readonly killed?: unknown;
    readonly signal?: unknown;
    readonly code?: unknown;
    readonly message?: unknown;
  };
  if (e.killed === true) return true;
  if (e.signal === "SIGTERM" || e.signal === "SIGKILL") return true;
  if (e.code === "ETIMEDOUT") return true;
  if (typeof e.message === "string" && /timed? ?out/i.test(e.message)) return true;
  return false;
}

export interface ExecFileTimeoutOptions {
  readonly stage: string;
  readonly timeoutMs?: number;
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly input?: string;
  readonly maxBuffer?: number;
}

/**
 * Sync subprocess seam with a mandatory clock. On timeout the child is killed
 * (Node's execFileSync behaviour) and a typed {@link ExternalCallTimeoutError}
 * is raised carrying the stage name.
 */
export function execFileWithTimeout(
  file: string,
  args: readonly string[],
  opts: ExecFileTimeoutOptions,
): string {
  const timeoutMs = effectiveSubprocessTimeoutMs(
    opts.timeoutMs ?? DEFAULT_SUBPROCESS_TIMEOUT_MS,
  );
  try {
    // No stdin input → ignore stdin so git/gh never hang waiting on the pipe.
    const hasInput = opts.input !== undefined;
    return execFileSync(file, [...args], {
      cwd: opts.cwd,
      env: opts.env,
      ...(hasInput ? { input: opts.input } : {}),
      encoding: "utf8",
      stdio: hasInput ? ["pipe", "pipe", "pipe"] : ["ignore", "pipe", "pipe"],
      timeout: timeoutMs,
      maxBuffer: opts.maxBuffer ?? 16 * 1024 * 1024,
      // SIGKILL: hard clock. SIGTERM can be trapped → parent still waits (Node docs).
      killSignal: "SIGKILL",
    }).toString();
  } catch (err) {
    if (isTimeoutLikeExecError(err)) {
      throw new ExternalCallTimeoutError({
        stage: opts.stage,
        timeoutMs,
        seam: "subprocess",
        cause: err,
      });
    }
    throw err;
  }
}

/**
 * Async subprocess seam with a clock — preferred for parallel work (smoke-k)
 * so Promise.all actually overlaps wall time.
 */
export function execFileAsyncWithTimeout(
  file: string,
  args: readonly string[],
  opts: ExecFileTimeoutOptions,
): Promise<string> {
  const timeoutMs = effectiveSubprocessTimeoutMs(
    opts.timeoutMs ?? DEFAULT_SUBPROCESS_TIMEOUT_MS,
  );
  const hasInput = opts.input !== undefined;
  return new Promise<string>((resolve, reject) => {
    const child = execFile(
      file,
      [...args],
      {
        cwd: opts.cwd,
        env: opts.env,
        encoding: "utf8",
        timeout: timeoutMs,
        maxBuffer: opts.maxBuffer ?? 16 * 1024 * 1024,
        // SIGKILL: hard clock. SIGTERM can be trapped → parent still waits (Node docs).
        killSignal: "SIGKILL",
      },
      (err, stdout, stderr) => {
        if (err !== null) {
          if (isTimeoutLikeExecError(err)) {
            reject(
              new ExternalCallTimeoutError({
                stage: opts.stage,
                timeoutMs,
                seam: "subprocess",
                cause: err,
              }),
            );
            return;
          }
          const enriched = err as Error & { readonly stderr?: string };
          if (typeof stderr === "string" && stderr.length > 0) {
            enriched.message = `${enriched.message}\n${stderr}`;
          }
          reject(err);
          return;
        }
        resolve(typeof stdout === "string" ? stdout : String(stdout ?? ""));
      },
    );
    if (hasInput) {
      child.stdin?.end(opts.input);
    } else {
      child.stdin?.end();
    }
  });
}

/**
 * In-process provider/HTTP seam: race the work against AbortSignal.timeout.
 *
 * The runner SHOULD honour `signal` (fetch, undici, …) so the underlying work
 * can cancel. The wrapper ALSO races an abort reject so a non-cooperative
 * provider that ignores the signal still cannot hang the process forever —
 * that is the #884 hang class (provider never responds, no thrown error).
 */
export async function withProviderTimeout<T>(
  stage: string,
  run: (signal: AbortSignal) => Promise<T>,
  opts?: { readonly timeoutMs?: number },
): Promise<T> {
  const timeoutMs = opts?.timeoutMs ?? DEFAULT_PROVIDER_TIMEOUT_MS;
  const signal = AbortSignal.timeout(timeoutMs);
  let onAbort: (() => void) | undefined;
  try {
    const abortPromise = new Promise<never>((_resolve, reject) => {
      const fire = () => {
        reject(
          new ExternalCallTimeoutError({
            stage,
            timeoutMs,
            seam: "provider",
            cause: signal.reason,
          }),
        );
      };
      if (signal.aborted) {
        fire();
        return;
      }
      onAbort = fire;
      signal.addEventListener("abort", fire, { once: true });
    });
    return await Promise.race([run(signal), abortPromise]);
  } catch (err) {
    if (err instanceof ExternalCallTimeoutError) throw err;
    if (
      signal.aborted ||
      (err !== null &&
        typeof err === "object" &&
        ((err as { name?: unknown }).name === "TimeoutError" ||
          (err as { name?: unknown }).name === "AbortError"))
    ) {
      throw new ExternalCallTimeoutError({
        stage,
        timeoutMs,
        seam: "provider",
        cause: err,
      });
    }
    throw err;
  } finally {
    if (onAbort !== undefined) {
      signal.removeEventListener("abort", onAbort);
    }
  }
}

export interface ExternalCallRetryOptions {
  readonly maxAttempts?: number;
  readonly sleepMs?: (ms: number) => Promise<void>;
  readonly onAttempt?: (attempt: number, stage: string) => void;
  /** Durable / observable bookkeeping — every attempt carries the stage name. */
  readonly record?: (event: ExternalCallAttemptRecord) => void;
  readonly now?: () => Date;
}

/**
 * Default production recorder: stage-named line on every non-trivial outcome
 * (retry / exhausted / quota / durable / multi-attempt ok). First-attempt ok
 * stays quiet so hot paths are not log-spam.
 */
export function defaultExternalCallRecorder(
  event: ExternalCallAttemptRecord,
): void {
  if (event.outcome === "ok" && event.attempt === 1) return;
  const err =
    event.error !== undefined && event.error.length > 0
      ? ` error=${event.error}`
      : "";
  console.warn(
    `[orchestrator:external-call] stage=${event.stage} attempt=${event.attempt} outcome=${event.outcome}${err}`,
  );
}

/**
 * Attempt budget for host subprocess seams.
 * - vitest: always 1 (keep unit tests fast / deterministic)
 * - retry:false (mutations): always 1 (exactly-once — timeout must not re-fire
 *   git push/merge/clone or gh writes; ADR 0062 / #884 cmr r7)
 * - otherwise: EXTERNAL_CALL_MAX_ATTEMPTS (1 initial + 2 transient retries)
 */
export function hostSubprocessRetryAttempts(opts?: {
  readonly retry?: boolean;
}): number {
  if (process.env.VITEST === "true") return 1;
  if (opts?.retry === false) return 1;
  return EXTERNAL_CALL_MAX_ATTEMPTS;
}

/**
 * Host subprocess with clock + S5 retry disposition + stage-named records.
 * Preferred entry for production `gh`/`git`/CLI one-shots.
 */
export function shWithClock(
  file: string,
  args: readonly string[],
  opts?: {
    readonly stage?: string;
    readonly cwd?: string;
    readonly timeoutMs?: number;
    /**
     * When false, do not transient-retry (mutating gh/git must be exactly-once
     * per ADR 0062 — a lost response must not re-fire DELETE/close).
     * Default true for read-ish ops. Mixed class-level `sh` seams (RealBackend /
     * RealFamilyBackend) MUST pass retry:false — they carry both reads and
     * mutations and cannot safely default-retry.
     */
    readonly retry?: boolean;
  },
): string {
  const stage = opts?.stage ?? `subprocess:${file}`;
  const maxAttempts = hostSubprocessRetryAttempts({ retry: opts?.retry });
  return withExternalCallRetrySync(
    stage,
    () =>
      execFileWithTimeout(file, [...args], {
        stage,
        timeoutMs: effectiveSubprocessTimeoutMs(
          opts?.timeoutMs ?? DEFAULT_SUBPROCESS_TIMEOUT_MS,
        ),
        cwd: opts?.cwd,
      }).trim(),
    {
      maxAttempts,
      record: defaultExternalCallRecorder,
    },
  );
}

/**
 * Run an external call with S5-family transient retry. Exhaustion raises
 * {@link ExternalCallExhaustedError} with the stage name for degrade/park paths.
 */
export async function withExternalCallRetry<T>(
  stage: string,
  run: () => Promise<T>,
  opts?: ExternalCallRetryOptions,
): Promise<T> {
  const maxAttempts = opts?.maxAttempts ?? EXTERNAL_CALL_MAX_ATTEMPTS;
  const sleepMs = opts?.sleepMs ?? defaultSleepMs;
  const now = opts?.now ?? (() => new Date());
  let lastError: unknown;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    opts?.onAttempt?.(attempt, stage);
    try {
      const value = await run();
      opts?.record?.({
        stage,
        attempt,
        outcome: "ok",
        ts: now().toISOString(),
      });
      return value;
    } catch (err) {
      lastError = err;
      const klass = classifyExternalCallFailure(err);
      if (klass === "quota") {
        opts?.record?.({
          stage,
          attempt,
          outcome: "quota",
          error: err instanceof Error ? err.message : String(err),
          ts: now().toISOString(),
        });
        throw err;
      }
      if (klass === "durable") {
        opts?.record?.({
          stage,
          attempt,
          outcome: "durable",
          error: err instanceof Error ? err.message : String(err),
          ts: now().toISOString(),
        });
        throw err;
      }
      // transient
      if (attempt >= maxAttempts) {
        opts?.record?.({
          stage,
          attempt,
          outcome: "exhausted",
          error: err instanceof Error ? err.message : String(err),
          ts: now().toISOString(),
        });
        throw new ExternalCallExhaustedError({
          stage,
          attempts: maxAttempts,
          lastError: err,
        });
      }
      opts?.record?.({
        stage,
        attempt,
        outcome: "retry",
        error: err instanceof Error ? err.message : String(err),
        ts: now().toISOString(),
      });
      const backoff =
        EXTERNAL_CALL_RETRY_BACKOFF_MS[
          Math.min(attempt - 1, EXTERNAL_CALL_RETRY_BACKOFF_MS.length - 1)
        ] ?? 1_000;
      await sleepMs(backoff);
    }
  }

  throw new ExternalCallExhaustedError({
    stage,
    attempts: maxAttempts,
    lastError,
  });
}

export interface ExternalCallRetrySyncOptions {
  readonly maxAttempts?: number;
  readonly sleepMs?: (ms: number) => void;
  readonly onAttempt?: (attempt: number, stage: string) => void;
  readonly record?: (event: ExternalCallAttemptRecord) => void;
  readonly now?: () => Date;
}

/**
 * Sync counterpart of {@link withExternalCallRetry} for host `gh`/`git`
 * seams that remain synchronous (`Sh` / `RealBackend.sh`). Same S5-family
 * disposition: transient → retry ×2; quota → no retry; durable → surface.
 */
export function withExternalCallRetrySync<T>(
  stage: string,
  run: () => T,
  opts?: ExternalCallRetrySyncOptions,
): T {
  const maxAttempts = opts?.maxAttempts ?? EXTERNAL_CALL_MAX_ATTEMPTS;
  const sleepMs = opts?.sleepMs ?? defaultSleepSync;
  const now = opts?.now ?? (() => new Date());
  let lastError: unknown;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    opts?.onAttempt?.(attempt, stage);
    try {
      const value = run();
      opts?.record?.({
        stage,
        attempt,
        outcome: "ok",
        ts: now().toISOString(),
      });
      return value;
    } catch (err) {
      lastError = err;
      const klass = classifyExternalCallFailure(err);
      if (klass === "quota") {
        opts?.record?.({
          stage,
          attempt,
          outcome: "quota",
          error: err instanceof Error ? err.message : String(err),
          ts: now().toISOString(),
        });
        throw err;
      }
      if (klass === "durable") {
        opts?.record?.({
          stage,
          attempt,
          outcome: "durable",
          error: err instanceof Error ? err.message : String(err),
          ts: now().toISOString(),
        });
        throw err;
      }
      if (attempt >= maxAttempts) {
        opts?.record?.({
          stage,
          attempt,
          outcome: "exhausted",
          error: err instanceof Error ? err.message : String(err),
          ts: now().toISOString(),
        });
        throw new ExternalCallExhaustedError({
          stage,
          attempts: maxAttempts,
          lastError: err,
        });
      }
      opts?.record?.({
        stage,
        attempt,
        outcome: "retry",
        error: err instanceof Error ? err.message : String(err),
        ts: now().toISOString(),
      });
      const backoff =
        EXTERNAL_CALL_RETRY_BACKOFF_MS[
          Math.min(attempt - 1, EXTERNAL_CALL_RETRY_BACKOFF_MS.length - 1)
        ] ?? 1_000;
      sleepMs(backoff);
    }
  }

  throw new ExternalCallExhaustedError({
    stage,
    attempts: maxAttempts,
    lastError,
  });
}
