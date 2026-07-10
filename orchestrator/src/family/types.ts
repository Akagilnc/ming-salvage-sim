/**
 * Family integration-layer domain types (ADR 0022, #293).
 *
 * The family layer sits ABOVE the single-slice runner (ADR 0017/0018): it takes
 * a parent epic whose child slices were ALREADY cut (native sub-issues +
 * explicit blocked_by) by an external `to-issues` step, schedules them in
 * dependency waves, fans each child out through the existing single-slice
 * `runOrchestrator`, then serially merges the reviewed child branches into a
 * local FAMILY BASE.
 *
 * #293 ships the thinnest spine plus FOUR independent extension seams
 * (commander / merger / family-ledger / verify-cmr). Keep these shapes stable —
 * #294–#298 fill behaviour in, not re-shape these.
 */

import type {
  Backend,
  CleanupResult,
  DispatchContext,
  Escalation,
  EscalationAnswerPayload,
  EscalationKind,
  Finding,
  FindingDisposition,
  PriorFindingDisposition,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
} from "../types.js";
import type {
  AcceptedSuppressionSource,
  FamilyModuleContext,
  SourcedModuleDeclaration,
} from "./moduleDeclaration.js";
import type {
  VerifyCmrInput,
  VerifyCmrPhase,
  VerifyCmrResult,
} from "./verifyCmr.js";
import type { StopSummary } from "../stopSummary.js";

/** The two runner-visible integrated CMR gates (#419). */
export type IntegratedCmrPass = "completeness" | "correctness";

// ─────────────────────────── child slice ───────────────────────────

/**
 * One already-cut child slice of the parent epic (ADR 0022 decision 1).
 *
 * The cutting (epic → vertical-slice sub-issues with explicit `blockedBy`) is an
 * EXTERNAL `to-issues` responsibility — the commander never decomposes an epic;
 * it only READS these descriptors and the explicit dependency edges. So this is
 * the minimal descriptor the commander needs: the child's own issue number and
 * the issue numbers it is blocked by.
 */
export interface ChildSlice {
  /** The child slice's own GitHub issue number. */
  readonly issue: number;
  /**
   * Issue numbers this child is `blocked_by` (the explicit native dependency
   * edges). A child is schedulable once EVERY blocker is merged into the family
   * base. #293 reads these as the single source of truth — no LLM inference.
   */
  readonly blockedBy: ReadonlyArray<number>;
  /** Structured module declaration parsed from the child issue body (#449). */
  readonly moduleDeclaration?: SourcedModuleDeclaration;
}

/**
 * The parent epic fed to the family entry point (ADR 0022 decision 6①).
 *
 * Unlike a single slice, an epic HAS sub-issues — the family S0 gate accepts it
 * (reversing the single-slice "no sub-issues" rule). The `children` are the
 * already-cut descriptors the commander schedules.
 */
export interface FamilyEpic {
  /** The parent epic's GitHub issue number — also the family run key (ADR 0024). */
  readonly issue: number;
  /** The already-cut child slices (native sub-issues + explicit blocked_by). */
  readonly children: ReadonlyArray<ChildSlice>;
  /** Structured module declaration parsed from the parent/family issue body (#449). */
  readonly moduleDeclaration?: SourcedModuleDeclaration;
  /** Children excluded at production admission before scheduling, kept for summary audit. */
  readonly admissionSkipped?: ReadonlyArray<FamilyAdmissionSkippedChild>;
}

export interface FamilyAdmissionSkippedChild {
  readonly issue: number;
  readonly reason: string;
  readonly message: string;
}

// ─────────────────────────── family ledger ───────────────────────────

/**
 * One append-only family-ledger event (ADR 0022 decision 5).
 *
 * #293 recorded only the minimal `{childIssue, status:"merged"}` per merged
 * child. #298 widens the schema to the FULL event (childBranch / childHead /
 * wave / familyHeadBefore / familyHeadAfter) + the `"aborted"` status (verify /
 * cmr failure, carrying the family head at the time) + the `"reconciled"` event
 * tag (a crash-window補账条). All #298 fields are OPTIONAL so #293's thin write
 * — `{childIssue, status:"merged"}` — remains a valid entry (back-compatible).
 *
 * INVARIANT KEPT BY THE UNBLOCK PREDICATE: the commander's unblock check (ADR
 * 0022 decision 6②) reads `status === "merged"` ONLY. A reconcile補账条 carries
 * `status:"merged"` (so it COUNTS as merged — decision 5 / codex R3:補成
 * `status:"reconciled"` would死锁) and is distinguished from a live merge by the
 * separate `event: "reconciled"` tag — NOT by the `status` field. So `mergedSet`
 * filters on `status`, and the reconcile tag rides alongside it without changing
 * the unblock truth.
 */
