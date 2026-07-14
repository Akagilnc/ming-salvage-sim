/**
 * Host-side automatic PR merge after online review + doc-release (#602).
 *
 * Deterministic gh queries + merge execution — no LLM. Merge-readiness always
 * re-queries live GitHub state (mergeStateStatus / threads / CI), never a cache.
 */

import { shWithClock } from "./externalCall.js";

import {
  classifyCheckRuns,
  isLiveGithubReviewPollEnabled,
  parsePrRef,
  unresolvedThreadCount,
  type PrReviewSnapshot,
} from "./botPolling.js";
import type { Sh } from "./familyDriver.js";
import type { StopSummary } from "./stopSummary.js";

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


export type AutoMergeTerminalState =
  | "merged"
  | "not_ready"
  | "decision_gate"
  | "externally_merged_never_converged"
  | "already_recorded";

function githubFieldEquals(actual: string | undefined, expected: string): boolean {
  return actual?.trim().toLowerCase() === expected.trim().toLowerCase();
}

export interface AutoMergeStageResult {
  readonly ok: boolean;
  readonly terminalState: AutoMergeTerminalState;
  readonly record?: PrMergedTerminalRecord;
  readonly stopSummary?: StopSummary;
}

/**
 * Historical helper: was the #602 doc-only path allowlist for merge veto.
 * ADR 0123 / #735 removed that veto — kept for diagnostics / tests only.
 * Do not reintroduce as a silent second merge gate without a new ADR.
 */
export function isDocOnlyPath(path: string): boolean {
  const normalized = path.trim().replace(/\\/g, "/");
  if (normalized.length === 0) return false;
  if (normalized.includes("..")) return false;
  if (normalized === "VERSION") return true;
  if (normalized === "CHANGELOG.md") return true;
  if (normalized === "orchestrator/CHANGELOG.md") return true;
  if (normalized.startsWith("docs/") && normalized.length > "docs/".length) {
    return true;
  }
  return false;
}

/** Historical helper (ADR 0123: not a merge gate). See {@link isDocOnlyPath}. */
export function isDocOnlyFileList(files: readonly string[]): boolean {
  return files.length > 0 && files.every(isDocOnlyPath);
}

function normalizeDocReleaseGitPath(line: string): string | undefined {
  const trimmed = line.trim();
  if (trimmed.length === 0) return undefined;
  const renameTarget = trimmed.includes(" -> ")
    ? trimmed.slice(trimmed.lastIndexOf(" -> ") + 4)
    : trimmed;
  const unquoted =
    renameTarget.startsWith('"') && renameTarget.endsWith('"')
      ? renameTarget.slice(1, -1)
      : renameTarget;
  const normalized = unquoted.trim().replace(/\\/g, "/");
  return normalized.length > 0 ? normalized : undefined;
}

