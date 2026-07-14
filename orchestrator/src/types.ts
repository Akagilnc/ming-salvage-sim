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
 * Keep these shared shapes stable: current runner, backends, and family flow all
 * depend on them.
 */

import type { FamilyModuleContext } from "./family/moduleDeclaration.js";
import type { ModelProviderFactory } from "./modelRegistry.js";
import type { ResolvedModelRoute } from "./modelRoutes.js";
import type { ProviderDegradationSummary, StopSummary } from "./stopSummary.js";

// ───────────────────────────── step identifiers ─────────────────────────────

/**
 * The child-slice step sequence (ADR 0030): the runner owns the visible
 * per-slice review/fix loop.
 *
 *   S0 gate → S1 context → S2 implement → S3 review → S4 classify
 *     → S7 local handoff when clean
 *     → S5 fix → S6 fresh full-diff review → S4 re-check while blocking remains
 *     → S8 handoff
 *
 * S2 and S5 are coder workers. S3 and S6 are fresh read-only reviewer workers.
 * S4 is the runner-owned ENVELOPE boundary (信封宪法, ADR 0062): it reads only the
 * blocking findings COUNT (0 → pass, non-0 → fix loop), never the finding content,
 * making per-round verdicts visible in the ledger instead of hiding the loop inside
 * one coder session.
 */
/** Executable child-slice topology. The runner routes only these steps. */
export type SliceStepId =
  | "S0"
  | "S1"
  | "S2"
  | "S3"
  | "S4"
  | "S5"
  | "S6"
  | "S7"
  | "S8";

/** Family endgame worker labels; these are not child-runner route steps. */
export type FamilyEndgameWorkerId =
  | "S9"
  | "S10"
  | "S11"
  | "S12";

/** Any durable worker/ledger label across the child and family machines. */
export type StepId = SliceStepId | FamilyEndgameWorkerId;

/**
 * Durable ledger rows normally identify a canonical orchestrator step.  Retry
 * bookkeeping deliberately occupies its own namespace so step-result readers
 * cannot mistake a pre-dispatch marker for that step's result (#824 r6).
 */
export type LedgerStepId = SliceStepId | "mechanical_redispatch_attempt";

export function isStepId(step: unknown): step is SliceStepId {
  return (
    step === "S0" ||
    step === "S1" ||
    step === "S2" ||
    step === "S3" ||
    step === "S4" ||
    step === "S5" ||
    step === "S6" ||
    step === "S7" ||
    step === "S8"
  );
}

/** Worker roles shared by child and family dispatch. */
export type StepRole =
  | "coder"
  | "reviewer"
  | "verify"
  | "fixer"
  | "cleanup"
  | "docRelease";

/** Terminal handoff status (ADR 0018 / PRD #244 route table). */
export type HandoffStatus = "success" | "escalate" | "error";

// ───────────────────────────── step spec ─────────────────────────────

/**
 * Soul identifier injected into the sandbox for a step.
 *
 * - `"coder"`: implementation/fix soul (TDD for S2, finding fix contract for S5).
 * - `"READ-ONLY"`: reviewer soul with READ-ONLY soft constraint baked in
 *   (prompt-level, not an OS-level mount — same image, separate `run()`).
 * - `"cmr"`: family integrated-cmr pass worker soul (ADR 0030) — review/outcome
 *   discipline for the selected CMR gate. Blocking findings return to the runner;
 *   a separate `"coder"` worker creates any persistent repair commits.
 * - `"ship"`: the delivery soul the family ship worker runs under — a WRITE soul
 *   distinct from `"coder"`: it invokes `gstack-ship`, stops at PR creation, and
 *   records deferred findings in a tracker (issue / TODOS.md), never the PR body.
 */
export type StepSoul =
  | "coder"
  | "READ-ONLY"
  | "cmr"
  | "ship"
  | "verify"
  | "fixer"
  | "cleanup"
  | "docRelease";

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
   * Route-selected slug resolved through the model registry.
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
   * v0.1: the runner does NOT enforce maxIter (lazy field on worker specs).
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
  /**
   * P0/P1 ⇒ always `fix_now`; P2/P3 reviewer judges fix_now vs accepted
   * suppression (`wont_fix` / `rejected`). Accepted suppressions must include
   * an `accepted_suppressed` disposition with source, scope, rationale, and
   * bounded reopen conditions.
   */
  readonly action: "fix_now" | "wont_fix" | "rejected";
  /** Required when action is `wont_fix` or `rejected`; optional otherwise. */
  readonly disposition_reason?: string;
  /** Machine-verifiable classification evidence for suppression outcomes. */
  readonly disposition?: FindingDispositionEvidence;
}

/**
 * The only disposition kind a reviewer/CMR soul may emit (#604 slice 4, ADR
 * 0062). The purely-routing kinds (`same_module` / `cross_module` /
 * `spec_conflict` / `infra_failure` / `owning_issue_still_red`) were removed:
 * the runner no longer reads a route field to decide a finding's fate.
 * `accepted_suppressed` remains as the governance carrier for accepted
 * suppression (source/scope/bounded reopen).
 */
export type FindingDispositionKind = "accepted_suppressed";

export interface FindingDispositionEvidence {
  readonly kind: FindingDispositionKind;
  /** Why this classification applies. Required for every disposition kind. */
  readonly reason: string;
  /** Required for accepted_suppressed. */
  readonly source?: string;
  /** Required for accepted_suppressed. */
  readonly scope?: string;
  /** Optional for accepted_suppressed; omitted values are derived from the finding. */
  readonly findingIdentity?: string;
  /** Required for accepted_suppressed bounded reopen. */
  readonly boundedReopen?: string;
}

export interface FindingDisposition {
  readonly identityKey: string;
  readonly status: "unrepaired" | "wont_fix" | "rejected" | "accepted_suppressed";
  readonly reason: string;
  readonly severity: Finding["severity"];
  readonly source?: string;
  readonly scope?: string;
  readonly boundedReopen?: string;
}

/** Fresh-review adjudication for a prior coder-fix worker's claimed-fixed finding. */
export interface PriorFindingDisposition {
  /** Stable key produced by `findingIdentityKey` for the prior claimed-fixed finding. */
  readonly identityKey: string;
  /**
   * ADR0030's explicit closure buckets; absence is never closure.
   * `accepted_suppressed` is terminal only when the reviewer supplies the
   * source/scope/bounded reopen fields below.
   */
  readonly status:
    | "still-active"
    | "verified-closed"
    | "unable-to-assess"
    | "accepted_suppressed";
  /** Optional reviewer rationale for audit/debugging. */
  readonly reason?: string;
  readonly source?: string;
  readonly scope?: string;
  readonly boundedReopen?: string;
}

