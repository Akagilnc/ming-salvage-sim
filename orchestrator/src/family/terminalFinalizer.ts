/**
 * #1125 owner A — sole family terminal finalizer (deep module).
 *
 * ## Terminal-state table (implementation checklist)
 *
 * | Exit | Facts / intent | Durable in | Children | Priority | Durable write | Progress |
 * | --- | --- | --- | --- | --- | --- | --- |
 * | startup route/smoke | recorded=[], failed | empty ledger ok | normalize | fail | none (pre-work) | after build |
 * | prior escalation replay | ledger escalated row | terminalChildren | cargo or normalize | failure vs park by kind/stop | none (read) | after build |
 * | refetch fail | recorded=[] | live ledger | normalize | fail/park | none | after build |
 * | reconcile/cycle | recorded results | live | normalize | fail | optional failure | after durable |
 * | correctness/merge/wave quota | drained recorded | live | normalize once | fail > provider_degraded | none (re-enterable) | after build |
 * | merger decision | drained recorded | live | normalize | sibling fail > park | decision[+failure] + terminalChildren | after durable |
 * | child decision park (wave) | does NOT terminal — records child park only | child_decision_parked | n/a | n/a | child park row | none |
 * | post-wave / finalize auto | recorded | live | normalize | fail > unanswered park > complete | failure when parks+fail | after durable |
 * | resume tails (converged/shipped) | recorded already_done | live | normalize | complete/park | none | after build |
 *
 * Callers submit facts + discriminated intent only.
 */

import { emitExitProgress } from "../progressBroadcast.js";
import type { StopSummary } from "../stopSummary.js";
import type { Escalation } from "../types.js";
import {
  isPublicRunResult,
  PUBLIC_FAILED_CAUSES,
  type PublicFailedCause,
} from "../publicResult.js";
import type { VerifyCmrPhase } from "./verifyCmr.js";
import type { FamilyStageFailureStatus } from "./familyTerminal.js";
import {
  failedFamilyResult,
  type ChildSlice,
  type FamilyBackend,
  type FamilyChildEscalation,
  type FamilyChildResult,
  type FamilyChildStatus,
  type FamilyEpic,
  type FamilyLedgerEntry,
  type FamilyRunResult,
  type FamilyRunStatus,
} from "./types.js";
import {
  mergedSet,
  recordFamilyEscalated,
  unansweredChildEscalations,
} from "./ledger.js";

// ─── skip tokens ────────────────────────────────────────────────────────────

export type FamilySkipReason =
  | "not_scheduled_this_invocation"
  | "unanswered_sibling_park_residual"
  | "startup_preflight_failed"
  | "refetch_failed"
  | "reconcile_inconsistent"
  | "dependency_cycle_residual";

const CHILD_STATUSES: ReadonlySet<string> = new Set([
  "ran",
  "merged",
  "already_done",
  "resumed",
  "skipped",
  "failed",
  "escalated",
]);

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

// ─── schema A: strict terminalChildren validation ───────────────────────────

/**
 * Validate durable terminalChildren cargo (schema A). Malformed → throw (ADR 0005).
 * Never returns undefined on bad input; never silently renormalizes.
 */
