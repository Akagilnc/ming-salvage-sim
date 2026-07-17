/**
 * #925 test fixtures — build legal judge StepOutputs / WorkerResults without
 * hand-copying disposition tables in every fake backend.
 */

import type { IntegratedCmrResult } from "../../src/family/types.js";
import { findingIdentityKey } from "../../src/findings.js";
import {
  liveDispositionsForFindings,
  liveDispositionsForOpenCount,
  unusableResidualOpenCountPaper,
} from "../../src/judgeStation.js";
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
    /** #952 terminal suppress rows (parked; not sent to fixer). */
    readonly suppress?: ReadonlyArray<
      JudgeFindingDisposition & { action: "suppress" }
    >;
    readonly advanceCoder?: string;
  },
): JudgeResult {
  const kills = opts?.kill ?? [];
  const suppresses = opts?.suppress ?? [];
  const terminalKeys = new Set([
    ...kills.map((k) => k.identityKey),
    ...suppresses.map((s) => s.identityKey),
  ]);
  const live = liveDispositionsForFindings(
    findings.filter((f) => !terminalKeys.has(findingIdentityKey(f))),
  );
  return {
    kind: "judge",
    status: "continue",
    findingDispositions: [...kills, ...suppresses, ...live],
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

/**
 * Test-fake live continue for family CMR fix-loop scripts (#919 E).
 *
 * Prefer this over residual `kind:cmr` + positive `findingsCount` — production
 * never mints continue from open-count. When findings cargo is sparse but a
 * positive count is intended, dispositions use synthetic live keys (fixture
 * 直出 live judge envelope; not residual projection).
 */
export function liveCmrJudgeContinue(
  findings: ReadonlyArray<Finding>,
  opts?: {
    readonly findingsCount?: number;
    readonly successfulLegs?: ReadonlyArray<string>;
    readonly skippedLegs?: IntegratedCmrResult["skippedLegs"];
    readonly evidencePaths?: ReadonlyArray<string>;
    readonly reason?: string;
    readonly claimedFixedFindingIdentityKeys?: ReadonlyArray<string>;
    readonly priorFindingDispositions?: IntegratedCmrResult["priorFindingDispositions"];
    readonly findingFamilies?: IntegratedCmrResult["findingFamilies"];
  },
): JudgeResult {
  const count = opts?.findingsCount;
  const base =
    findings.length > 0
      ? judgeContinue(findings)
      : count !== undefined && count > 0
        ? ({
            kind: "judge",
            status: "continue",
            findingDispositions: liveDispositionsForOpenCount(count, []),
            findings: [],
          } as JudgeResult)
        : judgeContinue([]);
  return {
    ...base,
    ...(opts?.successfulLegs !== undefined
      ? { successfulLegs: opts.successfulLegs }
      : {}),
    ...(opts?.skippedLegs !== undefined ? { skippedLegs: opts.skippedLegs } : {}),
    ...(opts?.evidencePaths !== undefined
      ? { evidencePaths: opts.evidencePaths }
      : {}),
    ...(opts?.reason !== undefined ? { reason: opts.reason } : {}),
    ...(opts?.claimedFixedFindingIdentityKeys !== undefined
      ? {
          claimedFixedFindingIdentityKeys: opts.claimedFixedFindingIdentityKeys,
        }
      : {}),
    ...(opts?.priorFindingDispositions !== undefined
      ? { priorFindingDispositions: opts.priorFindingDispositions }
      : {}),
    ...(opts?.findingFamilies !== undefined
      ? { findingFamilies: opts.findingFamilies }
      : {}),
  } as JudgeResult;
}

/**
 * Test-fake boundary only (#919 E / R7 / CR N2).
 *
 * Scripts may still *declare* positive findingsCount as an intent to continue;
 * this helper mints **live** `kind:judge` continue at the fake boundary
 * (not production residual — family residual is
 * {@link unusableResidualOpenCountPaper} only).
 *
 * - findingsCount > 0 → live kind:judge continue (from findings cargo / synthetic)
 * - findingsCount === 0 → shared unusable residual paper (never silent clean)
 * - boolean green WITHOUT findingsCount → live kind:judge converged
 *
 * Prefer {@link judgeContinue} / {@link liveCmrJudgeGreen} for new fixtures.
 * Production residual path never invents green/continue from count or boolean.
 */
export function legacyCmrScriptToWorkerOutput(
  cmr: IntegratedCmrResult,
): JudgeResult | ReturnType<typeof unusableResidualOpenCountPaper> {
  // Script intent: positive open-count → live judge continue (fake boundary only).
  if (
    typeof cmr.findingsCount === "number" &&
    Number.isSafeInteger(cmr.findingsCount) &&
    cmr.findingsCount > 0
  ) {
    return liveCmrJudgeContinue(cmr.findings ?? [], {
      findingsCount: cmr.findingsCount,
      ...(cmr.successfulLegs !== undefined
        ? { successfulLegs: cmr.successfulLegs }
        : {}),
      ...(cmr.skippedLegs !== undefined ? { skippedLegs: cmr.skippedLegs } : {}),
      ...(cmr.evidencePaths !== undefined
        ? { evidencePaths: cmr.evidencePaths }
        : {}),
      ...(cmr.claimedFixedFindingIdentityKeys !== undefined
        ? {
            claimedFixedFindingIdentityKeys:
              cmr.claimedFixedFindingIdentityKeys,
          }
        : {}),
      ...(cmr.priorFindingDispositions !== undefined
        ? { priorFindingDispositions: cmr.priorFindingDispositions }
        : {}),
      ...(cmr.reason !== undefined ? { reason: cmr.reason } : {}),
      ...(cmr.findingFamilies !== undefined
        ? { findingFamilies: cmr.findingFamilies }
        : {}),
    });
  }

  // Happy path 直出 judge — only when open-count is absent.
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

  // findingsCount:0 / missing-non-green residual → shared unusable paper only.
  return unusableResidualOpenCountPaper();
}
