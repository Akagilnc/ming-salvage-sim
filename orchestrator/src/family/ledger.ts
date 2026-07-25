/**
 * family-ledger — append-only merged-child event ledger (ADR 0022 decision 5,
 * #293 seam 3).
 *
 * The family ledger is the append-only event record of which child slices have
 * been merged into the family base. It lives (in the real Backend) as a sibling
 * of the family base worktree, OUTSIDE it, so a worktree clean can never touch
 * the resume / unblock truth. #293 records only the thinnest event
 * `{childIssue, status:"merged"}`; the commander's unblock predicate (ADR 0022
 * decision 6②: a child is schedulable once every blocker has a `status==="merged"`
 * ledger entry) reads the merged set this module derives.
 *
 * #298 EXTENSION POINT: the full event schema (childBranch / childHead / wave /
 * familyHeadBefore / familyHeadAfter / `aborted` events) + crash-window reconcile
 * layer HERE — by widening {@link FamilyLedgerEntry} and adding write/reconcile
 * helpers in this module. The spine only ever calls `recordMerged` / `mergedSet`,
 * so those extensions never reach into the family main loop. (#293 keeps the
 * append-only invariant but does NOT dedup — reconcile is #298.)
 */

import type {
  CleanupResult,
  EscalationAnswerPayload,
  EscalationKind,
} from "../types.js";
import { isValidCleanupResult } from "../reviewLoopOutcome.js";
import {
  decisionGateParkStopSummary,
  infraFailureStopSummary,
  successStopSummary,
  type StopSummary,
} from "../stopSummary.js";
import {
  emitShipProgress,
  getProgressBroadcastConfig,
} from "../progressBroadcast.js";
import { isCanonicalGithubPrUrl } from "../botPolling.js";
import {
  FAMILY_LEDGER_STATUS_VALUES,
  type FamilyBackend,
  type FamilyLedgerEntry,
  type IntegratedCmrPass,
} from "./types.js";
import type { VerifyCmrPhase } from "./verifyCmr.js";

/**
 * The full-schema fields a #298 `merged` event can carry (ADR 0022 decision 5).
 * Everything but `childIssue` is optional so the #293 thin write still validates.
 */
export interface MergedRecord {
  readonly childIssue: number;
  readonly childBranch?: string;
  readonly childHead?: string;
  readonly wave?: number;
  readonly familyHeadBefore?: string;
  readonly familyHeadAfter?: string;
  /**
   * Set to `"reconciled"` by {@link reconcileFamilyLedger} for a crash-window
   * 补账条 (a merge that landed before the live `merged` write — decision 5). The
   * entry still carries `status:"merged"` so the unblock predicate counts it
   * (codex R3); the tag is for audit. Normal merges leave this undefined.
   */
  readonly event?: "reconciled";
  /**
   * Did this child's merge get LLM-resolved (#295)? Forwarded by the merger from
   * {@link MergeResult.conflictResolvedByLlm} so the integrated cmr 承重闸 can read
   * it off the durable ledger (#291 缺口 1). Omitted on a clean merge.
   */
  readonly conflictResolvedByLlm?: boolean;
}

/**
 * The fields a PHASE-LEVEL `aborted` event (verify/cmr failure) carries (#291 缺口
 * 2). An abort is a failure of a whole verify PHASE, not a single child — so it
 * carries the `phase` (and `reason`), NOT a `childIssue`. `familyHeadAfter` is the
 * family base head at the time the barrier failed, REUSED so reconcile's "read末条
 * familyHeadAfter" baseline logic treats merged AND aborted entries uniformly.
 */
