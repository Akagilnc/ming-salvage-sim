/**
 * verify-cmr — the family verify + integrated-cmr HOOK seam (ADR 0022 decision
 * 3④/⑥, #293 seam 4).
 *
 * #293 立 the seam ONLY: a no-op hook the family spine calls at the wave barrier
 * and after all waves merge. #296 fills it with:
 *   - the per-wave family verify (typecheck + unit tests, fail-fast — ADR 0022
 *     decision 3④: a red wave aborts before排下一波), and
 *   - the end-of-run integrated cross-model cmr (ADR 0022 decision 3⑥: the
 *     load-bearing审 that catches跨片接缝; the native pipeline has zero review).
 *
 * #293 keeps it a NO-OP so the spine wiring is proven (the hook is called and
 * returns a clean result) without pulling verify/cmr into this slice — exactly
 * the "本片不处理冲突、不跑 verify/cmr" scope (#293 = the four seams, not their
 * behaviour).
 *
 * #296 EXTENSION POINT: this module grows the real verify (run typecheck + tests
 * in the family base) and the cmr trigger; the spine keeps calling `runVerifyCmr`
 * at the same hook points, so #296 never rewrites the family main loop.
 */

/** The verify-cmr hook result. */
export interface VerifyCmrResult {
  /** Whether the (eventual #296) verify + cmr passed. #293 no-op ⇒ always true. */
  readonly ok: boolean;
  /** Whether any real verify/cmr work actually ran. #293 no-op ⇒ false. */
  readonly ran: boolean;
}

/**
 * The verify-cmr hook (#293 no-op).
 *
 * #293 returns `{ ok: true, ran: false }` unconditionally — the seam is wired,
 * nothing runs yet. #296 implements the real per-wave verify (fail-fast) and the
 * end-of-run integrated cmr behind this same signature.
 */
export async function runVerifyCmr(): Promise<VerifyCmrResult> {
  // #296 fills this: family verify (typecheck + tests) + integrated cmr.
  return { ok: true, ran: false };
}
