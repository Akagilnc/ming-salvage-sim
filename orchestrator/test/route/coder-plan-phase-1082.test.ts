/**
 * #1082 / ADR 0147 — coder plan-phase closed loop (铺码前过堂).
 *
 * Seam (Testing Decisions #1080 / PRD): family/slice route entry + scripted
 * worker backend only — no parallel helper-test seam.
 *
 * Vitest requires ORCHESTRATOR_CODER_PLAN_PHASE=1 (production always on).
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  CODER_BEAT_CONSTRUCT,
  CODER_BEAT_PLAN,
  shouldRunCoderPlanPhase,
} from "../../src/coderPlanPhase.js";
import { isJudgeOpenCourtSpec } from "../../src/judgeStation.js";
import { route } from "../../src/route.js";
import { runOrchestrator } from "../../src/runner.js";
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
import {
  completedJudge,
  judgeConverged,
  judgeContinue,
  judgePlanContinue,
  OPEN_COURT_SESSION,
  openCourtWorkerResultIfMatch,
} from "../helpers/judge-fixtures.js";
import { completeCmrPanelLegWorker } from "../helpers/cmr-panel-leg-dispatch.js";

/** Fake path — fast pool forbids real git spawn; landing arg is still asserted. */
const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-1082",
  base: "main",
  path: "/resident/worktrees/issue-1082",
};

const PLAN_BODY =
  "拟刀口：在 coderPlanPhase.ts 收敛 plan 相位；route continue→S2；不读散文";

class PlanPhaseBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: Array<WorkerLandingPayload | undefined> = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  private coderRound = 0;
  private judgeRound = 0;

  constructor(
    private readonly opts?: {
      /** Judge scripts after open-court (default: plan approve → converge). */
      readonly judgeResults?: ReadonlyArray<WorkerResult>;
      /** Force second coder beat to re-plan (退回 path). */
      readonly replanOnce?: boolean;
      /**
       * First S2 lies with construct cargo (committed+beat) — runner must
       * still treat first wave as plan (AC: no construct before judge).
       */
      readonly firstBeatConstructLie?: boolean;
    },
  ) {}

  async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState() {
    return undefined;
  }
  async runStep(): Promise<never> {
    throw new Error("runStep called directly — use dispatchWorker");
  }
  async resumeSession(): Promise<never> {
    throw new Error("resumeSession called directly — use dispatchWorker");
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
    return WORKTREE;
  }
  async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
    this.ledgerWrites.push(entry);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.specs.push(spec);
    this.ctxs.push(ctx);
    this.landings.push(landing);

    if (isJudgeOpenCourtSpec(spec)) {
      return openCourtWorkerResultIfMatch(spec, OPEN_COURT_SESSION)!;
    }
    const panelLeg = completeCmrPanelLegWorker(spec);
    if (panelLeg !== undefined) return panelLeg;
    if (spec.kind === "coder" && spec.id === "S2") {
      this.coderRound += 1;
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : "sess-coder-plan";
      if (this.coderRound === 1) {
        if (this.opts?.firstBeatConstructLie === true) {
          // Lying cargo: claim construct on first beat — structural plan wins.
          return {
            kind: "completed",
            sessionId,
            output: {
              kind: "coder",
              committed: true,
              commitsAdded: 1,
              beat: CODER_BEAT_CONSTRUCT,
              planBody: PLAN_BODY,
            },
          };
        }
        return {
          kind: "completed",
          sessionId,
          output: {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            beat: CODER_BEAT_PLAN,
            planBody: PLAN_BODY,
          },
        };
      }
      if (this.opts?.replanOnce === true && this.coderRound === 2) {
        return {
          kind: "completed",
          sessionId,
          output: {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            beat: CODER_BEAT_PLAN,
            planBody: `${PLAN_BODY}（退回后重拟）`,
          },
        };
      }
      return {
        kind: "completed",
        sessionId,
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          beat: CODER_BEAT_CONSTRUCT,
        },
      };
    }
    if (spec.id === "S3" || spec.id === "S6" || spec.kind === "verify") {
      const scripted = this.opts?.judgeResults?.[this.judgeRound];
      this.judgeRound += 1;
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : OPEN_COURT_SESSION;
      if (scripted !== undefined) {
        return scripted.kind === "completed"
          ? { ...scripted, sessionId: scripted.sessionId ?? sessionId }
          : scripted;
      }
      // Default: first judge = plan approve; second = converge post-construct.
      if (this.judgeRound === 1) {
        return completedJudge(judgePlanContinue(), sessionId);
      }
      return completedJudge(judgeConverged(), sessionId);
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }
}

