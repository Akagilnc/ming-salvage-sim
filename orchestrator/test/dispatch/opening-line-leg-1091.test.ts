/**
 * #1091 — single short opening-line stdout is degraded, not successful.
 * Seam: {@link isLegalLegPaper} / {@link isOpeningLineOnlyStdout}.
 */
import { describe, expect, it } from "vitest";
import {
  isLegalLegPaper,
  isOpeningLineOnlyStdout,
  successfulLegsFromTransports,
} from "../../src/legPaper.js";

describe("#1091 opening-line stdout is degraded", () => {
  it("classifies a single short opening line as opening-line-only", () => {
    expect(isOpeningLineOnlyStdout("我要开始审…")).toBe(true);
    expect(isOpeningLineOnlyStdout("I'll start the review now.")).toBe(true);
  });

  it("rejects opening-line-only stdout as legal paper (exit 0)", () => {
    expect(
      isLegalLegPaper({ exitCode: 0, stdout: "我要开始审…" }),
    ).toBe(false);
  });

  it("still accepts multi-line prose reviews (ADR 0141)", () => {
    const prose = [
      "我要开始审。",
      "",
      "## Finding",
      "P1: missing auth mount for claude panel legs.",
    ].join("\n");
    expect(isOpeningLineOnlyStdout(prose)).toBe(false);
    expect(isLegalLegPaper({ exitCode: 0, stdout: prose })).toBe(true);
  });

  it("omits opening-line legs from successfulLegsFromTransports", () => {
    expect(
      successfulLegsFromTransports([
        { slug: "grok-4.5", exitCode: 0, stdout: "我要开始审…" },
        {
          slug: "sonnet",
          exitCode: 0,
          stdout: "Finding P1: auth missing\nMore review body here.",
        },
      ]),
    ).toEqual(["sonnet"]);
  });
});
