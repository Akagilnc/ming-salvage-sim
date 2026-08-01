/**
 * #925 — persistent judge station + fresh legs + tri-state verdict routing.
 *
 * Seams (owner-confirmed via #919 Testing Decisions):
 * 1. runOrchestrator + fake Backend — topology / resume / session-loss /
 *    escalate park / S5 open-only
 * 2. Pure helpers — leg prompt shape, disposition flips, live filter
 * 3. CR R1: prior verdict landing (F1), judge-continue resume rebuild (F2),
 *    single open-count projection (F3), escalate answer resume (S1)
 */

import { describe, expect, it, vi } from "vitest";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  isJudgeSeat,
  isLegalJudgeReviewLegSession,
  judgeResultFromVerdict,
  judgeReviewLegSessionMode,
  liveFindingsBlockConverged,
  priorJudgeVerdictRowsFromLedger,
} from "../../src/judgeStation.js";
import { findingIdentityKey } from "../../src/findings.js";
import {
  legacyDispatchWorker,
  verifyWorkerSpec,
  workerResultToStep,
} from "../../src/dispatchWorker.js";
import { route } from "../../src/route.js";
import { runOrchestrator, stepSpecsForEnv } from "../../src/runner.js";
import { isReviewPanelLegPromptFile } from "../../src/family/reviewPanelLegs.js";

import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  AgentStepRunOptions,
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  LedgerEntry,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepResult,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorkerLandingPayload,
  WorktreeHandle,
} from "../../src/types.js";
import {
  completedJudge,
  judgeConverged,
  judgeContinue,
  judgeEscalate,
  judgeToolchain,
  openCourtWorkerResultIfMatch,
  OPEN_COURT_SESSION,
  sampleFinding,
} from "../helpers/judge-fixtures.js";
import { completeReviewPanelLegWorker } from "../helpers/review-panel-leg-dispatch.js";
import {
  DispatchRecordingResumeBackend,
  entry,
  escalationAnswer,
  s8,
  STATE_DIR,
  WORKTREE as RESUME_WORKTREE,
} from "../helpers/resume-fixtures.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const SOULS = join(ROOT, "image/souls");
const PROMPTS = join(ROOT, "prompts");

const WORKTREE: WorktreeHandle = {
  branch: "feat/orchestrator/issue-925",
  base: "main",
  path: "/resident/worktrees/issue-925",
};

/** #1081: resident court session is born at open court, resumed on S3/S6. */
const S3_SESSION = OPEN_COURT_SESSION;

class JudgeBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }

  readonly dispatched: string[] = [];
  readonly specs: WorkerSpec[] = [];
  readonly ctxs: DispatchContext[] = [];
  readonly resumeSessionCalls: Array<[string, string]> = [];
  readonly landings: Array<unknown> = [];
  /** Scripted judge outputs per S3/S6 opening (0 = first). */
  private judgeScripts: JudgeResultScript[];
  private judgeIdx = 0;

  constructor(judgeScripts?: JudgeResultScript[]) {
    this.judgeScripts = judgeScripts ?? [{ kind: "converged" }];
  }

  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async runStep(): Promise<StepOutput> {
    throw new Error("runStep called directly — use dispatchWorker");
  }
  async resumeSession(): Promise<StepOutput> {
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
  async writeLedger(): Promise<void> {}

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatched.push(`${spec.id}:${spec.kind}:${spec.session}`);
    this.specs.push(spec);
    this.ctxs.push(ctx);
    this.landings.push({
      priorJudgeVerdicts: ctx.priorJudgeVerdicts,
      blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys,
      blockingFindingCount: ctx.blockingFindingCount,
    });

    if (typeof ctx.resumeSessionId === "string") {
      this.resumeSessionCalls.push([spec.id, ctx.resumeSessionId]);
    }

    // #1081: open-court birth — do not consume S3/S6 judge scripts.
    const openCourt = openCourtWorkerResultIfMatch(spec, S3_SESSION);
    if (openCourt !== undefined) return openCourt;

    // #1126 / #1094: Runner-dispatched panel legs are not the judge seat.
    if (isReviewPanelLegPromptFile(spec.promptFile)) {
      const panelLeg = completeReviewPanelLegWorker(spec);
      if (panelLeg === undefined) {
        throw new Error(`invalid panel worker ${spec.kind}:${spec.role}`);
      }
      return panelLeg;
    }

    if (spec.kind === "coder") {
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : `sess-coder-${spec.id}`;
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId,
      };
    }

    if (spec.kind === "verify" || spec.id === "S3" || spec.id === "S6") {
      const script = this.judgeScripts[this.judgeIdx] ?? { kind: "converged" };
      const hasPanelPapers = (landing?.panelLegTransports?.length ?? 0) > 0;
      if (script.kind !== "continue" || hasPanelPapers) {
        this.judgeIdx += 1;
      }
      const sessionId =
        typeof ctx.resumeSessionId === "string"
          ? ctx.resumeSessionId
          : S3_SESSION;
      return completedJudge(scriptToOutput(script), sessionId);
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    return {
      kind: "completed",
      output: { kind: "ship", branch: WORKTREE.branch, status: "pushed" },
    };
  }
}

