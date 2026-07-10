import type { PendingDecision } from "./types";

export function pendingDecisionsFrom(events: unknown[]): PendingDecision[] {
  return events.filter(isPendingDecision);
}

function isPendingDecision(event: unknown): event is PendingDecision {
  if (!event || typeof event !== "object") return false;
  const candidate = event as Partial<PendingDecision>;
  return typeof candidate.idx === "number"
    && typeof candidate.title === "string"
    && typeof candidate.context === "string"
    && Array.isArray(candidate.options)
    && candidate.options.every((option) => (
      !!option
      && typeof option.label === "string"
      && typeof option.hint === "string"
    ));
}
