/**
 * #880 (873·S6) — ADR 0130 submission-contract pointers in orchestrator role files.
 *
 * Codex on PR #872: the contract claims to cover per-slice review, but per-slice
 * legs deliberately do NOT invoke ak-cross-m-review (CLAUDE.md Skill routing).
 * Without pointers in orchestrator souls, per-slice reviewers never see the
 * 交卷契约 / 钉子令牌 / 钉上刻字 obligations.
 *
 * Skill package owns the rule body (owner session; out of this slice). This
 * slice only pins POINTER phrases in role files — short citations, not a second
 * copy of the skill text. Phrase pins mirror the skill's test_submission_contract
 * / test_nail_token spirit: positive presence + "pointer not restatement" guard.
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

const ADR_PATH = "docs/adr/0130-exhaustive-review-submission-contract";

describe("#880 ADR 0130 pointer — per-slice reviewer soul (PR #872 gap)", () => {
  const soul = norm(readSoul("reviewer.md"));

  it("cites ADR 0130 / the exhaustive-review submission contract path", () => {
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toContain(ADR_PATH);
  });

  it("names the 交卷契约 / Submission contract and requires reporting every finding", () => {
    expect(soul).toMatch(/Submission contract|交卷契约/);
    // Positive: delivery only after every seen finding is written down.
    expect(soul).toMatch(/every finding|all findings|every defect you (saw|see)/i);
    // Severity is a label, not an admission gate (wiki §额外硬规则 #8).
    expect(soul).toMatch(/severity is a (label|property)|not an? (admission )?threshold/i);
  });

  it("is a pointer, not a restated skill body", () => {
    // Must explicitly say the skill / ADR is the single source (pointer stance).
    expect(soul).toMatch(/pointer|single source|do not (restate|duplicate|re-copy|rewrite)/i);
    // Must not paste skill-only field names that belong to the cmr-fixer schema.
    expect(soul).not.toMatch(/`adjudications` entry/);
    expect(soul).not.toMatch(/`incidental_fixes`/);
  });
});

describe("#880 ADR 0130 pointer — integrated CMR completeness soul (钉子令牌 + 钉上刻字)", () => {
  const soul = norm(readSoul("cmr_completeness.md"));

  it("cites ADR 0130 and the submission contract", () => {
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toContain(ADR_PATH);
    expect(soul).toMatch(/Submission contract|交卷契约/);
  });

  it("points at 钉子令牌 and 钉上刻字 (wiki §额外硬规则 #9)", () => {
    expect(soul).toContain("钉子令牌");
    expect(soul).toContain("钉上刻字");
    // Completeness owns nail hand-off; point at the skill section, do not rewrite.
    expect(soul).toMatch(/ak-cmr-completeness|ak-cross-m-review/);
    expect(soul).toMatch(/pointer|single source|do not (restate|duplicate|re-copy|rewrite)/i);
  });
});

describe("#880 ADR 0130 pointer — integrated CMR correctness soul", () => {
  const soul = norm(readSoul("cmr_correctness.md"));

  it("cites ADR 0130 / submission contract as a pointer into the skill", () => {
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toContain(ADR_PATH);
    expect(soul).toMatch(/Submission contract|交卷契约/);
    expect(soul).toMatch(/pointer|single source|do not (restate|duplicate|re-copy|rewrite)/i);
  });
});

describe("#880 ADR 0130 pointer — fixer first-duty (online review fixer soul)", () => {
  const soul = norm(readSoul("fixer.md"));

  it("cites ADR 0130 and makes empirical adjudication the first duty", () => {
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toContain(ADR_PATH);
    expect(soul).toMatch(/first duty|first task|first job/i);
    expect(soul).toMatch(/empiric|against the (real|actual) (code|source)|verify.*(true|false|authenticity)/i);
    expect(soul).toMatch(/refut/i);
  });
});

describe("#880 ADR 0130 pointer — per-slice coder-fix (coder soul + coder_fix prompt)", () => {
  const soul = norm(readSoul("coder.md"));
  const prompt = norm(readPrompt("coder_fix.md"));

  it("coder soul cites ADR 0130 for the verify-then-fix / refute first duty", () => {
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toContain(ADR_PATH);
    expect(soul).toMatch(/refute the false ones|refuted/i);
    expect(soul).toMatch(/Check each supplied finding against the real code first/i);
  });

  it("coder_fix prompt stays thin while the soul carries the ADR 0130 method", () => {
    expect(prompt).not.toMatch(/ADR 0130|refut/i);
    expect(soul).toMatch(/ADR 0130/);
    expect(soul).toContain(ADR_PATH);
  });
});

describe("#880 ADR 0130 pointer — thin reviewer prompt defers to soul that carries the contract", () => {
  const prompt = readPrompt("reviewer_review.md");

  it("still routes method to the live-mounted reviewer soul (pointer lives there)", () => {
    expect(prompt).toMatch(
      /\/home\/agent\/\.orchestrator\/souls\/reviewer\.md/,
    );
    // Thin entrypoint may restate a one-liner pointer, but must not invent a
    // second full contract body. Prefer soul as the carrier.
    const n = norm(prompt);
    expect(n).not.toMatch(/`adjudications` entry/);
  });
});
