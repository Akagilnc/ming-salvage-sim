/**
 * #600 — online review-loop: bot polling + evidence + CI classification pins.
 * Host poll/retrigger/side-effect dual-owner path deleted in #1145; pins here
 * cover production symbols still owned by botPolling / evidenceAdmissibility /
 * Landing (`pollPrReviewState`) / autoMerge (`classifyCheckRuns`).
 */

import { describe, expect, it } from "vitest";
import type { OnlineReviewLandingSnapshot } from "../src/types.js";
import type { PrReviewSnapshot } from "../src/botPolling.js";
import {
  BOT_OVERDUE_POLL_COUNT,
  BOT_OVERDUE_MIN_WALL_MS,
  BOT_POLL_INTERVAL_MS,
  botOverdueWallClockMs,
  checkRunsConverged,
  classifyCheckRuns,
  ONLINE_REVIEW_BOT_IDS,
  ONLINE_REVIEW_BOT_LOGINS,
  ONLINE_REVIEW_BOT_RETRIGGER_COMMENT,
  paginateReviewThreadNodes,
  parsePrRef,
  pollPrReviewState,
} from "../src/botPolling.js";
import {
  assertOfflineSyntheticPollAdmissible,
  buildRoundTrigger,
  classifyEvidenceFreshness,
  convergenceHeadToRecord,
  evidenceAdmissible,
  offlineSyntheticPollAdmissible,
} from "../src/evidenceAdmissibility.js";
import type { Sh } from "../src/familyDriver.js";
import { familyReviewLoopConvergedForHead } from "../src/family/ledger.js";

/** Snapshot → opaque collector evidence (test-only; host toLandingSnapshot deleted). */
function evidenceFromSnapshot(snap: PrReviewSnapshot): OnlineReviewLandingSnapshot {
  return {
    prUrl: snap.prUrl,
    headOid: snap.headOid,
    totalFindingCount: snap.totalFindingCount,
    quiescent: snap.quiescent,
    bots: snap.bots,
    droppedBots: ONLINE_REVIEW_BOT_IDS.filter(
      (bot) => snap.bots[bot].state === "dropped",
    ),
    threads: snap.threads.map((t) => ({
      id: t.id,
      threadNodeId: t.threadNodeId,
      path: t.path,
      line: t.line,
      body: t.body,
      isResolved: t.isResolved,
      headOid: t.headOid,
      authorLogin: t.authorLogin,
    })),
    checkRuns: snap.checkRuns,
    checkRunsEmptyMeans: snap.checkRunsEmptyMeans,
  };
}

function ghFixture(input: { calls: string[] }): Sh {
  return (file, args) => {
    input.calls.push(`${file} ${args.join(" ")}`);
    const cmd = args.join(" ");
    if (cmd.includes("pulls/42") && cmd.includes("repos/o/r/pulls/42") && !cmd.includes("comments") && !cmd.includes("reviews")) {
      return JSON.stringify({
        head: { sha: "headsha1" },
        html_url: "https://github.com/o/r/pull/42",
      });
    }
    if (cmd.includes("issues/42/comments") || cmd.includes("pulls/42/comments")) {
      // GitHub REST issue/PR comments expose `user.login`, not `author.login`.
      // https://docs.github.com/en/rest/pulls/comments?apiVersion=2022-11-28
      return JSON.stringify([
        {
          user: { login: "coderabbitai[bot]" },
          body: "Summary: one nit on line 10",
          created_at: FRESH_BOT_TIMESTAMP,
        },
      ]);
    }
    if (cmd.includes("check-runs")) {
      return JSON.stringify({
        check_runs: [
          {
            id: 1,
            name: "ci",
            head_sha: "headsha1",
            status: "completed",
            conclusion: "success",
          },
        ],
      });
    }
    if (cmd.includes("repos/o/r/issues/42/reactions")) {
      return "[]";
    }
    if (
      (cmd.includes("pulls/comments/") || cmd.includes("issues/comments/")) &&
      cmd.includes("/reactions")
    ) {
      return "[]";
    }
    if (cmd.includes("pulls/42/reviews")) {
      return JSON.stringify([
        {
          user: { login: "chatgpt-codex-connector[bot]" },
          state: "COMMENTED",
          submitted_at: FRESH_BOT_TIMESTAMP,
        },
      ]);
    }
    if (cmd.includes("graphql") && cmd.includes("reviewThreads")) {
      return JSON.stringify({
        data: {
          repository: {
            pullRequest: {
              reviewThreads: {
                pageInfo: { endCursor: "cursor-single-page", hasNextPage: false },
                nodes: [
                  {
                    id: "PRRT_kwDOExampleThread",
                    isResolved: false,
                    comments: {
                      nodes: [
                        {
                          databaseId: 4242,
                          body: "top-level review comment",
                          path: "src/a.ts",
                          line: 10,
                          author: { login: "coderabbitai[bot]" },
                        },
                      ],
                    },
                  },
                  {
                    id: "PRRT_kwDOReplyOnly",
                    isResolved: false,
                    comments: {
                      nodes: [
                        {
                          databaseId: 4243,
                          body: "reply on thread",
                          path: "src/a.ts",
                          line: 10,
                          author: { login: "human" },
                          commit: { oid: "headsha1" },
                        },
                      ],
                    },
                  },
                ],
              },
            },
          },
        },
      });
    }
    if (cmd.includes("issues/42/comments") && cmd.includes("-f")) {
      return JSON.stringify({
        id: 9001,
        body: "posted",
        user: { login: "orchestrator-host" },
      });
    }
    return reviewThreadsGraphqlFallback(cmd) ?? "[]";
  };
}

