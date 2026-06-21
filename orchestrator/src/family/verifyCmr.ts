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
 * #296 EXTENSION POINT: this module grows the real verify (run typecheck + tests
 * in the family base — needs `familyBase` + `familyBackend` to read/write the
 * ledger's `aborted` event) and the integrated cmr trigger, behind this SAME
 * signature. Because the spine already (a) passes the phase + context and (b)
 * fails-fast on `ok === false` at the wave barrier, #296 fills only the hook
 * body — it never rewrites the family main loop. THAT is the seam boundary.
 */

import type { FamilyBackend } from "./types.js";

/** Which of the two ADR 0022 decision-3 verify points is running. */
export type VerifyCmrPhase = "wave" | "final";

/**
 * The context the verify-cmr hook needs to do its (eventual #296) work.
 *
 * #293 passes it but ignores it (no-op). #296 reads `familyBase` to run verify in
 * the family base worktree and `familyBackend` to append the `aborted` ledger
 * event (decision 5) when a wave is red.
 */
export interface VerifyCmrInput {
  /** Wave barrier (decision 3④, fail-fast) vs end-of-run (decision 3⑤/⑥). */
  readonly phase: VerifyCmrPhase;
  /** The family base branch verify runs against / cmr reviews. */
  readonly familyBase: string;
  /** The family seam (#296 writes the `aborted` ledger event through it). */
  readonly familyBackend: FamilyBackend;
}

/** The verify-cmr hook result. */
export interface VerifyCmrResult {
  /**
   * Whether the (eventual #296) verify + cmr passed. #293 no-op ⇒ always true.
   * The spine fails-fast when this is `false` at the wave barrier (decision 3④),
   * so #296 only has to RETURN `{ ok: false }` — it does not touch the spine.
   */
  readonly ok: boolean;
  /** Whether any real verify/cmr work actually ran. #293 no-op ⇒ false. */
  readonly ran: boolean;
}

/**
 * The verify-cmr hook (#293 no-op).
 *
 * #293 returns `{ ok: true, ran: false }` unconditionally — the seam is wired
 * (called at both phases, with `input` in hand, and the spine acts on `ok`),
 * nothing runs yet. #296 implements the real per-wave verify (fail-fast) and the
 * end-of-run integrated cmr behind this same signature, reading `input`.
 */
export async function runVerifyCmr(
  _input: VerifyCmrInput,
): Promise<VerifyCmrResult> {
  // #296 fills this: per-wave family verify (typecheck + tests, fail-fast on the
  // "wave" phase) + end-of-run 全量 verify + integrated cmr (the "final" phase),
  // using `_input.familyBase` / `_input.familyBackend`.
  return { ok: true, ran: false };
}
