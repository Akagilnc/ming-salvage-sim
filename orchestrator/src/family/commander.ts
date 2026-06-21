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
 * main loop, which only ever CALLS selectWave. That is the seam boundary.
 *
 * No LLM dependency inference (ADR 0022: we have explicit blocked_by, so the
 * native Plan's LLM selector is neither used nor needed) and NO round/cycle
 * detection yet (#294). #293's contract: given children + a merged set, return
 * the unmerged children whose blocked_by ⊆ merged, in input order
 * (deterministic).
 */

import type { ChildSlice } from "./types.js";

/**
 * Select the next wave of schedulable child slices.
 *
 * A child is in the wave iff:
 *   - it is NOT already merged (`!merged.has(child.issue)`), AND
 *   - every issue it is `blocked_by` is in the merged set
 *     (`child.blockedBy.every((b) => merged.has(b))`).
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
  return children.filter(
    (c) => !merged.has(c.issue) && c.blockedBy.every((b) => merged.has(b)),
  );
}