const EMPTY_REVIEW_THREADS_GRAPHQL = JSON.stringify({
  data: {
    repository: {
      pullRequest: {
        reviewThreads: {
          pageInfo: { endCursor: "", hasNextPage: false },
          nodes: [],
        },
      },
    },
  },
});

function reviewThreadsGraphqlFallback(cmd: string): string | undefined {
  if (cmd.includes("graphql") && cmd.includes("reviewThreads")) {
    return EMPTY_REVIEW_THREADS_GRAPHQL;
  }
  return undefined;
}

const FRESH_BOT_TIMESTAMP = "2026-07-08T12:00:00.000Z";
const TEST_ROUND_TRIGGER = buildRoundTrigger(
  "headsha1",
  "2026-07-08T11:00:00.000Z",
);

describe("#600 botPolling — parsePrRef + paginated gh api", () => {
  it("keeps every exact-match bot login lowercase", () => {
    for (const logins of Object.values(ONLINE_REVIEW_BOT_LOGINS)) {
      for (const login of logins) {
        expect(login).toBe(login.toLowerCase());
      }
    }
  });

  it("parses a full GitHub PR URL", () => {
    expect(
      parsePrRef("https://github.com/o/r/pull/42", "fallback/r"),
    ).toEqual({ repo: "o/r", prNumber: 42 });
  });

  it("paginateReviewThreadNodes collects all threads across GraphQL cursor pages (#600 AC2)", () => {
    const calls: string[] = [];
    let graphqlPage = 0;
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
      if (cmd.includes("graphql") && cmd.includes("reviewThreads")) {
        graphqlPage += 1;
        if (graphqlPage === 1) {
          return JSON.stringify({
            data: {
              repository: {
                pullRequest: {
                  reviewThreads: {
                    pageInfo: { endCursor: "cursor-page-1", hasNextPage: true },
                    nodes: [
                      {
                        id: "PRRT_page1_a",
                        isResolved: false,
                        comments: { nodes: [{ databaseId: 1001 }] },
                      },
                      {
                        id: "PRRT_page1_b",
                        isResolved: false,
                        comments: { nodes: [{ databaseId: 1002 }] },
                      },
                    ],
                  },
                },
              },
            },
          });
        }
        return JSON.stringify({
          data: {
            repository: {
              pullRequest: {
                reviewThreads: {
                  pageInfo: { endCursor: "cursor-page-2", hasNextPage: false },
                  nodes: [
                    {
                      id: "PRRT_page2_a",
                      isResolved: true,
                      comments: { nodes: [{ databaseId: 1003 }] },
                    },
                  ],
                },
              },
            },
          },
        });
      }
      return "[]";
    };
    const nodes = paginateReviewThreadNodes(
      sh,
      "o/r",
      42,
      "id isResolved comments(first:1){nodes{databaseId}}",
      2,
    );
    expect(nodes).toHaveLength(3);
    expect(nodes.map((n) => n.comments?.nodes?.[0]?.databaseId)).toEqual([
      1001, 1002, 1003,
    ]);
    expect(graphqlPage).toBe(2);
    expect(calls.some((c) => c.includes("after=cursor-page-1"))).toBe(true);
  });

  it("pin r32: malformed GraphQL page mid-pagination fails closed (not silent truncation)", () => {
    let graphqlPage = 0;
    const sh: Sh = () => {
      graphqlPage += 1;
      if (graphqlPage === 1) {
        return JSON.stringify({
          data: {
            repository: {
              pullRequest: {
                reviewThreads: {
                  pageInfo: { endCursor: "cursor-page-1", hasNextPage: true },
                  nodes: [{ id: "PRRT_page1_a", isResolved: false }],
                },
              },
            },
          },
        });
      }
      return JSON.stringify({
        data: {
          repository: {
            pullRequest: {
              reviewThreads: {
                pageInfo: { endCursor: "", hasNextPage: true },
                nodes: [{ id: "PRRT_page2_a", isResolved: false }],
              },
            },
          },
        },
      });
    };
    expect(() =>
      paginateReviewThreadNodes(sh, "o/r", 42, "id isResolved"),
    ).toThrow(/hasNextPage without endCursor/);
  });

  it("pin r32: clean terminal GraphQL page with empty nodes ends pagination", () => {
    const sh: Sh = () =>
      JSON.stringify({
        data: {
          repository: {
            pullRequest: {
              reviewThreads: {
                pageInfo: { endCursor: "cursor-last", hasNextPage: false },
                nodes: [],
              },
            },
          },
        },
      });
    expect(paginateReviewThreadNodes(sh, "o/r", 42, "id isResolved")).toEqual(
      [],
    );
  });

  it("#1016: reviewThreads GraphQL query closes 4 outer scopes (brace-balanced, not +1 extra })", () => {
    // Real ship post-#985: gh api graphql rejects a query with one extra trailing `}`.
    // Nesting is query / repository / pullRequest / reviewThreads (pageInfo + nodes self-close).
    // Known-good literal (independent of production join): 6 opens / 6 closes.
    const expectedQuery =
      "query($owner:String!,$name:String!,$number:Int!,$first:Int!,$after:String){" +
      "repository(owner:$owner,name:$name){" +
      "pullRequest(number:$number){" +
      "reviewThreads(first:$first,after:$after){" +
      "pageInfo{endCursor hasNextPage}" +
      "nodes{id isResolved}" +
      "}}}}";
    let capturedQuery: string | undefined;
    const sh: Sh = (_file, args) => {
      const queryArg = args.find((a) => a.startsWith("query="));
      if (queryArg !== undefined) {
        capturedQuery = queryArg.slice("query=".length);
      }
      return JSON.stringify({
        data: {
          repository: {
            pullRequest: {
              reviewThreads: {
                pageInfo: { endCursor: "c1", hasNextPage: false },
                nodes: [{ id: "PRRT_ok", isResolved: false }],
              },
            },
          },
        },
      });
    };
    // nodesFields without nested braces so outer close count is unambiguous.
    const nodes = paginateReviewThreadNodes(sh, "o/r", 42, "id isResolved");
    expect(nodes).toHaveLength(1);
    expect(capturedQuery).toBe(expectedQuery);
    const query = capturedQuery!;
    const open = (query.match(/\{/g) ?? []).length;
    const close = (query.match(/\}/g) ?? []).length;
    expect(open).toBe(close);
    // nodes self-close contributes 1 trailing `}` + 4 outer closers = 5 consecutive.
    // Pre-#1016 bug appended a 5th outer closer → 6 consecutive (and open !== close).
    expect((query.match(/\}+$/)?.[0] ?? "").length).toBe(5);
  });

  it("#1016: GraphQL errors on reviewThreads still fail closed (no silent 0 threads)", () => {
    const sh: Sh = () =>
      JSON.stringify({
        errors: [{ message: "Expected end of document, found }" }],
      });
    expect(() =>
      paginateReviewThreadNodes(sh, "o/r", 42, "id isResolved"),
    ).toThrow(/GraphQL reviewThreads errors/);
  });

  it("pollPrReviewState threads use GraphQL top comment id distinct from threadNodeId (#600 r7)", () => {
    const calls: string[] = [];
    const sh = ghFixture({ calls });
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    expect(snap.threads).toHaveLength(2);
    const thread = snap.threads[0]!;
    expect(thread.id).toBe("4242");
    expect(thread.threadNodeId).toBe("PRRT_kwDOExampleThread");
    expect(thread.id).not.toBe(thread.threadNodeId);
    expect(thread.isResolved).toBe(false);
    expect(calls.some((c) => c.includes("graphql") && c.includes("reviewThreads"))).toBe(
      true,
    );
  });

  it("pin r24: poll snapshot threads carry path/line for collector evidence", () => {
    const calls: string[] = [];
    const sh = ghFixture({ calls });
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    const evidence = evidenceFromSnapshot(snap);
    expect(evidence.threads?.[0]).toEqual(
      expect.objectContaining({
        id: "4242",
        threadNodeId: "PRRT_kwDOExampleThread",
        path: "src/a.ts",
        line: 10,
      }),
    );
  });

  it("pollPrReviewState collects bot legs and marks quiescent when all complete/dropped", () => {
    const calls: string[] = [];
    const sh = ghFixture({ calls });
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    expect(snap.headOid).toBe("headsha1");
    expect(snap.checkRuns).toEqual([
      expect.objectContaining({ name: "ci", headSha: "headsha1" }),
    ]);
    expect(snap.quiescent).toBe(false);
    expect(ONLINE_REVIEW_BOT_IDS.every((b) => snap.bots[b] !== undefined)).toBe(
      true,
    );
    expect(calls.some((c) => c.includes("per_page=100"))).toBe(true);
  });

  it("pin online R2/R4 Codex: mid-round head drift re-anchors trigger for bot evidence", () => {
    // PR head is NEW; bot comments have no commit_id and timestamp after OLD
    // trigger but before re-anchor nowIso → must NOT mark bots complete.
    const OLD_TS = "2026-07-01T00:00:00.000Z";
    const BETWEEN_TS = "2026-07-01T12:00:00.000Z";
    const NOW_TS = "2026-07-09T12:00:00.000Z";
    const NEW_HEAD = "newheadsha11111111111111111111111111111";
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews")
      ) {
        return JSON.stringify({
          head: { sha: NEW_HEAD },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("graphql") && cmd.includes("reviewThreads")) {
        return JSON.stringify({
          data: {
            repository: {
              pullRequest: {
                reviewThreads: {
                  pageInfo: { endCursor: "c1", hasNextPage: false },
                  nodes: [],
                },
              },
            },
          },
        });
      }
      if (cmd.includes("issues/42/comments") || cmd.includes("pulls/42/comments")) {
        return JSON.stringify([
          {
            user: { login: "coderabbitai[bot]" },
            body: "Summary: review complete",
            created_at: BETWEEN_TS,
          },
          {
            user: { login: "sourcery-ai[bot]" },
            body: "Sourcery review complete",
            created_at: BETWEEN_TS,
          },
          {
            user: { login: "gemini-code-assist[bot]" },
            body: "Gemini review complete",
            created_at: BETWEEN_TS,
          },
        ]);
      }
      if (cmd.includes("pulls/42/reviews")) {
        return JSON.stringify([
          {
            user: { login: "chatgpt-codex-connector[bot]" },
            state: "COMMENTED",
            submitted_at: BETWEEN_TS,
            body: "Codex review complete",
          },
        ]);
      }
      if (cmd.includes("check-runs")) {
        return JSON.stringify({ check_runs: [] });
      }
      if (cmd.includes("reactions")) return "[]";
      return "[]";
    };
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: buildRoundTrigger("old-head-sha", OLD_TS),
      nowIso: NOW_TS,
    });
    expect(snap.headOid).toBe(NEW_HEAD);
    expect(snap.roundTriggerUsed.headOid).toBe(NEW_HEAD);
    expect(snap.roundTriggerUsed.triggeredAt).toBe(NOW_TS);
    for (const bot of ONLINE_REVIEW_BOT_IDS) {
      expect(snap.bots[bot].state).not.toBe("complete");
    }
  });

  it("pin online R5 Codex P1: chained poll reuses re-anchored trigger (no re-now)", () => {
    const OLD_TS = "2026-07-01T00:00:00.000Z";
    const HEAD1 = "head1111111111111111111111111111111111111";
    const HEAD_OLD = "head0000000000000000000000000000000000000";
    const emptyGql = JSON.stringify({
      data: {
        repository: {
          pullRequest: {
            reviewThreads: {
              pageInfo: { endCursor: "c1", hasNextPage: false },
              nodes: [],
            },
          },
        },
      },
    });
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      // graphql before reviews — "reviewThreads" contains "reviews"
      if (cmd.includes("graphql") && cmd.includes("reviewThreads")) {
        return emptyGql;
      }
      if (
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews")
      ) {
        return JSON.stringify({
          head: { sha: HEAD1 },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") || cmd.includes("pulls/42/comments")) {
        return "[]";
      }
      if (cmd.includes("pulls/42/reviews")) return "[]";
      if (cmd.includes("check-runs")) {
        return JSON.stringify({ check_runs: [] });
      }
      if (cmd.includes("reactions")) return "[]";
      return "[]";
    };
    const first = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: buildRoundTrigger(HEAD_OLD, OLD_TS),
      nowIso: "2026-07-09T12:00:00.000Z",
    });
    expect(first.roundTriggerUsed.headOid).toBe(HEAD1);
    expect(first.roundTriggerUsed.triggeredAt).toBe("2026-07-09T12:00:00.000Z");

    // Second poll must pass first.roundTriggerUsed — if wrongly re-anchored with a
    // newer now, triggeredAt would change even when head is stable.
    const second = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 2,
      roundTrigger: first.roundTriggerUsed,
      nowIso: "2026-07-09T12:05:00.000Z",
    });
    expect(second.roundTriggerUsed.headOid).toBe(HEAD1);
    expect(second.roundTriggerUsed.triggeredAt).toBe(
      first.roundTriggerUsed.triggeredAt,
    );
    expect(second.roundTriggerUsed.triggeredAt).not.toBe("2026-07-09T12:05:00.000Z");
  });

  it("drops a bot after the overdue poll window", () => {
    const sh = ghFixture({ calls: [] });
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: BOT_OVERDUE_POLL_COUNT,
      roundTrigger: TEST_ROUND_TRIGGER,
      botPendingPolls: { gemini: BOT_OVERDUE_POLL_COUNT },
    });
    expect(snap.bots.gemini.state).toBe("dropped");
    expect(snap.quiescent).toBe(true);
    expect(
      ONLINE_REVIEW_BOT_IDS.some((bot) => snap.bots[bot].state === "dropped"),
    ).toBe(true);
    expect(
      ONLINE_REVIEW_BOT_IDS.filter((bot) => snap.bots[bot].state === "dropped"),
    ).toContain("gemini");
  });

  it("pin overdue constants: N = ceil(15m/interval)+1 so wall clock cannot be mis-counted", () => {
    expect(BOT_POLL_INTERVAL_MS).toBe(120_000);
    expect(BOT_OVERDUE_MIN_WALL_MS).toBe(15 * 60_000);
    expect(BOT_OVERDUE_POLL_COUNT).toBe(
      Math.ceil(BOT_OVERDUE_MIN_WALL_MS / BOT_POLL_INTERVAL_MS) + 1,
    );
    expect(BOT_OVERDUE_POLL_COUNT).toBe(9);
    // sleeps before drop
    expect(BOT_OVERDUE_POLL_COUNT - 1).toBe(8);
    expect(botOverdueWallClockMs(9)).toBe(16 * 60_000);
    expect(botOverdueWallClockMs(1)).toBe(0);
    expect(botOverdueWallClockMs(0)).toBe(0);
    // Regression: N=8 would only sleep 7×2m = 14m (< 15m).
    expect(botOverdueWallClockMs(8)).toBeLessThan(BOT_OVERDUE_MIN_WALL_MS);
  });

  it("marks a zero-finding bot review as complete (not pending/dropped)", () => {
    const sh: Sh = (file, args) => {
      const cmd = args.join(" ");
      if (cmd.includes("pulls/42") && cmd.includes("repos/o/r/pulls/42") && !cmd.includes("comments") && !cmd.includes("reviews")) {
        return JSON.stringify({
          head: { sha: "headsha1" },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") || cmd.includes("pulls/42/comments")) {
        return "[]";
      }
      if (cmd.includes("check-runs")) {
        return JSON.stringify({ check_runs: [] });
      }
      if (cmd.includes("pulls/42/reviews")) {
        return JSON.stringify([
          {
            user: { login: "gemini-code-assist[bot]" },
            state: "APPROVED",
            submitted_at: FRESH_BOT_TIMESTAMP,
          },
        ]);
      }
      if (
        (cmd.includes("pulls/comments/") || cmd.includes("issues/comments/")) &&
        cmd.includes("/reactions")
      ) {
        return "[]";
      }
      return reviewThreadsGraphqlFallback(cmd) ?? "[]";
    };
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    expect(snap.bots.gemini).toEqual({ state: "complete", findingCount: 0 });
    expect(snap.bots.gemini.state).not.toBe("pending");
    expect(snap.bots.gemini.state).not.toBe("dropped");
  });

  it("pollPrReviewState failures fail closed (no empty-green snapshot)", () => {
    const sh: Sh = () => {
      throw new Error("gh api failed");
    };
    expect(() =>
      pollPrReviewState(sh, {
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        pollCount: 1,
        roundTrigger: TEST_ROUND_TRIGGER,
      }),
    ).toThrow(/gh api failed/);
  });

});

