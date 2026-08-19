import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./main";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
class _RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as typeof globalThis & { ResizeObserver?: unknown }).ResizeObserver = _RO;

const jsonResp = (payload: unknown): Response => ({ ok: true, json: async () => payload } as unknown as Response);

const MENU_STATUS = {
  has_api_key: true, has_running_game: true, has_main_db: true, saves: [],
  llm: { base_url: "x", model: "m", has_api_key: true, max_tokens: 1, timeout_seconds: 1, thinking_level: "", advanced_model: "", advanced_base_url: "", has_advanced_api_key: false, advanced_thinking_level: "" },
};
const acct = () => ({ balance: 0, income: [], expense: [], income_total: 0, expense_total: 0, net: 0, movements: [], movements_total: 0 });
const makeState = () => ({
  turn: { year: 1627, period: 10, turn: 1, phase: "summoning" },
  metrics: {}, previous_summary: "", issues: [], legacies: [], closed_this_turn: [],
  budget: { 国库: acct(), 内库: acct() }, region_warning: "", army_warning: "", power_warning: "", powers: [],
  victory_status: { status: "", summary: "" }, ending: null, events: [], regions: [], armies: [],
  map_nodes: [], ministers: [], consorts: [], directives: [], pending_count: 0, last_decree: "", last_report: "",
});

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

// 回归：ESC 全局处理器的 effect 依赖曾漏 5 个抽屉 state（stale closure），
// 打开兵/省/工/户/吏抽屉后 ESC 闭包里的布尔永远是 false → 关不掉。
describe("全局 ESC 关闭抽屉（stale closure 回归）", () => {
  it.each([
    ["军队列表", "right-drawer-army"],
    ["省份列表", "right-drawer-region"],
    ["经济面板", "right-drawer-economy"],
    ["建筑列表", "right-drawer-building"],
    ["官员任免", "right-drawer-appointment"],
  ])("打开 %s 抽屉后按 ESC 可关闭", async (navLabel, drawerClass) => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState());
      return jsonResp({});
    }));

    const host = document.createElement("div");
    document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<App />); });
    await tick();
    expect(host.querySelector(".hud2-stage")).not.toBeNull();  // 已进入游戏视图

    const nav = host.querySelector(`button[aria-label="${navLabel}"]`);
    expect(nav).toBeTruthy();
    act(() => { nav!.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await tick();
    expect(host.querySelector(`aside.${drawerClass}.open`)).not.toBeNull();  // 抽屉已开

    act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    await tick();
    expect(host.querySelector(`aside.${drawerClass}.open`)).toBeNull();      // ESC 后抽屉已关
  });
});

describe("全局 ESC 关闭结局页（endingDismissed）", () => {
  it("ESC 关闭结局后不会被 auto-open effect 立刻重开", async () => {
    const endingState = {
      ...makeState(),
      ending: {
        status: "defeat",
        label: "煤山自缢",
        summary: "终章。",
        timeline: [{ turn: 1, year: 1644, period: 3, decree_brief: "", effect_brief: "", chapter: "三月" }],
      },
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(endingState);
      return jsonResp({});
    }));

    const host = document.createElement("div");
    document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<App />); });
    await tick();
    expect(host.querySelector(".modal-bg-ending")).not.toBeNull();

    act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    await tick();
    expect(host.querySelector(".modal-bg-ending")).toBeNull();
  });
});
