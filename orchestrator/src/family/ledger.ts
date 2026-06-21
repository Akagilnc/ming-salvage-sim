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
 * The full-schema fields a #298 `merged` event can carry (ADR 0022 decision 5).
 * Everything but `childIssue` is optional so the #293 thin write still validates.
 */
export interface MergedRecord {
  readonly childIssue: number;
  readonly childBranch?: string;
  readonly childHead?: string;
  readonly wave?: number;
  readonly familyHeadBefore?: string;
  readonly familyHeadAfter?: string;
  /**
   * Set to `"reconciled"` by {@link reconcileFamilyLedger} for a crash-window
   * 补账条 (a merge that landed before the live `merged` write — decision 5). The
   * entry still carries `status:"merged"` so the unblock predicate counts it
   * (codex R3); the tag is for audit. Normal merges leave this undefined.
   */
  readonly event?: "reconciled";
}

/** The fields a #298 `aborted` event (verify/cmr failure) carries. */
export interface AbortedRecord {
  readonly childIssue: number;
  readonly wave?: number;
  /** The family base HEAD at the time the barrier failed (for triage). */
  readonly familyHeadAfter?: string;
}

/**
 * Drop `undefined`-valued optional fields so the appended entry is clean
 * (`{childIssue, status}` with only the supplied extras — no `field: undefined`
 * noise, which would break `toEqual` and bloat the persisted JSONL).
 */
function compact<T extends Record<string, unknown>>(obj: T): T {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined) out[k] = v;
  }
  return out as T;
}

/**
 * Append one `merged` event to the family ledger.
 *
 * Called by the merger AFTER a child's merge commit has landed on the family
 * base (ADR 0022 decision 5: only write the `merged` entry once the merge commit
 * is on the base). Append-only — never mutates a prior entry.
 *
 * #298: accepts EITHER a bare child issue number (the #293 thin form, kept for
 * back-compat with the no-conflict merger) OR a full {@link MergedRecord} with
 * the event's full schema. The `status:"merged"` field is always stamped here.
 */
export async function recordMerged(
  backend: FamilyBackend,
  record: number | MergedRecord,
): Promise<void> {
  const r: MergedRecord =
    typeof record === "number" ? { childIssue: record } : record;
  await backend.appendFamilyLedger(
    compact({
      childIssue: r.childIssue,
      status: "merged",
      ...(r.event !== undefined ? { event: r.event } : {}),
      childBranch: r.childBranch,
      childHead: r.childHead,
      wave: r.wave,
      familyHeadBefore: r.familyHeadBefore,
      familyHeadAfter: r.familyHeadAfter,
    }) as FamilyLedgerEntry,
  );
}

/**
 * Append one `aborted` event to the family ledger (ADR 0022 decision 5: "verify/
 * cmr 失败写 aborted 事件，携带当时 family head").
 *
 * #296 calls this when a verify/cmr barrier returns red, so the family base is
 * left observably aborted (not silently a success). An `aborted` event is NOT
 * counted as merged by {@link mergedSet} — a failed child stays blocked, never
 * unblocking downstream slices off a red barrier.
 */
export async function recordAborted(
  backend: FamilyBackend,
  record: AbortedRecord,
): Promise<void> {
  await backend.appendFamilyLedger(
    compact({
      childIssue: record.childIssue,
      status: "aborted",
      wave: record.wave,
      familyHeadAfter: record.familyHeadAfter,
    }) as FamilyLedgerEntry,
  );
}

/**
 * Derive the set of merged child issue numbers from the ledger entries.
 *
 * This is the unblock truth the commander reads (ADR 0022 decision 6②): a child
 * unblocks once every issue it is `blocked_by` is in this set. The filter is on
 * `status === "merged"` ONLY, which (decision 5) means:
 *   - a live merge (`status:"merged"`) COUNTS;
 *   - a reconcile補账条 (`status:"merged"` + `event:"reconciled"`) COUNTS too —
 *     it carries `status:"merged"` precisely so the predicate counts it and the
 *     reconciled blocker's downstream child is NOT判未合死锁 (codex R3);
 *   - an `aborted` event (`status:"aborted"`) does NOT count — a child whose
 *     barrier failed stays blocked.
 */
export function mergedSet(
  entries: ReadonlyArray<FamilyLedgerEntry>,
): ReadonlySet<number> {
  return new Set(
    entries.filter((e) => e.status === "merged").map((e) => e.childIssue),
  );
}
