/**
 * #1082 / ADR 0147 — coder plan-phase closed loop (铺码前过堂).
 *
 * Topology (when enabled):
 *   S2 plan beat → S3 resident judge → continue → same S2 (plan or construct)
 *   until a construct beat lands → normal post-construction S3/S5 edges.
 *
 * Runner never reads plan/verdict prose. It only:
 *   - transports opaque plan body / judge fixPacketBody
 *   - routes on JudgeVerdictStatus + plan-phase flag + live-finding count
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
  };
};

/**
 * True while no construction beat has completed after plan pre-review.
 *
 * Rules (structural — no prose):
 * - Every S2 before the first post-plan judge continue is a plan beat
 *   (even if cargo wrongly claims construct — first beat is plan).
 * - After a plan-phase judge `continue`, subsequent S2 rows use cargo beat:
 *   `plan` keeps the phase (退回 / re-plan); `construct` ends it.
 */
export function isCoderPlanPhase(
  ledger: ReadonlyArray<PlanPhaseLedgerRow>,
): boolean {
  let sawPlanS2 = false;
  let sawJudgeContinueAfterPlan = false;

  for (const entry of ledger) {
    if (entry.step === "S2" && entry.output?.kind === "coder") {
      if (!sawJudgeContinueAfterPlan) {
        // First-wave S2(s) are always plan while awaiting / before first verdict.
        sawPlanS2 = true;
        continue;
      }
      // Post-verdict: construct cargo ends plan phase; re-plan keeps it.
      if (coderBeatFromOutput(entry.output) === CODER_BEAT_CONSTRUCT) {
        return false;
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
  return true;
}

/**
 * Hint for the next S2 dispatch while plan phase is active.
 * Before any plan S2 / before first plan-phase judge continue → `plan`.
 * After judge continue (still in plan phase) → `after_plan_verdict`.
 */
export function nextCoderBeatHint(
  ledger: ReadonlyArray<PlanPhaseLedgerRow>,
): CoderBeatHint {
  let sawPlanS2 = false;
  let sawJudgeContinueAfterPlan = false;
  for (const entry of ledger) {
    if (entry.step === "S2" && entry.output?.kind === "coder") {
      if (!sawJudgeContinueAfterPlan) sawPlanS2 = true;
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
  return sawJudgeContinueAfterPlan ? "after_plan_verdict" : "plan";
}

/**
 * Opaque plan prose from the latest plan-beat S2 row (runner transports only).
 */
export function latestPlanBodyFromLedger(
  ledger: ReadonlyArray<PlanPhaseLedgerRow & { output?: { planBody?: string } }>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i -= 1) {
    const entry = ledger[i]!;
    if (entry.step !== "S2" || entry.output?.kind !== "coder") continue;
    // Prefer rows that are still plan beats (or pre-verdict first wave).
    const body = entry.output.planBody;
    if (typeof body === "string" && body.trim().length > 0) return body;
  }
  return undefined;
}

export type JudgeContinueRoute =
  | { readonly kind: "builder"; readonly step: "S2" }
  | { readonly kind: "fixer"; readonly step: "S5" }
  | { readonly kind: "empty_continue_drift" };

/**
 * Where judge `continue` goes under #1082.
 *
 * Plan phase: always resume S2 (same builder) — 0 live findings is legal
 * (准/退/索证 live in prose + fixPacketBody, not live-finding rows).
 * Post-construction: live findings → S5; empty continue → contract drift.
 */
export function routeJudgeContinueForPlanPhase(input: {
  readonly planPhase: boolean;
  readonly liveFindingCount: number;
  readonly terminalDispositionCount: number;
}): JudgeContinueRoute {
  if (input.planPhase) {
    return { kind: "builder", step: "S2" };
  }
  if (input.liveFindingCount > 0) {
    return { kind: "fixer", step: "S5" };
  }
  if (input.terminalDispositionCount > 0) {
    // Terminal-only continue routes like converged at the runner layer;
    // route() still sees continue — caller handles terminal-only separately.
    // For pure route edges, empty live → S5 is wrong; mark drift unless
    // terminals exist (runner suppresses S5 spin for terminal-only).
    return { kind: "fixer", step: "S5" };
  }
  return { kind: "empty_continue_drift" };
}
