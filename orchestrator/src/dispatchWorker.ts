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

import { execFileSync } from "node:child_process";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";

import { modelForSlot, type ResolvedModelRoute } from "./modelRoutes.js";
import type {
  Backend,
  DispatchContext,
  FixFindingsLandingFile,
  StepOutput,
  StepResult,
  StepSpec,
  WorkerContextRetention,
  WorkerKind,
  WorkerResult,
  WorkerSessionMode,
  WorkerSpec,
} from "./types.js";

const FIX_FINDINGS_LANDING_FILE = ".orchestrator-fix-findings.json";
const FIX_FINDINGS_LEDGER_FILE = "fix-findings.json";

/**
 * The wiki skill each worker kind invokes (ADR 0026):
 *   coder/fix → `/tdd`, reviewer → `/code-review`, cmr → `ak-cross-m-review`,
 *   ship → `gstack-ship`, merge → none (may use no skill — US#9).
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
};

/**
 * Map a {@link StepSpec.role} to its {@link WorkerKind} for the agent steps.
 * S2/S5 coder → `coder`; S3/S6 reviewer → `reviewer`. (Ship/cmr/merge are built
 * directly, not from a role StepSpec.)
 */
function workerKindForRole(role: StepSpec["role"]): WorkerKind {
  return role === "coder" ? "coder" : "reviewer";
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
  return kind === "coder" ? "retain" : "clean";
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

function writeFixFindingsLandingFile(
  spec: WorkerSpec,
  ctx: DispatchContext,
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
        blockingFindings: ctx.blockingFindings ?? [],
        blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys ?? [],
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

  // FAIL-CLOSED on the worker kind (online review r1, 3 bots): only the legacy
  // AGENT workers (coder/reviewer) belong on the `runStep`/`resumeSession` path
  // below. `cmr`/`merge` are family-only worker kinds with NO legacy backend
  // method — if such a spec reached this public seam it would be silently
  // mis-dispatched as a coder/reviewer StepSpec (workerSpecToStepSpec drops
  // kind/skill, so a cmr review would run as a plain reviewer step). Reject it
  // explicitly rather than coerce. (`ship` is handled above.)
  if (spec.kind !== "coder" && spec.kind !== "reviewer") {
    throw new Error(
      `legacyDispatchWorker: worker kind '${spec.kind}' (${spec.id}) has no legacy ` +
        `dispatch path — only coder/reviewer (agent) and ship are forwarded. A ` +
        `cmr/merge worker must go through a backend implementing the unified ` +
        `dispatchWorker seam.`,
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
  const fixFindingsLanding = writeFixFindingsLandingFile(spec, ctx);
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
    fixFindingsOptions !== undefined || outcomeLanding !== undefined
      ? {
          ...(fixFindingsOptions ?? {}),
          ...(outcomeLanding !== undefined ? { outcomeLanding } : {}),
        }
      : undefined;
  try {
    if (ctx.resumeSessionId !== undefined) {
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
): Promise<WorkerResult> {
  if (backend.dispatchWorker !== undefined) {
    return backend.dispatchWorker(spec, ctx);
  }
  return legacyDispatchWorker(backend, spec, ctx);
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
