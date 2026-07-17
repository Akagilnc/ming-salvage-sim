/**
 * #979 — family coder-fix (fixer chain) resumes the same session across fix rounds.
 *
 * Defect: runCmrCoderFix always opened fresh (`familyCoderFixWorkerSpec` hard-codes
 * session:"fresh"; cmr_fix_committed never recorded sessionId; production
 * runFamilyCoderFixWorker never threaded Sandcastle resumeSession). Same findings
 * chain's second fix round re-explored from zero context.
 *
 * Acceptance:
 *   1. Same-chain round-2 coder-fix resumes round-1 session (ledger sole truth)
 *   2. Session absent / resume-incapable seat → fresh + negative test
 *   3. Reviewer/cmr legs stay fresh (no regression of judgeReviewLeg / cmr clean eyes)
 *   4. Production runFamilyCoderFixWorker passes Sandcastle resumeSession when
 *      ctx.resumeSessionId is set and the seat is resume-capable
 *   5. existsOnHost false → drop resume (fresh open)
 */

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
const fixerSoul = readFileSync(join(realSoulsDir, "fixer.md"), "utf8");

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
afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

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
          pr: `pr://${ctx.familyBase}`,
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

describe("#979 pure ledger helper — familyCoderFixResumeSessionIdFromLedger", () => {
  it.each([
    {
      name: "empty ledger → undefined",
      ledger: [] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined as string | undefined,
    },
    {
      name: "newest fix row with sessionId wins",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "old",
        },
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "latest",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: "latest",
    },
    {
      name: "newest blank sessionId means fresh (do not resurrect older)",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "kept",
        },
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined,
    },
    {
      name: "other pass fix does not supply this pass resume id",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "correctness",
          sessionId: "corr-only",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined,
    },
    {
      name: "coder_advance after fix invalidates resume (new coder fresh)",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "pre-advance",
        },
        {
          status: "coder_advance",
          event: "coder_advance",
          fromModelId: "grok-4.5",
          toModelId: "opus",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined,
    },
    {
      name: "coder_advance_stay_put does not invalidate",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "still-valid",
        },
        {
          status: "coder_advance_stay_put",
          event: "coder_advance_stay_put",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: "still-valid",
    },
  ])("$name", ({ ledger, pass, expected }) => {
    expect(familyCoderFixResumeSessionIdFromLedger(ledger, pass)).toBe(expected);
  });
});

