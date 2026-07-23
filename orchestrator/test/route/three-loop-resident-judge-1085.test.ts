/**
 * #1085 / ADR 0147 — three repair rings share one resident-judge hub table.
 *
 * Rings: per-slice review/fix, integrated CMR fixer, wave-verify triage.
 * AC:
 * 1. Same JudgeVerdictStatus enum → isomorphic hub next across three rings
 * 2. Integrated CMR fixer beats resume the resident judge (no builder→reviewer)
 * 3. Wave-verify uses the same hub language + resume semantics as resident judge
 * 4. Negative: any ring path where builder skips judge (direct construction exit
 *    or direct reviewer) fails the assertion
 *
 * Seams (PRD #1080 Testing Decisions): route() + runVerifyCmr + scripted
 * Backend / FamilyBackend — zero new seam.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { route, routeBuilderBeatToResidentJudge } from "../../src/route.js";
import {
  hubNextFromFamilyClosureAction,
  routeResidentJudgeHub,
  type ResidentJudgeHubNext,
  type ResidentJudgeRing,
  type ResidentJudgeStatus,
} from "../../src/residentJudgeHub.js";
import { isJudgeSeat } from "../../src/judgeStation.js";
import { runOrchestrator } from "../../src/runner.js";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  FamilyAbortedEvent,
  FamilyEscalation,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
} from "../../src/family/types.js";
import { buildExplicitLandingLiveHooks } from "../../src/family/landing.js";
import {
  completeReviewPanelLegWorker,
  isReviewPanelLegWorker,
} from "../helpers/review-panel-leg-dispatch.js";
import {
  completedJudge,
  judgeContinue,
  judgeConverged,
  judgeToolchain,
  legacyCmrScriptToWorkerOutput,
  OPEN_COURT_SESSION,
  openCourtWorkerResultIfMatch,
  sampleFinding,
} from "../helpers/judge-fixtures.js";

// ─── pure hub table ─────────────────────────────────────────────────────────

describe("#1085 pure: one status→hub table for three rings", () => {
  const statuses: ResidentJudgeStatus[] = [
    "converged",
    "continue",
    "escalate",
    "toolchain",
    "unusable",
  ];

  it("same status enum yields isomorphic hub next on family_cmr and wave_verify", () => {
    for (const status of statuses) {
      const cmr = routeResidentJudgeHub(status, "family_cmr");
      const wave = routeResidentJudgeHub(status, "wave_verify");
      expect(cmr).toBe(wave);
    }
  });

  it("per_slice matches family on continue / converged / escalate; unusable policy differs", () => {
    expect(routeResidentJudgeHub("continue", "per_slice")).toBe("resume_builder");
    expect(routeResidentJudgeHub("continue", "family_cmr")).toBe("resume_builder");
    expect(routeResidentJudgeHub("continue", "wave_verify")).toBe("resume_builder");

    expect(routeResidentJudgeHub("converged", "per_slice")).toBe("exit_loop");
    expect(routeResidentJudgeHub("converged", "family_cmr")).toBe("exit_loop");
    expect(routeResidentJudgeHub("converged", "wave_verify")).toBe("exit_loop");

    expect(routeResidentJudgeHub("escalate", "per_slice")).toBe("park");
    expect(routeResidentJudgeHub("escalate", "family_cmr")).toBe("park");
    expect(routeResidentJudgeHub("escalate", "wave_verify")).toBe("park");

    expect(routeResidentJudgeHub("toolchain", "per_slice")).toBe("toolchain");
    expect(routeResidentJudgeHub("toolchain", "family_cmr")).toBe("toolchain");
    expect(routeResidentJudgeHub("toolchain", "wave_verify")).toBe("toolchain");

    // Documented dual only for unusable: per-slice never silent-clean (→ builder);
    // family rings fail-loud (#919 M1).
    expect(routeResidentJudgeHub("unusable", "per_slice")).toBe("resume_builder");
    expect(routeResidentJudgeHub("unusable", "family_cmr")).toBe("fail_loud");
    expect(routeResidentJudgeHub("unusable", "wave_verify")).toBe("fail_loud");
  });

  it("FamilyJudgeClosure.action projects onto the same hub next", () => {
    const rings: Array<"family_cmr" | "wave_verify"> = [
      "family_cmr",
      "wave_verify",
    ];
    for (const ring of rings) {
      expect(hubNextFromFamilyClosureAction("pass", ring)).toBe("exit_loop");
      expect(hubNextFromFamilyClosureAction("continue", ring)).toBe(
        "resume_builder",
      );
      expect(hubNextFromFamilyClosureAction("escalate", ring)).toBe("park");
      expect(hubNextFromFamilyClosureAction("toolchain", ring)).toBe(
        "toolchain",
      );
      expect(hubNextFromFamilyClosureAction("unusable", ring)).toBe("fail_loud");
    }
  });

  it("#1080 production family/wave rings share one hub edge vocabulary with per-slice", () => {
    // #1085 AC: 无双规则并存 — family_cmr / wave_verify / per_slice all project
    // the same next-action set through routeResidentJudgeHub /
    // hubNextFromFamilyClosureAction (production verifyCmr + route.ts).
    const actions = [
      "pass",
      "continue",
      "escalate",
      "toolchain",
      "unusable",
    ] as const;
    for (const action of actions) {
      const family = hubNextFromFamilyClosureAction(action, "family_cmr");
      const wave = hubNextFromFamilyClosureAction(action, "wave_verify");
      expect(family).toBe(wave);
      // Map FamilyJudgeClosure.action → ResidentJudgeStatus for per-slice parity.
      const status =
        action === "pass"
          ? ("converged" as const)
          : action === "continue"
            ? ("continue" as const)
            : action === "escalate"
              ? ("escalate" as const)
              : action === "toolchain"
                ? ("toolchain" as const)
                : ("unusable" as const);
      if (status === "unusable") {
        // Documented dual only for unusable (family fail_loud vs per-slice builder).
        expect(routeResidentJudgeHub(status, "per_slice")).toBe("resume_builder");
        expect(family).toBe("fail_loud");
      } else {
        expect(routeResidentJudgeHub(status, "per_slice")).toBe(family);
      }
    }
  });

  it("after every builder beat the next seat is the resident judge (S2→S3 / S5→S6)", () => {
    // Per-slice step mapping is the only fork; both land on judge seats.
    expect(routeBuilderBeatToResidentJudge("S2")).toEqual({
      kind: "next",
      step: "S3",
    });
    expect(routeBuilderBeatToResidentJudge("S5")).toEqual({
      kind: "next",
      step: "S6",
    });
    expect(isJudgeSeat({ step: "S3" })).toBe(true);
    expect(isJudgeSeat({ step: "S6" })).toBe(true);
  });

  it("negative: no status maps to a 'skip_judge' or 'direct_reviewer' hub next", () => {
    const legal: ReadonlySet<ResidentJudgeHubNext> = new Set([
      "resume_builder",
      "exit_loop",
      "park",
      "toolchain",
      "fail_loud",
    ]);
    const rings: ResidentJudgeRing[] = [
      "per_slice",
      "family_cmr",
      "wave_verify",
    ];
    for (const ring of rings) {
      for (const status of statuses) {
        const next = routeResidentJudgeHub(status, ring);
        expect(legal.has(next)).toBe(true);
        // No invented vocabulary for builder→reviewer or builder→exit skips.
        expect(String(next)).not.toMatch(/reviewer|skip|direct/i);
      }
    }
  });

  it("per-slice route() edges consume the shared hub (continue/converged/escalate)", () => {
    expect(
      route({
        from: "S3",
        output: { kind: "judge", status: "continue", findingDispositions: [] },
      }),
    ).toEqual({ kind: "next", step: "S5" });
    expect(
      route({
        from: "S6",
        output: { kind: "judge", status: "converged" },
      }),
    ).toEqual({ kind: "next", step: "S7" });
    expect(
      route({
        from: "S3",
        output: {
          kind: "judge",
          status: "escalate",
          reason: "blocked",
          diagnosis: "needs owner",
        },
      }),
    ).toEqual({ kind: "handoff", status: "parked" });
    // Builder beat → judge only.
    expect(
      route({
        from: "S5",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    ).toEqual({ kind: "next", step: "S6" });
  });
});

// ─── per-slice e2e (ring 1) ─────────────────────────────────────────────────

function makeScratchWorktree(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "hub-1085-"));
  return {
    branch: "feat/orchestrator/issue-1085",
    base: "main",
    path,
  };
}

class SliceHubBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  private judgeRound = 0;
  private s5Round = 0;

  constructor(private readonly worktree: WorktreeHandle) {}

  async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState() {
    return undefined;
  }
  async runStep(): Promise<never> {
    throw new Error("runStep called directly");
  }
  async resumeSession(): Promise<never> {
    throw new Error("resumeSession called directly");
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
  async writeLedger(_entry: PersistentLedgerEntry): Promise<void> {}

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.specs.push(spec);
    this.ctxs.push(ctx);

    const openCourt = openCourtWorkerResultIfMatch(spec, OPEN_COURT_SESSION);
    if (openCourt !== undefined) return openCourt;

    if (spec.kind === "coder") {
      if (spec.id === "S5") {
        this.s5Round += 1;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
          sessionId: "sess-coder-fix-1085",
        };
      }
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "sess-coder-1085",
      };
    }

    if (spec.kind === "verify" || spec.kind === "reviewer") {
      const scripts = [
        completedJudge(
          judgeContinue([sampleFinding()]),
          OPEN_COURT_SESSION,
        ),
        completedJudge(judgeConverged(), OPEN_COURT_SESSION),
      ];
      const result =
        scripts[this.judgeRound] ??
        completedJudge(judgeConverged(), OPEN_COURT_SESSION);
      this.judgeRound += 1;
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : OPEN_COURT_SESSION;
      if (result.kind === "completed") {
        return { ...result, sessionId: result.sessionId ?? sessionId };
      }
      return result;
    }

    throw new Error(`unexpected worker kind ${spec.kind}`);
  }
}

describe("#1085 e2e ring1: per-slice builder beat always hits resident judge", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.stubEnv("ORCHESTRATOR_REPO", "test/repo");
  });

  it("S5 is never followed by a non-judge seat", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    const worktree = makeScratchWorktree();
    const backend = new SliceHubBackend(worktree);
    const result = await runOrchestrator({ issueNumber: 1085, backend });
    expect(result.status).toBe("completed");
    const sequence = backend.specs.map((s) => `${s.id}:${s.kind}`);
    for (let i = 0; i < sequence.length; i += 1) {
      if (sequence[i] === "S5:coder") {
        expect(sequence[i + 1]).toBe("S6:verify");
        expect(sequence[i + 1]).not.toMatch(/:reviewer$/);
      }
      if (sequence[i] === "S2:coder") {
        expect(sequence[i + 1]).toBe("S3:verify");
      }
    }
  });
});

// ─── family fake (rings 2 + 3) ──────────────────────────────────────────────

class FamilyHubBackend implements FamilyBackend {
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
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly dispatches: Array<{
    readonly spec: WorkerSpec;
    readonly ctx: DispatchContext;
  }> = [];
  currentFamilyHead = "head-1085";

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult;
      worker?: (
        spec: WorkerSpec,
        ctx: DispatchContext,
      ) => WorkerResult | Promise<WorkerResult>;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(
    child: MergeRequest,
  ): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async resolveMergeConflict(): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(familyBase: string): Promise<string> {
    void familyBase;
    return this.currentFamilyHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    const result =
      this.script.cmr?.(req) ?? {
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      };
    return result.findings === undefined ? { ...result, findings: [] } : result;
  }
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    const panelLeg = completeReviewPanelLegWorker(spec);
    if (panelLeg !== undefined) {
      this.dispatches.push({ spec, ctx });
      return panelLeg;
    }
    this.dispatches.push({ spec, ctx });
    if (this.script.worker !== undefined) {
      return this.script.worker(spec, ctx);
    }
    if (spec.kind === "cmr") {
      const cmr = await this.runIntegratedCmr({
        familyBase: ctx.familyBase!,
        ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
      });
      return {
        kind: "completed",
        output: legacyCmrScriptToWorkerOutput(cmr),
      };
    }
    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "sess-family-fix-1085",
      };
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: "family/1085",
          pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/1",
          status: "pr_opened",
        },
      };
    }
    throw new Error(`unexpected family worker ${spec.kind}`);
  }
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }
  async openFamilyPr(): Promise<{ pr: string }> {
    return { pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/1" };
  }
}

/**
 * Assert no builder (coder S5) is immediately followed by a reviewer-only
 * panel leg. After a builder beat the next topology worker must be the pure
 * judge (kind cmr / verify seat), not a fresh panel (kind reviewer).
 */
