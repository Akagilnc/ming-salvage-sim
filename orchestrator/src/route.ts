/**
 * route() — the runner's deterministic decision function (ADR 0018 §1, ADR 0030).
 *
 * The next step is decided HERE by the runner, never by the agent. route()
 * consumes the structured step output and returns the next StepId. This is the
 * state-machine edge table from PRD #244's contract layer.
 *
 * ADR 0030 re-splits per-slice review/fix convergence into runner-visible
 * worker boundaries:
 *
 *   S0→S1→S2(implement)→S3(review)→S4(classify)
 *     clean/deferred only → S7(ship)→S9(verify)→S10(fixer)→S11(cleanup)→S12(docRelease)→S8(success)
 *     blocking → S5(fix)→S6(fresh full-diff review)→S4
 *
 * Escalate stays the global stop edge (checked FIRST).
 */

import type { Finding, StepId, StepOutput } from "./types.js";
import { classifyFindings } from "./findings.js";
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
  isValidReviewerOutput,
} from "./validate.js";
import {
  isValidCleanupResult,
  isValidDocReleaseResult,
  isValidFixerResult,
  isValidVerifyResult,
} from "./reviewLoopOutcome.js";

/** What route() decides: the next step to run, or a terminal handoff. */
export type RouteDecision =
  | { kind: "next"; step: StepId }
  | { kind: "handoff"; status: "success" | "escalate" | "error" };

/** Inputs route() needs to decide the edge out of `from`. */
export interface RouteContext {
  /** The step we are routing OUT of. */
  readonly from: StepId;
  /**
   * The agent output the edge should act on — i.e. the most recent agent-worker
   * output in flight. ADR 0030 has multiple agent steps (S2/S3/S5/S6); this is
   * the output from whichever one just completed. Undefined when no agent has
   * run yet.
   */
  readonly output?: StepOutput;
  /**
   * Runner-adjudicated blocking findings selected at S4.
   *
   * For S6 re-reviews, ADR 0030 closure can re-open a prior claimed-fixed
   * finding even when the reviewer omits it from `findings[]` and marks it
   * still-active/unable-to-assess. S4 routing must follow the runner's
   * adjudicated state, not reclassify the raw reviewer payload as if absence
   * were closure.
   */
  readonly pendingBlockingFindings?: ReadonlyArray<Finding>;
}

/**
 * Decide the next step.
 *
 * ADR 0030 edges: S2 committed output goes to S3, S3/S6 reviewer output goes to
 * S4, S4 sends blocking findings to S5 and clean/deferred-only reviews to S7.
 * The global escalate stop (#251) is still checked FIRST, ahead of the switch.
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
      // S1 load_context done → implementation worker.
      return { kind: "next", step: "S2" };

    case "S2": {
      // S2 implementation done → independent fresh reviewer.
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
      return { kind: "next", step: "S3" };
    }

    case "S3":
    case "S6":
      if (!isValidReviewerOutput(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      return { kind: "next", step: "S4" };

    case "S4": {
      if (!isValidReviewerOutput(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      const blockingCount =
        ctx.pendingBlockingFindings !== undefined
          ? ctx.pendingBlockingFindings.length
          : classifyFindings(ctx.output.findings).blocking.length;
      return blockingCount > 0
        ? { kind: "next", step: "S5" }
        : { kind: "next", step: "S7" };
    }

    case "S5": {
      if (!isValidCoderOutput(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      if (!ctx.output.committed) {
        return { kind: "handoff", status: "error" };
      }
      return { kind: "next", step: "S6" };
    }

    case "S7":
      // S7 ship succeeded → enter the runner-visible review-loop skeleton.
      // NOTE: ship failure is caught in runner.ts (the ship worker
      // throws/escalates) and converted to S8(error)/S8(escalate) there — it
      // does not flow through route() because route() is only called after a
      // successful step body.
      return { kind: "next", step: "S9" };

    case "S9": {
      if (!isValidVerifyResult(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      return { kind: "next", step: "S10" };
    }

    case "S10": {
      if (!isValidFixerResult(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      return { kind: "next", step: "S11" };
    }

    case "S11": {
      if (!isValidCleanupResult(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      return { kind: "next", step: "S12" };
    }

    case "S12": {
      if (!isValidDocReleaseResult(ctx.output)) {
        return { kind: "handoff", status: "error" };
      }
      return { kind: "handoff", status: "success" };
    }

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
