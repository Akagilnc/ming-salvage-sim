import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  parseCoderRec,
  resolveCoderRecOrder,
  selectCoderRecEntry,
  type CoderRosterEntry,
} from "./coderRoster.js";
import {
  modelFamilyForCmrReviewLeg,
  modelFamilyForSlug,
  resolveModelSlug,
  type ModelFamily,
} from "./modelRegistry.js";
import {
  billingPoolForModelRef,
  type BillingPoolId,
  type NextRelayBaton,
} from "./quotaPoolTable.js";
import { isJudgeSeat } from "./judgeStation.js";
import type { StepId } from "./types.js";

export type RouteSmokeStatus =
  | { readonly state: "unverified" }
  | {
      readonly state: "passed";
      readonly at: string;
      readonly cliVersion: string;
    }
  | {
      readonly state: "failed";
      readonly at: string;
      readonly error: string;
    };

export interface RouteSmokeEntry {
  readonly key: string;
  readonly slug: string;
  readonly family: ModelFamily;
}

export interface RouteSmokeExecutionInput {
  readonly key: string;
  readonly slug: string;
  readonly family: ModelFamily;
  readonly command: "echo OK";
}

export type RouteSmokeExecutor = (
  input: RouteSmokeExecutionInput,
) => Promise<{ readonly cliVersion: string }>;

export const DEFAULT_ROUTE_SMOKE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

// #923: reviewer model-route slot retired — verify is the sole judge identity
// staffing both single-slice S3/S6 openings and the verify station. Worker role
// / cargo kind "reviewer" and leg souls remain separate from this slot table.
export const MODEL_ROUTE_SLOTS = [
  "coder",
  "coderFix",
  "ship",
  "merger",
  "cmrCompleteness",
  "cmrCorrectness",
  "collector",
  "verify",
  "fixer",
  "cleanup",
  "landing",
] as const;

export const MODEL_ROUTE_LEG_COLLECTIONS = ["cmrReview"] as const;

const SLOT_SET = new Set<string>(MODEL_ROUTE_SLOTS);
const LEG_COLLECTION_SET = new Set<string>(MODEL_ROUTE_LEG_COLLECTIONS);

export type ModelRouteSlot = (typeof MODEL_ROUTE_SLOTS)[number];
export type ModelRouteLegCollection = (typeof MODEL_ROUTE_LEG_COLLECTIONS)[number];
export type ModelSlotMap = Readonly<Record<ModelRouteSlot, string>>;
export interface ModelRouteLeg {
  readonly family: ModelFamily;
  readonly slug: string;
  /** Best-effort preset leg. Programmatic non-preset legs omit this marker. */
  readonly optional?: true;
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
  /**
   * Tight families captured at resolve time from the presets table that
   * produced this route. Mutations must reuse this snapshot — never re-fetch
   * via process.env (custom ORCHESTRATOR_ROUTE_PRESETS_PATH only in the
   * resolve env arg would otherwise drop policy to []).
   */
  readonly tightFamilies: ReadonlyArray<ModelFamily>;
  readonly tightFamilyViolations: ReadonlyArray<TightFamilyViolation>;
  /** One smoke record for every model×pipe entry in this route. */
  readonly smoke: Readonly<Record<string, RouteSmokeStatus>>;
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

/** Env override for the route-presets config path (#916). */
export const ROUTE_PRESETS_PATH_ENV = "ORCHESTRATOR_ROUTE_PRESETS_PATH";

const DEFAULT_ROUTE_PRESETS_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "config",
  "route-presets.json",
);

const MODEL_FAMILIES = new Set<ModelFamily>(["claude", "codex", "agy", "other"]);

let cachedRoutePresets: Readonly<Record<string, ModelRoutePreset>> | undefined;
let cachedRoutePresetsPath: string | undefined;

/** Test-only: drop the loaded presets cache after path/env mutations. */
export function resetRoutePresetsCacheForTests(): void {
  cachedRoutePresets = undefined;
  cachedRoutePresetsPath = undefined;
}

