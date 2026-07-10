import { describe, expect, it, vi } from "vitest";
import { activeModelRoute, cmrLegAccountingFailure } from "../src/modelRoutes.js";

describe("#441 test route isolation", () => {
  it("defaults tests to the normal route unless a test opts into another route", () => {
    expect(activeModelRoute()).toMatchObject({
      routeName: "normal",
      slots: {
        coder: "gpt-5.6-terra",
        reviewer: "gpt-5.6-sol",
        coderFix: "gpt-5.6-terra",
        ship: "sonnet",
        merger: "sonnet",
        cmrCompleteness: "gpt-5.6-terra",
        cmrCorrectness: "gpt-5.6-terra",
      },
      legCollections: {
        cmrReview: [
          { family: "codex", slug: "gpt-5.6-sol" },
          { family: "claude", slug: "opus" },
          { family: "agy", slug: "agy" },
        ],
      },
    });
  });

  it("still lets fake CMR accounting opt into the active tight route", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

    expect(activeModelRoute().legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.6-sol",
      "agy",
    ]);
    expect(
      cmrLegAccountingFailure({ successfulLegs: ["gpt-5.6-sol", "agy"] }),
    ).toBeUndefined();
    expect(
      cmrLegAccountingFailure({ successfulLegs: ["gpt-5.6-sol", "agy", "opus"] }),
    ).toMatch(/not declared.*opus/i);
  });
});
