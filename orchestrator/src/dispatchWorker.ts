/**
 * The unified worker-dispatch seam (ADR 0026 / PRD #330, #331).
 *
 * ADR 0026 makes the runner a PURE SCHEDULER: every step that produces or changes
 * the worked artifact is a WORKER, dispatched through ONE seam. This module is the
 * single-slice half of that seam:
 *
 *   - {@link stepSpecToWorkerSpec} — derive a {@link WorkerSpec} from the runner's
 *     fixed {@link StepSpec} table (the explicit, assertable dispatch decision:
 *     which skill, fresh|resume, soul — US#16/#18).
 *   - {@link dispatchWorker} — the free function the runner ALWAYS calls. It uses
 *     `backend.dispatchWorker` when a backend implements the unified seam, else
 *     falls back to {@link legacyDispatchWorker}.
 *   - {@link legacyDispatchWorker} — the compatibility wrapper for older
 *     Backends: forwards child coder/reviewer workers to `runStep`/`resumeSession`
 *     and wraps their returns into the discriminated {@link WorkerResult}.
 *   - {@link workerResultToStep} — unwrap a `completed` {@link WorkerResult} back
 *     into the `{@link StepOutput} | {@link StepResult}` shape the existing runner
 *     control flow consumes without changing route()/validate().
 */

import { shWithClock } from "./externalCall.js";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";

import {
  isJudgeSeat,
  materializeLandingFixPacketBody,
  mintJudgeEscalate,
} from "./judgeStation.js";
import {
  materializeRawReviewerArtifactsForSandbox,
  RAW_REVIEWER_SIDECAR_SANDBOX_FILE,
  RAW_REVIEWER_STDOUT_SANDBOX_FILE,
} from "./rawReviewerArtifacts.js";
import {
  modelForSlot,
  routeSmokeFailure,
  type ResolvedModelRoute,
} from "./modelRoutes.js";
import { resolveModelSlugForPool } from "./modelRegistry.js";
import type { BillingPoolId } from "./quotaPoolTable.js";
import {
  createTelemetryLegStamper,
  scheduleTelemetryEnvironmentStamp,
} from "./telemetry.js";
import { isMissingMonitorSidecarResult } from "./cliMonitorHooks.js";
import { abandonSpawnAfterAdoptionFailure } from "./dispatchRetry.js";
import {
  dispatchMonitoredCliWorker,
  logSilenceWholeMinutes,
  readLogActivity,
  waitForChildExit,
  type MonitoredCliDispatchInput,
  type WorkerMonitorDeps,
} from "./workerMonitor.js";
import type {
  Backend,
  DispatchContext,
  FixFindingsLandingFile,
  StepOutput,
  StepResult,
  StepSpec,
  WorkerContextRetention,
  WorkerKind,
  WorkerLandingPayload,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSessionMode,
  WorkerHost,
  WorkerSpec,
} from "./types.js";

const FIX_FINDINGS_LANDING_FILE = ".orchestrator-fix-findings.json";

/**
 * The worker host follows the executable provider selected by the registry.
 * `claudeCode` retains the historical `claude` host spelling; every other
 * provider is already the corresponding host CLI name.
 */
export function workerHostForModel(
  model: string,
  billingPool?: BillingPoolId,
): WorkerHost {
  const provider = resolveModelSlugForPool(model, billingPool).provider;
  return provider === "claudeCode" ? "claude" : provider;
}

const FIX_FINDINGS_LEDGER_FILE = "fix-findings.json";

/**
 * The wiki skill each worker kind invokes (ADR 0026):
 *   coder → `/tdd`, reviewer → `/code-review`, cmr → `ak-cross-m-review`,
 *   ship → `gstack-ship`, merge → none; review-loop agents: verify/fixer/landing.
 *   Cleanup is the S11 host-deterministic endgame action, not an agent skill.
 *
 * Production backends invoke these routed skills through the unified dispatch
 * seam. The legacy compatibility wrapper forwards only older child methods.
 */
const SKILL_FOR_KIND: Readonly<Record<WorkerKind, string | undefined>> = {
  coder: "/tdd",
  reviewer: "/code-review",
  cmr: "ak-cross-m-review",
  ship: "gstack-ship",
  merge: undefined,
  // Verify runs the shipped /verify skill through verify.md.
  verify: "/verify",
  // Fixer runs the shipped /fixer skill through fixer.md.
  fixer: "/fixer",
  cleanup: undefined,
  // #735: real 文档发布 — invoke /gstack-document-release (not a path-allowlist gate).
  landing: "/gstack-document-release",
};

