import { createInterface } from "node:readline/promises";

import {
  modelFamilyForCmrReviewLeg,
  modelFamilyForSlug,
  resolveModelSlug,
  type ModelFamily,
} from "./modelRegistry.js";

export const MODEL_ROUTE_SLOTS = [
  "coder",
  "reviewer",
  "coderFix",
  "ship",
  "merger",
  "cmrCompleteness",
  "cmrCorrectness",
  "verify",
  "fixer",
  "cleanup",
  "docRelease",
] as const;

export const MODEL_ROUTE_LEG_COLLECTIONS = ["cmrReview"] as const;

export type ModelRouteSlot = (typeof MODEL_ROUTE_SLOTS)[number];
export type ModelRouteLegCollection = (typeof MODEL_ROUTE_LEG_COLLECTIONS)[number];
export type ModelSlotMap = Readonly<Record<ModelRouteSlot, string>>;
export interface ModelRouteLeg {
  readonly family: ModelFamily;
  readonly slug: string;
}
export type ModelRouteLegCollectionMap = Readonly<
  Record<ModelRouteLegCollection, ReadonlyArray<ModelRouteLeg>>
>;
export type ModelRouteOverrides = Readonly<Partial<Record<ModelRouteSlot, string>>>;
export type ModelRouteLegCollectionOverrides = Readonly<
  Partial<Record<ModelRouteLegCollection, ReadonlyArray<string>>>
>;
export type ModelRouteEnv = Readonly<Record<string, string | undefined>>;
export type CmrLegAccountingRoute =
  | ResolvedModelRoute
  | ModelRouteEnv
  | ReadonlyArray<{ readonly slug: string }>
  | null
  | undefined;

export interface TightFamilyViolation {
  readonly slot: ModelRouteSlot | ModelRouteLegCollection;
  readonly slug: string;
  readonly family: ModelFamily;
}

export interface ResolvedModelRoute {
  readonly routeName: string;
  readonly slots: ModelSlotMap;
  readonly legCollections: ModelRouteLegCollectionMap;
  readonly tightFamilyViolations: ReadonlyArray<TightFamilyViolation>;
}

export interface TightRoutePolicyStop {
  readonly kind: "stop";
  readonly escalation: {
    readonly reason: string;
    readonly diagnosis: string;
  };
}

export type TightRoutePolicyDecision =
  | { readonly kind: "continue"; readonly route: ResolvedModelRoute }
  | TightRoutePolicyStop;

interface ModelRoutePreset {
  readonly slots: ModelSlotMap;
  readonly legCollections: ModelRouteLegCollectionMap;
  readonly tightFamilies?: ReadonlyArray<ModelFamily>;
}

const NORMAL_SLOTS: ModelSlotMap = {
  coder: "sonnet",
  reviewer: "gpt-5.5",
  coderFix: "sonnet",
  ship: "sonnet",
  merger: "sonnet",
  cmrCompleteness: "opus",
  cmrCorrectness: "opus",
  verify: "opus",
  fixer: "sonnet",
  cleanup: "sonnet",
  docRelease: "sonnet",
};

const NORMAL_LEG_COLLECTIONS: ModelRouteLegCollectionMap = {
  cmrReview: [
    { family: "codex", slug: "gpt-5.5" },
    { family: "claude", slug: "opus" },
    { family: "agy", slug: "agy" },
  ],
};

