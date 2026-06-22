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
import {
  appendFileSync,
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join } from "node:path";

import { z } from "zod";

import * as sc from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

import { runExclusive } from "../gitMutex.js";
import {
  branchForIssue,
  modelIdForSlug,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_SKILLS_DIR,
  SANDBOX_SOUL_ENV,
} from "../realBackend.js";
import {
  cmrWorkerSpec,
  familyShipWorkerSpec,
  legacyDispatchFamilyWorker,
} from "./dispatchFamilyWorker.js";
import {
  isFilledString,
  shipOutcomeFromResult,
  type ShipWorkerOutcome,
} from "../shipOutcome.js";

import type {
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../types.js";
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
 * Where the agy (antigravity / gemini) CLI reads its OAuth token + writes its
 * runtime config INSIDE the cmr worker container (#335 / #333 gotcha). The host
 * file `~/.sc-agy-oauth-token` is copied into a per-run dir mounted HERE as
 * `antigravity-oauth-token`. It is a WRITABLE dir (NOT read-only): the agy CLI
 * writes cache/log/state under its config dir, so a read-only mount would make the
 * agy cmr leg fail at startup and degrade the cmr to codex-only (the #333 spike's
 * agy leg only caught the injected bug WITH its file token mounted writable). The
 * path mirrors the host `~/.gemini/antigravity-cli/` exactly, the same
 * host-mirrored auth-mount pattern codex (`SANDBOX_CODEX_DIR`) uses.
 */
export const SANDBOX_AGY_DIR = "/home/agent/.gemini/antigravity-cli";
/** The agy OAuth token filename inside {@link SANDBOX_AGY_DIR}. */
export const AGY_TOKEN_FILENAME = "antigravity-oauth-token";

/**
 * The git-ignored cmr FOCUS file written into the family-base worktree (#335): it
 * pins the EXACT review-scope diff command (on the recorded cut SHA) + the
 * machine-resolved-child focus, so the in-container `ak-cross-m-review` scopes the
 * family diff correctly and prioritises machine-touched merges (#291 缺口 1).
 */
export const CMR_FOCUS_FILENAME = ".cmr-focus.md";

/**
 * The git-ignored SHIP FOCUS file written into the family-base worktree before the
 * family ship worker runs (cmr S336 r5): it pins the family base branch + the
 * CONFIGURED PR target base (`opts.base`) + the repo slug, so the in-container
 * `gstack-ship` opens the family PR against the RIGHT base. Without it gstack-ship
 * INFERS the base from the repo default branch (main) — silently regressing the
 * legacy `openFamilyPr` `gh pr create --base this.opts.base` contract whenever the
 * family run targets a non-main integration branch (e.g. `integ/291-wave3`).
 */
export const SHIP_FOCUS_FILENAME = ".ship-focus.md";

/** The cmr worker's completion signal (matches prompts/integrated_cmr.md). */
const CMR_COMPLETION_SIGNAL = "CMR_STEP_COMPLETE";
/** The READ-ONLY soul the cmr worker (a reviewer) runs under (ADR 0017 §4). */
const CMR_SOUL = "READ-ONLY";

/** The WRITE soul the ship worker runs under (it commits the bump + pushes). */
const SHIP_SOUL = "coder";

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
  /**
   * Where the deterministic verify commands (`npx tsc` / `npx vitest`) run. The
   * `workingRepo` clone is the FULL repo, but the Node project (package.json /
   * tsconfig / vitest config) lives in a subdir, so verify must run THERE, not at
   * the clone root (online R2 Codex P1: a root-cwd verify finds no project → a real
   * family run always returns verify_failed). Defaults to `workingRepo`.
   */
  readonly verifyCwd?: string;
  /** GitHub repo slug for `gh` (`owner/name`) — for openFamilyPr. */
  readonly repo: string;
  /** The base branch the family PR targets (e.g. an integration branch or "main"). */
  readonly base: string;
  /** Dir holding the versioned promptFiles (the merger conflict prompt). */
  readonly promptsDir: string;
  /** The profile image (souls + CLIs baked in) for the merger agent sandbox. */
  readonly imageName: string;
  /**
   * DEPRECATED (#334): host dir of dev skills to bind-mount for the merger. The
   * 2b image bakes `resolving-merge-conflicts`; `mergerSandboxConfig()` no longer
   * mounts host skills (a runtime mount would SHADOW the baked skill). Kept
   * OPTIONAL for back-compat; no longer read. Remove once callers drop it.
   */
  readonly skillsMount?: string;
  /**
   * The family base HEAD at run setup — the baseline {@link ReconcileGit.familyBaseStartHead}
   * returns (the spine provides it; the only baseline available when the ledger is
   * empty). Optional at construction, but REQUIRED before `reconcileGit()` is used
   * for the empty-ledger crash-window net: that predicate THROWS when it is absent
   * rather than falling back to the live head (which would silently disable the net
   * — codex R3). A backend that never drives reconcile may omit it.
   */
  readonly familyBaseStartHead?: string;
  /**
   * Override $HOME for the cmr worker's auth-source paths (`~/.codex/auth.json`,
   * `~/.sc-agy-oauth-token`, `~/.sc-claude-token`). Defaults to {@link homedir}.
   * Tests inject a fixture home so the auth copy/mount is exercised without the
   * real host credentials.
   */
  readonly home?: string;
}

/** The merger-agent prompt the conflict resolver runs (under the `merger` soul). */
const MERGER_CONFLICT_PROMPT = "merger_resolve_conflict.md";

/**
 * Every promptFile the family layer can dispatch — DERIVED from the worker specs
 * (the cmr / family-ship workers) + the local merger-conflict prompt, exactly the
 * way the single-slice {@link REFERENCED_PROMPT_FILES} (realBackend.ts) derives
 * its list from STEP_SPECS + shipWorkerSpec() (integ-cmr int-r1 C-3 / gap g). By
 * reading the prompt off the dispatched specs, a new/changed family worker step
 * can never silently drift out of the construction-time validation list. De-duped
 * (a Set) in case two specs share a promptFile across versions.
 */
export const REFERENCED_FAMILY_PROMPT_FILES: ReadonlyArray<string> = [
  ...new Set([
    cmrWorkerSpec().promptFile,
    familyShipWorkerSpec().promptFile,
    MERGER_CONFLICT_PROMPT,
  ]),
];
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
    this.validateFamilyPromptsDir();
  }

  /**
   * Fail fast at construction if `promptsDir` is not an absolute, existing dir
   * containing every {@link REFERENCED_FAMILY_PROMPT_FILES} entry (integ-cmr
   * int-r1 gap g, same-type as the single-slice C-3) — so a misconfiguration
   * surfaces HERE, not deep inside the first family worker dispatch (or, worse,
   * silently against the wrong dir via Sandcastle's process.cwd() resolution of
   * promptFile). `promptsDir` MUST be ABSOLUTE: Sandcastle resolves promptFile
   * against `process.cwd()`, NOT the run cwd, so a relative promptsDir would
   * silently resolve the family prompts against the wrong directory at run time.
   */
  private validateFamilyPromptsDir(): void {
    const dir = this.opts.promptsDir;
    if (!isAbsolute(dir)) {
      throw new Error(
        `RealFamilyBackend: promptsDir must be an ABSOLUTE path (got "${dir}"). ` +
          `Sandcastle resolves promptFile against process.cwd(), not the run cwd, ` +
          `so a relative promptsDir would resolve family prompts against the wrong dir.`,
      );
    }
    if (!(existsSync(dir) && statSync(dir).isDirectory())) {
      throw new Error(
        `RealFamilyBackend: promptsDir "${dir}" does not exist (or is not a directory).`,
      );
    }
    const missing = REFERENCED_FAMILY_PROMPT_FILES.filter(
      (f) => !existsSync(join(dir, f)),
    );
    if (missing.length > 0) {
      throw new Error(
        `RealFamilyBackend: promptsDir "${dir}" is missing required family ` +
          `promptFile(s): ${missing.join(", ")}. All of ` +
          `[${REFERENCED_FAMILY_PROMPT_FILES.join(", ")}] must be present (the ` +
          `family cmr / ship / merger workers reference them).`,
      );
    }
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

  /**
   * Build the container agent for a {@link WorkerSpec}: the top-level claude on the
   * model the spec declares, resolved through the SAME validated `modelIdForSlug`
   * mapping the single-slice ship path uses (realBackend.ts:2122). The lone seam
   * that turns `spec.model` into an `sc.claudeCode(...)` agent for BOTH family
   * WorkerSpec-driven runs (ship + cmr) — so neither can hardcode a model id that
   * bypasses validation or drifts from the slug the runner declares (cmr S336 r7
   * P1). `protected` + pure (no container/I/O) so a unit test asserts the resolved
   * model without spinning a real `sc.run` — mirroring how `modelIdForSlug` /
   * `soulForStep` are the testable seams on the single-slice path.
   */
  protected agentForSpec(spec: WorkerSpec): ReturnType<typeof sc.claudeCode> {
    return sc.claudeCode(modelIdForSlug(spec.model));
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
   *
   * #334 (ADR 0026 / cross-slice note): the runtime host skills bind-mount onto
   * {@link SANDBOX_SKILLS_DIR} is DROPPED here too — the 2b image BAKES
   * `resolving-merge-conflicts` (+ its closure), so a runtime mount would SHADOW
   * the baked skill. The merger soul finds the skill in the IMAGE, not a host
   * mount; the sandbox now sets only the soul env (auth is wired by #335/#336).
   */
  protected mergerSandboxConfig(): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string }>;
  } {
    return {
      imageName: this.opts.imageName,
      env: { [SANDBOX_SOUL_ENV]: MERGER_SOUL },
      // #334: no skills mount — the baked image provides the merger skill.
      mounts: [],
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
    // Run where the Node project lives (verifyCwd), NOT the clone root — else npx
    // finds no package.json/config (online R2 Codex P1).
    const cwd = this.opts.verifyCwd ?? this.opts.workingRepo;
    this.sh("npx", ["tsc", "--noEmit"], cwd);
    this.sh("npx", ["vitest", "run"], cwd);
  }

  // ─────────────────────── unified worker dispatch (#335) ───────────────────────

  /**
   * THE family worker-dispatch seam (ADR 0026 / #331 / #335). For the integrated
   * cmr step it dispatches a real CONTAINER cmr WORKER that invokes
   * `ak-cross-m-review` (this slice, #335). Every other family worker kind (the
   * family ship/PR, #336) is forwarded to the legacy wrapper until its own slice
   * wires it — so this method takes over ONLY the cmr leg now (the legacy
   * `openFamilyPr` still backs the ship leg until #336).
   *
   * The cmr worker (`cmrWorkerSpec`) = the 2b container's TOP-LEVEL claude; it
   * `Skill`-invokes ak-cross-m-review (1 Agent + 2 CLI legs in-container, #333),
   * FRESH each round (cross-model independence — ADR 0026). It returns a BARE
   * `{converged, reason?}` verdict: the consumer (`verifyCmr.ts`) is escalate-on-red,
   * NO fix-loop at this layer (PRD #330 R2), so NO findings array is needed. A red
   * verdict is `WorkerResult.completed` (a CmrResult payload), NOT `failed`.
   */
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (spec.kind === "ship") {
      // #336: the family ship step (止于 PR) is a CONTAINER ship WORKER invoking
      // `gstack-ship` (replacing the inline `openFamilyPr`).
      return this.dispatchShipWorker(spec, ctx);
    }
    if (spec.kind !== "cmr") {
      // Any other family worker kind (merge — B 段) forwards to the legacy seam.
      return legacyDispatchFamilyWorker(this, spec, ctx);
    }
    if (ctx.familyBase === undefined) {
      throw new Error(
        "dispatchWorker(cmr): a family cmr worker requires ctx.familyBase (the " +
          "merged base whose diff the cross-model review audits).",
      );
    }
    const outcome = await this.runCmrWorker(spec, ctx);
    if (outcome.kind === "escalate") {
      // A model-stuck cmr worker (missing skill / no leg ran / could not produce a
      // verdict) is the WorkerResult-level escalate (續跑 path), NOT a fabricated
      // pass — verifyCmr.ts calls escalateFamily with this reason.
      return {
        kind: "escalated",
        escalation: { reason: outcome.reason, diagnosis: outcome.diagnosis },
      };
    }
    if (outcome.kind === "malformed") {
      // No parseable verdict ⇒ malformed (the gate must never read it as a pass).
      return { kind: "malformed", reason: outcome.reason };
    }
    return {
      kind: "completed",
      output: {
        kind: "cmr",
        converged: outcome.converged,
        ...(outcome.reason !== undefined ? { reason: outcome.reason } : {}),
      },
    };
  }

  // ─────────────────────────── integrated cmr ───────────────────────────

  /**
   * LEGACY per-method integrated-cmr seam (#331 capability gate). #335 routes the
   * real cmr through `dispatchWorker` (the container worker), so this default
   * THROWS — it is reached only if a caller bypasses the unified seam, and the
   * assembly test pins the throw to prove the bypass is not a silent fabricated
   * pass. (Kept so a #296-era consumer that reaches `runIntegratedCmr` directly
   * still type-checks; `dispatchFamilyWorker` prefers `dispatchWorker`.)
   */
  async runIntegratedCmr(request: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    return this.runCmr(request);
  }

  /**
   * The default `runIntegratedCmr` body: THROW. The real `ak-cross-m-review` runs
   * as the container cmr WORKER via `dispatchWorker` (#335), not this per-method
   * path. `protected` so the e2e / a unit test may still override it for the legacy
   * gate, but the production path no longer reaches it.
   */
  protected async runCmr(request: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    void request;
    throw new Error(
      "runIntegratedCmr: the real ak-cross-m-review is dispatched as the container " +
        "cmr WORKER via dispatchWorker (#335); this per-method seam is no longer " +
        "the production path. Dispatch through dispatchFamilyWorker.",
    );
  }

  /**
   * Run the integrated cmr WORKER: ONE `sc.run` of the 2b container's top-level
   * claude invoking `ak-cross-m-review` over the merged family base diff (#335).
   * `protected` so a unit test fixtures the outcome without a real container (the
   * real container only runs on the driver / manual-smoke / e2e path).
   *
   * The worker is the container's TOP-LEVEL agent (so it can start its own Agent +
   * CLI legs — ADR 0026), FRESH (`branchStrategy: head` keeps it on the resident
   * family base; review never commits), under the READ-ONLY soul. Its `<cmr>` tag
   * verdict is gated on the completion signal then parsed into a
   * {@link CmrWorkerOutcome}.
   */
  protected async runCmrWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<CmrWorkerOutcome> {
    // FAIL-CLOSED before any container work (codex cmr R3): the focus file pins the
    // EXACT cut-SHA review-scope diff (prompt contract integrated_cmr.md:19-24 — do
    // NOT guess main...HEAD). With no recorded cut SHA there is no honest scope to
    // hand the review, and a `main...familyBase` fallback would silently disable the
    // load-bearing scope — the same fail-open the reconcile `familyBaseStartHead()`
    // predicate refuses (this file ~877-895). So escalate (verifyCmr routes it as
    // not-passed续跑) rather than checking out the base + spinning the container only
    // to review the wrong scope.
    if (this.opts.familyBaseStartHead === undefined) {
      return {
        kind: "escalate",
        reason:
          "no familyBaseStartHead (cut SHA) recorded — cannot pin the cmr review scope",
        diagnosis:
          "the integrated cmr focus file must pin the EXACT git diff <cut SHA>...<familyBase> " +
          "scope (integrated_cmr.md:19-24); refusing to fall back to a possibly-stale " +
          "main...HEAD scope (a fail-open that would review the wrong diff). Provide " +
          "RealFamilyBackendOptions.familyBaseStartHead.",
      };
    }
    // FAIL-CLOSED on the WORKER's OWN auth (codex cmr R4): the cmr worker is the
    // container's TOP-LEVEL claude (`agent: sc.claudeCode` below), so the Claude
    // OAuth token is NOT a mere reviewer leg — it is THIS worker's auth. Absent, the
    // worker cannot start and never emits a `<cmr>` verdict; that failure would
    // throw out of `sc.run` (NOT a structured escalate), bypassing verifyCmr's
    // escalate routing (a fail-open — the gate is crashed, not honestly escalated).
    // codex/agy auth stay best-effort reviewer LEGS (they degrade in-container); the
    // Claude token alone is load-bearing for the worker itself. Mount once and reuse
    // for the sandbox (no double-mount). The cut-SHA guard above runs first; this is
    // the second fail-closed precondition, both BEFORE any container work.
    const auth = this.mountCmrAuth();
    if (auth.claudeToken === undefined) {
      return {
        kind: "escalate",
        reason: "no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — the cmr worker cannot start",
        diagnosis:
          "the integrated cmr worker is the container's top-level claude (sc.claudeCode); " +
          "its OAuth token (~/.sc-claude-token → CLAUDE_CODE_OAUTH_TOKEN) is the worker's " +
          "OWN auth, not a degradable reviewer leg. Without it the worker fails to start " +
          "and never emits a verdict; escalating here keeps the escalate续跑 semantics " +
          "(a thrown sc.run startup error would bypass verifyCmr's structured routing).",
      };
    }
    // Check out the family base so the in-container ak-cross-m-review reviews the
    // RIGHT base diff (ctx.familyBase is the contract input — dispatchWorker
    // already asserted it is present). The cmr worker runs as the container's
    // top-level claude over THIS checked-out base.
    this.sh("git", ["checkout", ctx.familyBase!], this.opts.workingRepo);
    // codex cmr R1 (F3+F2): thread the EXACT review scope + the LLM-resolved-child
    // FOCUS into the worker via a git-ignored focus file the prompt reads — the
    // skill can't reliably scope the family diff on its own (a stale local base
    // ref pollutes `main...HEAD`; non-`main` targets diff the wrong ref), and the
    // #291 缺口-1 focus signal must not be silently dropped. The focus file pins the
    // exact `git diff <familyBaseStartHead>...<familyBase>` scope command + the
    // baseline SHA + the machine-resolved children.
    this.writeCmrFocusFile(ctx);
    const result = await sc.run({
      name: "family-cmr",
      cwd: this.opts.workingRepo,
      sandbox: this.cmrSandbox(auth),
      // Derive the model from the spec via the shared validated seam (cmr S336 r7
      // symmetry): `cmrWorkerSpec().model === "opus"` resolves to claude-opus-4-8.
      // Same途径 the single-slice + family ship paths use — no constant that could
      // silently drift from the spec the runner declares.
      agent: this.agentForSpec(spec),
      // The cmr worker is a single review pass (ADR 0026: review = clean eyes, one
      // pass; a non-convergence is the runner's escalate fork, not a within-worker
      // loop).
      maxIterations: spec.maxIter,
      completionSignal: spec.completionSignal,
      // FRESH but on the resident family base — review must never commit (the
      // worktree is read; `head` keeps it in place, no detached temp checkout).
      branchStrategy: { type: "head" },
      promptFile: join(this.opts.promptsDir, spec.promptFile),
    });
    return cmrOutcomeFromResult(result);
  }

  /**
   * Write the git-ignored cmr FOCUS file into the family-base worktree (codex cmr
   * R1 F2+F3): the EXACT review scope + the machine-resolved-child focus. The
   * worker's prompt reads it so the in-container `ak-cross-m-review` scopes the
   * family diff on the recorded cut SHA (`familyBaseStartHead`) — not a
   * possibly-stale `main...HEAD` — and prioritises the merges a machine touched
   * (#291 缺口 1). `protected` so a unit test can fixture it without a real worktree.
   *
   * FAIL-CLOSED (codex cmr R3): the cut SHA is the ONLY honest review scope, so a
   * missing `familyBaseStartHead` THROWS rather than emitting a stale-base fallback
   * scope command — mirrors the reconcile `familyBaseStartHead()` predicate
   * (~877-895), which refuses to fall back to the live head. The caller
   * (`runCmrWorker`) already guards this up-front and escalates; this throw is the
   * load-bearing backstop so the seam can never silently regress to a guessed scope.
   */
  protected writeCmrFocusFile(ctx: DispatchContext): void {
    const familyBase = ctx.familyBase!;
    const startHead = this.opts.familyBaseStartHead;
    if (startHead === undefined) {
      throw new Error(
        "writeCmrFocusFile: no familyBaseStartHead (cut SHA) recorded — the focus " +
          "file must pin the EXACT git diff <cut SHA>...<familyBase> review scope " +
          "(integrated_cmr.md:19-24); refusing to emit a stale-base fallback scope " +
          "(a fail-open that would review the wrong diff). Provide " +
          "RealFamilyBackendOptions.familyBaseStartHead.",
      );
    }
    const scope = `git diff ${startHead}...${familyBase}`;
    const focusLine =
      ctx.llmResolvedChildren !== undefined && ctx.llmResolvedChildren.length > 0
        ? `Machine-resolved child merges (a machine resolved a conflict — review their merge seams with SPECIAL care): ${ctx.llmResolvedChildren
            .map((n) => `#${n}`)
            .join(", ")}.`
        : "No machine-resolved child merges this run.";
    const body =
      `# Integrated cmr — review scope + focus (machine-generated; #335)\n\n` +
      `Review THIS exact family-base diff (the commits the family base added since it\n` +
      `was cut from its target):\n\n    ${scope}\n\n${focusLine}\n`;
    // Git-ignore it (it is a transient runtime artifact, never committed) then write.
    const target = join(this.opts.workingRepo, CMR_FOCUS_FILENAME);
    this.excludeCmrFocusFromGit();
    writeFileSync(target, body, "utf8");
  }

  /** Add the cmr focus file to the worktree's local git excludes (never committed). */
  protected excludeCmrFocusFromGit(): void {
    try {
      const excludePath = join(
        this.sh("git", ["rev-parse", "--git-dir"], this.opts.workingRepo),
        "info",
        "exclude",
      );
      const abs = isAbsolute(excludePath)
        ? excludePath
        : join(this.opts.workingRepo, excludePath);
      let existing = "";
      try {
        existing = readFileSync(abs, "utf8");
      } catch {
        // no exclude file yet
      }
      if (!existing.split("\n").includes(CMR_FOCUS_FILENAME)) {
        mkdirSync(join(abs, ".."), { recursive: true });
        appendFileSync(abs, (existing.endsWith("\n") || existing === "" ? "" : "\n") + CMR_FOCUS_FILENAME + "\n", "utf8");
      }
    } catch {
      // Best-effort: if excludes can't be written the file is still produced; the
      // review never commits (branchStrategy head + READ-ONLY soul), so a stray
      // untracked file is harmless.
    }
  }

  /**
   * The cmr worker's sandbox (souls + skills + CLIs baked into the 2b image).
   * `runCmrWorker` mounts the auth ONCE up-front (so it can fail-closed on the
   * worker's own Claude token — codex cmr R4) and passes it here, avoiding a
   * double-mount; the arg defaults to a fresh mount for any other caller.
   */
  protected cmrSandbox(auth: CmrAuth = this.mountCmrAuth()): sc.SandboxProvider {
    return docker(this.cmrSandboxConfig(auth));
  }

  /**
   * Copy the three reviewer legs' host credentials into per-run dirs the cmr
   * sandbox mounts (#335). codex auth + the agy OAuth token are file/dir mounts;
   * the claude leg uses the durable OAuth token env var. Mirrors
   * `RealBackend.mountAuth`. The agy token is copied into a per-run dir mounted
   * WRITABLE (the agy CLI writes runtime state under its config dir — #333 gotcha).
   */
  protected mountCmrAuth(): CmrAuth {
    const home = this.opts.home ?? homedir();
    const root = join(home, ".sc-orchestrator");

    // codex cmr R1 (high): EACH leg's auth is BEST-EFFORT. The cmr contract is a
    // 降级链 — a leg whose auth is absent must let that leg DEGRADE (the skill drops
    // it; a missing reviewer is not a finding), NOT crash the whole gate. A hard
    // `copyFileSync` throw here would propagate out of `dispatchWorker` (verifyCmr
    // does not convert a thrown error into a structured WorkerResult), failing the
    // gate even when the OTHER legs could review. So a missing source ⇒ omit that
    // leg's auth (undefined) and let it degrade in-container.

    // codex auth.json (+ optional config.toml) → a per-run owner-only dir.
    let codexAuthDir: string | undefined;
    try {
      // Per-INVOCATION unique dir (codex cmr R2): a fixed path would be rmSync'd
      // + rebuilt under a concurrent family CMR worker, deleting the dir it has
      // mounted. mkdtempSync gives each invocation its own owner-only (0700) dir.
      mkdirSync(root, { recursive: true, mode: 0o700 });
      const dir = mkdtempSync(join(root, "cmr-codex-auth-"));
      copyFileSync(join(home, ".codex", "auth.json"), join(dir, "auth.json"));
      chmodSync(join(dir, "auth.json"), 0o600);
      try {
        copyFileSync(join(home, ".codex", "config.toml"), join(dir, "config.toml"));
        chmodSync(join(dir, "config.toml"), 0o600);
      } catch {
        // config.toml is optional.
      }
      codexAuthDir = dir;
    } catch {
      // codex auth absent ⇒ the codex leg degrades (no mount).
    }

    // agy OAuth token → a per-run WRITABLE dir mounted at the antigravity config
    // path (the agy CLI writes cache/log under its config dir, so it must NOT be
    // read-only — #333 gotcha).
    let agyDir: string | undefined;
    try {
      // Per-INVOCATION unique dir (codex cmr R2): same concurrency hazard as the
      // codex dir above — and the agy dir is mounted WRITABLE, so a shared path
      // would also cross-talk runtime state between concurrent workers.
      mkdirSync(root, { recursive: true, mode: 0o700 });
      const dir = mkdtempSync(join(root, "cmr-agy-"));
      copyFileSync(join(home, ".sc-agy-oauth-token"), join(dir, AGY_TOKEN_FILENAME));
      chmodSync(join(dir, AGY_TOKEN_FILENAME), 0o600);
      agyDir = dir;
    } catch {
      // agy token absent ⇒ the agy leg degrades (no mount); cmr falls to the rest.
    }

    let claudeToken: string | undefined;
    try {
      claudeToken = readFileSync(join(home, ".sc-claude-token"), "utf8").trim();
    } catch {
      // claude token absent ⇒ the Claude Agent leg degrades (no env var).
    }
    return { codexAuthDir, agyDir, claudeToken };
  }

  /**
   * The docker options the cmr worker sandbox runs under — the pure SANDBOX-CONFIG
   * seam (mirrors `mergerSandboxConfig` / `RealBackend.boxConfig` testability). No
   * container, no I/O: a unit test asserts the mounts + soul env without a real
   * sandbox.
   *
   * Wires ALL THREE reviewer legs' auth (#335 / #333 gotcha): the codex auth dir
   * (host-mirrored `~/.codex`), the agy OAuth token (host-mirrored
   * `~/.gemini/antigravity-cli`, mounted WRITABLE — the leg writes runtime state
   * there), and the claude OAuth token (env var). Without the agy mount the agy
   * cmr leg has no auth and the cmr degrades to codex-only. NO skills mount: the 2b
   * image BAKES ak-cross-m-review + its closure (#333) — a runtime mount would
   * SHADOW the baked skill (#334). READ-ONLY soul (the cmr worker is a reviewer).
   */
  protected cmrSandboxConfig(auth: CmrAuth): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    const env: Record<string, string> = { [SANDBOX_SOUL_ENV]: CMR_SOUL };
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [];
    // Each leg's auth is mounted only when present (the 降级链 — a missing leg
    // degrades, the rest still review). The agy dir is WRITABLE (default, no
    // `readonly`); codex auth likewise. No skills mount — the baked image wins (#334).
    if (auth.codexAuthDir !== undefined) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    if (auth.agyDir !== undefined) {
      mounts.push({ hostPath: auth.agyDir, sandboxPath: SANDBOX_AGY_DIR });
    }
    return { imageName: this.opts.imageName, env, mounts };
  }

  // ─────────────────────────── ship WORKER (止于 PR) ───────────────────────────

  /**
   * Dispatch the FAMILY ship WORKER (#336): a CONTAINER ship worker invoking
   * `gstack-ship` over the family base, 止于 PR (the online bot cmr + merge are the
   * separate pr-review-loop stage). Maps the {@link ShipWorkerOutcome} to the full
   * {@link WorkerResult} union (PRD #330 R2): shipped → `completed` ShipResult; a
   * genuine block → `escalated`; a hard ship/test failure → `failed`; unparseable →
   * `malformed`. A rerun-able flake is NOT escalated — the worker reruns it itself.
   */
  protected async dispatchShipWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<WorkerResult> {
    if (ctx.familyBase === undefined) {
      throw new Error(
        "dispatchWorker(ship): a family ship worker requires ctx.familyBase (the " +
          "merged base gstack-ship delivers as the family PR).",
      );
    }
    const outcome = await this.runShipWorker(spec, ctx);
    if (outcome.kind === "escalate") {
      // A genuine block (merge conflict / review ASK / hard defect a human must
      // decide) — the family escalate续跑 path (verifyCmr calls escalateFamily).
      return {
        kind: "escalated",
        escalation: { reason: outcome.reason, diagnosis: outcome.diagnosis },
      };
    }
    if (outcome.kind === "failed") {
      // A hard ship/test failure no rerun cleared → the family PR could not open
      // (verifyCmr fail-safes a non-ship/non-completed result to INCOMPLETE_GATE).
      return { kind: "failed", reason: `${outcome.reason} — ${outcome.diagnosis}` };
    }
    if (outcome.kind === "malformed") {
      return { kind: "malformed", reason: outcome.reason };
    }
    // Branch-identity check (cmr S336 r3 F1): the worker self-reports `branch`, and
    // a worker that ships some OTHER branch (e.g. the PR target base) but reports it
    // as a success must NOT be read as the family delivery → verifyCmr would return
    // ok:true on a PR for the wrong branch. prompts/family_ship.md pins the family
    // base (the worker `git checkout`s ctx.familyBase, `branchStrategy:{type:"head"}`)
    // and asks it to report THE family base branch — no legitimate rename path — so an
    // `outcome.branch` ≠ `ctx.familyBase` is off-contract → malformed.
    if (outcome.branch !== ctx.familyBase) {
      return {
        kind: "malformed",
        reason: `family ship worker reported branch "${outcome.branch}" but was asked to deliver the family base "${ctx.familyBase}" (a ship of a different branch is not the family delivery)`,
      };
    }
    // Fail-CLOSED on the FAMILY contract (prompts/family_ship.md): a family ship
    // delivery is a family PR — the ONLY accepted shipped status is "pr_opened"
    // with a `pr` URL. The shared parser also accepts "pushed" (legal for a SINGLE
    // slice, prompts/ship.md), so a family worker that pushed-but-opened-no-PR
    // would otherwise be read as a completed family delivery → verifyCmr ok:true on
    // a PHANTOM family PR (cmr S336 r2 F1). The single-slice consumer keeps "pushed"
    // (legal there); only THIS family consumer narrows it (verifyCmr never reads
    // success on a non-PR family ship). The `pr` belt uses isFilledString as
    // defense-in-depth (the parser already enforces non-empty pr — cmr S336 r3).
    if (outcome.status !== "pr_opened" || !isFilledString(outcome.pr)) {
      return {
        kind: "malformed",
        reason: `family ship worker reported status "${outcome.status}" — the family delivery must be "pr_opened" with a \`pr\` URL (family_ship.md allows only pr_opened; "pushed" is single-slice only)`,
      };
    }
    return {
      kind: "completed",
      output: {
        kind: "ship",
        branch: outcome.branch,
        status: outcome.status,
        pr: outcome.pr,
      },
    };
  }

  /**
   * Run the family ship WORKER: ONE `sc.run` of the 2b container's top-level claude
   * invoking `gstack-ship` over the checked-out family base (#336). `protected` so a
   * unit test fixtures the outcome without a real container (the real container only
   * runs on the driver / manual-smoke / e2e path).
   *
   * The worker is the container's TOP-LEVEL agent (gstack-ship's pipeline + any
   * rerun loops run inside it — ADR 0026), under the WRITE (`coder`) soul (it
   * commits the VERSION/CHANGELOG bump + pushes + opens the PR).
   * `branchStrategy:{type:"head"}` keeps it on the checked-out family base. Its
   * `<ship>` tag is gated on the completion signal then classified.
   */
  protected async runShipWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ShipWorkerOutcome> {
    // FAIL-CLOSED on the WORKER's OWN auth (cmr S336 r8, mirroring the cmr worker's
    // preflight ~645-666): the ship worker is the container's TOP-LEVEL claude
    // (`agent: sc.claudeCode` in shipContainerRun), so the Claude OAuth token is NOT
    // a degradable codex/gh LEG — it is THIS worker's auth. Absent, the worker cannot
    // start and never emits a `<ship>` verdict; that failure would throw out of
    // `sc.run` (NOT a structured escalate), bypassing the WorkerResult routing
    // (dispatchShipWorker → verifyCmr only handle the RETURNED result, never a thrown
    // startup error — a fail-open that crashes the gate rather than honestly
    // escalating). gh auth is ALSO preflighted below (cmr S336 r10): it is
    // load-bearing for `gh pr create` (the family delivery), NOT a degradable leg.
    // Only codex auth stays best-effort (in-container diff review). Preflight BEFORE
    // any container work (the checkout + focus write below) so a no-token host
    // escalates cleanly. Mount once and reuse for the sandbox (no double-mount).
    const auth = this.mountShipAuth();
    if (auth.claudeToken === undefined) {
      return {
        kind: "escalate",
        reason: "no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — the ship worker cannot start",
        diagnosis: "ship worker cannot start without CLAUDE_CODE_OAUTH_TOKEN",
      };
    }
    // FAIL-CLOSED on gh auth (cmr S336 r10): the family delivery's ONLY accepted
    // outcome is "pr_opened" (family_ship.md) — gstack-ship reaches it via `gh pr
    // create --base`. The 2b image bakes the gh CLI but no gh auth, so a no-gh host
    // would run the whole pipeline only to fail at `gh pr create` (an opaque late
    // failure, not the cleaner escalate续跑). codex auth stays best-effort. Preflight
    // BEFORE the checkout / focus write / container — symmetric with the single-slice
    // path. The token is read via `gh auth token` (OS keyring, not a portable file)
    // and injected as GH_TOKEN by shipSandboxConfig.
    if (auth.ghToken === undefined) {
      return {
        kind: "escalate",
        reason: "no gh auth (GH_TOKEN) — the family ship worker cannot `gh pr create`",
        diagnosis:
          "the family ship worker invokes gstack-ship, whose family delivery is a PR " +
          "(`gh pr create --base`); the 2b image bakes the gh CLI but no gh auth. " +
          "Provide a host gh login (`gh auth login`) so `gh auth token` yields a token " +
          "to inject as GH_TOKEN. Escalating here keeps the escalate续跑 semantics (a " +
          "late in-container `gh pr create` failure would surface as an opaque error).",
      };
    }
    // Check out the family base so gstack-ship delivers the RIGHT branch.
    this.sh("git", ["checkout", ctx.familyBase!], this.opts.workingRepo);
    // cmr S336 r5: thread the CONFIGURED PR target base into the worker via a
    // git-ignored focus file the prompt reads FIRST. gstack-ship otherwise INFERS
    // the base from the repo default branch (main), regressing the legacy
    // `openFamilyPr` `gh pr create --base this.opts.base` contract on a non-main
    // target. Written AFTER the checkout (the file lives in the family-base
    // worktree) and BEFORE the container so the worker can read it.
    this.writeShipFocusFile(ctx);
    const result = await this.shipContainerRun(spec, auth);
    return shipOutcomeFromResult(result);
  }

  /**
   * The single `sc.run` that spins the family ship container (gstack-ship over the
   * checked-out family base). `protected` so a unit test traps the container launch
   * (asserting the focus file is already on disk) without a real docker run.
   * `branchStrategy:{type:"head"}` keeps it on the checked-out family base.
   */
  protected async shipContainerRun(
    spec: WorkerSpec,
    auth: ShipAuth = this.mountShipAuth(),
  ): Promise<Awaited<ReturnType<typeof sc.run>>> {
    return sc.run({
      name: "family-ship",
      cwd: this.opts.workingRepo,
      sandbox: this.shipSandbox(auth),
      // Derive the model from the spec via the SAME validated mapping the
      // single-slice ship path uses (realBackend.ts:2122) — NOT a hardcoded id.
      // A hardcoded family model bypassed `modelIdForSlug` AND pinned a DIFFERENT
      // id (claude-sonnet-4-5) than the verified `sonnet → claude-sonnet-4-6`
      // mapping `familyShipWorkerSpec().model` resolves to (cmr S336 r7 P1).
      agent: this.agentForSpec(spec),
      maxIterations: spec.maxIter,
      completionSignal: spec.completionSignal,
      branchStrategy: { type: "head" },
      promptFile: join(this.opts.promptsDir, spec.promptFile),
    });
  }

  /**
   * Write the git-ignored SHIP FOCUS file into the family-base worktree (cmr S336
   * r5): the family base branch + the CONFIGURED PR target base (`opts.base`) + the
   * repo slug. The worker's prompt reads it FIRST so the in-container `gstack-ship`
   * opens the family PR against the configured base instead of its inferred repo
   * default — preserving the legacy `openFamilyPr` `--base this.opts.base` contract
   * (the lone load-bearing item gstack-ship cannot infer: `--head` = the checked-out
   * branch, `--repo` = the clone's origin, title/body/CHANGELOG = the skill's own,
   * push = the skill's; ONLY the non-default target base is unknowable to it).
   * `protected` so a unit test can fixture it without a real worktree.
   */
  protected writeShipFocusFile(ctx: DispatchContext): void {
    const familyBase = ctx.familyBase!;
    const body =
      `# Family ship — PR target (machine-generated; cmr S336 r5)\n\n` +
      `Ship the family base **${familyBase}** and open ONE PR — 止于 PR.\n\n` +
      `Open the PR against THIS exact target base (do NOT let gstack-ship infer the\n` +
      `repo default branch — the family run may target a non-main integration branch):\n\n` +
      `    PR target base: ${this.opts.base}\n` +
      `    PR head branch: ${familyBase}\n` +
      `    GitHub repo:    ${this.opts.repo}\n\n` +
      `When gstack-ship detects the base branch, OVERRIDE its inference with the\n` +
      `\`PR target base\` above (\`gh pr create --base ${this.opts.base} --head ${familyBase}\`).\n`;
    // Git-ignore it (it is a transient runtime artifact, never committed) then write.
    const target = join(this.opts.workingRepo, SHIP_FOCUS_FILENAME);
    this.excludeShipFocusFromGit();
    writeFileSync(target, body, "utf8");
  }

  /** Add the ship focus file to the worktree's local git excludes (never committed). */
  protected excludeShipFocusFromGit(): void {
    try {
      const excludePath = join(
        this.sh("git", ["rev-parse", "--git-dir"], this.opts.workingRepo),
        "info",
        "exclude",
      );
      const abs = isAbsolute(excludePath)
        ? excludePath
        : join(this.opts.workingRepo, excludePath);
      let existing = "";
      try {
        existing = readFileSync(abs, "utf8");
      } catch {
        // no exclude file yet
      }
      if (!existing.split("\n").includes(SHIP_FOCUS_FILENAME)) {
        mkdirSync(join(abs, ".."), { recursive: true });
        appendFileSync(
          abs,
          (existing.endsWith("\n") || existing === "" ? "" : "\n") + SHIP_FOCUS_FILENAME + "\n",
          "utf8",
        );
      }
    } catch {
      // Best-effort: if excludes can't be written the file is still produced; the
      // ship worker delivers the family base, and a stray untracked focus file is
      // harmless (gstack-ship ships the family base's TRACKED commits).
    }
  }

  /** The family ship worker's sandbox (souls + skills + CLIs baked into the 2b image). */
  protected shipSandbox(auth: ShipAuth = this.mountShipAuth()): sc.SandboxProvider {
    return docker(this.shipSandboxConfig(auth));
  }

  /**
   * Gather the ship worker's host credentials (#336): the codex auth dir (mounted),
   * the claude OAuth token (env), and the gh OAuth token (`gh auth token` → GH_TOKEN
   * env, cmr S336 r10 — `gh pr create` needs it; the 2b image bakes gh but no gh
   * auth). The worker is the container's TOP-LEVEL claude (so the claude token is its
   * OWN auth). Gathering is fail-soft per source (a missing one ⇒ undefined); the
   * REQUIRE gates (claude + gh) live in `runShipWorker`'s preflight, the codex leg
   * degrades silently.
   */
  protected mountShipAuth(): ShipAuth {
    const home = this.opts.home ?? homedir();
    const root = join(home, ".sc-orchestrator");
    let codexAuthDir: string | undefined;
    try {
      mkdirSync(root, { recursive: true, mode: 0o700 });
      const dir = mkdtempSync(join(root, "ship-codex-auth-"));
      copyFileSync(join(home, ".codex", "auth.json"), join(dir, "auth.json"));
      chmodSync(join(dir, "auth.json"), 0o600);
      try {
        copyFileSync(join(home, ".codex", "config.toml"), join(dir, "config.toml"));
        chmodSync(join(dir, "config.toml"), 0o600);
      } catch {
        // config.toml is optional.
      }
      codexAuthDir = dir;
    } catch {
      // codex auth absent ⇒ the codex leg degrades (no mount). gh is NOT here — it is
      // the separate, preflighted ghToken (cmr S336 r10).
    }
    let claudeToken: string | undefined;
    try {
      claudeToken = readFileSync(join(home, ".sc-claude-token"), "utf8").trim();
    } catch {
      // claude token absent ⇒ the top-level claude worker degrades (no env var).
    }
    return { codexAuthDir, claudeToken, ghToken: this.readGhToken() };
  }

  /**
   * Read the host's gh OAuth token via `gh auth token` (cmr S336 r10) — the same
   * extraction the single-slice ship uses (`RealBackend.readGhToken`). The token
   * lives in the host's OS keyring (not a portable hosts.yml), so we extract it with
   * gh itself and inject it as {@link SANDBOX_GH_TOKEN_ENV}. Returns undefined when gh
   * is unauthenticated / absent (the `runShipWorker` preflight then escalates — gh is
   * a hard requirement for the family PR). `protected` so a unit test stubs it.
   */
  protected readGhToken(): string | undefined {
    try {
      const tok = this.sh("gh", ["auth", "token"]).trim();
      return tok === "" ? undefined : tok;
    } catch {
      // gh unauthenticated / absent ⇒ no token; runShipWorker escalates.
      return undefined;
    }
  }

  /**
   * The docker options the family ship sandbox runs under — the pure SANDBOX-CONFIG
   * seam (mirrors `cmrSandboxConfig` / `RealBackend.shipSandboxConfig`). No
   * container, no I/O: a unit test asserts the mounts + soul env. The ship worker
   * runs under the WRITE (`coder`) soul (it commits the bump + pushes), with codex
   * auth + the claude token + the gh token (GH_TOKEN, cmr S336 r10), NO skills mount
   * (the 2b image BAKES gstack-ship — a runtime mount would SHADOW it, #334).
   */
  protected shipSandboxConfig(auth: ShipAuth): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string }>;
  } {
    const env: Record<string, string> = { [SANDBOX_SOUL_ENV]: SHIP_SOUL };
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    // cmr S336 r10: the in-container `gh pr create` (the family delivery) reads
    // GH_TOKEN. Set only when present (the pure seam stays tolerant; the REQUIRE-gh
    // gate is the runShipWorker preflight — symmetric with the single-slice path).
    if (auth.ghToken !== undefined) env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    const mounts: { hostPath: string; sandboxPath: string }[] = [];
    if (auth.codexAuthDir !== undefined) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    return { imageName: this.opts.imageName, env, mounts };
  }

  // ─────────────────────────── open PR (止于 PR) — legacy inline ───────────────

  /**
   * LEGACY inline 止于 PR (push family base + `gh pr create`). RETAINED as a
   * `protected`-style fallback the production seam no longer reaches: ADR 0026 /
   * #336 makes 止于 PR a ship WORKER (gstack-ship via {@link dispatchShipWorker}).
   * A direct caller (a test / a back-compat path bypassing the unified seam) may
   * still reach it; verifyCmr always dispatches through dispatchFamilyWorker.
   */
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

