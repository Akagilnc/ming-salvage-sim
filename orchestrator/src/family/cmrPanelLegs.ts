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

/** Current court scope for durable panel-evidence identity (#1118). */
export type PanelLegEvidenceScope = {
  readonly familyHeadAfter?: string;
  readonly ledgerPhase: "final" | "correctness_checkpoint";
  /** Declared panel-leg roster only (not full model route). */
  readonly panelLegsFingerprint: string;
};

/**
 * Stable fingerprint of the declared panel-leg roster for this court open.
 * Only slug/family/optional — never coder/ship/online worker slots.
 */
export function panelLegsRosterFingerprint(
  legs: ReadonlyArray<{
    readonly family: string;
    readonly slug: string;
    readonly optional?: true;
  }>,
): string {
  const rows = legs
    .map((leg) =>
      leg.optional === true
        ? ([leg.family, leg.slug, true] as const)
        : ([leg.family, leg.slug] as const),
    )
    .sort((a, b) => {
      const aFamily = a[0] ?? "";
      const bFamily = b[0] ?? "";
      if (aFamily !== bFamily) return aFamily < bFamily ? -1 : 1;
      const aSlug = a[1] ?? "";
      const bSlug = b[1] ?? "";
      if (aSlug !== bSlug) return aSlug < bSlug ? -1 : 1;
      return 0;
    });
  return JSON.stringify(rows);
}

/**
 * Normalize landing/ctx/durable transport cargo into {@link LegTransport} rows.
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
 * Normalize host skip rows into {@link CmrSkippedLeg}. Invalid rows dropped.
 */
export function normalizePanelLegSkippedCargo(
  rows:
    | ReadonlyArray<{
        readonly slug?: unknown;
        readonly reason?: unknown;
      }>
    | undefined
    | null,
): CmrSkippedLeg[] {
  if (rows === undefined || rows === null || rows.length === 0) return [];
  const out: CmrSkippedLeg[] = [];
  for (const row of rows) {
    if (typeof row.slug !== "string" || row.slug.trim().length === 0) continue;
    if (typeof row.reason !== "string" || row.reason.trim().length === 0) continue;
    out.push({ slug: row.slug.trim(), reason: row.reason.trim() });
  }
  return out;
}

/**
 * Shape-safe parse of durable panel-leg evidence JSON.
 * Malformed / wrong-shape → undefined (treat as no reusable evidence; fan-out).
 * Never bare-casts arrays that callers later `.map`.
 */
export function parseFamilyPanelLegEvidence(
  value: unknown,
):
  | {
      readonly familyHeadAfter?: string;
      readonly ledgerPhase?: "final" | "correctness_checkpoint";
      readonly panelLegsFingerprint?: string;
      readonly panelLegTransports?: ReadonlyArray<LegTransport>;
      readonly panelLegSkippedLegs?: ReadonlyArray<CmrSkippedLeg>;
    }
  | undefined {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const rec = value as Record<string, unknown>;
  const familyHeadAfter =
    typeof rec.familyHeadAfter === "string" && rec.familyHeadAfter.trim().length > 0
      ? rec.familyHeadAfter.trim()
      : undefined;
  const ledgerPhase =
    rec.ledgerPhase === "final" || rec.ledgerPhase === "correctness_checkpoint"
      ? rec.ledgerPhase
      : undefined;
  const panelLegsFingerprintRaw =
    typeof rec.panelLegsFingerprint === "string"
      ? rec.panelLegsFingerprint
      : undefined;
  const panelLegsFingerprint =
    typeof panelLegsFingerprintRaw === "string" &&
    panelLegsFingerprintRaw.length > 0
      ? panelLegsFingerprintRaw
      : undefined;
  // Wrong-type transports/skips (object, number, string) → treat as absent,
  // not as cast-array-that-throws on .map.
  const panelLegTransports = Array.isArray(rec.panelLegTransports)
    ? normalizePanelLegTransportCargo(rec.panelLegTransports)
    : undefined;
  const panelLegSkippedLegs = Array.isArray(rec.panelLegSkippedLegs)
    ? normalizePanelLegSkippedCargo(rec.panelLegSkippedLegs)
    : undefined;
  // Require at least one known field so garbage objects do not pass as evidence.
  if (
    familyHeadAfter === undefined &&
    ledgerPhase === undefined &&
    panelLegsFingerprint === undefined &&
    panelLegTransports === undefined &&
    panelLegSkippedLegs === undefined
  ) {
    return undefined;
  }
  return {
    ...(familyHeadAfter !== undefined ? { familyHeadAfter } : {}),
    ...(ledgerPhase !== undefined ? { ledgerPhase } : {}),
    ...(panelLegsFingerprint !== undefined ? { panelLegsFingerprint } : {}),
    ...(panelLegTransports !== undefined && panelLegTransports.length > 0
      ? { panelLegTransports }
      : {}),
    ...(panelLegSkippedLegs !== undefined && panelLegSkippedLegs.length > 0
      ? { panelLegSkippedLegs }
      : {}),
  };
}

