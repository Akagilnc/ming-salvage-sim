/**
 * runOrchestrator — the runner loop (ADR 0018, corrected by ADR 0030).
 *
 * The runner drives one family's fixed child-slice sequence: it performs each
 * runner-action step or dispatches each worker step, writes a step-ledger
 * entry, then calls route() to pick the next step. The agent never decides
 * the next step — route() does.
 *
 * ADR 0030: the child runner owns the visible per-slice review/fix loop:
 *
 *   S0(gate) → S1(context) → S2(implement) → S3(review) → S4(classify)
 *     clean/deferred only → S7(local handoff) → S8(handoff)
 *     blocking → S5(fix) → S6(fresh full-diff review) → S4(classify)
 *
 * S2/S5 are coder workers. S3/S6 are fresh read-only reviewer workers. S4 is a
 * runner-action classification boundary so findings and per-round outcomes are
 * visible in ledger state instead of hidden inside a coder session.
 *
 * Slice #249: persisted step ledger — every step is written via
 *   backend.writeLedger() to the sibling state dir (outside the worktree).
 * Slice #251: global escalate stop edge (in route()).
 * Slice #252: error edges —
 *   - any backend call throws → S8(error) + error package  [runner catch]
 *   - the S2 worker carries escalate → S8(escalate) [route() detects]
 * Slice #253: StepSpec contract — model/completionSignal/maxIter/soul/toolchain.
 * Slice #248: S0 input gate — three-way accept condition (rfa ∧ no sub-issues ∧
 *   blocked_by all closed); violations throw, stopping at S0. (Agent Brief was
 *   removed as a gate — design correction; the coder reads the whole issue.)
 * #331 (ADR 0026 / PRD #330), extended by ADR 0030: the runner dispatches every
 *   WORKER step (S2/S3/S5/S6 agent workers) through the single unified
 *   seam `dispatchWorker(backend, spec, ctx)` (dispatchWorker.ts) instead of
 *   reaching for `runStep` / `resumeSession` directly.
 */

import { mintRunId } from "./runId.js";
import { shWithClock } from "./externalCall.js";
import { hasAcceptedSuppressionAuthority } from "./acceptedSuppression.js";
import {
  reviewFixAssertionSignal,
  reviewFixDecisionGate,
} from "./reviewFixAssertionGate.js";
import { route } from "./route.js";
// The unified worker-dispatch seam (ADR 0026 / PRD #330 #331): the runner
// dispatches EVERY child worker step (S2/S3/S5/S6) through ONE free function
// instead of reaching for runStep/resumeSession directly.
import {
  dispatchWorkerWithMonitor,
  stepSpecToWorkerSpec,
  workerResultToStep,
} from "./dispatchWorker.js";
import { monitorHandleFromLedger } from "./workerMonitor.js";
import {
  scheduleCommitTelemetry,
} from "./telemetry.js";
import { routeSmokeFailure } from "./modelRoutes.js";
import { logDriverStage } from "./stageLog.js";
import {
  withMechanicalRetry,
  type MechanicalRetryOptions,
} from "./dispatchRetry.js";
import {
  isQuotaWaitForResetError,
  QuotaWaitForResetError,
  poolForModelRef,
} from "./quotaProbe.js";
import {
  parkOrRelayQuotaWall,
  parkQuotaWaitForReset,
} from "./quotaParkRelay.js";
import {
  applyCoderRecToRoute,
  applyRuntimeTightRoutePolicy,
  modelForSlot,
  printableRouteLineup,
  degradeOptionalRouteSmokeFailures,
  resolveActiveModelRoute,
  knownLiveBillingPoolsFromRoute,
  withCoderSlot,
  type ModelRouteEnv,
  type ResolvedModelRoute,
} from "./modelRoutes.js";
import {
  resolveCoderRecOrder,
  lookupCoderRosterEntry,
  completedS6RoundsFromLedger,
  CODER_REC_FALLBACK_AFTER_ROUNDS,
  type CoderRosterEntry,
} from "./coderRoster.js";
import {
  DEFAULT_PARK_THRESHOLD_MS,
  billingPoolForModelRef,
  billingPoolFromQuotaPool,
  findLiveBillingPoolForModel,
  resolveRelayPools as resolveRelayPoolsFromTable,
  type BillingPoolEntry,
  type BillingPoolId,
  type NextRelayBaton,
} from "./quotaPoolTable.js";
import {
  canRelayHandoff,
  isRelayCandidateExhaustion,
  applyResourceFailureHandoff,
  resumeRelayFromLedger,
  tryStageRelayFocusFile,
  isCapacityRelayError,
  isHangWithLivePoolError,
  isSelfReportedRelayError,
  RELAY_FOCUS_FILENAME,
  type RelayHandoffLedgerEvent,
} from "./relayDispatch.js";
import { existsSync } from "node:fs";
import { join } from "node:path";

// Shared seam guards — single source of truth, also used by route(), so the
// coder-output / commitsAdded rules can never drift.
import {
  escalateOf,
  isValidEscalation,
} from "./validate.js";
import {
  contractDriftStopSummary,
  decisionGateParkStopSummary,
  infraFailureStopSummary,
  successStopSummary,
  type AcceptedSuppressionSummary,
  type StopSummary,
} from "./stopSummary.js";
import {
  isStepId,
} from "./types.js";
import type {
  Backend,
  ContinueFixingEvent,
  ErrorPackage,
  Escalation,
  EscalationAnswerEvent,
  EscalationKind,
  Finding,
  FindingDisposition,
  FindingRepairScope,
  HandoffStatus,
  IssueMeta,
  IssueSnapshot,
  LedgerEntry,
  PersistentLedgerEntry,
  ResumeState,
  RunInput,
  RunResult,
  SliceStepId,
  StepId,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorktreeHandle,
} from "./types.js";

/** Map a wall step to the route slot a relay baton rewrites. */
function relaySlotForWallStep(
  wallStep: StepId,
): "coder" | "reviewer" | "coderFix" {
  if (wallStep === "S3" || wallStep === "S6") return "reviewer";
  if (wallStep === "S5") return "coderFix";
  return "coder";
}

/** Merge resume history with the display-seeded ledger without replaying shared rows. */
export function mergeResumeLedgerHistory(
  resumeHistoryLedger: ReadonlyArray<LedgerEntry>,
  ledger: ReadonlyArray<LedgerEntry>,
): ReadonlyArray<LedgerEntry> {
  return [...new Set([...resumeHistoryLedger, ...ledger])];
}

// ─── #256 seam-extension normalisation ───────────────────────────────────────
//
// #331 (ADR 0026): the runner-local `normalizeStepResult` was removed. The agent
// dispatch now goes through `dispatchWorker` (dispatchWorker.ts), which normalises
// the legacy `StepOutput | StepResult` return internally and hands back a
// discriminated WorkerResult (the runner unwraps `completed` → output + sessionId
// at the call site). One normalisation, no drift.

// ─── ledger helpers ────────────────────────────────────────────────────────

/**
 * Derive the sibling state directory from the worktree path.
 * Convention: `<worktree-parent>/.ledger-<issueNumber>/`
 * This guarantees the path is NOT under the worktree root, so `git clean -fd`
 * on the worktree cannot remove it.
 */
function deriveStateDir(worktreePath: string, issueNumber: number): string {
  // Trim any trailing path separators before computing the parent, so a path
  // like "/foo/bar/" does not regress to the worktree itself ("/foo/bar") as
  // parent — which would place `.ledger-N` INSIDE the worktree root and let
  // `git clean -fd` remove it (breaking the core invariant).
  const trimmed = worktreePath.replace(/[/\\]+$/, "");
  // Find the parent by stripping everything at and after the last separator.
  // Using a simple string split keeps this dependency-free (no `path` module).
  const lastSep = Math.max(
    trimmed.lastIndexOf("/"),
    trimmed.lastIndexOf("\\"),
  );
  const parent = lastSep >= 0 ? trimmed.slice(0, lastSep) : ".";
  return `${parent}/.ledger-${issueNumber}`;
}

/** SHA-256 hex of an arbitrary string, via Web Crypto (no @types/node dep). */
async function sha256Hex(input: string): Promise<string> {
  const encoded = new TextEncoder().encode(input);
  const buffer = await globalThis.crypto.subtle.digest("SHA-256", encoded);
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Stable SHA-256 hash for the ledger's `prompt_hash` field.
 *
 * #256 (DONE): for an agent step the runner asks the Backend to resolve the
 * promptFile to its raw CONTENT (`backend.readPromptContent`) and hashes the
 * CONTENT — the real anti-tampering audit. The hash is prefixed `content:` so a
 * content hash is never confused with the legacy name hash.
 *
 * Fallbacks (keep the v0.1 behaviour so the zero-container fake path is
 * unchanged): when there is no promptFile (runner-action step), no
 * `readPromptContent` on the Backend, or it returns `undefined` (prompt not
 * resolvable), hash the promptFile NAME (or the step id) prefixed `name:`.
 *
 * Uses the Web Crypto API (globalThis.crypto) available in Node ≥ 18 / ES2022,
 * so no `@types/node` dependency is needed.
 */
async function hashPrompt(
  promptFile: string | undefined,
  stepId: StepId,
  backend: Pick<Backend, "readPromptContent">,
): Promise<string> {
  if (promptFile !== undefined && backend.readPromptContent !== undefined) {
    let content: string | undefined;
    try {
      content = await backend.readPromptContent(promptFile);
    } catch {
      // A prompt-resolution fault must NOT abort ledgering — fall back to the
      // name hash so the step is still recorded (the resume truth survives).
      content = undefined;
    }
    if (content !== undefined) {
      return `content:${await sha256Hex(content)}`;
    }
  }
  // Fallback: hash the promptFile NAME (agent step) or the step id
  // (runner-action step), as in v0.1.
  return `name:${await sha256Hex(promptFile ?? stepId)}`;
}

/**
 * Build a PersistentLedgerEntry from the in-flight step context.
 *
 * #256 (DONE): the caller (`emitLedger`) now supplies the TRUE values it
 * receives from the seam extension / optional Backend helpers — `sessionId` is
 * the real per-step sandbox session id for agent steps (run-level UUID fallback
 * otherwise), `branchHEAD` the real `git rev-parse HEAD` SHA (branch-name
 * fallback otherwise), `prompt_hash` the content hash (name-hash fallback). This
 * builder just assembles the entry; value resolution lives in `emitLedger`.
 */
function buildPersistentEntry(opts: {
  step: SliceStepId;
  output: StepOutput | undefined;
  runId: string;
  sessionId: string;
  prompt_hash: string;
  branchHEAD: string;
  ts: string;
  /** Terminal status — set only for the S8 handoff entry (#255). */
  handoffStatus?: HandoffStatus;
  /** Escalation bucket — set only for S8(status=escalate), #439. */
  escalationKind?: EscalationKind;
  /** ADR0030 S4 classification state, persisted for resume replay. */
  findingDispositions?: ReadonlyArray<FindingDisposition>;
  /** Terminal stop reason summary (#450). */
  stopSummary?: StopSummary;
  /** External CLI worker monitor handle (#684). */
  monitorHandle?: import("./types.js").WorkerMonitorHandle;
}): PersistentLedgerEntry {
  let entry: PersistentLedgerEntry = {
    step: opts.step,
    runId: opts.runId,
    sessionId: opts.sessionId,
    prompt_hash: opts.prompt_hash,
    branchHEAD: opts.branchHEAD,
    ts: opts.ts,
  };
  // Only add output if defined — keeps the runner-action shape clean.
  if (opts.output !== undefined) {
    entry = { ...entry, output: opts.output };
  }
  // Tag the terminal S8 entry with its handoff status so a resuming run can
  // tell success / escalate / error apart (#255).
  if (opts.handoffStatus !== undefined) {
    entry = { ...entry, handoffStatus: opts.handoffStatus };
  }
  if (opts.escalationKind !== undefined) {
    entry = { ...entry, escalationKind: opts.escalationKind };
  }
  if (opts.findingDispositions !== undefined) {
    entry = { ...entry, findingDispositions: opts.findingDispositions };
  }
  if (opts.stopSummary !== undefined) {
    entry = { ...entry, stopSummary: opts.stopSummary };
  }
  if (opts.monitorHandle !== undefined) {
    entry = { ...entry, monitorHandle: opts.monitorHandle };
  }
  return entry;
}

/** Default child base for internal/test harnesses; family runs override it. */
const SLICE_BASE = "main";

// ─── #255 resume planning ──────────────────────────────────────────────────

/**
 * The recovery plan derived from a persisted ledger (#255).
 *
 * Crash-resume and escalate-resume share this ONE derivation: read the ledger
 * (the resume truth — NOT LLM memory), and decide where to continue.
 *
 *   - `terminalStatus` — set when the prior run already reached a terminal
 *                      handoff that is NOT being re-opened. Re-feeding is a
 *                      no-op; the runner returns this exact status (success /
 *                      error / escalate), NOT a hardcoded success. A prior
 *                      ERROR or ESCALATE that the human has not re-opened must
 *                      not masquerade as success.
 *   - `resumeStep`   — the step to continue from (only when terminalStatus is
 *                      undefined).
 *   - `resumeSessionId` — set when the step must be resumed in its ORIGINAL
 *                      agent session (Sandcastle `resumeSession`): the prior run
 *                      ESCALATED at this step and a human has since answered, so
 *                      the coder finishes in the same session rather than a
 *                      fresh `run()`. Undefined ⇒ continue with a fresh dispatch
 *                      (crash-resume: the next step is brand new work).
 *   - `lastOutput`   — the most recent agent-step output (drives `route()` for
 *                      the non-escalate resume case).
 *   - `priorLedger`  — the prior in-memory ledger entries to seed the run with,
 *                      so committed progress is preserved and not re-run.
 */
interface ResumePlan {
  readonly terminalStatus?: HandoffStatus;
  readonly resumeStep: SliceStepId;
  readonly resumeSessionId?: string;
  readonly escalationAnswer?: EscalationAnswerEvent;
  readonly continueFixingRepair?: ContinueFixingRepair;
  readonly lastOutput?: StepOutput;
  readonly priorLedger: ReadonlyArray<LedgerEntry>;
}

function isValidStepId(value: unknown): value is SliceStepId {
  return (
    value === "S0" ||
    value === "S1" ||
    value === "S2" ||
    value === "S3" ||
    value === "S4" ||
    value === "S5" ||
    value === "S6" ||
    value === "S7" ||
    value === "S8"
  );
}

function isEscalationAnswerEntry(
  entry: LedgerEntry,
): entry is LedgerEntry & EscalationAnswerEvent {
  const raw = entry as unknown as Record<string, unknown>;
  return (
    entry.event === "escalation_answered" &&
    entry.output == null &&
    raw.verdict == null &&
    isValidStepId(entry.forStep) &&
    typeof entry.answer === "string" &&
    entry.answer.trim().length > 0 &&
    (entry.note == null || typeof entry.note === "string") &&
    (entry.source == null || isBookkeepingSource(entry.source)) &&
    (entry.findingIdentityKey == null ||
      typeof entry.findingIdentityKey === "string") &&
    (entry.findingScope == null ||
      isFindingRepairScope(entry.findingScope))
  );
}

function answerPayload(
  entry: LedgerEntry & EscalationAnswerEvent,
): EscalationAnswerEvent {
  return {
    event: "escalation_answered",
    forStep: entry.forStep,
    answer: entry.answer,
    ...(entry.note != null ? { note: entry.note } : {}),
    source: entry.source ?? "human",
    ...(entry.findingIdentityKey != null
      ? { findingIdentityKey: entry.findingIdentityKey }
      : {}),
    ...(entry.findingScope != null
      ? { findingScope: entry.findingScope }
      : {}),
  };
}

function isBookkeepingEntry(entry: LedgerEntry): boolean {
  return entry.event != null;
}

/**
 * #683 — latest durable marker is a quota wait park. Resume re-enters the
 * parked step (not S8(error)). Same family as `online_review_ci_pending` parks.
 * #686 — a newer `relay_baton_handoff` also resumes the interrupted step so the
 * next baton can continue from the preserved worktree.
 */
function sliceQuotaWaitPending(
  ledger: ReadonlyArray<{
    readonly step?: string;
    readonly event?: string;
  }>,
): SliceStepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      entry.event === "quota_wait_for_reset" ||
      entry.event === "relay_baton_handoff"
    ) {
      const step = entry.step;
      if (
        step === "S2" ||
        step === "S3" ||
        step === "S5" ||
        step === "S6"
      ) {
        return step;
      }
      return "S2";
    }
    // Any newer executable agent/handoff progress clears the park.
    if (
      entry.event === undefined &&
      (entry.step === "S2" ||
        entry.step === "S3" ||
        entry.step === "S5" ||
        entry.step === "S6" ||
        entry.step === "S7")
    ) {
      return undefined;
    }
  }
  return undefined;
}

function executableLedgerEntries(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): ReadonlyArray<PersistentLedgerEntry> {
  return ledger.filter((entry) => !isBookkeepingEntry(entry));
}

function latestAnswerAfter(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
  index: number,
  forStep: StepId,
): EscalationAnswerEvent | undefined {
  for (let i = ledger.length - 1; i > index; i--) {
    const entry = ledger[i]!;
    if (
      isEscalationAnswerEntry(entry) &&
      entry.forStep === forStep &&
      isExecutableEscalationAnswerSource(entry.source)
    ) {
      return answerPayload(entry);
    }
  }
  return undefined;
}

