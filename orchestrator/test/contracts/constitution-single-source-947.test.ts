/**
 * #947 — four-reason adjudication law is single-sourced in the container-global
 * home CLAUDE.md (#911 dual-mount: same body reaches Claude workers at
 * ~/.claude/CLAUDE.md and codex workers as AGENTS.md). Souls carry a one-line
 * constitution pointer and their role-specific application ONLY — no second
 * full copy of the definitions anywhere in worker-facing law.
 *
 * The anchor phrases below are the same ones the host-side check-rule-sync.sh
 * greps across ~/.claude/CLAUDE.md, ~/.codex/AGENTS.md and this file; keep the
 * two lists in sync when amending the law.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const imageDir = join(here, "..", "..", "image");
const homeClaudeMd = readFileSync(join(imageDir, "home", "CLAUDE.md"), "utf8");
const verifySoul = readFileSync(join(imageDir, "souls", "verify.md"), "utf8");
const fixerSoul = readFileSync(join(imageDir, "souls", "fixer.md"), "utf8");
const receiptContracts = readFileSync(
  join(here, "..", "..", "src", "stationReceiptContracts.ts"),
  "utf8",
);

/** Sync anchors: full four-reason law lives in the container-global file. */
const LAW_ANCHORS = [
  "违宪",
  "过度防御",
  "事实不成立",
  "越权加戏",
  "scope_creep",
  "出事概率多大？后果多重？下游有没有兜底",
  "驳修法，不改宪法",
  "bug 早于 fixed point、位于邻接文件或偶然被发现",
  "难修不是驳回理由",
] as const;

/** Definition-body sentences that must never grow a second copy in souls. */
const DEFINITION_ONLY = [
  "出事概率多大？后果多重？下游有没有兜底",
  "bug 早于 fixed point、位于邻接文件或偶然被发现",
  "驳修法，不改宪法",
] as const;

describe("#947 container-global home CLAUDE.md is the single source of the four-reason law", () => {
  it("carries every sync anchor of the law", () => {
    for (const anchor of LAW_ANCHORS) {
      expect(homeClaudeMd).toContain(anchor);
    }
  });

  it("lists all four tokens next to their Chinese names", () => {
    for (const token of [
      "unconstitutional",
      "over_defense",
      "not_established",
      "scope_creep",
    ]) {
      expect(homeClaudeMd).toContain(token);
    }
  });
});

describe("#947 souls point at the law instead of copying it", () => {
  it("verify.md and fixer.md reference the容器全局 law by name", () => {
    expect(verifySoul).toMatch(/finding 裁决法理/);
    expect(fixerSoul).toMatch(/finding 裁决法理/);
  });

  it("no definition body survives in any soul (single source, rule 19)", () => {
    for (const sentence of DEFINITION_ONLY) {
      expect(verifySoul).not.toContain(sentence);
      expect(fixerSoul).not.toContain(sentence);
    }
  });

  it("verify.md keeps the four verdict tokens (kill-table enum stays legible)", () => {
    for (const token of [
      "unconstitutional",
      "over_defense",
      "not_established",
      "scope_creep",
    ]) {
      expect(verifySoul).toContain(token);
    }
  });

  it("verify.md drops the reviewer-facing disclaimers from §修复面审计", () => {
    expect(verifySoul).not.toMatch(/DOC-MODE|round-10|double-clear|standing-degraded/);
    // The operative half of that clause survives.
    expect(verifySoul).toContain("one-pass CMR 只出本次判词");
  });

  it("stationReceiptContracts.ts comment defers to the law instead of restating the carve-out", () => {
    expect(receiptContracts).not.toContain("bug 早于 fixed point");
    expect(receiptContracts).toMatch(/finding 裁决法理/);
    // Enum values themselves are untouched.
    for (const token of [
      "unconstitutional",
      "over_defense",
      "not_established",
      "scope_creep",
    ]) {
      expect(receiptContracts).toContain(`"${token}"`);
    }
  });
});
