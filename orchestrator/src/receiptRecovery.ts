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

const cmrReceiptSchema = z.object({
  converged: z.boolean(),
}).passthrough();

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

/** Whether a recovered compatibility receipt satisfies its role contract. */
export function workerReceiptIsReadable(role: WorkerReceiptRole, receipt: unknown): boolean {
  return workerReceiptSchema(role).safeParse(receipt).success;
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
    /(?:resume\s*)?session.*(?:not found|expired|missing|unavailable)/i.test(error.message);
}
