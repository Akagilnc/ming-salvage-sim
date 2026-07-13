/**
 * #291 — RealBackend.prepareWorktree cuts a family child from the LOCAL family
 * base (ADR 0022 decision 7), NOT `origin/<family-base>`.
 *
 * The family base is a LOCAL branch on the dedicated clone the merger accumulates
 * each wave's merges onto — it has no remote counterpart. So a family child must:
 *   - NOT run `git fetch origin <family-base>` (it would fail or resolve a stale
 *     remote branch), and
 *   - cut from the bare LOCAL ref (`baseBranch: <family-base>`), so it sees the
 *     prior waves the merger landed locally (agy R1).
 *
 * A standalone single-slice run (base="main", no `familyBase` option) is byte-
 * identical to before: it fetches origin/main and cuts from `origin/main`.
 *
 * Drives the REAL prepareWorktree via the `sh` + `createResidentWorktree` seams
 * (no real git clone, no Sandcastle container) — the same intercept pattern the
 * clone-isolation build test uses.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Worktree } from "@ai-hero/sandcastle";
import { describe, expect, it } from "vitest";
import {
  RealBackend,
  type RealBackendOptions,
} from "../../../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

/**
 * Intercepts `sh` (git), `cloneDirExists` (fs), and `createResidentWorktree`
 * (Sandcastle), recording every git invocation + the cut ref the worktree was
 * created from.
 */
class RecordingBackend extends RealBackend {
  // STATIC so constructor-time `sh` (the independent-clone guard) is captured
  // despite subclass field-init-after-super ordering. Reset per `build()`.
  static gitCalls: Array<{ file: string; args: string[] }> = [];
  static cutBaseBranch: string | undefined;

  get gitCalls(): Array<{ file: string; args: string[] }> {
    return RecordingBackend.gitCalls;
  }
  get cutBaseBranch(): string | undefined {
    return RecordingBackend.cutBaseBranch;
  }

  protected override sh(file: string, args: string[]): string {
    RecordingBackend.gitCalls.push({ file, args });
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      // satisfy the constructor's independent-clone guard.
      return ".git";
    }
    // worktree list → no existing worktree (drive the fresh-cut path).
    return "";
  }
  protected override cloneDirExists(): boolean {
    return true; // reuse — no clone in the constructor.
  }
  protected override async createResidentWorktree(
    branch: string,
    baseBranch: string,
  ): Promise<Worktree> {
    RecordingBackend.cutBaseBranch = baseBranch;
    return {
      branch,
      worktreePath: `/clone/.worktrees/${branch}`,
      async run() {
        throw new Error("test worktree must not run an agent");
      },
      async interactive() {
        throw new Error("test worktree must not start an interactive session");
      },
      async createSandbox() {
        throw new Error("test worktree must not create a sandbox");
      },
      async close() {
        return {};
      },
      async [Symbol.asyncDispose]() {},
    };
  }
}

function build(over: Partial<RealBackendOptions> = {}): RecordingBackend {
  RecordingBackend.gitCalls = [];
  RecordingBackend.cutBaseBranch = undefined;
  return new RecordingBackend({
    sourceRepo: "/src/Ming_LLM",
    remote: "https://github.com/Akagilnc/ming-salvage-sim.git",
    runKey: 291,
    repo: "Akagilnc/ming-salvage-sim",
    imageName: "img",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    home: "/tmp/home",
    ...over,
  });
}

describe("#291 prepareWorktree family-base local cut (ADR 0022 decision 7)", () => {
  it("a family child cuts from the LOCAL family base — no fetch, no origin/ prefix", async () => {
    const b = build({ familyBase: "family/293-base" });
    await b.prepareWorktree(42, "family/293-base");
    // cut from the bare LOCAL family base (the merger's accumulated waves).
    expect(b.cutBaseBranch).toBe("family/293-base");
    // and CRUCIALLY: no `git fetch origin family/293-base` (a local-only branch).
    const fetched = b.gitCalls.find(
      (c) => c.file === "git" && c.args[0] === "fetch",
    );
    expect(fetched).toBeUndefined();
  });

  it("a standalone single-slice run (base=main, no familyBase) keeps origin/main — zero regression", async () => {
    const b = build(); // no familyBase option
    await b.prepareWorktree(42, "main");
    // fetches origin/main and cuts from the refreshed remote ref.
    expect(b.cutBaseBranch).toBe("origin/main");
    const fetched = b.gitCalls.find(
      (c) => c.file === "git" && c.args[0] === "fetch" && c.args[1] === "origin" && c.args[2] === "main",
    );
    expect(fetched).toBeDefined();
  });
});
