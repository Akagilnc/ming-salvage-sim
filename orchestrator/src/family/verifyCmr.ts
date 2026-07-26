/**
 * verify-cmr — the family verify + integrated-cmr HOOK seam (ADR 0022 decision
 * 3④/⑤/⑥, #293 seam 4).
 *
 * Production export is the real hook body (default for the family spine — not a
 * success no-op). The spine calls it at TWO points ADR 0022 decision 3 names —
 *   - the per-wave barrier (decision 3④: run family verify, typecheck + unit
 *     tests, fail-fast — a red wave aborts BEFORE 排下一波), and
 *   - after all waves merge (decision 3⑤/⑥: the end-of-run 全量 verify + the
 *     load-bearing integrated cross-model cmr that catches 跨片接缝; the native
 *     pipeline has zero review).
 * The `phase` field tells which of the two is running.
 *
 * Wave = verify fail-fast; final = full verify then ordered
 * completeness/correctness CMR courts, coder-fix on blocking findings, then
 * ship. #939: `runFamilyVerify` is a required capability (no success no-op).
 * Missing CMR/ship after a real verify fails-safe to stage-named red (not success).
 * Family court closure is the shared T2 judge tri-state; residual open-count is
 * boundary-only transport. Three-channel routing stays (exit / judge status /
 * decision gate) plus real infra durable abort.
 */

import type { FamilyModuleContext } from "./moduleDeclaration.js";
import { shWithClock } from "../externalCall.js";

import {
  isCanonicalGithubPrUrl,
  isLiveGithubReviewPollEnabled,
  pollPrReviewState,
} from "../botPolling.js";
import {
  recordLandingActionFailure,
  runLandingAction,
} from "./landing.js";
import {
  buildRoundTrigger,
  convergenceHeadToRecord,
  type RoundTrigger,
} from "../evidenceAdmissibility.js";
import {
  fixerWorkerSpec,
  verifyWorkerSpec,
} from "../dispatchWorker.js";
import {
  immediateBotPollClock,
  OnlineReviewLoopTerminal,
  lastFixMarkedFindingAuthorizationFromFamilyLedger,
  lastOnlineReviewFixCommitShaFromFamilyLedger,
  offlinePrReviewSnapshot,
  onlineReviewRoundFromFamilyLedger,
  onlineReviewRoundTriggerFromFamilyLedger,
  realBotPollClock,
  ensureOnlineReviewRetriggerAfterFixGap,
  retriggerBotsAndPoll,
  familyPendingRoundTriggerFromFixGap,
  resolveOnlineReviewRoundTrigger,
  runOnlineReviewLoopStage,
  shipLedgerTriggeredAtFromFamilyLedger,
  waitForBotQuiescence,
  type OnlineReviewLoopStageResult,
} from "./onlineReviewLoop.js";
import {
  mergePriorRoundFindings,
  priorCmrFindingsFromFamilyLedger,
  priorOnlineReviewFindingsFromFamilyLedger,
} from "../priorRoundFindings.js";
import { applyVerifySideEffects } from "../onlineReviewSideEffects.js";

import {
  familyCoderFixWorkerSpec,
  cmrWorkerSpec,
  dispatchFamilyWorker,
  familyShipWorkerSpec,
  waveVerifyJudgeWorkerSpec,
} from "./dispatchFamilyWorker.js";
import {
  admissibleDurablePanelLegEvidence,
  courtGenerationFromDurableEvidence,
  ensureFamilyCmrPanelEvidence,
  landedPanelLegEvidence,
} from "./reviewPanelLegs.js";
import { dispatchFamilyWorkerOrAbort as dispatchOrAbort } from "./familyProcessRootDispatch.js";
import {
  executeAdvanceCoderSuggestion,
  familyAdvanceCoderAuditFields,
  latestCoderAdvanceToSlug,
  type AdvanceRepairSeat,
} from "../advanceCoderEffect.js";
import { lookupCoderRosterEntry } from "../coderRoster.js";
import {
  applyRelayBatonToRoute,
  modelRouteFingerprint,
  resolveActiveModelRoute,
  routeSmokeFailure,
  smokeRouteModels,
  type ModelRouteSlot,
  type ResolvedModelRoute,
} from "../modelRoutes.js";
import {
  billingPoolForFamilyWorker,
  familyWorkerSlotForDispatch,
} from "./familyWorkerSlots.js";
import {
  modelFamilyForCmrReviewLeg,
  resumeCapableForSlug,
} from "../modelRegistry.js";
import { isRunnerSynthesizedFailureEscalation } from "../runnerEscalation.js";
import type {
  DispatchContext,
  EscalationAnswerPayload,
  Finding,
  ShipResult,
  ReviewFixRefuseRecord,
  VerifyResult,
  WorkerLandingPayload,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../types.js";
import { findingIdentityKey } from "../findings.js";
import {
  closeFamilyCourtFromJudgeOutput,
  familyJudgeResumeSessionIdFromPriorRows,
  priorFamilyJudgeVerdictRowsFromLedger,
  requireFixPacketBody,
} from "../judgeStation.js";
import { coderRefuseReverifyLanding } from "../coderRefuseExit.js";
import { emitJudgeProgress } from "../progressBroadcast.js";
import { hubNextFromFamilyClosureAction } from "../residentJudgeHub.js";
import {
  buildReviewRoundStamp,
  readTelemetryRecords,
  scheduleCommitTelemetry,
  tryAppendTelemetryRecord,
  type TelemetryReviewRoundRecord,
} from "../telemetry.js";
import {
  cmrBarrierPhaseOf,
  cmrPassAlreadyPassed,
  mechanicalRedispatchAttemptsFromFamilyLedger,
  pendingBuilderReviewFromFamilyLedger,
  residentJudgePanelReturnSessionIdFromFamilyLedger,
  recordAborted as recordDurableAbort,
  familyCoderFixResumeSessionIdFromLedger,
  recordCmrFixCommitted,
  recordCmrPassed,
  recordCmrReviewed,
  recordFamilyEscalated,
  recordOnlineReviewFixCommitted,
  recordOnlineReviewRoundRetrigger,
  recordReviewLoopConverged,
  recordShipped,
} from "./ledger.js";
// Stable re-export for existing test imports (#934 ID-004 budget walk).
export { mechanicalRedispatchAttemptsFromFamilyLedger };
import { isFilledString } from "../shipOutcome.js";
import {
  contractDriftStopSummary,
  decisionGateParkStopSummary,
  successStopSummary,
  type StopSummary,
} from "../stopSummary.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyErrorPackage,
  FamilyVerifyResult,
  IntegratedCmrPass,
  PanelLegEvidenceIdentity,
  PanelLegEvidenceIdentitySeed,
} from "./types.js";
import {
  stageFailureStopSummary,
  type FamilyStageFailureStatus,
} from "./familyTerminal.js";

// #919 F4: re-export slot helpers so existing import sites stay stable.
export { billingPoolForFamilyWorker, familyWorkerSlotForDispatch };

/**
 * Which family barrier is running:
 *   - `"wave"` — per-wave verify fail-fast (decision 3④)
 *   - `"correctness_checkpoint"` — #961 / ADR 0139 incremental Integrated
 *     Correctness after a Verification-green batch (correctness court only;
 *     full range still parent-base…target; no ship)
 *   - `"final"` — end-of-run full verify + completeness → correctness + ship
 */
export type VerifyCmrPhase = "wave" | "correctness_checkpoint" | "final";

export type { FamilyStageFailureStatus };

/**
 * The context the verify-cmr hook needs to do its (eventual #296) work.
 *
 * #293 passes it but ignores it (no-op). #296 reads `familyBase` to run verify in
 * the family base worktree and `familyBackend` to inspect the ledger; it surfaces
 * a red wave via the returned `ok` (the spine fails-fast on it). The `aborted`
 * ledger event itself is #298's schema (the seam's `status` is `"merged"`-only
 * today — see the `familyBackend` field note).
 */
export interface VerifyCmrInput {
  /** Wave barrier (decision 3④, fail-fast) vs end-of-run (decision 3⑤/⑥). */
  readonly phase: VerifyCmrPhase;
  /** The family base branch verify runs against / cmr reviews. */
  readonly familyBase: string;
  /**
   * Family seam: verify is required (#939). Missing CMR/ship after a real verify
   * fails-safe to a stage-named red gate (not a success no-op). The CONCRETE
   * `aborted`/escalate schema is #298's; #296 only CALLS those seams.
   */
  readonly familyBackend: FamilyBackend;
  /** Invocation-scoped telemetry identity minted by runFamily. */
  readonly runId?: string;
  /** The family-startup-smoked route carried into every family worker dispatch. */
  readonly modelRoute?: ResolvedModelRoute;
  /**
   * #686 / #909 — baton billing pool for re-dispatch after a family quota
   * relay. When set WITH {@link billingPoolSlots}, only wall-role workers on
   * those slots receive the pool (no barrier-wide sticky pollution of ship/etc).
   * When set alone (tests / explicit), applied unscoped.
   */
  readonly billingPool?: string;
  /**
   * Slot-scoped baton pool binding. When present with {@link billingPool},
   * only workers whose route slot is listed get the pool rewrite.
   */
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  /**
   * The child issue numbers whose merge into the family base was LLM-resolved
   * (#295), derived by the spine from the durable family ledger (#291 缺口 1). The
   * `"final"` phase forwards it to {@link IntegratedCmrRequest.llmResolvedChildren}
   * so the 承重闸 sees which merges a machine touched. Absent/empty ⇒ no LLM
   * resolution this run; the cmr request omits the field (the back-compat shape).
   */
  readonly llmResolvedChildren?: readonly number[];
  /** Human answer that reopened a prior family decision escalation (#439). */
  readonly escalationAnswer?: EscalationAnswerPayload;
  /**
   * The family base HEAD at the time the hook runs (#291 缺口 2), supplied by the
   * spine. On a RED barrier the hook forwards it onto BOTH the in-memory seam
   * {@link FamilyAbortedEvent.familyHeadAfter} AND the PHASE-LEVEL durable `aborted`
   * ledger entry's `familyHeadAfter`, so reconcile's "read末条 familyHeadAfter"
   * baseline covers an abort. Absent ⇒ no merge landed yet (a fresh run's first
   * barrier); the durable entry omits the head.
  */
  readonly familyHeadAfter?: string;
  /** Parent/family issue number, used for issue-specific accepted suppressions. */
  readonly familyIssue?: number;
  /** Parsed module declarations for family-CMR scope classification (#449). */
  readonly moduleContext?: FamilyModuleContext;
  /**
   * Runner-owned prior finding identity keys passed to the integrated CMR
   * worker as artifact pointers (ADR 0130 case handoff). #875 demolished the
   * verifyCmr accounting court: the runner does NOT parse claim/disposition
   * coverage of these keys to abort a live run. Three-channel routing only
   * (exit / judge status / decision gate), plus real infra durable abort.
   */
  readonly priorCmrFindingIdentityKeys?: readonly string[];
  /** Pass-scoped prior finding identity keys; preferred over the legacy flat set. */
  readonly priorCmrFindingIdentityKeysByPass?: Partial<
    Record<IntegratedCmrPass, readonly string[]>
  >;
}

/** The verify-cmr hook result. */
export interface VerifyCmrResult {
  /**
   * Whether the verify + cmr passed. The spine fails-fast when this is `false` at
   * the wave barrier (decision 3④) / returns the stage-named terminal at the final
   * barrier (#922), so #296 only RETURNS the verdict — it does not touch the spine.
   */
  readonly ok: boolean;
  /**
   * Whether any real verify/cmr work actually ran. Missing-capability fail-closed
   * paths still report `ran:true` with a stage-named `failedStatus` so the spine
   * never confuses absence with a green pass.
   */
  readonly ran: boolean;
  /**
   * #922 — which post-child stage died when `ok===false`. The family spine maps
   * this onto FamilyRunResult.status + stopSummary.reason (same token). Omitted
   * for decision-gate parks (barrier stopSummary.reason === decision_gate_park
   * → status escalated) and for bare test inject hooks (default verify_failed).
   */
  readonly failedStatus?: FamilyStageFailureStatus;
}

/** Stage-tagged red barrier result (#922 — no umbrella verify_failed mash). */
function stageGate(status: FamilyStageFailureStatus): VerifyCmrResult {
  return { ok: false, ran: true, failedStatus: status };
}

/**
 * #1002 / #1017 — rebuild one sticky repair seat from the latest successful
 * family-ledger `coder_advance` scoped to that seat (not stay_put, not the
 * other court). Online-review uses `fixer` (S10); CMR uses `coderFix` (S5).
 * Courts must not cross-bleed on process re-entry.
 */
function reholdRepairSeatFromFamilyLedger(
  route: ResolvedModelRoute,
  ledger: ReadonlyArray<{
    readonly event?: string;
    readonly status?: string;
    readonly toModelId?: string;
    readonly advanceSeat?: string;
  }>,
  seat: AdvanceRepairSeat,
  step: "S5" | "S10",
): { readonly route: ResolvedModelRoute; readonly reheldSlug?: string } {
  const advancedTo = latestCoderAdvanceToSlug(ledger, seat);
  if (advancedTo === undefined) return { route };
  const advanced = lookupCoderRosterEntry(advancedTo);
  const slug = advanced?.slug ?? advancedTo;
  if (route.slots[seat] === slug) return { route, reheldSlug: slug };
  return {
    route: applyRelayBatonToRoute(route, { slug }, step, { slots: [seat] }),
    reheldSlug: slug,
  };
}

// #1027 S2 / ADR 0145 — ledger workerStep tags for the wave-verify triage court
// (与 CMR 庭同构,不另立法: reuse worker_dispatched / aborted vocabulary).
const WAVE_VERIFY_JUDGE_STEP = "wave-verify-judge";
const WAVE_VERIFY_FIX_STEP = "wave-verify-fix";

/**
 * Shared fragment of the exit-path JUDGE_STEP converged receipt (ledger
 * observation only — not a crash-recover debt key).
 */
const WAVE_VERIFY_CONVERGED_RECEIPT_MARKER = "converged after";

function waveVerifyConvergedReason(label: string, round: number): string {
  return `${label} ${WAVE_VERIFY_CONVERGED_RECEIPT_MARKER} ${round} round(s)`;
}

/** Human-facing label for the verify-red judge court (scope is a parameter). */
function familyVerifyCourtLabel(phase: VerifyCmrPhase): string {
  if (phase === "correctness_checkpoint") return "correctness_checkpoint verify";
  if (phase === "final") return "final verify";
  return "wave verify";
}

/**
 * #1027 S2 / #1107 — record one family-verify barrier abort (in-memory
 * `recordAborted` + durable ledger) and return the stage-named red. One seam so
 * the toolchain terminal, the unusable/route-failure terminal, and the
 * fixer-failure terminal all record identically across wave / checkpoint / final
 * (mirrors the shared verify→court glue {@link runFamilyVerifyThroughCourt}).
 */
async function recordWaveVerifyAbort(input: {
  readonly phase: VerifyCmrPhase;
  readonly familyBase: string;
  readonly familyBackend: FamilyBackend;
  readonly familyHeadAfter?: string;
  readonly reason: string;
  readonly errorPackage?: FamilyVerifyErrorPackage;
  readonly stopSummary?: StopSummary;
}): Promise<VerifyCmrResult> {
  const { phase, familyBase, familyBackend, familyHeadAfter, reason } = input;
  await familyBackend.recordAborted?.({
    phase,
    familyBase,
    errorPackage: input.errorPackage ?? { reason },
    familyHeadAfter,
  });
  await recordDurableAbort(familyBackend, {
    phase,
    reason,
    familyHeadAfter,
    stopSummary: input.stopSummary ?? familyVerifyFailureStopSummary(reason),
  });
  return stageGate("verify_failed");
}

/**
 * #1027 S2 / #1107 — record a family-verify worker escalation (judge or fixer).
 * A runner-synthesized startup failure is stage death (`verify_failed`); a real
 * worker-authored decision-gate raise leaves `failedStatus` unset so the spine
 * escalates for a human answer (通道③ 转运). Mirrors the CMR court's split.
 */
async function recordWaveVerifyEscalation(input: {
  readonly phase: VerifyCmrPhase;
  readonly familyBackend: FamilyBackend;
  readonly familyHeadAfter?: string;
  readonly seat: "judge" | "fixer";
  readonly round: number;
  readonly reason: string;
  readonly diagnosis: string;
  readonly synthesizedFailure: boolean;
}): Promise<VerifyCmrResult> {
  const { phase, familyBackend, familyHeadAfter } = input;
  const label = familyVerifyCourtLabel(phase);
  const summary = `${label} ${input.seat} round ${input.round}: ${input.reason} — ${input.diagnosis}`;
  const heads =
    familyHeadAfter !== undefined ? { actualFamilyHead: familyHeadAfter } : {};
  const stopSummary = input.synthesizedFailure
    ? stageFailureStopSummary({
        status: "verify_failed",
        summary,
        repairHint: `repair the ${label} worker startup/authentication failure, then rerun the family barrier`,
        ...(Object.keys(heads).length > 0 ? { metadata: { heads } } : {}),
      })
    : decisionGateParkStopSummary({
        summary,
        repairHint: `answer the ${label} worker's decision gate, then resume it in place`,
        heads,
      });
  await familyBackend.escalateFamily?.({
    reason: input.reason,
    diagnosis: input.diagnosis,
    familyHeadAfter,
    stopSummary,
    escalationKind: input.synthesizedFailure ? "failure" : "decision",
    phase,
  });
  await recordDurableAbort(familyBackend, {
    phase,
    reason: summary,
    familyHeadAfter,
    stopSummary,
  });
  // Decision park → no failedStatus (spine escalates); synthesized → verify_failed.
  return input.synthesizedFailure
    ? stageGate("verify_failed")
    : { ok: false, ran: true };
}

/** One wave-verify coder-fix round outcome. */
interface WaveVerifyFixerOutcome {
  /** Set when the fixer round is a terminal (escalate / worker failure). */
  readonly terminal?: VerifyCmrResult;
  /** Live family HEAD after the fix (best-effort observation). */
  readonly familyHeadAfter?: string;
}

interface VerifyJudgeCourtResult extends VerifyCmrResult {
  readonly familyHeadAfter?: string;
}

/**
 * #1027 S2 / #1085 — dispatch ONE wave-verify coder-fix round with the
 * judge-authored repair packet (ADR 0138 verbatim body). Reuses the family
 * coder-fix seat (S5) + its discipline. A completed fix (including a legal
 * refuse) returns non-terminal so the caller resumes the resident judge hub
 * (ADR 0147) — green re-verify is the hard precondition on the *exit* path
 * only (ADR 0145), never a builder→exit skip of the judge.
 *
 * #1085 resume: same-court fixer rounds resume the prior fixer session when
 * the seat is resume-capable (isomorphic with CMR #979).
 */