function resolveRoutePresetsPath(env: ModelRouteEnv = process.env): string {
  const override = env[ROUTE_PRESETS_PATH_ENV]?.trim();
  if (override !== undefined && override !== "") {
    return isAbsolute(override) ? override : join(process.cwd(), override);
  }
  return DEFAULT_ROUTE_PRESETS_PATH;
}

function parseRoutePresetLeg(raw: unknown, routeName: string): ModelRouteLeg {
  if (typeof raw !== "object" || raw === null) {
    throw new Error(
      `route preset "${routeName}": cmrReview leg must be an object with slug`,
    );
  }
  const record = raw as Record<string, unknown>;
  if (typeof record.slug !== "string" || record.slug.trim() === "") {
    throw new Error(`route preset "${routeName}": cmrReview leg missing slug`);
  }
  const slug = record.slug.trim();
  // family omitted → derive from registry. family present but not a known
  // ModelFamily → fail-loud (Gemini R2 G3 / family/914 online). Do not
  // silently fall back to modelFamilyForSlug on typos like "openai".
  let family: ModelFamily;
  if (record.family === undefined) {
    family = modelFamilyForSlug(slug);
  } else if (
    typeof record.family === "string" &&
    MODEL_FAMILIES.has(record.family as ModelFamily)
  ) {
    family = record.family as ModelFamily;
  } else {
    throw new Error(
      `route preset "${routeName}": cmrReview leg "${slug}" has invalid family ` +
        `"${String(record.family)}"`,
    );
  }
  if (record.optional === true) {
    return { family, slug, optional: true };
  }
  return { family, slug };
}

