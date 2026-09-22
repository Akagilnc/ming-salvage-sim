import type { ChatMessage, ServerChatMessage } from "./types";

/**
 * 服务端 turn-identified 投影 → 前端 ChatMessage（#499）。读心递话（attendant）
 * 已由服务端按轮归位并携 (chat_turn_id, record_id) 稳定身份；前端只做字段搬运，
 * 不重排、不按 narration 文本判断。setChat 用它替换整串也不会抹掉读心递话。
 */
export const projectServerHistory = (history: ServerChatMessage[]): ChatMessage[] =>
  (Array.isArray(history) ? history : []).map((m) =>
    m.role === "attendant"
      ? {
          role: "attendant" as const,
          content: m.content,
          chatTurnId: m.chat_turn_id,
          recordId: m.record_id,
        }
      : {
          role: m.role,
          content: m.content,
          chatTurnId: m.chat_turn_id,
          // #544：大臣清单随投影搬运；帝侧忽略
          ...(m.role === "minister" && Array.isArray(m.highlights)
            ? { highlights: m.highlights }
            : {}),
        },
  );

/**
 * App 实际消费的唯一召对串 reducer（#499）：所有召对显示态转移都过它，
 * 供真实生产路径 tracer 直接驱动（无需复制 setChat 胶水）。
 * - reset：切人/清屏
 * - history：/chat 历史、回话 done、撤回——统一映射 turn-identified 投影（含既往读心）
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
