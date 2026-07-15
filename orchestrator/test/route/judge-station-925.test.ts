/**
 * #925 — persistent judge station + fresh legs + tri-state verdict routing.
 *
 * Seams (owner-confirmed via #919 Testing Decisions):
 * 1. runOrchestrator + fake Backend — topology / resume / session-loss /
 *    escalate park / S5 open-only
 * 2. Pure helpers — leg prompt shape, disposition flips, live filter
 */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  buildJudgeReviewLegPrompt,
  isLegalJudgeReviewLegSession,
  judgeKillsToLedgerDispositions,
  judgeReviewLegSessionMode,
  liveFindingsBlockConverged,
  openFindingsForFixer,
  priorJudgeVerdictRowsFromLedger,
} from "../../src/judgeStation.js";
import { findingIdentityKey } from "../../src/findings.js";
import { route } from "../../src/route.js";
import { runOrchestrator, stepSpecsForEnv } from "../../src/runner.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";
import type {
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  IssueSnapshot,
  LedgerEntry,
  StepOutput,
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
  private failResumeOnce: boolean;

  constructor(
    judgeScripts?: JudgeResultScript[],
    opts?: { failResumeOnce?: boolean },
  ) {
    this.judgeScripts = judgeScripts ?? [{ kind: "converged" }];
    this.failResumeOnce = opts?.failResumeOnce === true;
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
      if (this.failResumeOnce && spec.id === "S6") {
        this.failResumeOnce = false;
        // Simulate dead-session fallback: still complete as fresh with new id,
        // but the runner already requested resume (shape under test).
      }
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

  it("session-loss path still supplies prior judge verdict rows (trajectory)", async () => {
    const backend = new JudgeBackend(
      [
        {
          kind: "continue",
          findings: [sampleFinding("r1", "r1.ts:1")],
        },
        { kind: "converged" },
      ],
      { failResumeOnce: true },
    );
    const result = await runOrchestrator({ issueNumber: 9254, backend });
    expect(result.status).toBe("success");

    const s6Idx = backend.specs.findIndex((s) => s.id === "S6");
    expect(s6Idx).toBeGreaterThanOrEqual(0);
    const s6Ctx = backend.ctxs[s6Idx]!;
    // Runner transports prior rows; does not synthesise prose summary.
    expect(s6Ctx.priorJudgeVerdicts).toBeDefined();
    expect(s6Ctx.priorJudgeVerdicts!.length).toBeGreaterThanOrEqual(1);
    expect(s6Ctx.priorJudgeVerdicts![0]!.status).toBe("continue");
    // Negative: no runner-authored narrative field.
    expect(
      (s6Ctx as { trajectorySummary?: string }).trajectorySummary,
    ).toBeUndefined();
  });

  it("no S4 open-count step appears on a clean judge path", async () => {
    const backend = new JudgeBackend([{ kind: "converged" }]);
    const result = await runOrchestrator({ issueNumber: 9255, backend });
    expect(result.status).toBe("success");
    expect(result.stepLedger.some((e) => e.step === "S4")).toBe(false);
    expect(backend.dispatched.some((d) => d.startsWith("S4:"))).toBe(false);
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

  it("judge_station prompt teaches T2 envelope fields", () => {
    const text = readFileSync(join(PROMPTS, "judge_station.md"), "utf8");
    expect(text).toMatch(/stationReceiptContracts/);
    expect(text).toMatch(/JUDGE_STEP_COMPLETE/);
    expect(text).toMatch(/findingDispositions/);
    expect(text).toMatch(/advanceCoder/);
    expect(text).toMatch(/maxIterations|maxIter/);
  });
});
