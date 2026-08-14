import { describe, expect, it } from "vitest";
import { filterMatchedHighlights, stripOrganicMarkdown } from "./format";

describe("stripOrganicMarkdown", () => {
  it("removes bold, italic, and list markers without changing the words", () => {
    expect(stripOrganicMarkdown("**要紧**，*速办*\n- 第一项\n* 第二项")).toBe("要紧，速办\n第一项\n第二项");
  });

  it("keeps Chinese punctuation at markdown boundaries", () => {
    expect(stripOrganicMarkdown("**户部**：*银两*；**兵部**、*军心*。")).toBe("户部：银两；兵部、军心。");
  });

  it("removes ordered list markers", () => {
    expect(stripOrganicMarkdown("1. 第一项\n2) 第二项")).toBe("第一项\n第二项");
  });

  it("removes ordered and unordered markers from mixed lists", () => {
    expect(stripOrganicMarkdown("1. 第一项\n- 第二项\n2) 第三项\n* 第四项")).toBe("第一项\n第二项\n第三项\n第四项");
  });

  it("removes headings, blockquotes, links, and inline-code markers", () => {
    expect(stripOrganicMarkdown("# 标题\n> 引文\n[正文](https://example.com)\n`代码`"))
      .toBe("标题\n引文\n正文\n代码");
  });

  it("preserves markdown-looking content inside inline code spans", () => {
    expect(stripOrganicMarkdown("`**原样**`\n`- 原样`"))
      .toBe("**原样**\n- 原样");
  });

  it("preserves inline-code content literally", () => {
    expect(stripOrganicMarkdown("`  a  `\n`a\nb`"))
      .toBe("  a  \na\nb");
  });

  it("preserves code content when a link destination contains a backtick", () => {
    expect(stripOrganicMarkdown("[甲](u`v`) `  a  `"))
      .toBe("甲   a  ");
  });

  it("keeps image alt text while stripping images and thematic breaks", () => {
    expect(stripOrganicMarkdown("甲 ![军报](https://example.com/report.png) 乙\n\n---\n\n丙"))
      .toBe("甲 军报 乙\n\n丙");
  });

  it("preserves table cell and row boundaries", () => {
    expect(stripOrganicMarkdown("| 甲 | 乙 |\n| --- | --- |\n| 丙 | 丁 |"))
      .toBe("甲\t乙\n丙\t丁");
  });

  it("decodes markdown entities consistently", () => {
    expect(stripOrganicMarkdown("&copy; **2026**")).toBe("© 2026");
  });

  it("does not treat user text that resembles an internal code placeholder as a code span", () => {
    expect(stripOrganicMarkdown("正文\uE0000\uE001尾")).toBe("正文\uE0000\uE001尾");
  });

  it("preserves code spans delimited by repeated backticks", () => {
    expect(stripOrganicMarkdown("``**code**``\n```- code```"))
      .toBe("**code**\n- code");
  });

  it("strips emphasis that is interrupted by a code span without reprocessing the code", () => {
    expect(stripOrganicMarkdown("甲**乙`丙`**")).toBe("甲乙丙");
  });

  it("renders an escaped link opener as literal text", () => {
    expect(stripOrganicMarkdown("\\[正文](url)")).toBe("[正文](url)");
  });

  it("uses backslash parity when deciding whether a backtick opens code", () => {
    expect(stripOrganicMarkdown("\\`非代码`")).toBe("`非代码`");
    expect(stripOrganicMarkdown("\\\\`代码 **原样**`")).toBe("\\代码 **原样**");
  });

  it("keeps unmatched emphasis delimiters as literal punctuation", () => {
    expect(stripOrganicMarkdown("甲**乙*丙")).toBe("甲**乙*丙");
  });

  it("strips valid nested emphasis after strong text", () => {
    expect(stripOrganicMarkdown("**粗体***斜体*")).toBe("粗体斜体");
  });

  it("strips valid nested emphasis before strong text", () => {
    expect(stripOrganicMarkdown("*斜体***粗体**")).toBe("斜体粗体");
  });

  it("treats Chinese letters as word characters around emphasis markers", () => {
    expect(stripOrganicMarkdown("字段_税率_值")).toBe("字段_税率_值");
  });

  it("strips bold text adjacent to CJK letters", () => {
    expect(stripOrganicMarkdown("甲**乙**丙")).toBe("甲乙丙");
  });

  it("renders escaped emphasis delimiters as literal punctuation, not emphasis", () => {
    expect(stripOrganicMarkdown("\\*原样\\*")).toBe("*原样*");
    expect(stripOrganicMarkdown("\\_下划线\\_")).toBe("_下划线_");
  });

  it("keeps underscores next to combining marks", () => {
    expect(stripOrganicMarkdown("e\u0301_x_!")).toBe("e\u0301_x_!");
  });

  it("strips links whose URLs contain nested parentheses", () => {
    expect(stripOrganicMarkdown("[正文](https://example.com/a_(b))")).toBe("正文");
  });

  it("strips links whose URLs contain escaped closing parentheses", () => {
    expect(stripOrganicMarkdown("[正文](https://example.com/a\\))")).toBe("正文");
  });

  it("strips nested block prefixes until the line is plain", () => {
    expect(stripOrganicMarkdown("> # 标题\n- > 引文"))
      .toBe("标题\n引文");
  });

  it("does not strip underscores inside words or multiplication asterisks", () => {
    expect(stripOrganicMarkdown("snake_case_value\n2 * 3 * 4")).toBe("snake_case_value\n2 * 3 * 4");
  });

  it("does not consume blank lines before list markers", () => {
    expect(stripOrganicMarkdown("前段。\n\n1. 第一项")).toBe("前段。\n\n第一项");
  });

  it("does not mutate the source string", () => {
    const source = "**原文**\n- 条目";
    stripOrganicMarkdown(source);
    expect(source).toBe("**原文**\n- 条目");
  });
});

describe("filterMatchedHighlights — sole browser strip/match authority", () => {
  it("strips phrases, exact-matches stripped answer, drops misses; keeps code-span padding", () => {
    const answer = "臣请`  据实核账  `，不可臆断。";
    expect(filterMatchedHighlights(answer, ["`  据实核账  `", "未命中", "臆断"]))
      .toEqual(["  据实核账  ", "臆断"]);
    expect(stripOrganicMarkdown(answer)).toContain("  据实核账  ");
  });

  it("loads the release-layout authority product bytes (web/dist/organicMarkdown.js)", async () => {
    const { readFileSync, existsSync } = await import("node:fs");
    const { dirname, join } = await import("node:path");
    const { fileURLToPath } = await import("node:url");
    const product = join(dirname(fileURLToPath(import.meta.url)), "..", "dist", "organicMarkdown.js");
    expect(existsSync(product)).toBe(true);
    const source = readFileSync(product, "utf8");
    expect(source).toContain("filterMatchedHighlights");
    expect(source).toContain("OrganicMarkdown");
  });
});
