/**
 * #292 — the resident slice worktree is never disposed by prepareWorktree
 * (ADR 0024 decision 2, second half).
 *
 * Sandcastle's `Worktree.close()` / `[Symbol.asyncDispose]` REMOVE a clean
 * worktree. But ADR 0017 makes the resident worktree the commit source + crash-
 * resume source, so it must outlive any single run — only an explicit terminal-
 * success GC may delete it, NOT a `.close()` / `await using` in the normal path.
 *
 * This pins the invariant on the FRESH-cut path: override the
 * `createResidentWorktree` seam to hand back a handle whose `close` / dispose are
 * spies, drive prepareWorktree, and assert neither was called. Zero container.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";
import type * as sc from "@ai-hero/sandcastle";
import {
  clonePathFor,
  RealBackend,
  type RealBackendOptions,
  repoSlug,
} from "../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "prompts");

const SOURCE = "/tmp/source";
const REMOTE = "https://github.com/owner/name.git";
const HOME = "/tmp/home";
const ISSUE = 292;
const CLONE = clonePathFor(HOME, repoSlug(SOURCE, REMOTE), ISSUE);

const close = vi.fn(async () => ({}));
const dispose = vi.fn(async () => {});

/**
 * Stubs the clone seams (construction never touches git) AND the
 * createResidentWorktree seam — returning a fake Worktree handle whose disposal
 * hooks are spies, so the test can prove prepareWorktree never disposes it.
 */
class StubCloneBackend extends RealBackend {
  protected override cloneDirExists(): boolean {
    return true;
  }
  protected override sh(file: string, args: string[]): string {
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      return `${CLONE}/.git`;
    }
    // worktree list → empty (no existing resident wt ⇒ FRESH cut path).
    return "";
  }
  protected override async createResidentWorktree(
    branch: string,
  ): Promise<sc.Worktree> {
    const handle = {
      branch,
      worktreePath: `${CLONE}/.sandcastle/worktrees/issue-${ISSUE}`,
      run: vi.fn(),
      interactive: vi.fn(),
      createSandbox: vi.fn(),
      close,
      [Symbol.asyncDispose]: dispose,
    };
    return handle as unknown as sc.Worktree;
  }
}

function newBackend(override?: Partial<RealBackendOptions>): StubCloneBackend {
  return new StubCloneBackend({
    sourceRepo: SOURCE,
    remote: REMOTE,
    runKey: ISSUE,
    repo: "owner/name",
    imageName: "img",
    skillsMount: "/tmp/skills",
    promptsDir: realPromptsDir,
    home: HOME,
    ...override,
  });
}

describe("#292 resident worktree is NOT disposed by prepareWorktree (ADR 0024 dec. 2)", () => {
  it("does not call the Worktree handle's close() / asyncDispose on the fresh cut", async () => {
    close.mockClear();
    dispose.mockClear();
    const backend = newBackend();
    const wt = await backend.prepareWorktree(ISSUE, "main");

    // The fresh-cut path kept the worktree's path.
    expect(wt.path).toBe(`${CLONE}/.sandcastle/worktrees/issue-${ISSUE}`);
    // The resident worktree must survive — neither disposal hook may fire.
    expect(close).not.toHaveBeenCalled();
    expect(dispose).not.toHaveBeenCalled();
  });
});
