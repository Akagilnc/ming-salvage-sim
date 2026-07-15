/**
 * #925 test fixtures — build legal judge StepOutputs / WorkerResults without
 * hand-copying disposition tables in every fake backend.
 */

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

/** True for S3/S6 judge seats after #925 (kind verify; residual reviewer kind). */
export function isJudgeSeat(spec: {
  readonly kind?: string;
  readonly id?: string;
  readonly role?: string;
}): boolean {
  if (spec.id === "S3" || spec.id === "S6") return true;
  return spec.kind === "verify" || spec.role === "verify";
}
