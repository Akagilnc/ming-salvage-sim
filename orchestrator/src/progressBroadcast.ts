/**
 * #1007 — active progress broadcast (typed signals only).
 *
 * Append-only `<ledgerDir>/progress.jsonl` + run.log lines so operators answer
 * "where is each issue / latest verdict / parks" without hand-scanning
 * steps.jsonl. Echoes only runner-held typed signals and ledger rows — never
 * worker prose (ADR 0131). Finding detail is path pointers only.
 *
 * I/O is fail-open (same treatment as #786 telemetry): append / notify failures
 * never block the main flow.
 */

import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import type { ChildProcess } from "node:child_process";

import { spawnDetached } from "./externalCall.js";
import type {
  Finding,
  JudgeFindingDisposition,
  JudgeVerdictStatus,
} from "./types.js";

// ─── constants ───────────────────────────────────────────────────────────────

export const PROGRESS_SCHEMA_VERSION = 1 as const;
export const PROGRESS_FILENAME = "progress.jsonl";

/** Env: shell command to run on park / escalate / terminal. Default off. */
export const PROGRESS_NOTIFY_ENV = "ORCHESTRATOR_NOTIFY_CMD";

// ─── process config (ledgerDir / epic for dual-write from stageLog) ──────────

export interface ProgressBroadcastConfig {
  readonly ledgerDir?: string;
  readonly epic?: number;
}

let progressConfig: ProgressBroadcastConfig = {};

/**
 * Install / merge process-level progress feed config.
 *
 * Lifecycle: process-global for one orchestration entry (family driver or
 * single-slice runner binds `ledgerDir` as soon as it is known). Tests must
 * call {@link clearProgressBroadcastConfig} between cases — production does
 * not clear on family exit (next entry re-binds / merges).
 */
export function configureProgressBroadcast(
  cfg: ProgressBroadcastConfig,
): void {
  progressConfig = { ...progressConfig, ...cfg };
}

/** Clear process-level config (tests / isolation). */
export function clearProgressBroadcastConfig(): void {
  progressConfig = {};
}

/** Read current process-level config (tests / status). */
export function getProgressBroadcastConfig(): ProgressBroadcastConfig {
  return progressConfig;
}

export function progressPath(ledgerDir: string): string {
  return join(ledgerDir, PROGRESS_FILENAME);
}

// ─── disposition / severity counters (pure; typed envelope only) ─────────────

export interface ProgressDispositionCounts {
  readonly fix_now: number;
  readonly refuted: number;
  readonly suppressed: number;
}

export interface ProgressSeverityCounts {
  readonly critical: number;
  readonly high: number;
  readonly medium: number;
  readonly low: number;
  readonly clarity: number;
}

/**
 * Map judge disposition actions → operator counts.
 * live → fix_now; refute → refuted; suppress → suppressed.
 */
export function countJudgeDispositions(
  rows: ReadonlyArray<JudgeFindingDisposition> | undefined,
): ProgressDispositionCounts {
  let fix_now = 0;
  let refuted = 0;
  let suppressed = 0;
  for (const row of rows ?? []) {
    if (row.action === "live") fix_now += 1;
    else if (row.action === "refute") refuted += 1;
    else if (row.action === "suppress") suppressed += 1;
  }
  return { fix_now, refuted, suppressed };
}

/** Severity histogram from typed findings cargo; null when cargo absent. */
export function countSeverityFromFindings(
  findings: ReadonlyArray<Finding> | undefined,
): ProgressSeverityCounts | null {
  if (findings === undefined) return null;
  const counts: {
    -readonly [K in keyof ProgressSeverityCounts]: number;
  } = {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
    clarity: 0,
  };
  for (const f of findings) {
    const sev = f.severity;
    if (
      sev === "critical" ||
      sev === "high" ||
      sev === "medium" ||
      sev === "low" ||
      sev === "clarity"
    ) {
      counts[sev] += 1;
    }
  }
  return counts;
}

// ─── event schema ────────────────────────────────────────────────────────────

export type ProgressEventKind =
  | "stage"
  | "judge"
  | "park"
  | "merge"
  | "ship"
  | "landing"
  | "wave_close"
  | "terminal";

