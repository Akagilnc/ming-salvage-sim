/**
 * #884 — external-call clocks only (S8 hygiene).
 *
 * Two seams, each with a wall clock:
 *   - subprocess: execFile(Sync)/async + timeout → kill child → typed error
 *   - provider: AbortSignal.timeout race (probe band 60–120s)
 *
 * Retry policy is NOT here — #879 `legTransientRetry` owns leg/probe retry.
 * Classification stays as a pure helper for that layer (no retry loop here).
 */

import {
  execFile,
  execFileSync,
  spawn,
  type ChildProcess,
  type SpawnOptions,
} from "node:child_process";

export type { ChildProcess };

/** Probe-class provider/HTTP wall budget (owner band 60–120s). */
export const DEFAULT_PROVIDER_TIMEOUT_MS = 90_000;

/** Default host subprocess wall budget (gh/git short ops). */
export const DEFAULT_SUBPROCESS_TIMEOUT_MS = 120_000;

/** Under vitest, clamp so hangs cannot burn minutes. */
export function effectiveSubprocessTimeoutMs(
  requested: number = DEFAULT_SUBPROCESS_TIMEOUT_MS,
): number {
  if (process.env.VITEST === "true") {
    return Math.min(requested, 2_000);
  }
  return requested;
}

export type ExternalFailureClass = "transient" | "quota" | "durable";
export type ExternalCallSeam = "subprocess" | "provider";

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

/**
 * Pure class helper for #879 leg retry. No loop, no recorder, no attempts.
 * Sources: typed timeout, allowlisted error code, numeric HTTP status.
 * Everything else is durable; free text is never classified.
 */
export function classifyExternalCallFailure(err: unknown): ExternalFailureClass {
  if (err instanceof ExternalCallTimeoutError) return "transient";
  if (err !== null && typeof err === "object") {
    const e = err as {
      readonly name?: unknown;
      readonly code?: unknown;
      readonly status?: unknown;
      readonly statusCode?: unknown;
    };
    if (
      e.name === "ExternalCallTimeoutError" ||
      e.name === "TimeoutError" ||
      e.name === "AbortError"
    ) {
      return "transient";
    }
    if (
      e.code === "ETIMEDOUT" ||
      e.code === "ECONNRESET" ||
      e.code === "ECONNREFUSED" ||
      e.code === "EPIPE" ||
      e.code === "EAI_AGAIN" ||
      e.code === "ENETUNREACH" ||
      e.code === "EHOSTUNREACH"
    ) {
      return "transient";
    }
    const status =
      Number.isInteger(e.status)
        ? (e.status as number)
        : Number.isInteger(e.statusCode)
          ? (e.statusCode as number)
          : undefined;
    if (status !== undefined) {
      if (status === 429) return "quota";
      if (status >= 500 && status <= 599) return "transient";
      if (status >= 100 && status <= 599) return "durable";
    }
  }

  return "durable";
}

function isTimeoutLikeExecError(err: unknown): boolean {
  if (err === null || typeof err !== "object") return false;
  const e = err as {
    readonly killed?: unknown;
    readonly signal?: unknown;
    readonly code?: unknown;
  };
  if (e.killed === true) return true;
  if (e.signal === "SIGTERM" || e.signal === "SIGKILL") return true;
  if (e.code === "ETIMEDOUT") return true;
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

/** Sync subprocess with a mandatory clock. Timeout → typed error + stage. */
export function execFileWithTimeout(
  file: string,
  args: readonly string[],
  opts: ExecFileTimeoutOptions,
): string {
  const timeoutMs = effectiveSubprocessTimeoutMs(
    opts.timeoutMs ?? DEFAULT_SUBPROCESS_TIMEOUT_MS,
  );
  try {
    const hasInput = opts.input !== undefined;
    return execFileSync(file, [...args], {
      cwd: opts.cwd,
      env: opts.env,
      ...(hasInput ? { input: opts.input } : {}),
      encoding: "utf8",
      stdio: hasInput ? ["pipe", "pipe", "pipe"] : ["ignore", "pipe", "pipe"],
      timeout: timeoutMs,
      maxBuffer: opts.maxBuffer ?? 16 * 1024 * 1024,
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

/** Async subprocess with a clock (parallel smoke overlaps wall time). */
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
          const enriched = err as Error & {
            stdout?: string;
            stderr?: string;
          };
          if (typeof stdout === "string") enriched.stdout = stdout;
          if (typeof stderr === "string") {
            enriched.stderr = stderr;
            if (stderr.length > 0) {
              enriched.message = `${enriched.message}\n${stderr}`;
            }
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

export interface SpawnDetachedOptions {
  readonly stage: string;
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly stdio?: SpawnOptions["stdio"];
  readonly detached?: boolean;
}

/** Sole production `spawn` surface (chokepoint). Launch is not a wait. */
export function spawnDetached(
  command: string,
  args: readonly string[],
  opts: SpawnDetachedOptions,
): ChildProcess {
  void opts.stage;
  return spawn(command, [...args], {
    cwd: opts.cwd,
    env: opts.env,
    detached: opts.detached ?? true,
    stdio: opts.stdio ?? "ignore",
  });
}

/**
 * Provider/HTTP seam: race work against AbortSignal.timeout.
 * Non-cooperative hang still cannot block forever.
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

/**
 * Host one-shot with clock — no retry (exactly-once). Prefer this for git/gh.
 * Stage name is required so timeouts are attributable.
 */
export function shWithClock(
  file: string,
  args: readonly string[],
  opts?: {
    readonly stage?: string;
    readonly cwd?: string;
    readonly timeoutMs?: number;
  },
): string {
  const stage = opts?.stage ?? `subprocess:${file}`;
  return execFileWithTimeout(file, [...args], {
    stage,
    timeoutMs: effectiveSubprocessTimeoutMs(
      opts?.timeoutMs ?? DEFAULT_SUBPROCESS_TIMEOUT_MS,
    ),
    cwd: opts?.cwd,
  }).trim();
}
