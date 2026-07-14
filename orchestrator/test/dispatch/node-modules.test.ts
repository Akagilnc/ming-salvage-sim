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

describe("lockfileFingerprint / resolveTemplateProjectDir / listNodeProjectDirs", () => {
  it("hashes package-lock.json content", () => {
    const dir = mkDir("lock-fp-");
    writeProject(dir, { lock: LOCK_A });
    const a = lockfileFingerprint(dir);
    expect(a).toMatch(/^[a-f0-9]{64}$/);
    writeFileSync(join(dir, "package-lock.json"), LOCK_B);
    expect(lockfileFingerprint(dir)).not.toBe(a);
  });

  it("returns undefined when no lockfile", () => {
    const dir = mkDir("no-lock-");
    writeProject(dir);
    expect(lockfileFingerprint(dir)).toBeUndefined();
  });

  it("maps target project onto template monorepo root by relative path", () => {
    expect(
      resolveTemplateProjectDir("/clone/orchestrator", {
        templateRoot: "/src",
        targetRoot: "/clone",
      }),
    ).toBe(join("/src", "orchestrator"));
  });

  it("returns undefined when target is outside targetRoot", () => {
    expect(
      resolveTemplateProjectDir("/other/orchestrator", {
        templateRoot: "/src",
        targetRoot: "/clone",
      }),
    ).toBeUndefined();
  });

  it("lists root + immediate child Node projects", () => {
    const root = mkDir("list-proj-");
    writeProject(root, { lock: LOCK_A });
    writeProject(join(root, "orchestrator"), { lock: LOCK_A });
    writeProject(join(root, "web"), { lock: LOCK_A });
    mkdirSync(join(root, "docs"), { recursive: true });
    const listed = listNodeProjectDirs(root).map((p) => p.slice(root.length + 1) || ".");
    expect(listed.sort()).toEqual([".", "orchestrator", "web"].sort());
  });
});

