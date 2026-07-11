/**
 * #686 — relay dispatch: tag contract, handoff triggers, resource-failure
 * boundary vs mechanical retry, ledger + parameter-file forwarding, and
 * review-gate closure.
 *
 * Builds on #683 (quota probe / park) and #767 (Coder-Rec roster). Does not
 * duplicate those modules — forks at the #683 disposition point and selects
 * the next baton via the same roster + ADR 0124 pool-orthogonal lookup.
 */

import { execFileSync } from "node:child_process";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { randomUUID } from "node:crypto";
import { join, resolve } from "node:path";
import { z } from "zod";
import type { CoderRosterEntry } from "./coderRoster.js";
import type { IdleDisposition } from "./quotaProbe.js";
import type { StepId } from "./types.js";
import {
  decideParkOrRelay,
  hasLiveRelayBaton,
  selectCapacityRelayBaton,
  selectNextRelayBaton,
  type BillingPoolEntry,
  type BillingPoolId,
  type NextRelayBaton,
  type ParkOrRelayDecision,
} from "./quotaPoolTable.js";

// ── <relay> tag contract (mirror ship/cmr fail-closed shape) ────────────────

const nonEmpty = z.string().trim().min(1);

const phaseCompleteSchema = z
  .object({
    phase_complete: z.enum(["build", "clear"]),
    state_summary: nonEmpty,
    remaining: nonEmpty,
  })
  .strict();

const blockedSchema = z
  .object({
    blocked: z
      .object({
        reason: nonEmpty,
        state_summary: nonEmpty,
        remaining: nonEmpty.optional(),
      })
      .strict(),
  })
  .strict();

const resourceSignalSchema = z
  .object({
    resource: z.literal(true),
    phase: z.enum(["build", "clear"]),
    state_summary: nonEmpty,
    remaining: nonEmpty,
  })
  .strict();

const decisionGateSignalSchema = z
  .object({
    decision_gate: z.literal(true),
    state_summary: nonEmpty,
    remaining: nonEmpty.optional(),
  })
  .strict();

export type RelayTagOutcome =
  | {
      readonly kind: "phase_complete";
      readonly phase: "build" | "clear";
      readonly state_summary: string;
      readonly remaining: string;
    }
  | {
      readonly kind: "blocked";
      readonly reason: string;
      readonly state_summary: string;
      readonly remaining?: string;
    }
  | {
      readonly kind: "decision_gate";
      readonly state_summary: string;
      readonly remaining?: string;
    }
  | { readonly kind: "malformed"; readonly reason: string };

/**
 * Parse the worker's `<relay>{…}</relay>` terminal. Resource relay and human
 * decision are explicit signal bits; their prose is opaque context. Legacy
 * #686 shapes remain readable during the rollout. Malformed tags are ignored.
 */
export function parseRelayTag(stdout: string): RelayTagOutcome {
  const re = /<relay>([\s\S]*?)<\/relay>/g;
  let last: string | undefined;
  for (let m = re.exec(stdout); m !== null; m = re.exec(stdout)) last = m[1];
  if (last === undefined) {
    return { kind: "malformed", reason: "worker emitted no <relay> tag" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { kind: "malformed", reason: "relay tag was not valid JSON" };
  }
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "malformed", reason: "relay tag was not a JSON object" };
  }
  const resource = resourceSignalSchema.safeParse(parsed);
  if (resource.success) {
    return {
      kind: "phase_complete",
      phase: resource.data.phase,
      state_summary: resource.data.state_summary,
      remaining: resource.data.remaining,
    };
  }
  const decisionGate = decisionGateSignalSchema.safeParse(parsed);
  if (decisionGate.success) {
    return {
      kind: "decision_gate",
      state_summary: decisionGate.data.state_summary,
      ...(decisionGate.data.remaining !== undefined
        ? { remaining: decisionGate.data.remaining }
        : {}),
    };
  }
  const blocked = blockedSchema.safeParse(parsed);
  if (blocked.success) {
    const b = blocked.data.blocked;
    return {
      kind: "blocked",
      reason: b.reason,
      state_summary: b.state_summary,
      ...(b.remaining !== undefined ? { remaining: b.remaining } : {}),
    };
  }
  const phase = phaseCompleteSchema.safeParse(parsed);
  if (phase.success) {
    return {
      kind: "phase_complete",
      phase: phase.data.phase_complete,
      state_summary: phase.data.state_summary,
      remaining: phase.data.remaining,
    };
  }
  return {
    kind: "malformed",
    reason: "relay tag failed shape validation (fail-closed)",
  };
}

