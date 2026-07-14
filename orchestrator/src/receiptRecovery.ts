import * as sc from "@ai-hero/sandcastle";
import { z } from "zod";

/** The bounded native Sandcastle retry budget ratified by #899. */
export const RECEIPT_MAX_RETRIES = 2;

const decisionBellSchema = z.object({
  // The runner's decision-bell probe owns the payload validation.  A bell must
  // never be rejected by typed receipt validation merely because its cargo is
  // malformed: that would turn a human-stop signal into a retryable receipt.
  escalate: z.unknown(),
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

/** A native receipt retry that must fall back to the caller's existing topology. */
export function isReceiptRecoveryFailure(error: unknown): boolean {
  if (error instanceof sc.StructuredOutputError) return true;
  return error instanceof Error &&
    /(?:(?:resume\s*)?session.*(?:not found|expired|missing|unavailable)|does not support resumeSession|output\.maxRetries requires an agent provider that supports session resumption)/i.test(error.message);
}

/**
 * Keep native receipt re-ask failure mapping and the pre-existing fallback
 * topology in one seam for every typed traffic-signal path (reviewer / CMR).
 * Coder cargo never uses this seam (#899 Out of Scope).
 */
export async function reaskReceiptOrFallback<T>(
  reask: () => Promise<T>,
  fallback: () => T,
  worker: string,
): Promise<T> {
  try {
    return await reask();
  } catch (error) {
    if (!isReceiptRecoveryFailure(error)) throw error;
    console.warn(`[orchestrator] ${worker} receipt recovery exhausted; using existing fallback`);
    return fallback();
  }
}
