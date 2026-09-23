import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAudienceChat, type SendChatCallbacks } from "./useAudienceChat";
import { ChatModal } from "./components/chatModal";
import type { ChatResponse, Minister, ServerChatMessage } from "./types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MINISTER: Minister = {
  name: "温体仁", office: "礼部右侍郎", office_type: "礼部", faction: "浙党",
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
        minister={MINISTER} ministers={[MINISTER]} portraitPrefix="minister_" scrollMode={scrollMode}
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
        onInput={() => {}} onSend={() => {}} onUndo={() => {}}
        onHint={() => {}} onFavorite={() => {}} onClose={() => {}} onCancel={() => {}}
      />
    );
  }
  const host = document.createElement("div");
  document.body.appendChild(host);
  act(() => createRoot(host).render(<Harness />));
  const rows = () =>
    Array.from(host.querySelectorAll(".chat-log .chat-message:not(.pending):not(.thinking)")).map((el) => {
      const role = ["user", "minister", "attendant"].find((r) => el.classList.contains(r)) || "";
      return `${role}:${el.querySelector("p")?.textContent ?? ""}`;
    });
  return {
    hookRef, busyRef, rows,
    setModal: (m: string) => act(() => setModalRef.current(m)),
  };
}

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const noCbs: SendChatCallbacks = { onDone: () => {}, onLeave: () => {}, onError: () => {} };

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("读心投递（#499 经真实 useAudienceChat 生产控制器）", () => {
  it("宣召落账先于回话重读主角，end 后仍重读尾随场景", async () => {
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
          protagonist: "温体仁",
          roster: [{ name: "温体仁", present: true }],
          messages: !ended ? [] : [
            { role: "scene", speaker: "", content: "新落账场景", chat_turn_id: 8 },
            { role: "minister", speaker: "温体仁", content: "臣遵旨。", beat: "dialogue", chat_turn_id: 8 },
          ],
        });
      }
      return gatedSse(
        [
          { event: "accepted", data: { campaign_id: "c1", night_id: 24, chat_turn_id: 8 } },
          { event: "protagonist_changed", data: {} },
        ],
        endGate,
        [{ event: "done", data: { history: [], suggestions: [], directives: [] } }, { event: "end", data: {} }],
      );
    }));
    const { hookRef, rows } = mount("audience", true);
    await tick();
    expect(scrollCalls).toBe(1);

    let sending!: Promise<void>;
    act(() => { sending = hookRef.current!.sendChat("温体仁", "请奏", noCbs); });
    await tick();
    expect(scrollCalls).toBeGreaterThan(1);
    expect(document.querySelector(".chat-portrait-wrap img")?.getAttribute("src")).toBe("/portraits/minister_温体仁.png");
    const callsBeforeEnd = scrollCalls;
    releaseEnd();
    await act(async () => { await sending; });
    await tick();

    expect(scrollCalls).toBe(callsBeforeEnd + 1);
    expect(document.body.textContent).toContain("新落账场景");
  });

  it("accepted 后 provider failure 以持久 identity 淘汰 generating 快照且保留其它轮", async () => {
    let scrollCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("/api/audience/scroll")) {
        scrollCalls += 1;
        return jsonResp(scrollCalls === 1 ? { night_id: 0, messages: [] } : {
          night_id: 24,
          protagonist: "", roster: [], translation_pending: false, messages: [
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

  it("accepted 后普通流中断会移除未持久化的半段回话", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (String(url).includes("/api/audience/scroll")) return jsonResp({ night_id: 24, protagonist: "", roster: [], translation_pending: false, messages: [] });
      return sse([
        { event: "accepted", data: { campaign_id: "c1", night_id: 24, chat_turn_id: 8 } },
        { event: "delta", data: { content: "未完成回话" } },
      ]);
    }));
    const { hookRef } = mount("audience");
    await tick();

    await act(async () => { await hookRef.current!.sendChat("温体仁", "请奏", noCbs); });

    expect(hookRef.current!.failedIdentity).toEqual({ campaign_id: "c1", night_id: 24, chat_turn_id: 8 });
    expect(document.querySelector('[data-audience-turn-id="8"]')).toBeNull();
  });

  it("无夜 identity 不接纳猜测出的旧卷，新夜回话失败也不回闪", async () => {
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      call += 1;
      if (call === 1 && String(url).includes("/api/audience/scroll")) return jsonResp({
        night_id: 23,
        protagonist: "", roster: [], translation_pending: false, messages: [{ role: "minister", speaker: "洪承畴", content: "旧夜他臣", chat_turn_id: 7 }],
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
