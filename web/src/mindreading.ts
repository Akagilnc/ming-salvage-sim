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

/** 后端读心记录：`id` 为持久主键（mindreading_records.id），narration 为自由文本正文。 */
export type MindreadingRecord = { id?: number; narration?: string };

/**
 * 把某一轮（chatTurnId）的读心记录**按归属轮定位插入**聊天串（#499）。
 * 稳定身份 = (chat_turn_id, record_id)；narration 是自由文本，不作身份、不按正文去重。
 * - 插在该轮大臣回话及其既有递话之后（即该轮最后一条消息之后），不再追加到串尾——
 *   done2 先于迟到的 mind1 时，mind1 仍落在其轮 1 大臣回话之后，而非轮 2 之后；
 * - 已在串中的 (chatTurnId, recordId) 不重复浮现（SSE/历史/轮询三路交叠去重）；
 * - 不同记录（不同 id）即使 narration 相同也各自浮现（不按正文去重）；
 * - 归属轮尚未在视图中（其回话未加载）则不臆测位置、不浮现——后续历史/投影会带入。
 *
 * 去重与定位均直接从当前聊天串（唯一真源）派生，不另建身份表/缓存。
 */
export const insertMindreadingByTurn = (
  chat: ChatMessage[],
  chatTurnId: number,
  records: MindreadingRecord[],
): ChatMessage[] => {
  let next = chat;
  for (const record of records) {
    const content = String(record?.narration || "").trim();
    const recordId = Number(record?.id || 0);
    if (!content || recordId <= 0) continue;  // 无正文或无持久身份的记录不投递
    const already = next.some(
      (m) => m.role === "attendant" && m.chatTurnId === chatTurnId && m.recordId === recordId,
    );
    if (already) continue;
    // 归属轮的最后一条消息（大臣回话或该轮既有递话）之后即插入点
    let insertAfter = -1;
    for (let i = 0; i < next.length; i += 1) {
      if (next[i].chatTurnId === chatTurnId) insertAfter = i;
    }
    if (insertAfter < 0) continue;  // 归属轮不在视图 → 不追加串尾（拆除 tail-append）
    const message: ChatMessage = { role: "attendant", content, chatTurnId, recordId };
    next = [...next.slice(0, insertAfter + 1), message, ...next.slice(insertAfter + 1)];
  }
  return next;
};

/**
 * App 实际消费的唯一召对串 reducer（#499）：所有召对显示态转移都过它，
 * 供真实生产路径 tracer 直接驱动（无需复制 setChat 胶水）。
 * - reset：切人/清屏
 * - history：/chat 历史、回话 done、撤回——统一映射 turn-identified 投影（含既往读心）
 * - mindreading：实时 SSE / 固定轮轮询增量——按归属轮定位插入、按 (turn,id) 去重
 */
export type ChatAction =
  | { type: "reset" }
  | { type: "history"; history: ServerChatMessage[] }
  | { type: "mindreading"; chatTurnId: number; records: MindreadingRecord[] }
  | { type: "highlights"; chatTurnId: number; highlights: string[] };

export const chatReducer = (state: ChatMessage[], action: ChatAction): ChatMessage[] => {
  switch (action.type) {
    case "reset":
      return state.length ? [] : state;
    case "history":
      return reconcileHistory(state, projectServerHistory(action.history));
    case "mindreading":
      return insertMindreadingByTurn(state, action.chatTurnId, action.records);
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

/**
 * 新历史投影替换整串时，保住「已浮现但新投影尚未含」的读心递话（#499）——
 * done1→mind1→陈旧 done2 的 done2 投影可能早于 mind1 落库、缺 a1；若整串替换会抹掉
 * a1。凡其归属轮仍在新投影中的已浮现递话，按归属轮重新定位补回；归属轮已消失
 * （撤回/切人）的则随之丢弃。定位/去重复用 insertMindreadingByTurn，不另建缓存。
 */
const reconcileHistory = (prev: ChatMessage[], projected: ChatMessage[]): ChatMessage[] => {
  const turnsInView = new Set(
    projected
      .map((m) => m.chatTurnId)
      .filter((t): t is number => typeof t === "number" && t > 0),
  );
  let result = projected;
  for (const m of prev) {
    if (
      m.role !== "attendant" ||
      typeof m.chatTurnId !== "number" ||
      typeof m.recordId !== "number" ||
      !turnsInView.has(m.chatTurnId)
    ) {
      continue;
    }
    result = insertMindreadingByTurn(result, m.chatTurnId, [{ id: m.recordId, narration: m.content }]);
  }
  return result;
};
