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
 *   - runIntegratedCmr         → a legacy per-method throw seam; production CMR
 *     runs as a container worker through `dispatchWorker`.
 *   - dispatchWorker(ship)     → the `gstack-ship` worker opens the family PR;
 *     online bot CMR + merge remain the separate PR-review-loop stage.
 *   - recordAborted            → the #296 in-memory back-compat seam (a no-op
 *     here): the durable PHASE-LEVEL `aborted` entry is `recordDurableAbort`'s job
 *     (verifyCmr.ts calls both; only the durable writer appends — exactly one entry).
 *   - escalateFamily           → a durable family-ledger decision escalation
 *     (ADR 0017/0018 升级续跑: 卡点 → 返回调用端 → append answer → resume).
 *   - reconcileGit()           → the {@link ReconcileGit} four predicates over
 *     `git rev-parse` / `git rev-parse --verify` / `git merge-base --is-ancestor`.
 *
 * SEAM BOUNDARY: the deterministic git / file ops run directly; the external side
 * effects go through dispatch/protected seams that unit tests can override. The
 * production driver is wired to this backend; real container/GitHub effects run
 * only on its driver/manual-smoke path.
 */

import { shWithClock } from "../externalCall.js";
import { formatExecFailureOutput } from "../execFailureOutput.js";
import {
  ensureRegularFileForBindMount,
  gitExitStatus,
  isFileNotFound,
} from "../fsErrors.js";
import {
  appendGitInfoExclude,
  ensureGitInfoExclude,
} from "../gitInfoExclude.js";
import {
  appendFileSync,
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
import {
  classifyDecisionGate,
  coderReceiptOutput,
  logAndRethrowReceiptFailure,
  mergerReceiptOutput,
  onlineReviewReceiptOutput,
  requireTypedTrafficSignal,
  runSandcastleWithOnlineReviewSoGuard,
  shipReceiptOutput,
  workerReceiptOutput,
} from "../receiptRecovery.js";
import {
  CODER_RECEIPT_TAG,
  JUDGE_RECEIPT_TAG,
  MERGER_RECEIPT_TAG,
  ONLINE_REVIEW_RECEIPT_TAG,
  SHIP_RECEIPT_TAG,
  coderStationReceiptSchema,
  decodeJudgeVerdict,
  decodeMergerEnvelope,
  decodeOnlineReviewEnvelope,
  judgeStationReceiptSchema,
  mergerStationReceiptSchema,
  onlineReviewStationReceiptSchema,
  shipStationReceiptSchema,
  type JudgeVerdict,
} from "../stationReceiptContracts.js";
import {
  judgeResultFromVerdict,
  materializeLandingFixPacketBody,
  unusableResidualOpenCountPaper,
} from "../judgeStation.js";
import {
  successfulLegsFromTransports,
  type LegTransport,
} from "../legPaper.js";
import {
  CMR_PANEL_LEG_COMPLETENESS_PROMPT_FILE,
  CMR_PANEL_LEG_CORRECTNESS_PROMPT_FILE,
  panelLegCompletedResult,
} from "./cmrPanelLegs.js";

import "../sandcastleCancelSeam.js"; // #1010 first: patch before sandcastle load
import * as sc from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

import {
  hasBoundedReopenCondition,
  hasExplicitAcceptedSuppressionSource,
} from "../acceptedSuppression.js";
import { findingIdentityKey } from "../findings.js";
import {
  isGitMutexHeldInProcess,
  runExclusive,
  runExclusiveSync,
} from "../gitMutex.js";
import { runnerSynthesizedFailureEscalation } from "../runnerEscalation.js";
import {
  isBillingPoolDispatchId,
  modelFamilyForCmrReviewLeg,
  resolveModelSlugForPool,
  unavailableProviderAuth,
  type ProviderAuthAvailability,
  resumeCapableForSlug,
  appendAgySoulMount,
} from "../modelRegistry.js";
import {
  agentForSlug,
  candidateBranches,
  lastSessionId,
  projectCoderStationReceipt,
  SANDBOX_CODEX_DIR,
  SANDBOX_GROK_DIR,
  appendAgyAuthMount,
  provisionFamilyWorkerAuth,
  providerAuthFromCore,
  type FamilyWorkerAuthCore,
  SANDBOX_FIX_FINDINGS_PATH_ENV,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_ISSUE_NUMBER_ALIAS_ENV,
  SANDBOX_ISSUE_NUMBER_ENV,
  SANDBOX_REPO_ENV,
  SANDBOX_SKILLS_DIR,
  SANDBOX_OUTCOME_PATH_ENV,
  SPAWNED_WORKER_ENV,
  WORKER_IDLE_TIMEOUT_SECONDS,
  modelFamilyForSlug,
  soulsMount,
  REQUIRED_SOUL_FILES,
  soulsDirError,
  type AgentSandboxRunOptions,
  appendHomeEnvMount,
  homeEnvFileFromSoulsDir,
} from "../realBackend.js";
import { withSandcastleInvokeDefaults } from "../sandboxStreamHeartbeat.js";
import {
  materializeRawReviewerArtifactsForSandbox,
  RAW_REVIEWER_SIDECAR_SANDBOX_FILE,
  RAW_REVIEWER_STDOUT_SANDBOX_FILE,
} from "../rawReviewerArtifacts.js";
import {
  ONLINE_REVIEW_LANDING_FILE,
  OnlineReviewLoopTerminal,
  SANDBOX_ONLINE_REVIEW_PATH_ENV,
} from "./onlineReviewLoop.js";
import { isQuotaWaitForResetError } from "../quotaProbe.js";
import {
  PROVISION_SUBPROCESS_TIMEOUT_MS,
  provisionNodeModules,
  resolveTemplateProjectDir,
  runProvisionCommand,
} from "../provisionNodeModules.js";
import {
  WORKER_OUTCOME_REPO_FILE,
  WORKER_OUTCOME_SANDBOX_FILE,
  readWorkerOutcomeSidecar,
  readRequiredWorkerOutcomeSidecar,
} from "../workerOutcomeSidecar.js";
import {
  extractLastTagBody,
  parseLastTaggedJsonSoft,
} from "../lastTaggedJson.js";
import { modelForSlot, type ResolvedModelRoute } from "../modelRoutes.js";
import {
  buildCliMonitorSpawnSpec,
  workerResultFromMonitorSidecar,
} from "../cliMonitorHooks.js";
import { legacyDispatchFamilyWorker } from "./dispatchFamilyWorker.js";
import { retryProcessCrash } from "../dispatchRetry.js";
import {
  formatSandcastleAgentError,
  isSandcastleAgentError,
} from "../sandcastleAgentError.js";
import {
  LANDING_PROMPT_FILE,
  FIXER_PROMPT_FILE,
  VERIFY_PROMPT_FILE,
  workerHostForModel,
} from "../dispatchWorker.js";
import { dispatchPostMergeCleanup } from "../postMergeCleanup.js";
import type { Sh } from "../familyDriver.js";
import { parseFamilyLedgerJsonl, recordFamilyEscalated } from "./ledger.js";
import { shipOutcomeFromResult } from "../shipOutcome.js";
import {
  configureTelemetryFromWorkerImage,
  createTelemetryLegStamper,
  recordVerificationStamp,
  scheduleTelemetryEnvironmentStamp,
} from "../telemetry.js";

import type {
  CleanupResult,
  CliMonitorSpawnSpec,
  DispatchContext,
  LandingResult,
  Escalation,
  WorkerMonitorHandle,
  Finding,
  FixerResult,
  OnlineReviewFindingDisposition,
  OnlineReviewThreadReply,
  PriorFindingDisposition,
  VerifyResult,
  VerifyWorkerTerminalState,
  WorkerLandingPayload,
  WorkerOutput,
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
  ReconcileGit,
} from "./types.js";
import type { VerifyCmrPhase } from "./verifyCmr.js";

/** The family-ledger sibling filename (under {@link RealFamilyBackendOptions.ledgerDir}). */
export const FAMILY_LEDGER_FILENAME = "family-ledger.jsonl";
/** Legacy durable escalate stuck-point filename, read for migration/back-compat. */
export const FAMILY_ESCALATION_FILENAME = "family-escalations.jsonl";

/** Re-export agy mount constants (canonical definitions live in realBackend). */
export { SANDBOX_AGY_DIR, AGY_TOKEN_FILENAME } from "../realBackend.js";

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
 * infers the repo default branch and cannot honor a non-main integration target.
 */
export const SHIP_FOCUS_FILENAME = ".ship-focus.md";

/** Compatibility read model for durable family-ledger escalation rows. */
export interface FamilyEscalationRecord extends Omit<FamilyEscalation, "escalationKind"> {
  readonly escalationKind?: FamilyLedgerEntry["escalationKind"];
  readonly familyHeadAfter?: string;
}

/** Options for {@link RealFamilyBackend}. */
export interface RealFamilyBackendOptions {
  /** Enable Codex priority processing for every in-container Codex leg. */
  readonly codexFast?: boolean;
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
   * #746 — monorepo root whose warm `node_modules` trees are the clonefile
   * template for verify installs (typically the driver `sourceRepo`). Not a
   * user-facing config surface: familyDriver wires it from sourceRepo. When
   * absent, installDeps falls back to full npm ci/install (pre-#746 behaviour).
   */
  readonly depsTemplateRoot?: string;
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
  /** GitHub repo slug for `gh` (`owner/name`). */
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
  /**
   * #911 — container home environment file (default: sibling image/home/CLAUDE.md).
   * Live-mounted for Claude; content also replaces AGENTS.md in per-issue codex auth dirs.
   */
  readonly homeEnvFile?: string;
  /** The profile image (skills + CLIs baked in; souls mounted live #372) for the merger agent sandbox. */
  readonly imageName: string;
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
   * `~/.gemini/antigravity-cli/antigravity-oauth-token`, `~/.sc-claude-token`). Defaults to {@link homedir}.
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
    // #1094: pass-distinct panel-leg prompts (one authoritative source per lens).
    "cmr_panel_leg_completeness.md",
    "cmr_panel_leg_correctness.md",
    // #1068 added a thin wave-verify triage judge promptFile
    // (waveVerifyJudgeWorkerSpec); it is family-dispatched, so it belongs to the
    // construction-time inventory the same as the integrated CMR prompts.
    "wave_verify_judge.md",
    "coder_fix.md",
    "family_ship.md",
    MERGER_CONFLICT_PROMPT,
    VERIFY_PROMPT_FILE,
    FIXER_PROMPT_FILE,
    LANDING_PROMPT_FILE,
  ]),
];
/** The merger resolver model slot, selected by the active route. */
export function mergerModel(route?: ResolvedModelRoute): string {
  return route?.slots.merger ?? modelForSlot("merger");
}

function mergerWorkerSpec(model: string): WorkerSpec {
  return {
    id: "S1",
    kind: "merge",
    role: "coder",
    host: workerHostForModel(model),
    session: "fresh",
    contextRetention: "clean",
    skill: "resolving-merge-conflicts",
    promptFile: MERGER_CONFLICT_PROMPT,
    maxIter: 1,
    model,
    soul: "merger",
    toolchain: [],
  };
}

export class RealFamilyBackend implements FamilyBackend {
  private verificationStampTail: Promise<void> = Promise.resolve();
  protected readonly opts: RealFamilyBackendOptions;

  constructor(opts: RealFamilyBackendOptions) {
    this.opts = opts;
    this.validateFamilyPromptsDir();
    this.validateSoulsDir();
  }

