/**
 * #1086 / ADR 0147 S6 — every builder↔judge beat lands a typed ledger row
 * and progress line; crash resume continues from the last committed beat
 * without re-running completed product beats; ledger write fail-loud.
 *
 * Seams (PRD #1080 Testing Decisions): family/slice route entry + scripted
 * worker backend — no parallel helper-only seam for the runner path.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  isCompletedBeatRerun,
  latestCompletedBeat,
  projectCompletedBeats,
  stampBuilderBeatOnOutput,
} from "../../src/builderJudgeBeat.js";
import { isJudgeOpenCourtSpec } from "../../src/judgeStation.js";
import { clearProgressBroadcastConfig } from "../../src/progressBroadcast.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  ResumeState,
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
  sampleFinding,
} from "../helpers/judge-fixtures.js";
import { entry } from "../helpers/resume-fixtures.js";

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-1086",
  base: "main",
  path: "/resident/worktrees/issue-1086",
};

const STATE_DIR = "/resident/worktrees/.ledger-1086";

class BeatLedgerBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: Array<WorkerLandingPayload | undefined> = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  private coderRound = 0;
  private judgeRound = 0;

  constructor(
    private readonly opts?: {
      readonly judgeResults?: ReadonlyArray<WorkerResult>;
      readonly resumeState?: ResumeState;
      /** Fail writeLedger on the N-th product beat step (1-based among S2/S3/S5/S6). */
      readonly failLedgerOnProductBeat?: number;
      readonly planPhase?: boolean;
    },
  ) {}

  private productBeatWrites = 0;

  async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  async findResumeState() {
    return this.opts?.resumeState;
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
    return this.opts?.resumeState?.worktree ?? WORKTREE;
  }
  async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
    if (
      this.opts?.failLedgerOnProductBeat !== undefined &&
      (entry.step === "S2" ||
        entry.step === "S3" ||
        entry.step === "S5" ||
        entry.step === "S6") &&
      entry.output != null
    ) {
      this.productBeatWrites += 1;
      if (this.productBeatWrites === this.opts.failLedgerOnProductBeat) {
        throw new Error("simulated ledger write failure on product beat");
      }
    }
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
    if (spec.kind === "coder" && (spec.id === "S2" || spec.id === "S5")) {
      this.coderRound += 1;
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : `sess-coder-${spec.id}`;
      if (spec.id === "S2" && this.opts?.planPhase === true && this.coderRound === 1) {
        return {
          kind: "completed",
          sessionId,
          output: {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            beat: "plan",
            planBody: "拟刀口：builderJudgeBeat 单缝 + progress beat 行",
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
          beat: "construct",
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
        return {
          ...scripted,
          sessionId:
            typeof scripted.sessionId === "string"
              ? scripted.sessionId
              : sessionId,
        };
      }
      return completedJudge(judgeConverged(), sessionId);
    }
    throw new Error(`unexpected spec ${spec.id}/${spec.kind}`);
  }
}

