import { execFileSync } from "node:child_process";

import { mkdtempSync, rmSync } from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import type * as sc from "@ai-hero/sandcastle";

import { cmrWorkerSpec } from "../../../src/family/dispatchFamilyWorker.js";

import {
  RealFamilyBackend,
  type CmrAuth,
} from "../../../src/family/realFamilyBackend.js";

import { runVerifyCmr } from "../../../src/family/verifyCmr.js";

import { familyJudgeResumeSessionIdFromPriorRows } from "../../../src/judgeStation.js";

import { resumeCapableForSlug } from "../../../src/modelRegistry.js";

import {
  resolveActiveModelRoute,
  smokeRouteModels,
} from "../../../src/modelRoutes.js";

import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";

import type {
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../../src/family/types.js";

import type {
  DispatchContext,
  JudgeResult,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

import {
  judgeConverged,
  judgeContinue,
  sampleFinding,
} from "../../helpers/judge-fixtures.js";

import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const here = dirname(fileURLToPath(import.meta.url));

const realPromptsDir = join(here, "..", "..", "..", "prompts");

const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

const FINDING = sampleFinding(
  "family open claim 966",
  "orchestrator/src/family/verifyCmr.ts:966",
);

const ROUND1_SESSION = "judge-sess-round1-966";

const GROK_SLUG = "grok-4.5";

const cleanups: string[] = [];

function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

function realRepo966(): string {
  const repo = mkDir("966-cmr-repo-");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
  execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], {
    cwd: repo,
  });
  execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
  return repo;
}

function completedJudge(output: JudgeResult, sessionId?: string): WorkerResult {
  return {
    kind: "completed",
    output,
    ...(sessionId !== undefined ? { sessionId } : {}),
  };
}

class FamilyJudgeLedgerBackend implements FamilyBackend {
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
  readonly dispatches: Array<{
    readonly kind: string;
    readonly session: string;
    readonly model?: string;
    readonly cmrPass?: string;
    readonly resumeSessionId?: string;
    readonly priorJudgeVerdicts?: DispatchContext["priorJudgeVerdicts"];
  }> = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: string[] = [];
  currentFamilyHead = "head-r1";

  private completenessRound = 0;
  private correctnessRound = 0;
  private coderFixRound = 0;

  constructor(
    private readonly script: {
      completeness?: (
        round: number,
        ctx: DispatchContext,
      ) => WorkerResult;
      correctness?: (
        round: number,
        ctx: DispatchContext,
      ) => WorkerResult;
      coder?: (round: number, ctx: DispatchContext) => WorkerResult;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
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
    return this.currentFamilyHead;
  }
  async runFamilyVerify(_req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      ...(typeof spec.model === "string" ? { model: spec.model } : {}),
      ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
      ...(ctx.resumeSessionId !== undefined
        ? { resumeSessionId: ctx.resumeSessionId }
        : {}),
      ...(ctx.priorJudgeVerdicts !== undefined
        ? { priorJudgeVerdicts: ctx.priorJudgeVerdicts }
        : {}),
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness") {
        const round = this.completenessRound++;
        if (this.script.completeness !== undefined) {
          return this.script.completeness(round, ctx);
        }
        return completedJudge(judgeConverged(), ROUND1_SESSION);
      }
      const round = this.correctnessRound++;
      if (this.script.correctness !== undefined) {
        return this.script.correctness(round, ctx);
      }
      return completedJudge(judgeConverged(), `${ROUND1_SESSION}-correctness`);
    }

    if (spec.kind === "coder") {
      const round = this.coderFixRound++;
      this.currentFamilyHead = `head-after-fix-${round + 1}`;
      if (this.script.coder !== undefined) {
        return this.script.coder(round, ctx);
      }
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }

    if (spec.kind === "ship") {
      this.prCalls.push(ctx.familyBase ?? "");
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase ?? "family/base",
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    throw new Error(`unexpected worker kind ${spec.kind}`);
  }

  /** Reset per-pass open counters so a second runVerifyCmr starts rounds at 0. */
  resetRoundCounters(): void {
    this.completenessRound = 0;
    this.correctnessRound = 0;
    this.coderFixRound = 0;
  }
}

async function grokCmrRoute() {
  const base = resolveActiveModelRoute({ ORCHESTRATOR_ROUTE: "normal" });
  return smokeRouteModels(
    {
      ...base,
      slots: {
        ...base.slots,
        cmrCompleteness: GROK_SLUG,
        cmrCorrectness: GROK_SLUG,
      },
    },
    async () => ({ cliVersion: "test-966" }),
  );
}

export {
  execFileSync,
  mkdtempSync,
  rmSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  sc,
  cmrWorkerSpec,
  RealFamilyBackend,
  CmrAuth,
  runVerifyCmr,
  familyJudgeResumeSessionIdFromPriorRows,
  resumeCapableForSlug,
  resolveActiveModelRoute,
  smokeRouteModels,
  skeletonReviewLoopWorkerResult,
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
  DispatchContext,
  JudgeResult,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  judgeConverged,
  judgeContinue,
  sampleFinding,
  buildExplicitLandingLiveHooks,
  here,
  realPromptsDir,
  realSoulsDir,
  FINDING,
  ROUND1_SESSION,
  GROK_SLUG,
  cleanups,
  mkDir,
  realRepo966,
  completedJudge,
  FamilyJudgeLedgerBackend,
  grokCmrRoute,
};
