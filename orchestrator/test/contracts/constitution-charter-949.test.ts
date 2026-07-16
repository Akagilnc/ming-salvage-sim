/**
 * #949 — the constitution gets a concrete identity for workers ("宪法实名制").
 *
 * Observed failure mode: judges and fixers forget that the constitution IS the
 * ADR set + the issue text + the CONTEXT glossary — they rule from vibes, and
 * sometimes even edit the constitution files to dissolve a finding. The charter
 * makes the law concrete: what the constitution is, the duty to enumerate the
 * authority set before ruling, constitution files as read-only inputs, and the
 * AC↔ADR conflict escalation.
 *
 * Owner rulings pinned here (2026-07-16):
 * - a fix diff touching constitution files gets REAL adjudication — an
 *   auto-unconstitutional mechanical rule was explicitly rejected;
 * - such rulings are loudly ledgered with a fixed marker for later statistics.
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

describe("#949 container-global charter defines the constitution concretely", () => {
  it("names the three-piece constitution", () => {
    expect(homeClaudeMd).toContain("本单 issue 原文 + AC");
    expect(homeClaudeMd).toContain("已 Accepted");
    expect(homeClaudeMd).toContain("CONTEXT.md 词表");
  });

  it("imposes the authority-set enumeration duty with clause anchors", () => {
    expect(homeClaudeMd).toContain("authority set");
    expect(homeClaudeMd).toContain("clause 锚点");
  });

  it("declares constitution files read-only with the single AC-authorized exception", () => {
    expect(homeClaudeMd).toContain("宪法只读");
    expect(homeClaudeMd).toContain("票面 AC");
    expect(homeClaudeMd).toContain("修宪权在 owner");
  });

  it("escalates AC↔ADR conflicts instead of picking a side", () => {
    expect(homeClaudeMd).toContain("AC 与 ADR 相抵");
    expect(homeClaudeMd).toMatch(/相抵[^。]*escalate/);
  });
});

describe("#949 judge handles constitution-touching fixes with judgment, not a tripwire", () => {
  it("verify.md opens court by enumerating the authority set", () => {
    expect(verifySoul).toContain("authority set");
    expect(verifySoul).toContain("clause 锚点");
  });

  it("verify.md adjudicates touched-constitution diffs and ledgers them loudly", () => {
    expect(verifySoul).toContain("[touched-constitution]");
    expect(verifySoul).toContain("docs/adr/");
    expect(verifySoul).toMatch(/实质审理/);
    expect(verifySoul).toMatch(/escalate/);
  });

  it("no mechanical auto-kill for touched-constitution diffs (owner rejected it)", () => {
    expect(verifySoul).not.toMatch(/自动\s*`?unconstitutional/);
    expect(verifySoul).not.toMatch(/无需(实质)?审理/);
  });
});

describe("#949 fixer opens its round by enumerating the authority set", () => {
  it("fixer.md carries the enumeration duty", () => {
    expect(fixerSoul).toContain("authority set");
  });
});
