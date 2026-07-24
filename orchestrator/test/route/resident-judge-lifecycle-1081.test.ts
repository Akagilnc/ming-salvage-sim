/**
 * #1081 / ADR 0147 — resident judge lifecycle skeleton:
 * open court at slice dispatch → resume every judging round → dismiss on converge.
 *
 * Seams (Testing Decisions #1080 / PRD):
 * 1. Pure helpers — rebuild / require resume / open-court gate
 * 2. runOrchestrator + scripted Backend — birth / resume / dismiss / fail-loud
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  isJudgeOpenCourtSpec,
  JUDGE_OPEN_COURT_PROMPT_FILE,
  rebuildResidentJudgeFromLedger,
  requireOpenCourtSession,
  requireResidentJudgeResume,
  usesJudgeReceiptChannel,
} from "../../src/judgeStation.js";
import { runOrchestrator, sliceQuotaWaitPending } from "../../src/runner.js";
import { CapacityRelayError } from "../../src/relayDispatch.js";
import { resetRoutePresetsCacheForTests } from "../../src/modelRoutes.js";
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
  judgeEscalate,
  OPEN_COURT_SESSION,
  openCourtWorkerResultIfMatch,
  sampleFinding,
} from "../helpers/judge-fixtures.js";
import { completeReviewPanelLegWorker } from "../helpers/review-panel-leg-dispatch.js";

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-1081",
  base: "main",
  path: "/resident/worktrees/issue-1081",
};

class LifecycleBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  private judgeRound = 0;
  private openCourtFirstThrowDone = false;
  private judgeResumeFirstThrowDone = false;

  constructor(
    private readonly judgeResults: ReadonlyArray<WorkerResult> = [
      completedJudge(judgeConverged(), OPEN_COURT_SESSION),
    ],
    private readonly openCourtResult?: WorkerResult,
    private readonly opts?: {
      readonly resumeState?: import("../../src/types.js").ResumeState;
      /** Open-court dispatch throws instead of returning (L5 throw arm). */
      readonly openCourtThrow?: Error;
      readonly openCourtFirstThrow?: Error;
      readonly judgeResumeFirstThrow?: Error;
      readonly judgeResumeThrowStep?: "S3" | "S6";
      readonly issueBody?: string;
    },
  ) {}

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
      ...(this.opts?.issueBody !== undefined ? { body: this.opts.issueBody } : {}),
    };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return this.opts?.resumeState?.worktree ?? WORKTREE;
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
    const panelLeg = completeReviewPanelLegWorker(spec);
    if (panelLeg !== undefined) return panelLeg;

    if (isJudgeOpenCourtSpec(spec)) {
      if (
        this.opts?.openCourtFirstThrow !== undefined &&
        !this.openCourtFirstThrowDone
      ) {
        this.openCourtFirstThrowDone = true;
        throw this.opts.openCourtFirstThrow;
      }
      if (this.opts?.openCourtThrow !== undefined) {
        throw this.opts.openCourtThrow;
      }
      if (this.openCourtResult !== undefined) return this.openCourtResult;
      return openCourtWorkerResultIfMatch(spec, OPEN_COURT_SESSION)!;
    }
    if (spec.kind === "coder") {
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId:
          typeof ctx.resumeSessionId === "string"
            ? ctx.resumeSessionId
            : "sess-coder",
      };
    }
    if (spec.id === "S3" || spec.id === "S6" || spec.kind === "verify") {
      if (
        this.opts?.judgeResumeFirstThrow !== undefined &&
        typeof ctx.resumeSessionId === "string" &&
        (this.opts.judgeResumeThrowStep === undefined ||
          this.opts.judgeResumeThrowStep === spec.id) &&
        !this.judgeResumeFirstThrowDone
      ) {
        this.judgeResumeFirstThrowDone = true;
        throw this.opts.judgeResumeFirstThrow;
      }
      const scripted = this.judgeResults[this.judgeRound];
      const isContinue =
        scripted?.kind === "completed" &&
        scripted.output?.kind === "judge" &&
        scripted.output.status === "continue";
      if (!isContinue || (landing?.panelLegTransports?.length ?? 0) > 0) {
        this.judgeRound += 1;
      }
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : OPEN_COURT_SESSION;
      if (scripted !== undefined) {
        return scripted.kind === "completed"
          ? { ...scripted, sessionId: scripted.sessionId ?? sessionId }
          : scripted;
      }
      return completedJudge(judgeConverged(), sessionId);
    }
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }
}

