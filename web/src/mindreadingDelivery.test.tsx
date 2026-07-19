import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchMindreading, streamChat } from "./api";
import { mergeMindreadingRecords, projectServerHistory } from "./mindreading";
import { ChatModal } from "./components/modals";
import type { ChatMessage, Minister, ServerChatMessage } from "./types";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MINISTER: Minister = {
  name: "温体仁",
  office: "礼部尚书",
  office_type: "礼部",
  faction: "浙党",
  style: "",
  status: "active",
  status_label: "在朝",
  summary: "",
  favorite: false,
  skills: [],
};

type SseEvent = { event: string; data: unknown };

function sseResponse(events: SseEvent[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const e of events) {
        controller.enqueue(encoder.encode(`event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`));
      }
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as unknown as Response;
}

/**
 * 真实投递 seam tracer（#499）：驱动真实 streamChat（真实 SSE 解析）跨两轮召对
 * done1/mind1/done2/mind2 + 重开，回调接真实 projectServerHistory / mergeMindreadingRecords，
 * 渲染真实 ChatModal，读 DOM 断言玩家所见。错实现（覆盖抹掉读心 / 按正文去重 / latest-only）
 * 无法蒙混。仅 setChat 胶水为测试所写，被测逻辑全是生产代码。
 */
type Handles = {
  applyHistory: (history: ServerChatMessage[]) => void;
  surface: (turnId: number, record: { id?: number; narration?: string }) => void;
};

function ChatHarness({ handles }: { handles: React.MutableRefObject<Handles | null> }) {
  const [chat, setChat] = React.useState<ChatMessage[]>([]);
  handles.current = {
    applyHistory: (history) => setChat(projectServerHistory(history)),
    surface: (turnId, record) => setChat((cur) => mergeMindreadingRecords(cur, turnId, [record])),
  };
  const noop = () => {};
  return (
    <ChatModal
      minister={MINISTER}
      portraitPrefix="minister_"
      chat={chat}
      suggestions={[]}
      pendingUserMessage=""
      streamingMinisterMessage=""
      chatNotice=""
      chatFailures={[]}
      canUndoLastChat={false}
      composerHint=""
      input=""
      busy=""
      error=""
      secretOrders={[]}
      onInput={noop}
      onSend={noop}
      onRetryFailure={noop}
      onUndo={noop}
      onHint={noop}
      onFavorite={noop}
      onOpenEdict={noop}
      onClose={noop}
      onCancel={noop}
    />
  );
}

function mount() {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const handles = React.createRef<Handles | null>() as React.MutableRefObject<Handles | null>;
  act(() => root.render(<ChatHarness handles={handles} />));
  const attendantTexts = () =>
    Array.from(host.querySelectorAll(".chat-message.attendant p")).map((n) => n.textContent);
  const allRows = () =>
    Array.from(host.querySelectorAll(".chat-log > .chat-message")).map((el) => {
      const role = ["user", "minister", "attendant"].find((r) => el.classList.contains(r)) || "";
      return `${role}:${el.querySelector("p")?.textContent ?? ""}`;
    });
  return { handles, attendantTexts, allRows, host };
}

