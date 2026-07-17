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
  StepOutput,
  WorkerSessionMode,
} from "./types.js";
import { findingIdentityKey } from "./findings.js";
import { recordFindingStoreFlip } from "./findingsStateStore.js";
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
 * Suppress / refute terminals do not block converged (only `live` does).
 */
export function liveFindingsBlockConverged(
  dispositions: ReadonlyArray<{ readonly action: string }> | undefined,
): boolean {
  return (dispositions ?? []).some((d) => d.action === "live");
}

/**
 * Map judge terminal dispositions to ledger findings-store flips:
 * - `refute` → `refuted` (#925)
 * - `suppress` → `suppressed` (#952; internal terminal, not public ABI)
 *
 * Live rows stay out of the terminal ledger flip set (they remain open).
 * Transitions go through {@link recordFindingStoreFlip} (single write-point
 * source — ADR 0129). Illegal transitions are skipped (caller/seat already
 * validated disposition shape; store only records legal open→terminal flips).
 */
export function judgeTerminalsToLedgerDispositions(
  dispositions: ReadonlyArray<JudgeFindingDisposition>,
  severity: Finding["severity"] = "medium",
): FindingDisposition[] {
  const out: FindingDisposition[] = [];
  for (const d of dispositions) {
    if (d.action === "refute") {
      const written = recordFindingStoreFlip({
        identityKey: d.identityKey,
        from: "unrepaired",
        to: "refuted",
        reason: `${d.reason}: ${d.evidence}`,
        severity,
        source: "judge_kill",
        scope: d.reason,
      });
      if (written.ok) out.push(written.value);
      continue;
    }
    if (d.action === "suppress") {
      const groundSource =
        "groundTicket" in d && d.groundTicket !== undefined
          ? `groundTicket:${d.groundTicket}`
          : d.ownerRecordPointer;
      const written = recordFindingStoreFlip({
        identityKey: d.identityKey,
        from: "unrepaired",
        to: "suppressed",
        reason: d.evidence,
        severity,
        source: groundSource,
        scope:
          "groundTicket" in d && d.groundTicket !== undefined
            ? "groundTicket"
            : "ownerRecordPointer",
      });
      if (written.ok) out.push(written.value);
    }
  }
  return out;
}

/**
 * Filter findings cargo to only the live (open) identity keys from the
 * disposition table. Dead / refuted / suppressed keys never enter S5 dispatch.
 *
 * Filtering is by schema identity keys — not by prose parsing. Only
 * `action: "live"` enters the fixer live-set (#952: suppressed is archived).
 *
 * Empty live set is a cargo filter result only — NOT topology authorization.
 * Family (#919 M1) and single-slice (#919 M6) both fail-loud when
 * status:continue projects zero live identity keys; callers must gate empty
 * continue before dispatching coder-fix / S5.
 */
