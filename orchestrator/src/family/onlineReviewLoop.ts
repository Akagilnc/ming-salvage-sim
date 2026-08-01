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

import type {
  FixerResult,
  OnlineReviewLandingSnapshot,
  OnlineReviewTerminalState,
  ShipResult,
  VerifyResult,
  WorkerLandingPayload,
} from "../types.js";
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
  return verify.status;
}

export type { OnlineReviewTerminalState } from "../types.js";

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

/** Base landing before the Online Review Action assembles evidence (#1145). */
export function buildOnlineReviewBaseLanding(
  ship: ShipResult,
  round: number,
): WorkerLandingPayload {
  return {
    shipDelivery: {
      branch: ship.branch,
      pr: ship.pr,
      ...(ship.prHead !== undefined && ship.prHead.length > 0
        ? { prHead: ship.prHead }
        : {}),
      ...(ship.status !== undefined ? { status: ship.status } : {}),
    },
    onlineReviewRound: round,
  };
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
  /** Opaque Fixer cargo recovered by the Collector's durable capability. */
  readonly recoveredFixerResult?: FixerResult;
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

/** Latest resident Verify session for this exact Action-owned review cycle. */
export function onlineReviewJudgeSessionIdFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly pr?: string;
    readonly onlineReviewCycle?: string;
    readonly sessionId?: string;
  }>,
  currentPr: string,
  currentCycle?: string,
): string | undefined {
  // An absent cycle token cannot prove resident-seat identity, so open fresh.
  if (currentCycle === undefined) return undefined;
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status !== "online_review_judge_opened" ||
      entry.event !== "online_review_judge_opened" ||
      !onlineReviewPrIdentityEquals(entry.pr, currentPr) ||
      entry.onlineReviewCycle !== currentCycle
    ) {
      continue;
    }
    // The professional Action owns session capability validity. Runner only
    // transports the typed handle and must not inspect its contents.
    return entry.sessionId;
  }
  return undefined;
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
    /**
     * #1145 post-fixer crash resume: opaque fixer cargo already durable.
     * When set, this round skips first Verify + Fixer and goes to same-round
     * Verify with the cargo (Collector still runs — checkpoint short-circuit).
     */
    readonly initialPendingFixerResult?: FixerResult;
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
  let recheckOnlineReviewFixPacket: unknown;
  /**
   * When set, skip first Verify + Fixer and feed this cargo to same-round Verify.
   * Cleared after the post-fixer Verify seat consumes it (or attempts to).
   */
  let pendingFixerResult: FixerResult | undefined = opts?.initialPendingFixerResult;
  // #940 / ID-012: no mechanical round cap — persistent verify judge owns
  // continue vs escalate. Runner only routes the three-state disposition.
  for (;;) {
    // Base landing only — Collector owns GH evidence (#1145).
    let landing = buildOnlineReviewBaseLanding(ship, round);
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
      // Opaque evidence transport — stage copies handle/blob by reference and
      // never inspects body fields to drive scheduling (#1145 / ADR 0131).
      // prHead bookkeeping = ship/fix SHA only. Sparse cargo ≠ fate.
      const baseHead = ship.prHead;
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
      // Recovery is decided by the professional Collector Action. Runner only
      // moves the returned opaque body to the resident judge and never reads
      // Fixer business fields.
      if (pendingFixerResult === undefined) {
        pendingFixerResult = collected.recoveredFixerResult;
      }
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

      // The judge's packet is one opaque value. In particular, do not touch the
      // retired parallel finding/key/thread fields even when accessors exist.
      recheckOnlineReviewFixPacket = verify?.onlineReviewFixPacket;
      landing = {
        ...landing,
        ...(recheckOnlineReviewFixPacket !== undefined
          ? { onlineReviewFixPacket: recheckOnlineReviewFixPacket }
          : {}),
      };

      const fixerLanding = landing;

      let fixerOutput: FixerResult | undefined;
      try {
        fixerOutput = await dispatch.dispatchFixer(fixerLanding);
      } catch (err) {
        if (err instanceof OnlineReviewLoopTerminal) {
          throw err;
        }
        return decisionGateFromDispatchInfra(reviewedPr, round, "fixer", err);
      }
      pendingFixerResult = fixerOutput;

    }

    // Fixer cargo returns whole to the resident judge. The Collector resolves
    // any resulting PR/head transition on its next beat.
    const effectiveHead =
      typeof pendingFixerResult?.fixCommitSha === "string" &&
      pendingFixerResult.fixCommitSha.trim().length > 0
        ? pendingFixerResult.fixCommitSha.trim()
        : landing.shipDelivery?.prHead;
    landing = {
      ...landing,
      ...(recheckOnlineReviewFixPacket !== undefined
        ? { onlineReviewFixPacket: recheckOnlineReviewFixPacket }
        : {}),
      ...(pendingFixerResult !== undefined
        ? { fixerResult: pendingFixerResult }
        : {}),
      ...(landing.shipDelivery !== undefined
        ? {
            shipDelivery: {
              ...landing.shipDelivery,
              ...(effectiveHead !== undefined ? { prHead: effectiveHead } : {}),
            },
          }
        : {}),
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
    recheckOnlineReviewFixPacket = verify?.onlineReviewFixPacket;
    round += 1;
  }
}
