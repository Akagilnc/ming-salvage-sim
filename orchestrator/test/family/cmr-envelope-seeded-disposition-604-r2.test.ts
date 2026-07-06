import { describe, expect, it } from "vitest";

import { deriveCmrEnvelope } from "../../src/family/cmrClassification.js";
import { findingIdentityKey } from "../../src/findings.js";
import type { FamilyModuleContext } from "../../src/family/moduleDeclaration.js";
import type { Finding, FindingDisposition } from "../../src/types.js";

/**
 * #604 correctness r2 (C1): `deriveCmrEnvelope` must NOT feed the CURRENT pass's
 * freshly-generated accepted-suppression dispositions back into the FINAL
 * `classifyFindings` call as if they were PRIOR-round dispositions. If it does,
 * a brand-new suppression (no real prior) is treated as a same-severity
 * re-submission against itself → the P1-d reopen/dispute handler fires and burns
 * the single dispute budget on the FIRST suppression, so a later genuine
 * same-severity re-submission is silently re-suppressed with no budget left.
 */

const SUPPRESSED_FINDING: Finding = {
  severity: "medium",
  category: "correctness",
  claim_quote: "hub loss accounts are still unimplemented",
  location: "orchestrator/src/family/verifyCmr.ts:42",
  suggested_fix: "close the family CMR gate instead of deferring same-module work",
  action: "wont_fix",
};

const SOURCE = "#303";
const SCOPE = "fiscal hub-loss finding only";
const REASON = "accepted as #261 hub implementation scope";
const BOUNDED_REOPEN = "reopen on severity escalation, new evidence, or different scope";

function suppressedFinding(): Finding {
  const identity = findingIdentityKey(SUPPRESSED_FINDING);
  return {
    ...SUPPRESSED_FINDING,
    disposition_reason: REASON,
    disposition: {
      kind: "accepted_suppressed",
      source: SOURCE,
      scope: SCOPE,
      reason: REASON,
      findingIdentity: identity,
      boundedReopen: BOUNDED_REOPEN,
    },
  } as unknown as Finding;
}

function moduleContext(): FamilyModuleContext {
  const identity = findingIdentityKey(SUPPRESSED_FINDING);
  return {
    currentModules: [
      {
        module: "fiscal",
        moduleScope: ["orchestrator/src/family"],
        source: "family_issue",
        issue: 604,
      },
    ],
    childModules: [],
    acceptedSuppressionSources: [
      {
        source: SOURCE,
        scope: SCOPE,
        reason: REASON,
        findingIdentity: identity,
        boundedReopen: BOUNDED_REOPEN,
      },
    ],
  };
}

describe("#604 r2 C1 — fresh accepted-suppression does not self-dispute", () => {
  it("a first-time accepted suppression (no real prior) burns NO dispute/reopen budget", () => {
    const finding = suppressedFinding();
    const classified = deriveCmrEnvelope({
      familyIssue: 604,
      findings: [finding],
      moduleContext: moduleContext(),
    });

    expect(classified.blocking).toEqual([]);
    expect(classified.deferred).toEqual([]);
    expect(classified.dispositions).toHaveLength(1);
    const disposition = classified.dispositions[0];
    expect(disposition.status).toBe("accepted_suppressed");
    // The persisted disposition must NOT have consumed a dispute or reopen on
    // its very first suppression — those budgets belong to a genuine
    // same-severity re-submission in a LATER round.
    expect(disposition.disputeAttempts ?? 0).toBe(0);
    expect(disposition.reopenAttempts).toBe(0);
  });

  it("a genuine same-severity re-submission (real prior) DOES spend the dispute budget", () => {
    const finding = suppressedFinding();
    const identity = findingIdentityKey(SUPPRESSED_FINDING);
    // Round 1 produced this persisted disposition (fresh, unspent budgets).
    const priorDispositions: FindingDisposition[] = [
      {
        identityKey: identity,
        status: "accepted_suppressed",
        reason: REASON,
        severity: "medium",
        reopenAttempts: 0,
        source: SOURCE,
        scope: SCOPE,
        boundedReopen: BOUNDED_REOPEN,
      },
    ];

    const classified = deriveCmrEnvelope({
      familyIssue: 604,
      findings: [finding],
      moduleContext: moduleContext(),
      priorDispositions,
    });

    expect(classified.blocking).toEqual([]);
    expect(classified.dispositions).toHaveLength(1);
    // A real same-severity re-submission against a real prior spends the one
    // dispute allowed before suppression resumes.
    expect(classified.dispositions[0].disputeAttempts).toBe(1);
  });
});
