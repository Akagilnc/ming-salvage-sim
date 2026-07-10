import * as sc from "@ai-hero/sandcastle";

/**
 * The codex coder slug + its effort. The model id is the bare CLI model string
 * the sandcastle codex provider expects.
 */
export const CODER_CODEX_SLUG = "gpt-5.6-terra";
const CODER_CODEX_EFFORT: NonNullable<sc.CodexOptions["effort"]> = "low";
export const REVIEWER_CODEX_SLUG = "gpt-5.6-sol";
export const VERIFY_CODEX_SLUG = "gpt-5.6-terra";

/**
 * Live-officer reasoning effort for verify / CMR workers on the verify Codex
 * slug. Shared by single-slice (`realBackend`) and family (`realFamilyBackend`)
 * so the two paths cannot drift.
 *
 * Returns `"xhigh"` when the slug is {@link VERIFY_CODEX_SLUG} and the context
 * is a verify role, a CMR soul, or a route-smoke key prefixed `verify`/`cmr`.
 */
export function effortForLiveOfficer(
  slug: string,
  context: { readonly role?: string; readonly soul?: string; readonly smokeKey?: string },
): "xhigh" | undefined {
  if (
    slug === VERIFY_CODEX_SLUG &&
    (context.role === "verify" || context.soul === "cmr" || /^(verify|cmr)/.test(context.smokeKey ?? ""))
  ) {
    return "xhigh";
  }
  return undefined;
}

export type ModelFamily = "claude" | "codex" | "agy" | "opencode" | "other";

export type ModelProviderFactory =
  | "claudeCode"
  | "codex"
  | "opencode"
  | "copilot"
  | "cursor"
  | "pi";

export const SUPPORTED_MODEL_PROVIDER_FACTORIES = [
  "claudeCode",
  "codex",
  "opencode",
  "copilot",
  "cursor",
  "pi",
] as const satisfies ReadonlyArray<ModelProviderFactory>;

type ModelProviderOptions =
  | sc.ClaudeCodeOptions
  | sc.CodexOptions
  | sc.OpenCodeOptions
  | sc.CopilotOptions
  | sc.CursorOptions
  | sc.PiOptions;

export type ModelSlugRegistryEntry =
  | { readonly provider: "claudeCode"; readonly model: string; readonly options?: sc.ClaudeCodeOptions }
  | { readonly provider: "codex"; readonly model: string; readonly options?: sc.CodexOptions }
  | { readonly provider: "opencode"; readonly model: string; readonly options?: sc.OpenCodeOptions }
  | { readonly provider: "copilot"; readonly model: string; readonly options?: sc.CopilotOptions }
  | { readonly provider: "cursor"; readonly model: string; readonly options?: sc.CursorOptions }
  | { readonly provider: "pi"; readonly model: string; readonly options?: sc.PiOptions };

type ModelSlugRegistryRow = ModelSlugRegistryEntry & {
  readonly family: ModelFamily;
  readonly strongLeg?: boolean;
};

type ProviderFactory = (model: string, options?: ModelProviderOptions) => sc.AgentProvider;

const MODEL_PROVIDER_FACTORIES: Readonly<Record<ModelProviderFactory, ProviderFactory>> = {
  claudeCode: (model, options) => sc.claudeCode(model, options as sc.ClaudeCodeOptions | undefined),
  codex: (model, options) => sc.codex(model, options as sc.CodexOptions | undefined),
  opencode: (model, options) => sc.opencode(model, options as sc.OpenCodeOptions | undefined),
  copilot: (model, options) => sc.copilot(model, options as sc.CopilotOptions | undefined),
  cursor: (model, options) => sc.cursor(model, options as sc.CursorOptions | undefined),
  pi: (model, options) => sc.pi(model, options as sc.PiOptions | undefined),
};

const MODEL_SLUG_REGISTRY: Readonly<Record<string, ModelSlugRegistryRow>> = {
  [CODER_CODEX_SLUG]: {
    provider: "codex",
    model: CODER_CODEX_SLUG,
    options: { effort: CODER_CODEX_EFFORT },
    family: "codex",
    strongLeg: true,
  },
  [REVIEWER_CODEX_SLUG]: {
    provider: "codex",
    model: REVIEWER_CODEX_SLUG,
    options: { effort: "medium" },
    family: "codex",
    strongLeg: true,
  },
  // #767 Coder-Rec roster: Luna (codex pool, medium effort).
  "gpt-5.6-luna": {
    provider: "codex",
    model: "gpt-5.6-luna",
    options: { effort: "medium" },
    family: "codex",
  },
  // #767 Coder-Rec roster: SuperGrok pool primary coder.
  "grok-4.5": {
    provider: "cursor",
    model: "grok-4.5",
    family: "other",
    strongLeg: true,
  },
  sonnet: {
    provider: "claudeCode",
    model: "claude-sonnet-4-6",
    family: "claude",
  },
  opus: {
    provider: "claudeCode",
    model: "claude-opus-4-8",
    family: "claude",
    strongLeg: true,
  },
  "opencode-grok": {
    provider: "opencode",
    model: "grok-4.3",
    family: "opencode",
    strongLeg: true,
  },
  // `agy` is retained as the route-facing family/slug for compatibility, but
  // it is now backed by the real OpenCode executor instead of a non-runnable
  // CMR-only label.
  agy: {
    provider: "opencode",
    model: "grok-4.3",
    family: "agy",
  },
};

