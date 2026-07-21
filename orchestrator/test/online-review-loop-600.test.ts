/**
 * #600 — online review-loop: bot polling + verify/fixer/reverify convergence.
 */

import { describe, expect, it, vi } from "vitest";
import {
  type MechanicalRetryOptions,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../src/dispatchRetry.js";
import {
  landingWorkerSpec,
  verifyWorkerSpec,
  fixerWorkerSpec,
} from "../src/dispatchWorker.js";
import {
  legacyDispatchFamilyWorker,
} from "../src/family/dispatchFamilyWorker.js";
import type {
  Backend,
  DispatchContext,
  FixerResult,
  IssueMeta,
  OnlineReviewLandingSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  VerifyResult,
  WorkerKind,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";
import type { PrReviewSnapshot } from "../src/botPolling.js";

const FIXER_ENVELOPE_SHA = "fixsha1111111111111111111111111111111111";
const fixerCommitted = (fixCommitSha = FIXER_ENVELOPE_SHA): FixerResult => ({
  kind: "fixer",
  committed: true,
  fixCommitSha,
});
const fixerNotFixed = (): FixerResult => ({ kind: "fixer", committed: false });
const fixerAlreadySatisfied = (fixCommitSha: string): FixerResult => ({
  kind: "fixer",
  committed: false,
  alreadySatisfied: true,
  fixCommitSha,
});
import {
  BOT_OVERDUE_POLL_COUNT,
  BOT_OVERDUE_MIN_WALL_MS,
  BOT_POLL_INTERVAL_MS,
  botOverdueWallClockMs,
  BOT_RETRIGGER_COMMENT,
  checkRunsConverged,
  classifyCheckRuns,
  droppedBotIds,
  hasDroppedBots,
  isBotQuiescent,
  isThreadEvidenceFresh,
  ONLINE_REVIEW_BOT_IDS,
  ONLINE_REVIEW_BOT_LOGINS,
  paginateReviewThreadNodes,
  parsePrRef,
  findAdmissibleRetriggerComment,
  isBotRetriggerCommentBody,
  pollPrReviewState,
  postBotRetriggerComment,
} from "../src/botPolling.js";
import {
  assertOfflineSyntheticPollAdmissible,
  buildRoundTrigger,
  classifyEvidenceFreshness,
  convergenceHeadToRecord,
  evidenceAdmissible,
  offlineSyntheticPollAdmissible,
} from "../src/evidenceAdmissibility.js";
import { offlinePrReviewSnapshot } from "../src/family/onlineReviewLoop.js";
import {
  enforceRunnerOwnedRecheck,
  immediateBotPollClock,
  lastFixMarkedFindingAuthorizationFromFamilyLedger,
  lastOnlineReviewFixCommitShaFromFamilyLedger,
  onlineReviewRoundFromFamilyLedger,
  onlineReviewRoundTriggerFromFamilyLedger,
  ensureOnlineReviewRetriggerAfterFixGap,
  retriggerBotsAndPoll,
  familyPendingRoundTriggerFromFixGap,
  resolveOnlineReviewRoundTrigger,

  runOnlineReviewLoopStage,
  fixMarkedKeysFromVerify,
  shipLedgerTriggeredAtFromFamilyLedger,
  waitForBotQuiescence,
} from "../src/family/onlineReviewLoop.js";
import {
  fixerHasFixCommit,
  skeletonReviewLoopWorkerResult,
} from "../src/reviewLoopOutcome.js";
import {
  buildOnlineReviewLanding,
  verifyBlockedOnlyOnPendingCheckRuns,
  onlineReviewFixerNothingToFixStopSummary,
} from "../src/family/onlineReviewLoop.js";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Sh } from "../src/familyDriver.js";
import {
  familyReviewLoopConvergedForHead,
  recordOnlineReviewFixCommitted,
} from "../src/family/ledger.js";
import { runFamilyOnlineReviewLoop } from "../src/family/verifyCmr.js";
import { RealFamilyBackend } from "../src/family/realFamilyBackend.js";
import type { FamilyBackend, FamilyLedgerEntry } from "../src/family/types.js";
import type { WorkerLandingPayload } from "../src/types.js";
import { buildExplicitLandingLiveHooks } from "../src/family/landing.js";


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

const LANDING_THREAD_PAIR_GRAPHQL = JSON.stringify({
  data: {
    repository: {
      pullRequest: {
        reviewThreads: {
          pageInfo: { endCursor: "", hasNextPage: false },
          nodes: [
            {
              id: "PRRT_kwDOExampleThread",
              isResolved: false,
              comments: { nodes: [{ databaseId: 4242 }] },
            },
          ],
        },
      },
    },
  },
});

const FRESH_BOT_TIMESTAMP = "2026-07-08T12:00:00.000Z";
const TEST_ROUND_TRIGGER = buildRoundTrigger(
  "headsha1",
  "2026-07-08T11:00:00.000Z",
);

const GITHUB_REPLY_SHAPE = [{
  id: 99,
  body: "reply body",
  path: "src/example.ts",
  user: { login: "orchestrator-host" },
}];

const GITHUB_RESOLVE_MUTATION_SHAPE = {
  data: {
    resolveReviewThread: {
      thread: { isResolved: true },
    },
  },
};

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

  it("pin r24: buildOnlineReviewLanding threads carry path/line from poll snapshot", () => {
    const calls: string[] = [];
    const sh = ghFixture({ calls });
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    const landing = buildOnlineReviewLanding(
      snap,
      {
        kind: "ship",
        branch: "feat/x",
        status: "pr_opened",
        pr: "https://github.com/o/r/pull/42",
        prHead: "headsha1",
      },
      1,
    );
    expect(landing.onlineReviewSnapshot?.threads[0]).toEqual(
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
    expect(isBotQuiescent(snap)).toBe(true);
    expect(hasDroppedBots(snap)).toBe(true);
    expect(droppedBotIds(snap)).toContain("gemini");
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

  it("pollPrReviewState failures fail closed (no empty-green snapshot)", async () => {
    const sh: Sh = () => {
      throw new Error("gh api failed");
    };
    await expect(
      waitForBotQuiescence(sh, {
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        roundTrigger: TEST_ROUND_TRIGGER,
        maxPolls: 1,
        clock: immediateBotPollClock,
      }),
    ).rejects.toThrow(/gh api failed/);
  });

  it("pin BOT_RETRIGGER_COMMENT matches wiki concepts/pr-review-loop.md bot commands", () => {
    // Wiki core (ADR 0061) + `/gemini review` slash form (Codex R12 / current Gemini docs).
    expect(BOT_RETRIGGER_COMMENT).toBe(
      "@sourcery-ai review\n@codex review\n@gemini-code-assist please review\n/gemini review",
    );
    // Old 3-line wiki body still admissible for gap recovery.
    expect(
      isBotRetriggerCommentBody(
        "@sourcery-ai review\n@codex review\n@gemini-code-assist please review",
      ),
    ).toBe(true);
  });

  it("postBotRetriggerComment posts the R2/R3 manual re-trigger body", () => {
    const calls: Array<{ file: string; args: string[] }> = [];
    const sh: Sh = (file, args) => {
      calls.push({ file, args: [...args] });
      if (args.join(" ").includes("pulls/42") && !args.includes("-f")) {
        return JSON.stringify({ head: { sha: "h" }, html_url: "https://github.com/o/r/pull/42" });
      }
      return "{}";
    };
    postBotRetriggerComment(sh, "o/r", 42);
    // CR-18: pin full API path + complete retrigger body (not first line only).
    expect(calls).toContainEqual({
      file: "gh",
      args: [
        "api",
        "repos/o/r/issues/42/comments",
        "-f",
        `body=${BOT_RETRIGGER_COMMENT}`,
      ],
    });
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
    expect(snap.threads[0]?.headOid).toBeUndefined();
    expect(isThreadEvidenceFresh(snap.threads[0]!, snap.headOid)).toBe(false);
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
    expect(isThreadEvidenceFresh(stale, "headsha1")).toBe(false);
  });
});


describe("#600 r18 retrigger timestamp anchoring", () => {
  it("pin: roundTrigger captured before post so race-window bot ACK stays fresh", () => {
    const TRIGGER_BEFORE_POST = "2026-07-08T13:00:00.000Z";
    const BETWEEN_POST_AND_OLD_CAPTURE = "2026-07-08T13:00:00.500Z";
    const OLD_BUGGY_CAPTURE = "2026-07-08T13:00:01.000Z";

    vi.useFakeTimers();
    vi.setSystemTime(new Date(TRIGGER_BEFORE_POST));
    try {
      const calls: string[] = [];
      const sh: Sh = (file, args) => {
        const cmd = args.join(" ");
        if (
          cmd.includes("issues/42/comments") &&
          cmd.includes("-f") &&
          cmd.includes(BOT_RETRIGGER_COMMENT.split("\n")[0]!)
        ) {
          vi.setSystemTime(new Date(OLD_BUGGY_CAPTURE));
          return JSON.stringify({ id: 9001, body: "posted" });
        }
        return ghFixture({ calls })(file, args);
      };

      const { roundTrigger } = retriggerBotsAndPoll(
        sh,
        "o/r",
        "https://github.com/o/r/pull/42",
        2,
        "headsha1",
      );

      expect(roundTrigger.triggeredAt).toBe(TRIGGER_BEFORE_POST);
      expect(
        evidenceAdmissible(
          {
            terminalState: "fresh_live",
            timestamp: BETWEEN_POST_AND_OLD_CAPTURE,
          },
          "headsha1",
          roundTrigger,
        ),
      ).toBe(true);
      expect(
        evidenceAdmissible(
          {
            terminalState: "fresh_live",
            timestamp: BETWEEN_POST_AND_OLD_CAPTURE,
          },
          "headsha1",
          buildRoundTrigger("headsha1", OLD_BUGGY_CAPTURE),
        ),
      ).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("#600 r34 gap-resume retrigger recovery", () => {
  const fixSha = "fixsha1111111111111111111111111111111111";
  const fixTs = "2026-07-08T12:30:00.000Z";
  const gapTrigger = buildRoundTrigger(fixSha, fixTs);
  const existingRetriggerTs = "2026-07-08T13:00:00.000Z";

  it("pin r34: ensure posts retrigger when no admissible comment exists", () => {
    const calls: string[] = [];
    const sh = ghFixture({ calls });
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-08T13:30:00.000Z"));
    try {
      const result = ensureOnlineReviewRetriggerAfterFixGap({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        gapTrigger,
      });
      expect(result.posted).toBe(true);
      expect(result.roundTrigger).toEqual(
        buildRoundTrigger("headsha1", "2026-07-08T13:30:00.000Z"),
      );
      expect(
        calls.some((c) => c.includes(BOT_RETRIGGER_COMMENT.split("\n")[0]!)),
      ).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("pin r34: ensure skips post when admissible retrigger comment already exists", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      const cmd = args.join(" ");
      calls.push(cmd);
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews")
      ) {
        return JSON.stringify({
          head: { sha: fixSha },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") && !cmd.includes("issues/comments/")) {
        return JSON.stringify([
          {
            id: 8801,
            user: { login: "orchestrator-host" },
            body: BOT_RETRIGGER_COMMENT,
            created_at: existingRetriggerTs,
          },
        ]);
      }
      if (cmd.includes("pulls/42/comments")) return "[]";
      if (cmd.includes("check-runs")) return JSON.stringify({ check_runs: [] });
      if (cmd.includes("pulls/42/reviews")) return "[]";
      if (cmd.includes("/reactions")) return "[]";
      return reviewThreadsGraphqlFallback(cmd) ?? "[]";
    };

    const existing = findAdmissibleRetriggerComment(
      sh,
      "o/r",
      "https://github.com/o/r/pull/42",
      gapTrigger,
    );
    expect(existing).toEqual(buildRoundTrigger(fixSha, existingRetriggerTs));

    const result = ensureOnlineReviewRetriggerAfterFixGap({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      gapTrigger,
    });
    expect(result.posted).toBe(false);
    expect(result.roundTrigger).toEqual(buildRoundTrigger(fixSha, existingRetriggerTs));
    expect(
      calls.some((c) => c.includes(BOT_RETRIGGER_COMMENT.split("\n")[0]!) && c.includes("-f")),
    ).toBe(false);
  });

  it("pin deep self-check: live head left gapTrigger.head → never reuse old re-trigger", () => {
    // gap was fixed at fixSha; live PR head advanced to newHead → must post fresh.
    const fixSha = "fixsha1111111111111111111111111111111111";
    const newHead = "newhead22222222222222222222222222222222";
    const gapTrigger = buildRoundTrigger(fixSha, "2026-07-08T12:30:00.000Z");
    const oldRetriggerTs = "2026-07-08T13:00:00.000Z";
    let postCount = 0;
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
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
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews")
      ) {
        return JSON.stringify({
          head: { sha: newHead },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") && cmd.includes("-f")) {
        postCount += 1;
        return JSON.stringify({ id: 9901, body: "posted" });
      }
      if (cmd.includes("issues/42/comments")) {
        return JSON.stringify([
          {
            id: 8801,
            user: { login: "orchestrator-host" },
            body: BOT_RETRIGGER_COMMENT,
            created_at: oldRetriggerTs,
          },
        ]);
      }
      if (cmd.includes("pulls/42/comments")) return "[]";
      if (cmd.includes("check-runs")) return JSON.stringify({ check_runs: [] });
      if (cmd.includes("pulls/42/reviews")) return "[]";
      if (cmd.includes("/reactions")) return "[]";
      return "[]";
    };

    expect(
      findAdmissibleRetriggerComment(
        sh,
        "o/r",
        "https://github.com/o/r/pull/42",
        gapTrigger,
      ),
    ).toBeUndefined();

    const result = ensureOnlineReviewRetriggerAfterFixGap({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      gapTrigger,
    });
    expect(result.posted).toBe(true);
    expect(result.roundTrigger.headOid).toBe(newHead);
    expect(result.roundTrigger.triggeredAt).not.toBe(oldRetriggerTs);
    expect(postCount).toBeGreaterThanOrEqual(1);
  });

  it("pin r34: double gap-resume does not duplicate retrigger comment", () => {
    let postCount = 0;
    const sh: Sh = (file, args) => {
      const cmd = args.join(" ");
      if (
        cmd.includes("issues/42/comments") &&
        cmd.includes("-f") &&
        cmd.includes(BOT_RETRIGGER_COMMENT.split("\n")[0]!)
      ) {
        postCount += 1;
        return JSON.stringify({ id: 9000 + postCount, body: "posted" });
      }
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews")
      ) {
        return JSON.stringify({
          head: { sha: fixSha },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") && !cmd.includes("issues/comments/")) {
        if (postCount > 0) {
          return JSON.stringify([
            {
              id: 9001,
              user: { login: "orchestrator-host" },
              body: BOT_RETRIGGER_COMMENT,
              created_at: "2026-07-08T13:30:00.000Z",
            },
          ]);
        }
        return "[]";
      }
      if (cmd.includes("pulls/42/comments")) return "[]";
      if (cmd.includes("check-runs")) return JSON.stringify({ check_runs: [] });
      if (cmd.includes("pulls/42/reviews")) return "[]";
      if (cmd.includes("/reactions")) return "[]";
      return reviewThreadsGraphqlFallback(cmd) ?? "[]";
    };

    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-08T13:30:00.000Z"));
    try {
      const first = ensureOnlineReviewRetriggerAfterFixGap({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        gapTrigger,
      });
      const second = ensureOnlineReviewRetriggerAfterFixGap({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        gapTrigger,
      });
      expect(first.posted).toBe(true);
      expect(second.posted).toBe(false);
      expect(postCount).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("pin r34: isBotRetriggerCommentBody matches the wiki contract body", () => {
    expect(isBotRetriggerCommentBody(BOT_RETRIGGER_COMMENT)).toBe(true);
    expect(isBotRetriggerCommentBody("  " + BOT_RETRIGGER_COMMENT + "  ")).toBe(true);
    expect(isBotRetriggerCommentBody("unrelated")).toBe(false);
    expect(isBotRetriggerCommentBody("@sourcery-ai review")).toBe(false);
    expect(isBotRetriggerCommentBody("@codex review")).toBe(false);
    expect(isBotRetriggerCommentBody("@sourcery-ai review\n@codex review")).toBe(false);
    expect(
      isBotRetriggerCommentBody(
        "Please re-run all bots after the fix:\n" +
          BOT_RETRIGGER_COMMENT +
          "\nThanks!",
      ),
    ).toBe(true);
  });

  it("pin r29: lone partial retrigger does not satisfy fix-gap idempotency", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      const cmd = args.join(" ");
      calls.push(cmd);
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews")
      ) {
        return JSON.stringify({
          head: { sha: fixSha },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") && !cmd.includes("issues/comments/")) {
        return JSON.stringify([
          {
            id: 8802,
            user: { login: "orchestrator-host" },
            body: "@sourcery-ai review",
            created_at: existingRetriggerTs,
          },
        ]);
      }
      if (cmd.includes("pulls/42/comments")) return "[]";
      if (cmd.includes("check-runs")) return JSON.stringify({ check_runs: [] });
      if (cmd.includes("pulls/42/reviews")) return "[]";
      if (cmd.includes("/reactions")) return "[]";
      return reviewThreadsGraphqlFallback(cmd) ?? "[]";
    };

    expect(
      findAdmissibleRetriggerComment(
        sh,
        "o/r",
        "https://github.com/o/r/pull/42",
        gapTrigger,
      ),
    ).toBeUndefined();

    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-08T13:30:00.000Z"));
    try {
      const result = ensureOnlineReviewRetriggerAfterFixGap({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        gapTrigger,
      });
      expect(result.posted).toBe(true);
      expect(result.roundTrigger).toEqual(
        buildRoundTrigger(fixSha, "2026-07-08T13:30:00.000Z"),
      );
      expect(
        calls.some(
          (c) =>
            c.includes(BOT_RETRIGGER_COMMENT.split("\n")[0]!) &&
            c.includes("@gemini-code-assist please review") &&
            c.includes("-f"),
        ),
      ).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("pin r29: full three-bot retrigger still satisfies fix-gap idempotency", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      const cmd = args.join(" ");
      calls.push(cmd);
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews")
      ) {
        return JSON.stringify({
          head: { sha: fixSha },
          html_url: "https://github.com/o/r/pull/42",
        });
      }
      if (cmd.includes("issues/42/comments") && !cmd.includes("issues/comments/")) {
        return JSON.stringify([
          {
            id: 8803,
            user: { login: "orchestrator-host" },
            body: BOT_RETRIGGER_COMMENT,
            created_at: existingRetriggerTs,
          },
        ]);
      }
      if (cmd.includes("pulls/42/comments")) return "[]";
      if (cmd.includes("check-runs")) return JSON.stringify({ check_runs: [] });
      if (cmd.includes("pulls/42/reviews")) return "[]";
      if (cmd.includes("/reactions")) return "[]";
      return reviewThreadsGraphqlFallback(cmd) ?? "[]";
    };

    const existing = findAdmissibleRetriggerComment(
      sh,
      "o/r",
      "https://github.com/o/r/pull/42",
      gapTrigger,
    );
    expect(existing).toEqual(buildRoundTrigger(fixSha, existingRetriggerTs));

    const result = ensureOnlineReviewRetriggerAfterFixGap({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      gapTrigger,
    });
    expect(result.posted).toBe(false);
    expect(result.roundTrigger).toEqual(buildRoundTrigger(fixSha, existingRetriggerTs));
    expect(
      calls.some((c) => c.includes(BOT_RETRIGGER_COMMENT.split("\n")[0]!) && c.includes("-f")),
    ).toBe(false);
  });
});

describe("#600 retriggerBotsAndPoll (#600 AC2)", () => {
  it("posts R2/R3 re-trigger then polls", () => {
    const calls: string[] = [];
    const sh = ghFixture({ calls });
    retriggerBotsAndPoll(sh, "o/r", "https://github.com/o/r/pull/42", 2, "headsha1");
    expect(calls.some((c) => c.includes(BOT_RETRIGGER_COMMENT.split("\n")[0]!))).toBe(
      true,
    );
  });

  it("waitForBotQuiescence enforces multi-poll cadence before quiescence", async () => {
    let polls = 0;
    const base = ghFixture({ calls: [] });
    const sh: Sh = (file, args) => {
      const cmd = args.join(" ");
      if (
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews")
      ) {
        polls += 1;
      }
      return base(file, args);
    };
    const sleepMs: number[] = [];
    const clock = {
      sleep(ms: number) {
        sleepMs.push(ms);
      },
    };
    const snap = await waitForBotQuiescence(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      roundTrigger: TEST_ROUND_TRIGGER,
      maxPolls: BOT_OVERDUE_POLL_COUNT,
      clock,
    });
    expect(polls).toBe(BOT_OVERDUE_POLL_COUNT);
    expect(sleepMs).toEqual(
      Array.from({ length: BOT_OVERDUE_POLL_COUNT - 1 }, () => BOT_POLL_INTERVAL_MS),
    );
    // Pin R16 arithmetic: N polls ⇒ N−1 sleeps; wall clock ≥ 15 min.
    expect(sleepMs.length).toBe(BOT_OVERDUE_POLL_COUNT - 1);
    expect(botOverdueWallClockMs(BOT_OVERDUE_POLL_COUNT)).toBe(
      sleepMs.length * BOT_POLL_INTERVAL_MS,
    );
    expect(botOverdueWallClockMs(BOT_OVERDUE_POLL_COUNT)).toBeGreaterThanOrEqual(
      BOT_OVERDUE_MIN_WALL_MS,
    );
    // Regression: N=8 would only sleep 7×2m = 14m (< 15m).
    expect(botOverdueWallClockMs(8)).toBeLessThan(BOT_OVERDUE_MIN_WALL_MS);
    expect(hasDroppedBots(snap)).toBe(true);
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

  it("buildOnlineReviewLanding keys shipDelivery.prHead to snapshot head after fix", () => {
    const landing = buildOnlineReviewLanding(
      {
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
      },
      {
        kind: "ship",
        branch: "feat/x",
        status: "pr_opened",
        pr: "https://github.com/o/r/pull/1",
        prHead: shipHead,
      },
      2,
    );
    expect(landing.shipDelivery?.prHead).toBe(postFixHead);
    expect(landing.onlineReviewSnapshot?.headOid).toBe(postFixHead);
  });
});

/**
 * Mirrors S9 production (online R10 Codex P1): read-only drift guard runs after
 * every attempt — including throws — so a mutate-then-crash path surfaces as
 * contract_drift instead of retrying on a dirty worktree.
 */
async function dispatchVerifyWithPerAttemptDriftGuard(
  dispatch: () => Promise<WorkerResult>,
  assertContract: () => Promise<void>,
  callerOwns: NonNullable<MechanicalRetryOptions["callerOwns"]>,
): Promise<WorkerResult> {
  return withMechanicalRetry(
    verifyWorkerSpec(),
    {} as DispatchContext,
    async () => {
      let dispatchError: unknown | undefined;
      let workerResult: WorkerResult | undefined;
      try {
        workerResult = await dispatch();
      } catch (err) {
        dispatchError = err;
      }
      // Always assert — prefer contract_drift over rethrowing a process throw
      // that left HEAD/worktree mutated (Codex R10 P1, verified against runner).
      await assertContract();
      if (dispatchError !== undefined) throw dispatchError;
      return workerResult!;
    },
    { callerOwns, rethrowOnExhaustion: true },
  );
}

describe("#600 verify/fixer crash retry (#600 AC7 / #598)", () => {
  it("a verify worker that crashes once then completes is retried fresh", async () => {
    let attempts = 0;
    const dispatch = async (): Promise<WorkerResult> => {
      attempts += 1;
      if (attempts === 1) throw new Error("verify worker threw on startup");
      return {
        kind: "completed",
        output: { kind: "verify", converged: true },
      };
    };
    const result = await withMechanicalRetry(
      verifyWorkerSpec(),
      {} as DispatchContext,
      async () => dispatch(),
    );
    expect(result.kind).toBe("completed");
    expect(attempts).toBe(2);
  });

  it("a fixer worker that crashes once then commits is retried on current state", async () => {
    let attempts = 0;
    const dispatch = async (): Promise<WorkerResult> => {
      attempts += 1;
      if (attempts === 1) throw new Error("fixer worker threw on startup");
      return {
        kind: "completed",
        output: { kind: "fixer", committed: true, fixCommitSha: FIXER_ENVELOPE_SHA },
      };
    };
    const result = await withMechanicalRetry(
      fixerWorkerSpec(),
      {} as DispatchContext,
      async () => dispatch(),
    );
    expect(result.kind).toBe("completed");
    expect(attempts).toBe(2);
  });

  it("a persistently crashing verify exhausts the shared dispatch bound", async () => {
    let attempts = 0;
    const result = await withMechanicalRetry(
      verifyWorkerSpec(),
      {} as DispatchContext,
      async () => {
        attempts += 1;
        throw new Error("verify worker threw on startup");
      },
    );
    expect(attempts).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(result).toMatchObject({
      kind: "failed",
      reason: expect.stringContaining(
        `after ${MAX_DISPATCH_ATTEMPTS} dispatch attempts`,
      ),
    });
  });

});

describe("#600 onlineReviewLoop helpers", () => {
  it("#940: fixMarkedKeysFromVerify preserves a missing self-reported fix-key list", () => {
    expect(
      fixMarkedKeysFromVerify({
        kind: "verify",
        converged: false,
      }),
    ).toEqual([]);
  });

  it("buildOnlineReviewLanding threads snapshot + ship metadata", () => {
    const landing = buildOnlineReviewLanding(
      {
        repo: "o/r",
        prNumber: 1,
        prUrl: "https://github.com/o/r/pull/1",
        headOid: "abc",
        pollCount: 1,
        bots: {
          coderabbit: { state: "complete", findingCount: 0 },
          sourcery: { state: "complete", findingCount: 0 },
          codex: { state: "complete", findingCount: 0 },
          gemini: {
            state: "dropped",
            reason: "no review signal after 9 polls",
          },
        },
        threads: [],
        checkRuns: [
          {
            id: 9,
            name: "ci",
            headSha: "abc",
            status: "completed",
            conclusion: "success",
          },
        ],
        roundTriggerUsed: TEST_ROUND_TRIGGER,
        checkRunsEmptyMeans: "converged",
        totalFindingCount: 0,
        quiescent: true,
      },
      { kind: "ship", branch: "feat/x", status: "pr_opened", pr: "https://github.com/o/r/pull/1" },
      2,
    );
    expect(landing.onlineReviewRound).toBe(2);
    expect(landing.shipDelivery?.branch).toBe("feat/x");
    expect(landing.onlineReviewSnapshot?.droppedBots).toEqual(["gemini"]);
    expect(landing.onlineReviewSnapshot?.bots?.gemini).toEqual({
      state: "dropped",
      reason: "no review signal after 9 polls",
    });
    expect(landing.onlineReviewSnapshot?.checkRuns).toEqual([
      {
        id: 9,
        name: "ci",
        headSha: "abc",
        status: "completed",
        conclusion: "success",
      },
    ]);
  });

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
    expect(classifyCheckRuns([{ id: 2, name: "ci", headSha: "h", status: "in_progress" }])).toBe(
      "pending",
    );
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
    expect(classifyCheckRuns([{ id: 3, name: "ci", headSha: "h", status: "completed", conclusion: "failure" }])).toBe(
      "failed",
    );
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
    // https://docs.github.com/en/rest/reactions/reactions?apiVersion=2022-11-28#list-reactions-for-an-issue-comment
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
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
            body: BOT_RETRIGGER_COMMENT,
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
    const sh: Sh = (file, args) => {
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
    const sh: Sh = (file, args) => {
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
            body: BOT_RETRIGGER_COMMENT,
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
    const sh: Sh = (file, args) => {
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
      expect(() =>
        offlinePrReviewSnapshot({
          repo: "o/r",
          prUrl: "https://github.com/o/r/pull/1",
          headOid: "abc",
          pollCount: 1,
        }),
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

describe("#600 r9 first-round RoundTrigger anchoring (#600 cmr r3)", () => {
  const SHIP_LEDGER_TS = "2026-07-08T10:00:00.000Z";
  const LOOP_START_TS = "2026-07-08T12:00:00.000Z";
  const BETWEEN_SHIP_AND_LOOP_TS = "2026-07-08T11:00:00.000Z";
  const PRE_SHIP_TS = "2026-07-08T09:00:00.000Z";
  const POST_RETRIGGER_TS = "2026-07-08T13:30:00.000Z";
  const RETRIGGER_TS = "2026-07-08T13:00:00.000Z";

  it("(c) round ≥2 retrigger anchoring uses a fresh trigger, not the ship ledger ts", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      return ghFixture({ calls })(file, args);
    };

    const shipRound1Trigger = buildRoundTrigger("headsha1", SHIP_LEDGER_TS);
    const betweenShipAndRetrigger = "2026-07-08T11:30:00.000Z";
    expect(
      evidenceAdmissible(
        { terminalState: "fresh_live", timestamp: betweenShipAndRetrigger },
        "headsha1",
        shipRound1Trigger,
      ),
    ).toBe(true);

    const { roundTrigger: round2Trigger } = retriggerBotsAndPoll(
      sh,
      "o/r",
      "https://github.com/o/r/pull/42",
      2,
      "headsha1",
    );
    expect(round2Trigger.triggeredAt).not.toBe(SHIP_LEDGER_TS);
    expect(calls.some((c) => c.includes(BOT_RETRIGGER_COMMENT.split("\n")[0]!))).toBe(
      true,
    );

    const explicitRound2Trigger = buildRoundTrigger("headsha1", RETRIGGER_TS);
    expect(
      evidenceAdmissible(
        { terminalState: "fresh_live", timestamp: betweenShipAndRetrigger },
        "headsha1",
        explicitRound2Trigger,
      ),
    ).toBe(false);
    expect(
      evidenceAdmissible(
        { terminalState: "fresh_live", timestamp: POST_RETRIGGER_TS },
        "headsha1",
        explicitRound2Trigger,
      ),
    ).toBe(true);

    const familyShipTs = shipLedgerTriggeredAtFromFamilyLedger(
      [
        {
          status: "shipped",
          event: "shipped",
          pr: "https://github.com/o/r/pull/42",
          ts: SHIP_LEDGER_TS,
        },
      ],
      "https://github.com/o/r/pull/42",
    );
    expect(familyShipTs).toBe(SHIP_LEDGER_TS);
  });

  it("pin r25: round ≥2 without persisted trigger fails closed (no ship fallback)", () => {
    expect(() =>
      resolveOnlineReviewRoundTrigger({
        onlineReviewRound: 2,
        shipPrHead: "headsha1",
        shipLedgerTriggeredAt: SHIP_LEDGER_TS,
      }),
    ).toThrow(/persisted round trigger/);
  });

  it("pin r29: retrigger-only marker gap restores round symmetrically (family)", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const familyLedger: FamilyLedgerEntry[] = [
      {
        status: "online_review_round_retrigger",
        event: "online_review_round_retrigger",
        phase: "final",
        roundTriggerHeadOid: fixSha,
        roundTriggerAt: RETRIGGER_TS,
        onlineReviewRound: 2,
      },
    ];
    expect(onlineReviewRoundFromFamilyLedger(familyLedger)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromFamilyLedger(familyLedger)).toBeUndefined();
    expect(onlineReviewRoundTriggerFromFamilyLedger(familyLedger)).toEqual(
      buildRoundTrigger(fixSha, RETRIGGER_TS),
    );
    const recheckOutcome = enforceRunnerOwnedRecheck(
      { kind: "verify", converged: true },
      onlineReviewRoundFromFamilyLedger(familyLedger),
    );
    expect(recheckOutcome).toEqual({
      kind: "verify",
      converged: true,
      isRecheck: true,
    });
  });

  it("pin r11: fix-gap picks chronologically latest unpaired fix (not last ledger order)", () => {
    const olderSha = "oldfixaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const newerSha = "newfixbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const olderTs = "2026-07-08T12:00:00.000Z";
    const newerTs = "2026-07-08T13:00:00.000Z";
    // Ledger order puts the older fix AFTER the newer one — timestamp must win.
    const familyGap = familyPendingRoundTriggerFromFixGap([
      {
        status: "online_review_fix_committed",
        event: "online_review_fix_committed",
        familyHeadAfter: newerSha,
        ts: newerTs,
      },
      {
        status: "online_review_fix_committed",
        event: "online_review_fix_committed",
        familyHeadAfter: olderSha,
        ts: olderTs,
      },
    ]);
    expect(familyGap).toEqual(buildRoundTrigger(newerSha, newerTs));
  });

  it("pin r11: buildOnlineReviewLanding omits prHead when convergence head missing", () => {
    const landing = buildOnlineReviewLanding(
      {
        repo: "o/r",
        prNumber: 1,
        prUrl: "https://github.com/o/r/pull/1",
        headOid: "",
        pollCount: 1,
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
      },
      {
        kind: "ship",
        branch: "feat/x",
        status: "pr_opened",
        pr: "https://github.com/o/r/pull/1",
        // no prHead
      },
      1,
    );
    expect(landing.shipDelivery?.prHead).toBeUndefined();
    expect(landing.shipDelivery?.pr).toBe("https://github.com/o/r/pull/1");
  });

  it("pin r27: round ≥2 crash gap reconstructs pending trigger from fix-committed", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const gapTrigger = familyPendingRoundTriggerFromFixGap([
      {
        status: "online_review_fix_committed",
        event: "online_review_fix_committed",
        familyHeadAfter: fixSha,
        ts: fixTs,
      },
    ]);
    expect(gapTrigger).toEqual(buildRoundTrigger(fixSha, fixTs));
    const resolved = resolveOnlineReviewRoundTrigger({
      onlineReviewRound: 2,
      pendingRetriggerFromFixGap: gapTrigger,
      shipPrHead: "headsha1",
      shipLedgerTriggeredAt: SHIP_LEDGER_TS,
    });
    expect(resolved).toEqual(gapTrigger);
  });

  it("pin r30: post-fixer crash-point matrix incl. network boundary (family)", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const pr = "https://github.com/test/repo/pull/352";
    const fixCommittedOnly: FamilyLedgerEntry = {
      status: "online_review_fix_committed",
      event: "online_review_fix_committed",
      phase: "final",
      familyHeadAfter: fixSha,
      pr,
      ts: fixTs,
    };
    const retrigger: FamilyLedgerEntry = {
      status: "online_review_round_retrigger",
      event: "online_review_round_retrigger",
      phase: "final",
      roundTriggerHeadOid: fixSha,
      roundTriggerAt: retriggerTs,
      onlineReviewRound: 2,
      pr,
      ts: retriggerTs,
    };

    // crash after fix_committed, before/during retrigger network;
    // resume ACTION: POST retrigger (idempotent) + persist marker + poll (symmetric)
    expect(onlineReviewRoundFromFamilyLedger([fixCommittedOnly])).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromFamilyLedger([fixCommittedOnly])).toBe(fixSha);
    const gapTrigger = familyPendingRoundTriggerFromFixGap([fixCommittedOnly]);
    expect(gapTrigger).toEqual(buildRoundTrigger(fixSha, fixTs));
    expect(
      resolveOnlineReviewRoundTrigger({
        onlineReviewRound: 2,
        pendingRetriggerFromFixGap: gapTrigger,
        shipPrHead: "headsha1",
        shipLedgerTriggeredAt: SHIP_LEDGER_TS,
      }),
    ).toEqual(gapTrigger);
    expect(onlineReviewRoundTriggerFromFamilyLedger([fixCommittedOnly])).toBeUndefined();

    // happy path
    expect(onlineReviewRoundFromFamilyLedger([fixCommittedOnly, retrigger])).toBe(2);
    expect(onlineReviewRoundTriggerFromFamilyLedger([fixCommittedOnly, retrigger])).toEqual(
      buildRoundTrigger(fixSha, retriggerTs),
    );

    // legacy r29: retrigger-only backward compat (round only, not fix SHA)
    expect(onlineReviewRoundFromFamilyLedger([retrigger])).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromFamilyLedger([retrigger])).toBeUndefined();
  });

  it("pin r31: family multi-round crash gap uses max(fixCommitted+1, retrigger round)", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const familyLedger: FamilyLedgerEntry[] = [
      {
        status: "online_review_fix_committed",
        event: "online_review_fix_committed",
        phase: "final",
        familyHeadAfter: fixSha,
        ts: fixTs,
      },
      {
        status: "online_review_round_retrigger",
        event: "online_review_round_retrigger",
        phase: "final",
        roundTriggerHeadOid: fixSha,
        roundTriggerAt: retriggerTs,
        onlineReviewRound: 3,
        ts: retriggerTs,
      },
    ];
    expect(onlineReviewRoundFromFamilyLedger(familyLedger)).toBe(3);
  });

  it("pin r32: round-1 persisted trigger + round-2 fix-gap → newer fix-gap wins", () => {
    const round1Persisted = buildRoundTrigger(
      "fixsha1111111111111111111111111111111111",
      "2026-07-08T10:00:00.000Z",
    );
    const round2Gap = buildRoundTrigger(
      "fixsha2222222222222222222222222222222222",
      "2026-07-08T12:30:00.000Z",
    );
    const resolved = resolveOnlineReviewRoundTrigger({
      onlineReviewRound: 2,
      persistedRoundTrigger: round1Persisted,
      pendingRetriggerFromFixGap: round2Gap,
    });
    expect(resolved).toEqual(round2Gap);
  });

  it("pin r32: persisted retrigger newer than fix-gap → persisted wins", () => {
    const gapTrigger = buildRoundTrigger(
      "fixsha1111111111111111111111111111111111",
      "2026-07-08T12:00:00.000Z",
    );
    const persistedTrigger = buildRoundTrigger(
      "fixsha1111111111111111111111111111111111",
      "2026-07-08T13:00:00.000Z",
    );
    const resolved = resolveOnlineReviewRoundTrigger({
      onlineReviewRound: 2,
      persistedRoundTrigger: persistedTrigger,
      pendingRetriggerFromFixGap: gapTrigger,
    });
    expect(resolved).toEqual(persistedTrigger);
  });

  it("pin r26: family ledger restores round/trigger/fix SHA", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const familyLedger: FamilyLedgerEntry[] = [
      {
        status: "online_review_round_retrigger",
        event: "online_review_round_retrigger",
        phase: "final",
        roundTriggerHeadOid: fixSha,
        roundTriggerAt: RETRIGGER_TS,
        onlineReviewRound: 2,
      },
      {
        status: "online_review_fix_committed",
        event: "online_review_fix_committed",
        phase: "final",
        familyHeadAfter: fixSha,
      },
    ];
    expect(onlineReviewRoundFromFamilyLedger(familyLedger)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromFamilyLedger(familyLedger)).toBe(fixSha);
    expect(onlineReviewRoundTriggerFromFamilyLedger(familyLedger)).toEqual(
      buildRoundTrigger(fixSha, RETRIGGER_TS),
    );
  });
});

describe("#600 r26 runner-owned isRecheck", () => {
  it("round ≥2 normalizes omitted isRecheck to true", () => {
    const normalized = enforceRunnerOwnedRecheck(
      { kind: "verify", converged: true },
      2,
    );
    expect(normalized).toEqual({ kind: "verify", converged: true, isRecheck: true });
  });

  it("#877: round ≥2 with explicit isRecheck:false force-normalizes (no contradiction kill)", () => {
    expect(
      enforceRunnerOwnedRecheck(
        { kind: "verify", converged: true, isRecheck: false },
        2,
      ),
    ).toEqual({ kind: "verify", converged: true, isRecheck: true });
  });

  it("pin r26: stage post-fixer verify omitting isRecheck still applies fixing SHA", async () => {
    let fixingSha: string | undefined;
    const pinKey = "pin:r26";
    const result = await runOnlineReviewLoopStage(
      {
        kind: "ship",
        branch: "feat/x",
        status: "pr_opened",
        pr: "https://github.com/test/repo/pull/601",
        prHead: "head-1",
      },
      {
        poll: async () => ({
          repo: "o/r",
          prNumber: 1,
          prUrl: "https://github.com/test/repo/pull/601",
          headOid: "head-1",
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
        }),
        dispatchVerify: async (_landing, round) => {
          if (round === 1) {
            return {
              kind: "verify",
              converged: false,
              fixMarkedFindingIdentityKeys: [pinKey],
              findingDispositions: [
                { identityKey: pinKey, threadId: "1", action: "fix" },
              ],
            };
          }
          return {
            kind: "verify",
            converged: true,
            fixMarkedFindingIdentityKeys: [pinKey],
          };
        },
        dispatchFixer: async () => fixerCommitted(),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
        resolveFixCommitSha: async (envelopeFixSha) => {
          // #940 / K1: envelope SHA is host-owned via resolveFixCommitSha only
          // (not via applySideEffects). GH cargo remains dual-owner: worker first,
          // host fail-safe applySideEffects still applies residual plan.
          fixingSha = envelopeFixSha;
          return "fix-sha-round1";
        },
      },
      { initialRound: 1 },
    );
    expect(result.ok).toBe(true);
    expect(fixingSha).toBe(FIXER_ENVELOPE_SHA);
  });

  it("#743: post-fixer recheck receives and must echo every fix-marked identity key before it can converge", async () => {
    const expectedKey = "thread:fixer-claimed";
    let recheckLanding: WorkerLandingPayload | undefined;
    const result = await runOnlineReviewLoopStage(
      {
        kind: "ship",
        branch: "feat/x",
        status: "pr_opened",
        pr: "https://github.com/test/repo/pull/601",
        prHead: "head-1",
      },
      {
        poll: async () => ({
          repo: "o/r",
          prNumber: 1,
          prUrl: "https://github.com/test/repo/pull/601",
          headOid: "head-1",
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
        }),
        dispatchVerify: async (landing, round) => {
          if (round === 1) {
            return {
              kind: "verify",
              converged: false,
              fixMarkedFindingIdentityKeys: [expectedKey],
              findingDispositions: [
                { identityKey: expectedKey, threadId: "1", action: "fix" },
              ],
            };
          }
          recheckLanding = landing;
          // A fixer can claim success without repairing anything. Bare convergence
          // does not prove that this specific finding was actually rechecked.
          return { kind: "verify", converged: true };
        },
        dispatchFixer: async () => fixerCommitted(),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
      },
    );

    expect(recheckLanding?.fixMarkedFindingIdentityKeys).toEqual([expectedKey]);
    expect(recheckLanding?.fixMarkedFindingThreads).toEqual([
      { identityKey: expectedKey, threadId: "1" },
    ]);
    // #877: bare post-fixer converge without echoing fix-marked keys ships —
    // echo coverage court demolished.
    expect(result).toEqual({
      ok: true,
      terminalState: "mergeable",
      round: 2,
    });
  });
});

describe("#600 r5 runOnlineReviewLoopStage — stage-level regression", () => {
  const stageShip = {
    kind: "ship" as const,
    branch: "family/epic-600",
    status: "pr_opened",
    pr: "https://github.com/test/repo/pull/602",
    prHead: "head-1",
  };
  const baseSnapshot: PrReviewSnapshot = {
    repo: "o/r",
    prNumber: 42,
    prUrl: "https://github.com/test/repo/pull/602",
    headOid: "head-1",
    pollCount: 1,
    bots: {
      coderabbit: { state: "complete", findingCount: 0 },
      sourcery: { state: "complete", findingCount: 0 },
      codex: { state: "complete", findingCount: 0 },
      gemini: { state: "complete", findingCount: 0 },
    },
    threads: [],
    checkRuns: [],
    totalFindingCount: 0,
    quiescent: true,
    roundTriggerUsed: TEST_ROUND_TRIGGER,
    checkRunsEmptyMeans: "converged",
  };

  it("happy path: converged verify → cleanup → landing terminates mergeable", async () => {
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async () => {
        verifyCalls += 1;
        return { kind: "verify", converged: true } satisfies VerifyResult;
      },
      dispatchFixer: async () => fixerCommitted(),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 1 });
    expect(verifyCalls).toBe(1);
  });



  it("pin deep self-check R8: CI failed + no fix marks parks without fixer", async () => {
    let fixerCalls = 0;
    let accountedVerify: VerifyResult | undefined;
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => ({
        ...baseSnapshot,
        checkRuns: [
          {
            id: 1,
            name: "ci",
            headSha: "head-1",
            status: "completed",
            conclusion: "failure",
          },
        ],
      }),
      dispatchVerify: async () => {
        // #940 / K1: capture worker disposition at the verify dispatch seam.
        // Host still applies residual cargo via applySideEffects (fail-safe).
        accountedVerify = { kind: "verify", converged: true };
        return accountedVerify;
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return fixerNotFixed();
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(fixerCalls).toBe(0);
    expect(accountedVerify).toEqual(
      expect.objectContaining({ kind: "verify", converged: true }),
    );
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate_raised");
    expect(result.stopSummary?.summary).toMatch(/CI check-runs failed/i);
  });

  it("pin online R2 Codex P2: pending CI re-polls — does not dispatch fixer", async () => {
    let pollCalls = 0;
    let verifyCalls = 0;
    let fixerCalls = 0;
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => {
        pollCalls += 1;
        if (pollCalls === 1) {
          return {
            ...baseSnapshot,
            checkRuns: [
              {
                id: 1,
                name: "ci",
                headSha: "head-1",
                status: "in_progress",
              },
            ],
          };
        }
        return baseSnapshot;
      },
      dispatchVerify: async () => {
        verifyCalls += 1;
        return { kind: "verify", converged: true } satisfies VerifyResult;
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return fixerCommitted();
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 1 });
    expect(pollCalls).toBe(2);
    expect(verifyCalls).toBe(2);
    expect(fixerCalls).toBe(0);
  });

  it("#934 ID-004: pending CI keeps re-polling past bot overdue window — no host fail", async () => {
    // Bot overdue window is for bots only. Pending-CI-only must sleep+continue
    // with no finite BOT_OVERDUE terminal, then proceed when CI goes terminal.
    let pollCalls = 0;
    let verifyCalls = 0;
    let fixerCalls = 0;
    const pendingPolls = BOT_OVERDUE_POLL_COUNT + 2;
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => {
        pollCalls += 1;
        if (pollCalls <= pendingPolls) {
          return {
            ...baseSnapshot,
            checkRuns: [
              {
                id: 1,
                name: "ci",
                headSha: "head-1",
                status: "in_progress",
              },
            ],
          };
        }
        return baseSnapshot;
      },
      dispatchVerify: async () => {
        verifyCalls += 1;
        return { kind: "verify", converged: true } satisfies VerifyResult;
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return fixerCommitted();
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("mergeable");
    expect(result.stopSummary?.summary ?? "").not.toMatch(
      /stayed non-terminal past the overdue poll window/i,
    );
    // N pending-CI polls + 1 clear poll after CI terminal.
    expect(pollCalls).toBe(pendingPolls + 1);
    expect(verifyCalls).toBe(pendingPolls + 1);
    expect(fixerCalls).toBe(0);
  });

  it("pin r22: stage landing shipDelivery.branch threads the real ship branch", async () => {
    let landingBranch: string | undefined;
    await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async (landing) => {
        landingBranch = landing.shipDelivery?.branch;
        return { kind: "verify", converged: true } satisfies VerifyResult;
      },
      dispatchFixer: async () => fixerCommitted(),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(landingBranch).toBe("family/epic-600");
  });




  it("#940: persistent non-convergence is worker escalate — host never mints round_budget_exhausted", async () => {
    let roundSeen = 0;
    let fixerCalls = 0;
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async (round) => {
        roundSeen = round;
        return { ...baseSnapshot, pollCount: round };
      },
      dispatchVerify: async (_landing, round) => {
        verifyCalls += 1;
        if (round >= 5) {
          return {
            kind: "verify",
            converged: false,
            terminalState: "decision_gate_raised",
          } satisfies VerifyResult;
        }
        return { kind: "verify", converged: false } satisfies VerifyResult;
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return fixerCommitted();
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async () => "fix-sha",
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate_raised");
    expect(fixerCalls).toBe(4);
    expect(verifyCalls).toBe(5);
    expect(roundSeen).toBe(5);
  });

  it("#940: multi-round continue past former cap still converges when worker greens", async () => {
    let roundSeen = 0;
    let fixerCalls = 0;
    let verifyCalls = 0;
    const budgetKey = "budget:1";
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async (round) => {
        roundSeen = round;
        return { ...baseSnapshot, pollCount: round };
      },
      dispatchVerify: async (_landing, round) => {
        verifyCalls += 1;
        if (round >= 5) {
          return {
            kind: "verify",
            converged: true,
            fixMarkedFindingIdentityKeys: [budgetKey],
          } satisfies VerifyResult;
        }
        return {
          kind: "verify",
          converged: false,
          findingDispositions: [
            { identityKey: budgetKey, threadId: "1", action: "fix" },
          ],
          fixMarkedFindingIdentityKeys: [budgetKey],
        } satisfies VerifyResult;
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return fixerCommitted();
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async () => "fix-sha",
    });
    expect(result).toEqual({
      ok: true,
      terminalState: "mergeable",
      round: 5,
    });
    expect(fixerCalls).toBe(4);
    expect(verifyCalls).toBe(5);
    expect(roundSeen).toBe(5);
  });

  it("committed:false returns through fresh verify findings instead of ending the run", async () => {
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async () => {
        verifyCalls += 1;
        return verifyCalls === 2
          ? {
              kind: "verify",
              converged: true,
              isRecheck: true,
              fixMarkedFindingIdentityKeys: ["no-fix:1"],
            }
          : {
              kind: "verify",
              converged: false,
              findingDispositions: [
                { identityKey: "no-fix:1", threadId: "thread-no-fix", action: "fix" },
              ],
            };
      },
      dispatchFixer: async () => fixerNotFixed(),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 2 });
    expect(verifyCalls).toBe(2);
  });

  it("pin r23: only verifier decision signal parks with the decision-gate summary", async () => {
    const stageResult = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async () => ({
        kind: "verify",
        converged: false,
        terminalState: "decision_gate_raised",
      }),
      dispatchFixer: async () => fixerNotFixed(),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(stageResult.stopSummary).toEqual(
      onlineReviewFixerNothingToFixStopSummary(),
    );
    const familySummary =
      stageResult.stopSummary ?? {
        reason: "infra_failure" as const,
        summary: "fallback",
        repairHint: "fallback",
      };
    expect(familySummary.reason).toBe("decision_gate_park");
    expect(familySummary.reason).not.toBe("infra_failure");
  });

  it("pin r19: retriggerAfterFix throw → decision_gate_raised in-band with stopSummary", async () => {
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async () => ({ kind: "verify", converged: false }),
      dispatchFixer: async () => fixerCommitted(),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {
        throw new Error("retriggerBotsAndPoll: gh api failed");
      },
      resolveFixCommitSha: async () => "fix-sha",
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "decision_gate_raised",
      round: 1,
      stopSummary: expect.objectContaining({
        reason: "online_review_failed",
        summary: expect.stringMatching(
          /host operation failed.*retriggerBotsAndPoll/s,
        ),
      }),
    });
  });


  it("pin r20: poll throw → decision_gate_raised in-band with stopSummary", async () => {
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => {
        throw new Error("waitForBotQuiescence: gh api rate limited");
      },
      dispatchVerify: async () => ({ kind: "verify", converged: true }),
      dispatchFixer: async () => fixerCommitted(),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "decision_gate_raised",
      round: 1,
      stopSummary: expect.objectContaining({
        reason: "online_review_failed",
        summary: expect.stringMatching(/bot poll failed.*rate limited/s),
      }),
    });
  });

  it("pin r20: dispatchVerify throw → decision_gate_raised in-band with stopSummary", async () => {
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async () => {
        throw new Error("dispatchFamilyReviewWorker: container start failed");
      },
      dispatchFixer: async () => fixerCommitted(),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "decision_gate_raised",
      round: 1,
      stopSummary: expect.objectContaining({
        reason: "online_review_failed",
        summary: expect.stringMatching(/verify dispatch failed.*container start/s),
      }),
    });
  });

  it("pin r20: dispatchFixer throw → decision_gate_raised in-band with stopSummary", async () => {
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async () => ({ kind: "verify", converged: false }),
      dispatchFixer: async () => {
        throw new Error("dispatchFamilyReviewWorker: fixer residue unsafe");
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "decision_gate_raised",
      round: 1,
      stopSummary: expect.objectContaining({
        reason: "online_review_failed",
        summary: expect.stringMatching(/fixer dispatch failed.*residue unsafe/s),
      }),
    });
  });

  it("pin r33: fixer alreadySatisfied proceeds to re-verify (envelope fix SHA, no git re-read)", async () => {
    let resolveFixCalls = 0;
    let retriggerCalls = 0;
    let fixingSha: string | undefined;
    const pinKey = "pin:r33";
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async (_landing, round) => {
        if (round === 1) {
          return {
            kind: "verify",
            converged: false,
            findingDispositions: [
              { identityKey: pinKey, threadId: "1", action: "fix" },
            ],
          };
        }
        return {
          kind: "verify",
          converged: true,
          isRecheck: true,
          fixMarkedFindingIdentityKeys: [pinKey],
        };
      },
      dispatchFixer: async () => fixerAlreadySatisfied("crash-landed-sha"),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {
        retriggerCalls += 1;
      },
      resolveFixCommitSha: async (envelopeFixSha) => {
        resolveFixCalls += 1;
        expect(envelopeFixSha).toBe("crash-landed-sha");
        // #940 / K1: fixing SHA is owned by resolveFixCommitSha + recheck landing
        // only — not threaded through applySideEffects (which remains the dual-owner
        // host fail-safe for GH cargo, not SHA resolution).
        fixingSha = envelopeFixSha;
        return envelopeFixSha ?? "should-not-read-git";
      },
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 2 });
    expect(resolveFixCalls).toBe(1);
    expect(retriggerCalls).toBe(1);
    expect(fixingSha).toBe("crash-landed-sha");
  });

  it("pin r39: committed:true fixCommitSha keys recheck via envelope only (no live HEAD)", async () => {
    const envelopeSha = "envelopefixsha111111111111111111111111";
    const driftHeadOid = "live-head-would-be-wrong-if-read";
    let resolveFixCalls = 0;
    let fixingSha: string | undefined;
    const pinKey = "pin:r39";
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => ({ ...baseSnapshot, headOid: driftHeadOid }),
      dispatchVerify: async (_landing, round) => {
        if (round === 1) {
          return {
            kind: "verify",
            converged: false,
            findingDispositions: [
              { identityKey: pinKey, threadId: "1", action: "fix" },
            ],
          };
        }
        return {
          kind: "verify",
          converged: true,
          isRecheck: true,
          fixMarkedFindingIdentityKeys: [pinKey],
        };
      },
      dispatchFixer: async () => fixerCommitted(envelopeSha),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async (envelopeFixSha) => {
        resolveFixCalls += 1;
        expect(envelopeFixSha).toBe(envelopeSha);
        fixingSha = envelopeFixSha;
        return envelopeFixSha;
      },
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 2 });
    expect(resolveFixCalls).toBe(1);
    expect(fixingSha).toBe(envelopeSha);
    expect(fixingSha).not.toBe(driftHeadOid);
  });

  it("completed fixer with sparse cargo dispatches once, then returns through fresh verify", async () => {
    const malformed = { kind: "fixer", committed: true } as FixerResult;
    let fixerCalls = 0;
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async () => {
        verifyCalls += 1;
        return verifyCalls === 2
          ? {
              kind: "verify",
              converged: true,
              isRecheck: true,
              fixMarkedFindingIdentityKeys: ["missing-sha:1"],
            }
          : {
              kind: "verify",
              converged: false,
              findingDispositions: [
                { identityKey: "missing-sha:1", threadId: "thread-missing-sha", action: "fix" },
              ],
            };
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return malformed;
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {
        throw new Error("retriggerAfterFix must not run for malformed fixer envelope");
      },
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 2 });
    expect(fixerCalls).toBe(1);
    expect(verifyCalls).toBe(2);
  });

  it("pin r40: retrigger-only ledger yields no fix SHA (family, envelope-only)", () => {
    const liveHead = "live-pr-head-not-envelope-fix-sha111111111";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const retriggerOnly: FamilyLedgerEntry[] = [
      {
        status: "online_review_round_retrigger",
        event: "online_review_round_retrigger",
        phase: "final",
        roundTriggerHeadOid: liveHead,
        roundTriggerAt: retriggerTs,
        onlineReviewRound: 2,
      },
    ];
    expect(onlineReviewRoundFromFamilyLedger(retriggerOnly)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromFamilyLedger(retriggerOnly)).toBeUndefined();
    expect(onlineReviewRoundTriggerFromFamilyLedger(retriggerOnly)).toEqual(
      buildRoundTrigger(liveHead, retriggerTs),
    );
  });

  it("pin r40: family fix_committed marker preserves the envelope SHA", () => {
    const envelopeSha = "envelopefixsha111111111111111111111111";
    const liveHead = "live-pr-head-would-be-wrong-if-used1111";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const familyFixCommitted: FamilyLedgerEntry[] = [
      {
        status: "online_review_fix_committed",
        event: "online_review_fix_committed",
        phase: "final",
        familyHeadAfter: envelopeSha,
      },
      {
        status: "online_review_round_retrigger",
        event: "online_review_round_retrigger",
        phase: "final",
        roundTriggerHeadOid: liveHead,
        roundTriggerAt: retriggerTs,
        onlineReviewRound: 2,
      },
    ];
    expect(lastOnlineReviewFixCommitShaFromFamilyLedger(familyFixCommitted)).toBe(
      envelopeSha,
    );
  });


  it("pin r33 family: fixer alreadySatisfied records fix marker path via envelope SHA", async () => {
    let recordedSha: string | undefined;
    const pinKey = "pin:r33-family";
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async (_landing, round) => {
        if (round === 1) {
          return {
            kind: "verify",
            converged: false,
            findingDispositions: [
              { identityKey: pinKey, threadId: "1", action: "fix" },
            ],
          };
        }
        return {
          kind: "verify",
          converged: true,
          isRecheck: true,
          fixMarkedFindingIdentityKeys: [pinKey],
        };
      },
      dispatchFixer: async () => fixerAlreadySatisfied("family-landed-sha"),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async (envelopeFixSha) => {
        expect(envelopeFixSha).toBe("family-landed-sha");
        recordedSha = envelopeFixSha;
        return envelopeFixSha!;
      },
    });
    expect(result.ok).toBe(true);
    expect(recordedSha).toBe("family-landed-sha");
  });

  it("pin r17: worker converged:true + red CI parks with CI failure (no fixer)", async () => {
    let fixerCalls = 0;
    const snapshotWithRedCi: PrReviewSnapshot = {
      ...baseSnapshot,
      checkRuns: [
        {
          id: 1,
          name: "ci",
          headSha: "head-1",
          status: "completed",
          conclusion: "failure",
        },
      ],
    };
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => snapshotWithRedCi,
      dispatchVerify: async () => ({ kind: "verify", converged: true }),
      dispatchFixer: async () => {
        fixerCalls += 1;
        return fixerNotFixed();
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    // Deep self-check R8: do not dispatch fixer with empty fix marks on CI red
    // (misleading "nothing to fix while findings remain").
    expect(fixerCalls).toBe(0);
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate_raised");
    expect(result.stopSummary?.summary).toMatch(/CI check-runs failed/i);
  });
});

