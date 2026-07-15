/**
 * #767 — design-time Coder-Rec roster (查表制).
 * #906 — parse issue body via real markdown AST first; unknown models / broken
 * marks fail closed (no silent default fallthrough).
 * #920 — pool isolation removed (ADR 0132 D5): same model may occupy coder and
 * review / cmrReview seats; only remaining isolation is fresh context + role prompt.
 *
 * Designers mark each slice with a `Coder-Rec: X → Y → Z` fallback order.
 * The orchestrator only READS that marking: markdown-strip → parse → filter to
 * this versioned roster → dispatch the first valid entry → advance after N
 * non-converging review/fix rounds. No runtime adaptive state machine.
 */

import type { Content, Root } from "mdast";
import { toString } from "mdast-util-to-string";
import remarkGfm from "remark-gfm";
import remarkParse from "remark-parse";
import { unified } from "unified";

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

/** Roster table version — bump when #424 bench updates the eligible set. */
export const CODER_ROSTER_VERSION = "2026-07-11.1";

/**
 * Eligible coder models (model × pool × aliases). Keep in sync with
 * `docs/CODER_ROSTER.md` and #424 bench updates.
 *
 * #789 — Claude pool entries (`sonnet-5` / `haiku-4.5`) are grok-exhaustion
 * backups (runnable slugs `sonnet` / `haiku`). #920: same-model cross-role is
 * legal, so slug overlap with cmrReview / reviewer seats is not filtered.
 */
export const CODER_ROSTER: ReadonlyArray<CoderRosterEntry> = [
  {
    id: "grok-4.5",
    slug: "grok-4.5",
    pool: "supergrok",
  },
  {
    id: "terra@med",
    slug: "gpt-5.6-terra",
    pool: "codex",
    aliases: ["terra@med+fast", "gpt-5.6-terra"],
  },
  {
    id: "luna@med",
    slug: "gpt-5.6-luna",
    pool: "codex",
    aliases: ["luna@med+fast", "gpt-5.6-luna"],
  },
  {
    id: "sol@med",
    slug: "gpt-5.6-sol",
    pool: "codex",
    aliases: ["sol@med+fast", "gpt-5.6-sol"],
  },
  {
    id: "sonnet-5",
    slug: "sonnet",
    pool: "claude",
    aliases: ["Sonnet 5", "sonnet"],
  },
  {
    id: "haiku-4.5",
    slug: "haiku",
    pool: "claude",
    aliases: ["Haiku 4.5", "haiku"],
  },
];

/** Default fallback order when the issue body has no Coder-Rec line. */
export const DEFAULT_CODER_REC_ORDER: ReadonlyArray<string> = [
  "grok-4.5",
  "terra@med",
  "luna@med",
];

/**
 * Historical round-threshold for mechanical Coder-Rec advance (pre-ADR 0132).
 * Kept as a named constant for tests that prove the live path no longer
 * rotates models when this many (or more) non-converging rounds elapse.
 * Live selection ignores it — judge `advanceCoder` is the sole advance signal
 * once #926 wires roster policy.
 */
export const CODER_REC_FALLBACK_AFTER_ROUNDS = 2;

/**
 * Completed S6 (fresh full-diff re-review) rounds in a run ledger.
 *
 * #899 (2026-07-15): the ledger carries a `worker_monitor_spawned` EVENT row
 * AND a completion row per S6 round (plus other bookkeeping event rows with
 * step ids). Counting raw `step === "S6"` rows doubled one real round into
 * two. Only event-less rows are completed rounds. (#920 removed the follow-on
 * pool-separation exhaust path; ADR 0132 also abolishes round-threshold
 * Coder-Rec model rotation — this counter is ledger telemetry / resume aid.)
 */
export function completedS6RoundsFromLedger(
  entries: ReadonlyArray<{ readonly step?: string; readonly event?: string }>,
): number {
  return entries.reduce(
    (n, e) => (e.step === "S6" && e.event === undefined ? n + 1 : n),
    0,
  );
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

function legalRosterIds(): string {
  return CODER_ROSTER.map((e) => e.id).join(", ");
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

/** Look up a roster entry by id or alias (case-insensitive). */
export function lookupCoderRosterEntry(
  token: string,
): CoderRosterEntry | undefined {
  const needle = normalizeToken(token);
  if (needle.length === 0) return undefined;
  for (const entry of CODER_ROSTER) {
    if (normalizeToken(entry.id) === needle) return entry;
    if (normalizeToken(entry.slug) === needle) return entry;
    for (const alias of entry.aliases ?? []) {
      if (normalizeToken(alias) === needle) return entry;
    }
  }
  return undefined;
}

function entriesForTokens(
  tokens: ReadonlyArray<string>,
): CoderRosterEntry[] {
  const seen = new Set<string>();
  const out: CoderRosterEntry[] = [];
  for (const token of tokens) {
    const entry = lookupCoderRosterEntry(token);
    if (entry === undefined) continue;
    if (seen.has(entry.id)) continue;
    seen.add(entry.id);
    out.push(entry);
  }
  return out;
}

/**
 * Resolve the roster-valid fallback order for an issue body.
 * Missing marking → {@link DEFAULT_CODER_REC_ORDER}.
 * Present marking with any unregistered token → throws {@link CoderRecError}
 * listing legal roster ids (owner rule: never silent-default unknown names).
 */
export function resolveCoderRecOrder(
  issueBody: string | undefined,
): ReadonlyArray<CoderRosterEntry> {
  const parsed =
    issueBody !== undefined && issueBody.length > 0
      ? parseCoderRec(issueBody)
      : undefined;
  if (parsed === undefined) {
    return entriesForTokens(DEFAULT_CODER_REC_ORDER);
  }
  const unknown = parsed.filter((t) => lookupCoderRosterEntry(t) === undefined);
  if (unknown.length > 0) {
    throw new CoderRecError(
      "unknown_model",
      `Coder-Rec contains unregistered model token(s): ${unknown.join(", ")}. ` +
        `Legal roster ids: ${legalRosterIds()}`,
    );
  }
  return entriesForTokens(parsed);
}

export interface SelectCoderRecOptions {
  /**
   * @deprecated ADR 0132 abolished round-threshold advance. Kept for call-site
   * signature stability; ignored.
   */
  readonly fallbackAfterRounds?: number;
}

/**
 * Select the active Coder-Rec entry.
 *
 * ADR 0132 / #919 CR P2: mechanical round-threshold advance
 * (`CODER_REC_FALLBACK_AFTER_ROUNDS`) is abolished. The first roster-valid
 * marked entry stays put for the run. Judge `advanceCoder` roster wiring is
 * #926 — until then, rounds never rotate the coder model. Stay-put forever
 * on empty order still throws (misconfigured roster).
 */
export function selectCoderRecEntry(
  order: ReadonlyArray<CoderRosterEntry>,
  _nonConvergingRounds: number = 0,
  _opts: SelectCoderRecOptions = {},
): CoderRosterEntry {
  if (order.length === 0) {
    throw new Error(
      "coder roster order is empty — roster table / default order misconfigured",
    );
  }
  return order[0]!;
}
