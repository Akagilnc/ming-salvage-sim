import { afterEach, describe, expect, it, vi } from "vitest";
import { retryAudienceStoryExtraction } from "./extractionRetry";

type SseEvent = { event: string; data: unknown };
const fmt = (e: SseEvent) => `event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`;

function sse(events: SseEvent[]): Response {
  const enc = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(c) {
        for (const e of events) c.enqueue(enc.encode(fmt(e)));
        c.close();
      },
    }),
    { status: 200 },
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("retryAudienceStoryExtraction (#1312 SSE progress)", () => {
  it("surfaces stage progress and returns done payload", async () => {
    const stages: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async () => sse([
      { event: "stage", data: { content: "补写召对账本（1/2）·袁崇焕" } },
      { event: "stage", data: { content: "补写召对账本（2/2）·孙承宗" } },
      { event: "done", data: { night_id: 3, count: 0, pending: [] } },
    ])));

    const settled = vi.fn();
    const result = await retryAudienceStoryExtraction(settled, {
      onStage: (text) => stages.push(text),
    });

    expect(stages).toEqual([
      "补写召对账本（1/2）·袁崇焕",
      "补写召对账本（2/2）·孙承宗",
    ]);
    expect(result).toEqual({ night_id: 3, count: 0, pending: [] });
    expect(settled).toHaveBeenCalledTimes(1);
  });

  it("does not settle scroll when pending remains", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sse([
      { event: "done", data: { night_id: 1, count: 2, pending: [{ chat_turn_id: 9, minister_name: "温体仁", night_id: 1 }] } },
    ])));
    const settled = vi.fn();
    const result = await retryAudienceStoryExtraction(settled);
    expect(result.count).toBe(2);
    expect(settled).not.toHaveBeenCalled();
  });

  it("raises on SSE error event", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sse([
      { event: "error", data: { message: "LLM 暂不可用" } },
    ])));
    await expect(retryAudienceStoryExtraction(() => {})).rejects.toThrow("LLM 暂不可用");
  });
});
