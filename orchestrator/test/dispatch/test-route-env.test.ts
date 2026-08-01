import { describe, expect, it, vi } from "vitest";
import { activeModelRoute } from "../../src/modelRoutes.js";

describe("#441 test route isolation", () => {
  it("defaults tests to the normal route unless a test opts into another route", () => {
    expect(activeModelRoute()).toMatchObject({
      routeName: "normal",
      slots: {
        coder: "gpt-5.6-terra",
        coderFix: "gpt-5.6-terra",
        ship: "sonnet",
        merger: "sonnet",
        cmrCompleteness: "gpt-5.6-sol",
        cmrCorrectness: "gpt-5.6-sol",
        collector: "grok-4.5",
        verify: "gpt-5.6-sol",
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

  it("lets a CMR harness opt into the active tight route", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");

    expect(activeModelRoute().legCollections.cmrReview.map((leg) => leg.slug)).toEqual([
      "gpt-5.6-sol",
      "grok-4.5",
      "agy",
    ]);
  });
});
