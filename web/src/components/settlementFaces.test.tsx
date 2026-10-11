import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GameHud, resolveUnreadMemorialCount } from "./gameHud";
import type { GameState } from "../types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom 无 SVG getBBox；GameHud 在 ready 时挂 GrandMap。
vi.mock("./map", () => ({
  GrandMap: () => <div data-testid="grand-map-stub" />,
  NodeIntel: () => null,
}));

const mounted: Array<{ root: Root; host: HTMLElement }> = [];

function mount(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => { root.render(node); });
  mounted.push({ root, host });
  return host;
}

afterEach(() => {
  for (const { root, host } of mounted.splice(0)) {
    act(() => root.unmount());
    host.remove();
  }
  vi.unstubAllGlobals();
});

const acct = () => ({
  balance: 100, income: [], expense: [], income_total: 0, expense_total: 0, net: 0, movements: [], movements_total: 0,
});

function makeState(
  settlementDisplay: boolean,
  extra: Partial<GameState> = {},
  phase: string = "settling",
): GameState {
  return {
    turn: { year: 1627, period: 10, turn: 5, phase, settlement_display: settlementDisplay },
    metrics: { 民心: 50, 皇威: 40 },
    previous_summary: "上月邸报",
    issues: [{ id: 1, kind: "situation", title: "半程军饷议题", status: "open", progress: 10, fail_condition: "" } as never],
    legacies: [],
    closed_this_turn: [{
      id: 2, kind: "situation", title: "月初已结漕运", status: "resolved",
      bar_value: 0, bar_good_meaning: "妥", bar_bad_meaning: "",
      closed_turn: 4, stage_text: "", effect: {},
    } as never],
    budget: { 国库: acct(), 内库: acct() },
    region_warning: "", army_warning: "", power_warning: "",
    powers: [],
    victory_status: { status: "", summary: "" },
    ending: null,
    events: [],
    regions: [],
    armies: [],
    map_nodes: [{ id: "liaodong", name: "辽东", kind: "region" } as never],
    ministers: [],
    consorts: [],
    directives: [{ id: 1 } as never],
    pending_count: 0,
    last_decree: "",
    last_report: "",
    ...extra,
  } as GameState;
}

describe("QA A-1 #1276/#1282/#1285 GameHud HUD 对齐", () => {
  function mountHud(opts: {
    state?: GameState;
    onOpenModal?: (modal: string) => void;
    navHandlers?: Record<string, () => void>;
    edictOpen?: boolean;
    onCloseEdict?: () => void;
  } = {}) {
    const opened: string[] = [];
    const navCalls: string[] = [];
    const closed: string[] = [];
    const state = opts.state ?? makeState(false, {
      // 局势仍可有 3 条，但奏疏计数须与之脱钩（#1726）
      issues: [
        { id: 1, kind: "situation", title: "户部亏空", status: "open", progress: 10, fail_condition: "" } as never,
        { id: 2, kind: "situation", title: "辽东索饷", status: "open", progress: 10, fail_condition: "" } as never,
        { id: 3, kind: "situation", title: "陕西流寇起", status: "open", progress: 10, fail_condition: "" } as never,
      ],
      memorials: [
        { key: "progress:1", kind: "progress", turn: 1, author_name: "杨嗣昌", memorial_text: "拨银进度一", unread: true },
        { key: "progress:2", kind: "progress", turn: 1, author_name: "杨嗣昌", memorial_text: "拨银进度二", unread: true },
        { key: "denunciation:1", kind: "denunciation", turn: 1, author_name: "某给事", memorial_text: "检举正文", unread: true },
      ],
      unread_memorial_count: 3,
      events: [],
    });
    const host = mount(
      <GameHud
        stageRef={() => {}}
        ready={true}
        state={state}
        mapNodes={[]}
        mapSelectedId=""
        onSelectMapNode={() => {}}
        activeDrawerKey=""
        navHandlers={opts.navHandlers ?? {
          court: () => navCalls.push("court"),
          harem: () => navCalls.push("harem"),
          army: () => navCalls.push("army"),
          region: () => navCalls.push("region"),
          building: () => navCalls.push("building"),
          economy: () => navCalls.push("economy"),
          appointment: () => navCalls.push("appointment"),
        }}
        secretOrderActiveCount={0}
        unreadMemorialCount={resolveUnreadMemorialCount(state)}
        edictOpen={opts.edictOpen}
        onCloseEdict={() => {
          closed.push("edict");
          opts.onCloseEdict?.();
        }}
        onOpenModal={(modal) => {
          opened.push(modal);
          opts.onOpenModal?.(modal);
        }}
        settlementFace={Boolean(state.turn.settlement_display)}
      />,
    );
    return { host, opened, navCalls, closed };
  }

  it("#1458 拟诏台开着：底栏仅拟诏收起可点，其余命令不得切走 activeModal", () => {
    // 复现：edict-safe-cmd 底边整条开洞，奏疏/邸报/密令/史册图钮与文字钮都在洞内可点，
    // 一点就 openModal 把拟诏台切走。修：台开时只放行拟诏收起。
    const { host, opened, closed } = mountHud({ edictOpen: true });
    const captions = Array.from(host.querySelectorAll(".hud2-cmd-caption"));
    const cmds = Array.from(host.querySelectorAll("button.hud2-cmd"));
    const others = ["奏疏", "邸报", "密令", "史册"];
    for (const name of others) {
      const cap = captions.find((b) => (b.getAttribute("aria-label") || "").includes(name));
      const img = cmds.find((b) => (b.getAttribute("aria-label") || "").includes(name));
      expect(cap, `${name} caption`).toBeTruthy();
      expect(img, `${name} img`).toBeTruthy();
      act(() => { cap?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
      act(() => { img?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    }
    expect(opened).toEqual([]);

    const edictCap = captions.find((b) => (b.getAttribute("aria-label") || "").includes("拟诏"));
    const edictImg = cmds.find((b) => (b.getAttribute("aria-label") || "").includes("拟诏"));
    act(() => { edictCap?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    expect(closed).toEqual(["edict"]);
  });
});
