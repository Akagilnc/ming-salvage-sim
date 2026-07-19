import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { chatReducer, type ChatAction } from "./mindreading";
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

const U = (content: string, turn: number): ServerChatMessage => ({ role: "user", content, chat_turn_id: turn });
const M = (content: string, turn: number): ServerChatMessage => ({ role: "minister", content, chat_turn_id: turn });
const A = (content: string, turn: number, id: number): ServerChatMessage => ({
  role: "attendant", content, chat_turn_id: turn, record_id: id,
});

const rows = (chat: ChatMessage[]) => chat.map((m) => `${m.role}:${m.content}`);

/** 真实生产 reducer（App 经 useReducer(chatReducer) 消费）的最短 tracer：
 *  串起一串真实 action，末态即玩家所见。无复制 setChat 胶水。 */
function reduce(actions: ChatAction[]): ChatMessage[] {
  return actions.reduce((state, action) => chatReducer(state, action), [] as ChatMessage[]);
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("读心跨轮投递（#499 真实 App reducer 生产路径）", () => {
  it("done1 / done2 / 迟到 mind1 / mind2 / 重开：读心各随其归属轮回话、同文异记录都留存", () => {
    // 逐个真实 action（App onDone→history、onMindreading→mindreading、重开→history）：
    const afterDone1 = reduce([
      { type: "history", history: [U("军务如何？", 10), M("臣先陈军务。", 10)] },  // done1
    ]);
    expect(rows(afterDone1)).toEqual(["user:军务如何？", "minister:臣先陈军务。"]);

    // done2 先于迟到的 mind1 到达：此刻服务端投影尚不含 a1
    const afterDone2 = chatReducer(afterDone1, {
      type: "history",
      history: [U("军务如何？", 10), M("臣先陈军务。", 10), U("再问钱粮。", 11), M("臣续陈钱粮。", 11)],
    });
    expect(rows(afterDone2)).toEqual([
      "user:军务如何？", "minister:臣先陈军务。", "user:再问钱粮。", "minister:臣续陈钱粮。",
    ]);

    // 迟到 mind1（轮 10）：必须落在轮 10 回话之后，而非串尾（轮 11 之后）——本轮修复要点
    const afterMind1 = chatReducer(afterDone2, {
      type: "mindreading", chatTurnId: 10, records: [{ id: 1, narration: "近臣低声：另有盘算。" }],
    });
    expect(rows(afterMind1)).toEqual([
      "user:军务如何？",
      "minister:臣先陈军务。",
      "attendant:近臣低声：另有盘算。",   // ← 归位于轮 10，不在串尾
      "user:再问钱粮。",
      "minister:臣续陈钱粮。",
    ]);

    // mind2（轮 11，narration 与 mind1 同文但记录不同）：随轮 11 回话之后
    const afterMind2 = chatReducer(afterMind1, {
      type: "mindreading", chatTurnId: 11, records: [{ id: 2, narration: "近臣低声：另有盘算。" }],
    });
    expect(rows(afterMind2)).toEqual([
      "user:军务如何？",
      "minister:臣先陈军务。",
      "attendant:近臣低声：另有盘算。",
      "user:再问钱粮。",
      "minister:臣续陈钱粮。",
      "attendant:近臣低声：另有盘算。",   // 同文异记录，各随其轮
    ]);

    // 重开：历史投影已含两轮读心，整串一致、不丢不重
    const afterReload = chatReducer(afterMind2, {
      type: "history",
      history: [
        U("军务如何？", 10), M("臣先陈军务。", 10), A("近臣低声：另有盘算。", 10, 1),
        U("再问钱粮。", 11), M("臣续陈钱粮。", 11), A("近臣低声：另有盘算。", 11, 2),
      ],
    });
    expect(rows(afterReload)).toEqual(rows(afterMind2));

    // 真实 ChatModal 渲染末态：玩家看到两条同文递话，各随其轮回话之后
    const host = document.createElement("div");
    document.body.appendChild(host);
    act(() => createRoot(host).render(renderChat(afterReload)));
    const domRows = Array.from(host.querySelectorAll(".chat-log > .chat-message")).map((el) => {
      const role = ["user", "minister", "attendant"].find((r) => el.classList.contains(r)) || "";
      return `${role}:${el.querySelector("p")?.textContent ?? ""}`;
    });
    expect(domRows).toEqual([
      "user:军务如何？",
      "minister:臣先陈军务。",
      "attendant:近臣低声：另有盘算。",
      "user:再问钱粮。",
      "minister:臣续陈钱粮。",
      "attendant:近臣低声：另有盘算。",
    ]);
  });

  it("同一 (chat_turn_id, record_id) 经 SSE + 历史/轮询交叠不重复", () => {
    const state = reduce([
      { type: "history", history: [U("问", 5), M("答", 5)] },
      { type: "mindreading", chatTurnId: 5, records: [{ id: 9, narration: "近臣低声。" }] },  // SSE
      { type: "mindreading", chatTurnId: 5, records: [{ id: 9, narration: "近臣低声。" }] },  // 轮询重复
    ]);
    expect(rows(state)).toEqual(["user:问", "minister:答", "attendant:近臣低声。"]);  // 恰一条
  });

  it("归属轮回话尚未在视图：不追加串尾、不臆测（拆除 tail-append）", () => {
    const state = reduce([
      { type: "history", history: [U("问5", 5), M("答5", 5)] },
      { type: "mindreading", chatTurnId: 99, records: [{ id: 1, narration: "孤儿读心。" }] },
    ]);
    expect(rows(state)).toEqual(["user:问5", "minister:答5"]);  // 未追加串尾
  });
});

function renderChat(chat: ChatMessage[]) {
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
