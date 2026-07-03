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
  Escalation,
  Finding,
  FindingDispositionEvidence,
  PriorFindingDisposition,
  RepairEvidence,
  ReviewerOutput,
  StepOutput,
} from "./types.js";
import { hasAcceptedSuppressionAuthority } from "./acceptedSuppression.js";

/** Exact severity enum (no whitespace / case drift tolerated). */
const SEVERITIES: ReadonlySet<string> = new Set([
  "critical",
  "high",
  "medium",
  "low",
  "clarity",
]);

/** Exact action enum. */
const ACTIONS: ReadonlySet<string> = new Set([
  "fix_now",
  "defer",
  "wont_fix",
  "rejected",
]);
const PRIOR_FINDING_DISPOSITIONS: ReadonlySet<string> = new Set([
  "still-active",
  "verified-closed",
  "unable-to-assess",
  "accepted_suppressed",
]);

/** Required string fields on a Finding (PRD #244 contract). */
const FINDING_STRING_FIELDS = [
  "category",
  "claim_quote",
  "location",
  "suggested_fix",
] as const;

const DISPOSITION_KINDS: ReadonlySet<string> = new Set([
  "same_module",
  "cross_module",
  "spec_conflict",
  "infra_failure",
  "owning_issue_still_red",
  "accepted_suppressed",
]);

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

function optionalString(v: unknown): boolean {
  return v === undefined || isString(v);
}