/**
 * Map a {@link StepSpec.role} to its {@link WorkerKind} for the agent steps.
 * S2/S5 coder → `coder`; S3/S6 verify-judge → `verify` (#919 S2 / M4 live seat).
 * Residual role:"reviewer" still maps to kind reviewer for historical fixtures
 * only — live single-slice seats are role:"verify". (Ship/cmr/merge are built
 * directly, not from a role StepSpec.)
 */
function workerKindForRole(role: StepSpec["role"]): WorkerKind {
  if (role === "coder") return "coder";
  if (role === "reviewer") return "reviewer";
  return role;
}

/**
 * Context retention by work type (ADR 0026): production workers (coder/fix)
 * RETAIN context across fix rounds ("what I wrote, why"); review / judge seats
 * start each round CLEAN (clean eyes). This is DECOUPLED from the dispatch
 * {@link WorkerSessionMode} — a normal coder round is `session:"fresh"` yet
 * `contextRetention:"retain"` (ADR 0026 invariant: normal fix keeps maxIter,
 * NOT the crash/escalate resume path).
 *
 * #925 S3/S6 judge continuity is `resumeSessionId` only (same agent session).
 * #919 S2/R7: judge seats (S3/S6 only via isJudgeSeat) force clean via
 * {@link stepSpecToWorkerSpec}. Family online-review S9 is not a judge seat
 * and pins clean explicitly on its WorkerSpec.
 */
function retentionForKind(kind: WorkerKind): WorkerContextRetention {
  // Production workers (coder + post-review fixer) retain context across rounds.
  // Online-review verify kind defaults retain here; single-slice S3/S6 force
  // clean in stepSpecToWorkerSpec (session continuity is resumeSessionId).
  return kind === "coder" || kind === "fixer" || kind === "verify"
    ? "retain"
    : "clean";
}

function ensureGitExcluded(worktreePath: string, pattern: string): void {
  try {
    const excludePath = shWithClock(
      "git",
      ["-C", worktreePath, "rev-parse", "--git-path", "info/exclude"],
      { stage: "dispatch:git-exclude" },
    );
    if (excludePath.length === 0) return;
    const resolvedPath = resolve(worktreePath, excludePath);
    mkdirSync(join(resolvedPath, ".."), { recursive: true });
    const existing = existsSync(resolvedPath)
      ? readFileSync(resolvedPath, "utf8")
      : "";
    if (!existing.split(/\r?\n/).includes(pattern)) {
      appendFileSync(resolvedPath, `${existing.endsWith("\n") || existing.length === 0 ? "" : "\n"}${pattern}\n`);
    }
  } catch {
    // Best effort only: the file is still useful to the worker even if this is
    // a non-git fixture path. Real git worktrees get the exclude entry.
  }
}

