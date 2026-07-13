/**
 * Unit tests for the PURE host-side logic of the real Backend (#256).
 *
 * Scope (per #256 acceptance criteria): only the zero-container, zero-LLM logic
 * — gh-snapshot parsing, auth-mount path construction, model-slug mapping,
 * per-step sessionId extraction (seam extension), resume error classification,
 * and failedStep attribution
 * (codex#3). The real container / real-LLM / real-gh paths are #256
 * MANUAL smoke and are NOT exercised here.
 *
 * These imports load `@ai-hero/sandcastle` (side-effect-free) but never start a
 * container, so the suite runs in the same zero-infra harness as the fake-Backend
 * step control-flow tests.
 */

import { dirname, join } from "node:path";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { afterAll, afterEach, describe, expect, it, vi } from "vitest";
import * as telemetry from "../src/telemetry.js";
import {
  agentForSlug,
  attributeFailure,
  branchForIssue,
  candidateBranches,
  buildAuthPaths,
  buildIssueMeta,
  buildIssueSnapshot,
  checkExecutableInstructionSource,
  classifyResumeError,
  cutRefFor,
  ensureExcluded,
  extractAgentBrief,
  extractCoderTag,
  extractVerifyTag,
  extractFixerTag,
  extractCleanupTag,
  extractDocReleaseTag,
  isLikelySha,
  isReadyForAgent,
  issueNumberFromBranch,
  lastSessionId,
  matchWorktreeForBranch,
  modelIdForSlug,
  modelFamilyForSlug,
  modelIsStrongLeg,
  opencodeAuthMount,
  applyUniformCredentialProvisioning,
  parseBlockedBy,
  parseCoderSelfReport,
  parseSubIssueCount,
  promptsDirError,
  soulsDirError,
  REQUIRED_SOUL_FILES,
  resolveModelSlug,
  soulForStep,
  REFERENCED_PROMPT_FILES,
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_GROK_DIR,
  SANDBOX_OPENCODE_AUTH_FILE,
  SANDBOX_SKILLS_DIR,
  SNAPSHOT_FILENAME,
  SUPPORTED_MODEL_PROVIDER_FACTORIES,
  WORKER_IDLE_TIMEOUT_SECONDS,
  type GhBlockedBy,
  type GhIssueJson,
} from "../src/realBackend.js";
import type {
  RepairEvidence,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../src/types.js";
import type * as sc from "@ai-hero/sandcastle";
import { resolveRouteModels } from "../src/modelRoutes.js";
// NOTE: `hasAgentBrief` was removed in #329 (vestigial after #328 de-gated the
// brief); S1's `extractAgentBrief` is the surviving brief reader.
import { StructuredOutputError } from "@ai-hero/sandcastle";

type AgentRunResult = Awaited<ReturnType<typeof sc.run>>;

function agentRunResult({
  completionSignal,
  stdout,
  commits = [],
  sessionId,
}: {
  readonly completionSignal?: string;
  readonly stdout: string;
  readonly commits?: ReadonlyArray<{ sha: string }>;
  readonly sessionId: string;
}): AgentRunResult {
  return {
    branch: "test-agent-branch",
    completionSignal,
    stdout,
    commits: [...commits],
    iterations: [{ sessionId }],
  };
}

/** #748: per-test $HOME so RealBackend never reads/writes real ~/.sc-orchestrator. */
const tempHomes: string[] = [];

function tempHome(prefix = "rb-home-748-"): string {
  const home = mkdtempSync(join(tmpdir(), prefix));
  tempHomes.push(home);
  return home;
}

function cleanupTempHomes(): void {
  while (tempHomes.length > 0) {
    const home = tempHomes.pop();
    if (home !== undefined) rmSync(home, { recursive: true, force: true });
  }
}

afterEach(cleanupTempHomes);
afterEach(() => vi.restoreAllMocks());
afterAll(cleanupTempHomes);

describe("#685 route smoke hardening", () => {
  it("turns a missing host CLI into an unknown version instead of throwing", () => {
    const backend = {
      sh: () => {
        throw new Error("host CLI missing");
      },
    };
    const cliVersionForSlug = (
      RealBackend.prototype as unknown as {
        cliVersionForSlug(this: typeof backend, slug: string): string;
      }
    ).cliVersionForSlug;

    expect(cliVersionForSlug.call(backend, "sonnet")).toBe("unknown");
  });

  it("looks up the CLI for the relay pool's final provider", () => {
    const calls: string[] = [];
    const backend = {
      sh: (file: string) => {
        calls.push(file);
        return "test-version";
      },
    };
    const cliVersionForSlug = (
      RealBackend.prototype as unknown as {
        cliVersionForSlug(this: typeof backend, slug: string, billingPool?: string): string;
      }
    ).cliVersionForSlug;

    expect(cliVersionForSlug.call(backend, "grok-4.5", "grok-build")).toBe("test-version");
    expect(calls).toEqual(["grok"]);
  });
});

// ─── gh JSON → IssueMeta / IssueSnapshot ─────────────────────────────────────

describe("realBackend gh parsing", () => {
  const briefComment = {
    author: { login: "Akagilnc" },
    body: "## Agent Brief\nimplement the real Backend per #256",
  };

  it("isReadyForAgent reads the ready-for-agent label", () => {
    expect(
      isReadyForAgent({ labels: [{ name: "ready-for-agent" }] }),
    ).toBe(true);
    expect(isReadyForAgent({ labels: [{ name: "bug" }] })).toBe(false);
    expect(isReadyForAgent({})).toBe(false);
  });

  it("buildIssueMeta derives the S0 gate fields (rfa ∧ no sub-issues ∧ blocked_by)", () => {
    const json: GhIssueJson = {
      number: 256,
      labels: [{ name: "ready-for-agent" }, { name: "enhancement" }],
    };
    const blockedBy: GhBlockedBy[] = [
      { number: 248, state: "closed" },
      { number: 254, state: "open" },
      { number: 252, state: "closed" },
    ];
    const meta = buildIssueMeta(256, json, blockedBy, /*subIssueCount*/ 0);
    expect(meta).toEqual({
      number: 256,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [254], // only the open one
    });
  });

  it("buildIssueMeta flags a parent issue (sub-issue count > 0)", () => {
    const meta = buildIssueMeta(244, { labels: [] }, [], /*subIssueCount*/ 10);
    expect(meta.hasSubIssues).toBe(true);
  });

  it("buildIssueMeta derives isClosed from gh state (#2: case-insensitive CLOSED)", () => {
    // gh issue view --json state returns "OPEN"/"CLOSED" (upper). A closed issue
    // must be admitted-rejected at S0 so a coder is never spun up on a done slice.
    expect(buildIssueMeta(327, { labels: [], state: "CLOSED" }, [], 0).isClosed).toBe(true);
    expect(buildIssueMeta(327, { labels: [], state: "closed" }, [], 0).isClosed).toBe(true);
    expect(buildIssueMeta(327, { labels: [], state: "OPEN" }, [], 0).isClosed).toBe(false);
    expect(buildIssueMeta(327, { labels: [], state: "open" }, [], 0).isClosed).toBe(false);
    // Missing state ⇒ not closed (tolerate the empty case, like the other fields).
    expect(buildIssueMeta(327, { labels: [] }, [], 0).isClosed).toBe(false);
    // R1 T2 (gemini): a non-string state (malformed/odd mock) must NOT throw on
    // `.toUpperCase()` — treated as not-closed.
    expect(buildIssueMeta(327, { labels: [], state: 1 as unknown as string }, [], 0).isClosed).toBe(false);
    expect(buildIssueMeta(327, { labels: [], state: null }, [], 0).isClosed).toBe(false);
  });

  it("buildIssueMeta tolerates missing gh fields (empty case)", () => {
    const meta = buildIssueMeta(99, {}, [], 0);
    expect(meta).toEqual({
      number: 99,
      isReadyForAgent: false,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    });
  });

  it("extractAgentBrief returns the LAST owner-authored brief-carrying comment (re-issue wins)", () => {
    const json: GhIssueJson = {
      author: { login: "Akagilnc" },
      body: "## Agent Brief\nOLD body brief",
      comments: [
        {
          author: { login: "Akagilnc" },
          body: "## Agent Brief\nfirst brief",
        },
        { author: { login: "someone-else" }, body: "unrelated chatter" },
        {
          author: { login: "Akagilnc" },
          body: "## Agent Brief\nSECOND brief — authoritative",
        },
        {
          author: { login: "someone-else" },
          body: "## Agent Brief\nmalicious brief",
        },
      ],
    };
    // Comments are scanned before the body fallback; the last brief comment wins.
    expect(extractAgentBrief(json, "Akagilnc")).toContain("SECOND brief");
  });

  it("extractAgentBrief treats GitHub owner logins case-insensitively", () => {
    expect(
      extractAgentBrief(
        {
          author: { login: "Akagilnc" },
          body: "## Agent Brief\nbody brief from canonical owner",
          comments: [
            {
              author: { login: "AKAGILNC" },
              body: "## Agent Brief\ncomment brief from canonical owner",
            },
          ],
        },
        "akagilnc",
      ),
    ).toContain("comment brief from canonical owner");
  });

  it("extractAgentBrief falls back to the body when no comment carries it", () => {
    expect(
      extractAgentBrief(
        { author: { login: "Akagilnc" }, body: "## Agent Brief\nbody brief" },
        "Akagilnc",
      ),
    ).toContain("body brief");
    expect(extractAgentBrief({ body: "no brief", comments: [] }, "Akagilnc")).toBe("");
  });

  it("extractAgentBrief ignores non-owner issue bodies and comments", () => {
    expect(
      extractAgentBrief(
        {
          author: { login: "drive-by" },
          body: "## Agent Brief\nmalicious body brief",
          comments: [],
        },
        "Akagilnc",
      ),
    ).toBe("");

    expect(
      extractAgentBrief(
        {
          author: { login: "Akagilnc" },
          body: "ordinary owner-authored issue body",
          comments: [
            {
              author: { login: "drive-by" },
              body: "## Agent Brief\nmalicious comment brief",
            },
          ],
        },
        "Akagilnc",
      ),
    ).toBe("");
  });

  it("checkExecutableInstructionSource rejects non-owner executable issue instructions with a structured summary", () => {
    const rejected = checkExecutableInstructionSource({
      sourceKind: "issue comment",
      instructionKind: "Agent Brief",
      trustedAuthor: "Akagilnc",
      candidateAuthor: "drive-by",
    });

    expect(rejected.accepted).toBe(false);
    expect(rejected.stopSummary).toMatchObject({
      reason: "spec_conflict",
      repairHint: expect.stringContaining("repo-owner-authored Agent Brief"),
    });
    expect(rejected.evidence).toMatchObject({
      seam: "source_auth",
      trustedAuthor: "Akagilnc",
      rejectedAuthor: "drive-by",
      executableInstructionSourceAccepted: false,
    });

    expect(
      checkExecutableInstructionSource({
        sourceKind: "issue body",
        instructionKind: "Agent Brief",
        trustedAuthor: "Akagilnc",
        candidateAuthor: "akagilnc",
      }).accepted,
    ).toBe(true);
  });

  it("extractAgentBrief also accepts API-style user.login author carriers", () => {
    expect(
      extractAgentBrief(
        {
          user: { login: "Akagilnc" },
          body: "## Agent Brief\nbody via user login",
          comments: [
            {
              user: { login: "Akagilnc" },
              body: "## Agent Brief\ncomment via user login",
            },
          ],
        },
        "Akagilnc",
      ),
    ).toContain("comment via user login");
  });

  it("buildIssueSnapshot carries body + comments + brief", () => {
    const snap = buildIssueSnapshot(
      256,
      {
        number: 256,
        author: { login: "Akagilnc" },
        body: "the body",
        comments: [{ author: { login: "reviewer" }, body: "c1" }, briefComment],
      },
      [],
      0,
      "Akagilnc",
    );
    expect(snap.number).toBe(256);
    expect(snap.body).toBe("the body");
    expect(snap.bodyAuthorLogin).toBe("Akagilnc");
    expect(snap.comments).toEqual(["c1", briefComment.body]);
    expect(snap.commentAuthorLogins).toEqual(["reviewer", "Akagilnc"]);
    expect(snap.agentBrief).toContain("## Agent Brief");
  });

  it("buildIssueSnapshot embeds the #244-named native metadata (title/state/labels + sub-issue + blocked_by summaries)", () => {
    // #244 S1: the full snapshot is "body + comments + 最新 Agent Brief 正文 +
    // native metadata". The native metadata S0 reads via gh must travel into the
    // clean-room snapshot so the host-side audit/resume artifact is contract-
    // complete. Worker execution truth is live issue fetch via in-container gh.
    const json: GhIssueJson = {
      number: 256,
      title: "Slice: real Backend",
      state: "open",
      author: { login: "Akagilnc" },
      body: "the body",
      labels: [{ name: "ready-for-agent" }, { name: "enhancement" }],
      comments: [briefComment],
    };
    const blockedBy: GhBlockedBy[] = [
      { number: 248, state: "closed" },
      { number: 254, state: "open" },
    ];
    const snap = buildIssueSnapshot(256, json, blockedBy, /*subIssueCount*/ 3, "Akagilnc");
    expect(snap.nativeMeta).toEqual({
      title: "Slice: real Backend",
      state: "open",
      labels: ["ready-for-agent", "enhancement"],
      subIssueCount: 3,
      blockedBy: [
        { number: 248, state: "closed" },
        { number: 254, state: "open" },
      ],
    });
  });

  it("buildIssueSnapshot tolerates missing title/state/labels (empty native metadata)", () => {
    const snap = buildIssueSnapshot(99, {}, [], 0, "Akagilnc");
    expect(snap.nativeMeta).toEqual({
      title: "",
      state: "",
      labels: [],
      subIssueCount: 0,
      blockedBy: [],
    });
  });
});

// ─── clean-room snapshot leak guard (integ-cmr 256 r2, F3) ───────────────────

describe("realBackend ensureExcluded (snapshot leak guard, F3)", () => {
  it("appends the pattern on its own newline-terminated line when absent", () => {
    expect(ensureExcluded("node_modules/\n", SNAPSHOT_FILENAME)).toBe(
      `node_modules/\n${SNAPSHOT_FILENAME}\n`,
    );
  });

  it("is idempotent — an already-present exact line is left unchanged", () => {
    const existing = `node_modules/\n${SNAPSHOT_FILENAME}\n`;
    expect(ensureExcluded(existing, SNAPSHOT_FILENAME)).toBe(existing);
  });

  it("handles an empty exclude file (fresh worktree)", () => {
    expect(ensureExcluded("", SNAPSHOT_FILENAME)).toBe(`${SNAPSHOT_FILENAME}\n`);
  });

  it("normalises a missing trailing newline before appending", () => {
    // A prior exclude line with no trailing newline must not merge with ours.
    expect(ensureExcluded("foo", SNAPSHOT_FILENAME)).toBe(
      `foo\n${SNAPSHOT_FILENAME}\n`,
    );
  });

  it("matches a present line even with surrounding whitespace (trim)", () => {
    const existing = `  ${SNAPSHOT_FILENAME}  \n`;
    expect(ensureExcluded(existing, SNAPSHOT_FILENAME)).toBe(existing);
  });

  it("the snapshot filename is the dot-prefixed clean-room artifact", () => {
    expect(SNAPSHOT_FILENAME).toBe(".orchestrator-snapshot.json");
  });
});

// ─── fresh-cut base ref (integ-cmr 256 r3, worktree_base_stale) ──────────────

describe("realBackend cutRefFor (worktree_base_stale, r3)", () => {
  it("cuts from origin/<base> when the fetch refreshed the remote ref", () => {
    // After a successful `git fetch origin main`, refs/remotes/origin/main is
    // the up-to-date base — derive the slice from THAT (matches the spike's
    // `git worktree add … origin/main`), NOT the possibly-stale local main.
    expect(cutRefFor("main", /*fetchedOk*/ true)).toBe("origin/main");
  });

  it("falls back to the local <base> when the fetch failed (offline / local-only)", () => {
    // A fetch failure (offline, or a local-only base with no remote) must not
    // block the cut — fall back to the local ref rather than a missing origin/.
    expect(cutRefFor("main", /*fetchedOk*/ false)).toBe("main");
  });

  it("preserves a non-default base name in both branches", () => {
    expect(cutRefFor("release-1.x", true)).toBe("origin/release-1.x");
    expect(cutRefFor("release-1.x", false)).toBe("release-1.x");
  });

  // #291: a family base is a LOCAL branch on the dedicated clone (ADR 0022
  // decision 7) — children cut from it, NOT origin/<family-base>. cutRefFor's
  // `localOnly` flag forces the LOCAL ref regardless of `fetchedOk`, so a stale
  // `origin/<family-base>` (e.g. a prior PR's remote branch) can never shadow the
  // local family base the merger accumulated this run's waves onto (agy R1).
  describe("localOnly (family base, #291)", () => {
    it("forces the LOCAL ref even when a fetch 'succeeded' (never origin/<family-base>)", () => {
      expect(cutRefFor("family/293-base", /*fetchedOk*/ true, /*localOnly*/ true)).toBe(
        "family/293-base",
      );
    });
    it("is the LOCAL ref when no fetch ran either", () => {
      expect(cutRefFor("family/293-base", /*fetchedOk*/ false, /*localOnly*/ true)).toBe(
        "family/293-base",
      );
    });
    it("standalone (localOnly omitted/false) keeps the origin/ behaviour — zero regression", () => {
      expect(cutRefFor("main", true)).toBe("origin/main");
      expect(cutRefFor("main", true, false)).toBe("origin/main");
    });
  });
});

// ─── worktree reuse: exact branch-line match (gemini R1, high) ───────────────

describe("realBackend matchWorktreeForBranch (prefix-collision safety)", () => {
  // `git worktree list --porcelain` emits blank-line-separated blocks, each a
  // set of `key value` lines; the branch line is exactly `branch refs/heads/<ref>`.
  const porcelain = [
    "worktree /repo/.worktrees/issue-12",
    "HEAD aaaa",
    "branch refs/heads/feat/244-orchestrator-issue-12",
    "",
    "worktree /repo/.worktrees/issue-123",
    "HEAD bbbb",
    "branch refs/heads/feat/244-orchestrator-issue-123",
  ].join("\n");

  it("returns the exact worktree for the queried branch", () => {
    expect(
      matchWorktreeForBranch(porcelain, "feat/244-orchestrator-issue-12"),
    ).toBe("/repo/.worktrees/issue-12");
    expect(
      matchWorktreeForBranch(porcelain, "feat/244-orchestrator-issue-123"),
    ).toBe("/repo/.worktrees/issue-123");
  });

  it("does NOT substring-match a longer same-prefix branch", () => {
    // The bug: `block.includes('branch refs/heads/' + branch)` matches the
    // issue-123 block when querying issue-12. Exact line match must not.
    const single = [
      "worktree /repo/.worktrees/issue-123",
      "HEAD bbbb",
      "branch refs/heads/feat/244-orchestrator-issue-123",
    ].join("\n");
    expect(
      matchWorktreeForBranch(single, "feat/244-orchestrator-issue-12"),
    ).toBeUndefined();
  });

  it("returns undefined when no block carries the branch", () => {
    expect(matchWorktreeForBranch(porcelain, "feat/other")).toBeUndefined();
    expect(matchWorktreeForBranch("", "feat/x")).toBeUndefined();
  });

  it("ignores a detached / branchless worktree block", () => {
    const detached = ["worktree /repo/.worktrees/detached", "HEAD cccc", "detached"].join(
      "\n",
    );
    expect(matchWorktreeForBranch(detached, "feat/x")).toBeUndefined();
  });
});

// ─── issue number from branch name (gemini R2, high) ─────────────────────────

describe("realBackend issueNumberFromBranch (suffix-safe extraction)", () => {
  it("extracts the issue number from a plain issue-suffixed branch", () => {
    expect(issueNumberFromBranch("feat/244-orchestrator-issue-256")).toBe(256);
    expect(issueNumberFromBranch("issue-12")).toBe(12);
  });

  it("extracts the issue number even when the branch has a trailing suffix", () => {
    // The bug: `/issue-(\d+)$/` fails here, then the fallback `/(\d+)/` grabs the
    // FIRST digit run (244, the epic) instead of the real issue number (256).
    expect(issueNumberFromBranch("feat/244-orchestrator-issue-256-fix")).toBe(
      256,
    );
    expect(issueNumberFromBranch("feat/244-issue-71-followup-v2")).toBe(71);
  });

  it("falls back to the LAST digit run when there is no issue- token", () => {
    expect(issueNumberFromBranch("feat/epic-244-slice-99")).toBe(99);
  });

  it("returns 0 when the branch carries no digits", () => {
    expect(issueNumberFromBranch("feat/no-number-here")).toBe(0);
  });
});

// ─── branchForIssue (#1: no hardcoded 244-orchestrator epic number) ──────────

describe("realBackend branchForIssue (neutral, no fake epic number)", () => {
  it("derives a branch name that does NOT bake in a wrong/fixed epic number", () => {
    const b = branchForIssue(256);
    // The bug was `feat/244-orchestrator-issue-256` — a hardcoded 244 that is the
    // wrong epic for every issue except 244. The name must carry ONLY the real
    // issue number, no spurious leading digit run.
    expect(b).not.toMatch(/244/);
    expect(b).toContain("issue-256");
  });

  it("round-trips through issueNumberFromBranch (the inverse must still parse it)", () => {
    for (const n of [12, 71, 256, 327]) {
      expect(issueNumberFromBranch(branchForIssue(n))).toBe(n);
    }
  });
});

// ─── candidateBranches (#593: old-name fallback for resume/worktree lookup) ──

describe("realBackend candidateBranches (ordered candidate branch names)", () => {
  it("returns the current convention first", () => {
    const candidates = candidateBranches(256);
    expect(candidates[0]).toBe("feat/issue-256");
  });

  it("includes the old convention as fallback", () => {
    const candidates = candidateBranches(256);
    expect(candidates[1]).toBe("feat/244-orchestrator-issue-256");
  });

  it("returns exactly two candidates (no more conventions)", () => {
    expect(candidateBranches(99)).toHaveLength(2);
  });

  it("both candidates round-trip through issueNumberFromBranch", () => {
    for (const n of [12, 71, 256]) {
      for (const b of candidateBranches(n)) {
        expect(issueNumberFromBranch(b)).toBe(n);
      }
    }
  });
});

// ─── auth-mount path construction (spike contract) ───────────────────────────

describe("realBackend auth mount paths", () => {
  it("builds per-issue codex auth + claude token paths under $HOME", () => {
    const p = buildAuthPaths(256, "/home/dev");
    expect(p.hostCodexAuthDir).toBe("/home/dev/.sc-orchestrator/auth-256");
    expect(p.srcCodexAuth).toBe("/home/dev/.codex/auth.json");
    expect(p.srcCodexConfig).toBe("/home/dev/.codex/config.toml");
    expect(p.hostGrokAuthDir).toBe("/home/dev/.sc-orchestrator/grok-auth-256");
    expect(p.srcGrokAuth).toBe("/home/dev/.grok/auth.json");
    expect(p.claudeTokenFile).toBe("/home/dev/.sc-claude-token");
  });

  it("the sandbox mount targets match the spike contract", () => {
    // codex auth → /home/agent/.codex ; grok auth → /home/agent/.grok ;
    // dev skills → /home/agent/.claude/skills
    expect(SANDBOX_CODEX_DIR).toBe("/home/agent/.codex");
    expect(SANDBOX_GROK_DIR).toBe("/home/agent/.grok");
    expect(SANDBOX_SKILLS_DIR).toBe("/home/agent/.claude/skills");
  });

  it("per-issue dirs are distinct so concurrent issues never collide", () => {
    expect(buildAuthPaths(256, "/h").hostCodexAuthDir).not.toBe(
      buildAuthPaths(257, "/h").hostCodexAuthDir,
    );
    expect(buildAuthPaths(256, "/h").hostGrokAuthDir).not.toBe(
      buildAuthPaths(257, "/h").hostGrokAuthDir,
    );
  });

  it("defaults home to os.homedir() when omitted (production default unchanged)", () => {
    // Pure path construction only — no file I/O.
    const p = buildAuthPaths(748);
    expect(p.hostCodexAuthDir).toBe(
      join(homedir(), ".sc-orchestrator", "auth-748"),
    );
  });
});

// ─── #748: injectable home keeps auth I/O off real ~/.sc-orchestrator ────────

describe("#748 RealBackend home injection (auth mount stays off real $HOME)", () => {
  const here = dirname(fileURLToPath(import.meta.url));

  /** Expose mountAuth over the production seam with clone/git stubbed. */
  class MountProbeBackend extends RealBackend {
    protected override cloneDirExists(): boolean {
      return true;
    }
    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      return "";
    }
    public mount(issueNumber: number): { authDir: string; claudeToken?: string } {
      return this.mountAuth(issueNumber);
    }
  }

  it("mountAuth with opts.home writes only under the injected home, never real ~/.sc-orchestrator", () => {
    const injected = tempHome("rb-home-748-mount-");
    const issue = 748;

    const backend = new MountProbeBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 748,
      repo: "owner/name",
      imageName: "img",
      promptsDir: join(here, "..", "prompts"),
      soulsDir: join(here, "..", "image", "souls"),
      home: injected,
    });

    const { authDir } = backend.mount(issue);
    expect(authDir).toBe(join(injected, ".sc-orchestrator", `auth-${issue}`));
    expect(existsSync(join(authDir, "config.toml"))).toBe(true);
    // The only filesystem path asserted by this isolation test is the injected
    // sentinel home; it never probes the real user's auth root.
  });
});