// ─────────────────────────── cmr worker outcome (#335) ───────────────────────────

/**
 * The classified outcome of the integrated cmr WORKER's run (#335). One of:
 *   - `verdict`   — the worker produced a bare `{converged, reason?}` cross-model
 *     verdict (the normal case; `verifyCmr.ts` reads `converged`);
 *   - `escalate`  — the worker is model-stuck (skill missing / no leg ran / it
 *     could not produce a verdict) ⇒ the runner's escalate续跑 fork, NOT a pass;
 *   - `malformed` — the run emitted no parseable `<cmr>` tag ⇒ the gate must never
 *     read it as a pass (fail-closed).
 * Deliberately NOT the bare {@link IntegratedCmrResult}: a cmr worker also has the
 * escalate / malformed WorkerResult-level cases the bare verdict cannot carry.
 */
export type CmrWorkerOutcome =
  | { readonly kind: "verdict"; readonly converged: boolean; readonly reason?: string }
  | { readonly kind: "escalate"; readonly reason: string; readonly diagnosis: string }
  | { readonly kind: "malformed"; readonly reason: string };

/**
 * The cmr worker's reviewer-leg auth, each leg BEST-EFFORT (codex cmr R1): a leg
 * whose host credential is absent is `undefined` so it degrades (the 降级链 — the
 * skill drops that leg, the rest still review), never crashing the whole gate.
 */
