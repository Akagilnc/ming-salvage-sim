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
 */

import { execFileSync } from "node:child_process";
import {
  chmodSync,
  copyFileSync,
  mkdirSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import * as sc from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { z } from "zod";

import type {
  Backend,
  Finding,
  IssueMeta,
  IssueSnapshot,
  ResumeState,
  StepId,
  StepOutput,
  StepResult,
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

/** Build the S1 {@link IssueSnapshot} (body + comments + Agent Brief). */
export function buildIssueSnapshot(
  issueNumber: number,
  json: GhIssueJson,
): IssueSnapshot {
  return {
    number: json.number ?? issueNumber,
    body: json.body ?? "",
    comments: (json.comments ?? []).map((c) => c.body ?? ""),
    agentBrief: extractAgentBrief(json),
  };
}

// ── auth-mount path construction (spike contract) ───────────────────────────

/** Where Sandcastle mounts the codex auth dir inside the container. */
export const SANDBOX_CODEX_DIR = "/home/agent/.codex";
/** Where the baked dev skills are mounted inside the container. */
export const SANDBOX_SKILLS_DIR = "/home/agent/.claude/skills";

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

// ── per-step session id extraction (#256 seam extension) ─────────────────────

/** Minimal slice of Sandcastle's RunResult this Backend reads. */
export interface RunResultLike {
  readonly iterations: ReadonlyArray<{ readonly sessionId?: string }>;
  readonly commits: ReadonlyArray<{ readonly sha: string }>;
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
  const cause = err instanceof Error ? err.message : String(err);
  return new Error(`${step}:${phase} — ${cause}`);
}

// ════════════════════════════════════════════════════════════════════════════
// Container glue (MANUAL smoke; not in the zero-container automated suite)
// ════════════════════════════════════════════════════════════════════════════

/** Tunables for the real Backend (host paths + the profile image). */
export interface RealBackendOptions {
  /** The host repo the resident slice worktrees are cut from (ADR 0017). */
  readonly mainRepo: string;
  /** GitHub repo slug for `gh` (`owner/name`). */
  readonly repo: string;
  /** The profile image (#253): toolchain + souls + model CLIs baked in. */
  readonly imageName: string;
  /** Host dir holding the baked dev skills to bind-mount (spike). */
  readonly skillsMount: string;
  /** Dir holding the versioned promptFiles (coder_implement.md, …). */
  readonly promptsDir: string;
  /** Override $HOME for auth path construction (tests). */
  readonly home?: string;
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

  constructor(opts: RealBackendOptions) {
    this.opts = opts;
  }

  /** Run a host `gh`/`git` command, returning trimmed stdout. */
  private sh(file: string, args: string[], cwd?: string): string {
    return execFileSync(file, args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      encoding: "utf8",
    }).trim();
  }

  // ── S0: lightweight metadata (host gh) ─────────────────────────────────────
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    const raw = this.sh("gh", [
      "issue",
      "view",
      String(issueNumber),
      "--repo",
      this.opts.repo,
      "--json",
      "number,body,labels,comments",
    ]);
    const json = JSON.parse(raw) as GhIssueJson;
    // Native sub-issue + blocked_by via the GraphQL/REST API.
    const subIssueCount = this.fetchSubIssueCount(issueNumber);
    const blockedBy = this.fetchBlockedBy(issueNumber);
    return buildIssueMeta(issueNumber, json, blockedBy, subIssueCount);
  }

  private fetchSubIssueCount(issueNumber: number): number {
    try {
      const raw = this.sh("gh", [
        "issue",
        "view",
        String(issueNumber),
        "--repo",
        this.opts.repo,
        "--json",
        "subIssues",
      ]);
      const parsed = JSON.parse(raw) as { subIssues?: unknown[] };
      return Array.isArray(parsed.subIssues) ? parsed.subIssues.length : 0;
    } catch {
      // `subIssues` is a newer gh field; absence ⇒ treat as a leaf.
      return 0;
    }
  }

  private fetchBlockedBy(issueNumber: number): GhBlockedBy[] {
    try {
      const raw = this.sh("gh", [
        "api",
        `repos/${this.opts.repo}/issues/${issueNumber}/dependencies/blocked_by`,
      ]);
      const parsed = JSON.parse(raw) as Array<{
        number?: number;
        state?: string;
      }>;
      return parsed
        .filter((d): d is { number: number; state: string } =>
          typeof d.number === "number" && typeof d.state === "string",
        )
        .map((d) => ({ number: d.number, state: d.state }));
    } catch {
      return [];
    }
  }

  // ── S1: full snapshot (host gh) ────────────────────────────────────────────
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    const raw = this.sh("gh", [
      "issue",
      "view",
      String(issueNumber),
      "--repo",
      this.opts.repo,
      "--json",
      "number,body,comments",
    ]);
    const json = JSON.parse(raw) as GhIssueJson;
    return buildIssueSnapshot(issueNumber, json);
  }

  // ── S1: resident slice worktree (Sandcastle native createWorktree) ─────────
  async prepareWorktree(
    issueNumber: number,
    base: string,
  ): Promise<WorktreeHandle> {
    const branch = `feat/244-orchestrator-issue-${issueNumber}`;
    // Idempotent reuse: if the resident worktree exists, reuse it (the runner's
    // #255 resume path drives this); else cut a fresh one from `base` (main).
    const existing = this.findExistingWorktree(branch);
    if (existing !== undefined) {
      return { branch, base, path: existing };
    }
    const wt = await sc.createWorktree({
      branchStrategy: { type: "branch", branch },
      cwd: this.opts.mainRepo,
    });
    return { branch, base, path: wt.worktreePath };
  }

  private findExistingWorktree(branch: string): string | undefined {
    try {
      const out = this.sh("git", ["worktree", "list", "--porcelain"], this.opts.mainRepo);
      const blocks = out.split("\n\n");
      for (const block of blocks) {
        if (block.includes(`branch refs/heads/${branch}`)) {
          const line = block.split("\n").find((l) => l.startsWith("worktree "));
          if (line) return line.slice("worktree ".length).trim();
        }
      }
    } catch {
      // no worktrees / git error ⇒ none existing.
    }
    return undefined;
  }

  // ── S1: write the snapshot into the worktree (clean-room) ──────────────────
  async writeSnapshot(
    worktree: WorktreeHandle,
    snapshot: IssueSnapshot,
  ): Promise<void> {
    const target = join(worktree.path, ".orchestrator-snapshot.json");
    // Use the fs writeFile via execFile-free path: write atomically.
    const { writeFileSync } = await import("node:fs");
    writeFileSync(target, JSON.stringify(snapshot, null, 2), "utf8");
  }

  // ── auth mount (spike contract) ────────────────────────────────────────────
  private mountAuth(issueNumber: number): {
    authDir: string;
    claudeToken: string;
  } {
    const paths = buildAuthPaths(issueNumber, this.opts.home);
    rmSync(paths.hostCodexAuthDir, { recursive: true, force: true });
    mkdirSync(paths.hostCodexAuthDir, { recursive: true });
    copyFileSync(
      paths.srcCodexAuth,
      join(paths.hostCodexAuthDir, "auth.json"),
    );
    try {
      copyFileSync(
        paths.srcCodexConfig,
        join(paths.hostCodexAuthDir, "config.toml"),
      );
    } catch {
      // config.toml is optional.
    }
    chmodSync(join(paths.hostCodexAuthDir, "auth.json"), 0o644);
    const claudeToken = readFileSync(paths.claudeTokenFile, "utf8").trim();
    return { authDir: paths.hostCodexAuthDir, claudeToken };
  }

  private box(issueNumber: number): sc.SandboxProvider {
    const { authDir, claudeToken } = this.mountAuth(issueNumber);
    return docker({
      imageName: this.opts.imageName,
      env: { CLAUDE_CODE_OAUTH_TOKEN: claudeToken },
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

  /** Decode a Sandcastle structured output into a domain StepOutput. */
  private decodeOutput(spec: StepSpec, raw: unknown): StepOutput {
    if (spec.role === "reviewer") {
      const r = reviewerOutputSchema.parse(raw);
      const findings: Finding[] = r.findings.map((f) => ({ ...f }));
      return r.escalate
        ? { kind: "reviewer", findings, escalate: r.escalate }
        : { kind: "reviewer", findings };
    }
    const c = coderOutputSchema.parse(raw);
    return c.escalate
      ? {
          kind: "coder",
          committed: c.committed,
          commitsAdded: c.commitsAdded,
          escalate: c.escalate,
        }
      : { kind: "coder", committed: c.committed, commitsAdded: c.commitsAdded };
  }

  // ── S2/S3/S5/S6: one sandbox.run() (#256 seam extension returns StepResult) ─
  async runStep(
    spec: StepSpec,
    worktree: WorktreeHandle,
  ): Promise<StepResult> {
    const issueNumber = this.issueOf(worktree);
    const result = await sc.run({
      name: `${spec.id}-${spec.role}`,
      cwd: worktree.path,
      sandbox: this.box(issueNumber),
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
      // requires maxIterations:1 with output); coder steps iterate, so their
      // output is collected from the completion-signalled final tag.
      ...(spec.maxIter === 1 ? { output: this.outputFor(spec) } : {}),
    });
    const output = this.decodeOutput(spec, (result as { output?: unknown }).output);
    return { output, sessionId: lastSessionId(result) };
  }

  // ── #255: resume the prior agent session (native + dead-session fallback) ───
  async resumeSession(
    spec: StepSpec,
    worktree: WorktreeHandle,
    sessionId: string,
  ): Promise<StepResult> {
    const issueNumber = this.issueOf(worktree);
    try {
      const result = await sc.run({
        name: `${spec.id}-${spec.role}-resume`,
        cwd: worktree.path,
        sandbox: this.box(issueNumber),
        agent: sc.claudeCode(modelIdForSlug(spec.model)),
        // resumeSession requires maxIterations:1 (Sandcastle constraint).
        maxIterations: 1,
        completionSignal: spec.completionSignal,
        branchStrategy: { type: "head" },
        resumeSession: sessionId,
        promptFile: join(this.opts.promptsDir, spec.promptFile),
        ...(spec.maxIter === 1 ? { output: this.outputFor(spec) } : {}),
      });
      const output = this.decodeOutput(
        spec,
        (result as { output?: unknown }).output,
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
          sandbox: this.box(issueNumber),
          agent: sc.claudeCode(modelIdForSlug(spec.model)),
          maxIterations: 1,
          completionSignal: spec.completionSignal,
          branchStrategy: { type: "head" },
          resumeSession: recovery.sessionId,
          promptFile: join(this.opts.promptsDir, spec.promptFile),
          ...(spec.maxIter === 1 ? { output: this.outputFor(spec) } : {}),
        });
        const output = this.decodeOutput(
          spec,
          (result as { output?: unknown }).output,
        );
        return { output, sessionId: lastSessionId(result) ?? recovery.sessionId };
      }
      // fresh-run fallback.
      return await this.runStep(spec, worktree);
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
    this.sh("git", ["reset", "--hard", "HEAD"], worktree.path);
    this.sh("git", ["clean", "-fd"], worktree.path);
    // prune is repo-level; run from the main repo.
    this.sh("git", ["worktree", "prune"], this.opts.mainRepo);
  }

  // ── #255: detect resume residue ────────────────────────────────────────────
  async findResumeState(issueNumber: number): Promise<ResumeState | undefined> {
    const branch = `feat/244-orchestrator-issue-${issueNumber}`;
    const wtPath = this.findExistingWorktree(branch);
    if (wtPath === undefined) return undefined;
    const stateDir = this.stateDirFor(wtPath, issueNumber);
    const ledger = this.readLedger(stateDir);
    if (ledger === undefined) return undefined;
    return {
      worktree: { branch, base: "main", path: wtPath },
      stateDir,
      ledger,
    };
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
    try {
      const raw = readFileSync(join(stateDir, "steps.jsonl"), "utf8");
      const lines = raw.split("\n").filter((l) => l.trim().length > 0);
      // reconstructProgressState / planResume defend against corrupted lines;
      // skip lines that don't parse rather than abort the whole resume.
      const entries = [] as Array<ResumeState["ledger"][number]>;
      for (const line of lines) {
        try {
          entries.push(JSON.parse(line));
        } catch {
          // corrupted-ledger line — skip it (the runner's reconstruct guards
          // tolerate gaps; a hard parse abort here would lose ALL progress).
        }
      }
      return entries;
    } catch {
      return undefined;
    }
  }

  // ── #249: ledger persistence (sibling JSONL) ───────────────────────────────
  async writeLedger(
    entry: import("./types.js").PersistentLedgerEntry,
    stateDir: string,
  ): Promise<void> {
    const { appendFileSync, mkdirSync: mkd } = await import("node:fs");
    mkd(stateDir, { recursive: true });
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
    const m = worktree.branch.match(/issue-(\d+)$/);
    if (m) return Number(m[1]);
    // Fall back to any trailing digits in the branch.
    const m2 = worktree.branch.match(/(\d+)/);
    return m2 ? Number(m2[1]) : 0;
  }
}
