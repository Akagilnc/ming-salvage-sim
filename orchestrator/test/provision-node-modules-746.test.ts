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

import {
  canClonefileNodeModules,
  listNodeProjectDirs,
  lockfileFingerprint,
  provisionNodeModules,
  resolveTemplateProjectDir,
} from "../src/provisionNodeModules.js";
import {
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../src/family/realFamilyBackend.js";
import {
  clonePathFor,
  RealBackend,
  type RealBackendOptions,
  repoSlug,
} from "../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "prompts");
const realSoulsDir = join(here, "..", "image", "souls");

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
});

describe("provisionNodeModules", () => {
  it("clonefiles when lockfiles match (no npm)", () => {
    const target = mkDir("prov-cf-t-");
    const tpl = mkDir("prov-cf-p-");
    writeProject(target, { lock: LOCK_A });
    writeProject(tpl, { lock: LOCK_A, withModules: true, modulesMarker: "tpl-marker" });

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = provisionNodeModules(target, {
      templateProjectDir: tpl,
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        if (file === "cp") {
          // Real clone/copy so the marker lands (tests run on APFS host).
          execFileSync(file, args, { encoding: "utf8" });
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

  it("falls back to npm ci when lockfiles mismatch", () => {
    const target = mkDir("prov-mis-t-");
    const tpl = mkDir("prov-mis-p-");
    writeProject(target, { lock: LOCK_B });
    writeProject(tpl, { lock: LOCK_A, withModules: true });

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = provisionNodeModules(target, {
      templateProjectDir: tpl,
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        return "";
      },
    });

    expect(result.method).toBe("npm-ci");
    expect(calls).toEqual([{ file: "npm", args: ["ci"], cwd: target }]);
  });

  it("falls back to npm install when no lockfile", () => {
    const target = mkDir("prov-inst-t-");
    writeProject(target);

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = provisionNodeModules(target, {
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        return "";
      },
    });

    expect(result.method).toBe("npm-install");
    expect(calls).toEqual([{ file: "npm", args: ["install"], cwd: target }]);
  });

  it("falls back to npm when clonefile command fails", () => {
    const target = mkDir("prov-fail-t-");
    const tpl = mkDir("prov-fail-p-");
    writeProject(target, { lock: LOCK_A });
    writeProject(tpl, { lock: LOCK_A, withModules: true });

    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = provisionNodeModules(target, {
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

  it("falls back to npm ci when no template is provided", () => {
    const target = mkDir("prov-notpl-");
    writeProject(target, { lock: LOCK_A });
    const calls: Array<{ file: string; args: string[]; cwd?: string }> = [];
    const result = provisionNodeModules(target, {
      sh: (file, args, cwd) => {
        calls.push({ file, args, cwd });
        return "";
      },
    });
    expect(result.method).toBe("npm-ci");
    expect(calls).toEqual([{ file: "npm", args: ["ci"], cwd: target }]);
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

  it("clonefiles from depsTemplateRoot subproject instead of npm when locks match", () => {
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
          execFileSync(file, args, { encoding: "utf8" });
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
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/746-base" });
      }
    }

    new SpyBackend(
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

  it("still npm ci when template lockfile mismatches (wave mutated lock)", () => {
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
      runVerifyForTest(): void {
        this.runVerifyCommands({ phase: "final", familyBase: "family/746-base" });
      }
    }

    new SpyBackend(
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
      skillsMount: "/tmp/skills",
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
          execFileSync(file, args, { encoding: "utf8" });
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
          execFileSync(file, args, { encoding: "utf8" });
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
    // Fail-closed residue clean still precedes provision (ADR 0024 / 0017).
    const resetIdx = ran.findIndex((r) => r === "git reset --hard HEAD");
    const cleanIdx = ran.findIndex((r) => r === "git clean -fd");
    const cpIdx = ran.findIndex((r) => r.startsWith("cp "));
    expect(resetIdx).toBeGreaterThanOrEqual(0);
    expect(cleanIdx).toBeGreaterThanOrEqual(0);
    expect(cpIdx).toBeGreaterThan(Math.max(resetIdx, cleanIdx));

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