export interface AbortedRecord {
  /** Which verify barrier was red. */
  readonly phase: VerifyCmrPhase;
  /** Which integrated CMR pass failed, when the abort came from a CMR pass. */
  readonly cmrPass?: IntegratedCmrPass;
  /** Human-readable abort reason (the verify error / cmr non-convergence). */
  readonly reason?: string;
  /** The family base HEAD at the time the barrier failed (for triage + baseline). */
  readonly familyHeadAfter?: string;
  /**
   * Thin control envelope (#604 slice 3 / ADR 0062): the deduped identity keys of
   * the blocking findings this abort carries. The runner reads ONLY this off an
   * aborted row. A `not_converged` sentinel abort carries `[]`; an infra abort
   * carries nothing (`undefined`), which the runner treats as an unclassified abort.
   */
  readonly blockingFindingIdentityKeys?: readonly string[];
  /** Unified stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
}

/**
 * The fields a PHASE-LEVEL `shipped` event (止于-PR success) carries (online
 * review r2, codex P1). Like {@link AbortedRecord} it is a phase-level event
 * (NOT a child), so it carries NO `childIssue`. It records the family `pr` URL
 * and the exact family HEAD covered by that PR. As of #596 `shipped` is
 * INTERMEDIATE: the spine skips the final barrier only when a matching
 * `review_loop_converged` marker exists for the current head.
 */
export interface ShippedRecord {
  /** The family PR URL the ship opened. */
  readonly pr: string;
  /** The family base HEAD covered by the ship / PR. */
  readonly familyHeadAfter: string;
  /** Unified stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
}

/**
 * The fields a PHASE-LEVEL `review_loop_converged` terminal event carries
 * (#596). Written after the family PR has passed the online review/PR-check
 * loop. The spine's final-barrier resume guard reads this marker.
 */
export interface ReviewLoopConvergedRecord {
  /** The family PR URL that has converged. */
  readonly pr: string;
  /** The family base HEAD covered by the converged review loop. */
  readonly familyHeadAfter: string;
  /** Unified stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
}

/** The fields a PHASE-LEVEL `pr_merged` terminal event carries (#602). */
export interface PrMergedRecord {
  readonly pr: string;
  readonly prNumber: number;
  readonly remoteBranchName: string;
  readonly mergedHeadOid: string;
  readonly familyHeadAfter: string;
  readonly stopSummary?: StopSummary;
}

/**
 * Landing docs/VERSION release completion (before merge). Durable so a crash
 * after push does not re-dispatch the landing worker and duplicate release.
 */
export interface DocsReleasedRecord {
  readonly pr: string;
  readonly familyHeadAfter: string;
  readonly stopSummary?: StopSummary;
}

/** The fields for a green integrated CMR pass audit event (#419). */
export interface CmrPassedRecord {
  readonly cmrPass: IntegratedCmrPass;
  /** The family base HEAD that this pass reviewed and passed. */
  readonly familyHeadAfter?: string;
  /** Resolved route fingerprint for the CMR worker and declared review legs. */
  readonly routeFingerprint?: string;
  /**
   * Barrier phase that produced this green pass. Defaults to `"final"`.
   * `#961` incremental IC checkpoints write `"correctness_checkpoint"`.
   */
  readonly phase?: VerifyCmrPhase;
  /** Unified stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
  /** #930 — family judge session id for resume / prior-verdict rows. */
  readonly sessionId?: string;
  /** #930 — T2 judge status (converged on green pass; toolchain #1027 S1). */
  readonly judgeStatus?: import("../types.js").JudgeVerdictStatus;
  /**
   * #930 / #952 — disposition table (usually empty on green pass). Includes
   * schema `action: "suppress"` when the judge parks a finding (queryable).
   */
  readonly findingDispositions?: ReadonlyArray<
    import("../types.js").JudgeFindingDisposition
  >;
  readonly advanceCoder?: string;
}

/** A red integrated CMR review outcome handed back to the runner before fix (#550). */
export interface CmrReviewedRecord {
  readonly cmrPass: IntegratedCmrPass;
  readonly reason?: string;
  readonly familyHeadAfter?: string;
  /** Barrier phase; defaults to `"final"`. `#961` checkpoints use `"correctness_checkpoint"`. */
  readonly phase?: VerifyCmrPhase;
  /**
   * Thin control envelope (#604 slice 3 / ADR 0062): the deduped identity keys of
   * the blocking findings the runner must route through coder-fix. The runner
   * reads ONLY this off a `cmr_reviewed` row.
   */
  readonly blockingFindingIdentityKeys?: readonly string[];
  readonly stopSummary?: StopSummary;
  /** #930 — family judge session id for resume / prior-verdict rows. */
  readonly sessionId?: string;
  /** #930 — T2 judge status (continue / escalate / toolchain / unusable-re-furnace). */
  readonly judgeStatus?: import("../types.js").JudgeVerdictStatus;
  /**
   * #930 / #952 — disposition table for session-loss prior rows. Schema actions
   * (`refute` / `suppress` / `live`) — suppress is queryable here as
   * `action: "suppress"` (family does not dual-write store-status rows).
   */
  readonly findingDispositions?: ReadonlyArray<
    import("../types.js").JudgeFindingDisposition
  >;
  readonly advanceCoder?: string;
}

/** A separate coder-fix commit produced for a red integrated CMR finding (#550). */
export interface CmrFixCommittedRecord {
  readonly cmrPass: IntegratedCmrPass;
  readonly reason?: string;
  readonly familyHeadBefore?: string;
  readonly familyHeadAfter?: string;
  readonly blockingFindingIdentityKeys?: readonly string[];
  readonly stopSummary?: StopSummary;
  /** Barrier phase; defaults to `"final"`. `#961` checkpoints use `"correctness_checkpoint"`. */
  readonly phase?: VerifyCmrPhase;
  /**
   * #979 — Sandcastle session id of this coder-fix open. Ledger sole truth for
   * same-chain fix-round resume (mirrors #966 judge sessionId on cmr_reviewed).
   * Absent when the provider surfaced no id.
   */
  readonly sessionId?: string;
  /**
   * #1119 — refused finding keys when this builder beat was a legal refuse.
   * Cold-start pure receive reloads these from the fix row (not process memory).
   */
  readonly refusedFindingIdentityKeys?: readonly string[];
  /**
   * #1119 — opaque refuseRecords cargo for judge re-ruling after cold resume.
   */
  readonly refuseRecords?: ReadonlyArray<
    import("../types.js").ReviewFixRefuseRecord
  >;
}

/** A PHASE-LEVEL family escalation marker (#439). */
export interface FamilyEscalatedRecord {
  readonly escalationKind: EscalationKind;
  readonly phase?: VerifyCmrPhase;
  readonly reason?: string;
  readonly familyHeadAfter?: string;
  /** Unified stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
}

/** A PHASE-LEVEL append-only answer to a prior family decision escalation (#439). */
export interface FamilyEscalationAnswerRecord {
  readonly answer: string;
  readonly source: "human" | "resume_input";
  readonly note?: string;
  /**
   * When set, this answer answers a CHILD decision escalation (#604 slice 5): it
   * matches the `child_decision_parked` row carrying the SAME childIssue, so multiple
   * parked children can be answered separately.
   */
  readonly childIssue?: number;
}

/**
 * A CHILD-LEVEL decision-gate park ledger record (#604 slice 5). Recorded when a
 * child slice's own single-slice run parked on a product/design题
 * (`escalationKind:"decision"`). INDEPENDENT of the family's own `escalated` row —
 * this is a human DECISION GATE (park → resume), not an infra escalation/failure.
 */
export interface ChildDecisionParkedRecord {
  readonly childIssue: number;
  readonly reason: string;
  readonly diagnosis: string;
  /** The child's escalated single-slice worker session id, for 原地 resume. */
  readonly sessionId?: string;
  readonly familyHeadAfter?: string;
  readonly stopSummary?: StopSummary;
}

/** A production-admission child skip audit row (#450/#451). */
export interface AdmissionSkippedRecord {
  readonly issue: number;
  readonly reason: string;
  readonly message: string;
}

/**
 * Drop `undefined`-valued optional fields so the appended entry is clean
 * (`{childIssue, status}` with only the supplied extras — no `field: undefined`
 * noise, which would break `toEqual` and bloat the persisted JSONL).
 */
function compact<T extends Record<string, unknown>>(obj: T): T {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined) out[k] = v;
  }
  return out as T;
}

/**
 * Append one `merged` event to the family ledger.
 *
 * Called by the merger AFTER a child's merge commit has landed on the family
 * base (ADR 0022 decision 5: only write the `merged` entry once the merge commit
 * is on the base). Append-only — never mutates a prior entry.
 *
 * #298: accepts EITHER a bare child issue number (the #293 thin form, kept for
 * back-compat with the no-conflict merger) OR a full {@link MergedRecord} with
 * the event's full schema. The `status:"merged"` field is always stamped here.
 */
export async function recordMerged(
  backend: FamilyBackend,
  record: number | MergedRecord,
): Promise<void> {
  const r: MergedRecord =
    typeof record === "number" ? { childIssue: record } : record;
  await backend.appendFamilyLedger(
    compact({
      childIssue: r.childIssue,
      status: "merged",
      ...(r.event != null ? { event: r.event } : {}),
      childBranch: r.childBranch,
      childHead: r.childHead,
      wave: r.wave,
      familyHeadBefore: r.familyHeadBefore,
      familyHeadAfter: r.familyHeadAfter,
      conflictResolvedByLlm: r.conflictResolvedByLlm,
    }) as FamilyLedgerEntry,
  );
}

/**
 * Append one PHASE-LEVEL `aborted` event to the family ledger (ADR 0022 decision
 * 5: "verify/cmr 失败写 aborted 事件，携带当时 family head"; #291 缺口 2 unifies it
 * to phase-level).
 *
 * The verify-cmr hook calls this when a verify/cmr barrier returns red, so the
 * family base is left observably aborted ON THE DURABLE LEDGER (not only the
 * in-memory seam, and not silently a success). An abort is a failure of a whole
 * verify PHASE, not one child — so the durable entry carries `phase` + `reason` +
 * `familyHeadAfter` (the abort-time head, REUSING the field so reconcile's "read末条
 * familyHeadAfter" baseline covers merged AND aborted uniformly), and NO
 * `childIssue`. An `aborted` event is NOT counted as merged by {@link mergedSet}
 * (it has no `childIssue` and the wrong `status`), so it never unblocks a
 * downstream slice off a red barrier.
 */
export async function recordAborted(
  backend: FamilyBackend,
  record: AbortedRecord,
): Promise<void> {
  await backend.appendFamilyLedger(
    compact({
      status: "aborted",
      event: "aborted",
      phase: record.phase,
      cmrPass: record.cmrPass,
      reason: record.reason,
      familyHeadAfter: record.familyHeadAfter,
      blockingFindingIdentityKeys: record.blockingFindingIdentityKeys,
      stopSummary:
        record.stopSummary ??
        infraFailureStopSummary({
          summary: record.reason ?? "family barrier aborted",
          repairHint: "inspect this aborted ledger row, repair the barrier, and rerun",
          ...(record.familyHeadAfter != null
            ? {
                heads: {
                  actualFamilyHead: record.familyHeadAfter,
                  sources: { actualFamilyHead: "family aborted ledger row" },
                },
              }
            : {}),
        }),
    }) as FamilyLedgerEntry,
  );
}

/** Append one PHASE-LEVEL green integrated CMR pass audit event (#419). */
export async function recordCmrPassed(
  backend: FamilyBackend,
  record: CmrPassedRecord,
): Promise<void> {
  await backend.appendFamilyLedger(
    compact({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: record.phase ?? "final",
      cmrPass: record.cmrPass,
      familyHeadAfter: record.familyHeadAfter,
      routeFingerprint: record.routeFingerprint,
      sessionId: record.sessionId,
      judgeStatus: record.judgeStatus ?? "converged",
      findingDispositions: record.findingDispositions,
      advanceCoder: record.advanceCoder,
      stopSummary:
        record.stopSummary ??
        successStopSummary(
          record.familyHeadAfter != null
            ? {
                heads: {
                  verifiedCmrHead: record.familyHeadAfter,
                  sources: { verifiedCmrHead: "cmr_passed ledger row" },
                },
              }
            : undefined,
        ),
    }) as FamilyLedgerEntry,
  );
}

/** Append one PHASE-LEVEL red CMR review audit event before coder-fix (#550). */
export async function recordCmrReviewed(
  backend: FamilyBackend,
  record: CmrReviewedRecord,
): Promise<void> {
  await backend.appendFamilyLedger(
    compact({
      status: "cmr_reviewed",
      event: "cmr_reviewed",
      phase: record.phase ?? "final",
      cmrPass: record.cmrPass,
      reason: record.reason,
      familyHeadAfter: record.familyHeadAfter,
      blockingFindingIdentityKeys: record.blockingFindingIdentityKeys,
      sessionId: record.sessionId,
      judgeStatus: record.judgeStatus,
      findingDispositions: record.findingDispositions,
      advanceCoder: record.advanceCoder,
      stopSummary:
        record.stopSummary ??
        infraFailureStopSummary({
          summary: record.reason ?? "family CMR review returned blocking findings",
          repairHint:
            "inspect this CMR review row and the following coder-fix row before re-review",
          ...(record.familyHeadAfter != null
            ? {
                heads: {
                  actualFamilyHead: record.familyHeadAfter,
                  sources: { actualFamilyHead: "cmr_reviewed ledger row" },
                },
              }
            : {}),
        }),
    }) as FamilyLedgerEntry,
  );
}

/** Append one PHASE-LEVEL CMR coder-fix commit audit event (#550). */
export async function recordCmrFixCommitted(
  backend: FamilyBackend,
  record: CmrFixCommittedRecord,
): Promise<void> {
  const sessionId =
    typeof record.sessionId === "string" && record.sessionId.trim().length > 0
      ? record.sessionId.trim()
      : undefined;
  const refusedKeys =
    record.refusedFindingIdentityKeys !== undefined &&
    record.refusedFindingIdentityKeys.length > 0
      ? record.refusedFindingIdentityKeys
      : undefined;
  const refuseRecords =
    record.refuseRecords !== undefined && record.refuseRecords.length > 0
      ? record.refuseRecords
      : undefined;
  await backend.appendFamilyLedger(
    compact({
      status: "cmr_fix_committed",
      event: "cmr_fix_committed",
      phase: record.phase ?? "final",
      cmrPass: record.cmrPass,
      reason: record.reason,
      familyHeadBefore: record.familyHeadBefore,
      familyHeadAfter: record.familyHeadAfter,
      blockingFindingIdentityKeys: record.blockingFindingIdentityKeys,
      // #979: durable fixer-chain session continuity (ledger sole truth).
      ...(sessionId !== undefined ? { sessionId } : {}),
      // #1119: refuse traffic + opaque cargo for cold-start pure receive.
      ...(refusedKeys !== undefined
        ? { refusedFindingIdentityKeys: refusedKeys }
        : {}),
      ...(refuseRecords !== undefined ? { refuseRecords } : {}),
      stopSummary:
        record.stopSummary ??
        successStopSummary({
          ...(record.familyHeadAfter != null ||
          record.familyHeadBefore != null
            ? {
                heads: {
                  ...(record.familyHeadBefore != null
                    ? { reportedFamilyHead: record.familyHeadBefore }
                    : {}),
                  ...(record.familyHeadAfter != null
                    ? { actualFamilyHead: record.familyHeadAfter }
                    : {}),
                  sources: {
                    reportedFamilyHead: "cmr_fix_committed pre-fix head",
                    actualFamilyHead: "cmr_fix_committed post-fix head",
                  },
                },
              }
            : {}),
        }),
    }) as FamilyLedgerEntry,
  );
}

/**
 * #1119 — cold-start recovery of pending fresh review after a builder beat.
 *
 * Structured lifecycle only (no reason/answer prose parse). Newest same-pass
 * same-barrier row among:
 *   - `cmr_fix_committed` → pending fresh review
 *   - `cmr_reviewed` / `cmr_passed` → not pending
 *
 * Not the #1111 WHO-debt layer.
 */
export function pendingBuilderReviewFromFamilyLedger(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  pass: IntegratedCmrPass,
  phase: "final" | "correctness_checkpoint" = "final",
): {
  readonly pending: boolean;
  readonly refusedFindingIdentityKeys?: readonly string[];
  readonly refuseRecords?: ReadonlyArray<
    import("../types.js").ReviewFixRefuseRecord
  >;
  readonly familyHeadAfter?: string;
} {
  const barrierPhase = cmrBarrierPhaseOf(phase);
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    const status = entry.status ?? entry.event;
    if (
      status !== "cmr_fix_committed" &&
      status !== "cmr_reviewed" &&
      status !== "cmr_passed"
    ) {
      continue;
    }
    if (entry.cmrPass !== pass) continue;
    if (cmrBarrierPhaseOf(entry.phase) !== barrierPhase) continue;
    if (status === "cmr_fix_committed") {
      const refused =
        Array.isArray(entry.refusedFindingIdentityKeys) &&
        entry.refusedFindingIdentityKeys.length > 0
          ? entry.refusedFindingIdentityKeys
          : undefined;
      const records =
        Array.isArray(entry.refuseRecords) && entry.refuseRecords.length > 0
          ? entry.refuseRecords
          : undefined;
      return {
        pending: true,
        ...(refused !== undefined
          ? { refusedFindingIdentityKeys: refused }
          : {}),
        ...(records !== undefined ? { refuseRecords: records } : {}),
        ...(typeof entry.familyHeadAfter === "string" &&
        entry.familyHeadAfter.trim().length > 0
          ? { familyHeadAfter: entry.familyHeadAfter.trim() }
          : {}),
      };
    }
    return { pending: false };
  }
  return { pending: false };
}

/**
 * #979 — latest family coder-fix session id from `cmr_fix_committed` ledger rows.
 *
 * Same-pass only (completeness vs correctness are separate findings chains).
 * Newest matching fix row is sole authority: blank/missing sessionId → fresh
 * (never resurrect an older id under a fresh-open row — same CR-10 as #966).
 * A later `coder_advance` (model change) after any prior fix invalidates resume
 * so the new coder opens fresh; `coder_advance_stay_put` does not invalidate.
 * A later same-pass `cmr_passed` ends that findings chain — do not walk past it
 * to an older pre-pass fix session (R6-C1); a fix after pass is a new chain.
 */
export function familyCoderFixResumeSessionIdFromLedger(
  ledger: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly cmrPass?: string;
    readonly sessionId?: string;
  }>,
  pass: string,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    const status = entry.status ?? entry.event;
    if (status === "coder_advance") {
      // Seat reassigned after a prior fix — do not hand the old conversation to
      // the new model binding.
      return undefined;
    }
    if (status === "cmr_passed") {
      // Converged court ends this pass's findings chain. Prefer same-pass match;
      // if the pass field is absent on the event, treat as chain boundary too
      // (fail closed: never resume across an unscoped pass marker).
      if (entry.cmrPass === undefined || entry.cmrPass === pass) {
        return undefined;
      }
      continue;
    }
    if (status === "cmr_fix_committed") {
      if (entry.cmrPass !== pass) continue;
      const sid = entry.sessionId;
      // Align with recordCmrFixCommitted write-path trim: whitespace-only →
      // absent / fresh (never hand a blank token to Sandcastle resume).
      if (typeof sid !== "string") return undefined;
      const trimmed = sid.trim();
      return trimmed.length > 0 ? trimmed : undefined;
    }
  }
  return undefined;
}

