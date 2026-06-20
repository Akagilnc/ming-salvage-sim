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
// Shared seam guards — single source of truth, also used by route(), so the
// finding-element (A) / commitsAdded (B) rules can never drift.
import { isValidStepOutput } from "./validate.js";
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

  /**
   * Best-effort persist for the error path (#3). Unlike emitLedger, a
   * writeLedger failure HERE is swallowed: we are already terminating with an
   * error, so a secondary persistence failure must not mask the original cause
   * nor raw-reject. The in-memory ledger still records the step regardless.
   */
  async function persistBestEffort(
    s: StepId,
    output: StepOutput | undefined,
    promptFile: string | undefined,
  ): Promise<void> {
    try {
      await emitLedger(s, output, promptFile);
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
    opts?: { recordInMemory?: boolean },
  ): Promise<RunResult> {
    // integ-cmr base r2 (D): split the two concerns the old single
    // `recordFailingStep` flag conflated. `recordInMemory` controls only the
    // in-memory push (skip it when the caller already pushed the failing step —
    // the writeLedger-failure path does). The best-effort PERSIST of the failing
    // step is UNCONDITIONAL: a transient ledger write fault must not leave the
    // persisted ledger missing the failing step (resume reads the persisted
    // ledger, so disk and memory must agree on the error path).
    const recordInMemory = opts?.recordInMemory ?? true;
    const reason = err instanceof Error ? err.message : String(err);
    const errorPackage: ErrorPackage = {
      failedStep,
      reason,
      branchHead: worktree?.branch,
    };

    // Record the failing step. The in-memory push is skipped when the caller
    // already pushed it (recordInMemory:false) or it is S8 itself; the
    // best-effort persist is still attempted so disk and memory agree (D).
    if (failedStep !== "S8") {
      if (recordInMemory) {
        ledger.push({ step: failedStep });
      }
      await persistBestEffort(failedStep, undefined, undefined);
    }

    // Terminal S8 entry — in-memory + persisted.
    ledger.push({ step: "S8" });
    await persistBestEffort("S8", undefined, undefined);

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
        // S5/S6 are fix-loop stubs added in #250; full loop control is #254.
        if (worktree === undefined) {
          // Programming error: the runner sequenced wrong.
          throw new Error(`runner: ${step} reached before worktree prepared`);
        }
        promptFile = STEP_SPECS[step].promptFile;
        try {
          output = await backend.runStep(STEP_SPECS[step], worktree);
        } catch (err) {
          return await errorTermination(step, err);
        }
        // #5 + integ-cmr base r2 (A, B): the step output must satisfy the full
        // role contract — not just kind. A coder step must yield a CONSISTENT
        // {committed, commitsAdded} (B: committed=true⇒≥1, false⇒0, non-negative
        // integer); a reviewer step must yield findings whose every ELEMENT is
        // valid (A: exact severity/action enums + required string fields). A
        // wrong-kind / undefined / garbage output, an inconsistent commitsAdded,
        // or any malformed finding element is a contract violation — NEVER pass
        // it silently to route() where it could bypass the P0/P1 fix gate (e.g.
        // a "critical " severity slips the exact-string test → push). Report
        // S8(error) instead. The runner and route() share one guard (validate.ts).
        const expectedKind =
          STEP_SPECS[step].role === "coder" ? "coder" : "reviewer";
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
      await emitLedger(step, output, promptFile);
    } catch (err) {
      // integ-cmr base r2 (D): the step is already in the in-memory ledger
      // (pushed above), so skip the in-memory push — but STILL best-effort
      // re-persist the failing step so the persisted ledger is not left missing
      // it on a transient write fault.
      return await errorTermination(step, err, { recordInMemory: false });
    }

    // The runner — not the agent — decides the next step.
    const decision = route({ from: step, output: lastOutput });

    if (decision.kind === "handoff") {
      ledger.push({ step: "S8" });
      // #249: persist the S8 handoff entry too.
      // #6: same as above — a writeLedger failure on the S8 entry → S8(error),
      // not a raw rejection. (deferredFindings stays whatever was collected.)
      try {
        await emitLedger("S8", undefined, undefined);
      } catch (err) {
        // integ-cmr base r2 (E): the failing operation here is the S8 handoff
        // ledger write — which happens for ANY handoff (S2 no-commit error,
        // route error, escalate, push success). The old code hard-coded
        // failedStep:"S7", misattributing it to push even on paths where push
        // never ran. Attribute to the REAL failing step (the S8 write) and name
        // the operation in the reason so the dev sees what actually failed.
        const cause = err instanceof Error ? err.message : String(err);
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

  throw new Error(
    `runner: exceeded ${MAX_STEPS} steps without reaching handoff (routing bug)`,
  );
}
