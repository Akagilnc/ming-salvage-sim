import * as sc from "@ai-hero/sandcastle";
import { z } from "zod";

import type {
  Finding,
  PriorFindingDisposition,
  ReviewerOutput,
} from "./types.js";

/** The bounded native Sandcastle retry budget ratified by #899. */
export const RECEIPT_MAX_RETRIES = 2;

/**
 * Always-emitted typed decision-gate tag for optional gate seats (#899).
 * Bound to {@link decisionGateOutput} so ordinary cargo tags (`coder` / `ship` /
 * `merger` / review-loop roles) stay outside Output.object — missing or
 * malformed cargo never forces structured-output re-ask.
 */
export const DECISION_GATE_TAG = "decision";

/** Strict decision-gate payload: reason/diagnosis must be non-empty strings. */
const decisionEscalateSchema = z.object({
  reason: z.string().trim().min(1),
  diagnosis: z.string().trim().min(1),
});

/**
 * Worker-pressed decision gate. Malformed bells fail Sandcastle schema
 * validation so the same session re-asks (#899); exhaust rethrows for #598.
 */
const decisionBellSchema = z.object({
  escalate: decisionEscalateSchema,
}).passthrough();

/**
 * Single shared probe for the optional `escalate` key on any receipt/signal
 * payload. Schema refinement and runtime classification both route through
 * this so none/malformed/bell stay one parse.
 */
type EscalateProbe =
  | { readonly kind: "absent" }
  | { readonly kind: "malformed" }
  | { readonly kind: "bell"; readonly reason: string; readonly diagnosis: string };

function probeEscalate(value: unknown): EscalateProbe {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { kind: "absent" };
  }
  if (!Object.prototype.hasOwnProperty.call(value, "escalate")) {
    return { kind: "absent" };
  }
  const parsed = decisionEscalateSchema.safeParse(
    (value as { escalate: unknown }).escalate,
  );
  if (!parsed.success) return { kind: "malformed" };
  return {
    kind: "bell",
    reason: parsed.data.reason,
    diagnosis: parsed.data.diagnosis,
  };
}

/**
 * When `escalate` is present on an open-count receipt it must be a well-formed
 * bell — otherwise a legal findingsCount would mask a bad gate via union
 * short-circuit (#899 S6 finding 1).
 */
function rejectMalformedEscalateAlongsideCount(
  value: unknown,
  ctx: z.RefinementCtx,
): void {
  if (probeEscalate(value).kind === "malformed") {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "malformed decision gate alongside open-count",
      path: ["escalate"],
    });
  }
}

/**
 * Shared open-count receipt for reviewer and CMR seats (#899). Both roles use
 * the same findingsCount + optional decision-gate contract until their typed
 * boundaries genuinely diverge — introduce role dispatch only then.
 *
 * Only the exact `escalate` key is a gate: present → must be a well-formed
 * bell; absent → no-gate. Unknown keys (including near-miss spellings) are
 * opaque cargo and must not be approximate-matched into a gate (#899).
 * Dedicated {@link DECISION_GATE_TAG} still rejects typos via `.strict()`.
 */
const openCountReceiptSchema = z.object({
  findingsCount: z.number().int().nonnegative(),
}).passthrough().superRefine((value, ctx) => {
  rejectMalformedEscalateAlongsideCount(value, ctx);
});

/**
 * Signal-level schema for the always-emitted {@link DECISION_GATE_TAG} tag.
 * Present `escalate` must be a well-formed bell; the only no-gate form is a
 * strict empty object `{}`. Unknown keys (e.g. `escalte`) fail via `.strict()`
 * so Sandcastle same-session re-asks rather than treating them as no-gate
 * (#899). Ordinary cargo never lands in this tag — open-count receipts keep
 * unknown keys as opaque cargo and only validate the exact `escalate` field.
 *
 * Non-object / null values fail so Sandcastle re-asks the signal itself rather
 * than silently accepting a missing protocol emission as "no gate".
 */
