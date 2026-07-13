/** The only content probe allowed on a worker receipt: a worker-pressed doorbell. */
export interface WorkerDecisionBell {
  readonly reason: string;
  readonly diagnosis: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Unknown keys and unusable sibling cargo are deliberately ignored. */
export function probeWorkerDecisionBell(
  receipt: unknown,
): WorkerDecisionBell | undefined {
  if (!isRecord(receipt) || !isRecord(receipt.escalate)) return undefined;
  const { reason, diagnosis } = receipt.escalate;
  return {
    reason: typeof reason === "string" ? reason : "",
    diagnosis: typeof diagnosis === "string" ? diagnosis : "",
  };
}
