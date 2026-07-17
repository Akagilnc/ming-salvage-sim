/**
 * #921 — Judge verdict + full-wave station completion thin envelope contracts.
 *
 * Pure-function prefactor for #919 (PRD) / ADR 0132. Later slices (#924/#925/#927)
 * wire these schemas into sandcastle typed output and runner topology; this module
 * does not touch the runner.
 *
 * ## Envelope boundary
 *
 * Worker / station receipt schemas validate only:
 *   1. routing / completion-status traffic signals
 *   2. identity keys of findings involved
 *   3. cargo pointers (opaque path / URI)
 *
 * They do **not** open or schema-check cargo body prose. Four legal refuse
 * reasons + evidence are validated only on the **judge finding-disposition table**
 * (and later by the judge when reading cargo). Coder refuse cargo is opaque.
 *
 * ## Field vocabulary (canonical unique — envelope field level)
 *
 * - Positive family: `refused*` (`status: "refused"`, `refusedFindingIdentityKeys`)
 * - Rejected spellings: any envelope key matching `^refuted` (e.g.
 *   `refutedFindingIdentityKeys`) — invented dual-field compatibility is banned
 * - Findings-store terminal flips `refuted` / `suppressed` (ADR 0129 / #952)
 *   are a **different layer**: judge dispositions use `action: "refute"` /
 *   `action: "suppress"` here and later map to those store flips; the envelope
 *   traffic signal stays `refused*`
 *
 * ## Stations colocated here (no parallel contract directory)
 *
 * `judge` | `coder` | `coderFix` | `familyCoderFix` | `ship` |
 * `merger` | `onlineReview`
 *
 * Shared traffic fields: `station`, `status`, optional `cargoPointer`.
 * Per-station extras stay on the same thin envelope (e.g. refuse keys, advanceCoder).
 * Thin gate seats (merger / onlineReview): completed | escalate only.
 */

import { z } from "zod";

/** Local JSON-safe structural clone (no third-party dep; encode only). */
function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

// ─── Result type (never throw bare exceptions from decode/parse) ─────────────

/**
 * Decode / validate result. Callers branch on `ok` — parsers never throw for
 * shape failures (garbage in → readable `reason` out).
 */
export type ContractResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly reason: string };

function ok<T>(value: T): ContractResult<T> {
  return { ok: true, value };
}

function fail(reason: string): ContractResult<never> {
  return { ok: false, reason };
}

function zodFail(prefix: string, err: z.ZodError): ContractResult<never> {
  const detail = err.issues
    .map((i) => {
      const path = i.path.length > 0 ? i.path.join(".") : "(root)";
      return `${path}: ${i.message}`;
    })
    .join("; ");
  return fail(`${prefix}: ${detail}`);
}

// ─── Four legal refuse / kill reasons (global rule 16 / ADR 0132) ────────────

/**
 * Canonical machine tokens for the four legal kill/refuse reasons.
 *
 * Definitions are single-sourced in the container-global home CLAUDE.md
 * (`image/home/CLAUDE.md` §finding 裁决法理, #947) — do not restate them here.
 *
 * Aligns with ADR 0130 fixer second-gate refuse channel: same four reasons,
 * different seat (judge kill table vs fixer refuse). Hard-to-fix is never a reason.
 */
export const LEGAL_REFUSE_REASONS = [
  "unconstitutional",
  "over_defense",
  "not_established",
  "scope_creep",
] as const;

export type LegalRefuseReason = (typeof LEGAL_REFUSE_REASONS)[number];

const legalRefuseReasonSchema = z.enum(LEGAL_REFUSE_REASONS);

/** Parse one four-reason token; invents are rejected with a readable reason. */
export function parseLegalRefuseReason(
  raw: unknown,
): ContractResult<LegalRefuseReason> {
  const parsed = legalRefuseReasonSchema.safeParse(raw);
  if (!parsed.success) {
    return fail(
      `illegal refuse reason (expected one of ${LEGAL_REFUSE_REASONS.join("|")}): ${String(raw)}`,
    );
  }
  return ok(parsed.data);
}

// ─── Stations ────────────────────────────────────────────────────────────────

/**
 * Full-wave stations that complete via a thin typed receipt envelope.
 * Colocated by design — do not invent a parallel contracts/ directory.
 */
export const STATION_IDS = [
  "judge",
  "coder",
  "coderFix",
  "familyCoderFix",
  "ship",
  "merger",
  "onlineReview",
] as const;

export type StationId = (typeof STATION_IDS)[number];

/** Coder-family stations share the same refuse / completed / escalate traffic. */
export const CODER_STATION_IDS = [
  "coder",
  "coderFix",
  "familyCoderFix",
] as const;

