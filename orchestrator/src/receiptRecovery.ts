import * as sc from "@ai-hero/sandcastle";
import { z } from "zod";

/** The bounded native Sandcastle retry budget ratified by #899. */
export const RECEIPT_MAX_RETRIES = 2;

/**
 * Always-emitted typed decision-gate tag for optional gate seats (#899).
 * Bound to {@link decisionGateOutput} so ordinary cargo tags (`coder` / `ship` /
 * `merger` / review-loop roles) stay outside Output.object — missing or
 * malformed cargo never forces structured-output re-ask.
 */
export const DECISION_GATE_TAG = "decision";

/** Strict decision-gate payload: reason/diagnosis must be non-empty strings. */
const decisionEscalateSchema = z.object({
  reason: z.string().trim().min(1),
  diagnosis: z.string().trim().min(1),
});

/**
 * Worker-pressed decision gate. Malformed bells fail Sandcastle schema
 * validation so the same session re-asks (#899); exhaust rethrows for #598.
 */
const decisionBellSchema = z.object({
  escalate: decisionEscalateSchema,
}).passthrough();

/**
 * When `escalate` is present on an open-count receipt it must be a well-formed
 * bell — otherwise a legal findingsCount would mask a bad gate via union
 * short-circuit (#899 S6 finding 1).
 */
function rejectMalformedEscalateAlongsideCount(
  value: unknown,
  ctx: z.RefinementCtx,
): void {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return;
  }
  if (!Object.prototype.hasOwnProperty.call(value, "escalate")) {
    return;
  }
  const parsed = decisionEscalateSchema.safeParse(
    (value as { escalate: unknown }).escalate,
  );
  if (!parsed.success) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "malformed decision gate alongside open-count",
      path: ["escalate"],
    });
  }
}

/**
 * Shared open-count receipt for reviewer and CMR seats (#899). Both roles use
 * the same findingsCount + optional decision-gate contract until their typed
 * boundaries genuinely diverge — introduce role dispatch only then.
 */
const openCountReceiptSchema = z.object({
  findingsCount: z.number().int().nonnegative(),
}).passthrough().superRefine(rejectMalformedEscalateAlongsideCount);

/**
 * Signal-level schema for the always-emitted {@link DECISION_GATE_TAG} tag.
 * Present `escalate` must be a well-formed bell; any object without `escalate`
 * (typically `{}`) is a no-gate signal. Ordinary cargo never lands in this tag.
 *
 * Non-object / null values fail so Sandcastle re-asks the signal itself rather
 * than silently accepting a missing protocol emission as "no gate".
 */
export const decisionGateSignalSchema: z.ZodType = z.union([
  decisionBellSchema,
  z.custom(
    (value) => {
      if (value === null || typeof value !== "object" || Array.isArray(value)) {
        return false;
      }
      return !Object.prototype.hasOwnProperty.call(value, "escalate");
    },
    { message: "decision signal must be an object without a malformed escalate" },
  ),
]);

/**
 * Shared open-count + optional decision-gate schema for reviewer/CMR typed seats.
 * No role parameter: both seats share one contract until they genuinely diverge.
 */
export function workerReceiptSchema(): z.ZodType {
  return z.union([
    decisionBellSchema,
    openCountReceiptSchema,
  ]);
}

/** One typed receipt definition for every worker path. */
export function workerReceiptOutput(
  tag: string,
  schema: z.ZodType = z.unknown(),
): sc.OutputDefinition {
  return sc.Output.object({ tag, schema, maxRetries: RECEIPT_MAX_RETRIES });
}

/**
 * Optional decision-gate Output.object on the dedicated {@link DECISION_GATE_TAG}.
 * Cargo tags stay untyped (ADR 0131 / #899).
 */
export function decisionGateOutput(): sc.OutputDefinition {
  return workerReceiptOutput(DECISION_GATE_TAG, decisionGateSignalSchema);
}

/**
 * Shared well-formed decision-bell probe for production parsers (#899 seam).
 * Returns the bell only when reason and diagnosis are both non-empty after trim;
 * present-but-malformed escalate is {@link isMalformedDecisionGate}.
 */
export function wellFormedDecisionBell(
  receipt: unknown,
): { reason: string; diagnosis: string } | undefined {
  if (receipt === null || typeof receipt !== "object" || Array.isArray(receipt)) {
    return undefined;
  }
  if (!Object.prototype.hasOwnProperty.call(receipt, "escalate")) {
    return undefined;
  }
  const parsed = decisionEscalateSchema.safeParse(
    (receipt as { escalate: unknown }).escalate,
  );
  if (!parsed.success) return undefined;
  return parsed.data;
}

/**
 * True when the payload carries an `escalate` key that fails the strict
 * decision-gate contract (empty reason/diagnosis, wrong shape, etc.).
 */
export function isMalformedDecisionGate(receipt: unknown): boolean {
  if (receipt === null || typeof receipt !== "object" || Array.isArray(receipt)) {
    return false;
  }
  if (!Object.prototype.hasOwnProperty.call(receipt, "escalate")) {
    return false;
  }
  return decisionEscalateSchema.safeParse(
    (receipt as { escalate: unknown }).escalate,
  ).success === false;
}

/**
 * Classified decision-gate signal after malformed-gate validation (#899 seam).
 * Callers map `bell` into role-specific escalate outcomes and treat `none` as
 * "no gate — continue with cargo".
 */
export type DecisionGateClassification =
  | { readonly kind: "none" }
  | { readonly kind: "bell"; readonly reason: string; readonly diagnosis: string };

/**
 * Central malformed-gate validation + bell classification for production parsers.
 * Present-but-malformed `escalate` throws so the Action exits non-zero for #598;
 * well-formed bells and no-gate payloads are returned as a discriminated result.
 */
export function classifyDecisionGate(
  receipt: unknown,
  label: string,
): DecisionGateClassification {
  if (isMalformedDecisionGate(receipt)) {
    throw new Error(
      `${label}: malformed decision gate (empty or non-string reason/diagnosis); failing Action for mechanical redispatch`,
    );
  }
  const bell = wellFormedDecisionBell(receipt);
  if (bell !== undefined) {
    return { kind: "bell", reason: bell.reason, diagnosis: bell.diagnosis };
  }
  return { kind: "none" };
}

/** A native receipt retry that must fail the Action for #598 mechanical redispatch. */
export function isReceiptRecoveryFailure(error: unknown): boolean {
  if (error instanceof sc.StructuredOutputError) return true;
  return error instanceof Error &&
    /(?:(?:resume\s*)?session.*(?:not found|expired|missing|unavailable)|does not support resumeSession|output\.maxRetries requires an agent provider that supports session resumption)/i.test(error.message);
}

/**
 * Log a typed-receipt recovery exhaust and rethrow so the Action exits non-zero
 * for #598 redispatch (#899). Accepts the already-caught error directly — this
 * is not a re-ask loop (Sandcastle owns same-session maxRetries).
 */
export function logAndRethrowReceiptFailure(error: unknown, worker: string): never {
  if (isReceiptRecoveryFailure(error)) {
    console.warn(
      `[orchestrator] ${worker} receipt recovery exhausted; propagating for mechanical redispatch`,
    );
  }
  throw error;
}
