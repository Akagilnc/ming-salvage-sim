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

/**
 * Run the one-iteration typed receipt resume only when the original transport
 * could not decode a final receipt.  Both ordinary and family workers share
 * this executor; their sandbox, agent, and prompt remain caller parameters.
 */
export async function resumeTypedReceiptRun<T>(params: {
  readonly result: T;
  readonly receiptWasUnreadable: boolean;
  readonly sessionId: string | undefined;
  readonly resume: (sessionId: string) => Promise<T>;
  readonly worker: string;
}): Promise<T> {
  return await resumeTypedReceiptOrFallback({
    receiptWasUnreadable: params.receiptWasUnreadable,
    sessionId: params.sessionId,
    resume: params.resume,
    fallback: () => params.result,
    worker: params.worker,
  });
}
