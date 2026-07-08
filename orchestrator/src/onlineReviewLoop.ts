/**
 * Online PR review-loop orchestration helpers (#600).
 *
 * Host-side deterministic glue between bot polling, verify/fixer worker dispatch,
 * and ledger markers. Worker judgment (fix / reject / defer) stays inside the
 * verify worker; the runner only counts findings and enforces the 3-round cap
 * (ADR 0061 / ADR 0062).
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";

import {
  droppedBotIds,
  ONLINE_REVIEW_BOT_IDS,
  type PrReviewSnapshot,
} from "./botPolling.js";
import {
  assertOfflineSyntheticPollAdmissible,
  buildRoundTrigger,
  convergenceHeadToRecord,
  type RoundTrigger,
} from "./evidenceAdmissibility.js";
import type { Sh } from "./familyDriver.js";
import {
  BOT_OVERDUE_POLL_COUNT,
  BOT_POLL_INTERVAL_MS,
  BOT_RETRIGGER_COMMENT,
  checkRunsConverged,
  findAdmissibleRetriggerComment,
  parsePrRef,
  pollPrReviewState,
  postBotRetriggerComment,
} from "./botPolling.js";
import type {
  FixerResult,
  OnlineReviewLandingSnapshot,
  OnlineReviewTerminalState,
  PersistentLedgerEntry,
  ShipResult,
  StepOutput,
  VerifyResult,
  WorkerLandingPayload,
} from "./types.js";
import {
  fixerEnvelopeFixCommitSha,
  fixerLedgerFixCommitSha,
  fixerLedgerOutputProceeds,
  fixerProceedsToVerify,
} from "./reviewLoopOutcome.js";
import {
  applyVerifySideEffects,
  fixMarkedKeysFromVerify,
} from "./onlineReviewSideEffects.js";
import type { StopSummary } from "./stopSummary.js";
import {
  contractDriftStopSummary,
  decisionGateParkStopSummary,
  infraFailureStopSummary,
} from "./stopSummary.js";

/** Hard cap on online review rounds — runner-enforced (ADR 0061). */
export const MAX_ONLINE_REVIEW_ROUNDS = 3;

export const ONLINE_REVIEW_SNAPSHOT_FILE = "online-review-snapshot.json";
export const ONLINE_REVIEW_LANDING_FILE = ".orchestrator-online-review.json";

export type { OnlineReviewTerminalState } from "./types.js";

export interface OnlineReviewConvergedMarker {
  readonly prUrl: string;
  readonly prHead: string;
  readonly round: number;
  readonly terminalState: OnlineReviewTerminalState;
}

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
  };
}

/**
 * Host-side default-deny: verify `converged:true` is inadmissible while CI check-runs
 * are in-progress or non-success (ADR 0061 — runner enforces, worker still sees runs).
 */
export function clampVerifyConvergenceForCheckRuns(
  verify: VerifyResult,
  landing: OnlineReviewLandingSnapshot | undefined,
): VerifyResult {
  if (!verify.converged || landing === undefined) {
    return verify;
  }
  if (!checkRunsConverged(landing.checkRuns)) {
    return { ...verify, converged: false };
  }
  return verify;
}

type OnlineReviewRetriggerRecoveryEntry = {
  readonly event?: string;
  readonly onlineReviewRound?: number;
  readonly roundTriggerHeadOid?: string;
  readonly branchHEAD?: string;
};

/** Latest post-fix recovery from a persisted retrigger marker (#600 r29). */
function latestOnlineReviewRetriggerRecovery(
  entries: ReadonlyArray<OnlineReviewRetriggerRecoveryEntry>,
): { readonly round?: number; readonly fixSha?: string } | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (entry.event !== "online_review_round_retrigger") {
      continue;
    }
    const round =
      typeof entry.onlineReviewRound === "number" && entry.onlineReviewRound > 0
        ? entry.onlineReviewRound
        : undefined;
    const fixSha =
      typeof entry.roundTriggerHeadOid === "string" &&
      entry.roundTriggerHeadOid.length > 0
        ? entry.roundTriggerHeadOid
        : typeof entry.branchHEAD === "string" && entry.branchHEAD.length > 0
          ? entry.branchHEAD
          : undefined;
    if (round !== undefined || fixSha !== undefined) {
      return {
        ...(round !== undefined ? { round } : {}),
        ...(fixSha !== undefined ? { fixSha } : {}),
      };
    }
  }
  return undefined;
}

