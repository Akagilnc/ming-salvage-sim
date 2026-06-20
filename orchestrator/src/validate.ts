/**
 * Step-output validation — the SINGLE source of truth for the agent↔runner
 * seam contract (PRD #244 contract layer). Both the runner (before routing) and
 * route() (defense-in-depth at the seam) use these guards, so the rules can
 * never drift between two hand-written copies.
 *
 * Why this is load-bearing (integ-cmr base r2, finding A):
 *   route()'s S4 compares `severity`/`action` by EXACT string. A malformed
 *   finding element — `severity:"critical "` (trailing space), `action:"FIX_NOW"`
 *   (uppercase), or a missing field — would silently fail every `=== 'critical'`
 *   / `=== 'fix_now'` test → needsFix=false → push → a REAL P0 shipped past the
 *   mandatory fix gate. So a finding array whose ELEMENTS are not all valid must
 *   never be treated as legitimate findings: the whole step → S8(error).
 */

import type {
  CoderOutput,
  Finding,
  ReviewerOutput,
  StepOutput,
} from "./types.js";

/** Exact severity enum (no whitespace / case drift tolerated). */
const SEVERITIES: ReadonlySet<string> = new Set([
  "critical",
  "high",
  "medium",
  "low",
  "clarity",
]);

/** Exact action enum. */
const ACTIONS: ReadonlySet<string> = new Set(["fix_now", "defer"]);

/** Required string fields on a Finding (PRD #244 contract). */
const FINDING_STRING_FIELDS = [
  "category",
  "claim_quote",
  "location",
  "suggested_fix",
] as const;

function isNonEmptyString(v: unknown): v is string {
  return typeof v === "string";
}

/**
 * A single reviewer finding is valid iff:
 *   - `severity` is EXACTLY one of the five enum values (no trailing space, no
 *     case drift — the route() severity comparison is exact-string),
 *   - `action` is EXACTLY `'fix_now'` or `'defer'`,
 *   - every required string field is present and a string.
 *
 * Anything else is a contract violation: the route() severity/action test would
 * silently miss it and could push a real P0 past the fix gate.
 */
export function isValidFinding(f: unknown): f is Finding {
  if (f == null || typeof f !== "object") return false;
  const obj = f as Record<string, unknown>;
  if (typeof obj.severity !== "string" || !SEVERITIES.has(obj.severity)) {
    return false;
  }
  if (typeof obj.action !== "string" || !ACTIONS.has(obj.action)) {
    return false;
  }
  for (const field of FINDING_STRING_FIELDS) {
    if (!isNonEmptyString(obj[field])) return false;
  }
  return true;
}

/**
 * A coder step output is valid iff it is `{kind:'coder', committed:boolean,
 * commitsAdded:number}` AND `commitsAdded` is a non-negative integer CONSISTENT
 * with `committed`:
 *   - committed === true  ⇒ commitsAdded >= 1
 *   - committed === false ⇒ commitsAdded === 0
 *
 * (integ-cmr base r2, finding B: the old guard only checked `committed` was a
 * boolean, so `{committed:true, commitsAdded:0}` or a missing/garbage
 * commitsAdded slipped through. v0.1 validates the field contract; deriving the
 * real count from git is #256.)
 */
export function isValidCoderOutput(o: StepOutput | undefined): o is CoderOutput {
  if (o == null || typeof o !== "object") return false;
  if (o.kind !== "coder") return false;
  const c = o as CoderOutput;
  if (typeof c.committed !== "boolean") return false;
  if (
    typeof c.commitsAdded !== "number" ||
    !Number.isInteger(c.commitsAdded) ||
    c.commitsAdded < 0
  ) {
    return false;
  }
  // Consistency: committed iff at least one commit was added.
  return c.committed ? c.commitsAdded >= 1 : c.commitsAdded === 0;
}

/**
 * A reviewer step output is valid iff it is `{kind:'reviewer', findings:Array}`
 * AND every finding ELEMENT is valid (finding A). A non-array `findings` or any
 * malformed element makes the whole output invalid → S8(error); route() must
 * never coerce it into a push.
 */
export function isValidReviewerOutput(
  o: StepOutput | undefined,
): o is ReviewerOutput {
  if (o == null || typeof o !== "object") return false;
  if (o.kind !== "reviewer") return false;
  const r = o as ReviewerOutput;
  if (!Array.isArray(r.findings)) return false;
  return r.findings.every(isValidFinding);
}

/**
 * Validate an agent-step output against the step's expected role. Used by the
 * runner before route() and (defense-in-depth) inside route() itself.
 */
export function isValidStepOutput(
  output: StepOutput | undefined,
  expectedKind: "coder" | "reviewer",
): boolean {
  return expectedKind === "coder"
    ? isValidCoderOutput(output)
    : isValidReviewerOutput(output);
}
