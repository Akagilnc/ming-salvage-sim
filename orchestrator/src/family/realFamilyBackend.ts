/**
 * realFamilyBackend.ts — the REAL {@link FamilyBackend} implementation (#291).
 *
 * The family integration layer's control flow (`family/*.ts`, #293) reaches the
 * outside world ONLY through the {@link FamilyBackend} seam. #293 立 the seam +
 * the zero-container fakes; THIS file gives that seam a real implementation —
 * each operation is a few `git`/file ops or one `sc.run`, NOT a big engine
 * (grounded against Sandcastle v0.10.0: the library has no branch-to-branch merge
 * /family-ledger/verify原语, so the family layer is deterministic git + the
 * existing single-slice primitives behind this seam).
 *
 *   - mergeChildIntoFamilyBase → `git checkout <familyBase>` + `git merge --no-ff`
 *     in the dedicated clone; a conflict is LEFT in place (never `--abort`).
 *   - resolveMergeConflict     → ONE `sc.run` under the `merger` soul +
 *     `resolving-merge-conflicts` skill, scoped to the in-progress conflicting
 *     merge (resolve → add → commit; never `--abort`). The真 `sc.run` is behind
 *     the {@link runMergerAgent} protected seam (fake-able in unit tests; the real
 *     container only runs on the manual-smoke / driver path).
 *   - appendFamilyLedger / readFamilyLedger → an append-only sibling JSONL OUTSIDE
 *     the family base worktree (a worktree clean can never touch the resume /
 *     unblock truth) — the same `appendFileSync`/`readFileSync`套路 as RealBackend's
 *     single-slice step ledger, but a distinct file.
 *   - runFamilyVerify          → `npx tsc --noEmit` + `npx vitest run` against the
 *     family base; green → {ok:true}, red → {ok:false, errorPackage:{reason}}.
 *   - runIntegratedCmr         → a thin wrap of the local `ak-cross-m-review`
 *     pipeline behind the {@link runCmr} protected seam.
 *   - openFamilyPr             → push the family base + `gh pr create` and STOP
 *     (the family orchestrator's autonomy ends at the PR; online bot cmr + merge
 *     are the separate pr-review-loop stage).
 *   - recordAborted            → the #296 in-memory back-compat seam (a no-op
 *     here): the durable PHASE-LEVEL `aborted` entry is `recordDurableAbort`'s job
 *     (verifyCmr.ts calls both; only the durable writer appends — exactly one entry).
 *   - escalateFamily           → a durable stuck-point record (ADR 0017/0018 升级
 *     续跑: 卡点 → 返回调用端 → resumeSession 注入; the卡点 must survive the process,
 *     so it is persisted alongside the ledger).
 *   - reconcileGit()           → the {@link ReconcileGit} four predicates over
 *     `git rev-parse` / `git rev-parse --verify` / `git merge-base --is-ancestor`.
 *
 * SEAM BOUNDARY: the deterministic git / file ops run directly; the external side
 * effects (the merger agent container, `gh pr create`, `ak-cross-m-review`) go
 * through protected methods a unit test overrides — so the contract is verified
 * zero-container, and the real container / real GitHub only run on the driver /
 * manual-smoke path (the next unit). This file does NOT wire into the driver / run
 * end-to-end — that is the下一个 unit.
 */

import { execFileSync } from "node:child_process";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import * as sc from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

import { runExclusive } from "../gitMutex.js";
import {
  branchForIssue,
  SANDBOX_SKILLS_DIR,
  SANDBOX_SOUL_ENV,
} from "../realBackend.js";

import type {
  ConflictResolveRequest,
  FamilyAbortedEvent,
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  MergeResult,
  OpenFamilyPrRequest,
  OpenFamilyPrResult,
  ReconcileGit,
} from "./types.js";

/** The family-ledger sibling filename (under {@link RealFamilyBackendOptions.ledgerDir}). */
export const FAMILY_LEDGER_FILENAME = "family-ledger.jsonl";
/** The durable escalate stuck-point filename (a sibling of the family ledger). */
export const FAMILY_ESCALATION_FILENAME = "family-escalations.jsonl";

/**
 * One durable escalate stuck-point (ADR 0022 decision 4: 卡点 → 返回调用端 → 拍 →
 * resumeSession). Persisted so the卡点 survives the process — the caller surfaces
 * it to a human, and a re-entry rebuilds the dependency graph from live GitHub
 * (the spine's `refetchEpic`/`reconcileGit` resume entry) rather than from this
 * record. The record is the OBSERVABILITY trail, not the resume state itself.
 */
