import type { Finding, FindingDispositionEvidence } from "./types.js";
import { findingIdentityKey } from "./findings.js";

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
  readonly missingSurface?: string;
  readonly nextStep?: string;
  readonly metadata?: StopSummaryMetadata;
}

export interface StopSummaryMetadata {
  readonly acceptedSuppressions?: ReadonlyArray<AcceptedSuppressionSummary>;
  readonly providerDegraded?: ReadonlyArray<ProviderDegradationSummary>;
  readonly routeAccounting?: RouteAccountingSummary;
  readonly heads?: HeadFreshnessSummary;
  readonly ship?: ShipFailureSummary;
  readonly admissionSkipped?: ReadonlyArray<AdmissionSkippedSummary>;
  readonly alreadyDone?: ReadonlyArray<AlreadyDoneSummary>;
  readonly trustBoundary?: TrustBoundarySummary;
  readonly trackedStatus?: ReadonlyArray<string>;
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

export interface RouteAccountingSummary {
  readonly declaredLegs: ReadonlyArray<string>;
  readonly successfulLegs: ReadonlyArray<string>;
  readonly skippedLegs: ReadonlyArray<{ readonly slug: string; readonly reason: string }>;
  readonly routeFingerprint: string;
  readonly routeArtifact?: {
    readonly path: string;
    readonly content: unknown;
  };
  readonly actualPayload?: {
    readonly successfulLegs: ReadonlyArray<string>;
    readonly skippedLegs?: ReadonlyArray<{ readonly slug: string; readonly reason: string }>;
  };
  readonly repairHint: string;
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

export interface TrustBoundarySummary {
  readonly stage: string;
  readonly failureClass: "source_auth_failure";
  readonly instructionKind: string;
  readonly rejectedAuthor: string;
  readonly trustedAuthor: string;
  readonly sourceKind: string;
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
      readonly missingSurface?: string;
      readonly nextStep?: string;
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
        ...(input.missingSurface !== undefined
          ? { missingSurface: input.missingSurface }
          : {}),
        ...(input.nextStep !== undefined ? { nextStep: input.nextStep } : {}),
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
    metadata: {
      trustBoundary: {
        stage: "S1",
        failureClass: "source_auth_failure",
        instructionKind: input.instructionKind,
        rejectedAuthor: input.rejectedAuthor,
        trustedAuthor: input.trustedAuthor,
        sourceKind: input.sourceKind,
      },
    },
  };
}

export function stopSummaryFromFindingDispositionEvidence(input: {
  readonly finding: Finding;
  readonly evidence: FindingDispositionEvidence;
}): StopSummary {
  const { finding, evidence } = input;
  const requireField = (
    value: string | undefined,
    field: string,
    kind: string,
  ): string => {
    if (value == null || value.trim() === "") {
      throw new Error(`${kind} disposition evidence requires ${field}`);
    }
    return value;
  };
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
        owningIssue: requireField(
          evidence.owningIssue,
          "owningIssue",
          evidence.kind,
        ),
        missingSurface: evidence.missingSurface,
        nextStep: evidence.nextStep,
        reason: evidence.reason,
      });
    case "cross_module":
      return stopReasonForFindingDisposition({
        kind: "cross_module",
        finding,
        targetModule: requireField(
          evidence.targetModule,
          "targetModule",
          evidence.kind,
        ),
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
      {
        const missing = [
          evidence.source == null || evidence.source.trim() === ""
            ? "source"
            : undefined,
          evidence.scope == null || evidence.scope.trim() === ""
            ? "scope"
            : undefined,
          evidence.boundedReopen == null || evidence.boundedReopen.trim() === ""
            ? "boundedReopen"
            : undefined,
        ].filter((field): field is string => field !== undefined);
        if (missing.length > 0) {
          throw new Error(
            `accepted_suppressed disposition evidence requires ${missing.join(", ")}`,
          );
        }
      }
      return {
        reason: "accepted_suppressed",
        summary: evidence.reason,
        finding,
        metadata: {
          acceptedSuppressions: [
            {
              source: requireField(evidence.source, "source", evidence.kind),
              scope: requireField(evidence.scope, "scope", evidence.kind),
              reason: evidence.reason,
              findingIdentity: evidence.findingIdentity ?? findingIdentityKey(finding),
              boundedReopen: requireField(
                evidence.boundedReopen,
                "boundedReopen",
                evidence.kind,
              ),
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
  readonly routeAccounting?: RouteAccountingSummary;
}): StopSummary {
  return {
    reason: "infra_failure",
    summary: input.summary,
    repairHint: input.repairHint,
    ...(input.ship !== undefined ||
    input.heads !== undefined ||
    input.routeAccounting !== undefined
      ? {
          metadata: {
            ...(input.ship !== undefined ? { ship: input.ship } : {}),
            ...(input.heads !== undefined ? { heads: input.heads } : {}),
            ...(input.routeAccounting !== undefined
              ? { routeAccounting: input.routeAccounting }
              : {}),
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
  readonly metadata?: StopSummaryMetadata;
}): StopSummary {
  const metadata = {
    ...(input.metadata ?? {}),
    ...(input.ship !== undefined ? { ship: input.ship } : {}),
    ...(input.heads !== undefined ? { heads: input.heads } : {}),
  };
  return {
    reason: "contract_drift",
    summary: input.summary,
    repairHint: input.repairHint,
    ...(Object.keys(metadata).length > 0 ? { metadata } : {}),
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
