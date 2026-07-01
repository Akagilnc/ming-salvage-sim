import { describe, expect, it } from "vitest";
import {
  providerDegradedStopSummary,
  stopReasonForFindingDisposition,
  successStopSummary,
} from "../src/stopSummary.js";
import type { Finding } from "../src/types.js";

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
});
