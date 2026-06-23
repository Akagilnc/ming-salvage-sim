/**
 * The unified worker-dispatch seam at the FAMILY layer (ADR 0026 / PRD #330,
 * #331) — parallel to the single-slice `dispatchWorker` (../dispatchWorker.ts).
 *
 * The family-LEVEL worker steps — the integrated cross-model cmr over the merged
 * family base, and the family-base ship/PR — are dispatched through ONE seam
 * instead of the per-method `runIntegratedCmr` / `openFamilyPr`.
 *
 *   - {@link cmrWorkerSpec} / {@link familyShipWorkerSpec} — the declarative
 *     {@link WorkerSpec}s for the two family workers.
 *   - {@link dispatchFamilyWorker} — the free function the verify-cmr hook calls.
 *     It uses `familyBackend.dispatchWorker` when implemented, else forwards to the
 *     legacy `runIntegratedCmr` / `openFamilyPr` (#331 prefactor — behaviour
 *     unchanged). The real container cmr worker lands in #335.
 *
 * NOTE the DispatchContext for a family worker carries `familyBase` (the caller
 * has only the base string, no single-slice worktree path — PRD #330 R2);
 * `worktree` is optional / backend-inferred. The WorkerResult is the same
 * discriminated union: a cmr `red` verdict is `completed` (with a CmrResult
 * payload), NOT `failed`.
 */

import type {
  DispatchContext,
  WorkerResult,
  WorkerSessionMode,
  WorkerSpec,
} from "../types.js";
import type {
  FamilyBackend,
  FamilyCoderFixResult,
  IntegratedCmrResult,
  OpenFamilyPrResult,
} from "./types.js";

/**
 * The integrated-cmr family worker spec (#335 invoke `ak-cross-m-review`).
 *
 * `session` is ALWAYS `fresh` — the cmr reviewer dispatches FRESH every round (ADR
 * 0026 line 20: 评审类每轮 fresh, cross-model 独立性; the `resumeSession` path is
 * crash/escalate-ONLY, skipping git-truthing). CONTINUITY across rounds is the PRIOR
 * round's findings passed as DATA on {@link DispatchContext.priorFindings} — an
 * EXTRA confirm-resolved task, NOT a narrowed scope (the worker re-reviews the WHOLE
 * diff fresh each round; the runner never counts rounds). The `session` param is
 * retained for shape parity but the verify-cmr scheduler always passes `fresh`.
 */
export function cmrWorkerSpec(session: WorkerSessionMode = "fresh"): WorkerSpec {
  return {
    id: "S6", // the family integrated cmr maps to the review step kind
    kind: "cmr",
    role: "reviewer",
    // The cmr skill fans out a Claude Agent leg + CLI legs → host pinned Claude
    // top-level (PRD #330 [J]).
    host: "claude",
    session,
    // Review worker: clean eyes each round (cross-model independence) — ADR 0026.
    contextRetention: "clean",
    skill: "ak-cross-m-review",
    promptFile: "integrated_cmr.md",
    completionSignal: "CMR_STEP_COMPLETE",
    maxIter: 1,
    model: "opus",
    soul: "READ-ONLY",
    toolchain: [],
  };
}

/**
 * The family integrated-cmr FIX worker spec (wiki Step 6 fix loop). Dispatched by
 * the verify-cmr hook when the integrated cmr returns NOT-converged: it fixes the
 * cross-slice findings ON THE FAMILY BASE (a new commit) by invoking `/tdd`
 * (+ `/diagnosing-bugs`) under the `coder` soul — the runner stays a pure
 * scheduler. RETAIN context across rounds (a coder接得住 the prior round), iterate
 * budget like the per-slice S5 coder_fix (5).
 *
 * `session` is ALWAYS `fresh` — the coder-fix worker dispatches FRESH every round
 * (ADR 0026 invariant: a normal fix keeps git-truthing + within-step maxIter, NOT
 * the `resumeSession` crash/escalate path). It接得住 the prior round via DATA: the
 * cmr's non-convergence reason on {@link DispatchContext.cmrReason} (its fix focus),
 * NOT a resumed session. The `session` param is retained for shape parity but the
 * verify-cmr scheduler always passes `fresh`.
 */
