/**
 * runFamily — the family spine (ADR 0022 decisions 1/2/3②/6, #293).
 *
 * The thinnest complete family closure:
 *   parent epic (children already cut + blocked_by)             [ADR 0022 dec.1]
 *     → commander.selectWave → the unblocked wave
 *     → fan out each child through the REUSED single-slice runOrchestrator,
 *       in family mode (cut from family base, S7 = local child handoff) [dec.2/7]
 *     → merger.mergeChild → serial `git merge --no-ff` into family base [dec.3②]
 *       (which writes the append-only family-ledger entry)             [dec.5]
 *     → verify-cmr hook                                            [dec.3④/⑥ seam]
 *     → loop until the commander returns an empty wave.
 *
 * The spine is a THIN scheduler: it OWNS none of the four extension modules'
 * logic — it only CALLS them (selectWave / runOrchestrator / mergeChild /
 * runVerifyCmr). That is the acceptance-4 boundary: #294 (waves), #295 (merge
 * conflict), #296 (verify+cmr), #298 (ledger) each grow THEIR module and the
 * spine keeps calling the same functions. Those modules now provide conflict,
 * verify/CMR, and crash-resume handling behind the same calls.
 *
 * The wave loop is written generally (re-select after each wave from the merged
 * set) so #294's multi-wave dependency scheduling drops in WITHOUT a spine
 * rewrite — but #293's children are all independent, so it converges in one wave.
 */

import { runOrchestrator } from "../runner.js";
import { mintRunId } from "../runId.js";
import {
  familyRelaySlotsForWall,
  knownLiveBillingPoolsFromRoute,
  printableRouteLineup,
  degradeOptionalRouteSmokeFailures,
  routeSmokeFailure,
  type ModelRouteSlot,
  type ResolvedModelRoute,
} from "../modelRoutes.js";
import {
  admitRouteFromEnv,
  admitRelayBaton,
  admissionRouteFailureDiagnosis,
} from "../admissionPreflight.js";
import {
  CoderRecError,
  lookupCoderRosterEntry,
  resolveCoderRecOrder,
} from "../coderRoster.js";
import {
  billingPoolFromQuotaPool,
  resolveRelayPools,
  type BillingPoolId,
  type NextRelayBaton,
} from "../quotaPoolTable.js";
import {
  isQuotaWaitForResetError,
  type QuotaWaitForResetError,
} from "../quotaProbe.js";
import { parkOrRelayQuotaWall } from "../quotaParkRelay.js";
import { MAX_RELAY_HANDOFFS } from "../relayDispatch.js";
import { logDriverStage } from "../stageLog.js";
import { isAnyStepId, isStepId } from "../types.js";
import { isRunnerSynthesizedFailureEscalation } from "../runnerEscalation.js";
import type {
  Backend,
  EscalationAnswerPayload,
  LedgerEntry,
  PersistentLedgerEntry,
  SliceStepId,
  StepId,
} from "../types.js";
import { escalateOf, isValidEscalation } from "../validate.js";
import { assertAcyclic, DependencyCycleError, selectWave } from "./commander.js";
import {
  childEscalationAnswer,
  familyEscalationState,
  familyReviewLoopConvergedForHead,
  familyShippedRecordForReviewLoopResume,
  familyOpenShippedForOnlineReview,
  familyPostMergeCleanupForHead,
  familyPrMergedForHead,
  isMergedAccountingEntry,
  mergedSet,
  recordAdmissionSkipped,
  recordChildDecisionParked,
  recordFamilyEscalated,
  recordMerged,
  recordReviewLoopConverged,
  unansweredChildEscalations,
} from "./ledger.js";
import { mergeChild } from "./merger.js";
import { reconcileFamilyLedger } from "./reconcile.js";
import {
  ensureFamilyPostMergeCleanup,
  runFamilyOnlineReviewLoop,
  runVerifyCmr,
} from "./verifyCmr.js";
import {
  familyAutoMergeIncomplete,
  isFamilyPrLiveMerged,
  runFamilyAutoMergeStage,
} from "./familyAutoMerge.js";
import { buildFamilyModuleContext } from "./moduleDeclaration.js";
import {
  decisionGateParkStopSummary,
  infraFailureStopSummary,
  successStopSummary,
  type StopSummary,
} from "../stopSummary.js";
import {
  familyTerminalFromStopSummary,
  isFamilyStageFailureStatus,
  resolveFamilyStageTerminal,
  stageFailureStopSummary,
  syncStopSummaryToStageFailure,
  type FamilyStageFailureStatus,
} from "./familyTerminal.js";
import type {
  ChildSlice,
  FamilyBackend,
  FamilyChildDiagnostic,
  FamilyChildEscalation,
  FamilyChildResult,
  FamilyLedgerEntry,
  FamilyRunInput,
  FamilyRunResult,
  FamilyRunStatus,
  IntegratedCmrPass,
} from "./types.js";
import type { VerifyCmrPhase } from "./verifyCmr.js";

function filled(value: string | undefined): string | undefined {
  if (value == null) return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

/**
 * Resolve epic Coder-Rec body for family quota walls from live issue meta only
 * (#936 / #934 ID-002: snapshot dual court deleted). Missing body → undefined
 * (default roster is legal). Present body is returned as-is so
 * {@link resolveCoderRecOrder} can fail-closed on broken marks (#906) — never
 * swallow CoderRecError into silent default.
 *
 * Meta read failure must NOT collapse to undefined → silent default roster.
 * Fail-closed by rethrowing.
 */
async function resolveFamilyCoderRecBody(
  backend: Backend,
  epicIssue: number,
): Promise<string | undefined> {
  try {
    const meta = await backend.fetchIssueMeta(epicIssue);
    if (typeof meta.body === "string" && meta.body.trim().length > 0) {
      return meta.body;
    }
    // Read succeeded but body empty/missing → legal default roster.
    return undefined;
  } catch (err) {
    const metaMsg = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Coder-Rec body unreadable for epic #${epicIssue} (meta failed): ${metaMsg}`,
    );
  }
}

/** Optional test seam / production override for pure baton apply. */
export type ApplyRelayBatonToRouteFn = (
  route: ResolvedModelRoute,
  baton: Pick<NextRelayBaton, "slug">,
  wallStep?: StepId,
  opts?: { readonly slots?: ReadonlyArray<ModelRouteSlot> },
) => ResolvedModelRoute;

function familyChildrenSnapshot(opts: {
  readonly familyBackend: FamilyBackend;
  readonly recordedResults: ReadonlyArray<FamilyChildResult>;
  readonly epicChildren: ReadonlyArray<ChildSlice>;
}): Promise<FamilyChildResult[]> {
  return (async () => {
    const ledgerMerged = mergedSet(await opts.familyBackend.readFamilyLedger());
    const recorded = new Map(opts.recordedResults.map((c) => [c.issue, c]));
    return opts.epicChildren.map((c) => {
      const rec = recorded.get(c.issue);
      if (rec !== undefined) return rec;
      if (ledgerMerged.has(c.issue)) {
        return { issue: c.issue, status: "already_done" as const };
      }
      return { issue: c.issue, status: "skipped" as const };
    });
  })();
}

/**
 * #909 B1 full invariant — family barrier QuotaWait decision.
 *
 * Reuses the single-slice park/relay machine ({@link parkOrRelayQuotaWall},
 * {@link resolveRelayPools}, {@link applyRelayBatonToRoute}). Outcomes:
 *   - park / park_fallback → structured FamilyRunResult escalate (provider_degraded)
 *   - relay → APPLY baton to route and return for in-process barrier re-dispatch
 *     (next dispatch uses toModel/toPool). Never "stage focus then escalate".
 *   - broken Coder-Rec → fail-closed escalate (#906), never silent default roster
 *
 * Do NOT write a blocking `escalationKind:"failure"` family ledger row on park
 * — re-feed must re-enter the barrier (single-slice planResume spirit).
 */
/**
 * Slot-scoped baton billing pool. Bound only to wall roles rewritten by the
 * baton — never a barrier-wide sticky that rewrites unrelated workers
 * (e.g. sonnet ship + codex-5h).
 */
export type FamilyRelayBillingBinding = {
  readonly pool: BillingPoolId;
  readonly slots: ReadonlyArray<ModelRouteSlot>;
};

type FamilyQuotaWallDecision =
  | { readonly kind: "park"; readonly result: FamilyRunResult }
  | {
      readonly kind: "relay";
      readonly nextBaton: NextRelayBaton;
      readonly appliedRoute: ResolvedModelRoute;
      readonly wallSlots: ReadonlyArray<ModelRouteSlot>;
      readonly relayBrief: string | undefined;
    };

/** Family barrier / merge wall phases that share the park/relay machine. */
export type FamilyQuotaWallPhase =
  | "wave"
  | "final"
  | "online_review"
  | "merge";

/**
 * Correctness C1 — wall step for baton consume slots.
 * Prefer the QuotaWait ledger step when it is a full StepId (incl. S9–S12);
 * never coerce endgame steps off the map via {@link isStepId} alone.
 * Phase defaults only when the error carries no usable step.
 */
export function familyWallStepFromQuotaWait(opts: {
  readonly err: QuotaWaitForResetError;
  readonly phase: FamilyQuotaWallPhase;
}): StepId {
  const raw = opts.err.applied.ledgerEntry?.step;
  if (raw !== undefined && isAnyStepId(raw)) return raw;
  if (opts.phase === "online_review") return "S9";
  if (opts.phase === "merge") return "S1";
  if (opts.phase === "wave") return "S9";
  return "S7";
}