describe("#1082 env gate (production always on)", () => {
  it("shouldRunCoderPlanPhase: production on; vitest off unless env (pos+neg)", () => {
    expect(shouldRunCoderPlanPhase({} as NodeJS.ProcessEnv)).toBe(true);
    expect(
      shouldRunCoderPlanPhase({ VITEST: "true" } as NodeJS.ProcessEnv),
    ).toBe(false);
    expect(
      shouldRunCoderPlanPhase({
        VITEST: "true",
        ORCHESTRATOR_CODER_PLAN_PHASE: "1",
      } as NodeJS.ProcessEnv),
    ).toBe(true);
  });
});

describe("#1082 route table (real entry)", () => {
  it("plan-phase continue→S2; post-construction continue→S5; S2→S3", () => {
    expect(
      route({
        from: "S3",
        output: judgePlanContinue(),
        coderPlanPhase: true,
      }),
    ).toEqual({ kind: "next", step: "S2" });
    expect(
      route({
        from: "S3",
        output: judgePlanContinue("x"),
        coderPlanPhase: false,
      }),
    ).toEqual({ kind: "next", step: "S5" });
    expect(
      route({
        from: "S2",
        output: { kind: "coder", committed: false, commitsAdded: 0 },
      }),
    ).toEqual({ kind: "next", step: "S3" });
  });
});

