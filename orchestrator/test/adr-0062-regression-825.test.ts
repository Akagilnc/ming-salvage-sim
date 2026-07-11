/**
 * #825 — closing regression sweep for ADR 0062 / #820.
 *
 * Completion sentinels are useful observability stamps, but an otherwise
 * completed worker must never be told they are a routing requirement. The
 * runtime's exit / durable facts remain the control plane; these strings are
 * deliberately checked at the authored contract boundary so a future prompt
 * edit cannot restore a lie-detector gate by instruction alone.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const CONTRACT_FILES = [
  "prompts/coder_implement.md",
  "prompts/coder_fix.md",
  "prompts/reviewer_review.md",
  "prompts/merger_resolve_conflict.md",
  "prompts/ship.md",
  "prompts/family_ship.md",
  "prompts/fixer.md",
  "prompts/verify.md",
  "prompts/docRelease.md",
  "prompts/integrated_cmr.md",
  "prompts/integrated_cmr_completeness.md",
  "prompts/integrated_cmr_correctness.md",
  "image/souls/output_protocol.md",
  "image/souls/fixer.md",
  "image/souls/verify.md",
  "image/souls/docRelease.md",
] as const;

describe("#825 ADR 0062 completion-sentinel contract sweep", () => {
  it.each(CONTRACT_FILES)("treats completion sentinels as optional telemetry in %s", (file) => {
    const body = readFileSync(resolve(process.cwd(), file), "utf8");

    expect(body).not.toMatch(/(?:always\s+)?(?:print|emit|fire)\s+[`\w]*_STEP_COMPLETE[^\n]*(?:must|only|required|at the very end)/i);
    expect(body).not.toMatch(/(?:must|required to)\s+(?:emit|print|fire)[^\n]*_STEP_COMPLETE/i);
  });
});
