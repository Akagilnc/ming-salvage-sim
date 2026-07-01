import {
  buildFamilyModuleContext,
  classifyFamilyCmrFindings,
  type FamilyCmrFindingClassification,
  type FamilyModuleContext,
} from "./family/cmrClassification.js";
import { findingIdentityKey } from "./findings.js";
import {
  contractDriftStopSummary,
  infraFailureStopSummary,
  providerDegradedStopSummary,
  stopReasonForFindingDisposition,
  successStopSummary,
  type StopReason,
  type StopSummary,
} from "./stopSummary.js";
import type { Finding } from "./types.js";

export type DogfoodReplayClassification =
  | FamilyCmrFindingClassification
  | "success"
  | "infra_failure"
  | "contract_drift"
  | "provider_degraded"
  | "already_done"
  | "resumed";

export interface DogfoodReplayScenario {
  readonly id: string;
  readonly issue: number;
  readonly title: string;
  readonly classification: DogfoodReplayClassification;
  readonly stopReason: StopReason;
  readonly summary: string;
  readonly repairHint?: string;
}

export interface DogfoodReplay {
  readonly issue: 451;
  readonly parentIssue: 445;
  readonly scenarios: ReadonlyArray<DogfoodReplayScenario>;
  readonly coveredStopReasons: ReadonlyArray<StopReason>;
  readonly summary: string;
}

const BASE_FINDING: Finding = {
  severity: "high",
  category: "correctness",
  claim_quote: "historical orchestrator regression remains reproducible",
  location: "orchestrator/src/runner.ts:1",
  suggested_fix: "classify the replay through the runner/family seam",
  action: "fix_now",
};

function scenario(input: {
  readonly id: string;
  readonly issue: number;
  readonly title: string;
  readonly classification: DogfoodReplayClassification;
  readonly stopSummary: StopSummary;
}): DogfoodReplayScenario {
  return {
    id: input.id,
    issue: input.issue,
    title: input.title,
    classification: input.classification,
    stopReason: input.stopSummary.reason,
    summary: input.stopSummary.summary,
    ...(input.stopSummary.repairHint !== undefined
      ? { repairHint: input.stopSummary.repairHint }
      : {}),
  };
}

function finding(overrides: Partial<Finding>): Finding {
  return { ...BASE_FINDING, ...overrides };
}

function familyClassificationScenario(input: {
  readonly id: string;
  readonly issue: number;
  readonly title: string;
  readonly familyIssue: number;
  readonly finding: Finding;
  readonly moduleContext: FamilyModuleContext;
}): DogfoodReplayScenario {
  const classified = classifyFamilyCmrFindings({
    familyIssue: input.familyIssue,
    findings: [input.finding],
    moduleContext: input.moduleContext,
  });
  const result = classified.results[0];
  if (result === undefined) {
    throw new Error(`dogfood replay ${input.id} produced no classification`);
  }

  if (result.classification === "cross_module_defer") {
    return scenario({
      id: input.id,
      issue: input.issue,
      title: input.title,
      classification: result.classification,
      stopSummary: stopReasonForFindingDisposition({
        kind: "cross_module",
        finding: input.finding,
        targetModule: result.targetModule ?? "unknown",
        reason: result.reason,
      }),
    });
  }

  if (result.classification === "accepted_suppressed") {
    return scenario({
      id: input.id,
      issue: input.issue,
      title: input.title,
      classification: result.classification,
      stopSummary: {
        reason: "accepted_suppressed",
        summary: result.reason,
        finding: input.finding,
        metadata: {
          acceptedSuppressions: [
            {
              source: result.source ?? "unknown",
              scope: "#287 hub-loss / central C_ accounts finding only",
              reason: result.reason,
              findingIdentity: findingIdentityKey(input.finding),
              boundedReopen:
                "reopen on severity escalation, new evidence, or #287-owned local integration scope",
            },
          ],
        },
      },
    });
  }

  return scenario({
    id: input.id,
    issue: input.issue,
    title: input.title,
    classification: result.classification,
    stopSummary: stopReasonForFindingDisposition({
      kind:
        result.classification === "owning_issue_still_red"
          ? "owning_issue_still_red"
          : result.classification === "spec_conflict"
            ? "spec_conflict"
            : "same_module",
      finding: input.finding,
      owningIssue: result.owningIssue ?? `#${input.familyIssue}`,
      reason: result.reason,
    }),
  });
}