export interface FamilyEscalationRecord extends FamilyEscalation {
  /** ISO timestamp the stuck-point was recorded. */
  readonly ts: string;
}

/** Options for {@link RealFamilyBackend}. */
export interface RealFamilyBackendOptions {
  /**
   * The dedicated clone the family run owns (ADR 0024) — the family base branch
   * + every child branch live here, and every git op anchors on it. In production
   * this is the family RealBackend's `workingRepoPath()`.
   */
  readonly workingRepo: string;
  /** The LOCAL family base branch the merger accumulates onto (ADR 0022 decision 7). */
  readonly familyBase: string;
  /**
   * Where the append-only family ledger + escalation records live — a directory
   * OUTSIDE the family base worktree (ADR 0022 decision 5), so a worktree clean
   * never touches the resume / unblock truth. Created on first write.
   */
  readonly ledgerDir: string;
  /** GitHub repo slug for `gh` (`owner/name`) — for openFamilyPr. */
  readonly repo: string;
  /** The base branch the family PR targets (e.g. an integration branch or "main"). */
  readonly base: string;
  /** Dir holding the versioned promptFiles (the merger conflict prompt). */
  readonly promptsDir: string;
  /** The profile image (souls + CLIs baked in) for the merger agent sandbox. */
  readonly imageName: string;
  /** Host dir holding the baked dev skills to bind-mount for the merger agent. */
  readonly skillsMount: string;
  /**
   * The family base HEAD at run setup — the baseline {@link ReconcileGit.familyBaseStartHead}
   * returns (the spine provides it; the only baseline available when the ledger is
   * empty). Optional at construction, but REQUIRED before `reconcileGit()` is used
   * for the empty-ledger crash-window net: that predicate THROWS when it is absent
   * rather than falling back to the live head (which would silently disable the net
   * — codex R3). A backend that never drives reconcile may omit it.
   */
  readonly familyBaseStartHead?: string;
}

/** The merger-agent prompt the conflict resolver runs (under the `merger` soul). */
const MERGER_CONFLICT_PROMPT = "merger_resolve_conflict.md";
/** The merger agent's completion signal (matches prompts/merger_resolve_conflict.md). */
const MERGER_COMPLETION_SIGNAL = "MERGER_STEP_COMPLETE";
/** The merger resolver runs on the higher-skill model (the conflict-resolution role). */
const MERGER_MODEL = "claude-opus-4-8";

/**
 * The baked soul the merger agent runs under (F28 / ADR 0022: the conflict
 * fallback follows the "one mirror new soul" model). This is a THIRD baked soul
 * value alongside the step souls — it is deliberately NOT a {@link StepSoul},
 * because the merger is not an S0–S8 single-slice step driven by `soulForStep`
 * (which maps a step's `role` → "coder"/"READ-ONLY"). The merger has its own
 * activation path: it is injected into the sandbox via {@link SANDBOX_SOUL_ENV}
 * (`ORCHESTRATOR_SOUL`), the SAME env mechanism `RealBackend.box()` uses for
 * coder/reviewer — same image, same env var, a new soul value — so the v0.1
 * profile entrypoint activates the merger soul (with the `resolving-merge-conflicts`
 * skill), not whatever default soul it would otherwise pick. The merger soul's
 * CONTENT (the baked profile + `prompts/merger_resolve_conflict.md` behaviour) is
 * a production-image concern (it must be baked into the profile image); this
 * constant is the code-side selector that activates it.
 */
export const MERGER_SOUL = "merger";

export class RealFamilyBackend implements FamilyBackend {
  protected readonly opts: RealFamilyBackendOptions;

  constructor(opts: RealFamilyBackendOptions) {
    this.opts = opts;
  }

  /**
   * Run a host `git`/`gh`/`npx` command in the dedicated clone, returning trimmed
   * stdout. `protected` so a unit test can intercept the external side-effect
   * commands (`gh pr create`, `ak-cross-m-review`) without a real GitHub / network
   * — the same seam pattern RealBackend's `sh` uses. The default `cwd` is the
   * dedicated clone (every family git op anchors there).
   */
  protected sh(file: string, args: string[], cwd?: string): string {
    return execFileSync(file, args, {
      cwd: cwd ?? this.opts.workingRepo,
      stdio: ["ignore", "pipe", "pipe"],
      encoding: "utf8",
    }).trim();
  }

