/**
 * #746 — APFS clonefile node_modules provisioning.
 *
 * Prefer cloning a lockfile-matching template node_modules (`cp -cR`) over a full
 * `npm ci`. Mismatched / missing template → real npm. Pure helper + installDeps /
 * prepareWorktree wiring (including RealBackend.prepareWorktreeLocked paths).
 */

import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import type * as sc from "@ai-hero/sandcastle";

import { _resetGitMutex } from "../../src/gitMutex.js";
import {
  canClonefileNodeModules,
  listNodeProjectDirs,
  lockfileFingerprint,
  packageJsonFingerprint,
  provisionNodeModules,
  provisionRepoNodeModules,
  resolveTemplateProjectDir,
} from "../../src/provisionNodeModules.js";
import {
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../src/family/realFamilyBackend.js";
import {
  clonePathFor,
  RealBackend,
  type RealBackendOptions,
  repoSlug,
} from "../../src/realBackend.js";
import { buildExplicitLandingLiveHooks } from "../../src/family/landing.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "image", "souls");

function runCpCompat(args: string[]): void {
  const compatibleArgs =
    process.platform === "darwin"
      ? args
      : args.map((arg) => (arg === "-cR" || arg === "-Rc" ? "-R" : arg));
  execFileSync("cp", compatibleArgs, { encoding: "utf8" });
}

const cleanups: string[] = [];
afterEach(() => {
  _resetGitMutex();
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

function writeProject(
  root: string,
  opts: { lock?: string; withModules?: boolean; modulesMarker?: string } = {},
): void {
  mkdirSync(root, { recursive: true });
  writeFileSync(
    join(root, "package.json"),
    JSON.stringify({ name: "proj", version: "0.0.0", scripts: { test: "echo ok" } }),
  );
  if (opts.lock !== undefined) {
    writeFileSync(join(root, "package-lock.json"), opts.lock);
  }
  if (opts.withModules) {
    const nm = join(root, "node_modules");
    mkdirSync(nm, { recursive: true });
    writeFileSync(join(nm, ".marker"), opts.modulesMarker ?? "from-template");
  }
}

const LOCK_A = JSON.stringify({ name: "proj", version: "0.0.0", lockfileVersion: 3 });
const LOCK_B = JSON.stringify({
  name: "proj",
  version: "0.0.1",
  lockfileVersion: 3,
  mutated: true,
});

describe("provisionNodeModules", () => {
  it("clonefiles when lockfiles match (no npm)", async () => {
    const target = mkDir("prov-cf-t-");
    const tpl = mkDir("prov-cf-p-");
    writeProject(target, { lock: LOCK_A });
    writeProject(tpl, { lock: LOCK_A, withModules: true, modulesMarker: "tpl-marker" });

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = await provisionNodeModules(target, {
      templateProjectDir: tpl,
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        if (file === "cp") {
          // Real clone/copy so the marker lands (tests run on APFS host).
          runCpCompat(args);
          return "";
        }
        throw new Error(`unexpected ${file}`);
      },
    });

    expect(result.method).toBe("clonefile");
    expect(calls[0]?.file).toBe("cp");
    expect(calls[0]?.args[0]).toMatch(/^-cR$|^-Rc$/);
    expect(calls.some((c) => c.file === "npm")).toBe(false);
    expect(readFileSync(join(target, "node_modules", ".marker"), "utf8")).toBe("tpl-marker");
  });

});

describe("RealFamilyBackend.installDeps uses clonefile when depsTemplateRoot matches", () => {
  function opts(workingRepo: string, extra?: Partial<RealFamilyBackendOptions>): RealFamilyBackendOptions {
    return {
      workingRepo,
      familyBase: "family/746-base",
      ledgerDir: join(workingRepo, ".ledger"),
      repo: "owner/name",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      ...extra,
    };
  }

  it("clonefiles from depsTemplateRoot subproject instead of npm when locks match", async () => {
    const clone = mkDir("rfb-clone-");
    const source = mkDir("rfb-src-");
    const verifyCwd = join(clone, "orchestrator");
    const tplProj = join(source, "orchestrator");
    writeProject(verifyCwd, { lock: LOCK_A });
    writeProject(tplProj, { lock: LOCK_A, withModules: true, modulesMarker: "src-orch" });

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        if (file === "cp") {
          runCpCompat(args);
          return "";
        }
        return "";
      }
      protected override packageScripts(): readonly string[] {
        return ["typecheck", "test"];
      }
      protected override isNodeProject(): boolean {
        return true;
      }
      async runVerifyForTest(): Promise<void> {
        await this.runVerifyCommands({ phase: "final", familyBase: "family/746-base" });
      }
    }

    await new SpyBackend(
      opts(clone, { verifyCwd, depsTemplateRoot: source }),
    ).runVerifyForTest();

    expect(calls[0]?.file).toBe("cp");
    expect(calls.some((c) => c.file === "npm" && (c.args[0] === "ci" || c.args[0] === "install"))).toBe(
      false,
    );
    expect(calls.map((c) => `${c.file} ${c.args.join(" ")}`).slice(1)).toEqual([
      "npm run typecheck",
      "npm test",
    ]);
    expect(existsSync(join(verifyCwd, "node_modules", ".marker"))).toBe(true);
    expect(readFileSync(join(verifyCwd, "node_modules", ".marker"), "utf8")).toBe("src-orch");
  });

});

