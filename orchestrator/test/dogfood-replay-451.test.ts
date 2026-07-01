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
          classification: "success",
          stopReason: "success",
          source: "runner",
          sourceStopSummary: expect.objectContaining({ reason: "success" }),
        }),
        expect.objectContaining({
          id: "307-no-observable-progress",
          issue: 307,
          classification: "same_module_still_red",
          stopReason: "same_module_still_red",
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
          stopReason: "success",
          metadata: expect.objectContaining({
            acceptedSuppressions: [
              expect.objectContaining({
                source: "#303",
                scope: expect.stringContaining("#287 hub-loss / central C_ accounts"),
              }),
            ],
          }),
        }),
        expect.objectContaining({
          id: "376-provider-degraded-nonblocking",
          issue: 376,
          classification: "provider_degraded",
          stopReason: "success",
          metadata: expect.objectContaining({
            providerDegraded: [
              expect.objectContaining({
                provider: "agy",
                leg: "agy",
                blocking: false,
              }),
            ],
          }),
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
              latestVerifiedCmrHead: "family-head",
              currentFamilyHead: "family-head",
              shipPrState: "not-written",
            }),
            heads: expect.objectContaining({
              verifiedCmrHead: "family-head",
              actualFamilyHead: "family-head",
            }),
          },
        }),
        expect.objectContaining({
          id: "family-admission-non-runnable-child",
          issue: 451,
          classification: "success",
          stopReason: "success",
          metadata: expect.objectContaining({
            admissionSkipped: [
              expect.objectContaining({
                issue: 451,
                reason: "missing-ready-for-agent",
              }),
            ],
          }),
          sourceStopSummary: expect.objectContaining({
            reason: "success",
            metadata: expect.objectContaining({
              admissionSkipped: [
                expect.objectContaining({
                  issue: 451,
                  reason: "missing-ready-for-agent",
                }),
              ],
            }),
          }),
          sourceEvidence: expect.objectContaining({
            seam: "family",
            mechanism: "admission_skip_summary",
          }),
        }),
        expect.objectContaining({
          id: "family-resume-already-done-child",
          issue: 451,
          classification: "already_done",
          stopReason: "already_done",
          source: "family",
          sourceStopSummary: expect.objectContaining({
            reason: "already_done",
            metadata: expect.objectContaining({
              alreadyDone: [
                expect.objectContaining({
                  issue: 451,
                  status: "merged",
                }),
              ],
            }),
          }),
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
      "already_done",
      "contract_drift",
      "cross_module_defer",
      "infra_failure",
      "owning_issue_still_red",
      "provider_degraded",
      "same_module_still_red",
      "spec_conflict",
      "success",
    ]);
    expect(replay.summary).toContain("9 stop reasons");
  });

  it("uses seam-produced stop summaries for replay rows that claim success or already-done", async () => {
    const replay = await issue451DogfoodReplay();
    const rowsById = new Map(replay.scenarios.map((scenario) => [scenario.id, scenario]));

    for (const id of [
      "307-continue-fixing-after-human-answer",
      "307-local-progress-shape-changed",
    ]) {
      const row = rowsById.get(id);
      expect(row, id).toBeDefined();
      expect(row?.source, id).toBe("runner");
      expect(row?.sourceStopSummary, id).toMatchObject({ reason: "success" });
      expect(row?.sourceEvidence, id).toMatchObject({
        seam: "runner",
        status: "success",
        dispatched: expect.arrayContaining(["S5:coder", "S6:reviewer", "S7:ship"]),
      });
    }
    expect(rowsById.get("307-continue-fixing-targeted-reset")).toMatchObject({
      source: "runner",
      classification: "same_module_still_red",
      stopReason: "same_module_still_red",
      sourceStopSummary: expect.objectContaining({ reason: "same_module_still_red" }),
      sourceEvidence: expect.objectContaining({
        seam: "runner",
        status: "escalate",
      }),
    });

    for (const id of [
      "287-module-declaration-fenced-yaml",
      "287-family-attribution-child-before-parent",
      "287-correctness-r3-legacy-disposition",
      "287-correctness-final-legacy-disposition",
      "287-stale-family-head-current-cmr-pass",
      "376-route-accounting-non-default",
      "376-route-freeze-after-import",
      "376-closure-context-positive",
    ]) {
      const row = rowsById.get(id);
      expect(row, id).toBeDefined();
      expect(row?.source, id).not.toBe("stop_summary");
      expect(row?.sourceStopSummary, id).toBeDefined();
      expect(row?.stopSummary, id).toEqual(row?.sourceStopSummary);
      expect(row?.sourceEvidence, id).toBeDefined();
    }

    expect(rowsById.get("family-resume-already-done-child")).toMatchObject({
      source: "family",
      sourceStopSummary: {
        reason: "already_done",
        metadata: {
          alreadyDone: [
            expect.objectContaining({
              issue: 451,
              status: "merged",
            }),
          ],
          heads: expect.objectContaining({
            actualFamilyHead: "family-done-head",
          }),
        },
      },
      sourceEvidence: expect.objectContaining({
        seam: "family",
        mechanism: "already_done_child_resume",
        skippedChildIssue: 451,
        childDispatches: [],
      }),
    });
  });

  it("does not count static stop-summary rows as dogfood replay coverage", async () => {
    const replay = await issue451DogfoodReplay();

    for (const row of replay.scenarios) {
      expect(row.source, row.id).toBeDefined();
      expect(row.source, row.id).not.toBe("stop_summary");
      expect(row.sourceStopSummary, row.id).toBeDefined();
      expect(row.stopSummary, row.id).toEqual(row.sourceStopSummary);
      expect(row.sourceEvidence, row.id).toBeDefined();
    }
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

  it("does not reuse generic success summaries for rows that name a specific replay seam", async () => {
    const replay = await issue451DogfoodReplay();
    const rowsById = new Map(replay.scenarios.map((scenario) => [scenario.id, scenario]));

    expect(rowsById.get("307-local-progress-shape-changed")?.sourceEvidence).toMatchObject({
      seam: "runner",
      mechanism: "changed_shape_progress",
      findingShape: "changed_after_local_progress",
      implementationMovement: false,
      movementEvidence: "scripted repairEvidence only; no real git worktree movement",
    });
    expect(rowsById.get("307-continue-fixing-targeted-reset")?.sourceEvidence).toMatchObject({
      seam: "runner",
      mechanism: "continue_fixing_bookkeeping",
      resetScope: "single_identity_key",
      preservedSibling: true,
    });
    expect(rowsById.get("307-reviewer-text-only-change")).toMatchObject({
      source: "runner",
      classification: "same_module_still_red",
      stopReason: "same_module_still_red",
      sourceStopSummary: expect.objectContaining({ reason: "same_module_still_red" }),
      sourceEvidence: expect.objectContaining({
        seam: "runner",
        mechanism: "reviewer_text_only_no_progress",
        status: "escalate",
        implementationMovement: false,
      }),
    });
    expect(rowsById.get("307-no-observable-progress")).toMatchObject({
      source: "runner",
      classification: "same_module_still_red",
      stopReason: "same_module_still_red",
      sourceStopSummary: expect.objectContaining({ reason: "same_module_still_red" }),
      sourceEvidence: expect.objectContaining({
        seam: "runner",
        mechanism: "claimed_attempt_without_observable_progress",
        status: "escalate",
        implementationMovement: false,
      }),
    });
    expect(rowsById.get("287-module-declaration-fenced-yaml")?.sourceEvidence).toMatchObject({
      seam: "family_verify_cmr",
      parserSeam: "module_declaration_parser",
      parsedModule: "orchestrator-family",
      undevelopedTargets: ["military-state-machine"],
      proseIgnored: true,
    });
    expect(rowsById.get("287-family-attribution-child-before-parent")?.sourceEvidence).toMatchObject({
      seam: "family_verify_cmr",
      attribution: {
        method: "child_module_scope",
        issue: 307,
        module: "orchestrator-runner",
      },
      dispatches: ["cmr:completeness"],
    });
    expect(rowsById.get("287-correctness-r3-legacy-disposition")?.sourceEvidence).toMatchObject({
      seam: "family_verify_cmr",
      parserSeam: "cmr_outcome_parser",
      normalizedPriorDisposition: "verified-closed",
      dispatches: expect.arrayContaining(["cmr:completeness", "cmr:correctness", "ship:family/287-legacy-disposition"]),
    });
    expect(rowsById.get("287-correctness-final-legacy-disposition")?.sourceEvidence).toMatchObject({
      seam: "family_verify_cmr",
      parserSeam: "cmr_outcome_parser",
      finalCmrPass: "correctness",
      rawLegacyDispositionField: "disposition",
      normalizedPriorDisposition: "verified-closed",
      dispatches: expect.arrayContaining([
        "cmr:completeness",
        "cmr:correctness",
        "ship:family/287-final-legacy-disposition",
      ]),
    });
    expect(rowsById.get("287-known-hub-loss-suppression")).toMatchObject({
      source: "family",
      classification: "accepted_suppressed",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({ reason: "success" }),
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr",
        runStatus: "success",
      }),
    });
    expect(rowsById.get("376-route-accounting-non-default")?.sourceEvidence).toMatchObject({
      seam: "family_verify_cmr",
      helperSeam: "family_cmr_accounting",
      routeName: "claude-tight",
      declaredLegs: ["gpt-5.5", "agy"],
      rejectedDefaultLeg: "opus",
      dispatches: ["cmr:completeness"],
    });
    expect(rowsById.get("376-route-env-format-mismatch")).toMatchObject({
      source: "family",
      classification: "infra_failure",
      stopReason: "infra_failure",
      sourceStopSummary: expect.objectContaining({
        reason: "infra_failure",
        repairHint: expect.stringContaining("route environment"),
      }),
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr_route_env",
        helperSeam: "model_route_cmr_leg_env",
        envShape: "json-written-csv-read",
        status: "aborted",
        dispatches: [],
      }),
    });
    expect(rowsById.get("376-route-freeze-after-import")?.sourceEvidence).toMatchObject({
      seam: "runner",
      mechanism: "route_freeze_after_import",
      routeName: "codex-tight",
      reviewerModel: "opus",
      envMutatedAfterImport: true,
    });
    expect(rowsById.get("376-startup-route-tight-violation")?.sourceEvidence).toMatchObject({
      seam: "runner_startup_route",
      helperSeam: "model_route_startup_policy",
      routeName: "claude-tight",
      violationReason: "tight route violation",
      status: "escalate",
      dispatchedBeforeAbort: [],
    });
    expect(rowsById.get("376-closure-context-positive")?.sourceEvidence).toMatchObject({
      seam: "runner",
      mechanism: "s5_s6_closure_loop",
      status: "success",
      priorFindingStatus: "verified-closed",
      dispatched: expect.arrayContaining(["S5:coder", "S6:reviewer", "S7:ship"]),
    });
    expect(rowsById.get("376-closure-context-negative")).toMatchObject({
      source: "family",
      classification: "contract_drift",
      stopReason: "contract_drift",
      sourceStopSummary: expect.objectContaining({ reason: "contract_drift" }),
      sourceEvidence: expect.objectContaining({
        seam: "family_cmr_closure",
        rejectedStatuses: ["still-active", "unable-to-assess"],
        rejectedShapes: expect.arrayContaining([
          "missing-disposition",
          "stale-self-claimed",
          "duplicate-disposition",
          "extra-stale-disposition",
        ]),
      }),
    });
    expect(rowsById.get("376-accepted-suppression-with-source")).toMatchObject({
      source: "family",
      classification: "accepted_suppressed",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({
        reason: "success",
        metadata: expect.objectContaining({
          acceptedSuppressions: [
            expect.objectContaining({
              source: "#376 owner answer",
              scope: expect.stringContaining("orchestrator route accounting"),
              boundedReopen: expect.stringContaining("scope mismatch"),
            }),
          ],
        }),
      }),
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr_pass_summary",
        mechanism: "accepted_suppressed_success_metadata",
      }),
    });
    expect(rowsById.get("376-provider-degraded-blocking")).toMatchObject({
      source: "family",
      classification: "provider_degraded",
      stopReason: "provider_degraded",
      sourceStopSummary: expect.objectContaining({
        reason: "provider_degraded",
        metadata: expect.objectContaining({
          providerDegraded: [
            expect.objectContaining({
              provider: "agy",
              leg: "agy",
              blocking: true,
            }),
          ],
        }),
      }),
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr_provider_worker_failure",
        failedLeg: "agy",
        status: "aborted",
        dispatches: ["cmr:completeness"],
      }),
    });
    expect(rowsById.get("376-closure-context-missing")).toMatchObject({
      source: "runner",
      classification: "contract_drift",
      stopReason: "contract_drift",
      sourceStopSummary: expect.objectContaining({ reason: "contract_drift" }),
      sourceEvidence: expect.objectContaining({
        seam: "runner",
        mechanism: "s6_missing_prior_context",
        status: "error",
        closureContext: "missing",
      }),
    });
    expect(rowsById.get("440-coder-trust-boundary")).toMatchObject({
      source: "runner",
      classification: "spec_conflict",
      stopReason: "spec_conflict",
      sourceStopSummary: expect.objectContaining({
        reason: "spec_conflict",
        repairHint: expect.stringContaining("repo-owner"),
      }),
      sourceEvidence: expect.objectContaining({
        seam: "source_auth",
        rejectedAuthor: "drive-by",
        trustedAuthor: "Akagilnc",
        executableInstructionSourceAccepted: false,
      }),
    });
  });
});
