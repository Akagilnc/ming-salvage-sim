import React from "react";
import { forwardSteamEvents } from "./steamEvents";
import type { MindreadingRecord } from "./mindreading";
import type { ApiErrorDetail, ChatResponse } from "./types";

export class ApiRequestError extends Error {
  detail: ApiErrorDetail;

  constructor(detail: ApiErrorDetail, fallback: string) {
    const message = detail.message || fallback;
    super(detail.code ? `[${detail.code}] ${message}` : message);
    this.name = "ApiRequestError";
    this.detail = detail;
  }
}

export const normalizeApiError = (error: any, fallback: string): ApiErrorDetail => {
  const detail = error?.detail ?? error;
  if (detail && typeof detail === "object") {
    return {
      code: detail.code,
      message: detail.message || detail.detail || fallback,
      provider_message: detail.provider_message,
      status_code: detail.status_code,
      pending_action_failures: Array.isArray(detail.pending_action_failures)
        ? detail.pending_action_failures
        : undefined,
    };
  }
  return { message: String(detail || fallback) };
};

export const formatApiError = (error: any, fallback: string) => {
  const detail = error instanceof ApiRequestError ? error.detail : normalizeApiError(error, fallback);
  return detail.code ? `[${detail.code}] ${detail.message || fallback}` : detail.message || fallback;
};

export const api = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiRequestError(normalizeApiError(error, response.statusText), response.statusText);
  }
  const payload = await response.json();
  void forwardSteamEvents(payload);
  return payload;
};

export const parseSseMessage = (raw: string): { event: string; data: string } | null => {
  const lines = raw.split(/\r?\n/);
  let event = "message";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!dataLines.length) return null;
  return { event, data: dataLines.join("\n") };
};

export type StreamChatOptions = {
  signal?: AbortSignal;
  /** #499 读心就绪即浮现：回话 done 后后台旁白到达时回调（不阻塞回话展示）；
   *  mindreading 携持久记录身份 id，前端按 (chat_turn_id, id) 归位/去重 */
  onMindreading?: (payload: {
    mindreading: MindreadingRecord | null;
    chat_turn_id: number;
  }) => void;
  /** 回话 done 时立刻回调，便于清 busy / 展示回话，不等读心 */
  onDone?: (payload: ChatResponse) => void;
};

export const streamChat = async (
  ministerName: string,
  message: string,
  onDelta: (delta: string) => void,
  signalOrOptions?: AbortSignal | StreamChatOptions,
): Promise<ChatResponse> => {
  const options: StreamChatOptions =
    signalOrOptions instanceof AbortSignal || signalOrOptions === undefined
      ? { signal: signalOrOptions }
      : signalOrOptions;
  const response = await fetch(`/api/ministers/${encodeURIComponent(ministerName)}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
    signal: options.signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiRequestError(normalizeApiError(error, response.statusText), response.statusText);
  }
  if (!response.body) {
    throw new Error("浏览器不支持流式回复。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let donePayload: ChatResponse | null = null;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const messages = buffer.split("\n\n");
    buffer = messages.pop() || "";

    for (const messageBlock of messages) {
      const parsed = parseSseMessage(messageBlock);
      if (!parsed) continue;
      const payload = JSON.parse(parsed.data);
      if (parsed.event === "delta") {
        onDelta(String(payload.content || ""));
      } else if (parsed.event === "done") {
        // 回话先可见：不结束流，等 end；兼容旧服务端（仅 done 无 end）则缓存后继续
        donePayload = payload as ChatResponse;
        options.onDone?.(donePayload);
      } else if (parsed.event === "mindreading") {
        options.onMindreading?.({
          mindreading: (payload?.mindreading ?? null) as MindreadingRecord | null,
          chat_turn_id: Number(payload?.chat_turn_id || 0),
        });
      } else if (parsed.event === "end") {
        if (!donePayload) {
          throw new Error("流式回复中断，未收到完成事件。");
        }
        return donePayload;
      } else if (parsed.event === "error") {
        throw new ApiRequestError(normalizeApiError(payload, "流式回复失败。"), "流式回复失败。");
      }
    }

    if (done) break;
  }

  // 兼容：服务端只发 done 就关流时仍返回回话
  if (donePayload) return donePayload;
  throw new Error("流式回复中断，未收到完成事件。");
};

export type MindreadingSnapshot = {
  chat_turn_id: number;
  mindreading: MindreadingRecord[];
  mindreading_pending?: boolean;
};

/** 固定 expected 轮拉取：不受新一轮成为 latest 影响，旧轮读心不丢失/不错归（#499）。 */
export const fetchMindreading = (ministerName: string, chatTurnId: number) =>
  api<MindreadingSnapshot>(
    `/api/ministers/${encodeURIComponent(ministerName)}/chat/mindreading` +
      `?chat_turn_id=${encodeURIComponent(String(chatTurnId))}`,
  );

/**
 * 取消实时流或读心落库前重开时，历史 GET 可能早于后台读心落库，之后再不浮现
 * （#499 p5-mindreading-player-delivery）。此处锁定 expected 轮 `chatTurnId` 做有界
 * 轮询，就绪即把该轮记录（带持久 id）交 onRecords 浮现；`mindreading_pending===false`
 * 或已浮现即停，避免空转。去重/归位由调用方按 (chat_turn_id, id) 负责——本函数只搬运。
 */
export const pollMindreadingUntilReady = async (
  ministerName: string,
  chatTurnId: number,
  opts: {
    onRecords: (records: MindreadingRecord[], chatTurnId: number) => void;
    shouldContinue: () => boolean;
    maxAttempts?: number;
    intervalMs?: number;
    sleep?: (ms: number) => Promise<void>;
  },
): Promise<void> => {
  const maxAttempts = opts.maxAttempts ?? 20;
  const intervalMs = opts.intervalMs ?? 1500;
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (!opts.shouldContinue()) return;
    await sleep(intervalMs);
    if (!opts.shouldContinue()) return;
    let data: MindreadingSnapshot;
    try {
      data = await fetchMindreading(ministerName, chatTurnId);
    } catch {
      continue;  // 瞬断重试，不中断轮询
    }
    const rows = Array.isArray(data.mindreading) ? data.mindreading : [];
    const ready = rows.filter(
      (row) => Number(row?.id || 0) > 0 && String(row?.narration || "").trim(),
    );
    if (ready.length) {
      opts.onRecords(ready, chatTurnId);  // 固定 expected 轮归位，不读 data.chat_turn_id 的 latest
      return;
    }
    if (data.mindreading_pending === false) return;  // 本轮不会再有读心
  }
};
