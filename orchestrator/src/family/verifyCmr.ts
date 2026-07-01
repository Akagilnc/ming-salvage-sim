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
 *     Step 6 correctness only after completeness passes. Each pass is a write-capable
 *     cmr worker over the current family base and returns a TERMINAL pass verdict
 *     (`converged` | `escalate`). A converged pass may have committed pass-local
 *     fixes, so the next pass reads the post-worker family HEAD. Escalate / malformed
 *     / contract-slip verdicts are recorded as durable aborts and stop before ship.
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
  classifyFamilyCmrFindings,
  type FamilyCmrClassification,
  type FamilyModuleContext,
} from "./cmrClassification.js";
import {
  cmrWorkerSpec,
  dispatchFamilyWorker,
  familyShipWorkerSpec,
} from "./dispatchFamilyWorker.js";
import {
  cmrLegAccountingFailure,
  modelRouteFingerprint,
  resolveActiveModelRoute,
  type ResolvedModelRoute,
} from "../modelRoutes.js";
import { hasAcceptedSuppressionAuthority } from "../acceptedSuppression.js";
import { modelFamilyForCmrReviewLeg } from "../modelRegistry.js";
import { modelIsStrongLeg } from "../realBackend.js";
import type { EscalationAnswerPayload, FindingDisposition } from "../types.js";
import { findingIdentityKey } from "../findings.js";
import {
  cmrPassAlreadyPassed,
  recordAborted as recordDurableAbort,
  recordCmrPassed,
  recordShipped,
} from "./ledger.js";
import { isFilledString } from "../shipOutcome.js";
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
  /** Parsed module declarations for family-CMR defer classification (#449). */
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
      ? input.skippedLegs.map((leg) => ({
          provider: modelFamilyForCmrReviewLeg(leg.slug),
          leg: leg.slug,
          reason: leg.reason,
          blocking: true,
          repairHint: `restore provider availability for ${leg.slug} and rerun the CMR gate`,
        }))
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

