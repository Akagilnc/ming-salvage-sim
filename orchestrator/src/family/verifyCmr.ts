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

import {
  cmrWorkerSpec,
  dispatchFamilyWorker,
  familyShipWorkerSpec,
} from "./dispatchFamilyWorker.js";
import { recordAborted as recordDurableAbort } from "./ledger.js";
import { isFilledString } from "../shipOutcome.js";
import type {
  FamilyBackend,
  FamilyVerifyResult,
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
  /**
   * The child issue numbers whose merge into the family base was LLM-resolved
   * (#295), derived by the spine from the durable family ledger (#291 缺口 1). The
   * `"final"` phase forwards it to {@link IntegratedCmrRequest.llmResolvedChildren}
   * so the 承重闸 sees which merges a machine touched. Absent/empty ⇒ no LLM
   * resolution this run; the cmr request omits the field (the back-compat shape).
   */
  readonly llmResolvedChildren?: readonly number[];
  /**
   * The family base HEAD at the time the hook runs (#291 缺口 2), supplied by the
   * spine. On a RED barrier the hook forwards it onto BOTH the in-memory seam
   * {@link FamilyAbortedEvent.familyHeadAfter} AND the PHASE-LEVEL durable `aborted`
   * ledger entry's `familyHeadAfter`, so reconcile's "read末条 familyHeadAfter"
   * baseline covers an abort. Absent ⇒ no merge landed yet (a fresh run's first
   * barrier); the durable entry omits the head.
   */
  readonly familyHeadAfter?: string;
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
 * Dispatch a family worker, converting ANY thrown STARTUP error into a documented
 * gate result instead of letting it escape verifyCmr (cmr S336 r8 — startup/error
 * path audit). The single-slice runner wraps its S7 ship dispatch in
 * try/catch → S8(error); the family verifyCmr did NOT, so a worker that threw on
 * startup — a missing-auth `sc.run` start failure (now preflighted to a structured
 * escalate, but the worker ALSO `git checkout`s the family base + writes the focus
 * file + spins docker, any of which can still throw) — would propagate out of
 * `runVerifyCmr` and reject the WHOLE family run, bypassing the INCOMPLETE_GATE
 * fail-safe the malformed / non-completed paths already use. So catch it, record an
 * `aborted` event (decision 3⑤ "不静默吞" — the gate failure stays observable, not a
 * silent swallow), and hand back the discriminated `failed` WorkerResult the callers
 * already fail-safe to INCOMPLETE_GATE. A NON-throwing dispatch is returned
 * unchanged (escalated / completed / malformed are handled by the callers).
 */
async function dispatchOrAbort(
  familyBackend: FamilyBackend,
  spec: Parameters<typeof dispatchFamilyWorker>[1],
  ctx: Parameters<typeof dispatchFamilyWorker>[2],
  phase: VerifyCmrPhase,
  familyHeadAfter: string | undefined,
): Promise<Awaited<ReturnType<typeof dispatchFamilyWorker>>> {
  try {
    return await dispatchFamilyWorker(familyBackend, spec, ctx);
  } catch (err) {
    const reason = `family ${spec.kind} worker threw on startup: ${
      err instanceof Error ? err.message : String(err)
    }`;
    await familyBackend.recordAborted?.({
      phase,
      familyBase: ctx.familyBase!,
      errorPackage: { reason },
      familyHeadAfter,
    });
    await recordDurableAbort(familyBackend, { phase, reason, familyHeadAfter });
    return { kind: "failed", reason };
  }
}

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
  const { phase, familyBase, familyBackend, llmResolvedChildren, familyHeadAfter } =
    input;

  // No verify capability ⇒ the #293 no-op path (nothing to verify; do not pretend).
  if (familyBackend.runFamilyVerify === undefined) return NOOP;

  // ── verify (both phases; "final" runs the FULL suite — a RealBackend scopes it
  //    off `phase`). RED ⇒ fail-fast: record the `aborted` event so the failure is
  //    not silently dropped, and return `{ok:false}` (decision 3④/5). ──
  const verify: FamilyVerifyResult = await familyBackend.runFamilyVerify({ phase, familyBase });
  if (!verify.ok) {
    const reason = verify.errorPackage?.reason ?? "family verify failed";
    // (a) in-memory seam (back-compat, #296) — enriched with the abort-time head.
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: verify.errorPackage ?? { reason },
      familyHeadAfter,
    });
    // (b) PHASE-LEVEL DURABLE ledger entry (#291 缺口 2): so the abort reaches the
    //     ledger reconcile reads末条 familyHeadAfter from, not only the seam array.
    await recordDurableAbort(familyBackend, { phase, reason, familyHeadAfter });
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
  // ADR 0026 / #331: the integrated cmr is dispatched as a FAMILY cmr WORKER
  // through the unified seam (no longer the inline `runIntegratedCmr`). The
  // capability check stays: NO cmr capability ⇒ INCOMPLETE_GATE (the load-bearing
  // review cannot run; never a false pass). The capability is satisfied by EITHER
  // the new unified `dispatchWorker` seam OR the legacy `runIntegratedCmr` (the
  // dispatch helper prefers the former, forwards to the latter) — gating on the
  // legacy method ALONE would wrongly fail-safe a backend that implements ONLY the
  // new seam (codex cmr finding). #291 缺口 1: the LLM-resolved children ride on the
  // DispatchContext (OMITTED when none, the back-compat request shape).
  if (
    familyBackend.dispatchWorker === undefined &&
    familyBackend.runIntegratedCmr === undefined
  ) {
    return INCOMPLETE_GATE;
  }
  const cmrResult = await dispatchOrAbort(
    familyBackend,
    cmrWorkerSpec(),
    {
      familyBase,
      ...(llmResolvedChildren !== undefined && llmResolvedChildren.length > 0
        ? { llmResolvedChildren }
        : {}),
    },
    phase,
    familyHeadAfter,
  );
  // An ESCALATED cmr worker (model-judged stuck) is the family escalate续跑 path
  // (decision 3⑥/4) — call the escalate seam with the worker's reason, NOT a bare
  // INCOMPLETE_GATE (codex cmr R4 finding: keep escalate semantics). A
  // crash/malformed result still cannot be reported as a pass — fail-safe to
  // INCOMPLETE_GATE (decision 3⑤ "不静默吞"). #331's legacy wrapper produces neither.
  if (cmrResult.kind === "escalated") {
    await familyBackend.escalateFamily?.({
      reason: `${cmrResult.escalation.reason} — ${cmrResult.escalation.diagnosis}`,
    });
    return { ok: false, ran: true };
  }
  if (cmrResult.kind !== "completed" || cmrResult.output.kind !== "cmr") {
    return INCOMPLETE_GATE;
  }
  const cmr = cmrResult.output;
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
  // ADR 0026 / #331: 止于 PR is a FAMILY SHIP WORKER through the unified seam (no
  // longer the inline `openFamilyPr`). Capability check: the terminal action is
  // runnable via EITHER the new unified `dispatchWorker` seam OR the legacy
  // `openFamilyPr`; neither ⇒ INCOMPLETE_GATE (the PR cannot open; never a false
  // success). #331 prefactor: dispatchFamilyWorker forwards to `openFamilyPr`; #336
  // makes it invoke `gstack-ship`.
  if (
    familyBackend.dispatchWorker === undefined &&
    familyBackend.openFamilyPr === undefined
  ) {
    return INCOMPLETE_GATE;
  }
  const shipResult = await dispatchOrAbort(
    familyBackend,
    familyShipWorkerSpec(),
    { familyBase },
    phase,
    familyHeadAfter,
  );
  // An ESCALATED family ship worker (gstack-ship STOP/HITL) is the family
  // escalate续跑 path, not a false success — call the escalate seam (codex cmr R4
  // finding: keep escalate semantics). A `completed` non-ship payload / crash /
  // malformed means the PR did not open → fail-safe INCOMPLETE_GATE (decision 3⑤;
  // mirrors the cmr-stage guard above). #331's legacy wrapper produces neither.
  if (shipResult.kind === "escalated") {
    await familyBackend.escalateFamily?.({
      reason: `${shipResult.escalation.reason} — ${shipResult.escalation.diagnosis}`,
    });
    return { ok: false, ran: true };
  }
  if (shipResult.kind !== "completed" || shipResult.output.kind !== "ship") {
    return INCOMPLETE_GATE;
  }
  // ── cmr S336 r4 (P1): the terminal family gate must NOT trust the discriminant
  // alone. verifyCmr explicitly allows ANY FamilyBackend to implement the unified
  // dispatchWorker seam — a backend that implements the seam but skips the success
  // contract (the real RealFamilyBackend.dispatchShipWorker enforces it, but a
  // minimal seam-only backend need not) could return a `completed {kind:"ship"}`
  // that never opened the family PR (status:"pushed", missing/blank pr) or opened
  // it on the WRONG branch. Re-assert the family-ship contract here, fail-CLOSED
  // (defense-in-depth, independent of which backend produced the payload; mirrors
  // the non-completed/non-ship fail-safe just above). 止于 PR (decision 4) means a
  // REAL family PR on the family base: branch === familyBase, status === "pr_opened",
  // pr a non-empty string — anything else did not open the PR → INCOMPLETE_GATE.
  const ship = shipResult.output;
  if (
    ship.branch !== familyBase ||
    ship.status !== "pr_opened" ||
    !isFilledString(ship.pr)
  ) {
    return INCOMPLETE_GATE;
  }
  return { ok: true, ran: true };
}