  // ─────────────────────────── family ledger ───────────────────────────

  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    appendFileSync(
      join(this.opts.ledgerDir, FAMILY_LEDGER_FILENAME),
      JSON.stringify(entry) + "\n",
      "utf8",
    );
  }

  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    let raw: string;
    try {
      raw = readFileSync(join(this.opts.ledgerDir, FAMILY_LEDGER_FILENAME), "utf8");
    } catch (err) {
      // ONLY "file does not exist yet" (ENOENT) means an empty ledger. Any OTHER
      // read failure (EACCES, EISDIR, transient IO, path corruption) must FAIL
      // CLOSED — the ledger is the durable resume/unblock truth reconcile reads,
      // and silently returning [] on an unreadable-but-PRESENT ledger would make
      // reconcile think no child ever merged → re-merge already-landed children
      // (codex R2; decision 5 "不静默吞"). Rethrow with path context.
      if (isFileNotFound(err)) return [];
      throw new Error(
        `readFamilyLedger: failed to read the family ledger at ` +
          `${join(this.opts.ledgerDir, FAMILY_LEDGER_FILENAME)} — ` +
          `${err instanceof Error ? err.message : String(err)}`,
      );
    }
    return raw
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as FamilyLedgerEntry);
  }

  // ─────────────────────────── merge ───────────────────────────

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<MergeResult> {
    // #291 B7: serialise this git-MUTATING merge under the SAME per-clone mutex the
    // single-slice prepareWorktree uses (keyed on the dedicated clone). The spine
    // already merges serially, but a wave's children still run their cuts
    // concurrently — a `git worktree add` racing a `git checkout <familyBase>` +
    // `git merge` on the one clone would contend on `.git/index.lock` / HEAD. Keying
    // both critical sections on `workingRepo` makes a child cut and a family merge
    // never touch the shared `.git` at once (a different clone never blocks).
    return runExclusive(this.opts.workingRepo, () => this.mergeChildLocked(child));
  }

  /** The git-mutating body of {@link mergeChildIntoFamilyBase}, under the per-clone mutex. */
  private async mergeChildLocked(child: MergeRequest): Promise<MergeResult> {
    const repo = this.opts.workingRepo;
    // Pin the SHAs BEFORE the merge: the family base HEAD before, and the child
    // branch HEAD being merged in (the ancestor reconcile branch ② confirms).
    this.sh("git", ["checkout", this.opts.familyBase], repo);
    const familyHeadBefore = this.sh("git", ["rev-parse", "HEAD"], repo);
    const childHead = this.sh("git", ["rev-parse", child.childBranch], repo);
    const msg = `Merge child #${child.childIssue} (${child.childBranch}) into ${this.opts.familyBase}`;
    try {
      this.sh("git", ["merge", "--no-ff", "-m", msg, child.childBranch], repo);
    } catch (err) {
      // git exit ≠ 0 is NOT always a content conflict: a bad ref, index/lock
      // error, dirty worktree, hook/config failure all exit non-zero too, and
      // leave NO in-progress merge (no MERGE_HEAD). Reporting THOSE as
      // `conflicted:true` would route a broken/locked repo into the LLM resolver
      // — spinning up the merger agent on a state it cannot resolve (codex R1 +
      // agy R1). So only a REAL conflict (MERGE_HEAD present) becomes
      // `conflicted:true`; we LEAVE that state (do NOT `--abort`) so the point-LLM
      // resolver can resolve it in place. The merger reads `conflicted` to route to
      // resolveMergeConflict ("仅冲突才上 LLM"); it never writes a `merged` ledger
      // entry on a conflicted result. A non-conflict git failure RETHROWS so the
      // wave aborts loudly with the original git error (decision 3④/5 "不静默吞").
      if (this.mergeInProgress(repo)) {
        return { familyHead: familyHeadBefore, familyHeadBefore, childHead, conflicted: true };
      }
      throw err;
    }
    const familyHead = this.sh("git", ["rev-parse", "HEAD"], repo);
    return { familyHead, familyHeadBefore, childHead };
  }

  async resolveMergeConflict(req: ConflictResolveRequest): Promise<MergeResult> {
    const repo = this.opts.workingRepo;
    const familyHeadBefore = this.sh("git", ["rev-parse", this.opts.familyBase], repo);
    const childHead = this.sh("git", ["rev-parse", req.childBranch], repo);
    // ONE agent under the `merger` soul + `resolving-merge-conflicts` skill,
    // scoped to THIS in-progress conflicting merge: resolve each hunk → `git add`
    // → commit the merge (NEVER `--abort`). The real `sc.run` is behind the
    // {@link runMergerAgent} seam (fake-able; the real container only on the
    // driver / manual-smoke path).
    const outcome = await this.runMergerAgent(req);
    if (!outcome.resolved) {
      // The resolver could not resolve (escalated / failed) → surface it; the
      // merger does NOT write a `merged` entry (an unresolved conflict never looks
      // clean). Throw with the agent's diagnosis so the failure is locatable.
      throw new Error(
        `resolveMergeConflict: the merger agent did not resolve child #${req.childIssue}` +
          (outcome.reason !== undefined ? ` — ${outcome.reason}` : ""),
      );
    }
    // The agent claims it committed the merge — but VERIFY git truth before
    // returning clean (the prompt's "resolve → add → commit, never --abort" is a
    // soft LLM instruction, not a postcondition). Failure modes a clean return
    // would otherwise wave through into a durable `merged` ledger entry:
    //   (a) the merge is still in progress (MERGE_HEAD present) — the agent never
    //       committed; (codex R2)
    //   (b) the agent aborted/reset instead of committing — the family base ref is
    //       back at (or before) familyHeadBefore and the child never landed; (codex R2)
    //   (c) the agent landed the child on the WRONG ref (a detached HEAD or another
    //       branch) — HEAD moved + child is an ancestor of HEAD, but the FAMILY BASE
    //       ref is unmoved; the next verify checks out familyBase and sees no merge,
    //       yet the ledger said merged (codex R3).
    // So the post-state is read off the FAMILY BASE REF (not HEAD): only when the
    // family base ref itself moved past familyHeadBefore AND childHead is now its
    // ancestor does the merge count as landed. Anything else → `conflicted:true` so
    // the merger refuses to record `merged` (invariant: "an unresolved conflict
    // never looks clean").
    const stillInProgress = this.mergeInProgress(repo);
    const familyHead = this.sh("git", ["rev-parse", this.opts.familyBase], repo);
    const childLanded =
      !stillInProgress &&
      familyHead !== familyHeadBefore &&
      this.isAncestorOf(childHead, familyHead, repo);
    return childLanded
      ? { familyHead, familyHeadBefore, childHead }
      : { familyHead, familyHeadBefore, childHead, conflicted: true };
  }

  /** True iff `ancestor` is an ancestor of `descendant` (`git merge-base --is-ancestor`). */
  protected isAncestorOf(ancestor: string, descendant: string, repo: string): boolean {
    try {
      this.sh("git", ["merge-base", "--is-ancestor", ancestor, descendant], repo);
      return true;
    } catch (err) {
      // exit 1 = a legit "not an ancestor"; anything else (128 bad object / broken
      // repo) is OPERATIONAL and must propagate, not read as a false predicate.
      if (gitExitStatus(err) === 1) return false;
      throw err;
    }
  }

  /**
   * Run the merger agent over the in-progress conflicting merge (ONE `sc.run`
   * under the `merger` soul + `resolving-merge-conflicts` skill). `protected` so a
   * unit test fakes the outcome without a real container — the real container only
   * runs on the driver / manual-smoke path. Returns whether the agent resolved +
   * an optional reason (the escalate diagnosis on a non-resolve).
   */
  protected async runMergerAgent(
    req: ConflictResolveRequest,
  ): Promise<{ resolved: boolean; reason?: string }> {
    const result = await sc.run({
      name: `merger-resolve-${req.childIssue}`,
      cwd: this.opts.workingRepo,
      sandbox: this.mergerSandbox(),
      agent: sc.claudeCode(MERGER_MODEL),
      maxIterations: 1,
      completionSignal: MERGER_COMPLETION_SIGNAL,
      branchStrategy: { type: "head" }, // commit the resolved merge in place
      promptFile: join(this.opts.promptsDir, MERGER_CONFLICT_PROMPT),
    });
    return mergerOutcomeFromResult(result);
  }

  /** The merger agent's sandbox (souls + skills baked into the image). */
  protected mergerSandbox(): sc.SandboxProvider {
    return docker(this.mergerSandboxConfig());
  }

  /**
   * The docker options the merger sandbox runs under — the SOUL-SELECTION seam
   * (F28 / ADR 0022). Pure (no container, no I/O) so a unit test asserts the
   * baked-soul env + skills-mount path without spinning a real sandbox, mirroring
   * how {@link soulForStep} is the testable seam on the single-slice path.
   *
   * The merger soul is activated the SAME way coder/reviewer are in
   * `RealBackend.box()`: by injecting {@link SANDBOX_SOUL_ENV} (`ORCHESTRATOR_SOUL`)
   * — same env var, same image, a new soul value ({@link MERGER_SOUL}) — NOT by the
   * prompt alone. Before this the sandbox set no env, so `ORCHESTRATOR_SOUL` was
   * never set and the merger ran under the image's default soul (the F28 PARTIAL).
   * The `resolving-merge-conflicts` skill is mounted at {@link SANDBOX_SKILLS_DIR}
   * (`/home/agent/.claude/skills`, the path the agent's soul/skill discovery scans
   * — the same one `RealBackend.box()` uses), so the merger soul can find it.
   */
  protected mergerSandboxConfig(): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string }>;
  } {
    return {
      imageName: this.opts.imageName,
      env: { [SANDBOX_SOUL_ENV]: MERGER_SOUL },
      mounts: [{ hostPath: this.opts.skillsMount, sandboxPath: SANDBOX_SKILLS_DIR }],
    };
  }

  /** Is a git merge in progress (MERGE_HEAD present)? */
  protected mergeInProgress(repo: string): boolean {
    try {
      this.sh("git", ["rev-parse", "-q", "--verify", "MERGE_HEAD"], repo);
      return true;
    } catch {
      return false;
    }
  }

  // ─────────────────────────── verify ───────────────────────────

  async runFamilyVerify(request: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    const repo = this.opts.workingRepo;
    // Verify runs against the family base (checked out). Both phases run typecheck
    // + tests; "final" runs the FULL suite (vitest run is already the full suite
    // here — wave can scope narrower in a richer config, but the family base must
    // be GREEN end-to-end before the integrated cmr / PR either way).
    this.sh("git", ["checkout", request.familyBase], repo);
    try {
      this.runVerifyCommands(request);
    } catch (err) {
      return {
        ok: false,
        errorPackage: { reason: summarizeError(request.phase, err) },
      };
    }
    return { ok: true };
  }

  /**
   * Run the deterministic verify commands (typecheck + tests) in the dedicated
   * clone. `protected` so a unit test drives the green/red branch without a real
   * `npx tsc` / `npx vitest` run. A non-zero exit throws (the caller packages it).
   */
  protected runVerifyCommands(_request: FamilyVerifyRequest): void {
    this.sh("npx", ["tsc", "--noEmit"], this.opts.workingRepo);
    this.sh("npx", ["vitest", "run"], this.opts.workingRepo);
  }

  // ─────────────────────────── integrated cmr ───────────────────────────

  async runIntegratedCmr(request: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    return this.runCmr(request);
  }

  /**
   * Thin wrap of the local `ak-cross-m-review` pipeline over the merged family
   * base (ADR 0022 decision 3⑥). `protected` so a unit test fakes convergence
   * without spawning the real cross-model squad. The real path invokes the local
   * cmr runner (a subprocess) and parses its convergence verdict.
   */
  protected async runCmr(request: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    // The local cmr pipeline is a subprocess; the REAL invocation + verdict parse
    // is the driver / manual-smoke path (it spawns the cross-model squad). Here we
    // delegate to the seam so the unit test verifies the call contract; a default
    // real impl would run `ak-cross-m-review` against `request.familyBase` and
    // surface its converged / non-converged verdict + reason.
    void request;
    throw new Error(
      "runIntegratedCmr: the real ak-cross-m-review invocation is the driver / " +
        "manual-smoke path; unit tests override runCmr to verify the call contract.",
    );
  }

  // ─────────────────────────── open PR (止于 PR) ───────────────────────────

  async openFamilyPr(request: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
    const repo = this.opts.workingRepo;
    // ONLY here do we push the family base + open the PR — and STOP (the family
    // orchestrator's autonomy ends at the PR; online bot cmr + merge are the
    // separate pr-review-loop stage). This is the SOLE remote push.
    this.sh("git", ["push", "-u", "origin", request.familyBase], repo);
    const url = this.sh(
      "gh",
      [
        "pr",
        "create",
        "--repo",
        this.opts.repo,
        "--base",
        this.opts.base,
        "--head",
        request.familyBase,
        "--fill",
      ],
      repo,
    );
    return { url };
  }

  // ─────────────────────────── aborted / escalate ───────────────────────────

  async recordAborted(_event: FamilyAbortedEvent): Promise<void> {
    // The `recordAborted` SEAM is the #296 in-memory back-compat event hook — NOT
    // the durable writer. The verify/cmr hook (verifyCmr.ts) records a red verify
    // by calling BOTH this seam AND `recordDurableAbort` (ledger.ts), and ONLY the
    // latter appends the PHASE-LEVEL durable `aborted` entry through
    // `appendFamilyLedger`. The contract is fixed by wiring-aborted-durable-291:
    // exactly ONE durable aborted entry per red verify, from `recordDurableAbort`.
    // An earlier version of this method ALSO appended durably, so against the real
    // spine one red verify wrote TWO identical aborted entries (codex R1). This is
    // therefore a deliberate no-op: the durable truth is `recordDurableAbort`'s,
    // and this seam only exists so a #296-era caller that depends on the hook still
    // type-checks. (A RealFamilyBackend has no in-memory consumer, so there is
    // nothing to push — the durable ledger is the single source of truth.)
  }

  async escalateFamily(escalation: FamilyEscalation): Promise<void> {
    // Persist the卡点 durably (ADR 0017/0018 升级续跑: 卡点 → 返回调用端 → 拍 →
    // resumeSession). The record must survive the process so the caller can surface
    // it + a re-entry rebuilds the graph from live GitHub (the spine's resume
    // entry); this is the observability trail. Append-only, a sibling of the ledger.
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    const record: FamilyEscalationRecord = {
      reason: escalation.reason,
      ts: new Date().toISOString(),
    };
    appendFileSync(
      join(this.opts.ledgerDir, FAMILY_ESCALATION_FILENAME),
      JSON.stringify(record) + "\n",
      "utf8",
    );
  }

  /** Read the durable escalate stuck-points (for the caller / a re-entry). */
  async readEscalations(): Promise<ReadonlyArray<FamilyEscalationRecord>> {
    let raw: string;
    try {
      raw = readFileSync(join(this.opts.ledgerDir, FAMILY_ESCALATION_FILENAME), "utf8");
    } catch (err) {
      // Same fail-closed rule as readFamilyLedger (codex R2): a missing file
      // (ENOENT) is an empty set, but an unreadable-but-PRESENT escalation log
      // (EACCES / EISDIR / IO error) must rethrow — hiding a stuck-point read
      // failure as "no escalations" would lose the durable卡点 a re-entry surfaces.
      if (isFileNotFound(err)) return [];
      throw new Error(
        `readEscalations: failed to read the escalation log at ` +
          `${join(this.opts.ledgerDir, FAMILY_ESCALATION_FILENAME)} — ` +
          `${err instanceof Error ? err.message : String(err)}`,
      );
    }
    return raw
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as FamilyEscalationRecord);
  }

  // ─────────────────────────── reconcile git seam ───────────────────────────

  /**
   * The {@link ReconcileGit} four predicates over real git in the dedicated clone
   * (ADR 0022 decision 5, #298). The spine hands this to {@link reconcileFamilyLedger}
   * so the crash-window reconcile is computed against the live HEAD.
   */
  reconcileGit(): ReconcileGit {
    const repo = this.opts.workingRepo;
    const familyBase = this.opts.familyBase;
    const sh = (args: string[]): string => this.sh("git", args, repo);
    const startHead = this.opts.familyBaseStartHead;
    return {
      liveFamilyHead: async () => sh(["rev-parse", familyBase]),
      // The empty-ledger crash-window safety net (reconcile.ts) compares the live
      // family head to this start head: if the base moved past it yet no child
      // explains the move, fail-closed escalate. Falling back to the CURRENT live
      // head when no start head was recorded would make `liveHead !== startHead`
      // trivially false and SILENTLY DISABLE that net — a fail-open (codex R3). So
      // require the recorded setup head: throw when it is absent rather than
      // returning a value that defeats the check.
      familyBaseStartHead: async () => {
        if (startHead === undefined) {
          throw new Error(
            "reconcileGit.familyBaseStartHead: no familyBaseStartHead was recorded " +
              "at run setup — it is the only baseline for the empty-ledger crash-window " +
              "net; refusing to fall back to the live head (which would silently disable " +
              "the net). Provide RealFamilyBackendOptions.familyBaseStartHead.",
          );
        }
        return startHead;
      },
      childHeadExists: async (childIssue: number, childBranch?: string) => {
        // The production reconcile caller (reconcile.ts) is handed only the child
        // ISSUE — `ChildSlice` carries no branch — so it calls `childHeadExists(issue)`
        // with NO `childBranch`. Returning `{exists:false}` on a missing branch would
        // make the crash-window 补账 predicate dead in production: every already-landed
        // child would read as absent → reconcile re-merges it (a double-merge — the
        // exact failure MergeResult.childHead's contract exists to prevent — codex R1).
        // So derive the branch from the issue via the single-slice runner's own
        // `feat/244-orchestrator-issue-<n>` convention when no explicit branch is given.
        // (The proper end-state is to thread `childBranch` through ChildSlice/reconcile
        // — flagged to the driver unit; this fallback makes the seam WORK meanwhile.)
        const branch = childBranch ?? branchForIssue(childIssue);
        try {
          const childHead = sh(["rev-parse", "--verify", `${branch}^{commit}`]);
          return { exists: true, childHead };
        } catch {
          // NOTE (online R1 CodeRabbit): unlike the `--is-ancestor` predicates below,
          // `rev-parse --verify` exits 128 for BOTH a missing ref AND an operational
          // failure — the exit code cannot tell them apart. An absent child branch is
          // the EXPECTED reconcile case (ADR 0022 dec5 agy R4: "branch尚不存在 → 当未合
          // 从头跑"), so we keep the swallow → `{exists:false}`; a genuine repo fault
          // then surfaces loudly when the re-run child operates on the broken repo.
          return { exists: false };
        }
      },
      isAncestor: async (childHead: string, liveHead: string) => {
        try {
          // `--is-ancestor` exits 0 iff childHead is an ancestor of liveHead.
          this.sh("git", ["merge-base", "--is-ancestor", childHead, liveHead], repo);
          return true;
        } catch (err) {
          // exit 1 = legit "not an ancestor"; exit 128 (bad object / broken repo) is
          // OPERATIONAL and must propagate, not read as "not merged" (online R1 CR).
          if (gitExitStatus(err) === 1) return false;
          throw err;
        }
      },
    };
  }
}

