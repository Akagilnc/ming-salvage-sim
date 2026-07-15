/**
 * route() — the runner's deterministic decision function (ADR 0018 §1, ADR 0030 / #925).
 *
 * The next step is decided HERE by the runner, never by the agent. route()
 * consumes the structured step output and returns the next StepId. This is the
 * state-machine edge table from PRD #244's contract layer.
 *
 * #925 / ADR 0132: per-slice review/fix convergence is judge-verdict driven:
 *
 *   S0→S1→S2(implement)→S3(judge establish)
 *     converged → S7(local handoff) → S8(success)
 *     continue  → S5(fix)→S6(judge resume)→(verdict again)
 *     escalate  → decision-kind park (global stop edge)
 *
 * S4 mechanical open-count classification is dissolved. A valid decision
 * escalation stays the global stop edge (checked FIRST). Envelope shape never
 * decides fate beyond the typed status enum: an unusable envelope follows the
 * fixed topology to the fixer path (never silent clean).
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
 * Collapse residual open-count reviewer paper (and offline verify skeletons)
 * into the sole judge-status form used by topology. Production decode already
 * emits `kind:"judge"`; this keeps resume of pre-#925 ledger rows and test
 * fixtures on one routing path (no parallel open-count station).
 */
function judgeStatusOf(output: StepOutput | undefined):
  | "converged"
  | "continue"
  | "escalate"
  | "unusable" {
  if (output == null) return "unusable";
  if (output.kind === "judge") {
    if (output.status === "converged") return "converged";
    if (output.status === "continue") return "continue";
    return "escalate";
  }
  if (output.kind === "reviewer") {
    if (output.escalate != null) return "escalate";
    // Positive residual open-count only → continue. Zero / missing / non-integer
    // count is unusable residual paper (#925 AC / #919 CR P1): never silent clean.
    if (
      typeof output.findingsCount === "number" &&
      Number.isSafeInteger(output.findingsCount) &&
      output.findingsCount > 0
    ) {
      return "continue";
    }
    return "unusable";
  }
  if (output.kind === "verify" && typeof output.converged === "boolean") {
    return output.converged ? "converged" : "continue";
  }
  return "unusable";
}

/**
 * Decide the next step.
 *
 * #925 edges: S2 → S3 judge; S3/S6 judge verdict → S7 / S5 / escalate park;
 * S5 → S6. The global escalate stop (#251) is still checked FIRST.
 */
export function route(ctx: RouteContext): RouteDecision {
  // ── Global escalate stop edge (#251) ────────────────────────────────────
  // Check FIRST, ahead of every other edge (PRD #244 contract layer).
  // Judge escalate status also surfaces via escalateOf (reason+diagnosis on
  // the output). The model supplies reason+diagnosis; the runner does NOT
  // reclassify (impl vs design is the model's call — US#20).
  const escalate = escalateOf(ctx.output);
  if (escalate != null) {
    return { kind: "handoff", status: "escalate" };
  }

  switch (ctx.from) {
    case "S0":
      return { kind: "next", step: "S1" };

    case "S1":
      return { kind: "next", step: "S2" };

    case "S2": {
      // Implementation always hands the scene to the judge (S3 establish).
      return { kind: "next", step: "S3" };
    }

    case "S3":
    case "S6": {
      // #925: judge verdict tri-state is the sole convergence signal.
      // Residual open-count paper is projected to the same three statuses
      // (no second S4 station, no prose parsing).
      const status = judgeStatusOf(ctx.output);
      if (status === "converged") return { kind: "next", step: "S7" };
      if (status === "continue") return { kind: "next", step: "S5" };
      if (status === "escalate") return { kind: "handoff", status: "escalate" };
      // Unusable envelope → fixer path (never silent clean / S7).
      return { kind: "next", step: "S5" };
    }

    case "S4": {
      // #925: S4 mechanical open-count station is dissolved. Residual path for
      // legacy ledgers that still land on S4 — same status projection as S3/S6.
      const status = judgeStatusOf(ctx.output);
      if (status === "converged") return { kind: "next", step: "S7" };
      if (status === "continue") return { kind: "next", step: "S5" };
      if (status === "escalate") return { kind: "handoff", status: "escalate" };
      return { kind: "next", step: "S5" };
    }

    case "S5": {
      // Fix and fresh re-judge alternate by topology.
      return { kind: "next", step: "S6" };
    }

    case "S7":
      return { kind: "handoff", status: "success" };

    case "S8":
      throw new Error("route: S8 is terminal; nothing routes out of it");

    default: {
      const never: never = ctx.from;
      throw new Error(`route: unhandled step ${String(never)}`);
    }
  }
}
