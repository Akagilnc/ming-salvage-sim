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
 * FULL-FIELD HAPPY-PATH WRITE. Branch ① / ② key off the ledger末条
 * `familyHeadAfter` (and branch ② confirms a landed child via its `childHead`).
 * The happy-path `merged` write now carries the full schema (`familyHeadAfter` +
 * `childHead` + …) — `merger.ts` forwards the SHAs the {@link MergeResult} reports
 * (that full-field write is #298's own acceptance-1, not #295; #295 owns only the
 * `--no-ff` conflict fallback). So in production reconcile branch ② is reachable.
 *
 * BACK-COMPAT WITH #293 THIN ENTRIES. A pre-#298 thin entry `{childIssue,
 * status:"merged"}` (no `familyHeadAfter`) stays a VALID ledger entry, and a
 * NON-EMPTY thin ledger DEGRADES SAFELY on resume: it has no `familyHeadAfter`
 * baseline → reconcile trusts the recorded merged set (those entries DO account
 * for their merged children), no补账, NO escalate — even though the live base has
 * moved past the start head (that move is the recorded merges, not a lost one). A
 * never-recorded child is left to the wave loop. The family-base-start-head
 * first-merge-crash check (below) applies ONLY to a TRULY EMPTY ledger, so a
 * non-empty thin ledger is never false-escalated (cmr R4). No corruption / no
 * double-merge either way.
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

  // ── headless ledger (no entry records a familyHeadAfter) ───────────────────
  // No `familyHeadAfter` baseline exists — EITHER a truly empty ledger OR a #293
  // thin ledger (`{childIssue, status:"merged"}` without a head). In BOTH cases a
  // merge can have landed but its `merged` write crashed (the merger lands the
  // merge THEN writes the ledger), and the absent baseline means we cannot run
  // the branch-②/③ consistency check (`isAncestor(baseline, liveHead)`). BUT the
  // PER-CHILD ancestor check is SELF-SUFFICIENT — `isAncestor(childHead, liveHead)`
  // is a direct fact about whether a child's commit is in live's history, needing
  // no baseline (cmr R5: codex-s1 + codex-s2 + agy ×3). So we run the SAME
  // per-child reconcile loop branch ② uses: every landed child is补账ed (NOT
  // re-merged — no double-merge), every unaccounted-and-unlanded child is left to
  // the wave loop. This closes the thin/empty crash-window double-merge WITHOUT
  // false-escalating a legitimately-completed thin ledger (the R3↔R4 oscillation:
  // neither "always escalate" nor "blindly trust" was right — RECONCILE PER CHILD
  // is).
  if (baseline === undefined) {
    const { reconciled, merged } = await reconcileLandedChildren(
      children,
      ledgerMerged,
      liveHead,
      git,
    );
    // Safety net for the TRULY EMPTY ledger: if the family base moved past its
    // start head yet NO child explains the move (nothing补账ed), a merge landed
    // that we cannot attribute to any known child → fail-closed escalate (decision
    // 5 真有未落/不一致 → 升级) rather than silently proceed. A non-empty thin ledger
    // whose recorded children explain the position never trips this. (For a
    // non-empty ledger the recorded entries account for the base position, so the
    // start-head check is unnecessary and would false-alarm — it is gated on
    // ledger.length === 0.)
    if (ledger.length === 0 && reconciled.length === 0) {
      const startHead = await git.familyBaseStartHead();
      if (liveHead !== startHead) {
        return { escalate: true, reconciled: [], merged: ledgerMerged, liveHead };
      }
    }
    return { escalate: false, reconciled, merged, liveHead };
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
  const { reconciled, merged } = await reconcileLandedChildren(
    children,
    ledgerMerged,
    liveHead,
    git,
  );
  return { escalate: false, reconciled, merged, liveHead };
}

/**
 * The per-child crash-window reconcile, shared by branch ② AND the headless-ledger
 * path. For each child NOT already accounted in `ledgerMerged`, ask git whether its
 * branch HEAD landed on the live family base (`isAncestor(childHead, liveHead)`):
 *
 *   - landed (ancestor-confirmed) → 补 a reconciled entry + count it merged (no
 *     double-merge). The caller writes the補账条 `status:"merged"` + `event:"reconciled"`
 *     so the unblock predicate counts it (codex R3);
 *   - childHead/branch absent (crashed before any commit) → never merged → leave
 *     OUT of `merged`, the wave loop reruns it (no error, agy R4);
 *   - childHead exists but is NOT an ancestor → genuinely unmerged → rerun.
 *
 * The check is self-sufficient (no baseline needed), which is why the headless
 * path can reuse it to recover a thin/empty-ledger crash window (cmr R5).
 */
async function reconcileLandedChildren(
  children: ReadonlyArray<ChildSlice>,
  ledgerMerged: ReadonlySet<number>,
  liveHead: string,
  git: ReconcileGit,
): Promise<{
  reconciled: Array<{ childIssue: number; childHead: string }>;
  merged: Set<number>;
}> {
  const merged = new Set(ledgerMerged);
  const reconciled: Array<{ childIssue: number; childHead: string }> = [];
  for (const child of children) {
    if (merged.has(child.issue)) continue; // already accounted (ledger-merged)
    const { exists, childHead } = await git.childHeadExists(child.issue);
    if (!exists || childHead === undefined) continue; // crashed pre-commit → rerun
    if (await git.isAncestor(childHead, liveHead)) {
      reconciled.push({ childIssue: child.issue, childHead });
      merged.add(child.issue);
    }
    // else: head exists but not an ancestor → genuinely unmerged → rerun.
  }
  return { reconciled, merged };
}
