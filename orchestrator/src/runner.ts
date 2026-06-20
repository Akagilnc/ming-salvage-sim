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
 * Slice #250: S4 severity+action fan-out; S5/S6 step bodies stubbed so the
 *   fan-out is exercisable end-to-end (fix-loop back-edge remains #254).
 * Slice #251: global escalate stop edge (in route()).
 * Slice #252: error edges —
 *   - S2 committed:false → S8(error)  [route() detects]
 *   - S7 push() throws  → S8(error)   [runner catch]
 *   - any backend call throws → S8(error) + error package  [runner catch]
 *   - any agent output carries escalate → S8(escalate) [route() detects]
 * Slice #253: StepSpec contract — model/completionSignal/maxIter/soul/toolchain.
 * Slice #248: S0 input gate — four-way accept condition (rfa ∧ Agent Brief ∧
 *   no sub-issues ∧ blocked_by all closed); violations throw, stopping at S0.
 *
 * Remaining seam: #254 (fix-loop back-edge) layers onto these.
 */

import { route } from "./route.js";
import type {
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
  StepSpec,
  WorktreeHandle,
} from "./types.js";

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

/**
 * Stable SHA-256 hash for the ledger's `prompt_hash` field.
 *
 * TODO(#256): v0.1 placeholder — hashes the promptFile *name* (not its
 * content).  Real anti-tampering requires hashing the resolved file content;
 * wire in #256 when the real Backend reads the prompt file.
 * For runner-action steps (no promptFile): hash of the step id string.
 *
 * Uses the Web Crypto API (globalThis.crypto) available in Node ≥ 18 / ES2022,
 * so no `@types/node` dependency is needed.
 */
