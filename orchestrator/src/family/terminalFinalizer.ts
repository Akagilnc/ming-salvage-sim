/**
 * #1125 owner A — sole family terminal finalizer (deep module).
 *
 * Owns: required ledger read (loud fail), epic-order child normalization,
 * A-class failure > B-class park selection, single public result/stopSummary,
 * durable authority write, progress emission after durable write.
 *
 * Callers pass facts + terminal intent only — never prebuilt children, never
 * pre-selected status, never deferChildNormalize coordination flags.
 */

import { emitExitProgress } from "../progressBroadcast.js";
import {
  infraFailureStopSummary,
  type StopSummary,
} from "../stopSummary.js";
import type { Escalation } from "../types.js";
import {
  failedFamilyResult,
  type ChildSlice,
  type FamilyBackend,
  type FamilyChildEscalation,
  type FamilyChildResult,
  type FamilyEpic,
  type FamilyLedgerEntry,
  type FamilyRunResult,
  type FamilyRunStatus,
} from "./types.js";
import {
  isValidChildDecisionParked,
  mergedSet,
  recordFamilyEscalated,
  unansweredChildEscalations,
} from "./ledger.js";
import type { VerifyCmrPhase } from "./verifyCmr.js";
import type { FamilyStageFailureStatus } from "./familyTerminal.js";
import type { PublicFailedCause } from "../publicResult.js";

/** Machine-readable residual-skip reason tokens (log surface only). */
export type FamilySkipReason =
  | "not_scheduled_this_invocation"
  | "unanswered_sibling_park_residual"
  | "startup_preflight_failed"
  | "refetch_failed"
  | "reconcile_inconsistent"
  | "dependency_cycle_residual";

function skippedChild(
  issue: number,
  reason: FamilySkipReason,
): FamilyChildResult {
  console.warn(`family child #${issue} skipped: ${reason}`);
  return { issue, status: "skipped" };
}

function escalationFromChildParkRow(
  row: FamilyLedgerEntry & { readonly childIssue: number },
): FamilyChildEscalation {
  return {
    reason: row.reason ?? "(no reason recorded)",
    diagnosis:
      row.diagnosis ??
      "Append an escalation_answered ledger row carrying this childIssue to reopen the parked child.",
    escalationKind: "decision",
    ...(typeof row.sessionId === "string" && row.sessionId.length > 0
      ? { sessionId: row.sessionId }
      : {}),
  };
}

/**
 * Encode terminal children for durable stopSummary.metadata.trackedStatus
 * (existing string[] field — no schema widen). Replay reconstructs cargo.
 */
export function encodeTerminalChildrenCargo(
  children: ReadonlyArray<FamilyChildResult>,
): ReadonlyArray<string> {
  return children.map((c) =>
    JSON.stringify({
      issue: c.issue,
      status: c.status,
      ...(c.branch !== undefined ? { branch: c.branch } : {}),
      ...(c.failureCause !== undefined ? { failureCause: c.failureCause } : {}),
      ...(c.escalation !== undefined ? { escalation: c.escalation } : {}),
    }),
  );
}

export function decodeTerminalChildrenCargo(
  tracked: ReadonlyArray<string> | undefined,
): FamilyChildResult[] | undefined {
  if (tracked === undefined || tracked.length === 0) return undefined;
  const out: FamilyChildResult[] = [];
  for (const raw of tracked) {
    try {
      const parsed = JSON.parse(raw) as FamilyChildResult;
      if (
        typeof parsed.issue === "number" &&
        typeof parsed.status === "string"
      ) {
        out.push(parsed);
      } else {
        return undefined;
      }
    } catch {
      return undefined;
    }
  }
  return out.length > 0 ? out : undefined;
}