// ── failure-type boundary vs mechanical retry (#598/#661) ───────────────────

export type FailureClassKind =
  | "quota_wall"
  | "capacity"
  | "pool_dead"
  | "hang_with_live_pool"
  | "self_reported_blocked"
  | "process_failed"
  | "malformed"
  | "outcome_protocol_failure";

export type RetryOrRelayClass = "resource" | "mechanical_retry";

/**
 * Failure-type boundary: process-level → mechanical retry (may reset);
 * resource failure → relay (NEVER reset — preserves uncommitted drift).
 */
export function classifyFailureForRetryOrRelay(input: {
  readonly kind: FailureClassKind;
}): RetryOrRelayClass {
  switch (input.kind) {
    case "quota_wall":
    case "capacity":
    case "pool_dead":
    case "hang_with_live_pool":
    case "self_reported_blocked":
      return "resource";
    case "process_failed":
    case "malformed":
    case "outcome_protocol_failure":
      return "mechanical_retry";
  }
}

// ── ledger + parameter file ─────────────────────────────────────────────────

export const RELAY_FOCUS_FILENAME = ".relay-focus.md";

/** Keep runner-owned relay focus out of worker commits, like ship focus/snapshots. */
function excludeRelayFocusFromGit(worktreePath: string): void {
  try {
    const excludePath = execFileSync(
      "git",
      ["-C", worktreePath, "rev-parse", "--git-path", "info/exclude"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
    ).trim();
    if (excludePath.length === 0) return;
    const absolutePath = resolve(worktreePath, excludePath);
    mkdirSync(join(absolutePath, ".."), { recursive: true });
    const existing = existsSync(absolutePath)
      ? readFileSync(absolutePath, "utf8")
      : "";
    if (!existing.split(/\r?\n/).includes(RELAY_FOCUS_FILENAME)) {
      appendFileSync(
        absolutePath,
        `${existing.endsWith("\n") || existing.length === 0 ? "" : "\n"}${RELAY_FOCUS_FILENAME}\n`,
      );
    }
  } catch {
    // Non-git fixtures still receive the focus file; real worktrees get excluded.
  }
}

export type RelayHandoffTrigger =
  | "quota_wall"
  | "capacity"
  | "hang_with_live_pool"
  | "self_reported_blocked"
  | "phase_complete"
  | "pool_dead"
  | "mechanical_retry_exhausted";

/**
 * Append-only ledger row when a baton hands off (#686).
 * `state_summary` is the load-bearing field forwarded to the next baton.
 */
export interface RelayHandoffLedgerEvent {
  readonly event: "relay_baton_handoff";
  readonly trigger: RelayHandoffTrigger;
  readonly state_summary: string;
  readonly remaining?: string;
  readonly reason?: string;
  readonly fromModelId: string;
  readonly fromPool: BillingPoolId;
  readonly toModelId: string;
  readonly toPool: BillingPoolId;
  readonly step?: StepId;
  readonly ts: string;
}

export function buildRelayHandoffLedgerEntry(input: {
  readonly trigger: RelayHandoffTrigger;
  readonly state_summary: string;
  readonly remaining?: string;
  readonly reason?: string;
  readonly fromModelId: string;
  readonly fromPool: BillingPoolId;
  readonly toModelId: string;
  readonly toPool: BillingPoolId;
  readonly step?: StepId;
  readonly now: Date;
}): RelayHandoffLedgerEvent {
  return {
    event: "relay_baton_handoff",
    trigger: input.trigger,
    state_summary: input.state_summary,
    ...(input.remaining !== undefined ? { remaining: input.remaining } : {}),
    ...(input.reason !== undefined ? { reason: input.reason } : {}),
    fromModelId: input.fromModelId,
    fromPool: input.fromPool,
    toModelId: input.toModelId,
    toPool: input.toPool,
    ...(input.step !== undefined ? { step: input.step } : {}),
    ts: input.now.toISOString(),
  };
}

/**
 * Write the next baton's parameter file (thin: state_summary + remaining +
 * baton identity). Runner mechanically forwards — no method in the prompt.
 */
function relayFocusBody(
  entry: RelayHandoffLedgerEvent,
): string {
  const lines = [
    `# Relay baton handoff`,
    ``,
    `- trigger: ${entry.trigger}`,
    `- from: ${entry.fromModelId} @ ${entry.fromPool}`,
    `- to: ${entry.toModelId} @ ${entry.toPool}`,
    `- ts: ${entry.ts}`,
    ``,
    `## state_summary`,
    ``,
    entry.state_summary,
    ``,
  ];
  if (entry.remaining !== undefined && entry.remaining.length > 0) {
    lines.push(`## remaining`, ``, entry.remaining, ``);
  }
  if (entry.reason !== undefined && entry.reason.length > 0) {
    lines.push(`## reason`, ``, entry.reason, ``);
  }
  return lines.join("\n");
}

/**
 * Stage a relay brief beside the durable filename. Call {@link commit} only
 * after its matching ledger row has been persisted; {@link discard} leaves the
 * previously durable baton untouched when that persistence fails.
 */
export function stageRelayFocusFile(
  worktreePath: string,
  entry: RelayHandoffLedgerEvent,
): {
  readonly path: string;
  commit(): void;
  discard(): void;
} {
  excludeRelayFocusFromGit(worktreePath);
  const path = join(worktreePath, RELAY_FOCUS_FILENAME);
  const stagedPath = join(
    worktreePath,
    `.${RELAY_FOCUS_FILENAME}.${randomUUID()}.staged`,
  );
  writeFileSync(stagedPath, relayFocusBody(entry), "utf8");
  return {
    path,
    commit: () => renameSync(stagedPath, path),
    discard: () => {
      try {
        unlinkSync(stagedPath);
      } catch {
        // Nothing to do when staging failed before creating the temp file.
      }
    },
  };
}

/** Write a focus file immediately for isolated callers and test setup. */
export function buildRelayFocusFile(
  worktreePath: string,
  entry: RelayHandoffLedgerEvent,
): string {
  const staged = stageRelayFocusFile(worktreePath, entry);
  staged.commit();
  return staged.path;
}

/**
 * Fail-closed focus write: returns the path on success, or `{ ok:false }` when
 * the worktree is missing / write throws. Callers must park (not relay) on failure.
 */
export function tryBuildRelayFocusFile(
  worktreePath: string | undefined,
  entry: RelayHandoffLedgerEvent,
): { readonly ok: true; readonly path: string } | { readonly ok: false; readonly reason: string } {
  if (worktreePath === undefined || worktreePath.trim().length === 0) {
    return {
      ok: false,
      reason: "relay handoff requires a worktree to write .relay-focus.md",
    };
  }
  try {
    return { ok: true, path: buildRelayFocusFile(worktreePath, entry) };
  } catch (err) {
    return {
      ok: false,
      reason: `relay focus write failed: ${
        err instanceof Error ? err.message : String(err)
      }`,
    };
  }
}

/** Stage, but do not promote, a relay brief for a pending durable ledger row. */
export function tryStageRelayFocusFile(
  worktreePath: string | undefined,
  entry: RelayHandoffLedgerEvent,
):
  | { readonly ok: true; readonly focus: ReturnType<typeof stageRelayFocusFile> }
  | { readonly ok: false; readonly reason: string } {
  if (worktreePath === undefined || worktreePath.trim().length === 0) {
    return {
      ok: false,
      reason: "relay handoff requires a worktree to stage .relay-focus.md",
    };
  }
  try {
    return { ok: true, focus: stageRelayFocusFile(worktreePath, entry) };
  } catch (err) {
    return {
      ok: false,
      reason: `relay focus staging failed: ${
        err instanceof Error ? err.message : String(err)
      }`,
    };
  }
}

/** Count relay_baton_handoff rows in an append-only ledger (chain length). */
export function countRelayHandoffsInLedger(
  ledger: ReadonlyArray<{ readonly event?: string }>,
): number {
  return ledger.reduce(
    (n, e) => (e.event === "relay_baton_handoff" ? n + 1 : n),
    0,
  );
}

export const MAX_RELAY_HANDOFFS = 8;

export function canRelayHandoff(
  ledger: ReadonlyArray<{ readonly event?: string }>,
  max = MAX_RELAY_HANDOFFS,
): boolean {
  return countRelayHandoffsInLedger(ledger) < max;
}

/**
 * #686 — hang-with-live-pool resource failure. Thrown AFTER the monitor kills
 * the pid tree so the runner can relay (never mechanical-retry / never reset).
 */
export class HangWithLivePoolError extends Error {
  readonly workerPid: number;
  readonly poolId: string;
  readonly step?: StepId;

  constructor(input: {
    readonly workerPid: number;
    readonly poolId: string;
    readonly step?: StepId;
  }) {
    super(
      `hang with live pool (pid=${input.workerPid}, pool=${input.poolId})` +
        (input.step !== undefined ? ` on ${input.step}` : ""),
    );
    this.name = "HangWithLivePoolError";
    this.workerPid = input.workerPid;
    this.poolId = input.poolId;
    if (input.step !== undefined) this.step = input.step;
  }
}

/** #787 checkpoint-local service congestion; relay without quota parking. */
export class CapacityRelayError extends Error {
  readonly capacity = true;

  constructor(message: string) {
    super(message);
    this.name = "CapacityRelayError";
  }
}

/**
 * Capacity is deliberately narrower than generic 5xx failure and never absorbs
 * a quota 429. This is the provider's model-specific CLI fingerprint, not the
 * broader telemetry taxonomy (which is intentionally descriptive).
 */
export function isCapacityRelayError(err: unknown): err is CapacityRelayError {
  if (err instanceof CapacityRelayError) return true;
  const message = err instanceof Error ? err.message : String(err);
  const lower = message.toLowerCase();
  if (/\b(?:http\s*(?:status|code)?\s*)?429\b/.test(lower)) return false;
  return lower.includes("selected model is at capacity");
}

export function capacityRelayErrorFrom(err: unknown): CapacityRelayError | undefined {
  if (!isCapacityRelayError(err)) return undefined;
  return new CapacityRelayError(err instanceof Error ? err.message : String(err));
}

export function isHangWithLivePoolError(
  err: unknown,
): err is HangWithLivePoolError {
  return (
    err instanceof HangWithLivePoolError ||
    (typeof err === "object" &&
      err !== null &&
      (err as { readonly name?: unknown }).name === "HangWithLivePoolError")
  );
}

/**
 * #686 — worker self-reported actionable `<relay>` terminal. Resource signals
 * preserve drift and hand off; decision gates park for a human ruling.
 */
export class SelfReportedRelayError extends Error {
  readonly tag: Extract<
    RelayTagOutcome,
    { kind: "blocked" } | { kind: "phase_complete" } | { kind: "decision_gate" }
  >;
  readonly step?: StepId;

  constructor(
    tag: Extract<
      RelayTagOutcome,
      { kind: "blocked" } | { kind: "phase_complete" } | { kind: "decision_gate" }
    >,
    step?: StepId,
  ) {
    const label =
      tag.kind === "blocked"
        ? `self-reported blocked: ${tag.reason}`
        : tag.kind === "phase_complete"
          ? `phase_complete:${tag.phase}`
          : `decision_gate:${tag.state_summary}`;
    super(label);
    this.name = "SelfReportedRelayError";
    this.tag = tag;
    if (step !== undefined) this.step = step;
  }
}

export function isSelfReportedRelayError(
  err: unknown,
): err is SelfReportedRelayError {
  return (
    err instanceof SelfReportedRelayError ||
    (typeof err === "object" &&
      err !== null &&
      (err as { readonly name?: unknown }).name === "SelfReportedRelayError")
  );
}

/**
 * Inspect worker stdout / log for a voluntary or blocked `<relay>` tag.
 * Returns undefined when no actionable tag is present (malformed / absent).
 */
export function tryParseActionableRelayTag(
  stdout: string,
):
  | Extract<
      RelayTagOutcome,
      { kind: "blocked" } | { kind: "phase_complete" } | { kind: "decision_gate" }
    >
  | undefined {
  const parsed = parseRelayTag(stdout);
  if (
    parsed.kind === "blocked" ||
    parsed.kind === "phase_complete" ||
    parsed.kind === "decision_gate"
  ) {
    return parsed;
  }
  return undefined;
}

/**
 * Resume only a baton for the exact executable slot being re-entered. A later
 * execution of that slot consumes/supersedes its earlier relay marker.
 */
export function resumeRelayFromLedger(
  ledger: ReadonlyArray<{ readonly event?: string; readonly step?: StepId }>,
  resumeStep: StepId,
): RelayHandoffLedgerEvent | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const row = ledger[i]!;
    if (row.step !== resumeStep) continue;
    if (row.event === "relay_baton_handoff") return row as RelayHandoffLedgerEvent;
    if (row.event === undefined) return undefined;
  }
  return undefined;
}

