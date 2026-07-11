/**
 * #786 — orchestrator telemetry sidecar (append-only JSONL).
 *
 * Parallel to the step ledger (`steps.jsonl`): raw per-leg stamps only.
 * Aggregation / stats are out of scope for this ticket.
 *
 * Layout: durable `<ledgerDir>/telemetry.jsonl` — one JSON object per line.
 * Single-slice runs use `<dedicated-clone>/.ledger-<issue>/`; family runs use
 * their existing durable family ledger directory. The legacy
 * `.sandcastle/worktrees/.ledger-<issue>/` location is read-only fallback only.
 * Phases:
 *   - `environment` — once per run (image / route lineup / CLI versions)
 *   - `dispatch`    — half-row at spawn (identity / model / pool / time)
 *   - `collect`     — half-row at finish (terminal / tokens / session / log)
 *   - `verification`— deterministic typecheck / test harness observations
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

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  statSync,
} from "node:fs";
import { appendFile, mkdir, readdir, readFile, stat } from "node:fs/promises";
import { dirname, join } from "node:path";

import ts from "typescript";

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
  Finding,
  PriorFindingDisposition,
  WorkerResult,
  WorkerSpec,
} from "./types.js";
import { findingIdentityKey } from "./findings.js";
import { poolIdForWorker } from "./workerMonitor.js";

/**
 * Same default as {@link DEFAULT_IMAGE_TAG} in familyDriver — kept local so
 * telemetry stays free of the heavy driver/backend import graph.
 */
const TELEMETRY_DEFAULT_IMAGE_TAG = "ming-orchestrator-coder:latest";
/** Bound every best-effort telemetry subprocess so a stuck textconv/filesystem
 * cannot strand the per-ledger collection queue. */
