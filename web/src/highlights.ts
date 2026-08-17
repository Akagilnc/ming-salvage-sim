import { stripOrganicMarkdown } from "./format";
import { parseLeadingStageDirection } from "./components/scrollMessages";

/**
 * #544 / ADR 0045：判官短语 → 大臣气泡显示文本精确匹配。
 *
 * 匹配基准＝气泡实际正文渲染链：stripOrganicMarkdown 之后、再经
 * parseLeadingStageDirection 切出领头舞台指示后的 content。
 * 短语先过同一剥离函数；落在 action 段的短语按未命中静默丢弃；
 * 单条未命中静默丢弃，整清单不整崩。
 */
export function ministerDisplayContent(rawContent: string): {
  action: string | null;
  content: string;
} {
  const stripped = stripOrganicMarkdown(String(rawContent || ""));
  return parseLeadingStageDirection(stripped);
}

/** 返回命中显示正文的已剥离短语（保持首次出现顺序，去重）。 */
export function matchHighlightPhrases(
  rawContent: string,
  phrases: readonly string[] | null | undefined,
): string[] {
  const { content } = ministerDisplayContent(rawContent);
  if (!content || !Array.isArray(phrases) || phrases.length === 0) return [];
  const hit: string[] = [];
  const seen = new Set<string>();
  for (const raw of phrases) {
    const phrase = stripOrganicMarkdown(String(raw || ""));
    if (!phrase || seen.has(phrase)) continue;
    if (!content.includes(phrase)) continue;
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
