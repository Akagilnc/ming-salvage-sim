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
  githubFieldEquals,
  mergeRecordIfHeadAligned,
  type MergeRecordAlignment,
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
  familyDocsReleasedForHead,
  familyPostMergeCleanupForHead,
  familyPrMergedForHead,
  mergedSet,
  recordAborted,
  recordDocsReleased,
  recordFamilyEscalated,
  recordPostMergeCleanup,
  recordPrMerged,
  recordReviewLoopConverged,
} from "./ledger.js";
import { billingPoolForFamilyWorker } from "./familyWorkerSlots.js";
import { dispatchFamilyWorkerOrAbort } from "./familyProcessRootDispatch.js";
import { sleepPendingCiPollInterval } from "./onlineReviewLoop.js";
import type { FamilyBackend } from "./types.js";
import { shouldReclaimFamilyHost } from "../hostReclaim.js";
import { stageFailureStopSummary } from "./familyTerminal.js";

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
 * Single durable exit for non-ok landing (family/914 CR Standards DRY).
 * Fresh final-barrier (`verifyCmr`) and resume re-entry (`runner`) share this
 * writer — park → escalated decision; hard_fail → aborted + merge_failed stop.
 * Callers only map the returned kind onto their own result shape.
 */
export type LandingActionFailureRecorded =
  | { readonly kind: "park"; readonly stopSummary: StopSummary }
  | { readonly kind: "hard_fail"; readonly stopSummary: StopSummary };

export async function recordLandingActionFailure(
  familyBackend: FamilyBackend,
  landing: LandingActionResult,
  input: {
    readonly phase?: "wave" | "final";
    readonly familyHeadAfter: string;
  },
): Promise<LandingActionFailureRecorded> {
  const classified = classifyLandingActionResult(landing);
  if (classified.kind === "ok") {
    throw new Error(
      "recordLandingActionFailure called on ok landing result",
    );
  }
  const phase = input.phase ?? "final";
  if (classified.kind === "park") {
    await recordFamilyEscalated(familyBackend, {
      escalationKind: "decision",
      phase,
      reason: classified.stopSummary.summary,
      familyHeadAfter: input.familyHeadAfter,
      stopSummary: classified.stopSummary,
    });
    return classified;
  }
  const failStop = stageFailureStopSummary({
    status: "merge_failed",
    summary: classified.stopSummary.summary,
    repairHint:
      classified.stopSummary.repairHint ??
      "repair landing and re-enter the family final barrier",
  });
  await recordAborted(familyBackend, {
    phase,
    reason: failStop.summary,
    familyHeadAfter: input.familyHeadAfter,
    stopSummary: failStop,
  });
  return { kind: "hard_fail", stopSummary: failStop };
}

/**
 * Consecutive mid-loop live I/O failures before landing parks (Std S4 / R2 S1).
 * Covers both `fetchState` and `pollSnapshot` / `pollOnce` — auth/API death
 * must not keep-prior forever or escape as an uncaught throw.
 */
export const LANDING_CI_FETCH_FAILURE_LIMIT = 3;

/**
 * After `gh pr merge` succeeds, live MERGED may lag GitHub's eventual-consistency
 * window. Bounded retries before parking as ambiguous (R4-CX1) — not stale green.
 */
export const LANDING_MERGED_CONFIRM_ATTEMPTS = 3;