export interface CmrAuth {
  /** Per-run codex auth dir (host-mirrored `~/.codex`), or undefined if absent. */
  readonly codexAuthDir?: string;
  /** Per-run agy token dir (host-mirrored antigravity config), or undefined. */
  readonly agyDir?: string;
  /** The claude OAuth token (env var), or undefined if absent. */
  readonly claudeToken?: string;
}

/**
 * The family ship worker's auth (#336). The codex dir is BEST-EFFORT (mirrors
 * {@link CmrAuth} — it only feeds the in-container diff review); the claude token
 * (the top-level worker's own auth) and the gh token (the `gh pr create` the family
 * delivery requires) are LOAD-BEARING — `runShipWorker` preflights both and escalates
 * when either is absent (cmr S336 r8 + r10). A missing codex source degrades that
 * mount rather than crashing the gate.
 */
export interface ShipAuth {
  /** Per-run codex auth dir (host-mirrored `~/.codex`), or undefined if absent. */
  readonly codexAuthDir?: string;
  /** The claude OAuth token (env var), or undefined if absent. */
  readonly claudeToken?: string;
  /**
   * The gh OAuth token (`gh auth token` on the host → {@link SANDBOX_GH_TOKEN_ENV}
   * env), or undefined if absent. NOT best-effort: the family delivery is a PR
   * (`gh pr create`), so `runShipWorker` preflights it and escalates when absent.
   */
  readonly ghToken?: string;
}

