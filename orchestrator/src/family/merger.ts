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
 *   4. If the resolver CANNOT resolve — it throws, OR returns a result that is
 *      still `conflicted` — the merger surfaces it (propagates / throws) and NO
 *      `merged` ledger entry is written; an unresolved conflict must never look
 *      like a clean merge. The conflicting merge is left on the family base +
 *      ledger for triage, not swallowed. The resolver seam is OPTIONAL: a
 *      backend that never conflicts need not implement it, and a conflict on a
 *      resolver-less backend fails loud (never silently merges) too.
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
 * conflict-then-LLM-resolved merge records the POST-resolve SHAs). The earlier
 * thin `{childIssue, status:"merged"}` write left the ledger末条 without a
 * `familyHeadAfter` baseline, which made the crash-window reconcile branch ②
 * (补账) unreachable in production — a crash-window child would be RE-merged,
 * violating acceptance-2 "不双合" (cmr R1: codex-s1 + agy). #295's territory is
 * the conflict path; #298's is this ledger field set — they compose: the full
 * record is written once a clean OR LLM-resolved merge lands.
 */
export async function mergeChild(
  backend: FamilyBackend,
  request: MergeRequest,
): Promise<MergeResult> {
  // 1. Deterministic `git merge --no-ff` FIRST (确定性优先).
  const deterministic = await backend.mergeChildIntoFamilyBase(request);

  let result: MergeResult;
  if (deterministic.conflicted === true) {
    // 2. CONFLICT → point-LLM resolver (仅冲突才上 LLM). The resolver seam is
    //    OPTIONAL (a #293-era backend never reaches here). If a conflict IS hit
    //    on a backend without it, fail LOUD here — BEFORE the ledger write — so
    //    the conflict is surfaced, never recorded as `merged` ("不静默吞").
    if (typeof backend.resolveMergeConflict !== "function") {
      throw new Error(
        `merge conflict on child #${request.childIssue} but the family backend has no resolveMergeConflict resolver`,
      );
    }
    // A throw from the resolver propagates out of mergeChild BEFORE the ledger
    // write — an unresolved conflict is surfaced, never recorded as `merged`
    // (acceptance 3, "不静默吞").
    const resolved = await backend.resolveMergeConflict({
      childIssue: request.childIssue,
      childBranch: request.childBranch,
    });
    // The resolver returned WITHOUT throwing, but it may not have actually
    // cleared the conflict (a misbehaving / escalating backend). A still-
    // `conflicted` result MUST NOT look like a clean LLM resolution — surface it
    // BEFORE the ledger write, never record it as `merged` (invariant: "an
    // unresolved conflict must never look clean").
    if (resolved.conflicted === true) {
      throw new Error(
        `resolveMergeConflict returned a still-conflicted result for child #${request.childIssue}`,
      );
    }
    // 3. Flag the resolution so the downstream verify + cmr (#296) sees it.
    result = { ...resolved, conflictResolvedByLlm: true };
  } else {
    // Clean deterministic merge. The merger is the SOLE source of truth for
    // `conflictResolvedByLlm` (the type's contract: "Set by the merger AFTER a
    // successful resolve") — so a backend that accidentally stamped the flag on
    // a clean `mergeChildIntoFamilyBase` result must NOT leak a false
    // LLM-resolved signal downstream. Pin it to false here.
    result = { ...deterministic, conflictResolvedByLlm: false };
  }

  // 4. Ledger AFTER a clean OR LLM-resolved merge commit is on the base
  //    (decision 5 ordering). Only reached when the merge actually landed.
  //    #298: write the FULL schema, forwarding the SHAs the resolved
  //    {@link MergeResult} reports (so a conflict-then-LLM-resolved merge records
  //    the POST-resolve SHAs). `recordMerged`/`compact` drop any field the
  //    Backend left undefined (a #293-era Backend → thin entry, unchanged).
  await recordMerged(backend, {
    childIssue: request.childIssue,
    childBranch: request.childBranch,
    childHead: result.childHead,
    familyHeadBefore: result.familyHeadBefore,
    familyHeadAfter: result.familyHead,
  });
  return result;
}
