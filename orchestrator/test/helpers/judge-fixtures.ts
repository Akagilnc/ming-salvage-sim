/**
 * #925 test fixtures — build legal judge StepOutputs / WorkerResults without
 * hand-copying disposition tables in every fake backend.
 */

import { residualIntegratedCmrToJudgeOutput } from "../../src/family/dispatchFamilyWorker.js";
import type { IntegratedCmrResult } from "../../src/family/types.js";
import { findingIdentityKey } from "../../src/findings.js";
import { liveDispositionsForFindings } from "../../src/judgeStation.js";
import type {
  Finding,
  JudgeFindingDisposition,
  JudgeResult,
  WorkerResult,
} from "../../src/types.js";

export function judgeConverged(): JudgeResult {
  return { kind: "judge", status: "converged" };
}

export function judgeContinue(
  findings: ReadonlyArray<Finding>,
  opts?: {
    readonly kill?: ReadonlyArray<JudgeFindingDisposition & { action: "refute" }>;
    readonly advanceCoder?: string;
  },
): JudgeResult {
  const kills = opts?.kill ?? [];
  const killKeys = new Set(kills.map((k) => k.identityKey));
  const live = liveDispositionsForFindings(
    findings.filter((f) => !killKeys.has(findingIdentityKey(f))),
  );
  return {
    kind: "judge",
    status: "continue",
    findingDispositions: [...kills, ...live],
    findings: [...findings],
    ...(opts?.advanceCoder !== undefined
      ? { advanceCoder: opts.advanceCoder }
      : {}),
  };
}

export function judgeEscalate(
  reason = "stuck",
  diagnosis = "needs owner decision",
): JudgeResult {
  return {
    kind: "judge",
    status: "escalate",
    reason,
    diagnosis,
    escalate: { reason, diagnosis },
  };
}

export function completedJudge(
  output: JudgeResult,
  sessionId?: string,
): WorkerResult {
  return {
    kind: "completed",
    output,
    ...(sessionId !== undefined ? { sessionId } : {}),
  };
}

/** Sample blocking finding for topology tests. */
export function sampleFinding(
  claim = "x",
  location = "f.ts:1",
): Finding {
  return {
    severity: "high",
    category: "correctness",
    claim_quote: claim,
    location,
    suggested_fix: "fix it",
    action: "fix_now",
  };
}

/** True for S3/S6 judge seats after #925 — re-export production predicate (#919 S2). */
export { isJudgeSeat } from "../../src/judgeStation.js";

/**
 * Test-fake boundary only (#919 M2 / R7).
 *
 * - residual positive open-count → project to kind:judge continue
 * - boolean green WITHOUT findingsCount → live kind:judge converged
 *   (happy-path scripts 直出 judge at the fake boundary — not production)
 * - findingsCount:0 / residual unusable paper stays kind:cmr (**never** silent clean)
 *
 * Production residual path never invents green from boolean alone. Prefer
 * {@link judgeConverged} / {@link liveCmrJudgeGreen} for new fixtures.
 */
export function legacyCmrScriptToWorkerOutput(
  cmr: IntegratedCmrResult,
): JudgeResult | (IntegratedCmrResult & { readonly kind: "cmr" }) {
  const projected = residualIntegratedCmrToJudgeOutput(cmr);
  if (projected !== undefined) {
    return {
      ...projected,
      ...(cmr.successfulLegs !== undefined
        ? { successfulLegs: cmr.successfulLegs }
        : {}),
      ...(cmr.skippedLegs !== undefined ? { skippedLegs: cmr.skippedLegs } : {}),
      ...(cmr.evidencePaths !== undefined
        ? { evidencePaths: cmr.evidencePaths }
        : {}),
    } as JudgeResult;
  }
  // Happy path 直出 judge — only when open-count is absent. findingsCount:0
  // falls through as residual unusable (never silent clean).
  if (cmr.converged === true && typeof cmr.findingsCount !== "number") {
    return liveCmrJudgeGreen({
      ...(cmr.successfulLegs !== undefined
        ? { successfulLegs: cmr.successfulLegs }
        : {}),
      ...(cmr.skippedLegs !== undefined ? { skippedLegs: cmr.skippedLegs } : {}),
      ...(cmr.evidencePaths !== undefined
        ? { evidencePaths: cmr.evidencePaths }
        : {}),
    });
  }
  return {
    kind: "cmr",
    converged: cmr.converged,
    ...(cmr.findingsCount !== undefined
      ? { findingsCount: cmr.findingsCount }
      : {}),
    ...(cmr.reason !== undefined ? { reason: cmr.reason } : {}),
    ...(cmr.findings !== undefined ? { findings: cmr.findings } : {}),
    ...(cmr.successfulLegs !== undefined
      ? { successfulLegs: cmr.successfulLegs }
      : {}),
    ...(cmr.skippedLegs !== undefined ? { skippedLegs: cmr.skippedLegs } : {}),
    ...(cmr.claimedFixedFindingIdentityKeys !== undefined
      ? {
          claimedFixedFindingIdentityKeys: cmr.claimedFixedFindingIdentityKeys,
        }
      : {}),
    ...(cmr.priorFindingDispositions !== undefined
      ? { priorFindingDispositions: cmr.priorFindingDispositions }
      : {}),
    ...(cmr.evidencePaths !== undefined
      ? { evidencePaths: cmr.evidencePaths }
      : {}),
  };
}

/**
 * Test-fake live green for family CMR happy path (#919 R7).
 * Prefer this over residual `kind:cmr` + `findingsCount:0` scripts.
 */
export function liveCmrJudgeGreen(opts?: {
  readonly successfulLegs?: ReadonlyArray<string>;
  readonly skippedLegs?: IntegratedCmrResult["skippedLegs"];
  readonly evidencePaths?: ReadonlyArray<string>;
}): JudgeResult {
  return {
    kind: "judge",
    status: "converged",
    ...(opts?.successfulLegs !== undefined
      ? { successfulLegs: opts.successfulLegs }
      : {}),
    ...(opts?.skippedLegs !== undefined ? { skippedLegs: opts.skippedLegs } : {}),
    ...(opts?.evidencePaths !== undefined
      ? { evidencePaths: opts.evidencePaths }
      : {}),
  } as JudgeResult;
}
