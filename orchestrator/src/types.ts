/**
 * Domain types for the Epic Orchestrator (#244).
 *
 * This file holds the load-bearing seams that every downstream slice
 * (#248–#256) layers on top of:
 *   - {@link Backend}  — the single injected seam for all external actions.
 *   - {@link StepSpec} — what one agent step is made of.
 *   - step-output schema ({@link CoderOutput} / {@link ReviewerOutput}) —
 *     the agent↔runner contract that {@link route} consumes.
 *
 * Slice #247 only wires the happy path; field VALUES and most step kinds are
 * present in shape but exercised minimally. Keep shapes stable — later slices
 * fill behaviour in, not re-shape these.
 */

// ───────────────────────────── step identifiers ─────────────────────────────

/**
 * The fixed wiki step sequence (ADR 0018). Each id is either an *agent step*
 * (runs `sandbox.run()`) or a *runner action* (pure TS, no agent):
 *
 *   agent steps   : S2 coder_implement, S3 reviewer_full_review,
 *                   S5 coder_fix, S6 reviewer_rereview
 *   runner actions: S0 input_gate, S1 load_context, S4 route_findings,
 *                   S7 push, S8 handoff
 */
export type StepId =
  | "S0"
  | "S1"
  | "S2"
  | "S3"
  | "S4"
  | "S5"
  | "S6"
  | "S7"
  | "S8";

/** Which soul a step runs under. v0.1 = one image, two roles. */
export type StepRole = "coder" | "reviewer";

/** Terminal handoff status (ADR 0018 / PRD #244 route table). */
export type HandoffStatus = "success" | "escalate" | "error";

// ───────────────────────────── step spec ─────────────────────────────

/**
 * Soul identifier injected into the sandbox for a step.
 *
 * - `"coder"`: full dev-discipline soul (wiki TDD flow, /review, self-check).
 * - `"READ-ONLY"`: reviewer soul with READ-ONLY soft constraint baked in
 *   (prompt-level, not an OS-level mount — same image, separate `run()`).
 */
export type StepSoul = "coder" | "READ-ONLY";

/**
 * Project tool-chain entry. Each entry is a short, lower-case technology slug
 * (e.g. `"python"`, `"node"`, `"typescript"`). The full list is declared on
 * the image and asserted by #253 tests to include Python + frontend stack.
 */
export type ToolchainEntry = string;

/**
 * A single agent step (ADR 0018): one `sandbox.run()` driven entirely by the
 * runner. `role` selects which soul to inject (v0.1 one image, two roles);
 * `promptFile` is a versioned file — prompts are never assembled inline.
 *
 * #247 wired `id`, `role`, `promptFile`. #253 fills the remaining fields:
 * `model`, `completionSignal`, `maxIter`, `soul`, `toolchain`.
 */
export interface StepSpec {
  /** Which step in the S0–S8 sequence this spec drives (agent steps only). */
  readonly id: StepId;
  /** Selects the soul to inject. */
  readonly role: StepRole;
  /** Versioned prompt file; prompts are never assembled ad-hoc (ADR 0018 决定#4). */
  readonly promptFile: string;
  /**
   * Short model slug the runtime maps to a baked-in CLI.
   * Changing the slug is all it takes to swap models — no image rebuild, no
   * StepSpec shape change (PRD #244 Implementation Decisions).
   * `"sonnet"` → coder CLI; `"opus"` → reviewer CLI.
   */
  readonly model: string;
  /**
   * Signal the agent emits to mark the step complete (Sandcastle `run()` API).
   * Required so the sandbox knows when to stop and collect structured output.
   */
  readonly completionSignal: string;
  /**
   * Per-step iteration cap = the WITHIN-STEP agent (Ralph) retry budget for a
   * single `sandbox.run()`. NOT the fix-loop convergence round limit.
   *
   * - coder / fix steps: > 1 (the agent iterates within the one step until the
   *   step's work is done or it escalates).
   * - reviewer steps: exactly 1 (single pass — reviewer never self-edits).
   *
   * SEMANTICS (堵 #256 misuse): hitting maxIter means THAT step ends normally —
   * the outer `route()` loop then continues as usual. It is NEVER "the
   * orchestrator gives up": the orchestrator only stops when the MODEL emits an
   * `escalate` signal (US#18/US#19), never by counting iterations/rounds.
   *
   * v0.1: the runner does NOT enforce maxIter (lazy field — see STEP_SPECS).
   * When #256 wires Sandcastle, maxIter MUST be implemented with exactly this
   * semantics (within-step retry budget) and MUST NOT degrade into a
   * "count-to-N-then-give-up" fix-loop cap, which would violate US#18.
   */
  readonly maxIter: number;
  /**
   * Which soul to inject into the sandbox for this step (#253).
   * `"coder"` = full dev-discipline soul;
   * `"READ-ONLY"` = reviewer soul, soft-constraint READ-ONLY baked into soul
   * (not an OS-level readonly mount — same image, separate `run()` context).
   */
  readonly soul: StepSoul;
  /**
   * Project tool-chain the image declares (#253, US #29).
   * Must include Python + a frontend entry (node/npm/typescript).
   * Carried on every StepSpec so the runner can assert completeness.
   */
  readonly toolchain: ReadonlyArray<ToolchainEntry>;
}