function parseRoutePreset(
  routeName: string,
  raw: unknown,
): ModelRoutePreset {
  if (typeof raw !== "object" || raw === null) {
    throw new Error(`route preset "${routeName}" must be an object`);
  }
  const record = raw as Record<string, unknown>;
  if (typeof record.slots !== "object" || record.slots === null) {
    throw new Error(`route preset "${routeName}" missing slots`);
  }
  const slotsRaw = record.slots as Record<string, unknown>;
  const slots = {} as Record<ModelRouteSlot, string>;
  for (const slot of MODEL_ROUTE_SLOTS) {
    const value = slotsRaw[slot];
    if (typeof value !== "string" || value.trim() === "") {
      throw new Error(`route preset "${routeName}" missing slot "${slot}"`);
    }
    slots[slot] = value.trim();
  }
  for (const key of Object.keys(slotsRaw)) {
    if (!SLOT_SET.has(key)) {
      throw new Error(`route preset "${routeName}" has unknown slot "${key}"`);
    }
  }

  // Single nested form only (#916): legCollections.cmrReview. No top-level
  // cmrReview fallback — dual schema roots are a hand-sync surface.
  if (typeof record.legCollections !== "object" || record.legCollections === null) {
    throw new Error(`route preset "${routeName}" missing legCollections`);
  }
  const legsRoot = record.legCollections as Record<string, unknown>;
  // Mirror SLOT_SET: reject unknown keys (Gemini R2 G4 / family/914 online).
  for (const key of Object.keys(legsRoot)) {
    if (!LEG_COLLECTION_SET.has(key)) {
      throw new Error(
        `route preset "${routeName}" has unknown legCollection "${key}"`,
      );
    }
  }
  const cmrRaw = legsRoot.cmrReview;
  if (!Array.isArray(cmrRaw) || cmrRaw.length === 0) {
    throw new Error(`route preset "${routeName}" missing non-empty cmrReview legs`);
  }
  const cmrReview = cmrRaw.map((leg) => parseRoutePresetLeg(leg, routeName));

  let tightFamilies: ReadonlyArray<ModelFamily> | undefined;
  if (record.tightFamilies !== undefined) {
    if (!Array.isArray(record.tightFamilies)) {
      throw new Error(`route preset "${routeName}" tightFamilies must be an array`);
    }
    tightFamilies = record.tightFamilies.map((family) => {
      if (typeof family !== "string" || !MODEL_FAMILIES.has(family as ModelFamily)) {
        throw new Error(
          `route preset "${routeName}" has unknown tight family "${String(family)}"`,
        );
      }
      return family as ModelFamily;
    });
  }

  return {
    slots,
    legCollections: { cmrReview },
    ...(tightFamilies !== undefined ? { tightFamilies } : {}),
  };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * One-time on-disk migration for external route presets missing `collector`.
 *
 * Production docs point `ORCHESTRATOR_ROUTE_PRESETS_PATH` at an owner-edited
 * external file. When `collector` became a required slot, existing custom files
 * without that key would fail strict parse before worksite creation. Materialize
 * `collector` into the file once only when the key is absent (prefer same-named
 * factory preset, else factory `normal`, else shipped default slug) — never
 * rewrite explicit values (`null`, `""`, whitespace, numbers, …) and never
 * default/alias at runtime inside `parseRoutePreset`.
 */
function materializeCollectorSlotInExternalPresetsFile(path: string): void {
  if (path === DEFAULT_ROUTE_PRESETS_PATH) return;
  if (!existsSync(path)) return;

  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    // Let loadRoutePresetsFromFile fail-loud on unreadable JSON.
    return;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return;
  }

  let factoryCollectorByRoute = new Map<string, string>();
  let factoryNormalCollector: string | undefined;
  try {
    if (existsSync(DEFAULT_ROUTE_PRESETS_PATH)) {
      const factoryRaw = JSON.parse(
        readFileSync(DEFAULT_ROUTE_PRESETS_PATH, "utf8"),
      ) as unknown;
      if (
        typeof factoryRaw === "object" &&
        factoryRaw !== null &&
        !Array.isArray(factoryRaw)
      ) {
        for (const [name, value] of Object.entries(
          factoryRaw as Record<string, unknown>,
        )) {
          if (typeof value !== "object" || value === null) continue;
          const slots = (value as Record<string, unknown>).slots;
          if (typeof slots !== "object" || slots === null) continue;
          const collector = (slots as Record<string, unknown>).collector;
          if (typeof collector === "string" && collector.trim() !== "") {
            const trimmed = collector.trim();
            factoryCollectorByRoute.set(name, trimmed);
            if (name === "normal") factoryNormalCollector = trimmed;
          }
        }
      }
    }
  } catch {
    // Factory unreadable — fall through to shipped default slug.
  }
  const fallbackCollector = factoryNormalCollector ?? "grok-4.5";

  const root = parsed as Record<string, unknown>;
  let changed = false;
  for (const [name, value] of Object.entries(root)) {
    if (typeof value !== "object" || value === null) continue;
    const preset = value as Record<string, unknown>;
    if (typeof preset.slots !== "object" || preset.slots === null) continue;
    const slots = preset.slots as Record<string, unknown>;
    // Only absent-key is omission. Explicit null/""/whitespace/number stay so
    // parseRoutePreset's strict slot validation rejects them unchanged.
    if (Object.prototype.hasOwnProperty.call(slots, "collector")) {
      continue;
    }
    slots.collector =
      factoryCollectorByRoute.get(name) ?? fallbackCollector;
    changed = true;
  }
  if (!changed) return;
  writeFileSync(path, `${JSON.stringify(root, null, 2)}\n`, "utf8");
}

/**
 * Load route presets. External custom files get absent-key-only collector
 * materialization before strict parse — never a runtime alias (#1145).
 * Explicit invalid collector values remain errors under parseRoutePreset.
 */
function loadRoutePresetsFromFile(
  path: string,
): Readonly<Record<string, ModelRoutePreset>> {
  if (!existsSync(path)) {
    throw new Error(`route presets file not found: ${path}`);
  }
  // External custom file only — factory JSON is already current.
  materializeCollectorSlotInExternalPresetsFile(path);
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`failed to parse route presets at ${path}: ${detail}`);
  }
  if (!isPlainObject(parsed)) {
    throw new Error(`route presets file must be a JSON object: ${path}`);
  }
  const out: Record<string, ModelRoutePreset> = {};
  for (const [name, value] of Object.entries(parsed)) {
    out[name] = parseRoutePreset(name, value);
  }
  return out;
}

