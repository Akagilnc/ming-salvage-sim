import { describe, expect, it, vi } from "vitest";
import { activeModelRoute, cmrLegAccountingFailure } from "../src/modelRoutes.js";

describe("#441 test route isolation", () => {
  it("defaults tests to the normal route unless a test opts into another route", () => {
    expect(activeModelRoute().routeName).toBe("normal");
  });

  it("still lets fake CMR accounting opt into the active tight route", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

    expect(activeModelRoute().legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.5",
      "agy",
    ]);
    expect(
      cmrLegAccountingFailure({ successfulLegs: ["gpt-5.5", "agy"] }),
    ).toBeUndefined();
    expect(
      cmrLegAccountingFailure({ successfulLegs: ["gpt-5.5", "agy", "opus"] }),
    ).toMatch(/not declared.*opus/i);
  });
});
