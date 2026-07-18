/**
 * commander — deterministic wave scheduler (ADR 0022 decision 1, #293 seam 1).
 *
 * The commander reads the parent epic's ALREADY-CUT child slices (native
 * sub-issues + explicit blocked_by, the single source of truth —切片 happens
 * OUTSIDE the orchestrator) and selects the next WAVE: the children whose
 * blocked_by dependencies are all satisfied (merged into the family base).
 *
 * #293 ships the THINNEST commander: select the unblocked children given a set
 * of already-merged child issue numbers. The richer wave/unblock/cycle logic is
 * #294 — it must plug into THIS module without rewriting the family main loop,
 * so the selection is a pure, independently-testable function over the
 * children + the merged set.
 */

import { describe, expect, it } from "vitest";
import { selectWave } from "../../../src/family/commander.js";
import type { ChildSlice } from "../../../src/family/types.js";

/** Build a child slice descriptor. */
function child(issue: number, blockedBy: number[] = []): ChildSlice {
  return { issue, blockedBy };
}

describe("commander.selectWave (#293 seam 1)", () => {
  it("selects ALL children when none have blocked_by (one parallel wave)", () => {
    const children = [child(10), child(11), child(12)];
    const wave = selectWave(children, new Set());
    expect(wave.map((c) => c.issue)).toEqual([10, 11, 12]);
  });

  it("excludes children whose blocked_by is not yet merged", () => {
    // 11 is blocked by 10; with nothing merged, only 10 is unblocked.
    const children = [child(10), child(11, [10])];
    const wave = selectWave(children, new Set());
    expect(wave.map((c) => c.issue)).toEqual([10]);
  });

  it("includes a child once ALL its blocked_by are in the merged set", () => {
    // 12 is blocked by both 10 and 11.
    const children = [child(10), child(11), child(12, [10, 11])];
    // 10 merged but not 11 → 12 still blocked.
    expect(selectWave(children, new Set([10])).map((c) => c.issue)).toEqual([
      11,
    ]);
    // both merged → 12 unblocks.
    expect(selectWave(children, new Set([10, 11])).map((c) => c.issue)).toEqual(
      [12],
    );
  });

  it("does NOT re-select an already-merged child", () => {
    const children = [child(10), child(11)];
    const wave = selectWave(children, new Set([10]));
    expect(wave.map((c) => c.issue)).toEqual([11]);
  });

  it("returns an empty wave when every child is merged (loop terminates)", () => {
    const children = [child(10), child(11)];
    const wave = selectWave(children, new Set([10, 11]));
    expect(wave).toEqual([]);
  });

  it("preserves child input order in the selected wave (deterministic)", () => {
    const children = [child(30), child(10), child(20)];
    const wave = selectWave(children, new Set());
    expect(wave.map((c) => c.issue)).toEqual([30, 10, 20]);
  });

  it("ignores an EXTERNAL blocker (not a family child) — those are filtered at family admission, not the scheduler (#934 ID-002)", () => {
    // 999 is NOT a family child, so it can NEVER enter the family `merged` set. Family
    // admission (`filterExternalBlockedChildren`) visibly filters children still open
    // on ordinary external blockers; requiring 999 in `merged` here would strand 10
    // forever. selectWave must gate ONLY on intra-family blockers.
    const children = [child(10, [999])];
    expect(selectWave(children, new Set()).map((c) => c.issue)).toEqual([10]);
  });

  it("gates on the intra-family blocker while ignoring an external one in the same child", () => {
    const children = [child(10), child(11, [10, 999])];
    // 10 (family) not merged → 11 still blocked; external 999 is irrelevant here.
    expect(selectWave(children, new Set()).map((c) => c.issue)).toEqual([10]);
    // 10 merged → 11 unblocks (999 never required of the family scheduler).
    expect(selectWave(children, new Set([10])).map((c) => c.issue)).toEqual([11]);
  });
});