  /**
   * #786: install this family backend's fingerprints immediately before an absent
   * environment stamp is written. Deliberately not called from the constructor:
   * image inspection and directory hashing must never block backend creation.
   */
  async installTelemetryRunEnvironment(): Promise<void> {
    await configureTelemetryFromWorkerImage({
      imageName: this.opts.imageName,
      codexFast: this.opts.codexFast,
      soulsDir: this.opts.soulsDir,
      promptsDir: this.opts.promptsDir,
    });
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
   * (missing e.g. reviewer.md / verify.md) would sail to runtime.
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
    const homeEnv = this.resolveHomeEnvFile();
    // Fail-closed: path must be a regular file (directory would dual-mount as dir).
    if (!existsSync(homeEnv) || !statSync(homeEnv).isFile()) {
      throw new Error(
        `RealFamilyBackend: home env file missing at "${homeEnv}" ` +
          `(#911 dual-mount needs image/home/CLAUDE.md next to souls, or opts.homeEnvFile).`,
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
  protected sh(
    file: string,
    args: string[],
    cwd?: string,
    timeoutMs?: number,
  ): string {
    // Mixed read/write seam (merge/push/pr create + rev-parse). Default
    // no-retry so a timed-out mutation is never auto-replayed (#884 cmr r7).
    return shWithClock(file, args, {
      stage: `subprocess:${file}`,
      cwd: cwd ?? this.opts.workingRepo,
      timeoutMs,
    });
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
  /** #934 ID-004 / #937: SO maxRetries from provider resumability. */

  protected agentForSpec(spec: WorkerSpec, ctx?: Pick<DispatchContext, "billingPool">): sc.AgentProvider {
    // Effort comes from the registry row for `spec.model` only (#916: no
    // role/soul hard override of reasoning effort at dispatch).
    return agentForSlug(
      spec.model,
      isBillingPoolDispatchId(ctx?.billingPool) ? ctx.billingPool : undefined,
      spec.soul,
    );
  }

  /**
   * #955 r7 — receipt maxRetries uses the same (slug, pool) binding as
   * {@link agentForSpec}. Pool rewrite can move a resume-capable slug onto an
   * incapable provider; slug-only capability would attach a false maxRetries.
   */
  protected resumeCapableForSpec(
    spec: Pick<WorkerSpec, "model">,
    ctx?: Pick<DispatchContext, "billingPool">,
  ): boolean {
    return resumeCapableForSlug(
      spec.model,
      isBillingPoolDispatchId(ctx?.billingPool) ? ctx.billingPool : undefined,
    );
  }

  /**
   * #966 / #979 — resolve a Sandcastle resumeSession id for family workers.
   * Capability gate + existsOnHost presence check; dead / incapable → undefined
   * (fresh open). Shared by family CMR judge and family coder-fix — one bus.
   */
  protected async resolveSandcastleResumeSessionId(
    spec: WorkerSpec,
    ctx: DispatchContext,
    agent: sc.AgentProvider,
  ): Promise<string | undefined> {
    const resumeCapable = this.resumeCapableForSpec(spec, ctx);
    let resumeSessionId: string | undefined =
      typeof ctx.resumeSessionId === "string" && resumeCapable
        ? ctx.resumeSessionId
        : undefined;
    if (
      resumeSessionId !== undefined &&
      agent.sessionStorage?.existsOnHost !== undefined
    ) {
      const present = await agent.sessionStorage.existsOnHost(
        this.opts.workingRepo,
        resumeSessionId,
      );
      if (!present) {
        resumeSessionId = undefined;
      }
    }
    return resumeSessionId;
  }

  /** Typed provider gate shared by every family `sc.run` dispatch. */
  protected unavailableWorkerProviderAuth(
    spec: Pick<WorkerSpec, "model">,
    auth: Pick<
      CmrAuth | ShipAuth,
      "claudeToken" | "grokAuthDir" | "agyDir" | "providerAuth"
    >,
    ctx?: Pick<DispatchContext, "billingPool">,
  ): "claude" | "grok" | "agy" | undefined {
    const pool = isBillingPoolDispatchId(ctx?.billingPool) ? ctx.billingPool : undefined;
    return unavailableProviderAuth(
      resolveModelSlugForPool(spec.model, pool).provider,
      auth.providerAuth ?? providerAuthFromCore(auth),
    );
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
    // #934 S-3: per-line shape gate (not bare JSON.parse cast).
    return parseFamilyLedgerJsonl(raw);
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
    // #934: per-line shape gate (not bare JSON.parse cast). Invalid JSON or
    // off-shape object fails closed — never silent-as-typed cargo.
    return parseLegacyEscalationJsonl(raw);
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

  resolveFamilyWorkingRepo(): string {
    return this.opts.workingRepo;
  }

  /**
   * Terminal-success GC (#603 / ADR 0024): remove the dedicated family clone.
   * Caller must have verified ledger terminal+ok post_merge_cleanup first.
   */
  async reapFamilyHost(familyBase: string): Promise<void> {
    if (familyBase !== this.opts.familyBase) return;
    try {
      rmSync(this.opts.workingRepo, { recursive: true, force: true });
    } catch {
      // Best-effort: an already-reclaimed clone is success.
    }
  }

  // ─────────────────────────── merge ───────────────────────────

  /**
   * #1103 H2 / #1105 R4: `git checkout` on a shared clone mutates HEAD / index
   * under the common `.git`. When already inside {@link runExclusive}, the file
   * lock is held — do not nest {@link runExclusiveSync} (fail-fast on in-process
   * overlap). Otherwise take the sync lock (cross-process wait still allowed).
   */
  private checkoutSharedRepo(branch: string, repo: string = this.opts.workingRepo): void {
    if (isGitMutexHeldInProcess(repo)) {
      this.sh("git", ["checkout", branch], repo);
      return;
    }
    runExclusiveSync(repo, () => {
      this.sh("git", ["checkout", branch], repo);
    });
  }

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
    this.checkoutSharedRepo(this.opts.familyBase, repo);
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
    // #598 / 2026-07-08: a merger agent that CRASHES (throws) is retried fresh up to
    // the bound on the CURRENT worktree as-is. A returned structured outcome is
    // telemetry; git post-state below is the only resolve decision. A persistent
    // plain crash re-throws.
    // #964: merger seat court at sc.run inside {@link runMergerAgent}
    // (structured non-resolve + reason). Generic workers share the same
    // AgentError recognition via {@link workerResultFromAgentError} on the
    // free-function dispatch / process-root seams. No outer dual conversion
    // here — AgentError never escapes this seat, so throw→retryProcessCrash
    // is skipped for the whole AgentError class (not only auth).
    const outcome = await retryProcessCrash(async () => {
      // If a PRIOR crashed attempt already COMMITTED the merge, the child is LANDED
      // (git truth). Do NOT re-run the merger on a no-conflict state — recognize the
      // landed merge instead (the post-state check below then returns it clean).
      if (this.childLandedOnFamilyBase(familyHeadBefore, childHead, repo)) {
        return { resolved: true };
      }
      return await this.runMergerAgent(req);
    });
    if (outcome.escalation !== undefined) {
      return {
        familyHead: this.sh("git", ["rev-parse", this.opts.familyBase], repo),
        familyHeadBefore,
        childHead,
        escalation: outcome.escalation,
      };
    }
    // The worker has exited — VERIFY git truth before returning clean (the prompt's
    // "resolve → add → commit, never --abort" is a soft LLM instruction, not a
    // postcondition). Failure modes a clean return
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
    // never looks clean"). Non-empty merger reason threads onto MergeResult for
    // family-runner diagnostics (#964 S3; not a public cause token).
    const familyHead = this.sh("git", ["rev-parse", this.opts.familyBase], repo);
    const childLanded = this.childLandedOnFamilyBase(familyHeadBefore, childHead, repo);
    if (childLanded) {
      return { familyHead, familyHeadBefore, childHead };
    }
    const reason =
      typeof outcome.reason === "string" && outcome.reason.trim().length > 0
        ? outcome.reason.trim()
        : undefined;
    return {
      familyHead,
      familyHeadBefore,
      childHead,
      conflicted: true,
      ...(reason !== undefined ? { reason } : {}),
    };
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
      this.isAncestorOf(childHead, familyHead, repo) &&
      this.isMergeCommit(familyHead, repo) &&
      !this.hasUnmergedEntries(repo) &&
      !this.hasConflictMarkers(familyHeadBefore, familyHead, repo)
    );
  }

  /** A resolved conflict must be represented by a real two-parent merge commit. */
  protected isMergeCommit(commit: string, repo: string): boolean {
    try {
      const parents = this.sh("git", ["show", "-s", "--format=%P", commit], repo)
        .trim()
        .split(/\s+/)
        .filter(Boolean);
      return parents.length === 2;
    } catch {
      return false;
    }
  }

  /** A landed merge must not leave index entries for unresolved paths. */
  protected hasUnmergedEntries(repo: string): boolean {
    return this.sh("git", ["ls-files", "-u"], repo).trim().length > 0;
  }

  /** A merger commit containing conflict markers is not a clean resolution. */
  protected hasConflictMarkers(before: string, after: string, repo: string): boolean {
    try {
      const changed = this.sh(
        "git",
        ["diff", "--diff-filter=AM", "--name-only", "-z", before, after],
        repo,
      );
      const paths = changed.split("\0").filter(Boolean);
      if (paths.length === 0) return false;
      const matches = this.sh(
        "git",
        ["grep", "-n", "-E", "^(<<<<<<<|=======|>>>>>>>)( |$)", after, "--", ...paths],
        repo,
      );
      return matches.trim().length > 0;
    } catch (err) {
      if (gitExitStatus(err) === 1) return false;
      throw err;
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
  ): Promise<{ resolved: boolean; reason?: string; escalation?: FamilyEscalation }> {
    // FAIL-CLOSED on the WORKER's OWN auth (integ-cmr int-r2 A-1, mirroring the
    // cmr/ship worker preflight): when the merger slot resolves to a Claude-family
    // model, the Claude OAuth token is THIS worker's auth, not a degradable leg.
    // Absent, the worker cannot start and never reaches clean exit + sidecar; that
    // failure would throw out of `sc.run` (NOT a structured non-resolve), and the
    // thrown startup error would surface as an opaque wave abort instead of the
    // merger's honest "did not resolve" → escalate path
    // (`resolveMergeConflict` turns a non-resolve into a loud, locatable throw; the
    // ledger never records a phantom `merged`). So return a STRUCTURED unresolved
    // BEFORE spinning the container when the token is absent. Mount once and reuse for
    // the sandbox (no double-mount).
    const auth = this.mountMergerAuth();
    try {
      const model = mergerModel(req.modelRoute);
      if (modelFamilyForSlug(model) === "claude" && auth.claudeToken === undefined) {
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
      // N3: agy-selected merger without OAuth is fail-closed (structured non-resolve).
      if (modelFamilyForSlug(model) === "agy" && auth.agyDir === undefined) {
        return {
          resolved: false,
          reason:
            "merger worker cannot start without agy OAuth token — the merger slot is " +
            "agy-family; host agy OAuth token must be provisioned into the " +
            "sandbox (provisionAgyAuthDir reads the live antigravity-cli token). " +
            "Without it the worker fails to start " +
            "and never resolves; returning a structured non-resolve here keeps " +
            "resolveMergeConflict's loud-throw semantics.",
        };
      }
      // C5: merger=grok without SuperGrok creds is fail-closed (same N3 shape).
      if (
        modelFamilyForSlug(model) === "other" &&
        model.startsWith("grok") &&
        auth.grokAuthDir === undefined
      ) {
        return {
          resolved: false,
          reason:
            "merger worker cannot start without SuperGrok auth — the merger slot is " +
            "grok-family; host grok credentials must be provisioned into the " +
            "sandbox (mountMergerAuth grokAuthDir). Without it the worker fails to " +
            "start and never resolves; returning a structured non-resolve here keeps " +
            "resolveMergeConflict's loud-throw semantics.",
        };
      }
      const outcomeLanding = this.prepareMergerOutcomeLanding();
      try {
        const telemetrySpec = mergerWorkerSpec(model);
        const telemetryCtx: DispatchContext = {
          familyBase: this.opts.familyBase,
          familyIssue: req.childIssue,
          stateDir: this.opts.ledgerDir,
          ...(req.runId !== undefined ? { runId: req.runId } : {}),
          ...(req.modelRoute !== undefined ? { modelRoute: req.modelRoute } : {}),
        };
        const telemetry = createTelemetryLegStamper({
          ledgerDir: this.opts.ledgerDir,
          spec: telemetrySpec,
          ctx: telemetryCtx,
        });
        const telemetryEnvironmentStamp = scheduleTelemetryEnvironmentStamp(
          this.opts.ledgerDir,
          telemetryCtx,
          this,
        );
        telemetry.stampDispatch(new Date().toISOString());
        try {
          const result = await this.runAgentSandbox({
            name: `merger-resolve-${req.childIssue}`,
            idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
            cwd: this.opts.workingRepo,
            sandbox: this.mergerSandbox(auth, outcomeLanding, telemetrySpec),
            agent: agentForSlug(
              telemetrySpec.model,
              undefined,
              telemetrySpec.soul,
            ),
            maxIterations: 1,
            branchStrategy: { type: "head" }, // commit the resolved merge in place
            promptFile: join(this.opts.promptsDir, MERGER_CONFLICT_PROMPT),
            // #919 CR T2 / ADR 0132: thin merger station receipt (completed|escalate).
            // Resolve cargo stays opaque sidecar outside SO.
            output: mergerReceiptOutput(
              mergerStationReceiptSchema(),
              MERGER_RECEIPT_TAG,
              resumeCapableForSlug(model),
            ),
          });
          // Output.object was attached: absent typed signal → #598, not cargo.
          const typed = requireTypedTrafficSignal(
            (result as { readonly output?: unknown }).output,
            "merger",
          );
          const outcome = mergerOutcomeFromResult({
            ...result,
            outcomePath: outcomeLanding.path,
            output: typed,
          });
          telemetry.stampCollect({
            kind: "result",
            result: outcome.resolved
              ? { kind: "completed", output: { kind: "merge", familyHead: this.opts.familyBase } }
              : { kind: "failed", reason: outcome.reason ?? "merger agent did not resolve" },
          });
          return outcome;
        } catch (error) {
          telemetry.stampCollect({ kind: "thrown", error });
          await telemetryEnvironmentStamp;
          // #964: single court at sc.run — ANY Sandcastle AgentError (native
          // headless auth death, non-zero agent exit, FiberFailure wrap, …) →
          // structured non-resolve for the owning Merge Action. Intentionally
          // skips throw→retryProcessCrash for the whole AgentError class: same
          // dead credentials / agent failure will not recover on re-dispatch.
          // Do not rethrow FiberFailure/AgentError (launcher terminal lost on
          // flight3). Plain infrastructure crashes still throw for #598.
          if (isSandcastleAgentError(error)) {
            return {
              resolved: false,
              reason:
                `merger agent invocation failed: ${formatSandcastleAgentError(error)}`,
            };
          }
          throw error;
        }
      } finally {
        this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir, auth.agyDir, auth.grokAuthDir]);
    }
  }

  /** The merger agent's sandbox (live soul + image-provided skills + optional auth). */
  protected prepareMergerOutcomeLanding(): { path: string; sandboxPath: string } {
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    const dir = mkdtempSync(join(this.opts.ledgerDir, "worker-outcome-merger-"));
    const path = join(dir, "outcome.json");
    writeFileSync(path, "", "utf8");
    ensureGitInfoExclude(this.opts.workingRepo, WORKER_OUTCOME_REPO_FILE);
    return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
  }

  protected mergerSandbox(
    auth: MergerAuth = this.mountMergerAuth(),
    outcomeLanding?: { path: string; sandboxPath: string },
    spec: Pick<WorkerSpec, "model" | "soul"> = mergerWorkerSpec(mergerModel()),
  ): sc.SandboxProvider {
    return docker(this.mergerSandboxConfig(auth, outcomeLanding, spec));
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
    // #913: single shared provision seam (merger / cmr / ship).
    return provisionFamilyWorkerAuth({
      home: this.opts.home ?? homedir(),
      rolePrefix: "merger",
      homeEnvFile: this.resolveHomeEnvFile(),
      codexFast: this.opts.codexFast,
    });
  }

  /**
   * The docker options the merger sandbox runs under. Pure (no container, no I/O)
   * so tests can assert its live soul mount without spinning a real sandbox.
   *
   * #334 (ADR 0026 / cross-slice note): the runtime host skills bind-mount onto
   * {@link SANDBOX_SKILLS_DIR} is DROPPED here too — the 2b image BAKES
   * `resolving-merge-conflicts` (+ its closure), so a runtime mount would SHADOW
   * the image-provided skill. The merger finds the skill in the image, not a host mount.
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
    spec: Pick<WorkerSpec, "model" | "soul"> = mergerWorkerSpec(mergerModel()),
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    const model = spec.model;
    const env: Record<string, string> = { ...SPAWNED_WORKER_ENV };
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    if (outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = outcomeLanding.sandboxPath;
    }
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [];
    if (
      auth.codexAuthDir !== undefined &&
      modelFamilyForSlug(model) === "codex"
    ) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    // C5: SuperGrok auth mount when merger slot is grok-family.
    if (auth.grokAuthDir !== undefined) {
      mounts.push({ hostPath: auth.grokAuthDir, sandboxPath: SANDBOX_GROK_DIR });
    }
    // N3: mount agy OAuth when provisioned (writable antigravity config dir).
    appendAgyAuthMount(mounts, auth.agyDir);
    appendAgySoulMount(
      mounts,
      spec,
      undefined,
      this.opts.soulsDir,
    );
    if (outcomeLanding !== undefined) {
      mounts.push({
        hostPath: outcomeLanding.path,
        sandboxPath: outcomeLanding.sandboxPath,
      });
    }
    // #372: souls mount live for merger worker (data files not baked).
    // Use shared helper (forces readonly:true, single hard-coded sandbox path).
    // #911: live-mount container home CLAUDE.md.
    mounts.push(soulsMount(this.opts.soulsDir));
    appendHomeEnvMount(mounts, this.resolveHomeEnvFile());
    return {
      imageName: this.opts.imageName,
      env,
      // #334: no skills mount — the baked image provides the merger skill.
      mounts,
    };
  }

  /** #911: container home CLAUDE.md (default sibling of soulsDir). */
  protected resolveHomeEnvFile(): string {
    return this.opts.homeEnvFile ?? homeEnvFileFromSoulsDir(this.opts.soulsDir);
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
    this.checkoutSharedRepo(request.familyBase, repo);
    try {
      await this.runVerifyCommands(request);
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
  protected async runVerifyCommands(_request: FamilyVerifyRequest): Promise<void> {
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
    // #934 ID-011: scripts first (op-error throws); empty verifiable set skips.
    const scripts = this.packageScripts(cwd);
    if (
      !scripts.includes("typecheck") &&
      !scripts.includes("build") &&
      !scripts.includes("test")
    ) {
      return;
    }
    // #3/#372: always install before scripts (freshness by construction).
    await this.installDeps(cwd);
    // #5: project's own scripts (not hardcoded npx). typecheck > build > none.
    if (scripts.includes("typecheck")) {
      this.runObservedVerification(
        _request,
        "typecheck",
        ["run", "typecheck"],
        cwd,
      );
    } else if (scripts.includes("build")) {
      this.runObservedVerification(_request, "typecheck", ["run", "build"], cwd);
    }
    if (scripts.includes("test")) {
      this.runObservedVerification(
        _request,
        _request.phase === "wave" ? "unit" : "full",
        ["test"],
        cwd,
      );
    }
  }

  /**
   * Narrow verification-result seam: observe the harness exit and monotonic
   * duration, then append a raw sidecar row. Counts come only from an explicitly
   * side channel. The project's declared command is never rewritten just to get
   * telemetry, so this path currently records an explicitly unknown count. The
   * write is telemetry-only and cannot affect a verify result.
   */
  protected runObservedVerification(
    request: FamilyVerifyRequest,
    verification: "typecheck" | "unit" | "full",
    args: string[],
    cwd: string,
  ): string {
    const startedAt = process.hrtime.bigint();
    let passed = false;
    try {
      const output = this.sh(
        "npm",
        args,
        cwd,
        PROVISION_SUBPROCESS_TIMEOUT_MS,
      );
      passed = true;
      return output;
    } finally {
      const durationMs = Number(process.hrtime.bigint() - startedAt) / 1_000_000;
      // Intentionally detached: a slow/full telemetry filesystem must not delay
      // or change the project's verify verdict.
      const stampInput = {
        ...(request.runId !== undefined ? { runId: request.runId } : {}),
        ...(request.issue !== undefined ? { issue: request.issue } : {}),
        verification,
        passed,
        // No structured side channel is available without changing the declared
        // project command. `null` is an honest unknown, never a prose-derived 0.
        count: null,
        durationMs,
      };
      // Keep JSONL order deterministic without awaiting the side effect on the
      // verify path. recordVerificationStamp catches its own I/O failures, but
      // an unexpected throw must not poison the tail and block later stamps.
      this.verificationStampTail = this.verificationStampTail
        .then(async () => {
          await recordVerificationStamp(this.opts.ledgerDir, stampInput);
        })
        .catch((error: unknown) => {
          console.warn("verification telemetry stamp failed; continuing", error);
        });
    }
  }

  /** Test/offline consumer seam for detached verification telemetry writes. */
  protected async waitForVerificationStamps(): Promise<void> {
    await this.verificationStampTail;
  }

  /**
   * True iff package.json is a file (R1 T2 verify-skip guard). ENOENT→false;
   * other probe errors throw (#934 ID-011 / #939) — never soft-skip as non-Node.
   * `protected` so a unit test drives the skip branch without a real FS.
   */
  protected isNodeProject(cwd: string): boolean {
    const path = join(cwd, "package.json");
    try {
      return statSync(path).isFile();
    } catch (err) {
      if (isFileNotFound(err)) return false;
      const d = err instanceof Error ? err.message : String(err);
      // #934 CR: one canonical reason token (no dual-era parenthetical).
      throw new Error(
        `family verify: package.json probe failed at "${path}": ${d}`,
      );
    }
  }

  /**
   * Script names from package.json. Read/parse/shape op-errors throw (#934 ID-011).
   * Only a successful valid object may return [] (legal empty skip).
   */
  protected packageScripts(cwd: string): readonly string[] {
    const path = join(cwd, "package.json");
    const detail = (err: unknown) => (err instanceof Error ? err.message : String(err));
    let raw: string;
    try {
      raw = readFileSync(path, "utf8");
    } catch (err) {
      throw new Error(`family verify: failed to read package.json at "${path}": ${detail(err)}`);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      throw new Error(`family verify: failed to parse package.json at "${path}": ${detail(err)}`);
    }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`family verify: package.json at "${path}" must be a JSON object`);
    }
    const scripts = (parsed as { scripts?: unknown }).scripts;
    if (scripts === undefined) return [];
    if (scripts === null || typeof scripts !== "object" || Array.isArray(scripts)) {
      throw new Error(`family verify: package.json "scripts" at "${path}" must be an object`);
    }
    return Object.keys(scripts as Record<string, unknown>);
  }

  /**
   * Install the Node project's deps in `cwd` before verify (#3 + #746).
   *
   * Prefer APFS clonefile of a lockfile-matching template `node_modules` from
   * {@link RealFamilyBackendOptions.depsTemplateRoot} (source monorepo) over a
   * full `npm ci`. Lockfile hash mismatch / missing template / clonefile failure
   * → real `npm ci` (or `npm install` without a lock). Still unconditional in the
   * #372 sense: we always re-ensure deps; the fast path is clonefile, not a
   * presence/mtime skip. `protected` for test seam (used by verify tests).
   */
  protected async installDeps(cwd: string): Promise<void> {
    const templateProjectDir = resolveTemplateProjectDir(cwd, {
      templateRoot: this.opts.depsTemplateRoot,
      targetRoot: this.opts.workingRepo,
    });
    await provisionNodeModules(cwd, {
      templateProjectDir,
      sh: (file, args, c) => this.provisionCommand(file, args, c),
    });
  }

  /** Provision-only async shell seam; ordinary git/gh commands remain synchronous. */
  protected provisionCommand(
    file: string,
    args: string[],
    cwd?: string,
  ): string | Promise<string> {
    // Test doubles override the synchronous general shell seam; preserve that
    // seam for observability while the production implementation uses async I/O.
    if (this.sh !== RealFamilyBackend.prototype.sh) {
      return this.sh(file, args, cwd);
    }
    return runProvisionCommand(file, args, cwd);
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
   *     (`dispatchShipWorker`).
   * Every OTHER family worker kind (merge — B 段) still forwards to the legacy
   * wrapper until its own slice wires it.
   *
   * The cmr worker (`cmrWorkerSpec`) = the 2b container's TOP-LEVEL route-selected
   * reviewer for ONE ADR 0030 pass (completeness or correctness). It
   * `Skill`-invokes ak-cross-m-review in-container and returns a TERMINAL review
   * verdict. The runner (`verifyCmr.ts`) owns pass order, ADR0032 strong-leg /
   * required-leg floor, three-channel routing (exit / judge status / decision
   * gate), coder-fix dispatch, and fresh re-review before ship. #875 demolished
   * the accounting court (leg-accounting death / claimed-fixed coverage /
   * disposition-enum kill). A non-converged review outcome is a completed CMR
   * payload the runner routes; it is NOT a failed worker.
   */
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    if (spec.kind === "ship") {
      // #336: the family ship step (止于 PR) is a container ship worker invoking
      // `gstack-ship`.
      return this.dispatchShipWorker(spec, ctx);
    }
    if (spec.kind === "coder") {
      return this.runFamilyCoderFixWorker(spec, ctx, landing);
    }
    // #1094: family CMR panel legs are first-class reviewer workers (not nested
    // CLIs inside the judge sandbox).
    if (spec.kind === "reviewer") {
      return this.runCmrPanelLegWorker(spec, ctx, landing);
    }
    // #735: real 文档发布 worker shares the family review-loop agent path
    // (invoke /gstack-document-release). Offline/test stubs stay on backends
    // that short-circuit dispatchWorker or on the legacy offline hatch.
    if (spec.kind === "verify" || spec.kind === "fixer" || spec.kind === "landing") {
      return this.runFamilyReviewLoopWorker(spec, ctx, landing);
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
    // #919 R2: pass refuseRecords / priorJudgeVerdicts landing into CMR court
    // (same fix-findings landing shape as single-slice S6 reverify).
    const outcome = await this.runCmrWorker(spec, ctx, landing);
    return this.cmrOutcomeToWorkerResult(outcome, ctx);
  }

  async runPostMergeCleanup(
    landing: WorkerLandingPayload,
    ctx: DispatchContext,
  ): Promise<CleanupResult> {
    const ghSh: Sh = (file, args) =>
      shWithClock(file, args, { stage: `cleanup:${file}` });
    return dispatchPostMergeCleanup(landing, ctx, ghSh);
  }

  /**
   * #684: production monitored-CLI spawn for family productive workers.
   * Same bridge pattern as {@link RealBackend.resolveCliMonitorDispatch}.
   */
  resolveCliMonitorDispatch(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): CliMonitorSpawnSpec | undefined {
    // Container-free test/integration subclasses intentionally replace the
    // family review worker seam; preserve that seam instead of launching the
    // host bridge and bypassing the override.
    if (
      this.runFamilyReviewLoopWorker !==
      RealFamilyBackend.prototype.runFamilyReviewLoopWorker
    ) {
      return undefined;
    }
    return buildCliMonitorSpawnSpec({
      backendKind: "realFamily",
      backendOpts: this.opts,
      spec,
      ctx: {
        ...ctx,
        stateDir: ctx.stateDir ?? this.opts.ledgerDir,
      },
      landing,
    });
  }

  resolveTelemetryDir(_ctx: DispatchContext): string {
    return this.opts.ledgerDir;
  }

  /**
   * #684: map a finished monitored family CLI bridge child into a WorkerResult.
   */
  async awaitMonitoredCliWorker(
    handle: WorkerMonitorHandle,
    exitCode: number | null,
    _spec: WorkerSpec,
    _ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    return workerResultFromMonitorSidecar(handle, exitCode);
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
        escalation: outcome.escalation ?? {
          reason: outcome.reason,
          diagnosis: outcome.diagnosis,
        },
        ...(outcome.sessionId !== undefined ? { sessionId: outcome.sessionId } : {}),
      };
    }
    // #930 / #919 E / CR S1: live typed path is kind:"judge" only. Residual
    // open-count / kind:verdict never mints continue — one shared unusable
    // paper ({@link unusableResidualOpenCountPaper}, same as single-slice).
    // Court fail-louds non-judge; never open-count second closer / dual shapes.
    void ctx;
    if (outcome.kind === "judge") {
      const verdict: JudgeVerdict =
        outcome.status === "converged"
          ? { station: "judge", status: "converged" }
          : outcome.status === "escalate"
            ? {
                station: "judge",
                status: "escalate",
                reason: outcome.reason ?? "family judge escalate",
                diagnosis: outcome.diagnosis ?? "judge declared escalate",
              }
            : outcome.status === "toolchain"
              ? {
                  // #1027 S1 / ADR 0145: toolchain terminal (→ verify_failed).
                  station: "judge",
                  status: "toolchain",
                  reason: outcome.reason ?? "family judge toolchain",
                  diagnosis:
                    outcome.diagnosis ??
                    "judge declared toolchain/environment red",
                }
            : (() => {
                // ADR 0138 / #978 CR S2: never invent an empty packet body when
                // missing — fail at projection (schema already requires body on
                // live continue; empty invent only hides contract drift).
                if (typeof outcome.fixPacketBody !== "string") {
                  throw new Error(
                    "family judge continue missing fixPacketBody " +
                      "(ADR 0138; refuse invent empty string at projection)",
                  );
                }
                return {
                  station: "judge" as const,
                  status: "continue" as const,
                  findingDispositions: outcome.findingDispositions ?? [],
                  fixPacketBody: outcome.fixPacketBody,
                  ...(outcome.advanceCoder !== undefined
                    ? { advanceCoder: outcome.advanceCoder }
                    : {}),
                };
              })();
      const judge = judgeResultFromVerdict(verdict, outcome.findings);
      return {
        kind: "completed",
        output: withFamilyJudgeCargo(judge, outcome),
        ...(outcome.sessionId !== undefined
          ? { sessionId: outcome.sessionId }
          : {}),
      };
    }
    // Residual (incl. positive findingsCount / kind:verdict cargo): one unusable
    // paper only — {@link unusableResidualOpenCountPaper} (kind:"reviewer").
    return {
      kind: "completed",
      output: unusableResidualOpenCountPaper(),
      ...(outcome.sessionId !== undefined
        ? { sessionId: outcome.sessionId }
        : {}),
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
   * #1094 — once-per-round repo prep BEFORE panel-leg fan-out.
   * Checkout familyBase + write focus + shared-repo outcome exclude on
   * workingRepo exactly once; legs then only clone (never concurrent checkout /
   * exclude rewrite on the shared repo). Missing cut-SHA returns structured
   * escalate (same reason/diagnosis as runCmrWorker) — never a bare throw.
   */
  prepareFamilyCmrPanelRound(ctx: DispatchContext):
    | { readonly headSha: string }
    | {
        readonly kind: "escalate";
        readonly reason: string;
        readonly diagnosis: string;
        readonly escalation: ReturnType<typeof runnerSynthesizedFailureEscalation>;
      } {
    if (ctx.familyBase === undefined) {
      throw new Error(
        "prepareFamilyCmrPanelRound: requires ctx.familyBase",
      );
    }
    // Shared-repo exclude once before fan-out (#1094 R2 F4) — legs must not
    // concurrently rewrite `.git/info/exclude`.
    ensureGitInfoExclude(this.opts.workingRepo, WORKER_OUTCOME_REPO_FILE);
    if (
      this.opts.familyBaseStartHead === undefined &&
      ctx.waveVerifyFailure === undefined
    ) {
      const reason =
        "no familyBaseStartHead (cut SHA) recorded — cannot pin the cmr review scope";
      const diagnosis =
        "the integrated cmr focus file must pin the EXACT git diff <cut SHA>...<familyBase> " +
        "scope (integrated CMR pass prompts); refusing to fall back to a possibly-stale " +
        "main...HEAD scope (a fail-open that would review the wrong diff). Provide " +
        "RealFamilyBackendOptions.familyBaseStartHead.";
      return {
        kind: "escalate",
        reason,
        diagnosis,
        escalation: runnerSynthesizedFailureEscalation({ reason, diagnosis }),
      };
    }
    this.checkoutSharedRepo(ctx.familyBase);
    if (ctx.waveVerifyFailure === undefined) {
      this.writeCmrFocusFile(ctx);
    }
    const headSha = this.sh(
      "git",
      ["rev-parse", "HEAD"],
      this.opts.workingRepo,
    ).trim();
    return { headSha };
  }

  /**
   * #1094 — one runner-dispatched CMR panel-leg worker (fresh READ-ONLY reviewer).
   * Top-level sandcastle agent for the leg's model (credential injection = same
   * as single-slice fresh reviewer). Independent clone at PRE_HEAD; prose stdout
   * is the legal paper (ADR 0141).
   *
   * Does NOT checkout or rewrite focus on workingRepo — that is
   * {@link prepareFamilyCmrPanelRound}'s job (once before fan-out).
   * Does NOT provision an outcome sidecar — legs are prose-only (ADR 0141).
   */
  protected async runCmrPanelLegWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    _landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    if (ctx.familyBase === undefined) {
      throw new Error(
        "dispatchWorker(reviewer panel leg): requires ctx.familyBase",
      );
    }
    const auth = this.mountCmrAuth();
    let legClone: string | undefined;
    try {
      const missingProvider = this.unavailableWorkerProviderAuth(spec, auth, ctx);
      if (missingProvider !== undefined) {
        // #1094 F6: missing auth is terminal for this leg (escalate → no
        // mechanical 6× retry). Transport layer maps escalate → skipped evidence.
        const reason = `no ${missingProvider} auth — panel leg ${spec.model} cannot start`;
        return {
          kind: "escalated",
          escalation: runnerSynthesizedFailureEscalation({
            reason,
            diagnosis:
              "typed provider availability preflight rejected the panel leg before sc.run",
          }),
        };
      }
      if (
        modelFamilyForCmrReviewLeg(spec.model) === "claude" &&
        auth.claudeToken === undefined
      ) {
        return {
          kind: "escalated",
          escalation: runnerSynthesizedFailureEscalation({
            reason:
              "no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — panel leg cannot start",
            diagnosis:
              "panel leg Claude OAuth token missing; escalate (no mechanical retry)",
          }),
        };
      }
      // #1094 R4 F-A: setup infra (clone / soul / prompt / sandbox) throws degrade
      // THIS leg to {kind:"failed"} — same transport shape as R3 F4 focus-copy —
      // so allSettled siblings keep running and the pure court still opens.
      // Park/relay / OnlineReviewLoopTerminal escalate throws must rethrow so
      // fan-out can drain peers then surface the typed terminal (never collapse
      // into leg-kill failed, never whole-pass cmr_failed via bare Error).
      try {
        // Resolve familyBase SHA without checkout (prep already did that once).
        const headSha = this.sh(
          "git",
          ["rev-parse", ctx.familyBase],
          this.opts.workingRepo,
        ).trim();
        legClone = this.preparePanelLegClone(spec.model, headSha);
        // Focus file was written once on workingRepo; copy into the independent clone.
        // #1094 R3 F4: failed copy is a degraded transport (fail-loud), never a
        // present leg reviewing invent-your-own scope.
        const focusSrc = join(this.opts.workingRepo, CMR_FOCUS_FILENAME);
        try {
          copyFileSync(focusSrc, join(legClone, CMR_FOCUS_FILENAME));
        } catch (err) {
          const detail = err instanceof Error ? err.message : String(err);
          return {
            kind: "failed",
            reason:
              `panel leg ${spec.model}: failed to stage ${CMR_FOCUS_FILENAME} ` +
              `(pinned review scope) — ${detail}`,
          };
        }
        // #1094 R3 F5: lens authority is spec.promptFile only (cmrPanelLegWorkerSpec
        // pins it from the pass). Do not re-derive from ctx.cmrPass / default.
        const promptTemplate = readFileSync(
          join(this.opts.promptsDir, spec.promptFile),
          "utf8",
        );
        const passLabel =
          spec.promptFile === CMR_PANEL_LEG_COMPLETENESS_PROMPT_FILE
            ? "completeness"
            : spec.promptFile === CMR_PANEL_LEG_CORRECTNESS_PROMPT_FILE
              ? "correctness"
              : spec.promptFile;
        const taskBody =
          `${promptTemplate.trim()}\n\n` +
          `Panel leg slug: ${spec.model}.\n` +
          `CMR pass: ${passLabel}.\n` +
          `Review the family CMR focus in ${CMR_FOCUS_FILENAME} ` +
          `(or the assigned clone scope) and emit prose review on stdout.`;
        const promptPath = join(legClone, ".orchestrator-panel-leg-prompt.md");
        writeFileSync(promptPath, taskBody, "utf8");
        const result = await this.runAgentSandbox({
          name: `family-cmr-panel-${spec.model}`,
          idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
          cwd: legClone,
          sandbox: this.panelLegSandbox(auth, spec, ctx),
          agent: this.agentForSpec(spec, ctx),
          maxIterations: 1,
          branchStrategy: { type: "head" },
          promptFile: promptPath,
        });
        const stdout =
          typeof (result as { stdout?: unknown }).stdout === "string"
            ? (result as { stdout: string }).stdout
            : "";
        return panelLegCompletedResult(stdout);
      } catch (err) {
        if (err instanceof OnlineReviewLoopTerminal) throw err;
        if (isQuotaWaitForResetError(err)) throw err;
        const reason = err instanceof Error ? err.message : String(err);
        return { kind: "failed", reason: `panel leg ${spec.model}: ${reason}` };
      }
    } finally {
      this.cleanupTempAuthDirs([
        auth.codexAuthDir,
        auth.agyDir,
        auth.grokAuthDir,
      ]);
      if (legClone !== undefined) {
        rmSync(legClone, { recursive: true, force: true });
      }
    }
  }

  /**
   * Independent writable clone for one panel leg (#1094 / ak-cross-m-review
   * clone semantics): no linked worktree, no shared object store.
   */
  protected preparePanelLegClone(slug: string, headSha: string): string {
    const safe = slug.replace(/[^a-zA-Z0-9._-]+/g, "-");
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    const legRoot = mkdtempSync(
      join(this.opts.ledgerDir, `panel-leg-${safe}-`),
    );
    try {
      this.sh("git", [
        "clone",
        "--origin",
        "origin",
        "--no-local",
        "--no-checkout",
        this.opts.workingRepo,
        legRoot,
      ]);
      this.sh("git", ["checkout", "--detach", headSha], legRoot);
    } catch (err) {
      // #1094 R4 F-A: mkdtempSync already created legRoot — reclaim on
      // clone/checkout failure so ledgerDir does not leak half-built clones.
      rmSync(legRoot, { recursive: true, force: true });
      throw err;
    }
    try {
      this.sh("git", ["remote", "remove", "origin"], legRoot);
    } catch {
      // already remote-free
    }
    return legRoot;
  }

  protected panelLegSandbox(
    auth: CmrAuth,
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): sc.SandboxProvider {
    return docker(this.panelLegSandboxConfig(auth, spec, ctx));
  }

  protected panelLegSandboxConfig(
    auth: CmrAuth,
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{
      hostPath: string;
      sandboxPath: string;
      readonly?: boolean;
    }>;
  } {
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
      [SANDBOX_REPO_ENV]: this.opts.repo,
    };
    if (ctx.familyIssue !== undefined) {
      const issue = String(ctx.familyIssue);
      env[SANDBOX_ISSUE_NUMBER_ENV] = issue;
      env[SANDBOX_ISSUE_NUMBER_ALIAS_ENV] = issue;
    }
    if (auth.claudeToken !== undefined) {
      env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    }
    if (auth.ghToken !== undefined) env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    const mounts: {
      hostPath: string;
      sandboxPath: string;
      readonly?: boolean;
    }[] = [];
    // Mount credentials for the provider that will actually execute (#1094 R3 F1):
    // pool rewrite (ctx.billingPool) can change the CLI even when the registry
    // row stays e.g. gpt-5.6-sol / opus.
    const pool = isBillingPoolDispatchId(ctx.billingPool)
      ? ctx.billingPool
      : undefined;
    const provider = resolveModelSlugForPool(spec.model, pool).provider;
    if (provider === "codex" && auth.codexAuthDir !== undefined) {
      mounts.push({
        hostPath: auth.codexAuthDir,
        sandboxPath: SANDBOX_CODEX_DIR,
      });
    }
    if (provider === "agy" && auth.agyDir !== undefined) {
      appendAgyAuthMount(mounts, auth.agyDir);
      appendAgySoulMount(mounts, spec, pool, this.opts.soulsDir);
    }
    if (provider === "grok" && auth.grokAuthDir !== undefined) {
      mounts.push({
        hostPath: auth.grokAuthDir,
        sandboxPath: SANDBOX_GROK_DIR,
      });
    }
    mounts.push(soulsMount(this.opts.soulsDir));
    appendHomeEnvMount(mounts, this.resolveHomeEnvFile());
    return { imageName: this.opts.imageName, env, mounts };
  }

  protected async runCmrWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<CmrWorkerOutcome> {
    // #1094: pure-court judge — panel legs already ran via runner fan-out;
    // this worker reads landed prose and emits the typed verdict.
    // EXACT cut-SHA review-scope diff (prompt contract in the integrated CMR pass prompts — do
    // NOT guess main...HEAD). With no recorded cut SHA there is no honest scope to
    // hand the review, and a `main...familyBase` fallback would silently disable the
    // load-bearing scope — the same fail-open the reconcile `familyBaseStartHead()`
    // predicate refuses (this file ~877-895). So escalate (verifyCmr routes it as
    // not-passed续跑) rather than checking out the base + spinning the container only
    // to review the wrong scope.
    // ADR 0145: the family-verify triage judge presides over the phase-scoped
    // verify FAILURE, not a diff — there is no cut-SHA scope to pin.
    if (
      this.opts.familyBaseStartHead === undefined &&
      ctx.waveVerifyFailure === undefined
    ) {
      return {
        kind: "escalate",
        reason:
          "no familyBaseStartHead (cut SHA) recorded — cannot pin the cmr review scope",
        diagnosis:
          "the integrated cmr focus file must pin the EXACT git diff <cut SHA>...<familyBase> " +
          "scope (integrated CMR pass prompts); refusing to fall back to a possibly-stale " +
          "main...HEAD scope (a fail-open that would review the wrong diff). Provide " +
          "RealFamilyBackendOptions.familyBaseStartHead.",
        escalation: runnerSynthesizedFailureEscalation({
          reason:
            "no familyBaseStartHead (cut SHA) recorded — cannot pin the cmr review scope",
          diagnosis:
            "the integrated cmr focus file must pin the exact cut-SHA review scope before launch",
        }),
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
        escalation: runnerSynthesizedFailureEscalation({
          reason: "cmr worker spec missing frozen review legs",
          diagnosis:
            "cmrWorkerSpec must freeze the route-selected review legs before launch",
        }),
      };
    }
    const auth = this.mountCmrAuth();
    try {
      const missingProvider = this.unavailableWorkerProviderAuth(spec, auth, ctx);
      if (missingProvider !== undefined) {
        return {
          kind: "escalate",
          reason: `no ${missingProvider} auth — the selected cmr provider cannot start`,
          diagnosis: "typed provider availability preflight rejected the cmr launch before sc.run",
          escalation: runnerSynthesizedFailureEscalation({
            reason: `no ${missingProvider} auth — the selected cmr provider cannot start`,
            diagnosis:
              "typed provider availability preflight rejected the cmr launch before sc.run",
          }),
        };
      }
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
          escalation: runnerSynthesizedFailureEscalation({
            reason:
              "no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — the cmr worker cannot start",
            diagnosis:
              "the selected top-level Claude CMR worker cannot start without its OAuth token",
          }),
        };
      }
      // Check out the family base so the in-container ak-cross-m-review reviews the
      // RIGHT base diff (ctx.familyBase is the contract input — dispatchWorker
      // already asserted it is present). The cmr worker runs as the container's
      // route-selected top-level agent over THIS checked-out base.
      this.checkoutSharedRepo(ctx.familyBase!);
      // codex cmr R1 (F3+F2): thread the EXACT review scope + the LLM-resolved-child
      // FOCUS into the worker via a git-ignored focus file the prompt reads — the
      // skill can't reliably scope the family diff on its own (a stale local base
      // ref pollutes `main...HEAD`; non-`main` targets diff the wrong ref), and the
      // #291 缺口-1 focus signal must not be silently dropped. The focus file pins the
      // exact `git diff <familyBaseStartHead>...<familyBase>` scope command + the
      // baseline SHA + the machine-resolved children.
      // ADR 0145: the family-verify triage judge focuses on the phase-scoped
      // verify FAILURE, not a diff scope. Same judge decode + review-leg
      // machinery; only the focus content differs.
      if (ctx.waveVerifyFailure !== undefined) {
        this.writeWaveVerifyFocusFile(ctx);
      } else {
        this.writeCmrFocusFile(ctx);
      }
      this.writeCmrRouteFile(ctx, frozenReviewLegs);
      // #919 M3/M7 / #927 isomorphic: refuse keys sole on thin ctx; landing
      // carries refuseRecords cargo only (WorkerLandingPayload has no key field).
      // Trigger on ctx keys OR landing refuseRecords OR priorJudgeVerdicts.
      // #1094: also land when runner-dispatched panel-leg transports are present
      // so the pure judge court can read prose evidence.
      const needsFixFindingsLanding =
        (landing?.refuseRecords !== undefined &&
          landing.refuseRecords.length > 0) ||
        (landing?.panelLegTransports !== undefined &&
          landing.panelLegTransports.length > 0) ||
        (ctx.refusedFindingIdentityKeys !== undefined &&
          ctx.refusedFindingIdentityKeys.length > 0) ||
        (ctx.priorJudgeVerdicts !== undefined &&
          ctx.priorJudgeVerdicts.length > 0) ||
        (ctx.panelLegTransports !== undefined &&
          ctx.panelLegTransports.length > 0);
      const fixFindingsLanding = needsFixFindingsLanding
        ? this.writeFamilyFixFindingsFile(ctx, landing)
        : undefined;
      const outcomeLanding = this.prepareCmrOutcomeLanding(ctx);
      try {
        let result: Awaited<ReturnType<typeof sc.run>>;
        try {
          // #966: honor ledger-derived resumeSessionId on the live Sandcastle
          // path (single-slice already does via resumeSession / runAgentSandbox).
          // Capability gate matches runner #955: incapable provider → fresh open
          // with priorJudgeVerdicts still landed above (AC4 session-loss shape).
          // When the ledger id is present but the host session file is gone,
          // omit resumeSession (fresh open) — still keep priorJudgeVerdicts.
          const resumeCapable = this.resumeCapableForSpec(spec, ctx);
          const agent = this.agentForSpec(spec, ctx);
          const resumeSessionId = await this.resolveSandcastleResumeSessionId(
            spec,
            ctx,
            agent,
          );
          result = await this.runAgentSandbox({
            name: "family-cmr",
            idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
            cwd: this.opts.workingRepo,
            sandbox: this.cmrSandbox(
              auth,
              spec,
              outcomeLanding,
              ctx,
              fixFindingsLanding,
            ),
            // Derive the model from the spec via the shared validated seam (cmr S336 r7
            // symmetry): resolve the worker's slug through the shared family registry —
            // no constant that could silently drift
            // from the spec the runner declares.
            agent,
            // `maxIter` is the sandbox iteration budget for this single ADR 0030 cmr
            // pass worker. The pass verdict is consumed by verifyCmr, which owns pass
            // sequencing and accounting.
            maxIterations: spec.maxIter,
            // On the resident family base so the clean CMR reviewer audits the
            // current full family diff. Persistent repairs are made only by the
            // separate family coder-fix worker.
            branchStrategy: { type: "head" },
            ...(resumeSessionId !== undefined
              ? { resumeSession: resumeSessionId }
              : {}),
            promptFile: join(this.opts.promptsDir, spec.promptFile),
            // #930: same live judge seat as single-slice S3/S6 — T2 station
            // receipt on JUDGE_RECEIPT_TAG (not open-count `cmr` workerReceipt).
            // Sandcastle owns malformed-receipt recovery; sidecar stays cargo.
            output: workerReceiptOutput(
              JUDGE_RECEIPT_TAG,
              judgeStationReceiptSchema(),
              resumeCapable,
            ),
          });
        } catch (err) {
          // #899: typed traffic-signal exhaust exits non-zero for #598; do not
          // convert SOE into a sparse success verdict that feeds the fixer.
          logAndRethrowReceiptFailure(err, "family CMR");
        }
        // Output.object was attached: absent typed signal → #598, not cargo
        // no-gate completion (same class as realBackend.rawOutputFor).
        const typed = requireTypedTrafficSignal(
          (result as { readonly output?: unknown }).output,
          "family CMR",
        );
        // #1005 / ADR 0141 / #1094: host-observed panel-leg transports from
        // runner-dispatched first-class workers win over nested sandbox cargo.
        const hostTransports = normalizePanelLegTransports(
          ctx.panelLegTransports ?? landing?.panelLegTransports,
        );
        const legTransports =
          hostTransports ?? legTransportsFromCmrSandboxResult(result);
        return withCmrSession(
          cmrOutcomeFromResult({
            ...result,
            output: typed,
            cmrReviewLegs: frozenReviewLegs,
            outcomePath: outcomeLanding.path,
            ...(legTransports !== undefined ? { legTransports } : {}),
          }),
          lastSessionIdIfPresent(result),
        );
      } finally {
        if (fixFindingsLanding !== undefined) {
          rmSync(fixFindingsLanding.path, { force: true });
        }
        this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir, auth.agyDir, auth.grokAuthDir]);
    }
  }