// ─── model slug → CLI (role decides soul/model) ──────────────────────────────

describe("realBackend WORKER_IDLE_TIMEOUT_SECONDS (idle-timeout disable)", () => {
  it("is a far-future value that never fires in practice (sandcastle has no disable sentinel)", () => {
    // ONE WEEK in seconds. sandcastle multiplies idleTimeoutSeconds by 1e3, and the
    // millisecond delay must fit in a signed 32-bit int — a larger value (e.g. 1
    // year = 31_536_000_000 ms) OVERFLOWS int32 and fires the timer IMMEDIATELY
    // (gemini #384 R2). A week dwarfs any real run and stays well under the limit.
    expect(WORKER_IDLE_TIMEOUT_SECONDS).toBe(604_800);
    // far larger than sandcastle's 600s default → never beats a real worker.
    expect(WORKER_IDLE_TIMEOUT_SECONDS).toBeGreaterThan(600);
    // its millisecond form must not overflow a signed 32-bit timer.
    expect(WORKER_IDLE_TIMEOUT_SECONDS * 1000).toBeLessThanOrEqual(2 ** 31 - 1);
  });
});

describe("realBackend modelIdForSlug", () => {
  it("maps supported slugs to baked CLI model ids through the registry", () => {
    expect(modelIdForSlug("gpt-5.6-terra")).toBe("gpt-5.6-terra");
    expect(modelIdForSlug("gpt-5.6-sol")).toBe("gpt-5.6-sol");
    expect(modelIdForSlug("sonnet")).toBe("claude-sonnet-5");
    expect(modelIdForSlug("opus")).toBe("claude-opus-4-8");
  });

  it("throws on an unknown slug", () => {
    expect(() => modelIdForSlug("gpt")).toThrow(/unknown model slug/);
  });
});

