/**
 * #1145 Action-owned durable receipts + collection progress.
 *
 * Runner/stage never interprets these rows for fate. Collector/Verify Actions
 * own recovery: pristine start, in-progress resume, corrupt escalate.
 * Mutating GH ops: attempted → query external fact → succeeded | escalate
 * (never blind-replay attempted).
 */

import type { FamilyBackend, FamilyLedgerEntry } from "./types.js";

// ─── Side-effect receipts (mutating GH ops) ───────────────────────────

export type OnlineReviewSideEffectSeat = "collector" | "verify";
export type OnlineReviewSideEffectOp =
  | "retrigger"
  | "reply"
  | "resolve"
  | "defer";
export type OnlineReviewSideEffectState =
  | "attempted"
  | "succeeded"
  | "failed";

export type ExternalSideEffectFact = "applied" | "not_applied" | "unknown";

export interface OnlineReviewSideEffectReceipt {
  readonly seat: OnlineReviewSideEffectSeat;
  readonly round: number;
  readonly op: OnlineReviewSideEffectOp;
  readonly idempotencyKey: string;
  readonly externalHandle?: string;
  readonly state: OnlineReviewSideEffectState;
  readonly ts: string;
}

export type SideEffectRecoveryDecision =
  | { readonly action: "skip_already_done" }
  | { readonly action: "execute_once" }
  | {
      readonly action: "escalate";
      readonly reason: string;
      readonly diagnosis: string;
    };

/**
 * attempted recovery: always query external fact first; never bare-retry.
 * succeeded → skip. No receipt → first execute. Unknown fact → escalate.
 */
export function decideSideEffectRecovery(
  receipt: OnlineReviewSideEffectReceipt | undefined,
  externalFact: ExternalSideEffectFact,
): SideEffectRecoveryDecision {
  if (receipt?.state === "succeeded") {
    return { action: "skip_already_done" };
  }
  if (receipt === undefined || receipt.state === "failed") {
    if (externalFact === "applied") {
      return { action: "skip_already_done" };
    }
    if (externalFact === "unknown") {
      return {
        action: "escalate",
        reason: "side_effect_fact_unknown",
        diagnosis:
          "no durable succeeded receipt and platform cannot determine whether the mutating op already applied — refuse blind replay",
      };
    }
    return { action: "execute_once" };
  }
  // state === "attempted"
  if (externalFact === "applied") {
    return { action: "skip_already_done" };
  }
  if (externalFact === "not_applied") {
    return { action: "execute_once" };
  }
  return {
    action: "escalate",
    reason: "side_effect_attempted_unresolvable",
    diagnosis: `idempotencyKey=${receipt.idempotencyKey} is attempted without a determinable external fact; externalHandle=${receipt.externalHandle ?? "(none)"} — refuse blind replay`,
  };
}

/**
 * Run one mutating op with durable attempted→call→succeeded order.
 * `mutate` is invoked at most once per call when decision is execute_once.
 * On skip_already_done after attempted, backfills succeeded without mutate.
 */
export async function executeIdempotentSideEffect(input: {
  readonly receipt: OnlineReviewSideEffectReceipt | undefined;
  readonly queryExternal: () =>
    | ExternalSideEffectFact
    | Promise<ExternalSideEffectFact>;
  readonly mutate: () =>
    | { readonly externalHandle?: string }
    | Promise<{ readonly externalHandle?: string }>;
  readonly saveReceipt: (
    receipt: OnlineReviewSideEffectReceipt,
  ) => void | Promise<void>;
  readonly base: Omit<OnlineReviewSideEffectReceipt, "state" | "ts">;
  readonly now?: () => string;
}): Promise<
  | { readonly ok: true; readonly skipped: boolean }
  | {
      readonly ok: false;
      readonly reason: string;
      readonly diagnosis: string;
    }
