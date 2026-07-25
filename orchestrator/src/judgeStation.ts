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
  JudgeFindingDisposition,
  JudgeResult,
  JudgeVerdictStatus,
  LedgerEntry,
  StepOutput,
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
 * Review legs requested by the judge are Runner-dispatched fresh sessions
 * (#1126 / #1094 one mechanism). Resume is illegal (negative AC: 续腿不合法).
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
  return (
    value === "converged" ||
    value === "continue" ||
    value === "escalate" ||
    value === "toolchain"
  );
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
      // Slice steps never carry family event markers. Dual-field fold rows
      // (output + court_dismissed on converge) still carry judge topology
      // output — read them as prior verdicts (event filter alone would drop them).
      const seatStep = entry.step;
      if (
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
  if (verdict.status === "toolchain") {
    // #1027 FINAL / ADR 0145: toolchain terminal carries doorbell cargo but is
    // NOT a decision-gate park — no `escalate` mirror (route() must not treat it
    // as a human park). Fate is the runner's verify_failed fallback.
    return {
      kind: "judge",
      status: "toolchain",
      reason: verdict.reason,
      diagnosis: verdict.diagnosis,
    };
  }
  // continue — ADR 0138: fixPacketBody is traffic on the envelope; cargo may
  // still ride findings siblings but is never the coder-fix packet path.
  return {
    kind: "judge",
    status: "continue",
    findingDispositions: verdict.findingDispositions,
    fixPacketBody: verdict.fixPacketBody,
    ...(verdict.advanceCoder !== undefined
      ? { advanceCoder: verdict.advanceCoder }
      : {}),
    ...(findingsCargo !== undefined ? { findings: findingsCargo } : {}),
  };
}

/**
 * ADR 0138 — sole coder-fix packet body path: judge continue `fixPacketBody`,
 * verbatim. Missing / empty is loud failure; never fall back to bare findings.
 *
 * Runner topology may still read disposition identity keys as thin control
 * envelope; this helper never reads findings cargo for packet content.
 */
export function requireFixPacketBody(output: {
  readonly status?: string;
  readonly fixPacketBody?: unknown;
}): string {
  if (output.status !== "continue") {
    throw new Error(
      "fixPacketBody is only authorized on judge status:continue (ADR 0138)",
    );
  }
  if (typeof output.fixPacketBody !== "string") {
    throw new Error(
      "judge continue missing fixPacketBody (ADR 0138; no bare-findings fallback)",
    );
  }
  // Verbatim transport: do not rewrite whitespace. Empty / whitespace-only is
  // contract drift (same fail-loud class as empty live set).
  if (
    output.fixPacketBody.length === 0 ||
    output.fixPacketBody.trim().length === 0
  ) {
    throw new Error(
      "judge continue fixPacketBody is empty (ADR 0138; no bare-findings fallback)",
    );
  }
  return output.fixPacketBody;
}

/**
 * ADR 0138 / #978 — single helper for coder-fix landing writers (single-slice
 * `dispatchWorker` + family `writeFamilyFixFindingsFile`).
 *
 * - Present non-empty body → return **verbatim** (no trim rewrite).
 * - Open set present (keys length > 0 or count > 0) without usable body and
 *   `requireBodyWhenOpen` (default true for coder-fix) → fail loud (no
 *   soft-omit second channel).
 * - No open set / keys-only re-adjudicate (`requireBodyWhenOpen: false`) /
 *   raw-artifacts-only → `undefined` (not a fixer content packet).
 */
export function materializeLandingFixPacketBody(input: {
  readonly fixPacketBody?: unknown;
  readonly blockingFindingIdentityKeys?: readonly string[];
  readonly blockingFindingCount?: number;
  /**
   * Coder-fix content landings default true. S6 judge re-adjudicate landings
   * that carry identity keys without a fix packet set this false.
   */
  readonly requireBodyWhenOpen?: boolean;
}): string | undefined {
  const keysLen = input.blockingFindingIdentityKeys?.length ?? 0;
  const count = input.blockingFindingCount ?? 0;
  const hasOpenSet = keysLen > 0 || count > 0;
  const requireBody = input.requireBodyWhenOpen !== false;
  const raw =
    typeof input.fixPacketBody === "string" ? input.fixPacketBody : undefined;
  const usable =
    raw !== undefined && raw.length > 0 && raw.trim().length > 0
      ? raw
      : undefined;
  if (usable !== undefined) return usable;
  if (hasOpenSet && requireBody) {
    throw new Error(
      "coder-fix landing missing non-empty fixPacketBody with live open set " +
        "(ADR 0138; no bare-findings fallback / no soft-omit)",
    );
  }
  return undefined;
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
      /** ADR 0138: judge-authored packet body (required before coder-fix). */
      readonly fixPacketBody?: string;
    }
  | {
      readonly action: "escalate";
      readonly reason: string;
      readonly diagnosis: string;
    }
  | {
      // #1027 FINAL / ADR 0145: judge classified a red wave-verify as a
      // toolchain/environment failure → runner falls back to verify_failed
      // (no coder-fix loop, no decision-gate park).
      readonly action: "toolchain";
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
    readonly fixPacketBody?: unknown;
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
      const fixPacketBody =
        typeof rec.fixPacketBody === "string" ? rec.fixPacketBody : undefined;
      return {
        action: "continue",
        ...(fixPacketBody !== undefined ? { fixPacketBody } : {}),
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
    if (status === "toolchain") {
      // #1027 S1: dedicated toolchain terminal — do NOT fold into pass/continue.
      // Doorbell cargo mirrors escalate shape; fate (verify_failed) differs.
      const reason =
        (typeof rec.reason === "string" ? rec.reason : undefined) ??
        "family judge toolchain";
      const diagnosis =
        (typeof rec.diagnosis === "string" ? rec.diagnosis : undefined) ??
        "judge declared toolchain/environment red";
      return { action: "toolchain", reason, diagnosis };
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
    if (projected.status === "escalate") return "escalate";
    // toolchain (#1027 S1): single-slice S3/S6 has no wave-verify triage
    // scenario. Never silent-clean (converged/S7) and never mis-route as a
    // decision-gate park — collapse to the loud unusable edge (→ S5), the
    // established "this court cannot close on this envelope" signal.
    return "unusable";
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

// ─── #1081 / ADR 0147 resident judge lifecycle (birth at dispatch → dismiss) ─

/** Versioned open-court prompt (slice dispatch birth; not a topology 拍). */
export const JUDGE_OPEN_COURT_PROMPT_FILE = "judge_open_court.md";

/**
 * True when this worker is the S1 open-court birth dispatch (not S3/S6
 * judging). Distinguished solely by prompt file — zero new StepId.
 */
export function isJudgeOpenCourtSpec(input: {
  readonly promptFile?: string;
}): boolean {
  return input.promptFile === JUDGE_OPEN_COURT_PROMPT_FILE;
}

/**
 * Judge-receipt path for production SO: topology seats (S3/S6) **or** the
 * open-court birth dispatch. Family S9 online-review stays out.
 */
export function usesJudgeReceiptChannel(input: {
  readonly step?: string;
  readonly id?: string;
  readonly promptFile?: string;
}): boolean {
  return isJudgeSeat(input) || isJudgeOpenCourtSpec(input);
}

/** Resident-judge lifecycle state rebuilt from the durable ledger. */
export type ResidentJudgeLifecycle =
  | { readonly status: "absent" }
  | {
      readonly status: "open";
      readonly sessionId: string;
      readonly modelSlug: string;
    }
  | { readonly status: "dismissed" };

type ResidentJudgeLedgerRow = {
  readonly event?: string;
  readonly step?: string;
  readonly runId?: string;
  readonly sessionId?: string;
  readonly modelSlug?: string;
  /** Topology output when present (judge converge heals dismiss crash window). */
  readonly output?: StepOutput | { readonly kind?: string };
};

/**
 * Rebuild resident-judge lifecycle from ledger sole truth (#1081).
 *
 * Scan newest→oldest:
 * - `court_dismissed` → dismissed (no residual resumeable session)
 * - `court_opened` with sessionId → open (birth at dispatch)
 * - judge-seat verdict with sessionId (S3/S6) → open (continuity refresh)
 * - else → absent
 *
 * Heal (pre-atomic two-write crash window): when `court_opened` is present, a
 * later judge seat product-converged, and no `court_dismissed` was recorded,
 * treat as dismissed so a crash between converge write and dismiss write cannot
 * leave a permanently hanging court after full completion.
 *
 * Bookkeeping `session_continuity_lost` on a **judge seat** does not resurrect
 * a dropped id. Coder-seat continuity losses (S2/S5) must NOT orphan an open
 * court — only judge seats write judge continuity loss post-#1081, and pre-#1081
 * migration ledgers may still carry judge-seat rows.
 */
export function rebuildResidentJudgeFromLedger(
  ledger: ReadonlyArray<ResidentJudgeLedgerRow>,
): ResidentJudgeLifecycle {
  // Heal pass: product converge after open court without an explicit dismiss
  // row → dismissed (atomic fold writes event on the same row; this covers
  // residual two-write crash ledgers).
  let sawCourtOpened = false;
  let sawDismiss = false;
  let sawProductConvergeAfterOpen = false;
  for (const entry of ledger) {
    if (entry.event === "court_dismissed") {
      sawDismiss = true;
    }
    if (
      entry.event === "court_opened" &&
      typeof entry.sessionId === "string" &&
      entry.sessionId.length > 0
    ) {
      sawCourtOpened = true;
    }
    if (
      sawCourtOpened &&
      !sawDismiss &&
      isJudgeSeat({ step: entry.step }) &&
      entry.output !== undefined &&
      judgeStatusFromOutput(entry.output as StepOutput) === "converged"
    ) {
      sawProductConvergeAfterOpen = true;
    }
  }
  if (sawCourtOpened && sawProductConvergeAfterOpen && !sawDismiss) {
    return { status: "dismissed" };
  }

  for (let i = ledger.length - 1; i >= 0; i -= 1) {
    const entry = ledger[i]!;
    if (entry.event === "court_dismissed") {
      return { status: "dismissed" };
    }
    if (
      entry.event === "session_continuity_lost" &&
      isJudgeSeat({ step: entry.step })
    ) {
      // Judge continuity abandoned; do not revive the dropped id from older rows.
      return { status: "absent" };
    }
    if (
      entry.event === "court_opened" &&
      typeof entry.sessionId === "string" &&
      entry.sessionId.length > 0
    ) {
      return {
        status: "open",
        sessionId: entry.sessionId,
        modelSlug:
          typeof entry.modelSlug === "string" && entry.modelSlug.length > 0
            ? entry.modelSlug
            : "unknown",
      };
    }
    // Agent steps may fold court_dismissed onto the same durable row as
    // topology output (event set + output present). Those are handled above.
    // Pure agent rows (event undefined) refresh open continuity only when they
    // carry an actual judge verdict. Failed dispatch residues can carry the
    // runner/monitor session id without any judge output; they are not session
    // authority.
    if (
      entry.event === undefined &&
      isJudgeSeat({ step: entry.step }) &&
      entry.output?.kind === "judge" &&
      typeof entry.sessionId === "string" &&
      entry.sessionId.length > 0 &&
      entry.sessionId !== entry.runId
    ) {
      return {
        status: "open",
        sessionId: entry.sessionId,
        modelSlug:
          typeof entry.modelSlug === "string" && entry.modelSlug.length > 0
            ? entry.modelSlug
            : "unknown",
      };
    }
  }
  return { status: "absent" };
}

/**
 * Resolve how a judging seat (S3/S6) must open.
 *
 * #1081 AC: when the court is **open**, resume is mandatory — never silent
 * fresh-per-round. Create/resume failure is loud.
 *
 * Legal `establish` (fresh) paths only (both require a resume-capable seat —
 * same gate as {@link requireOpenCourtSession}; never mint a "resident" judge
 * under a provider that cannot resume later rounds):
 * - court never opened (absent) — S1 birth missed (crash before court_opened,
 *   or pre-#1081 ledger re-feed); first S3 births the resident session
 * - verify model changed under an open court (quota relay) — re-birth under
 *   the new seat model (old session cannot cross models)
 *
 * Open + same model + not resume-capable → **fail** (AC#3: no silent fresh
 * while court is open; matches runner resumeFor judge provider_incapable path).
 *
 * `dismissed` always fails (no hanging resumeable session after converge).
 */
export function requireResidentJudgeResume(input: {
  readonly lifecycle: ResidentJudgeLifecycle;
  readonly seatModel: string;
  readonly seatResumeCapable: boolean;
}):
  | { readonly kind: "resume"; readonly sessionId: string }
  | { readonly kind: "establish" }
  | { readonly kind: "fail"; readonly reason: string } {
  const { lifecycle, seatModel, seatResumeCapable } = input;
  if (lifecycle.status === "dismissed") {
    return {
      kind: "fail",
      reason:
        "resident judge court is dismissed; judging seat cannot reopen a " +
        "hanging session (court_dismissed is terminal for this slice run)",
    };
  }
  if (lifecycle.status === "absent") {
    // Birth at S1 is the normal path; establish here is the crash/migration
    // fallback when court_opened was never recorded. Fail loud when the seat
    // cannot resume — same as open-court gate (no silent non-resident mint).
    if (!seatResumeCapable) {
      return {
        kind: "fail",
        reason:
          `resident judge establish refused: seat model ${seatModel} is not ` +
          "resume-capable (resident judge requires resume across judging rounds); " +
          "silent fresh-per-round judge is illegal",
      };
    }
    return { kind: "establish" };
  }
  // lifecycle.status === "open"
  if (
    lifecycle.modelSlug !== "unknown" &&
    lifecycle.modelSlug !== seatModel
  ) {
    // Verify-seat model moved (e.g. quota relay) — re-birth under the new seat.
    // New seat must still be resume-capable or we fail at create time.
    if (!seatResumeCapable) {
      return {
        kind: "fail",
        reason:
          `resident judge re-establish refused: seat model ${seatModel} is not ` +
          "resume-capable (cannot re-birth resident court under an incapable seat); " +
          "silent fresh-per-round judge is illegal",
      };
    }
    return { kind: "establish" };
  }
  if (!seatResumeCapable) {
    // AC#3 / resumeFor judge path: open same-model court + provider incapable
    // must fail loud — never silent-establish a fresh per-round judge.
    return {
      kind: "fail",
      reason:
        `resident judge resume refused: seat model ${seatModel} is not ` +
        "resume-capable (provider cannot continue the open-court session); " +
        "silent fresh judge is illegal",
    };
  }
  return { kind: "resume", sessionId: lifecycle.sessionId };
}

/**
 * Validate open-court birth result. Fail loud when the worker did not surface
 * a real session id (no silent proceed to S2 without a resident judge).
 */
export function requireOpenCourtSession(input: {
  readonly resultKind: string;
  readonly sessionId?: string;
  readonly seatResumeCapable: boolean;
  readonly seatModel: string;
}):
  | { readonly kind: "ok"; readonly sessionId: string }
  | { readonly kind: "fail"; readonly reason: string } {
  if (!input.seatResumeCapable) {
    return {
      kind: "fail",
      reason:
        `open court refused: seat model ${input.seatModel} is not ` +
        "resume-capable (resident judge requires resume across judging rounds)",
    };
  }
  if (input.resultKind !== "completed") {
    return {
      kind: "fail",
      reason: `open court worker failed (${input.resultKind}); resident judge not established`,
    };
  }
  if (typeof input.sessionId !== "string" || input.sessionId.length === 0) {
    return {
      kind: "fail",
      reason:
        "open court completed without a session id; cannot establish " +
        "resident judge continuity (silent fresh-per-round is illegal)",
    };
  }
  return { kind: "ok", sessionId: input.sessionId };
}
