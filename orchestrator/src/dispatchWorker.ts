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
 *   - {@link legacyDispatchWorker} — the #331 PREFACTOR thin wrapper: forwards a
 *     worker to the EXISTING backend methods (`runStep`/`resumeSession` for agent
 *     workers, `push` for the S7 ship worker) and wraps their returns into the
 *     discriminated {@link WorkerResult}. External behaviour is unchanged
 *     (regression green); the real worker dispatch (invoke `/tdd` / `/code-review` /
 *     `gstack-ship`) lands in #334/#336.
 *   - {@link workerResultToStep} — unwrap a `completed` {@link WorkerResult} back
 *     into the `{@link StepOutput} | {@link StepResult}` shape the existing runner
 *     control flow consumes, so the prefactor does not touch route()/validate().
 */

import { execFileSync, type ChildProcess } from "node:child_process";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";

import { offlineReviewLoopDispatchAdmissible } from "./evidenceAdmissibility.js";
import {
  FIX_FOCUS_LANDING_FILE,
  formatFixFocusMarkdown,
} from "./findingFamilies.js";
import { dispatchPostMergeCleanup } from "./postMergeCleanup.js";
import type { Sh } from "./familyDriver.js";
import {
  modelForSlot,
  routeSmokeFailure,
  type ResolvedModelRoute,
} from "./modelRoutes.js";
import {
  HangWithLivePoolError,
  SelfReportedRelayError,
  tryParseActionableRelayTag,
} from "./relayDispatch.js";
import { skeletonReviewLoopWorkerResult } from "./reviewLoopOutcome.js";
import {
  buildCollectStamp,
  buildDispatchStamp,
  classifyWorkerTerminal,
  ensureEnvironmentStamp,
  extractTokensFromLog,
  newLegId,
  readDispatchLogSlice,
  tryAppendTelemetryRecord,
} from "./telemetry.js";
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
  WorkerSpec,
} from "./types.js";

const FIX_FINDINGS_LANDING_FILE = ".orchestrator-fix-findings.json";
const FIX_FINDINGS_LEDGER_FILE = "fix-findings.json";
const ONLINE_REVIEW_LANDING_FILE = ".orchestrator-online-review.json";

/**
 * The wiki skill each worker kind invokes (ADR 0026):
 *   coder → `/tdd`, reviewer → `/code-review`, cmr → `ak-cross-m-review`,
 *   ship → `gstack-ship`, merge → none; review-loop: verify/fixer/cleanup/docRelease
 *   (stubs only in #596; real in #600/#603).
 *
 * #331 PREFACTOR: this is only the DECLARED routing on the spec (so #337's "coder
 * 手搓 TDD 不 invoke /tdd" regression assertion has a target). The legacy wrapper
 * does NOT actually invoke the skill yet — it forwards to the existing methods.
 */
const SKILL_FOR_KIND: Readonly<Record<WorkerKind, string | undefined>> = {
  coder: "/tdd",
  reviewer: "/code-review",
  cmr: "ak-cross-m-review",
  ship: "gstack-ship",
  merge: undefined,
  // TODO(#600/#603): real /verify skill + prompt (verify.md) lands later; skeleton only.
  verify: "/verify",
  // TODO(#600/#603): real /fixer skill + prompt (fixer.md) lands later; skeleton only.
  fixer: "/fixer",
  // TODO(#600/#603): real /cleanup skill + prompt (cleanup.md) lands later; skeleton only.
  cleanup: "/cleanup",
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
 * normal fix keeps git-truthing + maxIter, NOT the crash/escalate resume path).
 */
function retentionForKind(kind: WorkerKind): WorkerContextRetention {
  // Production workers (coder + post-review fixer) retain context across rounds;
  // review-like workers start each round clean.
  return kind === "coder" || kind === "fixer" ? "retain" : "clean";
}