> {
  const now = input.now ?? (() => new Date().toISOString());
  const externalFact = await input.queryExternal();
  const decision = decideSideEffectRecovery(input.receipt, externalFact);

  if (decision.action === "escalate") {
    return {
      ok: false,
      reason: decision.reason,
      diagnosis: decision.diagnosis,
    };
  }

  if (decision.action === "skip_already_done") {
    if (input.receipt?.state !== "succeeded") {
      await input.saveReceipt({
        ...input.base,
        ...(input.receipt?.externalHandle !== undefined
          ? { externalHandle: input.receipt.externalHandle }
          : input.base.externalHandle !== undefined
            ? { externalHandle: input.base.externalHandle }
            : {}),
        state: "succeeded",
        ts: now(),
      });
    }
    return { ok: true, skipped: true };
  }

  // execute_once — durable attempted BEFORE mutate
  const attempted: OnlineReviewSideEffectReceipt = {
    ...input.base,
    state: "attempted",
    ts: now(),
  };
  await input.saveReceipt(attempted);

  try {
    const result = await input.mutate();
    await input.saveReceipt({
      ...input.base,
      ...(result.externalHandle !== undefined
        ? { externalHandle: result.externalHandle }
        : attempted.externalHandle !== undefined
          ? { externalHandle: attempted.externalHandle }
          : {}),
      state: "succeeded",
      ts: now(),
    });
    return { ok: true, skipped: false };
  } catch (err) {
    await input.saveReceipt({
      ...attempted,
      state: "failed",
      ts: now(),
    });
    throw err;
  }
}

export function lastSideEffectReceiptFromFamilyLedger(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  idempotencyKey: string,
): OnlineReviewSideEffectReceipt | undefined {
  const key = idempotencyKey.trim();
  if (key.length === 0) return undefined;
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status !== "online_review_side_effect_receipt" ||
      entry.event !== "online_review_side_effect_receipt"
    ) {
      continue;
    }
    const receipt = receiptFromLedgerEntry(entry);
    if (receipt !== undefined && receipt.idempotencyKey === key) {
      return receipt;
    }
  }
  return undefined;
}

export function sideEffectReceiptsForRound(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  round: number,
): ReadonlyArray<OnlineReviewSideEffectReceipt> {
  if (!Number.isSafeInteger(round) || round < 1) return [];
  const latestByKey = new Map<string, OnlineReviewSideEffectReceipt>();
  for (const entry of entries) {
    if (
      entry.status !== "online_review_side_effect_receipt" ||
      entry.event !== "online_review_side_effect_receipt"
    ) {
      continue;
    }
    const receipt = receiptFromLedgerEntry(entry);
    if (receipt === undefined || receipt.round !== round) continue;
    latestByKey.set(receipt.idempotencyKey, receipt);
  }
  return [...latestByKey.values()];
}

function receiptFromLedgerEntry(
  entry: FamilyLedgerEntry,
): OnlineReviewSideEffectReceipt | undefined {
  const seat = entry.sideEffectSeat;
  const op = entry.sideEffectOp;
  const state = entry.sideEffectState;
  const key = entry.sideEffectIdempotencyKey;
  const round = entry.onlineReviewRound;
  if (
    (seat !== "collector" && seat !== "verify") ||
    (op !== "retrigger" &&
      op !== "reply" &&
      op !== "resolve" &&
      op !== "defer") ||
    (state !== "attempted" && state !== "succeeded" && state !== "failed") ||
    typeof key !== "string" ||
    key.trim().length === 0 ||
    typeof round !== "number" ||
    !Number.isSafeInteger(round) ||
    round < 1
  ) {
    return undefined;
  }
  return {
    seat,
    round,
    op,
    idempotencyKey: key.trim(),
    ...(typeof entry.sideEffectExternalHandle === "string" &&
    entry.sideEffectExternalHandle.trim().length > 0
      ? { externalHandle: entry.sideEffectExternalHandle.trim() }
      : {}),
    state,
    ts:
      typeof entry.ts === "string" && entry.ts.length > 0
        ? entry.ts
        : new Date(0).toISOString(),
  };
}

