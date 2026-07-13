/**
 * Legacy domain validators retained for non-runner consumers and compatibility
 * parsing. ADR 0131 forbids runner/route from using them as fate courts: reviewer
 * routing reads only the worker-declared open count.
 */

import type {
  Escalation,
  RepairEvidence,
  StepOutput,
} from "./types.js";

/**
 * Type-only string guard (intentionally does NOT reject `""`): a Finding's
 * required string fields must be PRESENT strings per the #244 contract, but the
 * contract does not forbid empty values here. For a genuinely non-empty check
 * (used by `escalate`), see `isFilledString` below. The name is `isString`, not
 * `isNonEmptyString`, so the type-only intent is not misread (gemini R1).
 */
function isString(v: unknown): v is string {
  return typeof v === "string";
}

/** A genuinely non-empty string (rejects "" and whitespace-only). */
function isFilledString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

function isStringArray(v: unknown): v is ReadonlyArray<string> {
  return Array.isArray(v) && v.every(isString);
}

function isFilledStringArray(v: unknown): v is ReadonlyArray<string> {
  return Array.isArray(v) && v.every(isFilledString);
}

function isValidFindingRepairScope(v: unknown): boolean {
  if (v == null || typeof v !== "object" || Array.isArray(v)) return false;
  const obj = v as Record<string, unknown>;
  return (
    (obj.identityKeys === undefined || isStringArray(obj.identityKeys)) &&
    (obj.locations === undefined || isStringArray(obj.locations)) &&
    (obj.categories === undefined || isStringArray(obj.categories)) &&
    (obj.findingGroup === undefined || isString(obj.findingGroup)) &&
    (obj.reviewContext === undefined || isString(obj.reviewContext)) &&
    (obj.featureArea === undefined || isString(obj.featureArea))
  );
}

export function isValidRepairEvidence(v: unknown): v is RepairEvidence {
  if (v == null || typeof v !== "object" || Array.isArray(v)) return false;
  const obj = v as Record<string, unknown>;
  if (!isValidFindingRepairScope(obj.findingScope)) return false;
  if (
    obj.changedFiles !== undefined &&
    !isFilledStringArray(obj.changedFiles)
  ) {
    return false;
  }
  if (obj.tests !== undefined && !isFilledStringArray(obj.tests)) return false;
  if (obj.fixtures !== undefined && !isFilledStringArray(obj.fixtures)) {
    return false;
  }
  if (
    obj.sameClassBugScan !== undefined &&
    !isFilledString(obj.sameClassBugScan)
  ) {
    return false;
  }
  if (
    obj.introducedRegressionCheck !== undefined &&
    !isFilledString(obj.introducedRegressionCheck)
  ) {
    return false;
  }
  if (obj.patchSummary !== undefined && !isFilledString(obj.patchSummary)) {
    return false;
  }
  return (
    (Array.isArray(obj.changedFiles) && obj.changedFiles.length > 0) ||
    (Array.isArray(obj.tests) && obj.tests.length > 0) ||
    (Array.isArray(obj.fixtures) && obj.fixtures.length > 0)
  );
}

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
