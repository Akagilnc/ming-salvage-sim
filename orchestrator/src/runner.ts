/**
 * runOrchestrator — the runner loop (ADR 0018).
 *
 * The runner drives the fixed S0–S8 sequence itself: it performs each
 * runner-action step or dispatches each agent step, writes a step-ledger
 * entry, then calls route() to pick the next step. The agent never decides
 * the next step — route() does.
 *
 * Slice #247 = the thinnest happy path.
 * Slice #252 adds error edges:
 *   - S2 committed:false → S8(error)  [route() detects]
 *   - S7 push() throws  → S8(error)   [runner catch]
 *   - any backend call throws          → S8(error) + error package  [runner catch]
 *   - any agent output carries escalate → S8(escalate) [route() detects]
 *
 * No fix loop (#254), no full severity routing (#250), no persisted
 * ledger (#249), no soul injection (#253). Those layer onto these seams.
 */

import { route } from "./route.js";
import type {
  ErrorPackage,
  IssueSnapshot,
  LedgerEntry,
  RunInput,
  RunResult,
  StepId,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "./types.js";

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
  return { status: "error", errorPackage, stepLedger: ledger };
}

export async function runOrchestrator(input: RunInput): Promise<RunResult> {
  const { issueNumber, backend } = input;
  const ledger: LedgerEntry[] = [];

  // State threaded across steps within this run.
  let worktree: WorktreeHandle | undefined;
  let lastOutput: StepOutput | undefined;

  // The runner drives the sequence; the agent never picks the next step.
  let step: StepId = "S0";

  // Defensive runaway guard against a route() bug spinning the step machine
  // forever (happy path visits 7 steps; the cap is generous). This is NOT the
  // convergence safety-valve / round-cap — that is findings-driven and
  // deferred (PRD #244 G2, US#18/19). Do not repurpose it for fix-loop limits.
  const MAX_STEPS = 32;

  for (let i = 0; i < MAX_STEPS; i++) {
    let output: StepOutput | undefined;

    switch (step) {
      case "S0": {
        // S0 input_gate — runner action. #247: fetch lightweight metadata; the
        // real gate validation (rfa / Agent Brief / sub-issues / blocked_by)
        // is #248. Here we read it (proving the seam) and pass through.
        try {
          await backend.fetchIssueMeta(issueNumber);
        } catch (err) {
          return errorHandoff("S0", err, ledger, worktree);
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
        break;
      }

      case "S2":
      case "S3": {
        // Agent step — one sandbox.run() driven by its fixed StepSpec.
        if (worktree === undefined) {
          // Programming error: the runner sequenced wrong.
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
        try {
          output = await backend.runStep(STEP_SPECS[step], worktree);
        } catch (err) {
          return errorHandoff(step, err, ledger, worktree);
        }
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
        // S5/S6 are fix-loop steps not wired in #247.
        throw new Error(`runner: step ${step} not implemented in #247`);
      }
    }

    // Record this step in the ledger (anti-skip + resume truth, ADR 0018 §3).
    ledger.push(output === undefined ? { step } : { step, output });

    // The runner — not the agent — decides the next step.
    const decision = route({ from: step, output: lastOutput });

    if (decision.kind === "handoff") {
      ledger.push({ step: "S8" });

      if (decision.status === "error") {
        // Build an error package from the current step context so the developer
        // can diagnose without re-running the pipeline (#252 / US#30).
        const reason = buildErrorReason(step, lastOutput);
        const errorPackage: ErrorPackage = {
          failedStep: step,
          reason,
          branchHead: worktree?.branch,
        };
        return { status: "error", errorPackage, stepLedger: ledger };
      }

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
