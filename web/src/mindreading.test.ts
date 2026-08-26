import { describe, expect, it } from "vitest";
import { chatReducer, insertMindreadingByTurn, type MindreadingRecord } from "./mindreading";
import type { ChatMessage } from "./types";

describe("#1474 mindreading empty absence presentation", () => {
  const base: ChatMessage[] = [
    { role: "user", content: "问", chatTurnId: 10 },
    { role: "minister", content: "答", chatTurnId: 10 },
  ];

  it("empty / blank narration does not insert attendant bubble", () => {
    const records: MindreadingRecord[] = [
      { id: 1, narration: "" },
      { id: 2, narration: "   " },
      { id: 3 },
    ];
    const next = insertMindreadingByTurn(base, 10, records);
    expect(next).toEqual(base);
    expect(next.some((m) => m.role === "attendant")).toBe(false);
  });

  it("chatReducer mindreading empty path keeps prior chat intact", () => {
    const next = chatReducer(base, {
      type: "mindreading",
      chatTurnId: 10,
      records: [{ id: 9, narration: "" }],
    });
    expect(next).toEqual(base);
  });

  it("non-empty narration still inserts attendant bubble", () => {
    // #671：首尾空白只作判空，content 逐字保留原文
    const raw = "  皇爷，他这句另有盘算。  \n";
    const next = insertMindreadingByTurn(base, 10, [
      { id: 4, narration: raw },
    ]);
    expect(next).toHaveLength(3);
    expect(next[2]).toMatchObject({ role: "attendant", content: raw, chatTurnId: 10, recordId: 4 });
    expect(next.map((m) => `${m.role}:${m.content}`)).toEqual([
      "user:问",
      "minister:答",
      `attendant:${raw}`,
    ]);
  });
});
