/**
 * #899 hotfix / #937 — keep the monitored bridge's stdout alive while
 * Sandcastle runs (observational last-activity / first_output_at only).
 *
 * Host silence sentencing is deleted (#937 / #934 ID-007): silence never
 * kills, retries, or relays. Heartbeats still matter so log last-activity and
 * first_output_at telemetry can observe real agent progress while Sandcastle
 * drains the agent stream to its own file (bridge stdout would otherwise stay
 * silent between startup lines and final output).
 *
 * Inject Sandcastle's file-logging `onAgentStreamEvent` and forward real agent
 * activity to stdout as a throttled heartbeat. Same wrap forces completionSignal: [] (#928).
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

/** One heartbeat line at most per window (observational log growth only). */
export const STREAM_HEARTBEAT_THROTTLE_MS = 30_000;

interface HeartbeatSandboxOptions {
  /** Optional like sandcastle's RunOptions.cwd; defaults to process.cwd(). */
  readonly cwd?: string;
  readonly name?: string;
  readonly logging?: unknown;
  /** #928: sandcastle password shape (string | string[]); production forces `[]`. */
  readonly completionSignal?: string | readonly string[];
}

/** The concrete file-logging shape this helper injects (online r1: typed, not unknown). */
export interface MonitorHeartbeatLogging {
  readonly type: "file";
  readonly path: string;
  readonly onAgentStreamEvent: () => void;
}

/** Host I/O seams, injectable for tests. */
export interface StreamHeartbeatDeps {
  readonly writeLine?: (line: string) => void;
  readonly now?: () => number;
  readonly ensureDir?: (dir: string) => void;
}

/** Mirror of sandcastle's own log-filename sanitizer character class. */
function sanitizeName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9_.-]/g, "-");
}

/**
 * #928 / #919 F2 — shared Sandcastle invoke wrap used by RealBackend and
 * RealFamilyBackend:
 *   - force `completionSignal: []` (omit is NOT off; sandcastle defaults a password)
 *   - inject stream heartbeat for observational log last-activity (not host kill)
 *
 * Behavior-identical to the former dual inlined copies; one helper, two call sites.
 */
export function withSandcastleInvokeDefaults<T extends HeartbeatSandboxOptions>(
  options: T,
  deps?: StreamHeartbeatDeps,
): T & { completionSignal: string[] } {
  return withMonitorStreamHeartbeat(
    {
      ...options,
      completionSignal: [] as string[],
    },
    deps,
  ) as T & { completionSignal: string[] };
}

/**
 * Inject heartbeat file-logging into a Sandcastle run-options object. A run
 * that already carries an explicit `logging` config is returned untouched —
 * the caller owns its observability then.
 */
export function withMonitorStreamHeartbeat<T extends HeartbeatSandboxOptions>(
  options: T,
  deps?: StreamHeartbeatDeps,
  // Injected `logging` always conforms to {@link MonitorHeartbeatLogging};
  // the loose declared type keeps passthrough (caller-owned logging) legal.
): T & { readonly logging?: unknown } {
  if (options.logging !== undefined) return options;

  const writeLine =
    deps?.writeLine ??
    ((line: string) => {
      process.stdout.write(`${line}\n`);
    });
  // Monotonic by default (online r1): a backward wall-clock jump must not
  // suppress heartbeats within the idle window.
  const now = deps?.now ?? (() => performance.now());
  const ensureDir =
    deps?.ensureDir ?? ((dir: string) => mkdirSync(dir, { recursive: true }));

  const name = options.name ?? "agent";
  // Same anchor rule as sandcastle itself: cwd option, else process.cwd().
  const logDir = join(options.cwd ?? process.cwd(), ".sandcastle", "logs");
  try {
    ensureDir(logDir);
  } catch (err) {
    // Observability aid must not kill a healthy step (online r1): fall back
    // to sandcastle's own default logging — no heartbeat, but alive and loud.
    console.warn(
      `[monitor-heartbeat] log dir unavailable, heartbeat disabled for ${name}: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
    return options;
  }

  let lastBeatMs = Number.NEGATIVE_INFINITY;
  const logging = {
    type: "file" as const,
    path: join(logDir, `${sanitizeName(name)}.log`),
    onAgentStreamEvent: () => {
      const t = now();
      if (t - lastBeatMs < STREAM_HEARTBEAT_THROTTLE_MS) return;
      lastBeatMs = t;
      writeLine(`[monitor-heartbeat] ${name} agent stream active`);
    },
  };
  return { ...options, logging };
}