/** Append a PHASE-LEVEL family escalation marker (#439). */
export async function recordFamilyEscalated(
  backend: FamilyBackend,
  record: FamilyEscalatedRecord,
): Promise<void> {
  await backend.appendFamilyLedger(
    compact({
      status: "escalated",
      event: "escalated",
      phase: record.phase,
      reason: record.reason,
      familyHeadAfter: record.familyHeadAfter,
      escalationKind: record.escalationKind,
      stopSummary:
        record.stopSummary ??
        infraFailureStopSummary({
          summary: record.reason ?? "family run escalated",
          repairHint: "inspect this escalation row and repair before rerun",
          ...(record.familyHeadAfter != null
            ? {
                heads: {
                  actualFamilyHead: record.familyHeadAfter,
                  sources: { actualFamilyHead: "family escalation ledger row" },
                },
              }
            : {}),
        }),
    }) as FamilyLedgerEntry,
  );
}

/**
 * Append a PHASE-LEVEL human answer to a family decision escalation (#439).
 * Child-bound answers inherit the parked worker session id so every durable
 * decision-gate container identifies the session that will be resumed.
 */
export async function recordFamilyEscalationAnswered(
  backend: FamilyBackend,
  record: FamilyEscalationAnswerRecord,
): Promise<void> {
  const answer = record.answer.trim();
  if (answer.length === 0) {
    throw new Error("family escalation answer must be a non-empty string");
  }
  const sessionId =
    record.childIssue !== undefined
      ? [...(await backend.readFamilyLedger())]
          .reverse()
          .find(
            (entry) =>
              isValidChildDecisionParked(entry) &&
              entry.childIssue === record.childIssue,
          )?.sessionId
      : undefined;
  await backend.appendFamilyLedger(
    compact({
      status: "escalation_answered",
      event: "escalation_answered",
      phase: "final",
      // #604 F1: carry childIssue so `isValidChildAnswer` (entry.childIssue ===
      // childIssue) can bind this answer to the parked child. Dropping it here
      // deadlocked the decision gate — a human-supplied answer never reopened the
      // parked child because the row could not be matched.
      childIssue: record.childIssue,
      sessionId,
      answer,
      source: record.source,
      note: record.note,
    }) as FamilyLedgerEntry,
  );
}

/**
 * Append a CHILD-LEVEL decision-gate PARK marker (#604 slice 5).
 *
 * Recorded when a child slice parked on a product/design decision题
 * (`escalationKind:"decision"`). Uses the INDEPENDENT `child_decision_parked`
 * event (NOT the family's own A-class `escalated` row) so the human decision gate
 * (park → resume) stays distinct from infra escalation/failure. The row carries
 * `childIssue` so several children can park + be resumed separately, and the
 * child's `sessionId` so a later resume re-enters IN PLACE.
 */
