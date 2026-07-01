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

import type { EscalationAnswerPayload, EscalationKind } from "../types.js";
import {
  infraFailureStopSummary,
  successStopSummary,
  type StopSummary,
} from "../stopSummary.js";
import type { FamilyCmrClassification } from "./cmrClassification.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  IntegratedCmrPass,
} from "./types.js";

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
  readonly phase: "wave" | "final";
  /** Which integrated CMR pass failed, when the abort came from a CMR pass. */
  readonly cmrPass?: IntegratedCmrPass;
  /** Human-readable abort reason (the verify error / cmr non-convergence). */
  readonly reason?: string;
  /** The family base HEAD at the time the barrier failed (for triage + baseline). */
  readonly familyHeadAfter?: string;
  /** Family CMR finding classification audit trail (#449). */
  readonly cmrFindingClassification?: FamilyCmrClassification;
  /** Unified stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
}

/**
 * The fields a PHASE-LEVEL `shipped` event (terminal 止于-PR success) carries
 * (online review r2, codex P1). Like {@link AbortedRecord} it is a phase-level
 * event (NOT a child), so it carries NO `childIssue`. It records the family `pr`
 * URL and the exact family HEAD covered by that PR. The spine may skip a later
 * final barrier only when the current family HEAD still equals this head.
 */
