/**
 * integ-cmr 256 r3 — idempotent_reuse_dirty (finding 3, high).
 *
 * When a resident slice worktree already exists but there is NO readable ledger,
 * findResumeState() returns undefined → the runner takes the FRESH path → it
 * calls prepareWorktree → which (before this fix) reused the existing dir AS-IS,
 * never cleaning residue. Crash residue (uncommitted changes / stale commits)
 * was thus reused as a "fresh" start, violating ADR0017 ("复用前清未提交残留:
 * reset --hard + clean -fd + prune").
 *
 * The fix is fail-closed: prepareWorktree's reuse branch must clean residue
 * (reset --hard HEAD → clean -fd → worktree prune) BEFORE returning the reused
 * path, so a no-ledger old branch can never masquerade as a clean fresh cut.
 *
 * This drives the REAL Backend's prepareWorktree with a test subclass that
 * records every git invocation (the `sh` seam) and stubs the worktree-list query
 * to report the resident worktree as already existing — zero real git / Docker.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { RealBackend } from "../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "prompts");

const ISSUE = 256;
const BRANCH = `feat/244-orchestrator-issue-${ISSUE}`;
const EXISTING_PATH = "/resident/worktrees/issue-256";

/**
 * Test subclass that intercepts the `sh` seam: it answers the
 * `git worktree list --porcelain` query with a block reporting the resident
 * worktree as already present (so prepareWorktree takes the REUSE branch), and
 * records every other git command so the test can assert the residue-clean ran.
 */
class RecordingBackend extends RealBackend {
  readonly gitCalls: Array<{ args: string[]; cwd?: string }> = [];

  protected override sh(file: string, args: string[], cwd?: string): string {
    this.gitCalls.push({ args, cwd });
    if (
      file === "git" &&
      args[0] === "worktree" &&
      args[1] === "list" &&
      args[2] === "--porcelain"
    ) {
      // Report the resident worktree as already existing.
      return [
        `worktree ${EXISTING_PATH}`,
        "HEAD " + "a".repeat(40),
        `branch refs/heads/${BRANCH}`,
      ].join("\n");
    }
    // reset / clean / prune (and any other git) → empty success.
    return "";
  }
}

function newBackend(): RecordingBackend {
  return new RecordingBackend({
    mainRepo: "/tmp/main",
    repo: "owner/name",
    imageName: "img",
    skillsMount: "/tmp/skills",
    promptsDir: realPromptsDir,
    home: "/tmp/home",
  });
}

describe("integ-cmr 256 r3 — prepareWorktree reuse is fail-closed (cleans residue)", () => {
  it("reuses the existing worktree path but cleans residue first", async () => {
    const backend = newBackend();
    const wt = await backend.prepareWorktree(ISSUE, "main");

    // The reused path is returned (no re-cut).
    expect(wt.path).toBe(EXISTING_PATH);
    expect(wt.branch).toBe(BRANCH);

    const ran = backend.gitCalls.map((c) => c.args.join(" "));
    // ADR0017 residue-clean ran on reuse: reset --hard + clean -fd + prune.
    expect(ran).toContain("reset --hard HEAD");
    expect(ran).toContain("clean -fd");
    expect(ran).toContain("worktree prune");
  });

  it("the reset/clean run IN the reused worktree, prune in the main repo", async () => {
    const backend = newBackend();
    await backend.prepareWorktree(ISSUE, "main");

    const reset = backend.gitCalls.find(
      (c) => c.args.join(" ") === "reset --hard HEAD",
    );
    const clean = backend.gitCalls.find(
      (c) => c.args.join(" ") === "clean -fd",
    );
    const prune = backend.gitCalls.find(
      (c) => c.args.join(" ") === "worktree prune",
    );
    expect(reset?.cwd).toBe(EXISTING_PATH);
    expect(clean?.cwd).toBe(EXISTING_PATH);
    expect(prune?.cwd).toBe("/tmp/main");
  });

  it("cleans BEFORE returning (no createWorktree / fetch on the reuse path)", async () => {
    const backend = newBackend();
    await backend.prepareWorktree(ISSUE, "main");

    const ran = backend.gitCalls.map((c) => c.args.join(" "));
    // Reuse path must NOT fetch or re-cut — it only lists + cleans.
    expect(ran.some((r) => r.startsWith("fetch "))).toBe(false);
    // The residue-clean must be present (the whole point of fail-closed reuse).
    const resetIdx = ran.indexOf("reset --hard HEAD");
    const listIdx = ran.indexOf("worktree list --porcelain");
    expect(listIdx).toBeGreaterThanOrEqual(0);
    expect(resetIdx).toBeGreaterThan(listIdx);
  });
});
