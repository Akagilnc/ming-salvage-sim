/**
 * route() — the runner's deterministic decision function (ADR 0018 §1).
 *
 * The next step is decided HERE by the runner, never by the agent. route()
 * consumes the structured step output and returns the next StepId. This is the
 * state-machine edge table from PRD #244's contract layer.
 *
 * Slice #247 implements ONLY the happy-path edges:
 *   S0 → S1 → S2 → S3 → S4 → S7 → S8
 * Every other edge (fix loop S5/S6, escalate stop, error handoff, full
 * severity+action routing) is a labelled TODO seam left for its owning slice.
 * Do not implement those here — they are out of #247 scope.
 */

import type { StepId, StepOutput } from "./types.js";

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
   * output in flight. For agent steps (S2/S3/S5/S6) this is that step's own
   * output; for the route_findings action (S4) it is the preceding reviewer
   * output (the findings S4 routes on). Undefined when no agent has run yet.
   */
  readonly output?: StepOutput;
}

/**
 * Decide the next step. #247 = happy-path edges; #251 adds global escalate.
 *
 * NOTE: S2/S5 0-commit→error, S4 severity+action fan-out, the S5→S6→S4 fix
 * loop, and push-failure→error are intentionally NOT here. Each is owned by
 * a later slice (see inline TODOs).
 */
export function route(ctx: RouteContext): RouteDecision {
  // ── Global escalate stop edge (#251) ────────────────────────────────────
  // Check FIRST, ahead of every other edge (PRD #244 contract layer).
  // Any agent step (S2/S3/S5/S6) can carry `escalate`; when present the
  // runner stops immediately, records the output in the ledger, and returns
  // S8 handoff(status=escalate).  The model supplies reason+diagnosis; the
  // runner does NOT reclassify (impl vs design is the model's call — US#20).
  if (ctx.output?.escalate != null) {
    return { kind: "handoff", status: "escalate" };
  }

  switch (ctx.from) {
    case "S0":
      // S0 input_gate passed → load context.
      // TODO(#248): the real S0 gate (rfa ∧ Agent Brief ∧ no sub-issues ∧
      // blocked_by all closed) rejects non-compliant issues before reaching
      // here; #247's fake feeds a compliant issue so the gate is a pass-through.
      return { kind: "next", step: "S1" };

    case "S1":
      // S1 load_context done → coder implements.
      return { kind: "next", step: "S2" };

    case "S2":
      // S2 coder_implement done → reviewer reviews.
      // TODO(#252 error edge): if coder committed:false (0 commits) → S8
      // handoff(status=error: coder produced nothing). #247 happy path
      // assumes committed:true.
      return { kind: "next", step: "S3" };

    case "S3":
      // S3 reviewer_full_review done → route findings.
      return { kind: "next", step: "S4" };

    case "S4":
      // S4 route_findings: happy path = no findings → approve → push.
      // TODO(#250 severity+action fan-out): real S4 routes to S5 coder_fix
      // when there is any P0/P1 OR any P2/P3 with action:'fix_now'; defer-only
      // P2/P3 go to the defer list and do not block. #247 only handles the
      // empty-findings (approve) edge.
      // TODO(#254 fix loop): the S5→S6→S4 fix-loop back-edge lands here.
      return { kind: "next", step: "S7" };

    case "S7":
      // S7 push succeeded → success handoff.
      // TODO(#252 error edge): push failure → S8 handoff(status=error).
      return { kind: "handoff", status: "success" };

    // S5 coder_fix / S6 reviewer_rereview: fix-loop steps — owned by #254.
    case "S5":
    case "S6":
      throw new Error(
        `route: edge out of ${ctx.from} not implemented in #247 (fix loop = #254)`,
      );

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
