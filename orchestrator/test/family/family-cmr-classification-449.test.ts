import { describe, expect, it } from "vitest";

import {
  buildFamilyModuleContext,
  classifyFamilyCmrFindings,
  parseModuleDeclaration,
} from "../../src/family/cmrClassification.js";
import { findingIdentityKey } from "../../src/findings.js";
import { recordFamilyEscalated } from "../../src/family/ledger.js";
import { parseCmrOutcome } from "../../src/family/realFamilyBackend.js";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
} from "../../src/family/types.js";
import type { DispatchContext, Finding, WorkerResult, WorkerSpec } from "../../src/types.js";

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
  });
});

const finding: Finding = {
  severity: "medium",
  category: "correctness",
  claim_quote: "hub loss accounts are still unimplemented",
  location: "orchestrator/src/family/verifyCmr.ts:42",
  suggested_fix: "close the family CMR gate instead of deferring same-module work",
  action: "defer",
  disposition: {
    kind: "cross_module",
    targetModule: "fiscal",
    reason: "claimed as outside the current module",
  },
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

  it("keeps the parent module as fallback when child attribution is unavailable", () => {
    const parentScopedFinding: Finding = {
      ...finding,
      location: "docs/fiscal/family-contract.md:12",
      disposition: {
        kind: "cross_module",
        targetModule: "fiscal",
        reason: "claimed as outside child issue scope",
      },
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

    const classified = classifyFamilyCmrFindings({
      familyIssue: 445,
      findings: [parentScopedFinding],
      moduleContext,
    });

    expect(classified.blocking).toEqual([parentScopedFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "same_module_still_red",
      attribution: { method: "family_module", issue: 445, module: "fiscal" },
      owningIssue: "#445",
    });
  });

  it("fails closed on cross-module defer when no module declaration establishes the family module", () => {
    const classified = classifyFamilyCmrFindings({
      familyIssue: 445,
      findings: [finding],
      moduleContext: { currentModules: [], childModules: [] },
    });

    expect(classified.blocking).toEqual([finding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "same_module_still_red",
      attribution: { method: "missing_module_context" },
    });
  });

  it("fails closed when child attribution is ambiguous and no explicit family fallback exists", () => {
    const unownedFinding: Finding = {
      ...finding,
      claim_quote: "military state machine is not implemented",
      location: "docs/military-state-machine.md:1",
      disposition: {
        kind: "cross_module",
        targetModule: "military-state-machine",
        reason: "outside the declared child modules",
      },
    };

    const classified = classifyFamilyCmrFindings({
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
    expect(classified.results[0]).toMatchObject({
      classification: "same_module_still_red",
      attribution: { method: "missing_module_context" },
    });
  });

  it("allows only target modules outside the declared family module set to defer", () => {
    const sameModule = {
      ...finding,
      disposition: {
        kind: "cross_module" as const,
        targetModule: "fiscal",
        reason: "same family module, despite defer wording",
      },
    };
    const crossModule = {
      ...finding,
      claim_quote: "military state machine is not implemented",
      location: "docs/military-state-machine.md:1",
      disposition: {
        kind: "cross_module" as const,
        targetModule: "military-state-machine",
        reason: "outside the declared fiscal family module",
      },
    };

    const classified = classifyFamilyCmrFindings({
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

    expect(classified.blocking).toEqual([sameModule]);
    expect(classified.deferred).toEqual([crossModule]);
    expect(classified.results.map((r) => r.classification)).toEqual([
      "same_module_still_red",
      "cross_module_defer",
    ]);
    expect(classified.results[0]?.owningIssue).toBe("#449");
    expect(classified.results[1]?.targetModule).toBe("military-state-machine");
  });

  it("fails closed when a cross-module target aliases the current module name", () => {
    const aliasedModuleFinding: Finding = {
      ...finding,
      disposition: {
        kind: "cross_module",
        targetModule: "fiscal follow-up",
        reason: "claimed as an external follow-up bucket",
      },
    };

    const classified = classifyFamilyCmrFindings({
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
    expect(classified.results[0]?.classification).toBe("same_module_still_red");
  });

  it("records accepted suppression for the #287 hub-loss finding with bounded reopen conditions", () => {
    const hubLossFinding: Finding = {
      ...finding,
      claim_quote: "ADR0023 D9 central transport-loss C_ accounts still wait for ADR0021 hub oracle",
      location: "docs/adr/0023.md:D9",
      action: "defer",
      disposition: {
        kind: "cross_module",
        targetModule: "hub",
        reason: "the hub implementation is outside #287",
      },
    };

    const classified = classifyFamilyCmrFindings({
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
            scope:
              "#287 hub-loss / central C_ accounts finding only; not #287 local integration or stub-contract failures",
            reason:
              "#287 ADR0023 D9 central transport-loss C_ accounts are accepted as #261/ADR0021 hub implementation scope",
            findingIdentity: findingIdentityKey(hubLossFinding),
            boundedReopen:
              "reopen if severity escalates, new evidence changes the scope, or the finding targets #287-owned local integration/stub contract behavior",
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
        targetModule: "#261/ADR0021 hub implementation",
      },
    ]);
    expect(classified.results[0]).toMatchObject({
      classification: "accepted_suppressed",
      source: "#303",
      targetModule: "#261/ADR0021 hub implementation",
    });
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
        targetModule: "fiscal",
        boundedReopen: "reopen on severity escalation, new evidence, or different scope",
      },
    };

    const classified = classifyFamilyCmrFindings({
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
      classification: "same_module_still_red",
      attribution: { method: "family_module", issue: 445, module: "fiscal" },
    });
    expect(classified.dispositions).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ status: "accepted_suppressed" }),
      ]),
    );
  });

  it("fails closed when a prior accepted suppression has stale module scope", () => {
    const currentFinding: Finding = {
      ...finding,
      action: "fix_now",
    };

    const classified = classifyFamilyCmrFindings({
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
          targetModule: "military-state-machine",
          boundedReopen: "reopen on different scope",
        },
      ],
    });

    expect(classified.blocking).toEqual([currentFinding]);
    expect(classified.deferred).toEqual([]);
    expect(classified.results[0]).toMatchObject({
      classification: "same_module_still_red",
      attribution: { method: "family_module", issue: 445, module: "fiscal" },
    });
    expect(classified.dispositions).toEqual([]);
  });

  it("fails closed when accepted suppression targetModule matches but scope text is stale", () => {
    const suppressedFinding: Finding = {
      ...finding,
      action: "wont_fix",
      disposition_reason: "Accepted only for a different module scope",
      disposition: {
        kind: "accepted_suppressed",
        source: "#445",
        scope: "military-state-machine follow-up only",
        reason: "Accepted only for a different module scope",
        findingIdentity: findingIdentityKey(finding),
        targetModule: "fiscal",
        boundedReopen: "reopen on different scope",
      },
    };

    const classified = classifyFamilyCmrFindings({
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
      classification: "same_module_still_red",
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
        action: "defer",
        disposition: {
          kind: "cross_module",
          targetModule: "hub",
          reason: "the hub implementation is outside #287",
        },
      };

      const classified = classifyFamilyCmrFindings({
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
        classification: "same_module_still_red",
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
        successfulLegs: ["opus", "gpt-5.5", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        findings: [finding],
      })}</cmr>`,
    );

    expect(parsed).toMatchObject({
      kind: "verdict",
      converged: false,
      findings: [finding],
    });
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
          pr: "https://example.test/pr/449",
          prHead: this.currentFamilyHead,
        },
      };
    }
    throw new Error(`unexpected ${spec.kind}`);
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
        successfulLegs: ["opus", "gpt-5.5", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
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

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatched).toEqual(["cmr"]);
    expect(backend.ledger[0]).toMatchObject({
      status: "aborted",
      cmrPass: "completeness",
      cmrFindingClassification: {
        results: [{ classification: "same_module_still_red" }],
      },
    });
  });

  it("blocks a cross-module defer when the target is outside current modules but not declared undeveloped", async () => {
    const undeclaredTargetFinding: Finding = {
      ...finding,
      claim_quote: "unregistered target should not pass as cross-module work",
      location: "docs/unregistered-new-module.md:1",
      disposition: {
        kind: "cross_module",
        targetModule: "unregistered-new-module",
        reason: "outside current module but not declared as an undeveloped target",
      },
    };
    const backend = new CmrFindingBackend({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        reason: "undeclared target should block",
        successfulLegs: ["opus", "gpt-5.5", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
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

    expect(result).toEqual({ ok: false, ran: true });
    expect(backend.dispatched).toEqual(["cmr"]);
    expect(backend.ledger[0]).toMatchObject({
      status: "aborted",
      cmrPass: "completeness",
      cmrFindingClassification: {
        blocking: [expect.objectContaining({ claim_quote: undeclaredTargetFinding.claim_quote })],
        results: [{ classification: "same_module_still_red" }],
      },
    });
  });

  it("populates declared undeveloped modules from fenced module YAML into the family gate context", async () => {
    const parsed = parseModuleDeclaration(`## Module Declaration
\`\`\`yaml
module: fiscal
module_scope:
  - orchestrator/src/family
undeveloped_modules:
  - military-state-machine
\`\`\`
`);
    expect(parsed).toEqual({
      module: "fiscal",
      moduleScope: ["orchestrator/src/family"],
      undevelopedModules: [
        {
          module: "military-state-machine",
          moduleScope: ["military-state-machine"],
        },
      ],
    });
    const crossModuleFinding: Finding = {
      ...finding,
      claim_quote: "production parsed undeveloped module should unlock defer",
      location: "docs/military-state-machine.md:1",
      disposition: {
        kind: "cross_module",
        targetModule: "military-state-machine",
        reason: "outside current module and declared undeveloped in the family issue",
      },
    };
    const backend = new CmrFindingBackend({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        reason: "only parsed cross-module follow-up findings remain",
        successfulLegs: ["opus", "gpt-5.5", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
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
      }),
    });

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatched).toEqual(["cmr", "cmr", "ship"]);
    expect(backend.ledger[0]).toMatchObject({
      status: "cmr_passed",
      cmrPass: "completeness",
      stopSummary: {
        reason: "cross_module_defer",
        targetModule: "military-state-machine",
      },
      cmrFindingClassification: {
        deferred: [expect.objectContaining({ claim_quote: crossModuleFinding.claim_quote })],
        results: [{ classification: "cross_module_defer", targetModule: "military-state-machine" }],
        moduleContext: {
          currentModules: [
            expect.objectContaining({
              module: "fiscal",
              moduleScope: ["orchestrator/src/family"],
              source: "family_issue",
              issue: 445,
            }),
          ],
          childModules: [],
          fallbackModule: expect.objectContaining({
            module: "fiscal",
            source: "family_issue",
            issue: 445,
          }),
          undevelopedModules: [
            expect.objectContaining({
              module: "military-state-machine",
              moduleScope: ["military-state-machine"],
              source: "family_issue",
              issue: 445,
            }),
          ],
        },
      },
    });
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

  it("lets a declared cross-module CMR defer pass and records the classification in the ledger", async () => {
    const crossModuleFinding: Finding = {
      ...finding,
      claim_quote: "military state machine still lacks the combat transition",
      location: "docs/military-state-machine.md:1",
      disposition: {
        kind: "cross_module",
        targetModule: "military-state-machine",
        reason: "outside the declared fiscal family module",
      },
    };
    const backend = new CmrFindingBackend({
      kind: "completed",
      output: {
        kind: "cmr",
        converged: false,
        reason: "only cross-module follow-up findings remain",
        successfulLegs: ["opus", "gpt-5.5", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
        findings: [crossModuleFinding],
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

    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.dispatched).toEqual(["cmr", "cmr", "ship"]);
    expect(backend.ledger.filter((entry) => entry.status === "aborted")).toEqual([]);
    expect(backend.ledger[0]).toMatchObject({
      status: "cmr_passed",
      cmrPass: "completeness",
      stopSummary: {
        reason: "cross_module_defer",
        targetModule: "military-state-machine",
        summary: "outside the declared fiscal family module",
      },
      cmrFindingClassification: {
        deferred: [expect.objectContaining({ claim_quote: crossModuleFinding.claim_quote })],
        results: [{ classification: "cross_module_defer", targetModule: "military-state-machine" }],
      },
    });
  });

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
        successfulLegs: ["opus", "gpt-5.5", "agy"],
        claimedFixedFindingIdentityKeys: [],
        priorFindingDispositions: [],
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
            moduleScope: ["orchestrator/src/family"],
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
    expect(backend.dispatched).toEqual(["cmr", "cmr", "ship"]);
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
});
