import React from "react";
import { ApiRequestError, api, pollMindreadingUntilReady, streamChat } from "./api";
import { chatReducer } from "./mindreading";
import type { ChatIdentity, ChatMessage, ChatResponse, PendingActionFailure, Minister, ReplyRetry, ServerChatMessage, Suggestion } from "./types";

/**
 * #499 召对投递单一控制器：App 唯一消费的 hook，独占 SSE 流、历史加载、读心轮询、
 * reducer 派发。事件归属分三层，按最小必要门控（不多加 token/缓存/executor）：
 *
 * - 短暂请求态（待答文 / 流式文 / busy / 取消句柄）：归 requestToken。更新的 send 接手即
 *   旧流尾巴不得改动——只门控这四样。
 * - 历史快照（/chat 加载、回话 done 的整串投影）：归 generation + 当前大臣。send/reset/close/新
 *   load 都推进 generation，陈旧快照（更旧的 GET 迟到）据此丢弃，不抹掉新完成的轮。
 *   close 推进同一代次，使离面后迟到的非 Abort 失败不得再回调 composer 回填。
 * - 读心事件（持久、turn-identified）：只认当前大臣面板即入 reducer（不按 token/gen）。迟到的
 *   旧流读心仍按归属轮定位插入——绝不因新 send 作废 token 而永久丢失。
 * - 持久后果（草案/密令/换人/退下/loadState 等）：done 载荷到手即由 App 幂等消费（不按 token
 *   门控），不拖到 SSE end——读心可延后 end 达 120s，期间起新轮不得吞掉已完成的旧轮后果。
 * - 提交完成投影（成案等尾随落账）：SSE end 表示抽取/收夜等已 join，App 经 onEnd 再读权威
 *   durable state；不延迟 done 回话呈现。观察者离面无 end 时，重入拟诏等面经既有 loadState 接缝。
 */

export type AudienceHistoryData = {
  minister: Minister;
  history: ServerChatMessage[];
  suggestions: Suggestion[];
  can_undo_last_chat: boolean;
  pending_action_failures?: PendingActionFailure[];
  chat_turn_id?: number;
  mindreading_pending?: boolean;
  /** 本大臣本回合所有待读心轮 id（不只最新）——每轮各自轮询，随新一轮发出仍存活。 */
  pending_turn_ids?: number[];
  campaign_id: string;
  /** Persisted current open-night identity; 0 means no open audience night. */
  night_id: number;
  /** #505：崩溃遗留的中断轮 → 最后一句上给系统层重试（重新生成回话）。 */
  reply_retry?: ReplyRetry | null;
};

export type SendChatCallbacks = {
  /** 回话 done：done 载荷到手即消费持久后果 + 面板态（App 自行区分全局/面板归属）。 */
  onDone?: (data: ChatResponse) => void;
  /** 流 end：尾随写（抽取成案/收夜等）已 join，权威持久投影可重读。不按 token 门控。 */
  onEnd?: () => void;
  /** 观察者离开实时流（AbortError） */
  onLeave?: () => void;
  /** 失败（非 Abort） */
  onError?: (err: unknown) => void;
};

