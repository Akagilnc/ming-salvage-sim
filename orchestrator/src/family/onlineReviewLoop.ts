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
 */

import {
  BOT_OVERDUE_POLL_COUNT,
  BOT_POLL_INTERVAL_MS,
  BOT_RETRIGGER_COMMENT,
  classifyCheckRuns,
  droppedBotIds,
  findAdmissibleRetriggerComment,
  ONLINE_REVIEW_BOT_IDS,
  parsePrRef,
  pollPrReviewState,
  postBotRetriggerComment,
  type OnlineReviewBotId,
  type PrReviewSnapshot,
} from "../botPolling.js";
import {
  assertOfflineSyntheticPollAdmissible,
  buildRoundTrigger,
  convergenceHeadToRecord,
  type RoundTrigger,
} from "../evidenceAdmissibility.js";
import type { Sh } from "../familyDriver.js";
import type {
  FixerResult,
  OnlineReviewLandingSnapshot,
  OnlineReviewTerminalState,
  PriorRoundFindingSnapshot,
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
import {
  fixMarkedFindingThreadsFromVerify,
  fixMarkedKeysFromVerify,
  type FixMarkedFindingThread,
} from "../onlineReviewSideEffects.js";
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

export type { FixMarkedFindingThread };
export { fixMarkedKeysFromVerify, fixMarkedFindingThreadsFromVerify };

export type { OnlineReviewTerminalState } from "../types.js";

/**
 * Build the rich landing payload for verify/fixer workers (信封宪法 ADR 0062:
 * finding content in landing file, not DispatchContext).
 */
export function toLandingSnapshot(snapshot: PrReviewSnapshot): OnlineReviewLandingSnapshot {
  return {
    prUrl: snapshot.prUrl,
    headOid: snapshot.headOid,
    totalFindingCount: snapshot.totalFindingCount,
    quiescent: snapshot.quiescent,
    bots: snapshot.bots,
    droppedBots: droppedBotIds(snapshot),
    threads: snapshot.threads.map((t) => ({
      id: t.id,
      threadNodeId: t.threadNodeId,
      path: t.path,
      line: t.line,
      body: t.body,
      isResolved: t.isResolved,
      headOid: t.headOid,
      authorLogin: t.authorLogin,
    })),
    checkRuns: snapshot.checkRuns,
    checkRunsEmptyMeans: snapshot.checkRunsEmptyMeans,
  };
}

/**
 * Worker is green but CI is still running — re-poll / re-verify, do not fixer
 * and do not merge (online R2 Codex P2).
 */
export function verifyBlockedOnlyOnPendingCheckRuns(
  verify: VerifyResult,
  landing: OnlineReviewLandingSnapshot | undefined,
): boolean {
  if (!verify.converged || landing === undefined) {
    return false;
  }
  const emptyMeans = landing.checkRunsEmptyMeans ?? "converged";
  return classifyCheckRuns(landing.checkRuns, emptyMeans) === "pending";
}

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

/** Latest persisted family round freshness anchor. */
function roundTriggerFromEntries(
  ledger: ReadonlyArray<{
    readonly event?: string;
    readonly roundTriggerHeadOid?: string;
    readonly roundTriggerAt?: string;
  }>,
): RoundTrigger | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.event === "online_review_round_retrigger" &&
      typeof entry.roundTriggerHeadOid === "string" &&
      entry.roundTriggerHeadOid.length > 0 &&
      typeof entry.roundTriggerAt === "string" &&
      entry.roundTriggerAt.length > 0
    ) {
      return buildRoundTrigger(
        entry.roundTriggerHeadOid,
        entry.roundTriggerAt,
      );
    }
  }
  return undefined;
}

/** Retrigger marker head used to pair with a fix signal (#600 r35). */
function retriggerPairedFixHead(entry: {
  readonly event?: string;
  readonly roundTriggerHeadOid?: string;
  readonly branchHEAD?: string;
  readonly familyHeadAfter?: string;
}): string | undefined {
  if (entry.event !== "online_review_round_retrigger") {
    return undefined;
  }
  if (
    typeof entry.roundTriggerHeadOid === "string" &&
    entry.roundTriggerHeadOid.length > 0
  ) {
    return entry.roundTriggerHeadOid;
  }
  if (typeof entry.branchHEAD === "string" && entry.branchHEAD.length > 0) {
    return entry.branchHEAD;
  }
  if (
    typeof entry.familyHeadAfter === "string" &&
    entry.familyHeadAfter.length > 0
  ) {
    return entry.familyHeadAfter;
  }
  return undefined;
}