function ensureGitExcluded(worktreePath: string, pattern: string): void {
  try {
    const excludePath = execFileSync(
      "git",
      ["-C", worktreePath, "rev-parse", "--git-path", "info/exclude"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
    ).trim();
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

function writeOnlineReviewLandingFile(
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
): (FixFindingsLandingFile & { cleanup: boolean }) | undefined {
  const needsLanding =
    (spec.kind === "verify" || spec.kind === "fixer") &&
    landing?.onlineReviewSnapshot !== undefined;
  if (!needsLanding) {
    return undefined;
  }
  if (ctx.worktree === undefined) {
    throw new Error(
      `${spec.kind} worker requires a worktree to mount the online review landing file`,
    );
  }
  if (!existsSync(ctx.worktree.path)) {
    throw new Error(
      `${spec.kind} worker online review landing worktree missing: ${ctx.worktree.path}`,
    );
  }

  const landingPath =
    ctx.stateDir !== undefined
      ? join(ctx.stateDir, "online-review-landing.json")
      : join(ctx.worktree.path, ONLINE_REVIEW_LANDING_FILE);
  try {
    if (ctx.stateDir !== undefined) {
      mkdirSync(ctx.stateDir, { recursive: true });
    } else {
      ensureGitExcluded(ctx.worktree.path, ONLINE_REVIEW_LANDING_FILE);
    }
  } catch (err) {
    throw new Error(
      `${spec.kind} worker failed to prepare online review landing directory: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
  try {
    writeFileSync(
      landingPath,
      `${JSON.stringify(
        {
          onlineReviewSnapshot: landing.onlineReviewSnapshot,
          shipDelivery: landing.shipDelivery,
          onlineReviewRound: landing.onlineReviewRound ?? ctx.onlineReviewRound,
          fixMarkedFindingIdentityKeys: landing.fixMarkedFindingIdentityKeys ?? [],
          fixMarkedFindingThreads: landing.fixMarkedFindingThreads ?? [],
          ...(landing.priorRoundFindings !== undefined &&
          landing.priorRoundFindings.length > 0
            ? { priorRoundFindings: landing.priorRoundFindings }
            : {}),
        },
        null,
        2,
      )}\n`,
      "utf8",
    );
  } catch (err) {
    throw new Error(
      `${spec.kind} worker failed to write online review landing file: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
  return {
    path: landingPath,
    sandboxPath: ONLINE_REVIEW_LANDING_FILE,
    cleanup: ctx.stateDir === undefined,
  };
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
  const needsFindingsLanding =
    (spec.id === "S5" && spec.kind === "coder") ||
    (spec.id === "S6" && spec.kind === "reviewer") ||
    ctx.escalationAnswer !== undefined;
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
  writeFileSync(
    landingPath,
    `${JSON.stringify(
      {
        // Rich finding CONTENT comes from the SEPARATE landing payload (信封宪法,
        // ADR 0062) — never from the runner's thin DispatchContext.
        blockingFindings: landing?.blockingFindings ?? [],
        blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys ?? [],
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
 * threading a `resumeSessionId` (the crash/escalate-resume path); `"fresh"`
 * otherwise (the normal S2/S5 path). The default is `"fresh"` — a worker is never
 * marked `resume` by work type alone (ADR 0026; codex cmr R3 finding).
 */
export function stepSpecToWorkerSpec(
  spec: StepSpec,
  session: WorkerSessionMode = "fresh",
): WorkerSpec {
  const kind = workerKindForRole(spec.role);
  return {
    id: spec.id,
    kind,
    role: spec.role,
    // v0.1 single image, Claude host (its sub Agents do the cross-model fan-out).
    host: "claude",
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

/**
 * Build the S7 SHIP {@link WorkerSpec} (ADR 0026: S7 is a ship worker invoking
 * `gstack-ship`, no longer an inline `git push`). #331 prefactor: the legacy
 * wrapper forwards it to `backend.push`; #336 makes it invoke `gstack-ship`.
 */
export const SHIP_PROMPT_FILE = "ship.md";

export function shipWorkerSpec(route?: ResolvedModelRoute): WorkerSpec {
  return {
    id: "S7",
    kind: "ship",
    role: "coder",
    host: "claude",
    session: "fresh",
    contextRetention: "clean",
    skill: SKILL_FOR_KIND.ship,
    promptFile: SHIP_PROMPT_FILE,
    completionSignal: "SHIP_STEP_COMPLETE",
    // A WRITE/coder ship worker must self-rerun gstack-ship's rerun-able failures
    // (ship.md: "rerun it yourself") → an iterative budget like coder/fix (runner
    // runner worker specs use 5), NOT a single-pass reviewer's 1 (#336 cmr r6). The completion
    // signal stops the loop early on a clean ship; the <ship> parser reads the LAST tag.
    maxIter: 5,
    model: route?.slots.ship ?? modelForSlot("ship"),
    soul: "coder",
    toolchain: [],
  };
}

// Prompt status: verify.md / fixer.md real paths shipped in #600;
// docRelease.md real path shipped in #735; cleanup real host path remains #603.
export const VERIFY_PROMPT_FILE = "verify.md";
export const FIXER_PROMPT_FILE = "fixer.md";
export const CLEANUP_PROMPT_FILE = "cleanup.md";
export const DOCRELEASE_PROMPT_FILE = "docRelease.md";

/** S9 online-review / PR-check worker spec (#600 real prompt). */
export function verifyWorkerSpec(route?: ResolvedModelRoute): WorkerSpec {
  return {
    id: "S9",
    kind: "verify",
    role: "verify",
    host: "claude",
    session: "fresh",
    contextRetention: "clean",
    skill: SKILL_FOR_KIND.verify,
    promptFile: VERIFY_PROMPT_FILE,
    completionSignal: "VERIFY_STEP_COMPLETE",
    maxIter: 1,
    model: route?.slots.verify ?? modelForSlot("verify"),
    soul: "verify",
    toolchain: [],
  };
}

/** S10 post-review fixer worker spec (#600 real prompt). */
export function fixerWorkerSpec(route?: ResolvedModelRoute): WorkerSpec {
  return {
    id: "S10",
    kind: "fixer",
    role: "fixer",
    host: "claude",
    session: "fresh",
    contextRetention: "retain",
    skill: SKILL_FOR_KIND.fixer,
    promptFile: FIXER_PROMPT_FILE,
    completionSignal: "FIXER_STEP_COMPLETE",
    maxIter: 5,
    model: route?.slots.fixer ?? modelForSlot("fixer"),
    soul: "fixer",
    toolchain: [],
  };
}

/** S11 cleanup worker spec (#596 skeleton; real host path is #603). */
// TODO(#603): cleanup skill/prompt wiring is still skeleton here.
export function cleanupWorkerSpec(route?: ResolvedModelRoute): WorkerSpec {
  return {
    id: "S11",
    kind: "cleanup",
    role: "cleanup",
    host: "claude",
    session: "fresh",
    contextRetention: "clean",
    skill: SKILL_FOR_KIND.cleanup,
    promptFile: CLEANUP_PROMPT_FILE,
    completionSignal: "CLEANUP_STEP_COMPLETE",
    maxIter: 1,
    model: route?.slots.cleanup ?? modelForSlot("cleanup"),
    soul: "cleanup",
    toolchain: [],
  };
}

/**
 * S12 文档发布 worker (#735): invoke `/gstack-document-release` in a spawned /
 * non-interactive session. Success (including 文档发布空跑) → `released:true`;
 * skill crash / hang / explicit fail / required push fail → not released.
 * Offline/test may still synthesize via the offline hatch only.
 */
export function docReleaseWorkerSpec(route?: ResolvedModelRoute): WorkerSpec {
  return {
    id: "S12",
    kind: "docRelease",
    role: "docRelease",
    host: "claude",
    session: "fresh",
    contextRetention: "clean",
    skill: SKILL_FOR_KIND.docRelease,
    promptFile: DOCRELEASE_PROMPT_FILE,
    completionSignal: "DOCRELEASE_STEP_COMPLETE",
    maxIter: 1,
    model: route?.slots.docRelease ?? modelForSlot("docRelease"),
    soul: "docRelease",
    toolchain: [],
  };
}

/**
 * The #331 PREFACTOR thin wrapper: forward a worker to the EXISTING backend
 * methods and wrap the return into a {@link WorkerResult}. Behaviour-preserving.
 *
 *   - coder (the S2 build worker): when `ctx.resumeSessionId` is set the worker is
 *     dispatched via `backend.resumeSession` (the escalate/crash-resume path), else
 *     via `backend.runStep`. The returned `StepOutput | StepResult` is wrapped as
 *     `completed` (carrying the real per-step `sessionId` when surfaced).
 *   - ship (S7): forward to `backend.push` and wrap as a `completed` ShipResult.
 *
 * #331 always yields `completed` — the `failed`/`malformed`/`escalated` cases are
 * wired into the union now but produced by the real workers in later slices.
 */
export async function legacyDispatchWorker(
  backend: Backend,
  spec: WorkerSpec,
  ctx: DispatchContext,
  landing?: WorkerLandingPayload,
): Promise<WorkerResult> {
  if (spec.kind === "ship") {
    if (ctx.worktree === undefined) {
      throw new Error("legacyDispatchWorker: ship worker requires a worktree");
    }
    await backend.push(ctx.worktree);
    return {
      kind: "completed",
      output: { kind: "ship", branch: ctx.worktree.branch, status: "pushed" },
    };
  }

  // S11 post-merge cleanup (#603): deterministic verify+act when landing carries
  // pr_merged; offline/test without landing keeps the skeleton stub.
  if (spec.kind === "cleanup") {
    if (landing?.cleanupDispatch !== undefined) {
      const ghSh: Sh = (file, args) =>
        execFileSync(file, args, {
          encoding: "utf8",
          stdio: ["ignore", "pipe", "pipe"],
        }).trim();
      try {
        const output = dispatchPostMergeCleanup(landing, ctx, ghSh);
        return { kind: "completed", output };
      } catch (err) {
        return {
          kind: "failed",
          reason: err instanceof Error ? err.message : String(err),
        };
      }
    }
    const stub = skeletonReviewLoopWorkerResult(spec.kind);
    if (stub !== undefined) {
      return stub;
    }
  }

  // #596 skeleton: explicit offline/test contexts only when the backend has no
  // `dispatchWorker` seam (#600 r5 — mirror family legacy gate; live paths must
  // fail closed instead of synthesizing convergence).
  // #735: docRelease joins verify/fixer here — no unconditional forever-stub.
  const skeletonResult = skeletonReviewLoopWorkerResult(spec.kind);
  if (skeletonResult !== undefined && backend.dispatchWorker === undefined) {
    if (offlineReviewLoopDispatchAdmissible(ctx)) {
      return skeletonResult;
    }
    return {
      kind: "failed",
      reason:
        `${spec.kind} worker unavailable: no dispatchWorker seam and ` +
        `offline skeleton synthesis inadmissible for PR ${ctx.prUrl ?? "(missing)"}`,
    };
  }

  // FAIL-CLOSED on the worker kind (online review r1, 3 bots): only agent +
  // review-loop workers belong on the `runStep`/`resumeSession` path below.
  // #735: docRelease is a real agent worker (invoke /gstack-document-release).
  // cleanup stays deterministic (landing) or offline-stub above — not runStep.
  const runStepKinds = new Set<WorkerKind>([
    "coder",
    "reviewer",
    "verify",
    "fixer",
    "docRelease",
  ]);
  if (!runStepKinds.has(spec.kind)) {
    throw new Error(
      `legacyDispatchWorker: worker kind '${spec.kind}' (${spec.id}) has no legacy ` +
        `dispatch path — only coder/reviewer/verify/fixer/docRelease (agent), ship, ` +
        `and the #603 cleanup path are forwarded. A cmr/merge worker must go ` +
        `through a backend implementing the unified dispatchWorker seam.`,
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
  let onlineReviewLanding;
  try {
    onlineReviewLanding = writeOnlineReviewLandingFile(spec, ctx, landing);
  } catch (err) {
    if (fixFindingsLanding?.cleanup) {
      rmSync(fixFindingsLanding.path, { force: true });
    }
    if (fixFocusLanding?.cleanup) {
      rmSync(fixFocusLanding.path, { force: true });
    }
    return {
      kind: "failed",
      reason: err instanceof Error ? err.message : String(err),
    };
  }
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
  const onlineReviewOptions =
    onlineReviewLanding !== undefined
      ? {
          onlineReviewLanding: {
            path: onlineReviewLanding.path,
            sandboxPath: onlineReviewLanding.sandboxPath,
          },
        }
      : undefined;
  const outcomeLanding = writeWorkerOutcomeLandingFile(spec, ctx);
  const runOptions =
    fixFindingsOptions !== undefined ||
    fixFocusOptions !== undefined ||
    onlineReviewOptions !== undefined ||
    outcomeLanding !== undefined ||
    ctx.billingPool !== undefined ||
    ctx.relayFocusPath !== undefined
      ? {
          ...(fixFindingsOptions ?? {}),
          ...(fixFocusOptions ?? {}),
          ...(onlineReviewOptions ?? {}),
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
    if (fixFocusLanding?.cleanup) {
      rmSync(fixFocusLanding.path, { force: true });
    }
    if (onlineReviewLanding?.cleanup) {
      rmSync(onlineReviewLanding.path, { force: true });
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
const DEFAULT_MONITOR_POLL_INTERVAL_MS = 250;

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
 * S2/S3/S5/S6/S7/S9–S12 take this monitored branch in production.
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
  const ledgerDir = ctx.stateDir;
  const legId = newLegId();
  // model family for token extract — pure stamp, not the durable dispatch row.
  // Durable dispatched_at comes from handle.dispatchedAt after real spawn.
  const modelFamily = buildDispatchStamp({
    legId,
    spec,
    ctx,
    dispatchedAt: new Date().toISOString(),
  }).model.family;
  let firstOutputAt: string | null = null;
  let logPath: string | null = null;
  let logStartOffset: number | undefined;
  let collectStamped = false;

  ensureEnvironmentStamp(ledgerDir, ctx);

  const stampCollect = (
    outcome:
      | { readonly kind: "result"; readonly result: WorkerResult }
      | { readonly kind: "thrown"; readonly error: unknown },
  ): void => {
    if (collectStamped) return;
    collectStamped = true;
    const logText = readDispatchLogSlice(
      logPath ?? undefined,
      logStartOffset,
    );
    const classified = classifyWorkerTerminal(outcome);
    tryAppendTelemetryRecord(
      ledgerDir,
      buildCollectStamp({
        legId,
        completedAt: new Date().toISOString(),
        terminal: classified.terminal,
        errorCategory: classified.errorCategory,
        errorMessage: classified.errorMessage,
        tokens:
          logText !== null
            ? extractTokensFromLog(logText, modelFamily)
            : null,
        sessionId: classified.sessionId,
        logPath,
        firstOutputAt,
      }),
    );
  };

  try {
    const cliSpec = backend.resolveCliMonitorDispatch?.(spec, ctx, landing);

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
      tryAppendTelemetryRecord(
        ledgerDir,
        buildDispatchStamp({
          legId,
          spec,
          ctx,
          dispatchedAt: handle.dispatchedAt,
          poolId: cliSpec.poolId,
        }),
      );
      const exitPromise = waitForChildExit(child);
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
        opts?.idleThresholdMs ?? DEFAULT_MONITOR_IDLE_THRESHOLD_MS;
      const pollIntervalMs =
        opts?.pollIntervalMs ?? DEFAULT_MONITOR_POLL_INTERVAL_MS;
      const initialActivity = readLogActivity(handle, monitorDeps);
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
              // #786 first_output_at: first log growth after the spawn marker.
              if (
                firstOutputAt === null &&
                current.sizeBytes > previous.sizeBytes
              ) {
                firstOutputAt = new Date().toISOString();
              }
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
      // Signal-killed legs must land a `killed` collect row — do not silently
      // feed null exitCode into awaitMonitoredCliWorker and drop the terminal.
      // Hang dispositions reject monitorPromise (above) before kill settles, so
      // they never reach this branch. Late post-exit handler throws stay swallowed.
      if (race.kind === "killed") {
        const result: WorkerResult = {
          kind: "failed",
          reason: `CLI worker ${spec.id} killed by signal ${race.signal}`,
        };
        stampCollect({ kind: "result", result });
        return { result, monitorHandle: handle };
      }
      const exitCode = race.exitCode;
      if (backend.awaitMonitoredCliWorker === undefined) {
        const result: WorkerResult = {
          kind: "failed",
          reason:
            `CLI worker ${spec.id} finished (exit ${exitCode}) but backend has ` +
            `no awaitMonitoredCliWorker to map the process into a WorkerResult`,
        };
        stampCollect({ kind: "result", result });
        return { result, monitorHandle: handle };
      }
      const result = await backend.awaitMonitoredCliWorker(
        handle,
        exitCode,
        spec,
        ctx,
        landing,
      );
      // #686: self-reported blocked / phase_complete in the worker log → resource
      // relay (preserve drift). Malformed/absent tags are ignored here.
      // #786: token extract uses the same log slice (GC happens later at terminal).
      try {
        const logText = readDispatchLogSlice(
          handle.logPath,
          handle.logStartOffset,
        );
        if (logText !== null) {
          const tag = tryParseActionableRelayTag(logText);
          if (tag !== undefined) {
            throw new SelfReportedRelayError(tag, spec.id);
          }
        }
      } catch (err) {
        if (err instanceof SelfReportedRelayError) throw err;
        // Log read failures are non-fatal — fall through with the worker result.
      }
      stampCollect({ kind: "result", result });
      return { result, monitorHandle: handle };
    }
    // Container / legacy path: stamp dispatch at the moment we hand off to the
    // backend (no monitor handle.dispatchedAt available).
    tryAppendTelemetryRecord(
      ledgerDir,
      buildDispatchStamp({
        legId,
        spec,
        ctx,
        dispatchedAt: new Date().toISOString(),
        poolId:
          ctx.billingPool !== undefined ? ctx.billingPool : undefined,
      }),
    );
    const result = await dispatchWorker(backend, spec, ctx, landing);
    stampCollect({ kind: "result", result });
    return { result };
  } catch (err) {
    stampCollect({ kind: "thrown", error: err });
    throw err;
  }
}

/**
 * Unwrap a `completed` {@link WorkerResult} into the `StepOutput | StepResult`
 * shape the existing runner control flow (#256 normalisation, validate, route)
 * consumes for an AGENT step — so the prefactor leaves route()/validate()
 * untouched. A non-`completed` result is mapped to an escalate/garbage StepOutput
 * the runner's existing guards already handle:
 *   - `escalated` → a coder/reviewer output carrying the escalate (route() takes
 *     the global escalate edge → S8(escalate)).
 *   - `failed` / `malformed` → returns `{ unwrapped: undefined, reason }`: the
 *     runner maps a non-completed result to S8(error) carrying `reason`. The
 *     output is `undefined` so the runner's `isValidStepOutput` guard rejects it
 *     uniformly. (#331's legacy wrapper never produces these; #334's real workers
 *     do.)
 *
 * Returns `{ unwrapped, reason? }`: `unwrapped` is the `StepOutput | StepResult`
 * for the existing flow (`undefined` only for failed/malformed); `reason` is set
 * for failed/malformed so the runner can surface it in the error package.
 */
export function workerResultToStep(
  result: WorkerResult,
  expectedKind: "coder" | "reviewer",
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
        : { kind: "reviewer", findings: [], escalate: result.escalation };
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
  // failed / malformed → undefined output (the guard rejects it → S8(error)).
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
