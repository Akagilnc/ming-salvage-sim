/**
 * #1083 / ADR 0147 — fixer beats always dumb-relay to the resident judge hub.
 *
 * AC:
 * 1. Fixer beats (plan or construction) → resident judge; no envelope fork
 * 2. Fresh reviewer is not the next step after a builder beat (hub receives first)
 * 3. Bounce-back = same worker resume, same worktree; uncommitted output kept
 * 4. (souls/prompts carry 双向抗辩 — not asserted by free-text regex here)
 * 5. Negative: old "fixer → fresh reviewer" direct edge is gone
 *
 * Seams (PRD #1080 Testing Decisions): family/slice route() + scripted Backend.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  isBuilderBeatStep,
  route,
  routeBuilderBeatToResidentJudge,
} from "../../src/route.js";
import { isJudgeSeat } from "../../src/judgeStation.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  WorkerLandingPayload,
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

const UNCOMMITTED_MARKER = ".orchestrator-1083-uncommitted-plan.md";
const UNCOMMITTED_BODY = "plan beat draft — must survive bounce (#1083)\n";

/** Plain tmpdir worktree — no real git (stays in fast pool; gitHead is soft-fail). */
function makeScratchWorktree(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "hub-1083-"));
  return {
    branch: "feat/orchestrator/issue-1083",
    base: "main",
    path,
  };
}

class HubBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: (WorkerLandingPayload | undefined)[] = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  private judgeRound = 0;
  private s5Round = 0;

  constructor(
    private readonly worktree: WorktreeHandle,
    private readonly opts?: {
      /** S5 outputs in order (default: one commit then done via judge converge). */
      readonly s5Outputs?: ReadonlyArray<StepOutput>;
      /** On each S5 dispatch, optionally mutate the worktree (e.g. leave uncommitted). */
      readonly onS5?: (round: number, worktree: WorktreeHandle) => void;
      /**
       * Judge scripts after open-court. Default: continue once (with sample
       * finding) then converge — drives S5→S6→S5→S6 converge.
       */
      readonly judgeResults?: ReadonlyArray<WorkerResult>;
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
    return this.worktree;
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

    const openCourt = openCourtWorkerResultIfMatch(spec, OPEN_COURT_SESSION);
    if (openCourt !== undefined) return openCourt;

    if (spec.kind === "coder") {
      if (spec.id === "S5") {
        const round = this.s5Round;
        this.s5Round += 1;
        this.opts?.onS5?.(round, this.worktree);
        const scripted = this.opts?.s5Outputs?.[round];
        if (scripted !== undefined) {
          return {
            kind: "completed",
            output: scripted,
            sessionId: "sess-coder-fix-1083",
          };
        }
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
          sessionId: "sess-coder-fix-1083",
        };
      }
      // S2 implement
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "sess-coder-1083",
      };
    }

    if (spec.kind === "verify" || spec.kind === "reviewer") {
      const scripts =
        this.opts?.judgeResults ??
        [
          completedJudge(
            judgeContinue([sampleFinding()]),
            OPEN_COURT_SESSION,
          ),
          completedJudge(judgeConverged(), OPEN_COURT_SESSION),
        ];
      const result = scripts[this.judgeRound] ??
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

    throw new Error(`unexpected worker kind ${spec.kind} at ${spec.id}`);
  }
}

async function runReal<T>(fn: () => Promise<T>): Promise<T> {
  vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
  try {
    return await fn();
  } finally {
    vi.unstubAllEnvs();
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.stubEnv("ORCHESTRATOR_REPO", "test/repo");
  }
}