/**
 * Sole preset table = JSON on disk (#916). No hand-copied TS twin.
 *
 * Load order:
 * 1. `ORCHESTRATOR_ROUTE_PRESETS_PATH` when set (absolute or cwd-relative)
 * 2. else shipped `config/route-presets.json` next to the package
 * 3. if a custom path is missing, fall back to the shipped factory JSON only
 *    (still one file source — not a second in-code table)
 * 4. if the chosen file is absent or unreadable → fail-loud
 *
 * #936: slot/CMR env overrides are deleted; production resolve uses presets only.
 */
export function getRoutePresets(
  env: ModelRouteEnv = process.env,
): Readonly<Record<string, ModelRoutePreset>> {
  const path = resolveRoutePresetsPath(env);
  // Resolve loadPath BEFORE the cache check. Missing custom falls back to
  // DEFAULT; cache key must be the path actually loaded, otherwise every call
  // under a missing custom path recomputes loadPath=DEFAULT but checks against
  // the requested custom path → always miss → re-read factory every time.
  // Custom file appearing later changes loadPath → intentional miss → reload.
  let loadPath = path;
  if (!existsSync(path) && path !== DEFAULT_ROUTE_PRESETS_PATH) {
    loadPath = DEFAULT_ROUTE_PRESETS_PATH;
  }
  if (cachedRoutePresets !== undefined && cachedRoutePresetsPath === loadPath) {
    return cachedRoutePresets;
  }
  const fromFile = loadRoutePresetsFromFile(loadPath);
  cachedRoutePresets = fromFile;
  cachedRoutePresetsPath = loadPath;
  return fromFile;
}

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
  // Route declarations are executable live configuration. Historical CMR
  // labels remain parseable through modelFamilyForCmrReviewLeg, but can never
  // be selected as a current review worker.
  try {
    return { slug: trimmed, family: modelFamilyForSlug(trimmed) };
  } catch {
    throw new Error(
      `unknown cmr review leg slug "${trimmed}". Register a live worker in ` +
        "model-data config before selecting it in a route.",
    );
  }
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
  smokeOverrides: Readonly<Record<string, RouteSmokeStatus | undefined>> = {},
  env: ModelRouteEnv = process.env,
): ResolvedModelRoute {
  const trimmedRoute = routeName.trim() || "normal";
  const preset = getRoutePresets(env)[trimmedRoute];
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
      const family = modelFamilyForSlug(leg.slug);
      if (family !== leg.family) {
        throw new Error(
          `cmr review leg "${leg.slug}" declares family "${leg.family}" but registry says "${family}"`,
        );
      }
      return leg;
    });
  }

  const smoke: Record<string, RouteSmokeStatus> = {};
  for (const entry of routeSmokeEntries({
    slots,
    legCollections,
  })) {
    smoke[entry.key] = smokeOverrides[entry.key] ?? { state: "unverified" };
  }

  const tightFamilies = preset.tightFamilies ?? [];
  return {
    routeName: trimmedRoute,
    slots,
    legCollections,
    tightFamilies,
    tightFamilyViolations: tightFamilyViolations(
      slots,
      legCollections,
      tightFamilies,
    ),
    smoke,
  };
}

export function routeSmokeEntries(route: Pick<ResolvedModelRoute, "slots" | "legCollections">): ReadonlyArray<RouteSmokeEntry> {
  const entries: RouteSmokeEntry[] = [];
  for (const slot of MODEL_ROUTE_SLOTS) {
    const slug = route.slots[slot];
    entries.push({ key: `${slot}:${slug}`, slug, family: modelFamilyForSlug(slug) });
  }
  for (const collection of MODEL_ROUTE_LEG_COLLECTIONS) {
    for (const leg of route.legCollections[collection]) {
      entries.push({ key: `${collection}:${leg.slug}`, slug: leg.slug, family: leg.family });
    }
  }
  return entries;
}

