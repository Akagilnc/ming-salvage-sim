import React from "react";
import { audienceStreamPath } from "./audienceScene";
import { forwardSteamEvents } from "./steamEvents";
import type { ApiErrorDetail, ChatResponse } from "./types";

export class ApiRequestError extends Error {
  detail: ApiErrorDetail;
  chatIdentity?: { campaign_id: string; night_id: number; chat_turn_id: number };

  constructor(
    detail: ApiErrorDetail,
    fallback: string,
    chatIdentity?: { campaign_id: string; night_id: number; chat_turn_id: number },
  ) {
    const message = detail.message || fallback;
    super(message);
    this.name = "ApiRequestError";
    this.detail = detail;
    this.chatIdentity = chatIdentity;
  }
}

export const normalizeApiError = (error: any, fallback: string): ApiErrorDetail => {
  const detail = error?.detail ?? error;
  if (detail && typeof detail === "object") {
    const turnRaw = detail.turn;
    const turnNum = typeof turnRaw === "number" ? turnRaw : Number(turnRaw);
    return {
      code: detail.code,
      message: detail.message || detail.detail || fallback,
      provider_message: detail.provider_message,
      status_code: detail.status_code,
      turn: Number.isFinite(turnNum) ? turnNum : undefined,
      pending_action_failures: Array.isArray(detail.pending_action_failures)
        ? detail.pending_action_failures
        : undefined,
    };
  }
  return { message: String(detail || fallback) };
};

export const api = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    const normalized = normalizeApiError(error, response.statusText);
    if (normalized.status_code == null) normalized.status_code = response.status;
    throw new ApiRequestError(normalized, response.statusText);
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
  intent?: "secret_order";
  /** #544：流完补挂高亮清单（done 之后、end 之前） */
  onHighlights?: (payload: {
    highlights: string[];
    chat_turn_id: number;
    message_id: number;
  }) => void;
  /** 玩家问话已持久化并开夜；先于模型生成/失败返回。 */
  onAccepted?: (payload: { campaign_id: string; night_id: number; chat_turn_id: number }) => void;
  /** 回话 done 时立刻回调，便于清 busy / 展示回话，不等读心 */
  onDone?: (payload: ChatResponse) => void;
  /** 服务端 end 表示回话尾随写入均已 join、公共卷轴可安全重读。 */
  onEnd?: () => void;
  /** #1465：transport 重试开始——清空本轮未完成的临时回话呈现（delta.replace）。 */
  onStreamReset?: () => void;
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
  const url = audienceStreamPath();
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, ...(options.intent ? { intent: options.intent } : {}) }),
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
      if (parsed.event === "accepted") {
        options.onAccepted?.({
          campaign_id: String(payload.campaign_id || ""),
          night_id: Number(payload.night_id || 0),
          chat_turn_id: Number(payload.chat_turn_id || 0),
        });
      } else if (parsed.event === "delta") {
        // replace：复用既有 delta 事件；先重置临时正文，再按需接后续 content
        if (payload.replace) {
          options.onStreamReset?.();
        }
        const content = String(payload.content || "");
        if (content) {
          onDelta(content);
        }
      } else if (parsed.event === "done") {
        // 回话先可见：不结束流，等 end；兼容旧服务端（仅 done 无 end）则缓存后继续
        donePayload = payload as ChatResponse;
        options.onDone?.(donePayload);
      } else if (parsed.event === "highlights") {
        const raw = Array.isArray(payload?.highlights) ? payload.highlights : [];
        options.onHighlights?.({
          highlights: raw.map((item: unknown) => String(item || "")).filter(Boolean),
          chat_turn_id: Number(payload?.chat_turn_id || 0),
          message_id: Number(payload?.message_id || 0),
        });
      } else if (parsed.event === "end") {
        if (!donePayload) {
          throw new Error("流式回复中断，未收到完成事件。");
        }
        options.onEnd?.();
        return donePayload;
      } else if (parsed.event === "error") {
        const identity = {
          campaign_id: String(payload.campaign_id || ""),
          night_id: Number(payload.night_id || 0),
          chat_turn_id: Number(payload.chat_turn_id || 0),
        };
        throw new ApiRequestError(
          normalizeApiError(payload, "流式回复失败。"),
          "流式回复失败。",
          identity.night_id && identity.chat_turn_id ? identity : undefined,
        );
      }
    }

    if (done) break;
  }

  // 兼容：服务端只发 done 就关流时仍返回回话
  if (donePayload) return donePayload;
  throw new Error("流式回复中断，未收到完成事件。");
};
