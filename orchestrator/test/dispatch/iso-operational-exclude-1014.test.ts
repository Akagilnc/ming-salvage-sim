/**
 * #1014 — provision iso must git-exclude orchestrator operational sidecars
 * (.ledger-star-slash + .sandcastle/) so family final CMR dirty-pin porcelain
 * (`git status --untracked-files=all`) does not list runner-owned droppings.
 * True dirty still appears in porcelain (CMR hard-stop consumes that signal).
 *
 * No md content-pin tests.
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

import {
  ISO_OPERATIONAL_GIT_EXCLUDE_PATTERNS,
  appendIsoOperationalExcludes,
} from "../../src/gitInfoExclude.js";
import {
  clonePathFor,
  RealBackend,
  repoSlug,
} from "../../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "..", "prompts");
const realSoulsDir = join(here, "..", "..", "image", "souls");

const temps: string[] = [];
function trackTemp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  temps.push(d);
  return d;
}
afterEach(() => {
  while (temps.length > 0) {
    const d = temps.pop();
    if (d !== undefined) rmSync(d, { recursive: true, force: true });
  }
});

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", ["-C", cwd, ...args], {
    encoding: "utf8",
  }).trim();
}

function makeSourceRepo(): string {
  const dir = trackTemp("iso-1014-src-");
  git(dir, "init", "-q");
  git(dir, "config", "user.email", "t@t.t");
  git(dir, "config", "user.name", "t");
  git(dir, "config", "commit.gpgsign", "false");
  writeFileSync(join(dir, "README"), "seed\n");
  git(dir, "add", "README");
  git(dir, "commit", "-q", "-m", "seed");
  return dir;
}

function porcelainAll(repo: string): string {
  return execFileSync(
    "git",
    ["-C", repo, "status", "--porcelain=v1", "--untracked-files=all"],
    { encoding: "utf8" },
  );
}

function excludeLines(repo: string): string[] {
  const p = join(repo, ".git", "info", "exclude");
  if (!existsSync(p)) return [];
  return readFileSync(p, "utf8").split(/\r?\n/).filter((l) => l.length > 0 && !l.startsWith("#"));
}

describe("#1014 iso operational sidecar git excludes", () => {
  it("exports the two provision patterns as the single source of truth", () => {
    expect([...ISO_OPERATIONAL_GIT_EXCLUDE_PATTERNS]).toEqual([
      ".ledger-*/",
      ".sandcastle/",
    ]);
  });

  it("appendIsoOperationalExcludes writes both patterns idempotently (CRLF-safe)", () => {
    const repo = makeSourceRepo();
    const excludePath = join(repo, ".git", "info", "exclude");
    writeFileSync(excludePath, ".ledger-*/\r\n", "utf8");

    appendIsoOperationalExcludes(repo);
    appendIsoOperationalExcludes(repo); // second call must not duplicate

    const lines = excludeLines(repo);
    expect(lines.filter((l) => l === ".ledger-*/")).toHaveLength(1);
    expect(lines.filter((l) => l === ".sandcastle/")).toHaveLength(1);
  });

  it("provision iso via RealBackend.workingRepoPath puts both patterns in info/exclude", () => {
    const source = makeSourceRepo();
    const home = trackTemp("iso-1014-home-");
    const remote = "https://github.com/Akagilnc/ming-salvage-sim.git";
    const runKey = 1014;
    const expected = clonePathFor(home, repoSlug(source, remote), runKey);

    const backend = new RealBackend({
      sourceRepo: source,
      remote,
      runKey,
      repo: "Akagilnc/ming-salvage-sim",
      imageName: "img",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      home,
    });
    const iso = backend.workingRepoPath();
    expect(iso).toBe(expected);
    expect(existsSync(join(iso, ".git"))).toBe(true);

    const lines = excludeLines(iso);
    expect(lines).toContain(".ledger-*/");
    expect(lines).toContain(".sandcastle/");
  });

  it("live sidecars under exclude do not dirty porcelain=v1 --untracked-files=all; true dirty still shows", () => {
    const source = makeSourceRepo();
    const home = trackTemp("iso-1014-home-dirty-");
    const remote = "https://github.com/Akagilnc/ming-salvage-sim.git";
    const backend = new RealBackend({
      sourceRepo: source,
      remote,
      runKey: 10140,
      repo: "Akagilnc/ming-salvage-sim",
      imageName: "img",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      home,
    });
    const iso = backend.workingRepoPath();

    // Live orchestrator sidecars (the #985 failure shape).
    mkdirSync(join(iso, ".ledger-994", "worker-logs"), { recursive: true });
    writeFileSync(join(iso, ".ledger-994", "telemetry.jsonl"), "{}\n");
    mkdirSync(join(iso, ".sandcastle", "worktrees", "issue-994"), {
      recursive: true,
    });
    writeFileSync(
      join(iso, ".sandcastle", "worktrees", "issue-994", "steps.jsonl"),
      "{}\n",
    );

    // Assert porcelain only — CMR hard-stop reads this same signal.
    expect(porcelainAll(iso)).toBe("");

    // True dirty: non-sidecar untracked file → still appears in porcelain.
    writeFileSync(join(iso, "stray-untracked.txt"), "oops\n");
    expect(porcelainAll(iso)).toMatch(/stray-untracked\.txt/);

    // True dirty: tracked content change → still appears in porcelain.
    rmSync(join(iso, "stray-untracked.txt"));
    writeFileSync(join(iso, "README"), "mutated\n");
    expect(porcelainAll(iso)).toMatch(/README/);
  });

  it("appendIsoOperationalExcludes throws when info/exclude cannot be written (fail-closed)", () => {
    // Non-git path: rev-parse fails → throw-through (append* family), not ensure* swallow.
    const notARepo = trackTemp("iso-1014-nongit-");
    expect(() => appendIsoOperationalExcludes(notARepo)).toThrow();
  });
});
