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

import { describe, expect, it } from "vitest";
import {
  attributeFailure,
  buildAuthPaths,
  buildIssueMeta,
  buildIssueSnapshot,
  checkBranchHeadConsistency,
  classifyResumeError,
  extractAgentBrief,
  hasAgentBrief,
  isLikelySha,
  isReadyForAgent,
  lastSessionId,
  modelIdForSlug,
  SANDBOX_CODEX_DIR,
  SANDBOX_SKILLS_DIR,
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
    const snap = buildIssueSnapshot(256, {
      number: 256,
      body: "the body",
      comments: [{ body: "c1" }, briefComment],
    });
    expect(snap.number).toBe(256);
    expect(snap.body).toBe("the body");
    expect(snap.comments).toEqual(["c1", briefComment.body]);
    expect(snap.agentBrief).toContain("## Agent Brief");
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
});
