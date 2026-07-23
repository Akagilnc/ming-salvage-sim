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
};

/** Stamped panel evidence for one court opening (#1117 / #1118). */
export type PanelCourtEvidence = {
  readonly openingId: string;
  readonly cmrPass: IntegratedCmrPass;
  readonly familyHeadAfter?: string;
  readonly runId?: string;
  readonly transports: ReadonlyArray<LegTransport>;
  readonly skippedLegs: ReadonlyArray<CmrSkippedLeg>;
};

/**
 * True when at least one transport is legal ADR 0141 review paper.
 * Used by the court-open gate: valid same-opening evidence → no reburn.
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
 * Mint a runner-owned panel court opening id.
 * Always includes a fresh UUID so process re-entry / missing runId never collides
 * with a prior opening (same pass+head still gets a new id → reburn).
 */
export function mintPanelCourtOpeningId(input: {
  readonly runId?: string;
  readonly cmrPass: IntegratedCmrPass;
}): string {
  const runPart =
    typeof input.runId === "string" && input.runId.trim().length > 0
      ? input.runId.trim()
      : "norun";
  return `${runPart}:${input.cmrPass}:${globalThis.crypto.randomUUID()}`;
}

/**
 * Build stamped evidence from runner landing/ctx cargo when present and legal.
 * Production seed path for "landing already has valid transports" (#1118 AC).
 */
export function panelCourtEvidenceFromLanding(input: {
  readonly cmrPass: IntegratedCmrPass;
  readonly familyHeadAfter?: string;
  readonly runId?: string;
  readonly panelCourtOpeningId?: string;
  readonly panelLegTransports?: ReadonlyArray<{
    readonly slug: string;
    readonly exitCode: number;
    readonly stdout: string | null | undefined;
  }>;
  readonly panelLegSkippedLegs?: ReadonlyArray<{
    readonly slug: string;
    readonly reason: string;
  }>;
}): PanelCourtEvidence | undefined {
  const openingId = input.panelCourtOpeningId?.trim();
  if (openingId === undefined || openingId.length === 0) return undefined;
  const rows = input.panelLegTransports;
  if (rows === undefined || rows.length === 0) return undefined;
  const transports: LegTransport[] = [];
  for (const row of rows) {
    if (typeof row.slug !== "string" || row.slug.trim().length === 0) continue;
    if (typeof row.exitCode !== "number" || !Number.isFinite(row.exitCode)) {
      continue;
    }
    transports.push({
      slug: row.slug.trim(),
      exitCode: row.exitCode,
      stdout: typeof row.stdout === "string" ? row.stdout : "",
    });
  }
  if (!hasValidPanelLegTransports(transports)) return undefined;
  return {
    openingId,
    cmrPass: input.cmrPass,
    ...(input.familyHeadAfter !== undefined
      ? { familyHeadAfter: input.familyHeadAfter }
      : {}),
    ...(input.runId !== undefined ? { runId: input.runId } : {}),
    transports,
    skippedLegs: [...(input.panelLegSkippedLegs ?? [])],
  };
}

/**
 * #1117 / #1118 — lifecycle-scoped panel court session (one per family court
 * loop / process-held baton). Callers own the instance; invalidate on builder.
 */
export type PanelCourtSession = {
  /**
   * Resolve opening + optional reusable evidence.
   * Force reburn when: escalationAnswer, empty/invalid memo, pass/head/runId
   * mismatch. Same pass+head with a new opening id always reburns after
   * invalidate or escalationAnswer.
   */
  readonly resolve: (input: {
    readonly cmrPass: IntegratedCmrPass;
    readonly familyHeadAfter?: string;
    readonly runId?: string;
    readonly escalationAnswerPresent?: boolean;
  }) => {
    readonly openingId: string;
    readonly existing: PanelCourtEvidence | undefined;
  };
  /** Install runner landing/ctx stamped evidence as the current memo (same opening). */
  readonly seedFromLanding: (evidence: PanelCourtEvidence) => void;
  readonly record: (evidence: PanelCourtEvidence) => void;
  /** Drop memo so the next resolve mints a new opening (builder / head move). */
  readonly invalidate: () => void;
};

export function createPanelCourtSession(): PanelCourtSession {
  let memo: PanelCourtEvidence | undefined;
  return {
    resolve(input) {
      const forceReburn =
        input.escalationAnswerPresent === true ||
        memo === undefined ||
        memo.cmrPass !== input.cmrPass ||
        (input.familyHeadAfter !== undefined &&
          memo.familyHeadAfter !== input.familyHeadAfter) ||
        (input.runId !== undefined &&
          memo.runId !== undefined &&
          memo.runId !== input.runId) ||
        (input.runId !== undefined && memo.runId === undefined) ||
        (input.runId === undefined && memo.runId !== undefined);
      if (
        !forceReburn &&
        memo !== undefined &&
        hasValidPanelLegTransports(memo.transports)
      ) {
        return { openingId: memo.openingId, existing: memo };
      }
      const openingId = mintPanelCourtOpeningId({
        ...(input.runId !== undefined ? { runId: input.runId } : {}),
        cmrPass: input.cmrPass,
      });
      return { openingId, existing: undefined };
    },
    seedFromLanding(evidence) {
      if (
        hasValidPanelLegTransports(evidence.transports) &&
        evidence.openingId.trim().length > 0
      ) {
        memo = evidence;
      }
    },
    record(evidence) {
      memo = evidence;
    },
    invalidate() {
      memo = undefined;
    },
  };
}

/**
 * #1117 / #1118 — one panel-evidence gate for first open and court resume.
 *
 * Mechanism is only {@link dispatchFamilyCmrPanelLegs} (scope is a parameter).
 * Reuse when caller supplies same-opening valid evidence; otherwise fan-out.
 */
export async function ensureFamilyCmrPanelEvidence(input: {
  readonly legs: ReadonlyArray<WorkerCmrReviewLeg>;
  readonly cmrPass?: IntegratedCmrPass;
  readonly openingId: string;
  readonly existing?: PanelCourtEvidence;
  readonly dispatch: (spec: WorkerSpec) => Promise<WorkerResult>;
}): Promise<PanelLegsRoundResult & { readonly openingId: string }> {
  const legs = input.legs;
  const existing = input.existing;
  if (
    existing !== undefined &&
    existing.openingId === input.openingId &&
    hasValidPanelLegTransports(existing.transports)
  ) {
    return {
      openingId: input.openingId,
      transports: existing.transports,
      skippedLegs:
        existing.skippedLegs.length > 0
          ? existing.skippedLegs
          : skippedLegsFromTransports(legs, existing.transports),
    };
  }
  const round = await dispatchFamilyCmrPanelLegs({
    legs,
    ...(input.cmrPass !== undefined ? { cmrPass: input.cmrPass } : {}),
    dispatch: input.dispatch,
  });
  return {
    openingId: input.openingId,
    transports: round.transports,
    skippedLegs: round.skippedLegs,
  };
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
    return { transports: [], skippedLegs: [] };
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
  };
}
