import type { Finding, FindingDispositionEvidence } from "./types.js";

export type StopReason =
  | "success"
  | "same_module_still_red"
  | "owning_issue_still_red"
  | "accepted_suppressed"
  | "spec_conflict"
  | "cross_module_defer"
  | "infra_failure"
  | "provider_degraded"
  | "contract_drift"
  | "already_done"
  | "resumed";

export interface StopSummary {
  readonly reason: StopReason;
  readonly summary: string;
  readonly repairHint?: string;
  readonly finding?: Finding;
  readonly targetModule?: string;
  readonly owningIssue?: string;
  readonly metadata?: StopSummaryMetadata;
}

export interface StopSummaryMetadata {
  readonly acceptedSuppressions?: ReadonlyArray<AcceptedSuppressionSummary>;
  readonly providerDegraded?: ReadonlyArray<ProviderDegradationSummary>;
  readonly heads?: HeadFreshnessSummary;
  readonly ship?: ShipFailureSummary;
  readonly admissionSkipped?: ReadonlyArray<AdmissionSkippedSummary>;
  readonly alreadyDone?: ReadonlyArray<AlreadyDoneSummary>;
}

export interface AcceptedSuppressionSummary {
  readonly source: string;
  readonly scope: string;
  readonly reason: string;
  readonly findingIdentity: string;
  readonly boundedReopen: string;
}

export interface ProviderDegradationSummary {
  readonly provider?: string;
  readonly leg?: string;
  readonly reason: string;
  readonly blocking: boolean;
  readonly repairHint?: string;
}

export interface HeadFreshnessSummary {
  readonly reportedFamilyHead?: string;
  readonly actualFamilyHead?: string;
  readonly verifiedCmrHead?: string;
  readonly sources?: Readonly<Record<string, string>>;
}

export interface ShipFailureSummary {
  readonly latestVerifiedCmrHead?: string;
  readonly currentFamilyHead?: string;
  readonly reportedFamilyHead?: string;
  readonly shipPrState?: string;
}

export interface AdmissionSkippedSummary {
  readonly issue: number;
  readonly reason: string;
  readonly message: string;
}

export interface AlreadyDoneSummary {
  readonly issue: number;
  readonly status: "merged" | "shipped" | "completed";
  readonly source: string;
}

export type FindingDispositionStopInput =
  | {
      readonly kind: "same_module";
      readonly finding: Finding;
      readonly reason?: string;
    }
  | {
      readonly kind: "owning_issue_still_red";
      readonly finding: Finding;
      readonly owningIssue: string;
      readonly reason?: string;
    }
  | {
      readonly kind: "cross_module";
      readonly finding: Finding;
      readonly targetModule: string;
      readonly reason: string;
    }
  | {
      readonly kind: "spec_conflict";
      readonly finding: Finding;
      readonly reason: string;
      readonly repairHint?: string;
    }
  | {
      readonly kind: "infra_failure";
      readonly finding: Finding;
      readonly reason: string;
      readonly repairHint: string;
    };

export function stopReasonForFindingDisposition(
  input: FindingDispositionStopInput,
): StopSummary {
  switch (input.kind) {
    case "same_module":
      return {
        reason: "same_module_still_red",
        summary: input.reason ?? "same-module finding is still red",
        finding: input.finding,
      };
    case "owning_issue_still_red":
      return {
        reason: "owning_issue_still_red",
        summary: input.reason ?? "owning issue has not closed the required surface",
        finding: input.finding,
        owningIssue: input.owningIssue,
      };
    case "cross_module":
      return {
        reason: "cross_module_defer",
        summary: input.reason,
        finding: input.finding,
        targetModule: input.targetModule,
      };
    case "spec_conflict":
      return {
        reason: "spec_conflict",
        summary: input.reason,
        finding: input.finding,
        repairHint: input.repairHint ?? "resolve the specification conflict and rerun",
      };
    case "infra_failure":
      return {
        reason: "infra_failure",
        summary: input.reason,
        finding: input.finding,
        repairHint: input.repairHint,
      };
  }
}

export function successStopSummary(input?: {
  readonly acceptedSuppressions?: ReadonlyArray<AcceptedSuppressionSummary>;
  readonly providerDegraded?: ReadonlyArray<ProviderDegradationSummary>;
  readonly heads?: HeadFreshnessSummary;
  readonly admissionSkipped?: ReadonlyArray<AdmissionSkippedSummary>;
  readonly alreadyDone?: ReadonlyArray<AlreadyDoneSummary>;
}): StopSummary {
  return {
    reason: "success",
    summary: "run completed successfully",
    ...(input !== undefined
      ? {
          metadata: {
            ...(input.acceptedSuppressions !== undefined
              ? { acceptedSuppressions: input.acceptedSuppressions }
              : {}),
            ...(input.providerDegraded !== undefined
              ? { providerDegraded: input.providerDegraded }
              : {}),
            ...(input.heads !== undefined ? { heads: input.heads } : {}),
            ...(input.admissionSkipped !== undefined
              ? { admissionSkipped: input.admissionSkipped }
              : {}),
            ...(input.alreadyDone !== undefined
              ? { alreadyDone: input.alreadyDone }
              : {}),
          },
        }
      : {}),
  };
}

