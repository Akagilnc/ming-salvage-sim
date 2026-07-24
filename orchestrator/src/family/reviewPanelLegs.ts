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
 * typed verdict — it never spawns model CLIs. Single-slice Standards/Spec are
 * two Runner-owned fresh workers (never one worker that re-invokes /code-review).
 */

import { workerHostForModel } from "../dispatchWorker.js";
import type { LegTransport } from "../legPaper.js";
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

/** Single-slice Standards-axis review leg (#1126). */
export const CODE_REVIEW_STANDARDS_LEG_PROMPT_FILE =
  "code_review_standards_leg.md";

/** Single-slice Spec-axis review leg (#1126). */
export const CODE_REVIEW_SPEC_LEG_PROMPT_FILE = "code_review_spec_leg.md";

/** Single-slice review axis — one Runner-owned worker per axis. */
export type ReviewPanelAxis = "standards" | "spec";

/**
 * Declared review-panel leg. Family legs omit {@link axis}; single-slice
 * Standards/Spec legs set it so transport ids stay unique for same-model pairs.
 */
export type ReviewPanelLeg = WorkerCmrReviewLeg & {
  readonly axis?: ReviewPanelAxis;
};

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
    promptFile === CODE_REVIEW_STANDARDS_LEG_PROMPT_FILE ||
    promptFile === CODE_REVIEW_SPEC_LEG_PROMPT_FILE
  );
}

/** Transport identity — axis-qualified when single-slice shares a model slug. */
export function reviewPanelTransportId(leg: ReviewPanelLeg): string {
  return leg.axis !== undefined ? `${leg.slug}:${leg.axis}` : leg.slug;
}

function singleAxisPromptFile(axis: ReviewPanelAxis): string {
  return axis === "standards"
    ? CODE_REVIEW_STANDARDS_LEG_PROMPT_FILE
    : CODE_REVIEW_SPEC_LEG_PROMPT_FILE;
}

/**
 * Declarative WorkerSpec for one route-selected review leg.
 * Fresh / clean — never resume a prior leg session.
 * Family pass selects a CMR lens soul + family task; single-slice uses
 * READ-ONLY + one axis-specific task (never /code-review fan-out).
 */
export function reviewPanelLegWorkerSpec(
  leg: ReviewPanelLeg,
  scope: ReviewLegScope,
): WorkerSpec {
  const model = leg.slug;
  if (scope.kind === "single" && leg.axis === undefined) {
    throw new Error(
      "reviewPanelLegWorkerSpec: single-slice legs require axis (standards|spec)",
    );
  }
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
        ? singleAxisPromptFile(leg.axis!)
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
 * Strip judge-bound baton fields so fresh panel legs keep their own provider
 * and full process-root retry budget (#1094 R3 F2 / #1080 R3).
 */
export function omitJudgeBoundDispatchFields<
  T extends {
    readonly billingPool?: string;
    readonly resumeSessionId?: string;
  },
>(ctx: T): Omit<T, "billingPool" | "resumeSessionId"> {
  const { billingPool: _judgePool, resumeSessionId: _judgeResume, ...rest } =
    ctx;
  void _judgePool;
  void _judgeResume;
  return rest;
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

/** Declared legs absent from transport or exiting non-zero are skipped. */
export function skippedLegsFromTransports(
  declared: ReadonlyArray<ReviewPanelLeg>,
  transports: ReadonlyArray<LegTransport>,
): CmrSkippedLeg[] {
  const byId = new Map(transports.map((t) => [t.slug, t]));
  const skipped: CmrSkippedLeg[] = [];
  for (const leg of declared) {
    const id = reviewPanelTransportId(leg);
    const transport = byId.get(id);
    if (transport !== undefined && transport.exitCode === 0) continue;
    skipped.push({
      slug: id,
      reason: degradeReasonForTransport(id, transport),
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
  return `panel leg ${slug} failed (exit ${transport.exitCode})`;
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
 * One mechanism for family CMR and single-slice axis legs; scope is required.
 * Settles every leg first (#1094 F3), then either returns seat_control or
 * rethrows one real rejection — never leaves sibling rejections unhandled.
 *
 * `dispatch` returns only {@link ReviewPanelDispatchReply} (family wraps
 * WorkerResult explicitly — no normalize/cast dual API).
 */
export async function dispatchReviewPanelLegs<TControl = never>(input: {
  readonly legs: ReadonlyArray<ReviewPanelLeg>;
  readonly scope: ReviewLegScope;
  readonly dispatch: (
    spec: WorkerSpec,
  ) => Promise<ReviewPanelDispatchReply<TControl>>;
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
      const transportId = reviewPanelTransportId(leg);
      const degraded = degradedTransportForNonRunnablePanelLeg(leg.slug);
      if (degraded !== undefined) {
        return {
          kind: "transport",
          transport: { ...degraded, slug: transportId },
        };
      }
      const spec = reviewPanelLegWorkerSpec(leg, scope);
      const reply = await input.dispatch(spec);
      if (reply.kind === "seat_control") {
        return { kind: "seat_control", control: reply.control };
      }
      return {
        kind: "transport",
        transport: legTransportFromPanelLegResult(transportId, reply.result),
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
