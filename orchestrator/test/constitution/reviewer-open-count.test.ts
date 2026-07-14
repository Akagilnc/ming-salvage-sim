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

describe("ADR 0131 / #899 reviewer self-declared count", () => {
  it("uses typed receipt findingsCount even when structured rows differ", () => {
    const outcome = cmrOutcomeFromResult({
      output: {
        ...base,
        findingsCount: 3,
        findings: [finding, { ...finding, claim_quote: "gap 2" }],
      },
      // Stdout sentinel must not override the schema-validated count (#899).
      stdout: "findings = 99\n",
    });
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 3 });
  });

  it("trusts declaration zero even when the structured array is non-empty", () => {
    const outcome = cmrOutcomeFromResult({
      output: {
        ...base,
        findingsCount: 0,
        findings: [finding],
      },
    });
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 0 });
  });

  it("keeps the count unknown when findingsCount is absent from cargo", () => {
    const outcome = cmrOutcomeFromResult({
      outcomePath: sidecar({ ...base, findings: [finding, { ...finding, claim_quote: "gap 2" }] }),
    });
    expect(outcome).toMatchObject({ kind: "verdict" });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("never fabricates zero when findingsCount and structured rows are absent", () => {
    const outcome = cmrOutcomeFromResult({
      outcomePath: sidecar(base),
    });
    expect(outcome).toMatchObject({ kind: "verdict", converged: false });
    expect(outcome).not.toHaveProperty("findingsCount");
  });

  it("does not synthesize count from stdout sentinel when cargo has no findingsCount", () => {
    const outcome = cmrOutcomeFromResult({
      stdout: "findings = 2\n",
      outcomePath: sidecar({ chatty: "cargo without verdict fields" }),
    });
    expect(outcome).toMatchObject({ kind: "verdict" });
    expect(outcome).not.toHaveProperty("findingsCount");
    expect(outcome).not.toHaveProperty("converged");
  });

  it("prefers typed receipt over stdout decision bells", () => {
    const outcome = cmrOutcomeFromResult({
      output: {
        ...base,
        findingsCount: 0,
        converged: true,
      },
      stdout: '<cmr>{"junk": 1, "escalate": {"reason": "owner choice", "diagnosis": "CMR fork"}}</cmr>',
    });
    expect(outcome).toMatchObject({ kind: "verdict", findingsCount: 0, converged: true });
  });

  it("rings a well-formed decision bell from typed receipt", () => {
    const outcome = cmrOutcomeFromResult({
      output: {
        escalate: { reason: "owner choice", diagnosis: "CMR fork" },
      },
    });
    expect(outcome).toMatchObject({
      kind: "escalate",
      reason: "owner choice",
      diagnosis: "CMR fork",
    });
  });

  it("does not admit a malformed decision bell into the human loop", () => {
    // #899: present-but-malformed escalate fails the Action for #598 rather
    // than inventing a park or silently degrading to a zero open-count.
    expect(() =>
      cmrOutcomeFromResult({
        output: {
          ...base,
          findingsCount: 0,
          escalate: {},
        },
      }),
    ).toThrow(/malformed decision gate/);
  });

});
