/**
 * route() — the runner's deterministic decision function (ADR 0018 §1, ADR 0030 / #925).
 *
 * The next step is decided HERE by the runner, never by the agent. route()
 * consumes the structured step output and returns the next StepId. This is the
 * state-machine edge table from PRD #244's contract layer.
 *
 * #925 / ADR 0132 + #1083 / ADR 0147: per-slice review/fix is a **judge hub**:
 *
 *   S0→S1→S2(builder beat)→S3(resident judge)
 *     converged → S7(local handoff) → S8(completed)
 *     continue  → S5(builder beat)→S6(resident judge)→(verdict again)
 *     escalate  → decision-kind park (global stop edge)
 *
 * Builder beats (S2 / S5 — plan or construction, no envelope classification)
 * always dumb-relay to the resident judge. Builder and fresh reviewer never
 * connect directly; fresh review legs are the judge's post-receive outer gate.
 *
 * #1082 / ADR 0147: when `coderPlanPhase` is true, judge continue resumes the
 * same S2 builder (plan pre-review / construction) instead of S5 — 准/退/索证
 * live in judge prose, not live-finding rows.
 *
 * S4 mechanical open-count classification is dissolved. A valid decision
 * escalation stays the global stop edge (checked FIRST). Envelope shape never
 * decides fate beyond the typed status enum: an unusable envelope follows the
 * fixed topology to the fixer path (never silent clean).
 */

import type { SliceStepId, StepOutput } from "./types.js";
import { judgeStatusFromOutput } from "./judgeStation.js";
import {
  afterBuilderBeatNext,
  routeResidentJudgeHub,
} from "./residentJudgeHub.js";
import { escalateOf } from "./validate.js";

/** What route() decides: the next step to run, or a terminal handoff. */
export type RouteDecision =
  | { kind: "next"; step: SliceStepId }
  | {
      kind: "handoff";
      status: "completed" | "parked" | "failed";
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
  /**
   * #1082 — still in coder plan pre-review (no construction beat yet).
   * When true, judge `continue` resumes S2 (same builder), not S5.
   */
  readonly coderPlanPhase?: boolean;
}

/**
 * Builder beat seats that always dumb-relay to the resident judge hub
 * (#1083 / ADR 0147). Plan vs construction is not a runner concern.
 */
export type BuilderBeatStep = "S2" | "S5";

/**
 * #1083 / #1085 / ADR 0147 — single seam: every builder beat routes to the
 * resident judge. No envelope classification (committed / plan-only / refuse
 * cargo never forks this edge). Fresh reviewer is never the next step from a
 * builder beat — judge receives first, then may dispatch fresh legs.
 *
 * Consumers (audit):
 * - route() S2 / S5 cases
 * - family/verifyCmr.ts wave + CMR fixer (via {@link afterBuilderBeatNext})
 */
export function routeBuilderBeatToResidentJudge(
  from: BuilderBeatStep,
): RouteDecision {
  // Shared hub constant — rings must not invent a second "after builder" table.
  if (afterBuilderBeatNext() !== "resident_judge") {
    throw new Error("route: afterBuilderBeatNext must be resident_judge");
  }
  if (from === "S2") return { kind: "next", step: "S3" };
  return { kind: "next", step: "S6" };
}

/**
 * S3 / S6 / residual-S4 status → edge table via the shared #1085 hub
 * ({@link routeResidentJudgeHub}). Unusable and continue both go to S5
 * (never silent clean / S7) — except #1082 plan phase, where continue
 * resumes S2.
 *
 * Status collapse itself is {@link judgeStatusFromOutput} in judgeStation
 * (#919 S1 — shared with runner normalize; no parallel predicate here).
 */
function routeEdgesFromJudgeStatus(
  status: "converged" | "continue" | "escalate" | "unusable",
  coderPlanPhase?: boolean,
): RouteDecision {
  const hub = routeResidentJudgeHub(status, "per_slice");
  if (hub === "exit_loop") return { kind: "next", step: "S7" };
  if (hub === "park") return { kind: "handoff", status: "parked" };
  // resume_builder (continue / unusable). toolchain never reaches per-slice
  // collapse (judgeStatusFromOutput maps it to unusable → resume_builder).
  if (hub === "resume_builder" || hub === "toolchain" || hub === "fail_loud") {
    // #1082: plan pre-review continue/unusable → same S2 builder (not fixer).
    if (coderPlanPhase === true) return { kind: "next", step: "S2" };
    return { kind: "next", step: "S5" };
  }
  const _never: never = hub;
  throw new Error(`route: unhandled hub next ${String(_never)}`);
}

/**
 * Decide the next step.
 *
 * #925 / #1083 edges: S2/S5 builder beat → resident judge (S3/S6);
 * S3/S6 judge verdict → S7 / S5 / escalate park. #1082: plan-phase judge
 * continue → S2. The global escalate stop (#251) is still checked FIRST.
 */
export function route(ctx: RouteContext): RouteDecision {
  // ── Global escalate stop edge (#251) ────────────────────────────────────
  // Check FIRST, ahead of every other edge (PRD #244 contract layer).
  // Judge escalate status also surfaces via escalateOf (reason+diagnosis on
  // the output). The model supplies reason+diagnosis; the runner does NOT
  // reclassify (impl vs design is the model's call — US#20).
  const escalate = escalateOf(ctx.output);
  if (escalate != null) {
    return { kind: "handoff", status: "parked" };
  }

  switch (ctx.from) {
    case "S0":
      return { kind: "next", step: "S1" };

    case "S1":
      return { kind: "next", step: "S2" };

    case "S2":
      // #1083: builder beat → resident judge hub (no envelope fork).
      return routeBuilderBeatToResidentJudge("S2");

    case "S3":
    case "S6":
    case "S4": {
      // #925: judge verdict tri-state is the sole convergence signal.
      // S4 is dissolved open-count station — residual historical ledgers only;
      // same edge helper as live S3/S6 (no second status→edge table).
      return routeEdgesFromJudgeStatus(
        judgeStatusFromOutput(ctx.output),
        ctx.coderPlanPhase,
      );
    }

    case "S5":
      // #1083: fixer beat → resident judge hub (never direct fresh reviewer).
      return routeBuilderBeatToResidentJudge("S5");

    case "S7":
      return { kind: "handoff", status: "completed" };

    case "S8":
      throw new Error("route: S8 is terminal; nothing routes out of it");

    default: {
      const never: never = ctx.from;
      throw new Error(`route: unhandled step ${String(never)}`);
    }
  }
}