export interface DroppedOptionalRouteLeg {
  readonly slug: string;
  readonly reason: string;
}

/** Build the run-effective route after smoke, dropping only failed preset-optional legs. */
export function degradeOptionalRouteSmokeFailures(route: ResolvedModelRoute): {
  readonly route: ResolvedModelRoute;
  readonly dropped: ReadonlyArray<DroppedOptionalRouteLeg>;
} {
  const dropped: DroppedOptionalRouteLeg[] = [];
  const legCollections: ModelRouteLegCollectionMap = {
    ...route.legCollections,
    cmrReview: route.legCollections.cmrReview.filter((leg) => {
      if (leg.optional !== true) return true;
      const status = route.smoke[`cmrReview:${leg.slug}`];
      if (status?.state !== "failed") return true;
      dropped.push({ slug: leg.slug, reason: status.error });
      return false;
    }),
  };
  return {
    route: {
      ...route,
      legCollections,
      tightFamilyViolations: route.tightFamilyViolations.filter(
        (violation) =>
          violation.slot !== "cmrReview" ||
          legCollections.cmrReview.some((leg) => leg.slug === violation.slug),
      ),
    },
    dropped,
  };
}

/**
 * Override the coder and coderFix slots together for
 * design-time Coder-Rec (#767). #920: same-model cross-role is legal — does not
 * rewrite verify / cmrReview when the coder slug overlaps those seats.
 * Preserves prior smoke status for the new slug when the same slug was already
 * smoked under another key; otherwise marks the new keys unverified so the
 * runner's route-smoke gate can (re)verify before dispatch.
 */
export function withCoderSlot(
  route: ResolvedModelRoute,
  coderSlug: string,
): ResolvedModelRoute {
  const trimmed = coderSlug.trim();
  assertKnownWorkerSlug(trimmed);
  const slots: ModelSlotMap = {
    ...route.slots,
    coder: trimmed,
    coderFix: trimmed,
  };
  const legCollections = route.legCollections;
  const next: Pick<ResolvedModelRoute, "slots" | "legCollections"> = {
    slots,
    legCollections,
  };
  const smoke: Record<string, RouteSmokeStatus> = { ...route.smoke };
  for (const entry of routeSmokeEntries(next)) {
    if (smoke[entry.key] !== undefined) continue;
    const prior = Object.entries(route.smoke).find(
      ([key, status]) =>
        key.endsWith(`:${entry.slug}`) && status.state === "passed",
    );
    smoke[entry.key] = prior?.[1] ?? { state: "unverified" };
  }
  return {
    ...route,
    slots,
    legCollections,
    tightFamilyViolations: tightFamilyViolations(
      slots,
      legCollections,
      route.tightFamilies,
    ),
    smoke,
  };
}

/**
 * Single-slice wall-step → route slot (child runner only).
 * S3/S6 → verify (#923: judge identity), S5 → coderFix, else coder. Family
 * barriers MUST NOT use this map alone: they reuse S3/S7 ids but consume cmr*
 * and ship slots.
 */
export function relaySlotForSingleSliceWallStep(
  wallStep: StepId,
): ModelRouteSlot {
  // #919 S1: sole isJudgeSeat for S3/S6 seat membership (not hand-written OR).
  if (isJudgeSeat({ step: wallStep })) return "verify";
  if (wallStep === "S5") return "coderFix";
  return "coder";
}

/**
 * #909 — family barrier wall → the ModelRouteSlot(s) that
 * {@link dispatchFamilyWorker} / WorkerSpec actually read.
 *
 * Family reuses child StepIds with different consume slots:
 *   S1 → merger (conflict-resolver agent; family telemetry id)
 *   S3 → cmrCompleteness / cmrCorrectness (integrated CMR pass workers)
 *   S5 → coderFix
 *   S7 → ship
 *   S9 → verify, S10 → fixer, S12 → landing
 *
 * Correctness C1: endgame steps must never coerce onto ship/coder. Phase
 * fallbacks apply only when the step is not an explicit wall role.
 */
