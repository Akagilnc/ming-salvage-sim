/**
 * verify-cmr — the family verify + integrated-cmr HOOK seam (ADR 0022 decision
 * 3④/⑤/⑥, #293 seam 4).
 *
 * #293 立 the seam ONLY: a no-op hook the family spine calls at TWO points ADR
 * 0022 decision 3 names —
 *   - the per-wave barrier (decision 3④: run family verify, typecheck + unit
 *     tests, fail-fast — a red wave aborts BEFORE 排下一波), and
 *   - after all waves merge (decision 3⑤/⑥: the end-of-run 全量 verify + the
 *     load-bearing integrated cross-model cmr that catches 跨片接缝; the native
 *     pipeline has zero review).
 * The `phase` field tells #296 which of the two it is running.
 *
 * #293 keeps it a NO-OP so the spine wiring is proven (the hook is called at BOTH
 * points, with the context #296 needs, and the spine acts on `ok`) without
 * pulling verify/cmr into this slice — exactly the "本片不处理冲突、不跑 verify/cmr"
 * scope (#293 = the four seams, not their behaviour).
 *
 * #296 FILLS the hook body behind this SAME signature (it never rewrites the
 * family main loop — the spine already (a) passes the phase + context, (b)
 * fails-fast on `ok === false` at the wave barrier, (c) makes the failure
 * observable in the result):
 *   - "wave"  → run the family verify (typecheck + unit tests) against the family
 *     base; RED ⇒ `{ok:false}` (the spine aborts before the next wave) + an
 *     `aborted` ledger event (decision 3④/5).
 *   - "final" → run the FULL verify; green ⇒ run the two ADR 0030 integrated-cmr
 *     passes as ordered runner-dispatched boundaries: Step 5 completeness first,
 *     Step 6 correctness only after completeness passes. Each pass is a clean CMR
 *     reviewer over the current full family diff and returns a TERMINAL review
 *     verdict (`converged` | blocking findings | `escalate`). Blocking findings
 *     return to this runner, which records the review, dispatches a separate
 *     coder-fix worker for persistent repair commits, then dispatches a fresh CMR
 *     re-review over the current full diff. #878: when the fix leg completes but
 *     the observed family head did not advance, skip re-review and redispatch
 *     the fix leg (head position is scheduling plumbing, not judgment). Escalate
 *     / malformed / contract-slip verdicts are recorded as durable aborts and
 *     stop before ship. `verifyCmr` owns pass ordering and the ADR0032 strong-leg
 *     / required-leg degradation floor. #875 demolished the accounting court
 *     (leg-accounting death, claimed-fixed coverage audit, disposition-enum kill):
 *     envelope prose no longer aborts a live run. Three-channel routing stays
 *     (exit / findings count / decision gate) plus real infra durable abort.
 *
 * The verify / cmr / PR / abort / escalate capabilities are reached as OPTIONAL
 * methods on the injected `FamilyBackend` (the frozen spine input is `{phase,
 * familyBase, familyBackend}`). A backend that implements NONE of them — the #293
 * no-op default, the existing fakes — has no `runFamilyVerify`, so the hook returns
 * the nothing-ran no-op `{ok:true, ran:false}` and the spine's existing default
 * path stays untouched (zero regression). A backend that CAN verify but is missing
 * a required downstream final-barrier capability (cmr / PR) is the DIFFERENT case:
 * a real verify ran, so the hook fails-safe to `{ok:false, ran:true}` rather than a
 * false `success` — see `INCOMPLETE_GATE` below. The `aborted`/escalate SCHEMA
 * (`FamilyLedgerEntry` widening + the escalate/resume machine) is #298's (decision
 * 5 "字段级 JSON 留 TDD"); #296 only CALLS those seams. THAT is the seam boundary.
 */

import {
  deriveCmrEnvelope,
  type CmrEnvelope,
} from "./cmrClassification.js";
import type { FamilyModuleContext } from "./moduleDeclaration.js";
import { shWithClock } from "../externalCall.js";