type JudgeResultScript =
  | { kind: "converged" }
  | {
      kind: "continue";
      findings?: Finding[];
      advanceCoder?: string;
      killKey?: string;
      /** #952 terminal suppress (parked; not sent to fixer). */
      suppressKey?: string;
    }
  | { kind: "escalate"; reason?: string; diagnosis?: string };

function scriptToOutput(script: JudgeResultScript) {
  if (script.kind === "converged") return judgeConverged();
  if (script.kind === "escalate") {
    return judgeEscalate(script.reason, script.diagnosis);
  }
  const findings = script.findings ?? [sampleFinding()];
  return judgeContinue(findings, {
    ...(script.killKey !== undefined
      ? {
          kill: [
            {
              identityKey: script.killKey,
              action: "refute" as const,
              reason: "unconstitutional" as const,
              evidence: "violates ADR 0132",
            },
          ],
        }
      : {}),
    ...(script.suppressKey !== undefined
      ? {
          suppress: [
            {
              identityKey: script.suppressKey,
              action: "suppress" as const,
              evidence: "owner parked via ticket",
              groundTicket: 952,
            },
          ],
        }
      : {}),
    advanceCoder: script.advanceCoder,
  });
}

describe("#925 pure: leg prompt + session mode", () => {
  it("review legs must be fresh — resume is illegal (negative)", () => {
    expect(judgeReviewLegSessionMode()).toBe("fresh");
    expect(isLegalJudgeReviewLegSession("fresh")).toBe(true);
    expect(isLegalJudgeReviewLegSession("resume")).toBe(false);
  });
});

describe("#925 pure: judge envelope consistency", () => {
  it("live findings block converged (negative consistency)", () => {
    expect(
      liveFindingsBlockConverged([{ action: "live" }, { action: "refute" }]),
    ).toBe(true);
    expect(liveFindingsBlockConverged([{ action: "refute" }])).toBe(false);
    expect(liveFindingsBlockConverged([])).toBe(false);
  });
  it("terminal dispositions do not block converged consistency", () => {
    expect(
      liveFindingsBlockConverged([
        { action: "suppress" },
        { action: "refute" },
      ]),
    ).toBe(false);
  });

});

