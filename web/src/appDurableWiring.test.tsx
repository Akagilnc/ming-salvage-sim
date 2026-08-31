import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./main";
import { SETTLEMENT_CLOSED_REASON } from "./settlementPresentation";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
// jsdom 无布局：给 stage 非零尺寸，使 GameHud ready=true（地图/局势框/上月已结入口可挂）。
class _RO {
  private cb: ResizeObserverCallback;
  constructor(cb: ResizeObserverCallback) { this.cb = cb; }
  observe(el: Element) {
    this.cb([{ target: el } as ResizeObserverEntry], this as unknown as ResizeObserver);
  }
  unobserve() {}
  disconnect() {}
}
(globalThis as typeof globalThis & { ResizeObserver?: unknown }).ResizeObserver = _RO;
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 1600 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => 900 });

// #1236：face-gate / 密令自动弹窗谓词一律走真实实现。
// 禁止把 shouldAutoOpenSecretOrdersAfterSettlement 全局 mock 成恒 true——
// 否则挂载后 400ms 协调器定时器会在任意长测中途抢 activeModal（串写失败的假阴性根因）。
// 延迟呈现用例以真实谓词所需的 dossier_progress 行触发 autoOpen。

// GrandMap 依赖 SVG getBBox；本文件只验 face 门控/持久投影，不测地图几何。
vi.mock("./components/map", () => ({
  GrandMap: () => <div data-testid="grand-map-stub" />,
  NodeIntel: () => null,
}));