export type CoderStationId = (typeof CODER_STATION_IDS)[number];

// ─── Banned envelope spellings (refuted* dual-field ban) ─────────────────────

/**
 * Envelope field names that look like invent-spellings of the refuse vocabulary.
 * Findings-store status `refuted` is not an envelope field — it never appears here.
 */
const BANNED_REFUTED_KEY = /^refuted/i;

function bannedRefutedKeys(record: Record<string, unknown>): string[] {
  return Object.keys(record).filter((k) => BANNED_REFUTED_KEY.test(k));
}

/**
 * Reject envelopes that carry any `refuted*` field name (canonical is `refused*`).
 * Dual refused*+refuted* is also rejected — no compatibility shims.
 */
function rejectBannedEnvelopeVocabulary(
  record: Record<string, unknown>,
): ContractResult<true> {
  const banned = bannedRefutedKeys(record);
  if (banned.length === 0) return ok(true);
  return fail(
    `canonical envelope vocabulary is refused* only; banned refuted* field(s): ${banned.join(", ")}` +
      (record.refusedFindingIdentityKeys !== undefined
        ? " (dual refused*+refuted* fields are forbidden)"
        : ""),
  );
}

function asRecord(raw: unknown): ContractResult<Record<string, unknown>> {
  if (raw === null || raw === undefined) {
    return fail("envelope must be a non-null object");
  }
  if (typeof raw !== "object" || Array.isArray(raw)) {
    return fail(`envelope must be an object, got ${Array.isArray(raw) ? "array" : typeof raw}`);
  }
  return ok(raw as Record<string, unknown>);
}

const nonEmptyString = z.string().trim().min(1);

/** Optional cargo pointer: absent/undefined ok; empty string rejected. */
const cargoPointerSchema = nonEmptyString.optional();

// ─── Finding disposition table (judge-side) ──────────────────────────────────

/**
 * Judge kill row: refute this finding under one of the four legal reasons,
 * with evidence. Maps later to findings-store terminal flip `refuted` (ADR 0130)
 * — that store status is not an envelope field.
 */
export interface JudgeKillDisposition {
  readonly identityKey: string;
  readonly action: "refute";
  /** One of {@link LEGAL_REFUSE_REASONS}. */
  readonly reason: LegalRefuseReason;
  /** Non-empty evidence string the judge records for audit. */
  readonly evidence: string;
}

/** Live finding row: still open for fix; no reason/evidence on the envelope. */
export interface JudgeLiveDisposition {
  readonly identityKey: string;
  readonly action: "live";
}

/**
 * Judge suppress row (#952): park a finding as internal terminal `suppressed`
 * in the findings state store (not a public result / cause).
 *
 * Shape only: non-empty `evidence` + exactly one ground —
 * `groundTicket` (numeric issue number) XOR `ownerRecordPointer` (owner batch
 * pointer). Ground authenticity is the judge's authority, not this schema.
 *
 * Vocabulary boundary (#952 4b): this `action: "suppress"` + store status
 * `suppressed` is the **judge / findings-store seam**. It is **not** the CMR
 * reviewer governance carrier `accepted_suppressed` ({@link FindingDispositionKind}
 * in types.ts / priorFindingDispositions prompts). Do not alias the three
 * tokens; cross-comments live at both type definitions.
 */
export type JudgeSuppressDisposition =
  | {
      readonly identityKey: string;
      readonly action: "suppress";
      readonly evidence: string;
      readonly groundTicket: number;
      readonly ownerRecordPointer?: never;
    }
  | {
      readonly identityKey: string;
      readonly action: "suppress";
      readonly evidence: string;
      readonly ownerRecordPointer: string;
      readonly groundTicket?: never;
    };

export type JudgeFindingDisposition =
  | JudgeKillDisposition
  | JudgeLiveDisposition
  | JudgeSuppressDisposition;

const killDispositionSchema = z
  .object({
    identityKey: nonEmptyString,
    action: z.literal("refute"),
    reason: legalRefuseReasonSchema,
    evidence: nonEmptyString,
  })
  .strict();

const liveDispositionSchema = z
  .object({
    identityKey: nonEmptyString,
    action: z.literal("live"),
  })
  .strict();

const suppressWithTicketSchema = z
  .object({
    identityKey: nonEmptyString,
    action: z.literal("suppress"),
    evidence: nonEmptyString,
    groundTicket: z.number().int().positive(),
  })
  .strict();

const suppressWithOwnerPointerSchema = z
  .object({
    identityKey: nonEmptyString,
    action: z.literal("suppress"),
    evidence: nonEmptyString,
    ownerRecordPointer: nonEmptyString,
  })
  .strict();

