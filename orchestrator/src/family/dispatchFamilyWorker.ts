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

import type {
  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSessionMode,
  WorkerSpec,
} from "../types.js";
import {
  cmrReviewLegs as activeCmrReviewLegs,
  modelForSlot,
  type ResolvedModelRoute,
} from "../modelRoutes.js";
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
  return {
    id: "S3",
    kind: "cmr",
    role: "reviewer",
    // The cmr skill fans out a Claude Agent leg + CLI legs → host pinned Claude
    // top-level (PRD #330 [J]).
    host: "claude",
    session,
    contextRetention: "clean",
    skill: "ak-cross-m-review",
    promptFile:
      pass === "completeness"
        ? "integrated_cmr_completeness.md"
        : "integrated_cmr_correctness.md",
    completionSignal: "CMR_STEP_COMPLETE",
    maxIter: 1,
    model:
      route?.slots[pass === "completeness" ? "cmrCompleteness" : "cmrCorrectness"] ??
      modelForSlot(pass === "completeness" ? "cmrCompleteness" : "cmrCorrectness"),
    cmrReviewLegs: route?.legCollections.cmrReview ?? activeCmrReviewLegs(),
    soul: "cmr",
    toolchain: [],
  };
}

/** Family-level coder-fix worker for blocking CMR findings (#550). */
export function familyCoderFixWorkerSpec(route?: ResolvedModelRoute): WorkerSpec {
  return {
    id: "S5",
    kind: "coder",
    role: "coder",
    host: "claude",
    session: "fresh",
    contextRetention: "retain",
    skill: "/tdd",
    promptFile: "coder_fix.md",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    model: route?.slots.coderFix ?? modelForSlot("coderFix"),
    soul: "coder",
    toolchain: IMAGE_TOOLCHAIN,
  };
}

/** The family-base ship/PR worker spec (止于 PR; invoke `gstack-ship`). */
export function familyShipWorkerSpec(route?: ResolvedModelRoute): WorkerSpec {
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
    // (runner worker specs use 5), NOT the cmr reviewer's single-pass 1 (#336 cmr r6).
    maxIter: 5,
    model: route?.slots.ship ?? modelForSlot("ship"),
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
  if (familyBackend.dispatchWorker !== undefined) {
    return familyBackend.dispatchWorker(spec, ctx, landing);
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

  // #596 skeleton: deterministic no-op stubs for the family review-loop workers
  // when the backend has no real implementation. Shared resolver (single-slice
  // + family + spy backends return the SAME stub verdicts).
  const skeletonResult = skeletonReviewLoopWorkerResult(spec.kind);
  if (skeletonResult !== undefined) {
    return skeletonResult;
  }

  throw new Error(
    `legacyDispatchFamilyWorker: unsupported family worker kind ${spec.kind}`,
  );
}