export interface FamilyLedgerEntry {
  /**
   * The child slice issue number this event is about — for `merged` /
   * `reconciled` events (a per-child merge). OPTIONAL because a PHASE-LEVEL
   * `aborted` event (#291 缺口 2) is a verify/cmr failure of a whole PHASE, not a
   * single child, so it carries NO `childIssue` (it carries `phase` instead). The
   * unblock predicate `mergedSet` only reads `childIssue` on `status:"merged"`
   * entries, which always supply it, so optionality never weakens the merged truth.
   */
  readonly childIssue?: number;
  /**
   * Merge status — the UNBLOCK-PREDICATE field (ADR 0022 decision 6②).
   *   - `"merged"`  — the child's branch is merged into the family base (a live
   *     merge OR a reconcile補账条; both COUNT as merged).
   *   - `"aborted"` — a verify/cmr barrier failed; this PHASE-LEVEL event carries
   *     the family head at the time (`familyHeadAfter`) + the `phase` + a `reason`
   *     for triage (#291 缺口 2). NOT counted as merged.
   *   - `"shipped"` — the family ship (止于-PR) SUCCEEDED (online review r2,
   *     codex P1). A PHASE-LEVEL marker carrying the family `pr` URL and the
   *     covered `familyHeadAfter`. As of #596 it is INTERMEDIATE, not terminal:
   *     the spine skips re-run only when a matching `"review_loop_converged"`
   *     marker exists for the current head. NOT counted as merged (no `childIssue`).
   *   - `"review_loop_converged"` — the TERMINAL family review-loop marker (#596).
   *     Written after the shipped PR has passed the online review/PR-check loop.
   *     The spine's resume guard reads it so only a fully-converged HEAD skips
   *     re-verify / re-cmr / re-ship / re-loop. NOT counted as merged.
   *   - `"pr_merged"` — the TERMINAL family auto-merge marker (#602). Written
   *     after live GitHub confirms the PR merged at the converged head. NOT
   *     counted as merged (no `childIssue`).
   *   - `"post_merge_cleanup"` — the TERMINAL post-merge cleanup marker (#603).
   *     Written after live verify+act cleanup succeeds. NOT counted as merged.
  *   - `"cmr_reviewed"` — a PHASE-LEVEL audit event recording one red integrated
 *     CMR review outcome before the runner dispatches coder-fix (#550). NOT
 *     counted as merged.
 *   - `"cmr_fix_committed"` — a PHASE-LEVEL audit event recording the separate
 *     coder-fix worker's independent commit for a CMR finding (#550). NOT counted
 *     as merged.
 *   - `"cmr_passed"` — a PHASE-LEVEL audit event recording one green integrated
 *     CMR pass (#419). NOT counted as merged.
   *   - `"escalated"` — a PHASE-LEVEL family pause/failure marker (#439). Decision
   *     escalations are answerable by a later append-only `escalation_answered`
   *     row; failure escalations are terminal until human/manual repair outside
   *     this runner. NOT counted as merged.
   *   - `"child_decision_parked"` — (#604 slice 5) a CHILD-LEVEL decision-gate PARK:
   *     a child slice hit a product/design题 (`escalationKind:"decision"`) and parked
   *     the family awaiting a human answer. INDEPENDENT of the family's own A-class
   *     `"escalated"` row so the human decision gate (park → resume) stays distinct
   *     from infra escalation/failure. Carries `childIssue` so multiple children can
   *     park + be resumed separately; answered by a later `escalation_answered` row
   *     that ALSO carries the matching `childIssue`. NOT counted as merged.
   *   - `"escalation_answered"` — a PHASE-LEVEL append-only human answer event
   *     (#439). It reopens a prior decision escalation without editing/deleting
   *     that prior row. NOT counted as merged.
   *   - `"admission_skipped"` — production admission skipped a child before wave
   *     scheduling; durable audit only, not an unblock fact.
   */
  readonly status:
    | "merged"
    | "aborted"
    | "shipped"
    | "review_loop_converged"
    | "pr_merged"
    | "post_merge_cleanup"
    | "cmr_reviewed"
    | "cmr_fix_committed"
    | "cmr_passed"
    | "escalated"
    | "child_decision_parked"
    | "escalation_answered"
    | "admission_skipped"
    | "online_review_fix_committed"
    | "online_review_round_retrigger";
  /**
   * Event tag.
   *   - `"reconciled"` — a crash-window補账条 (decision 5); carries
   *     `status:"merged"` so the unblock predicate counts it (codex R3), the tag is
   *     for audit. Set ONLY by reconcile.
   *   - `"aborted"` — a PHASE-LEVEL verify/cmr-failure durable entry (#291 缺口 2),
   *     paired with `status:"aborted"`; written by the verify-cmr hook so the abort
   *     reaches the durable ledger reconcile reads (not just the in-memory seam).
   *   - `"shipped"` — the family ship succeeded (online review r2, codex P1),
   *     paired with `status:"shipped"`; written by the verify-cmr hook at the
   *     止于-PR success. As of #596 this is an INTERMEDIATE marker; the terminal
   *     resume guard looks for `"review_loop_converged"`.
   *   - `"review_loop_converged"` — paired with `status:"review_loop_converged"`;
   *     the terminal marker written after the online review/PR-check loop converged
   *     (#596).
   *   - `"pr_merged"` — paired with `status:"pr_merged"`; the terminal marker
   *     written after live GitHub confirms the PR merged (#602).
   *   - `"post_merge_cleanup"` — paired with `status:"post_merge_cleanup"`;
   *     the terminal marker written after post-merge verify+act cleanup (#603).
   *   - `"cmr_reviewed"` — paired with `status:"cmr_reviewed"`; records a red
   *     reviewer outcome before the runner sends it to coder-fix (#550).
   *   - `"cmr_fix_committed"` — paired with `status:"cmr_fix_committed"`; records
   *     the separate coder-fix worker commit before fresh re-review (#550).
   *   - `"cmr_passed"` — paired with `status:"cmr_passed"`; records the pass
   *     verdict so step5 and step6 are visible in the family ledger (#419).
   *   - `"escalated"` — paired with `status:"escalated"`; records the family
   *     escalation bucket (#439).
   *   - `"child_decision_parked"` — paired with `status:"child_decision_parked"`;
   *     records a child-level decision gate that parked the family (#604 slice 5).
   *   - `"escalation_answered"` — paired with `status:"escalation_answered"`; an
   *     append-only human answer to a prior decision escalation/park (#439). When it
   *     carries a `childIssue` it answers a `child_decision_parked` row (#604 slice 5).
   *   - `"admission_skipped"` — paired with `status:"admission_skipped"`; records
   *     production admission skips before scheduling.
   * Not the unblock truth (that is `status`); the tag is for observability.
   */
  readonly event?:
    | "reconciled"
    | "aborted"
    | "shipped"
    | "review_loop_converged"
    | "pr_merged"
    | "post_merge_cleanup"
    | "cmr_reviewed"
    | "cmr_fix_committed"
    | "cmr_passed"
    | "escalated"
    | "child_decision_parked"
    | "escalation_answered"
    | "admission_skipped"
    | "online_review_fix_committed"
    | "online_review_round_retrigger";
  /**
   * Which phase this PHASE-LEVEL event belongs to. Set on `aborted` entries and
   * on `cmr_passed` audit entries; `merged` / `reconciled` entries omit it because
   * they are per-child, not per-phase.
   */
  readonly phase?: "wave" | "final";
  /** Which integrated CMR pass this phase-level audit/failure event belongs to. */
  readonly cmrPass?: IntegratedCmrPass;
  /**
   * Human-readable phase-level reason. `aborted` rows use it for verify/cmr
   * failures; `escalated` rows use it for answerable family decision pauses.
   */
  readonly reason?: string;
  /** Admission-skip diagnostic message, when status/event is admission_skipped. */
  readonly message?: string;
  /** The child branch that was merged (full schema, #298). */
  readonly childBranch?: string;
  /** The child branch HEAD commit that was merged (the ancestor reconcile checks). */
  readonly childHead?: string;
  /** The wave number this child was scheduled in (#294's wave numbering). */
  readonly wave?: number;
  /** The family base HEAD BEFORE this child's merge. */
  readonly familyHeadBefore?: string;
  /**
   * The family base HEAD AFTER this child's merge, at barrier failure, at CMR
   * review/fix audit time, or at the time a `cmr_passed` audit row's pass reviewed
   * the base.
   */
  readonly familyHeadAfter?: string;
  /**
   * The resolved model route fingerprint for a green `cmr_passed` audit row.
   * Resume may skip a CMR pass only when both the reviewed family HEAD and the
   * active worker/reviewer route match; old rows without this fail closed.
   */
  readonly routeFingerprint?: string;
  /**
   * The THIN control envelope the runner reads on `cmr_reviewed` / `aborted`
   * rows (#604 slice 3 / ADR 0062): the identity keys of the CURRENT blocking
   * findings (deduped). The runner is a pure scheduler — it reads this key list
   * and NOTHING else off a CMR row. It replaces the former fat
   * `cmrFindingClassification` blob (Finding full text + results[] audit +
   * dispositions[]), which leaked finding CONTENT the runner must never read.
   * Also stored on `cmr_fix_committed` rows so crash-resume can protect the same
   * keys in the next fresh CMR pass. A `not_converged` sentinel row carries `[]`
   * (defined-but-empty), preserving its "no pending keys" short-circuit.
   */
  readonly blockingFindingIdentityKeys?: readonly string[];
  /**
   * The governance side-channel the CMR GATE (not the runner) reads to track
   * cross-round prior dispositions (#604 slice 3 / ADR 0062). Carries the
   * accepted-suppression / owning-issue dispositions the classifier
   * produced this pass, so a later pass can honour a prior accepted suppression
   * without re-blocking. Split out of the old `cmrFindingClassification` blob so
   * the runner's control envelope (`blockingFindingIdentityKeys`) and the gate's
   * governance data live in separate, purpose-scoped fields.
   */
  readonly cmrDispositions?: readonly FindingDisposition[];
  /**
   * Did this child's merge get LLM-resolved (the `resolving-merge-conflicts` soul
   * ran, #295) rather than land as a clean deterministic merge? Forwarded by the
   * merger from {@link MergeResult.conflictResolvedByLlm} onto the DURABLE ledger
   * entry (#291 缺口 1), so the integrated cmr 承重闸 — which after a context
   * compaction reads only the ledger, not in-memory state — can see WHICH children
   * a machine touched its merge of (decision 3②/3⑥ "不静默吞"). Absent/`false` ⇒ a
   * clean deterministic merge. Only set on `status:"merged"` live-merge entries; a
   * reconcile補账条 / `aborted` event omits it.
   */
  readonly conflictResolvedByLlm?: boolean;
  /**
   * The family PR URL — ONLY on a `status:"shipped"` terminal entry (online review
   * r2, codex P1). Records WHICH PR the terminal 止于-PR ship opened, so the resume
   * guard's "already delivered" decision is locatable from the ledger alone.
   */
  readonly pr?: string;
  /** PR number on `status:"pr_merged"` terminal entries (#602). */
  readonly prNumber?: number;
  /** Remote branch name on `status:"pr_merged"` terminal entries (#602). */
  readonly remoteBranchName?: string;
  /** Merged head OID on `status:"pr_merged"` terminal entries (#602). */
  readonly mergedHeadOid?: string;
  /** Cleanup worker output on `status:"post_merge_cleanup"` entries (#603). */
  readonly cleanupOutput?: CleanupResult;
  /** Decision pauses can be reopened by an answer row; failure escalations cannot. */
  readonly escalationKind?: "decision" | "failure";
  /**
   * The child Escalation diagnosis on a `child_decision_parked` row (#604 slice 5) —
   * the product/design context the human needs to answer. `reason` carries the
   * short escalation reason; `diagnosis` the longer explanation.
   */
  readonly diagnosis?: string;
  /**
   * The escalated child's single-slice worker session id on a `child_decision_parked`
   * row (#604 slice 5), forwarded so a later resume re-enters the SAME session
   * (原地 resume, ADR 0062 退出-重入). Absent when the child provider surfaced no id.
   */
  readonly sessionId?: string;
  /** Human answer payload when `event === "escalation_answered"` (#439). */
  readonly answer?: string;
  /** Required executable source for answer rows. */
  readonly source?: "human" | "resume_input" | "coordinator" | "peripheral";
  /** Optional human note attached to an escalation answer (#439). */
  readonly note?: string;
  /** Unified run-level/family-level stop reason summary (#450). */
  readonly stopSummary?: StopSummary;
  /** ISO-8601 instant when this ledger row was written (#600 r9 round-1 trigger truth). */
  readonly ts?: string;
  /** Online review round re-trigger marker (#600 r26): anchored PR head OID. */
  readonly roundTriggerHeadOid?: string;
  /** Online review round re-trigger marker (#600 r26): ISO instant the round began. */
  readonly roundTriggerAt?: string;
  /** Online review loop round (#600 r26): 1-based round at fix/retrigger time. */
  readonly onlineReviewRound?: number;
  /**
   * Fix-marked finding identity keys from the verify that drove an
   * `online_review_fix_committed` marker (#711 prior-round synthesis source).
   * Family online-review does not persist S9 verify rows; these keys on fix
   * markers are the durable prior-round data for resume.
   */
  readonly fixMarkedFindingIdentityKeys?: readonly string[];
}

