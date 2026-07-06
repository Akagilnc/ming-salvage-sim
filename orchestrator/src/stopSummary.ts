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
  // B-class: a HUMAN DECISION GATE parked the run awaiting an answer (#604 F2,
  // ADR 0062 A/B分家). Distinct from `infra_failure` (A-class真失败): a decision
  // park is answerable + resumable in place, not a failure to repair.
  | "decision_gate_park"
  | "provider_degraded"
  | "contract_drift"
  | "already_done"
  | "resumed";

/**
 * Thin typed description of a finding for persistence on a ledger/StopSummary
 * (#604 F5, 信封宪法 ADR 0062). A StopSummary is a persisted run-terminus record;
 * it must carry only the finding's IDENTITY (identityKey), SEVERITY, and a short
 * human summary — never the full {@link Finding} rich content (claim_quote /
 * suggested_fix / disposition evidence). The rich Finding travels only in the
 * live coder-fix landing payload (see verifyCmr `{ blockingFindings }`), never
 * into the ledger. Keeps the persisted structure thin so rich reviewer content
 * cannot leak back into durable state.
 */
export interface FindingDescriptor {
  readonly identityKey: string;
  readonly severity: Finding["severity"];
  readonly summary: string;
}

export function findingDescriptor(finding: Finding, summary?: string): FindingDescriptor {
  return {
    identityKey: findingIdentityKey(finding),
    severity: finding.severity,
    summary: summary ?? finding.claim_quote,
  };
}

export interface StopSummary {
  readonly reason: StopReason;
  readonly summary: string;
  readonly repairHint?: string;
  /**
   * Thin typed descriptor of the finding that drove this stop — identity +
   * severity + summary only. NOT the full {@link Finding} (#604 F5, ADR 0062):
   * rich finding content must not be persisted on the ledger; it travels in the
   * live coder-fix landing payload instead.
   */
  readonly findingDescriptor?: FindingDescriptor;
  // #604 correctness r2 (C4): targetModule/owningIssue/missingSurface/nextStep
  // were only ever set by the removed dead route-kind branches of
  // stopReasonForFindingDisposition — no producer sets them and no consumer
  // reads them off a StopSummary. Removed with the dead branches (ADR 0062).
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

// #604 correctness r2 (C4) / ADR 0062: the routing disposition kinds
// (owning_issue_still_red / cross_module / spec_conflict / infra_failure) were
// deleted from the reviewer contract — the runner is a pure scheduler that
// counts blocking findings, it does not read a route kind. The only live caller
// (verifyCmr.ts) passes `same_module`, so those four input branches were
// unreachable dead code (with their derived StopSummary fields
// targetModule/owningIssue/missingSurface/nextStep). They are removed here. The
// `StopReason` union keeps its reserved runner terminal-state words unchanged.
export type FindingDispositionStopInput = {
  readonly kind: "same_module";
  readonly finding: Finding;
  readonly reason?: string;
};

export function stopReasonForFindingDisposition(
  input: FindingDispositionStopInput,
): StopSummary {
  const summary = input.reason ?? "same-module finding is still red";
  return {
    reason: "same_module_still_red",
    summary,
    findingDescriptor: findingDescriptor(input.finding, summary),
  };
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
  // #604 slice 4 (ADR 0062): the only reviewer-emitted disposition kind is
  // accepted_suppressed — the routing kinds were removed from the contract.
  switch (evidence.kind) {
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
        findingDescriptor: findingDescriptor(finding, evidence.reason),
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
