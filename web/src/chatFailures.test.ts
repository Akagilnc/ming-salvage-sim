import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, normalizeApiError, streamChat } from "./api";
import { mergePendingActionFailures, refreshRetriedPendingActionFailures } from "./chatFailures";
import type { PendingActionFailure } from "./types";

const failure = (id: number, message = `失败 ${id}`): PendingActionFailure => ({
  id,
  kind: "secret_order",
  action: "新建",
  message,
});

describe("mergePendingActionFailures", () => {
  it("keeps existing retryable failures when an unrelated chat reply reports none", () => {
    const existing = [failure(1, "旧失败")];

    expect(mergePendingActionFailures(existing, [])).toEqual(existing);
  });

  it("adds new failures without dropping old ones", () => {
    expect(mergePendingActionFailures([failure(1)], [failure(2)])).toEqual([
      failure(1),
      failure(2),
    ]);
  });

  it("replaces a failure with the latest payload for the same id", () => {
    expect(mergePendingActionFailures([failure(1, "旧")], [failure(1, "新")])).toEqual([
      failure(1, "新"),
    ]);
  });
});

describe("refreshRetriedPendingActionFailures", () => {
  it("refreshes same-minister secret-order failures without dropping unsupported failures", () => {
    const officeFailure: PendingActionFailure = {
      id: 3,
      kind: "office",
      action: "任命",
      minister_name: "张居正",
      message: "任免未能正式落库",
    };

    expect(refreshRetriedPendingActionFailures(
      [
        { ...failure(1, "已重试"), minister_name: "张居正" },
        { ...failure(2, "同臣旧密令失败"), minister_name: "张居正" },
        officeFailure,
        { ...failure(4, "别臣密令失败"), minister_name: "申时行" },
      ],
      1,
      "张居正",
      [{ ...failure(5, "同臣新密令失败"), minister_name: "张居正" }],
    )).toEqual([
      officeFailure,
      { ...failure(4, "别臣密令失败"), minister_name: "申时行" },
      { ...failure(5, "同臣新密令失败"), minister_name: "张居正" },
    ]);
  });

  it("does not drop unscoped secret-order failures when no minister is selected", () => {
    expect(refreshRetriedPendingActionFailures(
      [
        { ...failure(1, "已重试") },
        { ...failure(2, "仍需保留") },
      ],
      1,
      undefined,
      [],
    )).toEqual([
      { ...failure(2, "仍需保留") },
    ]);
  });
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
    expect(error.message).toBe("通传未达，请稍后再召。");
    expect(error.detail.code).toBe("llm_run_error");
    expect(error.detail.provider_message).toBe("provider stack trace");
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
        expect(p.answer).toBe("");
        expect(String(p.answer)).not.toContain("SUMMON_");
        expect(String(p.answer)).not.toContain("赴京");
        expect(String(p.answer)).not.toContain("不能入殿");
      },
    }).catch((err) => {
      sawError = true;
      throw err;
    });

    expect(sawError).toBe(false);
    expect(deltas).toEqual([]);
    expect(done.admission).toBe("SUMMON_FRESH");
    expect(done.answer).toBe("");
    // 消费端契约：成功记召不经 ApiRequestError / error 事件进 danger note。
    expect(String(done.answer || "")).not.toMatch(/SUMMON_|赴京|在途|不能入殿/);
  });
});
