import { describe, expect, it } from "vitest";

import { deriveCmrEnvelope } from "../../src/family/cmrClassification.js";
import {
  buildFamilyModuleContext,
  parseModuleDeclaration,
} from "../../src/family/moduleDeclaration.js";
import { findingIdentityKey } from "../../src/findings.js";
import { recordFamilyEscalated } from "../../src/family/ledger.js";
import { parseCmrOutcome } from "../../src/family/realFamilyBackend.js";
import {
  providerDegradedWorkerFailureStopSummary,
  runVerifyCmr,
} from "../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../src/family/types.js";
import type { DispatchContext, Finding, WorkerResult, WorkerSpec } from "../../src/types.js";

const CMR_EVIDENCE = {
  evidencePaths: ["cmr/review-summary.json"],
} as const;

describe("#449 family CMR module declarations", () => {
  it("parses only the structured Module Declaration fenced YAML block", () => {
    expect(
      parseModuleDeclaration(`# fiscal work

This prose says module: fiscal, but prose must not count.

## Module Declaration

\`\`\`yaml
module: fiscal
module_scope:
  - orchestrator/src/family
  - fiscal substrate
\`\`\`
`),
    ).toEqual({
      module: "fiscal",
      moduleScope: ["orchestrator/src/family", "fiscal substrate"],
    });

    expect(parseModuleDeclaration("module: fiscal\nmodule_scope:\n  - prose")).toBeUndefined();
    expect(
      parseModuleDeclaration(`## Module Declaration
\`\`\`yaml
module: fiscal
extra: forbidden
\`\`\`
`),
    ).toBeUndefined();
    expect(
      parseModuleDeclaration(`## Module Declaration
\`\`\`yaml
module: fiscal
module_scope:
  -orchestrator/src/family
\`\`\`
`),
    ).toBeUndefined();
    expect(
      parseModuleDeclaration(`## Module Declaration
\`\`\`yaml
module: fiscal
module_scope:
\`\`\`
`),
    ).toBeUndefined();
    expect(
      parseModuleDeclaration(`## Module Declaration
\`\`\`yaml
module: fiscal
module_scope:
  - orchestrator/src/family
\`\`\`

## Module Declaration
\`\`\`yaml
module: second
module_scope:
  - orchestrator/src/runner.ts
\`\`\`
`),
    ).toBeUndefined();
    expect(
      parseModuleDeclaration(`## Module Declaration

No declaration fence is present in this section.

## Example

\`\`\`yaml
module: unrelated-example
module_scope:
  - docs/example
\`\`\`
`),
    ).toBeUndefined();
  });

  it("preserves hash characters inside quoted module declaration values", () => {
    expect(
      parseModuleDeclaration(`## Module Declaration
\`\`\`yaml
# owner note
module: "#fiscal"
module_scope:
  - "foo#bar"
  - "foo #bar"
  - "foo \\\"bar #baz"
  - orchestrator/src/family # real comment
\`\`\`
`),
    ).toEqual({
      module: "#fiscal",
      moduleScope: [
        "foo#bar",
        "foo #bar",
        'foo \\"bar #baz',
        "orchestrator/src/family",
      ],
    });
  });

  it("allows explanatory prose between the Module Declaration heading and fence", () => {
    expect(
      parseModuleDeclaration(`## Module Declaration

This section is authoritative; prose here is not parsed as YAML.

\`\`\`yaml
module: fiscal
module_scope:
  - orchestrator/src/family
\`\`\`
`),
    ).toEqual({
      module: "fiscal",
      moduleScope: ["orchestrator/src/family"],
    });
  });
});

// #604 slice 4 (ADR 0062): the `cross_module` routing disposition kind was
// removed. The base fixture is now a plain blocking finding (fix_now with no
// disposition) — every non-accepted-suppressed finding is blocking.
const finding: Finding = {
  severity: "medium",
  category: "correctness",
  claim_quote: "hub loss accounts are still unimplemented",
  location: "orchestrator/src/family/verifyCmr.ts:42",
  suggested_fix: "close the family CMR gate instead of deferring same-module work",
  action: "fix_now",
};

