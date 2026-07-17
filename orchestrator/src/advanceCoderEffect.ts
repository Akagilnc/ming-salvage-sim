/**
 * #919 / #926 / #930 — one advanceCoder execution path for both courts.
 *
 * Topology law lives here once:
 *   resolveAdvanceCoderSuggestion → applySlug → optional probe → advanced | stay_put | noop
 *
 * Callers own only: audit persistence + sticky seat state. Never terminal on
 * bad advance (slice S3/S6 and family CMR continue share this contract).
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
 * `applySlug` is the only court difference:
 *   - single-slice S3/S6 → rewrite coder + coderFix
 *   - family CMR continue → rewrite coderFix only
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
