/**
 * Family review-loop worker outcome seam (#596).
 *
 * Defines the typed payload shapes and compatibility results consumed by the
 * family S9 verify / S10 fixer / S12 landing agent outcomes plus the
 * host-deterministic S11 cleanup result.
 */

import type {
  CleanupResult,
  CollectorResult,
  LandingResult,
  FixerResult,
  OnlineReviewLandingSnapshot,
  StepOutput,
  VerifyResult,
  WorkerKind,
  WorkerResult,
} from "./types.js";

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

/** Deterministic collector evidence for explicit offline/test injection only. */
export function stubCollectorEvidence(
  overrides?: {
    readonly prUrl?: string;
    readonly headOid?: string;
    readonly [key: string]: unknown;
  },
): OnlineReviewLandingSnapshot {
  // Convenience defaults for fixtures that still want PR/head bookkeeping keys.
  // Production transport admits any object body — these keys are not required.
  return {
    ...overrides,
    prUrl: overrides?.prUrl ?? "pr://offline",
    headOid: overrides?.headOid ?? "offline-head",
  };
}

/** Deterministic collector verdict for explicit offline/test injection only. */
export function stubCollectorResult(
  evidence?: OnlineReviewLandingSnapshot,
): CollectorResult {
  return { kind: "collector", evidence: evidence ?? stubCollectorEvidence() };
}

/** Deterministic verify verdict for explicit offline/test injection only. */
export function stubVerifyResult(): VerifyResult {
  return { kind: "verify", status: "converged" };
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
    case "collector":
      return { kind: "completed", output: stubCollectorResult() };
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
