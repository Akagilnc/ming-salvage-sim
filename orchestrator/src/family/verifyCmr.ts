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
 *     re-review over the current full diff. A malformed reviewer envelope follows
 *     the same fixed topology with its raw artifact paths as fixer cargo. A worker-
 *     pressed escalation is transported unchanged; process crashes stop before
 *     ship. `verifyCmr` owns pass ordering and the ADR0032 strong-leg
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

import type { FamilyModuleContext } from "./moduleDeclaration.js";
import { shWithClock } from "../externalCall.js";

import { isLiveGithubReviewPollEnabled, pollPrReviewState } from "../botPolling.js";
import {
  familyAutoMergeIncomplete,
  runFamilyAutoMergeStage,
} from "./familyAutoMerge.js";
import { buildCleanupLanding } from "../postMergeCleanup.js";
import { offlineReviewLoopDispatchAdmissible } from "../evidenceAdmissibility.js";
import { stubCleanupResult } from "../reviewLoopOutcome.js";
import {
  shouldReclaimFamilyHost,
} from "../hostReclaim.js";
import {
  buildRoundTrigger,
  convergenceHeadToRecord,
  type RoundTrigger,
} from "../evidenceAdmissibility.js";
import {
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
} from "./onlineReviewLoop.js";
import {
  mergePriorRoundFindings,
  priorCmrFindingsFromFamilyLedger,
  priorOnlineReviewFindingsFromFamilyLedger,
} from "../findingFamilies.js";
import { applyVerifySideEffects } from "../onlineReviewSideEffects.js";
import {
  familyCoderFixWorkerSpec,
  cmrWorkerSpec,
  dispatchFamilyWorker,
  dispatchFamilyWorkerWithMonitor,
  familyShipWorkerSpec,
} from "./dispatchFamilyWorker.js";
import { withMechanicalRetry } from "../dispatchRetry.js";
import {
  modelRouteFingerprint,
  resolveActiveModelRoute,
  smokeRouteModels,
  type ResolvedModelRoute,
} from "../modelRoutes.js";
import { modelFamilyForCmrReviewLeg } from "../modelRegistry.js";
import { isQuotaWaitForResetError } from "../quotaProbe.js";
import { isRunnerSynthesizedFailureEscalation } from "../runnerEscalation.js";
import type {
  CleanupResult,
  DispatchContext,
  EscalationAnswerPayload,
  Finding,
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
  recordShipped,
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
   * #686 / #909 — sticky baton billing pool for re-dispatch after a family
   * quota relay. When set, every family worker DispatchContext carries it so
   * the real provider/CLI channel matches the baton (not only the model slug).
   */
  readonly billingPool?: string;
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
   * (exit / findings count / decision gate), plus real infra durable abort.
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
  readonly blockingFindings: readonly Finding[];
  readonly blockingFindingCount?: number;
  readonly blockingFindingIdentityKeys: readonly string[];
  readonly rawReviewerArtifacts?: WorkerLandingPayload["rawReviewerArtifacts"];
  readonly findingFamilies?: ReadonlyArray<FindingFamily>;
  readonly familyHeadBefore?: string;
  readonly escalationAnswer?: EscalationAnswerPayload;
  readonly familyIssue?: number;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly billingPool?: string;
}): Promise<IntegratedCmrPassOutcome> {
  const {
    pass,
    familyBackend,
    familyBase,
    runId,
    blockingFindings,
    blockingFindingCount,
    blockingFindingIdentityKeys,
    rawReviewerArtifacts,
    findingFamilies,
    familyHeadBefore,
    escalationAnswer,
    familyIssue,
    resolvedRoute,
    billingPool,
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
      ...(billingPool !== undefined ? { billingPool } : {}),
      // 信封宪法 (ADR 0062): only identity keys + count on the dispatch structure;
      // rich finding content travels in the separate landing payload below.
      blockingFindingIdentityKeys,
      ...(blockingFindingCount !== undefined ? { blockingFindingCount } : {}),
      ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
      ...(familyIssue !== undefined ? { familyIssue } : {}),
    },
    {
      blockingFindings,
      ...(rawReviewerArtifacts !== undefined ? { rawReviewerArtifacts } : {}),
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
      ? infraFailureStopSummary({
          summary: `${reason} — ${diagnosis}`,
          repairHint:
            "repair the coder-fix worker startup/authentication failure, then re-feed the family run",
          heads,
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

  if (fixResult.kind !== "completed") {
    const reason = `${reasonPrefix} failed: ${fixResult.reason}`;
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

  if (fixResult.output.kind !== "coder") {
    await recordCmrFixCommitted(familyBackend, {
      cmrPass: pass,
      familyHeadBefore: currentFamilyHeadBefore,
      familyHeadAfter,
      blockingFindingIdentityKeys,
      reason: `${reasonPrefix}: completed coder receipt carried another shape; fresh reviewer will judge the diff`,
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

  await recordCmrFixCommitted(familyBackend, {
    cmrPass: pass,
    familyHeadBefore: currentFamilyHeadBefore,
    familyHeadAfter,
    blockingFindingIdentityKeys,
    reason: `${reasonPrefix}: coder-fix completed; fresh reviewer will judge findings`,
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
    readonly onMonitorHandle?: (handle: WorkerMonitorHandle) => void;
  },
): Promise<WorkerResult> {
  const primary = await dispatchOrAbort(
    familyBackend,
    spec,
    ctx,
    landing,
    opts,
  );
  return primary;
}

export async function runFamilyOnlineReviewLoop(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId?: string;
  readonly ship: ShipResult;
  readonly resolvedRoute?: ResolvedModelRoute;
  readonly billingPool?: string;
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
    ...(input.billingPool !== undefined ? { billingPool: input.billingPool } : {}),
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
      let reviewerMonitorHandle: WorkerMonitorHandle | undefined;
      const result = await dispatchFamilyReviewWorker(
        input.familyBackend,
        verifyWorkerSpec(input.resolvedRoute),
        { ...baseCtx, onlineReviewRound: round },
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
      if (result.kind !== "completed") {
        const detail = result.kind === "failed" ? `: ${result.reason}` : "";
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
      if (result.output.kind !== "verify") {
        return {
          kind: "rawReviewerArtifacts",
          artifacts: reviewerArtifactPointers(
            reviewerMonitorHandle,
            result.sessionId,
          ),
        };
      }
      return {
        kind: "rawReviewerArtifacts",
        artifacts: reviewerArtifactPointers(
          reviewerMonitorHandle,
          result.sessionId,
        ),
        verify: result.output,
      };
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
          stopSummary: isRunnerSynthesizedFailureEscalation(result.escalation)
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
      if (result.kind !== "completed") {
        const detail =
          result.kind === "failed"
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
      return result.output.kind === "fixer" ? result.output : undefined;
    },
    // #740: family S12 crash-retry continues as-is (no scoped cleanup hook).
    dispatchDocRelease: async (landing: WorkerLandingPayload) => {
      const result = await dispatchFamilyReviewWorker(
        input.familyBackend,
        docReleaseWorkerSpec(input.resolvedRoute),
        baseCtx,
        landing,
      );
      if (result.kind !== "completed") return false;
      return result.output.kind === "docRelease"
        ? result.output.released
        : undefined;
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
    readonly onMonitorHandle?: (handle: WorkerMonitorHandle) => void;
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
                opts?.onMonitorHandle?.(handle);
                // Persist before waiting for the child: a hung family worker
                // must be resumable/judgable from the durable family ledger.
                try {
                  await familyBackend.appendFamilyLedger({
                    status: "worker_dispatched",
                    event: "worker_dispatched",
                    monitorHandle: handle,
                  });
                } catch {
                  // Best-effort only. The spawned
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
        if (dispatchError !== undefined) throw dispatchError;
        return workerResult!;
      },
      {
        onFailure: async (outcome, attempt) => {
          const reason =
            "result" in outcome
              ? outcome.result.kind === "failed"
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
    // #909: 429/quota park signal must NOT collapse into generic startup
    // `{kind:"failed"}` (leg-kill). Rethrow so upper family/runner can park or
    // relay — same typed terminal as single-slice withMechanicalRetry.
    if (isQuotaWaitForResetError(err)) throw err;
    const reason = `family ${spec.kind} worker threw on startup: ${
      err instanceof Error ? err.message : String(err)
    }`;
    return { kind: "failed", reason };
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
    const output =
      input.result.kind === "completed" && input.result.output.kind === "cmr"
        ? input.result.output
        : undefined;
    const workerVerdict =
      input.result.kind === "escalated"
        ? "escalated"
        : input.result.kind === "failed"
          ? "failed"
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
    ...(billingPool !== undefined ? { billingPool } : {}),
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
    let reviewerMonitorHandle: WorkerMonitorHandle | undefined;
    const cmrResult = await dispatchOrAbort(familyBackend, spec, dispatchCtx, undefined, {
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
  const routeRawReviewerArtifactsToFix = async (
    reason: string,
    sessionId: string | undefined,
  ): Promise<IntegratedCmrPassOutcome> => {
    const rawReviewerArtifacts = reviewerArtifactPointers(
      reviewerMonitorHandle,
      sessionId,
    );
    await persistFinalReviewRound("accepted", () =>
      recordCmrReviewed(familyBackend, {
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        blockingFindingIdentityKeys: [],
      }),
    );
    const fixRound = await runCmrCoderFix({
      pass,
      familyBackend,
      familyBase,
      ...(runId !== undefined ? { runId } : {}),
      blockingFindings: [],
      blockingFindingIdentityKeys: [],
      rawReviewerArtifacts,
      familyHeadBefore: postWorkerFamilyHead,
      escalationAnswer,
      familyIssue,
      resolvedRoute,
      ...(billingPool !== undefined ? { billingPool } : {}),
    });
    if (!fixRound.result.ok) return fixRound;
    return {
      result: { ok: true, ran: true },
      familyHeadAfter: fixRound.familyHeadAfter,
      restartFinalBarrier: {
        familyHeadAfter: fixRound.familyHeadAfter,
        priorCmrFindingIdentityKeysByPass:
          priorCmrFindingIdentityKeysByPass ?? {},
      },
    };
  };
  if (cmrResult.kind === "escalated") {
    const reason = cmrResult.escalation.reason;
    const diagnosis = cmrResult.escalation.diagnosis;
    const synthesizedFailure = isRunnerSynthesizedFailureEscalation(
      cmrResult.escalation,
    );
    const stopSummary = synthesizedFailure
      ? infraFailureStopSummary({
          summary: `${reason} — ${diagnosis}`,
          repairHint:
            "repair the integrated CMR worker startup/configuration failure, then re-feed the family run",
          heads: postWorkerFamilyHead !== undefined
            ? { actualFamilyHead: postWorkerFamilyHead }
            : undefined,
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
        phase: "final",
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
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
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
  if (cmrResult.output.kind !== "cmr") {
    return await routeRawReviewerArtifactsToFix(
      `integrated cmr ${pass} reviewer completed with a non-review shape; raw artifacts require fixer inspection`,
      cmrResult.sessionId,
    );
  }
  // ADR 0131: only the reviewer declaration routes. Structured findings are
  // cargo and cannot supply a missing count.
  const openFindingsCount = cmrResult.output.findingsCount;
  if (openFindingsCount === undefined) {
    return await routeRawReviewerArtifactsToFix(
      `integrated cmr ${pass} reviewer omitted its declared count; raw artifacts require fixer inspection`,
      cmrResult.sessionId,
    );
  }
  // ADR 0131: the reviewer-declared count is the complete routing signal.
  // Positive always enters coder-fix. Structured findings are optional cargo;
  // when absent, the fixer receives the raw reviewer artifact pointers instead.
  if (openFindingsCount > 0) {
    const blockingFindings = cmrResult.output.findings ?? [];
    const blockingFindingIdentityKeys = [
      ...new Set(blockingFindings.map(findingIdentityKey)),
    ];
    const reason =
      `integrated cmr ${pass} reviewer declared ${openFindingsCount} open findings`;
    const stopSummary: StopSummary = {
      reason: "same_module_still_red",
      summary: reason,
      repairHint: "send the reviewer artifacts to coder-fix, then run a fresh review",
    };
    // The runner schedules from count only; finding content is cargo.
    if (allowCoderFix) {
      await persistFinalReviewRound("accepted", () =>
        recordCmrReviewed(familyBackend, {
          cmrPass: pass,
          reason,
          familyHeadAfter: postWorkerFamilyHead,
          blockingFindingIdentityKeys,
          stopSummary,
        }),
      );
      const fixFamilyHeadBefore = postWorkerFamilyHead;
      const fixRound = await runCmrCoderFix({
        pass,
        familyBackend,
        familyBase,
        ...(runId !== undefined ? { runId } : {}),
        blockingFindings,
        blockingFindingCount: openFindingsCount,
        blockingFindingIdentityKeys,
        rawReviewerArtifacts: reviewerArtifactPointers(
          reviewerMonitorHandle,
          cmrResult.sessionId,
        ),
        ...(cmrResult.output.findingFamilies !== undefined
          ? { findingFamilies: cmrResult.output.findingFamilies }
          : {}),
        familyHeadBefore: fixFamilyHeadBefore,
        escalationAnswer,
        familyIssue,
        resolvedRoute,
        ...(billingPool !== undefined ? { billingPool } : {}),
      });
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
        stopSummary,
      }),
    );
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  // A zero declaration converges; the runner does not inspect finding content.
  const skippedLegs = cmrResult.output.skippedLegs;
  await persistFinalReviewRound("accepted", () => recordCmrPassed(familyBackend, {
    cmrPass: pass,
    familyHeadAfter: postWorkerFamilyHead,
    routeFingerprint,
    stopSummary: familyCmrPassStopSummary({
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
    ...(billingPool !== undefined ? { billingPool } : {}),
  });
  if (!completeness.result.ok) return completeness.result;
  if (completeness.restartFinalBarrier !== undefined) {
    return runVerifyCmr({
      phase: "final",
      familyBackend,
      familyBase,
      runId,
      modelRoute,
      ...(billingPool !== undefined ? { billingPool } : {}),
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
      ...(billingPool !== undefined ? { billingPool } : {}),
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
  // Both CMR passes converged. Continue through ship, online review, auto-merge,
  // and post-merge cleanup below.

  // ── Ship stage: green verify + converged CMR ⇒ open the family PR, then the
  //    same final barrier continues through online review, auto-merge, and cleanup.
  //    No PR capability means that continuation cannot start; verify + CMR already
  //    ran, so `{ok:true}` would report `"success"` for a run whose PR never opened
  //    — fail-safe to `ok:false` (NOT the no-op). The ship action is a FAMILY SHIP
  //    WORKER through the unified seam. Without that worker capability the final
  //    barrier remains incomplete.
  if (familyBackend.dispatchWorker === undefined) {
    const reason =
      "family ship worker unavailable after converged CMR: backend has no dispatchWorker capability";
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
          "provide the family ship worker dispatch seam, then rerun the final family barrier",
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
  const shipSpec = familyShipWorkerSpec(resolvedRoute);
  const shipContext = {
    familyBase,
    ...(runId !== undefined ? { runId } : {}),
    modelRoute: resolvedRoute,
    ...(billingPool !== undefined ? { billingPool } : {}),
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
      ? infraFailureStopSummary({
          summary: `${escalationReason} — ${escalationDiagnosis}`,
          repairHint:
            "repair the family ship worker startup/authentication failure, then re-feed the family run",
          heads,
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
    return { ok: false, ran: true };
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
    return INCOMPLETE_GATE;
  }
  const ship: ShipResult =
    shipResult.kind === "completed" && shipResult.output?.kind === "ship"
      ? shipResult.output
      : { kind: "ship", branch: familyBase, status: "completed" };
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
    ...(billingPool !== undefined ? { billingPool } : {}),
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
    pr: shipPr,
    familyHeadAfter: convergedFamilyHead,
    ...(shippedStopSummary !== undefined
      ? { stopSummary: shippedStopSummary }
      : {}),
  });

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
  let reportedCleanup: CleanupResult;
  try {
    const cleanupContext: DispatchContext = {
      familyBase,
      ...(input.runId !== undefined ? { runId: input.runId } : {}),
      repo: familyRepo,
      prUrl,
    };
    if (familyBackend.runPostMergeCleanup !== undefined) {
      reportedCleanup = await familyBackend.runPostMergeCleanup(
        cleanupLanding,
        cleanupContext,
      );
    } else if (offlineReviewLoopDispatchAdmissible(cleanupContext, familyRepo)) {
      reportedCleanup = stubCleanupResult();
    } else {
      throw new Error("family backend is missing deterministic post-merge cleanup");
    }
  } catch (error) {
    const reason = `family post-merge cleanup failed: ${
      error instanceof Error ? error.message : String(error)
    }`;
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
  if (!reportedCleanup.terminal || !reportedCleanup.ok) {
    const reason = "family post-merge cleanup did not reach a terminal success outcome";
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
    cleanupOutput: reportedCleanup,
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
