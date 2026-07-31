/**
 * Family PR review-loop orchestration helpers (#600 / #940 / #1145).
 *
 * Runner-side glue dispatches **Collector then Verify** as independent Actions
 * and routes only on Verify's three-state disposition
 * (`converged | continue | escalate`). GitHub query, wait, retrigger, and
 * evidence assembly are owned exclusively by the Collector worker; judgment +
 * side effects by Verify. Runner never host-polls GH or interprets bot/CI/
 * finding semantics (#1145). No mechanical round cap, no empty-success from
 * counts (#934 ID-012).
 *
 * Verify→Fixer transport is a single opaque packet field-passthrough: Runner
 * copies Verify cargo keys/threads as-is and never filters dispositions,
 * accumulates old findings, or overwrites `isRecheck`.
 */

import {
  BOT_POLL_INTERVAL_MS,
} from "../botPolling.js";
import {
  convergenceHeadToRecord,
} from "../evidenceAdmissibility.js";
import type {
  FixerResult,
  OnlineReviewLandingSnapshot,
  OnlineReviewTerminalState,
  ShipResult,
  VerifyResult,
  WorkerLandingPayload,
} from "../types.js";
import { fixerEnvelopeFixCommitSha } from "../reviewLoopOutcome.js";
import type { StopSummary } from "../stopSummary.js";
import { decisionGateParkStopSummary } from "../stopSummary.js";
import { stageFailureStopSummary } from "./familyTerminal.js";

export const ONLINE_REVIEW_LANDING_FILE = ".orchestrator-online-review.json";
export const SANDBOX_ONLINE_REVIEW_PATH_ENV = "ORCHESTRATOR_ONLINE_REVIEW_PATH";

/**
 * #940 / #934 ID-012 — host-visible judge disposition for online review.
 * Derived only from the verify worker's typed status fields; findings counts
 * are opaque cargo and never consulted.
 */
export type OnlineReviewJudgeDisposition =
  | "converged"
  | "continue"
  | "escalate";

export function onlineReviewJudgeDisposition(
  verify: VerifyResult,
): OnlineReviewJudgeDisposition {
  if (verify.terminalState === "decision_gate_raised") return "escalate";
  if (verify.converged) return "converged";
  return "continue";
}

export type { OnlineReviewTerminalState } from "../types.js";

/**
 * 1-based online review round from the family ledger (#600 r26 / #1145 resume).
 * Live phase markers (preferred):
 *   - collector / fixer_completed / fix_committed / mergeable → that round
 *   - verify_continued(N) → N+1 (next Collector cycle; side effects already done)
 * Legacy read-only width (no live writer / host poll / compatibility route):
 *   - online_review_round_retrigger(R) → R (old protocol: next round to enter)
 *   - fix_committed without onlineReviewRound → count+1 (old protocol)
 * Legal no-op continues advance without a new commit and still write later
 * Collector checkpoints.
 */
export function onlineReviewRoundFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly onlineReviewRound?: number;
  }>,
): number {
  let maxRound = 0;
  let legacyFixCount = 0;
  for (const entry of entries) {
    const hasRound =
      typeof entry.onlineReviewRound === "number" &&
      Number.isSafeInteger(entry.onlineReviewRound) &&
      entry.onlineReviewRound >= 1;
    const round = hasRound ? entry.onlineReviewRound : undefined;
    const liveSameRound =
      (entry.status === "online_review_collector_completed" &&
        entry.event === "online_review_collector_completed") ||
      (entry.status === "online_review_fixer_completed" &&
        entry.event === "online_review_fixer_completed") ||
      (entry.status === "online_review_fix_committed" &&
        entry.event === "online_review_fix_committed") ||
      (entry.status === "online_review_mergeable" &&
        entry.event === "online_review_mergeable");
    if (liveSameRound) {
      if (round !== undefined) {
        maxRound = Math.max(maxRound, round);
      } else if (
        entry.status === "online_review_fix_committed" &&
        entry.event === "online_review_fix_committed"
      ) {
        // Pre-round-field fix markers: old protocol counted completed fixes.
        legacyFixCount += 1;
      }
      continue;
    }
    // Post-fixer Verify continue is durable proof round N is done → start N+1.
    if (
      entry.status === "online_review_verify_continued" &&
      entry.event === "online_review_verify_continued" &&
      round !== undefined
    ) {
      maxRound = Math.max(maxRound, round + 1);
      continue;
    }
    // Legacy retrigger read-only: marker stores the next round to enter.
    if (
      entry.status === "online_review_round_retrigger" &&
      entry.event === "online_review_round_retrigger" &&
      round !== undefined
    ) {
      maxRound = Math.max(maxRound, round);
    }
  }
  if (legacyFixCount > 0) {
    maxRound = Math.max(maxRound, legacyFixCount + 1);
  }
  return maxRound > 0 ? maxRound : 1;
}

/** Last family online-review fix HEAD — ship/fix SHA bookkeeping for Collector post-fix landing head (#1145). */
export function lastOnlineReviewFixCommitShaFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly familyHeadAfter?: string;
  }>,
): string | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status === "online_review_fix_committed" &&
      entry.event === "online_review_fix_committed" &&
      typeof entry.familyHeadAfter === "string" &&
      entry.familyHeadAfter.length > 0
    ) {
      return entry.familyHeadAfter;
    }
  }
  return undefined;
}

/**
 * Latest fix SHA belonging to the review cycle anchored at `shipHead` (#1145).
 *
 * Cycle starts after the latest `shipped` marker whose `familyHeadAfter` equals
 * `shipHead`. Prior-cycle fixer SHAs (before that anchor) must not override a
 * newly shipped head; in-cycle fixer SHAs after the anchor remain effective
 * after a crash. When no matching shipped anchor exists (direct stage tests),
 * the whole ledger is the cycle window.
 */
export function lastInCycleOnlineReviewFixCommitShaFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly familyHeadAfter?: string;
  }>,
  shipHead: string,
): string | undefined {
  const head = typeof shipHead === "string" ? shipHead.trim() : "";
  if (head.length === 0) return undefined;

  let cycleStart = 0;
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status === "shipped" &&
      entry.event === "shipped" &&
      typeof entry.familyHeadAfter === "string" &&
      entry.familyHeadAfter.trim() === head
    ) {
      cycleStart = i + 1;
      break;
    }
  }

  for (let i = entries.length - 1; i >= cycleStart; i--) {
    const entry = entries[i]!;
    if (
      entry.status === "online_review_fix_committed" &&
      entry.event === "online_review_fix_committed" &&
      typeof entry.familyHeadAfter === "string" &&
      entry.familyHeadAfter.trim().length > 0
    ) {
      return entry.familyHeadAfter.trim();
    }
  }
  return undefined;
}

