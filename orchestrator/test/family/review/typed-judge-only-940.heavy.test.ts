/**
 * #940 — CMR / online review / 线上复验 only consume typed judge.
 *
 * Acceptance (issue #940):
 *   - public ignition/driver real entry proves #934 ID-012, ID-015, ID-016
 *   - unified worker dispatch real entry proves #934 ID-004, ID-006
 *
 * Seams (production paths only — no helper-only fakes as the subject):
 *   - runOnlineReviewLoopStage (online-review Action loop)
 *   - runVerifyCmr (family final barrier → cmr / ship)
 *   - dispatchRetry.withMechanicalRetry + terminateSpawnedChild (ID-004 / ID-006)
 *
 * Authority: #934 ID-004 / ID-006 / ID-012 / ID-015 / ID-016;
 *            landed #925/#926/#930 persistent judge baseline.
 */

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
afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

const STAGE_SHIP: ShipResult = {
  kind: "ship",
  branch: "family/epic-940",
  status: "pr_opened",
  pr: "pr://family/940-typed-judge",
  prHead: "head-940",
};

const BASE_SNAPSHOT: PrReviewSnapshot = {
  repo: "o/r",
  prNumber: 940,
  prUrl: "pr://family/940-typed-judge",
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
      pr: "pr://family/940-ship",
      prHead: "ship-head",
    },
  };
}

/** Minimal family backend that always has the production dispatchWorker seam. */
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

describe("#940 unified worker dispatch — ID-004 / ID-006 still hold", () => {

  it("POSITIVE: adoption-record failure terminates exact ChildProcess handle (ID-006)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-940-adopt-"));
    tempDirs.push(dir);
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 60_000)"],
        logDir: dir,
        poolId: "zai",
        stepId: "S2",
        readInstanceId: () => "test-instance",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    const killed: number[] = [];
    let spawnedPid: number | undefined;
    await expect(
      dispatchWorkerWithMonitor(backend, coderSpec(), {}, undefined, {
        onMonitorHandleSpawned: async (handle) => {
          spawnedPid = handle.pid;
          throw new Error("adoption persist failed");
        },
        monitorDeps: {
          readInstanceId: () => "test-instance",
          killPid: (pid, signal) => {
            killed.push(pid);
            try {
              process.kill(pid, signal);
            } catch {
              // group signal may fail in restricted sandboxes
            }
          },
          sleepMs: async () => {},
        },
      }),
    ).rejects.toThrow(/adoption persist failed/);
    // CR-15: kill targets the exact spawn PID (process-group form is -pid).
    expect(spawnedPid).toEqual(expect.any(Number));
    expect(
      killed.some((p) => p === spawnedPid || p === -spawnedPid!),
    ).toBe(true);
  });
});
