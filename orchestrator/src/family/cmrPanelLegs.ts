/**
 * #1094 — family CMR panel legs as runner-dispatched first-class workers.
 *
 * Panel legs are isomorphic to the single-slice fresh reviewer path:
 *   - same WorkerSpec / dispatchWorker mechanism
 *   - sandcastle injects credentials for the top-level agent (no nested-CLI mounts)
 *   - reviewer soul text prepended to the leg prompt
 *   - independent-clone semantics preserved at the backend seam
 *   - cross-vendor family → distinct CLI host via {@link workerHostForModel}
 *
 * The family judge receives their prose transports as inputs and emits the
 * unified typed verdict — it never spawns model CLIs.
 */

import { workerHostForModel } from "../dispatchWorker.js";
import {
  isLegalLegPaper,
  successfulLegsFromTransports,
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

/** Completeness-pass panel-leg prompt (Clause–Wire–Exercise). */
export const CMR_PANEL_LEG_COMPLETENESS_PROMPT_FILE =
  "cmr_panel_leg_completeness.md";
/** Correctness-pass panel-leg prompt (Trace–Break–Prove). */
export const CMR_PANEL_LEG_CORRECTNESS_PROMPT_FILE =
  "cmr_panel_leg_correctness.md";

/**
 * One authoritative prompt source per CMR pass lens — no shared duplicate body.
 */
export function cmrPanelLegPromptFile(pass: IntegratedCmrPass): string {
  return pass === "completeness"
    ? CMR_PANEL_LEG_COMPLETENESS_PROMPT_FILE
    : CMR_PANEL_LEG_CORRECTNESS_PROMPT_FILE;
}

/** True when promptFile is one of the pass-keyed panel-leg lens sources. */
export function isCmrPanelLegPromptFile(promptFile: string): boolean {
  return (
    promptFile === CMR_PANEL_LEG_COMPLETENESS_PROMPT_FILE ||
    promptFile === CMR_PANEL_LEG_CORRECTNESS_PROMPT_FILE
  );
}

/**
 * Declarative WorkerSpec for one route-selected CMR panel leg.
 * Fresh / clean / READ-ONLY — never resume a prior leg session.
 * Prompt is keyed by {@link IntegratedCmrPass} (pass-distinct lenses).
 */
export function cmrPanelLegWorkerSpec(
  leg: WorkerCmrReviewLeg,
  pass: IntegratedCmrPass = "correctness",
): WorkerSpec {
  const model = leg.slug;
  return {
    // Seat remains the family CMR court (S3); per-leg job/log uniqueness is the
    // monitor dispatchId substrate (#1094 F1) — not a new StepId.
    id: "S3",
    kind: "reviewer",
    role: "reviewer",
    host: workerHostForModel(model),
    session: "fresh",
    contextRetention: "clean",
    promptFile: cmrPanelLegPromptFile(pass),
    maxIter: 1,
    model,
    soul: "READ-ONLY",
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
  /**
   * #1117 / #1118 / #1119 — true when this round actually dispatched (or
   * degraded) legs; false when valid prior transports were reused (no reburn).
   */
  readonly dispatched: boolean;
};

/**
 * True when at least one transport is legal ADR 0141 review paper.
 * Court-open gate: valid evidence → no reburn; absent → fan-out.
 */
export function hasValidPanelLegTransports(
  transports: ReadonlyArray<LegTransport> | undefined | null,
): boolean {
  if (transports === undefined || transports === null || transports.length === 0) {
    return false;
  }
  return successfulLegsFromTransports(transports).length > 0;
}

/**
 * Normalize landing/ctx transport cargo into {@link LegTransport} rows.
 * Invalid rows are dropped (never invent legal paper).
 */
export function normalizePanelLegTransportCargo(
  rows:
    | ReadonlyArray<{
        readonly slug?: unknown;
        readonly exitCode?: unknown;
        readonly stdout?: unknown;
      }>
    | undefined
    | null,
): LegTransport[] {
  if (rows === undefined || rows === null || rows.length === 0) return [];
  const out: LegTransport[] = [];
  for (const row of rows) {
    if (typeof row.slug !== "string" || row.slug.trim().length === 0) continue;
    if (typeof row.exitCode !== "number" || !Number.isFinite(row.exitCode)) {
      continue;
    }
    out.push({
      slug: row.slug.trim(),
      exitCode: row.exitCode,
      stdout: typeof row.stdout === "string" ? row.stdout : "",
    });
  }
  return out;
}

/**
 * #1117 / #1118 / #1119 — one panel-evidence gate for first open, in-process
 * resume, and cold-start ledger re-entry.
 *
 * Mechanism is only {@link dispatchFamilyCmrPanelLegs} (scope is a parameter).
 * When valid transports already land, do not reburn; when missing (resume after
 * claimed-fixed re-review, human "rerun jury", empty landing after process exit),
 * fan-out again and land transports or host skip reasons — never open a pure
 * court on silent empty.
 */
export async function ensureFamilyCmrPanelEvidence(input: {
  readonly legs: ReadonlyArray<WorkerCmrReviewLeg>;
  readonly cmrPass?: IntegratedCmrPass;
  readonly existingTransports?:
    | ReadonlyArray<{
        readonly slug?: unknown;
        readonly exitCode?: unknown;
        readonly stdout?: unknown;
      }>
    | undefined;
  readonly dispatch: (spec: WorkerSpec) => Promise<WorkerResult>;
}): Promise<PanelLegsRoundResult> {
  const legs = input.legs;
  const existing = normalizePanelLegTransportCargo(input.existingTransports);
  if (hasValidPanelLegTransports(existing)) {
    return {
      transports: existing,
      skippedLegs: skippedLegsFromTransports(legs, existing),
      dispatched: false,
    };
  }
  const round = await dispatchFamilyCmrPanelLegs({
    legs,
    ...(input.cmrPass !== undefined ? { cmrPass: input.cmrPass } : {}),
    dispatch: input.dispatch,
  });
  return { ...round, dispatched: legs.length > 0 };
}

/**
 * Runner-owned panel-leg fan-out for one family CMR court round (#1094).
 * Dispatches N first-class reviewer workers (parallel), then rebuilds
 * ADR 0141 transports for the pure judge court.
 */
export async function dispatchFamilyCmrPanelLegs(input: {
  readonly legs: ReadonlyArray<WorkerCmrReviewLeg>;
  readonly cmrPass?: IntegratedCmrPass;
  readonly dispatch: (
    spec: WorkerSpec,
  ) => Promise<WorkerResult>;
}): Promise<PanelLegsRoundResult> {
  const legs = input.legs;
  const pass = input.cmrPass ?? "correctness";
  if (legs.length === 0) {
    return { transports: [], skippedLegs: [], dispatched: false };
  }
  // #1094 F3: Promise.all drops sibling rejections as unhandled after the first
  // park/relay throw. Settle every leg first, then rethrow one rejection.
  const settled = await Promise.allSettled(
    legs.map(async (leg) => {
      const degraded = degradedTransportForNonRunnablePanelLeg(leg.slug);
      if (degraded !== undefined) {
        return degraded;
      }
      const spec = cmrPanelLegWorkerSpec(leg, pass);
      const result = await input.dispatch(spec);
      return legTransportFromPanelLegResult(leg.slug, result);
    }),
  );
  const rejection = settled.find(
    (row): row is PromiseRejectedResult => row.status === "rejected",
  );
  if (rejection !== undefined) {
    throw rejection.reason;
  }
  const results = settled.map((row) => {
    if (row.status !== "fulfilled") {
      throw new Error("dispatchFamilyCmrPanelLegs: unreachable rejected after gate");
    }
    return row.value;
  });
  return {
    transports: results,
    skippedLegs: skippedLegsFromTransports(legs, results),
    dispatched: true,
  };
}
