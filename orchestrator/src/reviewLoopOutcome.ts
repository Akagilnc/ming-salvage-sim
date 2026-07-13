/**
 * Family review-loop worker outcome seam (#596).
 *
 * Defines the typed payload shapes and compatibility results consumed by the
 * family S9 verify → S10 fixer → S11 cleanup → S12 docRelease endgame.
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

/**
 * #877 / ship-pre completeness: disposition ↔ fixMarked set-equality and
 * "converged with fix marks" content courts demolished — hard DELETE, not an
 * always-true soft shell (kill-axis: no milder replacement validator).
 * Type-shape of optional arrays is checked below; no semantic helper remains.
 */
export function isValidVerifyResult(
  o: StepOutput | undefined,
): o is VerifyResult {
  if (o == null || typeof o !== "object") return false;
  const obj = o as unknown as Record<string, unknown>;
  if (obj.kind !== "verify" || typeof obj.converged !== "boolean") return false;
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

/** Every well-shaped fixer envelope returns to fresh S9 verification. */
export function fixerProceedsToVerify(_output: FixerResult): boolean {
  return true;
}

/** Ledger replay: every valid S10 fixer output advances to fresh verification. */
export function fixerLedgerOutputProceeds(output?: {
  readonly kind?: string;
  readonly committed?: boolean;
  readonly alreadySatisfied?: boolean;
}): boolean {
  return (
    output?.kind === "fixer" &&
    typeof output?.committed === "boolean"
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
 * Deterministic family offline/test skeleton for S12 文档发布.
 * Live paths must not use this unconditionally (#735) — only the offline hatch.
 */
export function stubDocReleaseResult(): DocReleaseResult {
  return { kind: "docRelease", released: true };
}

/**
 * The deterministic `completed` WorkerResult the #596 skeleton returns for a
 * review-loop kind (verify/fixer/cleanup/docRelease) when no real worker is
 * wired. Returns `undefined` for any other kind, so family test backends can
 * fall through to their own handling. Live family logic handles these kinds
 * before this compatibility helper.
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
