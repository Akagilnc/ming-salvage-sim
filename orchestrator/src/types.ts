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
 * The single-slice step sequence (ADR 0030): the runner owns the visible
 * per-slice review/fix loop.
 *
 *   S0 gate → S1 context → S2 implement → S3 review → S4 classify
 *     → S7 ship when clean
 *     → S5 fix → S6 fresh full-diff review → S4 classify while blocking remains
 *     → S8 handoff
 *
 * S2 and S5 are coder workers. S3 and S6 are fresh read-only reviewer workers.
 * S4 is the runner-owned classification boundary that makes per-round verdicts
 * visible in the ledger instead of hiding the loop inside one coder session.
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

/** Which role a single-slice worker runs under. */
export type StepRole = "coder" | "reviewer";

/** Terminal handoff status (ADR 0018 / PRD #244 route table). */
export type HandoffStatus = "success" | "escalate" | "error";

// ───────────────────────────── step spec ─────────────────────────────

/**
 * Soul identifier injected into the sandbox for a step.
 *
 * - `"coder"`: implementation/fix soul (TDD for S2, finding fix contract for S5).
 * - `"READ-ONLY"`: reviewer soul with READ-ONLY soft constraint baked in
 *   (prompt-level, not an OS-level mount — same image, separate `run()`).
 * - `"cmr"`: the family integrated-cmr fixer soul (ADR 0026 2026-06-24) — a WRITE
 *   soul: the cmr worker invokes `ak-cross-m-review` and commits its cross-slice
 *   fixes inside its own memory-bearing session (it is the fixer, not read-only).
 * - `"ship"`: the delivery soul the family ship worker runs under — a WRITE soul
 *   distinct from `"coder"`: it invokes `gstack-ship`, stops at PR creation, and
 *   records deferred findings in a tracker (issue / TODOS.md), never the PR body.
 */
