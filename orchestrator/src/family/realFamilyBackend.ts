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
 *   - escalateFamily           → a durable family-ledger decision escalation
 *     (ADR 0017/0018 升级续跑: 卡点 → 返回调用端 → append answer → resume).
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
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join } from "node:path";

import { z } from "zod";

import * as sc from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

import {
  hasBoundedReopenCondition,
  hasExplicitAcceptedSuppressionSource,
} from "../acceptedSuppression.js";
import { writeContainerCodexConfig } from "../containerCodexConfig.js";
import { findingIdentityKey } from "../findings.js";
import { runExclusive } from "../gitMutex.js";
import {
  agentForSlug,
  assertCompletionSignal,
  candidateBranches,
  extractCoderTag,
  lastSessionId,
  parseCoderSelfReport,
  realCommitCount,
  reconcileCoderCommits,
  SANDBOX_CODEX_DIR,
  SANDBOX_FIX_FINDINGS_PATH_ENV,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_ISSUE_NUMBER_ALIAS_ENV,
  SANDBOX_ISSUE_NUMBER_ENV,
  SANDBOX_REPO_ENV,
  SANDBOX_SKILLS_DIR,
  SANDBOX_SOUL_ENV,
  SANDBOX_OUTCOME_PATH_ENV,
  SPAWNED_WORKER_ENV,
  WORKER_IDLE_TIMEOUT_SECONDS,
  modelFamilyForSlug,
  soulsMount,
  REQUIRED_SOUL_FILES,
  soulsDirError,
  type SelfReportedCoder,
  verifyOutputSchema,
  fixerOutputSchema,
  cleanupOutputSchema,
  docReleaseOutputSchema,
} from "../realBackend.js";
import {
  isValidCleanupResult,
  isValidDocReleaseResult,
  isValidFixerResult,
  isValidVerifyResult,
} from "../reviewLoopOutcome.js";
import type {
  CleanupResult,
  DocReleaseResult,
  FixerResult,
  VerifyResult,
} from "../types.js";
import {
  WORKER_OUTCOME_REPO_FILE,
  WORKER_OUTCOME_SANDBOX_FILE,
  readRequiredWorkerOutcomeSidecar,
} from "../workerOutcomeSidecar.js";
import {
  cmrLegAccountingFailure,
  modelForSlot,
  type CmrLegAccountingRoute,
} from "../modelRoutes.js";
import { legacyDispatchFamilyWorker } from "./dispatchFamilyWorker.js";
import { retryProcessCrash } from "../dispatchRetry.js";
import { recordFamilyEscalated } from "./ledger.js";
import {
  isFilledString,
  shipOutcomeFromResult,
  type ShipWorkerOutcome,
} from "../shipOutcome.js";

import type {
  CoderResult,
  DispatchContext,
  Finding,
  PriorFindingDisposition,
  StepSoul,
  WorkerLandingPayload,
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
  VerifyFamilyShippedPrRequest,
  VerifyFamilyShippedPrResult,
} from "./types.js";

/** The family-ledger sibling filename (under {@link RealFamilyBackendOptions.ledgerDir}). */
export const FAMILY_LEDGER_FILENAME = "family-ledger.jsonl";
/** Legacy durable escalate stuck-point filename, read for migration/back-compat. */
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
/** Route-selected CMR review-leg config written next to {@link CMR_FOCUS_FILENAME}. */
export const CMR_ROUTE_FILENAME = ".cmr-route.json";
/** Runner-owned family coder-fix findings file, written transiently in the family base. */
export const FAMILY_FIX_FINDINGS_FILENAME = ".orchestrator-fix-findings.json";

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

/** The cmr worker's completion signal (matches the integrated CMR pass prompts). */
const CMR_COMPLETION_SIGNAL = "CMR_STEP_COMPLETE";
/**
 * The integrated-cmr reviewer soul (ADR 0030). It invokes `ak-cross-m-review` for
 * one selected gate and returns runner-visible review outcomes; persistent repairs
 * are made only by the separate family coder-fix worker.
 */
const CMR_SOUL = "cmr";

/**
 * The WRITE soul the ship worker runs under (it commits the bump + pushes). A
 * DEDICATED ship soul (not the coder soul): the ship worker's discipline is
 * delivery via `gstack-ship` — stop at PR, deferred findings → tracker (issue /
 * TODOS.md) never the PR body — not the coder's TDD build loop.
 */
const SHIP_SOUL: StepSoul = "ship";
const OUTCOME_REWRITE_PROMPT = "outcome_rewrite.md";

