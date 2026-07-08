/**
 * runOrchestrator — the runner loop (ADR 0018, corrected by ADR 0030).
 *
 * The runner drives the fixed single-slice sequence itself: it performs each
 * runner-action step or dispatches each worker step, writes a step-ledger
 * entry, then calls route() to pick the next step. The agent never decides
 * the next step — route() does.
 *
 * ADR 0030: the single-slice runner owns the visible per-slice review/fix loop:
 *
 *   S0(gate) → S1(context) → S2(implement) → S3(review) → S4(classify)
 *     clean/deferred only → S7(ship) → S8(handoff)
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
 *   - S2 committed:false → S8(error)  [route() detects]
 *   - S7 ship throws/escalates → S8(error)/S8(escalate)  [runner catch]
 *   - any backend call throws → S8(error) + error package  [runner catch]
 *   - the S2 worker carries escalate → S8(escalate) [route() detects]
 * Slice #253: StepSpec contract — model/completionSignal/maxIter/soul/toolchain.
 * Slice #248: S0 input gate — three-way accept condition (rfa ∧ no sub-issues ∧
 *   blocked_by all closed); violations throw, stopping at S0. (Agent Brief was
 *   removed as a gate — design correction; the coder reads the whole issue.)
 * #331 (ADR 0026 / PRD #330), extended by ADR 0030: the runner dispatches every
 *   WORKER step (S2/S3/S5/S6 agent workers + S7 ship) through the single unified
 *   seam `dispatchWorker(backend, spec, ctx)` (dispatchWorker.ts) instead of
 *   reaching for `runStep` / `resumeSession` / `push` directly.
 */

import { execFileSync } from "node:child_process";

import { hasAcceptedSuppressionAuthority } from "./acceptedSuppression.js";
import { route } from "./route.js";
import {
  adjudicatePriorClaimedFixedFindings,
  classifyFindings,
  findingIdentityKey,
} from "./findings.js";
// The unified worker-dispatch seam (ADR 0026 / PRD #330 #331): the runner
// dispatches EVERY worker step (S2/S3/S5/S6 agent workers + S7 ship) through ONE free function
// instead of reaching for runStep/resumeSession/push directly.
import {
  cleanupWorkerSpec,
  dispatchWorker,
  docReleaseWorkerSpec,
  fixerWorkerSpec,
  SHIP_PROMPT_FILE,
  shipWorkerSpec,
  stepSpecToWorkerSpec,
  verifyWorkerSpec,
  workerResultToStep,
} from "./dispatchWorker.js";
import {
  isValidCleanupResult,
  isValidDocReleaseResult,
  isValidFixerResult,
  isValidVerifyResult,
} from "./reviewLoopOutcome.js";
import {
  isLiveGithubReviewPollEnabled,
  pollPrReviewState,
  type PrReviewSnapshot,
} from "./botPolling.js";
import { withMechanicalRetry, type MechanicalRetryOptions } from "./dispatchRetry.js";
import {
  buildOnlineReviewLanding,
  clampVerifyConvergenceForCheckRuns,
  enforceRunnerOwnedRecheck,
  immediateBotPollClock,
  lastOnlineReviewFixCommitShaFromLedger,
  offlinePrReviewSnapshot,
  onlineReviewConvergedForHead,
  onlineReviewResumeHeadKeyFromLedger,
  onlineReviewRoundFromLedger,
  onlineReviewRoundTriggerFromLedger,
  resolveOnlineReviewRoundTrigger,
  realBotPollClock,
  reconstructOnlineReviewLandingForResume,
  retriggerBotsAndPoll,
  shipLedgerTriggeredAtFromSliceLedger,
  slicePendingRoundTriggerFromFixGap,
  slicePostFixVerifyPendingFromMarkerGap,
  onlineReviewFixerNothingToFixStopSummary,
  VerifyWorkerHeadMovedError,
  verifyReviewerHeadMovedStopSummary,
  verifySideEffectFailureStopSummary,
  waitForBotQuiescence,
  writeOnlineReviewSnapshotFile,
} from "./onlineReviewLoop.js";
import {
  assertOfflineSyntheticPollAdmissible,
  buildRoundTrigger,
  convergenceHeadToRecord,
  type RoundTrigger,
} from "./evidenceAdmissibility.js";
import {
  applyVerifySideEffects,
  fixMarkedKeysFromVerify,
} from "./onlineReviewSideEffects.js";
import {
  applyRuntimeTightRoutePolicy,
  modelForSlot,
  printableRouteLineup,
  resolveActiveModelRoute,
  type ModelRouteEnv,
  type ResolvedModelRoute,
} from "./modelRoutes.js";
import { isFilledString } from "./shipOutcome.js";
// Shared seam guards — single source of truth, also used by route(), so the
// coder-output / commitsAdded rules can never drift.
import {
  escalateOf,
  isValidEscalation,
  isValidStepOutput,
} from "./validate.js";
import {
  contractDriftStopSummary,
  infraFailureStopSummary,
  stopSummaryFromFindingDispositionEvidence,
  successStopSummary,
  type AcceptedSuppressionSummary,
  type StopSummary,
} from "./stopSummary.js";
import type {
  Backend,
  ContinueFixingEvent,
  ErrorPackage,
  Escalation,
  EscalationAnswerEvent,
  EscalationKind,
  Finding,
  FindingDisposition,
  HandoffStatus,
  IssueMeta,
  IssueSnapshot,
  LedgerEntry,
  PersistentLedgerEntry,
  RepairEvidence,
  ResumeState,
  RunInput,
  RunResult,
  StepId,
  ShipResult,
  StepOutput,
  StepSpec,
  WorkerLandingPayload,
  WorktreeHandle,
} from "./types.js";

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
  step: StepId;
  output: StepOutput | undefined;
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
  /** Runner-observed files changed by a coder step, for resume replay. */
  repairMovementPaths?: ReadonlyArray<string>;
  /** Terminal stop reason summary (#450). */
  stopSummary?: StopSummary;
}): PersistentLedgerEntry {
  let entry: PersistentLedgerEntry = {
    step: opts.step,
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
  if (opts.repairMovementPaths !== undefined) {
    entry = { ...entry, repairMovementPaths: opts.repairMovementPaths };
  }
  if (opts.stopSummary !== undefined) {
    entry = { ...entry, stopSummary: opts.stopSummary };
  }
  return entry;
}

/** v0.1 base for a single slice: always main (ADR 0017 §2). */
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
  readonly resumeStep: StepId;
  readonly resumeSessionId?: string;
  readonly escalationAnswer?: EscalationAnswerEvent;
  readonly continueFixingRepair?: ContinueFixingRepair;
  readonly lastOutput?: StepOutput;
  readonly priorLedger: ReadonlyArray<LedgerEntry>;
}

interface LandedCoderProtocolFailure {
  readonly index: number;
  readonly step: "S2" | "S5";
  readonly previousHead: string;
  readonly branchHead: string;
}

function isValidStepId(value: unknown): value is StepId {
  return (
    value === "S0" ||
    value === "S1" ||
    value === "S2" ||
    value === "S3" ||
    value === "S4" ||
    value === "S5" ||
    value === "S6" ||
    value === "S7" ||
    value === "S8" ||
    value === "S9" ||
    value === "S10" ||
    value === "S11" ||
    value === "S12"
  );
}

