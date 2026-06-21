/**
 * reconcile — the family crash-window reconcile (ADR 0022 decision 5, #298).
 *
 * The family ledger's idempotent invariant (decision 5) is: the merger writes a
 * `merged` entry ONLY AFTER the merge commit has landed on the family base. That
 * leaves a CRASH WINDOW — the merge landed but the `merged` write had not run
 * when the process died. On resume the family run must reconcile the ledger
 * against the LIVE family-base HEAD before continuing, so it neither
 * double-merges an already-landed child nor drops one.
 *
 * The three branches ADR 0022 decision 5 names, discriminated on the ledger末条
 * `familyHeadAfter` vs the live HEAD:
 *
 *   ① equal           → trust the merged set, skip already-merged, continue.
 *   ② live HEAD LEADS  → the common crash window (a merge landed, its `merged`
 *      (live is a            write crashed). For each NOT-yet-accounted child:
 *       descendant)          - childHead exists AND is an ancestor of live HEAD
 *                              → its merge LANDED →补 a `status:"merged"` +
 *                              `event:"reconciled"` entry (counted merged, codex
 *                              R3) and do NOT re-merge it;
 *                            - childHead/branch does NOT exist (crashed before any
 *                              child commit) → skip merge-base, treat as UNMERGED
 *                              (rerun from scratch), NO error;
 *                            - childHead exists but is NOT an ancestor → genuinely
 *                              unmerged → rerun (normal, not corruption).
 *   ③ inconsistent     → live HEAD is neither equal NOR a descendant of the
 *      (diverged)            ledger末条 (diverged / behind / unrelated history) →
 *                            fail-closed escalate (do not guess).
 *
 * This is WIDER than the single-slice `checkBranchHeadConsistency` "HEAD mismatch
 * → abort": branch ② does NOT abort — it补账 and continues, which is the "幂等
 * 续合" the family layer needs (agy/codex R2). The function is PURE over the
 * injected {@link ReconcileGit} seam (no real git here) so the spine stays a thin
 * caller and the三分支 are zero-container testable.
 *
 * INTEGRATION SEAM (full-field happy-path write). Branch ① / ② key off the ledger
 * 末条 `familyHeadAfter` (and branch ② confirms a landed child via its `childHead`).
 * For reconcile to be fully effective in production, the happy-path `merged` write
 * must carry `familyHeadAfter` + `childHead` (the full schema {@link recordMerged}
 * now ACCEPTS). #293's merger still writes the thin `{childIssue, status:"merged"}`
 * — that line lives in the shared `merger.ts` (#295 territory), so forwarding the
 * full fields through it is the one wiring left to the RealBackend integration.
 * Until then, reconcile DEGRADES SAFELY on thin entries: a thin ledger has no
 * baseline → the clean-start branch returns (no escalate, no double-merge; an
 * already-merged child is still counted from `status:"merged"` and never re-run, a
 * never-recorded child is re-run by the wave loop). No corruption either way —
 * thin entries make reconcile conservative (rerun) rather than optimal (补账).
 */

import { mergedSet } from "./ledger.js";
import type {
  ChildSlice,
  FamilyLedgerEntry,
  ReconcileGit,
  ReconcilePlan,
} from "./types.js";

/**
 * Find the most recent `familyHeadAfter` recorded in the ledger — the baseline
 * the live HEAD is compared against. The LAST entry that carries one (a `merged`
 * or `aborted` event with a head); reconcile補账条 carry one too. Undefined when
 * no entry records a head (an empty ledger, or only #293-thin entries).
 */
function lastRecordedHead(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const after = ledger[i]!.familyHeadAfter;
    if (after !== undefined) return after;
  }
  return undefined;
}

/**
 * Build the reconcile plan from the ledger + the live family-base HEAD.
 *
 * @param ledger    the append-only family-ledger entries, in write order.
 * @param children  the epic's child slices (to know which children to account).
 * @param git       the injected git seam (live HEAD / childHead existence /
 *                  ancestor) — a fake in tests, the RealBackend in production.
 */
