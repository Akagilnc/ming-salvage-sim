/**
 * #884 — driver stage line logs.
 * #1007 — stage lines carry issue numbers + dual-write progress.jsonl.
 *
 * One attributable line per phase entry so a silent hang can be blamed on the
 * last entered stage (recovery / smoke-k / reconcile / admission / dispatch).
 */

import {
  emitStageProgress,
  formatDriverStageLine,
  getProgressBroadcastConfig,
} from "./progressBroadcast.js";

export const DRIVER_STAGES = [
  "recovery",
  "admission",
  "reconcile",
  "smoke-k",
  "dispatch",
] as const;

export type DriverStage = (typeof DRIVER_STAGES)[number];

export interface LogDriverStageOptions {
  readonly issue?: number;
  readonly issues?: readonly number[];
  readonly step?: string;
  readonly epic?: number;
  readonly ledgerDir?: string;
}

/**
 * Emit `[orchestrator:stage] <stage> [issue #N] [detail]` — one line, always.
 * When progress broadcast is configured (or ledgerDir is passed), also append
 * a schema'd stage row to progress.jsonl (fail-open).
 */
export function logDriverStage(
  stage: DriverStage,
  detail?: string,
  opts?: LogDriverStageOptions,
): void {
  console.log(formatDriverStageLine(stage, detail, opts));

  const cfg = getProgressBroadcastConfig();
  const ledgerDir = opts?.ledgerDir ?? cfg.ledgerDir;
  const epic = opts?.epic ?? cfg.epic;
  // Always emit progress when we have a feed target OR an issue id to surface.
  // Without ledgerDir the emit still prints the progress line (run.log dual
  // channel) only when configured — avoid double console lines on bare tests.
  if (ledgerDir !== undefined) {
    const issue =
      opts?.issue ??
      (opts?.issues !== undefined && opts.issues.length === 1
        ? opts.issues[0]
        : undefined);
    const multiIssuesDetail =
      opts?.issues !== undefined && opts.issues.length > 1
        ? `issues=${opts.issues.map((n) => `#${n}`).join(",")}`
        : undefined;
    const progressDetail = [detail, multiIssuesDetail]
      .filter((s): s is string => s !== undefined && s.trim().length > 0)
      .join(" ");
    emitStageProgress({
      ledgerDir,
      stage,
      issue: issue ?? null,
      epic: epic ?? null,
      step: opts?.step ?? null,
      detail: progressDetail.length > 0 ? progressDetail : null,
      // stage line already printed via formatDriverStageLine — suppress the
      // second progress log line so run.log stays one line per stage entry.
      log: () => {},
    });
  }
}