export function parseTerminalChildrenCargo(
  value: unknown,
  context: string,
): ReadonlyArray<FamilyChildResult> {
  if (value === undefined) {
    throw new Error(
      `${context}: terminalChildren missing on durable family terminal authority`,
    );
  }
  if (!Array.isArray(value)) {
    throw new Error(
      `${context}: terminalChildren must be an array (got ${typeof value})`,
    );
  }
  const out: FamilyChildResult[] = [];
  for (let i = 0; i < value.length; i++) {
    const raw = value[i];
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
      throw new Error(
        `${context}: terminalChildren[${i}] must be a non-null object`,
      );
    }
    const row = raw as Record<string, unknown>;
    if (
      typeof row.issue !== "number" ||
      !Number.isSafeInteger(row.issue) ||
      row.issue <= 0
    ) {
      throw new Error(
        `${context}: terminalChildren[${i}].issue must be a positive integer`,
      );
    }
    if (typeof row.status !== "string" || !CHILD_STATUSES.has(row.status)) {
      throw new Error(
        `${context}: terminalChildren[${i}].status invalid: ${String(row.status)}`,
      );
    }
    const status = row.status as FamilyChildStatus;
    if (row.branch !== undefined && typeof row.branch !== "string") {
      throw new Error(
        `${context}: terminalChildren[${i}].branch must be string when present`,
      );
    }
    if (
      row.failureCause !== undefined &&
      typeof row.failureCause !== "string"
    ) {
      throw new Error(
        `${context}: terminalChildren[${i}].failureCause must be string when present`,
      );
    }
    if (status === "failed" && row.failureCause === undefined) {
      // failureCause optional for back-compat of in-memory results; allowed.
    }
    if (status === "escalated") {
      if (
        row.escalation === null ||
        typeof row.escalation !== "object" ||
        Array.isArray(row.escalation)
      ) {
        throw new Error(
          `${context}: terminalChildren[${i}].escalation required object for escalated`,
        );
      }
      const esc = row.escalation as Record<string, unknown>;
      if (typeof esc.reason !== "string" || esc.reason.trim().length === 0) {
        throw new Error(
          `${context}: terminalChildren[${i}].escalation.reason required`,
        );
      }
      if (
        typeof esc.diagnosis !== "string" ||
        esc.diagnosis.trim().length === 0
      ) {
        throw new Error(
          `${context}: terminalChildren[${i}].escalation.diagnosis required`,
        );
      }
      if (esc.escalationKind !== "decision" && esc.escalationKind !== "failure") {
        throw new Error(
          `${context}: terminalChildren[${i}].escalation.escalationKind invalid`,
        );
      }
    }
    out.push({
      issue: row.issue,
      status,
      ...(typeof row.branch === "string" ? { branch: row.branch } : {}),
      ...(typeof row.failureCause === "string"
        ? { failureCause: row.failureCause }
        : {}),
      ...(row.escalation !== undefined
        ? { escalation: row.escalation as FamilyChildEscalation }
        : {}),
    });
  }
  return out;
}

// ─── normalize ──────────────────────────────────────────────────────────────

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

/** Required ledger read (throws) + epic-order normalize. */
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
  // ADR 0005: ledger authority — errors propagate (no catch-to-empty).
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

// ─── intent + finalizer ─────────────────────────────────────────────────────

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

/**
 * Discriminated terminal intent. Durable write is semantic of the intent kind
 * for failure/park that must survive restart — not optional caller booleans.
 */
export type TerminalIntent =
  | {
      readonly kind: "auto";
      readonly barrierStopSummary?: StopSummary;
      readonly failedStatus?: FamilyStageFailureStatus;
      readonly failedPhase?: VerifyCmrPhase;
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
      /** When true, failure that coexists with unanswered parks is durable. */
      readonly persistFailureWithParks?: boolean;
    }
  | {
      readonly kind: "failed";
      readonly cause: PublicFailedCause;
      readonly escalationReason?: string;
      readonly escalation?: Escalation;
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
      readonly persistDurable?: boolean;
      readonly durableDecisionThenFailure?: {
        readonly reason: string;
        readonly diagnosis?: string;
        readonly phase?: VerifyCmrPhase;
      };
    }
  | {
      readonly kind: "parked";
      readonly parkReason: "decision_gate_park" | "provider_degraded";
      readonly escalationReason: string;
      readonly escalation: Escalation;
      readonly parkedIssue?: number;
      readonly residualSkipReason?: FamilySkipReason;
      readonly fallbackHead?: string;
      readonly headMetadata?: StopSummary["metadata"];
      readonly stopSummaryOverride?: StopSummary;
      /** Family-level decision durable (merger). Child parks use ledger child rows. */
      readonly persistFamilyDecision?: boolean;
      readonly durablePhase?: VerifyCmrPhase;
    }
  | {
      readonly kind: "merger_decision";
      readonly mergerIssue: number;
      readonly reason: string;
      readonly diagnosis: string;
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
    }
  | {
      readonly kind: "completed";
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
      readonly stopSummaryOverride?: StopSummary;
    };

