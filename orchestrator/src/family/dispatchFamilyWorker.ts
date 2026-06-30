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
import { modelForSlot } from "../modelRoutes.js";
import type {
  FamilyBackend,
  IntegratedCmrPass,
  IntegratedCmrResult,
  OpenFamilyPrResult,
} from "./types.js";

/**
 * The integrated-cmr family worker spec (#335 invoke `ak-cross-m-review`).
 *
 * ADR 0030 splits integrated cmr into ordered runner-dispatched pass workers:
 * completeness first, correctness second. This spec describes ONE such pass
 * worker, not the whole integrated gate:
 *   - `session: "fresh"` = start a NEW pass session (not a crash/escalate
 *     `resume`, which skips git-truthing). `verifyCmr` dispatches one fresh worker
 *     per pass and gates correctness on completeness.
 *   - `soul: "cmr"` = the pass worker is WRITE-capable (it may commit pass-local
 *     fixes on the family base), NOT the READ-ONLY per-slice reviewer soul.
 *   - `maxIter: 5` = the within-step Ralph iteration budget (StepSpec.maxIter
 *     semantics, same as the coder/ship workers), NOT the count of cmr fix rounds.
 *     `maxIter` is the sandbox iteration budget for this pass worker, not a
 *     runner-level cmr round counter. `verifyCmr` consumes only the terminal pass
 *     verdict and performs route/closure accounting.
 */
export function cmrWorkerSpec(
  session: WorkerSessionMode = "fresh",
  pass: IntegratedCmrPass = "correctness",
): WorkerSpec {
  return {
    id: "S2", // family cmr is a WRITE-capable pass worker before family S7 ship;
    //           ADR 0030 exposes the pass boundary via `cmrPass`, not new S3/S5/S6
    //           family step ids.
    kind: "cmr",
    role: "coder", // it WRITES (commits cross-slice fixes), not a read-only reviewer
    // The cmr skill fans out a Claude Agent leg + CLI legs → host pinned Claude
    // top-level (PRD #330 [J]).
    host: "claude",
    session,
    // The pass worker may retain context while producing its terminal pass verdict;
    // `verifyCmr` still owns the ADR 0030 pass boundary and pass ordering.
    contextRetention: "retain",
    skill: "ak-cross-m-review",
    promptFile:
      pass === "completeness"
        ? "integrated_cmr_completeness.md"
        : "integrated_cmr_correctness.md",
    completionSignal: "CMR_STEP_COMPLETE",
    maxIter: 5,
    model: modelForSlot(pass === "completeness" ? "cmrCompleteness" : "cmrCorrectness"),
    soul: "cmr",
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
    model: modelForSlot("ship"),
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
      ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
      ...(ctx.llmResolvedChildren !== undefined &&
      ctx.llmResolvedChildren.length > 0
        ? { llmResolvedChildren: ctx.llmResolvedChildren }
        : {}),
      ...(ctx.escalationAnswer !== undefined
        ? { escalationAnswer: ctx.escalationAnswer }
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
