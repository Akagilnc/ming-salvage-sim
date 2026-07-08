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
 *       descendant)          - childHead exists, is not already ancestor-or-equal
 *                              to the effective base head, AND is an ancestor of
 *                              live HEAD
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
 * This is WIDER than the removed single-slice HEAD-equality resume gate ("HEAD mismatch
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
 * status:"merged"}` (no `familyHeadAfter`) stays a VALID merged-set row so we do
 * not double-merge already-recorded children. But when the live family base has
 * advanced past the recorded start head, a headless row explains that advance only
 * if it carries a `childHead` that is still an ancestor of live. A bare thin row
 * is still visible in the returned merged set for audit, but the plan fail-closes
 * before scheduling can trust it.
 */

import { isMergedAccountingEntry, mergedSet } from "./ledger.js";
import type {
  ChildSlice,
  FamilyLedgerEntry,
  ReconcileGit,
  ReconcilePlan,
} from "./types.js";

/**
 * Find the most recent `familyHeadAfter` recorded in the ledger — the baseline
 * the live HEAD is compared against — AND its index. The LAST entry that carries
   * one (a `merged`, `aborted`, `cmr_reviewed`, `cmr_fix_committed`, `cmr_passed`,
   * `shipped`, or `review_loop_converged` event with a head); the baseline-advancing
   * reconcile 補账条
   * carries one too. Returns `{head: undefined, index: -1}` when no entry records a
   * head (an empty ledger, or only #293-thin entries).
 *
 * The INDEX matters because the reconcile-append loop advances the baseline only on
 * the LAST補账条 (cmr R2): a mid-loop crash can leave HEADLESS `status:"merged"` tail
 * entries (carrying a `childHead` but no `familyHeadAfter`) AFTER this baseline. Those
 * tail entries are NOT covered by the baseline, so branch ① must re-verify them
 * against live before trusting them (cmr R6).
 */
function lastRecordedHead(ledger: ReadonlyArray<FamilyLedgerEntry>): {
  head: string | undefined;
  index: number;
  invalid: boolean;
} {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    const after = entry.familyHeadAfter;
    if (after !== undefined) {
      if (!isValidRecordedHeadEntry(entry)) {
        return { head: undefined, index: i, invalid: true };
      }
      return { head: after, index: i, invalid: false };
    }
  }
  return { head: undefined, index: -1, invalid: false };
}

function hasNonBlankFamilyHeadAfter(entry: FamilyLedgerEntry): boolean {
  return (
    typeof entry.familyHeadAfter === "string" &&
    entry.familyHeadAfter.trim().length > 0
  );
}

function isValidRecordedHeadEntry(entry: FamilyLedgerEntry): boolean {
  if (!hasNonBlankFamilyHeadAfter(entry)) return false;
  if (entry.status === "merged") return isMergedAccountingEntry(entry);
  if (entry.status === "aborted") {
    return entry.event === "aborted" && (entry.phase === "wave" || entry.phase === "final");
  }
  if (entry.status === "cmr_passed") {
    return (
      entry.event === "cmr_passed" &&
      entry.phase === "final" &&
      (entry.cmrPass === "completeness" || entry.cmrPass === "correctness") &&
      typeof entry.routeFingerprint === "string" &&
      entry.routeFingerprint.trim().length > 0
    );
  }
  if (entry.status === "cmr_reviewed" || entry.status === "cmr_fix_committed") {
    return (
      entry.event === entry.status &&
      entry.phase === "final" &&
      (entry.cmrPass === "completeness" || entry.cmrPass === "correctness")
    );
  }
  if (entry.status === "escalated") {
    return (
      entry.event === "escalated" &&
      entry.phase === "final" &&
      (entry.escalationKind === "decision" || entry.escalationKind === "failure")
    );
  }
  if (entry.status === "shipped") {
    return (
      entry.event === "shipped" &&
      entry.phase === "final" &&
      typeof entry.pr === "string" &&
      entry.pr.trim().length > 0
    );
  }
  if (entry.status === "review_loop_converged") {
    return (
      entry.event === "review_loop_converged" &&
      entry.phase === "final" &&
      typeof entry.pr === "string" &&
      entry.pr.trim().length > 0
    );
  }
  return false;
}

/**
 * Branch ① guard (cmr R6): when the baseline-bearing entry's head equals live, the
 * baseline itself is consistent — but HEADLESS `status:"merged"` entries recorded
 * AFTER it (intermediate reconcile補账条 from a mid-append crash: a `childHead`, no
 * `familyHeadAfter`) are NOT covered by that equality. If the family base was rewound
 * to the baseline, such a tail entry's merge is no longer in live history, and
 * trusting it would漏合. Re-verify each such tail entry's `childHead` is still an
 * ancestor of live. Returns false (→ caller escalates) if any headless merged tail
 * entry lacks a `childHead` or whose `childHead` is no longer an ancestor of live.
 * Entries up to and including `baselineIndex`, and any `aborted` entries, are not
 * re-checked (the baseline equality already vouches for the base position).
 */
async function headlessTailIsConsistent(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  baselineIndex: number,
  liveHead: string,
  startHead: string,
  git: ReconcileGit,
): Promise<boolean> {
  for (let i = baselineIndex + 1; i < ledger.length; i++) {
    const entry = ledger[i]!;
    // Only merged entries that lack their own familyHeadAfter are "uncovered" by
    // the baseline. (An aborted tail entry does not count as merged; a tail entry
    // that DOES carry familyHeadAfter would have been the baseline.)
    if (entry.status !== "merged" || entry.familyHeadAfter !== undefined) continue;
    if (!isMergedAccountingEntry(entry)) return false;
    // A headless merged entry with no childHead cannot be verified → fail-closed.
    if (entry.childHead === undefined) return false;
    if (await git.isAncestor(entry.childHead, startHead)) return false;
    if (!(await git.isAncestor(entry.childHead, liveHead))) return false;
  }
  return true;
}

async function verifyHeadlessAccountingRows(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  liveHead: string,
  baseHead: string,
  git: ReconcileGit,
): Promise<{ consistent: boolean; hasVerified: boolean }> {
  let hasVerified = false;
  for (const entry of ledger) {
    if (!isMergedAccountingEntry(entry)) continue;
    if (entry.familyHeadAfter !== undefined) continue;
    if (entry.childHead === undefined) {
      return { consistent: false, hasVerified };
    }
    if (await git.isAncestor(entry.childHead, baseHead)) {
      return { consistent: false, hasVerified };
    }
    if (!(await git.isAncestor(entry.childHead, liveHead))) {
      return { consistent: false, hasVerified };
    }
    hasVerified = true;
  }
  return { consistent: true, hasVerified };
}

/**
 * Build the reconcile plan from the ledger + the live family-base HEAD.
 *
 * @param ledger    the append-only family-ledger entries, in write order.
 * @param children  the epic's child slices (to know which children to account).
 *                  INTENTIONALLY the spine's POST-refetch `epic.children` (ADR 0022
 *                  decision 4 重抓 live GitHub metadata 重建依赖图): reconcile
 *                  accounts only children that exist in the LIVE epic — the live
 *                  truth is deliberately coupled here (#291 缺口 4, codex2 LOW). So
 *                  if a refetch DROPPED a child (a human removed it from the epic
 *                  while escalated), reconcile does NOT补账 / re-run that child — it
 *                  is no longer part of the family, by design. No deeper change.
 * @param git       the injected git seam (live HEAD / childHead existence /
 *                  ancestor) — a fake in tests, the RealBackend in production.
 */
export async function reconcileFamilyLedger(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  children: ReadonlyArray<ChildSlice>,
  git: ReconcileGit,
): Promise<ReconcilePlan> {
  const ledgerMerged = mergedSet(ledger);
  const { head: baseline, index: baselineIndex, invalid: invalidBaseline } =
    lastRecordedHead(ledger);
  const liveHead = await git.liveFamilyHead();
  if (invalidBaseline) {
    return { escalate: true, reconciled: [], merged: ledgerMerged, liveHead };
  }

  // ── branch ① ledger末条 === live HEAD ──────────────────────────────────────
  // The baseline-bearing entry's head IS the live head: no merge landed past it.
  // Trust the merged set — BUT first re-verify any HEADLESS `status:"merged"` tail
  // entries recorded AFTER the baseline (intermediate reconcile補账条 from a mid-
  // append crash carry a `childHead` but no `familyHeadAfter`, so they sit past the
  // baseline and are NOT covered by `baseline === liveHead`). If the family base was
  // externally rewound to this baseline, such a tail entry's merge is no longer in
  // live history; blindly trusting it would漏合 (cmr R6: codex-s1). Re-check each
  // tail entry's `childHead` is still an ancestor of live; any missing or non-ancestor
  // → fail-closed escalate (do not silently skip a child whose merge is gone).
  if (baseline !== undefined && baseline === liveHead) {
    const startHead = await git.familyBaseStartHead();
    if (await headlessTailIsConsistent(ledger, baselineIndex, liveHead, startHead, git)) {
      return { escalate: false, reconciled: [], merged: ledgerMerged, liveHead };
    }
    return { escalate: true, reconciled: [], merged: ledgerMerged, liveHead };
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
    const startHead = await git.familyBaseStartHead();
    const headlessAccounting = await verifyHeadlessAccountingRows(
      ledger,
      liveHead,
      startHead,
      git,
    );
    if (!headlessAccounting.consistent) {
      return { escalate: true, reconciled: [], merged: ledgerMerged, liveHead };
    }

    const { reconciled, merged } = await reconcileLandedChildren(
      children,
      ledgerMerged,
      liveHead,
      startHead,
      git,
    );
    // Safety net for a headless ledger: after every existing headless merged row
    // has been individually verified, still fail closed if the family base moved
    // past its start head and NO child explains the move (nothing补账ed, and no
    // verified accounting row exists).
    if (
      reconciled.length === 0 &&
      !headlessAccounting.hasVerified
    ) {
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
    baseline,
    git,
  );
  return { escalate: false, reconciled, merged, liveHead };
}

/**
 * The per-child crash-window reconcile, shared by branch ② AND the headless-ledger
 * path. For each child NOT already accounted in `ledgerMerged`, ask git whether its
 * branch HEAD landed on the live family base (`!isAncestor(childHead, baseHead)`
 * AND `isAncestor(childHead, liveHead)`):
 *
 *   - landed (non-base ancestor-confirmed) → 补 a reconciled entry + count it
 *     merged (no double-merge). The caller writes the補账条 `status:"merged"` +
 *     `event:"reconciled"` so the unblock predicate counts it (codex R3);
 *   - childHead/branch absent (crashed before any commit) → never merged → leave
 *     OUT of `merged`, the wave loop reruns it (no error, agy R4);
 *   - childHead exists but is already ancestor-or-equal to the effective base head
 *     → branch exists but has no post-base child commit yet → rerun;
 *   - childHead exists but is NOT an ancestor → genuinely unmerged → rerun.
 *
 * The check is self-sufficient (no baseline needed), which is why the headless
 * path can reuse it to recover a thin/empty-ledger crash window (cmr R5).
 */
async function reconcileLandedChildren(
  children: ReadonlyArray<ChildSlice>,
  ledgerMerged: ReadonlySet<number>,
  liveHead: string,
  baseHead: string,
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
    if (await git.isAncestor(childHead, baseHead)) continue; // branch has no post-base child commit
    if (await git.isAncestor(childHead, liveHead)) {
      reconciled.push({ childIssue: child.issue, childHead });
      merged.add(child.issue);
    }
    // else: head exists but not an ancestor → genuinely unmerged → rerun.
  }
  return { reconciled, merged };
}