// ─── resolveModelSlug (data-driven slug → backend registry) ──────────────────

describe("realBackend resolveModelSlug", () => {
  it("pins the OpenCode Grok routes to the live Grok 4.5 model", () => {
    expect(resolveModelSlug("opencode-grok")).toEqual({
      provider: "opencode",
      model: "grok-4.5",
    });
    expect(resolveModelSlug("agy")).toEqual({
      provider: "opencode",
      model: "grok-4.5",
    });
    expect(resolveModelSlug("glm-5.2")).toEqual({
      provider: "opencode",
      model: "opencode-go/glm-5.2",
    });
  });

  it("declares the provider factories the registry can target (incl. #807 grok)", () => {
    expect(SUPPORTED_MODEL_PROVIDER_FACTORIES).toEqual([
      "claudeCode",
      "codex",
      "opencode",
      "copilot",
      "cursor",
      "pi",
      "grok",
    ]);
  });

  it("resolves existing slugs to the same provider/model/options as the pre-registry mapping", () => {
    expect(resolveModelSlug("gpt-5.6-terra")).toEqual({
      provider: "codex",
      model: "gpt-5.6-terra",
      options: { effort: "low" },
    });
    expect(resolveModelSlug("gpt-5.6-sol")).toEqual({
      provider: "codex",
      model: "gpt-5.6-sol",
      options: { effort: "medium" },
    });
    expect(resolveModelSlug("sonnet")).toEqual({
      provider: "claudeCode",
      model: "claude-sonnet-5",
      options: { permissionMode: "bypassPermissions" },
    });
    expect(resolveModelSlug("haiku")).toEqual({
      provider: "claudeCode",
      model: "claude-haiku-4-5",
      options: { permissionMode: "bypassPermissions" },
    });
    expect(resolveModelSlug("opus")).toEqual({
      provider: "claudeCode",
      model: "claude-opus-4-8",
      options: { permissionMode: "bypassPermissions" },
    });
    expect(modelFamilyForSlug("gpt-5.6-terra")).toBe("codex");
    expect(modelFamilyForSlug("sonnet")).toBe("claude");
    expect(modelFamilyForSlug("opus")).toBe("claude");
    expect(modelIsStrongLeg("gpt-5.6-terra")).toBe(true);
    expect(modelIsStrongLeg("gpt-5.6-sol")).toBe(true);
    expect(modelIsStrongLeg("sonnet")).toBe(false);
    expect(modelIsStrongLeg("opus")).toBe(true);
  });

  it("fails closed for unknown model slugs", () => {
    expect(() => resolveModelSlug("gpt")).toThrow(/unknown model slug/);
  });
});

describe("#420 OpenCode runtime auth", () => {
  it("mounts only auth.json read-only, leaving SQLite state container-local", () => {
    expect(opencodeAuthMount("/home/dev")).toEqual({
      hostPath: "/home/dev/.local/share/opencode/auth.json",
      sandboxPath: SANDBOX_OPENCODE_AUTH_FILE,
      readonly: true,
    });
  });

  describe("uniform dispatch credential provisioning", () => {
  const authFile = join(tmpdir(), "dispatch-opencode-auth.json");

  afterEach(() => {
    rmSync(authFile, { force: true });
    vi.unstubAllEnvs();
  });

  it("injects every available credential without inspecting its contents", () => {
    vi.stubEnv("GLM_KEY", "glm-secret");
    writeFileSync(authFile, JSON.stringify({ "opencode-go": { type: "oauth" } }));
    const env: Record<string, string> = {};
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [];
    applyUniformCredentialProvisioning({ env, mounts, opencodeAuthFile: authFile });
    expect(env.GLM_KEY).toBe("glm-secret");
    expect(mounts).toContainEqual({
      hostPath: authFile, sandboxPath: SANDBOX_OPENCODE_AUTH_FILE, readonly: true,
    });
  });

  it("tolerates absent optional credentials and leaves provisioning empty", () => {
    vi.stubEnv("GLM_KEY", undefined);
    const env: Record<string, string> = {};
    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] = [];
    expect(() => applyUniformCredentialProvisioning({ env, mounts })).not.toThrow();
    expect(env).toEqual({});
    expect(mounts).toEqual([]);
  });
  });
});

// ─── agentForSlug (model slug → baked-in CLI provider) ────────────────────────

describe("realBackend agentForSlug", () => {
  it("resolves each ratified 5.6 officer through the Codex provider", () => {
    // The S2 build worker (coder) runs on Codex gpt-5.6-terra — agentForSlug returns the
    // sandcastle codex provider (`.name === "codex"`), NOT claudeCode.
    expect(agentForSlug("gpt-5.6-terra").name).toBe("codex");
    expect(agentForSlug("gpt-5.6-sol").name).toBe("codex");
  });
  it("resolves the claude slugs to the claudeCode provider (reviewer/ship)", () => {
    // opus (reviewer / per-slice review subagent) and sonnet (the ship worker) stay
    // on Claude — agentForSlug returns the claudeCode provider (`.name === "claude-code"`).
    expect(agentForSlug("opus").name).toBe("claude-code");
    expect(agentForSlug("sonnet").name).toBe("claude-code");
  });
  it("throws on an unknown slug (misconfigured StepSpec)", () => {
    expect(() => agentForSlug("gpt")).toThrow(/unknown model slug/);
  });
});

// ─── soulForStep (ship-pre 256 r1, role→soul selection / contract fidelity) ───

describe("realBackend soulForStep", () => {
  it("selects the coder soul for a coder step (#244 'role 决定注哪份 soul')", () => {
    expect(
      soulForStep({ role: "coder", soul: "coder" }),
    ).toBe("coder");
  });

  it("selects the READ-ONLY reviewer soul for a reviewer step", () => {
    expect(
      soulForStep({ role: "reviewer", soul: "READ-ONLY" }),
    ).toBe("READ-ONLY");
  });

  it("throws when spec.soul contradicts the role's baked soul (dead-field guard)", () => {
    // The StepSpec.soul field is consumed (not dangling): a reviewer step that
    // carries the coder soul is a misconfigured spec — the baked reviewer image
    // soul is selected by role, so a contradicting soul must not be shipped.
    expect(() =>
      soulForStep({ role: "reviewer", soul: "coder" }),
    ).toThrow(/soul/i);
    expect(() =>
      soulForStep({ role: "coder", soul: "READ-ONLY" }),
    ).toThrow(/soul/i);
  });
});

// ─── per-step sessionId extraction (#256 seam extension) ─────────────────────

