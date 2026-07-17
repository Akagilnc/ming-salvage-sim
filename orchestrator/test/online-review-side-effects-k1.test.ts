/**
 * Correctness K1 — host fail-safe online-review side-effect applicator.
 *
 * Restored from #600 / BASE `onlineReviewSideEffects` after #940 deletion left
 * no working worker replacement: host must apply reply/resolve/deferred cargo
 * before accepting mergeable.
 */

import { describe, expect, it } from "vitest";

import type { Sh } from "../src/familyDriver.js";
import {
  applyVerifySideEffects,
  createDeferredTrackingIssue,
  findOpenDeferredTrackingIssueUrl,
} from "../src/onlineReviewSideEffects.js";

const GITHUB_REPLY_SHAPE = [
  {
    id: 9001,
    body: "ok",
    created_at: "2026-01-01T00:00:00.000Z",
  },
];

describe("#600 / K1 GitHub side effects (host fail-safe applicator)", () => {
  it("createDeferredTrackingIssue uses gh api repos/{repo}/issues", () => {
    const calls: string[] = [];
    let created = false;
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
      if (cmd.includes("state=open")) {
        return created
          ? JSON.stringify([
              {
                title: "defer finding",
                html_url: "https://github.com/o/r/issues/99",
                number: 99,
                created_at: "2026-01-01T00:00:00.000Z",
              },
            ])
          : "[]";
      }
      if (cmd.includes("repos/o/r/issues") && cmd.includes("-f title=")) {
        created = true;
        return "https://github.com/o/r/issues/99";
      }
      return "[]";
    };
    const url = createDeferredTrackingIssue(
      sh,
      "o/r",
      "defer finding",
      "reason text",
    );
    expect(url).toBe("https://github.com/o/r/issues/99");
    expect(calls.filter((c) => c.includes("state=open"))).toHaveLength(2);
    expect(
      calls.some((c) =>
        c.includes(
          "gh api repos/o/r/issues -f title=defer finding -f body=reason text --jq .html_url",
        ),
      ),
    ).toBe(true);
  });

  it("findOpenDeferredTrackingIssueUrl skips PR-shaped issue list rows", () => {
    const sh: Sh = (_file, args) =>
      args.join(" ").includes("state=open")
        ? JSON.stringify([
            {
              title: "defer finding",
              html_url: "https://github.com/o/r/pull/1",
              pull_request: {},
            },
            {
              title: "defer finding",
              html_url: "https://github.com/o/r/issues/99",
              number: 99,
              pull_request: null,
            },
          ])
        : "[]";

    expect(findOpenDeferredTrackingIssueUrl(sh, "o/r", "defer finding")).toBe(
      "https://github.com/o/r/issues/99",
    );
  });

  it("applyVerifySideEffects posts evidence replies and creates defer issues", () => {
    const calls: string[] = [];
    let createdIssue: { title: string; url: string } | undefined;
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
      if (cmd.includes("state=open")) {
        return createdIssue === undefined
          ? "[]"
          : JSON.stringify([
              {
                title: createdIssue.title,
                html_url: createdIssue.url,
                number: 77,
                created_at: "2026-01-01T00:00:00.000Z",
              },
            ]);
      }
      if (cmd.includes("repos/o/r/issues") && cmd.includes("-f title=")) {
        createdIssue = {
          title: args
            .find((arg) => arg.startsWith("title="))!
            .slice("title=".length),
          url: "https://github.com/o/r/issues/77",
        };
        return "https://github.com/o/r/issues/77";
      }
      if (
        cmd.includes("pulls/42/comments") &&
        !cmd.includes("/replies") &&
        !cmd.includes("-f body=")
      ) {
        return "[]";
      }
      if (cmd.includes("/replies")) {
        return JSON.stringify(GITHUB_REPLY_SHAPE);
      }
      return JSON.stringify(GITHUB_REPLY_SHAPE);
    };
    const result = applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      verify: {
        kind: "verify",
        converged: false,
        findingDispositions: [
          {
            identityKey: "t:3",
            threadId: "3",
            action: "defer",
            reason: "needs design",
          },
        ],
        threadReplies: [
          { threadId: "2", body: "rejected: false positive on line 10" },
        ],
      },
    });
    expect(result.deferredIssueUrls).toEqual([
      "https://github.com/o/r/issues/77",
    ]);
    expect(result.repliesPosted.some((r) => r.body.includes("rejected:"))).toBe(
      true,
    );
    expect(
      result.repliesPosted.some((r) => r.body.includes("Tracked issue:")),
    ).toBe(true);
    expect(
      calls.filter((c) =>
        c.includes(
          "gh api repos/o/r/issues -f title=Deferred online review finding: 3 -f body=needs design --jq .html_url",
        ),
      ),
    ).toHaveLength(1);
    expect(
      calls.filter((c) => c.includes("repos/o/r/pulls/42/comments/2/replies")),
    ).toHaveLength(1);
  });

  it("applyVerifySideEffects refuses mismatched caller repo vs PR URL", () => {
    const sh: Sh = () => "[]";
    expect(() =>
      applyVerifySideEffects({
        sh,
        repo: "other/r",
        prUrl: "https://github.com/o/r/pull/1",
        verify: { kind: "verify", converged: true },
      }),
    ).toThrow(/conflicts with PR URL repo/);
  });
});
