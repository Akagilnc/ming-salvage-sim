/**
 * realBackend.ts — the REAL {@link Backend} implementation (#256).
 *
 * The first slice (#256) that touches the outside world. The nine prior slices
 * (#247–#255) verified the runner's S0–S8 control flow against FAKE Backends; this
 * file gives that same injected seam a real implementation backed by:
 *   - **Sandcastle** (`createWorktree` / `createSandbox` / `run` / `resumeSession`)
 *     for the resident slice worktree + the isolated agent sandboxes,
 *   - **`gh`** (host-side) for S0/S1 gates + the audit snapshot, plus in-container
 *     `gh` issue reads for the worker's live execution context (the runner passes
 *     issue/repo env + GH_TOKEN when available; the worker must not guess from a
 *     stale prompt snapshot),
 *   - **`git`** for push + the residue-clean reconciliation + the HEAD SHA.
 *
 * The runner control flow is UNCHANGED: this class has the exact Backend
 * signatures the fakes do, so it drops into `runOrchestrator({ backend })`
 * with zero control-flow edits (#256 "真假 Backend 同签名、控制流零改动").
 *
 * ── What is unit-tested vs manually smoked ──────────────────────────────────
 * The container / real-LLM paths (createSandbox/run/resumeSession) are #256's
 * MANUAL smoke (a real container + a real model + a real `gh` is required), NOT
 * the zero-container automated suite. So this file is split:
 *   - PURE host-side logic — gh-snapshot parsing, the auth-mount path
 *     construction, the prompt-content hash, the failedStep attribution, the
 *     resume error fallback decision — is
 *     factored into exported, dependency-light functions
 *     that `realBackend.logic.test.ts` unit-tests WITHOUT a container.
 *   - The thin container glue calls those pure functions and Sandcastle.
 *
 * NOTE on Sandcastle imports: `@ai-hero/sandcastle` is a real dependency, but
 * the heavy container code only runs on the manual-smoke path. The pure logic is
 * importable and testable without ever starting Docker.
 *
 * ── Manual-smoke checklist additions (integ-cmr 256 r2) ─────────────────────
 *   - F3 clean-room snapshot leak: after S1 `writeSnapshot`, assert the snapshot
 *     is git-ignored in the resident worktree — run, inside the worktree:
 *       `git check-ignore .orchestrator-snapshot.json`  → must print the path
 *       (exit 0). A `git status --porcelain` must NOT list it as untracked, and a
 *       coder's `git add -A` must leave it unstaged. Covered by both the checked-in
 *       root `.gitignore` belt AND the per-worktree `.git/info/exclude` suspenders.
 *   - r3 worktree_base_stale: with the local `main` deliberately behind
 *     `origin/main` (e.g. `git reset --hard origin/main~1` on the working clone's
 *     main), run S1 and assert the fresh slice's base SHA equals the LATEST
 *     `origin/main` SHA (`git rev-parse origin/main`), not the stale local one —
 *     proving the cut derives from the just-fetched remote ref (cutRefFor).
 */