function staticScenario(input: {
  readonly id: string;
  readonly issue: number;
  readonly title: string;
  readonly classification: DogfoodReplayClassification;
  readonly stopSummary: StopSummary;
}): DogfoodReplayScenario {
  return scenario(input);
}

function uniqueSortedStopReasons(
  scenarios: ReadonlyArray<DogfoodReplayScenario>,
): ReadonlyArray<StopReason> {
  return [...new Set(scenarios.map((item) => item.stopReason))].sort();
}

export function issue451DogfoodReplay(): DogfoodReplay {
  const familyModule = {
    module: "orchestrator-family",
    moduleScope: ["orchestrator/src/family"],
    source: "family_issue" as const,
    issue: 287,
  };
  const moduleContext = buildFamilyModuleContext({
    childModules: [
      {
        module: "orchestrator-runner",
        moduleScope: ["orchestrator/src/runner.ts"],
        source: "child_issue",
        issue: 307,
      },
    ],
    familyModule,
  });
  const sameModuleFinding = finding({
    claim_quote: "same-module CMR gap was incorrectly treated as defer",
    location: "orchestrator/src/family/verifyCmr.ts:42",
    action: "defer",
    disposition: {
      kind: "cross_module",
      targetModule: "orchestrator-family",
      reason: "same module gap must stay red",
    },
  });
  const crossModuleFinding = finding({
    claim_quote: "military state machine follow-up belongs to another module",
    location: "docs/military-state-machine.md:1",
    action: "defer",
    disposition: {
      kind: "cross_module",
      targetModule: "military-state-machine",
      reason: "declared target module is outside the family module",
    },
  });
  const hubLossFinding = finding({
    severity: "medium",
    claim_quote:
      "ADR0023 D9 central transport-loss C_ accounts still wait for ADR0021 hub oracle",
    location: "docs/adr/0023.md:D9",
    action: "defer",
    disposition: {
      kind: "cross_module",
      targetModule: "hub",
      reason: "the hub implementation is outside #287",
    },
  });
  const specConflictFinding = finding({
    claim_quote: "Agent Brief contradicts the owner-authored acceptance criteria",
    location: "orchestrator/prompts/coder_implement.md:1",
    disposition: {
      kind: "spec_conflict",
      reason: "owner-authored instructions conflict and need human resolution",
    },
  });
  const infraFinding = finding({
    claim_quote: "MODULE_NOT_FOUND prevented final verification from running",
    location: "orchestrator/src/family/verifyCmr.ts:1",
    disposition: {
      kind: "infra_failure",
      reason: "runtime dependency missing",
    },
  });

  const scenarios: DogfoodReplayScenario[] = [
    staticScenario({
      id: "307-continue-fixing-after-human-answer",
      issue: 307,
      title: "owner says continue fixing and the resumed run stays in the fix loop",
      classification: "resumed",
      stopSummary: { reason: "resumed", summary: "decision answer reopened S4 at S5" },
    }),
    staticScenario({
      id: "307-local-progress-shape-changed",
      issue: 307,
      title: "finding shape changes with scoped implementation progress",
      classification: "resumed",
      stopSummary: { reason: "resumed", summary: "observable scoped progress resets only the target finding group" },
    }),
    staticScenario({
      id: "307-reviewer-text-only-change",
      issue: 307,
      title: "reviewer wording changes without implementation progress",
      classification: "spec_conflict",
      stopSummary: stopReasonForFindingDisposition({
        kind: "spec_conflict",
        finding: specConflictFinding,
        reason: "no-progress guard requires observable implementation evidence",
      }),
    }),
    staticScenario({
      id: "307-no-observable-progress",
      issue: 307,
      title: "worker claims attempted repair without scope-local diff/test/fixture movement",
      classification: "spec_conflict",
      stopSummary: stopReasonForFindingDisposition({
        kind: "spec_conflict",
        finding: specConflictFinding,
        reason: "claimed attempts alone cannot reset no-progress protection",
      }),
    }),
    staticScenario({
      id: "307-continue-fixing-targeted-reset",
      issue: 307,
      title: "continue-fixing resets only the target finding group",
      classification: "resumed",
      stopSummary: {
        reason: "resumed",
        summary: "sibling finding progress state remains intact outside the answered target group",
      },
    }),
    familyClassificationScenario({
      id: "287-same-module-cmr-gap",
      issue: 287,
      title: "same-module CMR gap remains blocking",
      familyIssue: 287,
      finding: sameModuleFinding,
      moduleContext,
    }),
    familyClassificationScenario({
      id: "287-cross-module-defer-with-module",
      issue: 287,
      title: "declared cross-module defer carries the target module",
      familyIssue: 287,
      finding: crossModuleFinding,
      moduleContext,
    }),
    staticScenario({
      id: "287-module-declaration-fenced-yaml",
      issue: 287,
      title: "module declaration is accepted only from fenced YAML or run options",
      classification: "success",
      stopSummary: successStopSummary(),
    }),
    staticScenario({
      id: "287-family-attribution-child-before-parent",
      issue: 287,
      title: "finding attribution uses child module before parent fallback",
      classification: "success",
      stopSummary: successStopSummary(),
    }),
    staticScenario({
      id: "287-correctness-r3-legacy-disposition",
      issue: 287,
      title: "legacy disposition fields do not make a converged correctness pass malformed",
      classification: "success",
      stopSummary: successStopSummary({
        heads: {
          reportedFamilyHead: "current-head",
          actualFamilyHead: "current-head",
          verifiedCmrHead: "current-head",
        },
      }),
    }),
    staticScenario({
      id: "287-correctness-final-legacy-disposition",
      issue: 287,
      title: "final correctness CMR normalizes legacy disposition into pass",
      classification: "success",
      stopSummary: successStopSummary({
        heads: {
          reportedFamilyHead: "current-head",
          actualFamilyHead: "current-head",
          verifiedCmrHead: "current-head",
        },
      }),
    }),
    staticScenario({
      id: "287-stale-family-head-current-cmr-pass",
      issue: 287,
      title: "stale reported familyHead does not override current-head CMR pass",
      classification: "success",
      stopSummary: successStopSummary({
        heads: {
          reportedFamilyHead: "4bfa5dd4",
          actualFamilyHead: "f0a72055",
          verifiedCmrHead: "f0a72055",
        },
      }),
    }),
    staticScenario({
      id: "287-coordinator-answer-reclassified",
      issue: 287,
      title: "coordinator-written escalation answer is replayed as evidence, not success",
      classification: "spec_conflict",
      stopSummary: stopReasonForFindingDisposition({
        kind: "spec_conflict",
        finding: specConflictFinding,
        reason: "peripheral coordinator answer requires fresh module/defer classification",
      }),
    }),
    familyClassificationScenario({
      id: "287-known-hub-loss-suppression",
      issue: 287,
      title: "ADR0023 hub-loss finding is accepted suppressed with bounded reopen",
      familyIssue: 287,
      finding: hubLossFinding,
      moduleContext,
    }),
    staticScenario({
      id: "376-route-accounting-non-default",
      issue: 376,
      title: "non-default route accounting uses declared route legs",
      classification: "success",
      stopSummary: successStopSummary(),
    }),
    staticScenario({
      id: "376-route-env-format-mismatch",
      issue: 376,
      title: "CMR leg env writer/reader mismatch fails closed",
      classification: "contract_drift",
      stopSummary: contractDriftStopSummary({
        summary: "CMR route env format mismatch",
        repairHint: "repair JSON-vs-CSV route env serialization before rerun",
      }),
    }),
    staticScenario({
      id: "376-route-freeze-after-import",
      issue: 376,
      title: "route is frozen at invocation even if env changes after import",
      classification: "success",
      stopSummary: successStopSummary(),
    }),
    staticScenario({
      id: "376-startup-route-tight-violation",
      issue: 376,
      title: "startup route violation is structured with repair hint",
      classification: "infra_failure",
      stopSummary: infraFailureStopSummary({
        summary: "startup route resolution failed closed",
        repairHint: "fix the active model route before dispatching workers",
      }),
    }),
    staticScenario({
      id: "376-closure-context-negative",
      issue: 376,
      title: "active or duplicate prior finding dispositions cannot pass closure",
      classification: "contract_drift",
      stopSummary: contractDriftStopSummary({
        summary: "closure contract rejected stale or duplicate dispositions",
        repairHint: "provide one verified-closed disposition per claimed finding",
      }),
    }),
    staticScenario({
      id: "376-closure-context-missing",
      issue: 376,
      title: "fresh reviewer missing prior finding context fails with structured drift",
      classification: "contract_drift",
      stopSummary: contractDriftStopSummary({
        summary: "closure_context_missing",
        repairHint: "pass current prior findings and claimed-fixed keys into S6",
      }),
    }),
    staticScenario({
      id: "376-closure-context-positive",
      issue: 376,
      title: "S6 verifies prior finding closed and lets the run continue",
      classification: "success",
      stopSummary: successStopSummary(),
    }),
    staticScenario({
      id: "376-owning-issue-still-red",
      issue: 376,
      title: "surface owned by a named child remains blocking",
      classification: "owning_issue_still_red",
      stopSummary: stopReasonForFindingDisposition({
        kind: "owning_issue_still_red",
        finding: finding({
          claim_quote: "owning child surface remains red",
          location: "orchestrator/src/family/verifyCmr.ts:376",
        }),
        owningIssue: "#376",
        reason: "owning issue still has the named surface red",
      }),
    }),
    staticScenario({
      id: "376-accepted-suppression-with-source",
      issue: 376,
      title: "accepted suppression with explicit source enters success metadata",
      classification: "accepted_suppressed",
      stopSummary: successStopSummary({
        acceptedSuppressions: [
          {
            source: "#376 owner answer",
            scope: "orchestrator route accounting",
            reason: "accepted as bounded out of scope",
            findingIdentity: "correctness|orchestrator/src/modelRoutes.ts:1|route accounting follow-up",
            boundedReopen: "reopen on scope mismatch, severity escalation, or new evidence",
          },
        ],
      }),
    }),
    staticScenario({
      id: "376-provider-degraded-nonblocking",
      issue: 376,
      title: "route-selected strong legs pass while a provider leg is degraded",
      classification: "provider_degraded",
      stopSummary: successStopSummary({
        providerDegraded: [
          {
            provider: "agy",
            leg: "agy-tight",
            reason: "provider auth unavailable",
            blocking: false,
            repairHint: "restore provider auth before requiring this leg",
          },
        ],
      }),
    }),
    staticScenario({
      id: "376-provider-degraded-blocking",
      issue: 376,
      title: "required route leg is unavailable",
      classification: "provider_degraded",
      stopSummary: providerDegradedStopSummary({
        provider: "agy",
        leg: "agy-tight",
        reason: "required route leg did not run",
        blocking: true,
        repairHint: "repair provider credentials or choose a route without that leg",
      }),
    }),
    staticScenario({
      id: "433-provider-leg-skipped-strong-leg-pass",
      issue: 433,
      title: "skipped provider leg is metadata when selected strong leg converges",
      classification: "provider_degraded",
      stopSummary: successStopSummary({
        providerDegraded: [
          {
            provider: "agy",
            leg: "agy",
            reason: "provider quota unavailable",
            blocking: false,
            repairHint: "restore provider quota before selecting this route as required",
          },
        ],
      }),
    }),
    staticScenario({
      id: "440-agent-brief-spec-conflict",
      issue: 440,
      title: "owner-authored Agent Brief conflict is classified as spec conflict",
      classification: "spec_conflict",
      stopSummary: stopReasonForFindingDisposition({
        kind: "spec_conflict",
        finding: specConflictFinding,
        reason: "Agent Brief contradicts acceptance criteria",
      }),
    }),
    staticScenario({
      id: "440-module-not-found",
      issue: 440,
      title: "MODULE_NOT_FOUND is machine repairable infrastructure failure",
      classification: "infra_failure",
      stopSummary: infraFailureStopSummary({
        summary: "MODULE_NOT_FOUND during worker startup",
        repairHint: "install or restore the missing module, then rerun",
      }),
    }),
    staticScenario({
      id: "440-coder-trust-boundary",
      issue: 440,
      title: "non-owner issue context is data-only and cannot instruct coder/fixer/ship",
      classification: "spec_conflict",
      stopSummary: stopReasonForFindingDisposition({
        kind: "spec_conflict",
        finding: specConflictFinding,
        reason: "source authentication failed for executable instructions",
      }),
    }),
    staticScenario({
      id: "440-escalation-answer-invalid",
      issue: 440,
      title: "blank, malformed, stale, or scope-mismatched answers do not unlock resume",
      classification: "spec_conflict",
      stopSummary: stopReasonForFindingDisposition({
        kind: "spec_conflict",
        finding: specConflictFinding,
        reason: "escalation answer is not executable for the paused step",
      }),
    }),
    staticScenario({
      id: "405-ship-worker-malformed-after-final-cmr",
      issue: 405,
      title: "ship worker malformed after final CMR pass does not write shipped marker",
      classification: "contract_drift",
      stopSummary: contractDriftStopSummary({
        summary: "ship worker returned no valid result after verified final CMR",
        repairHint:
          "preserve latest verified CMR head and rerun ship after repairing the worker contract",
      }),
    }),
    staticScenario({
      id: "405-module-not-found-final-verify",
      issue: 405,
      title: "final verification dependency failure is infrastructure, not product decision",
      classification: "infra_failure",
      stopSummary: stopReasonForFindingDisposition({
        kind: "infra_failure",
        finding: infraFinding,
        reason: "final verify dependency missing",
        repairHint: "restore verification dependencies and rerun final verify",
      }),
    }),
    staticScenario({
      id: "376-ship-side-review-degraded",
      issue: 376,
      title: "ship-side extra review degradation is recorded with blocking metadata",
      classification: "provider_degraded",
      stopSummary: providerDegradedStopSummary({
        provider: "ship-review",
        leg: "ship-side-review",
        reason: "sandbox/auth/provider restriction prevented extra ship review",
        blocking: false,
        repairHint: "restore ship-side review capability before making it required",
      }),
    }),
    staticScenario({
      id: "family-admission-non-runnable-child",
      issue: 451,
      title: "non-runnable child skip remains visible in family admission summary",
      classification: "owning_issue_still_red",
      stopSummary: stopReasonForFindingDisposition({
        kind: "owning_issue_still_red",
        finding: finding({
          claim_quote: "child is not ready-for-agent",
          location: "orchestrator/src/family/runner.ts:1",
        }),
        owningIssue: "#445",
        reason: "family admission skipped a non-runnable child",
      }),
    }),
    staticScenario({
      id: "family-resume-already-done-child",
      issue: 451,
      title: "already completed child is skipped during family resume",
      classification: "already_done",
      stopSummary: {
        reason: "already_done",
        summary: "family resume reused the shipped child result instead of rerunning it",
      },
    }),
  ];

  const coveredStopReasons = uniqueSortedStopReasons(scenarios);
  return {
    issue: 451,
    parentIssue: 445,
    scenarios,
    coveredStopReasons,
    summary: `${scenarios.length} dogfood replay scenarios cover ${coveredStopReasons.length} stop reasons`,
  };
}