/** Output of a coder step (S2/S5). 0 commits ⇒ committed:false (not a miss). */
/**
 * One finding the coder-fix worker legally refused (#677).
 * Prefer another repair; when a finding cannot be fixed without overturning a
 * ratified AC/assertion, refuse that identity, fix the others, commit, and
 * continue to fresh re-review — never a global escalate / decision-gate park.
 */
export interface ReviewFixRefuseRecord {
  readonly identityKey: string;
  readonly finding: string;
  readonly acceptanceCriterion: string;
  readonly conflictReason: string;
}

export interface CoderOutput {
  readonly kind: "coder";
  readonly committed: boolean;
  readonly commitsAdded: number;
  /**
   * #677 legal refuse: identity keys the coder-fix worker declined to adopt
   * (AC/assertion conflict). Valid with a commit that fixes the other findings;
   * runner threads these to S6 fresh re-review — not escalate/park.
   */
  readonly refusedFindingIdentityKeys?: ReadonlyArray<string>;
  /** #677 refuse detail records paired with {@link refusedFindingIdentityKeys}. */
  readonly refuseRecords?: ReadonlyArray<ReviewFixRefuseRecord>;
  /** Any agent step may signal it is stuck (route() reads this first). */
  readonly escalate?: Escalation;
}

/** Output of a reviewer step (S3/S6). `findings` is the reviewer's declared open-item cargo. */
export interface ReviewerOutput {
  readonly kind: "reviewer";
  readonly findings: ReadonlyArray<Finding>;
  readonly priorFindingDispositions?: ReadonlyArray<PriorFindingDisposition>;
  /** Any agent step may signal it is stuck (route() reads this first). */
  readonly escalate?: Escalation;
}

/** Worker-authored stuck signal. Transport metadata is not part of this contract. */
export interface Escalation {
  readonly reason: string;
  readonly diagnosis: string;
}

/** Escalation bucket recorded on a terminal S8 entry (#439). */
export type EscalationKind = "decision" | "failure";

/**
 * Append-only human answer event for a paused decision escalation (#439).
 *
 * Minimal JSONL shape for recording the answer:
 * `{ "step":"S4", "event":"escalation_answered", "forStep":"S4", "answer":"..." }`
 * If the answer means "continue fixing" after an S4 no-progress decision, it is
 * executable only when it also carries `findingIdentityKey` or a `findingScope`
 * that matches the active finding; unscoped continue answers stay paused rather
 * than guessing which finding to reopen.
 *
 * It intentionally remains a ledger row, not an edit to the prior S8 boundary.
 */
export interface EscalationAnswerPayload {
  readonly event: "escalation_answered";
  readonly forStep?: SliceStepId;
  /** Original parked worker session, when the answer reopens a decision gate. */
  readonly sessionId?: string;
  readonly answer: string;
  readonly note?: string;
  /** Source of the answer row when known; omitted on legacy rows. */
  readonly source?: "human" | "coordinator" | "peripheral" | "resume_input";
  /** Optional exact finding identity targeted by a run-state repair answer. */
  readonly findingIdentityKey?: string;
  /** Optional finding scope targeted by a run-state repair answer. */
  readonly findingScope?: FindingRepairScope;
}

export interface EscalationAnswerEvent extends EscalationAnswerPayload {
  readonly forStep: SliceStepId;
}

/** Scope carried by runner bookkeeping events that target active findings. */
export interface FindingRepairScope {
  /** Exact runner identity keys for the finding lineage, when available. */
  readonly identityKeys?: ReadonlyArray<string>;
  /** Broader path/location scope; only used when it maps to one active finding. */
  readonly locations?: ReadonlyArray<string>;
  /** Broader category scope; only used when it maps to one active finding. */
  readonly categories?: ReadonlyArray<string>;
  /** Optional durable grouping label from a review thread / finding group. */
  readonly findingGroup?: string;
  /** Optional review-context label from the coordinator. */
  readonly reviewContext?: string;
  /** Optional feature/module area label from the coordinator. */
  readonly featureArea?: string;
}

/**
 * Append-only runner bookkeeping event. It is ledger truth, but not reviewer
 * output and not a step adjudication.
 */
export interface ContinueFixingEvent {
  readonly event: "runner_bookkeeping";
  readonly intent: "continue_fixing";
  readonly findingIdentityKey?: string;
  readonly findingScope?: FindingRepairScope;
  readonly source: "human" | "coordinator" | "peripheral" | "resume_input";
  readonly ts: string;
  readonly reason?: string;
}

/**
 * #683 — idle-threshold quota probe hit a 429/limit wall. Step is parked for
 * quota reset (runner status escalate, not S8(error)). #686 forks this
 * disposition into park vs relay (three-tier rule, ADR 0125) when a live
 * baton exists. Same park family as `online_review_ci_pending`.
 * Shape mirrors {@link import("./quotaProbe.js").QuotaWaitForResetLedgerEvent}.
 */
export interface QuotaWaitForResetEvent {
  readonly event: "quota_wait_for_reset";
  /** Provider pool that returned 429 (`zai` / `opencode-go` / `grok` / `unknown`). */
  readonly pool: string;
  /** ISO-8601 reset instant when the 429 body carried one. */
  readonly resetAt?: string;
  readonly reason: string;
  readonly step?: SliceStepId;
  readonly workerPid?: number;
  readonly ts: string;
}

/**
 * #686 — baton handoff on a resource failure (quota wall / hang-with-live-pool /
 * self-reported blocked). `state_summary` is forwarded as the next baton's
 * parameter file (`.relay-focus.md`). Worktree drift is preserved (no reset).
 * Shape mirrors {@link import("./relayDispatch.js").RelayHandoffLedgerEvent}.
 */
export interface RelayBatonHandoffEvent {
  readonly event: "relay_baton_handoff";
  readonly trigger: string;
  readonly state_summary: string;
  readonly remaining?: string;
  readonly reason?: string;
  readonly fromModelId: string;
  readonly fromPool: string;
  readonly toModelId: string;
  readonly toPool: string;
  readonly step?: SliceStepId;
  readonly ts: string;
}

/**
 * #684 R2: spawn-time monitor handle bookkeeping — persisted AT SPAWN so hang
 * judge/kill/resume can rebuild the handle before the step completes.
 */
export interface WorkerMonitorSpawnedEvent {
  readonly event: "worker_monitor_spawned";
}

/**
 * #824 — durable mechanical-dispatch budget.  Written immediately before a
 * worker dispatch so a process crash cannot reset the bounded retry lifecycle
 * when the resident worktree is re-fed.
 */
export interface MechanicalRedispatchAttemptEvent {
  readonly event: "mechanical_redispatch_attempt";
  /** Canonical worker step whose current invocation owns this attempt. */
  readonly forStep: SliceStepId;
  readonly mechanicalRedispatchAttempt: number;
}

export interface RouteDegradedEvent {
  readonly event: "route_degraded";
  readonly droppedLeg: string;
  readonly reason: string;
}

