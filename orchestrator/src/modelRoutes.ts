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

export type ModelRouteSlot = (typeof MODEL_ROUTE_SLOTS)[number];
export type ModelSlotMap = Readonly<Record<ModelRouteSlot, string>>;
export type ModelRouteOverrides = Readonly<Partial<Record<ModelRouteSlot, string>>>;
export type ModelRouteEnv = Readonly<Record<string, string | undefined>>;

export interface TightFamilyViolation {
  readonly slot: ModelRouteSlot;
  readonly slug: string;
  readonly family: ModelFamily;
}

export interface ResolvedModelRoute {
  readonly routeName: string;
  readonly slots: ModelSlotMap;
  readonly tightFamilyViolations: ReadonlyArray<TightFamilyViolation>;
}

interface ModelRoutePreset {
  readonly slots: ModelSlotMap;
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

const ROUTE_PRESETS: Readonly<Record<string, ModelRoutePreset>> = {
  normal: { slots: NORMAL_SLOTS },
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
  },
};

const SLOT_SET = new Set<string>(MODEL_ROUTE_SLOTS);
const ENV_BY_SLOT: Readonly<Record<ModelRouteSlot, string>> = {
  coder: "ORCHESTRATOR_CODER_MODEL",
  reviewer: "ORCHESTRATOR_REVIEWER_MODEL",
  coderFix: "ORCHESTRATOR_CODER_FIX_MODEL",
  ship: "ORCHESTRATOR_SHIP_MODEL",
  merger: "ORCHESTRATOR_MERGER_MODEL",
  cmrCompleteness: "ORCHESTRATOR_CMR_COMPLETENESS_MODEL",
  cmrCorrectness: "ORCHESTRATOR_CMR_CORRECTNESS_MODEL",
};

function assertKnownSlot(slot: string): asserts slot is ModelRouteSlot {
  if (!SLOT_SET.has(slot)) {
    throw new Error(`unknown model slot "${slot}"`);
  }
}

function assertKnownSlug(slug: string): void {
  resolveModelSlug(slug);
}

function tightFamilyViolations(
  slots: ModelSlotMap,
  tightFamilies: ReadonlyArray<ModelFamily>,
): TightFamilyViolation[] {
  const tight = new Set(tightFamilies);
  const violations: TightFamilyViolation[] = [];
  for (const slot of MODEL_ROUTE_SLOTS) {
    const slug = slots[slot];
    const family = modelFamilyForSlug(slug);
    if (tight.has(family)) violations.push({ slot, slug, family });
  }
  return violations;
}

export function resolveRouteModels(
  routeName: string,
  overrides: Readonly<Record<string, string | undefined>>,
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
    assertKnownSlug(rawSlug.trim());
    slots[rawSlot] = rawSlug.trim();
  }

  for (const slot of MODEL_ROUTE_SLOTS) assertKnownSlug(slots[slot]);

  return {
    routeName: trimmedRoute,
    slots,
    tightFamilyViolations: tightFamilyViolations(
      slots,
      preset.tightFamilies ?? [],
    ),
  };
}

export function printableRouteLineup(route: ResolvedModelRoute): string {
  return [
    `route=${route.routeName}`,
    ...MODEL_ROUTE_SLOTS.map((slot) => `${slot}=${route.slots[slot]}`),
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

export function activeModelRoute(
  env: ModelRouteEnv = process.env,
): ResolvedModelRoute {
  const route = resolveRouteModels(
    env.ORCHESTRATOR_ROUTE?.trim() || "normal",
    routeOverridesFromEnv(env),
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
