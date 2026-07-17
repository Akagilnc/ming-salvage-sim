/**
 * Family PR review-loop orchestration helpers (#600 / #940).
 *
 * Host-side deterministic glue between bot polling, verify/fixer worker dispatch,
 * and ledger markers. The online-review verify worker owns finding judgment AND
 * GitHub side effects (reply / resolve / deferred issue); it self-reports judge
 * three-state after side effects succeed. The host loop only routes on that
 * disposition (`converged | continue | escalate`) — no host side-effect module,
 * no mechanical round cap, no empty-success from counts (#934 ID-012).
 */

import {
  droppedBotIds,
  ONLINE_REVIEW_BOT_IDS,
  type PrReviewSnapshot,
} from "../botPolling.js";
import {
  assertOfflineSyntheticPollAdmissible,
  buildRoundTrigger,
  convergenceHeadToRecord,
  type RoundTrigger,
} from "../evidenceAdmissibility.js";
import type { Sh } from "../familyDriver.js";
import {
  BOT_OVERDUE_POLL_COUNT,
  BOT_POLL_INTERVAL_MS,
  BOT_RETRIGGER_COMMENT,
  checkRunsConverged,
  classifyCheckRuns,
  findAdmissibleRetriggerComment,
  parsePrRef,
  pollPrReviewState,
  postBotRetriggerComment,
} from "../botPolling.js";
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

/** Identity↔thread binding for fixer landing cargo (not a host side-effect plan). */
export type FixMarkedFindingThread = {
  readonly identityKey: string;
  readonly threadId: string;
};

/** Preserve only the verify worker's self-reported fix-marked identity keys. */
export function fixMarkedKeysFromVerify(verify: VerifyResult): string[] {
  return [...(verify.fixMarkedFindingIdentityKeys ?? [])];
}

/** Preserve the thread that a fix-marked identity was judged against. */
export function fixMarkedFindingThreadsFromVerify(
  verify: VerifyResult,
): FixMarkedFindingThread[] {
  const keys = new Set(fixMarkedKeysFromVerify(verify));
  return (verify.findingDispositions ?? []).flatMap((disposition) =>
    disposition.action === "fix" && keys.has(disposition.identityKey)
      ? [{ identityKey: disposition.identityKey, threadId: disposition.threadId }]
      : [],
  );
}

export type { OnlineReviewTerminalState } from "../types.js";

/**
 * Build the rich landing payload for verify/fixer workers (信封宪法 ADR 0062:
 * finding content in landing file, not DispatchContext).
 */