/** Epic-order remount: recorded > merged > admitted unanswered park > vocal skip. */
export function remountDecisionParkChildren(opts: {
  readonly epicChildren: ReadonlyArray<ChildSlice>;
  readonly recordedResults: ReadonlyArray<FamilyChildResult>;
  readonly ledgerMerged: ReadonlySet<number>;
  readonly parkedEscalations?: ReadonlyMap<number, FamilyChildEscalation>;
  readonly residualSkipReason?: FamilySkipReason;
}): FamilyChildResult[] {
  const residualReason =
    opts.residualSkipReason ?? "unanswered_sibling_park_residual";
  const recorded = new Map(opts.recordedResults.map((c) => [c.issue, c]));
  return opts.epicChildren.map((c) => {
    const rec = recorded.get(c.issue);
    if (rec !== undefined) return rec;
    if (opts.ledgerMerged.has(c.issue)) {
      return { issue: c.issue, status: "already_done" as const };
    }
    const escalation = opts.parkedEscalations?.get(c.issue);
    if (escalation !== undefined) {
      return { issue: c.issue, status: "escalated" as const, escalation };
    }
    return skippedChild(c.issue, residualReason);
  });
}

/**
 * Required ledger read + normalize. Throws on ledger failure (ADR 0005).
 */
export async function normalizeTerminalChildren(opts: {
  readonly epicChildren: ReadonlyArray<ChildSlice>;
  readonly recordedResults: ReadonlyArray<FamilyChildResult>;
  readonly familyBackend: FamilyBackend;
  readonly residualSkipReason?: FamilySkipReason;
}): Promise<{
  readonly children: FamilyChildResult[];
  readonly ledger: ReadonlyArray<FamilyLedgerEntry>;
  readonly hasRealChildFailure: boolean;
  readonly primaryUnansweredPark:
    | (FamilyLedgerEntry & { readonly childIssue: number })
    | undefined;
}> {
  const familyIssues = new Set(opts.epicChildren.map((c) => c.issue));
  // ADR 0005: ledger authority — read errors fail loud (no catch-to-empty).
  const ledger = await opts.familyBackend.readFamilyLedger();
  const parkedRows = unansweredChildEscalations(ledger).filter((row) =>
    familyIssues.has(row.childIssue),
  );
  const parkedEscalations = new Map<number, FamilyChildEscalation>();
  for (const row of parkedRows) {
    parkedEscalations.set(row.childIssue, escalationFromChildParkRow(row));
  }
  const children = remountDecisionParkChildren({
    epicChildren: opts.epicChildren,
    recordedResults: opts.recordedResults,
    ledgerMerged: mergedSet(ledger),
    parkedEscalations,
    residualSkipReason:
      opts.residualSkipReason ?? "not_scheduled_this_invocation",
  });
  return {
    children,
    ledger,
    hasRealChildFailure: children.some((c) => c.status === "failed"),
    primaryUnansweredPark: parkedRows[0],
  };
}

/** Shared familyStopSummary is still owned by runner (head metadata helpers). */
export type FamilyStopSummaryFn = (input: {
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
  readonly admissionSkipped?: FamilyEpic["admissionSkipped"];
  readonly alreadyDone?: ReadonlyArray<{
    readonly issue: number;
    readonly status: "merged" | "shipped" | "completed";
    readonly source: string;
  }>;
}) => StopSummary;

export type TerminalIntent =
  /** Auto: failure children beat decision_gate_park barrier; else completed/failed from children. */
  | {
      readonly kind: "auto";
      readonly barrierStopSummary?: StopSummary;
      readonly failedStatus?: FamilyStageFailureStatus;
      readonly failedPhase?: VerifyCmrPhase;
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
      readonly durableFailure?: boolean;
    }
  /** Explicit A-class failure terminal. */
  | {
      readonly kind: "failed";
      readonly cause: PublicFailedCause;
      readonly escalationReason?: string;
      readonly escalation?: Escalation;
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
      readonly durableFailure?: boolean;
      /** Also keep a prior decision record then write failure authority. */
      readonly durableDecisionThenFailure?: {
        readonly reason: string;
        readonly diagnosis?: string;
        readonly phase?: VerifyCmrPhase;
      };
    }
  /** Explicit decision-gate park (or provider_degraded via stopReason override). */
  | {
      readonly kind: "parked";
      readonly parkReason: "decision_gate_park" | "provider_degraded";
      readonly escalationReason: string;
      readonly escalation: Escalation;
      readonly parkedIssue?: number;
      readonly residualSkipReason?: FamilySkipReason;
      readonly fallbackHead?: string;
      readonly headMetadata?: StopSummary["metadata"];
      readonly durableDecision?: boolean;
      readonly durablePhase?: VerifyCmrPhase;
    }
  /** Merger decision: select failure if real sibling failed (not merger issue). */
  | {
      readonly kind: "merger_decision";
      readonly mergerIssue: number;
      readonly reason: string;
      readonly diagnosis: string;
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
    }
  /** Completed (all merged / already_done). */
  | {
      readonly kind: "completed";
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
      readonly stopSummaryOverride?: StopSummary;
    };

