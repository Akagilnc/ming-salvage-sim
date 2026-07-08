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

import { isValidGithubIssueUrl } from "./onlineReviewSideEffects.js";
import type {
  CleanupResult,
  DocReleaseResult,
  FixerResult,
  StepOutput,
  VerifyResult,
  WorkerKind,
  WorkerResult,
} from "./types.js";

function isStringArray(value: unknown): value is ReadonlyArray<string> {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

function isFindingDispositionArray(
  value: unknown,
): value is VerifyResult["findingDispositions"] {
  if (!Array.isArray(value)) return false;
  return value.every((item) => {
    if (item == null || typeof item !== "object") return false;
    const d = item as Record<string, unknown>;
    return (
      typeof d.identityKey === "string" &&
      typeof d.threadId === "string" &&
      (d.action === "fix" || d.action === "reject" || d.action === "defer") &&
      (d.reason === undefined || typeof d.reason === "string")
    );
  });
}

function isThreadReplyArray(
  value: unknown,
): value is VerifyResult["threadReplies"] {
  if (!Array.isArray(value)) return false;
  return value.every((item) => {
    if (item == null || typeof item !== "object") return false;
    const r = item as Record<string, unknown>;
    return typeof r.threadId === "string" && typeof r.body === "string";
  });
}

function verifyResultSemanticallyConsistent(obj: Record<string, unknown>): boolean {
  const threadsToResolve = obj.threadsToResolve;
  if (
    Array.isArray(threadsToResolve) &&
    threadsToResolve.length > 0 &&
    obj.isRecheck !== true
  ) {
    return false;
  }

  const fixKeys = obj.fixMarkedFindingIdentityKeys;
  const dispositions = obj.findingDispositions;
  const hasExplicitFixKeys = fixKeys !== undefined;
  const hasDispositions =
    Array.isArray(dispositions) && dispositions.length > 0;

  // Set-equality when the worker explicitly carries fixMarkedFindingIdentityKeys
  // (fail-closed regardless of converged): the array and fix-action dispositions
  // must be the same set — both directions, including empty ([] ↔ no fix
  // dispositions). Omitted fixMarked keys derive from dispositions only after
  // validation passes (host-side fixMarkedKeysFromVerify).
  if (hasExplicitFixKeys) {
    if (!isStringArray(fixKeys)) {
      return false;
    }
    if (hasDispositions && !isFindingDispositionArray(dispositions)) {
      return false;
    }
    const markedKeys = new Set(fixKeys);
    const fixDispositionKeys = new Set(
      (hasDispositions ? dispositions : [])
        .filter((d) => d.action === "fix")
        .map((d) => d.identityKey),
    );
    if (markedKeys.size !== fixDispositionKeys.size) {
      return false;
    }
    for (const key of markedKeys) {
      if (!fixDispositionKeys.has(key)) {
        return false;
      }
    }
  }

  if (obj.converged !== true) return true;
  if (hasExplicitFixKeys && isStringArray(fixKeys) && fixKeys.length > 0) {
    return false;
  }
  if (
    Array.isArray(dispositions) &&
    dispositions.some(
      (item) =>
        item != null &&
        typeof item === "object" &&
        (item as { action?: unknown }).action === "fix",
    )
  ) {
    return false;
  }
  return true;
}

export function isValidVerifyResult(
  o: StepOutput | undefined,
): o is VerifyResult {
  if (o == null || typeof o !== "object") return false;
  const obj = o as unknown as Record<string, unknown>;
  if (obj.kind !== "verify" || typeof obj.converged !== "boolean") return false;
  if (!verifyResultSemanticallyConsistent(obj)) return false;
  if (
    obj.findingDispositions !== undefined &&
    !isFindingDispositionArray(obj.findingDispositions)
  ) {
    return false;
  }
  if (
    obj.fixMarkedFindingIdentityKeys !== undefined &&
    !isStringArray(obj.fixMarkedFindingIdentityKeys)
  ) {
    return false;
  }
  if (obj.threadReplies !== undefined && !isThreadReplyArray(obj.threadReplies)) {
    return false;
  }
  if (obj.threadsToResolve !== undefined && !isStringArray(obj.threadsToResolve)) {
    return false;
  }
  if (obj.deferredIssueUrls !== undefined) {
    if (!isStringArray(obj.deferredIssueUrls)) return false;
    if (!obj.deferredIssueUrls.every((url) => isValidGithubIssueUrl(url))) {
      return false;
    }
  }
  if (
    obj.terminalState !== undefined &&
    obj.terminalState !== "mergeable" &&
    obj.terminalState !== "round_budget_exhausted" &&
    obj.terminalState !== "decision_gate_raised"
  ) {
    return false;
  }
  if (obj.isRecheck !== undefined && typeof obj.isRecheck !== "boolean") {
    return false;
  }
  return true;
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
