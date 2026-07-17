/**
 * #683 park / #686 relay at the quota-wall disposition point.
 *
 * Shared by single-slice {@link runOrchestrator} and family {@link runFamily}
 * so 429/quota wait is one decision machine (ADR 0125), not two courts (#909).
 */

import type { CoderRosterEntry } from "./coderRoster.js";
import {
  DEFAULT_PARK_THRESHOLD_MS,
  type BillingPoolEntry,
  type BillingPoolId,
  type NextRelayBaton,
} from "./quotaPoolTable.js";
import {
  QuotaWaitForResetError,
  type QuotaWaitForResetLedgerEvent,
} from "./quotaProbe.js";
import {
  forkQuotaWallAt683Point,
  renderEphemeralRelayBrief,
  type RelayHandoffLedgerEvent,
} from "./relayDispatch.js";
import type {
  Backend,
  LedgerEntry,
  RunResult,
  SliceStepId,
} from "./types.js";
import { isStepId } from "./types.js";

function isValidStepId(value: unknown): value is SliceStepId {
  return isStepId(value);
}

/**
 * #934 R7 N2 — single try/catch vocabulary for required durable ledger writes.
 * `stateDir` undefined = no-op (in-memory-only callers). Write failure always
 * surfaces as `record_persist_failed: <classLabel>: …`.
 */
async function writeLedgerFailClosed(
  stateDir: string | undefined,
  classLabel: string,
  write: (dir: string) => Promise<void>,
): Promise<void> {
  if (stateDir === undefined) return;
  try {
    await write(stateDir);
  } catch (writeErr) {
    throw new Error(
      `record_persist_failed: ${classLabel}: ${
        writeErr instanceof Error ? writeErr.message : String(writeErr)
      }`,
    );
  }
}

/**
 * #934 ID-005 / #937 S2 — single durable court for `relay_baton_handoff` rows.
 *
 * Builds the in-memory marker, writeLedger (fail-closed with unified
 * `record_persist_failed` vocabulary), then ledger.push. Shared by quota-wall
 * relay and capacity relay so the two paths cannot drift on cargo or failure class.
 *
 * @param persistClass optional prefix fragment (e.g. `"capacity"`) →
 *   `record_persist_failed: capacity relay_baton_handoff: …`
 */
export async function persistRelayBatonHandoff(opts: {
  readonly entry: RelayHandoffLedgerEvent;
  readonly step: SliceStepId;
  readonly ledger: LedgerEntry[];
  readonly stateDir: string | undefined;
  readonly sessionId: string;
  readonly backend: Backend;
  readonly resolveBranchHEAD: () => Promise<string | undefined>;
  readonly hashPrompt: (
    promptFile: string | undefined,
    step: SliceStepId,
  ) => Promise<string>;
  readonly persistClass?: string;
}): Promise<LedgerEntry> {
  const { entry, step, ledger, stateDir, sessionId, backend } = opts;
  const marker: LedgerEntry = {
    step: isValidStepId(entry.step) ? entry.step : step,
    event: "relay_baton_handoff",
    trigger: entry.trigger,
    state_summary: entry.state_summary,
    ...(entry.remaining !== undefined ? { remaining: entry.remaining } : {}),
    ...(entry.reason !== undefined ? { reason: entry.reason } : {}),
    fromModelId: entry.fromModelId,
    fromPool: entry.fromPool,
    toModelId: entry.toModelId,
    toPool: entry.toPool,
    ts: entry.ts,
  };
  // Durable baton first; write failure fails closed (no best-effort in-memory-only).
  const classLabel =
    opts.persistClass !== undefined && opts.persistClass.length > 0
      ? `${opts.persistClass} relay_baton_handoff`
      : "relay_baton_handoff";
  await writeLedgerFailClosed(stateDir, classLabel, async (dir) => {
    await backend.writeLedger(
      {
        ...marker,
        sessionId,
        prompt_hash: await opts.hashPrompt(undefined, step),
        branchHEAD: await opts.resolveBranchHEAD(),
        ts: entry.ts,
      },
      dir,
    );
  });
  ledger.push(marker);
  return marker;
}

/**
 * #683 park: 429/quota wall → status escalate (resumable), not S8(error).
 * Mirror CI-pending park: ledger marker + stopSummary, no sticky failure.
 */