function isBookkeepingSource(
  value: unknown,
): value is ContinueFixingEvent["source"] {
  return (
    value === "human" ||
    value === "coordinator" ||
    value === "peripheral" ||
    value === "resume_input"
  );
}

function isExecutableEscalationAnswerSource(
  value: unknown,
): value is
  | Extract<ContinueFixingEvent["source"], "human" | "resume_input"> {
  return value === undefined || value === "human" || value === "resume_input";
}

function isExecutableContinueFixingSource(
  value: unknown,
): value is
  | Extract<ContinueFixingEvent["source"], "human" | "resume_input"> {
  return value === "human" || value === "resume_input";
}

function isStringArray(value: unknown): value is ReadonlyArray<string> {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isFindingRepairScope(
  value: unknown,
): value is NonNullable<ContinueFixingEvent["findingScope"]> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const scope = value as Record<string, unknown>;
  return (
    (scope.identityKeys === undefined || isStringArray(scope.identityKeys)) &&
    (scope.locations === undefined || isStringArray(scope.locations)) &&
    (scope.categories === undefined || isStringArray(scope.categories)) &&
    (scope.findingGroup === undefined ||
      typeof scope.findingGroup === "string") &&
    (scope.reviewContext === undefined ||
      typeof scope.reviewContext === "string") &&
    (scope.featureArea === undefined || typeof scope.featureArea === "string")
  );
}

function isContinueFixingEntry(
  entry: LedgerEntry,
): entry is LedgerEntry & ContinueFixingEvent {
  const raw = entry as unknown as Record<string, unknown>;
  return (
    entry.event === "runner_bookkeeping" &&
    entry.output == null &&
    raw.verdict == null &&
    entry.intent === "continue_fixing" &&
    isExecutableContinueFixingSource(entry.source) &&
    typeof entry.ts === "string" &&
    entry.ts.trim().length > 0 &&
    (entry.reason == null || typeof entry.reason === "string") &&
    (entry.findingIdentityKey == null ||
      typeof entry.findingIdentityKey === "string") &&
    (entry.findingScope == null ||
      isFindingRepairScope(entry.findingScope))
  );
}

function answerMapsToContinueFixing(answer: EscalationAnswerEvent): boolean {
  const text = answer.answer.trim().toLowerCase();
  return (
    text.includes("continue") ||
    text.includes("继续修") ||
    text.includes("继续改") ||
    text.includes("接着修")
  );
}

/**
 * Explicit identity keys written on the human continue-fixing signal.
 * Never derived from findings cargo (ADR 0131 / #899).
 */
function explicitContinueFixingKeys(
  event: ContinueFixingEvent,
): ReadonlyArray<string> {
  const keys: string[] = [];
  const addKey = (key: string | undefined) => {
    if (key !== undefined && key.trim().length > 0) keys.push(key);
  };
  addKey(event.findingIdentityKey);
  for (const key of event.findingScope?.identityKeys ?? []) addKey(key);
  return keys;
}

/**
 * Whether the human continue-fixing event carries an actionable explicit
 * signal (exact identity key and/or non-empty findingScope fields). Runner
 * does NOT match that signal against findings cargo — scope filtering is the
 * fixer's job (#899 / ADR 0131).
 */
function hasContinueFixingSignal(event: ContinueFixingEvent): boolean {
  if (explicitContinueFixingKeys(event).length > 0) return true;
  const scope = event.findingScope;
  if (scope === undefined) return false;
  return (
    (scope.locations?.length ?? 0) > 0 ||
    (scope.categories?.length ?? 0) > 0 ||
    (scope.findingGroup?.trim().length ?? 0) > 0 ||
    (scope.reviewContext?.trim().length ?? 0) > 0 ||
    (scope.featureArea?.trim().length ?? 0) > 0
  );
}

export function normalizeGitOutputLines(output: string): string[] {
  return output
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function gitOutputLines(
  worktree: WorktreeHandle | undefined,
  args: ReadonlyArray<string>,
): string[] {
  if (worktree === undefined) return [];
  try {
    return normalizeGitOutputLines(
      shWithClock("git", ["-C", worktree.path, ...args], {
        stage: "reconcile:git",
      }),
    );
  } catch {
    return [];
  }
}

function gitHead(worktree: WorktreeHandle | undefined): string | undefined {
  return gitOutputLines(worktree, ["rev-parse", "HEAD"])[0];
}
/**
 * #677: rebuild S5→S6 reverify locals from the persisted S5 ledger row.
 *
 * `preexistingAssertionTouchedForReverify` and
 * `refusedFindingIdentityKeysForReverify` are process-local; a crash between
 * S5 completing and S6 running would otherwise drop both. Prefer rebuild over
 * new durable fields: refuse keys already live on the S5 coder output, and the
 * assertion signal is recomputed from ledger branchHEADs + worktree git
 * (same shape as #743 authorization rebuild / S4 findings-count replay).
 */
interface S5ReverifySignals {
  readonly preexistingAssertionTouched: boolean;
  readonly refusedFindingIdentityKeys: readonly string[];
}

function ledgerEntryBranchHead(entry: LedgerEntry): string | undefined {
  const head = (entry as PersistentLedgerEntry).branchHEAD;
  return isLikelyGitSha(head) ? head : undefined;
}

function refusedKeysFromCoderOutput(
  output: Extract<StepOutput, { kind: "coder" }>,
): readonly string[] {
  const records = output.refuseRecords ?? [];
  if (records.length > 0) {
    return reviewFixDecisionGate({ records })?.refusedFindingIdentityKeys ?? [];
  }
  return output.refusedFindingIdentityKeys ?? [];
}

export function rebuildS5ReverifySignalsFromLedger(
  ledger: ReadonlyArray<LedgerEntry>,
  worktree: WorktreeHandle | undefined,
): S5ReverifySignals {
  let s5Index = -1;
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (isBookkeepingEntry(entry)) continue;
    if (entry.step === "S5" && entry.output?.kind === "coder") {
      s5Index = i;
      break;
    }
  }
  if (s5Index < 0) {
    return {
      preexistingAssertionTouched: false,
      refusedFindingIdentityKeys: [],
    };
  }

  const s5 = ledger[s5Index]!;
  const output = s5.output as Extract<StepOutput, { kind: "coder" }>;
  const refusedFindingIdentityKeys = refusedKeysFromCoderOutput(output);

  let preexistingAssertionTouched = false;
  if (worktree !== undefined) {
    const afterFix = ledgerEntryBranchHead(s5);
    let beforeFix: string | undefined;
    for (let j = s5Index - 1; j >= 0; j--) {
      const prev = ledger[j]!;
      if (isBookkeepingEntry(prev)) continue;
      const head = ledgerEntryBranchHead(prev);
      if (head !== undefined) {
        beforeFix = head;
        break;
      }
    }
    if (
      afterFix !== undefined &&
      beforeFix !== undefined &&
      beforeFix !== afterFix
    ) {
      try {
        preexistingAssertionTouched = reviewFixAssertionSignal({
          worktreePath: worktree.path,
          sliceBase: worktree.base,
          beforeFix,
          afterFix,
        });
      } catch {
        // Host-git observations are best-effort bookkeeping. Missing local
        // objects must not change the worker receipt's route.
        preexistingAssertionTouched = false;
      }
    }
  }

  return {
    preexistingAssertionTouched,
    refusedFindingIdentityKeys,
  };
}

interface ContinueFixingRepair {
  readonly event: ContinueFixingEvent | EscalationAnswerEvent;
  readonly matchingIdentityKeys: ReadonlyArray<string>;
}

function continueRepairFromEvent(
  event: ContinueFixingEvent,
  openCount: number,
): ContinueFixingRepair | undefined {
  // Explicit human signal only. Do not read findings cargo or derive identity
  // keys here — landing/fixer owns cargo identity materialization (#899).
  if (!hasContinueFixingSignal(event)) return undefined;
  // Channel (b): reopen only when the reviewer declared open findings.
  // Disposition prose / cargo-row key matching is not a runner court (#877/#899).
  if (openCount <= 0) return undefined;
  return {
    event,
    matchingIdentityKeys: explicitContinueFixingKeys(event),
  };
}

function continueRepairFromAnswer(
  answer: EscalationAnswerEvent | undefined,
  openCount: number,
): ContinueFixingRepair | undefined {
  if (answer === undefined || !answerMapsToContinueFixing(answer)) {
    return undefined;
  }
  const source = answer.source;
  if (!isExecutableEscalationAnswerSource(source)) return undefined;
  return continueRepairFromEvent(
    {
      event: "runner_bookkeeping",
      intent: "continue_fixing",
      source,
      ts: "answer-scope-only",
      ...(answer.findingIdentityKey !== undefined
        ? { findingIdentityKey: answer.findingIdentityKey }
        : {}),
      ...(answer.findingScope !== undefined
        ? { findingScope: answer.findingScope }
        : {}),
    },
    openCount,
  );
}

function latestContinueFixingAfter(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
  index: number,
  openCount: number,
): ContinueFixingRepair | undefined {
  for (let i = ledger.length - 1; i > index; i--) {
    const entry = ledger[i]!;
    if (!isContinueFixingEntry(entry)) continue;
    const repair = continueRepairFromEvent(entry, openCount);
    if (repair !== undefined) return repair;
  }
  return undefined;
}

function escalationKindForHandoff(
  status: HandoffStatus,
): EscalationKind | undefined {
  // This call site only transports route()'s worker-raised decision gate.
  // Process failures use escalateTermination(..., "failure") directly.
  return status === "escalate" ? "decision" : undefined;
}

/**
 * Find the most recent ledger entry that carries an agent output. The S8
 * handoff entry never has an output, so this skips it to recover the real
 * last agent result (which `route()` and escalate detection act on).
 */
function lastAgentEntry(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): PersistentLedgerEntry | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    if (ledger[i]!.output != null) return ledger[i];
  }
  return undefined;
}

/**
 * The StepId of the most recent agent step in a (possibly minimal) ledger —
 * used to label the `failedStep` of an error package when re-feeding a prior
 * error-terminated run. Returns undefined when no agent step is present.
 */
function lastAgentStep(
  ledger: ReadonlyArray<LedgerEntry>,
): SliceStepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.output != null && isValidStepId(entry.step)) return entry.step;
  }
  return undefined;
}

/**
 * The StepId of the most recent NON-S8 entry. Used to recover the deciding
 * step when an untagged (legacy) S8 entry is the last ledger record: route()
 * is terminal at S8, so we infer the handoff from the step that produced it.
 */
function lastNonTerminalStep(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): SliceStepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step !== "S8" && isValidStepId(entry.step)) return entry.step;
  }
  return undefined;
}

function isLikelyGitSha(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{7,64}$/.test(value);
}

const WORKER_STDOUT_MISSING_TAG_RE =
  /\b(?:coder step stdout carried no <coder>|reviewer step stdout carried no <review>)[\s\S]*tag\b/i;
function lastReviewerStep(
  ledger: ReadonlyArray<LedgerEntry>,
): SliceStepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.output?.kind === "reviewer" && isValidStepId(entry.step)) return entry.step;
  }
  return undefined;
}

interface S4FindingsCountReplay {
  readonly blocking: ReadonlyArray<Finding>;
  readonly blockingIdentityKeys: ReadonlyArray<string>;
  /** Reviewer-declared open-count (ADR 0131), not findings-array length. */
  readonly blockingFindingCount: number;
  readonly findingDispositions: ReadonlyArray<FindingDisposition>;
  /**
   * Rebuilt raw artifact pointers for the positive-count → S5 edge after an S4
   * resume boundary (host paths; materialised into the fixer sandbox at landing).
   */
  readonly rawReviewerArtifacts?: WorkerLandingPayload["rawReviewerArtifacts"];
}

/**
 * Opaque pointers to the preceding reviewer's raw products. Always attached on
 * the positive-count → S5 edge so sparse/missing findings cargo cannot produce
 * a no-op fixer landing (ADR 0131 / #899).
 */
function reviewerRawArtifactPointers(
  handle: import("./types.js").WorkerMonitorHandle | undefined,
  sessionId: string | undefined,
): NonNullable<WorkerLandingPayload["rawReviewerArtifacts"]> {
  return {
    ...(handle?.logPath !== undefined ? { stdoutPath: handle.logPath } : {}),
    ...(handle?.resultPath !== undefined ? { sidecarPath: handle.resultPath } : {}),
    ...(sessionId !== undefined ? { reviewerSessionId: sessionId } : {}),
    statement: "the previous reviewer raw artifacts are here",
  };
}

function replayS4FindingsCountState(
  ledger: ReadonlyArray<LedgerEntry>,
): S4FindingsCountReplay {
  let pendingBlockingFindings: Finding[] = [];
  let pendingBlockingFindingIdentityKeys: string[] = [];
  let pendingBlockingFindingCount = 0;
  let findingDispositions: FindingDisposition[] = [];
  let lastReviewerOutputForS4: StepOutput | undefined;
  let lastReviewerSessionId: string | undefined;
  let lastReviewerMonitorHandle: import("./types.js").WorkerMonitorHandle | undefined;
  let pendingRawReviewerArtifacts: WorkerLandingPayload["rawReviewerArtifacts"];

  for (const entry of ledger) {
    if (isBookkeepingEntry(entry)) {
      continue;
    }
    if (entry.output?.kind === "reviewer") {
      if (!isStepId(entry.step)) continue;
      lastReviewerOutputForS4 = entry.output;
      lastReviewerSessionId =
        typeof entry.sessionId === "string" ? entry.sessionId : undefined;
      lastReviewerMonitorHandle = entry.monitorHandle;
      continue;
    }
    if (entry.step !== "S4" || lastReviewerOutputForS4?.kind !== "reviewer") {
      continue;
    }

    // #877: findings-count channel only — disposition prose / still-active
    // reopen / no-progress courts demolished. Prior keys absent from findings[]
    // are closed by the three-channel envelope; the runner does not inspect prose.
    // Findings rows are opaque cargo: typed ReviewerOutput already decoded them
    // at the worker boundary; runner only shallow-copies + count-routes. Identity
    // keys are derived at the fixer landing writer, not here (ADR 0131 / #899).
    findingDispositions = [
      ...(entry.findingDispositions ?? []),
    ];
    // Opaque cargo copy only — not a decode/validation boundary.
    pendingBlockingFindings = [...lastReviewerOutputForS4.findings];
    pendingBlockingFindingIdentityKeys = [];
    // Count is the typed open-count, never cargo-array length.
    pendingBlockingFindingCount = lastReviewerOutputForS4.findingsCount;
    // Live path attaches raw pointers on every positive open-count → S5 edge;
    // resume after the persisted S4 boundary must rebuild them from the
    // preceding reviewer ledger row (sessionId + monitor handle paths).
    pendingRawReviewerArtifacts =
      lastReviewerOutputForS4.findingsCount > 0
        ? reviewerRawArtifactPointers(
            lastReviewerMonitorHandle,
            lastReviewerSessionId,
          )
        : undefined;
  }

  // Pre-S4 crash window (codex R3 / C-R4-1): last reviewer has positive open-
  // count but either no S4 row yet, or an earlier S4 left stale raw pointers
  // from a prior round (S3 r1 → S4 → S5 → S6 r2, crash before the second S4).
  // Always rebind findings/count/raw from the last reviewer so S5 does not
  // inherit r1 artifacts when r2 is the open review.
  if (
    lastReviewerOutputForS4?.kind === "reviewer" &&
    typeof lastReviewerOutputForS4.findingsCount === "number" &&
    Number.isSafeInteger(lastReviewerOutputForS4.findingsCount) &&
    lastReviewerOutputForS4.findingsCount > 0
  ) {
    pendingBlockingFindings = [...lastReviewerOutputForS4.findings];
    pendingBlockingFindingIdentityKeys = [];
    pendingBlockingFindingCount = lastReviewerOutputForS4.findingsCount;
    pendingRawReviewerArtifacts = reviewerRawArtifactPointers(
      lastReviewerMonitorHandle,
      lastReviewerSessionId,
    );
  }

  return {
    blocking: pendingBlockingFindings,
    blockingIdentityKeys: pendingBlockingFindingIdentityKeys,
    blockingFindingCount: pendingBlockingFindingCount,
    findingDispositions,
    ...(pendingRawReviewerArtifacts !== undefined
      ? { rawReviewerArtifacts: pendingRawReviewerArtifacts }
      : {}),
  };
}

/**
 * Derive the resume plan from a persisted ledger.
 *
 * The decision is made purely from the ledger contents (resume truth), never
 * from any in-memory/LLM state (PRD #244 US#22 / #255 AC4):
 *
 *   1. Empty ledger              → resume from S0 (treat as a fresh run).
 *   2. The last agent output escalated AND a later escalation_answered row exists
 *      → resume THAT step in its original session (resumeSession + sessionId).
 *      Without the appended answer, report the prior escalate terminal status.
 *   3. The prior run reached a terminal handoff that is NOT being re-opened
 *      (S8 entry, or the last step routes straight to a handoff) → report that
 *      handoff's TRUE status (success / error / escalate) — never a hardcoded
 *      success. The S8 entry carries `handoffStatus` (#255); when the terminal
 *      status must be inferred (a crash before the S8 write), route() gives it.
 *   4. Otherwise (crash mid-run) → continue from `route()`'s successor of the
 *      last recorded step, with a fresh dispatch.
 */
