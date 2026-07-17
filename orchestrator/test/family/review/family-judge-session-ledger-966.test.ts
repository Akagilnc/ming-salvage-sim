/**
 * #966 — family judge session continuity from ledger (not dead ByPass relay).
 *
 * Defect: verifyCmr packed restartFinalBarrier.judgeSessionIdByPass expecting
 * callers to pass it back, but nothing outside the process-local loop consumed
 * it across separate final-barrier rounds → every round opened a fresh amnesiac
 * judge. Ledger already records sessionId on cmr_reviewed / cmr_passed (#930).
 *
 * Acceptance:
 *   1. Next-round resume sessionId is derived from family ledger
 *      (priorFamilyJudgeVerdictRowsFromLedger / PriorJudgeVerdictRow.sessionId)
 *   2. Dead judgeSessionIdByPass production is deleted
 *   3. Two consecutive family CMR rounds: round-2 judge resumes round-1 session
 *      (grok seat is resume-capable — #955 sessionStorage)
 *   4. Fresh fallback when session truly absent stays (priorJudgeVerdicts only)
 */

import { describe, expect, it } from "vitest";

import { findingIdentityKey } from "../../../src/findings.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import { resumeCapableForSlug } from "../../../src/modelRegistry.js";
import {
  resolveActiveModelRoute,
  smokeRouteModels,
} from "../../../src/modelRoutes.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";
import type {
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../../src/family/types.js";
import type {
  DispatchContext,
  JudgeResult,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import {
  judgeConverged,
  judgeContinue,
  sampleFinding,
} from "../../helpers/judge-fixtures.js";

const FINDING = sampleFinding(
  "family open claim 966",
  "orchestrator/src/family/verifyCmr.ts:966",
);
const FINDING_KEY = findingIdentityKey(FINDING);
const ROUND1_SESSION = "judge-sess-round1-966";
const GROK_SLUG = "grok-4.5";

function completedJudge(output: JudgeResult, sessionId?: string): WorkerResult {
  return {
    kind: "completed",
    output,
    ...(sessionId !== undefined ? { sessionId } : {}),
  };
}

class FamilyJudgeLedgerBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: Array<{
    readonly kind: string;
    readonly session: string;
    readonly model?: string;
    readonly cmrPass?: string;
    readonly resumeSessionId?: string;
    readonly priorJudgeVerdicts?: DispatchContext["priorJudgeVerdicts"];
  }> = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: string[] = [];
  currentFamilyHead = "head-r1";

  private completenessRound = 0;
  private correctnessRound = 0;
  private coderFixRound = 0;

  constructor(
    private readonly script: {
      completeness?: (
        round: number,
        ctx: DispatchContext,
      ) => WorkerResult;
      correctness?: (
        round: number,
        ctx: DispatchContext,
      ) => WorkerResult;
      coder?: (round: number, ctx: DispatchContext) => WorkerResult;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async runFamilyVerify(_req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }

  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    this.dispatches.push({
      kind: spec.kind,
      session: spec.session,
      ...(typeof spec.model === "string" ? { model: spec.model } : {}),
      ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
      ...(ctx.resumeSessionId !== undefined
        ? { resumeSessionId: ctx.resumeSessionId }
        : {}),
      ...(ctx.priorJudgeVerdicts !== undefined
        ? { priorJudgeVerdicts: ctx.priorJudgeVerdicts }
        : {}),
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness") {
        const round = this.completenessRound++;
        if (this.script.completeness !== undefined) {
          return this.script.completeness(round, ctx);
        }
        return completedJudge(judgeConverged(), ROUND1_SESSION);
      }
      const round = this.correctnessRound++;
      if (this.script.correctness !== undefined) {
        return this.script.correctness(round, ctx);
      }
      return completedJudge(judgeConverged(), `${ROUND1_SESSION}-correctness`);
    }

    if (spec.kind === "coder") {
      const round = this.coderFixRound++;
      this.currentFamilyHead = `head-after-fix-${round + 1}`;
      if (this.script.coder !== undefined) {
        return this.script.coder(round, ctx);
      }
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }

    if (spec.kind === "ship") {
      this.prCalls.push(ctx.familyBase ?? "");
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase ?? "family/base",
          status: "pr_opened",
          pr: `pr://${ctx.familyBase}`,
          prHead: this.currentFamilyHead,
        },
      };
    }

    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    throw new Error(`unexpected worker kind ${spec.kind}`);
  }

  /** Reset per-pass open counters so a second runVerifyCmr starts rounds at 0. */
  resetRoundCounters(): void {
    this.completenessRound = 0;
    this.correctnessRound = 0;
    this.coderFixRound = 0;
  }
}

