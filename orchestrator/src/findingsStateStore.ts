/**
 * Findings state store statuses + write-point transition validation (ADR 0129).
 *
 * Single implementation source for store status tokens and legal flips.
 * Callers (judge kill/suppress mapping, tests) import from here — do not
 * re-declare status unions elsewhere.
 *
 * ## Vocabulary boundary (#952 4b — two seams, cross-commented)
 *
 * - **This module / judge suppress path**: store terminal `suppressed`, written
 *   from judge disposition `action: "suppress"` (schema in
 *   `stationReceiptContracts.ts`). Not a public result/cause; Runner never
 *   reads this store for routing (ADR 0131 / 0136).
 * - **CMR reviewer governance carrier**: `accepted_suppressed`
 *   (`FindingDispositionKind` + priorFindingDispositions prompts) — different
 *   seam for reviewer-side accepted suppression with source/scope/boundedReopen.
 *   Keep both vocabularies; do not alias or silently invent a third token.
 *
 * Ledger row shape is {@link FindingDisposition} in types.ts (status tokens
 * single-sourced here; severity from Finding — no parallel record type).
 */

import type { ContractResult } from "./stationReceiptContracts.js";
import type { Finding, FindingDisposition } from "./types.js";

/**
 * Canonical findings-store status tokens (ledger `FindingDisposition.status`).
 * Open row = `unrepaired`; all others are terminal for the fixer live-set.
 */
export const FINDING_STORE_STATUSES = [
  "unrepaired",
  "wont_fix",
  "rejected",
  /** CMR governance carrier status — not the judge suppress terminal. */
  "accepted_suppressed",
  /** Judge kill terminal (four-reason refute). */
  "refuted",
  /** Judge suppress terminal (#952). */
  "suppressed",
] as const;

export type FindingStoreStatus = (typeof FINDING_STORE_STATUSES)[number];

function ok<T>(value: T): ContractResult<T> {
  return { ok: true, value };
}

function fail(reason: string): ContractResult<never> {
  return { ok: false, reason };
}

/** Sole open status that may enter the fixer live-set. */
export const OPEN_FINDING_STORE_STATUS =
  "unrepaired" as const satisfies FindingStoreStatus;

const TERMINAL_FINDING_STORE_STATUSES = new Set<FindingStoreStatus>(
  FINDING_STORE_STATUSES.filter((s) => s !== OPEN_FINDING_STORE_STATUS),
);

/** True only for the open store status (`unrepaired`). */
export function isOpenForFixer(status: FindingStoreStatus): boolean {
  return status === OPEN_FINDING_STORE_STATUS;
}

export function isTerminalFindingStoreStatus(
  status: FindingStoreStatus,
): boolean {
  return TERMINAL_FINDING_STORE_STATUSES.has(status);
}

/**
 * Legal state transitions at the findings-store write point (ADR 0129).
 *
 * - Absent / open → any status (initial write or open flip)
 * - Terminal → anything (including same token) is illegal — terminals do not re-flip
 */
export function validateFindingStoreTransition(
  from: FindingStoreStatus | undefined,
  to: FindingStoreStatus,
): ContractResult<true> {
  if (!(FINDING_STORE_STATUSES as readonly string[]).includes(to)) {
    return fail(`unknown findings-store status: ${String(to)}`);
  }
  if (from === undefined || from === OPEN_FINDING_STORE_STATUS) {
    return ok(true);
  }
  if (isTerminalFindingStoreStatus(from)) {
    return fail(
      `illegal findings-store transition ${from} → ${to} (terminal status cannot re-flip)`,
    );
  }
  return fail(`illegal findings-store transition ${from} → ${to}`);
}

/**
 * Write-point flip: validates transition then returns a ledger disposition row.
 * Sole construction path for judge/store terminal flips that need transition
 * checks (refute / suppress). Row shape = {@link FindingDisposition} (types.ts).
 */
export function recordFindingStoreFlip(input: {
  readonly identityKey: string;
  readonly from: FindingStoreStatus | undefined;
  readonly to: FindingStoreStatus;
  readonly reason: string;
  readonly severity: Finding["severity"];
  readonly source?: string;
  readonly scope?: string;
  readonly boundedReopen?: string;
}): ContractResult<FindingDisposition> {
  const transition = validateFindingStoreTransition(input.from, input.to);
  if (!transition.ok) return transition;

  if (typeof input.identityKey !== "string" || input.identityKey.trim().length === 0) {
    return fail("finding store flip identityKey must be a non-empty string");
  }
  if (typeof input.reason !== "string" || input.reason.trim().length === 0) {
    return fail("finding store flip reason must be a non-empty string");
  }

  return ok({
    identityKey: input.identityKey.trim(),
    status: input.to,
    reason: input.reason.trim(),
    severity: input.severity,
    ...(input.source !== undefined ? { source: input.source } : {}),
    ...(input.scope !== undefined ? { scope: input.scope } : {}),
    ...(input.boundedReopen !== undefined
      ? { boundedReopen: input.boundedReopen }
      : {}),
  });
}
