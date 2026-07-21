/**
 * #1084 / ADR 0147 — non-continue verdict routing + existing fuses on the
 * builder↔judge hub (S2/S5 → S3/S6).
 *
 * AC:
 * 1. Full withdraw (live findings → 0) = converged out; no construction commits.
 *    Partial withdraw = continue (prose documents); builder continues.
 * 2. 换棒 (advanceCoder) = new model, same worktree, uncommitted kept.
 *    上抛 (escalate) = existing decision-gate park.
 * 3. Existing fuses (no blind round cap + dispatchRetry) apply; no new thresholds.
 * 4. Negative: empty continue does not spin builder; prose wording alone never
 *    changes route (only the status enum does).
 *
 * Seams (PRD #1080 Testing Decisions): route() + scripted Backend via
 * runOrchestrator — zero parallel helper-test seam.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { findingIdentityKey } from "../../src/findings.js";
import { isJudgeOpenCourtSpec, isJudgeSeat } from "../../src/judgeStation.js";
import { route } from "../../src/route.js";
import { runOrchestrator } from "../../src/runner.js";
import type {
  Backend,
  DispatchContext,
  Finding,
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
  judgeEscalate,
  judgePlanContinue,
  OPEN_COURT_SESSION,
  openCourtWorkerResultIfMatch,
  sampleFinding,
} from "../helpers/judge-fixtures.js";

const UNCOMMITTED_MARKER = ".orchestrator-1084-uncommitted.md";
const UNCOMMITTED_BODY = "advanceCoder must keep this on disk (#1084)\n";

function makeScratchWorktree(): WorktreeHandle {
  const path = mkdtempSync(join(tmpdir(), "hub-1084-"));
  return {
    branch: "feat/orchestrator/issue-1084",
    base: "main",
    path,
  };
}

/** Default worktree handle when disk markers are not under test. */
const STATIC_WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-1084",
  base: "main",
  path: "/resident/worktrees/issue-1084",
};

class NonContinueBackend implements Backend {
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly landings: Array<WorkerLandingPayload | undefined> = [];
  readonly ledgerWrites: PersistentLedgerEntry[] = [];
  readonly coderModels: string[] = [];
  private judgeRound = 0;
  private s5Round = 0;
  private s2Round = 0;
  private s5FailBudget: number;

  constructor(
    private readonly worktree: WorktreeHandle,
    private readonly opts?: {
      readonly judgeResults?: ReadonlyArray<WorkerResult>;
      readonly s5Outputs?: ReadonlyArray<StepOutput>;
      readonly s2Outputs?: ReadonlyArray<StepOutput>;
      readonly onS5?: (round: number, worktree: WorktreeHandle) => void;
      /** First N S5 dispatches return process-level failed (dispatchRetry). */
      readonly s5ProcessFailures?: number;
      /** First N S6 dispatches return process-level failed. */
      readonly s6ProcessFailures?: number;
      readonly planPhase?: boolean;
    },
  ) {
    this.s5FailBudget = opts?.s5ProcessFailures ?? 0;
  }

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
      // Coder-Rec so advanceCoder has a multi-seat roster surface.
      body: "Coder-Rec: grok-4.5 → terra@med → sol@med\n",
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
      this.coderModels.push(spec.model);
      if (spec.id === "S5") {
        if (this.s5FailBudget > 0) {
          this.s5FailBudget -= 1;
          return {
            kind: "failed",
            reason: "simulated process crash (#1084 fuse)",
          };
        }
        const round = this.s5Round;
        this.s5Round += 1;
        this.opts?.onS5?.(round, this.worktree);
        const scripted = this.opts?.s5Outputs?.[round];
        if (scripted !== undefined) {
          return {
            kind: "completed",
            output: scripted,
            sessionId: "sess-coder-fix-1084",
          };
        }
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
          sessionId: "sess-coder-fix-1084",
        };
      }
      // S2 implement / plan
      const round = this.s2Round;
      this.s2Round += 1;
      const scripted = this.opts?.s2Outputs?.[round];
      if (scripted !== undefined) {
        return {
          kind: "completed",
          output: scripted,
          sessionId: "sess-coder-1084",
        };
      }
      if (this.opts?.planPhase === true) {
        if (round === 0) {
          return {
            kind: "completed",
            output: {
              kind: "coder",
              committed: false,
              commitsAdded: 0,
              beat: "plan",
              planBody: "拟刀口：route 单缝 + 既有 fuse，不造新阈值",
            },
            sessionId: "sess-coder-1084",
          };
        }
        return {
          kind: "completed",
          output: {
            kind: "coder",
            committed: true,
            commitsAdded: 1,
            beat: "construct",
          },
          sessionId: "sess-coder-1084",
        };
      }
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "sess-coder-1084",
      };
    }

    if (spec.kind === "verify" || spec.kind === "reviewer") {
      // S6 process-failure fuse (after open-court handled above).
      if (
        spec.id === "S6" &&
        (this.opts?.s6ProcessFailures ?? 0) > 0 &&
        this.judgeRound < (this.opts?.s6ProcessFailures ?? 0)
      ) {
        this.judgeRound += 1;
        return {
          kind: "failed",
          reason: "simulated judge process crash (#1084 fuse)",
        };
      }
      const scripts =
        this.opts?.judgeResults ??
        [completedJudge(judgeConverged(), OPEN_COURT_SESSION)];
      const script = scripts[this.judgeRound];
      this.judgeRound += 1;
      if (script !== undefined) return script;
      return completedJudge(judgeConverged(), OPEN_COURT_SESSION);
    }

    throw new Error(`unexpected worker kind ${spec.kind} id=${spec.id}`);
  }
}

