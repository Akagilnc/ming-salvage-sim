/**
 * #1094 / #1126 — family CMR panel legs + single-slice review legs as
 * runner-dispatched first-class workers (one mechanism; scope is a parameter).
 *
 * Legs are isomorphic across scopes:
 *   - same WorkerSpec / dispatchWorker mechanism
 *   - sandcastle injects credentials for the top-level agent (no nested-CLI mounts)
 *   - the selected reviewer soul loads through the provider instruction layer
 *   - independent-clone semantics preserved at the backend seam
 *   - cross-vendor family → distinct CLI host via {@link workerHostForModel}
 *
 * The judge receives their prose transports as inputs and emits the unified
 * typed verdict — it never spawns model CLIs.
 */

import { workerHostForModel } from "../dispatchWorker.js";
import {
  isLegalLegPaper,
  type LegTransport,
} from "../legPaper.js";
import {
  modelFamilyForCmrReviewLeg,
  providerForModelSlug,
} from "../modelRegistry.js";
import type {
  CmrSkippedLeg,
  ReviewerOutput,
  WorkerCmrReviewLeg,
  WorkerResult,
  WorkerSpec,
} from "../types.js";
import type { IntegratedCmrPass } from "./types.js";

/** Family CMR panel-leg task prompt. */
export const CMR_PANEL_LEG_PROMPT_FILE = "cmr_panel_leg.md";

/** Single-slice per-slice /code-review leg task prompt (#1126). */
export const CODE_REVIEW_LEG_PROMPT_FILE = "code_review_leg.md";

/**
 * #1094 / #1126 — one panel-leg dispatch mechanism; scope is only a parameter.
 * Family keeps the CMR court seat id + lens soul; single-slice pins the
 * requesting judge seat (S3/S6) and the per-slice READ-ONLY reviewer soul.
 */
export type ReviewLegScope =
  | {
      readonly kind: "single";
      readonly judgeStep: "S3" | "S6";
    }
  | {
      readonly kind: "family";
      readonly pass: IntegratedCmrPass;
    };

/** True when promptFile is a runner-owned review-panel leg task source. */
export function isReviewPanelLegPromptFile(promptFile: string): boolean {
  return (
    promptFile === CMR_PANEL_LEG_PROMPT_FILE ||
    promptFile === CODE_REVIEW_LEG_PROMPT_FILE
  );
}

/** @deprecated Prefer {@link isReviewPanelLegPromptFile}. */
export function isCmrPanelLegPromptFile(promptFile: string): boolean {
  return isReviewPanelLegPromptFile(promptFile);
}

/**
 * Declarative WorkerSpec for one route-selected review leg.
 * Fresh / clean — never resume a prior leg session.
 * Family pass selects a CMR lens soul + family task; single-slice uses
 * READ-ONLY + per-slice /code-review task.
 */
export function cmrPanelLegWorkerSpec(
  leg: WorkerCmrReviewLeg,
  scope: ReviewLegScope,
): WorkerSpec {
  const model = leg.slug;
  return {
    // Family: seat remains the CMR court (S3). Single-slice: pin the requesting
    // judge seat. Per-leg job/log uniqueness is the monitor dispatchId substrate
    // (#1094 F1) — not a new StepId.
    id: scope.kind === "single" ? scope.judgeStep : "S3",
    kind: "reviewer",
    role: "reviewer",
    host: workerHostForModel(model),
    session: "fresh",
    contextRetention: "clean",
    promptFile:
      scope.kind === "single"
        ? CODE_REVIEW_LEG_PROMPT_FILE
        : CMR_PANEL_LEG_PROMPT_FILE,
    maxIter: 1,
    model,
    soul:
      scope.kind === "single"
        ? "READ-ONLY"
        : scope.pass === "completeness"
          ? "cmr-completeness"
          : "cmr-correctness",
    toolchain: [],
  };
}

