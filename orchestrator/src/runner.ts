/**
 * runOrchestrator — the runner loop (ADR 0018).
 *
 * The runner drives the fixed S0–S8 sequence itself: it performs each
 * runner-action step or dispatches each agent step, writes a step-ledger
 * entry, then calls route() to pick the next step. The agent never decides
 * the next step — route() does.
 *
 * Slice #247: happy path S0–S3–S4(approve)–S7–S8.
 * Slice #250: S4 severity+action fan-out; S5/S6 step bodies stubbed so the
 *   fan-out is exercisable end-to-end (fix-loop back-edge remains #254).
 *
 * Remaining seams: #248 (real S0 gate), #249 (persisted ledger), #251
 * (escalate stop), #252 (error edges), #253 (soul injection), #254 (fix loop).
 */

import { route } from "./route.js";
import type {
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
 *
 * S5/S6 added in #250 (fix loop stubs — the real loop control is #254).
 */
const STEP_SPECS: Readonly<Record<"S2" | "S3" | "S5" | "S6", StepSpec>> = {
  S2: { id: "S2", role: "coder", promptFile: "coder_implement.md" },
  S3: { id: "S3", role: "reviewer", promptFile: "reviewer_full_review.md" },
  // S5/S6: stubs so S4 fan-out can be tested end-to-end (#250).
  // The fix-loop back-edge S5→S6→S4 is wired by #254 — not here.
  S5: { id: "S5", role: "coder", promptFile: "coder_fix.md" },
  S6: { id: "S6", role: "reviewer", promptFile: "reviewer_rereview.md" },
};

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
        break;
      }

      case "S2":
      case "S3":
      case "S5":
      case "S6": {
        // Agent step — one sandbox.run() driven by its fixed StepSpec.
        // S5/S6 are fix-loop stubs added in #250; full loop control is #254.
        if (worktree === undefined) {
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
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
        // Exhaustiveness guard: any unrecognised step is a routing bug.
        const never: never = step;
        throw new Error(`runner: step ${String(never)} not handled`);
      }
    }

    // Record this step in the ledger (anti-skip + resume truth, ADR 0018 §3).
    ledger.push(output === undefined ? { step } : { step, output });

    // The runner — not the agent — decides the next step.
    const decision = route({ from: step, output: lastOutput });

    if (decision.kind === "handoff") {
      ledger.push({ step: "S8" });
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