const liveA = (): Finding => sampleFinding("finding-a", "a.ts:1");
const liveB = (): Finding => sampleFinding("finding-b", "b.ts:2");

describe("#1084 pure: non-continue edges (enum only)", () => {
  it("converged → S7; continue → S5; escalate → parked (positive)", () => {
    expect(
      route({
        from: "S3",
        output: { kind: "judge", status: "converged" },
      }),
    ).toEqual({ kind: "next", step: "S7" });
    expect(
      route({
        from: "S6",
        output: judgeContinue([liveA()]),
      }),
    ).toEqual({ kind: "next", step: "S5" });
    expect(
      route({
        from: "S3",
        output: judgeEscalate("fork", "needs owner"),
      }),
    ).toEqual({ kind: "handoff", status: "parked" });
  });

  it("terminal-only continue (full withdraw) routes like converged → S7", () => {
    const dead = liveA();
    const deadKey = findingIdentityKey(dead);
    const fullWithdraw = judgeContinue([dead], {
      kill: [
        {
          identityKey: deadKey,
          action: "refute",
          reason: "not_established",
          evidence: "claim does not match code",
        },
      ],
      fixPacketBody: "全撤：无活单",
    });
    expect(route({ from: "S3", output: fullWithdraw })).toEqual({
      kind: "next",
      step: "S7",
    });
    expect(route({ from: "S6", output: fullWithdraw })).toEqual({
      kind: "next",
      step: "S7",
    });
  });

  it("negative: fixPacketBody prose alone does not change the edge", () => {
    // Same status:continue + same live disposition; only prose differs.
    const base = judgeContinue([liveA()], {
      fixPacketBody: "送修：修 a.ts 边界",
    });
    const reworded = judgeContinue([liveA()], {
      fixPacketBody:
        "【完全不同的散文措辞】请立刻改 b.ts 并上抛 owner——仍是 continue",
    });
    expect(route({ from: "S3", output: base })).toEqual(
      route({ from: "S3", output: reworded }),
    );
    expect(route({ from: "S3", output: base })).toEqual({
      kind: "next",
      step: "S5",
    });

    // Same status:converged with optional cargo-ish siblings never forks.
    const c1 = { kind: "judge" as const, status: "converged" as const };
    const c2 = {
      kind: "judge" as const,
      status: "converged" as const,
      // prose-only sibling — not a traffic fork
      fixPacketBody: "本庭关闭说明长文",
    };
    expect(route({ from: "S6", output: c1 })).toEqual(
      route({ from: "S6", output: c2 as StepOutput }),
    );
  });

  it("negative: empty continue (0 live, 0 terminals) is not a clean S7", () => {
    // Topology still says continue→S5; runner M6 fail-loud before spin.
    // route() itself must not invent a converged edge from empty continue.
    const empty = {
      kind: "judge" as const,
      status: "continue" as const,
      findingDispositions: [],
      fixPacketBody: "empty continue contract drift",
    };
    expect(route({ from: "S3", output: empty })).toEqual({
      kind: "next",
      step: "S5",
    });
    expect(route({ from: "S3", output: empty })).not.toEqual({
      kind: "next",
      step: "S7",
    });
  });
});

