/** Match only substrings of the unchanged drama; never match a transformed copy. */
export function matchHighlightPhrases(
  rawContent: string,
  phrases: readonly string[] | null | undefined,
): string[] {
  if (!rawContent || !Array.isArray(phrases) || phrases.length === 0) return [];
  const hit: string[] = [];
  const seen = new Set<string>();
  for (const raw of phrases) {
    const phrase = String(raw || "");
    if (!phrase || seen.has(phrase)) continue;
    if (!rawContent.includes(phrase)) continue;
    seen.add(phrase);
    hit.push(phrase);
  }
  return hit;
}

/** 将显示正文按命中短语切成 plain / mark 段（非重叠、从左贪心最长优先）。 */
export function segmentHighlightedContent(
  displayContent: string,
  matchedPhrases: readonly string[],
): Array<{ text: string; highlight: boolean }> {
  if (!displayContent) return [];
  if (!matchedPhrases.length) return [{ text: displayContent, highlight: false }];
  const phrases = [...matchedPhrases].filter(Boolean).sort((a, b) => b.length - a.length);
  const segments: Array<{ text: string; highlight: boolean }> = [];
  let cursor = 0;
  while (cursor < displayContent.length) {
    let bestIdx = -1;
    let bestPhrase = "";
    for (const phrase of phrases) {
      const at = displayContent.indexOf(phrase, cursor);
      if (at < 0) continue;
      if (bestIdx < 0 || at < bestIdx || (at === bestIdx && phrase.length > bestPhrase.length)) {
        bestIdx = at;
        bestPhrase = phrase;
      }
    }
    if (bestIdx < 0) {
      segments.push({ text: displayContent.slice(cursor), highlight: false });
      break;
    }
    if (bestIdx > cursor) {
      segments.push({ text: displayContent.slice(cursor, bestIdx), highlight: false });
    }
    segments.push({ text: bestPhrase, highlight: true });
    cursor = bestIdx + bestPhrase.length;
  }
  return segments;
}