// ──────────────────────────── step outputs ────────────────────────────
// The agent↔runner seam contract: route() consumes these structured outputs.

/** A reviewer finding (PRD #244 contract layer). */
export interface Finding {
  readonly severity: "critical" | "high" | "medium" | "low" | "clarity";
  readonly category: string;
  readonly claim_quote: string;
  readonly location: string;
  readonly suggested_fix: string;
  /** P0/P1 ⇒ always `fix_now`; P2/P3 reviewer judges fix_now vs defer. */
  readonly action: "fix_now" | "defer";
}

/** Output of a coder step (S2/S5). 0 commits ⇒ committed:false (not a miss). */
export interface CoderOutput {
  readonly kind: "coder";
  readonly committed: boolean;
  readonly commitsAdded: number;
  /** Any agent step may signal it is stuck (route() reads this first). */
  readonly escalate?: Escalation;
}

/** Output of a reviewer step (S3/S6). Empty findings ⇒ approve. */
export interface ReviewerOutput {
  readonly kind: "reviewer";
  readonly findings: ReadonlyArray<Finding>;
  /** Any agent step may signal it is stuck (route() reads this first). */
  readonly escalate?: Escalation;
}

/** Stuck signal (ADR 0018 §5): model-judged, runner-routed — not agent-driven. */
export interface Escalation {
  readonly reason: string;
  readonly diagnosis: string;
}

/** The structured output of any agent step. */
export type StepOutput = CoderOutput | ReviewerOutput;

// ──────────────────────────── snapshots ────────────────────────────

/**
 * Lightweight issue metadata read by the S0 input gate (host-side `gh`).
 * #247's fake returns a compliant issue; the real S0 validation logic is #248.
 */
export interface IssueMeta {
  readonly number: number;
  readonly isReadyForAgent: boolean;
  readonly hasAgentBrief: boolean;
  readonly hasSubIssues: boolean;
  /** Issue numbers of still-open blocked_by dependencies. */
  readonly openBlockedBy: ReadonlyArray<number>;
}

/** Full issue snapshot read by S1 (body + comments + Agent Brief). */
export interface IssueSnapshot {
  readonly number: number;
  readonly body: string;
  readonly comments: ReadonlyArray<string>;
  readonly agentBrief: string;
}

/** Handle to the resident slice worktree (ADR 0017). */
export interface WorktreeHandle {
  readonly branch: string;
  readonly base: string;
  readonly path: string;
}

// ──────────────────────────── ledger ────────────────────────────

/**
 * One step-ledger entry (ADR 0018 §3). The ledger is the anti-skip truth and
 * the resume truth. #247 records the minimal shape; #249 builds the full
 * persisted ledger (sessionId, prompt_hash, branchHEAD, ts, sibling state dir).
 */
export interface LedgerEntry {
  readonly step: StepId;
  /** Structured output for agent steps; undefined for runner-action steps. */
  readonly output?: StepOutput;
}

/**
 * Full persisted ledger entry (#249). Extends {@link LedgerEntry} with the
 * audit and resume fields required by ADR 0018 §3.
 *
 * ⚠️ v0.1 PLACEHOLDERS (real values + seam extension = #256). Three of these
 * fields carry placeholder values in v0.1 — do NOT rely on them as their
 * eventual real meaning yet:
 *   - `sessionId`   — v0.1: a run-level UUID shared by ALL steps in one run.
 *                     Real (#256): the per-step sandbox session id from
 *                     `resumeSession` — requires the seam extension that has
 *                     `runStep` RETURN the real session id.
 *   - `prompt_hash` — v0.1: SHA-256 of the promptFile NAME (or step id for
 *                     runner-action steps). Real (#256): SHA-256 of the
 *                     resolved promptFile CONTENT (real anti-tampering audit).
 *   - `branchHEAD`  — v0.1: the branch NAME. Real (#256): the git commit SHA
 *                     (`git rev-parse HEAD`) at the worktree HEAD.
 *   - `ts`          — ISO-8601 timestamp when this entry was written (real).
 *
 * The runner hands this to {@link Backend.writeLedger}, which persists it to the
 * sibling state directory (outside the worktree so `git clean -fd` cannot remove it).
 */
