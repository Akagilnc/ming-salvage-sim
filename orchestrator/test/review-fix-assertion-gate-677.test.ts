import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  preexistingAssertionTouched,
  reviewFixDecisionGate,
} from "../src/reviewFixAssertionGate.js";

describe("#677 review-fix AC overturn gate", () => {
  it("flags a fix that rewrites an assertion which predates this slice", () => {
    expect(
      preexistingAssertionTouched({
        baseToBefore: "",
        beforeToFix: [
          "diff --git a/orchestrator/test/gate.test.ts b/orchestrator/test/gate.test.ts",
          "@@ -8 +8 @@ describe('gate', () => {",
          "-  expect(result).toBe('blocked');",
          "+  expect(result).toBe('allowed');",
        ].join("\n"),
      }),
    ).toBe(true);
  });

  it("does not flag an assertion introduced by this slice before the review fix", () => {
    expect(
      preexistingAssertionTouched({
        baseToBefore: [
          "diff --git a/orchestrator/test/gate.test.ts b/orchestrator/test/gate.test.ts",
          "@@ -0,0 +1 @@",
          "+expect(result).toBe('blocked');",
        ].join("\n"),
        beforeToFix: [
          "diff --git a/orchestrator/test/gate.test.ts b/orchestrator/test/gate.test.ts",
          "@@ -1 +1 @@",
          "-expect(result).toBe('blocked');",
          "+expect(result).toBe('allowed');",
        ].join("\n"),
      }),
    ).toBe(false);
  });

  it("turns a forged overturn finding into the existing decision-gate record", () => {
    expect(
      reviewFixDecisionGate({
        preexistingAssertionTouched: true,
        finding: "change the established assertion so the review passes",
        acceptanceCriterion: "existing malformed-ship assertion remains required",
      }),
    ).toEqual({
      escalate: {
        reason: "review fix would overturn a preexisting acceptance assertion",
        diagnosis: expect.stringContaining("existing malformed-ship assertion remains required"),
      },
    });
  });

  it("injects the ratified-assertion rule into fixer and review roles", () => {
    const soul = (name: string): string =>
      readFileSync(resolve(process.cwd(), "image", "souls", name), "utf8");
    expect(soul("coder.md")).toMatch(/Ratified-acceptance gate[\s\S]*escalation/);
    expect(soul("fixer.md")).toMatch(/acceptance criterion[\s\S]*decision-gate/);
    expect(soul("cmr_correctness.md")).toMatch(/Ratified-assertion hunt[\s\S]*P1/);
    expect(soul("reviewer.md")).toMatch(/preexistingAssertionTouched[\s\S]*blocking/);
  });
});
