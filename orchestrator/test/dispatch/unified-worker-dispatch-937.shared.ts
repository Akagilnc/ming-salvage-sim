import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../../src/dispatchRetry.js";

import { dispatchWorkerWithMonitor } from "../../src/dispatchWorker.js";

import { resolveCoderRecOrder } from "../../src/coderRoster.js";

import { DEFAULT_PARK_THRESHOLD_MS } from "../../src/quotaPoolTable.js";

import { QuotaWaitForResetError } from "../../src/quotaProbe.js";

import { parkOrRelayQuotaWall } from "../../src/quotaParkRelay.js";

import {
  MAX_RELAY_HANDOFFS,
  canRelayHandoff,
  countRelayHandoffsInLedger,
  renderEphemeralRelayBrief,
  buildRelayHandoffLedgerEntry,
} from "../../src/relayDispatch.js";

const RELAY_FOCUS_FILENAME = ".relay-focus.md";

import { terminateSpawnedChild } from "../../src/workerMonitor.js";

import type {
  Backend,
  CliMonitorSpawnSpec,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

const tempDirs: string[] = [];

function coderSpec(): WorkerSpec {
  return {
    id: "S2",
    kind: "coder",
    role: "coder",
    host: "codex",
    session: "fresh",
    contextRetention: "retain",
    promptFile: "coder.md",
    maxIter: 1,
    model: "grok-4.5",
    soul: "coder",
    toolchain: [],
  } as WorkerSpec;
}

function quotaWallError(now: Date, resetAt: Date): QuotaWaitForResetError {
  return new QuotaWaitForResetError({
    disposition: {
      kind: "wait_for_reset",
      pool: "grok",
      resetAt,
      reason: "quota limited",
    },
    applied: {
      ledgerEntry: {
        event: "quota_wait_for_reset",
        pool: "grok",
        resetAt: resetAt.toISOString(),
        reason: "quota limited",
        step: "S2",
        workerPid: 1,
        ts: now.toISOString(),
      },
    },
    pool: "grok"
  });
}

export {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  vi,
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  dispatchWorkerWithMonitor,
  resolveCoderRecOrder,
  DEFAULT_PARK_THRESHOLD_MS,
  QuotaWaitForResetError,
  parkOrRelayQuotaWall,
  MAX_RELAY_HANDOFFS,
  canRelayHandoff,
  countRelayHandoffsInLedger,
  renderEphemeralRelayBrief,
  buildRelayHandoffLedgerEntry,
  RELAY_FOCUS_FILENAME,
  terminateSpawnedChild,
  Backend,
  CliMonitorSpawnSpec,
  WorkerResult,
  WorkerSpec,
  tempDirs,
  coderSpec,
  quotaWallError,
};