async function grokCmrRoute() {
  const base = resolveActiveModelRoute({ ORCHESTRATOR_ROUTE: "normal" });
  return smokeRouteModels(
    {
      ...base,
      slots: {
        ...base.slots,
        cmrCompleteness: GROK_SLUG,
        cmrCorrectness: GROK_SLUG,
      },
    },
    async () => ({ cliVersion: "test-966" }),
  );
}

describe("#966 family judge session from ledger", () => {
  it("registry truth: grok-4.5 is resume-capable (#955 sessionStorage path)", () => {
    expect(resumeCapableForSlug(GROK_SLUG)).toBe(true);
  });

  it("two consecutive final CMR rounds: round-2 judge resumes round-1 session (ledger)", async () => {
    // Round 1 opens fresh, records sessionId on cmr_reviewed / cmr_passed.
    // Round 2 is a NEW runVerifyCmr (external head advance — barrier re-entry).
    // Without ledger-derived resume, round-2 would open fresh every time.
    const backend = new FamilyJudgeLedgerBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING]), ROUND1_SESSION);
        }
        return completedJudge(judgeConverged(), ROUND1_SESSION);
      },
      correctness: () =>
        completedJudge(judgeConverged(), `${ROUND1_SESSION}-correctness`),
    });
    const route = await grokCmrRoute();

    const round1 = await runVerifyCmr({
      phase: "final",
      familyBase: "family/966-base",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(round1).toEqual({ ok: true, ran: true });

    const round1Completeness = backend.dispatches.filter(
      (d) => d.kind === "cmr" && d.cmrPass === "completeness",
    );
    expect(round1Completeness.length).toBeGreaterThanOrEqual(2);
    expect(round1Completeness[0]?.session).toBe("fresh");
    expect(round1Completeness[0]?.resumeSessionId).toBeUndefined();
    // Within-round fix re-open must also resume (ledger sole truth after #966).
    expect(round1Completeness[1]?.session).toBe("resume");
    expect(round1Completeness[1]?.resumeSessionId).toBe(ROUND1_SESSION);
    // Grok seat was the real dispatch model for the court.
    expect(round1Completeness[0]?.model).toBe(GROK_SLUG);
    expect(round1Completeness[1]?.model).toBe(GROK_SLUG);
    expect(resumeCapableForSlug(round1Completeness[1]!.model!)).toBe(true);

    // Ledger is the durable source: sessionId on court rows for completeness.
    expect(
      backend.ledger.some(
        (e) =>
          (e.status === "cmr_reviewed" || e.status === "cmr_passed") &&
          e.cmrPass === "completeness" &&
          e.sessionId === ROUND1_SESSION,
      ),
    ).toBe(true);

    // External head advance (not barrier-internal-only) forces re-open of courts.
    const dispatchCountAfterRound1 = backend.dispatches.length;
    backend.currentFamilyHead = "head-external-round2";
    backend.resetRoundCounters();

    const round2 = await runVerifyCmr({
      phase: "final",
      familyBase: "family/966-base",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(round2).toEqual({ ok: true, ran: true });

    const round2Completeness = backend.dispatches
      .slice(dispatchCountAfterRound1)
      .filter((d) => d.kind === "cmr" && d.cmrPass === "completeness");
    expect(round2Completeness.length).toBeGreaterThanOrEqual(1);
    // #966 core: next final-barrier round resumes the ledger session — not fresh.
    expect(round2Completeness[0]?.session).toBe("resume");
    expect(round2Completeness[0]?.resumeSessionId).toBe(ROUND1_SESSION);
    expect(round2Completeness[0]?.model).toBe(GROK_SLUG);
    // priorJudgeVerdicts still land for trajectory (even on resume).
    expect(
      (round2Completeness[0]?.priorJudgeVerdicts?.length ?? 0) > 0,
    ).toBe(true);
  });

  it("session truly absent → fresh open with priorJudgeVerdicts (no resume)", async () => {
    const backend = new FamilyJudgeLedgerBackend({
      completeness: (round, ctx) => {
        if (round === 0) {
          // No sessionId on WorkerResult → ledger court row has no session to resume.
          return { kind: "completed", output: judgeContinue([FINDING]) };
        }
        expect(ctx.resumeSessionId).toBeUndefined();
        expect(
          ctx.priorJudgeVerdicts?.some((r) => r.status === "continue"),
        ).toBe(true);
        return completedJudge(judgeConverged(), "judge-fresh-after-loss-966");
      },
    });
    const route = await grokCmrRoute();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/966-loss",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(result).toEqual({ ok: true, ran: true });
    const opens = backend.dispatches.filter(
      (d) => d.kind === "cmr" && d.cmrPass === "completeness",
    );
    expect(opens[0]?.session).toBe("fresh");
    expect(opens[1]?.session).toBe("fresh");
    expect(opens[1]?.resumeSessionId).toBeUndefined();
  });
});