async function runWaveVerifyFixerRound(input: {
  readonly phase: VerifyCmrPhase;
  readonly familyBase: string;
  readonly familyBackend: FamilyBackend;
  readonly runId?: string;
  readonly familyIssue?: number;
  readonly round: number;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  readonly escalationAnswer?: EscalationAnswerPayload;
  readonly fixPacketBody: string;
  readonly blockingFindingIdentityKeys: readonly string[];
  readonly blockingFindingCount?: number;
  readonly familyHeadBefore?: string;
  /** #1085 — prior wave-fixer session in this court (process-local resume). */
  readonly resumeSessionId?: string;
}): Promise<WaveVerifyFixerOutcome & { readonly sessionId?: string }> {
  const { phase, familyBase, familyBackend, runId, familyIssue, round } = input;
  const label = familyVerifyCourtLabel(phase);
  const fixPool = billingPoolForFamilyWorker({
    ...(input.billingPool !== undefined ? { billingPool: input.billingPool } : {}),
    ...(input.billingPoolSlots !== undefined
      ? { billingPoolSlots: input.billingPoolSlots }
      : {}),
    kind: "coder",
  });
  await familyBackend.appendFamilyLedger({
    status: "worker_dispatched",
    event: "worker_dispatched",
    workerStep: WAVE_VERIFY_FIX_STEP,
    reason: `${label} fixer round ${round}: dispatch coder-fix`,
  });
  const provisionalFixSpec = familyCoderFixWorkerSpec(input.resolvedRoute);
  const seatResumeCapable = resumeCapableForSlug(
    provisionalFixSpec.model,
    fixPool,
  );
  const resumeSessionId =
    typeof input.resumeSessionId === "string" &&
    input.resumeSessionId.length > 0 &&
    seatResumeCapable
      ? input.resumeSessionId
      : undefined;
  const coderFixSpec = familyCoderFixWorkerSpec(
    input.resolvedRoute,
    resumeSessionId !== undefined ? "resume" : "fresh",
  );
  const fixResult = await dispatchOrAbort(
    familyBackend,
    coderFixSpec,
    {
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      modelRoute: input.resolvedRoute,
      ...(fixPool !== undefined ? { billingPool: fixPool } : {}),
      ...(resumeSessionId !== undefined ? { resumeSessionId } : {}),
      blockingFindingIdentityKeys: input.blockingFindingIdentityKeys,
      ...(input.blockingFindingCount !== undefined
        ? { blockingFindingCount: input.blockingFindingCount }
        : {}),
      ...(input.escalationAnswer !== undefined
        ? { escalationAnswer: input.escalationAnswer }
        : {}),
      ...(familyIssue !== undefined ? { familyIssue } : {}),
    },
    { fixPacketBody: input.fixPacketBody },
  );
  const familyHeadAfter = await readPostCmrFamilyHead(
    familyBackend,
    familyBase,
    input.familyHeadBefore,
    "unknown",
  );
  const withHead = (terminal: VerifyCmrResult): WaveVerifyFixerOutcome => ({
    terminal,
    ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
  });

  const sessionId =
    typeof fixResult.sessionId === "string" && fixResult.sessionId.length > 0
      ? fixResult.sessionId
      : undefined;
  const withSession = (
    outcome: WaveVerifyFixerOutcome,
  ): WaveVerifyFixerOutcome & { readonly sessionId?: string } =>
    sessionId !== undefined ? { ...outcome, sessionId } : outcome;

  if (fixResult.kind === "escalated") {
    return withSession(
      withHead(
        await recordWaveVerifyEscalation({
          phase,
          familyBackend,
          ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
          seat: "fixer",
          round,
          reason: fixResult.escalation.reason,
          diagnosis: fixResult.escalation.diagnosis,
          synthesizedFailure: isRunnerSynthesizedFailureEscalation(
            fixResult.escalation,
          ),
        }),
      ),
    );
  }
  if (fixResult.kind !== "completed") {
    return withSession(
      withHead(
        await recordWaveVerifyAbort({
          phase,
          familyBase,
          familyBackend,
          ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
          reason: `${label} fixer worker failed at round ${round}: ${fixResult.reason}`,
        }),
      ),
    );
  }
  if (
    fixResult.output.kind === "coder" &&
    fixResult.output.escalate !== undefined
  ) {
    return withSession(
      withHead(
        await recordWaveVerifyEscalation({
          phase,
          familyBackend,
          ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
          seat: "fixer",
          round,
          reason: fixResult.output.escalate.reason,
          diagnosis: fixResult.output.escalate.diagnosis,
          synthesizedFailure: false,
        }),
      ),
    );
  }
  // #1085 / ADR 0147: completed builder beat always returns to the resident
  // judge hub — never exit on green alone. Caller resumes judge; ADR 0145
  // green hard-pre lives on the exit_loop path only.
  return withSession(
    familyHeadAfter !== undefined ? { familyHeadAfter } : {},
  );
}

/**
 * #1027 S2 / ADR 0145 / #1085 / #1107 — the family-verify triage judge court.
 *
 * Entered after a red family verify at ANY barrier scope (`wave` /
 * `correctness_checkpoint` / `final`). Owner 07-22: one mechanism, scope is a
 * parameter — not a layered second control shape. Owner FINAL 2026-07-20: the
 * runner does ZERO verify-kind classification — a red is handed uniformly to the
 * judge. Routing uses the **shared** resident-judge hub table
 * ({@link hubNextFromFamilyClosureAction}) — same language as per-slice and
 * integrated CMR. Each round:
 *   1. dispatch/resume the triage judge over the current verify failure;
 *   2. hub-route the typed verdict — `toolchain` → `verify_failed` (fixer
 *      zero-spin); `park`/`escalate` → decision-gate; `resume_builder` →
 *      judge-authored packet → family coder-fix; `exit_loop`/`pass` →
 *      deterministic re-verify (ADR 0145 green hard-pre);
 *   3. **after every builder beat** resume the same judge (ADR 0147 hub) —
 *      green re-verify never exits without the judge receive step;
 *   4. exit_loop + GREEN re-verify → close; RED forces another judge round.
 * Stuck detection is the resumed judge's call via round trend — no mechanical
 * runner round cap.
 */
async function runWaveVerifyJudgeCourt(input: {
  readonly phase: VerifyCmrPhase;
  readonly familyBase: string;
  readonly familyBackend: FamilyBackend;
  readonly familyHeadAfter?: string;
  readonly runId?: string;
  readonly familyIssue?: number;
  readonly modelRoute?: ResolvedModelRoute;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  readonly escalationAnswer?: EscalationAnswerPayload;
  readonly initialFailure: string;
}): Promise<VerifyJudgeCourtResult> {
  const { phase, familyBase, familyBackend, runId, familyIssue, escalationAnswer } =
    input;
  const label = familyVerifyCourtLabel(phase);

  // Resolve the dispatch route. Production family runs pass the startup-smoked
  // route; standalone unit tests predate that envelope, so smoke one here. A
  // route we cannot resolve is an infra failure → verify_failed (not a silent
  // pass, not a fixer spin).
  let resolvedRoute: ResolvedModelRoute;
  try {
    resolvedRoute =
      input.modelRoute ??
      (await smokeRouteModels(resolveActiveModelRoute(), async () => ({
        cliVersion: "standalone-wave-verify-test",
      })));
  } catch (err) {
    const reason = `${label} triage route failure: ${err instanceof Error ? err.message : String(err)}`;
    return await recordWaveVerifyAbort({
      phase,
      familyBase,
      familyBackend,
      ...(input.familyHeadAfter !== undefined
        ? { familyHeadAfter: input.familyHeadAfter }
        : {}),
      reason,
    });
  }

  const judgePool = billingPoolForFamilyWorker({
    ...(input.billingPool !== undefined ? { billingPool: input.billingPool } : {}),
    ...(input.billingPoolSlots !== undefined
      ? { billingPoolSlots: input.billingPoolSlots }
      : {}),
    kind: "cmr",
  });

  let failureReason = input.initialFailure;
  let greenReceipt: DispatchContext["waveVerifyReceipt"];
  let familyHeadBefore = input.familyHeadAfter;
  /** Process-local court session across builder beats in this court open. */
  let judgeSessionId: string | undefined;
  /** #1085 — resume same wave-fixer session across builder beats in this court. */
  let fixerSessionId: string | undefined;
  /**
   * #1085 F1: last post-builder (or exit-path) family-verify observation.
   * exit_loop reuses it as ADR 0145 green hard-pre when family HEAD is
   * unchanged across the judge resume (no second full-family verify).
   */
  let lastObserve: FamilyVerifyResult | undefined;
  let lastObserveFamilyHead: string | undefined;
  let round = 0;

  while (true) {
    round += 1;
    // ── dispatch/resume the triage judge over the current verify failure ──
    // Round receipt is written AFTER the judge returns (ledger observation).
    const judgeSpec = waveVerifyJudgeWorkerSpec(
      resolvedRoute,
      judgeSessionId !== undefined ? "resume" : "fresh",
    );
    const judgeResult = await dispatchOrAbort(familyBackend, judgeSpec, {
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      modelRoute: resolvedRoute,
      ...(judgePool !== undefined ? { billingPool: judgePool } : {}),
      ...(greenReceipt !== undefined
        ? { waveVerifyReceipt: greenReceipt }
        : { waveVerifyFailure: failureReason }),
      phase,
      ...(judgeSessionId !== undefined ? { resumeSessionId: judgeSessionId } : {}),
      ...(familyIssue !== undefined ? { familyIssue } : {}),
      ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
    });
    // Round receipt — durable only after the judge returned (any kind).
    await familyBackend.appendFamilyLedger({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: WAVE_VERIFY_JUDGE_STEP,
      reason: `${label} triage judge round ${round} for: ${failureReason}`,
    });
    const judgeHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      familyHeadBefore,
    );
    if (judgeResult.kind === "escalated") {
      return await recordWaveVerifyEscalation({
        phase,
        familyBackend,
        ...(judgeHead !== undefined ? { familyHeadAfter: judgeHead } : {}),
        seat: "judge",
        round,
        reason: judgeResult.escalation.reason,
        diagnosis: judgeResult.escalation.diagnosis,
        synthesizedFailure: isRunnerSynthesizedFailureEscalation(
          judgeResult.escalation,
        ),
      });
    }
    if (judgeResult.kind !== "completed") {
      return await recordWaveVerifyAbort({
        phase,
        familyBase,
        familyBackend,
        ...(judgeHead !== undefined ? { familyHeadAfter: judgeHead } : {}),
        reason: `${label} triage judge worker failed at round ${round}: ${judgeResult.reason}`,
      });
    }
    if (
      typeof judgeResult.sessionId === "string" &&
      judgeResult.sessionId.length > 0 &&
      resumeCapableForSlug(judgeSpec.model, judgePool)
    ) {
      judgeSessionId = judgeResult.sessionId;
    }

    const closure = closeFamilyCourtFromJudgeOutput(judgeResult.output);
    // #1085 / #1080: sole production edge source = shared hub table
    // (isomorphic with per-slice route.ts → routeResidentJudgeHub). Cargo
    // still narrows on closure.action after hubNext is known.
    const hubNext = hubNextFromFamilyClosureAction(
      closure.action,
      "wave_verify",
    );

    // ── toolchain: env red → verify_failed (fixer zero-spin, loud). ──
    if (hubNext === "toolchain") {
      if (closure.action !== "toolchain") {
        throw new Error(
          `${label}: hub toolchain without toolchain action (${closure.action})`,
        );
      }
      const reason = `${label} toolchain: ${closure.reason} — ${closure.diagnosis}`;
      return await recordWaveVerifyAbort({
        phase,
        familyBase,
        familyBackend,
        ...(judgeHead !== undefined ? { familyHeadAfter: judgeHead } : {}),
        reason,
        stopSummary: stageFailureStopSummary({
          status: "verify_failed",
          summary: reason,
          repairHint:
            "family judge classified this red as toolchain/environment " +
            "(not a cross-slice regression); fix the toolchain/dependency and " +
            "re-run — do not route through coder-fix",
        }),
      });
    }
    // ── park: decision-gate escalate. ──
    if (hubNext === "park") {
      if (closure.action !== "escalate") {
        throw new Error(
          `wave verify: hub park without escalate action (${closure.action})`,
        );
      }
      return await recordWaveVerifyEscalation({
        phase,
        familyBackend,
        ...(judgeHead !== undefined ? { familyHeadAfter: judgeHead } : {}),
        seat: "judge",
        round,
        reason: closure.reason,
        diagnosis: closure.diagnosis,
        synthesizedFailure: false,
      });
    }
    // ── fail_loud: unusable envelope (seat-side SO re-ask is official). ──
    if (hubNext === "fail_loud") {
      if (closure.action !== "unusable") {
        throw new Error(
          `${label}: hub fail_loud without unusable action (${closure.action})`,
        );
      }
      const reason = `${label} triage judge round ${round}: ${closure.reason}`;
      return await recordWaveVerifyAbort({
        phase,
        familyBase,
        familyBackend,
        ...(judgeHead !== undefined ? { familyHeadAfter: judgeHead } : {}),
        reason,
        stopSummary: stageFailureStopSummary({
          status: "verify_failed",
          summary: reason,
          repairHint:
            `unusable ${label} judge envelope after seat-side typed SO re-ask; ` +
            "re-open the same judge seat or repair the seat receipt contract — " +
            "do not route bad shape through coder-fix",
        }),
      });
    }

    // ── continue → resume_builder: judge-authored packet → coder-fix, then
    //    ALWAYS resume judge (ADR 0147). Green alone never exits past the hub. ──
    if (hubNext === "resume_builder") {
      if (closure.action !== "continue") {
        throw new Error(
          `wave verify: hub resume_builder without continue action (${closure.action})`,
        );
      }
      let fixPacketBody: string;
      try {
        fixPacketBody = requireFixPacketBody({
          status: "continue",
          fixPacketBody: closure.fixPacketBody,
        });
      } catch (err) {
        const reason =
          err instanceof Error
            ? err.message
            : `${label} judge continue missing fixPacketBody (ADR 0138)`;
        return await recordWaveVerifyAbort({
          phase,
          familyBase,
          familyBackend,
          ...(judgeHead !== undefined ? { familyHeadAfter: judgeHead } : {}),
          reason,
          stopSummary: stageFailureStopSummary({
            status: "verify_failed",
            summary: reason,
            repairHint:
              `${label} judge status:continue must author a non-empty fixPacketBody; ` +
              "runner transports it verbatim and will not pack bare findings",
          }),
        });
      }
      // ADR 0138: the judge-authored packet is the complete fixer control
      // cargo. Runner must not inspect disposition actions or manufacture a
      // second fixer scope from that table (ADR 0062 / 0131).
      const blockingIdentityKeys: readonly string[] = [];
      const fixOutcome = await runWaveVerifyFixerRound({
        phase,
        familyBase,
        familyBackend,
        ...(runId !== undefined ? { runId } : {}),
        ...(familyIssue !== undefined ? { familyIssue } : {}),
        round,
        resolvedRoute,
        ...(input.billingPool !== undefined ? { billingPool: input.billingPool } : {}),
        ...(input.billingPoolSlots !== undefined
          ? { billingPoolSlots: input.billingPoolSlots }
          : {}),
        ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
        fixPacketBody,
        blockingFindingIdentityKeys: blockingIdentityKeys,
        blockingFindingCount: blockingIdentityKeys.length,
        ...(familyHeadBefore !== undefined ? { familyHeadBefore } : {}),
        ...(fixerSessionId !== undefined ? { resumeSessionId: fixerSessionId } : {}),
      });
      if (fixOutcome.terminal !== undefined) return fixOutcome.terminal;
      if (fixOutcome.familyHeadAfter !== undefined) {
        familyHeadBefore = fixOutcome.familyHeadAfter;
      }
      if (
        typeof fixOutcome.sessionId === "string" &&
        fixOutcome.sessionId.length > 0
      ) {
        fixerSessionId = fixOutcome.sessionId;
      }
      // Observe re-verify for the next judge resume (fact, not exit authority).
      const reVerifyAfterFix: FamilyVerifyResult =
        await familyBackend.runFamilyVerify({
          phase,
          familyBase,
          ...(runId !== undefined ? { runId } : {}),
          ...(familyIssue !== undefined ? { issue: familyIssue } : {}),
        });
      lastObserve = reVerifyAfterFix;
      lastObserveFamilyHead = familyHeadBefore;
      if (reVerifyAfterFix.ok) {
        // Explicit typed receipt to the same resident judge (ADR 0145/0147).
        // Green is never rewritten into the red-failure channel.
        greenReceipt = { status: "green", phase };
      } else {
        greenReceipt = undefined;
        failureReason =
          reVerifyAfterFix.errorPackage?.reason ?? "family verify failed";
      }
      // ADR 0147: builder beat → resident judge (loop).
      continue;
    }

    // ── pass → exit_loop: ADR 0145 green hard-pre. GREEN → close;
    //    RED → force another judge round (even judge-converged cannot close).
    //    #1085: reuse last observe when HEAD unchanged (one full-family verify
    //    per convergence cycle — never double-run after a judge-only resume). ──
    if (hubNext === "exit_loop") {
      const headStable =
        lastObserve !== undefined &&
        lastObserveFamilyHead === familyHeadBefore;
      const reVerify: FamilyVerifyResult = headStable
        ? lastObserve!
        : await familyBackend.runFamilyVerify({
            phase,
            familyBase,
            ...(runId !== undefined ? { runId } : {}),
            ...(familyIssue !== undefined ? { issue: familyIssue } : {}),
          });
      if (!headStable) {
        lastObserve = reVerify;
        lastObserveFamilyHead = familyHeadBefore;
      }
      if (reVerify.ok) {
        await familyBackend.appendFamilyLedger({
          status: "worker_dispatched",
          event: "worker_dispatched",
          workerStep: WAVE_VERIFY_JUDGE_STEP,
          reason: waveVerifyConvergedReason(label, round),
          phase,
          ...(familyHeadBefore !== undefined
            ? { familyHeadAfter: familyHeadBefore }
            : {}),
        });
        return {
          ok: true,
          ran: true,
          ...(familyHeadBefore !== undefined
            ? { familyHeadAfter: familyHeadBefore }
            : {}),
        };
      }
      greenReceipt = undefined;
      failureReason = reVerify.errorPackage?.reason ?? "family verify failed";
      continue;
    }

    // Closed ResidentJudgeHubNext — compile-time exhaustiveness (no fallthrough).
    const _never: never = hubNext;
    throw new Error(
      `wave verify triage judge round ${round}: unhandled hub next ${String(_never)}`,
    );
  }
}

/**
 * #1107 / #1110 P1 — one verify→court glue for every family-verify call site
 * (entry barrier + mid-court after CMR fixer). Green verify returns ok immediately;
 * red enters the shared {@link runWaveVerifyJudgeCourt} (phase = scope). No second
 * isomorphic court; no hard-die bypass.
 */
async function runFamilyVerifyThroughCourt(input: {
  readonly phase: VerifyCmrPhase;
  readonly familyBase: string;
  readonly familyBackend: FamilyBackend;
  readonly familyHeadAfter?: string;
  readonly runId?: string;
  readonly familyIssue?: number;
  readonly modelRoute?: ResolvedModelRoute;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  readonly escalationAnswer?: EscalationAnswerPayload;
}): Promise<VerifyJudgeCourtResult> {
  const { phase, familyBase, familyBackend, familyHeadAfter, runId, familyIssue } =
    input;
  const verify: FamilyVerifyResult = await familyBackend.runFamilyVerify({
    phase,
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    ...(familyIssue !== undefined ? { issue: familyIssue } : {}),
  });
  if (verify.ok) {
    return {
      ok: true,
      ran: true,
      ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
    };
  }
  return await runWaveVerifyJudgeCourt({
    phase,
    familyBase,
    familyBackend,
    ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
    ...(runId !== undefined ? { runId } : {}),
    ...(familyIssue !== undefined ? { familyIssue } : {}),
    ...(input.modelRoute !== undefined ? { modelRoute: input.modelRoute } : {}),
    ...(input.billingPool !== undefined ? { billingPool: input.billingPool } : {}),
    ...(input.billingPoolSlots !== undefined
      ? { billingPoolSlots: input.billingPoolSlots }
      : {}),
    ...(input.escalationAnswer !== undefined
      ? { escalationAnswer: input.escalationAnswer }
      : {}),
    initialFailure: verify.errorPackage?.reason ?? "family verify failed",
  });
}

interface CmrRouteLegEvidence {
  readonly slug: string;
  readonly family?: string;
}

function cmrRouteLegEvidence(leg: unknown): CmrRouteLegEvidence | undefined {
  if (typeof leg === "string") {
    const slug = leg.trim();
    return slug.length > 0 ? { slug } : undefined;
  }
  if (leg === null || typeof leg !== "object") return undefined;
  const candidate = leg as { readonly slug?: unknown; readonly family?: unknown };
  const slug = typeof candidate.slug === "string" ? candidate.slug.trim() : "";
  if (slug.length === 0) return undefined;
  return {
    slug,
    ...(typeof candidate.family === "string"
      ? { family: candidate.family.trim().toLowerCase() }
      : {}),
  };
}

function providerForCmrLegSlug(slug: string): string | undefined {
  try {
    return modelFamilyForCmrReviewLeg(slug);
  } catch {
    return undefined;
  }
}

function skippedLegProviderDegradation(
  leg: { readonly slug: string; readonly reason: string },
  input: {
    readonly blocking: boolean;
    readonly repairHint: string;
  },
) {
  const provider = providerForCmrLegSlug(leg.slug);
  return {
    ...(provider !== undefined ? { provider } : {}),
    leg: leg.slug,
    reason: leg.reason,
    blocking: input.blocking,
    repairHint: input.repairHint,
  };
}