describe("realBackend lastSessionId", () => {
  it("returns the LAST iteration's sessionId", () => {
    expect(
      lastSessionId({
        iterations: [{ sessionId: "a" }, { sessionId: "b" }, { sessionId: "c" }],
      }),
    ).toBe("c");
  });
  it("skips trailing iterations with no sessionId", () => {
    expect(
      lastSessionId({ iterations: [{ sessionId: "a" }, {}, {}] }),
    ).toBe("a");
  });
  it("returns undefined when no iteration carries a sessionId", () => {
    expect(lastSessionId({ iterations: [{}, {}] })).toBeUndefined();
    expect(lastSessionId({ iterations: [] })).toBeUndefined();
  });
});

describe("realBackend isLikelySha", () => {
  it("accepts 7–40 lower-hex, rejects branch names / upper / short", () => {
    expect(isLikelySha("abc1234")).toBe(true);
    expect(isLikelySha("a".repeat(40))).toBe(true);
    expect(isLikelySha("feat/x")).toBe(false);
    expect(isLikelySha("ABC1234")).toBe(false);
    expect(isLikelySha("abc12")).toBe(false);
  });
});

// ─── resume error classification (#285) ─────────────────────────────────────

describe("realBackend classifyResumeError", () => {
  it("propagates StructuredOutputError instead of falling back to a fresh run", () => {
    const err = new StructuredOutputError("bad output", {
      tag: "review",
      rawMatched: undefined,
      commits: [],
      branch: "feat/x",
      sessionId: "sess-123",
    });
    expect(classifyResumeError(err)).toEqual({ kind: "propagate" });
  });

  it("propagates schema-parse style StructuredOutputError with no sessionId", () => {
    const err = new StructuredOutputError("bad output", {
      tag: "review",
      rawMatched: undefined,
      commits: [],
      branch: "feat/x",
    });
    expect(classifyResumeError(err)).toEqual({ kind: "propagate" });
  });

  it("fresh-run only for an explicit dead or missing resume session", () => {
    expect(classifyResumeError(new Error("session not found"))).toEqual({
      kind: "fresh-run",
    });
    expect(classifyResumeError(new Error("resume session expired"))).toEqual({
      kind: "fresh-run",
    });
    expect(
      classifyResumeError(
        new Error('resumeSession "session-escalated-S2" not found under /tmp/sc'),
      ),
    ).toEqual({ kind: "fresh-run" });
    expect(
      classifyResumeError(
        new Error(
          "Session resume failed: session session-escalated-S2 not found in /tmp/sc",
        ),
      ),
    ).toEqual({ kind: "fresh-run" });
  });

  it("propagates auth, model, and generic errors", () => {
    expect(classifyResumeError(new Error("401 unauthorized"))).toEqual({
      kind: "propagate",
    });
    expect(classifyResumeError(new Error("session token not found"))).toEqual({
      kind: "propagate",
    });
    expect(classifyResumeError(new Error("model overloaded"))).toEqual({
      kind: "propagate",
    });
    expect(
      classifyResumeError(new Error("could not resume session: 401 unauthorized")),
    ).toEqual({ kind: "propagate" });
    expect(classifyResumeError("string error")).toEqual({ kind: "propagate" });
  });
});

// ─── failedStep attribution (codex#3) ────────────────────────────────────────

describe("realBackend attributeFailure (codex#3)", () => {
  it("prefixes the failing step + phase onto the cause", () => {
    const e = attributeFailure("S1", "prepareWorktree", new Error("git boom"));
    expect(e.message).toBe("S1:prepareWorktree — git boom");
  });
  it("stringifies a non-Error cause", () => {
    const e = attributeFailure("S7", "push", "denied");
    expect(e.message).toBe("S7:push — denied");
  });
  it("appends execFileSync stderr so the S8 package shows the real cause (gemini R2)", () => {
    // execFileSync throws an Error whose `.message` is just "Command failed: gh …"
    // but the actionable detail (gh GraphQL error, git reject) lives on `.stderr`.
    const err = Object.assign(new Error("Command failed: gh api …"), {
      stderr: Buffer.from("GraphQL: Could not resolve to a node (issue #999)\n"),
    });
    const e = attributeFailure("S7", "push", err);
    expect(e.message).toContain("S7:push — Command failed: gh api …");
    expect(e.message).toContain(
      "GraphQL: Could not resolve to a node (issue #999)",
    );
  });
  it("does not append a blank stderr line when stderr is empty", () => {
    const err = Object.assign(new Error("boom"), { stderr: "   " });
    const e = attributeFailure("S1", "prepareWorktree", err);
    expect(e.message).toBe("S1:prepareWorktree — boom");
  });
});

// ─── promptsDir validation (integ-cmr 256 r2, F4) ────────────────────────────

describe("realBackend promptsDirError (F4)", () => {
  const abs = "/abs/prompts";

  it("rejects a relative promptsDir (Sandcastle resolves against process.cwd())", () => {
    const err = promptsDirError("./prompts", false, true, []);
    expect(err).toMatch(/must be an ABSOLUTE path/);
    expect(err).toMatch(/process\.cwd/);
  });

  it("rejects a non-existent absolute promptsDir", () => {
    expect(promptsDirError(abs, true, false, [])).toMatch(/does not exist/);
  });

  it("rejects an absolute existing dir missing referenced promptFiles", () => {
    const err = promptsDirError(abs, true, true, ["coder_fix.md"]);
    expect(err).toMatch(/missing required promptFile/);
    expect(err).toMatch(/coder_fix\.md/);
  });

  it("accepts an absolute, existing dir with all referenced files (undefined)", () => {
    expect(promptsDirError(abs, true, true, [])).toBeUndefined();
  });

  it("REFERENCED_PROMPT_FILES covers every dispatched worker prompt incl. ship.md + review-loop (integ-cmr int-r1 C-3 / #739)", () => {
    const files = [...REFERENCED_PROMPT_FILES];
    expect(new Set(files)).toEqual(
      new Set([
        "coder_implement.md",
        "coder_fix.md",
        "reviewer_review.md",
        "ship.md",
        "verify.md",
        "fixer.md",
        "docRelease.md",
        "integrated_cmr_completeness.md",
        "integrated_cmr_correctness.md",
      ]),
    );
    // No duplicates.
    expect(new Set(files).size).toBe(files.length);
    // #739: S12 real worker must fail-fast at construction if prompt missing.
    expect(REFERENCED_PROMPT_FILES).toContain("docRelease.md");
  });

  it("prompt inventory is route-independent and does not call shipWorkerSpec during module setup", () => {
    const src = readFileSync(
      fileURLToPath(new URL("../src/realBackend.ts", import.meta.url)),
      "utf8",
    );
    expect(src).not.toContain("shipWorkerSpec().promptFile");
  });

  it("promptsDirError reports a dir missing ship.md as invalid (integ-cmr int-r1 C-3)", () => {
    // A promptsDir that has the four agent prompts but no ship.md must FAIL
    // construction validation — not pass and crash at S7 run time.
    const err = promptsDirError(abs, true, true, ["ship.md"]);
    expect(err).toMatch(/missing required promptFile/);
    expect(err).toMatch(/ship\.md/);
  });
});