function planResume(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
  repairIntent?: ContinueFixingEvent,
): ResumePlan {
  if (ledger.length === 0) {
    return { resumeStep: "S0", priorLedger: [] };
  }

  const executableLedger = executableLedgerEntries(ledger);
  if (executableLedger.length === 0) {
    return { resumeStep: "S0", priorLedger: ledger as ReadonlyArray<LedgerEntry> };
  }

  const lastEntry = executableLedger[executableLedger.length - 1]!;
  const lastEntryIndex = ledger.lastIndexOf(lastEntry);
  const agentEntry = lastAgentEntry(executableLedger);

  // #709 exemption: keep strict !== undefined (not != null) — escalationKind presence
  // on S8(escalate) distinguishes legacy untagged (absent → fallthrough to Case 2
  // agentEscalate + answer reopen logic) from tagged kind (present → use "decision"
  // vs "failure" to decide reopen vs always-terminal). Traced: planResume Case1 vs
  // Case2/3a; familyEscalationState uses ==/=== directly; "unknown tagged" test forces
  // terminal for non-decision even w/ answer. null-vs-undefined load-bearing for
  // resume routing on deserialized persisted ledger (same JSONL class as stopSummary).
  // Explicit null treated as "tagged invalid kind" (terminal) not "absent legacy".
  if (
    lastEntry.step === "S8" &&
    lastEntry.handoffStatus === "escalate" &&
    lastEntry.escalationKind !== undefined
  ) {
    if (lastEntry.escalationKind === "failure") {
      return {
        terminalStatus: "escalate",
        resumeStep: "S8",
        lastOutput: agentEntry?.output,
        priorLedger: ledger as ReadonlyArray<LedgerEntry>,
      };
    }
    if (lastEntry.escalationKind !== "decision") {
      return {
        terminalStatus: "escalate",
        resumeStep: "S8",
        lastOutput: agentEntry?.output,
        priorLedger: ledger as ReadonlyArray<LedgerEntry>,
      };
    }

    const decisionStep = lastNonTerminalStep(executableLedger);
    const replayedS4 = replayS4FindingsCountState(executableLedger);
    const answer =
      decisionStep !== undefined
        ? latestAnswerAfter(ledger, lastEntryIndex, decisionStep)
        : undefined;
    const continueFixingRepair =
      decisionStep === "S4"
        ? repairIntent !== undefined
          ? continueRepairFromEvent(
              repairIntent,
              replayedS4.blockingFindingCount,
            )
          : latestContinueFixingAfter(
              ledger,
              lastEntryIndex,
              replayedS4.blockingFindingCount,
            ) ??
            continueRepairFromAnswer(answer, replayedS4.blockingFindingCount)
        : undefined;
    if (
      decisionStep === undefined ||
      (answer === undefined && continueFixingRepair === undefined)
    ) {
      return {
        terminalStatus: "escalate",
        resumeStep: "S8",
        lastOutput: agentEntry?.output,
        priorLedger: ledger as ReadonlyArray<LedgerEntry>,
      };
    }

    if (decisionStep === "S4") {
      if (continueFixingRepair === undefined) {
        return {
          terminalStatus: "escalate",
          resumeStep: "S8",
          lastOutput: agentEntry?.output,
          priorLedger: ledger as ReadonlyArray<LedgerEntry>,
        };
      }
      return {
        resumeStep: "S5",
        escalationAnswer:
          answer !== undefined && answerMapsToContinueFixing(answer)
            ? answer
            : undefined,
        continueFixingRepair,
        lastOutput: agentEntry?.output,
        priorLedger: ledger as ReadonlyArray<LedgerEntry>,
      };
    }

    if (
      agentEntry !== undefined &&
      agentEntry.step === decisionStep &&
      isValidStepId(agentEntry.step) &&
      isValidEscalation(escalateOf(agentEntry.output))
    ) {
      const escalatedLedgerIdx = ledger.lastIndexOf(agentEntry);
      return {
        resumeStep: agentEntry.step,
        resumeSessionId:
          typeof agentEntry.sessionId === "string" ? agentEntry.sessionId : undefined,
        escalationAnswer: answer,
        lastOutput: agentEntry.output,
        priorLedger: ledger.slice(0, escalatedLedgerIdx) as ReadonlyArray<LedgerEntry>,
      };
    }

    return {
      terminalStatus: "escalate",
      resumeStep: "S8",
      lastOutput: agentEntry?.output,
      priorLedger: ledger as ReadonlyArray<LedgerEntry>,
    };
  }

  // Case 2: legacy/untagged agent decision-escalate residue — the last agent
  // output carries an escalation object (the bell; its fields are cargo). Only a
  // later escalation_answered row re-opens THAT step in its original agent
  // session; otherwise the prior S8(escalate) remains a pause.
  //
  // Persisted legacy ledgers may predate the receipt bell normalizer. Keep the
  // compatibility presence guard here; current receipt cargo quality never
  // changes whether the worker pressed the decision bell.
  //
  // integ-cmr m2 r2 (#252 ⋈ #255): a tagged terminal S8(error) ALSO supersedes
  // escalate-resume, even when the decision bell is present. An escalate handoff
  // whose S8 write faulted returns status:error in-run and best-effort persists
  // a tagged 'error' S8 — the disk then holds a decision-bell agent entry AND a
  // trailing S8(error). The run errored; re-feeding must report that ERROR (Case
  // 3a), NOT re-run the escalating step via resumeSession. So Case 2 yields when
  // the last entry is a tagged terminal-error S8. (A legitimate human-answered
  // escalate has S8(escalate) plus a later answer row — NOT error — so it still
  // resumes here.)
  const lastIsTaggedError =
    lastEntry.step === "S8" && lastEntry.handoffStatus === "error";
  const agentEscalate = escalateOf(agentEntry?.output);
  if (
    !lastIsTaggedError &&
    agentEntry !== undefined &&
    agentEscalate != null &&
    isValidEscalation(agentEscalate)
  ) {
    if (!isValidStepId(agentEntry.step)) {
      throw new Error("planResume: agent output cannot belong to bookkeeping ledger row");
    }
    const escalatedLedgerIdx = ledger.lastIndexOf(agentEntry);
    const answerSearchIndex =
      lastEntry.step === "S8" ? lastEntryIndex : escalatedLedgerIdx;
    const answer = latestAnswerAfter(
      ledger,
      answerSearchIndex,
      agentEntry.step,
    );
    if (answer === undefined) {
      return {
        terminalStatus: "escalate",
        resumeStep: "S8",
        lastOutput: agentEntry.output,
        priorLedger: ledger as ReadonlyArray<LedgerEntry>,
      };
    }
    // Drop the prior terminal handoff (and any entries after the escalated
    // step): we are re-opening that step, so the prior boundary is superseded.
    // The slice is EXCLUSIVE of the escalated step itself — it is re-run via
    // resumeSession and gets a fresh in-memory entry, so keeping the old one
    // here would duplicate it. ADR 0030 has multiple agent steps (S2/S3/S5/S6);
    // whichever one escalated is resumed in its recorded session after the human
    // answer, while normal review/fix rounds stay fresh dispatches.
    const priorLedger = ledger.slice(0, escalatedLedgerIdx);
    return {
      resumeStep: agentEntry.step,
      resumeSessionId:
        typeof agentEntry.sessionId === "string" ? agentEntry.sessionId : undefined,
      escalationAnswer: answer,
      lastOutput: agentEntry.output,
      priorLedger: priorLedger as ReadonlyArray<LedgerEntry>,
    };
  }

  // Case 3a: the prior run wrote a terminal S8 entry. Report its TRUE status
  // (recorded in handoffStatus, #255) — a prior error/escalate must not be
  // re-reported as success. If an older ledger lacks the tag, fall back to
  // inferring via route() below.
  if (lastEntry.step === "S8" && lastEntry.handoffStatus !== undefined) {
    return {
      terminalStatus: lastEntry.handoffStatus,
      resumeStep: "S8",
      lastOutput: agentEntry?.output,
      priorLedger: ledger as ReadonlyArray<LedgerEntry>,
    };
  }

  // Case 3b / 4: no escalation, no tagged terminal entry. Ask route() what the
  // last recorded step leads to (route() reads the recorded output, not LLM
  // memory). A handoff → the prior run terminated (crash after the deciding
  // step but before the S8 write, or an untagged legacy S8) → report that
  // status. A next step → crash mid-run → continue from there.
  //
  // route() never routes OUT of S8 (it is terminal — calling it throws). When
  // the last entry is an untagged S8 (a legacy ledger written before #255 added
  // the handoffStatus tag), route from the last NON-S8 step instead so we can
  // still infer the terminal status.
  const routeFrom =
    lastEntry.step === "S8"
      ? lastNonTerminalStep(executableLedger) ?? lastEntry.step
      : lastEntry.step;
  if (!isValidStepId(routeFrom)) {
    throw new Error("planResume: executable ledger row must use a canonical step id");
  }
  const routeOutput = agentEntry?.output;
  const decision = route({
    from: routeFrom,
    output: routeOutput,
  });
  const priorForResume = ledger as ReadonlyArray<LedgerEntry>;
  // #683: quota wait park → re-enter the parked step (not S8(error)).
  const quotaWaitStep = sliceQuotaWaitPending(ledger);
  if (quotaWaitStep !== undefined) {
    return {
      resumeStep: quotaWaitStep,
      lastOutput: undefined,
      priorLedger: priorForResume,
    };
  }
  if (decision.kind === "handoff") {
    return {
      terminalStatus: decision.status,
      resumeStep: "S8",
      lastOutput: routeOutput,
      priorLedger: priorForResume,
    };
  }
  return {
    resumeStep: decision.step,
    lastOutput: routeOutput,
    priorLedger: priorForResume,
  };
}

/**
 * Project tool-chain declared on the image (#253 AC-6, US #29).
 * Must include Python + frontend stack so both game-backend and web slices can
 * run their tests inside the same image.
 */
const IMAGE_TOOLCHAIN: ReadonlyArray<string> = [
  "python",
  "node",
  "npm",
  "typescript",
] as const;

// #873 / ADR 0062: runner has NO authority to judge reviewer output format
// (findings schema, tags, zod). Format belongs at write-point / worker.
// Runner only: process exit / open findings count / worker-raised decision gate.

/**
 * The fixed StepSpecs for child-slice worker steps. Versioned promptFiles,
 * never assembled inline (ADR 0018 决定#4).
 *
 * ADR 0030 makes the per-slice loop runner-visible: S2 implements, S3 reviews,
 * S5 fixes blocking findings, and S6 performs the fresh full-diff re-review.
 *
 * #253 fields: model (CLI slug), completionSignal (Sandcastle run() API), maxIter
 * (per-seat Sandcastle iteration budget — NOT a fix-loop give-up counter), soul,
 * toolchain.
 *
 * maxIter SEMANTICS (#899 / ADR 0128): every selected seat is single-iteration
 * (`maxIter: 1`). The skill finishes inside that one `sandbox.run()`; native
 * structured-output re-asks are in-session, not outer iterations. Hitting
 * maxIter ends the step normally — never "orchestrator gives up" (that only
 * happens on a MODEL escalate — US#18/US#19). See StepSpec.maxIter.
 *
 * Swapping models = set ORCHESTRATOR_ROUTE for the base preset, optionally layered
 * with single-slot overrides (see {@link coderModel}); no image rebuild, no
 * structural StepSpec change (PRD #244 Implementation Decisions + ADR 0031).
 */

/**
 * The S2 coder worker's model slug, selected by the active route and optionally
 * overridden via `ORCHESTRATOR_CODER_MODEL`. The slug is resolved to the baked CLI
 * by agentForSlug; invalid route names / slugs fail closed before dispatch.
 */
export function coderModel(env: ModelRouteEnv = process.env): string {
  return modelForSlot("coder", env);
}

export function reviewerModel(env: ModelRouteEnv = process.env): string {
  return modelForSlot("reviewer", env);
}

type WorkerStepId = "S2" | "S3" | "S5" | "S6";

export function stepSpecsForRoute(
  route: Pick<ResolvedModelRoute, "slots">,
): Readonly<Record<WorkerStepId, StepSpec>> {
  return {
    S2: {
      id: "S2",
      role: "coder",
      promptFile: "coder_implement.md",
      // The whole-slice build worker's model is env-switchable (default Codex
      // gpt-5.6-terra; was Sonnet 4.6). The slug is resolved to the baked CLI by
      // agentForSlug (realBackend); switching the model is `ORCHESTRATOR_CODER_MODEL`
      // alone — no image rebuild, no StepSpec shape change.
      model: route.slots.coder,
      completionSignal: "CODER_STEP_COMPLETE",
      // #899 / ADR 0128: one single-iteration Sandcastle run per seat; the skill
      // finishes inside that invocation (no outer Ralph multi-iter).
      maxIter: 1,
      soul: "coder",
      toolchain: IMAGE_TOOLCHAIN,
    },
    S3: {
      id: "S3",
      role: "reviewer",
      promptFile: "reviewer_review.md",
      model: route.slots.reviewer,
      completionSignal: "REVIEWER_STEP_COMPLETE",
      maxIter: 1,
      soul: "READ-ONLY",
      toolchain: IMAGE_TOOLCHAIN,
    },
    S5: {
      id: "S5",
      role: "coder",
      promptFile: "coder_fix.md",
      model: route.slots.coderFix,
      completionSignal: "CODER_STEP_COMPLETE",
      // #899 / ADR 0128: single-iteration seat (same as S2).
      maxIter: 1,
      soul: "coder",
      toolchain: IMAGE_TOOLCHAIN,
    },
    S6: {
      id: "S6",
      role: "reviewer",
      promptFile: "reviewer_review.md",
      model: route.slots.reviewer,
      completionSignal: "REVIEWER_STEP_COMPLETE",
      maxIter: 1,
      soul: "READ-ONLY",
      toolchain: IMAGE_TOOLCHAIN,
    },
  };
}

/** The relay pool belongs to one wall-hit route entry, never the whole lineup. */
function activeRelaySmokeEntryKey(
  step: StepId | undefined,
  route: Pick<ResolvedModelRoute, "slots">,
): string | undefined {
  const slot =
    step === "S2" ? "coder" :
    step === "S3" || step === "S6" ? "reviewer" :
    step === "S5" ? "coderFix" : undefined;
  return slot === undefined ? undefined : `${slot}:${route.slots[slot]}`;
}

export function stepSpecsForEnv(
  env: ModelRouteEnv = process.env,
): Readonly<Record<WorkerStepId, StepSpec>> {
  return stepSpecsForRoute(resolveActiveModelRoute(env));
}

export const WORKER_PROMPT_FILES: Readonly<Record<WorkerStepId, string>> = {
  S2: "coder_implement.md",
  S3: "reviewer_review.md",
  S5: "coder_fix.md",
  S6: "reviewer_review.md",
};

/** Synthesise a human-readable reason for a route-owned error edge. */
function buildErrorReason(step: StepId, _output: StepOutput | undefined): string {
  return `step ${step} routed to error handoff`;
}

function acceptedSuppressionsFromDispositions(
  dispositions: ReadonlyArray<FindingDisposition>,
): AcceptedSuppressionSummary[] {
  return dispositions.flatMap((disposition) => {
    if (
      disposition.status !== "accepted_suppressed" ||
      !hasAcceptedSuppressionAuthority(disposition) ||
      disposition.source === undefined ||
      disposition.scope === undefined ||
      disposition.boundedReopen === undefined
    ) {
      return [];
    }
    return [
      {
        source: disposition.source,
        scope: disposition.scope,
        reason: disposition.reason,
        findingIdentity: disposition.identityKey,
        boundedReopen: disposition.boundedReopen,
      },
    ];
  });
}

function successSummaryForCurrentState(input: {
  readonly findingDispositions: ReadonlyArray<FindingDisposition>;
}): StopSummary {
  // #604 slice 4 (ADR 0062): a success summary carries accepted-suppression
  // metadata only.
  const acceptedSuppressions = acceptedSuppressionsFromDispositions(
    input.findingDispositions,
  );
  return successStopSummary(
    acceptedSuppressions.length > 0 ? { acceptedSuppressions } : undefined,
  );
}

function stopSummaryForErrorPackage(errorPackage: ErrorPackage): StopSummary {
  const repairHint = /MODULE_NOT_FOUND|Cannot find module/i.test(errorPackage.reason)
    ? `install or restore the missing module for ${errorPackage.failedStep}, then rerun`
    : `inspect ${errorPackage.failedStep} and rerun after repairing the cause`;
  if (/source authentication failed/i.test(errorPackage.reason)) {
    return {
      reason: "spec_conflict",
      summary: errorPackage.reason,
      repairHint:
        "move executable instructions into a repo-owner-authored Agent Brief, accepted issue body, ADR, or runner Agent Brief, then rerun",
    };
  }
  // Pure reporting telemetry: this label does not choose retry, park, or
  // termination. Those control decisions have already happened upstream.
  if (
    /contract|malformed|does not match|no valid result|off-contract|prior claimed-fixed finding|prior finding disposition/i.test(
      errorPackage.reason,
    ) ||
    WORKER_STDOUT_MISSING_TAG_RE.test(errorPackage.reason)
  ) {
    return contractDriftStopSummary({ summary: errorPackage.reason, repairHint });
  }
  return infraFailureStopSummary({
    summary: errorPackage.reason,
    repairHint,
  });
}

function untrustedExecutableInstructionSummary(
  _snapshot: IssueSnapshot,
): StopSummary | undefined {
  // Non-owner Agent Brief headings are ordinary issue/comment text. Only the
  // structured IssueSnapshot.agentBrief field is executable runner input.
  return undefined;
}

function stopSummaryForEscalation(escalation: Escalation): StopSummary {
  const reason = `${escalation.reason}: ${escalation.diagnosis}`;
  return {
    reason: "spec_conflict",
    summary: reason,
    repairHint: "answer the decision escalation and rerun",
  };
}

