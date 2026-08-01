/**
 * #683 / #937 — explicit quota wait-for-reset (typed 429 wall).
 *
 * Host silence never probes pools or invents quota fate (ID-007). This module
 * owns pool id mapping, durable wait-for-reset ledger rows, bridge
 * serialize/parse of QuotaWaitForResetError, and idle-error classification
 * for telemetry only. #686 parks vs relays at wait_for_reset.
 *
 * #905 r2: opencode-go PONG path retired — no process spawn of `opencode`.
 */

import type { StepId } from "./types.js";

/** Provider quota pool the worker is drawing from. */
export type QuotaPoolId = "zai" | "opencode-go" | "grok" | "unknown";

const QUOTA_POOL_IDS: ReadonlySet<string> = new Set<QuotaPoolId>([
  "zai",
  "opencode-go",
  "grok",
  "unknown",
]);

function isQuotaPoolId(value: unknown): value is QuotaPoolId {
  return typeof value === "string" && QUOTA_POOL_IDS.has(value);
}

const BRIDGE_STEP_IDS: ReadonlySet<string> = new Set<StepId>([
  "S0",
  "S1",
  "S2",
  "S3",
  "S4",
  "S5",
  "S6",
  "S7",
  "S8",
  "S9",
  "S10",
  "S11",
  "S12",
  "S13", // #1145 Collector seat — must survive quota bridge round-trip
]);

function isBridgeStepId(value: unknown): value is StepId {
  return typeof value === "string" && BRIDGE_STEP_IDS.has(value);
}

/** Explicit quota wall disposition (never invented from host silence). */
export type IdleDisposition = {
  readonly kind: "wait_for_reset";
  readonly pool: QuotaPoolId;
  readonly resetAt?: Date;
  readonly reason: string;
};

/**
 * Append-only ledger row when a worker is parked on a quota wall (#683).
 * Lives in {@link import("./types.js").LedgerBookkeepingEvent}.
 */
export interface QuotaWaitForResetLedgerEvent {
  readonly event: "quota_wait_for_reset";
  readonly pool: QuotaPoolId;
  /** ISO-8601 reset instant when known (from 429 body). */
  readonly resetAt?: string;
  readonly reason: string;
  readonly step?: StepId;
  readonly workerPid?: number;
  readonly ts: string;
}

/** Applied ledger side of an explicit quota wait-for-reset (bridge / park). */
export interface ApplyIdleDispositionResult {
  readonly ledgerEntry?: QuotaWaitForResetLedgerEvent;
}

/**
 * Map a route/model reference (slug, `provider/model`, or CLI model id) to a
 * quota pool. Companion to the model route table — pool membership is derived
 * from naming conventions used by the cheap-coder benches (#424 / #440).
 */
export function poolForModelRef(modelRef: string): QuotaPoolId {
  // Defensive: untyped callers may pass non-strings; never throw on .trim().
  if (typeof modelRef !== "string" || modelRef.length === 0) return "unknown";
  const raw = modelRef.trim().toLowerCase();
  if (raw.length === 0) return "unknown";

  // Explicit provider prefix wins.
  if (raw.startsWith("zai/") || raw === "zai") return "zai";
  // #905 r2: opencode-go model refs no longer map to a live probe pool.
  // Historical strings fall through to unknown (fail-safe hang), not a spawn.
  if (raw.startsWith("opencode-go/") || raw === "opencode-go") return "unknown";

  // Grok CLI family (SuperGrok subscription pool).
  if (raw.startsWith("grok-") || raw === "grok" || raw.startsWith("grok/")) {
    return "grok";
  }

  // Bare GLM ids default to zai (primary free/lite path).
  if (raw.startsWith("glm-") || raw.includes("glm-5")) return "zai";

  // #905 r2: kimi bare slug previously Go-pool only — retired with opencode.
  if (raw.includes("kimi")) return "unknown";

  return "unknown";
}

/** Build the ledger-visible wait-for-reset row (ISO resetAt when known). */
export function buildQuotaWaitForResetLedgerEntry(input: {
  readonly pool: QuotaPoolId;
  readonly resetAt?: Date;
  readonly reason: string;
  readonly step?: StepId;
  readonly workerPid?: number;
  readonly now: Date;
}): QuotaWaitForResetLedgerEvent {
  return {
    event: "quota_wait_for_reset",
    pool: input.pool,
    ...(input.resetAt !== undefined
      ? { resetAt: input.resetAt.toISOString() }
      : {}),
    reason: input.reason,
    ...(input.step !== undefined ? { step: input.step } : {}),
    ...(input.workerPid !== undefined ? { workerPid: input.workerPid } : {}),
    ts: input.now.toISOString(),
  };
}

/**
 * Detect Sandcastle's idle-timeout failure. `AgentIdleTimeoutError` is not on
 * the package's public export surface, so we match by tagged name / message.
 * Classification only (telemetry) — silence never triggers quota probe/park.
 */
export function isAgentIdleTimeoutError(err: unknown): boolean {
  if (err === null || typeof err !== "object") return false;
  const e = err as { readonly _tag?: unknown; readonly name?: unknown; readonly message?: unknown };
  if (e._tag === "AgentIdleTimeoutError" || e.name === "AgentIdleTimeoutError") {
    return true;
  }
  if (typeof e.message === "string" && /agent idle for \d+/i.test(e.message)) {
    return true;
  }
  return false;
}

/**
 * Raised on an **explicit** typed 429/quota wall (bridge sidecar / live
 * constructors). Must not be invented from host silence (ID-007).
 *
 * The runner parks via ledger `quota_wait_for_reset` + status escalate — never
 * S8(error). Auto re-dispatch after reset is #686.
 */
