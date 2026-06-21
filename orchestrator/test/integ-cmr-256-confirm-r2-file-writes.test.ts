/**
 * integ-cmr 256 confirm r2 — REAL file-writing-path regressions (zero container).
 *
 * Two faces the fake-Backend integ tests cover only transitively, pinned here
 * against the REAL RealBackend on-disk helpers (a temp dir, no Docker/LLM/gh):
 *
 *  1. contract-completeness (writeSnapshot): #244 S1 names the full snapshot as
 *     "body + comments + 最新 Agent Brief 正文 + native metadata". The native
 *     metadata (title/state/labels + sub-issue + blocked_by summaries) must be
 *     SERIALIZED into the clean-room `.orchestrator-snapshot.json` the container
 *     reads locally. The fake backends return a bare snapshot, so only this real
 *     write proves the native metadata reaches disk.
 *
 *  2. regression-coverage (writeFixFindings): the r6 escalate-resume test asserts
 *     the resumed coder RECEIVES non-empty findings, but its fake backend never
 *     observes the on-disk `.orchestrator-fix-findings.json`. The behaviour the
 *     bug would have regressed — non-undefined findings ⟹ the file is WRITTEN and
 *     NOT removed (vs. the undefined branch's rmSync) — is pinned here directly
 *     on the real file helper.
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  buildIssueSnapshot,
  FIX_FINDINGS_FILENAME,
  RealBackend,
  SNAPSHOT_FILENAME,
  type GhBlockedBy,
  type GhIssueJson,
} from "../src/realBackend.js";
import type { Finding, WorktreeHandle } from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "prompts");

/**
 * Test subclass that exposes the protected {@link RealBackend.writeFixFindings}
 * (same seam-exposure rationale as the r3 reuse test's `sh` override), so the
 * real on-disk write/delete decision is drivable without a container.
 */
class FileWriteBackend extends RealBackend {
  // #292: stub the clone seams so construction never touches real git (this test
  // exercises only the on-disk write helpers, not the clone build).
  protected override cloneDirExists(): boolean {
    return true;
  }
  protected override sh(file: string, args: string[]): string {
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      return ".git";
    }
    return "";
  }

  callWriteFixFindings(
    worktree: WorktreeHandle,
    findings: ReadonlyArray<Finding> | undefined,
  ): void {
    this.writeFixFindings(worktree, findings);
  }
}

function newBackend(home: string): FileWriteBackend {
  return new FileWriteBackend({
    sourceRepo: "/tmp/source",
    remote: "https://github.com/owner/name.git",
    runKey: 256,
    repo: "owner/name",
    imageName: "img",
    skillsMount: "/tmp/skills",
    promptsDir: realPromptsDir,
    home,
  });
}

function finding(): Finding {
  return {
    severity: "critical",
    action: "fix_now",
    category: "correctness",
    claim_quote: "the loop never converges",
    location: "src/foo.ts:10",
    suggested_fix: "add a guard",
  };
}

let tmp: string;
let worktree: WorktreeHandle;

beforeEach(() => {
  // A plain (non-git) temp dir: excludeFromGit's `git rev-parse` throws and is
  // swallowed best-effort, so the WRITE itself is what these tests observe.
  tmp = mkdtempSync(join(tmpdir(), "orch-filewrite-"));
  worktree = { branch: "feat/x", base: "main", path: tmp };
});

afterEach(() => {
  rmSync(tmp, { recursive: true, force: true });
});

describe("integ-cmr 256 confirm r2 — writeSnapshot serialises the native metadata (contract-completeness)", () => {
  it("writes the #244-named native metadata into the clean-room snapshot file", async () => {
    const json: GhIssueJson = {
      number: 256,
      title: "Slice: real Backend",
      state: "open",
      body: "the body",
      labels: [{ name: "ready-for-agent" }, { name: "enhancement" }],
      comments: [{ body: "## Agent Brief\nimplement #256" }],
    };
    const blockedBy: GhBlockedBy[] = [
      { number: 248, state: "closed" },
      { number: 254, state: "open" },
    ];
    const snapshot = buildIssueSnapshot(256, json, blockedBy, /*subIssueCount*/ 3);

    const backend = newBackend(tmp);
    await backend.writeSnapshot(worktree, snapshot);

    const onDisk = JSON.parse(
      readFileSync(join(tmp, SNAPSHOT_FILENAME), "utf8"),
    );
    // The body/comments/brief still serialize…
    expect(onDisk.body).toBe("the body");
    expect(onDisk.agentBrief).toContain("## Agent Brief");
    // …AND the native metadata #244 names reaches the file the container reads.
    expect(onDisk.nativeMeta).toEqual({
      title: "Slice: real Backend",
      state: "open",
      labels: ["ready-for-agent", "enhancement"],
      subIssueCount: 3,
      blockedBy: [
        { number: 248, state: "closed" },
        { number: 254, state: "open" },
      ],
    });
  });
});

describe("integ-cmr 256 confirm r2 — writeFixFindings real write/delete (regression-coverage)", () => {
  const target = (): string => join(tmp, FIX_FINDINGS_FILENAME);

  it("non-empty findings: the on-disk findings file is WRITTEN with {fix_now:[...]} (not removed)", () => {
    const backend = newBackend(tmp);
    const fixNow = finding();

    // Seed a stale file first to make the no-delete face observable: were the
    // undefined-branch rmSync to run (the r6 bug), the file would vanish.
    writeFileSync(target(), JSON.stringify({ fix_now: ["STALE"] }), "utf8");

    backend.callWriteFixFindings(worktree, [fixNow]);

    expect(existsSync(target())).toBe(true);
    const onDisk = JSON.parse(readFileSync(target(), "utf8"));
    expect(onDisk).toEqual({ fix_now: [fixNow] });
  });

  it("undefined findings: the stale file IS removed (the branch the r6 bug mis-took)", () => {
    const backend = newBackend(tmp);
    writeFileSync(target(), JSON.stringify({ fix_now: ["STALE"] }), "utf8");

    backend.callWriteFixFindings(worktree, undefined);

    // The undefined branch is the LEAK-guard: a non-fix step / lost-findings
    // round clears the file. The r6 bug was reaching THIS branch on an
    // escalate-resume that should have delivered non-empty findings (asserted
    // above). Here we pin the branch's own correct behaviour.
    expect(existsSync(target())).toBe(false);
  });

  it("undefined findings on an absent file is a no-op (force:true never throws)", () => {
    const backend = newBackend(tmp);
    expect(() => backend.callWriteFixFindings(worktree, undefined)).not.toThrow();
    expect(existsSync(target())).toBe(false);
  });
});
