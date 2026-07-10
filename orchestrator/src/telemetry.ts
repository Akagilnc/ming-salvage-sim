/**
 * #786 — orchestrator telemetry sidecar (append-only JSONL).
 *
 * Parallel to the step ledger (`steps.jsonl`): raw per-leg stamps only.
 * Aggregation / stats are out of scope for this ticket.
 *
 * Layout: `<ledgerDir>/telemetry.jsonl` — one JSON object per line.
 * Phases:
 *   - `environment` — once per run (image / route lineup / CLI versions)
 *   - `dispatch`    — half-row at spawn (identity / model / pool / time)
 *   - `collect`     — half-row at finish (terminal / tokens / session / log)
 *
 * Join key: `legId` shared by a dispatch+collect pair.
 * Unobtainable fields are `null` — never block the worker path.
 * Telemetry I/O is best-effort: callers must not let throws escape into
 * dispatch control flow.
 *
 * Time axes on a collect row (`dispatched_at` lives on the paired dispatch
 * row): `first_output_at` is **first observed log growth at poll
 * granularity**, not true first-byte / TTFB. See field JSDoc and
 * `orchestrator/README.md` § first_output_at.
 */

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
} from "node:fs";
import { dirname, join } from "node:path";

import {
  resolveCoderRecOrder,
} from "./coderRoster.js";
import {
  effortForLiveOfficer,
  modelFamilyForSlug,
  resolveModelSlug,
} from "./modelRegistry.js";
import type { ResolvedModelRoute } from "./modelRoutes.js";
import {
  isAgentIdleTimeoutError,
  isQuotaWaitForResetError,
} from "./quotaProbe.js";
import {
  isHangWithLivePoolError,
  isSelfReportedRelayError,
} from "./relayDispatch.js";
import type {
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "./types.js";
import { poolIdForWorker } from "./workerMonitor.js";

/**
 * Same default as {@link DEFAULT_IMAGE_TAG} in familyDriver — kept local so
 * telemetry stays free of the heavy driver/backend import graph.
 */
const TELEMETRY_DEFAULT_IMAGE_TAG = "ming-orchestrator-coder:latest";

/**
 * Once-per-process run environment for telemetry (image / fast / content hashes).
 * Set lazily by RealBackend / RealFamilyBackend immediately before an absent
 * environment stamp, so stamps read the real imageName + codexFast without
 * making backend construction block on fingerprint collection.
 */
export interface TelemetryRunEnvironment {
  readonly imageTag?: string | null;
  readonly imageDigest?: string | null;
  readonly sandboxFingerprint?: string | null;
  readonly soulsHash?: string | null;
  readonly promptHash?: string | null;
  /** Effective Codex fast switch for this run (explicit option or resolved env). */
  readonly codexFast?: boolean | null;
}

let telemetryRunEnvironment: TelemetryRunEnvironment = {};

/** Install / merge the process-level run environment used by stamp builders. */
export function configureTelemetryRunEnvironment(
  env: TelemetryRunEnvironment,
): void {
  telemetryRunEnvironment = { ...telemetryRunEnvironment, ...env };
}

/** Clear process-level run environment (tests). */
export function clearTelemetryRunEnvironment(): void {
  telemetryRunEnvironment = {};
}

/** Read the current process-level run environment (tests / diagnostics). */
export function getTelemetryRunEnvironment(): TelemetryRunEnvironment {
  return telemetryRunEnvironment;
}

/**
 * Wire worker-image config into telemetry (called by RealBackend /
 * RealFamilyBackend immediately before an absent environment stamp). Best-effort:
 * missing docker / dirs → null fields.
 */
export function configureTelemetryFromWorkerImage(opts: {
  readonly imageName: string;
  readonly codexFast?: boolean;
  readonly soulsDir?: string;
  readonly promptsDir?: string;
}): void {
  const imageTag =
    opts.imageName.trim().length > 0 ? opts.imageName.trim() : null;
  const imageDigest =
    imageTag !== null ? resolveDockerImageDigest(imageTag) : null;
  const soulsHash =
    opts.soulsDir !== undefined ? hashDirectoryContents(opts.soulsDir) : null;
  const promptHash =
    opts.promptsDir !== undefined
      ? hashDirectoryContents(opts.promptsDir)
      : null;
  const sandboxFingerprint =
    imageTag !== null
      ? computeSandboxFingerprint({
          imageTag,
          imageDigest,
          soulsDir: opts.soulsDir,
          promptsDir: opts.promptsDir,
        })
      : null;
  const codexFast =
    opts.codexFast !== undefined
      ? opts.codexFast
      : process.env.ORCHESTRATOR_CODEX_FAST === "1";
  configureTelemetryRunEnvironment({
    imageTag,
    imageDigest,
    sandboxFingerprint,
    soulsHash,
    promptHash,
    codexFast,
  });
}

/** Best-effort docker image Id for an image tag; null when docker/image absent. */
export function resolveDockerImageDigest(imageTag: string): string | null {
  if (imageTag.trim().length === 0) return null;
  try {
    const out = execFileSync(
      "docker",
      ["image", "inspect", "--format", "{{.Id}}", imageTag],
      { encoding: "utf8", timeout: 5_000, stdio: ["ignore", "pipe", "ignore"] },
    ).trim();
    return out.length > 0 ? out : null;
  } catch {
    return null;
  }
}

/**
 * Stable SHA-256 over files under `dir` (sorted relative paths).
 * Returns null when dir is missing or unreadable.
 */
export function hashDirectoryContents(dir: string): string | null {
  if (dir.trim().length === 0 || !existsSync(dir)) return null;
  try {
    if (!statSync(dir).isDirectory()) return null;
    const hash = createHash("sha256");
    const files = listFilesRecursive(dir).sort();
    if (files.length === 0) {
      hash.update("empty-dir\n");
    }
    for (const rel of files) {
      hash.update(`file:${rel}\0`);
      try {
        hash.update(readFileSync(join(dir, rel)));
      } catch {
        hash.update("unreadable");
      }
      hash.update("\n");
    }
    return hash.digest("hex");
  } catch {
    return null;
  }
}

/** Lightweight sandbox fingerprint: image + souls + prompts content (no auth). */
export function computeSandboxFingerprint(input: {
  readonly imageTag: string;
  readonly imageDigest?: string | null;
  readonly soulsDir?: string;
  readonly promptsDir?: string;
}): string {
  const hash = createHash("sha256");
  hash.update(`image:${input.imageTag}\n`);
  hash.update(`image-id:${input.imageDigest ?? "unknown"}\n`);
  if (input.soulsDir !== undefined) {
    hash.update(`souls:${hashDirectoryContents(input.soulsDir) ?? "missing"}\n`);
  } else {
    hash.update("souls:unset\n");
  }
  if (input.promptsDir !== undefined) {
    hash.update(
      `prompts:${hashDirectoryContents(input.promptsDir) ?? "missing"}\n`,
    );
  } else {
    hash.update("prompts:unset\n");
  }
  return hash.digest("hex");
}

function listFilesRecursive(root: string, base = ""): string[] {
  const out: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(join(root, base));
  } catch {
    return out;
  }
  for (const name of entries) {
    const rel = base.length > 0 ? `${base}/${name}` : name;
    const abs = join(root, rel);
    try {
      const st = statSync(abs);
      if (st.isDirectory()) {
        out.push(...listFilesRecursive(root, rel));
      } else if (st.isFile()) {
        out.push(rel);
      }
    } catch {
      // skip unreadable entries
    }
  }
  return out;
}