/** 1-based online review round from the full executable ledger (#600 r7 resume). */
export function onlineReviewRoundFromLedger(
  ledger: ReadonlyArray<{
    readonly step: string;
    readonly event?: string;
    readonly onlineReviewRound?: number;
    readonly output?: {
      readonly kind?: string;
      readonly committed?: boolean;
      readonly alreadySatisfied?: boolean;
    };
  }>,
): number {
  const fixCommittedMarkers = ledger.filter(
    (e) => e.event === "online_review_fix_committed",
  ).length;
  const retriggerRecovery = latestOnlineReviewRetriggerRecovery(ledger);
  if (fixCommittedMarkers > 0) {
    return Math.max(fixCommittedMarkers + 1, retriggerRecovery?.round ?? 0);
  }
  if (retriggerRecovery?.round !== undefined) {
    return retriggerRecovery.round;
  }
  const completedFixerRounds = ledger.filter(
    (e) => e.step === "S10" && fixerLedgerOutputProceeds(e.output),
  ).length;
  return completedFixerRounds + 1;
}

/** Last committed S10 branchHEAD — fixing commit for recheck side effects (#600 r7). */
export function lastOnlineReviewFixCommitShaFromLedger(
  ledger: ReadonlyArray<{
    readonly step: string;
    readonly event?: string;
    readonly fixCommitSha?: string;
    readonly roundTriggerHeadOid?: string;
    readonly branchHEAD?: string;
    readonly output?: {
      readonly kind?: string;
      readonly committed?: boolean;
      readonly alreadySatisfied?: boolean;
      readonly fixCommitSha?: string;
    };
  }>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.event === "online_review_fix_committed" &&
      typeof entry.fixCommitSha === "string" &&
      entry.fixCommitSha.length > 0
    ) {
      return entry.fixCommitSha;
    }
    if (entry.step === "S10") {
      const fromS10 = fixerLedgerFixCommitSha(entry);
      if (fromS10 !== undefined) {
        return fromS10;
      }
    }
    if (entry.event === "online_review_round_retrigger") {
      const fromRetrigger = latestOnlineReviewRetriggerRecovery([entry])?.fixSha;
      if (fromRetrigger !== undefined) {
        return fromRetrigger;
      }
    }
  }
  return undefined;
}

/** Latest persisted round ≥2 freshness anchor from ledger (#600 r25 resume). */
export function onlineReviewRoundTriggerFromLedger(
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
  let latestUnpaired: { readonly sha: string; readonly ts: string } | undefined;
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
      latestUnpaired = { sha: entry.familyHeadAfter, ts: entry.ts };
    }
  }
  if (latestUnpaired === undefined) {
    return undefined;
  }
  return buildRoundTrigger(latestUnpaired.sha, latestUnpaired.ts);
}

/**
 * True when audit markers prove the fixer finished but the executable S10 row is
 * still missing (#600 r28). Resume must enter post-fix verify (S9), not re-dispatch
 * the fixer.
 */
export function slicePostFixVerifyPendingFromMarkerGap(
  ledger: ReadonlyArray<{
    readonly step?: string;
    readonly event?: string;
    readonly output?: {
      readonly kind?: string;
      readonly committed?: boolean;
      readonly alreadySatisfied?: boolean;
    };
  }>,
): boolean {
  let lastCommittedS10Idx = -1;
  let lastFixSignalIdx = -1;
  for (let i = 0; i < ledger.length; i++) {
    const entry = ledger[i]!;
    if (
      entry.step === "S10" &&
      entry.event === undefined &&
      fixerLedgerOutputProceeds(entry.output)
    ) {
      lastCommittedS10Idx = i;
    }
    if (
      entry.event === "online_review_fix_committed" ||
      entry.event === "online_review_round_retrigger"
    ) {
      lastFixSignalIdx = i;
    }
  }
  return lastFixSignalIdx > lastCommittedS10Idx;
}