/**
 * Among unpaired fix signals, pick the chronologically latest by `ts`
 * (Cursor R11 medium — not last-in-ledger-order, which can lag a later fix
 * if ledger rows are not strictly append-time-ordered).
 */
function latestFixSignalByTimestamp(
  signals: ReadonlyArray<{ readonly sha: string; readonly ts: string }>,
): { readonly sha: string; readonly ts: string } | undefined {
  let latest: { readonly sha: string; readonly ts: string } | undefined;
  for (const signal of signals) {
    if (latest === undefined) {
      latest = signal;
      continue;
    }
    const signalMs = Date.parse(signal.ts);
    const latestMs = Date.parse(latest.ts);
    if (Number.isFinite(signalMs) && Number.isFinite(latestMs)) {
      if (signalMs >= latestMs) latest = signal;
    } else if (Number.isFinite(signalMs)) {
      latest = signal;
    }
  }
  return latest;
}

/** Family ledger: fix-committed landed but retrigger persistence crashed mid-gap (#600 r27). */
export function familyPendingRoundTriggerFromFixGap(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly familyHeadAfter?: string;
    readonly roundTriggerHeadOid?: string;
    readonly branchHEAD?: string;
    readonly ts?: string;
  }>,
): RoundTrigger | undefined {
  const pairedFixShas = new Set<string>();
  for (const entry of entries) {
    const head = retriggerPairedFixHead(entry);
    if (head !== undefined) {
      pairedFixShas.add(head);
    }
  }
  const unpaired: Array<{ readonly sha: string; readonly ts: string }> = [];
  for (const entry of entries) {
    if (
      entry.status === "online_review_fix_committed" &&
      entry.event === "online_review_fix_committed" &&
      typeof entry.familyHeadAfter === "string" &&
      entry.familyHeadAfter.length > 0 &&
      typeof entry.ts === "string" &&
      entry.ts.length > 0 &&
      !pairedFixShas.has(entry.familyHeadAfter)
    ) {
      unpaired.push({ sha: entry.familyHeadAfter, ts: entry.ts });
    }
  }
  const latestUnpaired = latestFixSignalByTimestamp(unpaired);
  if (latestUnpaired === undefined) {
    return undefined;
  }
  return buildRoundTrigger(latestUnpaired.sha, latestUnpaired.ts);
}

function roundTriggerRecencyMs(trigger: RoundTrigger): number | undefined {
  const ms = Date.parse(trigger.triggeredAt);
  return Number.isFinite(ms) ? ms : undefined;
}

/** Pick the fresher recovery anchor when multiple sources are present (#600 r32). */
export function newerRoundTrigger(
  a: RoundTrigger,
  b: RoundTrigger,
): RoundTrigger {
  const aMs = roundTriggerRecencyMs(a);
  const bMs = roundTriggerRecencyMs(b);
  if (aMs !== undefined && bMs !== undefined) {
    return aMs >= bMs ? a : b;
  }
  if (aMs !== undefined) return a;
  if (bMs !== undefined) return b;
  return a;
}

/**
 * Resolve the bot-poll freshness anchor for the current online review round.
 * Round 1 may fall back to the family ship ledger timestamp; round ≥2 requires a
 * persisted re-trigger anchor and never reuses the ship anchor (#600 r25).
 * When fix-committed landed before retrigger (crash gap), reconstruct the
 * pending anchor from the fix record so resume stays in-band (#600 r27).
 * When both persisted and fix-gap anchors exist, precedence is by recency (#600 r32).
 */
