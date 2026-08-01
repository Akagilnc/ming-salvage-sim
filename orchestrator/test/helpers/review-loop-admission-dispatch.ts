/**
 * Test harness for family fakes that deleted ungated skeleton shortcuts.
 *
 * Production keeps one PR handle after ship (`resolveShippedPrUrl` → canonical
 * https for the ledger and the online-review loop's poll ctx). Live poll stays
 * on that https URL via setup-route-env gh mocks.
 *
 * Review-loop verify/fixer/landing, however, only admit skeleton through the
 * real gate (`offlineReviewLoopDispatchAdmissible`): `pr://…` +
 * `ORCHESTRATOR_OFFLINE_REVIEW_POLL=1`. These seams differ — ledger/poll keep
 * the canonical URL; dispatch ctx for skeleton is a synthetic test handle.
 *
 * Never call {@link skeletonReviewLoopWorkerResult} from a fake without this
 * (or an equivalent) admission path.
 */
import { legacyDispatchFamilyWorker } from "../../src/family/dispatchFamilyWorker.js";
import type { FamilyBackend } from "../../src/family/types.js";
import type {
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";
import { completeReviewPanelLegWorker } from "./review-panel-leg-dispatch.js";

export async function dispatchReviewLoopThroughAdmission(
  familyBackend: FamilyBackend,
  spec: WorkerSpec,
  ctx: DispatchContext,
): Promise<WorkerResult> {
  // #1094: panel legs are first-class reviewer workers — test fakes auto-complete
  // legal ADR 0141 prose (never fall through to unsupported-kind throws).
  const panelLeg = completeReviewPanelLegWorker(spec);
  if (panelLeg !== undefined) return panelLeg;

  if (
    spec.kind !== "collector" &&
    spec.kind !== "verify" &&
    spec.kind !== "fixer" &&
    spec.kind !== "landing"
  ) {
    return legacyDispatchFamilyWorker(familyBackend, spec, ctx);
  }

  const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
  process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
  try {
    const familyBase = ctx.familyBase ?? "family/offline";
    const trimmed = ctx.prUrl?.trim() ?? "";
    const prUrl = trimmed.startsWith("pr://")
      ? trimmed
      : `pr://family/offline-dispatch/${encodeURIComponent(familyBase)}`;
    return legacyDispatchFamilyWorker(familyBackend, spec, {
      ...ctx,
      prUrl,
    });
  } finally {
    if (prev === undefined) {
      delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    } else {
      process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
    }
  }
}
