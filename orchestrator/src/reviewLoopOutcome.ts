/**
 * Review-loop worker outcome seam (#596 skeleton).
 *
 * The single-slice runner gains four new runner-visible steps after S7 ship:
 *   S9 verify → S10 fixer → S11 cleanup → S12 docRelease → S8 success
 *
 * This slice is a SKELETON: the real bot-polling / online-review logic lives in
 * later issues. Here we only define the typed payload shapes, deterministic stub
 * verdicts for the legacy/no-op path, and fail-closed validators so route() can
 * reject an off-contract output instead of silently advancing.
 */

import type {
  CleanupResult,
  DocReleaseResult,
  FixerResult,
  StepOutput,
  VerifyResult,
  WorkerKind,
  WorkerResult,
} from "./types.js";

export function isValidVerifyResult(
  o: StepOutput | undefined,
): o is VerifyResult {
  if (o == null || typeof o !== "object") return false;
  const obj = o as unknown as Record<string, unknown>;
  return obj.kind === "verify" && typeof obj.converged === "boolean";
}

export function isValidFixerResult(o: StepOutput | undefined): o is FixerResult {
  if (o == null || typeof o !== "object") return false;
  const obj = o as unknown as Record<string, unknown>;
  return obj.kind === "fixer" && typeof obj.committed === "boolean";
}

export function isValidCleanupResult(
  o: StepOutput | undefined,
): o is CleanupResult {
  if (o == null || typeof o !== "object") return false;
  const obj = o as unknown as Record<string, unknown>;
  return obj.kind === "cleanup" && typeof obj.ok === "boolean";
}

export function isValidDocReleaseResult(
  o: StepOutput | undefined,
): o is DocReleaseResult {
  if (o == null || typeof o !== "object") return false;
  const obj = o as unknown as Record<string, unknown>;
  return obj.kind === "docRelease" && typeof obj.released === "boolean";
}

/** Deterministic skeleton verdict used by the legacy dispatch path for S9. */
export function stubVerifyResult(): VerifyResult {
  return { kind: "verify", converged: true };
}

/** Deterministic skeleton verdict used by the legacy dispatch path for S10. */
export function stubFixerResult(): FixerResult {
  return { kind: "fixer", committed: true };
}

/** Deterministic skeleton verdict used by the legacy dispatch path for S11. */
export function stubCleanupResult(): CleanupResult {
  return { kind: "cleanup", ok: true };
}

/** Deterministic skeleton verdict used by the legacy dispatch path for S12. */
export function stubDocReleaseResult(): DocReleaseResult {
  return { kind: "docRelease", released: true };
}

/**
 * The deterministic `completed` WorkerResult the #596 skeleton returns for a
 * review-loop kind (verify/fixer/cleanup/docRelease) when no real worker is
 * wired. Returns `undefined` for any other kind, so callers (the legacy
 * dispatchers + test/family spy backends that implement the unified seam) can
 * fall through to their own handling. The single-slice and family paths share
 * the SAME stub verdicts (#596: "single-slice and family paths share one kind
 * set"); real bot-polling logic lands in later slices and will override these
 * by handling the kind before calling this helper.
 */
export function skeletonReviewLoopWorkerResult(
  kind: WorkerKind,
): WorkerResult | undefined {
  switch (kind) {
    case "verify":
      return { kind: "completed", output: stubVerifyResult() };
    case "fixer":
      return { kind: "completed", output: stubFixerResult() };
    case "cleanup":
      return { kind: "completed", output: stubCleanupResult() };
    case "docRelease":
      return { kind: "completed", output: stubDocReleaseResult() };
    default:
      return undefined;
  }
}
