/**
 * #767 — design-time Coder-Rec roster (查表制).
 * #906 — parse issue body via real markdown AST first; unknown models / broken
 * marks fail closed (no silent default fallthrough).
 * #920 — pool isolation removed (ADR 0132 D5): same model may occupy coder and
 * review / cmrReview seats; only remaining isolation is fresh context + role prompt.
 * #1074 / ADR 0146 S2 — roster data rows live in model-data config (S1 loader);
 * every public lookup re-reads the file (用时现读). No in-code constant table.
 *
 * Designers mark each slice with a `Coder-Rec: X → Y → Z` fallback order.
 * The orchestrator only READS that marking: markdown-strip → parse → filter to
 * the live roster → dispatch the first valid entry (sticky stay-put;
 * ADR 0132 / #919 CR). No round-threshold mechanical advance; judge
 * `advanceCoder` is executed by the runner via {@link resolveAdvanceCoderSuggestion}
 * (#926) with stay-put when the target is unusable. No runtime adaptive state machine.
 */

import type { Content, Root } from "mdast";
import { toString } from "mdast-util-to-string";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import { unified } from "unified";

import {
  loadModelData,
  type ModelDataEnv,
  type ModelDataRosterEntry,
} from "./modelDataConfig.js";

export type CoderPoolId = "supergrok" | "codex" | "claude";

export interface CoderRosterEntry {
  /** Designer-facing id used in `Coder-Rec:` lines. */
  readonly id: string;
  /** Runnable modelRegistry slug used at dispatch. */
  readonly slug: string;
  /** Quota / provider pool this coder draws from. */
  readonly pool: CoderPoolId;
  /** Alternate tokens accepted in Coder-Rec lines. */
  readonly aliases?: ReadonlyArray<string>;
}

/** Thrown for broken Coder-Rec marks or unregistered model tokens (#906). */
export class CoderRecError extends Error {
  readonly code: "broken_mark" | "unknown_model";

  constructor(code: "broken_mark" | "unknown_model", message: string) {
    super(message);
    this.name = "CoderRecError";
    this.code = code;
  }
}

function toCoderEntry(entry: ModelDataRosterEntry): CoderRosterEntry {
  return {
    id: entry.id,
    slug: entry.slug,
    pool: entry.pool,
    ...(entry.aliases !== undefined && entry.aliases.length > 0
      ? { aliases: entry.aliases }
      : {}),
  };
}

/**
 * Live roster rows from model-data config. **Every call re-reads** (no cache).
 * Prefer this over holding a snapshot across dispatch boundaries.
 */
export function getCoderRoster(
  env: ModelDataEnv = process.env,
): ReadonlyArray<CoderRosterEntry> {
  return loadModelData(env).roster.map(toCoderEntry);
}

/** Live config `version` field (re-reads every call). */
export function getCoderRosterVersion(
  env: ModelDataEnv = process.env,
): string {
  return loadModelData(env).version;
}

/**
 * Default Coder-Rec order when the issue body has no marking (re-reads every call).
 */
export function getDefaultCoderRecOrder(
  env: ModelDataEnv = process.env,
): ReadonlyArray<string> {
  return loadModelData(env).defaultCoderRecOrder;
}

/** Allow optional Markdown bullet markers (`- `, `* `, `+ `) before the label. */
const CODER_REC_LINE =
  /^\s*(?:[-*+]\s+)?Coder-Rec\s*:\s*(.+?)\s*$/im;

// Case-insensitive: align presence probe with CODER_REC_LINE's /i flag so
// `coder-rec carefully` is broken-mark fail-closed, not silent absent (N4).
const CODER_REC_MARK = /Coder-Rec/i;

