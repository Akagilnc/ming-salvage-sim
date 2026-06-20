/**
 * runOrchestrator — the runner loop (ADR 0018).
 *
 * The runner drives the fixed S0–S8 sequence itself: it performs each
 * runner-action step or dispatches each agent step, writes a step-ledger
 * entry, then calls route() to pick the next step. The agent never decides
 * the next step — route() does.
 *
 * Slice #247 = the thinnest happy path:
 *   S0 input_gate (fake = compliant) → S1 load_context → S2 coder_implement
 *   → S3 reviewer_full_review → S4 route_findings (no findings = approve)
 *   → S7 push → S8 handoff(status=success).
 *
 * Slice #249 adds persisted step ledger: every step is written via
 * backend.writeLedger() to the sibling state dir (outside the worktree).
 *
 * No fix loop (#254), no escalate stop (#251), no error edges (#252), no full
 * severity routing (#250), no soul injection (#253). Those layer onto these
 * seams without reshaping them.
 */

import { route } from "./route.js";
import type {
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
  // Find the parent by stripping everything at and after the last separator.
  // Using a simple string split keeps this dependency-free (no `path` module).
  const lastSep = Math.max(
    worktreePath.lastIndexOf("/"),
    worktreePath.lastIndexOf("\\"),
  );
  const parent = lastSep >= 0 ? worktreePath.slice(0, lastSep) : ".";
  return `${parent}/.ledger-${issueNumber}`;
}

/**
 * Stable SHA-256 hash for the ledger's `prompt_hash` field.
 *
 * For agent steps: hash of the promptFile name (v0.1 placeholder; a real
 * implementation would hash the resolved file content).
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
 * `sessionId` is stable per `runOrchestrator` invocation (set once at run start).
 * `branchHEAD` is the worktree branch ref when known; empty string before S1.
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
 * The fixed StepSpec for each agent step. Versioned promptFiles, never
 * assembled inline (ADR 0018 §4). #247 sets id/role/promptFile; model /
 * completionSignal / maxIter are seams for later slices.
 */
const STEP_SPECS: Readonly<Record<"S2" | "S3", StepSpec>> = {
  S2: { id: "S2", role: "coder", promptFile: "coder_implement.md" },
  S3: { id: "S3", role: "reviewer", promptFile: "reviewer_full_review.md" },
};

export async function runOrchestrator(input: RunInput): Promise<RunResult> {
  const { issueNumber, backend } = input;
  const ledger: LedgerEntry[] = [];

  // State threaded across steps within this run.
  let worktree: WorktreeHandle | undefined;
  let lastOutput: StepOutput | undefined;

  // ── #249: per-run session id + sibling state dir ──────────────────────────
  // sessionId: a stable identifier for this orchestrator invocation.
  // Using crypto.randomUUID() (Node ≥ 14.17) — no external deps.
  const sessionId = crypto.randomUUID();

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

    // stateDir is now known: flush buffered entries first (in order), then write.
    for (const pending of pendingEntries.splice(0)) {
      await backend.writeLedger(pending, stateDir);
    }
    await backend.writeLedger(entry, stateDir);
  }
  // ─────────────────────────────────────────────────────────────────────────

  // The runner drives the sequence; the agent never picks the next step.
  let step: StepId = "S0";

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
        // S0 input_gate — runner action. #247: fetch lightweight metadata; the
        // real gate validation (rfa / Agent Brief / sub-issues / blocked_by)
        // is #248. Here we read it (proving the seam) and pass through.
        await backend.fetchIssueMeta(issueNumber);
        break;
      }

      case "S1": {
        // S1 load_context — runner action: full snapshot → resident worktree
        // (base=main) → write snapshot in (clean-room).
        const snapshot: IssueSnapshot =
          await backend.fetchIssueSnapshot(issueNumber);
        worktree = await backend.prepareWorktree(issueNumber, SLICE_BASE);
        await backend.writeSnapshot(worktree, snapshot);
        // Now that the worktree is prepared, fix the stateDir to be a true
        // sibling of the worktree root (not the provisional cwd-based one).
        stateDir = deriveStateDir(worktree.path, issueNumber);
        break;
      }

      case "S2":
      case "S3": {
        // Agent step — one sandbox.run() driven by its fixed StepSpec.
        if (worktree === undefined) {
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
        promptFile = STEP_SPECS[step].promptFile;
        output = await backend.runStep(STEP_SPECS[step], worktree);
        lastOutput = output;
        break;
      }

      case "S4": {
        // S4 route_findings — pure TS, no agent. route() (below) consumes the
        // reviewer output; nothing to do in the step body itself.
        break;
      }

      case "S7": {
        // S7 push — runner action: push the resident slice branch. No PR, no
        // merge (the Backend exposes neither).
        if (worktree === undefined) {
          throw new Error("runner: S7 push reached before worktree prepared");
        }
        await backend.push(worktree);
        break;
      }

      case "S8": {
        // Unreachable: S8 is produced as a terminal handoff by route(), it is
        // never entered as a loop step. Guarded for completeness.
        throw new Error("runner: S8 should be reached via handoff, not looped");
      }

      default: {
        // S5/S6 are fix-loop steps not wired in #247.
        throw new Error(`runner: step ${step} not implemented in #247`);
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
      await emitLedger("S8", undefined, undefined);
      return {
        status: decision.status,
        branch: decision.status === "success" ? worktree?.branch : undefined,
        stepLedger: ledger,
      };
    }

    step = decision.step;
  }

  throw new Error(
    `runner: exceeded ${MAX_STEPS} steps without reaching handoff (routing bug)`,
  );
}
