import type { Finding } from "./types.js";
import { isBlockingFinding } from "./validate.js";

function normalizeFindingPart(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
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
    normalizeFindingPart(finding.category),
    normalizeFindingPart(finding.location),
    normalizeFindingPart(finding.claim_quote),
  ].join("|");
}

export interface ReviewClassification {
  readonly blocking: ReadonlyArray<Finding>;
  readonly deferred: ReadonlyArray<Finding>;
  readonly blockingIdentityKeys: ReadonlyArray<string>;
}

export function classifyFindings(
  findings: ReadonlyArray<Finding>,
): ReviewClassification {
  const blocking = findings.filter(isBlockingFinding);
  const deferred = findings.filter((finding) => !isBlockingFinding(finding));
  return {
    blocking,
    deferred,
    blockingIdentityKeys: blocking.map(findingIdentityKey),
  };
}