// 一轮召对的真实 streamChat 驱动：done(history) → mindreading(record) → end。
async function driveTurn(
  handles: Handles,
  events: SseEvent[],
): Promise<void> {
  vi.stubGlobal("fetch", vi.fn(async () => sseResponse(events)));
  await act(async () => {
    await streamChat("温体仁", "军务如何？", () => {}, {
      onDone: (done) => handles.applyHistory(done.history),
      onMindreading: (mind) => {
        if (mind.mindreading) handles.surface(Number(mind.chat_turn_id || 0), mind.mindreading);
      },
    });
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const U = (content: string, turn: number): ServerChatMessage => ({ role: "user", content, chat_turn_id: turn });
const M = (content: string, turn: number): ServerChatMessage => ({ role: "minister", content, chat_turn_id: turn });
const A = (content: string, turn: number, id: number): ServerChatMessage => ({
  role: "attendant", content, chat_turn_id: turn, record_id: id,
});

describe("读心跨轮投递（#499 真实 streamChat 生产路径）", () => {
  it("done1/mind1/done2/mind2 + 重开：两轮读心均保留、按轮归位、不重复", async () => {
    const { handles, attendantTexts, allRows } = mount();
    const h = handles.current!;

    // 第一轮：done1=[u1,m1]（读心尚未落库），随后 mind1 事件浮现
    await driveTurn(h, [
      { event: "done", data: { history: [U("军务如何？", 10), M("臣先陈军务。", 10)], suggestions: [], directives: [] } },
      { event: "mindreading", data: { mindreading: { id: 1, narration: "近臣低声：另有盘算。" }, chat_turn_id: 10 } },
      { event: "end", data: {} },
    ]);
    expect(attendantTexts()).toEqual(["近臣低声：另有盘算。"]);

    // 第二轮：done2 的服务端投影已内含第一轮读心 a1（这是修复要点：done 不再抹掉 a1）
    await driveTurn(h, [
      {
        event: "done",
        data: {
          history: [U("军务如何？", 10), M("臣先陈军务。", 10), A("近臣低声：另有盘算。", 10, 1), U("再问钱粮。", 11), M("臣续陈钱粮。", 11)],
          suggestions: [],
          directives: [],
        },
      },
      { event: "mindreading", data: { mindreading: { id: 2, narration: "近臣低声：另有盘算。" }, chat_turn_id: 11 } },
      { event: "end", data: {} },
    ]);

    // 两轮读心都在、按轮归位（a1 随轮 10、a2 随轮 11），同文异记录都显示、不重复
    expect(allRows()).toEqual([
      "user:军务如何？",
      "minister:臣先陈军务。",
      "attendant:近臣低声：另有盘算。",
      "user:再问钱粮。",
      "minister:臣续陈钱粮。",
      "attendant:近臣低声：另有盘算。",
    ]);

    // 重开（历史 GET 投影已含两轮读心）：整串一致、读心不丢不重
    act(() =>
      h.applyHistory([
        U("军务如何？", 10), M("臣先陈军务。", 10), A("近臣低声：另有盘算。", 10, 1),
        U("再问钱粮。", 11), M("臣续陈钱粮。", 11), A("近臣低声：另有盘算。", 11, 2),
      ]),
    );
    expect(attendantTexts()).toEqual(["近臣低声：另有盘算。", "近臣低声：另有盘算。"]);
  });

  it("取消/早重开：投影暂无读心，固定 expected 轮轮询就绪即归位、不去问 latest", async () => {
    const { handles, attendantTexts } = mount();
    const h = handles.current!;
    // 重开旧轮 10：投影此刻尚无读心
    act(() => h.applyHistory([U("军务如何？", 10), M("臣先陈军务。", 10)]));
    expect(attendantTexts()).toEqual([]);

    const asked: number[] = [];
    const server: Record<number, { chat_turn_id: number; mindreading: Array<{ id: number; narration: string }>; mindreading_pending?: boolean }> = {
      10: { chat_turn_id: 10, mindreading: [{ id: 7, narration: "旧轮近臣低声。" }] },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const tid = Number(new URL(url, "http://t.local").searchParams.get("chat_turn_id") || 0);
        asked.push(tid);
        return jsonResponse(server[tid] ?? { chat_turn_id: tid, mindreading: [], mindreading_pending: true });
      }),
    );

    await act(async () => {
      const snap = await fetchMindreading("温体仁", 10);  // 固定 expected 轮
      snap.mindreading.forEach((rec) => h.surface(10, rec));
    });

    expect(asked).toEqual([10]);  // 未去问 latest
    expect(attendantTexts()).toEqual(["旧轮近臣低声。"]);
  });
});
