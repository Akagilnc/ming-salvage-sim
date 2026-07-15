/**
 * Legacy domain validators retained for non-runner consumers and compatibility
 * parsing. ADR 0131 / #925: runner/route fate courts read only typed traffic
 * signals (judge verdict status tri-state; coder escalate field) — never cargo.
 */

import type {
  Escalation,
  StepOutput,
} from "./types.js";

/**
 * Validate the `escalate` field on an agent-step output.
 *
 * Presence of a non-null object is the worker's decision bell. `reason` and
 * `diagnosis` are cargo: missing or empty fields do not unpress the bell. This
 * compatibility predicate therefore checks presence/shape only and never routes
 * on cargo quality.
 */
export function isValidEscalation(e: unknown): e is Escalation | null | undefined {
  if (e == null) return true;
  return typeof e === "object";
}

/**
 * Read the `escalate` field off a {@link StepOutput}, narrowing safely across the
 * widened union. Agent outputs that carry an `escalate` field:
 *   - {@link CoderOutput}
 *   - {@link ReviewerOutput} (legacy open-count seats; residual)
 *   - {@link JudgeResult} (#925 — escalate status + doorbell cargo)
 *
 * Ship / cmr / merge deliberately do NOT (stuck worker is WorkerResult-level
 * `{kind:"escalated"}`; codex cmr R3b).
 */
export function escalateOf(
  output: StepOutput | undefined,
): Escalation | null | undefined {
  if (output == null) return undefined;
  if (
    output.kind === "coder" ||
    output.kind === "reviewer" ||
    output.kind === "judge"
  ) {
    return output.escalate;
  }
  return undefined;
}