describe("#449 family CMR finding classification", () => {
  it("uses child module declarations before the parent fallback and run options", () => {
    expect(
      buildFamilyModuleContext({
        childModules: [
          {
            module: "child-fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "child_issue",
            issue: 449,
          },
        ],
        familyModule: {
          module: "parent-fiscal",
          moduleScope: ["docs/fiscal"],
          source: "family_issue",
          issue: 445,
        },
        runOptionModule: {
          module: "run-option",
          moduleScope: ["fallback"],
          source: "run_option",
        },
      }),
    ).toEqual(
      expect.objectContaining({
        currentModules: [
          {
            module: "child-fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "child_issue",
            issue: 449,
          },
          {
            module: "parent-fiscal",
            moduleScope: ["docs/fiscal"],
            source: "family_issue",
            issue: 445,
          },
        ],
        fallbackModule: {
          module: "parent-fiscal",
          moduleScope: ["docs/fiscal"],
          source: "family_issue",
          issue: 445,
        },
      }),
    );
  });

  it("matches Windows drive-letter finding locations without truncating the path", () => {
    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [
        {
          ...finding,
          location: "C:\\project\\orchestrator\\src\\family\\runner.ts:42",
        },
      ],
      moduleContext: buildFamilyModuleContext({
        childModules: [
          {
            module: "windows-runner",
            moduleScope: ["C:\\project\\orchestrator\\src\\family"],
            source: "child_issue",
            issue: 449,
          },
        ],
      }),
    });

    expect(classified.results[0]?.attribution).toEqual({
      method: "child_module_scope",
      issue: 449,
      module: "windows-runner",
      source: "child_issue",
    });
  });

  it("matches finding locations with trailing line-column-symbol suffixes", () => {
    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [
        {
          ...finding,
          location: "orchestrator/src/family/verifyCmr.ts:42:10:runPass",
        },
      ],
      moduleContext: buildFamilyModuleContext({
        childModules: [
          {
            module: "verify-cmr",
            moduleScope: ["orchestrator/src/family/verifyCmr.ts"],
            source: "child_issue",
            issue: 449,
          },
        ],
      }),
    });

    expect(classified.results[0]?.attribution).toEqual({
      method: "child_module_scope",
      issue: 449,
      module: "verify-cmr",
      source: "child_issue",
    });
  });

  it("matches Windows absolute finding locations with trailing symbol suffixes", () => {
    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [
        {
          ...finding,
          location: "C:\\repo\\orchestrator\\src\\family\\verifyCmr.ts:runPass",
        },
      ],
      moduleContext: buildFamilyModuleContext({
        childModules: [
          {
            module: "verify-cmr",
            moduleScope: ["C:\\repo\\orchestrator\\src\\family\\verifyCmr.ts"],
            source: "child_issue",
            issue: 449,
          },
        ],
      }),
    });

    expect(classified.results[0]?.attribution).toEqual({
      method: "child_module_scope",
      issue: 449,
      module: "verify-cmr",
      source: "child_issue",
    });
  });

  it("keeps the parent module as fallback when child attribution is unavailable", () => {
    const parentScopedFinding: Finding = {
      ...finding,
      location: "docs/fiscal/family-contract.md:12",
    };
    const moduleContext = buildFamilyModuleContext({
      childModules: [
        {
          module: "transport",
          moduleScope: ["orchestrator/src/transport"],
          source: "child_issue",
          issue: 451,
        },
        {
          module: "hub",
          moduleScope: ["orchestrator/src/hub"],
          source: "child_issue",
          issue: 452,
        },
      ],
      familyModule: {
        module: "fiscal",
        moduleScope: ["docs/fiscal"],
        source: "family_issue",
        issue: 445,
      },
    });

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [parentScopedFinding],
      moduleContext,
    });

    expect(classified.blocking).toEqual([parentScopedFinding]);
    expect(classified.deferred).toEqual([]);
    // #604 slice 4 (ADR 0062): result classification collapsed to "blocking"; the
    // family-module attribution + owningIssue fallback logic is retained.
    expect(classified.results[0]).toMatchObject({
      classification: "blocking",
      attribution: { method: "family_module", issue: 445, module: "fiscal" },
      owningIssue: "#445",
    });
  });

  it("matches directory module_scope values that include a trailing slash", () => {
    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [finding],
      moduleContext: buildFamilyModuleContext({
        childModules: [],
        familyModule: {
          module: "orchestrator-family",
          moduleScope: ["orchestrator/src/family/"],
          source: "family_issue",
          issue: 445,
        },
      }),
    });

    expect(classified.blocking).toEqual([finding]);
    expect(classified.deferred).toEqual([]);
    // #604 slice 4 (ADR 0062): result classification collapsed to "blocking"; the
    // trailing-slash module_scope matching is retained.
    expect(classified.results[0]).toMatchObject({
      classification: "blocking",
      attribution: { method: "family_module", issue: 445, module: "orchestrator-family" },
    });
  });

  // #604 slice 4 (ADR 0062): the cross-module-defer PASS outcome (via slug-distinct
  // undeveloped-target matching) is gone. The finding is now blocking; only the
  // attribution/module-context logic is retained, so this asserts the blocking outcome.
  it("treats a slug-like undeveloped target as a blocking finding", () => {
    const fiscalReportsFinding: Finding = {
      ...finding,
      location: "docs/fiscal-reports/summary.md:12",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [fiscalReportsFinding],
      moduleContext: buildFamilyModuleContext({
        childModules: [],
        familyModule: {
          module: "fiscal",
          moduleScope: ["orchestrator/src/fiscal"],
          source: "family_issue",
          issue: 445,
        },
        undevelopedModules: [
          {
            module: "fiscal-reports",
            moduleScope: ["docs/fiscal-reports"],
            source: "run_option",
          },
        ],
      }),
    });

    expect(classified.blocking).toEqual([fiscalReportsFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "blocking",
    });
  });

  // #604 slice 4 (ADR 0062): the undeveloped-module scope-text defer PASS is gone.
  // The finding is now blocking; the module_scope-text attribution logic is retained.
  it("treats an undeveloped module scope-text target as a blocking finding", () => {
    const scopeTargetFinding: Finding = {
      ...finding,
      location: "docs/hub/central-accounts.md:12",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [scopeTargetFinding],
      moduleContext: buildFamilyModuleContext({
        childModules: [],
        familyModule: {
          module: "fiscal",
          moduleScope: ["orchestrator/src/fiscal"],
          source: "family_issue",
          issue: 445,
        },
        undevelopedModules: [
          {
            module: "central-accounts",
            moduleScope: ["docs/hub"],
            source: "run_option",
          },
        ],
      }),
    });

    expect(classified.blocking).toEqual([scopeTargetFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "blocking",
    });
  });

  it("fails closed when the family fallback module scope does not cover the finding location", () => {
    const scopedOutFinding: Finding = {
      ...finding,
      location: "orchestrator/src/family/verifyCmr.ts:42",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [scopedOutFinding],
      moduleContext: buildFamilyModuleContext({
        childModules: [],
        familyModule: {
          module: "fiscal",
          moduleScope: ["docs/fiscal"],
          source: "family_issue",
          issue: 445,
        },
        undevelopedModules: [
          {
            module: "military-state-machine",
            moduleScope: ["docs/military-state-machine.md"],
            source: "family_issue",
            issue: 445,
          },
        ],
      }),
    });

    expect(classified.blocking).toEqual([scopedOutFinding]);
    expect(classified.deferred).toEqual([]);
    // #604 slice 4 (ADR 0062): result classification collapsed to "blocking"; the
    // fail-closed missing-module-context attribution is retained.
    expect(classified.results[0]).toMatchObject({
      classification: "blocking",
      attribution: { method: "missing_module_context" },
    });
  });

  it("blocks when no module declaration establishes the family module", () => {
    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [finding],
      moduleContext: { currentModules: [], childModules: [] },
    });

    expect(classified.blocking).toEqual([finding]);
    expect(classified.deferred).toEqual([]);
    // #604 slice 4 (ADR 0062): result classification collapsed to "blocking".
    expect(classified.results[0]).toMatchObject({
      classification: "blocking",
      attribution: { method: "missing_module_context" },
    });
  });

  it("fails closed when child attribution is ambiguous and no explicit family fallback exists", () => {
    const unownedFinding: Finding = {
      ...finding,
      claim_quote: "military state machine is not implemented",
      location: "docs/military-state-machine.md:1",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [unownedFinding],
      moduleContext: buildFamilyModuleContext({
        childModules: [
          {
            module: "transport",
            moduleScope: ["orchestrator/src/transport"],
            source: "child_issue",
            issue: 451,
          },
          {
            module: "hub",
            moduleScope: ["orchestrator/src/hub"],
            source: "child_issue",
            issue: 452,
          },
        ],
      }),
    });

    expect(classified.blocking).toEqual([unownedFinding]);
    expect(classified.deferred).toEqual([]);
    // #604 slice 4 (ADR 0062): result classification collapsed to "blocking".
    expect(classified.results[0]).toMatchObject({
      classification: "blocking",
      attribution: { method: "missing_module_context" },
    });
  });

  it("fails closed when overlapping child module scopes make attribution ambiguous", () => {
    const overlappingFinding: Finding = {
      ...finding,
      location: "orchestrator/src/family/verifyCmr.ts:42",
      action: "wont_fix",
      disposition: {
        kind: "accepted_suppressed",
        source: "#445",
        scope: "orchestrator/src/family",
        reason: "Owner accepted this exact finding for the family CMR scope",
        findingIdentity: findingIdentityKey(finding),
        boundedReopen: "reopen on different scope, higher severity, or new evidence",
      },
    };
    const acceptedSource = {
      source: "#445",
      scope: "orchestrator/src/family",
      reason: "Owner accepted this exact finding for the family CMR scope",
      findingIdentity: findingIdentityKey(finding),
      boundedReopen: "reopen on different scope, higher severity, or new evidence",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [overlappingFinding],
      moduleContext: buildFamilyModuleContext({
        childModules: [
          {
            module: "family-runner",
            moduleScope: ["orchestrator/src/family"],
            source: "child_issue",
            issue: 449,
          },
          {
            module: "family-cmr",
            moduleScope: ["orchestrator/src/family"],
            source: "child_issue",
            issue: 450,
          },
        ],
        familyModule: {
          module: "orchestrator-family",
          moduleScope: ["orchestrator/src/family"],
          source: "family_issue",
          issue: 445,
        },
        acceptedSuppressionSources: [acceptedSource],
      }),
    });

    expect(classified.blocking).toEqual([overlappingFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.dispositions).toEqual([]);
    // #604 slice 4 (ADR 0062): result classification collapsed to "blocking"; the
    // ambiguous-child-scope fail-closed attribution is retained.
    expect(classified.results[0]).toMatchObject({
      classification: "blocking",
      attribution: { method: "ambiguous_child_module_scope" },
    });
  });

  // #604 slice 4 (ADR 0062): the cross-module-defer PASS outcome is gone — a target
  // outside the family module set no longer defers, it blocks. Both same-module and
  // formerly-cross-module findings are now blocking; the attribution logic (owningIssue
  // via child module scope) is retained.
  it("blocks findings regardless of whether the target is inside or outside the family module", () => {
    const sameModule: Finding = { ...finding };
    const crossModule: Finding = {
      ...finding,
      claim_quote: "military state machine is not implemented",
      location: "docs/military-state-machine.md:1",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [sameModule, crossModule],
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["orchestrator/src/family", "docs/fiscal"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [
          {
            module: "fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "child_issue",
            issue: 449,
          },
        ],
        undevelopedModules: [
          {
            module: "military-state-machine",
            moduleScope: ["docs/military-state-machine.md"],
            source: "family_issue",
            issue: 445,
          },
        ],
      },
    });

    expect(classified.blocking).toEqual([sameModule, crossModule]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results.map((r) => r.classification)).toEqual([
      "blocking",
      "blocking",
    ]);
    expect(classified.results[0]?.owningIssue).toBe("#449");
  });

  // #604 slice 4 (ADR 0062): the cross-module-defer PASS outcome is gone; a finding
  // whose location falls under an undeveloped module scope now blocks rather than
  // deferring. The blank-slug / casing normalization module-context logic is retained.
  it("blocks findings under undeveloped module scopes, skipping blank current module slugs", () => {
    const crossModule: Finding = {
      ...finding,
      claim_quote: "military state machine is not implemented",
      location: "docs/military-state-machine.md:1",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [crossModule],
      moduleContext: {
        currentModules: [
          {
            module: "",
            moduleScope: ["docs/empty"],
            source: "run_option",
          },
          {
            module: "fiscal",
            moduleScope: ["docs/fiscal"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [],
        undevelopedModules: [
          {
            module: "external-roadmap",
            moduleScope: ["DOCS/MILITARY-STATE-MACHINE.MD"],
            source: "family_issue",
            issue: 445,
          },
        ],
      },
    });

    expect(classified.blocking).toEqual([crossModule]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]?.classification).toBe("blocking");
  });

  it("blocks a finding whose target aliases the current module name", () => {
    const aliasedModuleFinding: Finding = { ...finding };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [aliasedModuleFinding],
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [],
        undevelopedModules: [
          {
            module: "military-state-machine",
            moduleScope: ["docs/military-state-machine.md"],
            source: "family_issue",
            issue: 445,
          },
        ],
      },
    });

    expect(classified.deferred).toEqual([]);
    expect(classified.blocking).toEqual([aliasedModuleFinding]);
    // #604 slice 4 (ADR 0062): result classification collapsed to "blocking".
    expect(classified.results[0]?.classification).toBe("blocking");
  });

  it("records accepted suppression for the #287 hub-loss finding with bounded reopen conditions", () => {
    const acceptedScope =
      "#287 hub-loss / central C_ accounts finding only; not #287 local integration or stub-contract failures";
    const acceptedReason =
      "#287 ADR0023 D9 central transport-loss C_ accounts are accepted as #261/ADR0021 hub implementation scope";
    const boundedReopen =
      "reopen if severity escalates, new evidence changes the scope, or the finding targets #287-owned local integration/stub contract behavior";
    const hubLossFinding: Finding = {
      ...finding,
      claim_quote: "ADR0023 D9 central transport-loss C_ accounts still wait for ADR0021 hub oracle",
      location: "docs/adr/0023.md:D9",
      action: "wont_fix",
      disposition_reason: acceptedReason,
      disposition: {
        kind: "accepted_suppressed",
        source: "#303",
        scope: acceptedScope,
        reason: acceptedReason,
        findingIdentity: findingIdentityKey({
          ...finding,
          claim_quote:
            "ADR0023 D9 central transport-loss C_ accounts still wait for ADR0021 hub oracle",
          location: "docs/adr/0023.md:D9",
        }),
        boundedReopen,
      },
    };
    const hubLossIdentity = findingIdentityKey(hubLossFinding);

    const classified = deriveCmrEnvelope({
      familyIssue: 287,
      findings: [hubLossFinding],
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["docs/adr/0023.md"],
            source: "family_issue",
            issue: 287,
          },
        ],
        childModules: [],
        acceptedSuppressionSources: [
          {
            source: "#303",
            scope: acceptedScope,
            reason: acceptedReason,
            findingIdentity: hubLossIdentity,
            boundedReopen,
          },
        ],
      },
    });

    expect(classified.blocking).toEqual([]);
    expect(classified.deferred).toEqual([]);
    expect(classified.dispositions).toMatchObject([
      {
        status: "accepted_suppressed",
        source: "#303",
      },
    ]);
    expect(classified.results[0]).toMatchObject({
      classification: "accepted_suppressed",
      source: "#303",
    });
  });

  it("fails closed when #287 hub-loss prose lacks an accepted suppression disposition", () => {
    const reviewerFinding: Finding = {
      ...finding,
      claim_quote:
        "ADR0023 D9 central transport-loss C_ accounts still wait for ADR0021 hub oracle",
      location: "docs/adr/0023.md:D9",
      action: "fix_now",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 287,
      findings: [reviewerFinding],
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["docs/adr/0023.md"],
            source: "family_issue",
            issue: 287,
          },
        ],
        childModules: [],
        acceptedSuppressionSources: [
          {
            source: "#303",
            scope:
              "#287 hub-loss / central C_ accounts finding only; not #287 local integration or stub-contract failures",
            reason:
              "#287 ADR0023 D9 central transport-loss C_ accounts are accepted as #261/ADR0021 hub implementation scope",
            findingIdentity: findingIdentityKey(reviewerFinding),
            boundedReopen:
              "reopen if severity escalates, new evidence changes the scope, or the finding targets #287-owned local integration/stub contract behavior",
          },
        ],
      },
    });

    expect(classified.blocking).toEqual([reviewerFinding]);
    expect(classified.deferred).toEqual([]);
    // #617: `defer` was removed from the action union. A non-accepted-suppressed
    // finding is blocking; the suppression-source that does not attach (no matching
    // disposition) does not suppress it.
    expect(classified.results[0]).toMatchObject({
      classification: "blocking",
      attribution: { method: "family_module", issue: 287, module: "fiscal" },
    });
    expect(classified.dispositions).toEqual([]);
  });

  it("fails closed when an accepted suppression names a different finding identity", () => {
    const suppressedFinding: Finding = {
      ...finding,
      action: "wont_fix",
      disposition_reason: "Accepted elsewhere, but not for this finding",
      disposition: {
        kind: "accepted_suppressed",
        source: "#445",
        scope: "fiscal",
        reason: "Accepted elsewhere, but not for this finding",
        findingIdentity: "correctness|other.ts:1|a different finding",
        boundedReopen: "reopen on severity escalation, new evidence, or different scope",
      },
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [suppressedFinding],
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [],
        undevelopedModules: [
          {
            module: "military-state-machine",
            moduleScope: ["docs/military-state-machine.md"],
            source: "family_issue",
            issue: 445,
          },
        ],
      },
    });

    expect(classified.blocking).toEqual([suppressedFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "blocking", // #604 slice 4 (ADR 0062): was same_module_still_red
      attribution: { method: "family_module", issue: 445, module: "fiscal" },
    });
    expect(classified.dispositions).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ status: "accepted_suppressed" }),
      ]),
    );
  });

  it("fails closed when accepted suppression scope matches fallback text but not module path scope", () => {
    const acceptedSource = {
      source: "#445",
      scope: "fiscal accepted suppression",
      reason: "Accepted only inside the declared fiscal module scope",
      findingIdentity: findingIdentityKey(finding),
      boundedReopen: "reopen on different scope",
    };
    const suppressedFinding: Finding = {
      ...finding,
      action: "wont_fix",
      disposition: {
        kind: "accepted_suppressed",
        source: acceptedSource.source,
        scope: acceptedSource.scope,
        reason: acceptedSource.reason,
        boundedReopen: acceptedSource.boundedReopen,
      },
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [suppressedFinding],
      moduleContext: buildFamilyModuleContext({
        childModules: [],
        familyModule: {
          module: "fiscal",
          moduleScope: ["docs/fiscal"],
          source: "family_issue",
          issue: 445,
        },
        acceptedSuppressionSources: [acceptedSource],
      }),
    });

    expect(classified.blocking).toEqual([suppressedFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "blocking", // #604 slice 4 (ADR 0062): was same_module_still_red
      attribution: { method: "missing_module_context" },
    });
    expect(classified.dispositions).toEqual([]);
  });

  it("accepts a registered suppression source passed through the module context builder", () => {
    const acceptedSource = {
      source: "#445",
      scope: "orchestrator/src/family",
      reason: "Owner accepted this exact finding for the family CMR scope",
      findingIdentity: findingIdentityKey(finding),
      boundedReopen: "reopen on different scope, higher severity, or new evidence",
    };
    const suppressedFinding: Finding = {
      ...finding,
      action: "wont_fix",
      disposition_reason: acceptedSource.reason,
      disposition: {
        kind: "accepted_suppressed",
        source: acceptedSource.source,
        scope: acceptedSource.scope,
        reason: acceptedSource.reason,
        findingIdentity: acceptedSource.findingIdentity,
        boundedReopen: acceptedSource.boundedReopen,
      },
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [suppressedFinding],
      moduleContext: buildFamilyModuleContext({
        childModules: [],
        familyModule: {
          module: "orchestrator-family",
          moduleScope: ["orchestrator/src/family"],
          source: "family_issue",
          issue: 445,
        },
        acceptedSuppressionSources: [acceptedSource],
      }),
    });

    expect(classified.blocking).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "accepted_suppressed",
      source: "#445",
    });
    expect(classified.dispositions).toEqual([
      expect.objectContaining({
        status: "accepted_suppressed",
        source: "#445",
        scope: acceptedSource.scope,
        reason: acceptedSource.reason,
      }),
    ]);
  });

  it("fails closed when accepted suppression scope only prefix-matches the module path", () => {
    const prefixScopeFinding: Finding = {
      ...finding,
      location: "orchestrator/src/family/verifyCmr.ts:42",
      action: "wont_fix",
      disposition: {
        kind: "accepted_suppressed",
        source: "#445",
        scope: "orchestrator/src/family-runner",
        reason: "Owner accepted only the family-runner scope",
        findingIdentity: findingIdentityKey(finding),
        boundedReopen: "reopen on different scope",
      },
    };
    const acceptedSource = {
      source: "#445",
      scope: "orchestrator/src/family-runner",
      reason: "Owner accepted only the family-runner scope",
      findingIdentity: findingIdentityKey(finding),
      boundedReopen: "reopen on different scope",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [prefixScopeFinding],
      moduleContext: buildFamilyModuleContext({
        childModules: [],
        familyModule: {
          module: "orchestrator-family",
          moduleScope: ["orchestrator/src/family"],
          source: "family_issue",
          issue: 445,
        },
        acceptedSuppressionSources: [acceptedSource],
      }),
    });

    expect(classified.blocking).toEqual([prefixScopeFinding]);
    expect(classified.dispositions).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "blocking", // #604 slice 4 (ADR 0062): was same_module_still_red
      attribution: { method: "family_module", module: "orchestrator-family" },
    });
  });

  it("fails closed when accepted suppression scope only prefix-matches the issue number", () => {
    const prefixIssueFinding: Finding = {
      ...finding,
      action: "wont_fix",
      disposition: {
        kind: "accepted_suppressed",
        source: "#4450",
        scope: "#4450",
        reason: "Owner accepted only issue 4450",
        findingIdentity: findingIdentityKey(finding),
        boundedReopen: "reopen on different issue",
      },
    };
    const acceptedSource = {
      source: "#4450",
      scope: "#4450",
      reason: "Owner accepted only issue 4450",
      findingIdentity: findingIdentityKey(finding),
      boundedReopen: "reopen on different issue",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [prefixIssueFinding],
      moduleContext: buildFamilyModuleContext({
        childModules: [],
        familyModule: {
          module: "orchestrator-family",
          moduleScope: ["orchestrator/src/family"],
          source: "family_issue",
          issue: 445,
        },
        acceptedSuppressionSources: [acceptedSource],
      }),
    });

    expect(classified.blocking).toEqual([prefixIssueFinding]);
    expect(classified.dispositions).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "blocking", // #604 slice 4 (ADR 0062): was same_module_still_red
      attribution: { method: "family_module", module: "orchestrator-family" },
    });
  });

  it("fails closed when a prior accepted suppression has stale module scope", () => {
    const currentFinding: Finding = {
      ...finding,
      action: "fix_now",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [currentFinding],
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [],
      },
      priorDispositions: [
        {
          identityKey:
            "correctness|orchestrator/src/family/verifycmr.ts:42|hub loss accounts are still unimplemented",
          status: "accepted_suppressed",
          reason: "Accepted only for a different module",
          severity: "medium",
          reopenAttempts: 0,
          disputeAttempts: 1,
          source: "#445",
          scope: "military-state-machine",
          boundedReopen: "reopen on different scope",
        },
      ],
    });

    expect(classified.blocking).toEqual([currentFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "blocking", // #604 slice 4 (ADR 0062): was same_module_still_red
      attribution: { method: "family_module", issue: 445, module: "fiscal" },
    });
    expect(classified.dispositions).toEqual([]);
  });

  it("fails closed when accepted suppression targetModule matches but scope text is stale", () => {
    const acceptedSource = {
      source: "#445",
      scope: "orchestrator/src/family",
      reason: "Accepted only for the family CMR scope",
      findingIdentity: findingIdentityKey(finding),
      boundedReopen: "reopen on different scope",
    };
    const suppressedFinding: Finding = {
      ...finding,
      action: "wont_fix",
      disposition_reason: acceptedSource.reason,
      disposition: {
        kind: "accepted_suppressed",
        source: acceptedSource.source,
        scope: "military-state-machine follow-up only",
        reason: acceptedSource.reason,
        findingIdentity: acceptedSource.findingIdentity,
        boundedReopen: acceptedSource.boundedReopen,
      },
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [suppressedFinding],
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [],
        undevelopedModules: [
          {
            module: "military-state-machine",
            moduleScope: ["docs/military-state-machine.md"],
            source: "family_issue",
            issue: 445,
          },
        ],
        acceptedSuppressionSources: [acceptedSource],
      },
    });

    expect(classified.blocking).toEqual([suppressedFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "blocking", // #604 slice 4 (ADR 0062): was same_module_still_red
      attribution: { method: "family_module", issue: 445, module: "fiscal" },
    });
    expect(classified.dispositions).toEqual([]);
  });

  it("fails closed when a prior accepted suppression source matches but scope text is stale", () => {
    const currentFinding: Finding = {
      ...finding,
      action: "fix_now",
    };
    const acceptedSource = {
      source: "#445",
      scope: "orchestrator/src/family",
      reason: "Accepted only for the family CMR scope",
      findingIdentity: findingIdentityKey(finding),
      boundedReopen: "reopen on different scope",
    };

    const classified = deriveCmrEnvelope({
      familyIssue: 445,
      findings: [currentFinding],
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [],
        acceptedSuppressionSources: [acceptedSource],
      },
      priorDispositions: [
        {
          identityKey: acceptedSource.findingIdentity,
          status: "accepted_suppressed",
          reason: acceptedSource.reason,
          severity: "medium",
          reopenAttempts: 0,
          source: acceptedSource.source,
          scope: "military-state-machine follow-up only",
          boundedReopen: acceptedSource.boundedReopen,
        },
      ],
    });

    expect(classified.blocking).toEqual([currentFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "blocking", // #604 slice 4 (ADR 0062): was same_module_still_red
      attribution: { method: "family_module", issue: 445, module: "fiscal" },
    });
    expect(classified.dispositions).toEqual([]);
  });

  it.each(["high", "critical"] as const)(
    "reopens the #287 hub-loss suppression when reviewer severity escalates to %s",
    (severity) => {
      const escalatedHubLossFinding: Finding = {
        ...finding,
        severity,
        claim_quote: "ADR0023 D9 central transport-loss C_ accounts still wait for ADR0021 hub oracle",
        location: "docs/adr/0023.md:D9",
        action: "fix_now",
      };

      const classified = deriveCmrEnvelope({
        familyIssue: 287,
        findings: [escalatedHubLossFinding],
        moduleContext: {
          currentModules: [
            {
              module: "fiscal",
              moduleScope: ["docs/adr/0023.md"],
              source: "family_issue",
              issue: 287,
            },
          ],
          childModules: [],
        },
      });

      expect(classified.blocking).toEqual([escalatedHubLossFinding]);
      expect(classified.deferred).toEqual([]);
      expect(classified.results[0]).toMatchObject({
        classification: "blocking", // #604 slice 4 (ADR 0062): was same_module_still_red
        attribution: { method: "family_module", issue: 287, module: "fiscal" },
      });
      expect(classified.dispositions).not.toEqual(
        expect.arrayContaining([
          expect.objectContaining({ status: "accepted_suppressed" }),
        ]),
      );
    },
  );
});

