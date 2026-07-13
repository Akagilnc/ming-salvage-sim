/**
 * #604 rework — reopen/dispute state machine per ADR 0030 (user定论 2026-07-06).
 *
 * Constitution PRESERVED: #369 bounded-dispute + the general fix_now branch
 * (same-severity fix_now blocks once + spends the single dispute budget; once the
 * budget is exhausted a repeat is re-suppressed / stands). ADR 0030 restored on
 * the disposition-action (wont_fix/rejected) branch:
 *
 *   - MAINTAIN (matched suppression, prior exists, same/lower severity, a
 *     maintenance action wont_fix/rejected) → ZERO-OP on the disposition: spend
 *     no disputeAttempts, do not refresh severity, do not reset budgets; keep the
 *     prior exactly as-is and stay suppressed. Maintaining a suppression NEVER
 *     rewrites governance state.
 *   - UPGRADE (matched, prior exists, severity升级) → record reopen AND BLOCK
 *     (both budget-available and budget-exhausted subcases block — fixes the
 *     silent-drop where the old upgrade subpath recorded a reopen then continued
 *     without ever blocking).
 *   - DOWNGRADE maintain → keep prior AS-IS, do NOT刷回 to the lower severity /
 *     reset budgets (ADR 0030 "降级…不刷回").
 *
 * The "维持花预算" behavior (same-severity wont_fix spending a dispute) that r1
 * P1-d introduced is a NON-ratified implementation semantic that violates ADR
 * 0030 — this rework rolls it back. The general fix_now branch is untouched.
 */

import { describe, expect, it } from "vitest";

import { classifyFindings } from "../../src/findings.js";
import { isValidFinding } from "../../src/validate.js";
import type { Finding, FindingDisposition } from "../../src/types.js";

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
    reason: trustedSource.reason,
    severity,
    reopenAttempts,
    disputeAttempts,
    source: trustedSource.source,
    scope: trustedSource.scope,
    boundedReopen: trustedSource.boundedReopen,
  } as FindingDisposition;
}

describe("#604 ADR 0030 — maintain spends no budget (①)", () => {
  it("same-severity wont_fix maintenance keeps disputeAttempts at 0 and stays suppressed", () => {
    const c = classifyFindings([finding("medium", "wont_fix")], [
      priorSuppression("medium", 0, 0),
    ], { acceptedSuppressionSources: [trustedSource] });
    expect(c.blocking).toEqual([]);
    expect(c.dispositions).toHaveLength(1);
    // MAINTAIN = zero-op: no dispute spent, prior kept as-is.
    expect(c.dispositions[0]?.disputeAttempts ?? 0).toBe(0);
    expect(c.dispositions[0]?.severity).toBe("medium");
    expect(c.dispositions[0]?.reopenAttempts).toBe(0);
  });

  it("same-severity rejected maintenance also spends no budget", () => {
    const c = classifyFindings([finding("medium", "rejected")], [
      priorSuppression("medium", 0, 0),
    ], { acceptedSuppressionSources: [trustedSource] });
    expect(c.blocking).toEqual([]);
    expect(c.dispositions[0]?.disputeAttempts ?? 0).toBe(0);
  });

  it("maintenance does not touch an already-spent prior budget", () => {
    // prior already recorded a dispute (disputeAttempts 1) and 2 reopens; a
    // same-severity wont_fix maintenance must leave BOTH untouched.
    const c = classifyFindings([finding("medium", "wont_fix")], [
      priorSuppression("medium", 2, 1),
    ], { acceptedSuppressionSources: [trustedSource] });
    expect(c.blocking).toEqual([]);
    expect(c.dispositions[0]?.disputeAttempts).toBe(1);
    expect(c.dispositions[0]?.reopenAttempts).toBe(2);
  });

  // #604 correctness r4 (D4): the bf0fcfc6 "HIGH/CRITICAL same-severity
  // maintenance is zero-op" cases were REMOVED — they tested a
  // PRODUCTION-UNREACHABLE payload. The upstream validate.ts / zod / Python
  // guards reject `severity ∈ {critical,high}` unless `action === "fix_now"`, and
  // an `accepted_suppressed` disposition is valid only on wont_fix/rejected, so a
  // high/critical finding can NEVER be validly suppressed nor take a
  // wont_fix/rejected maintenance action. `finding("high","wont_fix")` bypasses
  // that gate by calling `classifyFindings` directly; asserting a zero-op for it
  // pinned behavior for a shape the system can never produce. The real invariant
  // is the positive one below (fresh high/crit blocks; upgrade-to-high blocks
  // with a recorded reopen), which holds under the reverted `!isBlockingFinding`
  // guard.
  it("HIGH wont_fix with a MATCHING suppression but NO prior still BLOCKS (fresh high cannot self-waive)", () => {
    // guard fix must NOT let a first-seen high suppression self-suppress: with no
    // prior disposition it falls through to the general blocking path.
    const c = classifyFindings([finding("high", "wont_fix")], [], {
      acceptedSuppressionSources: [trustedSource],
    });
    expect(c.blocking).toHaveLength(1);
  });

  it("HIGH wont_fix upgrading a prior MEDIUM suppression → reopen recorded AND blocks", () => {
    const c = classifyFindings([finding("high", "wont_fix")], [
      priorSuppression("medium", 0, 0),
    ], { acceptedSuppressionSources: [trustedSource] });
    expect(c.blocking).toHaveLength(1);
    expect(c.dispositions[0]?.reopenAttempts).toBe(1);
    expect(c.dispositions[0]?.severity).toBe("high");
  });

  // #604 correctness r4 (D4): the invariant that makes a high/critical
  // maintenance action production-unreachable — the upstream finding validator
  // rejects `severity ∈ {critical,high}` unless `action === "fix_now"`. This is
  // WHY the bf0fcfc6 `|| priorSuppression !== undefined` widening was dead code.
  it("upstream validator rejects high/critical findings that are not fix_now (unreachable maintenance shape)", () => {
    expect(isValidFinding(finding("high", "wont_fix"))).toBe(false);
    expect(isValidFinding(finding("critical", "rejected"))).toBe(false);
    // A high/critical finding is only valid as fix_now (which is BLOCKING, so it
    // never enters the disposition-action maintenance branch).
    const highFixNow: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "claim",
      location: "src/x.ts:1",
      suggested_fix: "fix it",
      action: "fix_now",
    };
    expect(isValidFinding(highFixNow)).toBe(true);
  });
});

