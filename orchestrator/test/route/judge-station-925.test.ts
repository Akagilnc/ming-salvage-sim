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

import { describe, expect, it } from "vitest";
import { existsSync, mkdirSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  buildJudgeReviewLegPrompt,
  isLegalJudgeReviewLegSession,
  judgeContinueFromOpenCount,
  judgeKillsToLedgerDispositions,
  judgeReviewLegSessionMode,
  liveDispositionsForOpenCount,
  liveFindingsBlockConverged,
  openFindingsForFixer,
  priorJudgeVerdictRowsFromLedger,
  projectJudgeContinueBlocking,
} from "../../src/judgeStation.js";
import { findingIdentityKey } from "../../src/findings.js";
import { legacyDispatchWorker } from "../../src/dispatchWorker.js";
import { route } from "../../src/route.js";
import { runOrchestrator, stepSpecsForEnv } from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  AgentStepRunOptions,
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  LedgerEntry,
  PersistentLedgerEntry,
  ResumeState,
  StepOutput,
  StepResult,
  StepSpec,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";
import {
  completedJudge,
  judgeConverged,
  judgeContinue,
  judgeEscalate,
  sampleFinding,
} from "../helpers/judge-fixtures.js";
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

const S3_SESSION = "sess-judge-s3-925";

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
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "" };
  }
  async prepareWorktree(): Promise<WorktreeHandle> {
    return WORKTREE;
  }
  async writeSnapshot(): Promise<void> {}
  async writeLedger(): Promise<void> {}

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
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

    if (
      spec.kind === "verify" ||
      spec.kind === "reviewer" ||
      spec.id === "S3" ||
      spec.id === "S6"
    ) {
      const script = this.judgeScripts[this.judgeIdx] ?? { kind: "converged" };
      this.judgeIdx += 1;
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
  | { kind: "continue"; findings?: Finding[]; advanceCoder?: string; killKey?: string }
  | { kind: "escalate"; reason?: string; diagnosis?: string };

function scriptToOutput(script: JudgeResultScript) {
  if (script.kind === "converged") return judgeConverged();
  if (script.kind === "escalate") {
    return judgeEscalate(script.reason, script.diagnosis);
  }
  const findings = script.findings ?? [sampleFinding()];
  if (script.killKey !== undefined) {
    return judgeContinue(findings, {
      kill: [
        {
          identityKey: script.killKey,
          action: "refute",
          reason: "unconstitutional",
          evidence: "violates ADR 0132",
        },
      ],
      advanceCoder: script.advanceCoder,
    });
  }
  return judgeContinue(findings, { advanceCoder: script.advanceCoder });
}

describe("#925 pure: leg prompt + session mode", () => {
  it("prepends full reviewer soul at leg prompt head (positive)", () => {
    const soul = readFileSync(join(SOULS, "reviewer.md"), "utf8");
    const prompt = buildJudgeReviewLegPrompt(soul, "Review the full diff.");
    expect(prompt.startsWith(soul.trim())).toBe(true);
    expect(prompt).toContain("Review the full diff.");
    expect(prompt).toContain("---");
  });

  it("rejects empty soul or body (negative)", () => {
    expect(() => buildJudgeReviewLegPrompt("", "task")).toThrow(/soul/);
    expect(() => buildJudgeReviewLegPrompt("soul", "")).toThrow(/body/);
  });

  it("review legs must be fresh — resume is illegal (negative)", () => {
    expect(judgeReviewLegSessionMode()).toBe("fresh");
    expect(isLegalJudgeReviewLegSession("fresh")).toBe(true);
    expect(isLegalJudgeReviewLegSession("resume")).toBe(false);
  });
});

describe("#925 pure: disposition → open-only + refuted flips", () => {
  it("filters dead keys out of S5 findings (positive + negative)", () => {
    const live = sampleFinding("live", "a.ts:1");
    const dead = sampleFinding("dead", "b.ts:2");
    const liveKey = findingIdentityKey(live);
    const deadKey = findingIdentityKey(dead);
    const dispositions = [
      { identityKey: liveKey, action: "live" as const },
      {
        identityKey: deadKey,
        action: "refute" as const,
        reason: "not_established" as const,
        evidence: "claim does not match code",
      },
    ];
    const open = openFindingsForFixer([live, dead], dispositions);
    expect(open).toEqual([live]);
    expect(open.some((f) => findingIdentityKey(f) === deadKey)).toBe(false);

    const kills = judgeKillsToLedgerDispositions(dispositions);
    expect(kills).toHaveLength(1);
    expect(kills[0]!.status).toBe("refuted");
    expect(kills[0]!.identityKey).toBe(deadKey);
  });

  it("live findings block converged (negative consistency)", () => {
    expect(
      liveFindingsBlockConverged([{ action: "live" }, { action: "refute" }]),
    ).toBe(true);
    expect(liveFindingsBlockConverged([{ action: "refute" }])).toBe(false);
    expect(liveFindingsBlockConverged([])).toBe(false);
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
      status: "escalate",
    });
  });

  it("negative: live continue must not route to S7", () => {
    const decision = route({
      from: "S6",
      output: judgeContinue([sampleFinding()]),
    });
    expect(decision).not.toEqual({ kind: "next", step: "S7" });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  it("unusable (non-judge) envelope → S5, never silent clean", () => {
    expect(
      route({
        from: "S3",
        output: { kind: "fixer", committed: false },
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
  it("stepSpecs pin verify soul, maxIter 1, judge prompt", () => {
    const specs = stepSpecsForEnv();
    expect(specs.S3.maxIter).toBe(1);
    expect(specs.S6.maxIter).toBe(1);
    // WorkerKind stays reviewer for the child dispatch seam; soul is verify.
    expect(specs.S3.role).toBe("reviewer");
    expect(specs.S6.role).toBe("reviewer");
    expect(specs.S3.soul).toBe("verify");
    expect(specs.S6.soul).toBe("verify");
    expect(specs.S3.promptFile).toBe("judge_station.md");
    expect(specs.S6.promptFile).toBe("judge_station.md");
  });
});

describe("#925 runOrchestrator: resume shape + routing", () => {
  it("S3 is fresh single-iter; S6 resumes the same judge session", async () => {
    const backend = new JudgeBackend([
      {
        kind: "continue",
        findings: [sampleFinding()],
        advanceCoder: "gpt-5.6-sol",
      },
      { kind: "converged" },
    ]);
    const result = await runOrchestrator({ issueNumber: 925, backend });
    expect(result.status).toBe("success");

    const s3 = backend.specs.find((s) => s.id === "S3");
    const s6 = backend.specs.find((s) => s.id === "S6");
    expect(s3).toBeDefined();
    expect(s6).toBeDefined();
    expect(s3!.maxIter).toBe(1);
    expect(s6!.maxIter).toBe(1);
    expect(s3!.session).toBe("fresh");
    expect(s6!.session).toBe("resume");
    expect(backend.resumeSessionCalls).toContainEqual(["S6", S3_SESSION]);

    // Negative: must not multi-iter the judge seat.
    expect(s3!.maxIter).not.toBeGreaterThan(1);
    expect(s6!.maxIter).not.toBeGreaterThan(1);
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
    expect(result.status).toBe("success");

    const s5Idx = backend.specs.findIndex((s) => s.id === "S5");
    expect(s5Idx).toBeGreaterThanOrEqual(0);
    const s5Ctx = backend.ctxs[s5Idx]!;
    expect(s5Ctx.blockingFindingIdentityKeys).toEqual([
      findingIdentityKey(live),
    ]);
    expect(s5Ctx.blockingFindingIdentityKeys).not.toContain(deadKey);
    expect(s5Ctx.blockingFindingCount).toBe(1);

    // Ledger carries kill flip + advance slot when present.
    const judgeRows = result.stepLedger.filter(
      (e) => e.step === "S3" || e.step === "S6",
    );
    expect(judgeRows.length).toBeGreaterThanOrEqual(1);
    const s3Row = result.stepLedger.find((e) => e.step === "S3");
    expect(s3Row?.findingDispositions?.some((d) => d.status === "refuted")).toBe(
      true,
    );
  });

  it("advanceCoder lands on the S3 ledger row", async () => {
    const backend = new JudgeBackend([
      {
        kind: "continue",
        findings: [sampleFinding()],
        advanceCoder: "claude-opus",
      },
      { kind: "converged" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9252, backend });
    expect(result.status).toBe("success");
    const s3 = result.stepLedger.find((e) => e.step === "S3");
    expect(s3?.advanceCoder).toBe("claude-opus");
  });

  it("escalate parks via decision-kind (status escalate), does not success-terminal", async () => {
    const backend = new JudgeBackend([
      { kind: "escalate", reason: "stalled", diagnosis: "same bug 3 rounds" },
    ]);
    const result = await runOrchestrator({ issueNumber: 9253, backend });
    expect(result.status).toBe("escalate");
    expect(result.status).not.toBe("success");
    // Must not invent a brand-new terminal — still the escalate park family.
    expect(backend.specs.some((s) => s.id === "S7")).toBe(false);
  });

  it("dead resume → fresh S6 consumes prior continue via fix-findings landing", async () => {
    // Real session-loss behaviour (not ctx-only shape): resume fails once →
    // mechanical redispatch opens fresh S6; prior verdict rows land in
    // fix-findings.json; the seat converges only when that landing carries the
    // expected prior status (消费此前走势).
    const parent = mkdtempSync(join(tmpdir(), "judge-session-loss-"));
    const worktreePath = join(parent, "wt-9254");
    mkdirSync(worktreePath, { recursive: true });
    const worktree: WorktreeHandle = {
      branch: "feat/925-session-loss",
      base: "main",
      path: worktreePath,
    };
    const DEAD_SESSION = "sess-judge-s3-dead-925";
    const FRESH_AFTER_DEAD = "sess-judge-s6-fresh-after-dead";
    let resumeFailCount = 0;
    let s6FreshOpenings = 0;
    let observedLanding: {
      priorJudgeVerdicts?: Array<{
        status?: string;
        step?: string;
        sessionId?: string;
      }>;
      trajectorySummary?: string;
    } | undefined;
    let s6ConsumedPriorContinue = false;

    const readLanding = (
      options?: AgentStepRunOptions,
    ): typeof observedLanding => {
      const landingPath = options?.fixFindingsLanding?.path;
      if (landingPath === undefined || !existsSync(landingPath)) {
        return undefined;
      }
      return JSON.parse(readFileSync(landingPath, "utf8")) as NonNullable<
        typeof observedLanding
      >;
    };

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
      async fetchIssueSnapshot(issueNumber) {
        return {
          number: issueNumber,
          body: "b",
          comments: [],
          agentBrief: "",
        };
      },
      async prepareWorktree() {
        return worktree;
      },
      async writeSnapshot() {},
      async writeLedger() {},
      async resumeSession(spec, _wt, sessionId, options) {
        if (spec.id === "S6") {
          resumeFailCount += 1;
          // Landing is written before resumeSession (legacyDispatchWorker).
          observedLanding = readLanding(options);
          throw new Error(
            `Session resume failed: session ${sessionId} not found`,
          );
        }
        throw new Error(`unexpected resume of ${spec.id}`);
      },
      async runStep(spec, _wt, options): Promise<StepOutput | StepResult> {
        if (spec.id === "S2" || spec.id === "S5") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        if (spec.id === "S3") {
          return {
            output: judgeContinue([sampleFinding("r1", "r1.ts:1")]),
            sessionId: DEAD_SESSION,
          };
        }
        if (spec.id === "S6") {
          s6FreshOpenings += 1;
          // Fresh seat after dead resume — must read structured prior rows from
          // the fix-findings landing (not a runner-synthesised narrative).
          observedLanding = readLanding(options);
          const priors = observedLanding?.priorJudgeVerdicts;
          const sawContinue = (priors ?? []).some(
            (r) => r.status === "continue",
          );
          if (!sawContinue) {
            return {
              output: judgeEscalate(
                "no_prior_trajectory",
                "landing missing prior continue status",
              ),
              sessionId: FRESH_AFTER_DEAD,
            };
          }
          s6ConsumedPriorContinue = true;
          return {
            output: judgeConverged(),
            sessionId: FRESH_AFTER_DEAD,
          };
        }
        throw new Error(`unexpected runStep of ${spec.id}`);
      },
    };

    const result = await runOrchestrator({ issueNumber: 9254, backend });
    expect(result.status).toBe("success");
    // Dead resume once, then fresh S6 (no second resume).
    expect(resumeFailCount).toBe(1);
    expect(s6FreshOpenings).toBe(1);
    expect(s6ConsumedPriorContinue).toBe(true);
    expect(observedLanding?.priorJudgeVerdicts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          step: "S3",
          status: "continue",
          sessionId: DEAD_SESSION,
        }),
      ]),
    );
    // Negative: no runner-authored narrative field in the landing file.
    expect(observedLanding?.trajectorySummary).toBeUndefined();
    // Fresh after dead keeps a new session id on the S6 ledger row.
    const s6Row = result.stepLedger.find((e) => e.step === "S6");
    expect(s6Row?.sessionId).toBe(FRESH_AFTER_DEAD);
  });

  it("no S4 open-count step appears on a clean judge path", async () => {
    const backend = new JudgeBackend([{ kind: "converged" }]);
    const result = await runOrchestrator({ issueNumber: 9255, backend });
    expect(result.status).toBe("success");
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
      async fetchIssueSnapshot() {
        throw new Error("not expected");
      },
      async prepareWorktree() {
        throw new Error("not expected");
      },
      async writeSnapshot() {},
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
        kind: "reviewer",
        role: "reviewer",
        host: "codex",
        session: "fresh",
        contextRetention: "clean",
        skill: "/code-review",
        promptFile: "judge_station.md",
        completionSignal: "JUDGE_STEP_COMPLETE",
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
    expect(result.status).toBe("success");

    // planResume of S3 continue → S5; first dispatch is S5 with open set.
    expect(backend.dispatchSpecs[0]?.id).toBe("S5");
    const s5Ctx = backend.dispatchContexts[0]!;
    expect(s5Ctx.blockingFindingIdentityKeys).toEqual([liveKey]);
    expect(s5Ctx.blockingFindingIdentityKeys).not.toContain(deadKey);
    expect(s5Ctx.blockingFindingCount).toBe(1);
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
        s8("escalate"),
        escalationAnswer("S3", "owner: keep going with the live set"),
      ],
    });

    const result = await runOrchestrator({ issueNumber: 9257, backend });
    expect(result.status).toBe("success");
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

describe("#925 F3: single open-count → continue projection", () => {
  it("mints __open_N live keys when cargo is sparse; reuses findings when present", () => {
    const sparse = liveDispositionsForOpenCount(2, []);
    expect(sparse).toEqual([
      { identityKey: "__open_1", action: "live" },
      { identityKey: "__open_2", action: "live" },
    ]);
    const f = sampleFinding("c", "c.ts:1");
    const withCargo = liveDispositionsForOpenCount(1, [f]);
    expect(withCargo).toEqual([
      { identityKey: findingIdentityKey(f), action: "live" },
    ]);
    const continueOut = judgeContinueFromOpenCount(2, []);
    expect(continueOut?.status).toBe("continue");
    expect(continueOut?.findingDispositions).toEqual(sparse);
    expect(judgeContinueFromOpenCount(0, [])).toBeUndefined();
  });

  it("projectJudgeContinueBlocking keeps live keys only and flips kills", () => {
    const live = sampleFinding("L", "l.ts:1");
    const dead = sampleFinding("D", "d.ts:2");
    const out = judgeContinue([live, dead], {
      kill: [
        {
          identityKey: findingIdentityKey(dead),
          action: "refute",
          reason: "scope_creep",
          evidence: "out of AC",
        },
      ],
    });
    const projected = projectJudgeContinueBlocking(out);
    expect(projected?.blockingIdentityKeys).toEqual([findingIdentityKey(live)]);
    expect(projected?.killDispositions).toHaveLength(1);
    expect(projected?.killDispositions[0]!.status).toBe("refuted");
  });
});

describe("#925 verify.md 收敛判官 chapter + judge prompt", () => {
  it("soul chapter has tri-state / four reasons / trajectory stall", () => {
    const text = readFileSync(join(SOULS, "verify.md"), "utf8");
    expect(text).toMatch(/收敛判官/);
    expect(text).toMatch(/converged/);
    expect(text).toMatch(/continue/);
    expect(text).toMatch(/escalate/);
    expect(text).toMatch(/unconstitutional|违宪/);
    expect(text).toMatch(/over_defense|过度防御/);
    expect(text).toMatch(/not_established|事实不成立/);
    expect(text).toMatch(/scope_creep|越权/);
    expect(text).toMatch(/走势|卡死/);
  });

  it("judge_station prompt teaches T2 envelope fields + session-loss landing", () => {
    const text = readFileSync(join(PROMPTS, "judge_station.md"), "utf8");
    expect(text).toMatch(/stationReceiptContracts/);
    expect(text).toMatch(/JUDGE_STEP_COMPLETE/);
    expect(text).toMatch(/findingDispositions/);
    expect(text).toMatch(/advanceCoder/);
    expect(text).toMatch(/maxIterations|maxIter/);
    expect(text).toMatch(/priorJudgeVerdicts/);
    expect(text).toMatch(/ORCHESTRATOR_FIX_FINDINGS_PATH|fix-findings/);
  });
});
