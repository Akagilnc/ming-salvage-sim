/**
 * Tests for #250: S4 severity+action fan-out routing.
 *
 * route() at S4 must deterministically split reviewer findings into:
 *   → S5 coder_fix   when any P0/P1 (critical/high) OR any P2/P3 (medium/low/clarity)
 *                    with action:'fix_now' is present
 *   → S7 push        otherwise (empty findings OR all remaining findings are
 *                    action:'defer'), collecting defer-only P2/P3 into a
 *                    defer list that surfaces via the run result (not PR body)
 *
 * The route() function reads ONLY severity+action JSON — the agent never
 * decides the next step (ADR 0018 §1 / PRD #244 Implementation Decision).
 *
 * Regression: empty findings must still route to S7 push (slice #247 contract).
 */

import { describe, expect, it } from "vitest";
import { route } from "../src/route.js";
import type { CoderOutput, Finding, ReviewerOutput, StepOutput } from "../src/types.js";

// ─── helpers ─────────────────────────────────────────────────────────────────

function reviewerOutput(findings: Finding[]): ReviewerOutput {
  return { kind: "reviewer", findings };
}

function finding(
  severity: Finding["severity"],
  action: Finding["action"],
): Finding {
  return {
    severity,
    action,
    category: "test",
    claim_quote: "some quote",
    location: "src/foo.ts:1",
    suggested_fix: "fix it",
  };
}

// ─── regression: empty findings → S7 push ───────────────────────────────────

describe("S4 route_findings — empty findings (regression)", () => {
  it("empty findings → S7 push (slice #247 approve path still works)", () => {
    const decision = route({ from: "S4", output: reviewerOutput([]) });
    expect(decision).toEqual({ kind: "next", step: "S7" });
  });
});

// ─── P0/P1 → S5 ─────────────────────────────────────────────────────────────

