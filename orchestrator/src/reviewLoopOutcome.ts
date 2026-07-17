/**
 * Family review-loop worker outcome seam (#596).
 *
 * Defines the typed payload shapes and compatibility results consumed by the
 * family S9 verify / S10 fixer / S12 landing agent outcomes plus the
 * host-deterministic S11 cleanup result.
 */

import type {
  CleanupResult,
  LandingResult,
  FixerResult,
  StepOutput,
  VerifyResult,
  WorkerKind,
  WorkerResult,
} from "./types.js";

/** Every well-shaped fixer envelope returns to fresh S9 verification. */
export function fixerProceedsToVerify(_output: FixerResult): boolean {
  return true;
}

/**
 * Optional fix SHA from the fixer envelope. A no-fix envelope has no SHA and
 * proceeds through the verify findings channel.
 */
export function fixerEnvelopeFixCommitSha(output: FixerResult): string | undefined {
  return output.fixCommitSha;
}

/** Whether the fixer envelope carries a commit that permits commit side effects. */
export function fixerHasFixCommit(output: FixerResult): boolean {
  const fixCommitSha = fixerEnvelopeFixCommitSha(output);
  return fixCommitSha !== undefined && fixCommitSha.length > 0;
}

export function isValidCleanupResult(
  o: StepOutput | undefined,
): o is CleanupResult {
  if (o == null || typeof o !== "object") return false;
  const obj = o as unknown as Record<string, unknown>;
  if (obj.kind !== "cleanup") return false;
  if (typeof obj.terminal !== "boolean" || typeof obj.ok !== "boolean") {
    return false;
  }
  return !(obj.terminal === false && obj.ok === true);
}

/** Deterministic verify verdict for explicit offline/test injection only. */
export function stubVerifyResult(): VerifyResult {
  return { kind: "verify", converged: true };
}

/** Deterministic fixer verdict for explicit offline/test injection only. */
export function stubFixerResult(): FixerResult {
  return { kind: "fixer", committed: true, fixCommitSha: "stub-fix-sha" };
}

/** Deterministic host-cleanup result used by explicit offline/test paths. */
export function stubCleanupResult(): CleanupResult {
  return {
    kind: "cleanup",
    terminal: true,
    ok: true,
    branchOutcome: "already_gone",
  };
}

/**
 * Deterministic family offline/test skeleton for S12 文档发布.
 * Live paths must not use this unconditionally (#735) — only the offline hatch.
 */
export function stubLandingResult(): LandingResult {
  return { kind: "landing", released: true };
}

/**
 * Explicit offline/test injection for review-loop workers. Production callers
 * must pass their offline-admissibility gate before invoking this helper.
 */
export function skeletonReviewLoopWorkerResult(
  kind: WorkerKind,
): WorkerResult | undefined {
  switch (kind) {
    case "verify":
      return { kind: "completed", output: stubVerifyResult() };
    case "fixer":
      return { kind: "completed", output: stubFixerResult() };
    case "landing":
      return { kind: "completed", output: stubLandingResult() };
    default:
      return undefined;
  }
}
