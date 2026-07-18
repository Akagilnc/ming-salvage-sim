import { spawn } from "node:child_process";

import {
  existsSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { dispatchWorkerWithMonitor } from "../../src/dispatchWorker.js";

import {
  dispatchMonitoredCliWorker,
  monitorHandleFromLedger,
  poolIdForWorker,
  readLogActivity,
  silenceWholeMinutes,
  terminateSpawnedChild,
  validateMonitorHandle,
} from "../../src/workerMonitor.js";

import type {
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  LedgerEntry,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

function baseHandle(
  overrides: Partial<WorkerMonitorHandle> &
    Pick<WorkerMonitorHandle, "pid" | "logPath">,
): WorkerMonitorHandle {
  return {
    poolId: "grok/composer",
    stepId: "S7",
    dispatchedAt: new Date().toISOString(),
    instanceId: "test-instance",
    ...overrides,
  };
}

function sleepWorker(
  logDir: string,
  poolId: string,
  stepId: string,
): ReturnType<typeof dispatchMonitoredCliWorker> {
  return dispatchMonitoredCliWorker({
    command: process.platform === "win32" ? "ping" : "sleep",
    args: process.platform === "win32" ? ["-n", "600"] : ["600"],
    logDir,
    poolId,
    stepId,
    logBasename: `${stepId}.log`,
    readInstanceId: () => `test-instance-${stepId}`,
  });
}

export {
  spawn,
  existsSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  describe,
  expect,
  it,
  dispatchWorkerWithMonitor,
  dispatchMonitoredCliWorker,
  monitorHandleFromLedger,
  poolIdForWorker,
  readLogActivity,
  silenceWholeMinutes,
  terminateSpawnedChild,
  validateMonitorHandle,
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  LedgerEntry,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
  baseHandle,
  sleepWorker,
};
