import { describe, expect, it } from "vitest";
import { route } from "../../src/route.js";
import { probeWorkerDecisionBell } from "../../src/workerReceipt.js";

describe("ADR 0131 zero-judgment runner constitution", () => {
  it("routes any present escalation ticket, including empty strings, to decision", () => {
    expect(route({ from: "S2", output: {
      kind: "coder", committed: true, commitsAdded: 1,
      escalate: { reason: "", diagnosis: "" },
    } })).toEqual({ kind: "handoff", status: "escalate" });
  });

  it("treats the escalate block itself as the decision bell", () => {
    expect(probeWorkerDecisionBell({ escalate: {} })).toEqual({
      reason: "",
      diagnosis: "",
    });
    expect(
      probeWorkerDecisionBell({ escalate: { reason: "", diagnosis: "" } }),
    ).toEqual({ reason: "", diagnosis: "" });
  });

  it("routes S4 solely by reviewer-declared findingsCount (never findings.length)", () => {
    const opaque = { severity: "nonsense", action: "ignore", title: "opaque" } as any;
    // Self-reported open-count owns the edge; cargo rows cannot invent 0-vs-positive.
    expect(route({
      from: "S4",
      output: { kind: "reviewer", findings: [opaque], findingsCount: 1 },
    })).toEqual({ kind: "next", step: "S5" });
    expect(route({
      from: "S4",
      output: { kind: "reviewer", findings: [], findingsCount: 0 },
    })).toEqual({ kind: "next", step: "S7" });
    // Missing findingsCount is unusable receipt → fixer, even when cargo rows exist
    // or are empty (never derive open-count from findings.length).
    expect(route({
      from: "S4",
      output: { kind: "reviewer", findings: [opaque] },
    })).toEqual({ kind: "next", step: "S5" });
    expect(route({
      from: "S4",
      output: { kind: "reviewer", findings: [] },
    })).toEqual({ kind: "next", step: "S5" });
  });

  it("routes every completed coder report directly to the next reviewer", () => {
    expect(route({ from: "S2", output: {
      kind: "coder", committed: false, commitsAdded: 0,
    } })).toEqual({ kind: "next", step: "S3" });
    expect(route({ from: "S5", output: {
      kind: "coder", committed: false, commitsAdded: 0,
    } })).toEqual({ kind: "next", step: "S6" });
  });

  it("child kind mismatch never decides redispatch or error fate", () => {
    const wrong = { kind: "coder", committed: false, commitsAdded: 0 } as const;
    expect(route({ from: "S3", output: wrong })).toEqual({ kind: "next", step: "S4" });
    expect(route({ from: "S6", output: wrong })).toEqual({ kind: "next", step: "S4" });
    expect(route({ from: "S4", output: wrong })).toEqual({ kind: "next", step: "S5" });
  });

});
