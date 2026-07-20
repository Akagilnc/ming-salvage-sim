/**
 * #1073 / ADR 0146 S1 — model-data config base.
 *
 * External JSON (env path injection, same pattern as route-presets) holding
 * roster + registry *data rows*. Provider wiring stays in code (S3). Callers
 * that want live values call {@link loadModelData} — every call re-reads the
 * file (用时现读; no process-lifetime cache). Bad shape / missing file fail
 * closed with path + reason; never silent fallback to a prior parse.
 *
 * S2 (#1074) switched coderRoster consumers onto this loader (constants
 * deleted). S3 (#1075) switched modelRegistry consumers onto this loader
 * (registry data rows deleted from code; provider factories stay in
 * modelRegistry). Pool table stays in code (ADR 0146).
 */

import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import { fileURLToPath } from "node:url";

/** Env override for the model-data config path (#1073 / ADR 0146). */
export const MODEL_DATA_PATH_ENV = "ORCHESTRATOR_MODEL_DATA_PATH";

const DEFAULT_MODEL_DATA_PATH = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "config",
  "model-data.json",
);

const CODER_POOLS: ReadonlySet<string> = new Set([
  "supergrok",
  "codex",
  "claude",
]);
const MODEL_FAMILIES: ReadonlySet<string> = new Set([
  "claude",
  "codex",
  "agy",
  "other",
]);
const MODEL_PROVIDERS: ReadonlySet<string> = new Set([
  "claudeCode",
  "codex",
  "agy",
  "copilot",
  "cursor",
  "pi",
  "grok",
]);

export type ModelDataEnv = Readonly<Record<string, string | undefined>>;

export type ModelDataPoolId = "supergrok" | "codex" | "claude";
export type ModelDataFamily = "claude" | "codex" | "agy" | "other";
export type ModelDataProvider =
  | "claudeCode"
  | "codex"
  | "agy"
  | "copilot"
  | "cursor"
  | "pi"
  | "grok";

export interface ModelDataRosterEntry {
  readonly id: string;
  readonly slug: string;
  readonly pool: ModelDataPoolId;
  readonly aliases?: ReadonlyArray<string>;
}

export interface ModelDataRegistryRow {
  readonly provider: ModelDataProvider;
  readonly model: string;
  readonly family: ModelDataFamily;
  /** Opaque provider options (effort, permissionMode, …); S3 maps to typed options. */
  readonly options?: Readonly<Record<string, unknown>>;
  readonly strongLeg?: boolean;
}

export interface ModelDataConfig {
  readonly version: string;
  readonly roster: ReadonlyArray<ModelDataRosterEntry>;
  readonly defaultCoderRecOrder: ReadonlyArray<string>;
  readonly registry: Readonly<Record<string, ModelDataRegistryRow>>;
}

function fail(path: string, reason: string): never {
  throw new Error(`model data at ${path}: ${reason}`);
}

/**
 * Resolve the operative model-data file path.
 *
 * 1. `ORCHESTRATOR_MODEL_DATA_PATH` when set (absolute or cwd-relative)
 * 2. else shipped `config/model-data.json` next to the package
 */
export function resolveModelDataPath(env: ModelDataEnv = process.env): string {
  const override = env[MODEL_DATA_PATH_ENV]?.trim();
  if (override !== undefined && override !== "") {
    return isAbsolute(override) ? override : join(process.cwd(), override);
  }
  return DEFAULT_MODEL_DATA_PATH;
}

function parseRosterEntry(
  raw: unknown,
  index: number,
  path: string,
): ModelDataRosterEntry {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    fail(path, `roster[${index}] must be an object`);
  }
  const record = raw as Record<string, unknown>;
  if (typeof record.id !== "string" || record.id.trim() === "") {
    fail(path, `roster[${index}] missing non-empty string "id"`);
  }
  if (typeof record.slug !== "string" || record.slug.trim() === "") {
    fail(path, `roster[${index}] missing non-empty string "slug"`);
  }
  if (typeof record.pool !== "string" || !CODER_POOLS.has(record.pool as ModelDataPoolId)) {
    fail(
      path,
      `roster[${index}] unknown pool "${String(record.pool)}" (expected supergrok|codex|claude)`,
    );
  }
  let aliases: ReadonlyArray<string> | undefined;
  if (record.aliases !== undefined) {
    if (!Array.isArray(record.aliases)) {
      fail(path, `roster[${index}] aliases must be an array of strings`);
    }
    aliases = record.aliases.map((alias, aliasIndex) => {
      if (typeof alias !== "string" || alias.trim() === "") {
        fail(
          path,
          `roster[${index}].aliases[${aliasIndex}] must be a non-empty string`,
        );
      }
      return alias.trim();
    });
  }
  return {
    id: record.id.trim(),
    slug: record.slug.trim(),
    pool: record.pool as ModelDataPoolId,
    ...(aliases !== undefined && aliases.length > 0 ? { aliases } : {}),
  };
}