// ── handoff composition ─────────────────────────────────────────────────────

export type RelayDispositionResult =
  | {
      readonly kind: "park";
      readonly preserveWorktree: true;
      readonly reason: string;
      readonly resetAt?: Date;
    }
  | {
      readonly kind: "park_fallback";
      readonly preserveWorktree: true;
      readonly reason: string;
      readonly resetAt?: Date;
    }
  | {
      readonly kind: "relay";
      readonly preserveWorktree: true;
      readonly trigger: RelayHandoffTrigger;
      readonly nextBaton: NextRelayBaton;
      readonly reason: string;
      readonly ledgerEntry?: RelayHandoffLedgerEvent;
    }
  | {
      readonly kind: "hang";
      readonly preserveWorktree: false;
      readonly reason: string;
    };

export interface DecideRelayAfterIdleInput {
  /** Probe outcome kind from #683 (`ok` | `quota_limited` | `error`). */
  readonly probeKind: "ok" | "quota_limited" | "error";
  readonly resetAt?: Date;
  readonly now: Date;
  readonly parkThresholdMs: number;
  readonly currentModelId: string;
  readonly currentPool: BillingPoolId;
  readonly rosterOrder: ReadonlyArray<CoderRosterEntry>;
  readonly pools: ReadonlyArray<BillingPoolEntry>;
  readonly reviewerSlugs?: ReadonlyArray<string>;
  readonly reviewerSlugsForCandidate?: (
    candidate: CoderRosterEntry,
  ) => ReadonlyArray<string>;
  readonly workerPid: number;
  readonly killPidTree: (pid: number) => void | Promise<void>;
  readonly state_summary?: string;
  readonly remaining?: string;
  readonly step?: StepId;
}

