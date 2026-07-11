/**
 * The unified worker-dispatch seam at the FAMILY layer (ADR 0026 / PRD #330,
 * #331) — parallel to the single-slice `dispatchWorker` (../dispatchWorker.ts).
 *
 * The family-LEVEL worker steps — integrated cross-model cmr over the merged
 * family base, runner-visible coder-fix for blocking CMR findings, and the
 * family-base ship/PR — are dispatched through ONE seam instead of hiding work
 * inside the per-method `runIntegratedCmr` / `openFamilyPr`.
 *
 *   - {@link cmrWorkerSpec} / {@link familyCoderFixWorkerSpec} /
 *     {@link familyShipWorkerSpec} — the declarative {@link WorkerSpec}s for the
 *     family workers.
 *   - {@link dispatchFamilyWorker} — the free function the verify-cmr hook calls.
 *     It uses `familyBackend.dispatchWorker` when implemented, else forwards to the
 *     legacy `runIntegratedCmr` / `openFamilyPr` (#331 prefactor — behaviour
 *     unchanged for legacy cmr/ship). The real container cmr worker lands in #335;
 *     the runner-visible CMR coder-fix worker lands in #550.
 *
 * NOTE the DispatchContext for a family worker carries `familyBase` (the caller
 * has only the base string, no single-slice worktree path — PRD #330 R2);
 * `worktree` is optional / backend-inferred. The WorkerResult is the same
 * discriminated union: a cmr `red` verdict is `completed` (with a CmrResult
 * payload), NOT `failed`.
 */

import type { ChildProcess } from "node:child_process";

import { workerHostForModel } from "../dispatchWorker.js";
import {
  createTelemetryLegStamper,
  scheduleTelemetryEnvironmentStamp,
} from "../telemetry.js";
import {
  dispatchMonitoredCliWorker,
  killWorkerTree,
  readLogActivity,
  type MonitoredCliDispatchInput,
} from "../workerMonitor.js";
import type {
  DispatchContext,
  WorkerLandingPayload,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSessionMode,
  WorkerSpec,
} from "../types.js";
import {
  cmrReviewLegs as activeCmrReviewLegs,
  modelForSlot,
  routeSmokeFailure,
  type ResolvedModelRoute,
} from "../modelRoutes.js";
import { offlineReviewLoopDispatchAdmissible } from "../evidenceAdmissibility.js";
import { skeletonReviewLoopWorkerResult } from "../reviewLoopOutcome.js";
import type {
  FamilyBackend,
  IntegratedCmrPass,
  IntegratedCmrResult,
  OpenFamilyPrResult,
} from "./types.js";

const IMAGE_TOOLCHAIN: ReadonlyArray<string> = [
  "python",
  "node",
  "npm",
  "typescript",
] as const;

/**
 * The integrated-cmr family reviewer spec (#335 invoke `ak-cross-m-review`).
 *
 * ADR 0030 splits integrated cmr into ordered runner-dispatched pass workers:
 * completeness first, correctness second. This spec describes ONE such pass
 * worker, not the whole integrated gate:
 *   - `session: "fresh"` = start a NEW pass session (not a crash/escalate
 *     `resume`, which skips git-truthing). `verifyCmr` dispatches one fresh worker
 *     per pass and gates correctness on completeness.
 *   - `role: "reviewer"` and `contextRetention: "clean"` = this worker reports
 *     review artifacts/outcome only. Blocking findings return to the runner; a
 *     separate coder-fix worker commits repairs.
 *   - `maxIter: 1` = one reviewer pass. Fresh re-review is a new runner dispatch,
 *     not an in-worker fix loop.
 */
