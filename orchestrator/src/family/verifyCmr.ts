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

import { isLiveGithubReviewPollEnabled, pollPrReviewState } from "../botPolling.js";
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
} from "./dispatchFamilyWorker.js";
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
  storeStatusByIdentityFromDispositions,
} from "../judgeStation.js";
import type { FindingStoreStatus } from "../findingsStateStore.js";
import { coderRefuseReverifyLanding } from "../coderRefuseExit.js";
import { emitJudgeProgress } from "../progressBroadcast.js";
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
  FamilyVerifyResult,
  IntegratedCmrPass,
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

async function runFamilyVerifyOrAbort(input: {
  readonly phase: VerifyCmrPhase;
  readonly familyBase: string;
  readonly familyBackend: FamilyBackend;
  readonly familyHeadAfter?: string;
  readonly runId?: string;
  readonly familyIssue?: number;
}): Promise<VerifyCmrResult | undefined> {
  const { phase, familyBase, familyBackend, familyHeadAfter } = input;
  const verify: FamilyVerifyResult = await familyBackend.runFamilyVerify({
    phase,
    familyBase,
    ...(input.runId !== undefined ? { runId: input.runId } : {}),
    ...(input.familyIssue !== undefined ? { issue: input.familyIssue } : {}),
  });
  if (verify.ok) return undefined;

  const reason = verify.errorPackage?.reason ?? "family verify failed";
  await familyBackend.recordAborted?.({
    phase,
    familyBase,
    errorPackage: verify.errorPackage ?? { reason },
    familyHeadAfter,
  });
  await recordDurableAbort(familyBackend, {
    phase,
    reason,
    familyHeadAfter,
    stopSummary: familyVerifyFailureStopSummary(reason),
  });
  return stageGate("verify_failed");
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

interface IntegratedCmrPassOutcome {
  readonly result: VerifyCmrResult;
  readonly familyHeadAfter?: string;
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
    /** #930 / #919 R2 — refuse keys blind-routed back to the family judge. */
    readonly refusedFindingIdentityKeysByPass?: Partial<
      Record<IntegratedCmrPass, readonly string[]>
    >;
    /**
     * #919 R2 / #927 isomorphic — opaque refuseRecords cargo for family judge
     * re-open (landing only; never on thin DispatchContext).
     */
    readonly refuseRecordsByPass?: Partial<
      Record<IntegratedCmrPass, readonly ReviewFixRefuseRecord[]>
    >;
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
    await recordCmrFixCommitted(familyBackend, {
      cmrPass: pass,
      phase: ledgerPhase,
      familyHeadBefore: currentFamilyHeadBefore,
      familyHeadAfter,
      blockingFindingIdentityKeys,
      reason: `${reasonPrefix}: completed coder receipt carried another shape; family judge will re-open on the diff`,
      ...(openedFixerSessionId !== undefined
        ? { sessionId: openedFixerSessionId }
        : {}),
    });
    return { result: { ok: true, ran: true }, familyHeadAfter };
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

  await recordCmrFixCommitted(familyBackend, {
    cmrPass: pass,
    phase: ledgerPhase,
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
  });
  return {
    result: { ok: true, ran: true },
    familyHeadAfter,
    // Surface refuse cargo so the pass loop re-opens the court.
    // #966: judge resume sessionId is derived from family ledger on re-open
    // (no judgeSessionIdByPass memory relay — ledger is sole truth).
    restartFinalBarrier: {
      familyHeadAfter,
      priorCmrFindingIdentityKeysByPass: priorCmrFindingIdentityKeysByPass ?? {},
      ...(refusedFindingIdentityKeys.length > 0
        ? {
            refusedFindingIdentityKeysByPass: {
              [pass]: refusedFindingIdentityKeys,
            },
          }
        : {}),
      // #919 R2 / #927: opaque refuseRecords cargo (landing-only on re-open).
      ...(refuseRecords !== undefined && refuseRecords.length > 0
        ? {
            refuseRecordsByPass: {
              [pass]: refuseRecords,
            },
          }
        : {}),
    },
  };
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
  const resumeJudgeSessionId =
    familyJudgeResumeSessionIdFromPriorRows(priorJudgeVerdicts);
  const spec = cmrWorkerSpec(
    resumeJudgeSessionId !== undefined ? "resume" : "fresh",
    pass,
    resolvedRoute,
  );
  const cmrPool = billingPoolForFamilyWorker({
    ...(billingPool !== undefined ? { billingPool } : {}),
    ...(billingPoolSlots !== undefined ? { billingPoolSlots } : {}),
    kind: "cmr",
    cmrPass: pass,
  });
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
    const cmrResult = await dispatchOrAbort(
      familyBackend,
      spec,
      dispatchCtx,
      refuseReopenLanding,
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
  // #952 R7-C1: family ledger stores T2 schema dispositions (refute/suppress/live)
  // on prior court rows — map terminals to store statuses so illegal
  // refuted→suppressed morphs fail at the shared write point (R6-C2 consumer).
  // Do not invent a second store; reuse priorJudgeVerdicts already loaded above.
  const priorSchemaStoreRows: Array<{
    readonly identityKey: string;
    readonly status: FindingStoreStatus;
  }> = [];
  for (const row of priorJudgeVerdicts) {
    for (const d of row.findingDispositions ?? []) {
      if (d.action === "refute") {
        priorSchemaStoreRows.push({
          identityKey: d.identityKey,
          status: "refuted",
        });
      } else if (d.action === "suppress") {
        priorSchemaStoreRows.push({
          identityKey: d.identityKey,
          status: "suppressed",
        });
      }
    }
  }
  const currentStoreStatusByIdentity =
    storeStatusByIdentityFromDispositions(priorSchemaStoreRows);
  const closure = closeFamilyCourtFromJudgeOutput(
    judgeTraffic,
    currentStoreStatusByIdentity,
  );
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
      findingDispositions: judgeDispositionsForLedger,
      findings: judgeTraffic.findings,
    });
  }
  // S3: skippedLegs must not drop on kind:judge (cargo rides).
  const cargoSource =
    rawOutput !== null && typeof rawOutput === "object"
      ? (rawOutput as {
          readonly skippedLegs?: ReadonlyArray<{
            readonly slug: string;
            readonly reason: string;
          }>;
        })
      : undefined;
  const skippedLegs = cargoSource?.skippedLegs;

  if (closure.action === "pass") {
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

  if (closure.action === "escalate") {
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

  // #919 M1 / #930 AC: unusable / bad shape is NOT family coder-fix.
  // Official typed re-furnace = seat-side SO re-ask (RECEIPT_MAX_RETRIES).
  // Runner never uses fixer/coder-fix as a schema court.
  if (closure.action === "unusable") {
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

  // #1027 FINAL / ADR 0145: toolchain terminal — judge classified the red as a
  // toolchain/environment failure, so the runner falls back to verify_failed
  // (no coder-fix loop, no decision-gate park). Loud terminal, never silent.
  if (closure.action === "toolchain") {
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

  // continue + live findings → coder-fix (or abort when fix disabled)
  // #952: terminal-only continue (0 live + suppress/refute flips) is already
  // folded to closure.action === "pass" by closeFamilyCourtFromJudgeOutput —
  // isomorphic with single-slice runner (continue + terminals → converged route).
  const blockingFindings = closure.blocking;
  const blockingFindingIdentityKeys = closure.blockingIdentityKeys;
  const blockingFindingCount = closure.blockingFindingCount;

  // #919 M1 / #930 AC: true empty continue (0 live AND 0 terminals) is court
  // contract drift — never empty-spin family coder-fix. openFindingsForFixer
  // may yield [] for cargo filter; that does NOT authorize a topology fix loop
  // with zero live identity keys. Terminal-only never reaches here (pass above).
  if (
    blockingFindingCount === 0 &&
    blockingFindingIdentityKeys.length === 0
  ) {
    // Defense in depth: if a continue still carries terminal flips, close like
    // pass rather than inventing cmr_failed (mirrors runner M6/#952 gate).
    if (closure.terminalDispositions.length > 0) {
      await persistFinalReviewRound("accepted", () =>
        recordCmrPassed(familyBackend, {
        phase: ledgerPhase,
          cmrPass: pass,
          familyHeadAfter: postWorkerFamilyHead,
          routeFingerprint,
          ...(openedJudgeSessionId !== undefined
            ? { sessionId: openedJudgeSessionId }
            : {}),
          // Keep envelope truth queryable; topology already treated as pass.
          judgeStatus: "continue",
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
    const reason =
      `integrated cmr ${pass} judge continue with 0 live findings ` +
      `(court contract drift; empty continue must not spin coder-fix)`;
    const stopSummary: StopSummary = stageFailureStopSummary({
      status: "cmr_failed",
      summary: reason,
      repairHint:
        "family judge status:continue requires non-empty live identity keys " +
        "or terminal-only dispositions (suppress/refute); " +
        "re-open the same family judge seat or repair the seat envelope — " +
        "do not empty-spin coder-fix",
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

  const reason = `integrated cmr ${pass} judge continue with ${blockingFindingCount} live finding(s)`;
  const stopSummary: StopSummary = stageFailureStopSummary({
      status: "cmr_failed",
    summary: reason,
    repairHint: "send live findings to coder-fix, then resume the family judge",
  });

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
        ...(fromFix?.refusedFindingIdentityKeysByPass !== undefined
          ? {
              refusedFindingIdentityKeysByPass:
                fromFix.refusedFindingIdentityKeysByPass,
            }
          : {}),
        ...(fromFix?.refuseRecordsByPass !== undefined
          ? { refuseRecordsByPass: fromFix.refuseRecordsByPass }
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
async function runCorrectnessCourtLoop(input: {
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
}> {
  const {
    phase,
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

  let correctnessFamilyHeadAfter = input.familyHeadAfter;
  let correctnessPriorKeysByPass = input.priorKeysByPass;
  let resolvedRoute = input.resolvedRoute;
  // Process-local refuse maps survive barrier restarts for the immediate
  // re-open after coder-fix refuse (#966 / #919 R2).
  let refusedFindingIdentityKeysByPass: Partial<
    Record<IntegratedCmrPass, readonly string[]>
  > = {};
  let refuseRecordsByPass: Partial<
    Record<IntegratedCmrPass, readonly ReviewFixRefuseRecord[]>
  > = {};

  while (true) {
    const correctness = await runIntegratedCmrPass({
      pass: "correctness",
      familyBackend,
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      llmResolvedChildren,
      escalationAnswer,
      familyHeadAfter: correctnessFamilyHeadAfter,
      familyIssue,
      moduleContext,
      priorCmrFindingIdentityKeys: correctnessPriorKeysByPass.correctness,
      priorCmrFindingIdentityKeysByPass: correctnessPriorKeysByPass,
      resolvedRoute,
      allowCoderFix: true,
      ledgerPhase,
      ...scopedPoolFields,
      ...(refusedFindingIdentityKeysByPass.correctness !== undefined
        ? {
            refusedFindingIdentityKeys:
              refusedFindingIdentityKeysByPass.correctness,
          }
        : {}),
      ...(refuseRecordsByPass.correctness !== undefined
        ? { refuseRecords: refuseRecordsByPass.correctness }
        : {}),
    });
    if (!correctness.result.ok) {
      return {
        result: correctness.result,
        familyHeadAfter: correctness.familyHeadAfter,
        resolvedRoute: correctness.resolvedRoute ?? resolvedRoute,
      };
    }
    // #919: sticky advanced coderFix across courts / fix rounds.
    if (correctness.resolvedRoute !== undefined) {
      resolvedRoute = correctness.resolvedRoute;
    }
    if (correctness.restartFinalBarrier === undefined) {
      return {
        result: { ok: true, ran: true },
        familyHeadAfter: correctness.familyHeadAfter,
        resolvedRoute,
      };
    }
    const verifyAfterFixFailed = await runFamilyVerifyOrAbort({
      phase,
      familyBase,
      familyBackend,
      familyHeadAfter: correctness.restartFinalBarrier.familyHeadAfter,
      runId,
      familyIssue,
    });
    if (verifyAfterFixFailed !== undefined) {
      return {
        result: verifyAfterFixFailed,
        familyHeadAfter: correctness.restartFinalBarrier.familyHeadAfter,
        resolvedRoute,
      };
    }
    correctnessFamilyHeadAfter =
      correctness.restartFinalBarrier.familyHeadAfter;
    correctnessPriorKeysByPass =
      correctness.restartFinalBarrier.priorCmrFindingIdentityKeysByPass;
    // Unified refuse-map style: replace cargo for this pass only (next re-open).
    const nextRefuse =
      correctness.restartFinalBarrier.refusedFindingIdentityKeysByPass
        ?.correctness;
    refusedFindingIdentityKeysByPass =
      nextRefuse !== undefined ? { correctness: nextRefuse } : {};
    const nextRefuseRecords =
      correctness.restartFinalBarrier.refuseRecordsByPass?.correctness;
    refuseRecordsByPass =
      nextRefuseRecords !== undefined
        ? { correctness: nextRefuseRecords }
        : {};
  }
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
    familyHeadAfter,
    familyIssue,
    moduleContext,
    priorCmrFindingIdentityKeys,
    priorCmrFindingIdentityKeysByPass,
    modelRoute,
    billingPool,
    billingPoolSlots,
    runId,
  } = input;
  const scopedPoolFields = {
    ...(billingPool !== undefined ? { billingPool } : {}),
    ...(billingPoolSlots !== undefined ? { billingPoolSlots } : {}),
  };

  // ── verify (both phases; "final" runs the FULL suite — a RealBackend scopes it
  //    off `phase`). RED ⇒ fail-fast: record the `aborted` event so the failure is
  //    not silently dropped, and return `{ok:false}` (decision 3④/5).
  //    #939: verify is a required capability on FamilyBackend (type-level) —
  //    no optional success no-op path. ──
  const verifyFailed = await runFamilyVerifyOrAbort({
    phase,
    familyBase,
    familyBackend,
    familyHeadAfter,
    runId,
    familyIssue,
  });
  if (verifyFailed !== undefined) return verifyFailed;

  // The wave barrier is verify-only (decision 3④); cmr + PR are the end-of-run
  // (decision 3⑤/⑥). A green wave verify clears the wave. #961 incremental IC
  // checkpoints are a separate phase (correctness court only — see below).
  if (phase === "wave") return { ok: true, ran: true };

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
    const checkpoint = await runCorrectnessCourtLoop({
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
  const activePriorKeysByPass: Partial<
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
  const priorKeysForPass = (
    pass: IntegratedCmrPass,
  ): readonly string[] | undefined =>
    activePriorKeysByPass[pass];
  // #966: judge resume sessionId is derived from the family ledger on each
  // open (cmr_reviewed / cmr_passed). Process-local refuse maps still survive
  // barrier restarts within this final-phase invocation for the immediate
  // re-open after coder-fix refuse.
  let refusedFindingIdentityKeysByPass: Partial<
    Record<IntegratedCmrPass, readonly string[]>
  > = {};
  // #919 R2: opaque refuseRecords cargo pairs with keys for the next re-open.
  let refuseRecordsByPass: Partial<
    Record<IntegratedCmrPass, readonly ReviewFixRefuseRecord[]>
  > = {};

  // Completeness court: loop continue → fix → resume judge until pass.
  // Unusable is fail-loud (seat SO re-ask owns typed re-furnace; no coder-fix).
  let completenessFamilyHeadAfter = familyHeadAfter;
  let completenessPriorKeysByPass = activePriorKeysByPass;
  for (;;) {
    const completeness = await runIntegratedCmrPass({
      pass: "completeness",
      familyBackend,
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      llmResolvedChildren,
      escalationAnswer,
      familyHeadAfter: completenessFamilyHeadAfter,
      familyIssue,
      moduleContext,
      priorCmrFindingIdentityKeys:
        completenessPriorKeysByPass.completeness ??
        priorKeysForPass("completeness"),
      priorCmrFindingIdentityKeysByPass: completenessPriorKeysByPass,
      resolvedRoute,
      allowCoderFix: true,
      ...scopedPoolFields,
      ...(refusedFindingIdentityKeysByPass.completeness !== undefined
        ? {
            refusedFindingIdentityKeys:
              refusedFindingIdentityKeysByPass.completeness,
          }
        : {}),
      ...(refuseRecordsByPass.completeness !== undefined
        ? { refuseRecords: refuseRecordsByPass.completeness }
        : {}),
    });
    if (!completeness.result.ok) return completeness.result;
    // #919: sticky advanced coderFix across courts / fix rounds.
    if (completeness.resolvedRoute !== undefined) {
      resolvedRoute = completeness.resolvedRoute;
    }
    if (completeness.restartFinalBarrier === undefined) {
      completenessFamilyHeadAfter = completeness.familyHeadAfter;
      break;
    }
    // After fix, re-verify before re-opening the court (parity with correctness).
    const verifyAfterCompletenessFix = await runFamilyVerifyOrAbort({
      phase,
      familyBase,
      familyBackend,
      familyHeadAfter: completeness.restartFinalBarrier.familyHeadAfter,
      runId,
      familyIssue,
    });
    if (verifyAfterCompletenessFix !== undefined) {
      return verifyAfterCompletenessFix;
    }
    completenessFamilyHeadAfter =
      completeness.restartFinalBarrier.familyHeadAfter;
    completenessPriorKeysByPass =
      completeness.restartFinalBarrier.priorCmrFindingIdentityKeysByPass;
    // Keep refuse keys + cargo only for the immediate next judge open.
    const nextRefuse =
      completeness.restartFinalBarrier.refusedFindingIdentityKeysByPass
        ?.completeness;
    refusedFindingIdentityKeysByPass =
      nextRefuse !== undefined
        ? { completeness: nextRefuse }
        : {};
    const nextRefuseRecords =
      completeness.restartFinalBarrier.refuseRecordsByPass?.completeness;
    refuseRecordsByPass =
      nextRefuseRecords !== undefined
        ? { completeness: nextRefuseRecords }
        : {};
  }
  // Correctness court shares the same loop machine as #961 checkpoint
  // (ledgerPhase final; ship / online-review / landing continue below).
  const correctnessCourt = await runCorrectnessCourtLoop({
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
  const cmrPassedFamilyHeadAfter = correctnessCourt.familyHeadAfter;
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
  const shipPr =
    isFilledString(ship.pr)
      ? ship.pr
      : isFilledString(ship.branch)
        ? ship.branch
        : familyBase;
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
