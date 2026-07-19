import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAudienceChat } from "./useAudienceChat";
import { ChatModal } from "./components/modals";
import type { Minister, ServerChatMessage } from "./types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MINISTER: Minister = {
  name: "温体仁", office: "礼部尚书", office_type: "礼部", faction: "浙党",
  style: "", status: "active", status_label: "在朝", summary: "", favorite: false, skills: [],
};

const U = (content: string, turn: number): ServerChatMessage => ({ role: "user", content, chat_turn_id: turn });
const M = (content: string, turn: number): ServerChatMessage => ({ role: "minister", content, chat_turn_id: turn });
const A = (content: string, turn: number, id: number): ServerChatMessage => ({ role: "attendant", content, chat_turn_id: turn, record_id: id });

type SseEvent = { event: string; data: unknown };
const fmt = (e: SseEvent) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`;

/** 一次性 SSE 响应（真实 streamChat 解析）。 */
function sseResponse(events: SseEvent[]): Response {
  const enc = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(c) { for (const e of events) c.enqueue(enc.encode(fmt(e))); c.close(); },
    }),
    { status: 200 },
  );
}

/** 门控 SSE：先发 head，等 gate 再发 tail——模拟 stream 尾巴延迟到下一请求已在飞。 */
function gatedSseResponse(head: SseEvent[], gate: Promise<void>, tail: SseEvent[]): Response {
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

type HookApi = ReturnType<typeof useAudienceChat>;

function mount() {
  const hookRef = { current: null as HookApi | null };
  const busyRef = { current: "" };
  function Harness() {
    const selectedRef = React.useRef("温体仁");
    const [busy, setBusy] = React.useState("");
    busyRef.current = busy;
    hookRef.current = useAudienceChat(setBusy, selectedRef);
    return (
      <ChatModal
        minister={MINISTER} portraitPrefix="minister_"
        chat={hookRef.current.chat}
        pendingUserMessage={hookRef.current.pendingUserMessage}
        streamingMinisterMessage={hookRef.current.streamingMinisterMessage}
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
  // 已落定消息（排除在飞的待答/流式 pending 与「思索中」占位）
  const rows = () =>
    Array.from(host.querySelectorAll(".chat-log > .chat-message:not(.pending):not(.thinking)")).map((el) => {
      const role = ["user", "minister", "attendant"].find((r) => el.classList.contains(r)) || "";
      return `${role}:${el.querySelector("p")?.textContent ?? ""}`;
    });
  return { hookRef, busyRef, rows };
}

const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

const noopCbs = { onComplete: () => {}, onDone: () => {}, onLeave: () => {}, onError: () => {} };

afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = ""; });

describe("读心投递（#499 经真实 useAudienceChat 生产控制器）", () => {
  it("done1 / mind1 / 陈旧 done2 / mind2：陈旧 done2 整串替换不抹掉 mind1（reducer 保住并归位）", async () => {
    const { hookRef, rows } = mount();
    const hook = hookRef.current!;

    vi.stubGlobal("fetch", vi.fn(async () => sseResponse([
      { event: "done", data: { history: [U("问军务", 10), M("答军务", 10)], suggestions: [], directives: [] } },
      { event: "mindreading", data: { mindreading: { id: 1, narration: "近臣低声。" }, chat_turn_id: 10 } },
      { event: "end", data: {} },
    ])));
    await act(async () => { await hook.sendChat("温体仁", "问军务", noopCbs); });
    expect(rows()).toEqual(["user:问军务", "minister:答军务", "attendant:近臣低声。"]);

    // 陈旧 done2：服务端投影早于 mind1 落库、缺 a1；整串替换若不 reconcile 会抹掉 a1
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse([
      { event: "done", data: { history: [U("问军务", 10), M("答军务", 10), U("问钱粮", 11), M("答钱粮", 11)], suggestions: [], directives: [] } },
      { event: "mindreading", data: { mindreading: { id: 2, narration: "近臣低声。" }, chat_turn_id: 11 } },
      { event: "end", data: {} },
    ])));
    await act(async () => { await hook.sendChat("温体仁", "问钱粮", noopCbs); });

    // a1 仍在轮 10 之后（未被 done2 抹掉），a2 随轮 11；同文异记录都留存
    expect(rows()).toEqual([
      "user:问军务", "minister:答军务", "attendant:近臣低声。",
      "user:问钱粮", "minister:答钱粮", "attendant:近臣低声。",
    ]);
  });

  it("重叠流归属：旧流尾巴（finally）不清掉更新请求的 busy / 待答文", async () => {
    const { hookRef, busyRef, rows } = mount();
    const hook = hookRef.current!;

    let releaseEnd1!: () => void;
    const end1 = new Promise<void>((r) => { releaseEnd1 = r; });
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      call += 1;
      if (call === 1) {
        // 流 1：done1 后门控挂起，尾巴（end）延迟到流 2 已在飞后才到
        return gatedSseResponse(
          [{ event: "done", data: { history: [U("问1", 10), M("答1", 10)], suggestions: [], directives: [] } }],
          end1,
          [{ event: "end", data: {} }],
        );
      }
      // 流 2：尚未 done、保持在飞（busy 应为其所有）——测试期不释放
      return gatedSseResponse([], new Promise<void>(() => {}), []);
    }));

    // 启动流 1（不 await）；done1 清 busy、允许下一轮
    let p1!: Promise<void>;
    act(() => { p1 = hook.sendChat("温体仁", "问1", noopCbs); });
    await tick();
    expect(busyRef.current).toBe("");  // done1 已清 busy

    // 启动流 2：busy 重新占用、待答=问2；流 2 尚未 done → busy 保持
    let p2!: Promise<void>;
    act(() => { p2 = hook.sendChat("温体仁", "问2", noopCbs); });
    await tick();
    expect(busyRef.current).toBe("大臣思索中");
    expect(hookRef.current!.pendingUserMessage).toBe("问2");

    // 释放流 1 尾巴：其 finally 运行——绝不能清掉流 2 的 busy / 待答文
    releaseEnd1();
    await act(async () => { await p1; });
    expect(busyRef.current).toBe("大臣思索中");          // 流 2 的 busy 未被旧流清掉
    expect(hookRef.current!.pendingUserMessage).toBe("问2");  // 流 2 的待答文未被旧流清掉
    // 流 1 的 done1 历史仍在（其读心/回话不受影响）
    expect(rows()).toEqual(["user:问1", "minister:答1"]);
    void p2;
  });

  it("同一 (chat_turn_id, id) 经历史 + 读心交叠不重复；孤儿轮读心不追加串尾", async () => {
    const { hookRef, rows } = mount();
    const hook = hookRef.current!;
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse([
      { event: "done", data: { history: [U("问", 5), M("答", 5), A("近臣低声。", 5, 9)], suggestions: [], directives: [] } },
      { event: "mindreading", data: { mindreading: { id: 9, narration: "近臣低声。" }, chat_turn_id: 5 } },  // 与投影内同记录
      { event: "mindreading", data: { mindreading: { id: 1, narration: "孤儿。" }, chat_turn_id: 99 } },      // 归属轮不在视图
      { event: "end", data: {} },
    ])));
    await act(async () => { await hook.sendChat("温体仁", "问", noopCbs); });
    expect(rows()).toEqual(["user:问", "minister:答", "attendant:近臣低声。"]);  // 不重复、孤儿未追加
  });
});
