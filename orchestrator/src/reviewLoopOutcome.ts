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
