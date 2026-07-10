/**
 * #767 — design-time Coder-Rec roster (查表制).
 *
 * Designers mark each slice with a `Coder-Rec: X → Y → Z` fallback order.
 * The orchestrator only READS that marking: parse → filter to this versioned
 * roster → dispatch the first valid entry → advance after N non-converging
 * review/fix rounds. No runtime adaptive state machine.
 *
 * Pool-separation hard rule: a coder roster entry must not also appear as an
 * active reviewer leg (same slug). Prefer the next roster-valid entry instead.
 */

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

/** Roster table version — bump when #424 bench updates the eligible set. */
export const CODER_ROSTER_VERSION = "2026-07-11";

/**
 * Eligible coder models (model × pool × aliases). Keep in sync with
 * `docs/CODER_ROSTER.md` and #424 bench updates.
 *
 * #789 — Claude pool entries (`sonnet-5` / `haiku-4.5`) are grok-exhaustion
 * backups. Their runnable slugs (`sonnet` / `haiku`) differ from the cmrReview
 * Claude leg (`opus`), so they do not trip pool-separation against normal CMR.
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
 * After this many non-converging per-slice review/fix rounds on the current
 * coder, advance to the next roster-valid entry (issue: "2-3 轮不收敛 → 顺位补位").
 */
export const CODER_REC_FALLBACK_AFTER_ROUNDS = 2;

/** Allow optional Markdown bullet markers (`- `, `* `, `+ `) before the label. */
const CODER_REC_LINE =
  /^\s*(?:[-*+]\s+)?Coder-Rec\s*:\s*(.+?)\s*$/im;

function splitCoderRecTokens(raw: string): string[] {
  return raw
    .split(/\s*(?:→|->|,|／|\/)\s*/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}

/**
 * Parse the designer `Coder-Rec:` line from an issue body.
 * Returns the raw token list (not yet roster-filtered), or undefined if absent.
 */
export function parseCoderRec(
  issueBody: string,
): ReadonlyArray<string> | undefined {
  const match = CODER_REC_LINE.exec(issueBody);
  if (match === null) return undefined;
  const tokens = splitCoderRecTokens(match[1] ?? "");
  return tokens.length > 0 ? tokens : undefined;
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
 * Missing / empty / all-invalid markings → {@link DEFAULT_CODER_REC_ORDER}.
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
  const dropped = parsed.filter((t) => lookupCoderRosterEntry(t) === undefined);
  const fromMarking = entriesForTokens(parsed);
  if (fromMarking.length === 0) {
    console.info(
      `[coder-roster] Coder-Rec tokens all invalid (${dropped.join(", ")}); degrading to default order`,
    );
    return entriesForTokens(DEFAULT_CODER_REC_ORDER);
  }
  if (dropped.length > 0) {
    console.info(
      `[coder-roster] dropped invalid Coder-Rec token(s): ${dropped.join(", ")}`,
    );
  }
  return fromMarking;
}

export interface SelectCoderRecOptions {
  /** Active reviewer / CMR leg slugs — used for pool-separation filtering. */
  readonly reviewerSlugs?: ReadonlyArray<string> | ReadonlySet<string>;
  /** Override the default fallback threshold (tests). */
  readonly fallbackAfterRounds?: number;
}

function indexForRounds(
  nonConvergingRounds: number,
  orderLength: number,
  fallbackAfterRounds: number,
): number {
  if (orderLength <= 0) return 0;
  if (fallbackAfterRounds <= 0) return 0;
  const steps = Math.floor(
    Math.max(0, nonConvergingRounds) / fallbackAfterRounds,
  );
  return Math.min(steps, orderLength - 1);
}

/**
 * Hard rule: a coder roster entry must not double as an active reviewer leg
 * (same runnable slug). Returns a human-readable violation, or undefined if ok.
 */
export function poolSeparationViolation(
  coder: CoderRosterEntry,
  reviewerSlugs: ReadonlyArray<string> | ReadonlySet<string>,
): string | undefined {
  const reviewer: ReadonlySet<string> = reviewerSlugs instanceof Set
    ? reviewerSlugs
    : new Set(
        (reviewerSlugs as ReadonlyArray<string>)
          .map((s) => s.trim())
          .filter((s) => s.length > 0),
      );
  if (!reviewer.has(coder.slug)) return undefined;
  return (
    `coder roster entry "${coder.id}" (slug=${coder.slug}) must not double as ` +
    `a reviewer leg; pick a different Coder-Rec entry or change the reviewer route`
  );
}

/**
 * Select the coder for the current non-converging-round count.
 * Advances one roster step every {@link CODER_REC_FALLBACK_AFTER_ROUNDS} rounds.
 * Skips entries that violate pool separation when a later entry is available;
 * if every remaining entry collides, returns the indexed entry (degraded).
 */
export function selectCoderRecEntry(
  order: ReadonlyArray<CoderRosterEntry>,
  nonConvergingRounds: number,
  opts: SelectCoderRecOptions = {},
): CoderRosterEntry {
  if (order.length === 0) {
    throw new Error(
      "coder roster order is empty — roster table / default order misconfigured",
    );
  }
  const threshold =
    opts.fallbackAfterRounds ?? CODER_REC_FALLBACK_AFTER_ROUNDS;
  const start = indexForRounds(nonConvergingRounds, order.length, threshold);
  const reviewerSlugs = new Set(
    [...(opts.reviewerSlugs ?? [])]
      .map((slug) => slug.trim())
      .filter((slug) => slug.length > 0),
  );

  for (let i = start; i < order.length; i++) {
    const candidate = order[i]!;
    if (poolSeparationViolation(candidate, reviewerSlugs) === undefined) {
      return candidate;
    }
  }
  // Degraded: every remaining entry collides with a reviewer leg.
  return order[start]!;
}

/**
 * Active reviewer / CMR-leg slugs from a resolved model route.
 * Includes per-slice reviewer, CMR gate slots (completeness / correctness /
 * verify), and cmrReview collection legs — coder roster entries must not
 * double as any of these (pool-separation hard rule).
 */
export function reviewerSlugsFromRoute(route: {
  readonly slots: {
    readonly reviewer: string;
    readonly cmrCompleteness: string;
    readonly cmrCorrectness: string;
    readonly verify: string;
  };
  readonly legCollections: {
    readonly cmrReview: ReadonlyArray<{ readonly slug: string }>;
  };
}): string[] {
  return [
    route.slots.reviewer,
    route.slots.cmrCompleteness,
    route.slots.cmrCorrectness,
    route.slots.verify,
    ...route.legCollections.cmrReview.map((leg) => leg.slug),
  ];
}
