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
import {
  pollPrReviewState,
  type PrReviewSnapshot,
} from "../botPolling.js";
import { landingWorkerSpec } from "../dispatchWorker.js";
import { buildRoundTrigger } from "../evidenceAdmissibility.js";
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
import type {
  CleanupResult,
  DispatchContext,
  WorkerResult,
} from "../types.js";
import type { ModelRouteSlot, ResolvedModelRoute } from "../modelRoutes.js";
import {
  familyPostMergeCleanupForHead,
  familyPrMergedForHead,
  mergedSet,
  recordPostMergeCleanup,
  recordPrMerged,
  recordReviewLoopConverged,
} from "./ledger.js";
import { billingPoolForFamilyWorker } from "./familyWorkerSlots.js";
import { dispatchFamilyWorkerOrAbort } from "./familyProcessRootDispatch.js";
import { sleepPendingCiPollInterval } from "./onlineReviewLoop.js";
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

/**
 * Single authority for landing Action terminal → park vs hard-fail (family/914
 * CR R1 Std M1 / CLAUDE #19). Fresh final-barrier and resume re-entry must
 * share this classifier — do not re-copy isPark at call sites.
 *
 * - `decision_gate` / `decision_gate_park` → park (answerable decision)
 * - other non-ok → hard_fail (merge_failed stage)
 */
export type LandingActionClassification =
  | { readonly kind: "ok" }
  | { readonly kind: "park"; readonly stopSummary: StopSummary }
  | { readonly kind: "hard_fail"; readonly stopSummary: StopSummary };

export function classifyLandingActionResult(
  landing: LandingActionResult,
): LandingActionClassification {
  if (landing.ok) return { kind: "ok" };
  const stopSummary =
    landing.stopSummary ??
    decisionGateParkStopSummary({
      summary: `family landing did not complete (${landing.terminalState})`,
      repairHint:
        "resolve landing blockers or answer the decision gate, then re-enter landing",
    });
  const isPark =
    landing.terminalState === "decision_gate" ||
    stopSummary.reason === "decision_gate_park";
  return isPark
    ? { kind: "park", stopSummary }
    : { kind: "hard_fail", stopSummary };
}

/**
 * Consecutive mid-loop live I/O failures before landing parks (Std S4 / R2 S1).
 * Covers both `fetchState` and `pollSnapshot` / `pollOnce` — auth/API death
 * must not keep-prior forever or escape as an uncaught throw.
 */
export const LANDING_CI_FETCH_FAILURE_LIMIT = 3;

/** Injectable live GitHub/git surface for tests — production uses gh defaults. */
export interface LandingLiveHooks {
  readonly fetchState: () => PrMergeLiveState;
  readonly executeMerge?: (prNumber: number, headOid: string) => void;
  readonly confirmMerged?: (
    expectedHeadOid: string,
  ) => PrMergedTerminalRecord | undefined;
  /** Real readiness snapshot; production uses pollPrReviewState when absent. */
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
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  readonly live?: LandingLiveHooks;
}

/**
 * Explicit live-hook builder for offline/unit tests.
 * Not a silent 伪 PR hatch — caller must attach the result to
 * {@link LandingActionInput.live} or {@link FamilyBackend.resolveLandingLiveHooks}.
 */
