/**
 * #684 — structured monitor handles produced atomically at CLI worker dispatch.
 *
 * Alive/idle/progress judgment and kill operations go ONLY through a
 * {@link WorkerMonitorHandle}. No global process-name matching APIs are provided.
 */

import type { ChildProcess } from "node:child_process";
import {
  ExternalCallTimeoutError,
  effectiveSubprocessTimeoutMs,
  shWithClock,
  spawnDetached,
  DEFAULT_SUBPROCESS_TIMEOUT_MS,
} from "./externalCall.js";
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

/** Spawn-ack wall budget (#884 cmr r8 — every external wait carries a clock). */
export const SPAWN_ACK_TIMEOUT_MS = DEFAULT_SUBPROCESS_TIMEOUT_MS;

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
  readonly resultPath?: string;
  /**
   * Optional identity reader at spawn (#684 R2). Tests inject this so the
   * dispatch path does not require a real `ps` in restricted sandboxes.
   */
  readonly readInstanceId?: (pid: number) => string | undefined;
}

export interface MonitoredCliDispatchResult {
  readonly handle: WorkerMonitorHandle;
  readonly child: ChildProcess;
}

export interface KillWorkerTreeResult {
  readonly killedPids: readonly number[];
  readonly residualPids: readonly number[];
  /** PIDs left alive without sufficient per-member identity evidence. */
  readonly unverifiedPids: readonly number[];
  /**
   * True when the handle PID is alive but its process start identity no longer
   * matches — the PID was reused by an unrelated process and kill was refused.
   */
  readonly skippedDueToPidReuse?: boolean;
}