export async function parkQuotaWaitForReset(opts: {
  readonly step: SliceStepId;
  readonly err: QuotaWaitForResetError;
  readonly ledger: LedgerEntry[];
  readonly stateDir: string | undefined;
  readonly sessionId: string;
  readonly backend: Backend;
  readonly resolveBranchHEAD: () => Promise<string | undefined>;
  readonly hashPrompt: (
    promptFile: string | undefined,
    step: SliceStepId,
  ) => Promise<string>;
}): Promise<RunResult> {
  const { err, step, ledger, stateDir, sessionId, backend } = opts;
  const ledgerEntry: QuotaWaitForResetLedgerEvent =
    err.applied.ledgerEntry ?? {
      event: "quota_wait_for_reset",
      pool: err.pool,
      reason: err.disposition.reason,
      step,
      ts: new Date().toISOString(),
      ...(err.disposition.resetAt !== undefined
        ? { resetAt: err.disposition.resetAt.toISOString() }
        : {}),
    };
  const marker: LedgerEntry = {
    step: isValidStepId(ledgerEntry.step) ? ledgerEntry.step : step,
    event: "quota_wait_for_reset",
    pool: ledgerEntry.pool,
    reason: ledgerEntry.reason,
    ts: ledgerEntry.ts,
    ...(ledgerEntry.resetAt !== undefined ? { resetAt: ledgerEntry.resetAt } : {}),
    ...(ledgerEntry.workerPid !== undefined
      ? { workerPid: ledgerEntry.workerPid }
      : {}),
  };
  // #934 ID-001 / ID-005: park is only legal when the durable re-entry boundary
  // is established. A writeLedger failure must fail closed — never return a
  // parked/resumable outcome from an in-memory-only marker.
  await writeLedgerFailClosed(stateDir, "quota_wait_for_reset", async (dir) => {
    await backend.writeLedger(
      {
        ...marker,
        sessionId,
        prompt_hash: await opts.hashPrompt(undefined, step),
        branchHEAD: await opts.resolveBranchHEAD(),
        ts: ledgerEntry.ts,
      },
      dir,
    );
  });
  ledger.push(marker);
  const resetHint =
    ledgerEntry.resetAt !== undefined
      ? ` (resetAt ${ledgerEntry.resetAt})`
      : "";
  return {
    status: "escalate",
    stepLedger: ledger,
    stopSummary: {
      reason: "provider_degraded",
      summary: `quota wait for reset on pool ${ledgerEntry.pool}${resetHint}`,
      repairHint:
        "wait for the provider quota to reset, then re-feed — resume re-enters the parked step (auto re-dispatch is #686)",
    },
  };
}

export type ParkOrRelayQuotaWallOutcome =
  | { readonly kind: "park"; readonly result: RunResult }
  | {
      readonly kind: "relay";
      readonly nextBaton: NextRelayBaton;
      readonly ledgerEntry: RelayHandoffLedgerEvent;
      /** Ephemeral brief from ledger memory (#937); not a worktree path. */
      readonly relayBrief: string;
    };

/**
 * #683 park / #686 relay fork at the quota-wall disposition point.
 * Within T or no live baton → existing park family (escalate + quota_wait marker).
 * Beyond T + live baton → durable relay_baton_handoff + ephemeral brief render
 * and return the next baton for the caller to apply + re-dispatch.
 */
export async function parkOrRelayQuotaWall(opts: {
  readonly step: SliceStepId;
  readonly err: QuotaWaitForResetError;
  readonly ledger: LedgerEntry[];
  readonly stateDir: string | undefined;
  readonly sessionId: string;
  readonly backend: Backend;
  readonly resolveBranchHEAD: () => Promise<string | undefined>;
  readonly hashPrompt: (
    promptFile: string | undefined,
    step: SliceStepId,
  ) => Promise<string>;
  readonly worktreePath: string | undefined;
  readonly currentModelId: string;
  readonly currentPool: BillingPoolId;
  readonly rosterOrder: ReadonlyArray<CoderRosterEntry>;
  readonly pools: ReadonlyArray<BillingPoolEntry>;
  readonly parkThresholdMs?: number;
  readonly now: Date;
  readonly state_summary?: string;
}): Promise<ParkOrRelayQuotaWallOutcome> {
  const {
    err,
    step,
    ledger,
    stateDir,
    sessionId,
    backend,
  } = opts;
  const disposition = err.disposition;
  if (disposition.kind !== "wait_for_reset") {
    // Defensive: QuotaWaitForResetError constructor already requires this.
    return {
      kind: "park",
      result: await parkQuotaWaitForReset({
        step,
        err,
        ledger,
        stateDir,
        sessionId,
        backend,
        resolveBranchHEAD: opts.resolveBranchHEAD,
        hashPrompt: opts.hashPrompt,
      }),
    };
  }

  const forked = forkQuotaWallAt683Point({
    disposition,
    now: opts.now,
    parkThresholdMs: opts.parkThresholdMs ?? DEFAULT_PARK_THRESHOLD_MS,
    currentModelId: opts.currentModelId,
    currentPool: opts.currentPool,
    rosterOrder: opts.rosterOrder,
    pools: opts.pools,
    state_summary:
      opts.state_summary ??
      `quota wall on ${opts.currentPool}; uncommitted drift preserved`,
    step,
  });

  if (forked.tier === "relay" && forked.nextBaton && forked.ledgerEntry) {
    const entry = forked.ledgerEntry;
    // #937 / #934 S2: durable ledger row via single court; ephemeral brief is
    // pure render from the in-memory entry (no worktree focus file).
    await persistRelayBatonHandoff({
      entry,
      step,
      ledger,
      stateDir,
      sessionId,
      backend,
      resolveBranchHEAD: opts.resolveBranchHEAD,
      hashPrompt: opts.hashPrompt,
    });
    return {
      kind: "relay",
      nextBaton: forked.nextBaton,
      ledgerEntry: entry,
      relayBrief: renderEphemeralRelayBrief(entry),
    };
  }

  // park / park_fallback — identical to #683 park family.
  return {
    kind: "park",
    result: await parkQuotaWaitForReset({
      step,
      err,
      ledger,
      stateDir,
      sessionId,
      backend,
      resolveBranchHEAD: opts.resolveBranchHEAD,
      hashPrompt: opts.hashPrompt,
    }),
  };
}