function acceptedSuppressionAuthorityFromRecord(
  obj: Record<string, unknown>,
): boolean {
  return hasAcceptedSuppressionAuthority({
    source: typeof obj.source === "string" ? obj.source : undefined,
    scope: typeof obj.scope === "string" ? obj.scope : undefined,
    reason: typeof obj.reason === "string" ? obj.reason : undefined,
    boundedReopen:
      typeof obj.boundedReopen === "string" ? obj.boundedReopen : undefined,
  });
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

function hasConcreteRepairScope(scope: RepairEvidence["findingScope"]): boolean {
  return (
    (scope.identityKeys?.length ?? 0) > 0 ||
    (scope.locations?.length ?? 0) > 0 ||
    (scope.categories?.length ?? 0) > 0 ||
    (scope.findingGroup?.trim().length ?? 0) > 0 ||
    (scope.reviewContext?.trim().length ?? 0) > 0 ||
    (scope.featureArea?.trim().length ?? 0) > 0
  );
}

export function isCompleteRepairEvidence(
  evidence: RepairEvidence | undefined,
): evidence is RepairEvidence {
  return (
    evidence !== undefined &&
    isValidRepairEvidence(evidence) &&
    hasConcreteRepairScope(evidence.findingScope) &&
    (evidence.tests?.length ?? 0) > 0 &&
    isFilledString(evidence.sameClassBugScan) &&
    isFilledString(evidence.introducedRegressionCheck)
  );
}

function isValidDispositionEvidence(
  d: unknown,
): d is FindingDispositionEvidence {
  if (d == null || typeof d !== "object") return false;
  const obj = d as Record<string, unknown>;
  if (typeof obj.kind !== "string" || !DISPOSITION_KINDS.has(obj.kind)) {
    return false;
  }
  if (!isFilledString(obj.reason)) return false;
  if (
    !optionalString(obj.targetModule) ||
    !optionalString(obj.owningIssue) ||
    !optionalString(obj.missingSurface) ||
    !optionalString(obj.nextStep) ||
    !optionalString(obj.source) ||
    !optionalString(obj.scope) ||
    !optionalString(obj.findingIdentity) ||
    !optionalString(obj.boundedReopen)
  ) {
    return false;
  }
  switch (obj.kind) {
    case "cross_module":
      return isFilledString(obj.targetModule);
    case "owning_issue_still_red":
      return (
        isFilledString(obj.owningIssue) &&
        isFilledString(obj.missingSurface) &&
        isFilledString(obj.nextStep)
      );
    case "accepted_suppressed":
      return acceptedSuppressionAuthorityFromRecord(obj);
    case "spec_conflict":
    case "infra_failure":
      return isFilledString(obj.source);
    case "same_module":
      return true;
  }
  return false;
}

/**
 * Validate the `escalate` field on an agent-step output.
 *
 * `escalate` is part of the step-output schema contract (PRD #244 contract
 * layer: `{ escalate?: { reason, diagnosis } }`). It is the GLOBAL stop edge —
 * route() takes it before every other edge. So a NON-NULL escalate is a real
 * human-escalation stop signal whose `reason`/`diagnosis` the caller reads
 * verbatim; a garbage escalate (empty `{}`, wrong types, blank strings) must NOT
 * be accepted as a legitimate stop signal — that is the malformed-output
 * coercion hole (integ-cmr base r1, F1). route() must judge such a step
 * S8(error), not S8(escalate).
 *
 * Rules:
 *   - absent / undefined / null → NO escalate (valid: the step simply did not
 *     escalate; real backends emit `escalate: null` for the unset field).
 *   - present (non-null) → MUST be `{ reason: non-empty string,
 *     diagnosis: non-empty string }`; anything else is invalid.
 */
export function isValidEscalation(e: unknown): e is Escalation | null | undefined {
  if (e == null) return true; // absent / undefined / null = no escalate.
  if (typeof e !== "object") return false;
  const obj = e as Record<string, unknown>;
  return isFilledString(obj.reason) && isFilledString(obj.diagnosis);
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
  if (
    (obj.action === "wont_fix" || obj.action === "rejected") &&
    !(
      isFilledString(obj.disposition_reason) ||
      (isValidDispositionEvidence(obj.disposition) &&
        obj.disposition.kind === "accepted_suppressed" &&
        isFilledString(obj.disposition.reason))
    )
  ) {
    return false;
  }
  if (
    obj.disposition_reason !== undefined &&
    !isString(obj.disposition_reason)
  ) {
    return false;
  }
  if (
    obj.disposition !== undefined &&
    !isValidDispositionEvidence(obj.disposition)
  ) {
    return false;
  }
  if (
    (obj.severity === "critical" || obj.severity === "high") &&
    obj.action !== "fix_now"
  ) {
    return false;
  }
  if (obj.action === "defer") {
    if (!isValidDispositionEvidence(obj.disposition)) return false;
    if (obj.disposition.kind === "accepted_suppressed") return false;
  }
  if (obj.action === "wont_fix" || obj.action === "rejected") {
    if (!isValidDispositionEvidence(obj.disposition)) return false;
    if (obj.disposition.kind !== "accepted_suppressed") return false;
  }
  for (const field of FINDING_STRING_FIELDS) {
    if (!isString(obj[field])) return false;
  }
  return true;
}

export function isValidPriorFindingDisposition(
  d: unknown,
): d is PriorFindingDisposition {
  if (d == null || typeof d !== "object") return false;
  const obj = d as Record<string, unknown>;
  if (!isFilledString(obj.identityKey)) return false;
  if (
    typeof obj.status !== "string" ||
    !PRIOR_FINDING_DISPOSITIONS.has(obj.status)
  ) {
    return false;
  }
  if (obj.reason !== undefined && !isString(obj.reason)) return false;
  if (obj.status === "accepted_suppressed") {
    return acceptedSuppressionAuthorityFromRecord(obj);
  }
  return true;
}

/**
 * The SINGLE blocking-finding predicate — the one source of truth for "this
 * finding forces an S5 coder_fix". Both route()'s S4 routing decision (does the
 * review send code to S5 or push?) AND the S5 delivery seam (which findings does
 * selectFixNowFindings hand the coder?) MUST consult THIS, so the routing side
 * and the delivery side can never drift.
 *
 * integ-cmr 256 confirm r1 (high, #244 铁律): a finding is blocking iff it is a
 * P0/P1 (`severity` critical or high) OR a reviewer-judged `fix_now`. Severity
 * trumps action — a reviewer CANNOT defer a P0/P1 ("P0/P1 必修不许私自降级",
 * route-s4.test.ts "P0 still trumps even when all deferred"). The earlier
 * delivery seam filtered on `action === 'fix_now'` ALONE, so a
 * `{severity:'critical'|'high', action:'defer'}` finding routed to S5 (severity
 * branch) yet reached the coder as an EMPTY set — silently re-deferring a P0/P1
 * on the coder side. Sharing this predicate closes that gap.
 */
export function isBlockingFinding(f: Finding): boolean {
  return (
    f.severity === "critical" || f.severity === "high" || f.action === "fix_now"
  );
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
  // F1: a non-null escalate must be a well-shaped Escalation (reason+diagnosis,
  // both non-empty strings). A garbage escalate is a contract violation even if
  // the happy-path fields are present.
  if (!isValidEscalation(c.escalate)) return false;
  if (typeof c.committed !== "boolean") return false;
  if (
    typeof c.commitsAdded !== "number" ||
    !Number.isInteger(c.commitsAdded) ||
    c.commitsAdded < 0
  ) {
    return false;
  }
  if (
    c.repairEvidence !== undefined &&
    !isValidRepairEvidence(c.repairEvidence)
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
  const obj = o as unknown as Record<string, unknown>;
  if (obj.kind !== "reviewer") return false;
  // F1: same escalate-shape contract as the coder output.
  if (!isValidEscalation(obj.escalate)) return false;
  if (!Array.isArray(obj.findings)) return false;
  if (!obj.findings.every(isValidFinding)) return false;
  if (obj.priorFindingDispositions === undefined) return true;
  return (
    Array.isArray(obj.priorFindingDispositions) &&
    obj.priorFindingDispositions.every(isValidPriorFindingDisposition)
  );
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
