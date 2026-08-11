import React from "react";
import { createRoot } from "react-dom/client";
import { Crown, Loader2, X } from "lucide-react";
import { api } from "./api";
import { useAudienceChat } from "./useAudienceChat";
import { useDurableProjection } from "./useDurableProjection";
import { mergePendingActionFailures, refreshRetriedPendingActionFailures } from "./chatFailures";
import { AppointmentDrawer, ArmyDrawer, BuildingDrawer, CourtDrawer, EconomyDrawer, HaremDrawer, RegionDrawer } from "./components/drawers";
import { GameMenuModal } from "./components/gameMenu";
import { BudgetHover, CommandSlot, FullscreenModal, HUD_BG, HUD_SLOTS, LegacyBar, LongGoalsModal, QuadFrame } from "./components/hud";
import { GrandMap, NodeIntel } from "./components/map";
import { MenuPage } from "./components/menuPage";
import { AudienceArchiveModal, ChatModal, ClosedIssuesModal, EdictModal, EndingModal, HistoryModal, ReportModal, SecretOrdersModal, StateModal, filterConsorts, filterMinisters } from "./components/modals";
import { SituationPanel } from "./components/situation";
import { DecisionModal } from "./components/decisionModal";
import { DecisionRecoveryPanel } from "./components/decisionRecovery";
import { replacePendingDecisionsOnRefresh, routeIssueDecisions, routeRefreshDecisions, routeRetryDecisions } from "./decisionRouting";
import { getMapIntelStyle, refreshLabelMaps, scoreTone } from "./format";
import { retryAudienceStoryExtraction } from "./extractionRetry";
import { shouldAutoOpenClosedIssuesAfterSettlement, shouldAutoOpenSecretOrdersAfterSettlement } from "./settlementPresentation";
import { forwardSteamEvents, type SteamEvent } from "./steamEvents";
import type { AppView, ChatUndoResponse, ClosedIssue, Directive, ExtractionPendingStatus, GameState, MenuStatus, Minister, ModalName, PendingActionFailure, PendingDecision, ReplyRetry, SecretOrder, Suggestion } from "./types";
import "./styles.css";

