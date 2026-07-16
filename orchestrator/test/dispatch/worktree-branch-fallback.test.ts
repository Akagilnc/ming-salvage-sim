/**
 * #593 — resume/worktree lookup falls back to the old branch-name convention
 * (`feat/244-orchestrator-issue-<n>`) when the current `feat/issue-<n>` name
 * misses. Worktrees found under the old name are resumed IN PLACE — no rename,
 * no migration. Drives the REAL RealBackend via the `sh` / `createResidentWorktree`
 * seams (zero real git / Docker), plus the pure porcelain resolver.
 */

import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import type * as sc from "@ai-hero/sandcastle";
import {
  candidateBranches,
  clonePathFor,
  RealBackend,
  resolveExistingWorktreeFromPorcelain,
  repoSlug,
  scanPorcelainForIssueWorktree,
} from "../../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "image", "souls");

const cleanups: string[] = [];
afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  cleanups.push(d);
  return d;
}

const ISSUE = 593;
const NEW_BRANCH = `feat/issue-${ISSUE}`;
const OLD_BRANCH = `feat/244-orchestrator-issue-${ISSUE}`;
const SOURCE = "/tmp/source-593";
const REMOTE = "https://github.com/Akagilnc/ming-salvage-sim.git";
const HOME = "/tmp/home-593";
const CLONE = clonePathFor(HOME, repoSlug(SOURCE, REMOTE), ISSUE);
const EXISTING_WT = `${CLONE}/.sandcastle/worktrees/issue-593`;
const HEAD_SHA = "a".repeat(40);
const ADVANCED_HEAD_SHA = "b".repeat(40);
const LEDGER_HEAD_SHA = "c".repeat(40);

function porcelainForBranch(branch: string, path = EXISTING_WT): string {
  return [`worktree ${path}`, `HEAD ${HEAD_SHA}`, `branch refs/heads/${branch}`].join("\n");
}

/** Records git calls and stubs worktree-list / clone guard for #593 seam tests. */
class RecordingBackend extends RealBackend {
  private _gitCalls?: Array<{ file: string; args: string[]; cwd?: string }>;
  get gitCalls(): Array<{ file: string; args: string[]; cwd?: string }> {
    return (this._gitCalls ??= []);
  }
  createWorktreeCalls = 0;
  porcelain = porcelainForBranch(NEW_BRANCH);
  liveHeadSha = HEAD_SHA;

  protected override cloneDirExists(): boolean {
    return true;
  }

  protected override sh(file: string, args: string[], cwd?: string): string {
    this.gitCalls.push({ file, args, cwd });
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      return `${CLONE}/.git`;
    }
    if (
      file === "git" &&
      args[0] === "worktree" &&
      args[1] === "list" &&
      args[2] === "--porcelain"
    ) {
      return this.porcelain;
    }
    if (file === "git" && args[0] === "rev-parse" && args[1] === "HEAD") {
      return this.liveHeadSha;
    }
    return "";
  }

  protected override async createResidentWorktree(
    branch: string,
    _baseBranch: string,
  ): Promise<sc.Worktree> {
    this.createWorktreeCalls += 1;
    return { worktreePath: `${CLONE}/.sandcastle/worktrees/fresh-${branch}` } as sc.Worktree;
  }
}

function newBackend(porcelain = porcelainForBranch(NEW_BRANCH)): RecordingBackend {
  const b = new RecordingBackend({
    sourceRepo: SOURCE,
    remote: REMOTE,
    runKey: ISSUE,
    repo: "Akagilnc/ming-salvage-sim",
    imageName: "img",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    home: HOME,
  });
  b.porcelain = porcelain;
  b.gitCalls.length = 0;
  return b;
}

// ─── pure porcelain resolver (#593) ─────────────────────────────────────────