function stopSummaryForStartupRouteFailure(escalation: Escalation): StopSummary {
  const reason =
    `${escalation.reason}: ${escalation.diagnosis}; ` +
    `route env ORCHESTRATOR_ROUTE=${process.env.ORCHESTRATOR_ROUTE ?? "normal"}, ` +
    `ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS=${process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS ?? "(unset)"}`;
  return infraFailureStopSummary({
    summary: reason,
    repairHint: "fix the active model route or route env overrides before dispatching workers",
  });
}

function latestLedgerStopSummary(
  ledger: ReadonlyArray<LedgerEntry>,
): StopSummary | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const stopSummary = ledger[i]!.stopSummary;
    if (stopSummary != null) return stopSummary;
  }
  return undefined;
}

export async function runOrchestrator(input: RunInput): Promise<RunResult> {
  const { issueNumber, backend } = input;
  const relayNow = (): Date =>
    input.now !== undefined ? input.now() : new Date();
  let modelRoute: ResolvedModelRoute;
  try {
    modelRoute = resolveActiveModelRoute();
  } catch (err) {
    const reason =
      err instanceof Error ? err.message : `failed to resolve active model route: ${String(err)}`;
    const stopSummary = stopSummaryForStartupRouteFailure({
      reason: "startup route failure",
      diagnosis: `${reason}; route env ORCHESTRATOR_ROUTE=${process.env.ORCHESTRATOR_ROUTE ?? "normal"}, ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS=${process.env.ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS ?? "(unset)"}`,
    });
    return {
      status: "error",
      errorPackage: { failedStep: "S0", reason },
      stepLedger: [{ step: "S8", stopSummary }],
      stopSummary,
    };
  }
  const routePolicy = await applyRuntimeTightRoutePolicy(modelRoute, {
    interactive: process.stdin.isTTY === true && process.stdout.isTTY === true,
    warn: (message) => console.warn(`[orchestrator] ${message}`),
  });
  if (routePolicy.kind === "stop") {
    const stopSummary = stopSummaryForStartupRouteFailure(routePolicy.escalation);
    return {
      status: "escalate",
      errorPackage: {
        failedStep: "S0",
        reason: `${routePolicy.escalation.reason}: ${routePolicy.escalation.diagnosis}`,
      },
      stepLedger: [{ step: "S8", stopSummary }],
      stopSummary,
    };
  }
  console.info(
    `[orchestrator] model route lineup\n${printableRouteLineup(routePolicy.route)}`,
  );
  // #767: modelRoute / stepSpecs stay mutable so Coder-Rec can override the
  // coder (+ coderFix) slot at S0 and advance it after non-converging fix rounds.
  modelRoute = routePolicy.route;
  let stepSpecs = stepSpecsForRoute(modelRoute);
  /** Issue body used for Coder-Rec parse (S0 meta.body, else S1 snapshot.body). */
  let coderRecIssueBody: string | undefined;
  /** When true, ORCHESTRATOR_CODER_MODEL won — never re-apply Coder-Rec. */
  let coderRecEnvSkipped = false;
  let routeSmokeChecked = false;
  /** #686 — last applied relay baton's billing pool (drives next exhaustion lookup). */
  let currentBillingPool: BillingPoolId | undefined;
  /**
   * Correctness B3 — run-scoped pools that already hit a quota wall this run.
   * Excluded from route-smoke knownLive promotion so a smoke-passed pool cannot
   * re-enter as a live baton and ping-pong until the handoff cap.
   */
  const wallHitBillingPools = new Set<BillingPoolId>();
  /**
   * #686 — sticky resource-relay baton slug. Scopes stickiness to resource
   * handoffs only: blocks Coder-Rec snap-back while nonConvergingRounds === 0,
   * but clears so #767 quality advance (S6 rounds) still runs.
   */
  let stickyRelayCoderSlug: string | undefined;
  /** S5 resource relay is independent from the normal S2 coder slot. */
  let stickyRelayCoderFixSlug: string | undefined;
  /** #686 — last written relay focus path (forwarded on next dispatch). */
  let activeRelayFocusPath: string | undefined;
  /** The only step allowed to consume the current relay pool and focus baton. */
  let activeRelayStep: StepId | undefined;
  // #924: coder persistent session across S2 → S5 rounds (declared early so
  // Coder-Rec model advances can invalidate it before the next dispatch).
  let coderSessionId: string | undefined;
  let coderSessionModel: string | undefined;

  const applyCoderRecSelection = async (
    nonConvergingRounds: number,
  ): Promise<ReturnType<typeof applyRuntimeTightRoutePolicy> | undefined> => {
    if (coderRecEnvSkipped) return undefined;
    // Resource-relay stickiness: hold the baton until #767 quality advance
    // would actually move (S6 rounds ≥ FALLBACK). Do NOT set coderRecEnvSkipped.
    if (
      stickyRelayCoderSlug !== undefined &&
      nonConvergingRounds < CODER_REC_FALLBACK_AFTER_ROUNDS
    ) {
      if (modelRoute.slots.coder !== stickyRelayCoderSlug) {
        modelRoute = withCoderSlot(modelRoute, stickyRelayCoderSlug);
        stepSpecs = stepSpecsForRoute(modelRoute);
        routeSmokeChecked = false;
        // #924: relay model change drops the prior coder session.
        if (
          coderSessionModel !== undefined &&
          stepSpecs.S2.model !== coderSessionModel &&
          stepSpecs.S5.model !== coderSessionModel
        ) {
          coderSessionId = undefined;
          coderSessionModel = undefined;
        }
      }
      return undefined;
    }
    if (
      stickyRelayCoderFixSlug !== undefined &&
      nonConvergingRounds < CODER_REC_FALLBACK_AFTER_ROUNDS
    ) {
      if (modelRoute.slots.coderFix !== stickyRelayCoderFixSlug) {
        modelRoute = {
          ...modelRoute,
          slots: { ...modelRoute.slots, coderFix: stickyRelayCoderFixSlug },
        };
        stepSpecs = stepSpecsForRoute(modelRoute);
        routeSmokeChecked = false;
        if (
          coderSessionModel !== undefined &&
          stepSpecs.S2.model !== coderSessionModel &&
          stepSpecs.S5.model !== coderSessionModel
        ) {
          coderSessionId = undefined;
          coderSessionModel = undefined;
        }
      }
      return undefined;
    }
    if (stickyRelayCoderSlug !== undefined) {
      stickyRelayCoderSlug = undefined;
    }
    if (stickyRelayCoderFixSlug !== undefined) {
      stickyRelayCoderFixSlug = undefined;
    }
    let applied: ReturnType<typeof applyCoderRecToRoute>;
    try {
      applied = applyCoderRecToRoute(
        modelRoute,
        coderRecIssueBody,
        nonConvergingRounds,
      );
    } catch (err) {
      // #906: broken Coder-Rec mark / unregistered model → admission fail-closed
      // (same family as route smoke failure): escalate, zero dispatch.
      const diagnosis = err instanceof Error ? err.message : String(err);
      return {
        kind: "stop",
        escalation: {
          reason: "Coder-Rec admission failure",
          diagnosis,
        },
      };
    }
    if (applied.skippedForEnvOverride) {
      coderRecEnvSkipped = true;
      return undefined;
    }
    if (applied.route === modelRoute) return undefined;
    modelRoute = applied.route;
    // #686 P1: quality advance must not inherit the prior resource-relay pool —
    // reselect from the new model's dispatch binding.
    currentBillingPool = billingPoolFromQuotaPool(
      poolForModelRef(modelRoute.slots.coder),
    );
    stepSpecs = stepSpecsForRoute(modelRoute);
    // #924: model change invalidates the prior Sandcastle session — next
    // coder seat establishes a new session (cannot resume across providers).
    if (
      coderSessionModel !== undefined &&
      stepSpecs.S2.model !== coderSessionModel &&
      stepSpecs.S5.model !== coderSessionModel
    ) {
      coderSessionId = undefined;
      coderSessionModel = undefined;
    }
    // Clear so the caller re-runs ensureRouteSmoke for the new coder slug
    // before its first dispatch (top-of-loop OR the S2/S5 advance path).
    routeSmokeChecked = false;
    if (applied.entry !== undefined) {
      console.info(
        `[orchestrator] Coder-Rec → ${applied.entry.id} (${applied.entry.slug})` +
          (nonConvergingRounds > 0
            ? ` after ${nonConvergingRounds} non-converging review round(s)`
            : ""),
      );
    }
    return applyRuntimeTightRoutePolicy(modelRoute, {
      interactive: process.stdin.isTTY === true && process.stdout.isTTY === true,
      warn: (message) => console.warn(`[orchestrator] ${message}`),
    });
  };

  const stopForCoderRecTightRoutePolicy = async (escalation: {
    readonly reason: string;
    readonly diagnosis: string;
  }): Promise<RunResult> => {
    const stopSummary = stopSummaryForStartupRouteFailure(escalation);
    // #899: this stop can fire MID-RUN (the S2/S5 advance path), not only at
    // startup. It used to return an inline RunResult with an in-memory-only
    // S8 — no disk row, no output — so the family saw a bare "failed", resume
    // could not classify the breakpoint, and every re-ignition replayed the
    // whole run from scratch. Terminal returns must speak and persist.
    console.error(
      `[orchestrator] ${escalation.reason}: ${escalation.diagnosis}`,
    );
    ledger.push({ step: "S8", stopSummary });
    await persistBestEffort(
      "S8",
      undefined,
      undefined,
      "escalate",
      undefined,
      undefined,
      "failure",
      stopSummary,
    );
    return {
      status: "escalate",
      errorPackage: {
        failedStep: "S0",
        reason: `${escalation.reason}: ${escalation.diagnosis}`,
      },
      stepLedger: ledger,
      stopSummary,
    };
  };

  /** #686 — apply a relay baton onto the wall-hit role slot (role-aware). */
  const applyRelayBaton = (baton: NextRelayBaton, wallStep?: StepId): void => {
    currentBillingPool = baton.pool;
    activeRelayStep = wallStep ?? "S2";
    const relaySlot = relaySlotForWallStep(wallStep ?? "S2");
    const slots = { ...modelRoute.slots };
    if (relaySlot === "reviewer") {
      slots.reviewer = baton.slug;
    } else if (relaySlot === "coderFix") {
      slots.coderFix = baton.slug;
      stickyRelayCoderFixSlug = baton.slug;
    } else {
      // S2/default — coder (+ coderFix) slot; sticky for resource relay only.
      modelRoute = withCoderSlot(modelRoute, baton.slug);
      stickyRelayCoderSlug = baton.slug;
      stepSpecs = stepSpecsForRoute(modelRoute);
      routeSmokeChecked = false;
      console.info(
        `[orchestrator] #686 relay baton → ${baton.modelId} (${baton.slug}) @ ${baton.pool}`,
      );
      return;
    }
    modelRoute = { ...modelRoute, slots };
    stepSpecs = stepSpecsForRoute(modelRoute);
    routeSmokeChecked = false;
    console.info(
      `[orchestrator] #686 relay baton → ${baton.modelId} (${baton.slug}) @ ${baton.pool}` +
        (wallStep !== undefined ? ` (slot for ${wallStep})` : ""),
    );
  };

  // #686 P1: count the chain from the FULL ledger (resume history + in-memory),
  // so post-handoff trim / re-feed cannot reset MAX_RELAY_HANDOFFS.
  const canRelayInProcess = (): boolean =>
    canRelayHandoff(mergeResumeLedgerHistory(resumeHistoryLedger, ledger));

  // Attempt markers belong to a dedicated durable ledger namespace, not the
  // canonical step-result ledger. Keep the live-process delta separately so
  // successful retries do not add duplicate worker rows to `RunResult.stepLedger`.
  const mechanicalRedispatchAttempts = new Map<SliceStepId, number>();

  const mechanicalRedispatchAttemptsFor = (step: SliceStepId): number => {
    const history = mergeResumeLedgerHistory(resumeHistoryLedger, ledger);
    let durableAttempts = 0;
    // A canonical completed row starts a new logical invocation.  Markers
    // before it have already been consumed by a successful invocation.
    for (let index = history.length - 1; index >= 0; index--) {
      const entry = history[index]!;
      if (entry.step === step && entry.event === undefined) break;
      // A relay baton re-enters the same step under a new worker/model scene.
      // Its prior crash streak is audit history, not the next invocation's
      // dispatch budget.
      if (entry.step === step && entry.event === "relay_baton_handoff") break;
      const isCurrentMarker =
        entry.step === "mechanical_redispatch_attempt" && entry.forStep === step;
      // Read r5 rows for crash-resume compatibility; new rows use the distinct
      // marker namespace above.
      const isLegacyMarker =
        entry.step === step && entry.event === "mechanical_redispatch_attempt";
      if (isCurrentMarker || isLegacyMarker) {
        durableAttempts = Math.max(
          durableAttempts,
          entry.mechanicalRedispatchAttempt ?? 0,
        );
      }
    }
    return Math.max(mechanicalRedispatchAttempts.get(step) ?? 0, durableAttempts);
  };

  const completeMechanicalRetryInvocation = (step: SliceStepId): void => {
    mechanicalRedispatchAttempts.delete(step);
  };

  const durableMechanicalRetryOptions = (
    step: SliceStepId,
    options: MechanicalRetryOptions = {},
  ): MechanicalRetryOptions => ({
    ...options,
    attemptsAlreadyUsed: mechanicalRedispatchAttemptsFor(step),
    onAttempt: async (attempt) => {
      await options.onAttempt?.(attempt);
      const marker: LedgerEntry = {
        step: "mechanical_redispatch_attempt",
        event: "mechanical_redispatch_attempt",
        forStep: step,
        mechanicalRedispatchAttempt: attempt,
      };
      mechanicalRedispatchAttempts.set(step, attempt);
      if (stateDir === undefined) return;
      await backend.writeLedger(
        {
          ...marker,
          sessionId,
          prompt_hash: await hashPrompt(undefined, step, backend),
          branchHEAD: await resolveBranchHEAD(),
          ts: new Date().toISOString(),
        },
        stateDir,
      );
    },
  });

  const modelRefForWallStep = (wallStep: StepId): string => {
    return modelRoute.slots[relaySlotForWallStep(wallStep)];
  };

  const modelIdForWallStep = (wallStep: StepId): string => {
    const modelRef = modelRefForWallStep(wallStep);
    return lookupCoderRosterEntry(modelRef)?.id ?? modelRef;
  };

  const resolveRelayPools = (
    limitedPool: BillingPoolId,
    resetAt: Date | undefined,
    /**
     * Quota-wall path only: promote route-smoke-passed pools to live so a 429
     * beyond T can apply a real baton without test-only `relayPools` injection.
     * Resource / mechanical-retry paths leave this false — their live evidence
     * is first-leg proof / hang probe, not smoke of unrelated route slots.
     */
    forQuotaWall = false,
  ): ReadonlyArray<BillingPoolEntry> => {
    if (forQuotaWall) wallHitBillingPools.add(limitedPool);
    return resolveRelayPoolsFromTable(
      limitedPool,
      resetAt,
      input.relayPools,
      forQuotaWall
        ? knownLiveBillingPoolsFromRoute(modelRoute)
        : undefined,
      forQuotaWall ? wallHitBillingPools : undefined,
    );
  };

  const hasExplicitRelayPools = input.relayPools !== undefined;

  const resolveResourceFailurePool = (input: {
    readonly modelRef: string;
    readonly knownPool?: BillingPoolId;
    readonly capacity: boolean;
  }): {
    readonly currentPool: BillingPoolId;
    readonly pools: ReadonlyArray<BillingPoolEntry>;
  } => {
    const inferredPool =
      billingPoolForModelRef(input.modelRef) ??
      billingPoolFromQuotaPool(poolForModelRef(input.modelRef));
    const configuredPools = resolveRelayPools(inferredPool, undefined);
    const confirmedPool =
      input.knownPool ??
      currentBillingPool ??
      findLiveBillingPoolForModel(configuredPools, input.modelRef);
    const currentPool = confirmedPool ?? inferredPool;
    // A first-leg capacity result comes from the currently dispatched model,
    // so it proves that its inferred billing pool is live. Keep an explicit
    // relay table authoritative, and keep later relay legs tied to their
    // recorded pool; only the default, unbatoned first leg gets this proof.
    const firstLegCapacityPoolIsLive =
      input.capacity &&
      confirmedPool === undefined &&
      !hasExplicitRelayPools;
    return {
      currentPool,
      pools: configuredPools.map((pool) => {
        if (pool.id !== currentPool) return pool;
        if (!input.capacity) return { ...pool, status: "dead" as const };
        return confirmedPool !== undefined || firstLegCapacityPoolIsLive
          ? { ...pool, status: "live" as const }
          : pool;
      }),
    };
  };

  const relayBillingPoolForDispatch = (
    dispatchStep: StepId,
  ): BillingPoolId | undefined =>
    activeRelayStep === dispatchStep ? currentBillingPool : undefined;
  const relayFocusForDispatch = (dispatchStep: StepId): string | undefined =>
    activeRelayStep === dispatchStep ? activeRelayFocusPath : undefined;
  const clearCompletedRelayState = (completedStep: StepId, completed: StepOutput | undefined): void => {
    if (
      activeRelayStep !== completedStep ||
      completed === undefined ||
      escalateOf(completed) !== undefined
    ) return;
    currentBillingPool = undefined;
    activeRelayFocusPath = undefined;
    activeRelayStep = undefined;
  };

  // #899: count COMPLETED S6 rounds only — monitor-spawn / bookkeeping event
  // rows share the S6 step id and were doubling one round into two (see
  // completedS6RoundsFromLedger).
  const coderRecRoundsFromLedger = (
    entries: ReadonlyArray<LedgerEntry>,
  ): number => completedS6RoundsFromLedger(entries);
  // Family-run context (ADR 0022 decision 2). Production always supplies this
  // for a child. Focused skeleton tests may omit it and cut from the test base;
  // S7 remains a local handoff in either case.
  const family = input.family;
  // The cut base: the family base in production, else the focused-test default.
  // This is the only place "main" is parameterised —
  // the Backend seam already takes base as a parameter (ADR 0017 §2); #293 just
  // feeds the family base instead of the hardcoded constant.
  const sliceBase = family !== undefined ? family.familyBase : SLICE_BASE;
  const ledger: LedgerEntry[] = [];

  // State threaded across steps within this run.
  let worktree: WorktreeHandle | undefined;
  let lastOutput: StepOutput | undefined;
  let pendingBlockingFindings: Finding[] = [];
  let pendingBlockingFindingIdentityKeys: string[] = [];
  /** Reviewer-declared open-count for S5/S6 (not findings-array length). */
  let pendingBlockingFindingCount = 0;
  let pendingRawReviewerArtifacts: WorkerLandingPayload["rawReviewerArtifacts"];
  /** Opaque continue_fixing scope for S5 landing (C-R4-2A); never filters cargo. */
  let pendingFixerFindingScope: FindingRepairScope | undefined;
  let findingDispositions: FindingDisposition[] = [];
  let lastReviewerStepId: StepId | undefined;
  let preexistingAssertionTouchedForReverify = false;
  let refusedFindingIdentityKeysForReverify: readonly string[] = [];
  // Preserve the full ledger for relay and resume accounting.
  let resumeHistoryLedger: ReadonlyArray<LedgerEntry> = [];

  function seedClassificationFromReviewerOutput(
    reviewerOutput: StepOutput | undefined,
    _afterFix: boolean,
  ): string[] {
    if (reviewerOutput?.kind !== "reviewer") return [];
    // Opaque cargo copy only — not a decode/validation boundary. Runner routes
    // by findingsCount and transports findings rows as-is; identity-key
    // derivation is the landing writer's job (dispatchWorker → fixer), not a
    // runner court (ADR 0131 / #899).
    pendingBlockingFindings = [...reviewerOutput.findings];
    pendingBlockingFindingIdentityKeys = [];
    // ADR 0131: declared count is the control signal; findings rows are cargo.
    pendingBlockingFindingCount = reviewerOutput.findingsCount;
    return [];
  }

  // ── #249: per-run session id + sibling state dir ──────────────────────────
  // sessionId: a stable identifier for this orchestrator invocation.
  // Using globalThis.crypto.randomUUID() — consistent with the rest of this
  // file's use of globalThis.crypto (e.g. globalThis.crypto.subtle.digest).
  //
  // #256: this is the run-level FALLBACK id. Agent steps record their REAL
  // per-step sandbox session id (surfaced by the seam extension, see
  // normalizeStepResult); runner-action steps (S0/S1/S4/S7/S8) and the
  // zero-container fake path — which carry no per-step sandbox session — fall
  // back to this run-level id.
  const sessionId = globalThis.crypto.randomUUID();
  // State directories deliberately survive and are deterministically derived
  // from an issue. Telemetry therefore needs a separate per-invocation key:
  // same-issue restarts must append a fresh environment row, never dedupe it.
  const runId = mintRunId();

  /**
   * Resolve the ledger's `branchHEAD` value (#256).
   *
   * Real Backend: the worktree HEAD commit SHA (`git rev-parse HEAD`) via the
   * optional `backend.worktreeHead`. Fallback (no worktree yet / no
   * `worktreeHead` on the Backend / it returns undefined / it throws): the
   * branch NAME, as in v0.1 — a ledger I/O helper must never abort the run on a
   * git read fault.
   */
  async function resolveBranchHEAD(): Promise<string> {
    if (worktree === undefined) return "";
    if (backend.worktreeHead !== undefined) {
      try {
        const sha = await backend.worktreeHead(worktree);
        if (sha !== undefined && sha.length > 0) {
          return sha;
        }
      } catch {
        // fall through to the branch-name fallback
      }
    }
    return worktree.branch;
  }

  // stateDir is resolved once the worktree is prepared (S1 sets it).
  // Until then, ledger entries for pre-S1 steps are buffered and flushed to
  // the confirmed stateDir after S1 completes.  This guarantees:
  //   (a) all entries go to the same single stateDir, and
  //   (b) stateDir is always a sibling of the real worktree (not provisional).
  let stateDir: string | undefined;

  // Buffer for entries emitted before stateDir is known (S0 only in v0.1).
  const pendingEntries: Array<PersistentLedgerEntry> = [];

  /**
   * Emit one persistent ledger entry.
   *
   * Before S1 (stateDir unknown): buffer the entry.
   * After S1 (stateDir known):    flush any buffered entries first, then write.
   */
  async function emitLedger(
    s: SliceStepId,
    output: StepOutput | undefined,
    promptFile: string | undefined,
    handoffStatus?: HandoffStatus,
    /**
     * #256: the REAL per-step sandbox session id for an agent step (from the
     * seam extension). When undefined, the run-level UUID fallback is recorded
     * (runner-action steps, or a fake Backend that returns a bare StepOutput).
     */
    stepSessionId?: string,
    findingDispositions?: ReadonlyArray<FindingDisposition>,
    escalationKind?: EscalationKind,
    stopSummary?: StopSummary,
    monitorHandle?: import("./types.js").WorkerMonitorHandle,
  ): Promise<void> {
    const ph = await hashPrompt(promptFile, s, backend);
    const branchHEAD = await resolveBranchHEAD();
    const entry = buildPersistentEntry({
      step: s,
      output,
      runId,
      sessionId: stepSessionId ?? sessionId,
      prompt_hash: ph,
      branchHEAD,
      ts: new Date().toISOString(),
      handoffStatus,
      escalationKind,
      findingDispositions,
      stopSummary,
      monitorHandle,
    });

    const mirrorInMemoryLedgerPersistedFields = (
      step: SliceStepId,
      fields: Pick<PersistentLedgerEntry, "ts" | "branchHEAD">,
    ): void => {
      for (let i = ledger.length - 1; i >= 0; i--) {
        if (ledger[i]!.step === step) {
          ledger[i] = { ...ledger[i]!, ...fields };
          break;
        }
      }
    };

    if (stateDir === undefined) {
      // stateDir not yet known — buffer until S1 resolves the worktree path.
      pendingEntries.push(entry);
      return;
    }

    // stateDir is now known: drain the buffer one entry at a time, removing
    // each item ONLY AFTER its write succeeds.  If writeLedger rejects, the
    // remaining entries stay in the buffer — they are never silently dropped.
    while (pendingEntries.length > 0) {
      const buffered = pendingEntries[0]!;
      await backend.writeLedger(buffered, stateDir);
      pendingEntries.shift();
      if (isStepId(buffered.step)) {
        mirrorInMemoryLedgerPersistedFields(buffered.step, {
          ts: buffered.ts,
          branchHEAD: buffered.branchHEAD,
        });
      }
    }
    await backend.writeLedger(entry, stateDir);
    mirrorInMemoryLedgerPersistedFields(s, {
      ts: entry.ts,
      branchHEAD: entry.branchHEAD,
    });
  }

  /**
   * #684 R2: persist the monitor handle AT SPAWN TIME (bookkeeping event, not a
   * completed step). Hang judge/kill/resume can rebuild via
   * {@link monitorHandleFromLedger} while the worker is still running.
   */
  async function persistMonitorHandleAtSpawn(
    s: SliceStepId,
    handle: import("./types.js").WorkerMonitorHandle,
  ): Promise<void> {
    if (stateDir === undefined) return;
    const ph = await hashPrompt(undefined, s, backend);
    const branchHEAD = await resolveBranchHEAD();
    const entry: PersistentLedgerEntry = {
      step: s,
      event: "worker_monitor_spawned",
      runId,
      sessionId,
      prompt_hash: ph,
      branchHEAD,
      ts: new Date().toISOString(),
      monitorHandle: handle,
    };
    ledger.push({
      step: s,
      event: "worker_monitor_spawned",
      monitorHandle: handle,
    });
    await backend.writeLedger(entry, stateDir);
  }

  /**
   * Best-effort persist for the error path (#3). Unlike emitLedger, a
   * writeLedger failure HERE is swallowed: we are already terminating with an
   * error, so a secondary persistence failure must not mask the original cause
   * nor raw-reject. The in-memory ledger still records the step regardless.
   *
   * integ-cmr m2 r1 (Finding 1): `handoffStatus` is threaded through so the
   * error-path terminal S8 is persisted TAGGED (handoffStatus:'error'). Without
   * the tag, planResume Case 3a (which only reports a terminal status when
   * lastEntry.handoffStatus !== undefined) falls through to Case 3b/4 and routes
   * from the prior NON-S8 step — re-entering the fix loop on a no-progress bail,
   * or reporting SUCCESS for a push-fail. The terminal status must be recorded
   * on disk, not inferred. Non-terminal best-effort persists (the failing step)
   * pass handoffStatus=undefined, matching emitLedger's "undefined for non-S8".
   */
  async function persistBestEffort(
    s: SliceStepId,
    output: StepOutput | undefined,
    promptFile: string | undefined,
    handoffStatus?: HandoffStatus,
    /**
     * #331: the real per-step worker session id, threaded to emitLedger's 5th
     * arg so an escalated worker's session id is persisted as the ledger
     * `sessionId` (resume truth) — NOT lost (codex cmr R6 finding). Undefined for
     * the normal error path (run-level UUID fallback applies, as before).
     */
    stepSessionId?: string,
    findingDispositions?: ReadonlyArray<FindingDisposition>,
    escalationKind?: EscalationKind,
    stopSummary?: StopSummary,
  ): Promise<void> {
    try {
      await emitLedger(
        s,
        output,
        promptFile,
        handoffStatus,
        stepSessionId,
        findingDispositions,
        escalationKind,
        stopSummary,
      );
    } catch {
      // Swallow: error termination must not be derailed by a ledger I/O fault.
    }
  }

  /**
   * Build an S8(status=error) termination from the failing step + caught error.
   *
   * #3: records BOTH the failing step and the terminal S8 in the in-memory
   * ledger AND persists them (best-effort) to the sibling state dir, so a
   * resume reading the PERSISTED ledger sees the error termination instead of
   * the failing step + S8 vanishing.
   *
   * PRE-WORKTREE failures are an unpersistable special case (integ-cmr base r2,
   * finding C): before the worktree exists there is no sibling stateDir, so
   * persistence is inherently impossible (the resume contract needs a worktree
   * sibling dir). This covers BOTH:
   *   - S0 fetchIssueMeta throw, AND
   *   - S1 PRE-worktree throws: fetchIssueSnapshot / prepareWorktree (which run
   *     BEFORE deriveStateDir sets stateDir).
   * In all these the in-memory ledger still records S8 and the run still returns
   * S8(error), but NOTHING is persisted. Only POST-worktree S1 (writeSnapshot,
   * which runs after stateDir is fixed) and later steps persist their error
   * termination. So this contract does NOT promise "every S1 throw is persisted"
   * — only post-worktree ones.
   */
  async function errorTermination(
    failedStep: SliceStepId,
    err: unknown,
    opts?: {
      recordInMemory?: boolean;
      output?: StepOutput;
      findingDispositions?: ReadonlyArray<FindingDisposition>;
      stopSummary?: StopSummary;
    },
  ): Promise<RunResult> {
    // integ-cmr base r2 (D): split the two concerns the old single
    // `recordFailingStep` flag conflated. `recordInMemory` controls only the
    // in-memory push (skip it when the caller already pushed the failing step —
    // the writeLedger-failure path does). The best-effort PERSIST of the failing
    // step is UNCONDITIONAL: a transient ledger write fault must not leave the
    // persisted ledger missing the failing step (resume reads the persisted
    // ledger, so disk and memory must agree on the error path).
    //
    // integ-cmr base r1 (F3): the best-effort re-persist must carry the failing
    // step's OUTPUT. The old call passed output=undefined, so on a writeLedger
    // fault the DISK ledger entry for an agent step lost its output (in-memory
    // kept it) — and resume reads the disk ledger, so a crash there would resume
    // from an output-less step (e.g. a reviewer S3 with no findings). The
    // caller threads the in-flight output through `opts.output` so disk and
    // memory agree on the error path.
    const recordInMemory = opts?.recordInMemory ?? true;
    const reason = err instanceof Error ? err.message : String(err);
    const errorPackage: ErrorPackage = {
      failedStep,
      reason,
      branchHead: worktree?.branch,
    };
    const stopSummary = opts?.stopSummary ?? stopSummaryForErrorPackage(errorPackage);

    // Record the failing step. The in-memory push is skipped when the caller
    // already pushed it (recordInMemory:false) or it is S8 itself; the
    // best-effort persist is still attempted so disk and memory agree (D),
    // carrying the failing step's output (F3).
    if (failedStep !== "S8") {
      if (recordInMemory) {
        ledger.push({
          step: failedStep,
          ...(opts?.output !== undefined ? { output: opts.output } : {}),
          ...(opts?.findingDispositions !== undefined
            ? { findingDispositions: opts.findingDispositions }
            : {}),
        });
      }
      await persistBestEffort(
        failedStep,
        opts?.output,
        undefined,
        undefined,
        undefined,
        opts?.findingDispositions,
        undefined,
        undefined,
      );
    }

    // Terminal S8 entry — in-memory + persisted. The PERSISTED entry is TAGGED
    // with the terminal status (integ-cmr m2 r1, Finding 1): errorTermination is
    // always an ERROR handoff, so the disk S8 must carry handoffStatus:'error';
    // a re-feed then reports the true error via planResume Case 3a instead of
    // falling through to Case 3b/4 (which would re-route from the prior NON-S8
    // step — reporting a spurious success). The in-memory entry stays untagged,
    // matching the normal handoff path (only the disk ledger is the resume truth;
    // the in-memory ledger is the live result).
    ledger.push({ step: "S8", stopSummary });
    await persistBestEffort(
      "S8",
      undefined,
      undefined,
      "error",
      undefined,
      undefined,
      undefined,
      stopSummary,
    );

    // An error abort returns whatever deferred findings were already collected
    // (typically none before S4). ADR 0030 keeps per-slice review/fix work in
    // runner-visible S3/S4/S5/S6 steps; deferral tracking belongs to the later
    // family/integrated gates, not this error path.
    return {
      status: "error",
      errorPackage,
      stepLedger: ledger,
      stopSummary,
    };
  }
  // ─────────────────────────────────────────────────────────────────────────

  /** Transport a child worker's decision/failure park without judging its prose. */
  async function escalateTermination(
    failedStep: SliceStepId,
    escalation: Escalation,
    sessionId?: string,
    escalationKind: EscalationKind = "decision",
    output?: StepOutput,
    stopSummaryOverride?: StopSummary,
  ): Promise<RunResult> {
    const stopSummary = stopSummaryOverride ?? stopSummaryForEscalation(escalation);
    if (failedStep !== "S8") {
      ledger.push({
        step: failedStep,
        ...(output !== undefined ? { output } : {}),
        ...(sessionId !== undefined ? { sessionId } : {}),
      });
      // Persist the failing step carrying its REAL worker session id (5th arg —
      // NOT the promptFile slot; codex cmr R6 finding), so a re-feed reading the
      // persisted ledger has the true session id for the human-answer resume.
      //
      await persistBestEffort(failedStep, output, undefined, undefined, sessionId);
    }
    ledger.push({ step: "S8", stopSummary });
    await persistBestEffort(
      "S8",
      undefined,
      undefined,
      "escalate",
      undefined,
      undefined,
      escalationKind,
      stopSummary,
    );
    return {
      status: "escalate",
      // Surface the escalation as the error package so the caller can read the
      // reason/diagnosis (resume指引) — same diagnostic channel, escalate status.
      errorPackage: {
        failedStep,
        reason: `${failedStep} worker escalated: ${escalation.reason} — ${escalation.diagnosis}`,
        branchHead: worktree?.branch,
      },
      stepLedger: ledger,
      stopSummary,
    };
  }
  // ─────────────────────────────────────────────────────────────────────────

  // ── #255: idempotent resume ───────────────────────────────────────────────
  // Before anything else, check whether this issue has resume residue (an
  // existing resident worktree + persisted ledger from a crash or an escalate).
  // Crash-resume and escalate-resume share this ONE machine: read the ledger
  // (resume truth), reuse the worktree, clean uncommitted residue, and continue
  // from the recorded breakpoint — no re-cut from S0, no re-running done steps.
  //
  // findResumeState is consulted FIRST: a resumed run already passed the S0
  // gate on its first pass, so it must not re-gate. A backend transport failure
  // here becomes an error handoff (consistent with #252), via errorTermination
  // (base integ-cmr): no worktree exists yet, so — like the S0 fetch path —
  // nothing is persistable, but the in-memory S8 + S8(error) result are still
  // recorded so the caller gets a clean error package rather than a raw reject.
  let resumeState: ResumeState | undefined;
  try {
    // #884: reconcile = resume-residue / ledger discovery before productive work.
    logDriverStage("reconcile", `issue #${issueNumber}`);
    resumeState = await backend.findResumeState(issueNumber);
  } catch (err) {
    return await errorTermination("S0", err);
  }
  const recordedRouteDegradations = new Set(
    (resumeState?.ledger ?? [])
      .filter((entry) => entry.event === "route_degraded")
      .map((entry) => `${entry.droppedLeg}\0${entry.reason}`),
  );

  // The runner drives the sequence; the agent never picks the next step.
  let step: SliceStepId = "S0";

  // ── ADR 0030: runner-visible review/fix loop, no blind round cap ───────────
  // The runner dispatches S2/S3/S5/S6 as separate ledger-visible worker
  // boundaries. S4 classifies reviewer findings and routes to S5 while blocking
  // work remains, but there is no fixed "count to N and stop" convergence cap:
  // only structured worker outputs or explicit escalations decide progress.

  // ── #255: idempotent resume from the recorded breakpoint ───────────────────
  // When set, the next dispatch of `resumeFor.step` must use the original agent
  // session (Sandcastle `resumeSession`) rather than a fresh `run()`. Used for
  // the escalate-resume case (the human answered; the build worker finishes in
  // its original memory-bearing session). Cleared after the step is dispatched once.
  let resumeFor: { step: SliceStepId; sessionId: string } | undefined;
  let resumedEscalationAnswer: EscalationAnswerEvent | undefined;
  // #684 R2: monitor handle rebuilt from ledger via monitorHandleFromLedger on resume.
  let resumeMonitorHandle:
    | import("./types.js").WorkerMonitorHandle
    | undefined;

  /** #884: emit dispatch stage line once when first productive worker is entered. */
  let dispatchStageLogged = false;

  const ensureRouteSmoke = async (): Promise<RunResult | undefined> => {
    if (typeof backend.smokeModelRoute !== "function") {
      const reason =
        "route smoke executor is required before dispatch; backend did not provide smokeModelRoute";
      return {
        status: "error",
        errorPackage: { failedStep: "S0", reason },
        stepLedger: [],
        stopSummary: infraFailureStopSummary({
          summary: reason,
          repairHint: "provide a real model×pipe smoke executor before dispatching workers",
        }),
      };
    }

    let currentCliVersions: Readonly<Record<string, string | undefined>>;
    try {
      logDriverStage("smoke-k", `route=${modelRoute.routeName}`);
      currentCliVersions = backend.currentCliVersions
        ? await backend.currentCliVersions(
            modelRoute,
            activeRelayStep === undefined ? undefined : currentBillingPool,
            activeRelaySmokeEntryKey(activeRelayStep, modelRoute),
          )
        : {};
      modelRoute = await backend.smokeModelRoute(
        modelRoute,
        currentCliVersions,
        activeRelayStep === undefined ? undefined : currentBillingPool,
        activeRelaySmokeEntryKey(activeRelayStep, modelRoute),
      );
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      return {
        status: "error",
        errorPackage: { failedStep: "S0", reason: `route smoke failed: ${reason}` },
        stepLedger: [],
        stopSummary: infraFailureStopSummary({
          summary: `route smoke failed: ${reason}`,
          repairHint: "repair the selected model×pipe tool smoke before dispatching workers",
        }),
      };
    }
    const degradation = degradeOptionalRouteSmokeFailures(modelRoute);
    modelRoute = degradation.route;
    const smokeFailure = routeSmokeFailure(
      modelRoute,
      Date.now(),
      undefined,
      currentCliVersions,
    );
    if (smokeFailure !== undefined) {
      return {
        status: "error",
        errorPackage: { failedStep: "S0", reason: smokeFailure },
        stepLedger: [],
        stopSummary: infraFailureStopSummary({
          summary: smokeFailure,
          repairHint: "rerun the route smoke or repair the selected model×pipe",
        }),
      };
    }
    for (const dropped of degradation.dropped) {
      console.error(
        `[orchestrator] OPTIONAL CMR LEG DROPPED: ${dropped.slug}: ${dropped.reason}`,
      );
      const degradationKey = `${dropped.slug}\0${dropped.reason}`;
      if (!recordedRouteDegradations.has(degradationKey)) {
        const entry: PersistentLedgerEntry = {
          step: "S0",
          event: "route_degraded",
          droppedLeg: dropped.slug,
          reason: dropped.reason,
          runId,
          sessionId,
          prompt_hash: await hashPrompt(undefined, "S0", backend),
          branchHEAD: await resolveBranchHEAD(),
          ts: new Date().toISOString(),
        };
        if (stateDir === undefined) pendingEntries.push(entry);
        else await backend.writeLedger(entry, stateDir);
        recordedRouteDegradations.add(degradationKey);
      }
    }
    if (degradation.dropped.length > 0) {
      console.info(
        `[orchestrator] effective model route lineup\n${printableRouteLineup(modelRoute)}`,
      );
    }
    routeSmokeChecked = true;
    return undefined;
  };

  if (resumeState !== undefined && resumeState.ledger.length > 0) {
    // Reuse the resident worktree (NO re-cut) and fix the sibling stateDir.
    worktree = resumeState.worktree;
    stateDir = resumeState.stateDir;
    let resumeLedger = resumeState.ledger;
    if (input.repairIntent !== undefined) {
      const repairIntentEntry: PersistentLedgerEntry = {
        step: "S4",
        event: input.repairIntent.event,
        intent: input.repairIntent.intent,
        source: input.repairIntent.source,
        ts: input.repairIntent.ts,
        ...(input.repairIntent.findingIdentityKey !== undefined
          ? { findingIdentityKey: input.repairIntent.findingIdentityKey }
          : {}),
        ...(input.repairIntent.findingScope !== undefined
          ? { findingScope: input.repairIntent.findingScope }
          : {}),
        ...(input.repairIntent.reason !== undefined
          ? { reason: input.repairIntent.reason }
          : {}),
        sessionId,
        prompt_hash: await hashPrompt(undefined, "S4", backend),
        branchHEAD: await resolveBranchHEAD(),
      };
      try {
        await backend.writeLedger(repairIntentEntry, stateDir);
      } catch (err) {
        return await errorTermination("S4", err);
      }
      resumeLedger = [...resumeLedger, repairIntentEntry];
    }
    const plan = planResume(resumeLedger);
    resumeHistoryLedger = resumeLedger;

    // #684 R2: production call site for monitorHandleFromLedger — rebuild any
    // in-flight CLI monitor handle from the persisted ledger so hang judge/kill
    // can resume without global process-name matching.
    resumeMonitorHandle = (() => {
      for (let i = resumeLedger.length - 1; i >= 0; i--) {
        const candidate = resumeLedger[i]!;
        // Completed step entries also carry the handle for auditability. Only
        // the spawn bookkeeping event denotes an in-flight worker; otherwise a
        // later resume could inherit a stale handle from the previous step.
        if (candidate.event !== "worker_monitor_spawned") continue;
        const superseded = resumeLedger
          .slice(i + 1)
          .some(
            (entry) =>
              entry.step === candidate.step &&
              entry.event !== "worker_monitor_spawned",
          );
        if (superseded) continue;
        const rebuilt = monitorHandleFromLedger(candidate);
        if (rebuilt !== undefined) return rebuilt;
      }
      return undefined;
    })();

    // Seed the in-memory ledger with prior progress so committed work is
    // preserved and the prior steps are NOT re-run.
    for (const e of plan.priorLedger) ledger.push(e);
    lastOutput = plan.lastOutput;

    // #877: persisted S4 boundaries are replayed from reviewer findings-count
    // only. Each S4 replaces the pending blocker set with that reviewer's
    // `findings[]`; prose dispositions do not preserve or reopen findings.
    // #899: also rebuild raw reviewer artifact pointers so a crash/resume after
    // S4 still hands the fixer host paths (materialised at landing).
    const replayedS4 = replayS4FindingsCountState(plan.priorLedger);
    pendingBlockingFindings = [...replayedS4.blocking];
    pendingBlockingFindingIdentityKeys = [...replayedS4.blockingIdentityKeys];
    pendingBlockingFindingCount = replayedS4.blockingFindingCount;
    findingDispositions = [...replayedS4.findingDispositions];
    pendingRawReviewerArtifacts = replayedS4.rawReviewerArtifacts;
    lastReviewerStepId = lastReviewerStep(plan.priorLedger);
    // #677: rebuild S5→S6 reverify locals after crash/restart. Refuse keys and
    // the assertion-touch signal live only in process memory during a live run;
    // resume recomputes them from the persisted S5 coder row + ledger HEADs.
    const rebuilt = rebuildS5ReverifySignalsFromLedger(
      plan.priorLedger,
      worktree,
    );
    preexistingAssertionTouchedForReverify =
      rebuilt.preexistingAssertionTouched;
    refusedFindingIdentityKeysForReverify =
      rebuilt.refusedFindingIdentityKeys;

    // #924: rebuild coder session continuity from the last S2/S5 ledger row so
    // crash/re-feed still resumes the same agent session when models match.
    for (let i = plan.priorLedger.length - 1; i >= 0; i -= 1) {
      const entry = plan.priorLedger[i]!;
      if (
        (entry.step === "S2" || entry.step === "S5") &&
        typeof entry.sessionId === "string"
      ) {
        coderSessionId = entry.sessionId;
        coderSessionModel =
          entry.step === "S5" ? stepSpecs.S5.model : stepSpecs.S2.model;
        break;
      }
    }

    if (plan.terminalStatus !== undefined) {
      // The prior run already reached a terminal handoff that is NOT being
      // re-opened. Re-feeding is a pure status report — no worktree mutation,
      // so no destructive cleanup is run here (a cleanup failure must not flip
      // an already-finished run's reported status). Report the
      // TRUE terminal status (success / error / escalate), never a hardcoded
      // success (#255: a prior error/escalate must not masquerade as success).
      if (plan.terminalStatus === "error") {
        const reason =
          "prior run terminated with an error handoff (re-fed after completion)";
        const errorPackage: ErrorPackage = {
          failedStep: lastAgentStep(plan.priorLedger) ?? "S8",
          reason,
          branchHead: worktree.branch,
        };
        const stopSummary =
          latestLedgerStopSummary(ledger) ?? stopSummaryForErrorPackage(errorPackage);
        return {
          status: "error",
          errorPackage,
          stepLedger: ledger,
          stopSummary,
        };
      }
      const stopSummary: StopSummary =
        plan.terminalStatus === "success"
          ? {
              reason: "already_done",
              summary: "prior run already reached a success handoff",
            }
          : latestLedgerStopSummary(ledger) ?? {
              reason: "spec_conflict",
              summary: "prior run is paused at an unanswered escalation",
              repairHint: "answer the escalation and rerun",
            };
      return {
        status: plan.terminalStatus,
        branch: plan.terminalStatus === "success" ? worktree.branch : undefined,
        stepLedger: ledger,
        stopSummary,
      };
    }

    // #661 / #686 P0: NEVER destroy the worker scene on resume. Reading/comparing
    // HEADs is legal; destructive reset/cleanup is not — uncommitted work + partial
    // commits + `.relay-focus.md` are the payload. Relay state is read from the
    // FULL resume ledger preserves every relay marker.
    // ADR 0030: resume continues from the recorded runner-visible boundary. If
    // that boundary follows S4, the classification state was rebuilt above from
    // the persisted reviewer output.

    // Continue from the recorded breakpoint.
    step = plan.resumeStep;
    if (typeof plan.resumeSessionId === "string") {
      resumeFor = { step: plan.resumeStep, sessionId: plan.resumeSessionId };
    }
    resumedEscalationAnswer = plan.escalationAnswer;
    // C-R4-2A / #899: consume plan.continueFixingRepair — opaque findingScope
    // into S5 landing only. Runner still does not filter blockingFindings.
    const repairScope = plan.continueFixingRepair?.event.findingScope;
    if (repairScope !== undefined) {
      pendingFixerFindingScope = repairScope;
    }

    // #767: resume skips S0/S1, so re-fetch the issue body and apply Coder-Rec
    // (including the S6-count advance position from the restored ledger) before
    // the first dispatch / top-of-loop smoke. Without this, applyCoderRecToRoute
    // sees undefined body → skippedForMissingMarking → silent preset revert.
    // Coder-Rec is OPTIONAL: re-fetch failures must degrade safely (try meta,
    // then snapshot) — never errorTerminate / poison the resume terminal state.
    try {
      const meta = await backend.fetchIssueMeta(issueNumber);
      if (typeof meta.body === "string" && meta.body.length > 0) {
        coderRecIssueBody = meta.body;
      }
    } catch {
      // fall through to snapshot
    }
    if (
      (coderRecIssueBody === undefined || coderRecIssueBody.length === 0)
    ) {
      try {
        const snapshot = await backend.fetchIssueSnapshot(issueNumber);
        if (snapshot.body.length > 0) {
          coderRecIssueBody = snapshot.body;
        }
      } catch {
        // fall through — continue with route preset
      }
    }
    if (coderRecIssueBody === undefined || coderRecIssueBody.length === 0) {
      console.info(
        "[orchestrator] Coder-Rec resume re-fetch failed; continuing with route preset",
      );
    }
    const coderRecPolicy = await applyCoderRecSelection(
      coderRecRoundsFromLedger(ledger.filter((entry) => isStepId(entry.step))),
    );
    if (coderRecPolicy?.kind === "stop") {
      return await stopForCoderRecTightRoutePolicy(coderRecPolicy.escalation);
    }
    const relayResume = resumeRelayFromLedger(
      resumeLedger.filter(
        (entry): entry is PersistentLedgerEntry & { readonly step: StepId } =>
          isStepId(entry.step),
      ),
      plan.resumeStep,
    );

    // #686 — after #767 has rebuilt the base Coder-Rec route, resume from a
    // recorded baton before re-entering the interrupted step.
    if (relayResume !== undefined) {
      const batonEntry = lookupCoderRosterEntry(relayResume.toModelId);
      applyRelayBaton(
        {
          modelId: relayResume.toModelId,
          slug: batonEntry?.slug ?? relayResume.toModelId,
          pool: relayResume.toPool as BillingPoolId,
        },
        plan.resumeStep,
      );
      if (worktree.path !== undefined) {
        const focus = join(worktree.path, RELAY_FOCUS_FILENAME);
        if (existsSync(focus)) activeRelayFocusPath = focus;
      }
    }
  }

  // The step machine has no fixed bound: route() always terminates the run via a
  // handoff (success/escalate/error). ADR 0030 makes the per-slice review/fix
  // loop visible in S3/S4/S5/S6, but still rejects a blind round cap; a `for (;;)`
  // keeps the absence of any "数到 N 就停" cap explicit (US#18).
  orchestratorStepLoop: for (;;) {
    if (!routeSmokeChecked && step !== "S0") {
      const smokeResult = await ensureRouteSmoke();
      if (smokeResult !== undefined) return smokeResult;
    }
    let output: StepOutput | undefined;
    // promptFile for the current step (agent steps only; undefined for runner actions).
    let promptFile: string | undefined;
    // #256: the REAL per-step sandbox session id, captured from the seam
    // extension (runStep/resumeSession → StepResult). Undefined for runner
    // actions and for a fake Backend that returns a bare StepOutput → the ledger
    // records the run-level UUID fallback for those.
    let stepSessionId: string | undefined;
    // #684: monitor handle from production CLI dispatch (dispatchWorkerWithMonitor),
    // when the worker was spawned as a host-side CLI process. Persisted on the
    // ledger so resume can rebuild alive/idle/kill judgment without global pgrep.
    // Seed from resume rebuild (monitorHandleFromLedger) until a fresh spawn
    // overwrites via onMonitorHandleSpawned.
    let stepMonitorHandle: import("./types.js").WorkerMonitorHandle | undefined;
    if (resumeMonitorHandle?.stepId === step) {
      stepMonitorHandle = resumeMonitorHandle;
      // Consume resume handle once so a later step does not inherit a stale one.
      resumeMonitorHandle = undefined;
    }

    switch (step) {
      case "S0": {
        // S0 input_gate — runner action. Read lightweight metadata (the backend
        // `gh` call is wrapped so a transport failure becomes an error handoff,
        // #252), then enforce the accept condition (ADR 0018 / #248):
        //   (a) ready-for-agent label
        //   (b) no sub-issues (leaf slice, not a parent/epic)
        //   (c) all blocked_by dependencies are closed
        // A gate violation terminates as structured S8(error): the runner still
        // stops before preparing a worktree or dispatching an agent step, but AFK
        // callers get the unified terminal result / stop summary instead of a raw
        // process error.
        //
        // NOTE: a `## Agent Brief` is deliberately NOT a gate (design decision —
        // a `to-issues` slice may not carry that section, and the tool must not be
        // rigid about it). S1 loads the WHOLE issue (body + comments) for the coder;
        // the brief, when present, is just the most-authoritative part of that.
        let meta: IssueMeta;
        try {
          // #884: admission = S0 input gate / live issue metadata fetch.
          logDriverStage("admission", `issue #${issueNumber}`);
          meta = await backend.fetchIssueMeta(issueNumber);
        } catch (err) {
          // No worktree yet → no sibling stateDir → cannot persist (inherent:
          // the resume contract needs a worktree's sibling dir). errorTermination
          // records the in-memory S8 and persists only if stateDir is resolved.
          return await errorTermination("S0", err);
        }

        if (meta.isClosed) {
          // #2: a CLOSED issue is already done — admitting it would spin a coder on
          // a finished slice (the dogfood pulled closed game issues). Fail-closed,
          // like the other three gate conditions.
          return await errorTermination("S0", new Error(
            `S0 input gate: issue #${issueNumber} is CLOSED. ` +
              `Feed an open, ready-for-agent slice; a closed issue is already done.`,
          ));
        }

        if (!meta.isReadyForAgent) {
          return await errorTermination("S0", new Error(
            `S0 input gate: issue #${issueNumber} is not labelled ready-for-agent. ` +
              `Triage the issue and apply the label before running the orchestrator.`,
          ));
        }

        if (meta.hasSubIssues) {
          return await errorTermination("S0", new Error(
            `S0 input gate: issue #${issueNumber} is a parent issue (it has sub-issues). ` +
              `Feed a leaf slice issue, not a parent/epic.`,
          ));
        }

        // #294 / ADR 0022 decision 6③: the blocked_by gate's OPEN set. In a
        // FAMILY run the child's blockers are merged into the LOCAL family base by
        // the commander, but the blocker's GitHub issue need not be `closed` — so
        // a blocker GitHub still reports OPEN may already be ledger-merged. The
        // commander hands that ledger-merged set down via `family.mergedBlockers`;
        // those are SATISFIED, so a just-released child is not re-rejected by its
        // own S0 (the agy R2实锤 deadlock). This is an ADDED family-mode derivation
        // that ONLY narrows the set: focused tests without `family` have an empty
        // `mergedBlockers`, so `openBlockedBy` below is byte-for-byte
        // `meta.openBlockedBy` and the original GitHub-closed gate is unchanged. A
        // blocker NOT ledger-merged (e.g. an external dependency) stays open and
        // still rejects.
        const ledgerMergedBlockers = new Set(family?.mergedBlockers ?? []);
        const openBlockedBy =
          ledgerMergedBlockers.size === 0
            ? meta.openBlockedBy
            : meta.openBlockedBy.filter((n) => !ledgerMergedBlockers.has(n));

        if (openBlockedBy.length > 0) {
          const blockers = openBlockedBy.map((n) => `#${n}`).join(", ");
          return await errorTermination("S0", new Error(
            `S0 input gate: issue #${issueNumber} is blocked by upstream issues that are still open: ${blockers}. ` +
              `Merge the upstream changes before running.`,
          ));
        }

        // #767: apply Coder-Rec BEFORE the S0 smoke so we smoke the final
        // route once (not the preset, then a full re-smoke after mutation).
        // Mid-loop advance still re-smokes via the S2/S5 path below.
        coderRecIssueBody = meta.body;
        const coderRecPolicy = await applyCoderRecSelection(0);
        if (coderRecPolicy?.kind === "stop") {
          return await stopForCoderRecTightRoutePolicy(coderRecPolicy.escalation);
        }

        const smokeResult = await ensureRouteSmoke();
        if (smokeResult !== undefined) return smokeResult;

        break;
      }

      case "S1": {
        // S1 load_context — runner action: full snapshot → resident worktree
        // (base=`sliceBase`: family base in production) → write snapshot in.
        //
        // integ-cmr base r2 (C): the first two S1 sub-steps run BEFORE the
        // worktree exists, so there is no sibling stateDir yet — their error
        // terminations are UNPERSISTABLE (same special case as S0 fetch). Only
        // writeSnapshot below (after deriveStateDir) persists. This contract
        // does NOT claim "every S1 throw is persisted".
        let snapshot: IssueSnapshot;
        try {
          snapshot = await backend.fetchIssueSnapshot(issueNumber);
        } catch (err) {
          // PRE-worktree throw → unpersistable; S8(error) in-memory only.
          return await errorTermination("S1", err);
        }
        try {
          worktree = await backend.prepareWorktree(issueNumber, sliceBase);
        } catch (err) {
          // PRE-worktree throw → unpersistable; S8(error) in-memory only.
          return await errorTermination("S1", err);
        }
        // Fix the stateDir to be a true sibling of the worktree root (#249) as
        // soon as the worktree exists — BEFORE writeSnapshot — so that even a
        // writeSnapshot failure can persist its error termination to the ledger
        // (#3: error paths must persist, not vanish on resume).
        stateDir = deriveStateDir(worktree.path, issueNumber);
        const sourceAuthFailure = untrustedExecutableInstructionSummary(snapshot);
        if (sourceAuthFailure !== undefined) {
          return await errorTermination(
            "S1",
            new Error(`source authentication failed: ${sourceAuthFailure.summary}`),
            { stopSummary: sourceAuthFailure },
          );
        }
        try {
          await backend.writeSnapshot(worktree, snapshot);
        } catch (err) {
          return await errorTermination("S1", err);
        }
        // #767: if S0 lacked a body (lightweight fake / older meta), take it
        // from the S1 snapshot and apply Coder-Rec before S2.
        if (
          (coderRecIssueBody === undefined || coderRecIssueBody.length === 0) &&
          snapshot.body.length > 0
        ) {
          coderRecIssueBody = snapshot.body;
          const coderRecPolicy = await applyCoderRecSelection(
            coderRecRoundsFromLedger(ledger),
          );
          if (coderRecPolicy?.kind === "stop") {
            return await stopForCoderRecTightRoutePolicy(coderRecPolicy.escalation);
          }
        }
        break;
      }

      case "S2":
      case "S3":
      case "S5":
      case "S6": {
        // ADR 0030 productive steps:
        //   S2 coder implement, S3 fresh read-only review, S5 coder fix,
        //   S6 fresh read-only full-diff re-review.
        // #924: S2 establishes a coder session; S5 rounds resume it (same
        // model). Crash/escalate `resumeFor` still wins when set. Reviewer
        // seats (S3/S6) stay fresh every round.
        if (!dispatchStageLogged) {
          logDriverStage("dispatch", `step=${step}`);
          dispatchStageLogged = true;
        }
        if (worktree === undefined) {
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
        // #767: before each coder dispatch, re-select from Coder-Rec using the
        // number of completed S6 fix rounds as the non-convergence counter.
        // Mid-loop advance clears routeSmokeChecked — re-smoke here because the
        // top-of-loop check already ran for this iteration.
        if (step === "S2" || step === "S5") {
          const coderRecPolicy = await applyCoderRecSelection(
            coderRecRoundsFromLedger(ledger),
          );
          if (coderRecPolicy?.kind === "stop") {
            return await stopForCoderRecTightRoutePolicy(coderRecPolicy.escalation);
          }
          if (!routeSmokeChecked) {
            const smokeResult = await ensureRouteSmoke();
            if (smokeResult !== undefined) return smokeResult;
          }
        }
        promptFile = stepSpecs[step].promptFile;
        const expectedKind = stepSpecs[step].role as "coder" | "reviewer";
        let stepTelemetryDir: string | undefined;
        try {
          stepTelemetryDir = backend.resolveTelemetryDir?.({ runId, worktree, stateDir });
        } catch (err) {
          console.warn(
            `[orchestrator] telemetry dir resolution failed (fail-open): ${
              err instanceof Error ? err.message : String(err)
            }`,
          );
        }
        const coderHeadBeforeStep = expectedKind === "coder"
          ? gitHead(worktree)
          : undefined;
        let commitTelemetryWorker:
          | { readonly stepId: string; readonly modelSlug: string }
          | undefined;
        try {
          let resumeSessionId: string | undefined;
          if (resumeFor !== undefined && resumeFor.step === step && typeof resumeFor.sessionId === "string") {
            resumeSessionId = resumeFor.sessionId;
            resumeFor = undefined;
          } else if (
            // #924: normal S2→S5 continuity (and multi-round S5) resumes the
            // retained coder session when the seat model still matches.
            (step === "S2" || step === "S5") &&
            typeof coderSessionId === "string" &&
            coderSessionModel !== undefined &&
            stepSpecs[step].model === coderSessionModel
          ) {
            resumeSessionId = coderSessionId;
          }
          const escalationAnswerForStep =
            resumedEscalationAnswer !== undefined &&
            (resumedEscalationAnswer.forStep === step ||
              (step === "S5" && resumedEscalationAnswer.forStep === "S4"))
              ? resumedEscalationAnswer
              : undefined;
          if (escalationAnswerForStep !== undefined) {
            resumedEscalationAnswer = undefined;
          }

          for (;;) {
            let result: Awaited<
              ReturnType<typeof dispatchWorkerWithMonitor>
            >["result"];
            {
              const billingPool = relayBillingPoolForDispatch(step);
              const workerSpec = stepSpecToWorkerSpec(
                stepSpecs[step],
                typeof resumeSessionId === "string" ? "resume" : "fresh",
                billingPool,
              );
              if (expectedKind === "coder") {
                commitTelemetryWorker = {
                  stepId: workerSpec.id,
                  modelSlug: workerSpec.model,
                };
              }
              const focusPath = relayFocusForDispatch(step);
              const dispatchCtx = {
                runId,
                worktree,
                stateDir,
                modelRoute,
                ...(typeof resumeSessionId === "string" ? { resumeSessionId } : {}),
                ...(escalationAnswerForStep != null
                  ? { escalationAnswer: escalationAnswerForStep }
                  : {}),
                ...(billingPool !== undefined
                  ? { billingPool }
                  : {}),
                ...(focusPath !== undefined ? { relayFocusPath: focusPath } : {}),
                // 信封宪法 (ADR 0062): the dispatch structure carries only the
                // identity keys + count; the rich finding content travels in the
                // separate landing payload below.
                ...(step === "S5" || step === "S6"
                  ? {
                      blockingFindingIdentityKeys:
                        pendingBlockingFindingIdentityKeys,
                      // Declared open-count, never cargo-array length (sparse
                      // findings[] must not zero out the control envelope).
                      blockingFindingCount: pendingBlockingFindingCount,
                      ...(step === "S6" && preexistingAssertionTouchedForReverify
                        ? { preexistingAssertionTouched: true }
                        : {}),
                      ...(step === "S6" &&
                      refusedFindingIdentityKeysForReverify.length > 0
                        ? {
                            refusedFindingIdentityKeys:
                              refusedFindingIdentityKeysForReverify,
                          }
                        : {}),
                    }
                  : {}),
              };
              const landingPayload =
                step === "S5" || step === "S6"
                  ? {
                      // Full findings cargo always — never scope-filtered (#899).
                      blockingFindings: pendingBlockingFindings,
                      ...(step === "S5" && pendingRawReviewerArtifacts !== undefined
                        ? { rawReviewerArtifacts: pendingRawReviewerArtifacts }
                        : {}),
                      ...(step === "S5" && pendingFixerFindingScope !== undefined
                        ? { findingScope: pendingFixerFindingScope }
                        : {}),
                      ...(step === "S6" && preexistingAssertionTouchedForReverify
                        ? { preexistingAssertionTouched: true }
                        : {}),
                      ...(step === "S6" &&
                      refusedFindingIdentityKeysForReverify.length > 0
                        ? {
                            refusedFindingIdentityKeys:
                              refusedFindingIdentityKeysForReverify,
                          }
                        : {}),
                    }
                  : undefined;
              // #598: the generic mechanical retry re-dispatches a process-level
              // crash (`failed` / throw, including StructuredOutputError after
              // Sandcastle maxRetries exhaust) with a fresh worker at the same
              // fixed position (#899). This loop dispatches agent steps S2/S3/S5/S6.
              // S7 is only the local child handoff handled by the loop below; it
              // dispatches no worker and has no retry predicate.
              //
              //  - CODER (S2/S5): process failure + typed-signal SOE enter retry.
              //    Completed opaque cargo never changes routing.
              //  - REVIEWER (S3/S6): completed open-count cargo goes to the fixer;
              //    SOE exhaust does NOT feed empty findings to the fixer (#899).
              //
              // #661 owner ruling (2026-07-10): process-level retry CONTINUES on the
              // current scene — do NOT pass a cleanup hook into withMechanicalRetry.
              // Uncommitted work + partial commits are the payload; reading/comparing
              // HEADs is legal, destroying scenes is not. (resetBeforeRetry remains an
              // optional hook for non-runner callers; this site intentionally omits it.)
              //
              // Reviewer: rethrow on throw-exhaust so S8(error) surfaces process
              // crashes and SOE exhaust alike — never feed empty cargo to fixer.
              // Coder keeps default failed→durable abort (existing escalate path).
              const durableRetryOpts = durableMechanicalRetryOptions(
                step,
                expectedKind === "reviewer"
                  ? { rethrowOnExhaustion: true }
                  : {},
              );
              result = await withMechanicalRetry(
                workerSpec,
                dispatchCtx,
                async (s, c) => {
                  // #684: production path — CLI workers go through
                  // dispatchMonitoredCliWorker atomically via
                  // dispatchWorkerWithMonitor; RealBackend hooks make this the
                  // production branch. Handle persisted AT SPAWN (not post-exit).
                  const outcome = await dispatchWorkerWithMonitor(
                    backend,
                    s,
                    c,
                    landingPayload,
                    {
                      onMonitorHandleSpawned: async (handle) => {
                        stepMonitorHandle = handle;
                        try {
                          if (isValidStepId(s.id)) {
                            await persistMonitorHandleAtSpawn(s.id, handle);
                          }
                        } catch {
                          // Best-effort: spawn-time ledger write must not abort
                          // the worker; post-step emitLedger still records it.
                        }
                      },
                    },
                  );
                  if (outcome.monitorHandle !== undefined) {
                    stepMonitorHandle = outcome.monitorHandle;
                  }
                  // The worker has already exited and its result is collected;
                  // join the first-run environment side effect before this
                  // runner advances or returns to an external caller. This
                  // deliberately does not delay spawn / first output (#793).
                  await outcome.telemetryEnvironmentStamp;
                  const dispatched = outcome.result;
                  if (dispatched.kind !== "completed") return dispatched;
                  const dispatchedEscalation = escalateOf(dispatched.output);
                  if (dispatchedEscalation !== undefined) {
                    return dispatched;
                  }

                  return dispatched;
                },
                durableRetryOpts,
              );
              if (result.kind === "completed") completeMechanicalRetryInvocation(step);
            }
            const { unwrapped, reason } = workerResultToStep(result, expectedKind);

            if (unwrapped === undefined) {
              // #686 P2-b: mechanical-retry exhaustion is a relay candidate —
              // hand off when a live baton exists; durable abort only when none.
              if (
                expectedKind === "coder" &&
                isRelayCandidateExhaustion(reason) &&
                canRelayInProcess()
              ) {
                const currentPool =
                  currentBillingPool ??
                  billingPoolFromQuotaPool(
                    poolForModelRef(modelRoute.slots.coder),
                  );
                // Mark the wall-hit pool dead/limited so 换马甲 does not
                // re-select the same model on a "different" pool forever when
                // poolForModelRef disagrees with the baton's billing pool.
                const pools = resolveRelayPools(currentPool, undefined).map(
                  (p) =>
                    p.id === currentPool
                      ? { ...p, status: "dead" as const }
                      : p,
                );
                const handoff = await applyResourceFailureHandoff({
                  trigger: "mechanical_retry_exhausted",
                  state_summary:
                    reason ??
                    `mechanical retry exhausted on ${step}; uncommitted drift preserved`,
                  reason: reason ?? "mechanical retry exhausted",
                  currentModelId: modelIdForWallStep(step),
                  currentPool,
                  rosterOrder: resolveCoderRecOrder(coderRecIssueBody),
                  pools,
                  now: relayNow(),
                  step,
                });
                if (handoff.kind === "relay" && handoff.ledgerEntry) {
                  const entry = handoff.ledgerEntry;
                  const staged = tryStageRelayFocusFile(worktree?.path, entry);
                  if (!staged.ok) {
                    return await errorTermination(
                      step,
                      new Error(staged.reason),
                    );
                  }
                  const marker: LedgerEntry = {
                    step: isValidStepId(entry.step) ? entry.step : step,
                    event: "relay_baton_handoff",
                    trigger: entry.trigger,
                    state_summary: entry.state_summary,
                    ...(entry.remaining !== undefined
                      ? { remaining: entry.remaining }
                      : {}),
                    ...(entry.reason !== undefined
                      ? { reason: entry.reason }
                      : {}),
                    fromModelId: entry.fromModelId,
                    fromPool: entry.fromPool,
                    toModelId: entry.toModelId,
                    toPool: entry.toPool,
                    ts: entry.ts,
                  };
                  if (stateDir !== undefined) {
                    try {
                      await backend.writeLedger(
                        {
                          ...marker,
                          sessionId,
                          prompt_hash: await hashPrompt(
                            undefined,
                            step,
                            backend,
                          ),
                          branchHEAD: await resolveBranchHEAD(),
                          ts: entry.ts,
                        },
                        stateDir,
                      );
                } catch {
                  staged.focus.discard();
                  return await errorTermination(
                        step,
                        new Error(
                          `relay handoff ledger write failed after mechanical retry exhaustion`,
                        ),
                      );
                    }
                  }
                  try {
                    staged.focus.commit();
                  } catch (focusErr) {
                    return await errorTermination(step, focusErr);
                  }
                  ledger.push(marker);
                  activeRelayFocusPath = staged.focus.path;
                  completeMechanicalRetryInvocation(step);
                  applyRelayBaton(handoff.nextBaton, step);
                  continue orchestratorStepLoop;
                }
              }
              const exhaustionReason =
                reason ?? `worker ${step} returned ${result.kind} after bounded redispatch`;
              return await escalateTermination(
                step,
                {
                  reason: `${step} mechanical redispatch exhausted`,
                  diagnosis: exhaustionReason,
                },
                result.sessionId,
                "failure",
                undefined,
                infraFailureStopSummary({
                  summary: exhaustionReason,
                  repairHint: `inspect ${step} worker protocol failure and rerun`,
                }),
              );
            }
            const normalized =
              "output" in unwrapped && !("kind" in unwrapped)
                ? { output: unwrapped.output, sessionId: unwrapped.sessionId }
                : { output: unwrapped as StepOutput, sessionId: undefined };
            output = normalized.output;
            stepSessionId = normalized.sessionId;
            // #924: retain coder session for S5 continuity (and multi-round S5).
            if (
              (step === "S2" || step === "S5") &&
              typeof stepSessionId === "string"
            ) {
              coderSessionId = stepSessionId;
              coderSessionModel = stepSpecs[step].model;
            }
            break;
          }
        } catch (err) {
          if (isSelfReportedRelayError(err) && err.tag.kind === "decision_gate") {
            const escalation: Escalation = {
              reason: `${step} worker raised a decision gate`,
              diagnosis: err.tag.state_summary,
            };
            const decisionOutput: StepOutput =
              expectedKind === "coder"
                ? {
                    kind: "coder",
                    committed: false,
                    commitsAdded: 0,
                    escalate: escalation,
                  }
                : { kind: "reviewer", findings: [], findingsCount: 0, escalate: escalation };
            return await escalateTermination(
              step,
              escalation,
              err.sessionId,
              "decision",
              decisionOutput,
              decisionGateParkStopSummary({
                summary: `${step} worker raised a decision gate: ${err.tag.state_summary}`,
                repairHint:
                  "answer the decision gate, then re-feed to resume the parked worker step",
              }),
            );
          }
          // #683/#686: 429 quota wall → park within T / no baton; relay beyond T
          // with a live baton (write handoff + focus, apply next baton, re-enter).
          if (isQuotaWaitForResetError(err)) {
            const currentPool =
              currentBillingPool ?? billingPoolFromQuotaPool(err.pool);
            if (!canRelayInProcess()) {
              return await parkQuotaWaitForReset({
                step,
                err,
                ledger,
                stateDir,
                sessionId,
                backend,
                resolveBranchHEAD,
                hashPrompt: (promptFile, s) =>
                  hashPrompt(promptFile, s, backend),
              });
            }
            const outcome = await parkOrRelayQuotaWall({
              step,
              err,
              ledger,
              stateDir,
              sessionId,
              backend,
              resolveBranchHEAD,
              hashPrompt: (promptFile, s) => hashPrompt(promptFile, s, backend),
              worktreePath: worktree?.path,
              currentModelId: modelIdForWallStep(step),
              currentPool,
              rosterOrder: resolveCoderRecOrder(coderRecIssueBody),
              // #909 production live path: route-smoke knownLive for quota walls.
              pools: resolveRelayPools(
                currentPool,
                err.disposition.resetAt,
                true,
              ),
              now: relayNow(),
            });
            if (outcome.kind === "park") return outcome.result;
            if (outcome.focusPath !== undefined) {
              activeRelayFocusPath = outcome.focusPath;
            }
            applyRelayBaton(outcome.nextBaton, step);
            continue orchestratorStepLoop;
          }
          // #686/#787: resource failures relay without retry; capacity keeps its
          // pool live so the capacity selector can change checkpoints in-pool.
          // (never mechanical-retry / never reset).
          if (
            (isHangWithLivePoolError(err) ||
              isSelfReportedRelayError(err) ||
              isCapacityRelayError(err)) &&
            canRelayInProcess()
          ) {
            const { currentPool, pools } = resolveResourceFailurePool({
              modelRef: modelRefForWallStep(step),
              ...(isHangWithLivePoolError(err)
                ? { knownPool: billingPoolFromQuotaPool(err.poolId) }
                : {}),
              capacity: isCapacityRelayError(err),
            });
            const trigger = isCapacityRelayError(err)
              ? ("capacity" as const)
              : isHangWithLivePoolError(err)
              ? ("hang_with_live_pool" as const)
              : isSelfReportedRelayError(err) && err.tag.kind === "blocked"
                ? ("self_reported_blocked" as const)
                : ("phase_complete" as const);
            const stateSummary = isSelfReportedRelayError(err)
              ? err.tag.state_summary
              : isCapacityRelayError(err)
                ? "model checkpoint at capacity; drift preserved"
                : "worker hang with live pool; pid tree killed; drift preserved";
            const remaining =
              isSelfReportedRelayError(err) && "remaining" in err.tag
                ? err.tag.remaining
                : undefined;
            const handoff = await applyResourceFailureHandoff({
              trigger,
              state_summary: stateSummary,
              ...(remaining !== undefined ? { remaining } : {}),
              reason: err instanceof Error ? err.message : String(err),
              currentModelId: modelIdForWallStep(step),
              currentPool,
              rosterOrder: resolveCoderRecOrder(coderRecIssueBody),
              pools,
              now: relayNow(),
              step,
            });
            if (handoff.kind === "relay" && handoff.ledgerEntry) {
              const entry = handoff.ledgerEntry;
              const staged = tryStageRelayFocusFile(worktree?.path, entry);
              if (!staged.ok) {
                return await errorTermination(
                  step,
                  new Error(staged.reason),
                );
              }
              const marker: LedgerEntry = {
                step: isValidStepId(entry.step) ? entry.step : step,
                event: "relay_baton_handoff",
                trigger: entry.trigger,
                state_summary: entry.state_summary,
                ...(entry.remaining !== undefined
                  ? { remaining: entry.remaining }
                  : {}),
                ...(entry.reason !== undefined ? { reason: entry.reason } : {}),
                fromModelId: entry.fromModelId,
                fromPool: entry.fromPool,
                toModelId: entry.toModelId,
                toPool: entry.toPool,
                ts: entry.ts,
              };
              if (stateDir !== undefined) {
                try {
                  await backend.writeLedger(
                    {
                      ...marker,
                      sessionId,
                      prompt_hash: await hashPrompt(undefined, step, backend),
                      branchHEAD: await resolveBranchHEAD(),
                      ts: entry.ts,
                    },
                    stateDir,
                  );
                } catch {
                  staged.focus.discard();
                  return await errorTermination(step, err);
                }
              }
              try {
                staged.focus.commit();
              } catch (focusErr) {
                return await errorTermination(step, focusErr);
              }
              ledger.push(marker);
              activeRelayFocusPath = staged.focus.path;
              completeMechanicalRetryInvocation(step);
              applyRelayBaton(handoff.nextBaton, step);
              continue orchestratorStepLoop;
            }
          }
          return await errorTermination(step, err);
        }

        // Fresh host HEAD capture is best-effort telemetry/bookkeeping only.
        // Its availability cannot change the worker receipt's route.
        const coderHeadAfterStep = expectedKind === "coder"
          ? gitHead(worktree)
          : undefined;

        // #786: host-git commit observations are strictly sidecar-only.
        // A failed read/write cannot affect the step's ledger or route decision.
        // Trigger this from the expected worker role before any output contract
        // gate: a worker may have committed before reporting malformed output.
        if (expectedKind === "coder" && worktree !== undefined) {
          const telemetryDir = stepTelemetryDir;
          if (telemetryDir !== undefined && coderHeadAfterStep !== undefined) {
            void scheduleCommitTelemetry({
              ledgerDir: telemetryDir,
              repoPath: worktree.path,
              runId,
              issue: issueNumber,
              ...(commitTelemetryWorker !== undefined
                ? { worker: commitTelemetryWorker }
                : {}),
              before: coderHeadBeforeStep === undefined
                ? { kind: "resolve-before-head", commitsAdded:
                    output.kind === "coder" && Number.isInteger(output.commitsAdded)
                      ? output.commitsAdded
                      : 1 }
                : { kind: "held", oid: coderHeadBeforeStep },
              after: { kind: "held", oid: coderHeadAfterStep },
            });
          }
        }

        const stepEscalate = escalateOf(output);
        const carriesEscalate = stepEscalate != null;
        if (!carriesEscalate) {
          if (expectedKind === "reviewer") {
            // Control envelope only: role kind so findings-count channel can run.
            // Do not inspect individual finding fields (findings schema court).
            if (output?.kind !== "reviewer") {
              // Unusable review envelope (not a typed open-count receipt) →
              // fixer path with raw artifact pointers. Do NOT inspect findings
              // cargo shape here (ADR 0131 / #899).
              pendingBlockingFindings = [];
              pendingBlockingFindingIdentityKeys = [];
              pendingBlockingFindingCount = 0;
              pendingRawReviewerArtifacts = reviewerRawArtifactPointers(
                stepMonitorHandle,
                stepSessionId,
              );
              step = "S5";
              continue orchestratorStepLoop;
            }
            // Typed findingsCount only: positive open-count always preserves
            // raw artifact pointers for S5. Findings rows are opaque cargo —
            // never re-dispatch or zero the count based on array shape.
            if (output.findingsCount > 0) {
              pendingRawReviewerArtifacts = reviewerRawArtifactPointers(
                stepMonitorHandle,
                stepSessionId,
              );
            }
          }
        }
        lastOutput = output;
        if (output.kind === "coder") {
          if (step === "S5" && coderHeadBeforeStep !== undefined) {
            const afterFix = coderHeadAfterStep;
            if (afterFix !== undefined) {
              try {
                preexistingAssertionTouchedForReverify = reviewFixAssertionSignal({
                  worktreePath: worktree.path,
                  sliceBase: worktree.base,
                  beforeFix: coderHeadBeforeStep,
                  afterFix,
                });
              } catch {
                preexistingAssertionTouchedForReverify = false;
              }
            }
          }
          // #677: legal refuse — wire decision gate on the real S5 path.
          // Refused keys stay in the fix→fresh-re-review loop (never escalate/park).
          if (step === "S5") {
            const records = output.refuseRecords ?? [];
            if (records.length > 0) {
              const legal = reviewFixDecisionGate({ records });
              refusedFindingIdentityKeysForReverify =
                legal?.refusedFindingIdentityKeys ?? [];
            } else {
              refusedFindingIdentityKeysForReverify =
                output.refusedFindingIdentityKeys ?? [];
            }
          }
        }
        if (step === "S3" || step === "S6") lastReviewerStepId = step;
        if (step === "S5") {
          pendingRawReviewerArtifacts = undefined;
          pendingFixerFindingScope = undefined;
        }
        break;
      }

      case "S4": {
        // #877: findings-count channel only — no disposition/no-progress court.
        seedClassificationFromReviewerOutput(
          lastOutput,
          lastReviewerStepId === "S6",
        );
        break;
      }

      case "S7": {
        // A slice always runs inside a family worktree. S7 is the child handoff:
        // commits stay local for the family merger; no standalone ship/PR path exists.
        if (worktree === undefined) {
          throw new Error("runner: S7 reached before worktree prepared");
        }
        break;
      }

      case "S8": {
        // Unreachable: S8 is produced as a terminal handoff by route(), it is
        // never entered as a loop step. Guarded for completeness.
        throw new Error("runner: S8 should be reached via handoff, not looped");
      }

      default: {
        // Exhaustiveness guard: any unrecognised step is a routing bug.
        const never: never = step;
        throw new Error(`runner: step ${String(never)} not handled`);
      }
    }

    const stepFindingDispositions =
      step === "S4" ? findingDispositions : undefined;

    // Record this step in the ledger (anti-skip + resume truth, ADR 0018 §3).
    // #249: also persist via backend.writeLedger (sibling state dir).
    ledger.push({
      step,
      ...(output !== undefined ? { output } : {}),
      // #604 correctness r5 (E2): carry the surfaced per-step session id on the
      // in-memory entry too. The persisted ledger (emitLedger below) already records
      // it, but RunResult.stepLedger (the in-memory ledger) previously dropped it —
      // so the family runner reading a parked child's escalated agent step off the
      // lean RunResult ledger saw `sessionId: undefined` and never forwarded the
      // real id for 原地 resume (FamilyChildEscalation.sessionId existed in name only).
      ...(stepSessionId !== undefined ? { sessionId: stepSessionId } : {}),
      ...(stepFindingDispositions !== undefined
        ? { findingDispositions: stepFindingDispositions }
        : {}),
      // #684: surface the CLI monitor handle in-memory too (resume rebuild parity).
      ...(stepMonitorHandle !== undefined
        ? { monitorHandle: stepMonitorHandle }
        : {}),
    });
    // #6: a writeLedger failure here is a backend-call exception → it must
    // converge to S8(error) with an error package, NOT raw-reject out of
    // runOrchestrator (PRD route table: any backend call throwing → S8(error)).
    // The step is already recorded in-memory above, so don't double-record it.
    try {
      // #256: pass the real per-step sandbox session id (captured from the seam
      // extension) so the ledger records the true id resumeSession will resume.
      // #684: pass the monitor handle so resume can rebuild alive/idle/kill judgment.
      await emitLedger(
        step,
        output,
        promptFile,
        undefined,
        stepSessionId,
        stepFindingDispositions,
        undefined,
        undefined,
        stepMonitorHandle,
      );
    } catch (err) {
      // integ-cmr base r2 (D): the step is already in the in-memory ledger
      // (pushed above), so skip the in-memory push — but STILL best-effort
      // re-persist the failing step so the persisted ledger is not left missing
      // it on a transient write fault.
      // integ-cmr base r1 (F3): pass the in-flight `output` so the re-persisted
      // disk entry carries it (resume reads the disk ledger; an output-less
      // re-persist would resume from a step missing its findings/commit count).
      return await errorTermination(step, err, {
        recordInMemory: false,
        output,
        findingDispositions: stepFindingDispositions,
      });
    }

    // A relay baton is a step-local override. Once its relayed step has
    // durably completed, normal downstream roles must reselect their own route.
    clearCompletedRelayState(step, output);

    // The runner — not the agent — decides the next step.
    // The fixed review/fix topology advances from the reviewer's self-reported
    // findings count and explicit escalation; receipt cargo is not a fate input.
    const decision = route({
      from: step,
      output: lastOutput,
    });

    if (decision.kind === "handoff") {
      const handoffStopSummary: StopSummary =
        decision.status === "success"
          ? successSummaryForCurrentState({ findingDispositions })
          : decision.status === "error"
            ? stopSummaryForErrorPackage({
                failedStep: step,
                reason: buildErrorReason(step, lastOutput),
                branchHead: worktree?.branch,
              })
            : stopSummaryForEscalation(
                escalateOf(lastOutput) ?? {
                  reason: "run escalated",
                  diagnosis: `step ${step} routed to an escalate handoff`,
                },
              );
      ledger.push({ step: "S8", stopSummary: handoffStopSummary });
      // #249: persist the S8 handoff entry too.
      // #6 / integ-cmr base r2 (E): a writeLedger failure on the S8 entry →
      // S8(error), not a raw rejection.
      // #255: tag the entry with the terminal status (decision.status) so a
      // resuming run can tell a prior success / escalate / error apart (the S8
      // entry is otherwise identical for all three).
      try {
        await emitLedger(
          "S8",
          undefined,
          undefined,
          decision.status,
          undefined,
          undefined,
          escalationKindForHandoff(decision.status),
          handoffStopSummary,
        );
      } catch (err) {
        // integ-cmr base r2 (E): the failing operation here is the S8 handoff
        // ledger write — which happens for ANY handoff (route error, escalate,
        // local child success). The old code hard-coded
        // failedStep:"S7", misattributing it to push even on paths where push
        // never ran. Attribute to the REAL failing step (the S8 write) and name
        // the operation in the reason so the dev sees what actually failed.
        const cause = err instanceof Error ? err.message : String(err);
        // integ-cmr m2 r2 (cross-slice seam #252 ⋈ #255): the FIRST emitLedger
        // re-threw, so the disk ledger still stops at the last SUCCESSFUL step
        // (S7 on a success handoff; the escalating agent step on an escalate
        // handoff) — there is NO tagged terminal S8. A re-feed would then
        // mis-report: planResume routes S7→{handoff,success}→SUCCESS (a run that
        // actually errored masquerading as success), or Case 2 re-runs the
        // escalating step via resumeSession (the errored run silently re-run).
        // Mirror the error paths (errorTermination / no-progress bail): best-
        // effort persist a TAGGED 'error' S8 so the disk carries the true
        // terminal status and a re-feed reports ERROR via planResume Case 3a.
        const errorPackage: ErrorPackage = {
          failedStep: "S8",
          reason: `writeLedger(S8) failed while persisting the handoff entry: ${cause}`,
          branchHead: worktree?.branch,
        };
        const stopSummary = stopSummaryForErrorPackage(errorPackage);
        // persistBestEffort swallows a secondary write fault — we already return
        // status:error, a second ledger fault must not mask the original cause.
        await persistBestEffort(
          "S8",
          undefined,
          undefined,
          "error",
          undefined,
          undefined,
          undefined,
          stopSummary,
        );
        return {
          status: "error",
          errorPackage,
          stepLedger: ledger,
          stopSummary,
        };
      }

      if (decision.status === "error") {
        // Build an error package from the current step context so the developer
        // can diagnose without re-running the pipeline (#252 / US#30).
        const reason = buildErrorReason(step, lastOutput);
        const errorPackage: ErrorPackage = {
          failedStep: step,
          reason,
          branchHead: worktree?.branch,
        };
        return {
          status: "error",
          errorPackage,
          stepLedger: ledger,
          stopSummary: handoffStopSummary,
        };
      }

      return {
        status: decision.status,
        branch: decision.status === "success" ? worktree?.branch : undefined,
        stepLedger: ledger,
        stopSummary: handoffStopSummary,
      };
    }

    step = decision.step;
  }
  // Unreachable: the `for (;;)` loop exits only via a `return` above — every
  // route() handoff returns and the no-progress guard returns. There is no
  // round/step cap to fall out of (US#18: no "数到 N 就停").
}