/**
 * Pure integration entry at the #683 `wait_for_reset` disposition point
 * (ADR 0125). This is the runner seam — {@link parkOrRelayQuotaWall} / hang
 * helpers compose on top. Returns park / park_fallback / relay (+ baton +
 * ledger row when relaying).
 */
export function forkQuotaWallAt683Point(input: {
  readonly disposition: Extract<IdleDisposition, { kind: "wait_for_reset" }>;
  readonly now: Date;
  readonly parkThresholdMs: number;
  readonly currentModelId: string;
  readonly currentPool: BillingPoolId;
  readonly rosterOrder: ReadonlyArray<CoderRosterEntry>;
  readonly pools: ReadonlyArray<BillingPoolEntry>;
  readonly reviewerSlugs?: ReadonlyArray<string>;
  readonly reviewerSlugsForCandidate?: (
    candidate: CoderRosterEntry,
  ) => ReadonlyArray<string>;
  readonly state_summary?: string;
  readonly remaining?: string;
  readonly step?: StepId;
}): {
  readonly tier: ParkOrRelayDecision;
  readonly nextBaton?: NextRelayBaton;
  readonly ledgerEntry?: RelayHandoffLedgerEvent;
} {
  const batonInput = {
    currentModelId: input.currentModelId,
    currentPool: input.currentPool,
    rosterOrder: input.rosterOrder,
    pools: input.pools,
    reviewerSlugs: input.reviewerSlugs,
    reviewerSlugsForCandidate: input.reviewerSlugsForCandidate,
  };
  const live = hasLiveRelayBaton(batonInput);
  const tier = decideParkOrRelay({
    now: input.now,
    resetAt: input.disposition.resetAt,
    parkThresholdMs: input.parkThresholdMs,
    hasLiveBaton: live,
  });
  if (tier !== "relay") {
    return { tier };
  }
  const nextBaton = selectNextRelayBaton(batonInput);
  if (nextBaton === undefined) {
    return { tier: "park_fallback" };
  }
  return {
    tier: "relay",
    nextBaton,
    ledgerEntry: buildRelayHandoffLedgerEntry({
      trigger: "quota_wall",
      state_summary:
        input.state_summary ??
        "quota wall interrupt; uncommitted drift preserved",
      remaining: input.remaining,
      fromModelId: input.currentModelId,
      fromPool: input.currentPool,
      toModelId: nextBaton.modelId,
      toPool: nextBaton.pool,
      step: input.step,
      now: input.now,
    }),
  };
}

