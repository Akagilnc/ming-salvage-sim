import { afterEach, describe, expect, it, vi } from "vitest";
import { pollMindreadingUntilReady } from "./api";

type Snapshot = {
  chat_turn_id: number;
  mindreading: Array<{ narration?: string }>;
  mindreading_pending?: boolean;
};

const mockFetchSequence = (snapshots: Snapshot[]) => {
  let call = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      const payload = snapshots[Math.min(call, snapshots.length - 1)];
      call += 1;
      return { ok: true, json: async () => payload } as unknown as Response;
    }),
  );
  return () => call;
};

const noSleep = async () => {};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("pollMindreadingUntilReady (#499 取消/早重开)", () => {
  it("轮询到读心落库后浮现一次并停止", async () => {
    const calls = mockFetchSequence([
      { chat_turn_id: 7, mindreading: [], mindreading_pending: true },
      { chat_turn_id: 7, mindreading: [], mindreading_pending: true },
      { chat_turn_id: 7, mindreading: [{ narration: "近臣低声：另有盘算。" }], mindreading_pending: true },
    ]);
    const surfaced: Array<[string, number]> = [];

    await pollMindreadingUntilReady("温体仁", {
      onNarration: (n, id) => surfaced.push([n, id]),
      shouldContinue: () => true,
      sleep: noSleep,
    });

    expect(surfaced).toEqual([["近臣低声：另有盘算。", 7]]);
    // 第 3 次拉到记录即返回，不再多拉
    expect(calls()).toBe(3);
  });

  it("mindreading_pending=false 即停，不空转到上限", async () => {
    const calls = mockFetchSequence([
      { chat_turn_id: 9, mindreading: [], mindreading_pending: false },
    ]);
    const surfaced: string[] = [];

    await pollMindreadingUntilReady("毕自严", {
      onNarration: (n) => surfaced.push(n),
      shouldContinue: () => true,
      sleep: noSleep,
      maxAttempts: 50,
    });

    expect(surfaced).toEqual([]);
    expect(calls()).toBe(1);
  });

  it("shouldContinue 变假（切人/重开作废）立即停止，不再拉取", async () => {
    const calls = mockFetchSequence([
      { chat_turn_id: 3, mindreading: [], mindreading_pending: true },
    ]);
    const surfaced: string[] = [];

    await pollMindreadingUntilReady("温体仁", {
      onNarration: (n) => surfaced.push(n),
      shouldContinue: () => false,
      sleep: noSleep,
    });

    expect(surfaced).toEqual([]);
    expect(calls()).toBe(0);
  });

  it("已由 SSE 实时浮现的读心，轮询经记录身份去重不重复递话", async () => {
    // 递话去重规则（与 main.tsx appendAttendantNarration 同判据：按 narration 正文去重）
    const chat: Array<{ role: string; content: string }> = [
      { role: "minister", content: "臣先陈军务。" },
      { role: "attendant", content: "近臣低声：另有盘算。" }, // SSE 已浮现
    ];
    const appendAttendantNarration = (narration: string) => {
      const content = narration.trim();
      if (!content) return;
      if (chat.some((m) => m.role === "attendant" && m.content === content)) return;
      chat.push({ role: "attendant", content });
    };

    mockFetchSequence([
      { chat_turn_id: 7, mindreading: [{ narration: "近臣低声：另有盘算。" }], mindreading_pending: true },
    ]);

    await pollMindreadingUntilReady("温体仁", {
      onNarration: (n) => appendAttendantNarration(n),
      shouldContinue: () => true,
      sleep: noSleep,
    });

    const attendantMsgs = chat.filter((m) => m.role === "attendant");
    expect(attendantMsgs).toHaveLength(1);
    expect(attendantMsgs[0].content).toBe("近臣低声：另有盘算。");
  });
});