export function openFindingsForFixer(
  findings: ReadonlyArray<Finding>,
  dispositions: ReadonlyArray<JudgeFindingDisposition>,
): Finding[] {
  const liveKeys = new Set(
    dispositions.filter((d) => d.action === "live").map((d) => d.identityKey),
  );
  // Cargo filter only: empty table / zero live keys → yield []. Topology
  // authorization for empty continue is the caller's fail-loud gate (M1/M6).
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

/** Prior judge-verdict transport row (single-slice + family share this shape). */
export type PriorJudgeVerdictRow = {
  readonly step: string;
  readonly status: JudgeVerdictStatus;
  readonly advanceCoder?: string;
  readonly findingDispositions?: ReadonlyArray<JudgeFindingDisposition>;
  readonly sessionId?: string;
};

/**
 * Heterogeneous ledger entry fields accepted by the unified prior-row scan
 * (single-slice S3/S6 output rows + family cmr_reviewed / cmr_passed rows).
 * Structural fields only — callers pass full ledger unions via cast at the
 * thin wrappers so WorkerOutput / family disposition variance does not fight
 * the scan signature.
 */
type PriorJudgeLedgerEntry = {
  readonly event?: string;
  readonly step?: string;
  readonly sessionId?: string;
  readonly output?: {
    readonly kind?: string;
    readonly status?: string;
    readonly advanceCoder?: string;
    readonly findingDispositions?: ReadonlyArray<JudgeFindingDisposition>;
  };
  readonly status?: string;
  readonly cmrPass?: string;
  readonly judgeStatus?: string;
  readonly findingDispositions?: ReadonlyArray<JudgeFindingDisposition>;
  readonly advanceCoder?: string;
};

function isJudgeVerdictStatus(value: unknown): value is JudgeVerdictStatus {
  return value === "converged" || value === "continue" || value === "escalate";
}

function pushPriorJudgeRow(
  rows: PriorJudgeVerdictRow[],
  row: PriorJudgeVerdictRow,
): void {
  rows.push(row);
}

/**
 * One scan, two sources (#919 S3):
 *   - slice: S3/S6 ledger steps with `output.kind:"judge"`
 *   - family: cmr_reviewed / cmr_passed rows with `judgeStatus` tri-state
 *
 * Runner transports rows as-is — never synthesises a narrative summary.
 */
export function priorJudgeVerdictRowsFromSources(
  ledger: ReadonlyArray<PriorJudgeLedgerEntry>,
  options?: {
    readonly sources?: ReadonlyArray<"slice" | "family">;
    readonly familyPass?: string;
  },
): ReadonlyArray<PriorJudgeVerdictRow> {
  const sources = options?.sources ?? (["slice", "family"] as const);
  const wantSlice = sources.includes("slice");
  const wantFamily = sources.includes("family");
  const familyPass = options?.familyPass;
  const rows: PriorJudgeVerdictRow[] = [];

  for (const entry of ledger) {
    if (wantSlice) {
      // Slice steps never carry family event markers.
      const seatStep = entry.step;
      if (
        entry.event === undefined &&
        seatStep !== undefined &&
        isJudgeSeat({ step: seatStep }) &&
        entry.output?.kind === "judge" &&
        isJudgeVerdictStatus(entry.output.status)
      ) {
        const out = entry.output;
        pushPriorJudgeRow(rows, {
          step: seatStep,
          status: out.status as JudgeVerdictStatus,
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
        continue;
      }
    }

    if (wantFamily) {
      const isFamilyCourtRow =
        entry.status === "cmr_reviewed" ||
        entry.status === "cmr_passed" ||
        entry.event === "cmr_reviewed" ||
        entry.event === "cmr_passed";
      if (!isFamilyCourtRow) continue;
      if (familyPass !== undefined && entry.cmrPass !== familyPass) continue;
      if (!isJudgeVerdictStatus(entry.judgeStatus)) continue;
      pushPriorJudgeRow(rows, {
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
  }
  return rows;
}

/**
 * Extract prior judge verdict rows from a single-slice ledger for a new judge
 * after session loss.
 */
export function priorJudgeVerdictRowsFromLedger(
  ledger: ReadonlyArray<LedgerEntry>,
): ReadonlyArray<PriorJudgeVerdictRow> {
  return priorJudgeVerdictRowsFromSources(
    ledger as ReadonlyArray<PriorJudgeLedgerEntry>,
    { sources: ["slice"] },
  );
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
 * **Single-slice historical residual resume only** — open-count → continue.
 *
 * Scope (crystal clear, #919 CR N4 / ADR 0131):
 *   - LIVE production seats emit typed `kind:"judge"`; they never call this.
 *   - Family court MUST NOT use this as a closer (family residual →
 *     {@link unusableResidualOpenCountPaper} only; see closeFamilyCourtFromJudgeOutput).
 *   - Allowed callers: pre-#925 ledger residual rebuild
 *     (`applyHistoricalResidualOpenSet` / residual open-count decode for
 *     historical single-slice paper). Positive count → continue is resume
 *     compatibility only — not a second live court.
 *
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
 * **Single-slice historical residual paper → sole judge form** (#919 CR U3 / N4).
 *
 * Shared by runner normalize residual path, realBackend residual decode, and
 * route judgeStatusOf so escalate / positive-continue / non-positive-unusable
 * are one predicate — not three parallel arms.
 *
 * Scope: historical residual open-count paper only. Live family court never
 * closes on this projection (non-judge → unusable / cmr_failed). Live seats
 * emit T2 `kind:"judge"` tri-state directly.
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
 * (terminals → store flips; live keys only). Shared by the in-process continue
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
  readonly terminalDispositions: FindingDisposition[];
} | undefined {
  if (output.status !== "continue") return undefined;
  const dispositions = output.findingDispositions ?? [];
  const terminals = judgeTerminalsToLedgerDispositions(dispositions);
  const cargo = output.findings ?? [];
  const blocking = openFindingsForFixer(cargo, dispositions);
  const blockingIdentityKeys = liveFindingIdentityKeys(dispositions);
  return {
    blocking,
    blockingIdentityKeys,
    blockingFindingCount: blockingIdentityKeys.length,
    terminalDispositions: terminals,
  };
}

/**
 * #930 — family CMR court closure from the shared T2 judge tri-state only.
 *
 * One judgment function, two ordered courts (completeness / correctness). The
 * family path must NOT read open-count / findingsCount as a second closer.
 * Unusable / non-judge envelopes are fail-loud at the family court (#919 M1):
 * official typed re-furnace is seat-side SO re-ask — runner never invents a
 * clean pass and never routes bad shape through family coder-fix.
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
      readonly terminalDispositions: FindingDisposition[];
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
        terminalDispositions: projected?.terminalDispositions ?? [],
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
 * Thin wrapper over {@link priorJudgeVerdictRowsFromSources} (family source).
 * Shape matches single-slice {@link priorJudgeVerdictRowsFromLedger}.
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
): ReadonlyArray<PriorJudgeVerdictRow> {
  return priorJudgeVerdictRowsFromSources(
    ledger as ReadonlyArray<PriorJudgeLedgerEntry>,
    {
      sources: ["family"],
      ...(pass !== undefined ? { familyPass: pass } : {}),
    },
  );
}

/**
 * #966 — latest family-court session id from prior judge rows (ledger sole truth).
 * Only the newest row counts: empty / missing sessionId on that row means fresh
 * open (CR-10) — never resurrect an older conversation under a fresh-open row.
 */
export function familyJudgeResumeSessionIdFromPriorRows(
  rows: ReadonlyArray<Pick<PriorJudgeVerdictRow, "sessionId">>,
): string | undefined {
  if (rows.length === 0) return undefined;
  const sid = rows[rows.length - 1]?.sessionId;
  return typeof sid === "string" && sid.length > 0 ? sid : undefined;
}

/**
 * #919 AS4 — honest unusable residual open-count paper.
 *
 * Not a fixer/coder seat report. Route maps residual open-count 0 via
 * {@link projectResidualReviewerToJudge} → undefined → unusable → S5
 * (never silent clean, never `kind:"fixer"` placeholder).
 */
export function unusableResidualOpenCountPaper(): {
  readonly kind: "reviewer";
  readonly findingsCount: 0;
  readonly findings: readonly [];
} {
  return { kind: "reviewer", findingsCount: 0, findings: [] };
}

/**
 * #919 S1 — sole residual→judge seat projection used by both runner normalize
 * and route topology status collapse. Production decode already emits
 * `kind:"judge"`; residual open-count paper projects once here.
 *
 * #919 AS5: no `kind:"verify"+converged` arm on the judge seat. Online-review
 * S9 uses kind:verify on its own stage; S3/S6 fixtures must emit kind:judge.
 * Leftover verify paper on a judge seat stays as-is → unusable → S5.
 *
 * - kind:judge → as-is
 * - kind:reviewer residual → projectResidualReviewerToJudge or leave as-is
 * - else → as-is (caller maps unusable)
 */
export function projectJudgeSeatOutput(output: StepOutput): StepOutput {
  if (output.kind === "judge") return output;
  if (output.kind === "reviewer") {
    const projected = projectResidualReviewerToJudge(output);
    // Leave residual paper as-is when unusable → route → S5 / fail-loud.
    return projected ?? output;
  }
  return output;
}

/**
 * #919 S1 — sole judge-status collapse for topology (route) and callers that
 * only need the tri-state (+ unusable). Always goes through
 * {@link projectJudgeSeatOutput} first so normalize and status cannot drift.
 */
export function judgeStatusFromOutput(
  output: StepOutput | undefined,
): "converged" | "continue" | "escalate" | "unusable" {
  if (output == null) return "unusable";
  const projected = projectJudgeSeatOutput(output);
  if (projected.kind === "judge") {
    if (projected.status === "converged") return "converged";
    if (projected.status === "continue") return "continue";
    return "escalate";
  }
  return "unusable";
}

/**
 * #919 S2 / R7 — single judge-seat predicate for topology / decision_gate /
 * soul selection / receipt extract.
 *
 * Only S3/S6 are judge seats. Family online-review S9 (`verifyWorkerSpec`:
 * kind/role/soul `"verify"`) is **not** a judge — it keeps the verify receipt
 * channel, never the judge receipt tag.
 *
 * Seat identity is the step/id only. Never treat `kind|role|soul === "verify"`
 * alone as judge (that falsely claimed S9). Production S3/S6 specs use
 * role+soul `"verify"`; residual dual-spell `role:"reviewer"+soul:"verify"` on
 * S3/S6 still matches via the step/id arm. (`#923` only merged the model-route
 * *slot* into verify — not a forever pin that seat role must remain
 * `"reviewer"`. Leg soul `"reviewer"` is multi-model review-leg vocabulary only.)
 */
export function isJudgeSeat(input: {
  readonly step?: string;
  readonly id?: string;
}): boolean {
  // Seat identity is step/id only (#919 R4) — kind/role/soul are not consulted
  // (S9 online-review carries kind/role/soul "verify" and is NOT a judge seat).
  const seat = input.step ?? input.id;
  return seat === "S3" || seat === "S6";
}
