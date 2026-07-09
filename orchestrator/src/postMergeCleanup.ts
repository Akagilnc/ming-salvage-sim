/**
 * #603 — post-merge cleanup: live GitHub/git verify+act for issue close + branch delete.
 */

import {
  fetchPrMergeLiveState,
  type PrMergedTerminalRecord,
} from "./autoMerge.js";
import { isLiveGithubReviewPollEnabled } from "./botPolling.js";
import type { Sh } from "./familyDriver.js";
import type {
  CleanupBranchOutcome,
  CleanupResult,
  DispatchContext,
  WorkerLandingPayload,
} from "./types.js";

export interface LiveSubIssue {
  readonly number: number;
  readonly state: string;
}

export interface PostMergeCleanupActs {
  readonly allStepsComplete: boolean;
  readonly issuesClosed?: readonly number[];
  readonly parentIssueClosed?: boolean;
  readonly branchOutcome?: CleanupBranchOutcome;
  readonly skippedReasons?: readonly string[];
}

export interface PostMergeCleanupInput {
  readonly sh: Sh;
  readonly repo: string;
  readonly coveredIssues: readonly number[];
  readonly prMerged: PrMergedTerminalRecord;
  readonly parentIssue?: number;
  readonly closeIssue?: (issue: number) => void;
  readonly deleteBranch?: (branch: string) => void;
  readonly fetchBranchTip?: (branch: string) => string | undefined;
  readonly branchExists?: (branch: string) => boolean;
  readonly fetchSubIssues?: (parent: number) => readonly LiveSubIssue[];
  readonly fetchIssueState?: (issue: number) => string;
}

export function branchTipMatchesMergedHead(
  branchTip: string | undefined,
  mergedHeadOid: string,
): boolean {
  return (
    typeof branchTip === "string" &&
    branchTip.trim().length > 0 &&
    branchTip === mergedHeadOid
  );
}

export type BranchDeletePrecondition =
  | "may_delete"
  | "already_gone"
  | "skip_tip_drift"
  | "skip_pr_not_merged";

export function assessBranchDeletePrecondition(input: {
  readonly prState: string;
  readonly branchExists: boolean;
  readonly branchTip?: string;
  readonly mergedHeadOid: string;
}): BranchDeletePrecondition {
  if (input.prState !== "MERGED") return "skip_pr_not_merged";
  if (!input.branchExists) return "already_gone";
  if (!branchTipMatchesMergedHead(input.branchTip, input.mergedHeadOid)) {
    return "skip_tip_drift";
  }
  return "may_delete";
}

export function shouldCloseParentIssue(
  subIssues: readonly LiveSubIssue[],
  coveredIssues: readonly number[],
): boolean {
  const covered = new Set(coveredIssues);
  return subIssues.every(
    (s) =>
      s.state.toUpperCase() === "CLOSED" || covered.has(s.number),
  );
}

function subIssueNodes(parsed: unknown): unknown[] {
  if (Array.isArray(parsed)) return parsed;
  if (parsed === null || typeof parsed !== "object") return [];
  const sub = (parsed as { subIssues?: unknown }).subIssues;
  if (sub === null || typeof sub !== "object") return [];
  const nodes = (sub as { nodes?: unknown }).nodes;
  return Array.isArray(nodes) ? nodes : [];
}

function parseLiveSubIssue(node: unknown): LiveSubIssue | undefined {
  if (node === null || typeof node !== "object") return undefined;
  const number = (node as { number?: unknown }).number;
  const state = (node as { state?: unknown }).state;
  if (typeof number !== "number" || !Number.isFinite(number)) return undefined;
  if (typeof state !== "string" || state.trim().length === 0) return undefined;
  return { number, state };
}

/** Paginated native sub-issues (per_page=100, page until short). */
export function fetchPaginatedSubIssues(
  sh: Sh,
  repo: string,
  epicIssue: number,
): readonly LiveSubIssue[] {
  const all: LiveSubIssue[] = [];
  for (let page = 1; ; page += 1) {
    const raw = sh("gh", [
      "api",
      `repos/${repo}/issues/${epicIssue}/sub_issues?per_page=100&page=${page}`,
    ]);
    const nodes = subIssueNodes(JSON.parse(raw));
    for (const node of nodes) {
      const parsed = parseLiveSubIssue(node);
      if (parsed !== undefined) all.push(parsed);
    }
    if (nodes.length < 100) break;
  }
  return all;
}