import { createHash, randomUUID } from "node:crypto";
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
import { homedir, tmpdir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";

import * as sc from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { z } from "zod";

import { writeContainerCodexConfig } from "./containerCodexConfig.js";
import {
  execFileAsyncWithTimeout,
  shWithClock,
} from "./externalCall.js";
import { withLegTransientRetry } from "./legTransientRetry.js";
import { runExclusive } from "./gitMutex.js";
import {
  provisionRepoNodeModules,
  runProvisionCommand,
  type Sh as ProvisionSh,
} from "./provisionNodeModules.js";
import {
  sourceAuthFailureStopSummary,
  type StopSummary,
} from "./stopSummary.js";
import {
  agentForSlug,
  CODER_CODEX_SLUG,
  effortForLiveOfficer,
  isBillingPoolDispatchId,
  modelFamilyForSlug,
  modelIdForSlug,
  modelIsStrongLeg,
  resolveModelSlug,
  resolveModelSlugForPool,
  unavailableProviderAuth,
  SUPPORTED_MODEL_PROVIDER_FACTORIES,
  type BillingPoolDispatchId,
  type ModelFamily,
  type ModelProviderFactory,
  type ProviderAuthAvailability,
  type ModelSlugRegistryEntry,
} from "./modelRegistry.js";
import {
  routeSmokeEntries,
  smokeRouteModels,
  type ResolvedModelRoute,
} from "./modelRoutes.js";

// ── #884 bare-ping smoke only (credential oracle; no docker/tool loop) ───────

/** Fill `prompts/route-smoke.md` `{{NONCE}}` (or a one-line default). */
export function buildBarePingPrompt(
  nonce: string,
  template: string = "Reply with exactly: {{NONCE}}",
): string {
  if (!template.includes("{{NONCE}}")) {
    throw new Error(
      "bare-ping prompt template must contain {{NONCE}} placeholder",
    );
  }
  return template.split("{{NONCE}}").join(nonce);
}

export function loadBarePingPromptTemplate(promptsDir: string): string {
  return readFileSync(join(promptsDir, "route-smoke.md"), "utf8");
}

/**
 * Credential oracle: stdout is exactly the nonce, or any full line is.
 * Substring embedding (nonce mid-token) does not count.
 */
export function barePingNonceSatisfied(stdout: string, nonce: string): boolean {
  if (nonce.length === 0) return false;
  const trimmed = stdout.trim();
  if (trimmed === nonce) return true;
  return stdout.split(/\r?\n/).some((line) => line.trim() === nonce);
}

export interface BarePingArgv {
  readonly file: string;
  readonly args: readonly string[];
  /** When set, fed on stdin (codex `exec … -` pattern). */
  readonly input?: string;
}

/**
 * One-shot host CLI argv per provider. Empty-cwd / no docker / no tool loop —
 * ignition only answers "is this credential alive?".
 */
export function barePingArgv(
  provider: ModelProviderFactory,
  model: string,
  prompt: string,
): BarePingArgv {
  switch (provider) {
    case "codex":
      // README auth probe: `echo "…" | codex exec --skip-git-repo-check -m <model> -`
      return {
        file: "codex",
        args: ["exec", "--skip-git-repo-check", "--ephemeral", "-m", model, "-"],
        input: prompt,
      };
    case "claudeCode":
      return {
        file: "claude",
        args: [
          "-p",
          prompt,
          "--model",
          model,
          "--permission-mode",
          "bypassPermissions",
        ],
      };
    case "opencode":
      return {
        file: "opencode",
        args: ["run", "--dangerously-skip-permissions", "-m", model, prompt],
      };
    case "grok":
      return {
        file: "grok",
        args: [
          "-p",
          prompt,
          "-m",
          model,
          "--always-approve",
          "--permission-mode",
          "bypassPermissions",
        ],
      };
    case "cursor":
      // Sandcastle 0.10.0 invokes the standalone `agent` binary (not `cursor agent`).
      return {
        file: "agent",
        args: ["-p", prompt, "--model", model, "--print"],
      };
    case "copilot":
      return {
        file: "copilot",
        args: ["-p", prompt, "--model", model],
      };
    case "pi":
      return {
        file: "pi",
        args: ["-p", prompt, "--mode", "json", "--model", model],
      };
  }
}
export {
  agentForSlug,
  CODER_CODEX_SLUG,
  modelFamilyForSlug,
  modelIdForSlug,
  modelIsStrongLeg,
  resolveModelSlug,
  SUPPORTED_MODEL_PROVIDER_FACTORIES,
  type ModelFamily,
  type ModelProviderFactory,
  type ModelSlugRegistryEntry,
};
import {
  buildCliMonitorSpawnSpec,
  workerResultFromMonitorSidecar,
} from "./cliMonitorHooks.js";
import { legacyDispatchWorker } from "./dispatchWorker.js";
import {
  handleIdleThreshold,
  isAgentIdleTimeoutError,
  QuotaWaitForResetError,
  runPoolProbe,
  type HandleIdleThresholdResult,
  type QuotaPoolId,
  type QuotaProbeResult,
  type QuotaWaitForResetLedgerEvent,
} from "./quotaProbe.js";
import { WORKER_PROMPT_FILES } from "./runner.js";
import {
  readRequiredWorkerOutcomeSidecar as readRequiredOutcomeSidecar,
  readWorkerOutcomeSidecar as readOutcomeSidecar,
  stripJsonFence as stripOutcomeJsonFence,
} from "./workerOutcomeSidecar.js";
import { probeWorkerDecisionBell } from "./workerReceipt.js";
import { isStepId } from "./types.js";
import type {
  AgentStepRunOptions,
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  Finding,
  PriorFindingDisposition,
  IssueMeta,
  IssueSnapshot,
  IssueSnapshotMeta,
  PersistentLedgerEntry,
  ResumeState,
  StepId,
  StepOutput,
  StepResult,
  StepSoul,
  StepSpec,
  RepairEvidence,
  WorkerLandingPayload,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "./types.js";
import {
  configureTelemetryFromWorkerImage,
  durableTelemetryDirForSingleSlice,
} from "./telemetry.js";
// ════════════════════════════════════════════════════════════════════════════
// PURE host-side logic (unit-tested in realBackend.logic.test.ts; no container)
// ════════════════════════════════════════════════════════════════════════════

// ── gh issue → IssueMeta / IssueSnapshot parsing ────────────────────────────

/** The heading that marks an (optional) `## Agent Brief` section — the
 *  most-authoritative part of the spec when present, but not required. */
const AGENT_BRIEF_HEADING = "## Agent Brief";
/** The label that gates S0 (a triaged, agent-ready slice). */
const READY_FOR_AGENT_LABEL = "ready-for-agent";

/**
 * Raw shape of `gh issue view --json` we depend on. `gh` always emits these
 * keys for the requested fields; we treat anything missing as the empty case.
 */
export interface GhIssueJson {
  readonly number?: number;
  readonly title?: string | null;
  readonly state?: string | null;
  readonly author?: { readonly login?: string | null } | null;
  readonly user?: { readonly login?: string | null } | null;
  readonly body?: string | null;
  readonly labels?: ReadonlyArray<{ readonly name?: string }> | null;
  readonly comments?: ReadonlyArray<{
    readonly body?: string;
    readonly author?: { readonly login?: string | null } | null;
    readonly user?: { readonly login?: string | null } | null;
  }> | null;
}

/** Native blocked_by dependency summary from `gh api .../dependencies`. */
export interface GhBlockedBy {
  readonly number: number;
  readonly state: string; // "open" | "closed"
}

/** Is the issue labelled ready-for-agent? */
export function isReadyForAgent(json: GhIssueJson): boolean {
  return (json.labels ?? []).some((l) => l.name === READY_FOR_AGENT_LABEL);
}

/**
 * Is the issue itself CLOSED (#2)? gh `--json state` returns "OPEN"/"CLOSED"
 * (upper-case); judge case-insensitively. A missing/odd state ⇒ not closed (the
 * S0 gate only rejects a definitively-closed issue, never an unknown state).
 */
export function isClosedIssue(json: GhIssueJson): boolean {
  // typeof guard (R1 T2 gemini): a malformed / oddly-mocked `state` (number, object)
  // would throw on `.toUpperCase()`; treat any non-string as not-closed.
  return typeof json.state === "string" && json.state.toUpperCase() === "CLOSED";
}

/**
 * Build the S0 {@link IssueMeta} from the gh JSON + the native blocked_by list +
 * the native sub-issue count. The three-way accept condition the runner enforces
 * is derived from these fields (rfa ∧ no sub-issues ∧ all blocked_by closed).
 * The Agent Brief is NOT read here — it is no longer an S0 gate (#328) and the
 * vestigial `hasAgentBrief` metadata was dropped (#329); S1 still writes a
 * contract-complete audit snapshot, while the coder reads the live issue via gh.
 *
 * `openBlockedBy` = the numbers of blocked_by dependencies whose state is not
 * "closed" (an open upstream the slice would otherwise be cut from a stale base
 * against — PRD #244 S0).
 */
export function buildIssueMeta(
  issueNumber: number,
  json: GhIssueJson,
  blockedBy: ReadonlyArray<GhBlockedBy>,
  subIssueCount: number,
): IssueMeta {
  return {
    number: json.number ?? issueNumber,
    isReadyForAgent: isReadyForAgent(json),
    hasSubIssues: subIssueCount > 0,
    isClosed: isClosedIssue(json),
    openBlockedBy: blockedBy
      .filter((d) => d.state !== "closed")
      .map((d) => d.number),
    // #767: body is cheap (unlike comments) and lets S0 parse Coder-Rec.
    ...(typeof json.body === "string" ? { body: json.body } : {}),
  };
}

function actorLogin(
  carrier: {
    readonly author?: { readonly login?: string | null } | null;
    readonly user?: { readonly login?: string | null } | null;
  } | null | undefined,
): string {
  return carrier?.author?.login ?? carrier?.user?.login ?? "";
}

function repoOwnerLogin(repo: string): string {
  return repo.split("/", 1)[0] ?? "";
}

/**
 * Extract the latest trusted `## Agent Brief` from the issue body/comments. Only
 * repo-owner-authored carriers count; among those, later comments supersede
 * earlier comments and the body. Returns "" when no trusted brief is present —
 * that is a valid slice, not an S0 gate.
 */
export function extractAgentBrief(json: GhIssueJson, ownerLogin: string): string {
  // Priority order, LOWEST first: the issue body is the fallback, then comments
  // in order (newest last). A later carrier overwrites an earlier one, so the
  // LAST brief-bearing COMMENT wins over both earlier comments and the body
  // (a re-issued brief supersedes the original) — the body only stands when no
  // comment carries a brief.
  const carriers = [
    { text: json.body ?? "", author: json, sourceKind: "issue body" },
    ...(json.comments ?? []).map((c) => ({
      text: c.body ?? "",
      author: c,
      sourceKind: "issue comment",
    })),
  ];
  let brief = "";
  for (const carrier of carriers) {
    if (!carrier.text.includes(AGENT_BRIEF_HEADING)) continue;
    const sourceCheck = checkExecutableInstructionSource({
      sourceKind: carrier.sourceKind,
      instructionKind: "Agent Brief",
      trustedAuthor: ownerLogin,
      candidateAuthor: actorLogin(carrier.author),
    });
    if (sourceCheck.accepted) {
      brief = carrier.text;
    }
  }
  return brief;
}

export interface ExecutableInstructionSourceCheck {
  readonly accepted: boolean;
  readonly stopSummary?: StopSummary;
  readonly evidence: {
    readonly seam: "source_auth";
    readonly sourceKind: string;
    readonly instructionKind: string;
    readonly trustedAuthor: string;
    readonly candidateAuthor: string;
    readonly rejectedAuthor?: string;
    readonly executableInstructionSourceAccepted: boolean;
  };
}

export function checkExecutableInstructionSource(input: {
  readonly sourceKind: string;
  readonly instructionKind: string;
  readonly trustedAuthor: string;
  readonly candidateAuthor: string;
}): ExecutableInstructionSourceCheck {
  const trusted = input.trustedAuthor.trim();
  const candidate = input.candidateAuthor.trim();
  const accepted =
    trusted.length > 0 && candidate.toLowerCase() === trusted.toLowerCase();
  return {
    accepted,
    ...(accepted
      ? {}
      : {
          stopSummary: sourceAuthFailureStopSummary({
            instructionKind: input.instructionKind,
            rejectedAuthor: candidate,
            trustedAuthor: trusted,
            sourceKind: input.sourceKind,
          }),
        }),
    evidence: {
      seam: "source_auth",
      sourceKind: input.sourceKind,
      instructionKind: input.instructionKind,
      trustedAuthor: trusted,
      candidateAuthor: candidate,
      ...(!accepted ? { rejectedAuthor: candidate } : {}),
      executableInstructionSourceAccepted: accepted,
    },
  };
}

/**
 * Real shape of `gh issue view --json subIssues`:
 * `{"subIssues":{"nodes":[…],"totalCount":N}}` — an OBJECT, not an array
 * (verified against the live #244: `totalCount:10`). The S0 input gate uses this
 * count to reject a parent epic (`hasSubIssues`), so reading it correctly is
 * load-bearing: an array check on the object is always false → count always 0 →
 * the parent-epic gate never fires (PRD #244 US#3 / S0 three-way condition).
 *
 * Prefers `totalCount`, falls back to `nodes.length`, and returns 0 for any
 * missing/malformed value (never NaN/throw — a future gh shape must not crash
 * the gate).
 */
export function parseSubIssueCount(parsed: { subIssues?: unknown }): number {
  const sub = parsed.subIssues;
  if (sub === null || typeof sub !== "object") return 0;
  const obj = sub as { totalCount?: unknown; nodes?: unknown };
  if (typeof obj.totalCount === "number" && Number.isFinite(obj.totalCount)) {
    return obj.totalCount;
  }
  if (Array.isArray(obj.nodes)) return obj.nodes.length;
  return 0;
}

/**
 * Parse the native `blocked_by` dependency list from a CONFIRMED API response
 * (`gh api repos/.../issues/N/dependencies/blocked_by`, a JSON array). Keeps only
 * entries with a numeric `number` + string `state`; tolerates a non-array /
 * malformed value by returning `[]` (a future/odd shape must not crash the gate).
 *
 * IMPORTANT (integ-cmr 256 r2, F2): this is the CONFIRMED-empty path only. The
 * caller does NOT swallow a thrown `gh`/transport error into `[]` — a failed
 * query fails CLOSED (routes to S0 backend error → S8(error)), because returning
 * `[]` on a transient failure would let a blocked-by-open issue slip past the S0
 * gate and run from a stale base missing upstream changes.
 */
export function parseBlockedBy(parsed: unknown): GhBlockedBy[] {
  if (!Array.isArray(parsed)) return [];
  return parsed
    .filter(
      (d): d is { number: number; state: string } =>
        typeof d?.number === "number" && typeof d?.state === "string",
    )
    .map((d) => ({ number: d.number, state: d.state }));
}

/**
 * Build the native metadata block #244 S1 names ("body + comments + 最新 Agent
 * Brief 正文 + native metadata") — title/state/labels + the native sub-issue +
 * blocked_by summaries. S0 already reads these via gh; passing them through into
 * the host-written snapshot keeps the audit/resume artifact contract-complete.
 * The worker's execution context is still the live issue it fetches in-container
 * via gh using the runner-injected issue/repo env.
 */
export function buildIssueSnapshotMeta(
  json: GhIssueJson,
  blockedBy: ReadonlyArray<GhBlockedBy>,
  subIssueCount: number,
): IssueSnapshotMeta {
  return {
    title: json.title ?? "",
    state: json.state ?? "",
    labels: (json.labels ?? []).map((l) => l.name ?? "").filter((n) => n !== ""),
    subIssueCount,
    blockedBy: blockedBy.map((d) => ({ number: d.number, state: d.state })),
  };
}

/**
 * Build the S1 {@link IssueSnapshot}: body + comments + Agent Brief + the
 * #244-named native metadata. The native sub-issue count + blocked_by list S0
 * fetched are threaded in here (not re-queried) so the host-side snapshot is
 * contract-complete (#244 S1 names native metadata as a snapshot element).
 */
export function buildIssueSnapshot(
  issueNumber: number,
  json: GhIssueJson,
  blockedBy: ReadonlyArray<GhBlockedBy>,
  subIssueCount: number,
  ownerLogin: string,
): IssueSnapshot {
  return {
    number: json.number ?? issueNumber,
    body: json.body ?? "",
    bodyAuthorLogin: actorLogin(json),
    comments: (json.comments ?? []).map((c) => c.body ?? ""),
    commentAuthorLogins: (json.comments ?? []).map((c) => actorLogin(c)),
    trustedOwnerLogin: ownerLogin,
    agentBrief: extractAgentBrief(json, ownerLogin),
    nativeMeta: buildIssueSnapshotMeta(json, blockedBy, subIssueCount),
  };
}

// ── clean-room snapshot leak guard (integ-cmr 256 r2, F3) ───────────────────

/**
 * The host-fetched clean-room snapshot file, written into the resident worktree
 * as read-only context for the agent. It must NEVER be committed: with
 * `branchStrategy:{type:'head'}` a coder's `git add -A` would otherwise stage it
 * into the reviewed/pushed branch (polluting the shipped artifact). The Backend
 * git-ignores it (per-worktree `.git/info/exclude`) before any agent run (F3).
 */
export const SNAPSHOT_FILENAME = ".orchestrator-snapshot.json";

/**
 * Idempotently ensure `pattern` is present as its own line in a git
 * `info/exclude` file's content. Returns the new content (existing + the pattern
 * appended on a fresh line) when absent, or the input UNCHANGED when the pattern
 * is already an exact line (so repeated S1 resume writes never duplicate it).
 *
 * Pure (string assembly) so the leak-guard decision is unit-tested without git.
 */
export function ensureExcluded(existing: string, pattern: string): string {
  const lines = existing.split("\n").map((l) => l.trim());
  if (lines.includes(pattern)) return existing;
  // Append on its own line; preserve a trailing newline so the file stays
  // newline-terminated regardless of the prior content's shape.
  const base = existing.length === 0 || existing.endsWith("\n")
    ? existing
    : existing + "\n";
  return `${base}${pattern}\n`;
}

/**
 * The git ref to cut a fresh slice worktree FROM (integ-cmr 256 r3,
 * worktree_base_stale).
 *
 * `ensureBaseRef` runs `git fetch origin <base>`, which updates
 * `refs/remotes/origin/<base>` (and FETCH_HEAD) but does NOT move the local
 * `refs/heads/<base>`. So deriving with the bare local `<base>` could cut from a
 * stale local branch behind upstream — violating #244's "从 main 派生 =
 * up-to-date" invariant and diverging from the spike's explicit
 * `git worktree add … origin/main`. When the fetch succeeded, cut from
 * `origin/<base>` (the just-refreshed remote-tracking ref); only when the fetch
 * failed (offline / a local-only base with no remote) fall back to the local
 * `<base>` so the cut is never blocked.
 *
 * #291 family base: a family base is a LOCAL branch on the dedicated clone (ADR
 * 0022 decision 7) — the merger accumulates each wave's merges onto it, and the
 * next wave's children cut from THAT local branch, NOT `origin/<family-base>`.
 * `localOnly` forces the bare local ref REGARDLESS of `fetchedOk`, so a stale
 * `origin/<family-base>` (e.g. a prior PR's remote branch that still exists, or
 * a `fetch` that happened to resolve it) can never shadow the local family base
 * carrying this run's accumulated waves (agy R1). A standalone single-slice run
 * leaves `localOnly` false, so its `main` cut is byte-identical to before
 * (`origin/main` when fetched, local fallback otherwise).
 *
 * Pure (string assembly) so the ref-selection decision is unit-tested without git.
 */
export function cutRefFor(
  base: string,
  fetchedOk: boolean,
  localOnly = false,
): string {
  if (localOnly) return base;
  return fetchedOk ? `origin/${base}` : base;
}

/**
 * Normalize `git worktree list --porcelain` output for CRLF / trailing-whitespace
 * robustness before parsing. Pure so line-ending handling is unit-tested without git.
 */
export function normalizePorcelainOutput(porcelainOut: string): string {
  return porcelainOut.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

/**
 * Find the worktree path bound to `branch` in `git worktree list --porcelain`
 * output. Porcelain blocks are blank-line-separated; the branch line is exactly
 * `branch refs/heads/<ref>`.
 *
 * Match the branch line EXACTLY — a substring `includes` would let a query for
 * `…issue-12` reuse the worktree of `…issue-123` (shared prefix), causing
 * wrong-worktree reuse and state pollution (gemini R1, high). Pure (string
 * parsing) so the matching is unit-tested without git.
 */
export function matchWorktreeForBranch(
  porcelainOut: string,
  branch: string,
): string | undefined {
  const wanted = `branch refs/heads/${branch}`;
  for (const block of normalizePorcelainOutput(porcelainOut).split("\n\n")) {
    const lines = block.split("\n").map((l) => l.trimEnd());
    if (lines.some((l) => l === wanted)) {
      const wt = lines.find((l) => l.startsWith("worktree "));
      if (wt) return wt.slice("worktree ".length).trim();
    }
  }
  return undefined;
}

/**
 * Recover the issue number from a resident branch name. Prefer the `issue-<n>`
 * token (not anchored to end — a branch may carry a trailing suffix such as
 * `…issue-256-fix`); only when no such token exists fall back to the LAST digit
 * run in the branch.
 *
 * Anchoring `/issue-(\d+)$/` and falling back to the FIRST digit run mis-reads a
 * suffixed branch's epic prefix (e.g. `feat/244-…-issue-256-fix` → 244, not 256)
 * → wrong issue metadata / wrong `.ledger-<n>` dir (gemini R2, high). Pure so
 * the extraction is unit-tested without git. Returns 0 when no digits exist.
 */
/**
 * The resident slice branch name for an issue — the single source of the
 * `feat/issue-<n>` convention `prepareWorktree` cuts under, and the inverse of
 * {@link issueNumberFromBranch}. Exported so the family layer can recover a
 * child's branch from its issue when reconcile is handed only the issue number
 * (#291, agy/codex R1). Pure → unit-tested without git.
 *
 * NEUTRAL prefix (dogfood #327 #1): the earlier `feat/244-orchestrator-issue-<n>`
 * baked in a hardcoded `244` (the #244 epic) — wrong for every other issue, and
 * `issueNumberFromBranch`'s fallback could mis-read that leading run as the issue.
 */
export function branchForIssue(issueNumber: number): string {
  return `feat/issue-${issueNumber}`;
}

/**
 * Ordered list of candidate branch names for a given issue number — current
 * naming convention first (`feat/issue-<n>`), then the prior convention
 * (`feat/244-orchestrator-issue-<n>`, from before PR #365). The fallback
 * supports resume of worktrees cut under the old name: they are reused IN PLACE
 * with no rename or migration. `issueNumberFromBranch` already parses the issue
 * number from either convention, so this list is the single source for lookups
 * that go the OTHER direction (issue → branch name candidates).
 */
export function candidateBranches(issueNumber: number): string[] {
  return [
    `feat/issue-${issueNumber}`,
    `feat/244-orchestrator-issue-${issueNumber}`,
  ];
}

/**
 * Scan `git worktree list --porcelain` output for a resident worktree bound to
 * one of {@link candidateBranches} for `issueNumber`. Returns the first exact
 * branch-line match and how many candidate names were tried (#593 call-count
 * tests). Pure (string parsing) so the fallback strategy is unit-tested without git.
 */
export function scanPorcelainForIssueWorktree(
  porcelainOut: string,
  issueNumber: number,
): {
  worktree: { path: string; branch: string } | undefined;
  matchAttempts: number;
} {
  let matchAttempts = 0;
  for (const branch of candidateBranches(issueNumber)) {
    matchAttempts += 1;
    const path = matchWorktreeForBranch(porcelainOut, branch);
    if (path !== undefined) return { worktree: { path, branch }, matchAttempts };
  }
  return { worktree: undefined, matchAttempts };
}

/** First-match resident worktree for `issueNumber`, if any (#593). */
export function resolveExistingWorktreeFromPorcelain(
  porcelainOut: string,
  issueNumber: number,
): { path: string; branch: string } | undefined {
  return scanPorcelainForIssueWorktree(porcelainOut, issueNumber).worktree;
}

export function issueNumberFromBranch(branch: string): number {
  const m = branch.match(/issue-(\d+)/);
  if (m) return Number(m[1]);
  const all = branch.match(/\d+/g);
  return all ? Number(all[all.length - 1]) : 0;
}

// ── auth-mount path construction (spike contract) ───────────────────────────

/** Where Sandcastle mounts the codex auth dir inside the container. */
export const SANDBOX_CODEX_DIR = "/home/agent/.codex";
/**
 * Where Sandcastle mounts the grok auth dir inside the container (#807).
 * Grok CLI reads credentials from `~/.grok/auth.json` under this tree.
 * The worker image installs a real `/usr/local/bin/grok` binary (not a
 * symlink into this tree) so the bind-mount does not hide PATH.
 */
export const SANDBOX_GROK_DIR = "/home/agent/.grok";
/** OpenCode Go auth is a single read-only file; SQLite/runtime state stays per-container. */
export const SANDBOX_OPENCODE_AUTH_FILE = "/home/agent/.local/share/opencode/auth.json";

export function opencodeAuthMount(home: string): {
  hostPath: string;
  sandboxPath: string;
  readonly: true;
} {
  return {
    hostPath: join(home, ".local", "share", "opencode", "auth.json"),
    sandboxPath: SANDBOX_OPENCODE_AUTH_FILE,
    readonly: true,
  };
}

export function hostOpenCodeAuthFile(home: string): string | undefined {
  const path = opencodeAuthMount(home).hostPath;
  return existsSync(path) ? path : undefined;
}

export function appendOpenCodeAuthMount(
  mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[],
  hostPath: string | undefined,
): void {
  if (hostPath !== undefined) {
    mounts.push({ hostPath, sandboxPath: SANDBOX_OPENCODE_AUTH_FILE, readonly: true });
  }
}

/**
 * Provision optional OpenCode credentials identically in every worker sandbox.
 * Credential validity is established only by the live route smoke.
 */
export function applyUniformCredentialProvisioning(input: {
  env: Record<string, string>;
  mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[];
  opencodeAuthFile?: string;
}): void {
  if (process.env.GLM_KEY !== undefined) input.env.GLM_KEY = process.env.GLM_KEY;
  appendOpenCodeAuthMount(input.mounts, input.opencodeAuthFile);
}
/** Where the baked dev skills are mounted inside the container. */
export const SANDBOX_SKILLS_DIR = "/home/agent/.claude/skills";
/**
 * Env var the v0.1 one-image-two-roles profile reads to ACTIVATE the role's
 * baked soul (ship-pre 256 r1). Both souls are baked into the single image; this
 * tells the entrypoint which one this `run()` is under (#244 "role 决定注哪份
 * soul"). NOT an OS-level readonly mount — the reviewer's READ-ONLY stays a
 * prompt/soul soft constraint (ADR 0017 §4).
 */
export const SANDBOX_SOUL_ENV = "ORCHESTRATOR_SOUL";
/** The issue number handed to the worker; prompt/soul live-fetch the issue via gh. */
export const SANDBOX_ISSUE_NUMBER_ENV = "ORCHESTRATOR_ISSUE_NUMBER";
/** A short alias for tools/skills that conventionally read ISSUE_NUMBER. */
export const SANDBOX_ISSUE_NUMBER_ALIAS_ENV = "ISSUE_NUMBER";
/** GitHub repo slug (`owner/repo`) the worker should use for gh issue reads. */
export const SANDBOX_REPO_ENV = "ORCHESTRATOR_REPO";
/** S5 coder-fix worker path to runner-owned blocking findings JSON. */
export const SANDBOX_FIX_FINDINGS_PATH_ENV = "ORCHESTRATOR_FIX_FINDINGS_PATH";
export const SANDBOX_FIX_FOCUS_PATH_ENV = "ORCHESTRATOR_FIX_FOCUS_PATH";
/** Worker path to the runner-owned machine outcome sidecar JSON. */
export const SANDBOX_OUTCOME_PATH_ENV = "ORCHESTRATOR_OUTCOME_PATH";
/** Optional ship-worker focus file read by the ship prompt before gstack-ship. */
/**
 * The env var the ship worker's in-container `gh` reads for auth (cmr S336 r10).
 * The 2b image BAKES the gh CLI but NO gh auth (a live OAuth secret). gstack-ship
 * Step 17 pushes over https (gh credential helper) + Step 19 runs `gh pr create`,
 * both of which gh authenticates from `GH_TOKEN`. We inject the host token (read via
 * `gh auth token`) as this env var rather than mounting `~/.config/gh`: the host
 * stores its token in the OS keyring, so `hosts.yml` is TOKENLESS and a config-dir
 * mount would carry no usable credential — `GH_TOKEN` is gh's portable env-auth path.
 */
export const SANDBOX_GH_TOKEN_ENV = "GH_TOKEN";

/**
 * Effectively disables sandcastle's per-worker idle timeout (default 600s, which
 * fails the run with "Agent idle for N seconds"). Every observed "hang" so far
 * was the laptop sleeping mid-run or deep-reasoning silence — false fires; real
 * hangs are <1% and are caught manually. Sandcastle has no disable sentinel
 * (`0` would fire immediately; `??` only falls back on null/undefined), so we use
 * ONE WEEK — far longer than any real worker run, so the 600s default is
 * neutralized in practice.
 *
 * Must stay well under the timer limit: sandcastle multiplies idleTimeoutSeconds
 * by 1e3, and the millisecond delay must fit in a signed 32-bit int — Node timers
 * (and the Effect scheduler underneath) clamp anything over 2**31-1 ms, firing
 * IMMEDIATELY instead of waiting (gemini #384 R2: a 1-year value = 31_536_000_000
 * ms OVERFLOWED int32 → the idle timer fired at once, the opposite of "never
 * fires"). 604_800 * 1000 = 604_800_000 ms ≪ 2**31-1, no overflow.
 *
 * #683: when this timer DOES fire (or an external monitor hits idle first),
 * {@link RealBackend.runAgentSandbox} routes through {@link handleIdleThreshold}
 * — probe the worker's pool before hang kill (429 → wait-for-reset, not hang).
 */
export const WORKER_IDLE_TIMEOUT_SECONDS = 604_800;

/**
 * #683 context threaded beside Sandcastle run options for the internal-timeout
 * fallback. The live CLI monitor owns the normal idle disposition.
 * (Sandcastle does not know this field).
 *
 * `workerPid` is optional at the call site — production dispatch paths leave it
 * unset and {@link RealBackend.runAgentSandbox} fills it from the live sandbox
 * handle via {@link RealBackend.noteActiveSandboxWorkerPid}. Callers must not
 * hand-stuff a fake pid; hang kill no-ops on `pid <= 0`.
 *
 * 429 fallback semantic: by the time Sandcastle surfaces
 * `AgentIdleTimeoutError`, `withSandbox` has already released the sandbox. The
 * fallback may park a quota wall, but never owns hang-kill; live worker kills
 * belong exclusively to the #684 monitor handle.
 */
export interface QuotaProbeRunContext {
  /** Model/route slug → {@link import("./quotaProbe.js").poolForModelRef}. */
  readonly modelRef: string;
  readonly step?: StepId;
  /**
   * OS pid of the worker process when known. Prefer leaving unset — production
   * captures it from the sandbox handle mid-run (#684 monitor handle companion).
   */
  readonly workerPid?: number;
  /** Resident worktree path — used to derive sibling `.ledger-<n>` for wait rows. */
  readonly worktreePath?: string;
  readonly issueNumber?: number;
}

/** Sandcastle run options + optional #683 idle quota-probe context. */
export type AgentSandboxRunOptions = Parameters<typeof sc.run>[0] & {
  readonly quotaProbe?: QuotaProbeRunContext;
};

/**
 * Marks the container as an orchestrator-spawned, non-interactive session.
 * gstack-ship reads OPENCLAW_SESSION → its spawned path auto-chooses the
 * recommended option on AskUserQuestion instead of blocking/improvising (the
 * orchestrator's only human touchpoint is structured escalation, never a
 * worker-level prompt). Central set: add future tools' spawned-detection keys here.
 */
export const SPAWNED_WORKER_ENV: Record<string, string> = { OPENCLAW_SESSION: "1" };

/**
 * Build the souls mount spec. Hardcodes the sandbox path once.
 * ALWAYS returns readonly:true so container workers cannot mutate the host
 * souls truth source (the image's baked souls are no longer present; host
 * souls/*.md are the single source of truth).
 * Used at all 6 dispatch sites (RealBackend box/ship + RealFamilyBackend's
 * 4 workers: merger, coder-fix, integrated-cmr, family-ship).
 */
export function soulsMount(soulsDir: string): { hostPath: string; sandboxPath: string; readonly: true } {
  return {
    hostPath: soulsDir,
    sandboxPath: "/home/agent/.orchestrator/souls",
    readonly: true,
  };
}

/**
 * Host paths for the per-issue codex auth copy + the claude token (spike
 * contract). codex auth MUST live under $HOME (colima shares $HOME into the
 * Docker VM; $TMPDIR is NOT shared → a tmp copy mounts root-owned/empty →
 * "Permission denied"). The claude leg uses a durable OAuth token env var, not
 * a mount.
 *
 * Pure: builds the paths only — no file I/O. `mountAuth()` does the copy.
 */
export interface AuthPaths {
  /** Per-issue host dir holding the codex auth.json copy (under $HOME). */
  readonly hostCodexAuthDir: string;
  /** Source codex auth.json on the host. */
  readonly srcCodexAuth: string;
  /** Source codex config.toml on the host (best-effort copy). */
  readonly srcCodexConfig: string;
  /**
   * Per-issue host dir holding the grok auth.json copy (#807; under $HOME so
   * colima can share it into the Docker VM — same constraint as codex).
   */
  readonly hostGrokAuthDir: string;
  /** Source grok auth.json on the host (`~/.grok/auth.json`). */
  readonly srcGrokAuth: string;
  /** Host file holding the durable claude OAuth token. */
  readonly claudeTokenFile: string;
}

export function buildAuthPaths(
  issueNumber: number,
  home: string = homedir(),
): AuthPaths {
  return {
    hostCodexAuthDir: join(home, ".sc-orchestrator", `auth-${issueNumber}`),
    srcCodexAuth: join(home, ".codex", "auth.json"),
    srcCodexConfig: join(home, ".codex", "config.toml"),
    hostGrokAuthDir: join(home, ".sc-orchestrator", `grok-auth-${issueNumber}`),
    srcGrokAuth: join(home, ".grok", "auth.json"),
    claudeTokenFile: join(home, ".sc-claude-token"),
  };
}

// ── #292: dedicated-clone isolation (ADR 0024) path/guard pure logic ─────────

/** Short, stable hex digest used when a clean `owner_repo` slug isn't derivable. */
function shortHash(input: string): string {
  return createHash("sha1").update(input).digest("hex").slice(0, 16);
}

/**
 * Build the repo-slug component of the dedicated-clone path (ADR 0024 decision 1).
 *
 * Preference order, so two distinct sources can never collide on one clone dir:
 *   1. A parseable GitHub remote (https or ssh) → `<owner>_<repo>` (human-readable,
 *      and same-named repos under different owners stay distinct). Restricted to
 *      github.com hosts — for that host the 2-segment `owner/repo` IS the whole
 *      identity, so collision is impossible; any OTHER host (e.g. a GitLab nested
 *      group `groupA/sub/repo` vs `groupB/sub/repo`) shares its last two segments,
 *      so it must hash the FULL remote instead (case 2), never the tail.
 *   2. A remote that isn't a github.com `owner/repo` → a stable hash of the FULL
 *      (trimmed) remote — preserves every distinguishing segment, no collision.
 *   3. NO remote (a local-only source) → a stable hash of the source ABSOLUTE path
 *      (ADR 0024 "无 remote 的本地 source → 退化为 source 绝对路径的 hash"). The
 *      source is resolved to an absolute path FIRST, so the same repo referenced
 *      relatively (from any cwd) maps to one stable clone — crash-resume idempotency.
 *
 * Pure: derives the slug only — no file I/O.
 */
export function repoSlug(sourceRepo: string, remote: string | undefined): string {
  if (remote !== undefined && remote.trim() !== "") {
    const trimmed = remote.trim();
    const parsed = parseOwnerRepo(trimmed);
    if (parsed !== undefined) return `${parsed.owner}_${parsed.repo}`;
    return shortHash(trimmed);
  }
  // Resolve to absolute so `../repo` and `/abs/repo` (same repo, different cwd)
  // hash identically (ADR 0024 dec.1: hash of the source ABSOLUTE path).
  return shortHash(resolve(sourceRepo));
}

/**
 * Extract `{owner, repo}` from an https or ssh **github.com** remote, or
 * undefined for any non-github.com remote. Restricted to github.com on purpose:
 * only there is the 2-segment `owner/repo` the repo's whole identity, so the
 * human-readable `owner_repo` slug is collision-free. A non-github host can carry
 * deeper namespaces (GitLab subgroups: `groupA/sub/repo` vs `groupB/sub/repo`)
 * that share their last two segments — those must NOT slug here; the caller hashes
 * the full remote for them instead.
 */
function parseOwnerRepo(
  remote: string,
): { owner: string; repo: string } | undefined {
  // github.com must be the actual HOST, not a path substring — else a non-github
  // remote that merely embeds `@github.com` / `/github.com` in its PATH (e.g.
  // `https://evil.example/path@github.com/owner/repo.git`) would falsely slug as
  // the genuine github repo and COLLIDE with it (ADR 0024 dec.1, r2 codex). So we
  // anchor the host position in each accepted form, never a loose substring:
  const trailer = "([^/:\\s]+)\\/([^/\\s]+?)(?:\\.git)?\\/?$"; // owner / repo
  const patterns = [
    // scheme://[user[:pass]@]github.com[:port]/owner/repo  (https / ssh / git)
    new RegExp(`^[a-z][a-z0-9+.-]*:\\/\\/(?:[^/@\\s]+@)?github\\.com(?::\\d+)?\\/${trailer}`),
    // scp-like:  [user@]github.com:owner/repo  (no scheme, ':' separates host)
    new RegExp(`^(?:[^/@\\s]+@)?github\\.com:${trailer}`),
  ];
  for (const re of patterns) {
    const m = remote.match(re);
    if (m !== null && m[1] !== "" && m[2] !== "") {
      return { owner: m[1], repo: m[2] };
    }
  }
  return undefined;
}

/**
 * The dedicated-clone path for one orchestrator invocation (ADR 0024 decision 1):
 * `<home>/.sc-orchestrator/<repo-slug>-iso-<runKey>`. Run-key-addressed so the
 * SAME key resumes the SAME clone (idempotent) and DIFFERENT invocations get
 * physically separate clones (their own `.git` ⇒ a prune can't reach across).
 *
 * Pure: composes the path only.
 */
export function clonePathFor(
  home: string,
  slug: string,
  runKey: number,
): string {
  return join(home, ".sc-orchestrator", `${slug}-iso-${runKey}`);
}

/** Verdict for the fail-closed guard (ADR 0024 decision 1 / 3). */
export interface OwnGitDirVerdict {
  readonly ok: boolean;
  /** The raw `git rev-parse --git-common-dir` output, for the error message. */
  readonly commonDir: string;
}

/**
 * Decide whether `git rev-parse --git-common-dir` (run inside the clone) proves
 * the clone owns its `.git` — i.e. is a real clone, NOT a linked worktree sharing
 * another repo's `.git` (ADR 0024 decision 1: 断言作业仓库非 linked worktree).
 *
 * A normal clone's common dir is its own `.git` — git prints it as the literal
 * relative `.git` (run from the repo root) or as the absolute `<clone>/.git`.
 * A linked worktree's common dir points at the SHARED parent repo's `.git`
 * (e.g. `<other>/.git` or `<other>/.git/worktrees/<name>`), which is the topology
 * #292 must reject. Pure: compares strings only.
 */
export function checkOwnGitDir(
  commonDir: string,
  clonePath: string,
): OwnGitDirVerdict {
  const trimmed = commonDir.trim();
  const own =
    trimmed === ".git" ||
    trimmed === join(clonePath, ".git") ||
    trimmed === clonePath; // bare-repo edge: common dir is the repo dir itself
  return { ok: own, commonDir: trimmed };
}

// ── model slug → agent provider selection (role decides soul/CLI) ───────────

// ── role → baked soul selection (ship-pre 256 r1) ───────────────────────────

/**
 * Select the soul a step runs under, consuming {@link StepSpec.soul} so the
 * contract field is NOT dead (ship-pre 256 r1, role-soul wiring).
 *
 * v0.1 = ONE image, TWO roles (ADR 0017 §4 + PRD #244): BOTH the coder soul and
 * the READ-ONLY reviewer soul are BAKED INTO the single profile image
 * ("烤进镜像的 reviewer soul 里写 READ-ONLY 硬约束"), and the soul is SELECTED
 * AT RUNTIME by `role` ("role 决定注哪份 soul ... runner 凭 StepSpec.role 选
 * coder/reviewer soul", issue body). The reviewer's READ-ONLY is a prompt/soul
 * SOFT constraint, NOT an OS-level readonly mount — same image, separate fresh
 * `run()` context (ADR 0017 §4 + Consequences; the runtime hard read-only mount
 * is explicitly deferred to a two-image split, issue body line 108).
 *
 * So the soul is `role`-derived: `coder` → the `"coder"` soul, `reviewer` → the
 * `"READ-ONLY"` soul. The StepSpec ALSO carries an explicit `spec.soul`; this
 * helper VALIDATES the two agree (a reviewer step carrying the coder soul is a
 * misconfigured spec, mirroring how {@link modelIdForSlug} throws on a bad slug).
 * The mismatch throws → the runner's S8(error) edge, never a silently-mis-souled
 * run.
 *
 * Why this closes the finding: previously `spec.soul` was declared in the
 * StepSpec contract and populated in per-run worker specs but NEVER consumed by the real
 * Backend (`grep spec.soul` = no hit) — a dead contract field. Now it is read
 * and asserted at the step's run-setup, so the v0.1 "role 决定注哪份 soul"
 * selection is realised and the field can no longer drift unnoticed.
 *
 * Pure (a check on the role/soul pair): unit-tested without a container.
 */
export function soulForStep(spec: Pick<StepSpec, "role" | "soul">): StepSoul {
  const expected: StepSoul =
    spec.role === "reviewer"
      ? "READ-ONLY"
      : spec.role === "verify"
        ? "verify"
        : spec.role === "fixer"
          ? "fixer"
          : spec.role === "cleanup"
            ? "cleanup"
            : spec.role === "docRelease"
              ? "docRelease"
              : "coder";
  if (spec.soul !== expected) {
    throw new Error(
      `realBackend: step role "${spec.role}" requires the "${expected}" soul ` +
        `but the StepSpec carries "${spec.soul}". v0.1 selects the role soul ` +
        `(live-mounted at /home/agent/.orchestrator/souls per #372) by role ` +
        `(#244 "role 决定注哪份 soul"; ADR 0017 §4 one-image-two-roles); ` +
        `a spec.soul that contradicts its role is misconfigured.`,
    );
  }
  return expected;
}

// ── per-step session id extraction (#256 seam extension) ─────────────────────

/** Minimal slice of Sandcastle's RunResult this Backend reads. */
export interface RunResultLike {
  readonly iterations: ReadonlyArray<{ readonly sessionId?: string }>;
  readonly commits: ReadonlyArray<{ readonly sha: string }>;
  /** The completion signal observed by Sandcastle, if any. */
  readonly completionSignal?: string;
}

/**
 * The real per-step sandbox session id = the LAST iteration's sessionId
 * (the iteration that produced the final output / would be resumed). Both the
 * Claude AND the Codex providers are RESUMABLE and carry a sessionId (sandcastle
 * 0.10: "continue a prior Claude Code, Codex, or Pi conversation"; Codex resumes
 * via `codex exec resume <id>`), so the default Codex coder's escalate → human →
 * resume path returns to the real session, NOT a dead one. Undefined only when an
 * iteration genuinely carried no id (a truly non-resumable provider / capture
 * disabled) — only then does the runner record the run-level UUID fallback.
 */
export function lastSessionId(
  result: Pick<RunResultLike, "iterations">,
): string | undefined {
  for (let i = result.iterations.length - 1; i >= 0; i--) {
    const sid = result.iterations[i]?.sessionId;
    if (sid !== undefined && sid.length > 0) return sid;
  }
  return undefined;
}

// ── coder structured output from stdout (integ-cmr 256 r1) ──────────────────

/**
 * Extract + JSON-parse the LAST `<coder>…</coder>` tag from a coder step's
 * stdout.
 *
 * WHY a stdout tag (not Sandcastle's typed `output`): a coder step runs with
 * `maxIterations = StepSpec.maxIter > 1` (the within-step Ralph retry budget),
 * but Sandcastle's `output` definition REQUIRES `maxIterations === 1`
 * (d.ts: "maxIterations must be 1"). So the coder step cannot use the typed
 * `output` path — `result.output` is `undefined` and `coderOutputSchema.parse`
 * would throw a ZodError on every coder step (the wiring bug this fixes). The
 * coder instead emits its structured result in a `<coder>` tag in stdout, mirroring
 * Sandcastle's own tag-in-stdout extraction (fence-aware JSON unwrapping).
 *
 * The LAST tag wins so a multi-iteration coder reports its FINAL state.
 *
 * Pure: parses a string only — unit-tested without a container. Returns the raw
 * parsed object for {@link RealBackend}'s `decodeOutput` (coderOutputSchema) to
 * validate. Missing tags are advisory compatibility misses; malformed present
 * tags still throw rather than being mistaken for a valid machine outcome.
 */
function extractTaggedJson(
  stdout: string,
  tag: "coder" | "review" | "verify" | "fixer" | "cleanup" | "docRelease",
): unknown | undefined {
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
    const body = stdout.slice(bodyStart, end).trim();
    return parseTaggedJsonBody(body);
  }

  return undefined;
}

function parseTaggedJsonBody(body: string): unknown {
  const stripped = stripJsonFence(body);
  try {
    return JSON.parse(stripped);
  } catch (err) {
    const prefix = balancedJsonPrefix(stripped);
    if (prefix !== undefined && /^[}\]\s]*$/.test(stripped.slice(prefix.length))) {
      return JSON.parse(prefix);
    }
    throw err;
  }
}