async function decideFamilyQuotaWall(opts: {
  readonly err: QuotaWaitForResetError;
  readonly phase: FamilyQuotaWallPhase;
  readonly familyBackend: FamilyBackend;
  readonly singleSliceBackend: Backend;
  readonly familyBase: string;
  readonly familyHead: string | undefined;
  readonly runId: string;
  readonly modelRoute: ResolvedModelRoute;
  readonly recordedResults: ReadonlyArray<FamilyChildResult>;
  readonly epicChildren: ReadonlyArray<ChildSlice>;
  readonly epicIssue: number;
  readonly relayPools?: FamilyRunInput["relayPools"];
  readonly admissionSkipped?: FamilyRunResult["admissionSkipped"];
  readonly now?: Date;
  /** In-run relay handoff count (caps with {@link MAX_RELAY_HANDOFFS}). */
  readonly relayHandoffsSoFar: number;
  /**
   * Optional apply override (tests: identity must RED the consumed-slot nail).
   * Production leaves unset → {@link applyRelayBatonToRoute}.
   */
  readonly applyRelayBatonToRoute?: ApplyRelayBatonToRouteFn;
  /** When known, narrow family S3 CMR wall to the pass that hit the wall. */
  readonly cmrPass?: "completeness" | "correctness";
  /**
   * Correctness B3 — run-scoped wall-hit pools excluded from knownLive promote.
   * Mutated here when this wall's pool is recorded.
   */
  readonly wallHitBillingPools?: Set<BillingPoolId>;
}): Promise<FamilyQuotaWallDecision> {
  const buildParkResult = async (
    stopSummary: StopSummary,
    escalation?: { readonly reason: string; readonly diagnosis: string },
  ): Promise<FamilyQuotaWallDecision> => {
    const children = await familyChildrenSnapshot(opts);
    return {
      kind: "park",
      result: {
        status: "escalated",
        familyBase: opts.familyBase,
        familyHead: opts.familyHead,
        escalation: escalation ?? {
          reason: stopSummary.summary,
          diagnosis:
            stopSummary.repairHint ??
            "wait for provider quota reset, then re-feed the family run",
        },
        stopSummary,
        children,
        ...(opts.admissionSkipped !== undefined &&
        opts.admissionSkipped.length > 0
          ? { admissionSkipped: opts.admissionSkipped }
          : {}),
      },
    };
  };

  const currentPool = billingPoolFromQuotaPool(opts.err.pool);
  // C1: full StepId (S9/S10/S12/S1…) for consume-slot map — isStepId-only
  // coercion to S7 rewrote online-review verify onto ship.
  const wallStep = familyWallStepFromQuotaWait({
    err: opts.err,
    phase: opts.phase,
  });
  // parkOrRelayQuotaWall ledger rows are child LedgerEntry (SliceStepId only);
  // endgame walls keep their identity on family audit + baton apply, park uses
  // a SliceStepId stand-in when needed.
  const parkStep: import("../types.js").SliceStepId = isStepId(wallStep)
    ? wallStep
    : "S7";
  // Family reuses S3/S7 ids but consumes cmr/ship — never single-slice coder map.
  // N2: prefer explicit opts.cmrPass, else stamp from the QuotaWait error (pass
  // worker rethrow). S3 without pass must not dual-rewrite both CMR slots.
  const wallCmrPass =
    opts.cmrPass ??
    (opts.err.cmrPass === "completeness" || opts.err.cmrPass === "correctness"
      ? opts.err.cmrPass
      : undefined);
  let wallSlots: ReadonlyArray<ModelRouteSlot>;
  try {
    wallSlots = familyRelaySlotsForWall({
      phase: opts.phase,
      wallStep,
      ...(wallCmrPass !== undefined ? { cmrPass: wallCmrPass } : {}),
    });
  } catch (slotErr) {
    const diagnosis =
      slotErr instanceof Error ? slotErr.message : String(slotErr);
    return buildParkResult(
      {
        reason: "provider_degraded",
        summary: `family ${opts.phase} S3 quota wall missing cmrPass — refuse dual CMR rewrite`,
        repairHint: diagnosis,
      },
      {
        reason: "family S3 wall requires cmrPass",
        diagnosis,
      },
    );
  }
  const inMemoryLedger: LedgerEntry[] = [];
  const worktreePath = opts.familyBackend.resolveFamilyWorkingRepo?.();

  // #906: body-read total failure + broken Coder-Rec both fail closed —
  // never resolveCoderRecOrder(undefined) as a silent default from errors.
  let rosterOrder;
  try {
    const coderRecBody = await resolveFamilyCoderRecBody(
      opts.singleSliceBackend,
      opts.epicIssue,
    );
    rosterOrder = resolveCoderRecOrder(coderRecBody);
  } catch (err) {
    const diagnosis =
      err instanceof CoderRecError
        ? err.message
        : err instanceof Error
          ? err.message
          : String(err);
    // #934 ID-001/005: family Recovery reads family-ledger.jsonl — never park
    // (or fail-closed escalate) without a durable family-ledger boundary.
    await opts.familyBackend.appendFamilyLedger({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: `quota_park:${opts.phase}`,
      reason: `Coder-Rec fail-closed at family ${opts.phase}: ${diagnosis}`,
    });
    return buildParkResult(
      {
        reason: "infra_failure",
        summary: `Coder-Rec fail-closed on family ${opts.phase} quota wall`,
        repairHint: diagnosis,
      },
      {
        reason: "Coder-Rec fail-closed",
        diagnosis,
      },
    );
  }

  // Cap chain length the same way single-slice does (ledger + in-run count).
  if (opts.relayHandoffsSoFar >= MAX_RELAY_HANDOFFS) {
    const stopSummary: StopSummary = {
      reason: "provider_degraded",
      summary: `quota wait for reset on pool ${opts.err.pool} (relay handoff cap ${MAX_RELAY_HANDOFFS})`,
      repairHint:
        "wait for the provider quota to reset, then re-feed — family barrier re-enters from ledger truth",
    };
    await opts.familyBackend.appendFamilyLedger({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: `quota_park:${opts.phase}`,
      reason: stopSummary.summary,
    });
    return buildParkResult(stopSummary);
  }

  // Wall-hit role model = first consume slot's current slug (cmr/ship/…),
  // NOT always coder (default normal coder is already terra → hollow walk).
  const wallRef = opts.modelRoute.slots[wallSlots[0]!];
  const currentModelId =
    lookupCoderRosterEntry(wallRef)?.id ?? wallRef;

  // Shared pool seam: explicit override wins; else default + route-smoke knownLive
  // so production can reach a live baton without test-only injection.
  // B3: accumulate wall-hit pools so smoke-passed walls stay out of knownLive.
  opts.wallHitBillingPools?.add(currentPool);
  const pools = resolveRelayPools(
    currentPool,
    opts.err.disposition.resetAt,
    opts.relayPools,
    knownLiveBillingPoolsFromRoute(opts.modelRoute),
    opts.wallHitBillingPools,
  );

  // #934 R6 F4: family Recovery only reads family-ledger.jsonl. Do not also
  // write slice steps.jsonl via parkOrRelayQuotaWall (half dual court). The
  // sole durable boundary is appendFamilyLedger below (fail-closed).
  const outcome = await parkOrRelayQuotaWall({
    step: parkStep,
    err: opts.err,
    ledger: inMemoryLedger,
    stateDir: undefined,
    sessionId: opts.runId,
    backend: opts.singleSliceBackend,
    resolveBranchHEAD: async () => {
      // #934 ID-015: optional branchHEAD — warn + omit on empty/failure (never "").
      if (opts.familyHead != null && opts.familyHead.trim().length > 0) {
        return opts.familyHead;
      }
      if (opts.familyBackend.readFamilyHead === undefined) return undefined;
      try {
        const head = await opts.familyBackend.readFamilyHead(opts.familyBase);
        if (head != null && head.trim().length > 0) return head;
        console.warn(
          "[orchestrator] optional family branchHEAD read returned empty (omit)",
        );
        return undefined;
      } catch (err) {
        console.warn(
          `[orchestrator] optional family branchHEAD read failed (omit): ${
            err instanceof Error ? err.message : String(err)
          }`,
        );
        return undefined;
      }
    },
    hashPrompt: async () => `family-quota-${opts.phase}`,
    worktreePath,
    currentModelId,
    currentPool,
    rosterOrder,
    pools,
    now: opts.now ?? new Date(),
    state_summary: `family ${opts.phase} quota wall on ${currentPool}; barrier continues on baton when live`,
  });

  if (outcome.kind === "park") {
    const stopSummary: StopSummary = outcome.result.stopSummary ?? {
      reason: "provider_degraded",
      summary: `quota wait for reset on pool ${opts.err.pool}`,
      repairHint:
        "wait for the provider quota to reset, then re-feed — family barrier re-enters from ledger truth",
    };
    // Durable family-ledger park boundary first; write failure fails closed
    // (same class as parkQuotaWaitForReset writeLedger — no resumable park).
    await opts.familyBackend.appendFamilyLedger({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: `quota_park:${opts.phase}`,
      reason: `quota wait for reset on pool ${opts.err.pool} at family ${opts.phase}`,
    });
    return buildParkResult(stopSummary);
  }

  // Relay: APPLY baton onto the REAL family consume slots + re-dispatch.
  // Identity / coder-only apply is hollow and must fail consumed-slot nails.
  // #934 ID-002 / R7 F2: single admit court ({@link admitRelayBaton}) — same
  // stop shape as single-slice (apply throw → typed stop; tight fail → stop).
  // Spec N1 / OUT #942: keep stopSummary.reason = infra_failure until public
  // ABI cutover; do not invent a parallel route_config_invalid token here.
  const admitted = admitRelayBaton(
    opts.modelRoute,
    outcome.nextBaton,
    wallStep,
    {
      slots: wallSlots,
      ...(opts.applyRelayBatonToRoute !== undefined
        ? { applyFn: opts.applyRelayBatonToRoute }
        : {}),
    },
  );
  if (admitted.kind === "stop") {
    const diagnosis = admitted.escalation.diagnosis;
    await opts.familyBackend.appendFamilyLedger({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: `quota_relay:${opts.phase}`,
      reason: `relay baton admission refused — refuse dispatch: ${diagnosis}`,
    });
    return buildParkResult(
      {
        reason: "infra_failure",
        summary: `${admitted.escalation.reason}: ${diagnosis}`,
        repairHint:
          "pick a baton/route preset that preserves tight-family invariants, then re-feed",
      },
      {
        reason: admitted.escalation.reason,
        diagnosis,
      },
    );
  }
  const appliedRoute = admitted.route;
  // Durable family-ledger relay boundary first; write failure fails closed.
  await opts.familyBackend.appendFamilyLedger({
    status: "worker_dispatched",
    event: "worker_dispatched",
    workerStep: `quota_relay:${opts.phase}`,
    reason: `quota wall relay applied ${outcome.ledgerEntry.fromPool}→${outcome.ledgerEntry.toPool} (${outcome.nextBaton.modelId}@${outcome.nextBaton.pool}) slots=[${wallSlots.join(",")}] at family ${opts.phase}`,
  });
  console.info(
    `[orchestrator:family] #909 relay baton → ${outcome.nextBaton.modelId} (${outcome.nextBaton.slug}) @ ${outcome.nextBaton.pool} (phase=${opts.phase}, slots=${wallSlots.join(",")})`,
  );
  return {
    kind: "relay",
    nextBaton: outcome.nextBaton,
    appliedRoute,
    wallSlots,
    relayBrief: outcome.relayBrief,
  };
}

/**
 * Run a family barrier under the shared quota park/relay machine. On relay,
 * re-dispatches the barrier with the applied baton route + a **slot-scoped**
 * baton billing pool (only wall roles rewritten by the baton). On park,
 * returns the structured FamilyRunResult for the caller to exit.
 *
 * No barrier-wide sticky pool: unrelated roles keep their natural provider
 * channel (DELETE pollution of ship/etc. after a cmr wall).
 */
async function runFamilyBarrierWithQuotaRelay<T>(opts: {
  readonly phase: FamilyQuotaWallPhase;
  readonly familyBackend: FamilyBackend;
  readonly singleSliceBackend: Backend;
  readonly familyBase: string;
  readonly familyHead: string | undefined;
  readonly runId: string;
  readonly modelRoute: ResolvedModelRoute;
  readonly recordedResults: ReadonlyArray<FamilyChildResult>;
  readonly epicChildren: ReadonlyArray<ChildSlice>;
  readonly epicIssue: number;
  readonly relayPools?: FamilyRunInput["relayPools"];
  readonly admissionSkipped?: FamilyRunResult["admissionSkipped"];
  readonly now?: () => Date;
  readonly run: (
    route: ResolvedModelRoute,
    relayBilling: FamilyRelayBillingBinding | undefined,
  ) => Promise<T>;
  /** Mutable handoff counter shared across barriers in one family run. */
  readonly relayHandoffs: { count: number };
  /** Correctness B3 — shared wall-hit set for the whole family run. */
  readonly wallHitBillingPools?: Set<BillingPoolId>;
  readonly applyRelayBatonToRoute?: ApplyRelayBatonToRouteFn;
  /**
   * C4 — run-scoped slot-scoped pool binding retained across barriers.
   * Seed so a baton pool from a prior barrier is not dropped on the next.
   */
  readonly initialRelayBilling?: FamilyRelayBillingBinding;
}): Promise<
  | {
      readonly kind: "ok";
      readonly value: T;
      readonly route: ResolvedModelRoute;
      readonly relayBilling: FamilyRelayBillingBinding | undefined;
    }
  | { readonly kind: "park"; readonly result: FamilyRunResult }
> {
  let route = opts.modelRoute;
  // Slot-scoped only — never a bare sticky pool that fans to all roles.
  // C4: retain prior barrier's slot bindings when re-entering a new barrier.
  let relayBilling: FamilyRelayBillingBinding | undefined =
    opts.initialRelayBilling;
  for (;;) {
    try {
      const value = await opts.run(route, relayBilling);
      return { kind: "ok", value, route, relayBilling };
    } catch (err) {
      if (!isQuotaWaitForResetError(err)) throw err;
      const decision = await decideFamilyQuotaWall({
        err,
        phase: opts.phase,
        familyBackend: opts.familyBackend,
        singleSliceBackend: opts.singleSliceBackend,
        familyBase: opts.familyBase,
        familyHead: opts.familyHead,
        runId: opts.runId,
        modelRoute: route,
        recordedResults: opts.recordedResults,
        epicChildren: opts.epicChildren,
        epicIssue: opts.epicIssue,
        ...(opts.relayPools !== undefined
          ? { relayPools: opts.relayPools }
          : {}),
        ...(opts.admissionSkipped !== undefined
          ? { admissionSkipped: opts.admissionSkipped }
          : {}),
        ...(opts.now !== undefined ? { now: opts.now() } : {}),
        ...(opts.applyRelayBatonToRoute !== undefined
          ? { applyRelayBatonToRoute: opts.applyRelayBatonToRoute }
          : {}),
        ...(opts.wallHitBillingPools !== undefined
          ? { wallHitBillingPools: opts.wallHitBillingPools }
          : {}),
        relayHandoffsSoFar: opts.relayHandoffs.count,
      });
      if (decision.kind === "park") return decision;
      // Apply + continue — baton pool binds ONLY to rewritten wall slots.
      route = decision.appliedRoute;
      relayBilling = {
        pool: decision.nextBaton.pool,
        slots: decision.wallSlots,
      };
      opts.relayHandoffs.count += 1;
    }
  }
}

function familyHeadMetadata(input: {
  readonly reportedFamilyHead?: string;
  readonly actualFamilyHead?: string;
  readonly actualFamilyHeadSource?: string;
  readonly verifiedCmrHead?: string;
}): StopSummary["metadata"] | undefined {
  const reportedFamilyHead = filled(input.reportedFamilyHead);
  const actualFamilyHead = filled(input.actualFamilyHead);
  const verifiedCmrHead = filled(input.verifiedCmrHead);
  if (
    reportedFamilyHead == null &&
    actualFamilyHead == null &&
    verifiedCmrHead == null
  ) {
    return undefined;
  }
  const sources: Record<string, string> = {};
  if (reportedFamilyHead != null) {
    sources.reportedFamilyHead = "FamilyRunResult.familyHead";
  }
  if (actualFamilyHead != null) {
    sources.actualFamilyHead =
      input.actualFamilyHeadSource ?? "family runner current head";
  }
  if (verifiedCmrHead != null) {
    sources.verifiedCmrHead = "latest cmr_passed ledger row";
  }
  return {
    heads: {
      ...(reportedFamilyHead != null ? { reportedFamilyHead } : {}),
      ...(actualFamilyHead != null ? { actualFamilyHead } : {}),
      ...(verifiedCmrHead != null ? { verifiedCmrHead } : {}),
      sources,
    },
  };
}

function familyStopSummary(input: {
  readonly status: FamilyRunStatus;
  readonly failedPhase?: VerifyCmrPhase;
  readonly familyHead?: string;
  readonly headMetadata?: StopSummary["metadata"];
  readonly barrierStopSummary?: StopSummary;
  readonly familyBase: string;
  readonly children: ReadonlyArray<FamilyChildResult>;
  readonly escalationReason?: string;
  /**
   * B-class (#604 F2, ADR 0062 A/B分家): a HUMAN DECISION GATE parked this run
   * awaiting an answer (a child's own single-slice decision题). When true the
   * `escalated`-status summary carries the `decision_gate_park` reason instead of
   * the A-class `infra_failure` word — a park is answerable + resumable, not a
   * failure to repair.
   */
  readonly decisionGatePark?: boolean;
  readonly admissionSkipped?: ReadonlyArray<{
    readonly issue: number;
    readonly reason: string;
    readonly message: string;
  }>;
  readonly alreadyDone?: ReadonlyArray<{
    readonly issue: number;
    readonly status: "merged" | "shipped" | "completed";
    readonly source: string;
  }>;
}): StopSummary {
  const metadata =
    input.headMetadata ??
    familyHeadMetadata({
      reportedFamilyHead: input.familyHead,
      actualFamilyHead: input.familyHead,
    });
  if (input.status === "success") {
    const hasMetadata =
      metadata?.heads != null ||
      (input.admissionSkipped?.length ?? 0) > 0 ||
      (input.alreadyDone?.length ?? 0) > 0;
    return successStopSummary(
      hasMetadata
        ? {
            ...(metadata?.heads != null ? { heads: metadata.heads } : {}),
            ...(input.admissionSkipped !== undefined && input.admissionSkipped.length > 0
              ? { admissionSkipped: input.admissionSkipped }
              : {}),
            ...(input.alreadyDone != null && input.alreadyDone.length > 0
              ? { alreadyDone: input.alreadyDone }
              : {}),
          }
        : undefined,
    );
  }
  // #922 — stage failure status and stopSummary.reason share the same token.
  if (isFamilyStageFailureStatus(input.status)) {
    const synced = syncStopSummaryToStageFailure(
      input.status,
      input.barrierStopSummary,
    );
    if (input.barrierStopSummary == null && input.failedPhase !== undefined) {
      return stageFailureStopSummary({
        status: input.status,
        summary: `family ${input.failedPhase} ${input.status.replace(/_failed$/, "")} barrier failed`,
        repairHint: synced.repairHint,
        ...(metadata?.heads != null ? { metadata: { heads: metadata.heads } } : {}),
      });
    }
    if (metadata?.heads != null && synced.metadata?.heads == null) {
      return {
        ...synced,
        metadata: { ...(synced.metadata ?? {}), heads: metadata.heads },
      };
    }
    return synced;
  }
  if (input.status === "incomplete") {
    const blocked = input.children
      .filter((child) => child.status !== "merged" && child.status !== "already_done")
      .map((child) => `#${child.issue}:${child.status}`)
      .join(", ");
    return {
      reason: "owning_issue_still_red",
      summary: `family run is incomplete; unmerged children: ${blocked}`,
      repairHint: "repair or complete the listed child slices and rerun the family",
    };
  }
  // B-class: a human decision gate parked the run (#604 F2). Answerable +
  // resumable — never the A-class `infra_failure` word.
  if (input.decisionGatePark === true) {
    return {
      reason: "decision_gate_park",
      summary: input.escalationReason ?? "family run parked on a decision gate",
      repairHint:
        "append an escalation_answered ledger row carrying the parked childIssue, then rerun the family to resume in place",
      ...(metadata !== undefined ? { metadata } : {}),
    };
  }
  return {
    reason: "infra_failure",
    summary: input.escalationReason ?? "family run escalated",
    repairHint: "inspect the family ledger escalation entry and repair before rerun",
    ...(metadata !== undefined ? { metadata } : {}),
  };
}

