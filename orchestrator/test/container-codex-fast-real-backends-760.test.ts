import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import { RealFamilyBackend, type RealFamilyBackendOptions } from "../src/family/realFamilyBackend.js";
import { RealBackend, type RealBackendOptions } from "../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const promptsDir = join(here, "..", "prompts");
const soulsDir = join(here, "..", "image", "souls");
const configToml = (dir: string) => readFileSync(join(dir, "config.toml"), "utf8");

const tempRoots: string[] = [];

function tempRoot(prefix: string): string {
  const root = mkdtempSync(join(tmpdir(), prefix));
  tempRoots.push(root);
  return root;
}

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}

function makeSourceRepo(): string {
  const repo = tempRoot("codex-fast-760-source-");
  git(repo, "init", "-q");
  git(repo, "config", "user.email", "test@example.com");
  git(repo, "config", "user.name", "test");
  git(repo, "config", "commit.gpgsign", "false");
  writeFileSync(join(repo, "README.md"), "fixture\n", "utf8");
  git(repo, "add", "README.md");
  git(repo, "commit", "-q", "-m", "fixture");
  return repo;
}

function makeHome(): string {
  const home = tempRoot("codex-fast-760-home-");
  mkdirSync(join(home, ".codex"), { recursive: true });
  writeFileSync(join(home, ".codex", "auth.json"), "{}\n", "utf8");
  writeFileSync(join(home, ".sc-claude-token"), "test-token\n", "utf8");
  return home;
}

function realBackendOptions(sourceRepo: string, home: string, codexFast: boolean): RealBackendOptions {
  return {
    sourceRepo,
    runKey: 760,
    repo: "owner/repo",
    imageName: "test-image",
    promptsDir,
    soulsDir,
    home,
    codexFast,
  };
}

function familyBackendOptions(workingRepo: string, home: string, ledgerDir: string, codexFast: boolean): RealFamilyBackendOptions {
  return {
    workingRepo,
    familyBase: "main",
    ledgerDir,
    repo: "owner/repo",
    base: "main",
    promptsDir,
    soulsDir,
    imageName: "test-image",
    home,
    codexFast,
  };
}

class ExposedRealBackend extends RealBackend {
  mountAuthForTest(issueNumber: number) {
    return this.mountAuth(issueNumber);
  }

  mountShipAuthForTest(issueNumber: number) {
    return this.mountShipAuth(issueNumber);
  }
}

class ExposedRealFamilyBackend extends RealFamilyBackend {
  mountMergerAuthForTest() {
    return this.mountMergerAuth();
  }

  mountCmrAuthForTest() {
    return this.mountCmrAuth();
  }

  mountShipAuthForTest() {
    return this.mountShipAuth();
  }
}

afterEach(() => {
  for (const root of tempRoots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("#760 real backend Codex fast write-site consumption", () => {
  it.each([true, false])("RealBackend mountAuth writes service_tier for codexFast=%s", (codexFast) => {
    const home = makeHome();
    const backend = new ExposedRealBackend(realBackendOptions(makeSourceRepo(), home, codexFast));

    backend.mountAuthForTest(760);

    const config = configToml(join(home, ".sc-orchestrator", "auth-760"));
    expect(config.includes('service_tier = "fast"')).toBe(codexFast);
  });

  it.each([true, false])("RealBackend mountShipAuth writes service_tier for codexFast=%s", (codexFast) => {
    const home = makeHome();
    const backend = new ExposedRealBackend(realBackendOptions(makeSourceRepo(), home, codexFast));

    const auth = backend.mountShipAuthForTest(760);

    expect(auth.codexAuthDir).toBeDefined();
    expect(configToml(auth.codexAuthDir!)).toContain(codexFast ? 'service_tier = "fast"' : 'approval_policy = "never"');
  });

  it.each([true, false])("RealFamilyBackend writes service_tier at all three family sites for codexFast=%s", (codexFast) => {
    const home = makeHome();
    const backend = new ExposedRealFamilyBackend(
      familyBackendOptions(makeSourceRepo(), home, tempRoot("codex-fast-760-ledger-"), codexFast),
    );
    const auths = [
      backend.mountMergerAuthForTest(),
      backend.mountCmrAuthForTest(),
      backend.mountShipAuthForTest(),
    ];

    for (const auth of auths) {
      expect(auth.codexAuthDir).toBeDefined();
      expect(configToml(auth.codexAuthDir!)).toContain(codexFast ? 'service_tier = "fast"' : 'approval_policy = "never"');
      rmSync(auth.codexAuthDir!, { recursive: true, force: true });
    }
  });

  it("keeps all five production write sites consuming opts.codexFast", () => {
    const sources = [
      readFileSync(join(here, "..", "src", "realBackend.ts"), "utf8"),
      readFileSync(join(here, "..", "src", "family", "realFamilyBackend.ts"), "utf8"),
    ];
    const countMatches = (source: string) => {
      const matches: string[] = [];
      for (const match of source.matchAll(/writeContainerCodexConfig\s*\(/g)) {
        const openParen = match.index! + match[0].length - 1;
        let depth = 0;
        let closeParen = -1;
        for (let index = openParen; index < source.length; index += 1) {
          if (source[index] === "(") depth += 1;
          if (source[index] === ")" && --depth === 0) {
            closeParen = index;
            break;
          }
        }
        if (closeParen >= 0) matches.push(source.slice(match.index!, closeParen + 1));
      }
      const valid = matches.filter((match) => match.includes("this.opts.codexFast"));
      return { total: matches.length, valid: valid.length };
    };

    const realResult = countMatches(sources[0]);
    const familyResult = countMatches(sources[1]);

    expect(realResult).toEqual({ total: 2, valid: 2 });
    expect(familyResult).toEqual({ total: 3, valid: 3 });
  });
});