function balancedJsonPrefix(s: string): string | undefined {
  let depth = 0;
  let started = false;
  let inString = false;
  let escaped = false;
  for (let i = 0; i < s.length; i += 1) {
    const ch = s[i]!;
    if (!started) {
      if (/\s/.test(ch)) continue;
      if (ch !== "{" && ch !== "[") return undefined;
      started = true;
      depth = 1;
      continue;
    }
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === "\"") {
        inString = false;
      }
      continue;
    }
    if (ch === "\"") {
      inString = true;
    } else if (ch === "{" || ch === "[") {
      depth += 1;
    } else if (ch === "}" || ch === "]") {
      depth -= 1;
      if (depth === 0) return s.slice(0, i + 1);
      if (depth < 0) return undefined;
    }
  }
  return undefined;
}

export function extractCoderTag(stdout: string): unknown | undefined {
  return extractTaggedJson(stdout, "coder");
}

function extractReviewerTag(stdout: string): unknown | undefined {
  return extractTaggedJson(stdout, "review");
}

function extractRoleReceipt(stdout: string, role: StepSpec["role"]): unknown | undefined {
  try {
    return role === "coder"
      ? extractCoderTag(stdout)
      : role === "reviewer"
        ? extractReviewerTag(stdout)
        : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Read a runner-owned worker outcome sidecar.
 *
 * Missing/blank means "legacy worker did not write the new protocol file yet" and
 * callers may fall back to their old stdout/typed-output path. A non-blank file is
 * the machine protocol truth and must parse as JSON; malformed JSON throws rather
 * than falling back to human-readable stdout.
 */
export function readWorkerOutcomeSidecar(path: string | undefined): unknown | undefined {
  return readOutcomeSidecar(path);
}

/**
 * Unwrap a ```json … ``` (or bare ``` … ```) fenced code block to its inner
 * payload, mirroring Sandcastle's fence-aware tag extraction. Returns the input
 * unchanged when it is not fenced.
 */
export function stripJsonFence(s: string): string {
  return stripOutcomeJsonFence(s);
}

/** The self-reported coder JSON a step emits (already shape-validated). */
export interface SelfReportedCoder {
  readonly committed: boolean;
  readonly commitsAdded: number;
  readonly escalate?: { readonly reason: string; readonly diagnosis: string };
  readonly repairEvidence?: RepairEvidence;
}

/**
 * Parse a persisted JSONL ledger (`steps.jsonl` contents) into entries —
 * FAIL-CLOSED on corruption (integ-cmr 256 r5, high).
 *
 * The ledger is the #244 resume truth, so its truncation-recovery rule must be
 * explicit and bounded, NOT an implicit "skip whatever doesn't parse":
 *
 *   - Blank / whitespace-only lines (trailing newline, an interior empty line)
 *     carry no record and are skipped — the ONLY tolerated drift. A file that is
 *     empty or all-blank yields `[]`: a legitimately EMPTY ledger (the documented
 *     `ResumeState.ledger = []` ⇒ fresh-run case), NOT corruption.
 *   - Any NON-EMPTY line that does not `JSON.parse` means the ledger is CORRUPT.
 *     We throw rather than skip the line, because skipping silently rewrites the
 *     resume decision: a dropped tagged S8(error) leaves S7 as the surviving last
 *     entry → planResume routes S7→{handoff,success} → an ERROR run is re-reported
 *     as SUCCESS; and an all-corrupt file collapsing to `[]` would be read as "no
 *     progress" and re-run fresh-from-S0 over a RESIDENT branch that still carries
 *     prior commits. Both are wrong terminal-state / branch-progress rebuilds.
 *
 * The throw propagates out of {@link RealBackend.findResumeState} to the runner's
 * S8(error) bail — fail closed, exactly as the r2 F2 rule (a completeness failure
 * must not become a lenient default) requires.
 *
 * Pure (string scan) so the corrupt-ledger boundary is unit-tested without the
 * filesystem.
 */
/**
 * Valid child step ids (S0–S8). A persisted ledger record must carry one of these in
 * `step`: {@link planResume} dereferences canonical steps to route the resume;
 * a retry marker has its own validated shape and is retained as durable retry
 * accounting rather than treated as a route target.
 */
const STEP_IDS: ReadonlySet<string> = new Set([
  "S0",
  "S1",
  "S2",
  "S3",
  "S4",
  "S5",
  "S6",
  "S7",
  "S8",
]);

const MECHANICAL_REDISPATCH_ATTEMPT = "mechanical_redispatch_attempt";

/**
 * A parsed JSONL record is a usable ledger entry only if it is a non-null object
 * whose `step` is a valid {@link StepId}, or a well-formed #824 mechanical
 * redispatch marker. (`output` / `handoffStatus` are optional, so the minimal
 * canonical entry is `{step}`.)
 *
 * sessionId (when present) must be string — explicit null / non-string is
 * corrupt. This is the parse-boundary guard that prevents raw JSON null from
 * flowing through to resumeSessionId in DispatchContext / resumeFor / backend
 * (addresses the deserial path for #709 resumeSessionId sites).
 *
 * escalationKind (when present) must be string — explicit null / non-string is
 * corrupt. This closes the documented #709 exemption site at planResume: the
 * `!== undefined` (vs != null) distinction between absent=legacy-untagged vs
 * present=tagged (even if unknown value) is only safe once the parse boundary
 * enforces it (intent-verified is not boundary-enforced until now; symmetric
 * to the sessionId fix).
 *
 * A line such as `null`, `{}`, `42`, or `{"step":"S99"}`
 * `JSON.parse`s fine yet is NOT a ledger entry. Without this guard such a record
 * flows into `findResumeState` → `planResume`, where `lastEntry.step` is read
 * OUTSIDE any catch — a `null`/`{}` last entry crashes raw (TypeError /
 * undefined route) instead of the promised fail-closed S8(error). A
 * shape-invalid record is the same corruption class as an unparseable line.
 */
function isLedgerEntryShape(
  value: unknown,
): value is ResumeState["ledger"][number] {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const step = (value as { step?: unknown }).step;
  if (typeof step !== "string") return false;
  if (step === MECHANICAL_REDISPATCH_ATTEMPT) {
    const marker = value as {
      event?: unknown;
      forStep?: unknown;
      mechanicalRedispatchAttempt?: unknown;
    };
    if (
      marker.event !== MECHANICAL_REDISPATCH_ATTEMPT ||
      typeof marker.forStep !== "string" ||
      !STEP_IDS.has(marker.forStep) ||
      typeof marker.mechanicalRedispatchAttempt !== "number" ||
      !Number.isSafeInteger(marker.mechanicalRedispatchAttempt) ||
      marker.mechanicalRedispatchAttempt < 1
    ) {
      return false;
    }
  } else if (!STEP_IDS.has(step)) {
    return false;
  }
  const sid = (value as { sessionId?: unknown }).sessionId;
  if (sid !== undefined && typeof sid !== "string") return false;
  const ek = (value as { escalationKind?: unknown }).escalationKind;
  if (
    ek !== undefined &&
    (typeof ek !== "string" || (ek !== "decision" && ek !== "failure"))
  )
    return false;
  return true;
}

export function parseLedgerJsonl(raw: string): ResumeState["ledger"] {
  const entries: Array<ResumeState["ledger"][number]> = [];
  for (const line of raw.split("\n")) {
    if (line.trim().length === 0) continue; // blank line: no record, tolerated.
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      // A non-empty line that does not parse = corrupt ledger. Fail closed:
      // never skip it (would silently change the resume terminal state / branch
      // progress) and never collapse to an empty ledger.
      throw new Error(
        "corrupt ledger: a non-empty steps.jsonl line failed to parse — " +
          "refusing to resume on a partially-readable ledger (fail closed). " +
          "Skipping the line could re-report an ERROR run as SUCCESS or " +
          "re-run a resident branch fresh-from-S0; bailing to S8(error) instead.",
      );
    }
    // A line can JSON.parse yet not be a usable ledger entry (null / {} / a
    // primitive / a bad step id). Treat it as the SAME corruption: skipping or
    // accepting it would let planResume deref `lastEntry.step` on a non-entry
    // (raw crash) or route on an invalid step instead of failing to S8(error).
    if (!isLedgerEntryShape(parsed)) {
      throw new Error(
        "corrupt ledger: a steps.jsonl line parsed but is not a valid ledger " +
          "entry (must be an object with a valid child step S0–S8) — refusing to " +
          "resume on a malformed ledger (fail closed). Accepting it could crash " +
          "the resume route or re-report the wrong terminal state; bailing to " +
          "S8(error) instead.",
      );
    }
    entries.push(parsed);
  }
  return entries;
}

// ── resumeSession fallback decision (#256/#285) ─────────────────────────────

/**
 * Decide how to recover when `resumeSession` of a prior session fails because
 * the session is dead/missing (Sandcastle cannot resume a session whose JSONL is
 * gone — a pruned container, a cleaned host store).
 *
 * - A dead-session error (no resumable session) means the original session is
 *   gone → fall back to a FRESH `run()` (lose in-session memory, keep the
 *   committed worktree progress — the resident branch survives).
 * - Every other error (completion-signal mismatch, schema/structured-output
 *   parse failure, auth/model failure) propagates to
 *   S8(error). It must not be masked by a fresh run.
 *
 * Pure: classifies the error only; the caller performs the chosen recovery.
 */
export type ResumeRecovery =
  | { readonly kind: "fresh-run" }
  | { readonly kind: "propagate" };

export function classifyResumeError(err: unknown): ResumeRecovery {
  const message = err instanceof Error ? err.message : String(err);
  const isDeadSession =
    /\bresumeSession\b.*\b(not found|missing|expired|dead)\b/i.test(message) ||
    /\bSession resume failed:\s*session\s+\S+\s+(not found|missing|expired|dead)\b/i.test(message) ||
    /\bresume session\b.*\b(not found|missing|expired|dead)\b/i.test(message) ||
    /\bsession\s+(not found|missing|expired|dead)\b/i.test(message) ||
    /\b(no|missing|expired|dead)\s+(resume\s+)?session\b/i.test(message);
  if (isDeadSession) {
    return { kind: "fresh-run" };
  }
  return { kind: "propagate" };
}

// ── failedStep attribution (codex#3) ─────────────────────────────────────────

/**
 * codex#3 — attribute a thrown error to the step that produced it, for the
 * US#30 error package. The runner already labels `failedStep` from its own
 * switch; this helper covers the Backend-internal multi-phase steps where one
 * Backend method spans several sub-operations and the FIRST failing sub-op
 * should name the failure (so "S1 failed" is refined to "S1: prepareWorktree").
 *
 * Pure string assembly so it is unit-tested without any I/O.
 */
export function attributeFailure(
  step: StepId,
  phase: string,
  err: unknown,
): Error {
  let cause = err instanceof Error ? err.message : String(err);
  // execFileSync throws an Error whose `.message` is just "Command failed: …";
  // the actionable detail (gh GraphQL error, git reject/conflict) lives on
  // `.stderr`. Append it so the S8(error) package shows the real cause rather
  // than an opaque "Command failed" (gemini R2).
  if (err && typeof err === "object" && "stderr" in err) {
    const stderr = String((err as { stderr: unknown }).stderr).trim();
    if (stderr) cause += `\nstderr: ${stderr}`;
  }
  return new Error(`${step}:${phase} — ${cause}`);
}

// ── promptsDir validation (integ-cmr 256 r2, F4) ─────────────────────────────

/**
 * Every versioned promptFile a child WORKER dispatches resolves
 * at run time. The real Backend resolves each as `join(promptsDir, promptFile)`,
 * so all must exist under `promptsDir` or the real path cannot run end-to-end
 * (#256 AC "对一个真叶子 issue 端到端跑通").
 *
 * Route-independent prompt inventory: prompt validation must not import a
 * route-bearing StepSpec snapshot, because model routes are resolved per run.
 * Keep this derived from the S2/S3/S5/S6 prompt table. Family endgame prompts
 * are validated by RealFamilyBackend.
 */
export const REFERENCED_PROMPT_FILES: ReadonlyArray<string> = [
  ...new Set(Object.values(WORKER_PROMPT_FILES)),
];

/**
 * Build the construction-time `promptsDir` validation error message, or
 * `undefined` when the dir is valid (integ-cmr 256 r2, F4).
 *
 * `promptsDir` MUST be absolute: Sandcastle resolves `promptFile` against
 * `process.cwd()`, NOT the run's `cwd` option (index.d.ts), so a relative
 * `promptsDir` would silently resolve the prompt against the wrong directory at
 * run time — a latent footgun. It must also exist and contain every
 * {@link REFERENCED_PROMPT_FILES} entry, so the real path can actually run
 * end-to-end instead of throwing deep in the first `sandbox.run()`.
 *
 * Pure: the caller supplies the absoluteness verdict + the list of missing
 * files (from fs), so the message assembly is unit-tested without any I/O.
 */
export function promptsDirError(
  promptsDir: string,
  isAbsolute: boolean,
  dirExists: boolean,
  missingFiles: ReadonlyArray<string>,
): string | undefined {
  if (!isAbsolute) {
    return (
      `RealBackend: promptsDir must be an ABSOLUTE path (got "${promptsDir}"). ` +
      `Sandcastle resolves promptFile against process.cwd(), not the run cwd, ` +
      `so a relative promptsDir would resolve prompts against the wrong dir.`
    );
  }
  if (!dirExists) {
    return `RealBackend: promptsDir "${promptsDir}" does not exist.`;
  }
  if (missingFiles.length > 0) {
    return (
      `RealBackend: promptsDir "${promptsDir}" is missing required promptFile(s): ` +
      `${missingFiles.join(", ")}. All of [${REFERENCED_PROMPT_FILES.join(", ")}] ` +
      `must be present (S2 coder, S3/S6 reviewer, and S5 coder-fix reference them).`
    );
  }
  return undefined;
}

/**
 * The complete set of soul files that must exist under soulsDir.
 * Source of truth = every file under orchestrator/image/souls (no longer baked
 * into the image post #372; the ctor must verify presence so an incomplete/wrong
 * dir (e.g. pointing at image/ or a partial checkout) fails fast with names,
 * mirroring promptsDir validation. Family workers share this image inventory,
 * so docRelease/verify/fixer/ship souls remain required here.
 * cleanup has no soul file (deterministic path, not a runStep agent).
 */
export const REQUIRED_SOUL_FILES: ReadonlyArray<string> = [
  "cmr.md",
  "cmr_completeness.md",
  "cmr_correctness.md",
  "coder.md",
  "docRelease.md",
  "fixer.md",
  "merger.md",
  "output_protocol.md",
  "reviewer.md",
  "ship.md",
  "verify.md",
];

/**
 * Build the construction-time `soulsDir` validation error message, or
 * `undefined` when the dir is valid (#372).
 *
 * soulsDir MUST be absolute + exist + be a directory + contain every
 * {@link REQUIRED_SOUL_FILES} (all files under image/souls). Pure so the message
 * logic is unit-testable without I/O; the validate* wrapper supplies the fs
 * verdicts. Mirrors {@link promptsDirError}.
 */
export function soulsDirError(
  soulsDir: string,
  isAbs: boolean,
  dirExists: boolean,
  missingFiles: ReadonlyArray<string>,
): string | undefined {
  if (typeof soulsDir !== "string" || soulsDir.length === 0) {
    return (
      "RealBackend: soulsDir is required (souls are no longer baked into the image; " +
        "a missing soulsDir would yield soul-less container workers with no fallback)."
    );
  }
  if (!isAbs) {
    return `RealBackend: soulsDir must be an absolute path to an existing directory (got "${soulsDir}").`;
  }
  if (!dirExists) {
    return `RealBackend: soulsDir must be an absolute path to an existing directory (got "${soulsDir}").`;
  }
  if (missingFiles.length > 0) {
    return (
      `RealBackend: soulsDir "${soulsDir}" is missing required soul file(s): ` +
      `${missingFiles.join(", ")}. All of [${REQUIRED_SOUL_FILES.join(", ")}] ` +
      `must be present (every file under image/souls, incl. output_protocol.md and docRelease.md).`
    );
  }
  return undefined;
}

function toolchainVersionCommand(tool: string): string[] {
  if (tool === "typescript") return ["tsc", "--version"];
  return [tool, "--version"];
}

// ════════════════════════════════════════════════════════════════════════════
// Container glue (MANUAL smoke; not in the zero-container automated suite)
// ════════════════════════════════════════════════════════════════════════════

/** Tunables for the real Backend (host paths + the profile image). */
export interface RealBackendOptions {
  /** Enable Codex priority processing for every in-container Codex leg. */
  readonly codexFast?: boolean;
  /**
   * The SOURCE repo the orchestrator clones from (ADR 0024 decision 1). The
   * driver feeds the source — NOT a ready-made working repo. RealBackend builds
   * and holds its OWN dedicated clone keyed by {@link RealBackendOptions.runKey},
   * and that clone (not this source) is what the resident slice worktrees are cut
   * from. May be a path to a local repo (the common case) or any `git clone`-able
   * URL. The clone is what isolates one orchestrator invocation from every other
   * (its own `.git` ⇒ a worktree prune can't reach across sessions).
   */
  readonly sourceRepo: string;
  /**
   * The repo's git remote URL, used ONLY to derive a collision-free clone-path
   * slug (`<owner>_<repo>` for a GitHub remote; a hash otherwise). When absent
   * (a local-only source with no remote), the slug degrades to a hash of the
   * source absolute path (ADR 0024: 无 remote 的本地 source → source 绝对路径 hash).
   */
  readonly remote?: string;
  /**
   * The DETERMINISTIC run key that addresses this invocation's dedicated clone
   * (ADR 0024 decision 1). Family run = the parent epic issue number; single-slice
   * run = the slice's own issue number. MUST be deterministic (never random): a
   * crash-resume re-derives the SAME clone path from the same key, so the prior
   * ledger + resident worktree are found. A family run's child slices REUSE the
   * family clone by passing the parent epic# here (they only differ in the issue#
   * they cut a worktree for), so their local commits live in the one family clone
   * the merger later reads.
   */
  readonly runKey: number;
  /** GitHub repo slug for `gh` (`owner/name`). */
  readonly repo: string;
  /**
   * Login allowed to author trusted `## Agent Brief` sections. Defaults to the
   * owner segment of {@link RealBackendOptions.repo}; kept separate so the trust
   * source can grow into an allowlist later without changing parser callers.
   */
  readonly ownerLogin?: string;
  /** The profile image (#253): toolchain + skills + model CLIs baked in. Souls mounted live (#372). */
  readonly imageName: string;
  /**
   * Dir holding the versioned child promptFiles (`coder_implement.md` for S2,
   * `reviewer_review.md` for S3/S6 and `coder_fix.md` for S5).
   * ADR 0030 keeps the child review/fix loop runner-visible: S3/S6
   * are reviewer workers, and S5 is the coder-fix worker.
   *
   * MUST be an ABSOLUTE path (validated at construction, F4): Sandcastle
   * resolves `promptFile` against `process.cwd()`, NOT the run `cwd` option
   * (index.d.ts), so a relative `promptsDir` would silently resolve the prompt
   * against the wrong directory at run time. The dir must exist and contain every
   * {@link REFERENCED_PROMPT_FILES} entry, or the constructor throws.
   */
  readonly promptsDir: string;
  /**
   * Host dir containing souls (coder.md etc + output_protocol.md) to bind-mount
   * into the container at /home/agent/.orchestrator/souls . #372: souls are
   * mounted live (rather than baked) so source edits take effect on next dispatch
   * without a full image layer change for data files.
   * REQUIRED: souls are no longer baked into the image.
   */
  readonly soulsDir: string;
  /** Override $HOME for auth path construction (tests). */
  readonly home?: string;
  /**
   * #291: the LOCAL family base branch on this clone (ADR 0022 decision 7), set
   * ONLY when this Backend drives a family run's CHILD slices. When a child's
   * `prepareWorktree` base equals this, the slice is cut from the LOCAL family
   * base (no `git fetch origin`, no `origin/` prefix) — because the family base
   * is a local branch the merger accumulates onto, with no remote counterpart;
   * deriving it as `origin/<family-base>` would cut from a stale/absent remote ref
   * missing the prior waves (agy R1). Absent is retained only for the child-machine
   * harness and focused single-slice tests: the cut base is "main", fetched + cut
   * as `origin/main`.
   */
  readonly familyBase?: string;
}

/**
 * zod schema for the reviewer step's structured output (route() consumes it).
 *
 * #604 slice 4 (ADR 0062): the reviewer contract no longer carries routing
 * disposition kinds — the only disposition a reviewer may emit is the
 * accepted-suppression governance carrier.
 */
const findingRepairScopeSchema = z
  .object({
    identityKeys: z.array(z.string()).optional(),
    locations: z.array(z.string()).optional(),
    categories: z.array(z.string()).optional(),
    findingGroup: z.string().optional(),
    reviewContext: z.string().optional(),
    featureArea: z.string().optional(),
  })
  .strict();
const repairEvidenceSchema = z
  .object({
    findingScope: findingRepairScopeSchema,
    changedFiles: z.array(z.string().min(1)).optional(),
    tests: z.array(z.string().min(1)).optional(),
    fixtures: z.array(z.string().min(1)).optional(),
    sameClassBugScan: z.string().min(1).optional(),
    introducedRegressionCheck: z.string().min(1).optional(),
    patchSummary: z.string().optional(),
  })
  .superRefine((value, ctx) => {
    if (
      (value.changedFiles?.length ?? 0) === 0 &&
      (value.tests?.length ?? 0) === 0 &&
      (value.fixtures?.length ?? 0) === 0
    ) {
      ctx.addIssue({
        code: "custom",
        message:
          "repairEvidence requires changedFiles, tests, or fixtures; patchSummary alone is not concrete repair evidence",
      });
    }
  })
  .strict();
const coderOutputSchema = z.object({
  committed: z.boolean(),
  commitsAdded: z.number().int().nonnegative(),
  repairEvidence: repairEvidenceSchema.optional(),
  escalate: z
    .object({
      reason: z.string(),
      diagnosis: z.string(),
    })
    .optional(),
});

// Typed extraction may locate a receipt, but it must not judge the receipt
// before decodeOutput gets the independent decision-bell probe.
const workerReceiptSchema = z.unknown();

/** Parse a coder worker self-report with the same schema the single-slice path uses. */
export function parseCoderSelfReport(raw: unknown): SelfReportedCoder {
  return coderOutputSchema.parse(raw);
}

/**
 * #884 bare-ping wall budget (seconds). Owner target is ~5–10s total across
 * parallel legs; per-leg ceiling defaults to 60s so a single hung provider
 * still fails closed rather than sleeping the driver for minutes.
 *
 * Tunable via `ORCHESTRATOR_SMOKE_IDLE_SECONDS` (positive integer). Name kept
 * for env-compat with the pre-#884 sandcastle idle knob.
 */
const DEFAULT_ROUTE_SMOKE_IDLE_TIMEOUT_SECONDS = 60;

/** Hard upper bound the resolver enforces (same 32-bit-safe ceiling as before). */
const MAX_ROUTE_SMOKE_IDLE_TIMEOUT_SECONDS = 2_147_483;

/**
 * Resolve the bare-ping per-leg wall budget (seconds). Illegal / missing values
 * fall back to the default.
 */
export function resolveRouteSmokeIdleTimeoutSeconds(
  envValue: string | undefined,
): number {
  if (envValue === undefined) return DEFAULT_ROUTE_SMOKE_IDLE_TIMEOUT_SECONDS;
  const trimmed = envValue.trim();
  if (trimmed === "") return DEFAULT_ROUTE_SMOKE_IDLE_TIMEOUT_SECONDS;
  const parsed = Number(trimmed);
  if (
    !Number.isInteger(parsed) ||
    parsed < 1 ||
    parsed > MAX_ROUTE_SMOKE_IDLE_TIMEOUT_SECONDS
  ) {
    return DEFAULT_ROUTE_SMOKE_IDLE_TIMEOUT_SECONDS;
  }
  return parsed;
}

export class RealBackend implements Backend {
  private readonly opts: RealBackendOptions;
  private readonly ownerLogin: string;
  private readonly preflightedToolchains = new Set<string>();
  private readonly inFlightToolchainPreflights = new Map<string, Promise<void>>();
  /**
   * The dedicated clone this invocation owns (ADR 0024). All resident slice
   * worktrees are cut from HERE, and every internal git/Sandcastle op anchors on
   * it — NOT on {@link RealBackendOptions.sourceRepo}. Derived in the constructor
   * from `<home>/.sc-orchestrator/<repo-slug>-iso-<runKey>`, built (or reused) on
   * disk, and guarded to be an independent `.git` before construction succeeds.
   */
  private readonly workingRepo: string;

  constructor(opts: RealBackendOptions) {
    this.opts = opts;
    this.ownerLogin = opts.ownerLogin ?? repoOwnerLogin(opts.repo);
    this.validatePromptsDir();
    this.validateSoulsDir();
    this.workingRepo = this.buildOrReuseClone();
    this.assertIndependentClone();
  }

  /**
   * #786: install this backend's fingerprints immediately before an absent
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
   * The dedicated-clone path this invocation works in (ADR 0024). Exposed so the
   * driver / tests can see WHERE the resident worktrees are cut from; internally
   * every git op anchors on it instead of the driver-supplied source.
   */
  workingRepoPath(): string {
    return this.workingRepo;
  }

  /**
   * #685/#884: report host CLI versions for smoke TTL invalidation. Cheap
   * `--version` only — not a live model call.
   */
  async currentCliVersions(
    route: ResolvedModelRoute,
    billingPool?: string,
    relaySmokeEntryKey?: string,
  ): Promise<Readonly<Record<string, string | undefined>>> {
    const dispatchPool = isBillingPoolDispatchId(billingPool) ? billingPool : undefined;
    const versions: Record<string, string | undefined> = {};
    for (const entry of routeSmokeEntries(route)) {
      // #884: key by entry.key so pool-rewritten pipes don't share a slug bucket
      // with the default-provider entry (same class of aliasing as smoke uniqueness).
      if (versions[entry.key] === undefined) {
        versions[entry.key] = this.cliVersionForSlug(
          entry.slug,
          entry.key === relaySmokeEntryKey ? dispatchPool : undefined,
        );
      }
    }
    return versions;
  }

  /**
   * #884 bare-ping route smoke: one-shot host CLI per unique model×pipe, empty
   * cwd, no docker/repo/tool loop. Nonce echo in stdout is the credential
   * oracle. Unique legs run in parallel via {@link smokeRouteModels}.
   * Tool-capability verification is intentionally out of the ignition path.
   */
  async smokeModelRoute(
    route: ResolvedModelRoute,
    currentCliVersions: Readonly<Record<string, string | undefined>> = {},
    billingPool?: string,
    relaySmokeEntryKey?: string,
  ): Promise<ResolvedModelRoute> {
    void currentCliVersions;
    const dispatchPool = isBillingPoolDispatchId(billingPool) ? billingPool : undefined;
    const timeoutMs =
      resolveRouteSmokeIdleTimeoutSeconds(
        process.env.ORCHESTRATOR_SMOKE_IDLE_SECONDS,
      ) * 1000;
    const providerAuth = this.hostProviderAuthAvailability();
    // #879 / #861 D: each model×pipe smoke is the orchestrator-owned
    // encapsulation of a CMR/route *leg*. Transient transport blips
    // (reset/5xx) retry ×2 before the smoke is recorded failed (optional
    // legs then degrade; required anchors can still abort the run); 429 /
    // quota never retries — via withLegTransientRetry (production wire of
    // legTransientRetry.ts). Worker-process crashes stay on #598; in-container
    // ak-cross-m-review skill legs keep their own backend degrade chain.
    const pingOne = async (
      entry: { readonly key: string; readonly slug: string },
      entryPool: BillingPoolDispatchId | undefined,
    ): Promise<{ readonly cliVersion: string }> => {
      const resolved = resolveModelSlugForPool(entry.slug, entryPool);
      this.assertProviderAuth(entry.slug, entryPool, providerAuth);
      const nonce = randomUUID();
      const prompt = buildBarePingPrompt(
        nonce,
        loadBarePingPromptTemplate(this.opts.promptsDir),
      );
      const built = barePingArgv(resolved.provider, resolved.model, prompt);
      const emptyDir = mkdtempSync(join(tmpdir(), "route-smoke-ping-"));
      try {
        const stage = `smoke-k:${entry.slug}`;
        const stdout = await withLegTransientRetry(async () =>
          this.execBarePing({
            slug: entry.slug,
            cwd: emptyDir,
            prompt,
            nonce,
            file: built.file,
            args: built.args,
            stdin: built.input,
            timeoutMs,
          }),
        );
        if (!barePingNonceSatisfied(stdout, nonce)) {
          throw new Error(
            `bare ping nonce missing for ${entry.slug} at stage ${stage}`,
          );
        }
        return { cliVersion: this.cliVersionForSlug(entry.slug, entryPool) };
      } finally {
        rmSync(emptyDir, { recursive: true, force: true });
      }
    };

    // Pool-rewritten pipe: dedicated ping for the relay entry so a same-slug
    // default-provider result is never alias-passed as pool-smoked. Launch IN
    // PARALLEL with unique-slug legs (P5 / #884 cmr r7) — never serialize after
    // the full smoke wave (adds a whole timeout/retry budget before dispatch).
    const relayEntry =
      relaySmokeEntryKey !== undefined && dispatchPool !== undefined
        ? routeSmokeEntries(route).find((e) => e.key === relaySmokeEntryKey)
        : undefined;
    const relayPingPromise =
      relayEntry !== undefined
        ? pingOne(relayEntry, dispatchPool).then(
            (result) =>
              ({ ok: true as const, result, at: new Date().toISOString() }),
            (error: unknown) =>
              ({ ok: false as const, error, at: new Date().toISOString() }),
          )
        : undefined;

    // Unique-by-slug parallel legs (owner "六路") — always default pipe.
    // Pool credentials for relaySmokeEntryKey are covered ONLY by the dedicated
    // parallel relayPingPromise below (cmr r8: never let unique-wave pool ping
    // fan out as "default pipe passed").
    let smoked = await smokeRouteModels(route, async (entry) => {
      void entry;
      return pingOne(entry, undefined);
    });

    if (relayEntry !== undefined && relayPingPromise !== undefined) {
      const relayOutcome = await relayPingPromise;
      if (relayOutcome.ok) {
        smoked = {
          ...smoked,
          smoke: {
            ...smoked.smoke,
            [relayEntry.key]: {
              state: "passed",
              at: relayOutcome.at,
              cliVersion: relayOutcome.result.cliVersion,
            },
          },
        };
      } else {
        const err = relayOutcome.error;
        smoked = {
          ...smoked,
          smoke: {
            ...smoked.smoke,
            [relayEntry.key]: {
              state: "failed",
              at: relayOutcome.at,
              error: err instanceof Error ? err.message : String(err),
            },
          },
        };
      }
    }
    return smoked;
  }

  /**
   * Host-side bare-ping exec seam. `protected` so tests inject a scripted
   * responder without launching real model CLIs. Production uses
   * {@link execFileAsyncWithTimeout} so parallel smoke actually overlaps.
   */
  protected async execBarePing(input: {
    readonly slug: string;
    readonly cwd: string;
    readonly prompt: string;
    readonly nonce: string;
    readonly file: string;
    readonly args: readonly string[];
    readonly stdin?: string;
    readonly timeoutMs: number;
  }): Promise<string> {
    return execFileAsyncWithTimeout(input.file, input.args, {
      stage: `smoke-k:${input.slug}`,
      timeoutMs: input.timeoutMs,
      cwd: input.cwd,
      input: input.stdin,
      env: this.barePingEnvironment(),
    });
  }

  /** Host auth view used by bare-ping CLIs, aligned with worker auth sources. */
  private barePingEnvironment(): NodeJS.ProcessEnv {
    const home = this.opts.home ?? homedir();
    const env: NodeJS.ProcessEnv = { ...process.env, HOME: home };
    delete env.CLAUDE_CODE_OAUTH_TOKEN;
    try {
      const claudeToken = readFileSync(
        join(home, ".sc-claude-token"),
        "utf8",
      ).trim();
      if (claudeToken !== "") {
        env.CLAUDE_CODE_OAUTH_TOKEN = claudeToken;
      }
    } catch {
      // Missing Claude auth is rejected by assertProviderAuth before its ping.
    }
    return env;
  }

  /**
   * Lightweight host credential presence for bare-ping auth gates — no
   * per-issue temp copy (those are for container mounts only).
   */
  protected hostProviderAuthAvailability(): ProviderAuthAvailability {
    const home = this.opts.home ?? homedir();
    let claude = false;
    try {
      const token = readFileSync(join(home, ".sc-claude-token"), "utf8").trim();
      claude = token.length > 0;
    } catch {
      claude = false;
    }
    const grok = existsSync(join(home, ".grok", "auth.json"));
    return { claude, grok };
  }

  private cliVersionForSlug(slug: string, billingPool?: string): string {
    const provider = resolveModelSlugForPool(
      slug,
      isBillingPoolDispatchId(billingPool) ? billingPool : undefined,
    ).provider;
    // Keep CLI binary identity aligned with barePingArgv / Sandcastle.
    const command =
      provider === "claudeCode"
        ? "claude"
        : provider === "cursor"
          ? "agent"
          : provider;
    try {
      return this.sh(command, ["--version"]).trim() || "unknown";
    } catch {
      return "unknown";
    }
  }

  /**
   * Build (or reuse) the dedicated clone for this invocation (ADR 0024 dec. 1).
   *
   * Path = `<home>/.sc-orchestrator/<repo-slug>-iso-<runKey>`, addressed by the
   * deterministic run key so a crash-resume lands on the SAME clone + ledger
   * (idempotent). When the clone dir is already present we reuse it (no re-clone);
   * otherwise we `git clone <sourceRepo> <clonePath>`. The fail-closed guard runs
   * separately, AFTER the clone exists.
   */
  protected buildOrReuseClone(): string {
    const home = this.opts.home ?? homedir();
    const slug = repoSlug(this.opts.sourceRepo, this.opts.remote);
    const clonePath = clonePathFor(home, slug, this.opts.runKey);
    if (!this.cloneDirExists(clonePath)) {
      // Multi-phase S1-adjacent: a clone failure must abort construction loudly
      // (不启动), not silently leave a half-built or missing working repo.
      this.sh("git", ["clone", this.opts.sourceRepo, clonePath]);
    }
    return clonePath;
  }

  /**
   * Does the dedicated clone dir already exist on disk? `protected` so a test
   * subclass can drive the reuse-vs-clone branch without a real filesystem
   * (mirrors the {@link RealBackend.sh} seam). Checks the clone's `.git` so a
   * stray empty dir is not mistaken for a built clone.
   */
  protected cloneDirExists(clonePath: string): boolean {
    return existsSync(join(clonePath, ".git"));
  }

  /**
   * Fail-closed guard (ADR 0024 decision 1/3): after the clone exists, assert it
   * owns its `.git` — i.e. `git rev-parse --git-common-dir` resolves to the
   * clone's OWN `.git`, not a shared parent repo's `.git` (a linked worktree).
   * If the working repo is a linked worktree, a Sandcastle worktree prune
   * could reach across the shared `.git` into other sessions' admin namespace
   * (the #292 bug). So we refuse to start: throw at construction (不启动).
   */
  protected assertIndependentClone(): void {
    const commonDir = this.sh(
      "git",
      ["rev-parse", "--git-common-dir"],
      this.workingRepo,
    );
    const verdict = checkOwnGitDir(commonDir, this.workingRepo);
    if (!verdict.ok) {
      throw new Error(
        `RealBackend: working repo "${this.workingRepo}" is not an independent ` +
          `clone — git --git-common-dir resolved to "${verdict.commonDir}", which ` +
          `is NOT this clone's own .git. It is a linked worktree sharing another ` +
          `repo's .git; a worktree prune there would corrupt other sessions' ` +
          `worktree admin entries (ADR 0024). Refusing to start.`,
      );
    }
  }

  /**
   * Fail fast at construction if `promptsDir` is not an absolute, existing dir
   * containing every referenced promptFile (integ-cmr 256 r2, F4) — so a
   * misconfiguration surfaces here, not deep inside the first `sandbox.run()`
   * (or, worse, silently against the wrong dir via Sandcastle's process.cwd()
   * resolution). The pure {@link promptsDirError} builds the message; this thin
   * wrapper supplies the fs verdicts.
   */
  private validatePromptsDir(): void {
    const dir = this.opts.promptsDir;
    const dirExists = isAbsolute(dir) && existsSync(dir) && statSync(dir).isDirectory();
    const missing = dirExists
      ? REFERENCED_PROMPT_FILES.filter((f) => !existsSync(join(dir, f)))
      : [];
    const err = promptsDirError(dir, isAbsolute(dir), dirExists, missing);
    if (err !== undefined) throw new Error(err);
  }

  /**
   * Fail loudly at construction if soulsDir is missing or not a usable dir
   * containing the full REQUIRED_SOUL_FILES set. Souls are no longer baked (#372);
   * an incomplete/wrong dir (e.g. orchestrator/image/ or missing reviewer.md
   * / output_protocol.md) would now sail through to runtime (no more baked copies).
   * Delegates to the pure {@link soulsDirError} (single source of messages/checks).
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
   * Run a host `gh`/`git` command, returning trimmed stdout. `protected` so a
   * test subclass can intercept the git/gh seam without a real container or repo
   * (integ-cmr 256 r3 reuse-fail-closed test).
   *
   * #884: every subprocess wait carries a clock (default 120s).
   * Host one-shot with clock only (no auto-retry — #884 clocks / #879 owns leg retry).
   */
  protected sh(file: string, args: string[], cwd?: string): string {
    return shWithClock(file, args, {
      stage: `subprocess:${file}`,
      cwd,
    });
  }

  /** Best-effort host GitHub token for worker sandboxes that call `gh`. */
  protected readGhToken(): string | undefined {
    try {
      const token = this.sh("gh", ["auth", "token"]).trim();
      return token === "" ? undefined : token;
    } catch {
      return undefined;
    }
  }

  // ── S0: lightweight metadata (host gh) ─────────────────────────────────────
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    // Multi-phase step: the first failing sub-op names the failure for the US#30
    // error package (codex#3 attributeFailure — integ-cmr 256 r1, F6). ALL three
    // sub-ops (view, sub-issue count, blocked_by) FAIL CLOSED: a thrown gh /
    // transport / parse error routes via phase("S0", …) → the runner's S8(error)
    // package, NOT a leaf/no-blockers default (integ-cmr 256 r2, F2). Failing
    // open would let a parent epic (sub-issue query fault → 0 → leaf → allow) or
    // a blocked-by-open issue (blocked_by query fault → [] → no blockers → allow)
    // slip past the pinned S0 three-way gate and run from a stale base.
    const json = this.phase("S0", "fetchIssueView", () => {
      // S0 reads the gate fields + body (#767 Coder-Rec). It does NOT pull
      // comments — that would trigger gh's paginated preloadIssueComments for
      // no S0 consumer, and S1's full snapshot re-fetches body+comments anyway
      // (#329 perf). Body alone is cheap and lets the runner parse Coder-Rec
      // before the first worker dispatch.
      const raw = this.sh("gh", [
        "issue",
        "view",
        String(issueNumber),
        "--repo",
        this.opts.repo,
        "--json",
        "number,labels,state,body",
      ]);
      return JSON.parse(raw) as GhIssueJson;
    });
    // Native sub-issue + blocked_by via the GraphQL/REST API — each fails closed.
    const subIssueCount = this.fetchSubIssueCount(issueNumber);
    const blockedBy = this.fetchBlockedBy(issueNumber);
    return buildIssueMeta(issueNumber, json, blockedBy, subIssueCount);
  }

  /**
   * Run a multi-phase step's sub-operation, attributing any throw to
   * `step:phase` via {@link attributeFailure} (codex#3). The runner's outer
   * switch labels the STEP; this refines it to the failing sub-op (e.g.
   * "S1: createWorktree") for the US#30 error package.
   */
  private phase<T>(step: StepId, phase: string, op: () => T): T {
    try {
      return op();
    } catch (err) {
      throw attributeFailure(step, phase, err);
    }
  }

  /** Async sibling of {@link phase}: attribute an awaited sub-op's throw. */
  private async phaseAsync<T>(
    step: StepId,
    phase: string,
    op: () => Promise<T>,
  ): Promise<T> {
    try {
      return await op();
    } catch (err) {
      throw attributeFailure(step, phase, err);
    }
  }

  /**
   * Native sub-issue count, FAIL-CLOSED (integ-cmr 256 r2, F2). A thrown gh /
   * transport / JSON-parse error propagates via `phase("S0", …)` → the runner's
   * S8(error) package, NOT a leaf (0) default — failing open would let a parent
   * epic slip past the S0 gate (sub-issue query fault → 0 → leaf → allow).
   * `parseSubIssueCount` still returns 0 for a CONFIRMED empty/absent field (the
   * genuinely-absent case), distinct from a failed query.
   */
  private fetchSubIssueCount(issueNumber: number, step: StepId = "S0"): number {
    return this.phase(step, "fetchSubIssueCount", () => {
      const raw = this.sh("gh", [
        "issue",
        "view",
        String(issueNumber),
        "--repo",
        this.opts.repo,
        "--json",
        "subIssues",
      ]);
      const parsed = JSON.parse(raw) as { subIssues?: unknown };
      // `gh issue view --json subIssues` returns {nodes,totalCount} (an OBJECT),
      // not an array — read the count off that shape (integ-cmr 256 r1, F1).
      return parseSubIssueCount(parsed);
    });
  }

  /**
   * Native blocked_by list, FAIL-CLOSED (integ-cmr 256 r2, F2). A thrown gh /
   * transport / JSON-parse error propagates via `phase("S0", …)` → S8(error),
   * NOT a no-blockers ([]) default — failing open is the riskier leak: it would
   * let a blocked-by-OPEN issue (the pinned S0 three-way reject) run from a stale
   * base missing upstream changes. `parseBlockedBy` still returns [] for a
   * CONFIRMED empty/non-array response (the genuinely-empty case).
   */
  private fetchBlockedBy(issueNumber: number, step: StepId = "S0"): GhBlockedBy[] {
    return this.phase(step, "fetchBlockedBy", () => {
      const raw = this.sh("gh", [
        "api",
        `repos/${this.opts.repo}/issues/${issueNumber}/dependencies/blocked_by`,
      ]);
      return parseBlockedBy(JSON.parse(raw));
    });
  }

  // ── S1: full snapshot (host gh) ────────────────────────────────────────────
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    // Widen the field list to carry the #244-named native metadata
    // (title/state/labels) into the clean-room snapshot, not just the body. This
    // preserves the host-side audit/resume artifact; the worker still live-fetches
    // issue truth in-container via gh (#244 S1: "body + comments + 最新 Agent Brief
    // 正文 + native metadata").
    const json = this.phase("S1", "fetchIssueView", () => {
      const raw = this.sh("gh", [
        "issue",
        "view",
        String(issueNumber),
        "--repo",
        this.opts.repo,
        "--json",
        "number,title,state,author,body,labels,comments",
      ]);
      return JSON.parse(raw) as GhIssueJson;
    });
    // The native sub-issue + blocked_by summaries (the same ones S0 reads via the
    // GraphQL/REST API) complete the snapshot's native metadata. A thrown
    // gh/transport/parse error propagates → the runner's S1 error termination,
    // attributed to S1 (not S0) for the US#30 error package.
    const subIssueCount = this.fetchSubIssueCount(issueNumber, "S1");
    const blockedBy = this.fetchBlockedBy(issueNumber, "S1");
    return buildIssueSnapshot(
      issueNumber,
      json,
      blockedBy,
      subIssueCount,
      this.ownerLogin,
    );
  }

  // ── S1: resident slice worktree (Sandcastle native createWorktree) ─────────
  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    // #291 B7: the family spine fans a wave out CONCURRENTLY, and every child in
    // the wave shares THIS one dedicated clone (ADR 0024). The worktree-list scan,
    // the best-effort `git fetch`, and the `git worktree add` cut all MUTATE the shared `.git` — concurrent ones race on `.git/index.lock`
    // / per-ref locks (distinct child BRANCHES isolate the logical work, NOT the
    // git locks). So the git-mutating section runs under a per-clone mutex keyed on
    // the working repo: same-clone children serialise their cuts, while a DIFFERENT
    // clone (another run in the same process) never blocks. A standalone single-slice
    // run is the degenerate single-holder case (no contention).
    //
    // #746 R2: node_modules provisioning is NOT a git mutation — each worktree has
    // its own directory; template reads are read-only. Keeping npm ci / clonefile
    // inside the mutex serialises N wave children on ~90s cold installs (the issue's
    // goal is the opposite). Mutex covers only the cut/reuse git section; provision
    // runs after release. #661 preserves reused scenes intact; provisioning occurs
    // after the exclusive cut/reuse decision without cleaning user or worker files.
    const handle = await runExclusive(this.workingRepo, () =>
      this.prepareWorktreeLocked(issueNumber, base),
    );
    await this.provisionWorktreeNodeModules(handle.path);
    return handle;
  }

  /** The git-mutating body of {@link prepareWorktree}, run under the per-clone mutex. */
  private async prepareWorktreeLocked(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    // Idempotent reuse: if the resident worktree exists, reuse it (the runner's
    // #255 resume path drives this); else cut a fresh one from `base` (main).
    //
    // #661: an existing scene is work product, even if its ledger is missing or
    // unreadable. Reuse it AS-IS; a genuinely unusable scene must be escalated,
    // never reset or cleaned.
    const existing = this.findExistingWorktree(issueNumber);
    if (existing !== undefined) {
      return { branch: existing.branch, base, path: existing.path };
    }
    const branch = branchForIssue(issueNumber);
    // Cut the slice branch from `base` (= "main", runner.ts SLICE_BASE), NOT the
    // working clone's current HEAD. NamedBranchStrategy.baseBranch defaults to HEAD
    // when omitted (Sandcastle d.ts:213), so omitting it silently derived the
    // slice from whatever the clone happened to be checked out on — the #244
    // "从 main 派生" invariant only held by accident (integ-cmr 256 r1, F3).
    // Sandcastle notes the caller owns currency of the ref, so refresh `base`
    // first (best-effort: a fetch failure must not block a local-only base).
    //
    // integ-cmr 256 r3 (worktree_base_stale): `git fetch origin <base>` updates
    // refs/remotes/origin/<base>, NOT the local refs/heads/<base>. Deriving with
    // the bare local `<base>` after a fetch could still cut from a stale local
    // branch behind upstream. So when the fetch refreshed the remote ref, cut
    // from `origin/<base>` (matching the spike's `git worktree add … origin/main`
    // and the up-to-date invariant); fall back to the local `<base>` only when
    // the fetch failed (offline / local-only base). The WorktreeHandle.base field
    // still records the LOGICAL base ("main"), not the cut ref, for ledger
    // consistency.
    // #291: a family-base cut is LOCAL-only (ADR 0022 decision 7) — the family
    // base is a local branch the merger accumulates onto, with no remote
    // counterpart. So skip `git fetch origin <family-base>` (it would fail or, worse,
    // resolve a stale remote branch) and force the bare local ref. The child-machine
    // harness path (base="main", no `familyBase` option) keeps the fetch +
    // `origin/main` derivation used by focused single-slice tests.
    const localOnly = base === this.opts.familyBase;
    const fetchedOk = localOnly ? false : this.ensureBaseRef(base);
    const cutRef = cutRefFor(base, fetchedOk, localOnly);
    // Multi-phase S1: attribute a createWorktree throw as "S1: createWorktree"
    // for the US#30 error package (codex#3 attributeFailure — F6).
    const wt = await this.phaseAsync("S1", "createWorktree", () =>
      this.createResidentWorktree(branch, cutRef),
    );
    // ADR 0024 dec. 2 (second half): the resident worktree is the commit source +
    // crash-resume source (ADR 0017), so we keep ONLY its path and deliberately
    // do NOT dispose the handle — no `.close()`, no `await using`. Sandcastle's
    // close() removes a clean worktree, which would delete the resume truth. The
    // resident worktree is reaped only by an explicit terminal-success GC, never
    // by normal-path disposal.
    return { branch, base, path: wt.worktreePath };
  }

  /**
   * #746 — host-side Node deps for a resident worktree. Uses the driver
   * `sourceRepo` as the warm template monorepo. No package.json under the path
   * (fake/stub worktrees in unit tests) ⇒ no-op. `protected` so a subclass can
   * skip / spy without a real FS. May return a Promise (tests hold provision to
   * prove it runs outside the git mutex); callers always await.
   */
  protected provisionWorktreeNodeModules(
    worktreePath: string,
  ): Promise<void> {
    return provisionRepoNodeModules(worktreePath, {
      templateRoot: this.opts.sourceRepo,
      sh: (file, args, cwd) => this.provisionCommand(file, args, cwd ?? worktreePath),
    }).then(() => undefined);
  }

  /** Provision-only async shell seam; ordinary git/gh commands remain synchronous. */
  protected provisionCommand(
    file: string,
    args: string[],
    cwd?: string,
  ): string | Promise<string> {
    // Test doubles override the synchronous general shell seam; preserve that
    // seam for observability while the production implementation uses async I/O.
    if (this.sh !== RealBackend.prototype.sh) {
      return this.sh(file, args, cwd);
    }
    return (runProvisionCommand as ProvisionSh)(file, args, cwd);
  }

  /**
   * Cut the resident slice worktree via Sandcastle (`createWorktree`). `protected`
   * so a test subclass can intercept this seam without a real container (mirrors
   * the {@link RealBackend.sh} seam rationale), e.g. to assert ADR 0024's "do not
   * dispose the resident worktree" invariant.
   */
  protected async createResidentWorktree(
    branch: string,
    baseBranch: string,
  ): Promise<sc.Worktree> {
    return sc.createWorktree({
      branchStrategy: { type: "branch", branch, baseBranch },
      cwd: this.workingRepo,
    });
  }

  /**
   * Refresh the base ref so the slice is cut from an up-to-date `base`, and
   * REPORT whether the fetch succeeded so {@link cutRefFor} can choose the
   * origin/<base> remote-tracking ref vs the local fallback (integ-cmr 256 r3,
   * worktree_base_stale). Sandcastle notes the caller is responsible for the
   * ref's currency (d.ts:211); a `git fetch` failure (offline / local-only base)
   * must NOT block worktree creation, so this is best-effort and returns false
   * on any fault (the caller then derives from the local `<base>`).
   */
  private ensureBaseRef(base: string): boolean {
    try {
      this.sh("git", ["fetch", "origin", base], this.workingRepo);
      return true;
    } catch {
      // offline or a local-only base ⇒ proceed with the local ref.
      return false;
    }
  }

  private findExistingWorktree(issueNumber: number): { path: string; branch: string } | undefined {
    try {
      const out = this.sh("git", ["worktree", "list", "--porcelain"], this.workingRepo);
      return resolveExistingWorktreeFromPorcelain(out, issueNumber);
    } catch {
      // no worktrees / git error ⇒ none existing.
      return undefined;
    }
  }

  // ── S1: write the snapshot into the worktree (clean-room) ──────────────────
  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    // F3 — git-ignore the snapshot BEFORE writing it, so a coder's `git add -A`
    // can never stage the host-fetched clean-room snapshot into the reviewed /
    // pushed branch (branchStrategy:{type:'head'} commits in place). The
    // per-worktree info/exclude is the right scope: it is local to this resident
    // worktree, needs no checked-in change to the target repo, and survives the
    // agent run. Best-effort: an exclude failure must not block the (still
    // useful) snapshot write — but it is attempted first so the common path is
    // always covered.
    this.excludeFromGit(worktree, SNAPSHOT_FILENAME);
    const target = join(worktree.path, SNAPSHOT_FILENAME);
    writeFileSync(target, JSON.stringify(snapshot, null, 2), "utf8");
  }

  /**
   * Add `pattern` to the repo's git `info/exclude` (idempotent via
   * {@link ensureExcluded}), so a `git add -A`/`git add .` in the resident
   * worktree never stages it (F3). `git rev-parse --git-path info/exclude` run
   * inside a linked worktree resolves to the SHARED common-dir exclude
   * (git keeps `info/exclude` in the common git dir, not per-worktree) — that is
   * fine and intended here: every slice excludes the SAME snapshot filename, and
   * {@link ensureExcluded} is idempotent, so concurrent slices appending the same
   * pattern never duplicate or conflict. Best-effort: a git/fs fault here must
   * not block the snapshot write itself (the checked-in root `.gitignore` belt
   * still covers the common case).
   */
  private excludeFromGit(worktree: WorktreeHandle, pattern: string): void {
    try {
      const excludePath = this.sh(
        "git",
        ["rev-parse", "--git-path", "info/exclude"],
        worktree.path,
      );
      const abs = excludePath.startsWith("/")
        ? excludePath
        : join(worktree.path, excludePath);
      let existing = "";
      try {
        existing = readFileSync(abs, "utf8");
      } catch {
        // No exclude file yet (or info/ missing) — start from empty + mkdir.
      }
      const next = ensureExcluded(existing, pattern);
      if (next !== existing) {
        mkdirSync(join(abs, ".."), { recursive: true });
        writeFileSync(abs, next, "utf8");
      }
    } catch {
      // Best-effort: a divergent git layout must not block the snapshot write.
      // The root .gitignore (checked-in belt) still covers the common case.
    }
  }

  // ── auth mount (spike contract) ────────────────────────────────────────────
  // `protected` (not private) so the auth-mount tests can drive it over a real
  // temp $HOME (assert auth.json copied + the minimal container config written).
  protected mountAuth(issueNumber: number): {
    authDir: string;
    claudeToken?: string;
    /** Per-issue host dir for grok auth, only when host `~/.grok/auth.json` exists. */
    grokAuthDir?: string;
    opencodeAuthFile?: string;
    providerAuth: ProviderAuthAvailability;
  } {
    // #748: resolve home at this seam so tests can inject a tmpdir via opts.home;
    // production keeps the os.homedir() default when opts.home is omitted.
    const paths = buildAuthPaths(issueNumber, this.opts.home ?? homedir());
    rmSync(paths.hostCodexAuthDir, { recursive: true, force: true });
    // Owner-only dir: this holds copied credential material (auth.json /
    // config.toml). 0o700 keeps it off world-readable multi-user hosts
    // (coderabbit R2, major).
    mkdirSync(paths.hostCodexAuthDir, { recursive: true, mode: 0o700 });
    // The Codex auth is BEST-EFFORT too (#384 R2 codex P2 — symmetric to the
    // Claude token below). With ORCHESTRATOR_CODER_MODEL switched to a Claude coder
    // (e.g. "sonnet"), a host with Claude auth but no `~/.codex/auth.json` must
    // still start the worker — a missing codex auth degrades the codex leg, it does
    // not throw and block the Claude coder. So the env-only model switch works both
    // ways.
    try {
      copyFileSync(paths.srcCodexAuth, join(paths.hostCodexAuthDir, "auth.json"));
      // Copied credential file → owner-only (was world-readable 0o644).
      chmodSync(join(paths.hostCodexAuthDir, "auth.json"), 0o600);
    } catch {
      // No host codex auth → the codex leg degrades (no creds in the mounted dir).
    }
    // The container IS the sandbox boundary; codex must NOT self-sandbox (nested
    // bwrap is impossible). The host config.toml is host-personal (notify/plugins/
    // workspace-write) and irrelevant here — only auth.json crosses. Write the
    // minimal container config instead of copying the host's (#378). Always written
    // so the dir is a valid mount even when codex auth was absent.
    writeContainerCodexConfig(join(paths.hostCodexAuthDir, "config.toml"), this.opts.codexFast);
    // #807: grok auth is BEST-EFFORT + fail-closed skip. Host missing
    // `~/.grok/auth.json` ⇒ omit the mount entirely (unlike codex, which still
    // mounts an empty-ish dir for config.toml). Presence gate = copy success.
    let grokAuthDir: string | undefined = mkdtempSync(`${paths.hostGrokAuthDir}-`);
    try {
      chmodSync(grokAuthDir, 0o700);
      copyFileSync(paths.srcGrokAuth, join(grokAuthDir, "auth.json"));
      chmodSync(join(grokAuthDir, "auth.json"), 0o600);
    } catch {
      // No host grok auth → skip mount; reclaim the half-built dir.
      rmSync(grokAuthDir, { recursive: true, force: true });
      grokAuthDir = undefined;
    }
    // The Claude token is BEST-EFFORT (#384 codex P2). The coder step now runs
    // Codex (model gpt-5.6-terra), so it no longer needs CLAUDE_CODE_OAUTH_TOKEN. A host
    // with Codex auth but no `~/.sc-claude-token` must still start the worker — a
    // missing token degrades the Claude leg (undefined) rather than throwing and
    // blocking the Codex coder before it can start (mirrors ShipAuth's optional
    // claudeToken).
    let claudeToken: string | undefined;
    try {
      claudeToken = readFileSync(paths.claudeTokenFile, "utf8").trim() || undefined;
    } catch {
      claudeToken = undefined;
    }
    return {
      authDir: paths.hostCodexAuthDir,
      claudeToken,
      grokAuthDir,
      opencodeAuthFile: hostOpenCodeAuthFile(this.opts.home ?? homedir()),
      providerAuth: { claude: claudeToken !== undefined, grok: grokAuthDir !== undefined },
    };
  }

  /**
   * Grok OAuth copies are invocation-unique and only needed while their mounted
   * container runs. Reclaim them on every terminal path without masking the
   * worker result; this mirrors the family backend's per-run auth lifecycle.
   */
  protected cleanupTempAuthDirs(dirs: ReadonlyArray<string | undefined>): void {
    for (const dir of dirs) {
      if (dir === undefined) continue;
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {
        // Best-effort cleanup must not mask the worker's own outcome.
      }
    }
  }

  /** Fail before `sc.run`: a missing mount is not permission to launch unauthenticated. */
  private assertProviderAuth(
    slug: string,
    pool: BillingPoolDispatchId | undefined,
    availability: ProviderAuthAvailability,
  ): void {
    const resolved = resolveModelSlugForPool(slug, pool);
    const missing = unavailableProviderAuth(resolved.provider, availability);
    if (missing !== undefined) {
      throw new Error(
        `no ${missing} auth for selected ${resolved.provider} provider (${slug}) — refusing to launch`,
      );
    }
  }

  private box(
    issueNumber: number,
    spec: Pick<StepSpec, "role" | "soul" | "model">,
    options?: AgentStepRunOptions,
  ): { sandbox: sc.SandboxProvider; providerAuth: ProviderAuthAvailability; cleanup: () => void } {
    const auth = this.mountAuth(issueNumber);
    return {
      sandbox: docker(
        this.boxConfig(
          { ...auth, ghToken: this.readGhToken() },
          spec,
          issueNumber,
          options,
        ),
      ),
      providerAuth: auth.providerAuth,
      cleanup: () => this.cleanupTempAuthDirs([auth.grokAuthDir]),
    };
  }

  /**
   * #286 decision: implement the StepSpec.toolchain assertion instead of
   * downgrading it to documentation. Sandcastle v0.10.0 exposes no public
   * `sandbox.exec()` on the consumer sandbox, so the cheapest no-LLM preflight is
   * a direct one-shot `docker run --rm <image> <tool> --version` against the same
   * profile image, before any agent `sc.run()` can burn model time.
   */
  private async preflightToolchain(spec: StepSpec): Promise<void> {
    const tools = [...new Set(spec.toolchain)];
    if (tools.length === 0) return;
    const cacheKey = `${this.opts.imageName}\0${tools.join("\0")}`;
    if (this.preflightedToolchains.has(cacheKey)) return;
    const inFlight = this.inFlightToolchainPreflights.get(cacheKey);
    if (inFlight !== undefined) {
      await inFlight;
      return;
    }
    const run = this.runToolchainPreflight(tools, cacheKey);
    this.inFlightToolchainPreflights.set(cacheKey, run);
    try {
      await run;
    } finally {
      this.inFlightToolchainPreflights.delete(cacheKey);
    }
  }

  private async runToolchainPreflight(
    tools: ReadonlyArray<string>,
    cacheKey: string,
  ): Promise<void> {
    for (const tool of tools) {
      try {
        await this.preflightToolchainTool(tool);
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        throw new Error(
          `RealBackend toolchain preflight failed for image ` +
            `"${this.opts.imageName}": missing or unusable tool "${tool}" ` +
            `(${toolchainVersionCommand(tool).join(" ")}). ${detail}`,
        );
      }
    }
    this.preflightedToolchains.add(cacheKey);
  }

  protected async preflightToolchainTool(tool: string): Promise<void> {
    this.sh("docker", [
      "run",
      "--rm",
      this.opts.imageName,
      ...toolchainVersionCommand(tool),
    ]);
  }

  /**
   * The docker options the agent sandbox runs under — the pure SANDBOX-CONFIG
   * seam (mirrors the family `mergerSandboxConfig()` testability pattern). No
   * container, no I/O: a unit test asserts the mounts + soul env without spinning
   * a real sandbox (#334 — so the baked-skills behaviour is regression-
   * guarded the same way the family merger's mount is).
   *
   * #334 (ADR 0026 / cross-slice note from #332/#333): the runtime host
   * host-skills bind-mount onto {@link SANDBOX_SKILLS_DIR} is DROPPED. The 2b
   * worker image (#333) BAKES the full dev-skill closure at that exact path, so
   * mounting host skills there at runtime would SHADOW the baked skills — pulling
   * the worker back to host state (the ADR 0026 reproducibility regression). The
   * baked image is now the single source of skills; souls are mounted live (#372).
   * The only other mounts are per-issue auth + outcome files.
   *
   * ship-pre 256 r1: `soulForStep(spec)` selects the role's soul and
   * injects it via {@link SANDBOX_SOUL_ENV} so the v0.1 one-image-two-roles
   * profile activates the right one (#244 "role 决定注哪份 soul"); it throws on a
   * spec whose `soul` contradicts its `role` → S8(error). Still a soul ENV
   * signal, not an OS readonly mount (reviewer READ-ONLY stays soft, ADR 0017 §4).
   */
  protected boxConfig(
    auth: {
      authDir: string;
      claudeToken?: string;
      ghToken?: string;
      /** #807: optional per-issue grok auth dir (omit when host auth absent). */
      grokAuthDir?: string;
      opencodeAuthFile?: string;
    },
    spec: Pick<StepSpec, "role" | "soul"> & { model?: string },
    issueNumber?: number,
    options?: AgentStepRunOptions,
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
  } {
    const soul = soulForStep(spec);
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
      [SANDBOX_SOUL_ENV]: soul,
      [SANDBOX_REPO_ENV]: this.opts.repo,
    };
    // Inject the Claude token only when present: a Codex coder (model gpt-5.6-terra)
    // needs no CLAUDE_CODE_OAUTH_TOKEN, and an empty/undefined value would defeat
    // the in-container Claude auth on a Codex-only host (#384 codex P2).
    if (auth.claudeToken) {
      env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    }
    if (issueNumber !== undefined) {
      const issue = String(issueNumber);
      env[SANDBOX_ISSUE_NUMBER_ENV] = issue;
      env[SANDBOX_ISSUE_NUMBER_ALIAS_ENV] = issue;
    }
    if (auth.ghToken !== undefined) {
      env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    }
    if (options?.fixFindingsLanding !== undefined) {
      env[SANDBOX_FIX_FINDINGS_PATH_ENV] =
        options.fixFindingsLanding.sandboxPath;
    }
    if (options?.fixFocusLanding !== undefined) {
      env[SANDBOX_FIX_FOCUS_PATH_ENV] = options.fixFocusLanding.sandboxPath;
    }
    if (options?.outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = options.outcomeLanding.sandboxPath;
    }
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [
      { hostPath: auth.authDir, sandboxPath: SANDBOX_CODEX_DIR },
    ];
    // #807: mount grok auth only when host `~/.grok/auth.json` was present
    // (fail-closed skip). Whole-dir mount at SANDBOX_GROK_DIR; image keeps
    // `/usr/local/bin/grok` outside this tree so PATH survives the bind.
    if (auth.grokAuthDir !== undefined) {
      mounts.push({ hostPath: auth.grokAuthDir, sandboxPath: SANDBOX_GROK_DIR });
    }
    applyUniformCredentialProvisioning({
      env,
      mounts,
      opencodeAuthFile: auth.opencodeAuthFile,
    });
    // #372: mount souls live (from host source tree) so edits to souls/*.md take
    // effect immediately on next launch/dispatch without baking into image.
    // Uses shared helper which hardcodes sandbox path and forces readonly:true.
    mounts.push(soulsMount(this.opts.soulsDir));
    if (options?.fixFindingsLanding !== undefined) {
      mounts.push({
        hostPath: options.fixFindingsLanding.path,
        sandboxPath: options.fixFindingsLanding.sandboxPath,
        readonly: true,
      });
    }
    if (options?.fixFocusLanding !== undefined) {
      mounts.push({
        hostPath: options.fixFocusLanding.path,
        sandboxPath: options.fixFocusLanding.sandboxPath,
        readonly: true,
      });
    }
    if (options?.outcomeLanding !== undefined) {
      mounts.push({
        hostPath: options.outcomeLanding.path,
        sandboxPath: options.outcomeLanding.sandboxPath,
      });
    }
    return {
      imageName: this.opts.imageName,
      env,
      // #334: codex auth always-on; #372 adds souls mount (live data); S5 adds
      // runner-owned fix findings file as a narrow read-only overlay.
      mounts,
    };
  }

  /** Build the output definition for a step's role. */
  private outputFor(spec: StepSpec): sc.OutputDefinition {
    const tag = spec.role === "reviewer" ? "review" : spec.role;
    return sc.Output.object({ tag, schema: workerReceiptSchema });
  }

  /**
   * Resolve the raw structured payload to decode for a step.
   *
   * - `typedOutputUsed` (reviewer single-pass, OR any resume — both run
   *   maxIterations:1): Sandcastle parsed the tag into `result.output`, so read
   *   it directly.
   * - otherwise (a coder step with maxIter>1, where Sandcastle's typed `output`
   *   is forbidden): extract the `<coder>` tag from `result.stdout` ourselves
   *   (integ-cmr 256 r1, F2 — the coder path produced no `result.output`, so the
   *   old `coderOutputSchema.parse(undefined)` threw on EVERY coder step).
   */
  private rawOutputFor(
    result: { output?: unknown; stdout: string },
    spec: StepSpec,
    typedOutputUsed: boolean,
    options?: AgentStepRunOptions,
  ): unknown | undefined {
    const compatibility = extractRoleReceipt(result.stdout, spec.role);
    const compatibilityBell = probeWorkerDecisionBell(compatibility);
    try {
      if (options?.outcomeLanding?.path !== undefined) {
        const sidecar = readOutcomeSidecar(options.outcomeLanding.path);
        if (sidecar !== undefined) {
          if (probeWorkerDecisionBell(sidecar) !== undefined) return sidecar;
          if (compatibilityBell !== undefined) return compatibility;
          return sidecar;
        }
      }
    } catch (err) {
      console.warn(
        `[orchestrator] telemetry: ${spec.id}-${spec.role} outcome sidecar is unreadable cargo: ` +
          `${err instanceof Error ? err.message : String(err)}`,
      );
      return compatibilityBell !== undefined ? compatibility : undefined;
    }
    if (typedOutputUsed && result.output !== undefined) {
      if (probeWorkerDecisionBell(result.output) !== undefined) return result.output;
      if (compatibilityBell !== undefined) return compatibility;
      return result.output;
    }
    // Stdout tags are the primary machine channel for multi-iteration coders;
    // elsewhere they are compatibility for a missing typed result.
    if (compatibility !== undefined) {
      if (typedOutputUsed) {
        console.warn(
          `[orchestrator] telemetry: ${spec.id}-${spec.role} used legacy stdout tag compatibility fallback`,
        );
      }
      return compatibility;
    }
    // No receipt channel means no cargo. Do not synthesize worker output from Git.
    return undefined;
  }

  private decodeOutput(
    spec: StepSpec,
    raw: unknown,
  ): StepOutput {
    const decisionBell = probeWorkerDecisionBell(raw);
    if (decisionBell !== undefined) {
      return spec.role === "coder"
        ? {
            kind: "coder",
            committed: false,
            commitsAdded: 0,
            escalate: decisionBell,
          }
        : { kind: "reviewer", findings: [], escalate: decisionBell };
    }
    if (spec.role === "reviewer") {
      if (
        raw === null ||
        typeof raw !== "object" ||
        !Array.isArray((raw as { findings?: unknown }).findings)
      ) {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      const receipt = raw as {
        findings: ReadonlyArray<Finding>;
        priorFindingDispositions?: ReadonlyArray<PriorFindingDisposition>;
      };
      return {
        kind: "reviewer",
        findings: receipt.findings,
        ...(Array.isArray(receipt.priorFindingDispositions)
          ? { priorFindingDispositions: receipt.priorFindingDispositions }
          : {}),
      };
    }
    // Coder completion is worker-authored. The next reviewer judges the diff.
    if (spec.role === "coder") {
      if (raw === null || typeof raw !== "object") {
        return { kind: "coder", committed: false, commitsAdded: 0 };
      }
      const receipt = raw as Record<string, unknown>;
      const repairEvidence = repairEvidenceSchema.safeParse(receipt.repairEvidence);
      return {
        kind: "coder",
        committed: typeof receipt.committed === "boolean" ? receipt.committed : false,
        commitsAdded:
          typeof receipt.commitsAdded === "number" &&
          Number.isInteger(receipt.commitsAdded) &&
          receipt.commitsAdded >= 0
            ? receipt.commitsAdded
            : 0,
        ...(repairEvidence.success ? { repairEvidence: repairEvidence.data } : {}),
      };
    }

    // Family endgame roles are dispatched by RealFamilyBackend, never here.
    throw new Error(`realBackend: cannot decode output for unknown role ${spec.role}`);
  }

  // ── S2/S3/S5/S6 agent workers (ADR 0030; #256 seam extension returns
  //    StepResult). S2/S5 run the coder soul; S3/S6 run the fresh read-only
  //    reviewer soul. The runner owns the visible review/fix loop and threads
  //    S4 blocking findings to S5 through DispatchContext/landing artifacts. ─
  private async runFreshAgentStep(
    spec: StepSpec,
    worktree: WorktreeHandle,
    options?: AgentStepRunOptions,
  ): Promise<StepResult> {
    const issueNumber = this.issueOf(worktree);
    await this.preflightToolchain(spec);
    const typedOutputUsed =
      spec.maxIter === 1 && options?.outcomeLanding === undefined;
    const box = this.box(issueNumber, spec, options);
    try {
    const pool = isBillingPoolDispatchId(options?.billingPool) ? options.billingPool : undefined;
    this.assertProviderAuth(spec.model, pool, box.providerAuth);
    const result = await this.runAgentSandbox({
      name: `${spec.id}-${spec.role}`,
      idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
      cwd: worktree.path,
      sandbox: box.sandbox,
      // The build worker's CLI is the spec's model slug → provider (the S2 coder
      // runs on Codex gpt-5.6-terra; a claude slug stays claudeCode). agentForSlug keeps
      // the "model slug → baked CLI" #244 mapping unit-testable. #686: billing pool
      // overrides the channel when the same model lives on multiple pools.
      agent: agentForSlug(
        spec.model,
        effortForLiveOfficer(spec.model, spec),
        pool,
      ),
      // #7 maxIter: enforce the WITHIN-STEP Ralph retry budget = StepSpec.maxIter
      // (reviewer = 1 single pass; coder/fix > 1). Hitting it ends THE STEP
      // normally — route() continues — it is NEVER the orchestrator giving up
      // (StepSpec.maxIter semantics; the only give-up is a model escalate).
      maxIterations: spec.maxIter,
      completionSignal: spec.completionSignal,
      branchStrategy: { type: "head" }, // commit on the resident branch in place
      promptFile: join(this.opts.promptsDir, spec.promptFile),
      // Structured output only when Sandcastle should own tag parsing. When the
      // runner supplied an outcome sidecar, do not pass `output`: Sandcastle
      // would throw on a bad/missing compatibility tag before the backend can
      // read the sidecar machine protocol.
      ...(typedOutputUsed ? { output: this.outputFor(spec) } : {}),
      // #683 fallback context for Sandcastle's own internal timeout only. The
      // normal live-worker path is dispatched through the #684 monitor.
      quotaProbe: {
        modelRef: spec.model,
        step: spec.id,
        worktreePath: worktree.path,
        issueNumber,
      },
    });
    const raw = this.rawOutputFor(result, spec, typedOutputUsed, options);
    const output = this.decodeOutput(spec, raw);
    return { output, sessionId: lastSessionId(result) };
    } finally {
      box.cleanup();
    }
  }

  async runStep(
    spec: StepSpec,
    worktree: WorktreeHandle,
    options?: AgentStepRunOptions,
  ): Promise<StepResult> {
    return await this.runFreshAgentStep(spec, worktree, options);
  }

  // ── #255: resume the prior agent session (native + dead-session fallback) ───
  async resumeSession(
    spec: StepSpec,
    worktree: WorktreeHandle,
    sessionId: string,
    options?: AgentStepRunOptions,
  ): Promise<StepResult> {
    const issueNumber = this.issueOf(worktree);
    await this.preflightToolchain(spec);
    const box = this.box(issueNumber, spec, options);
    try {
      const pool = isBillingPoolDispatchId(options?.billingPool) ? options.billingPool : undefined;
      this.assertProviderAuth(spec.model, pool, box.providerAuth);
      const typedOutputUsed = options?.outcomeLanding === undefined;
      const result = await this.runAgentSandbox({
        name: `${spec.id}-${spec.role}-resume`,
        idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
        cwd: worktree.path,
        sandbox: box.sandbox,
        // Resume the build worker on the SAME CLI as its fresh run (agentForSlug:
        // codex for the gpt-5.6-terra coder, claudeCode for a claude slug). #686 pool
        // channel must match the fresh dispatch.
        agent: agentForSlug(
          spec.model,
          effortForLiveOfficer(spec.model, spec),
          pool,
        ),
        // resumeSession requires maxIterations:1 (Sandcastle constraint).
        maxIterations: 1,
        completionSignal: spec.completionSignal,
        branchStrategy: { type: "head" },
        resumeSession: sessionId,
        promptFile: join(this.opts.promptsDir, spec.promptFile),
        // A resume runs maxIterations:1, so typed output is valid unless the
        // outcome sidecar is mounted. With a sidecar, keep Sandcastle from
        // pre-parsing the compatibility tag before rawOutputFor can read the
        // runner-owned file.
        ...(typedOutputUsed ? { output: this.outputFor(spec) } : {}),
        // #683: idle timeout → pool probe before hang (额度墙 ≠ hang).
        quotaProbe: {
          modelRef: spec.model,
          step: spec.id,
          worktreePath: worktree.path,
          issueNumber,
        },
      });
      const output = this.decodeOutput(
        spec,
        this.rawOutputFor(result, spec, typedOutputUsed, options),
      );
      return { output, sessionId: lastSessionId(result) ?? sessionId };
    } catch (err) {
      // Dead-session fallback (#256/#285): ONLY a clearly missing/dead prior
      // session falls back to a fresh run() (keep committed worktree progress,
      // lose in-session memory). Signal mismatches, schema parse failures, auth
      // failures and model errors propagate to the
      // runner's S8(error) edge instead of being masked by a fresh run.
      const recovery = classifyResumeError(err);
      if (recovery.kind === "fresh-run") {
        return await this.runFreshAgentStep(spec, worktree, options);
      }
      throw err;
    } finally {
      box.cleanup();
    }
  }

  /**
   * Live sandbox-handle worker pid captured during the current
   * {@link runAgentSandbox} call. Cleared on entry/exit. Tests (and future
   * #684 monitor wiring) call {@link noteActiveSandboxWorkerPid} while the
   * sandbox handle is still live — before Sandcastle release.
   */
  private activeSandboxWorkerPid: number | undefined;

  /**
   * Record the OS pid from the live sandbox handle so hang kill after idle
   * probe has a real target. No-op for non-positive / non-integer values.
   */
  protected noteActiveSandboxWorkerPid(pid: number): void {
    if (Number.isInteger(pid) && pid > 0) {
      this.activeSandboxWorkerPid = pid;
    }
  }

  /** Resolve worker pid: explicit context → live sandbox handle → 0. */
  protected resolveWorkerPid(ctx: QuotaProbeRunContext): number {
    if (ctx.workerPid !== undefined && ctx.workerPid > 0) return ctx.workerPid;
    if (
      this.activeSandboxWorkerPid !== undefined &&
      this.activeSandboxWorkerPid > 0
    ) {
      return this.activeSandboxWorkerPid;
    }
    return 0;
  }

  /**
   * Thin Sandcastle `sc.run` seam. Unit tests that need a fake container result
   * override THIS method (or {@link runAgentSandbox}). Production idle/quota
   * disposition lives in {@link runAgentSandbox} so a full override of that
   * method intentionally bypasses #683 only when the test owns the whole path.
   *
   * Implementations that own a live sandbox handle MUST call
   * {@link noteActiveSandboxWorkerPid} with the handle's agent/container pid
   * while the handle is still alive (before teardown) so hang kill has a real
   * target. Public Sandcastle types do not expose handle.pid — capture is the
   * invoker's responsibility (#684 monitor handle is the durable companion).
   */
  protected async invokeSandcastleRun(
    options: Parameters<typeof sc.run>[0],
  ): Promise<Awaited<ReturnType<typeof sc.run>>> {
    return await sc.run(options);
  }

  /**
   * Production agent-sandbox entry (#683). Runs Sandcastle, and on idle timeout
   * probes the worker's quota pool BEFORE hang disposition:
   *   - 429/limit → {@link QuotaWaitForResetError} (park step for quota reset;
   *     ledger row via applied.ledgerEntry for runner park; do NOT mark failed)
   *   - probe ok / network error → fail-safe rethrow the idle error (kill is a
   *     no-op here; live hang kill is owned by the #684 monitor handle path)
   */
  protected async runAgentSandbox(
    options: AgentSandboxRunOptions,
  ): Promise<Awaited<ReturnType<typeof sc.run>>> {
    const { quotaProbe, ...scOptions } = options;
    this.activeSandboxWorkerPid = undefined;
    try {
      return await this.invokeSandcastleRun(scOptions);
    } catch (err) {
      if (!isAgentIdleTimeoutError(err) || quotaProbe === undefined) {
        throw err;
      }
      const result = await this.resolveIdleAfterQuotaProbe({
        ...quotaProbe,
      });
      if (result.disposition.kind === "wait_for_reset") {
        // 429: park for quota reset. Sandbox already released by Sandcastle;
        // runner consumes this error via existing park machinery (not S8 error).
        throw new QuotaWaitForResetError(result);
      }
      // Internal Sandcastle timeout fallback: the sandbox already owns its
      // teardown. Do not kill via the old backend-local pid path.
      throw err;
    } finally {
      this.activeSandboxWorkerPid = undefined;
    }
  }

  /**
   * #683 production idle disposition entry. Callable from runAgentSandbox (on
   * Sandcastle idle timeout) and from any external monitor that owns the idle
   * threshold. Overridable only for host I/O seams (probe / kill / ledger).
   */
  protected async resolveIdleAfterQuotaProbe(
    ctx: QuotaProbeRunContext,
  ): Promise<HandleIdleThresholdResult> {
    const pid = this.resolveWorkerPid(ctx);
    return handleIdleThreshold({
      modelRef: ctx.modelRef,
      worker: {
        pid,
        ...(ctx.step !== undefined ? { step: ctx.step } : {}),
      },
      actions: {
        // The live monitor owns verified pid-tree kill. This action is only a
        // no-op for the post-Sandcastle internal-timeout fallback.
        killPidTree: () => undefined,
        // Durable park marker is written once by runner.parkQuotaWaitForReset
        // with real sessionId/prompt_hash/branchHEAD. Do not double-write here
        // with placeholder audit fields (#683 integration R1).
        recordLedger: async () => undefined,
        now: () => this.idleNow(),
      },
      probe: (pool) => this.runQuotaProbe(pool),
    });
  }

  /** Clock for wait-for-reset ledger `ts` (injectable via override in tests). */
  protected idleNow(): Date {
    return new Date();
  }

  /**
   * Pool probe used after idle threshold (#683). Default = real
   * {@link runPoolProbe}; tests stub three outcomes.
   */
  protected async runQuotaProbe(pool: QuotaPoolId): Promise<QuotaProbeResult> {
    return runPoolProbe(pool);
  }

  /**
   * Persist a `quota_wait_for_reset` ledger row to the sibling state dir when
   * known. Tests may override to capture without touching disk.
   *
   * Production monitor / Sandcastle-fallback paths no longer call this for the
   * durable write (#683 R1): runner.parkQuotaWaitForReset owns the single
   * append-only row with real audit fields. Kept for test overrides / tooling.
   */
  protected async recordQuotaWaitLedger(
    entry: QuotaWaitForResetLedgerEvent,
    ctx: QuotaProbeRunContext,
  ): Promise<void> {
    if (ctx.worktreePath === undefined || ctx.issueNumber === undefined) {
      // No durable landing spot — still surface via QuotaWaitForResetError.applied
      return;
    }
    const stateDir = this.stateDirFor(ctx.worktreePath, ctx.issueNumber);
    const step = entry.step ?? ctx.step ?? "S2";
    if (!isStepId(step)) return;
    const persistent: PersistentLedgerEntry = {
      step,
      event: "quota_wait_for_reset",
      pool: entry.pool,
      ...(entry.resetAt !== undefined ? { resetAt: entry.resetAt } : {}),
      reason: entry.reason,
      ...(entry.workerPid !== undefined ? { workerPid: entry.workerPid } : {}),
      ts: entry.ts,
      sessionId: "quota-wait-for-reset",
      prompt_hash: "quota-wait-for-reset",
      branchHEAD: "quota-wait-for-reset",
    };
    await this.writeLedger(persistent, stateDir);
  }

  /** Child worker dispatch. S7 is a local family handoff and has no worker. */
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    return legacyDispatchWorker(this, spec, ctx, landing);
  }

  /**
   * #684: production monitored-CLI spawn for productive workers.
   *
   * Returns a host-side bridge spawn so {@link dispatchWorkerWithMonitor} takes
   * the monitored branch (handle atomic with real dispatch). The bridge child
   * re-enters {@link dispatchWorker} with ORCHESTRATOR_CLI_MONITOR_CHILD=1 so
   * these hooks short-circuit and the existing container seam does the work.
   * Absent log sink / non-productive kind / already-in-child → undefined.
   */
  resolveCliMonitorDispatch(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): CliMonitorSpawnSpec | undefined {
    return buildCliMonitorSpawnSpec({
      backendKind: "real",
      backendOpts: this.opts,
      spec,
      ctx,
      landing,
    });
  }

  resolveTelemetryDir(ctx: DispatchContext): string | undefined {
    return durableTelemetryDirForSingleSlice(this.workingRepo, ctx.stateDir);
  }

  /**
   * #684: map a finished monitored CLI bridge child into a WorkerResult by
   * reading the result sidecar the child wrote.
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

  /**
   * #683: probe at the live #684 monitor threshold. The monitor owns the
   * verified pid-tree kill; this backend only applies the quota state machine
   * and records a wait row when the pool returns 429.
   */
  async handleMonitoredWorkerIdle(
    handle: WorkerMonitorHandle,
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<"hang" | "hang_with_live_pool" | "wait_for_reset"> {
    const result = await handleIdleThreshold({
      // #686: a same-model relay may have changed provider/billing pool. Probe
      // the active dispatch pool carried by the runner whenever it is present.
      modelRef: ctx.billingPool ?? spec.model,
      worker: { pid: handle.pid, step: spec.id },
      actions: {
        killPidTree: () => undefined,
        // Runner parkQuotaWaitForReset writes the single durable marker with
        // real audit fields — avoid a second placeholder write here.
        recordLedger: async () => undefined,
      },
      probe: (pool) => this.runQuotaProbe(pool),
    });
    if (result.disposition.kind === "wait_for_reset") {
      throw new QuotaWaitForResetError(result);
    }
    return result.probe.kind === "ok" ? "hang_with_live_pool" : "hang";
  }

  // ── #255: detect resume residue ────────────────────────────────────────────
  async findResumeState(issueNumber: number): Promise<ResumeState | undefined> {
    const existing = this.findExistingWorktree(issueNumber);
    if (existing === undefined) return undefined;
    const stateDir = this.stateDirFor(existing.path, issueNumber);
    const ledger = this.readLedger(stateDir);
    if (ledger === undefined) return undefined;
    const worktree = { branch: existing.branch, base: "main", path: existing.path };
    return { worktree, stateDir, ledger };
  }

  private stateDirFor(wtPath: string, issueNumber: number): string {
    const trimmed = wtPath.replace(/[/\\]+$/, "");
    const lastSep = Math.max(trimmed.lastIndexOf("/"), trimmed.lastIndexOf("\\"));
    const parent = lastSep >= 0 ? trimmed.slice(0, lastSep) : ".";
    return join(parent, `.ledger-${issueNumber}`);
  }

  private readLedger(stateDir: string):
    | ResumeState["ledger"]
    | undefined {
    let raw: string;
    try {
      raw = readFileSync(join(stateDir, "steps.jsonl"), "utf8");
    } catch {
      // The ledger file is missing / unreadable: there is NO resume truth, so
      // there is nothing to resume. Returning undefined (vs []) makes
      // findResumeState treat it as "no ledger" — distinct from an empty-but-
      // valid ledger ([]) and distinct from a CORRUPT ledger (parse throws).
      return undefined;
    }
    // The ledger file EXISTS: parse it fail-closed. A non-empty line that does
    // not parse means the ledger is CORRUPT — parseLedgerJsonl throws, which
    // propagates out of findResumeState to the runner's S8(error) bail path.
    // We must NOT skip corrupt lines (256 r5): a skipped
    // tagged S8(error) would re-report ERROR as SUCCESS, and an all-corrupt file
    // collapsing to [] would be reinterpreted as "no progress" over a resident
    // branch that still carries prior commits.
    return parseLedgerJsonl(raw);
  }

  // ── #249: ledger persistence (sibling JSONL) ───────────────────────────────
  async writeLedger(
    entry: PersistentLedgerEntry,
    stateDir: string,
  ): Promise<void> {
    mkdirSync(stateDir, { recursive: true });
    appendFileSync(
      join(stateDir, "steps.jsonl"),
      JSON.stringify(entry) + "\n",
      "utf8",
    );
  }

  // ── #256 optional true-value helpers (read by the runner's ledger) ─────────
  async readPromptContent(promptFile: string): Promise<string | undefined> {
    try {
      return readFileSync(join(this.opts.promptsDir, promptFile), "utf8");
    } catch {
      return undefined;
    }
  }

  async worktreeHead(worktree: WorktreeHandle): Promise<string | undefined> {
    try {
      const head = this.sh("git", ["rev-parse", "HEAD"], worktree.path).trim();
      return head.length > 0 ? head : undefined;
    } catch {
      return undefined;
    }
  }

  /** Recover the issue number from the resident branch name. */
  private issueOf(worktree: WorktreeHandle): number {
    return issueNumberFromBranch(worktree.branch);
  }
}
