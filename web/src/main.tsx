import React from "react";
import { createRoot } from "react-dom/client";
import { Crown, X } from "lucide-react";
import { api } from "./api";
import { useAudienceChat } from "./useAudienceChat";
import { useDurableProjection } from "./useDurableProjection";
import { useEscClose } from "./useEscClose";
import { useEdictActions } from "./useEdictActions";
import { useSettlementFlow } from "./useSettlementFlow";
import { useChatActions } from "./useChatActions";
import { AppointmentDrawer, ArmyDrawer, BuildingDrawer, CourtDrawer, EconomyDrawer, HaremDrawer, RegionDrawer } from "./components/drawers";
import { GameMenuModal } from "./components/gameMenu";
import { FullscreenModal } from "./components/hud";
import { GameHud } from "./components/gameHud";
import { NodeIntel } from "./components/map";
import { MenuPage } from "./components/menuPage";
import { AudienceArchiveModal } from "./components/audienceArchiveModal";
import { ChatModal } from "./components/chatModal";
import { CheatConsole, useCheatHotkey } from "./components/cheatConsole";
import { ClosedIssuesModal } from "./components/closedIssues";
import { EdictModal } from "./components/edictModal";
import { EndingModal } from "./components/endingModal";
import { HistoryModal } from "./components/historyModal";
import { PendingFailureRecoveryPanel } from "./components/pendingFailureRecovery";
import { ReportModal } from "./components/reportModal";
import { SecretOrdersModal } from "./components/secretOrders";
import { SettlementLock } from "./components/settlementLock";
import { StateModal } from "./components/stateModal";
import { filterConsorts, filterMinisters } from "./components/ministerFilters";
import { DecisionModal } from "./components/decisionModal";
import { DecisionRecoveryPanel } from "./components/decisionRecovery";
import { needsPhase2Resume } from "./decisionRouting";
import { getMapIntelStyle, refreshLabelMaps } from "./format";
import {
  isFaceReachable,
  isSettlementDisplay,
  settlementClosedReason,
  shouldAutoOpenClosedIssuesAfterSettlement,
  shouldAutoOpenSecretOrdersAfterSettlement,
} from "./settlementPresentation";
import type { AppView, ChatIdentity, ClosedIssue, GameState, MenuStatus, Minister, ModalName, SecretOrder } from "./types";
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
  const [activeModal, setActiveModal] = React.useState<ModalName>("none");
  const [decree, setDecree] = React.useState("");
  const [report, setReport] = React.useState("");
  const [gazetteReport, setGazetteReport] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
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
  // 作弊控制台（Ctrl+~）：cheatDirective 暂存强制结算项，下次颁诏随结算一次性穿入。
  const [cheatOpen, setCheatOpen] = React.useState(false);
  const [cheatDirective, setCheatDirective] = React.useState("");

  // Tracks the current selected minister across async boundaries.
  // State closures capture stale values; this ref always reflects the latest.
  const selectedMinisterRef = React.useRef<string>("");
  const suppressNextReportRef = React.useRef(false);
  const [undoneChatIdentity, setUndoneChatIdentity] = React.useState<ChatIdentity | null>(null);
  const [audienceScrollGeneration, setAudienceScrollGeneration] = React.useState(0);
  const audienceScrollPositionsRef = React.useRef(new Map<string, number>());
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

  // 召对动作群（useChatActions.ts）：召对面板外围态 + 开召对/发问/撤回/重试/失败恢复。
  // 须在 useSettlementFlow 之前调用——结算流的 surfacePendingActionFailures 由这里直供。
  const {
    suggestions,
    chatNotice,
    chatFailures,
    activeChatFailures,
    replyRetry,
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
    retryPendingAction,
    openFailureRecovery,
    surfacePendingActionFailures,
  } = useChatActions({
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
  });

  // 诏书台动作群（useEdictActions.ts）：草案/诏文的全部 busy 动作与代次推进。
  const {
    directiveText,
    editingDirectiveId,
    editingDirectiveText,
    setDirectiveText,
    setEditingDirectiveText,
    createDirective,
    startEditDirective,
    cancelEditDirective,
    saveDirective,
    deleteDirective,
  } = useEdictActions({ setBusy, setError, setState, beginDurableMutation });

  // 颁诏结算流（useSettlementFlow.ts）：盖玺颁诏/HITL 决策点续裁/失败重拉。
  // hook 必须在 menu/loading 早退之前调用。
  const {
    settleStage,
    settleThinking,
    settleNarrative,
    pendingDecisions,
    decisionFailures,
    pausedDecisionError,
    issueDecree,
    submitDecisions,
    resumePhase2,
    retryPendingDecisions,
  } = useSettlementFlow({
    setBusy,
    setError,
    cheatDirective,
    setCheatDirective,
    loadState,
    surfacePendingActionFailures,
    state,
  });


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
    // #1236：上月已结属只读组——自动弹窗亦吃 isFaceReachable（与 FACE_GROUP 同口径）。
    if (
      closed.length
      && currentTurn !== closedShown
      && shouldAutoOpenClosedIssuesAfterSettlement()
      && isFaceReachable("closed_issues", isSettlementDisplay(state.turn))
    ) {
      setClosedModal(closed);
      setClosedShown(currentTurn);
      sessionStorage.setItem("closedShownTurn", String(currentTurn));
    }
  }, [state, closedShown]);

  // 新回合进入时拉取全部密令，有 active 密令则弹密令进度弹窗（邸报关闭后显示）。
  // #499：密令重取经唯一 latest-wins 协调器 refresh，与 done/撤回共享代次——旧回合的密令
  // 响应迟到不覆盖新结果。shown 标记只在**接受成功后**（onSecretOrders 内）落，取失败可重试；
  // 延迟弹窗在触发时按 isLatest 门控，撤回等推进代次后陈旧定时器 no-op（不会弹已作废的窗）。
  // #1236：密令属关闭组——核账展示态下不自动弹出（角标亦在 HUD 清零）。
  React.useEffect(() => {
    if (!state) return;
    const currentTurn = state.turn.turn;
    if (currentTurn === secretOrderShown) return;
    const settlementDisplay = isSettlementDisplay(state.turn);
    void refreshDurableProjection({
      secretOrders: true,
      onSecretOrders: () => setSecretOrderShown(currentTurn),  // 仅接受成功（最新代次）才标记已呈现
      // 延迟呈现归协调器：400ms 后仍最新代次才弹窗；撤回等推进代次后陈旧定时器 no-op。
      autoOpen: {
        afterMs: 400,
        when: (orders) =>
          isFaceReachable("secret_orders", settlementDisplay)
          && shouldAutoOpenSecretOrdersAfterSettlement(orders, currentTurn),
        open: () => setActiveModal("secret_orders"),
      },
    });
  }, [state?.turn.turn, state?.turn.settlement_display]);

  // 结局已触发：每次进页面/刷新都自动弹结局结算页。玩家点关闭后（endingDismissed）
  // 本次加载让位给盘面/邸报，可继续看局；刷新即复位重弹。
  React.useEffect(() => {
    if (!state || !state.ending) return;
    if (endingDismissed) return;
    setActiveModal("ending");
  }, [state, endingDismissed]);

  // 每次进入页面/换回合都弹上回合邸报。不持久化记录——刷新即重新弹。
  // 同一加载周期内同一回合不重复弹（gazetteShown 用 React state，刷新后回到 -1）。
  // #1236：邸报(gazette) 属只读组——自动弹出与渲染同吃 isFaceReachable（无第二真源）。
  React.useEffect(() => {
    if (!state) return;
    // 结局页未关掉时让位给它；玩家关掉后（endingDismissed）邸报照常。
    if (state.ending && !endingDismissed) return;
    const currentTurn = state.turn.turn;
    // #1356/#671：t0 双空不自动弹；有邸报或独立递话任一即弹。空壳仍可由木牌打开。
    // trim 只做空壳门；写入 state 的是未 trim 原文（P6）
    const hasReport = Boolean((state.previous_summary || "").trim());
    const hasAttendant = Boolean((state.last_attendant_message || "").trim());
    if (!hasReport && !hasAttendant) return;
    if (currentTurn === gazetteShown) return;
    if (!isFaceReachable("gazette", isSettlementDisplay(state.turn))) return;
    if (suppressNextReportRef.current) {
      suppressNextReportRef.current = false;
      return;
    }
    setGazetteReport(state.previous_summary || "");
    setActiveModal("report");
    setGazetteShown(currentTurn);
  }, [state, gazetteShown, endingDismissed, activeModal]);

  React.useEffect(() => {
    selectedMinisterRef.current = selectedMinister;
  }, [selectedMinister]);

  // 全局 ESC：按 z-index 优先级，最前面的弹窗先关。
  // ending 须同时 setEndingDismissed，否则自动重开 effect 会立刻弹回。
  useEscClose(activeModal, setActiveModal, [
    { open: activeModal === "ending", close: () => { setEndingDismissed(true); setActiveModal("none"); } },
    { open: drawerOpen, close: () => setDrawerOpen(false) },
    { open: haremDrawerOpen, close: () => setHaremDrawerOpen(false) },
    { open: armyDrawerOpen, close: () => setArmyDrawerOpen(false) },
    { open: regionDrawerOpen, close: () => setRegionDrawerOpen(false) },
    { open: buildingDrawerOpen, close: () => setBuildingDrawerOpen(false) },
    { open: economyDrawerOpen, close: () => setEconomyDrawerOpen(false) },
    { open: appointmentDrawerOpen, close: () => setAppointmentDrawerOpen(false) },
    { open: mapIntelOpen, close: () => setMapIntelOpen(false) },
  ]);

  // 作弊控制台：Ctrl+~（或 Ctrl+`）切换显隐。强制结算唯一入口。
  useCheatHotkey(setCheatOpen);

  // #1236：关闭组面若仍挂着（刷新前已开），核账期强制收起，避免半程内容残留。
  // hooks 须在 early return 之前。关闭组成员固定，不经表查字面 true。
  const settlementDisplay = isSettlementDisplay(state?.turn);
  React.useEffect(() => {
    if (!settlementDisplay) return;
    setRegionDrawerOpen(false);
    setArmyDrawerOpen(false);
    setMapIntelOpen(false);
    if (activeModal === "secret_orders" || activeModal === "edict" || activeModal === "chat") {
      setActiveModal("none");
    }
  }, [settlementDisplay, activeModal]);

  // #1342：hooks 须在 early return 之前。开底部命令模态时收起全部抽屉。
  const closeAllDrawers = React.useCallback(() => {
    setDrawerOpen(false);
    setHaremDrawerOpen(false);
    setArmyDrawerOpen(false);
    setRegionDrawerOpen(false);
    setBuildingDrawerOpen(false);
    setEconomyDrawerOpen(false);
    setAppointmentDrawerOpen(false);
  }, []);
  const openModal = React.useCallback((modal: ModalName) => {
    closeAllDrawers();
    setMapIntelOpen(false);
    setActiveModal(modal);
  }, [closeAllDrawers]);

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
  const mapIntelStyle = selectedNode ? getMapIntelStyle(selectedNode) : undefined;

  const selectMapNode = (nodeId: string) => {
    // #1236：地图节点详情属关闭组——核账期不点选开详（底图装饰可留）。
    if (state && !isFaceReachable("node_intel", isSettlementDisplay(state.turn))) {
      setError(settlementClosedReason(state.turn.phase));
      return;
    }
    setSelectedNodeId(nodeId);
    setMapIntelOpen(true);
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

  // #1236：核账门控唯一谓词 = 状态口 settlement_display。
  // busy==="月末结算" 仅驱动同会话非权威装饰 SettlementLock，绝不充真源、不挡必达三面。
  const sessionSettlingBusy = busy === "月末结算";
  // 召对写入口属关闭组；名册抽屉仍只读可达。
  const chatEntryEnabled = isFaceReachable("chat_entry", settlementDisplay);

  const activeDrawerKey =
    drawerOpen ? "court" :
    haremDrawerOpen ? "harem" :
    armyDrawerOpen ? "army" :
    regionDrawerOpen ? "region" :
    buildingDrawerOpen ? "building" :
    economyDrawerOpen ? "economy" :
    appointmentDrawerOpen ? "appointment" : "";
  // #1305：nav 互斥——开一关一（同键再点则收起）。
  const navHandlers = {
    court: () => {
      const opening = !drawerOpen;
      closeAllDrawers();
      if (opening) setDrawerOpen(true);
    },
    harem: () => {
      const opening = !haremDrawerOpen;
      closeAllDrawers();
      if (opening) setHaremDrawerOpen(true);
    },
    army: () => {
      const opening = !armyDrawerOpen;
      closeAllDrawers();
      if (opening) setArmyDrawerOpen(true);
    },
    region: () => {
      const opening = !regionDrawerOpen;
      closeAllDrawers();
      if (opening) setRegionDrawerOpen(true);
    },
    building: () => {
      const opening = !buildingDrawerOpen;
      closeAllDrawers();
      if (opening) setBuildingDrawerOpen(true);
    },
    economy: () => {
      const opening = !economyDrawerOpen;
      closeAllDrawers();
      if (opening) setEconomyDrawerOpen(true);
    },
    appointment: () => {
      const opening = !appointmentDrawerOpen;
      closeAllDrawers();
      if (opening) setAppointmentDrawerOpen(true);
    },
  };
  const sz = hudStageSize;
  const ready = sz.w > 0 && sz.h > 0;

  // 关闭/只读模态：若 activeModal 被外路径设到不可达面，不渲染（逐 key 吃 isFaceReachable）。
  const secretOrdersOpen = activeModal === "secret_orders" && isFaceReachable("secret_orders", settlementDisplay);
  const edictOpen = activeModal === "edict" && isFaceReachable("edict", settlementDisplay);
  const chatOpen = activeModal === "chat" && isFaceReachable("chat_entry", settlementDisplay);
  const gazetteOpen = activeModal === "report" && isFaceReachable("gazette", settlementDisplay);
  // memorials 面键真源（#1285）；ModalName 仍用既有 "state" 槽承载奏疏列表。
  // 内容闸走 situation 谓词：核账期面可达但零半程议题泄漏（模态不自判 settlementDisplay）。
  const memorialsOpen = activeModal === "state" && isFaceReachable("memorials", settlementDisplay);
  const showMemorialIssues = isFaceReachable("situation", settlementDisplay);
  const historyOpen = activeModal === "history" && isFaceReachable("history", settlementDisplay);
  // C：起居注入口单闸 = isFaceReachable(audience_archive)；不再经 gameHud.gatedModal 死枝。
  const audienceArchiveOpen = activeModal === "audience_archive" && isFaceReachable("audience_archive", settlementDisplay);
  const closedIssuesOpen = closedModal.length > 0 && isFaceReachable("closed_issues", settlementDisplay);
  const mapIntelVisible = mapIntelOpen && selectedNode && isFaceReachable("node_intel", settlementDisplay);
  const regionOpen = regionDrawerOpen && isFaceReachable("region", settlementDisplay);
  const armyOpen = armyDrawerOpen && isFaceReachable("army", settlementDisplay);

  return (
    <main className="game-shell" data-settlement-display={settlementDisplay ? "1" : "0"}>
      <GameHud
        stageRef={hudStageCbRef}
        ready={ready}
        state={state}
        mapNodes={mapNodes}
        mapSelectedId={mapIntelVisible ? selectedNode?.id || "" : ""}
        onSelectMapNode={selectMapNode}
        activeDrawerKey={activeDrawerKey}
        navHandlers={navHandlers}
        secretOrderActiveCount={secretOrders.filter((o) => o.status === "active").length}
        onOpenModal={openModal}
        onClosedFaceAttempt={(reason) => setError(reason)}
        edictOpen={edictOpen}
        onCloseEdict={() => setActiveModal("none")}
      />

      <CourtDrawer
        state={state}
        ministers={ministers}
        ministerGroup={ministerGroup}
        selectedMinister={selectedMinister}
        open={drawerOpen}
        onGroupChange={setMinisterGroup}
        onClose={() => setDrawerOpen(false)}
        onOpenChat={openChat}
        onUploadPortrait={uploadPortrait}
        chatEntryEnabled={chatEntryEnabled}
      />

      <HaremDrawer
        consorts={consorts}
        haremGroup={haremGroup}
        selectedMinister={selectedMinister}
        open={haremDrawerOpen}
        onGroupChange={setHaremGroup}
        onClose={() => setHaremDrawerOpen(false)}
        onOpenChat={openChat}
        onUploadPortrait={uploadPortrait}
        chatEntryEnabled={chatEntryEnabled}
        phase={state.turn.phase}
      />

      <ArmyDrawer
        armies={state.armies}
        open={armyOpen}
        selectedArmyId={selectedArmyId}
        onSelectArmy={setSelectedArmyId}
        onClose={() => setArmyDrawerOpen(false)}
      />

      <RegionDrawer
        regions={state.regions}
        open={regionOpen}
        selectedRegionId={selectedRegionId}
        onSelectRegion={setSelectedRegionId}
        onClose={() => setRegionDrawerOpen(false)}
      />

      <BuildingDrawer
        regions={state.regions}
        mapNodes={mapNodes}
        open={buildingDrawerOpen}
        onClose={() => setBuildingDrawerOpen(false)}
      />

      <EconomyDrawer
        state={state}
        open={economyDrawerOpen}
        onClose={() => setEconomyDrawerOpen(false)}
      />

      <AppointmentDrawer
        ministers={state.ministers}
        open={appointmentDrawerOpen}
        onOpenChat={openChat}
        onClose={() => setAppointmentDrawerOpen(false)}
        chatEntryEnabled={chatEntryEnabled}
        phase={state.turn.phase}
      />

      {mapIntelVisible ? (
        <section className="map-intel-panel overlay-panel" style={mapIntelStyle}>
          <button className="icon-button panel-close" aria-label="关闭地区详情" onClick={() => setMapIntelOpen(false)}>
            <X size={16} />
          </button>
          <NodeIntel node={selectedNode} />
        </section>
      ) : null}

      {memorialsOpen ? (
        <FullscreenModal
          title="奏疏"
          subtitle={`${showMemorialIssues ? state.issues.length : 0} 件待览 · ${state.turn.year} 年 ${state.turn.period} 月`}
          bgClass="modal-bg-state"
          onClose={() => setActiveModal("none")}
        >
          <StateModal state={state} showIssues={showMemorialIssues} />
        </FullscreenModal>
      ) : null}

      {chatOpen && activeMinister ? (
        <FullscreenModal title={`召对：${activeMinister.name}`} subtitle={activeMinister.office} bgClass="modal-bg-chat" hideTitle onClose={() => setActiveModal("none")}>
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
            secretOrders={secretOrders.filter((o) => o.status === "active")}
            replyRetry={replyRetry}
            onInput={setInput}
            onSend={sendChat}
            onRetryFailure={retryPendingAction}
            onRetryReply={retryInterruptedReply}
            onUndo={undoLastChat}
            onHint={setComposerHint}
            onFavorite={toggleFavorite}
            scrollPosition={audienceScrollPositionsRef.current.get(`${currentCampaignId}:${currentNightId}`)}
            onScrollPositionChange={(position) => audienceScrollPositionsRef.current.set(`${currentCampaignId}:${currentNightId}`, position)}
            onClose={() => setActiveModal("none")}
            onCancel={cancelChat}
          />
        </FullscreenModal>
      ) : null}

      {chatOpen && !activeMinister && failureRecoveryMode && chatFailures.length ? (
        <FullscreenModal title="政务失败恢复" subtitle="承办人暂不可召见" bgClass="modal-bg-chat" onClose={() => setActiveModal("none")}>
          <PendingFailureRecoveryPanel
            failures={chatFailures}
            busy={busy}
            error={error}
            onRetryFailure={retryPendingAction}
          />
        </FullscreenModal>
      ) : null}

      {edictOpen ? (
        <FullscreenModal
          title="诏书草案"
          subtitle={(state.directives?.length ?? 0) > 0 ? "盖玺颁诏即草案成案并过月" : ""}
          bgClass="modal-bg-edict"
          // #1454：底栏安全区——desk-footer 不得挡 HUD 拟诏木牌（台开时为收起开关）。
          layerClassName="edict-safe-cmd"
          onClose={() => setActiveModal("none")}
        >
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
            onIssueDecree={issueDecree}
            onOpenFailureRecovery={openFailureRecovery}
          />
        </FullscreenModal>
      ) : null}

      {/* #1356：空 previous_summary 亦可开卷轴壳（木牌）；无固定空注 */}
      {gazetteOpen ? (
        <ReportModal
          report={gazetteReport || state.previous_summary || report || ""}
          attendantMessage={state.last_attendant_message || undefined}
          periodLabel={state.previous_reign_period_label || undefined}
          onClose={() => setActiveModal("none")}
        />
      ) : null}

      {activeModal === "ending" && state.ending ? (
        <EndingModal ending={state.ending} onClose={() => { setEndingDismissed(true); setActiveModal("none"); }} />
      ) : null}

      {historyOpen ? (
        <HistoryModal
          onClose={() => setActiveModal("none")}
          onOpenAudienceArchive={isFaceReachable("audience_archive", settlementDisplay)
            ? () => setActiveModal("audience_archive")
            : undefined}
        />
      ) : null}

      {audienceArchiveOpen ? (
        <AudienceArchiveModal ministers={audienceRoster} onClose={() => setActiveModal("none")} />
      ) : null}

      {activeModal === "menu" ? (
        <GameMenuModal
          onClose={() => setActiveModal("none")}
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

      {closedIssuesOpen ? (
        <ClosedIssuesModal items={closedModal} onClose={() => setClosedModal([])} />
      ) : null}

      {secretOrdersOpen ? (
        <SecretOrdersModal
          orders={secretOrders}
          onClose={() => setActiveModal("none")}
          onOpenMinister={(name) => {
            // 密令内转召对亦属 chat_entry 关闭组
            if (!chatEntryEnabled) {
              setError(settlementClosedReason(state?.turn.phase));
              return;
            }
            setActiveModal("chat");
            setSelectedMinister(name);
          }}
        />
      ) : null}

      {/* 同会话非权威装饰：不挡必达三面；刷新路径零依赖 */}
      {sessionSettlingBusy ? (
        <SettlementLock
          stage={settleStage}
          thinking={settleThinking}
          narrative={settleNarrative}
        />
      ) : null}

      {/* 必达：续跑入口仍挂既有 phase===settling（及 issueDecree 恢复分流）；展示态门控不误关。
          ship-pre r4：崩溃/中止后重载时相位停在 settling——last_decree 已被 begin_turn 清空。
          #1418 r2 / #657：all-decided 或 typed resume_phase2 → 同条续跑面，空 POST resolve_decisions/stream。 */}
      {state.turn.phase === "settling"
        || needsPhase2Resume(
          state.turn.phase,
          state.pending_decisions || [],
          state.turn.settlement_display,
          state.resume_phase2,
        )
        ? (
        <div className="recovery-banner" data-testid="settle-resume">
          <span>上月结算未完成（进度已保存）。</span>
          <button
            className="seal-btn-issue"
            onClick={
              needsPhase2Resume(
                state.turn.phase,
                state.pending_decisions || [],
                state.turn.settlement_display,
                state.resume_phase2,
              )
                ? resumePhase2
                : issueDecree
            }
            disabled={!!busy}
          >
            续跑结算
          </button>
        </div>
      ) : null}

      {/* 必达：批红恢复——不得被 busy/SettlementLock 误关 */}
      {pausedDecisionError ? (
        <div data-testid="decision-recovery">
          <DecisionRecoveryPanel
            message={pausedDecisionError}
            busy={sessionSettlingBusy ? "" : busy}
            onRetry={retryPendingDecisions}
          />
        </div>
      ) : null}

      {cheatOpen ? (
        <CheatConsole
          directive={cheatDirective}
          onCommit={setCheatDirective}
          onClose={() => setCheatOpen(false)}
        />
      ) : null}

      {/* 必达：DecisionModal——核账展示态门控不得盖住本面 */}
      {pendingDecisions.length > 0 ? (
        <div data-testid="decision-modal">
          <DecisionModal decisions={pendingDecisions} failures={decisionFailures} onResolve={submitDecisions} />
        </div>
      ) : null}
    </main>
  );
}

// 仅在真实浏览器（存在 #root）自动挂载；测试可 import { App } 挂载真实组件走生产 wiring。
const rootEl = typeof document !== "undefined" ? document.getElementById("root") : null;
if (rootEl) createRoot(rootEl).render(<App />);
