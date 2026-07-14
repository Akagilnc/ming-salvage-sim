/**
 * #686 / ADR 0124 — route pool table: pool = quota/billing boundary,
 * orthogonal to the #767 Coder-Rec model roster.
 *
 * Pools (grok-build / cursor / zai / codex-5h / claude) track额度 + resetAt +
 * configurable park threshold T. Models are products that may live in
 * multiple pools (实证: grok-4.5 on grok-build then Cursor).
 *
 * #789 — `claude` is the Anthropic / Claude Code billing boundary that serves
 * roster backups sonnet-5 / haiku-4.5 (same family as the cmrReview opus leg,
 * different runnable slugs → pool-separation stays clear).
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
export type BillingPoolId =
  | "grok-build"
  | "cursor"
  | "zai"
  | "codex-5h"
  | "claude";

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
 * Already-elapsed `resetAt` (resetAt < now) is also beyond T — never clamp
 * into park; a past clock is not a wait window.
 */
export function decideParkOrRelay(input: {
  readonly now: Date;
  readonly resetAt?: Date;
  readonly parkThresholdMs: number;
  readonly hasLiveBaton: boolean;
}): ParkOrRelayDecision {
  const deltaMs =
    input.resetAt !== undefined
      ? input.resetAt.getTime() - input.now.getTime()
      : undefined;
  // deltaMs < 0 → already elapsed; deltaMs undefined → missing resetAt.
  // Both are beyond T (cannot wait a known future window).
  const withinT =
    deltaMs !== undefined &&
    deltaMs >= 0 &&
    deltaMs <= input.parkThresholdMs;

  if (withinT) return "park";
  if (input.hasLiveBaton) return "relay";
  return "park_fallback";
}

/** Map #683 probe pool ids onto ADR 0124 billing-pool ids. */
export function billingPoolFromQuotaPool(pool: string): BillingPoolId {
  switch (pool.trim().toLowerCase()) {
    case "zai":
      return "zai";
    case "grok":
    case "grok-build":
      return "grok-build";
    case "cursor":
      return "cursor";
    case "codex":
    case "codex-5h":
      return "codex-5h";
    case "claude":
    case "anthropic":
      // Claude Code OAuth / Anthropic subscription — same boundary as cmr Claude leg.
      return "claude";
    case "opencode-go":
      // Go-pool GLM/kimi share the zai-adjacent free/lite billing boundary for
      // relay lookup until a dedicated billing row exists.
      return "zai";
    default:
      return "grok-build";
  }
}

/** Default model memberships per billing pool (ADR 0124 orthogonal join). */
export const DEFAULT_POOL_MODELS: Readonly<
  Record<BillingPoolId, ReadonlyArray<string>>
> = {
  // #905: grok-4.5 only on SuperGrok / grok-build — no cursor/zai transit.
  "grok-build": ["grok-4.5"],
  cursor: [],
  zai: [],
  "codex-5h": [
    "terra@med",
    "luna@med",
    "sol@med",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.6-sol",
  ],
  // #789 — roster ids + runnable slugs (mirrors codex-5h dual keys).
  claude: ["sonnet-5", "haiku-4.5", "sonnet", "haiku"],
};

/**
 * Resolve a known roster model to its default billing boundary. This is
 * distinct from quota probing: codex and Claude have no #683 probe-pool id,
 * but their dispatched slugs still identify a billing pool for capacity relay.
 */
export function billingPoolForModelRef(
  modelRef: string,
): BillingPoolId | undefined {
  switch (lookupCoderRosterEntry(modelRef)?.pool) {
    case "supergrok":
      return "grok-build";
    case "codex":
      return "codex-5h";
    case "claude":
      return "claude";
    default:
      return undefined;
  }
}

/**
 * Build a route pool table for a quota-wall disposition: the wall-hit pool is
 * `limited` (with resetAt). Every other billing pool defaults to **not-live**
 * (`dead`) unless the caller supplies a probed/override table via
 * `RunInput.relayPools` / `FamilyRunInput.relayPools` — unknown pool state must
 * not fabricate live batons (#686 R2 / iron rule: park when unprobed).
 */