function assertNoBuilderToReviewer(
  dispatches: ReadonlyArray<{ readonly spec: WorkerSpec }>,
): void {
  for (let i = 0; i < dispatches.length - 1; i += 1) {
    const cur = dispatches[i]!.spec;
    const next = dispatches[i + 1]!.spec;
    const isBuilder =
      cur.kind === "coder" && (cur.id === "S5" || cur.role === "coder");
    if (!isBuilder) continue;
    // Negative: builder must not be followed by a bare reviewer kind.
    if (next.kind === "reviewer") {
      throw new Error(
        `builder→reviewer direct edge at dispatch[${i}]→[${i + 1}] ` +
          `(${cur.id}:${cur.kind} → ${next.id}:${next.kind})`,
      );
    }
    // Positive hub: next must be judge court (cmr/verify), not ship/other.
    if (next.kind !== "cmr" && next.kind !== "verify") {
      throw new Error(
        `builder beat not followed by resident judge at dispatch[${i}]→[${i + 1}] ` +
          `(${cur.id}:${cur.kind} → ${next.id}:${next.kind})`,
      );
    }
  }
}

describe("#1085 e2e ring3: wave-verify hub + resume", () => {
  const WAVE_FIXER_SESSION = "sess-wave-fix-1085";
  const WAVE_JUDGE_SESSION = "sess-wave-judge-1085";

  it("continue → fixer → always resume judge before exit; green hard-pre on exit_loop", async () => {
    let verifyCalls = 0;
    let judgeCalls = 0;
    const backend = new FamilyHubBackend({
      verify: () => {
        verifyCalls += 1;
        return verifyCalls >= 2
          ? { ok: true }
          : {
              ok: false,
              errorPackage: { reason: "cross-slice red #1085" },
            };
      },
      worker: (spec) => {
        if (spec.kind === "cmr") {
          judgeCalls += 1;
          return completedJudge(
            judgeCalls === 1
              ? judgeContinue([sampleFinding("wave seam", "w.ts:1")])
              : judgeConverged(),
            WAVE_JUDGE_SESSION,
          );
        }
        if (spec.kind === "coder") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
            sessionId: WAVE_FIXER_SESSION,
          };
        }
        throw new Error(`unexpected ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/1085-wave",
      familyBackend: backend,
      familyHeadAfter: "head-1085",
    });

    expect(result).toEqual({ ok: true, ran: true });
    // Builder beat must not have been the last topology worker before exit.
    expect(judgeCalls).toBeGreaterThanOrEqual(2);
    // Initial red + post-fix green observe; exit reuses observe (#1085 F1).
    expect(verifyCalls).toBe(2);
    const kinds = backend.dispatches.map((d) => d.spec.kind);
    const firstCoder = kinds.indexOf("coder");
    expect(firstCoder).toBeGreaterThanOrEqual(0);
    // After coder-fix there must be another cmr (judge) dispatch.
    expect(kinds.slice(firstCoder + 1).some((k) => k === "cmr")).toBe(true);
    assertNoBuilderToReviewer(backend.dispatches);
    // Judge resume: second wave-judge dispatch carries first session id.
    const judgeCtxs = backend.dispatches
      .filter((d) => d.spec.kind === "cmr")
      .map((d) => d.ctx);
    expect(judgeCtxs.length).toBeGreaterThanOrEqual(2);
    expect(judgeCtxs[0]?.resumeSessionId).toBeUndefined();
    expect(judgeCtxs[1]?.resumeSessionId).toBe(WAVE_JUDGE_SESSION);
  });

  it("wave-fixer second beat resumes prior fixer session (positive resume)", async () => {
    // Two continue rounds → two fixer beats; second must resume first session.
    let verifyCalls = 0;
    let judgeCalls = 0;
    let fixerCalls = 0;
    const backend = new FamilyHubBackend({
      verify: () => {
        verifyCalls += 1;
        // Stay red until after the second fixer beat (verify call #3).
        return verifyCalls >= 3
          ? { ok: true }
          : {
              ok: false,
              errorPackage: { reason: `still red @${verifyCalls}` },
            };
      },
      worker: (spec, ctx) => {
        if (spec.kind === "cmr") {
          judgeCalls += 1;
          if (judgeCalls <= 2) {
            return completedJudge(
              judgeContinue([
                sampleFinding(`wave residual r${judgeCalls}`, `w.ts:${judgeCalls}`),
              ]),
              WAVE_JUDGE_SESSION,
            );
          }
          return completedJudge(judgeConverged(), WAVE_JUDGE_SESSION);
        }
        if (spec.kind === "coder") {
          fixerCalls += 1;
          if (fixerCalls === 1) {
            expect(ctx.resumeSessionId).toBeUndefined();
            expect(spec.session).toBe("fresh");
          } else {
            expect(ctx.resumeSessionId).toBe(WAVE_FIXER_SESSION);
            expect(spec.session).toBe("resume");
          }
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
            sessionId: WAVE_FIXER_SESSION,
          };
        }
        throw new Error(`unexpected ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/1085-wave-fixer-resume",
      familyBackend: backend,
      familyHeadAfter: "head-1085",
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(fixerCalls).toBe(2);
    const coderCtxs = backend.dispatches
      .filter((d) => d.spec.kind === "coder")
      .map((d) => d.ctx);
    expect(coderCtxs[0]?.resumeSessionId).toBeUndefined();
    expect(coderCtxs[1]?.resumeSessionId).toBe(WAVE_FIXER_SESSION);
  });

  it("wave-fixer seat not resume-capable → second beat opens fresh (negative)", async () => {
    let judgeCalls = 0;
    let fixerCalls = 0;
    let verifyCalls = 0;
    const backend = new FamilyHubBackend({
      verify: () => {
        verifyCalls += 1;
        return verifyCalls >= 3
          ? { ok: true }
          : {
              ok: false,
              errorPackage: { reason: `red @${verifyCalls}` },
            };
      },
      worker: (spec, ctx) => {
        if (spec.kind === "cmr") {
          judgeCalls += 1;
          if (judgeCalls <= 2) {
            return completedJudge(
              judgeContinue([
                sampleFinding(`incap r${judgeCalls}`, `i.ts:${judgeCalls}`),
              ]),
              WAVE_JUDGE_SESSION,
            );
          }
          return completedJudge(judgeConverged(), WAVE_JUDGE_SESSION);
        }
        if (spec.kind === "coder") {
          fixerCalls += 1;
          // Capability gate drops resume even when prior session id exists.
          expect(ctx.resumeSessionId).toBeUndefined();
          expect(spec.session).toBe("fresh");
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
            sessionId: WAVE_FIXER_SESSION,
          };
        }
        throw new Error(`unexpected ${spec.kind}`);
      },
    });

    const mod = await import("../../src/modelRegistry.js");
    const spy = vi.spyOn(mod, "resumeCapableForSlug").mockReturnValue(false);
    try {
      const result = await runVerifyCmr({
        phase: "wave",
        familyBase: "family/1085-wave-fixer-incapable",
        familyBackend: backend,
        familyHeadAfter: "head-1085",
      });
      expect(result).toEqual({ ok: true, ran: true });
      expect(fixerCalls).toBe(2);
      const coderCtxs = backend.dispatches
        .filter((d) => d.spec.kind === "coder")
        .map((d) => d.ctx);
      expect(coderCtxs[0]?.resumeSessionId).toBeUndefined();
      expect(coderCtxs[1]?.resumeSessionId).toBeUndefined();
    } finally {
      spy.mockRestore();
    }
  });

  it("negative: empty continue does not spin wave coder-fix", async () => {
    const backend = new FamilyHubBackend({
      verify: () => ({
        ok: false,
        errorPackage: { reason: "red empty-continue" },
      }),
      worker: (spec) => {
        if (spec.kind === "cmr") {
          // continue with 0 live findings — contract drift.
          return completedJudge({
            kind: "judge",
            status: "continue",
            findingDispositions: [],
            fixPacketBody: "empty — must not spin",
          });
        }
        throw new Error(`coder-fix must not run: ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/1085-empty",
      familyBackend: backend,
      familyHeadAfter: "head-1085",
    });

    expect(result.ok).toBe(false);
    expect(result.failedStatus).toBe("verify_failed");
    expect(backend.dispatches.every((d) => d.spec.kind !== "coder")).toBe(true);
  });

  it("toolchain hub next never spins coder-fix (zero-spin)", async () => {
    const backend = new FamilyHubBackend({
      verify: () => ({
        ok: false,
        errorPackage: { reason: "env red" },
      }),
      worker: (spec, ctx) => {
        if (spec.kind === "cmr") {
          return completedJudge(
            judgeToolchain(ctx.waveVerifyFailure ?? "env", "toolchain"),
          );
        }
        throw new Error(`coder-fix must not run on toolchain: ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/1085-toolchain",
      familyBackend: backend,
    });

    expect(result.ok).toBe(false);
    expect(result.failedStatus).toBe("verify_failed");
    expect(backend.dispatches.every((d) => d.spec.kind !== "coder")).toBe(true);
  });
});

describe("#1085 e2e ring2: integrated CMR fixer → resident judge hub", () => {
  it("continue → coder-fix → restart re-opens judge court (not reviewer-only exit)", async () => {
    let correctnessOpens = 0;
    const finding = sampleFinding("cmr seam", "c.ts:2");
    const backend = new FamilyHubBackend({
      verify: () => ({ ok: true }),
      worker: (spec, ctx) => {
        if (spec.kind === "cmr") {
          // Completeness always converges; correctness continues once then converges.
          if (ctx.cmrPass === "completeness") {
            return completedJudge(judgeConverged(), "sess-cmr-comp-1085");
          }
          correctnessOpens += 1;
          if (correctnessOpens === 1) {
            return completedJudge(
              judgeContinue([finding]),
              "sess-cmr-corr-1085",
            );
          }
          return completedJudge(judgeConverged(), "sess-cmr-corr-1085");
        }
        if (spec.kind === "coder") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
            sessionId: "sess-cmr-fix-1085",
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: "family/1085-cmr",
              pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/1085",
              status: "pr_opened",
            },
          };
        }
        throw new Error(`unexpected worker ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1085-cmr",
      familyBackend: backend,
      familyHeadAfter: "head-1085",
    });

    // Correctness continues then fixes then re-opens judge.
    // Topology: after any S5 coder there is a later cmr judge.
    const sequence = backend.dispatches.map(
      (d) => `${d.spec.id}:${d.spec.kind}`,
    );
    expect(sequence.some((s) => s === "S5:coder")).toBe(true);
    for (let i = 0; i < sequence.length; i += 1) {
      if (sequence[i] === "S5:coder") {
        const after = sequence.slice(i + 1);
        expect(after.some((s) => s.startsWith("S3:cmr"))).toBe(true);
      }
    }
    assertNoBuilderToReviewer(backend.dispatches);
    expect(correctnessOpens).toBeGreaterThanOrEqual(2);
    // Result may complete or fail on secondary gates; topology is the contract.
    expect(result.ran).toBe(true);
  });

  it("after builder beat pure receive, converging open re-fans panel legs (ADR 0147 outer gate)", async () => {
    // #1080 completeness F1: receiveBuilderBeat is one-shot for the immediate
    // post-builder open only. Soft-accept of that pure receive must re-open
    // with panel fan-out before the court may close (收敛仍需 fresh 过目).
    let correctnessOpens = 0;
    const finding = sampleFinding("outer-gate seam", "og.ts:1");
    const backend = new FamilyHubBackend({
      verify: () => ({ ok: true }),
      worker: (spec, ctx) => {
        if (spec.kind === "cmr") {
          if (ctx.cmrPass === "completeness") {
            return completedJudge(judgeConverged(), "sess-cmr-comp-og");
          }
          correctnessOpens += 1;
          if (correctnessOpens === 1) {
            return completedJudge(
              judgeContinue([finding]),
              "sess-cmr-corr-og",
            );
          }
          // Pure receive (open 2) and outer-gate open (open 3) both converge.
          return completedJudge(judgeConverged(), "sess-cmr-corr-og");
        }
        if (spec.kind === "coder") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
            sessionId: "sess-cmr-fix-og",
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: "family/1080-outer-gate",
              pr: "https://github.com/Akagilnc/ming-salvage-sim/pull/1080",
              status: "pr_opened",
            },
          };
        }
        throw new Error(`unexpected worker ${spec.kind}`);
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/1080-outer-gate",
      familyBackend: backend,
      familyHeadAfter: "head-1080-og",
    });

    // Count correctness-pass panel legs immediately before each correctness cmr open.
    const panelsPerCorrectnessOpen: number[] = [];
    let pendingCorrectnessPanels = 0;
    for (const d of backend.dispatches) {
      if (isReviewPanelLegWorker(d.spec) && d.ctx.cmrPass === "correctness") {
        pendingCorrectnessPanels += 1;
        continue;
      }
      if (d.spec.kind === "cmr" && d.ctx.cmrPass === "correctness") {
        panelsPerCorrectnessOpen.push(pendingCorrectnessPanels);
        pendingCorrectnessPanels = 0;
      }
    }

    // Open 1 (first court): panels fan. Open 2 (pure receive after fix): 0.
    // Open 3 (independent outer gate): panels fan again before close.
    expect(panelsPerCorrectnessOpen.length).toBeGreaterThanOrEqual(3);
    expect(panelsPerCorrectnessOpen[0]).toBeGreaterThan(0);
    expect(panelsPerCorrectnessOpen[1]).toBe(0);
    expect(panelsPerCorrectnessOpen[2]).toBeGreaterThan(0);
    // Negative topology: builder still never feeds a panel leg directly.
    assertNoBuilderToReviewer(backend.dispatches);
    expect(correctnessOpens).toBeGreaterThanOrEqual(3);
    expect(result.ran).toBe(true);
  });
});
