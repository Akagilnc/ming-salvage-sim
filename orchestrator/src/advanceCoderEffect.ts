/**
 * #919 / #926 / #930 / #1002 — one advanceCoder execution path for all courts.
 *
 * Topology law lives here once:
 *   resolveAdvanceCoderSuggestion → applySlug → optional probe → advanced | stay_put | noop
 *
 * Callers own only: audit persistence + sticky seat state. Never terminal on
 * bad advance. Courts differ only in which repair seat `applySlug` rewrites
 * (single-slice coderFix / family coderFix / online-review fixer — #1002).
 */

import {
  resolveAdvanceCoderSuggestion,
  type CoderRosterEntry,
} from "./coderRoster.js";
import type { ResolvedModelRoute } from "./modelRoutes.js";

export type AdvanceCoderEffectResult =
  | {
      readonly kind: "noop";
      readonly reason: "empty_suggestion" | "already_active";
      readonly route: ResolvedModelRoute;
    }
  | {
      readonly kind: "stay_put";
      readonly reason: string;
      readonly suggestion: string;
      readonly route: ResolvedModelRoute;
      readonly audit: {
        readonly event: "coder_advance_stay_put";
        readonly reason: string;
        readonly fromModelId: string;
        readonly toModelId: string;
        readonly state_summary?: string;
        readonly ts: string;
      };
    }
  | {
      readonly kind: "advanced";
      readonly route: ResolvedModelRoute;
      readonly fromSlug: string;
      readonly toSlug: string;
      readonly entry: CoderRosterEntry;
      readonly audit: {
        readonly event: "coder_advance";
        readonly fromModelId: string;
        readonly toModelId: string;
        readonly state_summary?: string;
        readonly ts: string;
      };
    };

export type AdvanceCoderProbe = (
  route: ResolvedModelRoute,
) => Promise<
  | { readonly ok: true; readonly route: ResolvedModelRoute }
  | { readonly ok: false; readonly reason?: string }
>;

/**
 * Execute a judge `advanceCoder` suggestion against one seat's current slug.
 *
 * `applySlug` is the only court difference (repair seats only — #1002 07-18):
 *   - single-slice S3/S6 → rewrite coderFix
 *   - family CMR continue → rewrite coderFix
 *   - online-review continue → rewrite fixer
 */
export async function executeAdvanceCoderSuggestion(input: {
  readonly suggestion: string;
  readonly currentSlug: string;
  readonly route: ResolvedModelRoute;
  /** Apply roster slug onto the seat this court actually dispatches. */
  readonly applySlug: (
    route: ResolvedModelRoute,
    slug: string,
  ) => ResolvedModelRoute;
  /**
   * Assignability probe. Fail → stay_put `unassignable_target` (never terminal).
   * When omitted, advanced seats are accepted without smoke (callers that have
   * smoke must inject it — single-slice always does).
   */
  readonly probe?: AdvanceCoderProbe;
}): Promise<AdvanceCoderEffectResult> {
  const decision = resolveAdvanceCoderSuggestion(
    input.suggestion,
    input.currentSlug,
  );
  const ts = new Date().toISOString();

  if (decision.kind === "noop") {
    return {
      kind: "noop",
      reason: decision.reason,
      route: input.route,
    };
  }

  if (decision.kind === "stay_put") {
    return {
      kind: "stay_put",
      reason: decision.reason,
      suggestion: decision.suggestion,
      route: input.route,
      audit: {
        event: "coder_advance_stay_put",
        reason: decision.reason,
        fromModelId: input.currentSlug,
        toModelId: input.currentSlug,
        state_summary: decision.suggestion,
        ts,
      },
    };
  }

  // advanced — apply seat rewrite, then optional assignability probe.
  const candidate = input.applySlug(input.route, decision.entry.slug);
  const suggestionToken = input.suggestion.trim();

  if (input.probe !== undefined) {
    const probed = await input.probe(candidate);
    if (!probed.ok) {
      return {
        kind: "stay_put",
        reason: "unassignable_target",
        suggestion: suggestionToken,
        route: input.route,
        audit: {
          event: "coder_advance_stay_put",
          reason: "unassignable_target",
          fromModelId: input.currentSlug,
          toModelId: input.currentSlug,
          state_summary: suggestionToken,
          ts,
        },
      };
    }
    return {
      kind: "advanced",
      route: probed.route,
      fromSlug: decision.fromSlug,
      toSlug: decision.entry.slug,
      entry: decision.entry,
      audit: {
        event: "coder_advance",
        fromModelId: decision.fromSlug,
        toModelId: decision.entry.slug,
        state_summary: suggestionToken,
        ts,
      },
    };
  }

  return {
    kind: "advanced",
    route: candidate,
    fromSlug: decision.fromSlug,
    toSlug: decision.entry.slug,
    entry: decision.entry,
    audit: {
      event: "coder_advance",
      fromModelId: decision.fromSlug,
      toModelId: decision.entry.slug,
      state_summary: suggestionToken,
      ts,
    },
  };
}

/**
 * Repair seat a family-ledger `coder_advance*` row applied to.
 * Online-review sticky re-hold and CMR coderFix must not cross-bleed (#1017 R2).
 */
export type AdvanceRepairSeat = "coderFix" | "fixer";

/**
 * Dual status/event audit fields for family ledger advance rows.
 * Shared by online-review fixer + family CMR coderFix courts (#919 / #1002).
 * Callers spread court-only extras (phase / cmrPass) on top — no framework.
 * `advanceSeat` is required so sticky rebuild can scope by court.
 */
export function familyAdvanceCoderAuditFields(
  effect: Extract<AdvanceCoderEffectResult, { kind: "stay_put" | "advanced" }>,
  suggestion: string,
  advanceSeat: AdvanceRepairSeat,
): {
  readonly status: "coder_advance" | "coder_advance_stay_put";
  readonly event: "coder_advance" | "coder_advance_stay_put";
  readonly reason: string;
  readonly message: string | undefined;
  readonly fromModelId: string;
  readonly toModelId: string;
  readonly advanceCoder: string;
  readonly advanceSeat: AdvanceRepairSeat;
  readonly ts: string;
} {
  return {
    status: effect.audit.event,
    event: effect.audit.event,
    reason: effect.kind === "stay_put" ? effect.reason : "coder_advance",
    message: effect.audit.state_summary,
    fromModelId: effect.audit.fromModelId,
    toModelId: effect.audit.toModelId,
    advanceCoder: suggestion.trim(),
    advanceSeat,
    ts: effect.audit.ts,
  };
}

/**
 * Latest successful `coder_advance` target slug from a ledger scan
 * (newest-first), scoped to one repair seat. Ignores stay_put and rows for
 * other seats (or legacy unscoped rows — fail closed on re-hold).
 * Online-review sticky fixer rebuild (#1002 / #1017 R2).
 */
export function latestCoderAdvanceToSlug(
  ledger: ReadonlyArray<{
    readonly event?: string;
    readonly status?: string;
    readonly toModelId?: string;
    readonly advanceSeat?: string;
  }>,
  seat: AdvanceRepairSeat,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const row = ledger[i]!;
    const isAdvance =
      row.event === "coder_advance" || row.status === "coder_advance";
    if (
      isAdvance &&
      row.advanceSeat === seat &&
      typeof row.toModelId === "string" &&
      row.toModelId.length > 0
    ) {
      return row.toModelId;
    }
  }
  return undefined;
}
