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
  isGithubAuthFailure,
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
import {
  configureProgressBroadcast,
  emitLandingProgress,
  emitMergeProgress,
  emitShipProgress,
  emitWaveCloseProgress,
} from "../progressBroadcast.js";
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
  latestChildBoundAnswer,
  familyEscalationState,
  familyReviewLoopConvergedForHead,
  familyShippedRecordForReviewLoopResume,
  familyOpenShippedForOnlineReview,
  familyPostMergeCleanupForHead,
  familyPrMergedForHead,
  isMergedAccountingEntry,
  isValidChildDecisionParked,
  mergedSet,
  recordAdmissionSkipped,
  recordChildDecisionParked,
  recordMerged,
  recordReviewLoopConverged,
  unansweredChildEscalations,
} from "./ledger.js";
import { mergeChild } from "./merger.js";
import { reconcileFamilyLedger } from "./reconcile.js";
import {
  resolveFamilyShipPr,
  runFamilyOnlineReviewLoop,
  runVerifyCmr,
} from "./verifyCmr.js";
import {
  recordLandingActionFailure,
  runLandingAction,
} from "./landing.js";
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
  stageFailureStopSummary,
  syncStopSummaryToStageFailure,
  type FamilyStageFailureStatus,
} from "./familyTerminal.js";
import {
  type ChildSlice,
  type FamilyBackend,
  type FamilyChildDiagnostic,
  type FamilyChildEscalation,
  type FamilyChildResult,
  type FamilyLedgerEntry,
  type FamilyRunInput,
  type FamilyRunResult,
  type FamilyRunStatus,
  type IntegratedCmrPass,
} from "./types.js";
import type { VerifyCmrPhase, VerifyCmrResult } from "./verifyCmr.js";
import {
  finalizeFamilyTerminal,
  isLegacyEscalationWithoutTerminalCargo,
  replayPriorFamilyEscalation,
} from "./terminalFinalizer.js";
function filled(value: string | undefined): string | undefined {
  if (value == null) return undefined;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}
async function resolveFamilyCoderRecBody(
  backend: Backend,
  epicIssue: number,
): Promise<string | undefined> {
  try {
    const meta = await backend.fetchIssueMeta(epicIssue);
    if (typeof meta.body === "string" && meta.body.trim().length > 0) {
      return meta.body;
    }
    return undefined;
  } catch (err) {
    const metaMsg = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Coder-Rec body unreadable for epic #${epicIssue} (meta failed): ${metaMsg}`,
    );
  }
}
export type ApplyRelayBatonToRouteFn = (
  route: ResolvedModelRoute,
  baton: Pick<NextRelayBaton, "slug">,
  wallStep?: StepId,
  opts?: { readonly slots?: ReadonlyArray<ModelRouteSlot> },
) => ResolvedModelRoute;
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
export type FamilyQuotaWallPhase =
  | VerifyCmrPhase
  | "online_review"
  | "merge";