describe("#600 stale head + artifact bot freshness (#600 AC3)", () => {
  it("threads without native headOid are not coerced to current head", () => {
    const calls: string[] = [];
    const sh = ghFixture({ calls });
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    // Native head absent → not fresh for current head (Collector judges; host helper gone).
    expect(snap.threads[0]?.headOid).toBeUndefined();
    expect(snap.threads[0]?.headOid === snap.headOid).toBe(false);
  });

  it("stale prior-head thread is not counted fresh", () => {
    const stale = {
      id: "9",
      threadNodeId: "PRRT_stale",
      body: "old nit",
      authorLogin: "bot",
      isResolved: false,
      headOid: "oldhead0000000000000000000000000000000000",
    };
    // Production gate: head-bearing evidence uses SHA equality (host isThreadEvidenceFresh deleted).
    expect(
      classifyEvidenceFreshness(
        { headOid: stale.headOid },
        "headsha1",
        TEST_ROUND_TRIGGER,
      ),
    ).toBe("stale");
    expect(
      evidenceAdmissible(
        { terminalState: "fresh_live", headOid: stale.headOid },
        "headsha1",
        TEST_ROUND_TRIGGER,
      ),
    ).toBe(false);
  });
});


describe("#600 converged marker resume skip (#600 AC8)", () => {
  const shipHead = "shiphead1111111111111111111111111111111111";
  const postFixHead = "postfix1111111111111111111111111111111111";

  it("family no-fix: review_loop_converged marker keys to ship head", () => {
    const markerHead = convergenceHeadToRecord({ shipHead });
    expect(markerHead).toBe(shipHead);
    expect(
      familyReviewLoopConvergedForHead(
        [
          {
            status: "review_loop_converged",
            event: "review_loop_converged",
            phase: "final",
            pr: "https://github.com/test/repo/pull/600",
            familyHeadAfter: shipHead,
          },
        ],
        shipHead,
      ),
    ).toBeDefined();
    expect(
      familyReviewLoopConvergedForHead(
        [
          {
            status: "review_loop_converged",
            event: "review_loop_converged",
            phase: "final",
            pr: "https://github.com/test/repo/pull/600",
            familyHeadAfter: shipHead,
          },
        ],
        postFixHead,
      ),
    ).toBeUndefined();
  });

  it("family converge-after-fix: review_loop_converged marker keys to post-fix family head", () => {
    const markerHead = convergenceHeadToRecord({ shipHead, postFixHead });
    expect(markerHead).toBe(postFixHead);
    expect(
      familyReviewLoopConvergedForHead(
        [
          {
            status: "review_loop_converged",
            event: "review_loop_converged",
            phase: "final",
            pr: "https://github.com/test/repo/pull/600",
            familyHeadAfter: postFixHead,
          },
        ],
        postFixHead,
      ),
    ).toBeDefined();
    expect(
      familyReviewLoopConvergedForHead(
        [
          {
            status: "review_loop_converged",
            event: "review_loop_converged",
            phase: "final",
            pr: "https://github.com/test/repo/pull/600",
            familyHeadAfter: postFixHead,
          },
        ],
        shipHead,
      ),
    ).toBeUndefined();
  });

  it("evidenceFromSnapshot keys headOid to snapshot head after fix", () => {
    const evidence = evidenceFromSnapshot({
      repo: "o/r",
      prNumber: 1,
      prUrl: "https://github.com/o/r/pull/1",
      headOid: postFixHead,
      pollCount: 2,
      bots: {
        coderabbit: { state: "complete", findingCount: 0 },
        sourcery: { state: "complete", findingCount: 0 },
        codex: { state: "complete", findingCount: 0 },
        gemini: { state: "complete", findingCount: 0 },
      },
      threads: [],
      checkRuns: [],
      roundTriggerUsed: TEST_ROUND_TRIGGER,
      checkRunsEmptyMeans: "converged",
      totalFindingCount: 0,
      quiescent: true,
    });
    expect(evidence.headOid).toBe(postFixHead);
  });
});

