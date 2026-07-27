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
import {
  fixerEnvelopeFixCommitSha,
  fixerHasFixCommit,
  fixerProceedsToVerify,
} from "../reviewLoopOutcome.js";
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

type OnlineReviewRetriggerRecoveryEntry = {
  readonly event?: string;
  readonly onlineReviewRound?: number;
};

/** Latest post-fix recovery from a persisted retrigger marker (#600 r29). */
function latestOnlineReviewRetriggerRecovery(
  entries: ReadonlyArray<OnlineReviewRetriggerRecoveryEntry>,
): { readonly round?: number } | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (entry.event !== "online_review_round_retrigger") {
      continue;
    }
    const round =
      typeof entry.onlineReviewRound === "number" && entry.onlineReviewRound > 0
        ? entry.onlineReviewRound
        : undefined;
    if (round !== undefined) {
      return { round };
    }
  }
  return undefined;
}

/** 1-based online review round from the family ledger (#600 r26 resume). */
export function onlineReviewRoundFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly onlineReviewRound?: number;
    readonly roundTriggerHeadOid?: string;
    readonly branchHEAD?: string;
  }>,
): number {
  const completedFixerRounds = entries.filter(
    (e) =>
      e.status === "online_review_fix_committed" &&
      e.event === "online_review_fix_committed",
  ).length;
  const retriggerRecovery = latestOnlineReviewRetriggerRecovery(entries);
  if (completedFixerRounds > 0) {
    return Math.max(completedFixerRounds + 1, retriggerRecovery?.round ?? 0);
  }
  if (retriggerRecovery?.round !== undefined) {
    return retriggerRecovery.round;
  }
  return 1;
}

/** Last family online-review fix HEAD — fixing commit for recheck side effects (#600 r26). */
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
 * Rebuild the last fixer authorization from the family ledger's durable
 * `online_review_fix_committed` marker.
 */
export function lastFixMarkedFindingAuthorizationFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
    readonly fixMarkedFindingThreads?: ReadonlyArray<{
      readonly identityKey?: string;
      readonly threadId?: string;
    }>;
  }>,
): {
  readonly fixMarkedFindingIdentityKeys: ReadonlyArray<string>;
  readonly fixMarkedFindingThreads: ReadonlyArray<{
    readonly identityKey: string;
    readonly threadId: string;
  }>;
} {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status !== "online_review_fix_committed" ||
      entry.event !== "online_review_fix_committed"
    ) {
      continue;
    }
    return {
      fixMarkedFindingIdentityKeys: (entry.fixMarkedFindingIdentityKeys ?? []).filter(
        (key) => typeof key === "string" && key.trim().length > 0,
      ),
      fixMarkedFindingThreads: (entry.fixMarkedFindingThreads ?? []).flatMap(
        (binding) =>
          typeof binding.identityKey === "string" &&
          binding.identityKey.trim().length > 0 &&
          typeof binding.threadId === "string" &&
          binding.threadId.trim().length > 0
            ? [{ identityKey: binding.identityKey, threadId: binding.threadId }]
            : [],
      ),
    };
  }
  return {
    fixMarkedFindingIdentityKeys: [],
    fixMarkedFindingThreads: [],
  };
}

/**
 * Action-owned Collector checkpoint for durable resume (#1145 AC2).
 * Returns the latest completed Collector cargo for `round` when present.
 * Runner/stage never interprets evidence semantics — only the Online Review
 * Action loads this before deciding whether to re-dispatch Collector.
 */
export function lastCollectorCheckpointFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly onlineReviewRound?: number;
    readonly cargoPointer?: string;
    readonly collectorEvidenceCargo?: OnlineReviewLandingSnapshot;
  }>,
  round: number,
):
  | {
      readonly cargoPointer?: string;
      readonly evidence: OnlineReviewLandingSnapshot;
    }
  | undefined {
  if (!Number.isSafeInteger(round) || round < 1) return undefined;
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status !== "online_review_collector_completed" ||
      entry.event !== "online_review_collector_completed"
    ) {
      continue;
    }
    if (entry.onlineReviewRound !== round) continue;
    const evidence = entry.collectorEvidenceCargo;
    if (evidence === undefined) continue;
    if (
      typeof evidence.prUrl !== "string" ||
      evidence.prUrl.length === 0 ||
      typeof evidence.headOid !== "string" ||
      evidence.headOid.length === 0
    ) {
      continue;
    }
    return {
      ...(typeof entry.cargoPointer === "string" && entry.cargoPointer.length > 0
        ? { cargoPointer: entry.cargoPointer }
        : {}),
      evidence,
    };
  }
  return undefined;
}