/**
 * Effective reviewed head for the current online-review cycle (#1145 F1).
 * Prefer an in-cycle fixer SHA; otherwise the ship head that opened the cycle.
 */
export function effectiveOnlineReviewHeadFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly familyHeadAfter?: string;
  }>,
  shipHead: string,
): string {
  const ship = typeof shipHead === "string" ? shipHead.trim() : "";
  const inCycle = lastInCycleOnlineReviewFixCommitShaFromFamilyLedger(
    entries,
    ship,
  );
  return inCycle !== undefined && inCycle.length > 0 ? inCycle : ship;
}

function authorizationFromLedgerEntry(entry: {
  readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
  readonly fixMarkedFindingThreads?: ReadonlyArray<{
    readonly identityKey?: string;
    readonly threadId?: string;
  }>;
}): {
  readonly fixMarkedFindingIdentityKeys: ReadonlyArray<string>;
  readonly fixMarkedFindingThreads: ReadonlyArray<{
    readonly identityKey: string;
    readonly threadId: string;
  }>;
} {
  return {
    fixMarkedFindingIdentityKeys: (entry.fixMarkedFindingIdentityKeys ?? []).filter(
      (key) => typeof key === "string" && key.trim().length > 0,
    ),
    // Opaque Verify packet — byte-for-byte / shape-for-shape. Never reconstruct
    // or drop extended/malformed business bindings into empty work (#1145).
    fixMarkedFindingThreads: Array.isArray(entry.fixMarkedFindingThreads)
      ? (entry.fixMarkedFindingThreads as ReadonlyArray<{
          readonly identityKey: string;
          readonly threadId: string;
        }>)
      : [],
  };
}

/**
 * Rebuild the last fixer authorization from durable phase markers (#1145).
 * Prefer latest verify_continued / fixer_completed / fix_committed — no-op
 * continues have no fix_committed row.
 *
 * When `shippedAnchorHead` is set, only entries after the latest matching
 * `shipped` marker for that head are considered — prior-cycle thread bindings
 * must not seed a re-shipped head that has no current-cycle pending cargo.
 */
export function lastFixMarkedFindingAuthorizationFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly familyHeadAfter?: string;
    readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
    readonly fixMarkedFindingThreads?: ReadonlyArray<{
      readonly identityKey?: string;
      readonly threadId?: string;
    }>;
  }>,
  opts?: {
    /** Current matching shipped anchor head — cycle window lower bound. */
    readonly shippedAnchorHead?: string;
  },
): {
  readonly fixMarkedFindingIdentityKeys: ReadonlyArray<string>;
  readonly fixMarkedFindingThreads: ReadonlyArray<{
    readonly identityKey: string;
    readonly threadId: string;
  }>;
} {
  let cycleStart = 0;
  const anchor =
    typeof opts?.shippedAnchorHead === "string"
      ? opts.shippedAnchorHead.trim()
      : "";
  if (anchor.length > 0) {
    for (let i = entries.length - 1; i >= 0; i--) {
      const entry = entries[i]!;
      if (
        entry.status === "shipped" &&
        entry.event === "shipped" &&
        typeof entry.familyHeadAfter === "string" &&
        entry.familyHeadAfter.trim() === anchor
      ) {
        cycleStart = i + 1;
        break;
      }
    }
  }
  for (let i = entries.length - 1; i >= cycleStart; i--) {
    const entry = entries[i]!;
    const live =
      (entry.status === "online_review_verify_continued" &&
        entry.event === "online_review_verify_continued") ||
      (entry.status === "online_review_fixer_completed" &&
        entry.event === "online_review_fixer_completed") ||
      (entry.status === "online_review_fix_committed" &&
        entry.event === "online_review_fix_committed");
    if (!live) continue;
    return authorizationFromLedgerEntry(entry);
  }
  return {
    fixMarkedFindingIdentityKeys: [],
    fixMarkedFindingThreads: [],
  };
}

/**
 * Action-owned Collector checkpoint for durable resume (#1145 AC2).
 * Returns the latest completed Collector cargo handle/body for `round`.
 * Opaque only — no field structure gate (ADR 0131 cargo≠fate).
 * When `currentHead` is provided, only a checkpoint bound to that exact head
 * short-circuits (re-ship at a new head must re-run Collector).
 *
 * Bound to the current shipped PR cycle (same window as mergeable / fixer auth):
 * - current PR identity match when both marker and current PR are known
 * - marker must not precede the latest matching `shipped` anchor for that head
 *
 * A replacement/re-opened PR at identical SHA + same global round therefore
 * re-runs Collector instead of feeding the old PR's evidence to Verify.
 * Runner/stage never interprets evidence semantics.
 */