// ─────────────────────────── reconcile git seam ───────────────────────────

/**
 * The git seam crash-window reconcile (ADR 0022 decision 5, #298) reaches git
 * through — injected so {@link reconcileFamilyLedger} is verifiable zero-container
 * (a fake scripts live HEAD / childHead existence / ancestor results; no real git,
 * no killed process). The RealBackend implements it with `git rev-parse` +
 * `git rev-parse --verify <branch>` + `git merge-base --is-ancestor`.
 */
export interface ReconcileGit {
  /** The live family-base HEAD commit SHA right now (`git rev-parse <familyBase>`). */
  liveFamilyHead(): Promise<string>;
  /**
   * The family-base HEAD commit SHA BEFORE any child merged — the head the family
   * base was at when the run was set up (the RealBackend records it at family-base
   * creation; in git terms the point the family base branch was cut at). This is
   * the ONLY baseline available when the ledger is EMPTY: if the very first merge
   * landed but its `merged` write crashed (the merger lands the merge THEN writes
   * the ledger), the ledger is empty yet the live HEAD has moved PAST this start
   * head. Comparing live HEAD to the start head distinguishes a genuine fresh
   * start (live === start → clean) from a first-merge crash window (live moved,
   * empty ledger → fail-closed escalate; cmr R3: codex-s1) — without it an empty
   * ledger would unconditionally clean-start and re-merge the already-landed first
   * child (a double-merge).
   */
  familyBaseStartHead(): Promise<string>;
  /**
   * Whether a child's branch/HEAD exists in the clone, and if so its HEAD SHA.
   * `exists:false` ⇒ the run crashed before that child produced ANY commit
   * (branch absent) → reconcile treats it as never-merged, reruns it (no error).
   */
  childHeadExists(
    childIssue: number,
    childBranch?: string,
  ): Promise<{ exists: boolean; childHead?: string }>;
  /**
   * `git merge-base --is-ancestor <childHead> <liveHead>` — true iff the child's
   * merge ALREADY landed on the live family base (so reconcile补账 instead of
   * re-merging — no double-merge).
   */
  isAncestor(childHead: string, liveHead: string): Promise<boolean>;
}

