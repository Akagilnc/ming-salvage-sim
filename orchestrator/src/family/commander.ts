/**
 * commander — deterministic wave scheduler (ADR 0022 decision 1, #293 seam 1).
 *
 * The commander is a RUNNER step, NOT an LLM decomposer: the parent epic's child
 * slices are cut OUTSIDE the orchestrator (an external `to-issues` step) and fed
 * with explicit native `blocked_by` edges (the single source of truth). The
 * commander reads those现成 children + edges and selects the next WAVE — the
 * children whose every blocker is already merged into the family base.
 *
 * #293 ships the THINNEST selection: a pure function over the children + the set
 * of already-merged child issue numbers. #294 layers the richer wave / unblock /
 * cycle-detection logic ON this module (e.g. topological multi-wave ordering,
 * cycle fail-closed) — it extends THIS selector, it does NOT rewrite the family
 * main loop, which only ever CALLS selectWave / assertAcyclic. That is the seam
 * boundary.
 *
 * No LLM dependency inference (ADR 0022: we have explicit blocked_by, so the
 * native Plan's LLM selector is neither used nor needed). #294 adds the
 * fail-closed cycle guard (`assertAcyclic`) the family spine runs before
 * scheduling: the `selectWave` predicate alone turns a cyclic graph into an
 * empty wave forever (a SILENT deadlock — every cycle member stays blocked), so
 * the commander validates the intra-family `blocked_by` DAG is acyclic up front
 * and throws a human-actionable escalation otherwise (ADR 0022 decisions 3①/4).
 * #293's selectWave contract is unchanged: given children + a merged set, return
 * the unmerged children whose blocked_by ⊆ merged, in input order
 * (deterministic).
 */

import type { ChildSlice } from "./types.js";

/**
 * The error thrown when the intra-family `blocked_by` graph contains a cycle.
 *
 * A distinct class so the family spine (and the escalation path, ADR 0022
 * decision 4) can recognise a cycle fail-closure specifically — vs an ordinary
 * runtime fault — while the message stays human-actionable (it names the issues
 * on the cycle so the human can fix the `to-issues` dependency edges).
 */
export class DependencyCycleError extends Error {
  /** The issue numbers that lie on the detected cycle (for escalation triage). */
  readonly cycle: ReadonlyArray<number>;
  constructor(cycle: ReadonlyArray<number>) {
    const path = cycle.map((n) => `#${n}`).join(" → ");
    super(
      `blocked_by dependency cycle detected among family children: ${path}. ` +
        `No wave can ever schedule these slices (each waits on the other), so ` +
        `the family run fails closed rather than deadlocking. Fix the blocked_by ` +
        `edges (an external 'to-issues' / human concern) and re-run.`,
    );
    this.name = "DependencyCycleError";
    this.cycle = cycle;
  }
}

/**
 * Select the next wave of schedulable child slices.
 *
 * A child is in the wave iff:
 *   - it is NOT already merged (`!merged.has(child.issue)`), AND
 *   - every INTRA-FAMILY issue it is `blocked_by` is in the merged set
 *     (`c.blockedBy.every((b) => !family.has(b) || merged.has(b))`).
 *
 * online R1 #1 (Gemini + Codex, user 2026-06-22): the predicate gates ONLY on
 * intra-family blockers. An EXTERNAL `blocked_by` (an issue that is not one of this
 * epic's children) can NEVER enter the family `merged` set, so requiring it would
 * strand the child forever (silently skipped) — wrong even when that external issue
 * is already closed/satisfied. External blockers are instead filtered at family
 * admission (`filterExternalBlockedChildren`, #934 ID-002): children with open
 * ordinary external blockers are visibly skipped, so by the time selectWave runs
 * remaining children' external blockers are satisfied and must NOT gate scheduling.
 *
 * Input order is preserved (deterministic scheduling — no sorting/shuffling).
 * An empty result means every child is either merged or still blocked; the
 * family loop uses that as its termination signal for the merged case.
 *
 * #294 EXTENSION POINT: richer scheduling (explicit topological wave numbering,
 * blocked-by-DAG cycle detection → fail-closed) layers here by replacing/wrapping
 * the predicate; the family spine keeps calling `selectWave(children, merged)`.
 */
export function selectWave(
  children: ReadonlyArray<ChildSlice>,
  merged: ReadonlySet<number>,
): ReadonlyArray<ChildSlice> {
  const family = new Set(children.map((c) => c.issue));
  return children.filter(
    (c) =>
      !merged.has(c.issue) &&
      c.blockedBy.every((b) => !family.has(b) || merged.has(b)),
  );
}

/**
 * Fail-closed cycle guard (ADR 0022 decisions 3①/4) — run by the family spine
 * BEFORE scheduling any wave.
 *
 * The wave loop schedules a child once every blocker it is `blocked_by` is
 * merged. If the children's `blocked_by` edges form a CYCLE (A↦B, B↦A, or a
 * self-loop A↦A), no child in the cycle can EVER unblock — `selectWave` would
 * just keep returning an empty wave and the spine would silently terminate with
 * the cycle members "skipped". That is an undetected deadlock. This guard
 * detects it up front and THROWS a {@link DependencyCycleError} so the spine
 * fails closed and escalates to a human (decision 4), never deadlocks.
 *
 * Scope: only INTRA-FAMILY edges count — a `blocked_by` issue that is NOT one of
 * the children (an external blocker) cannot be part of a cycle WITH the children,
 * so such edges are ignored here (whether an external blocker is satisfied is the
 * ledger-merged unblock concern, not cycle detection). Detection is an iterative
 * DFS over the directed graph child → blocker; a back-edge to a node on the
 * current DFS stack is a cycle, and the stack slice from that node is reported as
 * the cycle path (deterministic in input order).
 */
export function assertAcyclic(children: ReadonlyArray<ChildSlice>): void {
  // Node set = the children's own issue numbers; only edges to nodes IN this set
  // are intra-family (external blockers are not cycle candidates).
  const nodes = new Set(children.map((c) => c.issue));
  const blockersOf = new Map<number, ReadonlyArray<number>>();
  for (const c of children) {
    blockersOf.set(c.issue, c.blockedBy.filter((b) => nodes.has(b)));
  }

  // DFS colouring: 0 = unvisited, 1 = on the current stack (grey), 2 = done.
  const colour = new Map<number, number>();

  // Iterative DFS so a deep chain cannot blow the call stack. `stack` holds the
  // active path (for cycle reporting); `iter` tracks each frame's next edge.
  for (const start of children.map((c) => c.issue)) {
    if (colour.get(start) === 2) continue;
    const stack: number[] = [start];
    const iter = new Map<number, number>([[start, 0]]);
    colour.set(start, 1);
    while (stack.length > 0) {
      const node = stack[stack.length - 1]!;
      const edges = blockersOf.get(node) ?? [];
      const i = iter.get(node)!;
      if (i < edges.length) {
        iter.set(node, i + 1);
        const next = edges[i]!;
        const c = colour.get(next) ?? 0;
        if (c === 1) {
          // Back-edge to a grey node still on the stack → cycle. Report the path
          // from that node to the current top, plus the closing edge.
          const from = stack.indexOf(next);
          const cycle = [...stack.slice(from), next];
          throw new DependencyCycleError(cycle);
        }
        if (c === 0) {
          colour.set(next, 1);
          iter.set(next, 0);
          stack.push(next);
        }
        // c === 2 → already fully explored, no cycle through it; skip.
      } else {
        colour.set(node, 2);
        stack.pop();
      }
    }
  }
}