/**
 * Parse one finding disposition row.
 *
 * Kill rows validate the four-reason enum + non-empty evidence.
 * Live rows reject smuggled `reason` / `evidence` keys (strict).
 * Suppress rows (#952) require non-empty evidence + exactly one ground
 * (`groundTicket` XOR `ownerRecordPointer`); invent `reason` fields fail strict.
 *
 * Sole validation path for disposition rows — used both by the public parser
 * and by {@link decodeJudgeVerdict} so nested continue tables never surface
 * bare Zod union "Invalid input" (AC: 可读原因).
 */
export function parseFindingDisposition(
  raw: unknown,
): ContractResult<JudgeFindingDisposition> {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return fail(
      `finding disposition must be an object, got ${Array.isArray(raw) ? "array" : typeof raw}`,
    );
  }
  const rec = raw as Record<string, unknown>;
  const action = rec.action;

  if (action === "live") {
    if (rec.reason !== undefined || rec.evidence !== undefined) {
      return fail(
        "live disposition must not carry reason/evidence (only refute/suppress terminals do)",
      );
    }
    const parsed = liveDispositionSchema.safeParse(rec);
    if (!parsed.success) return zodFail("finding disposition", parsed.error);
    return ok(parsed.data);
  }

  if (action === "refute") {
    // Surface reason/evidence failures with explicit field names (union "Invalid
    // input" is not readable enough for AC "可读原因").
    if (typeof rec.identityKey !== "string" || rec.identityKey.trim().length === 0) {
      return fail("finding disposition identityKey must be a non-empty string");
    }
    const reasonResult = parseLegalRefuseReason(rec.reason);
    if (!reasonResult.ok) {
      return fail(`finding disposition reason: ${reasonResult.reason}`);
    }
    if (typeof rec.evidence !== "string" || rec.evidence.trim().length === 0) {
      return fail("finding disposition evidence must be a non-empty string");
    }
    const parsed = killDispositionSchema.safeParse(rec);
    if (!parsed.success) return zodFail("finding disposition", parsed.error);
    return ok(parsed.data);
  }

  if (action === "suppress") {
    if (typeof rec.identityKey !== "string" || rec.identityKey.trim().length === 0) {
      return fail("finding disposition identityKey must be a non-empty string");
    }
    if (typeof rec.evidence !== "string" || rec.evidence.trim().length === 0) {
      return fail("finding disposition evidence must be a non-empty string");
    }
    if (rec.reason !== undefined) {
      return fail(
        "suppress disposition must not invent a reason field (use evidence + groundTicket|ownerRecordPointer only)",
      );
    }
    const hasTicket = rec.groundTicket !== undefined;
    const hasPointer = rec.ownerRecordPointer !== undefined;
    if (!hasTicket && !hasPointer) {
      return fail(
        "suppress disposition requires exactly one ground: groundTicket or ownerRecordPointer",
      );
    }
    if (hasTicket && hasPointer) {
      return fail(
        "suppress disposition requires exactly one ground; dual groundTicket+ownerRecordPointer is forbidden",
      );
    }
    if (hasTicket) {
      const parsed = suppressWithTicketSchema.safeParse(rec);
      if (!parsed.success) return zodFail("finding disposition", parsed.error);
      return ok(parsed.data as JudgeSuppressDisposition);
    }
    const parsed = suppressWithOwnerPointerSchema.safeParse(rec);
    if (!parsed.success) return zodFail("finding disposition", parsed.error);
    return ok(parsed.data as JudgeSuppressDisposition);
  }

  return fail(
    `finding disposition action must be refute|live|suppress, got ${String(action)}`,
  );
}
/**
 * Zod adapter around {@link parseFindingDisposition}: keeps continue-verdict
 * arrays on one validation path with readable issue messages (no bare union).
 */
const findingDispositionSchema: z.ZodType<JudgeFindingDisposition> = z
  .unknown()
  .transform((val, ctx) => {
    const result = parseFindingDisposition(val);
    if (!result.ok) {
      ctx.addIssue({ code: "custom", message: result.reason });
      return z.NEVER;
    }
    return result.value;
  });

// ─── Judge verdict (three states) ────────────────────────────────────────────

/**
 * Judge verdict status tokens — the sole convergence signal after #919
 * (replaces open-count mechanical closure).
 */
export type JudgeVerdictStatus = "converged" | "continue" | "escalate";

interface JudgeEnvelopeBase {
  readonly station: "judge";
  /** Opaque cargo pointer; body is never schema-checked here. */
  readonly cargoPointer?: string;
}

