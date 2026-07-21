/**
 * #925 / #1081 test fixtures — build legal judge StepOutputs / WorkerResults
 * without hand-copying disposition tables in every fake backend.
 */

import type { IntegratedCmrResult } from "../../src/family/types.js";
import { findingIdentityKey } from "../../src/findings.js";
import {
  isJudgeOpenCourtSpec,
  liveDispositionsForFindings,
  liveDispositionsForOpenCount,
  unusableResidualOpenCountPaper,
} from "../../src/judgeStation.js";
import type {
  Finding,
  JudgeFindingDisposition,
  JudgeResult,
  ReviewerOutput,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

/** Default session id for #1081 open-court birth in scripted backends. */
export const OPEN_COURT_SESSION = "sess-judge-court-open";

/**
 * #1081: open-court birth dispatch — return court-ready ack without consuming
 * S3/S6 judge scripts. Callers check this before scripted judge queues.
 *
 * Default is the production court-ready ack (`converged`). Tests that exercise
 * legal open-court escalate should pass a custom WorkerResult instead of this
 * helper (or supply openCourtResult to the lifecycle backend).
 */
export function openCourtWorkerResultIfMatch(
  spec: Pick<WorkerSpec, "promptFile">,
  sessionId: string = OPEN_COURT_SESSION,
  output: JudgeResult = { kind: "judge", status: "converged" },
): WorkerResult | undefined {
  if (!isJudgeOpenCourtSpec(spec)) return undefined;
  return {
    kind: "completed",
    output,
    sessionId,
  };
}

/** Authored residual body for fixtures that exercise residual open-count transport. */
export const FIXTURE_RESIDUAL_FIX_PACKET_BODY =
  "fixture residual authored fixPacketBody (ADR 0138 pass-through)";

/**
 * Residual open-count paper with an explicit authored body (pass-through only).
 * Production never invents this string — tests must supply it when residual
 * paper is expected to reach coder-fix (ADR 0138 / #978).
 */
export function residualOpenContinue(
  findings: ReadonlyArray<Finding>,
  opts?: {
    readonly findingsCount?: number;
    readonly fixPacketBody?: string;
  },
): ReviewerOutput {
  const findingsCount = opts?.findingsCount ?? findings.length;
  const fixPacketBody = opts?.fixPacketBody ?? FIXTURE_RESIDUAL_FIX_PACKET_BODY;
  return {
    kind: "reviewer",
    findings: [...findings],
    findingsCount,
    fixPacketBody,
  };
}

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
    /** ADR 0138 / #978: judge-authored fix packet body (defaults to fixture text). */
    readonly fixPacketBody?: string;
  },
): JudgeResult {
  const kills = opts?.kill ?? [];
  const suppresses = opts?.suppress ?? [];
  const terminalKeys = new Set([
    ...kills.map((k) => k.identityKey),
    ...suppresses.map((s) => s.identityKey),
  ]);
  const liveFindings = findings.filter(
    (f) => !terminalKeys.has(findingIdentityKey(f)),
  );
  const live = liveDispositionsForFindings(liveFindings);
  const fixPacketBody =
    opts?.fixPacketBody ??
    (liveFindings.length > 0
      ? liveFindings
          .map(
            (f) =>
              `${f.severity} ${f.category} @ ${f.location}: ${f.claim_quote}`,
          )
          .join("\n")
      : "fixture judge continue: live findings remain");
  return {
    kind: "judge",
    status: "continue",
    findingDispositions: [...kills, ...suppresses, ...live],
    findings: [...findings],
    fixPacketBody,
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

/**
 * Fourth terminal (#1027 / ADR 0145) — wave-verify red the judge classifies as
 * a toolchain/environment failure (runner falls back to verify_failed). Unlike
 * escalate this is NOT a decision-gate park, so it carries no `escalate` mirror.
 */
export function judgeToolchain(
  reason = "MODULE_NOT_FOUND after merge",
  diagnosis = "missing dependency; not a cross-slice regression",
): JudgeResult {
  return {
    kind: "judge",
    status: "toolchain",
    reason,
    diagnosis,
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
            fixPacketBody: `fixture family continue: ${count} live finding(s)`,
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