/** Compatibility read model for durable family-ledger escalation rows. */
export interface FamilyEscalationRecord extends FamilyEscalation {
  readonly escalationKind?: FamilyLedgerEntry["escalationKind"];
  readonly familyHeadAfter?: string;
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
  /**
   * LAZY verify-cwd resolver (#4): when `verifyCwd` is not set, this is called at
   * verify TIME (after the children have merged onto the family base) to infer the
   * cwd from the live family diff — the dominant changed subproject. It runs lazily
   * because at CONSTRUCTION the family base is freshly cut (an empty diff); the
   * verifiable change only exists once merges have landed. Returns `undefined` when
   * nothing maps to a known subproject → verify falls back to `workingRepo`.
   * Precedence: `verifyCwd` (explicit) > `resolveVerifyCwd()` (inferred) > `workingRepo`.
   */
  readonly resolveVerifyCwd?: () => string | undefined;
  /** GitHub repo slug for `gh` (`owner/name`) — for openFamilyPr. */
  readonly repo: string;
  /** The base branch the family PR targets (e.g. an integration branch or "main"). */
  readonly base: string;
  /** Dir holding the versioned promptFiles (the merger conflict prompt). */
  readonly promptsDir: string;
  /**
   * Host dir of souls to bind-mount live (souls/*.md). #372 unconditional:
   * souls mounted rather than baked so source changes visible immediately.
   * REQUIRED (souls no longer baked).
   */
  readonly soulsDir: string;
  /** The profile image (skills + CLIs baked in; souls mounted live #372) for the merger agent sandbox. */
  readonly imageName: string;
  /**
   * DEPRECATED (#334): host dir of dev skills to bind-mount for the merger. The
   * 2b image bakes `resolving-merge-conflicts`; `mergerSandboxConfig()` no longer
   * mounts host skills (a runtime mount would SHADOW the baked skill). Kept
   * OPTIONAL for back-compat; no longer read. Remove once callers drop it.
   * (Souls are mounted live per #372, not baked.)
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
 * Every promptFile the family layer can dispatch. This list is intentionally
 * static: prompt validation must not resolve model routes during module import.
 */
export const REFERENCED_FAMILY_PROMPT_FILES: ReadonlyArray<string> = [
  ...new Set([
    "integrated_cmr_completeness.md",
    "integrated_cmr_correctness.md",
    "coder_fix.md",
    OUTCOME_REWRITE_PROMPT,
    "family_ship.md",
    MERGER_CONFLICT_PROMPT,
  ]),
];
/** The merger agent's completion signal (matches prompts/merger_resolve_conflict.md). */
const MERGER_COMPLETION_SIGNAL = "MERGER_STEP_COMPLETE";
/** The merger resolver model slot, selected by the active route. */
export function mergerModel(): string {
  return modelForSlot("merger");
}

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
    this.validateSoulsDir();
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
   * Fail loudly at construction if soulsDir missing or invalid or incomplete.
   * Souls are no longer baked (#372); an existing but wrong/incomplete dir
   * (missing e.g. reviewer.md / output_protocol.md) would sail to runtime.
   * Delegates to the pure {@link soulsDirError} from realBackend (single source;
   * identical messages for both backends).
   */
  private validateSoulsDir(): void {
    const dir = this.opts.soulsDir;
    const dirExists = isAbsolute(dir) && existsSync(dir) && statSync(dir).isDirectory();
    const missing = dirExists
      ? REQUIRED_SOUL_FILES.filter((f) => !existsSync(join(dir, f)))
      : [];
    const err = soulsDirError(dir, isAbsolute(dir), dirExists, missing);
    if (err !== undefined) throw new Error(err);
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

  protected verifyFamilyShipPr(input: {
    readonly pr: string;
    readonly familyBase: string;
  }): { ok: true; headOid: string } | { ok: false; reason: string } {
    try {
      const raw = this.sh(
        "gh",
        [
          "pr",
          "view",
          input.pr,
          "--repo",
          this.opts.repo,
          "--json",
          "baseRefName,headRefName,headRefOid,state",
        ],
        this.opts.workingRepo,
      );
      const parsed = JSON.parse(raw) as {
        readonly baseRefName?: unknown;
        readonly headRefName?: unknown;
        readonly headRefOid?: unknown;
        readonly state?: unknown;
      };
      if (parsed.state !== "OPEN") {
        return {
          ok: false,
          reason: `family PR "${input.pr}" is ${String(parsed.state)} but must be OPEN`,
        };
      }
      if (parsed.baseRefName !== this.opts.base) {
        return {
          ok: false,
          reason: `family PR "${input.pr}" targets base "${String(parsed.baseRefName)}" but expected "${this.opts.base}"`,
        };
      }
      if (parsed.headRefName !== input.familyBase) {
        return {
          ok: false,
          reason: `family PR "${input.pr}" uses head "${String(parsed.headRefName)}" but expected "${input.familyBase}"`,
        };
      }
      if (typeof parsed.headRefOid !== "string" || parsed.headRefOid.trim().length === 0) {
        return {
          ok: false,
          reason: `family PR "${input.pr}" did not expose a non-empty headRefOid`,
        };
      }
      return { ok: true, headOid: parsed.headRefOid.trim() };
    } catch (err) {
      return {
        ok: false,
        reason: `could not verify family PR "${input.pr}" base/head via gh pr view: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  }

  async verifyFamilyShippedPr(
    request: VerifyFamilyShippedPrRequest,
  ): Promise<VerifyFamilyShippedPrResult> {
    const verifiedPr = this.verifyFamilyShipPr({
      pr: request.pr,
      familyBase: request.familyBase,
    });
    if (!verifiedPr.ok) return verifiedPr;
    if (verifiedPr.headOid !== request.expectedHead) {
      return {
        ok: false,
        reason:
          `family PR "${request.pr}" head ${verifiedPr.headOid} ` +
          `does not match current family HEAD ${request.expectedHead}`,
      };
    }
    return { ok: true };
  }

  /**
   * Build the container agent for a {@link WorkerSpec}: resolve the model slug
   * through the SAME backend registry the single-slice path uses. This is the lone
   * seam that turns `spec.model` into a Sandcastle provider for family
   * WorkerSpec-driven runs (cmr + coder-fix + ship), so none can hardcode a model id or
   * assume a provider family that drifts from the slug the runner declares.
   * `protected` + pure (no container/I/O) so a unit test asserts the resolved model
   * without spinning a real `sc.run`.
   */
  protected agentForSpec(spec: WorkerSpec): sc.AgentProvider {
    return agentForSlug(spec.model);
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

  private readFamilyLedgerFile(): ReadonlyArray<FamilyLedgerEntry> | undefined {
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
      if (isFileNotFound(err)) return undefined;
      throw new Error(
        `readFamilyLedger: failed to read the family ledger at ` +
          `${join(this.opts.ledgerDir, FAMILY_LEDGER_FILENAME)} — ` +
          `${err instanceof Error ? err.message : String(err)}`,
      );
    }
    const ledger = raw
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as FamilyLedgerEntry);
    return ledger;
  }

  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return [
      ...this.legacyEscalationLedgerEntries(),
      ...(this.readFamilyLedgerFile() ?? []),
    ];
  }

  private readLegacyEscalationRecords(): ReadonlyArray<FamilyEscalationRecord> {
    let raw: string;
    try {
      raw = readFileSync(join(this.opts.ledgerDir, FAMILY_ESCALATION_FILENAME), "utf8");
    } catch (err) {
      if (isFileNotFound(err)) return [];
      throw new Error(
        `readEscalations: failed to read the legacy escalation log at ` +
          `${join(this.opts.ledgerDir, FAMILY_ESCALATION_FILENAME)} — ` +
          `${err instanceof Error ? err.message : String(err)}`,
      );
    }
    return raw
      .split("\n")
      .filter((l) => l.trim().length > 0)
      .map((l) => JSON.parse(l) as FamilyEscalationRecord);
  }

  private legacyEscalationLedgerEntries(): ReadonlyArray<FamilyLedgerEntry> {
    return this.readLegacyEscalationRecords().map((record) => ({
      status: "escalated",
      event: "escalated",
      phase: "final",
      reason:
        typeof record.reason === "string" && record.reason.trim().length > 0
          ? record.reason
          : "legacy family escalation",
      ...(record.escalationKind == null
        ? { escalationKind: "decision" as const }
        : record.escalationKind === "decision" || record.escalationKind === "failure"
          ? { escalationKind: record.escalationKind }
          : {}),
      ...(record.familyHeadAfter != null
        ? { familyHeadAfter: record.familyHeadAfter }
        : {}),
    }));
  }

  async readFamilyHead(familyBase: string): Promise<string> {
    const out = await this.sh("git", ["rev-parse", familyBase], this.opts.workingRepo);
    return out.trim();
  }

  async readFamilyCurrentHead(): Promise<string> {
    const out = await this.sh("git", ["rev-parse", "HEAD"], this.opts.workingRepo);
    return out.trim();
  }

  async readFamilyTrackedStatus(_familyBase: string): Promise<readonly string[]> {
    const out = await this.sh(
      "git",
      ["status", "--short", "--untracked-files=no"],
      this.opts.workingRepo,
    );
    const trimmed = out.trim();
    return trimmed.length === 0 ? [] : trimmed.split(/\r?\n/);
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
    // #598: a merger agent that CRASHES (throws — e.g. a container/connection
    // failure inside the sc.run) is retried fresh up to the bound; before each retry
    // the half-resolved conflict is re-established so the retry starts from the same
    // clean conflicted state (idempotency). A RETURNED `{resolved:false}` is a JUDGED
    // non-resolve — surfaced below, never retried. A persistent crash re-throws.
    const outcome = await retryProcessCrash(
      async () => {
        // #598 idempotency: if a PRIOR crashed attempt already COMMITTED the merge,
        // the child is LANDED (git truth). Do NOT re-run the merger on a no-conflict
        // state — `reestablishConflictForRetry` would `git merge --abort` (a no-op
        // after a commit) then re-merge "already up to date", leaving the merger to
        // run with nothing to resolve and FAIL a child that was already correctly
        // merged. Recognize the landed merge instead (the post-state check below
        // then returns it clean). On attempt 1 the merge is still in-progress, so
        // this is false and the merger runs normally.
        if (this.childLandedOnFamilyBase(familyHeadBefore, childHead, repo)) {
          return { resolved: true };
        }
        return await this.runMergerAgent(req);
      },
      { resetBeforeRetry: () => this.reestablishConflictForRetry(req) },
    );
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
    const familyHead = this.sh("git", ["rev-parse", this.opts.familyBase], repo);
    const childLanded = this.childLandedOnFamilyBase(familyHeadBefore, childHead, repo);
    return childLanded
      ? { familyHead, familyHeadBefore, childHead }
      : { familyHead, familyHeadBefore, childHead, conflicted: true };
  }

  /**
   * Git-truth check (#295 / codex R2/R3, reused by the #598 idempotency retry
   * guard): the child's merge has LANDED iff there is no in-progress merge AND the
   * FAMILY BASE REF itself moved past `familyHeadBefore` AND `childHead` is now an
   * ancestor of it. Reading the FAMILY BASE REF (not HEAD) rejects a wrong-ref /
   * detached-HEAD landing (codex R3).
   */
  private childLandedOnFamilyBase(
    familyHeadBefore: string,
    childHead: string,
    repo: string,
  ): boolean {
    if (this.mergeInProgress(repo)) return false;
    const familyHead = this.sh("git", ["rev-parse", this.opts.familyBase], repo);
    return (
      familyHead !== familyHeadBefore &&
      this.isAncestorOf(childHead, familyHead, repo)
    );
  }

  /**
   * #598 idempotency: re-establish the SAME in-progress merge conflict that a
   * CRASHED {@link runMergerAgent} attempt left half-resolved, so the retry starts
   * from the clean conflicted state (never on top of a half-added index). Abort the
   * half-done merge, check out the family base, then re-run the deterministic
   * `git merge --no-ff` — a real conflict exits non-zero and leaves MERGE_HEAD,
   * which is exactly the state the retry's merger resolves. A protected seam so the
   * retry path is unit-testable without a real conflicting repo.
   */
  protected async reestablishConflictForRetry(
    req: ConflictResolveRequest,
  ): Promise<void> {
    const repo = this.opts.workingRepo;
    try {
      this.sh("git", ["merge", "--abort"], repo);
    } catch {
      // No in-progress merge to abort (the crash may have left none) — fine.
    }
    this.sh("git", ["checkout", this.opts.familyBase], repo);
    const msg = `Merge child #${req.childIssue} (${req.childBranch}) into ${this.opts.familyBase}`;
    try {
      this.sh("git", ["merge", "--no-ff", "-m", msg, req.childBranch], repo);
    } catch (err) {
      // #598 r5 (codexA/B, mirroring mergeChildLocked): only a REAL content conflict
      // exits non-zero AND leaves MERGE_HEAD — that is the re-established state the
      // retry resolves, so swallow it. A NON-conflict git failure (dirty worktree /
      // lock / bad ref) leaves NO MERGE_HEAD; swallowing it would let the retry's
      // merger run with no conflict re-established. Rethrow so retryProcessCrash counts
      // this as a reset failure and SKIPS the merger dispatch (never runs on an
      // un-re-established state), retrying the reset next attempt / exhausting.
      if (!this.mergeInProgress(repo)) throw err;
    }
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
    // FAIL-CLOSED on the WORKER's OWN auth (integ-cmr int-r2 A-1, mirroring the
    // cmr/ship worker preflight): when the merger slot resolves to a Claude-family
    // model, the Claude OAuth token is THIS worker's auth, not a degradable leg.
    // Absent, the worker cannot start and never fires its completion signal; that
    // failure would throw out of `sc.run` (NOT a structured non-resolve), and the
    // thrown startup error would surface as an opaque wave abort instead of the
    // merger's honest "did not resolve" → escalate path
    // (`resolveMergeConflict` turns a non-resolve into a loud, locatable throw; the
    // ledger never records a phantom `merged`). So return a STRUCTURED unresolved
    // BEFORE spinning the container when the token is absent. Mount once and reuse for
    // the sandbox (no double-mount).
    const auth = this.mountMergerAuth();
    try {
      if (modelFamilyForSlug(mergerModel()) === "claude" && auth.claudeToken === undefined) {
        return {
          resolved: false,
          reason:
            "merger worker cannot start without CLAUDE_CODE_OAUTH_TOKEN — the merger is " +
            "the container's top-level claude (sc.claudeCode); its OAuth token " +
            "(~/.sc-claude-token → CLAUDE_CODE_OAUTH_TOKEN) is the worker's OWN auth. " +
            "Without it the worker fails to start and never resolves; returning a " +
            "structured non-resolve here keeps resolveMergeConflict's loud-throw " +
            "semantics (a thrown sc.run startup error would surface as an opaque wave abort).",
        };
      }
      const outcomeLanding = this.prepareMergerOutcomeLanding();
      try {
        const result = await this.runAgentSandbox({
          name: `merger-resolve-${req.childIssue}`,
          idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
          cwd: this.opts.workingRepo,
          sandbox: this.mergerSandbox(auth, outcomeLanding),
          agent: agentForSlug(mergerModel()),
          maxIterations: 1,
          completionSignal: MERGER_COMPLETION_SIGNAL,
          branchStrategy: { type: "head" }, // commit the resolved merge in place
          promptFile: join(this.opts.promptsDir, MERGER_CONFLICT_PROMPT),
        });
        return mergerOutcomeFromResult({ ...result, outcomePath: outcomeLanding.path });
      } finally {
        this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir]);
    }
  }

  /** The merger agent's sandbox (souls + skills baked into the image + optional auth). */
  protected prepareMergerOutcomeLanding(): { path: string; sandboxPath: string } {
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    const dir = mkdtempSync(join(this.opts.ledgerDir, "worker-outcome-merger-"));
    const path = join(dir, "outcome.json");
    writeFileSync(path, "", "utf8");
    this.excludeOptionalRuntimeFileFromGit(WORKER_OUTCOME_REPO_FILE);
    return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
  }

  protected mergerSandbox(
    auth: MergerAuth = this.mountMergerAuth(),
    outcomeLanding?: { path: string; sandboxPath: string },
  ): sc.SandboxProvider {
    return docker(this.mergerSandboxConfig(auth, outcomeLanding));
  }

  /**
   * Gather the merger worker's host credentials: codex auth (mounted) plus the
   * claude OAuth token (env), mirroring the route-selected top-level worker auth
   * used by coder-fix / ship. The merger needs NO gh (it resolves + commits in
   * place, never pushes/PRs). Fail-soft: missing auth source ⇒ undefined (Claude's
   * REQUIRE gate is `runMergerAgent`'s preflight; codex degrades to no mount).
   * `protected` so a unit test points $HOME at a temp dir.
   */
  protected mountMergerAuth(): MergerAuth {
    const home = this.opts.home ?? homedir();
    const root = join(home, ".sc-orchestrator");
    let codexAuthDir: string | undefined;
    let tempCodexDir: string | undefined;
    try {
      mkdirSync(root, { recursive: true, mode: 0o700 });
      tempCodexDir = mkdtempSync(join(root, "merger-codex-auth-"));
      copyFileSync(join(home, ".codex", "auth.json"), join(tempCodexDir, "auth.json"));
      chmodSync(join(tempCodexDir, "auth.json"), 0o600);
      writeContainerCodexConfig(join(tempCodexDir, "config.toml"));
      codexAuthDir = tempCodexDir;
    } catch {
      // codex auth absent ⇒ no codex mount. Reclaim the mkdtemp dir if it was
      // created before copy/chmod/config writing threw.
      if (codexAuthDir === undefined && tempCodexDir !== undefined) {
        rmSync(tempCodexDir, { recursive: true, force: true });
      }
    }
    let claudeToken: string | undefined;
    try {
      const tok = readFileSync(join(home, ".sc-claude-token"), "utf8").trim();
      // A present-but-empty/blank token file ⇒ undefined (the preflight escalates),
      // NOT an injected empty CLAUDE_CODE_OAUTH_TOKEN="" that defeats the gate
      // (cmr int-r3 A; matches readGhToken's `tok === "" ? undefined` normalization).
      claudeToken = tok === "" ? undefined : tok;
    } catch {
      // claude token absent ⇒ the top-level merger worker degrades; the
      // runMergerAgent preflight returns a structured non-resolve.
    }
    return { codexAuthDir, claudeToken };
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
   * the baked skill. The merger soul finds the skill in the IMAGE, not a host mount.
   *
   * integ-cmr int-r2 (A-1): the merger is a TOP-LEVEL claude worker, so its claude
   * OAuth token is injected here as CLAUDE_CODE_OAUTH_TOKEN (symmetric with
   * `cmrSandboxConfig` / `shipSandboxConfig`) — #335/#336 wired the cmr/ship workers'
   * auth but the merger's was missing (the worker spun unauthenticated). The token is
   * set only when present (this pure seam stays tolerant; the REQUIRE gate is
   * `runMergerAgent`'s preflight). Codex auth is mounted when present for routes
   * whose merger slot resolves to a Codex-family worker. The merger needs NO gh
   * mount — it resolves + commits in place, never pushes / opens a PR.
   */
  protected mergerSandboxConfig(
    auth: MergerAuth,
    outcomeLanding?: { path: string; sandboxPath: string },
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    const env: Record<string, string> = { ...SPAWNED_WORKER_ENV, [SANDBOX_SOUL_ENV]: MERGER_SOUL };
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    if (outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = outcomeLanding.sandboxPath;
    }
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [];
    if (
      auth.codexAuthDir !== undefined &&
      modelFamilyForSlug(mergerModel()) === "codex"
    ) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    if (outcomeLanding !== undefined) {
      mounts.push({
        hostPath: outcomeLanding.path,
        sandboxPath: outcomeLanding.sandboxPath,
      });
    }
    // #372: souls mount live for merger worker (data files not baked).
    // Use shared helper (forces readonly:true, single hard-coded sandbox path).
    mounts.push(soulsMount(this.opts.soulsDir));
    return {
      imageName: this.opts.imageName,
      env,
      // #334: no skills mount — the baked image provides the merger skill.
      mounts,
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
    // Run where the Node project lives, NOT the clone root — else npx finds no
    // package.json/config (online R2 Codex P1). Precedence (#4): explicit verifyCwd
    // > the lazy diff-inferred cwd (the dominant changed subproject) > the clone root.
    let cwd: string | undefined;
    if (this.opts.verifyCwd !== undefined) {
      // An EXPLICIT verifyCwd that is not a Node project is a caller MISCONFIG —
      // fail CLOSED (R1 T3 codex), never silent-pass an un-verified merge.
      cwd = this.opts.verifyCwd;
      if (!this.isNodeProject(cwd)) {
        throw new Error(
          `verifyCwd "${cwd}" is not a Node project (no package.json) — failing ` +
            `closed rather than passing family verify with nothing installed / ` +
            `typechecked / tested.`,
        );
      }
    } else {
      // No explicit cwd → infer from the family diff. A git/diff ERROR in the
      // resolver THROWS (familyDiffFiles no longer swallows it) → verify_failed, NOT
      // mistaken for "no Node subproject".
      cwd = this.opts.resolveVerifyCwd?.();
      // R3 (gemini high): the resolver is undefined for a SINGLE-project repo too
      // (package.json at the clone ROOT — no subproject dir matches). Fall back to
      // workingRepo, but ONLY when the root is ITSELF a Node project — so a single
      // repo is verified, while a MULTI-project repo's non-Node root (R1 T2) is still
      // skipped, never `npm install`ed.
      if (cwd === undefined && this.isNodeProject(this.opts.workingRepo)) {
        cwd = this.opts.workingRepo;
      }
      // Still undefined ⇒ the diff genuinely touches no Node project (multi-project
      // repo, non-Node-only diff) ⇒ nothing to verify, skip.
      if (cwd === undefined) return;
    }
    // #3 (dogfood death) + #372 P2: ALWAYS install deps before running the
    // project's verify scripts. Freshness by construction (npm ci is idempotent
    // and lockfile-exact). Do NOT condition on node_modules presence or any
    // manifest/mtime detection — #372 ratified "freshness by construction, never
    // by detection". A later wave inside the family clone can mutate
    // package.json/package-lock.json; the launcher unconditional rebuild only
    // covers the *orchestrator* dist/image, not the family clone's project deps.
    // Therefore verify path must unconditionally ensure the cwd's deps.
    this.installDeps(cwd);
    // #5 (dogfood): run the PROJECT'S OWN package.json scripts, NOT a hardcoded
    // `npx tsc`/`npx vitest`. web/'s test script is `vitest run --environment jsdom`
    // — a bare `npx vitest run` DROPS `--environment jsdom`, so every jsdom render
    // test throws `document is not defined` and verify fails a perfectly good
    // project. (The orchestrator's own scripts HAPPENED to match `npx tsc`/`vitest`,
    // which is why this only surfaced on a foreign project — web/.) Run the declared
    // `typecheck` (when present) + `test` scripts so each project's real flags/config
    // (jsdom, tsc -b, …) are honoured.
    const scripts = this.packageScripts(cwd);
    // Type-check via the project's OWN command. R1 T3 (codex): web/ has NO `typecheck`
    // script — its TS check lives in `build` (`tsc -b && vite build`, exactly what the
    // game CI runs). Skipping it let a web change with TS/build errors pass verify as
    // long as Vitest passed. Precedence: dedicated `typecheck` > `build` (the project's
    // real type-checking build) > nothing. So types are NEVER silently skipped.
    if (scripts.includes("typecheck")) {
      this.sh("npm", ["run", "typecheck"], cwd);
    } else if (scripts.includes("build")) {
      this.sh("npm", ["run", "build"], cwd);
    }
    if (scripts.includes("test")) {
      this.sh("npm", ["test"], cwd);
    }
  }

  /**
   * The script names declared in `cwd`'s package.json (`scripts` keys), so
   * {@link runVerifyCommands} runs the project's OWN `typecheck`/`test` commands
   * (#5) instead of a hardcoded `npx`. `protected` so a unit test drives the
   * branches without a real FS. Returns [] on any read/parse failure (a non-Node
   * dir verifies nothing — installDeps would have failed earlier for a Node project
   * lacking a lockfile or package context).
   */
  /**
   * Does `cwd` hold a Node project (a `package.json`)? The verify-skip guard (R1 T2)
   * for non-Node diffs. `protected` so a unit test drives the skip branch without a
   * real FS.
   */
  protected isNodeProject(cwd: string): boolean {
    return existsSync(join(cwd, "package.json"));
  }

  protected packageScripts(cwd: string): readonly string[] {
    try {
      const pkg = JSON.parse(readFileSync(join(cwd, "package.json"), "utf8")) as {
        scripts?: Record<string, unknown>;
      };
      return Object.keys(pkg.scripts ?? {});
    } catch {
      return [];
    }
  }

  /**
   * Install the Node project's deps in `cwd` before verify (#3). Prefer `npm ci`
   * (a lockfile-exact, reproducible install) when a `package-lock.json` is
   * present; fall back to `npm install` when it is not (`npm ci` REQUIRES a
   * lockfile). `protected` for test seam (used by verify tests).
   */
  protected installDeps(cwd: string): void {
    const hasLock = existsSync(join(cwd, "package-lock.json"));
    this.sh("npm", [hasLock ? "ci" : "install"], cwd);
  }

  // ─────────────────────── unified worker dispatch (#335) ───────────────────────

  /**
   * THE family worker-dispatch seam (ADR 0026 / #331 / #335 / #336). It dispatches
   * real CONTAINER workers for the delivered family legs:
   *   - cmr  (#335): a route-selected top-level reviewer invoking `ak-cross-m-review`
   *     (`runCmrWorker`) for one clean review pass.
   *   - coder (#550): a family coder-fix worker invoking `/tdd` for blocking CMR
   *     findings (`runFamilyCoderFixWorker`).
   *   - ship (#336): a container ship worker invoking `gstack-ship` 止于 PR
   *     (`dispatchShipWorker`) — this REPLACED the legacy inline `openFamilyPr`.
   * Every OTHER family worker kind (merge — B 段) still forwards to the legacy
   * wrapper until its own slice wires it.
   *
   * The cmr worker (`cmrWorkerSpec`) = the 2b container's TOP-LEVEL route-selected
   * reviewer for ONE ADR 0030 pass (completeness or correctness). It
   * `Skill`-invokes ak-cross-m-review in-container and returns a TERMINAL review
   * verdict. The runner (`verifyCmr.ts`) owns pass order, route-leg accounting,
   * ADR0032 strong-leg floor, blocking-finding classification, coder-fix dispatch,
   * and fresh re-review before ship. A non-converged review outcome is a completed
   * CMR payload the runner routes; it is NOT a failed worker.
   */
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    if (spec.kind === "ship") {
      // #336: the family ship step (止于 PR) is a CONTAINER ship WORKER invoking
      // `gstack-ship` (replacing the inline `openFamilyPr`).
      return this.dispatchShipWorker(spec, ctx);
    }
    if (spec.kind === "coder") {
      return this.runFamilyCoderFixWorker(spec, ctx, landing);
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
    return this.cmrOutcomeToWorkerResult(outcome, ctx);
  }

  async rewriteWorkerOutcome(
    spec: WorkerSpec,
    ctx: DispatchContext,
    protocolFailure: Extract<WorkerResult, { kind: "malformed" }>,
    attempt: number,
  ): Promise<WorkerResult> {
    if (spec.kind !== "cmr") {
      return {
        kind: "failed",
        reason:
          `outcome protocol rewrite for worker kind "${spec.kind}" is not implemented`,
      };
    }
    const outcome = await this.runCmrOutcomeRewrite(
      spec,
      ctx,
      protocolFailure,
      attempt,
    );
    if (outcome.kind === "outcome_protocol_failure") return outcome;
    return this.cmrOutcomeToWorkerResult(outcome, ctx);
  }

  private cmrOutcomeToWorkerResult(
    outcome: CmrWorkerOutcome,
    ctx: DispatchContext,
  ): WorkerResult {
    if (outcome.kind === "escalate") {
      // A model-stuck cmr worker (missing skill / no leg ran / could not produce a
      // verdict) is the WorkerResult-level escalate (續跑 path), NOT a fabricated
      // pass — verifyCmr.ts calls escalateFamily with this reason.
      return {
        kind: "escalated",
        escalation: { reason: outcome.reason, diagnosis: outcome.diagnosis },
        ...(outcome.sessionId !== undefined ? { sessionId: outcome.sessionId } : {}),
      };
    }
    if (outcome.kind === "malformed") {
      // No parseable verdict ⇒ malformed (the gate must never read it as a pass).
      return {
        kind: "malformed",
        reason: outcome.reason,
        ...(outcome.sessionId !== undefined ? { sessionId: outcome.sessionId } : {}),
        ...(outcome.cmrLegAccountingPayload !== undefined
          ? { cmrLegAccountingPayload: outcome.cmrLegAccountingPayload }
          : {}),
      };
    }
    return {
      kind: "completed",
      output: {
        kind: "cmr",
        ...(ctx.cmrPass !== undefined ? { cmrPass: ctx.cmrPass } : {}),
        converged: outcome.converged,
        ...(outcome.reason !== undefined ? { reason: outcome.reason } : {}),
        successfulLegs: outcome.successfulLegs,
        ...(outcome.skippedLegs !== undefined ? { skippedLegs: outcome.skippedLegs } : {}),
        ...(outcome.claimedFixedFindingIdentityKeys !== undefined
          ? {
              claimedFixedFindingIdentityKeys:
                outcome.claimedFixedFindingIdentityKeys,
            }
          : {}),
        ...(outcome.priorFindingDispositions !== undefined
          ? { priorFindingDispositions: outcome.priorFindingDispositions }
          : {}),
        ...(outcome.findings !== undefined ? { findings: outcome.findings } : {}),
        evidencePaths: outcome.evidencePaths,
      },
      ...(outcome.sessionId !== undefined ? { sessionId: outcome.sessionId } : {}),
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
   * Run the integrated cmr WORKER: ONE `sc.run` of the 2b container's
   * route-selected agent invoking `ak-cross-m-review` over the merged family base
   * diff (#335).
   * `protected` so a unit test fixtures the outcome without a real container (the
   * real container only runs on the driver / manual-smoke / e2e path).
   *
   * The worker is the container's TOP-LEVEL route-selected reviewer, running on the
   * resident family base (`branchStrategy: head` keeps it on the full current diff)
   * under the dedicated `cmr` soul. Its `<cmr>` tag TERMINAL pass verdict is gated
   * on the completion signal then parsed into a
   * {@link CmrWorkerOutcome}; `verifyCmr.ts` performs the ADR 0030 pass sequencing
   * and accounting around that verdict.
   */
  protected async runCmrWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<CmrWorkerOutcome> {
    // FAIL-CLOSED before any container work (codex cmr R3): the focus file pins the
    // EXACT cut-SHA review-scope diff (prompt contract in the integrated CMR pass prompts — do
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
          "scope (integrated CMR pass prompts); refusing to fall back to a possibly-stale " +
          "main...HEAD scope (a fail-open that would review the wrong diff). Provide " +
          "RealFamilyBackendOptions.familyBaseStartHead.",
      };
    }
    // FAIL-CLOSED on the WORKER's OWN auth (codex cmr R4): when the cmr slot
    // resolves to a Claude-family model, the Claude OAuth token is NOT a mere
    // reviewer leg — it is THIS worker's auth. Absent, the worker cannot start and
    // never emits a `<cmr>` verdict; that failure would
    // throw out of `sc.run` (NOT a structured escalate), bypassing verifyCmr's
    // escalate routing (a fail-open — the gate is crashed, not honestly escalated).
    // codex/agy auth stay best-effort reviewer LEGS (they degrade in-container); the
    // Claude token alone is load-bearing for the worker itself. Mount once and reuse
    // for the sandbox (no double-mount). The cut-SHA guard above runs first; this is
    // the second fail-closed precondition, both BEFORE any container work.
    // `mountCmrAuth` creates per-run temp auth dirs (codex/agy) BEFORE the early
    // claude-token escalate below; the finally reclaims them on success, exception,
    // AND that early return (online review r1 — 3 bots: leaked temp dirs).
    const frozenReviewLegs = spec.cmrReviewLegs;
    if (frozenReviewLegs === undefined) {
      return {
        kind: "escalate",
        reason: "cmr worker spec missing frozen review legs",
        diagnosis:
          "cmrWorkerSpec must freeze the route-selected cmrReview leg collection before " +
          "dispatch. Refusing to re-read process.env in runCmrWorker because that can " +
          "write a route file that disagrees with the verified route fingerprint.",
      };
    }
    const auth = this.mountCmrAuth();
    try {
      if (modelFamilyForSlug(spec.model) === "claude" && auth.claudeToken === undefined) {
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
      // route-selected top-level agent over THIS checked-out base.
      this.sh("git", ["checkout", ctx.familyBase!], this.opts.workingRepo);
      // codex cmr R1 (F3+F2): thread the EXACT review scope + the LLM-resolved-child
      // FOCUS into the worker via a git-ignored focus file the prompt reads — the
      // skill can't reliably scope the family diff on its own (a stale local base
      // ref pollutes `main...HEAD`; non-`main` targets diff the wrong ref), and the
      // #291 缺口-1 focus signal must not be silently dropped. The focus file pins the
      // exact `git diff <familyBaseStartHead>...<familyBase>` scope command + the
      // baseline SHA + the machine-resolved children.
      this.writeCmrFocusFile(ctx);
      this.writeCmrRouteFile(ctx, frozenReviewLegs);
      const outcomeLanding = this.prepareCmrOutcomeLanding(ctx);
      try {
        const result = await this.runAgentSandbox({
          name: "family-cmr",
          idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
          cwd: this.opts.workingRepo,
          sandbox: this.cmrSandbox(auth, frozenReviewLegs, outcomeLanding),
          // Derive the model from the spec via the shared validated seam (cmr S336 r7
          // symmetry): resolve the worker's slug through the same registry as the
          // single-slice + family ship paths — no constant that could silently drift
          // from the spec the runner declares.
          agent: this.agentForSpec(spec),
          // `maxIter` is the sandbox iteration budget for this single ADR 0030 cmr
          // pass worker. The pass verdict is consumed by verifyCmr, which owns pass
          // sequencing and accounting.
          maxIterations: spec.maxIter,
          completionSignal: spec.completionSignal,
          // On the resident family base so the clean CMR reviewer audits the
          // current full family diff. Persistent repairs are made only by the
          // separate family coder-fix worker.
          branchStrategy: { type: "head" },
          promptFile: join(this.opts.promptsDir, spec.promptFile),
        });
        return withCmrSession(
          cmrOutcomeFromResult({
            ...result,
            cmrReviewLegs: frozenReviewLegs,
            outcomePath: outcomeLanding.path,
          }),
          lastSessionIdIfPresent(result),
        );
      } finally {
        this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir, auth.agyDir]);
    }
  }

  protected async runCmrOutcomeRewrite(
    spec: WorkerSpec,
    ctx: DispatchContext,
    protocolFailure: Extract<WorkerResult, { kind: "malformed" }>,
    attempt: number,
  ): Promise<CmrWorkerOutcome | Extract<WorkerResult, { kind: "outcome_protocol_failure" }>> {
    if (ctx.familyBase === undefined) {
      return {
        kind: "malformed",
        reason: "cmr outcome rewrite requires ctx.familyBase",
        ...(protocolFailure.sessionId !== undefined
          ? { sessionId: protocolFailure.sessionId }
          : {}),
      };
    }
    if (protocolFailure.sessionId === undefined) {
      return {
        kind: "malformed",
        reason:
          "cmr outcome rewrite requires the malformed worker sessionId to resume the same producing worker",
      };
    }
    const frozenReviewLegs = spec.cmrReviewLegs;
    if (frozenReviewLegs === undefined) {
      return {
        kind: "malformed",
        reason: "cmr outcome rewrite requires frozen review legs on the worker spec",
        sessionId: protocolFailure.sessionId,
      };
    }
    const auth = this.mountCmrAuth();
    try {
      if (modelFamilyForSlug(spec.model) === "claude" && auth.claudeToken === undefined) {
        return {
          kind: "malformed",
          reason:
            "cmr outcome rewrite cannot resume the same Claude worker without CLAUDE_CODE_OAUTH_TOKEN",
          sessionId: protocolFailure.sessionId,
        };
      }
      this.sh("git", ["checkout", ctx.familyBase], this.opts.workingRepo);
      const gitBefore = this.captureOutcomeRewriteGitEvidence();
      const outcomeLanding = this.prepareCmrOutcomeLanding(ctx);
      try {
        const result = await this.runAgentSandbox({
          name: `family-cmr-outcome-rewrite-${ctx.cmrPass ?? "legacy"}-${attempt}`,
          idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
          cwd: this.opts.workingRepo,
          sandbox: this.cmrSandbox(auth, frozenReviewLegs, outcomeLanding),
          agent: this.agentForSpec(spec),
          maxIterations: 1,
          completionSignal: spec.completionSignal,
          branchStrategy: { type: "head" },
          resumeSession: protocolFailure.sessionId,
          promptFile: join(this.opts.promptsDir, OUTCOME_REWRITE_PROMPT),
          promptArgs: {
            ATTEMPT: String(attempt),
            FAILURE_REASON: protocolFailure.reason,
            WORKER_KIND: spec.kind,
            CMR_PASS: ctx.cmrPass ?? "legacy",
            COMPLETION_SIGNAL: spec.completionSignal,
          },
        });
        const outcome = withCmrSession(
          cmrOutcomeFromResult({
            ...result,
            cmrReviewLegs: frozenReviewLegs,
            outcomePath: outcomeLanding.path,
          }),
          lastSessionIdIfPresent(result) ?? protocolFailure.sessionId,
        );
        const gitFailure = this.outcomeRewriteGitFailure({
          before: gitBefore,
          after: this.captureOutcomeRewriteGitEvidence(),
          attempt,
          sessionId: outcome.sessionId,
        });
        if (gitFailure !== undefined) return gitFailure;
        return outcome;
      } finally {
        this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir, auth.agyDir]);
    }
  }

  protected async runAgentSandbox(
    options: Parameters<typeof sc.run>[0],
  ): Promise<Awaited<ReturnType<typeof sc.run>>> {
    return await sc.run(options);
  }

  // ─────────────────────────── family coder-fix ───────────────────────────

  /**
   * Run the runner-visible family coder-fix worker (#550). The CMR reviewer never
   * commits repairs; blocking CMR findings arrive here as structured
   * `blockingFindings` / `blockingFindingIdentityKeys`, this worker commits on the
   * resident family base, and `verifyCmr.ts` dispatches a fresh CMR re-review over
   * the resulting full diff.
   */
  protected async runFamilyCoderFixWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    if (ctx.familyBase === undefined) {
      throw new Error(
        "dispatchWorker(coder): a family coder-fix worker requires ctx.familyBase " +
          "(the merged base branch to repair).",
      );
    }
    const auth = this.mountShipAuth();
    try {
      if (modelFamilyForSlug(spec.model) === "claude" && auth.claudeToken === undefined) {
        return {
          kind: "escalated",
          escalation: {
            reason:
              "no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — the family coder-fix worker cannot start",
            diagnosis:
              "the family coder-fix worker is a top-level Claude worker when the " +
              "active route selects a Claude-family coderFix model; provide " +
              "CLAUDE_CODE_OAUTH_TOKEN / ~/.sc-claude-token or select a non-Claude " +
              "coderFix route.",
          },
        };
      }
      this.sh("git", ["checkout", ctx.familyBase], this.opts.workingRepo);
      const fixFindingsLanding = this.writeFamilyFixFindingsFile(ctx, landing);
      try {
        const outcomeLanding = this.prepareFamilyCoderOutcomeLanding();
        try {
          const result = await this.runAgentSandbox({
            name: "family-coder-fix",
            idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
            cwd: this.opts.workingRepo,
            sandbox: this.familyCoderSandbox(auth, ctx, outcomeLanding),
            agent: this.agentForSpec(spec),
            maxIterations: spec.maxIter,
            completionSignal: spec.completionSignal,
            branchStrategy: { type: "head" },
            promptFile: join(this.opts.promptsDir, spec.promptFile),
          });
          return this.familyCoderResultFromRun(result, spec, outcomeLanding.path);
        } finally {
          this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
        }
      } finally {
        rmSync(fixFindingsLanding.path, { force: true });
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir]);
    }
  }

  /** Write the runner-owned blocking CMR findings file into the checked-out family base. */
  protected writeFamilyFixFindingsFile(
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): { path: string; sandboxPath: string } {
    this.excludeOptionalRuntimeFileFromGit(FAMILY_FIX_FINDINGS_FILENAME);
    const path = join(this.opts.workingRepo, FAMILY_FIX_FINDINGS_FILENAME);
    writeFileSync(
      path,
      `${JSON.stringify(
        {
          // Rich finding CONTENT comes from the SEPARATE landing payload (信封宪法,
          // ADR 0062) — never from the runner's thin DispatchContext.
          blockingFindings: landing?.blockingFindings ?? [],
          blockingFindingIdentityKeys: ctx.blockingFindingIdentityKeys ?? [],
          ...(ctx.repairAttemptFailures !== undefined &&
          ctx.repairAttemptFailures.length > 0
            ? { repairAttemptFailures: ctx.repairAttemptFailures }
            : {}),
          ...(ctx.escalationAnswer !== undefined
            ? { escalationAnswer: ctx.escalationAnswer }
            : {}),
        },
        null,
        2,
      )}\n`,
      "utf8",
    );
    return { path, sandboxPath: FAMILY_FIX_FINDINGS_FILENAME };
  }

  protected prepareFamilyCoderOutcomeLanding(): { path: string; sandboxPath: string } {
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    const dir = mkdtempSync(join(this.opts.ledgerDir, "worker-outcome-family-coder-fix-"));
    let success = false;
    try {
      const path = join(dir, "outcome.json");
      writeFileSync(path, "", "utf8");
      this.excludeOptionalRuntimeFileFromGit(WORKER_OUTCOME_REPO_FILE);
      success = true;
      return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
    } finally {
      if (!success) {
        rmSync(dir, { recursive: true, force: true });
      }
    }
  }

  protected familyCoderSandbox(
    auth: ShipAuth,
    ctx: DispatchContext,
    outcomeLanding: { path: string; sandboxPath: string },
  ): sc.SandboxProvider {
    return docker(this.familyCoderSandboxConfig(auth, ctx, outcomeLanding));
  }

  protected familyCoderSandboxConfig(
    auth: ShipAuth,
    ctx: DispatchContext,
    outcomeLanding: { path: string; sandboxPath: string },
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
      [SANDBOX_SOUL_ENV]: "coder",
      [SANDBOX_REPO_ENV]: this.opts.repo,
      [SANDBOX_FIX_FINDINGS_PATH_ENV]: FAMILY_FIX_FINDINGS_FILENAME,
      [SANDBOX_OUTCOME_PATH_ENV]: outcomeLanding.sandboxPath,
    };
    if (ctx.familyIssue !== undefined) {
      const issue = String(ctx.familyIssue);
      env[SANDBOX_ISSUE_NUMBER_ENV] = issue;
      env[SANDBOX_ISSUE_NUMBER_ALIAS_ENV] = issue;
    }
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    if (auth.ghToken !== undefined) env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    const mounts: { hostPath: string; sandboxPath: string }[] = [
      { hostPath: outcomeLanding.path, sandboxPath: outcomeLanding.sandboxPath },
    ];
    if (auth.codexAuthDir !== undefined) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    // #372: mount souls live for family coder-fix worker.
    // Shared helper forces readonly:true.
    mounts.push(soulsMount(this.opts.soulsDir));
    return { imageName: this.opts.imageName, env, mounts };
  }

  protected familyCoderResultFromRun(
    result: Pick<
      Awaited<ReturnType<typeof sc.run>>,
      "completionSignal" | "stdout" | "commits" | "iterations"
    >,
    spec: WorkerSpec,
    outcomePath: string,
  ): WorkerResult {
    try {
      assertCompletionSignal(result, spec.completionSignal, "family-coder-fix");
      const raw = readRequiredWorkerOutcomeSidecar(outcomePath);
      const truth = reconcileCoderCommits(
        parseCoderSelfReport(raw),
        realCommitCount(result),
      );
      return {
        kind: "completed",
        output: this.familyCoderOutput(truth),
        sessionId: lastSessionId(result),
      };
    } catch (err) {
      return {
        kind: "malformed",
        reason:
          `family coder-fix worker output malformed: ` +
          `${err instanceof Error ? err.message : String(err)}`,
        sessionId: lastSessionId(result),
      };
    }
  }

  private familyCoderOutput(output: SelfReportedCoder): CoderResult {
    return {
      kind: "coder",
      committed: output.committed,
      commitsAdded: output.commitsAdded,
      ...(output.repairEvidence !== undefined
        ? { repairEvidence: output.repairEvidence }
        : {}),
      ...(output.escalate !== undefined ? { escalate: output.escalate } : {}),
    };
  }

  private captureOutcomeRewriteGitEvidence(): {
    readonly head: string;
    readonly trackedStatus: readonly string[];
  } {
    const trackedStatus = this.sh("git", [
      "status",
      "--short",
      "--untracked-files=no",
    ], this.opts.workingRepo).trim();
    return {
      head: this.sh("git", ["rev-parse", "HEAD"], this.opts.workingRepo).trim(),
      trackedStatus: trackedStatus === "" ? [] : trackedStatus.split(/\r?\n/),
    };
  }

  private outcomeRewriteGitFailure(input: {
    readonly before: ReturnType<RealFamilyBackend["captureOutcomeRewriteGitEvidence"]>;
    readonly after: ReturnType<RealFamilyBackend["captureOutcomeRewriteGitEvidence"]>;
    readonly attempt: number;
    readonly sessionId?: string;
  }): Extract<WorkerResult, { kind: "outcome_protocol_failure" }> | undefined {
    const headMoved = input.before.head !== input.after.head;
    const trackedDirty = input.after.trackedStatus.length > 0;
    if (!headMoved && !trackedDirty) return undefined;

    const commitEvidence = headMoved
      ? this.sh("git", [
          "log",
          "--oneline",
          `${input.before.head}..${input.after.head}`,
        ], this.opts.workingRepo)
      : "";
    const reasons = [
      headMoved
        ? `outcome rewrite moved HEAD from ${input.before.head} to ${input.after.head}; commits: ${
            commitEvidence === "" ? "(no descendant commits listed)" : commitEvidence
          }`
        : undefined,
      trackedDirty
        ? `outcome rewrite left tracked changes: ${input.after.trackedStatus.join("; ")}`
        : undefined,
    ].filter((reason): reason is string => reason !== undefined);

    return {
      kind: "outcome_protocol_failure",
      reason: reasons.join(" | "),
      attempts: input.attempt,
      ...(input.sessionId !== undefined ? { sessionId: input.sessionId } : {}),
    };
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
          "(integrated CMR pass prompts); refusing to emit a stale-base fallback scope " +
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
    const passLine =
      ctx.cmrPass === "completeness"
        ? "CMR pass: step5 completeness gate."
        : ctx.cmrPass === "correctness"
          ? "CMR pass: step6 correctness gate."
          : "CMR pass: legacy integrated gate.";
    const answerBlock =
      ctx.escalationAnswer !== undefined
        ? `\n\nHuman escalation answer (#439):\n\n\`\`\`json\n${JSON.stringify(
            ctx.escalationAnswer,
            null,
            2,
          )}\n\`\`\`\n\nRetry the previously paused family gate with this answer in force. Do not repeat the same HITL escalation unless this answer leaves a concrete blocker unresolved.`
        : "";
    const moduleBlock =
      ctx.moduleContext !== undefined
        ? `\n\nParsed module context (#449; runner-derived, do not infer from prose):\n\n\`\`\`json\n${JSON.stringify(
            ctx.moduleContext,
            null,
            2,
          )}\n\`\`\``
        : "\n\nParsed module context (#449): none declared; do not infer module boundaries from prose or logs.";
    const closureBlock =
      ctx.priorCmrFindingIdentityKeys !== undefined
        ? `\n\nRunner-owned prior CMR finding identity keys that may be claimed fixed in this pass (#450 closure context):\n\n\`\`\`json\n${JSON.stringify(
            ctx.priorCmrFindingIdentityKeys,
            null,
            2,
          )}\n\`\`\`\n\nDo not invent claimed-fixed identity keys outside this list. If the list is empty, emit empty closure arrays unless this pass reports new findings.`
        : "\n\nRunner-owned prior CMR finding identity keys (#450 closure context): none supplied. Do not claim fixed prior findings; emit empty closure arrays unless this pass reports new findings.";
    // The focus file is pass-scoped: it pins only the exact review scope and the
    // machine-resolved-child focus. Cross-pass accounting lives in the durable
    // ledger / worker verdict fields, not in this transient prompt file.
    const body =
      `# Integrated cmr — review scope + focus (machine-generated; #335)\n\n` +
      `Review THIS exact family-base diff (the commits the family base added since it\n` +
      `was cut from its target):\n\n    ${scope}\n\n${passLine}\n\n${focusLine}${moduleBlock}${closureBlock}${answerBlock}\n`;
    // Git-ignore it (it is a transient runtime artifact, never committed) then write.
    const target = join(this.opts.workingRepo, CMR_FOCUS_FILENAME);
    this.excludeFromGit(CMR_FOCUS_FILENAME);
    writeFileSync(target, body, "utf8");
  }

  /** Write the route-selected CMR review legs for the in-container worker. */
  protected writeCmrRouteFile(
    ctxOrPass: DispatchContext | DispatchContext["cmrPass"],
    reviewLegs: NonNullable<WorkerSpec["cmrReviewLegs"]>,
  ): void {
    const ctx =
      typeof ctxOrPass === "string" || ctxOrPass === undefined || ctxOrPass === null
        ? { cmrPass: ctxOrPass ?? undefined }
        : ctxOrPass;
    const body = JSON.stringify(
      {
        pass: ctx.cmrPass ?? "legacy",
        reviewLegs,
        ...(ctx.moduleContext !== undefined
          ? { moduleContext: ctx.moduleContext }
          : {}),
        ...(ctx.priorCmrFindingIdentityKeys !== undefined
          ? { priorCmrFindingIdentityKeys: ctx.priorCmrFindingIdentityKeys }
          : {}),
      },
      null,
      2,
    );
    this.excludeFromGit(CMR_ROUTE_FILENAME);
    writeFileSync(join(this.opts.workingRepo, CMR_ROUTE_FILENAME), body + "\n", "utf8");
  }

  protected prepareCmrOutcomeLanding(
    ctx: DispatchContext,
  ): { path: string; sandboxPath: string } {
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    const pass = ctx.cmrPass ?? "legacy";
    const dir = mkdtempSync(join(this.opts.ledgerDir, `worker-outcome-cmr-${pass}-`));
    const path = join(dir, "outcome.json");
    writeFileSync(path, "", "utf8");
    this.excludeOptionalRuntimeFileFromGit(WORKER_OUTCOME_REPO_FILE);
    return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
  }

  /** Add a transient cmr runtime file to the worktree's local git excludes. */
  protected excludeFromGit(filename: string): void {
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
      if (!existing.split(/\r?\n/).includes(filename)) {
        mkdirSync(join(abs, ".."), { recursive: true });
        appendFileSync(
          abs,
          (existing.endsWith("\n") || existing === "" ? "" : "\n") +
            filename +
            "\n",
          "utf8",
        );
      }
    } catch (err) {
      throw new Error(
        `excludeFromGit: failed to exclude transient CMR runtime file "${filename}": ` +
          `${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  /**
   * The cmr worker's sandbox (souls + skills + CLIs baked into the 2b image).
   * `runCmrWorker` mounts the auth ONCE up-front (so it can fail-closed on the
   * worker's own Claude token — codex cmr R4) and passes it here, avoiding a
   * double-mount. The route legs are also explicit so the container env cannot
   * drift from the already-resolved worker spec.
   */
  protected cmrSandbox(
    auth: CmrAuth,
    reviewLegs: NonNullable<WorkerSpec["cmrReviewLegs"]>,
    outcomeLanding?: { path: string; sandboxPath: string },
  ): sc.SandboxProvider {
    return docker(this.cmrSandboxConfig(auth, reviewLegs, outcomeLanding));
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
    let tempCodexDir: string | undefined;
    try {
      // Per-INVOCATION unique dir (codex cmr R2): a fixed path would be rmSync'd
      // + rebuilt under a concurrent family CMR worker, deleting the dir it has
      // mounted. mkdtempSync gives each invocation its own owner-only (0700) dir.
      mkdirSync(root, { recursive: true, mode: 0o700 });
      tempCodexDir = mkdtempSync(join(root, "cmr-codex-auth-"));
      copyFileSync(join(home, ".codex", "auth.json"), join(tempCodexDir, "auth.json"));
      chmodSync(join(tempCodexDir, "auth.json"), 0o600);
      // The container IS the sandbox boundary; codex must NOT self-sandbox (nested
      // bwrap is impossible — the failure that degrades cmr legs to static-only).
      // The host config.toml is host-personal and irrelevant — only auth.json
      // crosses. Write the minimal container config (#378).
      writeContainerCodexConfig(join(tempCodexDir, "config.toml"));
      codexAuthDir = tempCodexDir;
    } catch {
      // codex auth absent ⇒ the codex leg degrades (no mount). Reclaim the
      // mkdtemp dir if it was created before copy/chmod threw (online review r2,
      // gemini): on the degrade path codexAuthDir stays undefined, so the per-
      // invocation dir would otherwise leak past the caller's finally cleanup.
      if (codexAuthDir === undefined && tempCodexDir !== undefined) {
        rmSync(tempCodexDir, { recursive: true, force: true });
      }
    }

    // agy OAuth token → a per-run WRITABLE dir mounted at the antigravity config
    // path (the agy CLI writes cache/log under its config dir, so it must NOT be
    // read-only — #333 gotcha).
    let agyDir: string | undefined;
    let tempAgyDir: string | undefined;
    try {
      // Per-INVOCATION unique dir (codex cmr R2): same concurrency hazard as the
      // codex dir above — and the agy dir is mounted WRITABLE, so a shared path
      // would also cross-talk runtime state between concurrent workers.
      mkdirSync(root, { recursive: true, mode: 0o700 });
      tempAgyDir = mkdtempSync(join(root, "cmr-agy-"));
      copyFileSync(join(home, ".sc-agy-oauth-token"), join(tempAgyDir, AGY_TOKEN_FILENAME));
      chmodSync(join(tempAgyDir, AGY_TOKEN_FILENAME), 0o600);
      agyDir = tempAgyDir;
    } catch {
      // agy token absent ⇒ the agy leg degrades (no mount); cmr falls to the rest.
      // Reclaim the mkdtemp dir if it was created before copy/chmod threw (online
      // review r2, gemini): on the degrade path agyDir stays undefined, so the
      // per-invocation dir would otherwise leak past the caller's finally cleanup.
      if (agyDir === undefined && tempAgyDir !== undefined) {
        rmSync(tempAgyDir, { recursive: true, force: true });
      }
    }

    let claudeToken: string | undefined;
    try {
      const tok = readFileSync(join(home, ".sc-claude-token"), "utf8").trim();
      // A present-but-empty/blank token file ⇒ undefined (the preflight escalates),
      // NOT an injected empty CLAUDE_CODE_OAUTH_TOKEN="" that defeats the gate
      // (cmr int-r3 A; matches readGhToken's `tok === "" ? undefined` normalization).
      claudeToken = tok === "" ? undefined : tok;
    } catch {
      // claude token absent ⇒ the Claude Agent leg degrades (no env var).
    }
    // gh token → GH_TOKEN for the in-container completeness gate's `gh issue view`
    // (the live issue body is its DELIVERED-vs-spec authority). BEST-EFFORT, mirroring
    // the ship worker's readGhToken extraction (host OS keyring, not a portable
    // hosts.yml) — but NOT preflighted: a missing token degrades the gate's authority,
    // it does not block the cmr worker (the cmr worker has no `gh pr create` to fail).
    return { codexAuthDir, agyDir, claudeToken, ghToken: this.readGhToken() };
  }

  /**
   * Reclaim the per-run temp auth dirs `mountCmrAuth` / `mountShipAuth` created
   * (online review r1, 3 bots): each `mkdtempSync` dir is unique per invocation and
   * is only needed for the lifetime of the container run it is mounted into. The
   * worker run paths wrap their `sc.run` in `try { … } finally { cleanup }` so the
   * dirs are reclaimed on success, exception, AND any early return — never leaked
   * into `~/.sc-orchestrator`. Best-effort (`force`): a missing dir is a no-op.
   */
  protected cleanupTempAuthDirs(dirs: ReadonlyArray<string | undefined>): void {
    for (const dir of dirs) {
      if (dir === undefined) continue;
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {
        // Best-effort cleanup: a failure to reclaim a transient dir must never
        // mask the worker's own outcome (the run already returned/threw).
      }
    }
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
   * SHADOW the baked skill (#334). The dedicated `cmr` soul carries review/outcome
   * discipline only; persistent fixes route through the family coder-fix worker.
   */
  protected cmrSandboxConfig(
    auth: CmrAuth,
    reviewLegs: NonNullable<WorkerSpec["cmrReviewLegs"]>,
    outcomeLanding?: { path: string; sandboxPath: string },
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    // ORCHESTRATOR_REPO too: the cmr worker runs `gh issue view` (completeness
    // authority) AND `gh issue create` (defer→tracker), both needing `--repo
    // "$ORCHESTRATOR_REPO"`. In a clone-from-LOCAL family run (launch sets
    // sourceRepo to the local repo) the container's git remote is the local path,
    // so gh's repo INFERENCE would target the wrong place — pass the slug explicitly
    // (codex #384). Mirrors ship/coder.
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
      [SANDBOX_SOUL_ENV]: CMR_SOUL,
      [SANDBOX_REPO_ENV]: this.opts.repo,
      ORCHESTRATOR_CMR_REVIEW_LEGS: JSON.stringify(reviewLegs),
    };
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    // The in-container completeness gate's `gh issue view` (the live issue body =
    // DELIVERED-vs-spec authority) reads GH_TOKEN. Inject only when present (mirrors
    // shipSandboxConfig's `!== undefined` guard); UNLIKE ship there is NO preflight —
    // gh absence degrades the gate's authority, it never blocks the cmr worker.
    if (auth.ghToken !== undefined) env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    if (outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = outcomeLanding.sandboxPath;
    }
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
    if (outcomeLanding !== undefined) {
      mounts.push({
        hostPath: outcomeLanding.path,
        sandboxPath: outcomeLanding.sandboxPath,
      });
    }
    // #372: souls mount live for integrated cmr worker (souls not baked).
    // Shared helper (single source for the mount + readonly:true).
    mounts.push(soulsMount(this.opts.soulsDir));
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
    const verifiedPr = this.verifyFamilyShipPr({
      pr: outcome.pr,
      familyBase: ctx.familyBase,
    });
    if (!verifiedPr.ok) {
      return { kind: "malformed", reason: verifiedPr.reason };
    }
    return {
      kind: "completed",
      output: {
        kind: "ship",
        branch: outcome.branch,
        status: outcome.status,
        pr: outcome.pr,
        prHead: verifiedPr.headOid,
      },
    };
  }

  /**
   * Run the family ship WORKER: ONE `sc.run` of the 2b container's route-selected agent
   * invoking `gstack-ship` over the checked-out family base (#336). `protected` so a
   * unit test fixtures the outcome without a real container (the real container only
   * runs on the driver / manual-smoke / e2e path).
   *
   * The worker is the container's TOP-LEVEL agent (gstack-ship's pipeline + any
   * retry cycles run there), under the WRITE (`coder`) soul (it
   * commits the VERSION/CHANGELOG bump + pushes + opens the PR).
   * `branchStrategy:{type:"head"}` keeps it on the checked-out family base. Its
   * `<ship>` tag is gated on the completion signal then classified.
   */
  protected async runShipWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ShipWorkerOutcome> {
    // FAIL-CLOSED on the WORKER's OWN auth (cmr S336 r8, mirroring the cmr worker's
    // preflight ~645-666): when the ship slot resolves to a Claude-family model,
    // the Claude OAuth token is NOT a degradable codex/gh LEG — it is THIS worker's
    // auth. Absent, the worker cannot start and never emits a `<ship>` verdict; that
    // failure would throw out of
    // `sc.run` (NOT a structured escalate), bypassing the WorkerResult routing
    // (dispatchShipWorker → verifyCmr only handle the RETURNED result, never a thrown
    // startup error — a fail-open that crashes the gate rather than honestly
    // escalating). gh auth is ALSO preflighted below (cmr S336 r10): it is
    // load-bearing for `gh pr create` (the family delivery), NOT a degradable leg.
    // Only codex auth stays best-effort (in-container diff review). Preflight BEFORE
    // any container work (the checkout + focus write below) so a no-token host
    // escalates cleanly. Mount once and reuse for the sandbox (no double-mount).
    // `mountShipAuth` creates a per-run temp codex auth dir BEFORE the early escalate
    // gates below; the finally reclaims it on success, exception, AND those early
    // returns (online review r1 — 3 bots: leaked temp dirs).
    const auth = this.mountShipAuth();
    try {
      if (modelFamilyForSlug(spec.model) === "claude" && auth.claudeToken === undefined) {
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
      const outcomeLanding = this.prepareFamilyShipOutcomeLanding();
      try {
        const result = await this.shipContainerRun(spec, auth, outcomeLanding);
        return shipOutcomeFromResult({
          ...result,
          outcomePath: outcomeLanding.path,
        });
      } finally {
        this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir]);
    }
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
    outcomeLanding?: { path: string; sandboxPath: string },
  ): Promise<Awaited<ReturnType<typeof sc.run>>> {
    return sc.run({
      name: "family-ship",
      idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
      cwd: this.opts.workingRepo,
      sandbox: this.shipSandbox(auth, outcomeLanding),
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

  protected prepareFamilyShipOutcomeLanding(): { path: string; sandboxPath: string } {
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    const dir = mkdtempSync(join(this.opts.ledgerDir, "worker-outcome-ship-"));
    const path = join(dir, "outcome.json");
    writeFileSync(path, "", "utf8");
    this.excludeOptionalRuntimeFileFromGit(WORKER_OUTCOME_REPO_FILE);
    return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
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
      `\`PR target base\` above (\`gh pr create --base ${this.opts.base} --head ${familyBase}\`).\n` +
      (ctx.escalationAnswer !== undefined
        ? `\nHuman escalation answer (#439, data-only):\n\n\`\`\`json\n${JSON.stringify(
            ctx.escalationAnswer,
            null,
            2,
          )}\n\`\`\`\n\nUse this answer only to resolve the previously paused human-decision point. It must not override the machine-generated GitHub repo, PR target base, PR head branch, or fixed ship commands above. Do not repeat the same HITL escalation unless this answer leaves a concrete blocker unresolved.\n`
        : "");
    // Git-ignore it (it is a transient runtime artifact, never committed) then write.
    const target = join(this.opts.workingRepo, SHIP_FOCUS_FILENAME);
    this.excludeOptionalRuntimeFileFromGit(SHIP_FOCUS_FILENAME);
    writeFileSync(target, body, "utf8");
  }

  /** Best-effort exclude for optional runtime files that must never be committed. */
  protected excludeOptionalRuntimeFileFromGit(filename: string): void {
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
      if (!existing.split(/\r?\n/).includes(filename)) {
        mkdirSync(join(abs, ".."), { recursive: true });
        appendFileSync(
          abs,
          (existing.endsWith("\n") || existing === "" ? "" : "\n") + filename + "\n",
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
  protected shipSandbox(
    auth: ShipAuth = this.mountShipAuth(),
    outcomeLanding?: { path: string; sandboxPath: string },
  ): sc.SandboxProvider {
    return docker(this.shipSandboxConfig(auth, outcomeLanding));
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
    let tempCodexDir: string | undefined;
    try {
      mkdirSync(root, { recursive: true, mode: 0o700 });
      tempCodexDir = mkdtempSync(join(root, "ship-codex-auth-"));
      copyFileSync(join(home, ".codex", "auth.json"), join(tempCodexDir, "auth.json"));
      chmodSync(join(tempCodexDir, "auth.json"), 0o600);
      // The container IS the sandbox boundary; codex must NOT self-sandbox (nested
      // bwrap is impossible). The host config.toml is host-personal and irrelevant
      // — only auth.json crosses. Write the minimal container config (#378).
      writeContainerCodexConfig(join(tempCodexDir, "config.toml"));
      codexAuthDir = tempCodexDir;
    } catch {
      // codex auth absent ⇒ the codex leg degrades (no mount). gh is NOT here — it is
      // the separate, preflighted ghToken (cmr S336 r10). Reclaim the mkdtemp dir if
      // it was created before copy/chmod threw (online review r2, gemini): on the
      // degrade path codexAuthDir stays undefined, so the per-invocation dir would
      // otherwise leak past the caller's finally cleanup.
      if (codexAuthDir === undefined && tempCodexDir !== undefined) {
        rmSync(tempCodexDir, { recursive: true, force: true });
      }
    }
    let claudeToken: string | undefined;
    try {
      const tok = readFileSync(join(home, ".sc-claude-token"), "utf8").trim();
      // A present-but-empty/blank token file ⇒ undefined (the preflight escalates),
      // NOT an injected empty CLAUDE_CODE_OAUTH_TOKEN="" that defeats the gate
      // (cmr int-r3 A; matches readGhToken's `tok === "" ? undefined` normalization).
      claudeToken = tok === "" ? undefined : tok;
    } catch {
      // claude token absent ⇒ Claude-family workers fail their preflight; non-Claude
      // route slots simply run without this env var.
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
  protected shipSandboxConfig(
    auth: ShipAuth,
    outcomeLanding?: { path: string; sandboxPath: string },
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    // ORCHESTRATOR_REPO too: the ship soul records a deferred finding with
    // `gh issue create --repo "$ORCHESTRATOR_REPO"`, so the family ship sandbox must
    // export it or that tracker write fails on an unset var (codex #384 — symmetric
    // with the single-slice ship sandbox).
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
      [SANDBOX_SOUL_ENV]: SHIP_SOUL,
      [SANDBOX_REPO_ENV]: this.opts.repo,
    };
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    // cmr S336 r10: the in-container `gh pr create` (the family delivery) reads
    // GH_TOKEN. Set only when present (the pure seam stays tolerant; the REQUIRE-gh
    // gate is the runShipWorker preflight — symmetric with the single-slice path).
    if (auth.ghToken !== undefined) env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    if (outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = outcomeLanding.sandboxPath;
    }
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [];
    if (auth.codexAuthDir !== undefined) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    if (outcomeLanding !== undefined) {
      mounts.push({
        hostPath: outcomeLanding.path,
        sandboxPath: outcomeLanding.sandboxPath,
      });
    }
    // #372: souls mount live for family ship worker.
    // Shared helper forces readonly:true at every site.
    mounts.push(soulsMount(this.opts.soulsDir));
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
    const verifiedPr = this.verifyFamilyShipPr({
      pr: url,
      familyBase: request.familyBase,
    });
    if (!verifiedPr.ok) {
      throw new Error(verifiedPr.reason);
    }
    return { url, prHead: verifiedPr.headOid };
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
    // Persist the decision pause on the append-only FAMILY LEDGER itself (#439).
    // This is the resume truth the family runner reads: no later
    // `escalation_answered` row keeps the run paused; a later answer reopens it.
    await recordFamilyEscalated(this, {
      escalationKind: "decision",
      phase: "final",
      reason: escalation.reason,
      familyHeadAfter: escalation.familyHeadAfter,
      stopSummary: escalation.stopSummary,
    });
  }

  /** Read the durable escalate stuck-points (for the caller / a re-entry). */
  async readEscalations(): Promise<ReadonlyArray<FamilyEscalationRecord>> {
    const ledgerEscalations = (this.readFamilyLedgerFile() ?? [])
      .filter((entry) => entry.status === "escalated" && entry.event === "escalated")
      .map((entry) => ({
        reason:
          typeof entry.reason === "string" && entry.reason.trim().length > 0
            ? entry.reason
            : "family escalation",
        ...(entry.escalationKind != null
          ? { escalationKind: entry.escalationKind }
          : {}),
        ...(entry.familyHeadAfter != null
          ? { familyHeadAfter: entry.familyHeadAfter }
          : {}),
      }));
    return [...this.readLegacyEscalationRecords(), ...ledgerEscalations];
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
        // When an explicit branch is given, try it directly. Otherwise try the
        // candidate branch names in order (current `feat/issue-<n>` first, then old
        // `feat/244-orchestrator-issue-<n>`), so a child resumed in place under the old
        // name is still recognised as already-merged — avoiding a double-merge bug.
        // (The proper end-state is to thread `childBranch` through ChildSlice/reconcile
        // — flagged to the driver unit; this fallback makes the seam WORK meanwhile.)
        // Explicit branch: only when a non-empty string was provided. `null` from
        // JSON/db round-trips and `undefined` (omitted) both fall through to the
        // candidate-list path; empty string is treated as absent too.
        if (typeof childBranch === "string" && childBranch.length > 0) {
          try {
            const childHead = sh(["rev-parse", "--verify", `${childBranch}^{commit}`]);
            return { exists: true, childHead };
          } catch {
            return { exists: false };
          }
        }
        for (const branch of candidateBranches(childIssue)) {
          try {
            const childHead = sh(["rev-parse", "--verify", `${branch}^{commit}`]);
            return { exists: true, childHead };
          } catch {
            // continue to next candidate
          }
        }
        return { exists: false };
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
 *   - `verdict`   — the worker produced a `{converged, reason?, successfulLegs}`
 *     verdict plus the leg slugs that actually reviewed (the normal case;
 *     `verifyCmr.ts` reads `converged` and enforces ADR0032's strong-leg floor);
 *   - `escalate`  — the worker is model-stuck (skill missing / no leg ran / it
 *     could not produce a verdict) ⇒ the runner's escalate续跑 fork, NOT a pass;
 *   - `malformed` — the run emitted no parseable `<cmr>` tag ⇒ the gate must never
 *     read it as a pass (fail-closed).
 * Deliberately NOT the bare {@link IntegratedCmrResult}: a cmr worker also has the
 * escalate / malformed WorkerResult-level cases the bare verdict cannot carry.
 */
export type CmrWorkerOutcome =
  | {
      readonly kind: "verdict";
      readonly converged: boolean;
      readonly reason?: string;
      readonly successfulLegs: readonly string[];
      readonly skippedLegs?: readonly CmrSkippedLeg[];
      readonly claimedFixedFindingIdentityKeys?: readonly string[];
      readonly priorFindingDispositions?: readonly PriorFindingDisposition[];
      readonly findings?: readonly Finding[];
      readonly evidencePaths: readonly string[];
      readonly sessionId?: string;
    }
  | {
      readonly kind: "escalate";
      readonly reason: string;
      readonly diagnosis: string;
      readonly sessionId?: string;
    }
  | {
      readonly kind: "malformed";
      readonly reason: string;
      readonly sessionId?: string;
      readonly cmrLegAccountingPayload?: {
        readonly successfulLegs?: readonly string[];
        readonly skippedLegs?: readonly { readonly slug: string; readonly reason: string }[];
      };
    };

interface CmrSkippedLeg {
  readonly slug: string;
  readonly reason: string;
}

function withCmrSession(
  outcome: CmrWorkerOutcome,
  sessionId: string | undefined,
): CmrWorkerOutcome {
  return sessionId === undefined ? outcome : { ...outcome, sessionId };
}

function lastSessionIdIfPresent(result: unknown): string | undefined {
  const iterations = (result as { readonly iterations?: unknown }).iterations;
  if (!Array.isArray(iterations)) return undefined;
  return lastSessionId({
    iterations: iterations as ReadonlyArray<{ readonly sessionId?: string }>,
  });
}

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
  /**
   * The host gh OAuth token (`gh auth token` → {@link SANDBOX_GH_TOKEN_ENV} env), or
   * undefined if absent. BEST-EFFORT (unlike the ship worker's hard-required gh): the
   * completeness gate grounds against the live issue body via `gh issue view`, so a
   * present token keeps that authority intact, but its ABSENCE only DEGRADES the gate
   * (it falls back to commit-titles/test-files) — it never blocks the cmr worker.
   */
  readonly ghToken?: string;
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
 * The merger worker's auth (integ-cmr int-r2 A-1). When the active route selects a
 * Claude-family merger slug, the claude OAuth token is its OWN auth
 * (LOAD-BEARING) — `runMergerAgent` preflights it and returns a structured
 * non-resolve when absent. The merger resolves + commits the merge in place
 * (`branchStrategy:{type:"head"}`); it never pushes or opens a PR.
 */
export interface MergerAuth {
  /** Per-run codex auth dir (host-mirrored `~/.codex`), or undefined if absent. */
  readonly codexAuthDir?: string;
  /** The claude OAuth token (env var), or undefined if absent. */
  readonly claudeToken?: string;
}

/**
 * Decide the cmr worker outcome from a Sandcastle run result. Guarded CMR workers
 * write their machine result to the runner-owned sidecar; a valid sidecar is the
 * completion proof and verdict source. Legacy/no-sidecar workers still require the
 * Sandcastle completion signal before stdout fallback is trusted.
 */
export function cmrOutcomeFromResult(result: {
  completionSignal?: string | string[];
  cmrReviewLegs?: ReadonlyArray<{ readonly slug: string }>;
  outcomePath?: string;
  stdout: string;
}): CmrWorkerOutcome {
  const signal = result.completionSignal;
  const signaled = Array.isArray(signal)
    ? signal.includes(CMR_COMPLETION_SIGNAL)
    : signal === CMR_COMPLETION_SIGNAL;
  try {
    if (result.outcomePath !== undefined) {
      const sidecar = readRequiredWorkerOutcomeSidecar(result.outcomePath);
      return classifyCmrOutcomePayload(
        sidecar,
        result.cmrReviewLegs ?? process.env,
        "cmr worker outcome sidecar",
      );
    }
  } catch (err) {
    if (!signaled) return missingCmrCompletionSignalOutcome(signal);
    return {
      kind: "malformed",
      reason:
        `cmr worker outcome sidecar was not valid JSON: ` +
        `${err instanceof Error ? err.message : String(err)}`,
    };
  }

  if (!signaled) {
    return missingCmrCompletionSignalOutcome(signal);
  }
  return parseCmrOutcome(result.stdout, result.cmrReviewLegs);
}

function missingCmrCompletionSignalOutcome(
  signal: string | string[] | undefined,
): CmrWorkerOutcome {
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

/** A trimmed, non-empty string at the schema layer (mirrors shipOutcome.ts). */
const nonEmpty = z.string().trim().min(1);

/**
 * The three — and ONLY three — `<cmr>` shapes (integ-cmr int-r1, Finding A;
 * mirrors shipOutcome.ts `.strict()` union). Each is `.strict()` so any EXTRA /
 * mixed key (a converged success carrying an `escalate` verdict, an off-contract
 * field) is rejected → malformed, closing the same "too-lax shape leaks the pass
 * branch" fail-open the ship parser was already hardened against. The contract is
 * the integrated CMR pass prompts' "must match one of the shapes above exactly":
 *   1. `{converged:true, successfulLegs, skippedLegs?, evidencePaths}`           — converged;
 *   2. `{converged:false, reason, successfulLegs, skippedLegs?, evidencePaths}`  — not converged;
 *   3. `{escalate:{reason, diagnosis}}`            — could not run the review.
 * Verdicts must also account for every default CMR leg: each must be either
 * successful or explicitly skipped.
 * Escalate is tried FIRST (a stuck worker carries no usable verdict).
 */
const cmrLegSlugSchema = z.string().trim().min(1);
const cmrSkippedLegSchema = z
  .object({ slug: cmrLegSlugSchema, reason: nonEmpty })
  .strict();
const cmrVerdictLegsSchema = {
  successfulLegs: z.array(cmrLegSlugSchema).min(1),
  skippedLegs: z.array(cmrSkippedLegSchema).optional(),
} as const;
const cmrFindingDispositionSchema = z
  .object({
    identityKey: nonEmpty,
    status: z.enum([
      "still-active",
      "verified-closed",
      "unable-to-assess",
      "accepted_suppressed",
    ]),
    reason: z.string().optional(),
    source: z.string().optional(),
    scope: z.string().optional(),
    boundedReopen: z.string().optional(),
  })
  .strict()
  .superRefine((disposition, ctx) => {
    if (disposition.status !== "accepted_suppressed") return;
    for (const field of ["reason", "source", "scope", "boundedReopen"] as const) {
      if (disposition[field] === undefined || disposition[field].trim() === "") {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `accepted_suppressed prior finding disposition requires ${field}`,
          path: [field],
        });
      }
    }
    if (
      disposition.source !== undefined &&
      !hasExplicitAcceptedSuppressionSource(disposition.source)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "accepted_suppressed prior finding disposition requires explicit user/ADR/issue source",
        path: ["source"],
      });
    }
    if (
      disposition.boundedReopen !== undefined &&
      !hasBoundedReopenCondition(disposition.boundedReopen)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "accepted_suppressed prior finding disposition requires bounded reopen condition",
        path: ["boundedReopen"],
      });
    }
  });
const cmrClosureSchema = {
  claimedFixedFindingIdentityKeys: z.array(nonEmpty),
  priorFindingDispositions: z.array(cmrFindingDispositionSchema),
} as const;
// #604 slice 4 (ADR 0062): the CMR reviewer contract no longer carries routing
// disposition kinds — the only disposition a reviewer may emit is the
// accepted-suppression governance carrier.
const cmrDispositionEvidenceSchema = z
  .object({
    kind: z.literal("accepted_suppressed"),
    source: nonEmpty,
    scope: nonEmpty,
    reason: nonEmpty,
    findingIdentity: nonEmpty.optional(),
    boundedReopen: nonEmpty,
  })
  .strict()
  .superRefine((disposition, ctx) => {
    if (!hasExplicitAcceptedSuppressionSource(disposition.source)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "accepted_suppressed requires explicit user/ADR/issue source",
        path: ["source"],
      });
    }
    if (!hasBoundedReopenCondition(disposition.boundedReopen)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "accepted_suppressed requires bounded reopen condition",
        path: ["boundedReopen"],
      });
    }
  });
export const cmrReviewerFindingSchema = z
  .object({
    severity: z.enum(["critical", "high", "medium", "low", "clarity"]),
    category: z.string(),
    claim_quote: z.string(),
    location: z.string(),
    suggested_fix: z.string(),
    action: z.enum(["fix_now", "wont_fix", "rejected"]),
    disposition_reason: z.string().optional(),
    disposition: cmrDispositionEvidenceSchema.optional(),
  })
  .strict()
  .superRefine((finding, ctx) => {
    if (
      (finding.severity === "critical" || finding.severity === "high") &&
      finding.action !== "fix_now"
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["action"],
        message: "critical/high findings must be fix_now",
      });
    }
    // #604 correctness r1 (P2-a): an `accepted_suppressed` governance disposition
    // is ONLY valid on a wont_fix/rejected finding. On a fix_now finding it would
    // otherwise validate, and classifyFindings (fix_now ⇒ blocking) would silently
    // turn the governance suppression into a blocker. Reject it here.
    if (
      finding.action !== "wont_fix" &&
      finding.action !== "rejected" &&
      finding.disposition?.kind === "accepted_suppressed"
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["disposition"],
        message:
          "accepted_suppressed disposition is only valid on wont_fix/rejected findings",
      });
    }
    if (
      (finding.action === "wont_fix" || finding.action === "rejected") &&
      ((!finding.disposition_reason && !finding.disposition?.reason) ||
        finding.disposition?.kind !== "accepted_suppressed")
    ) {
      ctx.addIssue({
        code: "custom",
        path: ["disposition"],
        message: "suppressed findings require accepted_suppressed disposition",
      });
    }
  });
