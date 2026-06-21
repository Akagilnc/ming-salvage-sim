/**
 * merger — thin serial `git merge --no-ff` orchestrator (ADR 0022 decision 3②,
 * #293 seam 2).
 *
 * The family integration of an already-committed child branch into the family
 * base is a branch-to-branch merge — the Sandcastle library has NO such原语
 * (`merge-to-head` is a slice/run-level回灌, used inside one coder run, NOT this).
 * So the merger is a DETERMINISTIC `git merge --no-ff` behind the
 * {@link FamilyBackend} seam, with point-LLM conflict resolution layered on
 * LATER — not the native "整段 LLM solves any conflict" approach.
 *
 * #293 did ONLY the no-conflict happy path: merge one reviewed child branch into
 * the family base, then write its `merged` ledger entry (ADR 0022 decision 5:
 * the entry is written ONLY after the merge commit has landed). #295 LAYERS the
 * conflict fallback HERE — without rewriting the family spine, which only ever
 * calls `mergeChild`:
 *
 *   1. DETERMINISTIC `git merge --no-ff` first (`mergeChildIntoFamilyBase`) —
 *      省额度、可重放. This is the inversion of Sandcastle's native "一上来就整段
 *      LLM" merge (ADR 0022 Considered Options「merger 照搬原生整段 LLM」= 否决).
 *   2. ONLY when that deterministic merge reports a conflict
 *      (`MergeResult.conflicted`) do we route to the POINT-LLM resolver
 *      `resolveMergeConflict` (an agent under the `merger` soul + the
 *      `resolving-merge-conflicts` skill — see prompts/merger_resolve_conflict.md).
 *      "仅冲突才上 LLM" (acceptance 2).
 *   3. The LLM resolution is NEVER silent: the returned result is flagged
 *      `conflictResolvedByLlm` so the downstream family verify + integrated cmr
 *      (#296) can审 it ("不静默吞", acceptance 3). The merged ledger entry is
 *      written ONLY AFTER a clean OR an LLM-resolved merge lands (decision 5).
 *   4. If the resolver CANNOT resolve (throws), the error propagates and NO
 *      `merged` ledger entry is written — an unresolved conflict must never look
 *      like a clean merge. The conflicting merge is left on the family base +
 *      ledger for triage, not swallowed.
 */

import { recordMerged } from "./ledger.js";
import type { FamilyBackend, MergeRequest, MergeResult } from "./types.js";

/**
 * Merge one reviewed child branch into the family base, then record it.
 *
 * Order matters (ADR 0022 decision 5 + the family ledger's idempotent
 * invariant): the `merged` ledger entry is written ONLY AFTER the merge commit
 * lands on the family base. So we await a clean (or LLM-resolved) merge FIRST,
 * THEN append the ledger entry.
 *
 * #295 conflict fallback: the deterministic merge runs first; on a conflict the
 * point-LLM resolver runs ("仅冲突才上 LLM"); the result is flagged
 * `conflictResolvedByLlm` so it is observable downstream ("不静默吞"). A resolver
 * that throws propagates WITHOUT writing the ledger entry.
 */
export async function mergeChild(
  backend: FamilyBackend,
  request: MergeRequest,
): Promise<MergeResult> {
  // 1. Deterministic `git merge --no-ff` FIRST (确定性优先).
  const deterministic = await backend.mergeChildIntoFamilyBase(request);

  let result: MergeResult;
  if (deterministic.conflicted === true) {
    // 2. CONFLICT → point-LLM resolver (仅冲突才上 LLM). A throw here propagates
    //    out of mergeChild BEFORE the ledger write — an unresolved conflict is
    //    surfaced, never recorded as `merged` (acceptance 3, "不静默吞").
    const resolved = await backend.resolveMergeConflict({
      childIssue: request.childIssue,
      childBranch: request.childBranch,
    });
    // 3. Flag the resolution so the downstream verify + cmr (#296) sees it.
    result = { ...resolved, conflictResolvedByLlm: true };
  } else {
    result = deterministic;
  }

  // 4. Ledger AFTER a clean OR LLM-resolved merge commit is on the base
  //    (decision 5 ordering). Only reached when the merge actually landed.
  await recordMerged(backend, request.childIssue);
  return result;
}
