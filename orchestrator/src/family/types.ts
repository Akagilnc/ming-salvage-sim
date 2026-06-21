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
 * One append-only family-ledger event (ADR 0022 decision 5, #293 thinnest form).
 *
 * #293 records only the minimal `{childIssue, status:"merged"}` per merged
 * child. #298 extends the schema (childBranch / childHead / wave /
 * familyHeadBefore / familyHeadAfter / aborted events + reconcile) by adding
 * fields HERE and writing them in the merger — without re-shaping the spine.
 */
export interface FamilyLedgerEntry {
  /** The child slice issue number that was merged into the family base. */
  readonly childIssue: number;
  /**
   * Merge status. #293 only ever writes `"merged"` (the happy, no-conflict
   * path). #298 adds `"aborted"` and reconcile events; the `status==="merged"`
   * predicate the commander's unblock check uses (ADR 0022 decision 6②) reads
   * THIS field, so reconcile補账条 must also be `"merged"`.
   */
  readonly status: "merged";
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
   * #298-OWNED escalate seam — #296 only CALLS it. A NOT-converged integrated cmr
   * (decision 3⑥) escalates续跑 (复用 ADR 0017/0018 的升级续跑: 卡点 → 返回调用端
   * → 拍 → resumeSession 注入). #296 does NOT build the escalate machine — it
   * hands the non-convergence reason to #298's seam. Optional ⇒ a backend without
   * it surfaces the red purely via the returned `{ok:false}`.
   */
  escalateFamily?(escalation: FamilyEscalation): Promise<void>;
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
}

/** The integrated-cmr outcome (the load-bearing cross-slice-seam gate). */
export interface IntegratedCmrResult {
  /** Converged (all reviewers empty / agreed) ⇒ true; else the gate is red. */
  readonly converged: boolean;
  /** Why it did not converge (handed to the escalate seam) — set when red. */
  readonly reason?: string;
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
}

/**
 * An `aborted` event #296 hands to #298's `recordAborted` seam on a red verify
 * (ADR 0022 decision 3④/5). The CONCRETE ledger schema (`FamilyLedgerEntry`
 * widening) is #298's; this is the minimal call shape #296 depends on.
 */
export interface FamilyAbortedEvent {
  /** Which verify barrier was red. */
  readonly phase: "wave" | "final";
  /** The family base at the time of the abort (so the failure is locatable). */
  readonly familyBase: string;
  /** The verify error package (decision 3④/5). */
  readonly errorPackage: FamilyVerifyErrorPackage;
}

/**
 * The escalation #296 hands to #298's `escalateFamily` seam when the integrated
 * cmr does not converge (ADR 0022 decision 3⑥/4 → 升级续跑). The CONCRETE
 * escalate/resume machine is #298's (复用 ADR 0017/0018); this is the minimal
 * call shape #296 depends on.
 */
export interface FamilyEscalation {
  /** Why the integrated cmr did not converge (the cross-slice-seam finding). */
  readonly reason: string;
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
  /** The family base HEAD commit after this merge landed. */
  readonly familyHead: string;
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
 * Precedence when more than one applies: `"verify_failed"` (most urgent) >
 * `"incomplete"` > `"success"`.
 */
export type FamilyRunStatus = "success" | "verify_failed" | "incomplete";

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
