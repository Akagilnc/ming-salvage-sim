/**
 * #927 — coder refuse exit: legal receipt → blind route to judge re-adjudicate.
 *
 * Envelope traffic (`status:"refused"` + `refusedFindingIdentityKeys`) is the
 * only routing signal. Four legal refuse reasons + evidence live in opaque
 * cargo for the judge; the runner never reads reason prose for topology.
 *
 * Production projection is a single helper: {@link coderRefuseReverifyLanding}.
 * Decode-side cargo siblings stay in realBackend (`coderRefuseCargoFields`);
 * this module only projects typed coder output onto S6 reverify signals.
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
 * Traffic keys for S5→S6 reverify.
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
 * S6 reverify signals derived from a completed S5 coder output.
 *
 * Sole production projection for refuse reverify: keys = envelope traffic;
 * refuseRecords = opaque cargo (pass-through, no reason validation).
 * Runner threads keys onto thin DispatchContext and cargo onto landing only
 * (信封宪法 — cargo prose never lives on the thin ctx).
 */
export function coderRefuseReverifyLanding(output: CoderRefuseCapableOutput): {
  readonly refusedFindingIdentityKeys: readonly string[];
  readonly refuseRecords?: readonly ReviewFixRefuseRecord[];
} {
  const keys = coderRefuseTrafficKeys(output);
  const records = output.refuseRecords;
  const cargo =
    records !== undefined && records.length > 0 ? records : undefined;
  return {
    refusedFindingIdentityKeys: keys,
    ...(cargo !== undefined ? { refuseRecords: cargo } : {}),
  };
}