export function resolveOnlineReviewRoundTrigger(input: {
  readonly onlineReviewRound: number;
  readonly persistedRoundTrigger?: RoundTrigger;
  readonly pendingRetriggerFromFixGap?: RoundTrigger;
  readonly fixCommitSha?: string;
  readonly shipPrHead?: string;
  readonly shipLedgerTriggeredAt?: string;
}): RoundTrigger {
  const { persistedRoundTrigger, pendingRetriggerFromFixGap, onlineReviewRound } =
    input;
  if (onlineReviewRound > 1) {
    if (
      persistedRoundTrigger !== undefined &&
      pendingRetriggerFromFixGap !== undefined
    ) {
      return newerRoundTrigger(
        pendingRetriggerFromFixGap,
        persistedRoundTrigger,
      );
    }
    if (persistedRoundTrigger !== undefined) {
      return persistedRoundTrigger;
    }
    if (pendingRetriggerFromFixGap !== undefined) {
      return pendingRetriggerFromFixGap;
    }
    throw new Error(
      "online review round ≥2 requires a persisted round trigger from ledger retrigger",
    );
  }
  if (persistedRoundTrigger !== undefined) {
    return persistedRoundTrigger;
  }
  return buildRoundTrigger(
    input.fixCommitSha ?? input.shipPrHead ?? "offline-review-head",
    input.shipLedgerTriggeredAt,
  );
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

/** Latest persisted round ≥2 freshness anchor from the family ledger (#600 r26). */
export function onlineReviewRoundTriggerFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly event?: string;
    readonly roundTriggerHeadOid?: string;
    readonly roundTriggerAt?: string;
  }>,
): RoundTrigger | undefined {
  return roundTriggerFromEntries(entries);
}

/** Family runner owns round ≥2 post-fixer recheck truth. */
export function enforceRunnerOwnedRecheck(
  verify: VerifyResult,
  onlineReviewRound: number,
): VerifyResult {
  const runnerRecheck = onlineReviewRound > 1;
  return { ...verify, isRecheck: runnerRecheck };
}

/** Family `shipped` ledger `ts` for the PR — round-1 freshness anchor (#600 r9). */
export function shipLedgerTriggeredAtFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly pr?: string;
    readonly ts?: string;
  }>,
  prUrl: string,
): string | undefined {
  const normalized = prUrl.trim();
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status === "shipped" &&
      entry.event === "shipped" &&
      entry.pr?.trim() === normalized &&
      typeof entry.ts === "string" &&
      entry.ts.length > 0
    ) {
      return entry.ts;
    }
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

/** Stop summary when host GitHub verify side effects fail closed (#600 r18). */
export function verifySideEffectFailureStopSummary(err: unknown): StopSummary {
  const detail = err instanceof Error ? err.message : String(err);
  // #922: family surface terminal owns online_review_failed at the source —
  // do not emit infra_failure for callers to restamp.
  return stageFailureStopSummary({
      status: "online_review_failed",
    summary: `online review verify side effects failed: ${detail}`,
    repairHint:
      "fix GitHub side-effect preconditions (valid PR ref, recheck fixing commit, defer issue creation) and rerun the online review loop",
  });
}

/**
 * Stop summary when an Online Review Action host-op fails closed
 * (e.g. post-fix bot retrigger). Side effects are worker-owned (#1145);
 * residual plan is never host-replayed.
 */
