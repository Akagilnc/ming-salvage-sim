/**
 * Family integrated-cmr FIX LOOP (wiki tdd-autonomous-dev §执行脊柱 Step 6 +
 * cross-model-review §修复 / §终止信号).
 *
 * The load-bearing integrated cmr is wiki ship-pre 正确性 cmr, whose discipline is
 * a **fix loop to convergence** — review → fix → re-review → … — NOT escalate on
 * the FIRST non-converged verdict. ADR 0022 decision 4 ("止于 cmr 绿 / cmr 不收敛
 * 才叫人") presupposes a convergence LOOP: "不收敛" is "tried to converge and could
 * not", not "the first round had a finding".
 *
 * The bug being fixed: `verifyCmr.ts` escalated on the FIRST non-converged cmr.
 * The fix: on a non-converged family cmr, dispatch a family coder-fix worker that
 * fixes the findings ON THE FAMILY BASE (committing), then RE-RUN the family cmr,
 * looping toward convergence. Termination is faithful to the wiki §失败/升级:
 *   - converged ⇒ ok:true (proceed to 止于 PR);
 *   - drift / no-progress (the cmr's non-convergence reason does not change across
 *     consecutive rounds) ⇒ escalate (NOT a hard round cap, NOT first-finding);
 *   - a fix worker that itself escalates / fails ⇒ escalate (cannot make progress).
 *
 * Driven entirely by a zero-container injected-seam fake (no real codex / container).
 */

import { describe, expect, it } from "vitest";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  FamilyCoderFixRequest,
  FamilyCoderFixResult,
  FamilyAbortedEvent,
  FamilyEscalation,
  OpenFamilyPrRequest,
  OpenFamilyPrResult,
  MergeRequest,
} from "../../src/family/types.js";

/**
 * A scriptable family backend exercising the fix loop via the LEGACY per-method
 * seam (`runIntegratedCmr` / `runFamilyCoderFix` / `openFamilyPr`). Each scripted
 * function is fed the call index so a test can return a different verdict per round
 * (round 0 red → fix → round 1 green, etc.).
 */
class LoopFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly fixCalls: FamilyCoderFixRequest[] = [];
  readonly prCalls: OpenFamilyPrRequest[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest, round: number) => IntegratedCmrResult;
      fix?: (req: FamilyCoderFixRequest, round: number) => FamilyCoderFixResult;
      pr?: (req: OpenFamilyPrRequest) => OpenFamilyPrResult;
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

  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    const round = this.cmrCalls.length;
    this.cmrCalls.push(req);
    return this.script.cmr?.(req, round) ?? { converged: true };
  }
  async runFamilyCoderFix(req: FamilyCoderFixRequest): Promise<FamilyCoderFixResult> {
    const round = this.fixCalls.length;
    this.fixCalls.push(req);
    return this.script.fix?.(req, round) ?? { committed: true, commitsAdded: 1 };
  }
  async openFamilyPr(req: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
    this.prCalls.push(req);
    return this.script.pr?.(req) ?? { url: `pr://${req.familyBase}` };
  }
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }
}

describe("family integrated-cmr FIX LOOP — wiki ship-pre 正确性 (Step 6, fix to converge)", () => {
  it("a non-converged THEN converged cmr runs the fix loop: cmr → fix → cmr → ok:true, NO escalate", async () => {
    const backend = new LoopFamilyBackend({
      // Round 0 red (a cross-slice finding), round 1 green (the fix landed).
      cmr: (_req, round) =>
        round === 0
          ? { converged: false, reason: "field-name mismatch: region.cannon vs region.cityCannon" }
          : { converged: true },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });

    // Converged after the fix → the gate is GREEN (止于 PR reached).
    expect(result).toEqual({ ok: true, ran: true });
    // The loop ran cmr TWICE (round 0 red, round 1 green) with a fix BETWEEN them.
    expect(backend.cmrCalls).toHaveLength(2);
    expect(backend.fixCalls).toHaveLength(1);
    // The fix worker received the round's non-convergence reason as its focus.
    expect(backend.fixCalls[0]?.reason).toContain("region.cannon");
    // It did NOT escalate on the first non-converged verdict (the bug).
    expect(backend.escalations).toEqual([]);
    // After convergence the PR opened (止于 PR, decision 4).
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
  });

  it("converges after TWO fix rounds (reason changes each round = progress): cmr → fix → cmr → fix → cmr → ok:true", async () => {
    const backend = new LoopFamilyBackend({
      cmr: (_req, round) => {
        if (round === 0) return { converged: false, reason: "seam A: type mismatch" };
        if (round === 1) return { converged: false, reason: "seam B: threshold unit drift" };
        return { converged: true };
      },
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toHaveLength(3);
    expect(backend.fixCalls).toHaveLength(2);
    expect(backend.escalations).toEqual([]);
  });

  it("DRIFT: the SAME non-convergence reason recurs (no progress) ⇒ escalate AFTER the loop, NOT on round 1", async () => {
    const SAME = "field-name mismatch: region.cannon vs region.cityCannon";
    const backend = new LoopFamilyBackend({
      // The fix never changes what the reviewer sees — same reason every round.
      cmr: () => ({ converged: false, reason: SAME }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // Could not converge → escalate (the existing escalate seam).
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("region.cannon");
    // It escalated only AFTER trying to fix — NOT on round 1 (the bug). The loop
    // dispatched at least one fix worker before judging it stuck.
    expect(backend.fixCalls.length).toBeGreaterThanOrEqual(1);
    // No PR while unresolved.
    expect(backend.prCalls).toEqual([]);
  });

  it("a fix worker that itself ESCALATES ⇒ family escalate (cannot make progress), NO PR", async () => {
    const backend = new LoopFamilyBackend({
      cmr: () => ({ converged: false, reason: "cross-slice contract drift" }),
      fix: () => ({
        committed: false,
        commitsAdded: 0,
        escalate: { reason: "finding conflicts with the epic spec", diagnosis: "needs a human design call" },
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toMatch(/conflicts with the epic spec|human design/i);
    expect(backend.prCalls).toEqual([]);
  });

  it("a CONVERGED-on-round-0 cmr never dispatches a fix worker (the happy path is unchanged)", async () => {
    const backend = new LoopFamilyBackend({ cmr: () => ({ converged: true }) });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toHaveLength(1);
    expect(backend.fixCalls).toEqual([]);
    expect(backend.escalations).toEqual([]);
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
  });
});