describe("#604 general fix_now branch PRESERVED — #369 bounded dispute (②③)", () => {
  it("② after maintenance, a real fix_now challenge still blocks once and spends the dispute", () => {
    // Maintenance left the prior at disputeAttempts 0; a fix_now same-severity
    // challenge then blocks and spends the single dispute (general branch).
    const maintained = priorSuppression("medium", 0, 0);
    const c = classifyFindings([finding("medium", "fix_now")], [maintained], {
      acceptedSuppressionSources: [trustedSource],
    });
    expect(c.blocking).toHaveLength(1);
    expect(c.dispositions[0]?.disputeAttempts).toBe(1);
  });

  it("③ after one dispute spent, repeat fix_now still blocks for human (no silent re-suppress)", () => {
    // Owner 2026-07-13: 意见统一不了 → 上升裁决, not "budget exhausted → stay suppressed".
    const c = classifyFindings([finding("medium", "fix_now")], [
      priorSuppression("medium", 0, 1),
    ], { acceptedSuppressionSources: [trustedSource] });
    expect(c.blocking).toHaveLength(1);
    expect(c.dispositions[0]?.disputeAttempts).toBe(1);
  });
});

describe("#604 ADR 0030 — downgrade maintain does not刷回 (④)", () => {
  it("prior medium + low wont_fix maintenance keeps the prior AS-IS (no reset to low / budget 0)", () => {
    const prior = priorSuppression("medium", 2, 1);
    const c = classifyFindings([finding("low", "wont_fix")], [prior], {
      acceptedSuppressionSources: [trustedSource],
    });
    expect(c.blocking).toEqual([]);
    expect(c.dispositions).toHaveLength(1);
    // The prior is preserved exactly — NOT刷回 to low / reopenAttempts 0.
    expect(c.dispositions[0]?.severity).toBe("medium");
    expect(c.dispositions[0]?.reopenAttempts).toBe(2);
    expect(c.dispositions[0]?.disputeAttempts).toBe(1);
  });
});

describe("#604 fix silent-drop — upgrade path blocks (⑤⑥)", () => {
  it("⑤ upgrade with budget available → reopen recorded AND blocks", () => {
    const c = classifyFindings([finding("medium", "wont_fix")], [
      priorSuppression("low", 0),
    ], { acceptedSuppressionSources: [trustedSource] });
    expect(c.blocking).toHaveLength(1);
    expect(c.dispositions).toHaveLength(1);
    expect(c.dispositions[0]?.reopenAttempts).toBe(1);
    expect(c.dispositions[0]?.severity).toBe("medium");
  });

  it("⑥ upgrade with many prior reopens → still reopens + blocks (no cap court)", () => {
    const c = classifyFindings([finding("medium", "wont_fix")], [
      priorSuppression("low", 4),
    ], { acceptedSuppressionSources: [trustedSource] });
    expect(c.blocking).toHaveLength(1);
    expect(c.deferred).toEqual([]);
    // no MAX_REOPEN_ATTEMPTS — counter only for ledger, always reopens
    expect(c.dispositions[0]?.reopenAttempts).toBe(5);
  });
});