describe("#600 CI classification (Landing/autoMerge via classifyCheckRuns)", () => {
  it("pin checkRunsConverged: in-progress or failed runs block convergence", () => {
    expect(
      checkRunsConverged([
        {
          id: 1,
          name: "ci",
          headSha: "h",
          status: "completed",
          conclusion: "success",
        },
      ]),
    ).toBe(true);
    expect(
      checkRunsConverged([
        {
          id: 2,
          name: "ci",
          headSha: "h",
          status: "in_progress",
        },
      ]),
    ).toBe(false);
    expect(
      classifyCheckRuns([
        { id: 2, name: "ci", headSha: "h", status: "in_progress" },
      ]),
    ).toBe("pending");
    expect(
      checkRunsConverged([
        {
          id: 3,
          name: "ci",
          headSha: "h",
          status: "completed",
          conclusion: "failure",
        },
      ]),
    ).toBe(false);
    expect(
      classifyCheckRuns([
        {
          id: 3,
          name: "ci",
          headSha: "h",
          status: "completed",
          conclusion: "failure",
        },
      ]),
    ).toBe("failed");
    expect(checkRunsConverged([])).toBe(true);
    expect(classifyCheckRuns([])).toBe("converged");
    // Live post-push race: empty check_runs must not mean CI green
    expect(classifyCheckRuns([], "pending")).toBe("pending");
    expect(checkRunsConverged([], "pending")).toBe(false);
  });
});