export async function reconcileFamilyLedger(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  children: ReadonlyArray<ChildSlice>,
  git: ReconcileGit,
): Promise<ReconcilePlan> {
  const ledgerMerged = mergedSet(ledger);
  const baseline = lastRecordedHead(ledger);
  const liveHead = await git.liveFamilyHead();

  // ── branch ① ledger末条 === live HEAD ──────────────────────────────────────
  // The last recorded head IS the live head: no merge landed past the ledger →
  // trust the merged set, no补账, no escalate. (An empty ledger with no recorded
  // head is the degenerate clean-start case handled below.)
  if (baseline !== undefined && baseline === liveHead) {
    return { escalate: false, reconciled: [], merged: ledgerMerged, liveHead };
  }

  // ── empty / headless ledger: distinguish a fresh start from a FIRST-merge
  //    crash window ────────────────────────────────────────────────────────────
  // No entry records a head. That is EITHER a genuine fresh start (nothing
  // merged yet) OR the very-first-merge crash window: the merger lands the merge
  // on the family base THEN writes the ledger, so a crash in between leaves the
  // ledger EMPTY while the family base HAS moved (cmr R3: codex-s1). With no
  // ledger末条 baseline we cannot attribute the landed merge to a child, so we
  // fall back to the family-base START head:
  //   - live HEAD === start head → nothing landed → genuine fresh start (clean).
  //   - live HEAD !== start head → a merge landed but was never recorded →
  //     fail-closed escalate (decision 5 真有未落/不一致 → 升级). An unconditional
  //     clean-start here would re-run + re-merge the already-landed first child
  //     (a double-merge), violating acceptance-2 不双合.
  if (baseline === undefined) {
    const startHead = await git.familyBaseStartHead();
    if (liveHead === startHead) {
      return { escalate: false, reconciled: [], merged: ledgerMerged, liveHead };
    }
    return { escalate: true, reconciled: [], merged: ledgerMerged, liveHead };
  }

  // ── branch ② vs ③: is the live HEAD a DESCENDANT of the ledger末条? ─────────
  // `isAncestor(baseline, liveHead)` true ⇒ live HEAD is ahead of the recorded
  // head on the SAME history (the crash window: a merge landed past the ledger).
  // false ⇒ the live HEAD diverged / went backwards / is unrelated → branch ③
  // fail-closed escalate (do not guess which merges are real).
  const liveLeads = await git.isAncestor(baseline, liveHead);
  if (!liveLeads) {
    return { escalate: true, reconciled: [], merged: ledgerMerged, liveHead };
  }

  // ── branch ②: reconcile each not-yet-accounted child against the live HEAD ──
  const merged = new Set(ledgerMerged);
  const reconciled: Array<{ childIssue: number; childHead: string }> = [];
  for (const child of children) {
    if (merged.has(child.issue)) continue; // already accounted (ledger-merged)
    const { exists, childHead } = await git.childHeadExists(child.issue);
    if (!exists || childHead === undefined) {
      // Crashed before any commit for this child → never merged → rerun from
      // scratch (leave it OUT of `merged`). No error (agy R4).
      continue;
    }
    if (await git.isAncestor(childHead, liveHead)) {
      // Its merge LANDED before the crash →补 a reconciled entry + count merged
      // (no double-merge). The补账条 is written status:"merged" by the caller via
      // recordMerged({..., event:"reconciled"}) so the unblock predicate counts
      // it (codex R3).
      reconciled.push({ childIssue: child.issue, childHead });
      merged.add(child.issue);
    }
    // else: childHead exists but its merge did not land (not an ancestor) →
    // genuinely unmerged → rerun (leave it OUT of `merged`). Normal, not
    // corruption.
  }

  return { escalate: false, reconciled, merged, liveHead };
}