function normalizeCmrReviewerFinding(
  finding: z.infer<typeof cmrReviewerFindingSchema>,
): Finding {
  if (
    (finding.action !== "wont_fix" && finding.action !== "rejected") ||
    finding.disposition?.kind !== "accepted_suppressed"
  ) {
    return finding;
  }
  return {
    ...finding,
    disposition_reason: finding.disposition.reason ?? finding.disposition_reason,
    disposition: {
      ...finding.disposition,
      findingIdentity:
        finding.disposition.findingIdentity ?? findingIdentityKey(finding),
    },
  };
}
const cmrFindingsSchema = {
  findings: z.array(cmrReviewerFindingSchema).optional(),
} as const;
const cmrEvidenceSchema = {
  evidencePaths: z.array(nonEmpty).min(1),
} as const;
const cmrConvergedSchema = z
  .object({
    converged: z.literal(true),
    ...cmrVerdictLegsSchema,
    ...cmrClosureSchema,
    ...cmrFindingsSchema,
    ...cmrEvidenceSchema,
  })
  .strict()
  .superRefine((outcome, ctx) => {
    const fixNowIndex = outcome.findings?.findIndex(
      (finding) => finding.action === "fix_now",
    );
    if (fixNowIndex !== undefined && fixNowIndex >= 0) {
      ctx.addIssue({
        code: "custom",
        path: ["findings", fixNowIndex, "action"],
        message: "converged CMR outcome cannot carry fix_now findings",
      });
    }
  });
