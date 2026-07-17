/**
 * #941 / #934 ID-013 — Landing Action.
 *
 * Atomic rename+expansion of the former docRelease Action/seat: after online
 * review converges, THIS Action owns docs release / necessary push, final
 * CI·review·ruleset judgment, merge, live MERGED confirm, issue close, and
 * safe cleanup. No new worker/seat/session/flow baton.
 *
 * Host auto-merge courts, readiness/HEAD/marker second-guess courts, host
 * cleanup classification that fails the run, and fake-PR offline merge hatches
 * are deleted — callers re-enter this Action only.
 */

import {
  assessMergeReadiness,
  confirmPrMergedLive,
  executePrMergeCommit,
  fetchPrMergeLiveState,
  type PrMergeLiveState,
  type PrMergedTerminalRecord,
} from "../autoMerge.js";
import type { PrReviewSnapshot } from "../botPolling.js";
import { isLiveGithubReviewPollEnabled } from "../botPolling.js";
import { landingWorkerSpec } from "../dispatchWorker.js";
import { shWithClock } from "../externalCall.js";
import {
  isMissingGitRefError,
  runPostMergeCleanup,
  type LiveSubIssue,
} from "../postMergeCleanup.js";
import {
  decisionGateParkStopSummary,
  type StopSummary,
} from "../stopSummary.js";
import type { CleanupResult, DispatchContext, WorkerResult } from "../types.js";
import type { ResolvedModelRoute } from "../modelRoutes.js";
import {
  familyPostMergeCleanupForHead,
  familyPrMergedForHead,
  mergedSet,
  recordPostMergeCleanup,
  recordPrMerged,
} from "./ledger.js";
import { billingPoolForFamilyWorker } from "./familyWorkerSlots.js";
import { dispatchFamilyWorker } from "./dispatchFamilyWorker.js";
import type { FamilyBackend } from "./types.js";
import { shouldReclaimFamilyHost } from "../hostReclaim.js";

export type LandingActionTerminal =
  | "completed"
  | "decision_gate"
  | "landing_failed"
  | "already_done";

export interface LandingActionResult {
  readonly ok: boolean;
  readonly terminalState: LandingActionTerminal;
  readonly leftovers?: readonly string[];
  readonly stopSummary?: StopSummary;
  readonly record?: PrMergedTerminalRecord;
}

/** Injectable live GitHub/git surface for tests — production uses gh defaults. */
export interface LandingLiveHooks {
  readonly fetchState: () => PrMergeLiveState;
  readonly executeMerge?: (prNumber: number, headOid: string) => void;
  readonly confirmMerged?: (
    expectedHeadOid: string,
  ) => PrMergedTerminalRecord | undefined;
  readonly pollSnapshot?: () => Promise<PrReviewSnapshot>;
  readonly closeIssue?: (issue: number) => void;
  readonly deleteBranch?: (branch: string) => void;
  readonly branchExists?: (branch: string) => boolean;
  readonly fetchBranchTip?: (branch: string) => string | undefined;
  readonly fetchIssueState?: (issue: number) => string;
  readonly fetchSubIssues?: (parent: number) => readonly LiveSubIssue[];
}

export interface LandingActionInput {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId?: string;
  readonly convergedHeadOid: string;
  readonly prUrl: string;
  readonly familyIssue?: number;
  readonly resolvedRoute?: ResolvedModelRoute;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<string>;
  /** Skip docs worker when review_loop already released (re-entry after merge only). */
  readonly skipDocsWorker?: boolean;
  readonly live?: LandingLiveHooks;
}

function ghSh(): (file: string, args: string[]) => string {
  return (file, args) =>
    shWithClock(file, args, { stage: `landing:${file}` });
}

function defaultFetchState(
  sh: (file: string, args: string[]) => string,
  repo: string,
  prUrl: string,
): PrMergeLiveState {
  return fetchPrMergeLiveState(sh, repo, prUrl);
}

/**
 * Landing Action — docs worker → merge → MERGED confirm → close/cleanup leftovers.
 *
 * close/cleanup failures become leftovers only (ID-013); never park/fail/flip
 * completed after live MERGED. Readiness/ruleset/manual merge failures emit a
 * typed decision gate.
 */
