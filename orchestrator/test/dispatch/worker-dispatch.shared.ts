import { execFileSync } from "node:child_process";

import { mkdtempSync, readFileSync, rmSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { runOrchestrator } from "../../src/runner.js";

import { decodeReviewerOpenCountReceipt } from "../../src/receiptRecovery.js";

import {
  dispatchWorker,
  landingWorkerSpec,
  fixerWorkerSpec,
  legacyDispatchWorker,
  stepSpecToWorkerSpec,
  verifyWorkerSpec,
  workerResultToStep,
} from "../../src/dispatchWorker.js";

import { familyShipWorkerSpec } from "../../src/family/dispatchFamilyWorker.js";

import { getCoderRoster } from "../../src/coderRoster.js";

import { QuotaWaitForResetError } from "../../src/quotaProbe.js";

import { resolveRouteModels, routeSmokeEntries } from "../../src/modelRoutes.js";

import {
  readTelemetryRecords,
  type TelemetryCommitRecord,
  type TelemetryEnvironmentRecord,
} from "../../src/telemetry.js";

import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorkerOutcomeLandingFile,
  WorkerResult,
  WorkerSpec,
  WorkerLandingPayload,
  WorktreeHandle,
} from "../../src/types.js";

const SMOKED_ROUTE = resolveRouteModels(
  "normal",
  {},
  {},
  Object.fromEntries(
    routeSmokeEntries(resolveRouteModels("normal", {})).map((entry) => [
      entry.key,
      { state: "passed", at: new Date().toISOString(), cliVersion: "test" },
    ]),
  ),
);

class DispatchBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  /** Ordered log of every worker dispatched: "id:kind:role:session:skill". */
  readonly dispatched: string[] = [];
  /** The full WorkerSpec of each dispatch, in order. */
  readonly specs: WorkerSpec[] = [];
  /** The DispatchContext of each dispatch, in order. */
  readonly ctxs: DispatchContext[] = [];
  /** Durable runner ledger rows, including the buffered S0 start row. */
  readonly persistedLedger: PersistentLedgerEntry[] = [];
  /** Asserts the runner NEVER reaches for the legacy methods directly. */
  legacyRunStepCount = 0;

  readonly worktree: WorktreeHandle = {
    branch: "feat/orchestrator/issue-331",
    base: "main",
    path: "/resident/worktrees/issue-331",
  };

  async findResumeState(): Promise<
    | undefined
    | {
        worktree: WorktreeHandle;
        stateDir: string;
        ledger: PersistentLedgerEntry[];
      }
  > {
    return undefined;
  }
  async resumeSession(): Promise<StepOutput> {
    throw new Error("resumeSession should not be called directly (#331)");
  }

  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    return {
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return this.worktree;
  }

  async runStep(): Promise<StepOutput> {
    this.legacyRunStepCount += 1;
    throw new Error("runStep should not be called directly (#331)");
  }

  async writeLedger(
    entry: PersistentLedgerEntry,
    _stateDir: string,
  ): Promise<void> {
    this.persistedLedger.push(entry);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    this.dispatched.push(
      `${spec.id}:${spec.kind}:${spec.role}:${spec.session}:${spec.contextRetention}:${spec.skill ?? "—"}`,
    );
    this.specs.push(spec);
    this.ctxs.push(ctx);
    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
    if ((spec.kind === "reviewer" || spec.kind === "verify")) {
      return { kind: "completed", output: { kind: "judge", status: "converged" } };
    }
    throw new Error(`unexpected child worker kind: ${spec.kind}`);
  }
}

export {
  execFileSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  vi,
  runOrchestrator,
  decodeReviewerOpenCountReceipt,
  dispatchWorker,
  landingWorkerSpec,
  fixerWorkerSpec,
  legacyDispatchWorker,
  stepSpecToWorkerSpec,
  verifyWorkerSpec,
  workerResultToStep,
  familyShipWorkerSpec,
  getCoderRoster,
  QuotaWaitForResetError,
  resolveRouteModels,
  routeSmokeEntries,
  readTelemetryRecords,
  TelemetryCommitRecord,
  TelemetryEnvironmentRecord,
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorkerOutcomeLandingFile,
  WorkerResult,
  WorkerSpec,
  WorkerLandingPayload,
  WorktreeHandle,
  SMOKED_ROUTE,
  DispatchBackend,
};