export function buildExplicitLandingLiveHooks(input: {
  readonly prUrl: string;
  readonly headOid: string;
  readonly remoteBranchName: string;
  readonly prNumber?: number;
}): LandingLiveHooks {
  let merged = false;
  const prNumber = input.prNumber ?? 1;
  const greenSnapshot = (): PrReviewSnapshot => ({
    repo: "test/repo",
    prNumber,
    prUrl: input.prUrl,
    headOid: input.headOid,
    pollCount: 1,
    bots: {
      coderabbit: { state: "complete", findingCount: 0 },
      sourcery: { state: "complete", findingCount: 0 },
      codex: { state: "complete", findingCount: 0 },
      gemini: { state: "complete", findingCount: 0 },
    },
    threads: [],
    checkRuns: [
      {
        id: 1,
        name: "ci",
        status: "completed",
        conclusion: "success",
        headSha: input.headOid,
      },
    ],
    totalFindingCount: 0,
    quiescent: true,
    roundTriggerUsed: {
      headOid: input.headOid,
      triggeredAt: "1970-01-01T00:00:00.000Z",
    },
    checkRunsEmptyMeans: "pending",
  });
  return {
    fetchState: () => ({
      prNumber,
      prUrl: input.prUrl,
      state: merged ? "MERGED" : "OPEN",
      headOid: input.headOid,
      headRefName: input.remoteBranchName,
      mergeStateStatus: "CLEAN",
    }),
    executeMerge: () => {
      merged = true;
    },
    confirmMerged: (expectedHeadOid) => ({
      prUrl: input.prUrl,
      prNumber,
      remoteBranchName: input.remoteBranchName,
      mergedHeadOid: expectedHeadOid,
      convergedHeadOid: expectedHeadOid,
    }),
    pollSnapshot: async () => greenSnapshot(),
    closeIssue: () => {},
    deleteBranch: () => {},
    branchExists: () => false,
    fetchIssueState: () => "CLOSED",
    fetchSubIssues: () => [],
  };
}

function ghSh(): (file: string, args: string[]) => string {
  return (file, args) =>
    shWithClock(file, args, { stage: `landing:${file}` });
}

/**
 * Live family HEAD for completion markers / resume lookup. Docs landing may
 * advance HEAD past the pre-doc review_loop_converged OID; markers and
 * already_done must key the head resume will re-read.
 */
async function resolveLandingMarkerHead(
  backend: FamilyBackend,
  familyBase: string,
  fallback: string,
): Promise<string> {
  if (backend.readFamilyHead === undefined) return fallback;
  try {
    const head = (await backend.readFamilyHead(familyBase)).trim();
    return head.length > 0 ? head : fallback;
  } catch {
    return fallback;
  }
}