export interface PersistentLedgerEntry extends LedgerEntry {
  /**
   * Sandbox session identifier (resume truth).
   *
   * TODO(#256): v0.1 PLACEHOLDER — stores a run-level UUID shared by all
   * steps in a single runOrchestrator invocation. This is NOT a per-step
   * sandbox session id. The real per-step session id (required for
   * `resumeSession`) needs the seam extension where `runStep` RETURNS the real
   * session id; wire in #256.
   */
  readonly sessionId: string;
  /**
   * Prompt hash for the anti-tampering audit.
   *
   * TODO(#256): v0.1 PLACEHOLDER — SHA-256 of the promptFile NAME for agent
   * steps (or of the step id string for runner-action steps), NOT of the file
   * CONTENT. The real content hash (true anti-tampering) requires the real
   * Backend reading the resolved promptFile; wire in #256.
   */
  readonly prompt_hash: string;
  /**
   * Worktree branch reference when this entry was recorded.
   *
   * TODO(#256): v0.1 PLACEHOLDER — stores the branch NAME (e.g.
   * "feat/244-s249-ledger"), NOT a git commit SHA. The real git SHA (from
   * `git rev-parse HEAD`) requires the real Backend; wire in #256.
   */
  readonly branchHEAD: string;
  /** ISO-8601 timestamp when this entry was persisted. */
  readonly ts: string;
}

// ──────────────────────────── Backend seam ────────────────────────────

/**
 * THE seam (PRD #244): the runner reaches the outside world only through this
 * injected interface — read issue, prepare worktree, run an agent step, push.
 * #247 injects a fake; the real Backend (Sandcastle + gh + git) is verified
 * separately. Keep this minimal and stable — 9 slices layer on it.
 */
export interface Backend {
  /** S0: lightweight metadata for the input gate (host-side `gh`). */
  fetchIssueMeta(issueNumber: number): Promise<IssueMeta>;
  /** S1: full snapshot (body + comments + Agent Brief) for the coder. */
  fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot>;
  /** S1: resident slice worktree from `base` (native createWorktree). */
  prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle>;
  /** S1: write the issue snapshot into the worktree (clean-room). */
  writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void>;
  /**
   * S2/S3/S5/S6: one `sandbox.run()` for an agent step.
   *
   * v0.1 returns only the structured {@link StepOutput}. The real per-step
   * sandbox session id (needed for `resumeSession` and the ledger's real
   * `sessionId`) is NOT carried here yet — extending this return to include
   * the session id is the #256 seam extension (see PersistentLedgerEntry).
   */
  runStep(spec: StepSpec, worktree: WorktreeHandle): Promise<StepOutput>;
  /** S7: push the resident slice branch (no PR, no merge). */
  push(worktree: WorktreeHandle): Promise<void>;
  /**
   * Write one persisted ledger entry to the sibling state directory (#249).
   *
   * The `stateDir` is derived by the runner from the worktree path: it is a
   * SIBLING of the worktree root (not a child), so `git clean -fd` on the
   * worktree cannot remove it. Naming convention:
   *   `<worktree-parent>/.ledger-<issueNumber>/`
   *
   * The Backend implementation appends the entry as a JSON-Lines record to
   * `<stateDir>/steps.jsonl`.  The runner calls this once per step, including
   * the S8 handoff entry, BEFORE returning the final result.
   */
  writeLedger(entry: PersistentLedgerEntry, stateDir: string): Promise<void>;
}

// ──────────────────────────── run result ────────────────────────────

/** Input to the orchestrator: only an issue number + the Backend seam. */
export interface RunInput {
  readonly issueNumber: number;
  readonly backend: Backend;
}

/**
 * Diagnostic payload for S8(status=error) (US#30, #252).
 * Lets the developer pinpoint the failing step without re-running the whole pipeline.
 */
export interface ErrorPackage {
  /** The step at which the run failed. */
  readonly failedStep: StepId;
  /** Human-readable explanation of what went wrong. */
  readonly reason: string;
  /**
   * Resident slice branch name at the time of failure.
   * Set whenever the worktree was already prepared (S1 completed), so commits
   * made before the failure are locatable without re-running the pipeline.
   */
  readonly branchHead?: string;
}

/** Final handoff (S8). `status` lets the caller tell the three outcomes apart. */
export interface RunResult {
  readonly status: HandoffStatus;
  /** The reviewed, pushed slice branch (set on success). */
  readonly branch?: string;
  /**
   * Diagnostic error payload — set when status=error (#252).
   * Undefined for success and escalate outcomes.
   */
  readonly errorPackage?: ErrorPackage;
  /** The step ledger — anti-skip + resume truth. */
  readonly stepLedger: ReadonlyArray<LedgerEntry>;
  /**
   * Reviewer findings with action:'defer' collected at S4 (PRD #244 US#25).
   * Present on success handoff so the caller can surface them (e.g. as a
   * follow-up issue list). Empty array when no defer findings exist.
   */
  readonly deferredFindings: ReadonlyArray<Finding>;
}