/**
 * Decide the cmr worker outcome from a Sandcastle run result: gate on the
 * completion signal FIRST (mirrors the merger gate / `assertCompletionSignal`),
 * then parse the `<cmr>` tag. Pure (a check on the run-result shape) so the gate is
 * unit-tested without a container. A complete-but-UNSIGNALED run (e.g.
 * `maxIterations` hit mid-review) is treated as ESCALATE (the safe direction — the
 * worker did not declare it finished, so its verdict is not trusted as a pass).
 */
export function cmrOutcomeFromResult(result: {
  completionSignal?: string | string[];
  stdout: string;
}): CmrWorkerOutcome {
  const signal = result.completionSignal;
  const signaled = Array.isArray(signal)
    ? signal.includes(CMR_COMPLETION_SIGNAL)
    : signal === CMR_COMPLETION_SIGNAL;
  if (!signaled) {
    const actual =
      signal === undefined
        ? "none (no signal fired before the iteration limit)"
        : `"${String(signal)}"`;
    return {
      kind: "escalate",
      reason: "cmr worker did not fire its completion signal",
      diagnosis:
        `expected "${CMR_COMPLETION_SIGNAL}", got ${actual} (a complete-but-unsignaled ` +
        `cmr run is not trusted as a verdict — escalate, never a fabricated pass)`,
    };
  }
  return parseCmrOutcome(result.stdout);
}

