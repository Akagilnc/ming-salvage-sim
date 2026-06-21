/**
 * verify-cmr — the family verify + integrated-cmr HOOK seam (ADR 0022 decision
 * 3④/⑤/⑥, #293 seam 4).
 *
 * #293 立 the seam ONLY: a no-op hook the family spine calls at TWO points ADR
 * 0022 decision 3 names —
 *   - the per-wave barrier (decision 3④: run family verify, typecheck + unit
 *     tests, fail-fast — a red wave aborts BEFORE 排下一波), and
 *   - after all waves merge (decision 3⑤/⑥: the end-of-run 全量 verify + the
 *     load-bearing integrated cross-model cmr that catches 跨片接缝; the native
 *     pipeline has zero review).
 * The `phase` field tells #296 which of the two it is running.
 *
 * #293 keeps it a NO-OP so the spine wiring is proven (the hook is called at BOTH
 * points, with the context #296 needs, and the spine acts on `ok`) without
 * pulling verify/cmr into this slice — exactly the "本片不处理冲突、不跑 verify/cmr"
 * scope (#293 = the four seams, not their behaviour).
 *
 * #296 FILLS the hook body behind this SAME signature (it never rewrites the
 * family main loop — the spine already (a) passes the phase + context, (b)
 * fails-fast on `ok === false` at the wave barrier, (c) makes the failure
 * observable in the result):
 *   - "wave"  → run the family verify (typecheck + unit tests) against the family
 *     base; RED ⇒ `{ok:false}` (the spine aborts before the next wave) + an
 *     `aborted` ledger event (decision 3④/5).
 *   - "final" → run the FULL verify; green ⇒ run the integrated cross-model cmr
 *     承重闸 (decision 3⑥); converged ⇒ open the family PR (decision 4, 止于 PR) +
 *     `{ok:true}`; NOT-converged ⇒ escalate续跑 (#298) + `{ok:false}`.
 *
 * The verify / cmr / PR / abort / escalate capabilities are reached as OPTIONAL
 * methods on the injected `FamilyBackend` (the frozen spine input is `{phase,
 * familyBase, familyBackend}`). A backend that does NOT implement them — the #293
 * no-op default, the existing fakes — yields the no-op `{ok:true, ran:false}`, so
 * the spine's existing default path stays untouched. The `aborted`/escalate
 * SCHEMA (`FamilyLedgerEntry` widening + the escalate/resume machine) is #298's
 * (decision 5 "字段级 JSON 留 TDD"); #296 only CALLS those seams. THAT is the seam
 * boundary.
 */

import type {
  FamilyBackend,
  FamilyVerifyResult,
  IntegratedCmrResult,
} from "./types.js";

/** Which of the two ADR 0022 decision-3 verify points is running. */
export type VerifyCmrPhase = "wave" | "final";

/**
 * The context the verify-cmr hook needs to do its (eventual #296) work.
 *
 * #293 passes it but ignores it (no-op). #296 reads `familyBase` to run verify in
 * the family base worktree and `familyBackend` to inspect the ledger; it surfaces
 * a red wave via the returned `ok` (the spine fails-fast on it). The `aborted`
 * ledger event itself is #298's schema (the seam's `status` is `"merged"`-only
 * today — see the `familyBackend` field note).
 */
export interface VerifyCmrInput {
  /** Wave barrier (decision 3④, fail-fast) vs end-of-run (decision 3⑤/⑥). */
  readonly phase: VerifyCmrPhase;
  /** The family base branch verify runs against / cmr reviews. */
  readonly familyBase: string;
  /**
   * The family seam #296 reaches the verify / integrated-cmr / open-PR / aborted
   * / escalate capabilities through (all OPTIONAL `FamilyBackend` methods). A
   * backend missing them yields the no-op `{ok:true, ran:false}`. The CONCRETE
   * `aborted`/escalate schema (`FamilyLedgerEntry` widening + the escalate/resume
   * machine) is #298's (ADR 0022 decision 5, "字段级 JSON 留 TDD"); #296 only CALLS
   * `recordAborted` / `escalateFamily`.
   */
  readonly familyBackend: FamilyBackend;
}

/** The verify-cmr hook result. */
export interface VerifyCmrResult {
  /**
   * Whether the verify + cmr passed. The spine fails-fast when this is `false` at
   * the wave barrier (decision 3④) / returns `verify_failed` at the final barrier,
   * so #296 only RETURNS the verdict — it does not touch the spine.
   */
  readonly ok: boolean;
  /**
   * Whether any real verify/cmr work actually ran. `false` ⇒ the no-op path (the
   * backend lacks the capability — a #293-era backend), so a `{ok:true, ran:false}`
   * is honestly "nothing verified", NOT a claimed pass.
   */
  readonly ran: boolean;
}

/** The no-op verdict: the backend has no verify capability (the #293 default). */
const NOOP: VerifyCmrResult = { ok: true, ran: false };

/**
 * Run the family verify against the family base, then (on the `"final"` phase)
 * the integrated cmr 承重闸 and the open-PR step (ADR 0022 decision 3④/⑤/⑥/4).
 *
 * Reaches verify / cmr / PR / abort / escalate as OPTIONAL `FamilyBackend`
 * methods, so a backend without them degrades to the no-op `NOOP` (the spine's
 * #293 default path stays green). Surfaces a red barrier purely via the returned
 * `ok`; the spine acts on it (it is never rewritten here).
 */
export async function runVerifyCmr(
  input: VerifyCmrInput,
): Promise<VerifyCmrResult> {
  const { phase, familyBase, familyBackend } = input;

  // No verify capability ⇒ the #293 no-op path (nothing to verify; do not pretend).
  if (familyBackend.runFamilyVerify === undefined) return NOOP;

  // ── verify (both phases; "final" runs the FULL suite — a RealBackend scopes it
  //    off `phase`). RED ⇒ fail-fast: record the `aborted` event (#298 seam) so the
  //    failure is not silently dropped, and return `{ok:false}` (decision 3④/5). ──
  const verify: FamilyVerifyResult = await familyBackend.runFamilyVerify({ phase, familyBase });
  if (!verify.ok) {
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: verify.errorPackage ?? { reason: "family verify failed" },
    });
    return { ok: false, ran: true };
  }

  // The wave barrier is verify-only (decision 3④); cmr + PR are the end-of-run
  // (decision 3⑤/⑥). A green wave verify clears the wave.
  if (phase === "wave") return { ok: true, ran: true };

  // ── integrated cmr 承重闸 (decision 3⑥): only AFTER a green full verify. No cmr
  //    capability ⇒ the hook cannot claim a converged review — degrade to no-op
  //    rather than fabricate a pass (the verify still ran). ──
  if (familyBackend.runIntegratedCmr === undefined) return NOOP;
  const cmr: IntegratedCmrResult = await familyBackend.runIntegratedCmr({ familyBase });
  if (!cmr.converged) {
    // NOT converged ⇒ escalate续跑 (#298 seam); do NOT open a PR. (decision 3⑥/4)
    await familyBackend.escalateFamily?.({
      reason: cmr.reason ?? "integrated cmr did not converge",
    });
    return { ok: false, ran: true };
  }

  // ── 止于 PR (decision 4): green verify + converged cmr ⇒ open the family PR and
  //    STOP. Online bot cmr + merge to main are the separate pr-review-loop stage,
  //    NOT this layer (this never merges). No PR capability ⇒ no-op (nothing opened). ──
  if (familyBackend.openFamilyPr === undefined) return NOOP;
  await familyBackend.openFamilyPr({ familyBase });
  return { ok: true, ran: true };
}
