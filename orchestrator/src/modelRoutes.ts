import { createInterface } from "node:readline/promises";

import {
  parseCoderRec,
  reviewerOverrideForCoderSlug,
  resolveCoderRecOrder,
  selectCoderRecEntry,
  type CoderRosterEntry,
} from "./coderRoster.js";
import {
  modelFamilyForCmrReviewLeg,
  CODER_CODEX_SLUG,
  REVIEWER_CODEX_SLUG,
  VERIFY_CODEX_SLUG,
  modelFamilyForSlug,
  resolveModelSlug,
  type ModelFamily,
} from "./modelRegistry.js";

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
  /** Best-effort preset leg. Env-declared legs intentionally omit this marker. */
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

const NORMAL_SLOTS: ModelSlotMap = {
  coder: CODER_CODEX_SLUG,
  reviewer: REVIEWER_CODEX_SLUG,
  coderFix: CODER_CODEX_SLUG,
  ship: "sonnet",
  merger: "sonnet",
  cmrCompleteness: VERIFY_CODEX_SLUG,
  cmrCorrectness: VERIFY_CODEX_SLUG,
  verify: VERIFY_CODEX_SLUG,
  fixer: "sonnet",
  cleanup: "sonnet",
  docRelease: "sonnet",
};

const NORMAL_LEG_COLLECTIONS: ModelRouteLegCollectionMap = {
  cmrReview: [
    { family: "codex", slug: REVIEWER_CODEX_SLUG },
    { family: "claude", slug: "opus" },
    { family: "agy", slug: "agy", optional: true },
  ],
};

