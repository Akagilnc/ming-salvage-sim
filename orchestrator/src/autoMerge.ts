/**
 * Live GitHub PR merge primitives for the Landing Action (#941 / #934 ID-013).
 *
 * Host auto-merge stage courts (runAutoMergeStage, readiness/HEAD/marker
 * second-guess, offline synthetic MERGED hatch) are deleted. Landing Action
 * owns merge readiness, merge execution, and live MERGED confirm.
 */

import {
  classifyCheckRuns,
  parsePrRef,
  unresolvedThreadCount,
  type PrReviewSnapshot,
} from "./botPolling.js";
import type { Sh } from "./familyDriver.js";

export type MergeReadinessBlocker =
  | "threads_unresolved"
  | "ci_pending"
  | "ci_failed"
  | "ruleset_blocked"
  | "not_open";

export interface PrMergeLiveState {
  readonly prNumber: number;
  readonly prUrl: string;
  readonly state: string;
  readonly headOid: string;
  readonly headRefName: string;
  /** GitHub's owner login for the PR head repository. */
  readonly headRepositoryOwnerLogin?: string;
  readonly baseRefName?: string;
  readonly mergeStateStatus: string;
  readonly mergeable?: string;
}

export interface MergeReadinessResult {
  readonly ready: boolean;
  readonly blockers: readonly MergeReadinessBlocker[];
  readonly live: PrMergeLiveState;
  readonly snapshot: PrReviewSnapshot;
  readonly ciGate: "converged" | "pending" | "failed";
  readonly unresolvedThreads: number;
}

export interface PrMergedTerminalRecord {
  readonly prUrl: string;
  readonly prNumber: number;
  readonly remoteBranchName: string;
  readonly mergedHeadOid: string;
  readonly convergedHeadOid: string;
}

/**
 * Case/whitespace-insensitive GitHub field compare (state, mergeStateStatus, …).
 * Single authority for MERGED/OPEN/CLOSED predicates across landing, autoMerge,
 * and postMergeCleanup — do not re-copy `.toUpperCase() ===` / bare `===`.
 */
export function githubFieldEquals(
  actual: string | undefined,
  expected: string,
): boolean {
  return actual?.trim().toLowerCase() === expected.trim().toLowerCase();
}

function parsePrMergeLivePayload(raw: string, prUrl: string): PrMergeLiveState {
  const parsed: unknown = JSON.parse(raw);
  if (parsed === null || parsed === undefined || typeof parsed !== "object") {
    throw new Error(`autoMerge: malformed gh pr view payload for ${prUrl}`);
  }
  const obj = parsed as Record<string, unknown>;
  const prNumber = typeof obj.number === "number" ? obj.number : NaN;
  const url = typeof obj.url === "string" ? obj.url.trim() : "";
  const state = typeof obj.state === "string" ? obj.state.trim() : "";
  const headRefName =
    typeof obj.headRefName === "string" ? obj.headRefName.trim() : "";
  const headRefOid =
    typeof obj.headRefOid === "string" ? obj.headRefOid.trim() : "";
  const headRepositoryOwner = obj.headRepositoryOwner;
  const headRepositoryOwnerRecord =
    headRepositoryOwner !== null && typeof headRepositoryOwner === "object"
      ? (headRepositoryOwner as Record<string, unknown>)
      : undefined;
  const ownerLogin = headRepositoryOwnerRecord?.login;
  const headRepositoryOwnerLogin =
    typeof ownerLogin === "string" ? ownerLogin.trim() : "";
  const mergeStateStatus =
    typeof obj.mergeStateStatus === "string" ? obj.mergeStateStatus.trim() : "";
  const mergeable =
    typeof obj.mergeable === "string" ? obj.mergeable.trim() : undefined;
  const baseRefName =
    typeof obj.baseRefName === "string" ? obj.baseRefName.trim() : undefined;
  if (!Number.isFinite(prNumber) || prNumber <= 0) {
    throw new Error(`autoMerge: gh pr view missing pr number for ${prUrl}`);
  }
  if (headRefOid.length === 0) {
    throw new Error(`autoMerge: gh pr view missing headRefOid for ${prUrl}`);
  }
  return {
    prNumber,
    prUrl: url.length > 0 ? url : prUrl,
    state,
    headOid: headRefOid,
    headRefName,
    ...(headRepositoryOwnerLogin.length > 0 ? { headRepositoryOwnerLogin } : {}),
    ...(baseRefName !== undefined ? { baseRefName } : {}),
    mergeStateStatus,
    ...(mergeable !== undefined ? { mergeable } : {}),
  };
}