export function familyRelaySlotsForWall(opts: {
  readonly phase:
    | "wave"
    | "correctness_checkpoint"
    | "final"
    | "online_review"
    | "merge";
  readonly wallStep: StepId;
  readonly cmrPass?: "completeness" | "correctness";
}): ReadonlyArray<ModelRouteSlot> {
  const step = opts.wallStep;
  if (step === "S1") return ["merger"];
  if (step === "S3") {
    if (opts.cmrPass === "correctness") return ["cmrCorrectness"];
    if (opts.cmrPass === "completeness") return ["cmrCompleteness"];
    // Correctness N2 / F2 residual: one pass 429 must not rewrite the other CMR
    // slot. Require the hit pass (or wall role); never default both.
    throw new Error(
      "familyRelaySlotsForWall: S3 wall requires cmrPass " +
        "(completeness|correctness); refusing to rewrite both CMR slots",
    );
  }
  if (step === "S5") return ["coderFix"];
  if (step === "S7") return ["ship"];
  if (step === "S9") {
    // Residual / legacy walls may still stamp S9 for IC checkpoint; do not
    // rewrite the verify slot when the phase is the correctness court.
    if (opts.phase === "correctness_checkpoint") {
      if (opts.cmrPass === "completeness") return ["cmrCompleteness"];
      return ["cmrCorrectness"];
    }
    return ["verify"];
  }
  if (step === "S10") return ["fixer"];
  if (step === "S12") return ["landing"];
  if (step === "S13") return ["collector"]; // #1145 Collector has its own route slot
  // Explicit wall roles above. Phase fallbacks never rewrite ship for
  // online-review / wave verify barriers (C1: online-review must not touch ship).
  if (opts.phase === "online_review") return ["verify"];
  if (opts.phase === "merge") return ["merger"];
  if (opts.phase === "wave") return ["verify"];
  // #961 incremental IC checkpoint — correctness court only.
  if (opts.phase === "correctness_checkpoint") return ["cmrCorrectness"];
  // final with ambiguous step — cover primary final consume slots
  return ["cmrCompleteness", "ship"];
}

/**
 * Mutate one non-coder slot and refresh smoke keys for the new slug
 * (reuse prior passed smoke for the same slug when present).
 */
function withSingleRouteSlot(
  route: ResolvedModelRoute,
  slot: ModelRouteSlot,
  slug: string,
): ResolvedModelRoute {
  const trimmed = slug.trim();
  assertKnownWorkerSlug(trimmed);
  if (slot === "coder") return withCoderSlot(route, trimmed);
  const slots: ModelSlotMap = { ...route.slots, [slot]: trimmed };
  const next: Pick<ResolvedModelRoute, "slots" | "legCollections"> = {
    slots,
    legCollections: route.legCollections,
  };
  const smoke: Record<string, RouteSmokeStatus> = { ...route.smoke };
  for (const entry of routeSmokeEntries(next)) {
    if (smoke[entry.key] !== undefined) continue;
    const prior = Object.entries(route.smoke).find(
      ([key, status]) =>
        key.endsWith(`:${entry.slug}`) && status.state === "passed",
    );
    smoke[entry.key] = prior?.[1] ?? { state: "unverified" };
  }
  return {
    ...route,
    slots,
    tightFamilyViolations: tightFamilyViolations(
      slots,
      route.legCollections,
      route.tightFamilies,
    ),
    smoke,
  };
}

/**
 * #686 / #909 — pure apply of a relay baton onto a resolved route (shared by
 * single-slice and family).
 *
 * - When `opts.slots` is provided (family barrier path), rewrite those exact
 *   ModelRouteSlots that `dispatchFamilyWorker` reads (cmr slots, ship, verify, ...).
 * - Otherwise use the single-slice StepId map: S3/S6 → verify (#923), S5 →
 *   coderFix, else coder (+coderFix via {@link withCoderSlot}).
 *
 * Does not carry sticky state — callers own that. Apply is load-bearing:
 * identity / coder-only apply on a family cmr/ship wall must fail consumed-slot nails.
 */