/**
 * Decide the merger outcome from a Sandcastle run result: gate on the completion
 * signal FIRST, then parse the `<merger>` tag. Pure (a check on the run-result
 * shape) so the gate is unit-tested without a container.
 *
 * The completion-signal gate mirrors the single-slice RealBackend's
 * `assertCompletionSignal` invariant ("#244 agent emit completionSignal 才进下一步"):
 * a complete-but-unsignaled run (e.g. `maxIterations` hit mid-resolution) can still
 * carry an EARLIER `<merger>{"resolved":true}</merger>` in its stdout; without this
 * gate {@link parseMergerOutcome} would accept that as resolved and record a merge
 * the agent never signaled done (codex R1). An unsignaled run is treated as
 * UNRESOLVED (escalate), never resolved — the safe direction; the caller surfaces
 * it rather than recording a phantom-clean merge.
 */
export function mergerOutcomeFromResult(result: {
  completionSignal?: string | string[];
  stdout: string;
}): { resolved: boolean; reason?: string } {
  const signal = result.completionSignal;
  const signaled = Array.isArray(signal)
    ? signal.includes(MERGER_COMPLETION_SIGNAL)
    : signal === MERGER_COMPLETION_SIGNAL;
  if (!signaled) {
    const actual =
      signal === undefined
        ? "none (no signal fired before the iteration limit)"
        : `"${String(signal)}"`;
    return {
      resolved: false,
      reason:
        `merger agent did not fire its completion signal — expected ` +
        `"${MERGER_COMPLETION_SIGNAL}", got ${actual} (a complete-but-unsignaled ` +
        `run does not count as resolved)`,
    };
  }
  return parseMergerOutcome(result.stdout);
}

