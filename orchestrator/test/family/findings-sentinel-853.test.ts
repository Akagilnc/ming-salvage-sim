import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  cmrOutcomeFromResult,
} from "../../src/family/realFamilyBackend.js";

const VERDICT = {
  converged: true,
  successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
  claimedFixedFindingIdentityKeys: [],
  priorFindingDispositions: [],
  evidencePaths: ["cmr/review-summary.json"],
};

function outcomePath(): string {
  const dir = mkdtempSync(join(tmpdir(), "findings-sentinel-"));
  const path = join(dir, "outcome.json");
  writeFileSync(path, `${JSON.stringify(VERDICT)}\n`, "utf8");
  return path;
}

describe("#853 reviewer findings sentinel", () => {
  it("rejects an otherwise valid reviewer verdict when the canonical fragment is missing", () => {
    const result = cmrOutcomeFromResult({
      stdout: "CMR_STEP_COMPLETE\n",
      outcomePath: outcomePath(),
      cmrReviewLegs: [{ slug: "opus" }, { slug: "gpt-5.6-sol" }, { slug: "agy" }],
    });

    expect(result).toMatchObject({
      kind: "malformed",
      reason: expect.stringContaining("findings = x"),
      priorVerdict: expect.objectContaining({ kind: "verdict", converged: true }),
    });
  });

  it("uses the canonical fragment as the counting channel", () => {
    const result = cmrOutcomeFromResult({
      stdout: "findings = 0\nCMR_STEP_COMPLETE\n",
      outcomePath: outcomePath(),
      cmrReviewLegs: [{ slug: "opus" }, { slug: "gpt-5.6-sol" }, { slug: "agy" }],
    });

    expect(result).toMatchObject({ kind: "verdict", findingsCount: 0 });
  });

  it("#875: non-zero findings count without structured findings still yields a verdict (routing is verifyCmr)", () => {
    // Sidecar has no findings array; stdout says findings = 1. Parse attaches
    // findingsCount; rewrite cannot invent findings JSON. runVerifyCmr terminals
    // the completed envelope as outcome-protocol failure (separate test).
    const result = cmrOutcomeFromResult({
      stdout: "findings = 1\nCMR_STEP_COMPLETE\n",
      outcomePath: outcomePath(),
      cmrReviewLegs: [{ slug: "opus" }, { slug: "gpt-5.6-sol" }, { slug: "agy" }],
    });

    expect(result).toMatchObject({
      kind: "verdict",
      findingsCount: 1,
    });
    if (result.kind === "verdict") {
      expect(result.findings).toBeUndefined();
    }
  });
});
