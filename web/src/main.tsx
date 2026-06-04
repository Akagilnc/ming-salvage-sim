import React from "react";
import { createRoot } from "react-dom/client";
import { Crown, Loader2, X } from "lucide-react";
import { api, streamChat } from "./api";
import { AppointmentDrawer, ArmyDrawer, BuildingDrawer, CourtDrawer, EconomyDrawer, HaremDrawer, RegionDrawer } from "./components/drawers";
import { ExtractionModal } from "./components/extraction";
import { GameMenuModal } from "./components/gameMenu";
import { BudgetHover, CommandSlot, FullscreenModal, HUD_BG, HUD_SLOTS, LegacyBar, LongGoalsModal, QuadFrame } from "./components/hud";
import { GrandMap, NodeIntel } from "./components/map";
import { MenuPage } from "./components/menuPage";
import { ChatModal, ClosedIssuesModal, EdictModal, EndingModal, HistoryModal, ReportModal, SecretOrdersModal, StateModal, filterConsorts, filterMinisters } from "./components/modals";
import { SituationPanel } from "./components/situation";
import { getMapIntelStyle, refreshLabelMaps, scoreTone } from "./format";
import { forwardSteamEvents, type SteamEvent } from "./steamEvents";
import type { AppView, ChatMessage, ChatUndoResponse, ClosedIssue, Directive, GameState, MenuStatus, Minister, ModalName, SecretOrder, Suggestion } from "./types";
import "./styles.css";

