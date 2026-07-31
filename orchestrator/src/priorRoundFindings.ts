/**
 * Prior-round finding snapshots for judge / online-review landings (#711 ledger
 * half retained after ADR 0137 removed the pattern-brief side channel).
 *
 * Runner-owned data only — topology never routes on these snapshots.
 */

import type { Finding, PriorRoundFindingSnapshot } from "./types.js";
import { findingIdentityKey } from "./findings.js";
import { cycleWindowStart } from "./family/onlineReviewLoop.js";

export type { PriorRoundFindingSnapshot } from "./types.js";

/**
 * Merge prior-round snapshots from multiple sources by round number.
 * Later sources win for the same round (e.g. in-process over ledger).
 */
export function mergePriorRoundFindings(
  ...sources: ReadonlyArray<ReadonlyArray<PriorRoundFindingSnapshot>>
): ReadonlyArray<PriorRoundFindingSnapshot> {
  const byRound = new Map<number, PriorRoundFindingSnapshot>();
  for (const source of sources) {
    for (const snap of source) {
      byRound.set(snap.round, {
        round: snap.round,
        fixMarkedFindingIdentityKeys: [...snap.fixMarkedFindingIdentityKeys],
        ...(snap.findingDispositions !== undefined
          ? { findingDispositions: snap.findingDispositions }
          : {}),
        ...(snap.blockingFindingIdentityKeys !== undefined
          ? {
              blockingFindingIdentityKeys: [
                ...snap.blockingFindingIdentityKeys,
              ],
            }
          : {}),
      });
    }
  }
  return [...byRound.values()].sort((a, b) => a.round - b.round);
}

type FamilyOnlineReviewLedgerEntry = {
  readonly status?: string;
  readonly event?: string;
  readonly onlineReviewRound?: number;
  readonly familyHeadAfter?: string;
  /** Opaque keys array when well-formed; non-array runtime junk is ignored. */
  readonly fixMarkedFindingIdentityKeys?: unknown;
};

/**
 * Prior online-review rounds from the family ledger.
 *
 * Family loop persists fix_committed markers and post-fixer verify_continued
 * markers (legal no-op continues have no fix_committed row). Later same-round
 * marker wins. Explicit empty `fixMarkedFindingIdentityKeys: []` is a real
 * later marker that clears the earlier same-round snapshot; omitted/malformed
 * field leaves prior history untouched. (`online_review_round_retrigger` is
 * legacy ledger read-only — no live writer.) History is enrichment only —
 * never Fixer packet routing.
 *
 * When `shippedAnchorHead` is set, only entries after the latest matching
 * `shipped` marker for that head are considered — prior-cycle fix_committed /
 * verify_continued findings must not seed a re-shipped head's first Verify
 * (same cycle window as fixer authorization / pending cargo).
 */
export function priorOnlineReviewFindingsFromFamilyLedger(
  ledger: ReadonlyArray<FamilyOnlineReviewLedgerEntry>,
  currentRound: number,
  opts?: {
    /** Current matching shipped anchor head — cycle window lower bound. */
    readonly shippedAnchorHead?: string;
  },
): ReadonlyArray<PriorRoundFindingSnapshot> {
  if (currentRound <= 1) return [];
  const cycleStart = cycleWindowStart(ledger, opts?.shippedAnchorHead);
  const byRound = new Map<number, PriorRoundFindingSnapshot>();
  for (let i = cycleStart; i < ledger.length; i++) {
    const entry = ledger[i]!;
    if (
      entry.event !== "online_review_fix_committed" &&
      entry.event !== "online_review_verify_continued"
    ) {
      continue;
    }
    const keys = entry.fixMarkedFindingIdentityKeys;
    // Omitted or malformed → do not touch this round (preserve prior history).
    // Explicit [] is a later marker and must overwrite/clear.
    if (!Array.isArray(keys)) continue;
    const round =
      typeof entry.onlineReviewRound === "number" &&
      Number.isSafeInteger(entry.onlineReviewRound) &&
      entry.onlineReviewRound >= 1
        ? entry.onlineReviewRound
        : undefined;
    if (round === undefined || round >= currentRound) continue;
    // Later same-round marker overwrites (Map set), including explicit empty.
    // #1145 A3: opaque keys whole-array passthrough — no element filter.
    byRound.set(round, {
      round,
      fixMarkedFindingIdentityKeys: keys,
    });
  }
  // Cleared rounds (explicit empty later marker) drop out of enrichment.
  return [...byRound.values()]
    .filter((snap) => snap.fixMarkedFindingIdentityKeys.length > 0)
    .sort((a, b) => a.round - b.round);
}



type CmrLedgerEntry = {
  readonly event?: string;
  readonly cmrPass?: string;
  readonly blockingFindingIdentityKeys?: ReadonlyArray<string>;
  readonly output?: {
    readonly kind?: string;
    readonly findings?: ReadonlyArray<Finding>;
  };
};

/** Prior integrated-CMR blocking rounds from the family ledger. */
export function priorCmrFindingsFromFamilyLedger(
  ledger: ReadonlyArray<CmrLedgerEntry>,
  cmrPass: "completeness" | "correctness",
): ReadonlyArray<PriorRoundFindingSnapshot> {
  const snapshots: PriorRoundFindingSnapshot[] = [];
  let round = 1;
  for (const entry of ledger) {
    if (
      entry.event === "cmr_reviewed" &&
      entry.cmrPass === cmrPass &&
      entry.blockingFindingIdentityKeys !== undefined &&
      entry.blockingFindingIdentityKeys.length > 0
    ) {
      snapshots.push({
        round,
        fixMarkedFindingIdentityKeys: [],
        blockingFindingIdentityKeys: [...entry.blockingFindingIdentityKeys],
      });
      round += 1;
      // Prefer explicit persisted keys over historical output fallback for the
      // same row — dual emit would invent two prior rounds for one review (#982).
      continue;
    }
    // #919 CR N3: live court paper is kind:judge; residual kind:cmr is
    // historical ledger width only (production residual is kind:reviewer).
    if (
      entry.cmrPass === cmrPass &&
      (entry.output?.kind === "judge" || entry.output?.kind === "cmr") &&
      entry.output.findings !== undefined
    ) {
      const blocking = entry.output.findings
        .filter((f) => f.action === "fix_now")
        .map((f) => findingIdentityKey(f));
      if (blocking.length > 0) {
        snapshots.push({
          round,
          fixMarkedFindingIdentityKeys: [],
          blockingFindingIdentityKeys: blocking,
        });
        round += 1;
      }
    }
  }
  return snapshots;
}