const ROUTE_PRESETS: Readonly<Record<string, ModelRoutePreset>> = {
  normal: { slots: NORMAL_SLOTS, legCollections: NORMAL_LEG_COLLECTIONS },
  "codex-cheap": {
    slots: {
      coder: "sonnet",
      reviewer: "opus",
      coderFix: "sonnet",
      ship: "sonnet",
      merger: "sonnet",
      cmrCompleteness: "opus",
      cmrCorrectness: "opus",
      verify: "opus",
      fixer: "sonnet",
      cleanup: "sonnet",
      docRelease: "sonnet",
    },
    legCollections: {
      cmrReview: [
        { family: "claude", slug: "opus" },
        { family: "agy", slug: "agy" },
        { family: "codex", slug: "gpt-5.5" },
      ],
    },
  },
  "codex-tight": {
    tightFamilies: ["codex"],
    slots: {
      coder: "sonnet",
      reviewer: "opus",
      coderFix: "sonnet",
      ship: "sonnet",
      merger: "sonnet",
      cmrCompleteness: "opus",
      cmrCorrectness: "opus",
      verify: "opus",
      fixer: "sonnet",
      cleanup: "sonnet",
      docRelease: "sonnet",
    },
    legCollections: {
      cmrReview: [
        { family: "claude", slug: "opus" },
        { family: "agy", slug: "agy" },
      ],
    },
  },
  "claude-cheap": {
    slots: {
      coder: "gpt-5.5",
      reviewer: "gpt-5.5",
      coderFix: "gpt-5.5",
      ship: "gpt-5.5",
      merger: "gpt-5.5",
      cmrCompleteness: "gpt-5.5",
      cmrCorrectness: "gpt-5.5",
      verify: "gpt-5.5",
      fixer: "gpt-5.5",
      cleanup: "gpt-5.5",
      docRelease: "gpt-5.5",
    },
    legCollections: {
      cmrReview: [
        { family: "codex", slug: "gpt-5.5" },
        { family: "agy", slug: "agy" },
        { family: "claude", slug: "opus" },
      ],
    },
  },
  "claude-tight": {
    tightFamilies: ["claude"],
    slots: {
      coder: "gpt-5.5",
      reviewer: "gpt-5.5",
      coderFix: "gpt-5.5",
      ship: "gpt-5.5",
      merger: "gpt-5.5",
      cmrCompleteness: "gpt-5.5",
      cmrCorrectness: "gpt-5.5",
      verify: "gpt-5.5",
      fixer: "gpt-5.5",
      cleanup: "gpt-5.5",
      docRelease: "gpt-5.5",
    },
    legCollections: {
      cmrReview: [
        { family: "codex", slug: "gpt-5.5" },
        { family: "agy", slug: "agy" },
      ],
    },
  },
};

const SLOT_SET = new Set<string>(MODEL_ROUTE_SLOTS);
const LEG_COLLECTION_SET = new Set<string>(MODEL_ROUTE_LEG_COLLECTIONS);
const ENV_BY_SLOT: Readonly<Record<ModelRouteSlot, string>> = {
  coder: "ORCHESTRATOR_CODER_MODEL",
  reviewer: "ORCHESTRATOR_REVIEWER_MODEL",
  coderFix: "ORCHESTRATOR_CODER_FIX_MODEL",
  ship: "ORCHESTRATOR_SHIP_MODEL",
  merger: "ORCHESTRATOR_MERGER_MODEL",
  cmrCompleteness: "ORCHESTRATOR_CMR_COMPLETENESS_MODEL",
  cmrCorrectness: "ORCHESTRATOR_CMR_CORRECTNESS_MODEL",
  verify: "ORCHESTRATOR_VERIFY_MODEL",
  fixer: "ORCHESTRATOR_FIXER_MODEL",
  cleanup: "ORCHESTRATOR_CLEANUP_MODEL",
  docRelease: "ORCHESTRATOR_DOCRELEASE_MODEL",
};
const ENV_BY_LEG_COLLECTION: Readonly<Record<ModelRouteLegCollection, string>> = {
  cmrReview: "ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS",
};

function assertKnownSlot(slot: string): asserts slot is ModelRouteSlot {
  if (!SLOT_SET.has(slot)) {
    throw new Error(`unknown model slot "${slot}"`);
  }
}

function assertKnownLegCollection(
  collection: string,
): asserts collection is ModelRouteLegCollection {
  if (!LEG_COLLECTION_SET.has(collection)) {
    throw new Error(`unknown model leg collection "${collection}"`);
  }
}

function assertKnownWorkerSlug(slug: string): void {
  resolveModelSlug(slug);
}

function legForSlug(slug: string): ModelRouteLeg {
  const trimmed = slug.trim();
  return { slug: trimmed, family: modelFamilyForCmrReviewLeg(trimmed) };
}