function toLandingSnapshot(snapshot: PrReviewSnapshot): OnlineReviewLandingSnapshot {
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

/**
 * Stop summary when a host-owned online-review operation fails closed
 * (e.g. post-fix retrigger). Side effects themselves are worker-owned (#940).
 */
export function onlineReviewHostOpFailureStopSummary(err: unknown): StopSummary {
  const detail = err instanceof Error ? err.message : String(err);
  // #922: family surface terminal owns online_review_failed at the source —
  // do not emit infra_failure for callers to restamp.
  return stageFailureStopSummary({
    status: "online_review_failed",
    summary: `online review host operation failed: ${detail}`,
    repairHint:
      "repair the online review host operation (bot retrigger / poll) and rerun the online review loop",
  });
}

type OnlineReviewDispatchPhase = "poll" | "verify" | "fixer";

/** Stop summary when poll/verify/fixer dispatch throws (#600 r20). */
export function onlineReviewDispatchFailureStopSummary(
  phase: OnlineReviewDispatchPhase,
  err: unknown,
): StopSummary {
  const detail = err instanceof Error ? err.message : String(err);
  const label =
    phase === "poll"
      ? "bot poll"
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
    readonly botPendingPolls?: Readonly<Partial<Record<string, number>>>;
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
      botPendingPolls: input.botPendingPolls as never,
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

/** Thrown when a read-only verify worker dirties the tracked worktree (#600 r32). */
export interface OnlineReviewLoopDispatch {
  readonly poll: (round: number) => Promise<PrReviewSnapshot>;
  readonly dispatchVerify: (
    landing: WorkerLandingPayload,
    round: number,
  ) => Promise<
    | VerifyResult
    | {
        readonly kind: "rawReviewerArtifacts";
        readonly artifacts: NonNullable<WorkerLandingPayload["rawReviewerArtifacts"]>;
        readonly verify?: VerifyResult;
      }
  >;
  readonly dispatchFixer: (
    landing: WorkerLandingPayload,
  ) => Promise<FixerResult | undefined>;
  readonly dispatchDocRelease: (
    landing: WorkerLandingPayload,
  ) => Promise<boolean | undefined>;
  /**
   * #940 / ID-012: host no longer applies GitHub side effects. The verify
   * worker owns reply/resolve/deferred and only self-reports after they succeed.
   */
  readonly retriggerAfterFix: () => void | Promise<void>;
  /**
   * Record/persist the fixing commit SHA after fixer success.
   * Receives the envelope {@link fixCommitSha} only — never re-read live git
   * (ADR 0030 envelope-only).
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
 * Post-merge cleanup (#603) runs after host auto-merge, not inside this loop.
 * Exit conditions are worker judge dispositions only — no mechanical round cap.
 */
export async function runOnlineReviewLoopStage(
  ship: ShipResult,
  dispatch: OnlineReviewLoopDispatch,
  opts?: {
    readonly initialRound?: number;
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
  /**
   * In-loop prior-round findings (#711). Family ledgers only persist
   * fix/retrigger markers — not verify output rows — so the continuous multi-round
   * path accumulates snapshots here after each successful fix cycle.
   */
  const priorRoundFindingsAccum: PriorRoundFindingSnapshot[] = [];

  // #940 / ID-012: no mechanical round cap — persistent verify judge owns
  // continue vs escalate. Host only routes the three-state disposition.
  for (;;) {
    let snapshot: PrReviewSnapshot;
    try {
      snapshot = await dispatch.poll(round);
    } catch (err) {
      if (err instanceof OnlineReviewLoopTerminal) {
        throw err;
      }
      return decisionGateFromDispatchInfra(round, "poll", err);
    }
    let landing = buildOnlineReviewLanding(snapshot, ship, round);
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

    let verify: VerifyResult | undefined;
    try {
      const dispatchedVerify = await dispatch.dispatchVerify(landing, round);
      if (dispatchedVerify.kind === "rawReviewerArtifacts") {
        landing = {
          ...landing,
          rawReviewerArtifacts: dispatchedVerify.artifacts,
        };
        verify = dispatchedVerify.verify;
      } else {
        verify = dispatchedVerify;
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

      // Pending CI only: re-poll without finite host fail (#934 ID-004).
      // Bot overdue window is for bots only — CI pending keeps sleeping until
      // check-runs go terminal (or the worker escalates on a later poll).
      if (
        verifyBlockedOnlyOnPendingCheckRuns(
          verify,
          landing.onlineReviewSnapshot,
        )
      ) {
        await sleepPendingCiPollInterval();
        continue;
      }

      // #940: side effects are worker-owned — host only reads opaque cargo for
      // fixer landing (identity keys / threads), never for routing.
      fixKeys = fixMarkedKeysFromVerify(verify);
      fixMarkedFindingThreads = fixMarkedFindingThreadsFromVerify(verify);
      landing = {
        ...landing,
        fixMarkedFindingIdentityKeys: fixKeys,
        fixMarkedFindingThreads,
        ...(verify.findingFamilies !== undefined
          ? { findingFamilies: verify.findingFamilies }
          : {}),
      };

      const reviewSnap = landing.onlineReviewSnapshot;
      const checkRuns = reviewSnap?.checkRuns ?? [];
      const emptyMeans = reviewSnap?.checkRunsEmptyMeans ?? "converged";

      if (
        disposition === "converged" &&
        checkRunsConverged(checkRuns, emptyMeans)
      ) {
        const released = await dispatch.dispatchDocRelease(landing);
        if (released === false) {
          return {
            ok: false,
            terminalState: "decision_gate_raised",
            round,
            stopSummary: stageFailureStopSummary({
              status: "online_review_failed",
              summary:
                "family 文档发布 returned released:false — skill fail / hang / required push fail",
              repairHint:
                "fix the docRelease skill or push failure and re-feed the family run",
            }),
          };
        }
        return { ok: true, terminalState: "mergeable", round };
      }

      // Converged disposition + CI red: park on CI (host-deterministic).
      if (
        disposition === "converged" &&
        classifyCheckRuns(checkRuns, emptyMeans) === "failed"
      ) {
        return {
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary: stageFailureStopSummary({
            status: "online_review_failed",
            summary:
              "online review bots are clean but CI check-runs failed on the PR head",
            repairHint:
              "fix the CI failures on the PR head and re-run the online review loop",
          }),
        };
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
          // #940: resolveFixCommitSha persists the envelope SHA for ledger /
          // recheck landing; host no longer threads it into side effects.
          if (dispatch.resolveFixCommitSha) {
            await dispatch.resolveFixCommitSha(envelopeFixSha);
          }
        } catch (err) {
          if (err instanceof OnlineReviewLoopTerminal) {
            throw err;
          }
          return decisionGateFromDispatchInfra(round, "fixer", err);
        }
        try {
          await dispatch.retriggerAfterFix();
        } catch (err) {
          if (err instanceof OnlineReviewLoopTerminal) {
            throw err;
          }
          return {
            ok: false,
            terminalState: "decision_gate_raised",
            round,
            stopSummary: onlineReviewHostOpFailureStopSummary(err),
          };
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
