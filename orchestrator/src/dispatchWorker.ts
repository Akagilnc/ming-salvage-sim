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

import type { ChildProcess } from "node:child_process";
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
  FIX_FOCUS_LANDING_FILE,
  formatFixFocusMarkdown,
} from "./findingFamilies.js";
import { findingIdentityKeys } from "./findings.js";
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
  HangWithLivePoolError,
  SelfReportedRelayError,
  tryParseActionableRelayTag,
} from "./relayDispatch.js";
import {
  createTelemetryLegStamper,
  readDispatchLogSlice,
  scheduleTelemetryEnvironmentStamp,
} from "./telemetry.js";
import { isMissingMonitorSidecarResult } from "./cliMonitorHooks.js";
import {
  dispatchMonitoredCliWorker,
  isWorkerIdle,
  killWorkerTree,
  readLogActivity,
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
  MonitoredWorkerIdleDisposition,
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
 *   ship → `gstack-ship`, merge → none; review-loop agents: verify/fixer/docRelease.
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
  docRelease: "/gstack-document-release",
};

/**
 * Map a {@link StepSpec.role} to its {@link WorkerKind} for the agent steps.
 * S2/S5 coder → `coder`; S3/S6 reviewer → `reviewer`. (Ship/cmr/merge are built
 * directly, not from a role StepSpec.)
 */
function workerKindForRole(role: StepSpec["role"]): WorkerKind {
  if (role === "coder") return "coder";
  if (role === "reviewer") return "reviewer";
  return role;
}

/**
 * Context retention by work type (ADR 0026): production workers (coder/fix)
 * RETAIN context across fix rounds ("what I wrote, why"); review workers
 * (reviewer/cmr) start each round CLEAN (clean eyes, cross-model independence).
 * This is DECOUPLED from the dispatch {@link WorkerSessionMode} — a normal coder
 * round is `session:"fresh"` yet `contextRetention:"retain"` (ADR 0026 invariant:
 * normal fix keeps maxIter, NOT the crash/escalate resume path).
 *
 * #925 S3/S6 judge continuity is `resumeSessionId` only (same agent session).
 * Single-slice seats keep WorkerKind `reviewer` (fixture/compat seam, AS4) so
 * `contextRetention` stays `"clean"` here — do not read that flag as "judge
 * loses trajectory"; trajectory after session loss is priorJudgeVerdicts
 * landing, not contextRetention.
 */