function resolveLegCollection(slugs: ReadonlyArray<string>): ReadonlyArray<ModelRouteLeg> {
  return slugs
    .map((slug) => slug.trim())
    .filter((slug) => slug !== "")
    .map(legForSlug);
}

function tightFamilyViolations(
  slots: ModelSlotMap,
  legCollections: ModelRouteLegCollectionMap,
  tightFamilies: ReadonlyArray<ModelFamily>,
): TightFamilyViolation[] {
  const tight = new Set(tightFamilies);
  const violations: TightFamilyViolation[] = [];
  for (const slot of MODEL_ROUTE_SLOTS) {
    const slug = slots[slot];
    const family = modelFamilyForSlug(slug);
    if (tight.has(family)) violations.push({ slot, slug, family });
  }
  for (const collection of MODEL_ROUTE_LEG_COLLECTIONS) {
    for (const leg of legCollections[collection]) {
      if (tight.has(leg.family)) {
        violations.push({
          slot: collection,
          slug: leg.slug,
          family: leg.family,
        });
      }
    }
  }
  return violations;
}

export function resolveRouteModels(
  routeName: string,
  overrides: Readonly<Record<string, string | undefined>>,
  legCollectionOverrides: Readonly<Record<string, ReadonlyArray<string> | undefined>> = {},
): ResolvedModelRoute {
  const trimmedRoute = routeName.trim() || "normal";
  const preset = ROUTE_PRESETS[trimmedRoute];
  if (preset === undefined) {
    throw new Error(`unknown route "${trimmedRoute}"`);
  }

  const slots: Record<ModelRouteSlot, string> = { ...preset.slots };
  for (const [rawSlot, rawSlug] of Object.entries(overrides)) {
    if (rawSlug === undefined || rawSlug.trim() === "") continue;
    assertKnownSlot(rawSlot);
    assertKnownWorkerSlug(rawSlug.trim());
    slots[rawSlot] = rawSlug.trim();
  }

  const legCollections: Record<ModelRouteLegCollection, ReadonlyArray<ModelRouteLeg>> = {
    ...preset.legCollections,
  };
  for (const [rawCollection, rawSlugs] of Object.entries(legCollectionOverrides)) {
    if (rawSlugs === undefined) continue;
    assertKnownLegCollection(rawCollection);
    const resolved = resolveLegCollection(rawSlugs);
    if (resolved.length === 0) {
      throw new Error(`empty model leg collection "${rawCollection}"`);
    }
    legCollections[rawCollection] = resolved;
  }

  for (const slot of MODEL_ROUTE_SLOTS) assertKnownWorkerSlug(slots[slot]);
  for (const collection of MODEL_ROUTE_LEG_COLLECTIONS) {
    legCollections[collection] = legCollections[collection].map((leg) => {
      const family = modelFamilyForCmrReviewLeg(leg.slug);
      if (family !== leg.family) {
        throw new Error(
          `cmr review leg "${leg.slug}" declares family "${leg.family}" but registry says "${family}"`,
        );
      }
      return leg;
    });
  }

  return {
    routeName: trimmedRoute,
    slots,
    legCollections,
    tightFamilyViolations: tightFamilyViolations(
      slots,
      legCollections,
      preset.tightFamilies ?? [],
    ),
  };
}

export function printableRouteLineup(route: ResolvedModelRoute): string {
  return [
    `route=${route.routeName}`,
    ...MODEL_ROUTE_SLOTS.map((slot) => `${slot}=${route.slots[slot]}`),
    ...MODEL_ROUTE_LEG_COLLECTIONS.map(
      (collection) =>
        `${collection}=[${route.legCollections[collection]
          .map((leg) => `${leg.family}:${leg.slug}`)
          .join(",")}]`,
    ),
  ].join("\n");
}

export function modelRouteFingerprint(route: ResolvedModelRoute): string {
  return JSON.stringify({
    routeName: route.routeName,
    slots: MODEL_ROUTE_SLOTS.map((slot) => [slot, route.slots[slot]]),
    legCollections: MODEL_ROUTE_LEG_COLLECTIONS.map((collection) => [
      collection,
      route.legCollections[collection].map((leg) => [leg.family, leg.slug]),
    ]),
  });
}