export function lastCollectorCheckpointFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly onlineReviewRound?: number;
    readonly cargoPointer?: string;
    readonly collectorEvidenceCargo?: OnlineReviewLandingSnapshot;
    readonly familyHeadAfter?: string;
    readonly pr?: string;
    readonly rawReviewerArtifacts?: WorkerLandingPayload["rawReviewerArtifacts"];
  }>,
  round: number,
  currentHead?: string,
  opts?: {
    /** Current ship PR identity — replacement PR at same SHA must not short-circuit. */
    readonly currentPr?: string;
    /** Current matching shipped anchor head — cycle window lower bound. */
    readonly shippedAnchorHead?: string;
  },
):
  | {
      readonly cargoPointer?: string;
      readonly evidence?: OnlineReviewLandingSnapshot;
      readonly artifacts?: NonNullable<
        WorkerLandingPayload["rawReviewerArtifacts"]
      >;
    }
  | undefined {
  if (!Number.isSafeInteger(round) || round < 1) return undefined;
  const head =
    typeof currentHead === "string" && currentHead.trim().length > 0
      ? currentHead.trim()
      : undefined;
  const currentPr =
    typeof opts?.currentPr === "string" && opts.currentPr.trim().length > 0
      ? opts.currentPr.trim()
      : undefined;
  let cycleStart = 0;
  const anchor =
    typeof opts?.shippedAnchorHead === "string"
      ? opts.shippedAnchorHead.trim()
      : "";
  // Prefer explicit anchor; otherwise the effective/current head opens the cycle.
  const anchorHead = anchor.length > 0 ? anchor : head;
  if (anchorHead !== undefined && anchorHead.length > 0) {
    for (let i = entries.length - 1; i >= 0; i--) {
      const entry = entries[i]!;
      if (
        entry.status === "shipped" &&
        entry.event === "shipped" &&
        typeof entry.familyHeadAfter === "string" &&
        entry.familyHeadAfter.trim() === anchorHead
      ) {
        cycleStart = i + 1;
        break;
      }
    }
  }
  for (let i = entries.length - 1; i >= cycleStart; i--) {
    const entry = entries[i]!;
    if (
      entry.status !== "online_review_collector_completed" ||
      entry.event !== "online_review_collector_completed"
    ) {
      continue;
    }
    if (entry.onlineReviewRound !== round) continue;
    if (head !== undefined) {
      const storedHead =
        typeof entry.familyHeadAfter === "string" &&
        entry.familyHeadAfter.trim().length > 0
          ? entry.familyHeadAfter.trim()
          : undefined;
      // Head-bound resume only — missing/mismatched head is not a safe skip.
      if (storedHead === undefined || storedHead !== head) continue;
    }
    if (currentPr !== undefined) {
      const storedPr =
        typeof entry.pr === "string" && entry.pr.trim().length > 0
          ? entry.pr.trim()
          : undefined;
      // Marker without PR / non-canonical mismatch — fail-closed (#1145).
      if (!onlineReviewPrIdentityEquals(storedPr, currentPr)) continue;
    }
    const cargoPointer =
      typeof entry.cargoPointer === "string" && entry.cargoPointer.length > 0
        ? entry.cargoPointer
        : undefined;
    const evidence = entry.collectorEvidenceCargo;
    const hasBody =
      evidence !== undefined &&
      typeof evidence === "object" &&
      evidence !== null;
    const raw =
      entry.rawReviewerArtifacts !== undefined &&
      typeof entry.rawReviewerArtifacts === "object" &&
      entry.rawReviewerArtifacts !== null
        ? entry.rawReviewerArtifacts
        : undefined;
    // Statement-alone is not readable paper — only restore when a path/session
    // pointer exists (empty checkpoints must stay empty).
    const artifacts =
      raw !== undefined &&
      ((typeof raw.stdoutPath === "string" && raw.stdoutPath.trim().length > 0) ||
        (typeof raw.sidecarPath === "string" &&
          raw.sidecarPath.trim().length > 0) ||
        (typeof raw.reviewerSessionId === "string" &&
          raw.reviewerSessionId.trim().length > 0))
        ? raw
        : undefined;
    // Completed marker is enough — empty opaque cargo is a legal checkpoint
    // (ADR 0131 cargo≠fate). Reader returns {} so Verify-crash re-entry does
    // not redispatch / re-wait Collector. Raw artifact pointers ride the same
    // opaque transport for Verify-crash resume when body/handle are absent.
    return {
      ...(cargoPointer !== undefined ? { cargoPointer } : {}),
      ...(hasBody ? { evidence } : {}),
      ...(artifacts !== undefined ? { artifacts } : {}),
    };
  }
  return undefined;
}

/**
 * Action-owned mergeable completion checkpoint (#1145 re-entry).
 * When Verify has already converged (side effects done), re-entry must not
 * re-dispatch Verify and replay reply/resolve/defer external effects.
 *
 * Bound to the current shipped PR cycle AND effective reviewed head:
 * - exact current-head match
 * - current PR identity match when both marker and current PR are known
 * - marker must not precede the latest matching `shipped` anchor for that head
 *
 * A replacement/re-opened PR at identical SHA therefore runs Collector→Verify.
 */
export function lastOnlineReviewMergeableFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly onlineReviewRound?: number;
    readonly familyHeadAfter?: string;
    readonly pr?: string;
  }>,
  currentHead: string | undefined,
  opts?: {
    /** Current ship PR identity — replacement PR at same SHA must not short-circuit. */
    readonly currentPr?: string;
    /** Current matching shipped anchor head — cycle window lower bound. */
    readonly shippedAnchorHead?: string;
  },
): { readonly round: number; readonly familyHeadAfter: string } | undefined {
  const head =
    typeof currentHead === "string" && currentHead.trim().length > 0
      ? currentHead.trim()
      : undefined;
  if (head === undefined) return undefined;
  const currentPr =
    typeof opts?.currentPr === "string" && opts.currentPr.trim().length > 0
      ? opts.currentPr.trim()
      : undefined;
  let cycleStart = 0;
  const anchor =
    typeof opts?.shippedAnchorHead === "string"
      ? opts.shippedAnchorHead.trim()
      : "";
  // Prefer explicit anchor; otherwise the effective/current head opens the cycle.
  const anchorHead = anchor.length > 0 ? anchor : head;
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status === "shipped" &&
      entry.event === "shipped" &&
      typeof entry.familyHeadAfter === "string" &&
      entry.familyHeadAfter.trim() === anchorHead
    ) {
      cycleStart = i + 1;
      break;
    }
  }
  for (let i = entries.length - 1; i >= cycleStart; i--) {
    const entry = entries[i]!;
    if (
      entry.status !== "online_review_mergeable" ||
      entry.event !== "online_review_mergeable"
    ) {
      continue;
    }
    const storedHead =
      typeof entry.familyHeadAfter === "string" &&
      entry.familyHeadAfter.trim().length > 0
        ? entry.familyHeadAfter.trim()
        : undefined;
    // No head on marker (legacy) or head mismatch → not a safe short-circuit.
    if (storedHead === undefined || storedHead !== head) {
      continue;
    }
    if (currentPr !== undefined) {
      const storedPr =
        typeof entry.pr === "string" && entry.pr.trim().length > 0
          ? entry.pr.trim()
          : undefined;
      // Marker without PR / non-canonical mismatch — fail-closed (#1145).
      if (!onlineReviewPrIdentityEquals(storedPr, currentPr)) {
        continue;
      }
    }
    const round =
      typeof entry.onlineReviewRound === "number" &&
      Number.isSafeInteger(entry.onlineReviewRound) &&
      entry.onlineReviewRound >= 1
        ? entry.onlineReviewRound
        : 1;
    return { round, familyHeadAfter: storedHead };
  }
  return undefined;
}

/**
 * Pending Fixer cargo for same-round Verify resume (#1145 post-fixer seam).
 * Returns opaque fixerResult when fixer_completed(round) exists and has not
 * been consumed by a later mergeable(round) or verify_continued(round).
 * Legal no-op (no SHA) is first-class cargo — never gated on committed.
 *
 * When `shippedAnchorHead` is set, only entries after the latest matching
 * `shipped` marker for that head are considered — prior-cycle unconsumed
 * same-round cargo must not override a re-shipped head (#1145 cycle bound).
 */
