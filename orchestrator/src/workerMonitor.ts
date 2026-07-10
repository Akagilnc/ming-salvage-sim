/**
 * #684 — structured monitor handles produced atomically at CLI worker dispatch.
 *
 * Alive/idle/progress judgment and kill operations go ONLY through a
 * {@link WorkerMonitorHandle}. No global process-name matching APIs are provided.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { execFileSync } from "node:child_process";
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
  readonly completionSignal: string;
  readonly stepId: string;
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly logBasename?: string;
}

export interface MonitoredCliDispatchResult {
  readonly handle: WorkerMonitorHandle;
  readonly child: ChildProcess;
}

export interface KillWorkerTreeResult {
  readonly killedPids: readonly number[];
  readonly residualPids: readonly number[];
  /**
   * True when the handle PID is alive but its process start identity no longer
   * matches — the PID was reused by an unrelated process and kill was refused.
   */
  readonly skippedDueToPidReuse?: boolean;
}

export interface WorkerMonitorDeps {
  readonly isPidAlive?: (pid: number) => boolean;
  readonly listChildPids?: (pid: number) => readonly number[];
  readonly killPid?: (pid: number, signal: NodeJS.Signals) => void;
  readonly statLog?: (logPath: string) => LogActivitySnapshot;
  readonly readLogTail?: (logPath: string) => string;
  readonly sleepMs?: (ms: number) => Promise<void>;
  /** OS-level process start identity for PID-reuse guards (#684 R1). */
  readonly readInstanceId?: (pid: number) => string | undefined;
}

const defaultDeps: Required<WorkerMonitorDeps> = {
  isPidAlive: (pid) => {
    if (!Number.isInteger(pid) || pid <= 0) return false;
    try {
      process.kill(pid, 0);
      return true;
    } catch (err) {
      const code = (err as NodeJS.ErrnoException).code;
      if (code === "ESRCH") return false;
      if (code === "EPERM") return true;
      return false;
    }
  },
  listChildPids: (pid) => {
    if (!Number.isInteger(pid) || pid <= 0) return [];
    try {
      const out = execFileSync("ps", ["-o", "pid=", "-ppid", String(pid)], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      });
      return out
        .split(/\r?\n/)
        .map((line) => Number.parseInt(line.trim(), 10))
        .filter((childPid) => Number.isInteger(childPid) && childPid > 0);
    } catch {
      return [];
    }
  },
  killPid: (pid, signal) => {
    process.kill(pid, signal);
  },
  statLog: (logPath) => {
    const stat = statSync(logPath);
    return { sizeBytes: stat.size, mtimeMs: stat.mtimeMs };
  },
  readLogTail: (logPath) => readFileSync(logPath, "utf8"),
  sleepMs: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  readInstanceId: (pid) => readProcessInstanceId(pid),
};

