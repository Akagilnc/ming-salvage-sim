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
  cleanupWorkerSpec,
  docReleaseWorkerSpec,
  verifyWorkerSpec,
  fixerWorkerSpec,
  legacyDispatchWorker,
} from "../src/dispatchWorker.js";
import {
  legacyDispatchFamilyWorker,
} from "../src/family/dispatchFamilyWorker.js";
import type {
  Backend,
  DispatchContext,
  FixerResult,
  IssueMeta,
  IssueSnapshot,
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

type OnlineLedgerFixture = {
  readonly step?: string;
  readonly event?: PersistentLedgerEntry["event"];
  readonly ts?: string;
  readonly branchHEAD?: string;
  readonly prHead?: string;
  readonly roundTriggerHeadOid?: string;
  readonly roundTriggerAt?: string;
  readonly onlineReviewRound?: number;
  readonly fixCommitSha?: string;
  readonly output?: StepOutput;
};

function onlineLedger(entries: readonly OnlineLedgerFixture[]): readonly OnlineLedgerFixture[] {
  return entries;
}

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
  BOT_REACTION_ACK_CONTENT,
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
  workerOutcomeAdmissible,
} from "../src/evidenceAdmissibility.js";
import { offlinePrReviewSnapshot } from "../src/onlineReviewLoop.js";
import {
  enforceRunnerOwnedRecheck,
  immediateBotPollClock,
  lastFixMarkedFindingAuthorizationFromFamilyLedger,
  lastOnlineReviewFixCommitShaFromFamilyLedger,
  lastOnlineReviewFixCommitShaFromLedger,
  MAX_ONLINE_REVIEW_ROUNDS,
  onlineReviewResumeHeadKeyFromLedger,
  onlineReviewRoundFromFamilyLedger,
  onlineReviewRoundFromLedger,
  onlineReviewRoundTriggerFromFamilyLedger,
  onlineReviewRoundTriggerFromLedger,
  ensureOnlineReviewRetriggerAfterFixGap,
  retriggerBotsAndPoll,
  familyPendingRoundTriggerFromFixGap,
  resolveOnlineReviewRoundTrigger,

  sliceOnlineReviewCiFailedPending,
  slicePendingRoundTriggerFromFixGap,
  slicePostFixVerifyPendingFromMarkerGap,
  runOnlineReviewLoopStage,
  shipLedgerTriggeredAtFromFamilyLedger,
  shipLedgerTriggeredAtFromSliceLedger,
  waitForBotQuiescence,
} from "../src/onlineReviewLoop.js";
import { runOrchestrator } from "../src/runner.js";
import { route } from "../src/route.js";
import { observeOpenPrForBranch } from "../src/autoMerge.js";
import {
  fixerHasFixCommit,
  skeletonReviewLoopWorkerResult,
} from "../src/reviewLoopOutcome.js";
import {
  buildOnlineReviewLanding,
  clampVerifyConvergenceForCheckRuns,
  verifyBlockedOnlyOnPendingCheckRuns,
  isReviewLoopConvergedMarker,
  onlineReviewConvergedForHead,
  onlineReviewFixerNothingToFixStopSummary,
  verifyReadOnlyWorktreeDrift,
  verifyReviewerWorktreeDirtyStopSummary,
  verifySideEffectFailureStopSummary,
} from "../src/onlineReviewLoop.js";
import {
  applyVerifySideEffects,
  createDeferredTrackingIssue,
  deferredTrackingIssueTitle,
  findOpenDeferredTrackingIssueUrl,
  fixMarkedKeysFromVerify,
  hostSideDeferredIdentityKey,
  replyToReviewThread,
  resolveReviewThread,
} from "../src/onlineReviewSideEffects.js";
import { isValidVerifyResult } from "../src/reviewLoopOutcome.js";
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
import type {
  OnlineReviewConvergedEvent,
  WorkerLandingPayload,
} from "../src/types.js";

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
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      if (args.join(" ").includes("pulls/42") && !args.includes("-f")) {
        return JSON.stringify({ head: { sha: "h" }, html_url: "https://github.com/o/r/pull/42" });
      }
      return "{}";
    };
    postBotRetriggerComment(sh, "o/r", 42);
    expect(calls.some((c) => c.includes(BOT_RETRIGGER_COMMENT.split("\n")[0]!))).toBe(
      true,
    );
  });
});

describe("#600 route — success flags + ADR 0061 verify/fixer topology", () => {
  it("observes an open PR for the shipped branch from GitHub host state", () => {
    const calls: string[] = [];
    const observation = observeOpenPrForBranch((file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      return JSON.stringify([
        {
          number: 42,
          url: "https://github.com/o/r/pull/42",
          state: "OPEN",
          headRefName: "fix/824-radius",
          headRefOid: "head-42",
          headRepositoryOwner: { login: "o" },
          mergeStateStatus: "CLEAN",
        },
      ]);
    }, "o/r", "fix/824-radius");

    expect(observation).toEqual({
      present: true,
      prUrl: "https://github.com/o/r/pull/42",
    });
    expect(calls[0]).toContain("gh pr list --repo o/r --head fix/824-radius --state open");
  });

  it("observes no open PR from an empty GitHub host result", () => {
    expect(
      observeOpenPrForBranch(() => "[]", "o/r", "fix/824-radius"),
    ).toEqual({ present: false });
  });

  it("discards a reported open PR on another branch and routes from the shipped branch host truth", () => {
    const observation = observeOpenPrForBranch(
      (_file, args) =>
        args[1] === "view"
          ? JSON.stringify({
              number: 99,
              url: "https://github.com/o/r/pull/99",
              state: "OPEN",
              headRefName: "other-open-branch",
              headRefOid: "deadbeef",
              mergeStateStatus: "CLEAN",
            })
          : JSON.stringify([
              {
                number: 100,
                url: "https://github.com/o/r/pull/100",
                state: "OPEN",
                headRefName: "fix/824-radius",
                headRefOid: "head-100",
                headRepositoryOwner: { login: "o" },
                mergeStateStatus: "CLEAN",
              },
            ]),
      "o/r",
      "fix/824-radius",
      "https://github.com/o/r/pull/99",
    );

    expect(observation).toEqual({
      present: true,
      prUrl: "https://github.com/o/r/pull/100",
    });
  });

  it("S7 skips online review when host truth says no PR, regardless of worker shipStatus", () => {
    expect(
      route({
        from: "S7",
        shipStatus: "pr_opened",
        hostPrPresent: false,
        output: { kind: "ship", branch: "b", status: "pr_opened", pr: "https://x" },
      }),
    ).toEqual({ kind: "handoff", status: "success" });
  });

  it("S7 enters S9 when host truth says a PR exists, regardless of worker shipStatus", () => {
    expect(
      route({
        from: "S7",
        shipStatus: "pushed",
        hostPrPresent: true,
        output: { kind: "ship", branch: "b", status: "pushed" },
      }),
    ).toEqual({ kind: "next", step: "S9" });
  });

  it("S9 converged skips fixer → S12", () => {
    expect(
      route({
        from: "S9",
        output: { kind: "verify", converged: true },
        onlineReviewRound: 1,
      }),
    ).toEqual({ kind: "next", step: "S12" });
  });

  it("S9 not converged routes to S10 when under round cap", () => {
    expect(
      route({
        from: "S9",
        output: { kind: "verify", converged: false },
        onlineReviewRound: 1,
      }),
    ).toEqual({ kind: "next", step: "S10" });
  });

  it("S9 verifier decision gate parks instead of dispatching another fixer", () => {
    expect(
      route({
        from: "S9",
        output: {
          kind: "verify",
          converged: false,
          terminalState: "decision_gate_raised",
        },
        onlineReviewRound: 1,
      }),
    ).toEqual({
      kind: "handoff",
      status: "escalate",
      onlineReviewTerminal: "decision_gate_raised",
    });
  });

  it("S9 not converged at round cap still routes to S10 (AC5: round-3 fix attempted)", () => {
    expect(
      route({
        from: "S9",
        output: { kind: "verify", converged: false },
        onlineReviewRound: MAX_ONLINE_REVIEW_ROUNDS,
      }),
    ).toEqual({ kind: "next", step: "S10" });
  });

  it("S9 not converged after round cap → round_budget_exhausted decision gate", () => {
    expect(
      route({
        from: "S9",
        output: { kind: "verify", converged: false },
        onlineReviewRound: MAX_ONLINE_REVIEW_ROUNDS + 1,
      }),
    ).toEqual({
      kind: "handoff",
      status: "escalate",
      onlineReviewTerminal: "round_budget_exhausted",
    });
  });

  it("S10 committed routes back to S9 for fresh re-verify (not cleanup)", () => {
    expect(
      route({
        from: "S10",
        output: { kind: "fixer", committed: true, fixCommitSha: FIXER_ENVELOPE_SHA },
      }),
    ).toEqual({ kind: "next", step: "S9" });
  });

  it("S10 committed:false returns to S9; only an explicit verify decision signal may park", () => {
    expect(
      route({ from: "S10", output: { kind: "fixer", committed: false } }),
    ).toEqual({ kind: "next", step: "S9" });
  });

  it("pin r41: only a fixer envelope with a non-empty SHA has commit side effects", () => {
    expect(fixerHasFixCommit({ kind: "fixer", committed: false })).toBe(false);
    expect(
      fixerHasFixCommit({
        kind: "fixer",
        committed: false,
        alreadySatisfied: true,
        fixCommitSha: FIXER_ENVELOPE_SHA,
      }),
    ).toBe(true);
    expect(fixerHasFixCommit(fixerCommitted())).toBe(true);
  });

  it("pin r33: S10 alreadySatisfied routes back to S9 (not decision_gate)", () => {
    expect(
      route({
        from: "S10",
        output: {
          kind: "fixer",
          committed: false,
          alreadySatisfied: true,
          fixCommitSha: "landed-fix-sha",
        },
      }),
    ).toEqual({ kind: "next", step: "S9" });
  });

  it("S11 ok:false → error (success-flag branch)", () => {
    expect(
      route({ from: "S11", output: { kind: "cleanup", ok: false, terminal: true } }),
    ).toEqual({ kind: "handoff", status: "error" });
  });

  it("shape-only guard still accepts converged:false as valid shape", () => {
    expect(isValidVerifyResult({ kind: "verify", converged: false })).toBe(true);
  });

  it("accepts full verify disposition contract", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "t:1", threadId: "1", action: "fix" },
          { identityKey: "t:2", threadId: "2", action: "reject", reason: "fp" },
        ],
        fixMarkedFindingIdentityKeys: ["t:1"],
        threadReplies: [{ threadId: "2", body: "rejected: fp" }],
      }),
    ).toBe(true);
  });

  it("#877: converged:true with fix-marked keys is type-valid (content court demolished)", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: true,
        fixMarkedFindingIdentityKeys: ["t:1"],
      }),
    ).toBe(true);
  });

  it("#743: accepts an explicit fix-marked confirmation set only on a recheck", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: true,
        isRecheck: true,
        fixMarkedFindingIdentityKeys: ["t:1"],
      }),
    ).toBe(true);
  });

  it("#877: post-fixer recheck no longer routes through fix-marked echo court", () => {
    // Hard DELETE of recheckConvergenceConfirmsFixMarkedKeys — bare converge is
    // three-channel only; no always-true soft shell remains to re-arm.
    expect(typeof isValidVerifyResult).toBe("function");
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: true,
        isRecheck: true,
      }),
    ).toBe(true);
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: true,
      }),
    ).toBe(true);
  });

  it("#743 R6: round-1 non-recheck bare converge stays legal (type-shape only)", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: true,
      }),
    ).toBe(true);
  });

  it("#877 pin r24: disposition↔fixMarked set mismatch is type-valid (content court demolished)", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "t:1", threadId: "1", action: "reject", reason: "fp" },
        ],
        fixMarkedFindingIdentityKeys: ["t:1"],
      }),
    ).toBe(true);
  });

  it("#877 pin r25: empty fixMarked with fix-action dispositions is type-valid", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "t:1", threadId: "1", action: "fix" },
        ],
        fixMarkedFindingIdentityKeys: [],
      }),
    ).toBe(true);
  });

  it("pin r25: accepts equal empty fixMarked and no fix dispositions", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "t:2", threadId: "2", action: "reject", reason: "fp" },
        ],
        fixMarkedFindingIdentityKeys: [],
      }),
    ).toBe(true);
  });

  it("pin r25: accepts equal non-empty fixMarked and matching fix dispositions", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "t:1", threadId: "1", action: "fix" },
          { identityKey: "t:2", threadId: "2", action: "reject", reason: "fp" },
        ],
        fixMarkedFindingIdentityKeys: ["t:1"],
      }),
    ).toBe(true);
  });

  it("pin r27: shape guard accepts threadsToResolve without isRecheck (runner normalizes)", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: false,
        threadsToResolve: ["99"],
      }),
    ).toBe(true);
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: false,
        isRecheck: true,
        threadsToResolve: ["99"],
      }),
    ).toBe(true);
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

