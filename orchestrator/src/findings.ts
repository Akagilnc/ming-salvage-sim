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
 * Identity keys for a findings cargo list. Landing / fixer materialization
 * derives keys here — the runner only pass-through findings rows and routes
 * by findingsCount (ADR 0131 / #899).
 */
export function findingIdentityKeys(
  findings: ReadonlyArray<Finding>,
): string[] {
  return findings.map(findingIdentityKey);
}