  // ADR 0131 removed the same-worker outcome rewrite ladder.

  /**
   * Thin Sandcastle `sc.run` seam (parallel to {@link RealBackend.invokeSandcastleRun}).
   * Unit tests override THIS method to fake container results while still
   * exercising the shared #909 idle/quota wrap in {@link runAgentSandbox}.
   */
  protected async invokeSandcastleRun(
    options: Parameters<typeof sc.run>[0],
  ): Promise<Awaited<ReturnType<typeof sc.run>>> {
    // #899 / #928 / #919 F2: shared wrap — same helper as RealBackend.
    // #1092: onlineReview seats get one schema-rich SO resume before #598.
    return await runSandcastleWithOnlineReviewSoGuard(
      (opts) => sc.run(withSandcastleInvokeDefaults(opts)),
      options,
    );
  }

  /**
   * Production family agent-sandbox entry (#937 / #934 ID-007). Same as
   * single-slice {@link RealBackend.runAgentSandbox}: Sandcastle only — silence
   * must not trigger quota probe/park/kill/relay. Explicit typed 429/capacity
   * enter park/relay via live constructors elsewhere.
   */
  protected async runAgentSandbox(
    options: AgentSandboxRunOptions,
  ): Promise<Awaited<ReturnType<typeof sc.run>>> {
    return this.invokeSandcastleRun(options);
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
      const missingProvider = this.unavailableWorkerProviderAuth(spec, auth, ctx);
      if (missingProvider !== undefined) {
        return {
          kind: "escalated",
          escalation: runnerSynthesizedFailureEscalation({
            reason: `no ${missingProvider} auth — the family coder-fix provider cannot start`,
            diagnosis: "typed provider availability preflight rejected the coder-fix launch before sc.run",
          }),
        };
      }
      if (modelFamilyForSlug(spec.model) === "claude" && auth.claudeToken === undefined) {
        return {
          kind: "escalated",
          escalation: runnerSynthesizedFailureEscalation({
            reason:
              "no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — the family coder-fix worker cannot start",
            diagnosis:
              "the family coder-fix worker is a top-level Claude worker when the " +
              "active route selects a Claude-family coderFix model; provide " +
              "CLAUDE_CODE_OAUTH_TOKEN / ~/.sc-claude-token or select a non-Claude " +
              "coderFix route.",
          }),
        };
      }
      this.checkoutSharedRepo(ctx.familyBase);
      const fixFindingsLanding = this.writeFamilyFixFindingsFile(ctx, landing);
      try {
        const outcomeLanding = this.prepareFamilyCoderOutcomeLanding();
        try {
          // #919 R3: T2 coder station receipt (CODER_RECEIPT_TAG + schema) —
          // same as single-slice; ordinary committed cargo stays outside SO.
          // #979: honor ledger-derived resumeSessionId on the live Sandcastle
          // path (same bus as family CMR #966 / single-slice #924).
          const resumeCapable = this.resumeCapableForSpec(spec, ctx);
          const agent = this.agentForSpec(spec, ctx);
          const resumeSessionId = await this.resolveSandcastleResumeSessionId(
            spec,
            ctx,
            agent,
          );
          const result = await this.runAgentSandbox({
            name: "family-coder-fix",
            idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
            cwd: this.opts.workingRepo,
            sandbox: this.familyCoderSandbox(
              auth,
              spec.model,
              ctx,
              outcomeLanding,
              spec.soul,
            ),
            agent,
            maxIterations: spec.maxIter,
            branchStrategy: { type: "head" },
            ...(resumeSessionId !== undefined
              ? { resumeSession: resumeSessionId }
              : {}),
            promptFile: join(this.opts.promptsDir, spec.promptFile),
            // #919 post-R8 M1 / R3: T2 coderStationReceiptSchema — refuse
            // traffic survives the family decode path (not decision-gate dual).
            output: coderReceiptOutput(
              coderStationReceiptSchema(),
              CODER_RECEIPT_TAG,
              resumeCapable,
            ),
          });
          return this.familyCoderResultFromRun(result, spec, outcomeLanding.path);
        } finally {
          this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
        }
      } finally {
        rmSync(fixFindingsLanding.path, { force: true });
        rmSync(join(this.opts.workingRepo, RAW_REVIEWER_STDOUT_SANDBOX_FILE), {
          force: true,
        });
        rmSync(join(this.opts.workingRepo, RAW_REVIEWER_SIDECAR_SANDBOX_FILE), {
          force: true,
        });
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir, auth.grokAuthDir, auth.agyDir]);
    }
  }

  /** Write the runner-owned blocking CMR findings file into the checked-out family base. */
  protected writeFamilyFixFindingsFile(
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): { path: string; sandboxPath: string } {
    ensureGitInfoExclude(this.opts.workingRepo, FAMILY_FIX_FINDINGS_FILENAME);
    ensureGitInfoExclude(this.opts.workingRepo, RAW_REVIEWER_STDOUT_SANDBOX_FILE);
    ensureGitInfoExclude(this.opts.workingRepo, RAW_REVIEWER_SIDECAR_SANDBOX_FILE);
    const path = join(this.opts.workingRepo, FAMILY_FIX_FINDINGS_FILENAME);
    // Host monitor paths are not visible inside the family coder-fix container.
    // Materialise into the sandbox cwd (workingRepo) and rewrite pointers (#899).
    const rawReviewerArtifacts =
      landing?.rawReviewerArtifacts !== undefined
        ? materializeRawReviewerArtifactsForSandbox(
            landing.rawReviewerArtifacts,
            this.opts.workingRepo,
          )
        : undefined;
    const identityKeys = [...(ctx.blockingFindingIdentityKeys ?? [])];
    // Shared helper with single-slice landing writer — fail-loud when open set
    // lacks body (raw-artifacts-only path with empty keys still soft-omits).
    const fixPacketBody = materializeLandingFixPacketBody({
      fixPacketBody: landing?.fixPacketBody,
      blockingFindingIdentityKeys: identityKeys,
      blockingFindingCount: ctx.blockingFindingCount,
    });
    // #1012: same host-file guarantee as single-slice landing writer.
    ensureRegularFileForBindMount(path);
    writeFileSync(
      path,
      `${JSON.stringify(
        {
          // ADR 0138 / #978: sole coder-fix packet content — judge body
          // verbatim. Bare findings packing deleted (no second path).
          ...(fixPacketBody !== undefined ? { fixPacketBody } : {}),
          ...(rawReviewerArtifacts !== undefined
            ? { rawReviewerArtifacts }
            : {}),
          blockingFindingIdentityKeys: identityKeys,
          ...(ctx.preexistingAssertionTouched === true
            ? { preexistingAssertionTouched: true }
            : {}),
          ...(ctx.refusedFindingIdentityKeys !== undefined &&
          ctx.refusedFindingIdentityKeys.length > 0
            ? { refusedFindingIdentityKeys: ctx.refusedFindingIdentityKeys }
            : {}),
          // #919 R2 / #927: opaque refuse cargo for judge re-adjudicate —
          // landing only (信封宪法); never invented from thin ctx.
          ...(landing?.refuseRecords !== undefined &&
          landing.refuseRecords.length > 0
            ? { refuseRecords: landing.refuseRecords }
            : {}),
          ...(ctx.repairAttemptFailures !== undefined &&
          ctx.repairAttemptFailures.length > 0
            ? { repairAttemptFailures: ctx.repairAttemptFailures }
            : {}),
          ...(ctx.escalationAnswer !== undefined
            ? { escalationAnswer: ctx.escalationAnswer }
            : {}),
          // #925 F1 / #919: structured prior judge rows for session-loss reopen.
          ...(ctx.priorJudgeVerdicts !== undefined &&
          ctx.priorJudgeVerdicts.length > 0
            ? { priorJudgeVerdicts: ctx.priorJudgeVerdicts }
            : {}),
          // #1094: runner-dispatched panel-leg prose for the pure judge court.
          ...((landing?.panelLegTransports ?? ctx.panelLegTransports) !==
            undefined &&
          (landing?.panelLegTransports ?? ctx.panelLegTransports)!.length > 0
            ? {
                panelLegTransports:
                  landing?.panelLegTransports ?? ctx.panelLegTransports,
              }
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
      ensureGitInfoExclude(this.opts.workingRepo, WORKER_OUTCOME_REPO_FILE);
      success = true;
      return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
    } finally {
      if (!success) {
        rmSync(dir, { recursive: true, force: true });
      }
    }
  }

  protected prepareFamilyReviewOutcomeLanding(): { path: string; sandboxPath: string } {
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    const dir = mkdtempSync(join(this.opts.ledgerDir, "worker-outcome-family-review-"));
    let success = false;
    try {
      const path = join(dir, "outcome.json");
      writeFileSync(path, "", "utf8");
      ensureGitInfoExclude(this.opts.workingRepo, WORKER_OUTCOME_REPO_FILE);
      success = true;
      return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
    } finally {
      if (!success) rmSync(dir, { recursive: true, force: true });
    }
  }

  protected familyCoderSandbox(
    auth: ShipAuth,
    model: string,
    ctx: DispatchContext,
    outcomeLanding: { path: string; sandboxPath: string },
    soul: WorkerSpec["soul"] = "fixer",
  ): sc.SandboxProvider {
    return docker(
      this.familyCoderSandboxConfig(auth, model, ctx, outcomeLanding, soul),
    );
  }

  protected familyCoderSandboxConfig(
    auth: ShipAuth,
    model: string,
    ctx: DispatchContext,
    outcomeLanding: { path: string; sandboxPath: string },
    soul: WorkerSpec["soul"] = "fixer",
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
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
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [
      { hostPath: outcomeLanding.path, sandboxPath: outcomeLanding.sandboxPath },
    ];
    if (auth.codexAuthDir !== undefined) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    if (auth.grokAuthDir !== undefined) {
      mounts.push({ hostPath: auth.grokAuthDir, sandboxPath: SANDBOX_GROK_DIR });
    }
    appendAgyAuthMount(mounts, auth.agyDir);
    // #372: mount souls live for family coder-fix worker.
    // Shared helper forces readonly:true.
    appendAgySoulMount(
      mounts,
      { model, soul },
      isBillingPoolDispatchId(ctx.billingPool) ? ctx.billingPool : undefined,
      this.opts.soulsDir,
    );
    mounts.push(soulsMount(this.opts.soulsDir));
    appendHomeEnvMount(mounts, this.resolveHomeEnvFile());
    return { imageName: this.opts.imageName, env, mounts };
  }

  /**
   * #919 post-R8 M1 — family coder-fix uses the same T2 projection as
   * single-slice {@link projectCoderStationReceipt}: status:refused + keys
   * survive; cargo refuseRecords are opaque; cargo never invents refuse traffic.
   */
  protected familyCoderResultFromRun(
    result: Pick<
      Awaited<ReturnType<typeof sc.run>>,
      "stdout" | "commits" | "iterations"
    > & { readonly output?: unknown },
    spec: WorkerSpec,
    outcomePath: string,
  ): WorkerResult {
    void spec;
    // Output.object was attached for this seat: absent typed signal fails for
    // #598 — never treat missing SO as cargo/no-gate completion (#899).
    const typed = requireTypedTrafficSignal(result.output, "family-coder-fix");
    const cargo = this.familyCoderCargoRaw(outcomePath);
    try {
      return {
        kind: "completed",
        output: projectCoderStationReceipt(typed, cargo),
        sessionId: lastSessionId(result),
      };
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      throw new Error(
        reason.startsWith("illegal coder station receipt")
          ? `family-coder-fix: ${reason}`
          : `family-coder-fix: illegal coder station receipt: ${reason}`,
      );
    }
  }

  /**
   * Family coder-fix cargo from the sidecar only. Tolerant reads — no
   * Zod/schema gate on ordinary cargo. Fate keys (escalate) are stripped so
   * a spoofed sidecar cannot override a validated typed T2 receipt (#899).
   */
  private familyCoderCargoRaw(outcomePath: string): unknown | undefined {
    try {
      const cargo = (() => {
        try {
          return readRequiredWorkerOutcomeSidecar(outcomePath);
        } catch {
          return undefined;
        }
      })();
      if (cargo === undefined) return undefined;
      if (cargo !== null && typeof cargo === "object" && !Array.isArray(cargo)) {
        const stripped: Record<string, unknown> = {
          ...(cargo as Record<string, unknown>),
        };
        delete stripped.escalate;
        return stripped;
      }
      return cargo;
    } catch {
      return undefined;
    }
  }

  protected async runFamilyReviewLoopWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    if (ctx.familyBase === undefined) {
      throw new Error(
        `dispatchWorker(${spec.kind}): a family ${spec.kind} worker requires ` +
          "ctx.familyBase (the merged base whose PR is under online review).",
      );
    }
    const auth = this.mountShipAuth();
    try {
      const missingProvider = this.unavailableWorkerProviderAuth(spec, auth, ctx);
      if (missingProvider !== undefined) {
        return {
          kind: "escalated",
          escalation: runnerSynthesizedFailureEscalation({
            reason: `no ${missingProvider} auth — the family ${spec.kind} provider cannot start`,
            diagnosis: "typed provider availability preflight rejected the review-loop launch before sc.run",
          }),
        };
      }
      if (modelFamilyForSlug(spec.model) === "claude" && auth.claudeToken === undefined) {
        return {
          kind: "escalated",
          escalation: runnerSynthesizedFailureEscalation({
            reason:
              `no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — the family ${spec.kind} worker cannot start`,
            diagnosis:
              `the family ${spec.kind} worker is a top-level Claude worker when the ` +
              "active route selects a Claude-family model; provide " +
              "CLAUDE_CODE_OAUTH_TOKEN / ~/.sc-claude-token or select a non-Claude route.",
          }),
        };
      }
      this.checkoutSharedRepo(ctx.familyBase);
      // verify/fixer need the bot-evidence landing; landing only invokes
      // /gstack-document-release and does not read the online-review snapshot.
      const onlineReviewLanding =
        spec.kind === "landing"
          ? undefined
          : this.writeFamilyOnlineReviewLandingFile(ctx, landing);
      const outcomeLanding = this.prepareFamilyReviewOutcomeLanding();
      try {
        // #919 CR T2 / ADR 0132: thin onlineReview station receipt
        // (completed|escalate). Role cargo (verify/fixer/cleanup/landing)
        // rides opaque sidecar only — never dual decision-gate tag.
        const result = await this.runAgentSandbox({
          name: `family-${spec.kind}`,
          idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
          cwd: this.opts.workingRepo,
          sandbox: this.familyReviewLoopSandbox(
            auth,
            spec,
            ctx,
            onlineReviewLanding,
            outcomeLanding,
          ),
          agent: this.agentForSpec(spec, ctx),
          maxIterations: spec.maxIter,
          branchStrategy: { type: "head" },
          promptFile: join(this.opts.promptsDir, spec.promptFile),
          output: onlineReviewReceiptOutput(
            onlineReviewStationReceiptSchema(),
            ONLINE_REVIEW_RECEIPT_TAG,
            this.resumeCapableForSpec(spec, ctx),
          ),
        });
        return this.familyReviewLoopResultFromRun(result, spec, outcomeLanding.path);
      } finally {
        if (onlineReviewLanding !== undefined) {
          rmSync(onlineReviewLanding.path, { force: true });
        }
        this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir, auth.grokAuthDir, auth.agyDir]);
    }
  }

  protected writeFamilyOnlineReviewLandingFile(
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): { path: string; sandboxPath: string } {
    if (landing?.onlineReviewSnapshot === undefined) {
      throw new Error(
        "writeFamilyOnlineReviewLandingFile: online review landing requires onlineReviewSnapshot",
      );
    }
    ensureGitInfoExclude(this.opts.workingRepo, ONLINE_REVIEW_LANDING_FILE);
    const path = join(this.opts.workingRepo, ONLINE_REVIEW_LANDING_FILE);
    writeFileSync(
      path,
      `${JSON.stringify(
        {
          onlineReviewSnapshot: landing.onlineReviewSnapshot,
          shipDelivery: landing.shipDelivery,
          onlineReviewRound: landing.onlineReviewRound ?? ctx.onlineReviewRound,
          fixMarkedFindingIdentityKeys: landing.fixMarkedFindingIdentityKeys ?? [],
          ...(ctx.escalationAnswer !== undefined
            ? { escalationAnswer: ctx.escalationAnswer }
            : {}),
          ...(landing.priorRoundFindings !== undefined &&
          landing.priorRoundFindings.length > 0
            ? { priorRoundFindings: landing.priorRoundFindings }
            : {}),
        },
        null,
        2,
      )}\n`,
      "utf8",
    );
    return { path, sandboxPath: ONLINE_REVIEW_LANDING_FILE };
  }

  protected familyReviewLoopSandbox(
    auth: ShipAuth,
    spec: WorkerSpec,
    ctx: DispatchContext,
    onlineReviewLanding?: { path: string; sandboxPath: string },
    outcomeLanding?: { path: string; sandboxPath: string },
  ): sc.SandboxProvider {
    return docker(
      this.familyReviewLoopSandboxConfig(
        auth,
        spec,
        ctx,
        onlineReviewLanding,
        outcomeLanding,
      ),
    );
  }

  protected familyReviewLoopSandboxConfig(
    auth: ShipAuth,
    spec: WorkerSpec,
    ctx: DispatchContext,
    onlineReviewLanding?: { path: string; sandboxPath: string },
    outcomeLanding?: { path: string; sandboxPath: string },
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    // #919 R8: pass id so isJudgeSeat (S3/S6 step/id only) is correct for family seats.
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
      [SANDBOX_REPO_ENV]: this.opts.repo,
    };
    if (onlineReviewLanding !== undefined) {
      env[SANDBOX_ONLINE_REVIEW_PATH_ENV] = onlineReviewLanding.sandboxPath;
    }
    if (outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = outcomeLanding.sandboxPath;
    }
    if (ctx.familyIssue !== undefined) {
      const issue = String(ctx.familyIssue);
      env[SANDBOX_ISSUE_NUMBER_ENV] = issue;
      env[SANDBOX_ISSUE_NUMBER_ALIAS_ENV] = issue;
    }
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    if (auth.ghToken !== undefined) env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [];
    if (onlineReviewLanding !== undefined) {
      mounts.push({
        hostPath: onlineReviewLanding.path,
        sandboxPath: onlineReviewLanding.sandboxPath,
        readonly: true,
      });
    }
    if (outcomeLanding !== undefined) {
      mounts.push({
        hostPath: outcomeLanding.path,
        sandboxPath: outcomeLanding.sandboxPath,
      });
    }
    if (auth.codexAuthDir !== undefined) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    if (auth.grokAuthDir !== undefined) {
      mounts.push({ hostPath: auth.grokAuthDir, sandboxPath: SANDBOX_GROK_DIR });
    }
    appendAgyAuthMount(mounts, auth.agyDir);
    appendAgySoulMount(
      mounts,
      spec,
      isBillingPoolDispatchId(ctx.billingPool) ? ctx.billingPool : undefined,
      this.opts.soulsDir,
    );
    mounts.push(soulsMount(this.opts.soulsDir));
    appendHomeEnvMount(mounts, this.resolveHomeEnvFile());
    return { imageName: this.opts.imageName, env, mounts };
  }

  protected familyReviewLoopResultFromRun(
    result: Pick<Awaited<ReturnType<typeof sc.run>>, "stdout" | "iterations"> & {
      readonly output?: unknown;
    },
    spec: WorkerSpec,
    outcomePath?: string,
  ): WorkerResult {
    const sessionId = lastSessionIdIfPresent(result);
    // Output.object was attached: absent typed signal → #598, not cargo/no-gate.
    const typed = requireTypedTrafficSignal(
      result.output,
      `family-${spec.kind}`,
    );
    // #919 CR T2: thin onlineReview envelope is sole fate channel.
    const decoded = decodeOnlineReviewEnvelope(typed);
    if (!decoded.ok) {
      throw new Error(
        `family-${spec.kind}: illegal onlineReview station receipt: ${decoded.reason}`,
      );
    }
    if (decoded.value.status === "escalate") {
      return {
        kind: "escalated",
        escalation: {
          reason: decoded.value.reason,
          diagnosis: decoded.value.diagnosis,
        },
        sessionId,
      };
    }
    // completed: sidecar/stdout enrich role cargo only — never escalate.
    // Sparse / unusable cargo completes as role-native opaque miss (ship-aligned);
    // cargo shape is never a #598 process failure (#899 / ADR 0131).
    return reviewLoopCargoResult(result.stdout, spec.kind, sessionId, outcomePath);
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
    // #711: runner only carries prior-round data. Method lives in the
    // live-mounted verify soul; pass scope lives in the selected CMR prompt.
    const priorRoundBlock =
      ctx.priorRoundFindings !== undefined && ctx.priorRoundFindings.length > 0
        ? `\n\nPrior integrated-CMR rounds from the family ledger (#711):\n\n\`\`\`json\n${JSON.stringify(
            ctx.priorRoundFindings,
            null,
            2,
          )}\n\`\`\``
        : "";
    // The focus file is pass-scoped: it pins only the exact review scope and the
    // machine-resolved-child focus. Cross-pass accounting lives in the durable
    // ledger / worker verdict fields, not in this transient prompt file.
    const body =
      `# Integrated cmr — review scope + focus (machine-generated; #335)\n\n` +
      `Review THIS exact family-base diff (the commits the family base added since it\n` +
      `was cut from its target):\n\n    ${scope}\n\n${passLine}\n\n${focusLine}${moduleBlock}${closureBlock}${priorRoundBlock}${answerBlock}\n`;
    // Git-ignore it (it is a transient runtime artifact, never committed) then write.
    const target = join(this.opts.workingRepo, CMR_FOCUS_FILENAME);
    this.excludeFromGit(CMR_FOCUS_FILENAME);
    writeFileSync(target, body, "utf8");
  }

  /** ADR 0145 — write the phase-scoped family-verify judge focus file. */
  protected writeWaveVerifyFocusFile(ctx: DispatchContext): void {
    const failure = ctx.waveVerifyFailure ?? "";
    const phase = ctx.phase ?? "wave";
    const accidentScope =
      phase === "wave"
        ? "after the current wave's child slices merged"
        : phase === "correctness_checkpoint"
          ? "at the correctness checkpoint"
          : "at the final family verification barrier";
    const answerBlock =
      ctx.escalationAnswer !== undefined
        ? `\n\nHuman escalation answer (#439):\n\n\`\`\`json\n${JSON.stringify(
            ctx.escalationAnswer,
            null,
            2,
          )}\n\`\`\`\n\nRetry the previously paused family-verify triage with this answer in force.`
        : "";
    const body =
      `# Family-verify triage — ${phase} (machine-generated; ADR 0145)\n\n` +
      `The family base verify (typecheck + tests) went RED ${accidentScope}.\n` +
      `Classify this phase-scoped red and return the shared typed judge verdict:\n` +
      `\`continue\` (author the repair packet for the family coder-fix seat — a real\n` +
      `code regression within this phase scope) or \`toolchain\` (an environment/\n` +
      `toolchain red the runner falls back to verify_failed on). Convergence is the\n` +
      `deterministic green re-verify receipt — never your word alone.\n\n` +
      `## Verify failure output\n\n\`\`\`\n${failure}\n\`\`\`${answerBlock}\n`;
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
    // Shared-repo exclude is written once in prepareFamilyCmrPanelRound
    // (#1094 R2 F4). Judge-only path (no panel prep) still needs it here.
    ensureGitInfoExclude(this.opts.workingRepo, WORKER_OUTCOME_REPO_FILE);
    return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
  }

  /** Add a transient cmr runtime file to the worktree's local git excludes. */
  protected excludeFromGit(filename: string): void {
    try {
      // Shared info/exclude write (#1014 DRY); throw-through for CMR must-exclude.
      appendGitInfoExclude(this.opts.workingRepo, filename);
    } catch (err) {
      throw new Error(
        `excludeFromGit: failed to exclude transient CMR runtime file "${filename}": ` +
          `${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }

  /**
   * The cmr worker's sandbox (live soul + image-provided skills and CLIs).
   * `runCmrWorker` mounts the auth ONCE up-front (so it can fail-closed on the
   * worker's own Claude token — codex cmr R4) and passes it here, avoiding a
   * double-mount. Judge identity credential is keyed by {@link WorkerSpec.model}
   * family — isomorphic to {@link panelLegSandboxConfig} (#1094 R2 F1).
   */
  protected cmrSandbox(
    auth: CmrAuth,
    spec: Pick<WorkerSpec, "model" | "soul" | "host">,
    outcomeLanding?: { path: string; sandboxPath: string },
    ctx?: Pick<DispatchContext, "billingPool">,
    fixFindingsLanding?: { path: string; sandboxPath: string },
  ): sc.SandboxProvider {
    return docker(
      this.cmrSandboxConfig(
        auth,
        spec,
        outcomeLanding,
        ctx,
        fixFindingsLanding,
      ),
    );
  }

  /**
   * Copy the three reviewer legs' host credentials into per-run dirs the cmr
   * sandbox mounts (#335). codex auth + the agy OAuth token are file/dir mounts;
   * the claude leg uses the durable OAuth token env var. Mirrors
   * `RealBackend.mountAuth`. The agy token is copied into a per-run dir mounted
   * WRITABLE (the agy CLI writes runtime state under its config dir — #333 gotcha).
   *
   * codex cmr R1: EACH leg's auth is BEST-EFFORT (降级链). Core provision is
   * shared (#913); gh is BEST-EFFORT here (completeness gate degrades without it,
   * never blocks the cmr worker).
   */
  protected mountCmrAuth(): CmrAuth {
    return this.mountAuthWithGh("cmr");
  }

  /**
   * Shared cmr/ship auth mount: core credentials via {@link provisionFamilyWorkerAuth}
   * plus gh + providerAuth projection. Differs only by `rolePrefix` (temp-dir
   * identity / cleanup). Policy on gh (best-effort vs hard-required) lives at
   * the worker preflight, not here.
   */
  private mountAuthWithGh(rolePrefix: "cmr" | "ship"): FamilyWorkerAuthWithGh {
    const core = provisionFamilyWorkerAuth({
      home: this.opts.home ?? homedir(),
      rolePrefix,
      homeEnvFile: this.resolveHomeEnvFile(),
      codexFast: this.opts.codexFast,
    });
    return {
      ...core,
      ghToken: this.readGhToken(),
      providerAuth: providerAuthFromCore(core),
    };
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
   * Pure config for the cmr sandbox — #1094 F7 pure court + R2 F1 judge identity
   * + R3 F1 executing-provider mount.
   * Mounts ONLY the credential for the CLI that will actually run (pool-aware
   * via {@link resolveModelSlugForPool}), isomorphic to
   * {@link panelLegSandboxConfig}. Nested-panel armament stays deleted.
   */
  protected cmrSandboxConfig(
    auth: CmrAuth,
    spec: Pick<WorkerSpec, "model" | "soul" | "host">,
    outcomeLanding?: { path: string; sandboxPath: string },
    ctx?: Pick<DispatchContext, "billingPool">,
    fixFindingsLanding?: { path: string; sandboxPath: string },
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    // ORCHESTRATOR_REPO: the cmr worker runs `gh issue view` / `gh issue create`
    // needing `--repo "$ORCHESTRATOR_REPO"`.
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
      [SANDBOX_REPO_ENV]: this.opts.repo,
    };
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    if (auth.ghToken !== undefined) env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    if (outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = outcomeLanding.sandboxPath;
    }
    if (fixFindingsLanding !== undefined) {
      env[SANDBOX_FIX_FINDINGS_PATH_ENV] = fixFindingsLanding.sandboxPath;
    }
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [];
    if (outcomeLanding !== undefined) {
      mounts.push({
        hostPath: outcomeLanding.path,
        sandboxPath: outcomeLanding.sandboxPath,
      });
    }
    // Executing-provider credential only (#1094 R3 F1) — not registry-row family,
    // not multi-provider armament. A 429 relay onto grok-build must mount ~/.grok
    // even when the judge slug stays gpt-5.6-sol.
    const pool = isBillingPoolDispatchId(ctx?.billingPool)
      ? ctx.billingPool
      : undefined;
    const provider = resolveModelSlugForPool(spec.model, pool).provider;
    if (provider === "codex" && auth.codexAuthDir !== undefined) {
      mounts.push({
        hostPath: auth.codexAuthDir,
        sandboxPath: SANDBOX_CODEX_DIR,
      });
    }
    if (provider === "agy" && auth.agyDir !== undefined) {
      appendAgyAuthMount(mounts, auth.agyDir);
      appendAgySoulMount(mounts, spec, pool, this.opts.soulsDir);
    }
    if (provider === "grok" && auth.grokAuthDir !== undefined) {
      mounts.push({
        hostPath: auth.grokAuthDir,
        sandboxPath: SANDBOX_GROK_DIR,
      });
    }
    mounts.push(soulsMount(this.opts.soulsDir));
    appendHomeEnvMount(mounts, this.resolveHomeEnvFile());
    return { imageName: this.opts.imageName, env, mounts };
  }

  // ─────────────────────────── ship WORKER (止于 PR) ───────────────────────────

  /**
   * Dispatch the FAMILY ship WORKER (#336): a CONTAINER ship worker invoking
   * `gstack-ship` over the family base, 止于 PR (the online bot cmr + merge are the
   * separate pr-review-loop stage). Maps the ship receipt to the full
   * {@link WorkerResult} union (PRD #330 R2): shipped → `completed` ShipResult; a
   * genuine block → `escalated`. A rerun-able flake is handled inside the worker;
   * other clean-exit cargo returns a completed placeholder.
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
        escalation: outcome.escalation ?? {
          reason: outcome.reason,
          diagnosis: outcome.diagnosis,
        },
      };
    }
    // Clean exit (exit 0): process success regardless of cargo richness.
    // Missing / off-shape delivery cargo must NOT become a coder no-commit
    // report — that re-opens cargo as a fourth fate channel (#899 / ADR 0131).
    // Cargo fields are transported as-is; status is never synthesized.
    if (outcome.kind === "completed") {
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: ctx.familyBase,
        },
      };
    }
    return {
      kind: "completed",
      output: {
        kind: "ship",
        branch: outcome.branch ?? ctx.familyBase,
        ...(outcome.status !== undefined ? { status: outcome.status } : {}),
        ...(outcome.pr !== undefined ? { pr: outcome.pr } : {}),
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
   * `branchStrategy:{type:"head"}` keeps it on the checked-out family base.
   * Completion is clean exit + legal sidecar / typed gate (#928); delivery cargo
   * is classified from the typed envelope / sidecar, not a STEP_COMPLETE password.
   */
  protected async runShipWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ReturnType<typeof shipOutcomeFromResult>> {
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
      const missingProvider = this.unavailableWorkerProviderAuth(spec, auth, ctx);
      if (missingProvider !== undefined) {
        return {
          kind: "escalate",
          reason: `no ${missingProvider} auth — the selected ship provider cannot start`,
          diagnosis:
            "selected provider cannot start without CLAUDE_CODE_OAUTH_TOKEN when Claude is selected; typed provider availability preflight rejected the ship launch before sc.run",
          escalation: runnerSynthesizedFailureEscalation({
            reason: `no ${missingProvider} auth — the selected ship provider cannot start`,
            diagnosis:
              "typed provider availability preflight rejected the ship launch before sc.run",
          }),
        };
      }
      if (modelFamilyForSlug(spec.model) === "claude" && auth.claudeToken === undefined) {
        return {
          kind: "escalate",
          reason: "no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — the ship worker cannot start",
          diagnosis: "ship worker cannot start without CLAUDE_CODE_OAUTH_TOKEN",
          escalation: runnerSynthesizedFailureEscalation({
            reason:
              "no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — the ship worker cannot start",
            diagnosis: "ship worker cannot start without CLAUDE_CODE_OAUTH_TOKEN",
          }),
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
          escalation: runnerSynthesizedFailureEscalation({
            reason: "no gh auth (GH_TOKEN) — the family ship worker cannot `gh pr create`",
            diagnosis:
              "the family ship worker cannot open its PR without host GitHub authentication",
          }),
        };
      }
      // Check out the family base so gstack-ship delivers the RIGHT branch.
      this.checkoutSharedRepo(ctx.familyBase!);
      // cmr S336 r5: thread the CONFIGURED PR target base into the worker via a
      // git-ignored focus file the prompt reads FIRST. gstack-ship otherwise infers
      // the repo default branch and misses a configured non-main target. Written
      // AFTER the checkout (the file lives in the family-base
      // worktree) and BEFORE the container so the worker can read it.
      this.writeShipFocusFile(ctx);
      const outcomeLanding = this.prepareFamilyShipOutcomeLanding();
      try {
        const result = await this.shipContainerRun(spec, auth, outcomeLanding, ctx);
        // Output.object was attached: absent typed signal → #598, not cargo.
        const typed = requireTypedTrafficSignal(
          (result as { readonly output?: unknown }).output,
          "family-ship",
        );
        return shipOutcomeFromResult({
          ...result,
          outcomePath: outcomeLanding.path,
          output: typed,
        });
      } finally {
        this.cleanupTempAuthDirs([join(outcomeLanding.path, "..")]);
      }
    } finally {
      this.cleanupTempAuthDirs([auth.codexAuthDir, auth.grokAuthDir, auth.agyDir]);
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
    ctx?: Pick<DispatchContext, "billingPool" | "familyIssue">,
  ): Promise<Awaited<ReturnType<typeof sc.run>>> {
    // #909: route ship through runAgentSandbox (not bare sc.run) so the shared
    // idle → quota-probe wrap applies on the same seam as other family workers.
    // Tests can trap launch options here without spying on Sandcastle ESM exports.
    return this.runAgentSandbox({
      name: "family-ship",
      idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
      cwd: this.opts.workingRepo,
      sandbox: this.shipSandbox(auth, outcomeLanding, spec, ctx?.billingPool),
      // Derive the model from the spec via the validated registry — NOT a hardcoded id.
      // A hardcoded family model bypassed `modelIdForSlug` AND pinned a DIFFERENT
      // id (claude-sonnet-4-5) than the verified `sonnet → claude-sonnet-5`
      // mapping `familyShipWorkerSpec().model` resolves to (cmr S336 r7 P1).
      agent: this.agentForSpec(spec, ctx),
      maxIterations: spec.maxIter,
      branchStrategy: { type: "head" },
      promptFile: join(this.opts.promptsDir, spec.promptFile),
      // #919 D / ADR 0132: T2 ship station receipt (SHIP_RECEIPT_TAG + schema).
      // PR/URL delivery cargo stays on sidecar outside SO.
      output: shipReceiptOutput(
        shipStationReceiptSchema(),
        SHIP_RECEIPT_TAG,
        this.resumeCapableForSpec(spec, ctx),
      ),
    });
  }

  protected prepareFamilyShipOutcomeLanding(): { path: string; sandboxPath: string } {
    mkdirSync(this.opts.ledgerDir, { recursive: true });
    const dir = mkdtempSync(join(this.opts.ledgerDir, "worker-outcome-ship-"));
    const path = join(dir, "outcome.json");
    writeFileSync(path, "", "utf8");
    ensureGitInfoExclude(this.opts.workingRepo, WORKER_OUTCOME_REPO_FILE);
    return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
  }

  /**
   * Write the git-ignored SHIP FOCUS file into the family-base worktree (cmr S336
   * r5): the family base branch + the CONFIGURED PR target base (`opts.base`) + the
   * repo slug. The worker's prompt reads it FIRST so the in-container `gstack-ship`
   * opens the family PR against the configured base instead of its inferred repo
   * default (the lone load-bearing item gstack-ship cannot infer: `--head` = the checked-out
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
    ensureGitInfoExclude(this.opts.workingRepo, SHIP_FOCUS_FILENAME);
    writeFileSync(target, body, "utf8");
  }

  /** The family ship worker's sandbox (live soul + image-provided skills and CLIs). */
  protected shipSandbox(
    auth: ShipAuth = this.mountShipAuth(),
    outcomeLanding?: { path: string; sandboxPath: string },
    spec?: WorkerSpec,
    billingPool?: DispatchContext["billingPool"],
  ): sc.SandboxProvider {
    return docker(this.shipSandboxConfig(auth, outcomeLanding, spec, billingPool));
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
    // #913: shared core + gh + providerAuth; ship REQUIRE-gh is preflighted in
    // runShipWorker (cmr S336 r10), not at mount time.
    return this.mountAuthWithGh("ship");
  }

  /**
   * Read the host's gh OAuth token via `gh auth token` (cmr S336 r10). The token
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
   * seam (mirrors `cmrSandboxConfig`). No
   * container, no I/O: a unit test asserts the mounts + soul env. The ship worker
   * runs under the WRITE (`coder`) soul (it commits the bump + pushes), with codex
   * auth + the claude token + the gh token (GH_TOKEN, cmr S336 r10), NO skills mount
   * (the 2b image BAKES gstack-ship — a runtime mount would SHADOW it, #334).
   */
  protected shipSandboxConfig(
    auth: ShipAuth,
    outcomeLanding?: { path: string; sandboxPath: string },
    spec?: WorkerSpec,
    billingPool?: DispatchContext["billingPool"],
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    // ORCHESTRATOR_REPO too: the ship soul records a deferred finding with
    // `gh issue create --repo "$ORCHESTRATOR_REPO"`, so the family ship sandbox must
    // export it or that tracker write fails on an unset var (codex #384 — symmetric
    // with the other family worker sandboxes).
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
      [SANDBOX_REPO_ENV]: this.opts.repo,
    };
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    // cmr S336 r10: the in-container `gh pr create` (the family delivery) reads
    // GH_TOKEN. Set only when present (the pure seam stays tolerant; the REQUIRE-gh
    // gate is the runShipWorker preflight).
    if (auth.ghToken !== undefined) env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    if (outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = outcomeLanding.sandboxPath;
    }
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [];
    if (auth.codexAuthDir !== undefined) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    if (auth.grokAuthDir !== undefined) {
      mounts.push({ hostPath: auth.grokAuthDir, sandboxPath: SANDBOX_GROK_DIR });
    }
    appendAgyAuthMount(mounts, auth.agyDir);
    if (outcomeLanding !== undefined) {
      mounts.push({
        hostPath: outcomeLanding.path,
        sandboxPath: outcomeLanding.sandboxPath,
      });
    }
    // #372: souls mount live for family ship worker.
    // Shared helper forces readonly:true at every site.
    if (spec !== undefined) {
      appendAgySoulMount(
        mounts,
        spec,
        isBillingPoolDispatchId(billingPool) ? billingPool : undefined,
        this.opts.soulsDir,
      );
    }
    mounts.push(soulsMount(this.opts.soulsDir));
    appendHomeEnvMount(mounts, this.resolveHomeEnvFile());
    return { imageName: this.opts.imageName, env, mounts };
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
      escalationKind: escalation.escalationKind,
      phase: escalation.phase ?? "final",
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
 * The classified outcome of the integrated cmr WORKER's run (#335 / #930).
 *   - `judge`    — live T2 tri-state verdict (sole production traffic after #930);
 *   - `verdict`  — residual open-count / legacy cargo paper (project once at
 *     {@link RealFamilyBackend.cmrOutcomeToWorkerResult} boundary);
 *   - `escalate` — model-stuck ⇒ WorkerResult-level escalate 续跑 fork.
 */
export type CmrWorkerOutcome =
  | {
      readonly kind: "judge";
      readonly status: "converged" | "continue" | "escalate" | "toolchain";
      readonly findingDispositions?: ReadonlyArray<
        import("../types.js").JudgeFindingDisposition
      >;
      /** ADR 0138: judge-authored coder-fix packet body on continue. */
      readonly fixPacketBody?: string;
      readonly advanceCoder?: string;
      readonly findings?: readonly Finding[];
      readonly reason?: string;
      readonly diagnosis?: string;
      readonly successfulLegs?: readonly string[];
      readonly skippedLegs?: readonly CmrSkippedLeg[];
      readonly claimedFixedFindingIdentityKeys?: readonly string[];
      readonly priorFindingDispositions?: readonly PriorFindingDisposition[];
      readonly evidencePaths?: readonly string[];
      readonly sessionId?: string;
    }
  | {
      readonly kind: "verdict";
      readonly converged?: boolean;
      readonly reason?: string;
      readonly successfulLegs: readonly string[];
      readonly skippedLegs?: readonly CmrSkippedLeg[];
      readonly claimedFixedFindingIdentityKeys?: readonly string[];
      readonly priorFindingDispositions?: readonly PriorFindingDisposition[];
      readonly findings?: readonly Finding[];
      readonly findingsCount?: number;
      readonly evidencePaths: readonly string[];
      readonly sessionId?: string;
    }
  | {
      readonly kind: "escalate";
      readonly reason: string;
      readonly diagnosis: string;
      readonly escalation?: Escalation;
      readonly sessionId?: string;
    };

/** Ride family cargo siblings on kind:judge without inventing a second closer. */
function withFamilyJudgeCargo(
  judge: import("../types.js").JudgeResult,
  cargo: {
    readonly skippedLegs?: readonly CmrSkippedLeg[];
    readonly successfulLegs?: readonly string[];
    readonly evidencePaths?: readonly string[];
    readonly claimedFixedFindingIdentityKeys?: readonly string[];
    readonly priorFindingDispositions?: readonly PriorFindingDisposition[];
  },
): import("../types.js").JudgeResult {
  return {
    ...judge,
    ...(cargo.skippedLegs !== undefined ? { skippedLegs: cargo.skippedLegs } : {}),
    ...(cargo.successfulLegs !== undefined
      ? { successfulLegs: cargo.successfulLegs }
      : {}),
    ...(cargo.evidencePaths !== undefined
      ? { evidencePaths: cargo.evidencePaths }
      : {}),
    ...(cargo.claimedFixedFindingIdentityKeys !== undefined
      ? {
          claimedFixedFindingIdentityKeys:
            cargo.claimedFixedFindingIdentityKeys,
        }
      : {}),
    ...(cargo.priorFindingDispositions !== undefined
      ? { priorFindingDispositions: cargo.priorFindingDispositions }
      : {}),
  };
}

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
 * Shared cmr/ship extras on top of {@link FamilyWorkerAuthCore} (#913 F8):
 * gh token + typed providerAuth projection. Worker policy on gh differs
 * (cmr best-effort completeness gate vs ship hard-required `gh pr create`)
 * and lives at preflight, not in this shape.
 */
export type FamilyWorkerAuthWithGh = FamilyWorkerAuthCore & {
  readonly ghToken?: string;
  readonly providerAuth?: ProviderAuthAvailability;
};

/**
 * The cmr worker's reviewer-leg auth, each leg BEST-EFFORT (codex cmr R1): a leg
 * whose host credential is absent is `undefined` so it degrades (the 降级链 — the
 * skill drops that leg, the rest still review), never crashing the whole gate.
 * Core fields on {@link FamilyWorkerAuthCore}; gh is BEST-EFFORT for the
 * completeness gate (`gh issue view`) — absence degrades authority, never
 * blocks the cmr worker.
 */
export type CmrAuth = FamilyWorkerAuthWithGh;

/**
 * The family ship worker's auth (#336). The codex dir is BEST-EFFORT (mirrors
 * {@link CmrAuth} — it only feeds the in-container diff review); the claude token
 * (the top-level worker's own auth) and the gh token (the `gh pr create` the family
 * delivery requires) are LOAD-BEARING — `runShipWorker` preflights both and escalates
 * when either is absent (cmr S336 r8 + r10). A missing codex source degrades that
 * mount rather than crashing the gate.
 * Core fields on {@link FamilyWorkerAuthCore}; shape shares {@link FamilyWorkerAuthWithGh}.
 */
export type ShipAuth = FamilyWorkerAuthWithGh;

/**
 * The merger worker's auth (integ-cmr int-r2 A-1). When the active route selects a
 * Claude-family merger slug, the claude OAuth token is its OWN auth
 * (LOAD-BEARING) — `runMergerAgent` preflights it and returns a structured
 * non-resolve when absent. When the merger slot is agy, the OAuth dir is likewise
 * load-bearing (N3: reuse provisionAgyAuthDir / appendAgyAuthMount; fail-closed
 * without token). The merger resolves + commits the merge in place
 * (`branchStrategy:{type:"head"}`); it never pushes or opens a PR.
 * No role-only extras (no gh / providerAuth) — alias of {@link FamilyWorkerAuthCore}.
 */
export type MergerAuth = FamilyWorkerAuthCore;

/**
 * Prefer Sandcastle typed receipt for fate signals (T2 judge + decision gate).
 * #928: completion is clean exit + typed envelope / legal sidecar — no signal.
 * Sidecar/stdout are cargo only — never override a schema-validated judge
 * envelope or admit an unvalidated decision bell into the human loop (#899).
 * Residual open-count paper is transport-only (project at worker boundary).
 *
 * #1005 / ADR 0141: when host-observed {@link LegTransport}s are supplied
 * (argument or soft cargo `legTransports`), rebuild `successfulLegs` via
 * {@link successfulLegsFromTransports} — pure prose / unanchored exit0
 * stdout is present paper; content shape is never a gate.
 */
export function cmrOutcomeFromResult(result: {
  cmrReviewLegs?: ReadonlyArray<{ readonly slug: string }>;
  /**
   * Host-observed per-leg transports. When present, authority for
   * `successfulLegs` presence under ADR 0141 (overlays cargo lists).
   */
  legTransports?: ReadonlyArray<LegTransport>;
  outcomePath?: string;
  output?: unknown;
  stdout?: string;
}): CmrWorkerOutcome {
  const stdout = (result.stdout ?? "").trim();
  // Typed Output.object is the sole live fate channel (judge tri-state + gate).
  let outcome: CmrWorkerOutcome;
  if (result.output !== undefined) {
    outcome = classifyCmrOutcomePayload(result.output, "CMR typed receipt");
  } else if (result.outcomePath !== undefined) {
    // Cargo-only fallbacks: sidecar then stdout tags. Never admit residual
    // findingsCount or escalate as process fate from untyped transports (#899).
    try {
      const sidecar = readWorkerOutcomeSidecar(result.outcomePath);
      if (sidecar !== undefined) {
        outcome = classifyCmrCargoOnly(sidecar);
      } else {
        outcome = classifyCmrCargoOnly(parseCmrStdoutCargo(stdout));
      }
    } catch {
      // Unreadable sidecar → try stdout cargo below.
      outcome = classifyCmrCargoOnly(parseCmrStdoutCargo(stdout));
    }
  } else {
    outcome = classifyCmrCargoOnly(parseCmrStdoutCargo(stdout));
  }
  return overlaySuccessfulLegsFromTransports(outcome, result.legTransports);
}

/**
 * #1005 / ADR 0141: when host-observed leg transports are present, they are
 * the authority for panel presence — rebuild successfulLegs transport-only
 * and overlay any cargo list (including a stale []). Content shape is never
 * a gate; monorepo does not park on empty successfulLegs cargo.
 * Escalate outcomes are fate-only and carry no leg cargo.
 */
function overlaySuccessfulLegsFromTransports(
  outcome: CmrWorkerOutcome,
  transports: ReadonlyArray<LegTransport> | undefined,
): CmrWorkerOutcome {
  if (transports === undefined) return outcome;
  if (outcome.kind !== "judge" && outcome.kind !== "verdict") return outcome;
  return {
    ...outcome,
    successfulLegs: successfulLegsFromTransports(transports),
  };
}

/** A trimmed, non-empty string at the schema layer (mirrors shipOutcome.ts). */
const nonEmpty = z.string().trim().min(1);

/**
 * Optional CMR cargo decoders. Escalation is probed independently before these
 * fields; none of the cargo shapes can reject a completed reviewer receipt.
 */
const cmrLegSlugSchema = z.string().trim().min(1);
const cmrSkippedLegSchema = z
  .object({ slug: cmrLegSlugSchema, reason: nonEmpty })
  .strict();
// #875 kill-axis: leg lists are worker prose at parse — non-array / empty /
// chatty skip elements must not shape-kill the whole verdict. Required-leg
// availability is checked earlier by route smoke, not recreated in this parser.
function softParseSuccessfulLegs(raw: unknown): string[] {
  // Always a string[] on the verdict type (CmrWorkerOutcome requires it).
  // Missing / non-array / empty remains [] for the mechanical downstream reader.
  if (!Array.isArray(raw)) return [];
  const kept: string[] = [];
  for (const item of raw) {
    if (typeof item === "string" && item.trim().length > 0) {
      kept.push(item.trim());
    }
  }
  return kept;
}

/**
 * Soft-parse optional per-leg transports from cargo (#1005 / ADR 0141).
 * Non-array / undefined → undefined (fall back to successfulLegs list).
 * Empty array or all-invalid rows after filter → undefined (same fall-back
 * as transport-absent — chatty garbage must not force successfulLegs=[]).
 * Well-formed rows (including dead transports) feed
 * {@link successfulLegsFromTransports}.
 */
function softParseLegTransports(
  raw: unknown,
): ReadonlyArray<LegTransport> | undefined {
  if (raw === undefined || !Array.isArray(raw)) return undefined;
  const kept: LegTransport[] = [];
  for (const item of raw) {
    if (item === null || typeof item !== "object" || Array.isArray(item)) {
      continue;
    }
    const rec = item as Record<string, unknown>;
    if (typeof rec.slug !== "string" || rec.slug.trim().length === 0) continue;
    if (typeof rec.exitCode !== "number" || !Number.isFinite(rec.exitCode)) {
      continue;
    }
    if (
      rec.stdout !== null &&
      rec.stdout !== undefined &&
      typeof rec.stdout !== "string"
    ) {
      continue;
    }
    kept.push({
      slug: rec.slug.trim(),
      exitCode: rec.exitCode,
      stdout: rec.stdout as string | null | undefined,
    });
  }
  // No legal rows after filter ≡ transport-absent (fall back).
  return kept.length > 0 ? kept : undefined;
}

/**
 * Production panel path: pull host-observed leg transports off a sandbox
 * result when present (ADR 0141). Looks at real production shapes:
 *   1. top-level `result.legTransports` (host / producer field)
 *   2. typed-output soft cargo `result.output.legTransports` (SO passthrough)
 * Absent → undefined; cargo soft path may still rebuild from payload.
 */
function normalizePanelLegTransports(
  raw:
    | ReadonlyArray<{
        readonly slug: string;
        readonly exitCode: number;
        readonly stdout: string | null | undefined;
      }>
    | undefined,
): ReadonlyArray<LegTransport> | undefined {
  if (raw === undefined || raw.length === 0) return undefined;
  return raw.map((t) => ({
    slug: t.slug,
    exitCode: t.exitCode,
    stdout: t.stdout,
  }));
}

function legTransportsFromCmrSandboxResult(
  result: unknown,
): ReadonlyArray<LegTransport> | undefined {
  if (result === null || typeof result !== "object") return undefined;
  const rec = result as Record<string, unknown>;
  const topLevel = softParseLegTransports(rec.legTransports);
  if (topLevel !== undefined) return topLevel;
  const output = rec.output;
  if (output !== null && typeof output === "object" && !Array.isArray(output)) {
    return softParseLegTransports(
      (output as Record<string, unknown>).legTransports,
    );
  }
  return undefined;
}
function softParseSkippedLegs(
  raw: unknown,
): Array<{ slug: string; reason: string }> | undefined {
  if (raw === undefined) return undefined;
  if (!Array.isArray(raw)) return [];
  const kept: Array<{ slug: string; reason: string }> = [];
  for (const item of raw) {
    const parsed = cmrSkippedLegSchema.safeParse(item);
    if (parsed.success) kept.push(parsed.data);
  }
  return kept;
}
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
  .strict();
// #875 kill-axis: priorFindingDispositions are opaque worker prose at parse.
// Omitting the array, incomplete accepted_suppressed fields, unknown status
// buckets, or extra chatty keys must NOT make the whole verdict malformed.
// Keep only well-formed entries; drop the rest (they do not govern).
// Governance for *finding* suppressions stays strict on
// cmrDispositionEvidenceSchema; pass-time acceptedSuppressions still filters
// via hasAcceptedSuppressionAuthority.
function softParsePriorFindingDispositions(
  raw: unknown,
): PriorFindingDisposition[] | undefined {
  if (raw === undefined) return undefined;
  // Non-array chatty values (object/string/null) → empty prose, not malformed.
  if (!Array.isArray(raw)) return [];
  const kept: PriorFindingDisposition[] = [];
  for (const item of raw) {
    const parsed = cmrFindingDispositionSchema.safeParse(item);
    if (parsed.success) kept.push(parsed.data);
  }
  return kept;
}
function softParseClaimedFixedFindingIdentityKeys(
  raw: unknown,
): string[] | undefined {
  if (raw === undefined) return undefined;
  if (!Array.isArray(raw)) return [];
  const kept: string[] = [];
  for (const item of raw) {
    if (typeof item === "string" && item.trim().length > 0) kept.push(item);
  }
  return kept;
}
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
    // otherwise validate despite contradicting the suppression contract.
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
function isJsonRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function normalizeKnownCmrAliases(parsed: Record<string, unknown>): Record<string, unknown> {
  const base = parsed;
  const dispositions = base.priorFindingDispositions;
  if (!Array.isArray(dispositions)) return base;
  return {
    ...base,
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
 * The independent bell probe precedes verdict cargo parsing, so unrelated schema
 * defects cannot suppress escalation. Verdict parsing is tolerant cargo support;
 * reviewer fate comes from its declared count. Only the LAST `<cmr>` tag is read.
 */
export function parseCmrOutcome(stdout: string): CmrWorkerOutcome {
  const parsed = parseLastTaggedJsonSoft(stdout, "cmr");
  if (parsed === undefined) return sparseCmrCargo();
  return classifyCmrOutcomePayload(parsed, "cmr worker <cmr> tag");
}

function classifyCmrOutcomePayload(
  parsed: unknown,
  _source: string,
): CmrWorkerOutcome {
  if (!isJsonRecord(parsed)) return sparseCmrCargo();
  const normalizedParsed = normalizeKnownCmrAliases(parsed);
  // #899: only well-formed bells are fate signals. Present-but-malformed
  // escalate fails closed for #598 (typed seats also re-ask via schema).
  const gate = classifyDecisionGate(normalizedParsed, "cmr");
  if (gate.kind === "bell") {
    return {
      kind: "escalate",
      reason: gate.reason,
      diagnosis: gate.diagnosis,
    };
  }

  // #930 live path: T2 judge verdict (same decode as single-slice S3/S6).
  const envelope = decodeJudgeVerdict(normalizedParsed);
  if (envelope.ok) {
    const cargo = extractCmrCargoFields(normalizedParsed);
    const v = envelope.value;
    if (v.status === "converged") {
      return { kind: "judge", status: "converged", ...cargo };
    }
    if (v.status === "escalate") {
      return {
        kind: "judge",
        status: "escalate",
        reason: v.reason,
        diagnosis: v.diagnosis,
        ...cargo,
      };
    }
    if (v.status === "toolchain") {
      // #1027 S1 / ADR 0145: toolchain terminal (runner → verify_failed).
      return {
        kind: "judge",
        status: "toolchain",
        reason: v.reason,
        diagnosis: v.diagnosis,
        ...cargo,
      };
    }
    return {
      kind: "judge",
      status: "continue",
      findingDispositions: v.findingDispositions,
      fixPacketBody: v.fixPacketBody,
      ...(v.advanceCoder !== undefined ? { advanceCoder: v.advanceCoder } : {}),
      ...cargo,
    };
  }

  // #919 E: residual open-count / legacy cmr paper is BOUNDARY-ONLY transport.
  // Typed judge failed above → never treat open-count as live fate. Residual
  // cargo rides as kind:verdict; cmrOutcomeToWorkerResult maps it to
  // {@link unusableResidualOpenCountPaper} (kind:"reviewer"+findingsCount:0) —
  // never mint continue from findingsCount; never dual kind:"cmr" unusable.
  return residualCmrVerdictCargo(normalizedParsed);
}

function extractCmrCargoFields(normalizedParsed: Record<string, unknown>): {
  readonly findings?: Finding[];
  readonly successfulLegs?: string[];
  readonly skippedLegs?: Array<{ slug: string; reason: string }>;
  readonly claimedFixedFindingIdentityKeys?: string[];
  readonly priorFindingDispositions?: PriorFindingDisposition[];
  readonly evidencePaths?: string[];
} {
  const findings = Array.isArray(normalizedParsed.findings)
    ? normalizedParsed.findings.flatMap((rawFinding) => {
        const candidate = cmrReviewerFindingSchema.safeParse(rawFinding);
        return candidate.success
          ? [normalizeCmrReviewerFinding(candidate.data)]
          : [];
      })
    : undefined;
  const evidencePaths = Array.isArray(normalizedParsed.evidencePaths)
    ? normalizedParsed.evidencePaths.filter(
        (path): path is string =>
          typeof path === "string" && path.trim().length > 0,
      )
    : undefined;
  const skippedLegs = softParseSkippedLegs(normalizedParsed.skippedLegs);
  const claimedFixedFindingIdentityKeys =
    softParseClaimedFixedFindingIdentityKeys(
      normalizedParsed.claimedFixedFindingIdentityKeys,
    );
  const priorFindingDispositions = softParsePriorFindingDispositions(
    normalizedParsed.priorFindingDispositions,
  );
  // #1005 / ADR 0141: when cargo lands per-leg transports, host rebuilds
  // successfulLegs transport-only (isLegalLegPaper). Content shape is never
  // a gate; transports overlay any cargo successfulLegs (including []).
  // Monorepo is consumer+overlay only — it does not park on empty lists.
  const cargoTransports = softParseLegTransports(
    normalizedParsed.legTransports,
  );
  const successfulLegs =
    cargoTransports !== undefined
      ? successfulLegsFromTransports(cargoTransports)
      : softParseSuccessfulLegs(normalizedParsed.successfulLegs);
  return {
    ...(findings !== undefined ? { findings } : {}),
    successfulLegs,
    ...(skippedLegs !== undefined ? { skippedLegs } : {}),
    ...(claimedFixedFindingIdentityKeys !== undefined
      ? { claimedFixedFindingIdentityKeys }
      : {}),
    ...(priorFindingDispositions !== undefined
      ? { priorFindingDispositions }
      : {}),
    ...(evidencePaths !== undefined ? { evidencePaths } : {}),
  };
}

function residualCmrVerdictCargo(
  normalizedParsed: Record<string, unknown>,
): Extract<CmrWorkerOutcome, { readonly kind: "verdict" }> {
  const cargo = extractCmrCargoFields(normalizedParsed);
  const findingsCount =
    typeof normalizedParsed.findingsCount === "number" &&
    Number.isSafeInteger(normalizedParsed.findingsCount) &&
    normalizedParsed.findingsCount >= 0
      ? normalizedParsed.findingsCount
      : undefined;
  return {
    kind: "verdict",
    ...(typeof normalizedParsed.converged === "boolean"
      ? { converged: normalizedParsed.converged }
      : {}),
    ...(typeof normalizedParsed.reason === "string" &&
    normalizedParsed.reason.trim().length > 0
      ? { reason: normalizedParsed.reason }
      : {}),
    successfulLegs: cargo.successfulLegs ?? [],
    ...(cargo.skippedLegs !== undefined ? { skippedLegs: cargo.skippedLegs } : {}),
    ...(cargo.claimedFixedFindingIdentityKeys !== undefined
      ? {
          claimedFixedFindingIdentityKeys:
            cargo.claimedFixedFindingIdentityKeys,
        }
      : {}),
    ...(cargo.priorFindingDispositions !== undefined
      ? { priorFindingDispositions: cargo.priorFindingDispositions }
      : {}),
    ...(cargo.findings !== undefined ? { findings: cargo.findings } : {}),
    ...(findingsCount !== undefined ? { findingsCount } : {}),
    evidencePaths: cargo.evidencePaths ?? [],
  };
}

function sparseCmrCargo(): Extract<CmrWorkerOutcome, { readonly kind: "verdict" }> {
  return { kind: "verdict", successfulLegs: [], evidencePaths: [] };
}

/**
 * Cargo-only CMR classify: strip findingsCount + escalate so untyped transports
 * cannot change routing (#899). Other prose cargo (legs, findings rows, evidence)
 * may still be transported for the next fixer.
 */
function classifyCmrCargoOnly(parsed: unknown): CmrWorkerOutcome {
  if (!isJsonRecord(parsed)) return sparseCmrCargo();
  const cargo: Record<string, unknown> = { ...parsed };
  delete cargo.escalate;
  delete cargo.findingsCount;
  return classifyCmrOutcomePayload(cargo, "cmr cargo");
}

/** Parse `<cmr>` stdout as opaque cargo JSON (no fate probes). */
function parseCmrStdoutCargo(stdout: string): unknown {
  return parseLastTaggedJsonSoft(stdout, "cmr");
}

/**
 * Parse the merger's structured result for telemetry. The caller does not use
 * this self-report as proof of a landed merge: the post-run git state must show
 * a two-parent merge commit with no in-progress conflict.
 *
 * #919 CR T2 / ADR 0132: typed Output.object is the thin merger station receipt
 * (completed | escalate). Resolve cargo rides on sidecar/stdout and never
 * reintroduces escalate when the typed signal is completed (same class as
 * shipOutcomeFromResult).
 */
export function mergerOutcomeFromResult(result: {
  outcomePath?: string;
  stdout: string;
  output?: unknown;
}): { resolved: boolean; reason?: string; escalation?: FamilyEscalation } {
  // Typed T2 merger envelope is the sole fate channel for gates.
  if (result.output !== undefined) {
    const decoded = decodeMergerEnvelope(result.output);
    if (!decoded.ok) {
      throw new Error(
        `merger: illegal merger station receipt: ${decoded.reason}`,
      );
    }
    if (decoded.value.status === "escalate") {
      return {
        resolved: false,
        reason: decoded.value.reason,
        escalation: {
          reason: decoded.value.reason,
          diagnosis: decoded.value.diagnosis,
          escalationKind: "decision",
          phase: "wave",
        },
      };
    }
    // completed: resolve status from cargo only (never escalate).
    return mergerResolveCargoFromResult(result);
  }
  // No typed signal (pure unit-test cargo path): resolve may enrich, escalate must not.
  return mergerResolveCargoFromResult(result);
}

/** Sidecar/stdout resolve cargo with escalate stripped (not a fate channel). */
function mergerResolveCargoFromResult(result: {
  outcomePath?: string;
  stdout: string;
}): { resolved: boolean; reason?: string; escalation?: FamilyEscalation } {
  if (result.outcomePath !== undefined) {
    try {
      const sidecar = readWorkerOutcomeSidecar(result.outcomePath);
      if (sidecar !== undefined) {
        return classifyMergerCargoOnly(sidecar, "merger agent outcome sidecar");
      }
    } catch (err) {
      return {
        resolved: false,
        reason: `merger worker outcome sidecar protocol failure: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  }
  return classifyMergerCargoOnly(
    parseLastTaggedJsonSoft(result.stdout, "merger"),
    "merger agent <merger> tag",
  );
}

function classifyMergerCargoOnly(
  parsed: unknown,
  source: string,
): { resolved: boolean; reason?: string; escalation?: FamilyEscalation } {
  // Arrays are typeof "object" in JS — reject them at the cargo boundary so
  // spread does not invent numeric keys from a JSON array payload.
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return {
      resolved: false,
      reason: parsed === undefined
        ? `${source} carried no cargo`
        : `${source} was not a JSON object`,
    };
  }
  const cargo: Record<string, unknown> = { ...(parsed as Record<string, unknown>) };
  delete cargo.escalate;
  return classifyMergerOutcomePayload(cargo, source);
}

