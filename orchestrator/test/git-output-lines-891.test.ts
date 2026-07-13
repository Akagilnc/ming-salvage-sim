import { describe, expect, it } from "vitest";
import { normalizeGitOutputLines } from "../src/runner.js";

describe("#891 git stdout line normalization", () => {
  it.each([
    ["empty bytes", "", []],
    ["LF-only output", "\n", []],
    ["CRLF-only output", "\r\n", []],
    ["one SHA", "abc123\n", ["abc123"]],
    ["multiple SHAs", "abc123\r\ndef456\r\n", ["abc123", "def456"]],
  ] as const)("normalizes %s", (_label, output, expected) => {
    expect(normalizeGitOutputLines(output)).toEqual(expected);
  });
});