describe("#1081 pure: resident judge lifecycle helpers", () => {
  it("open-court prompt is the sole birth discriminant (positive + negative)", () => {
    expect(isJudgeOpenCourtSpec({ promptFile: JUDGE_OPEN_COURT_PROMPT_FILE })).toBe(
      true,
    );
    expect(isJudgeOpenCourtSpec({ promptFile: "judge_station.md" })).toBe(false);
    expect(usesJudgeReceiptChannel({ id: "S1", promptFile: JUDGE_OPEN_COURT_PROMPT_FILE })).toBe(
      true,
    );
    expect(usesJudgeReceiptChannel({ id: "S9", promptFile: "verify.md" })).toBe(
      false,
    );
  });

  it("rebuild: court_opened → open; court_dismissed → dismissed (positive)", () => {
    expect(
      rebuildResidentJudgeFromLedger([
        {
          event: "court_opened",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
      ]),
    ).toEqual({ status: "open", sessionId: "j1", modelSlug: "gpt-5.4" });

    expect(
      rebuildResidentJudgeFromLedger([
        {
          event: "court_opened",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        {
          step: "S3",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
          output: { kind: "judge" },
        },
        { event: "court_dismissed", sessionId: "j1" },
      ]),
    ).toEqual({ status: "dismissed" });
  });

  it("rebuild: empty ledger is absent; judge continuity_lost clears (negative)", () => {
    expect(rebuildResidentJudgeFromLedger([])).toEqual({ status: "absent" });
    // Judge-seat continuity_lost orphans the court (pre-#1081 migration / loss).
    expect(
      rebuildResidentJudgeFromLedger([
        {
          event: "court_opened",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        {
          event: "session_continuity_lost",
          step: "S3",
          sessionId: "j1",
        },
      ]),
    ).toEqual({ status: "absent" });
  });

  it("rebuild: coder-seat continuity_lost does NOT orphan open court (L1 negative)", () => {
    // Coder-seat continuity loss must leave the judge court open; only a
    // judge-seat continuity loss orphans that court.
    expect(
      rebuildResidentJudgeFromLedger([
        {
          event: "court_opened",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        {
          step: "S3",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
          output: { kind: "judge" },
        },
        {
          event: "session_continuity_lost",
          step: "S5",
          sessionId: "coder-sess",
        },
      ]),
    ).toEqual({ status: "open", sessionId: "j1", modelSlug: "gpt-5.4" });
  });

  it("rebuild: runner/monitor UUID never replaces resident session authority", () => {
    expect(
      rebuildResidentJudgeFromLedger([
        {
          event: "court_opened",
          sessionId: "real-judge-session",
          modelSlug: "gpt-5.4",
          runId: "run-uuid",
        },
        {
          step: "S6",
          sessionId: "run-uuid",
          runId: "run-uuid",
          modelSlug: "gpt-5.4",
          output: {
            kind: "judge",
            status: "continue",
            findingDispositions: [],
            fixPacketBody: "继续修",
          },
        },
      ]),
    ).toEqual({
      status: "open",
      sessionId: "real-judge-session",
      modelSlug: "gpt-5.4",
    });
  });

  it("require resume: open→resume; absent/model-move→establish; incapable/dismissed fail", () => {
    const ok = requireResidentJudgeResume({
      lifecycle: {
        status: "open",
        sessionId: "j1",
        modelSlug: "gpt-5.4",
      },
      seatModel: "gpt-5.4",
      seatResumeCapable: true,
    });
    expect(ok).toEqual({ kind: "resume", sessionId: "j1" });

    // Absent = legal establish (crash/migration birth).
    expect(
      requireResidentJudgeResume({
        lifecycle: { status: "absent" },
        seatModel: "gpt-5.4",
        seatResumeCapable: true,
      }),
    ).toEqual({ kind: "establish" });
    // Model move under open court = re-birth under new seat.
    expect(
      requireResidentJudgeResume({
        lifecycle: {
          status: "open",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        seatModel: "other-model",
        seatResumeCapable: true,
      }),
    ).toEqual({ kind: "establish" });
    // Open + same model + not resume-capable = fail loud (AC#3; L2).
    expect(
      requireResidentJudgeResume({
        lifecycle: {
          status: "open",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        seatModel: "gpt-5.4",
        seatResumeCapable: false,
      }).kind,
    ).toBe("fail");
    // Absent / model-move establish arms also require resume-capable seat
    // (same gate as open-court; no silent non-resident mint).
    expect(
      requireResidentJudgeResume({
        lifecycle: { status: "absent" },
        seatModel: "gpt-5.4",
        seatResumeCapable: false,
      }).kind,
    ).toBe("fail");
    expect(
      requireResidentJudgeResume({
        lifecycle: {
          status: "open",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        seatModel: "other-model",
        seatResumeCapable: false,
      }).kind,
    ).toBe("fail");
    // Dismissed never reopens.
    expect(
      requireResidentJudgeResume({
        lifecycle: { status: "dismissed" },
        seatModel: "gpt-5.4",
        seatResumeCapable: true,
      }).kind,
    ).toBe("fail");
  });

  it("sliceQuotaWaitPending: dual-field court_dismissed+converge clears prior quota park", () => {
    // Counterexample from correctness court: quota wall on S6, then atomic
    // fold converge+dismiss. Park must clear — not leave S6 still-pending so
    // re-feed re-enters a dismissed court and errorTerminates forever.
    expect(
      sliceQuotaWaitPending([
        { step: "S6", event: "quota_wait_for_reset" },
        {
          step: "S6",
          event: "court_dismissed",
          output: { kind: "judge", status: "converged" },
        },
      ]),
    ).toBeUndefined();
    // Negative: bare quota park with no later executable progress stays pending.
    expect(
      sliceQuotaWaitPending([{ step: "S6", event: "quota_wait_for_reset" }]),
    ).toBe("S6");
    // Negative: pure bookkeeping dismiss without topology output does NOT clear.
    expect(
      sliceQuotaWaitPending([
        { step: "S6", event: "quota_wait_for_reset" },
        { step: "S6", event: "court_dismissed" },
      ]),
    ).toBe("S6");
    // Positive: classic event-less agent row still clears (regression).
    expect(
      sliceQuotaWaitPending([
        { step: "S5", event: "quota_wait_for_reset" },
        { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      ]),
    ).toBeUndefined();
  });

  it("rebuild heal: court_opened + product converge without dismiss → dismissed", () => {
    // Pre-atomic two-write crash window: converge row landed, dismiss did not.
    expect(
      rebuildResidentJudgeFromLedger([
        {
          event: "court_opened",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        {
          step: "S3",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
          output: { kind: "judge", status: "converged" },
        },
      ]),
    ).toEqual({ status: "dismissed" });
    // Negative: continue is not product converge — court stays open.
    expect(
      rebuildResidentJudgeFromLedger([
        {
          event: "court_opened",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        {
          step: "S3",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
          output: {
            kind: "judge",
            status: "continue",
            findingDispositions: [],
            fixPacketBody: "still open",
          },
        },
      ]),
    ).toEqual({ status: "open", sessionId: "j1", modelSlug: "gpt-5.4" });
  });

  it("open-court gate: missing session / not resume-capable fail (negative)", () => {
    expect(
      requireOpenCourtSession({
        resultKind: "completed",
        sessionId: "j1",
        seatResumeCapable: true,
        seatModel: "gpt-5.4",
      }),
    ).toEqual({ kind: "ok", sessionId: "j1" });

    expect(
      requireOpenCourtSession({
        resultKind: "completed",
        sessionId: undefined,
        seatResumeCapable: true,
        seatModel: "gpt-5.4",
      }).kind,
    ).toBe("fail");
    expect(
      requireOpenCourtSession({
        resultKind: "failed",
        sessionId: "j1",
        seatResumeCapable: true,
        seatModel: "gpt-5.4",
      }).kind,
    ).toBe("fail");
    expect(
      requireOpenCourtSession({
        resultKind: "completed",
        sessionId: "j1",
        seatResumeCapable: false,
        seatModel: "gpt-5.4",
      }).kind,
    ).toBe("fail");
  });
});

describe("#1081 runOrchestrator: birth → resume → dismiss", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  // Production open-court path (vitest default skips birth for fixture tax).
  const runReal = async (fn: () => Promise<void>) => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    await fn();
  };

  it("opens court at S1; S3/S6 resume same session; dismisses on converge", async () => {
    await runReal(async () => {
    const backend = new LifecycleBackend([
      completedJudge(
        judgeContinue([sampleFinding("live", "a.ts:1")]),
        OPEN_COURT_SESSION,
      ),
      completedJudge(judgeConverged(), OPEN_COURT_SESSION),
    ]);
    const result = await runOrchestrator({ issueNumber: 1081, backend });
    expect(result.status).toBe("completed");

    const openSpec = backend.specs.find((s) =>
      isJudgeOpenCourtSpec(s),
    );
    expect(openSpec).toBeDefined();
    expect(openSpec!.id).toBe("S1");
    expect(openSpec!.session).toBe("fresh");
    expect(openSpec!.promptFile).toBe(JUDGE_OPEN_COURT_PROMPT_FILE);

    const s3 = backend.specs.find((s) => s.id === "S3");
    const s6 = backend.specs.find((s) => s.id === "S6");
    expect(s3?.session).toBe("resume");
    expect(s6?.session).toBe("resume");

    const s3Ctx = backend.ctxs[backend.specs.indexOf(s3!)];
    const s6Ctx = backend.ctxs[backend.specs.indexOf(s6!)];
    expect(s3Ctx?.resumeSessionId).toBe(OPEN_COURT_SESSION);
    expect(s6Ctx?.resumeSessionId).toBe(OPEN_COURT_SESSION);

    // Ledger proves same judge throughout + dismiss after converge.
    const opened = result.stepLedger.find((e) => e.event === "court_opened");
    const dismissed = result.stepLedger.find(
      (e) => e.event === "court_dismissed",
    );
    expect(opened?.sessionId).toBe(OPEN_COURT_SESSION);
    expect(dismissed?.sessionId).toBe(OPEN_COURT_SESSION);
    // Atomic fold: court_dismissed rides the same durable row as the
    // product-converge judge step (no separate two-write window).
    expect(dismissed?.output?.kind).toBe("judge");
    // Negative: no hanging open court after dismiss in durable writes.
    const lastLifecycle = [...backend.ledgerWrites]
      .reverse()
      .find(
        (e) => e.event === "court_opened" || e.event === "court_dismissed",
      );
    expect(lastLifecycle?.event).toBe("court_dismissed");
    // Single durable write carries both converge output and dismiss event.
    expect(lastLifecycle?.output?.kind).toBe("judge");
    });
  });

  it("explicit judge session-not-found records continuity loss and fresh-reopens with prior verdicts", async () => {
    await runReal(async () => {
      const live = sampleFinding("live-after-reopen", "resume.ts:1");
      const backend = new LifecycleBackend(
        [
          completedJudge(judgeContinue([live]), "fresh-judge-session"),
          completedJudge(judgeConverged(), "fresh-judge-session"),
        ],
        undefined,
        {
          judgeResumeFirstThrow: new Error(
            `Session resume failed: session ${OPEN_COURT_SESSION} not found`,
          ),
          judgeResumeThrowStep: "S6",
        },
      );

      const result = await runOrchestrator({ issueNumber: 11281, backend });
      expect(result.status).toBe("completed");

      const lost = backend.ledgerWrites.find(
        (entry) =>
          entry.event === "session_continuity_lost" && entry.step === "S6",
      );
      expect(lost).toMatchObject({
        event: "session_continuity_lost",
        step: "S6",
        sessionId: "fresh-judge-session",
      });
      expect(lost?.reason).toContain("not found");

      const freshReopenIndex = backend.specs.findIndex(
        (spec, index) =>
          spec.id === "S6" &&
          spec.session === "fresh" &&
          (backend.ctxs[index]?.priorJudgeVerdicts?.length ?? 0) > 0,
      );
      expect(freshReopenIndex).toBeGreaterThanOrEqual(0);
      expect(backend.ctxs[freshReopenIndex]?.resumeSessionId).toBeUndefined();
    });
  });

  it("#1135 S6 judge model move records continuity loss and fresh-reopens with durable court cargo", async () => {
    await runReal(async () => {
      const routeDir = mkdtempSync(join(tmpdir(), "route-presets-1135-"));
      try {
        const presets = JSON.parse(
          readFileSync(new URL("../../config/route-presets.json", import.meta.url), "utf8"),
        ) as Record<string, { slots: Record<string, string> }>;
        presets.normal!.slots.verify = "gpt-5.6-sol-high";
        const routePath = join(routeDir, "route-presets.json");
        writeFileSync(routePath, JSON.stringify(presets));
        vi.stubEnv("ORCHESTRATOR_ROUTE_PRESETS_PATH", routePath);
        resetRoutePresetsCacheForTests();

        const oldJudgeSession = "judge-sol-session";
        const ownerAnswer = "owner: continue at S6";
        const persisted = (
          entry: Omit<PersistentLedgerEntry, "sessionId" | "prompt_hash" | "ts"> &
            Partial<Pick<PersistentLedgerEntry, "sessionId">>,
        ): PersistentLedgerEntry => ({
          sessionId: "run-uuid",
          prompt_hash: "h",
          ts: "2026-07-25T00:00:00.000Z",
          ...entry,
        });
        const priorLedger: PersistentLedgerEntry[] = [
          persisted({
            step: "S2",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          }),
          persisted({
            step: "S3",
            sessionId: oldJudgeSession,
            modelSlug: "gpt-5.6-sol",
            output: judgeContinue([sampleFinding("prior-live", "prior.ts:1")]),
          }),
          persisted({
            step: "S5",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          }),
          persisted({
            step: "S6",
            sessionId: oldJudgeSession,
            modelSlug: "gpt-5.6-sol",
            output: judgeEscalate("owner decision required", "await answer"),
          }),
          persisted({
            step: "S8",
            handoffStatus: "parked",
            escalationKind: "decision",
          }),
          persisted({
            event: "escalation_answered",
            step: "S6",
            forStep: "S6",
            answer: ownerAnswer,
            source: "human",
          }),
        ];
        const backend = new LifecycleBackend([completedJudge(judgeConverged())], undefined, {
          resumeState: {
            worktree: WORKTREE,
            stateDir: "/resident/worktrees/.ledger-1135",
            ledger: priorLedger,
          },
        });

        const result = await runOrchestrator({ issueNumber: 1135, backend });
        expect({
          status: result.status,
          lost: backend.ledgerWrites.filter(
            (entry) => entry.event === "session_continuity_lost",
          ),
          specs: backend.specs,
          ctx: backend.ctxs[0],
        }).toMatchObject({
          status: "completed",
          lost: [
            {
              step: "S6",
              sessionId: oldJudgeSession,
              fromModelId: "gpt-5.6-sol",
              toModelId: "gpt-5.6-sol-high",
            },
          ],
          specs: [{ id: "S6", model: "gpt-5.6-sol-high", session: "fresh" }],
          ctx: {
            worktree: WORKTREE,
            escalationAnswer: { forStep: "S6", answer: ownerAnswer },
            priorJudgeVerdicts: [
              {
                step: "S3",
                sessionId: oldJudgeSession,
                status: "continue",
              },
              {
                step: "S6",
                sessionId: oldJudgeSession,
                status: "escalate",
              },
            ],
          },
        });
        expect(backend.ctxs[0]?.resumeSessionId).toBeUndefined();

        const matchingLoss = persisted({
          event: "session_continuity_lost",
          step: "S6",
          sessionId: oldJudgeSession,
          fromModelId: "gpt-5.6-sol",
          toModelId: "gpt-5.6-sol-high",
          reason:
            "model_mismatch (session=gpt-5.6-sol, seat=gpt-5.6-sol-high)",
        });
        const crashResumeLedger = [...priorLedger, matchingLoss];
        const crashResumeBackend = new LifecycleBackend(
          [completedJudge(judgeConverged())],
          undefined,
          {
            resumeState: {
              worktree: WORKTREE,
              stateDir: "/resident/worktrees/.ledger-1135",
              ledger: crashResumeLedger,
            },
          },
        );
        const crashResumed = await runOrchestrator({
          issueNumber: 1135,
          backend: crashResumeBackend,
        });
        expect({
          status: crashResumed.status,
          durableLosses: [
            ...crashResumeLedger,
            ...crashResumeBackend.ledgerWrites,
          ].filter((entry) => entry.event === "session_continuity_lost"),
          newLossWrites: crashResumeBackend.ledgerWrites.filter(
            (entry) => entry.event === "session_continuity_lost",
          ),
          freshS6Dispatches: crashResumeBackend.specs.filter(
            (spec) => spec.id === "S6" && spec.session === "fresh",
          ),
        }).toMatchObject({
          status: "completed",
          durableLosses: [matchingLoss],
          newLossWrites: [],
          freshS6Dispatches: [
            {
              id: "S6",
              model: "gpt-5.6-sol-high",
              session: "fresh",
            },
          ],
        });

        const writeFailureBackend = new LifecycleBackend([], undefined, {
          resumeState: await backend.findResumeState(),
        });
        vi.spyOn(writeFailureBackend, "writeLedger").mockRejectedValueOnce(
          new Error("continuity ledger unavailable"),
        );
        const failed = await runOrchestrator({ issueNumber: 1135, backend: writeFailureBackend });
        expect({
          result: failed,
          lost: failed.stepLedger.filter(
            (entry) => entry.event === "session_continuity_lost",
          ).length,
          s6: failed.stepLedger.filter((entry) => entry.step === "S6").length,
          s8: failed.stepLedger.filter((entry) => entry.step === "S8").length,
          dispatches: writeFailureBackend.specs.length,
        }).toMatchObject({
          result: { status: "failed", cause: "record_persist_failed" },
          lost: 0,
          s6: 1,
          s8: 1,
          dispatches: 0,
        });
      } finally {
        resetRoutePresetsCacheForTests();
        rmSync(routeDir, { recursive: true, force: true });
      }
    });
  });

  it("judge session service/network unavailable stays loud and never opens fresh", async () => {
    await runReal(async () => {
      const backend = new LifecycleBackend(
        [
          completedJudge(
            judgeContinue([
              sampleFinding("network-loud", "network.ts:1"),
            ]),
            OPEN_COURT_SESSION,
          ),
        ],
        undefined,
        {
          judgeResumeFirstThrow: new Error(
            "resumeSession failed: session service/network unavailable",
          ),
          judgeResumeThrowStep: "S6",
        },
      );

      const result = await runOrchestrator({ issueNumber: 11283, backend });
      expect(result.status).toBe("failed");
      expect(
        backend.ledgerWrites.some(
          (entry) => entry.event === "session_continuity_lost",
        ),
      ).toBe(false);
      expect(
        backend.specs.some(
          (spec) => spec.id === "S6" && spec.session === "fresh",
        ),
      ).toBe(false);
    });
  });

  it("judge continue is transported to S5 without runner findings-store judgment", async () => {
    await runReal(async () => {
      const live = sampleFinding("live", "live.ts:1");
      const duplicateTerminal = {
        action: "refute" as const,
        identityKey: "same-refuted-row",
        reason: "not_established" as const,
        evidence: "same verdict repeated by the resident judge",
      };
      const backend = new LifecycleBackend([
        completedJudge(
          {
            ...judgeContinue([live]),
            findingDispositions: [
              duplicateTerminal,
              duplicateTerminal,
              {
                action: "live",
                identityKey: "live",
              },
            ],
          },
          OPEN_COURT_SESSION,
        ),
        completedJudge(judgeConverged(), OPEN_COURT_SESSION),
      ]);

      const result = await runOrchestrator({ issueNumber: 11282, backend });
      expect(result.status).toBe("completed");
      expect(backend.specs.some((spec) => spec.id === "S5")).toBe(true);
      const authoredJudgeRow = backend.ledgerWrites.find(
        (entry) =>
          entry.step === "S3" &&
          entry.output?.kind === "judge" &&
          entry.output.status === "continue",
      );
      expect(authoredJudgeRow?.findingDispositions).toBeUndefined();
      expect(
        authoredJudgeRow?.output?.kind === "judge"
          ? authoredJudgeRow.output.findingDispositions
          : undefined,
      ).toEqual([
        duplicateTerminal,
        duplicateTerminal,
        { action: "live", identityKey: "live" },
      ]);
    });
  });

  it("open-court escalate parks via decision gate — no court_opened / no S2", async () => {
    await runReal(async () => {
      const backend = new LifecycleBackend(undefined, {
        kind: "completed",
        output: judgeEscalate(
          "slice authority fork",
          "owner must choose between AC and ADR before construction",
        ),
        sessionId: OPEN_COURT_SESSION,
      });
      const result = await runOrchestrator({ issueNumber: 10816, backend });
      // Decision-gate park — not infra failure, not silent S2.
      expect(result.status).toBe("parked");
      expect(backend.specs.some((s) => s.id === "S2")).toBe(false);
      expect(result.stepLedger.some((e) => e.event === "court_opened")).toBe(
        false,
      );
      // S1 ledger carries the escalate output so resume/route see the bell.
      const s1 = result.stepLedger.find(
        (e) => e.step === "S1" && e.output?.kind === "judge",
      );
      expect(s1?.output).toMatchObject({
        kind: "judge",
        status: "escalate",
      });
      // #1080: creator identity for open-court resume gate (verify seat = normal route).
      expect(s1?.modelSlug).toBe("gpt-5.6-sol");
      const s1Disk = backend.ledgerWrites.find(
        (e) => e.step === "S1" && e.output?.kind === "judge",
      );
      expect(s1Disk?.modelSlug).toBe("gpt-5.6-sol");
    });
  });

  it("open-court escalate resume: same session + answer; success clears stale escalate", async () => {
    await runReal(async () => {
      const COURT = OPEN_COURT_SESSION;
      const priorLedger: PersistentLedgerEntry[] = [
        {
          step: "S0",
          sessionId: "run-uuid",
          prompt_hash: "h0",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:00.000Z",
        },
        {
          step: "S1",
          sessionId: COURT,
          // Matching verify seat (normal route) — identity gate admits resume.
          modelSlug: "gpt-5.6-sol",
          output: judgeEscalate(
            "slice authority fork",
            "owner must choose between AC and ADR before construction",
          ),
          prompt_hash: "h1",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:01.000Z",
        },
        {
          step: "S8",
          sessionId: "run-uuid",
          prompt_hash: "h8",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:02.000Z",
          handoffStatus: "parked",
          escalationKind: "decision",
        },
        {
          step: "S1",
          event: "escalation_answered",
          forStep: "S1",
          answer: "proceed under ADR 0147 as sole authority",
          source: "human",
          sessionId: "run-uuid",
          prompt_hash: "ha",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:03.000Z",
        },
      ];
      // Resume re-open succeeds (converged ack) — must NOT re-park on stale escalate.
      const backend = new LifecycleBackend(
        [completedJudge(judgeConverged(), COURT)],
        {
          kind: "completed",
          output: judgeConverged(),
          sessionId: COURT,
        },
        {
          resumeState: {
            worktree: WORKTREE,
            stateDir: "/resident/worktrees/.ledger-1081-esc",
            ledger: priorLedger,
          },
        },
      );
      const result = await runOrchestrator({ issueNumber: 10817, backend });
      expect(result.status).toBe("completed");
      // Open court resumed the escalated session with the human answer.
      const openSpec = backend.specs.find((s) => isJudgeOpenCourtSpec(s));
      expect(openSpec).toBeDefined();
      expect(openSpec!.session).toBe("resume");
      const openCtx = backend.ctxs[backend.specs.indexOf(openSpec!)];
      expect(openCtx?.resumeSessionId).toBe(COURT);
      expect(openCtx?.escalationAnswer).toMatchObject({
        event: "escalation_answered",
        forStep: "S1",
        answer: "proceed under ADR 0147 as sole authority",
      });
      // Court opened; S2 ran — not stuck re-parking on the original escalate.
      expect(result.stepLedger.some((e) => e.event === "court_opened")).toBe(
        true,
      );
      expect(backend.specs.some((s) => s.id === "S2")).toBe(true);
    });
  });

  it("F3: open-court capacity relay cannot carry the resident session across provider/model", async () => {
    // The first openCourtDispatch attempt resumes Sol and hits capacity. The
    // live baton targets Sonnet, but that provider/model cannot satisfy the
    // existing resident-session obligation: stop loud before a foreign fresh
    // court can be dispatched.
    await runReal(async () => {
      const COURT = OPEN_COURT_SESSION;
      const priorLedger: PersistentLedgerEntry[] = [
        {
          step: "S0",
          sessionId: "run-uuid",
          prompt_hash: "h0",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:00.000Z",
        },
        {
          step: "S1",
          sessionId: COURT,
          // The current verify seat owns this resumable court. Capacity during
          // the actual resume dispatch is what forces the cross-provider baton.
          modelSlug: "gpt-5.6-sol",
          output: judgeEscalate(
            "slice authority fork",
            "owner must choose between AC and ADR before construction",
          ),
          prompt_hash: "h1",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:01.000Z",
        },
        {
          step: "S8",
          sessionId: "run-uuid",
          prompt_hash: "h8",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:02.000Z",
          handoffStatus: "parked",
          escalationKind: "decision",
        },
        {
          step: "S1",
          event: "escalation_answered",
          forStep: "S1",
          answer: "proceed under ADR 0147 as sole authority",
          source: "human",
          sessionId: "run-uuid",
          prompt_hash: "ha",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:03.000Z",
        },
      ];
      const backend = new LifecycleBackend(
        [completedJudge(judgeConverged(), COURT)],
        {
          kind: "completed",
          output: judgeConverged(),
          sessionId: COURT,
        },
        {
          openCourtFirstThrow: new CapacityRelayError(
            "Selected model is at capacity",
          ),
          issueBody: "Coder-Rec: sol@med → sonnet-5",
          resumeState: {
            worktree: WORKTREE,
            stateDir: "/resident/worktrees/.ledger-1081-esc-mismatch",
            ledger: priorLedger,
          },
        },
      );
      const result = await runOrchestrator({
        issueNumber: 10818,
        backend,
        relayPools: [
          {
            id: "codex-5h",
            status: "limited",
            parkThresholdMs: 1,
            models: ["sol@med", "gpt-5.6-sol"],
          },
          {
            id: "claude",
            status: "live",
            parkThresholdMs: 1,
            models: ["sonnet-5", "sonnet"],
          },
        ],
      });
      expect(result.status).toBe("failed");
      if (result.status === "failed") {
        expect(result.errorPackage?.reason).toMatch(
          /resident judge open-court resume refused/,
        );
      }
      expect(backend.ledgerWrites).toContainEqual(
        expect.objectContaining({
          event: "relay_baton_handoff",
          trigger: "capacity",
          fromModelId: "sol@med",
          toModelId: "sonnet-5",
          toPool: "claude",
          step: "S3",
          state_summary: "open-court verify seat at capacity; drift preserved",
        }),
      );
      const openCourtAttempts = backend.specs
        .map((spec, index) => ({ spec, ctx: backend.ctxs[index] }))
        .filter(({ spec }) => isJudgeOpenCourtSpec(spec));
      expect(openCourtAttempts).toHaveLength(1);
      expect(openCourtAttempts[0]).toMatchObject({
        spec: { model: "gpt-5.6-sol", session: "resume" },
        ctx: { resumeSessionId: COURT },
      });
      expect(
        openCourtAttempts.some(
          ({ spec, ctx }) =>
            spec.model === "sonnet" && ctx?.resumeSessionId === COURT,
        ),
      ).toBe(false);
    });
  });

  it("open-court without session id fails loud when stub is off (negative)", async () => {
    await runReal(async () => {
      const backend = new LifecycleBackend(undefined, {
        kind: "completed",
        output: judgeConverged(),
        // no sessionId
      });
      const result = await runOrchestrator({ issueNumber: 10811, backend });
      // Behavioral guards only (L6: no free-prose regex on error text).
      expect(result.status).toBe("failed");
      expect(result.errorPackage).toBeDefined();
      // Negative: must not reach S2 without a resident judge.
      expect(backend.specs.some((s) => s.id === "S2")).toBe(false);
    });
  });

  it("open-court worker failure fails loud when stub is off (negative)", async () => {
    await runReal(async () => {
      const backend = new LifecycleBackend(undefined, {
        kind: "failed",
        reason: "sandbox boom",
      });
      const result = await runOrchestrator({ issueNumber: 10812, backend });
      // Behavioral guards only (L6: no free-prose regex).
      expect(result.status).toBe("failed");
      expect(result.errorPackage).toBeDefined();
      expect(backend.specs.some((s) => s.id === "S2")).toBe(false);
    });
  });

  it("open-court dispatch throw fails loud — no S2 (L5 throw arm)", async () => {
    await runReal(async () => {
      const backend = new LifecycleBackend(undefined, undefined, {
        openCourtThrow: new Error("sandbox boom on open court"),
      });
      const result = await runOrchestrator({ issueNumber: 10814, backend });
      expect(result.status).toBe("failed");
      expect(result.errorPackage).toBeDefined();
      expect(backend.specs.some((s) => s.id === "S2")).toBe(false);
    });
  });

  it("crash-resume with court_opened does not re-open court; S3 resumes same id (L5)", async () => {
    await runReal(async () => {
      const COURT = OPEN_COURT_SESSION;
      const priorLedger: PersistentLedgerEntry[] = [
        {
          step: "S0",
          sessionId: "run-uuid",
          prompt_hash: "h0",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:00.000Z",
        },
        {
          step: "S1",
          event: "court_opened",
          sessionId: COURT,
          modelSlug: "gpt-5.6-sol",
          reason: "resident judge court opened at slice dispatch (#1081)",
          prompt_hash: "h-open",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:01.000Z",
        },
        {
          step: "S1",
          sessionId: "run-uuid",
          prompt_hash: "h1",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:02.000Z",
        },
        {
          step: "S2",
          sessionId: "sess-coder",
          modelSlug: "gpt-5.6-terra",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
          prompt_hash: "h2",
          branchHEAD: "deadbeef",
          ts: "2026-07-21T00:00:03.000Z",
        },
      ];
      const backend = new LifecycleBackend(
        [completedJudge(judgeConverged(), COURT)],
        undefined,
        {
          resumeState: {
            worktree: WORKTREE,
            stateDir: "/resident/worktrees/.ledger-1081",
            ledger: priorLedger,
          },
        },
      );
      const result = await runOrchestrator({ issueNumber: 10815, backend });
      expect(result.status).toBe("completed");
      // No second open-court birth on resume.
      expect(
        backend.specs.filter((s) => isJudgeOpenCourtSpec(s)),
      ).toHaveLength(0);
      const s3 = backend.specs.find((s) => s.id === "S3");
      expect(s3?.session).toBe("resume");
      const s3Ctx = backend.ctxs[backend.specs.indexOf(s3!)];
      expect(s3Ctx?.resumeSessionId).toBe(COURT);
    });
  });

  it("happy path with single converge still opens + dismisses court", async () => {
    await runReal(async () => {
      const backend = new LifecycleBackend([
        completedJudge(judgeConverged(), OPEN_COURT_SESSION),
      ]);
      const result = await runOrchestrator({ issueNumber: 10813, backend });
      expect(result.status).toBe("completed");
      expect(result.stepLedger.some((e) => e.event === "court_opened")).toBe(
        true,
      );
      expect(result.stepLedger.some((e) => e.event === "court_dismissed")).toBe(
        true,
      );
      // S3 resumed; no S6 on first-round converge.
      const s3 = backend.specs.find((s) => s.id === "S3");
      expect(s3?.session).toBe("resume");
      expect(backend.specs.some((s) => s.id === "S6")).toBe(false);
    });
  });
});