/** Stop summary for the verifier's explicit decision-gate signal. */
export function onlineReviewFixerNothingToFixStopSummary(): StopSummary {
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
  round: number,
  phase: OnlineReviewDispatchPhase,
  err: unknown,
): OnlineReviewLoopStageResult {
  return {
    ok: false,
    terminalState: "decision_gate_raised",
    round,
    stopSummary: onlineReviewDispatchFailureStopSummary(phase, err),
  };
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

/** Base landing before the Online Review Action assembles evidence (#1145). */
export function buildOnlineReviewBaseLanding(
  ship: ShipResult,
  round: number,
): WorkerLandingPayload {
  const prHead = convergenceHeadForLanding({
    shipPrHead: ship.prHead,
  });
  return {
    shipDelivery: {
      branch: ship.branch,
      pr: ship.pr,
      ...(prHead !== undefined && prHead.length > 0 ? { prHead } : {}),
      ...(ship.status !== undefined ? { status: ship.status } : {}),
    },
    onlineReviewRound: round,
  };
}

/** Write the bot snapshot JSON the verify worker reads (state dir, outside git). */
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
 * Opaque evidence only — never judge enum. Runner transports as-is to Verify.
 * Sparse / missing evidence does not change Action fate (ADR 0131 cargo ≠ fate).
 */
export interface OnlineReviewCollectorDispatchResult {
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

export interface OnlineReviewLoopStageResult {
  readonly ok: boolean;
  readonly terminalState: OnlineReviewTerminalState;
  readonly round: number;
  /** Optional stop summary for non-success terminals. */
  readonly stopSummary?: StopSummary;
}

/**
 * Passthrough Verify → Fixer opaque packet (#1145).
 * Copies self-reported keys/threads only — never filters dispositions.
 */
function fixerPacketFromVerify(verify: VerifyResult): {
  readonly fixMarkedFindingIdentityKeys: ReadonlyArray<string>;
  readonly fixMarkedFindingThreads: ReadonlyArray<{
    readonly identityKey: string;
    readonly threadId: string;
  }>;
} {
  const keys = (verify.fixMarkedFindingIdentityKeys ?? []).filter(
    (key) => typeof key === "string" && key.trim().length > 0,
  );
  const threads = (verify.fixMarkedFindingThreads ?? []).flatMap((binding) =>
    typeof binding.identityKey === "string" &&
    binding.identityKey.trim().length > 0 &&
    typeof binding.threadId === "string" &&
    binding.threadId.trim().length > 0
      ? [{ identityKey: binding.identityKey, threadId: binding.threadId }]
      : [],
  );
  return {
    fixMarkedFindingIdentityKeys: keys,
    fixMarkedFindingThreads: threads,
  };
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
    /** Prior fixing commit SHA for recheck side-effect resolve (#600). */
    readonly initialFixCommitSha?: string;
    /** Durable fixer authorization reconstructed for a post-crash recheck. */
    readonly initialFixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
    /** Durable identity-to-thread bindings reconstructed for fixer landing. */
    readonly initialFixMarkedFindingThreads?: ReadonlyArray<{
      readonly identityKey: string;
      readonly threadId: string;
    }>;
    /** Optional runner-owned landing enrichment (#711 prior-round data). */
    readonly enrichVerifyLanding?: (
      landing: WorkerLandingPayload,
      round: number,
    ) => WorkerLandingPayload | Promise<WorkerLandingPayload>;
  },
): Promise<OnlineReviewLoopStageResult> {
  let round = opts?.initialRound ?? 1;
  /** The previous fixer assignment, required as the next verify's recheck contract. */
  let recheckFixMarkedFindingIdentityKeys: ReadonlyArray<string> | undefined =
    opts?.initialFixMarkedFindingIdentityKeys;
  let recheckFixMarkedFindingThreads:
    | ReadonlyArray<{ readonly identityKey: string; readonly threadId: string }>
    | undefined = opts?.initialFixMarkedFindingThreads;

  // #940 / ID-012: no mechanical round cap — persistent verify judge owns
  // continue vs escalate. Runner only routes the three-state disposition.
  for (;;) {
    // Base landing only — Collector owns GH evidence (#1145).
    let landing = buildOnlineReviewBaseLanding(ship, round);
    if (round > 1) {
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
    let collectorArtifacts: NonNullable<
      WorkerLandingPayload["rawReviewerArtifacts"]
    > | undefined;
    try {
      const collected = await dispatch.dispatchCollector(landing, round);
      // Opaque evidence transport — Runner does not interpret bot/CI fields.
      // Sparse cargo does not change fate (ADR 0131).
      landing = {
        ...landing,
        ...(collected.evidence !== undefined
          ? { onlineReviewSnapshot: collected.evidence }
          : {}),
        shipDelivery: {
          branch: ship.branch,
          pr: ship.pr,
          ...(collected.evidence !== undefined &&
          collected.evidence.headOid.length > 0
            ? { prHead: collected.evidence.headOid }
            : ship.prHead !== undefined && ship.prHead.length > 0
              ? { prHead: ship.prHead }
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
      return decisionGateFromDispatchInfra(round, "collector", err);
    }

    // ── 2. Verify: judgment only on Collector evidence ──
    let verify: VerifyResult | undefined;
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
      return decisionGateFromDispatchInfra(round, "verify", err);
    }
    let disposition: OnlineReviewJudgeDisposition = "continue";
    let fixKeys: ReadonlyArray<string> = [];
    let fixMarkedFindingThreads: ReadonlyArray<{
      readonly identityKey: string;
      readonly threadId: string;
    }> = [];

    if (verify !== undefined) {
      // #1145: isRecheck is Verify-owned cargo — Runner never overwrites it.
      disposition = onlineReviewJudgeDisposition(verify);

      if (disposition === "escalate") {
        return {
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary: onlineReviewFixerNothingToFixStopSummary(),
        };
      }

      // Opaque fixer packet passthrough — no disposition filtering.
      const packet = fixerPacketFromVerify(verify);
      fixKeys = packet.fixMarkedFindingIdentityKeys;
      fixMarkedFindingThreads = packet.fixMarkedFindingThreads;
      landing = {
        ...landing,
        fixMarkedFindingIdentityKeys: fixKeys,
        fixMarkedFindingThreads,
      };

      // #1145: Verify owns CI+bot completeness judgment. Runner trusts the
      // typed disposition only — no host check-run reread / pending sleep.
      if (disposition === "converged") {
        // #941 / ID-013: online-review ends at mergeable. Landing Action owns
        // docs release, merge, MERGED confirm, close, and cleanup.
        return { ok: true, terminalState: "mergeable", round };
      }
    }
    // Sparse / unusable verify cargo (no typed disposition) continues to fixer
    // with raw artifacts — never host empty-success (#940 / ID-012).

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
      return decisionGateFromDispatchInfra(round, "fixer", err);
    }
    if (
      fixerOutput !== undefined &&
      fixerProceedsToVerify(fixerOutput) &&
      fixerHasFixCommit(fixerOutput)
    ) {
      const envelopeFixSha = fixerEnvelopeFixCommitSha(fixerOutput);
      if (envelopeFixSha !== undefined) {
        try {
          // Persist envelope SHA for ledger / recheck landing. Next iteration's
          // Collector owns post-fix retrigger/query/wait (#1145).
          if (dispatch.resolveFixCommitSha) {
            await dispatch.resolveFixCommitSha(envelopeFixSha);
          }
        } catch (err) {
          if (err instanceof OnlineReviewLoopTerminal) {
            throw err;
          }
          return decisionGateFromDispatchInfra(round, "fixer", err);
        }
      }
    }
    // #1145: do not accumulate findingDispositions as a parallel history true
    // source. Next-round recheck keys come from this round's opaque packet and
    // durable fix_committed markers only.
    round += 1;
  }
}