/**
 * Landing Action — docs worker → merge → MERGED confirm → close/cleanup leftovers.
 *
 * close/cleanup failures become leftovers only (ID-013); never park/fail/flip
 * completed after live MERGED. Readiness/ruleset/manual merge failures emit a
 * typed decision gate. CI pending continuously re-polls (ID-004, no whole-run
 * deadline). 伪 PR offline synthetic MERGED is deleted — inject live hooks or
 * use a real pollable PR.
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
  // Resume keys live HEAD first (post-docs), then pre-doc fallback for older
  // markers stamped before this invariant.
  const liveMarkerHead = await resolveLandingMarkerHead(
    input.familyBackend,
    input.familyBase,
    input.convergedHeadOid,
  );
  const priorCleanup =
    familyPostMergeCleanupForHead(ledger, liveMarkerHead) ??
    (liveMarkerHead !== input.convergedHeadOid
      ? familyPostMergeCleanupForHead(ledger, input.convergedHeadOid)
      : undefined);
  if (priorCleanup !== undefined) {
    return { ok: true, terminalState: "already_done" };
  }

  const priorMerged =
    familyPrMergedForHead(ledger, liveMarkerHead) ??
    (liveMarkerHead !== input.convergedHeadOid
      ? familyPrMergedForHead(ledger, input.convergedHeadOid)
      : undefined);
  const sh = ghSh();
  // Explicit live surface only — no silent non-live pr:// MERGED hatch (ID-013).
  const liveHooks =
    input.live ??
    input.familyBackend.resolveLandingLiveHooks?.({
      prUrl,
      convergedHeadOid: input.convergedHeadOid,
      familyBase: input.familyBase,
    });
  const fetchState =
    liveHooks?.fetchState ??
    (() => fetchPrMergeLiveState(sh, familyRepo, prUrl));

  // ── 1. Docs + push (landing worker seat — former docRelease) ───────────
  if (priorMerged === undefined) {
    const pool = billingPoolForFamilyWorker({
      kind: "landing",
      ...(input.billingPool !== undefined
        ? { billingPool: input.billingPool }
        : {}),
      ...(input.billingPoolSlots !== undefined
        ? { billingPoolSlots: input.billingPoolSlots }
        : {}),
    });
    // Shared process-root court (ID-004 / ID-006 / #909): quota rethrows for
    // park/relay — do not wrap and collapse into landing_failed.
    const spec = landingWorkerSpec(input.resolvedRoute, pool);
    const ctx: DispatchContext = {
      familyBase: input.familyBase,
      ...(input.runId !== undefined ? { runId: input.runId } : {}),
      repo: familyRepo,
      prUrl,
      ...(pool !== undefined ? { billingPool: pool } : {}),
      ...(input.resolvedRoute !== undefined
        ? { modelRoute: input.resolvedRoute }
        : {}),
    };
    const workerResult = await dispatchFamilyWorkerOrAbort(
      input.familyBackend,
      spec,
      ctx,
    );
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

  // Docs may have advanced family HEAD. When docs ran, re-read live HEAD for
  // completion markers + resume lookup (not the stale pre-doc converged OID).
  // When docs were skipped (priorMerged already set), entry liveMarkerHead is
  // already the right key — a second resolve is pure redundancy.
  const docsRan = priorMerged === undefined;
  const completionHeadOid = docsRan
    ? await resolveLandingMarkerHead(
        input.familyBackend,
        input.familyBase,
        input.convergedHeadOid,
      )
    : liveMarkerHead;
  if (
    docsRan &&
    completionHeadOid !== input.convergedHeadOid
  ) {
    // Re-stamp so runner's already-converged short path (live HEAD equality)
    // still finds review_loop_converged after a non-empty docs push.
    await recordReviewLoopConverged(input.familyBackend, {
      pr: prUrl,
      familyHeadAfter: completionHeadOid,
    });
  }

  // ── 2. Merge + live MERGED confirm (Action-owned; no host auto-merge court)
  // No 伪 PR synthetic MERGED: tests inject live hooks; production uses gh.
  let mergeRecord: PrMergedTerminalRecord | undefined =
    priorMerged !== undefined
      ? {
          prUrl,
          prNumber: priorMerged.prNumber,
          remoteBranchName: priorMerged.remoteBranchName,
          mergedHeadOid: priorMerged.mergedHeadOid,
          convergedHeadOid: completionHeadOid,
        }
      : undefined;

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
        convergedHeadOid: completionHeadOid,
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
      // Final readiness: real poll (or injected live poll). Never fabricate
      // green bots/check-runs. CI pending → continuous re-poll (ID-004).
      const pollOnce = async (): Promise<PrReviewSnapshot> => {
        if (liveHooks?.pollSnapshot !== undefined) {
          return liveHooks.pollSnapshot();
        }
        return pollPrReviewState(sh, {
          repo: familyRepo,
          prUrl,
          roundTrigger: buildRoundTrigger(live.headOid),
          pollCount: 1,
        });
      };

      // Std S4 / R2 S1: repeated live I/O failures (fetchState OR pollOnce)
      // → decision_gate. Do not infinite keep-prior or throw out of band on
      // auth/API death while OPEN+ci_pending. Initial poll fails closed the
      // same way (retry interval until consecutive limit).
      let consecutiveFetchFailures = 0;
      let consecutivePollFailures = 0;
      let snapshot: PrReviewSnapshot | undefined;
      let readiness: ReturnType<typeof assessMergeReadiness> | undefined;
      while (true) {
        try {
          snapshot = await pollOnce();
          consecutivePollFailures = 0;
        } catch (err) {
          consecutivePollFailures += 1;
          if (consecutivePollFailures >= LANDING_CI_FETCH_FAILURE_LIMIT) {
            const detail = err instanceof Error ? err.message : String(err);
            return {
              ok: false,
              terminalState: "decision_gate",
              stopSummary: decisionGateParkStopSummary({
                summary: `landing PR review poll failed repeatedly during CI readiness: ${detail}`,
                repairHint:
                  "restore gh/auth connectivity or answer the decision gate, then re-enter landing",
              }),
            };
          }
          if (snapshot === undefined) {
            // No prior snapshot yet — blip then re-poll (same limit as mid-loop).
            await sleepPendingCiPollInterval();
            continue;
          }
          /* keep prior snapshot for a single/transient blip */
        }

        readiness = assessMergeReadiness(live, snapshot!);
        if (readiness.ready) break;

        const pendingOnly =
          readiness.blockers.length > 0 &&
          readiness.blockers.every((b) => b === "ci_pending");
        if (!pendingOnly) {
          return {
            ok: false,
            terminalState: "decision_gate",
            stopSummary: decisionGateParkStopSummary({
              summary: `landing merge blocked: ${readiness.blockers.join(", ")}`,
              repairHint:
                "resolve ruleset / threads / CI or answer the decision gate",
            }),
          };
        }
        // CI still pending — keep polling; no whole-run deadline (ID-004).
        await sleepPendingCiPollInterval();
        try {
          live = fetchState();
          consecutiveFetchFailures = 0;
        } catch (err) {
          consecutiveFetchFailures += 1;
          if (consecutiveFetchFailures >= LANDING_CI_FETCH_FAILURE_LIMIT) {
            const detail = err instanceof Error ? err.message : String(err);
            return {
              ok: false,
              terminalState: "decision_gate",
              stopSummary: decisionGateParkStopSummary({
                summary: `landing PR state fetch failed repeatedly during CI poll: ${detail}`,
                repairHint:
                  "restore gh/auth connectivity or answer the decision gate, then re-enter landing",
              }),
            };
          }
          /* keep prior live for a single/transient blip */
        }
        if (live.state.toUpperCase() === "MERGED") {
          mergeRecord = {
            prUrl: live.prUrl,
            prNumber: live.prNumber,
            remoteBranchName: live.headRefName,
            mergedHeadOid: live.headOid,
            convergedHeadOid: completionHeadOid,
          };
          break;
        }
      }

      if (mergeRecord === undefined) {
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
          try {
            const after = fetchState();
            if (after.state.toUpperCase() === "MERGED") {
              mergeRecord = {
                prUrl: after.prUrl,
                prNumber: after.prNumber,
                remoteBranchName: after.headRefName,
                mergedHeadOid: after.headOid,
                convergedHeadOid: completionHeadOid,
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
    }

    await recordPrMerged(input.familyBackend, {
      pr: prUrl,
      prNumber: mergeRecord.prNumber,
      remoteBranchName: mergeRecord.remoteBranchName,
      mergedHeadOid: mergeRecord.mergedHeadOid,
      familyHeadAfter: completionHeadOid,
    });
  }

  // ── 3. Close + cleanup AFTER live MERGED (leftovers only — ID-013 / ID-015)
  const coveredIssues = [...mergedSet(await input.familyBackend.readFamilyLedger())];
  const leftovers: string[] = [];
  let cleanupOutput: CleanupResult;

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
    // Never flip completed after MERGED — leftover only.
    // Set skippedReasons only; the ok+terminal branch below folds them into
    // leftovers once (do not push here — that double-counted).
    const detail = err instanceof Error ? err.message : String(err);
    const reason = isMissingGitRefError(err)
      ? "branch_already_gone"
      : `cleanup_exception:${detail}`;
    cleanupOutput = {
      kind: "cleanup",
      terminal: true,
      ok: true,
      skippedReasons: [reason],
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
    familyHeadAfter: completionHeadOid,
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
