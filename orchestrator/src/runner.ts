/**
 * runOrchestrator — the runner loop (ADR 0018, corrected by ADR 0030).
 *
 * The runner drives one family's fixed child-slice sequence: it performs each
 * runner-action step or dispatches each worker step, writes a step-ledger
 * entry, then calls route() to pick the next step. The agent never decides
 * the next step — route() does.
 *
 * ADR 0030 / #925: the child runner owns the visible per-slice review/fix loop:
 *
 *   S0(gate) → S1(context) → S2(implement) → S3(judge establish)
 *     converged → S7(local handoff) → S8(handoff)
 *     continue  → S5(fix) → S6(judge resume) → (verdict again)
 *     escalate  → decision-kind park (answer → 原地 resume)
 *
 * S2/S5 are coder workers. S3/S6 are the persistent verify judge. S4 mechanical
 * open-count classification is dissolved into the judge verdict tri-state.
 *
 * Slice #249: persisted step ledger — every step is written via
 *   backend.writeLedger() to the sibling state dir (outside the worktree).
 * Slice #251: global escalate stop edge (in route()).
 * Slice #252: error edges —
 *   - any backend call throws → S8(error) + error package  [runner catch]
 *   - the S2 worker carries escalate → S8(escalate) [route() detects]
 * Slice #253: StepSpec contract — model/maxIter/soul/toolchain (#928: no signal).
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
} from "./reviewFixAssertionGate.js";
import { coderRefuseReverifyLanding } from "./coderRefuseExit.js";
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
  modelForSlot,
  printableRouteLineup,
  degradeOptionalRouteSmokeFailures,
  resolveActiveModelRoute,
  knownLiveBillingPoolsFromRoute,
  relaySlotForSingleSliceWallStep,
  withCoderSlot,
  type ModelRouteEnv,
  type ResolvedModelRoute,
} from "./modelRoutes.js";
import {
  admitCoderRec,
  admitRouteFromEnv,
  admissionRouteFailureDiagnosis,
  isGithubAuthFailure,
} from "./admissionPreflight.js";
import { discoverResidentScene } from "./sceneAction.js";
import { executeAdvanceCoderSuggestion } from "./advanceCoderEffect.js";
import {
  resolveCoderRecOrder,
  lookupCoderRosterEntry,
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
  applyResourceFailureHandoff,
  resumeRelayFromLedger,
  renderEphemeralRelayBrief,
  isCapacityRelayError,
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
  isJudgeSeat,

  priorJudgeVerdictRowsFromLedger,
  projectJudgeContinueBlocking,
  projectJudgeSeatOutput,
} from "./judgeStation.js";
import {
  rebuildBlockingFromLedger,
  reviewerRawArtifactPointers,
} from "./residualLedger.js";
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
  LedgerEntry,
  PersistentLedgerEntry,
  ResumeState,
  ReviewFixRefuseRecord,
  RunInput,
  RunResult,
  SliceStepId,
  StepId,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorktreeHandle,
} from "./types.js";

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
    } catch (err) {
      // A prompt-resolution fault must NOT abort ledgering — fall back to the
      // name hash so the step is still recorded (the resume truth survives).
      // #934 ID-015: name-prefix fallback AND warn (not silent).
      console.warn(
        `[orchestrator] optional prompt content read failed (name-hash fallback): ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
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
 * otherwise), `branchHEAD` is the optional real `git rev-parse HEAD` SHA, and
 * `prompt_hash` uses the documented content/name fallback. This
 * builder just assembles the entry; value resolution lives in `emitLedger`.
 */