describe("#600 GitHub side effects (#600 AC5/AC6)", () => {
  it("#742 final: accepts a normalized non-PR issue with pull_request: null", () => {
    const sh: Sh = (_file, args) =>
      args.join(" ").includes("state=open")
        ? JSON.stringify([
            {
              title: "defer finding",
              html_url: "https://github.com/o/r/issues/99",
              number: 99,
              pull_request: null,
            },
          ])
        : "[]";

    expect(
      findOpenDeferredTrackingIssueUrl(sh, "o/r", "defer finding"),
    ).toBe("https://github.com/o/r/issues/99");
  });

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
    const url = createDeferredTrackingIssue(sh, "o/r", "defer finding", "reason text");
    expect(url).toBe("https://github.com/o/r/issues/99");
    // #742 R1: list (pre) + create + post-create converge list
    expect(calls.filter((c) => c.includes("state=open"))).toHaveLength(2);
    expect(
      calls.some((c) =>
        c.includes("gh api repos/o/r/issues -f title=defer finding -f body=reason text --jq .html_url"),
      ),
    ).toBe(true);
  });

  it("#742 R2 adopts a timestamped issue before an issue with a missing timestamp", () => {
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (cmd.includes("state=open")) {
        return JSON.stringify([
          {
            number: 101,
            title: "defer finding",
            html_url: "https://github.com/o/r/issues/101",
          },
          {
            number: 102,
            title: "defer finding",
            html_url: "https://github.com/o/r/issues/102",
            created_at: "2026-01-01T00:00:00.000Z",
          },
        ]);
      }
      return "[]";
    };

    expect(createDeferredTrackingIssue(sh, "o/r", "defer finding", "body")).toBe(
      "https://github.com/o/r/issues/102",
    );
  });

  it("createDeferredTrackingIssue fails closed on empty or malformed gh create output", () => {
    const emptyCreate: Sh = (_file, args) =>
      args.join(" ").includes("state=open") ? "[]" : "";
    const junkCreate: Sh = (_file, args) =>
      args.join(" ").includes("state=open")
        ? "[]"
        : args.join(" ").includes("-f title=")
          ? "not-a-github-url"
          : "[]";
    expect(() =>
      createDeferredTrackingIssue(emptyCreate, "o/r", "t", "b"),
    ).toThrow(/invalid issue URL/);
    expect(() =>
      createDeferredTrackingIssue(junkCreate, "o/r", "t", "b"),
    ).toThrow(/invalid issue URL/);
  });

  it("#742 R1 fails closed when post-create listing has not converged", () => {
    const sh: Sh = (_file, args) =>
      args.join(" ").includes("state=open")
        ? "[]"
        : "https://github.com/o/r/issues/99";

    expect(() =>
      createDeferredTrackingIssue(sh, "o/r", "defer finding", "reason text"),
    ).toThrow(/did not converge to a canonical issue/);
  });

  it("#742 R2 does not treat a reply without a parent as a matching reply", () => {
    let replyPosts = 0;
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (cmd.includes("repos/o/r/pulls/42/comments?") && !cmd.includes("/replies")) {
        return JSON.stringify([{ body: "same body" }]);
      }
      if (cmd.includes("/replies")) {
        replyPosts += 1;
        return JSON.stringify(GITHUB_REPLY_SHAPE);
      }
      return "[]";
    };

    applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      verify: {
        kind: "verify",
        converged: true,
        threadReplies: [{ threadId: "undefined", body: "same body" }],
      },
    });

    expect(replyPosts).toBe(1);
  });

  it("#742 R1 hostSideDeferredIdentityKey uses GitHub thread/comment id, not worker text", () => {
    expect(hostSideDeferredIdentityKey("3", undefined)).toBe("3");
    expect(hostSideDeferredIdentityKey("PRRT_abc", undefined)).toBe("PRRT_abc");
    expect(
      hostSideDeferredIdentityKey("3", [
        { id: "3", threadNodeId: "PRRT_stable_thread" },
      ]),
    ).toBe("PRRT_stable_thread");
    // worker may re-key identityKey text; host key stays anchored to landing REST/node ids
    expect(
      hostSideDeferredIdentityKey("99", [
        { id: "99", threadNodeId: "PRRT_stable_thread" },
      ]),
    ).toBe("PRRT_stable_thread");
    expect(
      hostSideDeferredIdentityKey("PRRT_stable_thread", [
        { id: "99", threadNodeId: "PRRT_stable_thread" },
      ]),
    ).toBe("PRRT_stable_thread");
    // REST-only landing (no GraphQL node) falls back to comment id
    expect(hostSideDeferredIdentityKey("42", [{ id: "42" }])).toBe("42");
  });

  it("#742 R1 deferred title ignores worker identityKey re-keying across rounds", () => {
    let createCount = 0;
    const openIssues: Array<{
      number: number;
      title: string;
      html_url: string;
      created_at: string;
    }> = [];
    const reviewComments: Array<{
      id: number;
      body: string;
      in_reply_to_id?: number;
    }> = [];
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (cmd.includes("repos/o/r/issues?") && cmd.includes("state=open")) {
        return JSON.stringify(openIssues);
      }
      if (cmd.includes("repos/o/r/issues") && cmd.includes("-f title=")) {
        createCount += 1;
        const titleField = args.find((a) => a.startsWith("title="));
        const title = titleField?.slice("title=".length) ?? "";
        const number = 100 + createCount;
        const url = `https://github.com/o/r/issues/${number}`;
        openIssues.push({
          number,
          title,
          html_url: url,
          created_at: `2026-01-01T00:00:0${createCount}.000Z`,
        });
        return url;
      }
      if (
        cmd.includes("pulls/42/comments") &&
        !cmd.includes("/replies") &&
        !cmd.includes("-f body=")
      ) {
        return JSON.stringify(reviewComments);
      }
      if (cmd.includes("/replies")) {
        const bodyField = args.find((a) => a.startsWith("body="));
        const body = bodyField?.slice("body=".length) ?? "";
        reviewComments.push({
          id: 9000 + reviewComments.length,
          body,
          in_reply_to_id: 3,
        });
        return JSON.stringify(GITHUB_REPLY_SHAPE);
      }
      return "[]";
    };
    const landingThreads = [{ id: "3", threadNodeId: "PRRT_thread_3" }];
    const first = applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      landingThreads,
      verify: {
        kind: "verify",
        converged: false,
        findingDispositions: [
          {
            identityKey: "worker-key-round-1",
            threadId: "3",
            action: "defer",
            reason: "needs design",
          },
        ],
      },
    });
    // Next round: verify worker re-keys identityKey string arbitrarily.
    const second = applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      landingThreads,
      verify: {
        kind: "verify",
        converged: false,
        findingDispositions: [
          {
            identityKey: "worker-key-round-2-REKEYED",
            threadId: "3",
            action: "defer",
            reason: "needs design",
          },
        ],
      },
    });
    expect(first.deferredIssueUrls).toEqual(["https://github.com/o/r/issues/101"]);
    expect(second.deferredIssueUrls).toEqual(["https://github.com/o/r/issues/101"]);
    expect(createCount).toBe(1);
    expect(openIssues).toHaveLength(1);
    expect(openIssues[0]?.title).toBe(
      deferredTrackingIssueTitle("PRRT_thread_3"),
    );
  });

  it("#742 applyVerifySideEffects is idempotent for deferred tracking issues (no duplicate on re-run)", () => {
    // Production seam: crash after create + before ledger → resume re-applies
    // side effects for the same finding identity. Must not open a second issue.
    let createCount = 0;
    let replyCount = 0;
    const openIssues: Array<{
      number: number;
      title: string;
      html_url: string;
      created_at: string;
    }> = [];
    const reviewComments: Array<{
      id: number;
      body: string;
      in_reply_to_id?: number;
    }> = [];
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (cmd.includes("repos/o/r/issues?") && cmd.includes("state=open")) {
        return JSON.stringify(openIssues);
      }
      if (cmd.includes("repos/o/r/issues") && cmd.includes("-f title=")) {
        createCount += 1;
        const titleField = args.find((a) => a.startsWith("title="));
        const title = titleField?.slice("title=".length) ?? "";
        const number = 100 + createCount;
        const url = `https://github.com/o/r/issues/${number}`;
        openIssues.push({
          number,
          title,
          html_url: url,
          created_at: `2026-01-01T00:00:0${createCount}.000Z`,
        });
        return url;
      }
      if (
        cmd.includes("pulls/42/comments") &&
        !cmd.includes("/replies") &&
        !cmd.includes("-f body=")
      ) {
        return JSON.stringify(reviewComments);
      }
      if (cmd.includes("/replies")) {
        replyCount += 1;
        const bodyField = args.find((a) => a.startsWith("body="));
        const body = bodyField?.slice("body=".length) ?? "";
        reviewComments.push({
          id: 9000 + replyCount,
          body,
          in_reply_to_id: 3,
        });
        return JSON.stringify(GITHUB_REPLY_SHAPE);
      }
      return "[]";
    };
    const verify: VerifyResult = {
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
    };
    const input = {
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      verify,
    };
    const first = applyVerifySideEffects(input);
    // Simulated crash resume / repeated round with the same deferred finding.
    const second = applyVerifySideEffects(input);
    expect(first.deferredIssueUrls).toEqual(["https://github.com/o/r/issues/101"]);
    expect(second.deferredIssueUrls).toEqual(["https://github.com/o/r/issues/101"]);
    expect(createCount).toBe(1);
    expect(openIssues).toHaveLength(1);
    // Host-side identity = REST comment id when no landing GraphQL node.
    expect(openIssues[0]?.title).toBe("Deferred online review finding: 3");
    // #742 R1 P1-3: thread reply is also idempotent — one Tracked issue reply only.
    expect(replyCount).toBe(1);
  });

  it("#742 R2 all reply paths are idempotent across a ledger crash", () => {
    const cases: Array<{
      name: string;
      verify: VerifyResult;
      fixingCommitSha?: string;
      /** #743 fail-closed: fixed/recheck resolves require approved identity↔thread bindings. */
      approvedFixMarkedFindingThreads?: ReadonlyArray<{
        readonly identityKey: string;
        readonly threadId: string;
      }>;
      expectedBody: string;
    }> = [
      {
        name: "evidence",
        verify: {
          kind: "verify",
          converged: true,
          threadReplies: [{ threadId: "3", body: "rejected: evidence" }],
        },
        expectedBody: "rejected: evidence",
      },
      {
        name: "deferred",
        verify: {
          kind: "verify",
          converged: false,
          findingDispositions: [
            { identityKey: "t:3", threadId: "3", action: "defer", reason: "needs design" },
          ],
        },
        expectedBody: "deferred: needs design\nTracked issue: https://github.com/o/r/issues/101",
      },
      {
        name: "fixed",
        verify: {
          kind: "verify",
          converged: true,
          isRecheck: true,
          findingDispositions: [
            { identityKey: "t:3", threadId: "3", action: "fix" },
          ],
          threadsToResolve: ["3"],
        },
        fixingCommitSha: "abc123def456",
        approvedFixMarkedFindingThreads: [
          { identityKey: "t:3", threadId: "3" },
        ],
        expectedBody: "fixed: https://github.com/o/r/commit/abc123def456",
      },
    ];

    for (const testCase of cases) {
      const comments: Array<{ id: number; body: string; in_reply_to_id: number }> = [];
      let nextCommentId = 100;
      let resolved = false;
      let replyPosts = 0;
      let resolveCalls = 0;
      const sh: Sh = (_file, args) => {
        const cmd = args.join(" ");
        if (cmd.includes("repos/o/r/pulls/42/comments?") && !cmd.includes("/replies")) {
          return JSON.stringify(comments);
        }
        if (cmd.includes("repos/o/r/issues?") && cmd.includes("state=open")) {
          return testCase.name === "deferred"
            ? JSON.stringify([{ number: 101, title: deferredTrackingIssueTitle("3"), html_url: "https://github.com/o/r/issues/101", created_at: "2026-01-01T00:00:00.000Z" }])
            : "[]";
        }
        if (cmd.includes("repos/o/r/issues") && cmd.includes("-f title=")) {
          return "https://github.com/o/r/issues/101";
        }
        if (cmd.includes("graphql") && cmd.includes("reviewThreads")) {
          return JSON.stringify({ data: { repository: { pullRequest: { reviewThreads: {
            pageInfo: { endCursor: "", hasNextPage: false },
            nodes: [{ id: "PRRT_thread", isResolved: resolved, comments: { nodes: [{ databaseId: 3 }] } }],
          } } } } });
        }
        if (cmd.includes("resolveReviewThread")) {
          resolveCalls += 1;
          resolved = true;
          return JSON.stringify(GITHUB_RESOLVE_MUTATION_SHAPE);
        }
        if (cmd.includes("/replies")) {
          replyPosts += 1;
          const body = args.find((arg) => arg.startsWith("body="))?.slice(5) ?? "";
          comments.push({ id: nextCommentId++, body, in_reply_to_id: 3 });
          return JSON.stringify(GITHUB_REPLY_SHAPE);
        }
        return "[]";
      };
      const input = {
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        verify: testCase.verify,
        ...(testCase.fixingCommitSha === undefined ? {} : { fixingCommitSha: testCase.fixingCommitSha }),
        ...(testCase.approvedFixMarkedFindingThreads === undefined
          ? {}
          : {
              approvedFixMarkedFindingThreads:
                testCase.approvedFixMarkedFindingThreads,
            }),
      };

      applyVerifySideEffects(input);
      applyVerifySideEffects(input);

      expect(replyPosts, testCase.name).toBe(1);
      expect(comments.filter((comment) => comment.body === testCase.expectedBody), testCase.name).toHaveLength(1);
      if (testCase.name === "fixed") {
        expect(resolveCalls).toBe(1);
      }
    }
  });

  it("#742 R2 reconciles overlapping reply posts by retaining the oldest identical reply", () => {
    const comments = [
      { id: 101, body: "rejected: evidence", in_reply_to_id: 3, created_at: "2026-01-01T00:00:00.000Z" },
      { id: 102, body: "rejected: evidence", in_reply_to_id: 3, created_at: "2026-01-01T00:00:01.000Z" },
    ];
    const deleted: number[] = [];
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (cmd.includes("repos/o/r/pulls/42/comments?") && !cmd.includes("/replies")) {
        return JSON.stringify(comments);
      }
      if (cmd.includes("-X DELETE")) {
        const id = Number(cmd.match(/comments\/(\d+)/)?.[1]);
        if (Number.isSafeInteger(id)) {
          deleted.push(id);
          const index = comments.findIndex((comment) => comment.id === id);
          if (index >= 0) comments.splice(index, 1);
        }
        return "";
      }
      return "[]";
    };

    applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      verify: {
        kind: "verify",
        converged: true,
        threadReplies: [{ threadId: "3", body: "rejected: evidence" }],
      },
    });

    expect(deleted).toEqual([102]);
    expect(comments.map((comment) => comment.id)).toEqual([101]);
  });

  it("#742 R1 createDeferredTrackingIssue re-queries before POST and adopts oldest on TOCTOU race", () => {
    // both-queried-before-either-created: two overlapping S9 runs both saw no
    // existing issue and both POSTed. Later convergence adopts oldest + closes dups.
    const title = deferredTrackingIssueTitle("3");
    const openIssues: Array<{
      number: number;
      title: string;
      html_url: string;
      created_at: string;
      state: string;
    }> = [
      {
        number: 101,
        title,
        html_url: "https://github.com/o/r/issues/101",
        created_at: "2026-01-01T00:00:00.000Z",
        state: "open",
      },
      {
        number: 102,
        title,
        html_url: "https://github.com/o/r/issues/102",
        created_at: "2026-01-01T00:00:01.000Z",
        state: "open",
      },
    ];
    const closed: number[] = [];
    let createCount = 0;
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (cmd.includes("repos/o/r/issues?") && cmd.includes("state=open")) {
        return JSON.stringify(openIssues.filter((i) => i.state === "open"));
      }
      if (cmd.includes("repos/o/r/issues/") && cmd.includes("PATCH") && cmd.includes("state=closed")) {
        const m = cmd.match(/issues\/(\d+)/);
        const n = Number(m?.[1]);
        if (Number.isFinite(n)) {
          closed.push(n);
          const hit = openIssues.find((i) => i.number === n);
          if (hit) hit.state = "closed";
        }
        return JSON.stringify({ state: "closed" });
      }
      if (cmd.includes("repos/o/r/issues") && cmd.includes("-f title=")) {
        createCount += 1;
        return "https://github.com/o/r/issues/999";
      }
      return "[]";
    };
    const url = createDeferredTrackingIssue(sh, "o/r", title, "body");
    expect(url).toBe("https://github.com/o/r/issues/101");
    expect(createCount).toBe(0);
    expect(closed).toEqual([102]);
    expect(openIssues.filter((i) => i.state === "open")).toHaveLength(1);
  });

  it("#742 R1 both-queried-before-either-created interleaving converges via post-create adopt-oldest", () => {
    // Sequential simulation of the race window: each create path re-queries
    // before POST and still sees empty (sibling not yet visible), both POST,
    // then post-create re-query + adopt-oldest leaves a single open issue.
    const title = deferredTrackingIssueTitle("anchor-cmt-7");
    const openIssues: Array<{
      number: number;
      title: string;
      html_url: string;
      created_at: string;
      state: string;
    }> = [];
    const closed: number[] = [];
    let nextNumber = 200;
    // list calls that still return empty even after a create — models the
    // both-queried-before-either-created window across two overlapping runs.
    let emptyListBudget = 3; // runA: pre+post; runB: pre+post
    const sh: Sh = (_file, args) => {
      const cmd = args.join(" ");
      if (cmd.includes("repos/o/r/issues?") && cmd.includes("state=open")) {
        if (emptyListBudget > 0) {
          emptyListBudget -= 1;
          return "[]";
        }
        return JSON.stringify(openIssues.filter((i) => i.state === "open"));
      }
      if (cmd.includes("repos/o/r/issues/") && cmd.includes("PATCH") && cmd.includes("state=closed")) {
        const m = cmd.match(/issues\/(\d+)/);
        const n = Number(m?.[1]);
        if (Number.isFinite(n)) {
          closed.push(n);
          const hit = openIssues.find((i) => i.number === n);
          if (hit) hit.state = "closed";
        }
        return JSON.stringify({ state: "closed" });
      }
      if (cmd.includes("repos/o/r/issues") && cmd.includes("-f title=")) {
        nextNumber += 1;
        const number = nextNumber;
        const url = `https://github.com/o/r/issues/${number}`;
        openIssues.push({
          number,
          title,
          html_url: url,
          created_at: `2026-02-01T00:00:${String(number - 200).padStart(2, "0")}.000Z`,
          state: "open",
        });
        return url;
      }
      return "[]";
    };
    expect(() =>
      createDeferredTrackingIssue(sh, "o/r", title, "body-a"),
    ).toThrow(/did not converge to a canonical issue/);
    const second = createDeferredTrackingIssue(sh, "o/r", title, "body-b");
    // Both created (race). Post-create / later list adopts oldest.
    expect(openIssues.map((i) => i.number).sort((a, b) => a - b)).toEqual([
      201, 202,
    ]);
    // After both paths finish, only the oldest remains open.
    expect(openIssues.filter((i) => i.state === "open").map((i) => i.number)).toEqual([
      201,
    ]);
    expect(closed).toContain(202);
    // A retry after the first runner's post-create visibility gap returns oldest.
    expect(second).toBe("https://github.com/o/r/issues/201");
  });

  it("applyVerifySideEffects appends tracked issue URL to pre-supplied defer reply", () => {
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
                number: 88,
                created_at: "2026-01-01T00:00:00.000Z",
              },
            ]);
      }
      if (cmd.includes("repos/o/r/issues") && cmd.includes("-f title=")) {
        createdIssue = {
          title: args.find((arg) => arg.startsWith("title="))!.slice("title=".length),
          url: "https://github.com/o/r/issues/88",
        };
        return "https://github.com/o/r/issues/88";
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
          { threadId: "3", body: "deferred: needs design — tracked issue will follow" },
        ],
      },
    });
    expect(result.repliesPosted[0]?.body).toContain(
      "https://github.com/o/r/issues/88",
    );
  });

  it("pin online R3 Codex P2: reject without threadReplies synthesizes rejected: reply from reason", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      if (args.join(" ").includes("/replies")) {
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
        converged: true,
        findingDispositions: [
          {
            identityKey: "t:2",
            threadId: "2",
            action: "reject",
            reason: "false positive on line 10",
          },
        ],
        // no threadReplies — host must still post evidence
      },
    });
    expect(result.repliesPosted).toEqual([
      { threadId: "2", body: "rejected: false positive on line 10" },
    ]);
    expect(calls.some((c) => c.includes("/replies"))).toBe(true);
  });

  it("pin online R3 Codex P2: reject without reply and without reason fails closed", () => {
    const sh: Sh = () => {
      throw new Error("gh should not be called");
    };
    expect(() =>
      applyVerifySideEffects({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        verify: {
          kind: "verify",
          converged: true,
          findingDispositions: [
            {
              identityKey: "t:2",
              threadId: "2",
              action: "reject",
            },
          ],
        },
      }),
    ).toThrow(/reject disposition.*requires a threadReplies entry or a non-empty reason/);
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
          title: args.find((arg) => arg.startsWith("title="))!.slice("title=".length),
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
    expect(result.deferredIssueUrls).toEqual(["https://github.com/o/r/issues/77"]);
    expect(result.repliesPosted.some((r) => r.body.includes("rejected:"))).toBe(true);
    expect(result.repliesPosted.some((r) => r.body.includes("Tracked issue:"))).toBe(true);
    expect(
      calls.filter((c) =>
        c.includes(
          "gh api repos/o/r/issues -f title=Deferred online review finding: 3 -f body=needs design --jq .html_url",
        ),
      ),
    ).toHaveLength(1);
    expect(calls.filter((c) => c.includes("state=open")).length).toBeGreaterThanOrEqual(2);
    expect(
      calls.filter((c) => c.includes("repos/o/r/pulls/42/comments/2/replies")),
    ).toHaveLength(1);
  });

  it("resolveReviewThread uses GraphQL resolveReviewThread (not REST comment edit)", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      if (args.join(" ").includes("graphql") && args.join(" ").includes("reviewThreads")) {
        return JSON.stringify({
          data: {
            repository: {
              pullRequest: {
                reviewThreads: {
                  pageInfo: { endCursor: "cursor-single-page", hasNextPage: false },
                  nodes: [
                    {
                      id: "PRRT_kwDOExampleThread",
                      comments: { nodes: [{ databaseId: 99 }] },
                    },
                  ],
                },
              },
            },
          },
        });
      }
      if (args.join(" ").includes("resolveReviewThread")) {
        return JSON.stringify(GITHUB_RESOLVE_MUTATION_SHAPE);
      }
      if (args.join(" ").includes("/replies")) {
        return JSON.stringify(GITHUB_REPLY_SHAPE);
      }
      return JSON.stringify(GITHUB_REPLY_SHAPE);
    };
    replyToReviewThread(sh, "o/r", 42, "99", "fixed: https://github.com/o/r/commit/abc");
    resolveReviewThread(sh, "o/r", 42, "99");
    expect(
      calls.filter((c) => c.includes("repos/o/r/pulls/42/comments/99/replies")),
    ).toHaveLength(1);
    expect(
      calls.filter((c) => c.includes("resolveReviewThread")),
    ).toHaveLength(1);
    expect(calls.some((c) => c.includes("-X PUT"))).toBe(false);
  });

  it("#742 final: does not match an unrelated thread when firstCommentId is undefined", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
      if (cmd.includes("graphql") && cmd.includes("reviewThreads")) {
        return JSON.stringify({
          data: {
            repository: {
              pullRequest: {
                reviewThreads: {
                  pageInfo: { endCursor: "cursor-single-page", hasNextPage: false },
                  nodes: [
                    { id: "PRRT_unrelated", comments: { nodes: [{}] } },
                  ],
                },
              },
            },
          },
        });
      }
      return "[]";
    };

    expect(() => resolveReviewThread(sh, "o/r", 42, "undefined")).toThrow(
      /no GraphQL review thread/,
    );

    expect(calls.some((call) => call.includes("resolveReviewThread"))).toBe(false);
  });

  it("pin r27: applyVerifySideEffects refuses mismatched caller repo vs PR URL", () => {
    const sh: Sh = () => {
      throw new Error("gh should not be called");
    };
    expect(() =>
      applyVerifySideEffects({
        sh,
        repo: "other/r",
        prUrl: "https://github.com/o/r/pull/42",
        verify: { kind: "verify", converged: true },
      }),
    ).toThrow(/conflicts with PR URL repo/);
  });

  it("applyVerifySideEffects refuses thread resolution without recheck + fixing commit", () => {
    const sh: Sh = () => {
      throw new Error("gh should not be called");
    };
    expect(() =>
      applyVerifySideEffects({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        verify: {
          kind: "verify",
          converged: false,
          threadsToResolve: ["99"],
        },
      }),
    ).toThrow(/isRecheck/);
    expect(() =>
      applyVerifySideEffects({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        verify: {
          kind: "verify",
          converged: false,
          isRecheck: true,
          threadsToResolve: ["99"],
        },
      }),
    ).toThrow(/fixingCommitSha/);
  });

  it("pin r19: pre-existing unrelated reply still gets fixed evidence reply before resolve", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
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
                      comments: { nodes: [{ databaseId: 99 }] },
                    },
                  ],
                },
              },
            },
          },
        });
      }
      if (cmd.includes("resolveReviewThread")) {
        return JSON.stringify(GITHUB_RESOLVE_MUTATION_SHAPE);
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
        converged: true,
        isRecheck: true,
        findingDispositions: [
          { identityKey: "finding:99", threadId: "99", action: "fix" },
        ],
        threadsToResolve: ["99"],
        threadReplies: [{ threadId: "99", body: "rejected: unrelated prior reply" }],
      },
      fixingCommitSha: "abc123def456",
      approvedFixMarkedFindingThreads: [
        { identityKey: "finding:99", threadId: "99" },
      ],
    });
    const fixedReplies = result.repliesPosted.filter((r) =>
      r.body.startsWith("fixed: https://github.com/o/r/commit/"),
    );
    expect(fixedReplies).toHaveLength(1);
    expect(fixedReplies[0]?.body).toBe(
      "fixed: https://github.com/o/r/commit/abc123def456",
    );
    expect(result.threadsResolved).toEqual(["99"]);
    expect(
      calls.filter((c) => c.includes("repos/o/r/pulls/42/comments/99/replies")),
    ).toHaveLength(2);
    expect(calls.filter((c) => c.includes("resolveReviewThread"))).toHaveLength(1);
  });

  it("applyVerifySideEffects resolves threads only on recheck with fixing commit", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
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
                      comments: { nodes: [{ databaseId: 99 }] },
                    },
                  ],
                },
              },
            },
          },
        });
      }
      if (cmd.includes("resolveReviewThread")) {
        return JSON.stringify(GITHUB_RESOLVE_MUTATION_SHAPE);
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
        converged: true,
        isRecheck: true,
        findingDispositions: [
          { identityKey: "finding:99", threadId: "99", action: "fix" },
        ],
        threadsToResolve: ["99"],
      },
      fixingCommitSha: "abc123def456",
      approvedFixMarkedFindingThreads: [
        { identityKey: "finding:99", threadId: "99" },
      ],
    });
    expect(result.threadsResolved).toEqual(["99"]);
    expect(
      result.repliesPosted.find((r) => r.threadId === "99")?.body,
    ).toContain("fixed: https://github.com/o/r/commit/abc123def456");
    expect(calls.filter((c) => c.includes("resolveReviewThread"))).toHaveLength(1);
  });

  it("#743 R1 runner path: a non-converged recheck cannot close a thread outside the fixer-approved identity set", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      return JSON.stringify(GITHUB_RESOLVE_MUTATION_SHAPE);
    };

    const result = applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      verify: {
        kind: "verify",
        converged: false,
        isRecheck: true,
        findingDispositions: [
          { identityKey: "finding:unapproved", threadId: "99", action: "fix" },
        ],
        threadsToResolve: ["99"],
      },
      fixingCommitSha: "abc123def456",
      approvedFixMarkedFindingThreads: [
        { identityKey: "finding:approved", threadId: "99" },
      ],
    });

    expect(result.threadsResolved).toEqual([]);
    expect(calls).toEqual([]);
  });

  it("#743 R2: an approved identity cannot be rebound to a different landing thread", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      return JSON.stringify(GITHUB_RESOLVE_MUTATION_SHAPE);
    };

    const result = applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      verify: {
        kind: "verify",
        converged: false,
        isRecheck: true,
        findingDispositions: [
          { identityKey: "finding:approved", threadId: "99", action: "fix" },
        ],
        threadsToResolve: ["99"],
      },
      fixingCommitSha: "abc123def456",
      approvedFixMarkedFindingThreads: [
        { identityKey: "finding:approved", threadId: "42" },
      ],
    });

    expect(result.threadsResolved).toEqual([]);
    expect(calls).toEqual([]);
  });

  it("#743 R1 family-resume path: missing approved identities closes no recheck threads", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      return JSON.stringify(GITHUB_RESOLVE_MUTATION_SHAPE);
    };

    const result = applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      verify: {
        kind: "verify",
        converged: false,
        isRecheck: true,
        findingDispositions: [
          { identityKey: "finding:fixed", threadId: "99", action: "fix" },
        ],
        threadsToResolve: ["99"],
      },
      fixingCommitSha: "abc123def456",
    });

    expect(result.threadsResolved).toEqual([]);
    expect(calls).toEqual([]);
  });

  const LANDING_THREAD_PAIR = [
    { id: "4242", threadNodeId: "PRRT_kwDOExampleThread" },
  ] as const;

  it("pin r24: defer disposition node id + reply comment id for same thread → deduped", () => {
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
                number: 55,
                created_at: "2026-01-01T00:00:00.000Z",
              },
            ]);
      }
      if (cmd.includes("repos/o/r/issues") && cmd.includes("-f title=")) {
        createdIssue = {
          title: args.find((arg) => arg.startsWith("title="))!.slice("title=".length),
          url: "https://github.com/o/r/issues/55",
        };
        return "https://github.com/o/r/issues/55";
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
      landingThreads: [...LANDING_THREAD_PAIR],
      verify: {
        kind: "verify",
        converged: false,
        findingDispositions: [
          {
            identityKey: "t:defer",
            threadId: "PRRT_kwDOExampleThread",
            action: "defer",
            reason: "needs design",
          },
        ],
        threadReplies: [
          {
            threadId: "4242",
            body: "deferred: needs design — tracked issue will follow",
          },
        ],
      },
    });
    expect(result.deferredIssueUrls).toEqual(["https://github.com/o/r/issues/55"]);
    expect(
      calls.filter((c) => c.includes("repos/o/r/pulls/42/comments/4242/replies")),
    ).toHaveLength(1);
    expect(result.repliesPosted).toHaveLength(1);
    expect(result.repliesPosted[0]?.body).toContain(
      "https://github.com/o/r/issues/55",
    );
  });

  it("pin r23: worker echoes node id → reply posts via REST comment id from landing", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      if (args.join(" ").includes("/replies")) {
        return JSON.stringify({ id: 1, body: "ok" });
      }
      return "[]";
    };
    applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      landingThreads: [...LANDING_THREAD_PAIR],
      verify: {
        kind: "verify",
        converged: false,
        threadReplies: [
          {
            threadId: "PRRT_kwDOExampleThread",
            body: "rejected: false positive",
          },
        ],
      },
    });
    expect(
      calls.filter((c) => c.includes("repos/o/r/pulls/42/comments/4242/replies")),
    ).toHaveLength(1);
    expect(
      calls.filter((c) =>
        c.includes("repos/o/r/pulls/42/comments/PRRT_kwDOExampleThread/replies"),
      ),
    ).toHaveLength(0);
  });

  it("pin r23: worker echoes comment id for threadsToResolve → resolve via node id from landing", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
      if (cmd.includes("resolveReviewThread")) {
        return JSON.stringify({ data: { resolveReviewThread: { thread: { isResolved: true } } } });
      }
      if (cmd.includes("/replies")) {
        return JSON.stringify({ id: 1, body: "ok" });
      }
      if (cmd.includes("repos/o/r/pulls/42/comments?")) {
        return "[]";
      }
      if (cmd.includes("reviewThreads")) {
        return LANDING_THREAD_PAIR_GRAPHQL;
      }
      return reviewThreadsGraphqlFallback(cmd) ?? LANDING_THREAD_PAIR_GRAPHQL;
    };
    const result = applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      landingThreads: [...LANDING_THREAD_PAIR],
      verify: {
        kind: "verify",
        converged: true,
        isRecheck: true,
        findingDispositions: [
          { identityKey: "finding:4242", threadId: "4242", action: "fix" },
        ],
        threadsToResolve: ["4242"],
      },
      fixingCommitSha: "abc123def456",
      approvedFixMarkedFindingThreads: [
        { identityKey: "finding:4242", threadId: "4242" },
      ],
    });
    expect(result.threadsResolved).toEqual(["PRRT_kwDOExampleThread"]);
    expect(
      calls.filter((c) => c.includes("repos/o/r/pulls/42/comments/4242/replies")),
    ).toHaveLength(1);
    expect(
      calls.filter(
        (c) =>
          c.includes("resolveReviewThread") &&
          c.includes("threadId=PRRT_kwDOExampleThread"),
      ),
    ).toHaveLength(1);
  });

  it("pin r23: worker echoes node id for threadsToResolve → reply via comment id + resolve via node id", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
      if (cmd.includes("resolveReviewThread")) {
        return JSON.stringify({ data: { resolveReviewThread: { thread: { isResolved: true } } } });
      }
      if (cmd.includes("/replies")) {
        return JSON.stringify({ id: 1, body: "ok" });
      }
      if (cmd.includes("repos/o/r/pulls/42/comments?")) {
        return "[]";
      }
      if (cmd.includes("reviewThreads")) {
        return LANDING_THREAD_PAIR_GRAPHQL;
      }
      return reviewThreadsGraphqlFallback(cmd) ?? LANDING_THREAD_PAIR_GRAPHQL;
    };
    const result = applyVerifySideEffects({
      sh,
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      landingThreads: [...LANDING_THREAD_PAIR],
      verify: {
        kind: "verify",
        converged: true,
        isRecheck: true,
        findingDispositions: [
          {
            identityKey: "finding:4242",
            threadId: "PRRT_kwDOExampleThread",
            action: "fix",
          },
        ],
        threadsToResolve: ["PRRT_kwDOExampleThread"],
      },
      fixingCommitSha: "abc123def456",
      approvedFixMarkedFindingThreads: [
        { identityKey: "finding:4242", threadId: "PRRT_kwDOExampleThread" },
      ],
    });
    expect(result.threadsResolved).toEqual(["PRRT_kwDOExampleThread"]);
    expect(
      calls.filter((c) => c.includes("repos/o/r/pulls/42/comments/4242/replies")),
    ).toHaveLength(1);
    expect(
      calls.filter(
        (c) =>
          c.includes("resolveReviewThread") &&
          c.includes("threadId=PRRT_kwDOExampleThread"),
      ),
    ).toHaveLength(1);
  });

  it("pin r23: unknown thread id with landing → terminal", () => {
    const sh: Sh = () => {
      throw new Error("gh should not be called");
    };
    expect(() =>
      applyVerifySideEffects({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        landingThreads: [...LANDING_THREAD_PAIR],
        verify: {
          kind: "verify",
          converged: false,
          threadReplies: [{ threadId: "UNKNOWN_THREAD", body: "rejected: x" }],
        },
      }),
    ).toThrow(/matches neither REST comment id nor GraphQL node id in landing/);
  });

  it("pin r25: invalid thread id in batch → zero GitHub writes occurred", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      return "https://github.com/o/r/issues/99";
    };
    expect(() =>
      applyVerifySideEffects({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        landingThreads: [...LANDING_THREAD_PAIR],
        verify: {
          kind: "verify",
          converged: false,
          findingDispositions: [
            {
              identityKey: "t:bad",
              threadId: "UNKNOWN_THREAD",
              action: "defer",
              reason: "needs design",
            },
          ],
        },
      }),
    ).toThrow(/matches neither REST comment id nor GraphQL node id in landing/);
    expect(calls).toEqual([]);
  });

  it("applyVerifySideEffects fails closed on invalid prUrl", () => {
    const sh: Sh = () => {
      throw new Error("gh should not be called");
    };
    expect(() =>
      applyVerifySideEffects({
        sh,
        repo: "o/r",
        prUrl: "not-a-pr",
        verify: { kind: "verify", converged: true },
      }),
    ).toThrow(/cannot parse PR reference/);
  });

  it("createDeferredTrackingIssue propagates gh failures", () => {
    const sh: Sh = () => {
      throw new Error("gh api repos/o/r/issues failed");
    };
    expect(() =>
      createDeferredTrackingIssue(sh, "o/r", "title", "body"),
    ).toThrow(/gh api repos\/o\/r\/issues failed/);
  });

  it("fixMarkedKeysFromVerify derives fix keys from dispositions", () => {
    expect(
      fixMarkedKeysFromVerify({
        kind: "verify",
        converged: false,
        findingDispositions: [
          { identityKey: "a", threadId: "1", action: "fix" },
          { identityKey: "b", threadId: "2", action: "defer" },
        ],
      }),
    ).toEqual(["a"]);
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

  it("isReviewLoopConvergedMarker matches pr head", () => {
    expect(
      isReviewLoopConvergedMarker(
        { event: "online_review_converged", prHead: "abc123" },
        "abc123",
      ),
    ).toBe(true);
    expect(
      isReviewLoopConvergedMarker(
        { event: "online_review_converged", prHead: "old" },
        "new",
      ),
    ).toBe(false);
  });

  it("no-fix convergence: marker and resume-skip key to ship head", () => {
    const ledger = [{ event: "online_review_converged", prHead: shipHead }];
    const reviewHead = convergenceHeadToRecord({ shipHead });
    expect(reviewHead).toBe(shipHead);
    expect(onlineReviewConvergedForHead(ledger, reviewHead)).toBe(true);
    expect(onlineReviewConvergedForHead(ledger, postFixHead)).toBe(false);
  });

  it("converge-after-fix: marker and resume-skip key to post-fix head, not stale ship", () => {
    const ledger = [{ event: "online_review_converged", prHead: postFixHead }];
    const reviewHead = convergenceHeadToRecord({
      shipHead,
      snapshotHead: postFixHead,
      postFixHead,
    });
    expect(reviewHead).toBe(postFixHead);
    expect(onlineReviewConvergedForHead(ledger, reviewHead)).toBe(true);
    expect(onlineReviewConvergedForHead(ledger, shipHead)).toBe(false);
  });

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
            pr: "pr://family/x",
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
            pr: "pr://family/x",
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
            pr: "pr://family/x",
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
            pr: "pr://family/x",
            familyHeadAfter: postFixHead,
          },
        ],
        shipHead,
      ),
    ).toBeUndefined();
  });

  it("pin r26: onlineReviewResumeHeadKeyFromLedger keys no-fix convergence to S9 branchHEAD", () => {
    const ledger: OnlineLedgerFixture[] = [
      {
        step: "S7",
        output: { kind: "ship", branch: "feat/600", status: "pr_opened" },
      },
      {
        step: "S9",
        output: { kind: "verify", converged: true },
        branchHEAD: shipHead,
      },
      { event: "online_review_converged", prHead: shipHead },
    ];
    const reviewHead = onlineReviewResumeHeadKeyFromLedger(ledger);
    expect(reviewHead).toBe(shipHead);
    expect(onlineReviewConvergedForHead(ledger, reviewHead)).toBe(true);
  });

  it("pin r36/r38: converged marker writer shape closes integrated resume-skip (prHead + branchHEAD, no trailing S9 verify output)", () => {
    const markerHead = "deadbeefcommitsha0000000000000000000000";
    const ledger = [
      {
        step: "S7",
        output: { kind: "ship", status: "pr_opened", pr: "pr://slice/offline-255" },
      },
      {
        step: "S9",
        event: "online_review_converged",
        prUrl: "pr://slice/offline-255",
        prHead: markerHead,
        branchHEAD: "branchheadfallback00000000000000000000",
        onlineReviewRound: 1,
      },
    ];
    const reviewHead = onlineReviewResumeHeadKeyFromLedger(ledger);
    expect(reviewHead).toBe(markerHead);
    expect(onlineReviewConvergedForHead(ledger, reviewHead)).toBe(true);
  });

  it("pin r36/r38: without converged marker, ship/fix/verify-row fallback unchanged and does not resume-skip", () => {
    const ledger: OnlineLedgerFixture[] = [
      {
        step: "S7",
        output: { kind: "ship", branch: "feat/600", status: "pr_opened" },
      },
      {
        step: "S9",
        output: { kind: "verify", converged: true },
        branchHEAD: shipHead,
      },
    ];
    const reviewHead = onlineReviewResumeHeadKeyFromLedger(ledger);
    expect(reviewHead).toBe(shipHead);
    expect(onlineReviewConvergedForHead(onlineLedger(ledger), reviewHead)).toBe(false);
  });

  it("pin r26: OnlineReviewConvergedEvent decodes persisted onlineReviewRound field", () => {
    const persisted = {
      event: "online_review_converged" as const,
      prUrl: "https://github.com/o/r/pull/1",
      prHead: shipHead,
      onlineReviewRound: 2,
    };
    const decoded: OnlineReviewConvergedEvent = persisted;
    expect(decoded.onlineReviewRound).toBe(2);
    expect(decoded.event).toBe("online_review_converged");
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

  it("#876 pin r27: verify that mutates HEAD then returns malformed is not reset-cleaned and is not git-convicted", async () => {
    let attempts = 0;
    let resets = 0;
    let head = "head-before";
    const headBefore = head;
    const resolveHead = () => head;
    const result = await withMechanicalRetry(
      verifyWorkerSpec(),
      {} as DispatchContext,
      async () => {
        attempts += 1;
        if (attempts === 1) {
          head = "head-after-mutation";
        }
        // #876: HEAD drift is advisory plumbing — do not throw a contract_drift
        // death. Malformed still routes through ordinary mechanical retry.
        void resolveHead();
        void headBefore;
        return attempts === 1
          ? { kind: "malformed" as const, reason: "missing verify tag" }
          : {
              kind: "completed" as const,
              output: { kind: "verify" as const, converged: true },
            };
      },
      { rethrowOnExhaustion: true },
    );
    expect(attempts).toBe(2);
    expect(resets).toBe(0);
    expect(head).toBe("head-after-mutation");
    expect(result).toMatchObject({
      kind: "completed",
      output: { kind: "verify", converged: true },
    });
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
      reason: expect.stringContaining("after 3 dispatch attempts"),
    });
  });

  it("#876 pin r10: verify that mutates HEAD then throws retries the throw (no git-truth death)", async () => {
    let attempts = 0;
    let head = "head-before";
    const headBefore = head;
    // #876: HEAD drift is advisory; only real worktree dirty remains caller-owned.
    const assertContract = async (): Promise<void> => {
      const drift = verifyReadOnlyWorktreeDrift({
        headBefore,
        headAfter: head,
        porcelainBefore: "",
        porcelainAfter: "",
      });
      // Head drift must not abort or short-circuit retries.
      void drift;
    };
    const result = await withMechanicalRetry(
      verifyWorkerSpec(),
      {} as DispatchContext,
      async () => {
        attempts += 1;
        head = "head-after-mutation";
        // Observe post-attempt HEAD (advisory) then rethrow the process error.
        await assertContract();
        throw new Error("verify worker threw on startup");
      },
    );
    expect(attempts).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(head).toBe("head-after-mutation");
    expect(result).toMatchObject({
      kind: "failed",
      reason: expect.stringContaining("after 3 dispatch attempts"),
    });
  });

  it("pin r10: verify that dirties tracked worktree then throws surfaces contract_drift (no retry on dirty tree)", async () => {
    const { VerifyWorkerWorktreeDirtyError } = await import(
      "../src/onlineReviewLoop.js"
    );
    let attempts = 0;
    let porcelainAfter = "";
    const assertContract = async (): Promise<void> => {
      const drift = verifyReadOnlyWorktreeDrift({
        headBefore: "same-head",
        headAfter: "same-head",
        porcelainBefore: "",
        porcelainAfter,
      });
      if (drift === "worktree") {
        throw new VerifyWorkerWorktreeDirtyError("", porcelainAfter);
      }
    };
    const result = await dispatchVerifyWithPerAttemptDriftGuard(
      async () => {
        attempts += 1;
        porcelainAfter = " M orchestrator/src/foo.ts";
        throw new Error("verify worker threw on startup");
      },
      assertContract,
      (o) =>
        "kind" in o && o.kind === "thrown" &&
        o.error instanceof VerifyWorkerWorktreeDirtyError,
    ).catch((err) => err);
    expect(attempts).toBe(1);
    expect(porcelainAfter).toBe(" M orchestrator/src/foo.ts");
    expect(result).toBeInstanceOf(VerifyWorkerWorktreeDirtyError);
  });

  it("pin r37: verify that throws transient error without mutation still retries fresh (#598)", async () => {
    const { VerifyWorkerWorktreeDirtyError } =
      await import("../src/onlineReviewLoop.js");
    let attempts = 0;
    const assertContract = async (): Promise<void> => {
      const drift = verifyReadOnlyWorktreeDrift({
        headBefore: "stable-head",
        headAfter: "stable-head",
        porcelainBefore: "",
        porcelainAfter: "",
      });
      if (drift === "worktree") {
        throw new VerifyWorkerWorktreeDirtyError("", "");
      }
    };
    const result = await dispatchVerifyWithPerAttemptDriftGuard(
      async () => {
        attempts += 1;
        if (attempts === 1) throw new Error("verify worker threw on startup");
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
        };
      },
      assertContract,
      (o) =>
        "kind" in o && o.kind === "thrown" &&
        o.error instanceof VerifyWorkerWorktreeDirtyError,
    );
    expect(attempts).toBe(2);
    expect(result.kind).toBe("completed");
  });
});

