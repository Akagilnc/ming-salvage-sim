/**
 * Legacy domain validators retained for non-runner consumers and compatibility
 * parsing. ADR 0131 forbids runner/route from using them as fate courts: reviewer
 * routing reads only the worker-declared open count.
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
 * widened union. Only the AGENT outputs ({@link CoderOutput}/{@link ReviewerOutput})
 * carry an `escalate` field — the new worker payloads (ship / cmr / merge) DELIBERATELY
 * do NOT (a stuck worker is the WorkerResult-level `{kind:"escalated"}` case; codex
 * cmr R3b). So this returns the escalate only for coder/reviewer outputs and
 * `undefined` for every other kind, letting route()/runner read it uniformly without
 * a kind switch — and guaranteeing a ship/cmr/merge output can never smuggle an
 * ignored escalate through the step path.
 */
export function escalateOf(
  output: StepOutput | undefined,
): Escalation | null | undefined {
  if (output == null) return undefined;
  if (output.kind === "coder" || output.kind === "reviewer") {
    return output.escalate;
  }
  return undefined;
}
