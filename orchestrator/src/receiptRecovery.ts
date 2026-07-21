import "./sandcastleCancelSeam.js"; // #1010 choke-point: patch before sandcastle load
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
 * Legacy decision-gate tag retained for unit fixtures that pin Sandcastle's
 * four-case matrix on the raw `decision` tag (#899). Production seats attach
 * T2 station receipts (coder / judge / ship / merger / onlineReview) instead.
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
  // Owner B ruling 2026-07-16: maxRetries follows provider session-resume
  // capability (resumeCapableForSlug). Incapable → 0; a bad envelope falls
  // through to the established process-root retry (#934 ID-006 SO-exhaust).
  // Required — no fail-open default; callers must pass the registry probe.
  resumeCapable: boolean,
): sc.OutputDefinition {
  return sc.Output.object({
    tag,
    schema,
    maxRetries: resumeCapable ? RECEIPT_MAX_RETRIES : 0,
  });
}

/**
 * #924 — single-slice coder station receipt Output.object.
 * Schema lives in {@link coderStationReceiptSchema} (T2 / stationReceiptContracts);
 * this is only the Sandcastle attach helper (tag + maxRetries).
 */
export function coderReceiptOutput(
  schema: z.ZodType,
  tag: string = "coder",
  resumeCapable: boolean,
): sc.OutputDefinition {
  return workerReceiptOutput(tag, schema, resumeCapable);
}

/**
 * #919 D — family ship station receipt Output.object.
 * Schema lives in {@link shipStationReceiptSchema} (T2 / stationReceiptContracts);
 * this is only the Sandcastle attach helper (tag + maxRetries).
 */
export function shipReceiptOutput(
  schema: z.ZodType,
  tag: string = "ship",
  resumeCapable: boolean,
): sc.OutputDefinition {
  return workerReceiptOutput(tag, schema, resumeCapable);
}

/**
 * #919 CR T2 — family merger station receipt Output.object.
 * Schema lives in {@link mergerStationReceiptSchema} (T2 / stationReceiptContracts).
 */
export function mergerReceiptOutput(
  schema: z.ZodType,
  tag: string = "merger",
  resumeCapable: boolean,
): sc.OutputDefinition {
  return workerReceiptOutput(tag, schema, resumeCapable);
}

/**
 * #919 CR T2 — family online-review-loop gate station receipt Output.object.
 * Schema lives in {@link onlineReviewStationReceiptSchema}
 * (T2 / stationReceiptContracts). Shared by verify/fixer/cleanup/landing.
 *
 * #1092: when `resumeCapable`, Sandcastle's built-in maxRetries resume prompt
 * omits the JSON schema (workers remember the tag name and emit YAML). Callers
 * that resume must feed {@link structuredOutputResumeInstruction} on the
 * resume/retry turn; {@link withMechanicalRetry} short-circuits after the first
 * resume-session SO parse failure + one fresh attempt.
 */
export function onlineReviewReceiptOutput(
  schema: z.ZodType,
  tag: string = "onlineReview",
  resumeCapable: boolean,
): sc.OutputDefinition {
  // #1092: Sandcastle's built-in SO maxRetries resume prompt omits the JSON
  // schema (YAML habit on hot resume). Keep the typed tag+schema attach, but
  // force maxRetries 0 so {@link runSandcastleWithOnlineReviewSoGuard} owns
  // exactly one schema-rich resume before the process-root fresh short-circuit.
  void resumeCapable;
  return workerReceiptOutput(tag, schema, false);
}

/**
 * #1092 — onlineReview station-receipt schema text restated on resume/retry.
 * Same strength as the fresh `prompts/*.md` envelope tables.
 */
export const ONLINE_REVIEW_RECEIPT_SCHEMA_TEXT = [
  'station: literal "onlineReview"',
  'status: "completed" | "escalate"',
  "cargoPointer: optional non-empty path/URI",
  'when status is "escalate": reason and diagnosis are required non-empty strings',
].join("\n");

/** #1092 — one minimal valid completed envelope (JSON, not YAML). */
export const ONLINE_REVIEW_RECEIPT_EXAMPLE_JSON =
  '{"station":"onlineReview","status":"completed"}';

