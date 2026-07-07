import type {
  Finding,
  FindingDisposition,
  FindingDispositionEvidence,
  PriorFindingDisposition,
  ReviewerOutput,
} from "./types.js";
import { hasAcceptedSuppressionAuthority } from "./acceptedSuppression.js";
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

export interface TrustedAcceptedSuppressionSource {
  readonly source: string;
  readonly scope: string;
  readonly reason: string;
  readonly findingIdentity: string;
  readonly boundedReopen: string;
}

export interface ReviewClassificationOptions {
  readonly acceptedSuppressionSources?: ReadonlyArray<TrustedAcceptedSuppressionSource>;
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

function isSourcedAcceptedSuppression(
  disposition: FindingDisposition | undefined,
  trustedSources: ReadonlyArray<TrustedAcceptedSuppressionSource>,
): disposition is FindingDisposition & {
  readonly status: "accepted_suppressed";
  readonly source: string;
  readonly scope: string;
  readonly boundedReopen: string;
} {
  return (
    disposition?.status === "accepted_suppressed" &&
    hasAcceptedSuppressionAuthority(disposition) &&
    trustedSources.some(
      (source) =>
        source.source === disposition.source &&
        source.scope === disposition.scope &&
        source.reason === disposition.reason &&
        source.findingIdentity === disposition.identityKey &&
        source.boundedReopen === disposition.boundedReopen,
    )
  );
}

function isMatchingAcceptedSuppression(
  finding: Finding,
  key: string,
  trustedSources: ReadonlyArray<TrustedAcceptedSuppressionSource>,
): boolean {
  if (!isAcceptedSuppression(finding.disposition)) return false;
  const identity = finding.disposition.findingIdentity ?? key;
  if (identity !== key || !hasAcceptedSuppressionAuthority(finding.disposition)) {
    return false;
  }
  return trustedSources.some(
    (source) =>
      source.source === finding.disposition?.source &&
      source.scope === finding.disposition.scope &&
      source.reason === finding.disposition.reason &&
      source.findingIdentity === identity &&
      source.boundedReopen === finding.disposition.boundedReopen,
  );
}

function dispositionFromFinding(
  finding: Finding,
  trustedSources: ReadonlyArray<TrustedAcceptedSuppressionSource>,
): FindingDisposition {
  const key = findingIdentityKey(finding);
  const acceptedSuppression = isMatchingAcceptedSuppression(
    finding,
    key,
    trustedSources,
  )
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
    reason: acceptedSuppression?.reason ?? finding.disposition_reason ?? "",
    severity: finding.severity,
    reopenAttempts: 0,
    ...(acceptedSuppression !== undefined
      ? {
          source: acceptedSuppression.source,
          scope: acceptedSuppression.scope,
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

function isBlockingByDisposition(finding: Finding): boolean {
  if (isBlockingFinding(finding)) return true;
  // #604 correctness r1 (P1-c) / ADR 0062: any non-suppression finding that
  // reaches this predicate is blocking — routing disposition kinds are gone, so
  // there is no免修 disposition left. This covers a reopened/disputed
  // `wont_fix`/`rejected` that fell through the accepted-suppression branch
  // (suppression失配 / dispute exhausted). Only a MATCHING accepted suppression
  // is suppressed, and that is handled上游 (it never reaches here). The `deferred`
  // bucket is retained by the return shape but is now PROVABLY always empty.
  return true;
}

export function classifyFindings(
  findings: ReadonlyArray<Finding>,
  priorDispositions: ReadonlyArray<FindingDisposition> = [],
  options: ReviewClassificationOptions = {},
): ReviewClassification {
  const trustedSources = options.acceptedSuppressionSources ?? [];
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
    const priorSuppression = isSourcedAcceptedSuppression(
      priorDisposition,
      trustedSources,
    )
      ? priorDisposition
      : undefined;
    if (isDispositionAction(finding.action) && !isBlockingFinding(finding)) {
      // #604 correctness r4 (D4): the disposition-action (wont_fix/rejected)
      // MAINTAIN/UPGRADE branch is gated by `!isBlockingFinding` ONLY. The
      // bf0fcfc6 `|| priorSuppression !== undefined` widening was DEAD CODE: a
      // finding only enters here when its action is wont_fix/rejected AND it is
      // non-blocking (medium/low). The widening only changed behavior for a
      // high/critical finding with a wont_fix/rejected action — but that shape is
      // PRODUCTION-UNREACHABLE: the upstream validate.ts / zod / Python guards
      // reject `severity ∈ {critical,high}` unless `action === "fix_now"`, and an
      // `accepted_suppressed` disposition is valid only on wont_fix/rejected. So a
      // high/critical finding can never be validly suppressed and can never take a
      // maintenance action; `priorSuppression` (derived from a prior sourced
      // accepted_suppression) is therefore never high/critical either. The
      // widening added a branch for an impossible payload and desynced the
      // classifier from the upstream invariant. Reverted here. A high/critical
      // finding stays out of this branch and blocks via the general path
      // (fresh-high cannot self-waive; an upgrade to high blocks with a recorded
      // reopen).
      if (!isMatchingAcceptedSuppression(finding, key, trustedSources)) {
        blocking.push(finding);
        continue;
      }
      // #604 rework per ADR 0030 (user定论 2026-07-06). A matching accepted
      // suppression that maintains an existing sourced suppression must NEVER
      // rewrite governance state, and an UPGRADE must BLOCK rather than be
      // silently dropped.
      if (priorSuppression !== undefined) {
        if (upgradedSeverity(finding, priorSuppression)) {
          // UPGRADE (severity升级): record the reopen (capped) AND BLOCK. The
          // higher severity is not covered by the waiver. Both the
          // budget-available and budget-exhausted subcases block — the old code
          // recorded a reopen then `continue`d, silently dropping the upgraded
          // finding (and dropping it entirely once the budget was exhausted).
          if (priorSuppression.reopenAttempts < MAX_REOPEN_ATTEMPTS) {
            dispositionByKey.set(
              key,
              reopenedDisposition(finding, priorSuppression),
            );
          }
          blocking.push(finding);
          continue;
        }
        // MAINTAIN (same OR lower severity, a maintenance action): ZERO-OP on
        // the disposition. Do NOT spend disputeAttempts, do NOT refresh severity,
        // do NOT刷回 a downgrade to the lower severity / reset budgets (ADR 0030
        // "降级…不刷回"). Keep the prior EXACTLY as-is and stay suppressed. The
        // "维持花预算" semantic that r1 P1-d introduced was a non-ratified
        // implementation drift that violated ADR 0030; it is rolled back here.
        // Only a real fix_now challenge (the general branch below) spends the
        // single bounded dispute budget (#369 PRESERVED).
        continue;
      }
      dispositionByKey.set(key, dispositionFromFinding(finding, trustedSources));
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
  readonly acceptedSuppressionSources?: ReadonlyArray<TrustedAcceptedSuppressionSource>;
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
  for (const finding of classifyFindings(input.review.findings, [], {
    acceptedSuppressionSources: input.acceptedSuppressionSources,
  }).blocking) {
    activeFindingsByKey.set(findingIdentityKey(finding), finding);
  }

  const stillOpen: Finding[] = [];
  const verifiedClosedIdentityKeys: string[] = [];
  for (const key of input.priorIdentityKeys) {
    const disposition = dispositionByKey.get(key);
    const priorFinding = priorByKey.get(key);
    if (disposition === undefined) {
      throw new Error(
        `reviewer omitted required disposition for prior claimed-fixed finding ${key}`,
      );
    }
    if (
      disposition.status === "verified-closed" ||
      (disposition.status === "accepted_suppressed" &&
        isSourcedAcceptedSuppression(
          {
            identityKey: disposition.identityKey,
            status: disposition.status,
            reason: disposition.reason ?? "",
            severity: priorFinding?.severity ?? "medium",
            reopenAttempts: 0,
            source: disposition.source,
            scope: disposition.scope,
            boundedReopen: disposition.boundedReopen,
          },
          input.acceptedSuppressionSources ?? [],
        ) &&
        priorFinding !== undefined &&
        priorFinding.severity !== "critical" &&
        priorFinding.severity !== "high")
    ) {
      verifiedClosedIdentityKeys.push(key);
      continue;
    }
    const finding = activeFindingsByKey.get(key) ?? priorFinding;
    if (finding === undefined) {
      throw new Error(
        `reviewer marked prior claimed-fixed finding ${key} still-active, but no active or prior finding payload exists`,
      );
    }
    stillOpen.push(finding);
  }
  return { stillOpen, verifiedClosedIdentityKeys };
}
