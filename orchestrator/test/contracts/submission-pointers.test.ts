/**
 * #880 (873·S6) / #911 — ADR 0130 submission-contract pointers in role files.
 *
 * #911 rewrote souls as Chinese character editions: the pointer lives as short
 * citations (交卷契约 → ADR 0130 / 钉子令牌 / 钉上刻字), not English restatements.
 * Thin prompts still defer method to the soul + skills.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const soulsDir = join(here, "..", "..", "image", "souls");
const promptsDir = join(here, "..", "..", "prompts");

function readSoul(name: string): string {
  return readFileSync(join(soulsDir, name), "utf8");
}

function readPrompt(name: string): string {
  return readFileSync(join(promptsDir, name), "utf8");
}

/** Collapse hard-wrap so phrase pins survive line breaks. */
function norm(text: string): string {
  return text.replace(/\s+/g, " ");
}

describe("#880/#911 ADR 0130 pointer — per-slice reviewer soul", () => {
  const soul = norm(readSoul("reviewer.md"));

  it("cites ADR 0130 / 交卷契约 and requires recording every finding", () => {
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toMatch(/交卷契约/);
    expect(soul).toMatch(/每条 finding 都欠一个记录/);
    expect(soul).toMatch(/只评审不修复/);
  });
});

describe("#880/#911 ADR 0130 pointer — verify soul (cmr_* symlink target)", () => {
  const soul = norm(readSoul("verify.md"));
  const completeness = norm(readSoul("cmr_completeness.md"));
  const correctness = norm(readSoul("cmr_correctness.md"));

  it("verify soul carries 交卷契约 + 钉子令牌 + 钉上刻字", () => {
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toMatch(/交卷契约/);
    expect(soul).toContain("钉子令牌");
    expect(soul).toContain("钉上刻字");
    expect(soul).toMatch(/严重度是标签，不是入场券/);
  });

  it("cmr_completeness/cmr_correctness resolve to the same verify body", () => {
    expect(completeness).toBe(soul);
    expect(correctness).toBe(soul);
  });
});

describe("#880/#911 ADR 0130 pointer — fixer first-duty", () => {
  const soul = norm(readSoul("fixer.md"));

  it("cites ADR 0130 and makes adjudication the first duty", () => {
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toMatch(/交卷契约/);
    expect(soul).toMatch(/裁决是你的第一义务|第一义务/);
    expect(soul).toMatch(/真 → 修/);
    expect(soul).toMatch(/违宪|过度防御|事实不成立|越权加戏/);
  });
});

describe("#880/#911 ADR 0130 pointer — per-slice coder-fix", () => {
  const soul = norm(readSoul("coder.md"));
  const prompt = norm(readPrompt("coder_fix.md"));

  it("coder soul cites ADR 0130 for verify-then-fix / refuse first duty", () => {
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toMatch(/裁决是第一义务/);
    expect(soul).toMatch(/refusedFindingIdentityKeys/);
    expect(soul).toMatch(/对真实代码验证/);
  });

  it("coder_fix prompt stays thin while soul carries ADR 0130 adjudication taste", () => {
    // Prompt may mention refuse mechanics as vacuum fill, but soul owns the duty.
    expect(soul).toMatch(/ADR 0130/);
    expect(prompt).toMatch(/coder\.md/);
  });
});

describe("#880/#911 thin reviewer prompt defers to soul", () => {
  const prompt = readPrompt("reviewer_review.md");

  it("still routes method to the live-mounted reviewer soul", () => {
    expect(prompt).toMatch(
      /\/home\/agent\/\.orchestrator\/souls\/reviewer\.md/,
    );
    const n = norm(prompt);
    expect(n).not.toMatch(/`adjudications` entry/);
  });
});
