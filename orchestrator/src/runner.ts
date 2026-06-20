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
 */
const STEP_SPECS: Readonly<Record<"S2" | "S3", StepSpec>> = {
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
};

export async function runOrchestrator(input: RunInput): Promise<RunResult> {
  const { issueNumber, backend } = input;
  const ledger: LedgerEntry[] = [];

  // State threaded across steps within this run.
  let worktree: WorktreeHandle | undefined;
  let lastOutput: StepOutput | undefined;

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
