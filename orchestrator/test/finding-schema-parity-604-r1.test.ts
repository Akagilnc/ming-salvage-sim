/**
 * #604 ship-pre CMR correctness r1 — P2-a / P2-b finding-contract parity.
 *
 * P2-a: an `accepted_suppressed` governance disposition is ONLY valid on
 *   wont_fix/rejected. On fix_now (or any other action) it must be rejected —
 *   classifyFindings treats fix_now as blocking, so a fix_now + accepted_suppressed
 *   would silently turn the governance suppression into a blocker.
 *
 */

import { describe, expect, it } from "vitest";

import { isValidFinding } from "../src/validate.js";

const suppression = {
  kind: "accepted_suppressed" as const,
  source: "ADR 0030 accepted scope",
  scope: "existing invariant",
  reason: "accepted as outside slice",
  boundedReopen: "reopen if severity escalates or new evidence changes scope",
};

function baseFinding(): Record<string, unknown> {
  return {
    severity: "medium",
    category: "correctness",
    claim_quote: "claim",
    location: "src/x.ts:1",
    suggested_fix: "fix it",
  };
}

describe("#604 r1 P2-a — accepted_suppressed only valid on wont_fix/rejected (validate.ts)", () => {
  it("rejects a fix_now finding carrying an accepted_suppressed disposition", () => {
    const finding = {
      ...baseFinding(),
      action: "fix_now",
      disposition: suppression,
    };
    expect(isValidFinding(finding)).toBe(false);
  });

  it("accepts a wont_fix finding carrying an accepted_suppressed disposition", () => {
    const finding = {
      ...baseFinding(),
      action: "wont_fix",
      disposition_reason: "r",
      disposition: suppression,
    };
    expect(isValidFinding(finding)).toBe(true);
  });
});