export async function runLandingAction(
  input: LandingActionInput,
): Promise<LandingActionResult> {
  const familyRepo =
    process.env.ORCHESTRATOR_REPO?.trim() ?? "Akagilnc/ming-salvage-sim";
  const prUrl = input.prUrl.trim();
  if (prUrl.length === 0) {
    return {
      ok: false,
      terminalState: "decision_gate",
      stopSummary: decisionGateParkStopSummary({
        summary: "landing blocked: missing PR URL",
        repairHint: "provide the ship PR URL, then re-enter landing",
      }),
    };
  }

  const ledger = await input.familyBackend.readFamilyLedger();
  const priorCleanup = familyPostMergeCleanupForHead(
    ledger,
    input.convergedHeadOid,
  );
  if (priorCleanup !== undefined) {
    return { ok: true, terminalState: "already_done" };
  }

  const priorMerged = familyPrMergedForHead(ledger, input.convergedHeadOid);
  const sh = ghSh();
  const liveHooks = input.live;
  const fetchState =
    liveHooks?.fetchState ??
    (() => defaultFetchState(sh, familyRepo, prUrl));

  // Non-live PR URLs (pr:// stubs, offline hatch): landing still owns the
  // durable terminal — no host auto-merge court, no fake live MERGED via gh.
  // Live hooks always take the real path below.
  const nonLivePr =
    liveHooks === undefined &&
    !isLiveGithubReviewPollEnabled(prUrl, familyRepo);

  // ── 1. Docs + push (landing worker seat — former docRelease) ───────────
  // Always attempt when the backend can dispatch (including non-live pr://).
  if (priorMerged === undefined && input.skipDocsWorker !== true) {
    const pool = billingPoolForFamilyWorker({
      kind: "landing",
      ...(input.billingPool !== undefined ? { billingPool: input.billingPool } : {}),
      ...(input.billingPoolSlots !== undefined
        ? { billingPoolSlots: input.billingPoolSlots as never }
        : {}),
    });
    const spec = landingWorkerSpec(
      input.resolvedRoute as never,
      pool as never,
    );
    const ctx: DispatchContext = {
      familyBase: input.familyBase,
      ...(input.runId !== undefined ? { runId: input.runId } : {}),
      repo: familyRepo,
      prUrl,
      ...(pool !== undefined ? { billingPool: pool } : {}),
      ...(input.resolvedRoute !== undefined
        ? { modelRoute: input.resolvedRoute as never }
        : {}),
    };
    let workerResult: WorkerResult;
    try {
      // Prefer the unified dispatchWorker seam (ID-006). Fall back to the
      // family helper when the backend only exposes legacy methods.
      if (input.familyBackend.dispatchWorker !== undefined) {
        workerResult = await input.familyBackend.dispatchWorker(spec, ctx);
      } else {
        workerResult = await dispatchFamilyWorker(
          input.familyBackend,
          spec,
          ctx,
        );
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        terminalState: "landing_failed",
        stopSummary: {
          // #942 will cut over public landing_worker_failed; keep stage token now.
          reason: "merge_failed",
          summary: `landing worker dispatch failed: ${detail}`,
          repairHint: "repair landing worker startup, then re-enter landing",
        },
      };
    }
    if (workerResult.kind === "escalated") {
      return {
        ok: false,
        terminalState: "decision_gate",
        stopSummary: decisionGateParkStopSummary({
          summary: `${workerResult.escalation.reason} — ${workerResult.escalation.diagnosis}`,
          repairHint: "answer the landing decision gate, then re-enter landing",
        }),
      };
    }
    const docsOk =
      workerResult.kind === "completed" &&
      workerResult.output?.kind === "landing" &&
      workerResult.output.released === true;
    if (!docsOk) {
      // Live paths must fail/park on docs failure. Non-live pr:// stubs record
      // leftovers and continue so offline drivers still reach durable landing.
      if (!nonLivePr) {
        const reason =
          workerResult.kind === "failed"
            ? workerResult.reason
            : workerResult.kind === "completed" &&
                workerResult.output?.kind === "landing"
              ? "landing returned released:false"
              : `landing worker returned ${workerResult.kind}`;
        return {
          ok: false,
          terminalState: "landing_failed",
          stopSummary: {
            reason: "merge_failed",
            summary: `landing worker failed: ${reason}`,
            repairHint: "fix the landing skill/push failure and re-enter landing",
          },
        };
      }
    }
  }

  // ── 2. Merge + live MERGED confirm (Action-owned; no host auto-merge court)
  let mergeRecord: PrMergedTerminalRecord | undefined =
    priorMerged !== undefined
      ? {
          prUrl,
          prNumber: priorMerged.prNumber,
          remoteBranchName: priorMerged.remoteBranchName,
          mergedHeadOid: priorMerged.mergedHeadOid,
          convergedHeadOid: input.convergedHeadOid,
        }
      : undefined;

  if (mergeRecord === undefined && nonLivePr) {
    // Durable offline completion owned by landing Action (not a host court).
    mergeRecord = {
      prUrl,
      prNumber: 1,
      remoteBranchName: input.familyBase,
      mergedHeadOid: input.convergedHeadOid,
      convergedHeadOid: input.convergedHeadOid,
    };
    await recordPrMerged(input.familyBackend, {
      pr: prUrl,
      prNumber: mergeRecord.prNumber,
      remoteBranchName: mergeRecord.remoteBranchName,
      mergedHeadOid: mergeRecord.mergedHeadOid,
      familyHeadAfter: input.convergedHeadOid,
    });
    const offlineCleanup: CleanupResult = {
      kind: "cleanup",
      terminal: true,
      ok: true,
      branchOutcome: "already_gone",
      skippedReasons: ["non_live_pr"],
    };
    await recordPostMergeCleanup(input.familyBackend, {
      familyHeadAfter: input.convergedHeadOid,
      cleanupOutput: offlineCleanup,
    });
    return {
      ok: true,
      terminalState: "completed",
      record: mergeRecord,
      leftovers: ["non_live_pr"],
    };
  }

  if (mergeRecord === undefined) {
    let live: PrMergeLiveState;
    try {
      live = fetchState();
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        terminalState: "decision_gate",
        stopSummary: decisionGateParkStopSummary({
          summary: `landing cannot read live PR state: ${detail}`,
          repairHint: "fix GitHub auth / PR URL, then re-enter landing",
        }),
      };
    }

    if (live.state.toUpperCase() === "MERGED") {
      mergeRecord = {
        prUrl: live.prUrl,
        prNumber: live.prNumber,
        remoteBranchName: live.headRefName,
        mergedHeadOid: live.headOid,
        convergedHeadOid: input.convergedHeadOid,
      };
    } else if (live.state.toUpperCase() === "CLOSED") {
      return {
        ok: false,
        terminalState: "decision_gate",
        stopSummary: decisionGateParkStopSummary({
          summary: "PR is CLOSED (not MERGED) — landing cannot close issues yet",
          repairHint:
            "re-open / re-merge the PR or answer the decision gate, then re-enter landing",
        }),
      };
    } else {
      // readiness: CI pending → keep polling (ID-004); other blockers → gate
      const poll =
        liveHooks?.pollSnapshot ??
        (async (): Promise<PrReviewSnapshot> => {
          // Minimal empty-converged snapshot when no poll injected (live readiness
          // still uses mergeStateStatus from gh pr view).
          return {
            repo: familyRepo,
            prNumber: live.prNumber,
            prUrl,
            headOid: live.headOid,
            pollCount: 1,
            bots: {
              coderabbit: { state: "complete", findingCount: 0 },
              sourcery: { state: "complete", findingCount: 0 },
              codex: { state: "complete", findingCount: 0 },
              gemini: { state: "complete", findingCount: 0 },
            },
            threads: [],
            checkRuns: [],
            totalFindingCount: 0,
            quiescent: true,
            roundTriggerUsed: {
              headOid: live.headOid,
              triggeredAt: new Date(0).toISOString(),
            },
            checkRunsEmptyMeans: "converged",
          };
        });

      // Single readiness pass for non-CI; CI pending is re-fetched once more.
      // Unlimited CI poll lives at the online-review Action; here readiness
      // that is only ci_pending raises a decision gate so re-entry resumes.
      const snapshot = await poll();
      // Re-fetch live after poll so head/ruleset stay fresh
      try {
        live = fetchState();
      } catch {
        /* keep prior live */
      }
      const readiness = assessMergeReadiness(live, snapshot);
      if (!readiness.ready) {
        const pendingOnly =
          readiness.blockers.length > 0 &&
          readiness.blockers.every((b) => b === "ci_pending");
        return {
          ok: false,
          terminalState: "decision_gate",
          stopSummary: decisionGateParkStopSummary({
            summary: pendingOnly
              ? "landing: CI still pending on PR head — re-enter when green"
              : `landing merge blocked: ${readiness.blockers.join(", ")}`,
            repairHint: pendingOnly
              ? "wait for CI, then re-enter landing (no whole-run deadline)"
              : "resolve ruleset / threads / CI or answer the decision gate",
          }),
        };
      }

      const doMerge =
        liveHooks?.executeMerge ??
        ((prNumber: number, headOid: string) =>
          executePrMergeCommit(sh, familyRepo, prNumber, headOid));
      try {
        doMerge(live.prNumber, live.headOid);
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        return {
          ok: false,
          terminalState: "decision_gate",
          stopSummary: decisionGateParkStopSummary({
            summary: `landing merge failed: ${detail}`,
            repairHint: "inspect the PR merge failure and re-enter landing",
          }),
        };
      }

      try {
        const confirm =
          liveHooks?.confirmMerged ??
          ((expectedHeadOid: string) =>
            confirmPrMergedLive(sh, familyRepo, prUrl, expectedHeadOid));
        mergeRecord = confirm(live.headOid);
      } catch {
        mergeRecord = undefined;
      }
      if (mergeRecord === undefined) {
        // Re-check live state once for eventual consistency / test hooks
        try {
          const after = fetchState();
          if (after.state.toUpperCase() === "MERGED") {
            mergeRecord = {
              prUrl: after.prUrl,
              prNumber: after.prNumber,
              remoteBranchName: after.headRefName,
              mergedHeadOid: after.headOid,
              convergedHeadOid: input.convergedHeadOid,
            };
          }
        } catch {
          /* fall through */
        }
      }
      if (mergeRecord === undefined) {
        return {
          ok: false,
          terminalState: "decision_gate",
          stopSummary: decisionGateParkStopSummary({
            summary:
              "landing merge returned but live GitHub state did not confirm MERGED",
            repairHint:
              "inspect the PR on GitHub and re-enter landing once MERGED is unambiguous",
          }),
        };
      }
    }

    await recordPrMerged(input.familyBackend, {
      pr: prUrl,
      prNumber: mergeRecord.prNumber,
      remoteBranchName: mergeRecord.remoteBranchName,
      mergedHeadOid: mergeRecord.mergedHeadOid,
      familyHeadAfter: input.convergedHeadOid,
    });
  }

  // ── 3. Close + cleanup AFTER live MERGED (leftovers only — ID-013 / ID-015)
  const coveredIssues = [...mergedSet(await input.familyBackend.readFamilyLedger())];
  const leftovers: string[] = [];
  let cleanupOutput: CleanupResult;

  if (nonLivePr && liveHooks === undefined) {
    cleanupOutput = {
      kind: "cleanup",
      terminal: true,
      ok: true,
      branchOutcome: "already_gone",
      skippedReasons: ["non_live_pr"],
    };
    leftovers.push("non_live_pr");
    await recordPostMergeCleanup(input.familyBackend, {
      familyHeadAfter: input.convergedHeadOid,
      cleanupOutput,
    });
    return {
      ok: true,
      terminalState: "completed",
      record: mergeRecord,
      leftovers,
    };
  }

  try {
    const liveForCleanup = (() => {
      try {
        return fetchState();
      } catch {
        return {
          prNumber: mergeRecord.prNumber,
          prUrl: mergeRecord.prUrl,
          state: "MERGED",
          headOid: mergeRecord.mergedHeadOid,
          headRefName: mergeRecord.remoteBranchName,
          mergeStateStatus: "UNKNOWN",
        };
      }
    })();
    cleanupOutput = runPostMergeCleanup({
      sh,
      repo: familyRepo,
      coveredIssues,
      ...(input.familyIssue !== undefined
        ? { parentIssue: input.familyIssue }
        : {}),
      prMerged: mergeRecord,
      liveState: {
        state: liveForCleanup.state,
        headOid: liveForCleanup.headOid,
        prNumber: liveForCleanup.prNumber,
        prUrl: liveForCleanup.prUrl,
        headRefName: liveForCleanup.headRefName,
        ...(liveForCleanup.mergeStateStatus !== undefined
          ? { mergeStateStatus: liveForCleanup.mergeStateStatus }
          : {}),
      },
      ...(liveHooks?.closeIssue !== undefined
        ? { closeIssue: liveHooks.closeIssue }
        : {}),
      ...(liveHooks?.deleteBranch !== undefined
        ? { deleteBranch: liveHooks.deleteBranch }
        : {}),
      ...(liveHooks?.branchExists !== undefined
        ? { branchExists: liveHooks.branchExists }
        : {}),
      ...(liveHooks?.fetchBranchTip !== undefined
        ? { fetchBranchTip: liveHooks.fetchBranchTip }
        : {}),
      ...(liveHooks?.fetchIssueState !== undefined
        ? { fetchIssueState: liveHooks.fetchIssueState }
        : {}),
      ...(liveHooks?.fetchSubIssues !== undefined
        ? { fetchSubIssues: liveHooks.fetchSubIssues }
        : {}),
    });
  } catch (err) {
    // Never flip completed after MERGED — leftover only
    const detail = err instanceof Error ? err.message : String(err);
    if (isMissingGitRefError(err)) {
      leftovers.push("branch_already_gone");
    } else {
      leftovers.push(`cleanup_exception:${detail}`);
    }
    cleanupOutput = {
      kind: "cleanup",
      terminal: true,
      ok: true,
      skippedReasons: [...leftovers],
      branchOutcome: "already_gone",
    };
  }

  // Map non-terminal cleanup acts → leftovers; force terminal completed (ID-013)
  if (!cleanupOutput.ok || !cleanupOutput.terminal) {
    if (cleanupOutput.skippedReasons !== undefined) {
      leftovers.push(...cleanupOutput.skippedReasons);
    } else {
      leftovers.push("cleanup_incomplete");
    }
    cleanupOutput = {
      ...cleanupOutput,
      kind: "cleanup",
      terminal: true,
      ok: true,
      ...(leftovers.length > 0 ? { skippedReasons: [...leftovers] } : {}),
    };
  } else if (
    cleanupOutput.skippedReasons !== undefined &&
    cleanupOutput.skippedReasons.length > 0
  ) {
    leftovers.push(...cleanupOutput.skippedReasons);
  }

  // Normalize 404/ref-missing into already-gone diagnostics (ID-015)
  const normalizedLeftovers = leftovers.map((l) =>
    /HTTP\s*404|Not Found|Reference does not exist/i.test(l)
      ? "branch_already_gone"
      : l,
  );

  await recordPostMergeCleanup(input.familyBackend, {
    familyHeadAfter: input.convergedHeadOid,
    cleanupOutput,
  });

  const postCleanupLedger = await input.familyBackend.readFamilyLedger();
  if (
    shouldReclaimFamilyHost(postCleanupLedger) &&
    input.familyBackend.reapFamilyHost !== undefined
  ) {
    try {
      await input.familyBackend.reapFamilyHost(input.familyBase);
    } catch {
      // Best-effort terminal GC — must not flip completed.
    }
  }

  return {
    ok: true,
    terminalState: "completed",
    record: mergeRecord,
    ...(normalizedLeftovers.length > 0
      ? { leftovers: normalizedLeftovers }
      : {}),
  };
}

/**
 * Resume/already_done helper: re-enter landing when pr_merged exists without
 * terminal cleanup, or when nothing is recorded yet. Never invents host courts.
 */
export async function ensureLandingComplete(
  input: LandingActionInput,
): Promise<LandingActionResult> {
  return runLandingAction(input);
}