import { isLiveGithubReviewPollEnabled, pollPrReviewState } from "../botPolling.js";
import {
  familyAutoMergeIncomplete,
  runFamilyAutoMergeStage,
} from "./familyAutoMerge.js";
import { buildCleanupLanding } from "../postMergeCleanup.js";
import {
  shouldReclaimFamilyHost,
} from "../hostReclaim.js";
import {
  buildRoundTrigger,
  convergenceHeadToRecord,
  inadmissibleWorkerOutcomeReason,
  workerOutcomeAdmissible,
  type RoundTrigger,
} from "../evidenceAdmissibility.js";
import {
  cleanupWorkerSpec,
  docReleaseWorkerSpec,
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
} from "../onlineReviewLoop.js";
import {
  mergePriorRoundFindings,
  priorCmrFindingsFromFamilyLedger,
  priorOnlineReviewFindingsFromFamilyLedger,
} from "../findingFamilies.js";
import { applyVerifySideEffects } from "../onlineReviewSideEffects.js";
import {
  isValidCleanupResult,
  isValidDocReleaseResult,
  isValidFixerResult,
  isValidVerifyResult,
} from "../reviewLoopOutcome.js";
import {
  familyCoderFixWorkerSpec,
  cmrWorkerSpec,
  dispatchFamilyWorker,
  dispatchFamilyWorkerWithMonitor,
  familyShipWorkerSpec,
} from "./dispatchFamilyWorker.js";
import {
  type DispatchOutcome,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../dispatchRetry.js";
import {
  requiredCmrLegSkipFailure,
  modelRouteFingerprint,
  resolveActiveModelRoute,
  smokeRouteModels,
  type ResolvedModelRoute,
} from "../modelRoutes.js";
import { hasAcceptedSuppressionAuthority } from "../acceptedSuppression.js";
import { modelFamilyForCmrReviewLeg } from "../modelRegistry.js";
import { modelIsStrongLeg } from "../realBackend.js";
import type {
  DispatchContext,
  EscalationAnswerPayload,
  FindingDisposition,
  FindingFamily,
  ShipResult,
  VerifyResult,
  WorkerLandingPayload,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../types.js";
import { findingIdentityKey } from "../findings.js";
import {
  buildReviewRoundStamp,
  readTelemetryRecords,
  scheduleCommitTelemetry,
  tryAppendTelemetryRecord,
  type TelemetryReviewRoundRecord,
} from "../telemetry.js";
import {
  cmrPassAlreadyPassed,
  recordAborted as recordDurableAbort,
  recordCmrFixCommitted,
  recordCmrPassed,
  recordCmrReviewed,
  recordOnlineReviewFixCommitted,
  recordOnlineReviewRoundRetrigger,
  recordReviewLoopConverged,
  familyShipCompletedRecord,
  recordShipDispatchReservation,
  recordShipDispatchAttempt,
  activeShipStreakId,
  recordShipStreakOpened,
  recordShipStreakClosed,
  recordShipCompleted,
  recordShipped,
  shipDispatchAttemptsSinceLatestCorrectnessCmrPass,
  unconfirmedShipReservationsSinceLatestCorrectnessCmrPass,
  familyPostMergeCleanupForHead,
  familyPrMergedForHead,
  mergedSet,
  recordPostMergeCleanup,
} from "./ledger.js";
import { isFilledString } from "../shipOutcome.js";
import {
  contractDriftStopSummary,
  decisionGateParkStopSummary,
  infraFailureStopSummary,
  successStopSummary,
  stopReasonForFindingDisposition,
  type StopSummary,
} from "../stopSummary.js";
import type {
  FamilyBackend,
  FamilyVerifyResult,
  IntegratedCmrPass,
} from "./types.js";

/** Which of the two ADR 0022 decision-3 verify points is running. */
export type VerifyCmrPhase = "wave" | "final";

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
   * The family seam #296 reaches the verify / integrated-cmr / open-PR / aborted
   * / escalate capabilities through (all OPTIONAL `FamilyBackend` methods). A
   * backend with NO `runFamilyVerify` yields the nothing-ran no-op `{ok:true,
   * ran:false}`; one that verifies green but lacks a required downstream capability
   * fails-safe to `{ok:false, ran:true}` (see `INCOMPLETE_GATE`). The CONCRETE
   * `aborted`/escalate schema (`FamilyLedgerEntry` widening + the escalate/resume
   * machine) is #298's (ADR 0022 decision 5, "字段级 JSON 留 TDD"); #296 only CALLS
   * `recordAborted` / `escalateFamily`.
   */
  readonly familyBackend: FamilyBackend;
  /** Invocation-scoped telemetry identity minted by runFamily. */
  readonly runId?: string;
  /** The family-startup-smoked route carried into every family worker dispatch. */
  readonly modelRoute?: ResolvedModelRoute;
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
   * (exit / findings count / decision gate) plus strong-leg floor, required-leg
   * degradation, and real infra durable abort.
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
   * the wave barrier (decision 3④) / returns `verify_failed` at the final barrier,
   * so #296 only RETURNS the verdict — it does not touch the spine.
   */
  readonly ok: boolean;
  /**
   * Whether any real verify/cmr work actually ran. `false` ⇒ the no-op path (the
   * backend lacks the capability — a #293-era backend), so a `{ok:true, ran:false}`
   * is honestly "nothing verified", NOT a claimed pass.
   */
  readonly ran: boolean;
}

/** The no-op verdict: the backend has no verify capability (the #293 default). */
const NOOP: VerifyCmrResult = { ok: true, ran: false };

/**
 * The fail-safe verdict for a backend that DID verify (green) but is missing a
 * REQUIRED downstream final-barrier capability (the integrated cmr 承重闸, or the
 * 止于-PR step after a converged cmr). It is NOT the #293 no-op: a real verify
 * already ran, so reporting `{ok:true}` would make the spine's `finalize()` treat
 * the final barrier as PASSED and the run as `"success"` — shipping code the
 * load-bearing integrated cmr never reviewed (decision 3⑥) / a run whose terminal
 * PR (decision 4) never opened. The spine ignores `ran` and acts on `ok` alone, so
 * the only fail-safe is `ok:false` (the run surfaces `verify_failed`/`failedPhase:
 * "final"`, never a false `success` — decision 3⑤ "不静默吞"). `ran:true` records
 * that real verify work DID happen (this is not the nothing-ran no-op).
 */
const INCOMPLETE_GATE: VerifyCmrResult = { ok: false, ran: true };
const OUTCOME_REWRITE_RETRY_CAP = 2;
const FINDINGS_SUPPLEMENT_RETRY_CAP = 3;

async function runFamilyVerifyOrAbort(input: {
  readonly phase: VerifyCmrPhase;
  readonly familyBase: string;
  readonly familyBackend: FamilyBackend;
  readonly familyHeadAfter?: string;
  readonly runId?: string;
  readonly familyIssue?: number;
}): Promise<VerifyCmrResult | undefined> {
  const { phase, familyBase, familyBackend, familyHeadAfter } = input;
  const verify: FamilyVerifyResult = await familyBackend.runFamilyVerify!({
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
  return { ok: false, ran: true };
}

/** ADR0032 floor: at least one successful CMR leg must be registry-marked strong. */
export function meetsCmrFloor(successfulLegs: readonly string[]): boolean {
  return successfulLegs.some(modelIsStrongLeg);
}

/**
 * Strong-leg floor credit: only route-declared successful legs count.
 * #875 demolished leg-accounting death (undeclared extras no longer kill), but
 * the retained floor must still mean "a route-selected strong leg ran" — an
 * undeclared strong slug cannot satisfy the floor by itself.
 */
function routeDeclaredSuccessfulLegs(
  successfulLegs: readonly string[],
  resolvedRoute: ResolvedModelRoute,
): readonly string[] {
  const declared = new Set(
    resolvedRoute.legCollections.cmrReview.map((leg) => leg.slug),
  );
  return successfulLegs.filter((slug) => declared.has(slug));
}

function cmrFloorFailureReason(input: {
  readonly pass: IntegratedCmrPass;
  readonly successfulLegs: readonly string[] | undefined;
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
  readonly resolvedRoute: ResolvedModelRoute;
}): string | undefined {
  const successfulLegs = input.successfulLegs;
  if (successfulLegs == null || successfulLegs.length === 0) {
    return `integrated cmr ${input.pass} floor failed: no successful leg set was reported`;
  }
  const creditedLegs = routeDeclaredSuccessfulLegs(
    successfulLegs,
    input.resolvedRoute,
  );
  if (meetsCmrFloor(creditedLegs)) return undefined;
  const skipped =
    input.skippedLegs != null && input.skippedLegs.length > 0
      ? `; skipped legs: ${input.skippedLegs
          .map((leg) => `${leg.slug} (${leg.reason})`)
          .join(", ")}`
      : "";
  return (
    `integrated cmr ${input.pass} floor failed: route-declared successful legs [` +
    `${creditedLegs.join(", ")}] include no strong leg` +
    (creditedLegs.length === successfulLegs.length
      ? ""
      : ` (reported [${successfulLegs.join(", ")}]; undeclared legs do not credit the floor)`) +
    skipped
  );
}

function providerDegradedFloorStopSummary(input: {
  readonly reason: string;
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
}): StopSummary {
  const providerDegraded =
    input.skippedLegs != null && input.skippedLegs.length > 0
      ? input.skippedLegs.map((leg) =>
          skippedLegProviderDegradation(leg, {
            blocking: true,
            repairHint: `restore provider availability for ${leg.slug} and rerun the CMR gate`,
          }),
        )
      : [
          {
            reason: input.reason,
            blocking: true,
            repairHint: "restore a route-selected strong CMR provider leg and rerun the gate",
          },
        ];

  return {
    reason: "provider_degraded",
    summary: input.reason,
    repairHint: "restore the required CMR provider leg coverage and rerun",
    metadata: { providerDegraded },
  };
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
    return infraFailureStopSummary({
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
  if (input.skippedLegs == null || input.skippedLegs.length === 0) {
    return undefined;
  }
  return successStopSummary({
    ...(input.familyHeadAfter != null
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

function shipWorkerContractDriftStopSummary(input: {
  readonly reason: string;
  readonly latestVerifiedCmrHead?: string;
  readonly currentFamilyHead?: string;
  readonly reportedFamilyHead?: string;
  readonly shipPrState: string;
}): StopSummary {
  return contractDriftStopSummary({
    summary: input.reason,
    repairHint:
      "preserve the latest verified CMR head and rerun ship after repairing the worker contract",
    ship: {
      ...(input.latestVerifiedCmrHead != null
        ? { latestVerifiedCmrHead: input.latestVerifiedCmrHead }
        : {}),
      ...(input.currentFamilyHead != null
        ? { currentFamilyHead: input.currentFamilyHead }
        : {}),
      ...(input.reportedFamilyHead != null
        ? { reportedFamilyHead: input.reportedFamilyHead }
        : {}),
      shipPrState: input.shipPrState,
    },
    heads: {
      ...(input.currentFamilyHead != null
        ? { actualFamilyHead: input.currentFamilyHead }
        : {}),
      ...(input.reportedFamilyHead != null
        ? { reportedFamilyHead: input.reportedFamilyHead }
        : {}),
      ...(input.latestVerifiedCmrHead != null
        ? { verifiedCmrHead: input.latestVerifiedCmrHead }
        : {}),
      sources: {
        actualFamilyHead: "family head after ship worker contract drift",
        reportedFamilyHead: "ship worker reported state",
        verifiedCmrHead: "latest cmr_passed ledger row",
      },
    },
  });
}

function shipWorkerFailedStopSummary(input: {
  readonly reason: string;
  readonly latestVerifiedCmrHead?: string;
  readonly currentFamilyHead?: string;
  readonly reportedFamilyHead?: string;
  readonly shipPrState: string;
}): StopSummary {
  if (
    /\b(auth|permission|push|transport|network|MODULE_NOT_FOUND|Cannot find module|dependency|build|test|toolchain|git)\b/i.test(
      input.reason,
    )
  ) {
    return infraFailureStopSummary({
      summary: input.reason,
      repairHint:
        "repair the family ship worker infrastructure/auth/toolchain failure and rerun the final family barrier",
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
    });
  }
  return shipWorkerContractDriftStopSummary(input);
}

function familyCmrBlockingStopSummary(
  classification: CmrEnvelope,
  fallbackReason: string,
): StopSummary {
  // #604 slice 4 (ADR 0062): routing classification values are gone, so there is
  // one blocking bucket. The stop-summary word stays `same_module_still_red`
  // (the retained StopReason for "blocking, fix it and rerun" — 岔路 1 A: the
  // StopReason machinery is untouched).
  const result = classification.results.find(
    (item) => item.classification === "blocking",
  );
  const finding =
    result !== undefined
      ? classification.blocking.find(
          (item) => findingIdentityKey(item) === result.identityKey,
        )
      : undefined;
  if (result !== undefined && finding !== undefined) {
    return stopReasonForFindingDisposition({
      kind: "same_module",
      finding,
      reason: result.reason || fallbackReason,
    });
  }
  return {
    reason: "same_module_still_red",
    summary: result?.reason || fallbackReason,
    repairHint: "fix the blocking family CMR finding and rerun",
  };
}

function familyCmrPassStopSummary(input: {
  readonly classification?: CmrEnvelope;
  readonly familyHeadAfter?: string;
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
}): StopSummary | undefined {
  const acceptedSuppressions = input.classification?.dispositions
    .filter(hasAcceptedSuppressionAuthority)
    .map((disposition) => ({
      source: disposition.source!,
      scope: disposition.scope!,
      reason: disposition.reason!,
      findingIdentity: disposition.identityKey,
      boundedReopen: disposition.boundedReopen!,
    }));
  const materialPassSummary = successStopSummary({
    ...(input.familyHeadAfter != null
      ? {
          heads: {
            verifiedCmrHead: input.familyHeadAfter,
            sources: { verifiedCmrHead: "cmr_passed ledger row" },
          },
        }
      : {}),
    ...(acceptedSuppressions != null && acceptedSuppressions.length > 0
      ? { acceptedSuppressions }
      : {}),
    ...(input.skippedLegs != null && input.skippedLegs.length > 0
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
  // #604 slice 4 (ADR 0062): the `cross_module_defer` classification is gone and
  // `deferred` is always empty, so there is no cross-module pass-with-defer path
  // to emit here — a passing family CMR run reports success/accepted-suppression
  // metadata only.
  if (
    (acceptedSuppressions === undefined || acceptedSuppressions.length === 0) &&
    (input.skippedLegs === undefined || input.skippedLegs.length === 0)
  ) {
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
    return infraFailureStopSummary({
      summary: reason,
      repairHint:
        "install or restore the missing verification dependency, rebuild if needed, then rerun family verify",
    });
  }
  return infraFailureStopSummary({
    summary: reason,
    repairHint:
      "inspect the family verify failure, repair the failing toolchain command, and rerun",
  });
}

function notConvergedStopSummary(reason: string): StopSummary {
  return {
    reason: "contract_drift",
    summary: `integrated CMR did not converge: ${reason}`,
    repairHint: "continue the CMR fix loop until the pass converges",
  };
}

function cmrEscalationStopSummary(reason: string): StopSummary {
  return {
    reason: "spec_conflict",
    summary: reason,
    repairHint:
      "resolve the CMR worker's design/specification conflict and rerun the family CMR gate",
  };
}

export function latestFamilyCmrDispositions(
  ledger: ReadonlyArray<{
    readonly cmrDispositions?: ReadonlyArray<FindingDisposition>;
  }>,
): ReadonlyArray<FindingDisposition> | undefined {
  // #604 slice 3 / ADR 0062: cross-round prior dispositions are read from the thin
  // `cmrDispositions` governance field, not the retired `cmrFindingClassification`
  // blob.
  //
  // #604 rework (codexB): SKIP defined-but-EMPTY tombstones. A not_converged
  // abort used to persist `cmrDispositions: []`; because this scan returned the
  // first DEFINED array from the end, that empty tombstone masked an earlier
  // round's real accepted-suppression dispositions → next pass saw no prior →
  // budget reset (C1-class recurrence). An empty array is never the authoritative
  // "there were suppressions but now there are none" signal in this codebase, so
  // skipping it is safe and keeps cross-round budget tracking intact. The
  // abort-side fix (aborts no longer write `[]` at all) is the root cause; this
  // read-side guard is defense-in-depth so no other entry point can re-introduce
  // the masking.
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.cmrDispositions != null && entry.cmrDispositions.length > 0) {
      return entry.cmrDispositions;
    }
  }
  return undefined;
}

interface IntegratedCmrPassOutcome {
  readonly result: VerifyCmrResult;
  readonly familyHeadAfter?: string;
  readonly restartFinalBarrier?: {
    readonly familyHeadAfter?: string;
    readonly priorCmrFindingIdentityKeysByPass: Partial<
      Record<IntegratedCmrPass, readonly string[]>
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
      ...(input.familyHeadBefore != null
        ? { reportedFamilyHead: input.familyHeadBefore }
        : {}),
      ...(input.familyHeadAfter != null
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
  readonly classification: CmrEnvelope;
  readonly blockingFindingIdentityKeys: readonly string[];
  readonly findingFamilies?: ReadonlyArray<FindingFamily>;
  readonly familyHeadBefore?: string;
  readonly escalationAnswer?: EscalationAnswerPayload;
  readonly familyIssue?: number;
  readonly resolvedRoute: ResolvedModelRoute;
}): Promise<IntegratedCmrPassOutcome> {
  const {
    pass,
    familyBackend,
    familyBase,
    runId,
    classification,
    blockingFindingIdentityKeys,
    findingFamilies,
    familyHeadBefore,
    escalationAnswer,
    familyIssue,
    resolvedRoute,
  } = input;
  const reasonPrefix =
    `integrated cmr ${pass} coder-fix for ` +
    blockingFindingIdentityKeys.join(", ");

  const currentFamilyHeadBefore = familyHeadBefore;
  let telemetryFamilyHeadBefore = familyHeadBefore;
  const coderFixSpec = familyCoderFixWorkerSpec(resolvedRoute);
  const fixResult = await dispatchOrAbort(
    familyBackend,
    coderFixSpec,
      {
        familyBase,
        ...(runId !== undefined ? { runId } : {}),
        modelRoute: resolvedRoute,
        // 信封宪法 (ADR 0062): only identity keys + count on the dispatch structure;
        // rich finding content travels in the separate landing payload below.
        blockingFindingIdentityKeys,
        blockingFindingCount: classification.blocking.length,
        ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
        ...(familyIssue !== undefined ? { familyIssue } : {}),
      },
      {
        blockingFindings: classification.blocking,
        ...(findingFamilies !== undefined ? { findingFamilies } : {}),
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
      const reason = `${reasonPrefix} escalated: ${fixResult.escalation.reason} — ${fixResult.escalation.diagnosis}`;
      const stopSummary = coderFixFailureStopSummary({
        pass,
        reason,
        familyHeadBefore: currentFamilyHeadBefore,
        familyHeadAfter,
      });
      await familyBackend.escalateFamily?.({
        reason,
        familyHeadAfter,
        stopSummary,
      });
      await recordDurableAbort(familyBackend, {
        phase: "final",
        cmrPass: pass,
        reason,
        familyHeadAfter,
        stopSummary,
      });
      return { result: { ok: false, ran: true }, familyHeadAfter };
    }

  if (fixResult.kind !== "completed" || fixResult.output.kind !== "coder") {
      const reason =
        fixResult.kind === "failed"
          ? `${reasonPrefix} failed: ${fixResult.reason}`
          : fixResult.kind === "malformed"
            ? `${reasonPrefix} malformed: ${fixResult.reason}`
            : fixResult.kind === "outcome_protocol_failure"
              ? `${reasonPrefix} outcome protocol failure: ${fixResult.reason}`
              : `${reasonPrefix} returned no valid coder result`;
      await recordDurableAbort(familyBackend, {
        phase: "final",
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
      return { result: { ok: false, ran: true }, familyHeadAfter };
  }

  if (fixResult.output.escalate !== undefined) {
      const reason =
        `${reasonPrefix} escalated: ${fixResult.output.escalate.reason} — ` +
        fixResult.output.escalate.diagnosis;
      const stopSummary = coderFixFailureStopSummary({
        pass,
        reason,
        familyHeadBefore: currentFamilyHeadBefore,
        familyHeadAfter,
      });
      await familyBackend.escalateFamily?.({
        reason,
        familyHeadAfter,
        stopSummary,
      });
      await recordDurableAbort(familyBackend, {
        phase: "final",
        cmrPass: pass,
        reason,
        familyHeadAfter,
        stopSummary,
      });
      return { result: { ok: false, ran: true }, familyHeadAfter };
  }

  const repairObservationAdvisory =
    fixResult.output.selfReportDiscrepancy !== undefined ||
    currentFamilyHeadBefore === undefined ||
    familyHeadAfter === undefined;

  await recordCmrFixCommitted(familyBackend, {
    cmrPass: pass,
    familyHeadBefore: currentFamilyHeadBefore,
    familyHeadAfter,
    blockingFindingIdentityKeys,
    reason:
      repairObservationAdvisory
        ? `${reasonPrefix}: coder-fix attempted; telemetry family/git observation advisory` +
          (fixResult.output.selfReportDiscrepancy !== undefined
            ? `; warning ${fixResult.output.selfReportDiscrepancy.code} ` +
              `(reported ${fixResult.output.selfReportDiscrepancy.selfReportedCommitsAdded}, ` +
              `git observed ${fixResult.output.selfReportDiscrepancy.gitCommitCount})`
            : "")
        : fixResult.output.committed && fixResult.output.commitsAdded >= 1
        ? `${reasonPrefix}: coder-fix committed ${fixResult.output.commitsAdded} ` +
          `commit${fixResult.output.commitsAdded === 1 ? "" : "s"}`
        : currentFamilyHeadBefore !== undefined &&
            familyHeadAfter !== undefined &&
            currentFamilyHeadBefore === familyHeadAfter
          ? `${reasonPrefix}: coder-fix left family head unmoved; redispatch fix (skip re-review)`
          : `${reasonPrefix}: coder-fix reported no commit; fresh reviewer will judge findings`,
  });
  return { result: { ok: true, ran: true }, familyHeadAfter };
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

/** Best-effort tracked status for online-review verify guard (skip when unreadable). */
async function readOnlineVerifyTrackedStatus(
  familyBackend: FamilyBackend,
  familyBase: string,
): Promise<readonly string[] | undefined> {
  if (familyBackend.readFamilyTrackedStatus === undefined) {
    return undefined;
  }
  try {
    return await readPostCmrTrackedStatus(familyBackend, familyBase);
  } catch {
    return undefined;
  }
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
 * the pass continues on the three channels (exit / findings count / decision
 * gate). Only a broken reader (true infra) still durable-aborts.
 *
 * Returns an abort outcome only for infra read failures; otherwise `undefined`
 * so the caller keeps the normal finding/fix/re-review path.
 */
async function guardPostCmrReviewerGitState(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly pass: IntegratedCmrPass;
  readonly expectedFamilyHead?: string;
  readonly familyHeadAfter?: string;
}): Promise<IntegratedCmrPassOutcome | undefined> {
  const {
    familyBackend,
    familyBase,
    pass,
    expectedFamilyHead,
    familyHeadAfter,
  } = input;
  let currentHead: string | undefined;
  try {
    currentHead = await readPostCmrCurrentHead(familyBackend);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    const reason = `integrated CMR ${pass} current HEAD read failed: ${detail}`;
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter,
      stopSummary: infraFailureStopSummary({
        summary: reason,
        repairHint:
          "repair the family current-HEAD reader before trusting the CMR reviewer ref guard",
      }),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter };
  }
  if (
    currentHead !== undefined &&
    familyHeadAfter !== undefined &&
    currentHead !== familyHeadAfter
  ) {
    // #876: checkout ≠ family base is advisory routing telemetry, not conviction.
    await familyBackend.appendFamilyLedger({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: `cmr:${pass}`,
      reason:
        `integrated CMR ${pass} reviewer checked out a different HEAD: ` +
        `family base ${familyHeadAfter}, current HEAD ${currentHead}`,
    });
  }
  let trackedStatus: readonly string[];
  try {
    trackedStatus = await readPostCmrTrackedStatus(familyBackend, familyBase);
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    const reason = `integrated CMR ${pass} tracked status read failed: ${detail}`;
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter,
      stopSummary: infraFailureStopSummary({
        summary: reason,
        repairHint:
          "repair the family tracked-status reader before trusting the CMR reviewer cleanliness gate",
      }),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter };
  }
  if (
    expectedFamilyHead !== undefined &&
    familyHeadAfter !== undefined &&
    familyHeadAfter !== expectedFamilyHead
  ) {
    // #876: family-base HEAD advancement is routing plumbing (diff scope for the
    // next pass / coder-fix), never a contract_drift death.
    await familyBackend.appendFamilyLedger({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: `cmr:${pass}`,
      reason:
        `integrated CMR ${pass} reviewer moved family HEAD: ` +
        `${expectedFamilyHead} -> ${familyHeadAfter}`,
    });
  }
  if (trackedStatus.length > 0) {
    const reason =
      `integrated CMR ${pass} reviewer left tracked changes: ` +
      trackedStatus.join("; ");
    await familyBackend.appendFamilyLedger({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: `cmr:${pass}`,
      reason,
    });
    // #853: reviewer edits are ordinary diff content. Preserve them for the
    // current round's normal finding/fix/re-review path; never abort or discard.
  }
  return undefined;
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

function describeShipPrState(ship: {
  readonly branch?: string;
  readonly status?: string;
  readonly pr?: string;
}): string {
  return [
    `branch=${isFilledString(ship.branch) ? ship.branch : "missing"}`,
    `status=${isFilledString(ship.status) ? ship.status : "missing"}`,
    `pr=${isFilledString(ship.pr) ? ship.pr : "missing"}`,
  ].join(" ");
}

/**
 * Dispatch a family worker, converting ANY thrown STARTUP error into a documented
 * gate result instead of letting it escape verifyCmr (cmr S336 r8 — startup/error
 * path audit). The single-slice runner wraps its S7 ship dispatch in
 * try/catch → S8(error); the family verifyCmr did NOT, so a worker that threw on
 * startup — a missing-auth `sc.run` start failure (now preflighted to a structured
 * escalate, but the worker ALSO `git checkout`s the family base + writes the focus
 * file + spins docker, any of which can still throw) — would propagate out of
 * `runVerifyCmr` and reject the WHOLE family run, bypassing the INCOMPLETE_GATE
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
    return reviewLoop.stopSummary;
  }
  const reason =
    reviewLoop.terminalState === "round_budget_exhausted"
      ? "family online review loop exhausted the 3-round budget"
      : "family online review loop did not converge";
  return infraFailureStopSummary({
    summary: `${reason} (terminal: ${reviewLoop.terminalState})`,
    repairHint: "resolve remaining online review findings or answer the decision gate",
  });
}

async function dispatchFamilyReviewWorker(
  familyBackend: FamilyBackend,
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
  opts?: {
    readonly afterEachAttempt?: () => Promise<void>;
    readonly extraCallerOwns?: (outcome: DispatchOutcome) => boolean;
  },
): Promise<WorkerResult> {
  const primary = await dispatchOrAbort(
    familyBackend,
    spec,
    ctx,
    landing,
    opts,
  );
  if (workerOutcomeAdmissible(primary, spec)) {
    return primary;
  }
  if (primary.kind === "escalated") {
    return primary;
  }
  if (
    primary.kind === "failed" ||
    primary.kind === "malformed" ||
    primary.kind === "outcome_protocol_failure"
  ) {
    return primary;
  }
  return {
    kind: "failed",
    reason: inadmissibleWorkerOutcomeReason(primary, spec),
  };
}

export async function runFamilyOnlineReviewLoop(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId?: string;
  readonly ship: ShipResult;
  readonly resolvedRoute?: ResolvedModelRoute;
  readonly escalationAnswer?: EscalationAnswerPayload;
}): Promise<OnlineReviewLoopStageResult> {
  const repo =
    process.env.ORCHESTRATOR_REPO?.trim() ?? "Akagilnc/ming-salvage-sim";
  const prUrl = input.ship.pr;
  if (prUrl == null || prUrl.trim().length === 0) {
    return { ok: false, terminalState: "decision_gate_raised", round: 1 };
  }
  const ghSh = (file: string, args: string[]) =>
    // Mixed poll + side-effect writes; no mutation auto-retry (#884 cmr r7).
    shWithClock(file, args, { stage: `dispatch:${file}`, retry: false });
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
      stopSummary: {
        reason: "infra_failure",
        summary: `family online-review route smoke failed: ${err instanceof Error ? err.message : String(err)}`,
        repairHint: "provide the family startup-smoked model route before dispatching online review workers",
      },
    };
  }
  const baseCtx: DispatchContext = {
    familyBase: input.familyBase,
    ...(input.runId !== undefined ? { runId: input.runId } : {}),
    modelRoute,
    repo,
    prUrl,
    prHead: input.ship.prHead,
    ...(input.escalationAnswer !== undefined
      ? { escalationAnswer: input.escalationAnswer }
      : {}),
  };

  const livePoll = isLiveGithubReviewPollEnabled(prUrl, repo);
  const familyLedger = await input.familyBackend.readFamilyLedger();
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
      stopSummary: {
        reason: "infra_failure",
        summary: `family online review round-trigger setup failed: ${err instanceof Error ? err.message : String(err)}`,
        repairHint:
          "repair ledger round-trigger / fix-gap anchors and re-feed the family run",
      },
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
      const headBefore = await readRequiredFamilyHead(
        input.familyBackend,
        input.familyBase,
      );
      const trackedBefore = await readOnlineVerifyTrackedStatus(
        input.familyBackend,
        input.familyBase,
      );
      const assertFamilyVerifyReadOnlyContract = async (): Promise<void> => {
        const headAfter = await readRequiredFamilyHead(
          input.familyBackend,
          input.familyBase,
        );
        const trackedAfter = await readOnlineVerifyTrackedStatus(
          input.familyBackend,
          input.familyBase,
        );
        // #876: HEAD movement is routing plumbing (diff scope for the next
        // fixer/verify round), never a contract_drift capital crime.
        if (
          headBefore !== undefined &&
          headAfter !== undefined &&
          headAfter !== headBefore
        ) {
          await input.familyBackend.appendFamilyLedger({
            status: "worker_dispatched",
            event: "worker_dispatched",
            workerStep: `online-verify:${round}`,
            reason:
              `online review verify worker moved HEAD: ${headBefore} -> ${headAfter}`,
          });
        }
        if (
          trackedBefore !== undefined &&
          trackedAfter !== undefined &&
          trackedAfter.join("\n") !== trackedBefore.join("\n")
        ) {
          await input.familyBackend.appendFamilyLedger({
            status: "worker_dispatched",
            event: "worker_dispatched",
            workerStep: `online-verify:${round}`,
            reason: `online review verify worker left tracked changes: ${trackedAfter.join("; ")}`,
          });
        }
      };
      const result = await dispatchFamilyReviewWorker(
        input.familyBackend,
        verifyWorkerSpec(input.resolvedRoute),
        { ...baseCtx, onlineReviewRound: round },
        landing,
        {
          afterEachAttempt: assertFamilyVerifyReadOnlyContract,
        },
      );
      // Cursor R11 medium + self-check: escalated must park with decision_gate_park
      // + escalate payload text — not a bare decision_gate_raised that drops reason.
      if (result.kind === "escalated") {
        const escalationSummary = `family verify worker escalated: ${result.escalation.reason} — ${result.escalation.diagnosis}`;
        const stopSummary =
          result.escalation.synthesizedFailure === true
            ? infraFailureStopSummary({
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
      if (result.kind !== "completed" || !isValidVerifyResult(result.output)) {
        const detail =
          result.kind === "failed" || result.kind === "malformed"
            ? `: ${result.reason}`
            : "";
        throw new OnlineReviewLoopTerminal({
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary: infraFailureStopSummary({
            summary: `family verify worker returned ${result.kind}${detail}`,
            repairHint:
              "inspect the verify worker envelope and re-feed the family online review loop",
          }),
        });
      }
      return result.output;
    },
    dispatchFixer: async (landing: WorkerLandingPayload) => {
      const round = landing.onlineReviewRound ?? baseCtx.onlineReviewRound ?? 1;
      lastFixMarkedFindingIdentityKeys =
        landing.fixMarkedFindingIdentityKeys ?? [];
      lastFixMarkedFindingThreads = landing.fixMarkedFindingThreads ?? [];
      lastFixerOnlineReviewRound = round;
      const result = await dispatchFamilyReviewWorker(
        input.familyBackend,
        fixerWorkerSpec(input.resolvedRoute),
        baseCtx,
        landing,
      );
      if (result.kind === "escalated") {
        const escalationSummary = `family fixer worker escalated: ${result.escalation.reason} — ${result.escalation.diagnosis}`;
        throw new OnlineReviewLoopTerminal({
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary:
            result.escalation.synthesizedFailure === true
              ? infraFailureStopSummary({
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
      if (result.kind !== "completed" || !isValidFixerResult(result.output)) {
        const detail =
          result.kind === "failed" || result.kind === "malformed"
            ? `: ${result.reason}`
            : "";
        throw new OnlineReviewLoopTerminal({
          ok: false,
          terminalState: "decision_gate_raised",
          round,
          stopSummary: infraFailureStopSummary({
            summary: `family fixer worker returned ${result.kind}${detail}`,
            repairHint:
              "inspect the fixer worker envelope and re-feed the family online review loop",
          }),
        });
      }
      return result.output;
    },
    // #740: family + single-slice S12 crash-retry both continue-as-is (no
    // scoped cleanResidue / resetBeforeRetry). Do not reintroduce a one-sided
    // reset on either path — same user override as #600 / 21906adf.
    dispatchDocRelease: async (landing: WorkerLandingPayload) => {
      const result = await dispatchFamilyReviewWorker(
        input.familyBackend,
        docReleaseWorkerSpec(input.resolvedRoute),
        baseCtx,
        landing,
      );
      return (
        result.kind === "completed" &&
        isValidDocReleaseResult(result.output) &&
        result.output.released
      );
    },
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
        initialFixCommitSha: loopState.lastFixSha,
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

async function dispatchOrAbort(
  familyBackend: FamilyBackend,
  spec: Parameters<typeof dispatchFamilyWorker>[1],
  ctx: Parameters<typeof dispatchFamilyWorker>[2],
  landing?: Parameters<typeof dispatchFamilyWorker>[3],
  opts?: {
    readonly afterEachAttempt?: () => Promise<void>;
    readonly extraCallerOwns?: (outcome: DispatchOutcome) => boolean;
  },
): Promise<Awaited<ReturnType<typeof dispatchFamilyWorker>>> {
  try {
    // #598 / 2026-07-08: a family worker that CRASHES (throws) re-dispatches a fresh
    // session on the CURRENT worktree as-is, up to MAX_DISPATCH_ATTEMPTS — every role,
    // read-only and write-capable alike. Every RESOLVED result (failed / malformed /
    // completed / escalated) is DEFERRED to this gate's own rich terminal handling.
    return await withMechanicalRetry(
      spec,
      ctx,
      async (s, c) => {
        let dispatchError: unknown | undefined;
        let workerResult: Awaited<ReturnType<typeof dispatchFamilyWorker>>;
        try {
          const monitored = await dispatchFamilyWorkerWithMonitor(
            familyBackend,
            s,
            c,
            landing,
            {
              onMonitorHandleSpawned: async (handle: WorkerMonitorHandle) => {
                // Persist before waiting for the child: a hung family worker
                // must be resumable/judgable from the durable family ledger.
                try {
                  await familyBackend.appendFamilyLedger({
                    status: "worker_dispatched",
                    event: "worker_dispatched",
                    monitorHandle: handle,
                  });
                } catch {
                  // Best-effort, matching the single-slice path. The spawned
                  // worker remains governed by its verified monitor handle.
                }
              },
            },
          );
          workerResult = monitored.result;
          await monitored.telemetryEnvironmentStamp;
        } catch (err) {
          dispatchError = err;
        }
        // Always assert (online R10 Codex P1 / parity with single-slice S9):
        // mutate-then-throw → contract_drift, not retry on dirty worktree.
        await opts?.afterEachAttempt?.();
        if (dispatchError !== undefined) throw dispatchError;
        return workerResult!;
      },
      {
        callerOwns: (o) =>
          opts?.extraCallerOwns?.(o) === true ||
          // Only the integrated CMR reviewer path has a follow-up loop for
          // malformed outcomes (`rewriteOutcomeProtocolFailure`); every other
          // family worker's caller would just abort on them, so those retry
          // mechanically like any transient failure.
          (spec.kind === "cmr" &&
            "result" in o &&
            (o.result.kind === "malformed" ||
              o.result.kind === "outcome_protocol_failure")),
        onFailure: async (outcome, attempt) => {
          const reason =
            "result" in outcome
              ? outcome.result.kind === "failed" ||
                  outcome.result.kind === "malformed" ||
                  outcome.result.kind === "outcome_protocol_failure"
                ? outcome.result.reason
                : `worker returned ${outcome.result.kind}`
              : outcome.error instanceof Error
                ? outcome.error.message
                : String(outcome.error);
          await familyBackend.appendFamilyLedger({
            status: "worker_dispatched",
            event: "worker_dispatched",
            workerStep: `${spec.kind}${ctx.cmrPass !== undefined ? `:${ctx.cmrPass}` : ""}`,
            mechanicalRedispatchAttempt: attempt,
            reason,
          });
        },
        rethrowOnExhaustion: true,
      },
    );
  } catch (err) {
    if (err instanceof OnlineReviewLoopTerminal) throw err;
    const reason = `family ${spec.kind} worker threw on startup: ${
      err instanceof Error ? err.message : String(err)
    }`;
    return { kind: "failed", reason };
  }
}

/**
 * Ship mutates remote state, so it deliberately bypasses `withMechanicalRetry`.
 * The caller writes its durable attempt marker first and observes host truth after
 * any thrown return path before deciding whether a replacement is safe.
 */
async function dispatchShipOnce(
  familyBackend: FamilyBackend,
  spec: Parameters<typeof dispatchFamilyWorker>[1],
  ctx: Parameters<typeof dispatchFamilyWorker>[2],
  shipDispatchId: string,
): Promise<{
  readonly result?: Awaited<ReturnType<typeof dispatchFamilyWorker>>;
  readonly launchConfirmed: boolean;
}> {
  let launchConfirmed = false;
  try {
    const monitored = await dispatchFamilyWorkerWithMonitor(
      familyBackend,
      spec,
      ctx,
      undefined,
      {
        onDispatchConfirmed: async () => {
          await recordShipDispatchAttempt(familyBackend, {
            phase: "final",
            shipDispatchId,
          });
          launchConfirmed = true;
        },
        onMonitorHandleSpawned: async (handle: WorkerMonitorHandle) => {
          try {
            await familyBackend.appendFamilyLedger({
              status: "worker_dispatched",
              event: "worker_dispatched",
              monitorHandle: handle,
            });
          } catch {
            // Best effort, matching the generic family dispatch path.
          }
        },
      },
    );
    await monitored.telemetryEnvironmentStamp;
    return { result: monitored.result, launchConfirmed };
  } catch {
    return { launchConfirmed };
  }
}

async function rewriteOutcomeProtocolFailure(input: {
  readonly familyBackend: FamilyBackend;
  readonly spec: WorkerSpec;
  readonly ctx: DispatchContext;
  readonly result: WorkerResult;
}): Promise<WorkerResult> {
  if (input.result.kind !== "malformed") return input.result;
  // #875: former cmrLegAccountingPayload short-circuit removed with the court;
  // sloppy leg lists no longer arrive as special malformed payloads.
  if (input.familyBackend.rewriteWorkerOutcome === undefined) {
    return {
      kind: "outcome_protocol_failure",
      reason:
        `worker outcome protocol failure could not be rewritten: ` +
        `backend has no same-worker outcome rewrite capability; original failure: ` +
        input.result.reason,
      attempts: 0,
      ...(input.result.sessionId !== undefined
        ? { sessionId: input.result.sessionId }
        : {}),
    };
  }

  let lastFailure: Extract<WorkerResult, { kind: "malformed" }> = input.result;
  const retryCap = input.result.cmrPriorOutput !== undefined
    ? FINDINGS_SUPPLEMENT_RETRY_CAP
    : OUTCOME_REWRITE_RETRY_CAP;
  for (let attempt = 1; attempt <= retryCap; attempt++) {
    if (input.result.cmrPriorOutput !== undefined) {
      await input.familyBackend.appendFamilyLedger({
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: `${input.spec.kind}:${input.ctx.cmrPass ?? "legacy"}:findings-supplement`,
        mechanicalRedispatchAttempt: attempt,
        reason: lastFailure.reason,
      });
    }
    let rewritten: WorkerResult;
    try {
      rewritten = await input.familyBackend.rewriteWorkerOutcome(
        input.spec,
        input.ctx,
        lastFailure,
        attempt,
      );
    } catch (err) {
      const sessionId = lastFailure.sessionId ?? input.result.sessionId;
      return {
        kind: "outcome_protocol_failure",
        reason:
          `worker outcome protocol rewrite threw on attempt ${attempt}: ` +
          `${err instanceof Error ? err.message : String(err)}; original failure: ` +
          lastFailure.reason,
        attempts: attempt,
        ...(sessionId !== undefined ? { sessionId } : {}),
      };
    }
    if (rewritten.kind !== "malformed") return rewritten;
    lastFailure = rewritten;
  }

  const sessionId = lastFailure.sessionId ?? input.result.sessionId;
  if (input.result.cmrPriorOutput !== undefined) {
    return {
      kind: "escalated",
      escalation: {
        reason: "reviewer omitted findings = x after 3 supplement attempts",
        diagnosis:
          "The semantic review is complete, but its constitutional findings count is still missing; a human decision is required.",
      },
      ...(sessionId !== undefined ? { sessionId } : {}),
    };
  }
  return {
    kind: "outcome_protocol_failure",
    reason:
      `worker outcome protocol failure persisted after ` +
      `${retryCap} same-reviewer supplement attempts: ` +
      lastFailure.reason,
    attempts: OUTCOME_REWRITE_RETRY_CAP,
    ...(sessionId !== undefined ? { sessionId } : {}),
  };
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
    const output =
      input.result.kind === "completed" && input.result.output.kind === "cmr"
        ? input.result.output
        : undefined;
    const workerVerdict =
      input.result.kind === "escalated"
        ? "escalated"
        : input.result.kind === "failed"
          ? "failed"
          : input.result.kind === "malformed"
            ? "malformed"
            : input.result.kind === "outcome_protocol_failure"
              ? "protocol_failure"
              : output?.converged === true
                ? "converged"
                : (output?.findings?.length ?? 0) > 0
                  ? "blocking"
                  : "not_converged";
    tryAppendTelemetryRecord(
      ledgerDir,
      buildReviewRoundStamp({
        runId: input.ctx.runId,
        issue: input.familyIssue ?? null,
        cmrPass: input.pass,
        reviewRound: priorReviewRecords.length + 1,
        verdict: workerVerdict,
        finalDisposition: input.finalDisposition,
        ...(output?.findings !== undefined ? { findings: output.findings } : {}),
        priorReviewRecords,
        ...(output?.priorFindingDispositions !== undefined
          ? { priorFindingDispositions: output.priorFindingDispositions }
          : {}),
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
    priorCmrFindingIdentityKeys,
    priorCmrFindingIdentityKeysByPass,
    allowCoderFix,
  } = input;
  const routeFingerprint = modelRouteFingerprint(resolvedRoute);
  const resolvedFamilyHeadAfter = await readPostCmrFamilyHead(
    familyBackend,
    familyBase,
    familyHeadAfter,
  );
  if (
    cmrPassAlreadyPassed(await familyBackend.readFamilyLedger(), {
      cmrPass: pass,
      familyHeadAfter: resolvedFamilyHeadAfter,
      routeFingerprint,
    })
  ) {
    return {
      result: { ok: true, ran: true },
      familyHeadAfter: resolvedFamilyHeadAfter,
    };
  }
  const spec = cmrWorkerSpec("fresh", pass, resolvedRoute);
  const familyLedger = await familyBackend.readFamilyLedger();
  const priorRoundFindings = priorCmrFindingsFromFamilyLedger(familyLedger, pass);
  const dispatchCtx: DispatchContext = {
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    modelRoute: resolvedRoute,
    cmrPass: pass,
    ...(llmResolvedChildren !== undefined && llmResolvedChildren.length > 0
      ? { llmResolvedChildren }
      : {}),
    ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
    ...(moduleContext !== undefined ? { moduleContext } : {}),
    ...(priorCmrFindingIdentityKeys !== undefined
      ? { priorCmrFindingIdentityKeys }
      : {}),
    ...(priorRoundFindings.length > 0 ? { priorRoundFindings } : {}),
  };
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
  // #598: one "logical cmr attempt" = a fresh dispatch + the same-worker
  // `rewriteOutcomeProtocolFailure` counter (OUTCOME_REWRITE_RETRY_CAP). When that
  // counter exhausts into `outcome_protocol_failure`, the GENERIC mechanical layer
  // fires ONLY AFTER it — a FRESH (non-resume) cmr re-dispatch, up to
  // MAX_DISPATCH_ATTEMPTS, before the durable abort below (crit 2 "generic fires
  // after the rewrite counter"; crit 1 "returned outcome_protocol_failure retries").
  // The cmr worker is READ-ONLY (reviews the family base) → no local residue to
  // reset between attempts. The HEAD-movement git guards stay per attempt.
  let rawCmrResult: WorkerResult;
  let cmrResult: WorkerResult;
  for (let cmrAttempt = 1; ; cmrAttempt++) {
    rawCmrResult = await dispatchOrAbort(familyBackend, spec, dispatchCtx);
    reviewRoundResult = rawCmrResult;
    if (rawCmrResult.kind === "malformed") {
      const postReviewFamilyHead = await readPostCmrFamilyHead(
        familyBackend,
        familyBase,
        resolvedFamilyHeadAfter,
      );
      const postReviewGitAbort = await guardPostCmrReviewerGitState({
        familyBackend,
        familyBase,
        pass,
        expectedFamilyHead: resolvedFamilyHeadAfter,
        familyHeadAfter: postReviewFamilyHead,
      });
      if (postReviewGitAbort !== undefined) {
        finalReviewRoundDisposition = "rejected";
        return postReviewGitAbort;
      }
    }
    cmrResult = await rewriteOutcomeProtocolFailure({
      familyBackend,
      spec,
      ctx: dispatchCtx,
      result: rawCmrResult,
    });
    reviewRoundResult = cmrResult;
    if (
      cmrResult.kind === "outcome_protocol_failure" &&
      cmrAttempt < MAX_DISPATCH_ATTEMPTS
    ) {
      // #598 r3 / #876: observe git state before re-dispatch (head position is
      // routing plumbing). HEAD/tracked residue is advisory — never a capital
      // crime that skips the ordinary mechanical retry path.
      const reDispatchFamilyHead = await readPostCmrFamilyHead(
        familyBackend,
        familyBase,
        resolvedFamilyHeadAfter,
      );
      const reDispatchGitAbort = await guardPostCmrReviewerGitState({
        familyBackend,
        familyBase,
        pass,
        expectedFamilyHead: resolvedFamilyHeadAfter,
        familyHeadAfter: reDispatchFamilyHead,
      });
      if (reDispatchGitAbort !== undefined) {
        finalReviewRoundDisposition = "rejected";
        return reDispatchGitAbort;
      }
      continue;
    }
    break;
  }
  // #598 crit 6 (r4 codexA): the manual cmr re-dispatch loop names its generic
  // attempt count on exhaustion too (parity with withMechanicalRetry) — reached only
  // when the loop exhausted MAX_DISPATCH_ATTEMPTS all on outcome_protocol_failure.
  if (cmrResult.kind === "outcome_protocol_failure") {
    cmrResult = {
      ...cmrResult,
      reason: `${cmrResult.reason} (after ${MAX_DISPATCH_ATTEMPTS} dispatch attempts)`,
    };
  }
  const postWorkerFamilyHead = await readPostCmrFamilyHead(
    familyBackend,
    familyBase,
    resolvedFamilyHeadAfter,
  );
  const postWorkerGitAbort = await guardPostCmrReviewerGitState({
    familyBackend,
    familyBase,
    pass,
    expectedFamilyHead: resolvedFamilyHeadAfter,
    familyHeadAfter: postWorkerFamilyHead,
  });
  if (postWorkerGitAbort !== undefined) {
    finalReviewRoundDisposition = "rejected";
    return postWorkerGitAbort;
  }
  if (cmrResult.kind === "escalated") {
    const reason = `${cmrResult.escalation.reason} — ${cmrResult.escalation.diagnosis}`;
    const stopSummary = cmrEscalationStopSummary(reason);
    await persistFinalReviewRound("accepted", async () => {
      await recordDurableAbort(familyBackend, {
        phase: "final",
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        stopSummary,
      });
      await familyBackend.escalateFamily?.({
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        stopSummary,
      });
    });
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  if (cmrResult.kind !== "completed" || cmrResult.output.kind !== "cmr") {
    const reason =
      cmrResult.kind === "failed"
        ? `family integrated cmr ${pass} worker failed: ${cmrResult.reason}`
        : cmrResult.kind === "outcome_protocol_failure"
          ? `family integrated cmr ${pass} outcome protocol failure: ${cmrResult.reason}`
        : cmrResult.kind === "malformed"
          ? `family integrated cmr ${pass} worker malformed: ${cmrResult.reason}`
          : `family integrated cmr ${pass} worker returned no valid result (crash/malformed)`;
    const stopSummary =
      cmrResult.kind === "outcome_protocol_failure"
        ? infraFailureStopSummary({
            summary: reason,
            repairHint:
              "repair the worker outcome writer/guard or the outcome rewrite prompt, then rerun the family barrier",
          })
        : cmrResult.kind === "failed"
        ? cmrWorkerFailedStopSummary({
            reason,
            resolvedRoute,
          })
        : undefined;
    await persistFinalReviewRound("rejected", async () => {
      await familyBackend.recordAborted?.({
        phase: "final",
        cmrPass: pass,
        familyBase,
        errorPackage: { reason },
        familyHeadAfter: postWorkerFamilyHead,
      });
      await recordDurableAbort(familyBackend, {
        phase: "final",
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        ...(stopSummary !== undefined ? { stopSummary } : {}),
      });
    });
    return { result: INCOMPLETE_GATE, familyHeadAfter: postWorkerFamilyHead };
  }
  // Opus/#875/ADR 0129: structured findings array is the single source of truth.
  // open-count is DERIVED (array length). Downstream runner never reconciles an
  // independent count field against the array (that thrash was r5–r11).
  // Write-point already rejects count≠length; here we only read the array.
  const openFindingsCount = cmrResult.output.findings?.length ?? 0;
  if (!cmrResult.output.converged && openFindingsCount === 0) {
    // #875: no claimed-fixed coverage court on thin not_converged envelopes.
    // Three-channel routing only — findings empty + not converged ⇒ ordinary
    // not_converged durable abort (not a disposition/claim shape kill).
    const reason =
      cmrResult.output.reason ?? `integrated cmr ${pass} did not converge`;
    // #604 slice 3 / ADR 0062: a not_converged abort carries NO blocking findings.
    // Persist the thin envelope with `blockingFindingIdentityKeys: []` so the
    // runner keeps it in the classified-abort branch and derives no pending keys
    // from it.
    //
    // #604 rework (codexB): DO NOT write `cmrDispositions: []` here. An empty
    // tombstone would mask an earlier round's real accepted-suppression
    // dispositions (`latestFamilyCmrDispositions` returned the latest DEFINED
    // array), resetting the reopen/dispute budget on the next pass. A
    // not_converged abort produced no new governance dispositions, so it leaves
    // the field UNDEFINED (omitted via `compact`), carrying the prior round's
    // dispositions forward.
    await persistFinalReviewRound("accepted", () => recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter: postWorkerFamilyHead,
      blockingFindingIdentityKeys: [],
      stopSummary: notConvergedStopSummary(reason),
    }));
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  // #875: leg-accounting court demolished. successfulLegs/skippedLegs are worker
  // prose for the degradation floor below — undeclared/duplicate/omitted legs no
  // longer abort the run. Floor still credits only route-declared successful legs
  // (undeclared strong must not satisfy ADR0032).
  const floorFailure = cmrFloorFailureReason({
    pass,
    successfulLegs: cmrResult.output.successfulLegs,
    skippedLegs: cmrResult.output.skippedLegs,
    resolvedRoute,
  });
  if (floorFailure !== undefined) {
    const skippedLegs = cmrResult.output.skippedLegs;
    await persistFinalReviewRound("rejected", () => recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason: floorFailure,
      familyHeadAfter: postWorkerFamilyHead,
      stopSummary: providerDegradedFloorStopSummary({
        reason: floorFailure,
        skippedLegs,
      }),
    }));
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  const requiredLegFailure = requiredCmrLegSkipFailure(
    cmrResult.output.skippedLegs,
    resolvedRoute,
    // #875: double-reported successful+skipped is prose — success wins.
    cmrResult.output.successfulLegs,
  );
  if (requiredLegFailure !== undefined) {
    const skippedLegs = cmrResult.output.skippedLegs;
    await persistFinalReviewRound("rejected", () => recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason: requiredLegFailure,
      familyHeadAfter: postWorkerFamilyHead,
      stopSummary: providerDegradedFloorStopSummary({
        reason: requiredLegFailure,
        skippedLegs,
      }),
    }));
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  // #875: early claimed-fixed / disposition coverage court demolished.
  // openFindingsCount>0 iff structured findings array is non-empty (derived).
  // No downstream branch for "count>0 without structured" — inexpressible after
  // write-point (Opus ballot).
  let cmrFindingClassification: CmrEnvelope | undefined;
  if (openFindingsCount > 0 && cmrResult.output.findings !== undefined) {
    const priorDispositions = latestFamilyCmrDispositions(
      await familyBackend.readFamilyLedger(),
    );
    cmrFindingClassification = deriveCmrEnvelope({
      familyIssue: familyIssue ?? 0,
      findings: cmrResult.output.findings,
      moduleContext: moduleContext ?? { currentModules: [], childModules: [] },
      ...(priorDispositions !== undefined ? { priorDispositions } : {}),
    });
    const classification = cmrFindingClassification;
    if (classification.blocking.length > 0) {
      const reason =
        `integrated cmr ${pass} found blocking family-scope findings: ` +
        classification.results
          .filter(
            // #604 slice 4 (ADR 0062): only accepted-suppression is non-blocking;
            // the routing classifications (incl. cross_module_defer) are gone.
            (result) => result.classification !== "accepted_suppressed",
          )
          .map((result) => `${result.classification}:${result.identityKey}`)
          .join(", ");
      const stopSummary = familyCmrBlockingStopSummary(
        classification,
        reason,
      );
      // #604 slice 2 / ADR 0062: the runner is a PURE SCHEDULER — it counts
      // blocking findings, it does NOT read a finding's disposition/classification
      // to decide whether the family lives. EVERY blocking finding's identity key
      // goes through coder-fix; a reviewer self-labeling a blocker
      // owning_issue_still_red / defer no longer terminates the whole family
      // (#497/#498).
      //
      // #597: the fixed CMR coder-fix round cap (formerly 3) is gone. While the
      // fresh reviewer keeps reporting a blocking finding, the runner keeps
      // dispatching coder-fix + fresh re-review — with NO runner-side round
      // counter or "same finding recurring" bookkeeping to replace the removed
      // cap; the runner only counts findings (0 vs. non-0).
      //
      // The two INTENDED steady-state exits: convergence (handled below —
      // findings == 0) or a worker-raised human-decision-gate signal. The stop
      // condition for a non-converging loop is therefore the WORKER's judgment,
      // not a runner budget: every fresh re-review dispatch can emit
      // `<cmr>{"escalate": …}` when it judges no convergence path (soul
      // cmr_completeness.md item 4), which lands as `cmrResult.kind ===
      // "escalated"` at the top of this pass (~L1632) → `escalateFamily` → park
      // for HITL. That per-round escalate is what prevents an endless loop; a
      // runner-side round/no-progress threshold is deliberately NOT re-added
      // (#597 acceptance #3; human-gate plumbing owned by #590/#604).
      // Beyond those two steady-state exits, the flow can still abort early on
      // operational failures (e.g. `runCmrCoderFix` returning `{ ok: false }`,
      // or worker/infra errors bubbling up) — those are error paths, not the
      // removed budget cap.
      const blockingFindingIdentityKeys = [
        ...new Set(classification.blocking.map(findingIdentityKey)),
      ];
      if (allowCoderFix) {
        // #604 slice 3 / ADR 0062: persist ONLY the thin envelope the runner reads
        // (blocking identity keys) + the gate's governance data (dispositions).
        // The fat `cmrFindingClassification` blob no longer lands on the ledger.
        await persistFinalReviewRound("accepted", () =>
          recordCmrReviewed(familyBackend, {
            cmrPass: pass,
            reason,
            familyHeadAfter: postWorkerFamilyHead,
            blockingFindingIdentityKeys,
            cmrDispositions: classification.dispositions,
            stopSummary,
          }),
        );
        // #878 head-not-moved short-circuit: after a completed fix leg, if the
        // observed family head did not advance, skip the expensive re-review
        // and redispatch the fix leg. Head position is scheduling plumbing
        // (routing), not a court judgment. Unknown heads fall through to the
        // normal re-review path rather than inventing a head-stuck signal.
        let fixFamilyHeadBefore = postWorkerFamilyHead;
        let fixRound = await runCmrCoderFix({
          pass,
          familyBackend,
          familyBase,
          ...(runId !== undefined ? { runId } : {}),
          classification,
          blockingFindingIdentityKeys,
          ...(cmrResult.output.findingFamilies !== undefined
            ? { findingFamilies: cmrResult.output.findingFamilies }
            : {}),
          familyHeadBefore: fixFamilyHeadBefore,
          escalationAnswer,
          familyIssue,
          resolvedRoute,
        });
        // #878 head-not-moved short-circuit: while the fix leg completes without
        // advancing family head, redispatch fix and skip re-review. Stop when
        // head moves, head is unknown, the fix leg fails/escalates, OR the
        // mechanical stuck budget is exhausted (scheduling plumbing — not a
        // content court; prevents infinite redispatch when the coder keeps
        // returning ok with no commit). Then fall through to fresh re-review.
        const MAX_HEAD_STUCK_REDISPATCHES = 3;
        let headStuckRedispatches = 0;
        while (
          fixRound.result.ok &&
          headStuckRedispatches < MAX_HEAD_STUCK_REDISPATCHES &&
          fixFamilyHeadBefore !== undefined &&
          fixRound.familyHeadAfter !== undefined &&
          fixFamilyHeadBefore === fixRound.familyHeadAfter
        ) {
          headStuckRedispatches += 1;
          fixRound = await runCmrCoderFix({
            pass,
            familyBackend,
            familyBase,
            ...(runId !== undefined ? { runId } : {}),
            classification,
            blockingFindingIdentityKeys,
            ...(cmrResult.output.findingFamilies !== undefined
              ? { findingFamilies: cmrResult.output.findingFamilies }
              : {}),
            familyHeadBefore: fixFamilyHeadBefore,
            escalationAnswer,
            familyIssue,
            resolvedRoute,
          });
        }
        if (!fixRound.result.ok) return fixRound;
        const updatedPriorKeys = [
            ...new Set([...(priorCmrFindingIdentityKeys ?? []), ...blockingFindingIdentityKeys]),
        ];
        return {
          result: { ok: true, ran: true },
          familyHeadAfter: fixRound.familyHeadAfter,
          restartFinalBarrier: {
            familyHeadAfter: fixRound.familyHeadAfter,
            priorCmrFindingIdentityKeysByPass: {
              ...(priorCmrFindingIdentityKeysByPass ?? {}),
              [pass]: updatedPriorKeys,
            },
          },
        };
      }
      await persistFinalReviewRound("accepted", () =>
        recordDurableAbort(familyBackend, {
          phase: "final",
          cmrPass: pass,
          reason,
          familyHeadAfter: postWorkerFamilyHead,
          blockingFindingIdentityKeys,
          cmrDispositions: classification.dispositions,
          stopSummary,
        }),
      );
      return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
    }
  }
  if (!cmrResult.output.converged) {
    // Three-channel: worker said not converged ⇒ never recordCmrPassed.
    // Covers residual r11 path where findingsCount>0 but all structured findings
    // classified as accepted_suppressed (blocking=[]) and the old guard required
    // count===0 / empty dispositions before not_converged — that leaked to pass.
    // #604 rework (codexB): do NOT write `cmrDispositions: []` tombstones.
    // If this pass produced governance dispositions, carry them; otherwise omit.
    const reason =
      cmrResult.output.reason ?? `integrated cmr ${pass} did not converge`;
    const dispositions = cmrFindingClassification?.dispositions;
    await persistFinalReviewRound("accepted", () =>
      recordDurableAbort(familyBackend, {
        phase: "final",
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        blockingFindingIdentityKeys: [],
        ...(dispositions != null && dispositions.length > 0
          ? { cmrDispositions: dispositions }
          : {}),
        stopSummary: notConvergedStopSummary(reason),
      }),
    );
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  // #875: late claimed-fixed / disposition-enum court demolished. Converged +
  // findings=0 (or only non-blocking suppressions already classified above) is
  // enough for three-channel pass; runner does not re-read disposition statuses
  // or claim coverage to kill the run.
  const skippedLegs = cmrResult.output.skippedLegs;
  await persistFinalReviewRound("accepted", () => recordCmrPassed(familyBackend, {
    cmrPass: pass,
    familyHeadAfter: postWorkerFamilyHead,
    routeFingerprint,
    // #604 slice 3 / ADR 0062: carry ONLY the governance dispositions forward for
    // cross-round prior-disposition tracking — not the fat classification blob.
    ...(cmrFindingClassification !== undefined
      ? { cmrDispositions: cmrFindingClassification.dispositions }
      : {}),
    stopSummary: familyCmrPassStopSummary({
      classification: cmrFindingClassification,
      familyHeadAfter: postWorkerFamilyHead,
      skippedLegs,
    }),
  }));
  return { result: { ok: true, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  } finally {
    stampReviewRound(reviewRoundResult, finalReviewRoundDisposition);
  }
}

/**
 * Run the family verify against the family base, then (on the `"final"` phase)
 * the integrated cmr 承重闸 and the open-PR step (ADR 0022 decision 3④/⑤/⑥/4).
 *
 * Reaches verify / cmr / PR / abort / escalate as OPTIONAL `FamilyBackend`
 * methods: a backend with NO verify capability degrades to the nothing-ran `NOOP`
 * (the spine's #293 default path stays green); one that verifies green but lacks a
 * required downstream capability fails-safe to `INCOMPLETE_GATE` (never a false
 * success). Surfaces a red barrier purely via the returned
 * `ok`; the spine acts on it (it is never rewritten here).
 */
export async function runVerifyCmr(
  input: VerifyCmrInput,
): Promise<VerifyCmrResult> {
  return runVerifyCmrWithShipTruthAttempt(input, 1);
}

async function runVerifyCmrWithShipTruthAttempt(
  input: VerifyCmrInput,
  shipTruthAttempt: number,
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
    runId,
  } = input;

  // No verify capability ⇒ the #293 no-op path (nothing to verify; do not pretend).
  if (familyBackend.runFamilyVerify === undefined) return NOOP;

  // ── verify (both phases; "final" runs the FULL suite — a RealBackend scopes it
  //    off `phase`). RED ⇒ fail-fast: record the `aborted` event so the failure is
  //    not silently dropped, and return `{ok:false}` (decision 3④/5). ──
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
  // (decision 3⑤/⑥). A green wave verify clears the wave.
  if (phase === "wave") return { ok: true, ran: true };

  // ── integrated cmr 承重闸 (decision 3⑥): only AFTER a green full verify. No cmr
  //    capability ⇒ the hook CANNOT run the load-bearing review, so it must NOT
  //    report a pass: a real verify already ran, and `{ok:true}` here would make
  //    the spine's finalize() call the run `"success"` with the 承重闸 never run.
  //    Fail-safe to `ok:false` (verify_failed) — NOT the #293 nothing-ran no-op. ──
  // ADR 0026 / #331: the integrated cmr is dispatched as a FAMILY cmr WORKER
  // through the unified seam (no longer the inline `runIntegratedCmr`). The
  // capability check stays: NO cmr capability ⇒ INCOMPLETE_GATE (the load-bearing
  // review cannot run; never a false pass). The capability is satisfied by EITHER
  // the new unified `dispatchWorker` seam OR the legacy `runIntegratedCmr` (the
  // dispatch helper prefers the former, forwards to the latter) — gating on the
  // legacy method ALONE would wrongly fail-safe a backend that implements ONLY the
  // new seam (codex cmr finding).
  if (
    familyBackend.dispatchWorker === undefined &&
    familyBackend.runIntegratedCmr === undefined
  ) {
    return INCOMPLETE_GATE;
  }
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
    const stopSummary = infraFailureStopSummary({
      summary: `startup route failure: ${reason}; route env ORCHESTRATOR_ROUTE=${process.env.ORCHESTRATOR_ROUTE ?? "normal"}, ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS=${process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS ?? "(unset)"}`,
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
    return { ok: false, ran: true };
  }

  // #419: Step5 completeness and Step6 correctness are two runner-dispatched
  // CMR worker passes. Correctness is structurally unreachable unless the
  // completeness worker returns a green terminal verdict.
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
  const completeness = await runIntegratedCmrPass({
    pass: "completeness",
    familyBackend,
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    llmResolvedChildren,
    escalationAnswer,
    familyHeadAfter,
    familyIssue,
    moduleContext,
    priorCmrFindingIdentityKeys: priorKeysForPass("completeness"),
    priorCmrFindingIdentityKeysByPass: activePriorKeysByPass,
    resolvedRoute,
    allowCoderFix: true,
  });
  if (!completeness.result.ok) return completeness.result;
  if (completeness.restartFinalBarrier !== undefined) {
    return runVerifyCmr({
      phase: "final",
      familyBackend,
      familyBase,
      runId,
      modelRoute,
      llmResolvedChildren,
      escalationAnswer,
      familyHeadAfter: completeness.restartFinalBarrier.familyHeadAfter,
      familyIssue,
      moduleContext,
      priorCmrFindingIdentityKeysByPass:
        completeness.restartFinalBarrier.priorCmrFindingIdentityKeysByPass,
    });
  }

  let correctnessFamilyHeadAfter = completeness.familyHeadAfter;
  let correctnessPriorKeysByPass = activePriorKeysByPass;
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
    });
    if (!correctness.result.ok) return correctness.result;
    if (correctness.restartFinalBarrier === undefined) {
      correctnessFamilyHeadAfter = correctness.familyHeadAfter;
      break;
    }
    const verifyAfterFixFailed = await runFamilyVerifyOrAbort({
      phase,
      familyBase,
      familyBackend,
      familyHeadAfter: correctness.restartFinalBarrier.familyHeadAfter,
      runId,
      familyIssue,
    });
    if (verifyAfterFixFailed !== undefined) return verifyAfterFixFailed;
    correctnessFamilyHeadAfter = correctness.restartFinalBarrier.familyHeadAfter;
    correctnessPriorKeysByPass =
      correctness.restartFinalBarrier.priorCmrFindingIdentityKeysByPass;
  }
  const cmrPassedFamilyHeadAfter = correctnessFamilyHeadAfter;
  // Both CMR passes converged. Fall through to 止于 PR (the ship worker) below.

  // ── 止于 PR (decision 4): green verify + converged cmr ⇒ open the family PR and
  //    STOP. Online bot cmr + merge to main are the separate pr-review-loop stage,
  //    NOT this layer (this never merges). No PR capability ⇒ the terminal action
  //    cannot run; verify + cmr already ran, so `{ok:true}` would report `"success"`
  //    for a run whose PR never opened — fail-safe to `ok:false` (NOT the no-op). ──
  // ADR 0026 / #331: 止于 PR is a FAMILY SHIP WORKER through the unified seam (no
  // longer the inline `openFamilyPr`). Capability check: the terminal action is
  // runnable via EITHER the new unified `dispatchWorker` seam OR the legacy
  // `openFamilyPr`; neither ⇒ INCOMPLETE_GATE (the PR cannot open; never a false
  // success). #331 prefactor: dispatchFamilyWorker forwards to `openFamilyPr`; #336
  // makes it invoke `gstack-ship`. Host PR verification is also a preflight
  // requirement: dispatch is mutating, and without that seam a legacy
  // `openFamilyPr` backend could open a real PR then be unable to establish the
  // shipped truth needed to finish this barrier.
  if (
    familyBackend.dispatchWorker === undefined &&
    familyBackend.openFamilyPr === undefined
  ) {
    const reason =
      "family ship worker unavailable after converged CMR: backend has neither dispatchWorker nor openFamilyPr";
    const postCmrFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason },
      familyHeadAfter: postCmrFamilyHead,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: postCmrFamilyHead,
      stopSummary: infraFailureStopSummary({
        summary: `${reason}; the terminal PR gate cannot open a PR`,
        repairHint:
          "provide the family ship worker dispatch seam or legacy openFamilyPr capability, then rerun the final family barrier",
        ship: {
          latestVerifiedCmrHead: cmrPassedFamilyHeadAfter,
          currentFamilyHead: postCmrFamilyHead,
          shipPrState: "ship-capability-missing",
        },
        heads: {
          ...(postCmrFamilyHead !== undefined
            ? { actualFamilyHead: postCmrFamilyHead }
            : {}),
          ...(cmrPassedFamilyHeadAfter !== undefined
            ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
            : {}),
          sources: {
            actualFamilyHead: "family head after CMR before missing ship capability",
            verifiedCmrHead: "latest cmr_passed ledger row",
          },
        },
      }),
    });
    return INCOMPLETE_GATE;
  }
  if (familyBackend.verifyFamilyShippedPr === undefined) {
    const reason =
      "family ship worker unavailable before mutation: backend has no host PR verification capability";
    const postCmrFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason },
      familyHeadAfter: postCmrFamilyHead,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: postCmrFamilyHead,
      stopSummary: infraFailureStopSummary({
        summary: `${reason}; the terminal PR gate cannot verify a dispatched PR`,
        repairHint:
          "provide verifyFamilyShippedPr before dispatching the family ship worker, then rerun the final family barrier",
        ship: {
          latestVerifiedCmrHead: cmrPassedFamilyHeadAfter,
          currentFamilyHead: postCmrFamilyHead,
          shipPrState: "ship-verification-capability-missing",
        },
        heads: {
          ...(postCmrFamilyHead !== undefined
            ? { actualFamilyHead: postCmrFamilyHead }
            : {}),
          ...(cmrPassedFamilyHeadAfter !== undefined
            ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
            : {}),
          sources: {
            actualFamilyHead: "family head after CMR before missing ship verification capability",
            verifiedCmrHead: "latest cmr_passed ledger row",
          },
        },
      }),
    });
    return INCOMPLETE_GATE;
  }
  const shipSpec = familyShipWorkerSpec(resolvedRoute);
  const shipContext = {
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    modelRoute: resolvedRoute,
    ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
  };
  // #823: a worker-reported completion is deliberately only an observation input,
  // not shipped truth. On a fresh re-entry, verify that exact locator before any
  // new mutating dispatch. Only a host-confirmed absence recurses with attempt >1;
  // a mismatch is observed-but-unexpected state and must be escalated in place.
  const completedShip =
    shipTruthAttempt === 1
      ? familyShipCompletedRecord(await familyBackend.readFamilyLedger())
      : undefined;
  let shipResult: WorkerResult | undefined =
    completedShip === undefined
      ? undefined
      : {
          kind: "completed",
          output: {
            kind: "ship",
            branch: completedShip.branch,
            status: "pr_opened",
            pr: completedShip.pr,
          },
        };
  let lastMalformedShipAttempt: WorkerResult | undefined;
  let lastMalformedReason: string | undefined;
  const shipLedger = await familyBackend.readFamilyLedger();
  const legacyShipAttempts = shipDispatchAttemptsSinceLatestCorrectnessCmrPass(shipLedger);
  const legacyInfraAttempts =
    unconfirmedShipReservationsSinceLatestCorrectnessCmrPass(shipLedger);
  let shipStreakId = activeShipStreakId(shipLedger);
  if (shipStreakId === undefined) {
    shipStreakId = `ship-streak-${Date.now()}`;
    await recordShipStreakOpened(familyBackend, {
      shipStreakId,
      shipAttemptsAtOpen: legacyShipAttempts,
      shipInfraAttemptsAtOpen: legacyInfraAttempts,
    });
  }
  let shipStreakClosed = false;
  const closeShipStreak = async (outcome: "shipped" | "exhausted") => {
    if (shipStreakClosed) return;
    await recordShipStreakClosed(familyBackend, { shipStreakId, shipStreakOutcome: outcome });
    shipStreakClosed = true;
  };
  let usedShipAttempts = legacyShipAttempts;
  let usedInfraAttempts = legacyInfraAttempts;
  while (
    shipResult === undefined &&
    usedShipAttempts < MAX_DISPATCH_ATTEMPTS &&
    usedInfraAttempts < MAX_DISPATCH_ATTEMPTS
  ) {
    const shipDispatchId = `ship-${Date.now()}-${usedShipAttempts}-${usedInfraAttempts}`;
    await recordShipDispatchReservation(familyBackend, {
      phase: "final",
      shipDispatchId,
    });
    const dispatched = await dispatchShipOnce(
      familyBackend,
      shipSpec,
      shipContext,
      shipDispatchId,
    );
    if (!dispatched.launchConfirmed) {
      usedInfraAttempts += 1;
      continue;
    }
    usedShipAttempts += 1;
    let candidate = dispatched.result;
    if (candidate === undefined) {
      const expectedHead = await readRequiredFamilyHead(familyBackend, familyBase);
      const observed =
        expectedHead === undefined || familyBackend.findFamilyShippedPr === undefined
          ? {
              ok: false as const,
              kind: "observation_failed" as const,
              reason:
                expectedHead === undefined
                  ? "ship dispatch threw and current family HEAD could not be observed"
                  : "ship dispatch threw and backend has no host PR discovery capability",
            }
          : await familyBackend.findFamilyShippedPr({ familyBase, expectedHead });
      if (observed.ok) {
        candidate = {
          kind: "completed",
          output: {
            kind: "ship",
            branch: familyBase,
            status: "pr_opened",
            pr: observed.pr,
          },
        };
      } else if (observed.kind === "pr_missing") {
        // Host truth proved nothing landed: the next iteration writes a new durable
        // marker before it performs the replacement physical dispatch.
        continue;
      } else {
        candidate = {
          kind: "failed",
          reason: `family ship dispatch threw; host observation ${observed.kind}: ${observed.reason}`,
        };
      }
    }
    const malformedReason =
      candidate.kind === "malformed"
        ? candidate.reason
        : candidate.kind === "completed" && candidate.output?.kind !== "ship"
          ? "worker returned a non-ship payload"
          : candidate.kind === "completed" &&
              candidate.output.kind === "ship" &&
              (!isFilledString(candidate.output.pr) || !isFilledString(candidate.output.branch))
            ? `worker did not provide a PR locator or branch: ${describeShipPrState(candidate.output)}`
            : undefined;
    if (malformedReason === undefined) {
      shipResult = candidate;
      break;
    }
    lastMalformedShipAttempt = candidate;
    lastMalformedReason = malformedReason;
  }

  if (shipResult === undefined && lastMalformedReason !== undefined) {
    // ADR 0062: a malformed control envelope is a process/protocol failure, not
    // a ship verdict. Re-dispatch this terminal step mechanically; only an
    // exhausted bounded retry may raise the legal infrastructure escalation.
    const reason =
      `family ship worker output remained malformed after ${MAX_DISPATCH_ATTEMPTS} ` +
      `dispatch attempts: ${lastMalformedReason}`;
    const malformedAttempt = lastMalformedShipAttempt!;
    const shipPrState =
      malformedAttempt.kind === "completed" && malformedAttempt.output?.kind === "ship"
        ? describeShipPrState(malformedAttempt.output)
        : "malformed-worker-output";
    const actualFamilyHeadSource =
      malformedAttempt.kind === "completed" && malformedAttempt.output?.kind === "ship"
        ? "family head after missing PR locator"
        : "family head after malformed ship worker output";
    const postShipFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    const stopSummary = infraFailureStopSummary({
      summary: reason,
      repairHint:
        "repair the family ship worker outcome sidecar/payload, then rerun the final family barrier",
      ship: {
        ...(cmrPassedFamilyHeadAfter !== undefined
          ? { latestVerifiedCmrHead: cmrPassedFamilyHeadAfter }
          : {}),
        ...(postShipFamilyHead !== undefined
          ? { currentFamilyHead: postShipFamilyHead }
          : {}),
        shipPrState,
      },
      heads: {
        ...(postShipFamilyHead !== undefined
          ? { actualFamilyHead: postShipFamilyHead }
          : {}),
        ...(cmrPassedFamilyHeadAfter !== undefined
          ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
          : {}),
        sources: {
          actualFamilyHead: actualFamilyHeadSource,
          verifiedCmrHead: "latest cmr_passed ledger row",
        },
      },
    });
    await familyBackend.escalateFamily?.({
      reason,
      familyHeadAfter: postShipFamilyHead,
      stopSummary,
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
    await closeShipStreak("exhausted");
    return { ok: false, ran: true };
  }
  if (shipResult === undefined) {
    // The durable count was already exhausted before this resume could dispatch
    // (for example, a process crashed after the third marker). Do not reset the
    // budget or send a fourth ship worker; make the protocol failure visible.
    const infraBudgetExhausted = usedInfraAttempts >= MAX_DISPATCH_ATTEMPTS;
    const reason = infraBudgetExhausted
      ? `family ship worker failed before physical launch after ${MAX_DISPATCH_ATTEMPTS} infrastructure attempts; confirmed ship dispatch budget remains ${usedShipAttempts}/${MAX_DISPATCH_ATTEMPTS}`
      : `family ship worker output remained malformed after ${MAX_DISPATCH_ATTEMPTS} dispatch attempts: durable ship dispatch budget exhausted before resume`;
    const postShipFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    const stopSummary = infraFailureStopSummary({
      summary: reason,
      repairHint:
        "repair the family ship worker outcome sidecar/payload, then rerun the final family barrier",
      ship: {
        ...(cmrPassedFamilyHeadAfter !== undefined
          ? { latestVerifiedCmrHead: cmrPassedFamilyHeadAfter }
          : {}),
        ...(postShipFamilyHead !== undefined
          ? { currentFamilyHead: postShipFamilyHead }
          : {}),
        shipPrState: infraBudgetExhausted
          ? "pre-spawn-infrastructure-budget-exhausted"
          : "durable-ship-dispatch-budget-exhausted",
      },
      heads: {
        ...(postShipFamilyHead !== undefined
          ? { actualFamilyHead: postShipFamilyHead }
          : {}),
        ...(cmrPassedFamilyHeadAfter !== undefined
          ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
          : {}),
        sources: {
          actualFamilyHead: "family head after durable ship dispatch budget exhaustion",
          verifiedCmrHead: "latest cmr_passed ledger row",
        },
      },
    });
    await familyBackend.escalateFamily?.({
      reason,
      familyHeadAfter: postShipFamilyHead,
      stopSummary,
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
    await closeShipStreak("exhausted");
    return { ok: false, ran: true };
  }
  // An ESCALATED family ship worker (gstack-ship STOP/HITL) is the family
  // escalate续跑 path, not a false success — call the escalate seam (codex cmr R4
  // finding: keep escalate semantics). A `completed` non-ship payload / crash /
  // malformed means the PR did not open → fail-safe INCOMPLETE_GATE (decision 3⑤;
  // mirrors the cmr-stage guard above). #331's legacy wrapper produces neither.
  if (shipResult.kind === "escalated") {
    const postShipFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    const escalationReason =
      `${shipResult.escalation.reason} — ${shipResult.escalation.diagnosis}`;
    const reason = `family ship worker escalated: ${escalationReason}`;
    const stopSummary = infraFailureStopSummary({
      summary: reason,
      repairHint: "answer or repair the family ship worker escalation, then rerun",
      ship: {
        ...(cmrPassedFamilyHeadAfter !== undefined
          ? { latestVerifiedCmrHead: cmrPassedFamilyHeadAfter }
          : {}),
        ...(postShipFamilyHead !== undefined
          ? { currentFamilyHead: postShipFamilyHead }
          : {}),
        shipPrState: "ship-worker-escalated",
      },
      heads: {
        ...(postShipFamilyHead !== undefined
          ? { actualFamilyHead: postShipFamilyHead }
          : {}),
        ...(cmrPassedFamilyHeadAfter !== undefined
          ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
          : {}),
        sources: {
          actualFamilyHead: "family head after ship worker escalation",
          verifiedCmrHead: "latest cmr_passed ledger row",
        },
      },
    });
    if (familyBackend.escalateFamily !== undefined) {
      await familyBackend.escalateFamily({
        reason: escalationReason,
        familyHeadAfter: postShipFamilyHead,
        stopSummary,
      });
    }
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: postShipFamilyHead,
      stopSummary,
    });
    return { ok: false, ran: true };
  }
  if (shipResult.kind !== "completed" || shipResult.output?.kind !== "ship") {
    // The ship worker ran but returned no valid result (crash / malformed / hard
    // command failure) at the terminal 止于-PR gate. Persist a durable `aborted`
    // event (online review r3, codex P2): without it a resume sees neither a shipped
    // marker nor a failure marker and re-runs the whole final verify/cmr/ship,
    // losing the original failure context (decision 3⑤ 不静默吞).
    const reason =
      shipResult.kind === "failed"
        ? `family ship worker failed: ${shipResult.reason}`
        : "family ship worker returned no valid result (crash/malformed)";
    const postShipFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
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
      stopSummary: shipWorkerFailedStopSummary({
        reason,
        latestVerifiedCmrHead: cmrPassedFamilyHeadAfter,
        currentFamilyHead: postShipFamilyHead,
        reportedFamilyHead: cmrPassedFamilyHeadAfter,
        shipPrState:
          shipResult.kind === "failed" ? "worker-failed" : "not-written",
      }),
    });
    return INCOMPLETE_GATE;
  }
  const ship = shipResult.output;
  if (!isFilledString(ship.pr)) {
    const postShipFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    const shipPrState = describeShipPrState(ship);
    const reason =
      `family ship worker did not provide a PR locator: ${shipPrState}`;
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
      stopSummary: infraFailureStopSummary({
        summary: reason,
        repairHint:
          "repair the family ship PR locator and rerun the final family barrier",
        ship: {
          ...(cmrPassedFamilyHeadAfter !== undefined
            ? { latestVerifiedCmrHead: cmrPassedFamilyHeadAfter }
            : {}),
          ...(postShipFamilyHead !== undefined
            ? { currentFamilyHead: postShipFamilyHead }
            : {}),
          shipPrState,
        },
        heads: {
          ...(postShipFamilyHead !== undefined
            ? { actualFamilyHead: postShipFamilyHead }
            : {}),
          ...(cmrPassedFamilyHeadAfter !== undefined
            ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
            : {}),
          sources: {
            actualFamilyHead: "family head after missing PR locator",
            verifiedCmrHead: "latest cmr_passed ledger row",
          },
        },
      }),
    });
    return INCOMPLETE_GATE;
  }
  if (completedShip === undefined) {
    // Persist before reading host HEAD or calling `gh pr view`: this record is
    // advisory worker output, and exists solely to resume host observation after a
    // crash without sending another mutating ship worker.
    await recordShipCompleted(familyBackend, { pr: ship.pr, branch: ship.branch });
  }
  const exactPostShipFamilyHead = await readRequiredFamilyHead(familyBackend, familyBase);
  if (exactPostShipFamilyHead === undefined) {
    const reason =
      "family ship worker opened a PR, but the current family HEAD could not be resolved; refusing to persist a stale shipped marker";
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason },
      familyHeadAfter: cmrPassedFamilyHeadAfter,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: cmrPassedFamilyHeadAfter,
      stopSummary: infraFailureStopSummary({
        summary: reason,
        repairHint:
          "resolve the current family HEAD, verify the family PR still points at it, and rerun the final family barrier",
        ship: {
          ...(cmrPassedFamilyHeadAfter !== undefined
            ? {
                latestVerifiedCmrHead: cmrPassedFamilyHeadAfter,
                reportedFamilyHead: cmrPassedFamilyHeadAfter,
              }
            : {}),
          shipPrState: "current-family-head-unresolved",
        },
        heads: {
          ...(cmrPassedFamilyHeadAfter !== undefined
            ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
            : {}),
          sources: {
            verifiedCmrHead: "latest cmr_passed ledger row",
          },
        },
      }),
    });
    return INCOMPLETE_GATE;
  }
  const verifyShippedPr = async () =>
    familyBackend.verifyFamilyShippedPr === undefined
      ? {
          ok: false as const,
          kind: "observation_failed" as const,
          reason: "backend has no host PR verification capability",
        }
      : familyBackend.verifyFamilyShippedPr({
          pr: ship.pr!,
          familyBase,
          expectedHead: exactPostShipFamilyHead,
        });
  let shippedPrVerification = await verifyShippedPr();
  // Unknown host truth must not re-run a mutating ship worker. Retry the
  // observation itself within the shared #824 bound; only host-confirmed absence
  // or mismatch re-dispatches ship below.
  for (
    let observationAttempt = 1;
    !shippedPrVerification.ok &&
    shippedPrVerification.kind === "observation_failed" &&
    observationAttempt < MAX_DISPATCH_ATTEMPTS;
    observationAttempt += 1
  ) {
    shippedPrVerification = await verifyShippedPr();
  }
  if (!shippedPrVerification.ok) {
    if (
      shippedPrVerification.kind === "pr_missing" &&
      shipTruthAttempt < MAX_DISPATCH_ATTEMPTS
    ) {
      return runVerifyCmrWithShipTruthAttempt(input, shipTruthAttempt + 1);
    }
    const reason =
      `family ship PR failed host verification after ${MAX_DISPATCH_ATTEMPTS} ` +
      `${shippedPrVerification.kind === "observation_failed" ? "observation" : shippedPrVerification.kind === "pr_missing" ? "dispatch" : "decision"} attempts: ` +
      shippedPrVerification.reason;
    const stopSummary = infraFailureStopSummary({
      summary: reason,
      repairHint:
        shippedPrVerification.kind === "mismatch"
          ? "inspect the observed PR base/head and decide whether to repair or accept it; never re-run the mutating ship blindly"
          : "repair the family ship PR on the host or its locator, then rerun the final family barrier",
      ship: {
        ...(cmrPassedFamilyHeadAfter !== undefined
          ? { latestVerifiedCmrHead: cmrPassedFamilyHeadAfter }
          : {}),
        currentFamilyHead: exactPostShipFamilyHead,
        shipPrState: "host-verification-failed",
      },
      heads: {
        actualFamilyHead: exactPostShipFamilyHead,
        ...(cmrPassedFamilyHeadAfter !== undefined
          ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
          : {}),
        sources: {
          actualFamilyHead: "family head after ship worker",
          verifiedCmrHead: "latest cmr_passed ledger row",
        },
      },
    });
    await familyBackend.escalateFamily?.({
      reason,
      familyHeadAfter: exactPostShipFamilyHead,
      stopSummary,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: exactPostShipFamilyHead,
      stopSummary,
    });
    if (shippedPrVerification.kind === "pr_missing") {
      await closeShipStreak("exhausted");
    }
    return { ok: false, ran: true };
  }
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
      reportedFamilyHead: "host-observed family HEAD used for PR truth",
      actualFamilyHead: "family head after ship worker",
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
      entry.stopSummary != null &&
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
  await closeShipStreak("shipped");
  await recordShipped(familyBackend, {
    pr: ship.pr,
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
      pr: ship.pr,
      prHead: exactPostShipFamilyHead,
      status: "pr_opened",
    },
    resolvedRoute,
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
    return INCOMPLETE_GATE;
  }

  const convergedFamilyHead = await familyConvergenceMarkerHead(
    familyBackend,
    familyBase,
    exactPostShipFamilyHead,
    knownPostFixHead,
  );
  await recordReviewLoopConverged(familyBackend, {
    pr: ship.pr,
    familyHeadAfter: convergedFamilyHead,
    ...(shippedStopSummary !== undefined
      ? { stopSummary: shippedStopSummary }
      : {}),
  });

  const shipPr = ship.pr;
  if (shipPr === undefined || shipPr.trim().length === 0) {
    return INCOMPLETE_GATE;
  }
  const autoMerge = await runFamilyAutoMergeStage({
    familyBackend,
    familyBase,
    convergedHeadOid: convergedFamilyHead,
    prUrl: shipPr,
  });
  if (familyAutoMergeIncomplete(autoMerge)) {
    const stopSummary =
      autoMerge.stopSummary ??
      decisionGateParkStopSummary({
        summary: `family auto-merge did not complete (${autoMerge.terminalState})`,
        repairHint:
          "resolve merge blockers or answer the decision gate, then re-run the family final barrier",
      });
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason: stopSummary.summary },
      familyHeadAfter: convergedFamilyHead,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason: stopSummary.summary,
      familyHeadAfter: convergedFamilyHead,
      stopSummary,
    });
    return INCOMPLETE_GATE;
  }

  const cleanupGate = await ensureFamilyPostMergeCleanup({
    familyBackend,
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    familyHeadAfter: convergedFamilyHead,
    prUrl: shipPr,
    ...(familyIssue !== undefined ? { familyIssue } : {}),
    resolvedRoute,
    phase,
    recordAbortOnFailure: true,
  });
  if (!cleanupGate.ok) return INCOMPLETE_GATE;
  return { ok: true, ran: true };
}

