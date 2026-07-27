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
 * Single truth = max `onlineReviewRound` on live Collector / fix / mergeable
 * markers. Do not count fix commits — legal no-op continues advance the loop
 * without a new commit and still write later Collector checkpoints.
 */
export function onlineReviewRoundFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly onlineReviewRound?: number;
  }>,
): number {
  let maxRound = 0;
  for (const entry of entries) {
    const live =
      (entry.status === "online_review_collector_completed" &&
        entry.event === "online_review_collector_completed") ||
      (entry.status === "online_review_fix_committed" &&
        entry.event === "online_review_fix_committed") ||
      (entry.status === "online_review_mergeable" &&
        entry.event === "online_review_mergeable");
    if (!live) continue;
    if (
      typeof entry.onlineReviewRound === "number" &&
      Number.isSafeInteger(entry.onlineReviewRound) &&
      entry.onlineReviewRound >= 1
    ) {
      maxRound = Math.max(maxRound, entry.onlineReviewRound);
    }
  }
  return maxRound > 0 ? maxRound : 1;
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

/**
 * Action-owned mergeable completion checkpoint (#1145 re-entry).
 * When Verify has already converged (side effects done), re-entry must not
 * re-dispatch Verify and replay reply/resolve/defer external effects.
 */
export function lastOnlineReviewMergeableFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly onlineReviewRound?: number;
  }>,
): { readonly round: number } | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status !== "online_review_mergeable" ||
      entry.event !== "online_review_mergeable"
    ) {
      continue;
    }
    const round =
      typeof entry.onlineReviewRound === "number" &&
      Number.isSafeInteger(entry.onlineReviewRound) &&
      entry.onlineReviewRound >= 1
        ? entry.onlineReviewRound
        : 1;
    return { round };
  }
  return undefined;
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
  postFixCommitSha?: string,
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
  verify: VerifyResult | undefined,
  round: number,
): OnlineReviewLoopStageResult | "continue" {
  if (verify === undefined) return "continue";
  const disposition = onlineReviewJudgeDisposition(verify);
  if (disposition === "escalate") {
    return {
      ok: false,
      terminalState: "decision_gate_raised",
      round,
      stopSummary: onlineReviewDecisionGateStopSummary(),
    };
  }
  if (disposition === "converged") {
    // #941 / ID-013: online-review ends at mergeable. Landing Action owns
    // docs release, merge, MERGED confirm, close, and cleanup.
    return { ok: true, terminalState: "mergeable", round };
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
    /** Optional runner-owned landing enrichment (#711 prior-round data). */
    readonly enrichVerifyLanding?: (
      landing: WorkerLandingPayload,
      round: number,
    ) => WorkerLandingPayload | Promise<WorkerLandingPayload>;
  },
): Promise<OnlineReviewLoopStageResult> {
  let round = opts?.initialRound ?? 1;
  /** Last known fix head for Collector post-fix landing (opaque transport). */
  let lastFixCommitSha = opts?.initialFixCommitSha;
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
    let landing = buildOnlineReviewBaseLanding(ship, round, lastFixCommitSha);
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
      const baseHead =
        lastFixCommitSha !== undefined && lastFixCommitSha.length > 0
          ? lastFixCommitSha
          : ship.prHead;
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
            : baseHead !== undefined && baseHead.length > 0
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

    {
      const terminal = applyVerifyDisposition(verify, round);
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
      return decisionGateFromDispatchInfra(round, "fixer", err);
    }

    // #1145: EVERY fixer result is opaque cargo back to the SAME Verify judge.
    // Do not branch topology on committed / alreadySatisfied / fixCommitSha
    // (no fourth state, no isFixerLegalNoOp control-flow fork).
    landing = {
      ...landing,
      ...(fixerOutput !== undefined ? { fixerResult: fixerOutput } : {}),
    };

    // Envelope SHA bookkeeping only — presence does not fork the next seat.
    const envelopeFixSha =
      fixerOutput !== undefined
        ? fixerEnvelopeFixCommitSha(fixerOutput)
        : undefined;
    if (envelopeFixSha !== undefined && dispatch.resolveFixCommitSha) {
      try {
        const resolved = await dispatch.resolveFixCommitSha(envelopeFixSha);
        if (typeof resolved === "string" && resolved.length > 0) {
          lastFixCommitSha = resolved;
        } else {
          lastFixCommitSha = envelopeFixSha;
        }
      } catch (err) {
        if (err instanceof OnlineReviewLoopTerminal) {
          throw err;
        }
        return decisionGateFromDispatchInfra(round, "fixer", err);
      }
    }

    // Same-round Verify re-entry with fixer cargo — skip Collector so frozen
    // checkpoint evidence is not the only thing the judge sees.
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
      return decisionGateFromDispatchInfra(round, "verify", err);
    }

    {
      const terminal = applyVerifyDisposition(verify, round);
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