/**
 * #1092 — resume/retry SO instruction that restates the full JSON schema plus
 * one minimal valid JSON example. Sandcastle's built-in retry feedback only
 * says "Emit only a corrected &lt;tag&gt; block" — that is what produced the
 * YAML-prose receipt habit on hot resume.
 */
export function structuredOutputResumeInstruction(input: {
  readonly tag: string;
  readonly schemaText: string;
  readonly exampleJson: string;
  readonly errorMessage?: string;
  readonly rawMatched?: string;
  readonly retriesRemaining?: number;
}): string {
  const problem =
    input.errorMessage ??
    `Structured output tag <${input.tag}> contains invalid JSON`;
  const previous =
    input.rawMatched === undefined
      ? "(no matching tag was emitted)"
      : input.rawMatched;
  const retries =
    input.retriesRemaining === undefined
      ? ""
      : `\nRetries remaining after this attempt: ${input.retriesRemaining}.\n`;
  return `Your previous response did not produce valid structured output.
${retries}
Problem:
${problem}

Previous matched output:
${previous}

Required JSON schema for <${input.tag}> (emit JSON only — never YAML or prose):
${input.schemaText}

Minimal valid JSON example (copy this shape; do not wrap in markdown fences):
<${input.tag}>${input.exampleJson}</${input.tag}>

Emit only a corrected <${input.tag}> JSON block. Do not change files or run commands.`;
}

