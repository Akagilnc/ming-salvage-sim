/** #942/#934 ID-001 public result + OS exit ABI (supersedes #929). */

import type { FamilyStageFailureStatus } from "./family/familyTerminal.js";

export const PUBLIC_RUN_RESULTS = ["completed", "parked", "failed"] as const;
export type PublicRunResult = (typeof PUBLIC_RUN_RESULTS)[number];

export const PUBLIC_FAILED_CAUSES = [
  "runner_config_invalid",
  "route_config_invalid",
  "coder_rec_invalid",
  "route_smoke_failed",
  "clone_failed",
  "worktree_prepare_failed",
  "issue_metadata_unavailable",
  "record_persist_failed",
  "resume_state_invalid",
  "runner_internal_error",
  "worker_dispatch_failed",
  "worker_termination_failed",
  "child_execution_failed",
  "dependency_cycle",
  "merger_worker_failed",
  "child_merge_failed",
  "verification_failed",
  "cmr_review_failed",
  "cmr_fix_failed",
  "ship_failed",
  "online_review_worker_failed",
  "ci_failed",
  "landing_worker_failed",
] as const;
export type PublicFailedCause = (typeof PUBLIC_FAILED_CAUSES)[number];

export const PUBLIC_EXIT_CODES: Readonly<Record<PublicRunResult, number>> = {
  completed: 0,
  parked: 2,
  failed: 1,
};

export const LEGACY_929_PUBLIC_STATUS_TOKENS = [
  "success",
  "already_done",
  "escalated",
  "incomplete",
  "error",
  "escalate",
  "verify_failed",
  "cmr_failed",
  "ship_failed",
  "online_review_failed",
  "merge_failed",
  "cleanup_failed",
] as const;

const PUBLIC_RESULT_SET: ReadonlySet<string> = new Set(PUBLIC_RUN_RESULTS);
const LEGACY_929_SET: ReadonlySet<string> = new Set(LEGACY_929_PUBLIC_STATUS_TOKENS);

const STAGE_CAUSE: Readonly<Record<FamilyStageFailureStatus, PublicFailedCause>> = {
  verify_failed: "verification_failed",
  cmr_failed: "cmr_review_failed",
  ship_failed: "ship_failed",
  online_review_failed: "online_review_worker_failed",
  merge_failed: "landing_worker_failed",
  cleanup_failed: "landing_worker_failed",
};

export function isPublicRunResult(value: unknown): value is PublicRunResult {
  return typeof value === "string" && PUBLIC_RESULT_SET.has(value);
}

export function isLegacy929PublicStatusToken(value: unknown): boolean {
  return typeof value === "string" && LEGACY_929_SET.has(value);
}

export function exitCodeForPublicResult(status: PublicRunResult | string): number {
  return isPublicRunResult(status) ? PUBLIC_EXIT_CODES[status] : PUBLIC_EXIT_CODES.failed;
}

export function familyDriverExitCode(
  result: { readonly status: string } | string,
): number {
  return exitCodeForPublicResult(typeof result === "string" ? result : result.status);
}

export function runResultExitCode(
  result: { readonly status: string } | string,
): number {
  return familyDriverExitCode(result);
}

export function exitProcessForFamilyRun(
  result: { readonly status: string },
  exitFn: (code: number) => void = (code) => {
    process.exit(code);
  },
): number {
  const code = familyDriverExitCode(result);
  exitFn(code);
  return code;
}

export function causeFromStageFailure(
  stage: FamilyStageFailureStatus,
): PublicFailedCause {
  return STAGE_CAUSE[stage];
}
