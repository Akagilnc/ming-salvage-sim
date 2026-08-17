import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./main";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
class _RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as typeof globalThis & { ResizeObserver?: unknown }).ResizeObserver = _RO;

// 开启密令换回合自动弹窗（生产 gate 默认关；测试打开以验协调器所属的延迟呈现定时器 wiring）。
// #1236：其余 face-gate 助手走真实实现，避免 wiring 测试与门控分叉。
vi.mock("./settlementPresentation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./settlementPresentation")>();
  return {
    ...actual,
    shouldAutoOpenSecretOrdersAfterSettlement: () => true,
    shouldAutoOpenClosedIssuesAfterSettlement: () => false,
  };
});

const jsonResp = (payload: unknown): Response => ({ ok: true, json: async () => payload } as unknown as Response);
const sseResp = (event: string, payload: unknown): Response => {
  const body = `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
};

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
  it("夜卷轴侧插话不夺锚且真实 App 请求命中当前奏对者", async () => {
    const minister = (name: string) => ({ name, office: "兵部", office_type: "内阁", faction: "", style: "", status: "active", status_label: "在朝", summary: "", favorite: false, skills: [] });
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = new URL(String(url), "http://t.local");
      calls.push(`${init?.method || "GET"} ${decodeURIComponent(u.pathname)}`);
      if (u.pathname.endsWith("/api/menu/status")) return jsonResp(MENU_STATUS);
      if (u.pathname.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });
      if (u.pathname.endsWith("/api/saves")) return jsonResp({ saves: [] });
      if (u.pathname.endsWith("/api/game/state")) return jsonResp(makeState(1, [], [minister("杨嗣昌"), minister("洪承畴")]));
      if (u.pathname.endsWith("/api/ministers/%E6%9D%A8%E5%97%A3%E6%98%8C/chat")) return jsonResp({ campaign_id: "c", night_id: 23, history: [], suggestions: [], can_undo_last_chat: false });
      if (u.pathname.endsWith("/api/audience/scroll")) return jsonResp({ night_id: 23, messages: [
        { role: "scene", speaker: "洪承畴", content: "入殿", beat: "entrance" },
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
    await act(async () => { createRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[title="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll(".minister-card")).find((node) => node.textContent?.includes("杨嗣昌")));
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
      if (decodeURIComponent(u.pathname).endsWith("/api/ministers/杨嗣昌/chat")) return jsonResp(retryCompleted ? {
        campaign_id: "c", night_id: 23, minister: minister("杨嗣昌"), history: [{ role: "minister", content: "臣已整饬边防", chat_turn_id: 7 }], suggestions: [{ label: "追问粮饷", text: "追问粮饷" }], can_undo_last_chat: true,
      } : {
        campaign_id: "c", night_id: 23, minister: minister("杨嗣昌"), history: [], suggestions: [], can_undo_last_chat: false,
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
    await act(async () => { createRoot(host).render(<App />); });
    await tick();
    await click(host.querySelector('[title="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(host.querySelectorAll(".minister-card")).find((node) => node.textContent?.includes("杨嗣昌")));
    await act(async () => { await vi.waitFor(() => expect(findButton(host, "重新生成回话")).toBeTruthy()); });
    const scrollCallsBeforeRetry = scrollCalls;
    await click(findButton(host, "重新生成回话"));
    await act(async () => { await vi.waitFor(() => expect(host.textContent).toContain("臣已整饬边防")); });

    expect(calls).toContain("POST /api/ministers/洪承畴/reply/retry");
    expect(calls.filter((call) => call === "GET /api/ministers/洪承畴/chat")).toHaveLength(0);
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
    await act(async () => { createRoot(host).render(<App />); });
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
    await act(async () => { createRoot(host).render(<App />); });
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
    await act(async () => { createRoot(host).render(<App />); });
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
    await act(async () => { createRoot(secondHost).render(<App />); });
    await tick();
    await click(secondHost.querySelector('[aria-label="朝堂·召见大臣"]'));
    await tick();
    await click(Array.from(secondHost.querySelectorAll("button")).find((b) => b.textContent?.includes("温体仁")));
    await tick();
    await click(findButton(secondHost, "退朝"));
    await act(async () => {
      await vi.waitFor(() => expect(paths.filter((path) => path.endsWith("/chat/stream")).length).toBeGreaterThanOrEqual(2));
    });

    expect(paths.some((path) => path === "POST /api/decree/advance_without_edict")).toBe(false);
  });

  it("成功密令经过真实召对发送链后不显示系统通知", async () => {
    let sentSecretOrder = false;
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
      if (u.pathname.endsWith("/api/ministers/%E6%9D%A8%E5%97%A3%E6%98%8C/chat/stream") && init?.method === "POST") {
        sentSecretOrder = true;
        return sseResp("done", {
          history: [
            { role: "user", content: "密令如下：整饬边备。", chat_turn_id: 1 },
            { role: "minister", content: "臣领旨。", chat_turn_id: 1 },
          ],
          suggestions: [], directives: [], pending_count: 0, pending_action_failures: [],
          can_undo_last_chat: true, secret_order_id: 7, night_id: 1,
        });
      }
      if (u.pathname.endsWith("/api/ministers/%E6%9D%A8%E5%97%A3%E6%98%8C/chat")) {
        return jsonResp({ minister, history: [], suggestions: [], pending_action_failures: [], pending_turn_ids: [], night_id: 1 });
      }
      return jsonResp({});
    }));

    const host = document.createElement("div"); document.body.appendChild(host);
    await act(async () => { createRoot(host).render(<App />); });
    await act(async () => { await vi.waitFor(() => expect(findButton(host, "杨嗣昌")).toBeTruthy()); });
    await click(host.querySelector('[aria-label="朝堂·召见大臣"]'));
    await click(findButton(host, "杨嗣昌"));
    await act(async () => { await vi.waitFor(() => expect(host.querySelector('textarea')).not.toBeNull()); });

    const textarea = host.querySelector("textarea") as HTMLTextAreaElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set?.call(
        textarea,
        "密令如下：整饬边备。",
      );
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const sendButton = findButton(host, "发送") as HTMLButtonElement;
    await click(sendButton);
    await act(async () => {
      await vi.waitFor(() => expect(sentSecretOrder).toBe(true));
      await vi.waitFor(() => expect(sendButton.disabled).toBe(false));
    });

    expect(host.querySelector(".chat-system-note")).toBeNull();
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