/** Resolved cargo stays strict; the decision bell is probed independently first. */
const mergerResolvedSchema = z
  .object({ resolved: z.literal(true), tradeoffs: z.string().optional() })
  .strict();

/**
 * Resolve-cargo only (no decision-gate dual). Escalate fate is the T2 merger
 * station receipt via {@link mergerOutcomeFromResult} / decodeMergerEnvelope
 * (#919 CR N1). Callers that still hold raw stdout must strip escalate first
 * (see {@link classifyMergerCargoOnly}).
 */
function classifyMergerOutcomePayload(
  parsed: unknown,
  source: string,
): { resolved: boolean; reason?: string; escalation?: FamilyEscalation } {
  // `JSON.parse` succeeds on the bare literals `null` / `true` / `5` / `"x"` / `[]`;
  // arrays are typeof "object" — reject them here so messages stay specific and
  // we never treat an array payload as merger cargo (agy R1 / gemini R1).
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { resolved: false, reason: `${source} was not a JSON object` };
  }
  if (mergerResolvedSchema.safeParse(parsed).success) {
    return { resolved: true };
  }
  // No resolved schema matched → off-contract cargo. Never read it as a clean resolve.
  return { resolved: false, reason: "merger did not resolve" };
}

/** A one-line human-readable summary of a failed verify command (phase + error). */
function summarizeError(
  phase: VerifyCmrPhase,
  err: unknown,
): string {
  // execFileSync on a non-zero exit throws an Error whose `.message` is only the
  // status line ("Command failed: npx tsc --noEmit") — the ACTUAL compiler / test
  // output (the locatable reason) is on `.stderr` / `.stdout`. Shared capture
  // keeps BOTH streams labeled (formatExecFailureOutput; codex R3 / #1006 DRY).
  // The 600-char tail keeps the trailing end where the real failure lands.
  const detail = formatExecFailureOutput(err);
  const tail = detail.length > 600 ? detail.slice(-600) : detail;
  return `family verify (${phase}) failed: ${tail}`;
}

