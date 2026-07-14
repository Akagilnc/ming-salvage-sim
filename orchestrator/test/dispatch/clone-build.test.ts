/**
 * #292 — RealBackend self-builds & holds a dedicated clone (ADR 0024 dec. 1+3).
 *
 * Drives the REAL RealBackend constructor with a test subclass that intercepts
 * the `sh` seam (the same pattern as integ-cmr-r3-reuse-fail-closed) plus the
 * `cloneDirExists` fs seam: no real `git clone`, no Docker. It records every git
 * invocation and answers the `rev-parse --git-common-dir` guard query, so we can
 * assert:
 *
 *   1. driver feeds sourceRepo (+remote) + a deterministic runKey — NOT a mainRepo
 *      path; RealBackend derives the clone path itself.
 *   2. a missing clone dir is cloned from sourceRepo; an existing one is reused
 *      (idempotent — same runKey → same clone, no re-clone).
 *   3. the fail-closed guard runs after the clone exists and THROWS at
 *      construction (不启动) when --git-common-dir is a linked worktree's shared
 *      .git instead of the clone's own .git.
 *   4. mainRepo (the clone) addresses by runKey; family run (parent epic#) and
 *      single-slice run (issue#) land on distinct clones.
 */

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  clonePathFor,
  RealBackend,
  type RealBackendOptions,
  repoSlug,
} from "../../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "image", "souls");

const SOURCE = "/Users/me/WorkSpace/Ming_LLM";
const REMOTE = "https://github.com/Akagilnc/ming-salvage-sim.git";
const HOME = "/tmp/home";

interface ShCfg {
  cloneExists: boolean;
  commonDir: string;
}

/**
 * Intercepts `sh` (git) + the `cloneDirExists` fs seam, recording every git
 * call. Config is read from a STATIC field set immediately before each `new`
 * (so the overridden seams already see it during the super() constructor body).
 */
class RecordingBackend extends RealBackend {
  static cfg: ShCfg = { cloneExists: false, commonDir: ".git" };
  // STATIC so constructor-time git (clone + guard) is captured despite the
  // subclass field-init-after-super ordering. Reset per `build()`.
  static gitCalls: Array<{ file: string; args: string[]; cwd?: string }> = [];

  get gitCalls(): Array<{ file: string; args: string[]; cwd?: string }> {
    return RecordingBackend.gitCalls;
  }

  protected override sh(file: string, args: string[], cwd?: string): string {
    RecordingBackend.gitCalls.push({ file, args, cwd });
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      return RecordingBackend.cfg.commonDir;
    }
    return "";
  }

  protected override cloneDirExists(_path: string): boolean {
    return RecordingBackend.cfg.cloneExists;
  }
}

function build(cfg: ShCfg, override?: Partial<RealBackendOptions>): RecordingBackend {
  RecordingBackend.cfg = cfg;
  RecordingBackend.gitCalls = [];
  return new RecordingBackend({
    sourceRepo: SOURCE,
    remote: REMOTE,
    runKey: 291,
    repo: "Akagilnc/ming-salvage-sim",
    imageName: "img",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    home: HOME,
    ...override,
  });
}

const expectedClone = clonePathFor(HOME, repoSlug(SOURCE, REMOTE), 291);

describe("#292 RealBackend self-builds a dedicated clone (ADR 0024 dec. 1)", () => {
  it("clones from sourceRepo into <home>/.sc-orchestrator/<slug>-iso-<runKey> when absent", () => {
    const b = build({ cloneExists: false, commonDir: `${expectedClone}/.git` });
    const clone = b.gitCalls.find((c) => c.file === "git" && c.args[0] === "clone");
    expect(clone).toBeDefined();
    expect(clone?.args).toContain(SOURCE);
    expect(clone?.args).toContain(expectedClone);
  });

  it("reuses an existing clone (idempotent) — does NOT re-clone", () => {
    const b = build({ cloneExists: true, commonDir: `${expectedClone}/.git` });
    const clone = b.gitCalls.find((c) => c.file === "git" && c.args[0] === "clone");
    expect(clone).toBeUndefined();
  });

  it("the derived clone path is the slice's working repo (worktree ops cut from it)", () => {
    const b = build({ cloneExists: true, commonDir: `${expectedClone}/.git` });
    expect(b.workingRepoPath()).toBe(expectedClone);
  });
});

describe("#292 fail-closed guard (ADR 0024 dec. 1/3)", () => {
  it("throws at construction when --git-common-dir is a linked worktree's shared .git", () => {
    expect(() =>
      build({ cloneExists: true, commonDir: "/Users/me/WorkSpace/Ming_LLM/.git" }),
    ).toThrow(/git-common-dir|linked worktree|not an independent clone/i);
  });

  it("does NOT throw when the common dir is the clone's own .git", () => {
    expect(() =>
      build({ cloneExists: true, commonDir: `${expectedClone}/.git` }),
    ).not.toThrow();
  });

  it("accepts the literal relative '.git' (normal clone run from its root)", () => {
    expect(() => build({ cloneExists: true, commonDir: ".git" })).not.toThrow();
  });
});

describe("#292 run-key addressing — family vs single-slice land on distinct clones", () => {
  it("family run (parent epic#) and single-slice run (issue#) use different clones", () => {
    const fam = build({ cloneExists: true, commonDir: ".git" }, { runKey: 291 });
    const single = build({ cloneExists: true, commonDir: ".git" }, { runKey: 292 });
    expect(fam.workingRepoPath()).not.toBe(single.workingRepoPath());
  });
});
