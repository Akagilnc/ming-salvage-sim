import * as sc from "@ai-hero/sandcastle";
import { z } from "zod";

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
 * payload. Schema refinement, well-formed-bell helpers, and runtime
 * classification all route through this so none/malformed/bell stay one parse.
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
 */
const openCountReceiptSchema = z.object({
  findingsCount: z.number().int().nonnegative(),
}).passthrough().superRefine(rejectMalformedEscalateAlongsideCount);

/**
 * Signal-level schema for the always-emitted {@link DECISION_GATE_TAG} tag.
 * Present `escalate` must be a well-formed bell; any object without `escalate`
 * (typically `{}`) is a no-gate signal. Ordinary cargo never lands in this tag.
 *
 * Non-object / null values fail so Sandcastle re-asks the signal itself rather
 * than silently accepting a missing protocol emission as "no gate".
 */
export const decisionGateSignalSchema: z.ZodType = z.union([
  decisionBellSchema,
  z.custom(
    (value) => {
      if (value === null || typeof value !== "object" || Array.isArray(value)) {
        return false;
      }
      return !Object.prototype.hasOwnProperty.call(value, "escalate");
    },
    { message: "decision signal must be an object without a malformed escalate" },
  ),
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
 */
export function decisionGateOutput(): sc.OutputDefinition {
  return workerReceiptOutput(DECISION_GATE_TAG, decisionGateSignalSchema);
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
 * Shared well-formed decision-bell probe for production parsers (#899 seam).
 * Returns the bell only when reason and diagnosis are both non-empty after trim;
 * present-but-malformed escalate is {@link isMalformedDecisionGate}.
 */
export function wellFormedDecisionBell(
  receipt: unknown,
): { reason: string; diagnosis: string } | undefined {
  const probe = probeEscalate(receipt);
  if (probe.kind !== "bell") return undefined;
  return { reason: probe.reason, diagnosis: probe.diagnosis };
}

/**
 * True when the payload carries an `escalate` key that fails the strict
 * decision-gate contract (empty reason/diagnosis, wrong shape, etc.).
 */
export function isMalformedDecisionGate(receipt: unknown): boolean {
  return probeEscalate(receipt).kind === "malformed";
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
 * Single probe pass — no double-parse of the same escalate payload.
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

/** A native receipt retry that must fail the Action for #598 mechanical redispatch. */
export function isReceiptRecoveryFailure(error: unknown): boolean {
  if (error instanceof sc.StructuredOutputError) return true;
  return error instanceof Error &&
    /(?:(?:resume\s*)?session.*(?:not found|expired|missing|unavailable)|does not support resumeSession|output\.maxRetries requires an agent provider that supports session resumption)/i.test(error.message);
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
