/**
 * #1103 — shared-.git write class: worktree wreckage self-heal (H1) +
 * cross-process gitMutex (H2) + exclude RMW under the same lock (H3).
 * #1105 R2 — owner-aware lock, fresh index.lock pass-through, self-contained
 * child processes, deterministic H3 contention, coverage gaps.
 *
 * Real git repos + real filesystem only — no mocked FS / no psychic fixtures.
 */

import { execFileSync, spawn } from "node:child_process";
import {
  closeSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import type * as sc from "@ai-hero/sandcastle";

import { ensureGitInfoExclude } from "../../src/gitInfoExclude.js";
import {
  _resetGitMutex,
  isGitMutexHeldInProcess,
  isPidAlive,
  LOCK_STALE_MS,
  mutexMapKey,
  ORCHESTRATOR_GIT_LOCK_NAME,
  orchestratorGitLockPath,
  runExclusive,
  runExclusiveSync,
  tryReclaimStaleLock,
} from "../../src/gitMutex.js";
import {
  clearStaleIndexLock,
  defaultQuarantineOrphansDir,
  healBeforeWorktreeCut,
  INDEX_LOCK_STALE_MS,
  sandcastleWorktreePathForBranch,
  worktreeAdminDirForBranch,
} from "../../src/gitWorktreePreflight.js";
import {
  branchForIssue,
  RealBackend,
} from "../../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const distRoot = join(here, "..", "..", "dist");
const orchRoot = join(here, "..", "..");
const realPromptsDir = join(orchRoot, "prompts");
const realSoulsDir = join(orchRoot, "image", "souls");

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

beforeAll(() => {
  // Child processes import precompiled dist/*.js (no npx/tsx network).
  // Explicit hook timeout: full-orch tsc can outlast Vitest's default 10s in CI.
  // inherit stdio so compiler diagnostics surface on failure (#1105 R7 F3).
  execFileSync(
    process.execPath,
    [join(orchRoot, "node_modules", "typescript", "bin", "tsc"), "-p", "tsconfig.json"],
    { cwd: orchRoot, stdio: "inherit" },
  );
}, 120_000);

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

/** Sandcastle's real on-disk layout (mirrors @ai-hero/sandcastle create()). */
function scWorktreePath(repo: string, branch: string): string {
  return join(repo, ".sandcastle", "worktrees", branch.replace(/\//g, "-"));
}

function spawnNode(
  scriptPath: string,
): Promise<{ status: number | null; stderr: string; stdout: string }> {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [scriptPath], {
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
    // Fixture path from Sandcastle layout; helper only checked for agreement (#1105 A7).
    const wtPath = scWorktreePath(repo, branch);
    expect(sandcastleWorktreePathForBranch(repo, branch)).toBe(wtPath);
    mkdirSync(wtPath, { recursive: true });
    writeFileSync(join(wtPath, "orphan.txt"), "wreckage\n");
    expect(git(repo, "worktree", "list", "--porcelain")).not.toContain(wtPath);

    const quarantineBase = defaultQuarantineOrphansDir(repo);
    healBeforeWorktreeCut(repo, branch);

    // Path cleared for a fresh cut — but content is quarantined, never destroyed.
    expect(existsSync(wtPath)).toBe(false);
    const quarantined = readdirSync(quarantineBase).filter((n) =>
      n.startsWith("feat-issue-1103-"),
    );
    expect(quarantined.length).toBe(1);
    expect(
      readFileSync(join(quarantineBase, quarantined[0]!, "orphan.txt"), "utf8"),
    ).toBe("wreckage\n");
    git(repo, "worktree", "add", "-b", branch, wtPath, "HEAD");
    expect(existsSync(join(wtPath, "README"))).toBe(true);
    expect(git(repo, "worktree", "list", "--porcelain")).toContain(wtPath);
  });

  it("quarantines content-bearing orphans intact (constitution §10 — never rm)", () => {
    const repo = makeRepo();
    const branch = "feat/issue-1103-preserve";
    const wtPath = scWorktreePath(repo, branch);
    mkdirSync(wtPath, { recursive: true });
    writeFileSync(join(wtPath, "worker-uncommitted.ts"), "export const x = 1;\n");
    mkdirSync(join(wtPath, "nested"), { recursive: true });
    writeFileSync(join(wtPath, "nested", "keep.txt"), "precious\n");
    const ledgerQuarantine = join(trackTemp("1103-ledger-"), "quarantine-orphans");

    healBeforeWorktreeCut(repo, branch, undefined, {
      quarantineBaseDir: ledgerQuarantine,
    });

    expect(existsSync(wtPath)).toBe(false);
    const moved = readdirSync(ledgerQuarantine);
    expect(moved).toHaveLength(1);
    const dest = join(ledgerQuarantine, moved[0]!);
    expect(readFileSync(join(dest, "worker-uncommitted.ts"), "utf8")).toBe(
      "export const x = 1;\n",
    );
    expect(readFileSync(join(dest, "nested", "keep.txt"), "utf8")).toBe(
      "precious\n",
    );
  });

  it("NEGATIVE: does not delete an active registered worktree", () => {
    const repo = makeRepo();
    const branch = "feat/issue-1103-live";
    const wtPath = scWorktreePath(repo, branch);
    mkdirSync(dirname(wtPath), { recursive: true });
    git(repo, "worktree", "add", "-b", branch, wtPath, "HEAD");
    writeFileSync(join(wtPath, "keep-me.txt"), "live\n");

    healBeforeWorktreeCut(repo, branch);

    expect(existsSync(join(wtPath, "keep-me.txt"))).toBe(true);
    expect(git(repo, "worktree", "list", "--porcelain")).toContain(wtPath);
  });

  it("leaves a fresh index.lock in place (no throw, no delete)", () => {
    const repo = makeRepo();
    const lockPath = join(repo, ".git", "index.lock");
    writeFileSync(lockPath, "");
    utimesSync(lockPath, new Date(), new Date());
    expect(() => clearStaleIndexLock(repo)).not.toThrow();
    expect(existsSync(lockPath)).toBe(true);
    const branch = "feat/issue-1103-fresh-lock";
    const wtPath = scWorktreePath(repo, branch);
    mkdirSync(dirname(wtPath), { recursive: true });
    git(repo, "worktree", "add", "-b", branch, wtPath, "HEAD");
    expect(existsSync(join(wtPath, "README"))).toBe(true);
  });

  it("reclaims a stale index.lock", () => {
    const repo = makeRepo();
    const lockPath = join(repo, ".git", "index.lock");
    writeFileSync(lockPath, "");
    const old = new Date(Date.now() - INDEX_LOCK_STALE_MS - 1_000);
    utimesSync(lockPath, old, old);
    clearStaleIndexLock(repo);
    expect(existsSync(lockPath)).toBe(false);
  });

  it("heals metadata-present/directory-absent (!dirExists && inList)", () => {
    const repo = makeRepo();
    const branch = "feat/issue-1103-meta-only";
    const wtPath = scWorktreePath(repo, branch);
    mkdirSync(dirname(wtPath), { recursive: true });
    git(repo, "worktree", "add", "-b", branch, wtPath, "HEAD");
    rmSync(wtPath, { recursive: true, force: true });
    expect(git(repo, "worktree", "list", "--porcelain")).toContain(
      branch.replace(/\//g, "-"),
    );

    healBeforeWorktreeCut(repo, branch);

    expect(existsSync(wtPath)).toBe(false);
    git(repo, "worktree", "add", wtPath, "HEAD");
    expect(existsSync(join(wtPath, "README"))).toBe(true);
  });

  it("clears an orphan admin dir when worktree is unlisted", () => {
    const repo = makeRepo();
    const branch = "feat/issue-1103-orphan-admin";
    const admin = worktreeAdminDirForBranch(repo, branch);
    mkdirSync(admin, { recursive: true });
    writeFileSync(join(admin, "HEAD"), "ref: refs/heads/orphan\n");
    expect(existsSync(admin)).toBe(true);

    healBeforeWorktreeCut(repo, branch);

    expect(existsSync(admin)).toBe(false);
  });

  it("NEGATIVE: does not prune a live sibling with a dangling gitdir (#1105 R7 F1)", () => {
    // Wave concurrency: sibling's gitdir was rewritten to a container path the
    // host cannot stat → prunable. Global `git worktree prune` would delete it
    // and kill the sibling mid-run. Heal must only touch the target name.
    const repo = makeRepo();
    const siblingBranch = "feat/issue-1103-sibling";
    const siblingPath = scWorktreePath(repo, siblingBranch);
    mkdirSync(dirname(siblingPath), { recursive: true });
    git(repo, "worktree", "add", "-b", siblingBranch, siblingPath, "HEAD");
    const siblingAdmin = worktreeAdminDirForBranch(repo, siblingBranch);
    writeFileSync(
      join(siblingAdmin, "gitdir"),
      "/sandbox/nonexistent/feat-issue-1103-sibling/.git\n",
    );
    expect(existsSync(siblingAdmin)).toBe(true);
    expect(git(repo, "worktree", "list")).toMatch(/prunable/i);

    const target = "feat/issue-1103-target";
    const targetAdmin = worktreeAdminDirForBranch(repo, target);
    mkdirSync(targetAdmin, { recursive: true });
    writeFileSync(join(targetAdmin, "HEAD"), "ref: refs/heads/orphan\n");

    healBeforeWorktreeCut(repo, target);

    expect(existsSync(targetAdmin)).toBe(false);
    expect(existsSync(siblingAdmin)).toBe(true);
    expect(readFileSync(join(siblingAdmin, "gitdir"), "utf8")).toContain(
      "/sandbox/nonexistent/",
    );
  });

  it("prepareWorktreeLocked wires quarantine to durable .ledger-N (not clone .sandcastle)", async () => {
    // #1105 R6 F1: production heal must land under ledger (survives sandcastle wipe).
    const ISSUE = 1105;
    const source = makeRepo();
    const home = trackTemp("1105-f1-home-");
    class LedgerQuarantineBackend extends RealBackend {
      protected override async createResidentWorktree(
        branch: string,
        _baseBranch: string,
      ): Promise<sc.Worktree> {
        const wtPath = sandcastleWorktreePathForBranch(
          this.workingRepoPath(),
          branch,
        );
        mkdirSync(wtPath, { recursive: true });
        writeFileSync(join(wtPath, "README"), "fresh-cut\n");
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
    const backend = new LedgerQuarantineBackend({
      sourceRepo: source,
      runKey: ISSUE,
      repo: "owner/name",
      imageName: "img",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      home,
    });
    const clone = backend.workingRepoPath();
    const branch = branchForIssue(ISSUE);
    const orphanPath = sandcastleWorktreePathForBranch(clone, branch);
    mkdirSync(orphanPath, { recursive: true });
    writeFileSync(join(orphanPath, "precious.ts"), "keep-me\n");

    await backend.prepareWorktree(ISSUE, "main");

    const ledgerQ = join(clone, `.ledger-${ISSUE}`, "quarantine-orphans");
    const cloneQ = defaultQuarantineOrphansDir(clone);
    expect(existsSync(cloneQ) ? readdirSync(cloneQ) : []).toEqual([]);
    const moved = readdirSync(ledgerQ);
    expect(moved).toHaveLength(1);
    expect(
      readFileSync(join(ledgerQ, moved[0]!, "precious.ts"), "utf8"),
    ).toBe("keep-me\n");
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
        join(distRoot, "gitMutex.js"),
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

    const childDone = spawnNode(childScript);
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

  it("async holder does not let a concurrent sync child pierce the lock", async () => {
    const repo = makeRepo();
    const marker = join(repo, "pierce-order.txt");
    writeFileSync(marker, "");
    const childScript = join(trackTemp("1103-pierce-"), "sync-child.mjs");
    writeFileSync(
      childScript,
      `
import { appendFileSync, existsSync } from "node:fs";
import { runExclusiveSync } from ${JSON.stringify(join(distRoot, "gitMutex.js"))};
const repo = ${JSON.stringify(repo)};
const marker = ${JSON.stringify(marker)};
const gate = ${JSON.stringify(join(repo, "pierce-gate"))};
const deadline = Date.now() + 10_000;
while (!existsSync(gate)) {
  if (Date.now() > deadline) throw new Error("pierce gate timeout");
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
}
runExclusiveSync(repo, () => {
  appendFileSync(marker, "sync-enter\\n");
  appendFileSync(marker, "sync-exit\\n");
});
`,
      "utf8",
    );

    const childDone = spawnNode(childScript);
    await runExclusive(repo, async () => {
      writeFileSync(marker, "async-enter\n");
      // Release the child; it must block on the file lock until we exit.
      closeSync(openSync(join(repo, "pierce-gate"), "w"));
      await new Promise((r) => setTimeout(r, 300));
      expect(readFileSync(marker, "utf8")).toBe("async-enter\n");
      writeFileSync(marker, "async-enter\nasync-exit\n");
    });

    const child = await childDone;
    expect(child.status, child.stderr).toBe(0);
    expect(readFileSync(marker, "utf8").trim().split("\n")).toEqual([
      "async-enter",
      "async-exit",
      "sync-enter",
      "sync-exit",
    ]);
  });

  it("same-process async holder + runExclusiveSync fail-fasts (no Atomics.wait deadlock)", async () => {
    const repo = makeRepo();
    let syncError: unknown;
    await runExclusive(repo, async () => {
      expect(isGitMutexHeldInProcess(repo)).toBe(true);
      try {
        runExclusiveSync(repo, () => {
          throw new Error("sync must not enter under async hold");
        });
      } catch (err) {
        syncError = err;
      }
      // Yield so a waiting Atomics.wait would have deadlocked the holder.
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(syncError).toBeInstanceOf(Error);
    expect(String(syncError)).toMatch(/fail-fast/);
    expect(isGitMutexHeldInProcess(repo)).toBe(false);
  });

  it("holder timer inheriting ALS must not pierce the lock", async () => {
    const repo = makeRepo();
    let timerEntered = false;
    let timerError: unknown;
    await runExclusive(repo, async () => {
      await new Promise<void>((resolve) => {
        setTimeout(() => {
          try {
            runExclusiveSync(repo, () => {
              timerEntered = true;
            });
          } catch (err) {
            timerError = err;
          }
          resolve();
        }, 10);
      });
    });
    expect(timerEntered).toBe(false);
    expect(timerError).toBeInstanceOf(Error);
    expect(String(timerError)).toMatch(/fail-fast/);
  });

  it("same-owner sync nesting is reentrant; nested section observes the lock", () => {
    const repo = makeRepo();
    const lockPath = orchestratorGitLockPath(repo);
    if (lockPath === null) throw new Error("expected lock");
    // Sync-within-sync only — async no longer publishes ALS for nesting.
    runExclusiveSync(repo, () => {
      expect(existsSync(lockPath)).toBe(true);
      runExclusiveSync(repo, () => {
        expect(existsSync(lockPath)).toBe(true);
      });
      expect(existsSync(lockPath)).toBe(true);
    });
    expect(existsSync(lockPath)).toBe(false);
  });

  it("linked worktree path and clone root share one mutexMapKey (common-dir)", () => {
    const repo = makeRepo();
    const branch = "feat/issue-1103-link";
    const wtPath = join(repo, "linked-wt");
    git(repo, "worktree", "add", "-b", branch, wtPath, "HEAD");
    expect(mutexMapKey(wtPath)).toBe(mutexMapKey(repo));
    expect(orchestratorGitLockPath(wtPath)).toBe(orchestratorGitLockPath(repo));
  });

  it("isPidAlive treats missing pid as dead and live pid as alive", () => {
    expect(isPidAlive(process.pid)).toBe(true);
    expect(isPidAlive(0)).toBe(false);
    expect(isPidAlive(-1)).toBe(false);
  });

  it("tryReclaimStaleLock refuses a live pid and reclaims a dead stale lock", () => {
    const repo = makeRepo();
    const lockDir = orchestratorGitLockPath(repo);
    if (lockDir === null) throw new Error("expected lock path");
    mkdirSync(lockDir);
    writeFileSync(join(lockDir, "pid"), `${process.pid}\n`);
    writeFileSync(join(lockDir, "owner"), "tok-live\n");
    const old = new Date(Date.now() - LOCK_STALE_MS - 1_000);
    utimesSync(lockDir, old, old);
    expect(tryReclaimStaleLock(lockDir, Date.now())).toBe(false);
    expect(existsSync(lockDir)).toBe(true);

    writeFileSync(join(lockDir, "pid"), "99999999\n");
    writeFileSync(join(lockDir, "owner"), "tok-dead\n");
    utimesSync(lockDir, old, old);
    expect(tryReclaimStaleLock(lockDir, Date.now())).toBe(true);
    expect(existsSync(lockDir)).toBe(false);
  });

  it("half-created lock dir (mkdir, no owner) is reclaimable when stale so waiters are not stuck", async () => {
    const repo = makeRepo();
    const lockDir = orchestratorGitLockPath(repo);
    if (lockDir === null) throw new Error("expected lock path");
    mkdirSync(lockDir);
    // No pid/owner — A5 prevents this on the write-fail path; stale reclaim
    // is the backstop if a crash still leaves the dir.
    const old = new Date(Date.now() - LOCK_STALE_MS - 1_000);
    utimesSync(lockDir, old, old);
    expect(tryReclaimStaleLock(lockDir, Date.now())).toBe(true);
    await runExclusive(repo, async () => {
      expect(existsSync(lockDir)).toBe(true);
    });
    expect(existsSync(lockDir)).toBe(false);
  });

  it("reclaim race: two reclaimers interleave — at most one deletes, loser restores or yields", () => {
    const repo = makeRepo();
    const lockDir = orchestratorGitLockPath(repo);
    if (lockDir === null) throw new Error("expected lock path");
    mkdirSync(lockDir);
    writeFileSync(join(lockDir, "pid"), "99999999\n");
    writeFileSync(join(lockDir, "owner"), "tok-race\n");
    const old = new Date(Date.now() - LOCK_STALE_MS - 1_000);
    utimesSync(lockDir, old, old);

    // Simulate interleaving: first reclaimer renames away; second sees absence.
    const reclaimA = `${lockDir}.reclaim.a`;
    renameSync(lockDir, reclaimA);
    expect(tryReclaimStaleLock(lockDir, Date.now())).toBe(false);
    // Loser must not destroy the claimed tree — reclaimA still holds the lock payload.
    expect(existsSync(reclaimA)).toBe(true);
    expect(readFileSync(join(reclaimA, "owner"), "utf8")).toBe("tok-race\n");
    // Put claimed path back under a fresh stale name and let one reclaim win.
    renameSync(reclaimA, lockDir);
    utimesSync(lockDir, old, old);
    const first = tryReclaimStaleLock(lockDir, Date.now());
    const second = tryReclaimStaleLock(lockDir, Date.now());
    expect(first).toBe(true);
    expect(second).toBe(false);
    expect(existsSync(lockDir)).toBe(false);
  });

  it("revalidate failure after rename restores lock (EISDIR pid) — fail-closed", () => {
    // #1105 R6 F2: post-claim read/stat exceptions must restore, never delete.
    const repo = makeRepo();
    const lockDir = orchestratorGitLockPath(repo);
    if (lockDir === null) throw new Error("expected lock path");
    mkdirSync(lockDir);
    // `pid` as a directory → readFileSync throws EISDIR (not ENOENT half-created).
    mkdirSync(join(lockDir, "pid"));
    writeFileSync(join(lockDir, "owner"), "tok-bad-pid\n");
    const old = new Date(Date.now() - LOCK_STALE_MS - 1_000);
    utimesSync(lockDir, old, old);

    expect(tryReclaimStaleLock(lockDir, Date.now())).toBe(false);
    expect(existsSync(lockDir)).toBe(true);
    expect(existsSync(join(lockDir, "owner"))).toBe(true);
    expect(readFileSync(join(lockDir, "owner"), "utf8")).toBe("tok-bad-pid\n");
    // No orphan .reclaim.* left behind after conservative restore.
    const siblings = readdirSync(dirname(lockDir)).filter((n) =>
      n.startsWith(`${ORCHESTRATOR_GIT_LOCK_NAME}.reclaim.`),
    );
    expect(siblings).toEqual([]);
  });
});

describe("#1103 H3 ensureGitInfoExclude under lock", () => {
  it("concurrent ensureGitInfoExclude on the same exclude file loses no writes", async () => {
    const repo = makeRepo();
    // High fan-out + start barrier so lost-write races are deterministic (#1105 A7).
    const patterns = Array.from({ length: 32 }, (_, i) => `.pat-${i}/`);
    const childDir = trackTemp("1103-h3-child-");
    const gate = join(childDir, "start-gate");

    const jobs = patterns.map((pattern, i) => {
      const script = join(childDir, `c-${i}.mjs`);
      writeFileSync(
        script,
        `
import { existsSync } from "node:fs";
import { ensureGitInfoExclude } from ${JSON.stringify(
          join(distRoot, "gitInfoExclude.js"),
        )};
const gate = ${JSON.stringify(gate)};
const deadline = Date.now() + 15_000;
while (!existsSync(gate)) {
  if (Date.now() > deadline) throw new Error("start gate timeout");
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 5);
}
ensureGitInfoExclude(${JSON.stringify(repo)}, ${JSON.stringify(pattern)});
`,
        "utf8",
      );
      return spawnNode(script);
    });

    await new Promise((r) => setTimeout(r, 200));
    closeSync(openSync(gate, "w"));

    const results = await Promise.all(jobs);
    for (const r of results) {
      expect(r.status, r.stderr).toBe(0);
    }
    const excludePath = join(repo, ".git", "info", "exclude");
    const body = readFileSync(excludePath, "utf8");
    for (const pattern of patterns) {
      expect(body.split(/\r?\n/)).toContain(pattern);
    }
    ensureGitInfoExclude(repo, ".same-proc/");
    expect(readFileSync(excludePath, "utf8").split(/\r?\n/)).toContain(
      ".same-proc/",
    );
  });
});
