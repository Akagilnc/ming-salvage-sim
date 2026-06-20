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
 *   (new commit OR changed findings each round) and bails cleanly to
 *   S8(status=error) only after K consecutive no-progress rounds.
 */

import { route } from "./route.js";
import type {
  ErrorPackage,
  Finding,
  IssueMeta,
  IssueSnapshot,
  LedgerEntry,
  PersistentLedgerEntry,
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
}): PersistentLedgerEntry {
  const entry: PersistentLedgerEntry = {
    step: opts.step,
    sessionId: opts.sessionId,
    prompt_hash: opts.prompt_hash,
    branchHEAD: opts.branchHEAD,
    ts: opts.ts,
  };
  // Only add output if defined — keeps the runner-action shape clean.
  if (opts.output !== undefined) {
    return { ...entry, output: opts.output };
  }
  return entry;
}

/** v0.1 base for a single slice: always main (ADR 0017 §2). */
const SLICE_BASE = "main";

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
  // commitsAdded reported by the most recent S5 fix step — half of the
  // no-progress signal evaluated when the matching S6 re-review completes.
  let lastFixCommits = 0;

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
  ): Promise<void> {
    const ph = await hashPrompt(promptFile, s);
    const entry = buildPersistentEntry({
      step: s,
      output,
      sessionId,
      prompt_hash: ph,
      branchHEAD: worktree?.branch ?? "",
      ts: new Date().toISOString(),
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
  // A "fix round" = one S5(fix)→S6(re-review) pass. PROGRESS in a round means:
  //   • the S5 coder step added a new commit (commitsAdded > 0), OR
  //   • the S6 reviewer findings changed vs the previous round's findings.
  // Progress resets the streak; only K *consecutive* no-progress rounds bail.
  // K is a small constant (a stuck loop dies fast — this逮 real deadlock/route
  // bugs, not "many rounds"). On bail: a clean S8(status=error) + errorPackage
  // (reason names the stuck guard) — never an uncaught throw / promise reject.
  const NO_PROGRESS_LIMIT = 3;
  let noProgressStreak = 0;
  // Findings of the previous fix round's re-review, serialised for comparison.
  // undefined until the first re-review (S6) completes.
  let prevFindingsKey: string | undefined;

  // The step machine has no fixed bound: route() always terminates the run via
  // a handoff (success/escalate/error), and the no-progress guard above breaks
  // any genuine stuck loop. A `while (true)` makes the absence of a round cap
  // explicit (US#18) — there is no "数到 N 就停" anywhere.
  for (;;) {
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
        // S5/S6 are the fix-loop steps; route() drives S5→S6→S4→(S5|S7) (#254).
        if (worktree === undefined) {
          // Programming error: the runner sequenced wrong.
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
        promptFile = STEP_SPECS[step].promptFile;
        try {
          output = await backend.runStep(STEP_SPECS[step], worktree);
        } catch (err) {
          return errorHandoff(step, err, ledger, worktree);
        }
        lastOutput = output;
        // Capture the fix step's commit count: it is one half of the
        // no-progress signal, paired with the S6 re-review findings below.
        if (step === "S5" && output.kind === "coder") {
          lastFixCommits = output.commitsAdded;
        }
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

    // ── No-progress stuck guard (cmr S254, US#18) ────────────────────────────
    // A fix round completes when the S6 re-review finishes. Evaluate progress
    // ONLY when route() would continue the loop (decision.kind === "next"); if
    // route() already hands off (escalate / S5-0-commit error / success) that
    // takes precedence — a stuck bail never pre-empts a legitimate handoff.
    // Progress = this round's S5 added a commit (lastFixCommits > 0) OR the S6
    // findings changed vs the previous round. No counting of rounds anywhere:
    // progress resets the streak, so a converging review of any length runs on.
    if (step === "S6" && decision.kind === "next") {
      const findingsKey =
        lastOutput?.kind === "reviewer"
          ? JSON.stringify(lastOutput.findings)
          : "";
      const findingsChanged =
        prevFindingsKey === undefined || findingsKey !== prevFindingsKey;
      const madeProgress = lastFixCommits > 0 || findingsChanged;
      prevFindingsKey = findingsKey;

      noProgressStreak = madeProgress ? 0 : noProgressStreak + 1;

      if (noProgressStreak >= NO_PROGRESS_LIMIT) {
        // Stuck: K consecutive rounds with no new commit AND no findings change
        // — a real deadlock / route bug, not "too many rounds". Bail cleanly to
        // S8(status=error); never throw / reject. Surface the defers collected
        // so far, consistent with the other in-loop error handoffs.
        ledger.push({ step: "S8" });
        await emitLedger("S8", undefined, undefined);
        const errorPackage: ErrorPackage = {
          failedStep: "S6",
          reason:
            `fix loop stuck: ${NO_PROGRESS_LIMIT} consecutive rounds with no ` +
            `progress (no new commit and unchanged reviewer findings). The fix ` +
            `loop is not converging — likely a route bug or a fix that changes ` +
            `nothing the reviewer sees; a human is needed.`,
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
      await emitLedger("S8", undefined, undefined);

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
