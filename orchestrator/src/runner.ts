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
 * #331 (ADR 0026 / PRD #330): the runner dispatches every WORKER step (S2 build +
 *   S7 ship) through the single unified seam `dispatchWorker(backend, spec, ctx)`
 *   (dispatchWorker.ts) instead of reaching for `runStep` / `resumeSession` /
 *   `push` directly.
 */

import { route } from "./route.js";
import { classifyFindings, findingIdentityKey } from "./findings.js";
// The unified worker-dispatch seam (ADR 0026 / PRD #330 #331): the runner
// dispatches EVERY worker step (S2 build, S7 ship) through ONE free function
// instead of reaching for runStep/resumeSession/push directly.
import {
  dispatchWorker,
  shipWorkerSpec,
  stepSpecToWorkerSpec,
  workerResultToStep,
} from "./dispatchWorker.js";
import { isFilledString } from "./shipOutcome.js";
// Shared seam guards — single source of truth, also used by route(), so the
// coder-output / commitsAdded rules can never drift.
import {
  escalateOf,
  isValidEscalation,
  isValidStepOutput,
} from "./validate.js";
import type {
  Backend,
  ErrorPackage,
  Escalation,
  Finding,
  HandoffStatus,
  IssueMeta,
  IssueSnapshot,
  LedgerEntry,
  PersistentLedgerEntry,
  ResumeState,
  RunInput,
  RunResult,
  StepId,
  StepOutput,
  StepSpec,
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
  readonly lastOutput?: StepOutput;
  readonly priorLedger: ReadonlyArray<LedgerEntry>;
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

function lastReviewerOutput(
  ledger: ReadonlyArray<LedgerEntry>,
): StepOutput | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const output = ledger[i]?.output;
    if (output?.kind === "reviewer") return output;
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
 *   2. The last agent output escalated → the human has answered; resume THAT
 *      step in its original session (resumeSession + sessionId). This takes
 *      precedence over a trailing S8(escalate) entry — re-feeding an escalation
 *      means "the human answered, continue", not "report escalate again".
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
): ResumePlan {
  if (ledger.length === 0) {
    return { resumeStep: "S0", priorLedger: [] };
  }

  const lastEntry = ledger[ledger.length - 1]!;
  const agentEntry = lastAgentEntry(ledger);

  // Case 2: escalate residue — the last agent output carries a WELL-FORMED
  // escalation. The human has answered; resume THAT step in its original agent
  // session. Checked before the terminal-handoff case so a trailing S8(escalate)
  // entry does not short-circuit into "report escalate again".
  //
  // integ-cmr m2 r1 (Finding 2): the guard is isValidEscalation, NOT a bare
  // non-null check. route.ts:81 / validate.ts treat a MALFORMED escalate (e.g.
  // `{}`, blank reason/diagnosis) as a contract violation → S8(status=error),
  // and the runner tags that S8 handoffStatus:'error'. With a bare `!= null`
  // check, Case 2 would fire on the garbage escalate BEFORE Case 3a's
  // terminal-status report, silently re-running the step via resumeSession
  // instead of reporting the true tagged error. Gating on isValidEscalation lets
  // a malformed escalate fall through to Case 3a — only a well-shaped escalate
  // (a real "human answered an escalation" signal) triggers escalate-resume.
  //
  // integ-cmr m2 r2 (#252 ⋈ #255): a tagged terminal S8(error) ALSO supersedes
  // escalate-resume, even when the escalate is WELL-FORMED. An escalate handoff
  // whose S8 write faulted returns status:error in-run and best-effort persists
  // a tagged 'error' S8 — the disk then holds a valid-escalate agent entry AND a
  // trailing S8(error). The run errored; re-feeding must report that ERROR (Case
  // 3a), NOT re-run the escalating step via resumeSession. So Case 2 yields when
  // the last entry is a tagged terminal-error S8. (A legitimate human-answered
  // escalate ends with S8(escalate) — NOT error — so it still resumes here.)
  const lastIsTaggedError =
    lastEntry.step === "S8" && lastEntry.handoffStatus === "error";
  const agentEscalate = escalateOf(agentEntry?.output);
  if (
    !lastIsTaggedError &&
    agentEntry !== undefined &&
    agentEscalate != null &&
    isValidEscalation(agentEscalate)
  ) {
    // Drop the prior terminal handoff (and any entries after the escalated
    // step): we are re-opening that step, so the prior boundary is superseded.
    // The slice is EXCLUSIVE of the escalated step itself — it is re-run via
    // resumeSession and gets a fresh in-memory entry, so keeping the old one
    // here would duplicate it. ADR 0030 has multiple agent steps (S2/S3/S5/S6);
    // whichever one escalated is resumed in its recorded session after the human
    // answer, while normal review/fix rounds stay fresh dispatches.
    const escalatedIdx = ledger.lastIndexOf(agentEntry);
    const priorLedger = ledger.slice(0, escalatedIdx);
    return {
      resumeStep: agentEntry.step,
      resumeSessionId: agentEntry.sessionId,
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
  // Recognise the pattern — last entry is S8(escalate) AND the deciding step is S7
  // — and RE-DISPATCH S7 (re-run the ship worker fresh; ship is a clean-session
  // runner action, so there is no agent session to resumeSession into). Drop the
  // trailing S8 boundary: we are re-opening, so the prior terminal is superseded.
  // Only the SHIP step re-opens this way; an agent escalate (S2 build worker) is
  // caught by Case 2 above (it has a well-formed escalate output) and never reaches here.
  if (
    lastEntry.step === "S8" &&
    lastEntry.handoffStatus === "escalate" &&
    lastNonTerminalStep(ledger) === "S7"
  ) {
    // Re-opening S7 means the OLD S7 entry is superseded — drop BOTH the trailing
    // S8(escalate) boundary AND the failing S7 entry it terminated. Slicing only at
    // the S8 (the old `slice(0, s8Idx)`) LEFT the old S7 in the in-memory ledger, so
    // the re-dispatch appended a SECOND S7 → two consecutive S7 entries (online
    // review r1, 3 bots). The escalate-resume contract re-opens the step, it does
    // not keep the superseded one. The S7 entry being re-opened is the last
    // non-terminal (non-S8) entry; truncate at its index.
    let reopenIdx = ledger.length - 1;
    while (reopenIdx >= 0 && ledger[reopenIdx]!.step === "S8") reopenIdx--;
    // reopenIdx now points at the failing S7 entry (lastNonTerminalStep === "S7").
    return {
      resumeStep: "S7",
      lastOutput: agentEntry?.output,
      priorLedger: ledger.slice(0, reopenIdx) as ReadonlyArray<LedgerEntry>,
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
      ? lastNonTerminalStep(ledger) ?? lastEntry.step
      : lastEntry.step;
  const decision = route({ from: routeFrom, output: agentEntry?.output });
  if (decision.kind === "handoff") {
    return {
      terminalStatus: decision.status,
      resumeStep: "S8",
      lastOutput: agentEntry?.output,
      priorLedger: ledger as ReadonlyArray<LedgerEntry>,
    };
  }
  return {
    resumeStep: decision.step,
    lastOutput: agentEntry?.output,
    priorLedger: ledger as ReadonlyArray<LedgerEntry>,
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
 * Swapping models = set ORCHESTRATOR_CODER_MODEL (see {@link coderModel}); no image
 * rebuild, no structural StepSpec change (PRD #244 Implementation Decisions).
 */

/**
 * The S2 coder worker's model slug, switchable via `ORCHESTRATOR_CODER_MODEL`
 * (default `"gpt-5.5"`). Swapping the coder backend (codex gpt-5.5 ↔ a Claude
 * coder ↔ …) is THIS env alone — the slug is resolved to the baked CLI by
 * agentForSlug, an invalid slug fails closed at modelIdForSlug, and the auth mount
 * is best-effort for both the codex and claude legs (realBackend mountAuth), so no
 * auth-wiring change is needed to switch. The user's standing decision: make the
 * coder model conveniently switchable rather than hard-coded.
 */
export function coderModel(): string {
  return process.env.ORCHESTRATOR_CODER_MODEL?.trim() || "gpt-5.5";
}

export const STEP_SPECS: Readonly<Record<"S2" | "S3" | "S5" | "S6", StepSpec>> = {
  S2: {
    id: "S2",
    role: "coder",
    promptFile: "coder_implement.md",
    // The whole-slice build worker's model is env-switchable (default Codex
    // gpt-5.5; was Sonnet 4.6). The slug is resolved to the baked CLI by
    // agentForSlug (realBackend); switching the model is `ORCHESTRATOR_CODER_MODEL`
    // alone — no image rebuild, no StepSpec shape change.
    model: coderModel(),
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    soul: "coder",
    toolchain: IMAGE_TOOLCHAIN,
  },
  S3: {
    id: "S3",
    role: "reviewer",
    promptFile: "reviewer_review.md",
    model: process.env.ORCHESTRATOR_REVIEWER_MODEL?.trim() || "gpt-5.5",
    completionSignal: "REVIEWER_STEP_COMPLETE",
    maxIter: 1,
    soul: "READ-ONLY",
    toolchain: IMAGE_TOOLCHAIN,
  },
  S5: {
    id: "S5",
    role: "coder",
    promptFile: "coder_fix.md",
    model: coderModel(),
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    soul: "coder",
    toolchain: IMAGE_TOOLCHAIN,
  },
  S6: {
    id: "S6",
    role: "reviewer",
    promptFile: "reviewer_review.md",
    model: process.env.ORCHESTRATOR_REVIEWER_MODEL?.trim() || "gpt-5.5",
    completionSignal: "REVIEWER_STEP_COMPLETE",
    maxIter: 1,
    soul: "READ-ONLY",
    toolchain: IMAGE_TOOLCHAIN,
  },
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

export async function runOrchestrator(input: RunInput): Promise<RunResult> {
  const { issueNumber, backend } = input;
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
  // Collected at S4: reviewer findings with action:'defer' (PRD #244 US#25).
  // Surfaced in RunResult.deferredFindings so the caller can act on them.
  let deferredFindings: Finding[] = [];
  let pendingBlockingFindings: Finding[] = [];
  let pendingBlockingFindingIdentityKeys: string[] = [];

  function seedClassificationFromReviewerOutput(
    reviewerOutput: StepOutput | undefined,
  ): void {
    if (reviewerOutput?.kind !== "reviewer") return;
    const classification = classifyFindings(reviewerOutput.findings);
    const blockingKeys = new Set(classification.blockingIdentityKeys);
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
    pendingBlockingFindings = [...classification.blocking];
    pendingBlockingFindingIdentityKeys = [
      ...classification.blockingIdentityKeys,
    ];
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
    });

    if (stateDir === undefined) {
      // stateDir not yet known — buffer until S1 resolves the worktree path.
      pendingEntries.push(entry);
      return;
    }

    // stateDir is now known: drain the buffer one entry at a time, removing
    // each item ONLY AFTER its write succeeds.  If writeLedger rejects, the
    // remaining entries stay in the buffer — they are never silently dropped.
    while (pendingEntries.length > 0) {
      await backend.writeLedger(pendingEntries[0]!, stateDir);
      pendingEntries.shift();
    }
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
  ): Promise<void> {
    try {
      await emitLedger(s, output, promptFile, handoffStatus, stepSessionId);
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
    opts?: { recordInMemory?: boolean; output?: StepOutput },
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

    // Record the failing step. The in-memory push is skipped when the caller
    // already pushed it (recordInMemory:false) or it is S8 itself; the
    // best-effort persist is still attempted so disk and memory agree (D),
    // carrying the failing step's output (F3).
    if (failedStep !== "S8") {
      if (recordInMemory) {
        ledger.push(
          opts?.output === undefined
            ? { step: failedStep }
            : { step: failedStep, output: opts.output },
        );
      }
      await persistBestEffort(failedStep, opts?.output, undefined);
    }

    // Terminal S8 entry — in-memory + persisted. The PERSISTED entry is TAGGED
    // with the terminal status (integ-cmr m2 r1, Finding 1): errorTermination is
    // always an ERROR handoff, so the disk S8 must carry handoffStatus:'error';
    // a re-feed then reports the true error via planResume Case 3a instead of
    // falling through to Case 3b/4 (which would re-route from the prior NON-S8
    // step — reporting a spurious success). The in-memory entry stays untagged,
    // matching the normal handoff path (only the disk ledger is the resume truth;
    // the in-memory ledger is the live result).
    ledger.push({ step: "S8" });
    await persistBestEffort("S8", undefined, undefined, "error");

    // An error abort surfaces an (always-empty) defer list — the single-slice
    // runner no longer collects defers (the per-slice cmr handles them inside S2).
    return {
      status: "error",
      errorPackage,
      stepLedger: ledger,
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
   * The worker `sessionId` is PERSISTED on the failing-step entry (resume truth)
   * so the data for a future human-answer RESUME exists. #331 scope: a re-feed
   * reports the escalate cleanly; REOPENING the S7 ship worker in its session
   * (S7 escalate-resume) is #336's concern (the real gstack-ship STOP/HITL with
   * resume指引) — the legacy ship wrapper never escalates, so #331 needs only the
   * honest terminal + the recorded session id, not a new S7 resume entry path.
   */
  async function escalateTermination(
    failedStep: StepId,
    escalation: Escalation,
    sessionId?: string,
  ): Promise<RunResult> {
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
        failedStep === "S7" ? shipWorkerSpec().promptFile : undefined;
      await persistBestEffort(failedStep, undefined, failedPromptFile, undefined, sessionId);
    }
    ledger.push({ step: "S8" });
    await persistBestEffort("S8", undefined, undefined, "escalate");
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

  if (resumeState !== undefined && resumeState.ledger.length > 0) {
    const plan = planResume(resumeState.ledger);

    // Reuse the resident worktree (NO re-cut) and fix the sibling stateDir.
    worktree = resumeState.worktree;
    stateDir = resumeState.stateDir;

    // Seed the in-memory ledger with prior progress so committed work is
    // preserved and the prior steps are NOT re-run.
    for (const e of plan.priorLedger) ledger.push(e);
    lastOutput = plan.lastOutput;

    // ADR 0030: if the prior run already persisted S4, resume can jump straight
    // to S5/S7. Rebuild the S4 classification state from the persisted reviewer
    // output so S5 receives the blocking findings and S7 reports defers.
    if (plan.resumeStep === "S5") {
      seedClassificationFromReviewerOutput(
        lastReviewerOutput(plan.priorLedger) ?? lastOutput,
      );
    } else if (plan.resumeStep === "S7") {
      seedClassificationFromReviewerOutput(lastOutput);
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
        return {
          status: "error",
          errorPackage,
          stepLedger: ledger,
          deferredFindings,
        };
      }
      return {
        status: plan.terminalStatus,
        branch: plan.terminalStatus === "success" ? worktree.branch : undefined,
        stepLedger: ledger,
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
        // A gate violation throws immediately — the runner stops here, no
        // worktree is prepared, no agent step is dispatched. Gate throws are
        // intentionally NOT converted to an error handoff (they are a caller
        // input fault, not a pipeline error); only the backend fetch is.
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
          throw new Error(
            `S0 input gate: issue #${issueNumber} is CLOSED. ` +
              `Feed an open, ready-for-agent slice; a closed issue is already done.`,
          );
        }

        if (!meta.isReadyForAgent) {
          throw new Error(
            `S0 input gate: issue #${issueNumber} is not labelled ready-for-agent. ` +
              `Triage the issue and apply the label before running the orchestrator.`,
          );
        }

        if (meta.hasSubIssues) {
          throw new Error(
            `S0 input gate: issue #${issueNumber} is a parent issue (it has sub-issues). ` +
              `Feed a leaf slice issue, not a parent/epic.`,
          );
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
          throw new Error(
            `S0 input gate: issue #${issueNumber} is blocked by upstream issues that are still open: ${blockers}. ` +
              `Merge the upstream changes before running.`,
          );
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
        promptFile = STEP_SPECS[step].promptFile;
        const expectedKind = STEP_SPECS[step].role;
        try {
          let resumeSessionId: string | undefined;
          if (resumeFor !== undefined && resumeFor.step === step) {
            resumeSessionId = resumeFor.sessionId;
            resumeFor = undefined;
          }

          let attempts = 0;
          for (;;) {
            attempts += 1;
            let result: Awaited<ReturnType<typeof dispatchWorker>>;
            try {
              result = await dispatchWorker(
                backend,
                stepSpecToWorkerSpec(
                  STEP_SPECS[step],
                  resumeSessionId !== undefined ? "resume" : "fresh",
                ),
                {
                  worktree,
                  stateDir,
                  ...(resumeSessionId !== undefined ? { resumeSessionId } : {}),
                  ...(step === "S5"
                    ? {
                        blockingFindings: pendingBlockingFindings,
                        blockingFindingIdentityKeys:
                          pendingBlockingFindingIdentityKeys,
                      }
                    : {}),
                },
              );
            } catch (err) {
              if (
                expectedKind === "reviewer" &&
                attempts < MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS
              ) {
                resumeSessionId = undefined;
                continue;
              }
              if (expectedKind === "reviewer") {
                output = {
                  kind: "reviewer",
                  findings: [],
                  escalate: {
                    reason: "reviewer output remained invalid after bounded reruns",
                    diagnosis:
                      `step ${step} failed to produce valid reviewer output ` +
                      `${attempts} times; last error: ${errorMessage(err)}`,
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
        break;
      }

      case "S4": {
        seedClassificationFromReviewerOutput(lastOutput);
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
          const shipSpec = shipWorkerSpec();
          promptFile = shipSpec.promptFile;
          const shipResult = await dispatchWorker(backend, shipSpec, {
            worktree,
          });
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
          stepSessionId = shipResult.sessionId;
        } catch (err) {
          // Push failure → S8(error) with branch head so dev can diagnose
          // without losing the commits already on the resident branch (#252).
          // errorTermination records + persists both the S7 and S8 entries (#3).
          return await errorTermination("S7", err);
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

    // Record this step in the ledger (anti-skip + resume truth, ADR 0018 §3).
    // #249: also persist via backend.writeLedger (sibling state dir).
    ledger.push(output === undefined ? { step } : { step, output });
    // #6: a writeLedger failure here is a backend-call exception → it must
    // converge to S8(error) with an error package, NOT raw-reject out of
    // runOrchestrator (PRD route table: any backend call throwing → S8(error)).
    // The step is already recorded in-memory above, so don't double-record it.
    try {
      // #256: pass the real per-step sandbox session id (captured from the seam
      // extension) so the ledger records the true id resumeSession will resume.
      await emitLedger(step, output, promptFile, undefined, stepSessionId);
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
      });
    }

    // The runner — not the agent — decides the next step.
    // The runner owns the review/fix loop, but termination is still not a blind
    // "count rounds then give up" rule. Only malformed reviewer outputs have a
    // bounded rerun budget; substantive convergence is driven by fresh reviewer
    // findings and explicit escalation.
    const decision = route({ from: step, output: lastOutput });

    if (decision.kind === "handoff") {
      ledger.push({ step: "S8" });
      // #249: persist the S8 handoff entry too.
      // #6 / integ-cmr base r2 (E): a writeLedger failure on the S8 entry →
      // S8(error), not a raw rejection. (deferredFindings stays whatever was
      // collected.)
      // #255: tag the entry with the terminal status (decision.status) so a
      // resuming run can tell a prior success / escalate / error apart (the S8
      // entry is otherwise identical for all three).
      try {
        await emitLedger("S8", undefined, undefined, decision.status);
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
        // persistBestEffort swallows a secondary write fault — we already return
        // status:error, a second ledger fault must not mask the original cause.
        await persistBestEffort("S8", undefined, undefined, "error");
        const errorPackage: ErrorPackage = {
          failedStep: "S8",
          reason: `writeLedger(S8) failed while persisting the handoff entry: ${cause}`,
          branchHead: worktree?.branch,
        };
        return {
          status: "error",
          errorPackage,
          stepLedger: ledger,
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
          deferredFindings,
        };
      }

      return {
        status: decision.status,
        branch: decision.status === "success" ? worktree?.branch : undefined,
        stepLedger: ledger,
        deferredFindings,
      };
    }

    step = decision.step;
  }
  // Unreachable: the `for (;;)` loop exits only via a `return` above — every
  // route() handoff returns and the no-progress guard returns. There is no
  // round/step cap to fall out of (US#18: no "数到 N 就停").
}
