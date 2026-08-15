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