/** Convergence: no further fix rounds. */
export interface JudgeVerdictConverged extends JudgeEnvelopeBase {
  readonly status: "converged";
}

/**
 * Continue the fix loop. May carry:
 * - `findingDispositions` — terminal rows (`refute`→store `refuted`,
 *   `suppress`→store `suppressed`) plus `live` rows for the fixer open set
 * - `advanceCoder` — suggestion to switch coder roster entry (runner still
 *   owns the stay-put fallback when the target is unusable — #926)
 */
export interface JudgeVerdictContinue extends JudgeEnvelopeBase {
  readonly status: "continue";
  readonly findingDispositions: readonly JudgeFindingDisposition[];
  readonly advanceCoder?: string;
}

/**
 * Escalate via the existing decision-gate park path (no new escalate channel).
 * `reason` + `diagnosis` are the doorbell cargo (same shape as worker escalate).
 */
export interface JudgeVerdictEscalate extends JudgeEnvelopeBase {
  readonly status: "escalate";
  readonly reason: string;
  readonly diagnosis: string;
}

export type JudgeVerdict =
  | JudgeVerdictConverged
  | JudgeVerdictContinue
  | JudgeVerdictEscalate;

/**
 * Single field vocabulary for judge envelopes. Decode uses `.strict()`;
 * Sandcastle SO uses `.passthrough()` + banned-key superRefine — never two
 * independent field tables that can drift.
 */
const judgeConvergedFields = {
  station: z.literal("judge"),
  status: z.literal("converged"),
  cargoPointer: cargoPointerSchema,
} as const;

const judgeContinueFields = {
  station: z.literal("judge"),
  status: z.literal("continue"),
  findingDispositions: z.array(findingDispositionSchema),
  advanceCoder: nonEmptyString.optional(),
  cargoPointer: cargoPointerSchema,
} as const;

const judgeEscalateFields = {
  station: z.literal("judge"),
  status: z.literal("escalate"),
  reason: nonEmptyString,
  diagnosis: nonEmptyString,
  cargoPointer: cargoPointerSchema,
} as const;

function judgeDecodeObject<T extends z.ZodRawShape>(shape: T) {
  return z.object(shape).strict();
}

function judgeSoObject<T extends z.ZodRawShape>(shape: T) {
  return z
    .object(shape)
    .passthrough()
    .superRefine((value, ctx) => {
      rejectBannedRefutedKeysInSo(value as Record<string, unknown>, ctx);
    });
}

const judgeConvergedSchema = judgeDecodeObject(judgeConvergedFields);
const judgeContinueSchema = judgeDecodeObject(judgeContinueFields);
const judgeEscalateSchema = judgeDecodeObject(judgeEscalateFields);

const judgeVerdictSchema = z.discriminatedUnion("status", [
  judgeConvergedSchema,
  judgeContinueSchema,
  judgeEscalateSchema,
]);

/** Encode a validated judge verdict into its canonical JSON shape. */
export function encodeJudgeVerdict(verdict: JudgeVerdict): JudgeVerdict {
  // Already typed; return a plain JSON-safe clone of the canonical shape.
  return cloneJson(verdict);
}

/** Decode + validate a judge verdict envelope. Never throws on bad shape. */
export function decodeJudgeVerdict(raw: unknown): ContractResult<JudgeVerdict> {
  const record = asRecord(raw);
  if (!record.ok) return record;
  const banned = rejectBannedEnvelopeVocabulary(record.value);
  if (!banned.ok) return banned;
  const parsed = judgeVerdictSchema.safeParse(record.value);
  if (!parsed.success) {
    return zodFail("judge verdict", parsed.error);
  }
  return ok(parsed.data);
}

/**
 * Sandcastle `Output.object` tag for judge station receipts (#925).
 * Traffic fields are schema-validated; findings cargo siblings may passthrough.
 */
export const JUDGE_RECEIPT_TAG = "judge";

/**
 * Production SO schema for the S3/S6 judge station receipt.
 *
 * Field vocabulary is shared with {@link decodeJudgeVerdict} via the judge*
 * field tables above. Cargo siblings (findings rows, essays) pass through —
 * only illegal traffic re-asks.
 */
export function judgeStationReceiptSchema(): z.ZodType {
  return z.union([
    judgeSoObject(judgeConvergedFields),
    judgeSoObject(judgeContinueFields),
    judgeSoObject(judgeEscalateFields),
  ]);
}

// ─── Coder-family envelopes ──────────────────────────────────────────────────

interface CoderEnvelopeBase {
  readonly station: CoderStationId;
  readonly cargoPointer?: string;
}