export async function recordChildDecisionParked(
  backend: FamilyBackend,
  record: ChildDecisionParkedRecord,
): Promise<void> {
  await backend.appendFamilyLedger(
    compact({
      childIssue: record.childIssue,
      status: "child_decision_parked",
      event: "child_decision_parked",
      phase: "wave",
      escalationKind: "decision",
      reason: record.reason,
      diagnosis: record.diagnosis,
      sessionId: record.sessionId,
      familyHeadAfter: record.familyHeadAfter,
      stopSummary:
        record.stopSummary ??
        decisionGateParkStopSummary({
          summary: record.reason,
          repairHint:
            "answer this child decision gate (append an escalation_answered row with the matching childIssue) and rerun the family to resume in place",
          ...(record.familyHeadAfter != null
            ? {
                heads: {
                  actualFamilyHead: record.familyHeadAfter,
                  sources: { actualFamilyHead: "family child decision-park ledger row" },
                },
              }
            : {}),
        }),
    }) as FamilyLedgerEntry,
  );
}

/**
 * Is this a valid, well-shaped `child_decision_parked` decision row (#604 slice 5)?
 * Single authority for "ledger-proven decision park" shape — family runner #970
 * injection gating reuses this (do not reimplement a weaker twin).
 */
export function isValidChildDecisionParked(
  entry: FamilyLedgerEntry,
): entry is FamilyLedgerEntry & { readonly childIssue: number } {
  return (
    entry.status === "child_decision_parked" &&
    entry.event === "child_decision_parked" &&
    entry.escalationKind === "decision" &&
    Number.isSafeInteger(entry.childIssue) &&
    (entry.childIssue ?? 0) > 0
  );
}

/** Is this a valid `escalation_answered` row bound to a specific child (#604 slice 5)? */
function isValidChildAnswer(
  entry: FamilyLedgerEntry,
  childIssue: number,
): boolean {
  return (
    entry.status === "escalation_answered" &&
    entry.event === "escalation_answered" &&
    entry.childIssue === childIssue &&
    typeof entry.answer === "string" &&
    entry.answer.trim().length > 0 &&
    // A durable JSONL round-trip can serialize an absent optional field as `null`
    // rather than omit it; `== null` accepts both null and undefined (the "no
    // source" intent) without accepting a real bad value.
    (entry.source == null ||
      entry.source === "human" ||
      entry.source === "resume_input")
  );
}

/**
 * The set of child issue numbers whose decision gate is STILL UNANSWERED
 * (#604 slice 5). A child is unanswered iff it has a `child_decision_parked` row
 * with no LATER matching `escalation_answered` row. The family runner returns
 * `status:"escalated"` while any child is unanswered.
 */
export function unansweredChildEscalations(
  entries: ReadonlyArray<FamilyLedgerEntry>,
): ReadonlyArray<FamilyLedgerEntry & { readonly childIssue: number }> {
  const out: (FamilyLedgerEntry & { readonly childIssue: number })[] = [];
  const seen = new Set<number>();
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (!isValidChildDecisionParked(entry)) continue;
    if (seen.has(entry.childIssue)) continue;
    seen.add(entry.childIssue);
    const answered = entries
      .slice(i + 1)
      .some((later) => isValidChildAnswer(later, entry.childIssue));
    if (!answered) out.push(entry);
  }
  return out.reverse();
}

function answerPayloadFromChildAnswer(
  entry: FamilyLedgerEntry,
): EscalationAnswerPayload {
  return {
    event: "escalation_answered",
    answer: entry.answer!,
    source: (entry.source ?? "human") as "human" | "resume_input",
    ...(entry.sessionId != null ? { sessionId: entry.sessionId } : {}),
    ...(entry.note != null ? { note: entry.note } : {}),
  };
}

/**
 * The human answer that reopens a specific child's parked decision gate
 * (#604 slice 5), or `undefined` when the child is not parked / not yet answered.
 * Reads the LATEST `child_decision_parked` for the child, then the latest matching
 * `escalation_answered` after it.
 */
export function childEscalationAnswer(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  childIssue: number,
): EscalationAnswerPayload | undefined {
  let escalatedIdx = -1;
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (isValidChildDecisionParked(entry) && entry.childIssue === childIssue) {
      escalatedIdx = i;
      break;
    }
  }
  if (escalatedIdx < 0) return undefined;
  for (let i = entries.length - 1; i > escalatedIdx; i--) {
    const entry = entries[i]!;
    if (isValidChildAnswer(entry, childIssue)) {
      return answerPayloadFromChildAnswer(entry);
    }
  }
  return undefined;
}

/**
 * #1019 — latest child-bound answer regardless of a preceding family park row.
 *
 * Mixed-wave failure+park historically dropped durable `child_decision_parked`
 * rows (#604 P1-a), so humans still answered from progress text but
 * {@link childEscalationAnswer} could not see the bind. Cross-launcher re-entry
 * must still feed that answer into fresh redispatch.
 */
export function latestChildBoundAnswer(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  childIssue: number,
): EscalationAnswerPayload | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (!isValidChildAnswer(entry, childIssue)) continue;
    return answerPayloadFromChildAnswer(entry);
  }
  return undefined;
}

/** Append one production-admission skip audit row. */
export async function recordAdmissionSkipped(
  backend: FamilyBackend,
  record: AdmissionSkippedRecord,
): Promise<void> {
  await backend.appendFamilyLedger(
    compact({
      childIssue: record.issue,
      status: "admission_skipped",
      event: "admission_skipped",
      phase: "wave",
      reason: record.reason,
      message: record.message,
      stopSummary: successStopSummary({
        admissionSkipped: [record],
      }),
    }) as FamilyLedgerEntry,
  );
}

/**
 * #1006 — durable audit when the admission baseline health gate fails closed
 * (family-base full suite red before fan-out). Not an unblock fact.
 */
export async function recordBaselineHealthFailed(
  backend: FamilyBackend,
  record: {
    readonly reason: string;
    readonly message: string;
    readonly familyHeadAfter?: string;
  },
): Promise<void> {
  await backend.appendFamilyLedger(
    compact({
      status: "baseline_health_failed",
      event: "baseline_health_failed",
      phase: "wave",
      reason: record.reason,
      message: record.message,
      ...(record.familyHeadAfter !== undefined
        ? { familyHeadAfter: record.familyHeadAfter }
        : {}),
    }) as FamilyLedgerEntry,
  );
}

function isValidFamilyAnswer(entry: FamilyLedgerEntry): boolean {
  return (
    entry.status === "escalation_answered" &&
    entry.event === "escalation_answered" &&
    entry.phase === "final" &&
    // #604 correctness r1 (P1-f): a FAMILY-level answer must NOT carry a
    // childIssue. A child-bound answer row (F1 added childIssue to child answers)
    // targets a specific parked CHILD via `isValidChildAnswer`; it must never
    // release an unrelated FAMILY-level decision escalation (which is the
    // `event:"escalated"` row that carries no childIssue).
    // `== null` (not `=== undefined`): a family-level answer must carry NO child
    // binding, and a JSONL round-trip can serialize that absence as `null`.
    entry.childIssue == null &&
    typeof entry.answer === "string" &&
    entry.answer.trim().length > 0 &&
    (entry.source == null ||
      entry.source === "human" ||
      entry.source === "resume_input") &&
    (entry.note == null || typeof entry.note === "string")
  );
}

function isValidFamilyShipped(
  entry: FamilyLedgerEntry,
): entry is FamilyLedgerEntry & { readonly pr: string; readonly familyHeadAfter: string } {
  return (
    entry.status === "shipped" &&
    entry.event === "shipped" &&
    entry.phase === "final" &&
    typeof entry.pr === "string" &&
    entry.pr.trim().length > 0 &&
    isCanonicalGithubPrUrl(entry.pr) &&
    typeof entry.familyHeadAfter === "string" &&
    entry.familyHeadAfter.trim().length > 0
  );
}

function isValidReviewLoopConverged(
  entry: FamilyLedgerEntry,
): entry is FamilyLedgerEntry & { readonly pr: string; readonly familyHeadAfter: string } {
  return (
    entry.status === "review_loop_converged" &&
    entry.event === "review_loop_converged" &&
    entry.phase === "final" &&
    typeof entry.pr === "string" &&
    entry.pr.trim().length > 0 &&
    typeof entry.familyHeadAfter === "string" &&
    entry.familyHeadAfter.trim().length > 0
  );
}

function isValidPrMerged(
  entry: FamilyLedgerEntry,
): entry is FamilyLedgerEntry & {
  readonly pr: string;
  readonly prNumber: number;
  readonly remoteBranchName: string;
  readonly mergedHeadOid: string;
  readonly familyHeadAfter: string;
} {
  return (
    entry.status === "pr_merged" &&
    entry.event === "pr_merged" &&
    entry.phase === "final" &&
    typeof entry.pr === "string" &&
    entry.pr.trim().length > 0 &&
    Number.isSafeInteger(entry.prNumber) &&
    entry.prNumber! > 0 &&
    typeof entry.remoteBranchName === "string" &&
    entry.remoteBranchName.trim().length > 0 &&
    typeof entry.mergedHeadOid === "string" &&
    entry.mergedHeadOid.trim().length > 0 &&
    typeof entry.familyHeadAfter === "string" &&
    entry.familyHeadAfter.trim().length > 0
  );
}

