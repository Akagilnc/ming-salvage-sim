/**
 * #292 — prune is handed back to Sandcastle (ADR 0024 decision 2).
 *
 * cleanResidueAt KEEPS the per-worktree residue clean (`reset --hard HEAD` +
 * `clean -fd`) but MUST NOT run the repo-level `git worktree prune` — that was
 * both a duplicate of Sandcastle's own pruneStale AND the dangerous cross-session
 * reaper the dedicated clone (decision 1) makes unnecessary. With an independent
 * clone, a prune is Sandcastle's job and can't reach across sessions anyway.
 *
 * Drives the REAL RealBackend via the same `sh`/clone seam subclass as the build
 * test (zero git / Docker), exercising the reuse path of prepareWorktree which
 * calls cleanResidueAt.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  clonePathFor,
  RealBackend,
  type RealBackendOptions,
  repoSlug,
} from "../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "prompts");

const SOURCE = "/Users/me/WorkSpace/Ming_LLM";
const REMOTE = "https://github.com/Akagilnc/ming-salvage-sim.git";
const HOME = "/tmp/home";
const ISSUE = 256;
const BRANCH = `feat/issue-${ISSUE}`; // #1: neutral prefix (matches branchForIssue)

const CLONE = clonePathFor(HOME, repoSlug(SOURCE, REMOTE), 291);
const EXISTING_WT = `${CLONE}/.sandcastle/worktrees/issue-256`;

/**
 * Reports the clone as built (so construction's guard passes), reports the
 * resident worktree as already present (so prepareWorktree takes the REUSE →
 * cleanResidueAt branch), and records every git call.
 */
class RecordingBackend extends RealBackend {
  static gitCalls: Array<{ file: string; args: string[]; cwd?: string }> = [];

  get gitCalls(): Array<{ file: string; args: string[]; cwd?: string }> {
    return RecordingBackend.gitCalls;
  }

  protected override cloneDirExists(): boolean {
    return true;
  }

  protected override sh(file: string, args: string[], cwd?: string): string {
    RecordingBackend.gitCalls.push({ file, args, cwd });
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      return `${CLONE}/.git`; // own .git ⇒ guard passes
    }
    if (
      file === "git" &&
      args[0] === "worktree" &&
      args[1] === "list" &&
      args[2] === "--porcelain"
    ) {
      return [
        `worktree ${EXISTING_WT}`,
        "HEAD " + "a".repeat(40),
        `branch refs/heads/${BRANCH}`,
      ].join("\n");
    }
    return "";
  }
}

function newBackend(override?: Partial<RealBackendOptions>): RecordingBackend {
  RecordingBackend.gitCalls = [];
  return new RecordingBackend({
    sourceRepo: SOURCE,
    remote: REMOTE,
    runKey: 291,
    repo: "Akagilnc/ming-salvage-sim",
    imageName: "img",
    skillsMount: "/tmp/skills",
    promptsDir: realPromptsDir,
    home: HOME,
    ...override,
  });
}

describe("#292 cleanResidueAt — prune is gone, in-worktree clean stays", () => {
  it("on reuse, runs reset --hard + clean -fd but NOT worktree prune", async () => {
    const b = newBackend();
    RecordingBackend.gitCalls = []; // ignore construction-time git
    await b.prepareWorktree(ISSUE, "main");

    const ran = b.gitCalls.map((c) => c.args.join(" "));
    expect(ran).toContain("reset --hard HEAD");
    expect(ran).toContain("clean -fd");
    expect(ran.some((r) => r.includes("worktree prune"))).toBe(false);
  });

  it("the kept reset/clean run IN the reused worktree (not the clone root)", async () => {
    const b = newBackend();
    RecordingBackend.gitCalls = [];
    await b.prepareWorktree(ISSUE, "main");

    const reset = b.gitCalls.find((c) => c.args.join(" ") === "reset --hard HEAD");
    const clean = b.gitCalls.find((c) => c.args.join(" ") === "clean -fd");
    expect(reset?.cwd).toBe(EXISTING_WT);
    expect(clean?.cwd).toBe(EXISTING_WT);
  });

  it("the public cleanResidue() path also runs no prune", async () => {
    const b = newBackend();
    RecordingBackend.gitCalls = [];
    await b.cleanResidue({ branch: BRANCH, base: "main", path: EXISTING_WT });

    const ran = b.gitCalls.map((c) => c.args.join(" "));
    expect(ran).toContain("reset --hard HEAD");
    expect(ran).toContain("clean -fd");
    expect(ran.some((r) => r.includes("worktree prune"))).toBe(false);
  });
});
