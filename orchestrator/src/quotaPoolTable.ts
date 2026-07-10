/**
 * #686 / ADR 0124 — route pool table: pool = quota/billing boundary,
 * orthogonal to the #767 Coder-Rec model roster.
 *
 * Pools (grok-build / cursor / zai / codex-5h) track额度 + resetAt +
 * configurable park threshold T. Models are products that may live in
 * multiple pools (实证: grok-4.5 on grok-build then Cursor).
 *
 * ADR 0125 three-tier park-vs-relay also lives here as a pure decision
 * over pool state + "has live baton" (baton selection is {@link
 * selectNextRelayBaton}).
 */

import {
  lookupCoderRosterEntry,
  poolSeparationViolation,
  type CoderRosterEntry,
} from "./coderRoster.js";

/** Quota / billing boundary ids (ADR 0124). */
export type BillingPoolId = "grok-build" | "cursor" | "zai" | "codex-5h";

/** Default park-vs-relay threshold T = 30 minutes (ADR 0125). */
export const DEFAULT_PARK_THRESHOLD_MS = 30 * 60 * 1000;

export type BillingPoolStatus = "live" | "limited" | "dead";

/**
 * One row in the route pool table. `models` lists roster ids (or slugs /
 * aliases) this pool can serve — the orthogonal join key to #767.
 */
export interface BillingPoolEntry {
  readonly id: BillingPoolId;
  readonly status: BillingPoolStatus;
  /** Known reset instant when status is `limited` (from 429 body). */
  readonly resetAt?: Date;
  /** Park-vs-relay threshold T for this pool (ms). */
  readonly parkThresholdMs: number;
  /** Roster ids / slugs / aliases this pool can run. */
  readonly models: ReadonlyArray<string>;
}

/** Mutable-looking map shape used by callers; values are readonly entries. */
export type PoolTable = Partial<
  Record<BillingPoolId, BillingPoolEntry>
>;

export type ParkOrRelayDecision = "park" | "relay" | "park_fallback";

/**
 * ADR 0125 three-tier rule at the #683 quota disposition point:
 *   ① same-pool reset within T → park (wait original baton)
 *   ② beyond T + live baton exists → relay
 *   ③ no live baton → park fallback
 *
 * Missing `resetAt` cannot be waited as a known window → treated as beyond T.
 */
export function decideParkOrRelay(input: {
  readonly now: Date;
  readonly resetAt?: Date;
  readonly parkThresholdMs: number;
  readonly hasLiveBaton: boolean;
}): ParkOrRelayDecision {
  const withinT =
    input.resetAt !== undefined &&
    input.resetAt.getTime() - input.now.getTime() <= input.parkThresholdMs &&
    input.resetAt.getTime() - input.now.getTime() >= 0;

  if (withinT) return "park";
  if (input.hasLiveBaton) return "relay";
  return "park_fallback";
}

export interface NextRelayBaton {
  readonly modelId: string;
  readonly slug: string;
  readonly pool: BillingPoolId;
}

export interface SelectNextRelayBatonInput {
  readonly currentModelId: string;
  readonly currentPool: BillingPoolId;
  readonly rosterOrder: ReadonlyArray<CoderRosterEntry>;
  readonly pools: ReadonlyArray<BillingPoolEntry>;
  readonly reviewerSlugs?: ReadonlyArray<string>;
}

function poolServesModel(
  pool: BillingPoolEntry,
  modelId: string,
  slug: string,
): boolean {
  const needles = new Set(
    [modelId, slug].map((s) => s.trim().toLowerCase()).filter((s) => s.length > 0),
  );
  for (const m of pool.models) {
    const entry = lookupCoderRosterEntry(m);
    if (entry !== undefined) {
      if (needles.has(entry.id.toLowerCase()) || needles.has(entry.slug.toLowerCase())) {
        return true;
      }
    }
    if (needles.has(m.trim().toLowerCase())) return true;
  }
  return false;
}

function livePoolsForModel(
  pools: ReadonlyArray<BillingPoolEntry>,
  modelId: string,
  slug: string,
  excludePool?: BillingPoolId,
): BillingPoolEntry[] {
  return pools.filter(
    (p) =>
      p.status === "live" &&
      (excludePool === undefined || p.id !== excludePool) &&
      poolServesModel(p, modelId, slug),
  );
}

/**
 * ADR 0126: next baton from the SAME #767 Coder-Rec roster, with one extra
 * pool-orthogonal step for resource triggers:
 *   1. same model on a different live pool (换马甲)
 *   2. else next roster model that has any live pool
 * Pool-separation filter (#767) is preserved.
 */
export function selectNextRelayBaton(
  input: SelectNextRelayBatonInput,
): NextRelayBaton | undefined {
  const reviewerSlugs = input.reviewerSlugs ?? [];
  const current =
    lookupCoderRosterEntry(input.currentModelId) ??
    input.rosterOrder.find((e) => e.id === input.currentModelId);

  // 1. Same model, alternate live pool (换马甲).
  if (current !== undefined) {
    const alts = livePoolsForModel(
      input.pools,
      current.id,
      current.slug,
      input.currentPool,
    );
    if (alts.length > 0) {
      return {
        modelId: current.id,
        slug: current.slug,
        pool: alts[0]!.id,
      };
    }
  }

  // 2. Walk roster from the entry AFTER current; pick first with a live pool
  //    that also passes pool-separation.
  const startIdx = input.rosterOrder.findIndex(
    (e) =>
      e.id === input.currentModelId ||
      e.slug === input.currentModelId ||
      (current !== undefined && e.id === current.id),
  );
  const from = startIdx >= 0 ? startIdx + 1 : 0;
  for (let i = from; i < input.rosterOrder.length; i++) {
    const candidate = input.rosterOrder[i]!;
    if (poolSeparationViolation(candidate, reviewerSlugs) !== undefined) {
      continue;
    }
    const lives = livePoolsForModel(
      input.pools,
      candidate.id,
      candidate.slug,
    );
    if (lives.length > 0) {
      return {
        modelId: candidate.id,
        slug: candidate.slug,
        pool: lives[0]!.id,
      };
    }
  }
  return undefined;
}

/** True when {@link selectNextRelayBaton} would return a baton. */
export function hasLiveRelayBaton(
  input: SelectNextRelayBatonInput,
): boolean {
  return selectNextRelayBaton(input) !== undefined;
}