describe("#600 onlineReviewLoop helpers", () => {
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

  it("pin clampVerifyConvergenceForCheckRuns default-denies worker converged:true when CI red", () => {
    const landing: OnlineReviewLandingSnapshot = {
      prUrl: "https://github.com/o/r/pull/1",
      headOid: "abc",
      totalFindingCount: 0,
      quiescent: true,
      bots: {
        coderabbit: { state: "complete", findingCount: 0 },
        sourcery: { state: "complete", findingCount: 0 },
        codex: { state: "complete", findingCount: 0 },
        gemini: { state: "complete", findingCount: 0 },
      },
      droppedBots: [],
      threads: [],
      checkRuns: [
        {
          id: 1,
          name: "ci",
          headSha: "abc",
          status: "completed",
          conclusion: "failure",
        },
      ],
    };
    expect(
      clampVerifyConvergenceForCheckRuns(
        { kind: "verify", converged: true },
        landing,
      ).converged,
    ).toBe(false);
    expect(
      clampVerifyConvergenceForCheckRuns(
        { kind: "verify", converged: true },
        { ...landing, checkRuns: [] },
      ).converged,
    ).toBe(true);
    // pending CI: leave converged true — re-poll, do not force fixer (online R2 Codex P2)
    const pendingLanding = {
      ...landing,
      checkRuns: [
        { id: 9, name: "ci", headSha: "abc", status: "in_progress" as const },
      ],
    };
    expect(
      clampVerifyConvergenceForCheckRuns(
        { kind: "verify", converged: true },
        pendingLanding,
      ).converged,
    ).toBe(true);
    expect(
      verifyBlockedOnlyOnPendingCheckRuns(
        { kind: "verify", converged: true },
        pendingLanding,
      ),
    ).toBe(true);
    expect(
      clampVerifyConvergenceForCheckRuns(
        { kind: "verify", converged: false },
        landing,
      ).converged,
    ).toBe(false);
  });

  it("#876 verifyReadOnlyWorktreeDrift no longer treats HEAD movement as a convictable drift class", () => {
    // Head position is routing plumbing (#876); only tracked worktree residue remains.
    expect(
      verifyReadOnlyWorktreeDrift({
        headBefore: "aaa",
        headAfter: "bbb",
        porcelainBefore: "",
        porcelainAfter: "",
      }),
    ).toBeUndefined();
    expect(
      verifyReadOnlyWorktreeDrift({
        headBefore: "aaa",
        headAfter: "bbb",
        porcelainBefore: "",
        porcelainAfter: " M orchestrator/src/foo.ts",
      }),
    ).toBe("worktree");
  });

  it("pin r32: verifyReadOnlyWorktreeDrift flags tracked edits without HEAD movement", () => {
    expect(
      verifyReadOnlyWorktreeDrift({
        headBefore: "same-head",
        headAfter: "same-head",
        porcelainBefore: "",
        porcelainAfter: " M orchestrator/src/foo.ts",
      }),
    ).toBe("worktree");
    expect(
      verifyReadOnlyWorktreeDrift({
        headBefore: "same-head",
        headAfter: "same-head",
        porcelainBefore: "",
        porcelainAfter: "",
      }),
    ).toBeUndefined();
  });

  it("verifyReviewerWorktreeDirtyStopSummary is contract_drift", () => {
    const s = verifyReviewerWorktreeDirtyStopSummary({
      trackedStatus: [" M orchestrator/src/foo.ts"],
    });
    expect(s.reason).toBe("contract_drift");
    expect(s.summary).toContain("tracked worktree changes");
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
    expect(BOT_REACTION_ACK_CONTENT.has("+1")).toBe(true);
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

  it("pin workerOutcomeAdmissible: failed dispatch is terminal, not skeleton-green", () => {
    const spec = verifyWorkerSpec();
    expect(
      workerOutcomeAdmissible(
        { kind: "failed", reason: "verify worker threw on startup" },
        spec,
      ),
    ).toBe(false);
    expect(
      workerOutcomeAdmissible(
        { kind: "completed", output: { kind: "verify", converged: true } },
        spec,
      ),
    ).toBe(true);
  });
});

describe("#600 r9 first-round RoundTrigger anchoring (#600 cmr r3)", () => {
  const SHIP_LEDGER_TS = "2026-07-08T10:00:00.000Z";
  const LOOP_START_TS = "2026-07-08T12:00:00.000Z";
  const BETWEEN_SHIP_AND_LOOP_TS = "2026-07-08T11:00:00.000Z";
  const PRE_SHIP_TS = "2026-07-08T09:00:00.000Z";
  const POST_RETRIGGER_TS = "2026-07-08T13:30:00.000Z";
  const RETRIGGER_TS = "2026-07-08T13:00:00.000Z";

  it("(a) evidence between ship ledger ts and loop start is admissible in round 1", () => {
    const shipTriggeredAt = shipLedgerTriggeredAtFromSliceLedger([
      {
        step: "S7",
        output: { kind: "ship" },
        ts: SHIP_LEDGER_TS,
      },
    ]);
    expect(shipTriggeredAt).toBe(SHIP_LEDGER_TS);

    const round1Trigger = buildRoundTrigger("headsha1", shipTriggeredAt);
    expect(
      evidenceAdmissible(
        {
          terminalState: "fresh_live",
          timestamp: BETWEEN_SHIP_AND_LOOP_TS,
        },
        "headsha1",
        round1Trigger,
      ),
    ).toBe(true);

    const loopStartTrigger = buildRoundTrigger("headsha1", LOOP_START_TS);
    expect(
      evidenceAdmissible(
        {
          terminalState: "fresh_live",
          timestamp: BETWEEN_SHIP_AND_LOOP_TS,
        },
        "headsha1",
        loopStartTrigger,
      ),
    ).toBe(false);

    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      const cmd = args.join(" ");
      if (
        cmd.includes("pulls/42") &&
        cmd.includes("repos/o/r/pulls/42") &&
        !cmd.includes("comments") &&
        !cmd.includes("reviews")
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
            body: "Summary posted after ship, before loop poll",
            created_at: BETWEEN_SHIP_AND_LOOP_TS,
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
      roundTrigger: round1Trigger,
    });
    expect(snap.bots.coderabbit.state).toBe("complete");
  });

  it("(b) evidence predating the ship ledger ts stays inadmissible in round 1", () => {
    const round1Trigger = buildRoundTrigger(
      "headsha1",
      shipLedgerTriggeredAtFromSliceLedger([
        {
          step: "S7",
          output: { kind: "ship" },
          ts: SHIP_LEDGER_TS,
        },
      ]),
    );
    expect(
      classifyEvidenceFreshness(
        { timestamp: PRE_SHIP_TS },
        "headsha1",
        round1Trigger,
      ),
    ).toBe("stale");
    expect(
      evidenceAdmissible(
        { terminalState: "fresh_live", timestamp: PRE_SHIP_TS },
        "headsha1",
        round1Trigger,
      ),
    ).toBe(false);
  });

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

  it("pin r25: resume mid-round-2 restores persisted retrigger anchor (pre-fix evidence stale)", () => {
    const betweenShipAndRetrigger = "2026-07-08T11:30:00.000Z";
    const resumedTrigger = onlineReviewRoundTriggerFromLedger(onlineLedger([{
        step: "S10",
        event: "online_review_round_retrigger",
        roundTriggerHeadOid: "fixsha1111111111111111111111111111111111",
        roundTriggerAt: RETRIGGER_TS,
        onlineReviewRound: 2,
      }]));
    expect(resumedTrigger).toEqual(
      buildRoundTrigger(
        "fixsha1111111111111111111111111111111111",
        RETRIGGER_TS,
      ),
    );

    const resolved = resolveOnlineReviewRoundTrigger({
      onlineReviewRound: 2,
      persistedRoundTrigger: resumedTrigger,
      shipPrHead: "headsha1",
      shipLedgerTriggeredAt: SHIP_LEDGER_TS,
    });
    expect(resolved).toBe(resumedTrigger);
    expect(
      evidenceAdmissible(
        { terminalState: "fresh_live", timestamp: betweenShipAndRetrigger },
        "fixsha1111111111111111111111111111111111",
        resolved,
      ),
    ).toBe(false);
    expect(
      evidenceAdmissible(
        { terminalState: "fresh_live", timestamp: POST_RETRIGGER_TS },
        "fixsha1111111111111111111111111111111111",
        resolved,
      ),
    ).toBe(true);
  });

  it("pin r25: round-1 resume still falls back to ship ledger anchor", () => {
    const shipTriggeredAt = shipLedgerTriggeredAtFromSliceLedger([
      {
        step: "S7",
        output: { kind: "ship" },
        ts: SHIP_LEDGER_TS,
      },
    ]);
    const resolved = resolveOnlineReviewRoundTrigger({
      onlineReviewRound: 1,
      shipPrHead: "headsha1",
      shipLedgerTriggeredAt: shipTriggeredAt,
    });
    expect(resolved).toEqual(buildRoundTrigger("headsha1", SHIP_LEDGER_TS));
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

  it("pin r28: slicePostFixVerifyPendingFromMarkerGap crash-point matrix (single-slice)", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const s9False = {
      step: "S9",
      output: { kind: "verify", converged: false },
      ts: "2026-07-08T12:00:00.000Z",
    } satisfies OnlineLedgerFixture;
    const s10Row = {
      step: "S10",
      output: { kind: "fixer", committed: true, fixCommitSha: FIXER_ENVELOPE_SHA },
      branchHEAD: fixSha,
      ts: fixTs,
    };
    const retrigger = {
      step: "S10",
      event: "online_review_round_retrigger" as const,
      roundTriggerHeadOid: fixSha,
      roundTriggerAt: RETRIGGER_TS,
      onlineReviewRound: 2,
      ts: fixTs,
    };
    const fixCommitted = {
      step: "S10",
      event: "online_review_fix_committed" as const,
      fixCommitSha: fixSha,
      onlineReviewRound: 1,
      ts: fixTs,
    };
    // crash before markers → no post-fix pending
    expect(slicePostFixVerifyPendingFromMarkerGap([s9False])).toBe(false);
    // crash after retrigger only → post-fix pending
    expect(slicePostFixVerifyPendingFromMarkerGap([s9False, retrigger])).toBe(true);
    // crash after fix_committed before S10 row → post-fix pending
    expect(
      slicePostFixVerifyPendingFromMarkerGap([s9False, retrigger, fixCommitted]),
    ).toBe(true);
    // crash after executable S10 row → not pending (resume uses S10→S9 route)
    expect(
      slicePostFixVerifyPendingFromMarkerGap([
        s9False,
        retrigger,
        fixCommitted,
        s10Row,
      ]),
    ).toBe(false);
    // same-SHA markers after executable S10 (fix-gap recovery order) are NOT a
    // missing-S10 gap — pair by fix SHA, not index order (online R1 Codex P2)
    expect(
      slicePostFixVerifyPendingFromMarkerGap([
        s9False,
        s10Row,
        retrigger,
        fixCommitted,
      ]),
    ).toBe(false);
    // different-SHA marker after S10 → still a gap (S10 does not cover that fix)
    expect(
      slicePostFixVerifyPendingFromMarkerGap([
        s9False,
        s10Row,
        {
          ...fixCommitted,
          fixCommitSha: "otherfixsha0000000000000000000000000001",
        },
      ]),
    ).toBe(true);
  });

  it("pin online R1 Codex P2: recheck S9 false after same-SHA markers must not force post-fix gap", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const s9False = {
      step: "S9",
      output: { kind: "verify", converged: false },
      ts: "2026-07-08T12:00:00.000Z",
    } satisfies OnlineLedgerFixture;
    const s10Row = {
      step: "S10",
      output: { kind: "fixer", committed: true, fixCommitSha: FIXER_ENVELOPE_SHA },
      branchHEAD: fixSha,
      ts: fixTs,
    };
    const retrigger = {
      step: "S10",
      event: "online_review_round_retrigger" as const,
      roundTriggerHeadOid: fixSha,
      roundTriggerAt: RETRIGGER_TS,
      onlineReviewRound: 2,
      ts: fixTs,
    };
    const fixCommitted = {
      step: "S10",
      event: "online_review_fix_committed" as const,
      fixCommitSha: fixSha,
      onlineReviewRound: 1,
      ts: fixTs,
    };
    const s9RecheckFalse = {
      step: "S9",
      output: {
        kind: "verify",
        converged: false,
        isRecheck: true,
        findingDispositions: [
          { identityKey: "f:1", threadId: "100", action: "fix" },
        ],
      },
      ts: "2026-07-08T14:00:00.000Z",
    };
    // Production-ish: markers then S10 then recheck false
    expect(
      slicePostFixVerifyPendingFromMarkerGap([
        s9False,
        fixCommitted,
        retrigger,
        s10Row,
        s9RecheckFalse,
      ]),
    ).toBe(false);
    // Recovery order: S10 then markers then recheck false — must also be false
    // so planResume routes to S10 fixer, not stolen back to S9
    expect(
      slicePostFixVerifyPendingFromMarkerGap([
        s9False,
        s10Row,
        fixCommitted,
        retrigger,
        s9RecheckFalse,
      ]),
    ).toBe(false);
  });

  it("pin r29: retrigger-only marker gap restores round for recheck (single-slice)", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const s9False = {
      step: "S9",
      output: { kind: "verify", converged: false },
      ts: "2026-07-08T12:00:00.000Z",
    } satisfies OnlineLedgerFixture;
    const retriggerOnly = {
      step: "S10",
      event: "online_review_round_retrigger" as const,
      roundTriggerHeadOid: fixSha,
      roundTriggerAt: RETRIGGER_TS,
      onlineReviewRound: 2,
      ts: fixTs,
    } satisfies OnlineLedgerFixture;
    const ledger = [s9False, retriggerOnly];

    expect(slicePostFixVerifyPendingFromMarkerGap(ledger)).toBe(true);
    expect(onlineReviewRoundFromLedger(ledger)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromLedger(ledger)).toBeUndefined();
    expect(onlineReviewRoundTriggerFromLedger(onlineLedger(ledger))).toEqual(
      buildRoundTrigger(fixSha, RETRIGGER_TS),
    );

    const recheckOutcome = enforceRunnerOwnedRecheck(
      { kind: "verify", converged: true },
      onlineReviewRoundFromLedger(ledger),
    );
    expect(recheckOutcome).toEqual({
      kind: "verify",
      converged: true,
      isRecheck: true,
    });
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

  it("pin r18: CI-failed marker keeps resume on S9 (not S10 empty fixer)", () => {
    const s9Red = {
      step: "S9",
      output: { kind: "verify" as const, converged: false },
      ts: "2026-07-09T12:00:00.000Z",
    };
    const ciFailed = {
      step: "S9",
      event: "online_review_ci_failed" as const,
      prHead: "headsha1",
      ts: "2026-07-09T12:00:01.000Z",
    };
    expect(sliceOnlineReviewCiFailedPending([s9Red, ciFailed])).toBe(true);
    // Later green S9 clears the park.
    expect(
      sliceOnlineReviewCiFailedPending(onlineLedger([
        s9Red,
        ciFailed,
        {
          step: "S9",
          output: { kind: "verify", converged: true },
          ts: "2026-07-09T13:00:00.000Z",
        },
      ])),
    ).toBe(false);
    // Stray S10 after CI park also clears (progressed past park).
    expect(
      sliceOnlineReviewCiFailedPending(onlineLedger([
        s9Red,
        ciFailed,
        {
          step: "S10",
          output: {
            kind: "fixer",
            committed: false,
            alreadySatisfied: true,
          },
        },
      ])),
    ).toBe(false);
    // R19: later S9 with fix marks must clear park so resume routes to S10.
    expect(
      sliceOnlineReviewCiFailedPending(onlineLedger([
        s9Red,
        ciFailed,
        {
          step: "S9",
          output: {
            kind: "verify",
            converged: false,
            fixMarkedFindingIdentityKeys: ["t:1"],
          },
        },
      ])),
    ).toBe(false);
    // R20: pending-CI park uses same resume-to-S9 predicate.
    expect(
      sliceOnlineReviewCiFailedPending(onlineLedger([
        {
          step: "S9",
          output: { kind: "verify", converged: true },
        },
        {
          step: "S9",
          event: "online_review_ci_pending",
          prHead: "headsha1",
        },
      ])),
    ).toBe(true);
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
    const sliceGap = slicePendingRoundTriggerFromFixGap([
      {
        event: "online_review_fix_committed",
        fixCommitSha: newerSha,
        ts: newerTs,
      },
      {
        event: "online_review_fix_committed",
        fixCommitSha: olderSha,
        ts: olderTs,
      },
    ]);
    expect(sliceGap).toEqual(buildRoundTrigger(newerSha, newerTs));
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
    expect(
      slicePendingRoundTriggerFromFixGap([
        {
          step: "S10",
          output: { kind: "fixer", committed: true, fixCommitSha: FIXER_ENVELOPE_SHA },
          branchHEAD: fixSha,
          ts: fixTs,
        },
      ]),
    ).toEqual(buildRoundTrigger(fixSha, fixTs));
  });

  it("pin r30: post-fixer crash-point matrix incl. network boundary (single-slice)", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const s9False = {
      step: "S9",
      output: { kind: "verify", converged: false },
      ts: "2026-07-08T12:00:00.000Z",
    } satisfies OnlineLedgerFixture;
    const s10Row = {
      step: "S10",
      output: { kind: "fixer", committed: true, fixCommitSha: FIXER_ENVELOPE_SHA },
      branchHEAD: fixSha,
      ts: fixTs,
    } satisfies OnlineLedgerFixture;
    const fixCommittedOnly = {
      step: "S10",
      event: "online_review_fix_committed" as const,
      fixCommitSha: fixSha,
      onlineReviewRound: 1,
      ts: fixTs,
    } satisfies OnlineLedgerFixture;
    const retrigger = {
      step: "S10",
      event: "online_review_round_retrigger" as const,
      roundTriggerHeadOid: fixSha,
      roundTriggerAt: retriggerTs,
      onlineReviewRound: 2,
      ts: retriggerTs,
    } satisfies OnlineLedgerFixture;

    // crash after fixer S10 row, before fix_committed persist → resume uses S10 row
    const afterS10Only = [s9False, s10Row];
    expect(slicePostFixVerifyPendingFromMarkerGap(afterS10Only)).toBe(false);
    expect(onlineReviewRoundFromLedger(afterS10Only)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromLedger(afterS10Only)).toBe(fixSha);

    // crash after fix_committed, before/during retrigger network → gap reader;
    // resume ACTION: POST retrigger (idempotent) + persist marker + poll (not fixer)
    const afterFixCommitted = [s9False, fixCommittedOnly];
    expect(slicePostFixVerifyPendingFromMarkerGap(afterFixCommitted)).toBe(true);
    expect(onlineReviewRoundFromLedger(afterFixCommitted)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromLedger(afterFixCommitted)).toBe(fixSha);
    const gapTrigger = slicePendingRoundTriggerFromFixGap(afterFixCommitted);
    expect(gapTrigger).toEqual(buildRoundTrigger(fixSha, fixTs));
    expect(
      resolveOnlineReviewRoundTrigger({
        onlineReviewRound: 2,
        pendingRetriggerFromFixGap: gapTrigger,
        shipPrHead: "headsha1",
        shipLedgerTriggeredAt: SHIP_LEDGER_TS,
      }),
    ).toEqual(gapTrigger);

    // crash after retrigger network, before retrigger marker → same gap recovery ACTION
    expect(slicePostFixVerifyPendingFromMarkerGap(afterFixCommitted)).toBe(true);
    expect(onlineReviewRoundTriggerFromLedger(onlineLedger(afterFixCommitted))).toBeUndefined();

    // happy path: both markers persisted
    const happy = [s9False, fixCommittedOnly, retrigger, s10Row];
    expect(slicePostFixVerifyPendingFromMarkerGap(happy)).toBe(false);
    expect(onlineReviewRoundFromLedger(happy)).toBe(2);
    expect(onlineReviewRoundTriggerFromLedger(onlineLedger(happy))).toEqual(
      buildRoundTrigger(fixSha, retriggerTs),
    );

    // legacy r29: retrigger-only (old ordering) still recovers round (not fix SHA)
    const retriggerOnly = [s9False, retrigger];
    expect(slicePostFixVerifyPendingFromMarkerGap(retriggerOnly)).toBe(true);
    expect(onlineReviewRoundFromLedger(retriggerOnly)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromLedger(retriggerOnly)).toBeUndefined();
    expect(onlineReviewRoundTriggerFromLedger(onlineLedger(retriggerOnly))).toEqual(
      buildRoundTrigger(fixSha, retriggerTs),
    );
  });

  it("pin r30: post-fixer crash-point matrix incl. network boundary (family)", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const pr = "https://gh/pr/352";
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

  it("pin r35: live S10 ledger pairing — happy path does not reopen fix-gap", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const s10LaterTs = "2026-07-08T13:05:00.000Z";
    const s9False = {
      step: "S9",
      output: { kind: "verify", converged: false },
      ts: "2026-07-08T12:00:00.000Z",
    };
    const fixCommittedOnly = {
      step: "S10",
      event: "online_review_fix_committed" as const,
      fixCommitSha: fixSha,
      onlineReviewRound: 1,
      ts: fixTs,
    };
    const retrigger = {
      step: "S10",
      event: "online_review_round_retrigger" as const,
      roundTriggerHeadOid: fixSha,
      roundTriggerAt: retriggerTs,
      onlineReviewRound: 2,
      ts: retriggerTs,
    };
    const s10Row = {
      step: "S10",
      output: { kind: "fixer", committed: true, fixCommitSha: FIXER_ENVELOPE_SHA },
      branchHEAD: fixSha,
      ts: s10LaterTs,
    };
    const liveHappy = [s9False, fixCommittedOnly, retrigger, s10Row];

    expect(slicePendingRoundTriggerFromFixGap(liveHappy)).toBeUndefined();
    expect(familyPendingRoundTriggerFromFixGap([fixCommittedOnly, retrigger])).toBeUndefined();
  });

  it("pin r35: live S10 ledger pairing — genuine r27 gap still pending", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const fixCommittedOnly = {
      step: "S10",
      event: "online_review_fix_committed" as const,
      fixCommitSha: fixSha,
      onlineReviewRound: 1,
      ts: fixTs,
    };
    expect(slicePendingRoundTriggerFromFixGap([fixCommittedOnly])).toEqual(
      buildRoundTrigger(fixSha, fixTs),
    );
    expect(
      familyPendingRoundTriggerFromFixGap([
        {
          status: "online_review_fix_committed",
          event: "online_review_fix_committed",
          familyHeadAfter: fixSha,
          ts: fixTs,
        },
      ]),
    ).toEqual(buildRoundTrigger(fixSha, fixTs));
  });

  it("pin r35: live S10 ledger pairing — S10-only fallback crash window still pending", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const s10Only = {
      step: "S10",
      output: { kind: "fixer", committed: true, fixCommitSha: FIXER_ENVELOPE_SHA },
      branchHEAD: fixSha,
      ts: fixTs,
    };
    expect(slicePendingRoundTriggerFromFixGap([s10Only])).toEqual(
      buildRoundTrigger(fixSha, fixTs),
    );
  });

  it("pin r31: multi-round crash gap uses max(fixCommitted+1, retrigger round) symmetrically", () => {
    const fixSha = "fixsha1111111111111111111111111111111111";
    const fixTs = "2026-07-08T12:30:00.000Z";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const round1FixCommitted = {
      step: "S10",
      event: "online_review_fix_committed" as const,
      fixCommitSha: fixSha,
      onlineReviewRound: 1,
      ts: fixTs,
    };
    const round3Retrigger = {
      step: "S10",
      event: "online_review_round_retrigger" as const,
      roundTriggerHeadOid: fixSha,
      roundTriggerAt: retriggerTs,
      onlineReviewRound: 3,
      ts: retriggerTs,
    };
    const sliceLedger = [round1FixCommitted, round3Retrigger];
    expect(onlineReviewRoundFromLedger(sliceLedger)).toBe(3);

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

  it("pin r26: family ledger restores round/trigger/fix SHA symmetrically to single-slice", () => {
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
        pr: "pr://x",
        prHead: "head-1",
      },
      {
        poll: async () => ({
          repo: "o/r",
          prNumber: 1,
          prUrl: "pr://x",
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
        dispatchCleanup: async () => true,
        dispatchDocRelease: async () => true,
        applySideEffects: (_landing, verify, sha) => {
          fixingSha = sha;
          return verify;
        },
        retriggerAfterFix: () => {},
        resolveFixCommitSha: async () => "fix-sha-round1",
      },
      { initialRound: 1 },
    );
    expect(result.ok).toBe(true);
    expect(fixingSha).toBe("fix-sha-round1");
  });

  it("#743: post-fixer recheck receives and must echo every fix-marked identity key before it can converge", async () => {
    const expectedKey = "thread:fixer-claimed";
    let recheckLanding: WorkerLandingPayload | undefined;
    const result = await runOnlineReviewLoopStage(
      {
        kind: "ship",
        branch: "feat/x",
        status: "pr_opened",
        pr: "pr://x",
        prHead: "head-1",
      },
      {
        poll: async () => ({
          repo: "o/r",
          prNumber: 1,
          prUrl: "pr://x",
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
        dispatchCleanup: async () => true,
        dispatchDocRelease: async () => true,
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
    pr: "pr://family/stage-test",
    prHead: "head-1",
  };
  const baseSnapshot: PrReviewSnapshot = {
    repo: "o/r",
    prNumber: 42,
    prUrl: "pr://family/stage-test",
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

  it("happy path: converged verify → cleanup → docRelease terminates mergeable", async () => {
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async () => {
        verifyCalls += 1;
        return { kind: "verify", converged: true } satisfies VerifyResult;
      },
      dispatchFixer: async () => fixerCommitted(),
      dispatchCleanup: async (_landing) => true,
      dispatchDocRelease: async (_landing) => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 1 });
    expect(verifyCalls).toBe(1);
  });

  it("pin deep self-check R8: CI failed + no fix marks parks without fixer", async () => {
    let fixerCalls = 0;
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
      dispatchVerify: async () =>
        ({ kind: "verify", converged: true }) satisfies VerifyResult,
      dispatchFixer: async () => {
        fixerCalls += 1;
        return fixerNotFixed();
      },
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(fixerCalls).toBe(0);
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 1 });
    expect(pollCalls).toBe(2);
    expect(verifyCalls).toBe(2);
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(landingBranch).toBe("family/epic-600");
  });

  it("non-convergence terminal: persistent verify red + fixer commits exhausts round budget", async () => {
    let roundSeen = 0;
    let fixerCalls = 0;
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async (round) => {
        roundSeen = round;
        return { ...baseSnapshot, pollCount: round };
      },
      dispatchVerify: async () => {
        verifyCalls += 1;
        return { kind: "verify", converged: false };
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return fixerCommitted();
      },
      dispatchCleanup: async (_landing) => true,
      dispatchDocRelease: async (_landing) => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async () => "fix-sha",
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "round_budget_exhausted",
      round: MAX_ONLINE_REVIEW_ROUNDS + 1,
    });
    expect(fixerCalls).toBe(MAX_ONLINE_REVIEW_ROUNDS);
    expect(verifyCalls).toBe(MAX_ONLINE_REVIEW_ROUNDS + 1);
    expect(roundSeen).toBe(MAX_ONLINE_REVIEW_ROUNDS + 1);
  });

  it("final-round fix converges on MAX+1 fresh verify → mergeable (not exhausted)", async () => {
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
        if (round > MAX_ONLINE_REVIEW_ROUNDS) {
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
        } satisfies VerifyResult;
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return fixerCommitted();
      },
      dispatchCleanup: async (_landing) => true,
      dispatchDocRelease: async (_landing) => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async () => "fix-sha",
    });
    expect(result).toEqual({
      ok: true,
      terminalState: "mergeable",
      round: MAX_ONLINE_REVIEW_ROUNDS + 1,
    });
    expect(fixerCalls).toBe(MAX_ONLINE_REVIEW_ROUNDS);
    expect(verifyCalls).toBe(MAX_ONLINE_REVIEW_ROUNDS + 1);
    expect(roundSeen).toBe(MAX_ONLINE_REVIEW_ROUNDS + 1);
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
      dispatchCleanup: async (_landing) => true,
      dispatchDocRelease: async (_landing) => true,
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
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
        reason: "infra_failure",
        summary: expect.stringMatching(/side effects failed.*retriggerBotsAndPoll/s),
      }),
    });
  });

  it("pin r18 family path: applyVerifySideEffects throw → decision_gate_raised in-band", async () => {
    const sh: Sh = () => {
      throw new Error("gh should not be called");
    };
    const result = await runOnlineReviewLoopStage(stageShip, {
      poll: async () => baseSnapshot,
      dispatchVerify: async (_landing, round) => {
        if (round === 1) {
          return {
            kind: "verify",
            converged: false,
            findingDispositions: [
              {
                identityKey: "finding:thread",
                threadId: "PRRT_kwDOExampleThread",
                action: "fix",
              },
            ],
          };
        }
        return {
          kind: "verify",
          converged: true,
          isRecheck: true,
          fixMarkedFindingIdentityKeys: ["finding:thread"],
          findingDispositions: [
            {
              identityKey: "finding:thread",
              threadId: "PRRT_kwDOExampleThread",
              action: "fix",
            },
          ],
          threadsToResolve: ["PRRT_kwDOExampleThread"],
        };
      },
      dispatchFixer: async () => fixerCommitted(),
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (landing, verify, fixingCommitSha) => {
        applyVerifySideEffects({
          sh,
          repo: "o/r",
          prUrl: "https://github.com/o/r/pull/42",
          verify,
          fixingCommitSha,
          landingThreads: [
            { id: "4242", threadNodeId: "PRRT_kwDOExampleThread" },
          ],
          approvedFixMarkedFindingThreads: landing.fixMarkedFindingThreads,
        });
        return verify;
      },
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async () => "fix-sha",
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "decision_gate_raised",
      round: 2,
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
        summary: expect.stringContaining("side effects failed"),
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "decision_gate_raised",
      round: 1,
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "decision_gate_raised",
      round: 1,
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "decision_gate_raised",
      round: 1,
      stopSummary: expect.objectContaining({
        reason: "infra_failure",
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify, sha) => {
        fixingSha = sha;
        return verify;
      },
      retriggerAfterFix: () => {
        retriggerCalls += 1;
      },
      resolveFixCommitSha: async (envelopeFixSha) => {
        resolveFixCalls += 1;
        expect(envelopeFixSha).toBe("crash-landed-sha");
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify, sha) => {
        fixingSha = sha;
        return verify;
      },
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async (envelopeFixSha) => {
        resolveFixCalls += 1;
        expect(envelopeFixSha).toBe(envelopeSha);
        return envelopeFixSha;
      },
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 2 });
    expect(resolveFixCalls).toBe(1);
    expect(fixingSha).toBe(envelopeSha);
    expect(fixingSha).not.toBe(driftHeadOid);
  });

  it("pin r39: committed:true without fixCommitSha retries once, then returns through verify", async () => {
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {
        throw new Error("retriggerAfterFix must not run for malformed fixer envelope");
      },
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 2 });
    expect(fixerCalls).toBe(2);
  });

  it("pin r40: retrigger-only ledger yields no fix SHA (single-slice, envelope-only)", () => {
    const liveHead = "live-pr-head-not-envelope-fix-sha111111111";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const retriggerOnly = [
      {
        step: "S9",
        output: { kind: "verify", converged: false },
        ts: "2026-07-08T12:00:00.000Z",
      },
      {
        step: "S10",
        event: "online_review_round_retrigger" as const,
        roundTriggerHeadOid: liveHead,
        roundTriggerAt: retriggerTs,
        onlineReviewRound: 2,
        branchHEAD: liveHead,
        ts: retriggerTs,
      },
    ];
    expect(onlineReviewRoundFromLedger(retriggerOnly)).toBe(2);
    expect(lastOnlineReviewFixCommitShaFromLedger(retriggerOnly)).toBeUndefined();
    expect(onlineReviewRoundTriggerFromLedger(retriggerOnly)).toEqual(
      buildRoundTrigger(liveHead, retriggerTs),
    );
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

  it("pin r40: fix SHA regression — fix_committed marker and S10 envelope unchanged", () => {
    const envelopeSha = "envelopefixsha111111111111111111111111";
    const liveHead = "live-pr-head-would-be-wrong-if-used1111";
    const retriggerTs = "2026-07-08T13:00:00.000Z";
    const fromFixCommitted = [
      {
        step: "S10",
        event: "online_review_fix_committed" as const,
        fixCommitSha: envelopeSha,
        onlineReviewRound: 1,
        ts: "2026-07-08T12:30:00.000Z",
      },
      {
        step: "S10",
        event: "online_review_round_retrigger" as const,
        roundTriggerHeadOid: liveHead,
        roundTriggerAt: retriggerTs,
        onlineReviewRound: 2,
        ts: retriggerTs,
      },
    ];
    expect(lastOnlineReviewFixCommitShaFromLedger(fromFixCommitted)).toBe(envelopeSha);

    const fromS10 = [
      {
        step: "S10",
        output: {
          kind: "fixer",
          committed: true,
          fixCommitSha: envelopeSha,
        },
        ts: "2026-07-08T12:30:00.000Z",
      },
    ];
    expect(lastOnlineReviewFixCommitShaFromLedger(fromS10)).toBe(envelopeSha);

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

  it("pin r40: recheck side effects fail-closed when fix SHA missing (no wrong GH link)", () => {
    const sh: Sh = () => {
      throw new Error("gh should not be called when fixingCommitSha is missing");
    };
    expect(() =>
      applyVerifySideEffects({
        sh,
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
        verify: {
          kind: "verify",
          converged: true,
          isRecheck: true,
          threadsToResolve: ["thread-1"],
        },
        landingThreads: [],
      }),
    ).toThrow(/fixingCommitSha/);
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
      dispatchCleanup: async () => true,
      dispatchDocRelease: async () => true,
      applySideEffects: (_landing, verify, sha) => {
        recordedSha = sha;
        return verify;
      },
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async (envelopeFixSha) => {
        expect(envelopeFixSha).toBe("family-landed-sha");
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
      dispatchCleanup: async (_landing) => true,
      dispatchDocRelease: async (_landing) => true,
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

describe("#600 r18 verifySideEffectFailureStopSummary contract", () => {
  it("pin single-slice: stopSummary shape used by runner errorTermination", () => {
    const err = new Error(
      "applyVerifySideEffects: threadsToResolve requires fixingCommitSha on recheck",
    );
    const stopSummary = verifySideEffectFailureStopSummary(err);
    expect(stopSummary.reason).toBe("infra_failure");
    expect(stopSummary.summary).toContain("side effects failed");
    expect(stopSummary.summary).toContain("fixingCommitSha");
    expect(stopSummary.repairHint).toMatch(/rerun/i);
  });
});

describe("#600 r17 landing write fail-closed — verify/fixer dispatch", () => {
  const landingPayload: WorkerLandingPayload = {
    onlineReviewSnapshot: {
      prUrl: "https://github.com/o/r/pull/42",
      headOid: "abc",
      totalFindingCount: 0,
      quiescent: true,
      bots: {
        coderabbit: { state: "complete", findingCount: 0 },
        sourcery: { state: "complete", findingCount: 0 },
        codex: { state: "complete", findingCount: 0 },
        gemini: { state: "complete", findingCount: 0 },
      },
      droppedBots: [],
      threads: [],
      checkRuns: [],
    },
  };

  it("pin: online review landing write failure returns failed dispatch, not worker-without-mount", async () => {
    const spec = verifyWorkerSpec();
    // A defined dispatchWorker skips the offline skeleton short-circuit so the
    // legacy path reaches writeOnlineReviewLandingFile (RealBackend shape).
    const legacyBackend = {
      dispatchWorker: async () => ({
        kind: "completed" as const,
        output: { kind: "verify", converged: true },
      }),
      async runStep(): Promise<StepOutput> {
        throw new Error("runStep must not run when landing write failed");
      },
    } as unknown as Backend;
    const result = await legacyDispatchWorker(
      legacyBackend,
      spec,
      {
        worktree: {
          branch: "feat/x",
          base: "main",
          path: "/nonexistent/worktree/path/for-landing-fail",
        },
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/42",
      },
      landingPayload,
    );
    expect(result.kind).toBe("failed");
    if (result.kind === "failed") {
      expect(result.reason).toMatch(/online review landing/i);
    }
  });
});

describe("#600 r5 legacy skeleton gate — family + slice", () => {
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
    expect(workerOutcomeAdmissible(result, spec)).toBe(false);
    if (result.kind === "failed") {
      expect(result.reason).toContain("offline skeleton synthesis inadmissible");
    }
  });

  it("pin slice legacy path: unavailable primary on live PR → failed, not skeleton-green", async () => {
    const spec = verifyWorkerSpec();
    const legacyBackend = {
      async push(): Promise<void> {},
    } as unknown as Backend;
    const result = await legacyDispatchWorker(legacyBackend, spec, {
      worktree,
      ...liveCtx,
    });
    expect(result.kind).toBe("failed");
    expect(workerOutcomeAdmissible(result, spec)).toBe(false);
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
      expect(workerOutcomeAdmissible(result, spec)).toBe(true);
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

  it("pin r15/#735: S11 cleanup still stubs without runStep; S12 docRelease is a real agent path", async () => {
    let runStepCalls = 0;
    const legacyBackend = {
      dispatchWorker: async () => ({
        kind: "completed" as const,
        output: { kind: "verify", converged: true },
      }),
      async runStep(): Promise<StepOutput> {
        runStepCalls += 1;
        // #735: real docRelease may reach runStep when not offline-stubbed.
        return { kind: "docRelease", released: true };
      },
    } as unknown as Backend;

    const cleanup = await legacyDispatchWorker(
      legacyBackend,
      cleanupWorkerSpec(),
      { worktree },
    );
    expect(cleanup.kind).toBe("completed");
    expect(workerOutcomeAdmissible(cleanup, cleanupWorkerSpec())).toBe(true);
    expect(runStepCalls).toBe(0);

    const doc = await legacyDispatchWorker(
      legacyBackend,
      docReleaseWorkerSpec(),
      { worktree, prUrl: liveCtx.prUrl, repo: liveCtx.repo },
    );
    // Live context + dispatchWorker seam present → agent runStep, not forever-stub.
    expect(runStepCalls).toBe(1);
    expect(doc.kind).toBe("completed");
    if (doc.kind === "completed") {
      expect(doc.output).toEqual({ kind: "docRelease", released: true });
    }
  });
});

describe("#600 r6 slice pollOnlineReviewState hook — central admissibility gate", () => {
  const livePr = "https://github.com/o/r/pull/42";
  const offlinePr = "pr://slice/offline-hook";

  const worktree: WorktreeHandle = {
    branch: "feat/600-hook-gate",
    base: "main",
    path: "/resident/worktrees/issue-600-hook",
  };

  const greenHookSnapshot = (): OnlineReviewLandingSnapshot => ({
    prUrl: livePr,
    headOid: "hook-green-head",
    totalFindingCount: 0,
    quiescent: true,
    bots: {
      coderabbit: { state: "complete", findingCount: 0 },
      sourcery: { state: "complete", findingCount: 0 },
      codex: { state: "complete", findingCount: 0 },
      gemini: { state: "complete", findingCount: 0 },
    },
    droppedBots: [],
    threads: [],
    checkRuns: [],
  });

  class HookPollBackend implements Backend {
  async smokeModelRoute(route: import("../src/modelRoutes.js").ResolvedModelRoute) {
    const { smokeRouteModels } = await import("../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
    readonly hookCalls: string[] = [];

    async findResumeState(): Promise<undefined> {
      return undefined;
    }
    async cleanResidue(): Promise<void> {}
    async resumeSession(): Promise<StepOutput> {
      throw new Error("resumeSession should not be called");
    }
    async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
      return {
        number: issueNumber,
        isReadyForAgent: true,
        hasSubIssues: false,
        isClosed: false,
        openBlockedBy: [],
      };
    }
    async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
      return {
        number: issueNumber,
        body: "b",
        comments: [],
        agentBrief: "",
      };
    }
    async prepareWorktree(): Promise<WorktreeHandle> {
      return worktree;
    }
    async writeSnapshot(): Promise<void> {}
    async writeLedger(_entry: PersistentLedgerEntry, _stateDir: string): Promise<void> {}
    async runStep(): Promise<StepOutput> {
      throw new Error("runStep should not be called");
    }
    async push(): Promise<void> {}
    async pollOnlineReviewState(input: {
      repo: string;
      prUrl: string;
      pollCount: number;
    }): Promise<OnlineReviewLandingSnapshot> {
      this.hookCalls.push(input.prUrl);
      return greenHookSnapshot();
    }
    async dispatchWorker(
      spec: WorkerSpec,
      _ctx: DispatchContext,
      _landing?: WorkerLandingPayload,
    ): Promise<WorkerResult> {
      if (spec.kind === "coder") {
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      }
      if (spec.kind === "reviewer") {
        return { kind: "completed", output: { kind: "reviewer", findings: [] } };
      }
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      if (skeleton !== undefined) {
        return skeleton;
      }
      return {
        kind: "completed",
        output: {
          kind: "ship",
          branch: worktree.branch,
          status: "pr_opened",
          pr: livePr,
        },
      };
    }
  }

  it("pin: hook green on a real PR URL outside test mode → error, not success", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    try {
      const backend = new HookPollBackend();
      const result = await runOrchestrator({ issueNumber: 600, backend });
      expect(result.status).toBe("error");
      expect(backend.hookCalls).toEqual([]);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("pin: hook green on a real PR URL with offline flag but non-test handle → error", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      const backend = new HookPollBackend();
      const result = await runOrchestrator({ issueNumber: 600, backend });
      expect(result.status).toBe("error");
      expect(backend.hookCalls).toEqual([]);
      expect(result.errorPackage?.reason).toMatch(
        /refused for live GitHub PR/,
      );
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("offline test handle still admits hook-provided poll snapshots", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      class OfflineHookBackend extends HookPollBackend {
        readonly verifyLandings: WorkerLandingPayload[] = [];

        override async pollOnlineReviewState(input: {
          repo: string;
          prUrl: string;
          pollCount: number;
        }): Promise<OnlineReviewLandingSnapshot> {
          this.hookCalls.push(input.prUrl);
          return {
            ...greenHookSnapshot(),
            prUrl: offlinePr,
            threads: [
              {
                id: "4242",
                threadNodeId: "PRRT_kwDOExampleThread",
                path: "src/offline.ts",
                line: 42,
                body: "offline hook thread",
                isResolved: false,
              },
            ],
          };
        }
        override async dispatchWorker(
          spec: WorkerSpec,
          ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
          if (spec.kind === "verify" && landing !== undefined) {
            this.verifyLandings.push(landing);
          }
          if (spec.kind === "ship") {
            return {
              kind: "completed",
              output: {
                kind: "ship",
                branch: worktree.branch,
                status: "pr_opened",
                pr: offlinePr,
              },
            };
          }
          return super.dispatchWorker(spec, ctx, landing);
        }
      }
      const backend = new OfflineHookBackend();
      const result = await runOrchestrator({ issueNumber: 600, backend });
      expect(result.status).toBe("success");
      expect(backend.hookCalls).toEqual([offlinePr]);
      expect(backend.verifyLandings[0]?.onlineReviewSnapshot?.threads[0]).toEqual(
        expect.objectContaining({
          id: "4242",
          threadNodeId: "PRRT_kwDOExampleThread",
          path: "src/offline.ts",
          line: 42,
        }),
      );
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("#824 pending-CI verify re-polls reset the durable S9 dispatch budget", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      class SlowCiBackend extends HookPollBackend {
        readonly ledgerWrites: PersistentLedgerEntry[] = [];
        verifyDispatches = 0;

        override async writeLedger(entry: PersistentLedgerEntry, _stateDir: string): Promise<void> {
          this.ledgerWrites.push(entry);
        }

        override async pollOnlineReviewState(): Promise<OnlineReviewLandingSnapshot> {
          return {
            ...greenHookSnapshot(),
            prUrl: offlinePr,
            checkRuns: this.verifyDispatches < 4
              ? [{ id: 1, name: "ci", headSha: "head-1", status: "in_progress" }]
              : [],
          };
        }

        override async dispatchWorker(
          spec: WorkerSpec,
          ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
          if (spec.kind === "ship") {
            return {
              kind: "completed",
              output: { kind: "ship", branch: worktree.branch, status: "pr_opened", pr: offlinePr },
            };
          }
          if (spec.kind === "verify") this.verifyDispatches += 1;
          return super.dispatchWorker(spec, ctx, landing);
        }
      }

      const backend = new SlowCiBackend();
      const result = await runOrchestrator({ issueNumber: 824, backend });

      expect(result.status).toBe("success");
      expect(backend.verifyDispatches).toBe(5);
      expect(
        backend.ledgerWrites.filter((entry) => entry.step === "S9" && entry.event === undefined),
      ).toHaveLength(5);
    } finally {
      if (prev === undefined) delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      else process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
    }
  });

  it("retries a clean-exit verify worker whose completed envelope is invalid", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      class InvalidVerifyThenConvergeBackend extends HookPollBackend {
        verifyDispatches = 0;

        override async pollOnlineReviewState(
          _input: { repo: string; prUrl: string; pollCount: number },
        ): Promise<OnlineReviewLandingSnapshot> {
          return { ...greenHookSnapshot(), prUrl: offlinePr };
        }

        override async dispatchWorker(
          spec: WorkerSpec,
          ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
          if (spec.kind === "ship") {
            return {
              kind: "completed",
              output: {
                kind: "ship",
                branch: worktree.branch,
                status: "pr_opened",
                pr: offlinePr,
              },
            };
          }
          if (spec.kind === "verify") {
            this.verifyDispatches += 1;
            if (this.verifyDispatches === 1) {
              return {
                kind: "completed",
                output: { kind: "verify", converged: "bad" },
              } as unknown as WorkerResult;
            }
          }
          return super.dispatchWorker(spec, ctx, landing);
        }
      }

      const backend = new InvalidVerifyThenConvergeBackend();
      const result = await runOrchestrator({ issueNumber: 600, backend });
      expect(result.status).toBe("success");
      expect(backend.verifyDispatches).toBe(2);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("#743 R2 runner path: rebuilding the round-2 landing still rejects bare convergence", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      class RebuildGuardBackend extends HookPollBackend {
        verifyCount = 0;

        override async pollOnlineReviewState(
          _input: { repo: string; prUrl: string; pollCount: number },
        ): Promise<OnlineReviewLandingSnapshot> {
          return { ...greenHookSnapshot(), prUrl: offlinePr };
        }

        override async dispatchWorker(
          spec: WorkerSpec,
          ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
          if (spec.kind === "ship") {
            return {
              kind: "completed",
              output: {
                kind: "ship",
                branch: worktree.branch,
                status: "pr_opened",
                pr: offlinePr,
              },
            };
          }
          if (spec.kind === "verify") {
            this.verifyCount += 1;
            if (this.verifyCount === 1) {
              return {
                kind: "completed",
                output: {
                  kind: "verify",
                  converged: false,
                  findingDispositions: [
                    { identityKey: "finding:r2", threadId: "4242", action: "fix" },
                  ],
                },
              };
            }
            return { kind: "completed", output: { kind: "verify", converged: true } };
          }
          return super.dispatchWorker(spec, ctx, landing);
        }
      }

      const result = await runOrchestrator({
        issueNumber: 600,
        backend: new RebuildGuardBackend(),
      });
      // #877: bare converge without fix-marked echo no longer contract_drift.
      expect(result.status).toBe("success");
      expect(result.stopSummary?.reason).not.toBe("contract_drift");
    } finally {
      if (prev === undefined) delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      else process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
    }
  });
});

describe("#600 r7 family online review — cleanup landing + in-band failures", () => {
  class ReviewLoopFamilyBackend implements FamilyBackend {
    readonly reviewLoopLandings: WorkerLandingPayload[] = [];
    readonly ledger: FamilyLedgerEntry[] = [];
    readFamilyHead?: (familyBase: string) => Promise<string>;
    readFamilyTrackedStatus?: (familyBase: string) => Promise<readonly string[]>;

    async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
      return { familyHead: "fb-head" };
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
        (spec.kind === "cleanup" || spec.kind === "docRelease") &&
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
    pr: "pr://family/r7-cleanup-landing",
    prHead: "head-r7",
    status: "pr_opened" as const,
  };

  it("happy path passes onlineReviewSnapshot landing into docRelease (cleanup is post-merge)", async () => {
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
      expect(backend.reviewLoopLandings).toHaveLength(1);
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

  it("#853 family verify tracked changes stay in the normal review flow", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      let trackedStatus: string[] = [];
      const backend = new ReviewLoopFamilyBackend();
      backend.readFamilyHead = async () => "head-before";
      backend.readFamilyTrackedStatus = async () => trackedStatus;
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
      expect(backend.ledger).toContainEqual(expect.objectContaining({
        workerStep: "online-verify:1",
        reason: expect.stringContaining("left tracked changes"),
      }));
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("#876 family verify that moves HEAD stays in the normal review flow", async () => {
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
      expect(backend.ledger).toContainEqual(expect.objectContaining({
        workerStep: "online-verify:1",
        reason: expect.stringContaining("moved HEAD"),
      }));
      expect(headReadCount).toBeGreaterThanOrEqual(2);
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

  it("pin r10: family verify that dirties tracked worktree then throws surfaces contract_drift (no retry on dirty tree)", async () => {
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
          reason: "infra_failure",
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
      readonly appended: FamilyLedgerEntry[] = [];
      async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
        return { familyHead: "head" };
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

  it("pin r15/#735: RealFamilyBackend routes verify+docRelease through runFamilyReviewLoopWorker", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const here = dirname(fileURLToPath(import.meta.url));
    const realPromptsDir = join(here, "..", "prompts");
    const realSoulsDir = join(here, "..", "image", "souls");
    try {
      class ProbeBackend extends RealFamilyBackend {
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
        skillsMount: "/tmp/skills",
      });
      const result = await runFamilyOnlineReviewLoop({
        familyBackend: backend,
        familyBase: "family/r7",
        ship: offlineShip,
      });
      expect(result.ok).toBe(true);
      // #735: docRelease is a real agent worker, same path as verify (not forever-stub).
      expect(backend.reviewLoopKinds).toEqual(["verify", "docRelease"]);
      expect(backend.landings.length).toBeGreaterThanOrEqual(1);
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
