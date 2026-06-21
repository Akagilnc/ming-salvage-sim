/**
 * #296 — the verify-cmr HOOK BODY (ADR 0022 decision 3④/⑤/⑥/4).
 *
 * #293 立 the seam (a no-op called at the wave barrier + end-of-run, with phase +
 * context, the spine acting on `ok`). #296 fills the BODY behind that same
 * `runVerifyCmr(input)` signature — it never touches the spine call sites:
 *
 *   - "wave" phase  → family verify (typecheck + unit tests), FAIL-FAST: red ⇒
 *                     `{ok:false}` (spine aborts before the next wave) + an
 *                     `aborted` ledger event (decision 3④/5).
 *   - "final" phase → full verify, then the integrated cross-model cmr 承重闸;
 *                     cmr not-converged ⇒ escalate续跑 (#298) + `{ok:false}`;
 *                     all green ⇒ open the family PR (止于 PR, decision 4) +
 *                     `{ok:true}`.
 *
 * The verify / cmr / PR / abort / escalate capabilities are reached through the
 * `FamilyBackend` seam (the input the frozen spine passes is `{phase, familyBase,
 * familyBackend}`), as OPTIONAL methods — a backend that does not implement them
 * (the #293 no-op default) yields the no-op `{ok:true, ran:false}`, so the spine's
 * existing default path is untouched. Everything is driven by a zero-container
 * fake — no real codex / container / push.
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
  FamilyAbortedEvent,
  FamilyEscalation,
  OpenFamilyPrRequest,
  OpenFamilyPrResult,
  MergeRequest,
} from "../../src/family/types.js";

/**
 * A full family backend fake with the #296 verify/cmr/PR/abort/escalate
 * capabilities, scriptable per call. Records every interaction so the test can
 * assert what ran (no real container / codex / push).
 */
class CapableFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: OpenFamilyPrRequest[] = [];

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult;
      pr?: (req: OpenFamilyPrRequest) => OpenFamilyPrResult;
    } = {},
  ) {}

  // ── core merge/ledger seam (unchanged from #293) ──
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }

  // ── #296 verify/cmr/PR capabilities (optional methods) ──
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    return this.script.cmr?.(req) ?? { converged: true };
  }
  async openFamilyPr(req: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
    this.prCalls.push(req);
    return this.script.pr?.(req) ?? { url: `pr://${req.familyBase}` };
  }

  // ── #298-owned abort/escalate seam (minimal shapes #296 only CALLS) ──
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
  }
}