function defaultFetchIssueState(sh: Sh, repo: string, issue: number): string {
  const raw = sh("gh", [
    "api",
    `repos/${repo}/issues/${issue}`,
    "--jq",
    ".state",
  ]);
  return raw.trim();
}

function defaultBranchExists(
  sh: Sh,
  repo: string,
  branch: string,
): boolean {
  try {
    sh("gh", [
      "api",
      `repos/${repo}/git/ref/heads/${encodeURIComponent(branch)}`,
      "--jq",
      ".object.sha",
    ]);
    return true;
  } catch {
    return false;
  }
}

function defaultFetchBranchTip(
  sh: Sh,
  repo: string,
  branch: string,
): string | undefined {
  try {
    const raw = sh("gh", [
      "api",
      `repos/${repo}/git/ref/heads/${encodeURIComponent(branch)}`,
      "--jq",
      ".object.sha",
    ]);
    const tip = raw.trim();
    return tip.length > 0 ? tip : undefined;
  } catch {
    return undefined;
  }
}

function defaultCloseIssue(sh: Sh, repo: string, issue: number): void {
  sh("gh", ["issue", "close", String(issue), "--repo", repo]);
}

function defaultDeleteBranch(sh: Sh, repo: string, branch: string): void {
  sh("gh", [
    "api",
    `-XDELETE`,
    `repos/${repo}/git/refs/heads/${encodeURIComponent(branch)}`,
  ]);
}

export function cleanupResultFromActs(acts: PostMergeCleanupActs): CleanupResult {
  return {
    kind: "cleanup",
    terminal: acts.allStepsComplete,
    ok: acts.allStepsComplete,
    ...(acts.issuesClosed !== undefined && acts.issuesClosed.length > 0
      ? { issuesClosed: [...acts.issuesClosed] }
      : {}),
    ...(acts.parentIssueClosed === true ? { parentIssueClosed: true } : {}),
    ...(acts.branchOutcome !== undefined
      ? { branchOutcome: acts.branchOutcome }
      : {}),
    ...(acts.skippedReasons !== undefined && acts.skippedReasons.length > 0
      ? { skippedReasons: [...acts.skippedReasons] }
      : {}),
  };
}

/**
 * Verify live PR MERGED + merged-head match, then close covered issues and delete
 * the merged branch when preconditions hold. Skips individual steps rather than
 * performing unsafe remote acts.
 */