export const decisionGateSignalSchema: z.ZodType = z.union([
  decisionBellSchema,
  z.object({}).strict(),
]);

/**
 * Shared open-count + optional decision-gate schema for reviewer/CMR typed seats.
 * No role parameter: both seats share one contract until they genuinely diverge.
 */
export function workerReceiptSchema(): z.ZodType {
  return z.union([
    decisionBellSchema,
    openCountReceiptSchema,
  ]);
}

/** One typed receipt definition for every worker path. Callers must pass schema. */
export function workerReceiptOutput(
  tag: string,
  schema: z.ZodType,
): sc.OutputDefinition {
  return sc.Output.object({ tag, schema, maxRetries: RECEIPT_MAX_RETRIES });
}

/**
 * Optional decision-gate Output.object on the dedicated {@link DECISION_GATE_TAG}.
 * Cargo tags stay untyped (ADR 0131 / #899).
 *
 * Single-slice coder seats no longer use this (#924) — they attach the T2
 * station receipt schema via {@link coderReceiptOutput}. Family seats that still
 * speak the decision-gate dual-channel keep calling this until their own slices.
 */
export function decisionGateOutput(): sc.OutputDefinition {
  return workerReceiptOutput(DECISION_GATE_TAG, decisionGateSignalSchema);
}

/**
 * #924 — single-slice coder station receipt Output.object.
 * Schema lives in {@link coderStationReceiptSchema} (T2 / stationReceiptContracts);
 * this is only the Sandcastle attach helper (tag + maxRetries).
 */
export function coderReceiptOutput(
  schema: z.ZodType,
  tag: string = "coder",
): sc.OutputDefinition {
  return workerReceiptOutput(tag, schema);
}

/**
 * Production seats that attach Output.object must receive a typed signal.
 * Absent `result.output` fails the Action for #598 — never fall through to
 * cargo as a no-gate completion (#899).
 */
export function requireTypedTrafficSignal(
  output: unknown | undefined,
  label: string,
): unknown {
  if (output === undefined) {
    throw new Error(
      `${label}: typed traffic signal missing; failing Action for mechanical redispatch`,
    );
  }
  return output;
}

/**
 * Classified decision-gate signal after malformed-gate validation (#899 seam).
 * Callers map `bell` into role-specific escalate outcomes and treat `none` as
 * "no gate — continue with cargo".
 */
export type DecisionGateClassification =
  | { readonly kind: "none" }
  | { readonly kind: "bell"; readonly reason: string; readonly diagnosis: string };

/**
 * Central malformed-gate validation + bell classification for production parsers.
 * Present-but-malformed `escalate` throws so the Action exits non-zero for #598;
 * well-formed bells and no-gate payloads are returned as a discriminated result.
 * Single probe pass via {@link probeEscalate} — no double-parse, no parallel
 * well-formed/malformed helper exports.
 */
export function classifyDecisionGate(
  receipt: unknown,
  label: string,
): DecisionGateClassification {
  const probe = probeEscalate(receipt);
  if (probe.kind === "malformed") {
    throw new Error(
      `${label}: malformed decision gate (empty or non-string reason/diagnosis); failing Action for mechanical redispatch`,
    );
  }
  if (probe.kind === "bell") {
    return { kind: "bell", reason: probe.reason, diagnosis: probe.diagnosis };
  }
  return { kind: "none" };
}

/**
 * Decode an untyped open-count receipt into a typed {@link ReviewerOutput}.
 *
 * Production Sandcastle / sidecar payloads enter here as `unknown`. Findings
 * rows are opaque cargo: non-array shapes become empty cargo, never rewrite
 * the declared findingsCount (ADR 0131 / #899). Missing or unusable count is
 * not a zero open-count — callers map that to the unusable-receipt path.
 *
 * Returns `undefined` when the receipt cannot supply a non-negative integer
 * findingsCount (unusable review envelope).
 */
