import { describe, expect, it } from "vitest";
import { classifyDecisionGate } from "../../src/receiptRecovery.js";
import { route } from "../../src/route.js";
import { probeWorkerDecisionBell } from "../../src/workerReceipt.js";

describe("ADR 0131 zero-judgment runner constitution", () => {
  it("routes any present escalation ticket, including empty strings, to decision", () => {
    // Route table: once a typed seat already admitted escalate onto StepOutput,
    // presence alone is the stop edge (cargo quality is not re-judged here).
    expect(route({ from: "S2", output: {
      kind: "coder", committed: true, commitsAdded: 1,
      escalate: { reason: "", diagnosis: "" },
    } })).toEqual({ kind: "handoff", status: "escalate" });
  });

  it("fails closed on present-but-malformed decision bells (unified #899 court)", () => {
    // Production probe + classify share one contract: empty escalate is not a bell.
    expect(() => probeWorkerDecisionBell({ escalate: {} })).toThrow(
      /malformed decision gate/,
    );
    expect(() =>
      probeWorkerDecisionBell({ escalate: { reason: "", diagnosis: "" } }),
    ).toThrow(/malformed decision gate/);
    expect(() => classifyDecisionGate({ escalate: {} }, "constitution")).toThrow(
      /malformed decision gate/,
    );
    expect(
      probeWorkerDecisionBell({
        escalate: { reason: "owner choice", diagnosis: "contract fork" },
      }),
    ).toEqual({ reason: "owner choice", diagnosis: "contract fork" });
    expect(probeWorkerDecisionBell({ findingsCount: 0 })).toBeUndefined();
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
    // Count is authenticated at the typed boundary: missing findingsCount never
    // becomes kind:"reviewer". If a non-reviewer envelope somehow reaches S4,
    // topology still sends it to the fixer path (never derive open-count from
    // findings.length). Decode maps unusable open-count to a non-reviewer
    // opaque-miss envelope (not findingsCount:0, not #598 shape throw).
    expect(route({
      from: "S4",
      output: { kind: "fixer", committed: false },
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
