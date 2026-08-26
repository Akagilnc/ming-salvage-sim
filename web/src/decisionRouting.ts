import type { PendingDecision } from "./types";

export const PAUSED_DECISION_MSG = "本回合仍在等待批红，但待批决策无法校验。请重新拉取后重试。";

/** #1307：settling 窗口 pending_decisions=[] 是正常中间态，不报错、不喊重拉。 */
export const SETTLING_WAIT_MSG = "";

/** #1374：phase2 已落 decided（先写后跑）——不可再当待批弹窗，禁「可再提交」假象。
 * fail-closed：须完整校验结构（同 pending）；畸形 `{status:"decided"}` 不得绕过。
 */
export function isDecisionAlreadyDecided(event: unknown): boolean {
  if (!isPendingDecision(event)) return false;
  return String((event as { status?: unknown }).status || "") === "decided";
}

/** 全员 decided（结构完整）——phase2 在办/待续的崩溃安全先写态。 */
export function isAllDecisionsDecided(events: unknown[]): boolean {
  return events.length > 0 && events.every(isDecisionAlreadyDecided);
}

/**
 * #1418 r2 / #657：需接到既有 settle-resume 续跑面
 * （重发 resolve_decisions/stream 续 phase2）。
 * - 非空 all-decided + settlement_display（同会话先写态）
 * - 或服务端 typed resume_phase2（desk 只 pending→空 + resolve_context 在）
 * 负向：快照已清（正常完成月 / 真失败退出）且无服务端信号 → 不触发。
 */
export function needsPhase2Resume(
  phase: string | undefined,
  events: unknown[],
  settlementDisplay?: boolean,
  resumePhase2Signal?: boolean,
): boolean {
  if (phase !== "awaiting_decision") return false;
  if (resumePhase2Signal) return true;
  if (!settlementDisplay) return false;
  return isAllDecisionsDecided(events);
}

export function pendingDecisionsFrom(events: unknown[]): PendingDecision[] {
  if (events.length === 0) return [];
  const validated: PendingDecision[] = [];
  for (let i = 0; i < events.length; i++) {
    const event = events[i];
    // 只做结构校验；身份靠 decision_key 提交。禁 idx===array-position 整表拒收。
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

export type DecisionRouteOutcome = {
  pendingDecisions: PendingDecision[] | null;
  error: string | null;
  /** #1418 r2：接到 settle-resume 续跑面（禁当成功空批清横幅、禁重开批红）。 */
  resumePhase2?: boolean;
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
  resumePhase2Signal?: boolean,
): DecisionRouteOutcome {
  // #1307：settling 中间态 pending=[] 正常——轮询/等待呈现，不报错不喊重拉。
  if (phase === "settling") {
    return { pendingDecisions: null, error: SETTLING_WAIT_MSG || null };
  }
  if (phase !== "awaiting_decision") {
    return { pendingDecisions: null, error: null };
  }
  // #1374/#1418 r2 / #657：phase2 在办——不重开批红；接到 settle-resume。
  if (resumePhase2Signal || isAllDecisionsDecided(events)) {
    return { pendingDecisions: null, error: null, resumePhase2: true };
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
  resumePhase2Signal?: boolean,
): DecisionRouteOutcome {
  // #1307：settling 重拉也不报错；空批红只在 awaiting_decision 才响亮。
  if (phase === "settling") {
    return { pendingDecisions: [], error: "" };
  }
  if (phase !== "awaiting_decision") {
    return { pendingDecisions: [], error: "" };
  }
  // #1418 r2 / #657：all-decided 或 typed resume 信号 → phase2 续跑 affordance。
  if (resumePhase2Signal || isAllDecisionsDecided(events)) {
    return { pendingDecisions: null, error: null, resumePhase2: true };
  }
  const decisions = pendingDecisionsFrom(events);
  if (decisions.length === 0) {
    return { pendingDecisions: [], error: PAUSED_DECISION_MSG };
  }
  return { pendingDecisions: decisions, error: "" };
}