/** Read a stable process-start identity string for PID-reuse guards. */
export function readProcessInstanceId(pid: number): string | undefined {
  if (!Number.isInteger(pid) || pid <= 0) return undefined;
  try {
    const out = execFileSync("ps", ["-p", String(pid), "-o", "lstart="], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    return out.length > 0 ? out : undefined;
  } catch {
    return undefined;
  }
}

function resolveDeps(deps?: WorkerMonitorDeps): Required<WorkerMonitorDeps> {
  return { ...defaultDeps, ...deps };
}

/** True when the live PID still matches the handle's recorded instance identity. */
export function instanceMatchesHandle(
  handle: WorkerMonitorHandle,
  deps?: WorkerMonitorDeps,
): boolean {
  const d = resolveDeps(deps);
  if (!d.isPidAlive(handle.pid)) return false;
  const liveId = d.readInstanceId(handle.pid);
  if (liveId === undefined) return false;
  return liveId === handle.instanceId;
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
    typeof handle.completionSignal === "string" &&
    handle.completionSignal.length > 0 &&
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

/** Dispatch a background CLI worker and atomically produce its monitor handle. */
export async function dispatchMonitoredCliWorker(
  input: MonitoredCliDispatchInput,
): Promise<MonitoredCliDispatchResult> {
  mkdirSync(input.logDir, { recursive: true });
  const logBasename = input.logBasename ?? `${input.stepId}.log`;
  const logPath = join(input.logDir, logBasename);
  const logFd = openSync(logPath, "a");
  const dispatchedAt = new Date().toISOString();

  const child = spawn(input.command, [...input.args], {
    cwd: input.cwd,
    env: input.env,
    detached: false,
    stdio: ["ignore", logFd, logFd],
  });
  closeSync(logFd);

  const pid = child.pid;
  if (pid === undefined || pid <= 0) {
    throw new Error(
      `dispatchMonitoredCliWorker: failed to spawn ${input.command} for ${input.stepId}`,
    );
  }

  // Capture OS start identity immediately so resume/kill can refuse PID reuse.
  const instanceId = readProcessInstanceId(pid) ?? `spawned:${pid}:${dispatchedAt}`;

  appendFileSync(
    logPath,
    `[orchestrator] dispatched ${input.stepId} pid=${pid} pool=${input.poolId} instance=${instanceId} at ${dispatchedAt}\n`,
    "utf8",
  );

  const handle: WorkerMonitorHandle = {
    pid,
    logPath,
    poolId: input.poolId,
    completionSignal: input.completionSignal,
    stepId: input.stepId,
    dispatchedAt,
    instanceId,
  };

  if (!validateMonitorHandle(handle)) {
    throw new Error(`dispatchMonitoredCliWorker: produced invalid monitor handle for ${input.stepId}`);
  }

  return { handle, child };
}

/**
 * Alive check scoped to the handle pid + instance identity only — never global
 * name matching. A live PID with a different start identity is treated as dead
 * (PID reuse), so hang-kill will not target an unrelated process.
 */
export function isWorkerAlive(
  handle: WorkerMonitorHandle,
  deps?: WorkerMonitorDeps,
): boolean {
  return instanceMatchesHandle(handle, deps);
}

/**
 * Read log growth signals for idle/progress judgment (#684).
 * Returns `undefined` when the log file is missing — callers must treat missing
 * evidence as "not idle" (fail-closed: no evidence ⇒ do not kill).
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
 * True when the handle log has not grown or changed within the idle threshold.
 * Missing log ⇒ false (no evidence = do not treat as idle / do not hang-kill).
 */
export function isWorkerIdle(
  handle: WorkerMonitorHandle,
  idleThresholdMs: number,
  previous: LogActivitySnapshot,
  deps?: WorkerMonitorDeps,
): boolean {
  const current = readLogActivity(handle, deps);
  if (current === undefined) return false;
  if (current.sizeBytes > previous.sizeBytes) return false;
  if (current.mtimeMs > previous.mtimeMs) return false;
  if (idleThresholdMs <= 0) return true;
  return Date.now() - current.mtimeMs >= idleThresholdMs;
}

/** Detect the handle's expected completion signal in its log file. */
export function hasCompletionSignalInLog(
  handle: WorkerMonitorHandle,
  deps?: WorkerMonitorDeps,
): boolean {
  const d = resolveDeps(deps);
  if (!existsSync(handle.logPath)) return false;
  return d.readLogTail(handle.logPath).includes(handle.completionSignal);
}

/** Collect the full pid subtree rooted at the handle pid. */
export function collectPidTree(
  rootPid: number,
  deps?: WorkerMonitorDeps,
): readonly number[] {
  const d = resolveDeps(deps);
  const seen = new Set<number>();
  const queue = [rootPid];
  const tree: number[] = [];

  while (queue.length > 0) {
    const pid = queue.shift()!;
    if (seen.has(pid)) continue;
    seen.add(pid);
    tree.push(pid);
    for (const child of d.listChildPids(pid)) {
      if (!seen.has(child)) queue.push(child);
    }
  }

  return tree;
}

/**
 * Kill only the handle pid tree, then verify no residue remains.
 *
 * Residual check covers:
 *   (1) the pre-kill tree snapshot, and
 *   (2) a re-collected tree from the root if it is still the same instance
 *       (captures children dynamically spawned during the kill window).
 *
 * LIMIT (re-parent to init / PID 1): children that re-parent to init (or another
 * unrelated process) after their parent dies cannot be discovered via PPID walk
 * from the original root. Mitigation: signal bottom-up (children before parents)
 * so descendants receive SIGTERM/SIGKILL before re-parenting. Orphans that escape
 * this window are outside the residual check by design.
 *
 * PID-reuse guard: if the handle PID is alive but its instance identity no
 * longer matches, refuse to signal any process and report `skippedDueToPidReuse`.
 */
export async function killWorkerTree(
  handle: WorkerMonitorHandle,
  deps?: WorkerMonitorDeps,
): Promise<KillWorkerTreeResult> {
  const d = resolveDeps(deps);

  // Refuse kill when the PID no longer refers to the original worker instance.
  if (d.isPidAlive(handle.pid) && !instanceMatchesHandle(handle, deps)) {
    return {
      killedPids: [],
      residualPids: [],
      skippedDueToPidReuse: true,
    };
  }

  const tree = [...collectPidTree(handle.pid, deps)];
  const killed = new Set<number>();

  const trySignal = (signal: NodeJS.Signals) => {
    // Bottom-up: children before parents, reducing re-parent-to-init orphans.
    for (let i = tree.length - 1; i >= 0; i--) {
      const pid = tree[i]!;
      if (!d.isPidAlive(pid)) continue;
      // Only signal the root under identity guard; children are trusted via tree walk.
      if (pid === handle.pid && !instanceMatchesHandle(handle, deps)) continue;
      try {
        d.killPid(pid, signal);
        killed.add(pid);
      } catch {
        // Process may have already exited between the alive check and kill.
      }
    }
  };

  trySignal("SIGTERM");
  await d.sleepMs(100);
  trySignal("SIGKILL");

  const residual = new Set<number>();
  for (const pid of tree) {
    if (d.isPidAlive(pid)) residual.add(pid);
  }
  // Re-collect while the original root instance is still alive — catches children
  // that appeared during the kill window (dynamic spawn / late re-parent under root).
  if (instanceMatchesHandle(handle, deps)) {
    for (const pid of collectPidTree(handle.pid, deps)) {
      if (d.isPidAlive(pid)) residual.add(pid);
    }
  }

  return {
    killedPids: [...killed],
    residualPids: [...residual],
  };
}
