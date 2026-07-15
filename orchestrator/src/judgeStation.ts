/**
 * #925 — Judge station pure helpers.
 *
 * Topology-facing utilities for the persistent verify judge (S3 establish /
 * S6 resume): review-leg prompt injection, disposition → ledger flips, and
 * live-finding filtering for S5. Runner topology reads only enum status +
 * fixed schema fields from {@link decodeJudgeVerdict}; this module never
 * parses finding prose for routing.
 */

import type {
  Finding,
  FindingDisposition,
  JudgeFindingDisposition,
  JudgeResult,
  JudgeVerdictStatus,
  LedgerEntry,
  WorkerSessionMode,
} from "./types.js";
import { findingIdentityKey } from "./findings.js";
import type {
  JudgeFindingDisposition as ContractDisposition,
  JudgeVerdict,
  LegalRefuseReason,
} from "./stationReceiptContracts.js";

// Re-export the contract disposition name collision fix — types.ts mirrors the
// same shape for StepOutput. Prefer types.JudgeFindingDisposition at call sites.
export type { LegalRefuseReason };

/**
 * Build a fresh review-leg prompt with the full reviewer soul prepended
 * (single-track CLI injection — no Claude-only agent definition).
 *
 * AC: 腿 prompt 头含 reviewer soul.
 */
export function buildJudgeReviewLegPrompt(
  reviewerSoulFullText: string,
  legTaskBody: string,
): string {
  const soul = reviewerSoulFullText.trim();
  const body = legTaskBody.trim();
  if (soul.length === 0) {
    throw new Error("buildJudgeReviewLegPrompt: reviewer soul text must be non-empty");
  }
  if (body.length === 0) {
    throw new Error("buildJudgeReviewLegPrompt: leg task body must be non-empty");
  }
  return `${soul}\n\n---\n\n${body}`;
}

/**
 * Review legs dispatched by the judge are always fresh sessions.
 * Resume is illegal (negative AC: 续腿不合法).
 */
export function judgeReviewLegSessionMode(): "fresh" {
  return "fresh";
}

/** True only for the legal leg session mode (`fresh`). */
export function isLegalJudgeReviewLegSession(
  session: WorkerSessionMode | string,
): boolean {
  return session === "fresh";
}

/**
 * Envelope consistency: converged must not coexist with live dispositions.
 * Pure check for tests / seat self-check — runner does not re-judge.
 */
export function liveFindingsBlockConverged(
  dispositions: ReadonlyArray<{ readonly action: string }> | undefined,
): boolean {
  return (dispositions ?? []).some((d) => d.action === "live");
}

/**
 * Map judge kill dispositions to ledger findings-store flips (`refuted`).
 * Live rows stay out of the terminal ledger flip set (they remain open).
 */
export function judgeKillsToLedgerDispositions(
  dispositions: ReadonlyArray<JudgeFindingDisposition | ContractDisposition>,
  severity: Finding["severity"] = "medium",
): FindingDisposition[] {
  const out: FindingDisposition[] = [];
  for (const d of dispositions) {
    if (d.action !== "refute") continue;
    out.push({
      identityKey: d.identityKey,
      status: "refuted",
      reason: `${d.reason}: ${d.evidence}`,
      severity,
      source: "judge_kill",
      scope: d.reason,
    });
  }
  return out;
}

/**
 * Filter findings cargo to only the live (open) identity keys from the
 * disposition table. Dead/refuted keys never enter S5 dispatch.
 *
 * Filtering is by schema identity keys — not by prose parsing.
 */
export function openFindingsForFixer(
  findings: ReadonlyArray<Finding>,
  dispositions: ReadonlyArray<JudgeFindingDisposition | ContractDisposition>,
): Finding[] {
  const liveKeys = new Set(
    dispositions.filter((d) => d.action === "live").map((d) => d.identityKey),
  );
  // When the judge supplied an explicit disposition table, only live keys pass.
  // Empty table with continue is legal (zero open) — yield empty.
  if (dispositions.length > 0 || liveKeys.size > 0) {
    return findings.filter((f) => liveKeys.has(findingIdentityKey(f)));
  }
  return [];
}

/** Live identity keys only (control envelope for S5). */
export function liveFindingIdentityKeys(
  dispositions: ReadonlyArray<JudgeFindingDisposition | ContractDisposition>,
): string[] {
  return dispositions
    .filter((d) => d.action === "live")
    .map((d) => d.identityKey);
}

/**
 * Extract prior judge verdict rows from a ledger for a new judge after
 * session loss. Runner transports these rows as-is — never synthesises a
 * narrative summary (AC: runner 不生成摘要).
 */
export function priorJudgeVerdictRowsFromLedger(
  ledger: ReadonlyArray<LedgerEntry>,
): ReadonlyArray<{
  readonly step: string;
  readonly status: JudgeVerdictStatus;
  readonly advanceCoder?: string;
  readonly findingDispositions?: ReadonlyArray<JudgeFindingDisposition>;
  readonly sessionId?: string;
}> {
  const rows: Array<{
    readonly step: string;
    readonly status: JudgeVerdictStatus;
    readonly advanceCoder?: string;
    readonly findingDispositions?: ReadonlyArray<JudgeFindingDisposition>;
    readonly sessionId?: string;
  }> = [];
  for (const entry of ledger) {
    if (entry.event !== undefined) continue;
    if (entry.step !== "S3" && entry.step !== "S6") continue;
    const out = entry.output;
    if (out?.kind !== "judge") continue;
    rows.push({
      step: entry.step,
      status: out.status,
      ...(out.advanceCoder !== undefined
        ? { advanceCoder: out.advanceCoder }
        : {}),
      ...(out.findingDispositions !== undefined
        ? { findingDispositions: out.findingDispositions }
        : {}),
      ...(typeof entry.sessionId === "string"
        ? { sessionId: entry.sessionId }
        : {}),
    });
  }
  return rows;
}

/**
 * Project a decoded T2 judge verdict + optional findings cargo into the
 * runner-facing {@link JudgeResult} step output.
 */
export function judgeResultFromVerdict(
  verdict: JudgeVerdict,
  findingsCargo?: ReadonlyArray<Finding>,
): JudgeResult {
  if (verdict.status === "converged") {
    return { kind: "judge", status: "converged" };
  }
  if (verdict.status === "escalate") {
    return {
      kind: "judge",
      status: "escalate",
      reason: verdict.reason,
      diagnosis: verdict.diagnosis,
      escalate: { reason: verdict.reason, diagnosis: verdict.diagnosis },
    };
  }
  // continue
  return {
    kind: "judge",
    status: "continue",
    findingDispositions: verdict.findingDispositions as readonly JudgeFindingDisposition[],
    ...(verdict.advanceCoder !== undefined
      ? { advanceCoder: verdict.advanceCoder }
      : {}),
    ...(findingsCargo !== undefined ? { findings: findingsCargo } : {}),
  };
}

/** Convenience: build a continue verdict table from live finding rows. */
export function liveDispositionsForFindings(
  findings: ReadonlyArray<Finding>,
): JudgeFindingDisposition[] {
  return findings.map((f) => ({
    identityKey: findingIdentityKey(f),
    action: "live" as const,
  }));
}
