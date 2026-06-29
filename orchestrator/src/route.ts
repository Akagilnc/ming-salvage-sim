/**
 * route() — the runner's deterministic decision function (ADR 0018 §1, ADR 0026).
 *
 * The next step is decided HERE by the runner, never by the agent. route()
 * consumes the structured step output and returns the next StepId. This is the
 * state-machine edge table from PRD #244's contract layer.
 *
 * ⚠️ PRE-0030 (about to be reversed — see ADR 0030, Proposed): ADR 0030 re-splits
 * the per-slice review→fix→re-review loop back to runner-dispatched coder/reviewer/
 * fix worker steps; the S2-only collapse below (and the "S3/S5/S6 deleted" claim)
 * will be reinstated as runner edges when ADR 0030 lands (#369/#422). Until then the
 * ADR-0026 edge table below is the current sequence — EXCEPT the per-slice REVIEW
 * specifics (a fresh Opus pass) are already further superseded by the current
 * Claude-paused policy: per CLAUDE.md "## Skill routing" + souls/coder.md the
 * per-slice 2nd review is a single NON-Claude (Codex) leg, NOT Opus. Don't re-invoke
 * Opus per the comment below under the Claude-paused pipeline.
 *
 * ADR 0026 (2026-06-24 correction, wiki line 42): the single-slice runner is a
 * PURE SCHEDULER and the per-slice review→fix→re-review LOOP no longer lives at
 * the runner level. The edge table collapses to:
 *
 *   S0(gate) → S1(context) → S2(whole-slice build) → S7(ship) → S8(handoff)
 *
 * S2 is ONE memory-bearing build worker that runs the entire per-slice sequence
 * INTERNALLY (invoke `/tdd`; then `/review` + the self-check 二连; then
 * `/ak-cross-m-review --scenario per-slice` to concurrence; commit with the
 * `sandcastle:` prefix; return the FINAL reviewed commit). So there is NO S3
 * reviewer step, NO S4 route fan-out, NO S5 fix step, NO S6 re-review here —
 * those edges are DELETED. A committed S2 output routes straight to S7 ship.
 * Escalate stays the global stop edge (checked FIRST).
 */

import type { StepId, StepOutput } from "./types.js";
// Shared seam guards — the SINGLE source of truth, also used by the runner, so
// the coder-output / commitsAdded rules can never drift between two copies.
//
// #5: a coder step output must be a real coder output; anything else is a
// contract violation route() must NOT route as a success.
// integ-cmr base r2 (B): a coder output with an inconsistent/garbage
// commitsAdded is invalid.
import {
  escalateOf,
  isValidCoderOutput,
  isValidEscalation,
} from "./validate.js";

/** What route() decides: the next step to run, or a terminal handoff. */
export type RouteDecision =
  | { kind: "next"; step: StepId }
  | { kind: "handoff"; status: "success" | "escalate" | "error" };

/** Inputs route() needs to decide the edge out of `from`. */
export interface RouteContext {
  /** The step we are routing OUT of. */
  readonly from: StepId;
  /**
   * The agent output the edge should act on — i.e. the most recent agent-step
   * output in flight. For S2 (the only agent step) this is the build worker's
   * own output. Undefined when no agent has run yet.
   */
  readonly output?: StepOutput;
}

/**
 * Decide the next step.
 *
 * ADR 0026 collapsed edges: S0→S1, S1→S2, S2(committed)→S7, S7→S8(success).
 * The global escalate stop (#251) is still checked FIRST, ahead of the switch.
 * S2 0-commit / malformed coder output → S8(error) (#252 / #5).
 */
export function route(ctx: RouteContext): RouteDecision {
  // ── Global escalate stop edge (#251) ────────────────────────────────────
  // Check FIRST, ahead of every other edge (PRD #244 contract layer).
  // The S2 build worker can carry `escalate`; when present the runner stops
  // immediately, records the output in the ledger, and returns S8 handoff
  // (status=escalate). The model supplies reason+diagnosis; the runner does NOT
  // reclassify (impl vs design is the model's call — US#20).
  //
  // integ-cmr base r1 (F1): a NON-NULL escalate is only a legitimate stop
  // signal if it is a well-shaped Escalation ({reason, diagnosis} non-empty
  // strings). A garbage escalate (`{}`, wrong types, blank strings) must NOT be
  // coerced into S8(escalate) — the caller would read reason/diagnosis as
  // undefined/wrong-type. A malformed escalate is a contract violation →
  // S8(error). (A valid escalate still wins over the happy-path edge, incl. an
  // incomplete role schema — that is F2, handled in the runner: it lets the
  // escalate edge fire without first demanding the full role schema.)
  const escalate = escalateOf(ctx.output);
  if (escalate != null) {
    return isValidEscalation(escalate)
      ? { kind: "handoff", status: "escalate" }
      : { kind: "handoff", status: "error" };
  }

  switch (ctx.from) {
    case "S0":
      // S0 input_gate passed → load context.
      // Gate is implemented in runner.ts: rejects non-compliant issues before
      // reaching this edge (rfa ∧ no sub-issues ∧ blocked_by closed).
      return { kind: "next", step: "S1" };

    case "S1":
      // S1 load_context done → the build worker runs the whole slice.
      return { kind: "next", step: "S2" };

    case "S2": {
      // S2 coder build done — the worker ran the WHOLE per-slice sequence
      // internally (tdd → review + self-check → per-slice cmr to concurrence)
      // and returned the FINAL reviewed commit (ADR 0026).
      // #5: a malformed coder output (wrong kind / undefined / garbage) is a
      // contract violation → S8(error). NEVER fall through to S7 on a malformed
      // output (the runner also guards this, but route() must be safe at the
      // seam regardless of caller).
      if (!isValidCoderOutput(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      // #252 error edge: 0 commits → S8(error: build produced nothing).
      if (!ctx.output.committed) {
        return { kind: "handoff", status: "error" };
      }
      // Happy path: the reviewed slice is committed → ship.
      return { kind: "next", step: "S7" };
    }

    case "S7":
      // S7 ship succeeded → success handoff.
      // NOTE: ship failure is caught in runner.ts (the ship worker
      // throws/escalates) and converted to S8(error)/S8(escalate) there — it
      // does not flow through route() because route() is only called after a
      // successful step body.
      return { kind: "handoff", status: "success" };

    case "S8":
      // S8 is terminal — route() is never called to leave it.
      throw new Error("route: S8 is terminal; nothing routes out of it");

    default: {
      // Exhaustiveness guard: a new StepId must be handled above.
      const never: never = ctx.from;
      throw new Error(`route: unhandled step ${String(never)}`);
    }
  }
}
