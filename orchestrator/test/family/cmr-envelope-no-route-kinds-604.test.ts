import { describe, expect, it } from "vitest";

import { classifyFamilyCmrFindings } from "../../src/family/cmrClassification.js";
import { buildFamilyModuleContext } from "../../src/family/moduleDeclaration.js";
import { classifyFindings } from "../../src/findings.js";
import type { Finding } from "../../src/types.js";

/**
 * #604 slice 4 (ADR 0062): reviewer/CMR souls no longer emit routing
 * disposition kinds (`same_module` / `cross_module` / `spec_conflict` /
 * `infra_failure` / `owning_issue_still_red`). A reviewer finding now carries
 * only body + `action` (+ an optional accepted-suppression governance
 * disposition). The runner treats EVERY non-accepted-suppressed finding as
 * blocking and sends it to coder-fix; there is no route-kind bucketing and no
 * cross-module deferred bucket.
 *
 * BEFORE slice 4 these findings carry a `cross_module` disposition that routes
 * them into the DEFERRED bucket (`classification: "cross_module_defer"`). After
 * slice 4 the route kinds are gone, so the very same input — now shaped without
 * a route kind — is BLOCKING. The `cross_module` fixtures below are cast so the
 * test compiles under the pre-slice-4 type while asserting the post-slice-4
 * runtime semantics (RED before, GREEN after).
 */
describe("#604 slice 4 — route-kind-less findings are blocking, deferred is empty", () => {
  const familyModuleContext = buildFamilyModuleContext({
    childModules: [],
    familyModule: {
      module: "orchestrator-family",
      moduleScope: ["orchestrator/src/family"],
      source: "family_issue",
      issue: 604,
    },
    // A separately-declared undeveloped module the old code would defer INTO.
    undevelopedModules: [
      {
        module: "fiscal-reports",
        moduleScope: ["docs/fiscal-reports"],
        source: "run_option",
      },
    ],
  });

  it("classifyFamilyCmrFindings sends a would-be cross_module defer to blocking, not deferred", () => {
    const finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "the report surface belongs to a separate undeveloped module",
      location: "docs/fiscal-reports/summary.md:12",
      suggested_fix: "implement the report surface",
      action: "defer",
      disposition: {
        // Pre-slice-4 this routes to the deferred bucket; slice 4 removes the kind.
        kind: "cross_module",
        targetModule: "fiscal-reports",
        reason: "claimed as outside the current module",
      },
    } as unknown as Finding;

    const classified = classifyFamilyCmrFindings({
      familyIssue: 604,
      findings: [finding],
      moduleContext: familyModuleContext,
    });

    // NEW semantics: no cross-module deferral survives — it is blocking.
    expect(classified.blocking).toEqual([finding]);
    expect(classified.deferred).toEqual([]);
  });

  it("single-slice classifyFindings sends a would-be cross_module defer to blocking", () => {
    const finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "same claim",
      location: "orchestrator/src/runner.ts:10",
      suggested_fix: "fix it",
      action: "defer",
      disposition: {
        kind: "cross_module",
        targetModule: "some-other-module",
        reason: "claimed cross module",
      },
    } as unknown as Finding;

    const classified = classifyFindings([finding]);
    expect(classified.blocking).toEqual([finding]);
    expect(classified.deferred).toEqual([]);
  });

  it("a bare fix_now finding with no disposition is blocking", () => {
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "guard is missing on the settle path",
      location: "orchestrator/src/family/verifyCmr.ts:42",
      suggested_fix: "add the missing guard",
      action: "fix_now",
    };

    const classified = classifyFamilyCmrFindings({
      familyIssue: 604,
      findings: [finding],
      moduleContext: familyModuleContext,
    });

    expect(classified.blocking).toEqual([finding]);
    expect(classified.deferred).toEqual([]);
  });
});
