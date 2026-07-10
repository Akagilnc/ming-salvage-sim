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
  const fixKeys = obj.fixMarkedFindingIdentityKeys;
  const dispositions = obj.findingDispositions;
  const isRecheck = obj.isRecheck === true;
  const hasExplicitFixKeys = fixKeys !== undefined;
  const hasDispositions =
    Array.isArray(dispositions) && dispositions.length > 0;

  // Set-equality when the worker explicitly carries fixMarkedFindingIdentityKeys
  // (fail-closed regardless of converged): the array and fix-action dispositions
  // must be the same set — both directions, including empty ([] ↔ no fix
  // dispositions). Omitted fixMarked keys derive from dispositions only after
  // validation passes (host-side fixMarkedKeysFromVerify).
  if (hasExplicitFixKeys && !isRecheck) {
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
  if (
    !isRecheck &&
    hasExplicitFixKeys &&
    isStringArray(fixKeys) &&
    fixKeys.length > 0
  ) {
    return false;
  }
  if (
    !isRecheck &&
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
  // #711: findingFamilies is an accelerator, not a gate. Malformed values must
  // not fail the whole verify verdict — callers sanitize/drop them to no-brief.
  return true;
}

function isValidFixerEnvelopeFields(obj: Record<string, unknown>): boolean {
  if (typeof obj.committed !== "boolean") return false;
  if (obj.alreadySatisfied !== undefined && typeof obj.alreadySatisfied !== "boolean") {
    return false;
  }
  if (obj.fixCommitSha !== undefined && typeof obj.fixCommitSha !== "string") {
    return false;
  }
  if (obj.committed === true && obj.alreadySatisfied === true) {
    return false;
  }
  if (
    obj.committed === true &&
    (typeof obj.fixCommitSha !== "string" || obj.fixCommitSha.length === 0)
  ) {
    return false;
  }
  if (
    obj.committed === false &&
    obj.alreadySatisfied === true &&
    (typeof obj.fixCommitSha !== "string" || obj.fixCommitSha.length === 0)
  ) {
    return false;
  }
  return true;
}

export function isValidFixerResult(o: StepOutput | undefined): o is FixerResult {
  if (o == null || typeof o !== "object") return false;
  const obj = o as unknown as Record<string, unknown>;
  return obj.kind === "fixer" && isValidFixerEnvelopeFields(obj);
}

/** True when the fixer outcome should advance to fresh S9 verify (not park). */
export function fixerProceedsToVerify(output: FixerResult): boolean {
  return output.committed || output.alreadySatisfied === true;
}

/** Ledger replay: S10 fixer output that advanced the loop (committed or alreadySatisfied). */
export function fixerLedgerOutputProceeds(output?: {
  readonly kind?: string;
  readonly committed?: boolean;
  readonly alreadySatisfied?: boolean;
}): boolean {
  return (
    output?.kind === "fixer" &&
    (output.committed === true || output.alreadySatisfied === true)
  );
}

/** Fix SHA recorded on an S10 ledger row (envelope only). */
export function fixerLedgerFixCommitSha(entry: {
  readonly branchHEAD?: string;
  readonly output?: {
    readonly kind?: string;
    readonly committed?: boolean;
    readonly alreadySatisfied?: boolean;
    readonly fixCommitSha?: string;
  };
}): string | undefined {
  const output = entry.output;
  if (!fixerLedgerOutputProceeds(output)) {
    return undefined;
  }
  if (
    typeof output?.fixCommitSha === "string" &&
    output.fixCommitSha.length > 0
  ) {
    return output.fixCommitSha;
  }
  return undefined;
}

/**
 * Fix SHA from the fixer envelope (committed:true or alreadySatisfied).
 * Runner/stage must not re-read live git for this value (ADR 0030).
 */
export function fixerEnvelopeFixCommitSha(output: FixerResult): string | undefined {
  if (output.committed === true || output.alreadySatisfied === true) {
    return output.fixCommitSha;
  }
  return undefined;
}

export function fixerResultFromParsed(parsed: {
  readonly committed: boolean;
  readonly alreadySatisfied?: boolean;
  readonly fixCommitSha?: string;
}): FixerResult {
  const candidate: FixerResult = {
    kind: "fixer",
    committed: parsed.committed,
    ...(parsed.alreadySatisfied === true ? { alreadySatisfied: true } : {}),
    ...(parsed.fixCommitSha !== undefined
      ? { fixCommitSha: parsed.fixCommitSha }
      : {}),
  };
  if (!isValidFixerResult(candidate)) {
    throw new Error("fixerResultFromParsed: envelope failed isValidFixerResult");
  }
  return candidate;
}

const CLEANUP_BRANCH_OUTCOMES = new Set([
  "deleted",
  "already_gone",
  "skipped_tip_drift",
  "skipped_pr_not_merged",
  "skipped_precondition",
]);

export function isValidCleanupResult(
  o: StepOutput | undefined,
): o is CleanupResult {
  if (o == null || typeof o !== "object") return false;
  const obj = o as unknown as Record<string, unknown>;
  if (obj.kind !== "cleanup") return false;
  if (typeof obj.terminal !== "boolean" || typeof obj.ok !== "boolean") {
    return false;
  }
  if (obj.terminal === false && obj.ok === true) return false;
  if (obj.issuesClosed !== undefined) {
    if (
      !Array.isArray(obj.issuesClosed) ||
      !obj.issuesClosed.every(
        (n) => typeof n === "number" && Number.isFinite(n) && n > 0,
      )
    ) {
      return false;
    }
  }
  if (
    obj.parentIssueClosed !== undefined &&
    typeof obj.parentIssueClosed !== "boolean"
  ) {
    return false;
  }
  if (
    obj.branchOutcome !== undefined &&
    (typeof obj.branchOutcome !== "string" ||
      !CLEANUP_BRANCH_OUTCOMES.has(obj.branchOutcome))
  ) {
    return false;
  }
  if (obj.skippedReasons !== undefined) {
    if (
      !Array.isArray(obj.skippedReasons) ||
      !obj.skippedReasons.every((r) => typeof r === "string")
    ) {
      return false;
    }
  }
  return true;
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
  return { kind: "fixer", committed: true, fixCommitSha: "stub-fix-sha" };
}

/** Deterministic skeleton verdict used by offline/test paths for S11. */
export function stubCleanupResult(): CleanupResult {
  return {
    kind: "cleanup",
    terminal: true,
    ok: true,
    branchOutcome: "already_gone",
  };
}

/**
 * Deterministic offline/test skeleton for S12 文档发布.
 * Live paths must not use this unconditionally (#735) — only the offline hatch.
 */
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
