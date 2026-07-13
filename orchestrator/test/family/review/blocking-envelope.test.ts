import { describe, expect, it } from "vitest";

import { deriveCmrEnvelope } from "../../../src/family/cmrClassification.js";
import { buildFamilyModuleContext } from "../../../src/family/moduleDeclaration.js";
import { classifyFindings } from "../../../src/findings.js";
import type { Finding } from "../../../src/types.js";

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

  it("deriveCmrEnvelope sends a would-be cross_module route to blocking, not deferred", () => {
    const finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "the report surface belongs to a separate undeveloped module",
      location: "docs/fiscal-reports/summary.md:12",
      suggested_fix: "implement the report surface",
      action: "fix_now",
      disposition: {
        // Pre-slice-4 this routes to the deferred bucket; slice 4 removes the kind.
        kind: "cross_module",
        targetModule: "fiscal-reports",
        reason: "claimed as outside the current module",
      },
    } as unknown as Finding;

    const classified = deriveCmrEnvelope({
      familyIssue: 604,
      findings: [finding],
      moduleContext: familyModuleContext,
    });

    // NEW semantics: no cross-module deferral survives — it is blocking.
    expect(classified.blocking).toEqual([finding]);
    expect(classified.deferred).toEqual([]);
  });

  it("single-slice classifyFindings sends a would-be cross_module route to blocking", () => {
    const finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "same claim",
      location: "orchestrator/src/runner.ts:10",
      suggested_fix: "fix it",
      action: "fix_now",
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

    const classified = deriveCmrEnvelope({
      familyIssue: 604,
      findings: [finding],
      moduleContext: familyModuleContext,
    });

    expect(classified.blocking).toEqual([finding]);
    expect(classified.deferred).toEqual([]);
  });

  // #604 correctness r1 (P2-c): a blocking finding result's `reason` flows into the
  // ledger stopSummary/findingDescriptor. It MUST stay generic / identity-only —
  // it must NOT leak `suggested_fix` (or other rich finding text) onto the ledger
  // (F5, ADR 0062). The rich content travels only in the live coder-fix landing.
  it("blocking result reason is generic identity-only, never the suggested_fix rich text", () => {
    const finding: Finding = {
      severity: "high",
      category: "correctness",
      claim_quote: "guard is missing on the settle path",
      location: "orchestrator/src/family/verifyCmr.ts:42",
      suggested_fix:
        "SECRET-RICH-DETAIL: rewrite the atomic settle block to hold the applier lock across both writes",
      action: "fix_now",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 604,
      findings: [finding],
      moduleContext: familyModuleContext,
    });

    const result = classified.results.find(
      (r) => r.classification === "blocking",
    );
    expect(result).toBeDefined();
    // The ledger-bound reason must NOT carry the suggested_fix rich text.
    expect(result?.reason).not.toContain("SECRET-RICH-DETAIL");
    expect(result?.reason).not.toBe(finding.suggested_fix);
    // Identity is still recoverable from the thin result.
    expect(result?.identityKey).toBeTruthy();
  });
});