describe("#1083 pure: builder beat → resident judge hub", () => {
  it("routeBuilderBeatToResidentJudge maps S2→S3 and S5→S6", () => {
    expect(routeBuilderBeatToResidentJudge("S2")).toEqual({
      kind: "next",
      step: "S3",
    });
    expect(routeBuilderBeatToResidentJudge("S5")).toEqual({
      kind: "next",
      step: "S6",
    });
  });

  it("isBuilderBeatStep admits only S2/S5", () => {
    expect(isBuilderBeatStep("S2")).toBe(true);
    expect(isBuilderBeatStep("S5")).toBe(true);
    expect(isBuilderBeatStep("S3")).toBe(false);
    expect(isBuilderBeatStep("S6")).toBe(false);
    expect(isBuilderBeatStep("S9")).toBe(false);
  });

  it("route(S5) is unconditional — plan / construction / refuse / empty all → S6", () => {
    const envelopes: Array<StepOutput | undefined> = [
      undefined,
      { kind: "coder", committed: true, commitsAdded: 1 },
      { kind: "coder", committed: false, commitsAdded: 0 },
      {
        kind: "coder",
        committed: true,
        commitsAdded: 1,
        refusedFindingIdentityKeys: ["correctness|src/x.ts:1|claim"],
      },
      // Malformed-looking cargo still routes by topology (runner no envelope fork).
      { kind: "coder", committed: false, commitsAdded: 0 } as StepOutput,
    ];
    for (const output of envelopes) {
      expect(route({ from: "S5", output })).toEqual({
        kind: "next",
        step: "S6",
      });
    }
  });

  it("route(S2) always → S3 (builder beat hub; no envelope fork)", () => {
    expect(
      route({
        from: "S2",
        output: { kind: "coder", committed: false, commitsAdded: 0 },
      }),
    ).toEqual({ kind: "next", step: "S3" });
    expect(
      route({
        from: "S2",
        output: { kind: "coder", committed: true, commitsAdded: 3 },
      }),
    ).toEqual({ kind: "next", step: "S3" });
  });

  it("negative: builder beat next step is always a judge seat, never a bare reviewer step id", () => {
    for (const from of ["S2", "S5"] as const) {
      const decision = routeBuilderBeatToResidentJudge(from);
      expect(decision.kind).toBe("next");
      if (decision.kind !== "next") continue;
      // Hub seats only.
      expect(isJudgeSeat({ step: decision.step })).toBe(true);
      // Old direct edge would have been a non-judge "fresh re-review" seat;
      // S5 must not jump to S7/S8/S0 or a non-judge id.
      expect(decision.step === "S7" || decision.step === "S8").toBe(false);
      expect(decision.step).not.toBe("S9");
    }
  });

  it("negative: prose/status shape on S5 does not open a second edge (only escalate parks)", () => {
    // Non-escalate completed/refused always S6.
    expect(
      route({
        from: "S5",
        output: {
          kind: "coder",
          committed: false,
          commitsAdded: 0,
        },
      }).kind,
    ).toBe("next");
    // Escalate is the global stop edge (decision gate) — not envelope plan/construction fork.
    expect(
      route({
        from: "S5",
        output: {
          kind: "coder",
          committed: false,
          commitsAdded: 0,
          escalate: { reason: "blocked", diagnosis: "needs owner" },
        },
      }),
    ).toEqual({ kind: "handoff", status: "parked" });
  });
});

