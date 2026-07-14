import * as sc from "@ai-hero/sandcastle";
import { z } from "zod";

/** The bounded native Sandcastle retry budget ratified by #899. */
export const RECEIPT_MAX_RETRIES = 2;

/** One typed receipt definition for every worker path. */
export function workerReceiptOutput(tag: string): sc.OutputDefinition {
  return sc.Output.object({ tag, schema: z.unknown(), maxRetries: RECEIPT_MAX_RETRIES });
}

/** A native receipt retry that must fall back to the caller's existing topology. */
export function isReceiptRecoveryFailure(error: unknown): boolean {
  if (error instanceof sc.StructuredOutputError) return true;
  return error instanceof Error &&
    /(?:resume\s*)?session.*(?:not found|expired|missing|unavailable)/i.test(error.message);
}
