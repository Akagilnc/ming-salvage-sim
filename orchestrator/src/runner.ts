/**
 * runOrchestrator — the runner loop (ADR 0018).
 *
 * The runner drives the fixed S0–S8 sequence itself: it performs each
 * runner-action step or dispatches each agent step, writes a step-ledger
 * entry, then calls route() to pick the next step. The agent never decides
 * the next step — route() does.
 *
 * Slice #247: happy path S0–S3–S4(approve)–S7–S8.
 * Slice #249: persisted step ledger — every step is written via
 *   backend.writeLedger() to the sibling state dir (outside the worktree).
 * Slice #250: S4 severity+action fan-out (P0/P1 or fix_now → S5; defer → S7).
 * Slice #251: global escalate stop edge (in route()).
 * Slice #252: error edges —
 *   - S2 committed:false → S8(error)  [route() detects]
 *   - S7 push() throws  → S8(error)   [runner catch]
 *   - any backend call throws → S8(error) + error package  [runner catch]
 *   - any agent output carries escalate → S8(escalate) [route() detects]
 * Slice #253: StepSpec contract — model/completionSignal/maxIter/soul/toolchain.
 * Slice #248: S0 input gate — four-way accept condition (rfa ∧ Agent Brief ∧
 *   no sub-issues ∧ blocked_by all closed); violations throw, stopping at S0.
 * Slice #254: fix-loop back-edge — route() wires S5→S6→S4→(S5|S7); the runner
 *   already dispatches S5/S6 as agent steps and re-collects defers at S4 each
 *   pass, so the loop iterates with no runner change. Co-exists with the
 *   escalate stop (#251) and error edges (#252): S5 0-commit → S8(error),
 *   any S5/S6 escalate → S8(escalate).
 * cmr S254: removed the round-counting MAX_STEPS cap (it limited fix rounds to
 *   ~8, violating US#18 "不因数到某个轮数就停") and replaced it with a
 *   no-progress stuck guard: the loop runs unbounded while it makes progress
 *   (the reviewer findings change each round) and bails cleanly to
 *   S8(status=error) only after K consecutive no-progress rounds. (Integ
 *   reconcile with base rule B: the original commit-leg of the progress signal
 *   is degenerate under the committed⟺commitsAdded≥1 contract, so progress is
 *   findings-change only — see the guard block for the full rationale.)
 */

import { route } from "./route.js";
// Shared seam guards — single source of truth, also used by route(), so the
// finding-element (A) / commitsAdded (B) rules can never drift.
import {
  isValidEscalation,
  isValidReviewerOutput,
  isValidStepOutput,
} from "./validate.js";
import type {
  Backend,
  ErrorPackage,
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
  StepResult,
  StepSpec,
  WorktreeHandle,
} from "./types.js";

// ─── #256 seam-extension normalisation ───────────────────────────────────────

/**
 * Normalise an agent-step return into `{ output, sessionId }`.
 *
 * #256 widened {@link Backend.runStep} / {@link Backend.resumeSession} from
 * `StepOutput` to `StepOutput | StepResult` (the seam extension). The two shapes
 * are distinguished purely by the `kind` discriminant: a {@link StepOutput} (a
 * CoderOutput / ReviewerOutput) always carries `kind:'coder'|'reviewer'`; a
 * {@link StepResult} wraps the output under `.output` and has NO top-level
 * `kind`. So:
 *   - a value with `kind` → a bare StepOutput (the zero-container fake path) →
 *     `sessionId: undefined` (the ledger falls back to the run-level UUID);
 *   - a value without `kind` → a StepResult (the real Backend) → carries the
 *     real per-step sandbox `sessionId`.
 *
 * Keeping this normalisation OUTSIDE the route()/error control flow is what makes
 * the runner identical for fake and real Backends (#256 "控制流零改动").
 */
function normalizeStepResult(
  ret: StepOutput | StepResult,
): { output: StepOutput; sessionId?: string } {
  // A StepResult has no top-level `kind`; a StepOutput always does.
  if (ret != null && typeof ret === "object" && !("kind" in ret)) {
    const r = ret as StepResult;
    return { output: r.output, sessionId: r.sessionId };
  }
  return { output: ret as StepOutput, sessionId: undefined };
}

/**
 * The reviewer findings with `action:'fix_now'` from the immediately preceding
 * reviewer step, for delivery to the S5 coder_fix step (integ-cmr 256 r3,
 * fix_loop_context). `lastOutput` at an S5 dispatch is always the preceding
 * reviewer output (S3 for round 1, the prior S6 thereafter); a malformed /
 * non-reviewer output (which the runner/route guards would already have routed
 * to S8(error) before reaching here) yields `undefined` so the seam never
 * delivers garbage. Only fix_now findings are handed over — defer findings do
 * not drive a fix.
 */
