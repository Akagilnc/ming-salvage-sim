import { describe, expect, it } from "vitest";
import { stripOrganicMarkdown } from "./format";

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
