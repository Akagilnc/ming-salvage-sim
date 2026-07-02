import { describe, expect, it } from "vitest";
import {
  providerDegradedStopSummary,
  stopReasonForFindingDisposition,
  stopSummaryFromFindingDispositionEvidence,
  successStopSummary,
} from "../src/stopSummary.js";
import type { Finding, FindingDispositionEvidence } from "../src/types.js";

const FINDING: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "thing is still broken",
  location: "src/x.ts:1",
  suggested_fix: "fix it",
  action: "fix_now",
};

describe("stop summary vocabulary (#450)", () => {
  it("maps per-finding dispositions into the canonical run-level stop reason vocabulary", () => {
    expect(stopReasonForFindingDisposition({ kind: "same_module", finding: FINDING }))
      .toMatchObject({ reason: "same_module_still_red" });
    expect(
      stopReasonForFindingDisposition({
        kind: "owning_issue_still_red",
        finding: FINDING,
        owningIssue: "#446",
      }),
    ).toMatchObject({ reason: "owning_issue_still_red", owningIssue: "#446" });
    expect(
      stopReasonForFindingDisposition({
        kind: "cross_module",
        finding: FINDING,
        targetModule: "family-cmr",
        reason: "belongs to the integrated gate",
      }),
    ).toMatchObject({
      reason: "cross_module_defer",
      targetModule: "family-cmr",
    });
    expect(
      stopReasonForFindingDisposition({
        kind: "spec_conflict",
        finding: FINDING,
        reason: "issue contradicts itself",
      }),
    ).toMatchObject({ reason: "spec_conflict" });
    expect(
      stopReasonForFindingDisposition({
        kind: "infra_failure",
        finding: FINDING,
        reason: "git failed",
        repairHint: "repair git auth and retry",
      }),
    ).toMatchObject({
      reason: "infra_failure",
      repairHint: "repair git auth and retry",
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
    expect(() =>
      stopSummaryFromFindingDispositionEvidence({
        finding: FINDING,
        evidence: {
          kind: "owning_issue_still_red",
          owningIssue: null,
          reason: "the owning issue still lacks a surface",
        } as unknown as FindingDispositionEvidence,
      }),
    ).toThrow(/owningIssue/i);

    expect(() =>
      stopSummaryFromFindingDispositionEvidence({
        finding: FINDING,
        evidence: {
          kind: "cross_module",
          targetModule: null,
          reason: "belongs elsewhere",
        } as unknown as FindingDispositionEvidence,
      }),
    ).toThrow(/targetModule/i);

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
          kind: "cross_module",
          reason: "belongs elsewhere",
        } as FindingDispositionEvidence,
      }),
    ).toThrow(/targetModule/i);

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