function splitCoderRecTokens(raw: string): string[] {
  return raw
    .split(/\s*(?:→|->|,|／|\/)\s*/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}

function legalRosterIds(roster: ReadonlyArray<CoderRosterEntry>): string {
  return roster.map((e) => e.id).join(", ");
}

/**
 * Body → mdast (remark-parse + GFM) → plain text lines per block.
 * `toString` strips bold / italic / inline code / links so designer markdown
 * decorations do not hide a legal Coder-Rec line (#899 / #906).
 */
function plainTextLinesFromMarkdown(body: string): string[] {
  const tree = unified().use(remarkParse).use(remarkGfm).parse(body) as Root;
  const lines: string[] = [];

  const walk = (nodes: ReadonlyArray<Content>): void => {
    for (const node of nodes) {
      if (node.type === "paragraph" || node.type === "heading") {
        const text = toString(node).trim();
        if (text.length > 0) lines.push(text);
        continue;
      }
      // Correctness B2 / #906: GFM table cells hold designer Coder-Rec marks.
      // Without tableCell extraction the walk only sees table→row structure and
      // never surfaces cell text — silent absent → default roster.
      if (node.type === "tableCell") {
        const text = toString(node).trim();
        if (text.length > 0) lines.push(text);
        continue;
      }
      if (node.type === "code") {
        for (const line of node.value.split("\n")) {
          const text = line.trim();
          if (text.length > 0) lines.push(text);
        }
        continue;
      }
      if ("children" in node && Array.isArray(node.children)) {
        walk(node.children as ReadonlyArray<Content>);
      }
    }
  };

  walk(tree.children);
  return lines;
}

/**
 * Parse the designer `Coder-Rec:` line from an issue body.
 * Returns the raw token list (not yet roster-filtered), or undefined if absent.
 *
 * #906: markdown is stripped first; a present but unparseable `Coder-Rec` mark
 * throws {@link CoderRecError} (fail-closed — never treat "broken mark" as absent).
 */
export function parseCoderRec(
  issueBody: string,
): ReadonlyArray<string> | undefined {
  const plain = plainTextLinesFromMarkdown(issueBody).join("\n");
  const match = CODER_REC_LINE.exec(plain);
  if (match !== null) {
    const tokens = splitCoderRecTokens(match[1] ?? "");
    if (tokens.length > 0) return tokens;
    throw new CoderRecError(
      "broken_mark",
      "Coder-Rec marking is present but has no model tokens; " +
        "expected a line like `Coder-Rec: model1 → model2`",
    );
  }
  // Presence on extracted plain text OR raw body: fail-closed when a mark is
  // visible in the issue but the AST walk did not yield a legal line (B2 residual
  // shapes — raw HTML, future mdast nodes, etc.). Never silent-default.
  if (CODER_REC_MARK.test(plain) || CODER_REC_MARK.test(issueBody)) {
    throw new CoderRecError(
      "broken_mark",
      "Coder-Rec marking is present but could not be parsed; " +
        "expected a line like `Coder-Rec: model1 → model2` " +
        "(markdown bold/code/links are stripped automatically)",
    );
  }
  return undefined;
}

function normalizeToken(token: string): string {
  return token.trim().toLowerCase();
}

function lookupInRoster(
  roster: ReadonlyArray<CoderRosterEntry>,
  token: string,
): CoderRosterEntry | undefined {
  const needle = normalizeToken(token);
  if (needle.length === 0) return undefined;
  for (const entry of roster) {
    if (normalizeToken(entry.id) === needle) return entry;
    if (normalizeToken(entry.slug) === needle) return entry;
    for (const alias of entry.aliases ?? []) {
      if (normalizeToken(alias) === needle) return entry;
    }
  }
  return undefined;
}

/** Look up a roster entry by id or alias (case-insensitive). Re-reads config. */
export function lookupCoderRosterEntry(
  token: string,
  env: ModelDataEnv = process.env,
): CoderRosterEntry | undefined {
  return lookupInRoster(getCoderRoster(env), token);
}

function entriesForTokens(
  roster: ReadonlyArray<CoderRosterEntry>,
  tokens: ReadonlyArray<string>,
): CoderRosterEntry[] {
  const seen = new Set<string>();
  const out: CoderRosterEntry[] = [];
  for (const token of tokens) {
    const entry = lookupInRoster(roster, token);
    if (entry === undefined) continue;
    if (seen.has(entry.id)) continue;
    seen.add(entry.id);
    out.push(entry);
  }
  return out;
}

/**
 * Resolve the roster-valid fallback order for an issue body.
 * Missing marking → live {@link getDefaultCoderRecOrder}.
 * Present marking with any unregistered token → throws {@link CoderRecError}
 * listing legal roster ids (owner rule: never silent-default unknown names).
 * Re-reads model-data config on every call.
 */
export function resolveCoderRecOrder(
  issueBody: string | undefined,
  env: ModelDataEnv = process.env,
): ReadonlyArray<CoderRosterEntry> {
  const data = loadModelData(env);
  const roster = data.roster.map(toCoderEntry);
  const parsed =
    issueBody !== undefined && issueBody.length > 0
      ? parseCoderRec(issueBody)
      : undefined;
  if (parsed === undefined) {
    return entriesForTokens(roster, data.defaultCoderRecOrder);
  }
  const unknown = parsed.filter((t) => lookupInRoster(roster, t) === undefined);
  if (unknown.length > 0) {
    throw new CoderRecError(
      "unknown_model",
      `Coder-Rec contains unregistered model token(s): ${unknown.join(", ")}. ` +
        `Legal roster ids: ${legalRosterIds(roster)}`,
    );
  }
  return entriesForTokens(roster, parsed);
}

/**
 * Select the active Coder-Rec entry.
 *
 * ADR 0132 / #919 CR: first roster-valid marked entry only (sticky stay-put).
 * Round-threshold mechanical advance is deleted — no rounds argument, no
 * fallback-after-N constant. Judge `advanceCoder` roster policy is #926.
 * Empty order still throws (misconfigured roster).
 */
export function selectCoderRecEntry(
  order: ReadonlyArray<CoderRosterEntry>,
): CoderRosterEntry {
  if (order.length === 0) {
    throw new Error(
      "coder roster order is empty — roster table / default order misconfigured",
    );
  }
  return order[0]!;
}

/**
 * #926 — pure policy for a judge `advanceCoder` suggestion.
 *
 * - Roster-valid target different from the active seat → `advanced`
 * - Unknown / unregistered token → `stay_put` (runner must never exit)
 * - Empty suggestion or already-active seat → `noop` (no ledger noise)
 *
 * Does not smoke, does not mutate routes — runner owns execution + audit.
 * Re-reads model-data config on every call (edit config → next advance sees it).
 */
export type AdvanceCoderDecision =
  | {
      readonly kind: "advanced";
      readonly entry: CoderRosterEntry;
      readonly fromSlug: string;
    }
  | {
      readonly kind: "stay_put";
      readonly reason: "unknown_target";
      readonly suggestion: string;
      readonly currentSlug: string;
    }
  | {
      readonly kind: "noop";
      readonly reason: "already_active" | "empty_suggestion";
      readonly currentSlug: string;
    };

export function resolveAdvanceCoderSuggestion(
  suggestion: string,
  currentCoderSlug: string,
  env: ModelDataEnv = process.env,
): AdvanceCoderDecision {
  const trimmed = suggestion.trim();
  if (trimmed.length === 0) {
    return {
      kind: "noop",
      reason: "empty_suggestion",
      currentSlug: currentCoderSlug,
    };
  }
  const roster = getCoderRoster(env);
  const entry = lookupInRoster(roster, trimmed);
  if (entry === undefined) {
    return {
      kind: "stay_put",
      reason: "unknown_target",
      suggestion: trimmed,
      currentSlug: currentCoderSlug,
    };
  }
  // Same seat via exact slug, id token, or roster alias of the current seat.
  const currentEntry = lookupInRoster(roster, currentCoderSlug);
  if (
    entry.slug === currentCoderSlug ||
    normalizeToken(entry.id) === normalizeToken(currentCoderSlug) ||
    (currentEntry !== undefined && currentEntry.id === entry.id)
  ) {
    return {
      kind: "noop",
      reason: "already_active",
      currentSlug: currentCoderSlug,
    };
  }
  return {
    kind: "advanced",
    entry,
    fromSlug: currentCoderSlug,
  };
}
