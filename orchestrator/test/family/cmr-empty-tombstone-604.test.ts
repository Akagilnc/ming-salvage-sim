/**
 * #604 ship-pre CMR — codexB defect: not_converged empty tombstone masking.
 *
 * A not_converged abort persisted `cmrDispositions: []` (defined-but-empty).
 * `latestFamilyCmrDispositions` returns the FIRST defined array scanning from the
 * end, so that empty tombstone MASKED an earlier round's real accepted-suppression
 * dispositions → the next pass saw NO prior → budget reset (C1-class: same
 * suppression stops being recognized as prior, a fresh dispute/reopen budget is
 * handed out every round via a different entry point).
 *
 * Two-part fix, both locked here:
 *   (A) not_converged aborts must NOT write `cmrDispositions: []` (leave it
 *       undefined so the scan skips the abort row). Verified via the real
 *       ledger-write shape in runner-verify-cmr; here we lock the read side.
 *   (B) `latestFamilyCmrDispositions` skips defined-but-EMPTY arrays so a stray
 *       `[]` tombstone can never re-introduce the masking through another entry.
 */

import { describe, expect, it } from "vitest";

import { latestFamilyCmrDispositions } from "../../src/family/verifyCmr.js";
import type { FindingDisposition } from "../../src/types.js";

const realDisposition: FindingDisposition = {
  identityKey: "correctness|src/x.ts:1|claim",
  status: "accepted_suppressed",
  reason: "accepted by family issue scope",
  severity: "medium",
  reopenAttempts: 0,
  disputeAttempts: 0,
  source: "issue #604 acceptance criteria",
  scope: "#604 family integrated CMR",
  boundedReopen: "reopen on higher severity or different scope",
};

describe("#604 latestFamilyCmrDispositions — empty tombstone must not mask prior", () => {
  it("returns undefined when no entry carries dispositions", () => {
    expect(
      latestFamilyCmrDispositions([{}, { reason: "x" } as never]),
    ).toBeUndefined();
  });

  it("returns the real dispositions from an earlier round", () => {
    expect(
      latestFamilyCmrDispositions([
        { cmrDispositions: [realDisposition] },
        {},
      ]),
    ).toEqual([realDisposition]);
  });

  it("an entry WITHOUT cmrDispositions (undefined) after a real round does NOT mask it", () => {
    // The abort-side fix (A): a not_converged abort omits cmrDispositions, so the
    // scan skips it and finds the earlier real dispositions.
    expect(
      latestFamilyCmrDispositions([
        { cmrDispositions: [realDisposition] },
        {}, // not_converged abort row, no cmrDispositions field
      ]),
    ).toEqual([realDisposition]);
  });

  it("a defined-but-EMPTY cmrDispositions tombstone does NOT mask an earlier real round (fix B)", () => {
    // Even if some path writes `cmrDispositions: []`, the read must skip the empty
    // tombstone and surface the earlier real accepted-suppression dispositions so
    // budget tracking survives across rounds (C1-recurrence prevention).
    expect(
      latestFamilyCmrDispositions([
        { cmrDispositions: [realDisposition] },
        { cmrDispositions: [] }, // stray empty tombstone
      ]),
    ).toEqual([realDisposition]);
  });

  it("a non-empty later round overrides an earlier one (latest non-empty wins)", () => {
    const later: FindingDisposition = {
      ...realDisposition,
      reopenAttempts: 2,
    };
    expect(
      latestFamilyCmrDispositions([
        { cmrDispositions: [realDisposition] },
        { cmrDispositions: [later] },
      ]),
    ).toEqual([later]);
  });
});