/**
 * Clean completion (commits / no-op done). Must not carry refuse keys —
 * refuse is its own traffic status.
 */
export interface CoderCompletedEnvelope extends CoderEnvelopeBase {
  readonly status: "completed";
}

/**
 * Legal refuse receipt (ADR 0130 second-gate aligned; #910/#927 export path).
 *
 * Envelope-level only:
 * - `status: "refused"` (canonical; `refuted` is not a status token here)
 * - `refusedFindingIdentityKeys` — identity keys of refused findings
 * - `cargoPointer` — optional pointer to opaque cargo (four reasons + evidence
 *   for the judge); schema never validates that cargo body
 */
export interface CoderRefusedEnvelope extends CoderEnvelopeBase {
  readonly status: "refused";
  readonly refusedFindingIdentityKeys: readonly string[];
}

/**
 * Coder rings the decision bell (same shape as other escalate seats).
 * Distinct from refuse — refuse is a legal completion back to the judge table.
 */
export interface CoderEscalateEnvelope extends CoderEnvelopeBase {
  readonly status: "escalate";
  readonly reason: string;
  readonly diagnosis: string;
}

export type CoderStationEnvelope =
  | CoderCompletedEnvelope
  | CoderRefusedEnvelope
  | CoderEscalateEnvelope;

const coderStationSchema = z.enum(CODER_STATION_IDS);

const coderCompletedSchema = z
  .object({
    station: coderStationSchema,
    status: z.literal("completed"),
    cargoPointer: cargoPointerSchema,
  })
  .strict();

const coderRefusedSchema = z
  .object({
    station: coderStationSchema,
    status: z.literal("refused"),
    refusedFindingIdentityKeys: z.array(nonEmptyString).min(1),
    cargoPointer: cargoPointerSchema,
  })
  .strict();

const coderEscalateSchema = z
  .object({
    station: coderStationSchema,
    status: z.literal("escalate"),
    reason: nonEmptyString,
    diagnosis: nonEmptyString,
    cargoPointer: cargoPointerSchema,
  })
  .strict();

/**
 * Sandcastle `Output.object` tag for coder-family station receipts (#924).
 * Same tag name as the historical cargo tag: traffic fields are schema-validated;
 * ordinary cargo siblings ride as passthrough (committed / commitsAdded / refuse
 * prose) so cargo shape never forces a native re-ask — only illegal traffic does.
 */
export const CODER_RECEIPT_TAG = "coder";

function rejectBannedRefutedKeysInSo(
  value: Record<string, unknown>,
  ctx: z.RefinementCtx,
): void {
  for (const key of Object.keys(value)) {
    if (BANNED_REFUTED_KEY.test(key)) {
      ctx.addIssue({
        code: "custom",
        message: `canonical envelope vocabulary is refused* only; banned field: ${key}`,
        path: [key],
      });
    }
  }
}

/**
 * Production SO schema for coder / coderFix / familyCoderFix station receipts.
 *
 * Used by Sandcastle `Output.object({ tag: CODER_RECEIPT_TAG, schema, maxRetries })`.
 * Traffic shape is strict enough to re-ask bad envelopes; cargo siblings pass
 * through. Decode still runs {@link decodeCoderEnvelope} for the traffic view.
 *
 * Single source of field vocabulary with the pure decode path above — do not
 * invent a parallel SO-only field set.
 */
export function coderStationReceiptSchema(): z.ZodType {
  const completed = z
    .object({
      station: coderStationSchema,
      status: z.literal("completed"),
      cargoPointer: cargoPointerSchema,
    })
    .passthrough()
    .superRefine((value, ctx) => {
      rejectBannedRefutedKeysInSo(value as Record<string, unknown>, ctx);
      if (
        Object.prototype.hasOwnProperty.call(value, "refusedFindingIdentityKeys")
      ) {
        ctx.addIssue({
          code: "custom",
          message:
            'completed coder envelope must not carry refusedFindingIdentityKeys (use status:"refused")',
          path: ["refusedFindingIdentityKeys"],
        });
      }
    });

  const refused = z
    .object({
      station: coderStationSchema,
      status: z.literal("refused"),
      refusedFindingIdentityKeys: z.array(nonEmptyString).min(1),
      cargoPointer: cargoPointerSchema,
    })
    .passthrough()
    .superRefine((value, ctx) => {
      rejectBannedRefutedKeysInSo(value as Record<string, unknown>, ctx);
    });

  const escalate = z
    .object({
      station: coderStationSchema,
      status: z.literal("escalate"),
      reason: nonEmptyString,
      diagnosis: nonEmptyString,
      cargoPointer: cargoPointerSchema,
    })
    .passthrough()
    .superRefine((value, ctx) => {
      rejectBannedRefutedKeysInSo(value as Record<string, unknown>, ctx);
    });

  return z.union([completed, refused, escalate]);
}

