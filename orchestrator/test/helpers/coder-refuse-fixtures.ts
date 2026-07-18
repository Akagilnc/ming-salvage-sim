/**
 * #927 test fixtures for four-reason refuse cargo.
 * Production workers mint refuse records in-process; tests use this factory.
 */

import type { ReviewFixRefuseRecord } from "../../src/types.js";
import {
  LEGAL_REFUSE_REASONS,
  type LegalRefuseReason,
} from "../../src/stationReceiptContracts.js";

export { LEGAL_REFUSE_REASONS };
export type { LegalRefuseReason };

/**
 * Build a four-reason refuse cargo row for tests.
 * Tokens must be one of {@link LEGAL_REFUSE_REASONS}; invents are rejected.
 */
export function mintFourReasonRefuseRecord(input: {
  readonly identityKey: string;
  readonly reason: LegalRefuseReason;
  readonly evidence: string;
  readonly finding?: string;
  readonly acceptanceCriterion?: string;
}): ReviewFixRefuseRecord {
  if (!(LEGAL_REFUSE_REASONS as readonly string[]).includes(input.reason)) {
    throw new Error(
      `mintFourReasonRefuseRecord: illegal reason ${String(input.reason)}`,
    );
  }
  const evidence = input.evidence.trim();
  if (evidence.length === 0) {
    throw new Error("mintFourReasonRefuseRecord: evidence must be non-empty");
  }
  const identityKey = input.identityKey.trim();
  if (identityKey.length === 0) {
    throw new Error("mintFourReasonRefuseRecord: identityKey must be non-empty");
  }
  // #677 AC-conflict shape uses conflictReason; #927 adds reason + evidence.
  // One prose payload fills both slots — not two independent narratives.
  return {
    identityKey,
    finding: input.finding ?? identityKey,
    acceptanceCriterion:
      input.acceptanceCriterion ??
      "four-reason refuse (judge re-adjudicates; not an AC-pin overturn)",
    conflictReason: evidence,
    reason: input.reason,
    evidence,
  };
}
