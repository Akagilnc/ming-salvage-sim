/**
 * realBackend.ts — the REAL {@link Backend} implementation (#256).
 *
 * The first slice (#256) that touches the outside world. The nine prior slices
 * (#247–#255) verified the runner's S0–S8 control flow against FAKE Backends; this
 * file gives that same injected seam a real implementation backed by:
 *   - **Sandcastle** (`createWorktree` / `createSandbox` / `run` / `resumeSession`)
 *     for the resident slice worktree + the isolated agent sandboxes,
 *   - **`gh`** (host-side) for issue metadata + the full snapshot (clean-room:
 *     the snapshot is fetched on the HOST and written into the worktree; the
 *     container never reaches the network),
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
 *     the failedStep attribution, the StructuredOutputError dead-session
 *     fallback decision — is factored into exported, dependency-light functions
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
 *   - r3 fix-loop findings leak: same git-ignore check for
 *     `.orchestrator-fix-findings.json` written before an S5 coder_fix run.
 */

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  appendFileSync,
  chmodSync,
  copyFileSync,
  existsSync,
  mkdirSync,
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

import type {
  Backend,
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
  WorktreeHandle,
} from "./types.js";

// ════════════════════════════════════════════════════════════════════════════
// PURE host-side logic (unit-tested in realBackend.logic.test.ts; no container)
// ════════════════════════════════════════════════════════════════════════════

// ── gh issue → IssueMeta / IssueSnapshot parsing ────────────────────────────

/** The `## Agent Brief` heading marks the authoritative implementation spec. */
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
  readonly body?: string | null;
  readonly labels?: ReadonlyArray<{ readonly name?: string }> | null;
  readonly comments?: ReadonlyArray<{ readonly body?: string }> | null;
}

/** Native blocked_by dependency summary from `gh api .../dependencies`. */
export interface GhBlockedBy {
  readonly number: number;
  readonly state: string; // "open" | "closed"
}

/**
 * Does any comment (or the body) carry a `## Agent Brief` section?
 * The brief is the authoritative spec (DEV_WORKFLOW); S0 requires it.
 */
export function hasAgentBrief(json: GhIssueJson): boolean {
  const inBody = (json.body ?? "").includes(AGENT_BRIEF_HEADING);
  const inComments = (json.comments ?? []).some((c) =>
    (c.body ?? "").includes(AGENT_BRIEF_HEADING),
  );
  return inBody || inComments;
}

/** Is the issue labelled ready-for-agent? */
export function isReadyForAgent(json: GhIssueJson): boolean {
  return (json.labels ?? []).some((l) => l.name === READY_FOR_AGENT_LABEL);
}

/**
 * Build the S0 {@link IssueMeta} from the gh JSON + the native blocked_by list +
 * the native sub-issue count. The four-way accept condition the runner enforces
 * is derived from these fields (rfa ∧ Agent Brief ∧ no sub-issues ∧ all
 * blocked_by closed).
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
    hasAgentBrief: hasAgentBrief(json),
    hasSubIssues: subIssueCount > 0,
    openBlockedBy: blockedBy
      .filter((d) => d.state !== "closed")
      .map((d) => d.number),
  };
}

/**
 * Extract the latest `## Agent Brief` body from the issue's comments (falling
 * back to the issue body). The brief is the authoritative spec; the LAST comment
 * carrying it wins (a re-issued brief supersedes earlier ones). Returns "" when
 * no brief is present (S0 would have already rejected such an issue).
 */
export function extractAgentBrief(json: GhIssueJson): string {
  // Priority order, LOWEST first: the issue body is the fallback, then comments
  // in order (newest last). A later carrier overwrites an earlier one, so the
  // LAST brief-bearing COMMENT wins over both earlier comments and the body
  // (a re-issued brief supersedes the original) — the body only stands when no
  // comment carries a brief.
  const carriers = [
    json.body ?? "",
    ...(json.comments ?? []).map((c) => c.body ?? ""),
  ];
  let brief = "";
  for (const text of carriers) {
    if (text.includes(AGENT_BRIEF_HEADING)) brief = text;
  }
  return brief;
}