export function providerDegradedWorkerFailureStopSummary(input: {
  readonly reason: string;
  readonly resolvedRoute: ResolvedModelRoute;
}): StopSummary | undefined {
  if (
    !/\b(provider|auth|authentication|quota|rate limit|transport)\b/i.test(
      input.reason,
    )
  ) {
    return undefined;
  }
  const normalizedReason = input.reason.toLowerCase();
  const matchedLegs = input.resolvedRoute.legCollections.cmrReview
    .map((leg) => cmrRouteLegEvidence(leg))
    .filter((leg): leg is CmrRouteLegEvidence => {
      if (leg === undefined) return false;
      return (
        normalizedReason.includes(leg.slug.toLowerCase()) ||
        (leg.family !== undefined && normalizedReason.includes(leg.family))
      );
    });
  const providerDegraded =
    matchedLegs.length > 0
      ? matchedLegs.map((leg) => {
          const provider = providerForCmrLegSlug(leg.slug);
          return {
            ...(provider !== undefined ? { provider } : {}),
            leg: leg.slug,
            reason: input.reason,
            blocking: true,
            repairHint: `restore provider availability for ${leg.slug} and rerun the CMR gate`,
          };
        })
      : [
          {
            reason: input.reason,
            blocking: true,
            repairHint:
              "restore the failing CMR provider transport/auth/quota path and rerun the gate",
          },
        ];
  return {
    reason: "provider_degraded",
    summary: input.reason,
    repairHint:
      "restore provider authentication/quota/transport for the CMR worker and rerun",
    metadata: { providerDegraded },
  };
}

function cmrWorkerFailedStopSummary(input: {
  readonly reason: string;
  readonly resolvedRoute: ResolvedModelRoute;
}): StopSummary | undefined {
  const providerSummary = providerDegradedWorkerFailureStopSummary(input);
  if (providerSummary !== undefined) return providerSummary;
  if (
    /\b(MODULE_NOT_FOUND|Cannot find module|dependency|build|test|toolchain)\b/i.test(
      input.reason,
    )
  ) {
    return stageFailureStopSummary({
      status: "cmr_failed",
      summary: input.reason,
      repairHint:
        "install or restore the missing CMR worker dependency/runtime, rebuild if needed, then rerun the CMR gate",
    });
  }
  return undefined;
}

function providerDegradedPassStopSummary(input: {
  readonly familyHeadAfter?: string;
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
}): StopSummary | undefined {
  if (input.skippedLegs === undefined || input.skippedLegs.length === 0) {
    return undefined;
  }
  return successStopSummary({
    ...(input.familyHeadAfter !== undefined
      ? {
          heads: {
            verifiedCmrHead: input.familyHeadAfter,
            sources: { verifiedCmrHead: "cmr_passed ledger row" },
          },
        }
      : {}),
    providerDegraded: input.skippedLegs.map((leg) =>
      skippedLegProviderDegradation(leg, {
        blocking: false,
        repairHint: `restore provider availability for ${leg.slug} before making this leg required`,
      }),
    ),
  });
}

function shipWorkerFailedStopSummary(input: {
  readonly reason: string;
  readonly latestVerifiedCmrHead?: string;
  readonly currentFamilyHead?: string;
  readonly reportedFamilyHead?: string;
  readonly shipPrState: string;
}): StopSummary {
  return stageFailureStopSummary({
      status: "ship_failed",
    summary: input.reason,
    repairHint:
      "repair the family ship worker infrastructure/auth/toolchain failure and rerun the final family barrier",
    metadata: {
      ship: {
        ...(input.latestVerifiedCmrHead !== undefined
          ? { latestVerifiedCmrHead: input.latestVerifiedCmrHead }
          : {}),
        ...(input.currentFamilyHead !== undefined
          ? { currentFamilyHead: input.currentFamilyHead }
          : {}),
        ...(input.reportedFamilyHead !== undefined
          ? { reportedFamilyHead: input.reportedFamilyHead }
          : {}),
        shipPrState: input.shipPrState,
      },
      heads: {
        ...(input.currentFamilyHead !== undefined
          ? { actualFamilyHead: input.currentFamilyHead }
          : {}),
        ...(input.latestVerifiedCmrHead !== undefined
          ? { verifiedCmrHead: input.latestVerifiedCmrHead }
          : {}),
        sources: {
          actualFamilyHead: "family head after ship worker failure",
          verifiedCmrHead: "latest cmr_passed ledger row",
        },
      },
    },
  });
}

function familyCmrPassStopSummary(input: {
  readonly familyHeadAfter?: string;
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
}): StopSummary | undefined {
  const materialPassSummary = successStopSummary({
    ...(input.familyHeadAfter !== undefined
      ? {
          heads: {
            verifiedCmrHead: input.familyHeadAfter,
            sources: { verifiedCmrHead: "cmr_passed ledger row" },
          },
        }
      : {}),
    ...(input.skippedLegs !== undefined && input.skippedLegs.length > 0
      ? {
          providerDegraded: input.skippedLegs.map((leg) =>
            skippedLegProviderDegradation(leg, {
              blocking: false,
              repairHint: `restore provider availability for ${leg.slug} before making this leg required`,
            }),
          ),
        }
      : {}),
  });
  if (input.skippedLegs === undefined || input.skippedLegs.length === 0) {
    return providerDegradedPassStopSummary({
      familyHeadAfter: input.familyHeadAfter,
      skippedLegs: input.skippedLegs,
    });
  }
  return materialPassSummary;
}

function isMaterialCmrStopSummary(stopSummary: StopSummary): boolean {
  if (stopSummary.reason !== "success") return true;
  const metadata = stopSummary.metadata;
  return (
    (metadata?.acceptedSuppressions?.length ?? 0) > 0 ||
    (metadata?.providerDegraded?.length ?? 0) > 0
  );
}

function familyVerifyFailureStopSummary(reason: string): StopSummary {
  if (/MODULE_NOT_FOUND|Cannot find module/i.test(reason)) {
    return stageFailureStopSummary({
      status: "verify_failed",
      summary: reason,
      repairHint:
        "install or restore the missing verification dependency, rebuild if needed, then rerun family verify",
    });
  }
  return stageFailureStopSummary({
      status: "verify_failed",
    summary: reason,
    repairHint:
      "inspect the family verify failure, repair the failing toolchain command, and rerun",
  });
}

type RefusalStateByPass = Partial<
  Record<
    IntegratedCmrPass,
    {
      readonly keys?: readonly string[];
      readonly records?: readonly ReviewFixRefuseRecord[];
    }
  >
>;

interface IntegratedCmrPassOutcome {
  readonly result: VerifyCmrResult;
  readonly familyHeadAfter?: string;
  /** Resident judge accepted a builder beat; open the independent fresh gate. */
  readonly needsFreshOuterGate?: boolean;
  /**
   * #919 — sticky route after optional advanceCoder execution on continue.
   * Outer completeness/correctness loops assign this so the next court + fix
   * see the advanced coderFix seat (advance must not last only one dispatch).
   */
  readonly resolvedRoute?: ResolvedModelRoute;
  readonly restartFinalBarrier?: {
    readonly familyHeadAfter?: string;
    readonly priorCmrFindingIdentityKeysByPass: Partial<
      Record<IntegratedCmrPass, readonly string[]>
    >;
    /** Refuse traffic + opaque cargo travel as one pass-partitioned state. */
    readonly refusalStateByPass?: RefusalStateByPass;
  };
}

function coderFixFailureStopSummary(input: {
  readonly pass: IntegratedCmrPass;
  readonly reason: string;
  readonly familyHeadBefore?: string;
  readonly familyHeadAfter?: string;
}): StopSummary {
  return contractDriftStopSummary({
    summary: `integrated CMR ${input.pass} coder-fix failed: ${input.reason}`,
    repairHint:
      "repair the family CMR coder-fix worker contract, then rerun the family CMR gate",
    heads: {
      ...(input.familyHeadBefore !== undefined
        ? { reportedFamilyHead: input.familyHeadBefore }
        : {}),
      ...(input.familyHeadAfter !== undefined
        ? { actualFamilyHead: input.familyHeadAfter }
        : {}),
      sources: {
        reportedFamilyHead: "pre-coder-fix family head",
        actualFamilyHead: "post-coder-fix family head",
      },
    },
  });
}

async function runCmrCoderFix(input: {
  readonly pass: IntegratedCmrPass;
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId?: string;
  /** ADR 0138: sole coder-fix packet body (verbatim judge text). */
  readonly fixPacketBody: string;
  readonly blockingFindingCount?: number;
  readonly blockingFindingIdentityKeys: readonly string[];
  readonly rawReviewerArtifacts?: WorkerLandingPayload["rawReviewerArtifacts"];
  readonly familyHeadBefore?: string;
  readonly escalationAnswer?: EscalationAnswerPayload;
  readonly familyIssue?: number;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  readonly priorCmrFindingIdentityKeysByPass?: Partial<
    Record<IntegratedCmrPass, readonly string[]>
  >;
  /** #961 — ledger phase for durable rows (final vs correctness_checkpoint). */
  readonly ledgerPhase?: VerifyCmrPhase;
}): Promise<IntegratedCmrPassOutcome> {
  const {
    pass,
    familyBackend,
    familyBase,
    runId,
    fixPacketBody,
    blockingFindingCount,
    blockingFindingIdentityKeys,
    rawReviewerArtifacts,
    familyHeadBefore,
    escalationAnswer,
    familyIssue,
    resolvedRoute,
    billingPool,
    billingPoolSlots,
    priorCmrFindingIdentityKeysByPass,
    ledgerPhase: ledgerPhaseInput = "final",
  } = input;
  const ledgerPhase = cmrBarrierPhaseOf(ledgerPhaseInput);
  const reasonPrefix =
    `integrated cmr ${pass} coder-fix for ` +
    blockingFindingIdentityKeys.join(", ");

  const currentFamilyHeadBefore = familyHeadBefore;
  let telemetryFamilyHeadBefore = familyHeadBefore;
  // #979: same findings-chain fix rounds resume the prior fixer session
  // (ledger sole truth on cmr_fix_committed). Absent / incapable → fresh;
  // fixer soul「修法史先于动刀」is the testimony channel when fresh.
  const fixPool = billingPoolForFamilyWorker({
    ...(billingPool !== undefined ? { billingPool } : {}),
    ...(billingPoolSlots !== undefined ? { billingPoolSlots } : {}),
    kind: "coder",
  });
  const familyLedgerForFix = await familyBackend.readFamilyLedger();
  const ledgerResumeSessionId = familyCoderFixResumeSessionIdFromLedger(
    familyLedgerForFix,
    pass,
  );
  // Provisional seat model (pre-session-mode) so capability gate can decide.
  const provisionalFixSpec = familyCoderFixWorkerSpec(resolvedRoute);
  const seatResumeCapable = resumeCapableForSlug(
    provisionalFixSpec.model,
    fixPool,
  );
  const resumeSessionId =
    typeof ledgerResumeSessionId === "string" && seatResumeCapable
      ? ledgerResumeSessionId
      : undefined;
  const coderFixSpec = familyCoderFixWorkerSpec(
    resolvedRoute,
    resumeSessionId !== undefined ? "resume" : "fresh",
  );
  const fixResult = await dispatchOrAbort(
    familyBackend,
    coderFixSpec,
    {
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      modelRoute: resolvedRoute,
      ...(fixPool !== undefined ? { billingPool: fixPool } : {}),
      // #979: thread prior same-chain fixer session when resume-capable.
      ...(resumeSessionId !== undefined ? { resumeSessionId } : {}),
      // 信封宪法 (ADR 0062): only identity keys + count on the dispatch structure;
      // ADR 0138 packet body travels in the separate landing payload below.
      blockingFindingIdentityKeys,
      ...(blockingFindingCount !== undefined ? { blockingFindingCount } : {}),
      ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
      ...(familyIssue !== undefined ? { familyIssue } : {}),
    },
    {
      fixPacketBody,
      ...(rawReviewerArtifacts !== undefined ? { rawReviewerArtifacts } : {}),
    },
  );
  // #878: observation failure must surface as unknown, never as a false
  // "head stuck" signal. Falling back to the pre-fix head would make
  // before===after and spin the fix redispatch forever.
  const familyHeadAfter = await readPostCmrFamilyHead(
    familyBackend,
    familyBase,
    currentFamilyHeadBefore,
    "unknown",
  );

  // Commit telemetry follows the independently observed family HEAD, never
  // the coder's self-report. The report remains for the repair gate below.
  if (
    telemetryFamilyHeadBefore !== undefined &&
    familyHeadAfter !== undefined &&
    familyHeadAfter !== telemetryFamilyHeadBefore
  ) {
    stampCmrCoderFixCommits({
      familyBackend,
      familyBase,
      runId,
      familyIssue,
      worker: { stepId: coderFixSpec.id, modelSlug: coderFixSpec.model },
      before: telemetryFamilyHeadBefore,
      after: familyHeadAfter,
    });
    telemetryFamilyHeadBefore = familyHeadAfter;
  }

  if (fixResult.kind === "escalated") {
    const reason = fixResult.escalation.reason;
    const diagnosis = fixResult.escalation.diagnosis;
    const synthesizedFailure = isRunnerSynthesizedFailureEscalation(
      fixResult.escalation,
    );
    const heads = {
      ...(familyHeadAfter !== undefined ? { actualFamilyHead: familyHeadAfter } : {}),
      ...(currentFamilyHeadBefore !== undefined
        ? { verifiedCmrHead: currentFamilyHeadBefore }
        : {}),
    };
    const stopSummary = synthesizedFailure
      ? stageFailureStopSummary({
      status: "cmr_failed",
          summary: `${reason} — ${diagnosis}`,
          repairHint:
            "repair the coder-fix worker startup/authentication failure, then re-feed the family run",
          ...(Object.keys(heads).length > 0 ? { metadata: { heads } } : {}),
        })
      : decisionGateParkStopSummary({
          summary: `${reason} — ${diagnosis}`,
          repairHint: "answer the coder-fix worker's decision gate, then resume it in place",
          heads,
        });
    await familyBackend.escalateFamily?.({
      reason,
      diagnosis,
      familyHeadAfter,
      stopSummary,
      escalationKind: synthesizedFailure ? "failure" : "decision",
      phase: ledgerPhase,
    });
    await recordDurableAbort(familyBackend, {
      phase: ledgerPhase,
      cmrPass: pass,
      reason,
      familyHeadAfter,
      stopSummary,
    });
    // Decision park → no failedStatus (spine → escalated); hard fail → cmr_failed.
    return {
      result: synthesizedFailure
        ? stageGate("cmr_failed")
        : { ok: false, ran: true },
      familyHeadAfter,
    };
  }

  if (fixResult.kind !== "completed") {
    const reason = `${reasonPrefix} failed: ${fixResult.reason}`;
    await recordDurableAbort(familyBackend, {
      phase: ledgerPhase,
      cmrPass: pass,
      reason,
      familyHeadAfter,
      stopSummary: coderFixFailureStopSummary({
        pass,
        reason,
        familyHeadBefore: currentFamilyHeadBefore,
        familyHeadAfter,
      }),
    });
    return { result: stageGate("cmr_failed"), familyHeadAfter };
  }

  // #979 CR R1 S1: one pack site class-wide (mirror openedJudgeSessionId).
  // Prefer provider-surfaced id; else keep the ledger-derived resume id so a
  // silent-complete resume still re-records the same-chain session.
  const openedFixerSessionId =
    typeof fixResult.sessionId === "string" && fixResult.sessionId.length > 0
      ? fixResult.sessionId
      : resumeSessionId;

  if (fixResult.output.kind !== "coder") {
    return completeCmrFixHandoff({
      familyBackend,
      pass,
      ledgerPhase,
      resolvedRoute,
      familyHeadBefore: currentFamilyHeadBefore,
      familyHeadAfter,
      blockingFindingIdentityKeys,
      reason: `${reasonPrefix}: completed coder receipt carried another shape; family judge will re-open on the diff`,
      priorCmrFindingIdentityKeysByPass,
      ...(openedFixerSessionId !== undefined
        ? { sessionId: openedFixerSessionId }
        : {}),
    });
  }

  if (fixResult.output.escalate !== undefined) {
    const reason = fixResult.output.escalate.reason;
    const diagnosis = fixResult.output.escalate.diagnosis;
    const stopSummary = decisionGateParkStopSummary({
      summary: `${reason} — ${diagnosis}`,
      repairHint: "answer the coder-fix worker's decision gate, then resume it in place",
      heads: {
        ...(familyHeadAfter !== undefined ? { actualFamilyHead: familyHeadAfter } : {}),
        ...(currentFamilyHeadBefore !== undefined
          ? { verifiedCmrHead: currentFamilyHeadBefore }
          : {}),
      },
    });
    await familyBackend.escalateFamily?.({
      reason,
      diagnosis,
      familyHeadAfter,
      stopSummary,
      escalationKind: "decision",
      phase: ledgerPhase,
    });
    await recordDurableAbort(familyBackend, {
      phase: ledgerPhase,
      cmrPass: pass,
      reason,
      familyHeadAfter,
      stopSummary,
    });
    // Decision gate park — leave failedStatus unset so the spine escalates.
    return { result: { ok: false, ran: true }, familyHeadAfter };
  }

  // #930 / #919 M1+R2: legal refuse is a completion, not a terminal / idle death —
  // blind-route keys + opaque refuseRecords cargo back to the family judge
  // (same contract as single-slice {@link coderRefuseReverifyLanding}).
  const refuseLanding = coderRefuseReverifyLanding(fixResult.output);
  const refusedFindingIdentityKeys = refuseLanding.refusedFindingIdentityKeys;
  const refuseRecords = refuseLanding.refuseRecords;

  return completeCmrFixHandoff({
    familyBackend,
    pass,
    ledgerPhase,
    resolvedRoute,
    familyHeadBefore: currentFamilyHeadBefore,
    familyHeadAfter,
    blockingFindingIdentityKeys,
    reason:
      refusedFindingIdentityKeys.length > 0
        ? `${reasonPrefix}: coder-fix refused ${refusedFindingIdentityKeys.length} finding(s); family judge will re-rule`
        : // Keep "fresh reviewer will judge findings" phrasing for ledger grep stability
          // while the re-open is the same family judge court (#930).
          `${reasonPrefix}: coder-fix completed; fresh reviewer will judge findings`,
    ...(openedFixerSessionId !== undefined
      ? { sessionId: openedFixerSessionId }
      : {}),
    // #1119: durable refuse cargo on the same fix row (cold restart truth).
    ...(refusedFindingIdentityKeys.length > 0
      ? { refusedFindingIdentityKeys }
      : {}),
    ...(refuseRecords !== undefined && refuseRecords.length > 0
      ? { refuseRecords }
      : {}),
    priorCmrFindingIdentityKeysByPass,
  });
}

/**
 * Commit the structured fixer boundary, then write its evidence tombstone.
 * The generation is reserved in the ledger first, making the two-write crash
 * window fail-safe on cold recovery.
 */
async function completeCmrFixHandoff(input: {
  readonly familyBackend: FamilyBackend;
  readonly pass: IntegratedCmrPass;
  readonly ledgerPhase: "final" | "correctness_checkpoint";
  readonly resolvedRoute: ResolvedModelRoute;
  readonly familyHeadBefore?: string;
  readonly familyHeadAfter?: string;
  readonly blockingFindingIdentityKeys: readonly string[];
  readonly reason: string;
  readonly sessionId?: string;
  readonly refusedFindingIdentityKeys?: readonly string[];
  readonly refuseRecords?: readonly ReviewFixRefuseRecord[];
  readonly priorCmrFindingIdentityKeysByPass?: Partial<
    Record<IntegratedCmrPass, readonly string[]>
  >;
}): Promise<IntegratedCmrPassOutcome> {
  const priorEvidence =
    typeof input.familyBackend.readFamilyPanelLegEvidence === "function"
      ? await input.familyBackend.readFamilyPanelLegEvidence(input.pass)
      : undefined;
  const expectedCourtGeneration =
    courtGenerationFromDurableEvidence(priorEvidence) + 1;
  await recordCmrFixCommitted(input.familyBackend, {
    cmrPass: input.pass,
    phase: input.ledgerPhase,
    familyHeadBefore: input.familyHeadBefore,
    familyHeadAfter: input.familyHeadAfter,
    blockingFindingIdentityKeys: input.blockingFindingIdentityKeys,
    reason: input.reason,
    expectedCourtGeneration,
    ...(input.sessionId !== undefined ? { sessionId: input.sessionId } : {}),
    ...(input.refusedFindingIdentityKeys !== undefined &&
    input.refusedFindingIdentityKeys.length > 0
      ? { refusedFindingIdentityKeys: input.refusedFindingIdentityKeys }
      : {}),
    ...(input.refuseRecords !== undefined && input.refuseRecords.length > 0
      ? { refuseRecords: input.refuseRecords }
      : {}),
  });
  await invalidatePanelEvidenceAfterBuilderBeat({
    familyBackend: input.familyBackend,
    pass: input.pass,
    expectedCourtGeneration,
    identity: {
      ledgerPhase: input.ledgerPhase,
      routeFingerprint: modelRouteFingerprint(input.resolvedRoute),
      familyHeadAfter: input.familyHeadAfter,
    },
  });
  return {
    result: { ok: true, ran: true },
    familyHeadAfter: input.familyHeadAfter,
    restartFinalBarrier: {
      familyHeadAfter: input.familyHeadAfter,
      priorCmrFindingIdentityKeysByPass:
        input.priorCmrFindingIdentityKeysByPass ?? {},
      ...(input.refusedFindingIdentityKeys !== undefined ||
      input.refuseRecords !== undefined
        ? {
            refusalStateByPass: {
              [input.pass]: {
                ...(input.refusedFindingIdentityKeys !== undefined
                  ? { keys: input.refusedFindingIdentityKeys }
                  : {}),
                ...(input.refuseRecords !== undefined
                  ? { records: input.refuseRecords }
                  : {}),
              },
            },
          }
        : {}),
    },
  };
}

