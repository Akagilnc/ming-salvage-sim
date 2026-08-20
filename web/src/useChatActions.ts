import React from "react";
import { api } from "./api";
import { retryAudienceStoryExtraction } from "./extractionRetry";
import { mergePendingActionFailures, refreshRetriedPendingActionFailures } from "./chatFailures";
import type { AudienceHistoryData, SendChatCallbacks } from "./useAudienceChat";
import type {
  ChatIdentity,
  ChatResponse,
  ChatUndoResponse,
  ExtractionPendingStatus,
  GameState,
  Minister,
  ModalName,
  PendingActionFailure,
  ReplyRetry,
  SecretOrder,
  ServerChatMessage,
  Suggestion,
} from "./types";

type RefreshDurableProjection = (options?: {
  secretOrders?: boolean;
  onSecretOrders?: (orders: SecretOrder[]) => void;
  autoOpen?: { afterMs: number; when: (orders: SecretOrder[]) => boolean; open: () => void };
}) => Promise<GameState | null>;

// 召对动作群：召对面板的全部外围态（建议/提示/失败/恢复模式/输入框）与 busy 动作
// （开召对/发问/撤回/重试/失败恢复）。SSE 流、历史投影、读心轮询的归属仍在
// useAudienceChat（#499 单一控制器）——本 hook 只经其回调补全面板外围写入，
// 面板写入一律按 selectedMinisterRef 当前大臣门控（陈旧快照绝不回覆新面板）。
export function useChatActions({
  state,
  setState,
  busy,
  setBusy,
  setError,
  activeModal,
  setActiveModal,
  selectedMinister,
  setSelectedMinister,
  selectedMinisterRef,
  suppressNextReportRef,
  setSecretOrders,
  setUndoneChatIdentity,
  loadState,
  refreshDurableProjection,
  resetPanel,
  clearPendingText,
  applyHistory,
  loadHistoryProjection,
  runAudienceTurn,
  invalidateAudienceScroll,
  currentNightId,
}: {
  state: GameState | null;
  setState: React.Dispatch<React.SetStateAction<GameState | null>>;
  busy: string;
  setBusy: (busy: string) => void;
  setError: (error: string) => void;
  activeModal: ModalName;
  setActiveModal: (modal: ModalName) => void;
  selectedMinister: string;
  setSelectedMinister: (name: string) => void;
  selectedMinisterRef: React.MutableRefObject<string>;
  suppressNextReportRef: React.MutableRefObject<boolean>;
  setSecretOrders: (orders: SecretOrder[]) => void;
  setUndoneChatIdentity: React.Dispatch<React.SetStateAction<ChatIdentity | null>>;
  loadState: () => Promise<GameState | null>;
  refreshDurableProjection: RefreshDurableProjection;
  resetPanel: () => void;
  clearPendingText: () => void;
  applyHistory: (history: ServerChatMessage[]) => void;
  loadHistoryProjection: (minister: string) => Promise<AudienceHistoryData | null>;
  runAudienceTurn: (minister: string, message: string, cb: SendChatCallbacks) => Promise<void>;
  invalidateAudienceScroll: () => void;
  currentNightId: number;
}) {
  const [suggestions, setSuggestions] = React.useState<Suggestion[]>([]);
  const [chatNotice, setChatNotice] = React.useState("");
  const [chatFailures, setChatFailures] = React.useState<PendingActionFailure[]>([]);
  const [replyRetry, setReplyRetry] = React.useState<ReplyRetry | null>(null);
  const [extractionPendingCount, setExtractionPendingCount] = React.useState(0);
  const [canUndoLastChat, setCanUndoLastChat] = React.useState(false);
  const [composerHint, setComposerHint] = React.useState("");
  const [input, setInput] = React.useState("");
  const [failureRecoveryMode, setFailureRecoveryMode] = React.useState(false);
  const [temporaryActiveMinister, setTemporaryActiveMinister] = React.useState<Minister | null>(null);

  // 仅用花名册查 temporaryActiveMinister；挂 ref 避免 durable setState 整表刷新
  // 重造 loadMinisterChat → 触发 selectedMinister effect → resetPanel 清掉召对面板。
  const rosterRef = React.useRef<Minister[]>([]);
  React.useEffect(() => {
    rosterRef.current = [
      ...(state?.ministers || []),
      ...(state?.consorts || []),
    ];
  }, [state?.ministers, state?.consorts]);

  const loadMinisterChat = React.useCallback(async (ministerName: string, options?: { mergeFailures?: boolean }) => {
    // #499：历史投影 + 每一待读心轮的轮询由 hook 独占派发。返回 null=被 generation 守卫拒收
    // 的陈旧快照 → App 一并跳过全部面板外围写入（建议/可撤回/失败/临时大臣），不回覆新完成的轮。
    const data = await loadHistoryProjection(ministerName);
    if (!data || selectedMinisterRef.current !== ministerName) return;
    const allKnown = rosterRef.current;
    setTemporaryActiveMinister(allKnown.some((m) => m.name === data.minister.name) ? null : data.minister);
    setSuggestions(data.suggestions);
    setCanUndoLastChat(!!data.can_undo_last_chat);
    // #505：崩溃遗留的中断轮 → 系统层重试入口。
    setReplyRetry(data.reply_retry ?? null);
    if (options?.mergeFailures) {
      const responseFailures = data.pending_action_failures || [];
      setChatFailures((items) => mergePendingActionFailures(items, responseFailures));
    } else {
      setChatFailures(data.pending_action_failures || []);
    }
  }, [loadHistoryProjection, selectedMinisterRef]);

  const refreshExtractionPending = React.useCallback(async () => {
    // #501：本开夜待补叙事抽取——显眼提示取数；失败静默（不挡召对）。
    // #1353：真欠账 count>0 露补写 CTA；不再读 closing+zero 自愈 hint。
    try {
      const data = await api<ExtractionPendingStatus>("/api/audience/extraction/pending");
      setExtractionPendingCount(Number(data?.count || 0));
    } catch {
      /* 取数失败不锁面板 */
    }
  }, []);

  // 召对/拟诏台打开时拉待补状态（#1312 颁诏 409 后拟诏台 CTA 同缝），低频刷新可自愈。
  React.useEffect(() => {
    if (activeModal !== "chat" && activeModal !== "edict") return;
    void refreshExtractionPending();
    const id = window.setInterval(() => {
      void refreshExtractionPending();
    }, 8000);
    return () => window.clearInterval(id);
  }, [activeModal, refreshExtractionPending, selectedMinister]);

  React.useEffect(() => {
    if (!selectedMinister) {
      resetPanel();
      setSuggestions([]);
      setChatNotice("");
      if (!failureRecoveryMode) {
        setChatFailures([]);
      }
      setCanUndoLastChat(false);
      setComposerHint("");
      return;
    }
    resetPanel();
    setSuggestions([]);
    if (!failureRecoveryMode) {
      setChatFailures([]);
    }
    setCanUndoLastChat(false);
    setComposerHint("");
    loadMinisterChat(selectedMinister, failureRecoveryMode ? { mergeFailures: true } : undefined)
      .catch((err) => setError(err.message));
  }, [selectedMinister, loadMinisterChat, failureRecoveryMode]);

  const activeMinister = state && selectedMinister
    ? [...state.ministers, ...(state.consorts || [])].find((m) => m.name === selectedMinister) || temporaryActiveMinister
    : null;
  const activeChatFailures = activeMinister
    ? (failureRecoveryMode
      ? chatFailures
      : chatFailures.filter((failure) => !failure.minister_name || failure.minister_name === activeMinister.name))
    : [];

  const surfacePendingActionFailures = async (failures: PendingActionFailure[] = []) => {
    if (!failures.length) return false;
    setFailureRecoveryMode(true);
    setChatFailures((items) => mergePendingActionFailures(items, failures));
    const targetName = failures.find((failure) => failure.minister_name)?.minister_name || "";
    suppressNextReportRef.current = true;
    const initialMinister = selectedMinisterRef.current;
    try {
      await loadState();
      if (selectedMinisterRef.current !== initialMinister) return false;
      selectedMinisterRef.current = targetName;
      setSelectedMinister(targetName);
      setActiveModal("chat");
      setChatNotice("");
      clearPendingText();
    } finally {
      setBusy("");
    }
    return true;
  };

  const sendChat = async (targetMinisterName: string, text = input) => {
    if (busy) return;
    const message = text.trim();
    if (!message) {
      setComposerHint("请先问话或点一个奏对题目");
      return;
    }

    const fromComposer = text === input;
    // #526 / ADR 0047：退朝钮与手输口令同一收夜管线（chat stream）；
    // 词表真源在后端 COURT_BREAK_COMMANDS，前端不复制、不旁路 advanceWithoutEdict。
    setError("");
    setComposerHint("");
    setChatNotice("");
    // 新一轮发出即清中断重试条（本轮 supersedes 崩溃遗留的系统重试入口）。
    setReplyRetry(null);
    if (fromComposer) {
      setInput("");
    }
    // 面板归属与卷轴当前奏对者是两种身份：前者只用于判断玩家是否已离开发起面板。
    const initiatingPanelName = selectedMinisterRef.current;
    // 流式/请求归属/派发由 hook 独占；App 只在 done 到手即幂等消费持久后果 + 面板态。
    await runAudienceTurn(targetMinisterName, message, {
      // 回话 done：done 载荷即含全部持久后果，立即消费——不拖到 SSE end（读心可延后 end 达
      // 120s），不按请求 token 门控（后果持久）。全局态无条件落；面板态按当前大臣归属落。
      onDone: (data) => {
        // 单调即时字段直接落 done 载荷（各 done 递新，无竞争）：指令 / pending_count。
        setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count ?? current.pending_count } : current));
        // 重取型刷新（state + 密令列表）经唯一协调器：撤回/相邻轮等任一新刷新都会作废本次旧响应。
        void refreshDurableProjection({ secretOrders: true });
        // 面板态：仅当前大臣面板未切走才落。
        if (selectedMinisterRef.current !== initiatingPanelName) return;
        setSuggestions(data.suggestions);
        setCanUndoLastChat(!!data.can_undo_last_chat);
        const responseFailures = data.pending_action_failures || [];
        // 成功的密令与拟旨由各自持久投影自然显现；系统层只承载失败/重试/恢复。
        setChatFailures((items) => mergePendingActionFailures(items, responseFailures));
        if (data.next_minister && !responseFailures.length) {
          // 换人：设 selectedMinister 即触发 selected-minister effect 加载新面板（不再显式重复加载）。
          resetPanel();
          setSuggestions([]);
          setCanUndoLastChat(false);
          setChatFailures([]);
          setReplyRetry(null);
          setSelectedMinister(data.next_minister);
          setActiveModal("chat");
        }
        // 正常回话完成后刷新待补抽取状态（可能有新的失败待补）。
        void refreshExtractionPending();
        if (data.court_action === "dismiss") {
          clearPendingText();
        }
      },
      // 观察者离开实时流：召对在后台续跑，重开经历史重入。
      onLeave: () => {
        setChatNotice("已离开实时回话；大臣会继续回奏，稍后重开可见。");
        setError("");
      },
      onError: (err) => {
        if (fromComposer) {
          setInput(message);
        }
        setError(err instanceof Error ? err.message : String(err));
      },
    });
  };

  const openChat = (minister: Minister) => {
    if (minister.status && minister.status !== "active") {
      setError(`${minister.name}已${minister.status_label}${minister.status_reason ? "（" + minister.status_reason + "）" : ""}，无法召见。`);
      return;
    }
    const isConsort = (state?.consorts || []).some((consort) => consort.name === minister.name);
    // 开夜中切大臣：写进夜卷轴「宣X」，不换面板归属。
    if (activeModal === "chat" && currentNightId > 0 && !isConsort && activeMinister) {
      void sendChat(activeMinister.name, `宣${minister.name}`);
      return;
    }
    const switchingMinister = selectedMinister !== minister.name;
    if (switchingMinister) {
      resetPanel();
      setSuggestions([]);
      setTemporaryActiveMinister(null);
      setCanUndoLastChat(false);
    }
    setSelectedMinister(minister.name);
    setActiveModal("chat");
    setError("");
    setFailureRecoveryMode(false);
    setComposerHint("");
    setChatNotice("");
    setChatFailures([]);
    setCanUndoLastChat(false);
    clearPendingText();
    // 切换大臣时 selected-minister effect 会加载；只有重开同一大臣（effect 不触发）才显式加载，
    // 免得一次切换发两条同大臣 GET（#499 陈旧快照回覆源头之一）。
    if (!switchingMinister) {
      loadMinisterChat(minister.name).catch((err) => setError(err.message));
    }
  };

  const undoLastChat = async (targetMinisterName: string) => {
    if (busy || !canUndoLastChat) return;
    const ok = window.confirm("将撤回最近一轮召对及其政务影响，是否继续？");
    if (!ok) return;
    const initiatingPanelName = selectedMinisterRef.current;
    setBusy("撤回召对");
    setError("");
    setChatNotice("");
    setComposerHint("");
    clearPendingText();
    try {
      const data = await api<ChatUndoResponse>(`/api/ministers/${encodeURIComponent(targetMinisterName)}/chat/undo`, {
        method: "POST",
      });
      // Undo's GLOBAL effects (secret orders / directives / full state) apply
      // regardless — the undo mutated game state, not just the panel. But the
      // minister-PANEL writes (history / suggestions / undo-availability / notice)
      // are gated on the staleness guard (#325, broad-scope): openChat does NOT
      // block on `busy`, so the player can switch ministers during the undo POST;
      // writing A's post-undo history into B's open panel is the same bleed.
      setSecretOrders(data.secret_orders || []);
      setUndoneChatIdentity({
        campaign_id: data.campaign_id,
        night_id: data.night_id,
        chat_turn_id: data.undone_chat_turn_id,
      });
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count } : current));
      await loadState();
      // Read the ref FRESH at the panel-write point (the minister could switch
      // during the awaits above), mirroring sendChat's post-await check.
      if (selectedMinisterRef.current === initiatingPanelName) {
        // #499：撤回后剩余轮的读心递话仍随 turn-identified 投影归位。
        applyHistory(data.history);
        setSuggestions(data.suggestions);
        setCanUndoLastChat(!!data.can_undo_last_chat);
        setChatFailures(data.pending_action_failures || []);
        setChatNotice("已撤回最近一轮召对。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const retryInterruptedReply = async (targetMinisterName: string) => {
    // #505：系统层重试——复用已持久问话，不造重复句。
    if (busy || !replyRetry) return;
    const initiatingPanelName = selectedMinisterRef.current;
    setBusy("重新生成回话");
    setError("");
    setChatNotice("");
    try {
      const data = await api<ChatResponse>(`/api/ministers/${encodeURIComponent(targetMinisterName)}/reply/retry`, {
        method: "POST",
      });
      if (selectedMinisterRef.current !== initiatingPanelName) return;
      applyHistory(data.history);
      setSuggestions(data.suggestions);
      setCanUndoLastChat(!!data.can_undo_last_chat);
      setChatFailures((items) => mergePendingActionFailures(items, data.pending_action_failures || []));
      setReplyRetry(null);
      setChatNotice("已重新生成回话。");
      invalidateAudienceScroll();
      void refreshDurableProjection({ secretOrders: true });
      void refreshExtractionPending();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const retryStoryExtraction = async () => {
    // #501：原地重试补跑叙事抽取。
    // #1312：SSE stage 分段进度反馈（既有 settle 同形），禁干等无反馈。
    if (busy) return;
    setBusy("重试补写账本");
    setError("");
    try {
      const data = await retryAudienceStoryExtraction(invalidateAudienceScroll, {
        onStage: (text) => setBusy(text || "重试补写账本"),
      });
      setExtractionPendingCount(Number(data?.count || 0));
      if ((data?.count || 0) === 0) {
        setChatNotice("待补账本已补写完毕。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const retryPendingAction = async (failure: PendingActionFailure) => {
    if (busy) return;
    const targetMinisterName = failure.minister_name || activeMinister?.name || selectedMinisterRef.current;
    setBusy("重试密令下达");
    setError("");
    try {
      const data = await api<{
        retry: { committed: boolean };
        secret_orders: SecretOrder[];
        can_undo_last_chat?: boolean;
        pending_action_failures?: PendingActionFailure[];
      }>(
        `/api/pending_actions/${failure.id}/retry`,
        { method: "POST" },
      );
      if (!data.retry?.committed) {
        if (selectedMinisterRef.current === targetMinisterName) {
          setError("密令仍未能正式落库，请稍后再试。");
        }
        return;
      }
      setSecretOrders(data.secret_orders || []);
      await loadState();
      const staleTarget = selectedMinisterRef.current !== targetMinisterName;
      const canRefreshFailureList = failureRecoveryMode || !staleTarget;
      if (data.pending_action_failures) {
        if (canRefreshFailureList) {
          setChatFailures((items) => refreshRetriedPendingActionFailures(
            items,
            failure.id,
            targetMinisterName,
            data.pending_action_failures || [],
          ));
        }
      } else {
        if (canRefreshFailureList) {
          setChatFailures((items) => items.filter((item) => item.id !== failure.id));
        }
      }
      if (staleTarget) return;
      if (typeof data.can_undo_last_chat === "boolean") {
        setCanUndoLastChat(data.can_undo_last_chat);
      }
    } catch (err) {
      if (selectedMinisterRef.current === targetMinisterName) {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy("");
    }
  };

  const openFailureRecovery = async () => {
    setBusy("读取失败密令");
    setError("");
    try {
      const data = await api<{ pending_action_failures?: PendingActionFailure[] }>("/api/pending_actions/failures");
      const failures = data.pending_action_failures || [];
      if (!(await surfacePendingActionFailures(failures))) {
        setError("暂无可处理的密令失败。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  return {
    suggestions,
    chatNotice,
    chatFailures,
    activeChatFailures,
    replyRetry,
    extractionPendingCount,
    refreshExtractionPending,
    canUndoLastChat,
    composerHint,
    setComposerHint,
    input,
    setInput,
    failureRecoveryMode,
    activeMinister,
    openChat,
    sendChat,
    undoLastChat,
    retryInterruptedReply,
    retryStoryExtraction,
    retryPendingAction,
    openFailureRecovery,
    surfacePendingActionFailures,
  };
}