describe("resolveExistingWorktreeFromPorcelain (#593)", () => {
  it("matches the current convention on the first candidate (one lookup attempt)", () => {
    const porcelain = porcelainForBranch(NEW_BRANCH);
    const scan = scanPorcelainForIssueWorktree(porcelain, ISSUE);

    expect(scan.worktree).toEqual({ path: EXISTING_WT, branch: NEW_BRANCH });
    expect(scan.matchAttempts).toBe(1);
    expect(resolveExistingWorktreeFromPorcelain(porcelain, ISSUE)).toEqual(scan.worktree);
  });

  it("falls back to the old convention when the current name is absent", () => {
    const porcelain = porcelainForBranch(OLD_BRANCH);
    const scan = scanPorcelainForIssueWorktree(porcelain, ISSUE);

    expect(scan.worktree).toEqual({ path: EXISTING_WT, branch: OLD_BRANCH });
    expect(scan.matchAttempts).toBe(2);
    expect(resolveExistingWorktreeFromPorcelain(porcelain, ISSUE)).toEqual(scan.worktree);
  });

  it("prefers the current convention when both names appear in porcelain", () => {
    const porcelain = [
      porcelainForBranch(OLD_BRANCH, `${EXISTING_WT}-old`),
      "",
      porcelainForBranch(NEW_BRANCH, `${EXISTING_WT}-new`),
    ].join("\n");
    expect(resolveExistingWorktreeFromPorcelain(porcelain, ISSUE)).toEqual({
      path: `${EXISTING_WT}-new`,
      branch: NEW_BRANCH,
    });
  });

  it("returns undefined when neither naming convention matches", () => {
    expect(resolveExistingWorktreeFromPorcelain("", ISSUE)).toBeUndefined();
    expect(
      resolveExistingWorktreeFromPorcelain(
        porcelainForBranch("feat/other-branch"),
        ISSUE,
      ),
    ).toBeUndefined();
  });

  it("parses CRLF porcelain output (line-ending robustness)", () => {
    const porcelain = porcelainForBranch(NEW_BRANCH).replace(/\n/g, "\r\n");
    expect(resolveExistingWorktreeFromPorcelain(porcelain, ISSUE)).toEqual({
      path: EXISTING_WT,
      branch: NEW_BRANCH,
    });
  });

  it("does not match a different issue's branch (exact-match lock-in, e.g. issue-59 vs 593)", () => {
    const porcelain = porcelainForBranch("feat/issue-59", "/tmp/wt-59");
    expect(resolveExistingWorktreeFromPorcelain(porcelain, ISSUE)).toBeUndefined();
    expect(
      resolveExistingWorktreeFromPorcelain(
        porcelainForBranch("feat/244-orchestrator-issue-59", "/tmp/wt-59-old"),
        ISSUE,
      ),
    ).toBeUndefined();
  });
});

// ─── prepareWorktree / findResumeState wiring (#593) ────────────────────────

describe("RealBackend prepareWorktree old-branch fallback (#593)", () => {
  it("reuses a worktree on the old branch name in place without destroying residue", async () => {
    const backend = newBackend(porcelainForBranch(OLD_BRANCH));
    const wt = await backend.prepareWorktree(ISSUE, "main");

    expect(wt.path).toBe(EXISTING_WT);
    expect(wt.branch).toBe(OLD_BRANCH);
    expect(backend.createWorktreeCalls).toBe(0);

    const ran = backend.gitCalls.map((c) => c.args.join(" "));
    expect(ran).toContain("worktree list --porcelain");
    expect(ran).not.toContain("reset --hard HEAD");
    expect(ran).not.toContain("clean -fd");
    expect(ran.some((r) => r.includes("branch -m"))).toBe(false);
    expect(ran.some((r) => r.includes("worktree move"))).toBe(false);
    expect(ran.some((r) => r.startsWith("fetch "))).toBe(false);
  });

  it("cuts a fresh feat/issue-<n> branch when neither convention matches", async () => {
    const backend = newBackend("");
    const wt = await backend.prepareWorktree(ISSUE, "main");

    expect(wt.branch).toBe(NEW_BRANCH);
    expect(backend.createWorktreeCalls).toBe(1);
    expect(backend.gitCalls.map((c) => c.args.join(" "))).not.toContain("reset --hard HEAD");
  });

  it("current-convention hit reuses without a fresh cut (unchanged common path)", async () => {
    const backend = newBackend(porcelainForBranch(NEW_BRANCH));
    const wt = await backend.prepareWorktree(ISSUE, "main");

    expect(wt.branch).toBe(NEW_BRANCH);
    expect(wt.path).toBe(EXISTING_WT);
    expect(backend.createWorktreeCalls).toBe(0);
  });
});