/** A trimmed, non-empty string at the schema layer (mirrors shipOutcome.ts). */
const nonEmpty = z.string().trim().min(1);

/**
 * The three — and ONLY three — `<cmr>` shapes (integ-cmr int-r1, Finding A;
 * mirrors shipOutcome.ts `.strict()` union). Each is `.strict()` so any EXTRA /
 * mixed key (a converged success carrying an `escalate` verdict, an off-contract
 * field) is rejected → malformed, closing the same "too-lax shape leaks the pass
 * branch" fail-open the ship parser was already hardened against. The contract is
 * prompts/integrated_cmr.md "must match one of the shapes above exactly":
 *   1. `{converged:true}`                          — converged (no other key);
 *   2. `{converged:false, reason}`                 — not converged (reason REQUIRED, non-empty);
 *   3. `{escalate:{reason, diagnosis}}`            — could not run the review.
 * Escalate is tried FIRST (a stuck worker carries no usable verdict).
 */
const cmrConvergedSchema = z.object({ converged: z.literal(true) }).strict();
const cmrRedSchema = z
  .object({ converged: z.literal(false), reason: nonEmpty })
  .strict();
const cmrEscalateSchema = z
  .object({ escalate: z.object({ reason: nonEmpty, diagnosis: nonEmpty }).strict() })
  .strict();