/** Single-slice ledger: S10 fix landed but retrigger persistence crashed mid-gap (#600 r27). */
export function slicePendingRoundTriggerFromFixGap(
  ledger: ReadonlyArray<{
    readonly step?: string;
    readonly event?: string;
    readonly fixCommitSha?: string;
    readonly branchHEAD?: string;
    readonly roundTriggerHeadOid?: string;
    readonly ts?: string;
    readonly output?: {
      readonly kind?: string;
      readonly committed?: boolean;
      readonly alreadySatisfied?: boolean;
      readonly fixCommitSha?: string;
    };
  }>,
): RoundTrigger | undefined {
  const pairedFixShas = new Set<string>();
  for (const entry of ledger) {
    const head = retriggerPairedFixHead(entry);
    if (head !== undefined) {
      pairedFixShas.add(head);
    }
  }

  const fixCommittedShas = new Set<string>();
  const fixSignals: Array<{ readonly sha: string; readonly ts: string }> = [];
  for (const entry of ledger) {
    if (
      entry.event === "online_review_fix_committed" &&
      typeof entry.fixCommitSha === "string" &&
      entry.fixCommitSha.length > 0 &&
      typeof entry.ts === "string" &&
      entry.ts.length > 0
    ) {
      fixCommittedShas.add(entry.fixCommitSha);
      fixSignals.push({ sha: entry.fixCommitSha, ts: entry.ts });
    }
  }
  for (const entry of ledger) {
    const sha = fixerLedgerFixCommitSha(entry);
    if (
      entry.step === "S10" &&
      entry.event === undefined &&
      sha !== undefined &&
      typeof entry.ts === "string" &&
      entry.ts.length > 0 &&
      !fixCommittedShas.has(sha)
    ) {
      fixSignals.push({ sha, ts: entry.ts });
    }
  }

  let latestUnpaired: { readonly sha: string; readonly ts: string } | undefined;
  for (const signal of fixSignals) {
    if (!pairedFixShas.has(signal.sha)) {
      latestUnpaired = signal;
    }
  }
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
 * Round 1 may fall back to the S7 ship ledger timestamp; round ≥2 requires a
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

/** S7 ship ledger `ts` — round-1 freshness anchor (#600 r9). */
export function shipLedgerTriggeredAtFromSliceLedger(
  ledger: ReadonlyArray<{
    readonly step: string;
    readonly output?: { readonly kind?: string };
    readonly ts?: string;
  }>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.step === "S7" &&
      entry.output?.kind === "ship" &&
      typeof entry.ts === "string" &&
      entry.ts.length > 0
    ) {
      return entry.ts;
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
    readonly roundTriggerHeadOid?: string;
    readonly branchHEAD?: string;
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
    if (entry.event === "online_review_round_retrigger") {
      const fromRetrigger = latestOnlineReviewRetriggerRecovery([entry])?.fixSha;
      if (fromRetrigger !== undefined) {
        return fromRetrigger;
      }
    }
  }
  return undefined;
}

/** Latest persisted round ≥2 freshness anchor from the family ledger (#600 r26). */
export function onlineReviewRoundTriggerFromFamilyLedger(
  entries: ReadonlyArray<{
    readonly event?: string;
    readonly roundTriggerHeadOid?: string;
    readonly roundTriggerAt?: string;
  }>,
): RoundTrigger | undefined {
  return onlineReviewRoundTriggerFromLedger(entries);
}

/**
 * Resume-skip / convergence head key from persisted ledger truth (#600 r26, r36, r38).
 * Prefer the latest `online_review_converged` marker's `prHead` (writer always
 * records it; predicate keys on prHead only) so crash-after-marker resume
 * matches durable convergence without a trailing S9 verify output row. Otherwise
 * mirror the marker writer's {@link convergenceHeadToRecord} inputs without relying
 * on in-memory landing or optional ship.prHead.
 */