export async function recordOnlineReviewSideEffectReceipt(
  backend: FamilyBackend,
  receipt: OnlineReviewSideEffectReceipt,
  opts?: { readonly pr?: string },
): Promise<void> {
  if (!Number.isSafeInteger(receipt.round) || receipt.round < 1) {
    throw new Error(
      "family online_review_side_effect_receipt must include round >= 1",
    );
  }
  if (receipt.idempotencyKey.trim().length === 0) {
    throw new Error(
      "family online_review_side_effect_receipt must include idempotencyKey",
    );
  }
  await backend.appendFamilyLedger({
    status: "online_review_side_effect_receipt",
    event: "online_review_side_effect_receipt",
    phase: "final",
    onlineReviewRound: receipt.round,
    sideEffectSeat: receipt.seat,
    sideEffectOp: receipt.op,
    sideEffectIdempotencyKey: receipt.idempotencyKey.trim(),
    sideEffectState: receipt.state,
    ...(receipt.externalHandle !== undefined &&
    receipt.externalHandle.trim().length > 0
      ? { sideEffectExternalHandle: receipt.externalHandle.trim() }
      : {}),
    ...(opts?.pr !== undefined && opts.pr.trim().length > 0
      ? { pr: opts.pr.trim() }
      : {}),
    ts: receipt.ts,
  });
}

// ─── Collection progress (wait / evidence handle) ─────────────────────

export type CollectionProgressPhase =
  | "initialized"
  | "waiting"
  | "evidence_ready";

export interface OnlineReviewCollectionProgress {
  readonly round: number;
  readonly phase: CollectionProgressPhase;
  readonly waitDeadlineAt?: string;
  readonly completedWaitEpochs?: number;
  /** Opaque evidence handle (cargoPointer). No business fields. */
  readonly evidenceHandle?: string;
  readonly ts: string;
}

export type CollectionProgressClassification =
  | { readonly kind: "pristine" }
  | {
      readonly kind: "resume";
      readonly progress: OnlineReviewCollectionProgress;
    }
  | {
      readonly kind: "corrupt";
      readonly reason: string;
      readonly diagnosis: string;
    };

/**
 * Same-round trichotomy: pristine | resume | corrupt.
 * Old-round rows are ignored. Missing same-round row = pristine (never escalate).
 */
export function classifyCollectionProgress(input: {
  readonly round: number;
  readonly progress: OnlineReviewCollectionProgress | undefined;
  readonly sameRoundReceipts: ReadonlyArray<OnlineReviewSideEffectReceipt>;
  readonly evidenceHandleReadable?: (handle: string) => boolean;
}): CollectionProgressClassification {
  const round = input.round;
  if (!Number.isSafeInteger(round) || round < 1) {
    return {
      kind: "corrupt",
      reason: "invalid_round",
      diagnosis: `online review round must be >= 1, got ${String(round)}`,
    };
  }

  const hasReceipts = input.sameRoundReceipts.length > 0;
  const progress = input.progress;

  if (progress === undefined && !hasReceipts) {
    return { kind: "pristine" };
  }

  if (progress === undefined && hasReceipts) {
    return {
      kind: "corrupt",
      reason: "unpaired_receipts",
      diagnosis: `round ${round} has side-effect receipts but no collection-progress row — unpaired durable trace`,
    };
  }

  // progress defined
  const p = progress!;
  if (p.round !== round) {
    // Caller should only pass same-round progress; treat mismatch as pristine
    // for this round (old rows ignored).
    if (!hasReceipts) return { kind: "pristine" };
    return {
      kind: "corrupt",
      reason: "round_mismatch_with_receipts",
      diagnosis: `progress.round=${p.round} does not match requested round=${round} while same-round receipts exist`,
    };
  }

  if (
    p.phase !== "initialized" &&
    p.phase !== "waiting" &&
    p.phase !== "evidence_ready"
  ) {
    return {
      kind: "corrupt",
      reason: "invalid_progress_phase",
      diagnosis: `round ${round} progress has unusable phase`,
    };
  }

  if (p.evidenceHandle !== undefined) {
    const handle = p.evidenceHandle.trim();
    if (handle.length === 0) {
      return {
        kind: "corrupt",
        reason: "empty_evidence_handle",
        diagnosis: `round ${round} progress carries an empty evidenceHandle`,
      };
    }
    const readable = input.evidenceHandleReadable?.(handle) ?? true;
    if (!readable) {
      return {
        kind: "corrupt",
        reason: "evidence_handle_unreadable",
        diagnosis: `round ${round} evidenceHandle=${handle} is not readable (corrupt/truncated/missing blob)`,
      };
    }
  }

  // attempted receipts without externalHandle are not corrupt by themselves —
  // recovery path (decideSideEffectRecovery) escalates when fact is unknown.
  return { kind: "resume", progress: p };
}

