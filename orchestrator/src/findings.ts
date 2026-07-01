import type {
  Finding,
  FindingDisposition,
  FindingDispositionEvidence,
  PriorFindingDisposition,
  ReviewerOutput,
} from "./types.js";
import { isBlockingFinding } from "./validate.js";

function normalizeFindingPart(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function encodeFindingPart(value: string): string {
  return normalizeFindingPart(value)
    .replace(/\\/g, "\\\\")
    .replace(/\|/g, "\\|");
}

/**
 * Stable identity key for cross-round finding matching.
 *
 * ADR 0030 requires drift/suppression/reopen logic to recognize the same
 * finding even when a reviewer changes wording. The runner anchors identity on
 * the stable parts every reviewer must provide: category + location + normalized
 * claim text. The key is intentionally semantic-ish, not a raw object hash.
 */
export function findingIdentityKey(finding: Finding): string {
  return [
    encodeFindingPart(finding.category),
    encodeFindingPart(finding.location),
    encodeFindingPart(finding.claim_quote),
  ].join("|");
}

export interface ReviewClassification {
  readonly blocking: ReadonlyArray<Finding>;
  readonly deferred: ReadonlyArray<Finding>;
  readonly blockingIdentityKeys: ReadonlyArray<string>;
  readonly dispositions: ReadonlyArray<FindingDisposition>;
}

const SEVERITY_RANK: Readonly<Record<Finding["severity"], number>> = {
  clarity: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

const MAX_REOPEN_ATTEMPTS = 4;

function isDispositionAction(
  action: Finding["action"],
): action is "wont_fix" | "rejected" {
  return action === "wont_fix" || action === "rejected";
}

function isAcceptedSuppression(
  disposition: FindingDispositionEvidence | undefined,
): disposition is FindingDispositionEvidence & {
  readonly kind: "accepted_suppressed";
} {
  return disposition?.kind === "accepted_suppressed";
}

function isFilledString(value: string | undefined): value is string {
  return value !== undefined && value.trim().length > 0;
}

function isSourcedAcceptedSuppression(
  disposition: FindingDisposition | undefined,
): disposition is FindingDisposition & {
  readonly status: "accepted_suppressed";
  readonly source: string;
  readonly scope: string;
  readonly boundedReopen: string;
} {
  return (
    disposition?.status === "accepted_suppressed" &&
    isFilledString(disposition.source) &&
    isFilledString(disposition.scope) &&
    isFilledString(disposition.boundedReopen)
  );
}

function isMatchingAcceptedSuppression(
  finding: Finding,
  key: string,
): boolean {
  return (
    isAcceptedSuppression(finding.disposition) &&
    finding.disposition.findingIdentity === key
  );
}

function dispositionFromFinding(finding: Finding): FindingDisposition {
  const key = findingIdentityKey(finding);
  const acceptedSuppression = isMatchingAcceptedSuppression(finding, key)
    ? finding.disposition
    : undefined;
  return {
    identityKey: key,
    status:
      acceptedSuppression !== undefined
        ? "accepted_suppressed"
        : finding.action === "rejected"
          ? "rejected"
          : "wont_fix",
    reason: finding.disposition_reason ?? "",
    severity: finding.severity,
    reopenAttempts: 0,
    ...(acceptedSuppression !== undefined
      ? {
          source: acceptedSuppression.source,
          scope: acceptedSuppression.scope,
          ...(acceptedSuppression.targetModule !== undefined
            ? { targetModule: acceptedSuppression.targetModule }
            : {}),
          boundedReopen: acceptedSuppression.boundedReopen,
        }
      : {}),
  };
}

function upgradedSeverity(
  finding: Finding,
  disposition: FindingDisposition,
): boolean {
  return SEVERITY_RANK[finding.severity] > SEVERITY_RANK[disposition.severity];
}

function sameSeverity(
  finding: Finding,
  disposition: FindingDisposition,
): boolean {
  return SEVERITY_RANK[finding.severity] === SEVERITY_RANK[disposition.severity];
}

function reopenedDisposition(
  finding: Finding,
  disposition: FindingDisposition,
): FindingDisposition {
  return {
    ...disposition,
    severity: finding.severity,
    reopenAttempts: Math.min(
      MAX_REOPEN_ATTEMPTS,
      disposition.reopenAttempts + 1,
    ),
  };
}

function disputedDisposition(disposition: FindingDisposition): FindingDisposition {
  return {
    ...disposition,
    disputeAttempts: (disposition.disputeAttempts ?? 0) + 1,
  };
}

function isAllowedCrossModuleDefer(finding: Finding): boolean {
  return (
    finding.action === "defer" &&
    finding.disposition?.kind === "cross_module" &&
    finding.disposition.targetModule !== undefined &&
    finding.disposition.targetModule.trim().length > 0 &&
    finding.disposition.reason.trim().length > 0
  );
}

function isBlockingByDisposition(finding: Finding): boolean {
  if (isBlockingFinding(finding)) return true;
  if (finding.action !== "defer") return false;
  return !isAllowedCrossModuleDefer(finding);
}

export function classifyFindings(
  findings: ReadonlyArray<Finding>,
  priorDispositions: ReadonlyArray<FindingDisposition> = [],
): ReviewClassification {
  const dispositionByKey = new Map<string, FindingDisposition>(
    priorDispositions.map((disposition) => [
      disposition.identityKey,
      disposition,
    ]),
  );
  const blocking: Finding[] = [];
  const deferred: Finding[] = [];

  for (const finding of findings) {
    const key = findingIdentityKey(finding);
    const priorDisposition = dispositionByKey.get(key);
    const priorSuppression = isSourcedAcceptedSuppression(priorDisposition)
      ? priorDisposition
      : undefined;
    if (isDispositionAction(finding.action) && !isBlockingFinding(finding)) {
      if (!isMatchingAcceptedSuppression(finding, key)) {
        blocking.push(finding);
        continue;
      }
      dispositionByKey.set(key, dispositionFromFinding(finding));
      continue;
    }
    if (priorSuppression !== undefined) {
      if (upgradedSeverity(finding, priorSuppression)) {
        if (priorSuppression.reopenAttempts < MAX_REOPEN_ATTEMPTS) {
          dispositionByKey.set(key, reopenedDisposition(finding, priorSuppression));
        }
      } else if (
        sameSeverity(finding, priorSuppression) &&
        (priorSuppression.disputeAttempts ?? 0) < 1
      ) {
        dispositionByKey.set(key, disputedDisposition(priorSuppression));
      } else {
        continue;
      }
    }
    if (isBlockingByDisposition(finding)) {
      blocking.push(finding);
    } else {
      deferred.push(finding);
    }
  }
  return {
    blocking,
    deferred,
    blockingIdentityKeys: blocking.map(findingIdentityKey),
    dispositions: [...dispositionByKey.values()],
  };
}

export interface PriorFindingAdjudication {
  readonly stillOpen: ReadonlyArray<Finding>;
  readonly verifiedClosedIdentityKeys: ReadonlyArray<string>;
}

export function adjudicatePriorClaimedFixedFindings(input: {
  readonly priorFindings: ReadonlyArray<Finding>;
  readonly priorIdentityKeys: ReadonlyArray<string>;
  readonly review: ReviewerOutput;
}): PriorFindingAdjudication {
  if (input.priorFindings.length !== input.priorIdentityKeys.length) {
    throw new Error(
      `prior claimed-fixed finding/key count mismatch: ` +
        `${input.priorFindings.length} findings for ${input.priorIdentityKeys.length} keys`,
    );
  }
  const dispositionByKey = new Map<string, PriorFindingDisposition>();
  for (const disposition of input.review.priorFindingDispositions ?? []) {
    if (dispositionByKey.has(disposition.identityKey)) {
      throw new Error(
        `reviewer provided duplicate prior finding disposition for ${disposition.identityKey}`,
      );
    }
    dispositionByKey.set(disposition.identityKey, disposition);
  }

  const priorByKey = new Map<string, Finding>();
  input.priorFindings.forEach((finding, index) => {
    const key = input.priorIdentityKeys[index] ?? findingIdentityKey(finding);
    priorByKey.set(key, finding);
  });

  const activeFindingsByKey = new Map<string, Finding>();
  for (const finding of classifyFindings(input.review.findings).blocking) {
    activeFindingsByKey.set(findingIdentityKey(finding), finding);
  }

  const stillOpen: Finding[] = [];
  const verifiedClosedIdentityKeys: string[] = [];
  for (const key of input.priorIdentityKeys) {
    const disposition = dispositionByKey.get(key);
    if (disposition === undefined) {
      throw new Error(
        `reviewer omitted required disposition for prior claimed-fixed finding ${key}`,
      );
    }
    if (disposition.status === "verified-closed") {
      verifiedClosedIdentityKeys.push(key);
      continue;
    }
    const finding = activeFindingsByKey.get(key) ?? priorByKey.get(key);
    if (finding === undefined) {
      throw new Error(
        `reviewer marked prior claimed-fixed finding ${key} still-active, but no active or prior finding payload exists`,
      );
    }
    stillOpen.push(finding);
  }
  return { stillOpen, verifiedClosedIdentityKeys };
}
