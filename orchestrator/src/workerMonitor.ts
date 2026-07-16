/**
 * #684 / #937 — structured monitor handles produced atomically at CLI worker
 * dispatch. Process ownership is the exact ChildProcess / process-group handle
 * returned at spawn (#934 ID-006). Idle kill, PID-tree collection, and spawn-ack
 * wall clocks are deleted; last-activity is observational only (ID-007).
 */

import type { ChildProcess } from "node:child_process";
import { shWithClock, spawnDetached } from "./externalCall.js";
import {
  appendFileSync,
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  statSync,
} from "node:fs";
import { join } from "node:path";

import type { LedgerEntry, WorkerMonitorHandle, WorkerSpec } from "./types.js";

export type { WorkerMonitorHandle } from "./types.js";

export interface LogActivitySnapshot {
  readonly sizeBytes: number;
  readonly mtimeMs: number;
}

export interface MonitoredCliDispatchInput {
  readonly command: string;
  readonly args: readonly string[];
  readonly logDir: string;
  readonly poolId: string;
  readonly stepId: string;
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly logBasename?: string;
  readonly resultPath?: string;
  /**
   * Optional identity reader at spawn. Tests inject this so the dispatch path
   * does not require a real `ps` in restricted sandboxes.
   */
  readonly readInstanceId?: (pid: number) => string | undefined;
}

export interface MonitoredCliDispatchResult {
  readonly handle: WorkerMonitorHandle;
  readonly child: ChildProcess;
}

export interface WorkerMonitorDeps {
  readonly statLog?: (logPath: string) => LogActivitySnapshot;
  readonly readLogTail?: (logPath: string) => string;
  readonly sleepMs?: (ms: number) => Promise<void>;
  readonly readInstanceId?: (pid: number) => string | undefined;
  /** Signal a process group (negative pid) or single pid. */
  readonly killPid?: (pid: number, signal: NodeJS.Signals) => void;
}

const defaultDeps: Required<
  Pick<WorkerMonitorDeps, "statLog" | "readLogTail" | "sleepMs" | "killPid">
> & { readonly readInstanceId: (pid: number) => string | undefined } = {
  statLog: (logPath) => {
    const stat = statSync(logPath);
    return { sizeBytes: stat.size, mtimeMs: stat.mtimeMs };
  },
  readLogTail: (logPath) => readFileSync(logPath, "utf8"),
  sleepMs: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  readInstanceId: (pid) => readProcessInstanceId(pid),
  killPid: (pid, signal) => {
    process.kill(pid, signal);
  },
};

function resolveDeps(deps?: WorkerMonitorDeps): typeof defaultDeps {
  return { ...defaultDeps, ...deps };
}

/** Read a stable process-start identity string when the platform exposes one. */
export function readProcessInstanceId(pid: number): string | undefined {
  if (!Number.isInteger(pid) || pid <= 0) return undefined;
  try {
    // Best-effort; missing `ps` falls back to spawn-scoped identity below.
    const out = shWithClock(
      "ps",
      ["-p", String(pid), "-o", "lstart="],
      { stage: "dispatch:ps-lstart" },
    );
    return out.length > 0 ? out : undefined;
  } catch {
    return undefined;
  }
}

/** Validate a persisted/rebuilt monitor handle shape. */
export function validateMonitorHandle(
  handle: WorkerMonitorHandle | undefined,
): handle is WorkerMonitorHandle {
  if (handle === undefined) return false;
  return (
    Number.isInteger(handle.pid) &&
    handle.pid > 0 &&
    typeof handle.logPath === "string" &&
    handle.logPath.length > 0 &&
    typeof handle.poolId === "string" &&
    handle.poolId.length > 0 &&
    typeof handle.stepId === "string" &&
    handle.stepId.length > 0 &&
    typeof handle.dispatchedAt === "string" &&
    handle.dispatchedAt.length > 0 &&
    typeof handle.instanceId === "string" &&
    handle.instanceId.length > 0
  );
}

/** Derive the pool/model identifier carried on a monitor handle. */
export function poolIdForWorker(spec: WorkerSpec): string {
  return `${spec.host}/${spec.model}`;
}

/** Rebuild a monitor handle from a ledger entry after resume (#684). */
export function monitorHandleFromLedger(
  entry: Pick<LedgerEntry, "monitorHandle">,
): WorkerMonitorHandle | undefined {
  const handle = entry.monitorHandle;
  return validateMonitorHandle(handle) ? handle : undefined;
}

/**
 * Dispatch a background CLI worker and atomically produce its monitor handle.
 * #937: no spawn-ack wall clock — ChildProcess is the ownership token.
 */
