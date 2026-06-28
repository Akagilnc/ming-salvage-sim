import { describe, expect, it } from "vitest";
import { normalizeApiError } from "./api";
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