/**
 * Parse the merger agent's `<merger>{…}</merger>` outcome from its stdout (the
 * shape in prompts/merger_resolve_conflict.md). Pure so it is unit-tested without
 * a container. Returns whether it resolved + an optional escalate reason.
 */
export function parseMergerOutcome(stdout: string): {
  resolved: boolean;
  reason?: string;
} {
  const re = /<merger>([\s\S]*?)<\/merger>/g;
  let last: string | undefined;
  for (let m = re.exec(stdout); m !== null; m = re.exec(stdout)) last = m[1];
  if (last === undefined) {
    return { resolved: false, reason: "merger agent emitted no <merger> tag" };
  }
  let parsed: {
    resolved?: boolean;
    escalate?: { reason?: string; diagnosis?: string };
  };
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { resolved: false, reason: "merger agent <merger> tag was not valid JSON" };
  }
  // `JSON.parse` succeeds on the bare literals `null` / `true` / `5` / `"x"` — a
  // misbehaving agent emitting `<merger>null</merger>` parses to `null`, and the
  // `parsed.resolved` read below would then throw a TypeError OUTSIDE this
  // try/catch and crash the parent (agy R1). Treat any non-object payload as an
  // unresolved-with-reason, never resolved (the safe direction).
  if (parsed === null || typeof parsed !== "object") {
    return { resolved: false, reason: "merger agent <merger> tag was not a JSON object" };
  }
  if (parsed.resolved === true) return { resolved: true };
  const reason =
    parsed.escalate?.reason ?? parsed.escalate?.diagnosis ?? "merger did not resolve";
  return { resolved: false, reason };
}

