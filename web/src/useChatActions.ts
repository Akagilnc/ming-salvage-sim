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
  RetryReadFailure,
  SecretOrder,
  ServerChatMessage,
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
  runAudienceTurn: (minister: string, message: string, cb: SendChatCallbacks) => Promise<void>;
  invalidateAudienceScroll: () => void;
  currentNightId: number;
}) {
  const [chatNotice, setChatNotice] = React.useState("");
  const [replyRetries, setReplyRetries] = React.useState<ReplyRetry[]>([]);
  const [translationRetries, setTranslationRetries] = React.useState<TranslationRetry[]>([]);
  const [retryReadFailure, setRetryReadFailure] = React.useState<RetryReadFailure | null>(null);
  const [canUndoLastChat, setCanUndoLastChat] = React.useState(false);
  const [composerHint, setComposerHint] = React.useState("");
  const [input, setInput] = React.useState("");
  const [temporaryActiveMinister, setTemporaryActiveMinister] = React.useState<Minister | null>(null);
  const recoveryTimer = React.useRef<number | undefined>(undefined);
  const recoveryRun = React.useRef(0);
  const summonTargetRef = React.useRef("");

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
    // #499：历史投影的派发由 hook 独占。返回 null=被 generation 守卫拒收
    // 的陈旧快照 → App 一并跳过全部面板外围写入（建议/可撤回/失败/临时大臣），不回覆新完成的轮。
    const data = await loadHistoryProjection(ministerName);
    if (!data || selectedMinisterRef.current !== ministerName) return null;
    const allKnown = rosterRef.current;
    setTemporaryActiveMinister(allKnown.some((m) => m.name === data.minister.name) ? null : data.minister);
    setCanUndoLastChat(!!data.can_undo_last_chat);
    // #505：崩溃遗留的中断轮 → 系统层重试入口。
    setReplyRetries(data.reply_retries ?? []);
    setTranslationRetries(data.translation_retries ?? []);
    setRetryReadFailure(null);
    return data;
  }, [loadHistoryProjection, selectedMinisterRef]);

  React.useEffect(() => {
    if (!selectedMinister) {
      resetPanel();
      setChatNotice("");
      setCanUndoLastChat(false);
      setComposerHint("");
      return;
    }
    resetPanel();
    setCanUndoLastChat(false);
    setRetryReadFailure(null);
    setComposerHint("");
    loadMinisterChat(selectedMinister)
      .catch((err) => setError(err.message));
  }, [selectedMinister, loadMinisterChat]);

  // 关召对只 setActiveModal("none"), 不改 selectedMinister / 不走 resetPanel；
  React.useEffect(() => {
    if (activeModal !== "chat") {
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
        status: "active", status_label: "在殿", summary: "", favorite: false,
      } : temporaryActiveMinister))
    : null;

  const sendChat = async (targetMinisterName: string, text = input) => {
    if (busy) return;
    // Free prose: preserve raw bytes; emptiness on a local copy (#1834 F16).
    const message = text;
    if (!message.trim()) {
      setComposerHint("请先问话或点一个奏对题目");
      return;
    }
    recoveryRun.current += 1;
    window.clearTimeout(recoveryTimer.current);

    const fromComposer = text === input;
    // #526 / ADR 0047：退朝钮与手输口令同一收夜管线（chat stream）；
    // 词表真源在后端 COURT_BREAK_COMMANDS，前端不复制。
    setError("");
    setComposerHint("");
    setChatNotice("");
    if (fromComposer) {
      setInput("");
    }
    // 面板归属与卷轴当前奏对者是两种身份：前者只用于判断玩家是否已离开发起面板。
    const initiatingPanelName = selectedMinisterRef.current;
    // 流式/请求归属/派发由 hook 独占；App 只在 done 到手即幂等消费持久后果 + 面板态。
    await runAudienceTurn(targetMinisterName, message, {
      // 回话 done：done 载荷即含全部持久后果，立即消费——不拖到 SSE end，
      // 不按请求 token 门控（后果持久）。全局态无条件落；面板态按当前大臣归属落。
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
        }
        setError(err instanceof Error ? err.message : String(err));
      },
    });
  };

  // Selection resets/loads the scene panel first; only then start its first stream.
  React.useEffect(() => {
    if (selectedMinister !== AUDIENCE_SCENE_SPEAKER || !summonTargetRef.current) return;
    const target = summonTargetRef.current;
    summonTargetRef.current = "";
    void sendChat(AUDIENCE_SCENE_SPEAKER, `宣${target}`);
  }, [selectedMinister]);

  const openChat = (minister: Minister) => {
    // #1849 reopen：召对只有殿上一个入口；非殿上名一律当「宣 X」加速器。
    if (minister.name !== AUDIENCE_SCENE_SPEAKER) {
      if (minister.status && minister.status !== "active") {
        setError(`${minister.name}已${minister.status_label}${minister.status_reason ? "（" + minister.status_reason + "）" : ""}，无法召见。`);
        return;
      }
      summonMinister(minister.name);
      return;
    }
    const switchingMinister = selectedMinister !== AUDIENCE_SCENE_SPEAKER;
    if (switchingMinister) {
      resetPanel();
      setTemporaryActiveMinister(null);
      setCanUndoLastChat(false);
    }
    setSelectedMinister(AUDIENCE_SCENE_SPEAKER);
    setActiveModal("chat");
    setError("");
    setComposerHint("");
    setChatNotice("");
    setCanUndoLastChat(false);
    clearPendingText();
    if (!switchingMinister) {
      loadMinisterChat(AUDIENCE_SCENE_SPEAKER).catch((err) => setError(err.message));
    }
  };

  const summonMinister = (ministerName: string) => {
    const scene = { name: AUDIENCE_SCENE_SPEAKER, office: "一夜一卷", status: "active" } as Minister;
    const switchingToScene = selectedMinister !== AUDIENCE_SCENE_SPEAKER;
    if (switchingToScene) summonTargetRef.current = ministerName;
    openChat(scene);
    if (!switchingToScene) void sendChat(AUDIENCE_SCENE_SPEAKER, `宣${ministerName}`);
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
      const data = await api<ChatUndoResponse>(audienceUndoPath(), {
        method: "POST",
      });
      // Undo's GLOBAL effects (secret orders / directives / full state) apply
      // regardless — the undo mutated game state, not just the panel. But the
      // minister-PANEL writes (history / undo-availability / notice)
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
    setRetryReadFailure(null);
    try {
      const data = await api<ChatResponse>(audienceRetryPath(), {
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
        setCanUndoLastChat(!!data.can_undo_last_chat);
      setReplyRetries((current) => current.filter((retry) => retry.chat_turn_id !== chatTurnId));
      setChatNotice("本轮恢复完成。");
      invalidateAudienceScroll();
    } catch (postError) {
      try {
        await loadMinisterChat(initiatingPanelName);
        if (selectedMinisterRef.current === initiatingPanelName) {
          setRetryReadFailure({ kind: "reply", chatTurnId, postSucceeded: false,
            message: postError instanceof Error ? postError.message : String(postError) });
        }
      } catch (reloadError) {
        console.error("Failed to reload audience after reply retry", reloadError);
        if (selectedMinisterRef.current === initiatingPanelName) {
          setRetryReadFailure({ kind: "reply", chatTurnId, postSucceeded: false,
            message: postError instanceof Error ? postError.message : String(postError), readFailure: true });
        }
      }
      invalidateAudienceScroll();
    } finally {
      setBusy("");
    }
  };

  const retryTranslation = async (chatTurnId: number) => {
    if (busy) return;
    const ministerName = selectedMinisterRef.current;
    setBusy("重试整理记录");
    setError("");
    const alreadyPosted = retryReadFailure?.kind === "translation"
      && retryReadFailure.chatTurnId === chatTurnId && retryReadFailure.postSucceeded;
    setRetryReadFailure(null);
    let postSucceeded = alreadyPosted;
    try {
      if (!alreadyPosted) {
        await api("/api/audience/translation/retry", {
          method: "POST",
          body: JSON.stringify({ chat_turn_id: chatTurnId }),
        });
        postSucceeded = true;
      }
      await loadMinisterChat(ministerName);
      invalidateAudienceScroll();
    } catch (postError) {
      try {
        await loadMinisterChat(ministerName);
        if (!postSucceeded && selectedMinisterRef.current === ministerName) {
          setRetryReadFailure({ kind: "translation", chatTurnId, postSucceeded,
            message: postError instanceof Error ? postError.message : String(postError) });
        }
      } catch (reloadError) {
        console.error("Failed to reload audience after translation retry", reloadError);
        if (selectedMinisterRef.current === ministerName) {
          setRetryReadFailure({ kind: "translation", chatTurnId, postSucceeded,
            message: postError instanceof Error ? postError.message : String(postError), readFailure: true });
        }
      }
      invalidateAudienceScroll();
    } finally {
      setBusy("");
    }
  };

  return {
    chatNotice,
    replyRetries,
    translationRetries,
    retryReadFailure,
    canUndoLastChat,
    composerHint,
    setComposerHint,
    input,
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
