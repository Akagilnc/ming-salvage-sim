import * as sc from "@ai-hero/sandcastle";
import { z } from "zod";

/** The bounded native Sandcastle retry budget ratified by #899. */
export const RECEIPT_MAX_RETRIES = 2;

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
 * Standalone reviewer open-count (#899 / ADR 0131). Typed boundary only checks
 * the explicit self-reported count + decision gate; findings rows, dispositions,
 * and other prose stay tolerant cargo (passthrough).
 */
const reviewerReceiptSchema = z.object({
  findingsCount: z.number().int().nonnegative(),
}).passthrough().superRefine(rejectMalformedEscalateAlongsideCount);

/**
 * CMR open-count only at the typed boundary. Legs, evidence, dispositions,
 * findings rows, and converged prose are cargo for the next fixer — not SOE
 * re-ask material (#899).
 */
const cmrReceiptSchema = z.object({
  findingsCount: z.number().int().nonnegative(),
}).passthrough().superRefine(rejectMalformedEscalateAlongsideCount);

/**
 * Signal-level schema for seats that may press a decision gate while ordinary
 * cargo stays opaque: any object without `escalate` passes; present `escalate`
 * must be a well-formed bell. Single-iteration seats (#899) attach this via
 * Output.object so malformed bells get same-session native re-ask without
 * schema-validating committed/commitsAdded/PR cargo.
 *
 * Non-object / null values also pass so optional-tag consumers that land empty
 * cargo do not force a cargo-shape re-ask (ADR 0131 opaque cargo).
 */
export const decisionGateSignalSchema: z.ZodType = z.union([
  decisionBellSchema,
  z.custom(
    (value) => {
      if (value === null || typeof value !== "object" || Array.isArray(value)) {
        return true;
      }
      return !Object.prototype.hasOwnProperty.call(value, "escalate");
    },
    { message: "opaque cargo must not carry a malformed decision gate" },
  ),
]);

/** Typed traffic-signal seats only (#899): reviewer/CMR open-count + decision. */
type WorkerReceiptRole = "reviewer" | "cmr";

/** The role contract Sandcastle validates before deciding whether to re-ask. */
export function workerReceiptSchema(role: WorkerReceiptRole): z.ZodType {
  return z.union([
    decisionBellSchema,
    role === "reviewer" ? reviewerReceiptSchema : cmrReceiptSchema,
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

/** A native receipt retry that must fail the Action for #598 mechanical redispatch. */
export function isReceiptRecoveryFailure(error: unknown): boolean {
  if (error instanceof sc.StructuredOutputError) return true;
  return error instanceof Error &&
    /(?:(?:resume\s*)?session.*(?:not found|expired|missing|unavailable)|does not support resumeSession|output\.maxRetries requires an agent provider that supports session resumption)/i.test(error.message);
}

/**
 * Run a typed-output seat. StructuredOutputError and other recovery failures
 * propagate so the Action exits non-zero and #598 re-dispatches at the same
 * fixed position (#899). Never convert exhaust into a success fallback that
 * would feed empty/cargo signals to the fixer or advance as 0.
 */
export async function reaskReceiptOrThrow<T>(
  reask: () => Promise<T>,
  worker: string,
): Promise<T> {
  try {
    return await reask();
  } catch (error) {
    if (isReceiptRecoveryFailure(error)) {
      console.warn(
        `[orchestrator] ${worker} receipt recovery exhausted; propagating for mechanical redispatch`,
      );
    }
    throw error;
  }
}