/**
 * The plan {@link reconcileFamilyLedger} produces from the ledger + live HEAD
 * (ADR 0022 decision 5). The spine acts on it BEFORE continuing the wave loop.
 */
export interface ReconcilePlan {
  /**
   * Fail-closed (branch ③): the live HEAD is inconsistent with the ledger末条
   * (diverged / behind / unrelated — neither equal nor a descendant). The spine
   * must escalate (return to the caller for a human) rather than guess.
   */
  readonly escalate: boolean;
  /**
   * The crash-window补账条 to append (branch ②): children whose merge LANDED
   * (ancestor-confirmed) but whose `merged` write crashed. Each is appended as a
   * `status:"merged"` + `event:"reconciled"` ledger entry (so the unblock
   * predicate counts it — codex R3) and is NOT re-merged (no double-merge).
   */
  readonly reconciled: ReadonlyArray<{ childIssue: number; childHead: string }>;
  /**
   * The VERIFIED live family-base HEAD this plan was computed against. The spine
   * stamps the LAST reconcile補账条 with `familyHeadAfter: liveHead` (only the
   * last — the append loop is itself a crash window, so the intermediate補账条
   * omit the head; cmr R2: agy), so a SUBSEQUENT clean resume's `lastRecordedHead`
   * advances to the post-reconcile head rather than the stale pre-crash baseline
   * (cmr R1: codex + agy), while a mid-append-loop crash falls back to the prior
   * real baseline and branch ② re-reconciles the remainder idempotently. Without
   * `liveHead`, `lastRecordedHead` would keep returning the old baseline after a
   * crash-then-reconcile, and a later rewind/divergence that branch ③ must
   * fail-closed escalate would be silently trusted (the補账条 doc in `reconcile.ts`
   * lastRecordedHead promises "reconcile補账条 carry one too" — this is the value
   * the baseline-advancing last entry carries).
   */
  readonly liveHead: string;
  /**
   * The full merged set AFTER reconcile = ledger-merged ∪ reconciled. The wave
   * loop selects from this, so an already-merged / reconciled child is skipped
   * (no double-merge) and a never-merged child (childHead absent / not an
   * ancestor) is re-run (no漏合).
   */
  readonly merged: ReadonlySet<number>;
}

// ─────────────────────────── family backend seam ───────────────────────────

/**
 * THE family seam (parallel to the single-slice {@link Backend}): the family
 * spine reaches the outside world (git merge into the family base, the verify
 * hook) only through this injected interface, so the whole spine is verifiable
 * with a zero-container fake (沿用 runner.happy-path / merge-seam 测试形态).
 *
 * It does NOT subsume the single-slice {@link Backend} — each child fan-out runs
 * the existing single-slice runner with its OWN {@link Backend}. This seam is
 * only for the family-LEVEL actions the merger / verify-cmr modules perform.
 */