/**
 * Run a child slice through the reused single-slice runner in FAMILY MODE.
 *
 * Family context (ADR 0022 decision 2) is passed via RunInput.family so the
 * single-slice runner cuts from the family base + performs an S7 local handoff. The child is a
 * leaf (no sub-issues) so its own S0 gate passes unchanged; #293's wave is
 * all-unblocked children so the ledger口径 dependency check (dec.6③) is trivially
 * satisfied (empty blocked_by).
 */
/**
 * Read a child's PARKED decision escalation off its single-slice RunResult (#604
 * slice 5). The caller has already checked `result.status==="escalate"`. This
 * distinguishes the DECISION bucket (a well-shaped Escalation on the escalated
 * agent step → answerable, parkable) from the FAILURE bucket (an
 * infra/retries-exhausted escalate with no valid Escalation → returns undefined,
 * so the caller keeps the CURRENT `"failed"` behaviour — A/B分家). The reason /
 * diagnosis and sessionId come from the escalated agent step's in-memory ledger
 * entry; the durable child ledger independently retains the same resume truth.
 *
 * NOTE: `escalationKindForHandoff` in runner.ts (single-slice) mirrors this exact
 * decision-vs-failure split (a valid Escalation ⇒ "decision", else "failure"); this
 * is the family-layer read of the same truth off the lean RunResult ledger.
 *
 * #604 correctness r5 (E2): the in-memory RunResult ledger now carries the escalated
 * agent step's `sessionId` (the runner records it on the in-memory entry, not only
 * the persisted one), so the parked escalation FORWARDS the real child session id
 * for 原地 resume. It is absent only when the provider surfaced no id.
 */
function readChildDecisionEscalation(
  ledger: ReadonlyArray<LedgerEntry>,
): FamilyChildEscalation | undefined {
  // The escalated agent step carries the Escalation payload (the S8 handoff entry
  // in the lean RunResult ledger carries no handoffStatus/escalationKind — those
  // live only on the PERSISTED ledger written via writeLedger).
  const agentEntry = [...ledger]
    .reverse()
    .find((e) => {
      const esc = escalateOf(e.output);
      return esc != null && isValidEscalation(esc);
    });
  const escalation = escalateOf(agentEntry?.output);
  if (escalation == null || !isValidEscalation(escalation)) return undefined;
  if (isRunnerSynthesizedFailureEscalation(escalation)) return undefined;
  return {
    reason: escalation.reason,
    diagnosis: escalation.diagnosis,
    escalationKind: "decision",
    ...(agentEntry?.sessionId !== undefined ? { sessionId: agentEntry.sessionId } : {}),
  };
}

/**
 * The escalated (last non-terminal) step in a child's parked single-slice ledger
 * (#604 slice 5) — the `forStep` a family-level answer must target so the child's
 * own `planResume` reopens THAT step in its recorded session.
 */
function escalatedChildStep(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): StepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step !== "S8" && isStepId(entry.step)) return entry.step;
  }
  return undefined;
}

/**
 * #970 typed fail-closed reason: a TRUE child-bound decision answer was present
 * (ledger-proven park + answer) but the child's single-slice parked resume state
 * is missing. Must never be silent / generic — field #485 triple-fail swallowed
 * this path into `owning_issue_still_red` with no durable cause.
 */
export const CHILD_ANSWER_WITHOUT_PARKED_STATE =
  "child_answer_without_parked_state" as const;

/**
 * Fail closed when a true child decision answer cannot resume in place (#604 P1-b
 * + #970 loud reason). Writes a durable family-ledger audit row so the typed
 * reason survives re-entry diagnostics (not just in-memory failureCause).
 */
async function failClosedChildAnswerWithoutParkedState(
  familyBackend: FamilyBackend,
  childIssue: number,
): Promise<FamilyChildResult> {
  // Audit-only durable marker (worker_dispatched) — do NOT write phase `aborted`
  // / family `escalated` here: those would poison barrier terminal resolution or
  // next re-entry park state. The child outcome remains `"failed"` + failureCause.
  await familyBackend.appendFamilyLedger({
    childIssue,
    status: "worker_dispatched",
    event: "worker_dispatched",
    workerStep: "child_answer_resume",
    reason: CHILD_ANSWER_WITHOUT_PARKED_STATE,
  });
  return {
    issue: childIssue,
    status: "failed",
    failureCause: CHILD_ANSWER_WITHOUT_PARKED_STATE,
  };
}

async function runChild(
  child: ChildSlice,
  singleSliceBackend: Backend,
  parentIssue: number,
  familyBase: string,
  familyChildIssues: ReadonlySet<number>,
  familyBackend: FamilyBackend,
  /**
   * A family-ledger-proven answer to THIS child's parked decision escalation
   * (#604 slice 5 / #970). Only set when the ledger proves a decision-kind park
   * with sessionId for this child — family-level answers (or free-text mentions of
   * a child issue number) must NOT reach here. When present, it is INJECTED into
   * the child's own single-slice ledger (as an `escalation_answered` row targeting
   * the escalated step) BEFORE re-running `runOrchestrator`, so the child's
   * `planResume` reopens the paused step in its recorded session (原地 resume).
   * Absent ⇒ a normal fresh/continued child run.
   */
  escalationAnswer?: EscalationAnswerPayload,
): Promise<FamilyChildResult> {
  // ── #604 slice 5 resume: inject the answer into the child's single-slice ledger
  // so the reused runOrchestrator's planResume → resumeSession reopens the paused
  // step IN PLACE (原 sessionId), never from scratch. We only inject when the child
  // actually has parked residue (findResumeState returns a ledger) whose last
  // non-terminal step is the one to reopen.
  if (escalationAnswer !== undefined) {
    const resumeState = await singleSliceBackend.findResumeState(child.issue);
    const forStep =
      resumeState !== undefined ? escalatedChildStep(resumeState.ledger) : undefined;
    if (resumeState !== undefined && forStep !== undefined) {
      const parkedSessionId = [...resumeState.ledger]
        .reverse()
        .find((entry) => entry.step === forStep)?.sessionId;
      if (parkedSessionId === undefined) {
        // #970: loud typed fail-closed (was silent bare `"failed"`).
        return failClosedChildAnswerWithoutParkedState(familyBackend, child.issue);
      }
      const answerEntry: PersistentLedgerEntry = {
        step: forStep,
        // Keep the answer row in the same session lineage as the parked worker.
        // The durable child step is the fallback truth for legacy family answer
        // rows that predate sessionId forwarding.
        sessionId: escalationAnswer.sessionId ?? parkedSessionId,
        prompt_hash: "family-answer",
        branchHEAD: resumeState.worktree.branch,
        ts: new Date().toISOString(),
        event: "escalation_answered",
        forStep,
        answer: escalationAnswer.answer,
        source: "human",
        ...(escalationAnswer.note !== undefined ? { note: escalationAnswer.note } : {}),
      } as PersistentLedgerEntry;
      await singleSliceBackend.writeLedger(answerEntry, resumeState.stateDir);
    } else {
      // #604 correctness r1 (P1-b): a human answered THIS child's decision gate,
      // but its parked resume state is MISSING (findResumeState returned undefined,
      // or no re-openable non-terminal step exists). We MUST NOT fall through to a
      // fresh `runOrchestrator` (that would re-run the child FROM SCRATCH, losing
      // committed progress and violating 原地-resume / never-from-scratch, ADR 0062).
      // #970: fail-closed with loud typed reason + durable ledger row — never a
      // silent bare `"failed"` that collapses into owning_issue_still_red with no cause.
      return failClosedChildAnswerWithoutParkedState(familyBackend, child.issue);
    }
  }
  const result = await runOrchestrator({
    issueNumber: child.issue,
    backend: singleSliceBackend,
    // #294 (ADR 0022 decision 6③): hand the child its ledger-merged blockers so
    // its OWN single-slice S0 `blocked_by` gate uses the ledger-merged口径, not
    // GitHub `closed`. runChild only runs a child the commander released — selectWave
    // confirmed every INTRA-FAMILY `blocked_by` is in the merged set — so each such
    // blocker IS merged into the family base for this child. We pass ONLY the
    // intra-family subset (a `blocked_by` issue that is itself a family sibling):
    // those are the blockers the commander can possibly have ledger-merged. An
    // EXTERNAL `blocked_by` (not a family child) is never in the family ledger, so it
    // is NOT excused here — but it is also NOT relied upon at S0: family admission
    // (`filterExternalBlockedChildren`, #934 ID-002) visibly filters children with
    // open ordinary external blockers up front, and selectWave no longer gates on
    // external blockers. Passing only the intra-family subset keeps S0 from seeing
    // a non-family number it has no ledger evidence for; the live S0 fetch remains a
    // backstop should an external blocker RE-open mid-run. For an intra-family
    // blocker that IS ledger-merged, the child's S0 treats a still-open-on-GitHub
    // blocker as satisfied, so a just-released child is not re-rejected (agy R2).
    family: {
      parentIssue,
      familyBase,
      mergedBlockers: child.blockedBy.filter((b) => familyChildIssues.has(b)),
    },
  });
  if (result.status === "success" && result.branch !== undefined) {
    // The single-slice run succeeded and produced a reviewed branch — but it is
    // NOT merged yet (the spine's serial-merge step does that, then flips this to
    // "merged" once the merge commit lands — ADR 0022 decision 5). So runChild
    // returns the transient "ran", never a premature "merged".
    return { issue: child.issue, status: "ran", branch: result.branch };
  }
  // #604 slice 5 (A/B分家): a child that PARKED on a product/design DECISION题
  // (`escalationKind:"decision"`) is `"escalated"`, NOT `"failed"` — an answerable
  // pause the family can resume IN PLACE. Only the decision bucket parks; a
  // `"failure"` escalate (infra / retries exhausted) and every other non-success
  // outcome keep the current `"failed"` behaviour below.
  if (result.status === "escalate") {
    const escalation = readChildDecisionEscalation(result.stepLedger);
    if (escalation !== undefined) {
      return { issue: child.issue, status: "escalated", escalation };
    }
  }
  // #293 thinnest: a non-success child does not merge (a failure escalate / error
  // stays failed). The spine records it honestly, not silently dropped.
  return { issue: child.issue, status: "failed" };
}

/**
 * Read the current merged set from the family ledger (the commander's unblock
 * truth, ADR 0022 decision 6②). Re-read each wave so #294's dependency
 * scheduling sees the freshly-merged children.
 */
async function currentMerged(
  familyBackend: FamilyBackend,
): Promise<ReadonlySet<number>> {
  return mergedSet(await familyBackend.readFamilyLedger());
}

async function readCurrentFamilyHead(
  familyBackend: FamilyBackend,
  familyBase: string,
): Promise<string | undefined> {
  if (familyBackend.readFamilyHead === undefined) return undefined;
  try {
    const head = (await familyBackend.readFamilyHead(familyBase)).trim();
    return head.length > 0 ? head : undefined;
  } catch {
    return undefined;
  }
}

/**
 * #603 — already_done / resume success is allowed only when the head has a
 * terminal+ok `post_merge_cleanup` ledger row (or cleanup re-enters successfully).
 * Returns an escalated FamilyRunResult when cleanup cannot complete; undefined
 * means the caller may report already_done.
 */
async function requirePostMergeCleanupForAlreadyDone(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId: string;
  readonly familyHeadAfter: string;
  readonly prUrl: string;
  readonly familyIssue: number;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly children: ReadonlyArray<FamilyChildResult>;
  readonly admissionSkipped?: ReadonlyArray<{
    readonly issue: number;
    readonly reason: string;
    readonly message: string;
  }>;
}): Promise<FamilyRunResult | undefined> {
  const ledger = await input.familyBackend.readFamilyLedger();
  if (
    familyPostMergeCleanupForHead(ledger, input.familyHeadAfter) !== undefined
  ) {
    return undefined;
  }
  if (familyPrMergedForHead(ledger, input.familyHeadAfter) === undefined) {
    return undefined;
  }
  const cleanup = await ensureFamilyPostMergeCleanup({
    familyBackend: input.familyBackend,
    familyBase: input.familyBase,
    runId: input.runId,
    familyHeadAfter: input.familyHeadAfter,
    prUrl: input.prUrl,
    familyIssue: input.familyIssue,
    // #922: resume cleanup failure must leave the same durable stage name as fresh.
    recordAbortOnFailure: true,
  });
  if (cleanup.ok) return undefined;
  const reason =
    cleanup.reason ??
    "family post-merge cleanup did not reach a terminal success outcome";
  const stopSummary = stageFailureStopSummary({
    status: "cleanup_failed",
    summary: reason,
  });
  return {
    status: "cleanup_failed",
    familyBase: input.familyBase,
    familyHead: input.familyHeadAfter,
    failedPhase: "final",
    stopSummary,
    children: [...input.children],
    ...(input.admissionSkipped !== undefined && input.admissionSkipped.length > 0
      ? { admissionSkipped: input.admissionSkipped }
      : {}),
  };
}

function latestVerifiedCmrHead(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "cmr_passed" &&
      entry.event === "cmr_passed" &&
      entry.phase === "final" &&
      filled(entry.familyHeadAfter) !== undefined
    ) {
      return filled(entry.familyHeadAfter);
    }
  }
  return undefined;
}

