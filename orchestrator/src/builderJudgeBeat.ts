/**
 * #1086 / ADR 0147 S6 — every builder↔judge beat lands a typed ledger row
 * and a progress line (拍别 + 判词终态). Crash resume continues from the last
 * committed beat; completed product beats are not re-dispatched.
 *
 * Runner never reads prose. This module projects only typed surfaces already
 * on ledger rows (coder `beat`, judge `status`) and normalises builder beat
 * stamps before durable write.
 *
 * Consumers (audit):
 * - runner.ts — stamp on product write + emitBeatProgress
 * - progressBroadcast.ts — beat progress event shape + status rotation
 * - planResume / crash-resume tests — completed beats are not re-run
 */

import {
  CODER_BEAT_CONSTRUCT,
  CODER_BEAT_PLAN,
  coderBeatFromOutput,
  type CoderBeatKind,
} from "./coderPlanPhase.js";
import type { JudgeVerdictStatus } from "./types.js";

// ─── beat roles / steps ──────────────────────────────────────────────────────

/** Builder product seats (S2 implement / S5 fixer). */
export type BuilderBeatStepId = "S2" | "S5";

/** Judge product seats (S3 first court / S6 re-adjudicate). */
export type JudgeBeatStepId = "S3" | "S6";

export type BeatProductStepId = BuilderBeatStepId | JudgeBeatStepId;

export type BeatRole = "builder" | "judge";

/**
 * Typed beat row — 拍别 + optional 判词终态. No prose.
 * `rotation` is 1-based among product beats (builder and judge interleaved).
 */
export interface BeatLedgerRow {
  readonly role: BeatRole;
  readonly step: BeatProductStepId;
  /** Builder only: plan | construct. */
  readonly beatKind?: CoderBeatKind;
  /** Judge only: tri-state terminal verdict. */
  readonly verdict?: JudgeVerdictStatus;
  readonly rotation: number;
}

export function isBuilderBeatStep(step: string): step is BuilderBeatStepId {
  return step === "S2" || step === "S5";
}

export function isJudgeBeatStep(step: string): step is JudgeBeatStepId {
  return step === "S3" || step === "S6";
}

export function isBeatProductStep(step: string): step is BeatProductStepId {
  return isBuilderBeatStep(step) || isJudgeBeatStep(step);
}

// ─── ledger projection ───────────────────────────────────────────────────────

type BeatCargoOutput = {
  readonly kind?: string;
  readonly beat?: string;
  readonly committed?: boolean;
  readonly commitsAdded?: number;
  readonly status?: string;
};

export type BeatLedgerEntry = {
  readonly step?: string;
  /** Pure bookkeeping rows (event, no product output) are not beats. */
  readonly event?: string;
  readonly output?: BeatCargoOutput;
};

const JUDGE_VERDICTS = new Set<string>([
  "continue",
  "converged",
  "escalate",
]);

function asJudgeVerdict(status: string | undefined): JudgeVerdictStatus | undefined {
  if (status !== undefined && JUDGE_VERDICTS.has(status)) {
    return status as JudgeVerdictStatus;
  }
  return undefined;
}

/**
 * Project one ledger entry into a typed beat row.
 * Bookkeeping-only rows (event marker without product output) are skipped.
 */
export function projectBeatFromEntry(
  entry: BeatLedgerEntry,
  rotation: number,
): BeatLedgerRow | undefined {
  if (entry.event != null && entry.output == null) return undefined;
  const step = entry.step;
  if (step === undefined || !isBeatProductStep(step)) return undefined;
  const output = entry.output;
  if (output === undefined) return undefined;

  if (isBuilderBeatStep(step) && output.kind === "coder") {
    return {
      role: "builder",
      step,
      beatKind: coderBeatFromOutput(output),
      rotation,
    };
  }
  if (isJudgeBeatStep(step) && output.kind === "judge") {
    const verdict = asJudgeVerdict(output.status);
    if (verdict === undefined) return undefined;
    return {
      role: "judge",
      step,
      verdict,
      rotation,
    };
  }
  return undefined;
}

/** All completed product beats in ledger order (sole resume / progress truth). */
export function projectCompletedBeats(
  ledger: ReadonlyArray<BeatLedgerEntry>,
): ReadonlyArray<BeatLedgerRow> {
  const out: BeatLedgerRow[] = [];
  for (const entry of ledger) {
    const beat = projectBeatFromEntry(entry, out.length + 1);
    if (beat !== undefined) out.push(beat);
  }
  return out;
}

/** Latest completed beat — operator rotation position. */
export function latestCompletedBeat(
  ledger: ReadonlyArray<BeatLedgerEntry>,
): BeatLedgerRow | undefined {
  const beats = projectCompletedBeats(ledger);
  return beats.length === 0 ? undefined : beats[beats.length - 1];
}

/**
 * Negative resume contract: a crash-resume next step must not equal the last
 * completed product beat step when that beat already finished (route successor
 * advances). Intentional same-step reopen (decision-answer resume) is not a
 * completed-beat re-run — callers pass `intentionalReopen: true` to exempt.
 *
 * Returns true when dispatching `nextStep` would re-burn a finished product beat.
 */
export function isCompletedBeatRerun(input: {
  readonly ledger: ReadonlyArray<BeatLedgerEntry>;
  readonly nextStep: string;
  /** Escalate-answer / decision reopen of the same step — not a re-run. */
  readonly intentionalReopen?: boolean;
}): boolean {
  if (input.intentionalReopen === true) return false;
  if (!isBeatProductStep(input.nextStep)) return false;
  const last = latestCompletedBeat(input.ledger);
  if (last === undefined) return false;
  return last.step === input.nextStep;
}

// ─── builder output stamp (durable 拍别) ─────────────────────────────────────

type CoderOut = {
  readonly kind: "coder";
  readonly committed: boolean;
  readonly commitsAdded: number;
  readonly beat?: CoderBeatKind;
  readonly planBody?: string;
  readonly refusedFindingIdentityKeys?: ReadonlyArray<string>;
  readonly refuseRecords?: ReadonlyArray<unknown>;
  readonly escalate?: { readonly reason: string; readonly diagnosis: string };
};

/**
 * Stamp typed builder 拍别 onto coder cargo before durable ledger write.
 *
 * - S5 fixer beats are always `construct` (post-construction repair).
 * - S2 uses cargo beat when present; otherwise commit activity ⇒ construct,
 *   else plan ({@link coderBeatFromOutput}).
 * - `forcePlan` forces structural first-wave plan (plan phase before any
 *   judge continue), matching {@link scanCoderPlanPhase} rules.
 */
export function stampBuilderBeatOnOutput<T extends CoderOut>(
  step: BuilderBeatStepId,
  output: T,
  opts?: { readonly forcePlan?: boolean },
): T & { readonly beat: CoderBeatKind } {
  const beat: CoderBeatKind =
    step === "S5"
      ? CODER_BEAT_CONSTRUCT
      : opts?.forcePlan === true
        ? CODER_BEAT_PLAN
        : coderBeatFromOutput(output);
  if (output.beat === beat) {
    return output as T & { readonly beat: CoderBeatKind };
  }
  return { ...output, beat };
}

/**
 * Whether the next S2 write is still structural first-wave plan (no judge
 * continue after a plan S2 yet). Used only to stamp durable 拍别; never routes.
 */
export function shouldForcePlanBeatStamp(
  ledger: ReadonlyArray<BeatLedgerEntry>,
): boolean {
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
  return !sawJudgeContinueAfterPlan;
}
