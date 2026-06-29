import {
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

interface ModelRoutePreset {
  readonly slots: ModelSlotMap;
  readonly legCollections: ModelRouteLegCollectionMap;
  readonly tightFamilies?: ReadonlyArray<ModelFamily>;
}

const NORMAL_SLOTS: ModelSlotMap = {
  coder: "gpt-5.5",
  reviewer: "gpt-5.5",
  coderFix: "gpt-5.5",
  ship: "sonnet",
  merger: "opus",
  cmrCompleteness: "opus",
  cmrCorrectness: "opus",
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
  "codex-tight": {
    tightFamilies: ["codex"],
    slots: {
      coder: "sonnet",
      reviewer: "opus",
      coderFix: "sonnet",
      ship: "sonnet",
      merger: "opus",
      cmrCompleteness: "opus",
      cmrCorrectness: "opus",
    },
    legCollections: {
      cmrReview: [
        { family: "claude", slug: "opus" },
        { family: "agy", slug: "agy" },
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
  return { slug: trimmed, family: modelFamilyForSlug(trimmed) };
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
      overrides[collection] = value
        .split(",")
        .map((slug) => slug.trim())
        .filter((slug) => slug !== "");
    }
  }
  return overrides;
}

export function activeModelRoute(
  env: ModelRouteEnv = process.env,
): ResolvedModelRoute {
  const route = resolveRouteModels(
    env.ORCHESTRATOR_ROUTE?.trim() || "normal",
    routeOverridesFromEnv(env),
    routeLegCollectionOverridesFromEnv(env),
  );
  if (route.tightFamilyViolations.length > 0) {
    const details = route.tightFamilyViolations
      .map((v) => `${v.slot}=${v.slug}(${v.family})`)
      .join(", ");
    throw new Error(
      `tight route violation for ${route.routeName}: ${details}`,
    );
  }
  return route;
}

export function modelForSlot(
  slot: ModelRouteSlot,
  env: ModelRouteEnv = process.env,
): string {
  return activeModelRoute(env).slots[slot];
}

export function cmrReviewLegs(
  env: ModelRouteEnv = process.env,
): ReadonlyArray<ModelRouteLeg> {
  return activeModelRoute(env).legCollections.cmrReview;
}
