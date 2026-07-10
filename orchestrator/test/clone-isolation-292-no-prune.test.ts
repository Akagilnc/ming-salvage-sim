/**
 * #292 — prune is handed back to Sandcastle (ADR 0024 decision 2).
 *
 * #661: reuse preserves every scene AS-IS. No reset, clean, or worktree prune
 * may be reachable from preparation or compatibility cleanup seams.
 *
 * Drives the REAL RealBackend via the same `sh`/clone seam subclass as the build
 * test (zero git / Docker), exercising the reuse path of prepareWorktree which
 * calls cleanResidueAt.
 */

import { dirname, join } from "node:path";
import { readFileSync } from "node:fs";
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
const realSoulsDir = join(here, "..", "image", "souls");

const SOURCE = "/Users/me/WorkSpace/Ming_LLM";
const REMOTE = "https://github.com/Akagilnc/ming-salvage-sim.git";
const HOME = "/tmp/home";
const ISSUE = 256;
const BRANCH = `feat/issue-${ISSUE}`; // #1: neutral prefix (matches branchForIssue)

const CLONE = clonePathFor(HOME, repoSlug(SOURCE, REMOTE), 291);
const EXISTING_WT = `${CLONE}/.sandcastle/worktrees/issue-256`;

/**
 * Reports the clone as built (so construction's guard passes), reports the
 * resident worktree as already present and records every git call.
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
    soulsDir: realSoulsDir,
    home: HOME,
    ...override,
  });
}

describe("#661 resident scene preservation", () => {
  it("has no reset/clean helper reachable from prepare, retry, resume, or relay source", () => {
    const backendSource = readFileSync(join(here, "..", "src", "realBackend.ts"), "utf8");
    const runnerSource = readFileSync(join(here, "..", "src", "runner.ts"), "utf8");
    expect(backendSource).not.toMatch(/cleanResidueAt|\["reset",\s*\["--hard"|\["clean",\s*\["-fd"/);
    expect(runnerSource).not.toMatch(/\.cleanResidue\(/);
  });

  it("on reuse, never resets, cleans, or prunes the scene", async () => {
    const b = newBackend();
    RecordingBackend.gitCalls = []; // ignore construction-time git
    await b.prepareWorktree(ISSUE, "main");

    const ran = b.gitCalls.map((c) => c.args.join(" "));
    expect(ran).not.toContain("reset --hard HEAD");
    expect(ran).not.toContain("clean -fd");
    expect(ran.some((r) => r.includes("worktree prune"))).toBe(false);
  });

  it("has no destructive git invocation in the reused worktree", async () => {
    const b = newBackend();
    RecordingBackend.gitCalls = [];
    await b.prepareWorktree(ISSUE, "main");

    expect(b.gitCalls.some((c) => c.cwd === EXISTING_WT && /^(reset --hard|clean -fd)/.test(c.args.join(" ")))).toBe(false);
  });

  it("the compatibility cleanResidue() seam is a no-op", async () => {
    const b = newBackend();
    RecordingBackend.gitCalls = [];
    await b.cleanResidue({ branch: BRANCH, base: "main", path: EXISTING_WT });

    const ran = b.gitCalls.map((c) => c.args.join(" "));
    expect(ran).not.toContain("reset --hard HEAD");
    expect(ran).not.toContain("clean -fd");
    expect(ran.some((r) => r.includes("worktree prune"))).toBe(false);
  });
});
