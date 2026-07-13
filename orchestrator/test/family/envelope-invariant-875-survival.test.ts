import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { cmrOutcomeFromResult } from "../../src/family/realFamilyBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const finding = {
  severity: "high", category: "correctness", claim_quote: "gap",
  location: "src/x.ts:1", suggested_fix: "fix", action: "fix_now",
} as const;
const base = {
  converged: false, reason: "declared open", successfulLegs: ["opus", "gpt-5.6-sol"],
  claimedFixedFindingIdentityKeys: [], priorFindingDispositions: [], evidencePaths: ["review.json"],
};

function sidecar(payload: unknown): string {
  const path = join(mkdtempSync(join(tmpdir(), "s1b-")), "outcome.json");
  writeFileSync(path, JSON.stringify(payload));
  return path;
}

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

describe("ADR 0131 S1b reviewer self-declared count", () => {
  it("passes sentinel declaration through even when structured rows differ", () => {
    const outcome = cmrOutcomeFromResult({
      stdout: "findings = 3\n",
      outcomePath: sidecar({ ...base, findings: [finding, { ...finding, claim_quote: "gap 2" }] }),
    });
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 3 });
  });

  it("trusts declaration zero even when the structured array is non-empty", () => {
    const outcome = cmrOutcomeFromResult({
      stdout: "findings = 0\n",
      outcomePath: sidecar({
        ...base,
        converged: false,
        findings: [finding],
      }),
    });
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 0 });
  });

  it("falls back to structured row count only when the sentinel is absent", () => {
    const outcome = cmrOutcomeFromResult({
      stdout: "review complete\n",
      outcomePath: sidecar({ ...base, findings: [finding, { ...finding, claim_quote: "gap 2" }] }),
    });
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 2 });
  });

  it("keeps count courts and rewrite ladders absent from executable family source", () => {
    const source = ["verifyCmr.ts", "realFamilyBackend.ts"]
      .map((file) => stripComments(readFileSync(join(here, `../../src/family/${file}`), "utf8")))
      .join("\n");
    for (const symbol of [
      "enforceFindingsSentinelWritePoint", "OUTCOME_REWRITE", "FINDINGS_SUPPLEMENT",
      "rewriteOutcomeProtocolFailure", "runCmrOutcomeRewrite",
    ]) expect(source).not.toContain(symbol);
    expect(source).toContain("output.findingsCount");
  });
});
