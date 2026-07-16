/**
 * Family worker → model-route slot mapping (#919 F4 extract from verifyCmr).
 *
 * Pure helpers used to scope baton billingPool to wall roles only. Kept out of
 * the verifyCmr god module so slot policy has a single small home.
 */

import type { ModelRouteSlot } from "../modelRoutes.js";
import type { IntegratedCmrPass } from "./types.js";
import type { WorkerSpec } from "../types.js";

/**
 * Map a family worker kind (+ optional cmr pass) to the route slot it consumes.
 * Used to scope baton billingPool to wall roles only (F2).
 */
export function familyWorkerSlotForDispatch(
  kind: WorkerSpec["kind"],
  cmrPass?: IntegratedCmrPass | string,
): ModelRouteSlot | undefined {
  switch (kind) {
    case "cmr":
      return cmrPass === "correctness" ? "cmrCorrectness" : "cmrCompleteness";
    case "ship":
      return "ship";
    case "coder":
      return "coderFix";
    case "verify":
      return "verify";
    case "fixer":
      return "fixer";
    case "docRelease":
      return "docRelease";
    default:
      return undefined;
  }
}

/**
 * Resolve DispatchContext.billingPool for a family worker.
 * - No pool → undefined
 * - Pool without slots (explicit test / unscoped) → pool for every worker
 * - Pool + slots → only wall-role workers on listed slots get the rewrite
 */
export function billingPoolForFamilyWorker(opts: {
  readonly billingPool?: string;
  readonly billingPoolSlots?: ReadonlyArray<ModelRouteSlot>;
  readonly kind: WorkerSpec["kind"];
  readonly cmrPass?: IntegratedCmrPass | string;
}): string | undefined {
  if (opts.billingPool === undefined) return undefined;
  if (opts.billingPoolSlots === undefined || opts.billingPoolSlots.length === 0) {
    return opts.billingPool;
  }
  const slot = familyWorkerSlotForDispatch(opts.kind, opts.cmrPass);
  if (slot === undefined) return undefined;
  return opts.billingPoolSlots.includes(slot) ? opts.billingPool : undefined;
}
