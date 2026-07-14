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

const reviewerReceiptSchema = z.object({
  findings: z.array(z.unknown()),
}).passthrough();

const cmrLegSchema = z.string().trim().min(1);
const cmrSkippedLegSchema = z.object({
  slug: cmrLegSchema,
  reason: z.string().trim().min(1),
}).strict();
const cmrVerdictFields = {
  // ADR 0131: the reviewer, not the runner, declares the open finding count.
  // Keep that declaration in the typed receipt so Sandcastle re-asks the same
  // reviewer when an otherwise valid verdict omits it.
  findingsCount: z.number().int().nonnegative(),
  successfulLegs: z.array(cmrLegSchema),
  skippedLegs: z.array(cmrSkippedLegSchema).optional(),
  claimedFixedFindingIdentityKeys: z.array(z.string()),
  priorFindingDispositions: z.array(z.unknown()),
  evidencePaths: z.array(z.string()),
  // Finding families are reviewer cargo consumed by the next fixer; their
  // tolerant parser owns their shape, not Sandcastle's receipt boundary.
  findingFamilies: z.unknown().optional(),
};
const cmrReceiptSchema = z.union([
  z.object({
    converged: z.literal(true),
    ...cmrVerdictFields,
  }).passthrough(),
  z.object({
    converged: z.literal(false),
    reason: z.string().trim().min(1),
    findings: z.array(z.unknown()).optional(),
    ...cmrVerdictFields,
  }).passthrough(),
]);

/**
 * Signal-level schema for seats that may press a decision gate while ordinary
 * cargo stays opaque: any object without `escalate` passes; present `escalate`
 * must be a well-formed bell. Missing tags still cannot use Output.object
 * (Sandcastle treats absence as SOE) — multi-iter coder/ship therefore keep
 * Output.object undefined per #899 opaque-cargo AC.
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

/** Typed traffic-signal seats only (#899): reviewer open-count + CMR open-count. */
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

/**
 * @deprecated Prefer {@link reaskReceiptOrThrow}. Kept as a thin alias that
 * ignores `fallback` so call-site renames can land without leaving a success
 * fallback on the typed-signal path.
 */
export async function reaskReceiptOrFallback<T>(
  reask: () => Promise<T>,
  _fallback: () => T,
  worker: string,
): Promise<T> {
  return reaskReceiptOrThrow(reask, worker);
}
