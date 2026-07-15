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
  tryStageRelayFocusFile,
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
  readonly resolveBranchHEAD: () => Promise<string>;
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
  ledger.push(marker);
  if (stateDir !== undefined) {
    try {
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
    } catch {
      // Best-effort durable park marker — in-memory ledger still holds it.
    }
  }
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
      readonly focusPath: string | undefined;
    };

/**
 * #683 park / #686 relay fork at the quota-wall disposition point.
 * Within T or no live baton → existing park family (escalate + quota_wait marker).
 * Beyond T + live baton → write relay_baton_handoff + .relay-focus.md and return
 * the next baton for the caller to apply + re-dispatch.
 */
export async function parkOrRelayQuotaWall(opts: {
  readonly step: SliceStepId;
  readonly err: QuotaWaitForResetError;
  readonly ledger: LedgerEntry[];
  readonly stateDir: string | undefined;
  readonly sessionId: string;
  readonly backend: Backend;
  readonly resolveBranchHEAD: () => Promise<string>;
  readonly hashPrompt: (
    promptFile: string | undefined,
    step: SliceStepId,
  ) => Promise<string>;
  readonly worktreePath: string | undefined;
  readonly currentModelId: string;
  readonly currentPool: BillingPoolId;
  readonly rosterOrder: ReadonlyArray<CoderRosterEntry>;
  readonly pools: ReadonlyArray<BillingPoolEntry>;
  readonly reviewerSlugs?: ReadonlyArray<string>;
  readonly reviewerSlugsForCandidate?: (
    candidate: CoderRosterEntry,
  ) => ReadonlyArray<string>;
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
    reviewerSlugs: opts.reviewerSlugs,
    reviewerSlugsForCandidate: opts.reviewerSlugsForCandidate,
    state_summary:
      opts.state_summary ??
      `quota wall on ${opts.currentPool}; uncommitted drift preserved`,
    step,
  });

  if (forked.tier === "relay" && forked.nextBaton && forked.ledgerEntry) {
    const entry = forked.ledgerEntry;
    // Stage the new brief while the previous durable baton remains consumable.
    // Promote only after the matching ledger row commits.
    const staged = tryStageRelayFocusFile(opts.worktreePath, entry);
    if (!staged.ok) {
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
    if (stateDir !== undefined) {
      try {
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
      } catch {
        staged.focus.discard();
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
    }
    try {
      staged.focus.commit();
    } catch {
      // C9: promote/commit failed after durable handoff write — discard staged
      // focus and do not leave an uncancelled half-applied baton as progress.
      try {
        staged.focus.discard();
      } catch {
        // best-effort cleanup
      }
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
    ledger.push(marker);
    return {
      kind: "relay",
      nextBaton: forked.nextBaton,
      ledgerEntry: entry,
      focusPath: staged.focus.path,
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