export type LedgerBookkeepingEvent =
  | EscalationAnswerEvent
  | ContinueFixingEvent
  | QuotaWaitForResetEvent
  | RelayBatonHandoffEvent
  | WorkerMonitorSpawnedEvent
  | MechanicalRedispatchAttemptEvent
  | RouteDegradedEvent;

/**
 * The structured output of any worker step.
 *
 * ADR 0026 / PRD #330 [R2-b]: WIDENED from `CoderOutput | ReviewerOutput` to the
 * full {@link WorkerOutput} union (also carrying {@link ShipResult} /
 * {@link CmrResult} / {@link MergeWorkerResult}) so a ship/cmr/merge worker's
 * output can flow through the ledger ({@link LedgerEntry.output}) without a tsc
 * error. `StepOutput` is kept as the historical name (consumed by route/validate)
 * and is now an ALIAS of `WorkerOutput` — ONE union, no drift. Every consumer
 * narrows on `.kind`; route() acts only on coder/reviewer cases.
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
// is a WORKER dispatched through ONE seam, `dispatchWorker(spec, ctx)`. All call
// sites now route through it; the narrow legacy wrapper only supports older
// integrated-CMR review backends.

/**
 * Which kind of work a worker performs. Drives the {@link WorkerResult} payload
 * discriminant and the skill invoked:
 *   - `coder`    → invoke `/tdd` (S2 implement / S5 fix), resume across rounds.
 *   - `reviewer` → invoke `/code-review` (S3/S6 per-slice review), fresh each round.
 *   - `cmr`      → invoke `ak-cross-m-review` (family integrated cmr), fresh.
 *   - `ship`     → invoke `gstack-ship` for the family PR. Child S7 is a local handoff.
 *   - `merge`    → family-layer merge (may use NO skill — ADR 0026); B 段, no A-段
 *                  consumer (shape only).
 */
export type WorkerKind =
  | "coder"
  | "reviewer"
  | "cmr"
  | "ship"
  | "merge"
  | "verify"
  | "fixer"
  | "cleanup"
  | "docRelease";

/** Which container host runs the worker (decides skill-invocation mechanism). */
export type WorkerHost = "claude" | Exclude<ModelProviderFactory, "claudeCode">;

/**
 * The DISPATCH MODE for this worker invocation:
 *   - `fresh`  — a brand-new `sandbox.run()`. THE NORMAL CASE for every worker,
 *     including S2 implement and a normal S5 fix round.
 *   - `resume` — continue a PRIOR agent session via the Sandcastle-native
 *     `resumeSession` path (carrying {@link DispatchContext.resumeSessionId}).
 *
 * ADR 0026 INVARIANT (do not conflate with context retention): `resume` is the
 * CRASH/ESCALATE-resume path ONLY and pins maxIter to 1. A normal coder/fix
 * round must NOT use it (it keeps within-step maxIter). So a worker is `resume`
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
 *     INVARIANT is that a normal fix keeps maxIter, so it is NOT
 *     the `resume` (crash/escalate) dispatch path.
 *   - `clean`  — review workers (reviewer/cmr) start each round with clean eyes
 *     (cross-model independence; never re-checking their own prior findings).
 */
export type WorkerContextRetention = "retain" | "clean";

export interface WorkerCmrReviewLeg {
  readonly family: string;
  readonly slug: string;
  readonly optional?: true;
}

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
  /** Frozen route-selected CMR review legs for this worker invocation. */
  readonly cmrReviewLegs?: ReadonlyArray<WorkerCmrReviewLeg>;
  /** Soul to inject (`coder` full discipline / `READ-ONLY` reviewer). */
  readonly soul: StepSoul;
  /** Project tool-chain the image declares (US #29). */
  readonly toolchain: ReadonlyArray<ToolchainEntry>;
}

/**
 * The RICH landing payload the dispatch seam writes STRAIGHT to the worker's
 * landing file — deliberately SEPARATE from {@link DispatchContext} (信封宪法,
 * ADR 0062): finding free-text content (`claim_quote` / `suggested_fix`) must NOT
 * reside in the runner's dispatch structure. The runner never reads these fields
 * for a fate decision — it only搬运s them into the landing file the coder-fix
 * worker reads. DispatchContext keeps ONLY the identity keys + count.
 */
/** Cross-round finding family synthesis (#711). */
export interface FindingFamily {
  readonly family: string;
  readonly members: ReadonlyArray<string>;
  readonly recurringFromRounds: ReadonlyArray<number>;
  readonly brief: string;
}

/** Prior-round finding snapshot forwarded to judge workers (#711). */
export interface PriorRoundFindingSnapshot {
  readonly round: number;
  readonly fixMarkedFindingIdentityKeys: ReadonlyArray<string>;
  readonly findingDispositions?: ReadonlyArray<OnlineReviewFindingDisposition>;
  readonly blockingFindingIdentityKeys?: ReadonlyArray<string>;
}

/** Bot snapshot landing content for online review verify/fixer workers (#600). */
/** Per-finding judgment from the verify worker (#600): fix / reject / defer. */
export type OnlineReviewFindingAction = "fix" | "reject" | "defer";

export interface OnlineReviewFindingDisposition {
  readonly identityKey: string;
  readonly threadId: string;
  readonly action: OnlineReviewFindingAction;
  readonly reason?: string;
}

/** Evidence-bearing thread reply authored by the verify worker (#600 AC6). */
export interface OnlineReviewThreadReply {
  readonly threadId: string;
  readonly body: string;
}

/** Terminal states a verify worker may self-declare (#600 wire schema). */
export type VerifyWorkerTerminalState =
  | "mergeable"
  | "round_budget_exhausted"
  | "decision_gate_raised";

/** Runner-internal online review terminals (contract_drift retained for non-git protocol failures). */
export type OnlineReviewTerminalState =
  | VerifyWorkerTerminalState
  | "contract_drift";

export type OnlineReviewBotLegLanding =
  | { readonly state: "pending" }
  | { readonly state: "complete"; readonly findingCount: number }
  | { readonly state: "dropped"; readonly reason: string };

