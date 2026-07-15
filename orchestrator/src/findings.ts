import type { Finding } from "./types.js";

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

/**
 * Identity keys for a findings cargo list. Landing / envelope consumers derive
 * keys here — the runner must not re-shape cargo or invent a second court
 * (ADR 0131 / #899).
 */
export function findingIdentityKeys(
  findings: ReadonlyArray<Finding>,
): string[] {
  return findings.map(findingIdentityKey);
}

/**
 * Pass-through of typed reviewer findings cargo for the fixer landing.
 * Shape tolerance for untyped raw receipts belongs at the decode boundary
 * ({@link decodeReviewerOpenCountReceipt}), not in the runner.
 */
export function fixLandingFromReviewerFindings(
  findings: ReadonlyArray<Finding>,
): {
  readonly findings: Finding[];
  readonly identityKeys: string[];
} {
  const rows = [...findings];
  return {
    findings: rows,
    identityKeys: findingIdentityKeys(rows),
  };
}