/**
 * Parse legacy family-escalations.jsonl fail-closed: every non-empty line must
 * JSON.parse AND pass {@link isLegacyEscalationRecordShape}. Blank lines ok.
 */
function parseLegacyEscalationJsonl(raw: string): FamilyEscalationRecord[] {
  const records: FamilyEscalationRecord[] = [];
  let lineNo = 0;
  for (const line of raw.split("\n")) {
    if (line.trim().length === 0) continue;
    lineNo += 1;
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch (err) {
      throw new Error(
        `readEscalations: legacy escalation line ${lineNo} is not valid JSON — ` +
          `refusing to read a partially-readable escalation log (fail closed): ${
            err instanceof Error ? err.message : String(err)
          }`,
      );
    }
    if (!isLegacyEscalationRecordShape(parsed)) {
      throw new Error(
        `readEscalations: legacy escalation line ${lineNo} is not a valid ` +
          `FamilyEscalationRecord shape (must be an object with string reason) — ` +
          `refusing silent cast (fail closed).`,
      );
    }
    records.push(parsed);
  }
  return records;
}

/**
 * Minimum shape for a legacy escalation stuck-point row. `reason` is the only
 * required field; optional known fields are type-checked when present. Extra
 * migration keys (e.g. `ts`) are tolerated on a valid object.
 */