export interface OnlineReviewLandingSnapshot {
  readonly prUrl: string;
  readonly headOid: string;
  readonly totalFindingCount: number;
  readonly quiescent: boolean;
  /** Per-bot terminal/pending legs — dropped bots are not clean-silence evidence (#600). */
  readonly bots: Readonly<Record<string, OnlineReviewBotLegLanding>>;
  /** Convenience list of bot ids dropped after the overdue window. */
  readonly droppedBots: ReadonlyArray<string>;
  readonly threads: ReadonlyArray<{
    /** Top-level review-comment databaseId — REST reply parent. */
    readonly id: string;
    /** GraphQL reviewThread node id — resolution target. */
    readonly threadNodeId?: string;
    readonly path?: string;
    readonly line?: number;
    readonly body: string;
    readonly isResolved: boolean;
    /** Native commit_id when GitHub exposes it; undefined for artifact bots. */
    readonly headOid?: string;
    readonly authorLogin?: string;
  }>;
  /** Head-correlated CI check-runs for verify default-deny (#600 / ADR 0061). */
  readonly checkRuns: ReadonlyArray<{
    readonly id: number;
    readonly name: string;
    readonly headSha: string;
    readonly status: string;
    readonly conclusion?: string;
  }>;
  /**
   * How empty checkRuns is classified: offline="converged", live="pending"
   * (post-push race before checks appear — Cursor medium, verified).
   */
  readonly checkRunsEmptyMeans?: "converged" | "pending";
}

export interface WorkerLandingPayload {
  /**
   * S5 / family coder-fix worker only: the blocking reviewer findings (full
   * content) selected from the current full-diff review. The dispatch seam writes
   * them to the landing file; the runner does not read them.
   */
  readonly blockingFindings?: ReadonlyArray<Finding>;
  /**
   * S5 only: opaque pointers to the preceding reviewer's raw products when no
   * countable findings envelope was available. The runner transports these
   * facts; the fixer reads the artifacts and decides what they mean.
   */
  readonly rawReviewerArtifacts?: {
    readonly stdoutPath?: string;
    readonly sidecarPath?: string;
    readonly reviewerSessionId?: string;
    readonly statement: "the previous reviewer raw artifacts are here";
  };
  /** #677 mechanical signal; reviewer must trace the assertion to authority. */
  readonly preexistingAssertionTouched?: boolean;
  /**
   * #677 legal refuse keys from the prior S5 coder-fix commit — still-active
   * findings the fixer declined; fresh re-review must adjudicate them.
   */
  readonly refusedFindingIdentityKeys?: ReadonlyArray<string>;
  /** Family online review workers: paginated bot/thread snapshot. */
  readonly onlineReviewSnapshot?: OnlineReviewLandingSnapshot;
  /** Family PR delivery metadata threaded into the review loop. */
  readonly shipDelivery?: {
    readonly branch: string;
    readonly pr?: string;
    readonly prHead?: string;
    readonly status: string;
  };
  /** 1-based family online review round (runner-enforced cap). */
  readonly onlineReviewRound?: number;
  /** Family fixer: fix-marked finding identity keys from verify worker. */
  readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
  /**
   * Original review thread bound to each fixer-approved identity.
   * A key alone is not authority to close another thread that happens to claim
   * the same identity.
   */
  readonly fixMarkedFindingThreads?: ReadonlyArray<{
    readonly identityKey: string;
    readonly threadId: string;
  }>;
  /** Prior family online-review rounds from ledger (#711). */
  readonly priorRoundFindings?: ReadonlyArray<PriorRoundFindingSnapshot>;
  /** Family fixer / child S5 coder-fix: pattern briefs from prior judge worker. */
  readonly findingFamilies?: ReadonlyArray<FindingFamily>;
  /** Family cleanup: host-computed close set + durable pr_merged record. */
  readonly cleanupDispatch?: {
    readonly coveredIssues: ReadonlyArray<number>;
    readonly parentIssue?: number;
    readonly prUrl: string;
    readonly prNumber: number;
    readonly remoteBranchName: string;
    readonly mergedHeadOid: string;
    readonly convergedHeadOid: string;
  };
}

/**
 * Everything (besides the {@link WorkerSpec} and the rich {@link
 * WorkerLandingPayload}) the dispatch seam needs to run a worker — PRD #330 [H]:
 * the inputs are part of the contract. Per the信封宪法 (ADR 0062) this THIN
 * control envelope carries only identity keys + counts + opaque搬运 payloads
 * (human answer, runner-observed gate failures) — never finding free-text content.
 */
export interface DispatchContext {
  /**
   * Ephemeral identity for one invocation of the orchestrator runner. Unlike
   * `stateDir`, this is freshly minted on every run, including a same-issue
   * resume against the same durable ledger.
   */
  readonly runId?: string;
  /** The immutable route selected for this run, including its smoke records. */
  readonly modelRoute?: ResolvedModelRoute;
  /**
   * The resident child worktree (ADR 0017 commit truth). MANDATORY for
   * child coder/reviewer workers; OPTIONAL for family-level
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
  /** Durable telemetry/log directory, outside Sandcastle's ephemeral worktrees. */
  readonly telemetryDir?: string;
  /**
   * The prior agent session id to resume — present ONLY for a `session:"resume"`
   * dispatch, i.e. the CRASH/ESCALATE-resume path where the runner re-opens a
   * recorded agent session. Normal S2/S3/S5/S6 runner-visible work is
   * `session:"fresh"` and does NOT carry this (codex cmr R3/R4 finding: normal
   * work must not take the crash/escalate resume path).
   */
  readonly resumeSessionId?: string;
  /**
   * Host-written issue snapshot for audit/resume compatibility. Current workers
   * live-fetch issue truth via gh using runner-injected issue/repo env; this is
   * not the execution source of truth.
   */
  readonly issueSnapshot?: IssueSnapshot;
  /**
   * S5 / family coder-fix worker only: the stable identity keys of the blocking
   * findings selected from the current full-diff review. This THIN identity list —
   * plus {@link blockingFindingCount} — is all the runner threads through its
   * dispatch structure; the rich finding CONTENT travels separately in {@link
   * WorkerLandingPayload} straight to the landing file (信封宪法, ADR 0062).
   * Suppression/reopen logic matches findings by normalized identity, not object
   * text, so the keys are the runner's control-envelope carrier.
   */
  readonly blockingFindingIdentityKeys?: ReadonlyArray<string>;
  /**
   * The number of blocking findings this coder-fix dispatch carries — the runner's
   * count signal (信封宪法: identity keys + 计数). The findings themselves are in the
   * separate {@link WorkerLandingPayload}, never on this dispatch structure.
   */
  readonly blockingFindingCount?: number;
  /** #677 runner fact only, never a content verdict. */
  readonly preexistingAssertionTouched?: boolean;
  /**
   * #677 legal refuse keys from S5 — thin identity list for S6 re-review
   * (runner does not park; fresh reviewer adjudicates still-active refuses).
   */
  readonly refusedFindingIdentityKeys?: ReadonlyArray<string>;
  /**
   * FAMILY CMR coder-fix retry only: runner-observed repair-evidence gate failures
   * from earlier attempts for the SAME blocking finding set. Fresh retry workers
   * receive this instead of relying on hidden session memory.
   */
  readonly repairAttemptFailures?: ReadonlyArray<{
    readonly attempt: number;
    readonly reason: string;
    readonly familyHeadBefore?: string;
    readonly familyHeadAfter?: string;
  }>;
  /**
   * S5 coder-fix or family-level CMR/ship worker: the human answer that
   * reopened a prior decision-escalate pause (#439). The runner passes it to the
   * re-dispatched worker so the resume instruction is visible without deleting or
   * rewriting the terminal ledger row that paused the run.
   */
  readonly escalationAnswer?: EscalationAnswerPayload;
  /**
   * FAMILY worker only: the parent/family issue whose live GitHub context should be
   * available to clean family workers. The family runner still passes structured
   * CMR findings separately; this number only lets prompts fetch current issue
   * prose when needed.
   */
  readonly familyIssue?: number;
  /**
   * FAMILY cmr worker only: the child issue numbers whose merge into the family
   * base was LLM-resolved (#295) — forwarded to the integrated cmr 承重闸 so it
   * focuses on the merges a machine touched (PRD #330 / #291 缺口 1). Undefined for
   * child workers and for a conflict-free family run.
   */
  readonly llmResolvedChildren?: ReadonlyArray<number>;
  /**
   * FAMILY cmr worker only: which integrated CMR pass this worker is running.
   * `completeness` is the step5 gate; `correctness` is the step6 gate and must be
   * dispatched only after completeness passes.
   */
  readonly cmrPass?: "completeness" | "correctness";
  /** FAMILY cmr worker only: parsed module declarations supplied by the runner. */
  readonly moduleContext?: FamilyModuleContext;
  /**
   * FAMILY cmr worker only: runner-owned prior finding identity keys that the
   * worker is allowed to adjudicate as claimed-fixed. A worker may not invent
   * closure keys outside this protected set.
   */
  readonly priorCmrFindingIdentityKeys?: ReadonlyArray<string>;
  /** Family online review: opened PR URL. */
  readonly prUrl?: string;
  /** Family online review: verified PR head OID/SHA. */
  readonly prHead?: string;
  /** GitHub `owner/repo` for gh api polling. */
  readonly repo?: string;
  /** 1-based online review round — runner enforces MAX_ONLINE_REVIEW_ROUNDS (#600). */
  readonly onlineReviewRound?: number;
  /**
   * Judge workers only: prior-round finding snapshots extracted from ledger (#711).
   * Runner-owned data — not used for routing decisions.
   */
  readonly priorRoundFindings?: ReadonlyArray<PriorRoundFindingSnapshot>;
  /**
   * #686 — billing pool for this dispatch (ADR 0124). Selects the real
   * provider/CLI channel when the same model lives on multiple pools.
   */
  readonly billingPool?: string;
  /**
   * #686 — absolute path to `.relay-focus.md` when a baton handoff is in force.
   * Mirrors `.cmr-focus.md` / `.ship-focus.md`: runner writes the parameter file;
   * the worker prompt reads it when present.
   */
  readonly relayFocusPath?: string;
}