/**
 * #603 — after `pr_merged` for a head, require terminal+ok `post_merge_cleanup`
 * (or dispatch cleanup → record → optional reclaim). Shared by the fresh final
 * barrier and family resume already_done exits so remote residue is never
 * reported as success.
 */
export async function ensureFamilyPostMergeCleanup(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId?: string;
  readonly familyHeadAfter: string;
  readonly prUrl: string;
  readonly familyIssue?: number;
  readonly resolvedRoute?: ResolvedModelRoute;
  readonly phase?: VerifyCmrPhase;
  /** When true (final barrier), write durable abort on cleanup failure. */
  readonly recordAbortOnFailure?: boolean;
}): Promise<{ readonly ok: boolean; readonly reason?: string }> {
  const {
    familyBackend,
    familyBase,
    familyHeadAfter,
    prUrl,
    familyIssue,
    phase = "final",
    recordAbortOnFailure = false,
  } = input;
  const ledger = await familyBackend.readFamilyLedger();
  const priorCleanup = familyPostMergeCleanupForHead(ledger, familyHeadAfter);
  if (priorCleanup !== undefined) {
    return { ok: true };
  }
  const prMergedRow = familyPrMergedForHead(ledger, familyHeadAfter);
  if (prMergedRow === undefined) {
    return { ok: true };
  }
  // Resolve only when about to dispatch cleanup — short-circuits above must
  // not fail on a broken ORCHESTRATOR_ROUTE after cleanup is already done /
  // when pr_merged is not yet present.
  const resolvedRoute = input.resolvedRoute ?? resolveActiveModelRoute();
  const familyRepo =
    process.env.ORCHESTRATOR_REPO?.trim() ?? "Akagilnc/ming-salvage-sim";
  const coveredIssues = [...mergedSet(ledger)];
  const cleanupLanding: WorkerLandingPayload = {
    cleanupDispatch: buildCleanupLanding({
      record: {
        prUrl: prMergedRow.pr,
        prNumber: prMergedRow.prNumber,
        remoteBranchName: prMergedRow.remoteBranchName,
        mergedHeadOid: prMergedRow.mergedHeadOid,
        convergedHeadOid: familyHeadAfter,
      },
      coveredIssues,
      ...(familyIssue !== undefined ? { parentIssue: familyIssue } : {}),
    }),
  };
  const cleanupResult = await dispatchOrAbort(
    familyBackend,
    cleanupWorkerSpec(resolvedRoute),
    {
      familyBase,
      ...(input.runId !== undefined ? { runId: input.runId } : {}),
      modelRoute: resolvedRoute,
      repo: familyRepo,
      prUrl,
    },
    cleanupLanding,
  );
  if (
    cleanupResult.kind !== "completed" ||
    !isValidCleanupResult(cleanupResult.output) ||
    !cleanupResult.output.terminal ||
    !cleanupResult.output.ok
  ) {
    const reason =
      cleanupResult.kind === "completed"
        ? "family post-merge cleanup did not reach a terminal success outcome"
        : cleanupResult.kind === "failed" || cleanupResult.kind === "malformed"
          ? `family post-merge cleanup worker returned ${cleanupResult.kind}: ${cleanupResult.reason}`
          : `family post-merge cleanup worker returned ${cleanupResult.kind}`;
    if (recordAbortOnFailure) {
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
        stopSummary: infraFailureStopSummary({
          summary: reason,
          repairHint:
            "verify PR is MERGED with matching head, then re-run the family final barrier",
        }),
      });
    }
    return { ok: false, reason };
  }
  await recordPostMergeCleanup(familyBackend, {
    familyHeadAfter,
    cleanupOutput: cleanupResult.output,
  });
  const postCleanupLedger = await familyBackend.readFamilyLedger();
  if (
    shouldReclaimFamilyHost(postCleanupLedger) &&
    familyBackend.reapFamilyHost !== undefined
  ) {
    try {
      await familyBackend.reapFamilyHost(familyBase);
    } catch {
      // Best-effort terminal GC — must not flip a successful cleanup.
    }
  }
  return { ok: true };
}
