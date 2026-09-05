import { describe, expect, it, vi } from "vitest";
import { consumeSettleStream } from "./settleStream";

function streamResponse(chunks: string[], ok = true): Response {
  const encoder = new TextEncoder();
  let index = 0;
  const body = {
    getReader() {
      return {
        async read() {
          if (index >= chunks.length) return { value: undefined, done: true };
          const value = encoder.encode(chunks[index++]);
          return { value, done: false };
        },
      };
    },
  };
  return { ok, status: ok ? 200 : 500, body } as unknown as Response;
}

const silent = {
  onStage: vi.fn(),
  onThinking: vi.fn(),
  onNarrative: vi.fn(),
};

describe("consumeSettleStream residual flush", () => {
  it("parses a terminal done left in buffer without trailing blank line", async () => {
    const outcome = await consumeSettleStream(
      streamResponse(['event: done\ndata: {"ok":true}']),
      silent,
    );
    expect(outcome).toEqual({ kind: "done", data: { ok: true } });
  });

  it("parses a terminal decisions left in buffer without trailing blank line", async () => {
    const outcome = await consumeSettleStream(
      streamResponse(['event: decisions\ndata: {"items":[1]}']),
      silent,
    );
    expect(outcome).toEqual({ kind: "decisions", data: { items: [1] } });
  });

  it("still returns interrupted for empty/incomplete tails", async () => {
    const outcome = await consumeSettleStream(
      streamResponse(["event: done\ndata: {"]),
      silent,
    );
    expect(outcome).toEqual({ kind: "error", data: "推演流意外中断。" });
  });

  it("keeps normal \\n\\n terminated done path", async () => {
    const outcome = await consumeSettleStream(
      streamResponse(['event: done\ndata: {"ok":true}\n\n']),
      silent,
    );
    expect(outcome).toEqual({ kind: "done", data: { ok: true } });
  });
});

describe("consumeSettleStream continue-style stages (#1195)", () => {
  it("invokes onStage for each stage then returns done state", async () => {
    const onStage = vi.fn();
    const outcome = await consumeSettleStream(
      streamResponse([
        'event: stage\ndata: {"content":"检查模型后端..."}\n\n',
        'event: stage\ndata: {"content":"载入上次进度..."}\n\n',
        'event: done\ndata: {"state":{"turn":{"turn":2}}}\n\n',
      ]),
      { onStage, onThinking: vi.fn(), onNarrative: vi.fn() },
      { httpErrorLabel: "继续失败" },
    );
    expect(onStage.mock.calls.map((c) => c[0])).toEqual([
      { content: "检查模型后端...", current: undefined, total: undefined },
      { content: "载入上次进度...", current: undefined, total: undefined },
    ]);
    expect(outcome).toEqual({ kind: "done", data: { state: { turn: { turn: 2 } } } });
  });

  it("uses custom httpErrorLabel on non-OK responses", async () => {
    await expect(
      consumeSettleStream(streamResponse([], false), silent, { httpErrorLabel: "继续失败" }),
    ).rejects.toThrow("继续失败：HTTP 500");
  });

  it("includes server JSON detail on non-OK responses", async () => {
    const response = {
      ok: false,
      status: 404,
      body: null,
      async json() {
        return { detail: "无上次进度可继续，请先新游戏或加载存档。" };
      },
    } as unknown as Response;
    await expect(
      consumeSettleStream(response, silent, { httpErrorLabel: "继续失败" }),
    ).rejects.toThrow("无上次进度可继续，请先新游戏或加载存档。");
  });
});

describe("#1725 stage SSE forwards typed progress facts", () => {
  it("passes current/total through without deriving them from content labels", async () => {
    const onStage = vi.fn();
    const outcome = await consumeSettleStream(
      streamResponse([
        // Arbitrary display label + independent typed progress — proves no label reverse-lookup.
        'event: stage\ndata: {"content":"任意显示文案","current":3,"total":6}\n\n',
        'event: stage\ndata: {"content":"另一段","current":7,"total":7}\n\n',
        'event: stage\ndata: {"content":"无进度的菜单文案"}\n\n',
        'event: done\ndata: {"ok":true}\n\n',
      ]),
      { onStage, onThinking: vi.fn(), onNarrative: vi.fn() },
    );
    expect(outcome.kind).toBe("done");
    expect(onStage.mock.calls.map((c) => c[0])).toEqual([
      { content: "任意显示文案", current: 3, total: 6 },
      { content: "另一段", current: 7, total: 7 },
      { content: "无进度的菜单文案", current: undefined, total: undefined },
    ]);
  });
});