const TELEMETRY_SUBPROCESS_TIMEOUT_MS = 5_000;

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
const pendingTelemetryEnvironmentStamps = new Map<string, Promise<void>>();

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
export async function configureTelemetryFromWorkerImage(opts: {
  readonly imageName: string;
  readonly codexFast?: boolean;
  readonly soulsDir?: string;
  readonly promptsDir?: string;
}): Promise<void> {
  const imageTag =
    opts.imageName.trim().length > 0 ? opts.imageName.trim() : null;
  // Every expensive input starts as asynchronous work before this function
  // yields. The first telemetry row must never delay worker output/exit events.
  const [imageDigest, soulsHash, promptHash] = await Promise.all([
    imageTag !== null ? resolveDockerImageDigestAsync(imageTag) : null,
    opts.soulsDir !== undefined ? hashDirectoryContentsAsync(opts.soulsDir) : null,
    opts.promptsDir !== undefined
      ? hashDirectoryContentsAsync(opts.promptsDir)
      : null,
  ]);
  const sandboxFingerprint =
    imageTag !== null
      ? computeSandboxFingerprintFromHashes({
          imageTag,
          imageDigest,
          soulsHash,
          promptHash,
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

/** Async counterpart used by the first-run environment stamp path. */
function resolveDockerImageDigestAsync(imageTag: string): Promise<string | null> {
  if (imageTag.trim().length === 0) return Promise.resolve(null);
  return new Promise((resolve) => {
    execFile(
      "docker",
      ["image", "inspect", "--format", "{{.Id}}", imageTag],
      { encoding: "utf8", timeout: 5_000 },
      (err, stdout) => {
        if (err !== null) {
          resolve(null);
          return;
        }
        const value = String(stdout).trim();
        resolve(value.length > 0 ? value : null);
      },
    );
  });
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

/**
 * Async stable SHA-256 over files under `dir`. File reads and directory walks
 * leave the event loop available; the periodic setImmediate also prevents a
 * very large cached tree from monopolising the promise queue between reads.
 */
async function hashDirectoryContentsAsync(dir: string): Promise<string | null> {
  if (dir.trim().length === 0) return null;
  try {
    if (!(await stat(dir)).isDirectory()) return null;
    const hash = createHash("sha256");
    const files = (await listFilesRecursiveAsync(dir)).sort();
    if (files.length === 0) {
      hash.update("empty-dir\n");
    }
    for (let index = 0; index < files.length; index += 1) {
      if (index > 0 && index % 32 === 0) {
        await new Promise<void>((resolve) => setImmediate(resolve));
      }
      const rel = files[index]!;
      hash.update(`file:${rel}\0`);
      try {
        hash.update(await readFile(join(dir, rel)));
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

function computeSandboxFingerprintFromHashes(input: {
  readonly imageTag: string;
  readonly imageDigest?: string | null;
  readonly soulsHash?: string | null;
  readonly promptHash?: string | null;
}): string {
  const hash = createHash("sha256");
  hash.update(`image:${input.imageTag}\n`);
  hash.update(`image-id:${input.imageDigest ?? "unknown"}\n`);
  if (input.soulsHash !== undefined) {
    hash.update(`souls:${input.soulsHash ?? "missing"}\n`);
  } else {
    hash.update("souls:unset\n");
  }
  if (input.promptHash !== undefined) {
    hash.update(`prompts:${input.promptHash ?? "missing"}\n`);
  } else {
    hash.update("prompts:unset\n");
  }
  return hash.digest("hex");
}

async function listFilesRecursiveAsync(root: string, base = ""): Promise<string[]> {
  const out: string[] = [];
  let entries: string[];
  try {
    entries = await readdir(join(root, base));
  } catch {
    return out;
  }
  for (const name of entries) {
    const rel = base.length > 0 ? `${base}/${name}` : name;
    const abs = join(root, rel);
    try {
      const entry = await stat(abs);
      if (entry.isDirectory()) {
        out.push(...(await listFilesRecursiveAsync(root, rel)));
      } else if (entry.isFile()) {
        out.push(rel);
      }
    } catch {
      // skip unreadable entries
    }
  }
  return out;
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

/**
 * Durable single-slice telemetry location. `stateDir` is the legacy sibling
 * under `.sandcastle/worktrees`; the dedicated clone root survives Sandcastle
 * worktree pruning and has the same lifetime as the resume ledger.
 */
export function durableTelemetryDirForSingleSlice(
  workingRepo: string,
  stateDir: string | undefined,
): string | undefined {
  if (workingRepo.length === 0 || stateDir === undefined) return undefined;
  const match = /(?:^|[/\\])\.ledger-(\d+)(?:[/\\]|$)/.exec(stateDir);
  const issue = match?.[1];
  return issue === undefined ? undefined : join(workingRepo, `.ledger-${issue}`);
}

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

/** Per integrated-CMR review round, recorded only and never consumed for routing. */
export interface TelemetryReviewRoundRecord extends TelemetryRecordBase {
  readonly phase: "review_round";
  readonly runId: string | null;
  readonly issue: number | null;
  readonly cmrPass: "completeness" | "correctness" | null;
  /** 1-based within a CMR pass in the durable sidecar; null when unavailable. */
  readonly reviewRound: number | null;
  readonly verdict:
    | "converged"
    | "blocking"
    | "not_converged"
    | "escalated"
    | "failed"
    | "malformed"
    | "protocol_failure";
  /**
   * Whether the runner accepted this review result after every terminal gate.
   * `unknown` means runner-side durable persistence threw before the terminal
   * classification completed; the observation must still be retained.
   */
  readonly finalDisposition: "accepted" | "rejected" | "unknown";
  readonly findingsBySeverity: Readonly<Record<Finding["severity"], number>> | null;
  /**
   * Identity recurrence is an exact match on category + location + normalized
   * claim_quote. It is not semantic deduplication: wording or line drift makes
   * the finding look new.
   */
  readonly identityMatch: "exact_identity_match";
  readonly exactIdentityMatchKeys: readonly string[] | null;
  readonly newExactIdentityMatchKeys: readonly string[] | null;
  readonly recurringExactIdentityMatchKeys: readonly string[] | null;
  /** Fresh re-review's disposition of the preceding round's claimed findings. */
  readonly priorFindingDispositions: ReadonlyArray<{
    readonly identityKey: string;
    readonly disposition: "fixed" | "refuted" | "deferred";
  }> | null;
}

/** Raw changed-line counts for one source/test bucket in a commit. */
export interface TelemetryCommitFileDistribution {
  readonly files: number;
  readonly insertions: number;
  readonly deletions: number;
}

/** #782 audit-pattern counts, kept separately for added and removed diff lines. */
export interface TelemetryEscapeHatchCounts {
  readonly asAny: number;
  readonly asNever: number;
  readonly asUnknownAs: number;
  readonly tsIgnore: number;
  readonly tsExpectError: number;
  readonly jsonParseStringify: number;
}

export interface TelemetryCommitMetrics {
  readonly files: number;
  readonly insertions: number;
  readonly deletions: number;
  readonly source: TelemetryCommitFileDistribution;
  readonly test: TelemetryCommitFileDistribution;
  readonly escapeHatches: {
    readonly added: TelemetryEscapeHatchCounts;
    readonly deleted: TelemetryEscapeHatchCounts;
  };
  /** Approximation: added/removed diff lines matching expect( or assert. */
  readonly assertions: { readonly added: number; readonly deleted: number };
}

/** Dispatch identity frozen when the runner schedules a commit collection. */
export interface TelemetryCommitWorkerIdentity {
  /** Orchestrator step / worker leg that produced the observed commit. */
  readonly stepId: string | null;
  /** Exact dispatched model or checkpoint slug; never inferred after the fact. */
  readonly modelSlug: string | null;
}

/** Per host-git commit observation. Telemetry only; never read for routing. */
export interface TelemetryCommitRecord extends TelemetryRecordBase {
  readonly phase: "commit";
  readonly runId: string | null;
  readonly issue: number | null;
  readonly commit: string;
  readonly worker: TelemetryCommitWorkerIdentity;
  readonly files: number | null;
  readonly insertions: number | null;
  readonly deletions: number | null;
  readonly source: TelemetryCommitFileDistribution | null;
  readonly test: TelemetryCommitFileDistribution | null;
  readonly escapeHatches: {
    readonly added: TelemetryEscapeHatchCounts;
    readonly deleted: TelemetryEscapeHatchCounts;
  } | null;
  /** Approximate `expect(`/`assert` changed-line delta; see builder. */
  readonly assertions: { readonly added: number; readonly deleted: number } | null;
}

/** One deterministic typecheck / test harness observation. Telemetry only. */
export interface TelemetryVerificationRecord extends TelemetryRecordBase {
  readonly phase: "verification";
  readonly runId: string | null;
  readonly issue: number | null;
  /** Wave unit lane versus the end-of-run full lane. */
  readonly verification: "typecheck" | "unit" | "full";
  /** Harness exit result; null when the structured observation is unavailable. */
  readonly passed: boolean | null;
  /** Test count only when the harness supplied structured count data. */
  readonly count: number | null;
  /** Monotonic command duration observed by the harness. */
  readonly duration_ms: number | null;
}

export type TelemetryRecord =
  | TelemetryEnvironmentRecord
  | TelemetryDispatchRecord
  | TelemetryCollectRecord
  | TelemetryReviewRoundRecord
  | TelemetryCommitRecord
  | TelemetryVerificationRecord;

// ───────────────────────── pure helpers ─────────────────────────

/** Fresh join key for a dispatch↔collect pair. */
export function newLegId(): string {
  return globalThis.crypto.randomUUID();
}

/** The narrow provider seam shared by single-slice and family backends. */
export interface TelemetryEnvironmentProvider {
  installTelemetryRunEnvironment?(): void | Promise<void>;
}

/**
 * Queue the once-per-run environment row without delaying worker dispatch.
 *
 * Providers must be invoked through their receiver: production backend methods
 * read instance options to reinstall the matching image/prompt fingerprints.
 */
export function scheduleTelemetryEnvironmentStamp(
  ledgerDir: string | undefined,
  ctx: DispatchContext,
  backend: TelemetryEnvironmentProvider,
): Promise<void> {
  // Per-run key (ledgerDir + runId): same durable ledger may host multiple runs.
  // Joinable Promise: callers can await completion without blocking dispatch.
  const runId = runIdFromContext(ctx);
  const pendingKey = `${ledgerDir ?? ""}\0${runId ?? ""}`;
  if (ledgerDir === undefined || ledgerDir.length === 0) {
    return Promise.resolve();
  }
  const pending = pendingTelemetryEnvironmentStamps.get(pendingKey);
  if (pending !== undefined) return pending;

  let complete: () => void;
  const completion = new Promise<void>((resolve) => {
    complete = resolve;
  });
  pendingTelemetryEnvironmentStamps.set(pendingKey, completion);
  queueMicrotask(() => {
    void (async () => {
      try {
        if (!(await hasEnvironmentStampAsync(ledgerDir, runId))) {
          await backend.installTelemetryRunEnvironment?.();
          if (!(await hasEnvironmentStampAsync(ledgerDir, runId))) {
            await tryAppendTelemetryRecordAsync(
              ledgerDir,
              buildEnvironmentStamp({ ctx }),
            );
          }
        }
      } catch (err) {
        console.warn(
          `[orchestrator] telemetry environment stamp failed (fail-open): ${
            err instanceof Error ? err.message : String(err)
          }`,
        );
      } finally {
        if (pendingTelemetryEnvironmentStamps.get(pendingKey) === completion) {
          pendingTelemetryEnvironmentStamps.delete(pendingKey);
        }
        complete();
      }
    })();
  });
  return completion;
}

export type TelemetryWorkerOutcome =
  | { readonly kind: "result"; readonly result: WorkerResult }
  | { readonly kind: "thrown"; readonly error: unknown };

export interface TelemetryLegCollectInput {
  readonly logPath?: string | null;
  readonly logStartOffset?: number;
  readonly firstOutputAt?: string | null;
}

export interface TelemetryLegStamper {
  stampDispatch(dispatchedAt: string, poolId?: string): void;
  stampCollect(
    outcome: TelemetryWorkerOutcome,
    input?: TelemetryLegCollectInput,
  ): void;
}

/**
 * Build a fail-open paired dispatch/collect stamper for one worker leg.
 * Both dispatch seams use this so terminal taxonomy and JSONL join semantics
 * cannot drift between single-slice and family workers.
 */
export function createTelemetryLegStamper(input: {
  readonly ledgerDir: string | undefined;
  readonly spec: WorkerSpec;
  readonly ctx: DispatchContext;
}): TelemetryLegStamper {
  let legId: string | null = null;
  let modelFamily: string | null = null;
  let collectStamped = false;
  let dispatchStamped = false;

  try {
    legId = newLegId();
    modelFamily = buildDispatchStamp({
      legId,
      spec: input.spec,
      ctx: input.ctx,
      dispatchedAt: new Date().toISOString(),
    }).model.family;
  } catch (err) {
    console.warn(
      `[orchestrator] telemetry init failed (fail-open): ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }

  return {
    stampDispatch(dispatchedAt: string, poolId?: string): void {
      if (legId === null) return;
      try {
        dispatchStamped = tryAppendTelemetryRecord(
          input.ledgerDir,
          buildDispatchStamp({
            legId,
            spec: input.spec,
            ctx: input.ctx,
            dispatchedAt,
            poolId,
          }),
        );
      } catch (err) {
        dispatchStamped = false;
        console.warn(
          `[orchestrator] telemetry dispatch stamp failed (fail-open): ${
            err instanceof Error ? err.message : String(err)
          }`,
        );
      }
    },
    stampCollect(
      outcome: TelemetryWorkerOutcome,
      collectInput: TelemetryLegCollectInput = {},
    ): void {
      if (collectStamped || legId === null || !dispatchStamped) return;
      collectStamped = true;
      try {
        const logText = readDispatchLogSlice(
          collectInput.logPath ?? undefined,
          collectInput.logStartOffset,
        );
        const classified = classifyWorkerTerminal(outcome);
        tryAppendTelemetryRecord(
          input.ledgerDir,
          buildCollectStamp({
            legId,
            completedAt: new Date().toISOString(),
            terminal: classified.terminal,
            errorCategory: classified.errorCategory,
            errorMessage: classified.errorMessage,
            tokens:
              logText !== null
                ? extractTokensFromLog(logText, modelFamily)
                : null,
            sessionId: classified.sessionId,
            logPath: collectInput.logPath ?? null,
            firstOutputAt: collectInput.firstOutputAt ?? null,
          }),
        );
      } catch (err) {
        console.warn(
          `[orchestrator] telemetry collect stamp failed (fail-open): ${
            err instanceof Error ? err.message : String(err)
          }`,
        );
      }
    },
  };
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

  // ── honest-incomplete (missing completion signal) ─────────────────────────
  // Real sources (must match first): shipOutcome / cmr / merger:
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

export interface BuildReviewRoundStampInput {
  readonly stampedAt?: string;
  readonly runId?: string | null;
  readonly issue?: number | null;
  readonly cmrPass?: "completeness" | "correctness" | null;
  readonly reviewRound?: number | null;
  readonly verdict: TelemetryReviewRoundRecord["verdict"];
  readonly finalDisposition: TelemetryReviewRoundRecord["finalDisposition"];
  /** Omit when the reviewer produced no parseable CMR result. */
  readonly findings?: readonly Finding[];
  readonly priorReviewRecords?: readonly TelemetryReviewRoundRecord[];
  readonly priorFindingDispositions?: readonly PriorFindingDisposition[];
}

export interface BuildCommitStampInput {
  readonly stampedAt?: string;
  readonly runId?: string | null;
  readonly issue?: number | null;
  readonly commit: string;
  /** Dispatch identity frozen by the runner when collection was scheduled. */
  readonly worker?: TelemetryCommitWorkerIdentity;
  /** Host-git numstat result. Omit when collection failed: all metrics become null. */
  readonly metrics?: TelemetryCommitMetrics;
  /** Changed lines from host `git show --unified=0`, for #782 / assertion auditing. */
  readonly diffLines?: readonly string[];
  /** TypeScript-scanned comment/string spans mapped from the relevant diff image. */
  readonly triviaByDiffIndex?: ReadonlyMap<number, readonly TriviaSpan[]>;
  /** Whether the corresponding changed line belongs to a supported code file. */
  readonly codeByDiffIndex?: ReadonlyMap<number, boolean>;
}

export interface BuildVerificationStampInput {
  readonly stampedAt?: string;
  readonly runId?: string | null;
  readonly issue?: number | null;
  readonly verification: TelemetryVerificationRecord["verification"];
  readonly passed?: boolean | null;
  readonly count?: number | null;
  readonly durationMs?: number | null;
}

const EMPTY_ESCAPE_HATCH_COUNTS: TelemetryEscapeHatchCounts = {
  asAny: 0,
  asNever: 0,
  asUnknownAs: 0,
  tsIgnore: 0,
  tsExpectError: 0,
  jsonParseStringify: 0,
};

const ESCAPE_HATCH_PATTERNS = {
  asAny: /\bas\s+any\b/,
  asNever: /\bas\s+never\b/,
  asUnknownAs: /\bas\s+unknown\s+as\b/,
  tsIgnore: /@ts-ignore\b/,
  tsExpectError: /@ts-expect-error\b/,
  jsonParseStringify: /\bJSON\s*\.\s*parse\s*\(\s*JSON\s*\.\s*stringify\s*\(/,
} as const;

function changedLineKind(line: string): "added" | "deleted" | undefined {
  if (line.startsWith("+++") || line.startsWith("---")) return undefined;
  if (line.startsWith("+")) return "added";
  if (line.startsWith("-")) return "deleted";
  return undefined;
}

type TriviaKind = "comment" | "string";

export interface TriviaSpan {
  readonly start: number;
  readonly end: number;
  readonly kind: TriviaKind;
}

function triviaKindForToken(kind: ts.SyntaxKind): TriviaKind | undefined {
  if (kind === ts.SyntaxKind.SingleLineCommentTrivia || kind === ts.SyntaxKind.MultiLineCommentTrivia) {
    return "comment";
  }
  if (
    kind === ts.SyntaxKind.StringLiteral ||
    kind === ts.SyntaxKind.NoSubstitutionTemplateLiteral ||
    kind === ts.SyntaxKind.TemplateHead ||
    kind === ts.SyntaxKind.TemplateMiddle ||
    kind === ts.SyntaxKind.LastTemplateToken
  ) {
    return "string";
  }
  return undefined;
}

/**
 * Use TypeScript's scanner for language-level trivia/string boundaries. Template
 * substitutions are scanned as ordinary code; only their literal segments are
 * masked. This deliberately replaces the former hand-written quote/comment state
 * machine.
 */
function scriptKindForPath(path: string | undefined): ts.ScriptKind | undefined {
  // Diff fallbacks have no path; retain TSX there so hand-built JSX diff tests
  // are still recognised. Real git image scans always provide a file path.
  if (path === undefined) return ts.ScriptKind.TSX;
  if (/\.(?:tsx|jsx)$/i.test(path)) return ts.ScriptKind.TSX;
  return /\.(?:ts|mts|cts|js)$/i.test(path) ? ts.ScriptKind.TS : undefined;
}

function triviaSpansByLine(
  source: string,
  path?: string,
): ReadonlyMap<number, readonly TriviaSpan[]> {
  const result = new Map<number, TriviaSpan[]>();
  const lineStarts = [0];
  for (let index = 0; index < source.length; index += 1) {
    if (source[index] === "\n") lineStarts.push(index + 1);
  }
  const lineForOffset = (offset: number): number => {
    let low = 0;
    let high = lineStarts.length;
    while (low + 1 < high) {
      const middle = Math.floor((low + high) / 2);
      if (lineStarts[middle]! <= offset) low = middle;
      else high = middle;
    }
    return low + 1;
  };
  const addTriviaSpan = (start: number, end: number, kind: TriviaKind): void => {
    const firstLine = lineForOffset(start);
    const lastLine = lineForOffset(Math.max(start, end - 1));
    for (let line = firstLine; line <= lastLine; line += 1) {
      const lineStart = lineStarts[line - 1]!;
      const lineEnd = lineStarts[line] === undefined ? source.length : lineStarts[line]! - 1;
      const spans = result.get(line) ?? [];
      spans.push({ start: Math.max(start, lineStart) - lineStart, end: Math.min(end, lineEnd) - lineStart, kind });
      result.set(line, spans);
    }
  };
  const scanner = ts.createScanner(ts.ScriptTarget.Latest, false, ts.LanguageVariant.Standard, source);
  const templateExpressionDepths: number[] = [];
  for (let token = scanner.scan(); token !== ts.SyntaxKind.EndOfFileToken; token = scanner.scan()) {
    const kind = triviaKindForToken(token);
    if (kind !== undefined) {
      addTriviaSpan(scanner.getTokenStart(), scanner.getTokenEnd(), kind);
    }
    if (token === ts.SyntaxKind.TemplateHead || token === ts.SyntaxKind.TemplateMiddle) {
      templateExpressionDepths.push(0);
    } else if (token === ts.SyntaxKind.FirstPunctuation && templateExpressionDepths.length > 0) {
      templateExpressionDepths[templateExpressionDepths.length - 1]! += 1;
    } else if (token === ts.SyntaxKind.CloseBraceToken && templateExpressionDepths.length > 0) {
      const top = templateExpressionDepths.length - 1;
      if (templateExpressionDepths[top]! > 0) {
        templateExpressionDepths[top]! -= 1;
      } else {
        const templateToken = scanner.reScanTemplateToken(false);
        const templateKind = triviaKindForToken(templateToken);
        if (templateKind !== undefined) {
          addTriviaSpan(scanner.getTokenStart(), scanner.getTokenEnd(), templateKind);
        }
        if (templateToken !== ts.SyntaxKind.TemplateMiddle) templateExpressionDepths.pop();
      }
    }
  }
  // The scanner's normal token stream intentionally does not enter JSX-text
  // mode. Parse only JSX-bearing files as TSX to obtain those spans; parsing a
  // .ts generic arrow as TSX can otherwise turn its body into JsxText and hide
  // a real escape hatch. TypeScript source offsets remain UTF-16 code-unit
  // offsets just like the scanner offsets above.
  const sourceFile = ts.createSourceFile(
    path ?? "telemetry.tsx",
    source,
    ts.ScriptTarget.Latest,
    true,
    scriptKindForPath(path) ?? ts.ScriptKind.TS,
  );
  const visit = (node: ts.Node): void => {
    if (node.kind === ts.SyntaxKind.JsxText) {
      addTriviaSpan(node.getStart(sourceFile), node.getEnd(), "string");
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return result;
}

function fallbackTriviaByDiffIndex(diffLines: readonly string[]): ReadonlyMap<number, readonly TriviaSpan[]> {
  const result = new Map<number, readonly TriviaSpan[]>();
  for (const kind of ["added", "deleted"] as const) {
    const indexes = diffLines.flatMap((line, index) => changedLineKind(line) === kind ? [index] : []);
    const source = indexes.map((index) => diffLines[index]!.slice(1)).join("\n");
    const byLine = triviaSpansByLine(source);
    for (const [offset, index] of indexes.entries()) result.set(index, byLine.get(offset + 1) ?? []);
  }
  return result;
}

function auditableLine(line: string, spans: readonly TriviaSpan[]): string | undefined {
  const kind = changedLineKind(line);
  if (kind === undefined) return undefined;
  const content = line.slice(1);
  const directive = spans.find((span) =>
    span.kind === "comment" &&
    /^\s*(?:\/\/|\/\*|\*)\s*@ts-(?:ignore|expect-error)\b/.test(content.slice(span.start, span.end)),
  );
  if (directive !== undefined) return content.slice(directive.start, directive.end);
  // TypeScript scanner offsets index UTF-16 code units, so this must not use
  // a code-point iterator (`[...content]`): astral characters occupy two
  // scanner offsets but one code point.
  const characters = content.split("");
  for (const span of spans) characters.fill(" ", span.start, span.end);
  const code = characters.join("").trim();
  return code === "" ? undefined : code;
}

/**
 * Build one raw per-commit observation. Assertion counts are intentionally
 * approximate: changed, non-comment lines matching `expect(` or `assert`.
 * Metrics omitted after a host-git error are null, never a control-flow error.
 */
export function buildCommitStamp(input: BuildCommitStampInput): TelemetryCommitRecord {
  // These dimensions come exclusively from the independent patch read. A
  // successful numstat must not turn a failed diff read into synthetic zeroes.
  let escapeHatches: TelemetryCommitRecord["escapeHatches"] = null;
  let assertions: TelemetryCommitRecord["assertions"] = null;
  if (input.diffLines !== undefined) {
    const added = { ...EMPTY_ESCAPE_HATCH_COUNTS };
    const deleted = { ...EMPTY_ESCAPE_HATCH_COUNTS };
    let addedAssertions = 0;
    let deletedAssertions = 0;
    const triviaByDiffIndex = input.triviaByDiffIndex ?? fallbackTriviaByDiffIndex(input.diffLines);
    for (const [index, line] of input.diffLines.entries()) {
      const kind = changedLineKind(line);
      if (input.codeByDiffIndex?.get(index) === false) continue;
      const content = auditableLine(line, triviaByDiffIndex.get(index) ?? []);
      if (kind === undefined || content === undefined) continue;
      const counts = kind === "added" ? added : deleted;
      for (const [name, pattern] of Object.entries(ESCAPE_HATCH_PATTERNS) as Array<
        [keyof TelemetryEscapeHatchCounts, RegExp]
      >) {
        if (pattern.test(content)) counts[name] += 1;
      }
      if (/\bexpect\s*\(|\bassert(?:\s*\(|\s*\.)/.test(content)) {
        if (kind === "added") addedAssertions += 1;
        else deletedAssertions += 1;
      }
    }
    escapeHatches = { added, deleted };
    assertions = { added: addedAssertions, deleted: deletedAssertions };
  }
  const metrics = input.metrics;
  return {
    v: TELEMETRY_SCHEMA_VERSION,
    phase: "commit",
    stamped_at: input.stampedAt ?? new Date().toISOString(),
    runId: input.runId ?? null,
    issue: input.issue ?? null,
    commit: input.commit,
    worker: input.worker ?? { stepId: null, modelSlug: null },
    files: metrics?.files ?? null,
    insertions: metrics?.insertions ?? null,
    deletions: metrics?.deletions ?? null,
    source: metrics?.source ?? null,
    test: metrics?.test ?? null,
    escapeHatches: escapeHatches ?? null,
    assertions: assertions ?? null,
  };
}

/** Build a raw verification observation without deriving any control-flow state. */
export function buildVerificationStamp(
  input: BuildVerificationStampInput,
): TelemetryVerificationRecord {
  return {
    v: TELEMETRY_SCHEMA_VERSION,
    phase: "verification",
    stamped_at: input.stampedAt ?? new Date().toISOString(),
    runId: input.runId ?? null,
    issue: input.issue ?? null,
    verification: input.verification,
    passed: input.passed ?? null,
    count: input.count ?? null,
    duration_ms: input.durationMs ?? null,
  };
}

function emptyCommitDistribution(): TelemetryCommitFileDistribution {
  return { files: 0, insertions: 0, deletions: 0 };
}

function addCommitDistribution(
  distribution: TelemetryCommitFileDistribution,
  insertions: number,
  deletions: number,
): TelemetryCommitFileDistribution {
  return {
    files: distribution.files + 1,
    insertions: distribution.insertions + insertions,
    deletions: distribution.deletions + deletions,
  };
}

function isTestPath(path: string): boolean {
  return /(?:^|\/)(?:test|tests)(?:\/|$)|\.(?:test|spec)\.[cm]?[jt]sx?$/.test(path);
}

function isSourcePath(path: string): boolean {
  return /(?:^|\/)src(?:\/|$)/.test(path);
}

async function gitOutput(
  repoPath: string,
  args: readonly string[],
): Promise<string | undefined> {
  return await new Promise((resolve) => {
    execFile("git", [...args], {
      cwd: repoPath,
      encoding: "utf8",
      timeout: TELEMETRY_SUBPROCESS_TIMEOUT_MS,
      killSignal: "SIGTERM",
    }, (err, stdout) => {
      resolve(err === null ? String(stdout) : undefined);
    });
  });
}

export async function collectCommitMetricsAsync(
  repoPath: string,
  commit: string,
): Promise<TelemetryCommitMetrics | undefined> {
  const output = await gitOutput(repoPath, ["show", "--format=", "--numstat", commit]);
  if (output === undefined) return undefined;
  return parseCommitMetrics(output);
}

function parseCommitMetrics(output: string): TelemetryCommitMetrics | undefined {
  let files = 0;
  let insertions = 0;
  let deletions = 0;
  let source = emptyCommitDistribution();
  let test = emptyCommitDistribution();
  for (const line of output.split(/\r?\n/)) {
    if (line.length === 0) continue;
    const [addedRaw, deletedRaw, path] = line.split("\t", 3);
    // git --numstat uses "-" for both counts of a binary file. Keep the
    // commit-level telemetry available and represent its uncountable line
    // changes as zero; the file still contributes to the file/path totals.
    const binary = addedRaw === "-" && deletedRaw === "-";
    const added = binary ? 0 : Number(addedRaw);
    const deleted = binary ? 0 : Number(deletedRaw);
    if (path === undefined || !Number.isInteger(added) || !Number.isInteger(deleted)) return undefined;
    files += 1;
    insertions += added;
    deletions += deleted;
    if (isTestPath(path)) test = addCommitDistribution(test, added, deleted);
    else if (isSourcePath(path)) source = addCommitDistribution(source, added, deleted);
  }
  return {
    files, insertions, deletions, source, test,
    escapeHatches: { added: { ...EMPTY_ESCAPE_HATCH_COUNTS }, deleted: { ...EMPTY_ESCAPE_HATCH_COUNTS } },
    assertions: { added: 0, deleted: 0 },
  };
}

export interface CommitDiffAudit {
  readonly diffLines: readonly string[];
  readonly triviaByDiffIndex: ReadonlyMap<number, readonly TriviaSpan[]>;
  /** Code-file gate for line-pattern metrics; non-code files retain numstat only. */
  readonly codeByDiffIndex: ReadonlyMap<number, boolean>;
}

export async function collectCommitDiffAuditAsync(
  repoPath: string,
  commit: string,
): Promise<CommitDiffAudit | undefined> {
  const diff = await gitOutput(repoPath, ["show", "--format=", "--unified=0", commit]);
  if (diff === undefined) return undefined;
  const diffLines = diff.split(/\r?\n/);
  try {
    const postImageTriviaByPath = new Map<string, ReadonlyMap<number, readonly TriviaSpan[]>>();
    const preImageTriviaByPath = new Map<string, ReadonlyMap<number, readonly TriviaSpan[]>>();
    const triviaByDiffIndex = new Map<number, readonly TriviaSpan[]>();
    const codeByDiffIndex = new Map<number, boolean>();
    let prePath: string | undefined;
    let postPath: string | undefined;
    let preImageLine: number | undefined;
    let postImageLine: number | undefined;
    for (const [index, line] of diffLines.entries()) {
      if (line.startsWith("--- ")) { const raw = line.slice(4); prePath = raw.startsWith("a/") ? raw.slice(2) : undefined; continue; }
      if (line.startsWith("+++ ")) { const raw = line.slice(4); postPath = raw.startsWith("b/") ? raw.slice(2) : undefined; continue; }
      const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
      if (hunk !== null) { preImageLine = Number(hunk[1]); postImageLine = Number(hunk[2]); continue; }
      if (line.startsWith("+") && !line.startsWith("+++")) {
        if (postPath === undefined || postImageLine === undefined) return undefined;
        const scriptKind = scriptKindForPath(postPath);
        codeByDiffIndex.set(index, scriptKind !== undefined);
        if (scriptKind === undefined) { postImageLine += 1; continue; }
        let spans = postImageTriviaByPath.get(postPath);
        if (spans === undefined) {
          const image = await gitOutput(repoPath, ["show", `${commit}:${postPath}`]);
          if (image === undefined) return undefined;
          spans = triviaSpansByLine(image, postPath);
          postImageTriviaByPath.set(postPath, spans);
        }
        triviaByDiffIndex.set(index, spans.get(postImageLine) ?? []);
        postImageLine += 1;
      } else if (line.startsWith("-") && !line.startsWith("---")) {
        if (prePath === undefined || preImageLine === undefined) return undefined;
        const scriptKind = scriptKindForPath(prePath);
        codeByDiffIndex.set(index, scriptKind !== undefined);
        if (scriptKind === undefined) { preImageLine += 1; continue; }
        let spans = preImageTriviaByPath.get(prePath);
        if (spans === undefined) {
          const image = await gitOutput(repoPath, ["show", `${commit}^:${prePath}`]);
          if (image === undefined) return undefined;
          spans = triviaSpansByLine(image, prePath);
          preImageTriviaByPath.set(prePath, spans);
        }
        triviaByDiffIndex.set(index, spans.get(preImageLine) ?? []);
        preImageLine += 1;
      } else { preImageLine = preImageLine === undefined ? undefined : preImageLine + 1; postImageLine = postImageLine === undefined ? undefined : postImageLine + 1; }
    }
    return { diffLines, triviaByDiffIndex, codeByDiffIndex };
  } catch { return undefined; }
}

export async function commitsBetweenAsync(repoPath: string, before: string, after: string): Promise<readonly string[] | undefined> {
  const output = await gitOutput(repoPath, ["rev-list", "--reverse", `${before}..${after}`]);
  return output?.split(/\r?\n/).map((value) => value.trim()).filter((value) => value.length > 0);
}

/**
 * Build one raw review-round observation. It deliberately only derives
 * observability fields: nothing here may influence review/fix control flow.
 */
export function buildReviewRoundStamp(
  input: BuildReviewRoundStampInput,
): TelemetryReviewRoundRecord {
  const findings = input.findings;
  const exactIdentityMatchKeys =
    findings === undefined
      ? null
      : [...new Set(findings.map(findingIdentityKey))];
  const priorKeys = new Set(
    (input.priorReviewRecords ?? []).flatMap(
      (record) => record.exactIdentityMatchKeys ?? [],
    ),
  );
  const findingsBySeverity =
    findings === undefined
      ? null
      : findings.reduce<Record<Finding["severity"], number>>(
          (counts, finding) => {
            counts[finding.severity] += 1;
            return counts;
          },
          { critical: 0, high: 0, medium: 0, low: 0, clarity: 0 },
        );
  const disposition = (status: PriorFindingDisposition["status"]): "fixed" | "refuted" | "deferred" =>
    status === "verified-closed"
      ? "fixed"
      : status === "accepted_suppressed"
        ? "refuted"
        : "deferred";
  return {
    v: TELEMETRY_SCHEMA_VERSION,
    phase: "review_round",
    stamped_at: input.stampedAt ?? new Date().toISOString(),
    runId: input.runId ?? null,
    issue: input.issue ?? null,
    cmrPass: input.cmrPass ?? null,
    reviewRound: input.reviewRound ?? null,
    verdict: input.verdict,
    finalDisposition: input.finalDisposition,
    findingsBySeverity,
    identityMatch: "exact_identity_match",
    exactIdentityMatchKeys,
    newExactIdentityMatchKeys:
      exactIdentityMatchKeys === null
        ? null
        : exactIdentityMatchKeys.filter((key) => !priorKeys.has(key)),
    recurringExactIdentityMatchKeys:
      exactIdentityMatchKeys === null
        ? null
        : exactIdentityMatchKeys.filter((key) => priorKeys.has(key)),
    priorFindingDispositions:
      input.priorFindingDispositions === undefined
        ? null
        : input.priorFindingDispositions.map((item) => ({
            identityKey: item.identityKey,
            disposition: disposition(item.status),
          })),
  };
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
  return ctx.runId ?? null;
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

async function tryAppendTelemetryRecordAsync(
  ledgerDir: string | undefined,
  record: TelemetryRecord,
): Promise<void> {
  if (ledgerDir === undefined || ledgerDir.length === 0) return;
  try {
    try {
      await stat(ledgerDir);
    } catch {
      const parent = dirname(ledgerDir);
      if (parent === ledgerDir || parent.length === 0) return;
      try {
        await stat(parent);
      } catch {
        return;
      }
      await mkdir(ledgerDir, { recursive: true });
    }
    await appendFile(telemetryPath(ledgerDir), `${JSON.stringify(record)}\n`, {
      encoding: "utf8",
      flag: "a",
    });
  } catch (err) {
    console.warn(`[orchestrator] telemetry append failed: ${err instanceof Error ? err.message : String(err)}`);
  }
}

export interface CommitTelemetryScheduleInput {
  readonly ledgerDir: string | undefined;
  readonly repoPath: string;
  readonly runId?: string;
  readonly issue?: number | null;
  /** Worker identity captured at the scheduling seam, before deferred collection. */
  readonly worker?: TelemetryCommitWorkerIdentity;
  readonly before: CommitTelemetryBoundary;
  readonly after: CommitTelemetryHeldBoundary;
}

/** A boundary captured synchronously before telemetry enters its deferred queue. */
export type CommitTelemetryHeldBoundary =
  | string
  | { readonly kind: "held"; readonly oid: string };

/** Before may be derived from the frozen after oid when no prior oid is held. */
export type CommitTelemetryBoundary =
  | CommitTelemetryHeldBoundary
  | { readonly kind: "resolve-before-head"; readonly commitsAdded: number };

interface CommitTelemetryCollectInput extends Omit<CommitTelemetryScheduleInput, "before" | "after"> {
  readonly before: string;
  readonly after: string;
}

/** One deferred collection chain per sidecar, preserving observation order. */
const telemetryCollectionQueues = new Map<string, Promise<void>>();

/**
 * Defer best-effort commit observation until after the caller has yielded its
 * routing decision. Its commit range is frozen at scheduling time; collection
 * uses only async subprocess and file I/O.
 */
export function scheduleCommitTelemetry(
  input: CommitTelemetryScheduleInput,
  collect: (input: CommitTelemetryCollectInput) => Promise<void> = collectCommitTelemetry,
): Promise<void> {
  let settle!: () => void;
  const completion = new Promise<void>((resolve) => { settle = resolve; });
  const prior = input.ledgerDir === undefined
    ? undefined
    : telemetryCollectionQueues.get(input.ledgerDir);
  const queued = (prior ?? Promise.resolve()).catch(() => undefined).then(async () => {
    await new Promise<void>((resolve) => setImmediate(resolve));
    const after = typeof input.after === "string" ? input.after : input.after.oid;
    const before = typeof input.before === "string" ? input.before
      : input.before.kind === "held" ? input.before.oid
      : input.before.kind === "resolve-before-head" && after !== undefined
        ? await gitOutput(input.repoPath, ["rev-parse", `${after}~${input.before.commitsAdded}`]).then((oid) => oid?.trim() || undefined)
        : undefined;
    if (before === undefined || after === undefined || before === after) return;
    await collect({ ...input, before, after });
  });
  if (input.ledgerDir !== undefined) telemetryCollectionQueues.set(input.ledgerDir, queued);
  void queued.catch((err: unknown) => {
    console.warn(`[orchestrator] commit telemetry failed (fail-open): ${err instanceof Error ? err.message : String(err)}`);
  }).finally(() => {
    if (input.ledgerDir !== undefined && telemetryCollectionQueues.get(input.ledgerDir) === queued) {
      telemetryCollectionQueues.delete(input.ledgerDir);
    }
    settle();
  });
  return completion;
}

async function collectCommitTelemetry(input: CommitTelemetryCollectInput): Promise<void> {
  if (input.before === input.after) return;
  const commits = await commitsBetweenAsync(input.repoPath, input.before, input.after) ?? [input.after];
  for (const commit of commits) {
    const [metrics, diffAudit] = await Promise.all([
      collectCommitMetricsAsync(input.repoPath, commit),
      collectCommitDiffAuditAsync(input.repoPath, commit),
    ]);
    await tryAppendTelemetryRecordAsync(input.ledgerDir, buildCommitStamp({
      runId: input.runId,
      issue: input.issue ?? null,
      commit,
      ...(input.worker !== undefined ? { worker: input.worker } : {}),
      ...(metrics !== undefined ? { metrics } : {}),
      ...(diffAudit !== undefined ? diffAudit : {}),
    }));
  }
}

/**
 * Best-effort verification append. This remains deliberately write-only: a
 * missing sidecar must never alter the family verification verdict or routing.
 */
export async function recordVerificationStamp(
  ledgerDir: string | undefined,
  input: BuildVerificationStampInput,
): Promise<boolean> {
  if (ledgerDir === undefined || ledgerDir.length === 0) return false;
  try {
    try {
      await stat(ledgerDir);
    } catch {
      const parent = dirname(ledgerDir);
      if (parent === ledgerDir || parent.length === 0) return false;
      try {
        await stat(parent);
      } catch {
        return false;
      }
      await mkdir(ledgerDir, { recursive: true });
    }
    await appendFile(telemetryPath(ledgerDir), `${JSON.stringify(buildVerificationStamp(input))}\n`, {
      encoding: "utf8",
      flag: "a",
    });
    return true;
  } catch (err) {
    console.warn(
      `[orchestrator] verification telemetry failed (fail-open): ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
    return false;
  }
}

/**
 * Ensure a single environment stamp exists for this ledgerDir and run.
 * Idempotent: skips when an environment phase line for the current run is
 * already present.
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
    const runId = opts?.runId ?? runIdFromContext(ctx);
    if (hasEnvironmentStamp(ledgerDir, runId)) return false;
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

/** Cheap, synchronous existence check for one run before expensive setup. */
export function hasEnvironmentStamp(
  ledgerDir: string | undefined,
  runId: string | null = null,
): boolean {
  if (ledgerDir === undefined || ledgerDir.length === 0) return false;
  try {
    const path = telemetryPath(ledgerDir);
    if (!existsSync(path)) return false;
    return readFileSync(path, "utf8")
      .split("\n")
      .some((line) => {
        if (line.trim().length === 0) return false;
        try {
          const record = JSON.parse(line) as {
            readonly phase?: unknown;
            readonly runId?: unknown;
          };
          return record.phase === "environment" && record.runId === runId;
        } catch {
          return false;
        }
      });
  } catch {
    return false;
  }
}

async function hasEnvironmentStampAsync(
  ledgerDir: string | undefined,
  runId: string | null = null,
): Promise<boolean> {
  if (ledgerDir === undefined || ledgerDir.length === 0) return false;
  try {
    const content = await readFile(telemetryPath(ledgerDir), "utf8");
    return content.split("\n").some((line) => {
      if (line.trim().length === 0) return false;
      try {
        const record = JSON.parse(line) as TelemetryRecord;
        return record.phase === "environment" && record.runId === runId;
      } catch {
        return false;
      }
    });
  } catch {
    return false;
  }
}

/**
 * Read and parse all telemetry lines (test / offline consumers).
 * Blank lines skipped; malformed lines throw (fail-closed for tools).
 */
export function readTelemetryRecords(
  ledgerDir: string,
  legacyLedgerDir?: string,
): TelemetryRecord[] {
  const path = telemetryPath(ledgerDir);
  const readPath = existsSync(path)
    ? path
    : legacyLedgerDir === undefined
      ? undefined
      : telemetryPath(legacyLedgerDir);
  if (readPath === undefined || !existsSync(readPath)) return [];
  const raw = readFileSync(readPath, "utf8");
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