function familyAnswerPayload(entry: FamilyLedgerEntry): EscalationAnswerPayload {
  return {
    event: "escalation_answered",
    answer: entry.answer!,
    source: (entry.source ?? "human") as "human" | "resume_input",
    ...(entry.note != null ? { note: entry.note } : {}),
  };
}

export function isMergedAccountingEntry(
  entry: FamilyLedgerEntry,
): entry is FamilyLedgerEntry & { readonly childIssue: number } {
  return (
    entry.status === "merged" &&
    Number.isSafeInteger(entry.childIssue) &&
    entry.childIssue! > 0
  );
}

function latestValidFamilyAnswerAfter(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  index: number,
): EscalationAnswerPayload | undefined {
  for (let i = entries.length - 1; i > index; i--) {
    const entry = entries[i]!;
    if (isValidFamilyAnswer(entry)) return familyAnswerPayload(entry);
  }
  return undefined;
}

/**
 * Complete durable family escalation shape for terminal replay / ledger-without-worksite
 * (#934 ID-005). Incomplete `status:"escalated"` rows (missing `event:"escalated"` or
 * decision/failure kind) still surface via {@link familyEscalationState} so mid-run
 * pause stays fail-closed, but they are NOT terminal durable truth.
 */
export function isCompleteFamilyEscalation(entry: FamilyLedgerEntry): boolean {
  return (
    entry.status === "escalated" &&
    entry.event === "escalated" &&
    (entry.escalationKind === "decision" || entry.escalationKind === "failure")
  );
}

/** Latest family escalation and the later valid answer row that reopens it (#439). */
export function familyEscalationState(
  entries: ReadonlyArray<FamilyLedgerEntry>,
):
  | {
      readonly escalation: FamilyLedgerEntry;
      readonly answer?: EscalationAnswerPayload;
    }
  | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (isValidFamilyShipped(entry)) return undefined;
    if (isValidReviewLoopConverged(entry)) return undefined;
    if (entry.status !== "escalated") continue;
    // Incomplete escalated rows still pause mid-run (do not disappear) but are
    // not terminal-replayable — see isCompleteFamilyEscalation / scene recovery.
    if (entry.event !== "escalated") return { escalation: entry };
    const answer =
      entry.escalationKind === "decision"
        ? latestValidFamilyAnswerAfter(entries, i)
        : undefined;
    return answer !== undefined ? { escalation: entry, answer } : { escalation: entry };
  }
  return undefined;
}

/**
 * Barrier phase for CMR pass-admission / fix-chain reachability / ledger rows.
 * Missing or non-checkpoint phases normalize to `"final"` (legacy rows).
 * Sole normalizer for `correctness_checkpoint | final` (#982 / SHARED #19) —
 * verifyCmr and ledger share this export (do not fork a twin helper).
 */
export function cmrBarrierPhaseOf(
  phase: string | undefined,
): "final" | "correctness_checkpoint" {
  return phase === "correctness_checkpoint"
    ? "correctness_checkpoint"
    : "final";
}

/**
 * Heads reachable from `fromHead` by walking same-barrier
 * `cmr_fix_committed` rows that appear AFTER `startIndex` and whose
 * `familyHeadBefore` is already reachable.
 *
 * Phase is scoped (#982 Codex P1 / #961): a `correctness_checkpoint` pass only
 * extends via checkpoint-phase fix commits; a `final` pass only via final-phase
 * fixes. Cross-phase fix advances must not free-skip a different court.
 *
 * Fail closed: incomplete fix rows (missing before/after) never extend the
 * set; pre-pass fix rows are ignored because the scan starts after the pass.
 */
function barrierInternalHeadsReachableFrom(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  startIndex: number,
  fromHead: string,
  barrierPhase: "final" | "correctness_checkpoint",
): Set<string> {
  const reachable = new Set<string>([fromHead]);
  for (let i = startIndex + 1; i < entries.length; i++) {
    const e = entries[i]!;
    if (
      e.status !== "cmr_fix_committed" ||
      e.event !== "cmr_fix_committed" ||
      cmrBarrierPhaseOf(e.phase) !== barrierPhase
    ) {
      continue;
    }
    const before =
      typeof e.familyHeadBefore === "string" ? e.familyHeadBefore.trim() : "";
    const after =
      typeof e.familyHeadAfter === "string" ? e.familyHeadAfter.trim() : "";
    if (before.length === 0 || after.length === 0) continue;
    if (reachable.has(before)) reachable.add(after);
  }
  return reachable;
}

/**
 * Did a specific integrated CMR pass already pass for the CURRENT family base
 * HEAD (or an earlier head in the same barrier whose subsequent advance is
 * explained only by barrier-internal fix commits)?
 *
 * Resume guard (#434, revised #881 to match live barrier semantics; #961
 * checkpoint phase; #982 separates checkpoint vs final admission):
 *   - exact head match on a complete `cmr_passed` row of the **same phase** → skip
 *   - head advanced ONLY via same-phase barrier-internal `cmr_fix_committed`
 *     chain after that pass marker → skip
 *   - head advanced without such a chain (barrier-external or other phase) → re-verify
 *   - a `correctness_checkpoint` green never free-skips a later `final` court
 *     (checkpoint reuse is for checkpoint admission / same-barrier resume only)
 *
 * Fails closed when the current head is missing or the ledger row lacks the
 * complete cmr_passed shape (status/event/pass/head/routeFingerprint).
 */
export function cmrPassAlreadyPassed(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  input: {
    readonly cmrPass: IntegratedCmrPass;
    readonly familyHeadAfter?: string;
    readonly routeFingerprint?: string;
    /**
     * Court phase asking for admission. Defaults to `"final"`.
     * Checkpoint and final are distinct for pass reuse (#982).
     */
    readonly phase?: "final" | "correctness_checkpoint";
  },
): boolean {
  if (
    input.familyHeadAfter === undefined ||
    input.familyHeadAfter.trim().length === 0
  ) {
    return false;
  }
  if (
    input.routeFingerprint === undefined ||
    input.routeFingerprint.trim().length === 0
  ) {
    return false;
  }
  const currentHead = input.familyHeadAfter.trim();
  const routeFingerprint = input.routeFingerprint.trim();
  const queryPhase = cmrBarrierPhaseOf(input.phase);

  for (let i = 0; i < entries.length; i++) {
    const e = entries[i]!;
    if (
      e.status !== "cmr_passed" ||
      e.event !== "cmr_passed" ||
      // #982: checkpoint ≢ final for final-court skip.
      cmrBarrierPhaseOf(e.phase) !== queryPhase ||
      e.cmrPass !== input.cmrPass ||
      e.familyHeadAfter === undefined ||
      e.familyHeadAfter.trim().length === 0 ||
      e.routeFingerprint === undefined ||
      e.routeFingerprint.trim() !== routeFingerprint
    ) {
      continue;
    }
    const passHead = e.familyHeadAfter.trim();
    if (passHead === currentHead) return true;
    // #881: same barrier + same phase, head advanced only by barrier-internal fixes.
    const reachable = barrierInternalHeadsReachableFrom(
      entries,
      i,
      passHead,
      queryPhase,
    );
    if (reachable.has(currentHead)) return true;
  }
  return false;
}

/**
 * #961 / ADR 0139 — durable `lastCorrectnessConvergedHead` single source.
 *
 * Pure reader over the family ledger: the latest green correctness
 * `cmr_passed` row's `familyHeadAfter` (checkpoint or final). Written only via
 * {@link recordCmrPassed} for `cmrPass:"correctness"` (Integrated Correctness
 * Action / Family Flow). Runner must not read this for admission or park.
 */
export function lastCorrectnessConvergedHeadFromLedger(
  entries: ReadonlyArray<FamilyLedgerEntry>,
): string | undefined {
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i]!;
    if (
      e.status !== "cmr_passed" ||
      e.event !== "cmr_passed" ||
      e.cmrPass !== "correctness"
    ) {
      continue;
    }
    const head =
      typeof e.familyHeadAfter === "string" ? e.familyHeadAfter.trim() : "";
    if (head.length > 0) return head;
  }
  return undefined;
}

/**
 * Append the PHASE-LEVEL `shipped` terminal marker to the family ledger (online
 * review r2, codex P1).
 *
 * The verify-cmr hook calls this AFTER the terminal 止于-PR family ship succeeds
 * (a real family PR opened on the family base). Without it, the family ship commit
 * (VERSION/CHANGELOG bump) advances the base but nothing records that the terminal
 * ship already ran — so on a re-feed/resume the spine would re-enter the final
 * barrier (full verify → integrated cmr → 止于-PR) and re-bump / re-open the PR.
 * The durable `shipped` entry is the spine's resume "already delivered" truth
 * ({@link familyAlreadyShipped}). It is NOT counted as merged by {@link mergedSet}
 * (no `childIssue`, `status:"shipped"`), so it never unblocks a slice.
 */