/** Sidecar filename under the ledger/state directory. */
export const TELEMETRY_FILENAME = "telemetry.jsonl";

/** Schema version for forward-compatible consumers. */
export const TELEMETRY_SCHEMA_VERSION = 1 as const;

/**
 * Error categories for failed/aborted legs (issue #786).
 * Distinct: at-capacity ≠ 429-quota ≠ hang-idle ≠ stream-disconnect.
 * Unknown failures map to `unclassified` (never silent null) so raw
 * `errorMessage` stays available for post-hoc taxonomy expansion.
 */
export type TelemetryErrorCategory =
  | "at-capacity"
  | "429-quota"
  | "hang-idle"
  | "stream-disconnect"
  | "honest-incomplete"
  | "relay-out"
  | "killed"
  | "unclassified";

/** Terminal discriminant recorded on the collect half-row. */
export type TelemetryTerminal =
  | "completed"
  | "failed"
  | "malformed"
  | "outcome_protocol_failure"
  | "escalated"
  | "thrown";

/** Token triple (+ optional total when only a single count is available). */
export interface TelemetryTokenUsage {
  readonly input: number | null;
  readonly output: number | null;
  readonly cached: number | null;
  /** Codex often prints only a total; keep it when the split is unavailable. */
  readonly total: number | null;
}

export interface TelemetryCoderRecProvenance {
  /** Designer Coder-Rec order (roster ids), when parseable from the issue body. */
  readonly order: readonly string[] | null;
  /** Model slug actually dispatched. */
  readonly selected: string | null;
  /** True when selected is not the head of the order. */
  readonly wasFallback: boolean | null;
  /** True when ORCHESTRATOR_CODER_MODEL env forced the coder. */
  readonly envOverride: boolean | null;
}

export interface TelemetryModelStamp {
  readonly slug: string | null;
  readonly family: string | null;
  readonly effort: string | null;
  /** ORCHESTRATOR_CODEX_FAST / service_tier=fast when known. */
  readonly fast: boolean | null;
}

interface TelemetryRecordBase {
  readonly v: typeof TELEMETRY_SCHEMA_VERSION;
  /** Wall-clock when this JSONL line was written. */
  readonly stamped_at: string;
}