export function buildDefaultBillingPools(input: {
  readonly limitedPool: BillingPoolId;
  readonly resetAt?: Date;
  readonly parkThresholdMs?: number;
}): BillingPoolEntry[] {
  const t = input.parkThresholdMs ?? DEFAULT_PARK_THRESHOLD_MS;
  const ids: BillingPoolId[] = [
    "grok-build",
    "cursor",
    "zai",
    "codex-5h",
    "claude",
  ];
  return ids.map((id) => {
    if (id === input.limitedPool) {
      return {
        id,
        status: "limited" as const,
        ...(input.resetAt !== undefined ? { resetAt: input.resetAt } : {}),
        parkThresholdMs: t,
        models: DEFAULT_POOL_MODELS[id],
      };
    }
    return {
      id,
      status: "dead" as const,
      parkThresholdMs: t,
      models: DEFAULT_POOL_MODELS[id],
    };
  });
}

/**
 * Loose pool-table row accepted on {@link RunInput.relayPools} /
 * {@link FamilyRunInput.relayPools} (tests + probed production tables).
 */
export type RelayPoolOverride = {
  readonly id: string;
  readonly status: BillingPoolStatus;
  readonly resetAt?: Date;
  readonly parkThresholdMs: number;
  readonly models: ReadonlyArray<string>;
};

/**
 * Shared single-slice + family seam: use an explicit probed/override table when
 * present; otherwise {@link buildDefaultBillingPools} (wall-hit limited, rest
 * dead). Never invents live batons from unprobed state.
 */
export function resolveRelayPools(
  limitedPool: BillingPoolId,
  resetAt: Date | undefined,
  override?: ReadonlyArray<RelayPoolOverride>,
): ReadonlyArray<BillingPoolEntry> {
  if (override !== undefined) {
    return override.map((p) => ({
      id: p.id as BillingPoolId,
      status: p.status,
      ...(p.resetAt !== undefined ? { resetAt: p.resetAt } : {}),
      parkThresholdMs: p.parkThresholdMs,
      models: p.models,
    }));
  }
  return buildDefaultBillingPools({ limitedPool, resetAt });
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
  /** Reviewer legs after this candidate becomes the coder baton. */
  readonly reviewerSlugsForCandidate?: (
    candidate: CoderRosterEntry,
  ) => ReadonlyArray<string>;
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
 * Return a pool whose liveness is confirmed by the relay table and which can
 * serve the dispatched model. A model slug alone is not evidence that its
 * quota/billing pool is live.
 */
export function findLiveBillingPoolForModel(
  pools: ReadonlyArray<BillingPoolEntry>,
  modelRef: string,
): BillingPoolId | undefined {
  const rosterEntry = lookupCoderRosterEntry(modelRef);
  const modelId = rosterEntry?.id ?? modelRef;
  const slug = rosterEntry?.slug ?? modelRef;
  return livePoolsForModel(pools, modelId, slug)[0]?.id;
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
    const candidateReviewerSlugs =
      input.reviewerSlugsForCandidate?.(candidate) ?? reviewerSlugs;
    if (poolSeparationViolation(candidate, candidateReviewerSlugs) !== undefined) {
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

/**
 * #787: capacity is checkpoint-local, not a billing-pool quota wall. Prefer
 * the next Coder-Rec checkpoint that the current live pool can serve; only
 * then fall back to the ordinary pool-orthogonal relay order.
 */
export function selectCapacityRelayBaton(
  input: SelectNextRelayBatonInput,
): NextRelayBaton | undefined {
  const current =
    lookupCoderRosterEntry(input.currentModelId) ??
    input.rosterOrder.find((entry) => entry.id === input.currentModelId);
  const startIdx = input.rosterOrder.findIndex(
    (entry) =>
      entry.id === input.currentModelId ||
      entry.slug === input.currentModelId ||
      (current !== undefined && entry.id === current.id),
  );
  const currentPool = input.pools.find(
    (pool) => pool.id === input.currentPool && pool.status === "live",
  );
  if (currentPool !== undefined) {
    const from = startIdx >= 0 ? startIdx + 1 : 0;
    for (let i = from; i < input.rosterOrder.length; i++) {
      const candidate = input.rosterOrder[i]!;
      const candidateReviewerSlugs =
        input.reviewerSlugsForCandidate?.(candidate) ??
        input.reviewerSlugs ??
        [];
      if (
        poolSeparationViolation(candidate, candidateReviewerSlugs) !== undefined
      ) {
        continue;
      }
      if (poolServesModel(currentPool, candidate.id, candidate.slug)) {
        return {
          modelId: candidate.id,
          slug: candidate.slug,
          pool: currentPool.id,
        };
      }
    }
  }
  return selectNextRelayBaton(input);
}

/** True when {@link selectNextRelayBaton} would return a baton. */
export function hasLiveRelayBaton(
  input: SelectNextRelayBatonInput,
): boolean {
  return selectNextRelayBaton(input) !== undefined;
}