/**
 * Real shape of `gh issue view --json subIssues`:
 * `{"subIssues":{"nodes":[…],"totalCount":N}}` — an OBJECT, not an array
 * (verified against the live #244: `totalCount:10`). The S0 input gate uses this
 * count to reject a parent epic (`hasSubIssues`), so reading it correctly is
 * load-bearing: an array check on the object is always false → count always 0 →
 * the parent-epic gate never fires (PRD #244 US#3 / S0 four-way condition).
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
 * the snapshot (rather than re-fetching) keeps the clean-room snapshot the single
 * source the container reads (it does NOT gh-fetch inside the box).
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
 * fetched are threaded in here (not re-queried) so the snapshot the coder reads
 * is contract-complete (#244 S1 names native metadata as a snapshot element).
 */
export function buildIssueSnapshot(
  issueNumber: number,
  json: GhIssueJson,
  blockedBy: ReadonlyArray<GhBlockedBy>,
  subIssueCount: number,
): IssueSnapshot {
  return {
    number: json.number ?? issueNumber,
    body: json.body ?? "",
    comments: (json.comments ?? []).map((c) => c.body ?? ""),
    agentBrief: extractAgentBrief(json),
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
 * The host-written fix-loop findings file (integ-cmr 256 r3, fix_loop_context).
 * The runner hands the S5 coder_fix step the round's reviewer `fix_now`
 * findings; the Backend writes them here for the coder to read (coder_fix.md
 * points at this name). Like {@link SNAPSHOT_FILENAME} it is a clean-room
 * artifact that must NEVER be committed — git-ignored (per-worktree
 * `.git/info/exclude` + root `.gitignore`) before any agent run.
 */
export const FIX_FINDINGS_FILENAME = ".orchestrator-fix-findings.json";

/**
 * Serialise the S5 fix_now findings to the on-disk JSON the coder reads
 * (integ-cmr 256 r3). Pure (string assembly) so the contract is unit-testable
 * without a worktree. The shape is a stable top-level object so the file is
 * self-describing and future fields (round index, etc.) extend it without
 * breaking the coder's reader.
 */
export function serializeFixFindings(
  findings: ReadonlyArray<Finding>,
): string {
  return JSON.stringify({ fix_now: findings }, null, 2);
}

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
 * `feat/244-orchestrator-issue-<n>` convention `prepareWorktree` cuts under, and
 * the inverse of {@link issueNumberFromBranch}. Exported so the family layer can
 * recover a child's branch from its issue when reconcile is handed only the issue
 * number (#291, agy/codex R1). Pure → unit-tested without git.
 */
export function branchForIssue(issueNumber: number): string {
  return `feat/244-orchestrator-issue-${issueNumber}`;
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

/**
 * Map a {@link StepSpec.model} slug to the baked-in CLI provider (PRD #244:
 * "换模型 = runtime 选已烤进镜像的 CLI"). coder = Sonnet (claudeCode), reviewer
 * = Opus 4.8 (claudeCode). Pure: returns the model id the provider factory
 * needs, so the mapping is unit-testable without constructing a provider.
 *
 * `"sonnet"` → claude-sonnet-4-6 (coder); `"opus"` → claude-opus-4-8 (reviewer).
 * Any other slug is a misconfigured StepSpec → throw (caught by the runner's
 * error edge, surfaced as S8(error)).
 */
export function modelIdForSlug(slug: string): string {
  switch (slug) {
    case "sonnet":
      return "claude-sonnet-4-6";
    case "opus":
      return "claude-opus-4-8";
    default:
      throw new Error(
        `realBackend: unknown model slug "${slug}" — expected "sonnet" or "opus". ` +
          `Add the CLI to the image and extend modelIdForSlug before using it.`,
      );
  }
}

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
 * StepSpec contract and populated in STEP_SPECS but NEVER consumed by the real
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
 * (the iteration that produced the final output / would be resumed). Undefined
 * when no iteration carried one (non-Claude provider / capture disabled) — the
 * runner then records the run-level UUID fallback.
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
 * On mismatch/undefined: THROW. The caller (runStep / resumeSession /
 * resume-retry) lets it propagate to the runner's error edge = S8(error) +
 * error package, never a silently-trusted advance. `stepName` is woven into the
 * message so the runner attributes the failure to the right step.
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
export function extractCoderTag(stdout: string): unknown {
  // Scan for ALL <coder>…</coder> blocks; the last one is the final iteration's
  // result. `[\s\S]` so the body may span newlines; non-greedy so adjacent tags
  // don't merge.
  const re = /<coder>([\s\S]*?)<\/coder>/g;
  let last: string | undefined;
  for (let m = re.exec(stdout); m !== null; m = re.exec(stdout)) {
    last = m[1];
  }
  if (last === undefined) {
    throw new Error(
      "realBackend: coder step stdout carried no <coder>…</coder> tag — the " +
        "coder must emit its structured result in a <coder> tag (maxIter>1 " +
        "steps cannot use Sandcastle's typed output, which requires " +
        "maxIterations:1).",
    );
  }
  return JSON.parse(stripJsonFence(last.trim()));
}

/**
 * Unwrap a ```json … ``` (or bare ``` … ```) fenced code block to its inner
 * payload, mirroring Sandcastle's fence-aware tag extraction. Returns the input
 * unchanged when it is not fenced.
 */
export function stripJsonFence(s: string): string {
  const fence = /^```(?:json)?\s*\n?([\s\S]*?)\n?```$/;
  const m = fence.exec(s.trim());
  return m ? m[1].trim() : s;
}

// ── coder commit truth from git (#256 truthification) ───────────────────────

/** The self-reported coder JSON a step emits (already shape-validated). */
export interface SelfReportedCoder {
  readonly committed: boolean;
  readonly commitsAdded: number;
  readonly escalate?: { readonly reason: string; readonly diagnosis: string };
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
  const base = { committed, commitsAdded: gitCommitCount };
  return selfReported.escalate !== undefined
    ? { ...base, escalate: selfReported.escalate }
    : base;
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

// ── StructuredOutputError dead-session fallback decision (#256) ──────────────

/**
 * Decide how to recover when `resumeSession` of a prior session fails because
 * the session is dead/missing (Sandcastle cannot resume a session whose JSONL is
 * gone — a pruned container, a cleaned host store).
 *
 * - A {@link sc.StructuredOutputError} carrying a sessionId means the resumed run
 *   reached the agent but the structured output was malformed → recover by
 *   resuming THAT session id with a corrective prompt (Sandcastle's own pattern).
 * - A dead-session error (no resumable session) means the original session is
 *   gone → fall back to a FRESH `run()` (lose in-session memory, keep the
 *   committed worktree progress — the resident branch survives).
 *
 * Pure: classifies the error only; the caller performs the chosen recovery.
 */
export type ResumeRecovery =
  | { readonly kind: "retry-structured"; readonly sessionId: string }
  | { readonly kind: "fresh-run" };

export function classifyResumeError(err: unknown): ResumeRecovery {
  if (err instanceof sc.StructuredOutputError && err.sessionId) {
    return { kind: "retry-structured", sessionId: err.sessionId };
  }
  // Any other resume failure (dead/missing session, transport) → fresh run.
  return { kind: "fresh-run" };
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
 * Every versioned promptFile the runner's STEP_SPECS reference (S2/S3/S5/S6).
 * The real Backend resolves each as `join(promptsDir, promptFile)`, so all four
 * must exist under `promptsDir` or the real path cannot run end-to-end (#256 AC
 * "对一个真叶子 issue 端到端跑通"). Kept in lock-step with `runner.ts` STEP_SPECS.
 */
export const REFERENCED_PROMPT_FILES = [
  "coder_implement.md",
  "reviewer_full_review.md",
  "coder_fix.md",
  "reviewer_rereview.md",
] as const;

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
      `must be present (the runner's S2/S3/S5/S6 reference them).`
    );
  }
  return undefined;
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
  /** The profile image (#253): toolchain + souls + model CLIs baked in. */
  readonly imageName: string;
  /** Host dir holding the baked dev skills to bind-mount (spike). */
  readonly skillsMount: string;
  /**
   * Dir holding the versioned promptFiles (`coder_implement.md`,
   * `reviewer_full_review.md`, `coder_fix.md`, `reviewer_rereview.md`).
   *
   * MUST be an ABSOLUTE path (validated at construction, F4): Sandcastle
   * resolves `promptFile` against `process.cwd()`, NOT the run `cwd` option
   * (index.d.ts), so a relative `promptsDir` would silently resolve the prompt
   * against the wrong directory at run time. The dir must exist and contain all
   * four referenced files, or the constructor throws.
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

/** zod schema for the reviewer step's structured output (route() consumes it). */
const findingSchema = z.object({
  severity: z.enum(["critical", "high", "medium", "low", "clarity"]),
  category: z.string(),
  claim_quote: z.string(),
  location: z.string(),
  suggested_fix: z.string(),
  action: z.enum(["fix_now", "defer"]),
});
const reviewerOutputSchema = z.object({
  findings: z.array(findingSchema),
  escalate: z
    .object({ reason: z.string(), diagnosis: z.string() })
    .optional(),
});
const coderOutputSchema = z.object({
  committed: z.boolean(),
  commitsAdded: z.number().int().nonnegative(),
  escalate: z
    .object({ reason: z.string(), diagnosis: z.string() })
    .optional(),
});

export class RealBackend implements Backend {
  private readonly opts: RealBackendOptions;
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
  private buildOrReuseClone(): string {
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
  private assertIndependentClone(): void {
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
    // slip past the pinned S0 four-way gate and run from a stale base.
    const json = this.phase("S0", "fetchIssueView", () => {
      const raw = this.sh("gh", [
        "issue",
        "view",
        String(issueNumber),
        "--repo",
        this.opts.repo,
        "--json",
        "number,body,labels,comments",
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
   * let a blocked-by-OPEN issue (the pinned S0 four-way reject) run from a stale
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
    // (title/state/labels) into the clean-room snapshot, not just the body —
    // the container reads this LOCAL snapshot and does NOT gh-fetch inside the
    // box (#244 S1: "body + comments + 最新 Agent Brief 正文 + native metadata").
    const json = this.phase("S1", "fetchIssueView", () => {
      const raw = this.sh("gh", [
        "issue",
        "view",
        String(issueNumber),
        "--repo",
        this.opts.repo,
        "--json",
        "number,title,state,body,labels,comments",
      ]);
      return JSON.parse(raw) as GhIssueJson;
    });
    // The native sub-issue + blocked_by summaries (the same ones S0 reads via the
    // GraphQL/REST API) complete the snapshot's native metadata. A thrown
    // gh/transport/parse error propagates → the runner's S1 error termination,
    // attributed to S1 (not S0) for the US#30 error package.
    const subIssueCount = this.fetchSubIssueCount(issueNumber, "S1");
    const blockedBy = this.fetchBlockedBy(issueNumber, "S1");
    return buildIssueSnapshot(issueNumber, json, blockedBy, subIssueCount);
  }

  // ── S1: resident slice worktree (Sandcastle native createWorktree) ─────────
  async prepareWorktree(
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

  /**
   * Write (or clear) the fix-loop findings file the S5 coder reads (integ-cmr
   * 256 r3, fix_loop_context). When `findings` is present (an S5 dispatch), the
   * file is git-ignored first (same belt-and-suspenders as the clean-room
   * snapshot — a coder `git add -A` must never stage host-written context into
   * the pushed branch) then written. When `findings` is undefined (S2/S3/S6, or a
   * fix round whose findings somehow did not survive the seam), any STALE file
   * from a previous round is removed, so a non-fix step / a later round can never
   * read another round's findings. Best-effort on the exclude + remove (a git/fs
   * fault must not block the still-useful write); the write itself surfaces.
   *
   * `protected` so a zero-container test subclass can drive the real on-disk
   * write/delete decision (integ-cmr 256 confirm r2) without a real container —
   * the same seam-exposure rationale as {@link sh}.
   */
  protected writeFixFindings(
    worktree: WorktreeHandle,
    findings: ReadonlyArray<Finding> | undefined,
  ): void {
    const target = join(worktree.path, FIX_FINDINGS_FILENAME);
    if (findings === undefined) {
      // Non-S5 step (or no findings): clear any stale file so it cannot leak.
      try {
        rmSync(target, { force: true });
      } catch {
        // best-effort cleanup
      }
      return;
    }
    this.excludeFromGit(worktree, FIX_FINDINGS_FILENAME);
    writeFileSync(target, serializeFixFindings(findings), "utf8");
  }

  // ── auth mount (spike contract) ────────────────────────────────────────────
  private mountAuth(issueNumber: number): {
    authDir: string;
    claudeToken: string;
  } {
    const paths = buildAuthPaths(issueNumber, this.opts.home);
    rmSync(paths.hostCodexAuthDir, { recursive: true, force: true });
    // Owner-only dir: this holds copied credential material (auth.json /
    // config.toml). 0o700 keeps it off world-readable multi-user hosts
    // (coderabbit R2, major).
    mkdirSync(paths.hostCodexAuthDir, { recursive: true, mode: 0o700 });
    copyFileSync(
      paths.srcCodexAuth,
      join(paths.hostCodexAuthDir, "auth.json"),
    );
    try {
      copyFileSync(
        paths.srcCodexConfig,
        join(paths.hostCodexAuthDir, "config.toml"),
      );
      // config.toml can carry credentials too — owner-only.
      chmodSync(join(paths.hostCodexAuthDir, "config.toml"), 0o600);
    } catch {
      // config.toml is optional.
    }
    // Copied credential file → owner-only (was world-readable 0o644).
    chmodSync(join(paths.hostCodexAuthDir, "auth.json"), 0o600);
    const claudeToken = readFileSync(paths.claudeTokenFile, "utf8").trim();
    return { authDir: paths.hostCodexAuthDir, claudeToken };
  }

  private box(issueNumber: number, spec: StepSpec): sc.SandboxProvider {
    const { authDir, claudeToken } = this.mountAuth(issueNumber);
    // ship-pre 256 r1: select the role's baked soul and inject it so the v0.1
    // one-image-two-roles profile activates the right one (#244 "role 决定注哪份
    // soul"). soulForStep CONSUMES spec.soul (no longer a dead contract field)
    // and throws if it contradicts the role → S8(error). Still a soul ENV signal,
    // not an OS readonly mount (reviewer READ-ONLY stays soft, ADR 0017 §4).
    const soul = soulForStep(spec);
    return docker({
      imageName: this.opts.imageName,
      env: {
        CLAUDE_CODE_OAUTH_TOKEN: claudeToken,
        [SANDBOX_SOUL_ENV]: soul,
      },
      mounts: [
        { hostPath: authDir, sandboxPath: SANDBOX_CODEX_DIR },
        { hostPath: this.opts.skillsMount, sandboxPath: SANDBOX_SKILLS_DIR },
      ],
    });
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
    typedOutputUsed: boolean,
  ): unknown {
    if (typedOutputUsed) return result.output;
    // Untyped coder path: structured result lives in a <coder> tag in stdout.
    return extractCoderTag(result.stdout);
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
   * `gitCommitCount === undefined` skips git-truthing and trusts the self-report
   * (used ONLY on the resume path): a `resumeSession` re-runs ONE iteration that
   * may just re-emit corrected structured output WITHOUT a new commit, so its
   * per-run `result.commits.length` is NOT a reliable cumulative truth (the
   * original run's commits already live on the branch and are not re-counted).
   * Git-truthing there would falsely flag `committed:true` as a 0-commit
   * contradiction. The normal `runStep` completion path the finding targets
   * always passes the real count.
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
      const findings: Finding[] = r.findings.map((f) => ({ ...f }));
      return r.escalate
        ? { kind: "reviewer", findings, escalate: r.escalate }
        : { kind: "reviewer", findings };
    }
    // Coder: parse the self-report for shape, then (normal path) TRUTH the commit
    // count from git (result.commits.length). reconcileCoderCommits throws on a
    // self-report that contradicts git → S8(error) at the runner (never a
    // trusted success). On the resume path (undefined) trust the self-report.
    const c = coderOutputSchema.parse(raw);
    const out =
      gitCommitCount === undefined
        ? c
        : reconcileCoderCommits(c, gitCommitCount);
    return out.escalate
      ? {
          kind: "coder",
          committed: out.committed,
          commitsAdded: out.commitsAdded,
          escalate: out.escalate,
        }
      : {
          kind: "coder",
          committed: out.committed,
          commitsAdded: out.commitsAdded,
        };
  }

  // ── S2/S3/S5/S6: one sandbox.run() (#256 seam extension returns StepResult) ─
  async runStep(
    spec: StepSpec,
    worktree: WorktreeHandle,
    fixNowFindings?: ReadonlyArray<Finding>,
  ): Promise<StepResult> {
    const issueNumber = this.issueOf(worktree);
    // integ-cmr 256 r3 (fix_loop_context): deliver the round's fix_now findings
    // to the S5 coder_fix step by writing them into the (git-ignored) worktree
    // file the coder reads. Set only on S5; other steps pass undefined.
    this.writeFixFindings(worktree, fixNowFindings);
    const result = await sc.run({
      name: `${spec.id}-${spec.role}`,
      cwd: worktree.path,
      sandbox: this.box(issueNumber, spec),
      agent: sc.claudeCode(modelIdForSlug(spec.model)),
      // #7 maxIter: enforce the WITHIN-STEP Ralph retry budget = StepSpec.maxIter
      // (reviewer = 1 single pass; coder/fix > 1). Hitting it ends THE STEP
      // normally — route() continues — it is NEVER the orchestrator giving up
      // (StepSpec.maxIter semantics; the only give-up is a model escalate).
      maxIterations: spec.maxIter,
      completionSignal: spec.completionSignal,
      branchStrategy: { type: "head" }, // commit on the resident branch in place
      promptFile: join(this.opts.promptsDir, spec.promptFile),
      // Structured output only on reviewer single-pass steps (Sandcastle
      // requires maxIterations:1 with output); coder steps iterate (maxIter>1),
      // so their structured result is collected from a <coder> tag in stdout
      // (rawOutputFor) instead — Sandcastle's typed `output` is forbidden there.
      ...(spec.maxIter === 1 ? { output: this.outputFor(spec) } : {}),
    });
    // #244 step-advance gate: the step only advances if the agent fired its
    // declared completionSignal. A complete-but-unsignaled run (e.g. maxIter hit
    // mid-work) throws here → S8(error), before any output is decoded.
    assertCompletionSignal(result, spec.completionSignal, `${spec.id}-${spec.role}`);
    const typedOutputUsed = spec.maxIter === 1;
    const raw = this.rawOutputFor(result, typedOutputUsed);
    // #256 commit-truth: the coder's committed/commitsAdded is derived from the
    // REAL commits Sandcastle observed (result.commits), not the self-report.
    const output = this.decodeOutput(spec, raw, realCommitCount(result));
    return { output, sessionId: lastSessionId(result) };
  }

  // ── #255: resume the prior agent session (native + dead-session fallback) ───
  async resumeSession(
    spec: StepSpec,
    worktree: WorktreeHandle,
    sessionId: string,
    fixNowFindings?: ReadonlyArray<Finding>,
  ): Promise<StepResult> {
    const issueNumber = this.issueOf(worktree);
    // integ-cmr 256 r3 (fix_loop_context): a RESUMED S5 coder_fix step sees the
    // same fix_now findings a fresh S5 would (escalate-resume). Write them BEFORE
    // resuming; the dead-session fallback below re-runs runStep, which writes
    // them again from its own param, so a fresh-run recovery is also covered.
    this.writeFixFindings(worktree, fixNowFindings);
    try {
      const result = await sc.run({
        name: `${spec.id}-${spec.role}-resume`,
        cwd: worktree.path,
        sandbox: this.box(issueNumber, spec),
        agent: sc.claudeCode(modelIdForSlug(spec.model)),
        // resumeSession requires maxIterations:1 (Sandcastle constraint).
        maxIterations: 1,
        completionSignal: spec.completionSignal,
        branchStrategy: { type: "head" },
        resumeSession: sessionId,
        promptFile: join(this.opts.promptsDir, spec.promptFile),
        // A resume ALWAYS runs maxIterations:1, so Sandcastle's typed `output`
        // is valid for BOTH roles here (it only forbids maxIter>1). Pass it by
        // role unconditionally — the old `spec.maxIter===1` gate left a resumed
        // CODER step (spec.maxIter>1) with no `output`, so decodeOutput parsed
        // `undefined` and threw a ZodError on every resumed coder step
        // (integ-cmr 256 r1, F4). Typed output ⇒ read `result.output` directly
        // for both roles (no <coder> stdout fallback needed at maxIter:1).
        output: this.outputFor(spec),
      });
      // #244 step-advance gate (resume path): a resumed step still only advances
      // on its declared completionSignal — an unsignaled resume throws → S8(error).
      assertCompletionSignal(
        result,
        spec.completionSignal,
        `${spec.id}-${spec.role}-resume`,
      );
      // Resume path: trust the self-report (undefined realCommitCount). A resume
      // re-runs ONE iteration that may re-emit corrected output with no new
      // commit, so its per-run commits.length is not a cumulative truth (#256
      // git-truthing applies to the normal runStep completion path only).
      const output = this.decodeOutput(
        spec,
        this.rawOutputFor(result, /*typedOutputUsed*/ true),
        /*realCommitCount (skip git-truth on resume)*/ undefined,
      );
      return { output, sessionId: lastSessionId(result) ?? sessionId };
    } catch (err) {
      // Dead-session fallback (#256): a missing/dead session → fresh run() (keep
      // the committed worktree progress, lose in-session memory). A
      // StructuredOutputError carrying a sessionId → retry that session with the
      // same prompt (Sandcastle's structured-retry pattern).
      const recovery = classifyResumeError(err);
      if (recovery.kind === "retry-structured") {
        const result = await sc.run({
          name: `${spec.id}-${spec.role}-resume-retry`,
          cwd: worktree.path,
          sandbox: this.box(issueNumber, spec),
          agent: sc.claudeCode(modelIdForSlug(spec.model)),
          maxIterations: 1,
          completionSignal: spec.completionSignal,
          branchStrategy: { type: "head" },
          resumeSession: recovery.sessionId,
          promptFile: join(this.opts.promptsDir, spec.promptFile),
          // maxIterations:1 ⇒ typed output valid for both roles (F4, as above).
          output: this.outputFor(spec),
        });
        // #244 step-advance gate (resume-retry path): same gate as the fresh and
        // native-resume runs — no signal, no advance (throws → S8(error)).
        assertCompletionSignal(
          result,
          spec.completionSignal,
          `${spec.id}-${spec.role}-resume-retry`,
        );
        // Resume-retry path: trust the self-report (undefined), same rationale as
        // the resume path above — a per-run commit count is not a cumulative
        // truth here (#256 git-truthing is the normal runStep path).
        const output = this.decodeOutput(
          spec,
          this.rawOutputFor(result, /*typedOutputUsed*/ true),
          /*realCommitCount (skip git-truth on resume)*/ undefined,
        );
        return { output, sessionId: lastSessionId(result) ?? recovery.sessionId };
      }
      // fresh-run fallback. Re-thread the fix_now findings (r3 fix_loop_context)
      // so the fresh S5 coder still receives them (runStep rewrites the file).
      return await this.runStep(spec, worktree, fixNowFindings);
    }
  }

  // ── S7: push (git) ─────────────────────────────────────────────────────────
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
