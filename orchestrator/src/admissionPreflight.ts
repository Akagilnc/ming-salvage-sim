/**
 * Admission / Preflight Action (#934 ID-002 / ID-003, #936).
 * Owns route resolve, tight-policy fail-closed, and Coder-Rec admission.
 * Env slot / CMR overrides and interactive continue are deleted.
 */

import {
  applyCoderRecToRoute,
  applyTightRoutePolicy,
  resolveActiveModelRoute,
  type ResolvedModelRoute,
} from "./modelRoutes.js";
import type { Escalation } from "./types.js";

export type AdmissionRouteResult =
  | { readonly kind: "ready"; readonly route: ResolvedModelRoute }
  | { readonly kind: "stop"; readonly escalation: Escalation };

/** Preset + `ORCHESTRATOR_ROUTE` only — no slot/CMR env overrides. */
export function admitRouteFromEnv(
  env: NodeJS.ProcessEnv = process.env,
): AdmissionRouteResult {
  try {
    return admitTightRoute(resolveActiveModelRoute(env));
  } catch (err) {
    const reason =
      err instanceof Error ? err.message : `failed to resolve active model route: ${String(err)}`;
    return {
      kind: "stop",
      escalation: { reason: "startup route failure", diagnosis: reason },
    };
  }
}

/** Tight-family policy always fail-closed (no interactive continue). */
export function admitTightRoute(route: ResolvedModelRoute): AdmissionRouteResult {
  const decision = applyTightRoutePolicy(route);
  if (decision.kind === "stop") {
    return { kind: "stop", escalation: decision.escalation };
  }
  return { kind: "ready", route: decision.route };
}

/** Apply issue Coder-Rec then re-check tight policy. Env never owns the slot. */
export function admitCoderRec(
  route: ResolvedModelRoute,
  issueBody: string | undefined,
): AdmissionRouteResult {
  try {
    return admitTightRoute(applyCoderRecToRoute(route, issueBody).route);
  } catch (err) {
    return {
      kind: "stop",
      escalation: {
        reason: "Coder-Rec admission failure",
        diagnosis: err instanceof Error ? err.message : String(err),
      },
    };
  }
}

export function admissionRouteFailureDiagnosis(reason: string): string {
  return `${reason}; route env ORCHESTRATOR_ROUTE=${process.env.ORCHESTRATOR_ROUTE ?? "normal"}`;
}
