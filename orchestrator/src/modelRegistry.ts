import * as sc from "@ai-hero/sandcastle";
import { agyAgent, type AgyAgentOptions } from "./agyAgent.js";
import { grokAgent, type GrokAgentOptions } from "./grokAgent.js";
import type { BillingPoolId } from "./quotaPoolTable.js";

/**
 * The codex coder slug + its effort. The model id is the bare CLI model string
 * the sandcastle codex provider expects.
 */
export const CODER_CODEX_SLUG = "gpt-5.6-terra";
const CODER_CODEX_EFFORT: NonNullable<sc.CodexOptions["effort"]> = "low";
export const REVIEWER_CODEX_SLUG = "gpt-5.6-sol";
export const VERIFY_CODEX_SLUG = "gpt-5.6-sol";
const CLAUDE_HEADLESS_OPTIONS = {
  permissionMode: "bypassPermissions",
} as const satisfies sc.ClaudeCodeOptions;

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
  | "copilot"
  | "cursor"
  | "pi"
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
  "copilot",
  "cursor",
  "pi",
  "grok",
] as const satisfies ReadonlyArray<ModelProviderFactory>;

type ModelProviderOptions =
  | sc.ClaudeCodeOptions
  | sc.CodexOptions
  | sc.CopilotOptions
  | sc.CursorOptions
  | sc.PiOptions
  | AgyAgentOptions
  | GrokAgentOptions;

export type ModelSlugRegistryEntry =
  | { readonly provider: "claudeCode"; readonly model: string; readonly options?: sc.ClaudeCodeOptions }
  | { readonly provider: "codex"; readonly model: string; readonly options?: sc.CodexOptions }
  | { readonly provider: "agy"; readonly model: string; readonly options?: AgyAgentOptions }
  | { readonly provider: "copilot"; readonly model: string; readonly options?: sc.CopilotOptions }
  | { readonly provider: "cursor"; readonly model: string; readonly options?: sc.CursorOptions }
  | { readonly provider: "pi"; readonly model: string; readonly options?: sc.PiOptions }
  | { readonly provider: "grok"; readonly model: string; readonly options?: GrokAgentOptions };

type ModelSlugRegistryRow = ModelSlugRegistryEntry & {
  readonly family: ModelFamily;
  readonly strongLeg?: boolean;
};

type ProviderFactory = (model: string, options?: ModelProviderOptions) => sc.AgentProvider;

const MODEL_PROVIDER_FACTORIES: Readonly<Record<ModelProviderFactory, ProviderFactory>> = {
  claudeCode: (model, options) => sc.claudeCode(model, options as sc.ClaudeCodeOptions | undefined),
  // #883 owner order (2026-07-12 「删了它」): session capture is structurally
  // dead for codex legs — the cmr rules mandate --ephemeral (no session file is
  // ever written), so the post-run capture ritual can only throw, which killed
  // two completed #883 coder iterations (completion unrecognized → idle-hang
  // SIGKILL). Disable capture at the single codex factory seam; Claude legs
  // keep capture (theirs works and feeds resume/usage parsing).
  codex: (model, options) =>
    sc.codex(model, { ...(options as sc.CodexOptions | undefined), captureSessions: false }),
  // #905: real Antigravity/Gemini CLI — optional-leg degrade when dead; never
  // substitute opencode/grok under the agy name.
  agy: (model, options) => agyAgent(model, options as AgyAgentOptions | undefined),
  copilot: (model, options) => sc.copilot(model, options as sc.CopilotOptions | undefined),
  cursor: (model, options) => sc.cursor(model, options as sc.CursorOptions | undefined),
  // Kept for sandcastle-native `pi` CLI (distinct product). grok-build pool does
  // NOT use this — see POOL_DISPATCH_BINDINGS + grokAgent (#807 owner ruling).
  pi: (model, options) => sc.pi(model, options as sc.PiOptions | undefined),
  grok: (model, options) => grokAgent(model, options as GrokAgentOptions | undefined),
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
  "gpt-5.6-luna": {
    provider: "codex",
    model: "gpt-5.6-luna",
    options: { effort: "medium" },
    family: "codex",
  },
  // #861 owner order (2026-07-12): a high-effort sol row so the family CMR
  // coder-fix slot can run sol@high via ORCHESTRATOR_CODER_FIX_MODEL without
  // touching the medium default the reviewer/verify slots pin.
  "gpt-5.6-sol-high": {
    provider: "codex",
    model: "gpt-5.6-sol",
    options: { effort: "high" },
    family: "codex",
    strongLeg: true,
  },
  // #916: low-effort sol row for ship/merger/fixer/cleanup/docRelease seats on
  // claude-tight (same model string as sol, options.effort:"low").
  "gpt-5.6-sol-low": {
    provider: "codex",
    model: "gpt-5.6-sol",
    options: { effort: "low" },
    family: "codex",
    strongLeg: true,
  },
  // #905: grok-4.5 always runs the real SuperGrok CLI (provider `grok`).
  // Never cursor / opencode transit — pool rewrite cannot re-route it.
  "grok-4.5": {
    provider: "grok",
    model: "grok-4.5",
    family: "other",
    strongLeg: true,
  },
  sonnet: {
    provider: "claudeCode",
    // #789: roster coder id `sonnet-5` → slug `sonnet` must resolve to Sonnet 5
    // (claude-sonnet-5), matching docs/CODER_ROSTER.md — not the prior 4.6 pin.
    model: "claude-sonnet-5",
    options: CLAUDE_HEADLESS_OPTIONS,
    family: "claude",
  },
  // #789 Coder-Rec roster: Claude-pool small-fix backup (same claudeCode pipe).
  haiku: {
    provider: "claudeCode",
    model: "claude-haiku-4-5",
    options: CLAUDE_HEADLESS_OPTIONS,
    family: "claude",
  },
  opus: {
    provider: "claudeCode",
    model: "claude-opus-4-8",
    options: CLAUDE_HEADLESS_OPTIONS,
    family: "claude",
    strongLeg: true,
  },
  // #905: real agy CLI. Empty model → agy default (Gemini 3.5 Flash). When the
  // Gemini consumer leg is dead, optional-leg degrade only — never substitute.
  agy: {
    provider: "agy",
    model: "",
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
    case "agy":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "copilot":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "cursor":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "pi":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
    case "grok":
      return { provider: entry.provider, model: entry.model, options: { ...entry.options } };
  }
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
  cursor: "cursor",
  // zai intentionally absent — no live registry slug after #905; no rewrite.
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
      : entry.options;
  return MODEL_PROVIDER_FACTORIES[entry.provider](entry.model, options);
}