/** A coder worker's output — the existing {@link CoderOutput}. */
export type CoderResult = CoderOutput;

/**
 * Per-slice reviewer worker output. ADR 0030 keeps review/fix convergence
 * runner-visible: reviewer workers return structured findings so the S4 envelope
 * boundary can count blocking findings (信封宪法, ADR 0062) rather than a bare verdict.
 */
export type ReviewerResult = ReviewerOutput;

/**
 * A family integrated-cmr worker's output (#335/#449). The runner routes only
 * the worker's self-reported findings count; all other reviewer fields are cargo.
 */
export interface CmrResult {
  readonly kind: "cmr";
  /** Which integrated CMR pass produced this verdict, when known. */
  readonly cmrPass?: "completeness" | "correctness";
  /** Optional reviewer cargo; routing comes only from findingsCount. */
  readonly converged?: boolean;
  /** Why it did not converge — set when red (handed to escalate). */
  readonly reason?: string;
  /** CMR leg slugs that actually produced a usable review this pass. */
  readonly successfulLegs?: readonly string[];
  /** Declared CMR legs skipped at runtime, with the visible degrade flag reason. */
  readonly skippedLegs?: readonly CmrSkippedLeg[];
  /** Prior claimed-fixed finding cargo reported by the integrated CMR worker. */
  readonly claimedFixedFindingIdentityKeys?: readonly string[];
  /** Explicit closure disposition for claimed-fixed integrated CMR findings. */
  readonly priorFindingDispositions?: readonly PriorFindingDisposition[];
  /** Structured CMR findings passed through as worker cargo. */
  readonly findings?: readonly Finding[];
  /** Reviewer-declared count. Structured finding rows never supply it. */
  readonly findingsCount?: number;
  /** Cross-round grouped findings + recurring-class markers (#711). */
  readonly findingFamilies?: readonly FindingFamily[];
  /** Reviewer-referenced evidence artifact pointers transported as cargo. */
  readonly evidencePaths?: readonly string[];
  // NOTE: a STUCK cmr worker is the WorkerResult-level `{kind:"escalated"}` case,
  // NOT an `escalate` field on this `completed` payload (codex cmr R3b finding: a
  // payload-level escalate would be silently ignored by the verifyCmr consumer,
  // which reads `converged`). `completed` means the worker ran to completion.
}

export interface CmrSkippedLeg {
  readonly slug: string;
  readonly reason: string;
}

/**
 * A family ship worker's output (#336). `gstack-ship` does more than
 * push+PR (merge-base / tests / review gate / VERSION / CHANGELOG + STOP/HITL);
 * the non-success routing is a #336 concern — the SHAPE is fixed here.
 */