export function cmrWorkerSpec(
  session: WorkerSessionMode = "fresh",
  pass: IntegratedCmrPass = "correctness",
  route?: ResolvedModelRoute,
): WorkerSpec {
  const model =
    route?.slots[pass === "completeness" ? "cmrCompleteness" : "cmrCorrectness"] ??
    modelForSlot(pass === "completeness" ? "cmrCompleteness" : "cmrCorrectness");
  return {
    id: "S3",
    kind: "cmr",
    role: "reviewer",
    host: workerHostForModel(model),
    session,
    contextRetention: "clean",
    skill: "ak-cross-m-review",
    promptFile:
      pass === "completeness"
        ? "integrated_cmr_completeness.md"
        : "integrated_cmr_correctness.md",
    completionSignal: "CMR_STEP_COMPLETE",
    maxIter: 1,
    model,
    cmrReviewLegs: route?.legCollections.cmrReview ?? activeCmrReviewLegs(),
    soul: "cmr",
    toolchain: [],
  };
}

/** Family-level coder-fix worker for blocking CMR findings (#550). */
export function familyCoderFixWorkerSpec(route?: ResolvedModelRoute): WorkerSpec {
  const model = route?.slots.coderFix ?? modelForSlot("coderFix");
  return {
    id: "S5",
    kind: "coder",
    role: "coder",
    host: workerHostForModel(model),
    session: "fresh",
    contextRetention: "retain",
    skill: "/tdd",
    promptFile: "coder_fix.md",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    model,
    soul: "coder",
    toolchain: IMAGE_TOOLCHAIN,
  };
}

/** The family-base ship/PR worker spec (止于 PR; invoke `gstack-ship`). */
export function familyShipWorkerSpec(route?: ResolvedModelRoute): WorkerSpec {
  const model = route?.slots.ship ?? modelForSlot("ship");
  return {
    id: "S7",
    kind: "ship",
    role: "coder",
    host: workerHostForModel(model),
    session: "fresh",
    contextRetention: "clean",
    skill: "gstack-ship",
    promptFile: "family_ship.md",
    completionSignal: "SHIP_STEP_COMPLETE",
    // A WRITE/coder ship worker must self-rerun gstack-ship's rerun-able failures
    // (family_ship.md: "rerun it yourself") → an iterative budget like coder/fix
    // (runner worker specs use 5), NOT the cmr reviewer's single-pass 1 (#336 cmr r6).
    maxIter: 5,
    model,
    // The family ship worker runs under the dedicated "ship" soul (delivery
    // discipline: gstack-ship, stop-at-PR, defer→tracker not PR body), matching
    // the runtime SHIP_SOUL injected by realFamilyBackend.shipSandboxConfig — the
    // spec must not still declare the coder soul (CodeRabbit #384: unify the
    // ship-worker soul contract).
    soul: "ship",
    toolchain: [],
  };
}

/**
 * THE family seam entry point: dispatch a family worker, preferring the backend's
 * unified `dispatchWorker` when implemented, else the legacy forwarding wrapper
 * (#331 prefactor). The verify-cmr hook calls ONLY this for the cmr / family-ship
 * worker steps.
 *
 * Returns the discriminated {@link WorkerResult}. For #331 the legacy wrapper
 * always yields `completed` (forwarding `runIntegratedCmr` / `openFamilyPr`):
 *   - cmr → `completed` with a {@link CmrResult} payload (`red` IS `completed`).
 *   - coder-fix → requires a backend implementing the unified seam (no legacy
 *     family method can safely make persistent fix commits).
 *   - family ship → `completed` with a {@link ShipResult} payload.
 */
export async function dispatchFamilyWorker(
  familyBackend: FamilyBackend,
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
): Promise<WorkerResult> {
  if (ctx.modelRoute === undefined) {
    throw new Error("family worker dispatch refused (fail-closed): model route smoke state is missing");
  }
  const smokeFailure = routeSmokeFailure(ctx.modelRoute);
  if (smokeFailure !== undefined) {
    throw new Error(`family worker dispatch refused (fail-closed): ${smokeFailure}`);
  }
  if (familyBackend.dispatchWorker !== undefined) {
    return familyBackend.dispatchWorker(spec, ctx, landing);
  }
  return legacyDispatchFamilyWorker(familyBackend, spec, ctx);
}