export function familyCoderFixWorkerSpec(session: WorkerSessionMode = "fresh"): WorkerSpec {
  return {
    id: "S5", // mirrors the per-slice S5 coder_fix step kind
    kind: "coder",
    role: "coder",
    host: "claude",
    session,
    contextRetention: "retain",
    skill: "tdd",
    promptFile: "family_coder_fix.md",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    model: "sonnet",
    soul: "coder",
    toolchain: [],
  };
}

/** The family-base ship/PR worker spec (止于 PR; invoke `gstack-ship`). */
export function familyShipWorkerSpec(): WorkerSpec {
  return {
    id: "S7",
    kind: "ship",
    role: "coder",
    host: "claude",
    session: "fresh",
    contextRetention: "clean",
    skill: "gstack-ship",
    promptFile: "family_ship.md",
    completionSignal: "SHIP_STEP_COMPLETE",
    // A WRITE/coder ship worker must self-rerun gstack-ship's rerun-able failures
    // (family_ship.md: "rerun it yourself") → an iterative budget like coder/fix
    // (runner STEP_SPECS use 5), NOT the cmr reviewer's single-pass 1 (#336 cmr r6).
    maxIter: 5,
    model: "sonnet",
    soul: "coder",
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
 *   - family ship → `completed` with a {@link ShipResult} payload.
 */
export async function dispatchFamilyWorker(
  familyBackend: FamilyBackend,
  spec: WorkerSpec,
  ctx: DispatchContext,
): Promise<WorkerResult> {
  if (familyBackend.dispatchWorker !== undefined) {
    return familyBackend.dispatchWorker(spec, ctx);
  }
  return legacyDispatchFamilyWorker(familyBackend, spec, ctx);
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
      ...(ctx.llmResolvedChildren !== undefined &&
      ctx.llmResolvedChildren.length > 0
        ? { llmResolvedChildren: ctx.llmResolvedChildren }
        : {}),
    });
    // A `red` (non-converged) verdict is `completed` with payload — NOT `failed`
    // (PRD #330 R2). The verify-cmr hook reads `converged` off the payload.
    return {
      kind: "completed",
      output: {
        kind: "cmr",
        converged: cmr.converged,
        ...(cmr.reason !== undefined ? { reason: cmr.reason } : {}),
      },
    };
  }

  if (spec.kind === "coder") {
    // The family integrated-cmr fix worker (wiki Step 6 fix loop). Forwards to the
    // legacy per-method `runFamilyCoderFix` seam. The hook only dispatches this
    // after first checking the capability exists (verifyCmr.ts), so a missing
    // method here is a wiring fault — throw loud rather than fabricate a fix.
    if (familyBackend.runFamilyCoderFix === undefined) {
      throw new Error(
        "legacyDispatchFamilyWorker: backend has no runFamilyCoderFix capability",
      );
    }
    if (ctx.cmrReason === undefined) {
      throw new Error(
        "legacyDispatchFamilyWorker: a family coder-fix worker requires ctx.cmrReason",
      );
    }
    const fix: FamilyCoderFixResult = await familyBackend.runFamilyCoderFix({
      familyBase,
      reason: ctx.cmrReason,
    });
    // A model-stuck fix (the finding conflicts with the spec / a design gap) is the
    // WorkerResult-level `escalated` case (PRD #330 R2) — NOT a `completed` coder
    // payload. The hook reads this to escalate续跑 rather than re-run the cmr.
    if (fix.escalate !== undefined) {
      return { kind: "escalated", escalation: fix.escalate };
    }
    return {
      kind: "completed",
      output: {
        kind: "coder",
        committed: fix.committed,
        commitsAdded: fix.commitsAdded,
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
    return {
      kind: "completed",
      output: { kind: "ship", branch: familyBase, pr: pr.url, status: "pr_opened" },
    };
  }

  throw new Error(
    `legacyDispatchFamilyWorker: unsupported family worker kind ${spec.kind}`,
  );
}
