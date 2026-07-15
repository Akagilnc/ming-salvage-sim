/**
 * #899 hotfix (2026-07-15) — keep the monitored bridge's stdout alive while
 * Sandcastle runs.
 *
 * The #684 idle monitor judges worker liveness ONLY by growth of the bridge
 * child's stdout log (worker-logs/<step>.log). Sandcastle in log-to-file mode
 * drains the entire agent stream to its own file and keeps stdout byte-silent
 * between the startup pointer lines and the final output, so every healthy
 * sandbox step longer than the idle threshold was killed as a hang: #899's
 * resumed S2 died 3× at exactly the 10-minute general tier, and #808 had
 * already met the same disease on Sonnet legs (it widened Claude's tier to
 * 30 minutes instead of fixing the channel).
 *
 * Fix at the sc.run boundary: inject Sandcastle's own file-logging
 * `onAgentStreamEvent` callback (built for "forwarding the agent's output
 * stream to external observability systems") and forward real agent activity
 * to stdout as a throttled heartbeat. A live agent keeps the monitored log
 * growing; a truly silent agent produces no heartbeat, so the idle threshold
 * still fires. Sandcastle swallows callback errors, so the writer needs no
 * guard of its own.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

/** One heartbeat line at most per window; well under every idle tier. */
export const STREAM_HEARTBEAT_THROTTLE_MS = 30_000;

interface HeartbeatSandboxOptions {
  /** Optional like sandcastle's RunOptions.cwd; defaults to process.cwd(). */
  readonly cwd?: string;
  readonly name?: string;
  readonly logging?: unknown;
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