/**
 * Pinned ledger/replay compatibility only. Retired model names MUST NOT enter
 * MODEL_SLUG_REGISTRY: that registry is the executable live-worker allowlist.
 */
const HISTORICAL_CMR_LEG_FAMILIES: Readonly<Record<string, ModelFamily>> = {
  "gpt-5.5": "codex",
};

const CMR_REVIEW_LEG_REGISTRY: Readonly<Record<string, ModelFamily>> = {
  agy: "agy",
};

function rowForSlug(slug: string): ModelSlugRegistryRow {
  const entry = MODEL_SLUG_REGISTRY[slug];
  if (!entry) {
    throw new Error(
      `realBackend: unknown model slug "${slug}". Add the CLI to the image and ` +
        `register it in MODEL_SLUG_REGISTRY before using it.`,
    );
  }
  return entry;
}

export function resolveModelSlug(slug: string): ModelSlugRegistryEntry {
  const entry = rowForSlug(slug);
  if (entry.options === undefined) {
    return { provider: entry.provider, model: entry.model } as ModelSlugRegistryEntry;
  }
  switch (entry.provider) {
    case "claudeCode":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "codex":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "opencode":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "copilot":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "cursor":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "pi":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
  }
}

/**
 * #686 / ADR 0124 — billing pool → execution-channel binding.
 * Same model id can live on multiple pools; the pool selects the real spawn
 * provider/CLI (换马甲 must change the channel, not a bookkeeping string).
 */
export type BillingPoolDispatchId =
  | "grok-build"
  | "cursor"
  | "zai"
  | "codex-5h";

export const POOL_DISPATCH_BINDINGS: Readonly<
  Record<BillingPoolDispatchId, ModelProviderFactory>
> = {
  "grok-build": "pi",
  cursor: "cursor",
  zai: "opencode",
  "codex-5h": "codex",
};

export function isBillingPoolDispatchId(
  value: string | undefined,
): value is BillingPoolDispatchId {
  return (
    value === "grok-build" ||
    value === "cursor" ||
    value === "zai" ||
    value === "codex-5h"
  );
}

/**
 * Resolve the executable provider for a slug under a billing pool.
 * When `pool` is set, the pool binding overrides the registry's default
 * provider while keeping the model id (ADR 0124 same-model 换马甲).
 */
export function resolveModelSlugForPool(
  slug: string,
  pool?: BillingPoolDispatchId,
): ModelSlugRegistryEntry {
  const base = resolveModelSlug(slug);
  if (pool === undefined) return base;
  const provider = POOL_DISPATCH_BINDINGS[pool];
  if (provider === base.provider) return base;
  // Pool channel override — drop provider-specific options that do not apply
  // to the new factory (e.g. codex effort on a cursor/pi spawn).
  return { provider, model: base.model } as ModelSlugRegistryEntry;
}

export function modelFamilyForSlug(slug: string): ModelFamily {
  const entry = MODEL_SLUG_REGISTRY[slug];
  if (entry !== undefined) {
    return entry.family;
  }
  throw new Error(
    `realBackend: unknown model slug "${slug}". Add the CLI to the image and ` +
      `register it in MODEL_SLUG_REGISTRY before using it.`,
  );
}

export function modelFamilyForCmrReviewLeg(slug: string): ModelFamily {
  const entry = MODEL_SLUG_REGISTRY[slug];
  if (entry !== undefined) {
    return entry.family;
  }
  const cmrLeg = CMR_REVIEW_LEG_REGISTRY[slug] ?? HISTORICAL_CMR_LEG_FAMILIES[slug];
  if (cmrLeg !== undefined) {
    return cmrLeg;
  }
  throw new Error(
    `unknown cmr review leg slug "${slug}". Add a runnable worker model to ` +
      `MODEL_SLUG_REGISTRY, or explicitly register a non-worker CMR leg before ` +
      `using it in ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS.`,
  );
}

export function modelIsStrongLeg(slug: string): boolean {
  return MODEL_SLUG_REGISTRY[slug]?.strongLeg === true;
}

export function modelIdForSlug(slug: string): string {
  return resolveModelSlug(slug).model;
}

export function agentForSlug(
  slug: string,
  codexEffort?: NonNullable<sc.CodexOptions["effort"]>,
  pool?: BillingPoolDispatchId,
): sc.AgentProvider {
  const entry = resolveModelSlugForPool(slug, pool);
  const options =
    entry.provider === "codex" && codexEffort !== undefined
      ? { ...(entry.options ?? {}), effort: codexEffort }
      : entry.provider === "codex"
        ? entry.options
        : entry.options;
  return MODEL_PROVIDER_FACTORIES[entry.provider](entry.model, options);
}