describe("#1086 pure beat projection", () => {
  it("projects builder 拍别 and judge 判词终态 from ledger rows", () => {
    const ledger = [
      { step: "S0" as const },
      {
        step: "S2" as const,
        output: {
          kind: "coder" as const,
          committed: false,
          commitsAdded: 0,
          beat: "plan" as const,
        },
      },
      {
        step: "S3" as const,
        output: {
          kind: "judge" as const,
          status: "continue" as const,
          fixPacketBody: "准",
        },
      },
      {
        step: "S2" as const,
        output: {
          kind: "coder" as const,
          committed: true,
          commitsAdded: 1,
          beat: "construct" as const,
        },
      },
      {
        step: "S3" as const,
        output: { kind: "judge" as const, status: "converged" as const },
      },
    ];
    const beats = projectCompletedBeats(ledger);
    expect(beats).toEqual([
      { role: "builder", step: "S2", beatKind: "plan", rotation: 1 },
      {
        role: "judge",
        step: "S3",
        verdict: "continue",
        rotation: 2,
      },
      {
        role: "builder",
        step: "S2",
        beatKind: "construct",
        rotation: 3,
      },
      {
        role: "judge",
        step: "S3",
        verdict: "converged",
        rotation: 4,
      },
    ]);
    expect(latestCompletedBeat(ledger)?.verdict).toBe("converged");
  });

  it("negative: bookkeeping-only rows are not product beats", () => {
    const beats = projectCompletedBeats([
      {
        step: "S1",
        event: "court_opened",
        // no output — pure bookkeeping
      },
      {
        step: "S2",
        event: "worker_monitor_spawned",
      },
    ]);
    expect(beats).toEqual([]);
  });

  it("stampBuilderBeatOnOutput forces construct on S5 and plan when forced", () => {
    const bare = {
      kind: "coder" as const,
      committed: false,
      commitsAdded: 0,
    };
    expect(stampBuilderBeatOnOutput("S5", bare).beat).toBe("construct");
    expect(
      stampBuilderBeatOnOutput("S2", bare, { forcePlan: true }).beat,
    ).toBe("plan");
    expect(
      stampBuilderBeatOnOutput("S2", {
        ...bare,
        committed: true,
        commitsAdded: 1,
      }).beat,
    ).toBe("construct");
  });

  it("isCompletedBeatRerun: same next step as last product beat is re-run", () => {
    const ledger = [
      entry("S2", {
        kind: "coder",
        committed: true,
        commitsAdded: 1,
        beat: "construct",
      }),
    ];
    expect(
      isCompletedBeatRerun({ ledger, nextStep: "S2" }),
    ).toBe(true);
    expect(
      isCompletedBeatRerun({ ledger, nextStep: "S3" }),
    ).toBe(false);
    expect(
      isCompletedBeatRerun({
        ledger,
        nextStep: "S2",
        intentionalReopen: true,
      }),
    ).toBe(false);
  });
});

