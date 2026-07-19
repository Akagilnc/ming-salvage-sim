import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { pollMindreadingUntilReady } from "./api";
import { mergeMindreadingRecords, type MindreadingRecord } from "./mindreading";
import { ChatModal } from "./components/modals";
import type { ChatMessage, Minister } from "./types";

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

const noSleep = async () => {};

/**
 * 真实投递 seam tracer：把 SSE / 历史 / 轮询三路都经生产函数
 * (mergeMindreadingRecords / pollMindreadingUntilReady) 汇入真实 ChatModal 渲染，
 * 读 DOM 断言玩家所见。不复制去重/归位实现——错实现无法蒙混过关。
 */
type Handles = {
  loadHistory: (history: ChatMessage[], turnId: number, records: MindreadingRecord[]) => void;
  surfaceSse: (turnId: number, record: MindreadingRecord) => void;
  appendMinister: (content: string) => void;
  runPoll: (ministerName: string, expectedTurnId: number) => Promise<void>;
};

function ChatHarness({ handles }: { handles: React.MutableRefObject<Handles | null> }) {
  const [chat, setChat] = React.useState<ChatMessage[]>([]);
  const surface = React.useCallback(
    (turnId: number, records: MindreadingRecord[]) =>
      setChat((cur) => mergeMindreadingRecords(cur, turnId, records)),
    [],
  );
  handles.current = {
    loadHistory: (history, turnId, records) => setChat(mergeMindreadingRecords(history, turnId, records)),
    surfaceSse: (turnId, record) => surface(turnId, [record]),
    appendMinister: (content) => setChat((cur) => [...cur, { role: "minister", content }]),
    runPoll: (ministerName, expectedTurnId) =>
      pollMindreadingUntilReady(ministerName, expectedTurnId, {
        onRecords: (records, turnId) => surface(turnId, records),
        shouldContinue: () => true,
        sleep: noSleep,
      }),
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
  return { handles: handles.current!, attendantTexts, root, host };
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("读心投递 seam（#499 真实组件 tracer）", () => {
  it("同一 (chat_turn_id, id) 经 SSE + 历史重开不重复递话", () => {
    const { handles, attendantTexts } = mount();
    const rec: MindreadingRecord = { id: 1, narration: "近臣低声：另有盘算。" };

    act(() => handles.surfaceSse(10, rec));          // 实时 SSE 浮现
    act(() => handles.loadHistory([{ role: "minister", content: "臣先陈军务。" }], 10, [rec]));  // 重开历史含同记录

    expect(attendantTexts()).toEqual(["近臣低声：另有盘算。"]);  // 恰一条，未因重开重复
  });

  it("不同记录（不同 id）即使 narration 相同也都浮现——不按正文去重", () => {
    const { handles, attendantTexts } = mount();

    act(() => handles.surfaceSse(10, { id: 1, narration: "近臣低声。" }));
    act(() => handles.surfaceSse(10, { id: 2, narration: "近臣低声。" }));  // 同文、异记录

    expect(attendantTexts()).toEqual(["近臣低声。", "近臣低声。"]);  // 两条都在
  });

  it("旧轮轮询期间新轮成为 latest，旧记录仍按 expected 轮固定浮现、不被截断", async () => {
    // 服务端按请求的 chat_turn_id 分轮作答：latest=11，但旧轮 10 的读心此刻才落库。
    const server: Record<number, { chat_turn_id: number; mindreading: MindreadingRecord[]; mindreading_pending?: boolean }> = {
      10: { chat_turn_id: 10, mindreading: [{ id: 5, narration: "旧轮近臣低声。" }] },
      11: { chat_turn_id: 11, mindreading: [], mindreading_pending: true },
    };
    const askedTurns: number[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const parsed = new URL(url, "http://test.local");
        const tid = Number(parsed.searchParams.get("chat_turn_id") || 0);
        askedTurns.push(tid);
        const snap = server[tid] ?? { chat_turn_id: tid, mindreading: [], mindreading_pending: true };
        return { ok: true, json: async () => snap } as unknown as Response;
      }),
    );

    const { handles, attendantTexts } = mount();
    // 重开旧轮 10（此刻尚无读心），随后新一轮 11 的大臣回话先到、成为 latest
    act(() => handles.loadHistory([{ role: "minister", content: "旧轮回话。" }], 10, []));
    act(() => handles.appendMinister("新轮回话。"));

    // 轮询锁定 expected 轮 10（非 latest 11）
    await act(async () => {
      await handles.runPoll("温体仁", 10);
    });

    expect(askedTurns).toEqual([10]);  // 固定 expected 轮，未去问 latest
    expect(attendantTexts()).toEqual(["旧轮近臣低声。"]);  // 旧轮读心仍浮现、未被新 latest 截断
  });
});