describe("#600 r5 legacy skeleton gate — family", () => {
  const liveCtx: DispatchContext = {
    familyBase: "fb",
    repo: "o/r",
    prUrl: "https://github.com/o/r/pull/42",
  };

  const worktree: WorktreeHandle = {
    branch: "feat/x",
    base: "main",
    path: "/wt",
  };

  it("pin family legacy path: unavailable primary on live PR → failed, not skeleton-green", async () => {
    const spec = verifyWorkerSpec();
    const result = await legacyDispatchFamilyWorker({} as never, spec, liveCtx);
    expect(result.kind).toBe("failed");
    if (result.kind === "failed") {
      expect(result.reason).toContain("offline skeleton synthesis inadmissible");
    }
  });

  it("offline test handle still admits skeleton on the family legacy path", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      const spec = verifyWorkerSpec();
      const result = await legacyDispatchFamilyWorker({} as never, spec, {
        familyBase: "fb",
        repo: "o/r",
        prUrl: "pr://family/offline",
      });
      expect(result.kind).toBe("completed");
      if (result.kind === "completed" && result.output.kind === "verify") {
        expect(result.output.converged).toBe(true);
      }
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

});

describe("#600 r7 family online review — cleanup landing + in-band failures", () => {
  class ReviewLoopFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

    readonly reviewLoopLandings: WorkerLandingPayload[] = [];
    readonly ledger: FamilyLedgerEntry[] = [];
    readFamilyHead?: (familyBase: string) => Promise<string>;
    readFamilyTrackedStatus?: (familyBase: string) => Promise<readonly string[]>;

    async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
      return { familyHead: "fb-head" };
    }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

    async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
      this.ledger.push(entry);
    }
    async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
      return this.ledger;
    }
    async dispatchWorker(
      spec: WorkerSpec,
      _ctx: DispatchContext,
      landing?: WorkerLandingPayload,
    ): Promise<WorkerResult> {
      if (
        (spec.kind === "cleanup" || spec.kind === "landing") &&
        landing !== undefined
      ) {
        this.reviewLoopLandings.push(landing);
      }
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      if (skeleton !== undefined) return skeleton;
      return { kind: "failed", reason: `unexpected ${spec.kind}` };
    }
  }

  const offlineShip = {
    kind: "ship" as const,
    branch: "family/r7",
    pr: "https://github.com/test/repo/pull/607",
    prHead: "head-r7",
    status: "pr_opened" as const,
  };

  it("happy path passes onlineReviewSnapshot landing into landing (cleanup is post-merge)", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      const backend = new ReviewLoopFamilyBackend();
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 1 });
      // #941: online-review ends at mergeable; landing Action owns docs/merge.
      expect(backend.reviewLoopLandings.length).toBeGreaterThanOrEqual(0);
      expect(
        backend.reviewLoopLandings.every(
          (l) => l.onlineReviewSnapshot !== undefined,
        ),
      ).toBe(true);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("#853 family verify receipt routes without a tracked-status court", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      let trackedStatus: string[] = [];
      let trackedStatusReads = 0;
      const backend = new ReviewLoopFamilyBackend();
      backend.readFamilyHead = async () => "head-before";
      backend.readFamilyTrackedStatus = async () => {
        trackedStatusReads += 1;
        return trackedStatus;
      };
      backend.dispatchWorker = async (spec) => {
        if (spec.kind === "verify") {
          trackedStatus = [" M orchestrator/src/foo.ts"];
          return {
            kind: "completed",
            output: { kind: "verify", converged: true },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result).toEqual(expect.objectContaining({ ok: true, round: 1 }));
      expect(trackedStatusReads).toBe(0);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("routes completed sparse verify cargo to fixer, then fresh verify", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      let verifyCalls = 0;
      let fixerCalls = 0;
      let fixerLanding: WorkerLandingPayload | undefined;
      const backend = new ReviewLoopFamilyBackend();
      backend.dispatchWorker = async (spec, _ctx, landing) => {
        if (spec.kind === "verify") {
          verifyCalls += 1;
          return verifyCalls === 1
            ? {
                kind: "completed",
                output: { kind: "coder", committed: false, commitsAdded: 0 },
                sessionId: "sparse-verify-session",
              }
            : {
                kind: "completed",
                output: { kind: "verify", converged: true },
              };
        }
        if (spec.kind === "fixer") {
          fixerCalls += 1;
          fixerLanding = landing;
          return {
            kind: "completed",
            output: { kind: "fixer", committed: false },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };

      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });

      expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 2 });
      expect(verifyCalls).toBe(2);
      expect(fixerCalls).toBe(1);
      expect(fixerLanding?.rawReviewerArtifacts).toMatchObject({
        reviewerSessionId: "sparse-verify-session",
      });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("passes raw verify artifacts to fixer even when structured cargo survives", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      let verifyCalls = 0;
      let fixerLanding: WorkerLandingPayload | undefined;
      const backend = new ReviewLoopFamilyBackend();
      backend.dispatchWorker = async (spec, _ctx, landing) => {
        if (spec.kind === "verify") {
          verifyCalls += 1;
          return verifyCalls === 1
            ? {
                kind: "completed",
                output: {
                  kind: "verify",
                  converged: false,
                  findingDispositions: [
                    {
                      identityKey: "correctness|src/a.ts:1|survivor",
                      threadId: "thread-survivor",
                      action: "fix",
                    },
                  ],
                },
                sessionId: "verify-partial-cargo-session",
              }
            : {
                kind: "completed",
                output: { kind: "verify", converged: true },
              };
        }
        if (spec.kind === "fixer") {
          fixerLanding = landing;
          return {
            kind: "completed",
            output: { kind: "fixer", committed: false },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };

      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });

      expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 2 });
      expect(fixerLanding?.rawReviewerArtifacts).toMatchObject({
        reviewerSessionId: "verify-partial-cargo-session",
        statement: "the previous reviewer raw artifacts are here",
      });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("completed landing without receipt cargo remains mergeable", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      const backend = new ReviewLoopFamilyBackend();
      backend.dispatchWorker = async (spec) => {
        if (spec.kind === "verify") {
          return {
            kind: "completed",
            output: { kind: "verify", converged: true },
          };
        }
        if (spec.kind === "landing") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: false, commitsAdded: 0 },
          };
        }
        return { kind: "failed", reason: `unexpected ${spec.kind}` };
      };

      await expect(
        runFamilyOnlineReviewLoop({
          familyBackend: backend,
          familyBase: "family/r7",
          ship: offlineShip,
        }),
      ).resolves.toEqual({ ok: true, terminalState: "mergeable", round: 1 });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("#876 family verify receipt routes without a HEAD court", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      let headReadCount = 0;
      const backend = new ReviewLoopFamilyBackend();
      backend.readFamilyHead = async () => {
        headReadCount += 1;
        return headReadCount === 1 ? "head-before" : "head-after";
      };
      backend.dispatchWorker = async (spec) => {
        if (spec.kind === "verify") {
          return {
            kind: "completed",
            output: { kind: "verify", converged: true },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result).toEqual(expect.objectContaining({ ok: true, round: 1 }));
      expect(headReadCount).toBe(0);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("#876 family verify that mutates HEAD then throws retries the throw (no git-truth death)", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      let attempts = 0;
      let headReadCount = 0;
      const backend = new ReviewLoopFamilyBackend();
      backend.readFamilyHead = async () => {
        headReadCount += 1;
        // attempt N: before=read1, after throw assert=read2 → head moved
        return headReadCount === 1 ? "head-before" : "head-after";
      };
      backend.dispatchWorker = async (spec) => {
        if (spec.kind === "verify") {
          attempts += 1;
          throw new Error("verify worker threw on startup");
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      // HEAD drift no longer short-circuits retries as contract_drift.
      expect(attempts).toBe(MAX_DISPATCH_ATTEMPTS);
      expect(result).toEqual(expect.objectContaining({ ok: false, round: 1 }));
      expect(result.terminalState).not.toBe("contract_drift");
      expect(backend.ledger).toContainEqual(expect.objectContaining({
        workerStep: "verify",
        mechanicalRedispatchAttempt: 1,
        reason: expect.stringContaining("verify worker threw on startup"),
      }));
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("pin r10: a verify process throw retries without consulting tracked cargo", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      let attempts = 0;
      let trackedStatus: string[] = [];
      const backend = new ReviewLoopFamilyBackend();
      backend.readFamilyHead = async () => "head-before";
      backend.readFamilyTrackedStatus = async () => trackedStatus;
      backend.dispatchWorker = async (spec) => {
        if (spec.kind === "verify") {
          attempts += 1;
          trackedStatus = [" M orchestrator/src/foo.ts"];
          throw new Error("verify worker threw on startup");
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(attempts).toBe(MAX_DISPATCH_ATTEMPTS);
      expect(result).toEqual(expect.objectContaining({ ok: false, round: 1 }));
      expect(backend.ledger).toContainEqual(expect.objectContaining({
        workerStep: "verify",
        mechanicalRedispatchAttempt: 1,
        reason: expect.stringContaining("verify worker threw on startup"),
      }));
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("pin r37: family verify that throws transient error without mutation still retries fresh (#598)", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      let attempts = 0;
      const backend = new ReviewLoopFamilyBackend();
      backend.readFamilyHead = async () => "head-before";
      backend.readFamilyTrackedStatus = async () => [];
      backend.dispatchWorker = async (spec) => {
        if (spec.kind === "verify") {
          attempts += 1;
          if (attempts === 1) throw new Error("verify worker threw on startup");
          return {
            kind: "completed",
            output: { kind: "verify", converged: true },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(attempts).toBe(2);
      expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 1 });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("pin r11: family verify escalated parks with decision_gate_park + escalate text", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      const backend = new ReviewLoopFamilyBackend();
      backend.dispatchWorker = async (spec) => {
        if (spec.kind === "verify") {
          return {
            kind: "escalated",
            escalation: {
              reason: "stuck on ambiguous finding",
              diagnosis: "need human disposition on thread T1",
              options: ["accept", "defer"],
            },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result).toEqual({
        ok: false,
        terminalState: "decision_gate_raised",
        round: 1,
        stopSummary: expect.objectContaining({
          reason: "decision_gate_park",
          summary: expect.stringContaining("stuck on ambiguous finding"),
        }),
      });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("pin r11: family fixer escalated parks with decision_gate_park + escalate text", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      const backend = new ReviewLoopFamilyBackend();
      backend.dispatchWorker = async (spec) => {
        if (spec.kind === "verify") {
          return {
            kind: "completed",
            output: {
              kind: "verify",
              converged: false,
              findings: [
                {
                  identityKey: "f1",
                  severity: "P2",
                  claim_quote: "need a fix",
                  path: "x.ts",
                },
              ],
              dispositions: [
                {
                  identityKey: "f1",
                  action: "fix",
                  reason: "real",
                },
              ],
            },
          };
        }
        if (spec.kind === "fixer") {
          return {
            kind: "escalated",
            escalation: {
              reason: "cannot apply fix safely",
              diagnosis: "conflicting prior commit",
              options: ["manual fix", "abort"],
            },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result).toEqual({
        ok: false,
        terminalState: "decision_gate_raised",
        round: 1,
        stopSummary: expect.objectContaining({
          reason: "decision_gate_park",
          summary: expect.stringContaining("cannot apply fix safely"),
        }),
      });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("verify dispatch failure returns decision_gate_raised in-band (no throw)", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      const backend = new ReviewLoopFamilyBackend();
      backend.dispatchWorker = async (spec) => {
        if (spec.kind === "verify") {
          return { kind: "failed", reason: "verify worker unavailable" };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        return skeleton ?? { kind: "failed", reason: "unexpected" };
      };
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result).toEqual({
        ok: false,
        terminalState: "decision_gate_raised",
        round: 1,
        stopSummary: expect.objectContaining({
          reason: "online_review_failed",
          summary: expect.stringContaining("verify worker unavailable"),
        }),
      });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("#743 online R1: family rebuild accepts the production recordOnlineReviewFixCommitted row shape", async () => {
    // Gemini alleged status-only rows; pin the real writer output and rebuild from it.
    class CaptureFamilyBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

      readonly appended: FamilyLedgerEntry[] = [];
      async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
        return { familyHead: "head" };
      }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
  }

      async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
        this.appended.push(entry);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.appended;
      }
    }
    const backend = new CaptureFamilyBackend();
    const authKey = "finding:prod-shape";
    const authThread = "4242";
    await recordOnlineReviewFixCommitted(backend, {
      familyHeadAfter: "fixsha1111111111111111111111111111111111",
      pr: "https://github.com/o/r/pull/42",
      onlineReviewRound: 1,
      fixMarkedFindingIdentityKeys: [authKey],
      fixMarkedFindingThreads: [{ identityKey: authKey, threadId: authThread }],
    });
    expect(backend.appended).toHaveLength(1);
    const productionRow = backend.appended[0]!;
    // Production writer stamps BOTH status and event (not status-only).
    expect(productionRow.status).toBe("online_review_fix_committed");
    expect(productionRow.event).toBe("online_review_fix_committed");
    expect(
      lastFixMarkedFindingAuthorizationFromFamilyLedger([productionRow]),
    ).toEqual({
      fixMarkedFindingIdentityKeys: [authKey],
      fixMarkedFindingThreads: [{ identityKey: authKey, threadId: authThread }],
    });
  });

  it("#743 R4: family resume fails closed when a legacy key-only marker is echoed without thread authorization", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const fixSha = "fixsha1111111111111111111111111111111111";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    try {
      class ResumeFamilyBackend extends ReviewLoopFamilyBackend {
        readonly verifyRounds: number[] = [];
        readonly verifyLandings: WorkerLandingPayload[] = [];
        override async dispatchWorker(
          spec: WorkerSpec,
          ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
          if (spec.kind === "verify") {
            this.verifyRounds.push(ctx.onlineReviewRound ?? landing?.onlineReviewRound ?? 0);
            if (landing !== undefined) this.verifyLandings.push(landing);
            return {
              kind: "completed",
              output: {
                kind: "verify",
                converged: true,
                isRecheck: true,
                fixMarkedFindingIdentityKeys: ["finding:r3"],
              },
            };
          }
          const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
          return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
        }
      }
      const backend = new ResumeFamilyBackend();
      backend.ledger.push(
        {
          status: "online_review_round_retrigger",
          event: "online_review_round_retrigger",
          phase: "final",
          roundTriggerHeadOid: fixSha,
          roundTriggerAt: retriggerTs,
          onlineReviewRound: 2,
          pr: offlineShip.pr,
        },
        {
          status: "online_review_fix_committed",
          event: "online_review_fix_committed",
          phase: "final",
          familyHeadAfter: fixSha,
          pr: offlineShip.pr,
          fixMarkedFindingIdentityKeys: ["finding:r3"],
        },
      );
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      // #877: legacy key-only marker without thread authorization survives —
      // fix-marked echo court demolished.
      expect(result).toEqual({
        ok: true,
        terminalState: "mergeable",
        round: 2,
      });
      expect(backend.verifyRounds).toEqual([2]);
      expect(backend.verifyLandings[0]?.fixMarkedFindingIdentityKeys).toEqual([
        "finding:r3",
      ]);
      expect(backend.verifyLandings[0]?.fixMarkedFindingThreads).toEqual([]);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("#877: family resume admits bare converge when all-empty marker (echo court demolished)", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const fixSha = "fixsha2222222222222222222222222222222222";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    try {
      class EmptyAuthFamilyBackend extends ReviewLoopFamilyBackend {
        readonly verifyLandings: WorkerLandingPayload[] = [];
        override async dispatchWorker(
          spec: WorkerSpec,
          ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
          if (spec.kind === "verify") {
            if (landing !== undefined) this.verifyLandings.push(landing);
            return {
              kind: "completed",
              output: { kind: "verify", converged: true, isRecheck: true },
            };
          }
          const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
          return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
        }
      }
      const backend = new EmptyAuthFamilyBackend();
      backend.ledger.push(
        {
          status: "online_review_round_retrigger",
          event: "online_review_round_retrigger",
          phase: "final",
          roundTriggerHeadOid: fixSha,
          roundTriggerAt: retriggerTs,
          onlineReviewRound: 2,
          pr: offlineShip.pr,
        },
        {
          status: "online_review_fix_committed",
          event: "online_review_fix_committed",
          phase: "final",
          familyHeadAfter: fixSha,
          pr: offlineShip.pr,
        },
      );
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result).toEqual({
        ok: true,
        terminalState: "mergeable",
        round: 2,
      });
      expect(backend.verifyLandings[0]?.fixMarkedFindingIdentityKeys).toEqual([]);
      expect(backend.verifyLandings[0]?.fixMarkedFindingThreads).toEqual([]);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("#743 R6: family resume with complete thread bindings echoes and merges", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const fixSha = "fixsha3333333333333333333333333333333333";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const authKey = "finding:r6-success";
    const authThread = "4242";
    try {
      class SuccessFamilyBackend extends ReviewLoopFamilyBackend {
        readonly verifyLandings: WorkerLandingPayload[] = [];
        override async dispatchWorker(
          spec: WorkerSpec,
          ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
          if (spec.kind === "verify") {
            if (landing !== undefined) this.verifyLandings.push(landing);
            return {
              kind: "completed",
              output: {
                kind: "verify",
                converged: true,
                isRecheck: true,
                fixMarkedFindingIdentityKeys: [...(landing?.fixMarkedFindingIdentityKeys ?? [])],
              },
            };
          }
          const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
          return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
        }
      }
      const backend = new SuccessFamilyBackend();
      backend.ledger.push(
        {
          status: "online_review_round_retrigger",
          event: "online_review_round_retrigger",
          phase: "final",
          roundTriggerHeadOid: fixSha,
          roundTriggerAt: retriggerTs,
          onlineReviewRound: 2,
          pr: offlineShip.pr,
        },
        {
          status: "online_review_fix_committed",
          event: "online_review_fix_committed",
          phase: "final",
          familyHeadAfter: fixSha,
          pr: offlineShip.pr,
          fixMarkedFindingIdentityKeys: [authKey],
          fixMarkedFindingThreads: [{ identityKey: authKey, threadId: authThread }],
        },
      );
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 2 });
      expect(backend.verifyLandings[0]?.fixMarkedFindingIdentityKeys).toEqual([authKey]);
      expect(backend.verifyLandings[0]?.fixMarkedFindingThreads).toEqual([
        { identityKey: authKey, threadId: authThread },
      ]);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("pin r15/#735: RealFamilyBackend routes verify+landing through runFamilyReviewLoopWorker", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const here = dirname(fileURLToPath(import.meta.url));
    const realPromptsDir = join(here, "..", "prompts");
    const realSoulsDir = join(here, "..", "image", "souls");
    try {
      class ProbeBackend extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

        readonly reviewLoopKinds: WorkerKind[] = [];
        readonly landings: WorkerLandingPayload[] = [];
        protected override async runFamilyReviewLoopWorker(
          spec: WorkerSpec,
          _ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
          this.reviewLoopKinds.push(spec.kind);
          if (landing !== undefined) this.landings.push(landing);
          const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
          return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
        }
      }
      const backend = new ProbeBackend({
        workingRepo: "/tmp/family-r7-probe",
        familyBase: "family/r7",
        ledgerDir: "/tmp/family-r7-ledger",
        repo: "o/r",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
      });
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result.ok).toBe(true);
      // #735: landing is a real agent worker, same path as verify (not forever-stub).
      // #941: online-review dispatches verify only; landing Action owns S12 after.
      expect(backend.reviewLoopKinds).toEqual(["verify"]);
      expect(backend.landings[0]?.onlineReviewSnapshot).toBeDefined();
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });
});