/** Once-per-run environment stamp. */
export interface TelemetryEnvironmentRecord extends TelemetryRecordBase {
  readonly phase: "environment";
  readonly runId: string | null;
  /**
   * Worker image tag (imageName / IMAGE_TAG / default). Null only when no
   * configured image and no default path applies.
   */
  readonly imageTag: string | null;
  /** Docker image Id/digest when inspect succeeds; else null. */
  readonly imageDigest: string | null;
  /**
   * Lightweight sandbox fingerprint (image + souls + prompts content).
   * Null when not computable from available config.
   */
  readonly sandboxFingerprint: string | null;
  /** Content hash of live-mounted souls dir; null when dir unknown/missing. */
  readonly soulsHash: string | null;
  /** Content hash of versioned prompt files dir; null when dir unknown/missing. */
  readonly promptHash: string | null;
  readonly routeName: string | null;
  /** Slot → model slug lineup from the resolved route. */
  readonly routeSlots: Readonly<Record<string, string>> | null;
  /** CMR review leg slugs, when present. */
  readonly routeCmrReviewLegs: readonly string[] | null;
  /** slug → cliVersion from route-smoke passed records. */
  readonly cliVersions: Readonly<Record<string, string>> | null;
}

/** Dispatch half-row (identity / model / pool / time). */
export interface TelemetryDispatchRecord extends TelemetryRecordBase {
  readonly phase: "dispatch";
  readonly legId: string;
  readonly runId: string | null;
  readonly issue: number | null;
  readonly stepId: string | null;
  readonly role: string | null;
  readonly kind: string | null;
  /** Online-review round or null when not applicable / unknown. */
  readonly round: number | null;
  /** Mechanical-retry attempt ordinal; null when the seam does not know. */
  readonly attempt: number | null;
  readonly model: TelemetryModelStamp;
  readonly poolId: string | null;
  readonly coderRec: TelemetryCoderRecProvenance | null;
  readonly cliVersion: string | null;
  readonly dispatched_at: string;
}

/** Collect half-row (terminal / tokens / session / log). */
export interface TelemetryCollectRecord extends TelemetryRecordBase {
  readonly phase: "collect";
  readonly legId: string;
  /**
   * ISO wall-clock when the orchestrator first **observed** worker log growth
   * past the post-spawn marker. **Not** true first-byte / TTFB.
   *
   * Precision boundary (poll granularity):
   * - Under a long-running worker the idle monitor polls the log; the stamp is
   *   the wall-clock of the poll that first sees size growth past baseline.
   *   Error upper bound ≈ `pollIntervalMs` (default 250ms in `dispatchWorker`).
   * - Quick-exit: if the child exits before any poll observes growth, a
   *   one-shot post-exit reconcile re-read stamps this at that moment
   *   (≈ process exit time) so the field is not left null when bytes exist.
   * - `null` only when no post-marker growth was observed by collect time.
   *
   * Monotonic with the paired dispatch row (when non-null):
   * `dispatched_at ≤ first_output_at ≤ completed_at`.
   */
  readonly first_output_at: string | null;
  readonly completed_at: string;
  readonly terminal: TelemetryTerminal;
  /**
   * Category for non-success terminals. `null` on completed, and on escalated
   * when the reason is a pure decision (no known failure signature). Escalated
   * legs that match a known pattern (e.g. missing completion signal →
   * `honest-incomplete`) keep that category so post-hoc clustering works.
   * Failures that do not match a known pattern are `"unclassified"` (not null).
   */
  readonly errorCategory: TelemetryErrorCategory | null;
  /**
   * Raw failure/throw message for post-hoc reclassification. `null` when the
   * terminal has no message (completed / escalated without reason).
   */
  readonly errorMessage: string | null;
  readonly tokens: TelemetryTokenUsage | null;
  readonly sessionId: string | null;
  readonly logPath: string | null;
}

export type TelemetryRecord =
  | TelemetryEnvironmentRecord
  | TelemetryDispatchRecord
  | TelemetryCollectRecord;

// ───────────────────────── pure helpers ─────────────────────────

/** Fresh join key for a dispatch↔collect pair. */
export function newLegId(): string {
  return globalThis.crypto.randomUUID();
}

/**
 * Codex CLI prints a total on stderr/stdout:
 *   `tokens used\n27,290`  or  `tokens used: 12345`
 * Returns null when no match.
 */
export function extractCodexTokens(logText: string): TelemetryTokenUsage | null {
  if (logText.length === 0) return null;
  // Prefer the last occurrence (final summary after the run).
  const block = /tokens used\s*[:：]?\s*(?:\r?\n\s*)?([\d,]+)/gi;
  let last: string | undefined;
  for (const m of logText.matchAll(block)) {
    if (m[1] !== undefined) last = m[1];
  }
  if (last === undefined) return null;
  const total = parseTokenInt(last);
  if (total === null) return null;
  return { input: null, output: null, cached: null, total };
}

/**
 * Claude Code / Anthropic-style usage lines. Accepts JSON-ish fields and a few
 * human-readable forms. Unmatched → null.
 */