interface ProgressEventBase {
  readonly v: typeof PROGRESS_SCHEMA_VERSION;
  readonly ts: string;
  readonly kind: ProgressEventKind;
  readonly epic?: number | null;
  readonly issue?: number | null;
}

export interface ProgressStageEvent extends ProgressEventBase {
  readonly kind: "stage";
  /** Driver stage token (recovery|admission|reconcile|smoke-k|dispatch) or free label. */
  readonly stage: string;
  readonly step?: string | null;
  readonly detail?: string | null;
}

export interface ProgressJudgeEvent extends ProgressEventBase {
  readonly kind: "judge";
  readonly step: string;
  readonly round?: number | null;
  readonly verdict: JudgeVerdictStatus;
  readonly dispositions: ProgressDispositionCounts;
  readonly severity?: ProgressSeverityCounts | null;
  /** Path pointer only — never finding body prose. */
  readonly cargoPointer?: string | null;
}

export interface ProgressParkEvent extends ProgressEventBase {
  readonly kind: "park";
  readonly step?: string | null;
  readonly gateSummary: string;
  readonly reason?: string | null;
}

export interface ProgressMergeEvent extends ProgressEventBase {
  readonly kind: "merge";
  readonly issue: number;
  readonly childHead?: string | null;
}

export interface ProgressShipEvent extends ProgressEventBase {
  readonly kind: "ship";
  readonly pr?: string | null;
  readonly familyHead?: string | null;
}

export interface ProgressLandingEvent extends ProgressEventBase {
  readonly kind: "landing";
  readonly pr?: string | null;
}

export interface ProgressWaveCloseEvent extends ProgressEventBase {
  readonly kind: "wave_close";
  readonly issues: readonly number[];
  readonly wave?: number | null;
}

export interface ProgressTerminalEvent extends ProgressEventBase {
  readonly kind: "terminal";
  readonly status: "completed" | "parked" | "failed";
  readonly stopReason?: string | null;
}

export type ProgressEvent =
  | ProgressStageEvent
  | ProgressJudgeEvent
  | ProgressParkEvent
  | ProgressMergeEvent
  | ProgressShipEvent
  | ProgressLandingEvent
  | ProgressWaveCloseEvent
  | ProgressTerminalEvent;

// ─── append I/O (fail-open) ──────────────────────────────────────────────────

function writeProgressLine(ledgerDir: string, event: ProgressEvent): void {
  appendFileSync(progressPath(ledgerDir), `${JSON.stringify(event)}\n`, {
    encoding: "utf8",
  });
}

/**
 * Best-effort append — mirrors telemetry tryAppend: never invent missing
 * ancestors; return false on any I/O failure.
 */