export function applyRelayBatonToRoute(
  route: ResolvedModelRoute,
  baton: Pick<NextRelayBaton, "slug">,
  wallStep: StepId = "S2",
  opts?: { readonly slots?: ReadonlyArray<ModelRouteSlot> },
): ResolvedModelRoute {
  const trimmed = baton.slug.trim();
  assertKnownWorkerSlug(trimmed);
  const targetSlots =
    opts?.slots !== undefined && opts.slots.length > 0
      ? opts.slots
      : [relaySlotForSingleSliceWallStep(wallStep)];

  let next = route;
  for (const slot of targetSlots) {
    next = withSingleRouteSlot(next, slot, trimmed);
  }
  return next;
}

/**
 * Production live-baton evidence: billing pools of smoke-`passed` route models.
 * Shared by single-slice + family so default runs can obtain a live pool table
 * without test-only `relayPools` injection. Unverified/failed smokes contribute
 * nothing — unknown state stays not-live.
 */
export function knownLiveBillingPoolsFromRoute(
  route: Pick<ResolvedModelRoute, "slots" | "legCollections" | "smoke">,
): ReadonlyArray<BillingPoolId> {
  const live = new Set<BillingPoolId>();
  for (const entry of routeSmokeEntries(route)) {
    const status = route.smoke[entry.key];
    if (status?.state !== "passed") continue;
    const pool = billingPoolForModelRef(entry.slug);
    if (pool !== undefined) live.add(pool);
  }
  return [...live];
}

export function routeSmokeFailure(
  route: Pick<ResolvedModelRoute, "slots" | "legCollections" | "smoke">,
  now = Date.now(),
  maxAgeMs = DEFAULT_ROUTE_SMOKE_MAX_AGE_MS,
  currentCliVersions: Readonly<Record<string, string | undefined>> = {},
): string | undefined {
  for (const entry of routeSmokeEntries(route)) {
    const status = route.smoke[entry.key];
    if (status === undefined || status.state === "unverified") {
      return `route smoke required for ${entry.key}; run the ${entry.slug} tool smoke before dispatch`;
    }
    if (status.state === "failed") {
      return `route smoke failed for ${entry.key}: ${status.error}`;
    }
    const at = Date.parse(status.at);
    if (!Number.isFinite(at) || now - at > maxAgeMs) {
      return `route smoke expired for ${entry.key}; last passed at ${status.at}`;
    }
    // Prefer entry.key (model×pipe / role); fall back to bare slug for older maps.
    const currentCliVersion =
      currentCliVersions[entry.key] ?? currentCliVersions[entry.slug];
    if (currentCliVersion !== undefined && currentCliVersion !== status.cliVersion) {
      return `route smoke expired for ${entry.key}; CLI version changed from ${status.cliVersion} to ${currentCliVersion}`;
    }
  }
  return undefined;
}

export async function smokeRouteModels(
  route: ResolvedModelRoute,
  executor: RouteSmokeExecutor,
  now = new Date(),
): Promise<ResolvedModelRoute> {
  const smoke: Record<string, RouteSmokeStatus> = { ...route.smoke };
  const entries = routeSmokeEntries(route);
  // #884: unique by model slug (owner "六路" = unique models). Status fans out
  // to every route entry sharing that slug. Pool-specific pings are forced by
  // RealBackend.smokeModelRoute after this when relaySmokeEntryKey is set.
  const uniqueEntries = [
    ...new Map(entries.map((entry) => [entry.slug, entry])).values(),
  ];
  const results = await Promise.all(
    uniqueEntries.map(async (entry) => {
      try {
        const result = await executor({ ...entry, command: "echo OK" });
        return {
          entry,
          status: {
            state: "passed",
            at: now.toISOString(),
            cliVersion: result.cliVersion,
          } satisfies RouteSmokeStatus,
        };
      } catch (error) {
        return {
          entry,
          status: {
            state: "failed",
            at: now.toISOString(),
            error: error instanceof Error ? error.message : String(error),
          } satisfies RouteSmokeStatus,
        };
      }
    }),
  );
  for (const { entry, status } of results) {
    for (const target of entries.filter((c) => c.slug === entry.slug)) {
      smoke[target.key] = status;
    }
  }
  return { ...route, smoke };
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
      route.legCollections[collection].map((leg) =>
        leg.optional === true ? [leg.family, leg.slug, true] : [leg.family, leg.slug],
      ),
    ]),
  });
}