export function extractClaudeTokens(logText: string): TelemetryTokenUsage | null {
  if (logText.length === 0) return null;

  // JSON-ish: "input_tokens":123 / input_tokens: 123 (optional quotes around key).
  // Negative lookbehind avoids matching the tail of cache_read_input_tokens.
  const input = matchLastInt(
    logText,
    /(?<![A-Za-z_])(?:input_tokens|prompt_tokens)"?\s*[=:]\s*(\d+)/gi,
  );
  const output = matchLastInt(
    logText,
    /(?<![A-Za-z_])(?:output_tokens|completion_tokens)"?\s*[=:]\s*(\d+)/gi,
  );
  const cached = matchLastInt(
    logText,
    /(?<![A-Za-z_])(?:cache_read_input_tokens|cache_read_tokens|cached_tokens)"?\s*[=:]\s*(\d+)/gi,
  );

  // Human forms: "Usage: input=123 output=45 cache=10" / "Input: 123 tokens"
  const humanInput =
    input ??
    matchLastInt(logText, /(?:^|\s)(?:input|prompt)\s*[:=]\s*([\d,]+)\s*tokens?/gi);
  const humanOutput =
    output ??
    matchLastInt(
      logText,
      /(?:^|\s)(?:output|completion)\s*[:=]\s*([\d,]+)\s*tokens?/gi,
    );
  const humanCached =
    cached ??
    matchLastInt(logText, /(?:^|\s)(?:cache(?:d)?|cache_read)\s*[:=]\s*([\d,]+)/gi);

  if (humanInput === null && humanOutput === null && humanCached === null) {
    return null;
  }
  const total =
    humanInput !== null || humanOutput !== null
      ? (humanInput ?? 0) + (humanOutput ?? 0)
      : null;
  return {
    input: humanInput,
    output: humanOutput,
    cached: humanCached,
    total,
  };
}

/**
 * Pick an extractor by model family, falling back across both formats.
 */
export function extractTokensFromLog(
  logText: string,
  family: string | null | undefined,
): TelemetryTokenUsage | null {
  if (family === "codex") {
    return extractCodexTokens(logText) ?? extractClaudeTokens(logText);
  }
  if (family === "claude") {
    return extractClaudeTokens(logText) ?? extractCodexTokens(logText);
  }
  // Unknown family: try both, prefer a non-null result with any filled field.
  return extractCodexTokens(logText) ?? extractClaudeTokens(logText);
}

/**
 * Classify a finished worker result or a thrown error into terminal + category.
 * Pure: no I/O.
 *
 * Failure categories are aligned to the real throw/return strings produced by
 * realBackend / realFamilyBackend / shipOutcome / dispatch monitor — not to
 * invented telemetry-only phrases. Unmatched failures are `"unclassified"`
 * (never silent `null`) and the raw message is always preserved.
 */
export function classifyWorkerTerminal(
  outcome:
    | { readonly kind: "result"; readonly result: WorkerResult }
    | { readonly kind: "thrown"; readonly error: unknown },
): {
  readonly terminal: TelemetryTerminal;
  readonly errorCategory: TelemetryErrorCategory | null;
  readonly errorMessage: string | null;
  readonly sessionId: string | null;
} {
  if (outcome.kind === "result") {
    const r = outcome.result;
    const sessionId =
      "sessionId" in r && typeof r.sessionId === "string" ? r.sessionId : null;
    if (r.kind === "completed") {
      return {
        terminal: "completed",
        errorCategory: null,
        errorMessage: null,
        sessionId,
      };
    }
    if (r.kind === "escalated") {
      // Keep the raw reason for post-hoc stats. Pure decision escalates stay
      // category-null; known failure signatures (ship/cmr missing completion
      // signal → honest-incomplete, etc.) stay clusterable — never force null.
      const reason = r.escalation.reason;
      const categorized =
        reason.length > 0 ? categoryFromReason(reason) : null;
      return {
        terminal: "escalated",
        errorCategory:
          categorized === null || categorized === "unclassified"
            ? null
            : categorized,
        errorMessage: reason.length > 0 ? reason : null,
        sessionId,
      };
    }
    if (r.kind === "malformed") {
      return {
        terminal: "malformed",
        errorCategory: categoryFromReason(r.reason),
        errorMessage: r.reason,
        sessionId,
      };
    }
    if (r.kind === "outcome_protocol_failure") {
      return {
        terminal: "outcome_protocol_failure",
        errorCategory: categoryFromReason(r.reason),
        errorMessage: r.reason,
        sessionId,
      };
    }
    // failed
    return {
      terminal: "failed",
      errorCategory: categoryFromReason(r.reason),
      errorMessage: r.reason,
      sessionId,
    };
  }

  const err = outcome.error;
  const msg = err instanceof Error ? err.message : String(err);
  if (isQuotaWaitForResetError(err)) {
    return {
      terminal: "thrown",
      errorCategory: "429-quota",
      errorMessage: msg,
      sessionId: null,
    };
  }
  if (isSelfReportedRelayError(err)) {
    return {
      terminal: "thrown",
      errorCategory: "relay-out",
      errorMessage: msg,
      sessionId: null,
    };
  }
  if (isHangWithLivePoolError(err)) {
    return {
      terminal: "thrown",
      errorCategory: "hang-idle",
      errorMessage: msg,
      sessionId: null,
    };
  }
  // Sandcastle AgentIdleTimeoutError — rethrown by realBackend.runAgentSandbox
  // with the fixed text "Agent idle for N seconds…". Match by tag/name/message
  // (same detector as #683) so real idle does not fall through to unclassified.
  if (isAgentIdleTimeoutError(err)) {
    return {
      terminal: "thrown",
      errorCategory: "hang-idle",
      errorMessage: msg,
      sessionId: null,
    };
  }
  return {
    terminal: "thrown",
    errorCategory: categoryFromReason(msg),
    errorMessage: msg,
    sessionId: null,
  };
}

