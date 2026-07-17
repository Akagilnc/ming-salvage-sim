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
/**
 * Public stage-failure ABI tokens (#922 / #942 freeze).
 * `cleanup_failed` remains for exit-code table stability until #942 cutover —
 * production landing never emits it (host cleanup-fail court deleted in #941).
 */
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
  // #941: landing owns merge; keep token merge_failed until #942 public ABI.
  merge_failed: "family landing merge stage failed",
  // Legacy ABI token only — production never sets this after #941.
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
}

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

/**
 * Single seam: raw stopSummary + stage context → FamilyRunResult terminal
 * `{ status, stopSummary }` used by merge / online-review resume tails (and any
 * same-class incomplete stage that already owns a stopSummary).
 *
 * - decision_gate_park → escalated (park preserved; no stage restamp)
 * - otherwise → stage token with status === stopSummary.reason (no infra_failure stand-in)
 */
export function familyTerminalFromStopSummary(input: {
  readonly stage: FamilyStageFailureStatus;
  readonly stopSummary: StopSummary;
}): {
  readonly status: "escalated" | FamilyStageFailureStatus;
  readonly stopSummary: StopSummary;
} {
  if (input.stopSummary.reason === "decision_gate_park") {
    return { status: "escalated", stopSummary: input.stopSummary };
  }
  return {
    status: input.stage,
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
