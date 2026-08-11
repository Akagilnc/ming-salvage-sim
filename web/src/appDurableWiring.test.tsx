import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./main";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
class _RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as typeof globalThis & { ResizeObserver?: unknown }).ResizeObserver = _RO;

// 开启密令换回合自动弹窗（生产 gate 默认关；测试打开以验协调器所属的延迟呈现定时器 wiring）。
vi.mock("./settlementPresentation", () => ({
  shouldAutoOpenSecretOrdersAfterSettlement: () => true,
  shouldAutoOpenClosedIssuesAfterSettlement: () => false,
}));

const jsonResp = (payload: unknown): Response => ({ ok: true, json: async () => payload } as unknown as Response);

const MENU_STATUS = {
  has_api_key: true, has_running_game: true, has_main_db: true, saves: [],
  llm: { base_url: "x", model: "m", has_api_key: true, max_tokens: 1, timeout_seconds: 1, thinking_level: "", advanced_model: "", advanced_base_url: "", has_advanced_api_key: false, advanced_thinking_level: "" },
};
const acct = () => ({ balance: 0, income: [], expense: [], income_total: 0, expense_total: 0, net: 0, movements: [], movements_total: 0 });
const directive = () => ({ id: 1, event_id: "", event_title: "", actor: "", skill_id: "", skill_name: "", text: "旧草案", source: "", status: "draft", notes: "", authority: "" });
const makeState = (turn: number, directives: unknown[] = [], ministers: unknown[] = []) => ({
  turn: { year: 1627, period: 10, turn, phase: "summoning" },
  metrics: {}, previous_summary: "", treasury: "", issues: [], legacies: [], closed_this_turn: [],
  budget: { 国库: acct(), 内库: acct() }, region_warning: "", army_warning: "", power_warning: "", powers: [],
  victory_status: { status: "", summary: "" }, ending: null, events: [], regions: [], armies: [],
  map_nodes: [], ministers, consorts: [], directives, pending_count: 0, last_decree: "", last_report: "",
});

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const click = (el: Element | null | undefined) => act(() => { el?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
const findButton = (host: HTMLElement, text: string) =>
  Array.from(host.querySelectorAll("button")).find((b) => (b.textContent || "").includes(text));

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("App 持久投影 wiring（#499 真实 App 挂载 durable-race tracer）", () => {
  it("第二命令槽 opens the read-only 起居注 and resolves archived attendant portraits from the App roster", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], [
        { name: "王承恩", portrait_id: "portrait_court_03" },
      ]));
      if (u.pathname.endsWith("/api/history/turns")) return jsonResp({ turns: [
        { kind: "night", turn: 1, year: 1627, period: 10, night_id: 31, title: "乾清宫召对", involved_people: ["王承恩"] },
      ] });
      if (u.pathname.endsWith("/api/audience/scroll")) return jsonResp({ messages: [
        { role: "attendant", speaker: "王承恩", content: "御前低语", audibility: "御前低语" },
      ] });
      return jsonResp({});
    }));
    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<App />); });
    await act(async () => {
      await vi.waitFor(() => expect(findButton(host, "起居注")).toBeTruthy());
    });

    await click(findButton(host, "起居注"));
    await act(async () => {
      await vi.waitFor(() => {
        expect(host.querySelector('[role="dialog"][aria-label="起居注：召对记录"]')).not.toBeNull();
        expect(host.querySelector<HTMLImageElement>(".aside-avatar")?.getAttribute("src"))
          .toBe("/portraits/minister_王承恩.png");
      });
    });
  });
  it("延迟刷新竞争：草案删除后旧 state 刷新迟到不覆盖——新 DOM 权威（beginDurableMutation 代次归属）", async () => {
    let releaseStale!: () => void;
    const staleGate = new Promise<void>((r) => { releaseStale = r; });
    let stateCall = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/directives/1") && init?.method === "DELETE") return jsonResp({ directives: [] });
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) {
        stateCall += 1;
        if (stateCall === 1) return jsonResp(makeState(1, [directive()]));  // 首拉：含旧草案
        await staleGate;                                                     // 第 2 次（换回合 effect 刷新）挂起
        return jsonResp(makeState(1, [directive()]));                        // 迟到：仍含旧草案（陈旧）
      }
      return jsonResp({});
    }));

    const host = document.createElement("div");
    document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<App />); });
    await tick();
    expect(host.querySelector(".hud2-stage")).not.toBeNull();  // 进入游戏视图（旧草案在飞刷新已发出、挂起）

    await click(findButton(host, "拟诏/结束回合"));  // 开诏书草案模态
    await tick();
    expect(findButton(host, "删")).toBeTruthy();      // 旧草案可删
    await click(findButton(host, "删"));              // 真实 deleteDirective：DELETE + beginDurableMutation + setState([])
    await tick();
    expect(findButton(host, "删")).toBeFalsy();        // 草案已删
    expect(stateCall).toBeGreaterThanOrEqual(2);       // 陈旧 state 刷新确实在飞（竞争真实存在）

    releaseStale();  // 陈旧 state 刷新（含旧草案）迟到 resolve——代次已被 deleteDirective 推进
    await tick();
    expect(findButton(host, "删")).toBeFalsy();        // 新 DOM 权威：陈旧刷新返 null 弃写，草案不复活
  });

  // 真实密令进度弹窗 = FullscreenModal 渲染的 <section role="dialog" aria-label="密令进度">；
  // HUD 常驻指令槽也含「密令」字样，故只认这个真实对话框，不认自由文本（否则空断言）。
  const secretDialog = (host: HTMLElement) => host.querySelector("[role='dialog'][aria-label='密令进度']");

  it("延迟呈现正路（协调器所属定时器）：最新代次时 fake time 到点弹密令进度对话框", async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
        if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [{ id: 1, title: "密", content: "", status: "active", minister_name: "", year_issued: 1627, period_issued: 10 }] });
        if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
        if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1));
        return jsonResp({});
      }));
      const host = document.createElement("div");
      document.body.appendChild(host);
      await act(async () => { createRoot(host).render(<App />); });
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });   // 冲刷挂载 fetch，换回合 effect 起 autoOpen 定时器
      expect(secretDialog(host)).toBeNull();                             // 未到点：真实对话框未开
      await act(async () => { await vi.advanceTimersByTimeAsync(400); }); // 400ms 到点、仍最新代次 → open()
      expect(secretDialog(host)).not.toBeNull();                         // 密令进度对话框已弹（协调器定时器 fire）
    } finally { vi.useRealTimers(); }
  });

  it("延迟呈现负路：定时器计时中经真实变更(删草案)推进代次→陈旧定时器 no-op，密令进度不弹", async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/api/directives/1") && init?.method === "DELETE") return jsonResp({ directives: [] });
        if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
        if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [{ id: 1, title: "密", content: "", status: "active", minister_name: "", year_issued: 1627, period_issued: 10 }] });
        if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
        if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [directive()]));
        return jsonResp({});
      }));
      const host = document.createElement("div");
      document.body.appendChild(host);
      await act(async () => { createRoot(host).render(<App />); });
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });   // 冲刷挂载：autoOpen 400ms 定时器已排程（尚未到点）
      expect(secretDialog(host)).toBeNull();

      // 计时期间执行一次真实变更（删草案）：deleteDirective 调 beginDurableMutation 推进代次
      await act(async () => { (findButton(host, "拟诏/结束回合"))?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      await act(async () => { (findButton(host, "删"))?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });   // DELETE 完成、代次已推进

      await act(async () => { await vi.advanceTimersByTimeAsync(400); }); // 定时器到点但陈旧 → no-op
      expect(secretDialog(host)).toBeNull();                             // 密令进度对话框未弹（已作废窗不弹）
    } finally { vi.useRealTimers(); }
  });

  it("经真实 App 退出到主菜单（exitToMenu 全链，含 beginDurableMutation 代次归属）", async () => {
    vi.stubGlobal("confirm", () => true);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1));
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      return jsonResp({});
    }));
    const host = document.createElement("div");
    document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<App />); });
    await tick();
    expect(host.querySelector(".hud2-stage")).not.toBeNull();

    await click(host.querySelector('[aria-label="游戏菜单"]'));
    await tick();
    await click(findButton(host, "回到主菜单"));
    await tick();
    await click(host.querySelector(".menu-btn.primary"));
    await tick();
    await tick();
    expect(host.querySelector(".hud2-stage")).toBeNull();  // 已退出游戏视图
  });
});