function buildPersistentEntry(opts: {
  step: SliceStepId;
  output: StepOutput | undefined;
  runId: string;
  sessionId: string;
  prompt_hash: string;
  branchHEAD?: string;
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
    ts: opts.ts,
    ...(opts.branchHEAD !== undefined ? { branchHEAD: opts.branchHEAD } : {}),
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
 * #677 / #927: rebuild S5→S6 reverify locals from the persisted S5 ledger row.
 *
 * `preexistingAssertionTouchedForReverify`,
 * `refusedFindingIdentityKeysForReverify`, and opaque `refuseRecordsForReverify`
 * are process-local; a crash between S5 completing and S6 running would
 * otherwise drop them. Prefer rebuild over new durable fields: refuse keys +
 * cargo already live on the S5 coder output, and the assertion signal is
 * recomputed from ledger branchHEADs + worktree git
 * (same shape as #743 authorization rebuild / S4 findings-count replay).
 */
interface S5ReverifySignals {
  readonly preexistingAssertionTouched: boolean;
  readonly refusedFindingIdentityKeys: readonly string[];
  readonly refuseRecords?: readonly ReviewFixRefuseRecord[];
}

function ledgerEntryBranchHead(entry: LedgerEntry): string | undefined {
  const head = (entry as PersistentLedgerEntry).branchHEAD;
  return isLikelyGitSha(head) ? head : undefined;
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
  // #927 / #919 M2: envelope keys only (cargo refuseRecords never invents keys).
  const refuseLanding = coderRefuseReverifyLanding(output);
  const refusedFindingIdentityKeys = refuseLanding.refusedFindingIdentityKeys;

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
    ...(refuseLanding.refuseRecords !== undefined
      ? { refuseRecords: refuseLanding.refuseRecords }
      : {}),
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
    const rebuiltBlocking = rebuildBlockingFromLedger(executableLedger);
    const answer =
      decisionStep !== undefined
        ? latestAnswerAfter(ledger, lastEntryIndex, decisionStep)
        : undefined;
    const continueFixingRepair =
      decisionStep === "S4"
        ? repairIntent !== undefined
          ? continueRepairFromEvent(
              repairIntent,
              rebuiltBlocking.blockingFindingCount,
            )
          : latestContinueFixingAfter(
              ledger,
              lastEntryIndex,
              rebuiltBlocking.blockingFindingCount,
            ) ??
            continueRepairFromAnswer(answer, rebuiltBlocking.blockingFindingCount)
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
// Runner only: process exit / judge status tri-state / worker-raised decision gate.

/**
 * The fixed StepSpecs for child-slice worker steps. Versioned promptFiles,
 * never assembled inline (ADR 0018 决定#4).
 *
 * #925 / ADR 0132: S2 implements, S3 establishes the verify judge, S5 fixes
 * live findings, S6 resumes the same judge session. maxIter is 1 on every seat
 * (Ralph outer multi-iter retired; typed SO re-asks are in-session).
 *
 * #253/#928 fields: model (CLI slug), maxIter (per-seat Sandcastle iteration
 * budget — NOT a fix-loop give-up counter; always 1), soul, toolchain.
 * Completion is clean exit + legal sidecar / typed envelope — no signal field.
 *
 * Swapping models = select ORCHESTRATOR_ROUTE or use owner-authored Coder-Rec;
 * no image rebuild or
 * structural StepSpec change (PRD #244 Implementation Decisions + ADR 0031).
 */

/**
 * The S2 coder worker's model slug, selected by the active route. The slug is resolved to the baked CLI
 * by agentForSlug; invalid route names / slugs fail closed before dispatch.
 */
export function coderModel(env: ModelRouteEnv = process.env): string {
  return modelForSlot("coder", env);
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
      // agentForSlug (realBackend); no image rebuild or StepSpec shape change.
      model: route.slots.coder,
      // #899 / ADR 0128 / #928: one single-iteration Sandcastle run per seat;
      // clean exit + legal sidecar / typed envelope is completion.
      maxIter: 1,
      soul: "coder",
      toolchain: IMAGE_TOOLCHAIN,
    },
    S3: {
      id: "S3",
      // #925 / #919 S2/R8: persistent verify judge. Seat identity is step/id
      // S3 only (isJudgeSeat); production role+soul are `"verify"` cargo.
      // `#923` model-route slot is already verify. Leg-soul `"reviewer"` remains
      // only inside multi-model review legs.
      role: "verify",
      promptFile: "judge_station.md",
      model: route.slots.verify,
      maxIter: 1,
      soul: "verify",
      toolchain: IMAGE_TOOLCHAIN,
    },
    S5: {
      id: "S5",
      role: "coder",
      promptFile: "coder_fix.md",
      model: route.slots.coderFix,
      // #899 / ADR 0128 / #928: single-iteration seat (same as S2).
      maxIter: 1,
      soul: "coder",
      toolchain: IMAGE_TOOLCHAIN,
    },
    S6: {
      id: "S6",
      // #925 / #919 S2/R8: same judge seat as S3 — resume S3 session.
      // Seat identity is step/id S6 (isJudgeSeat); role+soul `"verify"` cargo.
      role: "verify",
      promptFile: "judge_station.md",
      model: route.slots.verify,
      maxIter: 1,
      soul: "verify",
      toolchain: IMAGE_TOOLCHAIN,
    },
  };
}

/** The relay pool belongs to one wall-hit route entry, never the whole lineup. */
function activeRelaySmokeEntryKey(
  step: StepId | undefined,
  route: Pick<ResolvedModelRoute, "slots">,
): string | undefined {
  // #923: single-slice map lives in modelRoutes (S3/S6 → verify); do not fork it.
  if (step !== "S2" && step !== "S3" && step !== "S5" && step !== "S6") {
    return undefined;
  }
  const slot = relaySlotForSingleSliceWallStep(step);
  return `${slot}:${route.slots[slot]}`;
}

export function stepSpecsForEnv(
  env: ModelRouteEnv = process.env,
): Readonly<Record<WorkerStepId, StepSpec>> {
  return stepSpecsForRoute(resolveActiveModelRoute(env));
}

export const WORKER_PROMPT_FILES: Readonly<Record<WorkerStepId, string>> = {
  S2: "coder_implement.md",
  S3: "judge_station.md",
  S5: "coder_fix.md",
  S6: "judge_station.md",
};

/** Synthesise a human-readable reason for a route-owned error edge. */
function buildErrorReason(step: StepId, _output: StepOutput | undefined): string {
  return `step ${step} routed to error handoff`;
}

/**
 * #925 / #919 S1/M5: judge seats collapse residual paper via the sole
 * {@link projectJudgeSeatOutput} helper. Membership = {@link isJudgeSeat}.
 */
function normalizeJudgeSeatOutput(
  step: SliceStepId,
  output: StepOutput,
): StepOutput {
  return isJudgeSeat({ step }) ? projectJudgeSeatOutput(output) : output;
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

/**
 * Decision-kind escalate park stop summary.
 * #925 / ADR 0132 / #919 CR U2: typed judge escalate and decision_gate share
 * the same park family (`decision_gate_park`) — no third stop token.
 */
function stopSummaryForEscalation(escalation: Escalation): StopSummary {
  return decisionGateParkStopSummary({
    summary: `${escalation.reason}: ${escalation.diagnosis}`,
    repairHint: "answer the decision escalation and rerun",
  });
}

function stopSummaryForStartupRouteFailure(escalation: Escalation): StopSummary {
  const reason = admissionRouteFailureDiagnosis(
    `${escalation.reason}: ${escalation.diagnosis}`,
  );
  return infraFailureStopSummary({
    summary: reason,
    repairHint:
      "fix ORCHESTRATOR_ROUTE preset or issue Coder-Rec staffing before dispatching workers",
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

  // #936 / #934 ID-005: Scene Recovery first — resident discovery before
  // admission network work when a durable scene may already exist.
  const scene = await discoverResidentScene(backend, issueNumber);
  if (scene.kind === "corrupted") {
    const reason = scene.reason;
    const stopSummary = infraFailureStopSummary({
      summary: reason,
      repairHint: "repair or clear the resident worksite/ledger before re-entry",
    });
    return {
      status: "error",
      errorPackage: { failedStep: "S0", reason },
      stepLedger: [{ step: "S8", stopSummary }],
      stopSummary,
    };
  }

  // #936 / #934 ID-005: durable terminal replay BEFORE route admission.
  // A broken ORCHESTRATOR_ROUTE must not block re-delivery of an already
  // finished success/error/unanswered-escalate terminal (zero meta/smoke).
  // Skip early short-circuit when a repairIntent is present — that path must
  // still durable-write the intent (and surface write failures) before planResume.
  if (scene.kind === "resident" && input.repairIntent === undefined) {
    const earlyPlan = planResume(scene.state.ledger);
    if (earlyPlan.terminalStatus !== undefined) {
      const worktree = scene.state.worktree;
      const ledger = earlyPlan.priorLedger;
      if (earlyPlan.terminalStatus === "error") {
        const reason =
          "prior run terminated with an error handoff (re-fed after completion)";
        const errorPackage: ErrorPackage = {
          failedStep: lastAgentStep(ledger) ?? "S8",
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
        earlyPlan.terminalStatus === "success"
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
        status: earlyPlan.terminalStatus,
        branch: earlyPlan.terminalStatus === "success" ? worktree.branch : undefined,
        stepLedger: ledger,
        stopSummary,
      };
    }
  }

  // #936 / #934 ID-002: Admission/Preflight — preset route + fail-closed tight.
  // No env slot overrides, no interactive continue. Non-terminal resume still
  // needs a lineup for dispatch.
  const admitted = admitRouteFromEnv();
  if (admitted.kind === "stop") {
    const stopSummary = stopSummaryForStartupRouteFailure(admitted.escalation);
    const isTight = admitted.escalation.reason === "tight route violation";
    return {
      status: isTight ? "escalate" : "error",
      errorPackage: {
        failedStep: "S0",
        reason: `${admitted.escalation.reason}: ${admitted.escalation.diagnosis}`,
      },
      stepLedger: [{ step: "S8", stopSummary }],
      stopSummary,
    };
  }
  console.info(
    `[orchestrator] model route lineup\n${printableRouteLineup(admitted.route)}`,
  );
  // #767: modelRoute / stepSpecs stay mutable so Coder-Rec can override the
  // coder (+ coderFix) slot at S0 (first seat stay-put; #926 owns advanceCoder).
  let modelRoute: ResolvedModelRoute = admitted.route;
  let stepSpecs = stepSpecsForRoute(modelRoute);
  /** Issue body used for Coder-Rec parse (S0 meta.body). */
  let coderRecIssueBody: string | undefined;
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
   * handoffs only: blocks Coder-Rec snap-back after a relay for the rest of
   * the run. ADR 0132 deleted round-threshold quality advance.
   */
  let stickyRelayCoderSlug: string | undefined;
  /** S5 resource relay is independent from the normal S2 coder slot. */
  let stickyRelayCoderFixSlug: string | undefined;
  /**
   * #926 — sticky judge-advanced coder slug. Holds after a successful
   * `advanceCoder` so Coder-Rec first-seat re-apply cannot snap back. Resource
   * relay stickiness still wins when set (capacity crisis overrides quality advance).
   */
  let stickyJudgeAdvanceCoderSlug: string | undefined;
  /** #937 — last ephemeral relay brief (forwarded on next same-step dispatch). */
  let activeRelayBrief: string | undefined;
  /** The only step allowed to consume the current relay pool + ephemeral brief. */
  let activeRelayStep: StepId | undefined;
  // #924: coder persistent session across S2 → S5 rounds (declared early so
  // relay / first-seat Coder-Rec model changes can invalidate it).
  let coderSessionId: string | undefined;
  let coderSessionModel: string | undefined;
  // #925: judge persistent session across S3 → S6 rounds (same model).
  let judgeSessionId: string | undefined;
  let judgeSessionModel: string | undefined;

  /**
   * Hold a sticky coder seat against Coder-Rec snap-back: rewrite coder
   * (+coderFix), refresh stepSpecs, invalidate smoke, and retire the session
   * when the runnable model actually changed.
   */
  const holdCoderSticky = (slug: string): void => {
    if (modelRoute.slots.coder === slug) return;
    modelRoute = withCoderSlot(modelRoute, slug);
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
  };

  /**
   * #926 / #934 ID-005 — single bookkeeping write path for advance / stay-put
   * markers. Post-worksite route/step truth is required durable: writeLedger
   * failure surfaces as `record_persist_failed` (not ID-015 telemetry fail-open).
   * Matches the coder_advance_stay_put audit fail-closed path.
   */
  const persistAdvanceBookkeeping = async (
    marker: LedgerEntry,
    forStep: "S3" | "S6",
    label: string,
  ): Promise<void> => {
    ledger.push(marker);
    if (stateDir === undefined) return;
    try {
      await backend.writeLedger(
        {
          ...marker,
          sessionId,
          prompt_hash: await hashPrompt(undefined, forStep, backend),
          branchHEAD: await resolveBranchHEAD(),
          ts: marker.ts ?? new Date().toISOString(),
        },
        stateDir,
      );
    } catch (err) {
      throw new Error(
        `record_persist_failed: coder_advance (${label}): ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    }
  };

  /** Apply Coder-Rec first-seat stay-put (no round-threshold rotation). */
  const applyCoderRecSelection = async (): Promise<
    | { kind: "stop"; escalation: Escalation }
    | undefined
  > => {
    // Resource-relay stickiness: hold the baton for the run. ADR 0132 deleted
    // round-threshold quality advance.
    if (stickyRelayCoderSlug !== undefined) {
      holdCoderSticky(stickyRelayCoderSlug);
      return undefined;
    }
    if (stickyRelayCoderFixSlug !== undefined) {
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
    // #926: judge-advanced seat holds against Coder-Rec first-seat re-apply.
    if (stickyJudgeAdvanceCoderSlug !== undefined) {
      holdCoderSticky(stickyJudgeAdvanceCoderSlug);
      return undefined;
    }
    // #936: Admission Action owns Coder-Rec + tight re-check (no env skip).
    const admittedRec = admitCoderRec(modelRoute, coderRecIssueBody);
    if (admittedRec.kind === "stop") {
      return { kind: "stop", escalation: admittedRec.escalation };
    }
    if (admittedRec.route === modelRoute) return undefined;
    modelRoute = admittedRec.route;
    // #686 P1: a coder-slot change must not inherit the prior resource-relay
    // pool — reselect from the new model's dispatch binding.
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
    // before its first dispatch (top-of-loop OR the S2/S5 re-apply path).
    routeSmokeChecked = false;
    console.info(
      `[orchestrator] Coder-Rec applied → coder=${modelRoute.slots.coder}`,
    );
    return undefined;
  };

  const stopForCoderRecTightRoutePolicy = async (escalation: {
    readonly reason: string;
    readonly diagnosis: string;
  }): Promise<RunResult> => {
    const stopSummary = stopSummaryForStartupRouteFailure(escalation);
    // #899: this stop can fire MID-RUN (the S2/S5 Coder-Rec re-apply path),
    // not only at startup. It used to return an inline RunResult with an
    // in-memory-only S8 — no disk row, no output — so the family saw a bare
    // "failed", resume could not classify the breakpoint, and every re-ignition
    // replayed the whole run from scratch. Terminal returns must speak and persist.
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

  /**
   * Probe a candidate route for assignability (smoke) without terminalising.
   * Used by judge advance so an unassignable roster-legal seat stays put.
   */
  const probeRouteSmoke = async (
    candidate: ResolvedModelRoute,
  ): Promise<
    | { readonly ok: true; readonly route: ResolvedModelRoute }
    | { readonly ok: false; readonly reason: string }
  > => {
    if (typeof backend.smokeModelRoute !== "function") {
      return {
        ok: false,
        reason:
          "route smoke executor is required before dispatch; backend did not provide smokeModelRoute",
      };
    }
    try {
      const currentCliVersions = backend.currentCliVersions
        ? await backend.currentCliVersions(
            candidate,
            activeRelayStep === undefined ? undefined : currentBillingPool,
            activeRelaySmokeEntryKey(activeRelayStep, candidate),
          )
        : {};
      let smoked = await backend.smokeModelRoute(
        candidate,
        currentCliVersions,
        activeRelayStep === undefined ? undefined : currentBillingPool,
        activeRelaySmokeEntryKey(activeRelayStep, candidate),
      );
      smoked = degradeOptionalRouteSmokeFailures(smoked).route;
      const failure = routeSmokeFailure(
        smoked,
        Date.now(),
        undefined,
        currentCliVersions,
      );
      if (failure !== undefined) {
        return { ok: false, reason: failure };
      }
      return { ok: true, route: smoked };
    } catch (err) {
      return {
        ok: false,
        reason: `route smoke failed: ${
          err instanceof Error ? err.message : String(err)
        }`,
      };
    }
  };

  /**
   * #926 / #919 — execute a judge `advanceCoder` suggestion (or stay-put + audit).
   * Shared topology via {@link executeAdvanceCoderSuggestion}; this court only
   * owns bookkeeping + sticky state. Never terminals for roster unusability.
   */
  const applyJudgeAdvanceCoder = async (
    suggestion: string,
    forStep: "S3" | "S6",
  ): Promise<void> => {
    const currentSlug = modelRoute.slots.coder;
    const effect = await executeAdvanceCoderSuggestion({
      suggestion,
      currentSlug,
      route: modelRoute,
      applySlug: (route, slug) => withCoderSlot(route, slug),
      probe: probeRouteSmoke,
    });

    if (effect.kind === "noop") {
      return;
    }

    if (effect.kind === "stay_put") {
      await persistAdvanceBookkeeping(
        {
          step: forStep,
          ...effect.audit,
        },
        forStep,
        "stay-put",
      );
      console.info(
        `[orchestrator] #926 advanceCoder stay-put (${effect.reason}): ` +
          `kept ${currentSlug}; suggestion=${effect.suggestion}`,
      );
      return;
    }

    // advanced — hold sticky seat; retire prior coder session; follow billing pool.
    modelRoute = effect.route;
    stickyJudgeAdvanceCoderSlug = effect.toSlug;
    stepSpecs = stepSpecsForRoute(modelRoute);
    // Candidate already smoked — skip the next ensureRouteSmoke gate.
    routeSmokeChecked = true;
    // New coder: fresh session (memory = worktree git history + ledger only).
    coderSessionId = undefined;
    coderSessionModel = undefined;
    // Billing pool follows the new seat (same as Coder-Rec slot change).
    currentBillingPool = billingPoolFromQuotaPool(
      poolForModelRef(modelRoute.slots.coder),
    );

    await persistAdvanceBookkeeping(
      {
        step: forStep,
        ...effect.audit,
      },
      forStep,
      "advance",
    );
    console.info(
      `[orchestrator] #926 advanceCoder → ${effect.entry.id} (${effect.entry.slug}) ` +
        `from ${effect.fromSlug}; prior coder session retired`,
    );
  };

  /** #686 — apply a relay baton onto the wall-hit role slot (role-aware). */
  const applyRelayBaton = (baton: NextRelayBaton, wallStep?: StepId): void => {
    currentBillingPool = baton.pool;
    activeRelayStep = wallStep ?? "S2";
    const relaySlot = relaySlotForSingleSliceWallStep(wallStep ?? "S2");
    const slots = { ...modelRoute.slots };
    if (relaySlot === "verify") {
      // #923: S3/S6 judge openings share the verify slot.
      slots.verify = baton.slug;
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
    return modelRoute.slots[relaySlotForSingleSliceWallStep(wallStep)];
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
  const relayBriefForDispatch = (dispatchStep: StepId): string | undefined =>
    activeRelayStep === dispatchStep ? activeRelayBrief : undefined;
  const clearCompletedRelayState = (completedStep: StepId, completed: StepOutput | undefined): void => {
    if (
      activeRelayStep !== completedStep ||
      completed === undefined ||
      escalateOf(completed) !== undefined
    ) return;
    currentBillingPool = undefined;
    activeRelayBrief = undefined;
    activeRelayStep = undefined;
  };

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
  /**
   * #926 / #937 / #934 ID-008: consecutive review/fix no-baton stay-puts.
   * First stay-put is non-terminal (return to judge / preserve findings); a
   * second consecutive typed-429 wall with no baton parks for external reset
   * (ID-001) — never invents S8 error solely from candidate exhaustion.
   */
  let consecutiveReviewFixStayPuts = 0;
  /** Reviewer-declared open-count for S5/S6 (not findings-array length). */
  let pendingBlockingFindingCount = 0;
  let pendingRawReviewerArtifacts: WorkerLandingPayload["rawReviewerArtifacts"];
  /** Opaque continue_fixing scope for S5 landing (C-R4-2A); never filters cargo. */
  let pendingFixerFindingScope: FindingRepairScope | undefined;
  let findingDispositions: FindingDisposition[] = [];
  let lastReviewerStepId: StepId | undefined;
  let preexistingAssertionTouchedForReverify = false;
  let refusedFindingIdentityKeysForReverify: readonly string[] = [];
  /** #927 opaque refuse cargo for S6 judge re-adjudicate (not routing input). */
  let refuseRecordsForReverify: readonly ReviewFixRefuseRecord[] | undefined;
  // Preserve the full ledger for relay and resume accounting.
  let resumeHistoryLedger: ReadonlyArray<LedgerEntry> = [];

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
   * Resolve the ledger's `branchHEAD` value (#256 / #934 ID-015).
   *
   * Real Backend: the worktree HEAD commit SHA (`git rev-parse HEAD`) via the
   * optional `backend.worktreeHead`. When that optional read fails or returns
   * empty → warning + omit, never silent branch-name fallback.
   */
  async function resolveBranchHEAD(): Promise<string | undefined> {
    if (worktree === undefined || backend.worktreeHead === undefined) return undefined;
    try {
      const sha = await backend.worktreeHead(worktree);
      if (sha !== undefined && sha.length > 0) {
        return sha;
      }
      console.warn(
        "[orchestrator] optional branchHEAD read returned empty (omit)",
      );
      return undefined;
    } catch (err) {
      console.warn(
        `[orchestrator] optional branchHEAD read failed (omit): ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
      return undefined;
    }
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
    } catch (err) {
      // ID-005: secondary terminal-write failure must not mask the primary
      // fate, but must still land in stderr/diagnostics (not empty-catch).
      const msg = err instanceof Error ? err.message : String(err);
      console.error(
        `[orchestrator] persistBestEffort writeLedger(${s}) failed: ${msg}`,
      );
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
   *   - S1 PRE-worktree throws: prepareWorktree (which run
   *     BEFORE deriveStateDir sets stateDir).
   * In all these the in-memory ledger still records S8 and the run still returns
   * S8(error), but NOTHING is persisted. Only POST-worktree S1 (after
   * stateDir is fixed) and later steps persist their error termination.
   * So this contract does NOT promise "every S1 throw is persisted" — only
   * post-worktree ones.
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

    // #929 — non-success terminals must speak externally (not only return
    // errorPackage). stopForCoderRec already console.errors; keep the same
    // invariant on the shared errorTermination helper so mid-run crashes are
    // visible without parsing the RunResult.
    console.error(`[orchestrator] ${failedStep} failed: ${reason}`);

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
    // #929 — same non-success loudness invariant as errorTermination /
    // stopForCoderRec: operators must see the park without parsing RunResult.
    console.error(
      `[orchestrator] ${failedStep} escalated: ${escalation.reason} — ${escalation.diagnosis}`,
    );
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

  // ── #255 / #936: idempotent resume from Scene Action discovery ───────────
  // discoverResidentScene already ran at ignition (ID-005 Recovery first).
  // Crash-resume and escalate-resume share this ONE machine: read the ledger
  // (resume truth), reuse the worktree, and continue from the recorded
  // breakpoint — no re-cut from S0, no re-running done steps.
  logDriverStage("reconcile", `issue #${issueNumber}`);
  let resumeState: ResumeState | undefined =
    scene.kind === "resident" ? scene.state : undefined;
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
    // in-flight CLI monitor handle from the persisted ledger so observation +
    // exact-handle adoption/terminate can resume without global process-name
    // matching.
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

    // #925/#877: rebuild pending open-set / kill flips from the prior ledger
    // (judge continue + residual historical S4/reviewer open-count). Each
    // projection replaces the pending blocker set; prose dispositions do not
    // reopen findings. #899: also rebuild raw reviewer artifact pointers so a
    // crash/resume after S4 still hands the fixer host paths (materialised at
    // landing).
    const rebuiltBlocking = rebuildBlockingFromLedger(plan.priorLedger);
    pendingBlockingFindings = [...rebuiltBlocking.blocking];
    pendingBlockingFindingIdentityKeys = [...rebuiltBlocking.blockingIdentityKeys];
    pendingBlockingFindingCount = rebuiltBlocking.blockingFindingCount;
    findingDispositions = [...rebuiltBlocking.findingDispositions];
    pendingRawReviewerArtifacts = rebuiltBlocking.rawReviewerArtifacts;
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
    refuseRecordsForReverify = rebuilt.refuseRecords;

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
    // #925 / #919 S1: rebuild judge session from last judge-seat ledger row.
    for (let i = plan.priorLedger.length - 1; i >= 0; i -= 1) {
      const entry = plan.priorLedger[i]!;
      if (
        isJudgeSeat({ step: entry.step }) &&
        typeof entry.sessionId === "string"
      ) {
        judgeSessionId = entry.sessionId;
        judgeSessionModel =
          entry.step === "S6" ? stepSpecs.S6.model : stepSpecs.S3.model;
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
    // commits + baton state are the payload. Relay state is read from the
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
    // (first seat only — ADR 0132 deleted S6-count rotation) before the first
    // dispatch / top-of-loop smoke. Without this, applyCoderRecToRoute sees
    // undefined body → skippedForMissingMarking → silent preset revert.
    // #936: Coder-Rec body comes from live meta only — snapshot dual court deleted.
    // Coder-Rec is OPTIONAL: re-fetch failures must degrade safely — never
    // errorTerminate / poison the resume terminal state.
    try {
      const meta = await backend.fetchIssueMeta(issueNumber);
      if (typeof meta.body === "string" && meta.body.length > 0) {
        coderRecIssueBody = meta.body;
      }
    } catch {
      // fall through — continue with route preset
    }
    if (coderRecIssueBody === undefined || coderRecIssueBody.length === 0) {
      console.info(
        "[orchestrator] Coder-Rec resume re-fetch failed; continuing with route preset",
      );
    }
    const coderRecPolicy = await applyCoderRecSelection();
    if (coderRecPolicy?.kind === "stop") {
      return await stopForCoderRecTightRoutePolicy(coderRecPolicy.escalation);
    }

    // #926 — rebuild judge-advanced sticky seat from the latest successful
    // coder_advance row (before resource-relay, which still wins when present).
    for (let i = resumeLedger.length - 1; i >= 0; i--) {
      const row = resumeLedger[i]!;
      if (row.event === "coder_advance" && typeof row.toModelId === "string") {
        const advanced = lookupCoderRosterEntry(row.toModelId);
        const slug = advanced?.slug ?? row.toModelId;
        stickyJudgeAdvanceCoderSlug = slug;
        holdCoderSticky(slug);
        break;
      }
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
      activeRelayBrief = renderEphemeralRelayBrief(relayResume);
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
    // ledger so resume can rebuild the monitor handle for log last-activity without global pgrep.
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
          // #934 ID-003: GitHub auth needs external human login → typed decision
          // gate (same class as family admission), not infra errorTermination.
          if (isGithubAuthFailure(err)) {
            const diagnosis = err instanceof Error ? err.message : String(err);
            return await escalateTermination(
              "S0",
              {
                reason: "GitHub authentication required",
                diagnosis,
              },
              undefined,
              "decision",
              undefined,
              decisionGateParkStopSummary({
                summary: `GitHub authentication required: ${diagnosis}`,
                repairHint:
                  "run `gh auth login` (or restore GH_TOKEN) on the host, then re-feed",
              }),
            );
          }
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
        // S2/S5 re-apply first-seat stay-put below (no round rotation).
        coderRecIssueBody = meta.body;
        const coderRecPolicy = await applyCoderRecSelection();
        if (coderRecPolicy?.kind === "stop") {
          return await stopForCoderRecTightRoutePolicy(coderRecPolicy.escalation);
        }

        const smokeResult = await ensureRouteSmoke();
        if (smokeResult !== undefined) return smokeResult;

        break;
      }

      case "S1": {
        // S1 load_context — prepare resident worktree (base=`sliceBase`).
        // #936 / #934 ID-002: snapshot dual court deleted — workers live-fetch
        // issue truth; ledger is the only durable court after worksite exists.
        //
        // integ-cmr base r2 (C): prepareWorktree runs BEFORE the worktree
        // exists, so there is no sibling stateDir yet — its error termination
        // is UNPERSISTABLE (same special case as S0 fetch).
        try {
          worktree = await backend.prepareWorktree(issueNumber, sliceBase);
        } catch (err) {
          // PRE-worktree throw → unpersistable; S8(error) in-memory only.
          return await errorTermination("S1", err);
        }
        // Fix the stateDir to be a true sibling of the worktree root (#249) as
        // soon as the worktree exists so later error terminations persist.
        stateDir = deriveStateDir(worktree.path, issueNumber);
        break;
      }

      case "S2":
      case "S3":
      case "S5":
      case "S6": {
        // Productive steps:
        //   S2 coder implement, S3 judge establish, S5 coder fix,
        //   S6 judge resume (#925).
        // #924: S2 establishes a coder session; S5 rounds resume it (same
        // model). #925: S3 establishes a judge session; S6 rounds resume it.
        // Crash/escalate `resumeFor` still wins when set.
        if (!dispatchStageLogged) {
          logDriverStage("dispatch", `step=${step}`);
          dispatchStageLogged = true;
        }
        if (worktree === undefined) {
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
        // #767 / ADR 0132: before each coder dispatch, re-apply Coder-Rec
        // (first seat / sticky stay-put — no round-threshold rotation).
        // Re-smoke here if the route mutated, because the top-of-loop check
        // already ran for this iteration.
        if (step === "S2" || step === "S5") {
          const coderRecPolicy = await applyCoderRecSelection();
          if (coderRecPolicy?.kind === "stop") {
            return await stopForCoderRecTightRoutePolicy(coderRecPolicy.escalation);
          }
          if (!routeSmokeChecked) {
            const smokeResult = await ensureRouteSmoke();
            if (smokeResult !== undefined) return smokeResult;
          }
        }
        promptFile = stepSpecs[step].promptFile;
        const expectedKind = stepSpecs[step].role as "coder" | "reviewer" | "verify";
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
        /** Set when catch applies #926 stay-put and breaks to topology. */
        let reviewFixStayPutRouted = false;
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
          } else if (
            // #925 / #919 S1: S3→S6 (and multi-round S6) resumes retained judge session.
            isJudgeSeat({ step }) &&
            typeof judgeSessionId === "string" &&
            judgeSessionModel !== undefined &&
            stepSpecs[step].model === judgeSessionModel
          ) {
            resumeSessionId = judgeSessionId;
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
              const relayBrief = relayBriefForDispatch(step);
              const priorJudgeVerdicts = isJudgeSeat({ step })
                ? priorJudgeVerdictRowsFromLedger(ledger)
                : undefined;
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
                ...(relayBrief !== undefined ? { relayBrief } : {}),
                // #925: prior judge verdict rows for session-loss recovery /
                // trajectory (runner never synthesises a narrative summary).
                ...(priorJudgeVerdicts !== undefined &&
                priorJudgeVerdicts.length > 0
                  ? { priorJudgeVerdicts }
                  : {}),
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
                      // #927: refuseRecords cargo is landing-only (信封宪法).
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
                      // #919 M3 / #927: refuse traffic keys sole on thin ctx
                      // (above); landing carries opaque refuseRecords only.
                      // #927: four-reason + evidence cargo for judge re-adjudicate
                      // (landing only — never mirrored onto thin DispatchContext).
                      ...(step === "S6" &&
                      refuseRecordsForReverify !== undefined &&
                      refuseRecordsForReverify.length > 0
                        ? { refuseRecords: refuseRecordsForReverify }
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
              //  - JUDGE (S3/S6): typed status tri-state is the sole routing
              //    signal; SOE exhaust does NOT feed empty cargo to the fixer (#899).
              //
              // #661 / #937: process-level retry CONTINUES on the current scene —
              // no Git reset/checkout/clean. Uncommitted work is the payload.
              //
              // Reviewer: rethrow on throw-exhaust so S8(error) surfaces process
              // crashes and SOE exhaust alike — never feed empty cargo to fixer.
              // Coder keeps default failed→durable abort (existing escalate path).
              // #919 M4/M7: live judge seats are isJudgeSeat S3/S6 only
              // (role is always "verify" on those seats; dual-OR deleted).
              const durableRetryOpts = durableMechanicalRetryOptions(
                step,
                isJudgeSeat({ step })
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
                        // #934 ID-006 / #937: adoption/persist failure must
                        // terminate the exact ChildProcess — rethrow so
                        // dispatchWorkerWithMonitor runs terminateSpawnedChild.
                        if (isValidStepId(s.id)) {
                          await persistMonitorHandleAtSpawn(s.id, handle);
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
              if (result.kind === "completed") {
                completeMechanicalRetryInvocation(step);
                // Successful productive dispatch breaks the stay-put streak.
                consecutiveReviewFixStayPuts = 0;
              }
            }
            const { unwrapped, reason } = workerResultToStep(result, expectedKind);

            if (unwrapped === undefined) {
              // #934 ID-004 / #937: process-root exhaustion is the phase's
              // canonical failed edge — never a baton relay / park from silence.
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
            output = normalizeJudgeSeatOutput(step, normalized.output);
            stepSessionId = normalized.sessionId;
            // #924: retain coder session for S5 continuity (and multi-round S5).
            if (
              (step === "S2" || step === "S5") &&
              typeof stepSessionId === "string"
            ) {
              coderSessionId = stepSessionId;
              coderSessionModel = stepSpecs[step].model;
            }
            // #925 / #919 S1: retain judge session for S6 continuity.
            if (isJudgeSeat({ step }) && typeof stepSessionId === "string") {
              judgeSessionId = stepSessionId;
              judgeSessionModel = stepSpecs[step].model;
            }
            break;
          }
        } catch (err) {
          // #937: free-log SelfReportedRelayError / HangWithLivePoolError deleted
          // with the fourth fate channel. Decision gates arrive via typed station
          // escalate; hang no longer invents host kill+relay from silence.
          // #683/#686: 429 quota wall → park within T / no baton; relay beyond T
          // with a live baton (ephemeral brief, apply next baton, re-enter).
          //
          // #934 ID-008 / #926 / #937: review/fix (S3/S5/S6) no-candidate is
          // one stay-put seam — durable audit, keep owning coder, never invent
          // terminal solely from candidate exhaustion, no fabricated judge paper,
          // no clearing live findings. Topology returns to the persistent judge
          // (S5→S6) or re-enters the fix desk with preserved findings (S3/S6→S5).
          // After a full return-to-judge cycle still no baton: park for external
          // quota reset when the wall is typed 429 (ID-001 park), never S8 error.
          const isReviewFixSeat = isJudgeSeat({ step }) || step === "S5";
          const applyReviewFixStayPut = async (
            stayReason: string,
            stateSummary: string,
            parkErr?: QuotaWaitForResetError,
          ): Promise<"break" | RunResult> => {
            const stayModel = modelIdForWallStep(step);
            const stayTs = new Date().toISOString();
            const stayEntry = {
              step,
              event: "coder_advance_stay_put" as const,
              reason: stayReason,
              fromModelId: stayModel,
              toModelId: stayModel,
              state_summary: stateSummary,
              ts: stayTs,
            };
            ledger.push(stayEntry);
            // #926 / #934 ID-015: stay-put audit is required durable truth — not
            // fail-open. writeLedger failure surfaces as typed failed.
            if (stateDir !== undefined) {
              try {
                await backend.writeLedger(
                  {
                    ...stayEntry,
                    sessionId,
                    prompt_hash: await hashPrompt(undefined, step, backend),
                    branchHEAD: await resolveBranchHEAD(),
                    ts: stayTs,
                  },
                  stateDir,
                );
              } catch (writeErr) {
                return await errorTermination(
                  step,
                  new Error(
                    `record_persist_failed: coder_advance_stay_put audit: ${
                      writeErr instanceof Error
                        ? writeErr.message
                        : String(writeErr)
                    }`,
                  ),
                );
              }
            }
            consecutiveReviewFixStayPuts += 1;
            // Second consecutive no-baton wall after return-to-judge: wait for
            // external quota reset (ID-001 park) — never invent terminal from
            // candidate exhaustion (#926 / ID-008).
            if (consecutiveReviewFixStayPuts > 1 && parkErr !== undefined) {
              return await parkQuotaWaitForReset({
                step,
                err: parkErr,
                ledger,
                stateDir,
                sessionId,
                backend,
                resolveBranchHEAD,
                hashPrompt: (promptFile, s) =>
                  hashPrompt(promptFile, s, backend),
              });
            }
            if (step === "S5") {
              // #926: return result to persistent judge (S5→S6). Noop fix
              // receipt — live findings stay in pending* for S6.
              output = {
                kind: "coder",
                committed: false,
                commitsAdded: 0,
              };
              lastOutput = output;
              reviewFixStayPutRouted = true;
              return "break";
            }
            // S3/S6: never invent empty judge paper; never clear live findings.
            // Prefer prior continue paper so route → S5 with the same open set;
            // otherwise leave output undefined → unusable → S5 topology.
            if (
              lastOutput?.kind === "judge" &&
              lastOutput.status === "continue" &&
              pendingBlockingFindingCount > 0
            ) {
              output = lastOutput;
            } else {
              output = undefined;
            }
            // pendingBlockingFindings intentionally untouched.
            reviewFixStayPutRouted = true;
            return "break";
          };

          if (isQuotaWaitForResetError(err)) {
            const currentPool =
              currentBillingPool ?? billingPoolFromQuotaPool(err.pool);
            if (!canRelayInProcess()) {
              if (isReviewFixSeat) {
                const stay = await applyReviewFixStayPut(
                  `quota wall stay-put on ${step}: no live baton`,
                  err.message,
                  err,
                );
                if (stay !== "break") return stay;
                break;
              }
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
            if (outcome.kind === "park") {
              if (isReviewFixSeat) {
                const stay = await applyReviewFixStayPut(
                  `quota wall stay-put on ${step}: park/no baton`,
                  err.message,
                  err,
                );
                if (stay !== "break") return stay;
                break;
              }
              return outcome.result;
            }
            if (outcome.relayBrief !== undefined) {
              activeRelayBrief = outcome.relayBrief;
            }
            applyRelayBaton(outcome.nextBaton, step);
            continue orchestratorStepLoop;
          }
          // #686/#787/#937: capacity resource failure relays without retry
          // (never mechanical-retry / never reset). Hang/self-report free-log
          // constructors deleted with ID-006/007.
          // #934 ID-008: review/fix no-candidate is stay-put even when the
          // handoff chain is exhausted (canRelayInProcess false) — never invent
          // terminal solely from capacity candidate exhaustion.
          if (isCapacityRelayError(err)) {
            if (!canRelayInProcess()) {
              if (isReviewFixSeat) {
                const stay = await applyReviewFixStayPut(
                  `capacity stay-put on ${step}: no live baton`,
                  err instanceof Error ? err.message : String(err),
                );
                if (stay !== "break") return stay;
                break;
              }
              return await errorTermination(step, err);
            }
            const { currentPool, pools } = resolveResourceFailurePool({
              modelRef: modelRefForWallStep(step),
              capacity: true,
            });
            const handoff = await applyResourceFailureHandoff({
              trigger: "capacity",
              state_summary: "model checkpoint at capacity; drift preserved",
              reason: err instanceof Error ? err.message : String(err),
              currentModelId: modelIdForWallStep(step),
              currentPool,
              rosterOrder: resolveCoderRecOrder(coderRecIssueBody),
              pools,
              now: relayNow(),
              step,
            });
            if (handoff.kind !== "relay" || handoff.ledgerEntry === undefined) {
              if (isReviewFixSeat) {
                const stay = await applyReviewFixStayPut(
                  `capacity stay-put on ${step}: no live baton`,
                  err instanceof Error ? err.message : String(err),
                );
                if (stay !== "break") return stay;
                break;
              }
              return await errorTermination(step, err);
            }
            const entry = handoff.ledgerEntry;
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
                return await errorTermination(step, err);
              }
            }
            ledger.push(marker);
            activeRelayBrief = renderEphemeralRelayBrief(entry);
            completeMechanicalRetryInvocation(step);
            applyRelayBaton(handoff.nextBaton, step);
            continue orchestratorStepLoop;
          }
          return await errorTermination(step, err);
        }

        // Fresh host HEAD capture is best-effort telemetry/bookkeeping only.
        // Its availability cannot change the worker receipt's route.
        const coderHeadAfterStep = expectedKind === "coder"
          ? gitHead(worktree)
          : undefined;

        // #926 stay-put already set topology outputs and preserved live findings —
        // skip worker-output projection so we do not clear the open set.
        if (reviewFixStayPutRouted) {
          if (output !== undefined) lastOutput = output;
          break;
        }

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
          // #919 M4/M7: live open-set projection is sole isJudgeSeat (S3/S6).
          // Production role is always "verify" on those seats; expectedKind OR
          // was redundant. Residual role:"reviewer" is not live here.
          if (isJudgeSeat({ step })) {
            // #925: judge typed verdict is the sole routing signal. Unusable
            // envelope → fixer path with raw artifact pointers (never silent clean).
            if (output?.kind !== "judge") {
              pendingBlockingFindings = [];
              pendingBlockingFindingIdentityKeys = [];
              pendingBlockingFindingCount = 0;
              pendingRawReviewerArtifacts = reviewerRawArtifactPointers(
                stepMonitorHandle,
                stepSessionId,
              );
              // Seed findingDispositions empty; route() will send unusable → S5.
              lastOutput = output;
              break;
            }
            // Apply continue dispositions via the shared projection helper
            // (same helper resume rebuild uses — F2 single open-set seam).
            if (output.status === "continue") {
              const projected = projectJudgeContinueBlocking(output);
              if (projected !== undefined) {
                // Apply kill flips first, then gate empty live set (#919 M6).
                if (projected.killDispositions.length > 0) {
                  findingDispositions = [
                    ...findingDispositions,
                    ...projected.killDispositions,
                  ];
                }
                pendingBlockingFindings = projected.blocking;
                pendingBlockingFindingIdentityKeys =
                  projected.blockingIdentityKeys;
                pendingBlockingFindingCount = projected.blockingFindingCount;
                if (pendingBlockingFindingCount > 0) {
                  pendingRawReviewerArtifacts = reviewerRawArtifactPointers(
                    stepMonitorHandle,
                    stepSessionId,
                  );
                } else if (projected.blockingIdentityKeys.length === 0) {
                  // #919 M6 / family M1 isomorphic: empty continue is court
                  // contract drift — never empty-spin S5. Unusable (non-judge)
                  // still routes to S5 above; route() continue→S5 stays for
                  // non-empty live sets only.
                  const reason =
                    `judge ${step} continue with 0 live findings ` +
                    `(court contract drift; empty continue must not spin coder-fix)`;
                  return await errorTermination(step, new Error(reason), {
                    output,
                    findingDispositions,
                    stopSummary: contractDriftStopSummary({
                      summary: reason,
                      repairHint:
                        "judge status:continue requires non-empty live identity keys; " +
                        "re-open the same judge seat or repair the seat envelope — " +
                        "do not empty-spin S5 coder-fix",
                    }),
                  });
                }
              }
            } else {
              // converged / escalate: no open findings for S5.
              pendingBlockingFindings = [];
              pendingBlockingFindingIdentityKeys = [];
              pendingBlockingFindingCount = 0;
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
          // #677 / #927: legal refuse — envelope keys are traffic; refuseRecords
          // are opaque cargo for the S6 judge. Never escalate/park on refuse;
          // never drop envelope keys when cargo shape is non-#677.
          if (step === "S5") {
            const refuseLanding = coderRefuseReverifyLanding(output);
            refusedFindingIdentityKeysForReverify =
              refuseLanding.refusedFindingIdentityKeys;
            refuseRecordsForReverify = refuseLanding.refuseRecords;
          }
        }
        if (isJudgeSeat({ step })) lastReviewerStepId = step;
        if (step === "S5") {
          pendingRawReviewerArtifacts = undefined;
          pendingFixerFindingScope = undefined;
        }
        break;
      }

      case "S4": {
        // #925: S4 mechanical open-count station dissolved. Residual path for
        // legacy ledgers only — classification already applied at S3/S6.
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

    // #925 / #919 S1: verdict + kill flips land on judge seats (S4 residual).
    // Residual S4 still accepts dispositions if a legacy path writes them.
    const stepFindingDispositions =
      isJudgeSeat({ step }) || step === "S4" ? findingDispositions : undefined;

    // Record this step in the ledger (anti-skip + resume truth, ADR 0018 §3).
    // #249: also persist via backend.writeLedger (sibling state dir).
    // #919 CR U7/R2: advanceCoder sole source = output.advanceCoder (recovery /
    // priorJudgeVerdictRowsFromLedger). Top-level LedgerEntry.advanceCoder deleted
    // (zero readers; dual-write already gone). #926 owns any roster consumption.
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
      // #684: pass the monitor handle so resume can rebuild log last-activity observation.
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

    // #926: after a judge continue row is durably recorded, execute optional
    // advanceCoder (or stay-put + audit). Never terminals for roster unusability.
    // #919 R1: sole isJudgeSeat membership (no redundant S3||S6 string OR).
    // #934 ID-005: advance/stay-put ledger write is required durable truth —
    // persist failure must error-terminate, not continue with lost route truth.
    if (
      isJudgeSeat({ step }) &&
      output?.kind === "judge" &&
      output.status === "continue" &&
      typeof output.advanceCoder === "string"
    ) {
      try {
        // isJudgeSeat guarantees step/id is S3|S6 for applyJudgeAdvanceCoder.
        await applyJudgeAdvanceCoder(output.advanceCoder, step as "S3" | "S6");
      } catch (err) {
        return await errorTermination(
          step,
          err instanceof Error ? err : new Error(String(err)),
          { recordInMemory: false, output },
        );
      }
    }

    // A relay baton is a step-local override. Once its relayed step has
    // durably completed, normal downstream roles must reselect their own route.
    clearCompletedRelayState(step, output);

    // The runner — not the agent — decides the next step.
    // #925 / ADR 0132: topology advances from the judge status tri-state
    // (converged|continue|escalate) and explicit escalation; receipt cargo is
    // not a fate input. Residual open-count paper is projected before route().
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
        // #929 — speak before best-effort re-persist (same loudness class as
        // errorTermination; this path does not call that helper).
        console.error(
          `[orchestrator] S8 failed: writeLedger(S8) failed while persisting the handoff entry: ${cause}`,
        );
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