const jsonResp = (payload: unknown): Response => ({ ok: true, json: async () => payload } as unknown as Response);
const sseResp = (event: string, payload: unknown): Response => {
  const body = `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
};

const MENU_STATUS = {
  has_api_key: true, has_running_game: true, has_main_db: true, saves: [],
  llm: { base_url: "x", model: "m", has_api_key: true, timeout_seconds: 1, thinking_level: "", advanced_model: "", advanced_base_url: "", has_advanced_api_key: false, advanced_thinking_level: "" },
};
const acct = () => ({ balance: 0, income: [], expense: [], income_total: 0, expense_total: 0, net: 0, movements: [], movements_total: 0 });
const directive = () => ({ id: 1, event_id: "", event_title: "", actor: "", skill_id: "", skill_name: "", text: "旧草案", source: "", status: "draft", notes: "", authority: "" });
const makeState = (turn: number, directives: unknown[] = [], ministers: unknown[] = []) => ({
  turn: { year: 1627, period: 10, turn, phase: "summoning" },
  metrics: {}, previous_summary: "", issues: [], legacies: [], closed_this_turn: [],
  budget: { 国库: acct(), 内库: acct() }, region_warning: "", army_warning: "", power_warning: "", powers: [],
  victory_status: { status: "", summary: "" }, ending: null, events: [], regions: [], armies: [],
  map_nodes: [], ministers, consorts: [], directives, pending_count: 0, last_decree: "", last_report: "",
});

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const click = (el: Element | null | undefined) => act(() => { el?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
const findButton = (host: HTMLElement, text: string) =>
  Array.from(host.querySelectorAll("button")).find((b) => (b.textContent || "").includes(text));

// #671：根因——createRoot 后只清 innerHTML 不 unmount，孤儿树 effect/定时器串测致全套件时序 flake。
const mountedRoots: Array<{ root: Root; host: HTMLElement }> = [];
const trackRoot = (host: HTMLElement): Root => {
  const root = createRoot(host);
  mountedRoots.push({ root, host });
  return root;
};
const unmountTrackedRoots = () => {
  for (const { root, host } of mountedRoots.splice(0)) {
    act(() => { root.unmount(); });
    host.remove();
  }
};

afterEach(() => {
  unmountTrackedRoots();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("App 持久投影 wiring（#499 真实 App 挂载 durable-race tracer）", () => {
  it("#1276 邸报木牌重开 gazette；史册头起居注另入口解析近臣像", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp({
        ...makeState(1, [], [{ name: "王承恩", portrait_id: "portrait_court_03" }]),
        previous_summary: "天启七年九月邸报·试重开",
      });
      if (u.pathname.endsWith("/api/history/turns")) return jsonResp({ turns: [
        { kind: "month", turn: 0, year: 1627, period: 9, has_report: true, has_attendant: false, has_directive: false },
        { kind: "night", turn: 1, year: 1627, period: 10, night_id: 31, title: "乾清宫召对", involved_people: ["王承恩"] },
      ] });
      if (u.pathname.endsWith("/api/history/turn/0")) return jsonResp({ turn: 0, exists: true, report: "月档", directives: [] });
      if (u.pathname.endsWith("/api/audience/scroll")) return jsonResp({ messages: [
        { role: "attendant", speaker: "王承恩", content: "御前低语", audibility: "御前低语" },
      ] });
      return jsonResp({});
    }));
    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    // 自动邸报弹出后关掉，再经木牌重开
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="邸报"]')).not.toBeNull());
    });
    await click(host.querySelector('[aria-label="关闭弹窗"]'));
    await act(async () => {
      await vi.waitFor(() => expect(findButton(host, "邸报")).toBeTruthy());
    });
    await click(findButton(host, "邸报"));
    await act(async () => {
      await vi.waitFor(() => {
        expect(host.querySelector('[role="dialog"][aria-label="邸报"]')).not.toBeNull();
        expect(host.textContent).toContain("天启七年九月邸报·试重开");
      });
    });
    await click(host.querySelector('[aria-label="关闭弹窗"]'));

    // 起居注：史册头另入口
    await click(findButton(host, "史册"));
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
  it("夜卷轴侧插话随 selected minister 镜头保留，真实 App 请求命中窗口大臣 (#1511)", async () => {
    const minister = (name: string) => ({ name, office: "兵部", office_type: "内阁", faction: "", style: "", status: "active", status_label: "在朝", summary: "", favorite: false, skills: [] });
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      calls.push(`${init?.method || "GET"} ${decodeURIComponent(u.pathname)}`);
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], [minister("杨嗣昌"), minister("洪承畴")]));
      if (decodeURIComponent(u.pathname).endsWith("/api/ministers/洪承畴/chat")) return jsonResp({ campaign_id: "c", night_id: 23, history: [], suggestions: [], can_undo_last_chat: false });
      if (u.pathname.endsWith("/api/audience/scroll")) return jsonResp({ night_id: 23, messages: [
        { role: "scene", speaker: "洪承畴", content: "入殿", beat: "entrance" },
        { role: "minister", speaker: "洪承畴", content: "臣在。", beat: "dialogue", chat_turn_id: 1 },
        { role: "attendant", speaker: "杨嗣昌", content: "御前低语", audibility: "御前低语", beat: "dialogue" },
      ] });
      if (u.pathname.endsWith("/chat/stream")) {
        const body = [
          'event: delta\ndata: {"content":"臣请奏边务"}\n\n',
          'event: done\ndata: {"history":[],"directives":[],"suggestions":[{"label":"追问边务","text":"追问边务"}],"can_undo_last_chat":true,"pending_count":0}\n\n',
          'event: end\ndata: {}\n\n',
        ].join("");
        return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      return jsonResp({});
    }));
    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[title="朝堂·召见大臣"]'));
    await tick();
    // #1511: open the segment owner (洪); side interjection stays in-lens without stealing the window.
    await click(Array.from(host.querySelectorAll(".minister-card")).find((node) => node.textContent?.includes("洪承畴")));
    await act(async () => { await vi.waitFor(() => expect(host.querySelector("textarea")).not.toBeNull()); });
    const textarea = host.querySelector("textarea")!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(textarea, "边务如何");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(findButton(host, "发送"));
    await act(async () => { await vi.waitFor(() => expect(calls).toContain("POST /api/ministers/洪承畴/chat/stream")); });
    expect(calls).toContain("POST /api/ministers/洪承畴/chat/stream");
    expect(host.textContent).toContain("杨嗣昌御前低语");
  });

  it("typed SSE error 经真实召对链只向玩家呈现结构化 message", async () => {
    const minister = { name: "洪承畴", office: "兵部", office_type: "内阁", faction: "", style: "", status: "active", status_label: "在朝", summary: "", favorite: false, skills: [] };
    const detail = {
      code: "llm_run_error",
      message: "通传未达，请稍后再召。",
      provider_message: "provider stack trace",
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], [minister]));
      if (u.pathname.endsWith("/api/audience/scroll")) return jsonResp({ night_id: 23, messages: [] });
      if (u.pathname.endsWith("/chat/stream")) return sseResp("error", detail);
      if (decodeURIComponent(u.pathname).endsWith("/api/ministers/洪承畴/chat")) {
        return jsonResp({ campaign_id: "c", night_id: 23, minister, history: [], suggestions: [], can_undo_last_chat: false });
      }
      return jsonResp({});
    }));

    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[title="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll(".minister-card")).find((node) => node.textContent?.includes(minister.name)));
    await act(async () => { await vi.waitFor(() => expect(host.querySelector("textarea")).not.toBeNull()); });
    const textarea = host.querySelector("textarea")!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(textarea, "边务如何");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(findButton(host, "发送"));
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="alert"]')).not.toBeNull());
    });

    const alert = host.querySelector('[role="alert"]')!;
    expect(alert.textContent).toBe(detail.message);
    expect(alert.textContent).not.toContain(detail.code);
  });

  it("中断回话重试直接消费洪承畴 payload，并刷新夜卷轴而不重拉目标历史", async () => {
    const minister = (name: string) => ({ name, office: "兵部", office_type: "内阁", faction: "", style: "", status: "active", status_label: "在朝", summary: "", favorite: false, skills: [] });
    const calls: string[] = [];
    let scrollCalls = 0;
    let retryCompleted = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      const call = `${init?.method || "GET"} ${decodeURIComponent(u.pathname)}`;
      calls.push(call);
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], [minister("杨嗣昌"), minister("洪承畴")]));
      if (u.pathname.endsWith("/api/audience/scroll")) {
        scrollCalls += 1;
        return jsonResp({ night_id: 23, messages: retryCompleted
          ? [{ role: "minister", speaker: "洪承畴", content: "臣已整饬边防", beat: "dialogue", chat_turn_id: 7 }]
          : [{ role: "scene", speaker: "洪承畴", content: "入殿", beat: "entrance" }] });
      }
      // #1511: retry surfaces on the owning minister window (洪), not a mismatched entry card.
      if (decodeURIComponent(u.pathname).endsWith("/api/ministers/洪承畴/chat")) return jsonResp(retryCompleted ? {
        campaign_id: "c", night_id: 23, minister: minister("洪承畴"), history: [{ role: "minister", content: "臣已整饬边防", chat_turn_id: 7 }], suggestions: [{ label: "追问粮饷", text: "追问粮饷" }], can_undo_last_chat: true,
      } : {
        campaign_id: "c", night_id: 23, minister: minister("洪承畴"), history: [], suggestions: [], can_undo_last_chat: false,
        reply_retry: { chat_turn_id: 7, minister_name: "洪承畴", turn: 1, question: "边务如何" },
      });
      if (u.pathname.endsWith("/reply/retry") && init?.method === "POST") {
        retryCompleted = true;
        return jsonResp({
        answer: "臣已整饬边防", campaign_id: "c", night_id: 23, chat_turn_id: 7,
        history: [{ role: "user", content: "边务如何", chat_turn_id: 7 }, { role: "minister", content: "臣已整饬边防", chat_turn_id: 7 }],
        suggestions: [{ label: "追问粮饷", text: "追问粮饷" }], directives: [], can_undo_last_chat: true,
        pending_action_failures: [],
        });
      }
      return jsonResp({});
    }));
    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[title="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll(".minister-card")).find((node) => node.textContent?.includes("洪承畴")));
    await act(async () => { await vi.waitFor(() => expect(findButton(host, "重新生成回话")).toBeTruthy()); });
    const scrollCallsBeforeRetry = scrollCalls;
    await click(findButton(host, "重新生成回话"));
    await act(async () => { await vi.waitFor(() => expect(host.textContent).toContain("臣已整饬边防")); });

    expect(calls).toContain("POST /api/ministers/洪承畴/reply/retry");
    // History reload for 洪 is the selected-minister effect; retry itself must not re-GET chat.
    expect(scrollCalls).toBeGreaterThan(scrollCallsBeforeRetry);
    expect(host.textContent).toContain("追问粮饷");
    expect(host.textContent).toContain("已重新生成回话。");
    expect(findButton(host, "重新生成回话")).toBeFalsy();
    expect(findButton(host, "撤回本轮")?.hasAttribute("disabled")).toBe(false);
  });

  it("中断回话重试未决时切离发起面板，旧 payload 不串写新面板", async () => {
    const minister = (name: string) => ({ name, office: "兵部", office_type: "内阁", faction: "", style: "", status: "active", status_label: "在朝", summary: "", favorite: false, skills: [] });
    let resolveRetry!: (response: Response) => void;
    const retryGate = new Promise<Response>((resolve) => { resolveRetry = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], [minister("杨嗣昌"), minister("洪承畴")]));
      if (u.pathname.endsWith("/api/audience/scroll")) return jsonResp({ night_id: 23, messages: [{ role: "scene", speaker: "洪承畴", content: "入殿", beat: "entrance" }] });
      if (decodeURIComponent(u.pathname).endsWith("/api/ministers/杨嗣昌/chat")) return jsonResp({ campaign_id: "c", night_id: 23, minister: minister("杨嗣昌"), history: [], suggestions: [], can_undo_last_chat: false, reply_retry: { chat_turn_id: 7, minister_name: "洪承畴", turn: 1, question: "边务如何" } });
      if (decodeURIComponent(u.pathname).endsWith("/api/ministers/洪承畴/chat")) return jsonResp({ campaign_id: "c", night_id: 23, minister: minister("洪承畴"), history: [], suggestions: [], can_undo_last_chat: false });
      if (u.pathname.endsWith("/reply/retry") && init?.method === "POST") return retryGate;
      return jsonResp({});
    }));
    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[title="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll(".minister-card")).find((node) => node.textContent?.includes("杨嗣昌")));
    await act(async () => { await vi.waitFor(() => expect(findButton(host, "重新生成回话")).toBeTruthy()); });
    await click(findButton(host, "重新生成回话"));
    await click(host.querySelector('[aria-label="关闭弹窗"]'));
    await click(host.querySelector('[title="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll(".minister-card")).find((node) => node.textContent?.includes("洪承畴")));
    await tick();
    resolveRetry(jsonResp({ answer: "不应串写的旧回话", campaign_id: "c", night_id: 23, chat_turn_id: 7, history: [{ role: "minister", content: "不应串写的旧回话", chat_turn_id: 7 }], suggestions: [{ label: "旧建议", text: "旧建议" }], directives: [], can_undo_last_chat: true }));
    await tick();

    expect(host.textContent).not.toContain("不应串写的旧回话");
    expect(host.textContent).not.toContain("旧建议");
    expect(host.textContent).not.toContain("已重新生成回话。");
    expect(findButton(host, "撤回本轮")?.hasAttribute("disabled")).toBe(true);
  });

  it("名册点人只代发精确「宣X」，人物切换只消费服务端 next_minister", async () => {
    const requests: Array<{ minister: string; message: string }> = [];
    let streamCall = 0;
    const roster = [
      { id: "a", name: "温体仁", office: "首辅", summary: "", status: "active" },
      { id: "b", name: "周延儒", office: "次辅", summary: "", status: "active" },
    ];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], roster));
      if (u.pathname.endsWith("/chat/stream")) {
        requests.push({
          minister: decodeURIComponent(u.pathname.split("/").at(-3) || ""),
          message: JSON.parse(String(init?.body || "{}")).message,
        });
        streamCall += 1;
        return sseResp("done", {
          response: "臣遵旨", directives: [], pending_count: 0, suggestions: [],
          can_undo_last_chat: false, pending_action_failures: [],
          ...(streamCall === 1 ? { proposed_directive: { text: "着户部核饷" } } : {}),
          ...(streamCall === 2 ? { next_minister: "周延儒" } : {}),
        });
      }
      if (/\/api\/ministers\/[^/]+\/chat$/.test(u.pathname)) {
        const name = decodeURIComponent(u.pathname.split("/").at(-2) || "");
        return jsonResp({ minister: roster.find((m) => m.name === name), history: [], suggestions: [], campaign_id: "c1", night_id: 77, pending_turn_ids: [] });
      }
      if (u.pathname.endsWith("/api/audience/extraction/pending")) return jsonResp({ count: 0 });
      return jsonResp({});
    }));

    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[aria-label="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll("button")).find((b) => b.textContent?.includes("温体仁")));
    await tick();
    expect(host.querySelector('[aria-label="召对：温体仁"]')).not.toBeNull();

    for (let i = 0; i < 2; i += 1) {
      await click(host.querySelector('[aria-label="朝堂·召见大臣"]'));
      await tick();
      await click(Array.from(host.querySelectorAll("button")).find((b) => b.textContent?.includes("周延儒")));
      await tick();
      expect(requests[i]).toEqual({ minister: "温体仁", message: "宣周延儒" });
      expect(host.textContent).toContain(i === 0 ? "温体仁" : "周延儒");
      if (i === 0) {
        expect(host.textContent).not.toContain("对话内应允后，收夜提交即准旨");
        expect(host.textContent).not.toContain("核定（准/驳）");
      }
    }
  });

  it("#1684 晚到 next_minister 不抢回已切换的拟诏台", async () => {
    const roster = [
      { id: "a", name: "温体仁", office: "首辅", summary: "", status: "active" },
      { id: "b", name: "周延儒", office: "次辅", summary: "", status: "active" },
    ];
    let resolveStream!: (response: Response) => void;
    const streamGate = new Promise<Response>((resolve) => { resolveStream = resolve; });
    let streamStarted = false;
    let stateCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) {
        stateCalls += 1;
        return jsonResp(makeState(1, [directive()], roster));
      }
      if (u.pathname.endsWith("/chat/stream")) {
        streamStarted = true;
        return streamGate;
      }
      if (/\/api\/ministers\/[^/]+\/chat$/.test(u.pathname)) {
        const name = decodeURIComponent(u.pathname.split("/").at(-2) || "");
        return jsonResp({ minister: roster.find((m) => m.name === name), history: [], suggestions: [], campaign_id: "c1", night_id: 77, pending_turn_ids: [] });
      }
      if (u.pathname.endsWith("/api/audience/extraction/pending")) return jsonResp({ count: 0 });
      return jsonResp({});
    }));

    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[aria-label="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll("button")).find((b) => b.textContent?.includes("温体仁")));
    await tick();
    const textarea = host.querySelector("textarea")!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
      setter.call(textarea, "边务如何");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(findButton(host, "发送"));
    await act(async () => { await vi.waitFor(() => expect(streamStarted).toBe(true)); });

    await click(host.querySelector('[aria-label="关闭弹窗"]'));
    await click(findButton(host, "拟诏"));
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="诏书草案"]')).not.toBeNull());
    });

    const stateCallsBeforeDone = stateCalls;
    resolveStream(sseResp("done", {
      response: "臣遵旨", directives: [directive()], pending_count: 0, suggestions: [],
      can_undo_last_chat: false, pending_action_failures: [], next_minister: "周延儒",
    }));
    await act(async () => {
      await vi.waitFor(() => expect(stateCalls).toBeGreaterThan(stateCallsBeforeDone));
    });
    expect(host.querySelector('[role="dialog"][aria-label="诏书草案"]')).not.toBeNull();
    expect(findButton(host, "盖玺颁诏过月")?.hasAttribute("disabled")).toBe(false);
  });

  it("#1475 召对顶栏不重复左卡身份，横幅压成 bare 回收正文", async () => {
    const roster = [
      { id: "a", name: "曹化淳", office: "信邸内官（候补司礼监）", summary: "东厂", status: "active" },
    ];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], roster));
      if (/\/api\/ministers\/[^/]+\/chat$/.test(u.pathname)) {
        return jsonResp({
          minister: roster[0], history: [], suggestions: [],
          campaign_id: "c1", night_id: 77, pending_turn_ids: [],
        });
      }
      if (u.pathname.endsWith("/api/audience/extraction/pending")) return jsonResp({ count: 0 });
      if (u.pathname.endsWith("/api/audience/scroll")) return jsonResp({ night_id: 77, messages: [] });
      return jsonResp({});
    }));

    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[aria-label="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll("button")).find((b) => b.textContent?.includes("曹化淳")));
    await tick();

    const dialog = host.querySelector('[role="dialog"][aria-label="召对：曹化淳"]') as HTMLElement | null;
    expect(dialog).not.toBeNull();
    // a11y 标签保留；可见横幅标题删除——身份只在左卡一份
    expect(dialog!.querySelector(".modal-title")).toBeNull();
    expect(dialog!.querySelector(".modal-header-bare")).not.toBeNull();
    expect(dialog!.textContent || "").not.toMatch(/召对：/);

    const profile = dialog!.querySelector(".minister-profile");
    expect(profile).not.toBeNull();
    expect(profile!.textContent).toContain("曹化淳");
    expect(profile!.textContent).toContain("信邸内官（候补司礼监）");
    // 官衔不得在 dialog 内再出现第二份（左卡以外）
    const office = "信邸内官（候补司礼监）";
    const occurrences = (dialog!.textContent || "").split(office).length - 1;
    expect(occurrences).toBe(1);
  });

  it("退朝按钮与手输下朝都走召对 chat stream 同一收夜管线，不旁路 advance", async () => {
    const paths: string[] = [];
    const roster = [{ id: "a", name: "温体仁", office: "首辅", summary: "", status: "active" }];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      paths.push(`${init?.method || "GET"} ${u.pathname}`);
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], roster));
      if (u.pathname.endsWith("/api/decree/advance_without_edict")) return jsonResp({ state: makeState(2, [], roster), pending_action_failures: [] });
      if (u.pathname.endsWith("/chat/stream")) return sseResp("done", { response: "臣等恭送", directives: [], pending_count: 0, suggestions: [], can_undo_last_chat: false, pending_action_failures: [], court_action: "court_break" });
      if (/\/api\/ministers\/[^/]+\/chat$/.test(u.pathname)) return jsonResp({ minister: roster[0], history: [], suggestions: [], campaign_id: "c1", night_id: 77, pending_turn_ids: [] });
      if (u.pathname.endsWith("/api/audience/extraction/pending")) return jsonResp({ count: 0 });
      return jsonResp({});
    }));
    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[aria-label="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll("button")).find((b) => b.textContent?.includes("温体仁")));
    await tick();

    const textarea = host.querySelector("textarea") as HTMLTextAreaElement;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(textarea, "下朝");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(findButton(host, "发送"));
    await act(async () => {
      await vi.waitFor(() => expect(paths.some((path) => path.endsWith("/chat/stream"))).toBe(true));
    });

    const secondHost = document.createElement("div"); document.body.appendChild(secondHost);
    await act(async () => { trackRoot(secondHost).render(<App />); });
    await tick();
    await click(secondHost.querySelector('[aria-label="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(secondHost.querySelectorAll("button")).find((b) => b.textContent?.includes("温体仁")));
    await tick();
    await click(findButton(secondHost, "散夜"));
    await act(async () => {
      await vi.waitFor(() => expect(paths.filter((path) => path.endsWith("/chat/stream")).length).toBeGreaterThanOrEqual(2));
    });

    expect(paths.some((path) => path === "POST /api/decree/advance_without_edict")).toBe(false);
  });

  it("成功密令的 done 与 end 分别重读权威夜卷轴，且不显示系统通知", async () => {
    let sentSecretOrder: Record<string, unknown> | null = null;
    let scrollCalls = 0;
    let doneReached = false;
    let endReached = false;
    let streamController!: ReadableStreamDefaultController<Uint8Array>;
    const encoder = new TextEncoder();
    const minister = {
      name: "杨嗣昌", office: "兵部右侍郎", office_type: "兵部", faction: "",
      style: "", status: "active", status_label: "在朝", summary: "", favorite: false, skills: [],
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], [minister]));
      if (u.pathname.endsWith("/api/audience/extraction/pending")) return jsonResp({ count: 0 });
      if (u.pathname.endsWith("/api/audience/scroll")) {
        scrollCalls += 1;
        const messages = doneReached ? [
          { role: "user", speaker: "朕", content: "卷轴问话", chat_turn_id: 1 },
          { role: "minister", speaker: "杨嗣昌", content: "卷轴奏对", chat_turn_id: 1 },
          ...(endReached ? [{ role: "attendant", speaker: "王承恩", content: "卷轴递话", chat_turn_id: 1 }] : []),
        ] : [];
        return jsonResp({ night_id: 1, messages });
      }
      if (u.pathname.endsWith("/api/ministers/%E6%9D%A8%E5%97%A3%E6%98%8C/chat/stream") && init?.method === "POST") {
        sentSecretOrder = JSON.parse(String(init.body));
        return new Response(new ReadableStream<Uint8Array>({
          start(controller) { streamController = controller; },
        }), { status: 200, headers: { "Content-Type": "text/event-stream" } });
      }
      if (u.pathname.endsWith("/api/ministers/%E6%9D%A8%E5%97%A3%E6%98%8C/chat")) {
        return jsonResp({ minister, history: [], suggestions: [{ label: "机密差事", text: "", prefix: true, intent: "secret_order" }], pending_action_failures: [], pending_turn_ids: [], night_id: 1 });
      }
      return jsonResp({});
    }));

    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await act(async () => { await vi.waitFor(() => expect(findButton(host, "杨嗣昌")).toBeTruthy()); });
    await click(host.querySelector('[aria-label="朝堂·召见大臣"]'));
    await click(findButton(host, "杨嗣昌"));
    await act(async () => { await vi.waitFor(() => expect(host.querySelector('textarea')).not.toBeNull()); });

    await click(host.querySelector('[data-intent="secret_order"]'));
    const textarea = host.querySelector("textarea") as HTMLTextAreaElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set?.call(textarea, "整饬边备。");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(findButton(host, "发送"));
    await act(async () => {
      await vi.waitFor(() => expect(sentSecretOrder).not.toBeNull());
      expect(sentSecretOrder).toEqual({ message: "整饬边备。", intent: "secret_order" });
    });
    const beforeDone = scrollCalls;

    doneReached = true;
    await act(async () => {
      streamController.enqueue(encoder.encode(`event: done\ndata: ${JSON.stringify({
        history: [], suggestions: [], directives: [], pending_count: 0, pending_action_failures: [],
        can_undo_last_chat: true, secret_order_id: 7, night_id: 1,
      })}\n\n`));
    });
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector(".chat-message.pending, .chat-message.thinking")).toBeNull());
      await vi.waitFor(() => expect(scrollCalls).toBeGreaterThan(beforeDone));
      await vi.waitFor(() => expect(host.querySelector(".chat-message.user:not(.pending)")).not.toBeNull());
      expect(host.querySelector(".chat-message.minister:not(.thinking)")).not.toBeNull();
    });
    const beforeEnd = scrollCalls;
    expect(host.querySelector(".chat-message.attendant")).toBeNull();

    endReached = true;
    await act(async () => {
      streamController.enqueue(encoder.encode("event: end\ndata: {}\n\n"));
      streamController.close();
    });
    await act(async () => {
      await vi.waitFor(() => expect(scrollCalls).toBeGreaterThan(beforeEnd));
      await vi.waitFor(() => expect(host.querySelector(".chat-message.attendant")).not.toBeNull());
    });
    expect(host.querySelector(".chat-system-note")).toBeNull();
  });

  it("#1566 点机密差事不发、退出召对后再发普通问话，POST body 不带残留 intent", async () => {
    let sentChat: Record<string, unknown> | null = null;
    const minister = {
      name: "杨嗣昌", office: "兵部右侍郎", office_type: "兵部", faction: "",
      style: "", status: "active", status_label: "在朝", summary: "", favorite: false, skills: [],
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], [minister]));
      if (u.pathname.endsWith("/api/audience/extraction/pending")) return jsonResp({ count: 0 });
      if (u.pathname.endsWith("/api/audience/scroll")) return jsonResp({ night_id: 1, messages: [] });
      if (u.pathname.endsWith("/api/ministers/%E6%9D%A8%E5%97%A3%E6%98%8C/chat/stream") && init?.method === "POST") {
        sentChat = JSON.parse(String(init.body));
        return sseResp("done", {
          history: [], suggestions: [], directives: [], pending_count: 0,
          pending_action_failures: [], can_undo_last_chat: false, night_id: 1,
        });
      }
      if (u.pathname.endsWith("/api/ministers/%E6%9D%A8%E5%97%A3%E6%98%8C/chat")) {
        return jsonResp({
          minister, history: [],
          suggestions: [{ label: "机密差事", text: "", prefix: true, intent: "secret_order" }],
          pending_action_failures: [], pending_turn_ids: [], night_id: 1,
        });
      }
      return jsonResp({});
    }));

    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { trackRoot(host).render(<App />); });
    await act(async () => { await vi.waitFor(() => expect(findButton(host, "杨嗣昌")).toBeTruthy()); });
    await click(host.querySelector('[aria-label="朝堂·召见大臣"]'));
    await click(findButton(host, "杨嗣昌"));
    await act(async () => { await vi.waitFor(() => expect(host.querySelector("textarea")).not.toBeNull()); });

    await click(host.querySelector('[data-intent="secret_order"]'));
    await click(findButton(host, "退出召对"));
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector("textarea")).toBeNull());
    });

    await click(host.querySelector('[aria-label="朝堂·召见大臣"]'));
    await click(findButton(host, "杨嗣昌"));
    await act(async () => { await vi.waitFor(() => expect(host.querySelector("textarea")).not.toBeNull()); });

    const textarea = host.querySelector("textarea") as HTMLTextAreaElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set?.call(textarea, "边事如何？");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click(findButton(host, "发送"));
    await act(async () => {
      await vi.waitFor(() => expect(sentChat).not.toBeNull());
    });
    expect(sentChat).toEqual({ message: "边事如何？" });
    expect(sentChat).not.toHaveProperty("intent");
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
    await act(async () => { trackRoot(host).render(<App />); });
    await tick();
    expect(host.querySelector(".hud2-stage")).not.toBeNull();  // 进入游戏视图（旧草案在飞刷新已发出、挂起）

    await click(findButton(host, "拟诏"));  // 开诏书草案模态
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
      // makeState(1) → currentTurn=1；真实谓词认 turn-1 的 dossier_progress。
      const autoOpenOrder = {
        id: 1, title: "密", content: "", status: "active", minister_name: "",
        year_issued: 1627, period_issued: 10,
        dossier_progress: [{ turn: 0 }],
      };
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
        if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [autoOpenOrder] });
        if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
        if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1));
        return jsonResp({});
      }));
      const host = document.createElement("div");
      document.body.appendChild(host);
      await act(async () => { trackRoot(host).render(<App />); });
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });   // 冲刷挂载 fetch，换回合 effect 起 autoOpen 定时器
      expect(secretDialog(host)).toBeNull();                             // 未到点：真实对话框未开
      await act(async () => { await vi.advanceTimersByTimeAsync(400); }); // 400ms 到点、仍最新代次 → open()
      expect(secretDialog(host)).not.toBeNull();                         // 密令进度对话框已弹（协调器定时器 fire）
    } finally { vi.useRealTimers(); }
  });

  it("延迟呈现负路：定时器计时中经真实变更(删草案)推进代次→陈旧定时器 no-op，密令进度不弹", async () => {
    vi.useFakeTimers();
    try {
      const autoOpenOrder = {
        id: 1, title: "密", content: "", status: "active", minister_name: "",
        year_issued: 1627, period_issued: 10,
        dossier_progress: [{ turn: 0 }],
      };
      vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/api/directives/1") && init?.method === "DELETE") return jsonResp({ directives: [] });
        if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
        if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [autoOpenOrder] });
        if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
        if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [directive()]));
        return jsonResp({});
      }));
      const host = document.createElement("div");
      document.body.appendChild(host);
      await act(async () => { trackRoot(host).render(<App />); });
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });   // 冲刷挂载：autoOpen 400ms 定时器已排程（尚未到点）
      expect(secretDialog(host)).toBeNull();

      // 计时期间执行一次真实变更（删草案）：deleteDirective 调 beginDurableMutation 推进代次
      await act(async () => { (findButton(host, "拟诏"))?.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
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
    await act(async () => { trackRoot(host).render(<App />); });
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

  // #1499：main.tsx 政务失败恢复调用点——经拟诏「处理」真链触发，不得日后误传 hideTitle。
  it("#1499 经真实 App 拟诏处理入口触发政务失败恢复：标题可见且非 bare 布局", async () => {
    const failure = {
      id: 42,
      kind: "secret_order",
      action: "落库",
      message: "密令未能正式落库",
      retryable: true,
      // 无 minister_name → selectedMinister 空 → activeMinister null → 走 recovery 分支
    };
    try {
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
        if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
        if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
        if (u.pathname.endsWith("/api/game/state")) {
          // 无草案 + 有失败密令 → 拟诏台露出「处理」入口
          return jsonResp({ ...makeState(1, []), failed_secret_order_count: 1 });
        }
        if (u.pathname.endsWith("/api/pending_actions/failures")) {
          return jsonResp({ pending_action_failures: [failure] });
        }
        return jsonResp({});
      }));
      const host = document.createElement("div");
      document.body.appendChild(host);
      await act(async () => { trackRoot(host).render(<App />); });
      await tick();
      expect(host.querySelector(".hud2-stage")).not.toBeNull();

      await click(findButton(host, "拟诏"));
      await act(async () => {
        await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="诏书草案"]')).not.toBeNull());
      });
      const processBtn = Array.from(host.querySelectorAll("button")).find((b) => (b.textContent || "").includes("处理"));
      expect(processBtn).toBeTruthy();
      await click(processBtn);

      await act(async () => {
        await vi.waitFor(() => {
          expect(host.querySelector('[role="dialog"][aria-label="政务失败恢复"]')).not.toBeNull();
        });
      });
      const dialog = host.querySelector('[role="dialog"][aria-label="政务失败恢复"]') as HTMLElement;
      // 可见标题（main 未传 hideTitle）
      expect(dialog.querySelector(".modal-title h1")?.textContent).toContain("政务失败恢复");
      const modal = dialog.querySelector(".fullscreen-modal.modal-bg-chat");
      expect(modal).not.toBeNull();
      expect(modal!.classList.contains("modal-layout-bare")).toBe(false);
      expect(dialog.querySelector(".modal-header-bare")).toBeNull();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

// ─── #1236 T3：必达三面 / 只读组零半程泄漏 —— App 真挂载 ───────────────────

const SNAP_TREASURY = 1781;
const SNAP_INNER = 320;
const SNAP_MINXIN = 55;
const SNAP_HUANGWEI = 40;
const SNAP_LEGACY = "月初赈恤令";
const SNAP_MINISTER = "月初辅臣";
const SNAP_CONSORT = "月初妃嫔";
const SNAP_BUILDING = "月初城防";
const SNAP_MEMORIAL = "月初奏报正文";
// #671：含首尾空白与 markdown 标记——唯一 App→DOM 官方邸报逐字契约
const SNAP_GAZETTE = "\n  **上月邸报**\n- 军前缺饷\n  ";
// #671：含 markdown/空白特征的原文常量——证明 App 接线不经 strip
const SNAP_ATTENDANT = "  奴婢启禀：\n**洪承畴**已抵京候旨。  ";
const SNAP_CLOSED = "月初已结边饷";
// #1366：全军理论应发（结算前事实）+ 已结算边饷 hub 三项（结算后结果），同一 settled_turn。
const SNAP_ARMY_PAY_DUE = 72;
const SNAP_ARMY_PAY_DISBURSED = 60;
const SNAP_ARMY_PAY_ARRIVED = 50;
const SNAP_ARMY_PAY_LOSS = 10;
const SNAP_ARMY_PAY_SETTLED_TURN = 4;
const MIDCOURSE_ISSUE = "半程军饷议题";
const MIDCOURSE_ARMY = "半程边军";
const MIDCOURSE_REGION = "半程辽东";

const validDecision = {
  idx: 0,
  title: "辽东战守",
  context: "如何处置",
  options: [{ label: "固守", hint: "稳" }],
};

const snapBudget = (balance: number) => ({
  balance,
  income: [{ name: "田赋", amount: 100 }],
  expense: [{ name: "军饷", amount: 80 }],
  income_total: 100,
  expense_total: 80,
  net: 20,
  movements: [],
  movements_total: 0,
});

const settlementBaseState = (phase: string, extra: Record<string, unknown> = {}) => ({
  turn: { year: 1627, period: 10, turn: 5, phase, settlement_display: true },
  metrics: { 民心: SNAP_MINXIN, 皇威: SNAP_HUANGWEI, 国库: SNAP_TREASURY, 内库: SNAP_INNER },
  previous_summary: "",
  issues: [{ id: 9, kind: "situation", title: MIDCOURSE_ISSUE, status: "open", progress: 77, fail_condition: "" }],
  legacies: [{
    id: 1, name: SNAP_LEGACY, narrative_hint: "",
    modifiers: {}, effect_text: "民心+1", remaining_months: 3, clear_condition: "",
  }],
  closed_this_turn: [{
    id: 2, kind: "situation", title: SNAP_CLOSED, status: "resolved",
    bar_value: 0, bar_good_meaning: "妥", bar_bad_meaning: "",
    closed_turn: 4, stage_text: "", effect: {},
  }],
  budget: {
    国库: snapBudget(SNAP_TREASURY), 内库: snapBudget(SNAP_INNER),
    army_pay_due_total: SNAP_ARMY_PAY_DUE,
    settled_army_pay: {
      settled_turn: SNAP_ARMY_PAY_SETTLED_TURN,
      treasury_disbursed: SNAP_ARMY_PAY_DISBURSED,
      actual_arrived: SNAP_ARMY_PAY_ARRIVED,
      transit_loss: SNAP_ARMY_PAY_LOSS,
    },
  },
  region_warning: "", army_warning: "", power_warning: "", powers: [],
  victory_status: { status: "", summary: "" }, ending: null,
  events: [{ id: 1, title: "月初题本" }],
  regions: [{ id: "r1", name: MIDCOURSE_REGION }],
  // #321：共享 App 夹具须满足 Army exact ABI（含必填 arrears_text/morale_text/mutiny_tier）
  armies: [{
    id: "a1",
    name: MIDCOURSE_ARMY,
    station: "辽东",
    theater: "辽东",
    commander: "边将",
    controller: "兵部",
    troop_type: "边军",
    manpower: 10000,
    army_needed: 10,
    supply: 50,
    morale_text: "士气：不振",
    training: 50,
    equipment: 50,
    arrears_text: "无欠饷",
    mobility: 50,
    mutiny_tier: "一般",
    status: "驻防",
    owner_power: "ming",
  }],
  map_nodes: [{
    id: "liaodong", name: "辽东", kind: "region", label: "辽东",
    buildings: [{
      id: "b1", name: SNAP_BUILDING, category: "城防", level: 2,
      condition: 90, maintenance: 1, output_metric: "", output_amount: 0,
    }],
    region: { name: "辽东", controlled_by: "" },
  }],
  ministers: [{
    name: SNAP_MINISTER, office: "首辅", office_type: "内阁", faction: "",
    style: "", status: "active", status_label: "在朝", summary: "辅臣", favorite: false, skills: [],
  }],
  consorts: [{
    name: SNAP_CONSORT, title: "贵妃", status: "active", status_label: "在宫",
    summary: "", favorite: false, skills: [],
  }],
  directives: [{ id: 1, text: "半程拟诏草稿", status: "draft" }],
  pending_count: 0, last_decree: "", last_report: SNAP_MEMORIAL,
  pending_decisions: [],
  ...extra,
});

const stubSettlementFetch = (state: unknown) => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const u = new URL(String(url), "http://t.local");
    if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
    if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
    if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
    if (u.pathname.endsWith("/api/game/state")) return jsonResp(state);
    if (u.pathname.endsWith("/api/history/turns")) return jsonResp({
      turns: [{ kind: "month", turn: 4, year: 1627, period: 9, has_report: true, has_attendant: false, has_directive: true }],
    });
    if (u.pathname.includes("/api/history/turn/")) return jsonResp({
      turn: 4, year: 1627, period: 9, report: SNAP_GAZETTE, decree: "",
    });
    if (u.pathname.endsWith("/api/court_layout")) return jsonResp({ layout: "{}" });
    return jsonResp({});
  }));
};

const mountApp = async () => {
  const host = document.createElement("div");
  document.body.appendChild(host);
  await act(async () => { trackRoot(host).render(<App />); });
  await act(async () => {
    await vi.waitFor(() => expect(host.querySelector(".hud2-stage")).not.toBeNull());
  });
  return host;
};

const byAria = (host: HTMLElement, label: string) =>
  host.querySelector(`[aria-label="${label}"]`) as HTMLElement | null;

describe("#1236 App must-face wiring（settlement_display 真链）", () => {
  it("phase===settling：续跑入口可点；刷新重挂后仍在", async () => {
    stubSettlementFetch(settlementBaseState("settling"));
    const host = await mountApp();
    const resume = host.querySelector('[data-testid="settle-resume"] button') as HTMLButtonElement | null;
    expect(resume).not.toBeNull();
    expect(resume!.disabled).toBe(false);
    expect(resume!.textContent).toContain("续跑结算");
    // 核账递话条同屏（展示态真源），不挡续跑
    expect(host.querySelector("[data-testid=wang-settlement-slip]")).not.toBeNull();

    // 刷新口径：busy 空 + phase 仍 settling → 重挂仍可达
    unmountTrackedRoots();
    const host2 = await mountApp();
    const resume2 = host2.querySelector('[data-testid="settle-resume"] button') as HTMLButtonElement | null;
    expect(resume2).not.toBeNull();
    expect(resume2!.disabled).toBe(false);
  });

  it("awaiting_decision + 合法 pending：DecisionModal 可点；刷新重挂后仍在", async () => {
    stubSettlementFetch(settlementBaseState("awaiting_decision", {
      pending_decisions: [validDecision],
    }));
    const host = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[data-testid="decision-modal"]')).not.toBeNull());
    });
    const modal = host.querySelector('[data-testid="decision-modal"]')!;
    expect(modal.textContent).toContain("辽东战守");
    const action = Array.from(modal.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("批") || (b.textContent || "").includes("固守"),
    ) as HTMLButtonElement | undefined;
    expect(action).toBeTruthy();
    expect(action!.disabled).toBe(false);

    unmountTrackedRoots();
    const host2 = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host2.querySelector('[data-testid="decision-modal"]')).not.toBeNull());
    });
    expect(host2.querySelector('[data-testid="decision-modal"]')!.textContent).toContain("辽东战守");
  });

  it("awaiting_decision + 损坏 pending：DecisionRecoveryPanel 可点；刷新重挂后仍在", async () => {
    stubSettlementFetch(settlementBaseState("awaiting_decision", {
      pending_decisions: [{ broken: true }],
    }));
    const host = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[data-testid="decision-recovery"]')).not.toBeNull());
    });
    const panel = host.querySelector('[data-testid="decision-recovery"]')!;
    expect(panel.textContent).toMatch(/批红|待批/);
    const retry = panel.querySelector("button") as HTMLButtonElement | null;
    expect(retry).not.toBeNull();
    expect(retry!.disabled).toBe(false);
    expect(retry!.textContent).toContain("重新拉取");

    unmountTrackedRoots();
    const host2 = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host2.querySelector('[data-testid="decision-recovery"]')).not.toBeNull());
    });
    expect((host2.querySelector('[data-testid="decision-recovery"] button') as HTMLButtonElement).disabled).toBe(false);
  });

  it("#1620 落印 SSE error 挂 decision-recovery", async () => {
    const state = settlementBaseState("awaiting_decision", {
      pending_decisions: [validDecision],
    });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(state);
      if (u.pathname.endsWith("/api/history/turns")) return jsonResp({
        turns: [{ kind: "month", turn: 4, year: 1627, period: 9, has_report: true, has_attendant: false, has_directive: true }],
      });
      if (u.pathname.includes("/api/history/turn/")) return jsonResp({
        turn: 4, year: 1627, period: 9, report: SNAP_GAZETTE, decree: "",
      });
      if (u.pathname.endsWith("/api/court_layout")) return jsonResp({ layout: "{}" });
      if (u.pathname.endsWith("/api/decree/resolve_decisions/stream")) {
        return sseResp("error", { message: "stream-fail" });
      }
      return jsonResp({});
    }));
    const host = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[data-testid="decision-modal"]')).not.toBeNull());
    });
    const option = Array.from(host.querySelectorAll("button")).find((b) =>
      (b.textContent || "").includes("固守"),
    ) as HTMLButtonElement | undefined;
    expect(option).toBeTruthy();
    await click(option);
    const seal = host.querySelector('[aria-label="批红落印，续推时局"]') as HTMLButtonElement | null;
    expect(seal).not.toBeNull();
    await click(seal);
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[data-testid="decision-recovery"]')).not.toBeNull());
    });
  });

  it("#1418 r2 awaiting + 全员 decided + settlement_display：接到 settle-resume，不重开批红", async () => {
    const decided = { ...validDecision, status: "decided", choice: { label: "固守" } };
    stubSettlementFetch(settlementBaseState("awaiting_decision", {
      pending_decisions: [decided],
    }));
    const host = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[data-testid="settle-resume"]')).not.toBeNull());
    });
    // 续跑面可点；批红弹窗/损坏恢复横幅均不出现
    expect(host.querySelector('[data-testid="decision-modal"]')).toBeNull();
    expect(host.querySelector('[data-testid="decision-recovery"]')).toBeNull();
    const resume = host.querySelector('[data-testid="settle-resume"] button') as HTMLButtonElement;
    expect(resume.disabled).toBe(false);
    expect(resume.textContent).toContain("续跑结算");

    // 刷新重挂仍在
    unmountTrackedRoots();
    const host2 = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host2.querySelector('[data-testid="settle-resume"]')).not.toBeNull());
    });
    expect(host2.querySelector('[data-testid="decision-modal"]')).toBeNull();
  });

  it("#1418 r2 负向：全员 decided 但快照已清 → 不挂 settle-resume", async () => {
    const decided = { ...validDecision, status: "decided", choice: { label: "固守" } };
    stubSettlementFetch({
      ...settlementBaseState("awaiting_decision", { pending_decisions: [decided] }),
      turn: { year: 1627, period: 10, turn: 5, phase: "awaiting_decision", settlement_display: false },
    });
    const host = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector(".hud2-stage")).not.toBeNull());
    });
    expect(host.querySelector('[data-testid="settle-resume"]')).toBeNull();
    expect(host.querySelector('[data-testid="decision-modal"]')).toBeNull();
  });
});

const closeOpenOverlay = async (host: HTMLElement) => {
  const closer =
    host.querySelector('[aria-label="关闭弹窗"]')
    || host.querySelector('.right-drawer.open [aria-label="收起"]')
    || host.querySelector('.court-drawer.open [aria-label="收起"]')
    || host.querySelector('.harem-drawer.open [aria-label="收起"]')
    || host.querySelector("button.drawer-scrim")
    || document.querySelector('[aria-label="关闭"]');
  if (closer) await click(closer);
  await tick();
};

const cmdByCaption = (host: HTMLElement, caption: string) =>
  Array.from(host.querySelectorAll("button")).find((b) => (b.getAttribute("aria-label") || "").startsWith(`${caption}：`)) || null;

describe("#1236 App readonly zero mid-course leak（逐面审计）", () => {
  it("只读组逐面可达且吃月初叠影；关闭组不可达且半程面不泄漏", async () => {
    // phase=settling：续跑小条不挡 HUD；settlement_display 叠影照常
    // #1366：核账期（settling/awaiting_decision）不得下发半程已结算三项——只给结算前
    // 事实（全军名义应发），settled_army_pay 由后端置 null，与顶栏月初快照同一展示边界。
    stubSettlementFetch({
      ...settlementBaseState("settling"),
      budget: { ...settlementBaseState("settling").budget, settled_army_pay: null },
    });
    const host = await mountApp();

    // 顶栏快照四键 + 核账标（legacies / economy 同源叠影）
    expect(host.textContent).toContain("· 核账");
    expect(host.textContent).toContain(`${SNAP_TREASURY}万两`);
    expect(host.textContent).toContain(`${SNAP_INNER}万两`);
    expect(host.textContent).toContain(String(SNAP_MINXIN));
    expect(host.textContent).toContain(String(SNAP_HUANGWEI));
    expect(host.querySelector('[data-testid="settle-resume"]')).not.toBeNull();

    // 关闭组：半程局势不渲染；只读 closed_issues 仍可达（上月已结入口不关死）
    expect(host.textContent).not.toContain(MIDCOURSE_ISSUE);
    expect(host.querySelector(".situation-list")).toBeNull();
    expect(host.querySelector(".situation-closed-list")).not.toBeNull();
    expect(host.textContent).toContain(SNAP_CLOSED);
    expect(byAria(host, "省份列表")?.getAttribute("aria-disabled")).toBe("true");
    expect(byAria(host, "军队列表")?.getAttribute("aria-disabled")).toBe("true");
    // 点关闭组导航：抽屉不得进入 .open（子树可常挂，以 open 态为准）
    await click(byAria(host, "省份列表"));
    await tick();
    expect(host.querySelector(".right-drawer-region.open")).toBeNull();
    await click(byAria(host, "军队列表"));
    await tick();
    expect(host.querySelector(".right-drawer-army.open")).toBeNull();

    // 密令/拟诏关闭
    await click(cmdByCaption(host, "密令"));
    await tick();
    expect(host.querySelector('[role="dialog"][aria-label="密令进度"]')).toBeNull();
    await click(cmdByCaption(host, "拟诏·盖玺颁诏过月"));
    await tick();
    expect(host.querySelector('[role="dialog"][aria-label="诏书草案"]')).toBeNull();

    // legacies：顶栏帝国修正可开，内容=月初标记
    const legacyBtn = byAria(host, "现行帝国修正");
    expect(legacyBtn).not.toBeNull();
    await click(legacyBtn);
    await tick();
    expect(document.body.textContent).toContain(SNAP_LEGACY);
    await closeOpenOverlay(host);

    // economy：户部抽屉可开，余额=月初
    await click(byAria(host, "经济面板"));
    await tick();
    const economyOpen = host.querySelector(".right-drawer-economy.open");
    expect(economyOpen).not.toBeNull();
    expect(economyOpen!.textContent).toContain(`${SNAP_TREASURY}万两`);
    // #1366：结算前只见事实（全军名义应发）；核账期半程结果（国库实拨/实际到达/途中损耗）
    // 不下发不渲染——待整月推进完成才见同一 settled_turn 的三项结果（见下方独立用例）。
    expect(economyOpen!.textContent).toContain(`${SNAP_ARMY_PAY_DUE}万两`);
    expect(economyOpen!.textContent).not.toContain(`${SNAP_ARMY_PAY_DISBURSED}万两`);
    expect(economyOpen!.textContent).not.toContain(`${SNAP_ARMY_PAY_ARRIVED}万两`);
    expect(economyOpen!.textContent).not.toContain(`${SNAP_ARMY_PAY_LOSS}万两`);
    expect(economyOpen!.textContent).not.toContain(`第 ${SNAP_ARMY_PAY_SETTLED_TURN} 月`);
    await closeOpenOverlay(host);
    expect(host.querySelector(".right-drawer-economy.open")).toBeNull();

    // building：工部建筑可开，吃月初名
    await click(byAria(host, "建筑列表"));
    await tick();
    const buildingOpen = host.querySelector(".right-drawer-building.open");
    expect(buildingOpen).not.toBeNull();
    expect(buildingOpen!.textContent).toContain(SNAP_BUILDING);
    // 半程省/兵抽屉仍不得被连带打开
    expect(host.querySelector(".right-drawer-region.open")).toBeNull();
    expect(host.querySelector(".right-drawer-army.open")).toBeNull();
    await closeOpenOverlay(host);

    // court roster：名册可读、召对写入口拔除
    await click(byAria(host, "朝堂·召见大臣"));
    await tick();
    expect(host.querySelector(".court-drawer.open")).not.toBeNull();
    expect(host.querySelector(".court-drawer.open")!.textContent).toContain(SNAP_MINISTER);
    const courtCard = Array.from(host.querySelectorAll(".court-drawer.open button.minister-card")).find((b) =>
      (b.textContent || "").includes(SNAP_MINISTER),
    ) as HTMLButtonElement | undefined;
    expect(courtCard?.disabled).toBe(true);
    await closeOpenOverlay(host);

    // appointment roster
    await click(byAria(host, "官员任免"));
    await tick();
    const apptOpen = host.querySelector(".right-drawer-appointment.open");
    expect(apptOpen).not.toBeNull();
    expect(apptOpen!.textContent).toContain(SNAP_MINISTER);
    const apptRow = apptOpen!.querySelector("button.right-drawer-row-minister") as HTMLButtonElement | null;
    expect(apptRow?.disabled).toBe(true);
    await closeOpenOverlay(host);

    // harem roster
    await click(byAria(host, "后宫"));
    await tick();
    const haremOpen = host.querySelector(".harem-drawer.open");
    expect(haremOpen).not.toBeNull();
    expect(haremOpen!.textContent).toContain(SNAP_CONSORT);
    const haremCard = Array.from(haremOpen!.querySelectorAll("button.minister-card")).find((b) =>
      (b.textContent || "").includes(SNAP_CONSORT),
    ) as HTMLButtonElement | undefined;
    expect(haremCard?.disabled).toBe(true);
    await closeOpenOverlay(host);

    // memorials：只读可达；内容闸吃 situation——核账期零半程泄漏（#1236 正向断言）
    await click(cmdByCaption(host, "奏疏"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="奏疏"]')).not.toBeNull());
    });
    const memorialsDialog = host.querySelector('[role="dialog"][aria-label="奏疏"]')!;
    expect(memorialsDialog.textContent).not.toContain(MIDCOURSE_ISSUE);
    expect(memorialsDialog.querySelector(".situation-list")).toBeNull();
    expect(memorialsDialog.textContent).toContain(SETTLEMENT_CLOSED_REASON);
    expect(memorialsDialog.textContent).not.toContain(SNAP_MEMORIAL);
    await closeOpenOverlay(host);

    // history：史册可开，月档列表来自状态口同源只读 API
    await click(cmdByCaption(host, "史册"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="史册：历代奏报、诏书与递话"]')).not.toBeNull());
    });
    expect(host.querySelector('[role="dialog"][aria-label="史册：历代奏报、诏书与递话"]')!.textContent).toMatch(/1627\s*年\s*9\s*月/);
    await closeOpenOverlay(host);

    // audience_archive：史册头起居注另入口可开
    await click(cmdByCaption(host, "史册"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(findButton(host, "起居注")).toBeTruthy());
    });
    await click(findButton(host, "起居注"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="起居注：召对记录"]')).not.toBeNull());
    });
    await closeOpenOverlay(host);

    // menu：可开；存档允许
    await click(byAria(host, "游戏菜单"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(findButton(host, "保存")).toBeTruthy());
    });
    await closeOpenOverlay(host);

    // closed_issues：只读可达；半程议题零泄漏；不误弹局势了结全屏
    expect(host.querySelector(".situation-closed-list")).not.toBeNull();
    expect(host.textContent).toContain(SNAP_CLOSED);
    expect(host.textContent).not.toContain(MIDCOURSE_ISSUE);
    expect(host.querySelector('[role="dialog"][aria-label="局势了结"]')).toBeNull();
  });

  it("phase=awaiting_decision：核账门控唯一谓词=settlement_display，同样隐藏半程结算三项", async () => {
    // #1366：AWAITING_DECISION 与 settling 语义相同（FRONT_HALF_DONE_PHASES），真实 HITL
    // 暂停落在此相位；核账门控只认 settlement_display（main.tsx#460），readonly 面同可达。
    const decided = { ...validDecision, status: "decided", choice: { label: "固守" } };
    stubSettlementFetch({
      ...settlementBaseState("awaiting_decision", { pending_decisions: [decided] }),
      budget: {
        ...settlementBaseState("awaiting_decision").budget,
        settled_army_pay: null,
      },
    });
    const host = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[data-testid="settle-resume"]')).not.toBeNull());
    });
    await click(byAria(host, "经济面板"));
    await tick();
    const economyOpen = host.querySelector(".right-drawer-economy.open");
    expect(economyOpen).not.toBeNull();
    expect(economyOpen!.textContent).toContain(`${SNAP_ARMY_PAY_DUE}万两`);
    expect(economyOpen!.textContent).not.toContain(`${SNAP_ARMY_PAY_DISBURSED}万两`);
    expect(economyOpen!.textContent).not.toContain(`${SNAP_ARMY_PAY_ARRIVED}万两`);
    expect(economyOpen!.textContent).not.toContain(`${SNAP_ARMY_PAY_LOSS}万两`);
  });

  it("gazette：核账期邸报（上月）可读且正文=状态口 previous_summary（isFaceReachable 真链）", async () => {
    // #1356 F4：App 接缝——previous_* 与 turn.reign_period_label 同给，报头不得混充当前月
    // #671：唯一官方邸报 App→DOM 逐字契约（咬 state trim / prop trim / strip 三处）
    // #671：last_attendant_message 经 App 接线可达 gazette-attendant（不经 strip；在 document 外）
    stubSettlementFetch(settlementBaseState("player", {
      previous_summary: SNAP_GAZETTE,
      previous_reign_period_label: "天启七年九月",
      last_attendant_message: SNAP_ATTENDANT,
      turn: {
        year: 1627,
        period: 10,
        turn: 5,
        phase: "player",
        settlement_display: true,
        reign_period_label: "天启七年十月",
      },
      pending_decisions: [],
    }));
    const host = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="邸报"]')).not.toBeNull());
    });
    // 官方邸报 pre 正文与状态口 previous_summary 逐字相等（含空白与 markdown）
    expect(host.querySelector("pre.memorial-text")!.textContent).toBe(SNAP_GAZETTE);
    const masthead = host.querySelector(".gazette-masthead")?.textContent || "";
    expect(masthead).toContain("天启七年九月");
    expect(masthead).not.toContain("天启七年十月");
    // #671 App 接线：递话可见且位于 .gazette-document 之外
    const attendant = host.querySelector("[data-testid=gazette-attendant]");
    expect(attendant).not.toBeNull();
    expect(attendant!.textContent).toContain(SNAP_ATTENDANT);
    expect(attendant!.closest(".gazette-document")).toBeNull();
    // 半程议题仍不泄漏；上月已结只读面可同屏
    expect(host.textContent).not.toContain(MIDCOURSE_ISSUE);
    expect(host.querySelector(".situation-closed-list")).not.toBeNull();
    expect(host.textContent).toContain(SNAP_CLOSED);
  });

  it("gazette：仅有 last_attendant_message 时核账期仍自动弹邸报", async () => {
    // #671：attendant-only 月完——自动门槛认递话存在，dialog 含原文
    stubSettlementFetch(settlementBaseState("player", {
      previous_summary: "",
      previous_reign_period_label: "天启七年九月",
      last_attendant_message: SNAP_ATTENDANT,
      turn: {
        year: 1627,
        period: 10,
        turn: 5,
        phase: "player",
        settlement_display: true,
        reign_period_label: "天启七年十月",
      },
      pending_decisions: [],
    }));
    const host = await mountApp();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="邸报"]')).not.toBeNull());
    });
    const attendant = host.querySelector("[data-testid=gazette-attendant]");
    expect(attendant).not.toBeNull();
    expect(attendant!.textContent).toContain(SNAP_ATTENDANT);
  });

  it("月完后 settlement_display=false：关闭组入口恢复；递话条收；局势半程面重现", async () => {
    stubSettlementFetch({
      ...settlementBaseState("player"),
      turn: { year: 1627, period: 10, turn: 5, phase: "player", settlement_display: false },
      previous_summary: "",
      pending_decisions: [],
    });
    const host = await mountApp();
    expect(host.querySelector("[data-testid=wang-settlement-slip]")).toBeNull();
    expect(host.textContent).not.toContain("· 核账");
    expect(byAria(host, "省份列表")?.getAttribute("aria-disabled")).toBe("false");
    expect(byAria(host, "军队列表")?.getAttribute("aria-disabled")).toBe("false");
    // 局势（半程）与上月已结一并恢复
    expect(host.querySelector(".situation-panel")).not.toBeNull();
    expect(host.textContent).toContain(MIDCOURSE_ISSUE);
    expect(host.querySelector(".situation-closed-list")).not.toBeNull();
    expect(host.textContent).toContain(SNAP_CLOSED);
    // #1366：next_period 完成、月初快照过期后，同一 settled turn 的三项结果才可见
    // （settlementBaseState 默认 budget.settled_army_pay 非 null）。
    await click(byAria(host, "经济面板"));
    await tick();
    const economyOpen = host.querySelector(".right-drawer-economy.open");
    expect(economyOpen).not.toBeNull();
    expect(economyOpen!.textContent).toContain(`${SNAP_ARMY_PAY_DUE}万两`);
    expect(economyOpen!.textContent).toContain(`${SNAP_ARMY_PAY_DISBURSED}万两`);
    expect(economyOpen!.textContent).toContain(`${SNAP_ARMY_PAY_ARRIVED}万两`);
    expect(economyOpen!.textContent).toContain(`${SNAP_ARMY_PAY_LOSS}万两`);
    expect(economyOpen!.textContent).toContain(`第 ${SNAP_ARMY_PAY_SETTLED_TURN} 月`);
    await closeOpenOverlay(host);
    // 关闭组命令可再开
    await click(cmdByCaption(host, "密令"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="密令进度"]')).not.toBeNull());
    });
    await closeOpenOverlay(host);
    await click(cmdByCaption(host, "拟诏·盖玺颁诏过月"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="诏书草案"]')).not.toBeNull());
    });
  });

  it("#1285 非核账：奏疏模态呈 situation 议题列表（同 settlementBaseState 工厂）", async () => {
    stubSettlementFetch({
      ...settlementBaseState("player"),
      turn: { year: 1627, period: 10, turn: 5, phase: "player", settlement_display: false },
      previous_summary: "",
      pending_decisions: [],
    });
    const host = await mountApp();
    await click(cmdByCaption(host, "奏疏"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="奏疏"]')).not.toBeNull());
    });
    const memorialsDialog = host.querySelector('[role="dialog"][aria-label="奏疏"]')!;
    expect(memorialsDialog.querySelector(".situation-panel")).not.toBeNull();
    expect(memorialsDialog.textContent).toContain(MIDCOURSE_ISSUE);
    expect(memorialsDialog.textContent).not.toContain(SETTLEMENT_CLOSED_REASON);
  });

  it("#1342 朝堂抽屉开着时点拟诏：关抽屉并开拟诏台", async () => {
    stubSettlementFetch({
      ...settlementBaseState("player"),
      turn: { year: 1627, period: 10, turn: 5, phase: "player", settlement_display: false },
      previous_summary: "",
      pending_decisions: [],
    });
    const host = await mountApp();
    await click(byAria(host, "朝堂·召见大臣"));
    await tick();
    expect(host.querySelector(".court-drawer.open")).not.toBeNull();
    await click(cmdByCaption(host, "拟诏·盖玺颁诏过月"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="诏书草案"]')).not.toBeNull());
    });
    expect(host.querySelector(".court-drawer.open")).toBeNull();
    // #1277：drafts>0 副标题名实——去「退朝」描述，与页脚盖玺颁诏过月自洽。
    const edictDialog = host.querySelector('[role="dialog"][aria-label="诏书草案"]');
    expect(edictDialog?.textContent).toContain("盖玺颁诏即草案成案并过月");
    expect(edictDialog?.textContent).not.toContain("退朝即草案成案并过月");
  });

  it("#1454 拟诏台开着：木牌改收起可点关掉，层带安全区且主钮仍独占盖玺文案", async () => {
    stubSettlementFetch({
      ...settlementBaseState("player"),
      turn: { year: 1627, period: 10, turn: 5, phase: "player", settlement_display: false },
      previous_summary: "",
      pending_decisions: [],
    });
    const host = await mountApp();
    await click(cmdByCaption(host, "拟诏·盖玺颁诏过月"));
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="诏书草案"]')).not.toBeNull());
    });
    const layer = host.querySelector('.fullscreen-layer.edict-safe-cmd[aria-label="诏书草案"]');
    expect(layer).not.toBeNull();
    // 名实：HUD 木牌不再与 seal-btn-issue 同文；台内主钮仍独占「盖玺颁诏过月」
    expect(cmdByCaption(host, "拟诏·盖玺颁诏过月")).toBeNull();
    const collapse = cmdByCaption(host, "拟诏·收起");
    expect(collapse).not.toBeNull();
    expect(host.querySelector("button.seal-btn-issue")?.textContent).toMatch(/盖玺颁诏过月/);
    // 可点性：点收起木牌关台（非空等、非二次颁诏）
    await click(collapse);
    await tick();
    await act(async () => {
      await vi.waitFor(() => expect(host.querySelector('[role="dialog"][aria-label="诏书草案"]')).toBeNull());
    });
  });

  it("#1305 court/harem nav 互斥：开后宫即关朝堂", async () => {
    stubSettlementFetch({
      ...settlementBaseState("player"),
      turn: { year: 1627, period: 10, turn: 5, phase: "player", settlement_display: false },
      previous_summary: "",
      pending_decisions: [],
    });
    const host = await mountApp();
    await click(byAria(host, "朝堂·召见大臣"));
    await tick();
    expect(host.querySelector(".court-drawer.open:not(.harem-drawer)")).not.toBeNull();
    expect(host.querySelector(".harem-drawer.open")).toBeNull();

    await click(byAria(host, "后宫"));
    await tick();
    expect(host.querySelector(".harem-drawer.open")).not.toBeNull();
    expect(host.querySelector(".court-drawer.open:not(.harem-drawer)")).toBeNull();

    // #1305：同键再点 → 抽屉收起（实现 main.tsx navHandlers opening/closeAll）。
    await click(byAria(host, "后宫"));
    await tick();
    expect(host.querySelector(".harem-drawer.open")).toBeNull();
  });
});