describe("realBackend soulsDirError (#372)", () => {
  const abs = "/abs/souls";

  it("rejects empty soulsDir (required)", () => {
    const err = soulsDirError("", false, false, []);
    expect(err).toMatch(/soulsDir is required/);
  });

  it("rejects a non-absolute soulsDir", () => {
    const err = soulsDirError("./souls", false, true, []);
    expect(err).toMatch(/absolute path to an existing directory/);
  });

  it("rejects a non-existent absolute soulsDir", () => {
    expect(soulsDirError(abs, true, false, [])).toMatch(/absolute path to an existing directory/);
  });

  it("dir-exists-but-missing-souls throws with the missing filenames", () => {
    // dir exists but points at wrong/incomplete set (e.g. image/ instead of image/souls,
    // or partial checkout missing reviewer.md / output_protocol.md etc).
    const err = soulsDirError(abs, true, true, ["reviewer.md", "output_protocol.md"]);
    expect(err).toMatch(/missing required soul file\(s\)/);
    expect(err).toMatch(/reviewer\.md/);
    expect(err).toMatch(/output_protocol\.md/);
    expect(err).toMatch(/All of \[/);
    expect(err).not.toMatch(/promptFile/); // distinct from prompts error
  });

  it("accepts an absolute existing dir with zero missing (full souls set present)", () => {
    expect(soulsDirError(abs, true, true, [])).toBeUndefined();
  });

  it("REQUIRED_SOUL_FILES lists every file under image/souls incl. docRelease (#739)", () => {
    // Source of truth = orchestrator/image/souls/ directory listing via readdirSync.
    // Spot-checks + hard-coded count (e.g. size===11) still pass when a new soul
    // lands on disk but is missing from REQUIRED_SOUL_FILES — that is the #739
    // fail-late regression. Exact set equality catches both directions:
    // constant missing a dir file, or constant listing a file that is gone.
    const here = dirname(fileURLToPath(import.meta.url));
    const realSoulsDir = join(here, "..", "image", "souls");
    const onDisk = readdirSync(realSoulsDir)
      .filter((name) => !name.startsWith("."))
      .sort();
    const required = [...REQUIRED_SOUL_FILES].sort();
    expect(required).toEqual(onDisk);
    expect(onDisk).toContain("docRelease.md");
    expect(REQUIRED_SOUL_FILES).toContain("docRelease.md");
    // No duplicates in the constant (sort hides them in the equality above).
    expect(new Set(REQUIRED_SOUL_FILES).size).toBe(REQUIRED_SOUL_FILES.length);
  });

  it("soulsDirError reports missing docRelease.md by name (#739 fail-fast)", () => {
    const err = soulsDirError(abs, true, true, ["docRelease.md"]);
    expect(err).toMatch(/missing required soul file\(s\)/);
    expect(err).toMatch(/docRelease\.md/);
    expect(err).toMatch(/All of \[/);
  });
});

describe("RealBackend construction validates promptsDir (F4)", () => {
  // The checked-in prompts/ dir lives next to src/ — resolve it from this test
  // file's location so the assertion is path-independent.
  const here = dirname(fileURLToPath(import.meta.url));
  const realPromptsDir = join(here, "..", "prompts");
  const realSoulsDir = join(here, "..", "image", "souls");

  // #292: the driver now feeds sourceRepo (+remote) + a deterministic runKey;
  // RealBackend builds its own dedicated clone. Stub the clone seams so these
  // promptsDir-validation tests never touch real git (the build/guard logic has
  // its own dedicated tests in clone-isolation-292-build.test.ts).
  class StubCloneBackend extends RealBackend {
    protected override cloneDirExists(): boolean {
      return true; // pretend the clone already exists ⇒ no `git clone`
    }
    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git"; // own .git ⇒ fail-closed guard passes
      }
      return "";
    }
  }

  const baseOpts = {
    sourceRepo: "/tmp/source",
    remote: "https://github.com/owner/name.git",
    runKey: 999,
    repo: "owner/name",
    imageName: "img",
    soulsDir: realSoulsDir,
    skillsMount: "/tmp/skills",
    // #748: construction still resolves clone paths under home. Create it on
    // access because each test's cleanup removes the previous temp home.
    get home() {
      return tempHome("rb-home-prompts-");
    },
  };

  it("allocates a fresh home for each base option access", () => {
    const firstHome = baseOpts.home;
    const secondHome = baseOpts.home;

    expect(secondHome).not.toBe(firstHome);
    expect(existsSync(firstHome)).toBe(true);
    expect(existsSync(secondHome)).toBe(true);
  });

  it("constructs successfully against the checked-in absolute prompts/ dir", () => {
    expect(
      () => new StubCloneBackend({ ...baseOpts, promptsDir: realPromptsDir }),
    ).not.toThrow();
  });

  it("does not calculate telemetry fingerprints during construction", () => {
    const configure = vi.spyOn(
      telemetry,
      "configureTelemetryFromWorkerImage",
    );

    new StubCloneBackend({ ...baseOpts, promptsDir: realPromptsDir });

    expect(configure).not.toHaveBeenCalled();
  });

  it("throws on a relative promptsDir", () => {
    expect(
      () => new StubCloneBackend({ ...baseOpts, promptsDir: "prompts" }),
    ).toThrow(/must be an ABSOLUTE path/);
  });

  it("throws on an absolute promptsDir that does not exist", () => {
    expect(
      () =>
        new StubCloneBackend({
          ...baseOpts,
          promptsDir: "/definitely/not/a/real/dir/xyz",
        }),
    ).toThrow(/does not exist/);
  });

  it("dir-exists-but-missing-souls throws with the missing filenames", () => {
    // Use a real existing dir (mkdtemp) that has no soul files inside.
    // Ctor must reject before any clone/git work (validateSoulsDir runs early).
    const badSouls = mkdtempSync(join(tmpdir(), "dir-exists-missing-souls-"));
    expect(() =>
      new StubCloneBackend({
        ...baseOpts,
        promptsDir: realPromptsDir,
        soulsDir: badSouls,
      }),
    ).toThrow(/missing required soul file\(s\):/);
    let msg = "";
    try {
      new StubCloneBackend({
        ...baseOpts,
        promptsDir: realPromptsDir,
        soulsDir: badSouls,
      });
    } catch (e: any) {
      msg = String(e?.message ?? e);
    }
    expect(msg).toMatch(/cmr\.md/);
    expect(msg).toMatch(/output_protocol\.md/);
    expect(msg).toMatch(/All of \[/);
  });
});

describe("RealBackend reviewer output contract", () => {
  class DecodeOnlyBackend extends RealBackend {
    protected override cloneDirExists(): boolean {
      return true;
    }
    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      throw new Error(`unexpected shell call: ${file} ${args.join(" ")}`);
    }
  }

  const reviewerSpec: StepSpec = {
    id: "S6",
    role: "reviewer",
    promptFile: "reviewer_review.md",
    model: "gpt-5.6-sol",
    completionSignal: "REVIEWER_STEP_COMPLETE",
    maxIter: 1,
    soul: "READ-ONLY",
    toolchain: ["node", "typescript"],
  };
  const coderSpec: StepSpec = {
    id: "S5",
    role: "coder",
    promptFile: "coder_fix.md",
    model: "sonnet",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    soul: "coder",
    toolchain: ["node", "typescript"],
  };

  it("rings a coder decision bell even when the rest of the receipt is unusable cargo", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const backend = new DecodeOnlyBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 873,
      repo: "owner/name",
      imageName: "img",
      promptsDir: join(here, "..", "prompts"),
      soulsDir: join(here, "..", "image", "souls"),
      home: tempHome("rb-home-coder-bell-"),
    });

    const decoded = (
      backend as unknown as {
        decodeOutput(spec: StepSpec, raw: unknown): StepOutput;
      }
    ).decodeOutput(coderSpec, {
      committed: "not-a-boolean",
      unknownCargo: { any: "bytes" },
      escalate: { reason: "owner decision needed", diagnosis: "contract conflict" },
    });

    expect(decoded).toMatchObject({
      escalate: { reason: "owner decision needed", diagnosis: "contract conflict" },
    });
  });

  it("transports reviewer rows without adjudicating disposition fields", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const backend = new DecodeOnlyBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 445,
      repo: "owner/name",
      imageName: "img",
      promptsDir: join(here, "..", "prompts"),
      soulsDir: join(here, "..", "image", "souls"),
      home: tempHome("rb-home-reviewer-"),
    });

    expect(() =>
      (
        backend as unknown as {
          decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
        }
      ).decodeOutput(
        reviewerSpec,
        {
          findings: [],
          priorFindingDispositions: [
            {
              identityKey: "correctness|orchestrator/src/x.ts:1|accepted",
              status: "accepted_suppressed",
              source: "#445 owner answer",
              scope: "runner review/fix loop",
              boundedReopen: "reopen if the same finding recurs in this scope",
            },
          ],
        },
        undefined,
      ),
    ).not.toThrow();
  });

  it("normalizes accepted_suppressed findings with canonical disposition reason first", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const backend = new DecodeOnlyBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 445,
      repo: "owner/name",
      imageName: "img",
      promptsDir: join(here, "..", "prompts"),
      soulsDir: join(here, "..", "image", "souls"),
      home: tempHome("rb-home-reviewer-"),
    });

    const decoded = (
      backend as unknown as {
        decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): {
          findings?: ReadonlyArray<{ disposition_reason?: string }>;
        };
      }
    ).decodeOutput(
      reviewerSpec,
      {
        findings: [
          {
            severity: "medium",
            category: "correctness",
            claim_quote: "Known accepted gap",
            location: "orchestrator/src/runner.ts:42",
            suggested_fix: "keep the bounded suppression",
            action: "wont_fix",
            disposition_reason: "legacy fallback should not win",
            disposition: {
              kind: "accepted_suppressed",
              source: "#445 owner answer",
              scope: "runner review/fix loop",
              reason: "Owner accepted this bounded risk.",
              boundedReopen: "reopen if the same finding recurs in this scope",
            },
          },
        ],
        priorFindingDispositions: [],
      },
      undefined,
    );

    expect(decoded.findings?.[0]?.disposition_reason).toBe("legacy fallback should not win");
  });

  // #604 correctness r2 (C3): the standalone reviewer disposition schema is
  // `.strict()`, so a disposition carrying the deleted `targetModule` field (or
  // any other unknown key) is REJECTED here rather than silently stripped —
  // parity with the family parser and the Python outcome guard.
  it("treats unknown reviewer fields as cargo", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const backend = new DecodeOnlyBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 445,
      repo: "owner/name",
      imageName: "img",
      promptsDir: join(here, "..", "prompts"),
      soulsDir: join(here, "..", "image", "souls"),
      home: tempHome("rb-home-reviewer-"),
    });

    expect(() =>
      (
        backend as unknown as {
          decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
        }
      ).decodeOutput(
        reviewerSpec,
        {
          findings: [
            {
              severity: "medium",
              category: "correctness",
              claim_quote: "deleted field must no longer validate",
              location: "orchestrator/src/runner.ts:42",
              suggested_fix: "keep the bounded suppression",
              action: "wont_fix",
              disposition_reason: "r",
              disposition: {
                kind: "accepted_suppressed",
                source: "#445 owner answer",
                scope: "runner review/fix loop",
                reason: "Owner accepted this bounded risk.",
                boundedReopen: "reopen if the same finding recurs in this scope",
                targetModule: "some-module",
              },
            },
          ],
          priorFindingDispositions: [],
        },
        undefined,
      ),
    ).not.toThrow();
  });

  it("does not let unusable repair-evidence cargo change coder completion fate", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const backend = new DecodeOnlyBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 445,
      repo: "owner/name",
      imageName: "img",
      promptsDir: join(here, "..", "prompts"),
      soulsDir: join(here, "..", "image", "souls"),
      home: tempHome("rb-home-reviewer-"),
    });

    expect(() =>
      (
        backend as unknown as {
          decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
        }
      ).decodeOutput(
        coderSpec,
        {
          committed: true,
          commitsAdded: 1,
          repairEvidence: {
            findingScope: {
              identityKeys: ["correctness|orchestrator/src/x.ts:1|bug"],
            },
            patchSummary: "updated the fix",
          },
        },
        1,
      ),
    ).not.toThrow();
  });
});

// ─── #596 F2: real decode seam for verify/fixer/cleanup/docRelease (raw, not fake) ───