export interface ShippedRecord {
  /** The family PR URL the terminal ship opened. */
  readonly pr: string;
  /** The family base HEAD covered by the terminal ship / PR. */
  readonly familyHeadAfter: string;
  /** Unified stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
}

/** The fields for a green integrated CMR pass audit event (#419). */
export interface CmrPassedRecord {
  readonly cmrPass: IntegratedCmrPass;
  /** The family base HEAD that this pass reviewed and passed. */
  readonly familyHeadAfter?: string;
  /** Resolved route fingerprint for the CMR worker and declared review legs. */
  readonly routeFingerprint?: string;
  /** Family CMR finding classification audit trail (#449). */
  readonly cmrFindingClassification?: FamilyCmrClassification;
  /** Unified stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
}

/** A PHASE-LEVEL family escalation marker (#439). */
export interface FamilyEscalatedRecord {
  readonly escalationKind: EscalationKind;
  readonly phase?: "wave" | "final";
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
      ...(r.event !== undefined ? { event: r.event } : {}),
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
      cmrFindingClassification: record.cmrFindingClassification,
      stopSummary:
        record.stopSummary ??
        infraFailureStopSummary({
          summary: record.reason ?? "family barrier aborted",
          repairHint: "inspect this aborted ledger row, repair the barrier, and rerun",
          ...(record.familyHeadAfter !== undefined
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
      phase: "final",
      cmrPass: record.cmrPass,
      familyHeadAfter: record.familyHeadAfter,
      routeFingerprint: record.routeFingerprint,
      cmrFindingClassification: record.cmrFindingClassification,
      stopSummary:
        record.stopSummary ??
        successStopSummary(
          record.familyHeadAfter !== undefined
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
          ...(record.familyHeadAfter !== undefined
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

/** Append a PHASE-LEVEL human answer to a family decision escalation (#439). */
export async function recordFamilyEscalationAnswered(
  backend: FamilyBackend,
  record: FamilyEscalationAnswerRecord,
): Promise<void> {
  const answer = record.answer.trim();
  if (answer.length === 0) {
    throw new Error("family escalation answer must be a non-empty string");
  }
  await backend.appendFamilyLedger(
    compact({
      status: "escalation_answered",
      event: "escalation_answered",
      phase: "final",
      answer,
      source: record.source,
      note: record.note,
    }) as FamilyLedgerEntry,
  );
}

function isValidFamilyAnswer(entry: FamilyLedgerEntry): boolean {
  return (
    entry.status === "escalation_answered" &&
    entry.event === "escalation_answered" &&
    entry.phase === "final" &&
    typeof entry.answer === "string" &&
    entry.answer.trim().length > 0 &&
    (entry.source === "human" || entry.source === "resume_input") &&
    (entry.note === undefined || typeof entry.note === "string")
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
    typeof entry.familyHeadAfter === "string" &&
    entry.familyHeadAfter.trim().length > 0
  );
}

function familyAnswerPayload(entry: FamilyLedgerEntry): EscalationAnswerPayload {
  return {
    event: "escalation_answered",
    answer: entry.answer!,
    source: entry.source as "human" | "resume_input",
    ...(entry.note !== undefined ? { note: entry.note } : {}),
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
    if (entry.status !== "escalated") continue;
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
 * Did a specific integrated CMR pass already pass for the CURRENT family base
 * HEAD? This is a resume guard, so it fails closed when the current head is
 * missing or the ledger row lacks the complete cmr_passed shape.
 */
export function cmrPassAlreadyPassed(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  input: {
    readonly cmrPass: IntegratedCmrPass;
    readonly familyHeadAfter?: string;
    readonly routeFingerprint?: string;
  },
): boolean {
  if (input.familyHeadAfter === undefined || input.familyHeadAfter.trim().length === 0) {
    return false;
  }
  if (
    input.routeFingerprint === undefined ||
    input.routeFingerprint.trim().length === 0
  ) {
    return false;
  }
  return entries.some(
    (e) =>
      e.status === "cmr_passed" &&
      e.event === "cmr_passed" &&
      e.phase === "final" &&
      e.cmrPass === input.cmrPass &&
      e.familyHeadAfter !== undefined &&
      e.familyHeadAfter === input.familyHeadAfter &&
      e.routeFingerprint !== undefined &&
      e.routeFingerprint === input.routeFingerprint,
  );
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
  await backend.appendFamilyLedger(
    compact({
      status: "shipped",
      event: "shipped",
      phase: "final",
      pr,
      familyHeadAfter,
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

export function familyShippedRecordForHead(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  familyHeadAfter: string | undefined,
): ShippedRecord | undefined {
  // Fail-CLOSED on a malformed row (online review r3, coderabbit): the spine skips
  // the final barrier on this, so a corrupt/hand-edited `status:"shipped"` row with
  // no real delivery must NOT bypass verify/cmr/ship. Require the COMPLETE shape
  // `recordShipped` writes — status + event + final phase + a non-blank `pr` URL
  // + a non-blank `familyHeadAfter` — so only a genuine terminal ship for the
  // current HEAD counts as delivered.
  if (familyHeadAfter === undefined || familyHeadAfter.trim().length === 0) return undefined;
  const shipped = entries.find(
    (e): e is FamilyLedgerEntry & { readonly pr: string; readonly familyHeadAfter: string } =>
      isValidFamilyShipped(e) && e.familyHeadAfter === familyHeadAfter,
  );
  if (shipped === undefined) return undefined;
  return { pr: shipped.pr, familyHeadAfter: shipped.familyHeadAfter };
}

/**
 * Does the ledger contain a legacy terminal shipped marker that predates
 * `familyHeadAfter` binding? It proves a ship/PR already happened, but it cannot
 * prove which HEAD that PR covers, so resume must fail closed instead of either
 * silently skipping a newer head or re-running ship and duplicating the PR attempt.
 */
export function hasUnboundLegacyShippedMarker(
  entries: ReadonlyArray<FamilyLedgerEntry>,
): boolean {
  return entries.some(
    (e) =>
      e.status === "shipped" &&
      e.event === "shipped" &&
      e.phase === "final" &&
      typeof e.pr === "string" &&
      e.pr.trim().length > 0 &&
      (typeof e.familyHeadAfter !== "string" || e.familyHeadAfter.trim().length === 0),
  );
}

export function hasBoundShippedMarker(
  entries: ReadonlyArray<FamilyLedgerEntry>,
): boolean {
  return entries.some((e) => isValidFamilyShipped(e));
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