const cmrRedSchema = z
  .object({
    converged: z.literal(false),
    reason: nonEmpty,
    ...cmrVerdictLegsSchema,
    ...cmrClosureSchema,
    ...cmrFindingsSchema,
    ...cmrEvidenceSchema,
  })
  .strict();
const cmrEscalateSchema = z
  .object({ escalate: z.object({ reason: nonEmpty, diagnosis: nonEmpty }).strict() })
  .strict();

function isJsonRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function normalizeKnownCmrAliases(parsed: Record<string, unknown>): Record<string, unknown> {
  const dispositions = parsed.priorFindingDispositions;
  if (!Array.isArray(dispositions)) return parsed;
  return {
    ...parsed,
    priorFindingDispositions: dispositions.map((rawDisposition) => {
      if (
        !isJsonRecord(rawDisposition) ||
        typeof rawDisposition.disposition !== "string"
      ) {
        return rawDisposition;
      }
      const { disposition, status, ...withoutAlias } = rawDisposition;
      return { ...withoutAlias, status: status ?? disposition };
    }),
  };
}

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
export function parseCmrOutcome(
  stdout: string,
  routeOrEnv: CmrLegAccountingRoute = process.env,
): CmrWorkerOutcome {
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
  return classifyCmrOutcomePayload(parsed, routeOrEnv, "cmr worker <cmr> tag");
}