function selectFixNowFindings(
  output: StepOutput | undefined,
): ReadonlyArray<Finding> | undefined {
  if (!isValidReviewerOutput(output)) return undefined;
  return output.findings.filter((f) => f.action === "fix_now");
}

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
  if (
    !lastIsTaggedError &&
    agentEntry?.output?.escalate != null &&
    isValidEscalation(agentEntry.output.escalate)
  ) {
    // Drop the prior terminal handoff (and any entries after the escalated
    // step): we are re-opening that step, so the prior boundary is superseded.
    // The slice is EXCLUSIVE of the escalated step itself — it is re-run via
    // resumeSession and gets a fresh in-memory entry, so keeping the old one
    // here would duplicate it.
    const escalatedIdx = ledger.lastIndexOf(agentEntry);
    return {
      resumeStep: agentEntry.step,
      resumeSessionId: agentEntry.sessionId,
      lastOutput: agentEntry.output,
      priorLedger: ledger.slice(0, escalatedIdx) as ReadonlyArray<LedgerEntry>,
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

/**
 * The fixed StepSpec for each agent step. Versioned promptFiles, never
 * assembled inline (ADR 0018 决定#4).
 *
 * #247 wired id/role/promptFile. #253 fills the contract:
 *   model           — short slug the runtime maps to a baked-in CLI
 *   completionSignal — signal the sandbox watches for (Sandcastle run() API)
 *   maxIter         — coder >1 (iterates), reviewer =1 (single pass)
 *   soul            — which soul to inject (coder / READ-ONLY)
 *   toolchain       — image tool-chain declaration
 *
 * maxIter SEMANTICS (lazy field in v0.1 — the runner does NOT enforce it):
 * it is the WITHIN-STEP agent (Ralph) retry budget for one `sandbox.run()`,
 * NOT a fix-loop give-up counter. Hitting it = that step ends normally and the
 * outer route() loop continues; it is NEVER the orchestrator giving up (that
 * only happens on a MODEL escalate signal — US#18/US#19, never by counting).
 * When #256 wires Sandcastle, maxIter must be implemented with this semantics
 * and must NOT become a "count-to-N-then-give-up" cap. See StepSpec.maxIter.
 *
 * Swapping models = change the `model` slug here; no image rebuild, no
 * structural StepSpec change (PRD #244 Implementation Decisions).
 *
 * S5/S6 are the fix-loop agent steps (route() wires S5→S6→S4→(S5|S7) in #254).
 * They carry the same full StepSpec contract as S2/S3: S5 mirrors the coder
 * spec (coder_fix prompt), S6 the reviewer (reviewer_rereview prompt, same
 * READ-ONLY soul + maxIter:1 single-pass full re-review as S3).
 */
const STEP_SPECS: Readonly<Record<"S2" | "S3" | "S5" | "S6", StepSpec>> = {
  S2: {
    id: "S2",
    role: "coder",
    promptFile: "coder_implement.md",
    model: "sonnet",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    soul: "coder",
    toolchain: IMAGE_TOOLCHAIN,
  },
  S3: {
    id: "S3",
    role: "reviewer",
    promptFile: "reviewer_full_review.md",
    model: "opus",
    completionSignal: "REVIEWER_STEP_COMPLETE",
    maxIter: 1,
    soul: "READ-ONLY",
    toolchain: IMAGE_TOOLCHAIN,
  },
  // S5/S6: the fix-loop agent steps. route() wires S5→S6→S4→(S5|S7) (#254).
  S5: {
    id: "S5",
    role: "coder",
    promptFile: "coder_fix.md",
    model: "sonnet",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    soul: "coder",
    toolchain: IMAGE_TOOLCHAIN,
  },
  S6: {
    id: "S6",
    role: "reviewer",
    promptFile: "reviewer_rereview.md",
    model: "opus",
    completionSignal: "REVIEWER_STEP_COMPLETE",
    maxIter: 1,
    soul: "READ-ONLY",
    toolchain: IMAGE_TOOLCHAIN,
  },
};

/**
 * Order-independent serialisation of a reviewer's findings, for the
 * no-progress signal (cmr S254).
 *
 * The raw `JSON.stringify(findings)` is fragile: it is sensitive to BOTH the
 * object key order within each Finding AND the array element order. The real
 * path (#256 parses LLM-emitted JSON) may legitimately reorder keys/elements
 * between rounds while the logical findings are unchanged — that would make
 * `findingsChanged` permanently true, so a genuinely stuck loop (0 commit +
 * same findings) would never accumulate to K and the stuck guard would be
 * bypassed (the very deadlock it exists to catch).
 *
 * Normalisation: project each Finding onto its fixed declared fields in a
 * canonical key order, stably sort the projected findings, then stringify. The
 * same logical set of findings serialises identically regardless of incoming
 * key/array order; a real content change (add/remove/edit a field) still
 * changes the string, so true progress is preserved.
 */
function normalizeFindingsKey(findings: ReadonlyArray<Finding>): string {
  // Project to the fixed Finding fields in a stable key order. This both
  // canonicalises key order and drops any stray keys, so the comparison
  // depends only on the contractual fields.
  const projected = findings.map((f) => ({
    action: f.action,
    category: f.category,
    claim_quote: f.claim_quote,
    location: f.location,
    severity: f.severity,
    suggested_fix: f.suggested_fix,
  }));
  // Stable sort by the projected fields so array element order does not matter.
  // Each element is already in canonical key order, so stringifying one element
  // yields a stable per-element key to sort on.
  projected.sort((a, b) =>
    JSON.stringify(a) < JSON.stringify(b) ? -1 : JSON.stringify(a) > JSON.stringify(b) ? 1 : 0,
  );
  return JSON.stringify(projected);
}

/**
 * The ACTIVE suffix of a persisted ledger — the entries that belong to the
 * still-live attempt, with any SUPERSEDED escalation attempt dropped
 * (integ-cmr m2 r5, cross-slice seam #255 × #254 × #251).
 *
 * The disk ledger is append-only (types.ts: writeLedger appends a JSONL record).
 * Escalate-resume re-opens the escalated step: planResume Case 2 truncates the
 * IN-MEMORY priorLedger to slice(0, escalatedIdx), but the DISK ledger keeps the
 * old escalated step entry AND its S8(escalate) — then the resumed continuation
 * APPENDS fresh entries after them. So after a double-resume
 * (escalate → answer-resume → crash → re-resume) the disk holds:
 *
 *   …S3(F), S4, S5, S6(escalate)(F), S8(escalate),   ← SUPERSEDED attempt
 *   S6(resumed)(F), S4, …                             ← ACTIVE suffix (reopened)
 *
 * A terminal S8 entry that is NOT the last record was superseded by exactly such
 * a reopen (a finished run is never continued — Case 3a/3b reports its status and
 * stops; only a re-opened escalation appends past its S8). So the boundary is the
 * LAST non-final S8: everything at-and-before it is the superseded prior attempt,
 * everything after it is the active suffix the live loop actually continued.
 *
 * Returning only the active suffix makes reconstructProgressState mirror the live
 * loop exactly: each escalate-resume starts a FRESH no-progress streak from the
 * resumed step (the human just answered — the loop is making progress, not stuck),
 * so the prior escalated attempt's reviewer outputs must NOT seed/score the streak.
 * Without this, the superseded attempt's repeated findings inflate noProgressStreak
 * and trip the K-consecutive stuck guard prematurely → a false S8(error) deadlock.
 *
 * A ledger with no non-final S8 (a normal crash-resume mid-run) is returned
 * unchanged — there is no superseded boundary to drop.
 */
function activeSuffix(
  ledger: ReadonlyArray<LedgerEntry>,
): ReadonlyArray<LedgerEntry> {
  // Find the LAST S8 entry that is not the final record. Any S8 followed by more
  // entries terminated a superseded attempt (only a re-opened escalation appends
  // past its own S8 handoff). The active suffix begins right after it.
  let boundary = -1;
  for (let i = 0; i < ledger.length - 1; i++) {
    if (ledger[i]!.step === "S8") boundary = i;
  }
  return boundary >= 0 ? ledger.slice(boundary + 1) : ledger;
}

/**
 * Reconstruct the no-progress guard state from a persisted ledger on resume
 * (integ-cmr m2 r1, Finding 3).
 *
 * The live loop maintains two pieces of state for the K-consecutive-no-progress
 * stuck contract (US#18/19): `prevFindingsKey` (the previous reviewer step's
 * normalised findings, the baseline the next S6 compares against) and
 * `noProgressStreak` (consecutive S6 rounds whose findings did not change). On a
 * crash/escalate-resume mid-fix-loop these were NOT reconstructed, so the first
 * S6 after resume scored a free "progress" pass and erased the prior streak — a
 * genuinely-stuck loop could evade the contract indefinitely across resume
 * boundaries. This folds the same findings-change signal over the persisted
 * reviewer outputs to rebuild both, so the contract holds through resume.
 *
 * The baseline is the S3 full review (round-0); each subsequent S6 re-review is
 * compared against the running `prevFindingsKey`, mirroring the live loop's
 * sequencing exactly (seed at S3, advance + score at each S6). Reviewer entries
 * are read IN ORDER; the first reviewer output seeds the baseline (no streak
 * change), and each later one scores progress/no-progress against it.
 *
 * integ-cmr m2 r5 (cross-slice seam #255 × #254 × #251): the fold runs over the
 * ACTIVE suffix only, NOT the full append-only disk ledger. A reopened escalation
 * leaves its superseded attempt's reviewer outputs on disk (append-only); folding
 * over them would count the prior attempt's repeated findings as no-progress rounds
 * of the live loop and inflate the streak past K → a false stuck S8(error). The
 * live loop's streak resets at each escalate-resume (the resumed step is fresh
 * progress), so reconstruction must score only the active suffix after the last
 * superseded escalation boundary — see activeSuffix().
 */
function reconstructProgressState(
  ledger: ReadonlyArray<LedgerEntry>,
): { prevFindingsKey: string | undefined; noProgressStreak: number } {
  let prevFindingsKey: string | undefined;
  let noProgressStreak = 0;
  let seenBaseline = false;

  for (const e of activeSuffix(ledger)) {
    const out = e.output;
    // integ-cmr m2 r4 (self-check, same class as the defer-rebuild hole): use
    // isValidReviewerOutput, NOT a bare `kind === "reviewer"` check. The persisted
    // ledger is untyped on disk, so a malformed reviewer entry (missing or
    // non-array findings) would pass the discriminant and make normalizeFindingsKey
    // call `.map(...)` on a non-array → raw TypeError, rejecting the resume. The
    // live loop only ever SCORES validated reviewer outputs (a malformed one bails
    // to S8 and never reaches the no-progress bookkeeping), so faithfully skipping
    // malformed reviewer entries here mirrors the live loop exactly.
    if (!isValidReviewerOutput(out)) continue;
    const key = normalizeFindingsKey(out.findings);
    if (!seenBaseline) {
      // First reviewer output (the S3 round-0 baseline): seed only, no scoring —
      // matches the live loop, which seeds prevFindingsKey from S3 and scores
      // progress only at S6.
      prevFindingsKey = key;
      seenBaseline = true;
      continue;
    }
    // A re-review round (S6): score progress against the running baseline.
    const madeProgress = key !== prevFindingsKey;
    noProgressStreak = madeProgress ? 0 : noProgressStreak + 1;
    prevFindingsKey = key;
  }

  return { prevFindingsKey, noProgressStreak };
}

/**
 * Synthesise a human-readable reason string for route()-detected error edges
 * (e.g. 0-commit). Backend-throw errors use the caught message directly.
 */
function buildErrorReason(step: StepId, output: StepOutput | undefined): string {
  if (step === "S2" && output?.kind === "coder" && !output.committed) {
    return "coder produced no commits (committed:false) — nothing to review";
  }
  if (step === "S5" && output?.kind === "coder" && !output.committed) {
    return "fix step produced no commits (committed:false) — unable to proceed";
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

export async function runOrchestrator(input: RunInput): Promise<RunResult> {
  const { issueNumber, backend } = input;
  const ledger: LedgerEntry[] = [];

  // State threaded across steps within this run.
  let worktree: WorktreeHandle | undefined;
  let lastOutput: StepOutput | undefined;
  // Collected at S4: reviewer findings with action:'defer' (PRD #244 US#25).
  // Surfaced in RunResult.deferredFindings so the caller can act on them.
  let deferredFindings: Finding[] = [];

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
  ): Promise<void> {
    try {
      await emitLedger(s, output, promptFile, handoffStatus);
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
    // step — re-entering the fix loop or reporting a spurious success). The
    // in-memory entry stays untagged, matching the normal handoff path (only the
    // disk ledger is the resume truth; the in-memory ledger is the live result).
    ledger.push({ step: "S8" });
    await persistBestEffort("S8", undefined, undefined, "error");

    // An error abort surfaces whatever defers were collected before the fault
    // (empty if S4 never ran).
    return {
      status: "error",
      errorPackage,
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

  // ── No-progress stuck guard (cmr S254, US#18) ──────────────────────────────
  // The runner must NEVER stop because a round counter hit a number — US#18:
  // "我不想它因为数到某个轮数就停，这样它不会还在进展时就放弃" — and the PRD
  // defers any round-cap (轮数上限策略 deferred). So this is NOT a round/step
  // cap: it is a *no-progress* detector that fires only when the fix loop is
  // genuinely stuck (a route bug or a fix that changes nothing the reviewer
  // sees). As long as the loop makes progress every round, it runs unbounded —
  // a converging review of 20, 50, 100+ rounds is never truncated.
  //
  // A "fix round" = one S5(fix)→S6(re-review) pass. PROGRESS in a round means
  // the S6 reviewer findings changed vs the previous round's findings. (The
  // original #254 progress signal also OR-ed in "the S5 step added a new commit
  // (commitsAdded > 0)"; that leg is degenerate under base rule B — every
  // committed fix reaching S6 has commitsAdded ≥ 1, and a 0-commit fix already
  // bails at the S5 0-commit error edge — so it is dropped here. Full rationale
  // at the guard block below.)
  // Progress resets the streak; only K *consecutive* no-progress rounds bail.
  // K is a small constant (a stuck loop dies fast — this逮 real deadlock/route
  // bugs, not "many rounds"). On bail: a clean S8(status=error) + errorPackage
  // (reason names the stuck guard) — never an uncaught throw / promise reject.
  const NO_PROGRESS_LIMIT = 3;
  let noProgressStreak = 0;
  // Normalised key of the PREVIOUS reviewer step's findings — the baseline the
  // next S6 re-review compares against. SEEDED from the S3 full review (the
  // round-0 baseline) so the FIRST S6 round is a genuine comparison, not a free
  // "progress" pass (off-by-one fix, cmr S254): without seeding, the first S6
  // would compare against `undefined` and always score progress, slipping the
  // bail to K+1 rounds. It is then maintained at each S6 inside the no-progress
  // block. Stays undefined only if no reviewer step has run yet.
  let prevFindingsKey: string | undefined;

  // ── #255: idempotent resume from the recorded breakpoint ───────────────────
  // When set, the next dispatch of `resumeFor.step` must use the original agent
  // session (Sandcastle `resumeSession`) rather than a fresh `run()`. Used for
  // the escalate-resume case (the human answered; the coder finishes in-session).
  // Cleared after the step is dispatched once.
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

    // Re-derive the defer list from the prior reviewer output, if any, so a
    // resume that lands after S4 still surfaces the deferred findings (US#25).
    //
    // integ-cmr m2 r4 (cross-slice seam #255 × defer-rebuild): a bare
    // `kind === "reviewer"` discriminant check is NOT enough — the persisted
    // ledger is untyped on disk, so a malformed S6/S3 reviewer entry
    // (`{kind:'reviewer'}` with NO findings, or `findings` non-array) passes the
    // discriminant yet `.findings.filter(...)` throws a raw TypeError. That
    // TypeError escaped HERE, before the try/catch around cleanResidue (below)
    // and before any route(), so runOrchestrator REJECTED instead of returning
    // S8(error) — bypassing the "malformed step output → S8(error)" decision and
    // the US#30 error package. The resume path drives off the recorded
    // lastOutput and runs BEFORE the live path's pre-route isValidStepOutput
    // guard, so it must validate the shape itself. Gate on isValidReviewerOutput:
    //   • valid reviewer → rebuild the defer list as before;
    //   • malformed reviewer-kind → contract violation → S8(error) (via
    //     errorTermination, tagged + best-effort persisted, NEVER a raw reject),
    //     mirroring route()'s S2/S5 isValidCoderOutput edges and the new S3/S6
    //     isValidReviewerOutput edges. The defer list is NOT rebuilt from garbage.
    //   • non-reviewer (coder/undefined) → leave the defer list untouched.
    if (plan.lastOutput?.kind === "reviewer") {
      if (!isValidReviewerOutput(plan.lastOutput)) {
        return await errorTermination(
          lastAgentStep(plan.priorLedger) ?? "S6",
          new Error(
            "resume: recorded reviewer output is malformed (missing or " +
              "non-array findings) — cannot rebuild the defer list; a " +
              "malformed step output terminates as S8(error)",
          ),
        );
      }
      deferredFindings = plan.lastOutput.findings
        .filter((f) => f.action === "defer")
        .slice();
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

    // ── Reconstruct the no-progress guard state (integ-cmr m2 r1, Finding 3) ──
    // The fix-loop stuck contract (US#18/19) lives in prevFindingsKey +
    // noProgressStreak, maintained at each S6. A crash/escalate-resume mid-loop
    // must NOT start with a clean streak: that would grant the first S6 after
    // resume a free "progress" pass and erase the prior streak, letting a
    // genuinely-stuck loop evade the K-consecutive contract across the resume
    // boundary. Fold the same findings-change signal over the persisted reviewer
    // outputs to rebuild both pieces of state.
    const resumed = reconstructProgressState(plan.priorLedger);
    prevFindingsKey = resumed.prevFindingsKey;
    noProgressStreak = resumed.noProgressStreak;

    // If the persisted history is ALREADY at K consecutive no-progress rounds,
    // the prior run was stuck at the contract limit before it crashed — do not
    // continue it. Bail immediately to S8(status=error), mirroring the in-loop
    // no-progress bail (tagged + best-effort persisted, never a raw reject).
    if (noProgressStreak >= NO_PROGRESS_LIMIT) {
      ledger.push({ step: "S8" });
      await persistBestEffort("S8", undefined, undefined, "error");
      const errorPackage: ErrorPackage = {
        failedStep: "S6",
        reason:
          `fix loop stuck: ${NO_PROGRESS_LIMIT} consecutive rounds with no ` +
          `progress (unchanged reviewer findings) in the resumed history. The ` +
          `fix loop is not converging — likely a route bug or a fix that ` +
          `changes nothing the reviewer sees; a human is needed.`,
        branchHead: worktree.branch,
      };
      return {
        status: "error",
        errorPackage,
        stepLedger: ledger,
        deferredFindings,
      };
    }

    // Continue from the recorded breakpoint.
    step = plan.resumeStep;
    if (plan.resumeSessionId !== undefined) {
      resumeFor = { step: plan.resumeStep, sessionId: plan.resumeSessionId };
    }
  }

  // The step machine has no fixed bound: route() always terminates the run via
  // a handoff (success/escalate/error), and the no-progress guard above breaks
  // any genuine stuck loop. A `while (true)` makes the absence of a round cap
  // explicit (US#18) — there is no "数到 N 就停" anywhere.
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
        // #252), then enforce the four-way accept condition (ADR 0018 / #248):
        //   (a) ready-for-agent label
        //   (b) has ## Agent Brief comment
        //   (c) no sub-issues (leaf slice, not a parent/epic)
        //   (d) all blocked_by dependencies are closed
        // A gate violation throws immediately — the runner stops here, no
        // worktree is prepared, no agent step is dispatched. Gate throws are
        // intentionally NOT converted to an error handoff (they are a caller
        // input fault, not a pipeline error); only the backend fetch is.
        let meta: IssueMeta;
        try {
          meta = await backend.fetchIssueMeta(issueNumber);
        } catch (err) {
          // No worktree yet → no sibling stateDir → cannot persist (inherent:
          // the resume contract needs a worktree's sibling dir). errorTermination
          // records the in-memory S8 and persists only if stateDir is resolved.
          return await errorTermination("S0", err);
        }

        if (!meta.isReadyForAgent) {
          throw new Error(
            `S0 input gate: issue #${issueNumber} is not labelled ready-for-agent. ` +
              `Triage the issue and apply the label before running the orchestrator.`,
          );
        }

        if (!meta.hasAgentBrief) {
          throw new Error(
            `S0 input gate: issue #${issueNumber} has no "## Agent Brief" section. ` +
              `Add an Agent Brief (the authoritative implementation contract) before running.`,
          );
        }

        if (meta.hasSubIssues) {
          throw new Error(
            `S0 input gate: issue #${issueNumber} is a parent issue (it has sub-issues). ` +
              `Feed a leaf slice issue, not a parent/epic.`,
          );
        }

        if (meta.openBlockedBy.length > 0) {
          const blockers = meta.openBlockedBy.map((n) => `#${n}`).join(", ");
          throw new Error(
            `S0 input gate: issue #${issueNumber} is blocked by upstream issues that are still open: ${blockers}. ` +
              `Merge the upstream changes before running.`,
          );
        }

        break;
      }

      case "S1": {
        // S1 load_context — runner action: full snapshot → resident worktree
        // (base=main) → write snapshot in (clean-room).
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
          worktree = await backend.prepareWorktree(issueNumber, SLICE_BASE);
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
        // Agent step — one sandbox.run() driven by its fixed StepSpec.
        // S5/S6 are the fix-loop steps; route() drives S5→S6→S4→(S5|S7) (#254).
        if (worktree === undefined) {
          // Programming error: the runner sequenced wrong.
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
        promptFile = STEP_SPECS[step].promptFile;
        // #255 escalate-resume: if this step is the one we are resuming in its
        // original agent session (the human answered an escalation), dispatch
        // via Sandcastle-native resumeSession carrying the recorded sessionId —
        // SAME machine as crash-resume, but continuing the existing session
        // rather than a fresh run(). Crash-resume's NEXT step is brand-new work
        // → normal runStep. resumeFor is consumed once, then cleared.
        try {
          // #256: normalise the seam return (StepOutput | StepResult). The real
          // Backend yields a StepResult carrying the real per-step sandbox
          // session id; a fake yields a bare StepOutput (sessionId undefined).
          let ret: StepOutput | StepResult;
          // integ-cmr 256 r3 (fix_loop_context): the S5 coder_fix step must
          // RECEIVE the round's reviewer fix_now findings so the coder knows what
          // to fix (US#13). The findings live in lastOutput — the immediately
          // preceding reviewer step (S3 for round 1, the prior S6 thereafter). We
          // hand ONLY the fix_now subset (defer findings do not drive a fix) to
          // the S5 dispatch; every other step gets undefined (unchanged seam).
          const fixNowFindings =
            step === "S5" ? selectFixNowFindings(lastOutput) : undefined;
          if (resumeFor !== undefined && resumeFor.step === step) {
            const sid = resumeFor.sessionId;
            resumeFor = undefined;
            ret = await backend.resumeSession(
              STEP_SPECS[step],
              worktree,
              sid,
              fixNowFindings,
            );
          } else {
            ret = await backend.runStep(
              STEP_SPECS[step],
              worktree,
              fixNowFindings,
            );
          }
          const normalized = normalizeStepResult(ret);
          output = normalized.output;
          stepSessionId = normalized.sessionId;
        } catch (err) {
          return await errorTermination(step, err);
        }
        // ── escalate precedence (integ-cmr base r1, F2) ───────────────────
        // escalate is the GLOBAL stop edge (ADR 0018 / PRD route table:
        // "checked FIRST, any agent step can carry it"). A step can get stuck
        // mid-work and emit a VALID escalate while its happy-path schema is
        // incomplete (coder missing committed, reviewer missing findings). The
        // full role-schema check (isValidStepOutput) below would judge that
        // false → S8(error) and SWALLOW the escalate diagnosis. So if the output
        // carries a VALID escalate, hand it straight to route() (which takes the
        // escalate edge) WITHOUT demanding the rest of the happy-path schema.
        // A NON-NULL but MALFORMED escalate is itself a contract violation —
        // route()'s escalate edge maps it to S8(error) (F1); we let it through
        // to route() unchanged (do NOT also fail it on the role schema, so the
        // error is attributed to the escalate edge, the real fault).
        const expectedKind =
          STEP_SPECS[step].role === "coder" ? "coder" : "reviewer";
        const carriesEscalate = output != null && output.escalate != null;
        if (!carriesEscalate) {
          // #5 + integ-cmr base r2 (A, B): only when there is NO escalate does
          // the output have to satisfy the full role contract — not just kind.
          // A coder step must yield a CONSISTENT {committed, commitsAdded}
          // (B: committed=true⇒≥1, false⇒0, non-negative integer); a reviewer
          // step must yield findings whose every ELEMENT is valid (A: exact
          // severity/action enums + required string fields). A wrong-kind /
          // undefined / garbage output, an inconsistent commitsAdded, or any
          // malformed finding element is a contract violation — NEVER pass it
          // silently to route() where it could bypass the P0/P1 fix gate (e.g.
          // a "critical " severity slips the exact-string test → push). Report
          // S8(error) instead. Runner and route() share one guard (validate.ts).
          if (!isValidStepOutput(output, expectedKind)) {
            return await errorTermination(
              step,
              new Error(
                `${step}: step output does not match the ${STEP_SPECS[step].role} ` +
                  `contract (expected kind:'${expectedKind}'). Got: ` +
                  `${describeOutput(output)}. Refusing to route a malformed output ` +
                  `(would risk bypassing the P0/P1 fix gate).`,
              ),
            );
          }
          // ── No-progress signal capture (cmr S254) ──────────────────────────
          // Only a NON-escalate output that PASSED isValidStepOutput reaches
          // here, so commitsAdded (coder) / findings (reviewer) are guaranteed
          // present and well-shaped. A valid-escalate output skips this block
          // (route() takes the escalate edge before the no-progress check ever
          // runs) — and would otherwise crash here on its missing happy-path
          // fields (e.g. an S3 escalate has no findings → normalizeFindingsKey
          // of undefined). So the seed is scoped to the validated path.
          //
          // Seed the no-progress baseline from the S3 full review (off-by-one
          // fix, cmr S254): the first S6 re-review compares against the S3
          // findings, so a first-round repeat of the same finding is correctly
          // scored as no-progress (not a free pass). Only S3 seeds; S6 maintains
          // the key inside the no-progress block below to avoid a double-update.
          // (The commit count is no longer captured here: under base rule B the
          // commit-leg of the no-progress signal is degenerate — see the guard
          // block below — so progress is findings-change only.)
          if (step === "S3" && output.kind === "reviewer") {
            prevFindingsKey = normalizeFindingsKey(output.findings);
          }
        } else if (!isValidEscalation(output.escalate)) {
          // Carries a non-null but malformed escalate: do not run the role
          // schema (so attribution lands on the escalate edge). route() will
          // map it to S8(error) (F1). Still record it as the in-flight output.
          lastOutput = output;
          break;
        }
        lastOutput = output;
        break;
      }

      case "S4": {
        // S4 route_findings — pure TS, no agent. Collect defer findings here
        // so they can be surfaced in RunResult.deferredFindings (PRD #244 US#25).
        // route() (below) consumes the reviewer output to decide S5 vs S7.
        if (lastOutput?.kind === "reviewer") {
          deferredFindings = lastOutput.findings
            .filter((f) => f.action === "defer")
            .slice(); // defensive copy
        }
        break;
      }

      case "S7": {
        // S7 push — runner action: push the resident slice branch. No PR, no
        // merge (the Backend exposes neither).
        if (worktree === undefined) {
          throw new Error("runner: S7 push reached before worktree prepared");
        }
        try {
          await backend.push(worktree);
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
    const decision = route({ from: step, output: lastOutput });

    // ── No-progress stuck guard (cmr S254, US#18) ────────────────────────────
    // A fix round completes when the S6 re-review finishes. Evaluate progress
    // ONLY when route() would continue the loop (decision.kind === "next"); if
    // route() already hands off (escalate / S5-0-commit error / success) that
    // takes precedence — a stuck bail never pre-empts a legitimate handoff.
    //
    // PROGRESS = the S6 re-review findings CHANGED vs the previous round.
    //
    // Integ reconcile (#254 ⋈ base rule B): the original #254 guard also OR-ed
    // in "this round's S5 added a new commit (commitsAdded > 0)". Under base's
    // commitsAdded contract (validate.ts rule B: committed:true ⟺ commitsAdded
    // ≥ 1, committed:false ⟺ 0) that leg is degenerate: any committed fix that
    // reaches S6 has commitsAdded ≥ 1 (always "progress"), and a 0-commit fix is
    // committed:false → route()'s S5 edge already bails it to S8(error) BEFORE
    // this guard runs. So the commit-leg is permanently true for every fix that
    // reaches here — keeping it would mask the one stuck shape this guard exists
    // to catch: the coder commits a real new commit every round but the reviewer
    // raises the SAME findings forever (the fix never moves the review). That is
    // genuine non-convergence (US#19: "在打磨次要的 / findings 不动"), so the
    // contract-faithful signal is findings-change alone. (#254's "0 commit +
    // same findings" stuck case is subsumed: under rule B it is committed:false
    // → S5 0-commit error edge, a louder + earlier bail.) No round counting
    // anywhere (US#18): progress resets the streak, so a converging review of
    // any length runs on; only K CONSECUTIVE no-progress rounds bail.
    if (step === "S6" && decision.kind === "next") {
      // Normalised so that a reorder of keys/elements between rounds (which the
      // real LLM-JSON path can emit) is NOT mistaken for a findings change
      // (cmr S254). prevFindingsKey was seeded from the S3 review, so on the
      // first S6 this is a real comparison against the round-0 baseline, not a
      // free "progress" pass (off-by-one fix).
      const findingsKey =
        lastOutput?.kind === "reviewer"
          ? normalizeFindingsKey(lastOutput.findings)
          : "";
      const madeProgress =
        prevFindingsKey === undefined || findingsKey !== prevFindingsKey;
      prevFindingsKey = findingsKey;

      noProgressStreak = madeProgress ? 0 : noProgressStreak + 1;

      if (noProgressStreak >= NO_PROGRESS_LIMIT) {
        // Stuck: K consecutive rounds whose reviewer findings did not change —
        // the fix loop is not converging (a real deadlock / route bug / a fix
        // that changes nothing the reviewer sees), not "too many rounds". Bail
        // cleanly to S8(status=error); never throw / reject. Surface the defers
        // collected so far, consistent with the other in-loop error handoffs.
        //
        // integ-cmr m2 r1 (Findings 1 & 4): persist via persistBestEffort with
        // handoffStatus:'error', mirroring errorTermination. Two merge-seam bugs
        // fixed at once:
        //   - Finding 1: the old emitLedger('S8', undefined, undefined) wrote the
        //     terminal S8 UNTAGGED, so a re-feed routed S6→S4 and RE-ENTERED the
        //     fix loop instead of reporting the stuck error. Tagging it 'error'
        //     makes planResume Case 3a report the true terminal status.
        //   - Finding 4: the old emitLedger here was UNGUARDED (unlike the normal
        //     handoff path's try/catch). A writeLedger throw on this S8 persist
        //     raw-rejected out of runOrchestrator, violating the #252 invariant
        //     "any backend call throwing → S8(error) + error package".
        //     persistBestEffort swallows the write fault so we still return the
        //     original stuck S8(error) package rather than rejecting.
        ledger.push({ step: "S8" });
        await persistBestEffort("S8", undefined, undefined, "error");
        const errorPackage: ErrorPackage = {
          failedStep: "S6",
          reason:
            `fix loop stuck: ${NO_PROGRESS_LIMIT} consecutive rounds with no ` +
            `progress (unchanged reviewer findings). The fix loop is not ` +
            `converging — likely a route bug or a fix that changes nothing the ` +
            `reviewer sees; a human is needed.`,
          branchHead: worktree?.branch,
        };
        return {
          status: "error",
          errorPackage,
          stepLedger: ledger,
          deferredFindings,
        };
      }
    }

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
