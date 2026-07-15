/**
 * #922 — family terminal real names.
 *
 * The post-wave final barrier used to collapse every stage failure into the
 * umbrella `verify_failed`. Callers (and resume) must see the stage that
 * actually died: verify / CMR / ship / online review / merge / cleanup.
 *
 * FamilyRunResult.status and StopSummary.reason use the SAME token for these
 * stage failures (no alias layer, no "infra_failure" stand-in).
 */

import type { StopSummary } from "../stopSummary.js";

/** Per-stage family terminal failure names (PRD #919 / issue #922). */
export const FAMILY_STAGE_FAILURE_STATUSES = [
  "verify_failed",
  "cmr_failed",
  "ship_failed",
  "online_review_failed",
  "merge_failed",
  "cleanup_failed",
] as const;

export type FamilyStageFailureStatus =
  (typeof FAMILY_STAGE_FAILURE_STATUSES)[number];

const STAGE_FAILURE_SET: ReadonlySet<string> = new Set(
  FAMILY_STAGE_FAILURE_STATUSES,
);

export function isFamilyStageFailureStatus(
  value: unknown,
): value is FamilyStageFailureStatus {
  return typeof value === "string" && STAGE_FAILURE_SET.has(value);
}

const DEFAULT_SUMMARY: Readonly<Record<FamilyStageFailureStatus, string>> = {
  verify_failed: "family verify barrier failed",
  cmr_failed: "family integrated CMR barrier failed",
  ship_failed: "family ship stage failed",
  online_review_failed: "family online review stage failed",
  merge_failed: "family auto-merge stage failed",
  cleanup_failed: "family post-merge cleanup stage failed",
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
    "resolve merge blockers or answer the decision gate, then re-feed the family run",
  cleanup_failed:
    "verify PR is MERGED with matching head, then re-run the family final barrier",
};

/**
 * Build a stage-named stop summary. `reason` is always the stage token so
 * family aggregation and stopSummary stay synchronized.
 */
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

/**
 * Re-stamp an existing barrier stopSummary so its reason matches the stage
 * terminal name, preserving summary / repairHint / metadata. Decision parks
 * are left untouched (caller routes those to `escalated`).
 */
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

/**
 * Resolve the honest family terminal for a red barrier:
 * - decision_gate_park → escalated (answerable pause, not a stage failure)
 * - explicit failedStatus from the verify/cmr hook wins
 * - barrier stopSummary already carrying a stage token is reused (resume truth)
 * - otherwise default to verify_failed (wave verify / bare inject hooks)
 */
export function resolveFamilyStageTerminal(input: {
  readonly failedStatus?: FamilyStageFailureStatus;
  readonly barrierStopSummary?: StopSummary;
  readonly defaultStatus?: FamilyStageFailureStatus;
}):
  | { readonly kind: "stage"; readonly status: FamilyStageFailureStatus }
  | { readonly kind: "escalated"; readonly stopSummary: StopSummary } {
  const barrier = input.barrierStopSummary;
  if (barrier?.reason === "decision_gate_park") {
    return { kind: "escalated", stopSummary: barrier };
  }
  if (input.failedStatus !== undefined) {
    return { kind: "stage", status: input.failedStatus };
  }
  if (barrier !== undefined && isFamilyStageFailureStatus(barrier.reason)) {
    return { kind: "stage", status: barrier.reason };
  }
  return {
    kind: "stage",
    status: input.defaultStatus ?? "verify_failed",
  };
}
