/**
 * #684 — shared helpers so RealBackend / RealFamilyBackend can participate in
 * the production monitored CLI dispatch path (resolveCliMonitorDispatch +
 * awaitMonitoredCliWorker).
 *
 * Production shape: parent spawns a host-side bridge child via
 * {@link dispatchMonitoredCliWorker}; the child re-enters `dispatchWorker` /
 * `dispatchFamilyWorker` with `ORCHESTRATOR_CLI_MONITOR_CHILD=1` so the hooks
 * short-circuit and the existing container seam does the work. The parent holds
 * the monitor handle (pid/log/pool/signal/instance) for hang judgment and kill.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

import {
  isQuotaWaitForResetError,
  tryParseQuotaWaitForResetBridge,
} from "./quotaProbe.js";
import { poolIdForWorker } from "./workerMonitor.js";
import type {
  CliMonitorSpawnSpec,
  DispatchContext,
  WorkerKind,
  WorkerLandingPayload,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "./types.js";

/** Env flag set on the monitored bridge child so hooks do not re-wrap. */
export const CLI_MONITOR_CHILD_ENV = "ORCHESTRATOR_CLI_MONITOR_CHILD";

const MONITORED_KINDS: ReadonlySet<WorkerKind> = new Set([
  "coder",
  "reviewer",
  "ship",
  "cmr",
  "verify",
  "fixer",
  "cleanup",
  "docRelease",
]);

/** Internal provenance marker for a result synthesized because no sidecar existed. */
const MISSING_MONITOR_SIDECAR_RESULT = Symbol("missingMonitorSidecarResult");

function markMissingMonitorSidecarResult(result: WorkerResult): WorkerResult {
  return Object.assign(result, { [MISSING_MONITOR_SIDECAR_RESULT]: true });
}

export type CliMonitorBackendKind = "real" | "realFamily";

export interface CliMonitorJobFile {
  readonly backendKind: CliMonitorBackendKind;
  readonly backendOpts: unknown;
  readonly spec: WorkerSpec;
  readonly ctx: DispatchContext;
  readonly landing?: WorkerLandingPayload;
  readonly resultPath: string;
}

export function isCliMonitorChildProcess(): boolean {
  return process.env[CLI_MONITOR_CHILD_ENV] === "1";
}

export function isMonitoredWorkerKind(kind: WorkerKind): boolean {
  return MONITORED_KINDS.has(kind);
}

/** Log directory for monitor handles: durable telemetry dir preferred. */
export function resolveMonitorLogDir(ctx: DispatchContext): string | undefined {
  if (ctx.telemetryDir !== undefined && ctx.telemetryDir.length > 0) {
    return join(ctx.telemetryDir, "worker-logs");
  }
  if (ctx.stateDir !== undefined && ctx.stateDir.length > 0) {
    return join(ctx.stateDir, "worker-logs");
  }
  if (ctx.worktree?.path !== undefined && ctx.worktree.path.length > 0) {
    return join(ctx.worktree.path, ".orchestrator-worker-logs");
  }
  return undefined;
}

export function monitorJobPath(logDir: string, stepId: string): string {
  return join(logDir, `${stepId}.job.json`);
}

export function monitorResultPath(
  logDir: string,
  stepId: string,
  dispatchId?: string,
): string {
  return join(
    logDir,
    dispatchId === undefined
      ? `${stepId}.result.json`
      : `${stepId}.${dispatchId}.result.json`,
  );
}

/** Resolve the compiled (or same-dir) host CLI bridge runner path. */
export function resolveHostCliWorkerRunnerPath(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  return join(here, "hostCliWorkerRunner.js");
}

/**
 * Build the CliMonitorSpawnSpec for a productive worker, writing the job file
 * the bridge child will consume. Returns undefined when monitoring cannot run
 * (child process, non-productive kind, or no log sink).
 */