export function onlineReviewHostOpFailureStopSummary(err: unknown): StopSummary {
  const detail = err instanceof Error ? err.message : String(err);
  // #922: family surface terminal owns online_review_failed at the source —
  // do not emit infra_failure for callers to restamp.
  return stageFailureStopSummary({
      status: "online_review_failed",
    summary: `online review host operation failed: ${detail}`,
    repairHint:
      "repair the online review Action operation (bot retrigger) and rerun the online review loop",
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
 * Synthetic bot snapshot for offline/test PR handles (`pr://…`) where live `gh api`
 * polling is impossible. Worker dispatch still runs; only host polling is skipped.
 */
export function offlinePrReviewSnapshot(input: {
  readonly repo: string;
  readonly prUrl: string;
  readonly headOid: string;
  readonly pollCount: number;
}): PrReviewSnapshot {
  assertOfflineSyntheticPollAdmissible(input.prUrl, input.repo);
  const bots = Object.fromEntries(
    ONLINE_REVIEW_BOT_IDS.map((bot) => [
      bot,
      { state: "complete" as const, findingCount: 0 },
    ]),
  ) as PrReviewSnapshot["bots"];
  return {
    repo: input.repo,
    prNumber: 0,
    prUrl: input.prUrl,
    headOid: input.headOid,
    pollCount: input.pollCount,
    bots,
    threads: [],
    checkRuns: [],
    totalFindingCount: 0,
    quiescent: true,
    roundTriggerUsed: buildRoundTrigger(input.headOid, "1970-01-01T00:00:00.000Z"),
    checkRunsEmptyMeans: "converged",
  };
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

export function buildOnlineReviewLanding(
  snapshot: PrReviewSnapshot,
  ship: ShipResult,
  round: number,
): WorkerLandingPayload {
  // Fail-closed: never non-null-assert a missing convergence head (Cursor R11 low).
  // Prefer snapshot/post-fix head; omit prHead when neither side supplies one.
  const prHead = convergenceHeadForLanding({
    snapshotHeadOid: snapshot.headOid,
    shipPrHead: ship.prHead,
  });
  return {
    onlineReviewSnapshot: toLandingSnapshot(snapshot),
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
 * Poll until bots are quiescent or the poll budget for this wait is exhausted.
 * Enforces ~2-minute cadence between polls; production defaults to
 * {@link BOT_OVERDUE_POLL_COUNT} (N polls ⇒ N−1 sleeps, ≥15 min wall clock).
 * Pass `maxPolls: 1` and `clock: immediateBotPollClock` in unit tests.
 */
export async function waitForBotQuiescence(
  sh: Sh,
  input: {
    readonly repo: string;
    readonly prUrl: string;
    readonly roundTrigger: RoundTrigger;
    readonly maxPolls?: number;
    readonly botPendingPolls?: Readonly<
      Partial<Record<OnlineReviewBotId, number>>
    >;
    readonly clock?: BotPollClock;
  },
): Promise<PrReviewSnapshot> {
  const maxPolls = input.maxPolls ?? BOT_OVERDUE_POLL_COUNT;
  if (maxPolls < 1) {
    throw new Error("waitForBotQuiescence requires maxPolls >= 1");
  }
  const clock = input.clock ?? realBotPollClock;
  // Chain re-anchored triggers across polls (online R5 Codex P1): after head
  // drift, pollPrReviewState re-anchors once; subsequent polls must reuse that
  // anchor rather than re-anchoring with a newer now (which stales real replies).
  let roundTrigger = input.roundTrigger;
  let last: PrReviewSnapshot | undefined;
  for (let poll = 1; poll <= maxPolls; poll += 1) {
    last = pollPrReviewState(sh, {
      repo: input.repo,
      prUrl: input.prUrl,
      pollCount: poll,
      roundTrigger,
      botPendingPolls: input.botPendingPolls,
    });
    roundTrigger = last.roundTriggerUsed;
    if (last.quiescent) return last;
    if (poll < maxPolls) {
      await clock.sleep(BOT_POLL_INTERVAL_MS);
    }
  }
  return last!;
}

/**
 * Gap-resume recovery: post the bot re-trigger when fix_committed landed but the
 * retrigger marker did not (#600 r34). Idempotent — skips posting when evidence
 * collection already finds an admissible re-trigger comment for this round/head.
 */
export function ensureOnlineReviewRetriggerAfterFixGap(input: {
  readonly sh: Sh;
  readonly repo: string;
  readonly prUrl: string;
  readonly gapTrigger: RoundTrigger;
}): { readonly roundTrigger: RoundTrigger; readonly posted: boolean } {
  // findAdmissible polls once and fail-closes when live head left gapTrigger.head.
  const existing = findAdmissibleRetriggerComment(
    input.sh,
    input.repo,
    input.prUrl,
    input.gapTrigger,
  );
  if (existing !== undefined) {
    return { roundTrigger: existing, posted: false };
  }
  // Post against the live head (probe again so post uses current headOid even if
  // HEAD advanced between find and post — rare; second poll is intentional).
  const headProbe = pollPrReviewState(input.sh, {
    repo: input.repo,
    prUrl: input.prUrl,
    pollCount: 0,
    roundTrigger: input.gapTrigger,
  });
  const { prNumber } = parsePrRef(input.prUrl, input.repo);
  const triggeredAt = new Date().toISOString();
  postBotRetriggerComment(input.sh, input.repo, prNumber, BOT_RETRIGGER_COMMENT);
  // Always key the new trigger to the live head + post time (not gap fix SHA alone).
  return {
    roundTrigger: buildRoundTrigger(headProbe.headOid, triggeredAt),
    posted: true,
  };
}

/** Post R2/R3 re-trigger then poll once (caller may loop). */
export function retriggerBotsAndPoll(
  sh: Sh,
  repo: string,
  prUrl: string,
  pollCount: number,
  roundTriggerHead: string,
): { readonly snapshot: PrReviewSnapshot; readonly roundTrigger: RoundTrigger } {
  const headProbe = pollPrReviewState(sh, {
    repo,
    prUrl,
    pollCount: 0,
    roundTrigger: buildRoundTrigger(roundTriggerHead),
    botPendingPolls: {},
  });
  const triggeredAt = new Date().toISOString();
  postBotRetriggerComment(sh, repo, headProbe.prNumber, BOT_RETRIGGER_COMMENT);
  const roundTrigger = buildRoundTrigger(headProbe.headOid, triggeredAt);
  const snapshot = pollPrReviewState(sh, {
    repo,
    prUrl,
    pollCount,
    roundTrigger,
  });
  // Prefer snapshot.roundTriggerUsed (identity with roundTrigger when no further drift).
  return { snapshot, roundTrigger: snapshot.roundTriggerUsed };
}

/**
 * Online Review Collector Action result (#1145).
 * Opaque evidence only — never judge enum. Runner transports as-is to Verify.
 */
export interface OnlineReviewCollectorDispatchResult {
  readonly evidence: OnlineReviewLandingSnapshot;
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
   */
  readonly dispatchCollector: (
    landing: WorkerLandingPayload,
    round: number,
  ) => Promise<OnlineReviewCollectorDispatchResult>;
  /**
   * Online Review Verify seat (#1145): owns judgment + side effects only.
   * Receives Collector evidence via landing; returns typed disposition.
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
  let lastFixCommitSha = opts?.initialFixCommitSha;
  /** The previous fixer assignment, required as the next verify's recheck contract. */
  let recheckFixMarkedFindingIdentityKeys: ReadonlyArray<string> | undefined =
    opts?.initialFixMarkedFindingIdentityKeys;
  let recheckFixMarkedFindingThreads:
    | ReadonlyArray<{ readonly identityKey: string; readonly threadId: string }>
    | undefined = opts?.initialFixMarkedFindingThreads;
  /**
   * In-loop prior-round findings (#711). Family ledgers only persist
   * fix/retrigger markers — not verify output rows — so the continuous multi-round
   * path accumulates snapshots here after each successful fix cycle.
   */
  const priorRoundFindingsAccum: PriorRoundFindingSnapshot[] = [];

  // #940 / ID-012: no mechanical round cap — persistent verify judge owns
  // continue vs escalate. Runner only routes the three-state disposition.
  for (;;) {
    // Base landing only — Collector owns GH evidence (#1145).
    let landing = buildOnlineReviewBaseLanding(ship, round);
    if (priorRoundFindingsAccum.length > 0) {
      landing = {
        ...landing,
        priorRoundFindings: priorRoundFindingsAccum.map((s) => ({ ...s })),
      };
    }
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
    let collectorArtifacts: NonNullable<
      WorkerLandingPayload["rawReviewerArtifacts"]
    > | undefined;
    try {
      const collected = await dispatch.dispatchCollector(landing, round);
      // Opaque evidence transport — Runner does not interpret bot/CI fields.
      landing = {
        ...landing,
        onlineReviewSnapshot: collected.evidence,
        shipDelivery: {
          branch: ship.branch,
          pr: ship.pr,
          ...(collected.evidence.headOid.length > 0
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
    let fixKeys: string[] = [];
    let fixMarkedFindingThreads: FixMarkedFindingThread[] = [];

    if (verify !== undefined) {
      // #877: isRecheck force-normalize is routing plumbing.
      verify = enforceRunnerOwnedRecheck(verify, round);
      disposition = onlineReviewJudgeDisposition(verify);

      if (disposition === "escalate") {
        return {
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary: onlineReviewFixerNothingToFixStopSummary(),
        };
      }

      fixKeys = fixMarkedKeysFromVerify(verify);
      fixMarkedFindingThreads = fixMarkedFindingThreadsFromVerify(verify);
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
          lastFixCommitSha = dispatch.resolveFixCommitSha
            ? await dispatch.resolveFixCommitSha(envelopeFixSha)
            : envelopeFixSha;
        } catch (err) {
          if (err instanceof OnlineReviewLoopTerminal) {
            throw err;
          }
          return decisionGateFromDispatchInfra(round, "fixer", err);
        }
      }
    }
    // #711: record this round's fix-marked keys for the next verify's priorRoundFindings.
    priorRoundFindingsAccum.push({
      round,
      fixMarkedFindingIdentityKeys: fixKeys,
      ...(verify?.findingDispositions !== undefined
        ? { findingDispositions: verify.findingDispositions }
        : {}),
    });
    round += 1;
  }
}
