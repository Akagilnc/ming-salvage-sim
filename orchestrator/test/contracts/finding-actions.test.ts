/**
 * #617: `defer` is removed from the `Finding.action` union and its compile
 * closure. This test records the contract at the runtime validation seam,
 * the TypeScript type seam, and the zod schema seams used by the standalone
 * and family CMR reviewers.
 */

import { describe, expect, it } from "vitest";

import { cmrReviewerFindingSchema } from "../../src/family/realFamilyBackend.js";
import { findingSchema } from "../../src/realBackend.js";
import type { Finding } from "../../src/types.js";

const strayDeferFinding = {
  severity: "medium" as const,
  category: "correctness",
  claim_quote: "claim",
  location: "src/x.ts:1",
  suggested_fix: "fix it",
  action: "defer",
};

describe("#617 — defer removed from Finding.action", () => {
  it("standalone reviewer zod schema rejects action: defer", () => {
    const result = findingSchema.safeParse(strayDeferFinding);
    expect(result.success).toBe(false);
  });

  it("family CMR reviewer zod schema rejects action: defer", () => {
    const result = cmrReviewerFindingSchema.safeParse(strayDeferFinding);
    expect(result.success).toBe(false);
  });

  it("type union does not include defer", () => {
    // If the union still includes "defer", the @ts-expect-error is unused and
    // the project's own typecheck fails (RED). Once "defer" is removed,
    // assigning it becomes a real error and the directive is satisfied (GREEN).
    // @ts-expect-error — defer was removed from Finding.action in #617.
    const _check: Finding["action"] = "defer";
    expect(_check).toBe("defer");
  });
});
