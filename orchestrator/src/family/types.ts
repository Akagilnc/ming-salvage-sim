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

import type { Backend } from "../types.js";
import type {
  VerifyCmrInput,
  VerifyCmrPhase,
  VerifyCmrResult,
} from "./verifyCmr.js";

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
  /** The child slice issue number this event is about. */
  readonly childIssue: number;
  /**
   * Merge status — the UNBLOCK-PREDICATE field (ADR 0022 decision 6②).
   *   - `"merged"`  — the child's branch is merged into the family base (a live
   *     merge OR a reconcile補账条; both COUNT as merged).
   *   - `"aborted"` — a verify/cmr barrier failed; this event carries the family
   *     head at the time (`familyHeadAfter`) for triage. NOT counted as merged.
   */
  readonly status: "merged" | "aborted";
  /**
   * Event tag distinguishing a crash-window reconcile補账条 (`"reconciled"`) from
   * a live merge. Set ONLY by reconcile. The entry still carries
   * `status:"merged"` so the unblock predicate counts it (decision 5, codex R3);
   * the tag is for observability / audit, NOT the unblock truth.
   */
  readonly event?: "reconciled";
  /** The child branch that was merged (full schema, #298). */
  readonly childBranch?: string;
  /** The child branch HEAD commit that was merged (the ancestor reconcile checks). */
  readonly childHead?: string;
  /** The wave number this child was scheduled in (#294's wave numbering). */
  readonly wave?: number;
  /** The family base HEAD BEFORE this child's merge. */
  readonly familyHeadBefore?: string;
  /** The family base HEAD AFTER this child's merge (or, for `aborted`, at failure). */
  readonly familyHeadAfter?: string;
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
}

/** What the merger needs to merge one child branch into the family base. */
export interface MergeRequest {
  /** The child slice issue number (for the `--no-ff` merge message + ledger). */
  readonly childIssue: number;
  /** The child slice branch to merge (the reviewed, locally-committed branch). */
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
 * - `"failed"` — the child's single-slice run did not reach success (it cannot
 *   merge); recorded honestly rather than silently dropped.
 * - `"skipped"` — the child was never schedulable (a blocker never merged, so it
 *   stayed blocked when the wave loop terminated). Recorded so the family result
 *   accounts for every child (#294's richer wave/cycle logic refines this).
 */
export type FamilyChildStatus = "ran" | "merged" | "skipped" | "failed";

/** Per-child outcome record in the family result. */
export interface FamilyChildResult {
  readonly issue: number;
  readonly status: FamilyChildStatus;
  /** The child's reviewed branch (set when the single-slice run succeeded). */
  readonly branch?: string;
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
  /** Per-child outcomes, in execution order. */
  readonly children: ReadonlyArray<FamilyChildResult>;
}
