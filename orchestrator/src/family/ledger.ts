/**
 * family-ledger — append-only merged-child event ledger (ADR 0022 decision 5,
 * #293 seam 3).
 *
 * The family ledger is the append-only event record of which child slices have
 * been merged into the family base. It lives (in the real Backend) as a sibling
 * of the family base worktree, OUTSIDE it, so a worktree clean can never touch
 * the resume / unblock truth. #293 records only the thinnest event
 * `{childIssue, status:"merged"}`; the commander's unblock predicate (ADR 0022
 * decision 6②: a child is schedulable once every blocker has a `status==="merged"`
 * ledger entry) reads the merged set this module derives.
 *
 * #298 EXTENSION POINT: the full event schema (childBranch / childHead / wave /
 * familyHeadBefore / familyHeadAfter / `aborted` events) + crash-window reconcile
 * layer HERE — by widening {@link FamilyLedgerEntry} and adding write/reconcile
 * helpers in this module. The spine only ever calls `recordMerged` / `mergedSet`,
 * so those extensions never reach into the family main loop. (#293 keeps the
 * append-only invariant but does NOT dedup — reconcile is #298.)
 */

import type { FamilyBackend, FamilyLedgerEntry } from "./types.js";

/**
 * Append one `{childIssue, status:"merged"}` event to the family ledger.
 *
 * Called by the merger AFTER a child's merge commit has landed on the family
 * base (ADR 0022 decision 5: only write the `merged` entry once the merge commit
 * is on the base). Append-only — never mutates a prior entry.
 */
export async function recordMerged(
  backend: FamilyBackend,
  childIssue: number,
): Promise<void> {
  await backend.appendFamilyLedger({ childIssue, status: "merged" });
}

/**
 * Derive the set of merged child issue numbers from the ledger entries.
 *
 * This is the unblock truth the commander reads (ADR 0022 decision 6②): a child
 * unblocks once every issue it is `blocked_by` is in this set. #293 only ever
 * writes `status:"merged"` entries, but the filter is explicit so #298's
 * `aborted` events do NOT count as merged.
 */
export function mergedSet(
  entries: ReadonlyArray<FamilyLedgerEntry>,
): ReadonlySet<number> {
  return new Set(
    entries.filter((e) => e.status === "merged").map((e) => e.childIssue),
  );
}
