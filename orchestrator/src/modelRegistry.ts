import "./sandcastleCancelSeam.js"; // #1010 choke-point: patch before sandcastle load
import * as sc from "@ai-hero/sandcastle";
import { agyAgent, type AgyAgentOptions } from "./agyAgent.js";
import { grokAgent, type GrokAgentOptions } from "./grokAgent.js";
import {
  loadModelData,
  type ModelDataRegistryRow,
} from "./modelDataConfig.js";
import type { BillingPoolId } from "./quotaPoolTable.js";
import {
  agySoulRulesMount,
  sandboxSoulPath,
  withSoulInstructions,
  type WorkerSoul,
} from "./soulInstructions.js";

/**
 * Pinned identity constants for seats / tests that name a default codex slug.
 * Registry *data rows* (provider/model/family/options) live in model-data
 * config (#1075 / ADR 0146 S3) — not in code.
 */
export const CODER_CODEX_SLUG = "gpt-5.6-terra";
export const REVIEWER_CODEX_SLUG = "gpt-5.6-sol";
export const VERIFY_CODEX_SLUG = "gpt-5.6-sol";

// Reasoning effort authority = registry row (and route-preset slug selection)
// only. Never force effort from role/soul/smokeKey at dispatch time — if a seat
// needs a different effort, give it a registry slug that declares that effort
// (e.g. gpt-5.6-sol-low / gpt-5.6-sol-high). Owner constitutional ruling
// 2026-07-16 (#916): deleted effortForLiveOfficer xhigh hard override.

export type ModelFamily = "claude" | "codex" | "agy" | "other";

export type ModelProviderFactory =
  | "claudeCode"
  | "codex"
  /** #905: real agy (Antigravity / Gemini) CLI via custom AgentProvider. */
  | "agy"
  /** #807: real SuperGrok CLI via custom AgentProvider (not sc.pi). */
  | "grok";

/** Typed host credential availability consumed before a provider is launched. */
export interface ProviderAuthAvailability {
  readonly claude: boolean;
  readonly grok: boolean;
  /** #905: agy OAuth token presence (container mount required for real agy). */
  readonly agy: boolean;
}

/**
 * Returns the provider-owned missing credential, if any.  This is deliberately
 * derived from the selected provider, never from worker prose or a model slug.
 */
export function unavailableProviderAuth(
  provider: ModelProviderFactory,
  availability: ProviderAuthAvailability,
): "claude" | "grok" | "agy" | undefined {
  if (provider === "claudeCode" && !availability.claude) return "claude";
  if (provider === "grok" && !availability.grok) return "grok";
  if (provider === "agy" && !availability.agy) return "agy";
  return undefined;
}

export const SUPPORTED_MODEL_PROVIDER_FACTORIES = [
  "claudeCode",
  "codex",
  "agy",
  "grok",
] as const satisfies ReadonlyArray<ModelProviderFactory>;

type ModelProviderOptions =
  | sc.ClaudeCodeOptions
  | sc.CodexOptions
  | AgyAgentOptions
  | GrokAgentOptions;

export type ModelSlugRegistryEntry =
  | { readonly provider: "claudeCode"; readonly model: string; readonly options?: sc.ClaudeCodeOptions }
  | { readonly provider: "codex"; readonly model: string; readonly options?: sc.CodexOptions }
  | { readonly provider: "agy"; readonly model: string; readonly options?: AgyAgentOptions }
  | { readonly provider: "grok"; readonly model: string; readonly options?: GrokAgentOptions };

type ModelSlugRegistryRow = ModelSlugRegistryEntry & {
  readonly family: ModelFamily;
  readonly strongLeg?: boolean;
};

type ProviderFactory = (model: string, options?: ModelProviderOptions) => sc.AgentProvider;

/**
 * Provider wiring stays in code (#1075). Data rows (which slug → which
 * provider/model/family/options) live in model-data config and are read at use.
 */
const MODEL_PROVIDER_FACTORIES: Readonly<Record<ModelProviderFactory, ProviderFactory>> = {
  claudeCode: (model, options) => sc.claudeCode(model, options as sc.ClaudeCodeOptions | undefined),
  // #957: restore Sandcastle-native codex capture + resume. #883 forced
  // captureSessions:false after capture threw "session not found"; that was a
  // symptom fix. Host-side CMR legs still use --ephemeral (parallel host
  // processes share ~/.codex — real collision risk, codex#11435). Inside a
  // container there is one codex process per worker, so Sandcastle's sc.codex
  // (no --ephemeral; default captureSessions:true) is correct: sessions land
  // on disk, capture succeeds, S3→S6 / SO same-session resume works.
  codex: (model, options) => sc.codex(model, options as sc.CodexOptions | undefined),
  // #905: real Antigravity/Gemini CLI — optional-leg degrade when dead; never
  // substitute opencode/grok under the agy name.
  agy: (model, options) => agyAgent(model, options as AgyAgentOptions | undefined),
  grok: (model, options) => grokAgent(model, options as GrokAgentOptions | undefined),
};