export interface DispatchFamilyWorkerWithMonitorOutcome {
  readonly result: WorkerResult;
  readonly monitorHandle?: WorkerMonitorHandle;
  /** Completion handle for this run's fail-open environment telemetry stamp. */
  readonly telemetryEnvironmentStamp: Promise<void>;
}

export interface DispatchFamilyWorkerWithMonitorOptions {
  readonly onMonitorHandleSpawned?: (
    handle: WorkerMonitorHandle,
  ) => void | Promise<void>;
}

function waitForChildExit(child: ChildProcess): Promise<number | null> {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve(child.exitCode);
  }
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve(code));
  });
}

/**
 * #684 production family dispatch path — parallel to single-slice
 * `dispatchWorkerWithMonitor`. When the family backend supplies a CLI spawn via
 * {@link FamilyBackend.resolveCliMonitorDispatch}, the monitor handle is
 * generated atomically at spawn (and optionally persisted via
 * `onMonitorHandleSpawned` before wait).
 */
export async function dispatchFamilyWorkerWithMonitor(
  familyBackend: FamilyBackend,
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
  opts?: DispatchFamilyWorkerWithMonitorOptions,
): Promise<DispatchFamilyWorkerWithMonitorOutcome> {
  // Best-effort only: never changes worker semantics. Optional chaining only
  // guards missing methods; a throwing resolveTelemetryDir must not abort
  // dispatch (same fail-open as single-slice; CodeRabbit #815).
  let telemetryDir = ctx.telemetryDir;
  if (telemetryDir === undefined) {
    try {
      telemetryDir = familyBackend.resolveTelemetryDir?.(ctx);
    } catch (err) {
      console.warn(
        `[orchestrator] family resolveTelemetryDir failed (fail-open): ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
    telemetryDir = telemetryDir ?? ctx.stateDir;
  }
  const telemetryCtx =
    telemetryDir === undefined ? ctx : { ...ctx, telemetryDir };
  const telemetry = createTelemetryLegStamper({
    ledgerDir: telemetryDir,
    spec,
    ctx: telemetryCtx,
  });
  let firstOutputAt: string | null = null;
  let logPath: string | null = null;
  let logStartOffset: number | undefined;
  let monitorHandle: WorkerMonitorHandle | undefined;
  let firstOutputBaseline: number | undefined;
  let telemetryEnvironmentStamp = Promise.resolve();

  const reconcileFirstOutputAt = (): void => {
    if (firstOutputAt !== null || monitorHandle === undefined || firstOutputBaseline === undefined) {
      return;
    }
    const activity = readLogActivity(monitorHandle);
    if (activity !== undefined && activity.sizeBytes > firstOutputBaseline) {
      firstOutputAt = new Date().toISOString();
    }
  };

  try {
    const cliSpec = familyBackend.resolveCliMonitorDispatch?.(spec, telemetryCtx, landing);
    if (cliSpec !== undefined) {
      const input: MonitoredCliDispatchInput = {
        command: cliSpec.command,
        args: cliSpec.args,
        logDir: cliSpec.logDir,
        poolId: cliSpec.poolId,
        completionSignal: cliSpec.completionSignal,
        stepId: cliSpec.stepId,
        ...(cliSpec.cwd !== undefined ? { cwd: cliSpec.cwd } : {}),
        ...(cliSpec.env !== undefined ? { env: cliSpec.env } : {}),
        ...(cliSpec.logBasename !== undefined
          ? { logBasename: cliSpec.logBasename }
          : {}),
        ...(cliSpec.readInstanceId !== undefined
          ? { readInstanceId: cliSpec.readInstanceId }
          : {}),
        ...(cliSpec.resultPath !== undefined
          ? { resultPath: cliSpec.resultPath }
          : {}),
      };
      const { handle, child } = await dispatchMonitoredCliWorker(input);
      monitorHandle = handle;
      logPath = handle.logPath;
      logStartOffset = handle.logStartOffset;
      firstOutputBaseline = firstOutputBaselineBytes(handle);
      reconcileFirstOutputAt();
      telemetry.stampDispatch(handle.dispatchedAt, cliSpec.poolId);
      const exitPromise = waitForChildExit(child);
      // Environment collection is intentionally lazy and non-blocking. It must
      // start before the persistence callback so a callback throw cannot erase
      // this run's environment row.
      telemetryEnvironmentStamp = scheduleTelemetryEnvironmentStamp(
        telemetryDir,
        telemetryCtx,
        familyBackend,
      );
      if (opts?.onMonitorHandleSpawned !== undefined) {
        try {
          await opts.onMonitorHandleSpawned(handle);
        } catch (error) {
          // Cleanup remains scoped to the verified monitor handle; never signal
          // an unverified PID or process group on callback failure.
          await killWorkerTree(handle);
          try {
            await exitPromise;
          } catch {
            // Preserve the original spawn-persist error if child cleanup fails.
          }
          throw error;
        }
      }
      const exitCode = await exitPromise;
      reconcileFirstOutputAt();
      if (familyBackend.awaitMonitoredCliWorker === undefined) {
        const result: WorkerResult = {
          kind: "failed",
          reason:
            `family CLI worker ${spec.id} finished (exit ${exitCode}) but backend ` +
            `has no awaitMonitoredCliWorker to map the process into a WorkerResult`,
        };
        telemetry.stampCollect(
          { kind: "result", result },
          { logPath, logStartOffset, firstOutputAt },
        );
        return { result, monitorHandle: handle, telemetryEnvironmentStamp };
      }
      const result = await familyBackend.awaitMonitoredCliWorker(
        handle,
        exitCode,
        spec,
        ctx,
        landing,
      );
      reconcileFirstOutputAt();
      telemetry.stampCollect(
        { kind: "result", result },
        { logPath, logStartOffset, firstOutputAt },
      );
      return { result, monitorHandle: handle, telemetryEnvironmentStamp };
    }
    telemetry.stampDispatch(
      new Date().toISOString(),
      ctx.billingPool !== undefined ? ctx.billingPool : undefined,
    );
    telemetryEnvironmentStamp = scheduleTelemetryEnvironmentStamp(
      telemetryDir,
      telemetryCtx,
      familyBackend,
    );
    const result = await dispatchFamilyWorker(familyBackend, spec, ctx, landing);
    telemetry.stampCollect({ kind: "result", result });
    return { result, telemetryEnvironmentStamp };
  } catch (error) {
    reconcileFirstOutputAt();
    telemetry.stampCollect(
      { kind: "thrown", error },
      { logPath, logStartOffset, firstOutputAt },
    );
    await telemetryEnvironmentStamp;
    throw error;
  }
}

/**
 * Byte offset after the pre-dispatch log prefix plus the orchestrator's spawn
 * marker. This mirrors the single-slice baseline: only later growth is worker
 * output, not the marker written by `dispatchMonitoredCliWorker` itself.
 */
function firstOutputBaselineBytes(handle: WorkerMonitorHandle): number {
  const offset =
    typeof handle.logStartOffset === "number" &&
    Number.isFinite(handle.logStartOffset) &&
    handle.logStartOffset >= 0
      ? handle.logStartOffset
      : 0;
  const marker =
    `[orchestrator] dispatched ${handle.stepId} pid=${handle.pid} ` +
    `pool=${handle.poolId} instance=${handle.instanceId} at ${handle.dispatchedAt}\n`;
  return offset + Buffer.byteLength(marker, "utf8");
}

/**
 * The #331 PREFACTOR thin wrapper: forward a family worker to the EXISTING
 * `FamilyBackend` methods and wrap into a {@link WorkerResult}.
 *
 * The two optional legacy methods (`runIntegratedCmr` / `openFamilyPr`) gate the
 * dispatch: when absent the verify-cmr hook already degrades to its
 * INCOMPLETE_GATE path, so this wrapper is only reached when the capability
 * exists. A missing capability throws (the hook never calls dispatch without
 * first checking the legacy method exists — see verifyCmr.ts).
 */
export async function legacyDispatchFamilyWorker(
  familyBackend: FamilyBackend,
  spec: WorkerSpec,
  ctx: DispatchContext,
): Promise<WorkerResult> {
  const familyBase = ctx.familyBase;
  if (familyBase === undefined) {
    throw new Error(
      "legacyDispatchFamilyWorker: a family worker requires ctx.familyBase",
    );
  }

  if (spec.kind === "cmr") {
    if (familyBackend.runIntegratedCmr === undefined) {
      throw new Error(
        "legacyDispatchFamilyWorker: backend has no runIntegratedCmr capability",
      );
    }
    const cmr: IntegratedCmrResult = await familyBackend.runIntegratedCmr({
      familyBase,
      ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
      ...(ctx.llmResolvedChildren !== undefined &&
      ctx.llmResolvedChildren.length > 0
        ? { llmResolvedChildren: ctx.llmResolvedChildren }
        : {}),
      ...(ctx.escalationAnswer !== undefined
        ? { escalationAnswer: ctx.escalationAnswer }
        : {}),
      ...(ctx.moduleContext !== undefined ? { moduleContext: ctx.moduleContext } : {}),
      ...(ctx.priorCmrFindingIdentityKeys !== undefined
        ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
        : {}),
    });
    // A `red` (non-converged) verdict is `completed` with payload — NOT `failed`
    // (PRD #330 R2). The verify-cmr hook reads `converged` off the payload.
    return {
      kind: "completed",
      output: {
        kind: "cmr",
        ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
        converged: cmr.converged,
        ...(cmr.reason !== undefined ? { reason: cmr.reason } : {}),
        ...(cmr.successfulLegs !== undefined ? { successfulLegs: cmr.successfulLegs } : {}),
        ...(cmr.skippedLegs !== undefined ? { skippedLegs: cmr.skippedLegs } : {}),
        ...(cmr.claimedFixedFindingIdentityKeys !== undefined
          ? {
              claimedFixedFindingIdentityKeys:
                cmr.claimedFixedFindingIdentityKeys,
            }
          : {}),
        ...(cmr.priorFindingDispositions !== undefined
          ? { priorFindingDispositions: cmr.priorFindingDispositions }
          : {}),
        ...(cmr.findings !== undefined ? { findings: cmr.findings } : {}),
        ...(cmr.evidencePaths !== undefined ? { evidencePaths: cmr.evidencePaths } : {}),
      },
    };
  }

  if (spec.kind === "ship") {
    if (familyBackend.openFamilyPr === undefined) {
      throw new Error(
        "legacyDispatchFamilyWorker: backend has no openFamilyPr capability",
      );
    }
    const pr: OpenFamilyPrResult = await familyBackend.openFamilyPr({
      familyBase,
    });
    const prHead =
      typeof pr.prHead === "string" && pr.prHead.trim().length > 0
        ? pr.prHead.trim()
        : undefined;
    return {
      kind: "completed",
      output: {
        kind: "ship",
        branch: familyBase,
        pr: pr.url,
        ...(prHead !== undefined ? { prHead } : {}),
        status: "pr_opened",
      },
    };
  }

  // #596 skeleton: deterministic no-op stubs for explicit offline/test contexts
  // only (#600 r5 — same gate as verifyCmr dispatchFamilyReviewWorker: a failed or
  // unavailable primary path must NOT synthesize convergence).
  const skeletonResult = skeletonReviewLoopWorkerResult(spec.kind);
  if (skeletonResult !== undefined) {
    if (offlineReviewLoopDispatchAdmissible(ctx)) {
      return skeletonResult;
    }
    return {
      kind: "failed",
      reason:
        `family ${spec.kind} worker unavailable: no dispatchWorker seam and ` +
        `offline skeleton synthesis inadmissible for PR ${ctx.prUrl ?? "(missing)"}`,
    };
  }

  throw new Error(
    `legacyDispatchFamilyWorker: unsupported family worker kind ${spec.kind}`,
  );
}