describe("#449 CMR worker output parsing", () => {
  it("preserves structured findings on a not-converged CMR verdict", () => {
    const parsed = parseCmrOutcome(
      `<cmr>${JSON.stringify({
        converged: false,
        reason: "same-family gap remains",
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        ...CMR_EVIDENCE,
        findings: [finding],
      })}</cmr>`,
    );

    expect(parsed).toMatchObject({
      kind: "verdict",
      converged: false,
      findings: [finding],
    });
  });

  it("#598 a closure disposition missing a required field (boundedReopen) is MALFORMED, not a completed verdict", () => {
    // #598 downstream required-field re-validation: a CMR output whose
    // accepted_suppressed closure disposition omits a required field
    // (source/scope/boundedReopen) fails the strict parse schema → `malformed`, so
    // it is routed to the same-worker rewrite + the generic mechanical retry rather
    // than silently accepted as a completed verdict. Schema/protocol-level checking,
    // not content judgment.
    const parsed = parseCmrOutcome(
      `<cmr>${JSON.stringify({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [
          {
            identityKey: "correctness|src/x.ts:1|foo",
            status: "accepted_suppressed",
            source: "issue #448 acceptance criteria",
            scope: "same documented non-goal",
            reason: "accepted as outside this slice",
            // boundedReopen intentionally OMITTED → schema fails → malformed.
          },
        ],
        ...CMR_EVIDENCE,
      })}</cmr>`,
    );
    expect(parsed.kind).toBe("malformed");
  });
});

class CmrFindingBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly dispatched: WorkerSpec["kind"][] = [];
  readonly escalations: FamilyEscalation[] = [];
  currentFamilyHead = "head-449";

  constructor(private readonly cmrResult: WorkerResult) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: `h-${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    return this.currentFamilyHead;
  }
  async escalateFamily(escalation: FamilyEscalation): Promise<void> {
    this.escalations.push(escalation);
    await recordFamilyEscalated(this, {
      escalationKind: "decision",
      phase: "final",
      reason: escalation.reason,
      familyHeadAfter: escalation.familyHeadAfter,
      stopSummary: escalation.stopSummary,
    });
  }
  async runFamilyVerify(_req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatched.push(spec.kind);
    if (spec.kind === "cmr") return this.cmrResult;
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: "pr://family/449",
          prHead: this.currentFamilyHead,
        },
      };
    }
    if (
      spec.kind === "verify" ||
      spec.kind === "fixer" ||
      spec.kind === "cleanup" ||
      spec.kind === "docRelease"
    ) {
      return {
        kind: "completed",
        output:
          spec.kind === "verify"
            ? { kind: "verify", converged: true }
            : spec.kind === "fixer"
              ? {
                kind: "fixer",
                committed: true,
                fixCommitSha: "fixsha1111111111111111111111111111111111",
              }
              : spec.kind === "cleanup"
                ? { kind: "cleanup", terminal: true, ok: true, branchOutcome: "already_gone" }
                : { kind: "docRelease", released: true },
      };
    }
    // #598: a coder-fix that cannot fix returns a `failed` RESULT (a judged
    // not-ok, not a process crash); the generic mechanical retry defers judged
    // results to the gate, so this is one dispatch with no retry.
    return { kind: "failed", reason: `coder-fix reached (probe): ${spec.kind}` };
  }
}

class SequencedCmrBackend extends CmrFindingBackend {
  private cmrIndex = 0;

  constructor(private readonly cmrResults: ReadonlyArray<WorkerResult>) {
    super(cmrResults[0]!);
  }

  override async dispatchWorker(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
    this.dispatched.push(spec.kind);
    if (spec.kind === "cmr") {
      const result = this.cmrResults[this.cmrIndex] ?? this.cmrResults.at(-1);
      this.cmrIndex += 1;
      return result!;
    }
    if (spec.kind === "ship") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase!,
          status: "pr_opened",
          pr: "pr://family/449",
          prHead: this.currentFamilyHead,
        },
      };
    }
    if (
      spec.kind === "verify" ||
      spec.kind === "fixer" ||
      spec.kind === "cleanup" ||
      spec.kind === "docRelease"
    ) {
      return {
        kind: "completed",
        output:
          spec.kind === "verify"
            ? { kind: "verify", converged: true }
            : spec.kind === "fixer"
              ? {
                kind: "fixer",
                committed: true,
                fixCommitSha: "fixsha1111111111111111111111111111111111",
              }
              : spec.kind === "cleanup"
                ? { kind: "cleanup", terminal: true, ok: true, branchOutcome: "already_gone" }
                : { kind: "docRelease", released: true },
      };
    }
    // #598: a coder-fix that cannot fix returns a `failed` RESULT (a judged
    // not-ok, not a process crash); the generic mechanical retry defers judged
    // results to the gate, so this is one dispatch with no retry.
    return { kind: "failed", reason: `coder-fix reached (probe): ${spec.kind}` };
  }
}

describe("#449 verifyCmr family gate classification", () => {
  it("blocks a defer when the CMR finding lacks a declared family module context", async () => {
    const backend = new CmrFindingBackend({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        reason: "reviewers tried to defer without module context",
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        ...CMR_EVIDENCE,
        findings: [finding],
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/445-base",
      familyBackend: backend,
      familyIssue: 445,
      moduleContext: { currentModules: [], childModules: [] },
    });

    // #604 slice 2 / ADR 0062: a blocking finding no longer TERMINATES the family on
    // its content classification — the runner counts it and routes it through coder-fix.
    // This backend has no coder-fix worker, so the coder-fix attempt fails and the family
    // still aborts; the point preserved here is that the finding CLASSIFIES as blocking.
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatched).toEqual(["cmr", "coder"]);
    // #604 slice 3 / ADR 0062: the classification decision no longer persists to the
    // ledger — the runner-visible proof that the finding classified as BLOCKING (and
    // was therefore routed to coder-fix) is its identity key on the thin envelope.
    expect(backend.ledger[0]).toMatchObject({
      status: "cmr_reviewed",
      cmrPass: "completeness",
      blockingFindingIdentityKeys: [findingIdentityKey(finding)],
    });
    expect(backend.ledger[0]).not.toHaveProperty("cmrFindingClassification");
  });

  it("blocks a cross-module defer when the target is outside current modules but not declared undeveloped", async () => {
    // #604 slice 4 (ADR 0062): the `cross_module` disposition kind is gone; this is
    // now a plain blocking finding whose location falls outside the declared modules.
    const undeclaredTargetFinding: Finding = {
      ...finding,
      claim_quote: "unregistered target should not pass as cross-module work",
      location: "docs/unregistered-new-module.md:1",
    };
    const backend = new CmrFindingBackend({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        reason: "undeclared target should block",
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        ...CMR_EVIDENCE,
        findings: [undeclaredTargetFinding],
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/445-base",
      familyBackend: backend,
      familyIssue: 445,
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [],
      },
    });

    // #604 slice 2 / ADR 0062: the blocking finding is counted and routed through
    // coder-fix rather than terminating the family on its classification. The backend
    // has no coder-fix worker, so the family still fails; the invariant preserved is
    // that the undeclared-target defer CLASSIFIES as blocking.
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatched).toEqual(["cmr", "coder"]);
    // #604 slice 3 / ADR 0062: only the thin key envelope persists; the undeclared-
    // target defer classifies as BLOCKING, observable as its key on the envelope.
    expect(backend.ledger[0]).toMatchObject({
      status: "cmr_reviewed",
      cmrPass: "completeness",
      blockingFindingIdentityKeys: [findingIdentityKey(undeclaredTargetFinding)],
    });
    expect(backend.ledger[0]).not.toHaveProperty("cmrFindingClassification");
  });

  it("populates run-option undeveloped modules into the family gate context", async () => {
    const parsed = parseModuleDeclaration(`## Module Declaration