function isEscalationAnswerEntry(
  entry: LedgerEntry,
): entry is LedgerEntry & EscalationAnswerEvent {
  const raw = entry as unknown as Record<string, unknown>;
  return (
    entry.event === "escalation_answered" &&
    entry.output === undefined &&
    raw.verdict === undefined &&
    isValidStepId(entry.forStep) &&
    typeof entry.answer === "string" &&
    entry.answer.trim().length > 0 &&
    (entry.note === undefined || typeof entry.note === "string") &&
    (entry.source === undefined || isBookkeepingSource(entry.source)) &&
    (entry.findingIdentityKey === undefined ||
      typeof entry.findingIdentityKey === "string") &&
    (entry.findingScope === undefined ||
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
    ...(entry.note !== undefined ? { note: entry.note } : {}),
    source: entry.source ?? "human",
    ...(entry.findingIdentityKey !== undefined
      ? { findingIdentityKey: entry.findingIdentityKey }
      : {}),
    ...(entry.findingScope !== undefined
      ? { findingScope: entry.findingScope }
      : {}),
  };
}

function isBookkeepingEntry(entry: LedgerEntry): boolean {
  return entry.event !== undefined;
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

function normaliseScopePart(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
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

function stripLocationLine(value: string): string {
  const withoutLineColumn = value
    .trim()
    .replace(/:\d+(?::\d+)?(?::[^:/\\]+)?$/, "");
  const withoutSymbol = withoutLineColumn.replace(/:[^:/\\]+$/, "").trim();
  if (/^[A-Za-z]$/.test(withoutSymbol) && /^[A-Za-z]:$/.test(withoutLineColumn)) {
    return `${withoutSymbol}:`;
  }
  return withoutSymbol;
}

function locationScopeMatches(scope: string, location: string): boolean {
  const normalisedScope = normaliseScopePart(stripLocationLine(scope));
  const normalisedLocation = normaliseScopePart(location);
  const normalisedLocationPath = normaliseScopePart(stripLocationLine(location));
  if (
    normalisedScope === normalisedLocation ||
    normalisedScope === normalisedLocationPath
  ) {
    return true;
  }
  return (
    normalisedLocationPath.startsWith(`${normalisedScope}/`) ||
    normalisedLocationPath.endsWith(`/${normalisedScope}`) ||
    normalisedLocationPath.includes(`/${normalisedScope}/`)
  );
}

function textScopeMatches(scope: string, values: ReadonlyArray<string>): boolean {
  const normalisedScope = normaliseScopePart(scope);
  return values.some((value) => normaliseScopePart(value) === normalisedScope);
}

function findingMatchesBroadScope(
  finding: Finding,
  key: string,
  scope: NonNullable<ContinueFixingEvent["findingScope"]>,
): boolean {
  const locationScopes = scope.locations ?? [];
  const categoryScopes = scope.categories ?? [];
  const groupScope = scope.findingGroup;
  const contextScope = scope.reviewContext;
  const featureScope = scope.featureArea;
  const textualValues = [finding.category, finding.claim_quote, key];

  const locationMatches =
    locationScopes.length === 0 ||
    locationScopes.some((location) =>
      locationScopeMatches(location, finding.location),
    );
  const categoryMatches =
    categoryScopes.length === 0 ||
    categoryScopes.some((category) =>
      textScopeMatches(category, [finding.category]),
    );
  const groupMatches =
    groupScope === undefined ||
    locationScopeMatches(groupScope, finding.location) ||
    textScopeMatches(groupScope, textualValues);
  const contextMatches =
    contextScope === undefined ||
    locationScopeMatches(contextScope, finding.location) ||
    textScopeMatches(contextScope, textualValues);
  const featureMatches =
    featureScope === undefined ||
    locationScopeMatches(featureScope, finding.location) ||
    textScopeMatches(featureScope, textualValues);

  return (
    locationMatches &&
    categoryMatches &&
    groupMatches &&
    contextMatches &&
    featureMatches
  );
}

function isContinueFixingEntry(
  entry: LedgerEntry,
): entry is LedgerEntry & ContinueFixingEvent {
  const raw = entry as unknown as Record<string, unknown>;
  return (
    entry.event === "runner_bookkeeping" &&
    entry.output === undefined &&
    raw.verdict === undefined &&
    entry.intent === "continue_fixing" &&
    isExecutableContinueFixingSource(entry.source) &&
    typeof entry.ts === "string" &&
    entry.ts.trim().length > 0 &&
    (entry.reason === undefined || typeof entry.reason === "string") &&
    (entry.findingIdentityKey === undefined ||
      typeof entry.findingIdentityKey === "string") &&
    (entry.findingScope === undefined ||
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

function matchingContinueFixingKeys(
  event: ContinueFixingEvent,
  activeFindings: ReadonlyArray<Finding>,
  activeIdentityKeys: ReadonlyArray<string>,
): ReadonlyArray<string> {
  const exactKeys = new Set<string>();
  const addKey = (key: string | undefined) => {
    if (key !== undefined && key.trim().length > 0) exactKeys.add(key);
  };
  addKey(event.findingIdentityKey);
  for (const key of event.findingScope?.identityKeys ?? []) addKey(key);

  const exactMatches = activeIdentityKeys.filter((key) => exactKeys.has(key));
  if (exactMatches.length > 0) return exactMatches;

  const scope = event.findingScope;
  if (scope === undefined) return [];
  const hasBroadScope =
    (scope.locations?.length ?? 0) > 0 ||
    (scope.categories?.length ?? 0) > 0 ||
    (scope.findingGroup?.trim().length ?? 0) > 0 ||
    (scope.reviewContext?.trim().length ?? 0) > 0 ||
    (scope.featureArea?.trim().length ?? 0) > 0;
  if (!hasBroadScope) return [];

  const broadMatches = activeFindings
    .map((finding, index) => ({ finding, key: activeIdentityKeys[index] }))
    .filter(({ finding, key }) => {
      if (key === undefined) return false;
      return findingMatchesBroadScope(finding, key, scope);
    })
    .map(({ key }) => key!);

  // Broad module/file scopes must not reset sibling findings together. Without
  // a durable exact identity/group key, only a single active match is safe.
  return broadMatches.length === 1 ? broadMatches : [];
}

function normalizeGitPath(path: string): string | undefined {
  const trimmed = path.trim();
  if (trimmed.length === 0) return undefined;
  const renameTarget = trimmed.includes(" -> ")
    ? trimmed.slice(trimmed.lastIndexOf(" -> ") + 4)
    : trimmed;
  const unquoted =
    renameTarget.startsWith('"') && renameTarget.endsWith('"')
      ? renameTarget.slice(1, -1)
      : renameTarget;
  const normalized = unquoted.trim().replace(/\\/g, "/");
  return normalized.length > 0 ? normalized : undefined;
}

function normalizeRepairEvidencePath(path: string): string | undefined {
  const normalized = normalizeGitPath(path);
  if (normalized === undefined) return undefined;
  if (/\s/.test(normalized)) return undefined;
  return normalized.includes("/") || /\.[A-Za-z0-9]+$/.test(normalized)
    ? normalized
    : undefined;
}

function gitOutputLines(
  worktree: WorktreeHandle | undefined,
  args: ReadonlyArray<string>,
): string[] {
  if (worktree === undefined) return [];
  try {
    return execFileSync("git", ["-C", worktree.path, ...args], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    })
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
  } catch {
    return [];
  }
}

function gitHead(worktree: WorktreeHandle | undefined): string | undefined {
  return gitOutputLines(worktree, ["rev-parse", "HEAD"])[0];
}

function actualRepairMovementPaths(
  worktree: WorktreeHandle | undefined,
  sinceHead?: string,
): ReadonlyArray<string> {
  if (worktree === undefined) return [];
  const paths = new Set<string>();
  const add = (path: string | undefined): void => {
    if (path !== undefined) paths.add(path);
  };

  if (sinceHead !== undefined) {
    for (const line of gitOutputLines(worktree, [
      "diff",
      "--name-only",
      `${sinceHead}..HEAD`,
    ])) {
      add(normalizeGitPath(line));
    }
  }
  for (const line of gitOutputLines(worktree, ["status", "--porcelain"])) {
    add(normalizeGitPath(line.length > 3 ? line.slice(3) : line));
  }

  return [...paths];
}

function repairEvidenceMatchesKey(
  evidence: RepairEvidence | undefined,
  actualChangedPaths: ReadonlyArray<string>,
  finding: Finding,
  identityKey: string,
  activeFindings: ReadonlyArray<Finding>,
  activeIdentityKeys: ReadonlyArray<string>,
): boolean {
  if (evidence === undefined || actualChangedPaths.length === 0) {
    return false;
  }
  const matchingKeys = matchingContinueFixingKeys(
    {
      event: "runner_bookkeeping",
      intent: "continue_fixing",
      source: "resume_input",
      ts: "repair-evidence",
      findingScope: evidence.findingScope,
    },
    activeFindings,
    activeIdentityKeys,
  );
  if (!matchingKeys.includes(identityKey)) return false;
  const declaredChangedPaths = [
    ...(evidence.changedFiles ?? []).map(normalizeGitPath),
    ...(evidence.fixtures ?? []).map(normalizeGitPath),
    ...(evidence.tests ?? []).map(normalizeRepairEvidencePath),
  ].filter((path): path is string => path !== undefined);
  const scopedActualMovement = actualChangedPaths.some((path) =>
    locationScopeMatches(path, finding.location),
  );
  const declaredActualMovement =
    declaredChangedPaths.length > 0 &&
    declaredChangedPaths.some((declared) =>
      actualChangedPaths.some(
        (actual) =>
          actual === declared ||
          locationScopeMatches(actual, declared) ||
          locationScopeMatches(declared, actual),
      ),
    );
  if (!scopedActualMovement && !declaredActualMovement) return false;
  return (
    declaredChangedPaths.length === 0 ||
    declaredActualMovement ||
    declaredChangedPaths.some((path) => locationScopeMatches(path, finding.location))
  );
}

const FINDING_SEVERITY_RANK: Readonly<Record<Finding["severity"], number>> = {
  clarity: 0,
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

function sameFindingLineage(a: Finding, b: Finding): boolean {
  return a.category === b.category && a.location === b.location;
}

function reviewerObservedProgress(input: {
  readonly previousBlockingFindings: ReadonlyArray<Finding>;
  readonly previousBlockingIdentityKeys: ReadonlyArray<string>;
  readonly currentBlockingFindings: ReadonlyArray<Finding>;
  readonly currentBlockingIdentityKeys: ReadonlyArray<string>;
  readonly previousFinding: Finding;
  readonly previousIdentityKey: string;
  readonly previousNoProgressCount: number;
}): boolean {
  const currentBySameKey = input.currentBlockingFindings.find(
    (finding) => findingIdentityKey(finding) === input.previousIdentityKey,
  );
  if (
    currentBySameKey !== undefined &&
    FINDING_SEVERITY_RANK[currentBySameKey.severity] <
      FINDING_SEVERITY_RANK[input.previousFinding.severity]
  ) {
    return true;
  }

  return input.currentBlockingFindings.some(
    (finding) =>
      sameFindingLineage(input.previousFinding, finding) &&
      FINDING_SEVERITY_RANK[finding.severity] <
        FINDING_SEVERITY_RANK[input.previousFinding.severity],
  );
}

interface LatestCoderRepair {
  readonly repairEvidence?: RepairEvidence;
  readonly repairMovementPaths: ReadonlyArray<string>;
}

function latestCoderRepair(ledger: ReadonlyArray<LedgerEntry>): LatestCoderRepair {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    const output = entry.output;
    if (output?.kind === "coder") {
      return {
        repairEvidence: output.repairEvidence,
        repairMovementPaths: entry.repairMovementPaths ?? [],
      };
    }
  }
  return { repairMovementPaths: [] };
}

interface ContinueFixingRepair {
  readonly event: ContinueFixingEvent | EscalationAnswerEvent;
  readonly matchingIdentityKeys: ReadonlyArray<string>;
}

function continueRepairFromEvent(
  event: ContinueFixingEvent,
  replay: Pick<S4AdjudicationReplay, "blocking" | "blockingIdentityKeys">,
): ContinueFixingRepair | undefined {
  const matchingIdentityKeys = matchingContinueFixingKeys(
    event,
    replay.blocking,
    replay.blockingIdentityKeys,
  );
  if (matchingIdentityKeys.length === 0) return undefined;
  return { event, matchingIdentityKeys };
}

function continueRepairFromAnswer(
  answer: EscalationAnswerEvent | undefined,
  replay: Pick<S4AdjudicationReplay, "blocking" | "blockingIdentityKeys">,
): ContinueFixingRepair | undefined {
  if (answer === undefined || !answerMapsToContinueFixing(answer)) {
    return undefined;
  }
  const source = answer.source;
  if (!isExecutableEscalationAnswerSource(source)) return undefined;
  const matchingIdentityKeys = matchingContinueFixingKeys(
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
    replay.blocking,
    replay.blockingIdentityKeys,
  );
  if (matchingIdentityKeys.length === 0) return undefined;
  return { event: answer, matchingIdentityKeys };
}

function latestContinueFixingAfter(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
  index: number,
  replay: Pick<S4AdjudicationReplay, "blocking" | "blockingIdentityKeys">,
): ContinueFixingRepair | undefined {
  for (let i = ledger.length - 1; i > index; i--) {
    const entry = ledger[i]!;
    if (!isContinueFixingEntry(entry)) continue;
    const repair = continueRepairFromEvent(entry, replay);
    if (repair !== undefined) return repair;
  }
  return undefined;
}

function escalationKindForHandoff(
  status: HandoffStatus,
  output: StepOutput | undefined,
): EscalationKind | undefined {
  if (status !== "escalate") return undefined;
  const escalation = escalateOf(output);
  // #604 correctness r1 (P1-a) / ADR 0062: the DECISION gate (B-class park) fires
  // ONLY for a worker-PROACTIVE "需人类拍板" escalate. A well-shaped escalate that
  // the RUNNER SYNTHESIZED from a protocol failure (malformed reviewer output
  // exhausted its reruns — marked `synthesizedFailure`) is an infra/protocol
  // FAILURE (A-class), not a decision, even though its reason/diagnosis are
  // well-formed strings. So a valid escalate maps to "decision" ONLY when it is
  // NOT a synthesized failure.
  if (escalation == null || !isValidEscalation(escalation)) return "failure";
  return escalation.synthesizedFailure === true ? "failure" : "decision";
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
    if (ledger[i]!.output !== undefined) return ledger[i];
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
): StepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    if (ledger[i]!.output !== undefined) return ledger[i]!.step;
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
): StepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    if (ledger[i]!.step !== "S8") return ledger[i]!.step;
  }
  return undefined;
}

function isReviewLoopStep(step: StepId): boolean {
  return step === "S9" || step === "S10" || step === "S11" || step === "S12";
}

function shipStatusFromLedger(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.step === "S7" && entry.output?.kind === "ship") {
      return entry.output.status;
    }
  }
  return undefined;
}

/** Drop superseded S9–S12 entries when resuming mid online-review loop (#600 F3). */
function priorLedgerThroughLastShip(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): ReadonlyArray<LedgerEntry> {
  let shipIdx = -1;
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (
      !isBookkeepingEntry(entry) &&
      entry.step === "S7" &&
      entry.output?.kind === "ship"
    ) {
      shipIdx = i;
      break;
    }
  }
  if (shipIdx < 0) {
    return ledger as ReadonlyArray<LedgerEntry>;
  }
  return ledger.slice(0, shipIdx + 1) as ReadonlyArray<LedgerEntry>;
}

function isLikelyGitSha(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{7,64}$/.test(value);
}

const CODER_STDOUT_MISSING_TAG_RE =
  /\bcoder step stdout carried no <coder>[\s\S]*tag\b/i;
const WORKER_STDOUT_MISSING_TAG_RE =
  /\b(?:coder step stdout carried no <coder>|reviewer step stdout carried no <review>)[\s\S]*tag\b/i;

function isRecoverableCoderProtocolFailure(
  entry: PersistentLedgerEntry,
): boolean {
  if (
    entry.step !== "S8" ||
    entry.handoffStatus !== "error" ||
    entry.stopSummary === undefined
  ) {
    return false;
  }

  return CODER_STDOUT_MISSING_TAG_RE.test(entry.stopSummary.summary);
}