function isLegacyEscalationRecordShape(v: unknown): v is FamilyEscalationRecord {
  if (v === null || typeof v !== "object" || Array.isArray(v)) return false;
  const o = v as Record<string, unknown>;
  if (typeof o.reason !== "string" || o.reason.trim().length === 0) return false;
  if (
    o.escalationKind !== undefined &&
    o.escalationKind !== "decision" &&
    o.escalationKind !== "failure"
  ) {
    return false;
  }
  if (o.familyHeadAfter !== undefined && typeof o.familyHeadAfter !== "string") {
    return false;
  }
  if (o.phase !== undefined && o.phase !== "wave" && o.phase !== "final") {
    return false;
  }
  if (o.diagnosis !== undefined && typeof o.diagnosis !== "string") {
    return false;
  }
  return true;
}

// ════════════════════════════════════════════════════════════════════════════
// #596 F2 / #899 / ADR 0131: family-side cargo transport for the 4 review-loop
// kinds (verify / fixer / cleanup / landing). Sidecar-prefer + last <tag>
// JSON enrich delivery cargo only — never a fate court.
// Law: cargo is opaque. Sparse / unreadable / off-shape cargo completes the
// Action as best-effort (sparseReviewLoopCompleted); it does NOT throw for
// abolished #598 shape-lane and does NOT mint a fake kind:"coder" seat.
// Fate is exit code + typed decision-gate Output.object only. SOE exhaust is
// the sole process-level #598 redispatch channel (handled at the sc.run seat).
// Single-slice uses RealBackend outputFor/decodeOutput; this is the family eqv.
// ════════════════════════════════════════════════════════════════════════════

