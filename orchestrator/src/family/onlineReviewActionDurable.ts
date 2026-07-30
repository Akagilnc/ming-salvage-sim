/**
 * #1145 worker-owned online-review durable capability (DecisionGate A).
 *
 * Sole store: `{workingRepo}/.orchestrator-online-review-durable/`
 * Host may only ensure dir + RW-mount + ship bin.mjs — never parse/classify.
 * Workers call bin.mjs (or this module in tests) for progress/receipts/blobs.
 */

import {
  closeSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { ensureGitInfoExclude } from "../gitInfoExclude.js";

// ─── Paths / env (sole names) ─────────────────────────────────────────

/** Host + sandbox relative directory name (sole durable store). */
export const ONLINE_REVIEW_DURABLE_DIR = ".orchestrator-online-review-durable";

/** Env pointing at the mounted durable root inside the sandbox. */
export const ONLINE_REVIEW_DURABLE_PATH_ENV =
  "ORCHESTRATOR_ONLINE_REVIEW_DURABLE_PATH";

/** Sandbox mount / env value (relative to worker workdir). */
export const ONLINE_REVIEW_DURABLE_SANDBOX_PATH = ONLINE_REVIEW_DURABLE_DIR;

const STATE_FILE = "state.jsonl";
const LOCK_FILE = "state.jsonl.lock";
const BLOBS_DIR = "blobs";
const BIN_NAME = "bin.mjs";

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
 * succeeded → skip. Unknown fact → escalate.
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
 * `mutate` is invoked at most once when decision is execute_once.
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

// ─── Collection progress ──────────────────────────────────────────────

export type CollectionProgressPhase =
  | "initialized"
  | "waiting"
  | "evidence_ready";

export interface OnlineReviewCollectionProgress {
  readonly round: number;
  readonly phase: CollectionProgressPhase;
  readonly waitDeadlineAt?: string;
  readonly completedWaitEpochs?: number;
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
 * Missing same-round row = pristine (never escalate).
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

  const p = progress!;
  if (p.round !== round) {
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

  return { kind: "resume", progress: p };
}

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

// ─── File store (worker + tests; host must not classify) ──────────────

type ProgressEvent = {
  readonly v: 1;
  readonly kind: "collection_progress";
  readonly round: number;
  readonly ts: string;
  readonly phase: CollectionProgressPhase;
  readonly waitDeadlineAt?: string;
  readonly completedWaitEpochs?: number;
  readonly evidenceHandle?: string;
};

type ReceiptEvent = {
  readonly v: 1;
  readonly kind: "side_effect_receipt";
  readonly round: number;
  readonly ts: string;
  readonly seat: OnlineReviewSideEffectSeat;
  readonly op: OnlineReviewSideEffectOp;
  readonly idempotencyKey: string;
  readonly state: OnlineReviewSideEffectState;
  readonly externalHandle?: string;
};

type DurableEvent = ProgressEvent | ReceiptEvent;

export interface OnlineReviewDurableStore {
  readonly root: string;
  appendProgress(progress: OnlineReviewCollectionProgress): void;
  appendReceipt(receipt: OnlineReviewSideEffectReceipt): void;
  lastProgress(round: number): OnlineReviewCollectionProgress | undefined;
  lastReceipt(
    round: number,
    idempotencyKey: string,
  ): OnlineReviewSideEffectReceipt | undefined;
  receiptsForRound(round: number): ReadonlyArray<OnlineReviewSideEffectReceipt>;
  classify(round: number): CollectionProgressClassification;
  putEvidence(round: number, body: string | Buffer): string;
  getEvidence(handle: string): Buffer;
  evidenceReadable(handle: string): boolean;
}

function nowIso(): string {
  return new Date().toISOString();
}

function withLock(root: string, fn: () => void): void {
  const lockPath = join(root, LOCK_FILE);
  const started = Date.now();
  let fd: number | undefined;
  while (fd === undefined) {
    try {
      fd = openSync(lockPath, "wx");
    } catch (err) {
      const code =
        err !== null && typeof err === "object" && "code" in err
          ? String((err as { code?: unknown }).code)
          : "";
      if (code !== "EEXIST") throw err;
      if (Date.now() - started > 5_000) {
        throw new Error(
          `online-review durable lock timeout on ${lockPath}`,
        );
      }
      // busy-wait briefly (no Atomics/SAB dependency in worker images)
      const until = Date.now() + 20;
      while (Date.now() < until) {
        /* spin */
      }
    }
  }
  try {
    fn();
  } finally {
    closeSync(fd);
    try {
      unlinkSync(lockPath);
    } catch {
      // best-effort unlock
    }
  }
}

function readEvents(root: string): DurableEvent[] {
  const path = join(root, STATE_FILE);
  if (!existsSync(path)) return [];
  const text = readFileSync(path, "utf8");
  const out: DurableEvent[] = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.length === 0) continue;
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (
        parsed !== null &&
        typeof parsed === "object" &&
        (parsed as { v?: unknown }).v === 1 &&
        typeof (parsed as { kind?: unknown }).kind === "string"
      ) {
        out.push(parsed as DurableEvent);
      }
    } catch {
      // skip corrupt lines
    }
  }
  return out;
}

