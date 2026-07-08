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
 *     re-review over the current full diff. Escalate / malformed / contract-slip
 *     verdicts are recorded as durable aborts and stop before ship.
 *     `verifyCmr` owns pass ordering, route-leg accounting, ADR0032 strong-leg floor,
 *     and claimed-fixed closure checks; it does not inline reviewer grading or patch
 *     logic in this hook.
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
import { execFileSync } from "node:child_process";

import { isLiveGithubReviewPollEnabled } from "../botPolling.js";
import {
  buildRoundTrigger,
  convergenceHeadToRecord,
  inadmissibleWorkerOutcomeReason,
  workerOutcomeAdmissible,
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
  verifyReviewerHeadMovedStopSummary,
  verifyReviewerWorktreeDirtyStopSummary,
  waitForBotQuiescence,
  type OnlineReviewLoopStageResult,
} from "../onlineReviewLoop.js";
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
  familyShipWorkerSpec,
} from "./dispatchFamilyWorker.js";
import {
  type DispatchOutcome,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../dispatchRetry.js";
import {
  cmrLegAccountingFailure,
  modelRouteFingerprint,
  resolveActiveModelRoute,
  type ResolvedModelRoute,
} from "../modelRoutes.js";
import { hasAcceptedSuppressionAuthority } from "../acceptedSuppression.js";
import { modelFamilyForCmrReviewLeg } from "../modelRegistry.js";
import { modelIsStrongLeg } from "../realBackend.js";
import type {
  DispatchContext,
  EscalationAnswerPayload,
  FindingDisposition,
  ShipResult,
  StepOutput,
  VerifyResult,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../types.js";
import { findingIdentityKey } from "../findings.js";
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
} from "./ledger.js";
import { isFilledString } from "../shipOutcome.js";
import { isCompleteRepairEvidence } from "../validate.js";
import {
  contractDriftStopSummary,
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
   * Runner-owned prior finding identity keys that the integrated CMR worker may
   * close. If a worker claims fixed keys without this protected context, or
   * claims keys outside it, the family gate fails closed.
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

async function runFamilyVerifyOrAbort(input: {
  readonly phase: VerifyCmrPhase;
  readonly familyBase: string;
  readonly familyBackend: FamilyBackend;
  readonly familyHeadAfter?: string;
}): Promise<VerifyCmrResult | undefined> {
  const { phase, familyBase, familyBackend, familyHeadAfter } = input;
  const verify: FamilyVerifyResult = await familyBackend.runFamilyVerify!({
    phase,
    familyBase,
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

function cmrFloorFailureReason(input: {
  readonly pass: IntegratedCmrPass;
  readonly successfulLegs: readonly string[] | undefined;
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
}): string | undefined {
  const successfulLegs = input.successfulLegs;
  if (successfulLegs === undefined || successfulLegs.length === 0) {
    return `integrated cmr ${input.pass} floor failed: no successful leg set was reported`;
  }
  if (meetsCmrFloor(successfulLegs)) return undefined;
  const skipped =
    input.skippedLegs !== undefined && input.skippedLegs.length > 0
      ? `; skipped legs: ${input.skippedLegs
          .map((leg) => `${leg.slug} (${leg.reason})`)
          .join(", ")}`
      : "";
  return (
    `integrated cmr ${input.pass} floor failed: successful legs [` +
    `${successfulLegs.join(", ")}] include no strong leg${skipped}`
  );
}

function providerDegradedFloorStopSummary(input: {
  readonly reason: string;
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
}): StopSummary {
  const providerDegraded =
    input.skippedLegs !== undefined && input.skippedLegs.length > 0
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
      ...(input.reportedFamilyHead !== undefined
        ? { reportedFamilyHead: input.reportedFamilyHead }
        : {}),
      ...(input.latestVerifiedCmrHead !== undefined
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
    ...(input.familyHeadAfter !== undefined
      ? {
          heads: {
            verifiedCmrHead: input.familyHeadAfter,
            sources: { verifiedCmrHead: "cmr_passed ledger row" },
          },
        }
      : {}),
    ...(acceptedSuppressions !== undefined && acceptedSuppressions.length > 0
      ? { acceptedSuppressions }
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

function legAccountingFailureStopSummary(input: {
  readonly reason: string;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly routeFingerprint: string;
  readonly successfulLegs: readonly string[];
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
}): StopSummary {
  return infraFailureStopSummary({
    summary: input.reason,
    repairHint:
      "repair the CMR worker leg accounting payload so it matches the active route, then rerun the family CMR gate",
    routeAccounting: {
      declaredLegs: input.resolvedRoute.legCollections.cmrReview.map((leg) => leg.slug),
      successfulLegs: input.successfulLegs,
      skippedLegs: input.skippedLegs ?? [],
      routeFingerprint: input.routeFingerprint,
      routeArtifact: {
        path: ".cmr-route.json",
        content: {
          legCollections: {
            cmrReview: input.resolvedRoute.legCollections.cmrReview.map((leg) => ({
              slug: leg.slug,
              family: leg.family,
            })),
          },
        },
      },
      actualPayload: {
        successfulLegs: input.successfulLegs,
        ...(input.skippedLegs !== undefined ? { skippedLegs: input.skippedLegs } : {}),
      },
      repairHint:
        "every active-route CMR leg must appear exactly once as successful or skipped; undeclared legs must be removed from the worker verdict",
    },
  });
}

function trustedAcceptedSuppressionDisposition(
  disposition: {
    readonly identityKey: string;
    readonly status: string;
    readonly reason?: string;
    readonly source?: string;
    readonly scope?: string;
    readonly boundedReopen?: string;
  },
  moduleContext: FamilyModuleContext | undefined,
): boolean {
  if (
    disposition.status !== "accepted_suppressed" ||
    !hasAcceptedSuppressionAuthority(disposition)
  ) {
    return false;
  }
  return (moduleContext?.acceptedSuppressionSources ?? []).some(
    (source) =>
      source.source === disposition.source &&
      source.scope === disposition.scope &&
      source.reason === disposition.reason &&
      source.boundedReopen === disposition.boundedReopen &&
      source.findingIdentity === disposition.identityKey,
  );
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

function cmrClosureFailureReason(input: {
  readonly pass: IntegratedCmrPass;
  readonly moduleContext?: FamilyModuleContext;
  readonly claimedFixedFindingIdentityKeys?: readonly string[];
  readonly protectedPriorFindingIdentityKeys?: readonly string[];
  readonly priorFindingDispositions?: readonly {
    readonly identityKey: string;
    readonly status: string;
    readonly reason?: string;
    readonly source?: string;
    readonly scope?: string;
    readonly boundedReopen?: string;
  }[];
  // #604 correctness r4 (D1): the EARLY closure guard (run before the
  // blocking→coder-fix branch on a RESTART barrier) must only assert the closure
  // payload is WELL-FORMED — every protected prior key is claimed or disposed, no
  // stale/duplicate/malformed dispositions. It must NOT assert every prior
  // disposition is `verified-closed`: a prior finding that is still `still-active`
  // / `unable-to-assess` is precisely what the coder-fix loop exists to repair, so
  // aborting on it would over-fire and starve the fix loop (the r2 C2 regression).
  // `allowStillActive: true` skips ONLY the `stillOpen` closed-status assertion;
  // every shape/coverage check still runs. The LATE converged-path guard omits
  // this flag, keeping its full `verified-closed` assertion intact.
  readonly allowStillActive?: boolean;
}): string | undefined {
  const claimed = input.claimedFixedFindingIdentityKeys ?? [];
  const priorDispositions = input.priorFindingDispositions ?? [];
  if (claimed.length > 0 && input.protectedPriorFindingIdentityKeys === undefined) {
    return (
      `integrated cmr ${input.pass} closure_context_missing: worker claimed fixed ` +
      `prior findings but the runner supplied no protected prior finding identity set`
    );
  }
  const protectedPriorKeys = input.protectedPriorFindingIdentityKeys;
  const protectedKeys =
    protectedPriorKeys !== undefined ? new Set(protectedPriorKeys) : undefined;
  if (protectedKeys !== undefined && protectedPriorKeys !== undefined) {
    const staleClaims = claimed.filter((key) => !protectedKeys.has(key));
    if (staleClaims.length > 0) {
      return (
        `integrated cmr ${input.pass} closure failed: claimed-fixed keys outside ` +
        `the runner-supplied prior finding set: ${staleClaims.join(", ")}`
      );
    }
    const claimedSet = new Set(claimed);
    const unclaimedPriorKeys = protectedPriorKeys.filter((key) => !claimedSet.has(key));
    if (unclaimedPriorKeys.length > 0) {
      return (
        `integrated cmr ${input.pass} closure failed: runner-supplied prior ` +
        `findings were not explicitly claimed fixed: ${unclaimedPriorKeys.join(", ")}`
      );
    }
  }
  const dispositionKeys = priorDispositions.map((d) => d.identityKey);
  const duplicateDispositions = dispositionKeys.filter(
    (key, index, keys) => keys.indexOf(key) !== index,
  );
  if (duplicateDispositions.length > 0) {
    return (
      `integrated cmr ${input.pass} closure failed: duplicate prior finding ` +
      `dispositions for ${[...new Set(duplicateDispositions)].join(", ")}`
    );
  }
  const malformedAcceptedSuppressions = priorDispositions
    .filter(
      (disposition) =>
        disposition.status === "accepted_suppressed" &&
        !trustedAcceptedSuppressionDisposition(disposition, input.moduleContext),
    )
    .map((disposition) => disposition.identityKey);
  if (malformedAcceptedSuppressions.length > 0) {
    return (
      `integrated cmr ${input.pass} closure failed: accepted_suppressed ` +
      `dispositions missing source/scope/boundedReopen for ${malformedAcceptedSuppressions.join(", ")}`
    );
  }
  const suppressedProtectedPriorKeys =
    protectedKeys === undefined
      ? []
      : priorDispositions
          .filter(
            (disposition) =>
              disposition.status === "accepted_suppressed" &&
              protectedKeys.has(disposition.identityKey),
          )
          .map((disposition) => disposition.identityKey);
  if (suppressedProtectedPriorKeys.length > 0) {
    return (
      `integrated cmr ${input.pass} closure failed: runner-protected prior ` +
      `findings cannot be closed by accepted_suppressed: ${suppressedProtectedPriorKeys.join(", ")}`
    );
  }
  if (input.allowStillActive !== true) {
    const stillOpen = priorDispositions
      .filter(
        (disposition) =>
          disposition.status !== "verified-closed" &&
          !(
            disposition.status === "accepted_suppressed" &&
            trustedAcceptedSuppressionDisposition(disposition, input.moduleContext)
          ),
      )
      .map((disposition) => disposition.identityKey);
    if (stillOpen.length > 0) {
      return (
        `integrated cmr ${input.pass} closure failed: prior claimed-fixed ` +
        `findings are not verified closed: ${stillOpen.join(", ")}`
      );
    }
  }
  const dispositions = new Map(priorDispositions.map((d) => [d.identityKey, d.status]));
  const claimedSet = new Set(claimed);
  const extraDispositions = priorDispositions
    .map((disposition) => disposition.identityKey)
    .filter((key) => !claimedSet.has(key));
  if (extraDispositions.length > 0) {
    return (
      `integrated cmr ${input.pass} closure failed: prior finding ` +
      `dispositions without claimed-fixed keys: ${extraDispositions.join(", ")}`
    );
  }
  if (claimed.length === 0) return undefined;
  const missing = claimed.filter((key) => !dispositions.has(key));
  if (missing.length > 0) {
    return (
      `integrated cmr ${input.pass} closure failed: prior claimed-fixed ` +
      `findings missing explicit disposition: ${missing.join(", ")}`
    );
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

const MAX_CODER_FIX_REPAIR_EVIDENCE_ATTEMPTS = 3;

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

function familyRepairEvidenceGateFailureReason(input: {
  readonly pass: IntegratedCmrPass;
  readonly output: Extract<WorkerResult, { kind: "completed" }>["output"];
  readonly blockingFindingIdentityKeys: readonly string[];
  readonly familyHeadBefore?: string;
  readonly familyHeadAfter?: string;
  readonly allowEvidenceOnlyRepair?: boolean;
}): string | undefined {
  if (input.output.kind !== "coder") {
    return `integrated cmr ${input.pass} coder-fix returned non-coder output`;
  }
  const hasIndependentCommit = input.output.committed && input.output.commitsAdded >= 1;
  if (!hasIndependentCommit && input.allowEvidenceOnlyRepair !== true) {
    return (
      `integrated cmr ${input.pass} coder-fix produced no independent fix commit: ` +
      `committed=${input.output.committed} commitsAdded=${input.output.commitsAdded}`
    );
  }
  if (
    input.familyHeadBefore === undefined ||
    input.familyHeadAfter === undefined ||
    input.familyHeadBefore === input.familyHeadAfter
  ) {
    return (
      `integrated cmr ${input.pass} coder-fix produced no verifiable family HEAD movement: ` +
      `${input.familyHeadBefore ?? "unknown"} -> ${input.familyHeadAfter ?? "unknown"}`
    );
  }
  if (!isCompleteRepairEvidence(input.output.repairEvidence)) {
    return (
      `integrated cmr ${input.pass} coder-fix repairEvidence missing required ` +
      `finding scope, tests, same-class bug scan, or introduced-regression check`
    );
  }
  const evidenceKeys = new Set(
    input.output.repairEvidence.findingScope.identityKeys ?? [],
  );
  const missingKeys = input.blockingFindingIdentityKeys.filter(
    (key) => !evidenceKeys.has(key),
  );
  if (missingKeys.length > 0) {
    return (
      `integrated cmr ${input.pass} coder-fix repairEvidence did not map to ` +
      `blocking finding scope: ${missingKeys.join(", ")}`
    );
  }
  return undefined;
}

function cmrReviewerHeadMovedStopSummary(input: {
  readonly pass: IntegratedCmrPass;
  readonly familyHeadBefore: string;
  readonly familyHeadAfter: string;
}): StopSummary {
  return contractDriftStopSummary({
    summary:
      `integrated CMR ${input.pass} reviewer moved family HEAD: ` +
      `${input.familyHeadBefore} -> ${input.familyHeadAfter}`,
    repairHint:
      "restore the reviewer/coder role boundary so CMR review leaves HEAD unchanged, then rerun the family CMR gate",
    heads: {
      reportedFamilyHead: input.familyHeadBefore,
      actualFamilyHead: input.familyHeadAfter,
      sources: {
        reportedFamilyHead: "pre-CMR family head",
        actualFamilyHead: "post-CMR family head",
      },
    },
  });
}

function cmrReviewerTrackedDirtyStopSummary(input: {
  readonly pass: IntegratedCmrPass;
  readonly trackedStatus: readonly string[];
}): StopSummary {
  return contractDriftStopSummary({
    summary:
      `integrated CMR ${input.pass} reviewer left tracked changes: ` +
      input.trackedStatus.join("; "),
    repairHint:
      "restore the reviewer/coder role boundary so CMR review leaves the tracked worktree clean, then rerun the family CMR gate",
    metadata: { trackedStatus: input.trackedStatus },
  });
}

async function runCmrCoderFix(input: {
  readonly pass: IntegratedCmrPass;
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly classification: CmrEnvelope;
  readonly blockingFindingIdentityKeys: readonly string[];
  readonly familyHeadBefore?: string;
  readonly escalationAnswer?: EscalationAnswerPayload;
  readonly familyIssue?: number;
  readonly resolvedRoute: ResolvedModelRoute;
}): Promise<IntegratedCmrPassOutcome> {
  const {
    pass,
    familyBackend,
    familyBase,
    classification,
    blockingFindingIdentityKeys,
    familyHeadBefore,
    escalationAnswer,
    familyIssue,
    resolvedRoute,
  } = input;
  const reasonPrefix =
    `integrated cmr ${pass} coder-fix for ` +
    blockingFindingIdentityKeys.join(", ");

  let currentFamilyHeadBefore = familyHeadBefore;
  let attempt = 1;
  let evidenceOnlyFamilyHeadAfter: string | undefined;
  let repairAttemptFailures: NonNullable<
    DispatchContext["repairAttemptFailures"]
  > = [];

  while (true) {
    const fixResult = await dispatchOrAbort(
      familyBackend,
      familyCoderFixWorkerSpec(resolvedRoute),
      {
        familyBase,
        // 信封宪法 (ADR 0062): only identity keys + count on the dispatch structure;
        // rich finding content travels in the separate landing payload below.
        blockingFindingIdentityKeys,
        blockingFindingCount: classification.blocking.length,
        ...(repairAttemptFailures.length > 0
          ? { repairAttemptFailures }
          : {}),
        ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
        ...(familyIssue !== undefined ? { familyIssue } : {}),
      },
      { blockingFindings: classification.blocking },
    );
    const familyHeadAfter = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      currentFamilyHeadBefore,
    );

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

    const repairGateFailure = familyRepairEvidenceGateFailureReason({
      pass,
      output: fixResult.output,
      blockingFindingIdentityKeys,
      familyHeadBefore: currentFamilyHeadBefore,
      familyHeadAfter,
      allowEvidenceOnlyRepair:
        evidenceOnlyFamilyHeadAfter !== undefined &&
        familyHeadAfter === evidenceOnlyFamilyHeadAfter,
    });
    if (repairGateFailure !== undefined) {
      if (attempt < MAX_CODER_FIX_REPAIR_EVIDENCE_ATTEMPTS) {
        repairAttemptFailures = [
          ...repairAttemptFailures,
          {
            attempt,
            reason: repairGateFailure,
            ...(currentFamilyHeadBefore !== undefined
              ? { familyHeadBefore: currentFamilyHeadBefore }
              : {}),
            ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
          },
        ];
        if (
          fixResult.output.kind === "coder" &&
          fixResult.output.committed &&
          fixResult.output.commitsAdded >= 1 &&
          currentFamilyHeadBefore !== undefined &&
          familyHeadAfter !== undefined &&
          currentFamilyHeadBefore !== familyHeadAfter
        ) {
          evidenceOnlyFamilyHeadAfter = familyHeadAfter;
        } else if (
          evidenceOnlyFamilyHeadAfter !== undefined &&
          familyHeadAfter === evidenceOnlyFamilyHeadAfter
        ) {
          // Keep the original pre-fix head and committed repair head across
          // repeated evidence-only retries. Later attempts still need to prove
          // the same already-landed commit, not add another commit.
        } else {
          currentFamilyHeadBefore = familyHeadAfter;
          evidenceOnlyFamilyHeadAfter = undefined;
        }
        attempt += 1;
        continue;
      }
      const reason =
        `${reasonPrefix} repair evidence gate failed after ${attempt} attempts: ` +
        repairGateFailure;
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

    await recordCmrFixCommitted(familyBackend, {
      cmrPass: pass,
      familyHeadBefore: currentFamilyHeadBefore,
      familyHeadAfter,
      blockingFindingIdentityKeys,
      reason:
        fixResult.output.committed && fixResult.output.commitsAdded >= 1
          ? `${reasonPrefix}: coder-fix committed ${fixResult.output.commitsAdded} ` +
            `commit${fixResult.output.commitsAdded === 1 ? "" : "s"}`
          : `${reasonPrefix}: coder-fix commit already landed; retry repaired required evidence only`,
    });
    return { result: { ok: true, ran: true }, familyHeadAfter };
  }
}

async function readPostCmrFamilyHead(
  familyBackend: FamilyBackend,
  familyBase: string,
  fallbackHead: string | undefined,
): Promise<string | undefined> {
  if (familyBackend.readFamilyHead === undefined) return fallbackHead;
  try {
    const liveHead = (await familyBackend.readFamilyHead(familyBase)).trim();
    return liveHead.length > 0 ? liveHead : fallbackHead;
  } catch {
    return fallbackHead;
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
    const reason =
      `integrated CMR ${pass} reviewer checked out a different HEAD: ` +
      `family base ${familyHeadAfter}, current HEAD ${currentHead}`;
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter: currentHead,
      stopSummary: cmrReviewerHeadMovedStopSummary({
        pass,
        familyHeadBefore: familyHeadAfter,
        familyHeadAfter: currentHead,
      }),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter: currentHead };
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
    const reason =
      `integrated CMR ${pass} reviewer moved family HEAD: ` +
      `${expectedFamilyHead} -> ${familyHeadAfter}`;
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter,
      stopSummary: cmrReviewerHeadMovedStopSummary({
        pass,
        familyHeadBefore: expectedFamilyHead,
        familyHeadAfter,
      }),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter };
  }
  if (trackedStatus.length > 0) {
    const reason =
      `integrated CMR ${pass} reviewer left tracked changes: ` +
      trackedStatus.join("; ");
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter,
      stopSummary: cmrReviewerTrackedDirtyStopSummary({
        pass,
        trackedStatus,
      }),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter };
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

/** Re-read live family HEAD and key the convergence/abort marker via {@link convergenceHeadToRecord}. */
async function familyConvergenceMarkerHead(
  familyBackend: FamilyBackend,
  familyBase: string,
  shipHead: string,
): Promise<string> {
  const liveHead = await readRequiredFamilyHead(familyBackend, familyBase);
  return (
    convergenceHeadToRecord({
      shipHead,
      postFixHead:
        liveHead !== undefined && liveHead !== shipHead ? liveHead : undefined,
    }) ?? liveHead ?? shipHead
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
  return {
    kind: "failed",
    reason: inadmissibleWorkerOutcomeReason(primary, spec),
  };
}

export async function runFamilyOnlineReviewLoop(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly ship: ShipResult;
  readonly resolvedRoute?: ResolvedModelRoute;
}): Promise<OnlineReviewLoopStageResult> {
  const repo =
    process.env.ORCHESTRATOR_REPO?.trim() ?? "Akagilnc/ming-salvage-sim";
  const prUrl = input.ship.pr;
  if (prUrl == null || prUrl.trim().length === 0) {
    return { ok: false, terminalState: "decision_gate_raised", round: 1 };
  }
  const ghSh = (file: string, args: string[]) =>
    execFileSync(file, args, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  const baseCtx: DispatchContext = {
    familyBase: input.familyBase,
    repo,
    prUrl,
    prHead: input.ship.prHead,
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
  const pendingGapRetrigger = familyPendingRoundTriggerFromFixGap(familyLedger);
  let lastRoundTrigger = livePoll
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
  let familyLastFixCommitSha: string | undefined = loopState.lastFixSha;

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
      lastRoundTrigger = buildRoundTrigger(snapshot.headOid, lastRoundTrigger.triggeredAt);
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
        if (
          headBefore !== undefined &&
          headAfter !== undefined &&
          headAfter !== headBefore
        ) {
          throw new OnlineReviewLoopTerminal({
            ok: false,
            terminalState: "contract_drift",
            round,
            stopSummary: verifyReviewerHeadMovedStopSummary({
              headBefore,
              headAfter,
            }),
          });
        }
        if (
          trackedBefore !== undefined &&
          trackedAfter !== undefined &&
          trackedAfter.join("\n") !== trackedBefore.join("\n")
        ) {
          throw new OnlineReviewLoopTerminal({
            ok: false,
            terminalState: "contract_drift",
            round,
            stopSummary: verifyReviewerWorktreeDirtyStopSummary({
              trackedStatus: trackedAfter,
            }),
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
          extraCallerOwns: (o) =>
            "kind" in o &&
            o.kind === "thrown" &&
            o.error instanceof OnlineReviewLoopTerminal &&
            o.error.result.terminalState === "contract_drift",
        },
      );
      if (result.kind !== "completed" || !isValidVerifyResult(result.output)) {
        throw new OnlineReviewLoopTerminal({
          ok: false,
          terminalState: "decision_gate_raised",
          round,
        });
      }
      return result.output;
    },
    dispatchFixer: async (landing: WorkerLandingPayload) => {
      const round = landing.onlineReviewRound ?? baseCtx.onlineReviewRound ?? 1;
      const result = await dispatchFamilyReviewWorker(
        input.familyBackend,
        fixerWorkerSpec(input.resolvedRoute),
        baseCtx,
        landing,
      );
      if (result.kind !== "completed" || !isValidFixerResult(result.output)) {
        throw new OnlineReviewLoopTerminal({
          ok: false,
          terminalState: "decision_gate_raised",
          round,
        });
      }
      return result.output;
    },
    dispatchCleanup: async (landing: WorkerLandingPayload) => {
      const result = await dispatchFamilyReviewWorker(
        input.familyBackend,
        cleanupWorkerSpec(input.resolvedRoute),
        baseCtx,
        landing,
      );
      return (
        result.kind === "completed" &&
        isValidCleanupResult(result.output) &&
        result.output.ok
      );
    },
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
      });
      return sha;
    },
  },
      {
        initialRound: loopState.round,
        initialFixCommitSha: loopState.lastFixSha,
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
          workerResult = await dispatchFamilyWorker(
            familyBackend,
            s,
            c,
            landing,
          );
        } catch (err) {
          dispatchError = err;
        }
        if (dispatchError === undefined) {
          await opts?.afterEachAttempt?.();
        }
        if (dispatchError !== undefined) throw dispatchError;
        return workerResult!;
      },
      {
        callerOwns: (o) =>
          opts?.extraCallerOwns?.(o) === true || "result" in o,
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

async function rewriteOutcomeProtocolFailure(input: {
  readonly familyBackend: FamilyBackend;
  readonly spec: WorkerSpec;
  readonly ctx: DispatchContext;
  readonly result: WorkerResult;
}): Promise<WorkerResult> {
  if (input.result.kind !== "malformed") return input.result;
  if (input.result.cmrLegAccountingPayload !== undefined) {
    return input.result;
  }
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
  for (let attempt = 1; attempt <= OUTCOME_REWRITE_RETRY_CAP; attempt++) {
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
  return {
    kind: "outcome_protocol_failure",
    reason:
      `worker outcome protocol failure persisted after ` +
      `${OUTCOME_REWRITE_RETRY_CAP} same-worker rewrite attempts: ` +
      lastFailure.reason,
    attempts: OUTCOME_REWRITE_RETRY_CAP,
    ...(sessionId !== undefined ? { sessionId } : {}),
  };
}

async function runIntegratedCmrPass(input: {
  readonly pass: IntegratedCmrPass;
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
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
  const dispatchCtx: DispatchContext = {
    familyBase,
    cmrPass: pass,
    ...(llmResolvedChildren !== undefined && llmResolvedChildren.length > 0
      ? { llmResolvedChildren }
      : {}),
    ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
    ...(moduleContext !== undefined ? { moduleContext } : {}),
    ...(priorCmrFindingIdentityKeys !== undefined
      ? { priorCmrFindingIdentityKeys }
      : {}),
  };
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
      if (postReviewGitAbort !== undefined) return postReviewGitAbort;
    }
    cmrResult = await rewriteOutcomeProtocolFailure({
      familyBackend,
      spec,
      ctx: dispatchCtx,
      result: rawCmrResult,
    });
    if (
      cmrResult.kind === "outcome_protocol_failure" &&
      cmrAttempt < MAX_DISPATCH_ATTEMPTS
    ) {
      // #598 r3 (codexA): an `outcome_protocol_failure` can also come from the
      // rewrite worker MOVING HEAD / leaving tracked changes (outcomeRewriteGitFailure).
      // Guard git state BEFORE the fresh re-dispatch so the next cmr attempt never runs
      // on top of a moved/dirty family base — if the reviewer moved HEAD, abort (not a
      // retryable state); otherwise re-dispatch on the clean expected head.
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
      if (reDispatchGitAbort !== undefined) return reDispatchGitAbort;
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
  if (postWorkerGitAbort !== undefined) return postWorkerGitAbort;
  if (cmrResult.kind === "escalated") {
    const reason = `${cmrResult.escalation.reason} — ${cmrResult.escalation.diagnosis}`;
    const stopSummary = cmrEscalationStopSummary(reason);
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
        : cmrResult.kind === "malformed" &&
            cmrResult.cmrLegAccountingPayload !== undefined
        ? legAccountingFailureStopSummary({
            reason,
            resolvedRoute,
            routeFingerprint,
            successfulLegs:
              cmrResult.cmrLegAccountingPayload.successfulLegs ?? [],
            skippedLegs: cmrResult.cmrLegAccountingPayload.skippedLegs,
          })
        : undefined;
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
    return { result: INCOMPLETE_GATE, familyHeadAfter: postWorkerFamilyHead };
  }
  if (
    !cmrResult.output.converged &&
    (cmrResult.output.findings === undefined ||
      cmrResult.output.findings.length === 0)
  ) {
    // #604 correctness r4 (D2): on a RESTART barrier the protected prior keys must
    // be accounted for EVEN when the fresh reviewer returns `converged:false` with
    // NO findings. Without this guard a reviewer could emit `{converged:false,
    // findings:[]}` while silently dropping the protected prior keys (no
    // claimedFixed, no disposition) and slip past the ADR 0030 coverage check as an
    // ordinary thin not_converged envelope. Run the well-formedness closure guard
    // (shape/coverage only — `allowStillActive:true`, matching the early guard)
    // BEFORE the thin not_converged abort; a missing-coverage payload fails closed
    // as contract_drift instead.
    //
    // #604 correctness r4 (D3): also run when the reviewer SELF-REPORTS a closure
    // payload on a first pass (claimed-fixed keys / dispositions with no protected
    // prior set) so a `converged:false, findings:[]` malformed self-report cannot
    // masquerade as an ordinary not_converged abort.
    const notConvergedHasClosurePayload =
      priorCmrFindingIdentityKeys !== undefined ||
      (cmrResult.output.claimedFixedFindingIdentityKeys?.length ?? 0) > 0 ||
      (cmrResult.output.priorFindingDispositions?.length ?? 0) > 0;
    if (notConvergedHasClosurePayload) {
      const notConvergedClosureFailure = cmrClosureFailureReason({
        pass,
        moduleContext,
        claimedFixedFindingIdentityKeys:
          cmrResult.output.claimedFixedFindingIdentityKeys,
        protectedPriorFindingIdentityKeys: priorCmrFindingIdentityKeys,
        priorFindingDispositions: cmrResult.output.priorFindingDispositions,
        allowStillActive: true,
      });
      if (notConvergedClosureFailure !== undefined) {
        await recordDurableAbort(familyBackend, {
          phase: "final",
          cmrPass: pass,
          reason: notConvergedClosureFailure,
          familyHeadAfter: postWorkerFamilyHead,
          stopSummary: contractDriftStopSummary({
            summary: notConvergedClosureFailure,
            repairHint:
              "repair the integrated CMR claimed-fixed closure payload and rerun the family barrier",
          }),
        });
        return {
          result: { ok: false, ran: true },
          familyHeadAfter: postWorkerFamilyHead,
        };
      }
    }
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
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter: postWorkerFamilyHead,
      blockingFindingIdentityKeys: [],
      stopSummary: notConvergedStopSummary(reason),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  const legAccountingFailure = cmrLegAccountingFailure(
    {
      successfulLegs: cmrResult.output.successfulLegs ?? [],
      skippedLegs: cmrResult.output.skippedLegs,
    },
    resolvedRoute,
  );
  if (legAccountingFailure !== undefined) {
    const reason = `integrated cmr ${pass} leg accounting failed: ${legAccountingFailure}`;
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter: postWorkerFamilyHead,
      stopSummary: legAccountingFailureStopSummary({
        reason,
        resolvedRoute,
        routeFingerprint,
        successfulLegs: cmrResult.output.successfulLegs ?? [],
        skippedLegs: cmrResult.output.skippedLegs,
      }),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  const floorFailure = cmrFloorFailureReason({
    pass,
    successfulLegs: cmrResult.output.successfulLegs,
    skippedLegs: cmrResult.output.skippedLegs,
  });
  if (floorFailure !== undefined) {
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason: floorFailure,
      familyHeadAfter: postWorkerFamilyHead,
      stopSummary: providerDegradedFloorStopSummary({
        reason: floorFailure,
        skippedLegs: cmrResult.output.skippedLegs,
      }),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  // #604 correctness r2 (C2): on a RESTART barrier the runner carries protected
  // prior finding identity keys (`priorCmrFindingIdentityKeys`) that the fresh
  // reviewer MUST account for (claimed-fixed or explicitly disposed). If that
  // closure payload is malformed — e.g. it leaves a protected prior key
  // unaccounted — this is a contract drift that MUST fail closed and mechanically
  // rerun, NEVER dispatch coder-fix. Pre-r2 the `blocking.length > 0` branch ran
  // FIRST, so a fresh pass that also happened to raise a NEW blocker slipped the
  // unrelated new blocker into coder-fix and bypassed this guard. Run the closure
  // guard BEFORE the blocking branch whenever protected prior keys are present.
  //
  // #604 correctness r4 (D3): the early guard must ALSO run on a FIRST pass
  // (`priorCmrFindingIdentityKeys === undefined`) whenever the reviewer SELF-REPORTS
  // a closure payload — a non-empty `claimedFixedFindingIdentityKeys` or
  // `priorFindingDispositions`. Pre-r4 the guard ran only when protected prior keys
  // existed, so a first-pass reviewer that claimed to have fixed prior findings
  // (with no runner-supplied prior set → `closure_context_missing`) slipped its NEW
  // blocker into coder-fix and never tripped the malformed-payload guard. Running
  // when ANY closure payload is present routes that malformed self-report to
  // contract_drift. A genuinely payload-free first pass (no claimed, no
  // dispositions, no protected keys) still skips the guard and preserves the normal
  // blocking→coder-fix path (the late guard at the end still runs for the converged
  // path).
  const hasClosurePayload =
    priorCmrFindingIdentityKeys !== undefined ||
    (cmrResult.output.claimedFixedFindingIdentityKeys?.length ?? 0) > 0 ||
    (cmrResult.output.priorFindingDispositions?.length ?? 0) > 0;
  // #604 correctness r4 (D3): the early guard is scoped to the NON-converged path.
  // A converged payload has its own LATE closure guard at the end (with the full
  // `verified-closed` assertion), so the early guard must NOT preempt it — doing so
  // would (a) let the early guard's `allowStillActive` skip the late guard's
  // still-active rejection on the converged path, and (b) change which malformed-
  // shape message wins there. On the converged path the early guard is a no-op; the
  // late guard owns the complete assertion.
  if (hasClosurePayload && !cmrResult.output.converged) {
    const earlyClosureFailure = cmrClosureFailureReason({
      pass,
      moduleContext,
      claimedFixedFindingIdentityKeys:
        cmrResult.output.claimedFixedFindingIdentityKeys,
      protectedPriorFindingIdentityKeys: priorCmrFindingIdentityKeys,
      priorFindingDispositions: cmrResult.output.priorFindingDispositions,
      // #604 correctness r4 (D1): the EARLY guard is a WELL-FORMEDNESS gate only.
      // A prior key that is claimed-fixed but disposed `still-active` /
      // `unable-to-assess` is a legitimate coder-fix input, NOT a contract drift —
      // aborting on it (the r2 C2 regression) starves the fix loop. Skip only the
      // `stillOpen` verified-closed assertion here; the LATE converged-path guard
      // (no flag) keeps the full closed assertion.
      allowStillActive: true,
    });
    if (earlyClosureFailure !== undefined) {
      await recordDurableAbort(familyBackend, {
        phase: "final",
        cmrPass: pass,
        reason: earlyClosureFailure,
        familyHeadAfter: postWorkerFamilyHead,
        stopSummary: contractDriftStopSummary({
          summary: earlyClosureFailure,
          repairHint:
            "repair the integrated CMR claimed-fixed closure payload and rerun the family barrier",
        }),
      });
      return {
        result: { ok: false, ran: true },
        familyHeadAfter: postWorkerFamilyHead,
      };
    }
  }
  let cmrFindingClassification: CmrEnvelope | undefined;
  if (
    cmrResult.output.findings !== undefined &&
    cmrResult.output.findings.length > 0
  ) {
    const priorDispositions = latestFamilyCmrDispositions(
      await familyBackend.readFamilyLedger(),
    );
    cmrFindingClassification = deriveCmrEnvelope({
      familyIssue: familyIssue ?? 0,
      findings: cmrResult.output.findings,
      moduleContext: moduleContext ?? { currentModules: [], childModules: [] },
      ...(priorDispositions !== undefined ? { priorDispositions } : {}),
    });
    if (cmrFindingClassification.blocking.length > 0) {
      const reason =
        `integrated cmr ${pass} found blocking family-scope findings: ` +
        cmrFindingClassification.results
          .filter(
            // #604 slice 4 (ADR 0062): only accepted-suppression is non-blocking;
            // the routing classifications (incl. cross_module_defer) are gone.
            (result) => result.classification !== "accepted_suppressed",
          )
          .map((result) => `${result.classification}:${result.identityKey}`)
          .join(", ");
      const stopSummary = familyCmrBlockingStopSummary(
        cmrFindingClassification,
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
        ...new Set(cmrFindingClassification.blocking.map(findingIdentityKey)),
      ];
      if (allowCoderFix) {
        // #604 slice 3 / ADR 0062: persist ONLY the thin envelope the runner reads
        // (blocking identity keys) + the gate's governance data (dispositions).
        // The fat `cmrFindingClassification` blob no longer lands on the ledger.
        await recordCmrReviewed(familyBackend, {
          cmrPass: pass,
          reason,
          familyHeadAfter: postWorkerFamilyHead,
          blockingFindingIdentityKeys,
          cmrDispositions: cmrFindingClassification.dispositions,
          stopSummary,
        });
        const fixRound = await runCmrCoderFix({
          pass,
          familyBackend,
          familyBase,
          classification: cmrFindingClassification,
          blockingFindingIdentityKeys,
          familyHeadBefore: postWorkerFamilyHead,
          escalationAnswer,
          familyIssue,
          resolvedRoute,
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
      await recordDurableAbort(familyBackend, {
        phase: "final",
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        blockingFindingIdentityKeys,
        cmrDispositions: cmrFindingClassification.dispositions,
        stopSummary,
      });
      return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
    }
  }
  if (
    !cmrResult.output.converged &&
    (cmrFindingClassification === undefined ||
      (cmrFindingClassification.deferred.length === 0 &&
        cmrFindingClassification.dispositions.length === 0))
  ) {
    const reason =
      cmrResult.output.reason ?? `integrated cmr ${pass} did not converge`;
    // #604 slice 3 / ADR 0062: not_converged carries no blocking findings — the
    // thin envelope keeps `blockingFindingIdentityKeys: []`, staying in the
    // runner's classified-abort branch while yielding no pending keys.
    //
    // #604 rework (codexB): DO NOT write `cmrDispositions: []` — see the twin
    // not_converged branch above. An empty tombstone masks the prior round's real
    // accepted-suppression dispositions and resets the reopen/dispute budget. The
    // field is left UNDEFINED so the prior dispositions carry forward.
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter: postWorkerFamilyHead,
      blockingFindingIdentityKeys: [],
      stopSummary: notConvergedStopSummary(reason),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  const closureFailure = cmrClosureFailureReason({
    pass,
    moduleContext,
    claimedFixedFindingIdentityKeys:
      cmrResult.output.claimedFixedFindingIdentityKeys,
    protectedPriorFindingIdentityKeys: priorCmrFindingIdentityKeys,
    priorFindingDispositions: cmrResult.output.priorFindingDispositions,
  });
  if (closureFailure !== undefined) {
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason: closureFailure,
      familyHeadAfter: postWorkerFamilyHead,
      stopSummary: contractDriftStopSummary({
        summary: closureFailure,
        repairHint:
          "repair the integrated CMR claimed-fixed closure payload and rerun the family barrier",
      }),
    });
    return { result: { ok: false, ran: true }, familyHeadAfter: postWorkerFamilyHead };
  }
  await recordCmrPassed(familyBackend, {
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
      skippedLegs: cmrResult.output.skippedLegs,
    }),
  });
  return { result: { ok: true, ran: true }, familyHeadAfter: postWorkerFamilyHead };
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
    resolvedRoute = resolveActiveModelRoute();
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
  // makes it invoke `gstack-ship`.
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
  const shipResult = await dispatchOrAbort(
    familyBackend,
    familyShipWorkerSpec(resolvedRoute),
    {
      familyBase,
      ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
    },
    undefined,
  );
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
  // ── cmr S336 r4 (P1): the terminal family gate must NOT trust the discriminant
  // alone. verifyCmr explicitly allows ANY FamilyBackend to implement the unified
  // dispatchWorker seam — a backend that implements the seam but skips the success
  // contract (the real RealFamilyBackend.dispatchShipWorker enforces it, but a
  // minimal seam-only backend need not) could return a `completed {kind:"ship"}`
  // that never opened the family PR (status:"pushed", missing/blank pr) or opened
  // it on the WRONG branch. Re-assert the family-ship contract here, fail-CLOSED
  // (defense-in-depth, independent of which backend produced the payload; mirrors
  // the non-completed/non-ship fail-safe just above). 止于 PR (decision 4) means a
  // REAL family PR on the family base: branch === familyBase, status === "pr_opened",
  // pr a non-empty string — anything else did not open the PR → INCOMPLETE_GATE.
  const ship = shipResult.output;
  if (
    ship.branch !== familyBase ||
    ship.status !== "pr_opened" ||
    !isFilledString(ship.pr)
  ) {
    const postShipFamilyHead = await readPostCmrFamilyHead(
      familyBackend,
      familyBase,
      cmrPassedFamilyHeadAfter,
    );
    const shipPrState = describeShipPrState(ship);
    const reason =
      `family ship worker did not open a valid family PR: ${shipPrState}; ` +
      `expected branch=${familyBase} status=pr_opened and a non-empty PR URL`;
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
          "repair the family ship worker result/PR state and rerun the final family barrier",
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
            actualFamilyHead: "family head after ship contract failure",
            verifiedCmrHead: "latest cmr_passed ledger row",
          },
        },
      }),
    });
    return INCOMPLETE_GATE;
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
  if (!isFilledString(ship.prHead) || ship.prHead !== exactPostShipFamilyHead) {
    const reason =
      `family ship worker opened a PR, but the PR head (${ship.prHead ?? "missing"}) ` +
      `does not match current family HEAD (${exactPostShipFamilyHead}); refusing to persist a shipped marker`;
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: { reason },
      familyHeadAfter: exactPostShipFamilyHead,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: exactPostShipFamilyHead,
      stopSummary: infraFailureStopSummary({
        summary: reason,
        repairHint:
          "repair the family ship worker PR head binding and rerun the final family barrier",
        ship: {
          latestVerifiedCmrHead: cmrPassedFamilyHeadAfter,
          currentFamilyHead: exactPostShipFamilyHead,
          reportedFamilyHead: ship.prHead,
          shipPrState: "pr-head-mismatch",
        },
        heads: {
          actualFamilyHead: exactPostShipFamilyHead,
          verifiedCmrHead: cmrPassedFamilyHeadAfter,
          sources: {
            actualFamilyHead: "family head after ship worker",
            verifiedCmrHead: "latest cmr_passed ledger row",
          },
        },
      }),
    });
    return INCOMPLETE_GATE;
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
    reportedFamilyHead: ship.prHead,
    actualFamilyHead: exactPostShipFamilyHead,
    ...(cmrPassedFamilyHeadAfter !== undefined
      ? { verifiedCmrHead: cmrPassedFamilyHeadAfter }
      : {}),
    sources: {
      reportedFamilyHead: "ship worker reported prHead",
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
    pr: ship.pr,
    familyHeadAfter: exactPostShipFamilyHead,
    stopSummary: shippedStopSummary,
  });

  // #600: run the shared online review-loop stage (bot poll → verify → fixer →
  // fresh re-verify) before writing the terminal family review-loop marker.
  const reviewLoop = await runFamilyOnlineReviewLoop({
    familyBackend,
    familyBase,
    ship: {
      kind: "ship",
      branch: familyBase,
      pr: ship.pr,
      prHead: ship.prHead,
      status: "pr_opened",
    },
    resolvedRoute,
  });
  if (!reviewLoop.ok) {
    const stopSummary = familyOnlineReviewLoopFailureStopSummary(reviewLoop);
    const reason = stopSummary.summary;
    const abortFamilyHead = await familyConvergenceMarkerHead(
      familyBackend,
      familyBase,
      exactPostShipFamilyHead,
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
  );
  await recordReviewLoopConverged(familyBackend, {
    pr: ship.pr,
    familyHeadAfter: convergedFamilyHead,
    ...(shippedStopSummary !== undefined
      ? { stopSummary: shippedStopSummary }
      : {}),
  });
  return { ok: true, ran: true };
}