/**
 * Pinned ledger/replay compatibility only. Retired model names MUST NOT enter
 * model-data registry: that table is the executable live-worker allowlist.
 */
const HISTORICAL_CMR_LEG_FAMILIES: Readonly<Record<string, ModelFamily>> = {
  "gpt-5.5": "codex",
};

const CMR_REVIEW_LEG_REGISTRY: Readonly<Record<string, ModelFamily>> = {
  agy: "agy",
};

function unknownSlugError(slug: string): Error {
  return new Error(
    `realBackend: unknown model slug "${slug}". Add the CLI to the image and ` +
      `register it in model-data config (ORCHESTRATOR_MODEL_DATA_PATH / ` +
      `config/model-data.json) before using it.`,
  );
}

/**
 * Map an opaque config registry row onto the typed registry entry the
 * provider factories consume. Provider membership is fail-closed solely by
 * loadModelData/parseRegistryRow (MODEL_PROVIDERS whitelist) — do not re-check
 * here; ModelDataProvider and MODEL_PROVIDER_FACTORIES share the same keys.
 */
function rowFromConfigData(data: ModelDataRegistryRow): ModelSlugRegistryRow {
  const provider = data.provider;
  const family = data.family as ModelFamily;
  const optionsRaw = data.options;
  if (optionsRaw === undefined) {
    return {
      provider,
      model: data.model,
      family,
      ...(data.strongLeg === true ? { strongLeg: true } : {}),
    } as ModelSlugRegistryRow;
  }
  // Shallow-copy opaque options into the provider-typed options bag. Loader
  // already ensured a plain object; provider CLI owns further validation.
  const options = { ...optionsRaw };
  switch (provider) {
    case "claudeCode":
      return {
        provider,
        model: data.model,
        options: options as sc.ClaudeCodeOptions,
        family,
        ...(data.strongLeg === true ? { strongLeg: true } : {}),
      };
    case "codex":
      return {
        provider,
        model: data.model,
        options: options as sc.CodexOptions,
        family,
        ...(data.strongLeg === true ? { strongLeg: true } : {}),
      };
    case "agy":
      return {
        provider,
        model: data.model,
        options: options as AgyAgentOptions,
        family,
        ...(data.strongLeg === true ? { strongLeg: true } : {}),
      };
    case "grok":
      return {
        provider,
        model: data.model,
        options: options as GrokAgentOptions,
        family,
        ...(data.strongLeg === true ? { strongLeg: true } : {}),
      };
  }
}

/** Peek live model-data registry (re-reads file every call — 用时现读). */
function liveRegistryRow(slug: string): ModelSlugRegistryRow | undefined {
  const data = loadModelData().registry[slug];
  if (data === undefined) return undefined;
  return rowFromConfigData(data);
}

function rowForSlug(slug: string): ModelSlugRegistryRow {
  const entry = liveRegistryRow(slug);
  if (!entry) {
    throw unknownSlugError(slug);
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
    case "agy":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "grok":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
  }
}

/**
 * Non-throwing registry peek: provider for a known slug, else undefined.
 * Used by billing-pool inference for effort-variant / non-roster registry rows
 * that still identify a billing boundary via provider (codex → codex-5h, …).
 */
export function providerForModelSlug(
  slug: string,
): ModelProviderFactory | undefined {
  if (typeof slug !== "string" || slug.length === 0) return undefined;
  return liveRegistryRow(slug)?.provider;
}

/** #686 / ADR 0124 — billing pool → executable provider channel. */
export type BillingPoolDispatchId = BillingPoolId;

/**
 * Billing pool → executable provider rewrite. **Partial on purpose (#905 r2):**
 * empty/retired pools (e.g. `zai` after opencode eviction) MUST omit a binding
 * so {@link resolveModelSlugForPool} cannot silently rewrite onto another CLI.
 */
export const POOL_DISPATCH_BINDINGS: Readonly<
  Partial<Record<BillingPoolDispatchId, ModelProviderFactory>>