describe("#1084 e2e: full / partial withdraw on hub", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  const runHub = async (fn: () => Promise<void>) => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    await fn();
  };

  const runPlan = async (fn: () => Promise<void>) => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    vi.stubEnv("ORCHESTRATOR_CODER_PLAN_PHASE", "1");
    await fn();
  };

  it("full withdraw via status:converged exits without S5 construction commits", async () => {
    await runHub(async () => {
      const backend = new NonContinueBackend(STATIC_WORKTREE, {
        // S2 construct lands; S3 full-withdraws with converged (no fixer).
        judgeResults: [
          completedJudge(judgeConverged(), OPEN_COURT_SESSION),
        ],
      });
      const result = await runOrchestrator({ issueNumber: 10841, backend });
      expect(result.status).toBe("completed");
      expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
      expect(result.stepLedger.some((e) => e.step === "S7")).toBe(true);
      // Court dismissed on product converge.
      expect(
        backend.ledgerWrites.some((e) => e.event === "court_dismissed"),
      ).toBe(true);
    });
  });

  it("full withdraw via terminal-only continue (all refute) → S7, no S5", async () => {
    await runHub(async () => {
      const dead = liveA();
      const deadKey = findingIdentityKey(dead);
      const backend = new NonContinueBackend(STATIC_WORKTREE, {
        judgeResults: [
          completedJudge(
            judgeContinue([dead], {
              kill: [
                {
                  identityKey: deadKey,
                  action: "refute",
                  reason: "not_established",
                  evidence: "full withdraw — claim false",
                },
              ],
              fixPacketBody: "全撤：live findings 归零",
            }),
            OPEN_COURT_SESSION,
          ),
        ],
      });
      const result = await runOrchestrator({ issueNumber: 10842, backend });
      expect(result.status).toBe("completed");
      expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
      expect(result.stepLedger.some((e) => e.step === "S7")).toBe(true);
      const s3 = result.stepLedger.find((e) => e.step === "S3");
      expect(
        s3?.findingDispositions?.some((d) => d.status === "refuted"),
      ).toBe(true);
    });
  });

  it("plan-phase full withdraw (converged after plan) → no construct commits", async () => {
    await runPlan(async () => {
      const backend = new NonContinueBackend(STATIC_WORKTREE, {
        planPhase: true,
        judgeResults: [
          // Plan pre-review: nothing remains to build (全撤).
          completedJudge(judgeConverged(), OPEN_COURT_SESSION),
        ],
      });
      const result = await runOrchestrator({ issueNumber: 10843, backend });
      expect(result.status).toBe("completed");
      // Only one S2 (plan); no construct beat, no S5.
      expect(backend.specs.filter((s) => s.id === "S2").length).toBe(1);
      expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
      const s2Out = result.stepLedger.find((e) => e.step === "S2")?.output;
      expect(s2Out?.kind === "coder" && s2Out.committed).toBe(false);
      expect(s2Out?.kind === "coder" && (s2Out.commitsAdded ?? 0)).toBe(0);
    });
  });

  it("partial withdraw: kill one + live one → continue builder with live only", async () => {
    await runHub(async () => {
      const a = liveA();
      const b = liveB();
      const aKey = findingIdentityKey(a);
      const backend = new NonContinueBackend(STATIC_WORKTREE, {
        judgeResults: [
          completedJudge(
            judgeContinue([a, b], {
              kill: [
                {
                  identityKey: aKey,
                  action: "refute",
                  reason: "over_defense",
                  evidence: "partial withdraw — a is over-defense",
                },
              ],
              fixPacketBody:
                "部分撤：毙 a；b 仍 live — builder 只修 b",
            }),
            OPEN_COURT_SESSION,
          ),
          completedJudge(judgeConverged(), OPEN_COURT_SESSION),
        ],
      });
      const result = await runOrchestrator({ issueNumber: 10844, backend });
      expect(result.status).toBe("completed");
      // Builder continues (S5 once).
      expect(backend.specs.filter((s) => s.id === "S5").length).toBe(1);
      const s5Idx = backend.specs.findIndex((s) => s.id === "S5");
      const s5Ctx = backend.ctxs[s5Idx];
      const s5Landing = backend.landings[s5Idx];
      // Live set for fixer is identity keys of remaining live only (b).
      // Traffic keys live on thin DispatchContext (信封宪法); landing is packet body.
      const liveKeys = s5Ctx?.blockingFindingIdentityKeys ?? [];
      expect(liveKeys).toContain(findingIdentityKey(b));
      expect(liveKeys).not.toContain(aKey);
      // Partial-withdraw prose transported as fix packet (not route input).
      expect(s5Landing?.fixPacketBody).toContain("部分撤");
    });
  });
});

