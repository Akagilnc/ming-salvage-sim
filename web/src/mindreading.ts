import type { ChatMessage, ServerChatMessage } from "./types";

/**
 * 服务端 turn-identified 投影 → 前端 ChatMessage（#499）。
 * 前端只做字段搬运，不重排。
 */
export const projectServerHistory = (history: ServerChatMessage[]): ChatMessage[] =>
  (Array.isArray(history) ? history : []).map((m) => ({
    role: m.role,
    content: m.content,
    chatTurnId: m.chat_turn_id,
    // #544：大臣清单随投影搬运；帝侧忽略
    ...(m.role === "minister" && Array.isArray(m.highlights)
      ? { highlights: m.highlights }
      : {}),
  }));

/**
 * App 实际消费的唯一召对串 reducer（#499）：所有召对显示态转移都过它，
 * 供真实生产路径 tracer 直接驱动（无需复制 setChat 胶水）。
 * - reset：切人/清屏
 * - history：/chat 历史、回话 done、撤回——统一映射 turn-identified 投影
 */
export type ChatAction =
  | { type: "reset" }
  | { type: "history"; history: ServerChatMessage[] }
  | { type: "highlights"; chatTurnId: number; highlights: string[] };

export const chatReducer = (state: ChatMessage[], action: ChatAction): ChatMessage[] => {
  switch (action.type) {
    case "reset":
      return state.length ? [] : state;
    case "history":
      return projectServerHistory(action.history);
    case "highlights":
      return attachHighlightsByTurn(state, action.chatTurnId, action.highlights);
    default:
      return state;
  }
};

/** #544：流式补挂——按归属轮给大臣回话挂上判官清单（只标大臣）。 */
export const attachHighlightsByTurn = (
  chat: ChatMessage[],
  chatTurnId: number,
  highlights: string[],
): ChatMessage[] => {
  if (!chatTurnId || !Array.isArray(highlights) || !highlights.length) return chat;
  let changed = false;
  const next = chat.map((m) => {
    if (m.role !== "minister" || m.chatTurnId !== chatTurnId) return m;
    changed = true;
    return { ...m, highlights: [...highlights] };
  });
  return changed ? next : chat;
};