export type StepSoul = "coder" | "READ-ONLY" | "cmr" | "ship";

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
   *
   * CONSUMED by the real Backend (ship-pre 256 r1): `RealBackend.box()` selects
   * the role's baked soul via `soulForStep(spec)` and injects it into the
   * container (`ORCHESTRATOR_SOUL`) so the v0.1 one-image-two-roles profile
   * activates the right one (#244 "role 决定注哪份 soul"; ADR 0017 §4). v0.1
   * derives the soul from `role`; this field is the explicit declaration and is
   * asserted to agree with the role (a contradiction is a misconfigured spec →
   * S8(error)), so it is a validated contract field, not a dangling one.
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

/**
 * The structured output of any worker step.
 *
 * ADR 0026 / PRD #330 [R2-b]: WIDENED from `CoderOutput | ReviewerOutput` to the
 * full {@link WorkerOutput} union (also carrying {@link ShipResult} /
 * {@link CmrResult} / {@link MergeWorkerResult}) so a ship/cmr/merge worker's
 * output can flow through the ledger ({@link LedgerEntry.output}) without a tsc
 * error. `StepOutput` is kept as the historical name (consumed by route/validate)
 * and is now an ALIAS of `WorkerOutput` — ONE union, no drift. Every consumer
 * discriminates on `.kind` behind `isValidStepOutput`, so the widening is safe:
 * route() acts only on the validated `coder`/`reviewer` cases, and an unknown
 * kind is rejected by the guard, never silently routed.
 */
export type StepOutput = WorkerOutput;

/**
 * Result of dispatching one agent step — the #256 seam extension.
 *
 * v0.1 (#247–#255) had {@link Backend.runStep} / {@link Backend.resumeSession}
 * return only the bare {@link StepOutput}, with the ledger's per-step `sessionId`
 * carrying a single run-level UUID placeholder shared by every step (see
 * {@link PersistentLedgerEntry}). #256 (types.ts:361, authorised seam extension)
 * lets the Backend ALSO surface the real per-step sandbox session id, so the
 * ledger records the true id that {@link Backend.resumeSession} resumes.
 *
 * BACKWARD-COMPATIBLE by construction: the seam return type is widened to
 * `StepOutput | StepResult`, NOT replaced. A `StepResult` is distinguished from a
 * `StepOutput` purely by the absence of the `kind` discriminant (a `StepOutput`
 * always carries `kind:'coder'|'reviewer'`; a `StepResult` wraps the output under
 * `.output` and has no top-level `kind`). The fake Backends in the step
 * control-flow tests keep returning a bare `StepOutput` UNCHANGED — the runner
 * normalises both shapes (real Backend yields `StepResult` with the real id; a
 * bare `StepOutput` yields `sessionId: undefined` → run-level UUID fallback). The
 * runner control flow is identical for both, satisfying #256's "真假 Backend 同
 * 签名、控制流零改动" acceptance criterion.
 */
export interface StepResult {
  /** The structured agent output `route()` consumes. */
  readonly output: StepOutput;
  /**
   * The real per-step sandbox session id (Sandcastle
   * `RunResult.iterations[].sessionId`), or `undefined` when the agent/provider
   * did not surface one (e.g. a non-Claude provider, or capture disabled). The
   * runner records this as the ledger entry's `sessionId` (resume truth);
   * `undefined` falls back to the run-level UUID.
   */
  readonly sessionId?: string;
}

// ─────────────────────── unified worker-dispatch seam ───────────────────────
// ADR 0026 / PRD #330: every step that produces or changes the worked artifact
// is a WORKER dispatched through ONE seam, `dispatchWorker(spec, ctx)`. #331 is a
// PURE PREFACTOR: these shapes are defined and the call sites route through the
// seam, but `dispatchWorker` is a LEGACY WRAPPER forwarding to the existing
// methods (runStep / resumeSession / push / runIntegratedCmr / openFamilyPr), so
// external behaviour is unchanged. Per-worker output VALUES land in later slices
// (#334 coder/reviewer, #335 cmr, #336 ship); #331 only fixes the field shapes.

/**
 * Which kind of work a worker performs. Drives the {@link WorkerResult} payload
 * discriminant and (later slices) which skill is invoked:
 *   - `coder`    → invoke `/tdd` (S2 implement / S5 fix), resume across rounds.
 *   - `reviewer` → invoke `/review` (S3/S6 per-slice review), fresh each round.
 *   - `cmr`      → invoke `ak-cross-m-review` (family integrated cmr), fresh.
 *   - `ship`     → invoke `gstack-ship` (S7 / family PR).
 *   - `merge`    → family-layer merge (may use NO skill — ADR 0026); B 段, no A-段
 *                  consumer (shape only).
 */
export type WorkerKind = "coder" | "reviewer" | "cmr" | "ship" | "merge";

/** Which container host runs the worker (decides skill-invocation mechanism). */
export type WorkerHost = "claude" | "codex";

/**
 * The DISPATCH MODE for this worker invocation:
 *   - `fresh`  — a brand-new `sandbox.run()`. THE NORMAL CASE for every worker,
 *     including S2 implement and a normal S5 fix round.
 *   - `resume` — continue a PRIOR agent session via the Sandcastle-native
 *     `resumeSession` path (carrying {@link DispatchContext.resumeSessionId}).
 *
 * ADR 0026 INVARIANT (do not conflate with context retention): `resume` is the
 * CRASH/ESCALATE-resume path ONLY — it skips git-truthing (trusts the model's
 * self-report) and pins maxIter to 1. A normal coder/fix round must NOT use it
 * (it must keep git-truthing + within-step maxIter). So a worker is `resume`
 * ONLY when the runner is actually threading a `resumeSessionId`; otherwise
 * `fresh`. "Retain context across fix rounds" is a SEPARATE concern — see
 * {@link WorkerSpec.contextRetention} — NOT expressed via `resume`.
 */
export type WorkerSessionMode = "fresh" | "resume";

/**
 * Whether a worker keeps its working context across fix-loop rounds (ADR 0026
 * "fresh vs resume 按活类型"), DECOUPLED from the {@link WorkerSessionMode}
 * dispatch path:
 *   - `retain` — production workers (coder/fix) keep "what I wrote, why" across
 *     rounds so a fix接得住 findings without re-exploring from scratch. ADR 0026:
 *     the MECHANISM (e.g. fresh run + prior findings/output fed in, vs a
 *     fix-loop-capable resume) is left to the worker implementation (#334) — the
 *     INVARIANT is that a normal fix keeps git-truthing + maxIter, so it is NOT
 *     the `resume` (crash/escalate) dispatch path.
 *   - `clean`  — review workers (reviewer/cmr) start each round with clean eyes
 *     (cross-model independence; never re-checking their own prior findings).
 */
export type WorkerContextRetention = "retain" | "clean";

/**
 * The declarative spec of one worker step — what the runner hands the dispatch
 * seam so the dispatch decision is EXPLICIT and ASSERTABLE (US#16/#18/#19).
 *
 * Prompt权归 runner (ADR 0018 决定#4, kept by PRD #330 [D]): `promptFile` +
 * `promptArgs` are VERSIONED — the dispatch never assembles a prompt ad-hoc, and
 * `promptFile` CONTENT is still hashed into the ledger (anti-tampering). The
 * "thin prompt" of ADR 0026 means the promptFile CONTENT is slim ("implement
 * issue #N per CLAUDE.md dev flow"), NOT that prompts are built inline.
 */
export interface WorkerSpec {
  /** Which step in the S0–S8 sequence this worker drives. */
  readonly id: StepId;
  /** The work kind (drives result payload + skill routing). */
  readonly kind: WorkerKind;
  /** Which soul to inject (v0.1 one image, two roles). */
  readonly role: StepRole;
  /** Which container host runs it (Claude `Skill` invoke vs Codex SKILL.md item). */
  readonly host: WorkerHost;
  /**
   * The dispatch path for THIS invocation: `fresh` (a new `sandbox.run()`, the
   * normal case) or `resume` (the crash/escalate-resume path, set ONLY when the
   * runner threads a {@link DispatchContext.resumeSessionId}). NOT a proxy for
   * "coder retains context" — see {@link contextRetention} (ADR 0026 invariant:
   * a normal fix round is `fresh`, never `resume`).
   */
  readonly session: WorkerSessionMode;
  /**
   * Whether this worker keeps context across fix-loop rounds (`retain` for
   * coder/fix, `clean` for reviewer/cmr) — ADR 0026, DECOUPLED from {@link session}.
   */
  readonly contextRetention: WorkerContextRetention;
  /**
   * The wiki skill this worker invokes, or `undefined` for a no-skill worker
   * (e.g. family merge — ADR 0026 US#9). The "可空" branch has NO A-段 consumer;
   * it only reserves the shape for B 段 (PRD #330 [E]).
   */
  readonly skill?: string;
  /** Versioned prompt file; never assembled ad-hoc (ADR 0018 决定#4, hashed). */
  readonly promptFile: string;
  /** Versioned prompt arguments substituted into the promptFile (still hashed). */
  readonly promptArgs?: Readonly<Record<string, string>>;
  /** Signal the worker emits to mark completion (Sandcastle `run()` API). */
  readonly completionSignal: string;
  /** Within-step Ralph retry budget (NOT the fix-loop round cap — see {@link StepSpec.maxIter}). */
  readonly maxIter: number;
  /** Short model slug the runtime maps to a baked-in CLI (PRD #244). */
  readonly model: string;
  /** Soul to inject (`coder` full discipline / `READ-ONLY` reviewer). */
  readonly soul: StepSoul;
  /** Project tool-chain the image declares (US #29). */
  readonly toolchain: ReadonlyArray<ToolchainEntry>;
}

/**
 * Everything (besides the {@link WorkerSpec}) the dispatch seam needs to run a
 * worker — PRD #330 [H]: the inputs are part of the contract.
 */
export interface DispatchContext {
  /**
   * The resident slice worktree (ADR 0017 commit truth). MANDATORY for
   * single-slice workers (coder/reviewer/ship S7); OPTIONAL for family-level
   * workers (cmr / family ship) whose caller only has `familyBase: string` and
   * lets the backend infer the working repo (PRD #330 R2). When present, asserts
   * the worker's commits only land on this one worktree.
   */
  readonly worktree?: WorktreeHandle;
  /**
   * The family base branch — supplied INSTEAD of (or alongside) a `worktree` for
   * family-level workers (cmr / family ship) whose caller has only the base
   * string, no worktree path (PRD #330 R2 — `runFamilyVerify`/`runIntegratedCmr`
   * take `{familyBase}`).
   */
  readonly familyBase?: string;
  /** The sibling state directory holding the persisted ledger (ADR 0018 §3). */
  readonly stateDir?: string;
  /**
   * The prior agent session id to resume — present ONLY for a `session:"resume"`
   * dispatch, i.e. the CRASH/ESCALATE-resume path where the runner re-opens a
   * recorded S2 build session (ADR 0026 invariant). A NORMAL S2 build is
   * `session:"fresh"` and does NOT carry this; the per-slice review→fix loop runs
   * INSIDE the build worker's own session, not via a resumed session (codex cmr
   * R3/R4 finding: a normal build must not take the resume path, which skips
   * git-truthing).
   */
  readonly resumeSessionId?: string;
  /**
   * Host-written issue snapshot for audit/resume compatibility. Current workers
   * live-fetch issue truth via gh using runner-injected issue/repo env; this is
   * not the execution source of truth.
   */
  readonly issueSnapshot?: IssueSnapshot;
  /**
   * S5 coder-fix worker only: the blocking reviewer findings selected at S4
   * from the current full-diff review. This is the structured cross-worker
   * contract ADR 0030 needs; the runner owns classification and the fix worker
   * receives data, not hidden session memory.
   */
  readonly blockingFindings?: ReadonlyArray<Finding>;
  /**
   * Stable identity keys for {@link blockingFindings}. Suppression/reopen logic
   * must match findings by normalized identity rather than exact object text, so
   * the runner passes the keys alongside the structured findings.
   */
  readonly blockingFindingIdentityKeys?: ReadonlyArray<string>;
  /**
   * FAMILY cmr worker only: the child issue numbers whose merge into the family
   * base was LLM-resolved (#295) — forwarded to the integrated cmr 承重闸 so it
   * focuses on the merges a machine touched (PRD #330 / #291 缺口 1). Undefined for
   * single-slice workers and for a conflict-free family run.
   */
  readonly llmResolvedChildren?: ReadonlyArray<number>;
}

/** A coder worker's output — the existing {@link CoderOutput}. */
export type CoderResult = CoderOutput;

/**
 * Compatibility reviewer worker output. The active ADR 0026 path keeps per-slice
 * review/fix convergence inside the coder worker; if an older reviewer seam is
 * used, it must still return structured findings rather than a bare verdict.
 */
export type ReviewerResult = ReviewerOutput;

/**
 * A family integrated-cmr worker's output (#335). A BARE verdict is correct here
 * (PRD #330 R2): the consumer `verifyCmr.ts` reads `converged`; a `red` verdict
 * does NOT drive a fix-loop at this layer, so no findings array is required. (=
 * existing {@link IntegratedCmrResult}, re-exported via family/types — kept as a
 * separate `kind` payload in the union below.)
 */
export interface CmrResult {
  readonly kind: "cmr";
  /** Converged (all reviewers agreed) ⇒ true; else the gate is red. */
  readonly converged: boolean;
  /** Why it did not converge — set when red (handed to escalate). */
  readonly reason?: string;
  // NOTE: a STUCK cmr worker is the WorkerResult-level `{kind:"escalated"}` case,
  // NOT an `escalate` field on this `completed` payload (codex cmr R3b finding: a
  // payload-level escalate would be silently ignored by the verifyCmr consumer,
  // which reads `converged`). `completed` means the worker ran to completion.
}

/**
 * A ship worker's output (S7 / family PR, #336). `gstack-ship` does more than
 * push+PR (merge-base / tests / review gate / VERSION / CHANGELOG + STOP/HITL);
 * the non-success routing is a #336 concern — the SHAPE is fixed here.
 */
export interface ShipResult {
  readonly kind: "ship";
  /** The shipped branch. */
  readonly branch: string;
  /** The opened PR URL/handle (undefined when ship stopped before a PR). */
  readonly pr?: string;
  /** A short status string (e.g. "pushed" | "pr_opened"). Values: #336. */
  readonly status: string;
  // NOTE: a ship worker that STOPS for a human (gstack-ship STOP/HITL) is the
  // WorkerResult-level `{kind:"escalated"}` case (PRD #330 R2), NOT an `escalate`
  // field on this `completed` payload — a `completed ShipResult` means a PR opened
  // / push landed. (codex cmr R3b: a payload-level escalate would be ignored by
  // the S7 / family-ship consumers, which route a completed ship to success.)
}

/**
 * A family merge worker's output (B 段 — no A-段 consumer; shape only, PRD #330
 * [E]). Carries the family base HEAD after the merge landed.
 */
export interface MergeWorkerResult {
  readonly kind: "merge";
  /** The family base HEAD commit after this merge landed. */
  readonly familyHead: string;
  /** Was the merge LLM-resolved (vs a clean deterministic merge)? */
  readonly conflictResolvedByLlm?: boolean;
  // NOTE: a stuck merge worker is the WorkerResult-level `{kind:"escalated"}`
  // case, NOT an `escalate` field on this `completed` payload (codex cmr R3b).
}

/** The structured payload a worker produces — one per {@link WorkerKind}. */
export type WorkerOutput =
  | CoderResult
  | ReviewerResult
  | CmrResult
  | ShipResult
  | MergeWorkerResult;

/**
 * The result of dispatching ONE worker — a discriminated union so the runner can
 * route by case without ever receiving an undefined shape (PRD #330 [B]).
 *
 *   - `completed` — the worker ran and produced its structured `output`. NOTE a
 *     cmr `red` verdict is `completed` (with payload), NOT `failed` (PRD #330
 *     R2): `red` is a normal review outcome the runner routes on.
 *   - `failed`    — the worker crashed / its command or tests hard-failed
 *     (no usable output).
 *   - `malformed` — the worker produced output the seam could not parse into the
 *     declared schema (no completion signal / unparseable).
 *   - `escalated` — the worker (model-judged) signalled it is stuck and a human
 *     must answer (carries the resume指引). Crash/timeout/missing-skill map to
 *     `failed`/`malformed`; only a MODEL escalate is `escalated`.
 *
 * #331 prefactor: the legacy wrapper always yields `completed` (forwarding the
 * existing methods' returns); `failed`/`malformed`/`escalated` are wired into the
 * shape now and exercised by later slices.
 */
export type WorkerResult =
  | { readonly kind: "completed"; readonly output: WorkerOutput; readonly sessionId?: string }
  | { readonly kind: "failed"; readonly reason: string; readonly sessionId?: string }
  | { readonly kind: "malformed"; readonly reason: string; readonly sessionId?: string }
  | {
      readonly kind: "escalated";
      readonly escalation: Escalation;
      readonly sessionId?: string;
    };

// ──────────────────────────── snapshots ────────────────────────────

/**
 * Lightweight issue metadata read by the S0 input gate (host-side `gh`).
 * #247's fake returns a compliant issue; the real S0 validation logic is #248.
 */
export interface IssueMeta {
  readonly number: number;
  readonly isReadyForAgent: boolean;
  readonly hasSubIssues: boolean;
  /** The issue itself is CLOSED (gh `state` === "CLOSED") — S0 rejects it (#2). */
  readonly isClosed: boolean;
  /** Issue numbers of still-open blocked_by dependencies. */
  readonly openBlockedBy: ReadonlyArray<number>;
}

/**
 * The native metadata #244 S1 names as part of the full snapshot ("body +
 * comments + 最新 Agent Brief 正文 + native metadata"). S0 reads these via `gh`;
 * S1 writes them into the clean-room snapshot so the audit/resume artifact carries
 * the issue's title/state/labels + the native sub-issue + blocked_by summaries —
 * not just the body. Execution truth is still the live issue the worker reads via
 * in-container `gh`.
 */
export interface IssueSnapshotMeta {
  readonly title: string;
  /** "open" | "closed" (whatever `gh` reports; kept as a free string). */
  readonly state: string;
  readonly labels: ReadonlyArray<string>;
  /** Native sub-issue count (`gh issue view --json subIssues` → totalCount). */
  readonly subIssueCount: number;
  /** Native blocked_by dependency summary (number + state per dependency). */
  readonly blockedBy: ReadonlyArray<{ readonly number: number; readonly state: string }>;
}

/**
 * Full issue snapshot written by S1 (body + comments + Agent Brief + native
 * metadata). `nativeMeta` carries the #244-named native metadata; the REAL
 * Backend always populates it (`buildIssueSnapshot`), so the host audit/resume
 * artifact is contract-complete. Current workers execute from live issue reads,
 * not this snapshot.
 */
export interface IssueSnapshot {
  readonly number: number;
  readonly body: string;
  readonly comments: ReadonlyArray<string>;
  readonly agentBrief: string;
  readonly nativeMeta?: IssueSnapshotMeta;
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
 * #256 TRUTHIFIED these three formerly-placeholder fields. The REAL Backend now
 * supplies real values; the FAKE Backends in the step control-flow tests still
 * pass the v0.1 placeholders (those tests are zero-container and never exercise
 * the real Backend), so both meanings co-exist depending on which Backend ran:
 *   - `sessionId`   — Real (#256): the per-step sandbox session id surfaced by
 *                     the seam extension (runStep/resumeSession return a
 *                     {@link StepResult}). Fake/runner-action steps: a run-level
 *                     UUID fallback (no real per-step session).
 *   - `prompt_hash` — Real (#256): SHA-256 of the resolved promptFile CONTENT
 *                     (real anti-tampering audit). When the content is
 *                     unavailable (fake path / runner-action step) the runner
 *                     falls back to hashing the promptFile NAME (or step id).
 *   - `branchHEAD`  — Real (#256): the git commit SHA (`git rev-parse HEAD`) at
 *                     the worktree HEAD, read via the Backend. Fallback (no
 *                     Backend SHA available): the branch NAME, as in v0.1.
 *   - `ts`          — ISO-8601 timestamp when this entry was written (real).
 *
 * The runner hands this to {@link Backend.writeLedger}, which persists it to the
 * sibling state directory (outside the worktree so `git clean -fd` cannot remove it).
 */
export interface PersistentLedgerEntry extends LedgerEntry {
  /**
   * Sandbox session identifier (resume truth).
   *
   * #256 (DONE): the real Backend's seam extension surfaces the per-step sandbox
   * session id (via {@link StepResult}); the runner records it here so
   * {@link Backend.resumeSession} resumes the exact session that produced the
   * step. Runner-action steps (S0/S1/S4/S7/S8) and the zero-container fake path
   * fall back to a run-level UUID (no per-step sandbox session exists for them).
   */
  readonly sessionId: string;
  /**
   * Prompt hash for the anti-tampering audit.
   *
   * #256 (DONE): for agent steps the real Backend reads the resolved promptFile
   * and the runner hashes its CONTENT (real anti-tampering). When the content is
   * unavailable (the zero-container fake path, or a runner-action step with no
   * promptFile) the runner falls back to SHA-256 of the promptFile NAME (or the
   * step id string), as in v0.1.
   */
  readonly prompt_hash: string;
  /**
   * Worktree branch reference when this entry was recorded.
   *
   * #256 (DONE): the real Backend exposes the worktree HEAD SHA
   * (`git rev-parse HEAD`); the runner records that real commit SHA here. When
   * no Backend SHA is available (the zero-container fake path) the runner falls
   * back to the branch NAME (e.g. "feat/244-s249-ledger"), as in v0.1.
   */
  readonly branchHEAD: string;
  /** ISO-8601 timestamp when this entry was persisted. */
  readonly ts: string;
  /**
   * Terminal handoff status — set ONLY on the S8 entry (#255).
   *
   * Both success and error handoffs previously wrote an identical `{step:"S8"}`
   * entry, making them indistinguishable to a resuming run reading the ledger.
   * Recording the status here lets {@link ResumeState} recovery report the TRUE
   * terminal outcome (success / escalate / error) instead of inferring it — and
   * lets a re-fed run tell a prior SUCCESS apart from a prior ERROR.
   * Undefined for every non-S8 (in-flight) entry.
   */
  readonly handoffStatus?: HandoffStatus;
}

// ──────────────────────────── resume state ────────────────────────────

/**
 * Residue discovered for an issue at the start of a run (#255).
 *
 * When the same issue is re-fed and a resident slice worktree + persisted
 * ledger already exist (crash residue OR escalate residue), the Backend's
 * {@link Backend.findResumeState} returns this so the runner can RESUME from
 * the recorded breakpoint instead of re-cutting from S0.
 *
 * Crash-resume and escalate-resume share ONE machine: both read this state,
 * reuse the worktree, clean uncommitted residue, and continue from the step
 * the ledger says is next (decided by `route()`, not LLM memory).
 *
 * `ledger` is the persisted step ledger read from the sibling state dir
 * (`<stateDir>/steps.jsonl`) — the resume truth. The last entry's step + output
 * drive the next-step decision; a recorded `sessionId` lets the runner resume
 * the prior agent session via {@link Backend.resumeSession}.
 */
export interface ResumeState {
  /** The existing resident slice worktree to reuse (not re-cut). */
  readonly worktree: WorktreeHandle;
  /** The sibling state directory holding the persisted ledger. */
  readonly stateDir: string;
  /**
   * The persisted ledger read back from disk, in execution order.
   * Empty array ⇒ no usable progress (treated as a fresh run by the runner).
   */
  readonly ledger: ReadonlyArray<PersistentLedgerEntry>;
}

// ──────────────────────────── Backend seam ────────────────────────────

/**
 * THE seam (PRD #244): the runner reaches the outside world only through this
 * injected interface — read issue, prepare worktree, run an agent step, push.
 * #247 injects a fake; the real Backend (Sandcastle + gh + git) is verified
 * separately. Keep this minimal and stable — 9 slices layer on it.
 */
export interface Backend {
  /**
   * #255: detect resume residue for this issue at the very start of a run.
   *
   * The host-side implementation checks whether a resident slice worktree +
   * persisted ledger already exist (crash or escalate residue). Returns the
   * {@link ResumeState} when residue is found, or `undefined` for a fresh run.
   *
   * This is consulted BEFORE the S0 gate: a resumed run already passed the gate
   * on its first pass, so it must not re-gate/re-cut.
   */
  findResumeState(issueNumber: number): Promise<ResumeState | undefined>;
  /**
   * #255: clean uncommitted residue on the resident worktree before reuse.
   *
   * Real implementation: `git reset --hard HEAD` + `git clean -fd` ONLY —
   * a per-worktree residue clean, scoped to the worktree path. Committed progress
   * (the resident branch HEAD) is PRESERVED; only uncommitted/untracked residue
   * from the interrupted run is discarded. The ledger lives in the sibling state
   * dir (outside the worktree), so `clean -fd` cannot remove the resume truth.
   *
   * ADR 0024 decision 2: this does NOT run a repo-level `git worktree prune`.
   * Worktree admin pruning is Sandcastle's responsibility (its per-acquire
   * pruneStale); with each invocation owning a dedicated clone, that prune is
   * scoped to the clone and can never reach another session's worktree admin
   * namespace. `cleanResidue` must stay confined to the worktree path.
   */
  cleanResidue(worktree: WorktreeHandle): Promise<void>;
  /**
   * #255: resume the prior agent session for a step (Sandcastle-native).
   *
   * Carries the `sessionId` recorded in the ledger so the SAME agent session
   * continues from the breakpoint — used for both crash-resume and
   * escalate-resume (e.g. after a human answers a design blocker, the coder
   * finishes in its original session rather than a fresh `run()`).
   *
   * v0.1 fake: records the call and returns a default output. The real
   * Sandcastle `resumeSession` wiring (incl. dead-session fallback) is #256.
   *
   * #256 seam extension: may return a {@link StepResult} carrying the real
   * per-step sandbox session id alongside the output (so the resumed session's
   * id is recorded in the ledger). A bare {@link StepOutput} return is still
   * accepted (no real id → run-level UUID fallback); the runner normalises both.
   *
   * ADR 0026: the only agent step is the S2 build worker; resume re-opens that
   * one session. The per-slice review→fix loop runs INSIDE the build worker, so
   * there is no separate fix step to deliver findings to on resume.
   */
  resumeSession(
    spec: StepSpec,
    worktree: WorktreeHandle,
    sessionId: string,
  ): Promise<StepOutput | StepResult>;
  /** S0: lightweight metadata for the input gate (host-side `gh`). */
  fetchIssueMeta(issueNumber: number): Promise<IssueMeta>;
  /** S1: full host-side snapshot (body + comments + Agent Brief) for audit/resume. */
  fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot>;
  /** S1: resident slice worktree from `base` (native createWorktree). */
  prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle>;
  /** S1: write the issue snapshot into the worktree (clean-room). */
  writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void>;
  /**
   * S2: one `sandbox.run()` for the whole-slice build worker (ADR 0026 — the only
   * agent step).
   *
   * #256 seam extension (DONE): the return is widened from `StepOutput` to
   * `StepOutput | StepResult`. The real Backend returns a {@link StepResult}
   * carrying the real per-step sandbox session id
   * (`RunResult.iterations.at(-1).sessionId`) alongside the structured output,
   * so the ledger records the true per-step session id (`resumeSession` truth)
   * instead of a shared run-level UUID. A bare {@link StepOutput} is still a
   * valid return (the fake Backends use it unchanged) → the runner falls back to
   * the run-level UUID. The runner normalises both shapes, so its control flow is
   * identical for fake and real Backends (#256 "控制流零改动").
   */
  runStep(
    spec: StepSpec,
    worktree: WorktreeHandle,
  ): Promise<StepOutput | StepResult>;
  /**
   * THE unified worker-dispatch seam (ADR 0026 / PRD #330 #331).
   *
   * Every productive single-slice worker step (current path: S2 coder, S7 ship;
   * legacy compatibility may still map reviewer specs) is
   * dispatched through this ONE method: the runner hands a {@link WorkerSpec}
   * (what to invoke, host, fresh|resume, soul, skill) + a {@link DispatchContext}
   * (worktree, stateDir, resumeSessionId, audit snapshot when present) and gets
   * back a discriminated {@link WorkerResult}, then routes by case. This replaces
   * the per-method seam (`runStep` / `resumeSession` / `push`) as the runner's
   * dispatch entry point.
   *
   * #331 PREFACTOR: this is a thin LEGACY WRAPPER. The runner ALWAYS dispatches
   * through the free function `dispatchWorker(backend, spec, ctx)` (runner.ts),
   * which calls THIS method when a backend implements it, else falls back to
   * `legacyDispatchWorker` — forwarding to the existing methods
   * (`runStep`/`resumeSession` for agent workers, `push` for the S7 ship worker),
   * so external behaviour is unchanged (regression green) and every existing fake
   * Backend keeps working without change. The real worker dispatch (invoke
   * `/tdd` / `/review` / `gstack-ship`) lands in #334/#336. The legacy methods
   * stay on the seam during the transition.
   *
   * OPTIONAL on the interface during the prefactor so the existing zero-container
   * fakes need no change; new tests inject a fake implementing it to assert the
   * dispatch SEQUENCE + each {@link WorkerSpec} (the #331 acceptance criterion).
   */
  dispatchWorker?(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult>;
  /** S7: push the resident slice branch (no PR, no merge). */
  push(worktree: WorktreeHandle): Promise<void>;
  /**
   * #256 (optional, ledger true-value): resolve a step's promptFile to its raw
   * CONTENT so the runner can hash the content (real anti-tampering audit)
   * instead of the file name. Returns `undefined` when the prompt cannot be
   * resolved (the runner then falls back to hashing the name).
   *
   * OPTIONAL so the zero-container fake Backends need no change: when absent the
   * runner keeps the v0.1 name-hash. The real Backend implements it by reading
   * the baked-in prompt file from disk.
   */
  readPromptContent?(promptFile: string): Promise<string | undefined>;
  /**
   * #256 (optional, ledger true-value): the worktree HEAD commit SHA
   * (`git rev-parse HEAD`) so the ledger's `branchHEAD` records the real SHA
   * instead of the branch name. Returns `undefined` when unavailable (the runner
   * then falls back to the branch name).
   *
   * OPTIONAL so the zero-container fake Backends need no change: when absent the
   * runner keeps the v0.1 branch-name value. codex#2 consistency check
   * (ledger.branchHEAD vs the live worktree HEAD) is built on this in the real
   * Backend.
   */
  worktreeHead?(worktree: WorktreeHandle): Promise<string | undefined>;
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

/**
 * Family-run context carried into a CHILD slice's single-slice runner (ADR 0022
 * decision 2: the RunnerOptions seam through which the family layer passes its
 * context down to the reused single-slice runner).
 *
 * When present, the child slice runs in FAMILY MODE — three differences from a
 * standalone single-slice run (ADR 0022 decision 2/6/7):
 *   - `familyBase` replaces "main" as the cut base (children cut from the LOCAL
 *     family base the merger accumulates onto — decision 7);
 *   - `noPush` makes S7 a LOCAL NO-OP (decision 2: a shared-clone concurrent
 *     remote push would clash on `.git/refs/remotes`; only the family base PRs
 *     once at the end);
 *   - `parentIssue` is the family run key (ADR 0024) the child reuses for its
 *     clone + the ledger口径 (decision 6③) — carried for #294/#298 to read.
 *
 * Absent ⇒ a normal standalone single-slice run (base=main, S7 pushes) — the
 * existing single-slice tests pass `RunInput` without this field, unchanged.
 */
export interface FamilyContext {
  /** The parent epic issue number (the family run key, ADR 0024). */
  readonly parentIssue: number;
  /** The local family base branch the child cuts from (ADR 0022 decision 7). */
  readonly familyBase: string;
  /** When true, S7 push is a LOCAL no-op (ADR 0022 decision 2). */
  readonly noPush: boolean;
  /**
   * #294 (ADR 0022 decision 6③): the child's `blocked_by` issue numbers the
   * family commander has confirmed MERGED into the family base (the ledger-merged
   *口径). In family mode the child's own single-slice S0 `blocked_by` gate treats
   * a still-open-on-GitHub blocker as SATISFIED iff it is in this set — because
   * the commander only fans a child out once every blocker is ledger-merged, but
   * the blocker's GitHub issue need not be `closed`. Without this, a child the
   * commander just released would be re-rejected by its own S0 ("blocked by #N
   * still open") → deadlock (agy R2's实锤 regression). A blocker NOT in this set
   * (e.g. an external dependency, never merged into the family base) is still a
   * genuine open blocker the S0 gate rejects. Absent/empty ⇒ no merged blockers
   * to excuse (the v0.1 GitHub-closed check applies unchanged).
   */
  readonly mergedBlockers?: ReadonlyArray<number>;
}

/** Input to the orchestrator: an issue number + the Backend seam (+ optional family context). */
export interface RunInput {
  readonly issueNumber: number;
  readonly backend: Backend;
  /**
   * Family-run context (ADR 0022 decision 2). Present ⇒ this is a CHILD slice of
   * a family run (family base + no-op push). Absent ⇒ a standalone single-slice
   * run (the v0.1 behaviour — base=main, S7 pushes).
   */
  readonly family?: FamilyContext;
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
