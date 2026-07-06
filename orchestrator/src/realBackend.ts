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
 *     construction, the prompt-content hash, the branchHEAD consistency check,
 *     the failedStep attribution, the resume error fallback decision — is
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

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
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
import { isAbsolute, join, resolve } from "node:path";

import * as sc from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { z } from "zod";

import {
  hasBoundedReopenCondition,
  hasExplicitAcceptedSuppressionSource,
} from "./acceptedSuppression.js";
import { writeContainerCodexConfig } from "./containerCodexConfig.js";
import { runExclusive } from "./gitMutex.js";
import { findingIdentityKey } from "./findings.js";
import {
  sourceAuthFailureStopSummary,
  type StopSummary,
} from "./stopSummary.js";
import {
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
} from "./modelRegistry.js";
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
import { legacyDispatchWorker, SHIP_PROMPT_FILE } from "./dispatchWorker.js";
import { WORKER_PROMPT_FILES } from "./runner.js";
import {
  shipOutcomeFromResult,
  type ShipWorkerOutcome,
} from "./shipOutcome.js";
import {
  WORKER_OUTCOME_REPO_FILE,
  WORKER_OUTCOME_SANDBOX_FILE,
  readRequiredWorkerOutcomeSidecar as readRequiredOutcomeSidecar,
  readWorkerOutcomeSidecar as readOutcomeSidecar,
  stripJsonFence as stripOutcomeJsonFence,
} from "./workerOutcomeSidecar.js";
import type {
  AgentStepRunOptions,
  Backend,
  DispatchContext,
  Finding,
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
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "./types.js";

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
  for (const block of porcelainOut.split("\n\n")) {
    const lines = block.split("\n");
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
 *
 * RESUME-COMPAT DEFERRED (R1 T2 codex): `findResumeState`/`prepareWorktree` locate
 * the resident worktree by EXACT branch name, so a run cut under the OLD name and
 * resumed after this rename would be re-cut fresh (lost ledger/progress). No such
 * in-flight run exists across this rename (issue numbers are unique; the dogfood's
 * old-name worktrees are closed), so it does not trigger here — but a migration
 * old-alias lookup is tracked for if cross-upgrade resume becomes a need.
 */
export function branchForIssue(issueNumber: number): string {
  return `feat/issue-${issueNumber}`;
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
/** Worker path to the runner-owned machine outcome sidecar JSON. */
export const SANDBOX_OUTCOME_PATH_ENV = "ORCHESTRATOR_OUTCOME_PATH";
/** Optional ship-worker focus file read by the ship prompt before gstack-ship. */
export const SHIP_FOCUS_FILENAME = ".ship-focus.md";

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
 */
export const WORKER_IDLE_TIMEOUT_SECONDS = 604_800;

/**
 * Marks the container as an orchestrator-spawned, non-interactive session.
 * gstack-ship reads OPENCLAW_SESSION → its spawned path auto-chooses the
 * recommended option on AskUserQuestion instead of blocking/improvising (the
 * orchestrator's only human touchpoint is structured escalation, never a
 * worker-level prompt). Central set: add future tools' spawned-detection keys here.
 */
export const SPAWNED_WORKER_ENV: Record<string, string> = { OPENCLAW_SESSION: "1" };

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
  /** Host file holding the durable claude OAuth token. */
  readonly claudeTokenFile: string;
}

/**
 * The single-slice ship worker's BEST-EFFORT auth (mirrors the family
 * {@link import("./family/realFamilyBackend.js").ShipAuth}). The ship worker pushes
 * + `gh pr create` (needs codex/gh creds) and may run on a Claude-family model
 * (needs its own claude token then) — but each source is OPTIONAL here: a missing
 * source degrades that leg, it never crashes the ship (#336 cmr S336 r1: the inline
 * `mountAuth` threw on any missing credential, blocking ship in degraded auth envs).
 */
export interface ShipAuth {
  /** Per-run codex auth dir (host-mirrored `~/.codex`), or undefined if absent. */
  readonly codexAuthDir?: string;
  /** The claude OAuth token (env var), or undefined if absent. */
  readonly claudeToken?: string;
  /**
   * The gh OAuth token (`gh auth token` on the host → {@link SANDBOX_GH_TOKEN_ENV}
   * env), or undefined if absent. Unlike the codex leg this is NOT best-effort: the
   * ship worker's happy path pushes + `gh pr create`, both of which need it — so
   * `runShipWorker` preflights it and escalates when absent (cmr S336 r10).
   */
  readonly ghToken?: string;
}

export function buildAuthPaths(
  issueNumber: number,
  home: string = homedir(),
): AuthPaths {
  return {
    hostCodexAuthDir: join(home, ".sc-orchestrator", `auth-${issueNumber}`),
    srcCodexAuth: join(home, ".codex", "auth.json"),
    srcCodexConfig: join(home, ".codex", "config.toml"),
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
 * misconfigured spec, mirroring how {@link modelIdForSlug} throws on a bad slug
 * and {@link assertCompletionSignal} throws on a missing signal). The mismatch
 * throws → the runner's S8(error) edge, never a silently-mis-souled run.
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
  const expected: StepSoul = spec.role === "reviewer" ? "READ-ONLY" : "coder";
  if (spec.soul !== expected) {
    throw new Error(
      `realBackend: step role "${spec.role}" requires the "${expected}" soul ` +
        `but the StepSpec carries "${spec.soul}". v0.1 selects the baked soul ` +
        `by role (#244 "role 决定注哪份 soul"; ADR 0017 §4 one-image-two-roles); ` +
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
  /**
   * The matched completion signal, or `undefined` if no signal fired before the
   * iteration limit (Sandcastle d.ts). The step-advance gate keys off this — see
   * {@link assertCompletionSignal}.
   */
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

/**
 * The number of commits Sandcastle observed on the resident branch during a run
 * = `result.commits.length` (#256 commit-truth). This is the SINGLE SOURCE OF
 * TRUTH the coder path reconciles its self-reported `commitsAdded` against (see
 * {@link reconcileCoderCommits}), reading the {@link RunResultLike.commits} field
 * the Backend previously declared but never consumed. Mirrors
 * {@link lastSessionId}: a tiny accessor so the wiring is unit-tested without a
 * container.
 */
export function realCommitCount(
  result: Pick<RunResultLike, "commits">,
): number {
  return result.commits.length;
}

// ── completion-signal gate (ship-pre 256 r1) ────────────────────────────────

/**
 * Assert a step's run fired the EXACT completion signal its {@link StepSpec}
 * declared, BEFORE the caller decodes the output and advances the step.
 *
 * WHY (ship-pre 256 r1, design-compliance / real-Backend wiring): Sandcastle's
 * `RunResult.completionSignal` is "`undefined` if no signal fired before the
 * iteration limit" (sandcastle d.ts). Passing `completionSignal: spec.…` into
 * `run()` only tells the sandbox WHICH string ends the step early — it does NOT
 * make the run fail when the signal never fires. So an agent that emits a
 * complete, schema-valid `<coder>`/`<review>` tag but hits `maxIter` mid-work
 * WITHOUT firing `CODER_STEP_COMPLETE` / `REVIEWER_STEP_COMPLETE` would have its
 * output decoded and the step advanced — violating #244's gate "agent emit
 * completionSignal 才进下一步" (issue body; StepSpec.completionSignal doc
 * "Required so the sandbox knows when to stop"). A totally-missing output
 * already throws (extractCoderTag / schema.parse → S8(error)); this closes the
 * complete-but-UNSIGNALED leak the missing-output throw does not cover.
 *
 * On mismatch/undefined: THROW. The caller (runStep / resumeSession) lets it
 * propagate to the runner's error edge = S8(error) + error package, never a
 * silently-trusted advance. `stepName` is woven into the message so the runner
 * attributes the failure to the right step.
 *
 * Pure (a check on the RunResultLike shape): unit-tested without a container.
 */
export function assertCompletionSignal(
  result: Pick<RunResultLike, "completionSignal">,
  expected: string,
  stepName: string,
): void {
  if (result.completionSignal !== expected) {
    const actual =
      result.completionSignal === undefined
        ? "none (no signal fired before the iteration limit)"
        : `"${result.completionSignal}"`;
    throw new Error(
      `realBackend: step ${stepName} did not fire its required completion ` +
        `signal — expected "${expected}", got ${actual}. The agent must emit ` +
        `the completion signal to advance the step (#244 "agent emit ` +
        `completionSignal 才进下一步"); a complete-but-unsignaled run (e.g. ` +
        `maxIter hit mid-work) does NOT advance.`,
    );
  }
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
 * validate; throws a clear error when the tag is missing (the caller turns that
 * into the runner's S8(error) edge, same as a malformed structured output).
 */
function extractTaggedJson(
  stdout: string,
  tag: "coder" | "review",
  missingMessage: string,
): unknown {
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
    throw new Error(missingMessage);
  }

  for (let i = starts.length - 1; i >= 0; i -= 1) {
    const bodyStart = starts[i] + open.length;
    const end = stdout.indexOf(close, bodyStart);
    if (end === -1) continue;
    const body = stdout.slice(bodyStart, end).trim();
    return parseTaggedJsonBody(body);
  }

  throw new Error(missingMessage);
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

export function extractCoderTag(stdout: string): unknown {
  return extractTaggedJson(
    stdout,
    "coder",
    "realBackend: coder step stdout carried no <coder>…</coder> tag — the " +
      "coder must emit its structured result in a <coder> tag (maxIter>1 " +
      "steps cannot use Sandcastle's typed output, which requires " +
      "maxIterations:1).",
  );
}

function extractReviewerTag(stdout: string): unknown {
  return extractTaggedJson(
    stdout,
    "review",
    "realBackend: reviewer step stdout carried no <review>…</review> tag — " +
      "the reviewer must emit its structured result in a <review> tag.",
  );
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

// ── coder commit truth from git (#256 truthification) ───────────────────────

/** The self-reported coder JSON a step emits (already shape-validated). */
export interface SelfReportedCoder {
  readonly committed: boolean;
  readonly commitsAdded: number;
  readonly escalate?: { readonly reason: string; readonly diagnosis: string };
  readonly repairEvidence?: RepairEvidence;
}

/**
 * Reconcile a coder step's SELF-REPORTED `{committed, commitsAdded}` against the
 * REAL number of commits Sandcastle observed on the resident branch
 * (`result.commits.length`), and return a git-TRUTHED coder output.
 *
 * WHY (integ-cmr 256 r4, real-backend-wiring / commit-truth): the coder reports
 * `committed` / `commitsAdded` in its `<coder>` tag, but a model can claim a
 * commit it never made (`{committed:true, commitsAdded:1}` with ZERO real
 * commits). Trusting the self-report routes that step to S2/S5 SUCCESS, slipping
 * the #252 0-commit edge and defeating the very truthification this slice was
 * assigned (the in-tree `validate.ts` note: "deriving the real count from git is
 * #256"). The single source of truth is git — `result.commits.length` — so:
 *
 *   - committed   ← realCommitCount > 0
 *   - commitsAdded ← realCommitCount
 *
 * The self-report is kept only as a CROSS-CHECK: a self-report that contradicts
 * git (claims a commit git did not see, or miscounts) is a contract violation →
 * THROW. The caller (runStep / resumeSession) lets that propagate to the runner's
 * error edge = S8(error) + error package, never a silently-trusted success.
 *
 * `escalate` is a MODEL signal (not derivable from git), so it is preserved from
 * the self-report verbatim — but it does NOT suppress a commit-count
 * contradiction (an escalating coder that miscounts its commits still throws).
 *
 * Pure (no I/O): the caller supplies the real commit count from `result.commits`,
 * so the reconciliation is unit-tested without a container.
 */
export function reconcileCoderCommits(
  selfReported: SelfReportedCoder,
  gitCommitCount: number,
): SelfReportedCoder {
  const committed = gitCommitCount > 0;
  // Cross-check the self-report against git truth; a contradiction is a contract
  // violation (the model claimed a commit count git does not back).
  if (
    selfReported.committed !== committed ||
    selfReported.commitsAdded !== gitCommitCount
  ) {
    throw new Error(
      `realBackend: coder self-report {committed:${selfReported.committed}, ` +
        `commitsAdded:${selfReported.commitsAdded}} contradicts git ` +
        `(${gitCommitCount} real commit${gitCommitCount === 1 ? "" : "s"} on ` +
        `the resident branch). The commit count is derived from git, not the ` +
        `model's claim (#256 truthification); a divergent self-report is a ` +
        `contract violation → S8(error).`,
    );
  }
  const base = {
    committed,
    commitsAdded: gitCommitCount,
    ...(selfReported.repairEvidence !== undefined
      ? { repairEvidence: selfReported.repairEvidence }
      : {}),
  };
  return selfReported.escalate !== undefined
    ? { ...base, escalate: selfReported.escalate }
    : base;
}

export interface ResumeCoderCommitBasis {
  readonly baselineHead?: string;
  readonly priorCommitsAdded?: number;
}

/**
 * Locate the git truth basis for a resumed coder step.
 *
 * On escalate-resume, the runner re-opens the agent entry that escalated and
 * truncates it from the in-memory ledger, but the persisted ledger still has the
 * superseded coder entry plus the branch HEADs around it. The cumulative commit
 * truth for the resumed output is therefore:
 *
 *   commits from the ledger entry immediately BEFORE the resumed coder step
 *   through the current resident HEAD.
 *
 * If an older ledger has no usable SHA, the previous coder output's truthified
 * `commitsAdded` is retained as a fallback basis; the caller adds any commits
 * created during the resume iteration via a before/after HEAD diff.
 */
export function resumeCoderCommitBasis(
  ledger: ReadonlyArray<{
    readonly sessionId?: string;
    readonly branchHEAD?: string;
    readonly output?: StepOutput;
  }>,
  sessionId: string,
): ResumeCoderCommitBasis {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const entry = ledger[i]!;
    if (entry.sessionId !== sessionId || entry.output?.kind !== "coder") {
      continue;
    }
    let baselineHead: string | undefined;
    for (let j = i - 1; j >= 0; j--) {
      const head = ledger[j]?.branchHEAD;
      if (typeof head === "string" && isLikelySha(head)) {
        baselineHead = head;
        break;
      }
    }
    return {
      ...(baselineHead !== undefined ? { baselineHead } : {}),
      priorCommitsAdded: entry.output.commitsAdded,
    };
  }
  return {};
}

export function reconcileResumeCoderCommits(
  selfReported: SelfReportedCoder,
  cumulativeGitCommitCount: number,
): SelfReportedCoder {
  try {
    return reconcileCoderCommits(selfReported, cumulativeGitCommitCount);
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    throw new Error(`resume coder commit truth mismatch: ${reason}`);
  }
}

// ── branchHEAD consistency (codex#2) ────────────────────────────────────────

/**
 * codex#2 — ledger.branchHEAD vs the live worktree HEAD consistency check.
 *
 * After an agent step, the runner records the worktree HEAD SHA in the ledger
 * (#256 branchHEAD truth). On resume the recorded SHA must still match the live
 * worktree HEAD — a mismatch means the resident branch moved out from under the
 * ledger (a stray external commit, a wrong-worktree reuse, a corrupted ledger),
 * so continuing would attribute new work to a base the ledger never saw.
 *
 * Returns a structured verdict: `ok` when the two agree (or when the ledger has
 * no recorded SHA yet — nothing to contradict), else a `mismatch` carrying both
 * SHAs so the caller can decide (the real Backend logs + bails to a clean error
 * rather than silently continuing on a divergent base).
 *
 * Pure (string compare) so it is unit-tested without git.
 */
export type HeadConsistency =
  | { readonly ok: true }
  | { readonly ok: false; readonly ledgerHead: string; readonly liveHead: string };

export function checkBranchHeadConsistency(
  ledgerBranchHEAD: string | undefined,
  liveHead: string | undefined,
): HeadConsistency {
  // No recorded SHA (fresh / branch-name fallback) or no live SHA to compare —
  // nothing to contradict.
  if (
    ledgerBranchHEAD === undefined ||
    ledgerBranchHEAD.length === 0 ||
    liveHead === undefined ||
    liveHead.length === 0
  ) {
    return { ok: true };
  }
  // A SHA is a 40-char hex (or an abbreviation) — only compare when the ledger
  // value looks like a SHA, not the v0.1 branch-name fallback (which contains
  // "/" or non-hex chars). A branch-name ledger value pre-dates the SHA truth
  // and must not raise a false mismatch.
  if (!isLikelySha(ledgerBranchHEAD)) return { ok: true };
  return ledgerBranchHEAD === liveHead
    ? { ok: true }
    : { ok: false, ledgerHead: ledgerBranchHEAD, liveHead };
}

/** A git SHA / abbreviation: only lower-case hex, length 7–40. */
export function isLikelySha(s: string): boolean {
  return /^[0-9a-f]{7,40}$/.test(s);
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
 * The throw propagates out of {@link RealBackend.findResumeState} to the same
 * S8(error) bail the codex#2 HEAD-mismatch uses — fail closed, exactly as the
 * r2 F2 rule (a completeness failure must not become a lenient default) requires.
 *
 * Pure (string scan) so the corrupt-ledger boundary is unit-tested without the
 * filesystem.
 */
/**
 * Valid step ids (S0–S8). A persisted ledger record must carry one of these in
 * `step`: {@link planResume} dereferences `lastEntry.step` to route the resume,
 * so a record whose `step` is missing / non-string / out-of-range is unusable.
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

/**
 * A parsed JSONL record is a usable ledger entry only if it is a non-null object
 * whose `step` is a valid {@link StepId}. (`output` / `handoffStatus` are
 * optional, so the minimal valid entry is `{step}`.)
 *
 * Online codex P2: a line such as `null`, `{}`, `42`, or `{"step":"S9"}`
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
  return typeof step === "string" && STEP_IDS.has(step);
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
          "entry (must be an object with a valid step S0–S8) — refusing to " +
          "resume on a malformed ledger (fail closed). Accepting it could crash " +
          "the resume route or re-report the wrong terminal state; bailing to " +
          "S8(error) instead.",
      );
    }
    entries.push(parsed);
  }
  return entries;
}

/**
 * The most recent recorded `branchHEAD` **SHA** in a persisted ledger (codex#2
 * resume reconciliation). Scans from the end and returns the FIRST value that
 * passes {@link isLikelySha} — i.e. skips branch-name fallbacks ENTIRELY, not
 * just empty entries.
 *
 * Why SHA-only (integ-cmr 256 r2, F1): `resolveBranchHEAD` records the branch
 * NAME whenever `worktreeHead()` returns undefined / throws (a transient git
 * read fault), so a ledger can interleave `[realSha, branchNameFallback]` — a
 * later name fallback masking an earlier REAL SHA. If this returned the latest
 * non-empty value, that name would flow into {@link checkBranchHeadConsistency},
 * which sees a non-SHA and returns `{ok:true}` — SKIPPING a real divergence and
 * defeating the entire codex#2 guard (resume could continue on a divergent
 * base). Returning the last REAL recorded SHA makes the consistency check always
 * reconcile against the true base. Returns undefined when no entry carries a SHA
 * (fresh / name-only ledger) — the consistency check then has nothing to
 * contradict.
 *
 * Pure (array scan) so the resume reconciliation decision is unit-tested
 * without git: `lastLedgerBranchHead(ledger)` feeds
 * {@link checkBranchHeadConsistency} against the live HEAD, and a mismatch bails
 * `findResumeState` to a clean error (S8(error) at the runner).
 */
export function lastLedgerBranchHead(
  ledger: ReadonlyArray<{ readonly branchHEAD?: string }>,
): string | undefined {
  for (let i = ledger.length - 1; i >= 0; i--) {
    const head = ledger[i]?.branchHEAD;
    // Only a real SHA counts: a branch-name fallback (later git read fault) must
    // NOT mask an earlier real SHA, or the consistency check would short-circuit
    // to {ok:true} and skip a genuine divergence (F1).
    if (typeof head === "string" && isLikelySha(head)) return head;
  }
  return undefined;
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
 *   parse failure, auth/model failure, commit-truth contradiction) propagates to
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
 * Every versioned promptFile a single-slice WORKER the runner dispatches resolves
 * at run time. The real Backend resolves each as `join(promptsDir, promptFile)`,
 * so all must exist under `promptsDir` or the real path cannot run end-to-end
 * (#256 AC "对一个真叶子 issue 端到端跑通").
 *
 * Route-independent prompt inventory: prompt validation must not import a
 * route-bearing StepSpec snapshot, because model routes are resolved per run.
 * Keep this derived from the worker prompt-file constants plus the S7 ship spec.
 */
export const REFERENCED_PROMPT_FILES: ReadonlyArray<string> = [
  ...new Set([
    ...Object.values(WORKER_PROMPT_FILES),
    SHIP_PROMPT_FILE,
    "integrated_cmr_completeness.md",
    "integrated_cmr_correctness.md",
  ]),
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
      `must be present (S2 coder, S3/S6 reviewer, S5 coder-fix, and S7 ship reference them).`
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
  /** The profile image (#253): toolchain + souls + model CLIs baked in. */
  readonly imageName: string;
  /**
   * DEPRECATED (#334): host dir of dev skills to bind-mount. The 2b worker image
   * (#333) BAKES the dev-skill closure, so `box()` no longer mounts host skills at
   * runtime (a runtime mount would SHADOW the baked skills — the ADR 0026
   * reproducibility regression). Kept OPTIONAL only for back-compat with callers
   * still passing it; it is no longer read. Remove the field entirely once all
   * callers drop it (#336/#337 cleanup).
   */
  readonly skillsMount?: string;
  /**
   * Dir holding the versioned promptFiles (`coder_implement.md` for S2,
   * `reviewer_review.md` for S3/S6, `coder_fix.md` for S5, and `ship.md` for
   * S7). ADR 0030 keeps the single-slice review/fix loop runner-visible: S3/S6
   * are reviewer workers, and S5 is the coder-fix worker.
   *
   * MUST be an ABSOLUTE path (validated at construction, F4): Sandcastle
   * resolves `promptFile` against `process.cwd()`, NOT the run `cwd` option
   * (index.d.ts), so a relative `promptsDir` would silently resolve the prompt
   * against the wrong directory at run time. The dir must exist and contain every
   * {@link REFERENCED_PROMPT_FILES} entry, or the constructor throws.
   */
  readonly promptsDir: string;
  /** Override $HOME for auth path construction (tests). */
  readonly home?: string;
  /**
   * #291: the LOCAL family base branch on this clone (ADR 0022 decision 7), set
   * ONLY when this Backend drives a family run's CHILD slices. When a child's
   * `prepareWorktree` base equals this, the slice is cut from the LOCAL family
   * base (no `git fetch origin`, no `origin/` prefix) — because the family base
   * is a local branch the merger accumulates onto, with no remote counterpart;
   * deriving it as `origin/<family-base>` would cut from a stale/absent remote ref
   * missing the prior waves (agy R1). Absent ⇒ a standalone single-slice run: the
   * cut base is "main", fetched + cut as `origin/main` exactly as before.
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
const findingDispositionSchema = z
  .object({
    kind: z.literal("accepted_suppressed"),
    source: z.string().min(1),
    scope: z.string().min(1),
    reason: z.string().min(1),
    findingIdentity: z.string().min(1).optional(),
    boundedReopen: z.string().min(1),
  })
  .superRefine((disposition, ctx) => {
    if (!hasExplicitAcceptedSuppressionSource(disposition.source)) {
      ctx.addIssue({
        code: "custom",
        path: ["source"],
        message: "accepted_suppressed requires explicit user/ADR/issue source",
      });
    }
    if (!hasBoundedReopenCondition(disposition.boundedReopen)) {
      ctx.addIssue({
        code: "custom",
        path: ["boundedReopen"],
        message: "accepted_suppressed requires bounded reopen condition",
      });
    }
  });
const findingSchema = z.object({
  severity: z.enum(["critical", "high", "medium", "low", "clarity"]),
  category: z.string(),
  claim_quote: z.string(),
  location: z.string(),
  suggested_fix: z.string(),
  action: z.enum(["fix_now", "defer", "wont_fix", "rejected"]),
  disposition_reason: z.string().optional(),
  disposition: findingDispositionSchema.optional(),
}).superRefine((finding, ctx) => {
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
  if (
    finding.action === "defer" &&
    (finding.disposition === undefined ||
      finding.disposition.kind === "accepted_suppressed")
  ) {
    ctx.addIssue({
      code: "custom",
      path: ["disposition"],
      message: "deferred findings require a non-suppression disposition",
    });
  }
});
function normalizeReviewerFinding(finding: Finding): Finding {
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
const priorFindingDispositionSchema = z.object({
  identityKey: z.string().min(1),
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
}).superRefine((disposition, ctx) => {
  if (disposition.status !== "accepted_suppressed") return;
  for (const field of ["reason", "source", "scope", "boundedReopen"] as const) {
    if (disposition[field] === undefined || disposition[field].trim() === "") {
      ctx.addIssue({
        code: "custom",
        path: [field],
        message: `accepted_suppressed prior finding disposition requires ${field}`,
      });
    }
  }
  if (
    disposition.source !== undefined &&
    !hasExplicitAcceptedSuppressionSource(disposition.source)
  ) {
    ctx.addIssue({
      code: "custom",
      path: ["source"],
      message: "accepted_suppressed prior finding disposition requires explicit user/ADR/issue source",
    });
  }
  if (
    disposition.boundedReopen !== undefined &&
    !hasBoundedReopenCondition(disposition.boundedReopen)
  ) {
    ctx.addIssue({
      code: "custom",
      path: ["boundedReopen"],
      message: "accepted_suppressed prior finding disposition requires bounded reopen condition",
    });
  }
});
const reviewerOutputSchema = z.object({
  findings: z.array(findingSchema),
  priorFindingDispositions: z.array(priorFindingDispositionSchema).optional(),
  escalate: z
    .object({ reason: z.string(), diagnosis: z.string() })
    .optional(),
});
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
    .object({ reason: z.string(), diagnosis: z.string() })
    .optional(),
});

/** Parse a coder worker self-report with the same schema the single-slice path uses. */
export function parseCoderSelfReport(raw: unknown): SelfReportedCoder {
  return coderOutputSchema.parse(raw);
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
    this.workingRepo = this.buildOrReuseClone();
    this.assertIndependentClone();
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
   * If the working repo is a linked worktree, a Sandcastle/`cleanResidue` prune
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
   * Run a host `gh`/`git` command, returning trimmed stdout. `protected` so a
   * test subclass can intercept the git/gh seam without a real container or repo
   * (integ-cmr 256 r3 reuse-fail-closed test).
   */
  protected sh(file: string, args: string[], cwd?: string): string {
    return execFileSync(file, args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      encoding: "utf8",
    }).trim();
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
      // S0 reads ONLY the gate fields: labels (ready-for-agent) + state (closed?,
      // #2) here, plus the native sub-issue count + blocked_by from their own
      // queries below. It does NOT pull body/comments — the Agent Brief is no
      // longer an S0 gate (#328), so `comments` would only trigger gh's paginated
      // preloadIssueComments for no consumer, and S1's full snapshot re-fetches
      // both anyway (#329 perf).
      const raw = this.sh("gh", [
        "issue",
        "view",
        String(issueNumber),
        "--repo",
        this.opts.repo,
        "--json",
        "number,labels,state",
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
    // the best-effort `git fetch`, the residue clean, and the `git worktree add`
    // cut all MUTATE the shared `.git` — concurrent ones race on `.git/index.lock`
    // / per-ref locks (distinct child BRANCHES isolate the logical work, NOT the
    // git locks). So the whole git-mutating section runs under a per-clone mutex
    // keyed on the working repo: same-clone children serialise their cuts, while a
    // DIFFERENT clone (another run in the same process) never blocks. A standalone
    // single-slice run is the degenerate single-holder case (no contention).
    return runExclusive(this.workingRepo, () =>
      this.prepareWorktreeLocked(issueNumber, base),
    );
  }

  /** The git-mutating body of {@link prepareWorktree}, run under the per-clone mutex. */
  private async prepareWorktreeLocked(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    const branch = branchForIssue(issueNumber);
    // Idempotent reuse: if the resident worktree exists, reuse it (the runner's
    // #255 resume path drives this); else cut a fresh one from `base` (main).
    //
    // integ-cmr 256 r3 (idempotent_reuse_dirty): reuse is FAIL-CLOSED. The runner
    // reaches this fresh path even for an existing worktree when the ledger is
    // missing/unreadable (findResumeState → undefined ⇒ no resume ⇒ no
    // cleanResidue). Returning the dir AS-IS would reuse a prior crash's
    // uncommitted residue / stale commits as a "fresh" start (ADR0017: 复用前清
    // 未提留残留). So clean residue (reset --hard HEAD → clean -fd) BEFORE
    // returning, so a no-ledger old branch can never masquerade as a clean fresh
    // cut and leak residue into the pushed branch. (Repo-level prune handed back
    // to Sandcastle — ADR 0024 dec. 2.)
    const existing = this.findExistingWorktree(branch);
    if (existing !== undefined) {
      this.cleanResidueAt(existing);
      return { branch, base, path: existing };
    }
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
    // resolve a stale remote branch) and force the bare local ref. A standalone
    // single-slice run (base="main", no `familyBase` option) keeps the fetch +
    // `origin/main` derivation byte-identical.
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

  private findExistingWorktree(branch: string): string | undefined {
    try {
      const out = this.sh("git", ["worktree", "list", "--porcelain"], this.workingRepo);
      return matchWorktreeForBranch(out, branch);
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
  } {
    const paths = buildAuthPaths(issueNumber, this.opts.home);
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
    writeContainerCodexConfig(join(paths.hostCodexAuthDir, "config.toml"));
    // The Claude token is BEST-EFFORT (#384 codex P2). The coder step now runs
    // Codex (model gpt-5.5), so it no longer needs CLAUDE_CODE_OAUTH_TOKEN. A host
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
    return { authDir: paths.hostCodexAuthDir, claudeToken };
  }

  private box(
    issueNumber: number,
    spec: StepSpec,
    options?: AgentStepRunOptions,
  ): sc.SandboxProvider {
    const auth = this.mountAuth(issueNumber);
    return docker(
      this.boxConfig(
        { ...auth, ghToken: this.readGhToken() },
        spec,
        issueNumber,
        options,
      ),
    );
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
   * a real sandbox (#334 — so the dropped-skillsMount behaviour is regression-
   * guarded the same way the family merger's mount is).
   *
   * #334 (ADR 0026 / cross-slice note from #332/#333): the runtime host
   * `skillsMount` bind-mount onto {@link SANDBOX_SKILLS_DIR} is DROPPED. The 2b
   * worker image (#333) BAKES the full dev-skill closure at that exact path, so
   * mounting host skills there at runtime would SHADOW the baked skills — pulling
   * the worker back to host state (the ADR 0026 reproducibility regression). The
   * baked image is now the single source of skills; the only mount left is the
   * per-issue codex auth dir (a live secret, not bakeable).
   *
   * ship-pre 256 r1: `soulForStep(spec)` selects the role's baked soul and
   * injects it via {@link SANDBOX_SOUL_ENV} so the v0.1 one-image-two-roles
   * profile activates the right one (#244 "role 决定注哪份 soul"); it throws on a
   * spec whose `soul` contradicts its `role` → S8(error). Still a soul ENV
   * signal, not an OS readonly mount (reviewer READ-ONLY stays soft, ADR 0017 §4).
   */
  protected boxConfig(
    auth: { authDir: string; claudeToken?: string; ghToken?: string },
    spec: StepSpec,
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
    // Inject the Claude token only when present: a Codex coder (model gpt-5.5)
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
    if (options?.outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = options.outcomeLanding.sandboxPath;
    }
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [
      { hostPath: auth.authDir, sandboxPath: SANDBOX_CODEX_DIR },
    ];
    if (options?.fixFindingsLanding !== undefined) {
      mounts.push({
        hostPath: options.fixFindingsLanding.path,
        sandboxPath: options.fixFindingsLanding.sandboxPath,
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
      // #334: codex auth stays the only always-on runtime mount; S5 adds the
      // runner-owned fix findings file as a narrow read-only overlay.
      mounts,
    };
  }

  /** Build the output definition for a step's role. */
  private outputFor(spec: StepSpec): sc.OutputDefinition {
    return spec.role === "reviewer"
      ? sc.Output.object({ tag: "review", schema: reviewerOutputSchema })
      : sc.Output.object({ tag: "coder", schema: coderOutputSchema });
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
  ): unknown {
    try {
      if (options?.outcomeLanding?.path !== undefined) {
        const sidecar = readOutcomeSidecar(options.outcomeLanding.path);
        if (sidecar !== undefined) return sidecar;
      }
    } catch (err) {
      if (spec.role === "reviewer") {
        const wrapped = new Error(
          `StructuredOutputError: reviewer outcome sidecar was not valid JSON: ` +
            `${err instanceof Error ? err.message : String(err)}`,
        );
        wrapped.name = "StructuredOutputError";
        throw wrapped;
      }
      throw err;
    }
    if (typedOutputUsed) return result.output;
    // Untyped compatibility path: structured result lives in the role tag.
    return spec.role === "coder"
      ? extractCoderTag(result.stdout)
      : extractReviewerTag(result.stdout);
  }

  /**
   * Decode a Sandcastle structured output into a domain StepOutput.
   *
   * `gitCommitCount` is `result.commits.length` (via {@link realCommitCount}) —
   * the number of commits Sandcastle observed THIS run. For a coder step on the
   * NORMAL completion path it is the SINGLE SOURCE OF TRUTH for `committed` /
   * `commitsAdded` (#256 truthification): the self-reported `<coder>` tag is
   * reconciled against git via {@link reconcileCoderCommits}, which derives the
   * count from git and throws on a contradiction (a model claiming a commit it
   * never made) — the caller propagates that to the runner's S8(error) edge.
   *
   * `gitCommitCount === undefined` is allowed only for roles where commit truth
   * is irrelevant (reviewer). A resumed coder still gets git-truthed, but the
   * count is cumulative from the persisted ledger baseline to the resident HEAD,
   * not `result.commits.length`: resume may only re-emit corrected structured
   * output while earlier commits already live on the branch.
   *
   * Ignored for the reviewer role (commits are not part of a review's contract).
   */
  private decodeOutput(
    spec: StepSpec,
    raw: unknown,
    gitCommitCount: number | undefined,
  ): StepOutput {
    if (spec.role === "reviewer") {
      const r = reviewerOutputSchema.parse(raw);
      const findings: Finding[] = r.findings.map((f) =>
        normalizeReviewerFinding({ ...f }),
      );
      return {
        kind: "reviewer",
        findings,
        ...(r.priorFindingDispositions !== undefined
          ? { priorFindingDispositions: r.priorFindingDispositions }
          : {}),
        ...(r.escalate ? { escalate: r.escalate } : {}),
      };
    }
    // Coder: parse the self-report for shape, then TRUTH the commit count from
    // git. Fresh runs use result.commits.length; resumed runs pass a cumulative
    // ledger-baseline count. A contradiction throws → S8(error) at the runner.
    const c = coderOutputSchema.parse(raw);
    if (gitCommitCount === undefined) {
      throw new Error(
        "realBackend: coder output decoded without git commit truth. " +
          "Fresh and resumed coder steps must reconcile committed/commitsAdded " +
          "against git; trusting the model self-report would bypass S8(error).",
      );
    }
    const out = reconcileCoderCommits(c, gitCommitCount);
    const repairEvidence =
      out.repairEvidence !== undefined
        ? { repairEvidence: out.repairEvidence }
        : {};
    return out.escalate
      ? {
          kind: "coder",
          committed: out.committed,
          commitsAdded: out.commitsAdded,
          ...repairEvidence,
          escalate: out.escalate,
        }
      : {
          kind: "coder",
          committed: out.committed,
          commitsAdded: out.commitsAdded,
          ...repairEvidence,
        };
  }

  private resumeCoderCommitCount(
    worktree: WorktreeHandle,
    sessionId: string,
    beforeResumeHead: string | undefined,
  ): number {
    const stateDir = this.stateDirFor(worktree.path, this.issueOf(worktree));
    const ledger = this.readLedger(stateDir);
    const basis =
      ledger === undefined ? {} : resumeCoderCommitBasis(ledger, sessionId);
    if (basis.baselineHead !== undefined) {
      return this.countCommitsSince(worktree, basis.baselineHead);
    }
    if (basis.priorCommitsAdded !== undefined) {
      if (beforeResumeHead === undefined) {
        throw new Error(
          `realBackend: cannot git-truth resumed coder session ${sessionId}; ` +
            "the persisted ledger only has a prior commit count fallback, but " +
            "the before-resume HEAD could not be read. Refusing to count " +
            "resume-only commits as zero.",
        );
      }
      const resumeOnlyCommits =
        this.countCommitsSince(worktree, beforeResumeHead);
      return basis.priorCommitsAdded + resumeOnlyCommits;
    }
    throw new Error(
      `realBackend: cannot git-truth resumed coder session ${sessionId}; ` +
        "the persisted ledger has no matching coder entry with a baseline HEAD " +
        "or prior commit count. Refusing to trust the resumed <coder> self-report.",
    );
  }

  async countCommitsBetween(
    worktree: WorktreeHandle,
    fromHead: string,
    toHead: string,
  ): Promise<number> {
    return this.countCommitsInRange(worktree, `${fromHead}..${toHead}`);
  }

  private countCommitsSince(worktree: WorktreeHandle, fromHead: string): number {
    return this.countCommitsInRange(worktree, `${fromHead}..HEAD`);
  }

  private countCommitsInRange(worktree: WorktreeHandle, range: string): number {
    const raw = this.sh(
      "git",
      ["rev-list", "--count", range],
      worktree.path,
    );
    const count = Number.parseInt(raw, 10);
    if (!Number.isInteger(count) || count < 0) {
      throw new Error(
        `realBackend: git rev-list returned invalid commit count "${raw}" ` +
          `for ${range} in ${worktree.path}`,
      );
    }
    return count;
  }

  // ── S2/S3/S5/S6 agent workers (ADR 0030; #256 seam extension returns
  //    StepResult). S2/S5 run the coder soul; S3/S6 run the fresh read-only
  //    reviewer soul. The runner owns the visible review/fix loop and threads
  //    S4 blocking findings to S5 through DispatchContext/landing artifacts. ─
  private async runFreshAgentStep(
    spec: StepSpec,
    worktree: WorktreeHandle,
    options?: AgentStepRunOptions,
    coderCommitCount?: (result: Pick<RunResultLike, "commits">) => number,
  ): Promise<StepResult> {
    const issueNumber = this.issueOf(worktree);
    await this.preflightToolchain(spec);
    const typedOutputUsed =
      spec.maxIter === 1 && options?.outcomeLanding === undefined;
    const result = await this.runAgentSandbox({
      name: `${spec.id}-${spec.role}`,
      idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
      cwd: worktree.path,
      sandbox: this.box(issueNumber, spec, options),
      // The build worker's CLI is the spec's model slug → provider (the S2 coder
      // runs on Codex gpt-5.5; a claude slug stays claudeCode). agentForSlug keeps
      // the "model slug → baked CLI" #244 mapping unit-testable.
      agent: agentForSlug(spec.model),
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
    });
    // #244 step-advance gate: the step only advances if the agent fired its
    // declared completionSignal. A complete-but-unsignaled run (e.g. maxIter hit
    // mid-work) throws here → S8(error), before any output is decoded.
    assertCompletionSignal(result, spec.completionSignal, `${spec.id}-${spec.role}`);
    const raw = this.rawOutputFor(result, spec, typedOutputUsed, options);
    // #256 commit-truth: the coder's committed/commitsAdded is derived from the
    // REAL commits Sandcastle observed (result.commits), not the self-report.
    const gitCommitCount =
      spec.role === "coder"
        ? (coderCommitCount?.(result) ?? realCommitCount(result))
        : undefined;
    const output = this.decodeOutput(spec, raw, gitCommitCount);
    return { output, sessionId: lastSessionId(result) };
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
    const beforeResumeHead =
      spec.role === "coder" ? await this.worktreeHead(worktree) : undefined;
    await this.preflightToolchain(spec);
    try {
      const typedOutputUsed = options?.outcomeLanding === undefined;
      const result = await this.runAgentSandbox({
        name: `${spec.id}-${spec.role}-resume`,
        idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
        cwd: worktree.path,
        sandbox: this.box(issueNumber, spec, options),
        // Resume the build worker on the SAME CLI as its fresh run (agentForSlug:
        // codex for the gpt-5.5 coder, claudeCode for a claude slug).
        agent: agentForSlug(spec.model),
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
      });
      // #244 step-advance gate (resume path): a resumed step still only advances
      // on its declared completionSignal — an unsignaled resume throws → S8(error).
      assertCompletionSignal(
        result,
        spec.completionSignal,
        `${spec.id}-${spec.role}-resume`,
      );
      // Resume path: git-truth against the cumulative resident-branch commit
      // count, not this one-iteration result.commits.length. The resumed
      // iteration may only re-emit the structured tag while prior commits already
      // live on the branch.
      const gitCommitCount =
        spec.role === "coder"
          ? this.resumeCoderCommitCount(worktree, sessionId, beforeResumeHead)
          : undefined;
      const output = this.decodeOutput(
        spec,
        this.rawOutputFor(result, spec, typedOutputUsed, options),
        gitCommitCount,
      );
      return { output, sessionId: lastSessionId(result) ?? sessionId };
    } catch (err) {
      // Dead-session fallback (#256/#285): ONLY a clearly missing/dead prior
      // session falls back to a fresh run() (keep committed worktree progress,
      // lose in-session memory). Signal mismatches, schema parse failures, auth
      // failures, model errors, and commit-truth contradictions propagate to the
      // runner's S8(error) edge instead of being masked by a fresh run.
      const recovery = classifyResumeError(err);
      if (recovery.kind === "fresh-run") {
        // Re-dispatch the build worker (a dead resume session ⇒ start a fresh
        // sandbox.run for the same step). Coder commit truth still uses the
        // resume ledger baseline, because prior committed work may already live
        // on the resident branch even though the old session is gone.
        const coderCommitCount =
          spec.role === "coder"
            ? () => this.resumeCoderCommitCount(worktree, sessionId, beforeResumeHead)
            : undefined;
        return await this.runFreshAgentStep(
          spec,
          worktree,
          options,
          coderCommitCount,
        );
      }
      throw err;
    }
  }

  protected async runAgentSandbox(
    options: Parameters<typeof sc.run>[0],
  ): Promise<Awaited<ReturnType<typeof sc.run>>> {
    return await sc.run(options);
  }

  // ── S7: ship WORKER (invoke gstack-ship) ────────────────────────────────────

  /**
   * THE single-slice worker-dispatch seam (ADR 0026 / #331 / #336). The S7 ship
   * step is dispatched here as a CONTAINER ship WORKER that invokes `gstack-ship`
   * (#336) — replacing the inline `push` (a bare `git push`). Every OTHER worker
   * kind (coder / reviewer agent steps) is forwarded to {@link legacyDispatchWorker}
   * (runStep / resumeSession), which #334 already routes to the real `/tdd` /
   * `/code-review` workers — so THIS method takes over ONLY the ship leg.
   *
   * The ship worker (`shipWorkerSpec`) = the 2b container's TOP-LEVEL claude; it
   * `Skill`-invokes gstack-ship (base merge / tests / diff review / VERSION /
   * CHANGELOG / commit / push / `gh pr create`). It returns the full
   * {@link WorkerResult} mapping (PRD #330 R2): shipped → `completed` ShipResult;
   * a genuine block (merge conflict / review ASK / hard defect) → `escalated`; a
   * hard ship/test failure → `failed`; an unparseable run → `malformed`. A
   * rerun-able flake is NOT escalated — the worker reruns it itself (用户 note).
   */
  async dispatchWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
    landing?: WorkerLandingPayload,
  ): Promise<WorkerResult> {
    if (spec.kind !== "ship") {
      // #336 owns the ship leg; coder/reviewer agent workers stay on the existing
      // runStep/resumeSession seam (#334 routes them to /tdd / /code-review). The
      // rich landing payload (blocking findings) travels straight to the landing
      // file (信封宪法, ADR 0062).
      return legacyDispatchWorker(this, spec, ctx, landing);
    }
    if (ctx.worktree === undefined) {
      throw new Error(
        "dispatchWorker(ship): a ship worker requires ctx.worktree (the resident " +
          "slice branch gstack-ship delivers).",
      );
    }
    const outcome = await this.runShipWorker(spec, ctx);
    if (outcome.kind === "escalate") {
      // A GENUINE block (merge conflict the skill can't resolve / a review ASK / a
      // hard defect needing a human decision) — the WorkerResult-level escalate
      // (续跑 path; runner.ts S7 takes the S8(escalate) handoff). NOT a rerun-able
      // flake (the worker reruns those itself) and NOT a fabricated PR.
      return {
        kind: "escalated",
        escalation: { reason: outcome.reason, diagnosis: outcome.diagnosis },
      };
    }
    if (outcome.kind === "failed") {
      // A hard ship command / test failure no rerun cleared → the delivery could
      // not complete (runner.ts S7 maps non-completed to S8(error)).
      return { kind: "failed", reason: `${outcome.reason} — ${outcome.diagnosis}` };
    }
    if (outcome.kind === "malformed") {
      // No parseable verdict / no completion signal ⇒ malformed (never a success).
      return { kind: "malformed", reason: outcome.reason };
    }
    // Branch-identity check (cmr S336 r3 F1): the worker self-reports `branch`, and
    // a worker that ships some OTHER branch (e.g. the resident base `main`) but
    // reports it as a success must NOT be read as a delivery. prompts/ship.md asks
    // the worker to report THE shipped branch — the resident slice branch already
    // checked out (`branchStrategy:{type:"head"}`), with no legitimate rename path —
    // so an `outcome.branch` ≠ the worktree branch it was asked to deliver is
    // off-contract → malformed (never trust the self-reported branch identity).
    if (outcome.branch !== ctx.worktree.branch) {
      return {
        kind: "malformed",
        reason: `ship worker reported branch "${outcome.branch}" but was asked to deliver "${ctx.worktree.branch}" (a ship of a different branch is not the slice delivery)`,
      };
    }
    return {
      kind: "completed",
      output: {
        kind: "ship",
        branch: outcome.branch,
        status: outcome.status,
        ...(outcome.pr !== undefined ? { pr: outcome.pr } : {}),
      },
    };
  }

  /**
   * Run the ship WORKER: ONE `sc.run` of the 2b container's route-selected agent
   * invoking `gstack-ship` over the resident slice worktree (#336). `protected` so
   * a unit test fixtures the outcome without a real container (the real container
   * only runs on the driver / manual-smoke / e2e path).
   *
   * The worker is the container's TOP-LEVEL agent (so gstack-ship's own pipeline +
   * any rerun loops run inside it — ADR 0026), under the WRITE (`coder`) soul (it
   * commits the VERSION/CHANGELOG bump + pushes). `branchStrategy:{type:"head"}`
   * keeps it on the resident branch (the ADR 0017 commit真源). Its `<ship>` tag is
   * gated on the completion signal then classified by {@link shipOutcomeFromResult}.
   */
  protected async runShipWorker(
    spec: WorkerSpec,
    ctx: DispatchContext,
  ): Promise<ShipWorkerOutcome> {
    const worktree = ctx.worktree!;
    // FAIL-CLOSED on the WORKER's OWN auth (cmr S336 r8, mirroring the family ship
    // preflight + the cmr worker's claude-token guard): the ship worker is the
    // container's TOP-LEVEL claude (`agent: sc.claudeCode` below), so the Claude
    // OAuth token is NOT a degradable codex LEG — it is THIS worker's auth.
    // Absent, the worker cannot start and never emits a `<ship>` verdict; that would
    // throw out of `sc.run` (NOT a structured escalate). runner S7 DOES wrap this
    // dispatch in a try/catch → errorTermination (so a thrown start would not
    // crash the host outright), but an UNCAUGHT start-error is read as S8(error), not
    // the cleaner escalate续跑 the missing-auth case deserves (a human must supply the
    // token, not "the ship command failed"). So preflight and return a structured
    // escalate BEFORE the container — symmetric with the family path. The gh token is
    // ALSO preflighted below (cmr S336 r10): it is load-bearing for the push +
    // `gh pr create`, NOT a degradable leg — the 2b image bakes the gh CLI but no gh
    // auth, so a no-gh host must escalate, not fail late in-container. Only codex auth
    // stays best-effort (it merely degrades the in-container diff review). Mount once
    // and reuse for the sandbox (no double-mount).
    // `mountShipAuth` creates a per-call temp codex auth dir (mkdtempSync — a unique
    // name each call) BEFORE the early escalate gates below; the finally reclaims it
    // on success, exception, AND those early returns (online review r1 — 3 bots:
    // leaked temp dirs accumulating under the codex-auth root).
    const auth = this.mountShipAuth(this.issueOf(worktree));
    try {
      if (modelFamilyForSlug(spec.model) === "claude" && auth.claudeToken === undefined) {
        return {
          kind: "escalate",
          reason: "no Claude worker auth (CLAUDE_CODE_OAUTH_TOKEN) — the ship worker cannot start",
          diagnosis: "ship worker cannot start without CLAUDE_CODE_OAUTH_TOKEN",
        };
      }
    // FAIL-CLOSED on gh auth (cmr S336 r10): UNLIKE the codex leg (best-effort — it
    // only degrades the in-container diff review), gh auth is LOAD-BEARING for the
    // ship itself — gstack-ship Step 17 pushes over https (gh credential helper) and
    // Step 19 runs `gh pr create`. The 2b image bakes the gh CLI but no gh auth, so a
    // no-gh host would run the whole pipeline only to fail at push / `gh pr create` —
    // an opaque late failure, not the cleaner escalate续跑 (a human must supply gh
    // creds). So preflight it like the claude token (r8) and escalate BEFORE the
    // container. The host token is read via `gh auth token` (it lives in the OS
    // keyring, not a portable file) and injected as GH_TOKEN by shipSandboxConfig.
      if (auth.ghToken === undefined) {
        return {
          kind: "escalate",
          reason: "no gh auth (GH_TOKEN) — the ship worker cannot push / `gh pr create`",
          diagnosis:
            "the ship worker invokes gstack-ship, which pushes over https + runs " +
            "`gh pr create`; the 2b image bakes the gh CLI but no gh auth. Provide a " +
            "host gh login (`gh auth login`) so `gh auth token` yields a token to inject " +
            "as GH_TOKEN. Escalating here keeps the escalate续跑 semantics (a late " +
            "in-container `gh pr create` failure would surface as an opaque S8 error).",
        };
      }
      this.syncShipFocusFile(ctx);
      const outcomeLanding = this.prepareShipOutcomeLanding(ctx);
      try {
        const result = await this.runAgentSandbox({
          name: `${spec.id}-ship`,
          idleTimeoutSeconds: WORKER_IDLE_TIMEOUT_SECONDS,
          cwd: worktree.path,
          sandbox: this.shipSandbox(auth, outcomeLanding),
          agent: agentForSlug(spec.model),
          // The ship worker self-reruns gstack-ship's rerun-able steps INSIDE the
          // container (用户 note); maxIter is the within-worker budget. A genuine block
          // is the worker's `<ship>` escalate verdict, not the iteration limit.
          maxIterations: spec.maxIter,
          completionSignal: spec.completionSignal,
          // Commit the VERSION/CHANGELOG bump + push on the resident branch in place.
          branchStrategy: { type: "head" },
          promptFile: join(this.opts.promptsDir, spec.promptFile),
        });
        return shipOutcomeFromResult({
          ...result,
          ...(outcomeLanding !== undefined ? { outcomePath: outcomeLanding.path } : {}),
        });
      } finally {
        if (outcomeLanding !== undefined) {
          try {
            rmSync(join(outcomeLanding.path, ".."), { recursive: true, force: true });
          } catch {
            // best-effort: the run already returned/threw.
          }
        }
      }
    } finally {
      // Reclaim the per-call temp codex auth dir (online review r1, 3 bots):
      // best-effort — a failed cleanup must never mask the worker's outcome.
      if (auth.codexAuthDir !== undefined) {
        try {
          rmSync(auth.codexAuthDir, { recursive: true, force: true });
        } catch {
          // best-effort: the run already returned/threw.
        }
      }
    }
  }

  /**
   * Keep the single-slice ship focus file in sync with the current dispatch. S7
   * normally ships with no focus file, but an answered decision escalation must be
   * visible to the clean ship worker session that is retrying the blocked delivery.
   */
  protected syncShipFocusFile(ctx: DispatchContext): void {
    const worktree = ctx.worktree;
    if (worktree === undefined) return;
    const target = join(worktree.path, SHIP_FOCUS_FILENAME);
    const answer = ctx.escalationAnswer;
    if (answer === undefined) {
      rmSync(target, { force: true });
      return;
    }
    this.excludeShipFocusFromGit(worktree.path);
    const body =
      `# Single-slice ship focus (machine-generated; #439)\n\n` +
      `A human answered a prior S7 decision escalation. Retry the ship worker with\n` +
      `this answer in force; do not repeat the same HITL stop unless a new blocker\n` +
      `remains.\n\n` +
      `\`\`\`json\n${JSON.stringify(answer, null, 2)}\n\`\`\`\n`;
    writeFileSync(target, body, "utf8");
  }

  protected prepareShipOutcomeLanding(
    ctx: DispatchContext,
  ): { path: string; sandboxPath: string } | undefined {
    if (ctx.stateDir === undefined || ctx.worktree === undefined) return undefined;
    mkdirSync(ctx.stateDir, { recursive: true });
    const dir = mkdtempSync(join(ctx.stateDir, "worker-outcome-ship-"));
    const path = join(dir, "outcome.json");
    writeFileSync(path, "", "utf8");
    this.excludeRuntimeFileFromGit(ctx.worktree.path, WORKER_OUTCOME_REPO_FILE);
    return { path, sandboxPath: WORKER_OUTCOME_SANDBOX_FILE };
  }

  /** Add the generated ship focus file to local git excludes so it is never committed. */
  protected excludeShipFocusFromGit(worktreePath: string): void {
    this.excludeRuntimeFileFromGit(worktreePath, SHIP_FOCUS_FILENAME);
  }

  protected excludeRuntimeFileFromGit(worktreePath: string, filename: string): void {
    try {
      const excludePath = this.sh(
        "git",
        ["rev-parse", "--git-path", "info/exclude"],
        worktreePath,
      );
      const abs = isAbsolute(excludePath)
        ? excludePath
        : resolve(worktreePath, excludePath);
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
    } catch {
      // Non-git fixtures still get the focus file; real worktrees get the exclude.
    }
  }

  /**
   * The ship worker's sandbox: the 2b image (gstack-ship + gh + bun baked in,
   * #333) under the WRITE (`coder`) soul, with the codex auth mounted + the claude
   * and gh tokens injected as env (the ship worker pushes + `gh pr create`, so it
   * needs the live credentials). Takes the ALREADY-gathered {@link ShipAuth} (mirrors
   * the family `shipSandbox`) so `runShipWorker` gathers once: preflight the claude +
   * gh tokens THEN build the sandbox from the same auth (no double-gather).
   * `protected` so a unit test asserts the mounts + soul without a real container.
   */
  protected shipSandbox(
    auth: ShipAuth,
    outcomeLanding?: { path: string; sandboxPath: string },
  ): sc.SandboxProvider {
    return docker(this.shipSandboxConfig(auth, outcomeLanding));
  }

  /**
   * Gather the ship worker's host credentials (#336 cmr S336 r1): the codex auth dir
   * (mounted), the claude OAuth token (env), and the gh OAuth token (`gh auth token`
   * → GH_TOKEN env, cmr S336 r10). Gathering is fail-soft per source (each in its OWN
   * try/catch ⇒ a missing source is undefined, never a crash here).
   *
   * Unlike the agent-step `mountAuth` (which THROWS on any missing credential), the
   * GATHER is tolerant; the REQUIRE gates (claude + gh — both load-bearing for the
   * ship) live in `runShipWorker`'s preflight, the codex leg degrades silently. NOT
   * keyed by issue here for the codex dir — a fresh temp dir per call keeps it
   * self-contained; the claude token is read straight off the host, the gh token via
   * the gh CLI (it lives in the OS keyring, not a portable file).
   */
  protected mountShipAuth(issueNumber: number): ShipAuth {
    const paths = buildAuthPaths(issueNumber, this.opts.home);
    let codexAuthDir: string | undefined;
    let tempCodexDir: string | undefined;
    try {
      const root = join(paths.hostCodexAuthDir, "..");
      mkdirSync(root, { recursive: true, mode: 0o700 });
      tempCodexDir = mkdtempSync(join(root, `ship-codex-auth-${issueNumber}-`));
      copyFileSync(paths.srcCodexAuth, join(tempCodexDir, "auth.json"));
      chmodSync(join(tempCodexDir, "auth.json"), 0o600);
      // The container IS the sandbox boundary; codex must NOT self-sandbox (nested
      // bwrap is impossible). The host config.toml is host-personal and irrelevant
      // — only auth.json crosses. Write the minimal container config (#378).
      writeContainerCodexConfig(join(tempCodexDir, "config.toml"));
      codexAuthDir = tempCodexDir;
    } catch {
      // codex auth absent ⇒ the codex leg degrades (no mount), no crash. gh is NOT
      // here — it is the separate, preflighted ghToken (cmr S336 r10). Reclaim the
      // mkdtemp dir if it was created before copy/chmod threw (online review r2,
      // gemini): on the degrade path codexAuthDir stays undefined, so the per-
      // invocation dir would otherwise leak past the caller's finally cleanup.
      if (codexAuthDir === undefined && tempCodexDir !== undefined) {
        rmSync(tempCodexDir, { recursive: true, force: true });
      }
    }
    let claudeToken: string | undefined;
    try {
      const tok = readFileSync(paths.claudeTokenFile, "utf8").trim();
      // A present-but-empty/blank token file ⇒ undefined (the ship preflight
      // escalates), NOT an injected empty CLAUDE_CODE_OAUTH_TOKEN="" that defeats
      // the gate (cmr int-r3 A; matches readGhToken's empty-string normalization).
      claudeToken = tok === "" ? undefined : tok;
    } catch {
      // claude token absent ⇒ Claude-family workers fail their preflight; non-Claude
      // route slots simply run without this env var.
    }
    return { codexAuthDir, claudeToken, ghToken: this.readGhToken() };
  }

  /**
   * Read the host's gh OAuth token via `gh auth token` (cmr S336 r10). The token
   * lives in the host's OS keyring (not a portable hosts.yml), so we extract it with
   * gh itself and inject it as {@link SANDBOX_GH_TOKEN_ENV} into the container.
   * Returns undefined when gh is unauthenticated / not installed (the `runShipWorker`
   * preflight then escalates — gh is a hard ship requirement). `protected` so a unit
   * test stubs it without spawning gh.
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
   * The docker options the ship worker sandbox runs under — the pure
   * SANDBOX-CONFIG seam (mirrors `boxConfig` / the family `shipSandboxConfig`
   * testability). No container, no I/O: a unit test asserts the mounts + soul env
   * without a real sandbox. The ship worker runs under the `coder` (WRITE) soul
   * (it commits the bump + pushes) with codex auth + the claude token + the gh token
   * (GH_TOKEN — push over https + `gh pr create`, cmr S336 r10), each set only when
   * present (#336 cmr S336 r1), NO skills mount (the 2b image BAKES gstack-ship — a
   * runtime mount would SHADOW it, #334).
   */
  protected shipSandboxConfig(
    auth: ShipAuth,
    outcomeLanding?: { path: string; sandboxPath: string },
  ): {
    imageName: string;
    env: Record<string, string>;
    mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string }>;
  } {
    // The ship worker runs under the dedicated "ship" soul (delivery discipline:
    // gstack-ship, stop-at-PR, defer→tracker not PR body) — souls/ship.md covers
    // both single-slice and family deliveries, so the single-slice ship is unified
    // with the family ship rather than left on the coder soul (gemini #384 R3).
    // ORCHESTRATOR_REPO too: the ship soul records a deferred finding with
    // `gh issue create --repo "$ORCHESTRATOR_REPO"`, so the sandbox must export it
    // or that tracker write fails on an unset var (codex #384). Mirrors boxConfig.
    const env: Record<string, string> = {
      ...SPAWNED_WORKER_ENV,
      [SANDBOX_SOUL_ENV]: "ship",
      [SANDBOX_REPO_ENV]: this.opts.repo,
    };
    if (auth.claudeToken !== undefined) env.CLAUDE_CODE_OAUTH_TOKEN = auth.claudeToken;
    // cmr S336 r10: the in-container `gh` (push over https + `gh pr create`)
    // authenticates from GH_TOKEN. Set only when present (the pure seam stays
    // tolerant; the REQUIRE-gh gate is the runShipWorker preflight).
    if (auth.ghToken !== undefined) env[SANDBOX_GH_TOKEN_ENV] = auth.ghToken;
    if (outcomeLanding !== undefined) {
      env[SANDBOX_OUTCOME_PATH_ENV] = outcomeLanding.sandboxPath;
    }
    const mounts: { hostPath: string; sandboxPath: string }[] = [];
    // #334: codex auth ONLY — baked skills win (no host skills mount).
    if (auth.codexAuthDir !== undefined) {
      mounts.push({ hostPath: auth.codexAuthDir, sandboxPath: SANDBOX_CODEX_DIR });
    }
    if (outcomeLanding !== undefined) {
      mounts.push({
        hostPath: outcomeLanding.path,
        sandboxPath: outcomeLanding.sandboxPath,
      });
    }
    return { imageName: this.opts.imageName, env, mounts };
  }

  /**
   * The legacy inline push (#252 escalate-residue path). RETAINED as a `protected`
   * fallback the seam no longer reaches on the production path: ADR 0026 / #336
   * makes S7 a ship WORKER (gstack-ship via {@link dispatchWorker}). A direct
   * caller (a test / a legacy back-compat path that bypasses the unified seam) may
   * still reach it; the runner never does (it always goes through dispatchWorker).
   */
  async push(worktree: WorktreeHandle): Promise<void> {
    this.sh(
      "git",
      ["push", "-u", "origin", worktree.branch],
      worktree.path,
    );
  }

  // ── #255: clean uncommitted residue before reuse ───────────────────────────
  async cleanResidue(worktree: WorktreeHandle): Promise<void> {
    this.cleanResidueAt(worktree.path);
  }

  /**
   * The ADR0017 residue-clean applied to a worktree path before it is reused:
   * `git reset --hard HEAD` (drop uncommitted tracked changes) → `git clean -fd`
   * (drop untracked files/dirs). Factored out so BOTH the #255 resume path
   * (cleanResidue) and the r3 fail-closed reuse path (prepareWorktree, no-ledger
   * reuse) share one sequence.
   *
   * ADR 0024 decision 2: the repo-level `git worktree prune` that used to run here
   * is REMOVED. It both duplicated Sandcastle's own per-acquire `pruneStale` AND
   * was the cross-session reaper of #292 — with a dedicated clone (decision 1)
   * pruning is Sandcastle's job and physically can't reach another session's
   * worktree admin namespace. This method now ONLY does the per-worktree residue
   * clean; it must not touch repo-level admin state.
   */
  private cleanResidueAt(wtPath: string): void {
    this.sh("git", ["reset", "--hard", "HEAD"], wtPath);
    this.sh("git", ["clean", "-fd"], wtPath);
  }

  // ── #255: detect resume residue ────────────────────────────────────────────
  async findResumeState(issueNumber: number): Promise<ResumeState | undefined> {
    const branch = branchForIssue(issueNumber);
    const wtPath = this.findExistingWorktree(branch);
    if (wtPath === undefined) return undefined;
    const stateDir = this.stateDirFor(wtPath, issueNumber);
    const ledger = this.readLedger(stateDir);
    if (ledger === undefined) return undefined;
    const worktree = { branch, base: "main", path: wtPath };

    // codex#2 — before reusing the resident branch, verify the LAST recorded
    // branchHEAD SHA still matches the live worktree HEAD (integ-cmr 256 r1,
    // F5). A mismatch means the branch moved out from under the ledger (a stray
    // external commit, a wrong-worktree reuse, a corrupted ledger), so resuming
    // would attribute new work to a base the ledger never saw — log + bail to a
    // clean error rather than silently continuing on a divergent base. The
    // runner catches this `findResumeState` throw and turns it into S8(error).
    const ledgerHead = lastLedgerBranchHead(ledger);
    const liveHead = await this.worktreeHead(worktree);
    const verdict = checkBranchHeadConsistency(ledgerHead, liveHead);
    if (!verdict.ok) {
      const msg =
        `resume aborted for issue #${issueNumber}: the resident branch HEAD ` +
        `(${verdict.liveHead}) diverged from the last recorded ledger SHA ` +
        `(${verdict.ledgerHead}). The branch moved out from under the ledger ` +
        `(stray commit / wrong-worktree reuse / corrupted ledger); continuing ` +
        `would attribute new work to a base the ledger never saw.`;
      console.error(`[realBackend] ${msg}`);
      throw new Error(msg);
    }

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
    // propagates out of findResumeState to the same S8(error) bail path as the
    // codex#2 HEAD-mismatch. We must NOT skip corrupt lines (256 r5): a skipped
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
      return this.sh("git", ["rev-parse", "HEAD"], worktree.path);
    } catch {
      return undefined;
    }
  }

  /** Recover the issue number from the resident branch name. */
  private issueOf(worktree: WorktreeHandle): number {
    return issueNumberFromBranch(worktree.branch);
  }
}