export interface ShipResult {
  readonly kind: "ship";
  /** The shipped branch. */
  readonly branch: string;
  /** The opened PR URL/handle (undefined when ship stopped before a PR). */
  readonly pr?: string;
  /** The PR head commit SHA/OID verified by the host, when available. */
  readonly prHead?: string;
  /** A short status string (e.g. "pushed" | "pr_opened"). Values: #336. */
  readonly status: string;
  /** Nonblocking ship-side review degradation metadata, if gstack-ship reports it. */
  readonly degradedReviews?: ReadonlyArray<ProviderDegradationSummary>;
  // NOTE: a ship worker that STOPS for a human (gstack-ship STOP/HITL) is the
  // WorkerResult-level `{kind:"escalated"}` case (PRD #330 R2), NOT an `escalate`
  // field on this `completed` payload — a `completed ShipResult` means a PR opened
  // / push landed. (codex cmr R3b: a payload-level escalate would be ignored by
  // the family-ship consumer, which routes a completed ship to success.)
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

/**
 * Online review verify worker output (#600). The verify worker owns per-finding
 * fix / reject / defer judgment; the runner applies GitHub side effects and only
 * counts findings (0 / non-0) for routing — it does not interpret finding content.
 */
export interface VerifyResult {
  readonly kind: "verify";
  /** Bot/online review converged (green) ⇒ the fix loop can stop. */
  readonly converged: boolean;
  /** Per-finding dispositions judged by the verify worker. */
  readonly findingDispositions?: ReadonlyArray<OnlineReviewFindingDisposition>;
  /**
   * Identity keys carried through as data for the verify worker to use when
   * reporting which fix-marked findings it evaluated.
   */
  readonly fixMarkedFindingIdentityKeys?: ReadonlyArray<string>;
  /** Evidence-bearing replies for reject/defer/fixed outcomes (#600 AC6). */
  readonly threadReplies?: ReadonlyArray<OnlineReviewThreadReply>;
  /** Thread IDs to resolve only after a fresh re-check confirms the fix. */
  readonly threadsToResolve?: ReadonlyArray<string>;
  /** Tracked issue URLs created for deferred findings (runner-populated). */
  readonly deferredIssueUrls?: ReadonlyArray<string>;
  /** Documented terminal state when the loop ends (#600 AC1/AC5). */
  readonly terminalState?: VerifyWorkerTerminalState;
  /** True when this verify dispatch is a post-fixer fresh re-check (ADR 0061). */
  readonly isRecheck?: boolean;
  /** Cross-round grouped findings + recurring-class markers (#711). */
  readonly findingFamilies?: ReadonlyArray<FindingFamily>;
}

/**
 * Family post-review fixer worker output (#596).
 */
export interface FixerResult {
  readonly kind: "fixer";
  /** Whether the fixer produced commits for the requested repairs. */
  readonly committed: boolean;
  /**
   * When `committed` is false: assigned fix-marked findings are already resolved
   * on the current branch (e.g. a prior crashed attempt landed the fix).
   * The stage proceeds to verify using {@link fixCommitSha}, not decision_gate.
   */
  readonly alreadySatisfied?: boolean;
  /**
   * Fixing commit SHA from the fixer envelope. Required when {@link committed} is
   * true (new fix this turn) or when {@link alreadySatisfied} is true. Runner/stage
   * never re-read live git for this value (ADR 0030).
   */
  readonly fixCommitSha?: string;
}

/** Per-step branch-delete outcome recorded by the #603 cleanup worker. */
export type CleanupBranchOutcome =
  | "deleted"
  | "already_gone"
  | "skipped_tip_drift"
  | "skipped_pr_not_merged"
  | "skipped_precondition";

/**
 * Post-merge cleanup worker output (#603). Distinguishes terminal vs retryable
 * outcomes so the host reclaim gate can read ledger truth without trusting a
 * worker self-report.
 */
export interface CleanupResult {
  readonly kind: "cleanup";
  /** False ⇒ mechanical retry may re-dispatch; true ⇒ no further cleanup attempts. */
  readonly terminal: boolean;
  /** True when remote acts completed or were verified N/A under live checks. */
  readonly ok: boolean;
  readonly issuesClosed?: ReadonlyArray<number>;
  readonly parentIssueClosed?: boolean;
  readonly branchOutcome?: CleanupBranchOutcome;
  readonly skippedReasons?: ReadonlyArray<string>;
}

/**
 * 文档发布 worker output (#735 / S12). Thin schema only: skill success
 * (including 文档发布空跑) → `released:true`; crash / hang / skill fail /
 * required push fail → `released:false`. Tip continues via ledger `branchHEAD`.
 * Offline/test may still synthesize a green stub under the offline hatch only.
 */
export interface DocReleaseResult {
  readonly kind: "docRelease";
  /**
   * Whether 文档发布 finished successfully (true includes empty-run; false
   * blocks auto-merge).
   */
  readonly released: boolean;
}

/** The structured payload a worker produces — one per {@link WorkerKind}. */
export type WorkerOutput =
  | CoderResult
  | ReviewerResult
  | CmrResult
  | ShipResult
  | MergeWorkerResult
  | VerifyResult
  | FixerResult
  | CleanupResult
  | DocReleaseResult;

/**
 * The result of dispatching ONE worker — a discriminated union so the runner can
 * route by case without ever receiving an undefined shape (PRD #330 [B]).
 *
 *   - `completed` — the worker ran and produced its structured `output`. NOTE a
 *     cmr `red` verdict is `completed` (with payload), NOT `failed` (PRD #330
 *     R2): `red` is a normal review outcome the runner routes on.
 *   - `failed`    — the worker crashed / its command or tests hard-failed
 *     (no usable output).
 *   - `escalated` — the worker (model-judged) signalled it is stuck and a human
 *     must answer (carries the resume指引). Crash/timeout/missing-skill map to
 *     `failed`; only a MODEL escalate is `escalated`.
 *
 * The legacy wrapper yields `completed` by forwarding the older methods' returns;
 * unified real workers additionally mint process `failed` and worker-declared
 * `escalated` results.
 */
export type WorkerResult =
  | { readonly kind: "completed"; readonly output: WorkerOutput; readonly sessionId?: string }
  | { readonly kind: "failed"; readonly reason: string; readonly sessionId?: string }
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
  /**
   * Issue body when the S0 fetch included it (#767 Coder-Rec). Optional so
   * lightweight fakes / older callers stay valid; when present the runner
   * parses the design-time `Coder-Rec:` marking before dispatch.
   */
  readonly body?: string;
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
  /** Login of the issue-body author, when the host snapshot carried it. */
  readonly bodyAuthorLogin?: string;
  readonly comments: ReadonlyArray<string>;
  /** Author login aligned by index with `comments`, when available. */
  readonly commentAuthorLogins?: ReadonlyArray<string>;
  /** Repo owner login used to authenticate executable issue instructions. */
  readonly trustedOwnerLogin?: string;
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
  readonly step: LedgerStepId;
  /** Structured output for agent steps; undefined for runner-action steps. */
  readonly output?: StepOutput;
  /**
   * Per-step sandbox session id (#604 correctness r5, E2). The runner records the
   * agent step's surfaced session id here on the IN-MEMORY ledger too — not just on
   * the {@link PersistentLedgerEntry} written to disk — so an in-memory
   * `RunResult.stepLedger` consumer (the family runner reading a parked child's
   * escalated agent step, `readChildDecisionEscalation`) can forward the real
   * session id for 原地 resume. Absent for runner-action steps and when the
   * provider surfaced no id. {@link PersistentLedgerEntry.sessionId} REQUIRES a
   * value (run-level UUID fallback); this in-memory field carries it only when the
   * provider actually surfaced one.
   */
  readonly sessionId?: string;
  /** Append-only event marker for non-step ledger facts (#439 / #446 / #683). */
  readonly event?: LedgerBookkeepingEvent["event"];
  /** #824 — absolute per-step mechanical dispatch attempt number. */
  readonly mechanicalRedispatchAttempt?: number;
  /**
   * #683 — quota pool id on `quota_wait_for_reset` rows (ledger-visible).
   * Typed as string so JSONL round-trips stay schema-light; see
   * {@link QuotaWaitForResetEvent.pool}.
   */
  readonly pool?: string;
  /** #683 — ISO reset instant on `quota_wait_for_reset` when known. */
  readonly resetAt?: string;
  /** #683 — worker pid preserved while waiting for quota reset. */
  readonly workerPid?: number;
  /** #686 — relay handoff state_summary (next baton parameter). */
  readonly state_summary?: string;
  /** #686 — relay handoff remaining work hint. */
  readonly remaining?: string;
  /** #686 — relay from/to model + pool (ledger-visible strings). */
  readonly fromModelId?: string;
  readonly fromPool?: string;
  readonly toModelId?: string;
  readonly toPool?: string;
  /** #686 — relay handoff trigger discriminant. */
  readonly trigger?: string;
  /** Step this answer reopens when `event === "escalation_answered"` (#439). */
  readonly forStep?: SliceStepId;
  /** Human answer payload when `event === "escalation_answered"` (#439). */
  readonly answer?: string;
  /** Optional human note attached to an escalation answer (#439). */
  readonly note?: string;
  /** Runner repair intent when `event === "runner_bookkeeping"` (#446). */
  readonly intent?: ContinueFixingEvent["intent"];
  /** Exact finding identity targeted by a continue-fixing bookkeeping event. */
  readonly findingIdentityKey?: string;
  /** Active finding scope targeted by a continue-fixing bookkeeping event. */
  readonly findingScope?: FindingRepairScope;
  /** Source of a bookkeeping event, when recorded. */
  readonly source?: EscalationAnswerPayload["source"];
  /** Timestamp for a bookkeeping event, when recorded. */
  readonly ts?: string;
  /** Optional reason for a bookkeeping event. */
  readonly reason?: string;
  /** Optional CMR route leg removed after smoke failure. */
  readonly droppedLeg?: string;
  /**
   * ADR0030 finding dispositions persisted at the S4 review/fix boundary.
   *
   * S4 is the durable review/fix boundary. Persisting dispositions here lets a
   * resumed run replay accepted suppressions and bounded severity reopens instead
   * of re-deriving them from only the last reviewer payload. Governance data
   * (accepted suppression), not a runner content-classification (信封宪法, ADR 0062).
   */
  readonly findingDispositions?: ReadonlyArray<FindingDisposition>;
  /** Runner-owned terminal stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
  /**
   * Monitor handle for an in-flight external CLI worker (#684). Persisted so a
   * resumed run can rebuild alive/idle/kill judgment without global pgrep.
   */
  readonly monitorHandle?: WorkerMonitorHandle;
}

