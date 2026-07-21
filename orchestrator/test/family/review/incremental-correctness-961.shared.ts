import { describe, expect, it } from "vitest";

import {
  lastCorrectnessConvergedHeadFromLedger,
  recordCmrPassed,
} from "../../../src/family/ledger.js";

import { runFamily } from "../../../src/family/runner.js";

import { runVerifyCmr } from "../../../src/family/verifyCmr.js";

import { activeModelRoute, modelRouteFingerprint } from "../../../src/modelRoutes.js";

import { QuotaWaitForResetError } from "../../../src/quotaProbe.js";

import { legacyCmrScriptToWorkerOutput } from "../../helpers/judge-fixtures.js";

import { completeCmrPanelLegWorker } from "../../helpers/cmr-panel-leg-dispatch.js";

import { dispatchReviewLoopThroughAdmission } from "../../helpers/review-loop-admission-dispatch.js";

import { legacyDispatchFamilyWorker } from "../../../src/family/dispatchFamilyWorker.js";

import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
} from "../../../src/family/types.js";

import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { execFileSync } from "node:child_process";

function icQuotaParkError(resetAt: Date): QuotaWaitForResetError {
  return new QuotaWaitForResetError({
    disposition: {
      kind: "wait_for_reset",
      pool: "zai",
      resetAt,
      reason: "quota limited (429); wait for reset",
    },
    applied: {
      ledgerEntry: {
        event: "quota_wait_for_reset",
        pool: "zai",
        resetAt: resetAt.toISOString(),
        reason: "quota limited (429); wait for reset",
        step: "S9",
        workerPid: 0,
        ts: "2026-07-14T12:00:00.000Z",
      },
    },
    pool: "zai",
  });
}

function currentRouteFingerprint(): string {
  return modelRouteFingerprint(activeModelRoute());
}

function makeFamilyDocReleaseRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "ic-961-doc-"));
  const git = (args: string[]) =>
    execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  git(["init"]);
  git(["config", "user.email", "t@example.com"]);
  git(["config", "user.name", "t"]);
  writeFileSync(join(dir, "VERSION"), "1.0.0\n");
  git(["add", "."]);
  git(["commit", "-m", "doc-release"]);
  return dir;
}

class ChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
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
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
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

  readonly ledger: FamilyLedgerEntry[] = [];
  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly prCalls: Array<{ familyBase: string }> = [];
  readonly merges: MergeRequest[] = [];
  currentFamilyHead = "head-start";
  liveHead = "head-start";

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult | Promise<IntegratedCmrResult>;
      worker?: (spec: WorkerSpec, ctx: DispatchContext) => WorkerResult | Promise<WorkerResult>;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.currentFamilyHead = `+${child.childIssue}`;
    this.liveHead = this.currentFamilyHead;
    return { familyHead: this.currentFamilyHead };
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
  async readFamilyHead(_familyBase: string): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    const result =
      (await this.script.cmr?.(req)) ?? {
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        findings: [],
      };
    return result.findings === undefined ? { ...result, findings: [] } : result;
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    const panelLeg = completeCmrPanelLegWorker(spec);
    if (panelLeg !== undefined) return panelLeg;
    if (this.script.worker !== undefined) {
      return this.script.worker(spec, ctx);
    }
    if (spec.kind === "cmr") {
      const cmr = await this.runIntegratedCmr({
        familyBase: ctx.familyBase!,
        ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
        ...(ctx.priorCmrFindingIdentityKeys !== undefined
          ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
          : {}),
      });
      return {
        kind: "completed",
        output: legacyCmrScriptToWorkerOutput(cmr),
      };
    }
    if (spec.kind === "ship") {
      const request = { familyBase: ctx.familyBase! };
      this.prCalls.push(request);
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: request.familyBase,
          pr: `https://github.com/test/repo/pull/1090`,
          prHead: this.currentFamilyHead,
          status: "pr_opened",
        },
      };
    }
    return dispatchReviewLoopThroughAdmission(this, spec, ctx);
  }
  reconcileGit() {
    return {
      liveFamilyHead: async () => this.liveHead,
      familyBaseStartHead: async () => "head-start",
      isAncestor: async () => false,
    };
  }
  workingRepo = makeFamilyDocReleaseRepo();
}

export {
  describe,
  expect,
  it,
  lastCorrectnessConvergedHeadFromLedger,
  recordCmrPassed,
  runFamily,
  runVerifyCmr,
  activeModelRoute,
  modelRouteFingerprint,
  QuotaWaitForResetError,
  legacyCmrScriptToWorkerOutput,
  legacyDispatchFamilyWorker,
  buildExplicitLandingLiveHooks,
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  WorkerResult,
  WorkerSpec,
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  mkdtempSync,
  readFileSync,
  writeFileSync,
  tmpdir,
  join,
  execFileSync,
  icQuotaParkError,
  currentRouteFingerprint,
  makeFamilyDocReleaseRepo,
  ChildBackend,
  CapableFamilyBackend,
};
