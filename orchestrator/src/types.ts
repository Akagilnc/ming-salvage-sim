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
  /** Versioned prompt file; prompts are never assembled ad-hoc (ADR 0018 §4). */
  readonly promptFile: string;
  /**
   * Short model slug the runtime maps to a baked-in CLI.
   * Changing the slug is all it takes to swap models — no image rebuild, no
   * StepSpec shape change (ADR 0018 §6, US #28).
   * `"sonnet"` → coder CLI; `"opus"` → reviewer CLI.
   */
  readonly model: string;
  /**
   * Signal the agent emits to mark the step complete (Sandcastle `run()` API).
   * Required so the sandbox knows when to stop and collect structured output.
   */
  readonly completionSignal: string;
  /**
   * Per-step iteration cap.
   * - coder / fix steps: > 1 (they loop until done or escalate).
   * - reviewer steps: exactly 1 (single pass — reviewer never self-edits).
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
  /** S2/S3/S5/S6: one `sandbox.run()` for an agent step. */
  runStep(spec: StepSpec, worktree: WorktreeHandle): Promise<StepOutput>;
  /** S7: push the resident slice branch (no PR, no merge). */
  push(worktree: WorktreeHandle): Promise<void>;
}

// ──────────────────────────── run result ────────────────────────────

/** Input to the orchestrator: only an issue number + the Backend seam. */
export interface RunInput {
  readonly issueNumber: number;
  readonly backend: Backend;
}

/** Final handoff (S8). `status` lets the caller tell the three outcomes apart. */
export interface RunResult {
  readonly status: HandoffStatus;
  /** The reviewed, pushed slice branch (set on success). */
  readonly branch?: string;
  /** The step ledger — anti-skip + resume truth. */
  readonly stepLedger: ReadonlyArray<LedgerEntry>;
}
