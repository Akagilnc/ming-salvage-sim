import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { cmrOutcomeFromResult } from "../../src/family/realFamilyBackend.js";

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

  it("keeps the count unknown when the sentinel is absent", () => {
    const outcome = cmrOutcomeFromResult({
      stdout: "review complete\n",
      outcomePath: sidecar({ ...base, findings: [finding, { ...finding, claim_quote: "gap 2" }] }),
    });
    expect(outcome).toMatchObject({ kind: "verdict" });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("never fabricates zero when both the sentinel and structured rows are absent", () => {
    const outcome = cmrOutcomeFromResult({
      stdout: "review complete\n",
      outcomePath: sidecar(base),
    });
    expect(outcome).toMatchObject({ kind: "verdict", converged: false });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("does not synthesize converged from a declared count when cargo parsing fails", () => {
    const outcome = cmrOutcomeFromResult({
      stdout: "findings = 2\n",
      outcomePath: sidecar({ chatty: "cargo without verdict fields" }),
    });
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 2 });
    expect(outcome).not.toHaveProperty("converged");
  });

  it("rings a CMR stdout decision bell before parseable sidecar cargo", () => {
    const outcomePath = join(mkdtempSync(join(tmpdir(), "s1b-bell-")), "outcome.json");
    writeFileSync(outcomePath, JSON.stringify({ unrelatedCargo: true }));
    const outcome = cmrOutcomeFromResult({
      stdout: '<cmr>{"junk": 1, "escalate": {"reason": "owner choice", "diagnosis": "CMR fork"}}</cmr>',
      outcomePath,
    });
    expect(outcome).toMatchObject({
      kind: "escalate",
      reason: "owner choice",
      diagnosis: "CMR fork",
    });
  });

});