/**
 * Strip unknown keys before schema parse so opaque cargo body siblings
 * (refuseRecords prose, essays, …) are ignored rather than rejected.
 * Traffic fields + banned-vocabulary check still apply.
 */
const CODER_TRAFFIC_KEYS = new Set([
  "station",
  "status",
  "cargoPointer",
  "refusedFindingIdentityKeys",
  "reason",
  "diagnosis",
]);

function pickCoderTraffic(record: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of CODER_TRAFFIC_KEYS) {
    if (Object.prototype.hasOwnProperty.call(record, key)) {
      out[key] = record[key];
    }
  }
  return out;
}

/** Encode a validated coder-family envelope into its canonical JSON shape. */
export function encodeCoderEnvelope(
  envelope: CoderStationEnvelope,
): CoderStationEnvelope {
  return cloneJson(envelope);
}

/**
 * Decode + validate a coder / coderFix / familyCoderFix envelope.
 *
 * - `refused` requires non-empty `refusedFindingIdentityKeys`
 * - cargo body siblings are stripped (not validated)
 * - `refuted*` field names fail closed
 * - `completed` must not carry refuse keys
 */
export function decodeCoderEnvelope(
  raw: unknown,
): ContractResult<CoderStationEnvelope> {
  const record = asRecord(raw);
  if (!record.ok) return record;
  const banned = rejectBannedEnvelopeVocabulary(record.value);
  if (!banned.ok) return banned;

  const status = record.value.status;
  if (status === "completed" && record.value.refusedFindingIdentityKeys !== undefined) {
    return fail(
      "completed coder envelope must not carry refusedFindingIdentityKeys (use status:\"refused\")",
    );
  }

  const traffic = pickCoderTraffic(record.value);
  if (status === "completed") {
    const parsed = coderCompletedSchema.safeParse(traffic);
    if (!parsed.success) return zodFail("coder envelope", parsed.error);
    return ok(parsed.data);
  }
  if (status === "refused") {
    const parsed = coderRefusedSchema.safeParse(traffic);
    if (!parsed.success) return zodFail("coder envelope", parsed.error);
    return ok(parsed.data);
  }
  if (status === "escalate") {
    const parsed = coderEscalateSchema.safeParse(traffic);
    if (!parsed.success) return zodFail("coder envelope", parsed.error);
    return ok(parsed.data);
  }
  return fail(
    `coder envelope status must be completed|refused|escalate, got ${String(status)}`,
  );
}

// ─── Ship envelope ───────────────────────────────────────────────────────────

interface ShipEnvelopeBase {
  readonly station: "ship";
  readonly cargoPointer?: string;
}

export interface ShipShippedEnvelope extends ShipEnvelopeBase {
  readonly status: "shipped";
}

export interface ShipCompletedEnvelope extends ShipEnvelopeBase {
  readonly status: "completed";
}

export interface ShipEscalateEnvelope extends ShipEnvelopeBase {
  readonly status: "escalate";
  readonly reason: string;
  readonly diagnosis: string;
}

export type ShipStationEnvelope =
  | ShipShippedEnvelope
  | ShipCompletedEnvelope
  | ShipEscalateEnvelope;

const shipShippedSchema = z
  .object({
    station: z.literal("ship"),
    status: z.literal("shipped"),
    cargoPointer: cargoPointerSchema,
  })
  .strict();

const shipCompletedSchema = z
  .object({
    station: z.literal("ship"),
    status: z.literal("completed"),
    cargoPointer: cargoPointerSchema,
  })
  .strict();

const shipEscalateSchema = z
  .object({
    station: z.literal("ship"),
    status: z.literal("escalate"),
    reason: nonEmptyString,
    diagnosis: nonEmptyString,
    cargoPointer: cargoPointerSchema,
  })
  .strict();

const shipEnvelopeSchema = z.discriminatedUnion("status", [
  shipShippedSchema,
  shipCompletedSchema,
  shipEscalateSchema,
]);

/**
 * Sandcastle `Output.object` tag for ship station receipts (#919 D / ADR 0132).
 * Traffic fields are schema-validated; delivery cargo (branch/pr) stays sidecar.
 */
export const SHIP_RECEIPT_TAG = "ship";

/**
 * Production SO schema for the family ship station receipt.
 *
 * Field vocabulary is shared with {@link decodeShipEnvelope}. Cargo siblings
 * (branch/pr essays) pass through — only illegal traffic re-asks.
 */