function providerDegradedWorkerFailureStopSummary(input: {
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
  const matchedLegs = input.resolvedRoute.legCollections.cmrReview.filter(
    (leg) => {
      const rawFamily = "family" in leg ? leg.family : undefined;
      const family =
        typeof rawFamily === "string" ? rawFamily.toLowerCase() : undefined;
      return (
        normalizedReason.includes(leg.slug.toLowerCase()) ||
        (family !== undefined && normalizedReason.includes(family))
      );
    },
  );
  const providerDegraded =
    matchedLegs.length > 0
      ? matchedLegs.map((leg) => ({
          provider: modelFamilyForCmrReviewLeg(leg.slug),
          leg: leg.slug,
          reason: input.reason,
          blocking: true,
          repairHint: `restore provider availability for ${leg.slug} and rerun the CMR gate`,
        }))
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
    providerDegraded: input.skippedLegs.map((leg) => ({
      provider: modelFamilyForCmrReviewLeg(leg.slug),
      leg: leg.slug,
      reason: leg.reason,
      blocking: false,
      repairHint: `restore provider availability for ${leg.slug} before making this leg required`,
    })),
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
  classification: FamilyCmrClassification,
  fallbackReason: string,
): StopSummary {
  const blockingClassifications = new Set([
    "same_module_still_red",
    "owning_issue_still_red",
    "spec_conflict",
    "infra_failure",
  ]);
  const result =
    classification.results.find(
      (item) =>
        item.classification === "owning_issue_still_red" ||
        item.classification === "spec_conflict" ||
        item.classification === "infra_failure",
    ) ??
    classification.results.find((item) =>
      blockingClassifications.has(item.classification),
    );
  const finding =
    result !== undefined
      ? classification.blocking.find(
          (item) => findingIdentityKey(item) === result.identityKey,
        )
      : undefined;
  if (result?.classification === "same_module_still_red") {
    if (finding !== undefined) {
      return stopReasonForFindingDisposition({
        kind: "same_module",
        finding,
        reason: result.reason || fallbackReason,
      });
    }
    return {
      reason: "same_module_still_red",
      summary: result.reason || fallbackReason,
      repairHint: "fix the same-module family CMR finding and rerun",
    };
  }
  if (result?.classification === "owning_issue_still_red") {
    if (finding !== undefined && result.owningIssue !== undefined) {
      return stopReasonForFindingDisposition({
        kind: "owning_issue_still_red",
        finding,
        owningIssue: result.owningIssue,
        missingSurface: result.missingSurface,
        nextStep: result.nextStep,
        reason: result.reason || fallbackReason,
      });
    }
    return {
      reason: "owning_issue_still_red",
      summary: result.reason || fallbackReason,
      ...(result.owningIssue !== undefined ? { owningIssue: result.owningIssue } : {}),
      ...(result.missingSurface !== undefined
        ? { missingSurface: result.missingSurface }
        : {}),
      ...(result.nextStep !== undefined ? { nextStep: result.nextStep } : {}),
      repairHint: "close the owning issue surface before rerun",
    };
  }
  if (result?.classification === "spec_conflict") {
    if (finding !== undefined) {
      return stopReasonForFindingDisposition({
        kind: "spec_conflict",
        finding,
        reason: result.reason || fallbackReason,
      });
    }
    return {
      reason: "spec_conflict",
      summary: result.reason || fallbackReason,
      repairHint: "resolve the specification conflict and rerun",
    };
  }
  if (result?.classification === "infra_failure") {
    if (finding !== undefined) {
      return stopReasonForFindingDisposition({
        kind: "infra_failure",
        finding,
        reason: result.reason || fallbackReason,
        repairHint: "repair the infrastructure failure and rerun the family CMR gate",
      });
    }
    return infraFailureStopSummary({
      summary: result.reason || fallbackReason,
      repairHint: "repair the infrastructure failure and rerun the family CMR gate",
    });
  }
  return {
    reason: "same_module_still_red",
    summary: fallbackReason,
    repairHint: "fix the blocking family CMR finding and rerun",
  };
}

function familyCmrPassStopSummary(input: {
  readonly classification?: FamilyCmrClassification;
  readonly familyHeadAfter?: string;
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
}): StopSummary | undefined {
  const crossModule = input.classification?.results.find(
    (result) => result.classification === "cross_module_defer",
  );
  const finding = input.classification?.deferred[0];
  if (
    crossModule !== undefined &&
    finding !== undefined &&
    crossModule.targetModule !== undefined
  ) {
    return stopReasonForFindingDisposition({
      kind: "cross_module",
      finding,
      targetModule: crossModule.targetModule,
      reason: crossModule.reason,
    });
  }
  const acceptedSuppressions = input.classification?.dispositions
    .filter(hasAcceptedSuppressionAuthority)
    .map((disposition) => ({
      source: disposition.source!,
      scope: disposition.scope!,
      reason: disposition.reason!,
      findingIdentity: disposition.identityKey,
      boundedReopen: disposition.boundedReopen!,
    }));
  if (
    (acceptedSuppressions === undefined || acceptedSuppressions.length === 0) &&
    (input.skippedLegs === undefined || input.skippedLegs.length === 0)
  ) {
    return providerDegradedPassStopSummary({
      familyHeadAfter: input.familyHeadAfter,
      skippedLegs: input.skippedLegs,
    });
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
    ...(acceptedSuppressions !== undefined && acceptedSuppressions.length > 0
      ? { acceptedSuppressions }
      : {}),
    ...(input.skippedLegs !== undefined && input.skippedLegs.length > 0
      ? {
          providerDegraded: input.skippedLegs.map((leg) => ({
            provider: modelFamilyForCmrReviewLeg(leg.slug),
            leg: leg.slug,
            reason: leg.reason,
            blocking: false,
            repairHint: `restore provider availability for ${leg.slug} before making this leg required`,
          })),
        }
      : {}),
  });
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

function latestFamilyCmrDispositions(
  ledger: ReadonlyArray<{
    readonly cmrFindingClassification?: {
      readonly dispositions: ReadonlyArray<FindingDisposition>;
    };
  }>,
): ReadonlyArray<FindingDisposition> | undefined {
  return [...ledger]
    .reverse()
    .find((entry) => entry.cmrFindingClassification?.dispositions !== undefined)
    ?.cmrFindingClassification?.dispositions;
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
async function dispatchOrAbort(
  familyBackend: FamilyBackend,
  spec: Parameters<typeof dispatchFamilyWorker>[1],
  ctx: Parameters<typeof dispatchFamilyWorker>[2],
): Promise<Awaited<ReturnType<typeof dispatchFamilyWorker>>> {
  try {
    return await dispatchFamilyWorker(familyBackend, spec, ctx);
  } catch (err) {
    const reason = `family ${spec.kind} worker threw on startup: ${
      err instanceof Error ? err.message : String(err)
    }`;
    return { kind: "failed", reason };
  }
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
  readonly resolvedRoute: ResolvedModelRoute;
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
  const cmrResult = await dispatchOrAbort(
    familyBackend,
    cmrWorkerSpec("fresh", pass, resolvedRoute),
    {
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
    },
  );
  const postWorkerFamilyHead = await readPostCmrFamilyHead(
    familyBackend,
    familyBase,
    resolvedFamilyHeadAfter,
  );
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
        : cmrResult.kind === "malformed"
          ? `family integrated cmr ${pass} worker malformed: ${cmrResult.reason}`
          : `family integrated cmr ${pass} worker returned no valid result (crash/malformed)`;
    const stopSummary =
      cmrResult.kind === "failed"
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
  let cmrFindingClassification: FamilyCmrClassification | undefined;
  if (
    cmrResult.output.findings !== undefined &&
    cmrResult.output.findings.length > 0
  ) {
    const priorDispositions = latestFamilyCmrDispositions(
      await familyBackend.readFamilyLedger(),
    );
    cmrFindingClassification = classifyFamilyCmrFindings({
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
            (result) =>
              result.classification !== "cross_module_defer" &&
              result.classification !== "accepted_suppressed",
          )
          .map((result) => `${result.classification}:${result.identityKey}`)
          .join(", ");
      await recordDurableAbort(familyBackend, {
        phase: "final",
        cmrPass: pass,
        reason,
        familyHeadAfter: postWorkerFamilyHead,
        cmrFindingClassification,
        stopSummary: familyCmrBlockingStopSummary(
          cmrFindingClassification,
          reason,
        ),
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
    await recordDurableAbort(familyBackend, {
      phase: "final",
      cmrPass: pass,
      reason,
      familyHeadAfter: postWorkerFamilyHead,
      cmrFindingClassification: {
        blocking: [],
        deferred: [],
        dispositions: [],
        results: [
          {
            identityKey: `not_converged|${pass}`,
            classification: "not_converged",
            attribution: { method: "reviewer_disposition" },
            reason,
          },
        ],
        moduleContext: {
          currentModules: [],
          childModules: [],
          undevelopedModules: [],
        },
      },
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
    cmrFindingClassification,
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
  const verify: FamilyVerifyResult = await familyBackend.runFamilyVerify({ phase, familyBase });
  if (!verify.ok) {
    const reason = verify.errorPackage?.reason ?? "family verify failed";
    // (a) in-memory seam (back-compat, #296) — enriched with the abort-time head.
    await familyBackend.recordAborted?.({
      phase,
      familyBase,
      errorPackage: verify.errorPackage ?? { reason },
      familyHeadAfter,
    });
    // (b) PHASE-LEVEL DURABLE ledger entry (#291 缺口 2): so the abort reaches the
    //     ledger reconcile reads末条 familyHeadAfter from, not only the seam array.
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter,
      stopSummary: familyVerifyFailureStopSummary(reason),
    });
    return { ok: false, ran: true };
  }

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
  const priorKeysForPass = (
    pass: IntegratedCmrPass,
  ): readonly string[] | undefined =>
    priorCmrFindingIdentityKeysByPass?.[pass] ?? priorCmrFindingIdentityKeys;
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
    resolvedRoute,
  });
  if (!completeness.result.ok) return completeness.result;

  const correctness = await runIntegratedCmrPass({
    pass: "correctness",
    familyBackend,
    familyBase,
    llmResolvedChildren,
    escalationAnswer,
    familyHeadAfter: completeness.familyHeadAfter,
    familyIssue,
    moduleContext,
    priorCmrFindingIdentityKeys: priorKeysForPass("correctness"),
    resolvedRoute,
  });
  if (!correctness.result.ok) return correctness.result;
  const cmrPassedFamilyHeadAfter = correctness.familyHeadAfter;
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
    await familyBackend.escalateFamily?.({
      reason: escalationReason,
      familyHeadAfter: postShipFamilyHead,
    });
    await recordDurableAbort(familyBackend, {
      phase,
      reason,
      familyHeadAfter: postShipFamilyHead,
      stopSummary,
    });
    return { ok: false, ran: true };
  }
  if (shipResult.kind !== "completed" || shipResult.output.kind !== "ship") {
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
  const materialCmrSummary = [...(await familyBackend.readFamilyLedger())]
    .reverse()
    .find(
      (entry) =>
        entry.status === "cmr_passed" &&
        entry.familyHeadAfter === cmrPassedFamilyHeadAfter &&
        entry.stopSummary !== undefined &&
        isMaterialCmrStopSummary(entry.stopSummary),
    )?.stopSummary;
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
  return { ok: true, ran: true };
}