export function familyWallStepFromQuotaWait(opts: {
  readonly err: QuotaWaitForResetError;
  readonly phase: FamilyQuotaWallPhase;
}): StepId {
  const raw = opts.err.applied.ledgerEntry?.step;
  if (raw !== undefined && isAnyStepId(raw)) return raw;
  if (opts.phase === "online_review") return "S9";
  if (opts.phase === "merge") return "S1";
  if (opts.phase === "wave") return "S9";
  if (opts.phase === "correctness_checkpoint") return "S3";
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
  readonly relayHandoffsSoFar: number;
  readonly applyRelayBatonToRoute?: ApplyRelayBatonToRouteFn;
  readonly cmrPass?: "completeness" | "correctness";
  readonly wallHitBillingPools?: Set<BillingPoolId>;
}): Promise<FamilyQuotaWallDecision> {
  const buildParkResult = async (
    stopSummary: StopSummary,
    escalation?: { readonly reason: string; readonly diagnosis: string },
  ): Promise<FamilyQuotaWallDecision> => {
    const result = await finalizeFamilyTerminal({
      familyBackend: opts.familyBackend,
      epic: {
        issue: opts.epicIssue,
        children: opts.epicChildren,
        ...(opts.admissionSkipped !== undefined
          ? { admissionSkipped: opts.admissionSkipped }
          : {}),
      },
      epicIssue: opts.epicIssue,
      familyBase: opts.familyBase,
      ...(opts.familyHead !== undefined ? { familyHead: opts.familyHead } : {}),
      recordedResults: opts.recordedResults,
      familyStopSummary,
      intent: {
        kind: "parked",
        parkReason: "provider_degraded",
        escalationReason: escalation?.reason ?? stopSummary.summary,
        escalation: escalation ?? {
          reason: stopSummary.summary,
          diagnosis:
            stopSummary.repairHint ??
            "wait for provider quota reset, then re-feed the family run",
        },
        stopSummaryOverride: stopSummary,
      },
    });
    return {
      kind: "park",
      result,
    };
  };
  const currentPool = billingPoolFromQuotaPool(opts.err.pool);
  const wallStep = familyWallStepFromQuotaWait({
    err: opts.err,
    phase: opts.phase,
  });
  const parkStep: import("../types.js").SliceStepId = isStepId(wallStep)
    ? wallStep
    : "S7";
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
  const wallRef = opts.modelRoute.slots[wallSlots[0]!];
  const currentModelId =
    lookupCoderRosterEntry(wallRef)?.id ?? wallRef;
  opts.wallHitBillingPools?.add(currentPool);
  const pools = resolveRelayPools(
    currentPool,
    opts.err.disposition.resetAt,
    opts.relayPools,
    knownLiveBillingPoolsFromRoute(opts.modelRoute),
    opts.wallHitBillingPools,
  );
  const outcome = await parkOrRelayQuotaWall({
    step: parkStep,
    err: opts.err,
    ledger: inMemoryLedger,
    stateDir: undefined,
    sessionId: opts.runId,
    backend: opts.singleSliceBackend,
    resolveBranchHEAD: async () => {
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
    emitProgress: false,
  });
  if (outcome.kind === "park") {
    const stopSummary: StopSummary = outcome.result.stopSummary ?? {
      reason: "provider_degraded",
      summary: `quota wait for reset on pool ${opts.err.pool}`,
      repairHint:
        "wait for the provider quota to reset, then re-feed — family barrier re-enters from ledger truth",
    };
    await opts.familyBackend.appendFamilyLedger({
      status: "worker_dispatched",
      event: "worker_dispatched",
      workerStep: `quota_park:${opts.phase}`,
      reason: `quota wait for reset on pool ${opts.err.pool} at family ${opts.phase}`,
    });
    return buildParkResult(stopSummary);
  }
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
  readonly relayHandoffs: { count: number };
  readonly wallHitBillingPools?: Set<BillingPoolId>;
  readonly applyRelayBatonToRoute?: ApplyRelayBatonToRouteFn;
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
  readonly stage?: FamilyStageFailureStatus;
  readonly failedPhase?: VerifyCmrPhase;
  readonly familyHead?: string;
  readonly headMetadata?: StopSummary["metadata"];
  readonly barrierStopSummary?: StopSummary;
  readonly familyBase: string;
  readonly children: ReadonlyArray<FamilyChildResult>;
  readonly escalationReason?: string;
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
  if (input.status === "completed") {
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
  const stage =
    input.stage ??
    (input.barrierStopSummary !== undefined &&
    isFamilyStageFailureStatus(input.barrierStopSummary.reason)
      ? input.barrierStopSummary.reason
      : undefined);
  if (input.status === "failed" && stage !== undefined) {
    const synced = syncStopSummaryToStageFailure(stage, input.barrierStopSummary);
    if (input.barrierStopSummary == null && input.failedPhase !== undefined) {
      return stageFailureStopSummary({
        status: stage,
        summary: `family ${input.failedPhase} ${stage.replace(/_failed$/, "")} barrier failed`,
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
  if (input.status === "failed") {
    if (
      input.escalationReason !== undefined &&
      input.escalationReason.trim().length > 0
    ) {
      return {
        reason: "infra_failure",
        summary: input.escalationReason,
        repairHint: "inspect the family ledger and repair before rerun",
        ...(metadata !== undefined ? { metadata } : {}),
      };
    }
    const blocked = input.children
      .filter((child) => child.status !== "merged" && child.status !== "already_done")
      .map((child) => `#${child.issue}:${child.status}`)
      .join(", ");
    if (blocked.length > 0) {
      return {
        reason: "owning_issue_still_red",
        summary: `family run failed; unmerged children: ${blocked}`,
        repairHint: "repair or complete the listed child slices and rerun the family",
      };
    }
    return {
      reason: "infra_failure",
      summary: "family run failed",
      repairHint: "inspect the family ledger and repair before rerun",
      ...(metadata !== undefined ? { metadata } : {}),
    };
  }
  if (input.decisionGatePark === true || input.status === "parked") {
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
    summary: input.escalationReason ?? "family run failed",
    repairHint: "inspect the family ledger escalation entry and repair before rerun",
    ...(metadata !== undefined ? { metadata } : {}),
  };
}
function readChildDecisionEscalation(
  ledger: ReadonlyArray<LedgerEntry>,
): FamilyChildEscalation | undefined {
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
function escalatedChildStep(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): StepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step !== "S8" && isStepId(entry.step)) return entry.step;
  }
  return undefined;
}
const CHILD_ANSWER_FRESH_REDISPATCH =
  "child_answer_fresh_redispatch" as const;
function lastChildHandoffStatus(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): "completed" | "parked" | "failed" | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step !== "S8") continue;
    const status = entry.handoffStatus;
    if (status === "completed" || status === "parked" || status === "failed") {
      return status;
    }
  }
  return undefined;
}
function lastChildEscalationKind(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step !== "S8") continue;
    const kind = entry.escalationKind;
    if (typeof kind === "string" && kind.length > 0) return kind;
  }
  return undefined;
}
async function runChild(
  child: ChildSlice,
  singleSliceBackend: Backend,
  parentIssue: number,
  familyBase: string,
  familyChildIssues: ReadonlySet<number>,
  familyBackend: FamilyBackend,
  escalationAnswer?: EscalationAnswerPayload,
): Promise<FamilyChildResult> {
  let familyEscalationAnswer: EscalationAnswerPayload | undefined;
  if (escalationAnswer !== undefined) {
    const resumeState = await singleSliceBackend.findResumeState(child.issue);
    const forStep =
      resumeState !== undefined ? escalatedChildStep(resumeState.ledger) : undefined;
    const handoff =
      resumeState !== undefined
        ? lastChildHandoffStatus(resumeState.ledger)
        : undefined;
    const escKind =
      resumeState !== undefined
        ? lastChildEscalationKind(resumeState.ledger)
        : undefined;
    const canInjectInPlace =
      resumeState !== undefined &&
      forStep !== undefined &&
      handoff === "parked" &&
      escKind === "decision";
    const parkedSessionId =
      canInjectInPlace
        ? [...resumeState!.ledger]
            .reverse()
            .find((entry) => entry.step === forStep)?.sessionId
        : undefined;
    const answerSessionId =
      typeof escalationAnswer.sessionId === "string"
        ? escalationAnswer.sessionId.trim()
        : "";
    const staleAnswerForNewSession =
      canInjectInPlace &&
      typeof parkedSessionId === "string" &&
      parkedSessionId.length > 0 &&
      answerSessionId.length > 0 &&
      answerSessionId !== parkedSessionId;
    if (staleAnswerForNewSession) {
    } else if (
      canInjectInPlace &&
      typeof parkedSessionId === "string" &&
      parkedSessionId.length > 0
    ) {
      const alreadyConsumed = resumeState!.ledger.some(
        (e) =>
          e.event === "escalation_answered" &&
          e.forStep === forStep &&
          e.answer === escalationAnswer.answer,
      );
      if (!alreadyConsumed) {
        const answerEntry: PersistentLedgerEntry = {
          step: forStep!,
          sessionId: escalationAnswer.sessionId ?? parkedSessionId,
          prompt_hash: "family-answer",
          branchHEAD: resumeState!.worktree.branch,
          ts: new Date().toISOString(),
          event: "escalation_answered",
          forStep: forStep!,
          answer: escalationAnswer.answer,
          source: escalationAnswer.source ?? "human",
          ...(escalationAnswer.note !== undefined
            ? { note: escalationAnswer.note }
            : {}),
        } as PersistentLedgerEntry;
        await singleSliceBackend.writeLedger(answerEntry, resumeState!.stateDir);
      }
    } else {
      familyEscalationAnswer = escalationAnswer;
      await familyBackend.appendFamilyLedger({
        childIssue: child.issue,
        status: "worker_dispatched",
        event: "worker_dispatched",
        workerStep: CHILD_ANSWER_FRESH_REDISPATCH,
        reason: CHILD_ANSWER_FRESH_REDISPATCH,
      });
    }
  }
  const result = await runOrchestrator({
    issueNumber: child.issue,
    backend: singleSliceBackend,
    family: {
      parentIssue,
      familyBase,
      mergedBlockers: child.blockedBy.filter((b) => familyChildIssues.has(b)),
    },
    ...(familyEscalationAnswer !== undefined
      ? { familyEscalationAnswer }
      : {}),
  });
  if (result.status === "completed" && result.branch !== undefined) {
    return { issue: child.issue, status: "ran", branch: result.branch };
  }
  if (result.status === "parked") {
    const escalation = readChildDecisionEscalation(result.stepLedger);
    if (escalation !== undefined) {
      return { issue: child.issue, status: "escalated", escalation };
    }
  }
  return {
    issue: child.issue,
    status: "failed",
    failureCause: result.stopSummary?.summary,
  };
}
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
async function runLandingUnderFinalQuotaWall(input: {
  readonly familyBackend: FamilyBackend;
  readonly singleSliceBackend: Backend;
  readonly familyBase: string;
  readonly familyHead: string;
  readonly runId: string;
  readonly modelRoute: ResolvedModelRoute;
  readonly recordedResults: ReadonlyArray<FamilyChildResult>;
  readonly epicChildren: ReadonlyArray<ChildSlice>;
  readonly epicIssue: number;
  readonly relayHandoffs: { count: number };
  readonly wallHitBillingPools: Set<BillingPoolId>;
  readonly prUrl: string;
  readonly children: ReadonlyArray<FamilyChildResult>;
  readonly runRelayBilling?: FamilyRelayBillingBinding;
  readonly applyRelayBatonToRoute?: ApplyRelayBatonToRouteFn;
  readonly relayPools?: FamilyRunInput["relayPools"];
  readonly now?: () => Date;
  readonly admissionSkipped?: ReadonlyArray<{
    readonly issue: number;
    readonly reason: string;
    readonly message: string;
  }>;
}): Promise<
  | { readonly kind: "terminal"; readonly result: FamilyRunResult }
  | {
      readonly kind: "ok";
      readonly route: ResolvedModelRoute;
      readonly relayBilling: FamilyRelayBillingBinding | undefined;
    }
