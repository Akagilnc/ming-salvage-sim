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
import {
  resolveFamilyStageTerminal,
  type FamilyStageFailureStatus,
} from "./familyTerminal.js";
import {
  failedFamilyResult,
  type ChildSlice,
  type FamilyBackend,
  type FamilyChildEscalation,
  type FamilyChildResult,
  type FamilyChildStatus,
  type FamilySkipReason,
  type FamilyEpic,
  type FamilyLedgerEntry,
  type FamilyRunResult,
  type FamilyRunStatus,
  FAMILY_CHILD_STATUSES,
  FAMILY_SKIP_REASONS,
} from "./types.js";
import {
  mergedSet,
  recordFamilyEscalated,
  unansweredChildEscalations,
} from "./ledger.js";
// ─── skip tokens ────────────────────────────────────────────────────────────
const CHILD_STATUSES: ReadonlySet<string> = new Set(FAMILY_CHILD_STATUSES);
function skippedChild(
  issue: number,
  reason: FamilySkipReason,
): FamilyChildResult {
  console.warn(`family child #${issue} skipped: ${reason}`);
  return { issue, status: "skipped", reason };
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
function parseTerminalChildrenCargo(
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
    if (status === "skipped") {
      if (
        typeof row.reason !== "string" ||
        !FAMILY_SKIP_REASONS.includes(row.reason as FamilySkipReason)
      ) {
        throw new Error(
          `${context}: terminalChildren[${i}].reason required for skipped`,
        );
      }
    } else if (row.reason !== undefined) {
      throw new Error(
        `${context}: terminalChildren[${i}].reason only legal for skipped`,
      );
    }
    if (row.branch !== undefined && typeof row.branch !== "string") {
      throw new Error(
        `${context}: terminalChildren[${i}].branch must be string when present`,
      );
    }
    if (row.failureCause !== undefined && typeof row.failureCause !== "string") {
      throw new Error(
        `${context}: terminalChildren[${i}].failureCause must be string when present`,
      );
    }
    if (
      status === "failed" &&
      (typeof row.failureCause !== "string" || row.failureCause.length === 0)
    ) {
      throw new Error(
        `${context}: terminalChildren[${i}].failureCause required for failed`,
      );
    }
    if (status !== "failed" && row.failureCause !== undefined) {
      throw new Error(
        `${context}: terminalChildren[${i}].failureCause only legal for failed`,
      );
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
    const shared = {
      issue: row.issue,
      ...(typeof row.branch === "string" ? { branch: row.branch } : {}),
      ...(typeof row.failureCause === "string"
        ? { failureCause: row.failureCause }
        : {}),
      ...(row.escalation !== undefined
        ? { escalation: row.escalation as FamilyChildEscalation }
        : {}),
    };
    out.push(
      status === "skipped"
        ? {
            ...shared,
            status,
            reason: row.reason as FamilySkipReason,
          }
        : { ...shared, status },
    );
  }
  return out;
}

/** Legacy escalation rows predate every schema-A terminal replay field. */
export function isLegacyEscalationWithoutTerminalCargo(
  entry: FamilyLedgerEntry,
): boolean {
  return (
    entry.terminalStatus === undefined &&
    entry.terminalChildren === undefined &&
    entry.terminalCause === undefined
  );
}
// ─── normalize ──────────────────────────────────────────────────────────────
function remountDecisionParkChildren(opts: {
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
async function normalizeTerminalChildren(opts: {
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
type TerminalIntent =
  | {
      readonly kind: "auto";
      readonly barrierStopSummary?: StopSummary;
      readonly failedStatus?: FamilyStageFailureStatus;
      readonly failedPhase?: VerifyCmrPhase;
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
      /** When true, failure that coexists with unanswered parks is durable. */
      readonly persistFailureWithParks?: boolean;
      readonly completedStopSummaryOverride?: StopSummary;
    }
  | {
      readonly kind: "failed";
      readonly cause: PublicFailedCause;
      readonly escalationReason?: string;
      readonly escalation?: Escalation;
      readonly residualSkipReason?: FamilySkipReason;
      readonly headMetadata?: StopSummary["metadata"];
      readonly stopSummaryOverride?: StopSummary;
      readonly failedPhase?: VerifyCmrPhase;
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
    readonly barrierStopSummary?: StopSummary;
    readonly stopSummaryOverride?: StopSummary;
  }): Promise<FamilyRunResult> => {
    const terminalChildren = children.map((child) =>
      child.status === "failed" && child.failureCause === undefined
        ? { ...child, failureCause: input.cause }
        : child,
    );
    const stopSummary = input.stopSummaryOverride ?? opts.familyStopSummary({
      status: "failed",
      familyBase: opts.familyBase,
      ...(opts.familyHead !== undefined ? { familyHead: opts.familyHead } : {}),
      children: terminalChildren,
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
        terminalChildren,
        terminalStatus: "failed",
        terminalCause: input.cause,
      });
      await writeDurableEscalation(opts.familyBackend, {
        escalationKind: "failure",
        phase: input.durableDecisionThenFailure.phase ?? "wave",
        reason: input.durableDecisionThenFailure.reason,
        familyHeadAfter: opts.familyHead,
        stopSummary,
        terminalChildren,
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
        terminalChildren,
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
      children: terminalChildren,
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
    const terminalChildren =
      input.ignoreFailedIssues === undefined
        ? children
        : children.map((child) =>
            child.status === "failed" &&
            input.ignoreFailedIssues!.has(child.issue)
              ? {
                  issue: child.issue,
                  status: "escalated" as const,
                  escalation: {
                    reason: input.escalation.reason,
                    diagnosis:
                      input.escalation.diagnosis ?? input.escalation.reason,
                    escalationKind: "decision" as const,
                  },
                }
              : child,
          );
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
            children: terminalChildren,
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
        terminalChildren,
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
      children: terminalChildren,
      ...(opts.epic.admissionSkipped !== undefined &&
      opts.epic.admissionSkipped.length > 0
        ? { admissionSkipped: opts.epic.admissionSkipped }
        : {}),
    };
  };
  const buildCompleted = (stopSummary: StopSummary): FamilyRunResult => {
    emitExitProgress({
      epic: opts.epicIssue,
      status: "completed",
      stopReason: stopSummary.reason,
      gateSummary: stopSummary.summary,
    });
    return {
      status: "completed",
      familyBase: opts.familyBase,
      ...(opts.familyHead !== undefined ? { familyHead: opts.familyHead } : {}),
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
      return buildCompleted(stopSummary);
    }
    case "failed":
      return await buildFailed({
        cause: opts.intent.cause,
        escalationReason: opts.intent.escalationReason,
        escalation: opts.intent.escalation,
        persistDurable: opts.intent.persistDurable,
        durableDecisionThenFailure: opts.intent.durableDecisionThenFailure,
        headMetadata: opts.intent.headMetadata,
        stopSummaryOverride: opts.intent.stopSummaryOverride,
        failedPhase: opts.intent.failedPhase,
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
      const mergerDecision = opts.intent;
      const hasRealSiblingFailure = children.some(
        (c) =>
          c.status === "failed" && c.issue !== mergerDecision.mergerIssue,
      );
      if (hasRealSiblingFailure) {
        return await buildFailed({
          cause: "child_execution_failed",
          escalationReason: mergerDecision.reason,
          escalation: {
            reason: mergerDecision.reason,
            diagnosis: mergerDecision.diagnosis,
          },
          durableDecisionThenFailure: {
            reason: mergerDecision.reason,
            diagnosis: mergerDecision.diagnosis,
            phase: "wave",
          },
          headMetadata: mergerDecision.headMetadata,
        });
      }
      return await buildParked({
        parkReason: "decision_gate_park",
        escalationReason: mergerDecision.reason,
        escalation: {
          reason: mergerDecision.reason,
          diagnosis: mergerDecision.diagnosis,
        },
        parkedIssue: mergerDecision.mergerIssue,
        persistFamilyDecision: true,
        durablePhase: "wave",
        headMetadata: mergerDecision.headMetadata,
        ignoreFailedIssues: new Set([mergerDecision.mergerIssue]),
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
        const terminal = resolveFamilyStageTerminal({
          ...(intent.failedStatus !== undefined
            ? { failedStatus: intent.failedStatus }
            : {}),
          ...(intent.barrierStopSummary !== undefined
            ? { barrierStopSummary: intent.barrierStopSummary }
            : {}),
          defaultStatus: "verify_failed",
        });
        if (terminal.kind === "parked") {
          return await buildParked({
            parkReason:
              terminal.stopSummary.reason === "provider_degraded"
                ? "provider_degraded"
                : "decision_gate_park",
            escalationReason: terminal.stopSummary.summary,
            escalation: {
              reason: terminal.stopSummary.summary,
              diagnosis:
                terminal.stopSummary.repairHint ??
                terminal.stopSummary.summary,
            },
            headMetadata: intent.headMetadata,
            stopSummaryOverride: terminal.stopSummary,
          });
        }
        return await buildFailed({
          cause: terminal.cause,
          stage: terminal.stage,
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
        const computed = opts.familyStopSummary({
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
        const stopSummary: StopSummary =
          intent.completedStopSummaryOverride === undefined
            ? computed
            : {
                ...intent.completedStopSummaryOverride,
                metadata: {
                  ...(intent.completedStopSummaryOverride.metadata ?? {}),
                  ...(computed.metadata ?? {}),
                },
              };
        const completedStopSummary: StopSummary =
          children.length > 0 &&
          children.every((child) => child.status === "already_done")
            ? {
                ...stopSummary,
                reason: "already_done",
                summary:
                  "family resume found every child already merged and skipped rerun",
              }
            : stopSummary;
        return buildCompleted(completedStopSummary);
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
  readonly epicIssue: number;
  readonly familyBase: string;
  readonly escalation: FamilyLedgerEntry;
  readonly admissionSkipped?: FamilyEpic["admissionSkipped"];
}): Promise<FamilyRunResult> {
  if (!isPublicRunResult(opts.escalation.terminalStatus)) {
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
  const publicStatus = opts.escalation.terminalStatus;
  if (publicStatus === "completed") {
    throw new Error(
      "replay prior family terminal authority: escalation cannot be completed",
    );
  }
  if (
    opts.escalation.escalationKind === "failure" &&
    publicStatus !== "failed"
  ) {
    throw new Error(
      `replay prior family terminal authority: failure escalation cannot be ${publicStatus}`,
    );
  }
  if (publicStatus === "failed" && opts.escalation.terminalCause === undefined) {
    throw new Error(
      "replay prior family failure authority: terminalCause missing",
    );
  }
  if (publicStatus === "parked" && opts.escalation.terminalCause !== undefined) {
    throw new Error(
      "replay prior family park authority: terminalCause is forbidden",
    );
  }
  if (
    opts.escalation.stopSummary === undefined ||
    opts.escalation.stopSummary === null
  ) {
    throw new Error(
      "replay prior family terminal authority: stopSummary missing",
    );
  }
  const familyHead =
    typeof opts.escalation.familyHeadAfter === "string" &&
    opts.escalation.familyHeadAfter.trim().length > 0
      ? opts.escalation.familyHeadAfter
      : undefined;
  const terminalChildren = parseTerminalChildrenCargo(
    opts.escalation.terminalChildren,
    "replay prior family terminal authority",
  );
  const admissionSkipped = opts.admissionSkipped ?? [];
  const terminalIssues = new Set(terminalChildren.map((child) => child.issue));
  const children = [
    ...terminalChildren,
    ...admissionSkipped
      .filter((child) => !terminalIssues.has(child.issue))
      .map((child) => ({
        issue: child.issue,
        status: "skipped" as const,
        reason: "admission_skipped" as const,
      })),
  ];
  const stopSummary = opts.escalation.stopSummary;
  emitExitProgress({
    epic: opts.epicIssue,
    status: publicStatus,
    stopReason: stopSummary.reason,
    gateSummary: stopSummary.summary,
  });
  const escalation = {
    reason: opts.escalation.reason ?? "family escalation is not answered",
    diagnosis:
      opts.escalation.escalationKind === "failure"
        ? "Prior family escalation was classified as failure; append-only answers do not reopen it."
        : publicStatus === "failed"
          ? "Prior family decision was recorded with a failed terminal; re-feed does not re-park."
          : "Prior family decision escalation has no later valid escalation_answered ledger event.",
  };
  if (publicStatus === "failed") {
    return failedFamilyResult({
      cause: opts.escalation.terminalCause!,
      familyBase: opts.familyBase,
      ...(familyHead !== undefined ? { familyHead } : {}),
      escalation,
      stopSummary,
      children,
      ...(admissionSkipped.length > 0 ? { admissionSkipped } : {}),
    });
  }
  return {
    status: "parked",
    familyBase: opts.familyBase,
    ...(familyHead !== undefined ? { familyHead } : {}),
    escalation,
    stopSummary,
    children,
    ...(admissionSkipped.length > 0 ? { admissionSkipped } : {}),
  };
}