function parseOutcomePayload(
  stdout: string,
  tag: string,
  outcomePath?: string,
): { parsed: unknown; source: string } | { error: string } {
  if (outcomePath !== undefined) {
    let sidecar: unknown | undefined;
    let sidecarReadError: unknown | undefined;
    try {
      sidecar = readWorkerOutcomeSidecar(outcomePath);
    } catch (err) {
      sidecarReadError = err;
    }
    if (sidecar !== undefined) {
      // Cargo source selection is not a gate court (#899 / H2). Prefer a
      // readable sidecar; do not shop stdout because it carries a decision
      // bell. Fate is typed SO only — callers strip escalate after read.
      return { parsed: sidecar, source: `${tag} worker outcome sidecar` };
    }
    if (sidecarReadError !== undefined) {
      const last = extractLastTagBody(stdout, tag);
      if (last !== undefined) {
        try {
          const parsed = JSON.parse(last.trim());
          return { parsed, source: `${tag} worker <${tag}> tag` };
        } catch {
          // The sidecar and compatibility receipt are both unreadable cargo.
        }
      }
      return {
        error: `${tag} worker outcome sidecar protocol failure: ${sidecarReadError instanceof Error ? sidecarReadError.message : String(sidecarReadError)}`,
      };
    }
  }
  const last = extractLastTagBody(stdout, tag);
  if (last === undefined) {
    return { error: `${tag} worker emitted no <${tag}> tag` };
  }
  try {
    return {
      parsed: JSON.parse(last.trim()),
      source: `${tag} worker <${tag}> tag`,
    };
  } catch {
    return { error: `${tag} worker <${tag}> tag was not valid JSON` };
  }
}

