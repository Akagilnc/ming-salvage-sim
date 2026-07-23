import {
  isReviewPanelLegPromptFile,
  panelLegCompletedResult,
} from "../../src/family/cmrPanelLegs.js";
import type { WorkerResult, WorkerSpec } from "../../src/types.js";

const DEFAULT_PANEL_LEG_STDOUT =
  "fixture panel leg review prose (ADR 0141 legal paper)";

/** True when spec is a #1094/#1126 runner-owned review-panel leg. */
export function isCmrPanelLegWorker(spec: WorkerSpec): boolean {
  return (
    spec.kind === "reviewer" &&
    spec.role === "reviewer" &&
    isReviewPanelLegPromptFile(spec.promptFile)
  );
}

/**
 * Auto-complete a review-panel leg with legal ADR 0141 prose.
 * Returns undefined for non-panel workers so callers fall through.
 */
export function completeCmrPanelLegWorker(
  spec: WorkerSpec,
  stdout: string = DEFAULT_PANEL_LEG_STDOUT,
): WorkerResult | undefined {
  if (!isCmrPanelLegWorker(spec)) return undefined;
  return panelLegCompletedResult(stdout);
}