export function shipStationReceiptSchema(): z.ZodType {
  const shipped = z
    .object({
      station: z.literal("ship"),
      status: z.literal("shipped"),
      cargoPointer: cargoPointerSchema,
    })
    .passthrough();
  const completed = z
    .object({
      station: z.literal("ship"),
      status: z.literal("completed"),
      cargoPointer: cargoPointerSchema,
    })
    .passthrough();
  const escalate = z
    .object({
      station: z.literal("ship"),
      status: z.literal("escalate"),
      reason: nonEmptyString,
      diagnosis: nonEmptyString,
      cargoPointer: cargoPointerSchema,
    })
    .passthrough();
  return z.union([shipped, completed, escalate]);
}

/** Encode a validated ship envelope into its canonical JSON shape. */
export function encodeShipEnvelope(
  envelope: ShipStationEnvelope,
): ShipStationEnvelope {
  return cloneJson(envelope);
}

/** Decode + validate a ship station envelope. Never throws on bad shape. */
export function decodeShipEnvelope(
  raw: unknown,
): ContractResult<ShipStationEnvelope> {
  const record = asRecord(raw);
  if (!record.ok) return record;
  const banned = rejectBannedEnvelopeVocabulary(record.value);
  if (!banned.ok) return banned;
  // Strip cargo siblings (branch/pr) before strict traffic decode.
  const traffic: Record<string, unknown> = {};
  for (const key of ["station", "status", "cargoPointer", "reason", "diagnosis"]) {
    if (Object.prototype.hasOwnProperty.call(record.value, key)) {
      traffic[key] = record.value[key];
    }
  }
  const parsed = shipEnvelopeSchema.safeParse(traffic);
  if (!parsed.success) {
    return zodFail("ship envelope", parsed.error);
  }
  return ok(parsed.data);
}

// ─── Thin gate stations (merger / onlineReview) ──────────────────────────────
// ADR 0132: completed | escalate only. No rich cargo on the envelope.
// Resolve / role cargo rides sidecar; fate is this thin T2 receipt.

/** Sandcastle Output.object tag for the merger station receipt. */
export const MERGER_RECEIPT_TAG = "merger";

/** Sandcastle Output.object tag for family online-review-loop gate seats. */
export const ONLINE_REVIEW_RECEIPT_TAG = "onlineReview";

export type ThinGateStationId = "merger" | "onlineReview";

interface ThinGateEnvelopeBase {
  readonly cargoPointer?: string;
}

export interface MergerCompletedEnvelope extends ThinGateEnvelopeBase {
  readonly station: "merger";
  readonly status: "completed";
}

export interface MergerEscalateEnvelope extends ThinGateEnvelopeBase {
  readonly station: "merger";
  readonly status: "escalate";
  readonly reason: string;
  readonly diagnosis: string;
}

export type MergerStationEnvelope =
  | MergerCompletedEnvelope
  | MergerEscalateEnvelope;

export interface OnlineReviewCompletedEnvelope extends ThinGateEnvelopeBase {
  readonly station: "onlineReview";
  readonly status: "completed";
}

export interface OnlineReviewEscalateEnvelope extends ThinGateEnvelopeBase {
  readonly station: "onlineReview";
  readonly status: "escalate";
  readonly reason: string;
  readonly diagnosis: string;
}

export type OnlineReviewStationEnvelope =
  | OnlineReviewCompletedEnvelope
  | OnlineReviewEscalateEnvelope;

export type ThinGateStationEnvelope =
  | MergerStationEnvelope
  | OnlineReviewStationEnvelope;

const THIN_GATE_TRAFFIC_KEYS = [
  "station",
  "status",
  "cargoPointer",
  "reason",
  "diagnosis",
] as const;

function thinGateEnvelopeSchema(
  station: ThinGateStationId,
): z.ZodType<ThinGateStationEnvelope> {
  const completed = z
    .object({
      station: z.literal(station),
      status: z.literal("completed"),
      cargoPointer: cargoPointerSchema,
    })
    .strict();
  const escalate = z
    .object({
      station: z.literal(station),
      status: z.literal("escalate"),
      reason: nonEmptyString,
      diagnosis: nonEmptyString,
      cargoPointer: cargoPointerSchema,
    })
    .strict();
  return z.discriminatedUnion("status", [completed, escalate]) as z.ZodType<
    ThinGateStationEnvelope
  >;
}

const mergerEnvelopeSchema = thinGateEnvelopeSchema("merger");
const onlineReviewEnvelopeSchema = thinGateEnvelopeSchema("onlineReview");

/**
 * Production SO schema for the merger station receipt (completed | escalate).
 * Resolve cargo stays sidecar outside SO.
 */
