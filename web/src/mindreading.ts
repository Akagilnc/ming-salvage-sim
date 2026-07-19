import type { ChatMessage } from "./types";

/** 后端读心记录：`id` 为持久主键（mindreading_records.id），narration 为自由文本正文。 */
export type MindreadingRecord = { id?: number; narration?: string };

/**
 * 稳定递话身份（#499）= (chat_turn_id, record_id)。narration 是自由文本，不作身份：
 * 不同轮合法生成相同递话须都显示，故绝不按正文去重（拆除按 narration 全局去重）。
 */
export const attendantKey = (chatTurnId: number, recordId: number): string =>
  `${chatTurnId}:${recordId}`;

/**
 * 把某一轮（chatTurnId）的读心记录并入聊天串：
 * - 已在串中的 (chatTurnId, recordId) 不重复浮现（SSE/历史/轮询三路交叠去重）；
 * - 不同记录（不同 id）即使 narration 相同也各自浮现；
 * - 归位以记录携带的 chatTurnId 为准，不按「最新轮」臆测。
 *
 * 去重集直接从当前聊天串（唯一真源）派生，不另建身份表/缓存。
 */
export const mergeMindreadingRecords = (
  chat: ChatMessage[],
  chatTurnId: number,
  records: MindreadingRecord[],
): ChatMessage[] => {
  const seen = new Set<string>();
  for (const message of chat) {
    if (
      message.role === "attendant" &&
      typeof message.chatTurnId === "number" &&
      typeof message.recordId === "number"
    ) {
      seen.add(attendantKey(message.chatTurnId, message.recordId));
    }
  }
  const additions: ChatMessage[] = [];
  for (const record of records) {
    const content = String(record?.narration || "").trim();
    const recordId = Number(record?.id || 0);
    if (!content || recordId <= 0) continue;  // 无正文或无持久身份的记录不投递
    const key = attendantKey(chatTurnId, recordId);
    if (seen.has(key)) continue;
    seen.add(key);
    additions.push({ role: "attendant", content, chatTurnId, recordId });
  }
  return additions.length ? [...chat, ...additions] : chat;
};