describe("#596 F2: RealBackend outputFor/decodeOutput wires 4 review-loop kinds via raw tag-extract + decodeOutput (verify/fixer/cleanup/docRelease; valid shapes pass to typed; extra-key/malformed fail-closed; also covers outputFor for verify)", () => {
  class DecodeOnlyBackend extends RealBackend {
    protected override cloneDirExists(): boolean {
      return true;
    }
    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      throw new Error(`unexpected shell call: ${file} ${args.join(" ")}`);
    }
  }

  const here = dirname(fileURLToPath(import.meta.url));
  function makeBackend() {
    return new DecodeOnlyBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 596,
      repo: "owner/name",
      imageName: "img",
      promptsDir: join(here, "..", "prompts"),
      soulsDir: join(here, "..", "image", "souls"),
      home: tempHome("rb-home-596-"),
    });
  }

  const verifySpec: StepSpec = {
    id: "S9",
    role: "verify",
    promptFile: "dummy.md",
    model: "gpt-5.6-sol",
    completionSignal: "VERIFY_COMPLETE",
    maxIter: 1,
    soul: "READ-ONLY",
    toolchain: ["node"],
  };
  const fixerSpec: StepSpec = {
    id: "S10",
    role: "fixer",
    promptFile: "dummy.md",
    model: "gpt-5.6-sol",
    completionSignal: "FIXER_COMPLETE",
    maxIter: 1,
    soul: "coder",
    toolchain: ["node"],
  };
  const cleanupSpec: StepSpec = {
    id: "S11",
    role: "cleanup",
    promptFile: "dummy.md",
    model: "gpt-5.6-sol",
    completionSignal: "CLEANUP_COMPLETE",
    maxIter: 1,
    soul: "READ-ONLY",
    toolchain: ["node"],
  };
  const docReleaseSpec: StepSpec = {
    id: "S12",
    role: "docRelease",
    promptFile: "dummy.md",
    model: "gpt-5.6-sol",
    completionSignal: "DOCRELEASE_COMPLETE",
    maxIter: 1,
    soul: "READ-ONLY",
    toolchain: ["node"],
  };
  const coderSpec: StepSpec = {
    id: "S2",
    role: "coder",
    promptFile: "dummy.md",
    model: "gpt-5.6-sol",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 1,
    soul: "coder",
    toolchain: ["node"],
  };

  it("decodeOutput on RAW valid verify produces correct VerifyResult (not fake construction)", () => {
    const backend = makeBackend();
    // touch outputFor as part of the seam (AC2)
    const outDef = (backend as any).outputFor?.(verifySpec);
    if (outDef && typeof outDef === "object" && "tag" in outDef) {
      expect(outDef.tag).toBe("verify");
    }
    const raw = extractVerifyTag('<verify>{"converged": true}</verify>');
    const decoded = (
      backend as unknown as {
        decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
      }
    ).decodeOutput(verifySpec, raw, undefined);
    expect(decoded).toEqual({ kind: "verify", converged: true });
  });

  it("decodeOutput on RAW valid-but-false verify still succeeds (AC: shape-valid false passes)", () => {
    const backend = makeBackend();
    const raw = extractVerifyTag('<verify>{"converged": false}</verify>');
    const decoded = (
      backend as unknown as {
        decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
      }
    ).decodeOutput(verifySpec, raw, undefined);
    expect(decoded).toEqual({ kind: "verify", converged: false });
  });

  it("passes unusable verify cargo to the fixed fixer topology", () => {
    const backend = makeBackend();
    const decoded = (
        backend as unknown as {
          decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
        }
      ).decodeOutput(verifySpec, extractVerifyTag('<verify>{"converged": "notbool"}</verify>'), undefined);
    expect(decoded).toEqual({ kind: "coder", committed: false, commitsAdded: 0 });
  });

  it("keeps absent receipt bytes as cargo without inventing a decision bell", () => {
    const backend = makeBackend();
    const decodeOutput = (backend as unknown as {
      decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
    }).decodeOutput.bind(backend);

    for (const [spec, gitCommitCount] of [
      [coderSpec, 1],
      [verifySpec, undefined],
      [fixerSpec, undefined],
      [cleanupSpec, undefined],
      [docReleaseSpec, undefined],
    ] as const) {
      expect(decodeOutput(spec, undefined, gitCommitCount)).toEqual({
        kind: "coder", committed: false, commitsAdded: 0,
      });
    }
  });

  it("decodeOutput on RAW valid fixer produces FixerResult via real seam", () => {
    const backend = makeBackend();
    const raw = extractFixerTag('<fixer>{"committed": false}</fixer>');
    const decoded = (
      backend as unknown as {
        decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
      }
    ).decodeOutput(fixerSpec, raw, undefined);
    expect(decoded).toEqual({ kind: "fixer", committed: false });
  });

  it("pin r39: decodeOutput on RAW committed:true fixer requires fixCommitSha", () => {
    const backend = makeBackend();
    const sha = "b".repeat(40);
    const raw = extractFixerTag(
      `<fixer>{"committed": true, "fixCommitSha": "${sha}"}</fixer>`,
    );
    const decoded = (
      backend as unknown as {
        decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
      }
    ).decodeOutput(fixerSpec, raw, undefined);
    expect(decoded).toEqual({ kind: "fixer", committed: true, fixCommitSha: sha });
  });

  it("does not let missing fixer cargo stop the fresh re-review topology", () => {
    const backend = makeBackend();
    const decoded = (
        backend as unknown as {
          decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
        }
      ).decodeOutput(
        fixerSpec,
        extractFixerTag('<fixer>{"committed": true}</fixer>'),
        undefined,
      );
    expect(decoded).toEqual({ kind: "coder", committed: false, commitsAdded: 0 });
  });

  it("decodeOutput on RAW valid cleanup produces CleanupResult via real seam", () => {
    const backend = makeBackend();
    const raw = extractCleanupTag('<cleanup>{"terminal": true, "ok": true}</cleanup>');
    const decoded = (
      backend as unknown as {
        decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
      }
    ).decodeOutput(cleanupSpec, raw, undefined);
    expect(decoded).toEqual({ kind: "cleanup", terminal: true, ok: true });
  });

  it("decodeOutput on RAW valid docRelease produces DocReleaseResult via real seam", () => {
    const backend = makeBackend();
    const raw = extractDocReleaseTag('<docRelease>{"released": false}</docRelease>');
    const decoded = (
      backend as unknown as {
        decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
      }
    ).decodeOutput(docReleaseSpec, raw, undefined);
    expect(decoded).toEqual({ kind: "docRelease", released: false });
  });

  it("tolerates unknown cleanup cargo keys", () => {
    const backend = makeBackend();
    const decoded = (
        backend as unknown as {
          decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
        }
      ).decodeOutput(cleanupSpec, extractCleanupTag('<cleanup>{"terminal": true, "ok": true, "extra": 1}</cleanup>'), undefined);
    expect(decoded).toMatchObject({ kind: "cleanup", terminal: true, ok: true });
  });

  it("does not let unusable doc-release cargo change the next edge", () => {
    const backend = makeBackend();
    const decoded = (
        backend as unknown as {
          decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
        }
      ).decodeOutput(docReleaseSpec, extractDocReleaseTag('<docRelease>{"released": "no"}</docRelease>'), undefined);
    expect(decoded).toEqual({ kind: "coder", committed: false, commitsAdded: 0 });
  });

  it("decodeOutput on unknown role for review-loop raw fails closed", () => {
    const backend = makeBackend();
    const badSpec = { ...verifySpec, role: "unknown" as any };
    expect(() =>
      (
        backend as unknown as {
          decodeOutput(spec: StepSpec, raw: unknown, gitCommitCount: number | undefined): unknown;
        }
      ).decodeOutput(badSpec, { converged: true }, undefined),
    ).toThrow(/cannot decode output for unknown role/);
  });
});

// ─── #286 toolchain preflight before agent dispatch ─────────────────────────