export function pendingPriorCmrFindingIdentityKeysByPass(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  currentFamilyHead?: string,
): Partial<Record<IntegratedCmrPass, ReadonlyArray<string>>> {
  const keysByPass: Partial<Record<IntegratedCmrPass, string[]>> = {};
  const closedPasses = new Set<string>();
  const processedPasses = new Set<string>();
  // #604 correctness r1 (P1-e): passes marked processed ONLY by an empty
  // not_converged classified abort. An OLDER `cmr_fix_committed` for such a pass
  // still contributes its pending claimed-fixed keys (ADR 0030 closure); a pass in
  // `processedPasses` for any OTHER reason still blocks the fix-commit as before.
  const emptyAbortProcessedPasses = new Set<string>();
  const passesWithUnclosedFixCommits = new Set<string>();
  const unclassifiedAbortHeadByPass = new Map<string, string | undefined>();
  for (let index = ledger.length - 1; index >= 0; index--) {
    const entry = ledger[index]!;
    if (entry.status === "shipped") break;
    if (entry.status === "cmr_passed") {
      if (entry.cmrPass == null) break;
      closedPasses.add(entry.cmrPass);
      continue;
    }
    if (entry.status === "cmr_fix_committed") {
      const pass = entry.cmrPass;
      const keys = entry.blockingFindingIdentityKeys;
      // #604 correctness r1 (P1-e): a pass that is processed ONLY because of an
      // empty not_converged abort must NOT block this older fix-commit's pending
      // keys — they are still awaiting ADR 0030 closure. `processedPasses` for any
      // other reason (a real classified abort / cmr_reviewed) still blocks it.
      const blockedByProcessed =
        pass != null &&
        processedPasses.has(pass) &&
        !emptyAbortProcessedPasses.has(pass);
      if (
        pass == null ||
        closedPasses.has(pass) ||
        blockedByProcessed ||
        keys == null ||
        keys.length === 0
      ) {
        continue;
      }
      passesWithUnclosedFixCommits.add(pass);
      const existing = keysByPass[pass] ?? [];
      const seen = new Set(existing);
      const merged = [...existing];
      for (let keyIndex = keys.length - 1; keyIndex >= 0; keyIndex--) {
        const key = keys[keyIndex]!;
        if (seen.has(key)) continue;
        seen.add(key);
        merged.unshift(key);
      }
      keysByPass[pass] = merged;
      continue;
    }
    if (entry.status === "cmr_reviewed") {
      const pass = entry.cmrPass;
      const reviewedHead = filled(entry.familyHeadAfter);
      // #604 slice 3 / ADR 0062: the runner reads ONLY the thin envelope
      // (`blockingFindingIdentityKeys`) off a CMR row — never the finding content.
      const keys = entry.blockingFindingIdentityKeys;
      if (
        pass === undefined ||
        closedPasses.has(pass) ||
        processedPasses.has(pass)
      ) {
        continue;
      }
      if (passesWithUnclosedFixCommits.has(pass)) {
        continue;
      }
      const hasUnclassifiedAbort = unclassifiedAbortHeadByPass.has(pass);
      const abortHead = unclassifiedAbortHeadByPass.get(pass);
      if (
        hasUnclassifiedAbort &&
        (reviewedHead === undefined ||
          abortHead === undefined ||
          abortHead === reviewedHead)
      ) {
        continue;
      }
      processedPasses.add(pass);
      if (
        currentFamilyHead === undefined ||
        reviewedHead === undefined ||
        currentFamilyHead === reviewedHead ||
        keys == null ||
        keys.length === 0
      ) {
        continue;
      }
      keysByPass[pass] = [...keys];
      continue;
    }
    // #604 slice 3 / ADR 0062: an aborted row without a `blockingFindingIdentityKeys`
    // envelope is an UNCLASSIFIED abort (e.g. an infra failure) — it carries no CMR
    // blocking envelope. A not_converged abort carries `[]` (defined), so it stays
    // in the classified branch below and simply yields no keys.
    if (entry.status === "aborted" && entry.blockingFindingIdentityKeys == null) {
      const pass = entry.cmrPass;
      if (
        pass == null ||
        closedPasses.has(pass) ||
        processedPasses.has(pass)
      ) {
        continue;
      }
      if (!unclassifiedAbortHeadByPass.has(pass)) {
        unclassifiedAbortHeadByPass.set(pass, filled(entry.familyHeadAfter));
      }
      continue;
    }
    if (entry.status !== "aborted" || entry.blockingFindingIdentityKeys == null) {
      continue;
    }
    if (
      entry.cmrPass != null &&
      (closedPasses.has(entry.cmrPass) ||
        processedPasses.has(entry.cmrPass) ||
        unclassifiedAbortHeadByPass.has(entry.cmrPass))
    ) {
      continue;
    }
    const pass = entry.cmrPass;
    if (pass == null) continue;
    if (passesWithUnclosedFixCommits.has(pass)) {
      continue;
    }
    // #604 correctness r1 (P1-e): a not_converged sentinel abort carries an EMPTY
    // classified envelope (`blockingFindingIdentityKeys: []`). It yields no keys of
    // its own. It still marks the pass processed (its short-circuit semantics — an
    // older `cmr_reviewed` must NOT be revived as stale evidence past a
    // not_converged abort), but it is tracked as an EMPTY-ABORT processed pass so
    // it does NOT MASK an OLDER `cmr_fix_committed` row scanned later in this
    // newest-first loop. Those claimed-fixed keys are still pending ADR 0030
    // closure and must survive an empty not_converged abort — otherwise the next
    // fresh reviewer would no longer be told to cover them (silent DROP).
    if (entry.blockingFindingIdentityKeys.length === 0) {
      processedPasses.add(pass);
      emptyAbortProcessedPasses.add(pass);
      continue;
    }
    processedPasses.add(pass);
    const keys = keysByPass[pass] ?? [];
    const seen = new Set(keys);
    // #604 slice 2/3 / ADR 0062: pull EVERY blocking finding's identity key straight
    // off the thin envelope — no content classification is read.
    for (const identityKey of entry.blockingFindingIdentityKeys) {
      if (!seen.has(identityKey)) {
        seen.add(identityKey);
        keys.push(identityKey);
      }
    }
    keysByPass[pass] = keys;
  }
  return Object.fromEntries(
    Object.entries(keysByPass).map(([pass, values]) => [pass, values]),
  ) as Partial<Record<IntegratedCmrPass, ReadonlyArray<string>>>;
}

function latestAbortedStopSummary(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  phase: VerifyCmrPhase | undefined,
  minIndex = 0,
): StopSummary | undefined {
  for (let i = ledger.length - 1; i >= minIndex; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "aborted" &&
      (phase === undefined || entry.phase === phase) &&
      entry.stopSummary != null
    ) {
      return entry.stopSummary;
    }
  }
  return undefined;
}

function isMaterialCmrStopSummary(stopSummary: StopSummary): boolean {
  if (stopSummary.reason !== "success") return true;
  const metadata = stopSummary.metadata;
  return (
    (metadata?.acceptedSuppressions?.length ?? 0) > 0 ||
    (metadata?.providerDegraded?.length ?? 0) > 0
  );
}

function latestSuccessfulFinalCmrStopSummary(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  minIndex = 0,
): StopSummary | undefined {
  for (let i = ledger.length - 1; i >= minIndex; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "cmr_passed" &&
      entry.event === "cmr_passed" &&
      entry.phase === "final" &&
      entry.stopSummary != null &&
      isMaterialCmrStopSummary(entry.stopSummary)
    ) {
      return entry.stopSummary;
    }
  }
  return undefined;
}

function latestSuccessfulFinalShippedStopSummary(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  minIndex = 0,
): StopSummary | undefined {
  for (let i = ledger.length - 1; i >= minIndex; i--) {
    const entry = ledger[i]!;
    if (
      entry.status === "shipped" &&
      entry.event === "shipped" &&
      entry.phase === "final" &&
      entry.stopSummary != null &&
      isMaterialCmrStopSummary(entry.stopSummary)
    ) {
      return entry.stopSummary;
    }
  }
  return undefined;
}

/**
 * Derive the child issue numbers whose merge into the family base was LLM-resolved
 * (#291 缺口 1), read from the DURABLE family ledger — the only truth that survives
 * a context compaction. The spine hands this to the final-phase integrated cmr 承重闸
 * so it can focus its cross-slice review on the merges a machine touched
 * ("不静默吞"). Reads `conflictResolvedByLlm===true` `merged` entries; a clean merge
 * / reconcile補账条 / aborted event is excluded. In ledger write order, deduped.
 */
async function llmResolvedChildren(
  familyBackend: FamilyBackend,
): Promise<readonly number[]> {
  const ledger = await familyBackend.readFamilyLedger();
  const seen = new Set<number>();
  const out: number[] = [];
  for (const e of ledger) {
    if (
      isMergedAccountingEntry(e) &&
      e.conflictResolvedByLlm === true &&
      !seen.has(e.childIssue)
    ) {
      seen.add(e.childIssue);
      out.push(e.childIssue);
    }
  }
  return out;
}

/**
 * The family spine entry point (#293).
 *
 * @returns the family base branch + its HEAD after all merges + per-child
 *   outcomes. Acceptance 1: N independent ready children → one wave → serially
 *   merged into the family base.
 */