describe("canClonefileNodeModules", () => {
  it("true only when template has node_modules and lockfiles match", () => {
    const target = mkDir("can-tgt-");
    const tpl = mkDir("can-tpl-");
    writeProject(target, { lock: LOCK_A });
    writeProject(tpl, { lock: LOCK_A, withModules: true });
    expect(canClonefileNodeModules(target, tpl)).toBe(true);

    writeFileSync(join(target, "package-lock.json"), LOCK_B);
    expect(canClonefileNodeModules(target, tpl)).toBe(false);
  });

  it("false when template lacks node_modules", () => {
    const target = mkDir("can-no-nm-t-");
    const tpl = mkDir("can-no-nm-p-");
    writeProject(target, { lock: LOCK_A });
    writeProject(tpl, { lock: LOCK_A });
    expect(canClonefileNodeModules(target, tpl)).toBe(false);
  });

  it("false when package.json diverges even if package-lock.json matches", () => {
    const target = mkDir("can-pkg-drift-t-");
    const tpl = mkDir("can-pkg-drift-p-");
    writeProject(target, { lock: LOCK_A });
    writeProject(tpl, { lock: LOCK_A, withModules: true });
    writeFileSync(
      join(target, "package.json"),
      JSON.stringify({ name: "proj", version: "0.0.0", dependencies: { fresh: "1.0.0" } }),
    );

    expect(packageJsonFingerprint(target)).not.toBe(packageJsonFingerprint(tpl));
    expect(canClonefileNodeModules(target, tpl)).toBe(false);
  });
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

  it("falls back to npm ci when lockfiles mismatch", async () => {
    const target = mkDir("prov-mis-t-");
    const tpl = mkDir("prov-mis-p-");
    writeProject(target, { lock: LOCK_B });
    writeProject(tpl, { lock: LOCK_A, withModules: true });

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = await provisionNodeModules(target, {
      templateProjectDir: tpl,
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        return "";
      },
    });

    expect(result.method).toBe("npm-ci");
    expect(calls).toEqual([{ file: "npm", args: ["ci"], cwd: target }]);
  });

  it("keeps npm ci when package.json diverges but the lockfile still matches", async () => {
    const target = mkDir("prov-pkg-drift-t-");
    const tpl = mkDir("prov-pkg-drift-p-");
    writeProject(target, { lock: LOCK_A });
    writeProject(tpl, { lock: LOCK_A, withModules: true });
    writeFileSync(
      join(target, "package.json"),
      JSON.stringify({ name: "proj", version: "0.0.0", dependencies: { fresh: "1.0.0" } }),
    );

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = await provisionNodeModules(target, {
      templateProjectDir: tpl,
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        return "";
      },
    });

    expect(result.method).toBe("npm-ci");
    expect(calls).toEqual([{ file: "npm", args: ["ci"], cwd: target }]);
  });

  it("falls back to npm install when no lockfile", async () => {
    const target = mkDir("prov-inst-t-");
    writeProject(target);

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = await provisionNodeModules(target, {
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        return "";
      },
    });

    expect(result.method).toBe("npm-install");
    expect(calls).toEqual([{ file: "npm", args: ["install"], cwd: target }]);
  });

  it("falls back to npm when clonefile command fails", async () => {
    const target = mkDir("prov-fail-t-");
    const tpl = mkDir("prov-fail-p-");
    writeProject(target, { lock: LOCK_A });
    writeProject(tpl, { lock: LOCK_A, withModules: true });

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = await provisionNodeModules(target, {
      templateProjectDir: tpl,
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        if (file === "cp") throw new Error("clonefile unsupported");
        return "";
      },
    });

    expect(result.method).toBe("npm-ci");
    expect(calls[0]?.file).toBe("cp");
    expect(calls[1]).toEqual({ file: "npm", args: ["ci"], cwd: target });
  });

  it("cleans a partial clonefile target before starting npm fallback", async () => {
    const target = mkDir("prov-partial-fail-t-");
    const tpl = mkDir("prov-partial-fail-p-");
    writeProject(target, { lock: LOCK_A });
    writeProject(tpl, { lock: LOCK_A, withModules: true });

    let targetWasCleanAtNpmStart: boolean | undefined;
    const result = await provisionNodeModules(target, {
      templateProjectDir: tpl,
      sh: (file, _args, cwd) => {
        if (file === "cp") {
          mkdirSync(join(target, "node_modules"), { recursive: true });
          writeFileSync(join(target, "node_modules", ".partial"), "incomplete");
          throw new Error("clonefile failed midway");
        }
        if (file === "npm") {
          targetWasCleanAtNpmStart = !existsSync(join(cwd ?? target, "node_modules"));
          return "";
        }
        throw new Error(`unexpected ${file}`);
      },
    });

    expect(result.method).toBe("npm-ci");
    expect(targetWasCleanAtNpmStart).toBe(true);
  });

  it("falls back to npm ci when no template is provided", async () => {
    const target = mkDir("prov-notpl-");
    writeProject(target, { lock: LOCK_A });
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = await provisionNodeModules(target, {
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        return "";
      },
    });
    expect(result.method).toBe("npm-ci");
    expect(calls).toEqual([{ file: "npm", args: ["ci"], cwd: target }]);
  });

  it("awaits async shell work and overlaps concurrent provisions", async () => {
    const targetA = mkDir("prov-async-a-");
    const targetB = mkDir("prov-async-b-");
    const template = mkDir("prov-async-tpl-");
    writeProject(targetA, { lock: LOCK_A });
    writeProject(targetB, { lock: LOCK_A });
    writeProject(template, { lock: LOCK_A, withModules: true });

    let active = 0;
    let maxActive = 0;
    let completedCommands = 0;
    const HOLD_MS = 30;
    const sh = async (file: string): Promise<string> => {
      expect(file).toBe("cp");
      active += 1;
      maxActive = Math.max(maxActive, active);
      await new Promise((resolve) => setTimeout(resolve, HOLD_MS));
      active -= 1;
      completedCommands += 1;
      return "";
    };

    const results = await Promise.all([
      provisionNodeModules(targetA, { templateProjectDir: template, sh }),
      provisionNodeModules(targetB, { templateProjectDir: template, sh }),
    ]);

    expect(results.map((result) => result.method)).toEqual(["clonefile", "clonefile"]);
    expect(completedCommands).toBe(2);
    expect(maxActive).toBe(2);
  });

  it("awaits every project when provisioning a repository", async () => {
    const repo = mkDir("prov-repo-async-");
    const template = mkDir("prov-repo-async-tpl-");
    writeProject(repo, { lock: LOCK_A });
    writeProject(join(repo, "orchestrator"), { lock: LOCK_A });
    writeProject(template, { lock: LOCK_A, withModules: true });
    writeProject(join(template, "orchestrator"), { lock: LOCK_A, withModules: true });

    const calls: string[] = [];
    let active = 0;
    let maxActive = 0;
    const results = await provisionRepoNodeModules(repo, {
      templateRoot: template,
      sh: async (file, args, cwd) => {
        calls.push(`${file} ${args.join(" ")} ${cwd}`);
        active += 1;
        maxActive = Math.max(maxActive, active);
        await new Promise((resolve) => setTimeout(resolve, 20));
        active -= 1;
        return "";
      },
    });

    expect(results).toHaveLength(2);
    expect(calls).toHaveLength(2);
    expect(maxActive).toBe(2);
  });

  it("waits for every project before reporting aggregate provisioning failures", async () => {
    const repo = mkDir("prov-repo-fail-async-");
    const template = mkDir("prov-repo-fail-async-tpl-");
    writeProject(join(repo, "orchestrator"), { lock: LOCK_A });
    writeProject(join(repo, "web"), { lock: LOCK_A });
    writeProject(join(template, "orchestrator"), { lock: LOCK_A, withModules: true });
    writeProject(join(template, "web"), { lock: LOCK_A, withModules: true });

    const completed: string[] = [];
    await expect(
      provisionRepoNodeModules(repo, {
        templateRoot: template,
        sh: async (file, _args, cwd) => {
          const project = cwd?.endsWith("orchestrator") ? "orchestrator" : "web";
          await new Promise((resolve) =>
            setTimeout(resolve, project === "orchestrator" ? 5 : 30),
          );
          if (file === "npm") {
            completed.push(project);
          }
          throw new Error(`${project} ${file} failed`);
        },
      }),
    ).rejects.toThrow(/2.*provisioning.*failed|orchestrator failed.*web failed/s);
    expect(completed).toEqual(["orchestrator", "web"]);
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

  it("still npm ci when template lockfile mismatches (wave mutated lock)", async () => {
    const clone = mkDir("rfb-mis-clone-");
    const source = mkDir("rfb-mis-src-");
    const verifyCwd = join(clone, "orchestrator");
    writeProject(verifyCwd, { lock: LOCK_B, withModules: true });
    writeProject(join(source, "orchestrator"), { lock: LOCK_A, withModules: true });

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    class SpyBackend extends RealFamilyBackend {
      protected override sh(file: string, args: string[], cwd?: string): string {
        calls.push({ file, args, cwd });
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

    expect(calls[0]).toEqual({ file: "npm", args: ["ci"], cwd: verifyCwd });
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

  /**
   * #746 R2 P2 — provisioning must NOT run under the per-clone git mutex.
   * Family waves share one RealBackend/clone: if npm/clonefile stays inside
   * runExclusive, N concurrent prepares serialize on ~90s installs. Mutex covers
   * git worktree mutations only; each worktree's node_modules is independent.
   */
  it("provisions OUTSIDE the git mutex — concurrent prepares overlap on provision", async () => {
    const source = mkDir("rb-conc-src-");
    const home = mkDir("rb-conc-home-");
    writeProject(source, { lock: LOCK_A, withModules: true });

    // Two wave children, one shared RealBackend clone (runKey = ISSUE = 746).
    const ISSUE_A = 74601;
    const ISSUE_B = 74602;
    const clone = clonePathFor(home, repoSlug(source, REMOTE), ISSUE);
    const pathA = join(clone, ".sandcastle", "worktrees", `issue-${ISSUE_A}`);
    const pathB = join(clone, ".sandcastle", "worktrees", `issue-${ISSUE_B}`);
    writeProject(pathA, { lock: LOCK_A });
    writeProject(pathB, { lock: LOCK_A });

    let activeProvisions = 0;
    let maxConcurrentProvisions = 0;
    const HOLD_MS = 40;

    class ConcurrentProvisionBackend extends RealBackend {
      protected override cloneDirExists(): boolean {
        return true;
      }
      protected override sh(file: string, args: string[]): string {
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
            `worktree ${pathA}`,
            "HEAD " + "a".repeat(40),
            `branch refs/heads/feat/issue-${ISSUE_A}`,
            "",
            `worktree ${pathB}`,
            "HEAD " + "b".repeat(40),
            `branch refs/heads/feat/issue-${ISSUE_B}`,
          ].join("\n");
        }
        return "";
      }
      protected override async createResidentWorktree(): Promise<sc.Worktree> {
        throw new Error("concurrency test uses reuse path only");
      }
      /** Hold long enough that a second prepare can enter provision if mutex is free. */
      protected override async provisionWorktreeNodeModules(
        _worktreePath: string,
      ): Promise<void> {
        activeProvisions += 1;
        maxConcurrentProvisions = Math.max(maxConcurrentProvisions, activeProvisions);
        await new Promise((r) => setTimeout(r, HOLD_MS));
        activeProvisions -= 1;
      }
    }

    // One backend → one workingRepo mutex key (family-wave shape).
    const backend = new ConcurrentProvisionBackend(backendOpts(source, home));
    await Promise.all([
      backend.prepareWorktree(ISSUE_A, "main"),
      backend.prepareWorktree(ISSUE_B, "main"),
    ]);

    // If provision were still inside runExclusive, peak would be 1 (serial).
    // Outside the mutex, the two delayed provisions overlap → peak 2.
    expect(maxConcurrentProvisions).toBe(2);
  });
});