describe("RealBackend runStep toolchain preflight (#286)", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const realPromptsDir = join(here, "..", "prompts");
  const realSoulsDir = join(here, "..", "image", "souls");

  const coderSpec: StepSpec = {
    id: "S2",
    role: "coder",
    promptFile: "coder_implement.md",
    model: "gpt-5.6-sol",
    completionSignal: "CODER_STEP_COMPLETE",
    maxIter: 5,
    soul: "coder",
    toolchain: ["python", "node", "npm", "typescript"],
  };
  const reviewerSpec: StepSpec = {
    id: "S3",
    role: "reviewer",
    promptFile: "reviewer_review.md",
    model: "gpt-5.6-sol",
    completionSignal: "REVIEWER_STEP_COMPLETE",
    maxIter: 1,
    soul: "READ-ONLY",
    toolchain: ["node", "typescript"],
  };

  class PreflightBackend extends RealBackend {
    public agentRunReached = false;
    public agentResult?: Awaited<ReturnType<typeof sc.run>>;
    public lastAgentOptions?: Parameters<typeof sc.run>[0];
    public preflightResults = new Map<string, boolean>();
    public preflightHook?: (tool: string) => Promise<void>;
    /** Final reachable commits after the fresh worker's pinned baseline. */
    public finalGraphCommitCount = 0;

    protected override cloneDirExists(): boolean {
      return true;
    }

    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      if (file === "git" && args[0] === "rev-parse" && args[1] === "HEAD") {
        return "a".repeat(40);
      }
      if (file === "git" && args[0] === "rev-list" && args[1] === "--count") {
        return String(this.finalGraphCommitCount);
      }
      return "";
    }

    protected override async preflightToolchainTool(tool: string): Promise<void> {
      if (this.preflightHook !== undefined) return this.preflightHook(tool);
      if (this.preflightResults.get(tool) === false) {
        throw new Error(`${tool}: command not found`);
      }
    }

    protected override async runAgentSandbox(
      options: Parameters<typeof sc.run>[0],
    ): Promise<Awaited<ReturnType<typeof sc.run>>> {
      this.lastAgentOptions = options;
      this.agentRunReached = true;
      if (this.agentResult !== undefined) return this.agentResult;
      throw new Error("agent sandbox should not run during this test");
    }
  }

  function makeBackend(home = tempHome("rb-home-286-")): PreflightBackend {
    return new PreflightBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 286,
      repo: "owner/name",
      imageName: "ming-worker:bad",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      // #748: runStep → box → mountAuth must not touch real ~/.sc-orchestrator.
      home,
    });
  }

  it("fails before the agent sandbox when the declared image lacks a tool", async () => {
    const backend = makeBackend();
    backend.preflightResults.set("npm", false);

    await expect(
      backend.runStep(coderSpec, {
        branch: "feat/issue-286",
        base: "main",
        path: "/tmp/worktree/issue-286",
      }),
    ).rejects.toThrow(/toolchain preflight.*ming-worker:bad.*npm/is);
    expect(backend.agentRunReached).toBe(false);
  });

  it("continues to the agent sandbox when all declared tools exist", async () => {
    const backend = makeBackend();
    backend.agentResult = agentRunResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout: '<coder>{"committed": false, "commitsAdded": 0}</coder>',
      commits: [],
      sessionId: "sess-286",
    });

    const result = await backend.runStep(coderSpec, {
      branch: "feat/issue-286",
      base: "main",
      path: "/tmp/worktree/issue-286",
    });

    expect(backend.agentRunReached).toBe(true);
    expect(result).toEqual({
      output: { kind: "coder", committed: false, commitsAdded: 0 },
      sessionId: "sess-286",
    });
  });

  it("continues a clean-exit coder when receipt cargo is absent", async () => {
    const backend = makeBackend();
    backend.agentResult = agentRunResult({
      stdout: "worker completed its changes",
      commits: [{ sha: "abc123" }],
      sessionId: "sess-advisory-exit",
    });

    await expect(
      backend.runStep(coderSpec, {
        branch: "feat/issue-286",
        base: "main",
        path: "/tmp/worktree/issue-286",
      }),
    ).resolves.toMatchObject({
      output: { kind: "coder", committed: false, commitsAdded: 0 },
    });
  });

  it("continues a resumed clean-exit coder when receipt cargo is absent", async () => {
    const backend = makeBackend();
    backend.agentResult = agentRunResult({
      stdout: "resumed worker completed its changes",
      commits: [{ sha: "abc123" }],
      sessionId: "sess-resumed-advisory-exit",
    });

    await expect(
      backend.resumeSession(
        coderSpec,
        {
          branch: "feat/issue-286",
          base: "main",
          path: "/tmp/worktree/issue-286",
        },
        "prior-coder-session",
      ),
    ).resolves.toMatchObject({
      output: { kind: "coder", committed: false, commitsAdded: 0 },
    });
    expect(backend.lastAgentOptions?.resumeSession).toBe("prior-coder-session");
  });

  it("preserves a missing reviewer count as unusable cargo for the fixer", async () => {
    const backend = makeBackend();
    backend.agentResult = agentRunResult({
      stdout: "reviewer finished without a machine verdict",
      commits: [],
      sessionId: "sess-missing-review-outcome",
    });

    await expect(
      backend.runStep(reviewerSpec, {
        branch: "feat/issue-824",
        base: "main",
        path: "/tmp/worktree/issue-824",
      }),
    ).resolves.toMatchObject({
      output: { kind: "coder", committed: false, commitsAdded: 0 },
    });
  });

  it("accepts a reviewer verdict from any one supported outcome channel", () => {
    const backend = makeBackend();
    const rawOutputFor = (backend as unknown as {
      rawOutputFor(
        result: { output?: unknown; stdout: string },
        spec: StepSpec,
        typedOutputUsed: boolean,
        options?: { outcomeLanding?: { path: string; sandboxPath: string } },
      ): unknown;
    }).rawOutputFor.bind(backend);
    const payload = { findings: [] };

    expect(rawOutputFor({ output: payload, stdout: "" }, reviewerSpec, true)).toEqual(payload);
    expect(
      rawOutputFor({ stdout: '<review>{"findings": []}</review>' }, reviewerSpec, false),
    ).toEqual(payload);

    const dir = mkdtempSync(join(tmpdir(), "worker-review-sidecar-channel-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, JSON.stringify(payload), "utf8");
    expect(
      rawOutputFor(
        { stdout: "" },
        reviewerSpec,
        false,
        { outcomeLanding: { path: outcomePath, sandboxPath: ".orchestrator-outcome.json" } },
      ),
    ).toEqual(payload);

    expect(
      rawOutputFor(
        {
          stdout:
            '<review>{"junk": true, "escalate": {"reason": "owner choice", "diagnosis": "review fork"}}</review>',
        },
        reviewerSpec,
        false,
        { outcomeLanding: { path: outcomePath, sandboxPath: ".orchestrator-outcome.json" } },
      ),
    ).toMatchObject({
      escalate: { reason: "owner choice", diagnosis: "review fork" },
    });
  });

  it("does not label a multi-iteration coder stdout tag as a legacy fallback", () => {
    const backend = makeBackend();
    const rawOutputFor = (backend as unknown as {
      rawOutputFor(
        result: { output?: unknown; stdout: string },
        spec: StepSpec,
        typedOutputUsed: boolean,
      ): unknown;
    }).rawOutputFor.bind(backend);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    expect(
      rawOutputFor(
        { stdout: '<coder>{"committed": false, "commitsAdded": 0}</coder>' },
        coderSpec,
        false,
      ),
    ).toEqual({ committed: false, commitsAdded: 0 });
    expect(warn).not.toHaveBeenCalled();
  });

  it("keeps the legacy advisory when stdout substitutes for missing typed output", () => {
    const backend = makeBackend();
    const rawOutputFor = (backend as unknown as {
      rawOutputFor(
        result: { output?: unknown; stdout: string },
        spec: StepSpec,
        typedOutputUsed: boolean,
      ): unknown;
    }).rawOutputFor.bind(backend);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    expect(
      rawOutputFor({ stdout: '<review>{"findings": []}</review>' }, reviewerSpec, true),
    ).toEqual({ findings: [] });
    expect(warn).toHaveBeenCalledWith(
      "[orchestrator] telemetry: S3-reviewer used legacy stdout tag compatibility fallback",
    );
  });

  it("reclaims the temporary Grok OAuth copy after a worker container exits", async () => {
    const home = tempHome("rb-home-grok-auth-");
    mkdirSync(join(home, ".grok"), { recursive: true });
    writeFileSync(join(home, ".grok", "auth.json"), '{"token":"test"}\n');
    const backend = makeBackend(home);
    backend.agentResult = agentRunResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout: '<coder>{"committed": false, "commitsAdded": 0}</coder>',
      commits: [],
      sessionId: "sess-grok-auth-cleanup",
    });

    await backend.runStep(coderSpec, {
      branch: "feat/issue-286",
      base: "main",
      path: "/tmp/worktree/issue-286",
    });

    expect(
      readdirSync(join(home, ".sc-orchestrator")).filter((name) =>
        name.startsWith("grok-auth-286-"),
      ),
    ).toEqual([]);
  });

  it("prefers a runner-owned outcome sidecar over malformed coder stdout", async () => {
    const backend = makeBackend();
    backend.finalGraphCommitCount = 1;
    const dir = mkdtempSync(join(tmpdir(), "worker-outcome-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ committed: true, commitsAdded: 1 }) + "\n",
      "utf8",
    );
    backend.agentResult = agentRunResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout: "<coder>not json</coder>\nCODER_STEP_COMPLETE",
      commits: [{ sha: "abc123" }],
      sessionId: "sess-496",
    });

    const result = await backend.runStep(
      coderSpec,
      {
        branch: "feat/issue-496",
        base: "main",
        path: "/tmp/worktree/issue-496",
      },
      {
        outcomeLanding: {
          path: outcomePath,
          sandboxPath: ".orchestrator-outcome.json",
        },
      },
    );

    expect(result).toEqual({
      output: { kind: "coder", committed: true, commitsAdded: 1 },
      sessionId: "sess-496",
    });
  });

  it("preserves the fresh coder self-report without inspecting observed commits", async () => {
    const backend = makeBackend();
    // Sandcastle's commit observations are irrelevant to the worker-authored
    // completion report.
    backend.finalGraphCommitCount = 0;
    backend.agentResult = agentRunResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout: '<coder>{"committed":true,"commitsAdded":1}</coder>',
      commits: [{ sha: "unreachable-after-reset" }],
      sessionId: "sess-final-graph-truth",
    });

    await expect(
      backend.runStep(coderSpec, {
        branch: "feat/issue-818",
        base: "main",
        path: "/tmp/worktree/issue-818",
      }),
    ).resolves.toEqual({
      output: {
        kind: "coder",
        committed: true,
        commitsAdded: 1,
      },
      sessionId: "sess-final-graph-truth",
    });
  });

  it("falls back to signaled coder stdout when the outcome sidecar path is an empty directory", async () => {
    const backend = makeBackend();
    backend.finalGraphCommitCount = 1;
    const dir = mkdtempSync(join(tmpdir(), "worker-outcome-empty-dir-"));
    const outcomePath = join(dir, "outcome.json");
    mkdirSync(outcomePath);
    backend.agentResult = agentRunResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout: '<coder>{"committed": true, "commitsAdded": 1}</coder>\nCODER_STEP_COMPLETE',
      commits: [{ sha: "abc123" }],
      sessionId: "sess-dir-sidecar",
    });

    const result = await backend.runStep(
      coderSpec,
      {
        branch: "feat/issue-582",
        base: "main",
        path: "/tmp/worktree/issue-582",
      },
      {
        outcomeLanding: {
          path: outcomePath,
          sandboxPath: ".orchestrator-outcome.json",
        },
      },
    );

    expect(result).toEqual({
      output: { kind: "coder", committed: true, commitsAdded: 1 },
      sessionId: "sess-dir-sidecar",
    });
  });

  it("prefers a runner-owned outcome sidecar for a fresh reviewer before Sandcastle tag parsing", async () => {
    const backend = makeBackend();
    const dir = mkdtempSync(join(tmpdir(), "worker-review-outcome-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ findings: [] }) + "\n",
      "utf8",
    );
    backend.agentResult = agentRunResult({
      completionSignal: "REVIEWER_STEP_COMPLETE",
      stdout: "no review tag here\nREVIEWER_STEP_COMPLETE",
      commits: [],
      sessionId: "sess-review-sidecar",
    });

    const result = await backend.runStep(
      reviewerSpec,
      {
        branch: "feat/issue-496",
        base: "main",
        path: "/tmp/worktree/issue-496",
      },
      {
        outcomeLanding: {
          path: outcomePath,
          sandboxPath: ".orchestrator-outcome.json",
        },
      },
    );

    expect(result).toEqual({
      output: { kind: "reviewer", findings: [] },
      sessionId: "sess-review-sidecar",
    });
    expect(backend.lastAgentOptions).toBeDefined();
    expect("output" in backend.lastAgentOptions!).toBe(false);
  });

  it("prefers a runner-owned outcome sidecar for a resumed reviewer before Sandcastle tag parsing", async () => {
    const backend = makeBackend();
    const dir = mkdtempSync(join(tmpdir(), "worker-review-resume-outcome-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(
      outcomePath,
      JSON.stringify({ findings: [] }) + "\n",
      "utf8",
    );
    backend.agentResult = agentRunResult({
      completionSignal: "REVIEWER_STEP_COMPLETE",
      stdout: "not json in any review tag\nREVIEWER_STEP_COMPLETE",
      commits: [],
      sessionId: "sess-review-resume-sidecar",
    });

    const result = await backend.resumeSession(
      reviewerSpec,
      {
        branch: "feat/issue-496",
        base: "main",
        path: "/tmp/worktree/issue-496",
      },
      "prior-review-session",
      {
        outcomeLanding: {
          path: outcomePath,
          sandboxPath: ".orchestrator-outcome.json",
        },
      },
    );

    expect(result).toEqual({
      output: { kind: "reviewer", findings: [] },
      sessionId: "sess-review-resume-sidecar",
    });
    expect(backend.lastAgentOptions).toBeDefined();
    expect(backend.lastAgentOptions?.resumeSession).toBe("prior-review-session");
    expect("output" in backend.lastAgentOptions!).toBe(false);
  });

  it("continues a clean-exit coder when its sidecar cargo is unreadable", async () => {
    const backend = makeBackend();
    const dir = mkdtempSync(join(tmpdir(), "worker-outcome-bad-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");
    backend.agentResult = agentRunResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout: '<coder>{"committed": false, "commitsAdded": 0}</coder>',
      commits: [],
      sessionId: "sess-bad-sidecar",
    });

    await expect(
      backend.runStep(
        coderSpec,
        {
          branch: "feat/issue-496",
          base: "main",
          path: "/tmp/worktree/issue-496",
        },
        {
          outcomeLanding: {
            path: outcomePath,
            sandboxPath: ".orchestrator-outcome.json",
          },
        },
      ),
    ).resolves.toMatchObject({
      output: { kind: "coder", committed: false, commitsAdded: 0 },
    });
  });

  it("routes unreadable reviewer sidecar cargo toward the fixer topology", async () => {
    const backend = makeBackend();
    const dir = mkdtempSync(join(tmpdir(), "worker-review-outcome-bad-"));
    const outcomePath = join(dir, "outcome.json");
    writeFileSync(outcomePath, "{not json", "utf8");
    backend.agentResult = agentRunResult({
      completionSignal: "REVIEWER_STEP_COMPLETE",
      stdout: '<review>{"findings": []}</review>',
      commits: [],
      sessionId: "sess-review-bad-sidecar",
    });

    await expect(
      backend.runStep(
        reviewerSpec,
        {
          branch: "feat/issue-496",
          base: "main",
          path: "/tmp/worktree/issue-496",
        },
        {
          outcomeLanding: {
            path: outcomePath,
            sandboxPath: ".orchestrator-outcome.json",
          },
        },
      ),
    ).resolves.toMatchObject({
      output: { kind: "coder", committed: false, commitsAdded: 0 },
    });
  });

  it("shares an in-flight toolchain preflight across concurrent agent dispatches", async () => {
    const backend = makeBackend();
    const preflightCalls: string[] = [];
    backend.preflightHook = async (tool: string): Promise<void> => {
      preflightCalls.push(tool);
      await new Promise((resolve) => setTimeout(resolve, 1));
    };
    backend.agentResult = agentRunResult({
      completionSignal: "CODER_STEP_COMPLETE",
      stdout: '<coder>{"committed": false, "commitsAdded": 0}</coder>',
      commits: [],
      sessionId: "sess-286",
    });
    const worktree = {
      branch: "feat/issue-286",
      base: "main",
      path: "/tmp/worktree/issue-286",
    };

    await Promise.all([
      backend.runStep(coderSpec, worktree),
      backend.runStep(coderSpec, worktree),
    ]);

    expect(preflightCalls).toEqual(["python", "node", "npm", "typescript"]);
  });
});

// ─── gh subIssues count parsing (integ-cmr 256 r1, Finding 1) ────────────────

describe("realBackend parseSubIssueCount", () => {
  it("reads totalCount from the real gh {nodes,totalCount} object shape", () => {
    // `gh issue view --json subIssues` returns an OBJECT, not an array:
    // {"subIssues":{"nodes":[...],"totalCount":10}}. The old Array.isArray
    // check was always false → count always 0 → the S0 parent-epic gate never
    // fired. (Verified against the live #244: totalCount:10.)
    expect(
      parseSubIssueCount({
        subIssues: {
          nodes: [{ number: 247 }, { number: 248 }],
          totalCount: 10,
        },
      }),
    ).toBe(10);
  });

  it("falls back to nodes.length when totalCount is absent", () => {
    expect(
      parseSubIssueCount({ subIssues: { nodes: [{ number: 1 }, { number: 2 }] } }),
    ).toBe(2);
  });

  it("returns 0 for a leaf issue (empty sub-issues)", () => {
    expect(parseSubIssueCount({ subIssues: { nodes: [], totalCount: 0 } })).toBe(0);
  });

  it("returns 0 when the subIssues field is missing entirely", () => {
    expect(parseSubIssueCount({})).toBe(0);
    expect(parseSubIssueCount({ subIssues: undefined })).toBe(0);
  });

  it("returns 0 (never NaN/throw) for a malformed subIssues value", () => {
    // A future/odd gh shape must never crash the S0 gate.
    expect(parseSubIssueCount({ subIssues: "weird" })).toBe(0);
    expect(parseSubIssueCount({ subIssues: 5 })).toBe(0);
    expect(parseSubIssueCount({ subIssues: { nodes: "x" } })).toBe(0);
  });
});

