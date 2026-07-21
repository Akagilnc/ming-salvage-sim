/**
 * #1081 / ADR 0147 — resident judge lifecycle skeleton:
 * open court at slice dispatch → resume every judging round → dismiss on converge.
 *
 * Seams (Testing Decisions #1080 / PRD):
 * 1. Pure helpers — rebuild / require resume / open-court gate
 * 2. runOrchestrator + scripted Backend — birth / resume / dismiss / fail-loud
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  isJudgeOpenCourtSpec,
  JUDGE_OPEN_COURT_PROMPT_FILE,
  rebuildResidentJudgeFromLedger,
  requireOpenCourtSession,
  requireResidentJudgeResume,
  usesJudgeReceiptChannel,
} from "../../src/judgeStation.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import {
  completedJudge,
  judgeConverged,
  judgeContinue,
  OPEN_COURT_SESSION,
  openCourtWorkerResultIfMatch,
  sampleFinding,
} from "../helpers/judge-fixtures.js";

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

  constructor(
    private readonly judgeResults: ReadonlyArray<WorkerResult> = [
      completedJudge(judgeConverged(), OPEN_COURT_SESSION),
    ],
    private readonly openCourtResult?: WorkerResult,
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
  ): Promise<WorkerResult> {
    this.specs.push(spec);
    this.ctxs.push(ctx);

    if (isJudgeOpenCourtSpec(spec)) {
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
      const scripted = this.judgeResults[this.judgeRound];
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

  it("rebuild: empty ledger is absent; continuity_lost clears (negative)", () => {
    expect(rebuildResidentJudgeFromLedger([])).toEqual({ status: "absent" });
    expect(
      rebuildResidentJudgeFromLedger([
        {
          event: "court_opened",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        { event: "session_continuity_lost", sessionId: "j1" },
      ]),
    ).toEqual({ status: "absent" });
  });

  it("require resume: open→resume; absent/model-move/incapable→establish; dismissed fail", () => {
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
    // Provider not resume-capable = re-establish (do not hand a dead id).
    expect(
      requireResidentJudgeResume({
        lifecycle: {
          status: "open",
          sessionId: "j1",
          modelSlug: "gpt-5.4",
        },
        seatModel: "gpt-5.4",
        seatResumeCapable: false,
      }),
    ).toEqual({ kind: "establish" });
    // Dismissed never reopens.
    expect(
      requireResidentJudgeResume({
        lifecycle: { status: "dismissed" },
        seatModel: "gpt-5.4",
        seatResumeCapable: true,
      }).kind,
    ).toBe("fail");
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
    // Negative: no hanging open court after dismiss in durable writes.
    const lastLifecycle = [...backend.ledgerWrites]
      .reverse()
      .find(
        (e) => e.event === "court_opened" || e.event === "court_dismissed",
      );
    expect(lastLifecycle?.event).toBe("court_dismissed");
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
      expect(result.status).toBe("failed");
      expect(result.errorPackage?.reason ?? "").toMatch(/session id|open court/i);
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
      expect(result.status).toBe("failed");
      expect(result.errorPackage?.reason ?? "").toMatch(
        /open court|resident judge|failed/i,
      );
      expect(backend.specs.some((s) => s.id === "S2")).toBe(false);
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
