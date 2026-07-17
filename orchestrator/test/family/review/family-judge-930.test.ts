/**
 * #930 — family CMR courts close on shared T2 judge tri-state (not open-count).
 *
 * Seams (owner #919 Testing Decisions + #930 AC):
 * 1. runVerifyCmr + fake FamilyBackend — dual gates, tri-state routing,
 *    refuse → re-open judge, resume session shape, session-loss prior rows
 * 2. Pure helpers — closeFamilyCourtFromJudgeOutput, liveFindingsBlockConverged,
 *    priorFamilyJudgeVerdictRowsFromLedger
 */

import { describe, expect, it } from "vitest";

import {
  closeFamilyCourtFromJudgeOutput,
  liveFindingsBlockConverged,
  priorFamilyJudgeVerdictRowsFromLedger,
  priorJudgeVerdictRowsFromLedger,
  projectJudgeContinueBlocking,
  unusableResidualOpenCountPaper,
} from "../../../src/judgeStation.js";
import { findingIdentityKey } from "../../../src/findings.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import { cmrOutcomeFromResult } from "../../../src/family/realFamilyBackend.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyEscalation,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../../src/family/types.js";
import type {
  DispatchContext,
  JudgeResult,
  LedgerEntry,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import {
  judgeConverged,
  judgeContinue,
  judgeEscalate,
  sampleFinding,
} from "../../helpers/judge-fixtures.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const FINDING = sampleFinding("family open claim", "orchestrator/src/family/verifyCmr.ts:1");
const FINDING_KEY = findingIdentityKey(FINDING);

function completedJudge(
  output: JudgeResult,
  sessionId?: string,
): WorkerResult {
  return {
    kind: "completed",
    output,
    ...(sessionId !== undefined ? { sessionId } : {}),
  };
}

class FamilyJudgeBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatches: Array<{
    readonly kind: string;
    readonly session: string;
    readonly model?: string;
    readonly cmrPass?: string;
    readonly resumeSessionId?: string;
    readonly priorJudgeVerdicts?: DispatchContext["priorJudgeVerdicts"];
    readonly refusedFindingIdentityKeys?: ReadonlyArray<string>;
    readonly blockingFindingIdentityKeys?: ReadonlyArray<string>;
    /** #919 R2 — landing payload on re-open (refuseRecords cargo). */
    readonly landing?: WorkerLandingPayload;
  }> = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: string[] = [];
  currentFamilyHead = "head-1";

  private completenessRound = 0;
  private correctnessRound = 0;
  private coderFixRound = 0;

  constructor(
    private readonly script: {
      completeness?: (
        round: number,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ) => WorkerResult;
      correctness?: (
        round: number,
        ctx: DispatchContext,
        landing?: WorkerLandingPayload,
      ) => WorkerResult;
      coder?: (round: number, ctx: DispatchContext) => WorkerResult;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
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
    landing?: WorkerLandingPayload,
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
      ...(ctx.refusedFindingIdentityKeys !== undefined
        ? { refusedFindingIdentityKeys: ctx.refusedFindingIdentityKeys }
        : {}),
      ...(ctx.blockingFindingIdentityKeys !== undefined
        ? { blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys }
        : {}),
      ...(landing !== undefined ? { landing } : {}),
    });

    if (spec.kind === "cmr") {
      if (ctx.cmrPass === "completeness") {
        const round = this.completenessRound++;
        if (this.script.completeness !== undefined) {
          return this.script.completeness(round, ctx, landing);
        }
        return completedJudge(judgeConverged(), "judge-sess-completeness");
      }
      const round = this.correctnessRound++;
      if (this.script.correctness !== undefined) {
        return this.script.correctness(round, ctx, landing);
      }
      return completedJudge(judgeConverged(), "judge-sess-correctness");
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

    // #600/#603 online-review tail after ship (verify / fixer / landing / cleanup).
    const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
    if (skeleton !== undefined) return skeleton;
    throw new Error(`unexpected worker kind ${spec.kind}`);
  }
}