> = {
  // #807: SuperGrok pool runs the real `grok` CLI (custom AgentProvider), not
  // sandcastle's `sc.pi()` (different product / flag contract / auth home).
  "grok-build": "grok",
  // cursor/zai intentionally absent — no live registry slug; no rewrite.
  "codex-5h": "codex",
  claude: "claudeCode",
};

export function isBillingPoolDispatchId(
  value: string | undefined,
): value is BillingPoolDispatchId {
  return (
    value === "grok-build" ||
    value === "cursor" ||
    value === "zai" ||
    value === "codex-5h" ||
    value === "claude"
  );
}

/** Resolve a pool-specific provider without changing the roster model id. */
export function resolveModelSlugForPool(
  slug: string,
  pool?: BillingPoolDispatchId,
): ModelSlugRegistryEntry {
  const base = resolveModelSlug(slug);
  // #905: grok-4.5 always stays on the SuperGrok CLI — never cursor/opencode transit.
  if (slug === "grok-4.5") {
    return { provider: "grok", model: base.model } as ModelSlugRegistryEntry;
  }
  // Absent binding (retired/empty pool) → fail-closed: keep registry provider.
  const binding = pool === undefined ? undefined : POOL_DISPATCH_BINDINGS[pool];
  if (binding === undefined || binding === base.provider) return base;
  return { provider: binding, model: base.model } as ModelSlugRegistryEntry;
}

export function modelFamilyForSlug(slug: string): ModelFamily {
  const entry = liveRegistryRow(slug);
  if (entry !== undefined) {
    return entry.family;
  }
  throw unknownSlugError(slug);
}

export function modelFamilyForCmrReviewLeg(slug: string): ModelFamily {
  const entry = liveRegistryRow(slug);
  if (entry !== undefined) {
    return entry.family;
  }
  const cmrLeg = CMR_REVIEW_LEG_REGISTRY[slug] ?? HISTORICAL_CMR_LEG_FAMILIES[slug];
  if (cmrLeg !== undefined) {
    return cmrLeg;
  }
  throw new Error(
    `unknown cmr review leg slug "${slug}". Add a runnable worker model to ` +
      `model-data config, or explicitly register a non-worker CMR leg before ` +
      `selecting it in a route preset.`,
  );
}

export function modelIsStrongLeg(slug: string): boolean {
  return liveRegistryRow(slug)?.strongLeg === true;
}

export function modelIdForSlug(slug: string): string {
  return resolveModelSlug(slug).model;
}

/**
 * Sandcastle `Output.object` with maxRetries > 0 requires an agent provider
 * that supports session resumption (claudeCode / codex / pi). Capability
 * knowledge lives with the registry row's provider — owner B ruling
 * 2026-07-16 (#934 W1 first flight): incapable providers attach maxRetries 0.
 */
const RESUME_CAPABLE_PROVIDERS: ReadonlySet<string> = new Set([
  "claudeCode",
  "codex",
  // #955: grokAgent implements the sandcastle sessionStorage contract.
  "grok",
]);

export function resumeCapableForSlug(
  slug: string,
  pool?: BillingPoolDispatchId,
): boolean {
  return RESUME_CAPABLE_PROVIDERS.has(resolveModelSlugForPool(slug, pool).provider);
}

export function agentForSlug(
  slug: string,
  pool?: BillingPoolDispatchId,
  soul?: WorkerSoul,
): sc.AgentProvider {
  // Effort comes from the registry row for `slug` only — no call-site overlay
  // (#916 F9: deleted residual codexEffort parameter).
  const entry = resolveModelSlugForPool(slug, pool);
  const agent =
    entry.provider === "grok" && soul !== undefined
      ? grokAgent(entry.model, {
          ...(entry.options as GrokAgentOptions | undefined),
          rulesFile: sandboxSoulPath(soul),
        })
      : MODEL_PROVIDER_FACTORIES[entry.provider](entry.model, entry.options);
  return soul === undefined
    ? agent
    : withSoulInstructions(agent, entry.provider, soul);
}

export function appendAgySoulMount(
  mounts: Array<{
    hostPath: string;
    sandboxPath: string;
    readonly?: boolean;
  }>,
  spec: { readonly model: string; readonly soul: WorkerSoul },
  pool: BillingPoolDispatchId | undefined,
  soulsDir: string,
): void {
  if (resolveModelSlugForPool(spec.model, pool).provider === "agy") {
    mounts.push(agySoulRulesMount(soulsDir, spec.soul));
  }
}
