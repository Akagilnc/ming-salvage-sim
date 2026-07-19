import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";

import { execFileSync } from "node:child_process";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { dispatchWorkerWithMonitor } from "../../src/dispatchWorker.js";

import { workerResultFromMonitorSidecar } from "../../src/cliMonitorHooks.js";

import { resolveRouteModels, routeSmokeEntries } from "../../src/modelRoutes.js";
import { smokedRoute } from "../model-route-fixtures.shared.js";

import {
  appendTelemetryRecord,
  buildCollectStamp,
  buildDispatchStamp,
  buildEnvironmentStamp,
  buildCommitStamp,
  buildReviewRoundStamp,
  buildVerificationStamp,
  categoryFromReason,
  classifyWorkerTerminal,
  clearTelemetryRunEnvironment,
  collectCommitDiffAuditAsync,
  collectCommitMetricsAsync,
  commitsBetweenAsync,
  configureTelemetryFromWorkerImage,
  configureTelemetryRunEnvironment,
  durableTelemetryDirForSingleSlice,
  ensureEnvironmentStamp,
  extractClaudeTokens,
  extractCodexTokens,
  extractTokensFromLog,
  hashDirectoryContents,
  newLegId,
  readTelemetryRecords,
  recordVerificationStamp,
  scheduleCommitTelemetry,
  TELEMETRY_FILENAME,
  tryAppendTelemetryRecord,
  type TelemetryCollectRecord,
  type TelemetryCommitRecord,
  type TelemetryDispatchRecord,
  type TelemetryEnvironmentRecord,
  type TelemetryReviewRoundRecord,
  type TelemetryVerificationRecord,
} from "../../src/telemetry.js";

import type { Finding, PriorFindingDisposition } from "../../src/types.js";

import type {
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

const tempDirs: string[] = [];

function envRecordStub(
  overrides: Partial<TelemetryEnvironmentRecord> = {},
): TelemetryEnvironmentRecord {
  return {
    v: 1,
    phase: "environment",
    stamped_at: "t",
    runId: null,
    imageTag: null,
    imageDigest: null,
    sandboxFingerprint: null,
    soulsHash: null,
    promptHash: null,
    routeName: null,
    routeSlots: null,
    routeCmrReviewLegs: null,
    cliVersions: null,
    ...overrides,
  };
}

function tempDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(dir);
  return dir;
}

function baseSpec(overrides: Partial<WorkerSpec> = {}): WorkerSpec {
  return {
    id: "S2",
    kind: "coder",
    role: "coder",
    host: "codex",
    session: "fresh",
    contextRetention: "retain",
    promptFile: "coder.md",
    maxIter: 1,
    model: "gpt-5.6-terra",
    soul: "coder",
    toolchain: [],
    ...overrides,
  };
}

function finding(
  overrides: Partial<Finding> = {},
): Finding {
  return {
    severity: "high",
    category: "correctness",
    claim_quote: "the retry ignores the error",
    location: "src/retry.ts:42",
    suggested_fix: "preserve the error",
    action: "fix_now",
    ...overrides,
  };
}

export {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  execFileSync,
  tmpdir,
  dirname,
  join,
  afterEach,
  describe,
  expect,
  it,
  vi,
  dispatchWorkerWithMonitor,
  workerResultFromMonitorSidecar,
  resolveRouteModels,
  routeSmokeEntries,
  appendTelemetryRecord,
  buildCollectStamp,
  buildDispatchStamp,
  buildEnvironmentStamp,
  buildCommitStamp,
  buildReviewRoundStamp,
  buildVerificationStamp,
  categoryFromReason,
  classifyWorkerTerminal,
  clearTelemetryRunEnvironment,
  collectCommitDiffAuditAsync,
  collectCommitMetricsAsync,
  commitsBetweenAsync,
  configureTelemetryFromWorkerImage,
  configureTelemetryRunEnvironment,
  durableTelemetryDirForSingleSlice,
  ensureEnvironmentStamp,
  extractClaudeTokens,
  extractCodexTokens,
  extractTokensFromLog,
  hashDirectoryContents,
  newLegId,
  readTelemetryRecords,
  recordVerificationStamp,
  scheduleCommitTelemetry,
  TELEMETRY_FILENAME,
  tryAppendTelemetryRecord,
  TelemetryCollectRecord,
  TelemetryCommitRecord,
  TelemetryDispatchRecord,
  TelemetryEnvironmentRecord,
  TelemetryReviewRoundRecord,
  TelemetryVerificationRecord,
  Finding,
  PriorFindingDisposition,
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
  tempDirs,
  envRecordStub,
  tempDir,
  baseSpec,
  smokedRoute,
  finding,
};
