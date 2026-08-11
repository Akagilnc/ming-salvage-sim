import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAudienceChat, type SendChatCallbacks } from "./useAudienceChat";
import { ChatModal } from "./components/modals";
import { retryAudienceStoryExtraction } from "./extractionRetry";
import type { ChatResponse, Minister, ServerChatMessage } from "./types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MINISTER: Minister = {
  name: "温体仁", office: "礼部尚书", office_type: "礼部", faction: "浙党",
  style: "", status: "active", status_label: "在朝", summary: "", favorite: false, skills: [],
};

const U = (content: string, turn: number): ServerChatMessage => ({ role: "user", content, chat_turn_id: turn });
const M = (content: string, turn: number): ServerChatMessage => ({ role: "minister", content, chat_turn_id: turn });

type SseEvent = { event: string; data: unknown };
const fmt = (e: SseEvent) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`;

function sse(events: SseEvent[]): Response {
  const enc = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({ start(c) { for (const e of events) c.enqueue(enc.encode(fmt(e))); c.close(); } }),
    { status: 200 },
  );
}
function gatedSse(head: SseEvent[], gate: Promise<void>, tail: SseEvent[]): Response {
  const enc = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      async start(c) {
        for (const e of head) c.enqueue(enc.encode(fmt(e)));
        await gate;
        for (const e of tail) c.enqueue(enc.encode(fmt(e)));
        c.close();
      },
    }),
    { status: 200 },
  );
}
const jsonResp = (payload: unknown): Response => ({ ok: true, json: async () => payload } as unknown as Response);

type HookApi = ReturnType<typeof useAudienceChat>;

function mount(scrollMode: "audience" | "legacy" = "legacy", refreshOnEnd = false) {
  const hookRef = { current: null as HookApi | null };
  const busyRef = { current: "" };
  const setModalRef = { current: (_m: string) => {} };
  const invalidateScrollRef = { current: () => {} };
  function Harness() {
    const selectedRef = React.useRef("温体仁");
    const [busy, setBusy] = React.useState("");
    const [activeModal, setActiveModal] = React.useState("chat");
    const [scrollGeneration, setScrollGeneration] = React.useState(0);
    const invalidateScroll = React.useCallback(() => setScrollGeneration((value) => value + 1), []);
    invalidateScrollRef.current = invalidateScroll;
    busyRef.current = busy;
    setModalRef.current = setActiveModal;
    // App 同款消费：chatOpen=activeModal==="chat"。chat-exit 归属逻辑在 hook 内部（生产真实
    // 消费的 controller）；测试只驱动 activeModal，退出取消经 hook 内置 effect，不复制退出胶水。
    const hook = useAudienceChat(
      setBusy, selectedRef, activeModal === "chat", refreshOnEnd ? invalidateScroll : undefined,
    );
    hookRef.current = hook;
    return (
      <ChatModal
        minister={MINISTER} portraitPrefix="minister_" scrollMode={scrollMode}
        currentCampaignId={hook.currentCampaignId}
        currentNightId={hook.currentNightId}
        undoneChatIdentity={null}
        chat={hook.chat}
        pendingUserMessage={hook.pendingUserMessage}
        pendingIdentity={hook.pendingIdentity}
        failedIdentity={hook.failedIdentity}
        scrollGeneration={scrollGeneration}
        streamingMinisterMessage={hook.streamingMinisterMessage}
        suggestions={[]} chatNotice="" chatFailures={[]} canUndoLastChat={false}
        composerHint="" input="" busy={busy} error="" secretOrders={[]}
        onInput={() => {}} onSend={() => {}} onRetryFailure={() => {}} onUndo={() => {}}
        onHint={() => {}} onFavorite={() => {}} onOpenEdict={() => {}} onClose={() => {}} onCancel={() => {}}
      />
    );
  }
  const host = document.createElement("div");
  document.body.appendChild(host);
  act(() => createRoot(host).render(<Harness />));
  const rows = () =>
    Array.from(host.querySelectorAll(".chat-log > .chat-message:not(.pending):not(.thinking)")).map((el) => {
      const role = ["user", "minister", "attendant"].find((r) => el.classList.contains(r)) || "";
      return `${role}:${el.querySelector("p")?.textContent ?? ""}`;
    });
  return {
    hookRef, busyRef, rows,
    setModal: (m: string) => act(() => setModalRef.current(m)),
    retryExtraction: () => retryAudienceStoryExtraction(invalidateScrollRef.current),
  };
}

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const noCbs: SendChatCallbacks = { onDone: () => {}, onLeave: () => {}, onError: () => {} };

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("读心投递（#499 经真实 useAudienceChat 生产控制器）", () => {
  it("done 先清 busy 解锁，迟到 highlights 按 turn 补挂 legacy history", async () => {
    let releaseHighlights!: () => void;
    const gate = new Promise<void>((resolve) => { releaseHighlights = resolve; });
    let doneCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => gatedSse(
      [{ event: "done", data: { history: [U("问", 10), M("答", 10)], suggestions: [], directives: [] } }],
      gate,
      [{ event: "highlights", data: { chat_turn_id: 10, highlights: ["答"] } }, { event: "end", data: {} }],
    )));
    const { hookRef, busyRef } = mount("legacy", true);
    let sending!: Promise<void>;
    act(() => {
      sending = hookRef.current!.sendChat("温体仁", "问", {
        onDone: () => { doneCalls += 1; },
        onError: () => {},
      });
    });
    await tick();
    expect(doneCalls).toBe(1);
    expect(busyRef.current).toBe("");
    releaseHighlights();
    await act(async () => { await sending; });
    expect(busyRef.current).toBe("");
    expect(hookRef.current!.chat.find((m) => m.role === "minister")?.highlights).toEqual(["答"]);
  });

  it("done 后装饰失败响亮回调但不标记或隐藏已完成回话", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sse([
      { event: "done", data: { history: [U("问", 11), M("已成回话", 11)], suggestions: [], directives: [] } },
      { event: "decoration_error", data: { message: "disk full" } },
      { event: "end", data: {} },
    ])));
    const { hookRef } = mount("legacy", true);
    const errors: string[] = [];
    await act(async () => {
      await hookRef.current!.sendChat("温体仁", "问", {
        onError: (error) => errors.push(String(error)),
      });
    });
    expect(errors.join(" ")).toContain("disk full");
    expect(hookRef.current!.failedIdentity).toBeNull();
    expect(hookRef.current!.chat.some((m) => m.content === "已成回话")).toBe(true);
  });

  it("只在 SSE end 后失效并重读公共卷轴的新落账 scene", async () => {
    let scrollCalls = 0;
    let resolveEnd!: () => void;
    let ended = false;
    const endGate = new Promise<void>((resolve) => { resolveEnd = resolve; });
    const releaseEnd = () => { ended = true; resolveEnd(); };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("/api/audience/scroll")) {
        scrollCalls += 1;
        return jsonResp({
          night_id: 24,
          messages: !ended ? [] : [
            { role: "scene", speaker: "", content: "新落账场景", chat_turn_id: 8 },
          ],
        });
      }
      return gatedSse(
        [
          { event: "accepted", data: { campaign_id: "c1", night_id: 24, chat_turn_id: 8 } },
          { event: "done", data: { history: [], suggestions: [], directives: [] } },
        ],
        endGate,
        [{ event: "end", data: {} }],
      );
    }));
    const { hookRef, rows } = mount("audience", true);
    await tick();
    expect(scrollCalls).toBe(1);

    let sending!: Promise<void>;
    act(() => { sending = hookRef.current!.sendChat("温体仁", "请奏", noCbs); });
    await tick();
    const callsBeforeEnd = scrollCalls;
    releaseEnd();
    await act(async () => { await sending; });
    await tick();

    expect(scrollCalls).toBe(callsBeforeEnd + 1);
    expect(document.body.textContent).toContain("新落账场景");
  });

  it("补写成功且 pending 归零后复用同一代次重读公共卷轴", async () => {
    let scrollCalls = 0;
    let retried = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("/api/audience/extraction/retry")) {
        retried = true;
        return jsonResp({ count: 0 });
      }
      if (String(url).includes("/api/ministers/") && String(url).endsWith("/chat")) return jsonResp({
        minister: MINISTER, history: [], suggestions: [], can_undo_last_chat: false,
        campaign_id: "c1", night_id: 24,
      });
      if (String(url).includes("/api/audience/scroll")) {
        scrollCalls += 1;
        return jsonResp({
          night_id: 24,
          messages: !retried ? [] : [
            { role: "scene", speaker: "", content: "补写完成场景", chat_turn_id: 8 },
          ],
        });
      }
      throw new Error(`unexpected request: ${url}`);
    }));
    const { hookRef, retryExtraction } = mount("audience", true);
    await tick();
    await act(async () => { await hookRef.current!.loadHistory("温体仁"); });
    await tick();
    const callsBeforeRetry = scrollCalls;

    await act(async () => { await retryExtraction(); });
    await tick();

    expect(scrollCalls).toBe(callsBeforeRetry + 1);
    expect(document.body.textContent).toContain("补写完成场景");
  });

  it("accepted 后 provider failure 以持久 identity 淘汰 generating 快照且保留其它轮", async () => {
    let scrollCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("/api/audience/scroll")) {
        scrollCalls += 1;
        return jsonResp(scrollCalls === 1 ? { night_id: 0, messages: [] } : {
          night_id: 24,
          messages: [
            { role: "user", speaker: "圣上", content: "失败问话", chat_turn_id: 8, status: "generating" },
            { role: "user", speaker: "圣上", content: "保留问话", chat_turn_id: 7 },
            { role: "minister", speaker: "温体仁", content: "保留答复", chat_turn_id: 7 },
          ],
        });
      }
      return sse([
        { event: "accepted", data: { campaign_id: "", night_id: 24, chat_turn_id: 8 } },
        { event: "error", data: { message: "回话失败", campaign_id: "", night_id: 24, chat_turn_id: 8 } },
      ]);
    }));
    const { hookRef, rows } = mount("audience");
    await tick();

    await act(async () => { await hookRef.current!.sendChat("温体仁", "失败问话", noCbs); });
    await tick();

    expect(hookRef.current!.failedIdentity).toEqual({ campaign_id: "", night_id: 24, chat_turn_id: 8 });
    expect(rows()).not.toContain("user:失败问话");
    expect(rows()).toContain("user:保留问话");
    expect(rows()).toContain("minister:保留答复");
  });

  it("无夜 identity 不接纳猜测出的旧卷，新夜回话失败也不回闪", async () => {
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      call += 1;
      if (call === 1 && String(url).includes("/api/audience/scroll")) return jsonResp({
        night_id: 23,
        messages: [{ role: "minister", speaker: "洪承畴", content: "旧夜他臣", chat_turn_id: 7 }],
      });
      return sse([
        { event: "accepted", data: { night_id: 24 } },
        { event: "error", data: { message: "回话失败" } },
      ]);
    }));
    const { hookRef, rows } = mount();
    await tick();
    expect(hookRef.current!.currentNightId).toBe(0);
    expect(rows()).not.toContain("minister:旧夜他臣");

    await act(async () => {
      await hookRef.current!.sendChat("温体仁", "开启新场", noCbs);
    });
    expect(hookRef.current!.currentNightId).toBe(24);
    expect(rows()).not.toContain("minister:旧夜他臣");
  });

  it("迟到的旧流读心：新 send 作废 token 后，旧流 mind1 仍归其轮浮现（不按 token 门控）", async () => {
    const { hookRef, rows } = mount();
    const hook = hookRef.current!;

    let releaseTail1!: () => void;
    const gate1 = new Promise<void>((r) => { releaseTail1 = r; });
    let call = 0;
    let mindReleased = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("/api/audience/scroll")) {
        if (mindReleased) return new Promise<Response>(() => {}); // 权威刷新延迟，交接态须显示 reducer 增量
        return jsonResp({
        night_id: 23,
        messages: [
          { role: "user", content: "问1", chat_turn_id: 10 }, { role: "minister", content: "答1", chat_turn_id: 10 },
          { role: "user", content: "问2", chat_turn_id: 11 }, { role: "minister", content: "答2", chat_turn_id: 11 },
        ],
      });
      }
      call += 1;
      if (call === 1) {
        // 流 1：done1 后门控挂起；mind1 尾巴延迟到流 2 完成之后才到
        return gatedSse(
          [{ event: "accepted", data: { night_id: 23 } },
           { event: "done", data: { history: [U("问1", 10), M("答1", 10)], suggestions: [], directives: [] } }],
          gate1,
          [{ event: "mindreading", data: { mindreading: { id: 1, narration: "近臣低声。" }, chat_turn_id: 10 } },
           { event: "end", data: {} }],
        );
      }
      // 流 2：陈旧 done2（无 a1）后立即结束
      return sse([
        { event: "accepted", data: { night_id: 23 } },
        { event: "done", data: { history: [U("问1", 10), M("答1", 10), U("问2", 11), M("答2", 11)], suggestions: [], directives: [] } },
        { event: "end", data: {} },
      ]);
    }));

    let p1!: Promise<void>;
    act(() => { p1 = hook.sendChat("温体仁", "问1", noCbs); });
    await tick();  // done1 落 [u1,m1]
    await act(async () => { await hook.sendChat("温体仁", "问2", noCbs); });  // 流 2 完成 → [u1,m1,u2,m2]
    expect(rows()).toEqual(["user:问1", "minister:答1", "user:问2", "minister:答2"]);

    mindReleased = true;
    releaseTail1();  // 流 1 迟到的 mind1（turn10）到达——token 已被流 2 作废
    await act(async () => { await p1; });
    // hook 的真实 reducer 把 mind1 插回旧轮；ChatModal 与权威卷轴交接按身份差集保住它，
    // 不会因位置水位偏移而漏递话、重复既有尾轮。
    expect(rows()).toEqual(["user:问1", "minister:答1", "attendant:近臣低声。", "user:问2", "minister:答2"]);
  });

  it("持久后果在 done 到手即消费：读心延后 end 期间起新轮，旧轮后果不被丢弃", async () => {
    const { hookRef } = mount();
    const hook = hookRef.current!;
    const durablesSeen: number[] = [];
    const cb: SendChatCallbacks = { ...noCbs, onDone: (d: ChatResponse) => durablesSeen.push(d.secret_order_id || 0) };

    let releaseEnd1!: () => void;
    const gate1 = new Promise<void>((r) => { releaseEnd1 = r; });
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      call += 1;
      if (call === 1) {
        // 流 1：done1 携持久后果（密令 #7），随后门控挂起（模拟读心拖后 end）
        return gatedSse(
          [{ event: "done", data: { history: [U("问1", 10), M("答1", 10)], suggestions: [], directives: [], secret_order_id: 7 } }],
          gate1,
          [{ event: "end", data: {} }],
        );
      }
      return gatedSse([], new Promise<void>(() => {}), []);  // 流 2 保持在飞
    }));

    let p1!: Promise<void>;
    act(() => { p1 = hook.sendChat("温体仁", "问1", cb); });
    await tick();
    // done1 到手即消费持久后果（不拖到 end）
    expect(durablesSeen).toEqual([7]);

    // 读心尚未就绪、end 未到时起第 2 轮（token 自增作废流 1）
    act(() => { void hook.sendChat("温体仁", "问2", noCbs); });
    await tick();
    releaseEnd1();  // 流 1 收尾——绝不因 token 已变而回补/丢弃已消费的后果
    await act(async () => { await p1; });
    expect(durablesSeen).toEqual([7]);  // 仍恰一次，未被丢弃、未重复
  });

  it("重叠流归属：旧流尾巴（finally）不清掉更新请求的 busy / 待答文", async () => {
    const { hookRef, busyRef } = mount();
    const hook = hookRef.current!;
    let releaseEnd1!: () => void;
    const gate1 = new Promise<void>((r) => { releaseEnd1 = r; });
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      call += 1;
      if (call === 1) {
        return gatedSse(
          [{ event: "done", data: { history: [U("问1", 10), M("答1", 10)], suggestions: [], directives: [] } }],
          gate1, [{ event: "end", data: {} }],
        );
      }
      return gatedSse([], new Promise<void>(() => {}), []);  // 流 2 尚未 done、保持在飞
    }));

    let p1!: Promise<void>;
    act(() => { p1 = hook.sendChat("温体仁", "问1", noCbs); });
    await tick();
    expect(busyRef.current).toBe("");  // done1 清 busy

    act(() => { void hook.sendChat("温体仁", "问2", noCbs); });
    await tick();
    expect(busyRef.current).toBe("大臣思索中");
    expect(hookRef.current!.pendingUserMessage).toBe("问2");

    releaseEnd1();
    await act(async () => { await p1; });
    expect(busyRef.current).toBe("大臣思索中");            // 旧流未清掉流 2 的 busy
    expect(hookRef.current!.pendingUserMessage).toBe("问2");  // 旧流未清掉流 2 的待答文
  });

  it("陈旧同大臣历史响应：更旧的 GET 迟到不抹掉新完成的轮（generation 守卫）", async () => {
    const { hookRef, rows } = mount();
    const hook = hookRef.current!;
    let releaseOld!: () => void;
    const oldGate = new Promise<void>((r) => { releaseOld = r; });
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("/chat")) {
        call += 1;
        if (call === 1) { await oldGate; return jsonResp({ minister: MINISTER, history: [U("问1", 10), M("答1", 10)], suggestions: [], can_undo_last_chat: false }); }
        return jsonResp({ minister: MINISTER, history: [U("问1", 10), M("答1", 10), U("问2", 11), M("答2", 11)], suggestions: [], can_undo_last_chat: false });
      }
      return jsonResp({});
    }));

    // 先发一次历史 GET（更旧快照，门控挂起），再发第二次（更新快照，立即返回）
    let pOld!: Promise<unknown>;
    act(() => { pOld = hook.loadHistory("温体仁"); });
    await act(async () => { await hook.loadHistory("温体仁"); });  // gen2 落新快照
    expect(rows()).toEqual(["user:问1", "minister:答1", "user:问2", "minister:答2"]);

    releaseOld();  // 更旧的 GET 迟到——generation 已推进，须丢弃、不回退
    await act(async () => { await pOld; });
    expect(rows()).toEqual(["user:问1", "minister:答1", "user:问2", "minister:答2"]);
  });
});

describe("重开读心轮询（#499 pending_turn_ids 经真实 hook）", () => {
  // 历史 GET 携 pending_turn_ids；每一待读心轮各自轮询 /chat/mindreading?chat_turn_id=T。
  const routeReopen = (
    pendingTurnIds: number[],
    mindByTurn: (turnId: number, call: number) => { mindreading: Array<{ id: number; narration: string }>; mindreading_pending: boolean },
    counters: Record<string, number> = {},
  ) =>
    vi.fn(async (url: string) => {
      const u = new URL(String(url), "http://t.local");
      if (u.pathname.endsWith("/chat/mindreading")) {
        const tid = Number(u.searchParams.get("chat_turn_id") || 0);
        counters[tid] = (counters[tid] || 0) + 1;
        return jsonResp({ chat_turn_id: tid, ...mindByTurn(tid, counters[tid]) });
      }
      return jsonResp({
        minister: MINISTER, history: [U("问", 10), M("答", 10)], suggestions: [],
        can_undo_last_chat: false, pending_turn_ids: pendingTurnIds,
      });
    });

  const advance = () => act(async () => { await vi.advanceTimersByTimeAsync(1600); });

  it("待读心历史 + 固定轮轮询（先空后达）就绪即浮现，达成后终止", async () => {
    vi.useFakeTimers();
    try {
      const { hookRef, rows } = mount();
      const counters: Record<string, number> = {};
      vi.stubGlobal("fetch", routeReopen([10], (_tid, call) =>
        call < 2
          ? { mindreading: [], mindreading_pending: true }                                  // 先空（仍 pending）
          : { mindreading: [{ id: 1, narration: "近臣低声。" }], mindreading_pending: true },  // 后达
        counters,
      ));
      await act(async () => { await hookRef.current!.loadHistory("温体仁"); });
      expect(rows()).toEqual(["user:问", "minister:答"]);  // 读心未到
      await advance();  // 第 1 次轮询：空
      expect(rows()).toEqual(["user:问", "minister:答"]);
      await advance();  // 第 2 次：达 → 浮现
      expect(rows()).toEqual(["user:问", "minister:答", "attendant:近臣低声。"]);
      const afterDeliver = counters["10"];
      await advance();
      expect(counters["10"]).toBe(afterDeliver);  // 达成后不再轮询（终止）
    } finally { vi.useRealTimers(); }
  });

  it("多个待读心轮各自轮询，均浮现（不只最新轮）", async () => {
    vi.useFakeTimers();
    try {
      const { hookRef, rows } = mount();
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/chat/mindreading")) {
          const tid = Number(u.searchParams.get("chat_turn_id") || 0);
          return jsonResp({ chat_turn_id: tid, mindreading: [{ id: tid, narration: tid === 10 ? "近臣一。" : "近臣二。" }], mindreading_pending: true });
        }
        // 两轮都已完成回话（都在投影里），都待读心
        return jsonResp({
          minister: MINISTER,
          history: [U("问a", 10), M("答a", 10), U("问b", 11), M("答b", 11)],
          suggestions: [], can_undo_last_chat: false, pending_turn_ids: [10, 11],
        });
      }));
      await act(async () => { await hookRef.current!.loadHistory("温体仁"); });
      await advance();
      const attendants = rows().filter((r) => r.startsWith("attendant:"));
      expect(attendants.sort()).toEqual(["attendant:近臣一。", "attendant:近臣二。"]);
      // 各归其轮：近臣一随轮 10 回话之后，近臣二随轮 11 回话之后
      expect(rows()).toEqual([
        "user:问a", "minister:答a", "attendant:近臣一。",
        "user:问b", "minister:答b", "attendant:近臣二。",
      ]);
    } finally { vi.useRealTimers(); }
  });

  it("轮询随后续 send 存活：新一轮发出后旧轮读心仍就绪浮现（面板归属、不按发送作废）", async () => {
    vi.useFakeTimers();
    try {
      const { hookRef, rows } = mount();
      const counters: Record<string, number> = {};
      vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/chat/stream") || init?.method === "POST") {
          const enc = new TextEncoder();
          return new Response(new ReadableStream<Uint8Array>({
            start(c) {
              c.enqueue(enc.encode(fmt({ event: "done", data: { history: [U("问", 10), M("答", 10), U("问2", 11), M("答2", 11)], suggestions: [], directives: [] } })));
              c.enqueue(enc.encode(fmt({ event: "end", data: {} })));
              c.close();
            },
          }), { status: 200 });
        }
        if (u.pathname.endsWith("/chat/mindreading")) {
          const tid = Number(u.searchParams.get("chat_turn_id") || 0);
          counters[tid] = (counters[tid] || 0) + 1;
          return jsonResp({ chat_turn_id: tid, mindreading: counters[tid] >= 2 ? [{ id: 1, narration: "旧轮读心。" }] : [], mindreading_pending: true });
        }
        return jsonResp({ minister: MINISTER, history: [U("问", 10), M("答", 10)], suggestions: [], can_undo_last_chat: false, pending_turn_ids: [10] });
      }));
      await act(async () => { await hookRef.current!.loadHistory("温体仁"); });  // 轮 10 待读心，起轮询
      await advance();  // 第 1 次：空
      await act(async () => { await hookRef.current!.sendChat("温体仁", "问2", noCbs); });  // 期间发新一轮
      await advance();  // 轮 10 的轮询仍存活 → 达
      expect(rows().some((r) => r === "attendant:旧轮读心。")).toBe(true);
    } finally { vi.useRealTimers(); }
  });

  it("轮询前一次 fetch 失败自愈；越过旧 20 次上限的迟到记录仍浮现（寿命系于终态非常数）", async () => {
    vi.useFakeTimers();
    try {
      const { hookRef, rows } = mount();
      let call = 0;
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/chat/mindreading")) {
          call += 1;
          if (call === 1) throw new Error("net blip");                                    // 首次失败→自愈
          if (call < 25) return jsonResp({ chat_turn_id: 10, mindreading: [], mindreading_pending: true });  // 长时间空（越过旧 20 上限）
          return jsonResp({ chat_turn_id: 10, mindreading: [{ id: 1, narration: "迟到读心。" }], mindreading_pending: true });
        }
        return jsonResp({ minister: MINISTER, history: [U("问", 10), M("答", 10)], suggestions: [], can_undo_last_chat: false, pending_turn_ids: [10] });
      }));
      await act(async () => { await hookRef.current!.loadHistory("温体仁"); });
      for (let i = 0; i < 30; i += 1) await advance();  // 推进远超旧 20 次
      expect(rows().some((r) => r === "attendant:迟到读心。")).toBe(true);
    } finally { vi.useRealTimers(); }
  });

  it("服务端终态 pending=false 即终止轮询（不空转）", async () => {
    vi.useFakeTimers();
    try {
      const { hookRef } = mount();
      let call = 0;
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/chat/mindreading")) { call += 1; return jsonResp({ chat_turn_id: 10, mindreading: [], mindreading_pending: false }); }
        return jsonResp({ minister: MINISTER, history: [U("问", 10), M("答", 10)], suggestions: [], can_undo_last_chat: false, pending_turn_ids: [10] });
      }));
      await act(async () => { await hookRef.current!.loadHistory("温体仁"); });
      await advance();               // 第 1 次：pending=false → 停
      const afterStop = call;
      await advance(); await advance();
      expect(call).toBe(afterStop);  // 终态后不再轮询
    } finally { vi.useRealTimers(); }
  });

  it("经真实 App 退出路径（activeModal 离开 chat）停旧 poll-batch——不直呼 hook 取消法", async () => {
    vi.useFakeTimers();
    try {
      const { hookRef, setModal } = mount();
      let call = 0;
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/chat/mindreading")) { call += 1; return jsonResp({ chat_turn_id: 10, mindreading: [], mindreading_pending: true }); }
        return jsonResp({ minister: MINISTER, history: [U("问", 10), M("答", 10)], suggestions: [], can_undo_last_chat: false, pending_turn_ids: [10] });
      }));
      await act(async () => { await hookRef.current!.loadHistory("温体仁"); });
      await advance();
      const before = call;
      setModal("none");  // 离开召对面板（关闭/Escape/转诏书 等任一 departure 的共同表现）
      await advance(); await advance();
      expect(call).toBe(before);  // 退出后 exit-owner effect 停旧批轮询
    } finally { vi.useRealTimers(); }
  });

  it("转诏书（activeModal→edict）也停旧 poll-batch（edict transition 不绕过取消）", async () => {
    vi.useFakeTimers();
    try {
      const { hookRef, setModal } = mount();
      let call = 0;
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        const u = new URL(String(url), "http://t.local");
        if (u.pathname.endsWith("/chat/mindreading")) { call += 1; return jsonResp({ chat_turn_id: 10, mindreading: [], mindreading_pending: true }); }
        return jsonResp({ minister: MINISTER, history: [U("问", 10), M("答", 10)], suggestions: [], can_undo_last_chat: false, pending_turn_ids: [10] });
      }));
      await act(async () => { await hookRef.current!.loadHistory("温体仁"); });
      await advance();
      const before = call;
      setModal("edict");  // 转入诏书草案
      await advance(); await advance();
      expect(call).toBe(before);
    } finally { vi.useRealTimers(); }
  });
});
