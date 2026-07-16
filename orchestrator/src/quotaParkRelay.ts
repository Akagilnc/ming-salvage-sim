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
  if (stateDir !== undefined) {
    await backend.writeLedger(
      {
        ...marker,
        sessionId,
        prompt_hash: await opts.hashPrompt(undefined, step),
        branchHEAD: await opts.resolveBranchHEAD(),
        ts: ledgerEntry.ts,
      },
      stateDir,
    );
  }
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
    // #937: durable ledger row first; ephemeral brief is pure render from the
    // in-memory entry (no worktree focus file).
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
    // Durable baton first; write failure fails closed (no best-effort park).
    if (stateDir !== undefined) {
      await backend.writeLedger(
        {
          ...marker,
          sessionId,
          prompt_hash: await opts.hashPrompt(undefined, step),
          branchHEAD: await opts.resolveBranchHEAD(),
          ts: entry.ts,
        },
        stateDir,
      );
    }
    ledger.push(marker);
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
