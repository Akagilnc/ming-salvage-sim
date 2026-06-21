/**
 * Unit tests for the PURE host-side logic of the real Backend (#256).
 *
 * Scope (per #256 acceptance criteria): only the zero-container, zero-LLM logic
 * — gh-snapshot parsing, auth-mount path construction, model-slug mapping,
 * per-step sessionId extraction (seam extension), branchHEAD consistency
 * (codex#2), StructuredOutputError dead-session classification, and failedStep
 * attribution (codex#3). The real container / real-LLM / real-gh paths are #256
 * MANUAL smoke and are NOT exercised here.
 *
 * These imports load `@ai-hero/sandcastle` (side-effect-free) but never start a
 * container, so the suite runs in the same zero-infra harness as the fake-Backend
 * step control-flow tests.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  assertCompletionSignal,
  attributeFailure,
  buildAuthPaths,
  buildIssueMeta,
  buildIssueSnapshot,
  checkBranchHeadConsistency,
  classifyResumeError,
  cutRefFor,
  ensureExcluded,
  extractAgentBrief,
  FIX_FINDINGS_FILENAME,
  serializeFixFindings,
  extractCoderTag,
  hasAgentBrief,
  isLikelySha,
  isReadyForAgent,
  issueNumberFromBranch,
  lastLedgerBranchHead,
  lastSessionId,
  matchWorktreeForBranch,
  modelIdForSlug,
  parseBlockedBy,
  parseSubIssueCount,
  promptsDirError,
  realCommitCount,
  reconcileCoderCommits,
  soulForStep,
  REFERENCED_PROMPT_FILES,
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_SKILLS_DIR,
  SNAPSHOT_FILENAME,
  type GhBlockedBy,
  type GhIssueJson,
} from "../src/realBackend.js";
import { StructuredOutputError } from "@ai-hero/sandcastle";

// ─── gh JSON → IssueMeta / IssueSnapshot ─────────────────────────────────────

describe("realBackend gh parsing", () => {
  const briefComment = {
    body: "## Agent Brief\nimplement the real Backend per #256",
  };

  it("isReadyForAgent reads the ready-for-agent label", () => {
    expect(
      isReadyForAgent({ labels: [{ name: "ready-for-agent" }] }),
    ).toBe(true);
    expect(isReadyForAgent({ labels: [{ name: "bug" }] })).toBe(false);
    expect(isReadyForAgent({})).toBe(false);
  });

  it("hasAgentBrief finds the brief in a comment OR the body", () => {
    expect(hasAgentBrief({ comments: [briefComment] })).toBe(true);
    expect(hasAgentBrief({ body: "## Agent Brief\n…" })).toBe(true);
    expect(hasAgentBrief({ body: "no brief", comments: [{ body: "hi" }] })).toBe(
      false,
    );
    expect(hasAgentBrief({})).toBe(false);
  });

  it("buildIssueMeta derives the four-way gate fields", () => {
    const json: GhIssueJson = {
      number: 256,
      labels: [{ name: "ready-for-agent" }, { name: "enhancement" }],
      body: "body",
      comments: [briefComment],
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
      hasAgentBrief: true,
      hasSubIssues: false,
      openBlockedBy: [254], // only the open one
    });
  });

  it("buildIssueMeta flags a parent issue (sub-issue count > 0)", () => {
    const meta = buildIssueMeta(244, { labels: [] }, [], /*subIssueCount*/ 10);
    expect(meta.hasSubIssues).toBe(true);
  });

  it("buildIssueMeta tolerates missing gh fields (empty case)", () => {
    const meta = buildIssueMeta(99, {}, [], 0);
    expect(meta).toEqual({
      number: 99,
      isReadyForAgent: false,
      hasAgentBrief: false,
      hasSubIssues: false,
      openBlockedBy: [],
    });
  });

  it("extractAgentBrief returns the LAST brief-carrying comment (re-issue wins)", () => {
    const json: GhIssueJson = {
      body: "## Agent Brief\nOLD body brief",
      comments: [
        { body: "## Agent Brief\nfirst brief" },
        { body: "unrelated chatter" },
        { body: "## Agent Brief\nSECOND brief — authoritative" },
      ],
    };
    // Comments are scanned before the body fallback; the last brief comment wins.
    expect(extractAgentBrief(json)).toContain("SECOND brief");
  });

  it("extractAgentBrief falls back to the body when no comment carries it", () => {
    expect(extractAgentBrief({ body: "## Agent Brief\nbody brief" })).toContain(
      "body brief",
    );
    expect(extractAgentBrief({ body: "no brief", comments: [] })).toBe("");
  });

  it("buildIssueSnapshot carries body + comments + brief", () => {
    const snap = buildIssueSnapshot(
      256,
      {
        number: 256,
        body: "the body",
        comments: [{ body: "c1" }, briefComment],
      },
      [],
      0,
    );
    expect(snap.number).toBe(256);
    expect(snap.body).toBe("the body");
    expect(snap.comments).toEqual(["c1", briefComment.body]);
    expect(snap.agentBrief).toContain("## Agent Brief");
  });

  it("buildIssueSnapshot embeds the #244-named native metadata (title/state/labels + sub-issue + blocked_by summaries)", () => {
    // #244 S1: the full snapshot is "body + comments + 最新 Agent Brief 正文 +
    // native metadata". The native metadata S0 reads via gh must travel into the
    // clean-room snapshot, or the container's LOCAL context is missing a
    // contract-named element (it does NOT gh-fetch inside the box).
    const json: GhIssueJson = {
      number: 256,
      title: "Slice: real Backend",
      state: "open",
      body: "the body",
      labels: [{ name: "ready-for-agent" }, { name: "enhancement" }],
      comments: [briefComment],
    };
    const blockedBy: GhBlockedBy[] = [
      { number: 248, state: "closed" },
      { number: 254, state: "open" },
    ];
    const snap = buildIssueSnapshot(256, json, blockedBy, /*subIssueCount*/ 3);
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
    const snap = buildIssueSnapshot(99, {}, [], 0);
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

// ─── fix-loop findings file (integ-cmr 256 r3, fix_loop_context) ─────────────

describe("realBackend serializeFixFindings (fix_loop_context, r3)", () => {
  const f = {
    severity: "critical" as const,
    category: "correctness",
    claim_quote: "the loop never converges",
    location: "src/foo.ts:10",
    suggested_fix: "add a guard",
    action: "fix_now" as const,
  };

  it("emits a self-describing { fix_now: [...] } object the coder reads", () => {
    const json = JSON.parse(serializeFixFindings([f]));
    expect(json).toEqual({ fix_now: [f] });
  });

  it("serialises an empty list as an empty fix_now array (never undefined)", () => {
    expect(JSON.parse(serializeFixFindings([]))).toEqual({ fix_now: [] });
  });

  it("the findings filename is the dot-prefixed clean-room artifact", () => {
    expect(FIX_FINDINGS_FILENAME).toBe(".orchestrator-fix-findings.json");
  });

  it("is git-ignorable alongside the snapshot (distinct clean-room file)", () => {
    expect(FIX_FINDINGS_FILENAME).not.toBe(SNAPSHOT_FILENAME);
  });
});

// ─── auth-mount path construction (spike contract) ───────────────────────────

describe("realBackend auth mount paths", () => {
  it("builds per-issue codex auth + claude token paths under $HOME", () => {
    const p = buildAuthPaths(256, "/home/dev");
    expect(p.hostCodexAuthDir).toBe("/home/dev/.sc-orchestrator/auth-256");
    expect(p.srcCodexAuth).toBe("/home/dev/.codex/auth.json");
    expect(p.srcCodexConfig).toBe("/home/dev/.codex/config.toml");
    expect(p.claudeTokenFile).toBe("/home/dev/.sc-claude-token");
  });

  it("the sandbox mount targets match the spike contract", () => {
    // codex auth → /home/agent/.codex ; dev skills → /home/agent/.claude/skills
    expect(SANDBOX_CODEX_DIR).toBe("/home/agent/.codex");
    expect(SANDBOX_SKILLS_DIR).toBe("/home/agent/.claude/skills");
  });

  it("per-issue dirs are distinct so concurrent issues never collide", () => {
    expect(buildAuthPaths(256, "/h").hostCodexAuthDir).not.toBe(
      buildAuthPaths(257, "/h").hostCodexAuthDir,
    );
  });
});

// ─── model slug → CLI (role decides soul/model) ──────────────────────────────

describe("realBackend modelIdForSlug", () => {
  it("maps sonnet→coder CLI, opus→reviewer CLI", () => {
    expect(modelIdForSlug("sonnet")).toBe("claude-sonnet-4-6");
    expect(modelIdForSlug("opus")).toBe("claude-opus-4-8");
  });
  it("throws on an unknown slug (misconfigured StepSpec)", () => {
    expect(() => modelIdForSlug("gpt")).toThrow(/unknown model slug/);
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

describe("realBackend realCommitCount (#256 commit-truth)", () => {
  it("reads the real commit count from result.commits.length", () => {
    expect(
      realCommitCount({ commits: [{ sha: "a1" }, { sha: "b2" }] }),
    ).toBe(2);
  });
  it("returns 0 when the agent made no commits", () => {
    expect(realCommitCount({ commits: [] })).toBe(0);
  });
});

// ─── assertCompletionSignal (ship-pre 256 r1, completionSignal gate) ──────────

describe("realBackend assertCompletionSignal", () => {
  it("passes when the fired signal matches the spec's completionSignal", () => {
    expect(() =>
      assertCompletionSignal(
        { completionSignal: "CODER_STEP_COMPLETE" },
        "CODER_STEP_COMPLETE",
        "S2-coder",
      ),
    ).not.toThrow();
  });

  it("throws when no signal fired before the iteration limit (undefined)", () => {
    // RunResult.completionSignal is "undefined if no signal fired before the
    // iteration limit" (sandcastle d.ts). An agent that emitted a complete,
    // schema-valid tag but hit maxIter mid-work without firing the signal must
    // NOT advance the step (#244 "agent emit completionSignal 才进下一步").
    expect(() =>
      assertCompletionSignal(
        { completionSignal: undefined },
        "CODER_STEP_COMPLETE",
        "S2-coder",
      ),
    ).toThrow(/completion signal/i);
  });

  it("throws and names the expected + actual signal on a mismatch", () => {
    expect(() =>
      assertCompletionSignal(
        { completionSignal: "REVIEWER_STEP_COMPLETE" },
        "CODER_STEP_COMPLETE",
        "S2-coder",
      ),
    ).toThrow(/CODER_STEP_COMPLETE/);
  });

  it("names the step in the thrown error (runner attributes the failure)", () => {
    expect(() =>
      assertCompletionSignal({ completionSignal: undefined }, "X", "S5-coder"),
    ).toThrow(/S5-coder/);
  });
});

// ─── branchHEAD consistency (codex#2) ────────────────────────────────────────

describe("realBackend checkBranchHeadConsistency (codex#2)", () => {
  const sha = "a".repeat(40);
  const other = "b".repeat(40);

  it("ok when the recorded SHA matches the live HEAD", () => {
    expect(checkBranchHeadConsistency(sha, sha)).toEqual({ ok: true });
  });

  it("mismatch when the recorded SHA diverges from the live HEAD", () => {
    expect(checkBranchHeadConsistency(sha, other)).toEqual({
      ok: false,
      ledgerHead: sha,
      liveHead: other,
    });
  });

  it("ok (no contradiction) when there is no recorded SHA", () => {
    expect(checkBranchHeadConsistency(undefined, sha)).toEqual({ ok: true });
    expect(checkBranchHeadConsistency("", sha)).toEqual({ ok: true });
  });

  it("ok when the ledger value is a v0.1 branch-name fallback (not a SHA)", () => {
    // A pre-#256 ledger recorded the branch NAME, not a SHA — never a mismatch.
    expect(
      checkBranchHeadConsistency("feat/244-orchestrator-issue-256", sha),
    ).toEqual({ ok: true });
  });

  it("ok when the live HEAD is unavailable", () => {
    expect(checkBranchHeadConsistency(sha, undefined)).toEqual({ ok: true });
  });

  it("isLikelySha accepts 7–40 lower-hex, rejects branch names / upper / short", () => {
    expect(isLikelySha("abc1234")).toBe(true);
    expect(isLikelySha("a".repeat(40))).toBe(true);
    expect(isLikelySha("feat/x")).toBe(false);
    expect(isLikelySha("ABC1234")).toBe(false);
    expect(isLikelySha("abc12")).toBe(false); // too short
  });
});

// ─── resume HEAD reconciliation: mismatch → bail (integ-cmr 256 r1, F5) ───────

describe("realBackend resume HEAD reconciliation (codex#2 wiring, F5)", () => {
  const sha = "a".repeat(40);
  const other = "b".repeat(40);

  it("lastLedgerBranchHead picks the latest recorded SHA, skipping name fallbacks", () => {
    // Earliest entries used the v0.1 branch-NAME fallback; the latest agent step
    // recorded a real SHA — that is the base the resume must reconcile against.
    expect(
      lastLedgerBranchHead([
        { branchHEAD: "feat/244-orchestrator-issue-256" }, // v0.1 name
        { branchHEAD: sha }, // real SHA (latest)
      ]),
    ).toBe(sha);
  });

  it("lastLedgerBranchHead returns the last REAL SHA when a later branch-name fallback follows it (r2 F1)", () => {
    // The dangerous interleave: an agent step recorded a real SHA, then a LATER
    // step's resolveBranchHEAD hit a transient worktreeHead() fault and recorded
    // the branch NAME fallback. Returning the latest non-empty value would yield
    // the NAME — checkBranchHeadConsistency then sees a non-SHA and returns
    // {ok:true}, SKIPPING a real divergence. Scanning backward for the first
    // value that is a SHA reconciles against the last REAL recorded base instead.
    expect(
      lastLedgerBranchHead([
        { branchHEAD: sha }, // real SHA (earlier)
        { branchHEAD: "feat/244-orchestrator-issue-256" }, // later NAME fallback
      ]),
    ).toBe(sha);
  });

  it("lastLedgerBranchHead skips multiple trailing name fallbacks back to the real SHA (r2 F1)", () => {
    expect(
      lastLedgerBranchHead([
        { branchHEAD: other }, // older SHA
        { branchHEAD: sha }, // latest real SHA — the one to reconcile against
        { branchHEAD: "feat/244-orchestrator-issue-256" }, // name fallback
        { branchHEAD: "feat/244-orchestrator-issue-256" }, // name fallback
      ]),
    ).toBe(sha);
  });

  it("lastLedgerBranchHead returns undefined when only name fallbacks were recorded (r2 F1)", () => {
    // No real SHA anywhere ⇒ nothing for the consistency check to contradict.
    expect(
      lastLedgerBranchHead([
        { branchHEAD: "feat/244-orchestrator-issue-256" },
        { branchHEAD: "feat/244-orchestrator-issue-256" },
      ]),
    ).toBeUndefined();
  });

  it("returns undefined when no entry recorded a value (fresh / pre-SHA ledger)", () => {
    expect(lastLedgerBranchHead([{}, {}])).toBeUndefined();
    expect(lastLedgerBranchHead([])).toBeUndefined();
  });

  it("mismatch → bail: a moved branch (live HEAD ≠ last ledger SHA) is a hard error", () => {
    // The reconciliation findResumeState runs: read the last recorded SHA, read
    // the live worktree HEAD, compare. A divergence (stray commit / wrong-
    // worktree reuse / corrupted ledger) must NOT be resumed — it bails to a
    // clean error (S8(error) at the runner). This asserts the decision the wiring
    // feeds to `throw`.
    const ledgerHead = lastLedgerBranchHead([{ branchHEAD: sha }]);
    const verdict = checkBranchHeadConsistency(ledgerHead, /*liveHead*/ other);
    expect(verdict).toEqual({ ok: false, ledgerHead: sha, liveHead: other });
  });

  it("agreement → resume proceeds (live HEAD == last ledger SHA)", () => {
    const ledgerHead = lastLedgerBranchHead([{ branchHEAD: sha }]);
    expect(checkBranchHeadConsistency(ledgerHead, sha)).toEqual({ ok: true });
  });
});

// ─── StructuredOutputError dead-session classification (#256) ─────────────────

describe("realBackend classifyResumeError", () => {
  it("retry-structured when a StructuredOutputError carries a sessionId", () => {
    const err = new StructuredOutputError("bad output", {
      tag: "review",
      rawMatched: undefined,
      commits: [],
      branch: "feat/x",
      sessionId: "sess-123",
    });
    expect(classifyResumeError(err)).toEqual({
      kind: "retry-structured",
      sessionId: "sess-123",
    });
  });

  it("fresh-run when a StructuredOutputError has no sessionId", () => {
    const err = new StructuredOutputError("bad output", {
      tag: "review",
      rawMatched: undefined,
      commits: [],
      branch: "feat/x",
    });
    expect(classifyResumeError(err)).toEqual({ kind: "fresh-run" });
  });

  it("fresh-run for a generic dead-session / transport error", () => {
    expect(classifyResumeError(new Error("session not found"))).toEqual({
      kind: "fresh-run",
    });
    expect(classifyResumeError("string error")).toEqual({ kind: "fresh-run" });
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

  it("REFERENCED_PROMPT_FILES lists exactly the four S2/S3/S5/S6 prompts", () => {
    expect([...REFERENCED_PROMPT_FILES]).toEqual([
      "coder_implement.md",
      "reviewer_full_review.md",
      "coder_fix.md",
      "reviewer_rereview.md",
    ]);
  });
});

describe("RealBackend construction validates promptsDir (F4)", () => {
  // The checked-in prompts/ dir lives next to src/ — resolve it from this test
  // file's location so the assertion is path-independent.
  const here = dirname(fileURLToPath(import.meta.url));
  const realPromptsDir = join(here, "..", "prompts");

  const baseOpts = {
    mainRepo: "/tmp/main",
    repo: "owner/name",
    imageName: "img",
    skillsMount: "/tmp/skills",
  };

  it("constructs successfully against the checked-in absolute prompts/ dir", () => {
    expect(
      () => new RealBackend({ ...baseOpts, promptsDir: realPromptsDir }),
    ).not.toThrow();
  });

  it("throws on a relative promptsDir", () => {
    expect(
      () => new RealBackend({ ...baseOpts, promptsDir: "prompts" }),
    ).toThrow(/must be an ABSOLUTE path/);
  });

  it("throws on an absolute promptsDir that does not exist", () => {
    expect(
      () =>
        new RealBackend({
          ...baseOpts,
          promptsDir: "/definitely/not/a/real/dir/xyz",
        }),
    ).toThrow(/does not exist/);
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

  it("returns an escalate payload when the coder tag carries one", () => {
    const stdout =
      '<coder>{"committed": false, "commitsAdded": 0, "escalate": {"reason": "blocked", "diagnosis": "design gap"}}</coder>';
    expect(extractCoderTag(stdout)).toEqual({
      committed: false,
      commitsAdded: 0,
      escalate: { reason: "blocked", diagnosis: "design gap" },
    });
  });

  it("throws a clear error when no <coder> tag is present", () => {
    expect(() => extractCoderTag("no tag here\nCODER_STEP_COMPLETE")).toThrow(
      /<coder>/,
    );
  });

  it("throws when the tag body is not valid JSON", () => {
    expect(() => extractCoderTag("<coder>not json</coder>")).toThrow();
  });
});

// ─── reconcileCoderCommits (#256 commit-truth) ───────────────────────────────

describe("realBackend reconcileCoderCommits", () => {
  it("derives committed+commitsAdded from the real git commit count, not the self-report", () => {
    // git truth: 2 real commits. The derived output reflects git, even though the
    // function is also handed the (here matching) self-report.
    const out = reconcileCoderCommits({ committed: true, commitsAdded: 2 }, 2);
    expect(out).toEqual({ committed: true, commitsAdded: 2 });
  });

  it("derives committed:false / commitsAdded:0 when git shows zero commits", () => {
    const out = reconcileCoderCommits({ committed: false, commitsAdded: 0 }, 0);
    expect(out).toEqual({ committed: false, commitsAdded: 0 });
  });

  it("preserves a self-reported escalate (a model signal, not git-derivable)", () => {
    const out = reconcileCoderCommits(
      {
        committed: false,
        commitsAdded: 0,
        escalate: { reason: "blocked", diagnosis: "design gap" },
      },
      0,
    );
    expect(out).toEqual({
      committed: false,
      commitsAdded: 0,
      escalate: { reason: "blocked", diagnosis: "design gap" },
    });
  });

  it("throws when the coder self-reports committed:true,commitsAdded:1 but git made ZERO commits", () => {
    // The exact truthification bug #256 targets: a coder claims a commit it never
    // made. Without git-derivation this routed to S2/S5 success, bypassing the
    // #252 0-commit edge. Now it is a loud contradiction → S8(error) at the runner.
    expect(() =>
      reconcileCoderCommits({ committed: true, commitsAdded: 1 }, 0),
    ).toThrow(/self-report/i);
  });

  it("throws when the self-reported commitsAdded count disagrees with git", () => {
    // Self-report says 3 commits; git made 1. A miscount is a contract violation.
    expect(() =>
      reconcileCoderCommits({ committed: true, commitsAdded: 3 }, 1),
    ).toThrow(/git/i);
  });

  it("throws when the coder self-reports committed:false but git DID make commits", () => {
    expect(() =>
      reconcileCoderCommits({ committed: false, commitsAdded: 0 }, 1),
    ).toThrow(/self-report/i);
  });

  it("escalate does not suppress a commit-count contradiction", () => {
    // An escalate is orthogonal to commit truth: a self-report that escalates yet
    // miscounts its commits is still a contradiction.
    expect(() =>
      reconcileCoderCommits(
        {
          committed: true,
          commitsAdded: 2,
          escalate: { reason: "blocked", diagnosis: "design gap" },
        },
        0,
      ),
    ).toThrow(/self-report/i);
  });
});

// ─── S0 input gate: author-trust filter (issue #283) ──────────────────────────

describe("realBackend hasAgentBrief + extractAgentBrief — ownerLogin author filter (#283)", () => {
  const OWNER = "akagilnc";
  const OTHER = "stranger";

  // Issue authored by OWNER with a body brief
  const ownerBodyJson: GhIssueJson = {
    user: { login: OWNER },
    body: "## Agent Brief\ndo the thing",
    comments: [],
  };

  // Issue authored by OTHER, but OWNER left a comment brief
  const ownerCommentJson: GhIssueJson = {
    user: { login: OTHER },
    body: "regular issue body",
    comments: [
      { body: "some chatter", user: { login: OTHER } },
      { body: "## Agent Brief\nowner comment brief", user: { login: OWNER } },
    ],
  };

  // Issue authored by OTHER with a body brief (injection attempt)
  const nonOwnerBodyJson: GhIssueJson = {
    user: { login: OTHER },
    body: "## Agent Brief\ninjection attempt in body",
    comments: [],
  };

  // Issue authored by OWNER, but OTHER's comment has a brief (injection attempt)
  const nonOwnerCommentJson: GhIssueJson = {
    user: { login: OWNER },
    body: "regular owner body",
    comments: [
      { body: "## Agent Brief\ninjection in comment", user: { login: OTHER } },
    ],
  };

  // No brief at all
  const noBriefJson: GhIssueJson = {
    user: { login: OWNER },
    body: "just a regular body",
    comments: [],
  };

  describe("hasAgentBrief with ownerLogin", () => {
    it("accepts a brief in the owner-authored issue body", () => {
      expect(hasAgentBrief(ownerBodyJson, OWNER)).toBe(true);
    });

    it("accepts a brief in an owner comment even when the issue is by a non-owner", () => {
      expect(hasAgentBrief(ownerCommentJson, OWNER)).toBe(true);
    });

    it("rejects a brief in a non-owner's issue body (injection blocked)", () => {
      expect(hasAgentBrief(nonOwnerBodyJson, OWNER)).toBe(false);
    });

    it("rejects a brief in a non-owner comment (injection blocked)", () => {
      expect(hasAgentBrief(nonOwnerCommentJson, OWNER)).toBe(false);
    });

    it("rejects when there is no brief at all (original reject behavior unchanged)", () => {
      expect(hasAgentBrief(noBriefJson, OWNER)).toBe(false);
    });
  });

  describe("extractAgentBrief with ownerLogin", () => {
    it("returns the owner body brief when no owner comment overrides it", () => {
      expect(extractAgentBrief(ownerBodyJson, OWNER)).toContain("## Agent Brief");
      expect(extractAgentBrief(ownerBodyJson, OWNER)).toContain("do the thing");
    });

    it("returns the owner comment brief (last-wins over body)", () => {
      expect(extractAgentBrief(ownerCommentJson, OWNER)).toContain("owner comment brief");
    });

    it("returns empty when the body brief is non-owner-authored (injection blocked)", () => {
      expect(extractAgentBrief(nonOwnerBodyJson, OWNER)).toBe("");
    });

    it("returns empty when the only brief is in a non-owner comment (injection blocked)", () => {
      expect(extractAgentBrief(nonOwnerCommentJson, OWNER)).toBe("");
    });
  });

  describe("buildIssueMeta with ownerLogin", () => {
    it("sets hasAgentBrief:true when owner authored the body brief", () => {
      const meta = buildIssueMeta(283, ownerBodyJson, [], 0, OWNER);
      expect(meta.hasAgentBrief).toBe(true);
    });

    it("sets hasAgentBrief:true when owner wrote a comment brief", () => {
      const meta = buildIssueMeta(283, ownerCommentJson, [], 0, OWNER);
      expect(meta.hasAgentBrief).toBe(true);
    });

    it("sets hasAgentBrief:false when the only brief is by a non-owner (gates injection)", () => {
      const meta = buildIssueMeta(283, nonOwnerBodyJson, [], 0, OWNER);
      expect(meta.hasAgentBrief).toBe(false);
    });

    it("sets hasAgentBrief:false when the only brief comment is by a non-owner", () => {
      const meta = buildIssueMeta(283, nonOwnerCommentJson, [], 0, OWNER);
      expect(meta.hasAgentBrief).toBe(false);
    });
  });

  describe("buildIssueSnapshot with ownerLogin", () => {
    it("agentBrief is populated from the owner-authored body", () => {
      const snap = buildIssueSnapshot(283, ownerBodyJson, [], 0, OWNER);
      expect(snap.agentBrief).toContain("do the thing");
    });

    it("agentBrief is empty when the only brief is by a non-owner", () => {
      const snap = buildIssueSnapshot(283, nonOwnerBodyJson, [], 0, OWNER);
      expect(snap.agentBrief).toBe("");
    });
  });
});
