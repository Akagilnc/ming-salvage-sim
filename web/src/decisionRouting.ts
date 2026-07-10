import type { PendingDecision } from "./types";

export function pendingDecisionsFrom(events: unknown[]): PendingDecision[] {
  if (events.length === 0) return [];
  const validated: PendingDecision[] = [];
  for (const event of events) {
    if (!isPendingDecision(event)) return [];
    validated.push(event);
  }
  return validated;
}

function isPendingDecision(event: unknown): event is PendingDecision {
  if (!event || typeof event !== "object") return false;
  const candidate = event as Partial<PendingDecision>;
  return typeof candidate.idx === "number"
    && typeof candidate.title === "string"
    && typeof candidate.context === "string"
    && Array.isArray(candidate.options)
    && candidate.options.length > 0
    && candidate.options.every((option) => (
      !!option
      && typeof option.label === "string"
      && typeof option.hint === "string"
    ));
}