describe("#979 family coder-fix chain resume from ledger", () => {
  it("same-chain second fix round resumes first-round session (real resume path)", async () => {
    // Round shape: judge continue → coder-fix (sess A) → re-open judge continue
    // → coder-fix MUST resume A → re-open judge converged.
    const backend = new FamilyCoderFixLedgerBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING_R1]), "judge-979");
        }
        if (round === 1) {
          return completedJudge(judgeContinue([FINDING_R2]), "judge-979");
        }
        return completedJudge(judgeConverged(), "judge-979");
      },
      coder: (round, ctx) => {
        if (round === 0) {
          expect(ctx.resumeSessionId).toBeUndefined();
          return completedCoder(FIXER_SESSION);
        }
        // Round 2: real resume of the first fix session.
        expect(ctx.resumeSessionId).toBe(FIXER_SESSION);
        return completedCoder(FIXER_SESSION);
      },
    });
    const route = await resumeCapableCoderFixRoute();
    expect(resumeCapableForSlug(route.slots.coderFix)).toBe(true);

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/979-base",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(result).toEqual({ ok: true, ran: true });

    const coderDispatches = backend.dispatches.filter((d) => d.kind === "coder");
    expect(coderDispatches.length).toBeGreaterThanOrEqual(2);
    expect(coderDispatches[0]?.session).toBe("fresh");
    expect(coderDispatches[0]?.resumeSessionId).toBeUndefined();
    expect(coderDispatches[0]?.model).toBe(route.slots.coderFix);

    expect(coderDispatches[1]?.session).toBe("resume");
    expect(coderDispatches[1]?.resumeSessionId).toBe(FIXER_SESSION);
    expect(coderDispatches[1]?.model).toBe(route.slots.coderFix);

    // Ledger sole truth: sessionId on cmr_fix_committed.
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "cmr_fix_committed" &&
          e.cmrPass === "completeness" &&
          e.sessionId === FIXER_SESSION,
      ),
    ).toBe(true);
  });

  it("session truly absent → second fix opens fresh (negative)", async () => {
    const backend = new FamilyCoderFixLedgerBackend({
      completeness: (round) => {
        if (round <= 1) {
          return completedJudge(
            judgeContinue([round === 0 ? FINDING_R1 : FINDING_R2]),
            "judge-979-loss",
          );
        }
        return completedJudge(judgeConverged(), "judge-979-loss");
      },
      coder: (round, ctx) => {
        // No sessionId on WorkerResult → ledger fix row has nothing to resume.
        expect(ctx.resumeSessionId).toBeUndefined();
        return completedCoder(); // deliberately omit sessionId
      },
    });
    const route = await resumeCapableCoderFixRoute();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/979-loss",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(result).toEqual({ ok: true, ran: true });

    const coderDispatches = backend.dispatches.filter((d) => d.kind === "coder");
    expect(coderDispatches.length).toBeGreaterThanOrEqual(2);
    expect(coderDispatches[0]?.session).toBe("fresh");
    expect(coderDispatches[1]?.session).toBe("fresh");
    expect(coderDispatches[1]?.resumeSessionId).toBeUndefined();
  });

  it("resume-incapable seat → second fix opens fresh (negative)", async () => {
    const backend = new FamilyCoderFixLedgerBackend({
      completeness: (round) => {
        if (round <= 1) {
          return completedJudge(
            judgeContinue([round === 0 ? FINDING_R1 : FINDING_R2]),
            "judge-979-incapable",
          );
        }
        return completedJudge(judgeConverged(), "judge-979-incapable");
      },
      coder: (_round, ctx) => {
        // Capability gate drops resume even when ledger has a prior id.
        expect(ctx.resumeSessionId).toBeUndefined();
        return completedCoder(FIXER_SESSION);
      },
    });
    const route = await resumeCapableCoderFixRoute();
    const mod = await import("../../../src/modelRegistry.js");
    const spy = vi.spyOn(mod, "resumeCapableForSlug").mockReturnValue(false);
    try {
      const result = await runVerifyCmr({
        phase: "final",
        familyBase: "family/979-incapable",
        familyBackend: backend,
        modelRoute: route,
      });
      expect(result).toEqual({ ok: true, ran: true });
      const coderDispatches = backend.dispatches.filter((d) => d.kind === "coder");
      expect(coderDispatches.length).toBeGreaterThanOrEqual(2);
      expect(coderDispatches[0]?.session).toBe("fresh");
      expect(coderDispatches[1]?.session).toBe("fresh");
      expect(coderDispatches[1]?.resumeSessionId).toBeUndefined();
    } finally {
      spy.mockRestore();
    }
  });

  it("reviewer / cmr legs stay fresh (no regression of clean-eyes contract)", async () => {
    expect(judgeReviewLegSessionMode()).toBe("fresh");

    const backend = new FamilyCoderFixLedgerBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING_R1]), "judge-979-fresh");
        }
        return completedJudge(judgeConverged(), "judge-979-fresh");
      },
      coder: () => completedCoder(FIXER_SESSION),
    });
    const route = await resumeCapableCoderFixRoute();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/979-reviewer-fresh",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(result).toEqual({ ok: true, ran: true });

    const cmrDispatches = backend.dispatches.filter((d) => d.kind === "cmr");
    // First open is always fresh; subsequent may resume judge (#966) — that is
    // judge continuity, NOT reviewer-leg clean-eyes. Review legs themselves are
    // always fresh via judgeReviewLegSessionMode.
    expect(cmrDispatches[0]?.session).toBe("fresh");
    // Family cmr kind uses contextRetention clean via cmrWorkerSpec; pin that
    // the first open never carries a fixer resume id.
    for (const d of cmrDispatches) {
      // cmr must never inherit the fixer session id.
      if (d.resumeSessionId !== undefined) {
        expect(d.resumeSessionId).not.toBe(FIXER_SESSION);
      }
    }
  });

  it("recordCmrFixCommitted persists sessionId when provided", async () => {
    const ledger: FamilyLedgerEntry[] = [];
    const backend: Pick<FamilyBackend, "appendFamilyLedger"> = {
      async appendFamilyLedger(entry) {
        ledger.push(entry);
      },
    };
    await recordCmrFixCommitted(backend as FamilyBackend, {
      cmrPass: "completeness",
      familyHeadAfter: "abc",
      blockingFindingIdentityKeys: ["k"],
      sessionId: FIXER_SESSION,
    });
    expect(ledger[0]?.sessionId).toBe(FIXER_SESSION);
    expect(ledger[0]?.status).toBe("cmr_fix_committed");
  });
});

