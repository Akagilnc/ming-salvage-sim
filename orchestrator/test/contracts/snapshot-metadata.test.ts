/**
 * #936 / #934 ID-002: snapshot dual court deleted from production Backend path.
 * buildIssueSnapshot remains a pure host-audit shaper for gh JSON.
 */

import { describe, expect, it } from "vitest";
import {
  buildIssueSnapshot,
  RealBackend,
  type GhBlockedBy,
  type GhIssueJson,
} from "../../src/realBackend.js";

describe("integ-cmr 256 confirm r2 — snapshot dual court deleted (#936)", () => {
  it("buildIssueSnapshot still carries #244 native metadata for host audit helpers", () => {
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

  it("negative: RealBackend prototype does not implement dual-court methods", () => {
    const proto = Object.getOwnPropertyNames(RealBackend.prototype);
    expect(proto).not.toContain("fetchIssueSnapshot");
    expect(proto).not.toContain("writeSnapshot");
  });
});