export async function finalizeFamilyTerminal(opts: {
  readonly familyBackend: FamilyBackend;
  readonly epic: FamilyEpic;
  readonly epicIssue: number;
  readonly familyBase: string;
  readonly familyHead?: string;
  readonly recordedResults: ReadonlyArray<FamilyChildResult>;
  readonly intent: TerminalIntent;
  readonly familyStopSummary: FamilyStopSummaryFn;
}): Promise<FamilyRunResult> {
  const residual =
    opts.intent.kind === "completed"
      ? opts.intent.residualSkipReason
      : opts.intent.residualSkipReason;
  const normalized = await normalizeTerminalChildren({
    epicChildren: opts.epic.children,
    recordedResults: opts.recordedResults,
    familyBackend: opts.familyBackend,
    ...(residual !== undefined ? { residualSkipReason: residual } : {}),
  });

  // Prefer durable cargo on pure replay of failed terminals (no live recorded).
  let children = normalized.children;
  if (
    opts.recordedResults.length === 0 &&
    opts.intent.kind === "failed"
  ) {
    // no special case
  }

  const alreadyDone = children
    .filter((child) => child.status === "already_done")
    .map((child) => ({
      issue: child.issue,
      status: "merged" as const,
      source: "family child already_done result",
    }));

  const buildFailed = async (input: {
    readonly cause: PublicFailedCause;
    readonly escalationReason?: string;
    readonly escalation?: Escalation;
    readonly stage?: FamilyStageFailureStatus;
    readonly failedPhase?: VerifyCmrPhase;
    readonly durableFailure?: boolean;
    readonly durableDecisionThenFailure?: {
      readonly reason: string;
      readonly diagnosis?: string;
      readonly phase?: VerifyCmrPhase;
    };
    readonly headMetadata?: StopSummary["metadata"];
    readonly barrierStopSummary?: StopSummary;
  }): Promise<FamilyRunResult> => {
    const cargoMeta = {
      ...(input.headMetadata ?? {}),
      trackedStatus: encodeTerminalChildrenCargo(children),
    };
    const stopSummary = opts.familyStopSummary({
      status: "failed",
      familyBase: opts.familyBase,
      ...(opts.familyHead !== undefined ? { familyHead: opts.familyHead } : {}),
      children,
      ...(input.escalationReason !== undefined
        ? { escalationReason: input.escalationReason }
        : {}),
      ...(input.stage !== undefined ? { stage: input.stage } : {}),
      ...(input.failedPhase !== undefined
        ? { failedPhase: input.failedPhase }
        : {}),
      headMetadata: cargoMeta,
      ...(input.barrierStopSummary !== undefined &&
      input.barrierStopSummary.reason !== "decision_gate_park"
        ? { barrierStopSummary: input.barrierStopSummary }
        : {}),
      admissionSkipped: opts.epic.admissionSkipped,
      alreadyDone,
    });
    // Attach cargo onto stopSummary metadata (rebuild if helper dropped it).
    const stopWithCargo: StopSummary = {
      ...stopSummary,
      metadata: {
        ...(stopSummary.metadata ?? {}),
        trackedStatus: encodeTerminalChildrenCargo(children),
      },
    };

    const writeDurable = async (
      esc: Parameters<NonNullable<FamilyBackend["escalateFamily"]>>[0],
    ): Promise<void> => {
      if (opts.familyBackend.escalateFamily !== undefined) {
        await opts.familyBackend.escalateFamily(esc);
        return;
      }
      await recordFamilyEscalated(opts.familyBackend, {
        escalationKind: esc.escalationKind,
        phase: esc.phase ?? "wave",
        reason: esc.reason,
        familyHeadAfter: esc.familyHeadAfter,
        stopSummary: esc.stopSummary,
      });
    };
    if (input.durableDecisionThenFailure !== undefined) {
      await writeDurable({
        escalationKind: "decision",
        phase: input.durableDecisionThenFailure.phase ?? "wave",
        reason: input.durableDecisionThenFailure.reason,
        diagnosis: input.durableDecisionThenFailure.diagnosis,
        ...(opts.familyHead !== undefined
          ? { familyHeadAfter: opts.familyHead }
          : {}),
        stopSummary: stopWithCargo,
      });
    }
    if (
      input.durableFailure === true ||
      input.durableDecisionThenFailure !== undefined
    ) {
      await writeDurable({
        escalationKind: "failure",
        phase: input.durableDecisionThenFailure?.phase ?? "wave",
        reason:
          input.escalationReason ??
          input.durableDecisionThenFailure?.reason ??
          "family terminal failed",
        ...(opts.familyHead !== undefined
          ? { familyHeadAfter: opts.familyHead }
          : {}),
        stopSummary: stopWithCargo,
      });
    }

    emitExitProgress({
      epic: opts.epicIssue,
      status: "failed",
      stopReason: stopWithCargo.reason,
      gateSummary: stopWithCargo.summary,
    });

    return failedFamilyResult({
      cause: input.cause,
      familyBase: opts.familyBase,
      ...(opts.familyHead !== undefined ? { familyHead: opts.familyHead } : {}),
      ...(input.failedPhase !== undefined
        ? { failedPhase: input.failedPhase }
        : {}),
      ...(input.escalation !== undefined
        ? { escalation: input.escalation }
        : input.escalationReason !== undefined
          ? {
              escalation: {
                reason: input.escalationReason,
                diagnosis: input.escalationReason,
              },
            }
          : {}),
      stopSummary: stopWithCargo,
      children,
      ...(opts.epic.admissionSkipped !== undefined &&
      opts.epic.admissionSkipped.length > 0
        ? { admissionSkipped: opts.epic.admissionSkipped }
        : {}),
    });
  };

  const buildParked = async (input: {
    readonly parkReason: "decision_gate_park" | "provider_degraded";
    readonly escalationReason: string;
    readonly escalation: Escalation;
    readonly parkedIssue?: number;
    readonly durableDecision?: boolean;
    readonly durablePhase?: VerifyCmrPhase;
    readonly fallbackHead?: string;
    readonly headMetadata?: StopSummary["metadata"];
  }): Promise<FamilyRunResult> => {
    const thisRunHead =
      typeof opts.familyHead === "string" && opts.familyHead.trim().length > 0
        ? opts.familyHead
        : undefined;
    const fallback =
      typeof input.fallbackHead === "string" &&
      input.fallbackHead.trim().length > 0
        ? input.fallbackHead
        : undefined;
    const familyHead = thisRunHead ?? fallback;
    const stopSummary =
      input.parkReason === "provider_degraded"
        ? {
            reason: "provider_degraded" as const,
            summary: input.escalationReason,
            repairHint:
              "wait for provider quota reset, then re-feed the family run",
            metadata: {
              ...(input.headMetadata ?? {}),
              trackedStatus: encodeTerminalChildrenCargo(children),
            },
          }
        : opts.familyStopSummary({
            status: "parked",
            familyBase: opts.familyBase,
            ...(familyHead !== undefined ? { familyHead } : {}),
            children,
            escalationReason: input.escalationReason,
            decisionGatePark: true,
            admissionSkipped: opts.epic.admissionSkipped,
            alreadyDone,
            headMetadata: {
              ...(input.headMetadata ?? {}),
              trackedStatus: encodeTerminalChildrenCargo(children),
            },
          });
    const stopWithCargo: StopSummary = {
      ...stopSummary,
      metadata: {
        ...(stopSummary.metadata ?? {}),
        trackedStatus: encodeTerminalChildrenCargo(children),
      },
    };

    if (input.durableDecision === true) {
      if (opts.familyBackend.escalateFamily !== undefined) {
        await opts.familyBackend.escalateFamily({
          escalationKind: "decision",
          phase: input.durablePhase ?? "wave",
          reason: input.escalation.reason,
          diagnosis: input.escalation.diagnosis,
          ...(familyHead !== undefined ? { familyHeadAfter: familyHead } : {}),
          stopSummary: stopWithCargo,
        });
      } else {
        await recordFamilyEscalated(opts.familyBackend, {
          escalationKind: "decision",
          phase: input.durablePhase ?? "wave",
          reason: input.escalation.reason,
          ...(familyHead !== undefined ? { familyHeadAfter: familyHead } : {}),
          stopSummary: stopWithCargo,
        });
      }
    }

    emitExitProgress({
      epic: opts.epicIssue,
      ...(input.parkedIssue !== undefined ? { issue: input.parkedIssue } : {}),
      status: "parked",
      stopReason: stopWithCargo.reason,
      gateSummary:
        input.escalation.diagnosis ??
        input.escalation.reason ??
        stopWithCargo.summary,
    });

    return {
      status: "parked",
      familyBase: opts.familyBase,
      ...(familyHead !== undefined ? { familyHead } : {}),
      escalation: input.escalation,
      stopSummary: stopWithCargo,
      children,
      ...(opts.epic.admissionSkipped !== undefined &&
      opts.epic.admissionSkipped.length > 0
        ? { admissionSkipped: opts.epic.admissionSkipped }
        : {}),
    };
  };

  switch (opts.intent.kind) {
    case "completed": {
      const stopSummary =
        opts.intent.stopSummaryOverride ??
        opts.familyStopSummary({
          status: "completed",
          familyBase: opts.familyBase,
          ...(opts.familyHead !== undefined
            ? { familyHead: opts.familyHead }
            : {}),
          children,
          admissionSkipped: opts.epic.admissionSkipped,
          alreadyDone,
          headMetadata: opts.intent.headMetadata,
        });
      emitExitProgress({
        epic: opts.epicIssue,
        status: "completed",
        stopReason: stopSummary.reason,
        gateSummary: stopSummary.summary,
      });
      return {
        status: "completed",
        familyBase: opts.familyBase,
        ...(opts.familyHead !== undefined
          ? { familyHead: opts.familyHead }
          : {}),
        stopSummary,
        children,
        ...(opts.epic.admissionSkipped !== undefined &&
        opts.epic.admissionSkipped.length > 0
          ? { admissionSkipped: opts.epic.admissionSkipped }
          : {}),
      };
    }
    case "failed":
      return await buildFailed({
        cause: opts.intent.cause,
        escalationReason: opts.intent.escalationReason,
        escalation: opts.intent.escalation,
        durableFailure: opts.intent.durableFailure,
        durableDecisionThenFailure: opts.intent.durableDecisionThenFailure,
        headMetadata: opts.intent.headMetadata,
      });
    case "parked":
      // A-class child failure still wins over explicit park request when recorded
      // results already show failed (quota / decision with concurrent fail).
      if (normalized.hasRealChildFailure) {
        return await buildFailed({
          cause: "child_execution_failed",
          escalationReason: opts.intent.escalationReason,
          escalation: opts.intent.escalation,
          durableFailure: true,
          headMetadata: opts.intent.headMetadata,
        });
      }
      return await buildParked(opts.intent);
    case "merger_decision": {
      const mergerIntent = opts.intent;
      const hasRealSiblingFailure = children.some(
        (c) => c.status === "failed" && c.issue !== mergerIntent.mergerIssue,
      );
      if (hasRealSiblingFailure) {
        return await buildFailed({
          cause: "child_execution_failed",
          escalationReason: mergerIntent.reason,
          escalation: {
            reason: mergerIntent.reason,
            diagnosis: mergerIntent.diagnosis,
          },
          durableDecisionThenFailure: {
            reason: mergerIntent.reason,
            diagnosis: mergerIntent.diagnosis,
            phase: "wave",
          },
          headMetadata: mergerIntent.headMetadata,
        });
      }
      return await buildParked({
        parkReason: "decision_gate_park",
        escalationReason: mergerIntent.reason,
        escalation: {
          reason: mergerIntent.reason,
          diagnosis: mergerIntent.diagnosis,
        },
        parkedIssue: mergerIntent.mergerIssue,
        durableDecision: true,
        durablePhase: "wave",
        headMetadata: mergerIntent.headMetadata,
      });
    }
    case "auto": {
      // Unique selector: real failed child > decision_gate_park barrier > stage fail > children completeness.
      if (normalized.hasRealChildFailure) {
        return await buildFailed({
          cause: "child_execution_failed",
          durableFailure: opts.intent.durableFailure === true,
          headMetadata: opts.intent.headMetadata,
          barrierStopSummary: opts.intent.barrierStopSummary,
          failedPhase: opts.intent.failedPhase,
          stage: opts.intent.failedStatus,
        });
      }
      if (opts.intent.barrierStopSummary?.reason === "decision_gate_park") {
        const park = normalized.primaryUnansweredPark;
        return await buildParked({
          parkReason: "decision_gate_park",
          escalationReason:
            opts.intent.barrierStopSummary.summary ??
            "family run parked on a decision gate",
          escalation: {
            reason:
              opts.intent.barrierStopSummary.summary ??
              "family run parked on a decision gate",
            diagnosis:
              opts.intent.barrierStopSummary.repairHint ??
              opts.intent.barrierStopSummary.summary,
          },
          parkedIssue: park?.childIssue,
          fallbackHead: park?.familyHeadAfter,
          headMetadata: opts.intent.headMetadata,
        });
      }
      if (
        opts.intent.failedStatus !== undefined ||
        opts.intent.failedPhase !== undefined ||
        opts.intent.barrierStopSummary != null
      ) {
        return await buildFailed({
          cause: "child_execution_failed",
          stage: opts.intent.failedStatus,
          failedPhase: opts.intent.failedPhase,
          barrierStopSummary: opts.intent.barrierStopSummary,
          headMetadata: opts.intent.headMetadata,
        });
      }
      if (
        children.every(
          (c) => c.status === "merged" || c.status === "already_done",
        )
      ) {
        const stopSummary = opts.familyStopSummary({
          status: "completed",
          familyBase: opts.familyBase,
          ...(opts.familyHead !== undefined
            ? { familyHead: opts.familyHead }
            : {}),
          children,
          admissionSkipped: opts.epic.admissionSkipped,
          alreadyDone,
          headMetadata: opts.intent.headMetadata,
        });
        emitExitProgress({
          epic: opts.epicIssue,
          status: "completed",
          stopReason: stopSummary.reason,
          gateSummary: stopSummary.summary,
        });
        return {
          status: "completed",
          familyBase: opts.familyBase,
          ...(opts.familyHead !== undefined
            ? { familyHead: opts.familyHead }
            : {}),
          stopSummary,
          children,
          ...(opts.epic.admissionSkipped !== undefined &&
          opts.epic.admissionSkipped.length > 0
            ? { admissionSkipped: opts.epic.admissionSkipped }
            : {}),
        };
      }
      // Residual unanswered parks → decision park (post-wave).
      if (normalized.primaryUnansweredPark !== undefined) {
        const first = normalized.primaryUnansweredPark;
        const esc = escalationFromChildParkRow(first);
        return await buildParked({
          parkReason: "decision_gate_park",
          escalationReason: `child #${first.childIssue} decision gate is not answered: ${first.reason ?? "(no reason recorded)"}`,
          escalation: {
            reason: esc.reason,
            diagnosis: esc.diagnosis,
          },
          parkedIssue: first.childIssue,
          fallbackHead: first.familyHeadAfter,
          headMetadata: opts.intent.headMetadata,
        });
      }
      return await buildFailed({
        cause: "child_execution_failed",
        headMetadata: opts.intent.headMetadata,
      });
    }
  }
}