describe("#600 r4 central evidence admissibility gate", () => {
  const trigger = buildRoundTrigger("head-a", "2026-07-08T10:00:00.000Z");

  it("matrix: only fresh_live correlating evidence is admissible", () => {
    expect(
      evidenceAdmissible(
        { terminalState: "fresh_live", headOid: "head-a" },
        "head-a",
        trigger,
      ),
    ).toBe(true);
    for (const terminalState of [
      "stale",
      "synthetic",
      "failed",
      "fallback",
      "silent",
    ] as const) {
      expect(
        evidenceAdmissible(
          { terminalState, headOid: "head-a" },
          "head-a",
          trigger,
        ),
      ).toBe(false);
    }
  });

  it("matrix: timestamp freshness accepts post-trigger artifacts only", () => {
    expect(
      evidenceAdmissible(
        {
          terminalState: "fresh_live",
          timestamp: "2026-07-08T11:00:00.000Z",
        },
        "head-a",
        trigger,
      ),
    ).toBe(true);
    expect(
      evidenceAdmissible(
        {
          terminalState: "fresh_live",
          timestamp: "2026-07-08T09:00:00.000Z",
        },
        "head-a",
        trigger,
      ),
    ).toBe(false);
  });

  it("pin r15: timestamp freshness compares parsed instants (precision/timezone formats)", () => {
    const triggerZ = buildRoundTrigger("head-a", "2026-07-08T10:00:00Z");
    expect(
      classifyEvidenceFreshness(
        { timestamp: "2026-07-08T10:30:00.000Z" },
        "head-a",
        triggerZ,
      ),
    ).toBe("fresh_live");
    expect(
      classifyEvidenceFreshness(
        { timestamp: "2026-07-08T09:30:00Z" },
        "head-a",
        triggerZ,
      ),
    ).toBe("stale");
  });

  it("pin r10: GitHub second-precision bot timestamp in trigger second is fresh", () => {
    // trigger captured with ms; GH reaction/comment created_at is second-truncated
    // to the same wall second → must not be stale (Codex R10 P2, verified).
    const triggerMs = buildRoundTrigger("head-a", "2026-07-08T10:00:00.900Z");
    expect(
      classifyEvidenceFreshness(
        { timestamp: "2026-07-08T10:00:00Z" },
        "head-a",
        triggerMs,
      ),
    ).toBe("fresh_live");
    expect(
      classifyEvidenceFreshness(
        { timestamp: "2026-07-08T09:59:59Z" },
        "head-a",
        triggerMs,
      ),
    ).toBe("stale");
    expect(
      classifyEvidenceFreshness(
        { timestamp: "2026-07-08T10:00:01Z" },
        "head-a",
        triggerMs,
      ),
    ).toBe("fresh_live");
  });

  it("pin r15: unparseable timestamp → stale (fail-closed)", () => {
    expect(
      classifyEvidenceFreshness(
        { timestamp: "not-a-timestamp" },
        "head-a",
        trigger,
      ),
    ).toBe("stale");
    expect(
      evidenceAdmissible(
        { terminalState: "fresh_live", timestamp: "garbage-ts" },
        "head-a",
        trigger,
      ),
    ).toBe(false);
    expect(
      classifyEvidenceFreshness(
        { timestamp: "2026-07-08T11:00:00.000Z" },
        "head-a",
        buildRoundTrigger("head-a", "also-not-a-timestamp"),
      ),
    ).toBe("stale");
  });

  it("pin botPolling r15/r14: eyes ACK on re-trigger is alive-only, not complete", () => {
    // Codex ACKs the manual re-trigger via `eyes` on the issue comment — that is
    // NOT a finished review (R14 Codex P1). Leg stays pending until review/+1.
    const calls: string[] = [];
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      calls.push(cmd);
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews") &&
        !cmd.includes("check-runs")
      ) {
        return JSON.stringify({
          head: { sha: "headsha1" },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") && !cmd.includes("issues/comments/")) {
        return JSON.stringify([
          {
            id: 8801,
            user: { login: "orchestrator-host" },
            body: ONLINE_REVIEW_BOT_RETRIGGER_COMMENT,
            created_at: TEST_ROUND_TRIGGER.triggeredAt,
          },
        ]);
      }
      if (cmd.includes("pulls/42/comments")) {
        return "[]";
      }
      if (cmd.includes("check-runs")) {
        return JSON.stringify({ check_runs: [] });
      }
      if (cmd.includes("pulls/42/reviews")) {
        return "[]";
      }
      if (cmd.includes("issues/comments/8801/reactions")) {
        return JSON.stringify([
          {
            user: { login: "chatgpt-codex-connector[bot]" },
            content: "eyes",
            created_at: FRESH_BOT_TIMESTAMP,
          },
        ]);
      }
      if (
        (cmd.includes("pulls/comments/") || cmd.includes("issues/comments/")) &&
        cmd.includes("/reactions")
      ) {
        return "[]";
      }
      return reviewThreadsGraphqlFallback(cmd) ?? "[]";
    };
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    expect(
      calls.some((c) => c.includes("repos/o/r/issues/comments/8801/reactions")),
    ).toBe(true);
    expect(snap.bots.codex.state).toBe("pending");
    expect(snap.bots.codex).not.toEqual({ state: "complete", findingCount: 0 });
  });

  it("pin botPolling r17: Codex PR-level +1 reaction is completion evidence, not a finding", () => {
    const calls: string[] = [];
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      calls.push(cmd);
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews") &&
        !cmd.includes("check-runs")
      ) {
        return JSON.stringify({
          head: { sha: "headsha1" },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") && !cmd.includes("issues/comments/")) {
        return "[]";
      }
      if (cmd.includes("pulls/42/comments")) {
        return "[]";
      }
      if (cmd.includes("check-runs")) {
        return JSON.stringify({ check_runs: [] });
      }
      if (cmd.includes("pulls/42/reviews")) {
        return "[]";
      }
      if (cmd.includes("repos/o/r/issues/42/reactions")) {
        return JSON.stringify([
          {
            user: { login: "chatgpt-codex-connector[bot]" },
            content: "+1",
            created_at: FRESH_BOT_TIMESTAMP,
          },
        ]);
      }
      if (
        (cmd.includes("pulls/comments/") || cmd.includes("issues/comments/")) &&
        cmd.includes("/reactions")
      ) {
        return "[]";
      }
      return reviewThreadsGraphqlFallback(cmd) ?? "[]";
    };
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    expect(calls.some((c) => c.includes("repos/o/r/issues/42/reactions"))).toBe(
      true,
    );
    expect(snap.bots.codex).toEqual({ state: "complete", findingCount: 0 });
  });

  it("pin botPolling r15: stale pre-trigger issue-comment reaction stays inadmissible", () => {
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews") &&
        !cmd.includes("check-runs")
      ) {
        return JSON.stringify({
          head: { sha: "headsha1" },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") && !cmd.includes("issues/comments/")) {
        return JSON.stringify([
          {
            id: 8802,
            user: { login: "orchestrator-host" },
            body: ONLINE_REVIEW_BOT_RETRIGGER_COMMENT,
            created_at: TEST_ROUND_TRIGGER.triggeredAt,
          },
        ]);
      }
      if (cmd.includes("pulls/42/comments")) {
        return "[]";
      }
      if (cmd.includes("check-runs")) {
        return JSON.stringify({ check_runs: [] });
      }
      if (cmd.includes("pulls/42/reviews")) {
        return "[]";
      }
      if (cmd.includes("issues/comments/8802/reactions")) {
        return JSON.stringify([
          {
            user: { login: "chatgpt-codex-connector[bot]" },
            content: "eyes",
            created_at: "2020-01-01T00:00:00.000Z",
          },
        ]);
      }
      if (
        (cmd.includes("pulls/comments/") || cmd.includes("issues/comments/")) &&
        cmd.includes("/reactions")
      ) {
        return "[]";
      }
      return reviewThreadsGraphqlFallback(cmd) ?? "[]";
    };
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    expect(snap.bots.codex.state).toBe("pending");
    expect(snap.bots.codex).not.toEqual({ state: "complete", findingCount: 1 });
  });

  it("pin #741: substring-spoof logins do not count as bot evidence via pollPrReviewState", () => {
    // Production seam: pollPrReviewState → hasBotReviewSignal/countBotFindings → loginMatchesBot.
    // Substring match would treat "xxx-coderabbit-fan" / "sourcery-fan" / "codex-fan" as bots.
    const emptyPr = (cmd: string): string | undefined => {
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews") &&
        !cmd.includes("check-runs")
      ) {
        return JSON.stringify({
          head: { sha: "headsha1" },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("check-runs")) {
        return JSON.stringify({ check_runs: [] });
      }
      if (
        (cmd.includes("pulls/comments/") || cmd.includes("issues/comments/")) &&
        cmd.includes("/reactions")
      ) {
        return "[]";
      }
      return reviewThreadsGraphqlFallback(cmd);
    };

    const spoofSh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      const pr = emptyPr(cmd);
      if (pr !== undefined) return pr;
      if (cmd.includes("issues/42/comments") || cmd.includes("pulls/42/comments")) {
        return JSON.stringify([
          {
            user: { login: "xxx-coderabbit-fan" },
            body: "Summary: spoofed coderabbit complete signal body",
            created_at: FRESH_BOT_TIMESTAMP,
          },
          {
            user: { login: "sourcery-fan" },
            body: "Sourcery spoof review complete signal body",
            created_at: FRESH_BOT_TIMESTAMP,
          },
          {
            user: { login: "gemini-code-fan" },
            body: "Gemini spoof review complete signal body",
            created_at: FRESH_BOT_TIMESTAMP,
          },
        ]);
      }
      if (cmd.includes("pulls/42/reviews")) {
        return JSON.stringify([
          {
            user: { login: "chatgpt-codex-fan" },
            state: "COMMENTED",
            submitted_at: FRESH_BOT_TIMESTAMP,
            body: "Codex spoof review complete",
          },
        ]);
      }
      return "[]";
    };

    const spoofSnap = pollPrReviewState(spoofSh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    for (const bot of ONLINE_REVIEW_BOT_IDS) {
      expect(spoofSnap.bots[bot].state).toBe("pending");
    }
    expect(spoofSnap.bots.coderabbit).not.toEqual(
      expect.objectContaining({ state: "complete" }),
    );

    // Real bot logins still count; case differs only in letter case (GitHub login rules).
    const realSh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      const pr = emptyPr(cmd);
      if (pr !== undefined) return pr;
      if (cmd.includes("issues/42/comments") || cmd.includes("pulls/42/comments")) {
        return JSON.stringify([
          {
            user: { login: "CodeRabbitAI[bot]" },
            body: "Summary: real coderabbit complete signal body",
            created_at: FRESH_BOT_TIMESTAMP,
          },
          {
            user: { login: "sourcery-ai[bot]" },
            body: "Sourcery review complete signal body ok",
            created_at: FRESH_BOT_TIMESTAMP,
          },
          {
            user: { login: "gemini-code-assist[bot]" },
            body: "Gemini review complete signal body ok",
            created_at: FRESH_BOT_TIMESTAMP,
          },
        ]);
      }
      if (cmd.includes("pulls/42/reviews")) {
        return JSON.stringify([
          {
            user: { login: "chatgpt-codex-connector[bot]" },
            state: "COMMENTED",
            submitted_at: FRESH_BOT_TIMESTAMP,
            body: "Codex review complete",
          },
        ]);
      }
      return "[]";
    };

    const realSnap = pollPrReviewState(realSh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    for (const bot of ONLINE_REVIEW_BOT_IDS) {
      expect(realSnap.bots[bot].state).toBe("complete");
    }
  });

  it("pin botPolling: historical bot comments before round trigger stay pending", () => {
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews") &&
        !cmd.includes("check-runs")
      ) {
        return JSON.stringify({
          head: { sha: "headsha1" },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") || cmd.includes("pulls/42/comments")) {
        return JSON.stringify([
          {
            user: { login: "coderabbitai[bot]" },
            body: "stale summary from prior round",
            created_at: "2020-01-01T00:00:00.000Z",
          },
        ]);
      }
      if (cmd.includes("check-runs")) {
        return JSON.stringify({ check_runs: [] });
      }
      if (cmd.includes("pulls/42/reviews")) {
        return "[]";
      }
      if (
        (cmd.includes("pulls/comments/") || cmd.includes("issues/comments/")) &&
        cmd.includes("/reactions")
      ) {
        return "[]";
      }
      return reviewThreadsGraphqlFallback(cmd) ?? "[]";
    };
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    expect(snap.bots.coderabbit.state).toBe("pending");
  });

  it("pin offline gate: default-deny synthetic snapshots outside admissible handles", () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    try {
      expect(
        offlineSyntheticPollAdmissible("https://github.com/o/r/pull/1", "o/r"),
      ).toBe(false);
      expect(() =>
        assertOfflineSyntheticPollAdmissible(
          "https://github.com/o/r/pull/1",
          "o/r",
        ),
      ).toThrow(/refused for live GitHub PR/);

      delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      expect(() =>
        assertOfflineSyntheticPollAdmissible(
          "https://github.com/o/r/pull/1",
          "o/r",
        ),
      ).toThrow(/refused for live GitHub PR/);
      expect(() =>
        assertOfflineSyntheticPollAdmissible("pr://family/offline", "o/r"),
      ).toThrow(/refused for non-admissible PR handle/);

      process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
      expect(offlineSyntheticPollAdmissible("pr://family/offline", "o/r")).toBe(
        true,
      );
      expect(() =>
        assertOfflineSyntheticPollAdmissible("pr://family/offline", "o/r"),
      ).not.toThrow();
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });
});