describe("#1082 runOrchestrator: plan → judge → construct closed loop", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  const runPlanPhase = async (fn: () => Promise<void>) => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    vi.stubEnv("ORCHESTRATOR_CODER_PLAN_PHASE", "1");
    await fn();
  };

  it("plan beat → resident judge resume → same coder construct → converge", async () => {
    await runPlanPhase(async () => {
      const backend = new PlanPhaseBackend();
      const result = await runOrchestrator({ issueNumber: 1082, backend });
      expect(result.status).toBe("completed");

      const s2 = backend.specs.filter((s) => s.id === "S2");
      expect(s2.length).toBe(2);
      // First S2 fresh plan; second resumes same coder session.
      expect(s2[0]!.session).toBe("fresh");
      expect(s2[1]!.session).toBe("resume");
      const constructCtx = backend.ctxs[backend.specs.indexOf(s2[1]!)];
      expect(constructCtx?.resumeSessionId).toBe("sess-coder-plan");

      const s3 = backend.specs.filter((s) => s.id === "S3");
      expect(s3.length).toBe(2);
      // Both judging rounds resume open court — no fresh judge leg.
      expect(s3.every((s) => s.session === "resume")).toBe(true);
      for (const spec of s3) {
        const ctx = backend.ctxs[backend.specs.indexOf(spec)];
        expect(ctx?.resumeSessionId).toBe(OPEN_COURT_SESSION);
      }

      // Order: open-court → S2 plan → S3 plan-review → S2 construct → S3 post
      const ids = backend.specs.map((s) =>
        isJudgeOpenCourtSpec(s) ? "open-court" : s.id,
      );
      expect(ids).toEqual(["open-court", "S2", "S3", "S2", "S3"]);

      // Plan body transported to first S3 (dumb copy) — landing arg from runner.
      const firstS3Idx = backend.specs.findIndex((s) => s.id === "S3");
      expect(backend.landings[firstS3Idx]?.builderPlanBody).toBe(PLAN_BODY);

      // Judge boundary prose + after_plan_verdict hint on second S2.
      const secondS2Idx = backend.specs
        .map((s, i) => ({ s, i }))
        .filter(({ s }) => s.id === "S2")[1]!.i;
      expect(backend.landings[secondS2Idx]?.builderBeat).toBe(
        "after_plan_verdict",
      );
      expect(
        typeof backend.landings[secondS2Idx]?.fixPacketBody === "string" &&
          backend.landings[secondS2Idx]!.fixPacketBody!.length > 0,
      ).toBe(true);

      // First S2 beat hint is plan; no construct before first judge.
      const firstS2Idx = backend.specs.findIndex((s) => s.id === "S2");
      expect(backend.landings[firstS2Idx]?.builderBeat).toBe("plan");
      // Negative: no S5 fixer during plan pre-review.
      expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
    });
  });

  it("negative: judge 退回 keeps next beat as plan (re-plan before construct)", async () => {
    await runPlanPhase(async () => {
      const backend = new PlanPhaseBackend({
        replanOnce: true,
        judgeResults: [
          completedJudge(
            judgePlanContinue("退回：seam 选错，请改收敛到 route 单缝"),
          ),
          completedJudge(judgePlanContinue("准：可施工")),
          completedJudge(judgeConverged()),
        ],
      });
      const result = await runOrchestrator({ issueNumber: 10821, backend });
      expect(result.status).toBe("completed");

      const s2 = backend.specs.filter((s) => s.id === "S2");
      // plan → (退回) re-plan → construct
      expect(s2.length).toBe(3);
      // All post-first S2 resume same session (no fresh mid-loop).
      expect(s2[1]!.session).toBe("resume");
      expect(s2[2]!.session).toBe("resume");

      const ids = backend.specs.map((s) =>
        isJudgeOpenCourtSpec(s) ? "open-court" : s.id,
      );
      expect(ids).toEqual([
        "open-court",
        "S2",
        "S3",
        "S2",
        "S3",
        "S2",
        "S3",
      ]);
      // Still no fixer during plan loop.
      expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
    });
  });

  it("plan-phase continue + advanceCoder still resumes same S2 session", async () => {
    // advanceCoder rewrites coderFix only; during plan phase route re-enters S2
    // (coder slot). Clearing the shared coderSessionId would force a fresh S2
    // and discard plan-phase builder continuity (#1082 cheap-resume).
    await runPlanPhase(async () => {
      const backend = new PlanPhaseBackend({
        judgeResults: [
          completedJudge({
            ...judgePlanContinue("准：可施工；repair seat → sol@med"),
            advanceCoder: "sol@med",
          }),
          completedJudge(judgeConverged()),
        ],
      });
      const result = await runOrchestrator({ issueNumber: 10824, backend });
      expect(result.status).toBe("completed");
      const s2 = backend.specs.filter((s) => s.id === "S2");
      expect(s2.length).toBe(2);
      expect(s2[0]!.session).toBe("fresh");
      // Second S2 must resume the plan-phase builder — not a silent fresh mint.
      expect(s2[1]!.session).toBe("resume");
      const constructCtx = backend.ctxs[backend.specs.indexOf(s2[1]!)];
      expect(constructCtx?.resumeSessionId).toBe("sess-coder-plan");
      // advanceCoder audit still lands (coderFix rewrite is independent).
      expect(
        result.stepLedger.some((e) => e.event === "coder_advance"),
      ).toBe(true);
      // Negative: no fixer during plan pre-review.
      expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
    });
  });

  it("negative: first-beat construct cargo lie still routes plan→S2 not S5/S7", async () => {
    await runPlanPhase(async () => {
      const backend = new PlanPhaseBackend({
        firstBeatConstructLie: true,
      });
      const result = await runOrchestrator({ issueNumber: 10823, backend });
      expect(result.status).toBe("completed");
      // Structural first wave stays plan: empty plan-continue resumes S2.
      const s2 = backend.specs.filter((s) => s.id === "S2");
      expect(s2.length).toBe(2);
      expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
      const ids = backend.specs.map((s) =>
        isJudgeOpenCourtSpec(s) ? "open-court" : s.id,
      );
      expect(ids).toEqual(["open-court", "S2", "S3", "S2", "S3"]);
    });
  });

  it("negative: without plan-phase env, empty continue after paper still fails (no S2 spin)", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    // deliberately NOT set ORCHESTRATOR_CODER_PLAN_PHASE
    const backend = new PlanPhaseBackend({
      judgeResults: [
        completedJudge(judgePlanContinue()),
        // #1126: first empty continue requests legs; second empty with paper
        // is still contract drift (must not resume S2 / spin S5).
        completedJudge(judgePlanContinue()),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 10822, backend });
    expect(result.status).toBe("failed");
    expect(result.errorPackage).toBeDefined();
    // First S2 may have run (as legacy implement), then S3 empty-after-paper dies.
    // Must not resume a second S2 from empty continue.
    const s2Count = backend.specs.filter((s) => s.id === "S2").length;
    expect(s2Count).toBe(1);
    expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
  });

  it("negative: plan-phase terminal-only continue fails loud (no silent S7)", async () => {
    await runPlanPhase(async () => {
      const backend = new PlanPhaseBackend({
        judgeResults: [
          completedJudge(
            judgeContinue([], {
              kill: [
                {
                  identityKey: "bogus-plan-kill",
                  action: "refute",
                  reason: "not_established",
                  evidence: "plan pre-review must not emit kill rows",
                },
              ],
              fixPacketBody: "terminal-only under plan phase (illegal)",
            }),
          ),
        ],
      });
      const result = await runOrchestrator({ issueNumber: 10825, backend });
      expect(result.status).toBe("failed");
      expect(result.errorPackage).toBeDefined();
      // No second S2 construct and no silent completed handoff.
      expect(backend.specs.filter((s) => s.id === "S2").length).toBe(1);
      expect(result.status).not.toBe("completed");
    });
  });
});