type ReceiptCargo = { readonly kind: "cargo" };

const RECEIPT_CARGO: ReceiptCargo = { kind: "cargo" };

/**
 * Role-native opaque-miss cargo after a clean process + typed no-gate decision
 * (ship-aligned; #899 / ADR 0131). Cargo shape never fails the Action for #598
 * and never mints a fake `kind:"coder"` seat report.
 */
function sparseReviewLoopCompleted(
  kind: string,
  sessionId: string | undefined,
): WorkerResult {
  const output: WorkerOutput =
    kind === "verify"
      ? // Fail-soft: not green → topology continues to fixer with raw artifacts.
        { kind: "verify", converged: false }
      : kind === "fixer"
        ? { kind: "fixer", committed: false }
        : kind === "cleanup"
          ? // Delivery-class: exit 0 = process success; cargo miss does not flip fate.
            { kind: "cleanup", terminal: true, ok: true }
          : // Empty-run success is legal for 文档发布 (process success, cargo miss).
            { kind: "landing", released: true };
  return { kind: "completed", output, sessionId };
}

/**
 * Cargo-only review-loop result. Escalate is never admitted from sidecar/stdout
 * — those transports enrich delivery cargo only (#899). Fate comes solely from
 * the T2 onlineReview station receipt handled by the caller (#919 CR N1).
 */
function reviewLoopCargoResult(
  stdout: string,
  kind: string,
  sessionId: string | undefined,
  outcomePath?: string,
): WorkerResult {
  const tag =
    kind === "verify" ||
    kind === "fixer" ||
    kind === "cleanup" ||
    kind === "landing"
      ? kind
      : "verify";
  // Read cargo, strip fate keys, re-decode without escalate so a spoofed
  // sidecar bell cannot mask legitimate delivery cargo.
  const raw = parseOutcomePayload(stdout, tag, outcomePath);
  if ("error" in raw || !isJsonRecord(raw.parsed)) {
    // Sparse / unreadable cargo: process success + opaque miss (not #598).
    return sparseReviewLoopCompleted(kind, sessionId);
  }
  const cargo: Record<string, unknown> = { ...raw.parsed };
  delete cargo.escalate;
  const cargoStdout = `<${tag}>${JSON.stringify(cargo)}</${tag}>`;
  const parsed =
    kind === "verify"
      ? parseVerifyOutcome(cargoStdout)
      : kind === "fixer"
        ? parseFixerOutcome(cargoStdout)
        : kind === "cleanup"
          ? parseCleanupOutcome(cargoStdout)
          : parseLandingOutcome(cargoStdout);
  if (parsed.kind === "cargo") {
    // Off-shape paper is opaque miss cargo — complete the Action; do not
    // re-open cargo shape as a #598 channel.
    return sparseReviewLoopCompleted(kind, sessionId);
  }
  return { kind: "completed", output: parsed, sessionId };
}

/**
 * #919 CR N1: cargo-only decode. Fate bells live on the T2 onlineReview
 * envelope (decodeOnlineReviewEnvelope); never probe classifyDecisionGate here.
 * Host fail-safe applicator (correctness K1) needs threadReplies /
 * threadsToResolve / deferredIssueUrls decoded when well-typed.
 */
export function parseVerifyOutcome(
  stdout: string,
  outcomePath?: string,
): VerifyResult | ReceiptCargo {
  const payload = parseOutcomePayload(stdout, "verify", outcomePath);
  if ("error" in payload || !isJsonRecord(payload.parsed)) return RECEIPT_CARGO;
  const parsed = payload.parsed;
  if (typeof parsed.converged !== "boolean") return RECEIPT_CARGO;
  const stringArray = (value: unknown): value is string[] =>
    Array.isArray(value) && value.every((item) => typeof item === "string");
  const findingDispositions = Array.isArray(parsed.findingDispositions)
    ? parsed.findingDispositions.filter((item): item is OnlineReviewFindingDisposition => {
        if (!isJsonRecord(item)) return false;
        return (
          typeof item.identityKey === "string" &&
          typeof item.threadId === "string" &&
          (item.action === "fix" || item.action === "reject" || item.action === "defer") &&
          (item.reason === undefined || typeof item.reason === "string")
        );
      })
    : undefined;
  const threadReplies = Array.isArray(parsed.threadReplies)
    ? parsed.threadReplies.filter((item): item is OnlineReviewThreadReply =>
        isJsonRecord(item) &&
        typeof item.threadId === "string" &&
        typeof item.body === "string",
      )
    : undefined;
  const terminalState: VerifyWorkerTerminalState | undefined =
    parsed.terminalState === "mergeable" ||
    parsed.terminalState === "decision_gate_raised"
      ? parsed.terminalState
      : undefined;
  const advanceCoder =
    typeof parsed.advanceCoder === "string" && parsed.advanceCoder.trim().length > 0
      ? parsed.advanceCoder.trim()
      : undefined;
  const candidate: VerifyResult = {
    kind: "verify",
    converged: parsed.converged,
    ...(findingDispositions !== undefined ? { findingDispositions } : {}),
    ...(stringArray(parsed.fixMarkedFindingIdentityKeys)
      ? { fixMarkedFindingIdentityKeys: parsed.fixMarkedFindingIdentityKeys }
      : {}),
    ...(threadReplies !== undefined ? { threadReplies } : {}),
    ...(stringArray(parsed.threadsToResolve)
      ? { threadsToResolve: parsed.threadsToResolve }
      : {}),
    ...(stringArray(parsed.deferredIssueUrls)
      ? { deferredIssueUrls: parsed.deferredIssueUrls }
      : {}),
    ...(terminalState !== undefined ? { terminalState } : {}),
    ...(typeof parsed.isRecheck === "boolean" ? { isRecheck: parsed.isRecheck } : {}),
    ...(advanceCoder !== undefined ? { advanceCoder } : {}),
  };
  return candidate;
}

export function parseFixerOutcome(
  stdout: string,
  outcomePath?: string,
): FixerResult | ReceiptCargo {
  const payload = parseOutcomePayload(stdout, "fixer", outcomePath);
  if ("error" in payload) return RECEIPT_CARGO;
  const parsed = payload.parsed;
  if (!isJsonRecord(parsed)) return RECEIPT_CARGO;
  if (typeof parsed.committed !== "boolean") return RECEIPT_CARGO;
  const candidate: FixerResult = {
    kind: "fixer",
    committed: parsed.committed,
    ...(typeof parsed.alreadySatisfied === "boolean"
      ? { alreadySatisfied: parsed.alreadySatisfied }
      : {}),
    ...(typeof parsed.fixCommitSha === "string" && parsed.fixCommitSha.length > 0
      ? { fixCommitSha: parsed.fixCommitSha }
      : {}),
  };
  return candidate;
}

export function parseCleanupOutcome(
  stdout: string,
  outcomePath?: string,
): CleanupResult | ReceiptCargo {
  const payload = parseOutcomePayload(stdout, "cleanup", outcomePath);
  if ("error" in payload) return RECEIPT_CARGO;
  const parsed = payload.parsed;
  if (!isJsonRecord(parsed)) return RECEIPT_CARGO;
  if (typeof parsed.terminal !== "boolean" || typeof parsed.ok !== "boolean") {
    return RECEIPT_CARGO;
  }
  const branchOutcome =
    parsed.branchOutcome === "deleted" ||
    parsed.branchOutcome === "already_gone" ||
    parsed.branchOutcome === "skipped_tip_drift" ||
    parsed.branchOutcome === "skipped_pr_not_merged" ||
    parsed.branchOutcome === "skipped_precondition"
      ? parsed.branchOutcome
      : undefined;
  const candidate: CleanupResult = {
    kind: "cleanup",
    terminal: parsed.terminal,
    ok: parsed.ok,
    ...(Array.isArray(parsed.issuesClosed) &&
    parsed.issuesClosed.every(
      (issue): issue is number => Number.isInteger(issue) && (issue as number) > 0,
    )
      ? { issuesClosed: parsed.issuesClosed }
      : {}),
    ...(typeof parsed.parentIssueClosed === "boolean"
      ? { parentIssueClosed: parsed.parentIssueClosed }
      : {}),
    ...(branchOutcome !== undefined
      ? { branchOutcome }
      : {}),
    ...(Array.isArray(parsed.skippedReasons) &&
    parsed.skippedReasons.every((reason): reason is string => typeof reason === "string")
      ? { skippedReasons: parsed.skippedReasons }
      : {}),
  };
  return candidate;
}

export function parseLandingOutcome(
  stdout: string,
  outcomePath?: string,
): LandingResult | ReceiptCargo {
  const payload = parseOutcomePayload(stdout, "landing", outcomePath);
  if ("error" in payload) return RECEIPT_CARGO;
  const parsed = payload.parsed;
  if (!isJsonRecord(parsed)) return RECEIPT_CARGO;
  if (typeof parsed.released !== "boolean") return RECEIPT_CARGO;
  const candidate: LandingResult = { kind: "landing", released: parsed.released };
  return candidate;
}
