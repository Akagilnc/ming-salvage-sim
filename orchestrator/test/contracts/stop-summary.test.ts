import { describe, expect, it } from "vitest";
import {
  providerDegradedStopSummary,
  successStopSummary,
} from "../../src/stopSummary.js";

describe("stop summary vocabulary (#450)", () => {
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
