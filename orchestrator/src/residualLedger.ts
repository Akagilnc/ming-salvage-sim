/**
 * Residual + live judge open-set rebuild from ledger (#919 F4 extract).
 *
 * Pure projection used by the single-slice runner on crash/resume. Lives outside
 * runner.ts so Divergent Change on residual rebuild does not touch the god
 * orchestration loop.
 */

import {
  isJudgeSeat,
  projectJudgeContinueBlocking,
  projectResidualReviewerToJudge,
} from "./judgeStation.js";
import {
  isStepId,
  type Finding,
  type FindingDisposition,
  type LedgerEntry,
  type StepOutput,
  type WorkerLandingPayload,
  type WorkerMonitorHandle,
} from "./types.js";

export interface BlockingFromLedgerRebuild {
  readonly blocking: ReadonlyArray<Finding>;
  readonly blockingIdentityKeys: ReadonlyArray<string>;
  /** Declared open-count (residual/rebuild bookkeeping), not findings-array length. */
  readonly blockingFindingCount: number;
  readonly findingDispositions: ReadonlyArray<FindingDisposition>;
  /**
   * Rebuilt raw artifact pointers for the positive-count → S5 edge after a
   * judge-continue or residual S4 resume boundary (host paths; materialised
   * into the fixer sandbox at landing).
   */
  readonly rawReviewerArtifacts?: WorkerLandingPayload["rawReviewerArtifacts"];
}

/**
 * Opaque pointers to the preceding reviewer's raw products. Always attached on
 * the positive-count → S5 edge so sparse/missing findings cargo cannot produce
 * a no-op fixer landing (ADR 0131 / #899).
 */
export function reviewerRawArtifactPointers(
  handle: WorkerMonitorHandle | undefined,
  sessionId: string | undefined,
): NonNullable<WorkerLandingPayload["rawReviewerArtifacts"]> {
  return {
    ...(handle?.logPath !== undefined ? { stdoutPath: handle.logPath } : {}),
    ...(handle?.resultPath !== undefined ? { sidecarPath: handle.resultPath } : {}),
    ...(sessionId !== undefined ? { reviewerSessionId: sessionId } : {}),
    statement: "the previous reviewer raw artifacts are here",
  };
}

/**
 * Historical residual open-set projection (pre-#925 open-count paper).
 *
 * **Single-slice crash/resume only** (#919 CR N4). Not a live court closer and
 * never a family production path. Positive residual count may project continue
 * solely so historical ledgers rebuild the open set for fixer redispatch —
 * live seats mint typed `kind:"judge"` instead.
 *
 * Shared by the S4-attached residual arm and the pre-S4 crash residual arm in
 * {@link rebuildBlockingFromLedger}. Cargo keeps raw findings + declared count
 * with empty identity keys (lossless vs inventing `__open_N`); raw artifacts
 * attach only when residual→judge projects continue.
 */
export function applyHistoricalResidualOpenSet(
  lastReviewerOutput: Extract<StepOutput, { kind: "reviewer" }>,
  monitor: WorkerMonitorHandle | undefined,
  sessionId: string | undefined,
): {
  readonly blocking: Finding[];
  readonly blockingIdentityKeys: string[];
  readonly blockingFindingCount: number;
  readonly rawReviewerArtifacts?: NonNullable<
    WorkerLandingPayload["rawReviewerArtifacts"]
  >;
} {
  const projectsContinue =
    projectResidualReviewerToJudge(lastReviewerOutput)?.status === "continue";
  return {
    blocking: [...lastReviewerOutput.findings],
    blockingIdentityKeys: [],
    blockingFindingCount: lastReviewerOutput.findingsCount,
    ...(projectsContinue
      ? {
          rawReviewerArtifacts: reviewerRawArtifactPointers(
            monitor,
            sessionId,
          ),
        }
      : {}),
  };
}

/**
 * Rebuild the S5 open-set / kill flips / raw-artifact pointers from a
 * persisted ledger (crash/resume seed).
 *
 * Single shared projection (F2/F3) — not S4-only:
 *   - #925 live path: S3/S6 `kind:"judge" status:"continue"` → kills + live-only
 *     open set (same as in-process continue edge via
 *     {@link projectJudgeContinueBlocking}).
 *   - Residual historical path: S4 + preceding `kind:"reviewer"` open-count.
 *
 * Walk order: last applicable projection wins for the open set; judge kill
 * flips accumulate across continue rounds (mirrors the live path).
 */
