function filled(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed === undefined || trimmed.length === 0 ? undefined : trimmed;
}

export function hasExplicitAcceptedSuppressionSource(
  source: string | undefined,
): boolean {
  const text = filled(source)?.toLowerCase();
  if (text === undefined) return false;
  const hasAuthoritativeToken =
    /(^|\s)(#\d+|issue\s*#\d+|adr\s*0*\d+|owner|human|user)\b/i.test(text);
  if (hasAuthoritativeToken) return true;
  return false;
}

export function hasBoundedReopenCondition(
  boundedReopen: string | undefined,
): boolean {
  const text = filled(boundedReopen)?.toLowerCase();
  if (text === undefined) return false;
  return /\breopen\b/.test(text) && /\b(if|when|on|upon|unless)\b/.test(text);
}

export function hasAcceptedSuppressionAuthority(input: {
  readonly source?: string;
  readonly scope?: string;
  readonly reason?: string;
  readonly boundedReopen?: string;
}): boolean {
  return (
    hasExplicitAcceptedSuppressionSource(input.source) &&
    filled(input.scope) !== undefined &&
    filled(input.reason) !== undefined &&
    hasBoundedReopenCondition(input.boundedReopen)
  );
}