describe("#1084 e2e: 换棒 + 上抛", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("advanceCoder switches S5 model on same worktree; uncommitted payload kept", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    vi.stubEnv("ORCHESTRATOR_CODER_MODEL", "");
    vi.stubEnv("ORCHESTRATOR_CODER_FIX_MODEL", "gpt-5.6-terra");
    const worktree = makeScratchWorktree();
    const markerPath = join(worktree.path, UNCOMMITTED_MARKER);
    const backend = new NonContinueBackend(worktree, {
      s5Outputs: [
        { kind: "coder", committed: false, commitsAdded: 0 },
        { kind: "coder", committed: true, commitsAdded: 1 },
      ],
      onS5: (round, wt) => {
        if (round === 0) {
          writeFileSync(join(wt.path, UNCOMMITTED_MARKER), UNCOMMITTED_BODY);
        }
        if (round === 1) {
          expect(existsSync(join(wt.path, UNCOMMITTED_MARKER))).toBe(true);
          expect(readFileSync(join(wt.path, UNCOMMITTED_MARKER), "utf8")).toBe(
            UNCOMMITTED_BODY,
          );
        }
      },
      judgeResults: [
        completedJudge(
          judgeContinue([liveA()], {
            advanceCoder: "sol@med",
            fixPacketBody: "换棒 sol@med；同工作区续修",
          }),
          OPEN_COURT_SESSION,
        ),
        // After first S5 plan beat, bounce once more then converge.
        completedJudge(
          judgeContinue([liveA()], {
            fixPacketBody: "续：完成施工",
          }),
          OPEN_COURT_SESSION,
        ),
        completedJudge(judgeConverged(), OPEN_COURT_SESSION),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 10845, backend });
    expect(result.status).toBe("completed");

    const s5Specs = backend.specs.filter((s) => s.id === "S5");
    expect(s5Specs.length).toBe(2);
    // New model on repair seat (sol), not the pre-advance terra freeze.
    expect(s5Specs[0]!.model).toBe("gpt-5.6-sol");
    // Same worktree both rounds.
    const s5Ctxs = backend.ctxs.filter((_, i) => backend.specs[i]?.id === "S5");
    expect(s5Ctxs[0]?.worktree?.path).toBe(worktree.path);
    expect(s5Ctxs[1]?.worktree?.path).toBe(worktree.path);
    // Fresh session after model switch (cannot resume across model change).
    expect(s5Ctxs[0]?.resumeSessionId).toBeUndefined();
    // Marker survives full run.
    expect(existsSync(markerPath)).toBe(true);
    expect(readFileSync(markerPath, "utf8")).toBe(UNCOMMITTED_BODY);
    // Advance bookkeeping landed.
    expect(
      result.stepLedger.some((e) => e.event === "coder_advance"),
    ).toBe(true);
  });

  it("escalate parks via existing decision gate (not completed, not S7)", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    const backend = new NonContinueBackend(STATIC_WORKTREE, {
      judgeResults: [
        completedJudge(
          judgeEscalate("true fork", "owner must choose scope"),
          OPEN_COURT_SESSION,
        ),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 10846, backend });
    expect(result.status).toBe("parked");
    expect(result.status).not.toBe("completed");
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
    expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
    expect(result.stepLedger.some((e) => e.step === "S7")).toBe(false);
    expect(
      result.stepLedger.find((e) => e.step === "S8")?.stopSummary?.reason,
    ).toBe("decision_gate_park");
  });
});