/**
 * Structured monitor handle produced atomically at CLI worker dispatch (#684).
 * Alive/idle/kill operations must use this handle — never global process-name matching.
 */
export interface WorkerMonitorHandle {
  readonly pid: number;
  readonly logPath: string;
  /** Byte offset where this dispatch began appending to the shared step log. */
  readonly logStartOffset?: number;
  /** Pool / route identity (e.g. `grok/composer`, `zai/glm-5.2`). */
  readonly poolId: string;
  readonly completionSignal: string;
  readonly stepId: string;
  readonly dispatchedAt: string;
  /**
   * OS-level process start identity (e.g. `ps -o lstart=`) captured at spawn.
   * Resume/kill must verify the live PID still matches this identity before any
   * signal — otherwise a recycled PID would kill an unrelated process (#684 R1).
   */
  readonly instanceId: string;
  /** Dispatch-scoped result sidecar; absent only on legacy persisted handles. */
  readonly resultPath?: string;
}

/**
 * Host-side CLI spawn input for the production monitored-dispatch path (#684).
 * When a backend returns this from {@link Backend.resolveCliMonitorDispatch},
 * the runner free function {@link dispatchWorkerWithMonitor} spawns via
 * `dispatchMonitoredCliWorker` so the monitor handle is atomic with dispatch.
 */
export interface CliMonitorSpawnSpec {
  readonly command: string;
  readonly args: readonly string[];
  readonly logDir: string;
  readonly poolId: string;
  readonly completionSignal: string;
  readonly stepId: string;
  readonly cwd?: string;
  readonly env?: NodeJS.ProcessEnv;
  readonly logBasename?: string;
  /** Dispatch-scoped result sidecar written by the host bridge. */
  readonly resultPath?: string;
  /** Injectable process identity reader for restricted/test environments. */
  readonly readInstanceId?: (pid: number) => string | undefined;
}

/** #683: the monitor asks the backend to probe before it owns hang-kill. */
export type MonitoredWorkerIdleDisposition =
  | "hang"
  | "hang_with_live_pool"
  | "wait_for_reset";

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
  /** Runner invocation identity; shared by this run's ledger rows. */
  readonly runId?: string;
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
  /**
   * Distinguishes answerable decision pauses from true terminal failure
   * escalations (#439). Set only with `handoffStatus:"escalate"` on S8.
   */
  readonly escalationKind?: EscalationKind;
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
 * reuse the worktree, preserve uncommitted residue as work product, and
 * continue on the existing scene; only terminal-success GC removes worktrees.
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
 * injected interface — read issue, prepare worktree, run an agent step.
 * #247 injects a fake; the real Backend (Sandcastle + gh + git) is verified
 * separately. Keep this minimal and stable — 9 slices layer on it.
 */