export function lastPendingFixerCargoFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly onlineReviewRound?: number;
    readonly familyHeadAfter?: string;
    readonly pr?: string;
    readonly fixerResultCargo?: FixerResult;
    readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
    readonly fixMarkedFindingThreads?: ReadonlyArray<{
      readonly identityKey?: string;
      readonly threadId?: string;
    }>;
  }>,
  round: number,
  opts?: {
    /** Current matching shipped anchor head — cycle window lower bound. */
    readonly shippedAnchorHead?: string;
    /**
     * Current bound PR identity (#1145 P2). When set, only markers whose `pr`
     * canonical-equals this id count — replacement PR must not resume prior
     * ticket's fixer cargo. Missing marker pr = fail-closed skip.
     */
    readonly currentPr?: string;
  },
):
  | {
      readonly fixerResult: FixerResult;
      readonly fixMarkedFindingIdentityKeys: ReadonlyArray<string>;
      readonly fixMarkedFindingThreads: ReadonlyArray<{
        readonly identityKey: string;
        readonly threadId: string;
      }>;
    }
  | undefined {
  if (!Number.isSafeInteger(round) || round < 1) return undefined;

  let cycleStart = 0;
  const anchor =
    typeof opts?.shippedAnchorHead === "string"
      ? opts.shippedAnchorHead.trim()
      : "";
  if (anchor.length > 0) {
    for (let i = entries.length - 1; i >= 0; i--) {
      const entry = entries[i]!;
      if (
        entry.status === "shipped" &&
        entry.event === "shipped" &&
        typeof entry.familyHeadAfter === "string" &&
        entry.familyHeadAfter.trim() === anchor
      ) {
        cycleStart = i + 1;
        break;
      }
    }
  }

  const currentPr =
    typeof opts?.currentPr === "string" && opts.currentPr.trim().length > 0
      ? opts.currentPr.trim()
      : undefined;

  const prMatches = (entry: { readonly pr?: string }): boolean => {
    if (currentPr === undefined) return true;
    const storedPr =
      typeof entry.pr === "string" && entry.pr.trim().length > 0
        ? entry.pr.trim()
        : undefined;
    return onlineReviewPrIdentityEquals(storedPr, currentPr);
  };

  let pendingIdx = -1;
  let pending: FixerResult | undefined;
  let pendingAuth:
    | {
        readonly fixMarkedFindingIdentityKeys: ReadonlyArray<string>;
        readonly fixMarkedFindingThreads: ReadonlyArray<{
          readonly identityKey: string;
          readonly threadId: string;
        }>;
      }
    | undefined;
  for (let i = cycleStart; i < entries.length; i++) {
    const entry = entries[i]!;
    if (entry.onlineReviewRound !== round) continue;
    if (
      entry.status === "online_review_fixer_completed" &&
      entry.event === "online_review_fixer_completed" &&
      entry.fixerResultCargo !== undefined &&
      entry.fixerResultCargo.kind === "fixer"
    ) {
      if (!prMatches(entry)) continue;
      pendingIdx = i;
      pending = entry.fixerResultCargo;
      pendingAuth = authorizationFromLedgerEntry(entry);
      continue;
    }
    if (pendingIdx < 0) continue;
    // Later same-round consumption of the fixer cargo (same PR only).
    if (
      ((entry.status === "online_review_mergeable" &&
        entry.event === "online_review_mergeable") ||
        (entry.status === "online_review_verify_continued" &&
          entry.event === "online_review_verify_continued")) &&
      prMatches(entry)
    ) {
      pendingIdx = -1;
      pending = undefined;
      pendingAuth = undefined;
    }
  }
  if (pending === undefined || pendingAuth === undefined) return undefined;
  return {
    fixerResult: pending,
    fixMarkedFindingIdentityKeys: pendingAuth.fixMarkedFindingIdentityKeys,
    fixMarkedFindingThreads: pendingAuth.fixMarkedFindingThreads,
  };
}

/** Stop summary for the verifier's explicit decision-gate signal. */
export function onlineReviewDecisionGateStopSummary(): StopSummary {
  return decisionGateParkStopSummary({
    summary:
      "online review verifier raised an explicit decision-gate signal",
    repairHint:
      "answer the decision gate, then rerun the online review loop",
  });
}

type OnlineReviewDispatchPhase = "collector" | "verify" | "fixer";

/** Stop summary when collector/verify/fixer dispatch throws (#600 r20 / #1145). */
export function onlineReviewDispatchFailureStopSummary(
  phase: OnlineReviewDispatchPhase,
  err: unknown,
): StopSummary {
  const detail = err instanceof Error ? err.message : String(err);
  const label =
    phase === "collector"
      ? "collector dispatch"
      : phase === "verify"
        ? "verify dispatch"
        : "fixer dispatch";
  return stageFailureStopSummary({
    status: "online_review_failed",
    summary: `online review ${label} failed: ${detail}`,
    repairHint:
      "repair the online review loop infrastructure failure and rerun the online review loop",
  });
}

function decisionGateFromDispatchInfra(
  reviewedPr: string,
  round: number,
  phase: OnlineReviewDispatchPhase,
  err: unknown,
): OnlineReviewLoopStageResult {
  return boundOnlineReviewLoopResult(reviewedPr, {
    ok: false,
    terminalState: "decision_gate_raised",
    round,
    stopSummary: onlineReviewDispatchFailureStopSummary(phase, err),
  });
}

/** In-band terminal for family review-loop dispatch failures. */
export class OnlineReviewLoopTerminal extends Error {
  constructor(readonly result: OnlineReviewLoopStageResult) {
    super(`online review loop terminal: ${result.terminalState}`);
    this.name = "OnlineReviewLoopTerminal";
  }
}

/**
 * Head key for the family review landing. Prefer snapshot/post-fix truth over
 * the original shipped PR head once a fix round occurred.
 */
function convergenceHeadForLanding(input: {
  readonly postFixCommitSha?: string;
  readonly snapshotHeadOid?: string;
  readonly branchHeadAfter?: string;
  readonly shipPrHead?: string;
}): string | undefined {
  return convergenceHeadToRecord({
    shipHead: input.shipPrHead,
    snapshotHead: input.snapshotHeadOid,
    postFixHead: input.postFixCommitSha,
    branchHeadAfter: input.branchHeadAfter,
  });
}

/**
 * Explicit Collector post-fix transition fact (#1145).
 * True only when a committed-fixer head actually advances the effective
 * reviewed head — never from SHA presence alone, evidence body, disposition
 * cargo, or round arithmetic. Stage owns one-shot set/consume.
 */
