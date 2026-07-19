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
const makeState = (turn: number) => ({
  turn: { year: 1627, period: 10, turn, phase: "summoning" },
  metrics: {}, previous_summary: "", treasury: "", issues: [], legacies: [], closed_this_turn: [],
  budget: { 国库: acct(), 内库: acct() }, region_warning: "", army_warning: "", power_warning: "", powers: [],
  victory_status: { status: "", summary: "" }, ending: null, events: [], regions: [], armies: [],
  map_nodes: [], ministers: [], consorts: [], directives: [], pending_count: 0,
  last_decree: "", last_report: "",
});

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const click = (el: Element | null | undefined) =>
  act(() => { el?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
const findButton = (host: HTMLElement, text: string) =>
  Array.from(host.querySelectorAll("button")).find((b) => (b.textContent || "").includes(text));

async function mountGame(fetchImpl: (url: string) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(fetchImpl));
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { createRoot(host).render(<App />); });
  await tick();
  return host;
}

describe("App 持久投影 wiring（#499 真实 App 挂载）", () => {
  const baseFetch = (url: string) => {
    const u = new URL(String(url), "http://t.local");
    if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
    if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1));
    if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
    if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
    return jsonResp({});
  };

  it("挂载即进入游戏视图（真实 App wiring 冒烟：App 消费 useDurableProjection/useAudienceChat 无崩）", async () => {
    const host = await mountGame(async (u) => baseFetch(u));
    expect(host.querySelector(".hud2-stage")).not.toBeNull();
  });

  it("经真实 App 退出到主菜单：游戏视图 → 菜单（走 exitToMenu 全链，含 beginDurableMutation 代次归属）", async () => {
    vi.stubGlobal("confirm", () => true);  // ExitToMenuTab 确认框
    const host = await mountGame(async (u) => baseFetch(u));
    expect(host.querySelector(".hud2-stage")).not.toBeNull();

    await click(host.querySelector('[aria-label="游戏菜单"]'));   // 开游戏菜单
    await tick();
    await click(findButton(host, "回到主菜单"));                   // 切「回到主菜单」tab
    await tick();
    await click(host.querySelector(".menu-btn.primary"));          // 点退出 → exitToMenu
    await tick();
    await tick();

    // 退出后离开游戏视图（exitToMenu 清 state + 切菜单；beginDurableMutation 已作废在飞刷新）
    expect(host.querySelector(".hud2-stage")).toBeNull();
  });
});
