/**
 * Admission / Preflight Action (#934 ID-002 / ID-003, #936).
 * Owns route resolve, tight-policy fail-closed, and Coder-Rec admission.
 * Env slot / CMR overrides and interactive continue are deleted.
 */

import {
  applyCoderRecToRoute,
  applyRelayBatonToRoute,
  applyTightRoutePolicy,
  degradeOptionalRouteSmokeFailures,
  resolveActiveModelRoute,
  routeSmokeFailure,
  type ModelRouteSlot,
  type ResolvedModelRoute,
} from "./modelRoutes.js";
import type { Backend, Escalation, StepId } from "./types.js";
import { classifyExternalCallFailure } from "./externalCall.js";
import {
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
} from "./dispatchRetry.js";

/**
 * #1062 — synchronous blocking backoff for the metadata retry seam. The gh reads
 * are execFileSync at admission (the whole runner already blocks on them), so a
 * blocking wait is the right shape — no async ripple through the sync {@link Sh}
 * callers. No-op under vitest (mirrors dispatchRetry's `defaultRetrySleepMs`) so
 * the shared 15s table never burns wall time in tests.
 */
function defaultMetadataSleepSync(ms: number): void {
  if (process.env.VITEST === "true" || ms <= 0) return;
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

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

const GH_HTTP_STATUS = /\bHTTP\s*(\d{3})\b/i;

/**
 * #1063 — gh CLI reports the HTTP status only in its stderr/message text (e.g.
 * `gh: Service Unavailable (HTTP 503)`) while `.status` on the execFileSync
 * error holds the process EXIT code (1). Extract the numeric HTTP status — a
 * machine token in gh's own structured error line — and attach it as
 * `httpStatus` so {@link classifyExternalCallFailure} (which never reads free
 * text) can key on 5xx ahead of the shadowing exit code. Single boundary shared
 * by the retry budget below and, through it, the #1063 dual-channel fallback.
 * Mirrors the existing gh-text HTTP parse in {@link isGithubAuthFailure}.
 */
export function withGithubHttpStatus(err: unknown): unknown {
  if (err === null || typeof err !== "object") return err;
  const e = err as {
    httpStatus?: unknown;
    readonly message?: unknown;
    readonly stderr?: unknown;
  };
  if (Number.isInteger(e.httpStatus)) return err;
  const text = [e.message, e.stderr]
    .filter((part): part is string => typeof part === "string")
    .join("\n");
  const match = GH_HTTP_STATUS.exec(text);
  if (match !== null) {
    (err as { httpStatus?: number }).httpStatus = Number(match[1]);
  }
  return err;
}

/**
 * The sole GitHub metadata retry seam: transient only; deterministic/auth errors
 * do not retry. #1062 — reuses the process-level dispatch retry budget and its
 * 5×15s backoff table (no parallel metadata constant); a transient 5xx now spans
 * the outage window across the six attempts instead of firing six times in the
 * same millisecond. `sleepMs` is injectable so tests observe the backoff without
 * blocking on the real 75s wall.
 */
export function readMetadataWithRetry<T>(
  read: () => T,
  sleepMs: (ms: number) => void = defaultMetadataSleepSync,
): T {
  let last: unknown;
  for (let attempt = 1; attempt <= MAX_DISPATCH_ATTEMPTS; attempt += 1) {
    try {
      return read();
    } catch (err) {
      // #1063: surface gh's HTTP status as a numeric field before classify, so a
      // persistent 5xx is seen as transient (retry here, then GraphQL fallback)
      // rather than masked by exit code 1. The rethrown error carries httpStatus
      // for the downstream dual-channel classify too.
      const enriched = withGithubHttpStatus(err);
      last = enriched;
      if (
        classifyExternalCallFailure(enriched) !== "transient" ||
        attempt === MAX_DISPATCH_ATTEMPTS
      ) {
        throw enriched;
      }
      // #1062: wait the shared backoff interval before the next attempt (five
      // 15s slots across six attempts). Index by the just-failed attempt so
      // attempt 1's failure waits slot 0, ..., attempt 5's waits slot 4.
      const delayMs = DISPATCH_RETRY_BACKOFF_MS[attempt - 1];
      if (delayMs !== undefined) sleepMs(delayMs);
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

/**
 * Pure apply seam for {@link admitRelayBaton}. Production defaults to
 * {@link applyRelayBatonToRoute}; family/tests may inject a compatible override
 * so apply throws and slot rewrites share one admit court (not half-court).
 */
export type AdmitRelayBatonApplyFn = (
  route: ResolvedModelRoute,
  baton: { readonly slug: string },
  wallStep: StepId,
  opts?: { readonly slots?: ReadonlyArray<ModelRouteSlot> },
) => ResolvedModelRoute;

/**
 * #934 ID-002 / R7 F2 — after a relay baton rewrites the final route, re-satisfy
 * the same tight gate as admission before any further dispatch. Pure apply is
 * {@link applyRelayBatonToRoute}; this is apply + admit, not a second policy court.
 * Apply throws map to typed stop (same shape as tight violation) — never escape
 * as uncaught exceptions on the family half-court path.
 */
export function admitRelayBaton(
  route: ResolvedModelRoute,
  baton: { readonly slug: string },
  wallStep: StepId = "S2",
  opts?: {
    readonly slots?: ReadonlyArray<ModelRouteSlot>;
    readonly applyFn?: AdmitRelayBatonApplyFn;
  },
): AdmissionRouteResult {
  try {
    const apply = opts?.applyFn ?? applyRelayBatonToRoute;
    const applyOpts =
      opts?.slots !== undefined ? { slots: opts.slots } : undefined;
    return admitTightRoute(apply(route, baton, wallStep, applyOpts));
  } catch (err) {
    return {
      kind: "stop",
      escalation: {
        reason: "relay baton admission failure",
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
  // All ready: keep a deterministic primary route (first unique coder lineup)
  // but union every route's dropped optional-leg inventory so multi-route
  // admission does not silently discard non-primary smoke degradation (#934 S-4).
  const ready = results as Array<
    Extract<RouteSmokeAdmission, { readonly kind: "ready" }>
  >;
  const primary = ready[0]!;
  const droppedByKey = new Map<string, { readonly slug: string; readonly reason: string }>();
  for (const result of ready) {
    for (const dropped of result.dropped) {
      const key = `${dropped.slug}\0${dropped.reason}`;
      if (!droppedByKey.has(key)) droppedByKey.set(key, dropped);
    }
  }
  return {
    kind: "ready",
    route: primary.route,
    dropped: [...droppedByKey.values()],
  };
}