export async function recordShipped(
  backend: FamilyBackend,
  record: ShippedRecord,
): Promise<void> {
  const pr = record.pr.trim();
  const familyHeadAfter = record.familyHeadAfter.trim();
  if (pr.length === 0) {
    throw new Error("family shipped marker must include a non-empty PR URL");
  }
  if (familyHeadAfter.length === 0) {
    throw new Error("family shipped marker must include a non-empty familyHeadAfter");
  }
  // #1090 write-side guard: share the canonical URL predicate with every
  // shipped-PR consumer so permissive parser forms can never poison the ledger.
  if (!isCanonicalGithubPrUrl(pr)) {
    throw new Error(
      `family shipped marker pr must be a canonical https GitHub PR URL containing ` +
        `/pull/<number> (got "${pr}"); refusing to write a branch name or ` +
        `non-URL as the shipped ledger pr (#1090 — would poison the online ` +
        `review poll on idempotent re-ship)`,
    );
  }
  await backend.appendFamilyLedger(
    compact({
      status: "shipped",
      event: "shipped",
      phase: "final",
      pr,
      familyHeadAfter,
      ts: new Date().toISOString(),
      stopSummary:
        record.stopSummary ??
        successStopSummary({
          heads: {
            actualFamilyHead: familyHeadAfter,
            sources: { actualFamilyHead: "shipped ledger row" },
          },
        }),
    }) as FamilyLedgerEntry,
  );
  // #1007: first successful ship must echo progress (resume path also echoes;
  // missing here left the only ship event on re-entry, not the open).
  // Align epic with resume path when ambient progress config has it.
  emitShipProgress({
    epic: getProgressBroadcastConfig().epic,
    pr,
    familyHead: familyHeadAfter,
  });
}

/**
 * Did the terminal family ship already succeed for THIS family HEAD? True only
 * when a complete `status:"shipped"` marker is on the ledger and its
 * `familyHeadAfter` equals the current family HEAD. The spine reads this BEFORE
 * the final barrier so an already-delivered family run is not re-shipped, while a
 * later live HEAD advance is re-verified / re-shipped instead of being hidden by
 * an older PR marker.
 */
export function familyAlreadyShipped(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string | undefined,
): boolean {
  return familyShippedRecordForHead(entries, familyHeadAfter) !== undefined;
}

/** Online-review loop markers prove an in-progress round at `familyHeadAfter`. */
export function familyOnlineReviewLoopInProgressForHead(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string,
): boolean {
  const head = familyHeadAfter.trim();
  if (head.length === 0) return false;
  return entries.some(
    (e) =>
      (e.event === "online_review_fix_committed" &&
        e.familyHeadAfter === head) ||
      (e.event === "online_review_round_retrigger" &&
        e.roundTriggerHeadOid === head),
  );
}

/**
 * Shipped resume anchor for the online review-loop (#600 r28).
 *
 * Exact head match first; when an in-loop fixer advanced HEAD past the shipped
 * marker, accept the ancestor shipped row plus fix/retrigger markers for the
 * current head chain.
 */
export function familyShippedRecordForReviewLoopResume(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string | undefined,
): ShippedRecord | undefined {
  const exact = familyShippedRecordForHead(entries, familyHeadAfter);
  if (exact != null) return exact;
  if (familyHeadAfter === undefined || familyHeadAfter.trim().length === 0) {
    return undefined;
  }
  const currentHead = familyHeadAfter.trim();
  if (!familyOnlineReviewLoopInProgressForHead(entries, currentHead)) {
    return undefined;
  }
  let markerPr: string | undefined;
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    const markerHead =
      entry.event === "online_review_fix_committed" &&
      typeof entry.familyHeadAfter === "string"
        ? entry.familyHeadAfter.trim()
        : entry.event === "online_review_round_retrigger" &&
            typeof entry.roundTriggerHeadOid === "string"
          ? entry.roundTriggerHeadOid.trim()
          : undefined;
    if (markerHead === undefined || markerHead !== currentHead) {
      continue;
    }
    if (typeof entry.pr === "string" && entry.pr.trim().length > 0) {
      markerPr = entry.pr.trim();
      break;
    }
  }
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      isValidFamilyShipped(entry) &&
      typeof entry.pr === "string" &&
      entry.pr.trim().length > 0 &&
      typeof entry.familyHeadAfter === "string" &&
      entry.familyHeadAfter.trim().length > 0 &&
      entry.familyHeadAfter !== currentHead &&
      (markerPr === undefined || entry.pr.trim() === markerPr)
    ) {
      return {
        pr: entry.pr,
        familyHeadAfter: entry.familyHeadAfter,
        ...(entry.stopSummary !== undefined
          ? { stopSummary: entry.stopSummary }
          : {}),
      };
    }
  }
  return undefined;
}

/**
 * Latest valid `shipped` marker for **this** barrier head that has not yet
 * reached `review_loop_converged` for the same PR+head. Used for in-process
 * online-review re-entry after `recordShipped` (quota wall must not re-ship).
 *
 * Correctness N1 / F1 residual:
 * - Open shipped must match the **current family head / PR tip** — any-head open
 *   shipped must not hijack final verify/CMR/ship.
 * - Historical `review_loop_converged` on the same PR at an older head must not
 *   wipe a later ship at a new head (converge is head-scoped).
 */
export function familyOpenShippedForOnlineReview(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string | undefined,
): ShippedRecord | undefined {
  if (familyHeadAfter == null || familyHeadAfter.trim().length === 0) {
    return undefined;
  }
  const head = familyHeadAfter.trim();
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (!isValidFamilyShipped(entry)) continue;
    // Only the ship for THIS barrier head may skip re-ship.
    if (entry.familyHeadAfter !== head) continue;
    const pr = entry.pr.trim();
    const alreadyConverged = entries.some(
      (e) =>
        isValidReviewLoopConverged(e) &&
        e.pr.trim() === pr &&
        e.familyHeadAfter === head,
    );
    if (alreadyConverged) continue;
    return {
      pr,
      familyHeadAfter: entry.familyHeadAfter,
      ...(entry.stopSummary !== undefined
        ? { stopSummary: entry.stopSummary }
        : {}),
    };
  }
  return undefined;
}

export function familyShippedRecordForHead(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string | undefined,
): ShippedRecord | undefined {
  // Fail-CLOSED on a malformed row (online review r3, coderabbit): the spine skips
  // the final barrier on this, so a corrupt/hand-edited `status:"shipped"` row with
  // no real delivery must NOT bypass verify/cmr/ship. Require the COMPLETE shape
  // `recordShipped` writes — status + event + final phase + a non-blank `pr` URL
  // + a non-blank `familyHeadAfter` — so only a genuine ship for the current HEAD
  // counts.
  if (familyHeadAfter == null || familyHeadAfter.trim().length === 0) return undefined;
  const shipped = entries.find(
    (e): e is FamilyLedgerEntry & { readonly pr: string; readonly familyHeadAfter: string } =>
      isValidFamilyShipped(e) && e.familyHeadAfter === familyHeadAfter,
  );
  if (shipped == null) return undefined;
  return {
    pr: shipped.pr,
    familyHeadAfter: shipped.familyHeadAfter,
    ...(shipped.stopSummary != null
      ? { stopSummary: shipped.stopSummary }
      : {}),
  };
}

/** Append one online-review fixer commit audit row (#600 r26 family resume). */
export async function recordOnlineReviewFixCommitted(
  backend: FamilyBackend,
  record: {
    readonly familyHeadAfter: string;
    readonly pr?: string;
    /** 1-based online-review round that produced this fix (#711 prior rounds). */
    readonly onlineReviewRound?: number;
    /** Fix-marked identity keys from the verify that drove this fix (#711). */
    readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
    /** Original thread binding for each fix-marked identity (#743 resume authority). */
    readonly fixMarkedFindingThreads?: ReadonlyArray<{
      readonly identityKey: string;
      readonly threadId: string;
    }>;
  },
): Promise<void> {
  const familyHeadAfter = record.familyHeadAfter.trim();
  if (familyHeadAfter.length === 0) {
    throw new Error(
      "family online_review_fix_committed marker must include a non-empty familyHeadAfter",
    );
  }
  const fixKeys =
    record.fixMarkedFindingIdentityKeys !== undefined
      ? record.fixMarkedFindingIdentityKeys.filter(
          (k) => typeof k === "string" && k.trim().length > 0,
        )
      : [];
  const fixThreads = (record.fixMarkedFindingThreads ?? []).flatMap((binding) =>
    typeof binding.identityKey === "string" &&
    binding.identityKey.trim().length > 0 &&
    typeof binding.threadId === "string" &&
    binding.threadId.trim().length > 0
      ? [{ identityKey: binding.identityKey, threadId: binding.threadId }]
      : [],
  );
  await backend.appendFamilyLedger(
    compact({
      status: "online_review_fix_committed",
      event: "online_review_fix_committed",
      phase: "final",
      familyHeadAfter,
      ...(record.pr !== undefined && record.pr.trim().length > 0
        ? { pr: record.pr.trim() }
        : {}),
      ...(typeof record.onlineReviewRound === "number" &&
      Number.isSafeInteger(record.onlineReviewRound) &&
      record.onlineReviewRound >= 1
        ? { onlineReviewRound: record.onlineReviewRound }
        : {}),
      ...(fixKeys.length > 0
        ? { fixMarkedFindingIdentityKeys: fixKeys }
        : {}),
      ...(fixThreads.length > 0
        ? { fixMarkedFindingThreads: fixThreads }
        : {}),
      ts: new Date().toISOString(),
    }) as FamilyLedgerEntry,
  );
}

