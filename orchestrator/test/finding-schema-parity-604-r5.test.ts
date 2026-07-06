/**
 * #604 ship-pre CMR correctness r5 (E1) — strict validator parity for DELETED
 * disposition fields.
 *
 * The family CMR zod schemas (`cmrDispositionEvidenceSchema` /
 * `cmrFindingDispositionSchema`) and the standalone reviewer `disposition` schema
 * are `.strict()`, so a disposition carrying a DELETED routing field
 * (`targetModule`, `owningIssue`, `missingSurface`, `nextStep`, …) is REJECTED.
 * But the light-weight hand-written TS validators in `src/validate.ts`
 * (`isValidDispositionEvidence` / `isValidPriorFindingDisposition`) were an
 * ALLOW-LIST that only type-checked KNOWN fields — an extra unknown key slipped
 * through, so an `accepted_suppressed` disposition carrying `targetModule` still
 * passed `isValidFinding` / `isValidReviewerOutput` on the single-slice runner
 * control path (route.ts). The standalone `priorFindingDispositionSchema` was not
 * `.strict()` either, so zod SILENTLY STRIPPED the unknown field rather than
 * rejecting it.
 *
 * These validators must be STRICT: an extra key ⇒ reject, parity with the family
 * zod and the Python outcome-guard. Legal field sets must still pass.
 */

import { describe, expect, it } from "vitest";

import {
  isValidFinding,
  isValidPriorFindingDisposition,
  isValidReviewerOutput,
} from "../src/validate.js";
import type { StepOutput } from "../src/backend.js";
import { priorFindingDispositionSchema } from "../src/realBackend.js";

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
    action: "wont_fix",
    disposition_reason: "r",
  };
}

// The deleted routing/derived fields that must no longer be tolerated on a
// disposition. `targetModule` was the r2/C3 canary; the others (`owningIssue`,
// `missingSurface`, `nextStep`) belonged to the deleted route kinds too.
const DELETED_DISPOSITION_FIELDS = [
  "targetModule",
  "owningIssue",
  "missingSurface",
  "nextStep",
] as const;

describe("#604 r5 E1 — isValidFinding rejects extra keys on the disposition", () => {
  for (const field of DELETED_DISPOSITION_FIELDS) {
    it(`rejects a wont_fix finding whose accepted_suppressed disposition carries the deleted ${field} field`, () => {
      const finding = {
        ...baseFinding(),
        disposition: { ...suppression, [field]: "junk" },
      };
      expect(isValidFinding(finding)).toBe(false);
    });
  }

  it("still accepts a legal accepted_suppressed disposition (whitelisted fields only)", () => {
    const finding = {
      ...baseFinding(),
      disposition: { ...suppression, findingIdentity: "correctness|x|y" },
    };
    expect(isValidFinding(finding)).toBe(true);
  });
});

describe("#604 r5 E1 — isValidReviewerOutput rejects extra keys on the disposition", () => {
  it("rejects a reviewer output whose finding disposition carries a deleted field", () => {
    const output = {
      kind: "reviewer",
      escalate: null,
      findings: [
        {
          ...baseFinding(),
          disposition: { ...suppression, targetModule: "some-module" },
        },
      ],
    } as unknown as StepOutput;
    expect(isValidReviewerOutput(output)).toBe(false);
  });
});

describe("#604 r5 E1 — isValidPriorFindingDisposition rejects extra keys", () => {
  const validPrior = {
    identityKey: "correctness|x|y",
    status: "accepted_suppressed" as const,
    reason: "accepted as outside slice",
    source: "ADR 0030 accepted scope",
    scope: "existing invariant",
    boundedReopen: "reopen if severity escalates or new evidence changes scope",
  };

  for (const field of DELETED_DISPOSITION_FIELDS) {
    it(`rejects a prior-finding disposition carrying the deleted ${field} field`, () => {
      expect(
        isValidPriorFindingDisposition({ ...validPrior, [field]: "junk" }),
      ).toBe(false);
    });
  }

  it("still accepts a legal accepted_suppressed prior-finding disposition", () => {
    expect(isValidPriorFindingDisposition(validPrior)).toBe(true);
  });

  it("still accepts a legal non-suppression prior-finding disposition", () => {
    expect(
      isValidPriorFindingDisposition({
        identityKey: "correctness|x|y",
        status: "still-active",
        reason: "still open",
      }),
    ).toBe(true);
  });
});

describe("#604 r5 E1 — standalone priorFindingDispositionSchema is strict", () => {
  const validPrior = {
    identityKey: "correctness|x|y",
    status: "accepted_suppressed" as const,
    reason: "accepted as outside slice",
    source: "ADR 0030 accepted scope",
    scope: "existing invariant",
    boundedReopen: "reopen if severity escalates or new evidence changes scope",
  };

  for (const field of DELETED_DISPOSITION_FIELDS) {
    it(`rejects (not strips) a prior-finding disposition carrying the deleted ${field} field`, () => {
      const parsed = priorFindingDispositionSchema.safeParse({
        ...validPrior,
        [field]: "junk",
      });
      expect(parsed.success).toBe(false);
    });
  }

  it("still accepts a legal accepted_suppressed prior-finding disposition", () => {
    const parsed = priorFindingDispositionSchema.safeParse(validPrior);
    expect(parsed.success).toBe(true);
  });
});