/**
 * Durable evidence is admissible only when court identity matches
 * (head + barrier phase + declared panel-leg roster) AND transports contain
 * legal paper. Missing identity fields fail closed (no silent reuse).
 * No self-authorizing generation counter.
 */
export type AdmissiblePanelLegEvidence = {
  readonly transports: ReadonlyArray<LegTransport>;
  readonly skippedLegs: ReadonlyArray<CmrSkippedLeg>;
};

export function admissibleDurablePanelLegEvidence(
  evidence:
    | {
        readonly familyHeadAfter?: string;
        readonly ledgerPhase?: string;
        readonly panelLegsFingerprint?: string;
        readonly panelLegTransports?: ReadonlyArray<{
          readonly slug?: unknown;
          readonly exitCode?: unknown;
          readonly stdout?: unknown;
        }>;
        readonly panelLegSkippedLegs?: ReadonlyArray<{
          readonly slug?: unknown;
          readonly reason?: unknown;
        }>;
      }
    | undefined
    | null,
  scope: PanelLegEvidenceScope,
): AdmissiblePanelLegEvidence | undefined {
  if (evidence === undefined || evidence === null) return undefined;
  const durableHead =
    typeof evidence.familyHeadAfter === "string"
      ? evidence.familyHeadAfter.trim()
      : "";
  const currentHead =
    typeof scope.familyHeadAfter === "string"
      ? scope.familyHeadAfter.trim()
      : "";
  if (durableHead.length === 0 || currentHead.length === 0) return undefined;
  if (durableHead !== currentHead) return undefined;
  if (evidence.ledgerPhase !== scope.ledgerPhase) return undefined;
  if (
    typeof evidence.panelLegsFingerprint !== "string" ||
    evidence.panelLegsFingerprint.length === 0 ||
    evidence.panelLegsFingerprint !== scope.panelLegsFingerprint
  ) {
    return undefined;
  }
  const transports = normalizePanelLegTransportCargo(
    evidence.panelLegTransports,
  );
  const skippedLegs = normalizePanelLegSkippedCargo(
    evidence.panelLegSkippedLegs,
  );
  if (!hasValidPanelLegTransports(transports) && skippedLegs.length === 0) {
    return undefined;
  }
  return { transports, skippedLegs };
}

/**
 * #1117 / #1118 — one panel-evidence gate for first open and court resume.
 *
 * Mechanism is only {@link dispatchFamilyCmrPanelLegs} (scope is a parameter).
 * When valid transports already land (ctx / durable cargo), do not reburn; when
 * missing, fan-out and land transports or host skip reasons — never open a pure
 * court on silent empty. Cargo ownership is the FamilyBackend durable store
 * (production) or host landing/ctx — not optional test-only VerifyCmrInput seams.
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
  readonly existingSkippedLegs?: ReadonlyArray<{
    readonly slug?: unknown;
    readonly reason?: unknown;
  }>;
  readonly dispatch: (spec: WorkerSpec) => Promise<WorkerResult>;
}): Promise<PanelLegsRoundResult> {
  const legs = input.legs;
  const existing = normalizePanelLegTransportCargo(input.existingTransports);
  const existingSkippedLegs = normalizePanelLegSkippedCargo(
    input.existingSkippedLegs,
  );
  if (hasValidPanelLegTransports(existing) || existingSkippedLegs.length > 0) {
    return {
      transports: existing,
      skippedLegs:
        existingSkippedLegs.length > 0
          ? existingSkippedLegs
          : skippedLegsFromTransports(legs, existing),
    };
  }
  return dispatchFamilyCmrPanelLegs({
    legs,
    ...(input.cmrPass !== undefined ? { cmrPass: input.cmrPass } : {}),
    dispatch: input.dispatch,
  });
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
