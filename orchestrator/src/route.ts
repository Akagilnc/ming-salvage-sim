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
 *     clean/deferred only → S7(ship)→S9(verify)→S10(fixer)→S12(docRelease)→S11(cleanup)→S8(success)
 *     blocking → S5(fix)→S6(fresh full-diff review)→S4
 *
 * A valid decision escalation stays the global stop edge (checked FIRST).
 * Malformed envelopes return the same step as a redispatch request; the runner's
 * shared mechanical retry layer owns the bound and exhaustion escalation.
 */

import type { OnlineReviewTerminalState, StepId, StepOutput } from "./types.js";
import { escalateOf } from "./validate.js";
import { MAX_ONLINE_REVIEW_ROUNDS } from "./onlineReviewLoop.js";

/** What route() decides: the next step to run, or a terminal handoff. */
export type RouteDecision =
  | { kind: "next"; step: StepId }
  | {
      kind: "handoff";
      status: "success" | "escalate" | "error";
      /** Documented online-review terminal when the loop ends (#600 AC1/AC5). */
      onlineReviewTerminal?: OnlineReviewTerminalState;
    };

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
  /** Worker-reported S7 status, retained as telemetry only. */
  readonly shipStatus?: string;
  /** Host-observed truth: whether the shipped branch currently has an open PR. */
  readonly hostPrPresent?: boolean;
  /** 1-based online review round for S9/S10 routing (#600 / ADR 0061). */
  readonly onlineReviewRound?: number;
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
      // S2 implementation done → independent fresh reviewer.
      // #5: a malformed coder output (wrong kind / undefined / garbage) is a
      // contract violation → S8(error). NEVER fall through to S7 on a malformed
      // output (the runner also guards this, but route() must be safe at the
      // seam regardless of caller).
      if (ctx.output?.kind !== "coder") {
        return { kind: "next", step: "S2" };
      }
      // #252 error edge: 0 commits → S8(error: build produced nothing).
      if (!ctx.output.committed && ctx.output.selfReportDiscrepancy === undefined) {
        return { kind: "next", step: "S2" };
      }
      return { kind: "next", step: "S3" };
    }

    case "S3":
    case "S6":
      if (ctx.output?.kind !== "reviewer") {
        return { kind: "next", step: ctx.from };
      }
      return { kind: "next", step: "S4" };

    case "S4": {
      if (ctx.output?.kind !== "reviewer") {
        return { kind: "next", step: "S4" };
      }
      const blockingCount = ctx.output.findings.length;
      return blockingCount > 0
        ? { kind: "next", step: "S5" }
        : { kind: "next", step: "S7" };
    }

    case "S5": {
      if (ctx.output?.kind !== "coder") {
        return { kind: "next", step: "S5" };
      }
      if (!ctx.output.committed && ctx.output.selfReportDiscrepancy === undefined) {
        return { kind: "next", step: "S5" };
      }
      return { kind: "next", step: "S6" };
    }

    case "S7": {
      // #824: the worker's shipStatus is telemetry, not routing authority. Only
      // a fresh host-side GitHub observation decides whether S9+ is applicable.
      if (ctx.hostPrPresent !== true) {
        return { kind: "handoff", status: "success" };
      }
      return { kind: "next", step: "S9" };
    }

    case "S9": {
      if (ctx.output?.kind !== "verify") {
        return { kind: "handoff", status: "error" };
      }
      if (ctx.output.converged) {
        return {
          kind: "next",
          step: "S12",
        };
      }
      if (ctx.output.terminalState === "decision_gate_raised") {
        return {
          kind: "handoff",
          status: "escalate",
          onlineReviewTerminal: "decision_gate_raised",
        };
      }
      const round = ctx.onlineReviewRound ?? 1;
      // AC5: round 3 remaining P2/nits are attempted by default — only exhaust
      // after the final (round > cap) verify still has findings.
      if (round > MAX_ONLINE_REVIEW_ROUNDS) {
        return {
          kind: "handoff",
          status: "escalate",
          onlineReviewTerminal: "round_budget_exhausted",
        };
      }
      return { kind: "next", step: "S10" };
    }

    case "S10": {
      if (ctx.output?.kind !== "fixer") {
        return { kind: "handoff", status: "error" };
      }
      // Every valid fixer envelope, including committed:false, advances to a
      // fresh S9 verification; findings there own any decision gate.
      return { kind: "next", step: "S9" };
    }

    case "S11": {
      if (ctx.output?.kind !== "cleanup") {
        return { kind: "handoff", status: "error" };
      }
      if (!ctx.output.terminal) {
        return { kind: "handoff", status: "error" };
      }
      if (!ctx.output.ok) {
        return { kind: "handoff", status: "error" };
      }
      return { kind: "handoff", status: "success" };
    }

    case "S12": {
      if (ctx.output?.kind !== "docRelease") {
        return { kind: "handoff", status: "error" };
      }
      if (!ctx.output.released) {
        return { kind: "handoff", status: "error" };
      }
      return { kind: "next", step: "S11" };
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
