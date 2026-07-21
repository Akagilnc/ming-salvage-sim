import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import {
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../../../src/dispatchRetry.js";

import { dispatchWorkerWithMonitor } from "../../../src/dispatchWorker.js";

import { runOnlineReviewLoopStage } from "../../../src/family/onlineReviewLoop.js";

import { runVerifyCmr } from "../../../src/family/verifyCmr.js";

import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
} from "../../../src/family/types.js";

import type { PrReviewSnapshot } from "../../../src/botPolling.js";

import type {

  Backend,
  CliMonitorSpawnSpec,
  ShipResult,
  VerifyResult,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const tempDirs: string[] = [];

const STAGE_SHIP: ShipResult = {
  kind: "ship",
  branch: "family/epic-940",
  status: "pr_opened",
  pr: "https://github.com/test/repo/pull/940",
  prHead: "head-940",
};

const BASE_SNAPSHOT: PrReviewSnapshot = {
  repo: "o/r",
  prNumber: 940,
  prUrl: "https://github.com/test/repo/pull/940",
  headOid: "head-940",
  pollCount: 1,
  bots: {
    coderabbit: { state: "complete", findingCount: 0 },
    sourcery: { state: "complete", findingCount: 0 },
    codex: { state: "complete", findingCount: 0 },
    gemini: { state: "complete", findingCount: 0 },
  },
  threads: [],
  checkRuns: [],
  totalFindingCount: 0,
  quiescent: true,
  roundTriggerUsed: {
    headOid: "head-940",
    triggeredAt: "1970-01-01T00:00:00.000Z",
  },
  checkRunsEmptyMeans: "converged",
};

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

function completedJudgeGreen(): WorkerResult {
  return {
    kind: "completed",
    output: { kind: "judge", status: "converged" },
  };
}

function completedShip(): WorkerResult {
  return {
    kind: "completed",
    output: {
      kind: "ship",
      branch: "family/epic-940",
      status: "pr_opened",
      pr: "https://github.com/test/repo/pull/9410",
      prHead: "ship-head",
    },
  };
}

class DispatchCapableBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  readonly ledger: FamilyLedgerEntry[] = [];
  constructor(
    private readonly onDispatch: (spec: WorkerSpec) => Promise<WorkerResult>,
  ) {}
  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return "head-after-cmr";
  }
  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    return this.onDispatch(spec);
  }
}

export {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  dispatchWorkerWithMonitor,
  runOnlineReviewLoopStage,
  runVerifyCmr,
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  PrReviewSnapshot,
  Backend,
  CliMonitorSpawnSpec,
  ShipResult,
  VerifyResult,
  WorkerResult,
  WorkerSpec,
  buildExplicitLandingLiveHooks,
  tempDirs,
  STAGE_SHIP,
  BASE_SNAPSHOT,
  coderSpec,
  completedJudgeGreen,
  completedShip,
  DispatchCapableBackend,
};