\`\`\`yaml
module: fiscal
module_scope:
  - orchestrator/src/family
\`\`\`
`);
    expect(parsed).toEqual({
      module: "fiscal",
      moduleScope: ["orchestrator/src/family"],
    });
    // #604 slice 4 (ADR 0062): the cross-module-defer PASS is gone — a finding whose
    // location falls under a run-option-declared undeveloped module now BLOCKS rather
    // than passing. The retained behavior under test is that run-option undeveloped
    // modules still feed into the gate's module context (buildFamilyModuleContext);
    // the finding classifies as blocking and routes through coder-fix.
    const crossModuleFinding: Finding = {
      ...finding,
      claim_quote: "production parsed undeveloped module should unlock defer",
      location: "docs/military-state-machine.md:1",
    };
    const backend = new CmrFindingBackend({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        reason: "only parsed cross-module follow-up findings remain",
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        ...CMR_EVIDENCE,
        findings: [crossModuleFinding],
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/445-base",
      familyBackend: backend,
      familyIssue: 445,
      moduleContext: buildFamilyModuleContext({
        childModules: [],
        familyModule: {
          ...parsed!,
          source: "family_issue",
          issue: 445,
        },
        undevelopedModules: [
          {
            module: "military-state-machine",
            moduleScope: ["docs/military-state-machine.md"],
            source: "run_option",
          },
        ],
      }),
    });

    // The blocking finding routes to coder-fix; this backend has no coder-fix worker,
    // so the family aborts. The preserved invariant is that the finding CLASSIFIES as
    // blocking (its key on the thin cmr_reviewed envelope), not that it defers.
    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatched).toEqual(["cmr", "coder"]);
    expect(backend.ledger[0]).toMatchObject({
      status: "cmr_reviewed",
      cmrPass: "completeness",
      blockingFindingIdentityKeys: [findingIdentityKey(crossModuleFinding)],
    });
    expect(backend.ledger[0]).not.toHaveProperty("cmrFindingClassification");
  });

  it("records a CMR worker decision escalation as a spec conflict, not infra failure", async () => {
    const backend = new CmrFindingBackend({
      kind: "escalated",
      escalation: {
        reason: "accepted designs conflict",
        diagnosis: "ADR and issue acceptance criteria disagree",
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/445-base",
      familyBackend: backend,
      familyIssue: 445,
      moduleContext: {
        currentModules: [],
        childModules: [],
      },
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatched).toEqual(["cmr"]);
    expect(backend.ledger[0]).toMatchObject({
      status: "aborted",
      cmrPass: "completeness",
      stopSummary: {
        reason: "spec_conflict",
        summary: expect.stringContaining("accepted designs conflict"),
        repairHint: expect.stringContaining("design/specification conflict"),
      },
    });
    expect(backend.escalations[0]).toMatchObject({
      stopSummary: { reason: "spec_conflict" },
    });
    expect(backend.ledger[1]).toMatchObject({
      status: "escalated",
      stopSummary: {
        reason: "spec_conflict",
        summary: expect.stringContaining("accepted designs conflict"),
      },
    });
  });

  it("records a provider/auth CMR worker failure as provider_degraded, not infra_failure", async () => {
    const backend = new CmrFindingBackend({
      kind: "failed",
      reason: "provider authentication failed for agy reviewer",
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/445-base",
      familyBackend: backend,
      familyIssue: 445,
      moduleContext: {
        currentModules: [],
        childModules: [],
      },
    });

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatched).toEqual(["cmr"]);
    expect(backend.ledger[0]).toMatchObject({
      status: "aborted",
      cmrPass: "completeness",
      stopSummary: {
        reason: "provider_degraded",
        metadata: {
          providerDegraded: [
            expect.objectContaining({
              provider: "agy",
              leg: "agy",
              reason: expect.stringContaining("provider authentication failed"),
              blocking: true,
              repairHint: expect.stringContaining("agy"),
            }),
          ],
        },
      },
    });
  });

  it("normalizes dirty string-shaped CMR route legs in provider-degraded summaries", () => {
    const summary = providerDegradedWorkerFailureStopSummary({
      reason: "provider authentication failed for agy reviewer",
      resolvedRoute: {
        routeName: "dirty-test",
        slots: {} as never,
        legCollections: { cmrReview: ["agy"] } as never,
        tightFamilyViolations: [],
        smoke: {},
      },
    });

    expect(summary).toMatchObject({
      reason: "provider_degraded",
      metadata: {
        providerDegraded: [
          expect.objectContaining({
            provider: "agy",
            leg: "agy",
            blocking: true,
          }),
        ],
      },
    });
  });

  // #604 slice 4 (ADR 0062): DELETED "lets a declared cross-module CMR defer pass and
  // records the classification in the ledger" — its whole point was the cross-module
  // defer PASS outcome, which no longer exists (every non-suppressed finding blocks).
  // The retained "run-option undeveloped module feeds the gate context → blocking"
  // behavior is covered by "populates run-option undeveloped modules into the family
  // gate context" above.

  it("records accepted_suppressed dispositions in successful CMR stop summary metadata", async () => {
    const suppressedFindingBase: Finding = {
      ...finding,
      severity: "medium",
      claim_quote: "route accounting follow-up is accepted as bounded out of scope",
      location: "orchestrator/src/modelRoutes.ts:1",
      action: "wont_fix",
      disposition_reason: "accepted hub stub suppression",
    };
    const suppressedFindingIdentity = findingIdentityKey(suppressedFindingBase);
    const suppressedFinding: Finding = {
      ...suppressedFindingBase,
      disposition: {
        kind: "accepted_suppressed",
        source: "#303",
        scope: "#287 hub-loss / central C_ accounts finding only",
        reason: "accepted hub stub suppression",
        findingIdentity: suppressedFindingIdentity,
        boundedReopen: "reopen on severity escalation, new evidence, or #287-owned local integration scope",
      },
    };
    const backend = new CmrFindingBackend({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        reason: "only accepted suppressions remain",
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        ...CMR_EVIDENCE,
        findings: [suppressedFinding],
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/445-base",
      familyBackend: backend,
      familyIssue: 287,
      moduleContext: {
        currentModules: [
          {
            module: "orchestrator-family",
            moduleScope: ["orchestrator/src/modelRoutes.ts"],
            source: "family_issue",
            issue: 287,
          },
        ],
        childModules: [],
        acceptedSuppressionSources: [
          {
            source: "#303",
            scope: "#287 hub-loss / central C_ accounts finding only",
            reason: "accepted hub stub suppression",
            findingIdentity: suppressedFindingIdentity,
            boundedReopen:
              "reopen on severity escalation, new evidence, or #287-owned local integration scope",
          },
        ],
      },
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatched).toEqual([
      "cmr",
      "cmr",
      "ship",
      "verify",
      "docRelease",
      "cleanup",
    ]);
    expect(backend.ledger[0]).toMatchObject({
      status: "cmr_passed",
      cmrPass: "completeness",
      stopSummary: {
        reason: "success",
        metadata: {
          acceptedSuppressions: [
            expect.objectContaining({
              source: "#303",
              scope: expect.stringContaining("#287 hub-loss / central C_ accounts"),
              findingIdentity: expect.stringMatching(/route accounting follow-up/i),
              boundedReopen: expect.stringMatching(/severity escalat/i),
            }),
          ],
        },
      },
    });
  });

  // #604 slice 4 (ADR 0062): the cross-module-defer PASS is gone, so a pass row is no
  // longer produced alongside a cross_module finding. The retained behavior under test
  // is that a PASS carrying an accepted-suppression + a skipped (provider-degraded) leg
  // preserves BOTH on the stop summary metadata. The former cross_module finding is
  // dropped (it would now block); the pass reason is "success".
  it("preserves accepted suppression and skipped-leg metadata on CMR pass rows", async () => {
    const suppressedFindingBase: Finding = {
      ...finding,
      severity: "medium",
      claim_quote: "family ledger audit note is accepted as bounded out of scope",
      location: "orchestrator/src/family/ledger.ts:1",
      action: "wont_fix",
      disposition_reason: "accepted family ledger audit suppression",
    };
    const suppressedFindingIdentity = findingIdentityKey(suppressedFindingBase);
    const suppressedFinding: Finding = {
      ...suppressedFindingBase,
      disposition: {
        kind: "accepted_suppressed",
        source: "#445",
        scope: "#445 / orchestrator/src/family accepted ledger audit note only",
        reason: "accepted family ledger audit suppression",
        findingIdentity: suppressedFindingIdentity,
        boundedReopen: "reopen on severity escalation, new evidence, or #287-owned local integration scope",
      },
    };
    const backend = new CmrFindingBackend({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        reason: "only nonblocking family CMR findings remain",
        successfulLegs: ["opus", "agy"],
        skippedLegs: [{ slug: "gpt-5.6-sol", reason: "codex quota unavailable" }],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        ...CMR_EVIDENCE,
        findings: [suppressedFinding],
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/445-base",
      familyBackend: backend,
      familyIssue: 445,
      moduleContext: {
        currentModules: [
          {
            module: "fiscal",
            moduleScope: ["orchestrator/src/family"],
            source: "family_issue",
            issue: 445,
          },
        ],
        childModules: [],
        fallbackModule: {
          module: "fiscal",
          moduleScope: ["orchestrator/src/family"],
          source: "family_issue",
          issue: 445,
        },
        acceptedSuppressionSources: [
          {
            source: "#445",
            scope: "#445 / orchestrator/src/family accepted ledger audit note only",
            reason: "accepted family ledger audit suppression",
            findingIdentity: suppressedFindingIdentity,
            boundedReopen:
              "reopen on severity escalation, new evidence, or #287-owned local integration scope",
          },
        ],
      },
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.ledger[0]).toMatchObject({
      status: "cmr_passed",
      cmrPass: "completeness",
      stopSummary: {
        reason: "success",
        metadata: {
          acceptedSuppressions: [
            expect.objectContaining({
              source: "#445",
              scope: expect.stringContaining("orchestrator/src/family"),
              findingIdentity: expect.stringMatching(/family ledger audit note/i),
              boundedReopen: expect.stringMatching(/severity escalat/i),
            }),
          ],
          providerDegraded: [
            expect.objectContaining({
              leg: "gpt-5.6-sol",
              reason: "codex quota unavailable",
              blocking: false,
            }),
          ],
        },
      },
    });
  });

  // #604 slice 4 (ADR 0062): DELETED "shipped summary preserves material CMR
  // disposition over later head-only success". Its premise was a material
  // `cross_module_defer` disposition produced by the classifier on the current head
  // (a passing cross-module defer) surviving to the shipped summary. The classifier
  // can no longer emit `cross_module_defer` — a cross-module finding now blocks — so
  // this behavior is unreachable. The complementary head-matching logic (a shipped
  // summary reflecting the verified head's stop summary) is still covered by
  // "shipped summary ignores material CMR disposition from an older family head".

  it("shipped summary ignores material CMR disposition from an older family head", async () => {
    const backend = new SequencedCmrBackend([
      {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          ...CMR_EVIDENCE,
        },
      },
      {
        kind: "completed",
        output: {
          kind: "cmr",
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
          claimedFixedFindingIdentityKeys: [],
          priorFindingDispositions: [],
          ...CMR_EVIDENCE,
        },
      },
    ]);
    backend.ledger.push({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "final",
      cmrPass: "correctness",
      familyHeadAfter: "old-head",
      stopSummary: {
        reason: "cross_module_defer",
        summary: "old material defer",
        repairHint: "old follow-up",
      },
    });

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/445-base",
      familyBackend: backend,
      familyIssue: 445,
    });

    expect(result).toEqual({ ok: true, ran: true });
    const shipped = backend.ledger.find((entry) => entry.status === "shipped");
    expect(shipped?.stopSummary).toMatchObject({
      reason: "success",
      metadata: {
        heads: expect.objectContaining({
          verifiedCmrHead: "head-449",
        }),
      },
    });
    expect(shipped?.stopSummary?.reason).not.toBe("cross_module_defer");
  });
});