function parseRegistryRow(
  slug: string,
  raw: unknown,
  path: string,
): ModelDataRegistryRow {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    fail(path, `registry["${slug}"] must be an object`);
  }
  const record = raw as Record<string, unknown>;
  if (
    typeof record.provider !== "string" ||
    !MODEL_PROVIDERS.has(record.provider as ModelDataProvider)
  ) {
    fail(
      path,
      `registry["${slug}"] has invalid provider "${String(record.provider)}"`,
    );
  }
  if (typeof record.model !== "string") {
    // Empty model string is legal (agy default).
    fail(path, `registry["${slug}"] missing string "model"`);
  }
  if (
    typeof record.family !== "string" ||
    !MODEL_FAMILIES.has(record.family as ModelDataFamily)
  ) {
    fail(
      path,
      `registry["${slug}"] has invalid family "${String(record.family)}"`,
    );
  }
  let options: Readonly<Record<string, unknown>> | undefined;
  if (record.options !== undefined) {
    if (
      typeof record.options !== "object" ||
      record.options === null ||
      Array.isArray(record.options)
    ) {
      fail(path, `registry["${slug}"].options must be a plain object`);
    }
    options = record.options as Readonly<Record<string, unknown>>;
  }
  if (record.strongLeg !== undefined && typeof record.strongLeg !== "boolean") {
    fail(path, `registry["${slug}"].strongLeg must be a boolean when present`);
  }
  return {
    provider: record.provider as ModelDataProvider,
    model: record.model,
    family: record.family as ModelDataFamily,
    ...(options !== undefined ? { options } : {}),
    ...(record.strongLeg === true ? { strongLeg: true } : {}),
  };
}

function parseModelDataDocument(parsed: unknown, path: string): ModelDataConfig {
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(`model data file must be a JSON object: ${path}`);
  }
  const root = parsed as Record<string, unknown>;

  if (typeof root.version !== "string" || root.version.trim() === "") {
    fail(path, `missing non-empty string "version"`);
  }

  if (!Array.isArray(root.roster) || root.roster.length === 0) {
    fail(path, `roster must be a non-empty array`);
  }
  const roster = root.roster.map((entry, index) =>
    parseRosterEntry(entry, index, path),
  );

  if (!Array.isArray(root.defaultCoderRecOrder) || root.defaultCoderRecOrder.length === 0) {
    fail(path, `defaultCoderRecOrder must be a non-empty array of strings`);
  }
  const defaultCoderRecOrder = root.defaultCoderRecOrder.map((id, index) => {
    if (typeof id !== "string" || id.trim() === "") {
      fail(
        path,
        `defaultCoderRecOrder[${index}] must be a non-empty string`,
      );
    }
    return id.trim();
  });

  if (
    typeof root.registry !== "object" ||
    root.registry === null ||
    Array.isArray(root.registry)
  ) {
    fail(path, `registry must be a non-empty object`);
  }
  const registryRaw = root.registry as Record<string, unknown>;
  const registryKeys = Object.keys(registryRaw);
  if (registryKeys.length === 0) {
    fail(path, `registry must be a non-empty object`);
  }
  const registry: Record<string, ModelDataRegistryRow> = {};
  for (const [slugKey, value] of Object.entries(registryRaw)) {
    const slug = slugKey.trim();
    if (slug === "") {
      fail(path, `registry has an empty slug key`);
    }
    registry[slug] = parseRegistryRow(slug, value, path);
  }

  return {
    version: root.version.trim(),
    roster,
    defaultCoderRecOrder,
    registry,
  };
}

/**
 * Load model-data from disk. **Every call re-reads the file** (no cache).
 *
 * Fail-closed: missing file / unreadable / bad JSON / bad shape all throw
 * with the resolved path and a concrete reason. No silent use of a previous
 * successful parse.
 */
export function loadModelData(env: ModelDataEnv = process.env): ModelDataConfig {
  const path = resolveModelDataPath(env);
  if (!existsSync(path)) {
    throw new Error(`model data file not found: ${path}`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`failed to parse model data at ${path}: ${detail}`);
  }
  return parseModelDataDocument(parsed, path);
}
