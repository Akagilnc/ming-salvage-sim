import { describe, expect, it } from "vitest";

import {
  CODER_CODEX_SLUG,
  VERIFY_CODEX_SLUG,
  effortForLiveOfficer,
} from "../../src/modelRegistry.js";

/**
 * Drift guard: single-slice (`realBackend`) and family (`realFamilyBackend`)
 * both call this shared helper. Verify/CMR live officers on the verify Codex
 * slug must keep `"xhigh"`; unrelated contexts must stay undefined.
 */
describe("effortForLiveOfficer — shared verify/CMR xhigh policy", () => {
  it("returns xhigh for VERIFY_CODEX_SLUG + verify role (both backends)", () => {
    expect(effortForLiveOfficer(VERIFY_CODEX_SLUG, { role: "verify" })).toBe(
      "xhigh",
    );
  });

  it("returns xhigh for VERIFY_CODEX_SLUG + cmr soul (both backends)", () => {
    expect(effortForLiveOfficer(VERIFY_CODEX_SLUG, { soul: "cmr" })).toBe(
      "xhigh",
    );
  });

  it("returns xhigh for VERIFY_CODEX_SLUG + verify/cmr smoke keys (single-slice)", () => {
    expect(
      effortForLiveOfficer(VERIFY_CODEX_SLUG, { smokeKey: "verify" }),
    ).toBe("xhigh");
    expect(
      effortForLiveOfficer(VERIFY_CODEX_SLUG, { smokeKey: "cmrCompleteness" }),
    ).toBe("xhigh");
  });

  it("returns undefined for non-verify slug even with verify/cmr context", () => {
    expect(
      effortForLiveOfficer(CODER_CODEX_SLUG, { role: "verify", soul: "cmr" }),
    ).toBeUndefined();
  });

  it("returns undefined for VERIFY_CODEX_SLUG without verify/cmr context", () => {
    expect(
      effortForLiveOfficer(VERIFY_CODEX_SLUG, { role: "coder", soul: "coder" }),
    ).toBeUndefined();
    expect(effortForLiveOfficer(VERIFY_CODEX_SLUG, {})).toBeUndefined();
  });
});