/**
 * Replay prior family escalation from ledger (sole prior-escalation terminal).
 * Uses durable stopSummary cargo when present.
 */
export async function replayPriorFamilyEscalation(opts: {
  readonly familyBackend: FamilyBackend;
  readonly epic: FamilyEpic;
  readonly epicIssue: number;
  readonly familyBase: string;
  readonly escalation: FamilyLedgerEntry;
  readonly familyStopSummary: FamilyStopSummaryFn;
}): Promise<FamilyRunResult> {
  const pureDecisionPark =
    opts.escalation.escalationKind === "decision" &&
    (opts.escalation.stopSummary == null ||
      opts.escalation.stopSummary.reason === "decision_gate_park");
  const publicStatus: FamilyRunStatus = pureDecisionPark ? "parked" : "failed";

  const cargo = decodeTerminalChildrenCargo(
    opts.escalation.stopSummary?.metadata?.trackedStatus,
  );
  const familyHead =
    typeof opts.escalation.familyHeadAfter === "string" &&
    opts.escalation.familyHeadAfter.trim().length > 0
      ? opts.escalation.familyHeadAfter
      : undefined;

  if (cargo !== undefined) {
    const stopSummary =
      opts.escalation.stopSummary ??
      (publicStatus === "parked"
        ? opts.familyStopSummary({
            status: "parked",
            familyBase: opts.familyBase,
            familyHead,
            children: cargo,
            escalationReason:
              opts.escalation.reason ?? "family escalation is not answered",
            decisionGatePark: true,
          })
        : opts.familyStopSummary({
            status: "failed",
            familyBase: opts.familyBase,
            familyHead,
            children: cargo,
            escalationReason:
              opts.escalation.reason ?? "family escalation is not answered",
          }));
    emitExitProgress({
      epic: opts.epicIssue,
      status: publicStatus,
      stopReason: stopSummary.reason,
      gateSummary: stopSummary.summary,
    });
    if (publicStatus === "failed") {
      return failedFamilyResult({
        cause: "runner_internal_error",
        familyBase: opts.familyBase,
        ...(familyHead !== undefined ? { familyHead } : {}),
        escalation: {
          reason:
            opts.escalation.reason ?? "family escalation is not answered",
          diagnosis:
            opts.escalation.escalationKind === "failure"
              ? "Prior family escalation was classified as failure; append-only answers do not reopen it."
              : "Prior family decision was recorded with a failed terminal; re-feed does not re-park.",
        },
        stopSummary,
        children: cargo,
      });
    }
    return {
      status: "parked",
      familyBase: opts.familyBase,
      ...(familyHead !== undefined ? { familyHead } : {}),
      escalation: {
        reason: opts.escalation.reason ?? "family escalation is not answered",
        diagnosis:
          "Prior family decision escalation has no later valid escalation_answered ledger event.",
      },
      stopSummary,
      children: cargo,
    };
  }

  // No durable cargo — normalize from live ledger (parks preserved; missing
  // failed children may residual-skip; callers that need full cargo must have
  // written trackedStatus on first terminal).
  return await finalizeFamilyTerminal({
    familyBackend: opts.familyBackend,
    epic: opts.epic,
    epicIssue: opts.epicIssue,
    familyBase: opts.familyBase,
    familyHead,
    recordedResults: [],
    familyStopSummary: opts.familyStopSummary,
    intent:
      publicStatus === "parked"
        ? {
            kind: "parked",
            parkReason: "decision_gate_park",
            escalationReason:
              opts.escalation.reason ?? "family escalation is not answered",
            escalation: {
              reason:
                opts.escalation.reason ?? "family escalation is not answered",
              diagnosis:
                "Prior family decision escalation has no later valid escalation_answered ledger event.",
            },
          }
        : {
            kind: "failed",
            cause: "runner_internal_error",
            escalationReason:
              opts.escalation.reason ?? "family escalation is not answered",
            escalation: {
              reason:
                opts.escalation.reason ?? "family escalation is not answered",
              diagnosis:
                opts.escalation.escalationKind === "failure"
                  ? "Prior family escalation was classified as failure; append-only answers do not reopen it."
                  : "Prior family decision was recorded with a failed terminal; re-feed does not re-park.",
            },
          },
  });
}

// silence unused import if isValidChildDecisionParked not used
void isValidChildDecisionParked;
void infraFailureStopSummary;
