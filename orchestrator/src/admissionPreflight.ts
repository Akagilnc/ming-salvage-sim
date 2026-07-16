/**
 * Admission / Preflight Action (#934 ID-002 / ID-003, #936).
 * Owns route resolve, tight-policy fail-closed, and Coder-Rec admission.
 * Env slot / CMR overrides and interactive continue are deleted.
 */

import {
  applyCoderRecToRoute,
  applyTightRoutePolicy,
  degradeOptionalRouteSmokeFailures,
  resolveActiveModelRoute,
  routeSmokeFailure,
  type ResolvedModelRoute,
} from "./modelRoutes.js";
import type { Backend, Escalation } from "./types.js";
import { classifyExternalCallFailure } from "./externalCall.js";

export const MAX_METADATA_ATTEMPTS = 6;

/**
 * GitHub authentication / login required (#934 ID-003). Zero retry (durable
 * class via {@link classifyExternalCallFailure}); caller emits typed decision
 * gate — never invents a new auth/retry cause token.
 */
export function isGithubAuthFailure(err: unknown): boolean {
  if (err !== null && typeof err === "object") {
    const e = err as {
      readonly status?: unknown;
      readonly statusCode?: unknown;
      readonly message?: unknown;
      readonly stderr?: unknown;
    };
    const status =
      Number.isInteger(e.status)
        ? (e.status as number)
        : Number.isInteger(e.statusCode)
          ? (e.statusCode as number)
          : undefined;
    if (status === 401) return true;
    const text = [e.message, e.stderr]
      .filter((part): part is string => typeof part === "string")
      .join("\n");
    if (
      /\bHTTP\s*401\b/i.test(text) ||
      /\b401\s+Unauthorized\b/i.test(text) ||
      /bad credentials/i.test(text) ||
      /requires authentication/i.test(text) ||
      /authentication required/i.test(text) ||
      /not logged into any GitHub hosts/i.test(text) ||
      /gh auth login/i.test(text) ||
      /to re-authenticate/i.test(text) ||
      /GH_TOKEN/i.test(text) && /auth/i.test(text)
    ) {
      return true;
    }
  } else if (typeof err === "string") {
    if (/\bHTTP\s*401\b/i.test(err) || /gh auth login/i.test(err)) return true;
  }
  return false;
}

/** The sole GitHub metadata retry seam: transient only; deterministic/auth errors do not retry. */
export function readMetadataWithRetry<T>(read: () => T): T {
  let last: unknown;
  for (let attempt = 1; attempt <= MAX_METADATA_ATTEMPTS; attempt += 1) {
    try {
      return read();
    } catch (err) {
      last = err;
      if (
        classifyExternalCallFailure(err) !== "transient" ||
        attempt === MAX_METADATA_ATTEMPTS
      ) {
        throw err;
      }
    }
  }
  throw last;
}

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

export type RouteSmokeAdmission =
  | {
      readonly kind: "ready";
      readonly route: ResolvedModelRoute;
      readonly dropped: ReadonlyArray<{ readonly slug: string; readonly reason: string }>;
    }
  | { readonly kind: "stop"; readonly escalation: Escalation };

/** Shared final-route smoke gate. The caller decides when durable recording begins. */
export async function admitRouteSmoke(
  backend: Backend,
  route: ResolvedModelRoute,
): Promise<RouteSmokeAdmission> {
  if (backend.smokeModelRoute === undefined) {
    return {
      kind: "stop",
      escalation: {
        reason: "startup route smoke failure",
        diagnosis: "route smoke executor is required before dispatch",
      },
    };
  }
  try {
    const versions = backend.currentCliVersions
      ? await backend.currentCliVersions(route)
      : {};
    const smoked = await backend.smokeModelRoute(route, versions);
    const degradation = degradeOptionalRouteSmokeFailures(smoked);
    const failure = routeSmokeFailure(
      degradation.route,
      Date.now(),
      undefined,
      versions,
    );
    if (failure !== undefined) {
      return {
        kind: "stop",
        escalation: { reason: "startup route smoke failure", diagnosis: failure },
      };
    }
    return { kind: "ready", route: degradation.route, dropped: degradation.dropped };
  } catch (err) {
    return {
      kind: "stop",
      escalation: {
        reason: "startup route smoke failure",
        diagnosis: `route smoke failed: ${err instanceof Error ? err.message : String(err)}`,
      },
    };
  }
}

/** Smoke every distinct planned coder lineup concurrently, once before worksite. */
export async function admitPlannedRouteSmoke(
  backend: Backend,
  routes: ReadonlyArray<ResolvedModelRoute>,
): Promise<RouteSmokeAdmission> {
  const uniqueRoutes = [...new Map(
    routes.map((route) => [route.slots.coder, route]),
  ).values()];
  if (uniqueRoutes.length === 0) {
    return {
      kind: "stop",
      escalation: {
        reason: "startup route smoke failure",
        diagnosis: "planned route inventory is empty",
      },
    };
  }
  const results = await Promise.all(
    uniqueRoutes.map((route) => admitRouteSmoke(backend, route)),
  );
  // #934 ID-003: wait for all unique smokes, then aggregate every required
  // failure — never first-failure-only inventory drop.
  const failures = results.filter(
    (result): result is Extract<RouteSmokeAdmission, { readonly kind: "stop" }> =>
      result.kind === "stop",
  );
  if (failures.length > 0) {
    return {
      kind: "stop",
      escalation: {
        reason: "startup route smoke failure",
        diagnosis: failures.map((f) => f.escalation.diagnosis).join("; "),
      },
    };
  }
  return results[0]!;
}