/** Paths changed by a specific commit (diagnostics / tip inspection; not a merge veto after ADR 0123). */
export function docReleasePathsFromCommit(
  repoPath: string | undefined,
  commitOid: string | undefined,
): readonly string[] | undefined {
  if (repoPath === undefined || commitOid === undefined) return undefined;
  const oid = commitOid.trim();
  if (oid.length === 0) return undefined;
  try {
    const raw = shWithClock(
      "git",
      [
        "-C",
        repoPath,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        oid,
      ],
      { stage: "reconcile:git-diff-tree" },
    );
    const paths = raw
      .split(/\r?\n/)
      .map((line) => normalizeDocReleaseGitPath(line))
      .filter((p): p is string => p !== undefined);
    return paths.length > 0 ? paths : undefined;
  } catch {
    return undefined;
  }
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

export function mergeReadinessStopSummary(
  blockers: readonly MergeReadinessBlocker[],
): StopSummary {
  const pendingOnly =
    blockers.length > 0 && blockers.every((b) => b === "ci_pending");
  return {
    reason: "decision_gate_park",
    summary: `PR merge readiness blocked: ${blockers.join(", ")}`,
    repairHint: pendingOnly
      ? "wait for post-doc-release CI to finish, then re-feed to resume auto-merge"
      : "resolve merge blockers (ruleset, threads, CI) or answer the decision gate",
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
  expectedMergeHeadOid?: string,
): PrMergedTerminalRecord | undefined {
  if (!githubFieldEquals(live.state, "MERGED")) return undefined;
  if (live.headOid.length === 0) return undefined;
  const hasExpected =
    expectedMergeHeadOid !== undefined && expectedMergeHeadOid.trim().length > 0;
  if (
    hasExpected &&
    expectedMergeHeadOid !== convergedHeadOid
  ) {
    if (live.headOid !== expectedMergeHeadOid) return undefined;
  } else if (live.headOid !== convergedHeadOid) {
    return undefined;
  }
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

export interface AutoMergeStageInput {
  readonly sh: Sh;
  readonly repo: string;
  readonly prUrl: string;
  readonly convergedHeadOid: string;
  /** Post-doc-release PR tip when it differs from the #600 convergence key. */
  readonly expectedMergeHeadOid?: string;
  readonly docReleaseCompleted: boolean;
  readonly priorConvergenceRecorded: boolean;
  readonly prMergedMarkerPresent: boolean;
  readonly poll: (round: number) => Promise<PrReviewSnapshot>;
  /** Optional diagnostic: paths changed by the doc-release commit (not a merge veto after ADR 0123). */
  readonly docReleasePaths?: readonly string[];
  readonly executeMerge?: (prNumber: number) => void;
  /** Live merge confirm retry delay (ms); default 2000. Tests may pass 0. */
  readonly mergeConfirmRetryDelayMs?: number;
  /** Offline/test: skip live gh pr view/merge and synthesize MERGED from poll readiness. */
  readonly offlineSynthetic?: boolean;
}

function offlineSyntheticLiveState(
  snapshot: PrReviewSnapshot,
  state: "OPEN" | "MERGED" = "OPEN",
): PrMergeLiveState {
  return {
    prNumber: snapshot.prNumber > 0 ? snapshot.prNumber : 1,
    prUrl: snapshot.prUrl,
    state,
    headOid: snapshot.headOid,
    headRefName: "offline-branch",
    headRepositoryOwnerLogin: "offline",
    mergeStateStatus: state === "OPEN" ? "CLEAN" : "UNKNOWN",
  };
}

async function runOfflineSyntheticAutoMerge(
  input: AutoMergeStageInput,
): Promise<AutoMergeStageResult> {
  const snapshot = await input.poll(1);
  const live = offlineSyntheticLiveState(snapshot, "OPEN");
  const readiness = assessMergeReadiness(live, snapshot);
  if (!readiness.ready) {
    const pendingOnly =
      readiness.blockers.length > 0 &&
      readiness.blockers.every((b) => b === "ci_pending");
    return {
      ok: false,
      terminalState: pendingOnly ? "not_ready" : "decision_gate",
      stopSummary: mergeReadinessStopSummary(readiness.blockers),
    };
  }
  input.executeMerge?.(live.prNumber);
  const record: PrMergedTerminalRecord = {
    prUrl: snapshot.prUrl,
    prNumber: live.prNumber,
    remoteBranchName: live.headRefName,
    mergedHeadOid: snapshot.headOid,
    convergedHeadOid: input.convergedHeadOid,
  };
  return { ok: true, terminalState: "merged", record };
}

function externallyMergedNeverConvergedSummary(): StopSummary {
  return {
    reason: "decision_gate_park",
    summary:
      "PR is live MERGED but this run has no online_review_converged / review_loop_converged record (externally merged, never converged)",
    repairHint:
      "confirm whether the PR was merged outside the orchestrator review loop; answer the decision gate before cleanup",
  };
}

function mergeNotConfirmedSummary(): StopSummary {
  return {
    reason: "infra_failure",
    summary:
      "gh pr merge returned but live GitHub state did not confirm MERGED at the expected head",
    repairHint:
      "inspect the PR on GitHub and re-feed once merge state is unambiguous",
  };
}

function expectedMergeTipMismatchSummary(): StopSummary {
  return {
    reason: "decision_gate_park",
    summary:
      "auto-merge blocked: live PR tip does not match expected post-doc-release head",
    repairHint:
      "ensure the PR head equals the doc-release commit before merge",
  };
}

function expectedMergeTipMismatch(
  liveHeadOid: string,
  expectedMergeHeadOid?: string,
): StopSummary | undefined {
  const expected =
    expectedMergeHeadOid !== undefined && expectedMergeHeadOid.trim().length > 0
      ? expectedMergeHeadOid
      : undefined;
  if (expected !== undefined && liveHeadOid !== expected) {
    return expectedMergeTipMismatchSummary();
  }
  return undefined;
}

export async function tryResumePrMergedBackfill(
  input: Omit<
    AutoMergeStageInput,
    "docReleaseCompleted" | "poll" | "docReleasePaths"
  >,
  liveState?: PrMergeLiveState,
): Promise<AutoMergeStageResult | undefined> {
  if (input.prMergedMarkerPresent) {
    return { ok: true, terminalState: "already_recorded" };
  }
  const live =
    liveState ?? fetchPrMergeLiveState(input.sh, input.repo, input.prUrl);
  if (!githubFieldEquals(live.state, "MERGED")) return undefined;
  if (!input.priorConvergenceRecorded) {
    return {
      ok: false,
      terminalState: "externally_merged_never_converged",
      stopSummary: externallyMergedNeverConvergedSummary(),
    };
  }
  const record = prMergedRecordFromLive(
    live,
    input.convergedHeadOid,
    input.expectedMergeHeadOid,
  );
  if (record === undefined) return undefined;
  return { ok: true, terminalState: "merged", record };
}

export async function runAutoMergeStage(
  input: AutoMergeStageInput,
): Promise<AutoMergeStageResult> {
  if (input.prMergedMarkerPresent) {
    return { ok: true, terminalState: "already_recorded" };
  }
  if (!input.docReleaseCompleted) {
    return {
      ok: false,
      terminalState: "not_ready",
      stopSummary: {
        reason: "decision_gate_park",
        summary: "auto-merge blocked: doc-release has not completed",
        repairHint: "complete family doc-release before merge",
      },
    };
  }

  const offlineSynthetic =
    input.offlineSynthetic === true
      ? true
      : input.offlineSynthetic === false
        ? false
        : !isLiveGithubReviewPollEnabled(input.prUrl, input.repo) &&
          process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL === "1";

  // ADR 0123 / #735: auto-merge no longer vetoes on doc-release path allowlist.
  // Gate = docReleaseCompleted (above) + live readiness on the post-doc tip.
  // Path helpers (isDocOnlyFileList / docReleasePathsFromCommit) may remain for
  // diagnostics but must not re-enter as a silent second merge gate.

  if (offlineSynthetic) {
    return runOfflineSyntheticAutoMerge(input);
  }

  let live = fetchPrMergeLiveState(input.sh, input.repo, input.prUrl);
  const backfill = await tryResumePrMergedBackfill(input, live);
  if (backfill !== undefined) {
    return backfill;
  }

  if (githubFieldEquals(live.state, "MERGED")) {
    if (!input.priorConvergenceRecorded) {
      return {
        ok: false,
        terminalState: "externally_merged_never_converged",
        stopSummary: externallyMergedNeverConvergedSummary(),
      };
    }
    const record = prMergedRecordFromLive(
      live,
      input.convergedHeadOid,
      input.expectedMergeHeadOid,
    );
    if (record !== undefined) {
      return { ok: true, terminalState: "merged", record };
    }
    return {
      ok: false,
      terminalState: "decision_gate",
      stopSummary: mergeNotConfirmedSummary(),
    };
  }

  const snapshot = await input.poll(1);
  if (snapshot.headOid !== live.headOid) {
    live = fetchPrMergeLiveState(input.sh, input.repo, input.prUrl);
    if (snapshot.headOid !== live.headOid) {
      return {
        ok: false,
        terminalState: "decision_gate",
        stopSummary: {
          reason: "infra_failure",
          summary:
            "live PR head still mismatches readiness snapshot after re-fetch",
          repairHint:
            "wait for GitHub to settle on one head, then re-feed the run",
        },
      };
    }
  }
  const readiness = assessMergeReadiness(live, snapshot);
  if (!readiness.ready) {
    const pendingOnly =
      readiness.blockers.length > 0 &&
      readiness.blockers.every((b) => b === "ci_pending");
    return {
      ok: false,
      terminalState: pendingOnly ? "not_ready" : "decision_gate",
      stopSummary: mergeReadinessStopSummary(readiness.blockers),
    };
  }

  const tipMismatch = expectedMergeTipMismatch(
    live.headOid,
    input.expectedMergeHeadOid,
  );
  if (tipMismatch !== undefined) {
    return {
      ok: false,
      terminalState: "decision_gate",
      stopSummary: tipMismatch,
    };
  }

  const expectedMergeHead = live.headOid;
  const doMerge =
    input.executeMerge ??
    ((prNumber: number) =>
      executePrMergeCommit(input.sh, input.repo, prNumber, expectedMergeHead));
  doMerge(live.prNumber);

  const retryDelayMs = input.mergeConfirmRetryDelayMs ?? 2000;
  let record: PrMergedTerminalRecord | undefined;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      record = confirmPrMergedLive(
        input.sh,
        input.repo,
        input.prUrl,
        live.headOid,
      );
      if (record !== undefined) break;
    } catch {
      // Ignore transient network/API errors and retry.
    }
    if (attempt < 3 && retryDelayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
    }
  }
  const confirmTipMismatch =
    record !== undefined
      ? expectedMergeTipMismatch(record.mergedHeadOid, input.expectedMergeHeadOid)
      : undefined;
  if (confirmTipMismatch !== undefined) {
    return {
      ok: false,
      terminalState: "decision_gate",
      stopSummary: confirmTipMismatch,
    };
  }
  if (record === undefined) {
    return {
      ok: false,
      terminalState: "decision_gate",
      stopSummary: mergeNotConfirmedSummary(),
    };
  }
  return { ok: true, terminalState: "merged", record };
}
