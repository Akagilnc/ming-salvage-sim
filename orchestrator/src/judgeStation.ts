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
import {
  OPEN_FINDING_STORE_STATUS,
  recordFindingStoreFlip,
  type FindingStoreStatus,
} from "./findingsStateStore.js";
import type {
  JudgeVerdict,
  LegalRefuseReason,
} from "./stationReceiptContracts.js";

// types.ts re-exports JudgeFindingDisposition from stationReceiptContracts
// (single source — #919 CR P3). No dual isomorphic import needed.
export type { LegalRefuseReason };

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
 * Push a successful store flip into the terminal ledger list, or fail loud.
 * Local to {@link judgeTerminalsToLedgerDispositions} (refute + suppress).
 */
function pushTerminalOrThrow(
  out: FindingDisposition[],
  written: ReturnType<typeof recordFindingStoreFlip>,
): void {
  if (!written.ok) {
    throw new Error(written.reason);
  }
  out.push(written.value);
}

/**
 * Map judge terminal dispositions to ledger findings-store flips:
 * - `refute` → `refuted` (#925)
 * - `suppress` → `suppressed` (#952; internal terminal, not public ABI)
 *
 * Live rows stay out of the terminal ledger flip set (they remain open).
 * Transitions go through {@link recordFindingStoreFlip} (single write-point
 * source — ADR 0129). Illegal store flips fail loud (throw with store reason).
 *
 * #952 R6-C2: `currentStoreStatusByIdentity` supplies the actual prior store
 * status as `from` when known. Absent key → treat as open (backward compat for
 * pure unit tests / first write). Production callers that accumulate store
 * rows must pass the map so illegal terminal→terminal morphs are rejected.
 */
export function judgeTerminalsToLedgerDispositions(
  dispositions: ReadonlyArray<JudgeFindingDisposition>,
  severity: Finding["severity"] = "medium",
  currentStoreStatusByIdentity?: Readonly<
    Partial<Record<string, FindingStoreStatus>>
  >,
  /**
   * #982: identity-keyed severity from cargo findings. Missing keys fall back
   * to the `severity` argument (default medium).
   */
  severityByIdentity?: Readonly<Partial<Record<string, Finding["severity"]>>>,
): FindingDisposition[] {
  const out: FindingDisposition[] = [];
  // Working copy so same-table sequential flips see prior terminal status
  // (illegal terminal→terminal morph fails loud; no open hardcode laundering).
  const known: Partial<Record<string, FindingStoreStatus>> = {
    ...(currentStoreStatusByIdentity ?? {}),
  };
  for (const d of dispositions) {
    const from = known[d.identityKey] ?? OPEN_FINDING_STORE_STATUS;
    const rowSeverity = severityByIdentity?.[d.identityKey] ?? severity;
    if (d.action === "refute") {
      pushTerminalOrThrow(
        out,
        recordFindingStoreFlip({
          identityKey: d.identityKey,
          from,
          to: "refuted",
          reason: `${d.reason}: ${d.evidence}`,
          severity: rowSeverity,
          source: "judge_kill",
          scope: d.reason,
        }),
      );
      known[d.identityKey] = "refuted";
      continue;
    }
    if (d.action === "suppress") {
      const groundKind =
        "groundTicket" in d && d.groundTicket !== undefined
          ? "groundTicket"
          : "ownerRecordPointer";
      const groundSource =
        groundKind === "groundTicket"
          ? `groundTicket:${d.groundTicket}`
          : d.ownerRecordPointer;
      pushTerminalOrThrow(
        out,
        recordFindingStoreFlip({
          identityKey: d.identityKey,
          from,
          to: "suppressed",
          reason: d.evidence,
          severity: rowSeverity,
          source: groundSource,
          scope: groundKind,
        }),
      );
      known[d.identityKey] = "suppressed";
    }
  }
  return out;
}

/**
 * Build identityKey → latest store status from accumulated ledger store rows.
 * Last row wins per key (mirrors live accumulation order).
 */