/**
 * #746 R1 P2 — regression through the real prepareWorktreeLocked dispatch paths.
 * Helper-level tests alone miss a broken clonefile/fallback wire in
 * RealBackend.prepareWorktree (NEW cut vs resident existing.path reuse).
 */
describe("RealBackend.prepareWorktreeLocked provisions node_modules (#746)", () => {
  const ISSUE = 746;
  const BRANCH = `feat/issue-${ISSUE}`;
  const REMOTE = "https://github.com/owner/name.git";

  type Call = { file: string; args: string[]; cwd?: string };

  function backendOpts(
    sourceRepo: string,
    home: string,
  ): RealBackendOptions {
    return {
      sourceRepo,
      remote: REMOTE,
      runKey: ISSUE,
      repo: "owner/name",
      imageName: "img",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      home,
    };
  }

  it("NEW worktree path: after createResidentWorktree, clonefiles from sourceRepo", async () => {
    const source = mkDir("rb-new-src-");
    const home = mkDir("rb-new-home-");
    writeProject(source, {
      lock: LOCK_A,
      withModules: true,
      modulesMarker: "new-path-src",
    });

    const clone = clonePathFor(home, repoSlug(source, REMOTE), ISSUE);
    const wtPath = join(clone, ".sandcastle", "worktrees", `issue-${ISSUE}`);
    const calls: Call[] = [];

    class NewPathBackend extends RealBackend {
      protected override cloneDirExists(): boolean {
        return true;
      }
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
          return `${clone}/.git`;
        }
        if (file === "cp") {
          runCpCompat(args);
          return "";
        }
        // worktree list empty → FRESH cut; fetch/other git → success
        return "";
      }
      protected override async createResidentWorktree(
        branch: string,
      ): Promise<sc.Worktree> {
        writeProject(wtPath, { lock: LOCK_A });
        return {
          branch,
          worktreePath: wtPath,
          run: async () => ({}),
          interactive: async () => ({}),
          createSandbox: async () => ({}),
          close: async () => ({}),
          [Symbol.asyncDispose]: async () => {},
        } as unknown as sc.Worktree;
      }
    }

    const wt = await new NewPathBackend(backendOpts(source, home)).prepareWorktree(
      ISSUE,
      "main",
    );

    expect(wt.path).toBe(wtPath);
    expect(wt.branch).toBe(BRANCH);
    expect(calls.some((c) => c.file === "cp" && /^-cR$|^-Rc$/.test(c.args[0] ?? ""))).toBe(
      true,
    );
    expect(
      calls.some((c) => c.file === "npm" && (c.args[0] === "ci" || c.args[0] === "install")),
    ).toBe(false);
    expect(readFileSync(join(wtPath, "node_modules", ".marker"), "utf8")).toBe("new-path-src");
  });

  it("resident-reuse path (existing.path): after residue clean, clonefiles from sourceRepo", async () => {
    const source = mkDir("rb-reuse-src-");
    const home = mkDir("rb-reuse-home-");
    writeProject(source, {
      lock: LOCK_A,
      withModules: true,
      modulesMarker: "reuse-path-src",
    });

    const clone = clonePathFor(home, repoSlug(source, REMOTE), ISSUE);
    const existingPath = join(clone, ".sandcastle", "worktrees", `issue-${ISSUE}`);
    // Resident tree already on disk (resume / prior cut) — deps not yet present.
    writeProject(existingPath, { lock: LOCK_A });

    const calls: Call[] = [];

    class ReusePathBackend extends RealBackend {
      protected override cloneDirExists(): boolean {
        return true;
      }
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
        if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
          return `${clone}/.git`;
        }
        if (
          file === "git" &&
          args[0] === "worktree" &&
          args[1] === "list" &&
          args[2] === "--porcelain"
        ) {
          return [
            `worktree ${existingPath}`,
            "HEAD " + "b".repeat(40),
            `branch refs/heads/${BRANCH}`,
          ].join("\n");
        }
        if (file === "cp") {
          runCpCompat(args);
          return "";
        }
        // reset --hard / clean -fd stubbed (must not touch real FS)
        return "";
      }
      protected override async createResidentWorktree(): Promise<sc.Worktree> {
        throw new Error("reuse path must not cut a new worktree");
      }
    }

    const wt = await new ReusePathBackend(backendOpts(source, home)).prepareWorktree(
      ISSUE,
      "main",
    );

    expect(wt.path).toBe(existingPath);
    expect(wt.branch).toBe(BRANCH);

    const ran = calls.map((c) => `${c.file} ${c.args.join(" ")}`);
    // #661 preserves residue; provisioning may proceed without a destructive clean.
    const resetIdx = ran.findIndex((r) => r === "git reset --hard HEAD");
    const cleanIdx = ran.findIndex((r) => r === "git clean -fd");
    const cpIdx = ran.findIndex((r) => r.startsWith("cp "));
    expect(resetIdx).toBe(-1);
    expect(cleanIdx).toBe(-1);
    expect(cpIdx).toBeGreaterThanOrEqual(0);

    expect(calls.some((c) => c.file === "cp" && /^-cR$|^-Rc$/.test(c.args[0] ?? ""))).toBe(
      true,
    );
    expect(
      calls.some((c) => c.file === "npm" && (c.args[0] === "ci" || c.args[0] === "install")),
    ).toBe(false);
    expect(readFileSync(join(existingPath, "node_modules", ".marker"), "utf8")).toBe(
      "reuse-path-src",
    );
  });

});
