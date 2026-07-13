import type {
  Finding,
  FindingDisposition,
  FindingDispositionEvidence,
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
 * ADR 0030 requires a stable cross-round key. The runner uses an exact match on
 * category + location + normalized claim text; it is not semantic deduplication.
 * Wording or line-location drift therefore produces a different key and can make
 * a recurring finding appear new.
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

// No MAX_REOPEN_ATTEMPTS (owner 2026-07-13): reopen is not a capped court.
// Disagreement / severity upgrade re-enters blocking so the human decision gate
// can settle — never "budget exhausted → silently keep suppressed".

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
    reopenAttempts: disposition.reopenAttempts + 1,
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
          // UPGRADE: always reopen + block (no reopen attempt cap). Human settles
          // via findings-count / decision gate — not a budget court.
          dispositionByKey.set(
            key,
            reopenedDisposition(finding, priorSuppression),
          );
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
        dispositionByKey.set(key, reopenedDisposition(finding, priorSuppression));
      } else if (
        sameSeverity(finding, priorSuppression) &&
        (priorSuppression.disputeAttempts ?? 0) < 1
      ) {
        dispositionByKey.set(key, disputedDisposition(priorSuppression));
      } else {
        // Dispute already spent / cannot reconcile in-code → block for human
        // decision gate (owner: 意见统一不了上升裁决, not silent suppress).
        blocking.push(finding);
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

/**
 * #877: disposition prose is not a fate channel. Still-open = prior keys that
 * reappear as blocking findings (findings-count channel). Missing / duplicate /
 * still-active / accepted_suppressed disposition prose never aborts and never
 * reopens a finding that the reviewer did not re-emit in `findings[]`.
 */
export function adjudicatePriorClaimedFixedFindings(input: {
  readonly priorFindings: ReadonlyArray<Finding>;
  readonly priorIdentityKeys: ReadonlyArray<string>;
  readonly review: ReviewerOutput;
  readonly acceptedSuppressionSources?: ReadonlyArray<TrustedAcceptedSuppressionSource>;
}): PriorFindingAdjudication {
  void input.priorFindings;
  const activeFindingsByKey = new Map<string, Finding>();
  for (const finding of classifyFindings(input.review.findings, [], {
    acceptedSuppressionSources: input.acceptedSuppressionSources,
  }).blocking) {
    activeFindingsByKey.set(findingIdentityKey(finding), finding);
  }

  const stillOpen: Finding[] = [];
  const verifiedClosedIdentityKeys: string[] = [];
  for (const key of input.priorIdentityKeys) {
    const active = activeFindingsByKey.get(key);
    if (active !== undefined) {
      stillOpen.push(active);
    } else {
      verifiedClosedIdentityKeys.push(key);
    }
  }
  return { stillOpen, verifiedClosedIdentityKeys };
}