export function storeStatusByIdentityFromDispositions(
  storeRows: ReadonlyArray<{
    readonly identityKey: string;
    readonly status: FindingStoreStatus;
  }>,
): Partial<Record<string, FindingStoreStatus>> {
  const map: Partial<Record<string, FindingStoreStatus>> = {};
  for (const row of storeRows) {
    map[row.identityKey] = row.status;
  }
  return map;
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
 * status:continue projects **true empty** (0 live AND 0 terminal flips).
 * Terminal-only continue (0 live + non-empty refute/suppress flips) is court
 * closure via {@link isTerminalOnlyContinue} — not empty-spin (#952).
 */
export function openFindingsForFixer(
  findings: ReadonlyArray<Finding>,
  dispositions: ReadonlyArray<JudgeFindingDisposition>,
): Finding[] {
  const liveKeys = new Set(
    dispositions.filter((d) => d.action === "live").map((d) => d.identityKey),
  );
  // Cargo filter only: empty table / zero live keys → yield []. Topology
  // authorization: true empty continue fail-loud (M1/M6); terminal-only → close.
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
 * ADR 0138 / #978: never invent a residual placeholder `fixPacketBody`.
 * When historical paper already carries an authored non-empty body, pass it
 * through **verbatim** (transport only). When absent, omit the field — live
 * coder-fix edges fail loud via {@link requireFixPacketBody} /
 * {@link materializeLandingFixPacketBody}; do not synthesise runner cargo.
 *
 * Returns undefined when count is not a positive open-count (caller maps
 * zero / escalate / unusable separately).
 */
export function judgeContinueFromOpenCount(
  findingsCount: number,
  findings: ReadonlyArray<Finding> = [],
  fixPacketBody?: unknown,
): JudgeResult | undefined {
  if (
    typeof findingsCount !== "number" ||
    !Number.isSafeInteger(findingsCount) ||
    findingsCount <= 0
  ) {
    return undefined;
  }
  const cargo = [...findings];
  // Pass-through only — never invent residual placeholder bodies (ADR 0138).
  const authored =
    typeof fixPacketBody === "string" &&
    fixPacketBody.length > 0 &&
    fixPacketBody.trim().length > 0
      ? fixPacketBody
      : undefined;
  return {
    kind: "judge",
    status: "continue",
    findingDispositions: liveDispositionsForOpenCount(findingsCount, cargo),
    findings: cargo,
    ...(authored !== undefined ? { fixPacketBody: authored } : {}),
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
 * - positive open-count → continue (via {@link judgeContinueFromOpenCount});
 *   body only when residual paper already authored one (verbatim pass-through)
 * - zero / missing / non-integer → undefined (caller maps unusable; never silent clean)
 */
export function projectResidualReviewerToJudge(residual: {
  readonly findingsCount: number;
  readonly findings?: ReadonlyArray<Finding>;
  readonly escalate?: Escalation;
  /** Optional authored packet body already on residual paper — transport only. */
  readonly fixPacketBody?: unknown;
}): JudgeResult | undefined {
  if (residual.escalate !== undefined) {
    return mintJudgeEscalate(residual.escalate);
  }
  return judgeContinueFromOpenCount(
    residual.findingsCount,
    residual.findings ?? [],
    residual.fixPacketBody,
  );
}

/**
 * Live-path projection of a judge `continue` verdict into the S5 open set
 * (terminals → store flips; live keys only) plus optional ADR 0138 packet body.
 * Shared by the in-process continue edge and crash/resume ledger rebuild (F2).
 *
 * Packet content for coder-fix is {@link fixPacketBody} only — callers must
 * {@link requireFixPacketBody} (or the non-empty field here) before dispatch;
 * `blocking` findings cargo is residual/telemetry and is **not** the packet path.
 */
export function projectJudgeContinueBlocking(
  output: {
    readonly status: string;
    readonly findingDispositions?: ReadonlyArray<JudgeFindingDisposition>;
    readonly findings?: ReadonlyArray<Finding>;
    readonly fixPacketBody?: string;
  },
  /**
   * #952 R6-C2: prior store statuses (identityKey → status) for legal
   * transition checks. Production live/resume paths pass accumulated
   * findingDispositions via {@link storeStatusByIdentityFromDispositions}.
   */
  currentStoreStatusByIdentity?: Readonly<
    Partial<Record<string, FindingStoreStatus>>
  >,
): {
  readonly blocking: Finding[];
  readonly blockingIdentityKeys: string[];
  readonly blockingFindingCount: number;
  readonly terminalDispositions: FindingDisposition[];
  readonly fixPacketBody?: string;
} | undefined {
  if (output.status !== "continue") return undefined;
  const dispositions = output.findingDispositions ?? [];
  const cargo = output.findings ?? [];
  // #982: preserve cargo severity on terminal ledger flips (fallback medium).
  const severityByIdentity: Partial<Record<string, Finding["severity"]>> = {};
  for (const f of cargo) {
    severityByIdentity[findingIdentityKey(f)] = f.severity;
  }
  const terminals = judgeTerminalsToLedgerDispositions(
    dispositions,
    "medium",
    currentStoreStatusByIdentity,
    severityByIdentity,
  );
  const blocking = openFindingsForFixer(cargo, dispositions);
  const blockingIdentityKeys = liveFindingIdentityKeys(dispositions);
  const rawBody =
    typeof output.fixPacketBody === "string" ? output.fixPacketBody : undefined;
  return {
    blocking,
    blockingIdentityKeys,
    blockingFindingCount: blockingIdentityKeys.length,
    terminalDispositions: terminals,
    ...(rawBody !== undefined ? { fixPacketBody: rawBody } : {}),
  };
}

/**
 * #952 — terminal-only continue is court closure, not empty contract drift.
 *
 * Disposition-table pure check (no cargo walk / store flip): `status:continue`
 * with **0 live** AND **≥1 refute|suppress** means the judge finished the open
 * set by parking/killing everything — no fixer open set remains. Topology
 * routes like **converged** (single-slice S7 / family pass) after callers apply
 * flips. True empty continue (no live AND no terminals) remains fail-loud
 * (M1/M6). Prefer this over inventing a new public result/cause.
 *
 * Used by {@link judgeStatusFromOutput} so route never materializes cargo keys.
 */
export function isTerminalOnlyContinueDispositions(
  dispositions: ReadonlyArray<{ readonly action: string }> | undefined,
): boolean {
  const rows = dispositions ?? [];
  if (rows.length === 0) return false;
  let hasLive = false;
  let hasTerminal = false;
  for (const d of rows) {
    if (d.action === "live") hasLive = true;
    if (d.action === "refute" || d.action === "suppress") hasTerminal = true;
  }
  return !hasLive && hasTerminal;
}

/**
 * Projection form of {@link isTerminalOnlyContinueDispositions} for gates that
 * already hold {@link projectJudgeContinueBlocking} output.
 */
export function isTerminalOnlyContinue(projected: {
  readonly blockingFindingCount: number;
  readonly blockingIdentityKeys: ReadonlyArray<string>;
  readonly terminalDispositions: ReadonlyArray<unknown>;
}): boolean {
  return (
    projected.blockingFindingCount === 0 &&
    projected.blockingIdentityKeys.length === 0 &&
    projected.terminalDispositions.length > 0
  );
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
  /**
   * #952 R7-C1: prior findings-store statuses (identityKey → status) so
   * terminal→terminal morphs fail at the shared write point. Family production
   * builds this from ledger prior schema dispositions (refute→refuted,
   * suppress→suppressed) via {@link storeStatusByIdentityFromDispositions}.
   * Absent → treat as open (backward compat for pure unit tests / first write).
   */
  currentStoreStatusByIdentity?: Readonly<
    Partial<Record<string, FindingStoreStatus>>
  >,
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
      const dispositions = Array.isArray(rec.findingDispositions)
        ? (rec.findingDispositions as ReadonlyArray<JudgeFindingDisposition>)
        : undefined;
      const findings = Array.isArray(rec.findings)
        ? (rec.findings as ReadonlyArray<Finding>)
        : undefined;
      const fixPacketBody =
        typeof rec.fixPacketBody === "string" ? rec.fixPacketBody : undefined;
      // #952 R7-C1: thread real prior store `from` (mirrors runner/residual R6-C2).
      const projected = projectJudgeContinueBlocking(
        {
          status: "continue",
          findingDispositions: dispositions,
          findings,
          ...(fixPacketBody !== undefined ? { fixPacketBody } : {}),
        },
        currentStoreStatusByIdentity,
      );
      // #952: 0 live + non-empty terminal flips = court closed (like converged).
      // True empty continue stays `continue` with empty open set for the M1 gate.
      if (projected !== undefined && isTerminalOnlyContinue(projected)) {
        return { action: "pass" };
      }
      return {
        action: "continue",
        blocking: projected?.blocking ?? [],
        blockingIdentityKeys: projected?.blockingIdentityKeys ?? [],
        blockingFindingCount: projected?.blockingFindingCount ?? 0,
        terminalDispositions: projected?.terminalDispositions ?? [],
        ...(projected?.fixPacketBody !== undefined
          ? { fixPacketBody: projected.fixPacketBody }
          : fixPacketBody !== undefined
            ? { fixPacketBody }
            : {}),
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
    if (projected.status === "continue") {
      // #952: terminal-only continue (suppress/refute flips, 0 live) routes like
      // converged so single-slice S7 / resume do not empty-spin S5. Envelope
      // status string stays `continue` on the ledger for queryable flips.
      // Disposition-table only — never walk findings cargo here (opaque/residual
      // rows must not crash topology; store flips stay on the live gate).
      if (isTerminalOnlyContinueDispositions(projected.findingDispositions)) {
        return "converged";
      }
      return "continue";
    }
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
 * - judge-seat step with sessionId (S3/S6) → open (continuity refresh)
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
    // Pure agent rows (event undefined) still refresh open continuity.
    if (
      entry.event === undefined &&
      isJudgeSeat({ step: entry.step }) &&
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