/** Write the exact generation already reserved by cmr_fix_committed. */
async function invalidatePanelEvidenceAfterBuilderBeat(input: {
  readonly familyBackend: FamilyBackend;
  readonly pass: IntegratedCmrPass;
  readonly expectedCourtGeneration: number;
  readonly identity: PanelLegEvidenceIdentitySeed;
}): Promise<void> {
  const {
    familyBackend,
    pass,
    identity,
    expectedCourtGeneration,
  } = input;
  if (typeof familyBackend.readFamilyPanelLegEvidence !== "function") return;
  if (typeof familyBackend.writeFamilyPanelLegEvidence !== "function") return;
  const prior = await familyBackend.readFamilyPanelLegEvidence(pass);
  const familyHeadAfter =
    typeof identity.familyHeadAfter === "string" &&
    identity.familyHeadAfter.trim().length > 0
      ? identity.familyHeadAfter.trim()
      : typeof prior?.familyHeadAfter === "string" &&
          prior.familyHeadAfter.trim().length > 0
        ? prior.familyHeadAfter.trim()
        : undefined;
  // Idempotent: always write tombstone without transports (never leave stale
  // paper when invalidation runs after a successful fix-row append).
  await familyBackend.writeFamilyPanelLegEvidence(pass, {
    ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
    ledgerPhase: identity.ledgerPhase,
    routeFingerprint: identity.routeFingerprint,
    courtGeneration: expectedCourtGeneration,
  });
}

async function readPostCmrFamilyHead(
  familyBackend: FamilyBackend,
  familyBase: string,
  fallbackHead: string | undefined,
  onObservationFailure: "fallback" | "unknown" = "fallback",
): Promise<string | undefined> {
  const unavailable = (): string | undefined =>
    onObservationFailure === "fallback" ? fallbackHead : undefined;
  if (familyBackend.readFamilyHead === undefined) return unavailable();
  try {
    const liveHead = (await familyBackend.readFamilyHead(familyBase)).trim();
    return liveHead.length > 0 ? liveHead : unavailable();
  } catch {
    return unavailable();
  }
}

async function readPostCmrTrackedStatus(
  familyBackend: FamilyBackend,
  familyBase: string,
): Promise<readonly string[]> {
  if (familyBackend.readFamilyTrackedStatus === undefined) return [];
  return (await familyBackend.readFamilyTrackedStatus(familyBase)).filter(
    (line) => line.trim().length > 0,
  );
}

async function readPostCmrCurrentHead(
  familyBackend: FamilyBackend,
): Promise<string | undefined> {
  if (familyBackend.readFamilyCurrentHead === undefined) return undefined;
  const liveHead = (await familyBackend.readFamilyCurrentHead()).trim();
  return liveHead.length > 0 ? liveHead : undefined;
}

/**
 * Post-CMR git observation helper (#876 / #853).
 *
 * Head position + tracked residue are **routing / advisory plumbing**, never a
 * capital crime. Mismatches are ledger-visible so operators can see them, but
 * the pass continues on the three channels (exit / judge status / decision
 * gate). Reader and ledger failures are also telemetry-only: git state never
 * decides whether a completed reviewer receipt is accepted.
 */
async function observePostCmrReviewerGitState(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly pass: IntegratedCmrPass;
  readonly expectedFamilyHead?: string;
  readonly familyHeadAfter?: string;
}): Promise<void> {
  const {
    familyBackend,
    familyBase,
    pass,
    expectedFamilyHead,
    familyHeadAfter,
  } = input;
  const recordObservation = async (reason: string): Promise<void> => {
    try {
      await familyBackend.appendFamilyLedger({
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: `cmr:${pass}`,
        reason,
      });
    } catch {
      // Advisory git observation must never alter reviewer fate.
    }
  };
  let currentHead: string | undefined;
  try {
    currentHead = await readPostCmrCurrentHead(familyBackend);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    await recordObservation(
      `integrated CMR ${pass} current HEAD telemetry unavailable: ${detail}`,
    );
  }
  if (
    currentHead !== undefined &&
    familyHeadAfter !== undefined &&
    currentHead !== familyHeadAfter
  ) {
    // #876: checkout ≠ family base is advisory routing telemetry, not conviction.
    await recordObservation(
      `integrated CMR ${pass} reviewer checked out a different HEAD: ` +
        `family base ${familyHeadAfter}, current HEAD ${currentHead}`,
    );
  }
  let trackedStatus: readonly string[];
  try {
    trackedStatus = await readPostCmrTrackedStatus(familyBackend, familyBase);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    trackedStatus = [];
    await recordObservation(
      `integrated CMR ${pass} tracked-status telemetry unavailable: ${detail}`,
    );
  }
  if (
    expectedFamilyHead !== undefined &&
    familyHeadAfter !== undefined &&
    familyHeadAfter !== expectedFamilyHead
  ) {
    // #876: family-base HEAD advancement is routing plumbing (diff scope for the
    // next pass / coder-fix), never a contract_drift death.
    await recordObservation(
      `integrated CMR ${pass} reviewer moved family HEAD: ` +
        `${expectedFamilyHead} -> ${familyHeadAfter}`,
    );
  }
  if (trackedStatus.length > 0) {
    const reason =
      `integrated CMR ${pass} reviewer left tracked changes: ` +
      trackedStatus.join("; ");
    await recordObservation(reason);
    // #853: reviewer edits are ordinary diff content. Preserve them for the
    // current round's normal finding/fix/re-review path; never abort or discard.
  }
}