export function tryAppendProgressEvent(
  ledgerDir: string | undefined,
  event: ProgressEvent,
): boolean {
  if (ledgerDir === undefined || ledgerDir.length === 0) return false;
  try {
    if (!existsSync(ledgerDir)) {
      const parent = dirname(ledgerDir);
      if (parent === ledgerDir || parent.length === 0 || !existsSync(parent)) {
        return false;
      }
      mkdirSync(ledgerDir, { recursive: true });
    }
    writeProgressLine(ledgerDir, event);
    return true;
  } catch (err) {
    console.warn(
      `[orchestrator] progress append failed (fail-open): ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
    return false;
  }
}

export function readProgressEvents(ledgerDir: string): ProgressEvent[] {
  const path = progressPath(ledgerDir);
  if (!existsSync(path)) return [];
  try {
    const raw = readFileSync(path, "utf8");
    const out: ProgressEvent[] = [];
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (trimmed.length === 0) continue;
      try {
        const parsed = JSON.parse(trimmed) as ProgressEvent;
        if (
          parsed !== null &&
          typeof parsed === "object" &&
          parsed.v === PROGRESS_SCHEMA_VERSION &&
          typeof parsed.kind === "string"
        ) {
          out.push(parsed);
        }
      } catch {
        // skip corrupt lines (append-only feed; do not invent)
      }
    }
    return out;
  } catch {
    return [];
  }
}

// ─── run.log line formatting ─────────────────────────────────────────────────

function issueTag(issue: number | null | undefined): string {
  return issue !== undefined && issue !== null ? ` issue #${issue}` : "";
}

function epicTag(epic: number | null | undefined): string {
  return epic !== undefined && epic !== null ? ` epic #${epic}` : "";
}

export function formatProgressLogLine(event: ProgressEvent): string {
  const base = `[orchestrator:progress]`;
  switch (event.kind) {
    case "stage": {
      const step =
        event.step !== undefined && event.step !== null && event.step.length > 0
          ? ` step=${event.step}`
          : "";
      const detail =
        event.detail !== undefined &&
        event.detail !== null &&
        event.detail.trim().length > 0
          ? ` ${event.detail.trim()}`
          : "";
      return `${base} stage=${event.stage}${issueTag(event.issue)}${epicTag(event.epic)}${step}${detail}`;
    }
    case "judge": {
      const d = event.dispositions;
      const sev = event.severity;
      const sevPart =
        sev !== undefined && sev !== null
          ? ` severity={c:${sev.critical},h:${sev.high},m:${sev.medium},l:${sev.low},cl:${sev.clarity}}`
          : "";
      const round =
        event.round !== undefined && event.round !== null
          ? ` round=${event.round}`
          : "";
      const ptr =
        event.cargoPointer !== undefined &&
        event.cargoPointer !== null &&
        event.cargoPointer.length > 0
          ? ` cargo=${event.cargoPointer}`
          : "";
      return (
        `${base} judge${issueTag(event.issue)}${epicTag(event.epic)}` +
        ` step=${event.step}${round} verdict=${event.verdict}` +
        ` dispositions={fix_now:${d.fix_now},refuted:${d.refuted},suppressed:${d.suppressed}}` +
        `${sevPart}${ptr}`
      );
    }
    case "park": {
      const step =
        event.step !== undefined && event.step !== null
          ? ` step=${event.step}`
          : "";
      const reason =
        event.reason !== undefined && event.reason !== null
          ? ` reason=${event.reason}`
          : "";
      return `${base} park${issueTag(event.issue)}${epicTag(event.epic)}${step}${reason} gate=${event.gateSummary}`;
    }
    case "merge":
      return `${base} merge${issueTag(event.issue)}${epicTag(event.epic)}`;
    case "ship": {
      const pr =
        event.pr !== undefined && event.pr !== null ? ` pr=${event.pr}` : "";
      return `${base} ship${epicTag(event.epic)}${pr}`;
    }
    case "landing": {
      const pr =
        event.pr !== undefined && event.pr !== null ? ` pr=${event.pr}` : "";
      return `${base} landing${epicTag(event.epic)}${pr}`;
    }
    case "wave_close": {
      const issues = event.issues.map((n) => `#${n}`).join(",");
      const wave =
        event.wave !== undefined && event.wave !== null
          ? ` wave=${event.wave}`
          : "";
      return `${base} wave_close${epicTag(event.epic)}${wave} issues=${issues}`;
    }
    case "terminal": {
      const reason =
        event.stopReason !== undefined && event.stopReason !== null
          ? ` stop=${event.stopReason}`
          : "";
      return `${base} terminal${issueTag(event.issue)}${epicTag(event.epic)} status=${event.status}${reason}`;
    }
    default: {
      const _exhaustive: never = event;
      void _exhaustive;
      return base;
    }
  }
}

// ─── notify hook (park / escalate / terminal only; default off) ──────────────

export type NotifySpawn = (
  command: string,
  args: readonly string[],
  opts: { readonly env: NodeJS.ProcessEnv; readonly detached: boolean; readonly stdio: "ignore" },
) => Pick<ChildProcess, "unref">;

function defaultNotifySpawn(
  command: string,
  _args: readonly string[],
  opts: { readonly env: NodeJS.ProcessEnv; readonly detached: boolean; readonly stdio: "ignore" },
): Pick<ChildProcess, "unref"> {
  // Free-form user command → /bin/sh -c (osascript, notify-send, …).
  // Routes through externalCall chokepoint (#884 S8-T).
  return spawnDetached("/bin/sh", ["-c", command], {
    stage: "progress-notify",
    env: opts.env,
    detached: opts.detached,
    stdio: opts.stdio,
  });
}

function shouldNotify(kind: ProgressEventKind): boolean {
  return kind === "park" || kind === "terminal";
}

function maybeNotify(
  event: ProgressEvent,
  notifySpawn: NotifySpawn = defaultNotifySpawn,
): void {
  if (!shouldNotify(event.kind)) return;
  const cmd = process.env[PROGRESS_NOTIFY_ENV];
  if (cmd === undefined || cmd.trim().length === 0) return;
  try {
    const child = notifySpawn(cmd.trim(), [], {
      env: {
        ...process.env,
        ORCHESTRATOR_PROGRESS_KIND: event.kind,
        ORCHESTRATOR_PROGRESS_JSON: JSON.stringify(event),
      },
      detached: true,
      stdio: "ignore",
    });
    child.unref?.();
  } catch (err) {
    console.warn(
      `[orchestrator] progress notify failed (fail-open): ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }
}

// ─── emit helpers ────────────────────────────────────────────────────────────

export interface EmitProgressOptions {
  readonly ledgerDir?: string;
  readonly log?: (line: string) => void;
  readonly notifySpawn?: NotifySpawn;
  readonly now?: () => string;
}

function resolveLedgerDir(explicit?: string): string | undefined {
  if (explicit !== undefined && explicit.length > 0) return explicit;
  return progressConfig.ledgerDir;
}

function resolveEpic(explicit?: number | null): number | null | undefined {
  if (explicit !== undefined) return explicit;
  return progressConfig.epic;
}

/**
 * Emit one progress event: append progress.jsonl (fail-open) + run.log line +
 * optional notify. Never throws into the main flow.
 */
export function emitProgressEvent(input: {
  readonly event: ProgressEvent;
  readonly ledgerDir?: string;
  readonly log?: (line: string) => void;
  readonly notifySpawn?: NotifySpawn;
  /** When false, skip ORCHESTRATOR_NOTIFY_CMD (park dual-write already notified). */
  readonly notify?: boolean;
}): void {
  try {
    const line = formatProgressLogLine(input.event);
    (input.log ?? console.log)(line);
  } catch {
    // log failure must not block
  }
  tryAppendProgressEvent(resolveLedgerDir(input.ledgerDir), input.event);
  if (input.notify === false) return;
  try {
    maybeNotify(input.event, input.notifySpawn);
  } catch {
    // already fail-open inside maybeNotify
  }
}

export function emitStageProgress(input: {
  readonly ledgerDir?: string;
  readonly stage: string;
  readonly issue?: number | null;
  readonly epic?: number | null;
  readonly step?: string | null;
  readonly detail?: string | null;
  readonly log?: (line: string) => void;
  readonly notifySpawn?: NotifySpawn;
  readonly now?: () => string;
}): void {
  const event: ProgressStageEvent = {
    v: PROGRESS_SCHEMA_VERSION,
    ts: (input.now ?? (() => new Date().toISOString()))(),
    kind: "stage",
    stage: input.stage,
    epic: resolveEpic(input.epic) ?? null,
    issue: input.issue ?? null,
    step: input.step ?? null,
    detail: input.detail ?? null,
  };
  emitProgressEvent({
    event,
    ledgerDir: input.ledgerDir,
    log: input.log,
    notifySpawn: input.notifySpawn,
  });
}

export function emitJudgeProgress(input: {
  readonly ledgerDir?: string;
  readonly issue?: number | null;
  readonly epic?: number | null;
  readonly step: string;
  readonly round?: number | null;
  readonly verdict: JudgeVerdictStatus;
  readonly findingDispositions?: ReadonlyArray<JudgeFindingDisposition>;
  readonly findings?: ReadonlyArray<Finding>;
  readonly cargoPointer?: string | null;
  readonly log?: (line: string) => void;
  readonly notifySpawn?: NotifySpawn;
  readonly now?: () => string;
}): void {
  const severity = countSeverityFromFindings(input.findings);
  const event: ProgressJudgeEvent = {
    v: PROGRESS_SCHEMA_VERSION,
    ts: (input.now ?? (() => new Date().toISOString()))(),
    kind: "judge",
    epic: resolveEpic(input.epic) ?? null,
    issue: input.issue ?? null,
    step: input.step,
    round: input.round ?? null,
    verdict: input.verdict,
    dispositions: countJudgeDispositions(input.findingDispositions),
    severity,
    cargoPointer: input.cargoPointer ?? null,
  };
  emitProgressEvent({
    event,
    ledgerDir: input.ledgerDir,
    log: input.log,
    notifySpawn: input.notifySpawn,
  });
  // Judge escalate is a decision-gate path — also surface as park-class notify
  // via a follow-up park event when the runner parks; do not double-notify here.
}

export function emitParkProgress(input: {
  readonly ledgerDir?: string;
  readonly issue?: number | null;
  readonly epic?: number | null;
  readonly step?: string | null;
  readonly gateSummary: string;
  readonly reason?: string | null;
  readonly log?: (line: string) => void;
  readonly notifySpawn?: NotifySpawn;
  readonly now?: () => string;
}): void {
  const event: ProgressParkEvent = {
    v: PROGRESS_SCHEMA_VERSION,
    ts: (input.now ?? (() => new Date().toISOString()))(),
    kind: "park",
    epic: resolveEpic(input.epic) ?? null,
    issue: input.issue ?? null,
    step: input.step ?? null,
    gateSummary: input.gateSummary,
    reason: input.reason ?? null,
  };
  emitProgressEvent({
    event,
    ledgerDir: input.ledgerDir,
    log: input.log,
    notifySpawn: input.notifySpawn,
  });
}

export function emitMergeProgress(input: {
  readonly ledgerDir?: string;
  readonly issue: number;
  readonly epic?: number | null;
  readonly childHead?: string | null;
  readonly log?: (line: string) => void;
  readonly now?: () => string;
}): void {
  const event: ProgressMergeEvent = {
    v: PROGRESS_SCHEMA_VERSION,
    ts: (input.now ?? (() => new Date().toISOString()))(),
    kind: "merge",
    epic: resolveEpic(input.epic) ?? null,
    issue: input.issue,
    childHead: input.childHead ?? null,
  };
  emitProgressEvent({ event, ledgerDir: input.ledgerDir, log: input.log });
}

export function emitShipProgress(input: {
  readonly ledgerDir?: string;
  readonly epic?: number | null;
  readonly pr?: string | null;
  readonly familyHead?: string | null;
  readonly log?: (line: string) => void;
  readonly now?: () => string;
}): void {
  const event: ProgressShipEvent = {
    v: PROGRESS_SCHEMA_VERSION,
    ts: (input.now ?? (() => new Date().toISOString()))(),
    kind: "ship",
    epic: resolveEpic(input.epic) ?? null,
    pr: input.pr ?? null,
    familyHead: input.familyHead ?? null,
  };
  emitProgressEvent({ event, ledgerDir: input.ledgerDir, log: input.log });
}

export function emitLandingProgress(input: {
  readonly ledgerDir?: string;
  readonly epic?: number | null;
  readonly pr?: string | null;
  readonly log?: (line: string) => void;
  readonly now?: () => string;
}): void {
  const event: ProgressLandingEvent = {
    v: PROGRESS_SCHEMA_VERSION,
    ts: (input.now ?? (() => new Date().toISOString()))(),
    kind: "landing",
    epic: resolveEpic(input.epic) ?? null,
    pr: input.pr ?? null,
  };
  emitProgressEvent({ event, ledgerDir: input.ledgerDir, log: input.log });
}

export function emitWaveCloseProgress(input: {
  readonly ledgerDir?: string;
  readonly epic?: number | null;
  readonly issues: readonly number[];
  readonly wave?: number | null;
  readonly log?: (line: string) => void;
  readonly now?: () => string;
}): void {
  const event: ProgressWaveCloseEvent = {
    v: PROGRESS_SCHEMA_VERSION,
    ts: (input.now ?? (() => new Date().toISOString()))(),
    kind: "wave_close",
    epic: resolveEpic(input.epic) ?? null,
    issues: [...input.issues],
    wave: input.wave ?? null,
  };
  emitProgressEvent({ event, ledgerDir: input.ledgerDir, log: input.log });
}

export function emitTerminalProgress(input: {
  readonly ledgerDir?: string;
  readonly epic?: number | null;
  readonly issue?: number | null;
  readonly status: "completed" | "parked" | "failed";
  readonly stopReason?: string | null;
  readonly log?: (line: string) => void;
  readonly notifySpawn?: NotifySpawn;
  /** When false, write feed/log only (park dual-write already notified). Default true. */
  readonly notify?: boolean;
  readonly now?: () => string;
}): void {
  const event: ProgressTerminalEvent = {
    v: PROGRESS_SCHEMA_VERSION,
    ts: (input.now ?? (() => new Date().toISOString()))(),
    kind: "terminal",
    epic: resolveEpic(input.epic) ?? null,
    issue: input.issue ?? null,
    status: input.status,
    stopReason: input.stopReason ?? null,
  };
  emitProgressEvent({
    event,
    ledgerDir: input.ledgerDir,
    log: input.log,
    notifySpawn: input.notifySpawn,
    notify: input.notify,
  });
}

/**
 * #1007 — park/terminal dual-write for any public exit.
 *
 * Parked → park + terminal (park carries notify; terminal half skips notify);
 * completed/failed → terminal (notify). Fail-open; call from shared exit helpers
 * so call sites cannot forget.
 */
export function emitExitProgress(input: {
  readonly ledgerDir?: string;
  readonly epic?: number | null;
  readonly issue?: number | null;
  readonly step?: string | null;
  readonly status: "completed" | "parked" | "failed";
  readonly stopReason?: string | null;
  readonly gateSummary?: string | null;
  readonly log?: (line: string) => void;
  readonly notifySpawn?: NotifySpawn;
  readonly now?: () => string;
}): void {
  if (input.status === "parked") {
    const gate =
      typeof input.gateSummary === "string" && input.gateSummary.trim().length > 0
        ? input.gateSummary.trim()
        : typeof input.stopReason === "string" && input.stopReason.trim().length > 0
          ? input.stopReason.trim()
          : "parked";
    emitParkProgress({
      ledgerDir: input.ledgerDir,
      epic: input.epic,
      issue: input.issue ?? null,
      step: input.step ?? null,
      gateSummary: gate,
      reason: input.stopReason ?? null,
      log: input.log,
      notifySpawn: input.notifySpawn,
      now: input.now,
    });
    // Terminal feed row only — park already carried the single notify spawn.
    emitTerminalProgress({
      ledgerDir: input.ledgerDir,
      epic: input.epic,
      issue: input.issue ?? null,
      status: "parked",
      stopReason: input.stopReason ?? null,
      log: input.log,
      notify: false,
      now: input.now,
    });
    return;
  }
  emitTerminalProgress({
    ledgerDir: input.ledgerDir,
    epic: input.epic,
    issue: input.issue ?? null,
    status: input.status,
    stopReason: input.stopReason ?? null,
    log: input.log,
    notifySpawn: input.notifySpawn,
    now: input.now,
  });
}

// ─── status renderer ─────────────────────────────────────────────────────────

export interface IssueProgressSnapshot {
  readonly issue: number;
  readonly latestStep: string | null;
  readonly latestStage: string | null;
  readonly latestVerdict: JudgeVerdictStatus | null;
  readonly judgeRounds: number;
  readonly dispositions: ProgressDispositionCounts | null;
  readonly severity: ProgressSeverityCounts | null;
  readonly parked: boolean;
  readonly parkSummary: string | null;
  readonly merged: boolean;
  readonly cargoPointer: string | null;
}

export interface FamilyStatusSnapshot {
  readonly issues: readonly IssueProgressSnapshot[];
  readonly waves: readonly { readonly wave: number | null; readonly issues: readonly number[] }[];
  readonly ships: readonly { readonly pr: string | null; readonly familyHead: string | null }[];
  readonly landings: readonly { readonly pr: string | null }[];
  readonly terminals: readonly {
    readonly status: "completed" | "parked" | "failed";
    readonly stopReason: string | null;
    readonly issue: number | null;
  }[];
}

function readMergedIssuesFromFamilyLedger(
  familyLedgerPath: string | undefined,
): Set<number> {
  const merged = new Set<number>();
  if (familyLedgerPath === undefined || !existsSync(familyLedgerPath)) {
    return merged;
  }
  try {
    const raw = readFileSync(familyLedgerPath, "utf8");
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (trimmed.length === 0) continue;
      try {
        const row = JSON.parse(trimmed) as {
          status?: string;
          childIssue?: number;
        };
        if (
          row.status === "merged" &&
          typeof row.childIssue === "number" &&
          Number.isInteger(row.childIssue)
        ) {
          merged.add(row.childIssue);
        }
      } catch {
        // skip
      }
    }
  } catch {
    // fail-open empty
  }
  return merged;
}

export function renderFamilyStatus(input: {
  readonly events: readonly ProgressEvent[];
  readonly familyLedgerPath?: string;
}): FamilyStatusSnapshot {
  const byIssue = new Map<
    number,
    {
      latestStep: string | null;
      latestStage: string | null;
      latestVerdict: JudgeVerdictStatus | null;
      judgeRounds: number;
      dispositions: ProgressDispositionCounts | null;
      severity: ProgressSeverityCounts | null;
      parked: boolean;
      parkSummary: string | null;
      cargoPointer: string | null;
    }
  >();

  const ensure = (issue: number) => {
    let row = byIssue.get(issue);
    if (row === undefined) {
      row = {
        latestStep: null,
        latestStage: null,
        latestVerdict: null,
        judgeRounds: 0,
        dispositions: null,
        severity: null,
        parked: false,
        parkSummary: null,
        cargoPointer: null,
      };
      byIssue.set(issue, row);
    }
    return row;
  };

  const waves: Array<{
    wave: number | null;
    issues: readonly number[];
  }> = [];
  const ships: Array<{ pr: string | null; familyHead: string | null }> = [];
  const landings: Array<{ pr: string | null }> = [];
  const terminals: Array<{
    status: "completed" | "parked" | "failed";
    stopReason: string | null;
    issue: number | null;
  }> = [];

  for (const event of input.events) {
    switch (event.kind) {
      case "stage": {
        if (event.issue !== undefined && event.issue !== null) {
          const row = ensure(event.issue);
          row.latestStage = event.stage;
          if (event.step !== undefined && event.step !== null) {
            row.latestStep = event.step;
          }
        }
        break;
      }
      case "judge": {
        if (event.issue !== undefined && event.issue !== null) {
          const row = ensure(event.issue);
          row.latestStep = event.step;
          row.latestVerdict = event.verdict;
          row.judgeRounds += 1;
          row.dispositions = event.dispositions;
          row.severity = event.severity ?? null;
          row.cargoPointer = event.cargoPointer ?? null;
          if (event.verdict === "escalate") {
            row.parked = true;
            row.parkSummary = row.parkSummary ?? "judge escalate";
          }
        }
        break;
      }
      case "park": {
        if (event.issue !== undefined && event.issue !== null) {
          const row = ensure(event.issue);
          row.parked = true;
          row.parkSummary = event.gateSummary;
          if (event.step !== undefined && event.step !== null) {
            row.latestStep = event.step;
          }
        }
        break;
      }
      case "merge": {
        ensure(event.issue);
        break;
      }
      case "wave_close":
        waves.push({ wave: event.wave ?? null, issues: event.issues });
        for (const issue of event.issues) ensure(issue);
        break;
      case "ship":
        ships.push({
          pr: event.pr ?? null,
          familyHead: event.familyHead ?? null,
        });
        break;
      case "landing":
        landings.push({ pr: event.pr ?? null });
        break;
      case "terminal":
        terminals.push({
          status: event.status,
          stopReason: event.stopReason ?? null,
          issue: event.issue ?? null,
        });
        if (event.issue !== undefined && event.issue !== null) {
          const row = ensure(event.issue);
          if (event.status === "parked") {
            row.parked = true;
            row.parkSummary =
              row.parkSummary ?? event.stopReason ?? "parked";
          }
        }
        break;
      default:
        break;
    }
  }

  const mergedFromLedger = readMergedIssuesFromFamilyLedger(
    input.familyLedgerPath,
  );
  // progress merge events also mark merged
  for (const event of input.events) {
    if (event.kind === "merge") mergedFromLedger.add(event.issue);
  }

  const issues: IssueProgressSnapshot[] = [...byIssue.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([issue, row]) => ({
      issue,
      latestStep: row.latestStep,
      latestStage: row.latestStage,
      latestVerdict: row.latestVerdict,
      judgeRounds: row.judgeRounds,
      dispositions: row.dispositions,
      severity: row.severity,
      parked: row.parked,
      parkSummary: row.parkSummary,
      merged: mergedFromLedger.has(issue),
      cargoPointer: row.cargoPointer,
    }));

  return { issues, waves, ships, landings, terminals };
}

/** Human-readable family status from a durable ledger directory. */
export function renderFamilyStatusFromDir(ledgerDir: string): string {
  const events = readProgressEvents(ledgerDir);
  const familyLedgerPath = join(ledgerDir, "family-ledger.jsonl");
  const snap = renderFamilyStatus({
    events,
    familyLedgerPath: existsSync(familyLedgerPath)
      ? familyLedgerPath
      : undefined,
  });
  if (snap.issues.length === 0 && snap.terminals.length === 0) {
    return `family status @ ${ledgerDir}\n(no progress events yet)\n`;
  }
  const lines: string[] = [`family status @ ${ledgerDir}`];
  for (const issue of snap.issues) {
    const parts = [
      `#${issue.issue}`,
      `step=${issue.latestStep ?? "?"}`,
      `rounds=${issue.judgeRounds}`,
      `verdict=${issue.latestVerdict ?? "—"}`,
    ];
    // AC 站位: surface latest stage token when the feed has one.
    if (issue.latestStage !== null && issue.latestStage.length > 0) {
      parts.push(`stage=${issue.latestStage}`);
    }
    if (issue.dispositions !== null) {
      const d = issue.dispositions;
      parts.push(
        `dispositions={fix_now:${d.fix_now},refuted:${d.refuted},suppressed:${d.suppressed}}`,
      );
    }
    if (issue.merged) parts.push("merged");
    if (issue.parked) {
      parts.push(`parked:${issue.parkSummary ?? "yes"}`);
    }
    if (issue.cargoPointer) parts.push(`cargo=${issue.cargoPointer}`);
    lines.push(`  ${parts.join(" ")}`);
  }
  for (const w of snap.waves) {
    lines.push(
      `  wave_close${w.wave !== null ? ` #${w.wave}` : ""} issues=${w.issues.map((n) => `#${n}`).join(",")}`,
    );
  }
  for (const s of snap.ships) {
    lines.push(`  ship${s.pr !== null ? ` ${s.pr}` : ""}`);
  }
  for (const l of snap.landings) {
    lines.push(`  landing${l.pr !== null ? ` ${l.pr}` : ""}`);
  }
  for (const t of snap.terminals) {
    lines.push(
      `  terminal status=${t.status}` +
        (t.issue !== null ? ` issue=#${t.issue}` : "") +
        (t.stopReason !== null ? ` stop=${t.stopReason}` : ""),
    );
  }
  return `${lines.join("\n")}\n`;
}

// ─── stageLog bridge helpers ─────────────────────────────────────────────────

/**
 * Format the classic `[orchestrator:stage]` line with optional issue number
 * (#975 debt ④ / #1007).
 */
export function formatDriverStageLine(
  stage: string,
  detail?: string,
  opts?: { readonly issue?: number; readonly issues?: readonly number[] },
): string {
  const issuePart =
    opts?.issue !== undefined
      ? ` issue #${opts.issue}`
      : opts?.issues !== undefined && opts.issues.length > 0
        ? ` issues=${opts.issues.map((n) => `#${n}`).join(",")}`
        : "";
  const suffix =
    detail !== undefined && detail.trim().length > 0
      ? ` ${detail.trim()}`
      : "";
  return `[orchestrator:stage] ${stage}${issuePart}${suffix}`;
}

