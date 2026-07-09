/**
 * #603 — host-side worktree/clone reclamation gated on ledger terminal state.
 *
 * Reclamation precondition is read from the host ledger only — never a worker
 * self-report (ADR 0024 terminal-success GC).
 */

import { isValidCleanupResult } from "./reviewLoopOutcome.js";
import type { HandoffStatus, LedgerEntry } from "./types.js";
import type { WorktreeHandle } from "./types.js";

/** Last S11 cleanup row that is terminal+ok — the reclaim precondition. */
export function sliceCleanupTerminalForReclaim(
  ledger: ReadonlyArray<LedgerEntry>,
): boolean {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step !== "S11") continue;
    if (!isValidCleanupResult(entry.output)) return false;
    return entry.output.terminal === true && entry.output.ok === true;
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
