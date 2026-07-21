/**
 * #1085 / ADR 0147 — shared resident-judge hub routing for the three repair
 * rings: per-slice review/fix, integrated CMR fixer, and wave-verify triage.
 *
 * One status→next table. Runner dumb-relays builder beats to the resident judge
 * with no envelope classification; builder never connects straight to a fresh
 * reviewer. Family unusable is fail-loud (ADR 0131 / #919 M1); per-slice
 * unusable collapses to resume_builder (never silent clean / S7).
 *
 * Consumers (file:line audit in the #1085 commit body):
 * - route.ts — per-slice routeEdgesFromJudgeStatus / routeBuilderBeat…
 * - family/verifyCmr.ts — wave court + integrated CMR continue routing
 * - tests — three-loop-resident-judge-1085
 */

/** Legal judge status enum after seat collapse (shared T2 language). */
export type ResidentJudgeStatus =
  | "converged"
  | "continue"
  | "escalate"
  | "toolchain"
  | "unusable";

/**
 * Hub next-action after a judge verdict. Rings map this onto their own seats
 * (S5/S2, family coder-fix, wave fixer) but must not invent a second table.
 */
export type ResidentJudgeHubNext =
  | "resume_builder"
  | "exit_loop"
  | "park"
  | "toolchain"
  | "fail_loud";

/** Which repair ring is consulting the hub (unusable policy differs). */
export type ResidentJudgeRing = "per_slice" | "family_cmr" | "wave_verify";

/**
 * Single status→hub-next table for all three rings.
 *
 * - `converged` → exit_loop (wave still applies ADR 0145 green hard-pre at the
 *   exit site; that is a precondition, not a second status table)
 * - `continue` → resume_builder
 * - `escalate` → park (decision gate)
 * - `toolchain` → toolchain (wave/env terminal; per-slice collapses this to
 *   unusable before calling — see judgeStatusFromOutput)
 * - `unusable` → per_slice: resume_builder; family rings: fail_loud
 */
export function routeResidentJudgeHub(
  status: ResidentJudgeStatus,
  ring: ResidentJudgeRing = "per_slice",
): ResidentJudgeHubNext {
  if (status === "converged") return "exit_loop";
  if (status === "continue") return "resume_builder";
  if (status === "escalate") return "park";
  if (status === "toolchain") return "toolchain";
  // unusable
  if (ring === "per_slice") return "resume_builder";
  return "fail_loud";
}

/**
 * #1085 / ADR 0147 — after every builder beat the next hub seat is always the
 * resident judge. Plan vs construction is not a runner fork; fresh reviewer is
 * never the next step.
 *
 * Returns the constant `"resident_judge"` so call sites can assert the seam
 * without re-encoding the rule in prose or a second table.
 */
export function afterBuilderBeatNext(): "resident_judge" {
  return "resident_judge";
}

/**
 * Project {@link FamilyJudgeClosure}.action onto the shared hub next-action.
 * Empty continue (0 live keys) is NOT resume_builder — callers must fail-loud
 * before spinning the builder (shared empty-continue gate).
 */
export function hubNextFromFamilyClosureAction(
  action: "pass" | "continue" | "escalate" | "toolchain" | "unusable",
  ring: "family_cmr" | "wave_verify",
): ResidentJudgeHubNext {
  if (action === "pass") return routeResidentJudgeHub("converged", ring);
  if (action === "continue") return routeResidentJudgeHub("continue", ring);
  if (action === "escalate") return routeResidentJudgeHub("escalate", ring);
  if (action === "toolchain") return routeResidentJudgeHub("toolchain", ring);
  return routeResidentJudgeHub("unusable", ring);
}
