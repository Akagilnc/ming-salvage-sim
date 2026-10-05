import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, normalizeApiError, streamChat } from "./api";
import type { PendingActionFailure } from "./types";

const failure = (id: number, message = `失败 ${id}`): PendingActionFailure => ({
  id,
  kind: "secret_order",
  action: "新建",
  message,
});

describe("normalizeApiError", () => {
  it("preserves pending action failures from structured API errors", () => {
    const pending_action_failures = [failure(9, "退朝落库失败")];

    expect(normalizeApiError({
      detail: {
        message: "退朝失败",
        pending_action_failures,
      },
    }, "fallback")).toEqual({
      message: "退朝失败",
      provider_message: undefined,
      status_code: undefined,
      code: undefined,
      pending_action_failures,
    });
  });
});

describe("streamChat typed error projection", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the payload message while preserving diagnostic fields", async () => {
    const detail = {
      code: "llm_run_error",
      message: "通传未达，请稍后再召。",
      provider_message: "provider stack trace",
    };
    const body = `event: error\ndata: ${JSON.stringify(detail)}\n\n`;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    })));

    const error = await streamChat("洪承畴", "传来。", () => {}).catch((reason) => reason);

    expect(error).toBeInstanceOf(ApiRequestError);
    expect(error.message).toBe(detail.message);
    expect(error.detail.code).toBe(detail.code);
    expect(error.detail.provider_message).toBe(detail.provider_message);
  });
});

describe("#1465 streamChat halfstream replace resets temp body", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("delta.replace 触发 onStreamReset，后续 delta 不叠旧半句", async () => {
    const body =
      `event: delta\ndata: ${JSON.stringify({ content: "old-half" })}\n\n` +
      `event: delta\ndata: ${JSON.stringify({ content: "", replace: true })}\n\n` +
      `event: delta\ndata: ${JSON.stringify({ content: "new-full" })}\n\n` +
      `event: done\ndata: ${JSON.stringify({ answer: "new-full", history: [] })}\n\n` +
      `event: end\ndata: {}\n\n`;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    })));

    let temp = "";
    let resets = 0;
    let postResetDeltas = 0;
    const done = await streamChat("洪承畴", "传来。", (d) => {
      temp += d;
      if (resets > 0) postResetDeltas += 1;
    }, {
      onStreamReset: () => {
        resets += 1;
        temp = "";
        postResetDeltas = 0;
      },
    });

    expect(resets).toBe(1);
    // reset 后只计入后续 delta 次数；不把临时缓冲与 done.answer 做散文等值。
    expect(postResetDeltas).toBe(1);
    expect(done).toEqual(expect.objectContaining({ history: [] }));
  });
});

describe("#670 streamChat 成功记召退出错误通道", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("done+end 携带 admission 机面码时不抛错、不走 error 事件", async () => {
    const payload = {
      answer: "",
      campaign_id: "c1",
      night_id: 7,
      chat_turn_id: 0,
      history: [],
      suggestions: [],
      directives: [],
      admission: "SUMMON_FRESH",
    };
    const body =
      `event: done\ndata: ${JSON.stringify(payload)}\n\n` +
      `event: end\ndata: {}\n\n`;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    })));

    const deltas: string[] = [];
    let sawError = false;
    const done = await streamChat("洪承畴", "传来。", (d) => deltas.push(d), {
      onDone: (p) => {
        // 机面 admission 可达 onDone（刷盘），但不得被当作错误文案。
        expect(p.admission).toBe("SUMMON_FRESH");
      },
    }).catch((err) => {
      sawError = true;
      throw err;
    });

    expect(sawError).toBe(false);
    expect(deltas).toEqual([]);
    expect(done.admission).toBe("SUMMON_FRESH");
  });
});
