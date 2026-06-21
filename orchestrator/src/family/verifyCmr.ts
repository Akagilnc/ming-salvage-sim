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
 * familyBase, familyBackend}`). A backend that implements NONE of them — the #293
 * no-op default, the existing fakes — has no `runFamilyVerify`, so the hook returns
 * the nothing-ran no-op `{ok:true, ran:false}` and the spine's existing default
 * path stays untouched (zero regression). A backend that CAN verify but is missing
 * a required downstream final-barrier capability (cmr / PR) is the DIFFERENT case:
 * a real verify ran, so the hook fails-safe to `{ok:false, ran:true}` rather than a
 * false `success` — see `INCOMPLETE_GATE` below. The `aborted`/escalate SCHEMA
 * (`FamilyLedgerEntry` widening + the escalate/resume machine) is #298's (decision
 * 5 "字段级 JSON 留 TDD"); #296 only CALLS those seams. THAT is the seam boundary.
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
   * backend with NO `runFamilyVerify` yields the nothing-ran no-op `{ok:true,
   * ran:false}`; one that verifies green but lacks a required downstream capability
   * fails-safe to `{ok:false, ran:true}` (see `INCOMPLETE_GATE`). The CONCRETE
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
 * The fail-safe verdict for a backend that DID verify (green) but is missing a
 * REQUIRED downstream final-barrier capability (the integrated cmr 承重闸, or the
 * 止于-PR step after a converged cmr). It is NOT the #293 no-op: a real verify
 * already ran, so reporting `{ok:true}` would make the spine's `finalize()` treat
 * the final barrier as PASSED and the run as `"success"` — shipping code the
 * load-bearing integrated cmr never reviewed (decision 3⑥) / a run whose terminal
 * PR (decision 4) never opened. The spine ignores `ran` and acts on `ok` alone, so
 * the only fail-safe is `ok:false` (the run surfaces `verify_failed`/`failedPhase:
 * "final"`, never a false `success` — decision 3⑤ "不静默吞"). `ran:true` records
 * that real verify work DID happen (this is not the nothing-ran no-op).
 */
const INCOMPLETE_GATE: VerifyCmrResult = { ok: false, ran: true };

/**
 * Run the family verify against the family base, then (on the `"final"` phase)
 * the integrated cmr 承重闸 and the open-PR step (ADR 0022 decision 3④/⑤/⑥/4).
 *
 * Reaches verify / cmr / PR / abort / escalate as OPTIONAL `FamilyBackend`
 * methods: a backend with NO verify capability degrades to the nothing-ran `NOOP`
 * (the spine's #293 default path stays green); one that verifies green but lacks a
 * required downstream capability fails-safe to `INCOMPLETE_GATE` (never a false
 * success). Surfaces a red barrier purely via the returned
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
  //    capability ⇒ the hook CANNOT run the load-bearing review, so it must NOT
  //    report a pass: a real verify already ran, and `{ok:true}` here would make
  //    the spine's finalize() call the run `"success"` with the 承重闸 never run.
  //    Fail-safe to `ok:false` (verify_failed) — NOT the #293 nothing-ran no-op. ──
  if (familyBackend.runIntegratedCmr === undefined) return INCOMPLETE_GATE;
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
  //    NOT this layer (this never merges). No PR capability ⇒ the terminal action
  //    cannot run; verify + cmr already ran, so `{ok:true}` would report `"success"`
  //    for a run whose PR never opened — fail-safe to `ok:false` (NOT the no-op). ──
  if (familyBackend.openFamilyPr === undefined) return INCOMPLETE_GATE;
  await familyBackend.openFamilyPr({ familyBase });
  return { ok: true, ran: true };
}
