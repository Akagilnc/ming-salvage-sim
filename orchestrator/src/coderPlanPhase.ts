/**
 * #1082 / ADR 0147 — coder plan-phase closed loop (铺码前过堂).
 *
 * Topology (when enabled):
 *   S2 plan beat → S3 resident judge → continue → same S2 (plan or construct)
 *   until a construct beat lands → normal post-construction S3/S5 edges.
 *
 * Runner never reads plan/verdict prose. It only:
 *   - transports opaque plan body / judge fixPacketBody
 *   - routes on JudgeVerdictStatus + plan-phase flag
 *   - resumes the same coder + judge sessions (no fresh legs for pre-review)
 *
 * Vitest defaults the loop OFF (fixture tax, same pattern as #1081 open court);
 * production always ON. Suites that exercise this path set
 * `ORCHESTRATOR_CODER_PLAN_PHASE=1`.
 */

/** Cargo beat tokens on {@link import("./types.js").CoderOutput}. */
export const CODER_BEAT_PLAN = "plan" as const;
export const CODER_BEAT_CONSTRUCT = "construct" as const;

export type CoderBeatKind = typeof CODER_BEAT_PLAN | typeof CODER_BEAT_CONSTRUCT;

/**
 * Landing / dispatch hint for the next S2 beat (runner-authored; not prose).
 * `after_plan_verdict` = judge has returned continue; soul decides re-plan vs construct.
 */
export type CoderBeatHint = "plan" | "after_plan_verdict";

const PLAN_PHASE_ENV = "ORCHESTRATOR_CODER_PLAN_PHASE";

/**
 * Whether the coder plan-phase loop is active.
 *
 * Production (no vitest): always true.
 * Vitest: off unless `ORCHESTRATOR_CODER_PLAN_PHASE=1`.
 */
export function shouldRunCoderPlanPhase(
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const underVitest =
    env.VITEST === "true" || typeof env.VITEST_WORKER_ID === "string";
  if (!underVitest) return true;
  return env[PLAN_PHASE_ENV] === "1";
}

type BeatCargo = {
  readonly beat?: string;
  readonly committed?: boolean;
  readonly commitsAdded?: number;
};

/**
 * Resolve beat kind from coder cargo.
 *
 * Explicit `beat` wins. Without it, any commit activity ⇒ construct
 * (legacy construction report); otherwise plan.
 */
export function coderBeatFromOutput(
  output: BeatCargo | undefined,
): CoderBeatKind {
  if (output?.beat === CODER_BEAT_PLAN) return CODER_BEAT_PLAN;
  if (output?.beat === CODER_BEAT_CONSTRUCT) return CODER_BEAT_CONSTRUCT;
  if (
    output &&
    (output.committed === true ||
      (typeof output.commitsAdded === "number" && output.commitsAdded > 0))
  ) {
    return CODER_BEAT_CONSTRUCT;
  }
  return CODER_BEAT_PLAN;
}

type PlanPhaseLedgerRow = {
  readonly step?: string;
  readonly output?: {
    readonly kind?: string;
    readonly status?: string;
    readonly beat?: string;
    readonly committed?: boolean;
    readonly commitsAdded?: number;
    readonly planBody?: string;
  };
};

/** Single-scan plan-phase state for the runner (L3: one pass, two consumers). */
export type CoderPlanPhaseScan = {
  /** True until a post-verdict construct beat lands. */
  readonly planPhase: boolean;
  /** Next S2 beat hint while still in plan phase. */
  readonly beatHint: CoderBeatHint;
};

/**
 * One ledger scan → plan phase + next S2 beat hint.
 *
 * Rules (structural — no prose):
 * - Every S2 before the first post-plan judge continue is a plan beat
 *   (even if cargo wrongly claims construct — first beat is plan).
 * - After a plan-phase judge `continue`, subsequent S2 rows use cargo beat:
 *   `plan` keeps the phase (退回 / re-plan); `construct` ends it.
 * - Beat hint: `after_plan_verdict` once a plan-phase judge continue was seen
 *   and the phase is still open; otherwise `plan`.
 */
export function scanCoderPlanPhase(
  ledger: ReadonlyArray<PlanPhaseLedgerRow>,
): CoderPlanPhaseScan {
  let sawPlanS2 = false;
  let sawJudgeContinueAfterPlan = false;
  let planPhase = true;

  for (const entry of ledger) {
    if (entry.step === "S2" && entry.output?.kind === "coder") {
      if (!sawJudgeContinueAfterPlan) {
        // First-wave S2(s) are always plan while awaiting / before first verdict.
        sawPlanS2 = true;
      } else if (coderBeatFromOutput(entry.output) === CODER_BEAT_CONSTRUCT) {
        // Post-verdict construct cargo ends plan phase; re-plan keeps it.
        planPhase = false;
      }
    }
    if (
      (entry.step === "S3" || entry.step === "S6") &&
      entry.output?.kind === "judge" &&
      entry.output.status === "continue" &&
      sawPlanS2
    ) {
      sawJudgeContinueAfterPlan = true;
    }
  }

  return {
    planPhase,
    beatHint:
      sawJudgeContinueAfterPlan && planPhase ? "after_plan_verdict" : "plan",
  };
}

/**
 * Opaque plan prose from the latest S2 coder row with a non-empty planBody
 * (runner transports only; no beat filter).
 */
export function latestPlanBodyFromLedger(
  ledger: ReadonlyArray<PlanPhaseLedgerRow>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i -= 1) {
    const entry = ledger[i]!;
    if (entry.step !== "S2" || entry.output?.kind !== "coder") continue;
    const body = entry.output.planBody;
    if (typeof body === "string" && body.trim().length > 0) return body;
  }
  return undefined;
}