/**
 * Is this read error a "file does not exist yet" (ENOENT)? Used to keep the
 * ledger/escalation reads fail-CLOSED: only a missing file maps to an empty set;
 * any other read failure (EACCES / EISDIR / IO / corruption) must rethrow so an
 * unreadable-but-present durable file is never silently read as empty (codex R2).
 */
function isFileNotFound(err: unknown): boolean {
  return (
    err !== null &&
    typeof err === "object" &&
    (err as { code?: unknown }).code === "ENOENT"
  );
}

/** A one-line human-readable summary of a failed verify command (phase + error). */
function summarizeError(phase: "wave" | "final", err: unknown): string {
  // execFileSync on a non-zero exit throws an Error whose `.message` is only the
  // status line ("Command failed: npx tsc --noEmit") — the ACTUAL compiler / test
  // output (the locatable reason) is on `.stderr` / `.stdout`. Reading only
  // `.message` drops it, so the ledger could not name WHY verify went red,
  // breaking decision 3④/5 "reason locatable from the ledger alone" (agy R1).
  let detail = err instanceof Error ? err.message : String(err);
  if (err !== null && typeof err === "object") {
    const e = err as { stderr?: unknown; stdout?: unknown };
    // Append BOTH streams (labeled), not just the first non-empty one: some tools
    // put warnings/noise on stderr and the actual failure body on stdout (tsc/
    // vitest do), so taking stderr-OR-stdout would drop the locatable reason
    // (codex R3). The 600-char tail below keeps the trailing end where the real
    // failure lands.
    const stderr = decodeChildOutput(e.stderr);
    const stdout = decodeChildOutput(e.stdout);
    if (stderr.length > 0) detail += `\nstderr: ${stderr}`;
    if (stdout.length > 0) detail += `\nstdout: ${stdout}`;
  }
  const tail = detail.length > 600 ? detail.slice(-600) : detail;
  return `family verify (${phase}) failed: ${tail}`;
}

/** Decode an execFileSync `stderr`/`stdout` field (string | Buffer | undefined) to trimmed text. */
function decodeChildOutput(v: unknown): string {
  if (typeof v === "string") return v.trim();
  if (v instanceof Buffer) return v.toString("utf8").trim();
  return "";
}

/**
 * The process exit status carried by an `execFileSync` throw (`err.status`), or
 * `undefined` if the error is not an exit-code failure (e.g. ENOENT spawning git).
 * Lets a git predicate tell a LEGIT non-zero (`merge-base --is-ancestor` exits 1 for
 * "not an ancestor") from an OPERATIONAL failure (exit 128: bad object / broken repo)
 * that must propagate rather than read as a false predicate (online R1 CodeRabbit).
 */
function gitExitStatus(err: unknown): number | undefined {
  const status = (err as { status?: unknown } | null)?.status;
  return typeof status === "number" ? status : undefined;
}