// ─── blocked_by parse: CONFIRMED-empty only (integ-cmr 256 r2, F2) ────────────

describe("realBackend parseBlockedBy", () => {
  it("keeps entries with numeric number + string state", () => {
    expect(
      parseBlockedBy([
        { number: 248, state: "closed" },
        { number: 254, state: "open" },
      ]),
    ).toEqual([
      { number: 248, state: "closed" },
      { number: 254, state: "open" },
    ]);
  });

  it("returns [] for a CONFIRMED empty array (no dependencies)", () => {
    expect(parseBlockedBy([])).toEqual([]);
  });

  it("drops malformed entries (missing/typed-wrong number or state)", () => {
    expect(
      parseBlockedBy([
        { number: 1, state: "open" },
        { number: "2", state: "open" }, // number wrong type → dropped
        { number: 3 }, // missing state → dropped
        { state: "open" }, // missing number → dropped
        null,
      ]),
    ).toEqual([{ number: 1, state: "open" }]);
  });

  it("returns [] for a non-array response (future/odd shape, never throws)", () => {
    // NOTE: this is the CONFIRMED-response empty path. A THROWN gh/transport
    // error is NOT routed here — fetchBlockedBy fails CLOSED (S8 error) on a
    // throw; only a confirmed non-array response degrades to [].
    expect(parseBlockedBy({})).toEqual([]);
    expect(parseBlockedBy("weird")).toEqual([]);
    expect(parseBlockedBy(undefined)).toEqual([]);
    expect(parseBlockedBy(null)).toEqual([]);
  });
});

// ─── S0 fetchIssueMeta does not over-fetch comments (#329) ───────────────────

describe("realBackend fetchIssueMeta S0 perf (#329)", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const realPromptsDir = join(here, "..", "prompts");
  const realSoulsDir = join(here, "..", "image", "souls");

  // Records every gh/git invocation and serves canned JSON so fetchIssueMeta
  // runs without touching the network. The clone seams are stubbed (same as the
  // promptsDir suite) so construction never shells out to git.
  class RecordingMetaBackend extends RealBackend {
    // Lazily initialised: the base constructor calls sh() (clone guard) before a
    // field initialiser would have run, so default it inside sh() itself.
    public calls?: string[][];
    protected override cloneDirExists(): boolean {
      return true;
    }
    protected override sh(file: string, args: string[]): string {
      (this.calls ??= []).push([file, ...args]);
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      if (file === "gh" && args[0] === "issue" && args[1] === "view") {
        const fields = args[args.indexOf("--json") + 1] ?? "";
        if (fields.includes("subIssues")) {
          return JSON.stringify({ subIssues: { nodes: [], totalCount: 0 } });
        }
        if (fields.includes("body")) {
          return JSON.stringify({
            number: 329,
            title: "author-aware snapshot",
            state: "OPEN",
            author: { login: "owner" },
            body: "## Agent Brief\nbody brief",
            labels: [{ name: "ready-for-agent" }],
            comments: [
              {
                author: { login: "owner" },
                body: "## Agent Brief\nowner comment brief",
              },
              {
                author: { login: "drive-by" },
                body: "## Agent Brief\nmalicious comment brief",
              },
            ],
          });
        }
        return JSON.stringify({
          number: 329,
          labels: [{ name: "ready-for-agent" }],
        });
      }
      if (file === "gh" && args[0] === "api") {
        return JSON.stringify([]); // blocked_by → none
      }
      return "";
    }
  }

  function makeBackend(): RecordingMetaBackend {
    return new RecordingMetaBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 999,
      repo: "owner/name",
      imageName: "img",
      skillsMount: "/tmp/skills",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      home: tempHome("rb-home-329-"),
    });
  }

  it("S0 issue-view requests gate fields + body — still no comments (#329/#767)", async () => {
    const backend = makeBackend();
    await backend.fetchIssueMeta(329);

    // The lightweight S0 view (the one that does NOT ask for subIssues).
    const issueView = (backend.calls ?? []).find(
      (c) =>
        c[0] === "gh" &&
        c[1] === "issue" &&
        c[2] === "view" &&
        !(c[c.indexOf("--json") + 1] ?? "").includes("subIssues"),
    );
    expect(issueView).toBeDefined();
    const fields = issueView![issueView!.indexOf("--json") + 1] ?? "";
    // #329: pulling `comments` triggers gh's paginated preloadIssueComments —
    // still forbidden at S0. #767: `body` is now fetched so Coder-Rec can be
    // parsed before the first worker dispatch (body alone is cheap).
    expect(fields).not.toContain("comments");
    expect(fields).toContain("body");
    expect(fields).toContain("labels");
  });

  it("S1 snapshot trusts Agent Brief sections from the repo owner only by default", async () => {
    const backend = makeBackend();
    const snapshot = await backend.fetchIssueSnapshot(329);

    expect(snapshot.agentBrief).toContain("owner comment brief");
    expect(snapshot.agentBrief).not.toContain("malicious comment brief");
    expect(snapshot.bodyAuthorLogin).toBe("owner");
    expect(snapshot.commentAuthorLogins).toEqual(["owner", "drive-by"]);

    const issueView = (backend.calls ?? []).find((c) => {
      const fields = c[c.indexOf("--json") + 1] ?? "";
      return c[0] === "gh" && c[1] === "issue" && c[2] === "view" && fields.includes("body");
    });
    expect(issueView).toBeDefined();
    const fields = issueView![issueView!.indexOf("--json") + 1] ?? "";
    expect(fields).toContain("author");
    expect(fields).toContain("comments");
  });

  it("S0 meta is still derivable from the slim view (gate fields intact)", async () => {
    const backend = makeBackend();
    const meta = await backend.fetchIssueMeta(329);
    expect(meta).toEqual({
      number: 329,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
      body: "## Agent Brief\nbody brief",
    });
  });
});

// ─── coder stdout <coder> tag decode (integ-cmr 256 r1, Finding 2) ───────────

describe("realBackend extractCoderTag", () => {
  it("extracts + JSON-parses the <coder> tag from coder stdout", () => {
    // coder steps run maxIter>1, so Sandcastle's typed `output` (which requires
    // maxIterations:1) is unavailable; the structured coder result is carried in
    // a <coder> tag in stdout instead.
    const stdout =
      "some agent chatter\n<coder>{\"committed\": true, \"commitsAdded\": 2}</coder>\nCODER_STEP_COMPLETE";
    expect(extractCoderTag(stdout)).toEqual({ committed: true, commitsAdded: 2 });
  });

  it("unwraps a fenced JSON code block inside the tag", () => {
    const stdout =
      '<coder>\n```json\n{"committed": false, "commitsAdded": 0}\n```\n</coder>';
    expect(extractCoderTag(stdout)).toEqual({
      committed: false,
      commitsAdded: 0,
    });
  });

  it("takes the LAST <coder> tag when several iterations each emit one", () => {
    const stdout =
      '<coder>{"committed": true, "commitsAdded": 1}</coder>\n' +
      'iterating…\n' +
      '<coder>{"committed": true, "commitsAdded": 3}</coder>';
    expect(extractCoderTag(stdout)).toEqual({ committed: true, commitsAdded: 3 });
  });

  it("fails closed when the final complete <coder> tag is malformed instead of reusing an older tag", () => {
    const stdout =
      '<coder>{"committed": true, "commitsAdded": 1}</coder>\n' +
      "retrying after a validation failure\n" +
      '<coder>{"committed": true, "commitsAdded": </coder>\n' +
      "CODER_STEP_COMPLETE";

    expect(() => extractCoderTag(stdout)).toThrow();
  });

  it("ignores inline prose mentions of <coder> before the final JSON tag", () => {
    const stdout =
      "我会保留最终 `<coder>` 输出作为兼容协议。\n" +
      '<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "blocked", "diagnosis": "source gap"}}</coder>\n' +
      "CODER_STEP_COMPLETE";

    expect(extractCoderTag(stdout)).toEqual({
      committed: false,
      commitsAdded: 0,
      escalate: { reason: "blocked", diagnosis: "source gap" },
    });
  });

  it("accepts a final coder tag with extra trailing braces after a balanced JSON object", () => {
    const stdout =
      '<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "blocked", "diagnosis": "source gap"}}}</coder>\n' +
      "CODER_STEP_COMPLETE";

    expect(extractCoderTag(stdout)).toEqual({
      committed: false,
      commitsAdded: 0,
      escalate: { reason: "blocked", diagnosis: "source gap" },
    });
  });

  it("accepts a final tag with extra trailing brackets after a balanced JSON array", () => {
    const stdout = '<coder>[{"committed": true, "commitsAdded": 1}]]</coder>';

    expect(extractCoderTag(stdout)).toEqual([
      { committed: true, commitsAdded: 1 },
    ]);
  });

  it("still rejects non-brace garbage after a balanced coder JSON object", () => {
    expect(() =>
      extractCoderTag(
        '<coder>{"committed": false, "commitsAdded": 0} trailing</coder>',
      ),
    ).toThrow();
  });

  it("returns an escalate payload when the coder tag carries one", () => {
    const stdout =
      '<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "blocked", "diagnosis": "design gap"}}</coder>';
    expect(parseCoderSelfReport(extractCoderTag(stdout))).toEqual({
      committed: false,
      commitsAdded: 0,
      escalate: {
        reason: "blocked",
        diagnosis: "design gap",
      },
    });
  });

  it("accepts a coder escalation with only worker-owned reason and diagnosis", () => {
    expect(parseCoderSelfReport({
      committed: false,
      commitsAdded: 0,
      escalate: { reason: "blocked", diagnosis: "design gap" },
    })).toMatchObject({
      escalate: { reason: "blocked", diagnosis: "design gap" },
    });
  });

  it("#551 accepts coder-fix repair evidence with same-class and regression checks through the real parser", () => {
    const stdout =
      '<coder>{"committed": true, "commitsAdded": 1, "repairEvidence": {"findingScope": {"identityKeys": ["correctness|orchestrator/src/realBackend.ts:1700|schema drift"], "locations": ["orchestrator/src/realBackend.ts"]}, "changedFiles": ["orchestrator/src/realBackend.ts"], "tests": ["npm test -- --run test/realBackend.logic.test.ts -t #551"], "sameClassBugScan": "rg \\"repairEvidenceSchema|isCompleteRepairEvidence\\" orchestrator/src orchestrator/test", "introducedRegressionCheck": "npm test -- --run test/family/verify-cmr-fix-loop.test.ts", "patchSummary": "thread #551 repair evidence through the real worker parser"}}</coder>';

    expect(parseCoderSelfReport(extractCoderTag(stdout))).toMatchObject({
      committed: true,
      commitsAdded: 1,
      repairEvidence: {
        sameClassBugScan:
          'rg "repairEvidenceSchema|isCompleteRepairEvidence" orchestrator/src orchestrator/test',
        introducedRegressionCheck:
          "npm test -- --run test/family/verify-cmr-fix-loop.test.ts",
      },
    });
  });

  it("treats a missing coder tag as an advisory compatibility miss", () => {
    expect(extractCoderTag("worker finished without a legacy tag")).toBeUndefined();
  });

  it("throws when the tag body is not valid JSON", () => {
    expect(() => extractCoderTag("<coder>not json</coder>")).toThrow();
  });
});
