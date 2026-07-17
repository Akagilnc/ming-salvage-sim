import type { FamilyStageFailureStatus } from "./family/familyTerminal.js";

export type StopReason =
  | "success"
  | "same_module_still_red"
  | "owning_issue_still_red"
  | "accepted_suppressed"
  | "spec_conflict"
  | "cross_module_defer"
  | "infra_failure"
  // B-class: a HUMAN DECISION GATE parked the run awaiting an answer (#604 F2,
  // ADR 0062 A/B分家). Distinct from `infra_failure` (A-class真失败): a decision
  // park is answerable + resumable in place, not a failure to repair.
  | "decision_gate_park"
  | "provider_degraded"
  | "contract_drift"
  | "already_done"
  | "resumed"
  // #922/#942 — stage diagnostics for stopSummary.reason only (not public
  // FamilyRunStatus). Public ABI is completed|parked|failed (ID-001).
  // Derived from canonical FAMILY_STAGE_FAILURE_STATUSES — do not re-list.
  | FamilyStageFailureStatus;

export interface StopSummary {
  readonly reason: StopReason;
  readonly summary: string;
  readonly repairHint?: string;
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

/**
 * B-class stop summary: a HUMAN DECISION GATE parked the run (#604 F2, ADR 0062
 * A/B分家). Semantically a PARK awaiting an answer — resumable in place — NOT an
 * A-class infra failure to repair. Kept a separate constructor so decision-gate
 * parks never reuse the `infra_failure` reason/word.
 */
export function decisionGateParkStopSummary(input: {
  readonly summary: string;
  readonly repairHint: string;
  readonly heads?: HeadFreshnessSummary;
}): StopSummary {
  return {
    reason: "decision_gate_park",
    summary: input.summary,
    repairHint: input.repairHint,
    ...(input.heads !== undefined ? { metadata: { heads: input.heads } } : {}),
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
