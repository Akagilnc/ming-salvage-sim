import { describe, expect, it } from "vitest";
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

const silent = {};

describe("consumeSettleStream residual flush", () => {
  it.each([
    { event: "done", data: { ok: true }, suffix: "" },
    { event: "done", data: { ok: true }, suffix: "\n\n" },
    { event: "decisions", data: { items: [1] }, suffix: "" },
  ])("parses terminal $event with suffix '$suffix'", async ({ event, data, suffix }) => {
    const outcome = await consumeSettleStream(
      streamResponse([`event: ${event}\ndata: ${JSON.stringify(data)}${suffix}`]),
      silent,
    );
    expect(outcome).toEqual({ kind: event, data });
  });


  it("still returns interrupted for empty/incomplete tails", async () => {
    const outcome = await consumeSettleStream(
      streamResponse(["event: done\ndata: {"]),
      silent,
    );
    // Structural interrupt channel; do not lock production chrome copy.
    expect(outcome.kind).toBe("error");
    expect(typeof outcome.data).toBe("string");
    expect(outcome.data).not.toBe("");
  });

});

describe("consumeSettleStream HTTP errors", () => {
  it("uses custom httpErrorLabel on non-OK responses", async () => {
    await expect(
      consumeSettleStream(streamResponse([], false), silent, { httpErrorLabel: "继续失败" }),
    ).rejects.toThrow("继续失败");
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