/**
 * Idle-probe composition over {@link forkQuotaWallAt683Point} (quota path) plus
 * hang-with-live-pool / probe-error kill paths. Thin delegate for non-runner
 * callers; the runner wires {@link forkQuotaWallAt683Point} directly at the
 * #683 park sites.
 */
export async function decideRelayAfterIdle(
  input: DecideRelayAfterIdleInput,
): Promise<RelayDispositionResult> {
  const batonInput = {
    currentModelId: input.currentModelId,
    currentPool: input.currentPool,
    rosterOrder: input.rosterOrder,
    pools: input.pools,
    reviewerSlugs: input.reviewerSlugs,
    reviewerSlugsForCandidate: input.reviewerSlugsForCandidate,
  };

  if (input.probeKind === "quota_limited") {
    // Disposition pool is the #683 probe id; fork only reads resetAt here.
    const forked = forkQuotaWallAt683Point({
      disposition: {
        kind: "wait_for_reset",
        pool: "unknown",
        ...(input.resetAt !== undefined ? { resetAt: input.resetAt } : {}),
        reason: "quota limited",
      },
      now: input.now,
      parkThresholdMs: input.parkThresholdMs,
      currentModelId: input.currentModelId,
      currentPool: input.currentPool,
      rosterOrder: input.rosterOrder,
      pools: input.pools,
      reviewerSlugs: input.reviewerSlugs,
      reviewerSlugsForCandidate: input.reviewerSlugsForCandidate,
      state_summary: input.state_summary,
      remaining: input.remaining,
      step: input.step,
    });
    if (forked.tier === "park") {
      return {
        kind: "park",
        preserveWorktree: true,
        reason: "same-pool reset within T; park original baton",
        ...(input.resetAt !== undefined ? { resetAt: input.resetAt } : {}),
      };
    }
    if (forked.tier === "park_fallback") {
      return {
        kind: "park_fallback",
        preserveWorktree: true,
        reason: "no live baton; park fallback",
        ...(input.resetAt !== undefined ? { resetAt: input.resetAt } : {}),
      };
    }
    // relay — do NOT kill (429 path preserves #683 park semantics).
    return {
      kind: "relay",
      preserveWorktree: true,
      trigger: "quota_wall",
      nextBaton: forked.nextBaton!,
      reason: "quota wall beyond T with live baton; relay",
      ledgerEntry: forked.ledgerEntry,
    };
  }

  if (input.probeKind === "ok") {
    // Hang with live pool → kill THIS pid tree, then relay (not same-role retry).
    await input.killPidTree(input.workerPid);
    const next = selectNextRelayBaton(batonInput);
    if (next === undefined) {
      return {
        kind: "hang",
        preserveWorktree: false,
        reason: "hang; no live baton to relay to",
      };
    }
    const ledgerEntry = buildRelayHandoffLedgerEntry({
      trigger: "hang_with_live_pool",
      state_summary:
        input.state_summary ??
        "worker hang with live pool; pid tree killed; drift preserved",
      remaining: input.remaining,
      fromModelId: input.currentModelId,
      fromPool: input.currentPool,
      toModelId: next.modelId,
      toPool: next.pool,
      step: input.step,
      now: input.now,
    });
    return {
      kind: "relay",
      preserveWorktree: true,
      trigger: "hang_with_live_pool",
      nextBaton: next,
      reason: "hang with live pool; killed pid tree and relay",
      ledgerEntry,
    };
  }

  // probe error → fail-safe hang (same as #683); no relay guess on unknown pool.
  await input.killPidTree(input.workerPid);
  return {
    kind: "hang",
    preserveWorktree: false,
    reason: "idle probe error; fail-safe hang",
  };
}

