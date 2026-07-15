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
 * Identity keys for a findings cargo list. Derived at landing
 * (`dispatchWorker` / fixer materialization) — not by the single-slice runner
 * court. Main S3/S6 topology reads judge status enum only (ADR 0131 channel (b)
 * / #925); findings rows remain opaque cargo.
 */
export function findingIdentityKeys(
  findings: ReadonlyArray<Finding>,
): string[] {
  return findings.map(findingIdentityKey);
}
