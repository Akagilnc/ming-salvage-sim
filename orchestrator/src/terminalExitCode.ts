/**
 * #929 — pure terminal → process exit-code map.
 *
 * Drivers are a thin shell: `process.exit(exitCodeForTerminal(status))`.
 * Machine consumers classify a failed run by exit code alone (no log parse).
 *
 * Success class shares 0 (PRD #919): `success` and `already_done`.
 * Every non-success terminal owns a unique non-zero code (no collisions).
 */

import type { FamilyRunResult, FamilyRunStatus } from "./family/types.js";
import type { HandoffStatus, RunResult } from "./types.js";

/**
 * Full terminal vocabulary the exit-code map covers.
 * Family stage names (#922) + outcome classes (escalated / incomplete / error)
 * + success class (success / already_done).
 */
export const TERMINAL_EXIT_STATUSES = [
  "success",
  "already_done",
  "escalated",
  "incomplete",
  "error",
  "verify_failed",
  "cmr_failed",
  "ship_failed",
  "online_review_failed",
  "merge_failed",
  "cleanup_failed",
] as const;

export type TerminalExitStatus = (typeof TERMINAL_EXIT_STATUSES)[number];

/**
 * Canonical exit codes. Do not renumber casually — external drivers / cron
 * may key on these values.
 *
 * | terminal                 | code |
 * |--------------------------|------|
 * | success                  | 0    |
 * | already_done             | 0    |
 * | escalated                | 10   |
 * | incomplete               | 11   |
 * | error                    | 12   |
 * | verify_failed            | 20   |
 * | cmr_failed               | 21   |
 * | ship_failed              | 22   |
 * | online_review_failed     | 23   |
 * | merge_failed             | 24   |
 * | cleanup_failed           | 25   |
 */
export const TERMINAL_EXIT_CODES: Readonly<Record<TerminalExitStatus, number>> =
  {
    success: 0,
    already_done: 0,
    escalated: 10,
    incomplete: 11,
    error: 12,
    verify_failed: 20,
    cmr_failed: 21,
    ship_failed: 22,
    online_review_failed: 23,
    merge_failed: 24,
    cleanup_failed: 25,
  };

const TERMINAL_EXIT_SET: ReadonlySet<string> = new Set(TERMINAL_EXIT_STATUSES);

export function isTerminalExitStatus(
  value: unknown,
): value is TerminalExitStatus {
  return typeof value === "string" && TERMINAL_EXIT_SET.has(value);
}

/**
 * Pure map: terminal name → process exit code.
 * Unknown tokens fail closed as `error` (nonzero) so a driver never
 * accidentally exits 0 on a novel failure string.
 */
export function exitCodeForTerminal(status: TerminalExitStatus | string): number {
  if (isTerminalExitStatus(status)) {
    return TERMINAL_EXIT_CODES[status];
  }
  return TERMINAL_EXIT_CODES.error;
}

/** Family driver shell — map {@link FamilyRunResult.status} to exit code. */
export function familyDriverExitCode(
  result: Pick<FamilyRunResult, "status"> | FamilyRunStatus,
): number {
  const status = typeof result === "string" ? result : result.status;
  return exitCodeForTerminal(status);
}

/**
 * Single-slice {@link RunResult} → exit code.
 * HandoffStatus uses `escalate` (verb); map table uses `escalated` (family noun).
 */
export function runResultExitCode(
  result: Pick<RunResult, "status"> | HandoffStatus,
): number {
  const status = typeof result === "string" ? result : result.status;
  if (status === "success") return TERMINAL_EXIT_CODES.success;
  if (status === "escalate") return TERMINAL_EXIT_CODES.escalated;
  if (status === "error") return TERMINAL_EXIT_CODES.error;
  return exitCodeForTerminal(status);
}

/**
 * Thin driver shell: exit the process with the mapped code.
 * Injectable `exitFn` keeps the shell unit-testable without killing vitest.
 */
export function exitProcessForFamilyRun(
  result: Pick<FamilyRunResult, "status">,
  exitFn: (code: number) => void = (code) => {
    process.exit(code);
  },
): number {
  const code = familyDriverExitCode(result);
  exitFn(code);
  return code;
}