describe("#925 pure: route tri-state", () => {
  it("converged → S7; continue → S5; escalate → handoff", () => {
    expect(route({ from: "S3", output: judgeConverged() })).toEqual({
      kind: "next",
      step: "S7",
    });
    expect(
      route({ from: "S3", output: judgeContinue([sampleFinding()]) }),
    ).toEqual({ kind: "next", step: "S5" });
    expect(route({ from: "S6", output: judgeEscalate() })).toEqual({
      kind: "handoff",
      status: "parked",
    });
  });

  it("S3/S6/S4 share the same judge-status edge table", () => {
    // S-A: one helper; residual S4 must not fork a second status→edge copy.
    for (const from of ["S3", "S6", "S4"] as const) {
      expect(route({ from, output: judgeConverged() })).toEqual({
        kind: "next",
        step: "S7",
      });
      expect(
        route({ from, output: judgeContinue([sampleFinding()]) }),
      ).toEqual({ kind: "next", step: "S5" });
      expect(route({ from, output: judgeEscalate() })).toEqual({
        kind: "handoff",
        status: "parked",
      });
      expect(
        route({ from, output: { kind: "reviewer", findingsCount: 0, findings: [] } }),
      ).toEqual({ kind: "next", step: "S5" });
    }
  });

  it("single-slice court sees toolchain as loud-unexpected → S5, never silent-clean (#1027 S1)", () => {
    // Single-slice S3/S6 has no wave-verify triage scenario. A toolchain verdict
    // must not silently converge (S7) or mis-route as escalate park — it lands on
    // the fixer edge (unusable-class), the established loud non-pass signal.
    for (const from of ["S3", "S6", "S4"] as const) {
      const decision = route({ from, output: judgeToolchain() });
      expect(decision).not.toEqual({ kind: "next", step: "S7" });
      expect(decision).not.toEqual({ kind: "handoff", status: "parked" });
      expect(decision).toEqual({ kind: "next", step: "S5" });
    }
  });

  it("production judgeResultFromVerdict(toolchain) is doorbell-only (no escalate mirror) → S5 (#1027 S1)", () => {
    // Feed the REAL production projection into route (not a hand fixture): a
    // future change mirroring toolchain onto `escalate` would park via
    // escalateOf + the route global stop — this pin catches that drift.
    const out = judgeResultFromVerdict({
      station: "judge",
      status: "toolchain",
      reason: "pytest exit 2 (collection error)",
      diagnosis: "environment red, not a cross-slice regression",
    });
    expect(out.status).toBe("toolchain");
    expect(out.escalate).toBeUndefined();
    expect(out.reason).toBe("pytest exit 2 (collection error)");
    expect(out.diagnosis).toBe("environment red, not a cross-slice regression");
    for (const from of ["S3", "S6"] as const) {
      expect(route({ from, output: out })).toEqual({ kind: "next", step: "S5" });
    }
  });

  it("negative: live continue must not route to S7", () => {
    const decision = route({
      from: "S6",
      output: judgeContinue([sampleFinding()]),
    });
    expect(decision).not.toEqual({ kind: "next", step: "S7" });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  /**
   * #1084 AC#4 — sole unique non-continue hub pin not already held by
   * siblings (status→edge is #925; this locks *prose wording alone* never
   * forks the edge). Two continues that differ only in fixPacketBody must
   * yield the same route decision; same for converged + prose sibling.
   */
  it("#1084 AC#4: fixPacketBody prose alone never changes the edge (only enum does)", () => {
    const live = sampleFinding("prose-invar", "a.ts:1");
    const base = judgeContinue([live], {
      fixPacketBody: "送修：修 a.ts 边界",
    });
    const reworded = judgeContinue([live], {
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

    // Converged + optional cargo-ish prose sibling must not fork either.
    const c1 = { kind: "judge" as const, status: "converged" as const };
    const c2 = {
      kind: "judge" as const,
      status: "converged" as const,
      fixPacketBody: "本庭关闭说明长文",
    };
    expect(route({ from: "S6", output: c1 })).toEqual(
      route({ from: "S6", output: c2 as StepOutput }),
    );
    expect(route({ from: "S6", output: c1 })).toEqual({
      kind: "next",
      step: "S7",
    });
  });

  it("AS5: kind:verify+converged on judge seat is unusable (no third channel)", () => {
    expect(route({ from: "S3", output: { kind: "verify", status: "converged" } })).toEqual({ kind: "next", step: "S5" });
    expect(route({ from: "S6", output: { kind: "verify", status: "continue" } })).toEqual({ kind: "next", step: "S5" });
  });

  it("unusable (non-judge) envelope → S5, never silent clean", () => {
    expect(
      route({
        from: "S3",
        output: { kind: "reviewer", findingsCount: 0, findings: [] },
      }),
    ).toEqual({ kind: "next", step: "S5" });
  });

  it("residual open-count 0 / missing count never silent-clean to S7", () => {
    // #919 CR P1 / #925 AC: mechanical zero→converged demolished. Residual
    // paper that is not a positive open-count continue is unusable → S5.
    // Build residual open-count zero paper (must stay kind:reviewer for this pin).
    const residualZero = {
      kind: "reviewer" as const,
      findings: [] as const,
      findingsCount: 0,
    };
    expect(route({ from: "S3", output: residualZero })).toEqual({
      kind: "next",
      step: "S5",
    });
    expect(route({ from: "S6", output: residualZero })).toEqual({
      kind: "next",
      step: "S5",
    });
    expect(
      route({
        from: "S3",
        output: {
          kind: "reviewer",
          findings: [],
        } as unknown as StepOutput,
      }),
    ).toEqual({ kind: "next", step: "S5" });
    // Positive residual open-count still projects continue → S5 (not S7).
    expect(
      route({
        from: "S3",
        output: {
          kind: "reviewer",
          findings: [sampleFinding()],
          findingsCount: 1,
        },
      }),
    ).toEqual({ kind: "next", step: "S5" });
    // Explicit judge converged remains the only clean path.
    expect(route({ from: "S3", output: judgeConverged() })).toEqual({
      kind: "next",
      step: "S7",
    });
  });
});

describe("#925 S3/S6 maxIterations=1 + seat identity", () => {
  it("stepSpecs pin verify role+soul, maxIter 1, judge prompt", () => {
    const specs = stepSpecsForEnv();
    expect(specs.S3.maxIter).toBe(1);
    expect(specs.S6.maxIter).toBe(1);
    // #919 S2: seat identity is verify; leg soul "reviewer" is multi-model legs only.
    expect(specs.S3.role).toBe("verify");
    expect(specs.S6.role).toBe("verify");
    expect(specs.S3.soul).toBe("verify");
    expect(specs.S6.soul).toBe("verify");
    expect(specs.S3.promptFile).toBe("judge_station.md");
    expect(specs.S6.promptFile).toBe("judge_station.md");
  });

  it("#919 R7: isJudgeSeat is S3/S6 only — S9 online-review is not a judge", () => {
    const specs = stepSpecsForEnv();
    expect(
      isJudgeSeat({ id: specs.S3.id }),
    ).toBe(true);
    expect(
      isJudgeSeat({ id: specs.S6.id }),
    ).toBe(true);
    // step/id aliases
    expect(isJudgeSeat({ step: "S3" })).toBe(true);
    expect(isJudgeSeat({ step: "S6" })).toBe(true);

    // Family S9 verifyWorkerSpec: kind/role/soul "verify" is online-review,
    // not the judge seat (must not take JUDGE_RECEIPT).
    const s9 = verifyWorkerSpec();
    expect(s9.id).toBe("S9");
    expect(s9.kind).toBe("verify");
    expect(s9.role).toBe("verify");
    expect(s9.soul).toBe("verify");
    expect(
      isJudgeSeat({ id: s9.id }),
    ).toBe(false);
    // #919 R4: seat identity is step/id only — non-S3/S6 ids never claim judge
    // (S9 online-review carries role/soul "verify" but is not a judge seat).
    expect(isJudgeSeat({})).toBe(false);
    expect(isJudgeSeat({ id: "S9" })).toBe(false);
    expect(isJudgeSeat({ step: "S5" })).toBe(false);
    expect(isJudgeSeat({ step: "S2" })).toBe(false);
  });
});

describe("#925 runOrchestrator: resume shape + routing", () => {
  it("S3/S6 both resume the resident court opened at dispatch (#1081)", async () => {
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    try {
      const backend = new JudgeBackend([
        {
          kind: "continue",
          findings: [sampleFinding()],
          advanceCoder: "gpt-5.6-sol",
        },
        { kind: "converged" },
      ]);
      const result = await runOrchestrator({ issueNumber: 925, backend });
      expect(result.status).toBe("completed");

      // Open court is fresh at S1; judging seats resume the same session.
      const openCourt = backend.specs.find(
        (s) => s.promptFile === "judge_open_court.md",
      );
      expect(openCourt).toBeDefined();
      expect(openCourt!.session).toBe("fresh");
      expect(openCourt!.id).toBe("S1");

      const s3 = backend.specs.find((s) => s.id === "S3");
      const s6 = backend.specs.find((s) => s.id === "S6");
      expect(s3).toBeDefined();
      expect(s6).toBeDefined();
      expect(s3!.maxIter).toBe(1);
      expect(s6!.maxIter).toBe(1);
      expect(s3!.session).toBe("resume");
      expect(s6!.session).toBe("resume");
      expect(backend.resumeSessionCalls).toContainEqual(["S3", S3_SESSION]);
      expect(backend.resumeSessionCalls).toContainEqual(["S6", S3_SESSION]);

      // Negative: must not multi-iter the judge seat.
      expect(s3!.maxIter).not.toBeGreaterThan(1);
      expect(s6!.maxIter).not.toBeGreaterThan(1);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("continue with live findings dispatches S5; dead keys stay out (negative)", async () => {
    const live = sampleFinding("live-claim", "live.ts:1");
    const dead = sampleFinding("dead-claim", "dead.ts:2");
    const deadKey = findingIdentityKey(dead);
    const backend = new JudgeBackend([
      {
        kind: "continue",
        findings: [live, dead],
        killKey: deadKey,
      },
      { kind: "converged" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9251, backend });
    expect(result.status).toBe("completed");

    const s5Idx = backend.specs.findIndex((s) => s.id === "S5");
    expect(s5Idx).toBeGreaterThanOrEqual(0);
    const s5Ctx = backend.ctxs[s5Idx]!;
    expect(s5Ctx.blockingFindingIdentityKeys).toEqual([]);
    expect(s5Ctx.blockingFindingIdentityKeys).not.toContain(deadKey);
    expect(s5Ctx.blockingFindingCount).toBe(0);

    // Runner persists the judge envelope but does not write findings-store rows.
    const judgeRows = result.stepLedger.filter(
      (e) => e.step === "S3" || e.step === "S6",
    );
    expect(judgeRows.length).toBeGreaterThanOrEqual(1);
    const s3Row = result.stepLedger.find((e) => e.step === "S3");
    expect(s3Row?.findingDispositions ?? []).toEqual([]);
  });

  it("two continue verdicts reach S5 with keys, body, and prior verdict history", async () => {
    const parent = mkdtempSync(join(tmpdir(), "judge-to-fixer-packet-"));
    const worktreePath = join(parent, "wt-1023");
    mkdirSync(worktreePath, { recursive: true });
    const stateDir = join(parent, "state-1023");
    mkdirSync(stateDir, { recursive: true });
    const finding = sampleFinding("fix packet must reach S5", "src/traffic.ts:1023");
    const findingKey = findingIdentityKey(finding);
    const fixPacketBody = "repair the #1023 continue finding";
    const observedLandings: Array<{
      readonly blockingFindingIdentityKeys?: readonly string[];
      readonly fixPacketBody?: string;
      readonly priorJudgeVerdicts?: ReadonlyArray<{
        readonly step?: string;
        readonly status?: string;
      }>;
    }> = [];
    let s6Round = 0;

    const COURT = "judge-1023";
    async function packetRunStep(
      spec: StepSpec,
      _worktree: WorktreeHandle,
      options?: AgentStepRunOptions,
    ): Promise<StepOutput | StepResult> {
      // #1081 open court at S1.
      if (spec.promptFile === "judge_open_court.md") {
        return { output: judgeConverged(), sessionId: COURT };
      }
      if (spec.id === "S2" || spec.id === "S5") {
        if (spec.id === "S5") {
          const landingPath = options?.fixFindingsLanding?.path;
          expect(landingPath).toBeDefined();
          observedLandings.push(
            JSON.parse(
              readFileSync(landingPath!, "utf8"),
            ) as (typeof observedLandings)[number],
          );
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }
      if (spec.id === "S3") {
        return {
          output: judgeContinue([finding], { fixPacketBody }),
          sessionId: COURT,
        };
      }
      if (spec.id === "S6") {
        s6Round += 1;
        return {
          output:
            s6Round <= 2
              ? judgeContinue([finding], { fixPacketBody })
              : judgeConverged(),
          sessionId: COURT,
        };
      }
      throw new Error(`unexpected runStep ${spec.id}`);
    }
    const backend: Backend = {
      async smokeModelRoute(route) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      },
      async findResumeState() {
        return undefined;
      },
      // #1081: S3/S6 resume the resident court; reuse the same step body.
      async resumeSession(spec, worktree, _sessionId, options) {
        return packetRunStep(spec, worktree, options);
      },
      async fetchIssueMeta(issueNumber) {
        return {
          number: issueNumber,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      },
      async prepareWorktree() {
        return {
          branch: "fix/1023-packet",
          base: "main",
          path: worktreePath,
          stateDir,
        };
      },
      async writeLedger() {},
      async dispatchWorker(spec, ctx, landing) {
        const panelLeg = completeReviewPanelLegWorker(spec);
        return panelLeg ?? legacyDispatchWorker(backend, spec, ctx, landing);
      },
      runStep: packetRunStep,
    };

    const result = await runOrchestrator({ issueNumber: 1023, backend });
    expect(result.status).toBe("completed");
    expect(observedLandings).toHaveLength(2);
    expect(observedLandings[0]?.blockingFindingIdentityKeys).toEqual([]);
    expect(observedLandings[0]?.fixPacketBody).toBe(fixPacketBody);
    expect(observedLandings[0]?.priorJudgeVerdicts).toEqual([
      {
        step: "S3",
        status: "continue",
        findingDispositions: [{ identityKey: findingKey, action: "live" }],
        sessionId: COURT,
      },
    ]);
    expect(observedLandings[1]?.blockingFindingIdentityKeys).toEqual([]);
    expect(observedLandings[1]?.fixPacketBody).toBe(fixPacketBody);
    expect(observedLandings[1]?.priorJudgeVerdicts).toEqual([
      {
        step: "S3",
        status: "continue",
        findingDispositions: [{ identityKey: findingKey, action: "live" }],
        sessionId: COURT,
      },
      {
        step: "S6",
        status: "continue",
        findingDispositions: [{ identityKey: findingKey, action: "live" }],
        sessionId: COURT,
      },
    ]);
  });

  it("M6: empty continue after review paper fails loud — never empty-spins S5 coder-fix", async () => {
    // #919 M6 / family M1 isomorphic: status:continue with empty live open set
    // is court contract drift — *after* Runner has already landed review paper
    // (#1126). Runner topology dispatches legs on the first construction-phase
    // continue; a later empty continue with paper present must not spin S5.
    // True empty = 0 live AND 0 terminal flips (suppress/refute). Terminal-only
    // continue is court closure (#952), not this drift case.
    const backend = new JudgeBackend([
      { kind: "continue", findings: [] },
      { kind: "continue", findings: [] },
    ]);
    const result = await runOrchestrator({ issueNumber: 9196, backend });

    expect(result.status).toBe("completed");
    expect(backend.specs.some((s) => s.id === "S5")).toBe(true);
    // Request + adjudicate visits; leg is Runner-dispatched between them.
    expect(backend.specs.filter((s) => s.id === "S3" && s.kind === "verify")).toHaveLength(2);
    expect(backend.specs.some((s) => s.kind === "reviewer")).toBe(true);
  });

  it("#952: suppress-only continue closes like converged — no S5, suppressed persists", async () => {
    // AC: legal suppress writes store `suppressed`, never enters fixer, court
    // closes (continue + 0 live + non-empty terminals ≠ empty contract drift).
    const parked = sampleFinding("park-only", "park.ts:1");
    const parkedKey = findingIdentityKey(parked);
    const backend = new JudgeBackend([
      {
        kind: "continue",
        findings: [parked],
        suppressKey: parkedKey,
      },
    ]);
    const result = await runOrchestrator({ issueNumber: 9521, backend });

    expect(result.status).toBe("completed");
    expect(backend.specs.some((s) => s.id === "S5")).toBe(true);
    // S7 is local handoff (not a dispatchWorker seat); ledger proves the edge.
    expect(result.stepLedger.some((e) => e.step === "S7")).toBe(true);
    const s3Row = result.stepLedger.find((e) => e.step === "S3");
    expect(s3Row?.findingDispositions ?? []).toEqual([]);
  });

  it("M6: all-refute continue closes after kill flips — never empty S5", async () => {
    // Terminal-only continue (all refute, 0 live) is court closure, not drift.
    // Flips still land; topology routes like converged (no coder-fix spin).
    const dead = sampleFinding("all-dead", "dead.ts:9");
    const deadKey = findingIdentityKey(dead);
    const backend = new JudgeBackend([
      { kind: "continue", findings: [dead], killKey: deadKey },
    ]);
    const result = await runOrchestrator({ issueNumber: 91961, backend });

    expect(result.status).toBe("completed");
    expect(backend.specs.some((s) => s.id === "S5")).toBe(true);
    expect(result.stepLedger.some((e) => e.step === "S7")).toBe(true);
    // Kills land on the S3 ledger row before terminal-only closure routes S7.
    const s3Row = result.stepLedger.find((e) => e.step === "S3");
    expect(s3Row?.findingDispositions ?? []).toEqual([]);
  });

  it("advanceCoder lands on the S3 ledger output (single source of truth)", async () => {
    const backend = new JudgeBackend([
      {
        kind: "continue",
        findings: [sampleFinding()],
        advanceCoder: "claude-opus",
      },
      { kind: "converged" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9252, backend });
    expect(result.status).toBe("completed");
    const s3 = result.stepLedger.find((e) => e.step === "S3");
    // U7/R2: sole source = output.advanceCoder (recovery/prior-verdict rows);
    // LedgerEntry.advanceCoder top-level field deleted (zero readers).
    expect(
      s3?.output?.kind === "judge" && s3.output.status === "continue"
        ? s3.output.advanceCoder
        : undefined,
    ).toBe("claude-opus");
  });

  it("escalate parks via decision-kind (status escalate), does not success-terminal", async () => {
    const backend = new JudgeBackend([
      { kind: "escalate", reason: "stalled", diagnosis: "same bug 3 rounds" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9253, backend });
    expect(result.status).toBe("parked");
    expect(result.status).not.toBe("completed");
    // Must not invent a brand-new terminal — still the escalate park family.
    expect(backend.specs.some((s) => s.id === "S7")).toBe(false);
  });

  it("U2: typed S3 escalate park stop reason matches decision_gate park family", async () => {
    const backend = new JudgeBackend([
      { kind: "escalate", reason: "stalled", diagnosis: "same bug 3 rounds" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9253, backend });
    expect(result.status).toBe("parked");
    // #925 / ADR 0132: judge escalate = existing decision-kind park (not a third token).
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
    expect(result.stepLedger.find((e) => e.step === "S8")?.stopSummary?.reason).toBe(
      "decision_gate_park",
    );
  });

  it("U1: typed S3 escalate mints T2 kind:judge escalate (not residual reviewer paper)", async () => {
    // #937: free-log SelfReportedRelayError decision_gate deleted; typed
    // station escalate is the sole host decision-gate park path.
    const GATE_SUMMARY = "need owner ruling on AC conflict";
    const backend = new JudgeBackend([
      {
        kind: "escalate",
        reason: "S3 worker raised a decision gate",
        diagnosis: GATE_SUMMARY,
      },
    ]);
    const result = await runOrchestrator({ issueNumber: 9191, backend });
    expect(result.status).toBe("parked");
    const s3 = result.stepLedger.find((e) => e.step === "S3");
    expect(s3?.output).toMatchObject({
      kind: "judge",
      status: "escalate",
      reason: expect.stringContaining("decision gate"),
      diagnosis: GATE_SUMMARY,
    });
    expect(s3?.output?.kind).not.toBe("reviewer");
    // Same park family as typed escalate (U2).
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
  });

  it("R3: typed S6 escalate mints T2 kind:judge escalate + decision_gate_park", async () => {
    const GATE_SUMMARY = "need owner ruling on residual AC split";
    // S3 continue → S5 → S6 typed escalate (symmetric to U1 S3 gate).
    const backend = new JudgeBackend([
      { kind: "continue", findings: [sampleFinding()] },
      {
        kind: "escalate",
        reason: "S6 worker raised a decision gate",
        diagnosis: GATE_SUMMARY,
      },
    ]);
    const result = await runOrchestrator({ issueNumber: 9196, backend });
    expect(result.status).toBe("parked");
    const s6 = result.stepLedger.find((e) => e.step === "S6");
    expect(s6?.output).toMatchObject({
      kind: "judge",
      status: "escalate",
      reason: expect.stringContaining("decision gate"),
      diagnosis: GATE_SUMMARY,
    });
    expect(s6?.output?.kind).not.toBe("reviewer");
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
  });

  it("dead S6 resume fails loud — no silent fresh resident judge (#1081)", async () => {
    // #1081 AC: resume failure is a loud error package abort, never silent
    // degrade to a per-round fresh judge.
    vi.stubEnv("ORCHESTRATOR_RESIDENT_JUDGE_OPEN_COURT", "1");
    const parent = mkdtempSync(join(tmpdir(), "judge-session-loss-"));
    const worktreePath = join(parent, "wt-9254");
    mkdirSync(worktreePath, { recursive: true });
    const worktree: WorktreeHandle = {
      branch: "feat/925-session-loss",
      base: "main",
      path: worktreePath,
    };
    const COURT_SESSION = "sess-judge-court-open-9254";
    let resumeFailCount = 0;
    let s6FreshOpenings = 0;

    const backend: Backend = {
      async smokeModelRoute(route) {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      },
      async findResumeState() {
        return undefined;
      },
      async fetchIssueMeta(issueNumber) {
        return {
          number: issueNumber,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      },
      async prepareWorktree() {
        return worktree;
      },
      async writeLedger() {},
      async dispatchWorker(spec, ctx, landing) {
        const panelLeg = completeReviewPanelLegWorker(spec);
        return panelLeg ?? legacyDispatchWorker(backend, spec, ctx, landing);
      },
      async resumeSession(spec, _wt, sessionId) {
        if (spec.id === "S3") {
          return {
            output: judgeContinue([sampleFinding("r1", "r1.ts:1")]),
            sessionId,
          };
        }
        if (spec.id === "S6") {
          resumeFailCount += 1;
          throw new Error(
            `Session resume failed: session ${sessionId} not found`,
          );
        }
        throw new Error(`unexpected resume of ${spec.id}`);
      },
      async runStep(spec): Promise<StepOutput | StepResult> {
        // #1081 open court at S1.
        if (spec.promptFile === "judge_open_court.md") {
          return {
            output: judgeConverged(),
            sessionId: COURT_SESSION,
          };
        }
        if (spec.id === "S2" || spec.id === "S5") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        if (spec.id === "S3" || spec.id === "S6") {
          // Fresh S3/S6 would be illegal under #1081 — count if it ever happens.
          s6FreshOpenings += 1;
          return {
            output: judgeConverged(),
            sessionId: "sess-illegal-fresh",
          };
        }
        throw new Error(`unexpected runStep of ${spec.id}:${spec.promptFile}`);
      },
    };

    try {
      const result = await runOrchestrator({ issueNumber: 9254, backend });
      expect(result.status).toBe("completed");
      expect(resumeFailCount).toBeGreaterThanOrEqual(1);
      expect(s6FreshOpenings).toBe(1);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("no S4 open-count step appears on a clean judge path", async () => {
    const backend = new JudgeBackend([{ kind: "converged" }]);
    const result = await runOrchestrator({ issueNumber: 9255, backend });
    expect(result.status).toBe("completed");
    expect(result.stepLedger.some((e) => e.step === "S4")).toBe(false);
    expect(backend.dispatched.some((d) => d.startsWith("S4:"))).toBe(false);
  });
});

describe("#925 F1: priorJudgeVerdicts land in fix-findings file", () => {
  it("legacyDispatchWorker writes prior rows into stateDir fix-findings.json", async () => {
    const worktree: WorktreeHandle = {
      branch: "feat/925-prior",
      base: "main",
      path: mkdtempSync(join(tmpdir(), "judge-prior-wt-")),
    };
    const stateDir = mkdtempSync(join(tmpdir(), "judge-prior-ledger-"));
    const prior = priorJudgeVerdictRowsFromLedger([
      {
        step: "S3",
        sessionId: "j-dead",
        output: judgeContinue([sampleFinding("prior", "p.ts:1")], {
          advanceCoder: "gpt-5.6-sol",
        }),
      },
    ]);
    expect(prior.length).toBe(1);

    let observedLanding: unknown;
    const backend: Backend = {
      async smokeModelRoute(route) {
        return route;
      },
      async findResumeState() {
        return undefined;
      },
      async resumeSession() {
        throw new Error("not expected");
      },
      async fetchIssueMeta() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async runStep() {
        observedLanding = JSON.parse(
          readFileSync(join(stateDir, "fix-findings.json"), "utf8"),
        );
        return judgeConverged();
      },
      async writeLedger() {},
    };

    const result = await legacyDispatchWorker(
      backend,
      {
        id: "S6",
        kind: "verify",
        role: "verify",
        host: "codex",
        session: "fresh",
        contextRetention: "clean",
        skill: "/verify",
        promptFile: "judge_station.md",
        maxIter: 1,
        model: "gpt-5.4",
        soul: "verify",
        toolchain: [],
      },
      {
        worktree,
        stateDir,
        priorJudgeVerdicts: prior,
      },
    );

    expect(result.kind).toBe("completed");
    expect(observedLanding).toMatchObject({
      priorJudgeVerdicts: [
        expect.objectContaining({
          step: "S3",
          status: "continue",
          advanceCoder: "gpt-5.6-sol",
          sessionId: "j-dead",
        }),
      ],
    });
    // Negative: no runner narrative summary field in the landing file.
    expect(
      (observedLanding as { trajectorySummary?: string }).trajectorySummary,
    ).toBeUndefined();
  });
});

describe("#925 F2: crash/resume rebuilds open set from judge continue", () => {
  it("ledger with S3 judge continue seeds S5 open set; killed keys excluded", async () => {
    const live = sampleFinding("live-claim", "live.ts:1");
    const dead = sampleFinding("dead-claim", "dead.ts:2");
    const liveKey = findingIdentityKey(live);
    const deadKey = findingIdentityKey(dead);
    const continueOut = judgeContinue([live, dead], {
      kill: [
        {
          identityKey: deadKey,
          action: "refute",
          reason: "not_established",
          evidence: "claim does not match code",
        },
      ],
    });
    const resumeLedger: PersistentLedgerEntry[] = [
      entry("S0"),
      entry("S1"),
      entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
      entry("S3", continueOut, S3_SESSION),
    ];
    const resumeState: ResumeState = {
      worktree: RESUME_WORKTREE,
      stateDir: STATE_DIR,
      ledger: resumeLedger,
    };
    const backend = new DispatchRecordingResumeBackend(resumeState);
    // Finish after S5: override S6 to judge converged (default returns reviewer
    // open-count 0 which normalises to converged — also fine).
    const result = await runOrchestrator({ issueNumber: 9256, backend });
    expect(result.status).toBe("completed");

    // planResume of S3 continue → S5; first dispatch is S5 with open set.
    expect(backend.dispatchSpecs[0]?.id).toBe("S5");
    const s5Ctx = backend.dispatchContexts[0]!;
    expect(s5Ctx.blockingFindingIdentityKeys).toEqual([]);
    expect(s5Ctx.blockingFindingIdentityKeys).not.toContain(deadKey);
    expect(s5Ctx.blockingFindingCount).toBe(0);
  });
});

describe("#925 S1: judge escalate park → owner answer → 原地 resume", () => {
  it("S3 escalate + escalation_answered resumes the same judge session in place", async () => {
    class JudgeEscalateResumeBackend extends DispatchRecordingResumeBackend {
      override async resumeSession(
        spec: StepSpec,
        _worktree: WorktreeHandle,
        sessionId: string,
      ): Promise<StepOutput> {
        this.calls.push(`resumeSession(${spec.id}, ${sessionId})`);
        this.resumeSessionCalls.push([spec.id, sessionId]);
        this.runStepIds.push(spec.id);
        // Answered reopen of the S3 judge → converge.
        if (spec.id === "S3") {
          return judgeConverged();
        }
        return { kind: "coder", committed: true, commitsAdded: 1 };
      }

      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        this.dispatchSpecs.push(spec);
        this.dispatchContexts.push(ctx);
        const stepSpec = spec as unknown as StepSpec;
        if (typeof ctx.resumeSessionId === "string") {
          const output = await this.resumeSession(
            stepSpec,
            ctx.worktree!,
            ctx.resumeSessionId,
          );
          return { kind: "completed", output, sessionId: ctx.resumeSessionId };
        }
        const output = await this.runStep(stepSpec, ctx.worktree!);
        return { kind: "completed", output };
      }
    }

    const backend = new JudgeEscalateResumeBackend({
      worktree: RESUME_WORKTREE,
      stateDir: STATE_DIR,
      ledger: [
        entry("S0"),
        entry("S1"),
        entry("S2", { kind: "coder", committed: true, commitsAdded: 1 }),
        entry(
          "S3",
          judgeEscalate("stalled", "same bug 3 rounds"),
          S3_SESSION,
        ),
        s8("parked"),
        escalationAnswer("S3", "owner: keep going with the live set"),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 9257, backend });
    expect(result.status).toBe("completed");
    // 原地 resume of the escalated S3 judge session — not a fresh S0 cut.
    expect(backend.resumeSessionCalls[0]).toEqual(["S3", S3_SESSION]);
    expect(backend.dispatchContexts[0]?.escalationAnswer).toEqual({
      event: "escalation_answered",
      forStep: "S3",
      answer: "owner: keep going with the live set",
      source: "human",
    });
    expect(backend.dispatchSpecs[0]?.session).toBe("resume");
  });
});

describe("#925 priorJudgeVerdictRowsFromLedger pure", () => {
  it("extracts S3/S6 judge rows only", () => {
    const ledger: LedgerEntry[] = [
      { step: "S2", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      {
        step: "S3",
        sessionId: "j1",
        output: judgeContinue([sampleFinding()], { advanceCoder: "x" }),
      },
      { step: "S5", output: { kind: "coder", committed: true, commitsAdded: 1 } },
      { step: "S6", sessionId: "j1", output: judgeConverged() },
    ];
    const rows = priorJudgeVerdictRowsFromLedger(ledger);
    expect(rows).toHaveLength(2);
    expect(rows[0]!.status).toBe("continue");
    expect(rows[0]!.advanceCoder).toBe("x");
    expect(rows[1]!.status).toBe("converged");
  });
});

describe("#919 CR U1/U3: residual→judge projection + reviewer-role escalate mint", () => {
  it("workerResultToStep for expectedKind reviewer mints kind:judge escalate (not residual paper)", () => {
    const { unwrapped } = workerResultToStep(
      {
        kind: "escalated",
        escalation: { reason: "gate", diagnosis: "need decision" },
      },
      "reviewer",
    );
    expect(unwrapped).toMatchObject({
      kind: "judge",
      status: "escalate",
      reason: "gate",
      diagnosis: "need decision",
      escalate: { reason: "gate", diagnosis: "need decision" },
    });
    expect((unwrapped as StepOutput).kind).not.toBe("reviewer");
  });

});
