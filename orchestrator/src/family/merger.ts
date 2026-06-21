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
 *
 * #298: the ledger entry is written with the FULL schema (#298 acceptance-1:
 * `{childIssue, childBranch, childHead, familyHeadBefore, familyHeadAfter,
 * status}`), forwarding the SHAs the Backend's {@link MergeResult} reports. The
 * earlier thin `{childIssue, status:"merged"}` write left the ledger末条 without
 * a `familyHeadAfter` baseline, which made the crash-window reconcile branch ②
 * (补账) unreachable in production — a crash-window child would be RE-merged,
 * violating acceptance-2 "不双合" (cmr R1: codex-s1 + agy). The conflict-resolution
 * path itself is unchanged — #295's territory is the Backend's `--no-ff` merge
 * impl, NOT this ledger field set, which is #298's.
 */
export async function mergeChild(
  backend: FamilyBackend,
  request: MergeRequest,
): Promise<MergeResult> {
  const result = await backend.mergeChildIntoFamilyBase(request);
  // Ledger AFTER the merge commit is on the base (decision 5 ordering), with the
  // full schema so reconcile's branch ② baseline (`familyHeadAfter`) + landed-child
  // check (`childHead`) work in production. `recordMerged`/`compact` drop any
  // field the Backend left undefined (a #293-era Backend → thin entry, unchanged).
  await recordMerged(backend, {
    childIssue: request.childIssue,
    childBranch: request.childBranch,
    childHead: result.childHead,
    familyHeadBefore: result.familyHeadBefore,
    familyHeadAfter: result.familyHead,
  });
  return result;
}