describe("S4 route_findings — P0/P1 present", () => {
  it("single critical (P0) finding with fix_now → S5", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([finding("critical", "fix_now")]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  it("single high (P1) finding with fix_now → S5", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([finding("high", "fix_now")]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  it("P0 + defer P2/P3 mix → S5 (P0 trumps defer list)", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([
        finding("critical", "fix_now"),
        finding("medium", "defer"),
        finding("low", "defer"),
      ]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  it("P1 + defer P2/P3 mix → S5 (P1 trumps defer list)", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([
        finding("high", "fix_now"),
        finding("clarity", "defer"),
      ]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });
});

// ─── fix_now P2/P3 (no P0/P1) → S5 ─────────────────────────────────────────

describe("S4 route_findings — fix_now P2/P3 without P0/P1", () => {
  it("single medium fix_now → S5 (not direct push)", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([finding("medium", "fix_now")]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  it("single low fix_now → S5", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([finding("low", "fix_now")]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  it("single clarity fix_now → S5", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([finding("clarity", "fix_now")]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  it("mix of fix_now and defer P2/P3 (no P0/P1) → S5", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([
        finding("medium", "fix_now"),
        finding("low", "defer"),
      ]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });
});

// ─── defer-only P2/P3 → S7 push ──────────────────────────────────────────────

describe("S4 route_findings — defer-only P2/P3", () => {
  it("single medium defer → S7 push (defer does not block)", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([finding("medium", "defer")]),
    });
    expect(decision).toEqual({ kind: "next", step: "S7" });
  });

  it("single low defer → S7 push", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([finding("low", "defer")]),
    });
    expect(decision).toEqual({ kind: "next", step: "S7" });
  });

  it("multiple defer-only findings (medium+low+clarity) → S7 push", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([
        finding("medium", "defer"),
        finding("low", "defer"),
        finding("clarity", "defer"),
      ]),
    });
    expect(decision).toEqual({ kind: "next", step: "S7" });
  });
});

// ─── end-to-end: full route from S4 reads only JSON, not agent intent ────────

describe("S4 route_findings — determinism contract", () => {
  it("route() ignores escalate-free outputs and reads only severity+action", () => {
    // Same findings, same answer — purely structural, no randomness.
    const output = reviewerOutput([finding("medium", "fix_now")]);
    expect(route({ from: "S4", output })).toEqual({ kind: "next", step: "S5" });
    expect(route({ from: "S4", output })).toEqual({ kind: "next", step: "S5" });
  });
});

// ─── P0/P1 severity branch independently locked (#250 fix2) ──────────────────
//
// These cases have severity=critical/high but action='defer'. The action-based
// branch alone (|| action==='fix_now') would NOT send them to S5. Only the
// severity branch (severity==='critical' || severity==='high') catches them.
// This test locks that branch independently so it cannot be deleted silently.

describe("S4 route_findings — P0/P1 severity branch (action=defer, severity locks)", () => {
  it("critical (P0) + action:defer → S5 (severity branch, not action branch)", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([finding("critical", "defer")]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  it("high (P1) + action:defer → S5 (severity branch, not action branch)", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([finding("high", "defer")]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });

  it("critical+defer alongside medium+defer → S5 (P0 still trumps even when all deferred)", () => {
    const decision = route({
      from: "S4",
      output: reviewerOutput([
        finding("critical", "defer"),
        finding("medium", "defer"),
      ]),
    });
    expect(decision).toEqual({ kind: "next", step: "S5" });
  });
});

// ─── #5 route() defense-in-depth: malformed step output → handoff(error) ─────
//
// route() is the agent↔runner seam. Even though the runner now guards malformed
// output before route() is called, route() itself must NEVER silently coerce a
// non-conforming output into a success edge — that could bypass the P0/P1 fix
// gate (e.g. a non-reviewer output at S4 becoming empty findings → push).

function coderOutput(committed: boolean): CoderOutput {
  return { kind: "coder", committed, commitsAdded: committed ? 1 : 0 };
}

describe("S2 route — malformed output → handoff(error), never silent → S3", () => {
  it("S2 with a reviewer output (wrong kind) → handoff(error)", () => {
    const decision = route({
      from: "S2",
      output: reviewerOutput([]) as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S2 with undefined output → handoff(error)", () => {
    const decision = route({ from: "S2", output: undefined });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S2 with garbage output (no kind) → handoff(error)", () => {
    const decision = route({
      from: "S2",
      output: { foo: "bar" } as unknown as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S2 with a well-formed committed coder output → S3 (regression)", () => {
    const decision = route({ from: "S2", output: coderOutput(true) });
    expect(decision).toEqual({ kind: "next", step: "S3" });
  });
});

describe("S5 route — malformed coder output → handoff(error), never silent → S6", () => {
  // route() is the resume path's ONLY guard on the recorded S5 output
  // (planResume → route({from:'S5', output: ledgerOutput}) bypasses the runner's
  // isValidStepOutput). So the S5 case must be symmetric with S2: a malformed
  // coder output is a contract violation → handoff(error), NEVER a silent
  // fall-through to S6 (which would re-review / push UNVALIDATED code).

  it("S5 with undefined output → handoff(error)", () => {
    const decision = route({ from: "S5", output: undefined });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S5 with a reviewer output (wrong kind) → handoff(error)", () => {
    const decision = route({
      from: "S5",
      output: reviewerOutput([]) as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S5 with garbage output (no kind) → handoff(error)", () => {
    const decision = route({
      from: "S5",
      output: { foo: "bar" } as unknown as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S5 with inconsistent commitsAdded (committed:true, commitsAdded:0) → handoff(error)", () => {
    // The exact bug from the contract: committed:true but 0 commits is a garbage
    // coder output. The old S5 guard (kind==='coder' && !committed) saw
    // committed===true → fell through to S6. It must be rejected as invalid.
    const decision = route({
      from: "S5",
      output: {
        kind: "coder",
        committed: true,
        commitsAdded: 0,
      } as unknown as StepOutput,
    });
    // Crucially NOT { kind: "next", step: "S6" } — that re-reviews unvalidated code.
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S5 with a well-formed 0-commit coder output → handoff(error) (no progress, mirrors S2)", () => {
    const decision = route({ from: "S5", output: coderOutput(false) });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S5 with a well-formed committed coder output → S6 (regression)", () => {
    const decision = route({ from: "S5", output: coderOutput(true) });
    expect(decision).toEqual({ kind: "next", step: "S6" });
  });
});

describe("S4 route — non-reviewer output → handoff(error), NEVER coerced to empty findings + push", () => {
  it("S4 with a coder output (wrong kind) → handoff(error), not push", () => {
    const decision = route({
      from: "S4",
      output: coderOutput(true) as StepOutput,
    });
    // Crucially NOT { kind: "next", step: "S7" } — that would ship unreviewed.
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S4 with undefined output → handoff(error)", () => {
    const decision = route({ from: "S4", output: undefined });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });

  it("S4 with garbage output (no kind) → handoff(error)", () => {
    const decision = route({
      from: "S4",
      output: { findings: "nope" } as unknown as StepOutput,
    });
    expect(decision).toEqual({ kind: "handoff", status: "error" });
  });
});