/** Live GitHub PR metadata for merge gating (never cached by callers). */
export function fetchPrMergeLiveState(
  sh: Sh,
  repo: string,
  prUrl: string,
): PrMergeLiveState {
  const { prNumber } = parsePrRef(prUrl, repo);
  const raw = sh("gh", [
    "pr",
    "view",
    String(prNumber),
    "--repo",
    repo,
    "--json",
    "number,url,state,baseRefName,headRefName,headRefOid,headRepositoryOwner,mergeStateStatus,mergeable",
  ]);
  return parsePrMergeLivePayload(raw, prUrl);
}

/** Landing Action readiness helper (owned by landing, not a host court). */
export function assessMergeReadiness(
  live: PrMergeLiveState,
  snapshot: PrReviewSnapshot,
): MergeReadinessResult {
  const blockers: MergeReadinessBlocker[] = [];
  if (!githubFieldEquals(live.state, "OPEN") && !githubFieldEquals(live.state, "MERGED")) {
    blockers.push("not_open");
  }
  if (
    githubFieldEquals(live.state, "OPEN") &&
    !githubFieldEquals(live.mergeStateStatus, "CLEAN")
  ) {
    blockers.push("ruleset_blocked");
  }
  const unresolvedThreads = unresolvedThreadCount(snapshot);
  if (unresolvedThreads > 0) {
    blockers.push("threads_unresolved");
  }
  const ciGate = classifyCheckRuns(
    snapshot.checkRuns,
    snapshot.checkRunsEmptyMeans,
  );
  if (ciGate === "pending") blockers.push("ci_pending");
  if (ciGate === "failed") blockers.push("ci_failed");
  return {
    ready: blockers.length === 0 && githubFieldEquals(live.state, "OPEN"),
    blockers,
    live,
    snapshot,
    ciGate,
    unresolvedThreads,
  };
}

/** Execute a merge commit (never squash) via gh. */
export function executePrMergeCommit(
  sh: Sh,
  repo: string,
  prNumber: number,
  expectedHeadOid: string,
): void {
  sh("gh", [
    "pr",
    "merge",
    String(prNumber),
    "--merge",
    "--match-head-commit",
    expectedHeadOid,
    "--repo",
    repo,
  ]);
}

/** Confirm merge via live GitHub state — not the merge command's exit code. */
export function confirmPrMergedLive(
  sh: Sh,
  repo: string,
  prUrl: string,
  expectedHeadOid: string,
): PrMergedTerminalRecord | undefined {
  const live = fetchPrMergeLiveState(sh, repo, prUrl);
  if (!githubFieldEquals(live.state, "MERGED")) return undefined;
  if (live.headOid !== expectedHeadOid) return undefined;
  return {
    prUrl: live.prUrl,
    prNumber: live.prNumber,
    remoteBranchName: live.headRefName,
    mergedHeadOid: live.headOid,
    convergedHeadOid: expectedHeadOid,
  };
}

export function prMergedRecordFromLive(
  live: PrMergeLiveState,
  convergedHeadOid: string,
): PrMergedTerminalRecord | undefined {
  if (!githubFieldEquals(live.state, "MERGED")) return undefined;
  if (live.headOid.length === 0) return undefined;
  return {
    prUrl: live.prUrl,
    prNumber: live.prNumber,
    remoteBranchName: live.headRefName,
    mergedHeadOid: live.headOid,
    convergedHeadOid,
  };
}

export interface PrMergedMarkerLike {
  readonly event?: string;
  readonly prHead?: string;
  readonly mergedHeadOid?: string;
}

export function isPrMergedMarker(
  entry: PrMergedMarkerLike,
  convergedHeadOid: string,
): boolean {
  return (
    entry.event === "pr_merged" &&
    typeof entry.mergedHeadOid === "string" &&
    entry.mergedHeadOid.trim().length > 0 &&
    (entry.prHead === undefined || entry.prHead === convergedHeadOid)
  );
}