export function postFixTransitionFromCommittedFixerResumeMarker(input: {
  readonly previousEffectiveHead?: string;
  readonly committedFixerHead?: string;
}): boolean {
  const next =
    typeof input.committedFixerHead === "string"
      ? input.committedFixerHead.trim()
      : "";
  if (next.length === 0) return false;
  const prev =
    typeof input.previousEffectiveHead === "string"
      ? input.previousEffectiveHead.trim()
      : "";
  return next !== prev;
}

/**
 * Reconstruct unconsumed post-fix one-shot from ledger (#1145).
 *
 * True when `committedFixHead` is non-empty and no Collector checkpoint has
 * been written bound to that head yet. A crash after fix_committed (or
 * committed fixer_completed) and before the new-head Collector checkpoint must
 * re-trigger once; after that checkpoint it must not. SHA equality alone is
 * not enough — lastFixSha already equals the new head on that resume path.
 */
export function postFixTransitionUnconsumedFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly familyHeadAfter?: string;
  }>,
  committedFixHead: string | undefined,
): boolean {
  const head =
    typeof committedFixHead === "string" ? committedFixHead.trim() : "";
  if (head.length === 0) return false;
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status === "online_review_collector_completed" &&
      entry.event === "online_review_collector_completed" &&
      typeof entry.familyHeadAfter === "string" &&
      entry.familyHeadAfter.trim() === head
    ) {
      return false;
    }
  }
  return true;
}

/** Base landing before the Online Review Action assembles evidence (#1145). */
export function buildOnlineReviewBaseLanding(
  ship: ShipResult,
  round: number,
  postFixCommitSha?: string,
  /**
   * One-shot stage fact: true only for the Collector that immediately follows
   * an effective-head move. Caller clears after that dispatch.
   */
  postFixTransition?: boolean,
): WorkerLandingPayload {
  const prHead = convergenceHeadForLanding({
    shipPrHead: ship.prHead,
    postFixCommitSha,
  });
  return {
    shipDelivery: {
      branch: ship.branch,
      pr: ship.pr,
      ...(prHead !== undefined && prHead.length > 0 ? { prHead } : {}),
      ...(ship.status !== undefined ? { status: ship.status } : {}),
    },
    onlineReviewRound: round,
    ...(postFixTransition === true ? { postFixTransition: true } : {}),
  };
}

export interface BotPollClock {
  sleep(ms: number): void | Promise<void>;
}

export const realBotPollClock: BotPollClock = {
  sleep(ms: number) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  },
};

export const immediateBotPollClock: BotPollClock = {
  sleep() {},
};

/**
 * Family pending-CI re-poll delay.
 * Under Vitest use the immediate clock so unit tests do not wall-clock sleep.
 * Production uses real 2-minute cadence between pending-CI polls (#934 ID-004:
 * CI pending is not on the bot overdue window — no finite host-fail budget).
 *
 * Used by Landing Action CI wait — not by Online Review Runner host polling
 * (host poll path deleted in #1145).
 */
export async function sleepPendingCiPollInterval(
  clock?: BotPollClock,
): Promise<void> {
  const resolved =
    clock ??
    (process.env.VITEST !== undefined ? immediateBotPollClock : realBotPollClock);
  await resolved.sleep(BOT_POLL_INTERVAL_MS);
}

/**
 * Online Review Collector Action result (#1145).
 * Opaque evidence handle/body only — never judge enum. Runner transports as-is
 * without reading body fields (ADR 0131). Sparse / missing body ≠ fate.
 */
export interface OnlineReviewCollectorDispatchResult {
  /**
   * Opaque evidence blob for Verify unpack only. Stage copies any object body
   * verbatim and must not read business fields. Prefer cargoPointer when both
   * are present for durable identity.
   */
  readonly evidence?: OnlineReviewLandingSnapshot;
  readonly cargoPointer?: string;
  readonly artifacts?: NonNullable<
    WorkerLandingPayload["rawReviewerArtifacts"]
  >;
}

/**
 * Online Review Verify Action result (#1145).
 * Judgment seat only — never owns GH wait/retrigger. Runner routes on verify.
 */
export interface OnlineReviewVerifyDispatchResult {
  readonly verify?: VerifyResult;
  readonly artifacts?: NonNullable<
    WorkerLandingPayload["rawReviewerArtifacts"]
  >;
}

/** Thrown when a read-only verify worker dirties the tracked worktree (#600 r32). */
export interface OnlineReviewLoopDispatch {
  /**
   * Online Review Collector seat (#1145): owns GitHub query, necessary wait,
   * post-fix retrigger, and evidence assembly. Runner only counts exit and
   * transports opaque evidence — never interprets bot/CI/finding semantics.
   * Action-owned durable resume may short-circuit re-dispatch when a completed
   * checkpoint already holds this round's cargo.
   */
  readonly dispatchCollector: (
    landing: WorkerLandingPayload,
    round: number,
  ) => Promise<OnlineReviewCollectorDispatchResult>;
  /**
   * Online Review Verify seat (#1145): owns judgment + side effects only.
   * Receives Collector evidence via landing; returns typed disposition +
   * opaque fixer packet on continue.
   */
  readonly dispatchVerify: (
    landing: WorkerLandingPayload,
    round: number,
  ) => Promise<OnlineReviewVerifyDispatchResult>;
  readonly dispatchFixer: (
    landing: WorkerLandingPayload,
  ) => Promise<FixerResult | undefined>;
  /**
   * Record/persist the fixing commit SHA after fixer success.
   * Receives the envelope {@link fixCommitSha} only — never re-read live git
   * (ADR 0030 envelope-only). Post-fix retrigger/wait is Collector's job on
   * the next loop iteration — no host retriggerAfterFix seam.
   */
  readonly resolveFixCommitSha?: (
    envelopeFixSha: string,
  ) => string | Promise<string>;
}

/**
 * #1145 thin PR identity for ledger write/read (sole normalize).
 * GitHub PR URL → `owner/repo#n` (owner/repo lowercased); `owner/repo#n` same;
 * other non-empty handles (e.g. `pr://…`) kept trimmed verbatim; empty → undefined.
 */
