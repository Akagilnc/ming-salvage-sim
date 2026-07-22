/**
 * #1103 — shared-.git write class: worktree wreckage self-heal (H1) +
 * cross-process gitMutex (H2) + exclude RMW under the same lock (H3).
 *
 * Real git repos + real filesystem only — no mocked FS / no psychic fixtures.
 */

import { execFileSync, spawn } from "node:child_process";
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

import { ensureGitInfoExclude } from "../../src/gitInfoExclude.js";
import {
  _resetGitMutex,
  orchestratorGitLockPath,
  runExclusive,
} from "../../src/gitMutex.js";
import {
  healBeforeWorktreeCut,
  sandcastleWorktreePathForBranch,
} from "../../src/gitWorktreePreflight.js";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "..", "..", "src");

const temps: string[] = [];
function trackTemp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  temps.push(d);
  return d;
}
afterEach(() => {
  _resetGitMutex();
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

function makeRepo(): string {
  const dir = trackTemp("1103-repo-");
  git(dir, "init", "-q");
  git(dir, "config", "user.email", "t@t.t");
  git(dir, "config", "user.name", "t");
  git(dir, "config", "commit.gpgsign", "false");
  writeFileSync(join(dir, "README"), "seed\n");
  git(dir, "add", "README");
  git(dir, "commit", "-q", "-m", "seed");
  return dir;
}

function spawnTsx(
  scriptPath: string,
): Promise<{ status: number | null; stderr: string; stdout: string }> {
  return new Promise((resolve) => {
    const child = spawn("npx", ["--yes", "tsx", scriptPath], {
      env: { ...process.env },
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (c: Buffer) => {
      stdout += c.toString();
    });
    child.stderr.on("data", (c: Buffer) => {
      stderr += c.toString();
    });
    child.on("close", (status) => resolve({ status, stdout, stderr }));
  });
}

describe("#1103 H1 healBeforeWorktreeCut", () => {
  it("heals dir-present/metadata-absent wreckage so a fresh worktree add succeeds", () => {
    const repo = makeRepo();
    const branch = "feat/issue-1103";
    const wtPath = sandcastleWorktreePathForBranch(repo, branch);
    mkdirSync(wtPath, { recursive: true });
    writeFileSync(join(wtPath, "orphan.txt"), "wreckage\n");
    expect(git(repo, "worktree", "list", "--porcelain")).not.toContain(wtPath);

    healBeforeWorktreeCut(repo, branch);

    expect(existsSync(wtPath)).toBe(false);
    git(repo, "worktree", "add", "-b", branch, wtPath, "HEAD");
    expect(existsSync(join(wtPath, "README"))).toBe(true);
    expect(git(repo, "worktree", "list", "--porcelain")).toContain(wtPath);
  });

  it("NEGATIVE: does not delete an active registered worktree", () => {
    const repo = makeRepo();
    const branch = "feat/issue-1103-live";
    const wtPath = sandcastleWorktreePathForBranch(repo, branch);
    mkdirSync(dirname(wtPath), { recursive: true });
    git(repo, "worktree", "add", "-b", branch, wtPath, "HEAD");
    writeFileSync(join(wtPath, "keep-me.txt"), "live\n");

    healBeforeWorktreeCut(repo, branch);

    expect(existsSync(join(wtPath, "keep-me.txt"))).toBe(true);
    expect(git(repo, "worktree", "list", "--porcelain")).toContain(wtPath);
  });
});

describe("#1103 H2 cross-process gitMutex", () => {
  it("two processes contending on the same clone serialise via a real lock file", async () => {
    const repo = makeRepo();
    const lockPath = orchestratorGitLockPath(repo);
    expect(lockPath).toEqual(expect.stringContaining(".orchestrator-git.lock"));
    if (lockPath === null) throw new Error("expected lock path for real repo");
    const marker = join(repo, "h2-overlap.txt");
    writeFileSync(marker, "");

    const childScript = join(trackTemp("1103-h2-child-"), "child.mjs");
    writeFileSync(
      childScript,
      `
import { appendFileSync, existsSync } from "node:fs";
import { runExclusive, orchestratorGitLockPath } from ${JSON.stringify(
        join(srcRoot, "gitMutex.ts"),
      )};
const repo = ${JSON.stringify(repo)};
const marker = ${JSON.stringify(marker)};
const lockPath = orchestratorGitLockPath(repo);
if (lockPath === null) throw new Error("child: expected lock path");
await runExclusive(repo, async () => {
  appendFileSync(marker, "child-enter\\n");
  if (!existsSync(lockPath)) {
    throw new Error("lock file missing while child holds runExclusive");
  }
  await new Promise((r) => setTimeout(r, 500));
  appendFileSync(marker, "child-exit\\n");
});
`,
      "utf8",
    );

    const childDone = spawnTsx(childScript);
    // Wait until child has entered the critical section (and created the lock).
    const deadline = Date.now() + 10_000;
    for (;;) {
      if (existsSync(marker) && readFileSync(marker, "utf8").includes("child-enter")) {
        break;
      }
      if (Date.now() > deadline) {
        throw new Error("child never entered critical section");
      }
      await new Promise((r) => setTimeout(r, 20));
    }
    expect(existsSync(lockPath)).toBe(true);

    let parentSawLock = false;
    await runExclusive(repo, async () => {
      parentSawLock = existsSync(lockPath);
      // Child must have fully exited before we enter (serialised).
      const body = readFileSync(marker, "utf8");
      expect(body).toContain("child-exit");
      writeFileSync(marker, body + "parent-enter\n");
    });

    const child = await childDone;
    expect(child.status, child.stderr).toBe(0);
    expect(parentSawLock).toBe(true);
    const finalBody = readFileSync(marker, "utf8").trim().split("\n");
    expect(finalBody).toEqual(["child-enter", "child-exit", "parent-enter"]);
  });
});

describe("#1103 H3 ensureGitInfoExclude under lock", () => {
  it("concurrent ensureGitInfoExclude on the same exclude file loses no writes", async () => {
    const repo = makeRepo();
    const patterns = Array.from({ length: 12 }, (_, i) => `.pat-${i}/`);
    const childDir = trackTemp("1103-h3-child-");

    const jobs = patterns.map((pattern) => {
      const script = join(
        childDir,
        `c-${pattern.replace(/[^a-z0-9]/gi, "")}.mjs`,
      );
      writeFileSync(
        script,
        `
import { ensureGitInfoExclude } from ${JSON.stringify(
          join(srcRoot, "gitInfoExclude.ts"),
        )};
ensureGitInfoExclude(${JSON.stringify(repo)}, ${JSON.stringify(pattern)});
`,
        "utf8",
      );
      return spawnTsx(script);
    });

    const results = await Promise.all(jobs);
    for (const r of results) {
      expect(r.status, r.stderr).toBe(0);
    }
    const excludePath = join(repo, ".git", "info", "exclude");
    const body = readFileSync(excludePath, "utf8");
    for (const pattern of patterns) {
      expect(body.split(/\r?\n/)).toContain(pattern);
    }
    // Also exercise same-process sync path once (API smoke).
    ensureGitInfoExclude(repo, ".same-proc/");
    expect(readFileSync(excludePath, "utf8").split(/\r?\n/)).toContain(
      ".same-proc/",
    );
  });
});