describe("#1083 e2e: fixer hub + bounce resume", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    vi.stubEnv("ORCHESTRATOR_REPO", "test/repo");
  });

  it("S5 always followed by S6 verify (judge); never a non-judge fresh reviewer kind", async () => {
    await runReal(async () => {
      const worktree = makeScratchWorktree();
      const backend = new HubBackend(worktree, {
        s5Outputs: [
          { kind: "coder", committed: false, commitsAdded: 0 },
          { kind: "coder", committed: true, commitsAdded: 1 },
        ],
        judgeResults: [
          completedJudge(
            judgeContinue([sampleFinding()]),
            OPEN_COURT_SESSION,
          ),
          completedJudge(
            judgeContinue([sampleFinding()]),
            OPEN_COURT_SESSION,
          ),
          completedJudge(judgeConverged(), OPEN_COURT_SESSION),
        ],
      });
      const result = await runOrchestrator({ issueNumber: 1083, backend });
      expect(result.status).toBe("completed");

      const sequence = backend.specs.map((s) => `${s.id}:${s.kind}`);
      // After every S5:coder the next topology worker is S6:verify (judge hub).
      for (let i = 0; i < sequence.length; i += 1) {
        if (sequence[i] === "S5:coder") {
          expect(sequence[i + 1]).toBe("S6:verify");
        }
      }
      // Negative: no builder→reviewer kind direct edge in the dispatch log.
      for (let i = 0; i < sequence.length - 1; i += 1) {
        if (sequence[i] === "S5:coder") {
          expect(sequence[i + 1]).not.toMatch(/:reviewer$/);
        }
      }
    });
  });

  it("bounce continue resumes same fixer session + same worktree; uncommitted plan survives", async () => {
    await runReal(async () => {
      const worktree = makeScratchWorktree();
      const markerPath = join(worktree.path, UNCOMMITTED_MARKER);
      const backend = new HubBackend(worktree, {
        s5Outputs: [
          // Plan beat — no commit.
          { kind: "coder", committed: false, commitsAdded: 0 },
          // Construction after bounce.
          { kind: "coder", committed: true, commitsAdded: 1 },
        ],
        onS5: (round, wt) => {
          if (round === 0) {
            writeFileSync(join(wt.path, UNCOMMITTED_MARKER), UNCOMMITTED_BODY);
          }
          if (round === 1) {
            // AC3: uncommitted payload from plan beat still present on resume.
            expect(existsSync(join(wt.path, UNCOMMITTED_MARKER))).toBe(true);
            expect(readFileSync(join(wt.path, UNCOMMITTED_MARKER), "utf8")).toBe(
              UNCOMMITTED_BODY,
            );
          }
        },
        judgeResults: [
          // S3 first review: send to fixer.
          completedJudge(
            judgeContinue([sampleFinding()]),
            OPEN_COURT_SESSION,
          ),
          // S6 after plan beat: bounce (continue) — same open set.
          completedJudge(
            judgeContinue([sampleFinding()], {
              fixPacketBody:
                "bounce: re-draft seam; do not invent dual path",
            }),
            OPEN_COURT_SESSION,
          ),
          // S6 after construction: converge.
          completedJudge(judgeConverged(), OPEN_COURT_SESSION),
        ],
      });

      const result = await runOrchestrator({ issueNumber: 10831, backend });
      expect(result.status).toBe("completed");

      const s5Specs = backend.specs.filter((s) => s.id === "S5");
      expect(s5Specs.length).toBe(2);
      // Same worktree path both times (no new worktree on bounce).
      const s5Ctxs = backend.ctxs.filter(
        (_, i) => backend.specs[i]?.id === "S5",
      );
      expect(s5Ctxs[0]?.worktree?.path).toBe(worktree.path);
      expect(s5Ctxs[1]?.worktree?.path).toBe(worktree.path);
      // Second S5 resumes the retained coder-fix session when model matches.
      expect(s5Ctxs[1]?.resumeSessionId).toBe("sess-coder-fix-1083");

      // Judge hub: both S3 and S6 resume the open-court session.
      const judgeCtxs = backend.ctxs.filter((_, i) => {
        const id = backend.specs[i]?.id;
        return id === "S3" || id === "S6";
      });
      expect(judgeCtxs.length).toBeGreaterThanOrEqual(2);
      for (const ctx of judgeCtxs) {
        expect(ctx.resumeSessionId).toBe(OPEN_COURT_SESSION);
      }

      // Marker still on disk after full run (runner never wiped the worktree).
      expect(existsSync(markerPath)).toBe(true);
      expect(readFileSync(markerPath, "utf8")).toBe(UNCOMMITTED_BODY);
    });
  });

  it("negative: plan-only S5 (committed:false) still hits S6 judge before any converge path", async () => {
    await runReal(async () => {
      const worktree = makeScratchWorktree();
      const backend = new HubBackend(worktree, {
        s5Outputs: [{ kind: "coder", committed: false, commitsAdded: 0 }],
        judgeResults: [
          completedJudge(
            judgeContinue([sampleFinding()]),
            OPEN_COURT_SESSION,
          ),
          // After plan-only S5, hub still resumes judge (S6) then converge.
          completedJudge(judgeConverged(), OPEN_COURT_SESSION),
        ],
      });
      const result = await runOrchestrator({ issueNumber: 10832, backend });
      expect(result.status).toBe("completed");
      const sequence = backend.specs.map((s) => s.id);
      const s5At = sequence.indexOf("S5");
      expect(s5At).toBeGreaterThanOrEqual(0);
      expect(sequence[s5At + 1]).toBe("S6");
      // Negative: plan-only must not skip the hub and hand off (S7) directly.
      expect(sequence[s5At + 1]).not.toBe("S7");
    });
  });
});