export function tightRouteViolationDetails(route: ResolvedModelRoute): string {
  return route.tightFamilyViolations
    .map((v) => `${v.slot}=${v.slug}(${v.family})`)
    .join(", ");
}

export function routeOverridesFromEnv(env: ModelRouteEnv): ModelRouteOverrides {
  const overrides: Partial<Record<ModelRouteSlot, string>> = {};
  for (const slot of MODEL_ROUTE_SLOTS) {
    const value = env[ENV_BY_SLOT[slot]]?.trim();
    if (value !== undefined && value !== "") overrides[slot] = value;
  }
  return overrides;
}

export function routeLegCollectionOverridesFromEnv(
  env: ModelRouteEnv,
): ModelRouteLegCollectionOverrides {
  const overrides: Partial<Record<ModelRouteLegCollection, ReadonlyArray<string>>> =
    {};
  for (const collection of MODEL_ROUTE_LEG_COLLECTIONS) {
    const value = env[ENV_BY_LEG_COLLECTION[collection]]?.trim();
    if (value !== undefined && value !== "") {
      if (value.startsWith("[") || value.startsWith("{")) {
        throw new Error(
          `${ENV_BY_LEG_COLLECTION[collection]} must be comma-separated CMR leg slugs, not JSON; ` +
            "repair_hint: rewrite the route env as CSV, for example gpt-5.5,agy",
        );
      }
      overrides[collection] = value
        .split(",")
        .map((slug) => slug.trim().replace(/^["']|["']$/g, ""))
        .filter((slug) => slug !== "");
    }
  }
  return overrides;
}

export function activeModelRoute(
  env: ModelRouteEnv = process.env,
): ResolvedModelRoute {
  const route = resolveActiveModelRoute(env);
  if (route.tightFamilyViolations.length > 0) {
    throw new Error(
      `tight route violation for ${route.routeName}: ${tightRouteViolationDetails(route)}`,
    );
  }
  return route;
}

export function resolveActiveModelRoute(
  env: ModelRouteEnv = process.env,
): ResolvedModelRoute {
  return resolveRouteModels(
    env.ORCHESTRATOR_ROUTE?.trim() || "normal",
    routeOverridesFromEnv(env),
    routeLegCollectionOverridesFromEnv(env),
  );
}

export function applyTightRoutePolicy(
  route: ResolvedModelRoute,
  opts: {
    readonly interactive?: boolean;
    readonly warn?: (message: string) => void;
    readonly confirm?: (message: string) => boolean;
  } = {},
): TightRoutePolicyDecision {
  if (route.tightFamilyViolations.length > 0) {
    const details = tightRouteViolationDetails(route);
    const message = `tight route violation for ${route.routeName}: ${details}`;
    if (opts.interactive === true) {
      opts.warn?.(message);
      if (opts.confirm?.(message) === true) {
        return { kind: "continue", route };
      }
    }
    return {
      kind: "stop",
      escalation: {
        reason: "tight route violation",
        diagnosis:
          `${message}. Non-interactive orchestrator startup stops instead of ` +
          "crashing or silently continuing; rerun with a route/model override " +
          "that preserves the tight-family invariant, or explicitly confirm in an interactive run.",
      },
    };
  }
  return { kind: "continue", route };
}

export async function applyRuntimeTightRoutePolicy(
  route: ResolvedModelRoute,
  opts: {
    readonly interactive?: boolean;
    readonly warn?: (message: string) => void;
    readonly confirm?: (message: string) => boolean | Promise<boolean>;
  } = {},
): Promise<TightRoutePolicyDecision> {
  if (route.tightFamilyViolations.length === 0) {
    return { kind: "continue", route };
  }
  const message = `tight route violation for ${route.routeName}: ${tightRouteViolationDetails(route)}`;
  if (opts.interactive === true) {
    opts.warn?.(message);
    const confirmed = await (opts.confirm ?? askContinue)(message);
    if (confirmed) return { kind: "continue", route };
  }
  return applyTightRoutePolicy(route, { interactive: false });
}

async function askContinue(message: string): Promise<boolean> {
  const rl = createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  try {
    const answer = await rl.question(`${message}\nContinue anyway? [y/N] `);
    return /^(y|yes)$/i.test(answer.trim());
  } finally {
    rl.close();
  }
}

export function modelForSlot(
  slot: ModelRouteSlot,
  env: ModelRouteEnv = process.env,
): string {
  return resolveActiveModelRoute(env).slots[slot];
}

export function cmrReviewLegs(
  env: ModelRouteEnv = process.env,
): ReadonlyArray<ModelRouteLeg> {
  return resolveActiveModelRoute(env).legCollections.cmrReview;
}

function isResolvedModelRoute(value: unknown): value is ResolvedModelRoute {
  if (value === null || typeof value !== "object") return false;
  const candidate = value as Partial<ResolvedModelRoute>;
  return (
    candidate.slots !== undefined &&
    candidate.slots !== null &&
    typeof candidate.slots === "object" &&
    candidate.legCollections !== undefined &&
    candidate.legCollections !== null &&
    typeof candidate.legCollections === "object" &&
    Array.isArray(candidate.legCollections.cmrReview) &&
    Array.isArray(candidate.tightFamilyViolations)
  );
}

function isCmrLegArray(
  value: CmrLegAccountingRoute,
): value is ReadonlyArray<{ readonly slug: string }> {
  return Array.isArray(value);
}

export function cmrLegAccountingFailure(
  input: {
    readonly successfulLegs: readonly string[];
    readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
  },
  routeOrEnv: CmrLegAccountingRoute = process.env,
): string | undefined {
  const declaredLegs = isCmrLegArray(routeOrEnv)
    ? routeOrEnv.map((leg) => leg.slug)
    : isResolvedModelRoute(routeOrEnv)
      ? routeOrEnv.legCollections.cmrReview.map((leg) => leg.slug)
      : cmrReviewLegs(routeOrEnv ?? process.env).map((leg) => leg.slug);
  const declared = new Set(declaredLegs);
  const undeclaredSuccessful = input.successfulLegs.filter((slug) => !declared.has(slug));
  if (undeclaredSuccessful.length > 0) {
    return (
      "cmr worker reported successful legs that were not declared by the active route: " +
      undeclaredSuccessful.join(", ")
    );
  }
  const undeclaredSkipped = (input.skippedLegs ?? [])
    .map((leg) => leg.slug)
    .filter((slug) => !declared.has(slug));
  if (undeclaredSkipped.length > 0) {
    return (
      "cmr worker reported skipped legs that were not declared by the active route: " +
      undeclaredSkipped.join(", ")
    );
  }
  const duplicateSuccessful = input.successfulLegs.filter(
    (slug, index, legs) => legs.indexOf(slug) !== index,
  );
  if (duplicateSuccessful.length > 0) {
    return (
      "cmr worker reported duplicate successful legs: " +
      [...new Set(duplicateSuccessful)].join(", ")
    );
  }
  const skippedSlugs = (input.skippedLegs ?? []).map((leg) => leg.slug);
  const duplicateSkipped = skippedSlugs.filter(
    (slug, index, legs) => legs.indexOf(slug) !== index,
  );
  if (duplicateSkipped.length > 0) {
    return (
      "cmr worker reported duplicate skipped legs: " +
      [...new Set(duplicateSkipped)].join(", ")
    );
  }
  const successful = new Set(input.successfulLegs);
  const skipped = new Set(skippedSlugs);
  const missing = declaredLegs.filter((slug) => !successful.has(slug) && !skipped.has(slug));
  if (missing.length > 0) {
    return (
      "cmr worker omitted declared leg accounting for: " +
      `${missing.join(", ")} (each active-route cmr leg must be successful or skipped)`
    );
  }
  const doubleReported = declaredLegs.filter((slug) => successful.has(slug) && skipped.has(slug));
  if (doubleReported.length > 0) {
    return (
      "cmr worker reported declared leg as both successful and skipped: " +
      doubleReported.join(", ")
    );
  }
  return undefined;
}