export function onlineReviewResumeHeadKeyFromLedger(
  ledger: ReadonlyArray<{
    readonly step?: string;
    readonly event?: string;
    readonly prHead?: string;
    readonly branchHEAD?: string;
    readonly output?: {
      readonly kind?: string;
      readonly prHead?: string;
      readonly committed?: boolean;
    };
  }>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.event !== "online_review_converged") continue;
    if (typeof entry.prHead === "string" && entry.prHead.length > 0) {
      return entry.prHead;
    }
    break;
  }
  const postFixHead = lastOnlineReviewFixCommitShaFromLedger(
    ledger.filter(
      (e): e is {
        readonly step: string;
        readonly branchHEAD?: string;
        readonly output?: { readonly kind?: string; readonly committed?: boolean };
      } => typeof e.step === "string",
    ),
  );
  let shipPrHead: string | undefined;
  let branchHeadAfter: string | undefined;
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step === "S7" && entry.output?.kind === "ship") {
      const out = entry.output as { prHead?: string };
      if (typeof out.prHead === "string" && out.prHead.length > 0) {
        shipPrHead = out.prHead;
      }
      break;
    }
  }
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.step === "S9" &&
      entry.output?.kind === "verify" &&
      typeof entry.branchHEAD === "string" &&
      entry.branchHEAD.length > 0
    ) {
      branchHeadAfter = entry.branchHEAD;
      break;
    }
  }
  return convergenceHeadToRecord({
    shipHead: shipPrHead,
    postFixHead,
    branchHeadAfter,
  });
}

/**
 * Runner-owned recheck truth (#600 r26): round ≥2 verify is a post-fixer re-check
 * by construction. Worker omission is normalized; explicit contradiction fails closed.
 */
export function enforceRunnerOwnedRecheck(
  verify: VerifyResult,
  onlineReviewRound: number,
): VerifyResult | { readonly kind: "recheck_contradiction" } {
  const runnerRecheck = onlineReviewRound > 1;
  if (verify.isRecheck === false && runnerRecheck) {
    return { kind: "recheck_contradiction" };
  }
  if (verify.isRecheck === true && !runnerRecheck) {
    return { kind: "recheck_contradiction" };
  }
  if (runnerRecheck) {
    return { ...verify, isRecheck: true };
  }
  return verify;
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

function lastS9VerifyOutputFromLedger(
  ledger: ReadonlyArray<{ readonly step: string; readonly output?: StepOutput }>,
): VerifyResult | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step === "S9" && entry.output?.kind === "verify") {
      return entry.output;
    }
  }
  return undefined;
}

/** Read the persisted bot snapshot written before a crash mid review-loop (#600 r7). */
export function readOnlineReviewSnapshotFile(
  stateDir: string,
): PrReviewSnapshot | undefined {
  const path = join(stateDir, ONLINE_REVIEW_SNAPSHOT_FILE);
  if (!existsSync(path)) return undefined;
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (parsed == null || typeof parsed !== "object") return undefined;
    return parsed as PrReviewSnapshot;
  } catch {
    return undefined;
  }
}

/**
 * Rebuild fixer landing from ledger + persisted snapshot — never from in-memory
 * survivors truncated away by priorLedgerThroughLastShip (#600 r7).
 */
export function reconstructOnlineReviewLandingForResume(input: {
  readonly fullLedger: ReadonlyArray<PersistentLedgerEntry>;
  readonly ship: ShipResult;
  readonly stateDir?: string;
  readonly round: number;
}): WorkerLandingPayload | undefined {
  const snapshot =
    input.stateDir !== undefined
      ? readOnlineReviewSnapshotFile(input.stateDir)
      : undefined;
  if (snapshot === undefined) return undefined;
  const lastVerify = lastS9VerifyOutputFromLedger(input.fullLedger);
  const fixKeys =
    lastVerify !== undefined ? fixMarkedKeysFromVerify(lastVerify) : [];
  return {
    ...buildOnlineReviewLanding(snapshot, input.ship, input.round),
    fixMarkedFindingIdentityKeys: fixKeys,
  };
}

/** Stop summary when fixer reports committed:false (nothing to fix) (#600 r22). */
export function onlineReviewFixerNothingToFixStopSummary(): StopSummary {
  return decisionGateParkStopSummary({
    summary:
      "online review fixer reported nothing to fix (committed:false) while verify still has remaining findings",
    repairHint:
      "answer the decision gate or resolve remaining findings manually, then rerun the online review loop",
  });
}

