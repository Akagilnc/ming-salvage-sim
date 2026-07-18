import { describe, expect, it } from "vitest";

import { mkdtempSync, writeFileSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { execFileSync } from "node:child_process";

import { findingIdentityKey } from "../../../src/findings.js";

import { legacyDispatchFamilyWorker } from "../../../src/family/dispatchFamilyWorker.js";

import { recordFamilyEscalated } from "../../../src/family/ledger.js";

import { runFamily } from "../../../src/family/runner.js";

import { legacyCmrScriptToWorkerOutput } from "../../helpers/judge-fixtures.js";

import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

import type {

  FamilyAbortedEvent,
  FamilyBackend,
  FamilyEpic,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  ReconcileGit,
} from "../../../src/family/types.js";

import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

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

function makeFamilyDocReleaseRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "capable-family-doc-"));
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
  readonly merges: MergeRequest[] = [];
  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: Array<{ readonly familyBase: string }> = [];
  readonly workingRepo: string;
  liveHead: string | undefined;

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult;
    } = {},
    workingRepo?: string,
  ) {
    this.workingRepo = workingRepo ?? makeFamilyDocReleaseRepo();
  }

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.liveHead = `+${child.childIssue}`;
    return { familyHead: this.liveHead };
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
    if (this.liveHead === undefined) throw new Error("no live head");
    return this.liveHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    // Default green is boolean converged without open-count — fake dispatch
    // emits live kind:judge (happy 直出). findingsCount:0 stays residual unusable
    // (#919 M2/R7 never silent clean).
    const result = this.script.cmr?.(req) ?? {
      converged: true,
      successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
    };
    return result.findings === undefined ? { ...result, findings: [] } : result;
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
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
      const familyBase = ctx.familyBase!;
      this.prCalls.push({ familyBase });
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: familyBase,
          pr: `pr://${familyBase}`,
          ...(this.liveHead !== undefined ? { prHead: this.liveHead } : {}),
          status: "pr_opened",
        },
      };
    }
    return legacyDispatchFamilyWorker(this, spec, ctx);
  }
  resolveFamilyWorkingRepo(): string | undefined {
    return this.workingRepo;
  }
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
    await recordFamilyEscalated(this, {
      escalationKind: "decision",
      phase: "final",
      reason: esc.reason,
      familyHeadAfter: esc.familyHeadAfter,
      stopSummary: esc.stopSummary,
    });
  }
}

class StaticReconcileGit implements ReconcileGit {
  constructor(private readonly liveHead: string, private readonly startHead: string = "base0") {}
  async liveFamilyHead(): Promise<string> {
    return this.liveHead;
  }
  async familyBaseStartHead(): Promise<string> {
    return this.startHead;
  }
  async childHeadExists(): Promise<{ exists: boolean; childHead?: string }> {
    return { exists: false };
  }
  async isAncestor(a: string, b: string): Promise<boolean> {
    return a === b || a === this.startHead || b === this.liveHead;
  }
}

const TWO_WAVES: FamilyEpic = {
  issue: 291,
  children: [
    { issue: 294, blockedBy: [] },
    { issue: 296, blockedBy: [294] },
  ],
};

function epicWith(...issues: number[]): FamilyEpic {
  return { issue: 291, children: issues.map((issue) => ({ issue, blockedBy: [] })) };
}

export {
  describe,
  expect,
  it,
  mkdtempSync,
  writeFileSync,
  tmpdir,
  join,
  execFileSync,
  findingIdentityKey,
  legacyDispatchFamilyWorker,
  recordFamilyEscalated,
  runFamily,
  legacyCmrScriptToWorkerOutput,
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  WorkerResult,
  WorkerSpec,
  FamilyAbortedEvent,
  FamilyBackend,
  FamilyEpic,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  ReconcileGit,
  buildExplicitLandingLiveHooks,
  ChildBackend,
  makeFamilyDocReleaseRepo,
  CapableFamilyBackend,
  StaticReconcileGit,
  TWO_WAVES,
  epicWith,
};
