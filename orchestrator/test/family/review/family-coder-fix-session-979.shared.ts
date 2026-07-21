import { execFileSync } from "node:child_process";

import { mkdtempSync, readFileSync, rmSync } from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import type * as sc from "@ai-hero/sandcastle";

import { familyCoderFixWorkerSpec } from "../../../src/family/dispatchFamilyWorker.js";

import {
  familyCoderFixResumeSessionIdFromLedger,
  recordCmrFixCommitted,
} from "../../../src/family/ledger.js";

import {
  RealFamilyBackend,
  type CmrAuth,
} from "../../../src/family/realFamilyBackend.js";

import { runVerifyCmr } from "../../../src/family/verifyCmr.js";

import { resumeCapableForSlug } from "../../../src/modelRegistry.js";

import {
  resolveActiveModelRoute,
  smokeRouteModels,
} from "../../../src/modelRoutes.js";

import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";

import { judgeReviewLegSessionMode } from "../../../src/judgeStation.js";

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

const FINDING_R1 = sampleFinding(
  "family open claim 979 r1",
  "orchestrator/src/family/verifyCmr.ts:979",
);

const FINDING_R2 = sampleFinding(
  "family open claim 979 r2 residual",
  "orchestrator/src/family/verifyCmr.ts:980",
);

const FIXER_SESSION = "fixer-sess-round1-979";

const GROK_SLUG = "grok-4.5";

const cleanups: string[] = [];

function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

function realRepo979(): string {
  const repo = mkDir("979-cmr-repo-");
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

function completedCoder(sessionId?: string): WorkerResult {
  return {
    kind: "completed",
    output: { kind: "coder", committed: true, commitsAdded: 1 },
    ...(sessionId !== undefined ? { sessionId } : {}),
  };
}

class FamilyCoderFixLedgerBackend implements FamilyBackend {
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
  }> = [];
  readonly escalations: FamilyEscalation[] = [];
  currentFamilyHead = "head-r1";

  private completenessRound = 0;
  private correctnessRound = 0;
  private coderFixRound = 0;

  constructor(
    private readonly script: {
      completeness?: (round: number, ctx: DispatchContext) => WorkerResult;
      correctness?: (round: number, ctx: DispatchContext) => WorkerResult;
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
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness") {
        const round = this.completenessRound++;
        if (this.script.completeness !== undefined) {
          return this.script.completeness(round, ctx);
        }
        return completedJudge(judgeConverged(), "judge-comp-979");
      }
      const round = this.correctnessRound++;
      if (this.script.correctness !== undefined) {
        return this.script.correctness(round, ctx);
      }
      return completedJudge(judgeConverged(), "judge-corr-979");
    }

    if (spec.kind === "coder") {
      const round = this.coderFixRound++;
      this.currentFamilyHead = `head-after-fix-${round + 1}`;
      if (this.script.coder !== undefined) {
        return this.script.coder(round, ctx);
      }
      return completedCoder(`${FIXER_SESSION}-r${round + 1}`);
    }

    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase ?? "family/base",
          status: "pr_opened",
          pr: `https://github.com/test/repo/pull/1090`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    throw new Error(`unexpected worker kind ${spec.kind}`);
  }
}

async function resumeCapableCoderFixRoute() {
  // Default normal route: coderFix = gpt-5.6-terra (codex, resume-capable).
  // Keep cmr seats on grok only when we need a known resume-capable judge;
  // coder-fix seat stays the route default so production capability matches.
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
    async () => ({ cliVersion: "test-979" }),
  );
}

export {
  execFileSync,
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
  vi,
  sc,
  familyCoderFixWorkerSpec,
  familyCoderFixResumeSessionIdFromLedger,
  recordCmrFixCommitted,
  RealFamilyBackend,
  CmrAuth,
  runVerifyCmr,
  resumeCapableForSlug,
  resolveActiveModelRoute,
  smokeRouteModels,
  skeletonReviewLoopWorkerResult,
  judgeReviewLegSessionMode,
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
  FINDING_R1,
  FINDING_R2,
  FIXER_SESSION,
  GROK_SLUG,
  cleanups,
  mkDir,
  realRepo979,
  completedJudge,
  completedCoder,
  FamilyCoderFixLedgerBackend,
  resumeCapableCoderFixRoute,
};
