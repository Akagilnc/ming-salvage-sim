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
// Shared seam guards — the SINGLE source of truth, also used by the runner, so
// the finding-element / commitsAdded rules can never drift between two copies.
//
// #5: a coder step output must be a real coder output and a reviewer output a
// real reviewer output; anything else is a contract violation route() must NOT
// route as a success.
// integ-cmr base r2 (A): a reviewer output with any malformed finding ELEMENT
// (severity with trailing space / uppercase action / missing field) is invalid,
// so route() can never coerce it into a push past the P0/P1 gate.
// integ-cmr base r2 (B): a coder output with an inconsistent/garbage
// commitsAdded is invalid.
import {
  isValidCoderOutput,
  isValidEscalation,
  isValidReviewerOutput,
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
 * #252: error edges — S2 committed:false → S8(error). Push failure is handled
 *   in runner.ts (a backend throw, not a route output).
 * Remaining edge: fix-loop back-edge (#254) is an inline TODO.
 */
export function route(ctx: RouteContext): RouteDecision {
  // ── Global escalate stop edge (#251) ────────────────────────────────────
  // Check FIRST, ahead of every other edge (PRD #244 contract layer).
  // Any agent step (S2/S3/S5/S6) can carry `escalate`; when present the
  // runner stops immediately, records the output in the ledger, and returns
  // S8 handoff(status=escalate).  The model supplies reason+diagnosis; the
  // runner does NOT reclassify (impl vs design is the model's call — US#20).
  //
  // integ-cmr base r1 (F1): a NON-NULL escalate is only a legitimate stop
  // signal if it is a well-shaped Escalation ({reason, diagnosis} non-empty
  // strings). A garbage escalate (`{}`, wrong types, blank strings) must NOT be
  // coerced into S8(escalate) — the caller would read reason/diagnosis as
  // undefined/wrong-type. A malformed escalate is a contract violation →
  // S8(error). (A valid escalate still wins over every happy-path edge, incl.
  // an incomplete role schema — that is F2, handled in the runner: it lets the
  // escalate edge fire without first demanding the full role schema.)
  const escalate = ctx.output?.escalate;
  if (escalate != null) {
    return isValidEscalation(escalate)
      ? { kind: "handoff", status: "escalate" }
      : { kind: "handoff", status: "error" };
  }

  switch (ctx.from) {
    case "S0":
      // S0 input_gate passed → load context.
      // Gate is implemented in runner.ts: rejects non-compliant issues before
      // reaching this edge (rfa ∧ Agent Brief ∧ no sub-issues ∧ blocked_by closed).
      return { kind: "next", step: "S1" };

    case "S1":
      // S1 load_context done → coder implements.
      return { kind: "next", step: "S2" };

    case "S2": {
      // S2 coder_implement done.
      // #5: a malformed coder output (wrong kind / undefined / garbage) is a
      // contract violation → S8(error). NEVER fall through to S3 on a malformed
      // output (the runner also guards this, but route() must be safe at the
      // seam regardless of caller).
      if (!isValidCoderOutput(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      // #252 error edge: 0 commits → S8(error: coder produced nothing).
      if (!ctx.output.committed) {
        return { kind: "handoff", status: "error" };
      }
      // Happy path: committed → reviewer reviews.
      return { kind: "next", step: "S3" };
    }

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
      //
      // #5: S4 routes ONLY on a real reviewer output. A non-reviewer output
      // (wrong kind / undefined / garbage) must NOT be coerced into empty
      // findings → push — that would ship UNREVIEWED code past the P0/P1 gate.
      // It is a contract violation → S8(error). This now also rejects a
      // reviewer output whose findings array contains any MALFORMED element
      // (severity with trailing space / uppercase action / missing field),
      // which the exact-string severity/action test below would otherwise miss
      // → push a real P0 (integ-cmr base r2, finding A).
      if (!isValidReviewerOutput(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      const findings = ctx.output.findings;

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
      // NOTE: push failure is caught in runner.ts (backend.push() throws) and
      // converted to S8(error) there — it does not flow through route() because
      // route() is only called after a successful step body.
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