export function decodeReviewerOpenCountReceipt(
  raw: unknown,
): ReviewerOutput | undefined {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }
  const receipt = raw as {
    findingsCount?: unknown;
    findings?: unknown;
    priorFindingDispositions?: unknown;
  };
  const findingsCount =
    typeof receipt.findingsCount === "number" &&
    Number.isSafeInteger(receipt.findingsCount) &&
    receipt.findingsCount >= 0
      ? receipt.findingsCount
      : undefined;
  if (findingsCount === undefined) return undefined;
  const findings: Finding[] = Array.isArray(receipt.findings)
    ? (receipt.findings as Finding[])
    : [];
  const priorFindingDispositions = Array.isArray(receipt.priorFindingDispositions)
    ? (receipt.priorFindingDispositions as ReadonlyArray<PriorFindingDisposition>)
    : undefined;
  return {
    kind: "reviewer",
    findings,
    findingsCount,
    ...(priorFindingDispositions !== undefined
      ? { priorFindingDispositions }
      : {}),
  };
}

const RECEIPT_RECOVERY_MESSAGE =
  /(?:(?:resume\s*)?session.*(?:not found|expired|missing|unavailable)|does not support resumeSession|output\.maxRetries requires an agent provider that supports session resumption)/i;

/**
 * Walk Effect/Fiber `cause` / nested `error` wrappers that Sandcastle may put
 * around a native {@link sc.StructuredOutputError} (observed under concurrent
 * vitest load as FiberFailure → ExecError). Production #598 disposition must
 * still see the receipt-recovery class through the wrap.
 */
function* walkErrorChain(error: unknown): Generator<unknown> {
  let current: unknown = error;
  for (let depth = 0; depth < 8 && current != null; depth += 1) {
    yield current;
    if (typeof current !== "object") break;
    const bag = current as { cause?: unknown; error?: unknown };
    if (bag.cause !== undefined && bag.cause !== current) {
      current = bag.cause;
      continue;
    }
    if (bag.error !== undefined && bag.error !== current) {
      current = bag.error;
      continue;
    }
    break;
  }
}

/** True when node is a StructuredOutputError by instanceof or Error.name. */
function isStructuredOutputErrorNode(node: unknown): boolean {
  if (node instanceof sc.StructuredOutputError) return true;
  // Duplicate @ai-hero/sandcastle installs break instanceof across package
  // copies; name matches the prior runner-side pattern (gemini R2).
  return node instanceof Error && node.name === "StructuredOutputError";
}

/** Locate a nested StructuredOutputError, if any, inside wrapper errors. */
export function nestedStructuredOutputError(
  error: unknown,
): sc.StructuredOutputError | undefined {
  for (const node of walkErrorChain(error)) {
    if (isStructuredOutputErrorNode(node)) {
      return node as sc.StructuredOutputError;
    }
  }
  return undefined;
}

/** A native receipt retry that must fail the Action for #598 mechanical redispatch. */
export function isReceiptRecoveryFailure(error: unknown): boolean {
  for (const node of walkErrorChain(error)) {
    if (isStructuredOutputErrorNode(node)) return true;
    if (node instanceof Error && RECEIPT_RECOVERY_MESSAGE.test(node.message)) {
      return true;
    }
  }
  return false;
}

/**
 * Log a typed-receipt recovery exhaust and rethrow so the Action exits non-zero
 * for #598 redispatch (#899). Accepts the already-caught error directly — this
 * is not a re-ask loop (Sandcastle owns same-session maxRetries).
 */
export function logAndRethrowReceiptFailure(error: unknown, worker: string): never {
  if (isReceiptRecoveryFailure(error)) {
    console.warn(
      `[orchestrator] ${worker} receipt recovery exhausted; propagating for mechanical redispatch`,
    );
  }
  throw error;
}