async function hashPrompt(
  promptFile: string | undefined,
  stepId: StepId,
): Promise<string> {
  const input = promptFile ?? stepId;
  const encoded = new TextEncoder().encode(input);
  const buffer = await globalThis.crypto.subtle.digest("SHA-256", encoded);
  return Array.from(new Uint8Array(buffer))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Build a PersistentLedgerEntry from the in-flight step context.
 *
 * TODO(#256): `sessionId` is a run-level UUID placeholder (shared across all
 * steps); the real per-step sandbox session id is wired in #256.
 * TODO(#256): `branchHEAD` stores the branch name placeholder; the real git
 * commit SHA (git rev-parse HEAD) is wired in #256.
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

  // Case 2: escalate residue — the last agent output carries an escalation.
  // The human has answered; resume THAT step in its original agent session.
  // Checked before the terminal-handoff case so a trailing S8(escalate) entry
  // does not short-circuit into "report escalate again".
  if (agentEntry?.output?.escalate != null) {
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
 * Swapping models = change the `model` slug here; no image rebuild, no
 * structural StepSpec change (PRD #244 Implementation Decisions).
 *
 * S5/S6 added in #250 (fix-loop stubs so the S4 fan-out is exercisable
 * end-to-end; the real S5→S6→S4 loop control is #254). They carry the same
 * full StepSpec contract as S2/S3: S5 mirrors the coder spec, S6 the reviewer.
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
  // S5/S6: fix-loop stubs so S4 fan-out can be tested end-to-end (#250).
  // The fix-loop back-edge S5→S6→S4 is wired by #254 — not here.
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

/** Build an S8(error) handoff from the failing step and caught error. */
function errorHandoff(
  failedStep: StepId,
  err: unknown,
  ledger: LedgerEntry[],
  worktree: WorktreeHandle | undefined,
): RunResult {
  const reason =
    err instanceof Error ? err.message : String(err);
  const errorPackage: ErrorPackage = {
    failedStep,
    reason,
    branchHead: worktree?.branch,
  };
  ledger.push({ step: "S8" });
  // An error abort surfaces no defer list (S4 defer collection never completed);
  // deferredFindings is required on RunResult (#250), so return it empty here.
  return { status: "error", errorPackage, stepLedger: ledger, deferredFindings: [] };
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
  const sessionId = globalThis.crypto.randomUUID();

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
  ): Promise<void> {
    const ph = await hashPrompt(promptFile, s);
    const entry = buildPersistentEntry({
      step: s,
      output,
      sessionId,
      prompt_hash: ph,
      branchHEAD: worktree?.branch ?? "",
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
  // here becomes an error handoff (consistent with #252).
  let resumeState: ResumeState | undefined;
  try {
    resumeState = await backend.findResumeState(issueNumber);
  } catch (err) {
    return errorHandoff("S0", err, ledger, worktree);
  }

  // The runner drives the sequence; the agent never picks the next step.
  let step: StepId = "S0";

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
    if (plan.lastOutput?.kind === "reviewer") {
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
    // `clean -fd` cannot touch the resume truth.
    try {
      await backend.cleanResidue(worktree);
    } catch (err) {
      return errorHandoff(plan.resumeStep, err, ledger, worktree);
    }

    // Continue from the recorded breakpoint.
    step = plan.resumeStep;
    if (plan.resumeSessionId !== undefined) {
      resumeFor = { step: plan.resumeStep, sessionId: plan.resumeSessionId };
    }
  }

  // Defensive runaway guard against a route() bug spinning the step machine
  // forever (happy path visits 7 steps; the cap is generous). This is NOT the
  // convergence safety-valve / round-cap — that is findings-driven and
  // deferred (PRD #244 G2, US#18/19). Do not repurpose it for fix-loop limits.
  const MAX_STEPS = 32;

  for (let i = 0; i < MAX_STEPS; i++) {
    let output: StepOutput | undefined;
    // promptFile for the current step (agent steps only; undefined for runner actions).
    let promptFile: string | undefined;

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
          return errorHandoff("S0", err, ledger, worktree);
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
        let snapshot: IssueSnapshot;
        try {
          snapshot = await backend.fetchIssueSnapshot(issueNumber);
        } catch (err) {
          return errorHandoff("S1", err, ledger, worktree);
        }
        try {
          worktree = await backend.prepareWorktree(issueNumber, SLICE_BASE);
        } catch (err) {
          return errorHandoff("S1", err, ledger, worktree);
        }
        try {
          await backend.writeSnapshot(worktree, snapshot);
        } catch (err) {
          return errorHandoff("S1", err, ledger, worktree);
        }
        // Now that the worktree is prepared, fix the stateDir to be a true
        // sibling of the worktree root (#249), so ledger writes land outside
        // the worktree where `git clean -fd` cannot remove them.
        stateDir = deriveStateDir(worktree.path, issueNumber);
        break;
      }

      case "S2":
      case "S3":
      case "S5":
      case "S6": {
        // Agent step — one sandbox.run() driven by its fixed StepSpec.
        // S5/S6 are fix-loop stubs added in #250; full loop control is #254.
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
          if (resumeFor !== undefined && resumeFor.step === step) {
            const sid = resumeFor.sessionId;
            resumeFor = undefined;
            output = await backend.resumeSession(
              STEP_SPECS[step],
              worktree,
              sid,
            );
          } else {
            output = await backend.runStep(STEP_SPECS[step], worktree);
          }
        } catch (err) {
          return errorHandoff(step, err, ledger, worktree);
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
          ledger.push({ step: "S7" });
          return errorHandoff("S7", err, ledger, worktree);
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
    await emitLedger(step, output, promptFile);

    // The runner — not the agent — decides the next step.
    const decision = route({ from: step, output: lastOutput });

    if (decision.kind === "handoff") {
      ledger.push({ step: "S8" });
      // #249: persist the S8 handoff entry too.
      // #255: tag it with the terminal status so a resuming run can tell a
      // prior success / escalate / error apart (the S8 entry is otherwise
      // identical for all three).
      await emitLedger("S8", undefined, undefined, decision.status);

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

  throw new Error(
    `runner: exceeded ${MAX_STEPS} steps without reaching handoff (routing bug)`,
  );
}
