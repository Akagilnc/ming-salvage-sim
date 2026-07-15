/**
 * #927 — coder refuse exit: legal receipt → blind route to judge re-adjudicate.
 *
 * Envelope traffic (`status:"refused"` + `refusedFindingIdentityKeys`) is the
 * only routing signal. Four legal refuse reasons + evidence live in opaque
 * cargo for the judge; the runner never reads reason prose for topology.
 *
 * Reuses {@link LEGAL_REFUSE_REASONS} / refused* vocabulary from
 * stationReceiptContracts (T2). Re-dispatch governance (#902) is out of scope.
 */

import type { ReviewFixRefuseRecord } from "./types.js";
import { reviewFixDecisionGate } from "./reviewFixAssertionGate.js";
import {
  LEGAL_REFUSE_REASONS,
  type LegalRefuseReason,
} from "./stationReceiptContracts.js";

export { LEGAL_REFUSE_REASONS };
export type { LegalRefuseReason };

/** Coder-fix output fields the refuse-exit seam cares about. */
export interface CoderRefuseCapableOutput {
  readonly refusedFindingIdentityKeys?: ReadonlyArray<string>;
  readonly refuseRecords?: ReadonlyArray<ReviewFixRefuseRecord>;
  readonly escalate?: { readonly reason: string; readonly diagnosis: string };
}

/**
 * Traffic keys for S5→S6 reverify landing.
 *
 * Prefer envelope `refusedFindingIdentityKeys` (canonical T2 traffic). Fall
 * back to well-shaped #677 refuseRecords via the decision gate. Never parses
 * four-reason tokens or evidence prose.
 */
export function coderRefuseTrafficKeys(
  output: CoderRefuseCapableOutput,
): readonly string[] {
  const fromEnvelope = (output.refusedFindingIdentityKeys ?? []).filter(
    (k): k is string => typeof k === "string" && k.trim().length > 0,
  );
  if (fromEnvelope.length > 0) return fromEnvelope;

  const records = output.refuseRecords ?? [];
  if (records.length === 0) return [];
  return reviewFixDecisionGate({ records })?.refusedFindingIdentityKeys ?? [];
}

/**
 * True when the coder output is a legal refuse receipt (traffic keys present
 * and no escalate bell). Escalate is a different exit — never dual-classified.
 */
export function isCoderRefuseReceipt(
  output: CoderRefuseCapableOutput,
): boolean {
  if (output.escalate != null) return false;
  return coderRefuseTrafficKeys(output).length > 0;
}

/**
 * Opaque refuse cargo for judge re-adjudication. Runner transports as-is —
 * does not validate reason tokens, evidence, or AC conflict prose.
 */
export function coderRefuseOpaqueCargo(
  output: CoderRefuseCapableOutput,
): readonly ReviewFixRefuseRecord[] | undefined {
  const records = output.refuseRecords;
  if (records === undefined || records.length === 0) return undefined;
  return records;
}

/**
 * S6 reverify signals derived from a completed S5 coder output.
 * Pure projection — same shape the runner threads into DispatchContext /
 * WorkerLandingPayload (keys = traffic; refuseRecords = opaque cargo).
 */
export function coderRefuseReverifyLanding(output: CoderRefuseCapableOutput): {
  readonly refusedFindingIdentityKeys: readonly string[];
  readonly refuseRecords?: readonly ReviewFixRefuseRecord[];
} {
  const keys = coderRefuseTrafficKeys(output);
  const cargo = coderRefuseOpaqueCargo(output);
  return {
    refusedFindingIdentityKeys: keys,
    ...(cargo !== undefined ? { refuseRecords: cargo } : {}),
  };
}

/**
 * Build a four-reason refuse cargo row for tests / workers.
 * Tokens must be one of {@link LEGAL_REFUSE_REASONS}; invents are rejected.
 * Runner topology never calls this — it is a cargo factory, not a router.
 */
export function mintFourReasonRefuseRecord(input: {
  readonly identityKey: string;
  readonly reason: LegalRefuseReason;
  readonly evidence: string;
  readonly finding?: string;
  readonly acceptanceCriterion?: string;
}): ReviewFixRefuseRecord {
  if (
    !(LEGAL_REFUSE_REASONS as readonly string[]).includes(input.reason)
  ) {
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
