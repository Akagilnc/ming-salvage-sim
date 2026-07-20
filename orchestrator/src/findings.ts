import type { Finding } from "./types.js";

function normalizeFindingPart(value: unknown, fieldName: string): string {
  if (typeof value !== "string") {
    throw new Error(
      `findingIdentityKey: ${fieldName} must be a string (got ${
        value === null ? "null" : typeof value
      })`,
    );
  }
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

function encodeFindingPart(value: unknown, fieldName: string): string {
  return normalizeFindingPart(value, fieldName)
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
  // #1076 L2 / ADR 0131: topology must not re-derive identity from sparse
  // cargo prose. When a finding carries a pre-computed identityKey, use it
  // verbatim instead of recomputing from category/location/claim_quote
  // (which crashes on sparse cargo — undefined .trim() TypeError).
  const explicit = (finding as { identityKey?: unknown }).identityKey;
  if (typeof explicit === "string" && explicit.length > 0) {
    return explicit;
  }
  return [
    encodeFindingPart(finding.category, "category"),
    encodeFindingPart(finding.location, "location"),
    encodeFindingPart(finding.claim_quote, "claim_quote"),
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
