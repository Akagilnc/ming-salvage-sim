import React from "react";
import { api } from "./api";
import type { AudienceHistoryData, SendChatCallbacks } from "./useAudienceChat";
import type {
  ChatIdentity,
  ChatResponse,
  ChatUndoResponse,
  GameState,
  Minister,
  ModalName,
  ReplyRetry,
  SecretOrder,
  ServerChatMessage,
  Suggestion,
  TranslationRetry,
} from "./types";
import { AUDIENCE_SCENE_SPEAKER, audienceRetryPath, audienceUndoPath } from "./audienceScene";

type RefreshDurableProjection = (options?: {
  secretOrders?: boolean;
  onSecretOrders?: (orders: SecretOrder[]) => void;
  autoOpen?: { afterMs: number; when: (orders: SecretOrder[]) => boolean; open: () => void };
}) => Promise<GameState | null>;

// 召对动作群：召对面板的全部外围态（建议/提示/失败/恢复模式/输入框）与 busy 动作
// （开召对/发问/撤回/重试/失败恢复）。SSE 流、历史投影的归属仍在
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
  setSecretOrders: (orders: SecretOrder[]) => void;
  setUndoneChatIdentity: React.Dispatch<React.SetStateAction<ChatIdentity | null>>;
  loadState: () => Promise<GameState | null>;
  refreshDurableProjection: RefreshDurableProjection;
  resetPanel: () => void;
  clearPendingText: () => void;
  applyHistory: (history: ServerChatMessage[]) => void;
  loadHistoryProjection: (minister: string) => Promise<AudienceHistoryData | null>;
  runAudienceTurn: (minister: string, message: string, cb: SendChatCallbacks, intent?: "secret_order") => Promise<void>;
  invalidateAudienceScroll: () => void;
  currentNightId: number;
}) {
  const [suggestions, setSuggestions] = React.useState<Suggestion[]>([]);
  const [chatNotice, setChatNotice] = React.useState("");
  const [replyRetries, setReplyRetries] = React.useState<ReplyRetry[]>([]);
  const [translationRetries, setTranslationRetries] = React.useState<TranslationRetry[]>([]);
  const [canUndoLastChat, setCanUndoLastChat] = React.useState(false);
  const [composerHint, setComposerHint] = React.useState("");
  const [input, setInput] = React.useState("");
  const [composerIntent, setComposerIntent] = React.useState<"secret_order" | undefined>();
  const [temporaryActiveMinister, setTemporaryActiveMinister] = React.useState<Minister | null>(null);
  const recoveryTimer = React.useRef<number | undefined>(undefined);
  const recoveryRun = React.useRef(0);

  // 仅用花名册查 temporaryActiveMinister；挂 ref 避免 durable setState 整表刷新
  // 重造 loadMinisterChat → 触发 selectedMinister effect → resetPanel 清掉召对面板。
  const rosterRef = React.useRef<Minister[]>([]);
  React.useEffect(() => {
    rosterRef.current = [
      ...(state?.ministers || []),
      ...(state?.consorts || []),
    ];
  }, [state?.ministers, state?.consorts]);

  const loadMinisterChat = React.useCallback(async (ministerName: string) => {
    // #499：历史投影 + 每一待读心轮的轮询由 hook 独占派发。返回 null=被 generation 守卫拒收
    // 的陈旧快照 → App 一并跳过全部面板外围写入（建议/可撤回/失败/临时大臣），不回覆新完成的轮。
    const data = await loadHistoryProjection(ministerName);
    if (!data || selectedMinisterRef.current !== ministerName) return null;
    const allKnown = rosterRef.current;
    setTemporaryActiveMinister(allKnown.some((m) => m.name === data.minister.name) ? null : data.minister);
    setSuggestions(data.suggestions);
    setCanUndoLastChat(!!data.can_undo_last_chat);
    // #505：崩溃遗留的中断轮 → 系统层重试入口。
    setReplyRetries(data.reply_retries ?? []);
    setTranslationRetries(data.translation_retries ?? []);
    return data;
  }, [loadHistoryProjection, selectedMinisterRef]);

  React.useEffect(() => {
    if (!selectedMinister) {
      resetPanel();
      setSuggestions([]);
      setChatNotice("");
      setCanUndoLastChat(false);
      setComposerHint("");
      setComposerIntent(undefined);
      return;
    }
    resetPanel();
    setSuggestions([]);
    setCanUndoLastChat(false);
    setComposerHint("");
    setComposerIntent(undefined);
    loadMinisterChat(selectedMinister)
      .catch((err) => setError(err.message));
  }, [selectedMinister, loadMinisterChat]);

  // 关召对只 setActiveModal("none"), 不改 selectedMinister / 不走 resetPanel；
  // composerIntent 是 composer-session 态，离 chat 面必须随 session 死。
  React.useEffect(() => {
    if (activeModal !== "chat") {
      setComposerIntent(undefined);
      recoveryRun.current += 1;
      window.clearTimeout(recoveryTimer.current);
    }
    return () => {
      recoveryRun.current += 1;
      window.clearTimeout(recoveryTimer.current);
    };
  }, [activeModal]);

  const activeMinister = state && selectedMinister
    ? ([...state.ministers, ...(state.consorts || [])].find((m) => m.name === selectedMinister)
      || (selectedMinister === AUDIENCE_SCENE_SPEAKER ? {
        name: AUDIENCE_SCENE_SPEAKER, office: "一夜一卷", office_type: "scene", faction: "", style: "",
        status: "active", status_label: "在殿", summary: "", favorite: false, skills: [],
      } : temporaryActiveMinister))
    : null;

  const sendChat = async (targetMinisterName: string, text = input) => {
    const intent = text === input ? composerIntent : undefined;
    if (busy) return;
    const message = text.trim();
    if (!message) {
      setComposerHint("请先问话或点一个奏对题目");
      return;
    }

    const fromComposer = text === input;
    // #526 / ADR 0047：退朝钮与手输口令同一收夜管线（chat stream）；
    // 词表真源在后端 COURT_BREAK_COMMANDS，前端不复制。
    setError("");
    setComposerHint("");
    setChatNotice("");
    if (fromComposer) {
      setInput("");
      setComposerIntent(undefined);
    }
    // 面板归属与卷轴当前奏对者是两种身份：前者只用于判断玩家是否已离开发起面板。
    const initiatingPanelName = selectedMinisterRef.current;
    // 流式/请求归属/派发由 hook 独占；App 只在 done 到手即幂等消费持久后果 + 面板态。
    await runAudienceTurn(targetMinisterName, message, {
      // 回话 done：done 载荷即含全部持久后果，立即消费——不拖到 SSE end（读心可延后 end 达
      // 120s），不按请求 token 门控（后果持久）。全局态无条件落；面板态按当前大臣归属落。
      onDone: (data) => {
        // 单调即时字段直接落 done 载荷（各 done 递新，无竞争）：指令 / pending 计数。
        // #1716：pending_directive_count 同落——拟诏台 hasSettleWork 不得等 refresh 竞态。
        setState((current) => (current ? {
          ...current,
          directives: data.directives,
          pending_count: data.pending_count ?? current.pending_count,
          pending_directive_count: data.pending_directive_count ?? current.pending_directive_count,
        } : current));
        // done 即重取：回话可见后的即时持久后果；成案等尾随落账以 onEnd 再读为准（#1764）。
        // 经唯一协调器 latest-wins：end/撤回等新刷新会作废本次早到响应。
        void refreshDurableProjection({ secretOrders: true });
        // 面板态：仅当前大臣面板未切走才落。
        if (selectedMinisterRef.current !== initiatingPanelName) return;
        setSuggestions(data.suggestions);
        setCanUndoLastChat(!!data.can_undo_last_chat);
        if (data.court_action === "dismiss") {
          clearPendingText();
        }
      },
      // #1764：end = 抽取成案/收夜等尾随已 join 的提交完成缝；再读权威 durable（含 cased_directives）。
      // 不延迟 done；不新建轮询/总线。观察者离面无 end 时，重入拟诏经公共 openModal(edict)→loadState。
      onEnd: () => {
        void refreshDurableProjection({ secretOrders: true });
      },
      // 观察者离开实时流：召对在后台续跑，重开经历史重入。
      onLeave: () => {
        setChatNotice("已离开实时回话；大臣会继续回奏，稍后重开可见。");
        setError("");
      },
      onError: (err, failedTurn) => {
        // 回填归属由 useAudienceChat 的 generation+面板 freshness 门控后才入此回调；
        // 此处再按发起面板守一次，防切大臣后的同 token 尾巴。
        if (failedTurn?.chat_turn_id) {
          setError("");
          const run = ++recoveryRun.current;
          const awaitTerminal = async () => {
            try {
              const data = await loadMinisterChat(initiatingPanelName);
              if (run === recoveryRun.current && data?.generating_turn_ids?.includes(failedTurn.chat_turn_id)) {
                recoveryTimer.current = window.setTimeout(awaitTerminal, 1500);
              }
            } catch (loadError) {
              setError(loadError instanceof Error ? loadError.message : String(loadError));
              if (run === recoveryRun.current) recoveryTimer.current = window.setTimeout(awaitTerminal, 1500);
            }
          };
          void awaitTerminal();
          return;
        }
        if (fromComposer && selectedMinisterRef.current === initiatingPanelName) {
          setInput(message);
          setComposerIntent(intent);
        }
        setError(err instanceof Error ? err.message : String(err));
      },
    }, intent);
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
    setComposerHint("");
    setChatNotice("");
    setCanUndoLastChat(false);
    clearPendingText();
    // 切换大臣时 selected-minister effect 会加载；只有重开同一大臣（effect 不触发）才显式加载，
    // 免得一次切换发两条同大臣 GET（#499 陈旧快照回覆源头之一）。
    if (!switchingMinister) {
      loadMinisterChat(minister.name).catch((err) => setError(err.message));
    }
  };

  const summonMinister = (ministerName: string) => {
    const scene = { name: AUDIENCE_SCENE_SPEAKER, office: "一夜一卷", status: "active" } as Minister;
    openChat(scene);
    // The command starts in the same event turn, before React commits selectedMinister.
    selectedMinisterRef.current = AUDIENCE_SCENE_SPEAKER;
    void sendChat(AUDIENCE_SCENE_SPEAKER, `宣${ministerName}`);
  };

  const undoLastChat = async (targetMinisterName: string) => {
    if (busy || !canUndoLastChat) return;
    // #1732 B：确认门控移到 ChatModal 就地条；此处直接执行。
    const initiatingPanelName = selectedMinisterRef.current;
    setBusy("撤回召对");
    setError("");
    setChatNotice("");
    setComposerHint("");
    clearPendingText();
    try {
      const data = await api<ChatUndoResponse>(audienceUndoPath(targetMinisterName), {
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
      setState((current) => (current ? {
        ...current,
        directives: data.directives,
        pending_count: data.pending_count ?? current.pending_count,
        pending_directive_count: data.pending_directive_count ?? current.pending_directive_count,
      } : current));
      // reload 不承担计数正确性：post-undo count 已由 pending_directive_count 即时投影。
      await loadState();
      // Read the ref FRESH at the panel-write point (the minister could switch
      // during the awaits above), mirroring sendChat's post-await check.
      if (selectedMinisterRef.current === initiatingPanelName) {
        // #499：撤回后剩余轮的读心递话仍随 turn-identified 投影归位。
        applyHistory(data.history);
        setSuggestions(data.suggestions);
        setCanUndoLastChat(!!data.can_undo_last_chat);
        setChatNotice("已撤回最近一轮召对。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const retryInterruptedReply = async (targetMinisterName: string, chatTurnId: number) => {
    // #505：系统层重试——复用已持久问话，不造重复句。
    const retry = replyRetries.find((entry) => entry.chat_turn_id === chatTurnId);
    if (busy || !retry) return;
    const initiatingPanelName = selectedMinisterRef.current;
    setBusy(retry.recovery_phase ? "恢复本轮后续处理" : "重新生成回话");
    setError("");
    setChatNotice("");
    try {
      const data = await api<ChatResponse>(audienceRetryPath(targetMinisterName), {
        method: "POST",
        body: JSON.stringify({ chat_turn_id: chatTurnId }),
      });
      // 拟旨计数是全局态：面板切走仍须即时投影，不得等 refresh / 不得被陈旧判断吞掉。
      setState((current) => (current ? {
        ...current,
        directives: data.directives,
        pending_count: data.pending_count ?? current.pending_count,
        pending_directive_count: data.pending_directive_count ?? current.pending_directive_count,
      } : current));
      void refreshDurableProjection({ secretOrders: true });
      if (selectedMinisterRef.current !== initiatingPanelName) return;
      applyHistory(data.history);
      setSuggestions(data.suggestions);
      setCanUndoLastChat(!!data.can_undo_last_chat);
      setReplyRetries((current) => current.filter((retry) => retry.chat_turn_id !== chatTurnId));
      setChatNotice("本轮恢复完成。");
      invalidateAudienceScroll();
    } catch (err) {
      await loadMinisterChat(initiatingPanelName).catch((loadError) =>
        setError(loadError instanceof Error ? loadError.message : String(loadError))
      );
    } finally {
      setBusy("");
    }
  };

  const retryTranslation = async (chatTurnId: number) => {
    if (busy) return;
    const ministerName = selectedMinisterRef.current;
    setBusy("重试整理记录");
    setError("");
    try {
      await api("/api/audience/translation/retry", {
        method: "POST",
        body: JSON.stringify({ chat_turn_id: chatTurnId }),
      });
      await loadMinisterChat(ministerName);
      invalidateAudienceScroll();
    } catch (err) {
      await loadMinisterChat(ministerName).catch((loadError) =>
        setError(loadError instanceof Error ? loadError.message : String(loadError))
      );
    } finally {
      setBusy("");
    }
  };

  return {
    suggestions,
    chatNotice,
    replyRetries,
    translationRetries,
    canUndoLastChat,
    composerHint,
    setComposerHint,
    input,
    setComposerIntent,
    setInput,
    activeMinister,
    openChat,
    summonMinister,
    sendChat,
    undoLastChat,
    retryInterruptedReply,
    retryTranslation,
  };
}