async function writeDurableEscalation(
  backend: FamilyBackend,
  esc: {
    readonly escalationKind: "decision" | "failure";
    readonly phase?: VerifyCmrPhase;
    readonly reason: string;
    readonly diagnosis?: string;
    readonly familyHeadAfter?: string;
    readonly stopSummary: StopSummary;
    readonly terminalChildren: ReadonlyArray<FamilyChildResult>;
    readonly terminalStatus: FamilyRunStatus;
    readonly terminalCause?: PublicFailedCause;
  },
): Promise<void> {
  if (backend.escalateFamily !== undefined) {
    await backend.escalateFamily({
      escalationKind: esc.escalationKind,
      phase: esc.phase ?? "wave",
      reason: esc.reason,
      ...(esc.diagnosis !== undefined ? { diagnosis: esc.diagnosis } : {}),
      ...(esc.familyHeadAfter !== undefined
        ? { familyHeadAfter: esc.familyHeadAfter }
        : {}),
      stopSummary: esc.stopSummary,
      terminalChildren: esc.terminalChildren,
      terminalStatus: esc.terminalStatus,
      terminalCause: esc.terminalCause,
    });
    return;
  }
  await recordFamilyEscalated(backend, {
    escalationKind: esc.escalationKind,
    phase: esc.phase ?? "wave",
    reason: esc.reason,
    familyHeadAfter: esc.familyHeadAfter,
    stopSummary: esc.stopSummary,
    terminalChildren: esc.terminalChildren,
    terminalStatus: esc.terminalStatus,
    terminalCause: esc.terminalCause,
  });
}

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
    "residualSkipReason" in opts.intent
      ? opts.intent.residualSkipReason
      : undefined;
  const normalized = await normalizeTerminalChildren({
    epicChildren: opts.epic.children,
    recordedResults: opts.recordedResults,
    familyBackend: opts.familyBackend,
    ...(residual !== undefined ? { residualSkipReason: residual } : {}),
  });
  const children = normalized.children;
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
    readonly persistDurable?: boolean;
    readonly durableDecisionThenFailure?: {
      readonly reason: string;
      readonly diagnosis?: string;
      readonly phase?: VerifyCmrPhase;
    };
    readonly headMetadata?: StopSummary["metadata"];
    readonly stopSummaryOverride?: StopSummary;
    readonly barrierStopSummary?: StopSummary;
  }): Promise<FamilyRunResult> => {
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
      headMetadata: input.headMetadata,
      ...(input.barrierStopSummary !== undefined &&
      input.barrierStopSummary.reason !== "decision_gate_park"
        ? { barrierStopSummary: input.barrierStopSummary }
        : {}),
      admissionSkipped: opts.epic.admissionSkipped,
      alreadyDone,
    });

    if (input.durableDecisionThenFailure !== undefined) {
      await writeDurableEscalation(opts.familyBackend, {
        escalationKind: "decision",
        phase: input.durableDecisionThenFailure.phase ?? "wave",
        reason: input.durableDecisionThenFailure.reason,
        diagnosis: input.durableDecisionThenFailure.diagnosis,
        familyHeadAfter: opts.familyHead,
        stopSummary,
        terminalChildren: children,
        terminalStatus: "failed",
        terminalCause: input.cause,
      });
      await writeDurableEscalation(opts.familyBackend, {
        escalationKind: "failure",
        phase: input.durableDecisionThenFailure.phase ?? "wave",
        reason: input.durableDecisionThenFailure.reason,
        familyHeadAfter: opts.familyHead,
        stopSummary,
        terminalChildren: children,
        terminalStatus: "failed",
        terminalCause: input.cause,
      });
    } else if (input.persistDurable === true) {
      await writeDurableEscalation(opts.familyBackend, {
        escalationKind: "failure",
        phase: "wave",
        reason:
          input.escalationReason ??
          input.escalation?.reason ??
          "family terminal failed",
        familyHeadAfter: opts.familyHead,
        stopSummary,
        terminalChildren: children,
        terminalStatus: "failed",
        terminalCause: input.cause,
      });
    }

    emitExitProgress({
      epic: opts.epicIssue,
      status: "failed",
      stopReason: stopSummary.reason,
      gateSummary: stopSummary.summary,
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
      stopSummary,
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
    readonly persistFamilyDecision?: boolean;
    readonly durablePhase?: VerifyCmrPhase;
    readonly fallbackHead?: string;
    readonly headMetadata?: StopSummary["metadata"];
    readonly stopSummaryOverride?: StopSummary;
    /** Issues whose failed status is a park placeholder, not A-class failure. */
    readonly ignoreFailedIssues?: ReadonlySet<number>;
  }): Promise<FamilyRunResult> => {
    // A-class child failure always wins over park (ignore merger placeholders).
    const realFail = children.some(
      (c) =>
        c.status === "failed" &&
        !(input.ignoreFailedIssues?.has(c.issue) ?? false),
    );
    if (realFail) {
      return await buildFailed({
        cause: "child_execution_failed",
        escalationReason: input.escalationReason,
        escalation: input.escalation,
        persistDurable: true,
        headMetadata: input.headMetadata,
      });
    }
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
      input.stopSummaryOverride ??
      (input.parkReason === "provider_degraded"
        ? ({
            reason: "provider_degraded",
            summary: input.escalationReason,
            repairHint:
              "wait for provider quota reset, then re-feed the family run",
            ...(input.headMetadata !== undefined
              ? { metadata: input.headMetadata }
              : {}),
          } satisfies StopSummary)
        : opts.familyStopSummary({
            status: "parked",
            familyBase: opts.familyBase,
            ...(familyHead !== undefined ? { familyHead } : {}),
            children,
            escalationReason: input.escalationReason,
            decisionGatePark: true,
            admissionSkipped: opts.epic.admissionSkipped,
            alreadyDone,
            headMetadata: input.headMetadata,
          }));

    if (input.persistFamilyDecision === true) {
      await writeDurableEscalation(opts.familyBackend, {
        escalationKind: "decision",
        phase: input.durablePhase ?? "wave",
        reason: input.escalation.reason,
        diagnosis: input.escalation.diagnosis,
        familyHeadAfter: familyHead,
        stopSummary,
        terminalChildren: children,
        terminalStatus: "parked",
      });
    }

    emitExitProgress({
      epic: opts.epicIssue,
      ...(input.parkedIssue !== undefined ? { issue: input.parkedIssue } : {}),
      status: "parked",
      stopReason: stopSummary.reason,
      gateSummary:
        input.escalation.diagnosis ??
        input.escalation.reason ??
        stopSummary.summary,
    });

    return {
      status: "parked",
      familyBase: opts.familyBase,
      ...(familyHead !== undefined ? { familyHead } : {}),
      escalation: input.escalation,
      stopSummary,
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
        persistDurable: opts.intent.persistDurable,
        durableDecisionThenFailure: opts.intent.durableDecisionThenFailure,
        headMetadata: opts.intent.headMetadata,
      });
    case "parked":
      return await buildParked({
        parkReason: opts.intent.parkReason,
        escalationReason: opts.intent.escalationReason,
        escalation: opts.intent.escalation,
        parkedIssue: opts.intent.parkedIssue,
        persistFamilyDecision: opts.intent.persistFamilyDecision,
        durablePhase: opts.intent.durablePhase,
        fallbackHead: opts.intent.fallbackHead,
        headMetadata: opts.intent.headMetadata,
        stopSummaryOverride: opts.intent.stopSummaryOverride,
      });
    case "merger_decision": {
      const m = opts.intent;
      const hasRealSiblingFailure = children.some(
        (c) => c.status === "failed" && c.issue !== m.mergerIssue,
      );
      if (hasRealSiblingFailure) {
        return await buildFailed({
          cause: "child_execution_failed",
          escalationReason: m.reason,
          escalation: { reason: m.reason, diagnosis: m.diagnosis },
          durableDecisionThenFailure: {
            reason: m.reason,
            diagnosis: m.diagnosis,
            phase: "wave",
          },
          headMetadata: m.headMetadata,
        });
      }
      return await buildParked({
        parkReason: "decision_gate_park",
        escalationReason: m.reason,
        escalation: { reason: m.reason, diagnosis: m.diagnosis },
        parkedIssue: m.mergerIssue,
        persistFamilyDecision: true,
        durablePhase: "wave",
        headMetadata: m.headMetadata,
        ignoreFailedIssues: new Set([m.mergerIssue]),
      });
    }
    case "auto": {
      const intent = opts.intent;
      if (normalized.hasRealChildFailure) {
        return await buildFailed({
          cause: "child_execution_failed",
          // Persist when parks coexist so replay does not re-park.
          persistDurable:
            intent.persistFailureWithParks === true ||
            normalized.primaryUnansweredPark !== undefined,
          headMetadata: intent.headMetadata,
          barrierStopSummary: intent.barrierStopSummary,
          failedPhase: intent.failedPhase,
          stage: intent.failedStatus,
        });
      }
      if (intent.barrierStopSummary?.reason === "decision_gate_park") {
        const park = normalized.primaryUnansweredPark;
        return await buildParked({
          parkReason: "decision_gate_park",
          escalationReason:
            intent.barrierStopSummary.summary ??
            "family run parked on a decision gate",
          escalation: {
            reason:
              intent.barrierStopSummary.summary ??
              "family run parked on a decision gate",
            diagnosis:
              intent.barrierStopSummary.repairHint ??
              intent.barrierStopSummary.summary,
          },
          parkedIssue: park?.childIssue,
          fallbackHead: park?.familyHeadAfter,
          headMetadata: intent.headMetadata,
        });
      }
      if (
        intent.failedStatus !== undefined ||
        intent.failedPhase !== undefined ||
        intent.barrierStopSummary != null
      ) {
        // Quota provider_degraded parks via barrier reason.
        if (intent.barrierStopSummary?.reason === "provider_degraded") {
          return await buildParked({
            parkReason: "provider_degraded",
            escalationReason: intent.barrierStopSummary.summary,
            escalation: {
              reason: intent.barrierStopSummary.summary,
              diagnosis:
                intent.barrierStopSummary.repairHint ??
                intent.barrierStopSummary.summary,
            },
            headMetadata: intent.headMetadata,
          });
        }
        return await buildFailed({
          cause: "child_execution_failed",
          stage: intent.failedStatus,
          failedPhase: intent.failedPhase,
          barrierStopSummary: intent.barrierStopSummary,
          headMetadata: intent.headMetadata,
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
          headMetadata: intent.headMetadata,
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
      if (normalized.primaryUnansweredPark !== undefined) {
        const first = normalized.primaryUnansweredPark;
        const esc = escalationFromChildParkRow(first);
        return await buildParked({
          parkReason: "decision_gate_park",
          escalationReason: `child #${first.childIssue} decision gate is not answered: ${first.reason ?? "(no reason recorded)"}`,
          escalation: { reason: esc.reason, diagnosis: esc.diagnosis },
          parkedIssue: first.childIssue,
          fallbackHead: first.familyHeadAfter,
          headMetadata: intent.headMetadata,
        });
      }
      return await buildFailed({
        cause: "child_execution_failed",
        headMetadata: intent.headMetadata,
      });
    }
  }
}

/**
 * Replay prior family escalation. Requires terminalChildren on durable row
 * when present; missing cargo + non-park failure throws (no silent renorm).
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
  if (
    opts.escalation.terminalStatus !== undefined &&
    !isPublicRunResult(opts.escalation.terminalStatus)
  ) {
    throw new Error(
      `replay prior family terminal authority: terminalStatus invalid: ${String(opts.escalation.terminalStatus)}`,
    );
  }
  if (
    opts.escalation.terminalCause !== undefined &&
    !PUBLIC_FAILED_CAUSES.includes(opts.escalation.terminalCause)
  ) {
    throw new Error(
      `replay prior family terminal authority: terminalCause invalid: ${String(opts.escalation.terminalCause)}`,
    );
  }
  const publicStatus =
    opts.escalation.terminalStatus ??
    (pureDecisionPark ? ("parked" as const) : ("failed" as const));
  if (pureDecisionPark ? publicStatus !== "parked" : publicStatus !== "failed") {
    throw new Error(
      `replay prior family terminal authority: terminalStatus ${publicStatus} contradicts ${pureDecisionPark ? "decision park" : "failure"} authority`,
    );
  }
  if (publicStatus === "failed" && opts.escalation.terminalStatus !== undefined &&
      opts.escalation.terminalCause === undefined) {
    throw new Error(
      "replay prior family failure authority: terminalCause missing",
    );
  }
  const familyHead =
    typeof opts.escalation.familyHeadAfter === "string" &&
    opts.escalation.familyHeadAfter.trim().length > 0
      ? opts.escalation.familyHeadAfter
      : undefined;

  // Schema A: failed authority MUST carry terminalChildren.
  if (!pureDecisionPark) {
    const children = parseTerminalChildrenCargo(
      opts.escalation.terminalChildren,
      "replay prior family failure authority",
    );
    const stopSummary =
      opts.escalation.stopSummary ??
      opts.familyStopSummary({
        status: "failed",
        familyBase: opts.familyBase,
        familyHead,
        children,
        escalationReason:
          opts.escalation.reason ?? "family escalation is not answered",
      });
    emitExitProgress({
      epic: opts.epicIssue,
      status: "failed",
      stopReason: stopSummary.reason,
      gateSummary: stopSummary.summary,
    });
    return failedFamilyResult({
      cause: opts.escalation.terminalCause ?? "child_execution_failed",
      familyBase: opts.familyBase,
      ...(familyHead !== undefined ? { familyHead } : {}),
      escalation: {
        reason: opts.escalation.reason ?? "family escalation is not answered",
        diagnosis:
          opts.escalation.escalationKind === "failure"
            ? "Prior family escalation was classified as failure; append-only answers do not reopen it."
            : "Prior family decision was recorded with a failed terminal; re-feed does not re-park.",
      },
      stopSummary,
      children,
    });
  }

  // Pure decision park: prefer cargo when present; else normalize live parks.
  if (opts.escalation.terminalChildren !== undefined) {
    const children = parseTerminalChildrenCargo(
      opts.escalation.terminalChildren,
      "replay prior family decision park",
    );
    const stopSummary =
      opts.escalation.stopSummary ??
      opts.familyStopSummary({
        status: "parked",
        familyBase: opts.familyBase,
        familyHead,
        children,
        escalationReason:
          opts.escalation.reason ?? "family escalation is not answered",
        decisionGatePark: true,
      });
    emitExitProgress({
      epic: opts.epicIssue,
      status: "parked",
      stopReason: stopSummary.reason,
      gateSummary: stopSummary.summary,
    });
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
      children,
    };
  }

  return await finalizeFamilyTerminal({
    familyBackend: opts.familyBackend,
    epic: opts.epic,
    epicIssue: opts.epicIssue,
    familyBase: opts.familyBase,
    familyHead,
    recordedResults: [],
    familyStopSummary: opts.familyStopSummary,
    intent: {
      kind: "parked",
      parkReason: "decision_gate_park",
      escalationReason:
        opts.escalation.reason ?? "family escalation is not answered",
      escalation: {
        reason: opts.escalation.reason ?? "family escalation is not answered",
        diagnosis:
          "Prior family decision escalation has no later valid escalation_answered ledger event.",
      },
    },
  });
}
