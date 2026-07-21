/**
 * ADR 0141 — legal review-leg paper is transport-only.
 *
 * A leg is present when the transport is alive (exit 0 + non-empty raw
 * stdout). Content shape is never a gate: pure prose, progress-style
 * narration, and reviews without structured / anchored candidate fields
 * all count as present. The judge distills anchors and dispositions from
 * raw stdout and emits the typed tri-state at the judge↔runner boundary
 * (ADR 0131 — the chain's only typed contract).
 *
 * Deleted extra-constitutional reject paths:
 *   - 「无锚点候选＝废票」— no structured/anchored candidate → void ballot
 *   - 「进度散文＝无卷」— progress-style prose → treat as no paper
 *
 * Behavior red lines that are NOT paper format (resource discipline) stay
 * elsewhere (e.g. no fan-out sub-agents).
 *
 * #1091 transport hardening (narrow exception): a single short opening line
 * with no findings structure (e.g. grok 「我要开始审…」 then exit 0) is
 * degraded — not successful. Multi-line / longer prose still counts as
 * present under ADR 0141.
 */

/** One review-leg transport observation (exit + raw stdout). */
export type LegTransport = {
  readonly slug: string;
  readonly exitCode: number;
  readonly stdout: string | null | undefined;
};

/** Max length for the #1091 opening-line degrade heuristic. */
const OPENING_LINE_MAX_CHARS = 120;

/**
 * #1091 — opening greetings / "I'll start reviewing" commitments with no
 * findings body. Progress narration ("Working… still scanning…") is NOT an
 * opening line under ADR 0141.
 *
 * The 「好的」 greeting variant makes 「我」 optional so forms like
 * 「好的，开始审」 / 「好的，开始进行审查」 also match (finding 2a).
 *
 * Note: do not trail CJK alternatives with `\b` — JS word boundaries are
 * ASCII-centric and reject matches like 「我要开始审…」.
 */
const OPENING_LINE_RE =
  /^(?:我要开始|开始审|好的[，,]?\s*(?:我(?:来|要)?)?开始|I'll start\b|I will start\b|Let me (?:start|begin)\b|Starting (?:the )?review\b)/i;

/**
 * #1091 — true when stdout is a single short greeting / opening line with
 * no findings-like structure (empty-success variant after grok exits early).
 * A greeting followed by substantive content on the same line (sentence break
 * + trailing word content) is NOT greeting-only — it stays legal paper.
 */
export function isOpeningLineOnlyStdout(
  stdout: string | null | undefined,
): boolean {
  const trimmed = (stdout ?? "").trim();
  if (trimmed.length === 0) return false;
  const lines = trimmed.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length !== 1) return false;
  const line = lines[0]!;
  if (line.length > OPENING_LINE_MAX_CHARS) return false;
  if (!OPENING_LINE_RE.test(line)) return false;
  // #1091 finding 2b: a greeting prefix followed by substantive content on the
  // same line is NOT greeting-only — keep it as legal paper.
  if (/[.!?。！？…]\s+\S/.test(line)) return false;
  // Findings / review structure → still legal paper even if short.
  if (/findings?\s*[:\[]/i.test(line)) return false;
  if (/^\s*[{[]/.test(line)) return false;
  if (/\bP[0-3]\b/.test(line)) return false;
  if (/##\s/.test(line)) return false;
  return true;
}

/**
 * True when a review leg produced legal paper under ADR 0141.
 *
 * - exit 0 + non-empty trimmed stdout → present
 * - non-zero exit, empty, or whitespace-only stdout → absent
 * - #1091: exit 0 + single short opening line → absent (degraded)
 *
 * Never inspects multi-line content shape (candidates, anchors, progress vs review).
 */
export function isLegalLegPaper(input: {
  readonly exitCode: number;
  readonly stdout: string | null | undefined;
}): boolean {
  if (input.exitCode !== 0) return false;
  if ((input.stdout ?? "").trim().length === 0) return false;
  if (isOpeningLineOnlyStdout(input.stdout)) return false;
  return true;
}

/**
 * Build family-cmr `successfulLegs` from observed transports (ADR 0141).
 *
 * Present = {@link isLegalLegPaper}; order follows the transport list.
 * Content shape is never a gate. Production host path:
 * {@link cmrOutcomeFromResult} overlays this list onto judge/verdict cargo
 * when `legTransports` are supplied (argument or soft cargo).
 */
export function successfulLegsFromTransports(
  transports: ReadonlyArray<LegTransport>,
): string[] {
  const present: string[] = [];
  for (const leg of transports) {
    if (typeof leg.slug !== "string") continue;
    const slug = leg.slug.trim();
    if (slug.length === 0) continue;
    if (isLegalLegPaper(leg)) present.push(slug);
  }
  return present;
}
