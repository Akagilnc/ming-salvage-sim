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
 *     clean/deferred only → S7(local handoff) → S8(success)
 *     blocking → S5(fix)→S6(fresh full-diff review)→S4
 *
 * A valid decision escalation stays the global stop edge (checked FIRST).
 * Envelope shape never decides fate: kind guards only narrow worker-owned fields;
 * an unusable envelope follows the same fixed topology to the next worker.
 */

import type { SliceStepId, StepOutput } from "./types.js";
import { escalateOf } from "./validate.js";

/** What route() decides: the next step to run, or a terminal handoff. */
export type RouteDecision =
  | { kind: "next"; step: SliceStepId }
  | {
      kind: "handoff";
      status: "success" | "escalate" | "error";
    };

/** Inputs route() needs to decide the edge out of `from`. */
export interface RouteContext {
  /** The step we are routing OUT of. */
  readonly from: SliceStepId;
  /**
   * The agent output the edge should act on — i.e. the most recent agent-worker
   * output in flight. ADR 0030 has multiple agent steps (S2/S3/S5/S6); this is
   * the output from whichever one just completed. Undefined when no agent has
   * run yet.
   */
  readonly output?: StepOutput;
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
  const escalate = escalateOf(ctx.output);
  if (escalate != null) {
    return { kind: "handoff", status: "escalate" };
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
      // A completed implementation worker always hands the scene to the fresh
      // reviewer. Empty or incorrect work is the reviewer's judgment.
      return { kind: "next", step: "S3" };
    }

    case "S3":
    case "S6":
      return { kind: "next", step: "S4" };

    case "S4": {
      if (ctx.output?.kind === "reviewer") {
        // ADR 0131 / #899: route on the self-reported open-count when present;
        // process-internal seams may still declare via the findings array.
        const blockingCount =
          ctx.output.findingsCount ?? ctx.output.findings.length;
        return blockingCount > 0
          ? { kind: "next", step: "S5" }
          : { kind: "next", step: "S7" };
      }
      // Unusable review cargo goes to the fixer with its raw artifact pointers.
      return { kind: "next", step: "S5" };
    }

    case "S5": {
      // Fix and fresh re-review alternate by topology, never by git movement.
      return { kind: "next", step: "S6" };
    }

    case "S7":
      return { kind: "handoff", status: "success" };

    case "S8":
      // S8 is terminal — route() is never called to leave it.
      throw new Error("route: S8 is terminal; nothing routes out of it");

    default: {
      // Exhaustiveness guard: a new slice step must be handled above.
      const never: never = ctx.from;
      throw new Error(`route: unhandled step ${String(never)}`);
    }
  }
}
