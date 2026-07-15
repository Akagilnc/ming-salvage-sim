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
 * 信封宪法: cargo (`refuseRecords`) never invents traffic keys. Keys come only
 * from the non-empty envelope field.
 *
 * Reuses {@link LEGAL_REFUSE_REASONS} / refused* vocabulary from
 * stationReceiptContracts (T2). Re-dispatch governance (#902) is out of scope.
 */

import type { ReviewFixRefuseRecord } from "./types.js";
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
 * Sole source = non-empty envelope `refusedFindingIdentityKeys` (canonical T2
 * traffic). Cargo `refuseRecords` never invents keys — even well-shaped #677
 * records do not fall back into topology. Never parses four-reason tokens or
 * evidence prose.
 */
export function coderRefuseTrafficKeys(
  output: CoderRefuseCapableOutput,
): readonly string[] {
  return (output.refusedFindingIdentityKeys ?? []).filter(
    (k): k is string => typeof k === "string" && k.trim().length > 0,
  );
}

/**
 * S6 reverify signals derived from a completed S5 coder output.
 *
 * Sole production projection for refuse reverify: keys = envelope traffic
 * (thin DispatchContext only); refuseRecords = opaque cargo (landing only).
 * Runner must not dual-write keys onto WorkerLandingPayload (信封宪法).
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