/**
 * Build a {@link LegTransport} from a panel-leg WorkerResult.
 *
 * - completed + rawStdout → exit 0 + stdout (ADR 0141 presence judged later)
 * - failed / escalated / missing prose → non-zero or empty (degraded evidence)
 */
export function legTransportFromPanelLegResult(
  slug: string,
  result: WorkerResult,
): LegTransport {
  if (result.kind === "completed") {
    const stdout = panelLegStdoutFromOutput(result.output);
    return { slug, exitCode: 0, stdout };
  }
  if (result.kind === "failed") {
    return { slug, exitCode: 1, stdout: result.reason };
  }
  if (result.kind === "escalated") {
    return {
      slug,
      exitCode: 1,
      stdout: `${result.escalation.reason}: ${result.escalation.diagnosis}`,
    };
  }
  return { slug, exitCode: 1, stdout: "" };
}

function panelLegStdoutFromOutput(output: unknown): string {
  if (output === undefined || output === null || typeof output !== "object") {
    return "";
  }
  if (!("kind" in output) || (output as { kind?: unknown }).kind !== "reviewer") {
    return "";
  }
  const raw = (output as ReviewerOutput).rawStdout;
  return typeof raw === "string" ? raw : "";
}

/**
 * Declared legs absent from transport-present successfulLegs become skippedLegs
 * with a short degrade reason for the judge (never silent success).
 */
export function skippedLegsFromTransports(
  declared: ReadonlyArray<WorkerCmrReviewLeg>,
  transports: ReadonlyArray<LegTransport>,
): CmrSkippedLeg[] {
  const bySlug = new Map(transports.map((t) => [t.slug, t]));
  const skipped: CmrSkippedLeg[] = [];
  for (const leg of declared) {
    const transport = bySlug.get(leg.slug);
    if (transport !== undefined && isLegalLegPaper(transport)) continue;
    skipped.push({
      slug: leg.slug,
      reason: degradeReasonForTransport(leg.slug, transport),
    });
  }
  return skipped;
}

function degradeReasonForTransport(
  slug: string,
  transport: LegTransport | undefined,
): string {
  if (transport === undefined) {
    return `panel leg ${slug} did not run`;
  }
  if (transport.exitCode !== 0) {
    const detail = (transport.stdout ?? "").trim();
    return detail.length > 0
      ? `panel leg ${slug} failed: ${detail.slice(0, 200)}`
      : `panel leg ${slug} failed (exit ${transport.exitCode})`;
  }
  if ((transport.stdout ?? "").trim().length === 0) {
    return `panel leg ${slug} produced empty stdout`;
  }
  return `panel leg ${slug} produced no legal review paper`;
}

/**
 * Mint a completed panel-leg WorkerResult carrying prose for transport rebuild.
 */
export function panelLegCompletedResult(stdout: string): WorkerResult {
  return {
    kind: "completed",
    output: {
      kind: "reviewer",
      findingsCount: 0,
      findings: [],
      rawStdout: stdout,
    },
  };
}

/**
 * #1094 R2 F7 — CMR-leg-only / unknown slugs must degrade loudly, never throw
 * through the family court (workerHostForModel / agentForSpec would crash).
 */
export function degradedTransportForNonRunnablePanelLeg(
  slug: string,
): LegTransport | undefined {
  if (providerForModelSlug(slug) !== undefined) {
    return undefined;
  }
  try {
    const family = modelFamilyForCmrReviewLeg(slug);
    return {
      slug,
      exitCode: 1,
      stdout:
        `panel leg ${slug} is CMR-leg-only (family ${family}, not a live worker ` +
        `slug) — degraded; restore a MODEL_SLUG_REGISTRY worker slug or drop the leg`,
    };
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return {
      slug,
      exitCode: 1,
      stdout: `panel leg ${slug} unknown / unresolvable — degraded: ${detail}`,
    };
  }
}

export type PanelLegsRoundResult = {
  readonly transports: ReadonlyArray<LegTransport>;
  readonly skippedLegs: ReadonlyArray<CmrSkippedLeg>;
};