export function App() {
  const [appView, setAppView] = React.useState<AppView>("menu");
  const [menuStatus, setMenuStatus] = React.useState<MenuStatus | null>(null);
  // 新 HUD stage 实际像素尺寸（matrix3d 透视需要 px 基准）
  const hudStageRef = React.useRef<HTMLDivElement | null>(null);
  const [hudStageSize, setHudStageSize] = React.useState({ w: 0, h: 0 });
  // 用 callback ref：stage 一挂载就接 ResizeObserver，避免 effect 时机竞态导致尺寸永远 0
  const hudStageCbRef = React.useCallback((el: HTMLDivElement | null) => {
    hudStageRef.current = el;
    if (!el) return;
    const measure = () => setHudStageSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    (el as any).__ro = ro;
  }, []);
  const [state, setState] = React.useState<GameState | null>(null);
  const [selectedNodeId, setSelectedNodeId] = React.useState<string>("");
  const [mapIntelOpen, setMapIntelOpen] = React.useState(false);
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const [haremDrawerOpen, setHaremDrawerOpen] = React.useState(false);
  const [armyDrawerOpen, setArmyDrawerOpen] = React.useState(false);
  const [regionDrawerOpen, setRegionDrawerOpen] = React.useState(false);
  const [buildingDrawerOpen, setBuildingDrawerOpen] = React.useState(false);
  const [economyDrawerOpen, setEconomyDrawerOpen] = React.useState(false);
  const [appointmentDrawerOpen, setAppointmentDrawerOpen] = React.useState(false);
  const [selectedRegionId, setSelectedRegionId] = React.useState<string>("");
  const [selectedArmyId, setSelectedArmyId] = React.useState<string>("");
  const [ministerGroup, setMinisterGroup] = React.useState("内阁+六部");
  const [haremGroup, setHaremGroup] = React.useState("全部");
  const [selectedMinister, setSelectedMinister] = React.useState<string>("");
  const [temporaryActiveMinister, setTemporaryActiveMinister] = React.useState<Minister | null>(null);
  const [activeModal, setActiveModal] = React.useState<ModalName>("none");
  const [suggestions, setSuggestions] = React.useState<Suggestion[]>([]);
  const [chatNotice, setChatNotice] = React.useState("");
  const [chatFailures, setChatFailures] = React.useState<PendingActionFailure[]>([]);
  const [replyRetry, setReplyRetry] = React.useState<ReplyRetry | null>(null);
  const [extractionPendingCount, setExtractionPendingCount] = React.useState(0);
  const [canUndoLastChat, setCanUndoLastChat] = React.useState(false);
  const [composerHint, setComposerHint] = React.useState("");
  const [input, setInput] = React.useState("");
  const [directiveText, setDirectiveText] = React.useState("");
  const [editingDirectiveId, setEditingDirectiveId] = React.useState<number | null>(null);
  const [editingDirectiveText, setEditingDirectiveText] = React.useState("");
  const [decree, setDecree] = React.useState("");
  const [report, setReport] = React.useState("");
  const [gazetteReport, setGazetteReport] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [settleStage, setSettleStage] = React.useState("");
  const [settleThinking, setSettleThinking] = React.useState("");
  const [settleNarrative, setSettleNarrative] = React.useState("");
  const [closedShown, setClosedShown] = React.useState<number>(() => {
    const raw = sessionStorage.getItem("closedShownTurn");
    return raw ? Number(raw) : -1;
  });
  const [closedModal, setClosedModal] = React.useState<ClosedIssue[]>([]);
  const [gazetteShown, setGazetteShown] = React.useState<number>(-1);
  // 结局页本次加载是否已被玩家关掉（关掉后让位邸报，刷新复位重弹）。
  const [endingDismissed, setEndingDismissed] = React.useState(false);
  const [secretOrders, setSecretOrders] = React.useState<SecretOrder[]>([]);
  const [secretOrderShown, setSecretOrderShown] = React.useState<number>(-1);
  const [undoneChatIdentity, setUndoneChatIdentity] = React.useState<{ campaign_id: string; night_id: number; chat_turn_id: number } | null>(null);
  const [audienceScrollGeneration, setAudienceScrollGeneration] = React.useState(0);
  // 作弊控制台（Ctrl+~）：cheatDirective 暂存强制结算项，下次颁诏随结算一次性穿入。
  const [cheatOpen, setCheatOpen] = React.useState(false);
  const [cheatDirective, setCheatDirective] = React.useState("");
  // HITL 决策点：颁诏推演若出重大抉择，暂停弹窗逐个亲裁，裁完续跑结算。
  const [pendingDecisions, setPendingDecisions] = React.useState<PendingDecision[]>([]);
  const [decisionFailures, setDecisionFailures] = React.useState<PendingActionFailure[]>([]);
  const [pausedDecisionError, setPausedDecisionError] = React.useState("");
  const [failureRecoveryMode, setFailureRecoveryMode] = React.useState(false);

  // Tracks the current selected minister across async boundaries.
  // State closures capture stale values; this ref always reflects the latest.
  const selectedMinisterRef = React.useRef<string>("");
  const suppressNextReportRef = React.useRef(false);
  const invalidateAudienceScroll = React.useCallback(() => {
    setAudienceScrollGeneration((generation) => generation + 1);
  }, []);

  // #499 召对投递单一控制器：App 唯一消费的 hook，独占 SSE / 历史 / 读心轮询 / 请求归属
  // (token) / reducer 派发。所有召对显示态写入都过它并按请求归属门控——旧流尾巴绝不改动
  // 更新请求的待答文/流式文/取消句柄/busy。App 只经回调补全外围态。
  const {
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
    loadHistory: loadHistoryProjection,
    sendChat: runAudienceTurn,
    cancelChat,
    // chatOpen=activeModal==="chat"：hook 内置的唯一 chat-exit 归属据此取消流 + 作废 poll-batch。
  } = useAudienceChat(setBusy, selectedMinisterRef, activeModal === "chat", invalidateAudienceScroll);

  // 持久投影落 UI 的稳定 applier（供 latest-wins 协调器代次门控后调用）。
  const applyDurableState = React.useCallback((data: GameState) => {
    refreshLabelMaps(data);
    setState(data);
    setSelectedNodeId((current) => current || data.map_nodes[0]?.id || "");
    setDecree(data.last_decree || "");
    setReport(data.last_report || "");
  }, []);
  const { refresh: refreshDurableProjection, beginMutation: beginDurableMutation } = useDurableProjection(applyDurableState, setSecretOrders);
  // loadState = 不带密令的持久刷新；所有既有调用方经此参与同一 latest-wins 协调（撤回/重试/
  // 结算调 loadState 即推进代次、作废在飞的旧 done 刷新）。
  const loadState = React.useCallback(
    () => refreshDurableProjection(),
    [refreshDurableProjection],
  );

  const loadMinisterChat = React.useCallback(async (ministerName: string, options?: { mergeFailures?: boolean }) => {
    // #499：历史投影 + 每一待读心轮的轮询由 hook 独占派发。返回 null=被 generation 守卫拒收
    // 的陈旧快照 → App 一并跳过全部面板外围写入（建议/可撤回/失败/临时大臣），不回覆新完成的轮。
    const data = await loadHistoryProjection(ministerName);
    if (!data || selectedMinisterRef.current !== ministerName) return;
    const allKnown = [
      ...(state?.ministers || []),
      ...(state?.consorts || []),
    ];
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
  }, [state, loadHistoryProjection]);

  const refreshExtractionPending = React.useCallback(async () => {
    // #501：本开夜待补叙事抽取——显眼提示取数；失败静默（不挡召对）。
    try {
      const data = await api<ExtractionPendingStatus>("/api/audience/extraction/pending");
      setExtractionPendingCount(Number(data?.count || 0));
    } catch {
      /* 取数失败不锁面板 */
    }
  }, []);

  // 召对面板打开时拉一次待补状态，并在打开期间低频刷新（补跑/回话完成后可自愈）。
  React.useEffect(() => {
    if (activeModal !== "chat") return;
    void refreshExtractionPending();
    const id = window.setInterval(() => {
      void refreshExtractionPending();
    }, 8000);
    return () => window.clearInterval(id);
  }, [activeModal, refreshExtractionPending, selectedMinister]);

  const uploadPortrait = React.useCallback(async (ministerName: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`/api/consorts/${encodeURIComponent(ministerName)}/portrait`, {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || resp.statusText);
    }
    await loadState();  // 重新拉 state，新 portrait_id 流回卡片
  }, [loadState]);

  const refreshMenuStatus = React.useCallback(async () => {
    const s = await api<MenuStatus>("/api/menu/status");
    setMenuStatus(s);
    return s;
  }, []);

  React.useEffect(() => {
    refreshMenuStatus()
      .then((s) => {
        if (s.has_running_game) {
          setAppView("game");
          loadState().catch((err) => setError(err.message));
        }
      })
      .catch((err) => setError(err.message));
  }, [refreshMenuStatus, loadState]);

  const enterGameAfterMenu = React.useCallback(async () => {
    setUndoneChatIdentity(null);
    setAppView("game");
    await loadState();
  }, [loadState]);

  const exitToMenu = React.useCallback(async () => {
    // #499：清空 state 前推进持久投影代次，作废在飞的旧 done 刷新——否则迟到刷新会在退菜单后
    // 把陈旧 state 回填、再入局时短暂渲染。清态本身也是一次持久投影变更，纳入代次归属。
    beginDurableMutation();
    await fetch("/api/menu/exit_to_menu", { method: "POST" });
    setState(null);
    setUndoneChatIdentity(null);
    setAppView("menu");
    await refreshMenuStatus();
  }, [refreshMenuStatus, beginDurableMutation]);

  React.useEffect(() => {
    if (!state) return;
    const closed = state.closed_this_turn || [];
    const currentTurn = state.turn.turn;
    if (closed.length && currentTurn !== closedShown && shouldAutoOpenClosedIssuesAfterSettlement()) {
      setClosedModal(closed);
      setClosedShown(currentTurn);
      sessionStorage.setItem("closedShownTurn", String(currentTurn));
    }
  }, [state, closedShown]);

  // 新回合进入时拉取全部密令；仅刚结算出的御前密奏触发私密侧区。
  // #499：密令重取经唯一 latest-wins 协调器 refresh，与 done/撤回共享代次——旧回合的密令
  // 响应迟到不覆盖新结果。shown 标记只在**接受成功后**（onSecretOrders 内）落，取失败可重试；
  // 延迟弹窗在触发时按 isLatest 门控，撤回等推进代次后陈旧定时器 no-op（不会弹已作废的窗）。
  React.useEffect(() => {
    if (!state) return;
    const currentTurn = state.turn.turn;
    if (currentTurn === secretOrderShown) return;
    void refreshDurableProjection({
      secretOrders: true,
      onSecretOrders: () => setSecretOrderShown(currentTurn),  // 仅接受成功（最新代次）才标记已呈现
      // 延迟呈现归协调器：400ms 后仍最新代次才弹窗；撤回等推进代次后陈旧定时器 no-op。
      autoOpen: {
        afterMs: 400,
        when: (orders) => shouldAutoOpenSecretOrdersAfterSettlement(orders, currentTurn),
        open: () => setActiveModal("secret_orders"),
      },
    });
  }, [state?.turn.turn]);

  // 结局已触发：每次进页面/刷新都自动弹结局结算页。玩家点关闭后（endingDismissed）
  // 本次加载让位给盘面/邸报，可继续看局；刷新即复位重弹。
  React.useEffect(() => {
    if (!state || !state.ending) return;
    if (endingDismissed) return;
    setActiveModal("ending");
  }, [state, endingDismissed]);

  // 刷新恢复：若回合停在 awaiting_decision 且有未裁决策点，自动重弹决策弹窗。
  React.useEffect(() => {
    if (!state) return;
    const route = routeRefreshDecisions(state.turn.phase, state.pending_decisions || []);
    if (route.pendingDecisions !== null) {
      const next = route.pendingDecisions;
      setPendingDecisions((prev) => replacePendingDecisionsOnRefresh(prev, next) || []);
    }
    if (route.error !== null) setPausedDecisionError(route.error);
  }, [state]);

  // 每次进入页面/换回合都弹上回合邸报。不持久化记录——刷新即重新弹。
  // 同一加载周期内同一回合不重复弹（gazetteShown 用 React state，刷新后回到 -1）。
  React.useEffect(() => {
    if (!state) return;
    // 结局页未关掉时让位给它；玩家关掉后（endingDismissed）邸报照常。
    if (state.ending && !endingDismissed) return;
    const currentTurn = state.turn.turn;
    const summary = (state.previous_summary || "").trim();
    if (!summary) return;
    if (summary.startsWith("登基伊始")) return;
    if (currentTurn === gazetteShown) return;
    if (suppressNextReportRef.current) {
      suppressNextReportRef.current = false;
      return;
    }
    setGazetteReport(summary);
    setActiveModal("report");
    setGazetteShown(currentTurn);
  }, [state, gazetteShown, endingDismissed, activeModal]);

  React.useEffect(() => {
    selectedMinisterRef.current = selectedMinister;
  }, [selectedMinister]);


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

  // 全局 ESC：按 z-index 优先级，最前面的弹窗先关
  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (activeModal === "chat" || activeModal === "edict" || activeModal === "state" || activeModal === "history" || activeModal === "audience_archive" || activeModal === "report" || activeModal === "secret_orders" || activeModal === "long_goals") {
        // 召对/诏书等全屏弹窗最优先
        setActiveModal("none");
      } else if (drawerOpen) {
        setDrawerOpen(false);
      } else if (haremDrawerOpen) {
        setHaremDrawerOpen(false);
      } else if (armyDrawerOpen) {
        setArmyDrawerOpen(false);
      } else if (regionDrawerOpen) {
        setRegionDrawerOpen(false);
      } else if (buildingDrawerOpen) {
        setBuildingDrawerOpen(false);
      } else if (economyDrawerOpen) {
        setEconomyDrawerOpen(false);
      } else if (appointmentDrawerOpen) {
        setAppointmentDrawerOpen(false);
      } else if (mapIntelOpen) {
        setMapIntelOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [activeModal, drawerOpen, haremDrawerOpen, mapIntelOpen]);

  // 作弊控制台：Ctrl+~（或 Ctrl+`）切换显隐。强制结算唯一入口。
  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.ctrlKey && (event.key === "~" || event.key === "`")) {
        event.preventDefault();
        setCheatOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  if (appView === "menu") {
    return (
      <MenuPage
        status={menuStatus}
        onRefresh={refreshMenuStatus}
        onEnterGame={enterGameAfterMenu}
        error={error}
        setError={setError}
      />
    );
  }

  if (!state) {
    return (
      <div className="loading-screen">
        <div className="loading-panel">
          <Crown size={28} />
          <p>正在启封奏牍与山河舆图...</p>
        </div>
      </div>
    );
  }

  const powerById = new Map((state.powers || []).map((power) => [power.id, power]));
  const mapNodes = state.map_nodes.map((node) => {
    const powerId = node.region?.controlled_by;
    return powerId ? { ...node, power: powerById.get(powerId) } : node;
  });
  const selectedNode = mapNodes.find((node) => node.id === selectedNodeId) || mapNodes[0];
  const ministers = ministerGroup === "在野"
    ? (state.talent_pool || [])  // 在野人才池（offstage 罢居前臣，#120）单独走 talent_pool
    : filterMinisters(state.ministers, ministerGroup);
  const consorts = filterConsorts(state.consorts || [], haremGroup);
  const audienceRoster = [...state.ministers, ...(state.talent_pool || [])];
  const allCharacters = [...state.ministers, ...(state.consorts || [])];
  const activeMinister = selectedMinister
    ? allCharacters.find((m) => m.name === selectedMinister) || temporaryActiveMinister
    : null;
  const activeChatFailures = activeMinister
    ? (failureRecoveryMode
      ? chatFailures
      : chatFailures.filter((failure) => !failure.minister_name || failure.minister_name === activeMinister.name))
    : [];
  const mapIntelStyle = selectedNode ? getMapIntelStyle(selectedNode) : undefined;

  const openChat = (minister: Minister) => {
    if (minister.status && minister.status !== "active") {
      setError(`${minister.name}已${minister.status_label}${minister.status_reason ? "（" + minister.status_reason + "）" : ""}，无法召见。`);
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

  const selectMapNode = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setMapIntelOpen(true);
  };

  const sendChat = async (text = input) => {
    if (busy) return;
    if (!activeMinister) return;
    const message = text.trim();
    if (!message) {
      setComposerHint("请先问话或点一个奏对题目");
      return;
    }

    const targetMinisterName = activeMinister.name;
    const fromComposer = text === input;
    setError("");
    setComposerHint("");
    setChatNotice("");
    // 新一轮发出即清中断重试条（本轮 supersedes 崩溃遗留的系统重试入口）。
    setReplyRetry(null);
    if (fromComposer) {
      setInput("");
    }
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
        if (selectedMinisterRef.current !== targetMinisterName) return;
        setSuggestions(data.suggestions);
        setCanUndoLastChat(!!data.can_undo_last_chat);
        const responseFailures = data.pending_action_failures || [];
        if (data.secret_order_id) {
          setChatNotice(`密令已秘密交付${targetMinisterName}，编号 #${data.secret_order_id}。`);
        }
        setChatFailures((items) => mergePendingActionFailures(items, responseFailures));
        if (data.proposed_directive) {
          setChatNotice(`${targetMinisterName}已拟旨一道，待陛下在「诏书草案」核定（准/驳）。`);
        }
        if (data.next_minister && !responseFailures.length) {
          // 换人：设 selectedMinister 即触发 selected-minister effect 加载新面板（不再显式重复加载）。
          resetPanel();
          setSuggestions([]);
          setCanUndoLastChat(false);
          setChatFailures([]);
          setReplyRetry(null);
          setSelectedMinister(data.next_minister);
          setActiveModal("chat");
          setChatNotice(`已传${data.next_minister}入殿。`);
        }
        // 正常回话完成后刷新待补抽取状态（可能有新的失败待补）。
        void refreshExtractionPending();
        if (data.court_action === "dismiss") {
          clearPendingText();
          setChatNotice(`${targetMinisterName}已退下。请从左侧召见下一位大臣。`);
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

  const undoLastChat = async () => {
    if (busy || !activeMinister || !canUndoLastChat) return;
    const targetMinisterName = activeMinister.name;
    const ok = window.confirm("将撤回最近一轮召对及其政务影响，是否继续？");
    if (!ok) return;
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
      if (selectedMinisterRef.current === targetMinisterName) {
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

  const retryInterruptedReply = async () => {
    // #505：系统层重试——复用已持久问话，不造重复句。
    if (busy || !activeMinister || !replyRetry) return;
    const targetMinisterName = activeMinister.name;
    setBusy("重新生成回话");
    setError("");
    setChatNotice("");
    try {
      await api(`/api/ministers/${encodeURIComponent(targetMinisterName)}/reply/retry`, {
        method: "POST",
      });
      if (selectedMinisterRef.current !== targetMinisterName) return;
      setReplyRetry(null);
      setChatNotice("已重新生成回话。");
      await loadMinisterChat(targetMinisterName, { mergeFailures: true });
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
    if (busy) return;
    setBusy("重试补写账本");
    setError("");
    try {
      const data = await retryAudienceStoryExtraction(invalidateAudienceScroll);
      setExtractionPendingCount(Number(data?.count || 0));
      if ((data?.count || 0) === 0) setChatNotice("待补账本已补写完毕。");
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

  const createDirective = async () => {
    if (!directiveText.trim()) return;
    setBusy("登记诏书草案");
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>("/api/directives", {
        method: "POST",
        body: JSON.stringify({
          text: directiveText.trim(),
        }),
      });
      setDirectiveText("");
      beginDurableMutation();  // 应用本变更响应前推进代次，作废在飞旧刷新（防旧 done 覆盖）
      setState((current) => (current ? { ...current, directives: data.directives } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const toggleFavorite = async (minister: Minister) => {
    setBusy(minister.favorite ? "移出收藏" : "加入收藏");
    setError("");
    try {
      await api<{ favorites: string[] }>(`/api/favorites/${encodeURIComponent(minister.name)}`, {
        method: minister.favorite ? "DELETE" : "POST",
      });
      await loadState();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const startEditDirective = (directive: Directive) => {
    setEditingDirectiveId(directive.id);
    setEditingDirectiveText(directive.text);
  };

  const cancelEditDirective = () => {
    setEditingDirectiveId(null);
    setEditingDirectiveText("");
  };

  const saveDirective = async (directive: Directive) => {
    if (!editingDirectiveText.trim()) return;
    setBusy("修改草案");
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>(`/api/directives/${directive.id}`, {
        method: "PATCH",
        body: JSON.stringify({ text: editingDirectiveText.trim() }),
      });
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives } : current));
      cancelEditDirective();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const deleteDirective = async (directiveId: number) => {
    setBusy("删除草案");
    setError("");
    try {
      const data = await api<{ directives: Directive[] }>(`/api/directives/${directiveId}`, { method: "DELETE" });
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives } : current));
      if (editingDirectiveId === directiveId) {
        cancelEditDirective();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const confirmDirective = async (directiveId: number) => {
    setBusy("核定大臣拟旨");
    setError("");
    try {
      const data = await api<{ directives: Directive[]; pending_count: number }>(`/api/directives/${directiveId}/confirm`, { method: "POST" });
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const rejectDirective = async (directiveId: number) => {
    setBusy("驳回大臣拟旨");
    setError("");
    try {
      const data = await api<{ directives: Directive[]; pending_count: number }>(`/api/directives/${directiveId}/reject`, { method: "POST" });
      beginDurableMutation();
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const writeDecree = async () => {
    setBusy("拟写正式诏书");
    setError("");
    try {
      const data = await api<{ decree: string }>("/api/decree/write", { method: "POST" });
      setDecree(data.decree);
      // write_decree 内部会运行 commit_pending_actions，pending 随之消失；
      // 因此重新获取包含 directives / pending_directive_count 的完整 state。
      await loadState();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const advanceWithoutEdict = async () => {
    setBusy("退朝");
    setError("");
    try {
      const data = await api<{ state: GameState; pending_action_failures?: PendingActionFailure[] }>("/api/decree/advance_without_edict", { method: "POST" });
      if (await surfacePendingActionFailures(data.pending_action_failures || [])) {
        return;
      }
      window.location.reload();
    } catch (err: any) {
      const detail = err?.detail && typeof err.detail === "object" ? err.detail : err;
      const failures = detail?.pending_action_failures;
      if (Array.isArray(failures) && await surfacePendingActionFailures(failures)) {
        setError(detail?.message || "退朝失败。");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const resetDecree = () => {
    // 返工：丢弃当前诏文回到御案理政幕。后端旧诏文留着无妨，重新生成即覆盖。
    setDecree("");
    setError("");
  };

  // 颁诏/续裁共用：消费 SSE 推演流，stage/thinking/text 实时更新进度区，
  // 返回结束态：done（已结算）/ decisions（暂停待裁）/ error。
  const consumeSettleStream = async (
    response: Response
  ): Promise<{ kind: "done" | "decisions" | "error"; data: any }> => {
    if (!response.ok || !response.body) {
      throw new Error(`颁诏失败：HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done: streamDone } = await reader.read();
      if (streamDone) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() || "";
      for (const block of blocks) {
        let evName = "";
        let dataRaw = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) evName = line.slice(7).trim();
          else if (line.startsWith("data: ")) dataRaw += line.slice(6);
        }
        if (!evName || !dataRaw) continue;
        let data: any = {};
        try { data = JSON.parse(dataRaw); } catch { continue; }
        if (evName === "stage") setSettleStage(data.content || "");
        else if (evName === "thinking") setSettleThinking((prev) => prev + (data.content || ""));
        else if (evName === "text") setSettleNarrative((prev) => prev + (data.content || ""));
        else if (evName === "error") return { kind: "error", data };
        else if (evName === "decisions") return { kind: "decisions", data };
        else if (evName === "done") return { kind: "done", data };
      }
    }
    return { kind: "error", data: "推演流意外中断。" };
  };

  const issueDecree = async () => {
    setBusy("月末结算");
    setSettleStage("");
    setSettleThinking("");
    setSettleNarrative("");
    setError("");
    try {
      // 作弊强制结算项随颁诏一次性穿入；发出即清空，绝不跨回合。
      const cheatPayload = cheatDirective.trim();
      const response = await fetch("/api/decree/issue/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cheat: cheatPayload }),
      });
      if (cheatPayload) {
        setCheatDirective("");
      }
      const outcome = await consumeSettleStream(response);
      if (outcome.kind === "error") {
        if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
          setError(typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "颁诏失败。"));
          return;
        }
        setError(typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "颁诏失败。"));
        setBusy("");
        return;
      }
      if (outcome.kind === "decisions") {
        // 出重大抉择：暂停弹窗逐个亲裁，裁完调 submitDecisions 续跑结算。
        const failures = outcome.data?.pending_action_failures || [];
        setDecisionFailures(failures);
        const route = routeIssueDecisions(outcome.data.decisions || []);
        if (route.pendingDecisions !== null) setPendingDecisions(route.pendingDecisions);
        if (route.error !== null) setPausedDecisionError(route.error);
        setBusy("");
        return;
      }
      await forwardSteamEvents(outcome.data);
      if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
        return;
      }
      // 结算完成：强制整页刷新，草案/对话/局势/closed 弹窗全部按新 state 重新初始化
      window.location.reload();
      return;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy("");
    }
  };

  const retryPendingDecisions = async () => {
    setBusy("重新拉取批红");
    setPausedDecisionError("");
    try {
      const freshState = await loadState();
      if (!freshState) return;  // 陈旧代次被协调器拒收（返 null）→ 拒收陈旧 cargo，不据此路由决策
      const route = routeRetryDecisions(freshState.turn.phase, freshState.pending_decisions || []);
      if (route.pendingDecisions !== null) setPendingDecisions(route.pendingDecisions);
      if (route.error !== null) setPausedDecisionError(route.error);
    } catch (err) {
      setPausedDecisionError(`重新拉取待批决策失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy("");
    }
  };

  // 皇帝亲裁完所有决策点：续跑 phase2 结算。choices 按决策点 idx 顺序。
  const submitDecisions = async (choices: { label?: string; hint?: string; note?: string }[]) => {
    setPendingDecisions([]);
    setDecisionFailures([]);
    setBusy("月末结算");
    setSettleStage("圣意亲裁，续推时局");
    setSettleThinking("");
    setSettleNarrative("");
    setError("");
    try {
      const response = await fetch("/api/decree/resolve_decisions/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choices }),
      });
      const outcome = await consumeSettleStream(response);
      if (outcome.kind === "error") {
        if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
          setError(typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "结算失败。"));
          return;
        }
        setError(typeof outcome.data === "string" ? outcome.data : (outcome.data.message || "结算失败。"));
        setBusy("");
        return;
      }
      await forwardSteamEvents(outcome.data);
      if (await surfacePendingActionFailures(outcome.data?.pending_action_failures || [])) {
        return;
      }
      window.location.reload();
      return;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy("");
    }
  };

  const settling = busy === "月末结算";
  const guardClose = (fn: () => void) => () => {
    if (settling) return;
    fn();
  };

  const activeDrawerKey =
    drawerOpen ? "court" :
    haremDrawerOpen ? "harem" :
    armyDrawerOpen ? "army" :
    regionDrawerOpen ? "region" :
    buildingDrawerOpen ? "building" :
    economyDrawerOpen ? "economy" :
    appointmentDrawerOpen ? "appointment" : "";
  const navHandlers = {
    court: () => setDrawerOpen((v) => !v),
    harem: () => setHaremDrawerOpen((v) => !v),
    army: () => setArmyDrawerOpen((v) => !v),
    region: () => setRegionDrawerOpen((v) => !v),
    building: () => setBuildingDrawerOpen((v) => !v),
    economy: () => setEconomyDrawerOpen((v) => !v),
    appointment: () => setAppointmentDrawerOpen((v) => !v),
    goal: () => setActiveModal("long_goals"),
  };
  const sz = hudStageSize;
  const ready = sz.w > 0 && sz.h > 0;

  return (
    <main className="game-shell">
      <div className="hud2-stage" ref={hudStageCbRef}>
        <img className="hud2-bg" src={HUD_BG} alt="" />

        {/* 地图：透视梯形（GrandMap 已改 transform pan，兼容 matrix3d）。?flat=1 关透视调试 */}
        {ready ? (
          (typeof window !== "undefined" && new URLSearchParams(window.location.search).has("flat")) ? (
            <div className="hud2-map-quad" style={{
              position: "absolute",
              left: `${HUD_SLOTS.地图四角.tl[0]}%`, top: `${HUD_SLOTS.地图四角.tl[1]}%`,
              width: `${HUD_SLOTS.地图四角.tr[0] - HUD_SLOTS.地图四角.tl[0]}%`,
              height: `${HUD_SLOTS.地图四角.bl[1] - HUD_SLOTS.地图四角.tl[1]}%`,
            }}>
              <GrandMap nodes={mapNodes} selectedId={mapIntelOpen ? selectedNode?.id || "" : ""} onSelect={selectMapNode} />
            </div>
          ) : (
            <QuadFrame className="hud2-map-quad" quad={HUD_SLOTS.地图四角}
              stageW={sz.w} stageH={sz.h} baseW={2560} baseH={1440}>
              <GrandMap nodes={mapNodes} selectedId={mapIntelOpen ? selectedNode?.id || "" : ""} onSelect={selectMapNode} />
            </QuadFrame>
          )
        ) : null}

        {/* 局势进度：塞进左卡透视梯形 */}
        {ready ? (
          <QuadFrame className="hud2-issue-quad" quad={HUD_SLOTS.局势四角}
            stageW={sz.w} stageH={sz.h} baseW={2560} baseH={1440}>
            <SituationPanel
              issues={state.issues}
              closedIssues={state.closed_this_turn || []}
              hasLegacies={(state.legacies || []).length > 0}
            />
          </QuadFrame>
        ) : null}

        {/* 顶栏：年月 + 国库/内库 + 民心/皇威，各按坑位绝对定位 */}
        <button className="hud2-slot hud2-year" style={HUD_SLOTS.顶栏.年月}
          onClick={() => setActiveModal("state")}>
          <span className="hud2-lab">大明</span>
          <span className="hud2-val">{state.turn.year} 年 {state.turn.period} 月</span>
        </button>
        <div className="hud2-slot" style={HUD_SLOTS.顶栏.国库}>
          <BudgetHover accountName="国库" budget={state.budget["国库"]} />
        </div>
        <div className="hud2-slot" style={HUD_SLOTS.顶栏.内库}>
          <BudgetHover accountName="内库" budget={state.budget["内库"]} />
        </div>
        <div className="hud2-slot hud2-metric-pair" style={HUD_SLOTS.顶栏.民心}>
          <span className={`hud2-metric-one ${scoreTone(state.metrics["民心"], false)}`}>
            <span className="hud2-lab">民心</span><span className="hud2-val">{state.metrics["民心"]}</span>
          </span>
          <span className={`hud2-metric-one ${scoreTone(state.metrics["皇威"], false)}`}>
            <span className="hud2-lab">皇威</span><span className="hud2-val">{state.metrics["皇威"]}</span>
          </span>
        </div>
        <div className="hud2-slot hud2-legacy-slot" style={HUD_SLOTS.顶栏.皇威}>
          <LegacyBar legacies={state.legacies} />
        </div>
        <button className="hud2-menu-btn"
          title="游戏菜单" aria-label="游戏菜单" onClick={() => setActiveModal("menu")}>
          <span className="hud2-val">菜单</span>
        </button>

        {/* 右侧竖排部院导航 */}
        {([
          ["政", "court", "朝堂·召见大臣"],
          ["吏", "appointment", "官员任免"],
          ["省", "region", "省份列表"],
          ["兵", "army", "军队列表"],
          ["户", "economy", "经济面板"],
          ["工", "building", "建筑列表"],
          ["礼", "court", "礼部"],
          ["后", "harem", "后宫"],
          ["目", "goal", "长期目标"],
        ] as const).map(([label, key, title], idx) => {
          const slotKey = (["政","吏部","省份","兵部","户部","工部","礼部","后宫","目标"] as const)[idx];
          return (
            <button key={slotKey} className={`hud2-slot hud2-nav${activeDrawerKey === key ? " active" : ""}`}
              style={HUD_SLOTS.导航[slotKey]} title={title} aria-label={title}
              onClick={(navHandlers as any)[key]}>
              {label}
            </button>
          );
        })}

        {/* 底部 5 命令物件（扣图填进木牌） */}
        <CommandSlot slotKey="奏疏" img="奏疏" badge={state.events.length}
          caption="奏疏" sub={`${state.events.length} 件待览`} onClick={() => setActiveModal("state")} />
        <CommandSlot slotKey="邸报" img="邸报"
          caption="起居注" sub="历次召对记录" onClick={() => setActiveModal("audience_archive")} />
        <CommandSlot slotKey="密令" img="密令"
          badge={secretOrders.filter((o) => o.status === "active" || o.status === "pending_review").length}
          caption="密令" sub="进行中密令" onClick={() => setActiveModal("secret_orders")} />
        <CommandSlot slotKey="史册" img="史册"
          caption="史册" sub="历代奏报/诏书" onClick={() => setActiveModal("history")} />
        <CommandSlot slotKey="拟诏" img="拟诏" badge={state.directives.length}
          caption="拟诏/结束回合" sub={state.directives.length ? `${state.directives.length} 道` : "本回合"}
          onClick={() => setActiveModal("edict")} />
      </div>

      <CourtDrawer
        state={state}
        ministers={ministers}
        ministerGroup={ministerGroup}
        selectedMinister={selectedMinister}
        open={drawerOpen}
        onGroupChange={setMinisterGroup}
        onClose={guardClose(() => setDrawerOpen(false))}
        onOpenChat={openChat}
        onUploadPortrait={uploadPortrait}
      />

      <HaremDrawer
        consorts={consorts}
        haremGroup={haremGroup}
        selectedMinister={selectedMinister}
        open={haremDrawerOpen}
        onGroupChange={setHaremGroup}
        onClose={guardClose(() => setHaremDrawerOpen(false))}
        onOpenChat={openChat}
        onUploadPortrait={uploadPortrait}
      />

      <ArmyDrawer
        armies={state.armies}
        open={armyDrawerOpen}
        selectedArmyId={selectedArmyId}
        onSelectArmy={setSelectedArmyId}
        onClose={guardClose(() => setArmyDrawerOpen(false))}
      />

      <RegionDrawer
        regions={state.regions}
        open={regionDrawerOpen}
        selectedRegionId={selectedRegionId}
        onSelectRegion={setSelectedRegionId}
        onClose={guardClose(() => setRegionDrawerOpen(false))}
      />

      <BuildingDrawer
        regions={state.regions}
        mapNodes={mapNodes}
        open={buildingDrawerOpen}
        onClose={guardClose(() => setBuildingDrawerOpen(false))}
      />

      <EconomyDrawer
        state={state}
        open={economyDrawerOpen}
        onClose={guardClose(() => setEconomyDrawerOpen(false))}
      />

      <AppointmentDrawer
        ministers={state.ministers}
        open={appointmentDrawerOpen}
        onOpenChat={openChat}
        onClose={guardClose(() => setAppointmentDrawerOpen(false))}
      />

      {mapIntelOpen && selectedNode ? (
        <section className="map-intel-panel overlay-panel" style={mapIntelStyle}>
          <button className="icon-button panel-close" aria-label="关闭地区详情" onClick={() => setMapIntelOpen(false)}>
            <X size={16} />
          </button>
          <NodeIntel node={selectedNode} />
        </section>
      ) : null}

      {activeModal === "state" ? (
        <FullscreenModal title="国势与奏报" subtitle={`${state.turn.year} 年 ${state.turn.period} 月`} bgClass="modal-bg-state" onClose={guardClose(() => setActiveModal("none"))}>
          <StateModal state={state} />
        </FullscreenModal>
      ) : null}

      {activeModal === "long_goals" ? (
        <LongGoalsModal onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "chat" && activeMinister ? (
        <FullscreenModal title={`召对：${activeMinister.name}`} subtitle={activeMinister.office} bgClass="modal-bg-chat" onClose={guardClose(() => setActiveModal("none"))}>
          <ChatModal
            minister={activeMinister}
            ministers={audienceRoster}
            portraitPrefix={(state.consorts || []).some((c) => c.name === activeMinister.name) ? "consort_" : "minister_"}
            scrollMode={(state.consorts || []).some((c) => c.name === activeMinister.name) ? "legacy" : "audience"}
            currentCampaignId={currentCampaignId}
            currentNightId={currentNightId}
            undoneChatIdentity={undoneChatIdentity}
            chat={chat}
            suggestions={suggestions}
            pendingUserMessage={pendingUserMessage}
            pendingIdentity={pendingIdentity}
            failedIdentity={failedIdentity}
            scrollGeneration={audienceScrollGeneration}
            streamingMinisterMessage={streamingMinisterMessage}
            chatNotice={chatNotice}
            chatFailures={activeChatFailures}
            canUndoLastChat={canUndoLastChat}
            composerHint={composerHint}
            input={input}
            busy={busy}
            error={error}
            secretOrders={secretOrders.filter((o) => o.minister_name === activeMinister.name && (o.status === "active" || o.status === "pending_review"))}
            replyRetry={replyRetry}
            extractionPendingCount={extractionPendingCount}
            onInput={setInput}
            onSend={sendChat}
            onRetryFailure={retryPendingAction}
            onRetryReply={retryInterruptedReply}
            onRetryExtraction={retryStoryExtraction}
            onUndo={undoLastChat}
            onHint={setComposerHint}
            onFavorite={() => toggleFavorite(activeMinister)}
            onOpenEdict={() => setActiveModal("edict")}
            onClose={guardClose(() => setActiveModal("none"))}
            onCancel={cancelChat}
          />
        </FullscreenModal>
      ) : null}

      {activeModal === "chat" && !activeMinister && failureRecoveryMode && chatFailures.length ? (
        <FullscreenModal title="政务失败恢复" subtitle="承办人暂不可召见" bgClass="modal-bg-chat" onClose={guardClose(() => setActiveModal("none"))}>
          <PendingFailureRecoveryPanel
            failures={chatFailures}
            busy={busy}
            error={error}
            onRetryFailure={retryPendingAction}
          />
        </FullscreenModal>
      ) : null}

      {activeModal === "edict" ? (
        <FullscreenModal title="诏书草案" subtitle="本月指令、拟诏与颁布" bgClass="modal-bg-edict" onClose={guardClose(() => setActiveModal("none"))}>
          <EdictModal
            state={state}
            directiveText={directiveText}
            editingDirectiveId={editingDirectiveId}
            editingDirectiveText={editingDirectiveText}
            decree={decree}
            report={report}
            busy={busy}
            error={error}
            onDirectiveTextChange={setDirectiveText}
            onEditingTextChange={setEditingDirectiveText}
            onCreateDirective={createDirective}
            onStartEdit={startEditDirective}
            onCancelEdit={cancelEditDirective}
            onSaveDirective={saveDirective}
            onDeleteDirective={deleteDirective}
            onWriteDecree={writeDecree}
            onAdvanceWithoutEdict={advanceWithoutEdict}
            onResetDecree={resetDecree}
            onIssueDecree={issueDecree}
            onConfirmDirective={confirmDirective}
            onRejectDirective={rejectDirective}
            onOpenFailureRecovery={openFailureRecovery}
          />
        </FullscreenModal>
      ) : null}

      {activeModal === "report" && (gazetteReport || report) ? (
        <ReportModal
          report={gazetteReport || report}
          onClose={guardClose(() => setActiveModal("none"))}
        />
      ) : null}

      {activeModal === "ending" && state.ending ? (
        <EndingModal ending={state.ending} onClose={() => { setEndingDismissed(true); setActiveModal("none"); }} />
      ) : null}

      {activeModal === "history" ? (
        <HistoryModal ministers={audienceRoster} onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "audience_archive" ? (
        <AudienceArchiveModal onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "menu" ? (
        <GameMenuModal
          onClose={guardClose(() => setActiveModal("none"))}
          onAfterLoad={() => {
            setActiveModal("none");
            window.location.reload();
          }}
          onExitToMenu={async () => {
            await exitToMenu();
            setActiveModal("none");
          }}
        />
      ) : null}

      {closedModal.length ? (
        <ClosedIssuesModal items={closedModal} onClose={() => setClosedModal([])} />
      ) : null}

      {activeModal === "secret_orders" ? (
        <SecretOrdersModal
          orders={secretOrders}
          onClose={() => setActiveModal("none")}
          onOpenMinister={(name) => {
            setActiveModal("chat");
            setSelectedMinister(name);
          }}
        />
      ) : null}

      {settling ? (
        <SettlementLock
          stage={settleStage}
          thinking={settleThinking}
          narrative={settleNarrative}
        />
      ) : null}

      {/* 恢复入口（ship-pre r4）：崩溃/中止后重载时相位停在 settling——last_decree 已被
          begin_turn 清空、盖玺按钮藏在非空诏文之后、write_decree 又拒恢复态，没有这个
          按钮 web 玩家永远够不到 resolve_turn 的恢复分流（重放/重新推演由后端自行分辨）。 */}
      {!settling && state.turn.phase === "settling" ? (
        <div className="recovery-banner">
          <span>上月结算未完成（进度已保存）。</span>
          <button className="seal-btn-issue" onClick={issueDecree} disabled={!!busy}>
            续跑结算
          </button>
        </div>
      ) : null}

      {!settling && pausedDecisionError ? (
        <DecisionRecoveryPanel
          message={pausedDecisionError}
          busy={busy}
          onRetry={retryPendingDecisions}
        />
      ) : null}

      {cheatOpen ? (
        <CheatConsole
          directive={cheatDirective}
          onCommit={setCheatDirective}
          onClose={() => setCheatOpen(false)}
        />
      ) : null}

      {pendingDecisions.length > 0 && !settling ? (
        <DecisionModal decisions={pendingDecisions} failures={decisionFailures} onResolve={submitDecisions} />
      ) : null}
    </main>
  );
}


function PendingFailureRecoveryPanel({
  failures,
  busy,
  error,
  onRetryFailure,
}: {
  failures: PendingActionFailure[];
  busy: string;
  error: string;
  onRetryFailure: (failure: PendingActionFailure) => void;
}) {
  return (
    <div className="failure-recovery-panel">
      {error ? <div className="error-line" role="alert">{error}</div> : null}
      {failures.map((failure) => (
        <div className="failure-recovery-item" role="alert" key={failure.id}>
          <div>
            {failure.minister_name ? (
              <span className="failure-recovery-minister">{failure.minister_name}</span>
            ) : null}
            <span>{failure.message}</span>
          </div>
          {failure.retryable ? (
            <button type="button" onClick={() => onRetryFailure(failure)} disabled={!!busy}>
              重试
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}


// HITL 重大抉择弹窗：逐个亲裁本回合决策点，全部选完一次提交续跑结算。
// 每个决策：标题 + 背景 + 2-3 预设选项（点选）+ 朱批输入框（可补自由旨意）。
// 作弊控制台：terminal UI。强制结算唯一入口（Ctrl+~ 唤出）。输入的指令暂存于
// cheatDirective，下次颁诏时随结算穿入 extractor 当既成事实落库。
function CheatConsole({
  directive,
  onCommit,
  onClose,
}: {
  directive: string;
  onCommit: (text: string) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = React.useState("");
  const [history, setHistory] = React.useState<string[]>([]);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    inputRef.current?.focus();
  }, []);
  React.useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [history]);

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    onCommit(text);
    setHistory((h) => [...h, `> ${text}`, "  已挂载强制结算项，下次颁诏随结算生效（一次性）。"]);
    setDraft("");
  };

  const clearMounted = () => {
    onCommit("");
    setHistory((h) => [...h, "  已清空强制结算项。"]);
  };

  return (
    <div className="cheat-console" role="dialog" aria-label="天命控制台" onClick={onClose}>
      <div className="cheat-console-window" onClick={(e) => e.stopPropagation()}>
        <div className="cheat-console-titlebar">
          <span>tianming@ming-salvage:~$ 天命控制台</span>
          <button className="cheat-console-x" onClick={onClose} aria-label="关闭">×</button>
        </div>
        <div className="cheat-console-body" ref={bodyRef}>
          <div className="cheat-console-line cheat-console-dim">
            强制结算控制台。输入的指令将在下次颁诏时作为「既成事实」穿入结算，无视合理性与史实。
          </div>
          <div className="cheat-console-line cheat-console-dim">
            Enter 提交 · Shift+Enter 换行 · Ctrl+~ 关闭
          </div>
          {directive ? (
            <div className="cheat-console-line cheat-console-armed">
              ● 当前已挂载：{directive}
            </div>
          ) : (
            <div className="cheat-console-line cheat-console-dim">○ 当前无挂载项</div>
          )}
          {history.map((line, i) => (
            <div className="cheat-console-line" key={i}>{line}</div>
          ))}
        </div>
        <div className="cheat-console-prompt">
          <span className="cheat-console-caret">&gt;</span>
          <textarea
            ref={inputRef}
            className="cheat-console-input"
            value={draft}
            rows={1}
            placeholder="例：国库增至九千万两，后金军覆灭，皇太极暴毙"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
        </div>
        <div className="cheat-console-actions">
          <button className="cheat-console-btn" onClick={submit}>挂载</button>
          <button className="cheat-console-btn cheat-console-btn-ghost" onClick={clearMounted}>清空挂载</button>
        </div>
      </div>
    </div>
  );
}

function SettlementLock({
  stage,
  thinking,
  narrative,
}: {
  stage: string;
  thinking: string;
  narrative: string;
}) {
  const thinkRef = React.useRef<HTMLDivElement>(null);
  const narrRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    const block = (event: KeyboardEvent) => {
      event.preventDefault();
      event.stopPropagation();
    };
    window.addEventListener("keydown", block, true);
    return () => window.removeEventListener("keydown", block, true);
  }, []);
  // 流式内容到达时自动滚到底
  React.useEffect(() => {
    if (thinkRef.current) thinkRef.current.scrollTop = thinkRef.current.scrollHeight;
  }, [thinking]);
  React.useEffect(() => {
    if (narrRef.current) narrRef.current.scrollTop = narrRef.current.scrollHeight;
  }, [narrative]);
  return (
    <div className="settlement-lock" role="alertdialog" aria-modal="true" aria-label="月末结算">
      <div className="settlement-lock-card">
        <Loader2 className="settlement-spin" size={28} />
        <h2>月末结算中</h2>
        <p>{stage === "数值推演结算" ? "档房核账中，钱粮、地方、军务落账，请稍候。" : stage ? `当前：${stage}` : "朝廷推演钱粮、地方、军务，请勿操作。"}</p>
        {thinking && (
          <div className="settlement-stream-block">
            <div className="settlement-stream-label">邸报房推敲</div>
            <div className="settlement-stream-text settlement-thinking" ref={thinkRef}>
              {thinking}
            </div>
          </div>
        )}
        {narrative && (
          <div className="settlement-stream-block">
            <div className="settlement-stream-label">月末奏章</div>
            <div className="settlement-stream-text settlement-narrative" ref={narrRef}>
              {narrative}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// 仅在真实浏览器（存在 #root）自动挂载；测试可 import { App } 挂载真实组件走生产 wiring。
const rootEl = typeof document !== "undefined" ? document.getElementById("root") : null;
if (rootEl) createRoot(rootEl).render(<App />);
