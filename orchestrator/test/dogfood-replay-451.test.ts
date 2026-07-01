import { describe, expect, it } from "vitest";

import { issue451DogfoodReplay } from "../src/dogfoodReplay.js";

describe("#451 dogfood replay fixture", () => {
  it("summarizes the historical orchestrator regressions through the runner/family seams", async () => {
    const replay = await issue451DogfoodReplay();

    expect(replay.issue).toBe(451);
    expect(replay.parentIssue).toBe(445);
    expect(replay.scenarios).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: "307-continue-fixing-after-human-answer",
          issue: 307,
          classification: "resumed",
          stopReason: "resumed",
          source: "runner",
          sourceStopSummary: expect.objectContaining({ reason: "success" }),
        }),
        expect.objectContaining({
          id: "307-no-observable-progress",
          issue: 307,
          classification: "spec_conflict",
          stopReason: "spec_conflict",
        }),
        expect.objectContaining({
          id: "287-same-module-cmr-gap",
          issue: 287,
          classification: "same_module_still_red",
          stopReason: "same_module_still_red",
        }),
        expect.objectContaining({
          id: "287-cross-module-defer-with-module",
          issue: 287,
          classification: "cross_module_defer",
          stopReason: "cross_module_defer",
        }),
        expect.objectContaining({
          id: "287-known-hub-loss-suppression",
          issue: 287,
          classification: "accepted_suppressed",
          stopReason: "accepted_suppressed",
          metadata: {
            acceptedSuppressions: [
              expect.objectContaining({
                source: "#303",
                scope: expect.stringContaining("#287 hub-loss / central C_ accounts"),
              }),
            ],
          },
        }),
        expect.objectContaining({
          id: "376-provider-degraded-nonblocking",
          issue: 376,
          classification: "provider_degraded",
          stopReason: "success",
          metadata: {
            providerDegraded: [
              expect.objectContaining({
                provider: "agy",
                leg: "agy-tight",
                blocking: false,
              }),
            ],
          },
        }),
        expect.objectContaining({
          id: "440-agent-brief-spec-conflict",
          issue: 440,
          classification: "spec_conflict",
          stopReason: "spec_conflict",
        }),
        expect.objectContaining({
          id: "440-module-not-found",
          issue: 440,
          classification: "infra_failure",
          stopReason: "infra_failure",
        }),
        expect.objectContaining({
          id: "405-ship-worker-malformed-after-final-cmr",
          issue: 405,
          classification: "contract_drift",
          stopReason: "contract_drift",
          metadata: {
            ship: expect.objectContaining({
              latestVerifiedCmrHead: "verified-head",
              currentFamilyHead: "family-head",
              shipPrState: "not-written",
            }),
            heads: expect.objectContaining({
              verifiedCmrHead: "verified-head",
              actualFamilyHead: "family-head",
            }),
          },
        }),
        expect.objectContaining({
          id: "family-admission-non-runnable-child",
          issue: 451,
          classification: "owning_issue_still_red",
          stopReason: "owning_issue_still_red",
        }),
        expect.objectContaining({
          id: "family-resume-already-done-child",
          issue: 451,
          classification: "already_done",
          stopReason: "already_done",
          source: "runner",
          sourceStopSummary: expect.objectContaining({ reason: "already_done" }),
        }),
      ]),
    );

    const staleHead = replay.scenarios.find(
      (item) => item.id === "287-stale-family-head-current-cmr-pass",
    );
    expect(staleHead).toMatchObject({
      source: "family",
      metadata: {
        heads: {
          reportedFamilyHead: "+287",
          actualFamilyHead: "f0a72055",
          verifiedCmrHead: "f0a72055",
          sources: {
            reportedFamilyHead: "FamilyRunResult.familyHead",
            actualFamilyHead: "familyBackend.readFamilyHead",
            verifiedCmrHead: "latest cmr_passed ledger row",
          },
        },
      },
    });

    expect(replay.coveredStopReasons).toEqual([
      "accepted_suppressed",
      "already_done",
      "contract_drift",
      "cross_module_defer",
      "infra_failure",
      "owning_issue_still_red",
      "provider_degraded",
      "resumed",
      "same_module_still_red",
      "spec_conflict",
      "success",
    ]);
    expect(replay.summary).toContain("11 stop reasons");
  });

  it("contains a replay row for each owner-specified #451 accident sample", async () => {
    expect((await issue451DogfoodReplay()).scenarios.map((scenario) => scenario.id)).toEqual([
      "307-continue-fixing-after-human-answer",
      "307-local-progress-shape-changed",
      "307-reviewer-text-only-change",
      "307-no-observable-progress",
      "307-continue-fixing-targeted-reset",
      "287-same-module-cmr-gap",
      "287-cross-module-defer-with-module",
      "287-module-declaration-fenced-yaml",
      "287-family-attribution-child-before-parent",
      "287-correctness-r3-legacy-disposition",
      "287-correctness-final-legacy-disposition",
      "287-stale-family-head-current-cmr-pass",
      "287-coordinator-answer-reclassified",
      "287-known-hub-loss-suppression",
      "376-route-accounting-non-default",
      "376-route-env-format-mismatch",
      "376-route-freeze-after-import",
      "376-startup-route-tight-violation",
      "376-closure-context-negative",
      "376-closure-context-missing",
      "376-closure-context-positive",
      "376-owning-issue-still-red",
      "376-accepted-suppression-with-source",
      "376-provider-degraded-nonblocking",
      "376-provider-degraded-blocking",
      "433-provider-leg-skipped-strong-leg-pass",
      "440-agent-brief-spec-conflict",
      "440-module-not-found",
      "440-coder-trust-boundary",
      "440-escalation-answer-invalid",
      "405-ship-worker-malformed-after-final-cmr",
      "405-module-not-found-final-verify",
      "376-ship-side-review-degraded",
      "family-admission-non-runnable-child",
      "family-resume-already-done-child",
    ]);
  });
});
