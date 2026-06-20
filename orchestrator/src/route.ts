/**
 * route() — the runner's deterministic decision function (ADR 0018 §1).
 *
 * The next step is decided HERE by the runner, never by the agent. route()
 * consumes the structured step output and returns the next StepId. This is the
 * state-machine edge table from PRD #244's contract layer.
 *
 * Slice #247: happy-path edges S0→S1→S2→S3→S4→S7→S8 (empty findings = approve).
 * Slice #250: S4 severity+action fan-out (P0/P1 or fix_now → S5; defer → S7).
 *
 * Remaining TODOs (each labelled inline):
 *   #248 — S0 real gate (rfa ∧ Agent Brief ∧ no sub-issues ∧ blocked_by closed)
 *   #251 — escalate global stop edge (checked FIRST, before the switch)
 *   #252 — S2/S5 0-commit→error, S7 push-failure→error
 *   #254 — S5→S6→S4 fix-loop back-edge
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
 * Decide the next step.
 * #247: happy-path edges. #251: global escalate stop (checked FIRST).
 * #250: S4 severity+action fan-out (P0/P1 or fix_now → S5; defer → S7).
 * Remaining edges (error/#252, fix-loop/#254) are inline TODOs.
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

    case "S4": {
      // S4 route_findings — runner reads severity+action JSON; the agent never
      // decides the next step (ADR 0018 §1 / PRD #244 Implementation Decision).
      //
      // Route to S5 coder_fix when:
      //   • any P0/P1 (severity critical or high) is present, OR
      //   • any P2/P3 (medium / low / clarity) with action:'fix_now' is present
      // Otherwise → S7 push (approve). action:'defer' findings do not block;
      // they surface via the defer list on S8 handoff (PRD #244 US#25).
      //
      // Escalate is handled globally above this switch.
      //
      // TODO(#254 fix loop): the S5→S6→S4 back-edge lands here (no change
      // needed in the routing logic itself; the loop just re-enters S4).
      const findings =
        ctx.output?.kind === "reviewer" ? ctx.output.findings : [];

      const needsFix = findings.some(
        (f) =>
          f.severity === "critical" ||
          f.severity === "high" ||
          f.action === "fix_now",
      );

      return needsFix
        ? { kind: "next", step: "S5" }
        : { kind: "next", step: "S7" };
    }

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
