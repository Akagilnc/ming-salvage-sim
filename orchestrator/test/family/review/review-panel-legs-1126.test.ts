/**
 * #1126 CR R1 — review-panel dispatch is scope-neutral; single vs family differ
 * only by ReviewLegScope → prompt/soul. Seat control is a typed outcome, never
 * a Symbol thrown through Promise.allSettled.
 *
 * Seam: public cmrPanelLegs.ts API only.
 */

import { describe, expect, it } from "vitest";

import {
  CODE_REVIEW_LEG_PROMPT_FILE,
  CMR_PANEL_LEG_PROMPT_FILE,
  cmrPanelLegWorkerSpec,
  dispatchReviewPanelLegs,
} from "../../../src/family/cmrPanelLegs.js";
import type { WorkerCmrReviewLeg, WorkerResult } from "../../../src/types.js";

const OK: WorkerResult = {
  kind: "completed",
  output: {
    kind: "reviewer",
    findingsCount: 0,
    findings: [],
    rawStdout: "Standards+Spec review paper",
  },
};

describe("#1126 review panel legs — scope selects task prompt", () => {
  it("single scope pins code-review task + READ-ONLY; family keeps CMR task + lens soul", () => {
    const leg: WorkerCmrReviewLeg = {
      family: "codex",
      slug: "gpt-5.6-sol",
    };
    const single = cmrPanelLegWorkerSpec(leg, {
      kind: "single",
      judgeStep: "S3",
    });
    const family = cmrPanelLegWorkerSpec(leg, {
      kind: "family",
      pass: "correctness",
    });

    expect(single).toMatchObject({
      id: "S3",
      promptFile: CODE_REVIEW_LEG_PROMPT_FILE,
      soul: "READ-ONLY",
    });
    expect(family).toMatchObject({
      id: "S3",
      promptFile: CMR_PANEL_LEG_PROMPT_FILE,
      soul: "cmr-correctness",
    });
    expect(single.promptFile).not.toBe(family.promptFile);
  });
});

describe("#1126 review panel legs — typed seat control (no throw adapter)", () => {
  it("returns seat_control after all siblings settle; does not reject the round", async () => {
    const legs: WorkerCmrReviewLeg[] = [
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
    ];
    let settled = 0;
    const round = await dispatchReviewPanelLegs({
      legs,
      scope: { kind: "single", judgeStep: "S6" },
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