describe("RealBackend findResumeState old-branch fallback (#593)", () => {
  function writeLedger(wtPath: string, issueNumber: number, ledgerLine: string): string {
    const parent = dirname(wtPath);
    const stateDir = join(parent, `.ledger-${issueNumber}`);
    mkdirSync(stateDir, { recursive: true });
    writeFileSync(join(stateDir, "steps.jsonl"), ledgerLine, "utf8");
    return stateDir;
  }

  it("finds resume state under the old branch name and preserves ledger on disk", async () => {
    const wtRoot = mkDir("wt-fallback-resume-");
    const existingWt = join(wtRoot, "issue-593");
    mkdirSync(existingWt, { recursive: true });

    const backend = newBackend(porcelainForBranch(OLD_BRANCH, existingWt));
    const ledgerLine = `${JSON.stringify({
      step: "S2",
      branchHEAD: HEAD_SHA,
      output: { kind: "coder", committed: true, commitsAdded: 1 },
    })}\n`;
    const stateDir = writeLedger(existingWt, ISSUE, ledgerLine);
    const before = readFileSync(join(stateDir, "steps.jsonl"), "utf8");

    const resume = await backend.findResumeState(ISSUE);

    expect(resume).toBeDefined();
    expect(resume?.worktree.branch).toBe(OLD_BRANCH);
    expect(resume?.worktree.path).toBe(existingWt);
    expect(resume?.stateDir).toBe(stateDir);
    expect(resume?.ledger).toHaveLength(1);
    expect(readFileSync(join(stateDir, "steps.jsonl"), "utf8")).toBe(before);
    expect(backend.gitCalls.map((c) => c.args.join(" "))).not.toContain("branch -m");
    expect(backend.gitCalls.map((c) => c.args.join(" "))).not.toContain("worktree move");
  });

  it("round-trips #824 mechanical redispatch markers for durable resume accounting", async () => {
    const wtRoot = mkDir("wt-mechanical-marker-resume-");
    const existingWt = join(wtRoot, "issue-593");
    mkdirSync(existingWt, { recursive: true });

    const backend = newBackend(porcelainForBranch(NEW_BRANCH, existingWt));
    const stateDir = writeLedger(
      existingWt,
      ISSUE,
      [
        {
          step: "mechanical_redispatch_attempt",
          event: "mechanical_redispatch_attempt",
          forStep: "S2",
          mechanicalRedispatchAttempt: 2,
          sessionId: "retry-marker-session",
        },
        { step: "S1", branchHEAD: HEAD_SHA },
      ].map((entry) => JSON.stringify(entry)).join("\n") + "\n",
    );

    const resume = await backend.findResumeState(ISSUE);

    expect(resume?.stateDir).toBe(stateDir);
    expect(resume?.ledger).toMatchObject([
      {
        step: "mechanical_redispatch_attempt",
        event: "mechanical_redispatch_attempt",
        forStep: "S2",
        mechanicalRedispatchAttempt: 2,
      },
      { step: "S1" },
    ]);
  });

  it("returns undefined when neither branch convention matches", async () => {
    const backend = newBackend("");
    expect(await backend.findResumeState(ISSUE)).toBeUndefined();
  });

  it("throws when a ledger exists without either resident worktree", async () => {
    const orphan = join(CLONE, ".sandcastle", "worktrees", `.ledger-${ISSUE}`);
    mkdirSync(orphan, { recursive: true });
    cleanups.push(CLONE);
    const backend = newBackend("");
    await expect(backend.findResumeState(ISSUE)).rejects.toThrow(
      /ledger exists without a worksite|partial residue/i,
    );
  });

  it("throws when the old-name worktree has no readable ledger (#936 partial residue)", async () => {
    // ID-005: worksite without ledger is corrupted residue, not fresh.
    const wtRoot = mkDir("wt-fallback-no-ledger-");
    const existingWt = join(wtRoot, "issue-593");
    mkdirSync(existingWt, { recursive: true });

    const backend = newBackend(porcelainForBranch(OLD_BRANCH, existingWt));
    await expect(backend.findResumeState(ISSUE)).rejects.toThrow(
      /without readable ledger|partial residue/i,
    );
  });

  it("corrupt ledger still aborts resume (infra fail-closed)", async () => {
    const wtRoot = mkDir("wt-corrupt-ledger-resume-");
    const existingWt = join(wtRoot, "issue-593");
    mkdirSync(existingWt, { recursive: true });

    const backend = newBackend(porcelainForBranch(NEW_BRANCH, existingWt));
    const stateDir = writeLedger(existingWt, ISSUE, "{not valid json}\n");

    await expect(backend.findResumeState(ISSUE)).rejects.toThrow(/corrupt ledger/i);
    expect(stateDir).toBeDefined();
  });
});

describe("candidateBranches contract (#593)", () => {
  it("lists current then old convention only", () => {
    expect(candidateBranches(ISSUE)).toEqual([NEW_BRANCH, OLD_BRANCH]);
  });
});