/**
 * True when free text names 429 in an HTTP-status context, not merely as an
 * unrelated number such as a GitHub issue, path segment, or item identifier.
 */
export function mentionsHttp429(reasonLower: string): boolean {
  return /\b(?:http(?:\/\d+(?:\.\d+)?)?(?:\s+(?:code|error|response\s+code|status(?:\s+code)?))?|status(?:\s+code)?|response\s+(?:status(?:\s+code)?|code))\s*(?:is|was)?\s*(?:=|:)?\s*429\b(?!\.\d)/.test(
    reasonLower,
  );
}

/**
 * Map a free-text failure reason onto a telemetry category.
 *
 * Patterns below are taken from the actual throw/return sites (not invented):
 * - realBackend.assertCompletionSignal — "did not fire its required completion
 *   signal" / "no signal fired before the iteration limit"
 * - shipOutcome / realFamilyBackend cmr+merger — "… did not fire its completion signal"
 * - HangWithLivePoolError — "hang with live pool"
 * - dispatchWorker idle monitor — "monitored worker idle hang"
 * - QuotaWaitForResetError — "quota wait for reset"
 * - SelfReportedRelayError — "self-reported blocked" / "phase_complete:"
 * - signal-kill stamp — "killed by signal" / SIGTERM / SIGKILL
 *
 * Anything unmatched → `"unclassified"` (raw message kept on the collect row).
 */
export function categoryFromReason(reason: string): TelemetryErrorCategory {
  const lower = reason.toLowerCase();

  // ── at-capacity ──────────────────────────────────────────────────────────
  if (
    lower.includes("at-capacity") ||
    lower.includes("at capacity") ||
    lower.includes("capacity exceeded")
  ) {
    return "at-capacity";
  }

  // ── 429 / quota (QuotaWaitForResetError message: "quota wait for reset…") ─
  // Prefer explicit quota phrases; bare "limit" is too broad (iteration limit).
  // A numeric 429 counts only when it is explicitly an HTTP-status token.
  if (
    mentionsHttp429(lower) ||
    lower.includes("quota wait for reset") ||
    lower.includes("rate limit") ||
    lower.includes("rate_limit") ||
    lower.includes("too many requests") ||
    // Standalone "quota" but not "iteration" context handled below first.
    (lower.includes("quota") && !lower.includes("iteration limit"))
  ) {
    return "429-quota";
  }

  // ── hang-idle (HangWithLivePoolError + monitored idle hang + Sandcastle idle) ─
  // realBackend rethrows AgentIdleTimeoutError as:
  //   "Agent idle for 600 seconds — no output received. …"
  // (#683 / quotaProbe isAgentIdleTimeoutError message shape).
  if (
    lower.includes("idle hang") ||
    lower.includes("hang-idle") ||
    lower.includes("worker idle") ||
    lower.includes("monitored worker idle hang") ||
    lower.includes("hang with live pool") ||
    /agent idle for \d+/.test(lower)
  ) {
    return "hang-idle";
  }

  // ── stream-disconnect ────────────────────────────────────────────────────
  if (
    lower.includes("stream disconnect") ||
    lower.includes("stream-disconnect") ||
    lower.includes("econnreset") ||
    lower.includes("socket hang up")
  ) {
    return "stream-disconnect";
  }

  // ── honest-incomplete (maxIter / missing completion signal) ──────────────
  // Real sources (must match first; "iteration limit" must not fall into quota):
  //   realBackend.ts assertCompletionSignal:
  //     `… did not fire its required completion signal — expected "…", got
  //      none (no signal fired before the iteration limit). …`
  //   shipOutcome / cmr / merger:
  //     `… did not fire its completion signal`
  //   also: "none (no signal fired before the iteration limit)" fragment alone
  if (
    lower.includes("honest-incomplete") ||
    lower.includes("honest incomplete") ||
    lower.includes("incomplete response") ||
    lower.includes("did not fire its required completion") ||
    lower.includes("did not fire its completion signal") ||
    lower.includes("no signal fired before the iteration limit") ||
    (lower.includes("completion signal") &&
      (lower.includes("did not fire") || lower.includes("iteration limit")))
  ) {
    return "honest-incomplete";
  }

  // ── relay-out (SelfReportedRelayError + relay tag text) ──────────────────
  if (
    lower.includes("self-reported blocked") ||
    lower.includes("phase_complete") ||
    lower.includes("relay-out") ||
    // Avoid matching "relay" inside unrelated words; keep common explicit forms.
    lower.includes("resource relay") ||
    /(^|[\s([{])relay([\s)\]}:.,]|$)/.test(lower)
  ) {
    return "relay-out";
  }

  // ── killed (OS signal / explicit kill stamp) ─────────────────────────────
  if (
    lower.includes("killed by signal") ||
    lower.includes("killed") ||
    lower.includes("sigkill") ||
    lower.includes("sigterm") ||
    lower.includes("signal sig")
  ) {
    return "killed";
  }

  return "unclassified";
}

