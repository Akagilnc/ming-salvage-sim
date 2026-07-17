/**
 * merger — thin serial `git merge --no-ff` orchestrator (ADR 0022 decision 3②,
 * #293 seam 2). Family Integration Merge Action entry (#934 ID-010 / #938).
 *
 * The family integration of an already-committed child branch into the family
 * base is a branch-to-branch merge — the Sandcastle library has NO such原语
 * (`merge-to-head` is a slice/run-level回灌, used inside one coder run, NOT this).
 * So the merger is a DETERMINISTIC `git merge --no-ff` behind the
 * {@link FamilyBackend} seam, with point-LLM conflict resolution layered on
 * LATER — not the native "整段 LLM solves any conflict" approach.
 *
 *   1. DETERMINISTIC `git merge --no-ff` first (`mergeChildIntoFamilyBase`) —
 *      省额度、可重放.
 *   2. ONLY when that deterministic merge reports a conflict
 *      (`MergeResult.conflicted`) do we route to the POINT-LLM resolver
 *      `resolveMergeConflict` (an agent under the `merger` soul + the
 *      `resolving-merge-conflicts` skill — see prompts/merger_resolve_conflict.md).
 *      Production/test contract guarantees the resolver exists (ID-010).
 *   3. The LLM resolution is NEVER silent: the returned result is flagged
 *      `conflictResolvedByLlm` so the downstream family verify + integrated cmr
 *      (#296) can审 it ("不静默吞"). The merged ledger entry is written ONLY AFTER
 *      a clean OR an LLM-resolved merge lands (decision 5).
 *   4. #938 / ID-010: the Action converges the merger worker's completed/raise
 *      outcome once — no host still-conflicted re-dispatch court / mechanical
 *      cap. Process-root transport retry lives inside the worker dispatch leg
 *      (ID-004), not here.
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
 *
 * #298: that ledger entry is written with the FULL schema (#298 acceptance-1:
 * `{childIssue, childBranch, childHead, familyHeadBefore, familyHeadAfter,
 * status}`), forwarding the SHAs the resolved {@link MergeResult} reports (so a
 * conflict-then-LLM-resolved merge records the POST-resolve SHAs).
 */
export async function mergeChild(
  backend: FamilyBackend,
  request: MergeRequest,
): Promise<MergeResult> {
  // 1. Deterministic `git merge --no-ff` FIRST (确定性优先).
  const deterministic = await backend.mergeChildIntoFamilyBase(request);

  let result: MergeResult;
  if (deterministic.conflicted === true) {
    // 2. CONFLICT → point-LLM resolver (仅冲突才上 LLM). Production/test contract
    //    guarantees resolveMergeConflict (ID-010); process-root transport retry
    //    is owned by the worker dispatch leg inside that method, not by a host
    //    still-conflicted re-dispatch loop here.
    const resolved = await backend.resolveMergeConflict!({
      childIssue: request.childIssue,
      childBranch: request.childBranch,
      ...(request.runId !== undefined ? { runId: request.runId } : {}),
      ...(request.modelRoute !== undefined ? { modelRoute: request.modelRoute } : {}),
    });
    // Structured raise / still-conflicted completed outcome: converge once.
    if (resolved.escalation !== undefined) return resolved;
    if (resolved.conflicted === true) return resolved;
    // 3. Flag the resolution so the downstream verify + cmr (#296) sees it.
    result = { ...resolved, conflictResolvedByLlm: true };
  } else {
    // Clean deterministic merge. The merger is the SOLE source of truth for
    // `conflictResolvedByLlm` — pin false so a backend stamp cannot leak.
    result = { ...deterministic, conflictResolvedByLlm: false };
  }

  // 4. Ledger AFTER a clean OR LLM-resolved merge commit is on the base
  //    (decision 5 ordering). Only reached when the merge actually landed.
  await recordMerged(backend, {
    childIssue: request.childIssue,
    childBranch: request.childBranch,
    childHead: result.childHead,
    familyHeadBefore: result.familyHeadBefore,
    familyHeadAfter: result.familyHead,
    ...(result.conflictResolvedByLlm === true
      ? { conflictResolvedByLlm: true }
      : {}),
  });
  return result;
}
