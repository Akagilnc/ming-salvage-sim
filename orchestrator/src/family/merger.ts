/**
 * Family Integration Merge Action entry (#293 / #934 ID-010 / #938).
 *
 * Deterministic `git merge --no-ff` first; only real conflicts call the merger
 * worker (`resolveMergeConflict`). Production/test contract guarantees the
 * resolver. The Action converges completed/raise once — no host still-conflicted
 * re-dispatch court (process-root retry is ID-004 inside the worker leg).
 * Ledger write only after a clean or LLM-resolved merge lands (decision 5).
 */

import { recordMerged } from "./ledger.js";
import type { FamilyBackend, MergeRequest, MergeResult } from "./types.js";

/** Merge one reviewed child branch into the family base, then record it. */
export async function mergeChild(
  backend: FamilyBackend,
  request: MergeRequest,
): Promise<MergeResult> {
  const deterministic = await backend.mergeChildIntoFamilyBase(request);

  let result: MergeResult;
  if (deterministic.conflicted === true) {
    // Required seam (#934 ID-010 / #938): no optional `?` + non-null assert.
    const resolved = await backend.resolveMergeConflict({
      childIssue: request.childIssue,
      childBranch: request.childBranch,
      ...(request.runId !== undefined ? { runId: request.runId } : {}),
      ...(request.modelRoute !== undefined ? { modelRoute: request.modelRoute } : {}),
    });
    if (resolved.escalation !== undefined) return resolved;
    if (resolved.conflicted === true) return resolved;
    result = { ...resolved, conflictResolvedByLlm: true };
  } else {
    result = { ...deterministic, conflictResolvedByLlm: false };
  }

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
