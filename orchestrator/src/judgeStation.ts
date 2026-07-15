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
  Escalation,
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
  JudgeVerdict,
  LegalRefuseReason,
} from "./stationReceiptContracts.js";

// types.ts re-exports JudgeFindingDisposition from stationReceiptContracts
// (single source — #919 CR P3). No dual isomorphic import needed.
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
  dispositions: ReadonlyArray<JudgeFindingDisposition>,
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
  dispositions: ReadonlyArray<JudgeFindingDisposition>,
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
  dispositions: ReadonlyArray<JudgeFindingDisposition>,
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
 * Mint the canonical T2 judge escalate envelope (status + reason/diagnosis +
 * escalate payload). Shared by gate bells, residual projection, and verdict
 * projection so three hand-copied objects cannot drift.
 */
export function mintJudgeEscalate(
  escalation: Escalation | { readonly reason: string; readonly diagnosis: string },
): JudgeResult {
  const escalate: Escalation = {
    reason: escalation.reason,
    diagnosis: escalation.diagnosis,
  };
  return {
    kind: "judge",
    status: "escalate",
    reason: escalate.reason,
    diagnosis: escalate.diagnosis,
    escalate,
  };
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
    return mintJudgeEscalate({
      reason: verdict.reason,
      diagnosis: verdict.diagnosis,
    });
  }
  // continue
  return {
    kind: "judge",
    status: "continue",
    findingDispositions: verdict.findingDispositions,
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

/**
 * Residual open-count paper only — not ADR 0131 channel (b), not the preferred
 * production S3/S6 path. One projection for runner normalize + realBackend
 * residual decode: mint opaque `__open_N` live keys when cargo is sparse or
 * lacks identity fields so a positive residual count can still land on S5
 * (count owns the edge; incomplete rows never crash projection). Main path
 * uses typed judge dispositions instead.
 */
export function liveDispositionsForOpenCount(
  findingsCount: number,
  findings: ReadonlyArray<Finding> = [],
): JudgeFindingDisposition[] {
  if (
    findings.length > 0 &&
    findings.every(
      (f) =>
        typeof f.category === "string" &&
        typeof f.location === "string" &&
        typeof f.claim_quote === "string",
    )
  ) {
    return liveDispositionsForFindings(findings);
  }
  // Sparse / opaque residual cargo → count-sized synthetic live keys.
  return Array.from({ length: findingsCount }, (_, i) => ({
    identityKey: `__open_${i + 1}`,
    action: "live" as const,
  }));
}

/**
 * Residual open-count paper → sole judge continue form.
 * Returns undefined when count is not a positive open-count (caller maps
 * zero / escalate / unusable separately).
 */
export function judgeContinueFromOpenCount(
  findingsCount: number,
  findings: ReadonlyArray<Finding> = [],
): JudgeResult | undefined {
  if (
    typeof findingsCount !== "number" ||
    !Number.isSafeInteger(findingsCount) ||
    findingsCount <= 0
  ) {
    return undefined;
  }
  const cargo = [...findings];
  return {
    kind: "judge",
    status: "continue",
    findingDispositions: liveDispositionsForOpenCount(findingsCount, cargo),
    findings: cargo,
  };
}

/**
 * Residual open-count reviewer paper → sole judge form (#919 CR U3).
 *
 * Shared by runner normalize, realBackend residual decode, and route
 * judgeStatusOf so escalate / positive-continue / non-positive-unusable are
 * one predicate — not three parallel arms.
 *
 * - escalate present → T2 kind:"judge" status:"escalate" (wins over count)
 * - positive open-count → continue (via {@link judgeContinueFromOpenCount})
 * - zero / missing / non-integer → undefined (caller maps unusable; never silent clean)
 */
export function projectResidualReviewerToJudge(residual: {
  readonly findingsCount: number;
  readonly findings?: ReadonlyArray<Finding>;
  readonly escalate?: Escalation;
}): JudgeResult | undefined {
  if (residual.escalate !== undefined) {
    return mintJudgeEscalate(residual.escalate);
  }
  return judgeContinueFromOpenCount(
    residual.findingsCount,
    residual.findings ?? [],
  );
}

/**
 * Live-path projection of a judge `continue` verdict into the S5 open set
 * (kills → refuted flips; live keys only). Shared by the in-process continue
 * edge and crash/resume ledger rebuild (F2).
 */
export function projectJudgeContinueBlocking(output: {
  readonly status: string;
  readonly findingDispositions?: ReadonlyArray<JudgeFindingDisposition>;
  readonly findings?: ReadonlyArray<Finding>;
}): {
  readonly blocking: Finding[];
  readonly blockingIdentityKeys: string[];
  readonly blockingFindingCount: number;
  readonly killDispositions: FindingDisposition[];
} | undefined {
  if (output.status !== "continue") return undefined;
  const dispositions = output.findingDispositions ?? [];
  const kills = judgeKillsToLedgerDispositions(dispositions);
  const cargo = output.findings ?? [];
  const blocking = openFindingsForFixer(cargo, dispositions);
  const blockingIdentityKeys = liveFindingIdentityKeys(dispositions);
  return {
    blocking,
    blockingIdentityKeys,
    blockingFindingCount: blockingIdentityKeys.length,
    killDispositions: kills,
  };
}

/**
 * #930 — family CMR court closure from the shared T2 judge tri-state only.
 *
 * One judgment function, two ordered courts (completeness / correctness). The
 * family path must NOT read open-count / findingsCount as a second closer.
 * Unusable / non-judge envelopes route to typed re-furnace (fixer with raw
 * artifacts) — runner does not invent a clean pass.
 *
 * Live+converged is an envelope-consistency negative for seats/tests
 * ({@link liveFindingsBlockConverged}); topology still trusts the status enum
 * and does not re-judge prose.
 */
export type FamilyJudgeClosure =
  | { readonly action: "pass" }
  | {
      readonly action: "continue";
      readonly blocking: Finding[];
      readonly blockingIdentityKeys: string[];
      readonly blockingFindingCount: number;
      readonly killDispositions: FindingDisposition[];
    }
  | {
      readonly action: "escalate";
      readonly reason: string;
      readonly diagnosis: string;
    }
  | { readonly action: "unusable"; readonly reason: string };

export function closeFamilyCourtFromJudgeOutput(
  // Accept any worker / fixture shape; only kind:"judge" is a family closer.
  // `unknown` keeps callers free of WorkerOutput index-signature fights.
  output: unknown,
): FamilyJudgeClosure {
  if (
    output === null ||
    typeof output !== "object" ||
    !("kind" in output) ||
    typeof (output as { kind?: unknown }).kind !== "string"
  ) {
    return {
      action: "unusable",
      reason:
        "family court requires kind:judge tri-state verdict; residual non-judge envelope is not a closer",
    };
  }
  const rec = output as {
    readonly kind: string;
    readonly status?: unknown;
    readonly findingDispositions?: unknown;
    readonly findings?: unknown;
    readonly reason?: unknown;
    readonly diagnosis?: unknown;
    readonly escalate?: unknown;
  };
  if (rec.kind === "judge") {
    const status = typeof rec.status === "string" ? rec.status : undefined;
    if (status === "converged") {
      return { action: "pass" };
    }
    if (status === "continue") {
      const dispositions = Array.isArray(rec.findingDispositions)
        ? (rec.findingDispositions as ReadonlyArray<JudgeFindingDisposition>)
        : undefined;
      const findings = Array.isArray(rec.findings)
        ? (rec.findings as ReadonlyArray<Finding>)
        : undefined;
      const projected = projectJudgeContinueBlocking({
        status: "continue",
        findingDispositions: dispositions,
        findings,
      });
      return {
        action: "continue",
        blocking: projected?.blocking ?? [],
        blockingIdentityKeys: projected?.blockingIdentityKeys ?? [],
        blockingFindingCount: projected?.blockingFindingCount ?? 0,
        killDispositions: projected?.killDispositions ?? [],
      };
    }
    if (status === "escalate") {
      const escalate =
        rec.escalate !== undefined &&
        typeof rec.escalate === "object" &&
        rec.escalate !== null
          ? (rec.escalate as Escalation)
          : undefined;
      const reason =
        (typeof rec.reason === "string" ? rec.reason : undefined) ??
        escalate?.reason ??
        "family judge escalate";
      const diagnosis =
        (typeof rec.diagnosis === "string" ? rec.diagnosis : undefined) ??
        escalate?.diagnosis ??
        "judge declared escalate";
      return { action: "escalate", reason, diagnosis };
    }
    return {
      action: "unusable",
      reason: "family judge envelope missing legal status tri-state",
    };
  }
  // Residual non-judge paper (incl. historical kind:"cmr"+findingsCount):
  // not a family closer. Typed re-furnace, never silent pass via open-count.
  return {
    action: "unusable",
    reason:
      "family court requires kind:judge tri-state verdict; residual non-judge envelope is not a closer",
  };
}

/**
 * #930 — prior family-court judge rows for session-loss recovery.
 * Runner transports ledger rows as-is; never synthesises a narrative summary.
 * Shape matches single-slice {@link priorJudgeVerdictRowsFromLedger} so the
 * family court reuses the same priorJudgeVerdicts landing field.
 */
export function priorFamilyJudgeVerdictRowsFromLedger(
  ledger: ReadonlyArray<{
    readonly status?: string;
    readonly event?: string;
    readonly cmrPass?: string;
    readonly sessionId?: string;
    readonly judgeStatus?: JudgeVerdictStatus;
    readonly findingDispositions?: ReadonlyArray<JudgeFindingDisposition>;
    readonly advanceCoder?: string;
  }>,
  pass?: string,
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
    if (
      entry.status !== "cmr_reviewed" &&
      entry.status !== "cmr_passed" &&
      entry.event !== "cmr_reviewed" &&
      entry.event !== "cmr_passed"
    ) {
      continue;
    }
    if (pass !== undefined && entry.cmrPass !== pass) continue;
    if (
      entry.judgeStatus !== "converged" &&
      entry.judgeStatus !== "continue" &&
      entry.judgeStatus !== "escalate"
    ) {
      continue;
    }
    rows.push({
      step: `family-cmr:${entry.cmrPass ?? "unknown"}`,
      status: entry.judgeStatus,
      ...(entry.advanceCoder !== undefined
        ? { advanceCoder: entry.advanceCoder }
        : {}),
      ...(entry.findingDispositions !== undefined
        ? { findingDispositions: entry.findingDispositions }
        : {}),
      ...(typeof entry.sessionId === "string"
        ? { sessionId: entry.sessionId }
        : {}),
    });
  }
  return rows;
}