export interface WorkerMonitorDeps {
  readonly isPidAlive?: (pid: number) => boolean;
  readonly listChildPids?: (pid: number) => readonly number[];
  /** Parent pid of a process (for per-pid parentage re-verify on kill, #684 R2). */
  readonly readParentPid?: (pid: number) => number | undefined;
  readonly killPid?: (pid: number, signal: NodeJS.Signals) => void;
  readonly statLog?: (logPath: string) => LogActivitySnapshot;
  readonly readLogTail?: (logPath: string) => string;
  readonly sleepMs?: (ms: number) => Promise<void>;
  /** OS-level process start identity for PID-reuse guards (#684 R1/R2). */
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
      const out = shWithClock(
        "ps",
        ["-o", "pid=", "-ppid", String(pid)],
        { stage: "dispatch:ps-children" },
      );
      return out
        .split(/\r?\n/)
        .map((line) => Number.parseInt(line.trim(), 10))
        .filter((childPid) => Number.isInteger(childPid) && childPid > 0);
    } catch {
      return [];
    }
  },
  readParentPid: (pid) => {
    if (!Number.isInteger(pid) || pid <= 0) return undefined;
    try {
      const out = shWithClock(
        "ps",
        ["-o", "ppid=", "-p", String(pid)],
        { stage: "dispatch:ps-parent" },
      );
      const ppid = Number.parseInt(out, 10);
      return Number.isInteger(ppid) && ppid > 0 ? ppid : undefined;
    } catch {
      return undefined;
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
  // Some supported platforms do not expose `ps`/an equivalent process-start
  // identity reader. In that documented boundary, only accept the
  // dispatch-scoped fallback for this exact PID; Unix-like platforms still
  // require the real start identity match above this comparison.
  if (liveId === undefined) {
    return handle.instanceId.startsWith(`spawned:${handle.pid}:`);
  }
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
  // Step logs are deliberately append-only across dispatches. Capture the
  // boundary before this child inherits the append fd so later consumers can
  // inspect only this worker's output.
  const logStartOffset = existsSync(logPath) ? statSync(logPath).size : 0;
  const logFd = openSync(logPath, "a");
  const dispatchedAt = new Date().toISOString();

  // #884: spawn only via externalCall chokepoint. detached:true gives the
  // worker its own process-group boundary; termination still goes through
  // individually verified killPid calls, #684 R2. Spawn-ack wait below carries
  // the wall clock (ExternalCallTimeoutError).
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

  // `child.pid` is assigned before the OS process is necessarily visible to
  // `ps`. Wait for Node's spawn notification before capturing the identity so
  // a freshly spawned worker does not get an artificial fallback identity
  // that can never match a later liveness check. Clocked (#884 cmr r8).
  const spawnStage = `dispatch:${input.stepId}:spawn`;
  const spawnTimeoutMs = effectiveSubprocessTimeoutMs(SPAWN_ACK_TIMEOUT_MS);
  await new Promise<void>((resolve, reject) => {
    if (child.exitCode !== null) {
      resolve();
      return;
    }
    const timer = setTimeout(() => {
      child.removeListener("spawn", onSpawn);
      child.removeListener("error", onError);
      // Clock fires → typed timeout only. Do NOT signal the child here
      // (#873 kill-axis / cmr r10): spawn-ack timeout is not an idle/hang
      // judgment, instance id is not yet captured, and a bare-pid signal
      // can hit a reused PID. Termination stays on the post-handle idle
      // path that verifies process identity.
      reject(
        new ExternalCallTimeoutError({
          stage: spawnStage,
          timeoutMs: spawnTimeoutMs,
          seam: "subprocess",
        }),
      );
    }, spawnTimeoutMs);
    const onSpawn = (): void => {
      clearTimeout(timer);
      child.removeListener("error", onError);
      resolve();
    };
    const onError = (err: Error): void => {
      clearTimeout(timer);
      child.removeListener("spawn", onSpawn);
      reject(err);
    };
    child.once("spawn", onSpawn);
    child.once("error", onError);
  });

  // Capture OS start identity immediately so resume/kill can refuse PID reuse.
  // Injectable for tests that must not call real `ps` (#684 R2).
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
    completionSignal: input.completionSignal,
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
 * True when `pid` is still safe to signal for this handle (#684 R2):
 *   - root: live instance identity must match the handle
 *   - child: still parented under a pid in `trustedTree` (parentage re-verify)
 *     AND its start identity is unchanged since the pre-kill snapshot when known
 */
export function pidSafeToSignal(
  pid: number,
  handle: WorkerMonitorHandle,
  trustedTree: ReadonlySet<number>,
  instanceAtCollect: ReadonlyMap<number, string | undefined>,
  deps?: WorkerMonitorDeps,
): boolean {
  const d = resolveDeps(deps);
  if (!d.isPidAlive(pid)) return false;

  if (pid === handle.pid) {
    return instanceMatchesHandle(handle, deps);
  }

  // Per-pid identity: refuse if the live process is a different instance than
  // the one we observed when walking the tree (PID slot reuse of a child).
  const expectedId = instanceAtCollect.get(pid);
  const liveId = d.readInstanceId(pid);
  // No evidence, no kill: a child absent from the collect snapshot, or a child
  // whose identity read failed during collection, is never safe to signal. A
  // later readable identity may belong to a reused PID.
  if (!instanceAtCollect.has(pid) || expectedId === undefined) {
    return false;
  }
  if (liveId !== undefined && liveId !== expectedId) {
    return false;
  }
  // If we cannot read a live identity for a non-root pid, refuse (fail-closed).
  if (liveId === undefined) return false;

  // Parentage re-verify: the live parent must still be in the trusted tree
  // (or be the handle root that still matches). Re-parent-to-init fails this
  // check — those orphans are reported as an unverified boundary instead.
  const parent = d.readParentPid(pid);
  if (parent === undefined) return false;
  if (parent === handle.pid) {
    return instanceMatchesHandle(handle, deps);
  }
  return trustedTree.has(parent);
}

/**
 * Kill only the handle pid tree, then verify no residue remains.
 *
 * Residual check covers:
 *   (1) the pre-kill tree snapshot, and
 *   (2) a re-collected tree from the root if it is still the same instance
 *       (captures children dynamically spawned during the kill window).
 *
 * Re-parent to init / PID 1: children that re-parent to init (or another
 * unrelated process) after their parent dies cannot be discovered via PPID walk
 * from the original root. They remain a documented `unverifiedPids` boundary;
 * group membership is not identity evidence, so no process-group signal is
 * used to reach them.
 *
 * PID-reuse guard: if the handle PID is alive but its instance identity no
 * longer matches, refuse to signal any process and report `skippedDueToPidReuse`.
 * Every pid (root and children) is identity- or parentage-checked before signal.
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
      unverifiedPids: [],
      skippedDueToPidReuse: true,
    };
  }

  const tree = [...collectPidTree(handle.pid, deps)];
  const trustedTree = new Set(tree);
  const instanceAtCollect = new Map<number, string | undefined>();
  for (const pid of tree) {
    instanceAtCollect.set(pid, d.readInstanceId(pid));
  }
  const killed = new Set<number>();

  const trySignal = (signal: NodeJS.Signals) => {
    // Bottom-up: children before parents, reducing re-parent-to-init orphans.
    for (let i = tree.length - 1; i >= 0; i--) {
      const pid = tree[i]!;
      if (
        !pidSafeToSignal(pid, handle, trustedTree, instanceAtCollect, deps)
      ) {
        continue;
      }
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
  const unverified = new Set<number>();
  for (const pid of tree) {
    if (!d.isPidAlive(pid)) continue;
    if (pidSafeToSignal(pid, handle, trustedTree, instanceAtCollect, deps)) {
      residual.add(pid);
    } else {
      // No evidence, no kill: report the boundary instead of widening the
      // signal target beyond individually verified members.
      unverified.add(pid);
    }
  }
  // Re-collect while the original root instance is still alive — catches children
  // that appeared during the kill window (dynamic spawn / late re-parent under root).
  if (instanceMatchesHandle(handle, deps)) {
    for (const pid of collectPidTree(handle.pid, deps)) {
      if (!d.isPidAlive(pid)) continue;
      if (pidSafeToSignal(pid, handle, trustedTree, instanceAtCollect, deps)) {
        residual.add(pid);
      } else {
        unverified.add(pid);
      }
    }
  }

  return {
    killedPids: [...killed],
    residualPids: [...residual],
    unverifiedPids: [...unverified],
  };
}
