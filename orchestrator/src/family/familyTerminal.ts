/** #922/#942 stage diagnostics; public ABI is completed|parked|failed (publicResult). */

import {
  FAMILY_STAGE_FAILURE_STATUSES,
  causeFromStageFailure,
  isFamilyStageFailureStatus,
  type FamilyStageFailureStatus,
  type PublicFailedCause,
  type PublicRunResult,
} from "../publicResult.js";
import type { StopSummary } from "../stopSummary.js";

// Re-export stage diagnostic tokens from publicResult (single source; LEGACY_929 composes them).
export {
  FAMILY_STAGE_FAILURE_STATUSES,
  isFamilyStageFailureStatus,
  type FamilyStageFailureStatus,
};

const DEFAULT_SUMMARY: Readonly<Record<FamilyStageFailureStatus, string>> = {
  verify_failed: "family verify barrier failed",
  cmr_failed: "family integrated CMR barrier failed",
  ship_failed: "family ship stage failed",
  online_review_failed: "family online review stage failed",
  merge_failed: "family landing merge stage failed",
  cleanup_failed: "family post-merge cleanup stage failed (legacy token)",
};

const DEFAULT_REPAIR: Readonly<Record<FamilyStageFailureStatus, string>> = {
  verify_failed:
    "inspect the family ledger aborted entry, repair the failing verify, and rerun",
  cmr_failed:
    "inspect the family ledger aborted/cmr entry, repair the integrated CMR, and rerun",
  ship_failed:
    "repair the family ship worker infrastructure/auth/toolchain failure and rerun the final family barrier",
  online_review_failed:
    "resolve remaining online review findings or answer the decision gate, then re-feed the family run",
  merge_failed:
    "resolve landing/merge blockers or answer the decision gate, then re-enter landing",
  cleanup_failed:
    "legacy token only — re-enter landing after live MERGED; leftovers never fail the run",
};

/** Stage diagnostic stopSummary (reason = stage token). */
export function stageFailureStopSummary(input: {
  readonly status: FamilyStageFailureStatus;
  readonly summary?: string;
  readonly repairHint?: string;
  readonly metadata?: StopSummary["metadata"];
}): StopSummary {
  return {
    reason: input.status,
    summary: input.summary ?? DEFAULT_SUMMARY[input.status],
    repairHint: input.repairHint ?? DEFAULT_REPAIR[input.status],
    ...(input.metadata !== undefined ? { metadata: input.metadata } : {}),
  };
}

/** Restamp barrier stopSummary.reason to stage; leave decision parks. */
export function syncStopSummaryToStageFailure(
  status: FamilyStageFailureStatus,
  barrier: StopSummary | undefined,
): StopSummary {
  if (barrier == null) {
    return stageFailureStopSummary({ status });
  }
  if (barrier.reason === "decision_gate_park") {
    return barrier;
  }
  return {
    ...barrier,
    reason: status,
  };
}

/** Red barrier → parked (decision) or failed+cause (stage). */
export function resolveFamilyStageTerminal(input: {
  readonly failedStatus?: FamilyStageFailureStatus;
  readonly barrierStopSummary?: StopSummary;
  readonly defaultStatus?: FamilyStageFailureStatus;
}):
  | {
      readonly kind: "failed";
      readonly stage: FamilyStageFailureStatus;
      readonly cause: PublicFailedCause;
    }
  | { readonly kind: "parked"; readonly stopSummary: StopSummary } {
  const barrier = input.barrierStopSummary;
  if (barrier?.reason === "decision_gate_park") {
    return { kind: "parked", stopSummary: barrier };
  }
  const stage =
    input.failedStatus !== undefined
      ? input.failedStatus
      : barrier !== undefined && isFamilyStageFailureStatus(barrier.reason)
        ? barrier.reason
        : (input.defaultStatus ?? "verify_failed");
  return {
    kind: "failed",
    stage,
    cause: causeFromStageFailure(stage),
  };
}

/** stopSummary + stage → public parked|failed (+ required cause on failed). */
export function familyTerminalFromStopSummary(input: {
  readonly stage: FamilyStageFailureStatus;
  readonly stopSummary: StopSummary;
}):
  | { readonly status: "parked"; readonly stopSummary: StopSummary }
  | {
      readonly status: "failed";
      readonly cause: PublicFailedCause;
      readonly stopSummary: StopSummary;
    } {
  if (input.stopSummary.reason === "decision_gate_park") {
    return { status: "parked", stopSummary: input.stopSummary };
  }
  return {
    status: "failed",
    cause: causeFromStageFailure(input.stage),
    stopSummary: stageFailureStopSummary({
      status: input.stage,
      summary: input.stopSummary.summary,
      repairHint: input.stopSummary.repairHint,
      ...(input.stopSummary.metadata !== undefined
        ? { metadata: input.stopSummary.metadata }
        : {}),
    }),
  };
}
