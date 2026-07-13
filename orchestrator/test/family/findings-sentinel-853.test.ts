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
  it("derives findingsCount from structured array; sentinel must match (write-point)", () => {
    // Opus/#875/ADR 0129: array is single source of truth; findings = N is a
    // write-point consistency check, not an independent counting channel.
    const result = cmrOutcomeFromResult({
      stdout: "findings = 0\nCMR_STEP_COMPLETE\n",
      outcomePath: outcomePath(),
      cmrReviewLegs: [{ slug: "opus" }, { slug: "gpt-5.6-sol" }, { slug: "agy" }],
    });

    expect(result).toMatchObject({ kind: "verdict", findingsCount: 0 });
  });

  });