/** True when a mechanical-retry exhaustion reason is a relay candidate (#686). */
export function isRelayCandidateExhaustion(
  reason: string | undefined,
): boolean {
  return typeof reason === "string" && /relay candidate/i.test(reason);
}

export interface ApplyResourceFailureHandoffInput {
  readonly trigger: RelayHandoffTrigger;
  readonly state_summary: string;
  readonly remaining?: string;
  readonly reason?: string;
  readonly currentModelId: string;
  readonly currentPool: BillingPoolId;
  readonly rosterOrder: ReadonlyArray<CoderRosterEntry>;
  readonly pools: ReadonlyArray<BillingPoolEntry>;
  readonly reviewerSlugs?: ReadonlyArray<string>;
  readonly reviewerSlugsForCandidate?: (
    candidate: CoderRosterEntry,
  ) => ReadonlyArray<string>;
  readonly resetBeforeRetry?: () => void | Promise<void>;
  readonly now: Date;
  readonly step?: StepId;
}

/**
 * Resource-failure handoff. Intentionally never calls `resetBeforeRetry` —
 * that seam belongs exclusively to mechanical retry (#598/#661).
 */
export async function applyResourceFailureHandoff(
  input: ApplyResourceFailureHandoffInput,
): Promise<RelayDispositionResult> {
  // Deliberate: do NOT await/call input.resetBeforeRetry.
  void input.resetBeforeRetry;

  const batonInput = {
    currentModelId: input.currentModelId,
    currentPool: input.currentPool,
    rosterOrder: input.rosterOrder,
    pools: input.pools,
    reviewerSlugs: input.reviewerSlugs,
    reviewerSlugsForCandidate: input.reviewerSlugsForCandidate,
  };
  const next =
    input.trigger === "capacity"
      ? selectCapacityRelayBaton(batonInput)
      : selectNextRelayBaton(batonInput);
  if (next === undefined) {
    return {
      kind: "park_fallback",
      preserveWorktree: true,
      reason: "resource failure but no live baton; park fallback",
    };
  }
  const ledgerEntry = buildRelayHandoffLedgerEntry({
    trigger: input.trigger,
    state_summary: input.state_summary,
    remaining: input.remaining,
    reason: input.reason,
    fromModelId: input.currentModelId,
    fromPool: input.currentPool,
    toModelId: next.modelId,
    toPool: next.pool,
    step: input.step,
    now: input.now,
  });
  return {
    kind: "relay",
    preserveWorktree: true,
    trigger: input.trigger,
    nextBaton: next,
    reason: input.reason ?? `resource failure → relay (${input.trigger})`,
    ledgerEntry,
  };
}

/**
 * Relay chain ends at the normal review gate. A closing baton's normal
 * terminal (no relay tag) is required — self-reported phase_complete / clear
 * is NOT a review-gate exemption (#596 empiric).
 */
export function isRelayChainReadyForReviewGate(input: {
  readonly closingBatonCompleted: boolean;
  readonly emittedRelayTag: boolean;
  readonly lastRelayPhase?: "build" | "clear";
}): boolean {
  return input.closingBatonCompleted === true && input.emittedRelayTag === false;
}
