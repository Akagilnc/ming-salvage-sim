/**
 * Online PR review-loop orchestration helpers (#600).
 *
 * Host-side deterministic glue between bot polling, verify/fixer worker dispatch,
 * and ledger markers. Worker judgment (fix / reject / defer) stays inside the
 * verify worker; the runner only counts findings and enforces the 3-round cap
 * (ADR 0061 / ADR 0062).
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import type { PrReviewSnapshot } from "./botPolling.js";
import type { Sh } from "./familyDriver.js";
import {
  BOT_RETRIGGER_COMMENT,
  pollPrReviewState,
  postBotRetriggerComment,
} from "./botPolling.js";
import type {
  OnlineReviewLandingSnapshot,
  ShipResult,
  WorkerLandingPayload,
} from "./types.js";
import type { StopSummary } from "./stopSummary.js";
import { contractDriftStopSummary } from "./stopSummary.js";

/** Hard cap on online review rounds — runner-enforced (ADR 0061). */
export const MAX_ONLINE_REVIEW_ROUNDS = 3;

export const ONLINE_REVIEW_SNAPSHOT_FILE = "online-review-snapshot.json";
export const ONLINE_REVIEW_LANDING_FILE = ".orchestrator-online-review.json";

export type OnlineReviewTerminalState =
  | "mergeable"
  | "round_budget_exhausted"
  | "decision_gate_raised";

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
    threads: snapshot.threads.map((t) => ({
      id: t.id,
      body: t.body,
      isResolved: t.isResolved,
      headOid: t.headOid,
      authorLogin: t.authorLogin,
    })),
  };
}

export function buildOnlineReviewLanding(
  snapshot: PrReviewSnapshot,
  ship: ShipResult,
  round: number,
): WorkerLandingPayload {
  return {
    onlineReviewSnapshot: toLandingSnapshot(snapshot),
    shipDelivery: {
      branch: ship.branch,
      pr: ship.pr,
      prHead: ship.prHead ?? snapshot.headOid,
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

/**
 * Poll until bots are quiescent or the poll budget for this wait is exhausted.
 * `maxPolls` defaults to 1 for unit tests; production callers pass higher budgets.
 */
export function waitForBotQuiescence(
  sh: Sh,
  input: {
    readonly repo: string;
    readonly prUrl: string;
    readonly maxPolls?: number;
    readonly botPendingPolls?: Readonly<Partial<Record<string, number>>>;
  },
): PrReviewSnapshot {
  const maxPolls = input.maxPolls ?? 1;
  let last: PrReviewSnapshot | undefined;
  for (let poll = 1; poll <= maxPolls; poll += 1) {
    last = pollPrReviewState(sh, {
      repo: input.repo,
      prUrl: input.prUrl,
      pollCount: poll,
      botPendingPolls: input.botPendingPolls as never,
    });
    if (last.quiescent) return last;
  }
  return last!;
}

/** Post R2/R3 re-trigger then poll once (caller may loop). */
export function retriggerBotsAndPoll(
  sh: Sh,
  repo: string,
  prUrl: string,
  pollCount: number,
): PrReviewSnapshot {
  const { prNumber } = pollPrReviewState(sh, {
    repo,
    prUrl,
    pollCount: 0,
    botPendingPolls: {},
  });
  postBotRetriggerComment(sh, repo, prNumber, BOT_RETRIGGER_COMMENT);
  return pollPrReviewState(sh, { repo, prUrl, pollCount });
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