> {
  const landingBarrier = await runFamilyBarrierWithQuotaRelay({
    phase: "final",
    familyBackend: input.familyBackend,
    singleSliceBackend: input.singleSliceBackend,
    familyBase: input.familyBase,
    familyHead: input.familyHead,
    runId: input.runId,
    modelRoute: input.modelRoute,
    recordedResults: input.recordedResults,
    epicChildren: input.epicChildren,
    epicIssue: input.epicIssue,
    relayHandoffs: input.relayHandoffs,
    wallHitBillingPools: input.wallHitBillingPools,
    ...(input.runRelayBilling !== undefined
      ? { initialRelayBilling: input.runRelayBilling }
      : {}),
    ...(input.applyRelayBatonToRoute !== undefined
      ? { applyRelayBatonToRoute: input.applyRelayBatonToRoute }
      : {}),
    ...(input.relayPools !== undefined ? { relayPools: input.relayPools } : {}),
    ...(input.now !== undefined ? { now: input.now } : {}),
    ...(input.admissionSkipped !== undefined && input.admissionSkipped.length > 0
      ? { admissionSkipped: input.admissionSkipped }
      : {}),
    run: (route, relayBilling) =>
      ensureLandingForResume({
        familyBackend: input.familyBackend,
        familyBase: input.familyBase,
        runId: input.runId,
        familyHeadAfter: input.familyHead,
        prUrl: input.prUrl,
        familyIssue: input.epicIssue,
        resolvedRoute: route,
        children: input.children,
        ...(relayBilling !== undefined
          ? {
              billingPool: relayBilling.pool,
              billingPoolSlots: relayBilling.slots,
            }
          : {}),
        ...(input.admissionSkipped !== undefined &&
        input.admissionSkipped.length > 0
          ? { admissionSkipped: input.admissionSkipped }
          : {}),
      }),
  });
  if (landingBarrier.kind === "park") {
    return { kind: "terminal", result: landingBarrier.result };
  }
  if (landingBarrier.value !== undefined) {
    return { kind: "terminal", result: landingBarrier.value };
  }
  return {
    kind: "ok",
    route: landingBarrier.route,
    relayBilling: landingBarrier.relayBilling,
  };
}
async function ensureLandingForResume(input: {
  readonly familyBackend: FamilyBackend;
  readonly familyBase: string;
  readonly runId: string;
  readonly familyHeadAfter: string;
  readonly prUrl: string;
  readonly familyIssue: number;
  readonly resolvedRoute: ResolvedModelRoute;
  readonly children: ReadonlyArray<FamilyChildResult>;
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  readonly admissionSkipped?: ReadonlyArray<{
    readonly issue: number;
    readonly reason: string;
    readonly message: string;
  }>;
}): Promise<FamilyRunResult | undefined> {
  const landing = await runLandingAction({
    familyBackend: input.familyBackend,
    familyBase: input.familyBase,
    runId: input.runId,
    convergedHeadOid: input.familyHeadAfter,
    prUrl: input.prUrl,
    familyIssue: input.familyIssue,
    resolvedRoute: input.resolvedRoute,
    ...(input.billingPool !== undefined
      ? { billingPool: input.billingPool }
      : {}),
    ...(input.billingPoolSlots !== undefined
      ? { billingPoolSlots: input.billingPoolSlots }
      : {}),
  });
  if (landing.ok) {
    emitLandingProgress({
      epic: input.familyIssue,
      pr: input.prUrl,
    });
    return undefined;
  }
  const recorded = await recordLandingActionFailure(
    input.familyBackend,
    landing,
    { phase: "final", familyHeadAfter: input.familyHeadAfter },
  );
  if (recorded.kind === "park") {
    return await finalizeFamilyTerminal({
      familyBackend: input.familyBackend,
      epic: {
        issue: input.familyIssue,
        children: input.children.map((child) => ({
          issue: child.issue,
          blockedBy: [],
        })),
        ...(input.admissionSkipped !== undefined
          ? { admissionSkipped: input.admissionSkipped }
          : {}),
      },
      epicIssue: input.familyIssue,
      familyBase: input.familyBase,
      familyHead: input.familyHeadAfter,
      recordedResults: input.children,
      familyStopSummary,
      intent: {
        kind: "parked",
        parkReason: "decision_gate_park",
        escalationReason: recorded.stopSummary.summary,
        escalation: {
          reason: recorded.stopSummary.summary,
          diagnosis:
            recorded.stopSummary.repairHint ?? recorded.stopSummary.summary,
        },
        stopSummaryOverride: recorded.stopSummary,
      },
    });
  }
  return await finalizeFamilyTerminal({
    familyBackend: input.familyBackend,
    epic: {
      issue: input.familyIssue,
      children: input.children.map((child) => ({
        issue: child.issue,
        blockedBy: [],
      })),
      ...(input.admissionSkipped !== undefined
        ? { admissionSkipped: input.admissionSkipped }
        : {}),
    },
    epicIssue: input.familyIssue,
    familyBase: input.familyBase,
    familyHead: input.familyHeadAfter,
    recordedResults: input.children,
    familyStopSummary,
    intent: {
      kind: "failed",
      cause: "landing_worker_failed",
      failedPhase: "final",
      stopSummaryOverride: recorded.stopSummary,
    },
  });
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
    if (entry.blockingFindingIdentityKeys.length === 0) {
      processedPasses.add(pass);
      emptyAbortProcessedPasses.add(pass);
      continue;
    }
    processedPasses.add(pass);
    const keys = keysByPass[pass] ?? [];
    const seen = new Set(keys);
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
    if (entry.stopSummary == null) continue;
    if (phase !== undefined && entry.phase !== phase) continue;
    if (entry.status === "aborted") {
      return entry.stopSummary;
    }
    if (
      entry.status === "escalated" &&
      entry.event === "escalated" &&
      entry.escalationKind === "decision" &&
      entry.stopSummary.reason === "decision_gate_park"
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
export async function runFamily(
  input: FamilyRunInput,
): Promise<FamilyRunResult> {
  const { familyBackend, singleSliceBackend, familyBase } = input;
  const runId = mintRunId();
  {
    let familyLedgerDir: string | undefined;
    try {
      familyLedgerDir = familyBackend.resolveTelemetryDir?.({
        runId,
      } as import("../types.js").DispatchContext);
    } catch {
      familyLedgerDir = undefined;
    }
    if (familyLedgerDir !== undefined && familyLedgerDir.length > 0) {
      configureProgressBroadcast({
        ledgerDir: familyLedgerDir,
        epic: input.epic.issue,
      });
    }
  }
  const admitted = input.admittedRoute === undefined
    ? admitRouteFromEnv()
    : { kind: "ready" as const, route: input.admittedRoute.route };
  if (admitted.kind === "stop") {
    const diagnosis = admissionRouteFailureDiagnosis(admitted.escalation.diagnosis);
    const stopSummary = infraFailureStopSummary({
      summary: `${admitted.escalation.reason}: ${diagnosis}`,
      repairHint:
        "repair ORCHESTRATOR_ROUTE preset or issue Coder-Rec staffing before rerun",
    });
    return await finalizeFamilyTerminal({
      familyBackend,
      epic: input.epic,
      epicIssue: input.epic.issue,
      familyBase,
      recordedResults: [],
      familyStopSummary,
      intent: {
        kind: "failed",
        cause: "route_config_invalid",
        escalation: {
          reason: admitted.escalation.reason,
          diagnosis,
        },
        residualSkipReason: "startup_preflight_failed",
        stopSummaryOverride: stopSummary,
      },
    });
  }
  let modelRoute: ResolvedModelRoute = admitted.route;
  if (input.admittedRoute === undefined && typeof singleSliceBackend.smokeModelRoute !== "function") {
    const reason =
      "route smoke executor is required before family dispatch; backend did not provide smokeModelRoute";
    const stopSummary = infraFailureStopSummary({
      summary: reason,
      repairHint: "provide a real model×pipe smoke executor before dispatching family workers",
    });
    return await finalizeFamilyTerminal({
      familyBackend,
      epic: input.epic,
      epicIssue: input.epic.issue,
      familyBase,
      recordedResults: [],
      familyStopSummary,
      intent: {
        kind: "failed",
        cause: "route_smoke_failed",
        escalation: { reason: "startup route smoke failure", diagnosis: reason },
        residualSkipReason: "startup_preflight_failed",
        stopSummaryOverride: stopSummary,
      },
    });
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
    const stopSummary = infraFailureStopSummary({
      summary: `route smoke failed: ${reason}`,
      repairHint: "repair the selected model×pipe tool smoke before dispatching family workers",
    });
    return await finalizeFamilyTerminal({
      familyBackend,
      epic: input.epic,
      epicIssue: input.epic.issue,
      familyBase,
      recordedResults: [],
      familyStopSummary,
      intent: {
        kind: "failed",
        cause: "route_smoke_failed",
        escalation: {
          reason: "startup route smoke failure",
          diagnosis: `route smoke failed: ${reason}`,
        },
        residualSkipReason: "startup_preflight_failed",
        stopSummaryOverride: stopSummary,
      },
    });
  }
  const degradation = input.admittedRoute ?? degradeOptionalRouteSmokeFailures(modelRoute);
  modelRoute = degradation.route;
  const smokeFailure = routeSmokeFailure(modelRoute, Date.now(), undefined, currentCliVersions);
  if (smokeFailure !== undefined) {
    const stopSummary = infraFailureStopSummary({
      summary: smokeFailure,
      repairHint: "rerun the route smoke or repair the selected model×pipe",
    });
    return await finalizeFamilyTerminal({
      familyBackend,
      epic: input.epic,
      epicIssue: input.epic.issue,
      familyBase,
      recordedResults: [],
      familyStopSummary,
      intent: {
        kind: "failed",
        cause: "route_smoke_failed",
        escalation: {
          reason: "startup route smoke failure",
          diagnosis: smokeFailure,
        },
        residualSkipReason: "startup_preflight_failed",
        stopSummaryOverride: stopSummary,
      },
    });
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
  let activeRoute: ResolvedModelRoute = modelRoute;
  let runRelayBilling: FamilyRelayBillingBinding | undefined;
  const relayHandoffs = { count: 0 };
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
      const isLegacyCargoLess =
        isLegacyEscalationWithoutTerminalCargo(escalation);
      if (isLegacyCargoLess) {
        const isDecisionPark =
          escalation.escalationKind === "decision" && answer === undefined;
        const reason =
          typeof escalation.reason === "string" &&
          escalation.reason.trim().length > 0
            ? escalation.reason
            : "family escalation is not answered";
        return await finalizeFamilyTerminal({
          familyBackend,
          epic: input.epic,
          epicIssue: input.epic.issue,
          familyBase,
          familyHead: escalation.familyHeadAfter,
          recordedResults: [],
          familyStopSummary,
          intent: isDecisionPark
            ? {
                kind: "parked",
                parkReason: "decision_gate_park",
                escalationReason: reason,
                escalation: {
                  reason,
                  diagnosis:
                    "Legacy family decision escalation has no terminal replay cargo and no later valid answer.",
                },
              }
            : {
                kind: "failed",
                cause: "runner_internal_error",
                escalationReason: reason,
                escalation: {
                  reason,
                  diagnosis:
                    "Legacy family failure escalation has no terminal replay cargo.",
                },
              },
        });
      }
      return await replayPriorFamilyEscalation({
        epicIssue: input.epic.issue,
        familyBase,
        escalation,
        admissionSkipped: input.epic.admissionSkipped,
      });
    }
  }
  const escalationAnswer = priorEscalation?.answer;
  let epic = input.epic;
  if (input.refetchEpic !== undefined) {
    try {
      epic = await input.refetchEpic();
    } catch (err) {
      const diagnosis = err instanceof Error ? err.message : String(err);
      if (err instanceof Error && err.name === "FamilyRootBlockerError") {
        const stopSummary = decisionGateParkStopSummary({
          summary: diagnosis,
          repairHint:
            "close or unblock the root epic blocked_by dependencies, then re-feed",
        });
        return await finalizeFamilyTerminal({
          familyBackend,
          epic: input.epic,
          epicIssue: input.epic.issue,
          familyBase,
          recordedResults: [],
          familyStopSummary,
          intent: {
            kind: "parked",
            parkReason: "decision_gate_park",
            escalationReason: diagnosis,
            escalation: { reason: diagnosis, diagnosis },
            residualSkipReason: "refetch_failed",
            stopSummaryOverride: stopSummary,
          },
        });
      }
      if (isGithubAuthFailure(err)) {
        const stopSummary = decisionGateParkStopSummary({
          summary: `GitHub authentication required: ${diagnosis}`,
          repairHint:
            "run `gh auth login` (or restore GH_TOKEN) on the host, then re-feed",
        });
        return await finalizeFamilyTerminal({
          familyBackend,
          epic: input.epic,
          epicIssue: input.epic.issue,
          familyBase,
          recordedResults: [],
          familyStopSummary,
          intent: {
            kind: "parked",
            parkReason: "decision_gate_park",
            escalationReason: `GitHub authentication required: ${diagnosis}`,
            escalation: {
              reason: "GitHub authentication required",
              diagnosis,
            },
            residualSkipReason: "refetch_failed",
            stopSummaryOverride: stopSummary,
          },
        });
      }
      const metaStop = infraFailureStopSummary({
        summary: diagnosis,
        repairHint: "repair GitHub metadata access and rerun",
      });
      return await finalizeFamilyTerminal({
        familyBackend,
        epic: input.epic,
        epicIssue: input.epic.issue,
        familyBase,
        recordedResults: [],
        familyStopSummary,
        intent: {
          kind: "failed",
          cause: "issue_metadata_unavailable",
          escalation: { reason: "issue metadata unavailable", diagnosis },
          residualSkipReason: "refetch_failed",
          stopSummaryOverride: metaStop,
        },
      });
    }
  }
  const familyChildIssues = new Set(epic.children.map((c) => c.issue));
  const parkedChildAnswers = new Map<number, EscalationAnswerPayload>();
  const stillUnanswered = new Set(
    unansweredChildEscalations(initialFamilyLedger).map((e) => e.childIssue),
  );
  {
    const latestParkByChild = new Map<
      number,
      FamilyLedgerEntry & { readonly childIssue: number }
    >();
    for (let i = initialFamilyLedger.length - 1; i >= 0; i--) {
      const entry = initialFamilyLedger[i]!;
      if (!isValidChildDecisionParked(entry)) continue;
      if (!latestParkByChild.has(entry.childIssue)) {
        latestParkByChild.set(entry.childIssue, entry);
      }
    }
    for (const [childIssue] of latestParkByChild) {
      if (stillUnanswered.has(childIssue)) continue;
      const answer = childEscalationAnswer(initialFamilyLedger, childIssue);
      if (answer !== undefined) parkedChildAnswers.set(childIssue, answer);
    }
    const ledgerMerged = mergedSet(initialFamilyLedger);
    for (const child of epic.children) {
      if (ledgerMerged.has(child.issue)) continue;
      if (parkedChildAnswers.has(child.issue)) continue;
      const bound = latestChildBoundAnswer(initialFamilyLedger, child.issue);
      if (bound !== undefined) parkedChildAnswers.set(child.issue, bound);
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
  const verifyCmr = input.verifyCmr ?? runVerifyCmr;
  const childResults: FamilyChildResult[] = [];
  const waveDiagnostics: FamilyChildDiagnostic[] = [];
  let familyHead: string | undefined;
  const attachDiagnostics = <T extends FamilyRunResult>(result: T): T => {
    if (waveDiagnostics.length === 0) return result;
    return { ...result, diagnostics: [...waveDiagnostics] };
  };
  const finalize = async (
    opts?: {
      readonly failedStatus?: FamilyStageFailureStatus;
      readonly failedPhase?: VerifyCmrPhase;
      readonly barrierLedgerStartIndex?: number;
    },
  ): Promise<FamilyRunResult> => {
    const verifyFailedPhase = opts?.failedPhase;
    const barrierLedgerStartIndex = opts?.barrierLedgerStartIndex ?? 0;
    const familyLedger = await familyBackend.readFamilyLedger();
    const barrierStopSummary =
      opts?.failedStatus !== undefined || verifyFailedPhase !== undefined
        ? (latestAbortedStopSummary(
            familyLedger,
            verifyFailedPhase,
            barrierLedgerStartIndex,
          ) ??
          latestAbortedStopSummary(familyLedger, undefined, barrierLedgerStartIndex))
        : undefined;
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
    const materialSuccessStopSummary =
      latestSuccessfulFinalShippedStopSummary(
        familyLedger,
        barrierLedgerStartIndex,
      ) ??
      latestSuccessfulFinalCmrStopSummary(familyLedger, barrierLedgerStartIndex);
    return attachDiagnostics(await finalizeFamilyTerminal({
      familyBackend,
      epic,
      epicIssue: epic.issue,
      familyBase,
      familyHead,
      recordedResults: childResults,
      familyStopSummary,
      intent: {
        kind: "auto",
        ...(opts?.failedStatus !== undefined
          ? { failedStatus: opts.failedStatus }
          : {}),
        ...(verifyFailedPhase !== undefined
          ? { failedPhase: verifyFailedPhase }
          : {}),
        ...(barrierStopSummary !== undefined
          ? { barrierStopSummary }
          : {}),
        headMetadata,
        ...(materialSuccessStopSummary !== undefined
          ? { completedStopSummaryOverride: materialSuccessStopSummary }
          : {}),
      },
    }));
  };
  if (input.reconcileGit !== undefined) {
    logDriverStage("reconcile", `family base ${input.familyBase}`);
    const ledger = await familyBackend.readFamilyLedger();
    const plan = await reconcileFamilyLedger(
      ledger,
      epic.children,
      input.reconcileGit,
    );
    if (plan.escalate) {
      const recordedFromPlan: FamilyChildResult[] = epic.children
        .filter((c) => plan.merged.has(c.issue))
        .map((c) => ({ issue: c.issue, status: "already_done" as const }));
      const reason =
        "family reconcile found the live family-base HEAD inconsistent with the ledger";
      return await finalizeFamilyTerminal({
        familyBackend,
        epic,
        epicIssue: epic.issue,
        familyBase,
        familyHead: plan.liveHead,
        recordedResults: recordedFromPlan,
        familyStopSummary,
        intent: {
          kind: "failed",
          cause: "runner_internal_error",
          escalationReason: reason,
          residualSkipReason: "reconcile_inconsistent",
          persistDurable: true,
        },
      });
    }
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
    if (plan.merged.size > 0) familyHead = plan.liveHead;
  }
  type PendingBarrier = ReturnType<typeof runFamilyBarrierWithQuotaRelay<VerifyCmrResult>>;
  let pendingCorrectnessCheckpoint: PendingBarrier | undefined;
  const awaitPendingCorrectnessCheckpoint = async (opts?: {
    readonly beforeFailFinalize?: () => void;
  }): Promise<FamilyRunResult | undefined> => {
    if (pendingCorrectnessCheckpoint === undefined) return undefined;
    const barrier = await pendingCorrectnessCheckpoint;
    pendingCorrectnessCheckpoint = undefined;
    if (barrier.kind === "park") {
      const settledByIssue = new Map(childResults.map((child) => [child.issue, child]));
      return attachDiagnostics({
        ...barrier.result,
        children: barrier.result.children.map(
          (child) => settledByIssue.get(child.issue) ?? child,
        ),
      });
    }
    activeRoute = barrier.route;
    if (barrier.relayBilling !== undefined) {
      runRelayBilling = barrier.relayBilling;
    }
    const value = barrier.value;
    if (!value.ok) {
      opts?.beforeFailFinalize?.();
      return await finalize({
        ...(value.failedStatus !== undefined
          ? { failedStatus: value.failedStatus }
          : {}),
        failedPhase: "correctness_checkpoint",
      });
    }
    return undefined;
  };
  const fireCorrectnessCheckpoint = (): void => {
    const checkpointHead = familyHead;
    pendingCorrectnessCheckpoint = runFamilyBarrierWithQuotaRelay({
      phase: "correctness_checkpoint",
      familyBackend,
      singleSliceBackend,
      familyBase,
      familyHead: checkpointHead,
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
      run: async (route, relayBilling) =>
        verifyCmr({
          phase: "correctness_checkpoint",
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
          llmResolvedChildren: await llmResolvedChildren(familyBackend),
          familyHeadAfter: checkpointHead,
          familyIssue: epic.issue,
          ...(declaredModuleContext !== undefined
            ? { moduleContext: declaredModuleContext }
            : {}),
        }),
    });
  };
  const attempted = new Set<number>();
  for (;;) {
    const merged = await currentMerged(familyBackend);
    const wave = selectWave(epic.children, merged).filter(
      (c) => !attempted.has(c.issue) && !stillUnanswered.has(c.issue),
    );
    if (wave.length === 0) {
      const icStop = await awaitPendingCorrectnessCheckpoint();
      if (icStop !== undefined) return icStop;
      const residual = epic.children.filter(
        (c) => !merged.has(c.issue) && !stillUnanswered.has(c.issue),
      );
      if (residual.length > 0) {
        try {
          assertAcyclic(residual);
        } catch (err) {
          if (!(err instanceof DependencyCycleError)) throw err;
          const escalationReason = `dependency_cycle: ${err.cycle.map((n) => `#${n}`).join(" → ")}`;
          return attachDiagnostics(await finalizeFamilyTerminal({
            familyBackend,
            epic,
            epicIssue: epic.issue,
            familyBase,
            familyHead,
            recordedResults: childResults,
            familyStopSummary,
            intent: {
              kind: "failed",
              cause: "dependency_cycle",
              escalationReason,
              escalation: { reason: escalationReason, diagnosis: err.message },
              residualSkipReason: "dependency_cycle_residual",
              persistDurable: true,
            },
          }));
        }
      }
      break;
    }
    logDriverStage(
      "dispatch",
      `wave n=${wave.length}`,
      {
        issues: wave.map((c) => c.issue),
        epic: epic.issue,
      },
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
    let waveMergedAny = false;
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
    {
      drainRemainingWaveSiblings();
      const icStopBeforeMerge = await awaitPendingCorrectnessCheckpoint({
        beforeFailFinalize: drainRemainingWaveSiblings,
      });
      if (icStopBeforeMerge !== undefined) return icStopBeforeMerge;
    }
    for (const r of ran) {
      if (r.status === "ran" && r.branch !== undefined) {
        drainRemainingWaveSiblings();
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
          return attachDiagnostics(mergeBarrier.result);
        }
        activeRoute = mergeBarrier.route;
        if (mergeBarrier.relayBilling !== undefined) {
          runRelayBilling = mergeBarrier.relayBilling;
        }
        const mergeResult = mergeBarrier.value;
        if (mergeResult.escalation !== undefined) {
          familyHead = mergeResult.familyHead;
          childResults.push({ issue: r.issue, status: "failed", branch: r.branch });
          drainRemainingWaveSiblings();
          const escalation = mergeResult.escalation;
          return attachDiagnostics(
            await finalizeFamilyTerminal({
              familyBackend,
              epic,
              epicIssue: epic.issue,
              familyBase,
              familyHead,
              recordedResults: childResults,
              familyStopSummary,
              intent: {
                kind: "merger_decision",
                mergerIssue: r.issue,
                reason: escalation.reason,
                diagnosis: escalation.diagnosis ?? escalation.reason,
              },
            }),
          );
        }
        if (mergeResult.conflicted === true) {
          familyHead = mergeResult.familyHead;
          const detail =
            typeof mergeResult.reason === "string" &&
            mergeResult.reason.trim().length > 0
              ? mergeResult.reason.trim()
              : "conflict unresolved on the family base";
          const cause =
            detail === "conflict unresolved on the family base"
              ? `merger_worker left child #${r.issue} ${detail}`
              : `merger_worker left child #${r.issue} conflict unresolved: ${detail}`;
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
        waveMergedAny = true;
        childResults.push({ issue: r.issue, status: "merged", branch: r.branch });
        emitMergeProgress({
          issue: r.issue,
          epic: epic.issue,
          childHead: mergeResult.familyHead,
        });
      } else {
        recordWaveSibling(r);
      }
    }
    emitWaveCloseProgress({
      epic: epic.issue,
      issues: ran.map((r) => r.issue),
    });
    const escalatedChildren = ran.filter(
      (r): r is FamilyChildResult & { escalation: FamilyChildEscalation } =>
        r.status === "escalated" && r.escalation !== undefined,
    );
    if (escalatedChildren.length > 0) {
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
        stillUnanswered.add(child.issue);
      }
      if (ran.some((r) => r.status === "failed")) {
        return await finalize();
      }
      if (!waveMergedAny) {
        return await finalize();
      }
    }
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
      return await finalize({
        failedStatus: waveVerify.failedStatus ?? "verify_failed",
        failedPhase: "wave",
      });
    }
    if (waveMergedAny) {
      fireCorrectnessCheckpoint();
    }
  }
  {
    const icStop = await awaitPendingCorrectnessCheckpoint();
    if (icStop !== undefined) return icStop;
  }
  {
    const liveLedger = await familyBackend.readFamilyLedger();
    const unansweredNow = unansweredChildEscalations(liveLedger).filter((row) =>
      familyChildIssues.has(row.childIssue),
    );
    const hasFailed = childResults.some((r) => r.status === "failed");
    if (unansweredNow.length > 0 || hasFailed) {
      return attachDiagnostics(
        await finalizeFamilyTerminal({
          familyBackend,
          epic,
          epicIssue: epic.issue,
          familyBase,
          familyHead,
          recordedResults: childResults,
          familyStopSummary,
          intent: {
            kind: "auto",
            residualSkipReason: "unanswered_sibling_park_residual",
            persistFailureWithParks: unansweredNow.length > 0 && hasFailed,
          },
        }),
      );
    }
  }
  const mergedNow = await currentMerged(familyBackend);
  if (!epic.children.every((c) => mergedNow.has(c.issue))) {
    return await finalize();
  }
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
    const recorded = epic.children
      .filter((c) => ledgerMerged.has(c.issue))
      .map((c) => ({ issue: c.issue, status: "already_done" as const }));
    const children: FamilyChildResult[] = recorded;
    familyHead = preFinalFamilyHead;
    const landingWall = await runLandingUnderFinalQuotaWall({
      familyBackend,
      singleSliceBackend,
      familyBase,
      familyHead: preFinalFamilyHead!,
      runId,
      modelRoute: activeRoute,
      recordedResults: children,
      epicChildren: epic.children,
      epicIssue: epic.issue,
      relayHandoffs,
      wallHitBillingPools,
      prUrl: convergedRecord.pr,
      children,
      ...(runRelayBilling !== undefined
        ? { runRelayBilling }
        : {}),
      ...(applyRelayOverride !== undefined
        ? { applyRelayBatonToRoute: applyRelayOverride }
        : {}),
      ...(input.relayPools !== undefined ? { relayPools: input.relayPools } : {}),
      ...(input.now !== undefined ? { now: input.now } : {}),
      ...(Array.isArray(epic.admissionSkipped) && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    });
    if (landingWall.kind === "terminal") return landingWall.result;
    activeRoute = landingWall.route;
    if (landingWall.relayBilling !== undefined) {
      runRelayBilling = landingWall.relayBilling;
    }
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
    return await finalizeFamilyTerminal({
      familyBackend,
      epic,
      epicIssue: epic.issue,
      familyBase,
      familyHead,
      recordedResults: children,
      familyStopSummary,
      intent: {
        kind: "completed",
        stopSummaryOverride: alreadyDoneSummary,
      },
    });
  }
  const shippedRecord = familyShippedRecordForReviewLoopResume(
    preFinalLedger,
    preFinalFamilyHead,
  );
  if (shippedRecord !== undefined) {
    emitShipProgress({
      epic: epic.issue,
      pr: shippedRecord.pr,
      familyHead: shippedRecord.familyHeadAfter,
    });
    const ledgerMerged = await currentMerged(familyBackend);
    const recordedShipped = epic.children
      .filter((child) => ledgerMerged.has(child.issue))
      .map((child) => ({ issue: child.issue, status: "already_done" as const }));
    const children: FamilyChildResult[] = recordedShipped;
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
      if (terminal.status !== "parked") {
        await familyBackend.appendFamilyLedger({
          status: "aborted",
          event: "aborted",
          phase: "final",
          reason: terminal.stopSummary.summary,
          familyHeadAfter: preFinalFamilyHead,
          stopSummary: terminal.stopSummary,
        });
      }
      if (terminal.status === "parked") {
        return await finalizeFamilyTerminal({
          familyBackend,
          epic,
          epicIssue: epic.issue,
          familyBase,
          familyHead: preFinalFamilyHead,
          recordedResults: children,
          familyStopSummary,
          intent: {
            kind: "parked",
            parkReason: "decision_gate_park",
            escalationReason: terminal.stopSummary.summary,
            escalation: {
              reason: terminal.stopSummary.summary,
              diagnosis:
                terminal.stopSummary.repairHint ?? terminal.stopSummary.summary,
            },
            persistFamilyDecision: true,
            durablePhase: "final",
            stopSummaryOverride: terminal.stopSummary,
          },
        });
      }
      return await finalizeFamilyTerminal({
        familyBackend,
        epic,
        epicIssue: epic.issue,
        familyBase,
        familyHead: preFinalFamilyHead,
        recordedResults: children,
        familyStopSummary,
        intent: {
          kind: "failed",
          cause: terminal.cause,
          failedPhase: "final",
          stopSummaryOverride: terminal.stopSummary,
        },
      });
    }
    const convergedHead =
      (await readCurrentFamilyHead(familyBackend, familyBase)) ??
      preFinalFamilyHead ??
      shippedRecord.familyHeadAfter;
    // #1145: Landing + converged marker bind the currently open PR, not a stale
    // shipped-ledger handle after replacement/re-open (thin identity only).
    const landingPrUrl =
      resolveFamilyShipPr(familyBase) ?? shippedRecord.pr;
    await recordReviewLoopConverged(familyBackend, {
      pr: landingPrUrl,
      familyHeadAfter: convergedHead,
      ...(shippedRecord.stopSummary !== undefined
        ? { stopSummary: shippedRecord.stopSummary }
        : {}),
    });
    familyHead = convergedHead;
    const landingWall = await runLandingUnderFinalQuotaWall({
      familyBackend,
      singleSliceBackend,
      familyBase,
      familyHead: convergedHead,
      runId,
      modelRoute: activeRoute,
      recordedResults: children,
      epicChildren: epic.children,
      epicIssue: epic.issue,
      relayHandoffs,
      wallHitBillingPools,
      prUrl: landingPrUrl,
      children,
      ...(runRelayBilling !== undefined
        ? { runRelayBilling }
        : {}),
      ...(applyRelayOverride !== undefined
        ? { applyRelayBatonToRoute: applyRelayOverride }
        : {}),
      ...(input.relayPools !== undefined ? { relayPools: input.relayPools } : {}),
      ...(input.now !== undefined ? { now: input.now } : {}),
      ...(epic.admissionSkipped !== undefined && epic.admissionSkipped.length > 0
        ? { admissionSkipped: epic.admissionSkipped }
        : {}),
    });
    if (landingWall.kind === "terminal") return landingWall.result;
    activeRoute = landingWall.route;
    if (landingWall.relayBilling !== undefined) {
      runRelayBilling = landingWall.relayBilling;
    }
    const stopSummary: StopSummary = {
      reason: "already_done",
      summary:
        "family review loop resumed from the shipped checkpoint and converged",
    };
    return await finalizeFamilyTerminal({
      familyBackend,
      epic,
      epicIssue: epic.issue,
      familyBase,
      familyHead,
      recordedResults: children,
      familyStopSummary,
      intent: {
        kind: "completed",
        stopSummaryOverride: stopSummary,
      },
    });
  }
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
      const ledgerNow = await familyBackend.readFamilyLedger();
      const barrierHead =
        (await readCurrentFamilyHead(familyBackend, familyBase)) ?? familyHead;
      const openShipped = familyOpenShippedForOnlineReview(
        ledgerNow,
        barrierHead,
      );
      if (openShipped !== undefined) {
        const ledgerMerged = await currentMerged(familyBackend);
        const recordedOpen: FamilyChildResult[] = epic.children
          .filter(
            (child) =>
              childResults.some(
                (c) => c.issue === child.issue && c.status === "merged",
              ) || ledgerMerged.has(child.issue),
          )
          .map((child) => ({
            issue: child.issue,
            status: ledgerMerged.has(child.issue)
              ? ("already_done" as const)
              : ("merged" as const),
          }));
        const openChildren = recordedOpen;
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
          if (terminal.status !== "parked") {
            await familyBackend.appendFamilyLedger({
              status: "aborted",
              event: "aborted",
              phase: "final",
              reason: terminal.stopSummary.summary,
              familyHeadAfter: barrierHead,
              stopSummary: terminal.stopSummary,
            });
          }
          openShippedTerminal =
            terminal.status === "parked"
              ? await finalizeFamilyTerminal({
                  familyBackend,
                  epic,
                  epicIssue: epic.issue,
                  familyBase,
                  familyHead: barrierHead,
                  recordedResults: openChildren,
                  familyStopSummary,
                  intent: {
                    kind: "parked",
                    parkReason: "decision_gate_park",
                    escalationReason: terminal.stopSummary.summary,
                    escalation: {
                      reason: terminal.stopSummary.summary,
                      diagnosis:
                        terminal.stopSummary.repairHint ??
                        terminal.stopSummary.summary,
                    },
                    persistFamilyDecision: true,
                    durablePhase: "final",
                    stopSummaryOverride: terminal.stopSummary,
                  },
                })
              : await finalizeFamilyTerminal({
                  familyBackend,
                  epic,
                  epicIssue: epic.issue,
                  familyBase,
                  familyHead: barrierHead,
                  recordedResults: openChildren,
                  familyStopSummary,
                  intent: {
                    kind: "failed",
                    cause: terminal.cause,
                    failedPhase: "final",
                    stopSummaryOverride: terminal.stopSummary,
                  },
                });
          return { ok: false, ran: true };
        }
        const convergedHead =
          (await readCurrentFamilyHead(familyBackend, familyBase)) ??
          openShipped.familyHeadAfter;
        // #1145: Landing + converged marker bind the currently open PR, not a
        // stale shipped-ledger handle after replacement/re-open.
        const landingPrUrl =
          resolveFamilyShipPr(familyBase) ?? openShipped.pr;
        await recordReviewLoopConverged(familyBackend, {
          pr: landingPrUrl,
          familyHeadAfter: convergedHead,
          ...(openShipped.stopSummary !== undefined
            ? { stopSummary: openShipped.stopSummary }
            : {}),
        });
        const landingBlocked = await ensureLandingForResume({
          familyBackend,
          familyBase,
          runId,
          familyHeadAfter: convergedHead,
          prUrl: landingPrUrl,
          familyIssue: epic.issue,
          resolvedRoute: route,
          children: openChildren,
          ...(relayBilling !== undefined
            ? {
                billingPool: relayBilling.pool,
                billingPoolSlots: relayBilling.slots,
              }
            : {}),
          ...(epic.admissionSkipped !== undefined &&
          epic.admissionSkipped.length > 0
            ? { admissionSkipped: epic.admissionSkipped }
            : {}),
        });
        if (landingBlocked !== undefined) {
          openShippedTerminal = landingBlocked;
          return { ok: false, ran: true };
        }
        openShippedTerminal = await finalizeFamilyTerminal({
          familyBackend,
          epic,
          epicIssue: epic.issue,
          familyBase,
          familyHead: convergedHead,
          recordedResults: openChildren,
          familyStopSummary,
          intent: {
            kind: "completed",
            stopSummaryOverride: {
              reason: "already_done",
              summary:
                "family review loop resumed from the open-shipped checkpoint and converged",
            },
          },
        });
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
  if (openShippedTerminal !== undefined) {
    familyHead = openShippedTerminal.familyHead ?? familyHead;
    return openShippedTerminal;
  }
  if (!finalVerify.ok) {
    return await finalize({
      ...(finalVerify.failedStatus !== undefined
        ? { failedStatus: finalVerify.failedStatus }
        : {}),
      failedPhase: "final",
      barrierLedgerStartIndex: preFinalLedgerLength,
    });
  }
  return await finalize({ barrierLedgerStartIndex: preFinalLedgerLength });
}