function retentionForKind(kind: WorkerKind): WorkerContextRetention {
  // Production workers (coder + post-review fixer) retain context across rounds.
  // `verify` kind is the family online-review seat; single-slice S3/S6 judges
  // stay `reviewer` → clean (session continuity is resumeSessionId, not this).
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

function writeFixFocusLandingFile(
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
): (FixFindingsLandingFile & { cleanup: boolean }) | undefined {
  const needsFixFocus =
    landing?.findingFamilies !== undefined &&
    landing.findingFamilies.length > 0 &&
    (spec.kind === "fixer" ||
      (spec.kind === "coder" &&
        (spec.id === "S5" || ctx.blockingFindingIdentityKeys !== undefined)));
  if (!needsFixFocus || ctx.worktree === undefined) {
    return undefined;
  }
  if (!existsSync(ctx.worktree.path)) return undefined;

  const landingPath =
    ctx.stateDir !== undefined
      ? join(ctx.stateDir, "fix-focus.md")
      : join(ctx.worktree.path, FIX_FOCUS_LANDING_FILE);
  if (ctx.stateDir !== undefined) {
    mkdirSync(ctx.stateDir, { recursive: true });
  } else {
    ensureGitExcluded(ctx.worktree.path, FIX_FOCUS_LANDING_FILE);
  }
  writeFileSync(
    landingPath,
    `${formatFixFocusMarkdown(landing.findingFamilies!)}\n`,
    "utf8",
  );
  return {
    path: landingPath,
    sandboxPath: FIX_FOCUS_LANDING_FILE,
    cleanup: ctx.stateDir === undefined,
  };
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
  const needsFindingsLanding =
    (spec.id === "S5" && spec.kind === "coder") ||
    // #925: S6 is the verify judge (kind verify/reviewer); still needs
    // fix-findings landing for re-adjudication of prior open rows.
    (spec.id === "S6" && (spec.kind === "reviewer" || spec.kind === "verify")) ||
    ctx.escalationAnswer !== undefined ||
    // #925 F1: prior judge verdict rows must reach the worker via the same
    // fix-findings landing seam (session-loss / fresh-after-dead-session).
    ((spec.id === "S3" || spec.id === "S6") && priorJudgeVerdicts !== undefined);
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
  // Identity keys are derived here at the fixer-landing boundary from opaque
  // findings cargo — not by the runner reading cargo fields (ADR 0131 / #899).
  // Prefer cargo-derived keys; fall back to ctx keys when findings rows are
  // sparse (family envelope / count-only reopen may still carry prior keys).
  const findingsRows = landing?.blockingFindings ?? [];
  const identityKeys =
    findingsRows.length > 0
      ? findingIdentityKeys(findingsRows)
      : [...(ctx.blockingFindingIdentityKeys ?? [])];
  writeFileSync(
    landingPath,
    `${JSON.stringify(
      {
        // Rich finding CONTENT comes from the SEPARATE landing payload (信封宪法,
        // ADR 0062) — never from the runner's thin DispatchContext.
        blockingFindings: findingsRows,
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
  return {
    id: spec.id,
    kind,
    role: spec.role,
    host: workerHostForModel(spec.model, billingPool),
    session,
    contextRetention: retentionForKind(kind),
    skill: SKILL_FOR_KIND[kind],
    promptFile: spec.promptFile,
    completionSignal: spec.completionSignal,
    maxIter: spec.maxIter,
    model: spec.model,
    soul: spec.soul,
    toolchain: spec.toolchain,
  };
}

// Prompt status: verify.md / fixer.md real paths shipped in #600;
// docRelease.md real path shipped in #735. Cleanup is host-deterministic (#603).
export const VERIFY_PROMPT_FILE = "verify.md";
export const FIXER_PROMPT_FILE = "fixer.md";
export const DOCRELEASE_PROMPT_FILE = "docRelease.md";

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
    completionSignal: "VERIFY_STEP_COMPLETE",
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
    completionSignal: "FIXER_STEP_COMPLETE",
    // #899 / ADR 0128: one single-iteration Sandcastle run per selected seat.
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
 * Offline/test may still synthesize via the offline hatch only.
 */
export function docReleaseWorkerSpec(
  route?: ResolvedModelRoute,
  billingPool?: BillingPoolId,
): WorkerSpec {
  const model = route?.slots.docRelease ?? modelForSlot("docRelease");
  return {
    id: "S12",
    kind: "docRelease",
    role: "docRelease",
    host: workerHostForModel(model, billingPool),
    session: "fresh",
    contextRetention: "clean",
    skill: SKILL_FOR_KIND.docRelease,
    promptFile: DOCRELEASE_PROMPT_FILE,
    completionSignal: "DOCRELEASE_STEP_COMPLETE",
    maxIter: 1,
    model,
    soul: "docRelease",
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
  const runStepKinds = new Set<WorkerKind>(["coder", "reviewer"]);
  if (!runStepKinds.has(spec.kind)) {
    throw new Error(
      `legacyDispatchWorker: worker kind '${spec.kind}' (${spec.id}) has no legacy ` +
        `dispatch path — only child coder/reviewer workers are forwarded. ` +
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
  const fixFocusLanding = writeFixFocusLandingFile(spec, ctx, landing);
  const fixFindingsOptions =
    fixFindingsLanding !== undefined
      ? {
          fixFindingsLanding: {
            path: fixFindingsLanding.path,
            sandboxPath: fixFindingsLanding.sandboxPath,
          },
        }
      : undefined;
  const fixFocusOptions =
    fixFocusLanding !== undefined
      ? {
          fixFocusLanding: {
            path: fixFocusLanding.path,
            sandboxPath: fixFocusLanding.sandboxPath,
          },
        }
      : undefined;
  const outcomeLanding = writeWorkerOutcomeLandingFile(spec, ctx);
  const runOptions =
    fixFindingsOptions !== undefined ||
    fixFocusOptions !== undefined ||
    outcomeLanding !== undefined ||
    ctx.billingPool !== undefined ||
    ctx.relayFocusPath !== undefined
      ? {
          ...(fixFindingsOptions ?? {}),
          ...(fixFocusOptions ?? {}),
          ...(outcomeLanding !== undefined ? { outcomeLanding } : {}),
          ...(ctx.billingPool !== undefined
            ? { billingPool: ctx.billingPool }
            : {}),
          ...(ctx.relayFocusPath !== undefined
            ? { relayFocusPath: ctx.relayFocusPath }
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
    if (fixFocusLanding?.cleanup) {
      rmSync(fixFocusLanding.path, { force: true });
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
 * is still running (hang judge/kill/resume needs a live handle, not a post-exit
 * one).
 */
export interface DispatchWorkerWithMonitorOptions {
  readonly onMonitorHandleSpawned?: (
    handle: WorkerMonitorHandle,
  ) => void | Promise<void>;
  /** Idle threshold used by the host-side monitor; production keeps this explicit. */
  readonly idleThresholdMs?: number;
  /** Poll cadence for the host-side idle clock. */
  readonly pollIntervalMs?: number;
  /** Injectable monitor I/O for tests; production uses verified OS helpers. */
  readonly monitorDeps?: WorkerMonitorDeps;
}

type ChildExit =
  | { readonly kind: "exit"; readonly exitCode: number | null }
  | { readonly kind: "killed"; readonly signal: NodeJS.Signals };

type MonitorRace = ChildExit;

const DEFAULT_MONITOR_IDLE_THRESHOLD_MS = 10 * 60 * 1000;
const CLAUDE_MONITOR_IDLE_THRESHOLD_MS = 30 * 60 * 1000;
const MAX_MONITOR_IDLE_SECONDS = 2_147_483;
const DEFAULT_MONITOR_POLL_INTERVAL_MS = 250;

/**
 * #808 productive-worker idle monitor budget. The general 10-minute tier keeps
 * genuinely silent workers killable, while Claude's thinking-heavy CLI gets a
 * 30-minute default: W1 telemetry recorded six Sonnet S5 legs being killed by
 * the former threshold before first output under three-container concurrency.
 *
 * `ORCHESTRATOR_WORKER_IDLE_SECONDS` is deliberately resolved for every
 * dispatch, like the route-smoke override, so an in-process operator change
 * applies without reloading this module. Invalid values fall back to the
 * provider tier; the upper bound keeps a seconds-to-milliseconds conversion
 * within a signed 32-bit timer should a caller reuse the value as a delay.
 */
export function resolveWorkerMonitorIdleThresholdMs(
  spec: Pick<WorkerSpec, "host">,
  envValue: string | undefined,
): number {
  const defaultMs =
    spec.host === "claude"
      ? CLAUDE_MONITOR_IDLE_THRESHOLD_MS
      : DEFAULT_MONITOR_IDLE_THRESHOLD_MS;
  if (envValue === undefined || envValue.trim() === "") return defaultMs;
  const parsed = Number(envValue.trim());
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > MAX_MONITOR_IDLE_SECONDS) {
    return defaultMs;
  }
  return parsed * 1000;
}

/**
 * Wait for a monitored child to leave the process table.
 * Signal-killed children resolve as `{ kind: "killed" }` so telemetry can stamp
 * a `killed` collect row instead of treating `exitCode === null` as a quiet exit.
 */
function waitForChildExit(child: ChildProcess): Promise<ChildExit> {
  const toExit = (
    code: number | null,
    signal: NodeJS.Signals | null,
  ): ChildExit => {
    if (signal !== null) {
      return { kind: "killed", signal };
    }
    return { kind: "exit", exitCode: code };
  };
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve(toExit(child.exitCode, child.signalCode));
  }
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve(toExit(code, signal)));
  });
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
 * land a ledger-rebuildable handle and hang/kill judgment never needs global
 * process-name matching. RealBackend / RealFamilyBackend implement the hooks so
 * Child S2/S3/S5/S6 and family S9–S12 take this monitored branch in production.
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
      // SPAWN-TIME persist seam: handle is available before waitForChildExit so a
      // hang still leaves a ledger-rebuildable handle for judge/kill/resume.
      if (opts?.onMonitorHandleSpawned !== undefined) {
        try {
          await opts.onMonitorHandleSpawned(handle);
        } catch (error) {
          await killWorkerTree(handle);
          try {
            await exitPromise;
          } catch {
            // Preserve the original spawn-persist error if child cleanup fails.
          }
          throw error;
        }
      }
      const monitorDeps = opts?.monitorDeps;
      const idleThresholdMs =
        opts?.idleThresholdMs ??
        resolveWorkerMonitorIdleThresholdMs(spec, process.env.ORCHESTRATOR_WORKER_IDLE_SECONDS);
      const pollIntervalMs =
        opts?.pollIntervalMs ?? DEFAULT_MONITOR_POLL_INTERVAL_MS;
      // Baseline = pre-dispatch size + orchestrator marker line. Growth past this
      // is worker (or tool) output — not the dispatch marker itself.
      const firstOutputBaseline = firstOutputBaselineBytes(handle);
      const initialActivity = readLogActivity(handle, monitorDeps);
      if (initialActivity !== undefined) {
        noteFirstOutputIfPastBaseline(
          initialActivity.sizeBytes,
          firstOutputBaseline,
        );
      }
      // Cancellation seam: when exit wins the race, stop further idle polls /
      // handleMonitoredWorkerIdle calls. A throw already in-flight is observed
      // below so it cannot become an unhandledRejection.
      let monitorCancelled = false;
      const monitorPromise: Promise<MonitorRace> = (async () => {
        if (initialActivity === undefined) {
          return await exitPromise;
        }
        let previous = initialActivity;
        while (
          !monitorCancelled &&
          child.exitCode === null &&
          child.signalCode === null
        ) {
          await (monitorDeps?.sleepMs ?? ((ms) => new Promise<void>((resolve) => setTimeout(resolve, ms))))(
            pollIntervalMs,
          );
          if (monitorCancelled) break;
          if (child.exitCode !== null || child.signalCode !== null) break;
          if (!isWorkerIdle(handle, idleThresholdMs, previous, monitorDeps)) {
            const current = readLogActivity(handle, monitorDeps);
            if (current !== undefined) {
              // First growth past post-marker baseline (not merely vs previous).
              noteFirstOutputIfPastBaseline(
                current.sizeBytes,
                firstOutputBaseline,
              );
              previous = current;
            }
            continue;
          }
          if (monitorCancelled) break;
          const disposition: MonitoredWorkerIdleDisposition =
            backend.handleMonitoredWorkerIdle !== undefined
              ? await backend.handleMonitoredWorkerIdle(handle, spec, ctx)
              : "hang";
          if (disposition === "wait_for_reset") {
            // Backends normally throw QuotaWaitForResetError here so runner park
            // machinery receives the reset timestamp and ledger event.
            throw new Error(
              "monitored worker idle disposition returned wait_for_reset without " +
                "raising the backend's quota park error",
            );
          }
          // Only a positive probe result may classify this as a live-pool hang.
          // Unknown/error/no-probe cases retain the ordinary fail-safe hang path.
          //
          // Reject the race with the hang error FIRST, then kill the tree. If we
          // kill-then-throw, the child signal-exit can settle before the throw and
          // win Promise.race as `killed`, swallowing HangWithLivePoolError (relay
          // would never see the hang). Kill is best-effort after the reject.
          const hangError =
            disposition === "hang_with_live_pool"
              ? new HangWithLivePoolError({
                  workerPid: handle.pid,
                  poolId: handle.poolId,
                  step: spec.id,
                })
              : new Error(`monitored worker idle hang: ${spec.id}`);
          const killPromise = killWorkerTree(handle, monitorDeps);
          try {
            throw hangError;
          } finally {
            await killPromise.catch(() => undefined);
          }
        }
        return await exitPromise;
      })();
      const race = await Promise.race([exitPromise, monitorPromise]);
      // Observe the race loser. If exit/kill won while handleMonitoredWorkerIdle
      // was still in flight, a late QuotaWaitForResetError (or other throw) must
      // be swallowed-with-log — never an unhandledRejection that can crash Node.
      if (race.kind === "exit" || race.kind === "killed") {
        monitorCancelled = true;
        void monitorPromise.then(
          () => undefined,
          (err: unknown) => {
            console.warn(
              `[orchestrator] monitored idle handler settled after child exit: ${
                err instanceof Error ? err.message : String(err)
              }`,
            );
          },
        );
      }
      // Quick-exit / race-won-by-exit: poll loop may never have observed growth.
      // One-shot re-read so first_output_at is not left null when bytes exist.
      // Stamp time ≈ process exit (poll-granularity semantics, not true TTFB).
      reconcileFirstOutputAt(handle, firstOutputBaseline, monitorDeps);
      // Always consult the result-sidecar mapper — even on signal exit. A worker
      // may have written a valid completed sidecar in the narrow window before
      // SIGTERM; skipping the mapper would fabricate failed and change dispatch
      // semantics (telemetry must not). Hang dispositions reject monitorPromise
      // (above) before kill settles, so they never reach this branch. Late
      // post-exit handler throws stay swallowed.
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
      // #686/#826: actionable worker-log relay tags become either resource
      // handoff signals or a decision-gate park. Malformed/absent tags are
      // ignored here.
      // #786: token extract uses the same log slice (GC happens later at terminal).
      try {
        const logText = readDispatchLogSlice(
          handle.logPath,
          handle.logStartOffset,
        );
        if (logText !== null) {
          const tag = tryParseActionableRelayTag(logText);
          if (tag !== undefined) {
            throw new SelfReportedRelayError(tag, spec.id, result.sessionId);
          }
        }
      } catch (err) {
        if (err instanceof SelfReportedRelayError) throw err;
        // Log read failures are non-fatal — fall through with the worker result.
      }
      // Final reconcile in case await path delayed past more log growth.
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
    const output: StepOutput =
      expectedKind === "coder"
        ? {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: result.escalation,
          }
        : expectedKind === "verify"
          ? {
              kind: "judge",
              status: "escalate",
              reason: result.escalation.reason,
              diagnosis: result.escalation.diagnosis,
              escalate: result.escalation,
            }
        : { kind: "reviewer", findings: [], findingsCount: 0, escalate: result.escalation };
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
    completionSignal: spec.completionSignal,
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