describe("#930 pure family judge closure", () => {
  it("converged → pass", () => {
    expect(closeFamilyCourtFromJudgeOutput(judgeConverged())).toEqual({
      action: "pass",
    });
  });

  it("continue → live-only open set for coder-fix", () => {
    const killKey = findingIdentityKey(
      sampleFinding("dead claim", "a.ts:1"),
    );
    const live = FINDING;
    const verdict = judgeContinue([live, sampleFinding("dead claim", "a.ts:1")], {
      kill: [
        {
          identityKey: killKey,
          action: "refute",
          reason: "not_established",
          evidence: "claim fails on real code",
        },
      ],
    });
    const closure = closeFamilyCourtFromJudgeOutput(verdict);
    expect(closure.action).toBe("continue");
    if (closure.action !== "continue") return;
    expect(closure.blockingIdentityKeys).toEqual([FINDING_KEY]);
    expect(closure.blocking).toEqual([live]);
    expect(closure.blockingFindingCount).toBe(1);
    expect(closure.terminalDispositions).toHaveLength(1);
    expect(closure.terminalDispositions[0]?.status).toBe("refuted");
  });

  it("#952 continue → suppress parks as terminalDispositions suppressed (queryable)", () => {
    const parked = sampleFinding("parked claim", "b.ts:2");
    const suppressKey = findingIdentityKey(parked);
    const live = FINDING;
    const verdict = judgeContinue([live, parked], {
      suppress: [
        {
          identityKey: suppressKey,
          action: "suppress",
          evidence: "owner parked via ticket",
          groundTicket: 949,
        },
      ],
    });
    // Schema table on the verdict is what family ledger persists (action:suppress).
    expect(
      verdict.findingDispositions?.some(
        (d) => d.action === "suppress" && d.identityKey === suppressKey,
      ),
    ).toBe(true);

    const closure = closeFamilyCourtFromJudgeOutput(verdict);
    expect(closure.action).toBe("continue");
    if (closure.action !== "continue") return;
    expect(closure.blockingIdentityKeys).toEqual([FINDING_KEY]);
    expect(closure.blocking).toEqual([live]);
    // Shared projection still produces store-status suppressed flips for
    // callers that need them (single-slice ledger); family live-set excludes
    // the parked key either way.
    expect(
      closure.terminalDispositions.some(
        (d) => d.status === "suppressed" && d.identityKey === suppressKey,
      ),
    ).toBe(true);
  });

  it("escalate → escalate action with reason/diagnosis", () => {
    expect(closeFamilyCourtFromJudgeOutput(judgeEscalate("stuck", "need owner"))).toEqual({
      action: "escalate",
      reason: "stuck",
      diagnosis: "need owner",
    });
  });

  it("negative: residual kind:cmr+findingsCount is unusable (not a closer)", () => {
    const closure = closeFamilyCourtFromJudgeOutput({
      kind: "cmr",
      findingsCount: 0,
      converged: true,
    } as never);
    expect(closure.action).toBe("unusable");
  });

  it("negative: residual positive findingsCount alone cannot open continue", () => {
    const closure = closeFamilyCourtFromJudgeOutput({
      kind: "cmr",
      findingsCount: 3,
      findings: [FINDING],
    } as never);
    expect(closure.action).toBe("unusable");
  });

  it("negative: live findings block converged (envelope consistency)", () => {
    const dispositions = [
      { identityKey: FINDING_KEY, action: "live" as const },
    ];
    expect(liveFindingsBlockConverged(dispositions)).toBe(true);
    // Topology still trusts status enum — pure check for seat self-check.
    expect(closeFamilyCourtFromJudgeOutput(judgeConverged()).action).toBe("pass");
  });

  it("projectJudgeContinueBlocking shared with single-slice", () => {
    const projected = projectJudgeContinueBlocking(
      judgeContinue([FINDING]),
    );
    expect(projected?.blockingFindingCount).toBe(1);
    expect(projected?.blockingIdentityKeys).toEqual([FINDING_KEY]);
  });

  it("S1: typed station:judge SO payload decodes to kind:judge (not open-count)", () => {
    const outcome = cmrOutcomeFromResult({
      output: {
        station: "judge",
        status: "converged",
        findingFamilies: [
          {
            family: "open-pattern",
            members: [FINDING_KEY],
            recurringFromRounds: [1],
            brief: "cargo rides",
          },
        ],
      },
    });
    expect(outcome.kind).toBe("judge");
    if (outcome.kind !== "judge") return;
    expect(outcome.status).toBe("converged");
    // S3: findingFamilies not dropped on kind:judge path.
    expect(outcome.findingFamilies?.[0]?.family).toBe("open-pattern");
  });

  it("shared unusable residual paper is the sole family residual fail-loud shape", () => {
    // #919 CR S1/N2: one helper both paths call — kind:reviewer+findingsCount:0.
    // Dead dual residualIntegratedCmrToJudgeOutput DELETED; court fail-louds
    // any non-judge (including legacy kind:cmr fixtures) as unusable.
    const paper = unusableResidualOpenCountPaper();
    expect(paper).toEqual({
      kind: "reviewer",
      findingsCount: 0,
      findings: [],
    });
    expect(closeFamilyCourtFromJudgeOutput(paper).action).toBe("unusable");
    expect(
      closeFamilyCourtFromJudgeOutput({
        kind: "cmr",
        findingsCount: 2,
        findings: [FINDING],
      } as never).action,
    ).toBe("unusable");
  });

  it("residual unusable paper (shared shape) is unusable — no coder-fix on count-minted continue", async () => {
    // #919 E / CR S1: residual fail-loud uses unusableResidualOpenCountPaper only.
    let opens = 0;
    const backend = new FamilyJudgeBackend({
      completeness: () => {
        opens += 1;
        return {
          kind: "completed",
          output: unusableResidualOpenCountPaper(),
        };
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-residual-positive",
      familyBackend: backend,
    });
    expect(result.ok).toBe(false);
    expect(result).toMatchObject({ failedStatus: "cmr_failed" });
    expect(backend.dispatches.some((d) => d.kind === "coder")).toBe(false);
    expect(opens).toBe(1);
  });

  it("S2: prior ledger row shape matches single-slice priorJudgeVerdicts", () => {
    // Family/single ledger sources differ (family events vs S3/S6 steps) but
    // the priorJudgeVerdicts landing row shape is isomorphic — both feed
    // DispatchContext.priorJudgeVerdicts with the same fields.
    const familyRows = priorFamilyJudgeVerdictRowsFromLedger(
      [
        {
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          cmrPass: "completeness",
          judgeStatus: "continue",
          sessionId: "fam-sess",
          findingDispositions: [{ identityKey: FINDING_KEY, action: "live" }],
        },
      ],
      "completeness",
    );
    const singleRows = priorJudgeVerdictRowsFromLedger([
      {
        step: "S3",
        sessionId: "slice-sess",
        output: {
          kind: "judge",
          status: "continue",
          findingDispositions: [{ identityKey: FINDING_KEY, action: "live" }],
        },
      } as LedgerEntry,
    ]);
    expect(Object.keys(familyRows[0]!).sort()).toEqual(
      Object.keys(singleRows[0]!).sort(),
    );
    expect(familyRows[0]).toMatchObject({
      status: "continue",
      sessionId: "fam-sess",
    });
    expect(singleRows[0]).toMatchObject({
      status: "continue",
      sessionId: "slice-sess",
      step: "S3",
    });
  });

  it("priorFamilyJudgeVerdictRowsFromLedger filters by pass and status", () => {
    const rows = priorFamilyJudgeVerdictRowsFromLedger(
      [
        {
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          cmrPass: "completeness",
          judgeStatus: "continue",
          sessionId: "sess-a",
          findingDispositions: [
            { identityKey: FINDING_KEY, action: "live" },
          ],
        },
        {
          status: "cmr_passed",
          event: "cmr_passed",
          cmrPass: "correctness",
          judgeStatus: "converged",
          sessionId: "sess-b",
        },
        {
          status: "cmr_reviewed",
          event: "cmr_reviewed",
          cmrPass: "completeness",
          // no judgeStatus — ignored
        },
      ],
      "completeness",
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      step: "family-cmr:completeness",
      status: "continue",
      sessionId: "sess-a",
    });
  });
});

