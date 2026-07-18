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
 */

/** One review-leg transport observation (exit + raw stdout). */
export type LegTransport = {
  readonly slug: string;
  readonly exitCode: number;
  readonly stdout: string | null | undefined;
};

/**
 * True when a review leg produced legal paper under ADR 0141.
 *
 * - exit 0 + non-empty trimmed stdout → present
 * - non-zero exit, empty, or whitespace-only stdout → absent
 *
 * Never inspects content shape (candidates, anchors, progress vs review).
 */
export function isLegalLegPaper(input: {
  readonly exitCode: number;
  readonly stdout: string | null | undefined;
}): boolean {
  if (input.exitCode !== 0) return false;
  return (input.stdout ?? "").trim().length > 0;
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
