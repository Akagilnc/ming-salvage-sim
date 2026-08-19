import type { PendingDecision } from "./types";

export const PAUSED_DECISION_MSG = "本回合仍在等待批红，但待批决策无法校验。请重新拉取后重试。";

/** #1374：phase2 已落 decided（先写后跑）——不可再当待批弹窗，禁「可再提交」假象。 */
export function isDecisionAlreadyDecided(event: unknown): boolean {
  if (!event || typeof event !== "object") return false;
  return String((event as { status?: unknown }).status || "") === "decided";
}

export function pendingDecisionsFrom(events: unknown[]): PendingDecision[] {
  if (events.length === 0) return [];
  const validated: PendingDecision[] = [];
  for (let i = 0; i < events.length; i++) {
    const event = events[i];
    if (!isPendingDecision(event)) return [];
    if (event.idx !== i) return [];
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

export type DecisionRouteOutcome = {
  pendingDecisions: PendingDecision[] | null;
  error: string | null;
};

export function replacePendingDecisionsOnRefresh(
  _previous: PendingDecision[],
  next: PendingDecision[] | null,
): PendingDecision[] | null {
  return next;
}

export function routeIssueDecisions(events: unknown[]): DecisionRouteOutcome {
  const decisions = pendingDecisionsFrom(events);
  if (decisions.length === 0) {
    return { pendingDecisions: [], error: PAUSED_DECISION_MSG };
  }
  return { pendingDecisions: decisions, error: "" };
}

export function routeRefreshDecisions(
  phase: string | undefined,
  events: unknown[],
): DecisionRouteOutcome {
  if (phase !== "awaiting_decision") {
    return { pendingDecisions: null, error: null };
  }
  // #1374：全员 decided = phase2 在办（崩溃安全先写），不重开批红弹窗、不报损坏。
  if (events.length > 0 && events.every(isDecisionAlreadyDecided)) {
    return { pendingDecisions: null, error: null };
  }
  const decisions = pendingDecisionsFrom(events);
  if (decisions.length === 0) {
    return { pendingDecisions: [], error: PAUSED_DECISION_MSG };
  }
  return { pendingDecisions: decisions, error: "" };
}

export function routeRetryDecisions(
  phase: string | undefined,
  events: unknown[],
): DecisionRouteOutcome {
  if (phase !== "awaiting_decision") {
    return { pendingDecisions: [], error: "" };
  }
  // #1374：phase2 在办时重拉不弹「可再提交」、不清成错误条。
  if (events.length > 0 && events.every(isDecisionAlreadyDecided)) {
    return { pendingDecisions: [], error: "" };
  }
  const decisions = pendingDecisionsFrom(events);
  if (decisions.length === 0) {
    return { pendingDecisions: [], error: PAUSED_DECISION_MSG };
  }
  return { pendingDecisions: decisions, error: "" };
}
