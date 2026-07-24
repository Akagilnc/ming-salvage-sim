import { describe, expect, it } from "vitest";

import { runVerifyCmr } from "../../../src/family/verifyCmr.js";

import {
  cmrWorkerSpec,
  dispatchFamilyWorker,
  dispatchFamilyWorkerWithMonitor,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
  legacyDispatchFamilyWorker,
} from "../../../src/family/dispatchFamilyWorker.js";

import { dispatchReviewLoopThroughAdmission } from "../../helpers/review-loop-admission-dispatch.js";

import { mkdtempSync, rmSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { resolveActiveModelRoute, smokeRouteModels } from "../../../src/modelRoutes.js";

import type {
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

import {
  legacyCmrScriptToWorkerOutput,
  liveCmrJudgeContinue,
} from "../../helpers/judge-fixtures.js";

import type {

  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
} from "../../../src/family/types.js";

import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";
import { completeReviewPanelLegWorker } from "../../helpers/review-panel-leg-dispatch.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

function completedJudgeGreen(
  cargo: Record<string, unknown> = {},
): WorkerResult {
  return {
    kind: "completed",
    output: {
      kind: "judge",
      status: "converged",
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      ...CMR_EVIDENCE,
      ...cargo,
    },
  } as WorkerResult;
}

class CapableFamilyBackend implements FamilyBackend {
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

  verifyCalls: FamilyVerifyRequest[] = [];
  cmrCalls: IntegratedCmrRequest[] = [];
  prCalls: Array<{ readonly familyBase: string }> = [];
  cmrConverged = true;

  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

  async appendFamilyLedger(): Promise<void> {}
  async readFamilyLedger(): Promise<[]> {
    return [];
  }
  async readFamilyHead(): Promise<string> {
    return "head-1";
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return { ok: true };
  }
  async runIntegratedCmr(
    req: IntegratedCmrRequest,
  ): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    // #919 M2/R7: residual findingsCount:0 is unusable. Boolean green without
    // open-count → live judge via legacyCmrScriptToWorkerOutput happy path.
    return this.cmrConverged
      ? {
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          findings: [],
        }
      : {
          converged: false,
          findingsCount: 1,
          reason: "cross-slice seam mismatch",
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          findings: [
            {
              severity: "high",
              category: "correctness",
              claim_quote: "cross-slice seam mismatch",
              location: "family integration seam",
              suggested_fix: "repair the cross-slice seam",
              action: "fix_now",
            },
          ],
        };
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    const panelLeg = completeReviewPanelLegWorker(spec);
    if (panelLeg !== undefined) return panelLeg;
    if (spec.kind === "cmr") {
      // #919 CR N2/N3: production residual is unusableResidualOpenCountPaper
      // (kind:reviewer). Test-fake maps IntegratedCmrResult script intent to
      // live kind:judge via legacyCmrScriptToWorkerOutput (production never
      // re-opens residual open-count as a closer).
      const familyBase = ctx.familyBase;
      if (familyBase === undefined) {
        throw new Error("CapableFamilyBackend: cmr requires ctx.familyBase");
      }
      const cmr = await this.runIntegratedCmr({
        familyBase,
        ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
        ...(ctx.llmResolvedChildren !== undefined &&
        ctx.llmResolvedChildren.length > 0
          ? { llmResolvedChildren: ctx.llmResolvedChildren }
          : {}),
        ...(ctx.escalationAnswer !== undefined
          ? { escalationAnswer: ctx.escalationAnswer }
          : {}),
      });
      return {
        kind: "completed",
        output: legacyCmrScriptToWorkerOutput(cmr),
      };
    }
    if (spec.kind === "ship") {
      const familyBase = ctx.familyBase!;
      this.prCalls.push({ familyBase });
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: familyBase,
          pr: `https://github.com/test/repo/pull/1090`,
          prHead: "head-1",
          status: "pr_opened",
        },
      };
    }
    return dispatchReviewLoopThroughAdmission(this, spec, ctx);
  }
}

export {
  describe,
  expect,
  it,
  runVerifyCmr,
  cmrWorkerSpec,
  dispatchFamilyWorker,
  dispatchFamilyWorkerWithMonitor,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
  legacyDispatchFamilyWorker,
  mkdtempSync,
  rmSync,
  tmpdir,
  join,
  resolveActiveModelRoute,
  smokeRouteModels,
  DispatchContext,
  WorkerResult,
  WorkerSpec,
  legacyCmrScriptToWorkerOutput,
  liveCmrJudgeContinue,
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  buildExplicitLandingLiveHooks,
  CMR_EVIDENCE,
  completedJudgeGreen,
  CapableFamilyBackend,
};
