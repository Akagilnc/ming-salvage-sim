import { mkdtempSync, rmSync, writeFileSync } from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import * as sc from "@ai-hero/sandcastle";

import { dispatchFamilyWorkerWithMonitor } from "../../../src/family/dispatchFamilyWorker.js";

import { runFamily } from "../../../src/family/runner.js";

import {
  RealFamilyBackend,
  type MergerAuth,
} from "../../../src/family/realFamilyBackend.js";

import { resolveRouteModels, routeSmokeEntries } from "../../../src/modelRoutes.js";

import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";

import { completeReviewPanelLegWorker } from "../../helpers/review-panel-leg-dispatch.js";

import {
  clearTelemetryRunEnvironment,
  readTelemetryRecords,
  type TelemetryCollectRecord,
  type TelemetryDispatchRecord,
  type TelemetryEnvironmentRecord,
  type TelemetryReviewRoundRecord,
} from "../../../src/telemetry.js";

import type {
  Backend,
  DispatchContext,
  IssueMeta,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../../src/types.js";

import type {

  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  MergeRequest,
} from "../../../src/family/types.js";

import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const tempDirs: string[] = [];

const here = dirname(fileURLToPath(import.meta.url));

const realPromptsDir = join(here, "..", "..", "..", "prompts");

const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

function tempDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(dir);
  return dir;
}

function smokedRoute() {
  const base = resolveRouteModels("normal", {});
  const smoke = Object.fromEntries(
    routeSmokeEntries(base).map((entry) => [
      entry.key,
      {
        state: "passed" as const,
        at: new Date().toISOString(),
        cliVersion: `cli-${entry.slug}`,
      },
    ]),
  );
  return resolveRouteModels("normal", {}, {}, smoke);
}

function familySpec(kind: WorkerSpec["kind"]): WorkerSpec {
  return {
    id: kind === "cmr" ? "S3" : "S9",
    kind,
    role: "verify",
    host: "codex",
    session: "fresh",
    contextRetention: "clean",
    promptFile: `${kind}.md`,
    maxIter: 1,
    model: "gpt-5.6-terra",
    soul: "verify",
    toolchain: [],
  };
}

function resultFor(kind: WorkerSpec["kind"]): WorkerResult {
  if (kind === "cmr") {
    return { kind: "failed", reason: "provider returned HTTP Error 429" };
  }
  if (kind === "verify") {
    throw new Error("stream disconnect while collecting verify output");
  }
  return {
    kind: "completed",
    output: { kind: "coder", committed: true, commitsAdded: 1 },
    sessionId: `family-${kind}-session`,
  };
}

async function waitForEnvironment(ledgerDir: string): Promise<TelemetryEnvironmentRecord | undefined> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const environment = readTelemetryRecords(ledgerDir).find(
      (record): record is TelemetryEnvironmentRecord => record.phase === "environment",
    );
    if (environment !== undefined) return environment;
    await new Promise<void>((resolve) => setTimeout(resolve, 5));
  }
  return undefined;
}

const COMPLETE_CMR_LEGS = ["opus", "gpt-5.6-sol", "agy"] as const;

const FAMILY_HEAD = "head-809-sidecar";

class FamilyTelemetryBackend implements FamilyBackend {
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

  readonly ctxs: DispatchContext[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];

  constructor(private readonly durableTelemetryDir: string) {}

  async mergeChildIntoFamilyBase(_child: MergeRequest): Promise<{ familyHead: string }> {
    throw new Error("family telemetry dual-run uses an empty epic (no children)");
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
    return FAMILY_HEAD;
  }

  resolveTelemetryDir(): string {
    return this.durableTelemetryDir;
  }

  async installTelemetryRunEnvironment(): Promise<void> {}

  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }

  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    // Record every dispatch (including panel-leg short-circuits) so runId
    // telemetry assertions cover the full fan-out, not only non-leg workers.
    this.ctxs.push(ctx);
    const panelLeg = completeReviewPanelLegWorker(spec);
    if (panelLeg !== undefined) return panelLeg;
    if (spec.kind === "cmr") {
      const cmrPass = ctx.cmrPass ?? "correctness";
      // #919 M1/M2: live ship green is typed kind:judge status:converged.
      // Residual findingsCount:0 is unusable (never silent clean / never ship).
      return {
        kind: "completed",
        output: {
          kind: "judge",
          status: "converged",
          cmrPass,
          successfulLegs: [...COMPLETE_CMR_LEGS],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          evidencePaths: [`cmr/${cmrPass}.json`],
        },
      };
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase ?? "family/809-sidecar",
          pr: "https://github.com/test/repo/pull/809",
          prHead: FAMILY_HEAD,
          status: "pr_opened",
        },
      };
    }
    const reviewLoop = skeletonReviewLoopWorkerResult(spec.kind);
    if (reviewLoop !== undefined) return reviewLoop;
    throw new Error(`unexpected family worker ${spec.kind}`);
  }
}

class SmokeOnlySingleSliceBackend implements Backend {
  async smokeModelRoute(
    _route: Parameters<Backend["smokeModelRoute"]>[0],
  ): Promise<Awaited<ReturnType<Backend["smokeModelRoute"]>>> {
    return smokedRoute();
  }

  async findResumeState(): Promise<undefined> {
    return undefined;
  }

  async resumeSession(): Promise<StepOutput> {
    throw new Error("smoke-only single-slice backend: resumeSession unused");
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

  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    return {
      branch: `feat/issue-${issueNumber}`,
      base,
      path: `/wt/${issueNumber}`,
    };
  }

  async runStep(): Promise<StepOutput> {
    throw new Error("smoke-only single-slice backend: runStep unused");
  }

  async writeLedger(): Promise<void> {}
}

export {
  mkdtempSync,
  rmSync,
  writeFileSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  vi,
  sc,
  dispatchFamilyWorkerWithMonitor,
  runFamily,
  RealFamilyBackend,
  MergerAuth,
  resolveRouteModels,
  routeSmokeEntries,
  skeletonReviewLoopWorkerResult,
  clearTelemetryRunEnvironment,
  readTelemetryRecords,
  TelemetryCollectRecord,
  TelemetryDispatchRecord,
  TelemetryEnvironmentRecord,
  TelemetryReviewRoundRecord,
  Backend,
  DispatchContext,
  IssueMeta,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  MergeRequest,
  buildExplicitLandingLiveHooks,
  tempDirs,
  here,
  realPromptsDir,
  realSoulsDir,
  tempDir,
  smokedRoute,
  familySpec,
  resultFor,
  waitForEnvironment,
  COMPLETE_CMR_LEGS,
  FAMILY_HEAD,
  FamilyTelemetryBackend,
  SmokeOnlySingleSliceBackend,
};