/** Stop summary when host GitHub verify side effects fail closed (#600 r18). */
export function verifySideEffectFailureStopSummary(err: unknown): StopSummary {
  const detail = err instanceof Error ? err.message : String(err);
  return infraFailureStopSummary({
    summary: `online review verify side effects failed: ${detail}`,
    repairHint:
      "fix GitHub side-effect preconditions (valid PR ref, recheck fixing commit, defer issue creation) and rerun the online review loop",
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
  return infraFailureStopSummary({
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

/** In-band terminal for family/slice review-loop dispatch failures (#600 r7 S2). */
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
  };
}

/**
 * Head key for converged marker, landing shipDelivery.prHead, and resume-skip.
 * Prefer recheck/snapshot/post-fix head over stale S7 ship.prHead once a fix
 * round occurred.
 */
/** @deprecated Prefer {@link convergenceHeadToRecord} — thin alias for call sites. */
export function onlineReviewConvergenceHeadKey(input: {
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

export function onlineReviewConvergedForHead(
  ledger: ReadonlyArray<{ readonly event?: string; readonly prHead?: string }>,
  reviewHead: string | undefined,
): boolean {
  if (reviewHead === undefined) return false;
  return ledger.some((entry) =>
    isReviewLoopConvergedMarker(entry, reviewHead),
  );
}

export function buildOnlineReviewLanding(
  snapshot: PrReviewSnapshot,
  ship: ShipResult,
  round: number,
): WorkerLandingPayload {
  const prHead = onlineReviewConvergenceHeadKey({
    snapshotHeadOid: snapshot.headOid,
    shipPrHead: ship.prHead,
  });
  return {
    onlineReviewSnapshot: toLandingSnapshot(snapshot),
    shipDelivery: {
      branch: ship.branch,
      pr: ship.pr,
      prHead: prHead!,
      status: ship.status,
    },
    onlineReviewRound: round,
  };
}

/** Write the bot snapshot JSON the verify worker reads (state dir, outside git). */
export function writeOnlineReviewSnapshotFile(
  stateDir: string,
  snapshot: PrReviewSnapshot,
): string | undefined {
  const path = join(stateDir, ONLINE_REVIEW_SNAPSHOT_FILE);
  try {
    mkdirSync(stateDir, { recursive: true });
    writeFileSync(path, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
    return path;
  } catch {
    // Best-effort audit artifact — a fake worktree path in unit tests may not be
    // mkdir-able; the landing file in stateDir (via dispatchWorker) is the worker
    // truth when this write is skipped.
    return undefined;
  }
}

/** Injectable clock for host-side bot poll cadence (tests use immediate no-op sleep). */
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
 * Poll until bots are quiescent or the poll budget for this wait is exhausted.
 * Enforces ~2-minute cadence between polls; production defaults to the ~5-poll
 * overdue window. Pass `maxPolls: 1` and `clock: immediateBotPollClock` in unit tests.
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
  const clock = input.clock ?? realBotPollClock;
  let last: PrReviewSnapshot | undefined;
  for (let poll = 1; poll <= maxPolls; poll += 1) {
    last = pollPrReviewState(sh, {
      repo: input.repo,
      prUrl: input.prUrl,
      pollCount: poll,
      roundTrigger: input.roundTrigger,
      botPendingPolls: input.botPendingPolls as never,
    });
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
  const existing = findAdmissibleRetriggerComment(
    input.sh,
    input.repo,
    input.prUrl,
    input.gapTrigger,
  );
  if (existing !== undefined) {
    return { roundTrigger: existing, posted: false };
  }
  const { prNumber } = parsePrRef(input.prUrl, input.repo);
  const headProbe = pollPrReviewState(input.sh, {
    repo: input.repo,
    prUrl: input.prUrl,
    pollCount: 0,
    roundTrigger: input.gapTrigger,
  });
  const triggeredAt = new Date().toISOString();
  postBotRetriggerComment(input.sh, input.repo, prNumber, BOT_RETRIGGER_COMMENT);
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
  return { snapshot, roundTrigger };
}

/** Thrown when a read-only verify worker mutates HEAD (runner catches → contract drift). */
export class VerifyWorkerHeadMovedError extends Error {
  readonly headBefore: string;
  readonly headAfter: string;

  constructor(headBefore: string, headAfter: string) {
    super(
      `online review verify worker moved HEAD: ${headBefore} -> ${headAfter}`,
    );
    this.name = "VerifyWorkerHeadMovedError";
    this.headBefore = headBefore;
    this.headAfter = headAfter;
  }
}

/** Thrown when a read-only verify worker dirties the tracked worktree (#600 r32). */
export class VerifyWorkerWorktreeDirtyError extends Error {
  readonly porcelainBefore: string;
  readonly porcelainAfter: string;

  constructor(porcelainBefore: string, porcelainAfter: string) {
    super(
      "online review verify worker left tracked worktree changes: " +
        porcelainAfter,
    );
    this.name = "VerifyWorkerWorktreeDirtyError";
    this.porcelainBefore = porcelainBefore;
    this.porcelainAfter = porcelainAfter;
  }
}

export function worktreePorcelainFingerprint(
  lines: ReadonlyArray<string>,
): string {
  return lines.map((line) => line.trimEnd()).join("\n");
}

export type VerifyReadOnlyWorktreeDrift =
  | "head"
  | "worktree"
  | undefined;

/** Detect read-only verify contract drift from HEAD or tracked-worktree movement. */
export function verifyReadOnlyWorktreeDrift(input: {
  readonly headBefore: string;
  readonly headAfter: string;
  readonly porcelainBefore: string;
  readonly porcelainAfter: string;
}): VerifyReadOnlyWorktreeDrift {
  if (input.headAfter !== input.headBefore) {
    return "head";
  }
  if (input.porcelainAfter !== input.porcelainBefore) {
    return "worktree";
  }
  return undefined;
}

/** Stop summary when a read-only verify worker moved HEAD (mirrors cmr reviewer guard). */
export function verifyReviewerHeadMovedStopSummary(input: {
  readonly headBefore: string;
  readonly headAfter: string;
}): StopSummary {
  return contractDriftStopSummary({
    summary:
      `online review verify worker moved HEAD: ${input.headBefore} -> ${input.headAfter}`,
    repairHint:
      "restore the verify/fixer role boundary so verify leaves HEAD unchanged, then rerun the online review loop",
    heads: {
      reportedFamilyHead: input.headBefore,
      actualFamilyHead: input.headAfter,
      sources: {
        reportedFamilyHead: "pre-verify branch HEAD",
        actualFamilyHead: "post-verify branch HEAD",
      },
    },
  });
}

/** Stop summary when a read-only verify worker left tracked worktree residue (#600 r32). */
export function verifyReviewerWorktreeDirtyStopSummary(input: {
  readonly trackedStatus: readonly string[];
}): StopSummary {
  return contractDriftStopSummary({
    summary:
      "online review verify worker left tracked worktree changes: " +
      input.trackedStatus.join("; "),
    repairHint:
      "restore the verify/fixer role boundary so verify leaves the tracked worktree clean, then rerun the online review loop",
    metadata: { trackedStatus: input.trackedStatus },
  });
}

export function isReviewLoopConvergedMarker(
  entry: { readonly event?: string; readonly prHead?: string },
  prHead: string,
): boolean {
  return entry.event === "online_review_converged" && entry.prHead === prHead;
}

export interface OnlineReviewLoopDispatch {
  readonly poll: (round: number) => Promise<PrReviewSnapshot>;
  readonly dispatchVerify: (
    landing: WorkerLandingPayload,
    round: number,
  ) => Promise<VerifyResult>;
  readonly dispatchFixer: (landing: WorkerLandingPayload) => Promise<FixerResult>;
  readonly dispatchCleanup: (landing: WorkerLandingPayload) => Promise<boolean>;
  readonly dispatchDocRelease: (landing: WorkerLandingPayload) => Promise<boolean>;
  readonly applySideEffects: (
    landing: WorkerLandingPayload,
    verify: VerifyResult,
    fixingCommitSha?: string,
  ) => VerifyResult;
  readonly retriggerAfterFix: () => void | Promise<void>;
  /**
   * Resolve the fixing commit SHA after fixer success (post-push HEAD).
   * When the fixer envelope carries alreadySatisfied.fixCommitSha, that override
   * is passed so the stage does not re-read git (ADR 0030 envelope-only).
   */
  readonly resolveFixCommitSha?: (
    envelopeFixSha?: string,
  ) => string | Promise<string>;
}

export interface OnlineReviewLoopStageResult {
  readonly ok: boolean;
  readonly terminalState: OnlineReviewTerminalState;
  readonly round: number;
  /** Populated for contract-drift terminals (e.g. read-only verify moved HEAD). */
  readonly stopSummary?: StopSummary;
}

/**
 * Shared online review-loop stage for single-slice and family PRs (#600 AC7).
 * S11/S12 remain stub workers until #603.
 */
export async function runOnlineReviewLoopStage(
  ship: ShipResult,
  dispatch: OnlineReviewLoopDispatch,
  opts?: {
    readonly initialRound?: number;
    readonly initialFixCommitSha?: string;
  },
): Promise<OnlineReviewLoopStageResult> {
  let round = opts?.initialRound ?? 1;
  let lastFixCommitSha = opts?.initialFixCommitSha;

  while (round <= MAX_ONLINE_REVIEW_ROUNDS + 1) {
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

    let verify: VerifyResult;
    try {
      verify = clampVerifyConvergenceForCheckRuns(
        await dispatch.dispatchVerify(landing, round),
        landing.onlineReviewSnapshot,
      );
    } catch (err) {
      if (err instanceof OnlineReviewLoopTerminal) {
        throw err;
      }
      return decisionGateFromDispatchInfra(round, "verify", err);
    }
    const recheckOutcome = enforceRunnerOwnedRecheck(verify, round);
    if (recheckOutcome.kind === "recheck_contradiction") {
      return {
        ok: false,
        terminalState: "decision_gate_raised",
        round,
        stopSummary: {
          reason: "infra_failure",
          summary:
            "online review verify worker contradicted runner-owned recheck truth (isRecheck)",
          repairHint:
            "omit isRecheck on round-1 verify; set isRecheck:true only on post-fixer re-check rounds",
        },
      };
    }
    verify = recheckOutcome;
    try {
      verify = dispatch.applySideEffects(
        landing,
        verify,
        round > 1 ? lastFixCommitSha : undefined,
      );
    } catch (err) {
      if (err instanceof OnlineReviewLoopTerminal) {
        throw err;
      }
      return {
        ok: false,
        terminalState: "decision_gate_raised",
        round,
        stopSummary: verifySideEffectFailureStopSummary(err),
      };
    }
    const fixKeys = fixMarkedKeysFromVerify(verify);
    landing = { ...landing, fixMarkedFindingIdentityKeys: fixKeys };

    if (verify.converged) {
      const cleanupOk = await dispatch.dispatchCleanup(landing);
      if (!cleanupOk) {
        return { ok: false, terminalState: "decision_gate_raised", round };
      }
      const released = await dispatch.dispatchDocRelease(landing);
      if (!released) {
        return { ok: false, terminalState: "decision_gate_raised", round };
      }
      return { ok: true, terminalState: "mergeable", round };
    }

    // ADR 0061: round MAX+1 is verify-only — no further fixer after the cap.
    if (round > MAX_ONLINE_REVIEW_ROUNDS) {
      return { ok: false, terminalState: "round_budget_exhausted", round };
    }

    let fixerOutput: FixerResult;
    try {
      fixerOutput = await dispatch.dispatchFixer(landing);
    } catch (err) {
      if (err instanceof OnlineReviewLoopTerminal) {
        throw err;
      }
      return decisionGateFromDispatchInfra(round, "fixer", err);
    }
    if (!fixerProceedsToVerify(fixerOutput)) {
      return {
        ok: false,
        terminalState: "decision_gate_raised",
        round,
        stopSummary: onlineReviewFixerNothingToFixStopSummary(),
      };
    }
    try {
      lastFixCommitSha =
        (await dispatch.resolveFixCommitSha?.(
          fixerEnvelopeFixCommitSha(fixerOutput),
        )) ?? snapshot.headOid;
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
        stopSummary: verifySideEffectFailureStopSummary(err),
      };
    }
    round += 1;
  }

  return { ok: false, terminalState: "round_budget_exhausted", round };
}