export function runPostMergeCleanup(
  input: PostMergeCleanupInput,
): CleanupResult {
  const skippedReasons: string[] = [];
  const issuesClosed: number[] = [];

  const offlineSynthetic = !isLiveGithubReviewPollEnabled(
    input.prMerged.prUrl,
    input.repo,
  );

  let live;
  if (offlineSynthetic) {
    live = {
      prNumber: input.prMerged.prNumber,
      prUrl: input.prMerged.prUrl,
      state: "MERGED",
      headOid: input.prMerged.mergedHeadOid,
      headRefName: input.prMerged.remoteBranchName,
      mergeStateStatus: "UNKNOWN",
    };
  } else {
    try {
      live = fetchPrMergeLiveState(input.sh, input.repo, input.prMerged.prUrl);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      return cleanupResultFromActs({
        allStepsComplete: false,
        skippedReasons: [`live_pr_fetch_failed:${detail}`],
        branchOutcome: "skipped_pr_not_merged",
      });
    }
  }

  if (live.state !== "MERGED") {
    return cleanupResultFromActs({
      allStepsComplete: false,
      skippedReasons: ["pr_not_merged"],
      branchOutcome: "skipped_pr_not_merged",
    });
  }

  if (live.headOid !== input.prMerged.mergedHeadOid) {
    return cleanupResultFromActs({
      allStepsComplete: false,
      skippedReasons: ["merged_head_mismatch"],
      branchOutcome: "skipped_precondition",
    });
  }

  const fetchIssueState =
    input.fetchIssueState ??
    ((issue) => defaultFetchIssueState(input.sh, input.repo, issue));
  const closeIssue =
    input.closeIssue ??
    ((issue) => defaultCloseIssue(input.sh, input.repo, issue));

  for (const issue of input.coveredIssues) {
    const state = fetchIssueState(issue);
    if (state.toUpperCase() !== "CLOSED") {
      closeIssue(issue);
      issuesClosed.push(issue);
    }
  }

  let parentClosedThisRun = false;
  if (input.parentIssue !== undefined) {
    const subIssues =
      input.fetchSubIssues?.(input.parentIssue) ??
      fetchPaginatedSubIssues(input.sh, input.repo, input.parentIssue);
    if (shouldCloseParentIssue(subIssues, input.coveredIssues)) {
      const parentState = fetchIssueState(input.parentIssue);
      if (parentState.toUpperCase() !== "CLOSED") {
        closeIssue(input.parentIssue);
        parentClosedThisRun = true;
      }
    }
  }

  const branch = input.prMerged.remoteBranchName;
  const branchExistsFn =
    input.branchExists ??
    ((b) => defaultBranchExists(input.sh, input.repo, b));
  const fetchTipFn =
    input.fetchBranchTip ??
    ((b) => defaultFetchBranchTip(input.sh, input.repo, b));
  const exists = branchExistsFn(branch);
  const precondition = assessBranchDeletePrecondition({
    prState: live.state,
    branchExists: exists,
    branchTip: exists ? fetchTipFn(branch) : undefined,
    mergedHeadOid: input.prMerged.mergedHeadOid,
  });

  let branchOutcome: CleanupBranchOutcome;
  let parentIssueClosed: boolean | undefined;

  if (input.parentIssue !== undefined) {
    if (parentClosedThisRun) {
      parentIssueClosed = true;
    } else {
      const parentState = fetchIssueState(input.parentIssue);
      parentIssueClosed = parentState.toUpperCase() === "CLOSED";
    }
  }

  switch (precondition) {
    case "may_delete": {
      const deleteBranch =
        input.deleteBranch ??
        ((b) => defaultDeleteBranch(input.sh, input.repo, b));
      deleteBranch(branch);
      branchOutcome = "deleted";
      break;
    }
    case "already_gone":
      branchOutcome = "already_gone";
      break;
    case "skip_tip_drift":
      skippedReasons.push("branch_tip_drift");
      branchOutcome = "skipped_tip_drift";
      break;
    case "skip_pr_not_merged":
      skippedReasons.push("pr_not_merged");
      branchOutcome = "skipped_pr_not_merged";
      return cleanupResultFromActs({
        allStepsComplete: false,
        issuesClosed,
        parentIssueClosed,
        branchOutcome,
        skippedReasons,
      });
    default: {
      const never: never = precondition;
      throw new Error(`unexpected branch delete precondition: ${String(never)}`);
    }
  }

  return cleanupResultFromActs({
    allStepsComplete: true,
    issuesClosed,
    parentIssueClosed,
    branchOutcome,
    ...(skippedReasons.length > 0 ? { skippedReasons } : {}),
  });
}

export function buildCleanupLanding(input: {
  readonly record: PrMergedTerminalRecord;
  readonly coveredIssues: readonly number[];
  readonly parentIssue?: number;
}): NonNullable<WorkerLandingPayload["cleanupDispatch"]> {
  return {
    coveredIssues: [...input.coveredIssues],
    ...(input.parentIssue !== undefined ? { parentIssue: input.parentIssue } : {}),
    prUrl: input.record.prUrl,
    prNumber: input.record.prNumber,
    remoteBranchName: input.record.remoteBranchName,
    mergedHeadOid: input.record.mergedHeadOid,
    convergedHeadOid: input.record.convergedHeadOid,
  };
}

/** Deterministic post-merge cleanup dispatch (#603) — verify+act, no LLM judgment. */
export function dispatchPostMergeCleanup(
  landing: WorkerLandingPayload | undefined,
  ctx: Pick<DispatchContext, "repo">,
  sh: Sh,
): CleanupResult {
  const dispatch = landing?.cleanupDispatch;
  if (dispatch === undefined) {
    throw new Error(
      "cleanup dispatch requires cleanupDispatch landing payload with pr_merged record",
    );
  }
  const repo = ctx.repo?.trim() ?? process.env.ORCHESTRATOR_REPO?.trim() ?? "";
  if (repo.length === 0) {
    throw new Error("cleanup dispatch requires repo on DispatchContext");
  }
  return runPostMergeCleanup({
    sh,
    repo,
    coveredIssues: dispatch.coveredIssues,
    ...(dispatch.parentIssue !== undefined
      ? { parentIssue: dispatch.parentIssue }
      : {}),
    prMerged: {
      prUrl: dispatch.prUrl,
      prNumber: dispatch.prNumber,
      remoteBranchName: dispatch.remoteBranchName,
      mergedHeadOid: dispatch.mergedHeadOid,
      convergedHeadOid: dispatch.convergedHeadOid,
    },
  });
}
