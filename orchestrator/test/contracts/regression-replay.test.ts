import { describe, expect, it } from "vitest";

import { issue451DogfoodReplay } from "../../src/dogfoodReplay.js";

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
          // #877: no-progress court demolished — ships via findings-count.
          classification: "success",
          stopReason: "success",
        }),
        expect.objectContaining({
          id: "287-same-module-cmr-gap",
          issue: 287,
          classification: "blocking",
          // #922: family CMR stage death is cmr_failed (no same_module_still_red umbrella).
          stopReason: "cmr_failed",
        }),
        expect.objectContaining({
          id: "258-cmr-reviewer-self-fix-attempt",
          issue: 258,
          classification: "success",
          stopReason: "success",
        }),
        expect.objectContaining({
          // #604 slice 4 (ADR 0062): the former "cross-module defer" pass is gone;
          // a declared-target follow-up is now a plain blocking family finding.
          id: "287-declared-target-follow-up-blocking",
          issue: 287,
          classification: "blocking",
          stopReason: "cmr_failed",
        }),
        expect.objectContaining({
          id: "287-known-hub-loss-suppression",
          issue: 287,
          classification: "accepted_suppressed",
          stopReason: "success",
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
          // Dogfood sample still classifies the accident as a product-level
          // spec conflict; #919 CR U2 parks the judge escalate as decision_gate_park
          // (same family as decision_gate — not a third stop token).
          classification: "spec_conflict",
          stopReason: "decision_gate_park",
        }),
        expect.objectContaining({
          id: "440-module-not-found",
          issue: 440,
          classification: "infra_failure",
          // Runner (single-slice) MODULE_NOT_FOUND stays infra_failure; family
          // verify stage death is `405-module-not-found-final-verify` → verify_failed.
          stopReason: "infra_failure",
        }),
        expect.objectContaining({
          id: "405-ship-worker-malformed-after-final-cmr",
          issue: 405,
          classification: "infra_failure",
          // #922: ship stage failure token.
          stopReason: "ship_failed",
          metadata: {
            ship: expect.objectContaining({
              latestVerifiedCmrHead: "family-head",
              currentFamilyHead: "family-head",
              shipPrState: "worker-failed",
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

    // #604 slice 4 (ADR 0062): the `cross_module_defer` and `owning_issue_still_red`
    // stop reasons are no longer produced by any replay scenario.
    // #922: blocking family CMR aborts use `cmr_failed` (stage real name).
    // #877: residual read-word contract_drift courts demolished (disposition /
    // fix-marked echo / no-progress); no dogfood scenario produces contract_drift.
    expect(replay.coveredStopReasons).toEqual([
      "already_done",
      "cmr_failed",
      "decision_gate_park",
      "infra_failure",
      "provider_degraded",
      "ship_failed",
      // Residual invalid-answer / prior-park paths may still surface
      // stopReason "spec_conflict"; live typed judge escalate is decision_gate_park.
      "spec_conflict",
      "success",
      "verify_failed",
    ]);
    // #877: contract_drift no longer covered by dogfood scenarios.
    // #919 CR U2: judge escalate parks as decision_gate_park; classification
    // may still say "spec_conflict".
    expect(replay.summary).toContain("9 stop reasons");
  });

  it("keeps scripted family CMR finding fixtures valid for the real worker parser", async () => {
    const replay = await issue451DogfoodReplay();
    const scriptedCmrFindingScenarioIds = [
      "287-same-module-cmr-gap",
      "287-declared-target-follow-up-blocking",
      "287-module-declaration-fenced-yaml",
      "287-family-attribution-child-before-parent",
      "287-coordinator-answer-reclassified",
      "287-known-hub-loss-suppression",
      "376-owning-issue-still-red",
    ];

    for (const id of scriptedCmrFindingScenarioIds) {
      const scenario = replay.scenarios.find((s) => s.id === id);
      expect(scenario?.sourceEvidence?.cmrWorkerParserValid, id).toBe(true);
    }
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
        dispatched: expect.arrayContaining(["S5:coder", "S6:verify"]),
      });
    }
    expect(rowsById.get("307-continue-fixing-targeted-reset")).toMatchObject({
      source: "runner",
      classification: "success",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({ reason: "success" }),
      sourceEvidence: expect.objectContaining({
        seam: "runner",
        status: "success",
        courtDemolished: true,
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
      "258-cmr-reviewer-self-fix-attempt",
      "287-same-module-cmr-gap",
      "287-declared-target-follow-up-blocking",
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
      movementEvidence: "scripted coder receipts only; no real git worktree movement",
    });
    expect(rowsById.get("307-continue-fixing-targeted-reset")?.sourceEvidence).toMatchObject({
      seam: "runner",
      mechanism: "continue_fixing_bookkeeping",
      resetScope: "single_identity_key",
      preservedSibling: true,
    });
    expect(rowsById.get("307-reviewer-text-only-change")).toMatchObject({
      source: "runner",
      classification: "success",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({ reason: "success" }),
      sourceEvidence: expect.objectContaining({
        seam: "runner",
        mechanism: "reviewer_text_only_no_progress",
        status: "success",
        courtDemolished: true,
        implementationMovement: false,
      }),
    });
    expect(rowsById.get("307-no-observable-progress")).toMatchObject({
      source: "runner",
      classification: "success",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({ reason: "success" }),
      sourceEvidence: expect.objectContaining({
        seam: "runner",
        mechanism: "claimed_attempt_without_observable_progress",
        status: "success",
        courtDemolished: true,
        implementationMovement: false,
      }),
    });
    expect(rowsById.get("258-cmr-reviewer-self-fix-attempt")).toMatchObject({
      source: "family",
      classification: "success",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({
        reason: "success",
      }),
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr",
        mechanism: "cmr_reviewer_head_movement_advisory",
        reviewerSelfFixBlocked: false,
        coderFixDispatched: true,
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
      dispatches: expect.arrayContaining([
        "cmr:completeness",
        "coder:family/287-attribution",
        "cmr:correctness",
        "ship:family/287-attribution",
      ]),
      reviewFixRereviewVisible: true,
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
    expect(rowsById.get("287-same-module-cmr-gap")).toMatchObject({
      source: "family",
      // #604 slice 4 (ADR 0062): the classifier now reports the single `blocking`
      // value; #922 stop summary uses the stage real name `cmr_failed`.
      classification: "blocking",
      stopReason: "cmr_failed",
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr",
        runStatus: "success",
      }),
    });
    expect(rowsById.get("376-route-accounting-non-default")).toMatchObject({
      source: "family",
      classification: "success",
      stopReason: "success",
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr",
        routeName: "claude-tight",
        // #916: claude-tight cmrReview = sol + grok-4.5 + agy(optional)
        declaredLegs: ["gpt-5.6-sol", "grok-4.5", "agy"],
        rejectedDefaultLeg: "opus",
        courtDemolished: true,
        status: "success",
      }),
    });
    expect(rowsById.get("376-route-env-format-mismatch")).toMatchObject({
      source: "family",
      // #936: deleted CMR leg env override is ignored — preset admits (success).
      classification: "success",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({
        reason: "success",
      }),
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr_route_env",
        helperSeam: "model_route_deleted_slot_env_ignored",
        envShape: "ignored-cmr-leg-override",
        status: "ok",
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
      // Pure unit still sees tight violation; public ignition ignores deleted env.
      violationReason: "tight route violation",
    });
    expect(rowsById.get("376-closure-context-positive")?.sourceEvidence).toMatchObject({
      seam: "runner",
      mechanism: "s5_s6_closure_loop",
      status: "success",
      priorFindingStatus: "verified-closed",
      dispatched: expect.arrayContaining(["S2:coder", "S3:verify", "S5:coder", "S6:verify"]),
    });
    expect(rowsById.get("376-closure-context-negative")).toMatchObject({
      source: "family",
      classification: "success",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({ reason: "success" }),
      sourceEvidence: expect.objectContaining({
        seam: "family_cmr_closure",
        courtDemolished: true,
        survivedStatuses: ["still-active", "unable-to-assess"],
        survivedShapes: expect.arrayContaining([
          "missing-disposition",
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
      }),
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr_pass_summary",
        mechanism: "zero_declaration_without_content_classification",
        runnerClassifiedFindingContent: false,
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
        dispatches: ["cmr:completeness", "cmr:completeness", "cmr:completeness"],
      }),
    });
    expect(rowsById.get("376-provider-degraded-nonblocking")).toMatchObject({
      source: "family",
      classification: "provider_degraded",
      stopReason: "success",
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr_provider_metadata",
        familyBase: "family/376-provider",
        status: "success",
      }),
    });
    expect(rowsById.get("433-provider-leg-skipped-strong-leg-pass")).toMatchObject({
      source: "family",
      classification: "provider_degraded",
      stopReason: "success",
      sourceEvidence: expect.objectContaining({
        seam: "family_verify_cmr_provider_metadata",
        familyBase: "family/433-provider",
        status: "success",
      }),
    });
    expect(rowsById.get("376-closure-context-missing")).toMatchObject({
      source: "runner",
      classification: "success",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({ reason: "success" }),
      sourceEvidence: expect.objectContaining({
        seam: "runner",
        mechanism: "s6_missing_prior_context_survives",
        status: "success",
        closureContext: "missing_but_survived",
        courtDemolished: true,
      }),
    });
    expect(rowsById.get("440-coder-trust-boundary")).toMatchObject({
      source: "runner",
      classification: "success",
      stopReason: "success",
      sourceStopSummary: expect.objectContaining({
        reason: "success",
      }),
      // #936: snapshot dual court deleted — host path no longer materializes
      // untrusted comment Agent Briefs; workers live-fetch in-container.
      sourceEvidence: expect.objectContaining({
        seam: "source_auth",
        snapshotDualCourtDeleted: true,
        sourceKind: "live_worker_fetch",
        executableInstructionSourceAccepted: false,
        status: "success",
        dispatched: expect.arrayContaining(["S2:coder", "S3:verify"]),
      }),
    });
  });
});
