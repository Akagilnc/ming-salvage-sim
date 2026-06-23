/**
 * integ-cmr 256 confirm r2 — REAL file-writing-path regression (zero container).
 *
 * contract-completeness (writeSnapshot): #244 S1 names the full snapshot as
 * "body + comments + 最新 Agent Brief 正文 + native metadata". The native
 * metadata (title/state/labels + sub-issue + blocked_by summaries) must be
 * SERIALIZED into the clean-room `.orchestrator-snapshot.json` the container
 * reads locally. The fake backends return a bare snapshot, so only this real
 * write proves the native metadata reaches disk.
 *
 * (The old writeFixFindings face is gone: ADR 0026 2026-06-24 collapsed the
 * per-slice review→fix loop INTO the S2 build worker, so there is no separate
 * fix step the runner delivers findings to — the file helper was removed.)
 */

import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  buildIssueSnapshot,
  RealBackend,
  SNAPSHOT_FILENAME,
  type GhBlockedBy,
  type GhIssueJson,
} from "../src/realBackend.js";
import type { WorktreeHandle } from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const realPromptsDir = join(here, "..", "prompts");

/**
 * Test subclass that stubs the clone seams so construction never touches real
 * git (this test exercises only writeSnapshot, not the clone build).
 */
class FileWriteBackend extends RealBackend {
  // #292: stub the clone seams so construction never touches real git.
  protected override cloneDirExists(): boolean {
    return true;
  }
  protected override sh(file: string, args: string[]): string {
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      return ".git";
    }
    return "";
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