export function mergerStationReceiptSchema(): z.ZodType {
  const completed = z
    .object({
      station: z.literal("merger"),
      status: z.literal("completed"),
      cargoPointer: cargoPointerSchema,
    })
    .passthrough();
  const escalate = z
    .object({
      station: z.literal("merger"),
      status: z.literal("escalate"),
      reason: nonEmptyString,
      diagnosis: nonEmptyString,
      cargoPointer: cargoPointerSchema,
    })
    .passthrough();
  return z.union([completed, escalate]);
}

/**
 * Production SO schema for family online-review-loop gate seats
 * (verify / fixer / cleanup / landing). Role cargo stays sidecar.
 */
export function onlineReviewStationReceiptSchema(): z.ZodType {
  const completed = z
    .object({
      station: z.literal("onlineReview"),
      status: z.literal("completed"),
      cargoPointer: cargoPointerSchema,
    })
    .passthrough();
  const escalate = z
    .object({
      station: z.literal("onlineReview"),
      status: z.literal("escalate"),
      reason: nonEmptyString,
      diagnosis: nonEmptyString,
      cargoPointer: cargoPointerSchema,
    })
    .passthrough();
  return z.union([completed, escalate]);
}

function pickThinGateTraffic(
  record: Record<string, unknown>,
): Record<string, unknown> {
  const traffic: Record<string, unknown> = {};
  for (const key of THIN_GATE_TRAFFIC_KEYS) {
    if (Object.prototype.hasOwnProperty.call(record, key)) {
      traffic[key] = record[key];
    }
  }
  return traffic;
}

/** Encode a validated merger envelope into its canonical JSON shape. */
export function encodeMergerEnvelope(
  envelope: MergerStationEnvelope,
): MergerStationEnvelope {
  return cloneJson(envelope);
}

/** Decode + validate a merger station envelope. Never throws on bad shape. */
export function decodeMergerEnvelope(
  raw: unknown,
): ContractResult<MergerStationEnvelope> {
  const record = asRecord(raw);
  if (!record.ok) return record;
  const banned = rejectBannedEnvelopeVocabulary(record.value);
  if (!banned.ok) return banned;
  const parsed = mergerEnvelopeSchema.safeParse(
    pickThinGateTraffic(record.value),
  );
  if (!parsed.success) {
    return zodFail("merger envelope", parsed.error);
  }
  return ok(parsed.data as MergerStationEnvelope);
}

/** Encode a validated online-review envelope into its canonical JSON shape. */
export function encodeOnlineReviewEnvelope(
  envelope: OnlineReviewStationEnvelope,
): OnlineReviewStationEnvelope {
  return cloneJson(envelope);
}

/** Decode + validate an online-review station envelope. Never throws on bad shape. */
export function decodeOnlineReviewEnvelope(
  raw: unknown,
): ContractResult<OnlineReviewStationEnvelope> {
  const record = asRecord(raw);
  if (!record.ok) return record;
  const banned = rejectBannedEnvelopeVocabulary(record.value);
  if (!banned.ok) return banned;
  const parsed = onlineReviewEnvelopeSchema.safeParse(
    pickThinGateTraffic(record.value),
  );
  if (!parsed.success) {
    return zodFail("onlineReview envelope", parsed.error);
  }
  return ok(parsed.data as OnlineReviewStationEnvelope);
}

// ─── Unified station decode ──────────────────────────────────────────────────

export type StationEnvelope =
  | JudgeVerdict
  | CoderStationEnvelope
  | ShipStationEnvelope
  | MergerStationEnvelope
  | OnlineReviewStationEnvelope;

/**
 * Decode any full-wave station completion envelope by `station` discriminator.
 * Unknown stations fail with a readable reason (no throw).
 */
export function decodeStationEnvelope(
  raw: unknown,
): ContractResult<StationEnvelope> {
  const record = asRecord(raw);
  if (!record.ok) return record;
  const banned = rejectBannedEnvelopeVocabulary(record.value);
  if (!banned.ok) return banned;

  const station = record.value.station;
  if (station === "judge") return decodeJudgeVerdict(record.value);
  if (
    station === "coder" ||
    station === "coderFix" ||
    station === "familyCoderFix"
  ) {
    return decodeCoderEnvelope(record.value);
  }
  if (station === "ship") return decodeShipEnvelope(record.value);
  if (station === "merger") return decodeMergerEnvelope(record.value);
  if (station === "onlineReview") return decodeOnlineReviewEnvelope(record.value);
  return fail(
    `unknown station (expected ${STATION_IDS.join("|")}): ${String(station)}`,
  );
}