/** Injectable live GitHub/git surface for tests — production uses gh defaults. */
export interface LandingLiveHooks {
  readonly fetchState: () => PrMergeLiveState;
  readonly executeMerge?: (prNumber: number, headOid: string) => void;
  /** Same three-state surface as {@link confirmPrMergedLive} (L2 / local CR nit). */
  readonly confirmMerged?: (
    expectedHeadOid: string,
  ) => MergeRecordAlignment;
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
      kind: "aligned" as const,
      record: {
        prUrl: input.prUrl,
        prNumber,
        remoteBranchName: input.remoteBranchName,
        mergedHeadOid: expectedHeadOid,
        convergedHeadOid: expectedHeadOid,
      },
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
 * Dual-key ledger resume: live (post-docs) HEAD first, then pre-doc
 * convergedHeadOid fallback for markers stamped before the post-doc re-key.
 * Single authority — do not re-copy live ?? pre-doc at call sites.
 */
function dualKeyLedgerLookup<T>(
  lookup: (head: string) => T | undefined,
  liveMarkerHead: string,
  preDocHead: string,
): T | undefined {
  return (
    lookup(liveMarkerHead) ??
    (liveMarkerHead !== preDocHead ? lookup(preDocHead) : undefined)
  );
}

function landingCiIoPark(
  detail: string,
  phase: "poll" | "state_fetch",
): LandingActionResult {
  const summary =
    phase === "poll"
      ? `landing PR review poll failed repeatedly during CI readiness: ${detail}`
      : `landing PR state fetch failed repeatedly during CI poll: ${detail}`;
  return {
    ok: false,
    terminalState: "decision_gate",
    stopSummary: decisionGateParkStopSummary({
      summary,
      repairHint:
        "restore gh/auth connectivity or answer the decision gate, then re-enter landing",
    }),
  };
}

function mergedHeadMismatchPark(
  liveHeadOid: string,
  completionHeadOid: string,
): LandingActionResult {
  return {
    ok: false,
    terminalState: "decision_gate",
    stopSummary: decisionGateParkStopSummary({
      summary: `landing PR is MERGED but head ${liveHeadOid} does not match completion head ${completionHeadOid}`,
      repairHint:
        "ensure the merged PR contains the landing docs/release commit, or answer the decision gate",
    }),
  };
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
  const priorCleanup = dualKeyLedgerLookup(
    (head) => familyPostMergeCleanupForHead(ledger, head),
    liveMarkerHead,
    input.convergedHeadOid,
  );
  if (priorCleanup !== undefined) {
    return { ok: true, terminalState: "already_done" };
  }

  const priorMerged = dualKeyLedgerLookup(
    (head) => familyPrMergedForHead(ledger, head),
    liveMarkerHead,
    input.convergedHeadOid,
  );
  // Durable docs release (CR-6): crash after worker push must not re-dispatch
  // VERSION/CHANGELOG. Keyed post-release HEAD (dual-key with pre-doc fallback).
  let priorDocsReleased = dualKeyLedgerLookup(
    (head) => familyDocsReleasedForHead(ledger, head),
    liveMarkerHead,
    input.convergedHeadOid,
  );
  // Infer successful prior release when HEAD advanced past pre-doc OID but the
  // docs_released row never landed (crash after push, before ledger write).
  // Empty-run leaves HEAD unchanged → re-dispatch is idempotent (文档发布空跑).
  if (
    priorMerged === undefined &&
    priorDocsReleased === undefined &&
    liveMarkerHead !== input.convergedHeadOid
  ) {
    await recordDocsReleased(input.familyBackend, {
      pr: prUrl,
      familyHeadAfter: liveMarkerHead,
    });
    await recordReviewLoopConverged(input.familyBackend, {
      pr: prUrl,
      familyHeadAfter: liveMarkerHead,
    });
    priorDocsReleased = {
      pr: prUrl,
      familyHeadAfter: liveMarkerHead,
    };
  }
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
  // Skip when already merged OR docs already durably released for this head.
  const docsNeedRun =
    priorMerged === undefined && priorDocsReleased === undefined;
  if (docsNeedRun) {
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
    // CR-6 durable window: stamp pre-doc key IMMEDIATELY on released:true so a
    // crash before post-HEAD re-read still dual-key skips re-dispatch.
    await recordDocsReleased(input.familyBackend, {
      pr: prUrl,
      familyHeadAfter: input.convergedHeadOid,
    });
  }

  // Docs may have advanced family HEAD. Re-read live HEAD only when docs just
  // ran this entry (not when priorMerged / priorDocsReleased already covers it).
  const completionHeadOid = docsNeedRun
    ? await resolveLandingMarkerHead(
        input.familyBackend,
        input.familyBase,
        input.convergedHeadOid,
      )
    : liveMarkerHead;
  if (docsNeedRun && completionHeadOid !== input.convergedHeadOid) {
    // Post-doc key + re-stamp so resume dual-key / already-converged short path
    // find markers after a non-empty docs push.
    await recordDocsReleased(input.familyBackend, {
      pr: prUrl,
      familyHeadAfter: completionHeadOid,
    });
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

    const entryMerged = mergeRecordIfHeadAligned(live, completionHeadOid);
    if (entryMerged.kind === "mismatch") {
      return mergedHeadMismatchPark(entryMerged.headOid, completionHeadOid);
    }
    if (entryMerged.kind === "aligned") {
      mergeRecord = entryMerged.record;
    } else if (githubFieldEquals(live.state, "CLOSED")) {
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

      // Std S4 / R2 S1 / R3-G2 / L1: repeated live I/O failures (fetchState OR
      // pollOnce) → decision_gate. Fail-closed per failed round: never assess
      // readiness from a stale snapshot/live after I/O death — on the next
      // success path refresh live first (or keep fail-closed until refresh works).
      let consecutiveFetchFailures = 0;
      let consecutivePollFailures = 0;
      let liveStaleAfterIoFailure = false;
      let snapshot: PrReviewSnapshot | undefined;
      let readiness: ReturnType<typeof assessMergeReadiness> | undefined;
      while (true) {
        try {
          snapshot = await pollOnce();
          consecutivePollFailures = 0;
        } catch (err) {
          consecutivePollFailures += 1;
          liveStaleAfterIoFailure = true;
          if (consecutivePollFailures >= LANDING_CI_FETCH_FAILURE_LIMIT) {
            const detail = err instanceof Error ? err.message : String(err);
            return landingCiIoPark(detail, "poll");
          }
          // Fail-closed (R3-G2): do not assess with a prior snapshot this round.
          await sleepPendingCiPollInterval();
          continue;
        }

        if (liveStaleAfterIoFailure) {
          try {
            live = fetchState();
            consecutiveFetchFailures = 0;
            liveStaleAfterIoFailure = false;
          } catch (err) {
            consecutiveFetchFailures += 1;
            if (consecutiveFetchFailures >= LANDING_CI_FETCH_FAILURE_LIMIT) {
              const detail = err instanceof Error ? err.message : String(err);
              return landingCiIoPark(detail, "state_fetch");
            }
            // Still fail-closed: do not assess with stale live.
            await sleepPendingCiPollInterval();
            continue;
          }
          const refreshedMerged = mergeRecordIfHeadAligned(
            live,
            completionHeadOid,
          );
          if (refreshedMerged.kind === "mismatch") {
            return mergedHeadMismatchPark(
              refreshedMerged.headOid,
              completionHeadOid,
            );
          }
          if (refreshedMerged.kind === "aligned") {
            mergeRecord = refreshedMerged.record;
            break;
          }
        }

        readiness = assessMergeReadiness(live, snapshot);
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
          liveStaleAfterIoFailure = false;
        } catch (err) {
          consecutiveFetchFailures += 1;
          liveStaleAfterIoFailure = true;
          if (consecutiveFetchFailures >= LANDING_CI_FETCH_FAILURE_LIMIT) {
            const detail = err instanceof Error ? err.message : String(err);
            return landingCiIoPark(detail, "state_fetch");
          }
          // Fail-closed: do not judge MERGED/ready from stale live this round.
          continue;
        }
        const midMerged = mergeRecordIfHeadAligned(live, completionHeadOid);
        if (midMerged.kind === "mismatch") {
          return mergedHeadMismatchPark(midMerged.headOid, completionHeadOid);
        }
        if (midMerged.kind === "aligned") {
          mergeRecord = midMerged.record;
          break;
        }
      }

      if (mergeRecord === undefined) {
        // Merge only the completion (post-docs) head — never a foreign tip.
        if (live.headOid !== completionHeadOid) {
          return {
            ok: false,
            terminalState: "decision_gate",
            stopSummary: decisionGateParkStopSummary({
              summary: `landing ready but live PR head ${live.headOid} does not match completion head ${completionHeadOid}`,
              repairHint:
                "ensure the PR tip includes the landing docs/release commit, then re-enter landing",
            }),
          };
        }
        const doMerge =
          liveHooks?.executeMerge ??
          ((prNumber: number, headOid: string) =>
            executePrMergeCommit(sh, familyRepo, prNumber, headOid));
        try {
          doMerge(live.prNumber, completionHeadOid);
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

        // R4-CX1 / L2: merge exit ≠ live MERGED. Bounded confirm retries cover
        // propagation lag. Hooks and production share MergeRecordAlignment.
        const confirmAlignment = (
          expectedHeadOid: string,
        ): MergeRecordAlignment => {
          if (liveHooks?.confirmMerged !== undefined) {
            return liveHooks.confirmMerged(expectedHeadOid);
          }
          return confirmPrMergedLive(
            sh,
            familyRepo,
            prUrl,
            expectedHeadOid,
          );
        };
        for (
          let attempt = 0;
          attempt < LANDING_MERGED_CONFIRM_ATTEMPTS;
          attempt += 1
        ) {
          let alignment: MergeRecordAlignment;
          try {
            alignment = confirmAlignment(completionHeadOid);
          } catch {
            alignment = { kind: "not_merged" };
          }
          if (alignment.kind === "mismatch") {
            return mergedHeadMismatchPark(
              alignment.headOid,
              completionHeadOid,
            );
          }
          if (alignment.kind === "aligned") {
            mergeRecord = alignment.record;
            break;
          }
          // not_merged: probe live again (hooks may lag confirm while live
          // already shows MERGED; also surfaces mismatch the hook cannot express).
          try {
            const after = fetchState();
            const afterMerged = mergeRecordIfHeadAligned(
              after,
              completionHeadOid,
            );
            if (afterMerged.kind === "mismatch") {
              return mergedHeadMismatchPark(
                afterMerged.headOid,
                completionHeadOid,
              );
            }
            if (afterMerged.kind === "aligned") {
              mergeRecord = afterMerged.record;
              break;
            }
          } catch {
            /* try again / fall through */
          }
          if (attempt + 1 < LANDING_MERGED_CONFIRM_ATTEMPTS) {
            await sleepPendingCiPollInterval();
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
    // R5-CX1: mergeRecord already proved MERGED. Never re-fetch live for the
    // cleanup merge gate — lag OPEN would skip issue close yet still stamp
    // terminal post_merge_cleanup → resume already_done without closing.
    const liveForCleanup: PrMergeLiveState = {
      prNumber: mergeRecord.prNumber,
      prUrl: mergeRecord.prUrl,
      state: "MERGED",
      headOid: mergeRecord.mergedHeadOid,
      headRefName: mergeRecord.remoteBranchName,
      mergeStateStatus: "UNKNOWN",
    };
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
        mergeStateStatus: liveForCleanup.mergeStateStatus,
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
