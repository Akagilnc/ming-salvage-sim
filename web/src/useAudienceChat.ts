import React from "react";
import { api, pollMindreadingUntilReady, streamChat } from "./api";
import { chatReducer } from "./mindreading";
import type { ChatMessage, ChatResponse, PendingActionFailure, Minister, ServerChatMessage, Suggestion } from "./types";

/**
 * #499 召对投递单一控制器：App 唯一消费的 hook，独占 SSE 流、历史加载、读心轮询、
 * 请求归属（token）与 reducer 派发。所有召对显示态写入都过它并按请求归属门控——
 * 旧流尾巴（post-await / finally）绝不改动更新请求的待答文/流式文/取消句柄/busy。
 * App 只经回调补全外围态（建议/失败/草案/密令/换人），真实 tracer 直接驱动本 hook。
 */

export type AudienceHistoryData = {
  minister: Minister;
  history: ServerChatMessage[];
  suggestions: Suggestion[];
  can_undo_last_chat: boolean;
  pending_action_failures?: PendingActionFailure[];
  chat_turn_id?: number;
  mindreading_pending?: boolean;
};

export type SendChatCallbacks = {
  /** 回话 done（当前请求归属时）：外围面板态（建议 / 可撤回） */
  onDone?: (data: ChatResponse) => void;
  /** 流式收尾（仍归属当前请求时）：外围全局态（草案/密令/换人/通知/loadState） */
  onComplete?: (data: ChatResponse) => void | Promise<void>;
  /** 观察者离开实时流（AbortError） */
  onLeave?: () => void;
  /** 失败（非 Abort） */
  onError?: (err: unknown) => void;
};

export function useAudienceChat(
  setBusy: (value: string) => void,
  selectedMinisterRef: React.MutableRefObject<string>,
) {
  const [chat, dispatchChat] = React.useReducer(chatReducer, [] as ChatMessage[]);
  const [pendingUserMessage, setPendingUserMessage] = React.useState("");
  const [streamingMinisterMessage, setStreamingMinisterMessage] = React.useState("");
  // 请求归属 token：每次 sendChat 自增；旧流尾巴据此识别自己已非当前请求。
  const requestTokenRef = React.useRef(0);
  const abortRef = React.useRef<AbortController | null>(null);
  // 读心轮询 token：每次重开/切人自增，作废旧轮询。
  const pollTokenRef = React.useRef(0);

  const resetPanel = React.useCallback(() => {
    dispatchChat({ type: "reset" });
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
  }, []);

  const clearPendingText = React.useCallback(() => {
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
  }, []);

  // 非流式历史投影（撤回后重投）：走同一 reducer history 动作（含读心保住/归位）。
  const applyHistory = React.useCallback((history: ServerChatMessage[]) => {
    dispatchChat({ type: "history", history });
  }, []);

  const loadHistory = React.useCallback(
    async (minister: string): Promise<AudienceHistoryData> => {
      pollTokenRef.current += 1;
      const pollToken = pollTokenRef.current;
      const data = await api<AudienceHistoryData>(
        `/api/ministers/${encodeURIComponent(minister)}/chat`,
      );
      if (selectedMinisterRef.current !== minister) return data;
      dispatchChat({ type: "history", history: data.history });
      const expectedTurnId = data.chat_turn_id || 0;
      if (data.mindreading_pending && expectedTurnId > 0) {
        void pollMindreadingUntilReady(minister, expectedTurnId, {
          shouldContinue: () =>
            selectedMinisterRef.current === minister && pollTokenRef.current === pollToken,
          onRecords: (records, turnId) => {
            if (selectedMinisterRef.current === minister && pollTokenRef.current === pollToken) {
              dispatchChat({ type: "mindreading", chatTurnId: turnId, records });
            }
          },
        });
      }
      return data;
    },
    [selectedMinisterRef],
  );

  const sendChat = React.useCallback(
    async (minister: string, message: string, cb: SendChatCallbacks): Promise<void> => {
      const token = ++requestTokenRef.current;
      const abort = new AbortController();
      abortRef.current = abort;
      // 请求归属：无更新请求接手（token 未变）。面板归属另加当前大臣未切换。
      const ownsRequest = () => requestTokenRef.current === token;
      const ownsPanel = () => ownsRequest() && selectedMinisterRef.current === minister;
      setPendingUserMessage(message);
      setStreamingMinisterMessage("");
      setBusy("大臣思索中");
      try {
        const data = await streamChat(
          minister,
          message,
          (delta) => {
            if (ownsPanel()) setStreamingMinisterMessage((current) => current + delta);
          },
          {
            signal: abort.signal,
            onDone: (doneData) => {
              if (!ownsPanel()) return;
              setPendingUserMessage("");
              setStreamingMinisterMessage("");
              dispatchChat({ type: "history", history: doneData.history });
              setBusy("");
              cb.onDone?.(doneData);
            },
            onMindreading: (mind) => {
              if (!ownsPanel() || !mind.mindreading) return;
              dispatchChat({
                type: "mindreading",
                chatTurnId: Number(mind.chat_turn_id || 0),
                records: [mind.mindreading],
              });
            },
          },
        );
        if (ownsRequest()) await cb.onComplete?.(data);
      } catch (err) {
        if (!ownsRequest()) return;  // 旧流尾巴：绝不触碰更新请求的态
        setPendingUserMessage("");
        setStreamingMinisterMessage("");
        if (err instanceof Error && err.name === "AbortError") cb.onLeave?.();
        else cb.onError?.(err);
      } finally {
        // busy / 取消句柄按请求归属回收：更新请求已接手则不动其 busy。
        if (ownsRequest()) setBusy("");
        if (abortRef.current === abort) abortRef.current = null;
      }
    },
    [setBusy, selectedMinisterRef],
  );

  const cancelChat = React.useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return {
    chat,
    pendingUserMessage,
    streamingMinisterMessage,
    resetPanel,
    clearPendingText,
    applyHistory,
    loadHistory,
    sendChat,
    cancelChat,
  };
}