export class QuotaWaitForResetError extends Error {
  readonly disposition: Extract<IdleDisposition, { kind: "wait_for_reset" }>;
  readonly applied: ApplyIdleDispositionResult;
  readonly pool: QuotaPoolId;
  /**
   * Family integrated-CMR wall role when the 429 happened on a pass worker.
   * Set by the family dispatch layer so relay rewrites only the hit CMR slot
   * (correctness N2 — never both).
   */
  cmrPass?: "completeness" | "correctness";

  constructor(result: {
    readonly disposition: IdleDisposition;
    readonly applied: ApplyIdleDispositionResult;
    readonly pool: QuotaPoolId;
  }) {
    if (result.disposition.kind !== "wait_for_reset") {
      throw new Error(
        "QuotaWaitForResetError requires a wait_for_reset disposition",
      );
    }
    super(
      `quota wait for reset on pool ${result.pool}` +
        (result.disposition.resetAt !== undefined
          ? ` until ${result.disposition.resetAt.toISOString()}`
          : ""),
    );
    this.name = "QuotaWaitForResetError";
    this.disposition = result.disposition;
    this.applied = result.applied;
    this.pool = result.pool;
  }
}

/** Sidecar reason prefix so a #684 bridge child can re-surface a quota park. */
export const QUOTA_WAIT_BRIDGE_REASON_PREFIX = "QUOTA_WAIT_FOR_RESET_V1:";

interface QuotaWaitBridgePayload {
  readonly pool: QuotaPoolId;
  readonly reason: string;
  readonly resetAt?: string;
  readonly step?: StepId;
  readonly workerPid?: number;
  readonly ts?: string;
  readonly probeDetail?: string;
}

/**
 * Serialize a {@link QuotaWaitForResetError} into a WorkerResult.failed reason
 * the parent monitor can reconstruct (bridge child cannot throw across process).
 */
export function serializeQuotaWaitForResetBridge(
  err: QuotaWaitForResetError,
): string {
  const payload: QuotaWaitBridgePayload = {
    pool: err.pool,
    reason: err.disposition.reason,
    ...(err.disposition.resetAt !== undefined
      ? { resetAt: err.disposition.resetAt.toISOString() }
      : {}),
    ...(err.applied.ledgerEntry?.step !== undefined
      ? { step: err.applied.ledgerEntry.step }
      : {}),
    ...(err.applied.ledgerEntry?.workerPid !== undefined
      ? { workerPid: err.applied.ledgerEntry.workerPid }
      : {}),
    ...(err.applied.ledgerEntry?.ts !== undefined
      ? { ts: err.applied.ledgerEntry.ts }
      : {}),
  };
  return `${QUOTA_WAIT_BRIDGE_REASON_PREFIX}${JSON.stringify(payload)}`;
}

/**
 * Reconstruct a {@link QuotaWaitForResetError} from a bridge sidecar reason, or
 * return undefined when the reason is not a quota-wait payload.
 */
export function tryParseQuotaWaitForResetBridge(
  reason: string,
): QuotaWaitForResetError | undefined {
  if (!reason.startsWith(QUOTA_WAIT_BRIDGE_REASON_PREFIX)) return undefined;
  const raw = reason.slice(QUOTA_WAIT_BRIDGE_REASON_PREFIX.length);
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return undefined;
  }
  if (parsed === null || typeof parsed !== "object") {
    return undefined;
  }
  const payload = parsed as Record<string, unknown>;
  // Required fields: fail-closed (reject) when pool is missing / not a
  // QuotaPoolId, or reason is not a string — same as other shape failures.
  if (!isQuotaPoolId(payload.pool) || typeof payload.reason !== "string") {
    return undefined;
  }
  const pool = payload.pool;
  const reasonText = payload.reason;

  const resetAt =
    typeof payload.resetAt === "string" && payload.resetAt.length > 0
      ? new Date(payload.resetAt)
      : undefined;
  const disposition: Extract<IdleDisposition, { kind: "wait_for_reset" }> = {
    kind: "wait_for_reset",
    pool,
    reason: reasonText,
    ...(resetAt !== undefined && !Number.isNaN(resetAt.getTime())
      ? { resetAt }
      : {}),
  };

  // Optional fields: drop/ignore malformed values rather than propagating.
  const step = isBridgeStepId(payload.step) ? payload.step : undefined;
  const workerPid =
    typeof payload.workerPid === "number" &&
    Number.isFinite(payload.workerPid) &&
    Number.isInteger(payload.workerPid)
      ? payload.workerPid
      : undefined;
  let now = new Date();
  if (typeof payload.ts === "string" && payload.ts.length > 0) {
    const parsedTs = new Date(payload.ts);
    if (!Number.isNaN(parsedTs.getTime())) {
      now = parsedTs;
    }
  }
  const ledgerEntry = buildQuotaWaitForResetLedgerEntry({
    pool,
    resetAt: disposition.resetAt,
    reason: reasonText,
    ...(step !== undefined ? { step } : {}),
    ...(workerPid !== undefined ? { workerPid } : {}),
    now,
  });
  return new QuotaWaitForResetError({
    disposition,
    applied: { ledgerEntry },
    pool,
  });
}

export function isQuotaWaitForResetError(err: unknown): err is QuotaWaitForResetError {
  return (
    err instanceof QuotaWaitForResetError ||
    (err !== null &&
      typeof err === "object" &&
      (err as { readonly name?: unknown }).name === "QuotaWaitForResetError")
  );
}
