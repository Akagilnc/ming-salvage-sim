import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { route } from "../src/route.js";

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

function familyEscalationObjectLiterals(source: string): readonly string[] {
  const results: string[] = [];
  const callPattern = /escalateFamily(?:\?\.)?\(\s*\{/g;
  for (const match of source.matchAll(callPattern)) {
    const start = match.index + match[0].lastIndexOf("{");
    let depth = 0;
    for (let index = start; index < source.length; index += 1) {
      if (source[index] === "{") depth += 1;
      if (source[index] === "}") depth -= 1;
      if (depth === 0) {
        results.push(source.slice(start + 1, index));
        break;
      }
    }
  }
  return results;
}

describe("ADR 0131 zero-judgment runner constitution", () => {
  it("routes any present escalation ticket, including empty strings, to decision", () => {
    expect(route({ from: "S2", output: {
      kind: "coder", committed: true, commitsAdded: 1,
      escalate: { reason: "", diagnosis: "", escalationKind: "decision" },
    } })).toEqual({ kind: "handoff", status: "escalate" });
  });

  it("routes S4 solely by reviewer-declared findings count", () => {
    const opaque = { severity: "nonsense", action: "ignore", title: "opaque" } as any;
    expect(route({ from: "S4", output: { kind: "reviewer", findings: [opaque] } }))
      .toEqual({ kind: "next", step: "S5" });
    expect(route({ from: "S4", output: { kind: "reviewer", findings: [] } }))
      .toEqual({ kind: "next", step: "S7" });
  });

  it("routes every completed coder report directly to the next reviewer", () => {
    expect(route({ from: "S2", output: {
      kind: "coder", committed: false, commitsAdded: 0,
    } })).toEqual({ kind: "next", step: "S3" });
    expect(route({ from: "S5", output: {
      kind: "coder", committed: false, commitsAdded: 0,
    } })).toEqual({ kind: "next", step: "S6" });
  });

  it("kind mismatch never decides redispatch or error fate", () => {
    const wrong = { kind: "coder", committed: false, commitsAdded: 0 } as const;
    expect(route({ from: "S3", output: wrong })).toEqual({ kind: "next", step: "S4" });
    expect(route({ from: "S6", output: wrong })).toEqual({ kind: "next", step: "S4" });
    expect(route({ from: "S4", output: wrong })).toEqual({ kind: "next", step: "S5" });
    expect(route({ from: "S9", output: wrong })).toEqual({ kind: "next", step: "S10" });
    expect(route({ from: "S10", output: wrong })).toEqual({ kind: "next", step: "S9" });
    expect(route({ from: "S11", output: wrong })).toEqual({
      kind: "handoff",
      status: "success",
    });
    expect(route({ from: "S12", output: wrong })).toEqual({ kind: "next", step: "S11" });
  });

  it("contains no coder git-verdict court in single-slice or family runtime", () => {
    const sources = [
      "src/runner.ts",
      "src/realBackend.ts",
      "src/family/realFamilyBackend.ts",
    ].map((file) => stripComments(
      readFileSync(new URL(`../${file}`, import.meta.url), "utf8"),
    ));
    const [runner, realBackend, familyBackend] = sources;

    expect(runner).not.toContain("coderNoCommitBudgetExhausted");
    expect(runner).not.toMatch(/rev-list[^\n]*coderHeadBeforeStep|coderHeadBeforeStep[^\n]*rev-list/);
    expect(realBackend).not.toContain("reconcileCoderCommits");
    expect(realBackend).not.toContain("freshCoderGitCommitCount");
    expect(realBackend).not.toContain("resumeCoderCommitCount");
    expect(familyBackend).not.toContain("familyCoderGitCommitCount");
  });

  it("runner and route cannot revive deleted output courts", () => {
    const source = ["runner.ts", "route.ts"]
      .map((file) => stripComments(readFileSync(new URL(`../src/${file}`, import.meta.url), "utf8")))
      .join("\n");
    for (const symbol of [
      "classifyFindings",
      "isValidStepOutput", "isValidCoderOutput", "isValidReviewerOutput",
      "isValidFinding", "isBlockingFinding", "isValidVerifyResult",
      "isValidFixerResult", "isValidCleanupResult", "isValidDocReleaseResult",
    ]) expect(source).not.toContain(symbol);
    expect(source).not.toContain("isReviewerStructuredOutputError");
    expect(stripComments(readFileSync(new URL("../src/route.ts", import.meta.url), "utf8")))
      .not.toContain("pendingBlockingFindings");
    expect(stripComments(readFileSync(new URL("../src/route.ts", import.meta.url), "utf8")))
      .not.toMatch(/ctx\.output\?\.kind\s*!==/);
    expect(source).not.toMatch(/\.severity\b/);
    expect(source).not.toMatch(/\.action\b/);
    expect(source).not.toMatch(
      /output\s*=\s*\{[^;]*findings\s*:\s*\[\s*\][^;]*\}/,
    );
  });

  it("runner decision parks are limited to worker-pressed gates", () => {
    const familyDir = new URL("../src/family/", import.meta.url);
    const files = [
      "src/runner.ts",
      "src/route.ts",
      ...readdirSync(familyDir, { recursive: true })
        .filter((file): file is string => typeof file === "string" && file.endsWith(".ts"))
        .map((file) => `src/family/${file}`),
    ];
    const decisionSites = new Map<string, number>();
    let escalateTerminationDecisionSites = 0;
    for (const file of files) {
      const source = stripComments(
        readFileSync(new URL(`../${file}`, import.meta.url), "utf8"),
      );
      const count = [...source.matchAll(/escalationKind\s*:\s*"decision"/g)].length;
      if (count > 0) decisionSites.set(file, count);
      escalateTerminationDecisionSites += [
        ...source.matchAll(/escalateTermination\s*\(\s*"decision"/g),
      ].length;
    }

    expect(Object.fromEntries(decisionSites)).toEqual({
      "src/runner.ts": 1,
      "src/family/runner.ts": 4,
      "src/family/ledger.ts": 1,
      "src/family/verifyCmr.ts": 4,
      "src/family/types.ts": 1,
      "src/family/realFamilyBackend.ts": 5,
    });
    expect([...decisionSites.values()].reduce((sum, count) => sum + count, 0)).toBe(16);
    expect(escalateTerminationDecisionSites).toBe(0);
  });

  it("requires every family escalation transport to declare its doorbell kind", () => {
    const familyDir = new URL("../src/family/", import.meta.url);
    const source = readdirSync(familyDir, { recursive: true })
      .filter((file): file is string => typeof file === "string" && file.endsWith(".ts"))
      .map((file) => stripComments(
        readFileSync(new URL(`../src/family/${file}`, import.meta.url), "utf8"),
      ))
      .join("\n");
    const calls = familyEscalationObjectLiterals(source);

    expect(calls.length).toBeGreaterThan(0);
    for (const call of calls) {
      expect(call).toMatch(/escalationKind\s*:/);
    }
    expect(source).not.toMatch(/escalationKind\s*:\s*[^,\n]*\?\?/);
  });

  it("family source cannot revive S1b count courts or rewrite ladders", () => {
    const source = ["verifyCmr.ts", "realFamilyBackend.ts"]
      .map((file) => readFileSync(new URL(`../src/family/${file}`, import.meta.url), "utf8"))
      .join("\n");
    for (const symbol of [
      "enforceFindingsSentinelWritePoint", "OUTCOME_REWRITE",
      "FINDINGS_SUPPLEMENT", "rewriteOutcomeProtocolFailure", "runCmrOutcomeRewrite",
      "captureOutcomeRewriteGitEvidence", "outcomeRewriteGitFailure",
      "cmrLegAccountingPayload", "cmrPriorOutput",
    ]) expect(source).not.toContain(symbol);
  });

  it("documents the reviewer declaration as the authoritative count channel", () => {
    const source = readFileSync(
      new URL("../src/family/verifyCmr.ts", import.meta.url),
      "utf8",
    );
    expect(source).toContain("reviewer declaration is authoritative");
    expect(source).toContain("Missing sentinel falls back to");
    expect(source).toContain("structured row count as the declaration");
    expect(source).toContain("Declaration accuracy belongs");
    expect(source).toContain("to coder-fix");
    expect(source).not.toContain("open-count is DERIVED (array length)");
  });
});
