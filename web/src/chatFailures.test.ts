import { describe, expect, it } from "vitest";
import { mergePendingActionFailures } from "./chatFailures";
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