function writeFixFindingsLandingFile(
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
): (FixFindingsLandingFile & { cleanup: boolean }) | undefined {
  const priorJudgeVerdicts =
    ctx.priorJudgeVerdicts !== undefined && ctx.priorJudgeVerdicts.length > 0
      ? ctx.priorJudgeVerdicts
      : undefined;
  const judgeSeat = isJudgeSeat({ id: spec.id });
  const needsFindingsLanding =
    (spec.id === "S5" && spec.kind === "coder") ||
    // #925 / #919 S2: S6 judge seat still needs fix-findings landing for
    // re-adjudication of prior open rows (sole isJudgeSeat predicate).
    (spec.id === "S6" && judgeSeat) ||
    ctx.escalationAnswer !== undefined ||
    // #925 F1: prior judge verdict rows must reach the worker via the same
    // fix-findings landing seam (session-loss / fresh-after-dead-session).
    (judgeSeat && priorJudgeVerdicts !== undefined);
  if (!needsFindingsLanding || ctx.worktree === undefined) {
    return undefined;
  }
  if (!existsSync(ctx.worktree.path)) return undefined;

  const landingPath =
    ctx.stateDir !== undefined
      ? join(ctx.stateDir, FIX_FINDINGS_LEDGER_FILE)
      : join(ctx.worktree.path, FIX_FINDINGS_LANDING_FILE);
  if (ctx.stateDir !== undefined) {
    mkdirSync(ctx.stateDir, { recursive: true });
  } else {
    ensureGitExcluded(ctx.worktree.path, FIX_FINDINGS_LANDING_FILE);
  }
  // Host monitor paths are not visible inside the fixer container. Copy
  // readable raw products into the sandbox cwd and rewrite pointers (#899).
  const rawReviewerArtifacts =
    landing?.rawReviewerArtifacts !== undefined
      ? materializeRawReviewerArtifactsForSandbox(
          landing.rawReviewerArtifacts,
          ctx.worktree.path,
        )
      : undefined;
  ensureGitExcluded(ctx.worktree.path, RAW_REVIEWER_STDOUT_SANDBOX_FILE);
  ensureGitExcluded(ctx.worktree.path, RAW_REVIEWER_SIDECAR_SANDBOX_FILE);
  // ADR 0138 / #978: packet content is judge-authored fixPacketBody only.
  // Identity keys stay on the thin control envelope (ctx); never derive packet
  // content from bare findings rows (deleted dual path).
  const identityKeys = [...(ctx.blockingFindingIdentityKeys ?? [])];
  // Coder-fix (S5) open set requires body; S6 judge re-adjudicate may carry
  // keys only (not a fix content packet). Shared helper with family writer.
  const isCoderFixLanding = spec.id === "S5" && spec.kind === "coder";
  const fixPacketBody = materializeLandingFixPacketBody({
    fixPacketBody: landing?.fixPacketBody,
    blockingFindingIdentityKeys: identityKeys,
    blockingFindingCount: ctx.blockingFindingCount,
    requireBodyWhenOpen: isCoderFixLanding,
  });
  writeFileSync(
    landingPath,
    `${JSON.stringify(
      {
        // ADR 0138: sole coder-fix packet content path — verbatim judge body.
        // Bare findings packing is deleted (no second content channel).
        ...(fixPacketBody !== undefined ? { fixPacketBody } : {}),
        ...(rawReviewerArtifacts !== undefined
          ? { rawReviewerArtifacts }
          : {}),
        // Opaque transport only — runner does not filter findings by scope
        // (#899 / ADR 0131 / C-R4-2A).
        ...(landing?.findingScope !== undefined
          ? { findingScope: landing.findingScope }
          : {}),
        blockingFindingIdentityKeys: identityKeys,
        ...(ctx.preexistingAssertionTouched === true
          ? { preexistingAssertionTouched: true }
          : {}),
        ...(ctx.refusedFindingIdentityKeys !== undefined &&
        ctx.refusedFindingIdentityKeys.length > 0
          ? { refusedFindingIdentityKeys: ctx.refusedFindingIdentityKeys }
          : {}),
        // #927: opaque refuse cargo (four reasons + evidence) for judge
        // re-adjudication — landing only (信封宪法); never from thin ctx.
        ...(landing?.refuseRecords !== undefined &&
        landing.refuseRecords.length > 0
          ? { refuseRecords: landing.refuseRecords }
          : {}),
        ...(ctx.escalationAnswer !== undefined
          ? { escalationAnswer: ctx.escalationAnswer }
          : {}),
        // #925 F1: structured prior judge verdict rows only — runner never
        // synthesises a narrative trajectory summary.
        ...(priorJudgeVerdicts !== undefined
          ? { priorJudgeVerdicts }
          : {}),
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
  return {
    path: landingPath,
    sandboxPath: FIX_FINDINGS_LANDING_FILE,
    cleanup: ctx.stateDir === undefined,
  };
}

function writeWorkerOutcomeLandingFile(
  spec: WorkerSpec,
  ctx: DispatchContext,
):
  | {
      path: string;
      sandboxPath: string;
    }
  | undefined {
  void spec;
  void ctx;
  // Coder/reviewer workers still use the stdout compatibility tag plus git commit
  // truth. The image guard currently rejects `--role coder`, and Sandcastle file
  // bind mounts can surface the sidecar as a busy directory in the worker, causing
  // agents to escalate on protocol plumbing instead of returning their real result.
  // Keep required sidecars only in the family CMR/ship seams where the guard
  // supports them.
  return undefined;
}

/**
 * Derive the declarative {@link WorkerSpec} for an agent step from the runner's
 * fixed {@link StepSpec}. The spec carries the explicit dispatch decision
 * (skill / session / contextRetention / soul / host) so the runner's scheduling
 * is assertable (US#16/#18/#19) — replacing the implicit "which method does the
 * runner call".
 *
 * `session` is supplied by the runner per-invocation: `"resume"` ONLY when it is
 * threading a `resumeSessionId` (crash/escalate resume OR #924 S5 continuity of
 * the S2 coder session); `"fresh"` otherwise. The default is `"fresh"` — a
 * worker is never marked `resume` by work type alone.
 */
export function stepSpecToWorkerSpec(
  spec: StepSpec,
  session: WorkerSessionMode = "fresh",
  billingPool?: BillingPoolId,
): WorkerSpec {
  const kind = workerKindForRole(spec.role);
  // #919 S2/R7: S3/S6 judge seats are clean-eyes via sole isJudgeSeat predicate
  // (promptFile is the station contract). S9 kind:verify is online-review, not
  // judge — skill /verify is unused by RealBackend.runStep for S3/S6.
  const judgeSeat = isJudgeSeat({ id: spec.id });
  return {
    id: spec.id,
    kind,
    role: spec.role,
    host: workerHostForModel(spec.model, billingPool),
    session,
    contextRetention: judgeSeat ? "clean" : retentionForKind(kind),
    skill: SKILL_FOR_KIND[kind],
    promptFile: spec.promptFile,
    maxIter: spec.maxIter,
    model: spec.model,
    soul: spec.soul,
    toolchain: spec.toolchain,
  };
}

// Prompt status: verify.md / fixer.md real paths shipped in #600;
// landing.md real path shipped in #735. Cleanup is host-deterministic (#603).
export const VERIFY_PROMPT_FILE = "verify.md";
export const FIXER_PROMPT_FILE = "fixer.md";
export const LANDING_PROMPT_FILE = "landing.md";

/** Family S9 online-review / PR-check worker spec (#600 real prompt). */
export function verifyWorkerSpec(
  route?: ResolvedModelRoute,
  billingPool?: BillingPoolId,
): WorkerSpec {
  const model = route?.slots.verify ?? modelForSlot("verify");
  return {
    id: "S9",
    kind: "verify",
    role: "verify",
    host: workerHostForModel(model, billingPool),
    session: "fresh",
    contextRetention: "clean",
    skill: SKILL_FOR_KIND.verify,
    promptFile: VERIFY_PROMPT_FILE,
    maxIter: 1,
    model,
    soul: "verify",
    toolchain: [],
  };
}

/** Family S10 post-review fixer worker spec (#600 real prompt). */
export function fixerWorkerSpec(
  route?: ResolvedModelRoute,
  billingPool?: BillingPoolId,
): WorkerSpec {
  const model = route?.slots.fixer ?? modelForSlot("fixer");
  return {
    id: "S10",
    kind: "fixer",
    role: "fixer",
    host: workerHostForModel(model, billingPool),
    session: "fresh",
    contextRetention: "retain",
    skill: SKILL_FOR_KIND.fixer,
    promptFile: FIXER_PROMPT_FILE,
    // #899 / ADR 0128 / #928: one single-iteration Sandcastle run per seat.
    maxIter: 1,
    model,
    soul: "fixer",
    toolchain: [],
  };
}

/**
 * Family S12 文档发布 worker (#735): invoke `/gstack-document-release` in a spawned /
 * non-interactive session. Success (including 文档发布空跑) → `released:true`;
 * skill crash / hang / explicit fail / required push fail → not released.
 * Landing Action dispatches this seat; no offline green stub hatch.
 */
export function landingWorkerSpec(
  route?: ResolvedModelRoute,
  billingPool?: BillingPoolId,
): WorkerSpec {
  const model = route?.slots.landing ?? modelForSlot("landing");
  return {
    id: "S12",
    kind: "landing",
    role: "landing",
    host: workerHostForModel(model, billingPool),
    session: "fresh",
    contextRetention: "clean",
    skill: SKILL_FOR_KIND.landing,
    promptFile: LANDING_PROMPT_FILE,
    maxIter: 1,
    model,
    soul: "landing",
    toolchain: [],
  };
}

/**
 * Compatibility wrapper for older Backends: forward a child worker to the
 * existing methods and wrap the return into a {@link WorkerResult}.
 *
 *   - coder (S2 build / S5 fix): when `ctx.resumeSessionId` is set the worker is
 *     dispatched via `backend.resumeSession` (#924 S5 continuity of the S2
 *     session, or crash/escalate reopen); else via `backend.runStep`. The
 *     returned `StepOutput | StepResult` is wrapped as `completed` (carrying the
 *     real per-step `sessionId` when surfaced).
 * This wrapper yields `completed`; unified real workers produce process `failed`
 * and worker-declared `escalated` results directly.
 */
/**
 * Surface used by {@link legacyDispatchWorker}: only the pre-unified child
 * agent methods. Production backends implement full {@link Backend}; tests may
 * supply a minimal adapter without double-casting to Backend.
 */
export type LegacyDispatchBackend = Pick<Backend, "runStep" | "resumeSession">;

export async function legacyDispatchWorker(
  backend: LegacyDispatchBackend,
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
): Promise<WorkerResult> {
  // #919 S2: S3/S6 verify-judge seats use the same runStep/resumeSession path
  // as residual reviewer; family online-review kind:verify uses family dispatch.
  const runStepKinds = new Set<WorkerKind>(["coder", "reviewer", "verify"]);
  if (!runStepKinds.has(spec.kind)) {
    throw new Error(
      `legacyDispatchWorker: worker kind '${spec.kind}' (${spec.id}) has no legacy ` +
        `dispatch path — only child coder/reviewer/verify-judge workers are forwarded. ` +
        `Family endgame workers must use the family dispatch seam.`,
    );
  }
  // coder / reviewer agent worker → runStep | resumeSession (legacy seam).
  if (ctx.worktree === undefined) {
    throw new Error(
      `legacyDispatchWorker: agent worker ${spec.id} requires a worktree`,
    );
  }
  const stepSpec = workerSpecToStepSpec(spec);
  let ret: StepOutput | StepResult;
  const fixFindingsLanding = writeFixFindingsLandingFile(spec, ctx, landing);
  const fixFindingsOptions =
    fixFindingsLanding !== undefined
      ? {
          fixFindingsLanding: {
            path: fixFindingsLanding.path,
            sandboxPath: fixFindingsLanding.sandboxPath,
          },
        }
      : undefined;
  const outcomeLanding = writeWorkerOutcomeLandingFile(spec, ctx);
  const runOptions =
    fixFindingsOptions !== undefined ||
    outcomeLanding !== undefined ||
    ctx.billingPool !== undefined ||
    ctx.relayBrief !== undefined
      ? {
          ...(fixFindingsOptions ?? {}),
          ...(outcomeLanding !== undefined ? { outcomeLanding } : {}),
          ...(ctx.billingPool !== undefined
            ? { billingPool: ctx.billingPool }
            : {}),
          ...(ctx.relayBrief !== undefined
            ? { relayBrief: ctx.relayBrief }
            : {}),
        }
      : undefined;
  try {
    // Robust guard (typeof string): explicit null from any source (incl. a
    // deserialized ledger with bad sessionId that slipped parse) must be
    // treated as absent, never passed as `resumeSessionId: null` to backend.
    // (The key presence vs value was load-bearing; we now require a real string id.)
    if (typeof ctx.resumeSessionId === "string") {
      ret = await backend.resumeSession(
        stepSpec,
        ctx.worktree,
        ctx.resumeSessionId,
        runOptions,
      );
    } else {
      ret = await backend.runStep(
        stepSpec,
        ctx.worktree,
        runOptions,
      );
    }
  } finally {
    if (fixFindingsLanding?.cleanup) {
      rmSync(fixFindingsLanding.path, { force: true });
    }
    if (ctx.worktree !== undefined) {
      // Materialised host artifacts live next to the worktree cwd; always
      // best-effort remove so a crash mid-fix does not leave host copies.
      rmSync(join(ctx.worktree.path, RAW_REVIEWER_STDOUT_SANDBOX_FILE), {
        force: true,
      });
      rmSync(join(ctx.worktree.path, RAW_REVIEWER_SIDECAR_SANDBOX_FILE), {
        force: true,
      });
    }
  }
  const { output, sessionId } = normalizeStepReturn(ret);
  return { kind: "completed", output, sessionId };
}

/**
 * THE seam entry point: dispatch a worker, preferring the backend's unified
 * `dispatchWorker` when implemented, else the legacy forwarding wrapper. The
 * runner calls ONLY this, so its dispatch path is one line regardless of which
 * Backend (real / fake / legacy) it was injected with (#331 acceptance).
 */
export async function dispatchWorker(
  backend: Backend,
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
): Promise<WorkerResult> {
  if (ctx.modelRoute === undefined) {
    throw new Error("worker dispatch refused (fail-closed): model route smoke state is missing");
  }
  const smokeFailure = routeSmokeFailure(ctx.modelRoute);
  if (smokeFailure !== undefined) {
    throw new Error(`worker dispatch refused (fail-closed): ${smokeFailure}`);
  }
  if (backend.dispatchWorker !== undefined) {
    return backend.dispatchWorker(spec, ctx, landing);
  }
  return legacyDispatchWorker(backend, spec, ctx, landing);
}

/**
 * Production dispatch outcome (#684): the {@link WorkerResult} plus an optional
 * monitor handle when the worker was spawned as a host-side CLI process.
 */
export interface DispatchWorkerWithMonitorOutcome {
  readonly result: WorkerResult;
  readonly monitorHandle?: WorkerMonitorHandle;
  /**
   * Resolves after this ledger's first-run telemetry environment stamp finishes
   * (including fail-open handling). Dispatch never awaits it; callers that are
   * about to exit or read telemetry can join it explicitly.
   */
  readonly telemetryEnvironmentStamp: Promise<void>;
}

/**
 * Options for {@link dispatchWorkerWithMonitor} (#684 R2).
 *
 * `onMonitorHandleSpawned` fires AT SPAWN TIME — before waiting for the child
 * to exit — so the runner can persist the handle to the ledger while the worker
 * is still running (observation + exact-handle adoption/terminate need a live
 * handle, not a post-exit one).
 */
export interface DispatchWorkerWithMonitorOptions {
  readonly onMonitorHandleSpawned?: (
    handle: WorkerMonitorHandle,
  ) => void | Promise<void>;
  /** Injectable monitor I/O for tests; production uses verified OS helpers. */
  readonly monitorDeps?: WorkerMonitorDeps;
}

/**
 * THE production dispatch path used by the runner (#684).
 *
 * When the backend supplies a CLI spawn via {@link Backend.resolveCliMonitorDispatch},
 * this spawns through {@link dispatchMonitoredCliWorker} so the monitor handle
 * (pid / log / pool / signal / instance identity) is generated atomically with
 * real dispatch, then maps the finished process via
 * {@link Backend.awaitMonitoredCliWorker}.
 *
 * The handle is handed to {@link DispatchWorkerWithMonitorOptions.onMonitorHandleSpawned}
 * immediately after spawn (before wait) so ledger persistence can happen at
 * spawn time (#684 R2).
 *
 * Otherwise falls through to {@link dispatchWorker} (container / legacy seam)
 * with no monitor handle.
 *
 * The runner always calls this (not bare {@link dispatchWorker}) so CLI workers
 * land a ledger-rebuildable handle and exact-handle adoption/terminate never
 * needs global process-name matching. RealBackend / RealFamilyBackend implement
 * the hooks so Child S2/S3/S5/S6 and family S9–S12 take this monitored branch in
 * production.
 */
export async function dispatchWorkerWithMonitor(
  backend: Backend,
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
  opts?: DispatchWorkerWithMonitorOptions,
): Promise<DispatchWorkerWithMonitorOutcome> {
  // #786 — per-leg telemetry sidecar (dispatch + collect half-rows).
  // Best-effort only: never changes worker semantics or resume contracts.
  // Optional chaining only guards missing methods; a throwing implementation
  // must not abort dispatch (CodeRabbit #815 / fail-open).
  let telemetryDir = ctx.telemetryDir;
  if (telemetryDir === undefined) {
    try {
      telemetryDir = backend.resolveTelemetryDir?.(ctx);
    } catch (err) {
      console.warn(
        `[orchestrator] resolveTelemetryDir failed (fail-open): ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
    telemetryDir = telemetryDir ?? ctx.stateDir;
  }
  const telemetryCtx =
    telemetryDir === undefined ? ctx : { ...ctx, telemetryDir };
  let firstOutputAt: string | null = null;
  let logPath: string | null = null;
  let logStartOffset: number | undefined;
  let telemetryEnvironmentStamp = Promise.resolve();
  const telemetry = createTelemetryLegStamper({
    ledgerDir: telemetryDir,
    spec,
    ctx: telemetryCtx,
  });

  /**
   * #786 first_output_at — first *observed* log growth past the post-spawn
   * orchestrator marker (not subsequent poll-only growth; not true TTFB).
   *
   * Semantics = poll granularity: stamp is wall-clock of this call, so error
   * upper bound ≈ pollIntervalMs under the idle loop. Covers (a) worker
   * output already present on the first activity snapshot and (b) quick-exit
   * reconcile (stamp ≈ process exit time) when the poll loop never saw growth.
   * See TelemetryCollectRecord.first_output_at + orchestrator/README.md.
   */
  const noteFirstOutputIfPastBaseline = (
    sizeBytes: number,
    baselineBytes: number,
  ): void => {
    if (firstOutputAt === null && sizeBytes > baselineBytes) {
      firstOutputAt = new Date().toISOString();
    }
  };

  const reconcileFirstOutputAt = (
    handle: WorkerMonitorHandle,
    baselineBytes: number,
    monitorDeps: WorkerMonitorDeps | undefined,
  ): void => {
    if (firstOutputAt !== null) return;
    const activity = readLogActivity(handle, monitorDeps);
    if (activity !== undefined) {
      noteFirstOutputIfPastBaseline(activity.sizeBytes, baselineBytes);
    }
  };

  try {
    const cliSpec = backend.resolveCliMonitorDispatch?.(spec, telemetryCtx, landing);

    if (cliSpec !== undefined) {
      const input: MonitoredCliDispatchInput = {
        command: cliSpec.command,
        args: cliSpec.args,
        logDir: cliSpec.logDir,
        poolId: cliSpec.poolId,
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
      logPath = handle.logPath;
      logStartOffset = handle.logStartOffset;
      // Dispatch half-row AFTER spawn: use the monitor handle's exact stamp
      // (same clock as the log line / instance identity), not a pre-parse guess.
      telemetry.stampDispatch(handle.dispatchedAt, cliSpec.poolId);
      const exitPromise = waitForChildExit(child);
      // Schedule before the caller callback. A failed durable-handle write still
      // leaves the asynchronous, best-effort environment row for this run.
      telemetryEnvironmentStamp = scheduleTelemetryEnvironmentStamp(
        telemetryDir,
        telemetryCtx,
        backend,
      );
      // SPAWN-TIME persist seam: handle is available before waitForChildExit.
      // Adoption-record failure terminates the exact ChildProcess/process group
      // (#934 ID-006) — no PID-tree walk.
      if (opts?.onMonitorHandleSpawned !== undefined) {
        try {
          await opts.onMonitorHandleSpawned(handle);
        } catch (error) {
          // #934 ID-006 / #937 S1: single adoption-failure cleanup court.
          await abandonSpawnAfterAdoptionFailure({
            child,
            exitPromise,
            adoptionError: error,
            instanceId: handle.instanceId,
            monitorDeps: opts?.monitorDeps,
          });
        }
      }
      const monitorDeps = opts?.monitorDeps;
      // Baseline = pre-dispatch size + orchestrator marker line. Growth past this
      // is worker (or tool) output — not the dispatch marker itself. Observational
      // only: silence never kills/retries/relays (#934 ID-007).
      const firstOutputBaseline = firstOutputBaselineBytes(handle);
      const initialActivity = readLogActivity(handle, monitorDeps);
      if (initialActivity !== undefined) {
        noteFirstOutputIfPastBaseline(
          initialActivity.sizeBytes,
          firstOutputBaseline,
        );
      }
      const race = await exitPromise;
      // One-shot re-read so first_output_at is not left null when bytes exist.
      reconcileFirstOutputAt(handle, firstOutputBaseline, monitorDeps);
      // #934 ID-007: on-demand whole-minute silence report from last-activity.
      // Pure observation — never kill/retry/relay/park/fail.
      const lastActivity = readLogActivity(handle, monitorDeps);
      if (lastActivity !== undefined) {
        logSilenceWholeMinutes(`worker ${spec.id}`, lastActivity.mtimeMs);
      }
      const exitCode = race.kind === "exit" ? race.exitCode : null;
      const killSignal = race.kind === "killed" ? race.signal : null;
      if (backend.awaitMonitoredCliWorker === undefined) {
        const result: WorkerResult =
          killSignal !== null
            ? {
                kind: "failed",
                reason: `CLI worker ${spec.id} killed by signal ${killSignal}`,
              }
            : {
                kind: "failed",
                reason:
                  `CLI worker ${spec.id} finished (exit ${exitCode}) but backend has ` +
                  `no awaitMonitoredCliWorker to map the process into a WorkerResult`,
              };
        telemetry.stampCollect(
          { kind: "result", result },
          { logPath, logStartOffset, firstOutputAt },
        );
        return { result, monitorHandle: handle, telemetryEnvironmentStamp };
      }
      let result = await backend.awaitMonitoredCliWorker(
        handle,
        exitCode,
        spec,
        ctx,
        landing,
      );
      // No usable sidecar after a signal kill → stamp killed (telemetry cluster);
      // a real sidecar outcome (completed / escalated / structured failed) wins.
      if (
        killSignal !== null &&
        isMissingMonitorSidecarResult(result)
      ) {
        result = {
          kind: "failed",
          reason: `CLI worker ${spec.id} killed by signal ${killSignal}`,
        };
      }
      // #937 / #934 ID-007: free-log relay/decision parsing is deleted — process
      // exit + typed sidecar are the only host fate channels.
      reconcileFirstOutputAt(handle, firstOutputBaseline, monitorDeps);
      telemetry.stampCollect(
        { kind: "result", result },
        { logPath, logStartOffset, firstOutputAt },
      );
      return { result, monitorHandle: handle, telemetryEnvironmentStamp };
    }
    // Container / legacy path: stamp dispatch at the moment we hand off to the
    // backend (no monitor handle.dispatchedAt available).
    telemetry.stampDispatch(
      new Date().toISOString(),
      ctx.billingPool !== undefined ? ctx.billingPool : undefined,
    );
    telemetryEnvironmentStamp = scheduleTelemetryEnvironmentStamp(
      telemetryDir,
      telemetryCtx,
      backend,
    );
    const result = await dispatchWorker(backend, spec, ctx, landing);
    telemetry.stampCollect({ kind: "result", result });
    return { result, telemetryEnvironmentStamp };
  } catch (err) {
    telemetry.stampCollect(
      { kind: "thrown", error: err },
      { logPath, logStartOffset, firstOutputAt },
    );
    // Error propagation is a terminal boundary: give the first-run environment
    // stamp its fail-open completion opportunity before callers retry or relay.
    await telemetryEnvironmentStamp;
    throw err;
  }
}

/**
 * Byte offset after the pre-dispatch log prefix + the orchestrator spawn marker
 * written by {@link dispatchMonitoredCliWorker}. Worker first-output is any
 * further growth past this baseline (marker alone does not count).
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
 * Unwrap a `completed` {@link WorkerResult} into the `StepOutput | StepResult`
 * shape the existing runner control flow (#256 normalisation, validate, route)
 * consumes for an AGENT step — so the unified seam leaves route()/validate()
 * untouched. A non-`completed` result is mapped to an escalate/garbage StepOutput
 * the runner's existing guards already handle:
 *   - `escalated` → a coder/reviewer output carrying the escalate (route() takes
 *     the global escalate edge → S8(escalate)).
 *   - process `failed` → `{ unwrapped: undefined, reason }` for S8(error).
 *
 * Returns `{ unwrapped, reason? }`; only process failure carries an error reason.
 */
export function workerResultToStep(
  result: WorkerResult,
  expectedKind: "coder" | "reviewer" | "verify",
): { unwrapped: StepOutput | StepResult | undefined; reason?: string } {
  if (result.kind === "completed") {
    return {
      unwrapped:
        result.sessionId !== undefined
          ? { output: result.output, sessionId: result.sessionId }
          : result.output,
    };
  }
  if (result.kind === "escalated") {
    // Attach the escalate to a minimal role-shaped output so route()'s
    // escalate-first edge fires (the runner checks `output.escalate` before the
    // full role schema).
    // #919 M4 / U1: non-coder agent seats (live role:"verify" judge) mint T2
    // kind:"judge" escalate — never residual open-count reviewer paper.
    const output: StepOutput =
      expectedKind === "coder"
        ? {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: result.escalation,
          }
        : mintJudgeEscalate(result.escalation);
    // PRESERVE the worker's sessionId on the escalate path (codex cmr R4 finding):
    // the human-answer resume (planResume → resumeSession) resumes the recorded
    // ledger sessionId; dropping it here would resume the wrong (run-level UUID)
    // session. Wrap as a StepResult when the id is present, mirroring `completed`.
    return {
      unwrapped:
        result.sessionId !== undefined
          ? { output, sessionId: result.sessionId }
          : output,
    };
  }
  // Process failure remains an error fact.
  return { unwrapped: undefined, reason: result.reason };
}

// ───────────────────────── internal helpers ─────────────────────────

/** Rebuild a {@link StepSpec} from a {@link WorkerSpec} for the legacy methods. */
function workerSpecToStepSpec(spec: WorkerSpec): StepSpec {
  return {
    id: spec.id,
    role: spec.role,
    promptFile: spec.promptFile,
    model: spec.model,
    maxIter: spec.maxIter,
    soul: spec.soul,
    toolchain: spec.toolchain,
  };
}

/** Normalise the legacy seam return (StepOutput | StepResult) → {output, sessionId}. */
function normalizeStepReturn(ret: StepOutput | StepResult): {
  output: StepOutput;
  sessionId?: string;
} {
  // A StepResult wraps the output under `.output` and has no top-level `kind`;
  // a bare StepOutput always carries `kind` (#256 normalisation contract).
  if (ret != null && "output" in ret && !("kind" in ret)) {
    return { output: ret.output, sessionId: ret.sessionId };
  }
  return { output: ret as StepOutput };
}
