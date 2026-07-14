import * as sc from "@ai-hero/sandcastle";
import { z } from "zod";

/** The bounded native Sandcastle retry budget ratified by #899. */
export const RECEIPT_MAX_RETRIES = 2;

const decisionBellSchema = z.object({
  escalate: z.object({ reason: z.string(), diagnosis: z.string() }),
}).passthrough();

const coderReceiptSchema = z.object({
  committed: z.boolean(),
  commitsAdded: z.number().int().nonnegative(),
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
  successfulLegs: z.array(cmrLegSchema),
  skippedLegs: z.array(cmrSkippedLegSchema).optional(),
  claimedFixedFindingIdentityKeys: z.array(z.string()),
  priorFindingDispositions: z.array(z.unknown()),
  evidencePaths: z.array(z.string()),
};
const cmrReceiptSchema = z.union([
  z.object({
    converged: z.literal(true),
    ...cmrVerdictFields,
  }).strict(),
  z.object({
    converged: z.literal(false),
    reason: z.string().trim().min(1),
    findings: z.array(z.unknown()).optional(),
    ...cmrVerdictFields,
  }).strict(),
]);

type WorkerReceiptRole = "coder" | "reviewer" | "cmr";

/** The role contract Sandcastle validates before deciding whether to re-ask. */
export function workerReceiptSchema(role: WorkerReceiptRole): z.ZodType {
  return z.union([
    decisionBellSchema,
    role === "coder"
      ? coderReceiptSchema
      : role === "reviewer"
        ? reviewerReceiptSchema
        : cmrReceiptSchema,
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
 * topology in one seam for every runner path.
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

/**
 * Resume a worker only at the transport boundary where its final receipt could
 * not be decoded.  The caller supplies Sandcastle's typed resume; this seam
 * deliberately does not inspect the receipt's claims or schema itself.
 */
export async function resumeTypedReceiptOrFallback<T>(params: {
  readonly sessionId: string | undefined;
  readonly receiptWasUnreadable: boolean;
  readonly resume: (sessionId: string) => Promise<T>;
  readonly fallback: () => T;
  readonly worker: string;
}): Promise<T> {
  if (!params.receiptWasUnreadable || params.sessionId === undefined) {
    return params.fallback();
  }
  return await reaskReceiptOrFallback(
    () => params.resume(params.sessionId!),
    params.fallback,
    params.worker,
  );
}
