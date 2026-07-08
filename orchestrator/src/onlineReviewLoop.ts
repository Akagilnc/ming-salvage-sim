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
  pollPrReviewState,
  postBotRetriggerComment,
} from "./botPolling.js";
import type {
  OnlineReviewLandingSnapshot,
  OnlineReviewTerminalState,
  PersistentLedgerEntry,
  ShipResult,
  StepOutput,
  VerifyResult,
  WorkerLandingPayload,
} from "./types.js";
import {
  applyVerifySideEffects,
  fixMarkedKeysFromVerify,
} from "./onlineReviewSideEffects.js";
import type { StopSummary } from "./stopSummary.js";
import { contractDriftStopSummary } from "./stopSummary.js";

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
      body: t.body,
      isResolved: t.isResolved,
      headOid: t.headOid,
      authorLogin: t.authorLogin,
    })),
  };
}

/** 1-based online review round from the full executable ledger (#600 r7 resume). */
export function onlineReviewRoundFromLedger(
  ledger: ReadonlyArray<{
    readonly step: string;
    readonly output?: { readonly kind?: string; readonly committed?: boolean };
  }>,
): number {
  const completedFixerRounds = ledger.filter(
    (e) =>
      e.step === "S10" &&
      e.output?.kind === "fixer" &&
      e.output.committed,
  ).length;
  return completedFixerRounds + 1;
}

/** Last committed S10 branchHEAD — fixing commit for recheck side effects (#600 r7). */
export function lastOnlineReviewFixCommitShaFromLedger(
  ledger: ReadonlyArray<{
    readonly step: string;
    readonly branchHEAD?: string;
    readonly output?: { readonly kind?: string; readonly committed?: boolean };
  }>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.step === "S10" &&
      entry.output?.kind === "fixer" &&
      entry.output.committed &&
      typeof entry.branchHEAD === "string" &&
      entry.branchHEAD.length > 0
    ) {
      return entry.branchHEAD;
    }
  }
  return undefined;
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
  postBotRetriggerComment(sh, repo, headProbe.prNumber, BOT_RETRIGGER_COMMENT);
  const roundTrigger = buildRoundTrigger(headProbe.headOid);
  const snapshot = pollPrReviewState(sh, {
    repo,
    prUrl,
    pollCount,
    roundTrigger,
  });
  return { snapshot, roundTrigger };
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
  readonly dispatchFixer: (landing: WorkerLandingPayload) => Promise<boolean>;
  readonly dispatchCleanup: (landing: WorkerLandingPayload) => Promise<boolean>;
  readonly dispatchDocRelease: (landing: WorkerLandingPayload) => Promise<boolean>;
  readonly applySideEffects: (
    verify: VerifyResult,
    fixingCommitSha?: string,
  ) => VerifyResult;
  readonly retriggerAfterFix: () => void;
  /** Resolve the fixing commit SHA after fixer success (post-push HEAD). */
  readonly resolveFixCommitSha?: () => string | Promise<string>;
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
  dispatch: OnlineReviewLoopDispatch,
): Promise<OnlineReviewLoopStageResult> {
  let round = 1;
  let lastFixCommitSha: string | undefined;

  while (round <= MAX_ONLINE_REVIEW_ROUNDS + 1) {
    const snapshot = await dispatch.poll(round);
    let landing = buildOnlineReviewLanding(
      snapshot,
      {
        kind: "ship",
        branch: "family-base",
        status: "pr_opened",
        pr: snapshot.prUrl,
        prHead: snapshot.headOid,
      },
      round,
    );

    let verify = await dispatch.dispatchVerify(landing, round);
    verify = dispatch.applySideEffects(
      verify,
      verify.isRecheck ? lastFixCommitSha : undefined,
    );
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

    const committed = await dispatch.dispatchFixer(landing);
    if (!committed) {
      return { ok: false, terminalState: "decision_gate_raised", round };
    }
    lastFixCommitSha =
      (await dispatch.resolveFixCommitSha?.()) ?? snapshot.headOid;
    dispatch.retriggerAfterFix();
    round += 1;
  }

  return { ok: false, terminalState: "round_budget_exhausted", round };
}