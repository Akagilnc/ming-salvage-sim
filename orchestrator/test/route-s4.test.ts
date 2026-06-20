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
import type { Finding, ReviewerOutput } from "../src/types.js";

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