describe("#979 production runFamilyCoderFixWorker Sandcastle resume", () => {
  it("passes Sandcastle resumeSession when ctx carries resumeSessionId + capable seat", async () => {
    // Default coderFix seat is codex (resume-capable); claudeToken-only auth
    // preflight is enough (same shape as #966 runCmrWorker production trap).
    const spec = familyCoderFixWorkerSpec(undefined, "resume");
    expect(resumeCapableForSlug(spec.model)).toBe(true);
    const repo = realRepo979();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];

    class Backend extends RealFamilyBackend {
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

      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runFamilyCoderFixWorker(workerSpec, ctx, {
          blockingFindings: [FINDING_R1],
        });
      }
      protected override mountShipAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override agentForSpec(
        workerSpec: WorkerSpec,
        ctx?: Pick<DispatchContext, "billingPool">,
      ): sc.AgentProvider {
        const agent = super.agentForSpec(workerSpec, ctx);
        return {
          ...agent,
          sessionStorage: {
            ...agent.sessionStorage!,
            existsOnHost: async (_cwd: string, id: string) =>
              id === FIXER_SESSION,
          },
        };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return {
          branch: "fb",
          stdout: "",
          commits: [],
          iterations: [{ sessionId: FIXER_SESSION }],
          output: {
            station: "coderFix",
            status: "completed",
          },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }

    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("979-fix-resume-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(spec, {
      familyBase: "fb",
      resumeSessionId: FIXER_SESSION,
      blockingFindingIdentityKeys: ["k"],
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBe(FIXER_SESSION);
  });

  it("existsOnHost false → fresh Sandcastle open (drop dead session)", async () => {
    const spec = familyCoderFixWorkerSpec(undefined, "resume");
    const repo = realRepo979();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];

    class Backend extends RealFamilyBackend {
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

      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runFamilyCoderFixWorker(workerSpec, ctx, {
          blockingFindings: [FINDING_R1],
        });
      }
      protected override mountShipAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override agentForSpec(
        workerSpec: WorkerSpec,
        ctx?: Pick<DispatchContext, "billingPool">,
      ): sc.AgentProvider {
        const agent = super.agentForSpec(workerSpec, ctx);
        return {
          ...agent,
          sessionStorage: {
            ...agent.sessionStorage!,
            existsOnHost: async () => false,
          },
        };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return {
          branch: "fb",
          stdout: "",
          commits: [],
          iterations: [{ sessionId: "fresh-after-loss-979" }],
          output: {
            station: "coderFix",
            status: "completed",
          },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }

    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("979-fix-loss-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(spec, {
      familyBase: "fb",
      resumeSessionId: "dead-session-979",
      blockingFindingIdentityKeys: ["k"],
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBeUndefined();
  });
});

describe("#979 fixer soul fallback clause", () => {
  it("fixer.md teaches 修法史先于动刀 as resume-loss fallback channel", () => {
    expect(fixerSoul).toContain("修法史先于动刀");
  });
});