function classifyCmrOutcomePayload(
  parsed: unknown,
  routeOrEnv: CmrLegAccountingRoute,
  source: string,
): CmrWorkerOutcome {
  // `JSON.parse` succeeds on bare literals (`null` / `true` / `5`); the strict
  // schemas reject every non-object, but guard explicitly so the malformed
  // message stays specific (mirrors parseShipOutcome / parseMergerOutcome).
  if (!isJsonRecord(parsed)) {
    return { kind: "malformed", reason: `${source} was not a JSON object` };
  }
  const normalizedParsed = normalizeKnownCmrAliases(parsed);
  if (
    normalizedParsed.converged === true &&
    Array.isArray(normalizedParsed.findings) &&
    normalizedParsed.findings.some(
      (finding) => isJsonRecord(finding) && finding.action === "fix_now",
    )
  ) {
    return {
      kind: "malformed",
      reason: `${source} cannot be converged while findings include fix_now actions`,
    };
  }
  // Escalate FIRST — a model-stuck worker never carries a usable verdict.
  const escalate = cmrEscalateSchema.safeParse(normalizedParsed);
  if (escalate.success) {
    return {
      kind: "escalate",
      reason: escalate.data.escalate.reason,
      diagnosis: escalate.data.escalate.diagnosis,
    };
  }
  if (cmrConvergedSchema.safeParse(normalizedParsed).success) {
    const converged = cmrConvergedSchema.parse(normalizedParsed);
    const legAccountingFailure = cmrLegAccountingFailure(converged, routeOrEnv);
    if (legAccountingFailure !== undefined) {
      return {
        kind: "malformed",
        reason: legAccountingFailure,
        cmrLegAccountingPayload: {
          successfulLegs: converged.successfulLegs,
          ...(converged.skippedLegs !== undefined
            ? { skippedLegs: converged.skippedLegs }
            : {}),
        },
      };
    }
    return {
      kind: "verdict",
      converged: true,
      successfulLegs: converged.successfulLegs,
      ...(converged.skippedLegs !== undefined ? { skippedLegs: converged.skippedLegs } : {}),
      claimedFixedFindingIdentityKeys:
        converged.claimedFixedFindingIdentityKeys,
      priorFindingDispositions: converged.priorFindingDispositions,
      ...(converged.findings !== undefined
        ? { findings: converged.findings.map(normalizeCmrReviewerFinding) }
        : {}),
      evidencePaths: converged.evidencePaths,
    };
  }
  const red = cmrRedSchema.safeParse(normalizedParsed);
  if (red.success) {
    const legAccountingFailure = cmrLegAccountingFailure(red.data, routeOrEnv);
    if (legAccountingFailure !== undefined) {
      return {
        kind: "malformed",
        reason: legAccountingFailure,
        cmrLegAccountingPayload: {
          successfulLegs: red.data.successfulLegs,
          ...(red.data.skippedLegs !== undefined
            ? { skippedLegs: red.data.skippedLegs }
            : {}),
        },
      };
    }
    return {
      kind: "verdict",
      converged: false,
      reason: red.data.reason,
      successfulLegs: red.data.successfulLegs,
      ...(red.data.skippedLegs !== undefined ? { skippedLegs: red.data.skippedLegs } : {}),
      claimedFixedFindingIdentityKeys: red.data.claimedFixedFindingIdentityKeys,
      priorFindingDispositions: red.data.priorFindingDispositions,
      ...(red.data.findings !== undefined
        ? { findings: red.data.findings.map(normalizeCmrReviewerFinding) }
        : {}),
      evidencePaths: red.data.evidencePaths,
    };
  }
  return {
    kind: "malformed",
    reason:
      `${source} matched no valid shape (expected one of: ` +
      "{converged:true,successfulLegs,skippedLegs?,claimedFixedFindingIdentityKeys,priorFindingDispositions,evidencePaths}, " +
      "{converged:false,reason,successfulLegs,skippedLegs?,claimedFixedFindingIdentityKeys,priorFindingDispositions,evidencePaths}, " +
      "{escalate:{reason,diagnosis}} — non-empty strings, no extra keys)",
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
  outcomePath?: string;
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
  try {
    if (result.outcomePath !== undefined) {
      const sidecar = readRequiredWorkerOutcomeSidecar(result.outcomePath);
      return classifyMergerOutcomePayload(sidecar, "merger agent outcome sidecar");
    }
  } catch (err) {
    return {
      resolved: false,
      reason:
        `merger agent outcome sidecar was not valid JSON: ` +
        `${err instanceof Error ? err.message : String(err)}`,
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
  return classifyMergerOutcomePayload(parsed, "merger agent <merger> tag");
}

function classifyMergerOutcomePayload(
  parsed: unknown,
  source: string,
): { resolved: boolean; reason?: string } {
  // `JSON.parse` succeeds on the bare literals `null` / `true` / `5` / `"x"`; the
  // strict schemas reject every non-object, but guard explicitly so the message
  // stays specific (agy R1: a non-object must never crash or coerce to resolved).
  if (parsed === null || typeof parsed !== "object") {
    return { resolved: false, reason: `${source} was not a JSON object` };
  }
  if (mergerResolvedSchema.safeParse(parsed).success) {
    return { resolved: true };
  }
  const escalate = mergerEscalateSchema.safeParse(parsed);
  if (escalate.success) {
    return {
      // `reason` is a required `nonEmpty` field in mergerEscalateSchema, so it is
      // always a non-empty string here — the old `?? diagnosis` fallback was dead
      // code (online review r3, gemini). `diagnosis` stays an optional schema field.
      resolved: false,
      reason: escalate.data.escalate.reason,
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

// ════════════════════════════════════════════════════════════════════════════
// #596 F2: family-side real decode/transport path for the 4 review-loop kinds.
// Mirror cmr/ship/merger parse style (last <tag> wins, JSON, explicit malformed on
// bad shape). Use isValid*Result guards (from reviewLoopOutcome) as decode validation.
// Raw (tag string) fed in tests — not fake WorkerOutput construction. Shape-valid
// false flags pass (no semantic branching). Malformed fails closed.
// Single-slice uses RealBackend outputFor/decodeOutput + extract*Tag; this is family eqv.
// ════════════════════════════════════════════════════════════════════════════

function extractLastTag(stdout: string, tag: string): string | undefined {
  // Mirror single-slice extractTaggedJson semantics exactly (indexOf collection +
  // backward scan for last start that has a close after it). This avoids:
  // (1) prose/conversational <tag> mentions before the real block poisoning the
  //     span (regex from mention open to first close), (2) regex perf on large
  //     stdout, (3) divergence from the realBackend.ts side of the seam.
  // lastIndexOf alone is insufficient (must fallback from unclosed trailing opens).
  const open = `<${tag}>`;
  const close = `</${tag}>`;
  const starts: number[] = [];
  for (
    let idx = stdout.indexOf(open);
    idx !== -1;
    idx = stdout.indexOf(open, idx + open.length)
  ) {
    starts.push(idx);
  }
  if (starts.length === 0) {
    return undefined;
  }
  for (let i = starts.length - 1; i >= 0; i -= 1) {
    const bodyStart = starts[i] + open.length;
    const end = stdout.indexOf(close, bodyStart);
    if (end === -1) continue;
    const body = stdout.slice(bodyStart, end);
    return body;
  }
  return undefined;
}

export function parseVerifyOutcome(
  stdout: string,
): VerifyResult | { kind: "malformed"; reason: string } {
  const last = extractLastTag(stdout, "verify");
  if (last === undefined) {
    return { kind: "malformed", reason: "verify worker emitted no <verify> tag" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { kind: "malformed", reason: "verify worker <verify> tag was not valid JSON" };
  }
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "malformed", reason: "verify worker <verify> tag was not a JSON object" };
  }
  // #596 r2 (R2-1): strict key validation via the same .strict() schema used on
  // single-slice side (realBackend decodeOutput). Extra keys → malformed (fail-closed),
  // matching parseCmrOutcome / parse* style and the header claim to "Mirror cmr…parse style".
  const shape = verifyOutputSchema.safeParse(parsed);
  if (!shape.success) {
    return {
      kind: "malformed",
      reason: "verify worker <verify> tag did not satisfy verifyOutputSchema (extra keys or wrong types)",
    };
  }
  const candidate: VerifyResult = { kind: "verify", converged: shape.data.converged };
  if (!isValidVerifyResult(candidate)) {
    return { kind: "malformed", reason: "verify worker <verify> tag did not satisfy isValidVerifyResult guard" };
  }
  return candidate;
}

export function parseFixerOutcome(
  stdout: string,
): FixerResult | { kind: "malformed"; reason: string } {
  const last = extractLastTag(stdout, "fixer");
  if (last === undefined) {
    return { kind: "malformed", reason: "fixer worker emitted no <fixer> tag" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { kind: "malformed", reason: "fixer worker <fixer> tag was not valid JSON" };
  }
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "malformed", reason: "fixer worker <fixer> tag was not a JSON object" };
  }
  // #596 r2 (R2-1): strict key validation via the same .strict() schema used on
  // single-slice side. Extra keys → malformed (fail-closed).
  const shape = fixerOutputSchema.safeParse(parsed);
  if (!shape.success) {
    return {
      kind: "malformed",
      reason: "fixer worker <fixer> tag did not satisfy fixerOutputSchema (extra keys or wrong types)",
    };
  }
  const candidate: FixerResult = { kind: "fixer", committed: shape.data.committed };
  if (!isValidFixerResult(candidate)) {
    return { kind: "malformed", reason: "fixer worker <fixer> tag did not satisfy isValidFixerResult guard" };
  }
  return candidate;
}

export function parseCleanupOutcome(
  stdout: string,
): CleanupResult | { kind: "malformed"; reason: string } {
  const last = extractLastTag(stdout, "cleanup");
  if (last === undefined) {
    return { kind: "malformed", reason: "cleanup worker emitted no <cleanup> tag" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { kind: "malformed", reason: "cleanup worker <cleanup> tag was not valid JSON" };
  }
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "malformed", reason: "cleanup worker <cleanup> tag was not a JSON object" };
  }
  // #596 r2 (R2-1): strict key validation via the same .strict() schema used on
  // single-slice side. Extra keys → malformed (fail-closed).
  const shape = cleanupOutputSchema.safeParse(parsed);
  if (!shape.success) {
    return {
      kind: "malformed",
      reason: "cleanup worker <cleanup> tag did not satisfy cleanupOutputSchema (extra keys or wrong types)",
    };
  }
  const candidate: CleanupResult = { kind: "cleanup", ok: shape.data.ok };
  if (!isValidCleanupResult(candidate)) {
    return { kind: "malformed", reason: "cleanup worker <cleanup> tag did not satisfy isValidCleanupResult guard" };
  }
  return candidate;
}

export function parseDocReleaseOutcome(
  stdout: string,
): DocReleaseResult | { kind: "malformed"; reason: string } {
  const last = extractLastTag(stdout, "docRelease");
  if (last === undefined) {
    return { kind: "malformed", reason: "docRelease worker emitted no <docRelease> tag" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(last.trim());
  } catch {
    return { kind: "malformed", reason: "docRelease worker <docRelease> tag was not valid JSON" };
  }
  if (parsed === null || typeof parsed !== "object") {
    return { kind: "malformed", reason: "docRelease worker <docRelease> tag was not a JSON object" };
  }
  // #596 r2 (R2-1): strict key validation via the same .strict() schema used on
  // single-slice side. Extra keys → malformed (fail-closed).
  const shape = docReleaseOutputSchema.safeParse(parsed);
  if (!shape.success) {
    return {
      kind: "malformed",
      reason: "docRelease worker <docRelease> tag did not satisfy docReleaseOutputSchema (extra keys or wrong types)",
    };
  }
  const candidate: DocReleaseResult = { kind: "docRelease", released: shape.data.released };
  if (!isValidDocReleaseResult(candidate)) {
    return { kind: "malformed", reason: "docRelease worker <docRelease> tag did not satisfy isValidDocReleaseResult guard" };
  }
  return candidate;
}
