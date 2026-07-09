/**
 * #603 — host-side worktree/clone reclamation gated on ledger terminal state.
 *
 * Reclamation precondition is read from the host ledger only — never a worker
 * self-report (ADR 0024 terminal-success GC).
 */

import { isValidCleanupResult } from "./reviewLoopOutcome.js";
import type { CleanupResult, HandoffStatus, LedgerEntry } from "./types.js";
import type { WorktreeHandle } from "./types.js";
import type { FamilyLedgerEntry } from "./family/types.js";

/** Whether a cleanup outcome qualifies for host reclaim (terminal success, no residue). */
export function cleanupResultReclaimEligible(
  output: CleanupResult,
): boolean {
  if (!isValidCleanupResult(output)) return false;
  return output.terminal === true && output.ok === true;
}

/** Last S11 cleanup row that is terminal+ok — the reclaim precondition. */
export function sliceCleanupTerminalForReclaim(
  ledger: ReadonlyArray<LedgerEntry>,
): boolean {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step !== "S11") continue;
    if (!isValidCleanupResult(entry.output)) return false;
    return cleanupResultReclaimEligible(entry.output);
  }
  return false;
}

/**
 * Whether host paths may be reclaimed after a genuine terminal success.
 * Does not fire on park, in-flight retry, failed, or malformed cleanup.
 */
export function shouldReclaimSliceHost(
  ledger: ReadonlyArray<LedgerEntry>,
  handoffStatus: HandoffStatus | undefined,
): boolean {
  if (handoffStatus !== "success") return false;
  return sliceCleanupTerminalForReclaim(ledger);
}

export interface HostReclaimBackend {
  reapResidentWorktree(worktree: WorktreeHandle): Promise<void>;
}

/**
 * Best-effort reclaim of the resident slice worktree at terminal success.
 * Caller must have already verified {@link shouldReclaimSliceHost}.
 */
export async function reclaimSliceHostPaths(
  backend: HostReclaimBackend,
  worktree: WorktreeHandle,
): Promise<void> {
  await backend.reapResidentWorktree(worktree);
}

/** Last post_merge_cleanup ledger row that is terminal+ok — family reclaim gate. */
export function familyCleanupTerminalForReclaim(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
): boolean {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.status !== "post_merge_cleanup") continue;
    const output = entry.cleanupOutput;
    if (output === undefined || !isValidCleanupResult(output)) return false;
    return cleanupResultReclaimEligible(output);
  }
  return false;
}

/** Whether the family clone/worktree may be reclaimed after genuine terminal cleanup. */
export function shouldReclaimFamilyHost(
  ledger: ReadonlyArray<FamilyLedgerEntry>,
): boolean {
  return familyCleanupTerminalForReclaim(ledger);
}

export interface FamilyReclaimBackend {
  reapFamilyHost(familyBase: string): Promise<void>;
}

/** Best-effort reclaim of the family host clone at terminal success. */
export async function reclaimFamilyHostPaths(
  backend: FamilyReclaimBackend,
  familyBase: string,
): Promise<void> {
  await backend.reapFamilyHost(familyBase);
}