export function buildCliMonitorSpawnSpec(input: {
  readonly backendKind: CliMonitorBackendKind;
  readonly backendOpts: unknown;
  readonly spec: WorkerSpec;
  readonly ctx: DispatchContext;
  readonly landing?: WorkerLandingPayload;
  readonly runnerPath?: string;
}): CliMonitorSpawnSpec | undefined {
  if (isCliMonitorChildProcess()) return undefined;
  if (!isMonitoredWorkerKind(input.spec.kind)) return undefined;

  const logDir = resolveMonitorLogDir(input.ctx);
  if (logDir === undefined) return undefined;

  mkdirSync(logDir, { recursive: true });
  const resultPath = monitorResultPath(logDir, input.spec.id, randomUUID());
  const jobPath = monitorJobPath(logDir, input.spec.id);
  const job: CliMonitorJobFile = {
    backendKind: input.backendKind,
    backendOpts: input.backendOpts,
    spec: input.spec,
    ctx: input.ctx,
    ...(input.landing !== undefined ? { landing: input.landing } : {}),
    resultPath,
  };
  writeFileSync(jobPath, `${JSON.stringify(job)}\n`, "utf8");

  const runnerPath = input.runnerPath ?? resolveHostCliWorkerRunnerPath();
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    [CLI_MONITOR_CHILD_ENV]: "1",
  };

  return {
    command: process.execPath,
    args: [runnerPath, jobPath],
    logDir,
    // A relay can retain the same model while switching its billing/provider
    // pool. Monitoring must attribute the child to that active pool, not infer
    // it again from the model name.
    poolId: input.ctx.billingPool ?? poolIdForWorker(input.spec),
    completionSignal: input.spec.completionSignal,
    stepId: input.spec.id,
    ...(input.ctx.worktree?.path !== undefined
      ? { cwd: input.ctx.worktree.path }
      : {}),
    env,
    logBasename: `${input.spec.id}.log`,
    resultPath,
  };
}

/**
 * Map a finished monitored CLI child into a WorkerResult by reading the result
 * sidecar the bridge wrote (fail-closed when missing / unreadable).
 */
export function workerResultFromMonitorSidecar(
  handle: WorkerMonitorHandle,
  exitCode: number | null,
): WorkerResult {
  const resultPath = handle.resultPath;
  const legacyPath = monitorResultPath(dirname(handle.logPath), handle.stepId);
  const expectedPath = resultPath ?? legacyPath;
  const path = resultPath !== undefined
    ? (existsSync(resultPath) ? resultPath : undefined)
    : (existsSync(legacyPath) ? legacyPath : undefined);

  if (path !== undefined) {
    try {
      const parsed = JSON.parse(readFileSync(path, "utf8")) as WorkerResult;
      if (
        parsed !== null &&
        typeof parsed === "object" &&
        "kind" in parsed &&
        typeof (parsed as { kind: unknown }).kind === "string"
      ) {
        // #683: bridge child serializes QuotaWaitForResetError into failed.reason
        // — re-throw so runner park machinery receives the real park error.
        if (
          parsed.kind === "failed" &&
          typeof parsed.reason === "string"
        ) {
          const quotaErr = tryParseQuotaWaitForResetBridge(parsed.reason);
          if (quotaErr !== undefined) throw quotaErr;
        }
        return parsed;
      }
    } catch (err) {
      // Re-throw reconstructed quota park; other parse failures fall through.
      if (isQuotaWaitForResetError(err)) {
        throw err;
      }
      // fall through to exit-code mapping
    }
  }

  if (exitCode === 0) {
    return markMissingMonitorSidecarResult({
      kind: "malformed",
      reason:
        `monitored CLI worker ${handle.stepId} exited 0 but wrote no usable ` +
        `WorkerResult sidecar at ${expectedPath}`,
    });
  }
  return markMissingMonitorSidecarResult({
    kind: "failed",
    reason:
      `monitored CLI worker ${handle.stepId} exited ${exitCode ?? "null"} ` +
      `without a WorkerResult sidecar (pool=${handle.poolId})`,
  });
}

/**
 * True only for the structured fallback produced by
 * {@link workerResultFromMonitorSidecar} when no usable result sidecar exists.
 * Used by the signal-kill path: honor a real sidecar outcome even after
 * SIGTERM; only synthesize `killed by signal` when the mapper found nothing
 * durable.
 */
export function isMissingMonitorSidecarResult(result: WorkerResult): boolean {
  return (
    result as WorkerResult & {
      readonly [MISSING_MONITOR_SIDECAR_RESULT]?: boolean;
    }
  )[MISSING_MONITOR_SIDECAR_RESULT] === true;
}