export function useAudienceChat(
  setBusy: (value: string) => void,
  selectedMinisterRef: React.MutableRefObject<string>,
  // 召对面板是否打开（App 传 activeModal==="chat"）。本 hook 内置**唯一 chat-exit 归属**：
  // 面板一关（任何 departure：关闭/Escape/转诏书/切模态/退菜单都令其为 false）即取消实时流
  // 观察者 + 作废重开 poll-batch。归属逻辑在 App 真实消费的 hook 里，不散落各 departure。
  chatOpen: boolean,
  /** 公共卷轴尾随写入落账后的唯一失效出口。 */
  onScrollSettled?: () => void,
) {
  const [chat, dispatchChat] = React.useReducer(chatReducer, [] as ChatMessage[]);
  const [pendingUserMessage, setPendingUserMessage] = React.useState("");
  const [pendingIdentity, setPendingIdentity] = React.useState<ChatIdentity | null>(null);
  const [failedIdentity, setFailedIdentity] = React.useState<ChatIdentity | null>(null);
  const [streamingMinisterMessage, setStreamingMinisterMessage] = React.useState("");
  const [currentCampaignId, setCurrentCampaignId] = React.useState("");
  const [currentNightId, setCurrentNightId] = React.useState<number>(0);
  // 短暂请求归属：每次 sendChat 自增。
  const requestTokenRef = React.useRef(0);
  // 全部在飞流的取消句柄：sendChat 每次登记自己的 controller、结束即摘除。close/cancel 须
  // 中止**所有**在飞流——单句柄只留最新，重叠请求会漏掉更早的 controller，旧 SSE/fetch 连接
  // 悬到服务端自闭。abortAll 统一中止并清空。
  const activeAbortsRef = React.useRef<Set<AbortController>>(new Set());
  const abortAll = React.useCallback(() => {
    for (const controller of activeAbortsRef.current) controller.abort();
    activeAbortsRef.current.clear();
  }, []);
  // 历史快照 generation：load / send / reset / close 都推进；陈旧历史响应与失败回填据此丢弃。
  const chatGenRef = React.useRef(0);
  // 读心 poll-batch 归属：一次「面板观察会话」的全部待读心轮轮询共此代次。close / reset /
  // 新接受的历史快照替换旧批（推进代次作废旧批）；**send 不推进**（同面板同待读心轮仍有效，
  // 旧轮读心不该因新一轮发出而停）。给 hook 唯一 poll-batch 归属，避免同大臣重开叠加重复轮询环。
  const pollBatchRef = React.useRef(0);

  // 唯一 chat-exit 归属 effect：面板关闭即取消流观察者 + 作废 poll-batch/generation
  // （selectedMinister 不变也停；同代次接缝让离面后的失败回调失去 freshness）。
  React.useEffect(() => {
    if (!chatOpen) {
      abortAll();
      pollBatchRef.current += 1;
      chatGenRef.current += 1;
    }
  }, [chatOpen, abortAll]);

  const resetPanel = React.useCallback(() => {
    chatGenRef.current += 1;   // 作废在飞的历史加载
    pollBatchRef.current += 1; // 作废旧 poll-batch（切人/清屏）
    dispatchChat({ type: "reset" });
    setPendingUserMessage("");
    setPendingIdentity(null);
    setFailedIdentity(null);
    setStreamingMinisterMessage("");
    setCurrentCampaignId("");
    setCurrentNightId(0);
  }, []);

  const clearPendingText = React.useCallback(() => {
    setPendingUserMessage("");
    setPendingIdentity(null);
    setStreamingMinisterMessage("");
  }, []);

  // 非流式历史投影（撤回后重投）：新一代快照，走同一 reducer history 动作（含读心保住/归位）。
  const applyHistory = React.useCallback((history: ServerChatMessage[]) => {
    chatGenRef.current += 1;
    dispatchChat({ type: "history", history });
  }, []);

  const loadHistory = React.useCallback(
    // 返回投影快照（已应用）或 null（被 generation 守卫拒收）——拒收时**不做任何面板写入**，
    // App 据 null 早退，杜绝陈旧快照的建议/可撤回/失败/临时大臣元数据回覆（#499）。
    async (minister: string): Promise<AudienceHistoryData | null> => {
      const gen = ++chatGenRef.current;
      const data = await api<AudienceHistoryData>(
        `/api/ministers/${encodeURIComponent(minister)}/chat`,
      );
      // generation + 面板守卫：更新的 load/send/reset 已发生或已切人 → 陈旧快照，拒收返 null。
      if (chatGenRef.current !== gen || selectedMinisterRef.current !== minister) return null;
      dispatchChat({ type: "history", history: data.history });
      setCurrentCampaignId(String(data.campaign_id || ""));
      setCurrentNightId(Number(data.night_id || 0));
      // 新接受的历史快照替换旧 poll-batch：推进批次代次，旧批的在飞轮询自停（去重叠加）。
      const batch = ++pollBatchRef.current;
      const batchAlive = () =>
        selectedMinisterRef.current === minister && pollBatchRef.current === batch;
      // 每一待读心轮各自轮询：寿命系于服务端终态（api 层），存活系于本 poll-batch 归属——
      // close/reset/新快照停之，send 不停之。覆盖所有待读心轮，不止最新轮。
      const pendingTurns = Array.isArray(data.pending_turn_ids) ? data.pending_turn_ids : [];
      for (const turnId of pendingTurns) {
        void pollMindreadingUntilReady(minister, turnId, {
          shouldContinue: batchAlive,
          onRecords: (records, tid) => {
            if (batchAlive()) dispatchChat({ type: "mindreading", chatTurnId: tid, records });
          },
        });
      }
      return data;
    },
    [selectedMinisterRef],
  );

  const sendChat = React.useCallback(
    async (minister: string, message: string, cb: SendChatCallbacks, intent?: "secret_order"): Promise<void> => {
      const token = ++requestTokenRef.current;
      const gen = ++chatGenRef.current;  // 作废在飞的历史加载，防陈旧快照迟到回覆本轮
      const initiatingPanelName = selectedMinisterRef.current;
      const abort = new AbortController();
      activeAbortsRef.current.add(abort);
      const ownsEphemeral = () => requestTokenRef.current === token;
      // The action target can be the scroll's current audience rather than the minister
      // used to open the modal. Guard ephemeral writes by the initiating panel only.
      const panelMatches = () => selectedMinisterRef.current === initiatingPanelName;
      const historyFresh = () => chatGenRef.current === gen && panelMatches();
      setPendingUserMessage(message);
      setPendingIdentity(null);
      setFailedIdentity(null);
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
            intent,
            onStreamReset: () => {
              // #1465 半流：重试开始替换未完成临时回话，不叠旧半句
              if (ownsEphemeral() && panelMatches()) setStreamingMinisterMessage("");
            },
            onAccepted: (identity) => {
              if (panelMatches()) {
                setCurrentCampaignId(identity.campaign_id);
                setCurrentNightId(identity.night_id);
                setPendingIdentity(identity);
              }
            },
            onDone: (doneData) => {
              // 短暂请求态按 token 回收
              if (ownsEphemeral()) {
                setPendingUserMessage("");
                setPendingIdentity(null);
                setStreamingMinisterMessage("");
                setBusy("");
              }
              // 历史快照：generation + 面板守卫（幂等 turn-identified，仍不越面板）
              if (historyFresh()) {
                dispatchChat({ type: "history", history: doneData.history });
                if (typeof doneData.night_id === "number") setCurrentNightId(doneData.night_id);
              }
              // done 已持久化本轮，立即重读公共卷轴；end 再失效一次以接回尾随落账。
              onScrollSettled?.();
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
            onHighlights: (hl) => {
              // #544：流完补挂——legacy 串挂清单；卷轴权威由 onEnd 重读带回
              if (panelMatches() && hl.highlights?.length) {
                dispatchChat({
                  type: "highlights",
                  chatTurnId: Number(hl.chat_turn_id || 0),
                  highlights: hl.highlights,
                });
              }
            },
            onEnd: () => {
              // 尾随落账后：卷轴再失效一次；提交完成缝交给 App 重读 durable（成案等）。
              onScrollSettled?.();
              cb.onEnd?.();
            },
          },
        );
      } catch (err) {
        if (!ownsEphemeral()) return;  // 旧流尾巴：绝不触碰更新请求的短暂态
        setPendingUserMessage("");
        setPendingIdentity(null);
        setStreamingMinisterMessage("");
        if (err instanceof Error && err.name === "AbortError") {
          cb.onLeave?.();
        } else if (historyFresh()) {
          // 失败回填只属于发起时仍存活的同一 composer（generation + 面板）；
          // 关闭/重开已推进 gen，旧非 Abort reject 不得污染新 session。
          if (err instanceof ApiRequestError && err.chatIdentity) setFailedIdentity(err.chatIdentity);
          cb.onError?.(err);
        }
      } finally {
        if (ownsEphemeral()) setBusy("");
        activeAbortsRef.current.delete(abort);
      }
    },
    [setBusy, selectedMinisterRef, onScrollSettled],
  );

  const cancelChat = React.useCallback(() => {
    abortAll();
  }, [abortAll]);

  return {
    chat,
    currentCampaignId,
    currentNightId,
    pendingUserMessage,
    pendingIdentity,
    failedIdentity,
    streamingMinisterMessage,
    resetPanel,
    clearPendingText,
    applyHistory,
    loadHistory,
    sendChat,
    cancelChat,
  };
}