export async function dispatchMonitoredCliWorker(
  input: MonitoredCliDispatchInput,
): Promise<MonitoredCliDispatchResult> {
  mkdirSync(input.logDir, { recursive: true });
  const logBasename = input.logBasename ?? `${input.stepId}.log`;
  const logPath = join(input.logDir, logBasename);
  // Step logs are deliberately append-only across dispatches. Capture the
  // boundary before this child inherits the append fd so later consumers can
  // inspect only this worker's output.
  const logStartOffset = existsSync(logPath) ? statSync(logPath).size : 0;
  const logFd = openSync(logPath, "a");
  const dispatchedAt = new Date().toISOString();

  // #884: spawn only via externalCall chokepoint. detached:true gives the
  // worker its own process-group boundary so adoption-failure cleanup can
  // signal the exact group (#934 ID-006).
  const child = spawnDetached(input.command, input.args, {
    stage: `dispatch:${input.stepId}:spawn-launch`,
    cwd: input.cwd,
    env: input.env,
    detached: true,
    stdio: ["ignore", logFd, logFd],
  });
  closeSync(logFd);

  const pid = child.pid;
  if (pid === undefined || pid <= 0) {
    throw new Error(
      `dispatchMonitoredCliWorker: failed to spawn ${input.command} for ${input.stepId}`,
    );
  }

  // Await Node's spawn or early exit so `error` is not an unhandled event;
  // there is no 120s spawn-ack wall clock (#934 ID-004).
  await new Promise<void>((resolve, reject) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve();
      return;
    }
    const onSpawn = (): void => {
      child.removeListener("error", onError);
      resolve();
    };
    const onError = (err: Error): void => {
      child.removeListener("spawn", onSpawn);
      reject(err);
    };
    child.once("spawn", onSpawn);
    child.once("error", onError);
  });

  const readId = input.readInstanceId ?? readProcessInstanceId;
  const instanceId = readId(pid) ?? `spawned:${pid}:${dispatchedAt}`;

  appendFileSync(
    logPath,
    `[orchestrator] dispatched ${input.stepId} pid=${pid} pool=${input.poolId} instance=${instanceId} at ${dispatchedAt}\n`,
    "utf8",
  );

  const handle: WorkerMonitorHandle = {
    pid,
    logPath,
    logStartOffset,
    poolId: input.poolId,
    stepId: input.stepId,
    dispatchedAt,
    instanceId,
    ...(input.resultPath !== undefined ? { resultPath: input.resultPath } : {}),
  };

  if (!validateMonitorHandle(handle)) {
    throw new Error(`dispatchMonitoredCliWorker: produced invalid monitor handle for ${input.stepId}`);
  }

  return { handle, child };
}

/**
 * Read log growth signals for observational silence / first-output telemetry
 * (#934 ID-007). Missing log ⇒ undefined (no evidence).
 */
export function readLogActivity(
  handle: WorkerMonitorHandle,
  deps?: WorkerMonitorDeps,
): LogActivitySnapshot | undefined {
  const d = resolveDeps(deps);
  if (!existsSync(handle.logPath)) {
    return undefined;
  }
  return d.statLog(handle.logPath);
}

/**
 * Whole minutes of silence from the last observed log activity (#934 ID-007).
 * Pure report — never triggers kill, retry, relay, park, fail, or exit.
 */
export function silenceWholeMinutes(
  lastActivityMs: number,
  nowMs: number = Date.now(),
): number {
  if (!Number.isFinite(lastActivityMs) || !Number.isFinite(nowMs)) return 0;
  const delta = nowMs - lastActivityMs;
  if (delta < 60_000) return 0;
  return Math.floor(delta / 60_000);
}

/**
 * Exact-handle termination for spawn-adoption failure (#934 ID-006).
 * Signals the detached process group of the ChildProcess when possible;
 * never walks a PID tree or global name match.
 */
export async function terminateSpawnedChild(
  child: ChildProcess,
  deps?: WorkerMonitorDeps,
): Promise<void> {
  const d = resolveDeps(deps);
  if (child.exitCode !== null || child.signalCode !== null) return;

  const signalGroupOrChild = (signal: NodeJS.Signals): void => {
    const pid = child.pid;
    if (pid !== undefined && pid > 0) {
      try {
        // Negative pid = process group (detached:true at spawn).
        d.killPid(-pid, signal);
        return;
      } catch {
        // Fall through to the ChildProcess handle.
      }
    }
    try {
      child.kill(signal);
    } catch {
      // Already exited between checks.
    }
  };

  signalGroupOrChild("SIGTERM");
  await d.sleepMs(100);
  if (child.exitCode === null && child.signalCode === null) {
    signalGroupOrChild("SIGKILL");
  }
}
