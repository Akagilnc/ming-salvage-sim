import React from "react";
import { api, pollMindreadingUntilReady, streamChat } from "./api";
import { chatReducer } from "./mindreading";
import type { ChatMessage, ChatResponse, PendingActionFailure, Minister, ServerChatMessage, Suggestion } from "./types";

/**
 * #499 召对投递单一控制器：App 唯一消费的 hook，独占 SSE 流、历史加载、读心轮询、
 * reducer 派发。事件归属分三层，按最小必要门控（不多加 token/缓存/executor）：
 *
 * - 短暂请求态（待答文 / 流式文 / busy / 取消句柄）：归 requestToken。更新的 send 接手即
 *   旧流尾巴不得改动——只门控这四样。
 * - 历史快照（/chat 加载、回话 done 的整串投影）：归 generation + 当前大臣。send/reset/新
 *   load 都推进 generation，陈旧快照（更旧的 GET 迟到）据此丢弃，不抹掉新完成的轮。
 * - 读心事件（持久、turn-identified）：只认当前大臣面板即入 reducer（不按 token/gen）。迟到的
 *   旧流读心仍按归属轮定位插入——绝不因新 send 作废 token 而永久丢失。
 * - 持久后果（草案/密令/换人/退下/loadState 等）：done 载荷到手即由 App 幂等消费（不按 token
 *   门控），不拖到 SSE end——读心可延后 end 达 120s，期间起新轮不得吞掉已完成的旧轮后果。
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
  /** 回话 done：done 载荷到手即消费持久后果 + 面板态（App 自行区分全局/面板归属）。 */
  onDone?: (data: ChatResponse) => void;
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
  // 短暂请求归属：每次 sendChat 自增。
  const requestTokenRef = React.useRef(0);
  const abortRef = React.useRef<AbortController | null>(null);
  // 历史快照 generation：load / send / reset 都推进；陈旧历史响应据此丢弃（含在飞轮询）。
  const chatGenRef = React.useRef(0);

  const resetPanel = React.useCallback(() => {
    chatGenRef.current += 1;  // 作废在飞的历史加载/轮询
    dispatchChat({ type: "reset" });
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
  }, []);

  const clearPendingText = React.useCallback(() => {
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
  }, []);

  // 非流式历史投影（撤回后重投）：新一代快照，走同一 reducer history 动作（含读心保住/归位）。
  const applyHistory = React.useCallback((history: ServerChatMessage[]) => {
    chatGenRef.current += 1;
    dispatchChat({ type: "history", history });
  }, []);

  const loadHistory = React.useCallback(
    async (minister: string): Promise<AudienceHistoryData> => {
      const gen = ++chatGenRef.current;
      const data = await api<AudienceHistoryData>(
        `/api/ministers/${encodeURIComponent(minister)}/chat`,
      );
      // generation 守卫：更新的 load/send/reset 已发生 → 本次为陈旧快照，丢弃不覆盖新完成的轮。
      const fresh = () => chatGenRef.current === gen && selectedMinisterRef.current === minister;
      if (!fresh()) return data;
      dispatchChat({ type: "history", history: data.history });
      const expectedTurnId = data.chat_turn_id || 0;
      if (data.mindreading_pending && expectedTurnId > 0) {
        void pollMindreadingUntilReady(minister, expectedTurnId, {
          shouldContinue: fresh,
          onRecords: (records, turnId) => {
            if (fresh()) dispatchChat({ type: "mindreading", chatTurnId: turnId, records });
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
      const gen = ++chatGenRef.current;  // 作废在飞的历史加载，防陈旧快照迟到回覆本轮
      const abort = new AbortController();
      abortRef.current = abort;
      const ownsEphemeral = () => requestTokenRef.current === token;
      const panelMatches = () => selectedMinisterRef.current === minister;
      const historyFresh = () => chatGenRef.current === gen && panelMatches();
      setPendingUserMessage(message);
      setStreamingMinisterMessage("");
      setBusy("大臣思索中");
      try {
        await streamChat(
          minister,
          message,
          (delta) => {
            if (ownsEphemeral() && panelMatches()) setStreamingMinisterMessage((current) => current + delta);
          },
          {
            signal: abort.signal,
            onDone: (doneData) => {
              // 短暂请求态按 token 回收
              if (ownsEphemeral()) {
                setPendingUserMessage("");
                setStreamingMinisterMessage("");
                setBusy("");
              }
              // 历史快照：generation + 面板守卫（幂等 turn-identified，仍不越面板）
              if (historyFresh()) dispatchChat({ type: "history", history: doneData.history });
              // 持久后果：done 到手即消费，不按 token 门控、不拖到 end（防 120s 读心期间被新轮吞掉）
              cb.onDone?.(doneData);
            },
            onMindreading: (mind) => {
              // 持久 turn-identified 事件：仅认当前面板即入 reducer（不按 token/gen；迟到旧流读心仍归其轮）
              if (panelMatches() && mind.mindreading) {
                dispatchChat({
                  type: "mindreading",
                  chatTurnId: Number(mind.chat_turn_id || 0),
                  records: [mind.mindreading],
                });
              }
            },
          },
        );
      } catch (err) {
        if (!ownsEphemeral()) return;  // 旧流尾巴：绝不触碰更新请求的短暂态
        setPendingUserMessage("");
        setStreamingMinisterMessage("");
        if (err instanceof Error && err.name === "AbortError") cb.onLeave?.();
        else cb.onError?.(err);
      } finally {
        if (ownsEphemeral()) setBusy("");
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
