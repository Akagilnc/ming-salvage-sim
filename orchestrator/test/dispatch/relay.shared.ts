import { execFileSync } from "node:child_process";

import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CODER_ROSTER,
  lookupCoderRosterEntry,
  resolveCoderRecOrder,
  selectCoderRecEntry,
} from "../../src/coderRoster.js";

import { modelIdForSlug } from "../../src/modelRegistry.js";

import {
  DEFAULT_PARK_THRESHOLD_MS,
  DEFAULT_POOL_MODELS,
  billingPoolFromQuotaPool,
  buildDefaultBillingPools,
  decideParkOrRelay,
  hasLiveRelayBaton,
  resolveRelayPools,
  selectCapacityRelayBaton,
  selectNextRelayBaton,
  type BillingPoolEntry,
  type BillingPoolId,
  type PoolTable,
} from "../../src/quotaPoolTable.js";

import {
  MAX_RELAY_HANDOFFS,
  applyResourceFailureHandoff,
  buildRelayHandoffLedgerEntry,
  canRelayHandoff,
  CapacityRelayError,
  countRelayHandoffsInLedger,
  forkQuotaWallAt683Point,
  isCapacityRelayError,
  isRelayChainReadyForReviewGate,
  renderEphemeralRelayBrief,
  resumeRelayFromLedger,
  type RelayHandoffLedgerEvent,
} from "../../src/relayDispatch.js";

import { QuotaWaitForResetError } from "../../src/quotaProbe.js";

import { buildCliMonitorSpawnSpec } from "../../src/cliMonitorHooks.js";

import { dispatchWorkerWithMonitor, legacyDispatchWorker } from "../../src/dispatchWorker.js";

import { runOrchestrator } from "../../src/runner.js";

import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";

import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepSpec,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

const RELAY_FOCUS_FILENAME = ".relay-focus.md";

function writeRoutePreset(name: string, slots: Record<string, string>): string {
  const dir = mkdtempSync(join(tmpdir(), "relay-preset-"));
  const path = join(dir, "route-presets.json");
  // Clone factory "normal" shape (full legs/optional markers) so capacity
  // relay pool attribution matches production, then apply slot overrides.
  const factoryNormal = JSON.parse(
    readFileSync(join(process.cwd(), "config", "route-presets.json"), "utf8"),
  ).normal;
  writeFileSync(
    path,
    JSON.stringify({
      [name]: {
        ...factoryNormal,
        slots: { ...factoryNormal.slots, ...slots },
      },
      // Keep normal available for any mid-test resolve that names it.
      normal: factoryNormal,
    }),
  );
  return path;
}

export {
  execFileSync,
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
  CODER_ROSTER,
  lookupCoderRosterEntry,
  resolveCoderRecOrder,
  selectCoderRecEntry,
  modelIdForSlug,
  DEFAULT_PARK_THRESHOLD_MS,
  DEFAULT_POOL_MODELS,
  billingPoolFromQuotaPool,
  buildDefaultBillingPools,
  decideParkOrRelay,
  hasLiveRelayBaton,
  resolveRelayPools,
  selectCapacityRelayBaton,
  selectNextRelayBaton,
  BillingPoolEntry,
  BillingPoolId,
  PoolTable,
  MAX_RELAY_HANDOFFS,
  applyResourceFailureHandoff,
  buildRelayHandoffLedgerEntry,
  canRelayHandoff,
  CapacityRelayError,
  countRelayHandoffsInLedger,
  forkQuotaWallAt683Point,
  isCapacityRelayError,
  isRelayChainReadyForReviewGate,
  renderEphemeralRelayBrief,
  resumeRelayFromLedger,
  RelayHandoffLedgerEvent,
  QuotaWaitForResetError,
  buildCliMonitorSpawnSpec,
  dispatchWorkerWithMonitor,
  legacyDispatchWorker,
  runOrchestrator,
  skeletonReviewLoopWorkerResult,
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepSpec,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  RELAY_FOCUS_FILENAME,
  writeRoutePreset,
};