async function readRequiredFamilyHead(
  familyBackend: FamilyBackend,
  familyBase: string,
): Promise<string | undefined> {
  if (familyBackend.readFamilyHead === undefined) return undefined;
  try {
    const liveHead = (await familyBackend.readFamilyHead(familyBase)).trim();
    return liveHead.length > 0 ? liveHead : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Re-read live family HEAD and key the convergence/abort marker via
 * {@link convergenceHeadToRecord}. Prefer an explicit post-fix SHA (ledger /
 * loop) when the live head reader is missing or returns the pre-fix ship head
 * (Cursor R12 medium).
 */
async function familyConvergenceMarkerHead(
  familyBackend: FamilyBackend,
  familyBase: string,
  shipHead: string,
  knownPostFixHead?: string,
): Promise<string> {
  const liveHead = await readRequiredFamilyHead(familyBackend, familyBase);
  // Prefer live tip when it advanced (post-doc S12 push or post-fix HEAD).
  // Preferring knownPostFixHead over liveHead left review_loop_converged keyed
  // to a pre-doc tip while the PR head moved — re-feed then missed the marker
  // and re-ran the full final barrier (#735 Codex R3 P2).
  const postFixHead =
    liveHead !== undefined && liveHead !== shipHead
      ? liveHead
      : knownPostFixHead !== undefined &&
          knownPostFixHead.length > 0 &&
          knownPostFixHead !== shipHead
        ? knownPostFixHead
        : undefined;
  return (
    convergenceHeadToRecord({
      shipHead,
      postFixHead,
    }) ??
    liveHead ??
    knownPostFixHead ??
    shipHead
  );
}

/**
 * Dispatch a family worker, converting ANY thrown STARTUP error into a documented
 * gate result instead of letting it escape verifyCmr (cmr S336 r8 — startup/error
 * path audit). A family worker that throws on
 * startup — a missing-auth `sc.run` start failure (now preflighted to a structured
 * escalate, but the worker ALSO `git checkout`s the family base + writes the focus
 * file + spins docker, any of which can still throw) — would propagate out of
 * `runVerifyCmr` and reject the WHOLE family run, bypassing the stage-named
 * fail-safe the malformed / non-completed paths already use. So catch it and hand
 * back the discriminated `failed` WorkerResult; the caller records the abort after
 * re-reading the live family head, because a write-capable worker may have committed
 * before throwing. A NON-throwing dispatch is returned unchanged (escalated /
 * completed / malformed are handled by the callers).
 */
function familyOnlineReviewLoopFailureStopSummary(
  reviewLoop: OnlineReviewLoopStageResult,
): StopSummary {
  if (reviewLoop.stopSummary !== undefined) {
    // Keep decision parks answerable. Hard fails already carry the stage token
    // at source (#922); stageFailureStopSummary is idempotent restamp + defaults.
    if (reviewLoop.stopSummary.reason === "decision_gate_park") {
      return reviewLoop.stopSummary;
    }
    return stageFailureStopSummary({
      status: "online_review_failed",
      summary: reviewLoop.stopSummary.summary,
      repairHint: reviewLoop.stopSummary.repairHint,
      ...(reviewLoop.stopSummary.metadata !== undefined
        ? { metadata: reviewLoop.stopSummary.metadata }
        : {}),
    });
  }
  // #940: mechanical round-budget exhaust deleted; remaining non-success is
  // worker/judge disposition (decision_gate / online_review_failed).
  return stageFailureStopSummary({
      status: "online_review_failed",
    summary: `family online review loop did not converge (terminal: ${reviewLoop.terminalState})`,
    repairHint: "resolve remaining online review findings or answer the decision gate",
  });
}

/**
 * Assignability smoke for family advanceCoder courts (online-review fixer /
 * integrated CMR coderFix). Fail → stay_put via executeAdvanceCoderSuggestion;
 * never terminal. Shared to avoid twin probe bodies (#919 / #1002 DRY).
 */
async function probeFamilyAdvanceRoute(
  candidate: ResolvedModelRoute,
  cliVersion: string,
): Promise<
  | { readonly ok: true; readonly route: ResolvedModelRoute }
  | { readonly ok: false; readonly reason: string }
> {
  try {
    const smoked = await smokeRouteModels(candidate, async () => ({
      cliVersion,
    }));
    const failure = routeSmokeFailure(smoked);
    if (failure !== undefined) {
      return { ok: false, reason: failure };
    }
    return { ok: true, route: smoked };
  } catch (err) {
    return {
      ok: false,
      reason: err instanceof Error ? err.message : String(err),
    };
  }
}

export async function runFamilyOnlineReviewLoop(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId?: string;
  readonly ship: ShipResult;
  readonly resolvedRoute?: ResolvedModelRoute;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  readonly escalationAnswer?: EscalationAnswerPayload;
}): Promise<OnlineReviewLoopStageResult> {
  const repo =
    process.env.ORCHESTRATOR_REPO?.trim() ?? "Akagilnc/ming-salvage-sim";
  const prUrl = input.ship.pr;
  if (prUrl === undefined || prUrl.trim().length === 0) {
    return { ok: false, terminalState: "decision_gate_raised", round: 1 };
  }
  const ghSh = (file: string, args: string[]) =>
    shWithClock(file, args, { stage: `dispatch:${file}` });
  let modelRoute: ResolvedModelRoute;
  try {
    modelRoute =
      input.resolvedRoute ??
      (await smokeRouteModels(
        resolveActiveModelRoute(),
        async () => ({ cliVersion: "standalone-online-review-test" }),
      ));
  } catch (err) {
    return {
      ok: false,
      terminalState: "decision_gate_raised",
      round: 1,
      stopSummary: stageFailureStopSummary({
      status: "online_review_failed",
        summary: `family online-review route smoke failed: ${err instanceof Error ? err.message : String(err)}`,
        repairHint:
          "provide the family startup-smoked model route before dispatching online review workers",
      }),
    };
  }
  // F2: do not put sticky baton pool on baseCtx — each dispatch scopes by slot.
  // modelRoute is intentionally omitted here and injected per-dispatch so
  // #1002 advanceCoder sticky fixer rewrites are visible to the next seat.
  const baseCtx: DispatchContext = {
    familyBase: input.familyBase,
    ...(input.runId !== undefined ? { runId: input.runId } : {}),
    repo,
    prUrl,
    prHead: input.ship.prHead,
    ...(input.escalationAnswer !== undefined
      ? { escalationAnswer: input.escalationAnswer }
      : {}),
  };
  const poolForKind = (kind: WorkerSpec["kind"]): string | undefined =>
    billingPoolForFamilyWorker({
      ...(input.billingPool !== undefined
        ? { billingPool: input.billingPool }
        : {}),
      ...(input.billingPoolSlots !== undefined
        ? { billingPoolSlots: input.billingPoolSlots }
        : {}),
      kind,
    });

  /**
   * #1002 — online-review continue + advanceCoder rewrites the **fixer** repair
   * seat (same effect topology as CMR coderFix; never terminal).
   */
  const applyOnlineReviewAdvanceCoder = async (
    suggestion: string,
  ): Promise<void> => {
    const effect = await executeAdvanceCoderSuggestion({
      suggestion,
      currentSlug: modelRoute.slots.fixer,
      route: modelRoute,
      applySlug: (route, slug) =>
        applyRelayBatonToRoute(route, { slug }, "S10", { slots: ["fixer"] }),
      probe: (candidate) =>
        probeFamilyAdvanceRoute(candidate, "online-review-advance"),
    });
    modelRoute = effect.route;
    if (effect.kind === "stay_put" || effect.kind === "advanced") {
      await input.familyBackend.appendFamilyLedger({
        ...familyAdvanceCoderAuditFields(effect, suggestion, "fixer"),
      });
      console.info(
        effect.kind === "advanced"
          ? `[family] #1002 advanceCoder → ${effect.toSlug} ` +
              `(fixer) from ${effect.fromSlug}`
          : `[family] #1002 advanceCoder stay-put (${effect.reason}): ` +
              `kept ${modelRoute.slots.fixer}; suggestion=${effect.suggestion}`,
      );
    }
  };

  const livePoll = isLiveGithubReviewPollEnabled(prUrl, repo);
  const familyLedger = await input.familyBackend.readFamilyLedger();
  // #1002 / #1017 — rebuild sticky **fixer** from latest family ledger
  // coder_advance scoped to advanceSeat:"fixer" (not stay_put, not CMR
  // coderFix advances on the same ledger). Process re-entry keeps the
  // advanced online-review repair seat without re-suggestion.
  {
    const beforeFixer = modelRoute.slots.fixer;
    const reheld = reholdRepairSeatFromFamilyLedger(
      modelRoute,
      familyLedger,
      "fixer",
      "S10",
    );
    modelRoute = reheld.route;
    if (
      reheld.reheldSlug !== undefined &&
      beforeFixer !== reheld.reheldSlug
    ) {
      console.info(
        `[family] #1002 re-hold sticky fixer from ledger coder_advance → ${reheld.reheldSlug}`,
      );
    }
  }
  const shipTriggeredAt = shipLedgerTriggeredAtFromFamilyLedger(
    familyLedger,
    prUrl,
  );
  const loopState = {
    round: onlineReviewRoundFromFamilyLedger(familyLedger),
    lastFixSha: lastOnlineReviewFixCommitShaFromFamilyLedger(familyLedger),
  };
  const resumedFixAuthorization =
    lastFixMarkedFindingAuthorizationFromFamilyLedger(familyLedger);
  const pendingGapRetrigger = familyPendingRoundTriggerFromFixGap(familyLedger);
  let lastRoundTrigger: RoundTrigger;
  try {
    lastRoundTrigger = livePoll
      ? resolveOnlineReviewRoundTrigger({
          onlineReviewRound: loopState.round,
          persistedRoundTrigger:
            onlineReviewRoundTriggerFromFamilyLedger(familyLedger),
          pendingRetriggerFromFixGap: pendingGapRetrigger,
          fixCommitSha: loopState.lastFixSha,
          shipPrHead: input.ship.prHead,
          shipLedgerTriggeredAt: shipTriggeredAt,
        })
      : buildRoundTrigger(
          loopState.lastFixSha ??
            input.ship.prHead ??
            "offline-review-head",
          shipTriggeredAt,
        );
    if (livePoll && pendingGapRetrigger !== undefined) {
      const ensured = ensureOnlineReviewRetriggerAfterFixGap({
        sh: ghSh,
        repo,
        prUrl,
        gapTrigger: pendingGapRetrigger,
      });
      lastRoundTrigger = ensured.roundTrigger;
      await recordOnlineReviewRoundRetrigger(input.familyBackend, {
        roundTriggerHeadOid: ensured.roundTrigger.headOid,
        roundTriggerAt: ensured.roundTrigger.triggeredAt,
        onlineReviewRound: loopState.round,
        pr: prUrl,
      });
    }
  } catch (err) {
    // resolveOnlineReviewRoundTrigger / ensure may throw (round≥2 missing anchor).
    // In-band decision_gate — do not abort the whole family runner (Cursor medium,
    // verified: call was outside try previously).
    return {
      ok: false,
      terminalState: "decision_gate_raised",
      round: loopState.round,
      stopSummary: stageFailureStopSummary({
      status: "online_review_failed",
        summary: `family online review round-trigger setup failed: ${err instanceof Error ? err.message : String(err)}`,
        repairHint:
          "repair ledger round-trigger / fix-gap anchors and re-feed the family run",
      }),
    };
  }
  let familyLastFixCommitSha: string | undefined = loopState.lastFixSha;
  /** #711: last fixer landing's fix-marked keys for durable family ledger prior rounds. */
  let lastFixMarkedFindingIdentityKeys: ReadonlyArray<string> = [];
  let lastFixMarkedFindingThreads: ReadonlyArray<{
    readonly identityKey: string;
    readonly threadId: string;
  }> = [];
  let lastFixerOnlineReviewRound = loopState.round;

  try {
    return await runOnlineReviewLoopStage(
      input.ship,
      {
    poll: async (round) => {
      if (!livePoll) {
        return offlinePrReviewSnapshot({
          repo,
          prUrl,
          headOid:
            familyLastFixCommitSha ??
            input.ship.prHead ??
            "offline-review-head",
          pollCount: round,
        });
      }
      const snapshot = await waitForBotQuiescence(ghSh, {
        repo,
        prUrl,
        roundTrigger: lastRoundTrigger,
        clock:
          process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL === "1"
            ? immediateBotPollClock
            : realBotPollClock,
      });
      // Chain re-anchored trigger (online R5 Codex P1) — do not keep old triggeredAt.
      lastRoundTrigger = snapshot.roundTriggerUsed;
      return snapshot;
    },
    dispatchVerify: async (landing, round) => {
      let reviewerMonitorHandle: WorkerMonitorHandle | undefined;
      const verifyPool = poolForKind("verify");
      const result = await dispatchOrAbort(
        input.familyBackend,
        verifyWorkerSpec(modelRoute),
        {
          ...baseCtx,
          modelRoute,
          onlineReviewRound: round,
          ...(verifyPool !== undefined ? { billingPool: verifyPool } : {}),
        },
        landing,
        {
          onMonitorHandle: (handle) => {
            reviewerMonitorHandle = handle;
          },
        },
      );
      // Cursor R11 medium + self-check: escalated must park with decision_gate_park
      // + escalate payload text — not a bare decision_gate_raised that drops reason.
      if (result.kind === "escalated") {
        const escalationSummary = `family verify worker escalated: ${result.escalation.reason} — ${result.escalation.diagnosis}`;
        const stopSummary = isRunnerSynthesizedFailureEscalation(result.escalation)
          ? stageFailureStopSummary({
      status: "online_review_failed",
              summary: escalationSummary,
              repairHint:
                "repair the family verify worker startup/authentication failure, then re-feed the family online review loop",
            })
          : decisionGateParkStopSummary({
              summary: escalationSummary,
              repairHint:
                "answer the decision gate / unstick the verify worker, then re-feed the family online review loop",
            });
        throw new OnlineReviewLoopTerminal({
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary,
        });
      }
      if (result.kind !== "completed") {
        const detail = result.kind === "failed" ? `: ${result.reason}` : "";
        throw new OnlineReviewLoopTerminal({
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary: stageFailureStopSummary({
      status: "online_review_failed",
            summary: `family verify worker returned ${result.kind}${detail}`,
            repairHint:
              "inspect the verify worker envelope and re-feed the family online review loop",
          }),
        });
      }
      if (result.output.kind !== "verify") {
        return {
          kind: "rawReviewerArtifacts",
          artifacts: reviewerArtifactPointers(
            reviewerMonitorHandle,
            result.sessionId,
          ),
        };
      }
      // #1002: continue disposition + advanceCoder rewrites fixer before fix
      // dispatch (same never-terminal contract as CMR/single-slice courts).
      const verifyOut = result.output;
      if (
        !verifyOut.converged &&
        verifyOut.terminalState !== "decision_gate_raised" &&
        typeof verifyOut.advanceCoder === "string" &&
        verifyOut.advanceCoder.trim().length > 0
      ) {
        await applyOnlineReviewAdvanceCoder(verifyOut.advanceCoder);
      }
      return {
        kind: "rawReviewerArtifacts",
        artifacts: reviewerArtifactPointers(
          reviewerMonitorHandle,
          result.sessionId,
        ),
        verify: verifyOut,
      };
    },
    dispatchFixer: async (landing: WorkerLandingPayload) => {
      const round = landing.onlineReviewRound ?? baseCtx.onlineReviewRound ?? 1;
      lastFixMarkedFindingIdentityKeys =
        landing.fixMarkedFindingIdentityKeys ?? [];
      lastFixMarkedFindingThreads = landing.fixMarkedFindingThreads ?? [];
      lastFixerOnlineReviewRound = round;
      const fixerPool = poolForKind("fixer");
      const result = await dispatchOrAbort(
        input.familyBackend,
        fixerWorkerSpec(modelRoute),
        {
          ...baseCtx,
          modelRoute,
          ...(fixerPool !== undefined ? { billingPool: fixerPool } : {}),
        },
        landing,
      );
      if (result.kind === "escalated") {
        const escalationSummary = `family fixer worker escalated: ${result.escalation.reason} — ${result.escalation.diagnosis}`;
        throw new OnlineReviewLoopTerminal({
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary: isRunnerSynthesizedFailureEscalation(result.escalation)
            ? stageFailureStopSummary({
      status: "online_review_failed",
                summary: escalationSummary,
                repairHint:
                  "repair the family fixer worker startup/authentication failure, then re-feed the family online review loop",
              })
            : decisionGateParkStopSummary({
                summary: escalationSummary,
                repairHint:
                  "answer the decision gate / unstick the fixer worker, then re-feed the family online review loop",
              }),
        });
      }
      if (result.kind !== "completed") {
        const detail =
          result.kind === "failed"
            ? `: ${result.reason}`
            : "";
        throw new OnlineReviewLoopTerminal({
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary: stageFailureStopSummary({
      status: "online_review_failed",
            summary: `family fixer worker returned ${result.kind}${detail}`,
            repairHint:
              "inspect the fixer worker envelope and re-feed the family online review loop",
          }),
        });
      }
      return result.output.kind === "fixer" ? result.output : undefined;
    },
    // #941: landing Action owns docs/merge/close/cleanup after this loop
    // (no host dispatchDocRelease here).
    // Host fail-safe applicator (correctness K1): live poll path still applies
    // reply/resolve/deferred from verify cargo until workers truly own gh.
    // Offline synthetic poll has no live PR — pass cargo through unchanged.
    applySideEffects: (
      landing: WorkerLandingPayload,
      verify: VerifyResult,
      fixingCommitSha?: string,
    ) => {
      if (!livePoll) {
        return verify;
      }
      const applied = applyVerifySideEffects({
        sh: ghSh,
        repo,
        prUrl,
        verify,
        fixingCommitSha,
        landingThreads: landing.onlineReviewSnapshot?.threads,
        approvedFixMarkedFindingThreads: landing.fixMarkedFindingThreads,
      });
      return {
        ...verify,
        ...(applied.deferredIssueUrls.length > 0
          ? { deferredIssueUrls: applied.deferredIssueUrls }
          : {}),
      };
    },
    retriggerAfterFix: async () => {
      if (livePoll) {
        const retriggered = retriggerBotsAndPoll(
          ghSh,
          repo,
          prUrl,
          1,
          familyLastFixCommitSha ??
            lastRoundTrigger.headOid ??
            input.ship.prHead ??
            "offline-review-head",
        );
        lastRoundTrigger = retriggered.roundTrigger;
        const nextRound = loopState.round + 1;
        await recordOnlineReviewRoundRetrigger(input.familyBackend, {
          roundTriggerHeadOid: retriggered.roundTrigger.headOid,
          roundTriggerAt: retriggered.roundTrigger.triggeredAt,
          onlineReviewRound: nextRound,
          pr: prUrl,
        });
        loopState.round = nextRound;
      }
    },
    resolveFixCommitSha: async (envelopeFixSha: string) => {
      const sha = envelopeFixSha;
      familyLastFixCommitSha = sha;
      loopState.lastFixSha = sha;
      await recordOnlineReviewFixCommitted(input.familyBackend, {
        familyHeadAfter: sha,
        pr: prUrl,
        onlineReviewRound: lastFixerOnlineReviewRound,
        ...(lastFixMarkedFindingIdentityKeys.length > 0
          ? { fixMarkedFindingIdentityKeys: lastFixMarkedFindingIdentityKeys }
          : {}),
        ...(lastFixMarkedFindingThreads.length > 0
          ? { fixMarkedFindingThreads: lastFixMarkedFindingThreads }
          : {}),
      });
      return sha;
    },
  },
      {
        initialRound: loopState.round,
        ...(loopState.lastFixSha !== undefined
          ? { initialFixCommitSha: loopState.lastFixSha }
          : {}),
        initialFixMarkedFindingIdentityKeys:
          resumedFixAuthorization.fixMarkedFindingIdentityKeys,
        initialFixMarkedFindingThreads:
          resumedFixAuthorization.fixMarkedFindingThreads,
        enrichVerifyLanding: async (landing, round) => {
          // Merge ledger history with in-process accumulation — never either/or.
          // After mid-loop resume, in-process only has post-resume rounds; a
          // non-empty array must not skip ledger enrichment or r3 loses r1.
          const ledger = await input.familyBackend.readFamilyLedger();
          const fromLedger = priorOnlineReviewFindingsFromFamilyLedger(
            ledger,
            round,
          );
          const priorRoundFindings = mergePriorRoundFindings(
            fromLedger,
            landing.priorRoundFindings ?? [],
          );
          return priorRoundFindings.length > 0
            ? { ...landing, priorRoundFindings }
            : landing;
        },
      },
    );
  } catch (err) {
    if (err instanceof OnlineReviewLoopTerminal) {
      return err.result;
    }
    throw err;
  }
}

/**
 * #786 review-round dimension: observation only. Call this only from a terminal
 * runner classification branch, after its durable accept/reject outcome is known.
 * It intentionally has no return value, so telemetry I/O cannot change ADR 0062
 * gate decisions.
 */
function stampCmrReviewRound(input: {
  readonly familyBackend: FamilyBackend;
  readonly ctx: DispatchContext;
  readonly pass: IntegratedCmrPass;
  readonly familyIssue?: number;
  readonly result: WorkerResult;
  readonly finalDisposition: "accepted" | "rejected" | "unknown";
}): void {
  try {
    const ledgerDir = input.familyBackend.resolveTelemetryDir?.(input.ctx);
    if (ledgerDir === undefined || ledgerDir.length === 0) return;
    const priorReviewRecords = readTelemetryRecords(ledgerDir).filter(
      (record): record is TelemetryReviewRoundRecord =>
        record.phase === "review_round" && record.cmrPass === input.pass,
    );
    // #919 CR N3: production court traffic is kind:"judge" only. Residual
    // unusable is kind:"reviewer" ({@link unusableResidualOpenCountPaper}) —
    // never dual-read kind:"cmr" as a live verdict signal.
    const completed =
      input.result.kind === "completed" ? input.result.output : undefined;
    const judgeOut = completed?.kind === "judge" ? completed : undefined;
    const workerVerdict =
      input.result.kind === "escalated"
        ? "escalated"
        : input.result.kind === "failed"
          ? "failed"
          : judgeOut?.status === "converged"
            ? "converged"
            : judgeOut?.status === "continue"
              ? "blocking"
              : "not_converged";
    const findingsCargo = judgeOut?.findings;
    tryAppendTelemetryRecord(
      ledgerDir,
      buildReviewRoundStamp({
        runId: input.ctx.runId,
        issue: input.familyIssue ?? null,
        cmrPass: input.pass,
        reviewRound: priorReviewRecords.length + 1,
        verdict: workerVerdict,
        finalDisposition: input.finalDisposition,
        ...(findingsCargo !== undefined ? { findings: findingsCargo } : {}),
        priorReviewRecords,
      }),
    );
  } catch (err) {
    console.warn(
      `[orchestrator] review-round telemetry failed (fail-open): ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}

/**
 * #786 per-commit dimension: host-git observation after a coder-fix moved the
 * known family HEAD. It deliberately has no return value: telemetry cannot
 * affect ADR 0062 repair-gate or routing decisions.
 */
function stampCmrCoderFixCommits(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId?: string;
  readonly familyIssue?: number;
  readonly worker: { readonly stepId: string; readonly modelSlug: string };
  readonly before?: string;
  readonly after?: string;
}): void {
  try {
    if (input.before === undefined || input.after === undefined || input.before === input.after) return;
    const repoPath = input.familyBackend.resolveFamilyWorkingRepo?.();
    if (repoPath === undefined || repoPath.length === 0) return;
    const ctx: DispatchContext = {
      familyBase: input.familyBase,
      ...(input.runId !== undefined ? { runId: input.runId } : {}),
      ...(input.familyIssue !== undefined ? { familyIssue: input.familyIssue } : {}),
    };
    const ledgerDir = input.familyBackend.resolveTelemetryDir?.(ctx);
    if (ledgerDir === undefined || ledgerDir.length === 0) return;
    // Commit observation is strictly sidecar-only. Its git reads, full-file
    // scans, and JSONL append run after routing yields, through async I/O.
    void scheduleCommitTelemetry({
      ledgerDir,
      repoPath,
      runId: input.runId,
      issue: input.familyIssue ?? null,
      worker: input.worker,
      before: input.before,
      after: input.after,
    });
  } catch (err) {
    console.warn(
      `[orchestrator] commit telemetry failed (fail-open): ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}

function reviewerArtifactPointers(
  handle: WorkerMonitorHandle | undefined,
  sessionId: string | undefined,
): NonNullable<WorkerLandingPayload["rawReviewerArtifacts"]> {
  return {
    ...(handle?.logPath !== undefined ? { stdoutPath: handle.logPath } : {}),
    ...(handle?.resultPath !== undefined ? { sidecarPath: handle.resultPath } : {}),
    ...(sessionId !== undefined ? { reviewerSessionId: sessionId } : {}),
    statement: "the previous reviewer raw artifacts are here",
  };
}

async function runIntegratedCmrPass(input: {
  readonly pass: IntegratedCmrPass;
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId?: string;
  readonly llmResolvedChildren?: readonly number[];
  readonly escalationAnswer?: EscalationAnswerPayload;
  readonly familyHeadAfter?: string;
  readonly familyIssue?: number;
  readonly moduleContext?: FamilyModuleContext;
  readonly priorCmrFindingIdentityKeys?: readonly string[];
  readonly priorCmrFindingIdentityKeysByPass?: Partial<
    Record<IntegratedCmrPass, readonly string[]>
  >;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly allowCoderFix: boolean;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  /** #930 — refuse keys from prior coder-fix for judge re-ruling. */
  readonly refusedFindingIdentityKeys?: readonly string[];
  /**
   * #919 R2 / #927 — opaque refuseRecords cargo for judge re-open landing
   * (信封宪法: keys on thin ctx; cargo on landing only).
   */
  readonly refuseRecords?: readonly ReviewFixRefuseRecord[];
  /** #961 — which barrier owns this court (default final). */
  readonly ledgerPhase?: VerifyCmrPhase;
  /**
   * A durable final-phase fixer row re-opens this court even when an older
   * cmr_passed row can explain the current HEAD. Panel evidence is still
   * generation-bound and may be reused after a crash before the judge.
   */
  readonly forceCourtOpen?: boolean;
  /** Ledger-reserved generation for a pending post-fix court. */
  readonly expectedCourtGeneration?: number;
  /** Legacy pending fix row without a reserved generation rejects all old cargo. */
  readonly requireFreshPanelEvidence?: boolean;
  /** This open only delivers the builder beat to the resident judge. */
  readonly receiveBuilderBeat?: boolean;
  /** This open only delivers a human decision answer to the resident judge. */
  readonly receiveDecisionAnswer?: boolean;
}): Promise<IntegratedCmrPassOutcome> {
  const {
    pass,
    familyBackend,
    familyBase,
    runId,
    llmResolvedChildren,
    escalationAnswer,
    familyHeadAfter,
    familyIssue,
    moduleContext,
    resolvedRoute,
    billingPool,
    billingPoolSlots,
    priorCmrFindingIdentityKeys,
    priorCmrFindingIdentityKeysByPass,
    allowCoderFix,
    refusedFindingIdentityKeys,
    refuseRecords,
    ledgerPhase: ledgerPhaseInput = "final",
    forceCourtOpen = false,
    expectedCourtGeneration,
    requireFreshPanelEvidence = false,
    receiveBuilderBeat = false,
    receiveDecisionAnswer = false,
  } = input;
  const ledgerPhase = cmrBarrierPhaseOf(ledgerPhaseInput);
  const routeFingerprint = modelRouteFingerprint(resolvedRoute);
  const resolvedFamilyHeadAfter = await readPostCmrFamilyHead(
    familyBackend,
    familyBase,
    familyHeadAfter,
  );
  // Mutable seat route for this pass; advanced on continue before coder-fix.
  let activeRoute = resolvedRoute;

  if (
    !forceCourtOpen &&
    cmrPassAlreadyPassed(await familyBackend.readFamilyLedger(), {
      cmrPass: pass,
      familyHeadAfter: resolvedFamilyHeadAfter,
      routeFingerprint,
      // #982: checkpoint green must not free-skip final IC admission.
      phase: ledgerPhase,
    })
  ) {
    return {
      result: { ok: true, ran: true },
      familyHeadAfter: resolvedFamilyHeadAfter,
      resolvedRoute: activeRoute,
    };
  }
  // #966 / #930: resume sessionId is derived from family ledger court rows
  // (cmr_reviewed / cmr_passed) — sole truth, no process-local ByPass relay.
  // Absent sessionId → fresh open; priorJudgeVerdicts still land for trajectory
  // / session-loss recovery (same shape as single-slice #925).
  const familyLedger = await familyBackend.readFamilyLedger();
  const priorRoundFindings = priorCmrFindingsFromFamilyLedger(familyLedger, pass);
  const priorJudgeVerdicts = priorFamilyJudgeVerdictRowsFromLedger(
    familyLedger,
    pass,
  );
  const cmrPool = billingPoolForFamilyWorker({
    ...(billingPool !== undefined ? { billingPool } : {}),
    ...(billingPoolSlots !== undefined ? { billingPoolSlots } : {}),
    kind: "cmr",
    cmrPass: pass,
  });
  const ledgerResumeJudgeSessionId =
    familyJudgeResumeSessionIdFromPriorRows(priorJudgeVerdicts);
  const panelReturnJudgeSession =
    residentJudgePanelReturnSessionIdFromFamilyLedger(
      familyLedger,
      pass,
      ledgerPhase,
    );
  const provisionalSpec = cmrWorkerSpec("fresh", pass, resolvedRoute);
  const cmrJudgeSeatResumeCapable = resumeCapableForSlug(provisionalSpec.model, cmrPool);
  // Soul law: session lost / seat not resume-capable → fresh judge;
  // priorJudgeVerdicts still land above for trajectory / session-loss recovery
  // (same shape as single-slice #925). No fail-loud terminal.
  const resumeJudgeSessionId = cmrJudgeSeatResumeCapable
    ? panelReturnJudgeSession.pendingPanelReturn
      ? panelReturnJudgeSession.sessionId
      : ledgerResumeJudgeSessionId
    : undefined;
  const spec = cmrWorkerSpec(
    resumeJudgeSessionId !== undefined ? "resume" : "fresh",
    pass,
    resolvedRoute,
  );
  const dispatchCtx: DispatchContext = {
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    modelRoute: resolvedRoute,
    ...(cmrPool !== undefined ? { billingPool: cmrPool } : {}),
    cmrPass: pass,
    ...(resumeJudgeSessionId !== undefined
      ? { resumeSessionId: resumeJudgeSessionId }
      : {}),
    ...(llmResolvedChildren !== undefined && llmResolvedChildren.length > 0
      ? { llmResolvedChildren }
      : {}),
    ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
    ...(moduleContext !== undefined ? { moduleContext } : {}),
    ...(priorCmrFindingIdentityKeys !== undefined
      ? { priorCmrFindingIdentityKeys }
      : {}),
    ...(priorRoundFindings.length > 0 ? { priorRoundFindings } : {}),
    // Session-loss / trajectory: always land prior rows when present (same as
    // single-slice #925). Fresh opens after lost session rely on these alone.
    ...(priorJudgeVerdicts.length > 0
      ? { priorJudgeVerdicts }
      : {}),
    ...(refusedFindingIdentityKeys !== undefined &&
    refusedFindingIdentityKeys.length > 0
      ? { refusedFindingIdentityKeys }
      : {}),
  };
  // #919 M3 / #927 isomorphic: refuse traffic keys sole on thin dispatchCtx;
  // landing carries opaque refuseRecords cargo only (信封宪法 — no dual key write).
  const refuseReopenLanding: WorkerLandingPayload | undefined =
    refuseRecords !== undefined && refuseRecords.length > 0
      ? { refuseRecords }
      : undefined;
  // #1143 / ADR 0147: round identity is explicit typed cargo. Panel emptiness
  // (including a generation tombstone) must never masquerade as that identity.
  const courtLanding: WorkerLandingPayload | undefined = receiveBuilderBeat
    ? {
        ...(refuseReopenLanding ?? {}),
        builderBeat: "construct",
      }
    : refuseReopenLanding;
  const stampReviewRound = (
    result: WorkerResult,
    finalDisposition: "accepted" | "rejected" | "unknown",
  ): void => {
    stampCmrReviewRound({
      familyBackend,
      ctx: dispatchCtx,
      pass,
      familyIssue,
      result,
      finalDisposition,
    });
  };
  let reviewRoundResult: WorkerResult = {
    kind: "failed",
    reason: "integrated CMR review round exited before producing a worker result",
  };
  let finalReviewRoundDisposition: "accepted" | "rejected" | "unknown" =
    "unknown";
  const persistFinalReviewRound = async (
    disposition: "accepted" | "rejected",
    record: () => Promise<void>,
  ): Promise<void> => {
    await record();
    finalReviewRoundDisposition = disposition;
  };
  try {
    let reviewerMonitorHandle: WorkerMonitorHandle | undefined;
    // Panel evidence belongs to the independent outer gate. A builder beat first
    // reaches the resident judge with zero fan-out; only its typed verdict may
    // open this gate. Pure judge never spawns nested CLIs.
    const receiveResidentJudgeOnly =
      receiveBuilderBeat || receiveDecisionAnswer;
    const frozenLegs = receiveResidentJudgeOnly ? [] : (spec.cmrReviewLegs ?? []);
    // Existing landing/ctx transports (valid → no reburn). Cold resume after
    // park with empty landing forces fan-out again (AC #1118 / #1119).
    // Durable ledgerDir evidence is cold-start recoverable (process temps are not).
    // Full court identity (phase + route/leg fingerprint + generation + head) —
    // not HEAD-only — so checkpoint≠final, builder refuse/no-op, and roster
    // changes cannot silently reuse stale 卷面 (#1119 P1).
    const durablePanelEvidence =
      typeof familyBackend.readFamilyPanelLegEvidence === "function"
        ? await familyBackend.readFamilyPanelLegEvidence(pass)
        : undefined;
    const courtGeneration =
      expectedCourtGeneration ??
      courtGenerationFromDurableEvidence(durablePanelEvidence);
    const panelEvidenceIdentity: PanelLegEvidenceIdentity | undefined =
      resolvedFamilyHeadAfter !== undefined &&
      resolvedFamilyHeadAfter.trim().length > 0
        ? {
            familyHeadAfter: resolvedFamilyHeadAfter.trim(),
            ledgerPhase,
            routeFingerprint,
            courtGeneration,
          }
        : undefined;
    const durableEvidenceForCourt = requireFreshPanelEvidence
      ? undefined
      : admissibleDurablePanelLegEvidence(
          durablePanelEvidence,
          panelEvidenceIdentity,
        );
    const existingPanelEvidence = receiveBuilderBeat
      ? undefined
      : receiveDecisionAnswer
        ? durableEvidenceForCourt
        : (landedPanelLegEvidence(courtLanding) ??
        landedPanelLegEvidence(dispatchCtx) ??
        durableEvidenceForCourt);
    // #1094 F2: checkout + focus + shared exclude ONCE before fan-out; legs only clone.
    // Skip prep whenever either official cargo class already landed (no reburn).
    const willFanOut =
      frozenLegs.length > 0 &&
      existingPanelEvidence?.panelLegTransports === undefined &&
      existingPanelEvidence?.panelLegSkippedLegs === undefined;
    if (
      willFanOut &&
      typeof familyBackend.prepareFamilyCmrPanelRound === "function"
    ) {
      const prep = await familyBackend.prepareFamilyCmrPanelRound(dispatchCtx);
      if (
        prep !== undefined &&
        typeof prep === "object" &&
        "kind" in prep &&
        prep.kind === "escalate"
      ) {
        const reason = prep.reason;
        const diagnosis = prep.diagnosis;
        reviewRoundResult = {
          kind: "escalated",
          escalation: prep.escalation,
        };
        const stopSummary = stageFailureStopSummary({
          status: "cmr_failed",
          summary: `${reason} — ${diagnosis}`,
          repairHint:
            "repair the integrated CMR worker startup/configuration failure, then re-feed the family run",
        });
        await persistFinalReviewRound("accepted", async () => {
          await recordDurableAbort(familyBackend, {
            phase: ledgerPhase,
            cmrPass: pass,
            reason,
            stopSummary,
          });
          await familyBackend.escalateFamily?.({
            reason,
            diagnosis,
            stopSummary,
            escalationKind: "failure",
          });
        });
        return {
          result: stageGate("cmr_failed"),
          familyHeadAfter: resolvedFamilyHeadAfter,
          resolvedRoute: activeRoute,
        };
      }
    }
    const panelRound = await ensureFamilyCmrPanelEvidence({
      legs: frozenLegs,
      cmrPass: pass,
      ...(existingPanelEvidence !== undefined
        ? { existingEvidence: existingPanelEvidence }
        : {}),
      // #1094 R3 F2: legs must NOT inherit the judge's billingPool — that pool
      // binding is for the cmr court slot (quota relay). Cross-vendor panel
      // legs keep their own registry providers (or none).
      // #1117 / #1119: legs are always fresh — strip judge resumeSessionId so
      // panel fan-out never collides with the pure-court resume conversation.
      dispatch: (legSpec) => {
        // #1094 R3 F2: legs must NOT inherit the judge billingPool.
        // #1080 R3: panel legs are always fresh (cmrPanelLegWorkerSpec session:
        // "fresh") — strip the pure-court resumeSessionId so a transient leg
        // failure keeps its full process-root retry budget and is never
        // misclassified as a resident-judge resume (forbidFreshRetry).
        const {
          billingPool: _judgePool,
          resumeSessionId: _judgeResume,
          ...legDispatchCtx
        } = dispatchCtx;
        void _judgePool;
        void _judgeResume;
        return dispatchOrAbort(
          familyBackend,
          legSpec,
          legDispatchCtx,
          undefined,
          {
            onMonitorHandle: (handle) => {
              reviewerMonitorHandle = handle;
            },
          },
        );
      },
    });
    // Preserve producer-authored runtime skips verbatim. Transports-only cold
    // cargo stays transports-only; the host never reparses its prose.
    const hostSkippedLegs = panelRound.panelLegSkippedLegs;
    // Canonical landing cargo for transports + explicit producer skip reasons.
    const panelLanding: WorkerLandingPayload = {
      ...(courtLanding ?? {}),
      ...(panelRound.panelLegTransports !== undefined
        ? { panelLegTransports: panelRound.panelLegTransports }
        : {}),
      ...(hostSkippedLegs !== undefined && hostSkippedLegs.length > 0
        ? {
            panelLegSkippedLegs: hostSkippedLegs.map((leg) => ({
              slug: leg.slug,
              reason: leg.reason,
            })),
          }
        : {}),
    };
    // #1119: persist durable evidence under ledgerDir BEFORE any terminal so
    // cold re-entry can reuse valid 卷面 or observe runtime skip reasons.
    // Stamp full court identity so reuse cannot cross phase/roster/generation.
    if (
      panelEvidenceIdentity !== undefined &&
      typeof familyBackend.writeFamilyPanelLegEvidence === "function" &&
      (panelLanding.panelLegTransports !== undefined ||
        panelLanding.panelLegSkippedLegs !== undefined)
    ) {
      await familyBackend.writeFamilyPanelLegEvidence(pass, {
        ...panelEvidenceIdentity,
        ...(panelLanding.panelLegTransports !== undefined
          ? { panelLegTransports: panelLanding.panelLegTransports }
          : {}),
        ...(panelLanding.panelLegSkippedLegs !== undefined
          ? { panelLegSkippedLegs: panelLanding.panelLegSkippedLegs }
          : {}),
      });
    }
    // Land transports + host skip reasons so the pure court never sees a silent
    // empty fix-findings file (production deadlock: cold resume without evidence).
    const judgeDispatchCtx: DispatchContext = {
      ...dispatchCtx,
      panelLegTransports: panelLanding.panelLegTransports,
      ...(panelLanding.panelLegSkippedLegs !== undefined
        ? { panelLegSkippedLegs: panelLanding.panelLegSkippedLegs }
        : {}),
    };
    const cmrResult = await dispatchOrAbort(
      familyBackend,
      spec,
      judgeDispatchCtx,
      panelLanding,
      {
      onMonitorHandle: (handle) => {
        reviewerMonitorHandle = handle;
      },
    });
    reviewRoundResult = cmrResult;
  const postWorkerFamilyHead = await readPostCmrFamilyHead(
    familyBackend,
    familyBase,
    resolvedFamilyHeadAfter,
  );
  await observePostCmrReviewerGitState({
    familyBackend,
    familyBase,
    pass,
    expectedFamilyHead: resolvedFamilyHeadAfter,
    familyHeadAfter: postWorkerFamilyHead,
  });
  if (cmrResult.kind === "escalated") {
    const reason = cmrResult.escalation.reason;
    const diagnosis = cmrResult.escalation.diagnosis;
    const synthesizedFailure = isRunnerSynthesizedFailureEscalation(
      cmrResult.escalation,
    );
    const stopSummary = synthesizedFailure
      ? stageFailureStopSummary({
      status: "cmr_failed",
          summary: `${reason} — ${diagnosis}`,
          repairHint:
            "repair the integrated CMR worker startup/configuration failure, then re-feed the family run",
          ...(postWorkerFamilyHead !== undefined
            ? { metadata: { heads: { actualFamilyHead: postWorkerFamilyHead } } }
            : {}),
        })
      : decisionGateParkStopSummary({
          summary: `${reason} — ${diagnosis}`,
          repairHint: "answer the CMR worker's decision gate, then resume it in place",
          heads: postWorkerFamilyHead !== undefined
            ? { actualFamilyHead: postWorkerFamilyHead }
            : undefined,
        });
    await persistFinalReviewRound("accepted", async () => {
      await recordDurableAbort(familyBackend, {
        phase: ledgerPhase,
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        stopSummary,
      });
      await familyBackend.escalateFamily?.({
        reason,
        diagnosis,
        familyHeadAfter: postWorkerFamilyHead,
        stopSummary,
        escalationKind: synthesizedFailure ? "failure" : "decision",
      });
    });
    return {
      result: synthesizedFailure
        ? stageGate("cmr_failed")
        : { ok: false, ran: true },
      familyHeadAfter: postWorkerFamilyHead,
      resolvedRoute: activeRoute,
    };
  }
  if (cmrResult.kind !== "completed") {
    const reason = `family integrated cmr ${pass} worker failed: ${cmrResult.reason}`;
    const stopSummary = cmrResult.kind === "failed"
        ? cmrWorkerFailedStopSummary({
            reason,
            resolvedRoute,
          })
        : undefined;
    await persistFinalReviewRound("rejected", async () => {
      await familyBackend.recordAborted?.({
        phase: ledgerPhase,
        cmrPass: pass,
        familyBase,
        errorPackage: { reason },
        familyHeadAfter: postWorkerFamilyHead,
      });
      await recordDurableAbort(familyBackend, {
        phase: ledgerPhase,
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        ...(stopSummary !== undefined
          ? {
              // Keep provider_degraded / other special reasons; only re-stamp
              // generic infra-shaped summaries to the stage token.
              stopSummary:
                stopSummary.reason === "provider_degraded" ||
                stopSummary.reason === "decision_gate_park"
                  ? stopSummary
                  : { ...stopSummary, reason: "cmr_failed" as const },
            }
          : {
              stopSummary: stageFailureStopSummary({
      status: "cmr_failed",
                summary: reason,
              }),
            }),
      });
    });
    return {
      // provider_degraded is still a stage death for the family barrier.
      result: stageGate("cmr_failed"),
      familyHeadAfter: postWorkerFamilyHead,
      resolvedRoute: activeRoute,
    };
  }
  // #930 / #919 E: family court closes on shared T2 judge tri-state only.
  // Residual kind:"cmr" / open-count paper is never projected to continue —
  // closeFamilyCourtFromJudgeOutput fail-louds non-judge as unusable (no
  // open-count second closer). Live kind:"judge" is direct.
  const rawOutput = cmrResult.output;
  const judgeTraffic = rawOutput;
  const closure = closeFamilyCourtFromJudgeOutput(judgeTraffic);
  const openedJudgeSessionId =
    typeof cmrResult.sessionId === "string" && cmrResult.sessionId.length > 0
      ? cmrResult.sessionId
      : resumeJudgeSessionId;
  const judgeStatusForLedger =
    judgeTraffic.kind === "judge" ? judgeTraffic.status : undefined;
  // Schema disposition table (refute/suppress/live) — queryable suppress is
  // action:"suppress" on this table (#952). Family persists T2 schema for
  // prior-verdict resume (no dual store-status ABI on the ledger). R7-C1 maps
  // prior schema terminals → store from-status into closeFamilyCourt so
  // projectJudgeContinueBlocking rejects illegal terminal→terminal morphs.
  const judgeDispositionsForLedger =
    judgeTraffic.kind === "judge" ? judgeTraffic.findingDispositions : undefined;
  const advanceCoderForLedger =
    judgeTraffic.kind === "judge" ? judgeTraffic.advanceCoder : undefined;
  // #1007 R5: typed family CMR judge land → progress feed (no prose).
  // Same helper as single-slice; step is pass-scoped (not S3/S6 seat id).
  if (judgeTraffic.kind === "judge") {
    emitJudgeProgress({
      epic: familyIssue ?? null,
      issue: familyIssue ?? null,
      step: `cmr:${pass}`,
      verdict: judgeTraffic.status,
    });
  }
  // #1094 F4: producer-authored skippedLegs are authoritative when panel legs
  // were declared (including undefined for transports-only cold cargo). Judge
  // cargo is fallback only when no legs were declared.
  const cargoSource =
    rawOutput !== null && typeof rawOutput === "object"
      ? (rawOutput as {
          readonly skippedLegs?: ReadonlyArray<{
            readonly slug: string;
            readonly reason: string;
          }>;
        })
      : undefined;
  const skippedLegs =
    frozenLegs.length > 0 ? hostSkippedLegs : cargoSource?.skippedLegs;

  // #1085 / #1080: sole production edge source = shared hub table
  // (isomorphic with per-slice route.ts → routeResidentJudgeHub and wave
  // court above). Cargo still narrows on closure.action after hubNext is known.
  const hubNext = hubNextFromFamilyClosureAction(closure.action, "family_cmr");

  // pass → exit_loop / accepted.
  if (hubNext === "exit_loop") {
    if (receiveResidentJudgeOnly) {
      finalReviewRoundDisposition = "accepted";
      await familyBackend.appendFamilyLedger({
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: `cmr:${pass}`,
        reason:
          `integrated cmr ${pass} resident judge received builder beat; ` +
          "fresh outer panel gate requested by typed converged verdict",
        phase: ledgerPhase,
        cmrPass: pass,
        ...(openedJudgeSessionId !== undefined
          ? { judgeSessionId: openedJudgeSessionId }
          : {}),
        ...(expectedCourtGeneration !== undefined
          ? { expectedCourtGeneration }
          : {}),
      });
      return {
        result: { ok: true, ran: true },
        familyHeadAfter: postWorkerFamilyHead,
        resolvedRoute: activeRoute,
        needsFreshOuterGate: true,
      };
    }
    await persistFinalReviewRound("accepted", () =>
      recordCmrPassed(familyBackend, {
        phase: ledgerPhase,
        cmrPass: pass,
        familyHeadAfter: postWorkerFamilyHead,
        routeFingerprint,
        ...(openedJudgeSessionId !== undefined
          ? { sessionId: openedJudgeSessionId }
          : {}),
        judgeStatus: "converged",
        ...(judgeDispositionsForLedger !== undefined
          ? { findingDispositions: judgeDispositionsForLedger }
          : {}),
        ...(advanceCoderForLedger !== undefined
          ? { advanceCoder: advanceCoderForLedger }
          : {}),
        stopSummary: familyCmrPassStopSummary({
          familyHeadAfter: postWorkerFamilyHead,
          skippedLegs,
        }),
      }),
    );
    return {
      result: { ok: true, ran: true },
      familyHeadAfter: postWorkerFamilyHead,
      resolvedRoute: activeRoute,
    };
  }

  // escalate → park.
  if (hubNext === "park") {
    if (closure.action !== "escalate") {
      throw new Error(
        `integrated cmr ${pass}: hub park without escalate action (${closure.action})`,
      );
    }
    const reason = closure.reason;
    const diagnosis = closure.diagnosis;
    const stopSummary = decisionGateParkStopSummary({
      summary: `${reason} — ${diagnosis}`,
      repairHint:
        "answer the family judge decision gate, then resume the family court in place",
      heads:
        postWorkerFamilyHead !== undefined
          ? { actualFamilyHead: postWorkerFamilyHead }
          : undefined,
    });
    await persistFinalReviewRound("accepted", async () => {
      await recordCmrReviewed(familyBackend, {
        phase: ledgerPhase,
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        blockingFindingIdentityKeys: [],
        ...(openedJudgeSessionId !== undefined
          ? { sessionId: openedJudgeSessionId }
          : {}),
        judgeStatus: "escalate",
        ...(judgeDispositionsForLedger !== undefined
          ? { findingDispositions: judgeDispositionsForLedger }
          : {}),
        stopSummary,
      });
      await familyBackend.escalateFamily?.({
        reason,
        diagnosis,
        familyHeadAfter: postWorkerFamilyHead,
        stopSummary,
        escalationKind: "decision",
      });
    });
    return {
      result: { ok: false, ran: true },
      familyHeadAfter: postWorkerFamilyHead,
      resolvedRoute: activeRoute,
    };
  }

  // unusable → fail_loud (#919 M1) — never family coder-fix.
  if (hubNext === "fail_loud") {
    if (closure.action !== "unusable") {
      throw new Error(
        `integrated cmr ${pass}: hub fail_loud without unusable action (${closure.action})`,
      );
    }
    const reason = `integrated cmr ${pass} ${closure.reason}`;
    const stopSummary: StopSummary = stageFailureStopSummary({
      status: "cmr_failed",
      summary: reason,
      repairHint:
        "unusable family judge envelope after seat-side typed SO re-ask " +
        "(RECEIPT_MAX_RETRIES); re-open the same family judge seat or repair " +
        "the seat receipt contract — do not route bad shape through coder-fix",
    });
    await persistFinalReviewRound("accepted", () =>
      recordDurableAbort(familyBackend, {
        phase: ledgerPhase,
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        blockingFindingIdentityKeys: [],
        stopSummary,
      }),
    );
    return {
      result: stageGate("cmr_failed"),
      familyHeadAfter: postWorkerFamilyHead,
      resolvedRoute: activeRoute,
    };
  }

  // toolchain (ADR 0145) — verify_failed, zero fixer spin.
  if (hubNext === "toolchain") {
    if (closure.action !== "toolchain") {
      throw new Error(
        `integrated cmr ${pass}: hub toolchain without toolchain action (${closure.action})`,
      );
    }
    const reason = `integrated cmr ${pass} toolchain: ${closure.reason} — ${closure.diagnosis}`;
    const stopSummary: StopSummary = stageFailureStopSummary({
      status: "verify_failed",
      summary: reason,
      repairHint:
        "family judge classified this red as toolchain/environment " +
        "(not a cross-slice regression); fix the toolchain/dependency and " +
        "re-run — do not route through coder-fix",
    });
    await persistFinalReviewRound("accepted", () =>
      recordDurableAbort(familyBackend, {
        phase: ledgerPhase,
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        blockingFindingIdentityKeys: [],
        stopSummary,
      }),
    );
    return {
      result: stageGate("verify_failed"),
      familyHeadAfter: postWorkerFamilyHead,
      resolvedRoute: activeRoute,
    };
  }

  // continue → resume_builder + live findings → coder-fix, then ALWAYS
  // re-open resident judge via restartFinalBarrier (ADR 0147 hub; #1085).
  // #952: terminal-only continue folds to pass at closeFamilyCourt (upstream).
  if (hubNext !== "resume_builder") {
    const _never: never = hubNext;
    throw new Error(
      `integrated cmr ${pass}: unhandled hub next ${String(_never)}`,
    );
  }
  if (closure.action !== "continue") {
    throw new Error(
      `integrated cmr ${pass}: hub resume_builder without continue action (${closure.action})`,
    );
  }
  // The opaque fixPacketBody is the judge-authored fixer scope. Disposition
  // rows remain judge/findings-store cargo and are never projected into fixer
  // controls by the runner (ADR 0062 / 0131 / 0138).
  const blockingFindingIdentityKeys: readonly string[] = [];
  const blockingFindingCount = blockingFindingIdentityKeys.length;

  // ADR 0138 / #978: packet body required before family coder-fix — never pack
  // bare findings as a second content channel.
  let fixPacketBody: string;
  try {
    fixPacketBody = requireFixPacketBody({
      status: "continue",
      fixPacketBody: closure.fixPacketBody,
    });
  } catch (err) {
    const reason =
      err instanceof Error
        ? err.message
        : "family judge continue missing fixPacketBody (ADR 0138)";
    const stopSummary: StopSummary = stageFailureStopSummary({
      status: "cmr_failed",
      summary: reason,
      repairHint:
        "family judge status:continue must author non-empty fixPacketBody; " +
        "runner transports it verbatim and will not pack bare findings",
    });
    await persistFinalReviewRound("accepted", () =>
      recordDurableAbort(familyBackend, {
        phase: ledgerPhase,
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        blockingFindingIdentityKeys,
        stopSummary,
      }),
    );
    return {
      result: stageGate("cmr_failed"),
      familyHeadAfter: postWorkerFamilyHead,
      resolvedRoute: activeRoute,
    };
  }

  const reason =
    `integrated cmr ${pass} judge continue with opaque fixer packet`;
  const stopSummary: StopSummary = stageFailureStopSummary({
    status: "cmr_failed",
    summary: reason,
    repairHint:
      "transport the judge-authored packet to coder-fix, then resume the family judge",
  });

  // Soul law: missing sessionId / not resume-capable → still coder-fix;
  // next open is fresh + priorJudgeVerdicts (no same-session-or-die terminal).
  if (allowCoderFix) {
    await persistFinalReviewRound("accepted", () =>
      recordCmrReviewed(familyBackend, {
        phase: ledgerPhase,
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        blockingFindingIdentityKeys,
        ...(openedJudgeSessionId !== undefined
          ? { sessionId: openedJudgeSessionId }
          : {}),
        ...(judgeStatusForLedger !== undefined
          ? { judgeStatus: judgeStatusForLedger }
          : { judgeStatus: "continue" }),
        ...(judgeDispositionsForLedger !== undefined
          ? { findingDispositions: judgeDispositionsForLedger }
          : {}),
        ...(advanceCoderForLedger !== undefined
          ? { advanceCoder: advanceCoderForLedger }
          : {}),
        stopSummary,
      }),
    );

    // #919 / #926 / #930: execute advanceCoder on the family coderFix seat
    // before dispatch (same effect path as single-slice; never terminal).
    const advanceSuggestion =
      typeof advanceCoderForLedger === "string"
        ? advanceCoderForLedger.trim()
        : "";
    if (advanceSuggestion.length > 0) {
      const effect = await executeAdvanceCoderSuggestion({
        suggestion: advanceSuggestion,
        currentSlug: activeRoute.slots.coderFix,
        route: activeRoute,
        applySlug: (route, slug) =>
          applyRelayBatonToRoute(route, { slug }, "S5", {
            slots: ["coderFix"],
          }),
        probe: (candidate) =>
          probeFamilyAdvanceRoute(candidate, "family-advance"),
      });
      activeRoute = effect.route;
      if (effect.kind === "stay_put" || effect.kind === "advanced") {
        await familyBackend.appendFamilyLedger({
          ...familyAdvanceCoderAuditFields(
            effect,
            advanceSuggestion,
            "coderFix",
          ),
          phase: ledgerPhase,
          cmrPass: pass,
        });
        console.info(
          effect.kind === "advanced"
            ? `[family] #919 advanceCoder → ${effect.toSlug} ` +
                `(coderFix) from ${effect.fromSlug}`
            : `[family] #919 advanceCoder stay-put (${effect.reason}): ` +
                `kept ${activeRoute.slots.coderFix}; suggestion=${effect.suggestion}`,
        );
      }
    }

    const fixFamilyHeadBefore = postWorkerFamilyHead;
    const fixRound = await runCmrCoderFix({
      pass,
      familyBackend,
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      fixPacketBody,
      blockingFindingCount,
      blockingFindingIdentityKeys,
      rawReviewerArtifacts: reviewerArtifactPointers(
        reviewerMonitorHandle,
        cmrResult.sessionId,
      ),
      familyHeadBefore: fixFamilyHeadBefore,
      escalationAnswer,
      familyIssue,
      resolvedRoute: activeRoute,
      // #961: checkpoint vs final ownership on durable fix rows (PR #982 C1).
      ledgerPhase,
      ...(billingPool !== undefined ? { billingPool } : {}),
      ...(billingPoolSlots !== undefined ? { billingPoolSlots } : {}),
      ...(priorCmrFindingIdentityKeysByPass !== undefined
        ? { priorCmrFindingIdentityKeysByPass }
        : {}),
    });
    // #1085 / ADR 0147: builder beat → resident judge only (restartFinalBarrier
    // re-opens the pure court). Never a builder→reviewer-only exit.
    if (!fixRound.result.ok) {
      return { ...fixRound, resolvedRoute: activeRoute };
    }
    const updatedPriorKeys = [
      ...new Set([
        ...(priorCmrFindingIdentityKeys ?? []),
        ...blockingFindingIdentityKeys,
      ]),
    ];
    const fromFix = fixRound.restartFinalBarrier;
    // #966: sessionId already on cmr_reviewed ledger row above; next open
    // derives resume from ledger (no ByPass packing).
    return {
      result: { ok: true, ran: true },
      familyHeadAfter: fixRound.familyHeadAfter,
      resolvedRoute: activeRoute,
      restartFinalBarrier: {
        familyHeadAfter: fixRound.familyHeadAfter,
        priorCmrFindingIdentityKeysByPass: {
          ...(priorCmrFindingIdentityKeysByPass ?? {}),
          ...(fromFix?.priorCmrFindingIdentityKeysByPass ?? {}),
          [pass]: updatedPriorKeys,
        },
        ...(fromFix?.refusalStateByPass !== undefined
          ? { refusalStateByPass: fromFix.refusalStateByPass }
          : {}),
      },
    };
  }

  await persistFinalReviewRound("accepted", () =>
    recordDurableAbort(familyBackend, {
      phase: ledgerPhase,
      cmrPass: pass,
      reason,
      familyHeadAfter: postWorkerFamilyHead,
      blockingFindingIdentityKeys,
      stopSummary,
    }),
  );
  return {
    result: stageGate("cmr_failed"),
    familyHeadAfter: postWorkerFamilyHead,
    resolvedRoute: activeRoute,
  };
  } finally {
    stampReviewRound(reviewRoundResult, finalReviewRoundDisposition);
  }
}

/**
 * Shared Integrated Correctness court loop (#961 CR R1 DRY).
 *
 * Both `correctness_checkpoint` and final Step6 run the same correctness court
 * machine (open → fix → re-verify → re-open). Callers differ only in prefix
 * (checkpoint: no completeness; final: completeness first) and suffix
 * (checkpoint: early `ok`; final: ship / online-review / landing).
 */
type PendingBuilderReceiveHydration = {
  readonly pendingReview: boolean;
  readonly pendingBuilderBeat: boolean;
  readonly pendingDecisionAnswer: boolean;
  readonly expectedCourtGeneration?: number;
  readonly requireFreshPanelEvidence: boolean;
  readonly familyHeadAfter?: string;
  readonly refusalStateByPass: RefusalStateByPass;
};

async function hydratePendingBuilderReceive(input: {
  readonly familyBackend: FamilyBackend;
  readonly pass: IntegratedCmrPass;
  readonly ledgerPhase: "final" | "correctness_checkpoint";
  readonly familyHeadAfter?: string;
}): Promise<PendingBuilderReceiveHydration> {
  const pending = pendingBuilderReviewFromFamilyLedger(
    await input.familyBackend.readFamilyLedger(),
    input.pass,
    input.ledgerPhase,
  );
  return {
    pendingReview: pending.pending,
    pendingBuilderBeat:
      pending.pending &&
      pending.pendingDecisionAnswer !== true &&
      pending.pendingPanelReturn !== true &&
      pending.freshPanelReviewRequired !== true,
    pendingDecisionAnswer: pending.pendingDecisionAnswer === true,
    ...(pending.expectedCourtGeneration !== undefined
      ? { expectedCourtGeneration: pending.expectedCourtGeneration }
      : {}),
    requireFreshPanelEvidence:
      pending.freshPanelReviewRequired === true ||
      (pending.pending &&
        pending.pendingDecisionAnswer !== true &&
        pending.pendingPanelReturn !== true &&
        pending.expectedCourtGeneration === undefined),
    familyHeadAfter:
      input.familyHeadAfter ?? pending.familyHeadAfter,
    refusalStateByPass:
      pending.refusedFindingIdentityKeys !== undefined ||
      pending.refuseRecords !== undefined
        ? {
            [input.pass]: {
              ...(pending.refusedFindingIdentityKeys !== undefined
                ? { keys: pending.refusedFindingIdentityKeys }
                : {}),
              ...(pending.refuseRecords !== undefined
                ? { records: pending.refuseRecords }
                : {}),
            },
          }
        : {},
  };
}

type PostFixHandoff =
  | {
      readonly ok: true;
      readonly familyHeadAfter?: string;
      readonly priorKeysByPass: Partial<
        Record<IntegratedCmrPass, readonly string[]>
      >;
      readonly refusalStateByPass: RefusalStateByPass;
    }
  | {
      readonly ok: false;
      readonly result: VerifyCmrResult;
      readonly familyHeadAfter?: string;
    };

/** Shared verify + structured state reconstruction after either CMR fixer. */
async function verifyPostFixHandoff(input: {
  readonly phase: VerifyCmrPhase;
  readonly familyBase: string;
  readonly familyBackend: FamilyBackend;
  readonly restart: NonNullable<
    IntegratedCmrPassOutcome["restartFinalBarrier"]
  >;
  readonly runId?: string;
  readonly familyIssue?: number;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  readonly escalationAnswer?: EscalationAnswerPayload;
}): Promise<PostFixHandoff> {
  const verified = await runFamilyVerifyThroughCourt({
    phase: input.phase,
    familyBase: input.familyBase,
    familyBackend: input.familyBackend,
    familyHeadAfter: input.restart.familyHeadAfter,
    ...(input.runId !== undefined ? { runId: input.runId } : {}),
    ...(input.familyIssue !== undefined
      ? { familyIssue: input.familyIssue }
      : {}),
    modelRoute: input.resolvedRoute,
    ...(input.billingPool !== undefined
      ? { billingPool: input.billingPool }
      : {}),
    ...(input.billingPoolSlots !== undefined
      ? { billingPoolSlots: input.billingPoolSlots }
      : {}),
    ...(input.escalationAnswer !== undefined
      ? { escalationAnswer: input.escalationAnswer }
      : {}),
  });
  const familyHeadAfter =
    verified.familyHeadAfter ?? input.restart.familyHeadAfter;
  if (!verified.ok) {
    return { ok: false, result: verified, familyHeadAfter };
  }
  return {
    ok: true,
    familyHeadAfter,
    priorKeysByPass: input.restart.priorCmrFindingIdentityKeysByPass,
    refusalStateByPass: input.restart.refusalStateByPass ?? {},
  };
}

type CourtOpenDirective = {
  readonly forceOpen: boolean;
  readonly expectedGeneration?: number;
  readonly requireFreshEvidence: boolean;
  readonly receiveBuilderBeat: boolean;
  readonly receiveDecisionAnswer: boolean;
};

function courtOpenDirective(input: {
  readonly pending: PendingBuilderReceiveHydration;
  readonly restartTriggerPending: boolean;
}): CourtOpenDirective {
  return {
    forceOpen: input.pending.pendingReview || input.restartTriggerPending,
    ...(input.pending.expectedCourtGeneration !== undefined
      ? { expectedGeneration: input.pending.expectedCourtGeneration }
      : {}),
    requireFreshEvidence:
      input.pending.requireFreshPanelEvidence ||
      input.restartTriggerPending,
    receiveBuilderBeat:
      input.pending.pendingBuilderBeat &&
      !input.pending.pendingDecisionAnswer &&
      !input.restartTriggerPending,
    receiveDecisionAnswer:
      input.pending.pendingDecisionAnswer && !input.restartTriggerPending,
  };
}

function passAcceptedAfterTrigger(input: {
  readonly ledger: ReadonlyArray<FamilyLedgerEntry>;
  readonly pass: IntegratedCmrPass;
  readonly triggerPass: IntegratedCmrPass;
  readonly phase: "final" | "correctness_checkpoint";
  readonly familyHeadAfter?: string;
  readonly routeFingerprint: string;
}): boolean {
  const head = input.familyHeadAfter?.trim();
  if (head === undefined || head.length === 0) return false;
  let triggerIndex = -1;
  for (let index = input.ledger.length - 1; index >= 0; index -= 1) {
    const entry = input.ledger[index]!;
    if (
      (entry.status === "cmr_fix_committed" ||
        entry.event === "cmr_fix_committed") &&
      entry.cmrPass === input.triggerPass &&
      cmrBarrierPhaseOf(entry.phase) === input.phase
    ) {
      triggerIndex = index;
      break;
    }
  }
  if (triggerIndex < 0) return false;
  return input.ledger.slice(triggerIndex + 1).some(
    (entry) =>
      entry.status === "cmr_passed" &&
      entry.event === "cmr_passed" &&
      entry.cmrPass === input.pass &&
      cmrBarrierPhaseOf(entry.phase) === input.phase &&
      entry.familyHeadAfter?.trim() === head &&
      entry.routeFingerprint === input.routeFingerprint,
  );
}

async function runCmrCourtLoop(input: {
  readonly pass: IntegratedCmrPass;
  /** A pending later-pass fix also invalidates this earlier final court. */
  readonly restartTriggerPass?: IntegratedCmrPass;
  /** Final correctness fixes restart the outer barrier at completeness. */
  readonly restartFinalBarrierAfterFix: boolean;
  readonly phase: VerifyCmrPhase;
  readonly ledgerPhase: "final" | "correctness_checkpoint";
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId?: string;
  readonly llmResolvedChildren?: readonly number[];
  readonly escalationAnswer?: EscalationAnswerPayload;
  readonly familyHeadAfter?: string;
  readonly familyIssue?: number;
  readonly moduleContext?: FamilyModuleContext;
  readonly priorKeysByPass: Partial<
    Record<IntegratedCmrPass, readonly string[]>
  >;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
}): Promise<{
  readonly result: VerifyCmrResult;
  readonly familyHeadAfter?: string;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly priorKeysByPass: Partial<
    Record<IntegratedCmrPass, readonly string[]>
  >;
  readonly refusalStateByPass: RefusalStateByPass;
  readonly restartFinalBarrier?: IntegratedCmrPassOutcome["restartFinalBarrier"];
}> {
  const {
    phase,
    pass,
    ledgerPhase,
    familyBackend,
    familyBase,
    runId,
    llmResolvedChildren,
    escalationAnswer,
    familyIssue,
    moduleContext,
  } = input;
  const scopedPoolFields = {
    ...(input.billingPool !== undefined ? { billingPool: input.billingPool } : {}),
    ...(input.billingPoolSlots !== undefined
      ? { billingPoolSlots: input.billingPoolSlots }
      : {}),
  };

  const restartTrigger =
    input.restartTriggerPass !== undefined &&
    input.restartTriggerPass !== pass
      ? await hydratePendingBuilderReceive({
          familyBackend,
          pass: input.restartTriggerPass,
          ledgerPhase,
          ...(input.familyHeadAfter !== undefined
            ? { familyHeadAfter: input.familyHeadAfter }
            : {}),
        })
      : undefined;
  const pendingReceive = await hydratePendingBuilderReceive({
    familyBackend,
    pass,
    ledgerPhase,
    ...(input.familyHeadAfter !== undefined
      ? { familyHeadAfter: input.familyHeadAfter }
      : restartTrigger?.familyHeadAfter !== undefined
        ? { familyHeadAfter: restartTrigger.familyHeadAfter }
      : {}),
  });
  const routeFingerprint = modelRouteFingerprint(input.resolvedRoute);
  const triggerRequiresRestart =
    restartTrigger?.pendingReview === true &&
    restartTrigger.pendingDecisionAnswer !== true &&
    !passAcceptedAfterTrigger({
      ledger: await familyBackend.readFamilyLedger(),
      pass,
      triggerPass: input.restartTriggerPass!,
      phase: ledgerPhase,
      familyHeadAfter: pendingReceive.familyHeadAfter,
      routeFingerprint,
    });
  let courtFamilyHeadAfter = pendingReceive.familyHeadAfter;
  let courtPriorKeysByPass = input.priorKeysByPass;
  let resolvedRoute = input.resolvedRoute;
  // Process-local refuse maps survive barrier restarts for the immediate
  // re-open after coder-fix refuse (#966 / #919 R2). Cold-start: recover from
  // durable cmr_fix_committed (#1119) — not process memory alone.
  let refusalStateByPass = pendingReceive.refusalStateByPass;
  let openDirective = courtOpenDirective({
    pending: pendingReceive,
    restartTriggerPending: triggerRequiresRestart,
  });
  while (true) {
    const court = await runIntegratedCmrPass({
      pass,
      familyBackend,
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      llmResolvedChildren,
      escalationAnswer,
      familyHeadAfter: courtFamilyHeadAfter,
      familyIssue,
      moduleContext,
      priorCmrFindingIdentityKeys: courtPriorKeysByPass[pass],
      priorCmrFindingIdentityKeysByPass: courtPriorKeysByPass,
      resolvedRoute,
      allowCoderFix: true,
      ledgerPhase,
      forceCourtOpen: openDirective.forceOpen,
      ...(openDirective.expectedGeneration !== undefined
        ? {
            expectedCourtGeneration: openDirective.expectedGeneration,
          }
        : {}),
      requireFreshPanelEvidence: openDirective.requireFreshEvidence,
      receiveBuilderBeat: openDirective.receiveBuilderBeat,
      receiveDecisionAnswer: openDirective.receiveDecisionAnswer,
      ...scopedPoolFields,
      ...(refusalStateByPass[pass]?.keys !== undefined
        ? {
            refusedFindingIdentityKeys:
              refusalStateByPass[pass]?.keys,
          }
        : {}),
      ...(refusalStateByPass[pass]?.records !== undefined
        ? { refuseRecords: refusalStateByPass[pass]?.records }
        : {}),
    });
    openDirective = {
      forceOpen: false,
      requireFreshEvidence: false,
      receiveBuilderBeat: false,
      receiveDecisionAnswer: false,
    };
    if (!court.result.ok) {
      return {
        result: court.result,
        familyHeadAfter: court.familyHeadAfter,
        resolvedRoute: court.resolvedRoute ?? resolvedRoute,
        priorKeysByPass: courtPriorKeysByPass,
        refusalStateByPass,
      };
    }
    // #919: sticky advanced coderFix across courts / fix rounds.
    if (court.resolvedRoute !== undefined) {
      resolvedRoute = court.resolvedRoute;
    }
    if (court.restartFinalBarrier === undefined) {
      if (court.needsFreshOuterGate === true) {
        courtFamilyHeadAfter = court.familyHeadAfter;
        openDirective = {
          forceOpen: true,
          requireFreshEvidence: true,
          receiveBuilderBeat: false,
          receiveDecisionAnswer: false,
        };
        continue;
      }
      return {
        result: { ok: true, ran: true },
        familyHeadAfter: court.familyHeadAfter,
        resolvedRoute,
        priorKeysByPass: courtPriorKeysByPass,
        refusalStateByPass,
      };
    }
    // #1110 P1: mid-court re-verify after CMR fixer uses the same verify→court
    // mechanism (not a hard-die bypass).
    const handoff = await verifyPostFixHandoff({
      phase,
      familyBase,
      familyBackend,
      restart: court.restartFinalBarrier,
      resolvedRoute,
      ...(runId !== undefined ? { runId } : {}),
      ...(familyIssue !== undefined ? { familyIssue } : {}),
      ...scopedPoolFields,
      ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
    });
    if (!handoff.ok) {
      return {
        result: handoff.result,
        familyHeadAfter: handoff.familyHeadAfter,
        resolvedRoute,
        priorKeysByPass: courtPriorKeysByPass,
        refusalStateByPass,
      };
    }
    courtFamilyHeadAfter = handoff.familyHeadAfter;
    courtPriorKeysByPass = handoff.priorKeysByPass;
    refusalStateByPass = handoff.refusalStateByPass;
    if (input.restartFinalBarrierAfterFix) {
      return {
        result: { ok: true, ran: true },
        familyHeadAfter: courtFamilyHeadAfter,
        resolvedRoute,
        priorKeysByPass: courtPriorKeysByPass,
        refusalStateByPass,
        restartFinalBarrier: {
          familyHeadAfter: courtFamilyHeadAfter,
          priorCmrFindingIdentityKeysByPass: courtPriorKeysByPass,
          ...(Object.keys(refusalStateByPass).length > 0
            ? { refusalStateByPass }
            : {}),
        },
      };
    }
    openDirective = {
      forceOpen: true,
      requireFreshEvidence: false,
      receiveBuilderBeat: true,
      receiveDecisionAnswer: false,
    };
  }
}

/**
 * #1090 — is `value` a canonical GitHub PR URL (https + `/pull/<number>`)? A branch
 * name is NOT a valid PR handle and must never be written to the shipped ledger
 * row's `pr` field — it would poison the online review poll (fail-closed
 * "non-admissible PR handle") on every idempotent re-ship.
 *
 * #1090 P1: botPolling.isCanonicalGithubPrUrl is the sole predicate for what PR
 * handle the shipped ledger may carry. No local lookalike validator may drift
 * from that exact https GitHub web form.
 *
 * Pure so the boundary is unit-tested without gh / a container.
 */
export function isPrUrl(value: string): boolean {
  return isCanonicalGithubPrUrl(value);
}

/**
 * #1090 — resolve the open PR URL for `branch` via `gh pr list --head <branch>
 * --json url`. Returns the URL when gh yields a well-formed PR URL; returns
 * `undefined` when gh finds no PR, returns a malformed value, or throws.
 *
 * Sync because `shWithClock` is sync (mirrors the `ghSh` pattern in
 * {@link runFamilyOnlineReviewLoop}). Uses `ORCHESTRATOR_REPO` when set so gh
 * targets the right repo in a clone-from-local family run (same env convention
 * as the online review loop).
 */
export function resolveFamilyShipPr(branch: string): string | undefined {
  const repo =
    process.env.ORCHESTRATOR_REPO?.trim() ?? "Akagilnc/ming-salvage-sim";
  const args = [
    "pr",
    "list",
    "--head",
    branch,
    "--json",
    "url",
    "--limit",
    "1",
    "--repo",
    repo,
  ];
  try {
    const out = shWithClock("gh", args, { stage: "resolve:shipPr" });
    const parsed = JSON.parse(out) as ReadonlyArray<{ readonly url?: unknown }>;
    const url = parsed[0]?.url;
    return typeof url === "string" && isPrUrl(url) ? url : undefined;
  } catch {
    return undefined;
  }
}

/** Keep canonical ship output; resolve every other handle from the family branch. */
export function resolveShippedPrUrl(
  shipPr: string | undefined,
  familyBranch: string,
): string | undefined {
  return shipPr !== undefined && isPrUrl(shipPr)
    ? shipPr.trim()
    : resolveFamilyShipPr(familyBranch);
}

/**
 * Run the family verify against the family base, then (on the `"final"` phase)
 * the integrated cmr 承重闸 and the open-PR step (ADR 0022 decision 3④/⑤/⑥/4).
 *
 * Missing `runFamilyVerify` fails closed (`verify_failed` — #939 / ID-011). A
 * backend that verifies green but lacks a required downstream capability
 * fails-safe via stage-named `stageGate(...)` (`cmr_failed` / `ship_failed` / …
 * — never a false success). Surfaces a red barrier purely via the returned `ok`;
 * the spine acts on it (it is never rewritten here).
 */
export async function runVerifyCmr(
  input: VerifyCmrInput,
): Promise<VerifyCmrResult> {
  const {
    phase,
    familyBase,
    familyBackend,
    llmResolvedChildren,
    escalationAnswer,
    familyIssue,
    moduleContext,
    priorCmrFindingIdentityKeys,
    priorCmrFindingIdentityKeysByPass,
    modelRoute,
    billingPool,
    billingPoolSlots,
    runId,
  } = input;
  let familyHeadAfter = input.familyHeadAfter;
  const scopedPoolFields = {
    ...(billingPool !== undefined ? { billingPool } : {}),
    ...(billingPoolSlots !== undefined ? { billingPoolSlots } : {}),
  };

  // ── verify (all phases: "wave", "correctness_checkpoint", "final") ──
  // #1107 / #1110: one mechanism — green continues; red enters the shared court.
  const verifyCourt = await runFamilyVerifyThroughCourt({
    phase,
    familyBase,
    familyBackend,
    ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
    ...(runId !== undefined ? { runId } : {}),
    ...(familyIssue !== undefined ? { familyIssue } : {}),
    ...(modelRoute !== undefined ? { modelRoute } : {}),
    ...scopedPoolFields,
    ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
  });
  if (!verifyCourt.ok) {
    return verifyCourt;
  }
  familyHeadAfter = verifyCourt.familyHeadAfter ?? familyHeadAfter;

  if (phase === "wave") {
    return { ok: true, ran: true };
  }

  // ── integrated cmr 承重闸 (decision 3⑥ / #961 checkpoint): only AFTER green verify.
  // #940 / ID-012: production/test contract guarantees CMR capability via the
  // unified dispatchWorker seam (legacy runIntegratedCmr remains a residual
  // fallback inside dispatchFamilyWorker). Missing-capability host fake exits
  // are deleted — dispatch failures surface as normal worker/process outcomes.
  let resolvedRoute: ResolvedModelRoute;
  try {
    resolvedRoute = modelRoute ?? resolveActiveModelRoute();
    // Direct verify-hook unit tests predate the family startup envelope and call
    // this hook without a runner-owned route. Keep those standalone tests on a
    // smoked route; production family runs always pass the real startup-smoked
    // route from runFamily above.
    if (modelRoute === undefined) {
      resolvedRoute = await smokeRouteModels(
        resolvedRoute,
        async () => ({ cliVersion: "standalone-verify-test" }),
      );
    }
  } catch (err) {
    const reason =
      err instanceof Error ? err.message : `failed to resolve active model route: ${String(err)}`;
    const stopSummary = stageFailureStopSummary({
      status: "cmr_failed",
      summary: `startup route failure: ${reason}; route env ORCHESTRATOR_ROUTE=${process.env.ORCHESTRATOR_ROUTE ?? "normal"}`,
      repairHint: "repair the CMR route environment and rerun the family barrier",
    });
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason },
      familyHeadAfter,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter,
      stopSummary,
    });
    return stageGate("cmr_failed");
  }

  // #1002 / #1017 C2 — rebuild sticky **coderFix** from latest family ledger
  // coder_advance scoped to advanceSeat:"coderFix" (not stay_put, not online-
  // review fixer advances). Process re-entry after CMR advance must keep the
  // advanced repair seat without re-suggestion.
  {
    const familyLedgerForRoute = await familyBackend.readFamilyLedger();
    const beforeSlug = resolvedRoute.slots.coderFix;
    const reheld = reholdRepairSeatFromFamilyLedger(
      resolvedRoute,
      familyLedgerForRoute,
      "coderFix",
      "S5",
    );
    resolvedRoute = reheld.route;
    if (
      reheld.reheldSlug !== undefined &&
      beforeSlug !== reheld.reheldSlug
    ) {
      console.info(
        `[family] #1002 re-hold sticky coderFix from ledger coder_advance → ${reheld.reheldSlug}`,
      );
    }
  }

  // #961 / ADR 0139: incremental Integrated Correctness checkpoint — full-strength
  // correctness court only (no completeness, no ship). Scope remains parent-base
  // …target via familyBaseStartHead focus file; durable lastCorrectnessConvergedHead
  // is the latest correctness cmr_passed row written by this court.
  if (phase === "correctness_checkpoint") {
    const activePriorKeysByPass: Partial<
      Record<IntegratedCmrPass, readonly string[]>
    > = {
      ...(priorCmrFindingIdentityKeys !== undefined
        ? { correctness: priorCmrFindingIdentityKeys }
        : {}),
      ...(priorCmrFindingIdentityKeysByPass ?? {}),
    };
    const checkpoint = await runCmrCourtLoop({
      pass: "correctness",
      restartFinalBarrierAfterFix: false,
      phase,
      ledgerPhase: "correctness_checkpoint",
      familyBackend,
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      llmResolvedChildren,
      escalationAnswer,
      familyHeadAfter,
      familyIssue,
      moduleContext,
      priorKeysByPass: activePriorKeysByPass,
      resolvedRoute,
      ...scopedPoolFields,
    });
    // Checkpoint ends here: early ok (or failed) — no completeness / ship suffix.
    return checkpoint.result;
  }

  // #419 / #930: Step5 completeness and Step6 correctness are two ordered
  // family courts of the SAME judge machine. Correctness is unreachable until
  // completeness returns judge-converged.
  let activePriorKeysByPass: Partial<
    Record<IntegratedCmrPass, readonly string[]>
  > = {
    ...(priorCmrFindingIdentityKeys !== undefined
      ? {
          completeness: priorCmrFindingIdentityKeys,
          correctness: priorCmrFindingIdentityKeys,
        }
      : {}),
    ...(priorCmrFindingIdentityKeysByPass ?? {}),
  };
  // #966: judge resume sessionId is derived from the family ledger on each
  // open (cmr_reviewed / cmr_passed). Process-local refuse maps still survive
  // barrier restarts within this final-phase invocation for the immediate
  // re-open after coder-fix refuse.
  let currentFinalHead = familyHeadAfter;
  let cmrPassedFamilyHeadAfter: string | undefined;

  finalCmrCycle: for (;;) {
    const completenessCourt = await runCmrCourtLoop({
      pass: "completeness",
      restartTriggerPass: "correctness",
      restartFinalBarrierAfterFix: false,
      phase,
      ledgerPhase: "final",
      familyBackend,
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      llmResolvedChildren,
      escalationAnswer,
      ...(currentFinalHead !== undefined
        ? { familyHeadAfter: currentFinalHead }
        : {}),
      familyIssue,
      moduleContext,
      priorKeysByPass: activePriorKeysByPass,
      resolvedRoute,
      ...scopedPoolFields,
    });
    if (!completenessCourt.result.ok) return completenessCourt.result;
    resolvedRoute = completenessCourt.resolvedRoute;
    const completenessFamilyHeadAfter =
      completenessCourt.familyHeadAfter;
    const completenessPriorKeysByPass =
      completenessCourt.priorKeysByPass;
  // Correctness court shares the same loop machine as #961 checkpoint
  // (ledgerPhase final; ship / online-review / landing continue below).
  const correctnessCourt = await runCmrCourtLoop({
    pass: "correctness",
    restartFinalBarrierAfterFix: true,
    phase,
    ledgerPhase: "final",
    familyBackend,
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    llmResolvedChildren,
    escalationAnswer,
    familyHeadAfter: completenessFamilyHeadAfter,
    familyIssue,
    moduleContext,
    priorKeysByPass: completenessPriorKeysByPass,
    resolvedRoute,
    ...scopedPoolFields,
  });
  if (!correctnessCourt.result.ok) return correctnessCourt.result;
  resolvedRoute = correctnessCourt.resolvedRoute;
  if (correctnessCourt.restartFinalBarrier !== undefined) {
    currentFinalHead =
      correctnessCourt.familyHeadAfter ??
      correctnessCourt.restartFinalBarrier.familyHeadAfter;
    activePriorKeysByPass =
      correctnessCourt.restartFinalBarrier.priorCmrFindingIdentityKeysByPass;
    continue finalCmrCycle;
  }
  cmrPassedFamilyHeadAfter = correctnessCourt.familyHeadAfter;
  break;
  }
  // Both CMR passes converged. Continue through ship, online review, then
  // landing (docs / merge / MERGED / close / cleanup) below.

  // ── Ship stage: green verify + converged CMR ⇒ open the family PR, then the
  //    same final barrier continues through online review and landing.
  // #940 / ID-012: ship capability is guaranteed by production/test contract
  // (dispatchWorker). Missing-capability host fake exits deleted — ship is
  // always dispatched; worker/process failure is the only ship_failed path.
  const shipSpec = familyShipWorkerSpec(resolvedRoute);
  const shipPool = billingPoolForFamilyWorker({
    ...scopedPoolFields,
    kind: "ship",
  });
  const shipContext = {
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    modelRoute: resolvedRoute,
    ...(shipPool !== undefined ? { billingPool: shipPool } : {}),
    ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
  };
  const shipResult = await dispatchOrAbort(
    familyBackend,
    shipSpec,
    shipContext,
  );

  // The ship worker owns delivery truth. The runner routes only the worker result:
  // completed succeeds, failed/process failure parks after #598 retry, and a
  // decision gate is transported unchanged.
  if (shipResult.kind === "escalated") {
    const postShipFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    const escalationReason = shipResult.escalation.reason;
    const escalationDiagnosis = shipResult.escalation.diagnosis;
    const synthesizedFailure = isRunnerSynthesizedFailureEscalation(
      shipResult.escalation,
    );
    const heads =
      postShipFamilyHead !== undefined
        ? { actualFamilyHead: postShipFamilyHead }
        : undefined;
    const stopSummary = synthesizedFailure
      ? stageFailureStopSummary({
      status: "ship_failed",
          summary: `${escalationReason} — ${escalationDiagnosis}`,
          repairHint:
            "repair the family ship worker startup/authentication failure, then re-feed the family run",
          ...(heads !== undefined ? { metadata: { heads } } : {}),
        })
      : decisionGateParkStopSummary({
          summary: `${escalationReason} — ${escalationDiagnosis}`,
          repairHint: "answer the family ship worker's decision gate, then resume it in place",
          heads,
        });
    await familyBackend.escalateFamily?.({
      reason: escalationReason,
      diagnosis: escalationDiagnosis,
      familyHeadAfter: postShipFamilyHead,
      stopSummary,
      escalationKind: synthesizedFailure ? "failure" : "decision",
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason: synthesizedFailure
        ? `family ship worker startup failure: ${escalationReason} — ${escalationDiagnosis}`
        : `family ship worker escalated: ${escalationReason} — ${escalationDiagnosis}`,
      familyHeadAfter: postShipFamilyHead,
      stopSummary,
    });
    return synthesizedFailure ? stageGate("ship_failed") : { ok: false, ran: true };
  }
  if (shipResult.kind === "failed") {
    const reason = `family ship worker failed: ${shipResult.reason}`;
    const postShipFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    const stopSummary = shipWorkerFailedStopSummary({
      reason,
      latestVerifiedCmrHead: cmrPassedFamilyHeadAfter,
      currentFamilyHead: postShipFamilyHead,
      reportedFamilyHead: cmrPassedFamilyHeadAfter,
      shipPrState: "worker-failed",
    });
    await familyBackend.escalateFamily?.({
      reason,
      familyHeadAfter: postShipFamilyHead,
      phase: "final",
      stopSummary,
      escalationKind: "failure",
    });
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason },
      familyHeadAfter: postShipFamilyHead,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: postShipFamilyHead,
      stopSummary,
    });
    return stageGate("ship_failed");
  }
  const ship: ShipResult =
    shipResult.kind === "completed" && shipResult.output?.kind === "ship"
      ? shipResult.output
      : { kind: "ship", branch: familyBase };
  // #1090 root fix: never fall back to a branch name — a branch name poisons the
  // shipped ledger row's pr field; the online review poll then fail-closed
  // refuses ("non-admissible PR handle") on every idempotent re-ship. Accept
  // ship.pr only when it is the canonical https GitHub PR URL; otherwise
  // resolve the open PR for the family branch via `gh pr list`. If neither yields
  // a real PR URL, fail loud at ship_failed (never write a bogus handle).
  const shipPr = resolveShippedPrUrl(ship.pr, familyBase);
  if (shipPr === undefined) {
    const missingPrHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    const reason =
      `family ship worker completed without a resolvable PR URL ` +
      `(ship.pr=${ship.pr ?? "<absent>"}; branch=${familyBase}); ` +
      `refusing to write a branch name as the shipped ledger pr ` +
      `(#1090 — would poison the online review poll)`;
    const stopSummary = shipWorkerFailedStopSummary({
      reason,
      latestVerifiedCmrHead: cmrPassedFamilyHeadAfter,
      currentFamilyHead: missingPrHead,
      reportedFamilyHead: cmrPassedFamilyHeadAfter,
      shipPrState: "missing-pr-url",
    });
    await familyBackend.escalateFamily?.({
      reason,
      familyHeadAfter: missingPrHead,
      phase: "final",
      stopSummary,
      escalationKind: "failure",
    });
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason },
      familyHeadAfter: missingPrHead,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: missingPrHead,
      stopSummary,
    });
    return stageGate("ship_failed");
  }
  const exactPostShipFamilyHead =
    (await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    )) ?? cmrPassedFamilyHeadAfter ?? "ship-worker-completed";
  // ── Persist the terminal SHIPPED marker before reporting success (online review
  // r2, codex P1). The family ship commit (VERSION/CHANGELOG bump) advanced the
  // family base, but nothing durable recorded that the terminal 止于-PR ship ALREADY
  // ran. On a re-feed/resume, the spine's completeness gate still passes (every
  // child merged) and it would re-enter this final barrier — re-running the full
  // verify + integrated cmr and re-invoking the ship worker (a duplicate VERSION
  // bump / PR attempt). Writing a `shipped` ledger entry makes the delivery durable
  // resume truth: the spine's `familyAlreadyShipped` guard short-circuits the barrier
  // only when the current family HEAD still equals this shipped head.
  const shippedHeadsSummary = {
    reportedFamilyHead: exactPostShipFamilyHead,
    actualFamilyHead: exactPostShipFamilyHead,
    ...(cmrPassedFamilyHeadAfter !== undefined
      ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
      : {}),
    sources: {
      reportedFamilyHead: "family HEAD carried after ship worker completion",
      actualFamilyHead: "family head after ship worker completion",
      verifiedCmrHead: "latest cmr_passed ledger row",
    },
  };
  const shippedSuccessSummary = successStopSummary({
    heads: shippedHeadsSummary,
    ...(ship.degradedReviews !== undefined && ship.degradedReviews.length > 0
      ? { providerDegraded: ship.degradedReviews }
      : {}),
  });
  const ledger = await familyBackend.readFamilyLedger();
  let materialCmrSummary: StopSummary | undefined;
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "cmr_passed" &&
      entry.familyHeadAfter === cmrPassedFamilyHeadAfter &&
      entry.stopSummary !== undefined &&
      isMaterialCmrStopSummary(entry.stopSummary)
    ) {
      materialCmrSummary = entry.stopSummary;
      break;
    }
  }
  const shippedStopSummary =
    materialCmrSummary !== undefined
      ? {
          ...materialCmrSummary,
          metadata: {
            ...(materialCmrSummary.metadata ?? {}),
            ...(shippedSuccessSummary.metadata ?? {}),
          },
        }
      : shippedSuccessSummary;
  await recordShipped(familyBackend, {
    pr: shipPr,
    familyHeadAfter: exactPostShipFamilyHead,
    stopSummary: shippedStopSummary,
  });

  // #600: run the shared online review-loop stage (bot poll → verify → fixer →
  // fresh re-verify) before writing the terminal family review-loop marker.
  const reviewLoop = await runFamilyOnlineReviewLoop({
    familyBackend,
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    ship: {
      kind: "ship",
      branch: familyBase,
      pr: shipPr,
      prHead: exactPostShipFamilyHead,
      status: "pr_opened",
    },
    resolvedRoute,
    ...scopedPoolFields,
  });
  const familyLedgerForHead = await familyBackend.readFamilyLedger();
  const knownPostFixHead =
    lastOnlineReviewFixCommitShaFromFamilyLedger(familyLedgerForHead);
  if (!reviewLoop.ok) {
    const stopSummary = familyOnlineReviewLoopFailureStopSummary(reviewLoop);
    const reason = stopSummary.summary;
    const abortFamilyHead = await familyConvergenceMarkerHead(
      familyBackend,
      familyBase,
      exactPostShipFamilyHead,
      knownPostFixHead,
    );
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason },
      familyHeadAfter: abortFamilyHead,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: abortFamilyHead,
      stopSummary,
    });
    // Decision park leaves failedStatus unset; hard fail → online_review_failed.
    return stopSummary.reason === "decision_gate_park"
      ? { ok: false, ran: true }
      : stageGate("online_review_failed");
  }

  const convergedFamilyHead = await familyConvergenceMarkerHead(
    familyBackend,
    familyBase,
    exactPostShipFamilyHead,
    knownPostFixHead,
  );
  await recordReviewLoopConverged(familyBackend, {
    pr: shipPr,
    familyHeadAfter: convergedFamilyHead,
    ...(shippedStopSummary !== undefined
      ? { stopSummary: shippedStopSummary }
      : {}),
  });

  // #941 / ID-013: landing Action owns docs + merge + MERGED + close + cleanup.
  // Host auto-merge courts and cleanup-fail classification are deleted.
  const landing = await runLandingAction({
    familyBackend,
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    convergedHeadOid: convergedFamilyHead,
    prUrl: shipPr,
    ...(familyIssue !== undefined ? { familyIssue } : {}),
    resolvedRoute,
    ...scopedPoolFields,
  });
  if (!landing.ok) {
    // family/914 CR — single durable exit (recordLandingActionFailure); same
    // writer as ensureLandingForResume. Callers only map kind → result shape.
    const recorded = await recordLandingActionFailure(
      familyBackend,
      landing,
      { phase: "final", familyHeadAfter: convergedFamilyHead },
    );
    if (recorded.kind === "park") {
      // failedStatus omitted → spine finalize escalates via barrier stopSummary
      return { ok: false, ran: true };
    }
    // hard_fail: optional #296 in-memory hook (RealFamilyBackend no-op); durable
    // aborted row already written by recordLandingActionFailure.
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason: recorded.stopSummary.summary },
      familyHeadAfter: convergedFamilyHead,
    });
    return stageGate("merge_failed");
  }
  return { ok: true, ran: true };
}