function protocolFailedLandedCoderStep(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
): LandedCoderProtocolFailure | undefined {
  if (ledger.length < 2) return undefined;
  const last = ledger[ledger.length - 1]!;
  if (!isRecoverableCoderProtocolFailure(last)) return undefined;

  let i = ledger.length - 2;
  while (i >= 0 && ledger[i]!.step === "S8") {
    i--;
  }
  if (i < 0) return undefined;

  const entry = ledger[i]!;
  if (
    (entry.step !== "S2" && entry.step !== "S5") ||
    entry.output !== undefined ||
    !isLikelyGitSha(entry.branchHEAD)
  ) {
    return undefined;
  }

  let previousHead: string | undefined;
  for (let j = i - 1; j >= 0; j--) {
    if (ledger[j]!.step === "S8") continue;
    const head = ledger[j]!.branchHEAD;
    if (isLikelyGitSha(head)) {
      previousHead = head;
      break;
    }
  }
  if (previousHead === undefined || previousHead === entry.branchHEAD) {
    return undefined;
  }
  return {
    index: i,
    step: entry.step,
    previousHead,
    branchHead: entry.branchHEAD,
  };
}

function ledgerThroughRecoveredCoderOutput(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
  landedProtocolFailure: {
    readonly index: number;
    readonly output: StepOutput;
  },
): ReadonlyArray<LedgerEntry> {
  return ledger
    .slice(0, landedProtocolFailure.index + 1)
    .map((entry, index) =>
      index === landedProtocolFailure.index
        ? { ...entry, output: landedProtocolFailure.output }
        : entry,
    ) as ReadonlyArray<LedgerEntry>;
}

async function planRecoveredLandedCoderProtocolFailure(
  ledger: ReadonlyArray<PersistentLedgerEntry>,
  worktree: WorktreeHandle,
  backend: Backend,
): Promise<ResumePlan | undefined> {
  const executableLedger = executableLedgerEntries(ledger);
  const landedProtocolFailure =
    protocolFailedLandedCoderStep(executableLedger);
  if (
    landedProtocolFailure === undefined ||
    backend.countCommitsBetween === undefined
  ) {
    return undefined;
  }

  let commitsAdded: number;
  try {
    commitsAdded = await backend.countCommitsBetween(
      worktree,
      landedProtocolFailure.previousHead,
      landedProtocolFailure.branchHead,
    );
  } catch {
    return undefined;
  }

  if (!Number.isInteger(commitsAdded) || commitsAdded <= 0) {
    return undefined;
  }

  const output: StepOutput = {
    kind: "coder",
    committed: true,
    commitsAdded,
  };
  const pendingBlockingFindings =
    landedProtocolFailure.step === "S5"
      ? adjudicatedBlockingFindingsForPersistedS4(executableLedger)
      : undefined;
  const decision = route({
    from: landedProtocolFailure.step,
    output,
    ...(pendingBlockingFindings !== undefined
      ? { pendingBlockingFindings }
      : {}),
  });
  if (decision.kind === "handoff") {
    return undefined;
  }

  return {
    resumeStep: decision.step,
    lastOutput: output,
    priorLedger: ledgerThroughRecoveredCoderOutput(
      executableLedger,
      {
        index: landedProtocolFailure.index,
        output,
      },
    ),
  };
}

function lastReviewerStep(
  ledger: ReadonlyArray<LedgerEntry>,
): StepId | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.output?.kind === "reviewer") return entry.step;
  }
  return undefined;
}

interface S4AdjudicationReplay {
  readonly blocking: ReadonlyArray<Finding>;
  readonly blockingIdentityKeys: ReadonlyArray<string>;
  readonly deferred: ReadonlyArray<Finding>;
  readonly findingDispositions: ReadonlyArray<FindingDisposition>;
  readonly noProgressCounts: ReadonlyMap<string, number>;
}

function replayS4AdjudicationState(
  ledger: ReadonlyArray<LedgerEntry>,
): S4AdjudicationReplay {
  let pendingBlockingFindings: Finding[] = [];
  let pendingBlockingFindingIdentityKeys: string[] = [];
  let deferredFindings: Finding[] = [];
  let findingDispositions: FindingDisposition[] = [];
  const noProgressCounts = new Map<string, number>();
  let lastReviewerOutputForS4: StepOutput | undefined;
  let lastReviewerStepForS4: StepId | undefined;
  let lastCoderRepairEvidenceForS4: RepairEvidence | undefined;
  let lastCoderActualRepairPathsForS4: ReadonlyArray<string> = [];

  for (const entry of ledger) {
    if (isBookkeepingEntry(entry)) {
      continue;
    }
    if (entry.output?.kind === "coder") {
      lastCoderRepairEvidenceForS4 = entry.output.repairEvidence;
      lastCoderActualRepairPathsForS4 = entry.repairMovementPaths ?? [];
    }
    if (entry.output?.kind === "reviewer") {
      lastReviewerOutputForS4 = entry.output;
      lastReviewerStepForS4 = entry.step;
      continue;
    }
    if (entry.step !== "S4" || lastReviewerOutputForS4?.kind !== "reviewer") {
      continue;
    }

    const classification = classifyFindings(
      lastReviewerOutputForS4.findings,
      findingDispositions,
    );
    const reviewerBlocking = [...classification.blocking];
    const reviewerBlockingIdentityKeys = reviewerBlocking.map(findingIdentityKey);
    let blocking = [...classification.blocking];
    let blockingIdentityKeys = blocking.map(findingIdentityKey);
    findingDispositions = [
      ...(entry.findingDispositions ?? classification.dispositions),
    ];

    if (
      lastReviewerStepForS4 === "S6" &&
      pendingBlockingFindingIdentityKeys.length > 0
    ) {
      const adjudication = adjudicatePriorClaimedFixedFindings({
        priorFindings: pendingBlockingFindings,
        priorIdentityKeys: pendingBlockingFindingIdentityKeys,
        review: lastReviewerOutputForS4,
      });
      for (const key of adjudication.verifiedClosedIdentityKeys) {
        noProgressCounts.delete(key);
      }
      const seenBlocking = new Set(blockingIdentityKeys);
      for (const finding of adjudication.stillOpen) {
        const key = findingIdentityKey(finding);
        const previousFinding =
          pendingBlockingFindings[
            pendingBlockingFindingIdentityKeys.indexOf(key)
          ] ?? finding;
        const observedReviewerProgress = reviewerObservedProgress({
          previousBlockingFindings: pendingBlockingFindings,
          previousBlockingIdentityKeys: pendingBlockingFindingIdentityKeys,
          currentBlockingFindings: reviewerBlocking,
          currentBlockingIdentityKeys: reviewerBlockingIdentityKeys,
          previousFinding,
          previousIdentityKey: key,
          previousNoProgressCount: noProgressCounts.get(key) ?? 0,
        });
        if (!seenBlocking.has(key)) {
          blocking.push(finding);
          blockingIdentityKeys.push(key);
          seenBlocking.add(key);
        }
        if (
          repairEvidenceMatchesKey(
            lastCoderRepairEvidenceForS4,
            lastCoderActualRepairPathsForS4,
            finding,
            key,
            pendingBlockingFindings,
            pendingBlockingFindingIdentityKeys,
          ) ||
          observedReviewerProgress
        ) {
          noProgressCounts.set(key, 0);
        } else {
          noProgressCounts.set(key, (noProgressCounts.get(key) ?? 0) + 1);
        }
      }
    }

    const blockingKeys = new Set(blockingIdentityKeys);
    deferredFindings = deferredFindings.filter(
      (finding) => !blockingKeys.has(findingIdentityKey(finding)),
    );
    const deferredKeys = new Set(deferredFindings.map(findingIdentityKey));
    for (const finding of classification.deferred) {
      const key = findingIdentityKey(finding);
      if (!deferredKeys.has(key)) {
        deferredFindings.push(finding);
        deferredKeys.add(key);
      }
    }
    pendingBlockingFindings = blocking;
    pendingBlockingFindingIdentityKeys = blockingIdentityKeys;
    if (lastReviewerStepForS4 !== "S6") {
      for (const key of blockingIdentityKeys) {
        if (!noProgressCounts.has(key)) noProgressCounts.set(key, 0);
      }
    }
  }

  return {
    blocking: pendingBlockingFindings,
    blockingIdentityKeys: pendingBlockingFindingIdentityKeys,
    deferred: deferredFindings,
    findingDispositions,
    noProgressCounts,
  };
}

