/**
 * commander cycle detection — #294 acceptance 3 (ADR 0022 decision 3①).
 *
 * The commander schedules waves over the `blocked_by` DAG. If `to-issues` (or a
 * human editing dependencies) produces a CYCLE among the children (A blocked_by
 * B, B blocked_by A), no wave can ever unblock all children — a naive predicate
 * just returns an empty wave forever and the run silently stalls / records the
 * cycle members as "skipped". That is a DEADLOCK, not an honest result.
 *
 * #294 adds `assertAcyclic`: BEFORE scheduling, validate the intra-family
 * `blocked_by` graph is acyclic. A cycle → THROW a fail-closed escalation (the
 * spine surfaces it to the human, decision 4) — never a silent empty-wave
 * deadlock. This is the commander's OWN seam (extends the #293 selector module),
 * tested as a pure function over the children + their edges.
 */

import { describe, expect, it } from "vitest";
import { assertAcyclic, selectWave } from "../../src/family/commander.js";
import type { ChildSlice } from "../../src/family/types.js";

/** Build a child slice descriptor. */
function child(issue: number, blockedBy: number[] = []): ChildSlice {
  return { issue, blockedBy };
}

describe("commander.assertAcyclic (#294 acceptance 3 — fail-closed on cycle)", () => {
  it("accepts an acyclic chain (no throw)", () => {
    // 10 → 11 → 12 (a linear dependency chain): acyclic.
    const children = [child(10), child(11, [10]), child(12, [11])];
    expect(() => assertAcyclic(children)).not.toThrow();
  });

  it("accepts a diamond (acyclic, multiple parents)", () => {
    // 12 blocked_by 10 AND 11; both blocked_by nothing: acyclic.
    const children = [child(10), child(11), child(12, [10, 11])];
    expect(() => assertAcyclic(children)).not.toThrow();
  });

  it("accepts independent children (empty graph, no throw)", () => {
    const children = [child(10), child(11), child(12)];
    expect(() => assertAcyclic(children)).not.toThrow();
  });

  it("THROWS on a direct 2-node cycle (A↔B)", () => {
    // 10 blocked_by 11, 11 blocked_by 10 — neither can ever schedule.
    const children = [child(10, [11]), child(11, [10])];
    expect(() => assertAcyclic(children)).toThrow(/cycle/i);
  });

  it("THROWS on a self-loop (A blocked_by A)", () => {
    const children = [child(10, [10])];
    expect(() => assertAcyclic(children)).toThrow(/cycle/i);
  });

  it("THROWS on a 3-node cycle (A→B→C→A)", () => {
    const children = [child(10, [12]), child(11, [10]), child(12, [11])];
    expect(() => assertAcyclic(children)).toThrow(/cycle/i);
  });

  it("THROWS naming the issues on the cycle (fail-closed message is actionable)", () => {
    const children = [child(10, [11]), child(11, [10])];
    // The escalation message must name the involved issues so the human can fix
    // the dependency edges (decision 4: cycle → escalate to a human).
    expect(() => assertAcyclic(children)).toThrow(/(?=.*#?10)(?=.*#?11)/);
  });

  it("THROWS on a cycle even when an INDEPENDENT acyclic child exists too", () => {
    // 99 is independent and schedulable; 10↔11 form a cycle. The whole run must
    // fail-closed (a partial-but-deadlocked epic is not silently shippable).
    const children = [child(99), child(10, [11]), child(11, [10])];
    expect(() => assertAcyclic(children)).toThrow(/cycle/i);
  });

  it("IGNORES edges to issues OUTSIDE the children set (external blockers are not intra-family cycles)", () => {
    // 10 is blocked_by 500, which is NOT one of the children. An external blocker
    // cannot form a cycle WITH the children — so this is acyclic. (Whether 500 is
    // satisfied is the ledger-merged unblock concern, not cycle detection.)
    const children = [child(10, [500]), child(11)];
    expect(() => assertAcyclic(children)).not.toThrow();
  });

  it("selectWave still works on an acyclic graph after the cycle guard (no behavioural regression)", () => {
    const children = [child(10), child(11, [10])];
    expect(() => assertAcyclic(children)).not.toThrow();
    expect(selectWave(children, new Set()).map((c) => c.issue)).toEqual([10]);
    expect(selectWave(children, new Set([10])).map((c) => c.issue)).toEqual([11]);
  });
});