/**
 * Parse the cmr worker's `<cmr>{…}</cmr>` outcome from its stdout (#335). Pure so
 * it is unit-tested without a container.
 *
 * integ-cmr int-r1 (Finding A): classification is centralized into three
 * `.strict()` zod schemas (mirroring shipOutcome.ts). `safeParse` rejects every
 * EXTRA / mixed key, a NON-boolean `converged`, a blank `reason`, and a garbage
 * escalate (blank reason/diagnosis) → all map to malformed (fail-CLOSED: the gate
 * must NEVER read an ambiguous or off-contract run as a pass). Only the LAST
 * `<cmr>` tag is read (the worker may iterate).
 */
export function parseCmrOutcome(stdout: string): CmrWorkerOutcome {
  const re = /<cmr>([\s\S]*?)<\/cmr>/g;
  let last: string | undefined;
  for (let m = re.exec(stdout); m !== null; m = re.exec(stdout)) last = m[1];
  if (last === undefined) {
    return { kind: "malformed", reason: "cmr worker emitted no <cmr> tag" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { kind: "malformed", reason: "cmr worker <cmr> tag was not valid JSON" };
  }
  // `JSON.parse` succeeds on bare literals (`null` / `true` / `5`); the strict
  // schemas reject every non-object, but guard explicitly so the malformed
  // message stays specific (mirrors parseShipOutcome / parseMergerOutcome).
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "malformed", reason: "cmr worker <cmr> tag was not a JSON object" };
  }
  // Escalate FIRST — a model-stuck worker never carries a usable verdict.
  const escalate = cmrEscalateSchema.safeParse(parsed);
  if (escalate.success) {
    return {
      kind: "escalate",
      reason: escalate.data.escalate.reason,
      diagnosis: escalate.data.escalate.diagnosis,
    };
  }
  if (cmrConvergedSchema.safeParse(parsed).success) {
    return { kind: "verdict", converged: true };
  }
  const red = cmrRedSchema.safeParse(parsed);
  if (red.success) {
    return { kind: "verdict", converged: false, reason: red.data.reason };
  }
  return {
    kind: "malformed",
    reason:
      'cmr worker <cmr> tag matched no valid shape (expected one of: {converged:true}, ' +
      "{converged:false,reason}, {escalate:{reason,diagnosis}} — non-empty strings, no extra keys)",
  };
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
 * The two — and ONLY two — `<merger>` shapes (integ-cmr int-r1, Finding A; mirrors
 * shipOutcome.ts `.strict()` union). Each is `.strict()` so a resolved:true carrying
 * an EXTRA / mixed key (e.g. an `escalate` verdict, an off-contract field) is
 * rejected → NOT a clean resolve (fail-CLOSED). The contract is
 * prompts/merger_resolve_conflict.md "must match the shape above exactly":
 *   1. `{resolved:true, tradeoffs?}`               — resolved (tradeoffs OPTIONAL note);
 *   2. `{resolved:false, escalate:{reason, diagnosis}}` — escalate (could not resolve).
 * `tradeoffs` is optional (the prompt allows an empty/absent note); the escalate
 * `diagnosis` is optional at the schema layer to keep surfacing a reason-only legacy
 * escalate, but a blank `reason` no longer coerces into a resolve.
 */