function parseTokenInt(raw: string): number | null {
  const n = Number.parseInt(raw.replace(/,/g, ""), 10);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function matchLastInt(text: string, re: RegExp): number | null {
  let last: string | undefined;
  for (const m of text.matchAll(re)) {
    if (m[1] !== undefined) last = m[1];
  }
  return last === undefined ? null : parseTokenInt(last);
}

// ───────────────────────── record builders ─────────────────────────

export interface BuildDispatchStampInput {
  readonly legId: string;
  readonly spec: WorkerSpec;
  readonly ctx: DispatchContext;
  readonly dispatchedAt: string;
  readonly poolId?: string | null;
  readonly attempt?: number | null;
  readonly now?: () => string;
}

/** Build a dispatch half-row from the seam inputs (nulls for unknowns). */
export function buildDispatchStamp(
  input: BuildDispatchStampInput,
): TelemetryDispatchRecord {
  const { legId, spec, ctx, dispatchedAt } = input;
  const now = input.now?.() ?? new Date().toISOString();
  const model = modelStampFor(spec);
  const poolId =
    input.poolId !== undefined
      ? input.poolId
      : ctx.billingPool !== undefined
        ? ctx.billingPool
        : poolIdForWorker(spec);
  const issue = issueFromContext(ctx);
  const runId = runIdFromContext(ctx);
  return {
    v: TELEMETRY_SCHEMA_VERSION,
    phase: "dispatch",
    stamped_at: now,
    legId,
    runId,
    issue,
    stepId: spec.id,
    role: spec.role,
    kind: spec.kind,
    round: ctx.onlineReviewRound ?? null,
    attempt: input.attempt ?? null,
    model,
    poolId,
    coderRec: coderRecProvenance(spec, ctx),
    cliVersion: cliVersionForSlug(ctx.modelRoute, spec.model),
    dispatched_at: dispatchedAt,
  };
}

export interface BuildCollectStampInput {
  readonly legId: string;
  readonly completedAt: string;
  readonly terminal: TelemetryTerminal;
  readonly errorCategory: TelemetryErrorCategory | null;
  /** Raw failure message; null when terminal has no message. */
  readonly errorMessage?: string | null;
  readonly tokens: TelemetryTokenUsage | null;
  readonly sessionId: string | null;
  readonly logPath: string | null;
  /**
   * First-observed log growth timestamp (poll granularity — not true TTFB).
   * See {@link TelemetryCollectRecord.first_output_at}.
   */
  readonly firstOutputAt: string | null;
  readonly now?: () => string;
}

/** Build a collect half-row. */
export function buildCollectStamp(
  input: BuildCollectStampInput,
): TelemetryCollectRecord {
  const now = input.now?.() ?? new Date().toISOString();
  return {
    v: TELEMETRY_SCHEMA_VERSION,
    phase: "collect",
    stamped_at: now,
    legId: input.legId,
    first_output_at: input.firstOutputAt,
    completed_at: input.completedAt,
    terminal: input.terminal,
    errorCategory: input.errorCategory,
    errorMessage: input.errorMessage ?? null,
    tokens: input.tokens,
    sessionId: input.sessionId,
    logPath: input.logPath,
  };
}

export interface BuildEnvironmentStampInput {
  readonly ctx: DispatchContext;
  readonly imageTag?: string | null;
  readonly imageDigest?: string | null;
  readonly sandboxFingerprint?: string | null;
  readonly soulsHash?: string | null;
  readonly promptHash?: string | null;
  readonly runId?: string | null;
  readonly now?: () => string;
}

/** Build the once-per-run environment stamp. */
export function buildEnvironmentStamp(
  input: BuildEnvironmentStampInput,
): TelemetryEnvironmentRecord {
  const now = input.now?.() ?? new Date().toISOString();
  const route = input.ctx.modelRoute;
  const runEnv = telemetryRunEnvironment;
  // Prefer explicit input → process run config (imageName) → env → default image.
  const rawTag =
    input.imageTag !== undefined
      ? input.imageTag
      : runEnv.imageTag !== undefined
        ? runEnv.imageTag
        : process.env.IMAGE_TAG?.trim() ||
          process.env.ORCHESTRATOR_IMAGE_TAG?.trim() ||
          TELEMETRY_DEFAULT_IMAGE_TAG;
  const imageTag =
    rawTag !== null && rawTag !== undefined && rawTag.length > 0
      ? rawTag
      : null;
  const imageDigest =
    input.imageDigest !== undefined
      ? input.imageDigest
      : runEnv.imageDigest !== undefined
        ? runEnv.imageDigest
        : null;
  const sandboxFingerprint =
    input.sandboxFingerprint !== undefined
      ? input.sandboxFingerprint
      : runEnv.sandboxFingerprint !== undefined
        ? runEnv.sandboxFingerprint
        : null;
  const soulsHash =
    input.soulsHash !== undefined
      ? input.soulsHash
      : runEnv.soulsHash !== undefined
        ? runEnv.soulsHash
        : null;
  const promptHash =
    input.promptHash !== undefined
      ? input.promptHash
      : runEnv.promptHash !== undefined
        ? runEnv.promptHash
        : null;
  return {
    v: TELEMETRY_SCHEMA_VERSION,
    phase: "environment",
    stamped_at: now,
    runId: input.runId ?? runIdFromContext(input.ctx),
    imageTag,
    imageDigest,
    sandboxFingerprint,
    soulsHash,
    promptHash,
    routeName: route?.routeName ?? null,
    routeSlots: route !== undefined ? { ...route.slots } : null,
    routeCmrReviewLegs:
      route !== undefined
        ? route.legCollections.cmrReview.map((leg) => leg.slug)
        : null,
    cliVersions: cliVersionsFromRoute(route),
  };
}

function modelStampFor(spec: WorkerSpec): TelemetryModelStamp {
  let family: string | null = null;
  let effort: string | null = null;
  try {
    family = modelFamilyForSlug(spec.model);
  } catch {
    family = null;
  }
  try {
    const entry = resolveModelSlug(spec.model);
    const opts = entry.options;
    if (opts !== undefined && "effort" in opts) {
      const e = (opts as { readonly effort?: unknown }).effort;
      if (typeof e === "string") effort = e;
    }
    const live = effortForLiveOfficer(spec.model, {
      role: spec.role,
      soul: spec.soul,
    });
    if (live !== undefined) effort = live;
  } catch {
    // unknown slug — leave effort null
  }
  // Prefer process run config (explicit codexFast option) over env alone.
  const fastEnv = process.env.ORCHESTRATOR_CODEX_FAST;
  const configuredFast = telemetryRunEnvironment.codexFast;
  let fast: boolean | null = null;
  if (family === "codex") {
    if (typeof configuredFast === "boolean") {
      fast = configuredFast;
    } else if (fastEnv === "1" || fastEnv === "true") {
      fast = true;
    } else if (fastEnv === "0" || fastEnv === "false") {
      fast = false;
    } else {
      fast = null;
    }
  }
  return {
    slug: spec.model,
    family,
    effort,
    fast,
  };
}

function coderRecProvenance(
  spec: WorkerSpec,
  ctx: DispatchContext,
): TelemetryCoderRecProvenance | null {
  const body = ctx.issueSnapshot?.body;
  const envRaw = process.env.ORCHESTRATOR_CODER_MODEL?.trim();
  const envOverride = envRaw !== undefined && envRaw.length > 0;
  let order: readonly string[] | null = null;
  let primarySlug: string | null = null;
  if (body !== undefined && body.length > 0) {
    try {
      const entries = resolveCoderRecOrder(body);
      order = entries.map((e) => e.id);
      primarySlug = entries[0]?.slug ?? null;
    } catch {
      order = null;
      primarySlug = null;
    }
  }
  // Non-coder legs with no Coder-Rec body and no env override: nothing to stamp.
  if (order === null && !envOverride && spec.kind !== "coder") {
    return null;
  }
  const selected = spec.model;
  let wasFallback: boolean | null = null;
  if (primarySlug !== null) {
    // Head of order is the primary recommendation; anything else is fallback/补位.
    wasFallback = primarySlug !== selected && order?.[0] !== selected;
  }
  return {
    order,
    selected,
    wasFallback,
    envOverride,
  };
}

function issueFromContext(ctx: DispatchContext): number | null {
  if (ctx.issueSnapshot?.number !== undefined) return ctx.issueSnapshot.number;
  if (ctx.familyIssue !== undefined) return ctx.familyIssue;
  if (ctx.stateDir !== undefined) {
    const m = /(?:^|\/)\.ledger-(\d+)\/?$/.exec(ctx.stateDir);
    if (m?.[1] !== undefined) {
      const n = Number.parseInt(m[1], 10);
      if (Number.isInteger(n) && n > 0) return n;
    }
  }
  return null;
}

function runIdFromContext(ctx: DispatchContext): string | null {
  // No dedicated run UUID on DispatchContext yet — use stateDir as a stable proxy.
  return ctx.stateDir ?? null;
}

function cliVersionForSlug(
  route: ResolvedModelRoute | undefined,
  slug: string,
): string | null {
  if (route === undefined) return null;
  // Prefer smoke keys that end with `:${slug}` (routeSmokeEntries key shape).
  for (const [key, status] of Object.entries(route.smoke)) {
    if (status.state === "passed" && (key === slug || key.endsWith(`:${slug}`))) {
      return status.cliVersion;
    }
  }
  // Fall back: return the sole passed smoke when only one model was smoked.
  const passed = Object.values(route.smoke).filter(
    (s): s is Extract<typeof s, { state: "passed" }> => s.state === "passed",
  );
  if (passed.length === 1) return passed[0]!.cliVersion;
  return null;
}

function cliVersionsFromRoute(
  route: ResolvedModelRoute | undefined,
): Readonly<Record<string, string>> | null {
  if (route === undefined) return null;
  const out: Record<string, string> = {};
  for (const [key, status] of Object.entries(route.smoke)) {
    if (status.state !== "passed") continue;
    // Keys look like `coder:grok-4.5` — use the slug suffix when present.
    const colon = key.lastIndexOf(":");
    const slug = colon >= 0 ? key.slice(colon + 1) : key;
    out[slug] = status.cliVersion;
  }
  return Object.keys(out).length > 0 ? out : null;
}

// ───────────────────────── JSONL I/O ─────────────────────────

/** Absolute path of the telemetry sidecar under a ledger/state directory. */
export function telemetryPath(ledgerDir: string): string {
  return join(ledgerDir, TELEMETRY_FILENAME);
}

function writeTelemetryLine(ledgerDir: string, record: TelemetryRecord): void {
  const line = `${JSON.stringify(record)}\n`;
  appendFileSync(telemetryPath(ledgerDir), line, { encoding: "utf8", flag: "a" });
}

/**
 * Append one telemetry record as a single JSONL line.
 *
 * Uses O_APPEND (`flag: "a"`) so short writes are atomic on POSIX.
 * Creates `ledgerDir` when missing. Throws on I/O failure — callers that
 * must not affect worker semantics should wrap in try/catch.
 */
export function appendTelemetryRecord(
  ledgerDir: string,
  record: TelemetryRecord,
): void {
  mkdirSync(ledgerDir, { recursive: true });
  writeTelemetryLine(ledgerDir, record);
}

/**
 * Best-effort append: swallows errors so dispatch never fails on telemetry.
 * Returns true when the line was written.
 *
 * Does **not** invent missing ancestor directories. Unit/integration fixtures
 * pass opaque fake `stateDir` strings (e.g. `/resident/worktrees/.ledger-N`)
 * that must never be materialised: recursive mkdir either spams ENOENT on
 * every worker leg or, when privileged, pollutes the host FS. Production
 * `stateDir` is a sibling under an already-existing worktree parent, so the
 * leaf `.ledger-N` is still created when only that leaf is missing.
 */
export function tryAppendTelemetryRecord(
  ledgerDir: string | undefined,
  record: TelemetryRecord,
): boolean {
  if (ledgerDir === undefined || ledgerDir.length === 0) return false;
  try {
    if (!existsSync(ledgerDir)) {
      const parent = dirname(ledgerDir);
      // Root / empty-parent / non-existent ancestor → silent fail-open.
      if (parent === ledgerDir || parent.length === 0 || !existsSync(parent)) {
        return false;
      }
      mkdirSync(ledgerDir, { recursive: true });
    }
    writeTelemetryLine(ledgerDir, record);
    return true;
  } catch (err) {
    console.warn(
      `[orchestrator] telemetry append failed: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
    return false;
  }
}

/**
 * Ensure a single environment stamp exists for this ledgerDir.
 * Idempotent: skips when an environment phase line is already present.
 */
export function ensureEnvironmentStamp(
  ledgerDir: string | undefined,
  ctx: DispatchContext,
  opts?: {
    readonly imageTag?: string | null;
    readonly imageDigest?: string | null;
    readonly sandboxFingerprint?: string | null;
    readonly soulsHash?: string | null;
    readonly promptHash?: string | null;
    readonly runId?: string | null;
  },
): boolean {
  if (ledgerDir === undefined || ledgerDir.length === 0) return false;
  try {
    if (hasEnvironmentStamp(ledgerDir)) return false;
    return tryAppendTelemetryRecord(
      ledgerDir,
      buildEnvironmentStamp({
        ctx,
        imageTag: opts?.imageTag,
        imageDigest: opts?.imageDigest,
        sandboxFingerprint: opts?.sandboxFingerprint,
        soulsHash: opts?.soulsHash,
        promptHash: opts?.promptHash,
        runId: opts?.runId,
      }),
    );
  } catch (err) {
    console.warn(
      `[orchestrator] telemetry environment stamp failed: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
    return false;
  }
}

/** Cheap, synchronous existence check used before scheduling expensive setup. */
export function hasEnvironmentStamp(ledgerDir: string | undefined): boolean {
  if (ledgerDir === undefined || ledgerDir.length === 0) return false;
  try {
    const path = telemetryPath(ledgerDir);
    return existsSync(path)
      ? readFileSync(path, "utf8").includes('"phase":"environment"')
      : false;
  } catch {
    return false;
  }
}

/**
 * Read and parse all telemetry lines (test / offline consumers).
 * Blank lines skipped; malformed lines throw (fail-closed for tools).
 */
export function readTelemetryRecords(ledgerDir: string): TelemetryRecord[] {
  const path = telemetryPath(ledgerDir);
  if (!existsSync(path)) return [];
  const raw = readFileSync(path, "utf8");
  const out: TelemetryRecord[] = [];
  for (const line of raw.split(/\r?\n/)) {
    if (line.trim().length === 0) continue;
    out.push(JSON.parse(line) as TelemetryRecord);
  }
  return out;
}

/**
 * Slice a shared step log to this dispatch's bytes (logStartOffset..EOF).
 * Used before GC so token lines are captured into the sidecar.
 */
export function readDispatchLogSlice(
  logPath: string | undefined,
  logStartOffset: number | undefined,
): string | null {
  if (logPath === undefined || logPath.length === 0) return null;
  if (!existsSync(logPath)) return null;
  try {
    const buf = readFileSync(logPath);
    const start =
      logStartOffset !== undefined &&
      Number.isInteger(logStartOffset) &&
      logStartOffset >= 0
        ? logStartOffset
        : 0;
    return buf.subarray(Math.min(start, buf.length)).toString("utf8");
  } catch {
    return null;
  }
}