export function tightRouteViolationDetails(route: ResolvedModelRoute): string {
  return route.tightFamilyViolations
    .map((v) => `${v.slot}=${v.slug}(${v.family})`)
    .join(", ");
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

/**
 * Production route resolve: `ORCHESTRATOR_ROUTE` + presets only.
 * No per-slot / CMR env overrides (#936 / #934 ID-002). Leftover slot/CMR env
 * names are ignored (deleted seams), not restaffed.
 */
export function resolveActiveModelRoute(
  env: ModelRouteEnv = process.env,
): ResolvedModelRoute {
  return resolveRouteModels(
    env.ORCHESTRATOR_ROUTE?.trim() || "normal",
    {},
    {},
    {},
    env,
  );
}

/**
 * Tight-family policy is always fail-closed (#936 / #934 ID-002).
 * Interactive continue seam deleted — violations always stop.
 */
export function applyTightRoutePolicy(
  route: ResolvedModelRoute,
): TightRoutePolicyDecision {
  if (route.tightFamilyViolations.length > 0) {
    const details = tightRouteViolationDetails(route);
    const message = `tight route violation for ${route.routeName}: ${details}`;
    return {
      kind: "stop",
      escalation: {
        reason: "tight route violation",
        diagnosis:
          `${message}. Orchestrator startup stops fail-closed; rerun with a ` +
          "route preset (`ORCHESTRATOR_ROUTE`) that preserves the tight-family " +
          "invariant, or change issue Coder-Rec staffing.",
      },
    };
  }
  return { kind: "continue", route };
}

/**
 * Apply design-time Coder-Rec selection onto a resolved route (#767 / #936).
 *
 * Only an explicit `Coder-Rec:` marking in the issue body overrides the active
 * route's coder slot — unmarked issues keep the route preset. A present but
 * broken / unregistered marking throws (fail-closed; #906). Env no longer owns
 * any slot (#934 ID-002).
 * #920: no review/CMR conflict filter — selection is pure roster position;
 * {@link withCoderSlot} only rewrites coder (+ coderFix).
 */
export function applyCoderRecToRoute(
  route: ResolvedModelRoute,
  issueBody: string | undefined,
): {
  readonly route: ResolvedModelRoute;
  readonly entry: CoderRosterEntry | undefined;
  /** True when no Coder-Rec line was present — route coder left untouched. */
  readonly skippedForMissingMarking: boolean;
} {
  // #906 S1: always admit/validate a present mark.
  if (issueBody !== undefined && issueBody.length > 0) {
    void resolveCoderRecOrder(issueBody);
  }

  const parsed =
    issueBody !== undefined && issueBody.length > 0
      ? parseCoderRec(issueBody)
      : undefined;
  if (parsed === undefined) {
    return {
      route,
      entry: undefined,
      skippedForMissingMarking: true,
    };
  }
  const order = resolveCoderRecOrder(issueBody);
  // #920 / ADR 0132: first roster seat only (sticky stay-put). No rounds arg.
  const entry = selectCoderRecEntry(order);
  if (
    route.slots.coder === entry.slug &&
    route.slots.coderFix === entry.slug
  ) {
    return {
      route,
      entry,
      skippedForMissingMarking: false,
    };
  }
  return {
    route: withCoderSlot(route, entry.slug),
    entry,
    skippedForMissingMarking: false,
  };
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