/** True when an error is a structured-output JSON/schema parse failure (#1092). */
export function isStructuredOutputParseFailure(error: unknown): boolean {
  const soe = nestedStructuredOutputError(error);
  if (soe === undefined) return false;
  const msg = soe.message;
  return (
    /contains invalid JSON/i.test(msg) ||
    /failed schema validation/i.test(msg) ||
    /not found in agent output/i.test(msg)
  );
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
 * Decode residual untyped open-count paper into a typed {@link ReviewerOutput}.
 *
 * Not the S3/S6 main path (that is judge tri-state / ADR 0131 channel (b)).
 * Production Sandcastle / sidecar payloads enter here as `unknown`. Findings
 * rows are opaque cargo: non-array shapes become empty cargo, never rewrite
 * the declared findingsCount (#899 cargo rule). Missing or unusable count is
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
    fixPacketBody?: unknown;
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
  // ADR 0138: residual paper may already carry an authored body — transport
  // only; never invent when absent (projection pass-through is separate).
  const fixPacketBody =
    typeof receipt.fixPacketBody === "string"
      ? receipt.fixPacketBody
      : undefined;
  return {
    kind: "reviewer",
    findings,
    findingsCount,
    ...(priorFindingDispositions !== undefined
      ? { priorFindingDispositions }
      : {}),
    ...(fixPacketBody !== undefined ? { fixPacketBody } : {}),
  };
}

const RECEIPT_RECOVERY_MESSAGE =
  /(?:(?:resume\s*)?session.*(?:not found|expired|missing|unavailable)|does not support resumeSession|output\.maxRetries requires an agent provider that supports session resumption)/i;

/**
 * Walk Effect/Fiber wrappers that Sandcastle may put around a native error
 * (observed under concurrent vitest load as FiberFailure → ExecError / Die.defect).
 * Shared by receipt recovery (#598 SOE) and #964 AgentError recognition so both
 * courts see the same chain shape.
 *
 * Follows `cause` → `error` → `defect` (Effect Die) in that order per hop.
 */
export function* walkErrorChain(error: unknown): Generator<unknown> {
  let current: unknown = error;
  for (let depth = 0; depth < 8 && current != null; depth += 1) {
    yield current;
    if (typeof current !== "object") break;
    const bag = current as {
      cause?: unknown;
      error?: unknown;
      defect?: unknown;
    };
    if (bag.cause !== undefined && bag.cause !== current) {
      current = bag.cause;
      continue;
    }
    if (bag.error !== undefined && bag.error !== current) {
      current = bag.error;
      continue;
    }
    // Effect Cause.Die nests the thrown value under `defect` (not error/cause).
    // CI flakes under load were false-negatives when SOE only lived here.
    if (bag.defect !== undefined && bag.defect !== current) {
      current = bag.defect;
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

function isOnlineReviewOutputDefinition(
  output: sc.OutputDefinition | undefined,
): output is sc.OutputDefinition & { readonly tag: string } {
  if (output === undefined || typeof output !== "object") return false;
  // #1091 finding 3: later logic dereferences `._tag` and `.schema`; verify
  // both at the guard so non-conforming outputs take the safe (throw) path
  // rather than reaching schema access with an unexpected shape.
  const o = output as { tag?: unknown; _tag?: unknown; schema?: unknown };
  return (
    o.tag === "onlineReview" &&
    o._tag === "object" &&
    o.schema !== undefined &&
    typeof o.schema === "object"
  );
}

/**
 * #1092 — wrap `sc.run` for onlineReview seats:
 * 1. Orchestrator-level resume turns get a schema-rich SO instruction (same
 *    strength as fresh promptFile tables) before the agent speaks.
 * 2. On the first SO parse failure with a resumable sessionId, resume once with
 *    {@link structuredOutputResumeInstruction}. Further failures propagate for
 *    {@link withMechanicalRetry}'s one-fresh short-circuit.
 */
export async function runSandcastleWithOnlineReviewSoGuard(
  run: (options: Parameters<typeof sc.run>[0]) => Promise<Awaited<ReturnType<typeof sc.run>>>,
  options: Parameters<typeof sc.run>[0],
): Promise<Awaited<ReturnType<typeof sc.run>>> {
  const prepared = enrichOnlineReviewResumeTurn(options);
  try {
    return await run(prepared);
  } catch (err) {
    if (!isOnlineReviewOutputDefinition(prepared.output)) throw err;
    if (!isStructuredOutputParseFailure(err)) throw err;
    const soe = nestedStructuredOutputError(err);
    if (soe?.sessionId === undefined) throw err;
    const tag =
      typeof prepared.output.tag === "string" ? prepared.output.tag : "onlineReview";
    const schema =
      prepared.output._tag === "object" ? prepared.output.schema : undefined;
    if (schema === undefined) throw err;
    const resumePrompt = structuredOutputResumeInstruction({
      tag,
      schemaText: ONLINE_REVIEW_RECEIPT_SCHEMA_TEXT,
      exampleJson: ONLINE_REVIEW_RECEIPT_EXAMPLE_JSON,
      errorMessage: soe.message,
      ...(soe.rawMatched !== undefined ? { rawMatched: soe.rawMatched } : {}),
      retriesRemaining: 0,
    });
    return await run({
      ...prepared,
      prompt: resumePrompt,
      promptFile: undefined,
      promptArgs: undefined,
      resumeSession: soe.sessionId,
      output: onlineReviewReceiptOutput(schema as z.ZodType, tag, false),
    });
  }
}

/** When the caller already resumes an onlineReview seat, restate SO schema. */
function enrichOnlineReviewResumeTurn(
  options: Parameters<typeof sc.run>[0],
): Parameters<typeof sc.run>[0] {
  if (typeof options.resumeSession !== "string") return options;
  if (!isOnlineReviewOutputDefinition(options.output)) return options;
  const tag =
    typeof options.output.tag === "string" ? options.output.tag : "onlineReview";
  const schemaInstruction = structuredOutputResumeInstruction({
    tag,
    schemaText: ONLINE_REVIEW_RECEIPT_SCHEMA_TEXT,
    exampleJson: ONLINE_REVIEW_RECEIPT_EXAMPLE_JSON,
    errorMessage:
      "Resume turn: emit the station receipt as JSON matching the schema below (not YAML or prose).",
  });
  // Prefer an inline schema-rich prompt on resume. Session memory already holds
  // the station work; the missing piece on hot resume is the JSON body genre.
  return {
    ...options,
    prompt:
      `${schemaInstruction}\n\n` +
      "Continue the in-progress station work from this session, then emit the receipt.",
    promptFile: undefined,
    promptArgs: undefined,
  };
}
