import { describe, expect, it } from "vitest";
import { parseLeadingStageDirection, stripOrganicMarkdown } from "./format";
import {
  matchHighlightPhrases,
  ministerDisplayContent,
  segmentHighlightedContent,
} from "./highlights";

describe("highlight match baseline (#544 AC3)", () => {
  it("hits stripped display content when phrase still carries organic markers", () => {
    const raw = "（跪奏）臣陈**辽饷**与*军心*，请陛下钧裁。";
    // 真实渲染链产物：strip → 切领头舞台指示
    const stripped = stripOrganicMarkdown(raw);
    const { action, content } = parseLeadingStageDirection(stripped);
    expect(action).toBe("（跪奏）");
    expect(content).toContain("辽饷");
    expect(content).not.toContain("**");

    const viaHelper = ministerDisplayContent(raw);
    expect(viaHelper).toEqual({ action, content });

    const matched = matchHighlightPhrases(raw, ["**辽饷**", "*军心*"]);
    expect(matched).toEqual(["辽饷", "军心"]);
    // 命中短语可在显示正文中精确找到
    for (const phrase of matched) {
      expect(content.includes(phrase)).toBe(true);
    }
  });

  it("silently drops unmatched items and phrases that only land in the action segment", () => {
    const raw = "（搁笔太息）臣以为户部尚可周转。";
    const matched = matchHighlightPhrases(raw, [
      "搁笔太息", // 只在 action 段
      "（搁笔太息）",
      "户部尚可周转",
      "纯属捏造",
      "",
    ]);
    expect(matched).toEqual(["户部尚可周转"]);
    // 整清单不整崩：未命中不抛
    expect(() => matchHighlightPhrases(raw, ["无", "有", "**x**"])).not.toThrow();
    expect(matchHighlightPhrases(raw, ["无", "有", "**x**"])).toEqual([]);
  });

  it("segments display content for minister-only mark rendering", () => {
    const display = "臣陈辽饷与军心。";
    const segs = segmentHighlightedContent(display, ["辽饷", "军心"]);
    expect(segs.filter((s) => s.highlight).map((s) => s.text)).toEqual(["辽饷", "军心"]);
    expect(segs.map((s) => s.text).join("")).toBe(display);
  });
});
