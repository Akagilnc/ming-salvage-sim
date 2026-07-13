import { describe, expect, it } from "vitest";
import {
  providerDegradedStopSummary,
  stopReasonForFindingDisposition,
  stopSummaryFromFindingDispositionEvidence,
  successStopSummary,
} from "../../src/stopSummary.js";
import type { Finding, FindingDispositionEvidence } from "../../src/types.js";

const FINDING: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "thing is still broken",
  location: "src/x.ts:1",
  suggested_fix: "fix it",
  action: "fix_now",
};

describe("stop summary vocabulary (#450)", () => {
  // #604 correctness r2 (C4) / ADR 0062: the routing disposition kinds
  // (owning_issue_still_red / cross_module / spec_conflict / infra_failure) were
  // removed from the reviewer contract, so the only live input kind is
  // `same_module` (verifyCmr.ts). The dead-branch cases are gone with the code.
  it("maps the same-module finding disposition into the canonical stop reason", () => {
    expect(
      stopReasonForFindingDisposition({ kind: "same_module", finding: FINDING }),
    ).toMatchObject({ reason: "same_module_still_red" });
    expect(
      stopReasonForFindingDisposition({
        kind: "same_module",
        finding: FINDING,
        reason: "same-module blocker still red after fix",
      }),
    ).toMatchObject({
      reason: "same_module_still_red",
      summary: "same-module blocker still red after fix",
    });
  });

  it("keeps accepted suppressions on a success summary with bounded reopen metadata", () => {
    const summary = successStopSummary({
      acceptedSuppressions: [
        {
          source: "owner comment",
          scope: "issue #450",
          reason: "accepted as out of scope",
          findingIdentity: "correctness:src/x.ts:1",
          boundedReopen: "reopen if it appears in the same module again",
        },
      ],
    });

    expect(summary).toMatchObject({
      reason: "success",
      metadata: {
        acceptedSuppressions: [
          {
            source: "owner comment",
            scope: "issue #450",
            findingIdentity: "correctness:src/x.ts:1",
            boundedReopen: "reopen if it appears in the same module again",
          },
        ],
      },
    });
  });

  it("maps provider degradation to success metadata or a blocking stop reason", () => {
    expect(
      providerDegradedStopSummary({
        provider: "agy",
        leg: "agy",
        reason: "quota unavailable",
        blocking: false,
      }),
    ).toMatchObject({
      reason: "success",
      metadata: {
        providerDegraded: [
          {
            provider: "agy",
            leg: "agy",
            reason: "quota unavailable",
            blocking: false,
          },
        ],
      },
    });

    expect(
      providerDegradedStopSummary({
        provider: "agy",
        leg: "agy",
        reason: "quota unavailable",
        blocking: true,
      }),
    ).toMatchObject({
      reason: "provider_degraded",
      summary: "quota unavailable",
      repairHint: "restore the required provider leg and rerun",
      metadata: {
        providerDegraded: [
          {
            provider: "agy",
            leg: "agy",
            reason: "quota unavailable",
            blocking: true,
          },
        ],
      },
    });
  });

  it("fails closed instead of inventing unknown metadata for incomplete disposition evidence", () => {
    // #604 slice 4 (ADR 0062): the routing disposition kinds (owning_issue_still_red /
    // cross_module / …) were removed from the reviewer contract, so the only kind
    // this bridge still handles is accepted_suppressed. The incomplete-evidence
    // fail-closed guard for accepted suppression is retained and asserted here;
    // the deleted-kind cases (owningIssue / targetModule throws) are gone with the
    // kinds themselves.
    expect(() =>
      stopSummaryFromFindingDispositionEvidence({
        finding: FINDING,
        evidence: {
          kind: "accepted_suppressed",
          source: null,
          scope: null,
          boundedReopen: null,
          reason: "the owning issue still lacks a surface",
        } as unknown as FindingDispositionEvidence,
      }),
    ).toThrow(/source.*scope.*boundedReopen/i);

    expect(() =>
      stopSummaryFromFindingDispositionEvidence({
        finding: FINDING,
        evidence: {
          kind: "accepted_suppressed",
          reason: "owner accepted this exact bounded finding",
        } as FindingDispositionEvidence,
      }),
    ).toThrow(/source.*scope.*boundedReopen/i);
  });
});