export function sourceAuthFailureStopSummary(input: {
  readonly instructionKind: string;
  readonly rejectedAuthor: string;
  readonly trustedAuthor: string;
  readonly sourceKind: string;
}): StopSummary {
  return {
    reason: "spec_conflict",
    summary: `${input.sourceKind} by ${input.rejectedAuthor} is not an authenticated executable ${input.instructionKind} source`,
    repairHint:
      "move executable instructions into a repo-owner-authored Agent Brief, accepted issue body, ADR, or runner Agent Brief, then rerun",
  };
}

export function stopSummaryFromFindingDispositionEvidence(input: {
  readonly finding: Finding;
  readonly evidence: FindingDispositionEvidence;
}): StopSummary {
  const { finding, evidence } = input;
  switch (evidence.kind) {
    case "same_module":
      return stopReasonForFindingDisposition({
        kind: "same_module",
        finding,
        reason: evidence.reason,
      });
    case "owning_issue_still_red":
      return stopReasonForFindingDisposition({
        kind: "owning_issue_still_red",
        finding,
        owningIssue: evidence.owningIssue ?? "unknown",
        reason: evidence.reason,
      });
    case "cross_module":
      return stopReasonForFindingDisposition({
        kind: "cross_module",
        finding,
        targetModule: evidence.targetModule ?? "unknown",
        reason: evidence.reason,
      });
    case "spec_conflict":
      return stopReasonForFindingDisposition({
        kind: "spec_conflict",
        finding,
        reason: evidence.reason,
      });
    case "infra_failure":
      return stopReasonForFindingDisposition({
        kind: "infra_failure",
        finding,
        reason: evidence.reason,
        repairHint: "repair the infrastructure failure and rerun",
      });
    case "accepted_suppressed":
      return {
        reason: "accepted_suppressed",
        summary: evidence.reason,
        finding,
        metadata: {
          acceptedSuppressions: [
            {
              source: evidence.source ?? "unknown",
              scope: evidence.scope ?? "unknown",
              reason: evidence.reason,
              findingIdentity: evidence.findingIdentity ?? "unknown",
              boundedReopen: evidence.boundedReopen ?? "unknown",
            },
          ],
        },
      };
  }
}

export function infraFailureStopSummary(input: {
  readonly summary: string;
  readonly repairHint: string;
  readonly ship?: ShipFailureSummary;
  readonly heads?: HeadFreshnessSummary;
}): StopSummary {
  return {
    reason: "infra_failure",
    summary: input.summary,
    repairHint: input.repairHint,
    ...(input.ship !== undefined || input.heads !== undefined
      ? {
          metadata: {
            ...(input.ship !== undefined ? { ship: input.ship } : {}),
            ...(input.heads !== undefined ? { heads: input.heads } : {}),
          },
        }
      : {}),
  };
}

export function contractDriftStopSummary(input: {
  readonly summary: string;
  readonly repairHint: string;
  readonly ship?: ShipFailureSummary;
  readonly heads?: HeadFreshnessSummary;
}): StopSummary {
  return {
    reason: "contract_drift",
    summary: input.summary,
    repairHint: input.repairHint,
    ...(input.ship !== undefined || input.heads !== undefined
      ? {
          metadata: {
            ...(input.ship !== undefined ? { ship: input.ship } : {}),
            ...(input.heads !== undefined ? { heads: input.heads } : {}),
          },
        }
      : {}),
  };
}

export function providerDegradedStopSummary(input: {
  readonly provider?: string;
  readonly leg?: string;
  readonly reason: string;
  readonly blocking: boolean;
  readonly repairHint?: string;
}): StopSummary {
  const degradation: ProviderDegradationSummary = {
    reason: input.reason,
    blocking: input.blocking,
    ...(input.provider !== undefined ? { provider: input.provider } : {}),
    ...(input.leg !== undefined ? { leg: input.leg } : {}),
    ...(input.repairHint !== undefined ? { repairHint: input.repairHint } : {}),
  };
  if (!input.blocking) {
    return successStopSummary({ providerDegraded: [degradation] });
  }
  return {
    reason: "provider_degraded",
    summary: input.reason,
    repairHint: input.repairHint ?? "restore the required provider leg and rerun",
    metadata: { providerDegraded: [degradation] },
  };
}
