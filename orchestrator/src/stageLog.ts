/**
 * #884 — driver stage line logs.
 *
 * One attributable line per phase entry so a silent hang can be blamed on the
 * last entered stage (recovery / smoke-k / reconcile / admission / dispatch).
 */

export const DRIVER_STAGES = [
  "recovery",
  "admission",
  "reconcile",
  "smoke-k",
  "dispatch",
] as const;

export type DriverStage = (typeof DRIVER_STAGES)[number];

/** Emit `[orchestrator:stage] <stage> [detail]` — one line, always. */
export function logDriverStage(stage: DriverStage, detail?: string): void {
  const suffix =
    detail !== undefined && detail.trim().length > 0 ? ` ${detail.trim()}` : "";
  console.log(`[orchestrator:stage] ${stage}${suffix}`);
}