function appendEvent(root: string, event: DurableEvent): void {
  withLock(root, () => {
    const path = join(root, STATE_FILE);
    writeFileSync(path, `${JSON.stringify(event)}\n`, {
      encoding: "utf8",
      flag: "a",
    });
  });
}

function progressFromEvent(
  e: ProgressEvent,
): OnlineReviewCollectionProgress {
  return {
    round: e.round,
    phase: e.phase,
    ...(e.waitDeadlineAt !== undefined
      ? { waitDeadlineAt: e.waitDeadlineAt }
      : {}),
    ...(e.completedWaitEpochs !== undefined
      ? { completedWaitEpochs: e.completedWaitEpochs }
      : {}),
    ...(e.evidenceHandle !== undefined
      ? { evidenceHandle: e.evidenceHandle }
      : {}),
    ts: e.ts,
  };
}

function receiptFromEvent(e: ReceiptEvent): OnlineReviewSideEffectReceipt {
  return {
    seat: e.seat,
    round: e.round,
    op: e.op,
    idempotencyKey: e.idempotencyKey,
    ...(e.externalHandle !== undefined
      ? { externalHandle: e.externalHandle }
      : {}),
    state: e.state,
    ts: e.ts,
  };
}

/** Open a durable store rooted at an existing directory. */
export function openOnlineReviewDurableStore(
  root: string,
): OnlineReviewDurableStore {
  mkdirSync(join(root, BLOBS_DIR), { recursive: true });

  const blobPath = (handle: string): string => {
    const normalized = handle.replace(/\\/g, "/");
    if (
      normalized.includes("..") ||
      !normalized.startsWith(`${BLOBS_DIR}/`)
    ) {
      throw new Error(`invalid evidence handle: ${handle}`);
    }
    return join(root, normalized);
  };

  const store: OnlineReviewDurableStore = {
    root,
    appendProgress(progress) {
      const event: ProgressEvent = {
        v: 1,
        kind: "collection_progress",
        round: progress.round,
        ts: progress.ts,
        phase: progress.phase,
        ...(progress.waitDeadlineAt !== undefined
          ? { waitDeadlineAt: progress.waitDeadlineAt }
          : {}),
        ...(progress.completedWaitEpochs !== undefined
          ? { completedWaitEpochs: progress.completedWaitEpochs }
          : {}),
        ...(progress.evidenceHandle !== undefined
          ? { evidenceHandle: progress.evidenceHandle }
          : {}),
      };
      appendEvent(root, event);
    },
    appendReceipt(receipt) {
      const event: ReceiptEvent = {
        v: 1,
        kind: "side_effect_receipt",
        round: receipt.round,
        ts: receipt.ts,
        seat: receipt.seat,
        op: receipt.op,
        idempotencyKey: receipt.idempotencyKey,
        state: receipt.state,
        ...(receipt.externalHandle !== undefined
          ? { externalHandle: receipt.externalHandle }
          : {}),
      };
      appendEvent(root, event);
    },
    lastProgress(round) {
      if (!Number.isSafeInteger(round) || round < 1) return undefined;
      const events = readEvents(root);
      for (let i = events.length - 1; i >= 0; i--) {
        const e = events[i]!;
        if (e.kind === "collection_progress" && e.round === round) {
          return progressFromEvent(e);
        }
      }
      return undefined;
    },
    lastReceipt(round, idempotencyKey) {
      const key = idempotencyKey.trim();
      if (!Number.isSafeInteger(round) || round < 1 || key.length === 0) {
        return undefined;
      }
      const events = readEvents(root);
      for (let i = events.length - 1; i >= 0; i--) {
        const e = events[i]!;
        if (
          e.kind === "side_effect_receipt" &&
          e.round === round &&
          e.idempotencyKey === key
        ) {
          return receiptFromEvent(e);
        }
      }
      return undefined;
    },
    receiptsForRound(round) {
      if (!Number.isSafeInteger(round) || round < 1) return [];
      const latest = new Map<string, OnlineReviewSideEffectReceipt>();
      for (const e of readEvents(root)) {
        if (e.kind !== "side_effect_receipt" || e.round !== round) continue;
        latest.set(e.idempotencyKey, receiptFromEvent(e));
      }
      return [...latest.values()];
    },
    classify(round) {
      return classifyCollectionProgress({
        round,
        progress: store.lastProgress(round),
        sameRoundReceipts: store.receiptsForRound(round),
        evidenceHandleReadable: (h) => store.evidenceReadable(h),
      });
    },
    putEvidence(round, body) {
      if (!Number.isSafeInteger(round) || round < 1) {
        throw new Error("evidence-put requires round >= 1");
      }
      const id = `r${round}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
      const handle = `${BLOBS_DIR}/${id}`;
      const dest = blobPath(handle);
      const tmp = `${dest}.tmp`;
      mkdirSync(dirname(dest), { recursive: true });
      writeFileSync(tmp, body);
      renameSync(tmp, dest);
      store.appendProgress({
        round,
        phase: "evidence_ready",
        evidenceHandle: handle,
        ts: nowIso(),
      });
      return handle;
    },
    getEvidence(handle) {
      const path = blobPath(handle);
      if (!existsSync(path)) {
        throw new Error(`evidence handle unreadable: ${handle}`);
      }
      return readFileSync(path);
    },
    evidenceReadable(handle) {
      try {
        return existsSync(blobPath(handle));
      } catch {
        return false;
      }
    },
  };
  return store;
}

function bundledBinSourcePath(): string {
  // Prefer scripts/ next to package root (src/family → ../../scripts).
  const here = dirname(fileURLToPath(import.meta.url));
  return join(here, "..", "..", "scripts", "online-review-durable-bin.mjs");
}

/**
 * Host-only: mkdir store, ship bin.mjs, git-exclude.
 * Must not read/parse state.jsonl.
 */
export function ensureOnlineReviewDurableDir(workingRepo: string): {
  readonly hostPath: string;
  readonly sandboxPath: string;
} {
  const hostPath = join(workingRepo, ONLINE_REVIEW_DURABLE_DIR);
  mkdirSync(join(hostPath, BLOBS_DIR), { recursive: true });
  const binSrc = bundledBinSourcePath();
  const binDest = join(hostPath, BIN_NAME);
  if (existsSync(binSrc)) {
    copyFileSync(binSrc, binDest);
  } else {
    // Fallback stub so mount always has a bin (tests may inject full script).
    writeFileSync(
      binDest,
      `#!/usr/bin/env node\nconsole.error("online-review durable bin missing source");\nprocess.exit(2);\n`,
      "utf8",
    );
  }
  ensureGitInfoExclude(workingRepo, ONLINE_REVIEW_DURABLE_DIR);
  ensureGitInfoExclude(workingRepo, `${ONLINE_REVIEW_DURABLE_DIR}/`);
  return {
    hostPath,
    sandboxPath: ONLINE_REVIEW_DURABLE_SANDBOX_PATH,
  };
}

/** Mount descriptor for familyReviewLoopSandboxConfig (RW). */
export function onlineReviewDurableMount(workingRepo: string): {
  readonly hostPath: string;
  readonly sandboxPath: string;
  readonly readonly?: boolean;
} {
  const ensured = ensureOnlineReviewDurableDir(workingRepo);
  return {
    hostPath: ensured.hostPath,
    sandboxPath: ensured.sandboxPath,
    // RW — workers append state / blobs
  };
}
