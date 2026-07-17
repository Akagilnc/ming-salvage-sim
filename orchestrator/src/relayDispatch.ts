/**
 * #686 — relay dispatch: tag contract, handoff triggers, resource-failure
 * boundary vs mechanical retry, ledger + ephemeral baton brief, and
 * review-gate closure.
 *
 * Builds on #683 (quota probe / park) and #767 (Coder-Rec roster). Does not
 * duplicate those modules — forks at the #683 disposition point and selects
 * the next baton via the same roster + ADR 0124 pool-orthogonal lookup.
 */

import type { CoderRosterEntry } from "./coderRoster.js";
import type { IdleDisposition } from "./quotaProbe.js";
import type { StepId } from "./types.js";
import {
  decideParkOrRelay,
  hasLiveRelayBaton,
  selectCapacityRelayBaton,
  selectNextRelayBaton,
  type BillingPoolEntry,
  type BillingPoolId,
  type NextRelayBaton,
  type ParkOrRelayDecision,
} from "./quotaPoolTable.js";

// #937 / #934 ID-007: free-log <relay> parser (parseRelayTag) deleted.
// Decision gates via typed station escalate; resource handoff is capacity/quota_wall.

// ── ledger + ephemeral baton brief (#937 / #934 ID-007) ──────────────────────

/** Live production handoff triggers only (#937 focus/free-log chain deleted). */
export type RelayHandoffTrigger = "quota_wall" | "capacity";

/**
 * Historical ledger trigger literals (read boundary only). Not production
 * constructors — never write these from live handoff code.
 */
export type LegacyRelayHandoffTrigger =
  | RelayHandoffTrigger
  | "pool_dead"
  | "mechanical_retry_exhausted"
  | "hang_with_live_pool"
  | "self_reported_blocked"
  | "phase_complete";

/**
 * Append-only ledger row when a baton hands off (#686).
 * `state_summary` is the load-bearing field forwarded to the next baton.
 */
export interface RelayHandoffLedgerEvent {
  readonly event: "relay_baton_handoff";
  /** Live writes are only quota_wall|capacity; legacy rows may carry retired tags. */
  readonly trigger: LegacyRelayHandoffTrigger;
  readonly state_summary: string;
  readonly remaining?: string;
  readonly reason?: string;
  readonly fromModelId: string;
  readonly fromPool: BillingPoolId;
  readonly toModelId: string;
  readonly toPool: BillingPoolId;
  readonly step?: StepId;
  readonly ts: string;
}

export function buildRelayHandoffLedgerEntry(input: {
  readonly trigger: RelayHandoffTrigger;
  readonly state_summary: string;
  readonly remaining?: string;
  readonly reason?: string;
  readonly fromModelId: string;
  readonly fromPool: BillingPoolId;
  readonly toModelId: string;
  readonly toPool: BillingPoolId;
  readonly step?: StepId;
  readonly now: Date;
}): RelayHandoffLedgerEvent {
  return {
    event: "relay_baton_handoff",
    trigger: input.trigger,
    state_summary: input.state_summary,
    ...(input.remaining !== undefined ? { remaining: input.remaining } : {}),
    ...(input.reason !== undefined ? { reason: input.reason } : {}),
    fromModelId: input.fromModelId,
    fromPool: input.fromPool,
    toModelId: input.toModelId,
    toPool: input.toPool,
    ...(input.step !== undefined ? { step: input.step } : {}),
    ts: input.now.toISOString(),
  };
}

/**
 * Render an ephemeral relay brief from an in-memory ledger handoff row.
 * #937 / #934 ID-007: one-shot at dispatch from ledger memory — no file, no
 * helper state, no reverse-write into the ledger.
 */
export function renderEphemeralRelayBrief(
  entry: Pick<
    RelayHandoffLedgerEvent,
    "trigger" | "fromModelId" | "fromPool" | "toModelId" | "toPool" | "ts" | "state_summary" | "remaining" | "reason"
  >,
): string {
  const lines = [
    `# Relay baton handoff`,
    ``,
    `- trigger: ${entry.trigger}`,
    `- from: ${entry.fromModelId} @ ${entry.fromPool}`,
    `- to: ${entry.toModelId} @ ${entry.toPool}`,
    `- ts: ${entry.ts}`,
    ``,
    `## state_summary`,
    ``,
    entry.state_summary,
    ``,
  ];
  if (entry.remaining !== undefined && entry.remaining.length > 0) {
    lines.push(`## remaining`, ``, entry.remaining, ``);
  }
  if (entry.reason !== undefined && entry.reason.length > 0) {
    lines.push(`## reason`, ``, entry.reason, ``);
  }
  return lines.join("\n");
}

