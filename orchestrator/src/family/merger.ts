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
 * #293 does ONLY the no-conflict happy path: merge one reviewed child branch into
 * the family base, then write its `merged` ledger entry (ADR 0022 decision 5:
 * the entry is written ONLY after the merge commit has landed). #295 EXTENSION
 * POINT: the conflict fallback (`resolving-merge-conflicts` soul on a conflicting
 * merge) layers HERE — by extending the Backend's merge implementation and this
 * module's handling of a conflict result — NOT by rewriting the family spine,
 * which only ever calls `mergeChild`.
 */

import { recordMerged } from "./ledger.js";
import type { FamilyBackend, MergeRequest, MergeResult } from "./types.js";

/**
 * Merge one reviewed child branch into the family base, then record it.
 *
 * Order matters (ADR 0022 decision 5 + the family ledger's idempotent
 * invariant): the `merged` ledger entry is written ONLY AFTER the merge commit
 * lands on the family base. So we await the merge first, THEN append the ledger
 * entry. #293's no-conflict path never throws mid-merge; #295 adds the
 * conflict-detection + fallback before the ledger write.
 */
export async function mergeChild(
  backend: FamilyBackend,
  request: MergeRequest,
): Promise<MergeResult> {
  const result = await backend.mergeChildIntoFamilyBase(request);
  // Ledger AFTER the merge commit is on the base (decision 5 ordering).
  await recordMerged(backend, request.childIssue);
  return result;
}