const mergerResolvedSchema = z
  .object({ resolved: z.literal(true), tradeoffs: z.string().optional() })
  .strict();
const mergerEscalateSchema = z
  .object({
    resolved: z.literal(false),
    escalate: z
      .object({ reason: nonEmpty, diagnosis: nonEmpty.optional() })
      .strict(),
  })
  .strict();

/**
 * Parse the merger agent's `<merger>{…}</merger>` outcome from its stdout (the
 * shape in prompts/merger_resolve_conflict.md). Pure so it is unit-tested without
 * a container. Returns whether it resolved + an optional escalate reason.
 *
 * integ-cmr int-r1 (Finding A): classification is centralized into two `.strict()`
 * zod schemas (mirroring shipOutcome.ts). A resolved:true carrying any extra/mixed
 * key (the dangerous false-clean: a success payload smuggling an escalate) no
 * longer counts as resolved → fail-CLOSED to unresolved. Only the LAST `<merger>`
 * tag is read (the agent may iterate).
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
  let parsed: unknown;
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { resolved: false, reason: "merger agent <merger> tag was not valid JSON" };
  }
  // `JSON.parse` succeeds on the bare literals `null` / `true` / `5` / `"x"`; the
  // strict schemas reject every non-object, but guard explicitly so the message
  // stays specific (agy R1: a non-object must never crash or coerce to resolved).
  if (parsed === null || typeof parsed !== "object") {
    return { resolved: false, reason: "merger agent <merger> tag was not a JSON object" };
  }
  if (mergerResolvedSchema.safeParse(parsed).success) {
    return { resolved: true };
  }
  const escalate = mergerEscalateSchema.safeParse(parsed);
  if (escalate.success) {
    return {
      resolved: false,
      reason: escalate.data.escalate.reason ?? escalate.data.escalate.diagnosis,
    };
  }
  // No strict schema matched → off-contract (mixed payload, extra key, blank
  // reason, unknown shape). Fail-CLOSED: never read as a clean resolve.
  return { resolved: false, reason: "merger did not resolve" };
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
