/**
 * ADR 0141 / 0142 — legal review-leg paper is transport-only.
 *
 * The runner observes only exit status and whether raw stdout is non-empty.
 * It never classifies the prose by keywords, regexes, structure, or meaning;
 * the judge reads the raw paper and emits the typed verdict.
 */

/** One review-leg transport observation (exit + raw stdout). */
export type LegTransport = {
  readonly slug: string;
  readonly exitCode: number;
  readonly stdout: string | null | undefined;
};

/** Exit 0 plus non-empty raw stdout is legal paper. */
export function isLegalLegPaper(input: {
  readonly exitCode: number;
  readonly stdout: string | null | undefined;
}): boolean {
  return input.exitCode === 0 && (input.stdout ?? "").trim().length > 0;
}

/** Build family-CMR successful-leg traffic from host-observed transports. */
export function successfulLegsFromTransports(
  transports: ReadonlyArray<LegTransport>,
): string[] {
  const present: string[] = [];
  for (const leg of transports) {
    if (typeof leg.slug !== "string") continue;
    const slug = leg.slug.trim();
    if (slug.length > 0 && isLegalLegPaper(leg)) present.push(slug);
  }
  return present;
}