export async function runFamily(
  input: FamilyRunInput,
): Promise<FamilyRunResult> {
  const { familyBackend, singleSliceBackend, familyBase } = input;
  // A durable family sidecar is shared across restarts, so it needs an
  // invocation-scoped identity just like the single-slice runner.
  const runId = mintRunId();
  // #936 / #934 ID-002: Admission/Preflight — preset route + fail-closed tight.
  // No env slot overrides, no interactive continue.
  const admitted = input.admittedRoute === undefined
    ? admitRouteFromEnv()
    : { kind: "ready" as const, route: input.admittedRoute.route };
  if (admitted.kind === "stop") {
    const children = input.epic.children.map((child) => ({
      issue: child.issue,
      status: "skipped" as const,
    }));
    const diagnosis = admissionRouteFailureDiagnosis(admitted.escalation.diagnosis);
    return {
      status: "escalated",
      familyBase: input.familyBase,
      escalation: {
        reason: admitted.escalation.reason,
        diagnosis,
      },
      stopSummary: infraFailureStopSummary({
        summary: `${admitted.escalation.reason}: ${diagnosis}`,
        repairHint:
          "repair ORCHESTRATOR_ROUTE preset or issue Coder-Rec staffing before rerun",
      }),
      children,
      ...(input.epic.admissionSkipped !== undefined &&
      input.epic.admissionSkipped.length > 0
        ? { admissionSkipped: input.epic.admissionSkipped }
        : {}),
    };
  }
  let modelRoute: ResolvedModelRoute = admitted.route;
  if (input.admittedRoute === undefined && typeof singleSliceBackend.smokeModelRoute !== "function") {
    const reason =
      "route smoke executor is required before family dispatch; backend did not provide smokeModelRoute";
    const children = input.epic.children.map((child) => ({
      issue: child.issue,
      status: "skipped" as const,
    }));
    return {
      status: "escalated",
      familyBase,
      escalation: { reason: "startup route smoke failure", diagnosis: reason },
      stopSummary: infraFailureStopSummary({
        summary: reason,
        repairHint: "provide a real model×pipe smoke executor before dispatching family workers",
      }),
      children,
    };
  }
  let currentCliVersions: Readonly<Record<string, string | undefined>> = {};
  try {
    if (input.admittedRoute !== undefined) {
      currentCliVersions = singleSliceBackend.currentCliVersions
        ? await singleSliceBackend.currentCliVersions(modelRoute)
        : {};
    } else {
      logDriverStage("smoke-k", `route=${modelRoute.routeName}`);
      currentCliVersions = singleSliceBackend.currentCliVersions
        ? await singleSliceBackend.currentCliVersions(modelRoute)
        : {};
      modelRoute = await singleSliceBackend.smokeModelRoute(
        modelRoute,
        currentCliVersions,
      );
    }
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    const children = input.epic.children.map((child) => ({
      issue: child.issue,
      status: "skipped" as const,
    }));
    return {
      status: "escalated",
      familyBase,
      escalation: { reason: "startup route smoke failure", diagnosis: `route smoke failed: ${reason}` },
      stopSummary: infraFailureStopSummary({
        summary: `route smoke failed: ${reason}`,
        repairHint: "repair the selected model×pipe tool smoke before dispatching family workers",
      }),
      children,
    };
  }
  const degradation = input.admittedRoute ?? degradeOptionalRouteSmokeFailures(modelRoute);
  modelRoute = degradation.route;
  const smokeFailure = routeSmokeFailure(modelRoute, Date.now(), undefined, currentCliVersions);
  if (smokeFailure !== undefined) {
    const children = input.epic.children.map((child) => ({
      issue: child.issue,
      status: "skipped" as const,
    }));
    return {
      status: "escalated",
      familyBase,
      escalation: { reason: "startup route smoke failure", diagnosis: smokeFailure },
      stopSummary: infraFailureStopSummary({
        summary: smokeFailure,
        repairHint: "rerun the route smoke or repair the selected model×pipe",
      }),
      children,
    };
  }
  const routeLedger = degradation.dropped.length > 0
    ? await familyBackend.readFamilyLedger()
    : [];
  for (const dropped of degradation.dropped) {
    console.error(
      `[orchestrator:family] OPTIONAL CMR LEG DROPPED: ${dropped.slug}: ${dropped.reason}`,
    );
    const alreadyRecorded = routeLedger.some((entry) =>
      entry.status === "route_degraded" &&
      entry.event === "route_degraded" &&
      entry.droppedLeg === dropped.slug &&
      entry.reason === dropped.reason
    );
    if (alreadyRecorded) continue;
    await familyBackend.appendFamilyLedger({
      status: "route_degraded",
      event: "route_degraded",
      droppedLeg: dropped.slug,
      reason: dropped.reason,
      ts: new Date().toISOString(),
    });
  }
  // Mutable route — #909 relay apply mutates real consume slots (cmr, ship, …)
  // and re-dispatches with baton model + **slot-scoped** billing pool only.
  // No barrier-wide sticky pool (F2: unrelated roles keep natural channel).
  let activeRoute: ResolvedModelRoute = modelRoute;
  // C4: slot-scoped baton pool retained across barriers (not barrier-local only).
  let runRelayBilling: FamilyRelayBillingBinding | undefined;
  const relayHandoffs = { count: 0 };
  /** Correctness B3 — pools that already walled this family run (no live re-offer). */
  const wallHitBillingPools = new Set<BillingPoolId>();
  const applyRelayOverride = input.applyRelayBatonToRoute;
  console.info(
    `[orchestrator:family] model route lineup\n${printableRouteLineup(activeRoute)}`,
  );
  let initialFamilyLedger = await familyBackend.readFamilyLedger();
  for (const skipped of input.epic.admissionSkipped ?? []) {
    const alreadyRecorded = initialFamilyLedger.some(
      (entry) =>
        entry.status === "admission_skipped" &&
        entry.event === "admission_skipped" &&
        entry.childIssue === skipped.issue &&
        entry.reason === skipped.reason,
    );
    if (!alreadyRecorded) {
      await recordAdmissionSkipped(familyBackend, skipped);
    }
  }
  if ((input.epic.admissionSkipped?.length ?? 0) > 0) {
    initialFamilyLedger = await familyBackend.readFamilyLedger();
  }
  const priorEscalation = familyEscalationState(initialFamilyLedger);
  if (priorEscalation !== undefined) {
    const { escalation, answer } = priorEscalation;
    if (escalation.escalationKind !== "decision" || answer === undefined) {
      const ledgerMerged = mergedSet(initialFamilyLedger);
      return {
        status: "escalated",
        familyBase,
        ...(typeof escalation.familyHeadAfter === "string" &&
        escalation.familyHeadAfter.trim().length > 0
          ? { familyHead: escalation.familyHeadAfter }
          : {}),
        escalation: {
          reason:
            typeof escalation.reason === "string" && escalation.reason.trim().length > 0
              ? escalation.reason
              : "family escalation is not answered",
          diagnosis:
            escalation.escalationKind === "failure"
              ? "Prior family escalation was classified as failure; append-only answers do not reopen it."
              : escalation.escalationKind !== "decision"
                ? "Prior family escalation kind is missing or invalid; append-only answers only reopen decision escalations."
              : "Prior family decision escalation has no later valid escalation_answered ledger event.",
        },
        stopSummary: familyStopSummary({
          status: "escalated",
          familyBase,
          familyHead:
            typeof escalation.familyHeadAfter === "string" &&
            escalation.familyHeadAfter.trim().length > 0
              ? escalation.familyHeadAfter
              : undefined,
          children: input.epic.children.map((child) => ({
            issue: child.issue,
            status: ledgerMerged.has(child.issue) ? "already_done" : "skipped",
          })),
          escalationReason:
            typeof escalation.reason === "string" && escalation.reason.trim().length > 0
              ? escalation.reason
              : "family escalation is not answered",
          // #604 F2 / ADR 0062 A/B分家 (PR#643 R2): an UNANSWERED family-level
          // DECISION escalation is an answerable park, not an A-class repair
          // failure — carry `decision_gate_park`, mirroring the child-park path
          // (F8). A `failure`/missing-kind escalation stays `infra_failure`.
          decisionGatePark: escalation.escalationKind === "decision",
        }),
        children: input.epic.children.map((child) => ({
          issue: child.issue,
          status: ledgerMerged.has(child.issue) ? "already_done" : "skipped",
        })),
      };
    }
  }
  const escalationAnswer = priorEscalation?.answer;
  // ── #298 escalate-resume dependency-graph rebuild (ADR 0022 decision 4) ─────
  // APPEND-ONLY resume entry: when a `refetchEpic` hook is injected (a re-entry
  // after escalation — cmr non-convergence / a cycle a human edited in GitHub),
  // REBUILD the dependency graph from LIVE GitHub metadata, NOT the cached epic
  // (decision 4 不信缓存; else a stale cycle re-escalates, agy R2). Absent ⇒ the
  // passed `epic` is used unchanged (a fresh run). The commander then schedules
  // off the live graph below.
  const epic =
    input.refetchEpic !== undefined ? await input.refetchEpic() : input.epic;
  // ID-009: no startup whole-family cycle guard (residual probe is at empty-wave).
  const familyChildIssues = new Set(epic.children.map((c) => c.issue));
  // ── #604 slice 5: child decision-escalation re-entry ────────────────────────
  // Read the family ledger for children PARKED on a decision题 (a `child_decision_parked`
  // row). For each, look up whether a later `escalation_answered` row (bound to the
  // SAME childIssue) reopened it:
  //   - ANSWERED → the answer is fed into runChild, which injects it into the
  //     child's single-slice ledger so its own planResume → resumeSession reopens
  //     the paused step IN PLACE (原 sessionId, 退出-重入 per ADR 0062).
  //   - UNANSWERED → the family stays PAUSED: return `status:"escalated"` before the
  //     wave loop rather than fruitlessly re-running the parked child (which would
  //     just re-escalate). Supports multiple children parked + answered separately.
  const parkedChildAnswers = new Map<number, EscalationAnswerPayload>();
  {
    // #970 type-split: inject into runChild ONLY when the ledger proves a
    // decision-kind park (child_decision_parked + escalationKind=decision +
    // non-empty parked sessionId) AND a later matching child-bound answer.
    // Family-level answers (no childIssue), free-text mentions of a child issue
    // number, or park rows without sessionId are NOT child decision resumes —
    // they must not enter parkedChildAnswers (noop for runChild).
    // `unansweredChildEscalations` returns ONLY the still-unanswered parked
    // children. To also resume the ANSWERED ones we look up each parked child's
    // answer directly: answered → feed it into runChild (resume in place);
    // unanswered → keep the family paused (return escalated).
    const parkedIssues = new Set<number>();
    for (const entry of initialFamilyLedger) {
      if (
        entry.status === "child_decision_parked" &&
        entry.event === "child_decision_parked" &&
        entry.escalationKind === "decision" &&
        typeof entry.childIssue === "number"
      ) {
        parkedIssues.add(entry.childIssue);
      }
    }
    const unanswered: (FamilyLedgerEntry & { readonly childIssue: number })[] = [];
    const stillUnanswered = new Set(
      unansweredChildEscalations(initialFamilyLedger).map((e) => e.childIssue),
    );
    for (const childIssue of parkedIssues) {
      const parkRow = [...initialFamilyLedger]
        .reverse()
        .find(
          (e) =>
            e.status === "child_decision_parked" &&
            e.event === "child_decision_parked" &&
            e.escalationKind === "decision" &&
            e.childIssue === childIssue,
        ) as (FamilyLedgerEntry & { readonly childIssue: number }) | undefined;
      if (stillUnanswered.has(childIssue)) {
        if (parkRow !== undefined) unanswered.push(parkRow);
        continue;
      }
      // Injection requires a parked sessionId on the durable park row (#970).
      // Without it the bind is not a proven child decision resume — leave the
      // answer consumed at family ledger level and run the child fresh/normal.
      const parkedSessionId =
        typeof parkRow?.sessionId === "string" ? parkRow.sessionId.trim() : "";
      if (parkedSessionId.length === 0) continue;
      const answer = childEscalationAnswer(initialFamilyLedger, childIssue);
      if (answer !== undefined) parkedChildAnswers.set(childIssue, answer);
    }
    if (unanswered.length > 0) {
      const ledgerMerged = mergedSet(initialFamilyLedger);
      const first = unanswered[0]!;
      // #604 F8: an UNANSWERED parked child re-entered before the wave loop must
      // map to `"escalated"` (its decision-gate park state), NOT `"skipped"`. The
      // wave-loop parking path finalizes these via `finalizeDecisionPark` →
      // `"escalated"`; the early-exit re-entry path must stay consistent, else the
      // driver sees the parked child as skipped and mis-reads the run. Carry the
      // escalation payload read from the `child_decision_parked` ledger row so the
      // driver has the same reason/diagnosis/sessionId either path.
      const parkedByIssue = new Map<number, FamilyChildEscalation>();
      for (const row of unanswered) {
        parkedByIssue.set(row.childIssue, {
          reason: row.reason ?? "(no reason recorded)",
          diagnosis:
            row.diagnosis ??
            "Append an escalation_answered ledger row carrying this childIssue to reopen the parked child.",
          escalationKind: "decision",
          ...(typeof row.sessionId === "string" && row.sessionId.length > 0
            ? { sessionId: row.sessionId }
            : {}),
        });
      }
      const children: FamilyChildResult[] = epic.children.map((c) => {
        if (ledgerMerged.has(c.issue)) {
          return { issue: c.issue, status: "already_done" as const };
        }
        const escalation = parkedByIssue.get(c.issue);
        if (escalation !== undefined) {
          return { issue: c.issue, status: "escalated" as const, escalation };
        }
        return { issue: c.issue, status: "skipped" as const };
      });
      const escalationReason = `child #${first.childIssue} decision gate is not answered: ${first.reason ?? "(no reason recorded)"}`;
      return {
        status: "escalated",
        familyBase,
        ...(typeof first.familyHeadAfter === "string" && first.familyHeadAfter.trim().length > 0
          ? { familyHead: first.familyHeadAfter }
          : {}),
        escalation: {
          reason: escalationReason,
          diagnosis:
            first.diagnosis ??
            "Append an escalation_answered ledger row carrying this childIssue to reopen the parked child.",
        },
        stopSummary: familyStopSummary({
          status: "escalated",
          familyBase,
          ...(typeof first.familyHeadAfter === "string" && first.familyHeadAfter.trim().length > 0
            ? { familyHead: first.familyHeadAfter }
            : {}),
          children,
          escalationReason,
          decisionGatePark: true,
        }),
        children,
      };
    }
  }
  const moduleContext = buildFamilyModuleContext({
    childModules: epic.children.map((child) => child.moduleDeclaration),
    familyModule: epic.moduleDeclaration,
    runOptionModule: input.moduleDeclaration,
    undevelopedModules: input.undevelopedModules,
    acceptedSuppressionSources: input.acceptedSuppressionSources,
  });
  const declaredModuleContext =
    moduleContext.currentModules.length > 0 ||
    moduleContext.childModules.length > 0 ||
    (moduleContext.undevelopedModules?.length ?? 0) > 0 ||
    (moduleContext.acceptedSuppressionSources?.length ?? 0) > 0
      ? moduleContext
      : undefined;
  // The verify-cmr hook: production default is the real {@link runVerifyCmr};
  // tests may inject a stub. Spine call sites + fail-fast on `ok===false` are
  // identical either way (ADR 0022 decision 3④/⑤/⑥; acceptance-4 seam boundary).
  const verifyCmr = input.verifyCmr ?? runVerifyCmr;
  const childResults: FamilyChildResult[] = [];
  /** Wave-aggregated sibling root causes (#938 / ID-009). */
  const waveDiagnostics: FamilyChildDiagnostic[] = [];
  let familyHead: string | undefined;

  const attachDiagnostics = <T extends FamilyRunResult>(result: T): T => {
    if (waveDiagnostics.length === 0) return result;
    return { ...result, diagnostics: [...waveDiagnostics] };
  };

  // Build the family result, accounting for EVERY epic child, and deriving an
  // HONEST family status (decision 3⑤ "不静默吞" — the result must not silently
  // look like success):
  //
  //   - every epic child gets a record. A child not run this invocation is
  //     LEDGER-AWARE: if it has a `merged` ledger entry (e.g. merged in a prior
  //     invocation — #298's resume truth), it is `"already_done"` (per the
  //     FamilyChildStatus contract: "merged" ⇔ merged this invocation;
  //     "already_done" ⇔ an earlier run's ledger truth), NOT `"skipped"`. Only a
  //     child absent from BOTH this run's results AND the
  //     merged ledger (a blocker never merged / a fail-fast wave aborted before
  //     it ran) is `"skipped"`.
  //   - `status` is a stage-named failure (#922) when a barrier was red
  //     (most urgent among non-escalated outcomes). Otherwise the run is
  //     `"success"` iff EVERY child is merged, else `"incomplete"`.
  //
  // Happy path (all independent children merge, every barrier green) is always
  // `"success"`; incomplete / stage-failure / ledger-merged branches guard
  // honesty for the failure + #294/#298 / #922 paths.
  const finalize = async (
    opts?: {
      readonly failedStatus?: FamilyStageFailureStatus;
      readonly failedPhase?: VerifyCmrPhase;
      readonly barrierLedgerStartIndex?: number;
    },
  ): Promise<FamilyRunResult> => {
    const verifyFailedPhase = opts?.failedPhase;
    const barrierLedgerStartIndex = opts?.barrierLedgerStartIndex ?? 0;
    const recorded = new Set(childResults.map((c) => c.issue));
    const ledgerMerged = await currentMerged(familyBackend);
    const familyLedger = await familyBackend.readFamilyLedger();
    const extra: FamilyChildResult[] = epic.children
      .filter((c) => !recorded.has(c.issue))
      .map((c) =>
        ledgerMerged.has(c.issue)
          ? { issue: c.issue, status: "already_done" as const }
          : { issue: c.issue, status: "skipped" as const },
      );
    const children = [...childResults, ...extra];
    const barrierStopSummary =
      opts?.failedStatus !== undefined || verifyFailedPhase !== undefined
        ? (latestAbortedStopSummary(
            familyLedger,
            verifyFailedPhase,
            barrierLedgerStartIndex,
          ) ??
          latestAbortedStopSummary(familyLedger, undefined, barrierLedgerStartIndex))
        : undefined;
    const terminal =
      opts?.failedStatus !== undefined ||
      verifyFailedPhase !== undefined ||
      barrierStopSummary != null
        ? resolveFamilyStageTerminal({
            ...(opts?.failedStatus !== undefined
              ? { failedStatus: opts.failedStatus }
              : {}),
            ...(barrierStopSummary !== undefined
              ? { barrierStopSummary }
              : {}),
            defaultStatus: "verify_failed",
          })
        : undefined;
    const status: FamilyRunStatus =
      terminal?.kind === "escalated"
        ? "escalated"
        : terminal?.kind === "stage"
          ? terminal.status
          : children.every((c) => c.status === "merged" || c.status === "already_done")
            ? "success"
            : "incomplete";
    const actualFamilyHead = await readCurrentFamilyHead(familyBackend, familyBase);
    const headMetadata = familyHeadMetadata({
      reportedFamilyHead: familyHead,
      actualFamilyHead: actualFamilyHead ?? familyHead,
      actualFamilyHeadSource:
        actualFamilyHead !== undefined
          ? "familyBackend.readFamilyHead"
          : "family runner current head",
      verifiedCmrHead: latestVerifiedCmrHead(familyLedger),
    });
    const alreadyDone = extra
      .filter((child) => child.status === "already_done")
      .map((child) => ({
        issue: child.issue,
        status: "merged" as const,
        source: "family child already_done result",
      }));
    const allChildrenAlreadyDone =
      status === "success" &&
      childResults.length === 0 &&
      children.length > 0 &&
      alreadyDone.length === children.length;
    const computedStopSummary =
      terminal?.kind === "escalated"
        ? terminal.stopSummary
        : familyStopSummary({
            status,
            failedPhase: verifyFailedPhase,
            familyBase,
            familyHead,
            headMetadata,
            barrierStopSummary,
            children,
            admissionSkipped: epic.admissionSkipped,
            alreadyDone,
          });
    const materialSuccessStopSummary =
      status === "success"
        ? (latestSuccessfulFinalShippedStopSummary(
            familyLedger,
            barrierLedgerStartIndex,
          ) ??
          latestSuccessfulFinalCmrStopSummary(familyLedger, barrierLedgerStartIndex))
        : undefined;
    const resultStopSummary =
      materialSuccessStopSummary !== undefined
        ? {
            ...materialSuccessStopSummary,
            metadata: {
              ...(materialSuccessStopSummary.metadata ?? {}),
              ...(computedStopSummary.metadata ?? {}),
            },
          }
        : computedStopSummary;
    return attachDiagnostics({
      status,
      ...(verifyFailedPhase !== undefined ? { failedPhase: verifyFailedPhase } : {}),
      familyBase,
      familyHead,
      stopSummary: allChildrenAlreadyDone
        ? {
            ...resultStopSummary,
            reason: "already_done",
            summary: "family resume found every child already merged and skipped rerun",
          }
        : resultStopSummary,
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    });
  };

  // #604 slice 5: build the family result when a CHILD decision escalation parked
  // the run. Every epic child gets a record (the parked child carries its
  // `escalation`; already-merged children in `recorded` keep their status; the rest
  // are `"skipped"`). The family status is `"escalated"` (the answerable pause), NOT
  // verify_failed / incomplete.
  const finalizeDecisionPark = async (
    parked: FamilyChildResult & { escalation: FamilyChildEscalation },
    recordedResults: ReadonlyArray<FamilyChildResult>,
  ): Promise<FamilyRunResult> => {
    const recorded = new Map(recordedResults.map((c) => [c.issue, c]));
    // LEDGER-AWARE (不静默吞, runner.ts ~958-968): a child MERGED in a prior
    // invocation is skipped by `selectWave`, so it is absent from this run's
    // `recordedResults`. It must report "already_done": the durable ledger truth
    // is present, but this invocation did not merge it. It must not be "skipped"
    // — mirroring the early-exit park path (~900) and finalize().
    const ledgerMerged = await currentMerged(familyBackend);
    const children: FamilyChildResult[] = epic.children.map((c) => {
      const rec = recorded.get(c.issue);
      if (rec !== undefined) return rec;
      if (ledgerMerged.has(c.issue)) return { issue: c.issue, status: "already_done" as const };
      return { issue: c.issue, status: "skipped" as const };
    });
    const escalationReason = `child #${parked.issue} escalated a decision: ${parked.escalation.reason}`;
    return {
      status: "escalated",
      familyBase,
      familyHead,
      escalation: {
        reason: escalationReason,
        diagnosis: parked.escalation.diagnosis,
      },
      stopSummary: familyStopSummary({
        status: "escalated",
        familyBase,
        familyHead,
        children,
        escalationReason,
        decisionGatePark: true,
      }),
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    };
  };

  // ── #298 crash-window reconcile (the RESUME ENTRY, ADR 0022 decision 5) ─────
  // APPEND-ONLY into the spine: this runs BEFORE the wave loop and does NOT touch
  // its structure. When a `reconcileGit` seam is injected (a resume), compare the
  // ledger末条 head to the live family-base HEAD and:
  //   - branch ② (live HEAD leads — a merge landed but its `merged` write
  //     crashed): APPEND a reconcile補账条 (`status:"merged"` + `event:"reconciled"`)
  //     for each ancestor-confirmed child, so `currentMerged` (re-read each wave)
  //     skips it (no double-merge); a never-merged child (childHead absent / not an
  //     ancestor) is left OUT and the existing wave loop re-runs it (no漏合);
  //   - branch ③ (inconsistent live HEAD): bail fail-closed to `status:"escalated"`
  //     BEFORE any merge (decision 5 真有未落/不一致 → 升级; decision 4 escalate).
  // Absent ⇒ a fresh run, the #293 behaviour unchanged. The reconcile LOGIC lives
  // in reconcile.ts; the spine only CALLS it + appends its补账条 (acceptance-4
  // seam boundary — the spine never carries the reconcile algorithm).
  if (input.reconcileGit !== undefined) {
    // #884: log reconcile at the true entry, after smoke-k and before ledger work.
    logDriverStage("reconcile", `family base ${input.familyBase}`);
    const ledger = await familyBackend.readFamilyLedger();
    const plan = await reconcileFamilyLedger(
      ledger,
      epic.children,
      input.reconcileGit,
    );
    if (plan.escalate) {
      // Fail-closed (decision 5 branch ③): do not proceed to the wave loop. The
      // family base + ledger are left for human triage (decision 3⑤ 不静默吞);
      // the run is observably `escalated`, NOT a fabricated success.
      const children: FamilyChildResult[] = epic.children.map((c) =>
        plan.merged.has(c.issue)
          ? { issue: c.issue, status: "already_done" as const }
          : { issue: c.issue, status: "skipped" as const },
      );
      await recordFamilyEscalated(familyBackend, {
        escalationKind: "failure",
        phase: "final",
        reason: "family reconcile found the live family-base HEAD inconsistent with the ledger",
        familyHeadAfter: plan.liveHead,
      });
      return {
        status: "escalated",
        familyBase,
        familyHead,
        stopSummary: familyStopSummary({
          status: "escalated",
          familyBase,
          familyHead,
          children,
          escalationReason:
            "family reconcile found the live family-base HEAD inconsistent with the ledger",
        }),
        children,
      };
    }
    // Append each reconcile補账条 (status:"merged" + event:"reconciled") through
    // the ledger seam so the wave loop's `currentMerged` counts it (codex R3) and
    // never re-merges the already-landed child.
    //
    // Baseline-advance only on the LAST補账条 (cmr R2: agy). The append loop is
    // itself a crash window: if EVERY補账条 stamped `familyHeadAfter: plan.liveHead`
    // and the process died after writing補账条 i but before i+1, the next resume's
    // `lastRecordedHead` would return liveHead (from补账条 i) → reconcile branch ①
    // (baseline === liveHead) → it would TRUST the incomplete merged set and the
    // un-appended landed children (i+1 …) would be re-run + re-merged (a
    // double-merge). By stamping `familyHeadAfter` ONLY on the final補账条, a
    // mid-loop-crash residue ends in a补账条 WITHOUT a head → `lastRecordedHead`
    // falls back to the PRIOR real baseline → live still LEADS it → branch ②
    // re-reconciles the remaining landed children idempotently (the already-written
    // ones are `status:"merged"` → skipped, the missing ones re-补账ed), no
    // double-merge. The final補账条 advances the baseline to the verified live HEAD
    // so a clean (non-crashed) resume's `lastRecordedHead` is correct (cmr R1).
    const lastReconciledIdx = plan.reconciled.length - 1;
    for (let i = 0; i < plan.reconciled.length; i++) {
      const r = plan.reconciled[i]!;
      await recordMerged(familyBackend, {
        childIssue: r.childIssue,
        childHead: r.childHead,
        ...(i === lastReconciledIdx
          ? { familyHeadAfter: plan.liveHead }
          : {}),
        event: "reconciled",
      });
    }
    // Step6 cmr (codex #3 + Claude): `familyHead` is otherwise assigned ONLY inside
    // the wave merge loop. On a resume where reconcile accounts for EVERY remaining
    // child (its补账 + the prior ledger cover the whole epic), `currentMerged` skips
    // them all → the wave loop runs NO merge → `familyHead` would leak `undefined`,
    // even though the family base真实 leads at the reconcile-verified `liveHead`.
    // Seed it from `plan.liveHead` whenever the base already has merges (`merged`
    // non-empty), so a no-new-merge resume's FINAL-barrier durable `aborted`
    // familyHeadAfter baseline (#291 缺口 2) AND the returned `FamilyRunResult`
    // report the真实 head; a later wave merge (:familyHead = mergeResult.familyHead)
    // overwrites it. A truly fresh run (empty ledger, nothing merged) leaves it
    // `undefined` — `plan.merged` is empty there, so the guard does not fire.
    if (plan.merged.size > 0) familyHead = plan.liveHead;
  }

  // The wave loop. Re-select from the merged set after each wave so a future
  // multi-wave epic (#294) advances as blockers merge; #293's all-unblocked
  // children converge in a single pass. Guard against a no-progress wave (a
  // child that failed to merge would otherwise re-select forever) by tracking
  // the set of children the spine has already ATTEMPTED.
  const attempted = new Set<number>();
  for (;;) {
    const merged = await currentMerged(familyBackend);
    const wave = selectWave(epic.children, merged).filter(
      (c) => !attempted.has(c.issue),
    );
    if (wave.length === 0) {
      // ID-009: residual cycle only at empty-wave + still-unmerged residual.
      const residual = epic.children.filter((c) => !merged.has(c.issue));
      if (residual.length > 0) {
        try {
          assertAcyclic(residual);
        } catch (err) {
          if (!(err instanceof DependencyCycleError)) throw err;
          const children: FamilyChildResult[] = epic.children.map((c) => {
            const recorded = childResults.find((entry) => entry.issue === c.issue);
            if (recorded !== undefined) return recorded;
            return merged.has(c.issue)
              ? { issue: c.issue, status: "already_done" as const }
              : { issue: c.issue, status: "skipped" as const };
          });
          const escalationReason = `dependency_cycle: ${err.cycle.map((n) => `#${n}`).join(" → ")}`;
          const stopSummary = familyStopSummary({
            status: "escalated",
            familyBase,
            familyHead,
            children,
            escalationReason,
          });
          await familyBackend.escalateFamily?.({
            reason: escalationReason,
            diagnosis: err.message,
            ...(familyHead !== undefined ? { familyHeadAfter: familyHead } : {}),
            stopSummary,
            escalationKind: "failure",
            phase: "wave",
          });
          return attachDiagnostics({
            status: "escalated" as const,
            familyBase,
            familyHead,
            escalation: { reason: escalationReason, diagnosis: err.message },
            stopSummary,
            children,
            ...(epic.admissionSkipped !== undefined &&
            epic.admissionSkipped.length > 0
              ? { admissionSkipped: epic.admissionSkipped }
              : {}),
          });
        }
      }
      break;
    }

    // Concurrent fan-out (allSettled, wave order); serial merge below.
    // #938: rethrow-first deleted — keep every sibling outcome.
    logDriverStage(
      "dispatch",
      `wave n=${wave.length} issues=${wave.map((c) => c.issue).join(",")}`,
    );
    for (const child of wave) attempted.add(child.issue);
    const settled = await Promise.allSettled(
      wave.map((child) =>
        runChild(
          child,
          singleSliceBackend,
          epic.issue,
          familyBase,
          familyChildIssues,
          familyBackend,
          // #604 slice 5 / #970: only ledger-proven decision parks with sessionId.
          parkedChildAnswers.get(child.issue),
        ),
      ),
    );
    const ran: FamilyChildResult[] = settled.map((s, i) => {
      if (s.status === "fulfilled") {
        const value = s.value;
        if (value.status === "failed") {
          const cause =
            value.failureCause ??
            `child #${value.issue} single-slice execution did not succeed`;
          waveDiagnostics.push({
            issue: value.issue,
            cause,
            kind: "child_execution",
          });
          return value.failureCause !== undefined
            ? value
            : { ...value, failureCause: cause };
        }
        return value;
      }
      const child = wave[i]!;
      const cause =
        s.reason instanceof Error ? s.reason.message : String(s.reason);
      waveDiagnostics.push({
        issue: child.issue,
        cause,
        kind: "process",
      });
      return {
        issue: child.issue,
        status: "failed" as const,
        failureCause: cause,
      };
    });

    // ── serial merge: each reviewed child branch into the family base ──────────
    // merger.mergeChild does the `git merge --no-ff` (via the FamilyBackend seam)
    // AND writes the merged ledger entry (decision 5 order). The spine never does
    // the merge itself — that is the #295 seam boundary. A child is recorded
    // `"merged"` ONLY AFTER its merge commit lands (decision 5): runChild returns
    // `"ran"` (single-slice success, not yet merged), and we flip it to `"merged"`
    // here once mergeChild resolves — so a future #295 merge failure can leave the
    // child as `"ran"`/`"failed"` instead of a stale `"merged"`.
    //
    // #938: mid-wave early exit (merger decision escalate / still-conflicted)
    // must drain remaining allSettled siblings into childResults first. Without
    // that flush, finalize / residual maps map executed peers to fake "skipped".
    // "skipped" is only for never-schedulable / never-ran children.
    // Spread the whole sibling so optional fields (branch / escalation /
    // failureCause / future FamilyChildResult cargo) are never silently dropped.
    const recordWaveSibling = (sibling: FamilyChildResult): void => {
      childResults.push({ ...sibling });
    };
    const drainRemainingWaveSiblings = (): void => {
      const recorded = new Set(childResults.map((c) => c.issue));
      for (const sibling of ran) {
        if (recorded.has(sibling.issue)) continue;
        recordWaveSibling(sibling);
        recorded.add(sibling.issue);
      }
    };
    /** #938: drain allSettled peers then residual-map epic children for early exits. */
    const residualChildrenAfterDrain = async (): Promise<FamilyChildResult[]> => {
      drainRemainingWaveSiblings();
      const ledgerMerged = await currentMerged(familyBackend);
      return epic.children.map((child) => {
        const recorded = childResults.find((entry) => entry.issue === child.issue);
        if (recorded !== undefined) return recorded;
        return ledgerMerged.has(child.issue)
          ? { issue: child.issue, status: "already_done" as const }
          : { issue: child.issue, status: "skipped" as const };
      });
    };
    for (const r of ran) {
      if (r.status === "ran" && r.branch !== undefined) {
        // C3: merger QuotaWait must enter the same park/relay machine (S1→merger),
        // not kill the family run outside the decision loop.
        const mergeBarrier = await runFamilyBarrierWithQuotaRelay({
          phase: "merge",
          familyBackend,
          singleSliceBackend,
          familyBase,
          familyHead,
          runId,
          modelRoute: activeRoute,
          recordedResults: childResults,
          epicChildren: epic.children,
          epicIssue: epic.issue,
          relayHandoffs,
          wallHitBillingPools,
          ...(runRelayBilling !== undefined
            ? { initialRelayBilling: runRelayBilling }
            : {}),
          ...(applyRelayOverride !== undefined
            ? { applyRelayBatonToRoute: applyRelayOverride }
            : {}),
          ...(input.relayPools !== undefined
            ? { relayPools: input.relayPools }
            : {}),
          ...(input.now !== undefined ? { now: input.now } : {}),
          ...(epic.admissionSkipped !== undefined &&
          epic.admissionSkipped.length > 0
            ? { admissionSkipped: epic.admissionSkipped }
            : {}),
          run: (route) =>
            mergeChild(familyBackend, {
              childIssue: r.issue,
              childBranch: r.branch!,
              modelRoute: route,
              runId,
            }),
        });
        if (mergeBarrier.kind === "park") {
          // #938: remount residual children after drain so executed siblings stay
          // honest `ran`, not fake `skipped`; attach wave diagnostics too.
          const children = await residualChildrenAfterDrain();
          return attachDiagnostics({ ...mergeBarrier.result, children });
        }
        activeRoute = mergeBarrier.route;
        if (mergeBarrier.relayBilling !== undefined) {
          runRelayBilling = mergeBarrier.relayBilling;
        }
        const mergeResult = mergeBarrier.value;
        if (mergeResult.escalation !== undefined) {
          familyHead = mergeResult.familyHead;
          childResults.push({ issue: r.issue, status: "failed", branch: r.branch });
          const children = await residualChildrenAfterDrain();
          const escalation = mergeResult.escalation;
          const stopSummary = familyStopSummary({
            status: "escalated",
            familyBase,
            familyHead,
            children,
            escalationReason: escalation.reason,
          });
          await familyBackend.escalateFamily?.({
            ...escalation,
            ...(familyHead !== undefined ? { familyHeadAfter: familyHead } : {}),
            stopSummary,
            escalationKind: "decision",
            phase: "wave",
          });
          return attachDiagnostics({
            status: "escalated" as const,
            familyBase,
            familyHead,
            escalation: {
              reason: escalation.reason,
              diagnosis: escalation.diagnosis ?? escalation.reason,
            },
            stopSummary,
            children,
          });
        }
        if (mergeResult.conflicted === true) {
          // ID-010: trust merger worker once; stop serial merge on conflicted base.
          familyHead = mergeResult.familyHead;
          const cause =
            `merger_worker left child #${r.issue} conflict unresolved on the family base`;
          waveDiagnostics.push({ issue: r.issue, cause, kind: "merger_worker" });
          childResults.push({
            issue: r.issue,
            status: "failed",
            branch: r.branch,
            failureCause: cause,
          });
          drainRemainingWaveSiblings();
          return await finalize();
        }
        familyHead = mergeResult.familyHead;
        childResults.push({ issue: r.issue, status: "merged", branch: r.branch });
      } else {
        recordWaveSibling(r);
      }
    }

    // ── #604 slice 5: a CHILD decision escalation PARKS the family (stop-wave) ───
    // A child that returned `"escalated"` hit a product/design题. Record an
    // INDEPENDENT `child_decision_parked` ledger row (bound to childIssue, carrying the
    // child's sessionId for 原地 resume) and STOP: do NOT run the wave barrier or
    // select a next wave (sub-decision ②). The `"ran"` siblings this wave already
    // merged above stay durable; the un-answered child pauses the whole family
    // until a later `escalation_answered` row reopens it (退出-重入, ADR 0062). The
    // failure bucket never reaches here — runChild returned `"failed"` for it.
    const escalatedChildren = ran.filter(
      (r): r is FamilyChildResult & { escalation: FamilyChildEscalation } =>
        r.status === "escalated" && r.escalation !== undefined,
    );
    if (escalatedChildren.length > 0) {
      // #604 correctness r1 (P1-a ②): A-class failure优先于 B-class decision park.
      // A wave can carry BOTH a real `failed` child (infra/protocol failure — the
      // A-class incomplete/failure outcome) AND a decision-escalated child. The
      // old code parked (B-class) as soon as ANY decision-escalated child existed,
      // silently MASKING the real failure behind an answerable park. If this wave
      // produced a genuine failure, do NOT park: fall through to the honest
      // `incomplete` finalize (the failed child is never merged, the run is not
      // shippable) rather than a `decision_gate_park` that hides it.
      const hasRealFailure = ran.some((r) => r.status === "failed");
      if (!hasRealFailure) {
        for (const child of escalatedChildren) {
          await recordChildDecisionParked(familyBackend, {
            childIssue: child.issue,
            reason: child.escalation.reason,
            diagnosis: child.escalation.diagnosis,
            ...(child.escalation.sessionId !== undefined
              ? { sessionId: child.escalation.sessionId }
              : {}),
            ...(familyHead !== undefined ? { familyHeadAfter: familyHead } : {}),
          });
        }
        return await finalizeDecisionPark(escalatedChildren[0]!, childResults);
      }
      // A real failure is present: finalize honestly as incomplete (A-class). The
      // escalated child's payload is preserved in `childResults` (recorded above
      // via the else branch of the merge loop), so the driver still sees it.
      return await finalize();
    }

    // ── verify-cmr hook: per-wave barrier (default = real runVerifyCmr) ────────
    // Decision 3④: a red wave fails-fast — abort BEFORE selecting the next wave.
    // The spine acts on `ok` and passes phase + context; production runs real
    // verify in the family base. Tests inject only when stubbing the barrier.
    // #909: quota wall → park or apply baton + re-dispatch (shared machine).
    const waveBarrier = await runFamilyBarrierWithQuotaRelay({
      phase: "wave",
      familyBackend,
      singleSliceBackend,
      familyBase,
      familyHead,
      runId,
      modelRoute: activeRoute,
      recordedResults: childResults,
      epicChildren: epic.children,
      epicIssue: epic.issue,
      relayHandoffs,
      wallHitBillingPools,
      ...(runRelayBilling !== undefined
        ? { initialRelayBilling: runRelayBilling }
        : {}),
      ...(applyRelayOverride !== undefined
        ? { applyRelayBatonToRoute: applyRelayOverride }
        : {}),
      ...(input.relayPools !== undefined ? { relayPools: input.relayPools } : {}),
      ...(input.now !== undefined ? { now: input.now } : {}),
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
      run: (route, relayBilling) =>
        verifyCmr({
          phase: "wave",
          familyBase,
          familyBackend,
          runId,
          modelRoute: route,
          ...(relayBilling !== undefined
            ? {
                billingPool: relayBilling.pool,
                billingPoolSlots: relayBilling.slots,
              }
            : {}),
          // #291 缺口 2: hand the abort-time family head to the hook so a RED wave verify
          // records it on the PHASE-LEVEL durable aborted entry's `familyHeadAfter`
          // (reconcile's baseline read covers the abort). `familyHead` is the head after
          // this wave's last merge — undefined only if nothing merged this run.
          familyHeadAfter: familyHead,
          familyIssue: epic.issue,
          ...(declaredModuleContext !== undefined
            ? { moduleContext: declaredModuleContext }
            : {}),
        }),
    });
    if (waveBarrier.kind === "park") return waveBarrier.result;
    activeRoute = waveBarrier.route;
    if (waveBarrier.relayBilling !== undefined) {
      runRelayBilling = waveBarrier.relayBilling;
    }
    const waveVerify = waveBarrier.value;
    if (!waveVerify.ok) {
      // Fail-fast (decision 3④): do not排下一波. #296's red wave lands here; the
      // family base + ledger are left for triage (decision 3⑤ "不静默吞"). Children
      // not yet run are recorded "skipped"/"merged" by finalize(); the run is
      // observably `verify_failed` at the "wave" phase (wave is verify-only; #922).
      return await finalize({
        failedStatus: waveVerify.failedStatus ?? "verify_failed",
        failedPhase: "wave",
      });
    }
  }

  // ── completeness gate (online R1 Codex P1): the final barrier is meaningful ONLY
  // for a COMPLETE family base ────────────────────────────────────────────────
  // A child can leave the wave loop UNMERGED without throwing (its single-slice run
  // returned "failed", or it stayed blocked) — finalize() then marks the run
  // "incomplete". Running the final barrier (全量 verify → integrated cmr → 止于-PR)
  // on that PARTIAL base would open a family PR missing slices, even though the
  // returned status is not shippable. So gate it: if not EVERY epic child is
  // ledger-merged, skip the barrier and finalize() honestly returns "incomplete"
  // with NO verify / cmr / PR (decision 3⑤ 不静默吞 + decision 4 止于-PR only when whole).
  const mergedNow = await currentMerged(familyBackend);
  if (!epic.children.every((c) => mergedNow.has(c.issue))) {
    return await finalize();
  }

  // ── already-converged resume guard (#596) ───────────────────────────────────
  // If a prior invocation already ran the full final barrier (verify → cmr →
  // ship → review loop) for the SAME family HEAD, a complete
  // `review_loop_converged` ledger entry exists. Re-running the final barrier
  // would re-verify, re-cmr, re-ship, and re-loop — duplicating work. An older
  // converged marker for a different head must NOT hide a later live-base
  // advance; that new head needs a fresh final barrier.
  const preFinalLedger = await familyBackend.readFamilyLedger();
  const preFinalLedgerLength = preFinalLedger.length;
  const preFinalFamilyHead =
    familyHead ?? (await readCurrentFamilyHead(familyBackend, familyBase));
  const convergedRecord = familyReviewLoopConvergedForHead(
    preFinalLedger,
    preFinalFamilyHead,
  );
  if (convergedRecord != null) {
    const ledgerMerged = await currentMerged(familyBackend);
    const children: FamilyChildResult[] = epic.children.map((c) =>
      ledgerMerged.has(c.issue)
        ? { issue: c.issue, status: "already_done" as const }
        : { issue: c.issue, status: "skipped" as const },
    );

    const priorPrMerged = familyPrMergedForHead(preFinalLedger, preFinalFamilyHead);
    if (priorPrMerged !== undefined) {
      familyHead = preFinalFamilyHead;
      const cleanupBlocked = await requirePostMergeCleanupForAlreadyDone({
        familyBackend,
        familyBase,
        runId,
        familyHeadAfter: preFinalFamilyHead!,
        prUrl: priorPrMerged.pr,
        familyIssue: epic.issue,
        resolvedRoute: activeRoute,
        children,
        ...(Array.isArray(epic.admissionSkipped) && epic.admissionSkipped.length > 0
          ? { admissionSkipped: epic.admissionSkipped }
          : {}),
      });
      if (cleanupBlocked !== undefined) return cleanupBlocked;
      const convergedVerifiedCmrHead =
        convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ??
        preFinalFamilyHead;
      const alreadyDoneSummary: StopSummary = {
        reason: "already_done",
        summary: "family run already converged for the current family HEAD",
        metadata: {
          heads: {
            actualFamilyHead: preFinalFamilyHead,
            reportedFamilyHead: convergedRecord.familyHeadAfter,
            verifiedCmrHead: convergedVerifiedCmrHead,
            sources: {
              actualFamilyHead: "current family head",
              reportedFamilyHead: "review_loop_converged ledger row",
              verifiedCmrHead:
                typeof convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ===
                "string"
                  ? "review_loop_converged ledger stop summary"
                  : "review_loop_converged ledger row",
            },
          },
        },
      };
      return {
        status: "success",
        familyBase,
        familyHead,
        stopSummary: alreadyDoneSummary,
        children,
        ...(Array.isArray(epic.admissionSkipped) && epic.admissionSkipped.length > 0
          ? { admissionSkipped: epic.admissionSkipped }
          : {}),
      };
    }

    if (
      isFamilyPrLiveMerged(convergedRecord.pr) &&
      preFinalFamilyHead !== undefined
    ) {
      const mergedBackfill = await runFamilyAutoMergeStage({
        familyBackend,
        familyBase,
        convergedHeadOid: preFinalFamilyHead,
        prUrl: convergedRecord.pr,
      });
      if (!familyAutoMergeIncomplete(mergedBackfill)) {
        familyHead = preFinalFamilyHead;
        const cleanupBlocked = await requirePostMergeCleanupForAlreadyDone({
          familyBackend,
          familyBase,
          runId,
          familyHeadAfter: preFinalFamilyHead,
          prUrl: convergedRecord.pr,
          familyIssue: epic.issue,
        resolvedRoute: activeRoute,
          children,
          ...(Array.isArray(epic.admissionSkipped) && epic.admissionSkipped.length > 0
            ? { admissionSkipped: epic.admissionSkipped }
            : {}),
        });
        if (cleanupBlocked !== undefined) return cleanupBlocked;
        const convergedVerifiedCmrHead =
          convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ??
          preFinalFamilyHead;
        const alreadyDoneSummary: StopSummary = {
          reason: "already_done",
          summary: "family run already converged for the current family HEAD",
          metadata: {
            heads: {
              actualFamilyHead: preFinalFamilyHead,
              reportedFamilyHead: convergedRecord.familyHeadAfter,
              verifiedCmrHead: convergedVerifiedCmrHead,
              sources: {
                actualFamilyHead: "current family head",
                reportedFamilyHead: "review_loop_converged ledger row",
                verifiedCmrHead:
                  typeof convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ===
                  "string"
                    ? "review_loop_converged ledger stop summary"
                    : "review_loop_converged ledger row",
              },
            },
          },
        };
        return {
          status: "success",
          familyBase,
          familyHead,
          stopSummary: alreadyDoneSummary,
          children,
          ...(Array.isArray(epic.admissionSkipped) && epic.admissionSkipped.length > 0
            ? { admissionSkipped: epic.admissionSkipped }
            : {}),
        };
      }
      const rawStop =
        mergedBackfill.stopSummary ??
        decisionGateParkStopSummary({
          summary: `family auto-merge did not complete (${mergedBackfill.terminalState})`,
          repairHint:
            "resolve merge blockers or answer the decision gate, then re-feed the family run",
        });
      const terminal = familyTerminalFromStopSummary({ stage: "merge_failed", stopSummary: rawStop });
      if (terminal.status === "escalated") {
        await recordFamilyEscalated(familyBackend, {
          escalationKind: "decision",
          phase: "final",
          reason: terminal.stopSummary.summary,
          familyHeadAfter: preFinalFamilyHead,
          stopSummary: terminal.stopSummary,
        });
      } else {
        await familyBackend.appendFamilyLedger({
          status: "aborted",
          event: "aborted",
          phase: "final",
          reason: terminal.stopSummary.summary,
          familyHeadAfter: preFinalFamilyHead,
          stopSummary: terminal.stopSummary,
        });
      }
      return {
        status: terminal.status,
        familyBase,
        familyHead: preFinalFamilyHead,
        ...(terminal.status === "merge_failed"
          ? { failedPhase: "final" as const }
          : {}),
        stopSummary: terminal.stopSummary,
        children,
      };
    }


    const autoMerge = await runFamilyAutoMergeStage({
      familyBackend,
      familyBase,
      convergedHeadOid: preFinalFamilyHead!,
      prUrl: convergedRecord.pr,
    });
    if (familyAutoMergeIncomplete(autoMerge)) {
      const rawStop =
        autoMerge.stopSummary ??
        decisionGateParkStopSummary({
          summary: `family auto-merge did not complete (${autoMerge.terminalState})`,
          repairHint:
            "resolve merge blockers or answer the decision gate, then re-feed the family run",
        });
      const terminal = familyTerminalFromStopSummary({ stage: "merge_failed", stopSummary: rawStop });
      if (terminal.status === "escalated") {
        await recordFamilyEscalated(familyBackend, {
          escalationKind: "decision",
          phase: "final",
          reason: terminal.stopSummary.summary,
          familyHeadAfter: preFinalFamilyHead,
          stopSummary: terminal.stopSummary,
        });
      } else {
        await familyBackend.appendFamilyLedger({
          status: "aborted",
          event: "aborted",
          phase: "final",
          reason: terminal.stopSummary.summary,
          familyHeadAfter: preFinalFamilyHead,
          stopSummary: terminal.stopSummary,
        });
      }
      return {
        status: terminal.status,
        familyBase,
        familyHead: preFinalFamilyHead,
        ...(terminal.status === "merge_failed"
          ? { failedPhase: "final" as const }
          : {}),
        stopSummary: terminal.stopSummary,
        children,
      };
    }

    familyHead = preFinalFamilyHead;
    const cleanupBlocked = await requirePostMergeCleanupForAlreadyDone({
      familyBackend,
      familyBase,
      runId,
      familyHeadAfter: preFinalFamilyHead!,
      prUrl: convergedRecord.pr,
      familyIssue: epic.issue,
      resolvedRoute: activeRoute,
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    });
    if (cleanupBlocked !== undefined) return cleanupBlocked;
    const convergedVerifiedCmrHead =
      convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead ??
      preFinalFamilyHead;
    const alreadyDoneSummary: StopSummary = {
      reason: "already_done",
      summary: "family run already converged for the current family HEAD",
      metadata: {
        heads: {
          actualFamilyHead: preFinalFamilyHead,
          reportedFamilyHead: convergedRecord.familyHeadAfter,
          verifiedCmrHead: convergedVerifiedCmrHead,
          sources: {
            actualFamilyHead: "current family head",
            reportedFamilyHead: "review_loop_converged ledger row",
            verifiedCmrHead:
              convergedRecord.stopSummary?.metadata?.heads?.verifiedCmrHead != null
                ? "review_loop_converged ledger stop summary"
                : "review_loop_converged ledger row",
          },
        },
      },
    };
    return {
      status: "success",
      familyBase,
      familyHead,
      stopSummary: alreadyDoneSummary,
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    };
  }

  // `shipped` is the durable checkpoint written immediately after the ship
  // worker opens the PR. A crash after that write resumes at online review;
  // verify/CMR/ship must not run twice. This is bookkeeping, not a delivery
  // verdict: the worker already pressed the ship success button.
  const shippedRecord = familyShippedRecordForReviewLoopResume(
    preFinalLedger,
    preFinalFamilyHead,
  );
  if (shippedRecord !== undefined) {
    const ledgerMerged = await currentMerged(familyBackend);
    const children: FamilyChildResult[] = epic.children.map((child) =>
      ledgerMerged.has(child.issue)
        ? { issue: child.issue, status: "already_done" as const }
        : { issue: child.issue, status: "skipped" as const },
    );
    // #909: online-review 429 → park or apply baton + re-dispatch.
    const reviewBarrier = await runFamilyBarrierWithQuotaRelay({
      phase: "online_review",
      familyBackend,
      singleSliceBackend,
      familyBase,
      familyHead: preFinalFamilyHead,
      runId,
      modelRoute: activeRoute,
      recordedResults: children,
      epicChildren: epic.children,
      epicIssue: epic.issue,
      relayHandoffs,
      wallHitBillingPools,
      ...(runRelayBilling !== undefined
        ? { initialRelayBilling: runRelayBilling }
        : {}),
      ...(applyRelayOverride !== undefined
        ? { applyRelayBatonToRoute: applyRelayOverride }
        : {}),
      ...(input.relayPools !== undefined ? { relayPools: input.relayPools } : {}),
      ...(input.now !== undefined ? { now: input.now } : {}),
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
      run: (route, relayBilling) =>
        runFamilyOnlineReviewLoop({
          familyBackend,
          familyBase,
          runId,
          ship: {
            kind: "ship",
            branch: familyBase,
            pr: shippedRecord.pr,
            prHead: shippedRecord.familyHeadAfter,
            status: "pr_opened",
          },
          resolvedRoute: route,
          ...(relayBilling !== undefined
            ? {
                billingPool: relayBilling.pool,
                billingPoolSlots: relayBilling.slots,
              }
            : {}),
          ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
        }),
    });
    if (reviewBarrier.kind === "park") return reviewBarrier.result;
    activeRoute = reviewBarrier.route;
    if (reviewBarrier.relayBilling !== undefined) {
      runRelayBilling = reviewBarrier.relayBilling;
    }
    const reviewLoop = reviewBarrier.value;
    if (!reviewLoop.ok) {
      const rawStop =
        reviewLoop.stopSummary ??
        stageFailureStopSummary({
          status: "online_review_failed",
          summary: "family online review loop did not converge during shipped resume",
          repairHint: "repair or answer the worker-reported stop, then re-feed the family run",
        });
      const terminal = familyTerminalFromStopSummary({
        stage: "online_review_failed",
        stopSummary: rawStop,
      });
      if (terminal.status === "escalated") {
        await recordFamilyEscalated(familyBackend, {
          escalationKind: "decision",
          phase: "final",
          reason: terminal.stopSummary.summary,
          familyHeadAfter: preFinalFamilyHead,
          stopSummary: terminal.stopSummary,
        });
      } else {
        await familyBackend.appendFamilyLedger({
          status: "aborted",
          event: "aborted",
          phase: "final",
          reason: terminal.stopSummary.summary,
          familyHeadAfter: preFinalFamilyHead,
          stopSummary: terminal.stopSummary,
        });
      }
      return {
        status: terminal.status,
        familyBase,
        familyHead: preFinalFamilyHead,
        ...(terminal.status === "online_review_failed"
          ? { failedPhase: "final" as const }
          : {}),
        stopSummary: terminal.stopSummary,
        children,
      };
    }

    const convergedHead =
      (await readCurrentFamilyHead(familyBackend, familyBase)) ??
      preFinalFamilyHead ??
      shippedRecord.familyHeadAfter;
    await recordReviewLoopConverged(familyBackend, {
      pr: shippedRecord.pr,
      familyHeadAfter: convergedHead,
      ...(shippedRecord.stopSummary !== undefined
        ? { stopSummary: shippedRecord.stopSummary }
        : {}),
    });
    const autoMerge = await runFamilyAutoMergeStage({
      familyBackend,
      familyBase,
      convergedHeadOid: convergedHead,
      prUrl: shippedRecord.pr,
    });
    if (familyAutoMergeIncomplete(autoMerge)) {
      const rawStop =
        autoMerge.stopSummary ??
        decisionGateParkStopSummary({
          summary: `family auto-merge did not complete (${autoMerge.terminalState})`,
          repairHint: "resolve the worker-reported merge stop, then re-feed the family run",
        });
      const terminal = familyTerminalFromStopSummary({ stage: "merge_failed", stopSummary: rawStop });
      if (terminal.status === "escalated") {
        await recordFamilyEscalated(familyBackend, {
          escalationKind: "decision",
          phase: "final",
          reason: terminal.stopSummary.summary,
          familyHeadAfter: convergedHead,
          stopSummary: terminal.stopSummary,
        });
      } else {
        await familyBackend.appendFamilyLedger({
          status: "aborted",
          event: "aborted",
          phase: "final",
          reason: terminal.stopSummary.summary,
          familyHeadAfter: convergedHead,
          stopSummary: terminal.stopSummary,
        });
      }
      return {
        status: terminal.status,
        familyBase,
        familyHead: convergedHead,
        ...(terminal.status === "merge_failed"
          ? { failedPhase: "final" as const }
          : {}),
        stopSummary: terminal.stopSummary,
        children,
      };
    }

    familyHead = convergedHead;
    const cleanupBlocked = await requirePostMergeCleanupForAlreadyDone({
      familyBackend,
      familyBase,
      runId,
      familyHeadAfter: convergedHead,
      prUrl: shippedRecord.pr,
      familyIssue: epic.issue,
      resolvedRoute: activeRoute,
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    });
    if (cleanupBlocked !== undefined) return cleanupBlocked;
    return {
      status: "success",
      familyBase,
      familyHead,
      stopSummary: {
        reason: "already_done",
        summary: "family review loop resumed from the shipped checkpoint and converged",
      },
      children,
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    };
  }

  // #909: final barrier 429 → park or apply baton + re-dispatch (full invariant).
  // B4: open-shipped terminal FamilyRunResult (escalated with stopSummary) must
  // not collapse into finalize("final") → bare verify_failed.
  let openShippedTerminal: FamilyRunResult | undefined;
  const finalBarrier = await runFamilyBarrierWithQuotaRelay({
    phase: "final",
    familyBackend,
    singleSliceBackend,
    familyBase,
    familyHead,
    runId,
    modelRoute: activeRoute,
    recordedResults: childResults,
    epicChildren: epic.children,
    epicIssue: epic.issue,
    relayHandoffs,
    wallHitBillingPools,
    ...(runRelayBilling !== undefined
      ? { initialRelayBilling: runRelayBilling }
      : {}),
    ...(applyRelayOverride !== undefined
      ? { applyRelayBatonToRoute: applyRelayOverride }
      : {}),
    ...(input.relayPools !== undefined ? { relayPools: input.relayPools } : {}),
    ...(input.now !== undefined ? { now: input.now } : {}),
    ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
      ? { admissionSkipped: epic.admissionSkipped }
      : {}),
    run: async (route, relayBilling) => {
      // F1 / N1: after recordShipped, online-review quota re-entry must NOT re-run
      // verify/CMR/ship — only when open shipped matches **this** barrier head.
      const ledgerNow = await familyBackend.readFamilyLedger();
      const barrierHead =
        (await readCurrentFamilyHead(familyBackend, familyBase)) ?? familyHead;
      const openShipped = familyOpenShippedForOnlineReview(
        ledgerNow,
        barrierHead,
      );
      if (openShipped !== undefined) {
        // B4: reuse shipped-resume tail — preserve stopSummary + escalated status
        // instead of bare {ok:false} → finalize verify_failed.
        const ledgerMerged = await currentMerged(familyBackend);
        const openChildren: FamilyChildResult[] = epic.children.map((child) =>
          childResults.some(
            (c) => c.issue === child.issue && c.status === "merged",
          ) || ledgerMerged.has(child.issue)
            ? {
                issue: child.issue,
                status: ledgerMerged.has(child.issue)
                  ? ("already_done" as const)
                  : ("merged" as const),
              }
            : { issue: child.issue, status: "skipped" as const },
        );
        const reviewLoop = await runFamilyOnlineReviewLoop({
          familyBackend,
          familyBase,
          runId,
          ship: {
            kind: "ship",
            branch: familyBase,
            pr: openShipped.pr,
            prHead: openShipped.familyHeadAfter,
            status: "pr_opened",
          },
          resolvedRoute: route,
          ...(relayBilling !== undefined
            ? {
                billingPool: relayBilling.pool,
                billingPoolSlots: relayBilling.slots,
              }
            : {}),
          ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
        });
        if (!reviewLoop.ok) {
          const rawStop =
            reviewLoop.stopSummary ??
            stageFailureStopSummary({
              status: "online_review_failed",
              summary:
                "family online review loop did not converge during open-shipped re-entry",
              repairHint:
                "repair or answer the worker-reported stop, then re-feed the family run",
            });
          const terminal = familyTerminalFromStopSummary({
            stage: "online_review_failed",
            stopSummary: rawStop,
          });
          if (terminal.status === "escalated") {
            await recordFamilyEscalated(familyBackend, {
              escalationKind: "decision",
              phase: "final",
              reason: terminal.stopSummary.summary,
              familyHeadAfter: barrierHead,
              stopSummary: terminal.stopSummary,
            });
          } else {
            await familyBackend.appendFamilyLedger({
              status: "aborted",
              event: "aborted",
              phase: "final",
              reason: terminal.stopSummary.summary,
              familyHeadAfter: barrierHead,
              stopSummary: terminal.stopSummary,
            });
          }
          openShippedTerminal = {
            status: terminal.status,
            familyBase,
            familyHead: barrierHead,
            ...(terminal.status === "online_review_failed"
              ? { failedPhase: "final" as const }
              : {}),
            stopSummary: terminal.stopSummary,
            children: openChildren,
            ...(epic.admissionSkipped !== undefined &&
            epic.admissionSkipped.length > 0
              ? { admissionSkipped: epic.admissionSkipped }
              : {}),
          };
          return { ok: false, ran: true };
        }
        // Mirror shipped-resume / verifyCmr post-ship tail.
        const convergedHead =
          (await readCurrentFamilyHead(familyBackend, familyBase)) ??
          openShipped.familyHeadAfter;
        await recordReviewLoopConverged(familyBackend, {
          pr: openShipped.pr,
          familyHeadAfter: convergedHead,
          ...(openShipped.stopSummary !== undefined
            ? { stopSummary: openShipped.stopSummary }
            : {}),
        });
        const autoMerge = await runFamilyAutoMergeStage({
          familyBackend,
          familyBase,
          convergedHeadOid: convergedHead,
          prUrl: openShipped.pr,
        });
        if (familyAutoMergeIncomplete(autoMerge)) {
          const rawStop =
            autoMerge.stopSummary ??
            decisionGateParkStopSummary({
              summary: `family auto-merge did not complete (${autoMerge.terminalState})`,
              repairHint:
                "resolve the worker-reported merge stop, then re-feed the family run",
            });
          const terminal = familyTerminalFromStopSummary({ stage: "merge_failed", stopSummary: rawStop });
          if (terminal.status === "escalated") {
            await recordFamilyEscalated(familyBackend, {
              escalationKind: "decision",
              phase: "final",
              reason: terminal.stopSummary.summary,
              familyHeadAfter: convergedHead,
              stopSummary: terminal.stopSummary,
            });
          } else {
            await familyBackend.appendFamilyLedger({
              status: "aborted",
              event: "aborted",
              phase: "final",
              reason: terminal.stopSummary.summary,
              familyHeadAfter: convergedHead,
              stopSummary: terminal.stopSummary,
            });
          }
          openShippedTerminal = {
            status: terminal.status,
            familyBase,
            familyHead: convergedHead,
            ...(terminal.status === "merge_failed"
              ? { failedPhase: "final" as const }
              : {}),
            stopSummary: terminal.stopSummary,
            children: openChildren,
            ...(epic.admissionSkipped !== undefined &&
            epic.admissionSkipped.length > 0
              ? { admissionSkipped: epic.admissionSkipped }
              : {}),
          };
          return { ok: false, ran: true };
        }
        const cleanupBlocked = await requirePostMergeCleanupForAlreadyDone({
          familyBackend,
          familyBase,
          runId,
          familyHeadAfter: convergedHead,
          prUrl: openShipped.pr,
          familyIssue: epic.issue,
          resolvedRoute: route,
          children: openChildren,
          ...(epic.admissionSkipped !== undefined &&
          epic.admissionSkipped.length > 0
            ? { admissionSkipped: epic.admissionSkipped }
            : {}),
        });
        if (cleanupBlocked !== undefined) {
          openShippedTerminal = cleanupBlocked;
          return { ok: false, ran: true };
        }
        openShippedTerminal = {
          status: "success",
          familyBase,
          familyHead: convergedHead,
          stopSummary: {
            reason: "already_done",
            summary:
              "family review loop resumed from the open-shipped checkpoint and converged",
          },
          children: openChildren,
          ...(epic.admissionSkipped !== undefined &&
          epic.admissionSkipped.length > 0
            ? { admissionSkipped: epic.admissionSkipped }
            : {}),
        };
        return { ok: true, ran: true };
      }
      return verifyCmr({
        phase: "final",
        familyBase,
        familyBackend,
        runId,
        modelRoute: route,
        ...(relayBilling !== undefined
          ? {
              billingPool: relayBilling.pool,
              billingPoolSlots: relayBilling.slots,
            }
          : {}),
        // #291 缺口 1: derive the LLM-resolved children from the durable ledger and
        // hand them to the final-phase integrated cmr 承重闸 (via runVerifyCmr →
        // IntegratedCmrRequest.llmResolvedChildren), so it sees which merges a machine
        // touched. The wave barrier is verify-only (no cmr), so only the final call
        // needs it; an empty list ⇒ the cmr request omits the field.
        llmResolvedChildren: await llmResolvedChildren(familyBackend),
        ...(() => {
          const priorKeysByPass = pendingPriorCmrFindingIdentityKeysByPass(
            preFinalLedger,
            preFinalFamilyHead,
          );
          return Object.keys(priorKeysByPass).length > 0
            ? { priorCmrFindingIdentityKeysByPass: priorKeysByPass }
            : {};
        })(),
        ...(escalationAnswer !== undefined ? { escalationAnswer } : {}),
        // #291 缺口 2: the abort-time head for a RED final verify's durable aborted entry.
        familyHeadAfter: familyHead,
        familyIssue: epic.issue,
        ...(declaredModuleContext !== undefined
          ? { moduleContext: declaredModuleContext }
          : {}),
      });
    },
  });
  if (finalBarrier.kind === "park") return finalBarrier.result;
  activeRoute = finalBarrier.route;
  if (finalBarrier.relayBilling !== undefined) {
    runRelayBilling = finalBarrier.relayBilling;
  }
  const finalVerify = finalBarrier.value;
  // B4: open-shipped re-entry already built a structured FamilyRunResult
  // (success or escalated with stopSummary) — do not rewrite to verify_failed.
  if (openShippedTerminal !== undefined) {
    familyHead = openShippedTerminal.familyHead ?? familyHead;
    return openShippedTerminal;
  }
  if (!finalVerify.ok) {
    // #296 / #922: stage-named terminal (verify/cmr/ship/online_review/merge/
    // cleanup) + failedPhase:"final". Decision parks leave failedStatus unset
    // and resolve to escalated via barrier stopSummary. Never a false success.
    return await finalize({
      ...(finalVerify.failedStatus !== undefined
        ? { failedStatus: finalVerify.failedStatus }
        : {}),
      failedPhase: "final",
      barrierLedgerStartIndex: preFinalLedgerLength,
    });
  }

  // Every barrier passed. finalize() derives "success" only if EVERY child
  // merged, else "incomplete" (a child failed / stayed blocked — not shippable).
  return await finalize({ barrierLedgerStartIndex: preFinalLedgerLength });
}
