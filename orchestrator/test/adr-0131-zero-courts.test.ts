import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { route } from "../src/route.js";

function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
}

describe("ADR 0131 zero-judgment runner constitution", () => {
  it("routes any present escalation ticket, including empty strings, to decision", () => {
    expect(route({ from: "S2", output: {
      kind: "coder", committed: true, commitsAdded: 1,
      escalate: { reason: "", diagnosis: "" },
    } })).toEqual({ kind: "handoff", status: "escalate" });
  });

  it("routes S4 solely by reviewer-declared findings count", () => {
    const opaque = { severity: "nonsense", action: "ignore", title: "opaque" } as any;
    expect(route({ from: "S4", output: { kind: "reviewer", findings: [opaque] } }))
      .toEqual({ kind: "next", step: "S5" });
    expect(route({ from: "S4", output: { kind: "reviewer", findings: [] } }))
      .toEqual({ kind: "next", step: "S7" });
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
    expect(source).not.toMatch(/\.severity\b/);
    expect(source).not.toMatch(/\.action\b/);
    expect(source).not.toMatch(
      /output\s*=\s*\{[^;]*findings\s*:\s*\[\s*\][^;]*\}/,
    );
  });

  it("runner decision parks are limited to worker-pressed gates", () => {
    const source = stripComments(
      readFileSync(new URL("../src/runner.ts", import.meta.url), "utf8"),
    );
    // Four allowed escalateTermination call sites (three relay tags + one
    // escalated worker result), plus the helper default and auto-merge ledger tag.
    expect(source.match(/"decision",/g)).toHaveLength(6);
    expect(source.match(/worker raised a decision gate/g)).toHaveLength(6);
    expect(source).toContain("result.escalation");
    expect(source).not.toContain("交卷不可用，需人拍");
    expect(source).not.toContain("reviewer 未申报可数卷面");
  });
});