/** Count relay_baton_handoff rows in an append-only ledger (chain length). */
export function countRelayHandoffsInLedger(
  ledger: ReadonlyArray<{ readonly event?: string }>,
): number {
  return ledger.reduce(
    (n, e) => (e.event === "relay_baton_handoff" ? n + 1 : n),
    0,
  );
}

/** Max completed handoffs; the 8th is forbidden (#934 ID-008). */
export const MAX_RELAY_HANDOFFS = 7;

export function canRelayHandoff(
  ledger: ReadonlyArray<{ readonly event?: string }>,
  max = MAX_RELAY_HANDOFFS,
): boolean {
  return countRelayHandoffsInLedger(ledger) < max;
}

/** #787 checkpoint-local service congestion; relay without quota parking. */
export class CapacityRelayError extends Error {
  readonly capacity = true;

  constructor(message: string) {
    super(message);
    this.name = "CapacityRelayError";
  }
}

/**
 * Capacity is deliberately narrower than generic 5xx failure and never absorbs
 * a quota 429. This is the provider's model-specific CLI fingerprint, not the
 * broader telemetry taxonomy (which is intentionally descriptive).
 */
export function isCapacityRelayError(err: unknown): err is CapacityRelayError {
  if (err instanceof CapacityRelayError) return true;
  const message = err instanceof Error ? err.message : String(err);
  const lower = message.toLowerCase();
  if (/\b(?:http\s*(?:status|code)?\s*)?429\b/.test(lower)) return false;
  return lower.includes("selected model is at capacity");
}

export function capacityRelayErrorFrom(err: unknown): CapacityRelayError | undefined {
  if (!isCapacityRelayError(err)) return undefined;
  return new CapacityRelayError(err instanceof Error ? err.message : String(err));
}

// #937: HangWithLivePoolError, SelfReportedRelayError, tryParseActionableRelayTag
// deleted with free-log fate channel / idle host kill (ID-006 / ID-007). Capacity
// and quota-wall remain the live resource-failure constructors.

/**
 * Resume only a baton for the exact executable slot being re-entered. A later
 * execution of that slot consumes/supersedes its earlier relay marker.
 */
export function resumeRelayFromLedger(
  ledger: ReadonlyArray<{ readonly event?: string; readonly step?: StepId }>,
  resumeStep: StepId,
): RelayHandoffLedgerEvent | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const row = ledger[i]!;
    if (row.step !== resumeStep) continue;
    if (row.event === "relay_baton_handoff") return row as RelayHandoffLedgerEvent;
    if (row.event === undefined) return undefined;
  }
  return undefined;
}

// ── handoff composition ─────────────────────────────────────────────────────

export type RelayDispositionResult =
  | {
      readonly kind: "park";
      readonly preserveWorktree: true;
      readonly reason: string;
      readonly resetAt?: Date;
    }
  | {
      readonly kind: "park_fallback";
      readonly preserveWorktree: true;
      readonly reason: string;
      readonly resetAt?: Date;
    }
  | {
      readonly kind: "relay";
      readonly preserveWorktree: true;
      readonly trigger: RelayHandoffTrigger;
      readonly nextBaton: NextRelayBaton;
      readonly reason: string;
      readonly ledgerEntry?: RelayHandoffLedgerEvent;
    }
  | {
      readonly kind: "hang";
      readonly preserveWorktree: false;
      readonly reason: string;
    };

/**
 * Pure integration entry at the #683 `wait_for_reset` disposition point
 * (ADR 0125). This is the runner seam — {@link parkOrRelayQuotaWall} / hang
 * helpers compose on top. Returns park / park_fallback / relay (+ baton +
 * ledger row when relaying).
 */
