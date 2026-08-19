import type { PendingDecision } from "./types";

export const PAUSED_DECISION_MSG = "本回合仍在等待批红，但待批决策无法校验。请重新拉取后重试。";

/** #1307：settling 窗口 pending_decisions=[] 是正常中间态，不报错、不喊重拉。 */
export const SETTLING_WAIT_MSG = "";

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
  // #1307：settling 中间态 pending=[] 正常——轮询/等待呈现，不报错不喊重拉。
  if (phase === "settling") {
    return { pendingDecisions: null, error: SETTLING_WAIT_MSG || null };
  }
  if (phase !== "awaiting_decision") {
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
  // #1307：settling 重拉也不报错；空批红只在 awaiting_decision 才响亮。
  if (phase === "settling") {
    return { pendingDecisions: [], error: "" };
  }
  if (phase !== "awaiting_decision") {
    return { pendingDecisions: [], error: "" };
  }
  const decisions = pendingDecisionsFrom(events);
  if (decisions.length === 0) {
    return { pendingDecisions: [], error: PAUSED_DECISION_MSG };
  }
  return { pendingDecisions: decisions, error: "" };
}
