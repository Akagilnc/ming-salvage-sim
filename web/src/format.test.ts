import { describe, expect, it } from "vitest";
import { stripOrganicMarkdown } from "./format";

describe("stripOrganicMarkdown", () => {
  it("removes bold, italic, and list markers without changing the words", () => {
    expect(stripOrganicMarkdown("**要紧**，*速办*\n- 第一项\n* 第二项")).toBe("要紧，速办\n第一项\n第二项");
  });

  it("keeps Chinese punctuation at markdown boundaries", () => {
    expect(stripOrganicMarkdown("**户部**：*银两*；**兵部**、*军心*。")).toBe("户部：银两；兵部、军心。");
  });

  it("does not mutate the source string", () => {
    const source = "**原文**\n- 条目";
    stripOrganicMarkdown(source);
    expect(source).toBe("**原文**\n- 条目");
  });
});