export function forkQuotaWallAt683Point(input: {
  readonly disposition: Extract<IdleDisposition, { kind: "wait_for_reset" }>;
  readonly now: Date;
  readonly parkThresholdMs: number;
  readonly currentModelId: string;
  readonly currentPool: BillingPoolId;
  readonly rosterOrder: ReadonlyArray<CoderRosterEntry>;
  readonly pools: ReadonlyArray<BillingPoolEntry>;
  readonly state_summary?: string;
  readonly remaining?: string;
  readonly step?: StepId;
}): {
  readonly tier: ParkOrRelayDecision;
  readonly nextBaton?: NextRelayBaton;
  readonly ledgerEntry?: RelayHandoffLedgerEvent;
} {
  const batonInput = {
    currentModelId: input.currentModelId,
    currentPool: input.currentPool,
    rosterOrder: input.rosterOrder,
    pools: input.pools,
  };
  const live = hasLiveRelayBaton(batonInput);
  const tier = decideParkOrRelay({
    now: input.now,
    resetAt: input.disposition.resetAt,
    parkThresholdMs: input.parkThresholdMs,
    hasLiveBaton: live,
  });
  if (tier !== "relay") {
    return { tier };
  }
  const nextBaton = selectNextRelayBaton(batonInput);
  if (nextBaton === undefined) {
    return { tier: "park_fallback" };
  }
  return {
    tier: "relay",
    nextBaton,
    ledgerEntry: buildRelayHandoffLedgerEntry({
      trigger: "quota_wall",
      state_summary:
        input.state_summary ??
        "quota wall interrupt; uncommitted drift preserved",
      remaining: input.remaining,
      fromModelId: input.currentModelId,
      fromPool: input.currentPool,
      toModelId: nextBaton.modelId,
      toPool: nextBaton.pool,
      step: input.step,
      now: input.now,
    }),
  };
}

/**
 * #937: decideRelayAfterIdle (idle probe → kill pid tree → hang/relay) deleted
 * with idle kill / PID-tree machinery (#934 ID-006 / ID-007). Quota-wall fork
 * remains {@link forkQuotaWallAt683Point}; resource handoff is
 * {@link applyResourceFailureHandoff}. isRelayCandidateExhaustion deleted —
 * process-root exhaustion is the phase's canonical failed edge (ID-004), not a
 * baton handoff.
 */

export interface ApplyResourceFailureHandoffInput {
  readonly trigger: RelayHandoffTrigger;
  readonly state_summary: string;
  readonly remaining?: string;
  readonly reason?: string;
  readonly currentModelId: string;
  readonly currentPool: BillingPoolId;
  readonly rosterOrder: ReadonlyArray<CoderRosterEntry>;
  readonly pools: ReadonlyArray<BillingPoolEntry>;
  readonly now: Date;
  readonly step?: StepId;
}

/**
 * Resource-failure handoff. Never resets the worktree scene (#934 ID-006).
 */
export async function applyResourceFailureHandoff(
  input: ApplyResourceFailureHandoffInput,
): Promise<RelayDispositionResult> {
  const batonInput = {
    currentModelId: input.currentModelId,
    currentPool: input.currentPool,
    rosterOrder: input.rosterOrder,
    pools: input.pools,
  };
  const next =
    input.trigger === "capacity"
      ? selectCapacityRelayBaton(batonInput)
      : selectNextRelayBaton(batonInput);
  if (next === undefined) {
    return {
      kind: "park_fallback",
      preserveWorktree: true,
      reason: "resource failure but no live baton; park fallback",
    };
  }
  const ledgerEntry = buildRelayHandoffLedgerEntry({
    trigger: input.trigger,
    state_summary: input.state_summary,
    remaining: input.remaining,
    reason: input.reason,
    fromModelId: input.currentModelId,
    fromPool: input.currentPool,
    toModelId: next.modelId,
    toPool: next.pool,
    step: input.step,
    now: input.now,
  });
  return {
    kind: "relay",
    preserveWorktree: true,
    trigger: input.trigger,
    nextBaton: next,
    reason: input.reason ?? `resource failure → relay (${input.trigger})`,
    ledgerEntry,
  };
}

/**
 * Relay chain ends at the normal review gate. A closing baton's normal
 * terminal (no relay tag) is required — self-reported phase_complete / clear
 * is NOT a review-gate exemption (#596 empiric).
 */
export function isRelayChainReadyForReviewGate(input: {
  readonly closingBatonCompleted: boolean;
  readonly emittedRelayTag: boolean;
  readonly lastRelayPhase?: "build" | "clear";
}): boolean {
  return input.closingBatonCompleted === true && input.emittedRelayTag === false;
}
