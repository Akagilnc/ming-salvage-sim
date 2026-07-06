/**
 * #604 ship-pre CMR correctness r1 — findings classification defects.
 *
 * P1-c: `isBlockingByDisposition` must return true for EVERY non-suppression
 *   finding that reaches it (defer AND a reopened/disputed wont_fix/rejected that
 *   fell through the accepted-suppression branch). ADR 0062: all non-suppression
 *   active findings are blocking; the `deferred` bucket must be PROVABLY empty.
 *
 * P1-d: a matching accepted suppression that ALSO has a prior sourced suppression
 *   at a LOWER severity is a REOPEN (severity升级), not a fresh re-suppression.
 *   The old code short-circuited to a fresh `dispositionFromFinding` (reopenAttempts
 *   reset to 0), silently re-suppressing the upgraded finding and never spending
 *   the bounded reopen budget.
 */

import { describe, expect, it } from "vitest";

import { classifyFindings } from "../src/findings.js";
import type { Finding, FindingDisposition } from "../src/types.js";

const IDENTITY = "correctness|src/x.ts:1|claim";
const trustedSource = {
  source: "ADR 0030 accepted scope",
  scope: "existing invariant",
  reason: "accepted as outside slice",
  findingIdentity: IDENTITY,
  boundedReopen: "reopen if severity escalates or new evidence changes scope",
};

function finding(
  severity: Finding["severity"],
  action: Finding["action"],
): Finding {
  return {
    severity,
    category: "correctness",
    claim_quote: "claim",
    location: "src/x.ts:1",
    suggested_fix: "fix it",
    action,
    disposition_reason: "r",
    disposition: { kind: "accepted_suppressed", ...trustedSource },
  } as Finding;
}

function priorSuppression(
  severity: Finding["severity"],
  reopenAttempts = 0,
  disputeAttempts = 0,
): FindingDisposition {
  return {
    identityKey: IDENTITY,
    status: "accepted_suppressed",
    // The prior disposition carries the TRUSTED SOURCE's reason (that is what
    // `dispositionFromFinding` persists), so `isSourcedAcceptedSuppression` can
    // recognise it as the same sourced suppression on the next round.
    reason: trustedSource.reason,
    severity,
    reopenAttempts,
    disputeAttempts,
    source: trustedSource.source,
    scope: trustedSource.scope,
    boundedReopen: trustedSource.boundedReopen,
  } as FindingDisposition;
}

describe("#604 r1 P1-c — non-suppression findings never land in deferred", () => {
  it("a reopened wont_fix (suppression失配, medium) is blocking, not deferred", () => {
    // 失配: the finding claims accepted_suppressed but no trusted source matches.
    const c = classifyFindings([finding("medium", "wont_fix")], [], {
      acceptedSuppressionSources: [],
    });
    expect(c.deferred).toEqual([]);
    expect(c.blocking).toHaveLength(1);
  });

  it("a medium defer is blocking, deferred stays empty", () => {
    const c = classifyFindings([finding("medium", "defer")], [], {});
    expect(c.deferred).toEqual([]);
    expect(c.blocking).toHaveLength(1);
  });
});

describe("#604 r1 P1-d — matching suppression at higher severity reopens, not re-suppresses", () => {
  it("prior low suppression + now medium wont_fix (upgrade) → reopen (reopenAttempts spent, severity升级) AND blocks", () => {
    const c = classifyFindings(
      [finding("medium", "wont_fix")],
      [priorSuppression("low", 0)],
      { acceptedSuppressionSources: [trustedSource] },
    );
    // The disposition must be a REOPEN of the prior, not a fresh re-suppression:
    // reopenAttempts incremented (0 → 1), severity carried up to medium.
    expect(c.dispositions).toHaveLength(1);
    expect(c.dispositions[0]?.reopenAttempts).toBe(1);
    expect(c.dispositions[0]?.severity).toBe("medium");
    // #604 rework (fix silent-drop): the upgraded finding must BLOCK — the old
    // upgrade subpath recorded a reopen then `continue`d without ever blocking.
    expect(c.blocking).toHaveLength(1);
    expect(c.deferred).toEqual([]);
  });

  it("same-severity wont_fix maintenance keeps the suppression AS-IS — no dispute spent (ADR 0030)", () => {
    // #604 rework per ADR 0030 (user定论 2026-07-06): a same-severity wont_fix
    // re-submission MAINTAINS an existing suppression — it is a ZERO-OP on the
    // disposition (no dispute budget spent, prior kept as-is, stays suppressed).
    // The earlier "counts a dispute (disputeAttempts→1)" assertion encoded the
    // non-ratified "维持花预算" drift that r1 P1-d introduced (not on main); it
    // violated ADR 0030 and is rolled back. Only a real fix_now challenge (the
    // general branch) spends the single bounded dispute (#369 PRESERVED).
    const c = classifyFindings(
      [finding("medium", "wont_fix")],
      [priorSuppression("medium", 0, 0)],
      { acceptedSuppressionSources: [trustedSource] },
    );
    expect(c.blocking).toEqual([]);
    expect(c.dispositions).toHaveLength(1);
    expect(c.dispositions[0]?.disputeAttempts ?? 0).toBe(0);
    expect(c.deferred).toEqual([]);
  });

  it("a fresh matching suppression (no prior) still suppresses cleanly at reopenAttempts 0", () => {
    const c = classifyFindings([finding("medium", "wont_fix")], [], {
      acceptedSuppressionSources: [trustedSource],
    });
    expect(c.blocking).toEqual([]);
    expect(c.deferred).toEqual([]);
    expect(c.dispositions).toHaveLength(1);
    expect(c.dispositions[0]?.reopenAttempts).toBe(0);
  });
});