export interface FamilyBackend {
  /**
   * merger seam (ADR 0022 decision 3②, #295 extends): serially merge a reviewed
   * child branch into the family base with `git merge --no-ff`. #293 handles
   * only the no-conflict path; #295 adds the conflict fallback by extending THIS
   * method's implementation (or wrapping it), not the spine.
   *
   * Returns the family base HEAD after the merge (so the ledger / next wave's
   * cut can reference it). The fake returns a synthetic head.
   */
  mergeChildIntoFamilyBase(child: MergeRequest): Promise<MergeResult>;
  /**
   * merger CONFLICT-fallback seam (ADR 0022 decision 3② "冲突才上 LLM", #295).
   *
   * Invoked by the merger ONLY when {@link mergeChildIntoFamilyBase} reports a
   * conflict ({@link MergeResult.conflicted}) — the "确定性优先、仅冲突上 LLM"
   * inversion of Sandcastle's native "一上来就整段 LLM" merge. The real Backend
   * starts ONE agent under the `merger` soul + the `resolving-merge-conflicts`
   * skill, scoped to THIS one in-progress conflicting merge: it resolves each
   * hunk (preserving both intents where possible; never inventing behaviour;
   * never `--abort`), stages, and commits the merge — leaving the resolved result
   * on the family base for the downstream family verify + integrated cmr (#296)
   * to审 ("不静默吞"). The fake injects a synthetic resolved head.
   *
   * Returns the family base HEAD after the LLM-resolved merge commit lands. If the
   * resolver CANNOT resolve (it throws / rejects, OR returns a still-`conflicted`
   * result), the merger does NOT write a `merged` ledger entry — an unresolved
   * conflict must never look clean.
   *
   * OPTIONAL: a #293-era backend (the no-op default, the existing zero-container
   * fakes) does not implement it — it is reached ONLY on the conflict path, which
   * those backends never take. If a conflict IS hit on a backend without this
   * method, the merger fails loud (throws a descriptive error) rather than writing
   * a `merged` ledger entry — the conflict is surfaced, never swallowed. (Same
   * optional-capability pattern the sibling verify-cmr seams use, so existing
   * fakes need no throwing stub.)
   */
  resolveMergeConflict?(req: ConflictResolveRequest): Promise<MergeResult>;
  /**
   * family-ledger seam (ADR 0022 decision 5, #298 extends): append one event to
   * the append-only family ledger (a sibling of the family base worktree, OUTSIDE
   * it). #293 writes only the thin entry; #298 extends the entry + adds reconcile.
   */
  appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void>;
  /**
   * family-ledger read seam: the current append-only ledger contents, in write
   * order. The commander's unblock predicate reads the merged set from here.
   */
  readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>>;
  /**
   * Live family-base HEAD read seam. CMR workers may commit fixes before returning
   * converged, so pass markers and later pass resume checks need the post-worker
   * HEAD, not just the pre-pass head supplied by the spine.
   */
  readFamilyHead?(familyBase: string): Promise<string>;
  /** Live checked-out worktree HEAD read seam after a family worker returns. */
  readFamilyCurrentHead?(): Promise<string>;
  /**
   * Live tracked worktree status read seam. Reviewer workers must not leave
   * tracked edits behind even when HEAD is unchanged.
   */
  readFamilyTrackedStatus?(familyBase: string): Promise<readonly string[]>;
  /**
   * THE unified worker-dispatch seam at the FAMILY layer (ADR 0026 / PRD #330
   * #331) — parallel to {@link Backend.dispatchWorker}. The family-LEVEL worker
   * steps (integrated cmr over the merged family base, the family-base ship/PR)
   * are dispatched through this ONE method instead of the per-method seam
   * (`runIntegratedCmr` / `openFamilyPr`).
   *
   * The {@link DispatchContext} for a family worker carries `familyBase` (the
   * caller has only the base string, no single-slice worktree path — PRD #330 R2);
   * `worktree` is optional / backend-inferred. The {@link WorkerResult} is the
   * same discriminated union: a cmr `red` verdict is `completed` (with a
   * {@link CmrResult} payload), NOT `failed`.
   *
   * #331 PREFACTOR: the runner's family verify-cmr hook ALWAYS dispatches through
   * the free function `dispatchFamilyWorker(familyBackend, spec, ctx)`
   * (verifyCmr.ts), which calls THIS method when implemented, else forwards to the
   * legacy `runIntegratedCmr` / `openFamilyPr` — external behaviour unchanged. The
   * real container cmr worker (#335) and family ship worker land later.
   *
   * OPTIONAL during the prefactor so the existing fakes need no change; new tests
   * inject it to assert the family dispatch sequence + spec.
   */
  dispatchWorker?(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult>;
  /**
   * Runner fallback for outcome protocol failures (#552).
   *
   * When a worker finished but its outcome control envelope was malformed,
   * missing, or schema-incompatible, the runner may ask the SAME producing worker
   * to rewrite only the machine outcome from existing artifacts/local memory.
   * This is a control-envelope repair path: it must not run semantic review/fix
   * work, move git truth, leave tracked changes, or infer a route from prose. The
   * runner owns the bounded retry cap.
   */
  rewriteWorkerOutcome?(
    spec: WorkerSpec,
    ctx: DispatchContext,
    protocolFailure: Extract<WorkerResult, { kind: "malformed" }>,
    attempt: number,
  ): Promise<WorkerResult>;

  // ─── #296 verify-cmr seam capabilities (ADR 0022 decision 3④/⑤/⑥/4) ───────
  // ALL OPTIONAL: a #293-era backend (the no-op default, the existing fakes)
  // does NOT implement them, so the verify-cmr hook degrades to the no-op
  // `{ok:true, ran:false}` and the spine's existing default path is untouched.
  // The verify-cmr module ({@link runVerifyCmr}) reaches these off the
  // `familyBackend` it is handed by the frozen spine input `{phase, familyBase,
  // familyBackend}`; a RealBackend supplies them (run typecheck+tests in the
  // family base / dispatch the integrated cmr / open the PR / record the
  // aborted+escalate events).

  /**
   * #296 verify seam (ADR 0022 decision 3④/⑤): run the family verify (typecheck
   * + unit tests; the FULL suite on the `"final"` phase) against the family base.
   * The verify-cmr hook fails-fast on `{ok:false}` at the wave barrier. Reads the
   * `phase` so a RealBackend can scope the wave verify vs the end-of-run 全量
   * verify. NOT塞进 LLM prompt — a deterministic command run (decision 3⑤).
   */
  runFamilyVerify?(request: FamilyVerifyRequest): Promise<FamilyVerifyResult>;
  /**
   * #296 integrated-cmr seam (ADR 0022 decision 3⑥): run the integrated
   * cross-model cmr 承重闸 over the merged family base AFTER a green full verify,
   * to catch 跨片接缝 (field-name / type / 阈值口径 / 组合 e2e) that per-slice cmr
   * cannot see. `{converged:false}` is the load-bearing red — the hook escalates
   * 续跑 (#298) rather than opening a PR. Mechanically reuses the local
   * `ak-cross-m-review` pipeline (a薄封装 behind this seam).
   */
  runIntegratedCmr?(request: IntegratedCmrRequest): Promise<IntegratedCmrResult>;
  /**
   * #296 止于 PR seam (ADR 0022 decision 4): after a green verify + converged
   * cmr, open the family-base PR and STOP — the family orchestrator's autonomy
   * ends here. Online bot cmr + merge to main are the separate pr-review-loop
   * stage, NOT this layer (so this seam never merges).
   */
  openFamilyPr?(request: OpenFamilyPrRequest): Promise<OpenFamilyPrResult>;
  /**
   * Resume-skip trust boundary: before a durable `shipped` marker can skip the
   * final verify/cmr/ship barrier, re-check that the recorded PR still exists,
   * is OPEN, targets the expected PR base, uses this family branch as head, and
   * has `headRefOid === expectedHead`.
   */
  verifyFamilyShippedPr?(
    request: VerifyFamilyShippedPrRequest,
  ): Promise<VerifyFamilyShippedPrResult>;
  /**
   * Absolute git working directory for the family base clone. Optional — used to
   * compute `docReleasePaths` for diagnostics only (ADR 0123 / #735). Missing
   * working-repo does not block merge: path allowlist is not a merge gate.
   * `allowUnverifiedDocReleasePaths` is a deprecated no-op retained for caller
   * type-compat (see autoMerge.ts); merge still requires readiness + doc-release
   * completed, independent of this field.
   */
  resolveFamilyWorkingRepo?(): string | undefined;
  /**
   * #298-OWNED aborted-event seam — #296 only CALLS it. A red verify writes an
   * `aborted` event (携带错误包 + the family base at the time) so a failed wave is
   * NOT silently dropped (decision 3④/5 "不静默吞"). The CONCRETE ledger schema
   * widening (`FamilyLedgerEntry.status` → `"aborted"` + the event fields) is
   * #298's (decision 5 "字段级 JSON 留 TDD"); #296 depends on this minimal method
   * existing. Optional ⇒ a backend without it just skips the abort record (the
   * `{ok:false}` the spine acts on still fails-fast).
   */
  recordAborted?(event: FamilyAbortedEvent): Promise<void>;
  /**
   * #298-OWNED escalate seam. A NOT-converged integrated cmr or family ship
   * HITL (decision 3⑥/4) records a decision escalation in the append-only family
   * ledger. A later `escalation_answered` row reopens the family runner; without
   * that answer the runner stays paused. Optional ⇒ a backend without it surfaces
   * the red purely via the returned `{ok:false}`.
   */
  escalateFamily?(escalation: FamilyEscalation): Promise<void>;
  /**
   * #603 host-side family clone reclamation at terminal post-merge cleanup success.
   * Optional — fakes omit it. Caller must verify ledger terminal+ok first.
   */
  reapFamilyHost?(familyBase: string): Promise<void>;
}

// ─────────────────────────── #296 verify-cmr I/O ───────────────────────────

/** What the family verify needs: which phase, and the family base to verify. */
export interface FamilyVerifyRequest {
  /** Wave barrier (decision 3④, fail-fast) vs end-of-run 全量 (decision 3⑤). */
  readonly phase: "wave" | "final";
  /** The family base branch verify runs against. */
  readonly familyBase: string;
}

/** The family verify outcome (typecheck + tests). */
export interface FamilyVerifyResult {
  /** Green ⇒ true. A red `ok:false` fails-fast the wave / gates the final cmr. */
  readonly ok: boolean;
  /**
   * The error package on a red verify — handed to the `aborted` ledger event so
   * the failure is locatable without re-running (decision 3④/5).
   */
  readonly errorPackage?: FamilyVerifyErrorPackage;
}

/** Diagnostic payload for a red family verify (decision 3④/5). */
export interface FamilyVerifyErrorPackage {
  /** Human-readable reason (e.g. the failing tsc / vitest summary). */
  readonly reason: string;
}

/** What the integrated cmr needs: the merged family base to review. */
export interface IntegratedCmrRequest {
  /** The merged family base branch the integrated cmr reviews. */
  readonly familyBase: string;
  /** Which runner-visible CMR pass this request is for (#419). */
  readonly cmrPass?: IntegratedCmrPass;
  /**
   * The child issue numbers whose merge into the family base was LLM-resolved
   * (`conflictResolvedByLlm:true` in the family ledger, #295). The spine derives
   * this from the durable ledger BEFORE the final-phase integrated cmr (#291 缺口
   * 1) so the 承机闸 can focus its cross-slice review on the merges a machine
   * touched ("不静默吞" — an LLM-resolved merge is never silently shipped). OMITTED
   * (not `[]`) when no child was LLM-resolved, so a conflict-free run's request is
   * the back-compatible `{familyBase}`-only shape.
   */
  readonly llmResolvedChildren?: readonly number[];
  /** Human answer that reopened a prior family decision escalation (#439). */
  readonly escalationAnswer?: EscalationAnswerPayload;
  /** Parsed module context supplied by the runner; the worker must not invent it. */
  readonly moduleContext?: FamilyModuleContext;
  /**
   * Runner-owned prior finding identity keys that this CMR worker may adjudicate
   * as claimed-fixed. Claimed-fixed keys outside this set are stale/self-claimed
   * closure and must fail closed at the family gate.
   */
  readonly priorCmrFindingIdentityKeys?: readonly string[];
}

/** The integrated-cmr outcome (the load-bearing cross-slice-seam gate). */
export interface IntegratedCmrResult {
  /** Converged (all reviewers empty / agreed) ⇒ true; else the gate is red. */
  readonly converged: boolean;
  /** Why it did not converge (handed to the escalate seam) — set when red. */
  readonly reason?: string;
  /** CMR leg slugs that actually produced a usable review this pass. */
  readonly successfulLegs?: readonly string[];
  /** Declared CMR legs skipped at runtime, with the visible degrade flag reason. */
  readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
  /** Prior claimed-fixed findings the integrated CMR result asks the runner to adjudicate. */
  readonly claimedFixedFindingIdentityKeys?: readonly string[];
  /** Explicit disposition for claimed-fixed integrated CMR findings. */
  readonly priorFindingDispositions?: readonly PriorFindingDisposition[];
  /** Structured findings to classify at the family gate (#449). */
  readonly findings?: readonly Finding[];
  /** Worker outcome guard evidence artifacts referenced by this CMR verdict. */
  readonly evidencePaths?: readonly string[];
}

/** What opening the family PR needs (decision 4, 止于 PR). */
export interface OpenFamilyPrRequest {
  /** The family base branch the PR is opened FROM. */
  readonly familyBase: string;
}

/** The opened-PR result. */
export interface OpenFamilyPrResult {
  /** The opened PR's URL (or a synthetic handle in the fake). */
  readonly url: string;
  /** The opened PR's head commit SHA/OID, verified from PR metadata when available. */
  readonly prHead?: string;
}

export interface VerifyFamilyShippedPrRequest {
  /** The shipped marker's PR URL/handle from the family ledger. */
  readonly pr: string;
  /** The family base branch the PR must use as its head branch. */
  readonly familyBase: string;
  /** The current local family base HEAD the PR must still cover. */
  readonly expectedHead: string;
}

export type VerifyFamilyShippedPrResult =
  | { readonly ok: true }
  | { readonly ok: false; readonly reason: string };

/**
 * An `aborted` event #296 hands to #298's `recordAborted` seam on a red verify
 * (ADR 0022 decision 3④/5). The CONCRETE ledger schema (`FamilyLedgerEntry`
 * widening) is #298's; this is the minimal call shape #296 depends on.
 */
export interface FamilyAbortedEvent {
  /** Which verify barrier was red. */
  readonly phase: "wave" | "final";
  /** Present when a final integrated CMR pass, not verify/ship, is what failed. */
  readonly cmrPass?: IntegratedCmrPass;
  /** The family base at the time of the abort (so the failure is locatable). */
  readonly familyBase: string;
  /** The verify error package (decision 3④/5). */
  readonly errorPackage: FamilyVerifyErrorPackage;
  /**
   * The family base HEAD at the time of the abort (#291 缺口 2), supplied by the
   * spine via {@link VerifyCmrInput} and forwarded onto the PHASE-LEVEL durable
   * `aborted` ledger entry's `familyHeadAfter` — so reconcile's "read末条
   * familyHeadAfter" baseline logic covers merged AND aborted entries uniformly.
   * Optional: a fresh run whose abort precedes any merge has no head yet.
   */
  readonly familyHeadAfter?: string;
}

/**
 * The escalation #296 hands to #298's `escalateFamily` seam when the integrated
 * cmr does not converge or family ship hits HITL (ADR 0022 decision 3⑥/4 →
 * 升级续跑).
 */
export interface FamilyEscalation {
  /** Why the family gate paused. */
  readonly reason: string;
  /** Family base HEAD at the pause point, when known. */
  readonly familyHeadAfter?: string;
  /** Unified stop reason summary for this pause, when the caller can classify it. */
  readonly stopSummary?: StopSummary;
}

/** What the merger needs to merge one child branch into the family base. */
export interface MergeRequest {
  /** The child slice issue number (for the `--no-ff` merge message + ledger). */
  readonly childIssue: number;
  /** The child slice branch to merge (the reviewed, locally-committed branch). */
  readonly childBranch: string;
}

/**
 * What the merger's conflict-fallback resolver needs (ADR 0022 decision 3②,
 * #295). The same child identity as the original {@link MergeRequest} — the
 * resolver works on the in-progress conflicting merge of THIS child branch into
 * the family base, so it needs the issue (for the merge message + ledger) and the
 * branch (the side being merged in).
 */
export interface ConflictResolveRequest {
  /** The child slice issue number whose deterministic merge conflicted. */
  readonly childIssue: number;
  /** The child slice branch whose merge into the family base conflicted. */
  readonly childBranch: string;
}

/** The merger's result for one child merge. */
export interface MergeResult {
  /** The family base HEAD commit after this merge landed (= `familyHeadAfter`). */
  readonly familyHead: string;
  /**
   * The family base HEAD commit BEFORE this merge — the `familyHeadBefore` the
   * full-schema ledger entry records (#298 acceptance-1). Optional so a #293-era
   * Backend that does not report it still type-checks; when absent the ledger
   * entry simply omits the field (the thin-entry back-compat path).
   */
  readonly familyHeadBefore?: string;
  /**
   * The child branch HEAD commit that was merged — the `childHead` the
   * full-schema ledger entry records (#298 acceptance-1), and the ancestor the
   * crash-window reconcile branch ② confirms against the live HEAD. Without it
   * in the ledger, reconcile's branch ② (补账) is unreachable in production and a
   * crash-window child gets RE-merged (cmr R1: codex-s1 + agy). Optional for the
   * same #293 back-compat reason as `familyHeadBefore`.
   */
  readonly childHead?: string;
  /**
   * Did the deterministic `git merge --no-ff` hit a conflict? (#295.) Set by the
   * Backend's {@link FamilyBackend.mergeChildIntoFamilyBase} when the merge could
   * not complete cleanly. The merger reads THIS to decide whether to route to the
   * point-LLM resolver — "仅冲突才上 LLM". Absent / `false` ⇒ a clean deterministic
   * merge (the #293 happy path); the LLM resolver is never touched.
   */
  readonly conflicted?: boolean;
  /**
   * Was this merge LLM-resolved (the `resolving-merge-conflicts` soul ran) rather
   * than a clean deterministic merge? (#295.) Set by the merger AFTER a successful
   * {@link FamilyBackend.resolveMergeConflict}. It makes the LLM resolution
   * OBSERVABLE to the downstream family verify + integrated cmr (#296) — an
   * LLM-resolved merge is NEVER silently swallowed (ADR 0022 decision 3⑤
   * "不静默吞"). Absent / `false` ⇒ the merge was a clean deterministic merge.
   */
  readonly conflictResolvedByLlm?: boolean;
}

// ─────────────────────────── family run I/O ───────────────────────────

/**
 * Input to the family entry point {@link runFamily}.
 *
 * `singleSliceBackend` is the {@link Backend} each child fan-out runs the
 * single-slice runner against (family mode: S7 push is a local no-op, base is
 * the family base — carried via the runner's family context). `familyBackend`
 * is the family-LEVEL seam (merge + ledger). They are distinct seams so the
 * single-slice runner is reused UNCHANGED for each child (ADR 0022 decision 2).
 */
export interface FamilyRunInput {
  readonly epic: FamilyEpic;
  readonly familyBackend: FamilyBackend;
  /**
   * The single-slice Backend each child fan-out uses. In production this is the
   * RealBackend keyed by the PARENT epic run key (ADR 0024: children reuse the
   * family clone). In tests it is a zero-container fake.
   */
  readonly singleSliceBackend: Backend;
  /**
   * The local family base branch the merger accumulates onto and each child cuts
   * from (ADR 0022 decision 7). Children are cut from THIS, not `origin/<base>`.
   */
  readonly familyBase: string;
  /**
   * Explicit family-run module boundary override (#449), lowest-priority after
   * child issue and parent/family issue declarations.
   */
  readonly moduleDeclaration?: SourcedModuleDeclaration;
  /**
   * Runner/run-option/route declared modules intentionally outside the current
   * family surface. Issue-body YAML must not invent them.
   */
  readonly undevelopedModules?: ReadonlyArray<SourcedModuleDeclaration>;
  /**
   * Explicitly trusted accepted-suppression records supplied by runner/run-option
   * context. Reviewers may cite these, but cannot self-author suppressions.
   */
  readonly acceptedSuppressionSources?: ReadonlyArray<AcceptedSuppressionSource>;
  /**
   * The verify-cmr hook (ADR 0022 decision 3④/⑤/⑥) — the family verify (per-wave
   * fail-fast) + end-of-run integrated cmr. Optional: defaults to the #293 no-op
   * {@link runVerifyCmr} module export. #296 fills the module body OR injects a
   * real impl here; either way the spine's call sites + fail-fast on `ok===false`
   * are already wired, so #296 does not rewrite the spine. Injectable so the
   * spine's fail-fast branch is testable now (the repo's injected-seam idiom).
   */
  readonly verifyCmr?: (input: VerifyCmrInput) => Promise<VerifyCmrResult>;
  /**
   * The crash-window reconcile git seam (ADR 0022 decision 5, #298). When
   * present, the spine runs {@link reconcileFamilyLedger} BEFORE the wave loop
   * (the resume entry): it compares the ledger末条 head to the live family-base
   * HEAD, appends reconcile補账条 for merges that landed but whose `merged` write
   * crashed (so the wave loop skips them — no double-merge), and escalates
   * fail-closed on an inconsistent live HEAD. Absent ⇒ a fresh run (no
   * reconcile), the #293 behaviour unchanged. Injectable so the三分支 are
   * testable zero-container (the repo's injected-seam idiom).
   */
  readonly reconcileGit?: ReconcileGit;
  /**
   * Escalate-resume dependency-graph rebuild hook (ADR 0022 decision 4, #298).
   *
   * When a family run escalates (cmr non-convergence / a cycle) and a human
   * answers — possibly by editing the `blocked_by` edges in GitHub to break a
   * cycle — RE-ENTRY must REBUILD the dependency graph from LIVE GitHub metadata,
   * NOT trust the cached {@link FamilyEpic} (decision 4: "重抓 live GitHub
   * metadata 重建依赖图，不信缓存"; else the stale cycle/edges persist and it
   * re-escalates — agy R2). When this hook is present (a re-entry), the spine
   * calls it FIRST and schedules off the LIVE graph it returns, overriding the
   * passed-in `epic`. Absent ⇒ the passed `epic` is used (a fresh run, no
   * re-fetch). Injectable so the rebuild is testable zero-container; the real
   * impl re-reads the epic's sub-issues + `blocked_by` via `gh`.
   */
  readonly refetchEpic?: () => Promise<FamilyEpic>;
}

/**
 * The status of one child within a family run.
 *
 * - `"ran"` — the child's single-slice run reached S8(success) and produced a
 *   reviewed branch, but it has NOT yet been merged into the family base. This is
 *   the transient state runChild returns; the spine flips it to `"merged"` only
 *   AFTER the merge commit lands (ADR 0022 decision 5), so a premature `"merged"`
 *   is impossible. In #293 the merge is the no-conflict happy path and always
 *   resolves, so a `"ran"` child always becomes `"merged"`. #295 (the conflict
 *   fallback) is what introduces a merge that can FAIL: it extends the merge step
 *   — `MergeResult` / the merger — to signal a failed/aborted merge, and the spine
 *   then leaves that child `"ran"` (or marks `"failed"`) instead of `"merged"`.
 *   So `"ran"` is the seam state #295 needs; #293 only ever transits through it.
 * - `"merged"` — the child's reviewed branch is merged into the family base (a
 *   `status:"merged"` ledger entry exists, decision 5).
 * - `"already_done"` — this invocation skipped the child because the durable
 *   family ledger already proved it merged/shipped/completed in an earlier run.
 * - `"failed"` — the child's single-slice run did not reach success (it cannot
 *   merge); recorded honestly rather than silently dropped.
 * - `"skipped"` — the child was never schedulable (a blocker never merged, so it
 *   stayed blocked when the wave loop terminated). Recorded so the family result
 *   accounts for every child (#294's richer wave/cycle logic refines this).
 */
export type FamilyChildStatus =
  | "ran"
  | "merged"
  | "already_done"
  | "resumed"
  | "skipped"
  | "failed"
  /**
   * `"escalated"` — (#604 slice 5) the child's single-slice run hit a
   * product/design DECISION题 (`escalationKind:"decision"`) and PARKED. Distinct
   * from `"failed"` (an infra `escalationKind:"failure"` / retries-exhausted child,
   * which is terminal until manual repair): a decision escalation is answerable —
   * a later `escalation_answered` ledger row bound to this childIssue re-opens it
   * and the family runner resumes the child IN PLACE (原 sessionId, 退出-重入 per
   * ADR 0062). runChild returns this ONLY for the decision bucket; the failure
   * bucket keeps the current `"failed"` behaviour (A/B分家).
   */
  | "escalated";

/**
 * The decision escalation a child slice PARKED on (#604 slice 5).
 *
 * Only the `escalationKind:"decision"` bucket produces this — an infra
 * (`"failure"`) escalation stays `"failed"` and is NOT parked (A/B分家). The
 * `sessionId` is the child's escalated single-slice worker session, forwarded so
 * the family resume re-enters the SAME session (原地 resume, never from scratch —
 * ADR 0062 退出-重入). Absent only when the child provider surfaced no session id.
 */
export interface FamilyChildEscalation {
  /** Why the child paused (the model-supplied Escalation reason). */
  readonly reason: string;
  /** The child's Escalation diagnosis (product/design context for the human). */
  readonly diagnosis: string;
  /** Decision (answerable, parkable) vs failure (terminal until manual repair). */
  readonly escalationKind: EscalationKind;
  /** The child's escalated single-slice worker session id, for 原地 resume. */
  readonly sessionId?: string;
}

/** Per-child outcome record in the family result. */
export interface FamilyChildResult {
  readonly issue: number;
  readonly status: FamilyChildStatus;
  /** The child's reviewed branch (set when the single-slice run succeeded). */
  readonly branch?: string;
  /**
   * The parked decision escalation when `status==="escalated"` (#604 slice 5).
   * Carries the reason/diagnosis/sessionId the family runner records on the
   * `child_decision_parked` ledger row and resumes from.
   */
  readonly escalation?: FamilyChildEscalation;
}

/**
 * The family-run outcome (ADR 0022 decision 3④/⑤/⑥).
 *
 * - `"success"` — every verify barrier passed AND every epic child is merged into
 *   the family base. Only a fully-closed family run is `"success"` (in #293 the
 *   no-op verify always passes, so N independent children that all merge ⇒
 *   `"success"`).
 * - `"verify_failed"` — a verify-cmr barrier returned `ok:false`; `failedPhase`
 *   says which. The spine fails-fast (decision 3④) and returns this so the caller
 *   can distinguish a red run from a clean one (decision 3⑤ "不静默吞").
 * - `"incomplete"` — every verify barrier passed but NOT every child merged: a
 *   child's single-slice run did not succeed (`"failed"`) or stayed blocked
 *   (`"skipped"`). The run did not silently look like success (decision 3⑤
 *   "不静默吞"); the caller MUST NOT treat it as fully closed. (#293's happy path
 *   never produces this — all children merge; it guards the honest result.)
 *
 * - `"escalated"` — (#298) the crash-window reconcile found the live family-base
 *   HEAD INCONSISTENT with the ledger末条 (diverged / behind / unrelated — ADR
 *   0022 decision 5 branch ③) and bailed fail-closed BEFORE the wave loop. The
 *   run did not merge anything this invocation; a human must triage / answer (the
 *   escalate-resume mechanism, decision 4). Distinct from `verify_failed` (a red
 *   barrier mid-run) — escalation is the resume-entry fail-closed.
 *
 * Precedence when more than one applies: `"escalated"` (resume-entry, most
 * urgent) > `"verify_failed"` > `"incomplete"` > `"success"`.
 */
export type FamilyRunStatus =
  | "success"
  | "verify_failed"
  | "incomplete"
  | "escalated";

/** The family run result. */
export interface FamilyRunResult {
  /**
   * The family-run outcome. `"verify_failed"` ⇒ a verify-cmr barrier was red (see
   * `failedPhase`); the caller MUST NOT treat the run as shippable. #293's no-op
   * verify always passes, so a complete #293 run is `"success"`; the failure path
   * is wired + tested (via an injected `verifyCmr`) for #296.
   */
  readonly status: FamilyRunStatus;
  /** Which verify-cmr barrier was red (only set when `status==="verify_failed"`). */
  readonly failedPhase?: VerifyCmrPhase;
  /** The family base branch the children were merged onto. */
  readonly familyBase: string;
  /** The family base HEAD after all merges (undefined if nothing merged). */
  readonly familyHead?: string;
  /** Structured startup/escalation reason when status is `"escalated"`. */
  readonly escalation?: Escalation;
  /** Unified family-level stop reason summary (#450). */
  readonly stopSummary: StopSummary;
  /** Per-child outcomes, in execution order. */
  readonly children: ReadonlyArray<FamilyChildResult>;
  /** Non-runnable children excluded before wave scheduling, if any. */
  readonly admissionSkipped?: ReadonlyArray<FamilyAdmissionSkippedChild>;
}
