import { classifyDecisionGate } from "./receiptRecovery.js";

/** The only content probe allowed on a worker receipt: a worker-pressed doorbell. */
export interface WorkerDecisionBell {
  readonly reason: string;
  readonly diagnosis: string;
}

/**
 * Shared decision-bell presence probe (#899).
 *
 * Delegates to {@link classifyDecisionGate}: absent → `undefined`; well-formed
 * bell → reason/diagnosis; present-but-malformed throws so production never soft-
 * accepts empty/non-string escalate fields.
 */
export function probeWorkerDecisionBell(
  receipt: unknown,
): WorkerDecisionBell | undefined {
  const gate = classifyDecisionGate(receipt, "worker-receipt");
  if (gate.kind === "none") return undefined;
  return { reason: gate.reason, diagnosis: gate.diagnosis };
}
