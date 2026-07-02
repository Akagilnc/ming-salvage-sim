import { describe, expect, it } from "vitest";

import { hasExplicitAcceptedSuppressionSource } from "../src/acceptedSuppression.js";

describe("accepted suppression source authority", () => {
  it("accepts authoritative ADR sources even when their title names a model or worker", () => {
    expect(hasExplicitAcceptedSuppressionSource("ADR 0031 model registry")).toBe(true);
    expect(hasExplicitAcceptedSuppressionSource("issue #445 worker route")).toBe(true);
  });

  it("rejects bare reviewer/model/worker self-authorized sources", () => {
    expect(hasExplicitAcceptedSuppressionSource("model said ok")).toBe(false);
    expect(hasExplicitAcceptedSuppressionSource("reviewer judgement")).toBe(false);
    expect(hasExplicitAcceptedSuppressionSource("worker self-check")).toBe(false);
  });
});