/** Append one online-review round ≥2 freshness anchor (#600 r26 family resume). */
export async function recordOnlineReviewRoundRetrigger(
  backend: FamilyBackend,
  record: {
    readonly roundTriggerHeadOid: string;
    readonly roundTriggerAt: string;
    readonly onlineReviewRound: number;
    readonly pr?: string;
  },
): Promise<void> {
  const headOid = record.roundTriggerHeadOid.trim();
  const triggeredAt = record.roundTriggerAt.trim();
  const onlineReviewRound = record.onlineReviewRound;
  if (headOid.length === 0 || triggeredAt.length === 0) {
    throw new Error(
      "family online_review_round_retrigger marker must include roundTriggerHeadOid and roundTriggerAt",
    );
  }
  if (!Number.isSafeInteger(onlineReviewRound) || onlineReviewRound < 2) {
    throw new Error(
      "family online_review_round_retrigger marker must include onlineReviewRound >= 2",
    );
  }
  await backend.appendFamilyLedger(
    compact({
      status: "online_review_round_retrigger",
      event: "online_review_round_retrigger",
      phase: "final",
      roundTriggerHeadOid: headOid,
      roundTriggerAt: triggeredAt,
      onlineReviewRound,
      ...(record.pr !== undefined && record.pr.trim().length > 0
        ? { pr: record.pr.trim() }
        : {}),
      ts: new Date().toISOString(),
    }) as FamilyLedgerEntry,
  );
}

/**
 * Append the PHASE-LEVEL `review_loop_converged` terminal marker to the family
 * ledger (#596).
 *
 * The verify-cmr hook calls this AFTER the online review/PR-check loop has
 * converged for the shipped PR. Without it, the family spine would treat the
 * intermediate `shipped` marker as terminal and skip re-running the final
 * barrier on a later live HEAD advance.
 */
export async function recordReviewLoopConverged(
  backend: FamilyBackend,
  record: ReviewLoopConvergedRecord,
): Promise<void> {
  const pr = record.pr.trim();
  const familyHeadAfter = record.familyHeadAfter.trim();
  if (pr.length === 0) {
    throw new Error("family review_loop_converged marker must include a non-empty PR URL");
  }
  if (familyHeadAfter.length === 0) {
    throw new Error(
      "family review_loop_converged marker must include a non-empty familyHeadAfter",
    );
  }
  await backend.appendFamilyLedger(
    compact({
      status: "review_loop_converged",
      event: "review_loop_converged",
      phase: "final",
      pr,
      familyHeadAfter,
      stopSummary:
        record.stopSummary ??
        successStopSummary({
          heads: {
            actualFamilyHead: familyHeadAfter,
            sources: { actualFamilyHead: "review_loop_converged ledger row" },
          },
        }),
    }) as FamilyLedgerEntry,
  );
}

/**
 * Did the terminal family review loop already converge for THIS family HEAD?
 * True only when a complete `status:"review_loop_converged"` marker is on the
 * ledger and its `familyHeadAfter` equals the current family HEAD. The spine
 * reads this BEFORE the final barrier so a fully-converged family run is not
 * re-run, while a later live HEAD advance is re-verified / re-shipped / re-looped
 * instead of being hidden by an older marker.
 */
export function familyReviewLoopConvergedForHead(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string | undefined,
): ReviewLoopConvergedRecord | undefined {
  if (familyHeadAfter == null || familyHeadAfter.trim().length === 0) return undefined;
  const converged = entries.find(
    (e): e is FamilyLedgerEntry & { readonly pr: string; readonly familyHeadAfter: string } =>
      isValidReviewLoopConverged(e) && e.familyHeadAfter === familyHeadAfter,
  );
  if (converged == null) return undefined;
  return {
    pr: converged.pr,
    familyHeadAfter: converged.familyHeadAfter,
    ...(converged.stopSummary != null
      ? { stopSummary: converged.stopSummary }
      : {}),
  };
}

/**
 * Append the PHASE-LEVEL `docs_released` marker (landing docs before merge).
 * Keyed by post-release family HEAD so resume skips a second VERSION/CHANGELOG.
 */
export async function recordDocsReleased(
  backend: FamilyBackend,
  record: DocsReleasedRecord,
): Promise<void> {
  const pr = record.pr.trim();
  const familyHeadAfter = record.familyHeadAfter.trim();
  if (pr.length === 0) {
    throw new Error("family docs_released marker must include a non-empty PR URL");
  }
  if (familyHeadAfter.length === 0) {
    throw new Error(
      "family docs_released marker must include a non-empty familyHeadAfter",
    );
  }
  await backend.appendFamilyLedger(
    compact({
      status: "docs_released",
      event: "docs_released",
      phase: "final",
      pr,
      familyHeadAfter,
      stopSummary:
        record.stopSummary ??
        successStopSummary({
          heads: {
            actualFamilyHead: familyHeadAfter,
            sources: { actualFamilyHead: "docs_released ledger row" },
          },
        }),
    }) as FamilyLedgerEntry,
  );
}

export function isValidDocsReleased(
  entry: FamilyLedgerEntry,
): entry is FamilyLedgerEntry & {
  readonly status: "docs_released";
  readonly event: "docs_released";
  readonly pr: string;
  readonly familyHeadAfter: string;
} {
  return (
    entry.status === "docs_released" &&
    entry.event === "docs_released" &&
    typeof entry.pr === "string" &&
    entry.pr.trim().length > 0 &&
    typeof entry.familyHeadAfter === "string" &&
    entry.familyHeadAfter.trim().length > 0
  );
}

/** Docs-release completion row for THIS family HEAD (landing crash re-entry). */
export function familyDocsReleasedForHead(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string | undefined,
): DocsReleasedRecord | undefined {
  if (familyHeadAfter === undefined || familyHeadAfter.trim().length === 0) {
    return undefined;
  }
  for (const e of entries) {
    if (!isValidDocsReleased(e)) continue;
    if (e.familyHeadAfter !== familyHeadAfter) continue;
    return {
      pr: e.pr,
      familyHeadAfter: e.familyHeadAfter,
      ...(e.stopSummary !== undefined ? { stopSummary: e.stopSummary } : {}),
    };
  }
  return undefined;
}

/**
 * Append the PHASE-LEVEL `pr_merged` terminal marker (#602).
 */
export async function recordPrMerged(
  backend: FamilyBackend,
  record: PrMergedRecord,
): Promise<void> {
  const pr = record.pr.trim();
  const familyHeadAfter = record.familyHeadAfter.trim();
  const remoteBranchName = record.remoteBranchName.trim();
  const mergedHeadOid = record.mergedHeadOid.trim();
  if (pr.length === 0) {
    throw new Error("family pr_merged marker must include a non-empty PR URL");
  }
  if (familyHeadAfter.length === 0) {
    throw new Error("family pr_merged marker must include a non-empty familyHeadAfter");
  }
  if (remoteBranchName.length === 0) {
    throw new Error("family pr_merged marker must include a non-empty remoteBranchName");
  }
  if (mergedHeadOid.length === 0) {
    throw new Error("family pr_merged marker must include a non-empty mergedHeadOid");
  }
  if (!Number.isSafeInteger(record.prNumber) || record.prNumber <= 0) {
    throw new Error("family pr_merged marker must include a positive prNumber");
  }
  await backend.appendFamilyLedger(
    compact({
      status: "pr_merged",
      event: "pr_merged",
      phase: "final",
      pr,
      prNumber: record.prNumber,
      remoteBranchName,
      mergedHeadOid,
      familyHeadAfter,
      stopSummary:
        record.stopSummary ??
        successStopSummary({
          heads: {
            actualFamilyHead: familyHeadAfter,
            sources: { actualFamilyHead: "pr_merged ledger row" },
          },
        }),
    }) as FamilyLedgerEntry,
  );
}