describe("#1084 e2e: fuses + empty continue negative", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("no blind round cap: many continue rounds still complete (judge decides)", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    // 6 continue rounds then converge — far past any historical N=3 style cap.
    const continues = Array.from({ length: 6 }, () =>
      completedJudge(
        judgeContinue([liveA()], {
          fixPacketBody: "still open — judge trajectory, not round count",
        }),
        OPEN_COURT_SESSION,
      ),
    );
    const backend = new NonContinueBackend(STATIC_WORKTREE, {
      judgeResults: [...continues, completedJudge(judgeConverged(), OPEN_COURT_SESSION)],
    });
    const result = await runOrchestrator({ issueNumber: 10847, backend });
    expect(result.status).toBe("completed");
    // 6 S5 builder beats — ring not killed by a mechanical round threshold.
    expect(backend.specs.filter((s) => s.id === "S5").length).toBe(6);
    // No S8 failed / parked from a round fuse.
    expect(result.status).not.toBe("failed");
    expect(result.status).not.toBe("parked");
  });

  it("dispatchRetry fuse: process failures on S5 exhaust MAX_DISPATCH_ATTEMPTS", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    const backend = new NonContinueBackend(STATIC_WORKTREE, {
      // Every S5 attempt fails at process level — exhaust mechanical retry.
      s5ProcessFailures: MAX_DISPATCH_ATTEMPTS + 2,
      judgeResults: [
        completedJudge(
          judgeContinue([liveA()], { fixPacketBody: "send to fixer" }),
          OPEN_COURT_SESSION,
        ),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 10848, backend });
    // Process-root exhaustion is a failed/parked terminal — not silent continue.
    expect(result.status).not.toBe("completed");
    // Exactly MAX_DISPATCH_ATTEMPTS process-level S5 tries (fuse bound).
    const s5Attempts = backend.specs.filter((s) => s.id === "S5").length;
    expect(s5Attempts).toBe(MAX_DISPATCH_ATTEMPTS);
  });

  it("negative: empty continue (0 live) does not spin S5 builder", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    // Post-construction empty continue = court contract drift (M6).
    const backend = new NonContinueBackend(STATIC_WORKTREE, {
      judgeResults: [
        completedJudge(
          {
            kind: "judge",
            status: "continue",
            findingDispositions: [],
            fixPacketBody: "empty continue must not empty-spin builder",
          },
          OPEN_COURT_SESSION,
        ),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 10849, backend });
    expect(result.status).toBe("failed");
    expect(result.errorPackage).toBeDefined();
    expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
  });

  it("negative: plan-phase empty continue is legal; post-phase empty is not", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    vi.stubEnv("ORCHESTRATOR_CODER_PLAN_PHASE", "1");
    const backend = new NonContinueBackend(STATIC_WORKTREE, {
      planPhase: true,
      judgeResults: [
        // Plan approve (0 live) — legal continue → same S2 construct.
        completedJudge(judgePlanContinue("准：可施工"), OPEN_COURT_SESSION),
        // Post-construct empty continue — fail loud, no S5 spin.
        completedJudge(
          {
            kind: "judge",
            status: "continue",
            findingDispositions: [],
            fixPacketBody: "post-construct empty continue",
          },
          OPEN_COURT_SESSION,
        ),
      ],
    });
    const result = await runOrchestrator({ issueNumber: 10850, backend });
    expect(result.status).toBe("failed");
    // Plan loop did resume S2 construct (2 S2s), but never spun S5.
    expect(backend.specs.filter((s) => s.id === "S2").length).toBe(2);
    expect(backend.specs.some((s) => s.id === "S5")).toBe(false);
  });

  it("negative: only enum flips route — prose reword on continue stays S5 edge", async () => {
    // Pure re-check at e2e surface: two runs that differ only in fixPacketBody
    // must land the same next builder step (S5), not diverge to S7/park.
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    for (const prose of [
      "修 a.ts",
      "【改写】立刻修 b.ts 并考虑上抛——仍是 continue 枚举",
    ]) {
      const backend = new NonContinueBackend(STATIC_WORKTREE, {
        judgeResults: [
          completedJudge(
            judgeContinue([liveA()], { fixPacketBody: prose }),
            OPEN_COURT_SESSION,
          ),
          completedJudge(judgeConverged(), OPEN_COURT_SESSION),
        ],
      });
      const result = await runOrchestrator({
        issueNumber: 10851,
        backend,
      });
      expect(result.status).toBe("completed");
      expect(backend.specs.some((s) => s.id === "S5")).toBe(true);
      expect(backend.specs.some((s) => isJudgeSeat(s))).toBe(true);
      // First judge seat after S2 is S3; never parks from prose alone.
      const ids = backend.specs.map((s) =>
        isJudgeOpenCourtSpec(s) ? "open-court" : s.id,
      );
      expect(ids).toContain("S5");
      expect(ids).toContain("S6");
    }
  });
});