/**
 * Dispatch reply for one review-panel leg (#1126).
 * Runner seat control is an explicit typed outcome — never a thrown Symbol.
 */
export type ReviewPanelDispatchReply<TControl = never> =
  | { readonly kind: "leg_result"; readonly result: WorkerResult }
  | { readonly kind: "seat_control"; readonly control: TControl };

/** Round outcome: transports, or the first seat-control signal. */
export type ReviewPanelRoundOutcome<TControl = never> =
  | ({ readonly kind: "round" } & PanelLegsRoundResult)
  | { readonly kind: "seat_control"; readonly control: TControl };

/**
 * Runner-owned review-panel fan-out (#1094 / #1126).
 * One mechanism for family CMR and single-slice /code-review; scope is required.
 * Settles every leg first (#1094 F3), then either returns seat_control or
 * rethrows one real rejection — never leaves sibling rejections unhandled.
 *
 * `dispatch` may return a bare {@link WorkerResult} (family path) or an explicit
 * {@link ReviewPanelDispatchReply} when the runner must surface seat control.
 */
export async function dispatchReviewPanelLegs<TControl = never>(input: {
  readonly legs: ReadonlyArray<WorkerCmrReviewLeg>;
  readonly scope: ReviewLegScope;
  readonly dispatch: (
    spec: WorkerSpec,
  ) => Promise<WorkerResult | ReviewPanelDispatchReply<TControl>>;
}): Promise<ReviewPanelRoundOutcome<TControl>> {
  const legs = input.legs;
  const scope = input.scope;
  if (legs.length === 0) {
    return { kind: "round", transports: [], skippedLegs: [] };
  }
  type SettledLeg =
    | { readonly kind: "transport"; readonly transport: LegTransport }
    | { readonly kind: "seat_control"; readonly control: TControl };

  // #1094 F3: Promise.all drops sibling rejections as unhandled after the first
  // park/relay throw. Settle every leg first, then rethrow one rejection or
  // surface the first typed seat_control.
  const settled = await Promise.allSettled(
    legs.map(async (leg): Promise<SettledLeg> => {
      const degraded = degradedTransportForNonRunnablePanelLeg(leg.slug);
      if (degraded !== undefined) {
        return { kind: "transport", transport: degraded };
      }
      const spec = cmrPanelLegWorkerSpec(leg, scope);
      const raw = await input.dispatch(spec);
      const reply = normalizeReviewPanelDispatchReply(raw);
      if (reply.kind === "seat_control") {
        return { kind: "seat_control", control: reply.control };
      }
      return {
        kind: "transport",
        transport: legTransportFromPanelLegResult(leg.slug, reply.result),
      };
    }),
  );
  const rejection = settled.find(
    (row): row is PromiseRejectedResult => row.status === "rejected",
  );
  if (rejection !== undefined) {
    throw rejection.reason;
  }
  const rows = settled.map((row) => {
    if (row.status !== "fulfilled") {
      throw new Error("dispatchReviewPanelLegs: unreachable rejected after gate");
    }
    return row.value;
  });
  const control = rows.find(
    (row): row is { kind: "seat_control"; control: TControl } =>
      row.kind === "seat_control",
  );
  if (control !== undefined) {
    return { kind: "seat_control", control: control.control };
  }
  const results = rows.map((row) => {
    if (row.kind !== "transport") {
      throw new Error("dispatchReviewPanelLegs: unreachable non-transport after control gate");
    }
    return row.transport;
  });
  return {
    kind: "round",
    transports: results,
    skippedLegs: skippedLegsFromTransports(legs, results),
  };
}

function normalizeReviewPanelDispatchReply<TControl>(
  raw: WorkerResult | ReviewPanelDispatchReply<TControl>,
): ReviewPanelDispatchReply<TControl> {
  if (
    raw !== null &&
    typeof raw === "object" &&
    "kind" in raw &&
    (raw.kind === "leg_result" || raw.kind === "seat_control")
  ) {
    return raw;
  }
  return { kind: "leg_result", result: raw as WorkerResult };
}