function adjudicatedBlockingFindingsForPersistedS4(
  ledger: ReadonlyArray<LedgerEntry>,
): ReadonlyArray<Finding> | undefined {
  return replayS4AdjudicationState(ledger).blocking;
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
    const replayedS4 = replayS4AdjudicationState(executableLedger);
    const answer =
      decisionStep !== undefined
        ? latestAnswerAfter(ledger, lastEntryIndex, decisionStep)
        : undefined;
    const continueFixingRepair =
      decisionStep === "S4"
        ? repairIntent !== undefined
          ? continueRepairFromEvent(repairIntent, replayedS4)
          : latestContinueFixingAfter(ledger, lastEntryIndex, replayedS4) ??
            continueRepairFromAnswer(answer, replayedS4)
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

    if (decisionStep === "S7") {
      let reopenIdx = executableLedger.length - 1;
      while (reopenIdx >= 0 && executableLedger[reopenIdx]!.step === "S8") {
        reopenIdx--;
      }
      return {
        resumeStep: "S7",
        escalationAnswer: answer,
        lastOutput: agentEntry?.output,
        priorLedger: executableLedger.slice(0, reopenIdx) as ReadonlyArray<LedgerEntry>,
      };
    }

    if (
      agentEntry !== undefined &&
      agentEntry.step === decisionStep &&
      isValidEscalation(escalateOf(agentEntry.output))
    ) {
      const escalatedLedgerIdx = ledger.lastIndexOf(agentEntry);
      return {
        resumeStep: agentEntry.step,
        resumeSessionId: agentEntry.sessionId,
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
  // output carries a WELL-FORMED escalation. Only a later escalation_answered row
  // re-opens THAT step in its original agent session; otherwise the prior
  // S8(escalate) remains a pause.
  //
  // integ-cmr m2 r1 (Finding 2): the guard is isValidEscalation, NOT a bare
  // non-null check. route.ts:81 / validate.ts treat a MALFORMED escalate (e.g.
  // `{}`, blank reason/diagnosis) as a contract violation → S8(status=error),
  // and the runner tags that S8 handoffStatus:'error'. With a bare `!= null`
  // check, Case 2 would fire on the garbage escalate BEFORE Case 3a's
  // terminal-status report, silently re-running the step via resumeSession
  // instead of reporting the true tagged error. Gating on isValidEscalation lets
  // a malformed escalate fall through to Case 3a — only a well-shaped escalate
  // plus a later answer event (a real "human answered an escalation" signal)
  // triggers escalate-resume.
  //
  // integ-cmr m2 r2 (#252 ⋈ #255): a tagged terminal S8(error) ALSO supersedes
  // escalate-resume, even when the escalate is WELL-FORMED. An escalate handoff
  // whose S8 write faulted returns status:error in-run and best-effort persists
  // a tagged 'error' S8 — the disk then holds a valid-escalate agent entry AND a
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
      resumeSessionId: agentEntry.sessionId,
      escalationAnswer: answer,
      lastOutput: agentEntry.output,
      priorLedger: priorLedger as ReadonlyArray<LedgerEntry>,
    };
  }

  // Case 2b (integ-cmr int-r1, C-1): S7 SHIP escalate-resume. ship.md promises a
  // ship `escalate` (gstack-ship STOP/HITL) is a real blocker the human answers →
  // the runner RE-OPENS S7. But S7 is a runner-ACTION step, and ship outputs
  // deliberately carry NO `escalate` field (escalateOf returns undefined for
  // them — validate.ts), so escalateTermination("S7", …) records the failing S7
  // entry WITHOUT an escalate output, then a trailing S8 tagged 'escalate'. Case 2
  // (agent escalate-resume) therefore never fires for S7, and Case 3a below would
  // report the escalate as a terminal status — leaving the slice permanently stuck
  // (#331 left this to #336; integ-cmr judged it the real S7-escalate-resume gap).
  //
  // Recognise the pattern — last entry is S8(escalate), the deciding step is S7,
  // and a later answer row exists — and RE-DISPATCH S7 (re-run the ship worker
  // fresh; ship is a clean-session runner action, so there is no agent session to
  // resumeSession into). Drop the trailing S8 boundary: we are re-opening, so the
  // prior terminal is superseded.
  // Only the SHIP step re-opens this way; an agent escalate (S2 build worker) is
  // caught by Case 2 above (it has a well-formed escalate output) and never reaches here.
  if (
    lastEntry.step === "S8" &&
    lastEntry.handoffStatus === "escalate" &&
    lastNonTerminalStep(executableLedger) === "S7"
  ) {
    const answer = latestAnswerAfter(ledger, lastEntryIndex, "S7");
    if (answer === undefined) {
      return {
        terminalStatus: "escalate",
        resumeStep: "S8",
        lastOutput: agentEntry?.output,
        priorLedger: ledger as ReadonlyArray<LedgerEntry>,
      };
    }
    // Re-opening S7 means the OLD S7 entry is superseded — drop BOTH the trailing
    // S8(escalate) boundary AND the failing S7 entry it terminated. Slicing only at
    // the S8 (the old `slice(0, s8Idx)`) LEFT the old S7 in the in-memory ledger, so
    // the re-dispatch appended a SECOND S7 → two consecutive S7 entries (online
    // review r1, 3 bots). The escalate-resume contract re-opens the step, it does
    // not keep the superseded one. The S7 entry being re-opened is the last
    // non-terminal (non-S8) entry; truncate at its index.
    let reopenIdx = executableLedger.length - 1;
    while (reopenIdx >= 0 && executableLedger[reopenIdx]!.step === "S8") reopenIdx--;
    // reopenIdx now points at the failing S7 entry (lastNonTerminalStep === "S7").
    return {
      resumeStep: "S7",
      escalationAnswer: answer,
      lastOutput: agentEntry?.output,
      priorLedger: executableLedger.slice(0, reopenIdx) as ReadonlyArray<LedgerEntry>,
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
  const pendingBlockingFindings =
    routeFrom === "S4"
      ? adjudicatedBlockingFindingsForPersistedS4(executableLedger)
      : undefined;
  const routeOutput =
    isReviewLoopStep(routeFrom) && routeFrom === lastEntry.step
      ? lastEntry.output
      : agentEntry?.output;
  const shipStatusForRoute =
    routeFrom === "S7"
      ? shipStatusFromLedger(executableLedger) ?? "pushed"
      : undefined;
  const onlineReviewRoundForRoute =
    routeFrom === "S9" || routeFrom === "S10"
      ? onlineReviewRoundFromLedger(executableLedger)
      : undefined;
  const decision = route({
    from: routeFrom,
    output: routeOutput,
    ...(pendingBlockingFindings !== undefined
      ? { pendingBlockingFindings }
      : {}),
    ...(shipStatusForRoute !== undefined
      ? { shipStatus: shipStatusForRoute }
      : {}),
    ...(onlineReviewRoundForRoute !== undefined
      ? { onlineReviewRound: onlineReviewRoundForRoute }
      : {}),
  });
  const truncateReviewLoop =
    isReviewLoopStep(routeFrom) && decision.kind === "next";
  const priorForResume = truncateReviewLoop
    ? priorLedgerThroughLastShip(ledger)
    : (ledger as ReadonlyArray<LedgerEntry>);
  const resumeLastOutput = truncateReviewLoop
    ? undefined
    : routeOutput;
  // #600 r28: markers persist before the executable S10 row — crash in that window
  // must resume into post-fix verify, not re-dispatch the fixer.
  if (
    slicePostFixVerifyPendingFromMarkerGap(ledger) &&
    decision.kind === "next" &&
    decision.step === "S10"
  ) {
    return {
      resumeStep: "S9",
      lastOutput: undefined,
      priorLedger: priorForResume,
    };
  }
  if (decision.kind === "handoff") {
    return {
      terminalStatus: decision.status,
      resumeStep: "S8",
      lastOutput: resumeLastOutput ?? agentEntry?.output,
      priorLedger: priorForResume,
    };
  }
  return {
    resumeStep: decision.step,
    lastOutput: resumeLastOutput,
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

const MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS = 2;

/**
 * The fixed StepSpecs for single-slice worker steps. Versioned promptFiles,
 * never assembled inline (ADR 0018 决定#4).
 *
 * ADR 0030 makes the per-slice loop runner-visible: S2 implements, S3 reviews,
 * S5 fixes blocking findings, and S6 performs the fresh full-diff re-review.
 *
 * #253 fields: model (CLI slug), completionSignal (Sandcastle run() API), maxIter
 * (the WITHIN-STEP Ralph retry budget — NOT a fix-loop give-up counter), soul,
 * toolchain.
 *
 * maxIter SEMANTICS: the WITHIN-STEP agent (Ralph) retry budget for one
 * `sandbox.run()`, NOT a give-up counter. Hitting it = the step ends normally; it
 * is NEVER the orchestrator giving up (that only happens on a MODEL escalate
 * signal — US#18/US#19, never by counting). See StepSpec.maxIter.
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

export function coderFixModel(env: ModelRouteEnv = process.env): string {
  return modelForSlot("coderFix", env);
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
      // gpt-5.5; was Sonnet 4.6). The slug is resolved to the baked CLI by
      // agentForSlug (realBackend); switching the model is `ORCHESTRATOR_CODER_MODEL`
      // alone — no image rebuild, no StepSpec shape change.
      model: route.slots.coder,
      completionSignal: "CODER_STEP_COMPLETE",
      maxIter: 5,
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
      maxIter: 5,
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

/**
 * Synthesise a human-readable reason string for route()-detected error edges
 * (e.g. 0-commit). Backend-throw errors use the caught message directly.
 */
function buildErrorReason(step: StepId, output: StepOutput | undefined): string {
  if ((step === "S2" || step === "S5") && output?.kind === "coder" && !output.committed) {
    return `${step} coder worker produced no commits (committed:false)`;
  }
  return `step ${step} routed to error handoff`;
}

/** Compact, safe description of a (possibly malformed) step output for errors. */
function describeOutput(output: StepOutput | undefined): string {
  if (output === undefined) return "undefined";
  if (output === null) return "null";
  if (typeof output !== "object") return String(output);
  const kind = (output as { kind?: unknown }).kind;
  return `object with kind=${JSON.stringify(kind)}`;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
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
  readonly deferredFindings: ReadonlyArray<Finding>;
  readonly findingDispositions: ReadonlyArray<FindingDisposition>;
}): StopSummary {
  // #604 slice 4 (ADR 0062): routing disposition kinds are gone and the deferred
  // bucket is always empty, so there is no cross-module defer to surface here —
  // a success summary carries accepted-suppression metadata only.
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
  if (
    /contract|malformed|does not match|no valid result|off-contract|prior claimed-fixed finding|prior finding disposition/i.test(
      errorPackage.reason,
    ) ||
    WORKER_STDOUT_MISSING_TAG_RE.test(errorPackage.reason)
  ) {
    return contractDriftStopSummary({
      summary: errorPackage.reason,
      repairHint,
    });
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
  if (/review\/fix loop made no progress/i.test(escalation.reason)) {
    return {
      reason: "same_module_still_red",
      summary: reason,
      repairHint: "repair the same-module finding or change the implementation strategy before rerun",
    };
  }
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
    if (stopSummary !== undefined) return stopSummary;
  }
  return undefined;
}

function isReviewerStructuredOutputError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  return (
    err.name === "ZodError" ||
    err.name === "StructuredOutputError" ||
    /StructuredOutputError|structured output|missing <review>|<review>|ZodError/i.test(
      err.message,
    )
  );
}

export async function runOrchestrator(input: RunInput): Promise<RunResult> {
  const { issueNumber, backend } = input;
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
      deferredFindings: [],
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
      deferredFindings: [],
    };
  }
  console.info(
    `[orchestrator] model route lineup\n${printableRouteLineup(routePolicy.route)}`,
  );
  const stepSpecs = stepSpecsForRoute(routePolicy.route);
  // Family-run context (ADR 0022 decision 2). When present this is a CHILD slice
  // of a family run: cut from the family base (decision 7) and S7 push is a local
  // no-op (decision 2). Absent ⇒ the v0.1 standalone behaviour (base=main, push).
  const family = input.family;
  // The cut base: the family base in family mode (decision 7), else "main"
  // (SLICE_BASE, ADR 0017 §2). This is the only place "main" is parameterised —
  // the Backend seam already takes base as a parameter (ADR 0017 §2); #293 just
  // feeds the family base instead of the hardcoded constant.
  const sliceBase = family !== undefined ? family.familyBase : SLICE_BASE;
  const ledger: LedgerEntry[] = [];

  // State threaded across steps within this run.
  let worktree: WorktreeHandle | undefined;
  let lastOutput: StepOutput | undefined;
  // #617: the `defer` action was removed from the reviewer contract, so this
  // bucket is always empty; it is retained so resume state stays shape-compatible.
  let deferredFindings: Finding[] = [];
  let pendingBlockingFindings: Finding[] = [];
  let pendingBlockingFindingIdentityKeys: string[] = [];
  let findingDispositions: FindingDisposition[] = [];
  let lastReviewerStepId: StepId | undefined;
  let lastCoderRepairEvidence: RepairEvidence | undefined;
  let lastCoderActualRepairPaths: ReadonlyArray<string> = [];
  const noProgressByFindingIdentityKey = new Map<string, number>();
  let lastShipOutput: ShipResult | undefined;
  let onlineReviewRound = 1;
  let onlineReviewLanding: WorkerLandingPayload | undefined;
  let lastOnlineReviewFixCommitSha: string | undefined;
  let lastOnlineReviewRoundTrigger: RoundTrigger | undefined;

  function ghSh(file: string, args: string[]): string {
    return execFileSync(file, args, {
      stdio: ["ignore", "pipe", "pipe"],
      encoding: "utf8",
    }).trim();
  }

  function defaultRepo(): string {
    const fromEnv = process.env.ORCHESTRATOR_REPO?.trim();
    if (fromEnv && fromEnv.length > 0) return fromEnv;
    if (process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL === "1") {
      return "Akagilnc/ming-salvage-sim";
    }
    try {
      return execFileSync("gh", ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
      }).trim();
    } catch {
      return "Akagilnc/ming-salvage-sim";
    }
  }

  async function pollOnlineReviewForShip(
    ship: ShipResult,
    pollCount: number,
  ): Promise<PrReviewSnapshot> {
    const prUrl = ship.pr;
    if (prUrl == null || prUrl.trim().length === 0) {
      throw new Error("online review poll requires a non-empty PR URL from ship");
    }
    const repo = defaultRepo();
    const livePoll = isLiveGithubReviewPollEnabled(prUrl, repo);
    if (!livePoll) {
      // #600 r6: hook and offline synthesis share the central admissibility gate —
      // test backends may inject poll results only under explicit offline/test handles.
      assertOfflineSyntheticPollAdmissible(prUrl, repo);
      if (backend.pollOnlineReviewState !== undefined) {
        const landing = await backend.pollOnlineReviewState({
          repo,
          prUrl,
          pollCount,
        });
        const defaultBots = {
          coderabbit: { state: "complete" as const, findingCount: 0 },
          sourcery: { state: "complete" as const, findingCount: 0 },
          codex: { state: "complete" as const, findingCount: 0 },
          gemini: { state: "complete" as const, findingCount: 0 },
        };
        return {
          repo,
          prNumber: 0,
          prUrl: landing.prUrl,
          headOid: landing.headOid,
          pollCount,
          bots: (landing.bots ?? defaultBots) as PrReviewSnapshot["bots"],
          threads: landing.threads.map((t) => ({
            id: t.id,
            threadNodeId: t.threadNodeId ?? t.id,
            path: t.path,
            line: t.line,
            body: t.body,
            authorLogin: t.authorLogin ?? "unknown",
            isResolved: t.isResolved,
            headOid: t.headOid,
          })),
          checkRuns: landing.checkRuns ?? [],
          totalFindingCount: landing.totalFindingCount,
          quiescent: landing.quiescent,
        };
      }
      return offlinePrReviewSnapshot({
        repo,
        prUrl,
        headOid:
          lastOnlineReviewFixCommitSha ??
          ship.prHead ??
          "offline-review-head",
        pollCount,
      });
    }
    const ghSh = (file: string, args: string[]) =>
      execFileSync(file, args, {
        stdio: ["ignore", "pipe", "pipe"],
        encoding: "utf8",
      }).trim();
    const roundTrigger = resolveOnlineReviewRoundTrigger({
      onlineReviewRound,
      persistedRoundTrigger: lastOnlineReviewRoundTrigger,
      pendingRetriggerFromFixGap: slicePendingRoundTriggerFromFixGap(ledger),
      fixCommitSha: lastOnlineReviewFixCommitSha,
      shipPrHead: ship.prHead,
      shipLedgerTriggeredAt: shipLedgerTriggeredAtFromSliceLedger(ledger),
    });
    const snapshot = await waitForBotQuiescence(ghSh, {
      repo,
      prUrl,
      roundTrigger,
      clock:
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL === "1"
          ? immediateBotPollClock
          : realBotPollClock,
    });
    lastOnlineReviewRoundTrigger = buildRoundTrigger(
      snapshot.headOid,
      roundTrigger.triggeredAt,
    );
    return snapshot;
  }

  function seedClassificationFromReviewerOutput(
    reviewerOutput: StepOutput | undefined,
    afterFix: boolean,
  ): string[] {
    if (reviewerOutput?.kind !== "reviewer") return [];
    const classification = classifyFindings(
      reviewerOutput.findings,
      findingDispositions,
    );
    const reviewerBlocking = [...classification.blocking];
    const reviewerBlockingIdentityKeys = reviewerBlocking.map(findingIdentityKey);
    let blocking = [...classification.blocking];
    let blockingIdentityKeys = blocking.map(findingIdentityKey);
    findingDispositions = [...classification.dispositions];
    const noProgressIdentityKeys: string[] = [];

    if (afterFix && pendingBlockingFindingIdentityKeys.length > 0) {
      const adjudication = adjudicatePriorClaimedFixedFindings({
        priorFindings: pendingBlockingFindings,
        priorIdentityKeys: pendingBlockingFindingIdentityKeys,
        review: reviewerOutput,
      });
      for (const key of adjudication.verifiedClosedIdentityKeys) {
        noProgressByFindingIdentityKey.delete(key);
      }
      const seenBlocking = new Set(blockingIdentityKeys);
      for (const finding of adjudication.stillOpen) {
        const key = findingIdentityKey(finding);
        const previousFinding =
          pendingBlockingFindings[
            pendingBlockingFindingIdentityKeys.indexOf(key)
          ] ?? finding;
        const observedReviewerProgress = reviewerObservedProgress({
          previousBlockingFindings: pendingBlockingFindings,
          previousBlockingIdentityKeys: pendingBlockingFindingIdentityKeys,
          currentBlockingFindings: reviewerBlocking,
          currentBlockingIdentityKeys: reviewerBlockingIdentityKeys,
          previousFinding,
          previousIdentityKey: key,
          previousNoProgressCount: noProgressByFindingIdentityKey.get(key) ?? 0,
        });
        if (!seenBlocking.has(key)) {
          blocking.push(finding);
          blockingIdentityKeys.push(key);
          seenBlocking.add(key);
        }
        if (
          repairEvidenceMatchesKey(
            lastCoderRepairEvidence,
            lastCoderActualRepairPaths,
            finding,
            key,
            pendingBlockingFindings,
            pendingBlockingFindingIdentityKeys,
          ) ||
          observedReviewerProgress
        ) {
          noProgressByFindingIdentityKey.set(key, 0);
        } else {
          const count = (noProgressByFindingIdentityKey.get(key) ?? 0) + 1;
          noProgressByFindingIdentityKey.set(key, count);
          if (count >= 2) noProgressIdentityKeys.push(key);
        }
      }
    }

    const blockingKeys = new Set(blockingIdentityKeys);
    deferredFindings = deferredFindings.filter(
      (finding) => !blockingKeys.has(findingIdentityKey(finding)),
    );
    const deferredKeys = new Set(deferredFindings.map(findingIdentityKey));
    for (const finding of classification.deferred) {
      const key = findingIdentityKey(finding);
      if (!deferredKeys.has(key)) {
        deferredFindings.push(finding);
        deferredKeys.add(key);
      }
    }
    pendingBlockingFindings = blocking;
    pendingBlockingFindingIdentityKeys = blockingIdentityKeys;
    if (!afterFix) {
      for (const key of blockingIdentityKeys) {
        if (!noProgressByFindingIdentityKey.has(key)) {
          noProgressByFindingIdentityKey.set(key, 0);
        }
      }
    }
    return noProgressIdentityKeys;
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
        if (sha !== undefined && sha.length > 0) return sha;
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
    s: StepId,
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
    repairMovementPaths?: ReadonlyArray<string>,
  ): Promise<void> {
    const ph = await hashPrompt(promptFile, s, backend);
    const branchHEAD = await resolveBranchHEAD();
    const entry = buildPersistentEntry({
      step: s,
      output,
      sessionId: stepSessionId ?? sessionId,
      prompt_hash: ph,
      branchHEAD,
      ts: new Date().toISOString(),
      handoffStatus,
      escalationKind,
      findingDispositions,
      repairMovementPaths,
      stopSummary,
    });

    const mirrorInMemoryLedgerTs = (step: StepId, ts: string): void => {
      for (let i = ledger.length - 1; i >= 0; i--) {
        if (ledger[i]!.step === step) {
          ledger[i] = { ...ledger[i]!, ts };
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
      mirrorInMemoryLedgerTs(buffered.step, buffered.ts);
    }
    await backend.writeLedger(entry, stateDir);
    mirrorInMemoryLedgerTs(s, entry.ts);
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
    s: StepId,
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
    repairMovementPaths?: ReadonlyArray<string>,
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
        repairMovementPaths,
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
    failedStep: StepId,
    err: unknown,
    opts?: {
      recordInMemory?: boolean;
      output?: StepOutput;
      findingDispositions?: ReadonlyArray<FindingDisposition>;
      repairMovementPaths?: ReadonlyArray<string>;
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
          ...(opts?.repairMovementPaths !== undefined
            ? { repairMovementPaths: opts.repairMovementPaths }
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
        opts?.repairMovementPaths,
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
      deferredFindings,
    };
  }
  // ─────────────────────────────────────────────────────────────────────────

  /**
   * Terminal ESCALATE handoff for a NON-agent worker step (S7 ship).
   *
   * The S2 build worker routes its `escalated` worker result through
   * route()'s global escalate edge (via `workerResultToStep` → output.escalate).
   * S7 is a runner-action boundary route() always maps to success, so a SHIP
   * worker that escalates (gstack-ship STOP/HITL) must be turned into an
   * S8(escalate) handoff HERE — not S8(error) (codex cmr R4 finding: a worker
   * `{kind:"escalated"}` must keep escalate semantics). Mirrors errorTermination's
   * ledger discipline but tags the S8 entry 'escalate', so a re-feed's planResume
   * Case 3a reports `terminalStatus:"escalate"` (an honest escalate handoff).
   *
   * The worker `sessionId` is PERSISTED on the failing-step entry (resume truth).
   * A later append-only answer row reopens S7 through `planResume`: the stale
   * S7/S8 pause is truncated from the in-memory ledger and the ship worker is
   * re-dispatched with the human answer in its focus file.
   */
  async function escalateTermination(
    failedStep: StepId,
    escalation: Escalation,
    sessionId?: string,
    escalationKind: EscalationKind = "decision",
  ): Promise<RunResult> {
    const stopSummary = stopSummaryForEscalation(escalation);
    if (failedStep !== "S8") {
      ledger.push({ step: failedStep });
      // Persist the failing step carrying its REAL worker session id (5th arg —
      // NOT the promptFile slot; codex cmr R6 finding), so a re-feed reading the
      // persisted ledger has the true session id for the human-answer resume.
      //
      // integ-cmr int-r2 (C-int2-1): for an escalating S7 the failing-step entry
      // must ALSO carry the ship.md CONTENT hash (the same anti-tampering audit the
      // happy S7 entry carries), not the degraded step-name hash. S7 is the only
      // runner-action step dispatched via a WorkerSpec (shipWorkerSpec); agent
      // steps already escalate through their own dispatch path, so deriving the
      // ship promptFile only for S7 keeps every other failing step's persist
      // unchanged (promptFile undefined → step-name hash, as before).
      const failedPromptFile =
        failedStep === "S7" ? SHIP_PROMPT_FILE : undefined;
      await persistBestEffort(failedStep, undefined, failedPromptFile, undefined, sessionId);
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
      deferredFindings,
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
    resumeState = await backend.findResumeState(issueNumber);
  } catch (err) {
    return await errorTermination("S0", err);
  }

  // The runner drives the sequence; the agent never picks the next step.
  let step: StepId = "S0";

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
  let resumeFor: { step: StepId; sessionId: string } | undefined;
  let resumedEscalationAnswer: EscalationAnswerEvent | undefined;

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
    const plan =
      (await planRecoveredLandedCoderProtocolFailure(
        resumeLedger,
        worktree,
        backend,
      )) ?? planResume(resumeLedger);

    // Seed the in-memory ledger with prior progress so committed work is
    // preserved and the prior steps are NOT re-run.
    for (const e of plan.priorLedger) ledger.push(e);
    lastOutput = plan.lastOutput;

    for (const e of plan.priorLedger) {
      if (e.step === "S7" && e.output?.kind === "ship") {
        lastShipOutput = e.output;
      }
    }
    // #600 r7: derive review-loop runtime from the FULL executable ledger before
    // priorLedgerThroughLastShip drops superseded S9–S12 entries for display seed.
    onlineReviewRound = onlineReviewRoundFromLedger(resumeLedger);
    lastOnlineReviewFixCommitSha =
      lastOnlineReviewFixCommitShaFromLedger(resumeLedger);
    lastOnlineReviewRoundTrigger =
      onlineReviewRoundTriggerFromLedger(resumeLedger);

    // ADR 0030: persisted S4 boundaries are the runner's closure truth. Resume
    // must replay the prior S4 adjudications, because an S6 reviewer may carry an
    // empty `findings[]` plus `still-active` dispositions for blockers inherited
    // from older rounds. Reclassifying only the previous reviewer payload would
    // treat absence as closure.
    const replayedS4 = replayS4AdjudicationState(plan.priorLedger);
    pendingBlockingFindings = [...replayedS4.blocking];
    pendingBlockingFindingIdentityKeys = [...replayedS4.blockingIdentityKeys];
    deferredFindings = [...replayedS4.deferred];
    findingDispositions = [...replayedS4.findingDispositions];
    noProgressByFindingIdentityKey.clear();
    for (const [key, count] of replayedS4.noProgressCounts) {
      noProgressByFindingIdentityKey.set(key, count);
    }
    for (const key of plan.continueFixingRepair?.matchingIdentityKeys ?? []) {
      noProgressByFindingIdentityKey.delete(key);
    }
    lastReviewerStepId = lastReviewerStep(plan.priorLedger);
    const latestRepair = latestCoderRepair(plan.priorLedger);
    lastCoderRepairEvidence = latestRepair.repairEvidence;
    lastCoderActualRepairPaths = latestRepair.repairMovementPaths;

    if (
      plan.resumeStep === "S10" &&
      lastShipOutput !== undefined &&
      onlineReviewLanding === undefined
    ) {
      const reconstructed = reconstructOnlineReviewLandingForResume({
        fullLedger: resumeLedger,
        ship: lastShipOutput,
        stateDir,
        round: onlineReviewRound,
      });
      if (reconstructed?.onlineReviewSnapshot !== undefined) {
        onlineReviewLanding = reconstructed;
      }
    }

    if (plan.terminalStatus !== undefined) {
      // The prior run already reached a terminal handoff that is NOT being
      // re-opened. Re-feeding is a pure status report — no worktree mutation,
      // so cleanResidue is intentionally NOT run here (a residue-clean failure
      // must not flip an already-finished run's reported status). Report the
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
          deferredFindings,
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
        deferredFindings,
      };
    }

    // Continuing from a breakpoint: clean uncommitted residue before reuse
    // (reset --hard / clean -fd / prune). Committed progress (the resident
    // branch HEAD) is preserved; the ledger lives outside the worktree so
    // `clean -fd` cannot touch the resume truth. A cleanResidue failure is a
    // backend throw → S8(error) (consistent with #252), via errorTermination
    // (base integ-cmr: records + best-effort persists the failing step + S8).
    try {
      await backend.cleanResidue(worktree);
    } catch (err) {
      return await errorTermination(plan.resumeStep, err);
    }

    // ADR 0030: resume continues from the recorded runner-visible boundary. If
    // that boundary follows S4, the classification state was rebuilt above from
    // the persisted reviewer output.

    // Continue from the recorded breakpoint.
    step = plan.resumeStep;
    if (plan.resumeSessionId !== undefined) {
      resumeFor = { step: plan.resumeStep, sessionId: plan.resumeSessionId };
    }
    resumedEscalationAnswer = plan.escalationAnswer;
  }

  // The step machine has no fixed bound: route() always terminates the run via a
  // handoff (success/escalate/error). ADR 0030 makes the per-slice review/fix
  // loop visible in S3/S4/S5/S6, but still rejects a blind round cap; a `for (;;)`
  // keeps the absence of any "数到 N 就停" cap explicit (US#18).
  for (;;) {
    let output: StepOutput | undefined;
    // promptFile for the current step (agent steps only; undefined for runner actions).
    let promptFile: string | undefined;
    // #256: the REAL per-step sandbox session id, captured from the seam
    // extension (runStep/resumeSession → StepResult). Undefined for runner
    // actions and for a fake Backend that returns a bare StepOutput → the ledger
    // records the run-level UUID fallback for those.
    let stepSessionId: string | undefined;

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
        // that ONLY narrows the set: standalone runs (no `family`) have an empty
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

        break;
      }

      case "S1": {
        // S1 load_context — runner action: full snapshot → resident worktree
        // (base=`sliceBase`: "main" standalone, the family base in family mode —
        // ADR 0022 decision 7) → write snapshot in (clean-room).
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
        break;
      }

      case "S2":
      case "S3":
      case "S5":
      case "S6": {
        // ADR 0030 productive steps:
        //   S2 coder implement, S3 fresh read-only review, S5 coder fix,
        //   S6 fresh read-only full-diff re-review.
        // Normal fix rounds are fresh runStep dispatches (git-truthing kept),
        // never resumeSession. resumeSession is only the crash/escalate resume
        // path when `resumeFor` carries a recorded session id.
        if (worktree === undefined) {
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
        promptFile = stepSpecs[step].promptFile;
        const expectedKind = stepSpecs[step].role as "coder" | "reviewer";
        const coderHeadBeforeStep =
          expectedKind === "coder" ? gitHead(worktree) : undefined;
        try {
          let resumeSessionId: string | undefined;
          if (resumeFor !== undefined && resumeFor.step === step) {
            resumeSessionId = resumeFor.sessionId;
            resumeFor = undefined;
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

          let attempts = 0;
          for (;;) {
            attempts += 1;
            let result: Awaited<ReturnType<typeof dispatchWorker>>;
            try {
              const workerSpec = stepSpecToWorkerSpec(
                stepSpecs[step],
                resumeSessionId != null ? "resume" : "fresh",
              );
              const dispatchCtx = {
                worktree,
                stateDir,
                ...(resumeSessionId != null ? { resumeSessionId } : {}),
                ...(escalationAnswerForStep != null
                  ? { escalationAnswer: escalationAnswerForStep }
                  : {}),
                // 信封宪法 (ADR 0062): the dispatch structure carries only the
                // identity keys + count; the rich finding content travels in the
                // separate landing payload below.
                ...(step === "S5" || step === "S6"
                  ? {
                      blockingFindingIdentityKeys:
                        pendingBlockingFindingIdentityKeys,
                      blockingFindingCount: pendingBlockingFindings.length,
                    }
                  : {}),
              };
              const landingPayload =
                step === "S5" || step === "S6"
                  ? { blockingFindings: pendingBlockingFindings }
                  : undefined;
              // #598: the generic mechanical retry re-dispatches a process-level
              // crash (failed/malformed/outcome_protocol_failure/throw) with a fresh
              // worker. This loop dispatches the agent worker steps S2/S3/S5/S6 (the
              // SHIP S7 is a separate dispatch below, with its own retry predicate).
              //
              //  - CODER (S2/S5): no semantic-retry loop → inherits the generic retry
              //    for EVERY process failure (the #592 asymmetry: a `failed` coder =
              //    produced no commit = a process failure to re-attempt).
              //  - REVIEWER (S3/S6): keeps its OWN bounded semantic loop below
              //    (MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS), which owns invalid/malformed
              //    RESULTS and structured-output THROWS — the generic layer defers those
              //    to it (no double-count). The generic layer DOES retry a NON-structured
              //    crash (connection drop / container start), recovering a transient one;
              //    a persistent crash is re-thrown so the reviewer loop surfaces it.
              //
              // Idempotency (#598): before any retry, reset the worktree's UNCOMMITTED
              // git residue (`cleanResidue` = reset --hard HEAD + clean -fd) the crashed
              // attempt may have left, so the fresh re-dispatch does not run on top of a
              // dirty index / untracked junk. Committed progress on the resident branch
              // HEAD is deliberately preserved (cleanResidue contract / ADR 0024 — it is
              // the resume anchor). A worktree-less family worker has no local residue.
              //
              // DEFERRED (#661, needs-design): a coder that COMMITTED a partial attempt
              // then crashed keeps that commit at HEAD, so the retry continues on it
              // rather than a strict pre-attempt HEAD. Unlike the merge-resolver's
              // committed-then-crashed case (data loss — fixed in this PR), a coder
              // continuing on preserved progress is bounded (the reviewer catches broken
              // partial work) and is what ADR 0024 intends; whether a mechanical retry
              // should override that committed-preservation is a design decision.
              const worktreeForReset = worktree;
              const resetBeforeRetry =
                worktreeForReset != null
                  ? () => backend.cleanResidue(worktreeForReset)
                  : undefined;
              const baseReset =
                resetBeforeRetry != null ? { resetBeforeRetry } : {};
              const retryOpts: MechanicalRetryOptions =
                expectedKind === "reviewer"
                  ? {
                      callerOwns: (o) =>
                        "result" in o
                          ? true
                          : isReviewerStructuredOutputError(o.error),
                      rethrowOnExhaustion: true,
                      ...baseReset,
                    }
                  : baseReset;
              result = await withMechanicalRetry(
                workerSpec,
                dispatchCtx,
                (s, c) => dispatchWorker(backend, s, c, landingPayload),
                retryOpts,
              );
            } catch (err) {
              if (
                expectedKind === "reviewer" &&
                isReviewerStructuredOutputError(err) &&
                attempts < MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS
              ) {
                resumeSessionId = undefined;
                continue;
              }
              if (
                expectedKind === "reviewer" &&
                isReviewerStructuredOutputError(err)
              ) {
                output = {
                  kind: "reviewer",
                  findings: [],
                  escalate: {
                    reason: "reviewer output remained invalid after bounded reruns",
                    diagnosis:
                      `step ${step} failed to produce valid reviewer output ` +
                      `${attempts} times; last error: ${errorMessage(err)}`,
                    // #604 correctness r1 (P1-a): a RUNNER-synthesized escalate from
                    // exhausted malformed reruns is a PROTOCOL FAILURE, not a
                    // worker-proactive decision — mark it so the handoff maps to
                    // escalationKind:"failure" (A-class), never the decision gate.
                    synthesizedFailure: true,
                  },
                };
                stepSessionId = undefined;
                break;
              }
              throw err;
            }
            const { unwrapped, reason } = workerResultToStep(result, expectedKind);
            const retryableReviewerFailure =
              expectedKind === "reviewer" &&
              (unwrapped === undefined ||
                !isValidStepOutput(
                  "output" in (unwrapped ?? {}) && !("kind" in (unwrapped ?? {}))
                    ? (unwrapped as { output: StepOutput }).output
                    : (unwrapped as StepOutput | undefined),
                  "reviewer",
                ));

            if (retryableReviewerFailure) {
              if (attempts < MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS) {
                resumeSessionId = undefined;
                continue;
              }
              output = {
                kind: "reviewer",
                findings: [],
                escalate: {
                  reason: "reviewer output remained invalid after bounded reruns",
                  diagnosis:
                    `step ${step} produced invalid reviewer output ${attempts} times; ` +
                    "runner stopped instead of retrying indefinitely",
                  // #604 correctness r1 (P1-a): protocol failure, not a decision —
                  // synthesized by the runner after exhausted reruns.
                  synthesizedFailure: true,
                },
              };
              stepSessionId =
                result.kind === "completed" || result.kind === "escalated"
                  ? result.sessionId
                  : undefined;
              break;
            }

            if (unwrapped === undefined) {
              return await errorTermination(
                step,
                new Error(
                  `worker ${step} returned ${result.kind}: ${reason ?? "no reason"}`,
                ),
              );
            }
            const normalized =
              "output" in unwrapped && !("kind" in unwrapped)
                ? { output: unwrapped.output, sessionId: unwrapped.sessionId }
                : { output: unwrapped as StepOutput, sessionId: undefined };
            output = normalized.output;
            stepSessionId = normalized.sessionId;
            break;
          }
        } catch (err) {
          return await errorTermination(step, err);
        }

        const stepEscalate = escalateOf(output);
        const carriesEscalate = stepEscalate != null;
        if (!carriesEscalate) {
          if (!isValidStepOutput(output, expectedKind)) {
            return await errorTermination(
              step,
              new Error(
                `${step}: step output does not match the ${expectedKind} contract. ` +
                  `Got: ${describeOutput(output)}. Refusing to route malformed output.`,
              ),
            );
          }
        } else if (!isValidEscalation(stepEscalate)) {
          lastOutput = output;
          break;
        }
        lastOutput = output;
        if (output.kind === "coder") {
          lastCoderRepairEvidence = output.repairEvidence;
          lastCoderActualRepairPaths = actualRepairMovementPaths(
            worktree,
            coderHeadBeforeStep,
          );
        }
        if (step === "S3" || step === "S6") lastReviewerStepId = step;
        break;
      }

      case "S4": {
        let noProgressIdentityKeys: string[];
        try {
          noProgressIdentityKeys = seedClassificationFromReviewerOutput(
            lastOutput,
            lastReviewerStepId === "S6",
          );
        } catch (err) {
          return await errorTermination("S4", err);
        }
        if (noProgressIdentityKeys.length > 0) {
          return await escalateTermination("S4", {
            reason: "review/fix loop made no progress",
            diagnosis:
              "Fresh re-review reported the same claimed-fixed finding still active " +
              `after repeated fix attempts: ${noProgressIdentityKeys.join(", ")}`,
          });
        }
        break;
      }

      case "S7": {
        // S7 push — runner action: push the resident slice branch. No PR, no
        // merge (the Backend exposes neither).
        if (worktree === undefined) {
          throw new Error("runner: S7 push reached before worktree prepared");
        }
        // Family mode (ADR 0022 decision 2): S7 is a LOCAL no-op. The child only
        // commits to its own branch in the shared family clone — it does NOT push
        // remotely (concurrent pushes from sibling children would clash on
        // .git/refs/remotes; only the family base PRs once at the end). The step
        // still records + routes to S8(success) exactly as a real push would; we
        // just skip the backend.push() call. (ADR 0022: "完整复用 S0-S8，但家族
        // 模式下 S7 的 backend.push 替换为本地 no-op".)
        if (family !== undefined && family.noPush) {
          break;
        }
        try {
          // ADR 0026 / #331: S7 is now a SHIP worker dispatched through the
          // unified seam (no longer an inline `backend.push`). #331 prefactor: the
          // legacy wrapper forwards the ship worker to `backend.push` (behaviour
          // unchanged); #336 makes it invoke `gstack-ship`.
          //
          // integ-cmr int-r2 (C-int2-1): bind the ship spec FIRST and thread its
          // versioned promptFile ("ship.md") into the loop-scoped `promptFile` so the
          // S7 ledger entry hashes the ship.md CONTENT (the WorkerSpec anti-tampering
          // contract, types.ts:"promptFile CONTENT is hashed into the ledger") — NOT
          // the degraded step-name hash (`name:<sha("S7")>`) the missing assignment
          // produced. The escalateTermination path below ALSO uses it (resume truth).
          const shipSpec = shipWorkerSpec(routePolicy.route);
          promptFile = shipSpec.promptFile;
          const escalationAnswerForStep =
            resumedEscalationAnswer?.forStep === "S7"
              ? resumedEscalationAnswer
              : undefined;
          if (escalationAnswerForStep != null) {
            resumedEscalationAnswer = undefined;
          }
          const shipCtx = {
            worktree,
            stateDir,
            ...(escalationAnswerForStep != null
              ? { escalationAnswer: escalationAnswerForStep }
              : {}),
          };
          // #598 + #601: the ship step re-dispatches fresh on a PROCESS-LEVEL failure
          // (a CRASH throw, or a STRUCTURAL `malformed`/`outcome_protocol_failure` —
          // the worker emitted no parseable `<ship>` verdict, the dogfood-362 /
          // family-405 incident class that used to durably abort the run on first
          // occurrence). The `callerOwns` predicate claims ONLY a JUDGED `failed`
          // verdict (a parsed `<ship>{failed:…}` delivery failure, or a branch-identity
          // mismatch RealBackend maps to `failed`) so it passes through with ZERO retry
          // — a decided delivery failure is never re-run. This is the SAME shared
          // `withMechanicalRetry` path the coder uses (#592 "no role treated specially"):
          // the structural no-output case retries, the judged-verdict case does not.
          // The worktree's uncommitted residue is reset before each retry (idempotency);
          // gstack-ship's re-runnable design keeps push/PR idempotent.
          const shipWorktree = worktree;
          // Mirror the coder/reviewer reset guard: only wire cleanResidue when a
          // worktree exists (a worktree-less worker has no local residue), so a retry
          // never calls cleanResidue(undefined). (gemini R1 — the coder path already
          // guards; the ship path must match.)
          const shipResetOpt =
            shipWorktree != null
              ? { resetBeforeRetry: () => backend.cleanResidue(shipWorktree) }
              : {};
          const shipResult = await withMechanicalRetry(
            shipSpec,
            shipCtx,
            (s, c) => dispatchWorker(backend, s, c),
            {
              callerOwns: (o) => "result" in o && o.result.kind === "failed",
              ...shipResetOpt,
            },
          );
          // A ship worker that ESCALATES (gstack-ship STOP/HITL) is an
          // S8(escalate) handoff, NOT an error — keep the escalate semantics so
          // the human-answer resume re-opens it (codex cmr R4 finding). #331's
          // legacy wrapper never escalates; the real ship worker (#336) does.
          if (shipResult.kind === "escalated") {
            return await escalateTermination(
              "S7",
              shipResult.escalation,
              shipResult.sessionId,
            );
          }
          // Otherwise the ship worker must return a `completed` result carrying a
          // SHIP payload — a `completed` result whose output is some other kind (a
          // mis-wired new-seam backend) or a failed/malformed result is NOT a
          // successful ship and must not route to S8(success) (codex cmr R2:
          // guard the output kind, as the agent steps + family cmr stage do).
          if (shipResult.kind !== "completed" || shipResult.output.kind !== "ship") {
            return await errorTermination(
              "S7",
              new Error(
                `ship worker returned ${shipResult.kind}` +
                  (shipResult.kind === "completed"
                    ? ` with non-ship output kind '${shipResult.output.kind}'`
                    : ` (${"reason" in shipResult ? shipResult.reason : "unknown"})`),
              ),
            );
          }
          // cmr S336 r4 (P1, symmetric to the family terminal gate): do NOT trust
          // the discriminant alone. The terminal single-slice gate consumes any
          // injected Backend's dispatchWorker — a backend that implements the seam
          // but skips the success contract (RealBackend.dispatchWorker enforces it;
          // a minimal seam-only backend need not) could return a `completed
          // {kind:"ship"}` carrying an off-contract status, or one that shipped a
          // DIFFERENT branch than the resident slice. Re-assert here, fail-CLOSED
          // (defense-in-depth). The single-slice contract (prompts/ship.md) ALLOWS
          // both `pushed` and `pr_opened` (pr_opened ⇒ a non-empty pr URL), and the
          // shipped branch MUST be the resident worktree branch.
          const ship = shipResult.output;
          if (
            ship.branch !== worktree.branch ||
            (ship.status !== "pushed" && ship.status !== "pr_opened") ||
            (ship.status === "pr_opened" && !isFilledString(ship.pr))
          ) {
            return await errorTermination(
              "S7",
              new Error(
                `ship worker reported an off-contract delivery (branch="${ship.branch}", ` +
                  `status="${ship.status}", pr=${ship.pr === undefined ? "absent" : `"${ship.pr}"`}) ` +
                  `— expected branch "${worktree.branch}" with status "pushed" or "pr_opened" ` +
                  `(pr_opened requires a non-empty pr URL); not a trusted slice delivery`,
              ),
            );
          }
          // Persist the validated SHIP payload + the worker's session id into the S7
          // ledger entry (online review r1, 3 bots): the shared record/emitLedger
          // path below writes `output`/`stepSessionId`, but S7 previously left both
          // undefined — so the persisted ledger AND RunResult.stepLedger dropped the
          // shipped branch/status and (for pr_opened) the PR URL, plus the ship
          // worker's sessionId. Assign them so the delivery is recoverable from
          // resume truth and surfaced to the caller.
          output = ship;
          lastShipOutput = ship;
          stepSessionId = shipResult.sessionId;
        } catch (err) {
          // Push failure → S8(error) with branch head so dev can diagnose
          // without losing the commits already on the resident branch (#252).
          // errorTermination records + persists both the S7 and S8 entries (#3).
          return await errorTermination("S7", err);
        }
        break;
      }

      case "S9":
      case "S10":
      case "S11":
      case "S12": {
        // #600 online review loop: bot poll → fresh verify → fixer → fresh verify
        // (ADR 0061). S11/S12 remain stub workers until #603.
        if (worktree === undefined) {
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
        if (lastShipOutput === undefined || lastShipOutput.pr === undefined) {
          return await errorTermination(
            step,
            new Error(
              `${step} requires a prior S7 pr_opened ship output with a PR URL`,
            ),
          );
        }
        let reviewStep = step;
        const reviewHeadKey =
          onlineReviewResumeHeadKeyFromLedger(ledger) ??
          convergenceHeadToRecord({
            shipHead: lastShipOutput.prHead,
            snapshotHead: onlineReviewLanding?.onlineReviewSnapshot?.headOid,
            postFixHead: lastOnlineReviewFixCommitSha,
          });
        if (
          reviewStep === "S9" &&
          onlineReviewConvergedForHead(ledger, reviewHeadKey)
        ) {
          reviewStep = "S11";
        }
        const reviewLoopSpec =
          reviewStep === "S9"
            ? verifyWorkerSpec(routePolicy.route)
            : reviewStep === "S10"
              ? fixerWorkerSpec(routePolicy.route)
              : reviewStep === "S11"
                ? cleanupWorkerSpec(routePolicy.route)
                : docReleaseWorkerSpec(routePolicy.route);
        promptFile = reviewLoopSpec.promptFile;
        try {
          if (reviewStep === "S9") {
            const snapshot = await pollOnlineReviewForShip(
              lastShipOutput,
              onlineReviewRound,
            );
            if (stateDir !== undefined) {
              writeOnlineReviewSnapshotFile(stateDir, snapshot);
            }
            onlineReviewLanding = buildOnlineReviewLanding(
              snapshot,
              lastShipOutput,
              onlineReviewRound,
            );
          }
          const reviewCtx = {
            worktree,
            stateDir,
            repo: defaultRepo(),
            prUrl: lastShipOutput.pr,
            prHead:
              onlineReviewLanding?.shipDelivery?.prHead ?? lastShipOutput.prHead,
            onlineReviewRound,
          };
          const headBefore =
            reviewStep === "S9" ? await resolveBranchHEAD() : undefined;
          const reviewResetOpt: MechanicalRetryOptions =
            reviewStep !== "S9" && worktree != null
              ? { resetBeforeRetry: () => backend.cleanResidue(worktree!) }
              : reviewStep === "S9"
                ? {
                    callerOwns: (o) =>
                      "kind" in o &&
                      o.kind === "thrown" &&
                      o.error instanceof VerifyWorkerHeadMovedError,
                    rethrowOnExhaustion: true,
                  }
                : {};
          if (
            reviewStep === "S10" &&
            (onlineReviewLanding === undefined ||
              onlineReviewLanding.onlineReviewSnapshot === undefined)
          ) {
            return await errorTermination(
              reviewStep,
              new Error(
                `${reviewStep} requires a reconstructed online review landing with ` +
                  "onlineReviewSnapshot — resume must rebuild from the full ledger " +
                  "and persisted snapshot before dispatching the fixer",
              ),
            );
          }
          const fixerLanding =
            reviewStep === "S10" && onlineReviewLanding !== undefined
              ? {
                  ...onlineReviewLanding,
                  fixMarkedFindingIdentityKeys:
                    onlineReviewLanding.fixMarkedFindingIdentityKeys ?? [],
                }
              : onlineReviewLanding;
          let result: Awaited<ReturnType<typeof withMechanicalRetry>>;
          try {
            result = await withMechanicalRetry(
              reviewLoopSpec,
              reviewCtx,
              async (s, c) => {
                const workerResult = await dispatchWorker(
                  backend,
                  s,
                  c,
                  reviewStep === "S9" || reviewStep === "S10"
                    ? fixerLanding
                    : undefined,
                );
                if (reviewStep === "S9" && headBefore !== undefined) {
                  const headAfterAttempt = await resolveBranchHEAD();
                  if (headAfterAttempt !== headBefore) {
                    throw new VerifyWorkerHeadMovedError(
                      headBefore,
                      headAfterAttempt,
                    );
                  }
                }
                return workerResult;
              },
              reviewResetOpt,
            );
          } catch (err) {
            if (err instanceof VerifyWorkerHeadMovedError) {
              const stopSummary = verifyReviewerHeadMovedStopSummary({
                headBefore: err.headBefore,
                headAfter: err.headAfter,
              });
              return await errorTermination(reviewStep, err, { stopSummary });
            }
            throw err;
          }
          if (result.kind !== "completed") {
            return await errorTermination(
              reviewStep,
              new Error(
                `${reviewStep} worker returned ${result.kind}` +
                  ("reason" in result ? `: ${result.reason}` : ""),
              ),
            );
          }
          const outputValid =
            (reviewStep === "S9" && isValidVerifyResult(result.output)) ||
            (reviewStep === "S10" && isValidFixerResult(result.output)) ||
            (reviewStep === "S11" && isValidCleanupResult(result.output)) ||
            (reviewStep === "S12" && isValidDocReleaseResult(result.output));
          if (!outputValid) {
            const badKind = (result.output as { kind?: unknown } | undefined | null)?.kind;
            return await errorTermination(
              reviewStep,
              new Error(
                `${reviewStep} worker returned non-${reviewStep} output kind '${String(badKind)}'`,
              ),
            );
          }
          if (reviewStep === "S9" && isValidVerifyResult(result.output)) {
            let verifyOutput = clampVerifyConvergenceForCheckRuns(
              result.output,
              onlineReviewLanding?.onlineReviewSnapshot,
            );
            const recheckOutcome = enforceRunnerOwnedRecheck(
              verifyOutput,
              onlineReviewRound,
            );
            if (recheckOutcome.kind === "recheck_contradiction") {
              return await errorTermination(
                reviewStep,
                new Error(
                  "online review verify worker contradicted runner-owned recheck truth (isRecheck)",
                ),
                {
                  output: verifyOutput,
                  stopSummary: {
                    reason: "infra_failure",
                    summary:
                      "online review verify worker contradicted runner-owned recheck truth (isRecheck)",
                    repairHint:
                      "omit isRecheck on round-1 verify; set isRecheck:true only on post-fixer re-check rounds",
                  },
                },
              );
            }
            verifyOutput = recheckOutcome;
            const headAfter = await resolveBranchHEAD();
            if (headBefore !== undefined && headAfter !== headBefore) {
              const stopSummary = verifyReviewerHeadMovedStopSummary({
                headBefore,
                headAfter,
              });
              return await errorTermination(reviewStep, new Error(stopSummary.summary), {
                stopSummary,
              });
            }
            let sideEffects: ReturnType<typeof applyVerifySideEffects>;
            try {
              sideEffects =
                lastShipOutput.pr != null &&
                isLiveGithubReviewPollEnabled(lastShipOutput.pr, reviewCtx.repo!)
                  ? applyVerifySideEffects({
                      sh: ghSh,
                      repo: reviewCtx.repo!,
                      prUrl: lastShipOutput.pr,
                      verify: verifyOutput,
                      fixingCommitSha:
                        onlineReviewRound > 1
                          ? lastOnlineReviewFixCommitSha
                          : undefined,
                      landingThreads:
                        onlineReviewLanding?.onlineReviewSnapshot?.threads,
                    })
                  : {
                      deferredIssueUrls: [],
                      repliesPosted: [],
                      threadsResolved: [],
                    };
            } catch (err) {
              return await errorTermination(reviewStep, err, {
                output: verifyOutput,
                stopSummary: verifySideEffectFailureStopSummary(err),
              });
            }
            verifyOutput = {
              ...verifyOutput,
              ...(sideEffects.deferredIssueUrls.length > 0
                ? { deferredIssueUrls: sideEffects.deferredIssueUrls }
                : {}),
            };
            const fixKeys = fixMarkedKeysFromVerify(verifyOutput);
            if (onlineReviewLanding !== undefined) {
              onlineReviewLanding = {
                ...onlineReviewLanding,
                fixMarkedFindingIdentityKeys: fixKeys,
              };
            }
            if (verifyOutput.converged && stateDir !== undefined) {
              const markerHead = convergenceHeadToRecord({
                shipHead: lastShipOutput.prHead,
                snapshotHead:
                  onlineReviewLanding?.onlineReviewSnapshot?.headOid,
                postFixHead: lastOnlineReviewFixCommitSha,
                branchHeadAfter: headAfter,
              });
              const marker = {
                step: "S9" as const,
                event: "online_review_converged" as const,
                prUrl: lastShipOutput.pr!,
                prHead: markerHead ?? headAfter,
                onlineReviewRound,
              };
              ledger.push(marker);
              try {
                await backend.writeLedger(
                  {
                    step: "S9",
                    event: "online_review_converged",
                    prUrl: marker.prUrl,
                    prHead: marker.prHead,
                    onlineReviewRound,
                    sessionId,
                    prompt_hash: await hashPrompt(promptFile, "S9", backend),
                    branchHEAD: headAfter,
                    ts: new Date().toISOString(),
                  },
                  stateDir,
                );
              } catch (err) {
                return await errorTermination(reviewStep, err, { recordInMemory: false });
              }
            }
            output = verifyOutput;
          } else {
            output = result.output;
          }
          if (
            reviewStep === "S10" &&
            isValidFixerResult(result.output) &&
            result.output.committed
          ) {
            lastOnlineReviewFixCommitSha = await resolveBranchHEAD();
            if (
              lastShipOutput.pr != null &&
              isLiveGithubReviewPollEnabled(lastShipOutput.pr, reviewCtx.repo!)
            ) {
              const nextRound = onlineReviewRound + 1;
              const fixCommittedMarker = {
                step: "S10" as const,
                event: "online_review_fix_committed" as const,
                fixCommitSha: lastOnlineReviewFixCommitSha!,
                onlineReviewRound,
              };
              ledger.push(fixCommittedMarker);
              if (stateDir !== undefined) {
                try {
                  await backend.writeLedger(
                    {
                      ...fixCommittedMarker,
                      sessionId,
                      prompt_hash: await hashPrompt(promptFile, "S10", backend),
                      branchHEAD: lastOnlineReviewFixCommitSha,
                      ts: new Date().toISOString(),
                    },
                    stateDir,
                  );
                } catch (err) {
                  return await errorTermination(reviewStep, err, {
                    recordInMemory: false,
                  });
                }
              }
              const retriggered = retriggerBotsAndPoll(
                ghSh,
                reviewCtx.repo!,
                lastShipOutput.pr,
                1,
                lastOnlineReviewFixCommitSha ??
                  lastOnlineReviewRoundTrigger?.headOid ??
                  lastShipOutput.prHead ??
                  "offline-review-head",
              );
              lastOnlineReviewRoundTrigger = retriggered.roundTrigger;
              const retriggerMarker = {
                step: "S10" as const,
                event: "online_review_round_retrigger" as const,
                roundTriggerHeadOid: retriggered.roundTrigger.headOid,
                roundTriggerAt: retriggered.roundTrigger.triggeredAt,
                onlineReviewRound: nextRound,
              };
              ledger.push(retriggerMarker);
              if (stateDir !== undefined) {
                try {
                  await backend.writeLedger(
                    {
                      ...retriggerMarker,
                      sessionId,
                      prompt_hash: await hashPrompt(promptFile, "S10", backend),
                      branchHEAD: lastOnlineReviewFixCommitSha,
                      ts: new Date().toISOString(),
                    },
                    stateDir,
                  );
                } catch (err) {
                  return await errorTermination(reviewStep, err, {
                    recordInMemory: false,
                  });
                }
              }
            }
            onlineReviewRound += 1;
          }
          step = reviewStep;
          stepSessionId = result.sessionId;
          lastOutput = output;
        } catch (err) {
          return await errorTermination(step, err);
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
    const stepRepairMovementPaths =
      output?.kind === "coder" ? lastCoderActualRepairPaths : undefined;

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
      ...(stepRepairMovementPaths !== undefined
        ? { repairMovementPaths: stepRepairMovementPaths }
        : {}),
    });
    // #6: a writeLedger failure here is a backend-call exception → it must
    // converge to S8(error) with an error package, NOT raw-reject out of
    // runOrchestrator (PRD route table: any backend call throwing → S8(error)).
    // The step is already recorded in-memory above, so don't double-record it.
    try {
      // #256: pass the real per-step sandbox session id (captured from the seam
      // extension) so the ledger records the true id resumeSession will resume.
      await emitLedger(
        step,
        output,
        promptFile,
        undefined,
        stepSessionId,
        stepFindingDispositions,
        undefined,
        undefined,
        stepRepairMovementPaths,
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
        repairMovementPaths: stepRepairMovementPaths,
      });
    }

    // The runner — not the agent — decides the next step.
    // The runner owns the review/fix loop, but termination is still not a blind
    // "count rounds then give up" rule. Only malformed reviewer outputs have a
    // bounded rerun budget; substantive convergence is driven by fresh reviewer
    // findings and explicit escalation.
    const decision = route({
      from: step,
      output: lastOutput,
      ...(step === "S4"
        ? { pendingBlockingFindings }
        : {}),
      ...(step === "S7"
        ? {
            shipStatus:
              lastShipOutput?.status ??
              (family?.noPush ? "pushed" : undefined),
          }
        : {}),
      ...(step === "S9" || step === "S10"
        ? { onlineReviewRound }
        : {}),
    });

    if (decision.kind === "handoff") {
      // Online-review decision terminals map to escalationKind:"failure" pending
      // #604's A/B re-open channel (B-class summary + A-class kind pairing is deliberate).
      const handoffStopSummary: StopSummary =
        decision.status === "success"
          ? successSummaryForCurrentState({ deferredFindings, findingDispositions })
          : decision.status === "error"
            ? stopSummaryForErrorPackage({
                failedStep: step,
                reason: buildErrorReason(step, lastOutput),
                branchHead: worktree?.branch,
              })
            : decision.onlineReviewTerminal === "decision_gate_raised"
              ? onlineReviewFixerNothingToFixStopSummary()
              : decision.onlineReviewTerminal === "round_budget_exhausted"
                ? {
                    reason: "decision_gate_park",
                    summary:
                      "online review loop exhausted the 3-round budget (round_budget_exhausted) with remaining findings",
                    repairHint:
                      "answer the decision gate or defer remaining findings, then rerun",
                  }
                : decision.onlineReviewTerminal === "contract_drift"
                  ? {
                      reason: "contract_drift",
                      summary:
                        "online review verify worker moved HEAD (contract_drift)",
                      repairHint:
                        "restore the verify/fixer role boundary so verify leaves HEAD unchanged, then rerun the online review loop",
                    }
                  : stopSummaryForEscalation(
                      escalateOf(lastOutput) ?? {
                        reason: "run escalated",
                        diagnosis: `step ${step} routed to an escalate handoff`,
                      },
                    );
      ledger.push({ step: "S8", stopSummary: handoffStopSummary });
      // #249: persist the S8 handoff entry too.
      // #6 / integ-cmr base r2 (E): a writeLedger failure on the S8 entry →
      // S8(error), not a raw rejection. (deferredFindings stays whatever was
      // collected.)
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
          escalationKindForHandoff(decision.status, lastOutput),
          handoffStopSummary,
        );
      } catch (err) {
        // integ-cmr base r2 (E): the failing operation here is the S8 handoff
        // ledger write — which happens for ANY handoff (S2 no-commit error,
        // route error, escalate, push success). The old code hard-coded
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
          deferredFindings,
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
          deferredFindings,
        };
      }

      return {
        status: decision.status,
        branch: decision.status === "success" ? worktree?.branch : undefined,
        stepLedger: ledger,
        stopSummary: handoffStopSummary,
        deferredFindings,
      };
    }

    step = decision.step;
  }
  // Unreachable: the `for (;;)` loop exits only via a `return` above — every
  // route() handoff returns and the no-progress guard returns. There is no
  // round/step cap to fall out of (US#18: no "数到 N 就停").
}
