/**
 * #604 ship-pre CMR correctness r5 (E1) — strict prior-disposition schema.
 *
 * The family CMR zod schemas (`cmrDispositionEvidenceSchema` /
 * `cmrFindingDispositionSchema`) and the standalone reviewer `disposition` schema
 * are `.strict()`, so a disposition carrying a DELETED routing field
 * (`targetModule`, `owningIssue`, `missingSurface`, `nextStep`, …) is REJECTED.
 * The standalone `priorFindingDispositionSchema` must reject rather than strip
 * deleted routing fields.
 */

import { describe, expect, it } from "vitest";

import { priorFindingDispositionSchema } from "../../src/realBackend.js";

const DELETED_DISPOSITION_FIELDS = [
  "targetModule",
  "owningIssue",
  "missingSurface",
  "nextStep",
] as const;

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
