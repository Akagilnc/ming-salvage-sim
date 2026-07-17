/**
 * Shared family process-root ownership court (ID-004 / ID-006 / #909).
 *
 * Monitored spawn + withMechanicalRetry + durable mechanical_redispatch budget.
 * Non-retryable quota (429 / wait-for-reset) is rethrown so upper family/runner
 * can park or relay — never collapsed into generic `{kind:"failed"}` leg-kill.
 *
 * Used by verifyCmr (cmr / ship / fixer) and landing (docs worker). One court —
 * no hand-synced forks (CLAUDE #19 / #941 CR R2 M1).
 */

import { withMechanicalRetry } from "../dispatchRetry.js";
import { isQuotaWaitForResetError } from "../quotaProbe.js";
import type {
  DispatchContext,
  WorkerLandingPayload,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../types.js";
import { dispatchFamilyWorkerWithMonitor } from "./dispatchFamilyWorker.js";
import { mechanicalRedispatchAttemptsFromFamilyLedger } from "./ledger.js";
import { OnlineReviewLoopTerminal } from "./onlineReviewLoop.js";
import type { FamilyBackend } from "./types.js";

/** Durable workerStep key for mechanical redispatch budget binding. */
export function familyWorkerStepKey(
  spec: WorkerSpec,
  ctx: DispatchContext,
): string {
  return `${spec.kind}${ctx.cmrPass !== undefined ? `:${ctx.cmrPass}` : ""}`;
}

/**
 * Dispatch a family worker through the process-root ownership court.
 *
 * @returns resolved {@link WorkerResult} (including startup-failed collapsed
 *   results for ordinary throws)
 * @throws {@link OnlineReviewLoopTerminal} — typed review-loop terminal
 * @throws {@link import("../quotaProbe.js").QuotaWaitForResetError} — 429/quota
 *   park signal for upper family/runner relay
 */
export async function dispatchFamilyWorkerOrAbort(
  familyBackend: FamilyBackend,
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
  opts?: {
    readonly onMonitorHandle?: (handle: WorkerMonitorHandle) => void;
  },
): Promise<WorkerResult> {
  try {
    // #598 / 2026-07-08: a family worker that CRASHES (throws) re-dispatches a fresh
    // session on the CURRENT worktree as-is, up to MAX_DISPATCH_ATTEMPTS — every role,
    // read-only and write-capable alike. Every RESOLVED result (failed / malformed /
    // completed / escalated) is DEFERRED to this gate's own rich terminal handling.
    // #934 ID-004: durable mechanical_redispatch markers bind the budget across
    // process re-entry (same contract as single-slice runner.ts).
    const workerStep = familyWorkerStepKey(spec, ctx);
    const ledger = await familyBackend.readFamilyLedger();
    const attemptsAlreadyUsed = mechanicalRedispatchAttemptsFromFamilyLedger(
      ledger,
      workerStep,
    );
    return await withMechanicalRetry(
      spec,
      ctx,
      async (s, c) => {
        let dispatchError: unknown | undefined;
        let workerResult: WorkerResult;
        try {
          const monitored = await dispatchFamilyWorkerWithMonitor(
            familyBackend,
            s,
            c,
            landing,
            {
              onMonitorHandleSpawned: async (handle: WorkerMonitorHandle) => {
                opts?.onMonitorHandle?.(handle);
                // #934 ID-006 / #937: adoption/persist failure terminates the
                // exact ChildProcess via dispatchFamilyWorkerWithMonitor —
                // rethrow so terminateSpawnedChild runs (no best-effort swallow).
                await familyBackend.appendFamilyLedger({
                  status: "worker_dispatched",
                  event: "worker_dispatched",
                  monitorHandle: handle,
                });
              },
            },
          );
          workerResult = monitored.result;
          await monitored.telemetryEnvironmentStamp;
        } catch (err) {
          dispatchError = err;
        }
        if (dispatchError !== undefined) throw dispatchError;
        return workerResult!;
      },
      {
        attemptsAlreadyUsed,
        onFailure: async (outcome, attempt) => {
          const reason =
            "result" in outcome
              ? outcome.result.kind === "failed"
                ? outcome.result.reason
                : `worker returned ${outcome.result.kind}`
              : outcome.error instanceof Error
                ? outcome.error.message
                : String(outcome.error);
          await familyBackend.appendFamilyLedger({
            status: "worker_dispatched",
            event: "worker_dispatched",
            workerStep,
            mechanicalRedispatchAttempt: attempt,
            reason,
          });
        },
        rethrowOnExhaustion: true,
      },
    );
  } catch (err) {
    if (err instanceof OnlineReviewLoopTerminal) throw err;
    // #909: 429/quota park signal must NOT collapse into generic startup
    // `{kind:"failed"}` (leg-kill). Rethrow so upper family/runner can park or
    // relay — same typed terminal as single-slice withMechanicalRetry.
    if (isQuotaWaitForResetError(err)) {
      // N2: stamp the hit CMR pass so wall relay rewrites only that slot.
      if (ctx.cmrPass === "completeness" || ctx.cmrPass === "correctness") {
        err.cmrPass = ctx.cmrPass;
      }
      throw err;
    }
    const reason = `family ${spec.kind} worker threw on startup: ${
      err instanceof Error ? err.message : String(err)
    }`;
    return { kind: "failed", reason };
  }
}