export function rebuildBlockingFromLedger(
  ledger: ReadonlyArray<LedgerEntry>,
): BlockingFromLedgerRebuild {
  let pendingBlockingFindings: Finding[] = [];
  let pendingBlockingFindingIdentityKeys: string[] = [];
  let pendingBlockingFindingCount = 0;
  let findingDispositions: FindingDisposition[] = [];
  let lastReviewerOutputForS4: StepOutput | undefined;
  let lastReviewerSessionId: string | undefined;
  let lastReviewerMonitorHandle: WorkerMonitorHandle | undefined;
  let pendingRawReviewerArtifacts: WorkerLandingPayload["rawReviewerArtifacts"];
  /** Index of the last judge-continue projection (suppresses stale residual rebind). */
  let lastJudgeContinueIndex = -1;

  for (let i = 0; i < ledger.length; i++) {
    const entry = ledger[i]!;
    // Bookkeeping rows (event markers) never seed the open set.
    if (entry.event != null) {
      continue;
    }

    // #925 / #919 S1: judge continue rebuilds open set the same way as the live edge.
    if (
      isJudgeSeat({ step: entry.step }) &&
      entry.output?.kind === "judge" &&
      entry.output.status === "continue"
    ) {
      const projected = projectJudgeContinueBlocking(entry.output);
      if (projected !== undefined) {
        if (projected.terminalDispositions.length > 0) {
          findingDispositions = [
            ...findingDispositions,
            ...projected.terminalDispositions,
          ];
        }
        pendingBlockingFindings = projected.blocking;
        pendingBlockingFindingIdentityKeys = projected.blockingIdentityKeys;
        pendingBlockingFindingCount = projected.blockingFindingCount;
        pendingRawReviewerArtifacts =
          projected.blockingFindingCount > 0
            ? reviewerRawArtifactPointers(
                entry.monitorHandle,
                typeof entry.sessionId === "string" ? entry.sessionId : undefined,
              )
            : undefined;
        lastJudgeContinueIndex = i;
        // A later residual reviewer must not clobber this open set via the
        // pre-S4 rebind below unless a newer S4 residual follows.
        lastReviewerOutputForS4 = undefined;
        lastReviewerSessionId = undefined;
        lastReviewerMonitorHandle = undefined;
      }
      continue;
    }

    if (entry.output?.kind === "reviewer") {
      if (!isStepId(entry.step)) continue;
      lastReviewerOutputForS4 = entry.output;
      lastReviewerSessionId =
        typeof entry.sessionId === "string" ? entry.sessionId : undefined;
      lastReviewerMonitorHandle = entry.monitorHandle;
      continue;
    }
    if (entry.step !== "S4" || lastReviewerOutputForS4?.kind !== "reviewer") {
      continue;
    }

    // Historical residual only (pre-#925 S4 + open-count paper).
    findingDispositions = [...(entry.findingDispositions ?? [])];
    {
      const residualOpen = applyHistoricalResidualOpenSet(
        lastReviewerOutputForS4,
        lastReviewerMonitorHandle,
        lastReviewerSessionId,
      );
      pendingBlockingFindings = residualOpen.blocking;
      pendingBlockingFindingIdentityKeys = residualOpen.blockingIdentityKeys;
      pendingBlockingFindingCount = residualOpen.blockingFindingCount;
      pendingRawReviewerArtifacts = residualOpen.rawReviewerArtifacts;
    }
    lastJudgeContinueIndex = -1;
  }

  // Historical residual only — pre-S4 crash window: last reviewer has positive
  // open-count but no S4 yet / stale earlier S4. Skip when a later judge
  // continue already projected the live open set (new path has no S4).
  if (
    lastJudgeContinueIndex < 0 &&
    lastReviewerOutputForS4?.kind === "reviewer"
  ) {
    const residualOpen = applyHistoricalResidualOpenSet(
      lastReviewerOutputForS4,
      lastReviewerMonitorHandle,
      lastReviewerSessionId,
    );
    // Pre-S4 crash rebind only when residual→judge projects continue
    // (raw artifacts present by construction of applyHistoricalResidualOpenSet).
    if (residualOpen.rawReviewerArtifacts !== undefined) {
      pendingBlockingFindings = residualOpen.blocking;
      pendingBlockingFindingIdentityKeys = residualOpen.blockingIdentityKeys;
      pendingBlockingFindingCount = residualOpen.blockingFindingCount;
      pendingRawReviewerArtifacts = residualOpen.rawReviewerArtifacts;
    }
  }

  return {
    blocking: pendingBlockingFindings,
    blockingIdentityKeys: pendingBlockingFindingIdentityKeys,
    blockingFindingCount: pendingBlockingFindingCount,
    findingDispositions,
    ...(pendingRawReviewerArtifacts !== undefined
      ? { rawReviewerArtifacts: pendingRawReviewerArtifacts }
      : {}),
  };
}