const ROUTE_PRESETS: Readonly<Record<string, ModelRoutePreset>> = {
  normal: { slots: NORMAL_SLOTS, legCollections: NORMAL_LEG_COLLECTIONS },
  "codex-cheap": {
    slots: {
      coder: CODER_CODEX_SLUG,
      reviewer: REVIEWER_CODEX_SLUG,
      coderFix: CODER_CODEX_SLUG,
      ship: "sonnet",
      merger: "sonnet",
      cmrCompleteness: VERIFY_CODEX_SLUG,
      cmrCorrectness: VERIFY_CODEX_SLUG,
      verify: VERIFY_CODEX_SLUG,
      fixer: "sonnet",
      cleanup: "sonnet",
      docRelease: "sonnet",
    },
    legCollections: {
      cmrReview: [
        { family: "claude", slug: "opus" },
        { family: "agy", slug: "agy", optional: true },
        { family: "codex", slug: REVIEWER_CODEX_SLUG },
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
        { family: "agy", slug: "agy", optional: true },
      ],
    },
  },
  "claude-cheap": {
    slots: {
      coder: CODER_CODEX_SLUG,
      reviewer: REVIEWER_CODEX_SLUG,
      coderFix: CODER_CODEX_SLUG,
      ship: CODER_CODEX_SLUG,
      merger: CODER_CODEX_SLUG,
      cmrCompleteness: VERIFY_CODEX_SLUG,
      cmrCorrectness: VERIFY_CODEX_SLUG,
      verify: VERIFY_CODEX_SLUG,
      fixer: CODER_CODEX_SLUG,
      cleanup: CODER_CODEX_SLUG,
      docRelease: CODER_CODEX_SLUG,
    },
    legCollections: {
      cmrReview: [
        { family: "codex", slug: REVIEWER_CODEX_SLUG },
        { family: "agy", slug: "agy", optional: true },
        { family: "claude", slug: "opus" },
      ],
    },
  },
  "claude-tight": {
    tightFamilies: ["claude"],
    slots: {
      coder: CODER_CODEX_SLUG,
      reviewer: REVIEWER_CODEX_SLUG,
      coderFix: CODER_CODEX_SLUG,
      ship: CODER_CODEX_SLUG,
      merger: CODER_CODEX_SLUG,
      cmrCompleteness: VERIFY_CODEX_SLUG,
      cmrCorrectness: VERIFY_CODEX_SLUG,
      verify: VERIFY_CODEX_SLUG,
      fixer: CODER_CODEX_SLUG,
      cleanup: CODER_CODEX_SLUG,
      docRelease: CODER_CODEX_SLUG,
    },
    legCollections: {
      cmrReview: [
        { family: "codex", slug: REVIEWER_CODEX_SLUG },
        { family: "agy", slug: "agy", optional: true },
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
  // Route declarations are executable live configuration. Historical CMR
  // labels remain parseable through modelFamilyForCmrReviewLeg, but can never
  // be selected as a current review worker.
  try {
    return { slug: trimmed, family: modelFamilyForSlug(trimmed) };
  } catch {
    throw new Error(
      `unknown cmr review leg slug "${trimmed}". Register a live worker in ` +
        "MODEL_SLUG_REGISTRY before selecting it in a route.",
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

  return {
    routeName: trimmedRoute,
    slots,
    legCollections,
    tightFamilyViolations: tightFamilyViolations(
      slots,
      legCollections,
      preset.tightFamilies ?? [],
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
 * Override the coder slot (and coderFix unless explicitly env-overridden) for
 * design-time Coder-Rec (#767). Sol's owner-ratified route also moves the
 * per-slice reviewer to Opus, so the selected coder never self-reviews.
 * Preserves prior smoke status for the new slug when the same slug was already
 * smoked under another key; otherwise marks the new keys unverified so the
 * runner's route-smoke gate can (re)verify before dispatch.
 */
export function withCoderSlot(
  route: ResolvedModelRoute,
  coderSlug: string,
  opts: { readonly preserveCoderFix?: boolean } = {},
): ResolvedModelRoute {
  const trimmed = coderSlug.trim();
  assertKnownWorkerSlug(trimmed);
  const reviewerOverride = reviewerOverrideForCoderSlug(trimmed);
  const slots: ModelSlotMap = {
    ...route.slots,
    coder: trimmed,
    ...(opts.preserveCoderFix ? {} : { coderFix: trimmed }),
    ...(reviewerOverride !== undefined ? { reviewer: reviewerOverride } : {}),
  };
  // Sol is an owner-approved coder only when Opus remains the primary reviewer
  // throughout the review loop. Remove Sol's default CMR review leg as well as
  // replacing the per-slice reviewer, otherwise the final route fails the
  // #767 pool-separation gate against its own CMR checkpoint.
  const legCollections: ModelRouteLegCollectionMap = {
    ...route.legCollections,
    ...(reviewerOverride !== undefined
      ? {
          cmrReview: route.legCollections.cmrReview.filter(
            (leg) => leg.slug !== trimmed,
          ),
        }
      : {}),
  };
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
      ROUTE_PRESETS[route.routeName]?.tightFamilies ?? [],
    ),
    smoke,
  };
}

/**
 * All self-review peers in a complete landed route except one slot owned by
 * the relay candidate. Exclusion is by slot identity: a matching slug in any
 * other slot or CMR review leg remains a conflict.
 */
export function routeConflictSlugsExcluding(
  route: Pick<ResolvedModelRoute, "slots" | "legCollections">,
  excludedSlot: ModelRouteSlot,
): ReadonlyArray<string> {
  return [
    ...(excludedSlot === "coder" ? [] : [route.slots.coder]),
    ...(excludedSlot === "reviewer" ? [] : [route.slots.reviewer]),
    ...(excludedSlot === "cmrCompleteness" ? [] : [route.slots.cmrCompleteness]),
    ...(excludedSlot === "cmrCorrectness" ? [] : [route.slots.cmrCorrectness]),
    ...(excludedSlot === "verify" ? [] : [route.slots.verify]),
    ...route.legCollections.cmrReview.map((leg) => leg.slug),
  ];
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
            "repair_hint: rewrite the route env as CSV, for example gpt-5.6-sol,agy",
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

/**
 * Apply design-time Coder-Rec selection onto a resolved route (#767).
 *
 * Ops env `ORCHESTRATOR_CODER_MODEL` still wins (explicit override). An explicit
 * `ORCHESTRATOR_CODER_FIX_MODEL` remains authoritative for just coderFix.
 * Otherwise,
 * only an explicit `Coder-Rec:` marking in the issue body overrides the active
 * route's coder slot — unmarked issues keep the route preset. A present but
 * all-invalid marking falls through to {@link DEFAULT_CODER_REC_ORDER}.
 * Entries are checked against every complete-route peer other than the coder
 * slot they replace. Sol's resulting per-slice reviewer pairing is still
 * modeled by {@link withCoderSlot}; it does not exempt any CMR checkpoint.
 */
export function applyCoderRecToRoute(
  route: ResolvedModelRoute,
  issueBody: string | undefined,
  nonConvergingRounds: number,
  env: ModelRouteEnv = process.env,
): {
  readonly route: ResolvedModelRoute;
  readonly entry: CoderRosterEntry | undefined;
  readonly skippedForEnvOverride: boolean;
  /** True when no Coder-Rec line was present — route coder left untouched. */
  readonly skippedForMissingMarking: boolean;
} {
  const coderEnvOverride = env.ORCHESTRATOR_CODER_MODEL?.trim();
  if (coderEnvOverride !== undefined && coderEnvOverride !== "") {
    return {
      route,
      entry: undefined,
      skippedForEnvOverride: true,
      skippedForMissingMarking: false,
    };
  }
  const preserveCoderFix =
    env.ORCHESTRATOR_CODER_FIX_MODEL?.trim() !== undefined &&
    env.ORCHESTRATOR_CODER_FIX_MODEL?.trim() !== "";
  const parsed =
    issueBody !== undefined && issueBody.length > 0
      ? parseCoderRec(issueBody)
      : undefined;
  if (parsed === undefined) {
    return {
      route,
      entry: undefined,
      skippedForEnvOverride: false,
      skippedForMissingMarking: true,
    };
  }
  const order = resolveCoderRecOrder(issueBody);
  const entry = selectCoderRecEntry(order, nonConvergingRounds, {
    reviewerSlugsForCandidate: (candidate) => {
      const candidateRoute = withCoderSlot(route, candidate.slug, {
        preserveCoderFix,
      });
      return routeConflictSlugsExcluding(candidateRoute, "coder");
    },
  });
  if (
    route.slots.coder === entry.slug &&
    (preserveCoderFix || route.slots.coderFix === entry.slug)
  ) {
    return {
      route,
      entry,
      skippedForEnvOverride: false,
      skippedForMissingMarking: false,
    };
  }
  return {
    route: withCoderSlot(route, entry.slug, { preserveCoderFix }),
    entry,
    skippedForEnvOverride: false,
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