function App() {
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
  const [chat, setChat] = React.useState<ChatMessage[]>([]);
  const [suggestions, setSuggestions] = React.useState<Suggestion[]>([]);
  const [pendingUserMessage, setPendingUserMessage] = React.useState("");
  const [streamingMinisterMessage, setStreamingMinisterMessage] = React.useState("");
  const [chatNotice, setChatNotice] = React.useState("");
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
  // 作弊控制台（Ctrl+~）：cheatDirective 暂存强制结算项，下次颁诏随结算一次性穿入。
  const [cheatOpen, setCheatOpen] = React.useState(false);
  const [cheatDirective, setCheatDirective] = React.useState("");

  const loadState = React.useCallback(async () => {
    const data = await api<GameState>("/api/game/state");
    refreshLabelMaps(data);
    setState(data);
    setSelectedNodeId((current) => current || data.map_nodes[0]?.id || "");
    setDecree(data.last_decree || "");
    setReport(data.last_report || "");
  }, [selectedMinister]);

  const loadMinisterChat = React.useCallback(async (ministerName: string) => {
    const data = await api<{ minister: Minister; history: ChatMessage[]; suggestions: Suggestion[]; can_undo_last_chat: boolean }>(`/api/ministers/${encodeURIComponent(ministerName)}/chat`);
    const allKnown = [
      ...(state?.ministers || []),
      ...(state?.consorts || []),
    ];
    setTemporaryActiveMinister(allKnown.some((m) => m.name === data.minister.name) ? null : data.minister);
    setChat(data.history);
    setSuggestions(data.suggestions);
    setCanUndoLastChat(!!data.can_undo_last_chat);
  }, [state]);

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
    setAppView("game");
    await loadState();
  }, [loadState]);

  const exitToMenu = React.useCallback(async () => {
    await fetch("/api/menu/exit_to_menu", { method: "POST" });
    setState(null);
    setAppView("menu");
    await refreshMenuStatus();
  }, [refreshMenuStatus]);

  React.useEffect(() => {
    if (!state) return;
    const closed = state.closed_this_turn || [];
    const currentTurn = state.turn.turn;
    if (closed.length && currentTurn !== closedShown) {
      setClosedModal(closed);
      setClosedShown(currentTurn);
      sessionStorage.setItem("closedShownTurn", String(currentTurn));
    }
  }, [state, closedShown]);

  // 新回合进入时拉取全部密令，有 active 密令则弹密令进度弹窗（邸报关闭后显示）
  React.useEffect(() => {
    if (!state) return;
    const currentTurn = state.turn.turn;
    if (currentTurn === secretOrderShown) return;
    api<{ orders: SecretOrder[] }>("/api/secret_orders")
      .then(({ orders }) => {
        setSecretOrders(orders);
        if (orders.some(o => o.status === "active" || o.status === "pending_review")) {
          // 延迟 400ms，避免与邸报弹窗争抢
          setTimeout(() => setActiveModal("secret_orders"), 400);
        }
        setSecretOrderShown(currentTurn);
      })
      .catch(() => {/* 失败静默 */});
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
    setGazetteReport(summary);
    setActiveModal("report");
    setGazetteShown(currentTurn);
  }, [state, gazetteShown, endingDismissed]);

  React.useEffect(() => {
    if (!selectedMinister) {
      setChat([]);
      setSuggestions([]);
      setPendingUserMessage("");
      setStreamingMinisterMessage("");
      setChatNotice("");
      setCanUndoLastChat(false);
      setComposerHint("");
      return;
    }
    setChat([]);
    setSuggestions([]);
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
    setCanUndoLastChat(false);
    setComposerHint("");
    loadMinisterChat(selectedMinister).catch((err) => setError(err.message));
  }, [selectedMinister, loadMinisterChat]);

  // 全局 ESC：按 z-index 优先级，最前面的弹窗先关
  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (activeModal === "chat" || activeModal === "edict" || activeModal === "state" || activeModal === "history" || activeModal === "report" || activeModal === "secret_orders" || activeModal === "long_goals") {
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
  const ministers = filterMinisters(state.ministers, ministerGroup);
  const consorts = filterConsorts(state.consorts || [], haremGroup);
  const allCharacters = [...state.ministers, ...(state.consorts || [])];
  const activeMinister = selectedMinister
    ? allCharacters.find((m) => m.name === selectedMinister) || temporaryActiveMinister
    : null;
  const mapIntelStyle = selectedNode ? getMapIntelStyle(selectedNode) : undefined;

  const openChat = (minister: Minister) => {
    if (minister.status && minister.status !== "active") {
      setError(`${minister.name}已${minister.status_label}${minister.status_reason ? "（" + minister.status_reason + "）" : ""}，无法召见。`);
      return;
    }
    const switchingMinister = selectedMinister !== minister.name;
    if (switchingMinister) {
      setChat([]);
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
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
    loadMinisterChat(minister.name).catch((err) => setError(err.message));
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

    const fromComposer = text === input;
    setPendingUserMessage(message);
    setStreamingMinisterMessage("");
    setBusy("大臣思索中");
    setError("");
    setComposerHint("");
    setChatNotice("");
    if (fromComposer) {
      setInput("");
    }
    try {
      const data = await streamChat(activeMinister.name, message, (delta) => {
        setStreamingMinisterMessage((current) => current + delta);
      });
      setPendingUserMessage("");
      setStreamingMinisterMessage("");
      setChat(data.history);
      setSuggestions(data.suggestions);
      setCanUndoLastChat(!!data.can_undo_last_chat);
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count ?? current.pending_count } : current));
      await loadState();
      // 刷新密令列表（含历史，大臣可能调了 issue_secret_order tool）
      api<{ orders: SecretOrder[] }>("/api/secret_orders")
        .then(({ orders }) => setSecretOrders(orders))
        .catch(() => {});
      if (data.secret_order_id) {
        setChatNotice(`密令已秘密交付${activeMinister.name}，编号 #${data.secret_order_id}。`);
      }
      if (data.proposed_directive) {
        setChatNotice(`${activeMinister.name}已拟旨一道，待陛下在「诏书草案」核定（准/驳）。`);
      }
      if (data.next_minister) {
        setChat([]);
        setSuggestions([]);
        setStreamingMinisterMessage("");
        setCanUndoLastChat(false);
        setSelectedMinister(data.next_minister);
        setActiveModal("chat");
        setChatNotice(`已传${data.next_minister}入殿。`);
        loadMinisterChat(data.next_minister).catch((err) => setError(err.message));
      }
      if (data.court_action === "dismiss") {
        setPendingUserMessage("");
        setChatNotice(`${activeMinister.name}已退下。请从左侧召见下一位大臣。`);
      }
    } catch (err) {
      if (fromComposer) {
        setInput(message);
      }
      setPendingUserMessage("");
      setStreamingMinisterMessage("");
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const undoLastChat = async () => {
    if (busy || !activeMinister || !canUndoLastChat) return;
    const ok = window.confirm("将撤回最近一轮召对及其政务影响，是否继续？");
    if (!ok) return;
    setBusy("撤回召对");
    setError("");
    setChatNotice("");
    setComposerHint("");
    setPendingUserMessage("");
    setStreamingMinisterMessage("");
    try {
      const data = await api<ChatUndoResponse>(`/api/ministers/${encodeURIComponent(activeMinister.name)}/chat/undo`, {
        method: "POST",
      });
      setChat(data.history);
      setSuggestions(data.suggestions);
      setCanUndoLastChat(!!data.can_undo_last_chat);
      setSecretOrders(data.secret_orders || []);
      setState((current) => (current ? { ...current, directives: data.directives, pending_count: data.pending_count } : current));
      await loadState();
      setChatNotice("已撤回最近一轮召对。");
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
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("");
    }
  };

  const saveDecree = async (text: string) => {
    setBusy("存改诏书");
    setError("");
    try {
      const data = await api<{ decree: string }>("/api/decree", {
        method: "PATCH",
        body: JSON.stringify({ decree: text }),
      });
      setDecree(data.decree);
    } catch (err) {
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
      if (!response.ok || !response.body) {
        throw new Error(`颁诏失败：HTTP ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = false;
      let failed = "";
      while (!done) {
        const { value, done: streamDone } = await reader.read();
        if (streamDone) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE 事件以空行分隔
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
          let data: { content?: string; message?: string } = {};
          try { data = JSON.parse(dataRaw); } catch { continue; }
          if (evName === "stage") {
            setSettleStage(data.content || "");
          } else if (evName === "thinking") {
            setSettleThinking((prev) => prev + (data.content || ""));
          } else if (evName === "text") {
            setSettleNarrative((prev) => prev + (data.content || ""));
          } else if (evName === "error") {
            failed = data.message || "颁诏失败。";
            done = true;
          } else if (evName === "done") {
            await forwardSteamEvents(data);
            done = true;
          }
        }
      }
      if (failed) {
        setError(failed);
        setBusy("");
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
          caption="邸报详明" sub="数项加减/账目明细" onClick={() => setActiveModal("extraction")} />
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
            portraitPrefix={(state.consorts || []).some((c) => c.name === activeMinister.name) ? "consort_" : "minister_"}
            chat={chat}
            suggestions={suggestions}
            pendingUserMessage={pendingUserMessage}
            streamingMinisterMessage={streamingMinisterMessage}
            chatNotice={chatNotice}
            canUndoLastChat={canUndoLastChat}
            composerHint={composerHint}
            input={input}
            busy={busy}
            error={error}
            secretOrders={secretOrders.filter((o) => o.minister_name === activeMinister.name && (o.status === "active" || o.status === "pending_review"))}
            onInput={setInput}
            onSend={sendChat}
            onUndo={undoLastChat}
            onHint={setComposerHint}
            onFavorite={() => toggleFavorite(activeMinister)}
            onOpenEdict={() => setActiveModal("edict")}
            onClose={guardClose(() => setActiveModal("none"))}
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
            onSaveDecree={saveDecree}
            onResetDecree={resetDecree}
            onIssueDecree={issueDecree}
            onConfirmDirective={confirmDirective}
            onRejectDirective={rejectDirective}
          />
        </FullscreenModal>
      ) : null}

      {activeModal === "report" && (gazetteReport || report) ? (
        <ReportModal report={gazetteReport || report} onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "ending" && state.ending ? (
        <EndingModal ending={state.ending} onClose={() => { setEndingDismissed(true); setActiveModal("none"); }} />
      ) : null}

      {activeModal === "extraction" ? (
        <ExtractionModal onClose={guardClose(() => setActiveModal("none"))} />
      ) : null}

      {activeModal === "history" ? (
        <HistoryModal onClose={guardClose(() => setActiveModal("none"))} />
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

      {cheatOpen ? (
        <CheatConsole
          directive={cheatDirective}
          onCommit={setCheatDirective}
          onClose={() => setCheatOpen(false)}
        />
      ) : null}
    </main>
  );
}


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

createRoot(document.getElementById("root")!).render(<App />);