/** A #293-era backend WITHOUT the new optional methods (the no-op default). */
class BareFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `+${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
}

describe("#296 verify-cmr hook body — wave phase (fail-fast verify)", () => {
  it("GREEN wave verify → ok:true, ran:true; verify run against the family base; no abort", async () => {
    const backend = new CapableFamilyBackend({ verify: () => ({ ok: true }) });
    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    // Verify ran against the family base, scoped to the wave phase.
    expect(backend.verifyCalls).toEqual([{ phase: "wave", familyBase: "family/291-base" }]);
    // No cmr at the wave barrier (that is the final phase), no abort.
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.aborted).toEqual([]);
  });

  it("RED wave verify → ok:false (spine fails-fast), ran:true, and an `aborted` ledger event with the error package", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: false, errorPackage: { reason: "tsc: TS2322 in regionApply" } }),
    });
    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // ok:false → the spine aborts before the next wave (decision 3④).
    expect(result.ok).toBe(false);
    expect(result.ran).toBe(true);
    // The red verify writes an `aborted` event carrying the error package +
    // family base (decision 3④/5; the schema is #298's, #296 only calls it).
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("wave");
    expect(backend.aborted[0]?.familyBase).toBe("family/291-base");
    expect(backend.aborted[0]?.errorPackage.reason).toContain("TS2322");
    // No PR / cmr on a red wave.
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
  });
});

describe("#296 verify-cmr hook body — final phase (full verify → cmr → PR)", () => {
  it("GREEN full verify + CONVERGED cmr → open the family PR, ok:true ran:true (止于 PR)", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: true, ran: true });
    // Order: full verify FIRST, then cmr, then PR.
    expect(backend.verifyCalls).toEqual([{ phase: "final", familyBase: "family/291-base" }]);
    expect(backend.cmrCalls).toEqual([{ familyBase: "family/291-base" }]);
    // 止于 PR: the PR is opened (decision 4) — but NOT merged (no merge call here).
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
    expect(backend.escalations).toEqual([]);
  });

  it("RED full verify → ok:false, ran:true, aborted event, and NO cmr / NO PR (verify gates cmr)", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: false, errorPackage: { reason: "vitest: 3 failed" } }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result.ok).toBe(false);
    expect(result.ran).toBe(true);
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.phase).toBe("final");
    // cmr only runs on GREEN verify; a red final verify never reaches cmr or PR.
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
  });

  it("GREEN verify but NOT-CONVERGED cmr → escalate续跑 (#298), ok:false, ran:true, NO PR", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: false,
        reason: "field-name mismatch across slices: region.cannon vs region.cityCannon",
      }),
    });
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // Not converged → the load-bearing cmr gate is red; the spine returns
    // verify_failed (止于 PR is NOT reached).
    expect(result.ok).toBe(false);
    expect(result.ran).toBe(true);
    // Escalate续跑 (#298): #296 only CALLS the escalate seam, carrying the cmr
    // non-convergence reason.
    expect(backend.escalations).toHaveLength(1);
    expect(backend.escalations[0]?.reason).toContain("mismatch");
    // No PR while cmr is unresolved.
    expect(backend.prCalls).toEqual([]);
  });
});

describe("#296 verify-cmr hook body — graceful no-op when the backend lacks the capability", () => {
  it("a #293-era backend WITHOUT runFamilyVerify yields the no-op {ok:true, ran:false} (spine default path untouched)", async () => {
    const result = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/291-base",
      familyBackend: new BareFamilyBackend(),
    });
    expect(result).toEqual({ ok: true, ran: false });
  });

  it("a backend with verify but WITHOUT cmr (final phase) FAILS-SAFE to ok:false — it does NOT report a pass the 承重闸 never ran", async () => {
    // verify present, cmr absent: green verify, then the cmr capability is missing
    // → #296 must not throw AND must not fabricate a pass. A real verify ran, so the
    // hook cannot return the nothing-ran no-op {ok:true}; that would make the spine
    // call the run "success" with the load-bearing integrated cmr never executed
    // (decision 3⑥). It fails-safe to {ok:false, ran:true} (verify_failed at final).
    class VerifyOnlyBackend extends BareFamilyBackend {
      readonly verifyCalls: FamilyVerifyRequest[] = [];
      async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
        this.verifyCalls.push(req);
        return { ok: true };
      }
    }
    const backend = new VerifyOnlyBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    // Verify ran (ran:true), but with no cmr capability the hook reports a red
    // final barrier (ok:false) — NOT a false success.
    expect(backend.verifyCalls).toHaveLength(1);
    expect(result).toEqual({ ok: false, ran: true });
  });

  it("a backend with verify + cmr but WITHOUT openFamilyPr (final phase) FAILS-SAFE to ok:false — the terminal 止于-PR step could not run", async () => {
    // verify green + cmr converged, but the PR capability is missing → the terminal
    // action (decision 4, 止于 PR) cannot run. {ok:true} would report "success" for a
    // run whose PR never opened; fail-safe to {ok:false, ran:true} instead.
    class VerifyAndCmrBackend extends BareFamilyBackend {
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async runIntegratedCmr(): Promise<IntegratedCmrResult> {
        return { converged: true };
      }
    }
    const backend = new VerifyAndCmrBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/291-base",
      familyBackend: backend,
    });
    expect(result).toEqual({ ok: false, ran: true });
  });
});