/** Fields a #603 post_merge_cleanup terminal event carries. */
export interface PostMergeCleanupRecord {
  readonly familyHeadAfter: string;
  readonly cleanupOutput: CleanupResult;
}

export function isValidPostMergeCleanup(
  entry: FamilyLedgerEntry,
): entry is FamilyLedgerEntry & {
  readonly status: "post_merge_cleanup";
  readonly event: "post_merge_cleanup";
  readonly familyHeadAfter: string;
  readonly cleanupOutput: CleanupResult;
} {
  return (
    entry.status === "post_merge_cleanup" &&
    entry.event === "post_merge_cleanup" &&
    typeof entry.familyHeadAfter === "string" &&
    entry.familyHeadAfter.trim().length > 0 &&
    entry.cleanupOutput !== undefined &&
    isValidCleanupResult(entry.cleanupOutput)
  );
}

/**
 * Append the PHASE-LEVEL `post_merge_cleanup` terminal marker (#603).
 */
export async function recordPostMergeCleanup(
  backend: FamilyBackend,
  record: PostMergeCleanupRecord,
): Promise<void> {
  const familyHeadAfter = record.familyHeadAfter.trim();
  if (familyHeadAfter.length === 0) {
    throw new Error(
      "family post_merge_cleanup marker must include a non-empty familyHeadAfter",
    );
  }
  if (!isValidCleanupResult(record.cleanupOutput)) {
    throw new Error(
      "family post_merge_cleanup marker must include a valid cleanupOutput",
    );
  }
  await backend.appendFamilyLedger(
    compact({
      status: "post_merge_cleanup",
      event: "post_merge_cleanup",
      phase: "final",
      familyHeadAfter,
      cleanupOutput: record.cleanupOutput,
      stopSummary: successStopSummary({
        heads: {
          actualFamilyHead: familyHeadAfter,
          sources: { actualFamilyHead: "post_merge_cleanup ledger row" },
        },
      }),
    }) as FamilyLedgerEntry,
  );
}

export function familyPrMergedForHead(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string | undefined,
): PrMergedRecord | undefined {
  if (familyHeadAfter === undefined || familyHeadAfter.trim().length === 0) {
    return undefined;
  }
  const merged = entries.find(
    (e) => isValidPrMerged(e) && e.familyHeadAfter === familyHeadAfter,
  );
  if (merged === undefined) return undefined;
  const row = merged as FamilyLedgerEntry & {
    readonly pr: string;
    readonly prNumber: number;
    readonly remoteBranchName: string;
    readonly mergedHeadOid: string;
    readonly familyHeadAfter: string;
  };
  return {
    pr: row.pr,
    prNumber: row.prNumber,
    remoteBranchName: row.remoteBranchName,
    mergedHeadOid: row.mergedHeadOid,
    familyHeadAfter: row.familyHeadAfter,
    ...(row.stopSummary !== undefined ? { stopSummary: row.stopSummary } : {}),
  };
}

/**
 * Terminal+ok `post_merge_cleanup` row for THIS family HEAD (#603).
 * Resume / already_done success requires this after `pr_merged`.
 */
export function familyPostMergeCleanupForHead(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string | undefined,
):
  | (FamilyLedgerEntry & {
      readonly status: "post_merge_cleanup";
      readonly event: "post_merge_cleanup";
      readonly familyHeadAfter: string;
      readonly cleanupOutput: CleanupResult;
    })
  | undefined {
  if (familyHeadAfter === undefined || familyHeadAfter.trim().length === 0) {
    return undefined;
  }
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (!isValidPostMergeCleanup(entry)) continue;
    if (entry.familyHeadAfter !== familyHeadAfter) continue;
    if (
      entry.cleanupOutput.terminal === true &&
      entry.cleanupOutput.ok === true
    ) {
      return entry;
    }
  }
  return undefined;
}

/**
 * Derive the set of merged child issue numbers from the ledger entries.
 *
 * This is the unblock truth the commander reads (ADR 0022 decision 6②): a child
 * unblocks once every issue it is `blocked_by` is in this set. The filter is on
 * `status === "merged"` ONLY, which (decision 5) means:
 *   - a live merge (`status:"merged"`) COUNTS;
 *   - a reconcile補账条 (`status:"merged"` + `event:"reconciled"`) COUNTS too —
 *     it carries `status:"merged"` precisely so the predicate counts it and the
 *     reconciled blocker's downstream child is NOT判未合死锁 (codex R3);
 *   - an `aborted` event (`status:"aborted"`) does NOT count — a child whose
 *     barrier failed stays blocked.
 */
export function mergedSet(
  entries: ReadonlyArray<FamilyLedgerEntry>,
): ReadonlySet<number> {
  const out = new Set<number>();
  for (const e of entries) {
    // Only `status:"merged"` entries count, and only via their `childIssue`. A
    // PHASE-LEVEL `aborted` entry (#291 缺口 2) has the wrong status AND no
    // `childIssue`; the `childIssue !== undefined` guard makes optionality explicit.
    if (isMergedAccountingEntry(e)) out.add(e.childIssue!);
  }
  return out;
}

/**
 * Known {@link FamilyLedgerEntry.status} values. Shape gate for JSONL parse —
 * a line that JSON.parses as `null` / `{}` / bad status must fail closed the
 * same way as an unparseable line (#934 S-3; mirror single-slice isLedgerEntryShape).
 * Built from {@link FAMILY_LEDGER_STATUS_VALUES} — no hand-synced twin list.
 */
export const FAMILY_LEDGER_STATUSES: ReadonlySet<string> = new Set(
  FAMILY_LEDGER_STATUS_VALUES,
);

/**
 * Per-line structural gate for family-ledger.jsonl (#934 S-3).
 * Thin `{childIssue, status:"merged"}` remains valid; null/primitive/array/{}
 * and unknown status values are not.
 */
export function isFamilyLedgerEntryShape(
  value: unknown,
): value is FamilyLedgerEntry {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const status = (value as { status?: unknown }).status;
  if (typeof status !== "string" || !FAMILY_LEDGER_STATUSES.has(status)) {
    return false;
  }
  const childIssue = (value as { childIssue?: unknown }).childIssue;
  if (
    childIssue !== undefined &&
    (typeof childIssue !== "number" ||
      !Number.isSafeInteger(childIssue) ||
      childIssue <= 0)
  ) {
    return false;
  }
  return true;
}

/**
 * Reconstruct durable process-root attempts already consumed for a family
 * worker step (#934 ID-004 / #937). Mirrors single-slice
 * `mechanicalRedispatchAttemptsFor`: walk the ledger tail, count trailing
 * failure markers for this workerStep, stop at any non-spawn boundary so a
 * later successful phase does not inherit an earlier crash streak.
 */
export function mechanicalRedispatchAttemptsFromFamilyLedger(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
  workerStep: string,
): number {
  let durableAttempts = 0;
  for (let index = ledger.length - 1; index >= 0; index--) {
    const entry = ledger[index]!;
    const attempt = entry.mechanicalRedispatchAttempt;
    if (
      entry.event === "worker_dispatched" &&
      entry.workerStep === workerStep &&
      typeof attempt === "number" &&
      Number.isSafeInteger(attempt) &&
      attempt >= 1
    ) {
      durableAttempts = Math.max(durableAttempts, attempt);
      continue;
    }
    // Spawn adoption / advisory git telemetry: worker_dispatched without a
    // retry counter — skip so inter-retry spawn rows do not reset the streak.
    if (
      entry.event === "worker_dispatched" &&
      entry.mechanicalRedispatchAttempt === undefined
    ) {
      continue;
    }
    // Any other durable fact (phase success, escalate, merge, …) is a budget
    // boundary for this workerStep.
    break;
  }
  return durableAttempts;
}

/**
 * Parse family-ledger.jsonl fail-closed: every non-empty line must JSON.parse
 * AND pass {@link isFamilyLedgerEntryShape}. Blank lines tolerated.
 */
export function parseFamilyLedgerJsonl(raw: string): FamilyLedgerEntry[] {
  const entries: FamilyLedgerEntry[] = [];
  for (const line of raw.split("\n")) {
    if (line.trim().length === 0) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch (err) {
      throw new Error(
        `corrupt family ledger: a non-empty family-ledger.jsonl line failed to parse — ` +
          `refusing to resume on a partially-readable ledger (fail closed): ${
            err instanceof Error ? err.message : String(err)
          }`,
      );
    }
    if (!isFamilyLedgerEntryShape(parsed)) {
      throw new Error(
        "corrupt family ledger: a family-ledger.jsonl line parsed but is not a " +
          "valid FamilyLedgerEntry (must be an object with a known status) — " +
          "refusing to resume on a malformed ledger (fail closed).",
      );
    }
    entries.push(parsed);
  }
  return entries;
}