export function canonicalOnlineReviewPrId(pr: string): string | undefined {
  const raw = typeof pr === "string" ? pr.trim() : "";
  if (raw.length === 0) return undefined;
  const urlMatch = raw.match(
    /^https?:\/\/(?:www\.)?github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)\/?$/i,
  );
  if (urlMatch !== null) {
    const owner = urlMatch[1]!.toLowerCase();
    const repo = urlMatch[2]!.toLowerCase();
    const n = String(Number(urlMatch[3]));
    if (!Number.isSafeInteger(Number(urlMatch[3])) || Number(urlMatch[3]) < 1) {
      return undefined;
    }
    return `${owner}/${repo}#${n}`;
  }
  const shortMatch = raw.match(/^([^/#\s]+)\/([^/#\s]+)#(\d+)$/);
  if (shortMatch !== null) {
    const owner = shortMatch[1]!.toLowerCase();
    const repo = shortMatch[2]!.toLowerCase();
    const num = Number(shortMatch[3]);
    if (!Number.isSafeInteger(num) || num < 1) return undefined;
    return `${owner}/${repo}#${String(num)}`;
  }
  // Non-GH thin handles (offline pr://… etc.) — exact trimmed identity.
  return raw;
}

/** Fail-closed PR identity equality via {@link canonicalOnlineReviewPrId}. */
export function onlineReviewPrIdentityEquals(
  a: string | undefined,
  b: string | undefined,
): boolean {
  if (a === undefined || b === undefined) return false;
  const ca = canonicalOnlineReviewPrId(a);
  const cb = canonicalOnlineReviewPrId(b);
  return ca !== undefined && cb !== undefined && ca === cb;
}

/**
 * Family online-review loop result (#1145 bound/unbound).
 * Bound variants always carry non-empty {@link reviewedPr} from loop entry.
 * Unbound = no PR identity — post-loop must not Landing/converged.
 */
export type OnlineReviewLoopStageResult =
  | {
      readonly binding: "bound";
      /** Non-empty thin PR identity bound at loop entry (never post-loop re-resolve). */
      readonly reviewedPr: string;
      readonly ok: boolean;
      readonly terminalState: OnlineReviewTerminalState;
      readonly round: number;
      readonly stopSummary?: StopSummary;
    }
  | {
      readonly binding: "unbound";
      readonly ok: false;
      readonly terminalState: "decision_gate_raised";
      readonly round: 1;
      readonly stopSummary?: StopSummary;
    };

/** Bound result helper — reviewedPr must be non-empty. */
export function boundOnlineReviewLoopResult(
  reviewedPr: string,
  result: {
    readonly ok: boolean;
    readonly terminalState: OnlineReviewTerminalState;
    readonly round: number;
    readonly stopSummary?: StopSummary;
  },
): Extract<OnlineReviewLoopStageResult, { readonly binding: "bound" }> {
  const pr = reviewedPr.trim();
  if (pr.length === 0) {
    throw new Error(
      "boundOnlineReviewLoopResult requires non-empty reviewedPr",
    );
  }
  return {
    binding: "bound",
    reviewedPr: pr,
    ok: result.ok,
    terminalState: result.terminalState,
    round: result.round,
    ...(result.stopSummary !== undefined
      ? { stopSummary: result.stopSummary }
      : {}),
  };
}

/** Early terminal when live+shipped PR handles are both absent. */
export function unboundOnlineReviewLoopResult(
  stopSummary?: StopSummary,
): Extract<OnlineReviewLoopStageResult, { readonly binding: "unbound" }> {
  return {
    binding: "unbound",
    ok: false,
    terminalState: "decision_gate_raised",
    round: 1,
    ...(stopSummary !== undefined ? { stopSummary } : {}),
  };
}

/**
 * Passthrough Verify → Fixer opaque packet (#1145).
 * Single transport of this-round self-reported keys/threads only — no secondary
 * filtering, no disposition derivation, no history backfill when sparse/missing.
 */
function fixerPacketFromVerify(verify: VerifyResult | undefined): {
  readonly fixMarkedFindingIdentityKeys: ReadonlyArray<string>;
  readonly fixMarkedFindingThreads: ReadonlyArray<{
    readonly identityKey: string;
    readonly threadId: string;
  }>;
} {
  return {
    fixMarkedFindingIdentityKeys: verify?.fixMarkedFindingIdentityKeys ?? [],
    fixMarkedFindingThreads: verify?.fixMarkedFindingThreads ?? [],
  };
}

function applyVerifyDisposition(
  reviewedPr: string,
  verify: VerifyResult | undefined,
  round: number,
): OnlineReviewLoopStageResult | "continue" {
  if (verify === undefined) return "continue";
  const disposition = onlineReviewJudgeDisposition(verify);
  if (disposition === "escalate") {
    return boundOnlineReviewLoopResult(reviewedPr, {
      ok: false,
      terminalState: "decision_gate_raised",
      round,
      stopSummary: onlineReviewDecisionGateStopSummary(),
    });
  }
  if (disposition === "converged") {
    // #941 / ID-013: online-review ends at mergeable. Landing Action owns
    // docs release, merge, MERGED confirm, close, and cleanup.
    return boundOnlineReviewLoopResult(reviewedPr, {
      ok: true,
      terminalState: "mergeable",
      round,
    });
  }
  return "continue";
}

/**
 * Family online review-loop stage (#940 typed-judge-only).
 * #941: stops at mergeable; landing Action owns docs/merge/close/cleanup.
 * Exit conditions are worker judge dispositions only — no mechanical round cap.
 */
export async function runOnlineReviewLoopStage(
  ship: ShipResult,
  dispatch: OnlineReviewLoopDispatch,
  opts?: {
    readonly initialRound?: number;
    /** Prior fixing commit SHA — surfaces post-fix head to Collector landing. */
    readonly initialFixCommitSha?: string;
    /** Durable fixer authorization reconstructed for a post-crash recheck. */
    readonly initialFixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
    /** Durable identity-to-thread bindings reconstructed for fixer landing. */
    readonly initialFixMarkedFindingThreads?: ReadonlyArray<{
      readonly identityKey: string;
      readonly threadId: string;
    }>;
    /**
     * #1145 post-fixer crash resume: opaque fixer cargo already durable.
     * When set, this round skips first Verify + Fixer and goes to same-round
     * Verify with the cargo (Collector still runs — checkpoint short-circuit).
     */
    readonly initialPendingFixerResult?: FixerResult;
    /**
     * #1145: reconstructed unconsumed post-fix one-shot. True when a committed
     * fix head has no Collector checkpoint yet (crash after fix_committed).
     * Live head-move during this process still sets the flag independently.
     */
    readonly initialPostFixTransition?: boolean;
    /** Optional runner-owned landing enrichment (#711 prior-round data). */
    readonly enrichVerifyLanding?: (
      landing: WorkerLandingPayload,
      round: number,
    ) => WorkerLandingPayload | Promise<WorkerLandingPayload>;
  },
): Promise<OnlineReviewLoopStageResult> {
  // Stage is only entered when family loop already bound a non-empty PR.
  const reviewedPr =
    typeof ship.pr === "string" && ship.pr.trim().length > 0
      ? ship.pr.trim()
      : "";
  if (reviewedPr.length === 0) {
    return unboundOnlineReviewLoopResult(
      stageFailureStopSummary({
        status: "online_review_failed",
        summary:
          "online review stage entered without a bound PR identity",
        repairHint:
          "bind a live or shipped PR handle before dispatching the online review loop",
      }),
    );
  }
  let round = opts?.initialRound ?? 1;
  /** Last known fix head for Collector post-fix landing (opaque transport). */
  let lastFixCommitSha = opts?.initialFixCommitSha;
  /**
   * One-shot stage fact for the next Collector only. Set when pending
   * committed-fixer resume or current fixer envelope moves the effective head;
   * cleared immediately after that Collector dispatch. Legal no-op retaining
   * the prior fix SHA must not set it (#1145).
   *
   * May also be reconstructed from ledger when fix_committed already advanced
   * lastFixSha to the new head but no Collector checkpoint exists yet.
   */
  let postFixTransition = opts?.initialPostFixTransition === true;
  /** The previous fixer assignment, required as the next verify's recheck contract. */
  let recheckFixMarkedFindingIdentityKeys: ReadonlyArray<string> | undefined =
    opts?.initialFixMarkedFindingIdentityKeys;
  let recheckFixMarkedFindingThreads:
    | ReadonlyArray<{ readonly identityKey: string; readonly threadId: string }>
    | undefined = opts?.initialFixMarkedFindingThreads;
  /**
   * When set, skip first Verify + Fixer and feed this cargo to same-round Verify.
   * Cleared after the post-fixer Verify seat consumes it (or attempts to).
   */
  let pendingFixerResult: FixerResult | undefined = opts?.initialPendingFixerResult;
  /**
   * Crash between Fixer return and resolveFixCommitSha left envelope SHA without
   * fix_committed — call the callback once on resume whenever the pending SHA
   * differs from the ledger's previous head (incl. second-round old→new).
   */
  let resumeNeedsFixShaBookkeeping = false;
  if (pendingFixerResult !== undefined) {
    const resumedSha = fixerEnvelopeFixCommitSha(pendingFixerResult);
    if (resumedSha !== undefined && resumedSha.length > 0) {
      const previousEffectiveHead =
        lastFixCommitSha !== undefined && lastFixCommitSha.length > 0
          ? lastFixCommitSha
          : ship.prHead;
      if (
        postFixTransitionFromCommittedFixerResumeMarker({
          previousEffectiveHead,
          committedFixerHead: resumedSha,
        })
      ) {
        lastFixCommitSha = resumedSha;
        resumeNeedsFixShaBookkeeping = true;
        postFixTransition = true;
      } else if (postFixTransition) {
        // fix_committed already booked the new head (SHA equality); keep the
        // reconstructed one-shot until Collector checkpoint consumes it.
        lastFixCommitSha = resumedSha;
      }
    }
  }

  // #940 / ID-012: no mechanical round cap — persistent verify judge owns
  // continue vs escalate. Runner only routes the three-state disposition.
  for (;;) {
    // Base landing only — Collector owns GH evidence (#1145).
    let landing = buildOnlineReviewBaseLanding(
      ship,
      round,
      lastFixCommitSha,
      postFixTransition,
    );
    if (round > 1 || pendingFixerResult !== undefined) {
      landing = {
        ...landing,
        fixMarkedFindingIdentityKeys:
          recheckFixMarkedFindingIdentityKeys ?? [],
        fixMarkedFindingThreads: recheckFixMarkedFindingThreads ?? [],
      };
    }
    if (opts?.enrichVerifyLanding !== undefined) {
      landing = await opts.enrichVerifyLanding(landing, round);
    }

    // ── 1. Collector: query/wait/retrigger/evidence (no judge enum) ──
    // Action may return a durable checkpoint without re-burning wait.
    // Also runs on post-fixer resume so frozen evidence is restored.
    let collectorArtifacts: NonNullable<
      WorkerLandingPayload["rawReviewerArtifacts"]
    > | undefined;
    try {
      const collected = await dispatch.dispatchCollector(landing, round);
      // One-shot: consume after the immediately following Collector dispatch.
      postFixTransition = false;
      // Opaque evidence transport — stage copies handle/blob by reference and
      // never inspects body fields to drive scheduling (#1145 / ADR 0131).
      // prHead bookkeeping = ship/fix SHA only. Sparse cargo ≠ fate.
      const baseHead =
        lastFixCommitSha !== undefined && lastFixCommitSha.length > 0
          ? lastFixCommitSha
          : ship.prHead;
      // Any object body copied verbatim; pointer-only remains legal.
      landing = {
        ...landing,
        ...(collected.evidence !== undefined &&
        typeof collected.evidence === "object" &&
        collected.evidence !== null
          ? { onlineReviewSnapshot: collected.evidence }
          : {}),
        ...(typeof collected.cargoPointer === "string" &&
        collected.cargoPointer.trim().length > 0
          ? { cargoPointer: collected.cargoPointer.trim() }
          : {}),
        shipDelivery: {
          branch: ship.branch,
          pr: ship.pr,
          ...(baseHead !== undefined && baseHead.length > 0
            ? { prHead: baseHead }
            : {}),
          ...(ship.status !== undefined ? { status: ship.status } : {}),
        },
        ...(collected.artifacts !== undefined
          ? { rawReviewerArtifacts: collected.artifacts }
          : {}),
      };
      collectorArtifacts = collected.artifacts;
    } catch (err) {
      if (err instanceof OnlineReviewLoopTerminal) {
        throw err;
      }
      return decisionGateFromDispatchInfra(reviewedPr, round, "collector", err);
    }

    let verify: VerifyResult | undefined;

    // ── 2/3. First Verify + Fixer — skipped when resuming durable fixer cargo ──
    if (pendingFixerResult === undefined) {
      try {
        const dispatchedVerify = await dispatch.dispatchVerify(landing, round);
        verify = dispatchedVerify.verify;
        if (dispatchedVerify.artifacts !== undefined) {
          landing = {
            ...landing,
            rawReviewerArtifacts: dispatchedVerify.artifacts,
          };
        } else if (collectorArtifacts !== undefined) {
          landing = {
            ...landing,
            rawReviewerArtifacts: collectorArtifacts,
          };
        }
      } catch (err) {
        if (err instanceof OnlineReviewLoopTerminal) {
          throw err;
        }
        return decisionGateFromDispatchInfra(reviewedPr, round, "verify", err);
      }

      {
        const terminal = applyVerifyDisposition(reviewedPr, verify, round);
        if (terminal !== "continue") return terminal;
      }
      // Sparse / unusable verify cargo (no typed disposition) continues to fixer
      // with raw artifacts — never host empty-success (#940 / ID-012).

      // Opaque fixer packet = THIS round's Verify cargo only. Missing/sparse must
      // not fall back to prior-round recheck keys seeded on the Verify landing.
      const packet = fixerPacketFromVerify(verify);
      const fixKeys = packet.fixMarkedFindingIdentityKeys;
      const fixMarkedFindingThreads = packet.fixMarkedFindingThreads;
      landing = {
        ...landing,
        fixMarkedFindingIdentityKeys: fixKeys,
        fixMarkedFindingThreads,
      };

      // continue disposition: fixer path (no mechanical round cap).
      recheckFixMarkedFindingIdentityKeys = fixKeys;
      recheckFixMarkedFindingThreads = fixMarkedFindingThreads;

      let fixerOutput: FixerResult | undefined;
      try {
        fixerOutput = await dispatch.dispatchFixer(landing);
      } catch (err) {
        if (err instanceof OnlineReviewLoopTerminal) {
          throw err;
        }
        return decisionGateFromDispatchInfra(reviewedPr, round, "fixer", err);
      }
      pendingFixerResult = fixerOutput;

      // Envelope SHA bookkeeping only — presence does not fork the next seat.
      // Always adopt envelope SHA first; resolveFixCommitSha may override only.
      // postFixTransition is set only when the effective head actually moves.
      const envelopeFixSha =
        fixerOutput !== undefined
          ? fixerEnvelopeFixCommitSha(fixerOutput)
          : undefined;
      if (envelopeFixSha !== undefined && envelopeFixSha.length > 0) {
        const previousEffectiveHead =
          lastFixCommitSha !== undefined && lastFixCommitSha.length > 0
            ? lastFixCommitSha
            : ship.prHead;
        lastFixCommitSha = envelopeFixSha;
        if (dispatch.resolveFixCommitSha) {
          try {
            const resolved = await dispatch.resolveFixCommitSha(envelopeFixSha);
            if (typeof resolved === "string" && resolved.length > 0) {
              lastFixCommitSha = resolved;
            }
          } catch (err) {
            if (err instanceof OnlineReviewLoopTerminal) {
              throw err;
            }
            return decisionGateFromDispatchInfra(reviewedPr, round, "fixer", err);
          }
        }
        if (
          postFixTransitionFromCommittedFixerResumeMarker({
            previousEffectiveHead,
            committedFixerHead: lastFixCommitSha,
          })
        ) {
          postFixTransition = true;
        }
      }
    } else if (
      resumeNeedsFixShaBookkeeping &&
      lastFixCommitSha !== undefined &&
      lastFixCommitSha.length > 0 &&
      dispatch.resolveFixCommitSha
    ) {
      resumeNeedsFixShaBookkeeping = false;
      try {
        const resolved = await dispatch.resolveFixCommitSha(lastFixCommitSha);
        if (typeof resolved === "string" && resolved.length > 0) {
          lastFixCommitSha = resolved;
        }
      } catch (err) {
        if (err instanceof OnlineReviewLoopTerminal) {
          throw err;
        }
        return decisionGateFromDispatchInfra(reviewedPr, round, "fixer", err);
      }
    } else {
      resumeNeedsFixShaBookkeeping = false;
    }

    // #1145: EVERY fixer result is opaque cargo back to the SAME Verify judge.
    // Do not branch topology on committed / alreadySatisfied / fixCommitSha
    // (no fourth state, no isFixerLegalNoOp control-flow fork).
    // After accepting/resolving the Fixer envelope SHA, pin shipDelivery.prHead
    // to the already-established effective head before same-round recheck
    // Verify — retain Collector evidence + opaque fixer cargo so the durable
    // (round, head, PR) receipt namespace stays stable across crash/resume.
    const effectiveHead =
      lastFixCommitSha !== undefined && lastFixCommitSha.length > 0
        ? lastFixCommitSha
        : ship.prHead;
    const shipDeliveryForRecheck =
      landing.shipDelivery !== undefined
        ? {
            ...landing.shipDelivery,
            ...(effectiveHead !== undefined && effectiveHead.length > 0
              ? { prHead: effectiveHead }
              : {}),
          }
        : {
            branch: ship.branch,
            pr: ship.pr,
            ...(effectiveHead !== undefined && effectiveHead.length > 0
              ? { prHead: effectiveHead }
              : {}),
            ...(ship.status !== undefined ? { status: ship.status } : {}),
          };
    landing = {
      ...landing,
      fixMarkedFindingIdentityKeys:
        recheckFixMarkedFindingIdentityKeys ??
        landing.fixMarkedFindingIdentityKeys ??
        [],
      fixMarkedFindingThreads:
        recheckFixMarkedFindingThreads ??
        landing.fixMarkedFindingThreads ??
        [],
      ...(pendingFixerResult !== undefined
        ? { fixerResult: pendingFixerResult }
        : {}),
      shipDelivery: shipDeliveryForRecheck,
    };
    // Cargo handed to same-round Verify — clear so a later continue iteration
    // does not skip first Verify + Fixer again.
    pendingFixerResult = undefined;

    // Same-round Verify with fixer cargo (Collector already ran this iteration).
    try {
      const recheck = await dispatch.dispatchVerify(landing, round);
      verify = recheck.verify;
      if (recheck.artifacts !== undefined) {
        landing = {
          ...landing,
          rawReviewerArtifacts: recheck.artifacts,
        };
      }
    } catch (err) {
      if (err instanceof OnlineReviewLoopTerminal) {
        throw err;
      }
      return decisionGateFromDispatchInfra(reviewedPr, round, "verify", err);
    }

    {
      const terminal = applyVerifyDisposition(reviewedPr, verify, round);
      if (terminal !== "continue") return terminal;
    }

    // Judge said continue after seeing fixer cargo → next Collector cycle
    // (post-fix retrigger/wait owned by Collector). Round advances only on
    // three-state continue, never on fixer envelope fields.
    const nextPacket = fixerPacketFromVerify(verify);
    recheckFixMarkedFindingIdentityKeys = nextPacket.fixMarkedFindingIdentityKeys;
    recheckFixMarkedFindingThreads = nextPacket.fixMarkedFindingThreads;
    round += 1;
  }
}
