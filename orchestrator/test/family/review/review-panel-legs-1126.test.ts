/**
 * #1126 — typed seat_control contract for review-panel dispatch (scope-neutral).
 * Axis prompt selection is covered by runOrchestrator tracer
 * (single-slice-review-legs-1126.test.ts).
 *
 * Seam: public reviewPanelLegs.ts API only.
 */

import { describe, expect, it } from "vitest";

import { dispatchReviewPanelLegs } from "../../../src/family/reviewPanelLegs.js";
import type { WorkerCmrReviewLeg, WorkerResult } from "../../../src/types.js";

const OK: WorkerResult = {
  kind: "completed",
  output: {
    kind: "reviewer",
    findingsCount: 0,
    findings: [],
    rawStdout: "family panel review paper",
  },
};

describe("#1126 review panel legs — typed seat control (no throw adapter)", () => {
  it("returns seat_control after all siblings settle; does not reject the round", async () => {
    const legs: WorkerCmrReviewLeg[] = [
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
    ];
    let settled = 0;
    const round = await dispatchReviewPanelLegs({
      legs,
      scope: { kind: "family", pass: "correctness" },
      dispatch: async (spec) => {
        settled += 1;
        await new Promise((r) => setTimeout(r, 5));
        if (spec.model === "gpt-5.6-sol") {
          return {
            kind: "seat_control",
            control: { kind: "relay" as const },
          };
        }
        return { kind: "leg_result", result: OK };
      },
    });

    expect(settled).toBe(2);
    expect(round).toEqual({
      kind: "seat_control",
      control: { kind: "relay" },
    });
  });
});