describe("#1086 runOrchestrator: beat ledger + progress + resume", () => {
  afterEach(() => {
    clearProgressBroadcastConfig();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  /** Capture run.log progress lines (runner binds its own progress ledgerDir). */
  function spyProgressLines(): string[] {
    const lines: string[] = [];
    const orig = console.log.bind(console);
    vi.spyOn(console, "log").mockImplementation((...args: unknown[]) => {
      const s = args.map(String).join(" ");
      if (s.includes("[orchestrator:progress]")) lines.push(s);
      orig(...args);
    });
    return lines;
  }

  it("each builder and judge product beat lands a typed ledger row", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    vi.stubEnv("ORCHESTRATOR_CODER_PLAN_PHASE", "1");
    const progressLines = spyProgressLines();
    const backend = new BeatLedgerBackend({
      planPhase: true,
      judgeResults: [
        completedJudge(judgePlanContinue("准：可施工")),
        completedJudge(judgeConverged()),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 1086, backend });
    expect(result.status).toBe("completed");

    const product = backend.ledgerWrites.filter(
      (e) =>
        (e.step === "S2" ||
          e.step === "S3" ||
          e.step === "S5" ||
          e.step === "S6") &&
        e.output != null,
    );
    // plan S2, plan-review S3, construct S2, post S3
    expect(product.length).toBe(4);

    const beats = projectCompletedBeats(product);
    expect(
      beats.map((b) => ({
        role: b.role,
        step: b.step,
        beatKind: b.beatKind,
        verdict: b.verdict,
      })),
    ).toEqual([
      { role: "builder", step: "S2", beatKind: "plan", verdict: undefined },
      {
        role: "judge",
        step: "S3",
        beatKind: undefined,
        verdict: "continue",
      },
      {
        role: "builder",
        step: "S2",
        beatKind: "construct",
        verdict: undefined,
      },
      {
        role: "judge",
        step: "S3",
        beatKind: undefined,
        verdict: "converged",
      },
    ]);

    // Durable coder rows carry stamped beat (typed 拍别).
    const coderRows = product.filter((e) => e.output?.kind === "coder");
    for (const row of coderRows) {
      expect(row.output?.kind === "coder" && row.output.beat).toBeTruthy();
    }
    // Judge rows carry 判词终态.
    const judgeRows = product.filter((e) => e.output?.kind === "judge");
    for (const row of judgeRows) {
      expect(row.output?.kind === "judge" && row.output.status).toBeTruthy();
    }

    // Progress lines show builder↔judge rotation + typed terminal fields.
    const beatLines = progressLines.filter((l) => l.includes(" beat "));
    expect(beatLines.length).toBeGreaterThanOrEqual(4);
    expect(beatLines.some((l) => l.includes("role=builder") && l.includes("beatKind=plan"))).toBe(
      true,
    );
    expect(
      beatLines.some(
        (l) => l.includes("role=judge") && l.includes("verdict=converged"),
      ),
    ).toBe(true);
    expect(progressLines.some((l) => l.includes("rotation="))).toBe(true);
  });

  it("crash resume continues after last committed beat — does not re-run S2", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    vi.stubEnv("ORCHESTRATOR_CODER_PLAN_PHASE", "1");
    // Ledger ends after plan S2 product beat (crash before judge).
    const resumeState: ResumeState = {
      worktree: WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        {
          ...entry("S2", {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            beat: "plan",
            planBody: "plan survived crash",
          }),
        },
        // court must exist for judge resume continuity when open-court is on
        {
          step: "S1",
          event: "court_opened",
          sessionId: OPEN_COURT_SESSION,
          modelSlug: "test-judge",
          prompt_hash: "hash-court",
          ts: "2026-07-21T00:00:00.000Z",
        } as PersistentLedgerEntry,
      ],
    };
    // Negative pure check: re-dispatching S2 would be a completed-beat re-run.
    expect(
      isCompletedBeatRerun({
        ledger: resumeState.ledger,
        nextStep: "S2",
      }),
    ).toBe(true);

    const backend = new BeatLedgerBackend({
      resumeState,
      planPhase: true,
      judgeResults: [
        completedJudge(judgePlanContinue("准")),
        completedJudge(judgeConverged()),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 10861, backend });
    expect(result.status).toBe("completed");

    // First product dispatch after resume must be judge S3, not re-burn S2 plan.
    const productSpecs = backend.specs.filter((s) => !isJudgeOpenCourtSpec(s));
    expect(productSpecs[0]?.id).toBe("S3");
    // S2 may run again for construct after plan continue — but first S2 plan
    // must not be re-dispatched as the first post-resume product step.
    const firstS2 = productSpecs.find((s) => s.id === "S2");
    if (firstS2 !== undefined) {
      const s2Idx = productSpecs.indexOf(firstS2);
      expect(s2Idx).toBeGreaterThan(0);
      expect(productSpecs[0]!.id).not.toBe("S2");
    }
  });

  it("negative: product-beat ledger write failure is fail-loud (no silent drop)", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    const backend = new BeatLedgerBackend({
      failLedgerOnProductBeat: 1,
      judgeResults: [completedJudge(judgeConverged())],
    });
    const result = await runOrchestrator({ issueNumber: 10862, backend });
    // Fail-loud: public failed + error package; never silent completed.
    expect(result.status).toBe("failed");
    expect(result.errorPackage).toBeDefined();
    expect(result.errorPackage?.reason).toMatch(/ledger write failure|simulated/);
    // No later product beats continued as if the failing write succeeded
    // (judge S3 never ran after S2 write blew up).
    expect(backend.specs.some((s) => s.id === "S3" || s.id === "S6")).toBe(
      false,
    );
  });

  it("fixer↔judge loop also stamps beats (S5 construct + S6 verdict)", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    const progressLines = spyProgressLines();
    const backend = new BeatLedgerBackend({
      judgeResults: [
        completedJudge(
          judgeContinue([sampleFinding()], {
            fixPacketBody: "fix the finding",
          }),
        ),
        completedJudge(judgeConverged()),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 10863, backend });
    expect(result.status).toBe("completed");

    const beats = projectCompletedBeats(
      backend.ledgerWrites.filter((e) => e.output != null),
    );
    expect(beats.some((b) => b.step === "S5" && b.beatKind === "construct")).toBe(
      true,
    );
    expect(beats.some((b) => b.step === "S6" && b.verdict === "converged")).toBe(
      true,
    );

    expect(
      progressLines.some(
        (l) =>
          l.includes(" beat ") &&
          l.includes("role=builder") &&
          l.includes("step=S5") &&
          l.includes("beatKind=construct"),
      ),
    ).toBe(true);
  });
});
