/**
 * #936 / #934 ID-002: snapshot dual court deleted.
 * buildIssueSnapshot still shapes host-side IssueSnapshot for audit; writeSnapshot
 * is a production no-op (workers live-fetch issue truth; ledger is durable court).
 */

import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  buildIssueSnapshot,
  RealBackend,
  SNAPSHOT_FILENAME,
  type GhBlockedBy,
  type GhIssueJson,
} from "../../src/realBackend.js";
import type { WorktreeHandle } from "../../src/types.js";

const tmpDirs: string[] = [];
afterEach(() => {
  while (tmpDirs.length > 0) {
    const d = tmpDirs.pop();
    if (d !== undefined) rmSync(d, { recursive: true, force: true });
  }
});

describe("integ-cmr 256 confirm r2 — snapshot dual court deleted (#936)", () => {
  it("buildIssueSnapshot still carries #244 native metadata for host audit", () => {
    const json: GhIssueJson = {
      number: 256,
      title: "Slice: real Backend",
      state: "open",
      author: { login: "Akagilnc" },
      body: "the body",
      labels: [{ name: "ready-for-agent" }, { name: "enhancement" }],
      comments: [
        { author: { login: "Akagilnc" }, body: "## Agent Brief\nimplement #256" },
      ],
    };
    const blockedBy: GhBlockedBy[] = [
      { number: 248, state: "closed" },
      { number: 254, state: "open" },
    ];
    const snapshot = buildIssueSnapshot(
      256,
      json,
      blockedBy,
      /*subIssueCount*/ 3,
      "Akagilnc",
    );
    expect(snapshot.body).toBe("the body");
    expect(snapshot.nativeMeta).toEqual({
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

  it("negative: writeSnapshot is a no-op (no clean-room file written)", async () => {
    const tmp = mkdtempSync(join(tmpdir(), "snap-meta-"));
    tmpDirs.push(tmp);
    const worktree: WorktreeHandle = {
      branch: "feat/issue-256",
      base: "main",
      path: tmp,
    };
    const json: GhIssueJson = {
      number: 256,
      title: "t",
      state: "open",
      author: { login: "Akagilnc" },
      body: "body",
      labels: [],
      comments: [],
    };
    const snapshot = buildIssueSnapshot(256, json, [], 0, "Akagilnc");
    // Call the production no-op without constructing a full RealBackend clone.
    await RealBackend.prototype.writeSnapshot.call(
      {} as RealBackend,
      worktree,
      snapshot,
    );
    expect(readdirSync(tmp)).not.toContain(SNAPSHOT_FILENAME);
  });
});