export interface Backend {
  /** Resolve the durable sidecar directory for a worker dispatch, when available. */
  resolveTelemetryDir?(ctx: DispatchContext): string | undefined;
  /** Run the real model×pipe bash smoke and return the route with fresh records. */
  smokeModelRoute(
    route: ResolvedModelRoute,
    currentCliVersions?: Readonly<Record<string, string | undefined>>,
    billingPool?: string,
    relaySmokeEntryKey?: string,
  ): Promise<ResolvedModelRoute>;
  currentCliVersions?(
    route: ResolvedModelRoute,
    billingPool?: string,
    relaySmokeEntryKey?: string,
  ): Promise<Readonly<Record<string, string | undefined>>>;
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
   * ADR 0030: resume re-opens the recorded agent step when a human answered an
   * escalation. Normal per-slice review/fix rounds are runner-visible fresh
   * dispatches; S4 findings are delivered to S5 through DispatchContext.
   */
  resumeSession(
    spec: StepSpec,
    worktree: WorktreeHandle,
    sessionId: string,
    options?: AgentStepRunOptions,
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
   * S2/S3/S5/S6: one `sandbox.run()` per runner-visible agent worker.
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
    options?: AgentStepRunOptions,
  ): Promise<StepOutput | StepResult>;
  /**
   * THE unified worker-dispatch seam (ADR 0026 / PRD #330 #331).
   *
   * Every productive child-slice worker step (S2/S3/S5/S6) is
   * dispatched through this ONE method: the runner hands a {@link WorkerSpec}
   * (what to invoke, host, fresh|resume, soul, skill) + a {@link DispatchContext}
   * (worktree, stateDir, resumeSessionId, audit snapshot when present) and gets
   * back a discriminated {@link WorkerResult}, then routes by case. This replaces
   * the per-method seam (`runStep` / `resumeSession`) as the runner's
   * dispatch entry point.
   *
   * The runner dispatches through the free function
   * `dispatchWorker(backend, spec, ctx)` (runner.ts), which calls THIS method when
   * implemented and otherwise falls back to `legacyDispatchWorker`. The fallback
   * only forwards older child coder/reviewer methods (`runStep`/`resumeSession`);
   * production backends invoke the routed worker skills through this unified seam.
   *
   * The method remains optional so zero-container and older fake Backends can use
   * the forwarding fallback unchanged.
   */
  dispatchWorker?(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult>;
  /**
   * #786 optional: reinstall this backend's image / souls / prompts fingerprints
   * into the process-level telemetry run environment immediately before a
   * dispatch stamps its once-per-ledger environment row. Required when more than
   * one backend is constructed in-process (familyDriver: RealBackend then
   * RealFamilyBackend) so child legs do not inherit the later family promptHash.
   *
   * Fail-open at the call site — must not throw into dispatch control flow.
   */
  installTelemetryRunEnvironment?(): void | Promise<void>;
  /**
   * #684 optional: when a worker runs as a host-side CLI process (opencode /
   * grok / …), return the spawn input. The production
   * {@link dispatchWorkerWithMonitor} path then uses `dispatchMonitoredCliWorker`
   * so the monitor handle is generated atomically with real dispatch and can be
   * persisted on the ledger for resume rebuild.
   *
   * Absent / returns undefined ⇒ container/legacy path (no CLI monitor handle).
   */
  resolveCliMonitorDispatch?(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): CliMonitorSpawnSpec | undefined;
  /**
   * #684: map a finished monitored CLI child into a {@link WorkerResult}.
   * Required when {@link resolveCliMonitorDispatch} returns a spawn spec.
   */
  awaitMonitoredCliWorker?(
    handle: WorkerMonitorHandle,
    exitCode: number | null,
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult>;
  /**
   * #683: called while the monitored worker is still alive at the idle threshold.
   * A backend may throw its quota-park error; returning `hang` leaves verified
   * pid-tree kill exclusively to the monitor.
   */
  handleMonitoredWorkerIdle?(
    handle: WorkerMonitorHandle,
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<MonitoredWorkerIdleDisposition>;
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
   * runner keeps the v0.1 branch-name value.
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

/** Runner-owned S5 findings file made visible inside the worker sandbox. */
export interface FixFindingsLandingFile {
  /** Host path to the runner-owned JSON file. */
  readonly path: string;
  /** Path where the worker sees the file inside the sandbox repo. */
  readonly sandboxPath: string;
}

/** Runner-owned worker outcome sidecar made visible inside the worker sandbox. */
export interface WorkerOutcomeLandingFile {
  /** Host path to the runner-owned JSON file. */
  readonly path: string;
  /** Path where the worker sees the file inside the sandbox repo. */
  readonly sandboxPath: string;
}

/** Optional agent-step execution metadata consumed by real sandboxes. */
export interface AgentStepRunOptions {
  readonly fixFindingsLanding?: FixFindingsLandingFile;
  readonly fixFocusLanding?: FixFindingsLandingFile;
  readonly outcomeLanding?: WorkerOutcomeLandingFile;
  /**
   * #686 / ADR 0124 — billing pool for this dispatch. Selects the real
   * provider/CLI channel when the same model lives on multiple pools.
   */
  readonly billingPool?: string;
  /** Durable relay brief for any baton role (coder, ship, or review). */
  readonly relayFocusPath?: string;
}

// ──────────────────────────── run result ────────────────────────────

/**
 * Family-run context carried into a CHILD slice's runner (ADR 0022
 * decision 2: the RunnerOptions seam through which the family layer passes its
 * context down to the reused child runner).
 *
 * Every child slice runs in FAMILY MODE. The family layer supplies the local
 * base and parent key through this context:
 *   - `familyBase` replaces "main" as the cut base (children cut from the LOCAL
 *     family base the merger accumulates onto — decision 7);
 *   - `parentIssue` is the family run key (ADR 0024) the child reuses for its
 *     clone + the ledger口径 (decision 6③) — carried for #294/#298 to read.
 *
 * S7 always hands the local child commit back to the family merger. Only the
 * family base is shipped after integrated verification.
 */
export interface FamilyContext {
  /** The parent epic issue number (the family run key, ADR 0024). */
  readonly parentIssue: number;
  /** The local family base branch the child cuts from (ADR 0022 decision 7). */
  readonly familyBase: string;
  /**
   * #294 (ADR 0022 decision 6③): the child's `blocked_by` issue numbers the
   * family commander has confirmed MERGED into the family base (the ledger-merged
   *口径). The child's own S0 `blocked_by` gate treats
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

/** Internal child-runner input. Production family calls always supply family context. */
export interface RunInput {
  readonly issueNumber: number;
  readonly backend: Backend;
  /**
   * Current invocation repair intent. This has higher priority than durable
   * ledger bookkeeping when resuming a paused S4 decision escalation.
   */
  readonly repairIntent?: ContinueFixingEvent;
  /**
   * Family-run context (ADR 0022 decision 2). Production supplies it for every
   * child. Absence is retained only for focused S0–S8 skeleton tests; S7 still
   * performs a local handoff and never ships.
   */
  readonly family?: FamilyContext;
  /**
   * #686 / #909 — optional route pool table override for park-vs-relay at the
   * #683 disposition point. When present, the table is authoritative. When
   * absent, wall-hit pool is `limited` and other pools stay not-live unless
   * route-smoke proves them live ({@link knownLiveBillingPoolsFromRoute}) —
   * production path without test-only injection. Unknown/unprobed state still
   * must not fabricate live batons.
   */
  readonly relayPools?: ReadonlyArray<{
    readonly id: string;
    readonly status: "live" | "limited" | "dead";
    readonly resetAt?: Date;
    readonly parkThresholdMs: number;
    readonly models: ReadonlyArray<string>;
  }>;
  /**
   * #686 — optional clock for park-vs-relay threshold tests (within T / beyond T).
   * Production leaves this unset (wall clock).
   */
  readonly now?: () => Date;
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
  /** The reviewed local slice branch handed to the family merger on success. */
  readonly branch?: string;
  /**
   * Diagnostic error payload — set when status=error (#252).
   * Undefined for success and escalate outcomes.
   */
  readonly errorPackage?: ErrorPackage;
  /** The step ledger — anti-skip + resume truth. */
  readonly stepLedger: ReadonlyArray<LedgerEntry>;
  /** Unified run-level stop reason summary (#450). */
  readonly stopSummary: StopSummary;
}