/**
 * Remaining wait ms from durable deadline. 0 if overdue or absent.
 * Never re-opens a full window — caller must have persisted deadline first.
 */
export function remainingWaitMs(
  progress: OnlineReviewCollectionProgress,
  nowMs: number = Date.now(),
): number {
  if (
    progress.waitDeadlineAt === undefined ||
    progress.waitDeadlineAt.trim().length === 0
  ) {
    return 0;
  }
  const deadline = Date.parse(progress.waitDeadlineAt);
  if (!Number.isFinite(deadline)) return 0;
  return Math.max(0, deadline - nowMs);
}

export function lastCollectionProgressFromFamilyLedger(
  entries: ReadonlyArray<FamilyLedgerEntry>,
  round: number,
): OnlineReviewCollectionProgress | undefined {
  if (!Number.isSafeInteger(round) || round < 1) return undefined;
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i]!;
    if (
      entry.status !== "online_review_collection_progress" ||
      entry.event !== "online_review_collection_progress"
    ) {
      continue;
    }
    if (entry.onlineReviewRound !== round) continue;
    const parsed = progressFromLedgerEntry(entry);
    if (parsed !== undefined) return parsed;
  }
  return undefined;
}

function progressFromLedgerEntry(
  entry: FamilyLedgerEntry,
): OnlineReviewCollectionProgress | undefined {
  const round = entry.onlineReviewRound;
  const phase = entry.collectionProgressPhase;
  if (
    typeof round !== "number" ||
    !Number.isSafeInteger(round) ||
    round < 1 ||
    (phase !== "initialized" &&
      phase !== "waiting" &&
      phase !== "evidence_ready")
  ) {
    return undefined;
  }
  return {
    round,
    phase,
    ...(typeof entry.collectionWaitDeadlineAt === "string" &&
    entry.collectionWaitDeadlineAt.trim().length > 0
      ? { waitDeadlineAt: entry.collectionWaitDeadlineAt.trim() }
      : {}),
    ...(typeof entry.collectionCompletedWaitEpochs === "number" &&
    Number.isSafeInteger(entry.collectionCompletedWaitEpochs) &&
    entry.collectionCompletedWaitEpochs >= 0
      ? { completedWaitEpochs: entry.collectionCompletedWaitEpochs }
      : {}),
    ...(typeof entry.collectionEvidenceHandle === "string" &&
    entry.collectionEvidenceHandle.trim().length > 0
      ? { evidenceHandle: entry.collectionEvidenceHandle.trim() }
      : {}),
    ts:
      typeof entry.ts === "string" && entry.ts.length > 0
        ? entry.ts
        : new Date(0).toISOString(),
  };
}

export async function recordOnlineReviewCollectionProgress(
  backend: FamilyBackend,
  progress: OnlineReviewCollectionProgress,
  opts?: { readonly pr?: string },
): Promise<void> {
  if (!Number.isSafeInteger(progress.round) || progress.round < 1) {
    throw new Error(
      "family online_review_collection_progress must include round >= 1",
    );
  }
  await backend.appendFamilyLedger({
    status: "online_review_collection_progress",
    event: "online_review_collection_progress",
    phase: "final",
    onlineReviewRound: progress.round,
    collectionProgressPhase: progress.phase,
    ...(progress.waitDeadlineAt !== undefined
      ? { collectionWaitDeadlineAt: progress.waitDeadlineAt }
      : {}),
    ...(progress.completedWaitEpochs !== undefined
      ? { collectionCompletedWaitEpochs: progress.completedWaitEpochs }
      : {}),
    ...(progress.evidenceHandle !== undefined &&
    progress.evidenceHandle.trim().length > 0
      ? { collectionEvidenceHandle: progress.evidenceHandle.trim() }
      : {}),
    ...(opts?.pr !== undefined && opts.pr.trim().length > 0
      ? { pr: opts.pr.trim() }
      : {}),
    ts: progress.ts,
  });
}