describe("#930 runVerifyCmr family judge courts", () => {
  it("dual gates: both courts must judge-converged before ship", async () => {
    const backend = new FamilyJudgeBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    const cmrPasses = backend.dispatches
      .filter((d) => d.kind === "cmr")
      .map((d) => d.cmrPass);
    expect(cmrPasses).toEqual(["completeness", "correctness"]);
    expect(backend.prCalls).toHaveLength(1);
    expect(
      backend.ledger.filter((e) => e.status === "cmr_passed"),
    ).toHaveLength(2);
  });

  it("continue → family coder-fix with live keys only, then re-open judge", async () => {
    const backend = new FamilyJudgeBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING]), "judge-sess-c");
        }
        return completedJudge(judgeConverged(), "judge-sess-c");
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    const coder = backend.dispatches.find((d) => d.kind === "coder");
    expect(coder?.blockingFindingIdentityKeys).toEqual([FINDING_KEY]);
    expect(
      backend.ledger.some((e) => e.status === "cmr_reviewed"),
    ).toBe(true);
    expect(
      backend.ledger.some((e) => e.status === "cmr_fix_committed"),
    ).toBe(true);
  });

  it("judge escalate parks via escalateFamily (not silent terminal)", async () => {
    const backend = new FamilyJudgeBackend({
      completeness: () =>
        completedJudge(judgeEscalate("stuck", "need owner decision"), "j1"),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result.ok).toBe(false);
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]).toMatchObject({
      reason: "stuck",
      diagnosis: "need owner decision",
    });
    expect(backend.prCalls).toEqual([]);
  });

  it("persistent judge: after fix, same pass resumes session (resume shape)", async () => {
    const backend = new FamilyJudgeBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING]), "judge-sess-persist");
        }
        return completedJudge(judgeConverged(), "judge-sess-persist");
      },
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    const completenessDispatches = backend.dispatches.filter(
      (d) => d.kind === "cmr" && d.cmrPass === "completeness",
    );
    expect(completenessDispatches.length).toBeGreaterThanOrEqual(2);
    expect(completenessDispatches[0]?.session).toBe("fresh");
    expect(completenessDispatches[0]?.resumeSessionId).toBeUndefined();
    // Second opening after coder-fix resumes the same judge session.
    expect(completenessDispatches[1]?.session).toBe("resume");
    expect(completenessDispatches[1]?.resumeSessionId).toBe("judge-sess-persist");
  });

  it("session loss: fresh judge receives priorJudgeVerdicts from ledger rows", async () => {
    const backend = new FamilyJudgeBackend({
      completeness: (round, ctx) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING]), "judge-sess-lost");
        }
        // Simulate lost session: backend returns a new session id; runner
        // must have supplied priorJudgeVerdicts on a fresh (no resume) open.
        expect(ctx.priorJudgeVerdicts?.length ?? 0).toBeGreaterThan(0);
        expect(ctx.priorJudgeVerdicts?.[0]).toMatchObject({
          status: "continue",
        });
        return completedJudge(judgeConverged(), "judge-sess-new");
      },
    });
    // Force second open without resume by clearing session after first open:
    // script still gets resume from runner — we instead seed ledger-only path
    // by using a backend that omits sessionId on first open, then checks priors.
    const noSessionBackend = new FamilyJudgeBackend({
      completeness: (round, ctx) => {
        if (round === 0) {
          // No sessionId → runner cannot resume; second open is fresh + priors.
          return { kind: "completed", output: judgeContinue([FINDING]) };
        }
        expect(ctx.resumeSessionId).toBeUndefined();
        expect(ctx.priorJudgeVerdicts?.some((r) => r.status === "continue")).toBe(
          true,
        );
        return completedJudge(judgeConverged(), "judge-fresh-after-loss");
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: noSessionBackend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    void backend;
  });

  it("refuse envelope blind-routes back to family judge (not terminal / not idle)", async () => {
    const refuseRecord = {
      identityKey: FINDING_KEY,
      finding: FINDING.claim_quote,
      acceptanceCriterion: "AC-1",
      conflictReason: "unconstitutional: contradicts accepted ADR",
      reason: "unconstitutional",
      evidence: "contradicts accepted ADR 0132",
    };
    const backend = new FamilyJudgeBackend({
      completeness: (round, ctx, landing) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING]), "judge-refuse");
        }
        // Second open must see refused keys for re-ruling (ctx only — M3).
        expect(ctx.refusedFindingIdentityKeys).toEqual([FINDING_KEY]);
        // #919 M3 / #927: opaque refuseRecords land on re-open; keys not dual-written.
        expect(landing?.refuseRecords).toEqual([refuseRecord]);
        // #919 M7: landing type no longer carries refuse keys (thin ctx only).
        expect(landing).not.toHaveProperty("refusedFindingIdentityKeys");
        return completedJudge(judgeConverged(), "judge-refuse");
      },
      coder: () => ({
        kind: "completed",
        output: {
          kind: "coder",
          committed: true,
          commitsAdded: 1,
          refusedFindingIdentityKeys: [FINDING_KEY],
          refuseRecords: [refuseRecord],
        },
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.escalations).toEqual([]);
    // Completeness re-opened after refuse (not multi-iter idle / not terminal).
    expect(
      backend.dispatches.filter(
        (d) => d.kind === "cmr" && d.cmrPass === "completeness",
      ).length,
    ).toBeGreaterThanOrEqual(2);
    // Dispatch record also surfaces landing cargo for audit.
    const reopen = backend.dispatches.find(
      (d) =>
        d.kind === "cmr" &&
        d.cmrPass === "completeness" &&
        d.refusedFindingIdentityKeys !== undefined,
    );
    expect(reopen?.landing?.refuseRecords?.[0]?.reason).toBe("unconstitutional");
  });

  it("residual unusable paper (shared shape) is fail-loud (never silent clean, never coder-fix)", async () => {
    // #919 M1/M2 / CR S1: residual open-count 0 → shared unusable paper only.
    // Official typed re-furnace is seat-side SO maxRetries — runner must NOT
    // dispatch family coder-fix as a schema court, and must NOT invent clean.
    let opens = 0;
    const backend = new FamilyJudgeBackend({
      completeness: () => {
        opens += 1;
        return {
          kind: "completed",
          output: unusableResidualOpenCountPaper(),
        };
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result.ok).toBe(false);
    expect(backend.dispatches.some((d) => d.kind === "coder")).toBe(false);
    expect(backend.prCalls).toEqual([]);
    // Single court open — no re-furnace loop via coder-fix.
    expect(opens).toBe(1);
    expect(
      backend.ledger.some(
        (e) => e.status === "aborted" || e.event === "aborted",
      ),
    ).toBe(true);
  });

  it("S1: typed station:judge continues/converges without open-count decode", async () => {
    // Live production traffic is kind:judge tri-state — not findingsCount.
    // S3: findingFamilies cargo siblings ride on the judge envelope.
    let cRound = 0;
    const backend = new FamilyJudgeBackend({
      completeness: (round) => {
        cRound = round;
        if (round === 0) {
          return completedJudge(
            {
              kind: "judge",
              status: "continue",
              findingDispositions: [
                { identityKey: FINDING_KEY, action: "live" },
              ],
              findings: [FINDING],
              findingFamilies: [
                {
                  family: "open-pattern",
                  members: [FINDING_KEY],
                  recurringFromRounds: [1],
                  brief: "still open after fix",
                },
              ],
            } as JudgeResult,
            "judge-typed-live",
          );
        }
        return completedJudge(judgeConverged(), "judge-typed-live");
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(cRound).toBeGreaterThanOrEqual(1);
    expect(backend.dispatches.some((d) => d.kind === "coder")).toBe(true);
  });

  it("negative: non-judge non-cmr envelope is unusable fail-loud (not coder-fix schema court)", async () => {
    // #919 M1: bad shape → fail-loud. Seat SO re-ask owns typed re-furnace;
    // family coder-fix is not a schema tribunal.
    let opens = 0;
    const backend = new FamilyJudgeBackend({
      completeness: () => {
        opens += 1;
        return {
          kind: "completed",
          output: { kind: "fixer", committed: false },
        };
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result.ok).toBe(false);
    expect(backend.dispatches.some((d) => d.kind === "coder")).toBe(false);
    expect(backend.prCalls).toEqual([]);
    expect(opens).toBe(1);
  });

  it("M1: continue with live findings still dispatches coder-fix (unusable path only is blocked)", async () => {
    const backend = new FamilyJudgeBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING]), "live-continue");
        }
        return completedJudge(judgeConverged(), "live-continue");
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatches.some((d) => d.kind === "coder")).toBe(true);
  });

  it("M1: empty continue (0 live keys) fails loud — never empty-spins coder-fix", async () => {
    // #919 M1 / #930 AC: status:continue with empty live open set is court
    // contract drift. openFindingsForFixer may yield [] for cargo filter; that
    // does not authorize a family fix loop with zero identity keys.
    let opens = 0;
    const backend = new FamilyJudgeBackend({
      completeness: () => {
        opens += 1;
        return completedJudge(
          {
            kind: "judge",
            status: "continue",
            findingDispositions: [],
            findings: [],
          },
          "empty-continue",
        );
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result).toEqual({
      ok: false,
      ran: true,
      failedStatus: "cmr_failed",
    });
    expect(backend.dispatches.some((d) => d.kind === "coder")).toBe(false);
    expect(backend.prCalls).toEqual([]);
    expect(opens).toBe(1);
    expect(
      backend.ledger.some(
        (e) => e.status === "aborted" || e.event === "aborted",
      ),
    ).toBe(true);
  });

  it("ADR 0030 order: correctness court not opened until completeness converged", async () => {
    const backend = new FamilyJudgeBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING]), "j-c");
        }
        return completedJudge(judgeConverged(), "j-c");
      },
    });
    await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    const ordered = backend.dispatches
      .filter((d) => d.kind === "cmr")
      .map((d) => d.cmrPass);
    // Completeness may open twice (continue then pass); correctness only after.
    const firstCorrectness = ordered.indexOf("correctness");
    const lastCompleteness = ordered.lastIndexOf("completeness");
    expect(firstCorrectness).toBeGreaterThan(lastCompleteness === -1 ? -1 : 0);
    expect(ordered.slice(0, firstCorrectness).every((p) => p === "completeness")).toBe(
      true,
    );
  });

  it("#919 advanceCoder: continue + live + advance uses advanced coderFix model", async () => {
    // Default route coderFix is gpt-5.6-terra; advance to sol@med → gpt-5.6-sol.
    const backend = new FamilyJudgeBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(
            judgeContinue([FINDING], { advanceCoder: "sol@med" }),
            "judge-advance",
          );
        }
        return completedJudge(judgeConverged(), "judge-advance");
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    const coder = backend.dispatches.find((d) => d.kind === "coder");
    expect(coder?.model).toBe("gpt-5.6-sol");
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "coder_advance" || e.event === "coder_advance",
      ),
    ).toBe(true);
  });

  it("#919 advanceCoder: invalid token stay-put — original coderFix, never terminal", async () => {
    const backend = new FamilyJudgeBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(
            judgeContinue([FINDING], {
              advanceCoder: "claude-opus-not-on-roster",
            }),
            "judge-stay-put",
          );
        }
        return completedJudge(judgeConverged(), "judge-stay-put");
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    // Negative: roster failure must not end the family run.
    expect(result).toEqual({ ok: true, ran: true });
    expect(result.ok).not.toBe(false);
    const coder = backend.dispatches.find((d) => d.kind === "coder");
    // Default normal route coderFix stays gpt-5.6-terra.
    expect(coder?.model).toBe("gpt-5.6-terra");
    const stayPut = backend.ledger.filter(
      (e) =>
        e.status === "coder_advance_stay_put" ||
        e.event === "coder_advance_stay_put",
    );
    expect(stayPut.length).toBe(1);
    expect(stayPut[0]).toMatchObject({
      reason: "unknown_target",
    });
    expect(
      stayPut[0]!.message ?? stayPut[0]!.advanceCoder ?? "",
    ).toMatch(/claude-opus-not-on-roster/);
    // Verdict cargo still recorded on cmr_reviewed.
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "cmr_reviewed" &&
          e.advanceCoder === "claude-opus-not-on-roster",
      ),
    ).toBe(true);
  });

  it("#919 advanceCoder sticky: next court/fix sees advanced coderFix", async () => {
    // Round 0 advances; round 1 continue without advanceCoder; second fix must
    // still use the advanced seat (sticky outer resolvedRoute).
    const backend = new FamilyJudgeBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(
            judgeContinue([FINDING], { advanceCoder: "sol@med" }),
            "judge-sticky",
          );
        }
        if (round === 1) {
          return completedJudge(
            judgeContinue([FINDING]),
            "judge-sticky",
          );
        }
        return completedJudge(judgeConverged(), "judge-sticky");
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/919-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    const coderModels = backend.dispatches
      .filter((d) => d.kind === "coder")
      .map((d) => d.model);
    expect(coderModels.length).toBeGreaterThanOrEqual(2);
    expect(coderModels.every((m) => m === "gpt-5.6-sol")).toBe(true);
  });
});
