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
import { getMapIntelStyle, refreshLabelMaps } from "./format";
import { shouldAutoOpenClosedIssuesAfterSettlement, shouldAutoOpenSecretOrdersAfterSettlement } from "./settlementPresentation";
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
  const advanceWithoutEdictRef = React.useRef<() => Promise<void>>(async () => {});
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
    extractionPendingCount,
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
    advanceWithoutEdictRef,
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
  } = useEdictActions({ setBusy, setError, setState, beginDurableMutation, loadState, setDecree });

  // 颁诏结算流（useSettlementFlow.ts）：盖玺颁诏/退朝/HITL 决策点续裁/失败重拉。
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
    retryPendingDecisions,
    advanceWithoutEdict,
  } = useSettlementFlow({
    setBusy,
    setError,
    cheatDirective,
    setCheatDirective,
    loadState,
    surfacePendingActionFailures,
    state,
  });
  advanceWithoutEdictRef.current = advanceWithoutEdict;


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

  // 新回合进入时拉取全部密令，有 active 密令则弹密令进度弹窗（邸报关闭后显示）。
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

  // 全局 ESC：按 z-index 优先级，最前面的弹窗先关
  useEscClose(activeModal, setActiveModal, [
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
  };
  const sz = hudStageSize;
  const ready = sz.w > 0 && sz.h > 0;

  return (
    <main className="game-shell">
      <GameHud
        stageRef={hudStageCbRef}
        ready={ready}
        state={state}
        mapNodes={mapNodes}
        mapSelectedId={mapIntelOpen ? selectedNode?.id || "" : ""}
        onSelectMapNode={selectMapNode}
        activeDrawerKey={activeDrawerKey}
        navHandlers={navHandlers}
        secretOrderActiveCount={secretOrders.filter((o) => o.status === "active" || o.status === "pending_review").length}
        onOpenModal={setActiveModal}
      />

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
            secretOrders={secretOrders.filter((o) => o.status === "active" || o.status === "pending_review")}
            replyRetry={replyRetry}
            extractionPendingCount={extractionPendingCount}
            onInput={setInput}
            onSend={sendChat}
            onRetryFailure={retryPendingAction}
            onRetryReply={retryInterruptedReply}
            onRetryExtraction={retryStoryExtraction}
            onUndo={undoLastChat}
            onHint={setComposerHint}
            onFavorite={toggleFavorite}
            scrollPosition={audienceScrollPositionsRef.current.get(`${currentCampaignId}:${currentNightId}`)}
            onScrollPositionChange={(position) => audienceScrollPositionsRef.current.set(`${currentCampaignId}:${currentNightId}`, position)}
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
        <FullscreenModal title="诏书草案" subtitle="本月指令与退朝" bgClass="modal-bg-edict" onClose={guardClose(() => setActiveModal("none"))}>
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
            onAdvanceWithoutEdict={advanceWithoutEdict}
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
        <HistoryModal onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "audience_archive" ? (
        <AudienceArchiveModal ministers={audienceRoster} onClose={guardClose(() => setActiveModal("none"))} />
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

// 仅在真实浏览器（存在 #root）自动挂载；测试可 import { App } 挂载真实组件走生产 wiring。
const rootEl = typeof document !== "undefined" ? document.getElementById("root") : null;
if (rootEl) createRoot(rootEl).render(<App />);
