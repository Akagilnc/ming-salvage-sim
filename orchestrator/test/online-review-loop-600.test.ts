/**
 * #600 — online review-loop: bot polling + verify/fixer/reverify convergence.
 */

import { describe, expect, it } from "vitest";
import { MAX_DISPATCH_ATTEMPTS, withMechanicalRetry } from "../src/dispatchRetry.js";
import {
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
  IssueMeta,
  IssueSnapshot,
  OnlineReviewLandingSnapshot,
  PrReviewSnapshot,
  StepOutput,
  VerifyResult,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../src/types.js";
import {
  BOT_OVERDUE_POLL_COUNT,
  BOT_POLL_INTERVAL_MS,
  BOT_RETRIGGER_COMMENT,
  droppedBotIds,
  hasDroppedBots,
  isBotQuiescent,
  isThreadEvidenceFresh,
  ONLINE_REVIEW_BOT_IDS,
  paginateReviewThreadNodes,
  parsePrRef,
  pollPrReviewState,
  postBotRetriggerComment,
} from "../src/botPolling.js";
import {
  assertOfflineSyntheticPollAdmissible,
  buildRoundTrigger,
  classifyEvidenceFreshness,
  evidenceAdmissible,
  offlineSyntheticPollAdmissible,
  workerOutcomeAdmissible,
} from "../src/evidenceAdmissibility.js";
import { offlinePrReviewSnapshot } from "../src/onlineReviewLoop.js";
import {
  immediateBotPollClock,
  MAX_ONLINE_REVIEW_ROUNDS,
  retriggerBotsAndPoll,
  runOnlineReviewLoopStage,
  shipLedgerTriggeredAtFromFamilyLedger,
  shipLedgerTriggeredAtFromSliceLedger,
  waitForBotQuiescence,
} from "../src/onlineReviewLoop.js";
import { runOrchestrator } from "../src/runner.js";
import { route } from "../src/route.js";
import { skeletonReviewLoopWorkerResult } from "../src/reviewLoopOutcome.js";
import {
  buildOnlineReviewLanding,
  isReviewLoopConvergedMarker,
  onlineReviewConvergenceHeadKey,
  onlineReviewConvergedForHead,
  verifyReviewerHeadMovedStopSummary,
} from "../src/onlineReviewLoop.js";
import {
  applyVerifySideEffects,
  createDeferredTrackingIssue,
  fixMarkedKeysFromVerify,
  replyToReviewThread,
  resolveReviewThread,
} from "../src/onlineReviewSideEffects.js";
import { isValidVerifyResult } from "../src/reviewLoopOutcome.js";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Sh } from "../src/familyDriver.js";
import { runFamilyOnlineReviewLoop } from "../src/family/verifyCmr.js";
import { RealFamilyBackend } from "../src/family/realFamilyBackend.js";
import type { FamilyBackend, FamilyLedgerEntry } from "../src/family/types.js";
import type { WorkerLandingPayload } from "../src/types.js";

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
    if (cmd.includes("pulls/comments/") && cmd.includes("/reactions")) {
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
    return "[]";
  };
}

const FRESH_BOT_TIMESTAMP = "2026-07-08T12:00:00.000Z";
const TEST_ROUND_TRIGGER = buildRoundTrigger(
  "headsha1",
  "2026-07-08T11:00:00.000Z",
);

const GITHUB_REPLY_SHAPE = {
  id: 99,
  body: "reply body",
  path: "src/example.ts",
  user: { login: "orchestrator-host" },
};

const GITHUB_RESOLVE_MUTATION_SHAPE = {
  data: {
    resolveReviewThread: {
      thread: { isResolved: true },
    },
  },
};

describe("#600 botPolling — parsePrRef + paginated gh api", () => {
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
      if (cmd.includes("pulls/comments/") && cmd.includes("/reactions")) {
        return "[]";
      }
      return "[]";
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
  it("S7 pushed skips the online review loop → S8 success", () => {
    expect(
      route({ from: "S7", shipStatus: "pushed", output: { kind: "ship", branch: "b", status: "pushed" } }),
    ).toEqual({ kind: "handoff", status: "success" });
  });

  it("S7 pr_opened enters S9", () => {
    expect(
      route({
        from: "S7",
        shipStatus: "pr_opened",
        output: { kind: "ship", branch: "b", status: "pr_opened", pr: "https://x" },
      }),
    ).toEqual({ kind: "next", step: "S9" });
  });

  it("S9 converged skips fixer → S11", () => {
    expect(
      route({
        from: "S9",
        output: { kind: "verify", converged: true },
        onlineReviewRound: 1,
      }),
    ).toEqual({ kind: "next", step: "S11" });
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
        output: { kind: "fixer", committed: true },
      }),
    ).toEqual({ kind: "next", step: "S9" });
  });

  it("S10 not committed → error", () => {
    expect(
      route({ from: "S10", output: { kind: "fixer", committed: false } }),
    ).toEqual({ kind: "handoff", status: "error" });
  });

  it("S11 ok:false → error (success-flag branch)", () => {
    expect(
      route({ from: "S11", output: { kind: "cleanup", ok: false } }),
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

  it("rejects contradictory converged:true with fix-marked findings", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: true,
        fixMarkedFindingIdentityKeys: ["t:1"],
      }),
    ).toBe(false);
  });

  it("rejects threadsToResolve without isRecheck", () => {
    expect(
      isValidVerifyResult({
        kind: "verify",
        converged: false,
        threadsToResolve: ["99"],
      }),
    ).toBe(false);
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
      body: "old nit",
      authorLogin: "bot",
      isResolved: false,
      headOid: "oldhead0000000000000000000000000000000000",
    };
    expect(isThreadEvidenceFresh(stale, "headsha1")).toBe(false);
  });
});

describe("#600 GitHub side effects (#600 AC5/AC6)", () => {
  it("createDeferredTrackingIssue uses gh issue create", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      return "https://github.com/o/r/issues/99";
    };
    const url = createDeferredTrackingIssue(sh, "o/r", "defer finding", "reason text");
    expect(url).toBe("https://github.com/o/r/issues/99");
    expect(calls).toEqual([
      "gh issue create --repo o/r --title defer finding --body reason text --json url -q .url",
    ]);
  });

  it("createDeferredTrackingIssue fails closed on empty or malformed gh output", () => {
    const emptySh: Sh = () => "";
    const junkSh: Sh = () => "not-a-github-url";
    expect(() =>
      createDeferredTrackingIssue(emptySh, "o/r", "t", "b"),
    ).toThrow(/invalid issue URL/);
    expect(() =>
      createDeferredTrackingIssue(junkSh, "o/r", "t", "b"),
    ).toThrow(/invalid issue URL/);
  });

  it("applyVerifySideEffects appends tracked issue URL to pre-supplied defer reply", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
      if (cmd.includes("issue create")) {
        return "https://github.com/o/r/issues/88";
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

  it("applyVerifySideEffects posts evidence replies and creates defer issues", () => {
    const calls: string[] = [];
    const sh: Sh = (file, args) => {
      calls.push(`${file} ${args.join(" ")}`);
      const cmd = args.join(" ");
      if (cmd.includes("issue create")) {
        return "https://github.com/o/r/issues/77";
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
      calls.filter((c) => c.startsWith("gh issue create")),
    ).toEqual([
      "gh issue create --repo o/r --title Deferred online review finding: t:3 --body needs design --json url -q .url",
    ]);
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
        threadsToResolve: ["99"],
      },
      fixingCommitSha: "abc123def456",
    });
    expect(result.threadsResolved).toEqual(["99"]);
    expect(
      result.repliesPosted.find((r) => r.threadId === "99")?.body,
    ).toContain("fixed: https://github.com/o/r/commit/abc123def456");
    expect(calls.filter((c) => c.includes("resolveReviewThread"))).toHaveLength(1);
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
      throw new Error("gh issue create failed");
    };
    expect(() =>
      createDeferredTrackingIssue(sh, "o/r", "title", "body"),
    ).toThrow(/gh issue create failed/);
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
    expect(hasDroppedBots(snap)).toBe(true);
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
    const reviewHead = onlineReviewConvergenceHeadKey({ shipPrHead: shipHead });
    expect(reviewHead).toBe(shipHead);
    expect(onlineReviewConvergedForHead(ledger, reviewHead)).toBe(true);
    expect(onlineReviewConvergedForHead(ledger, postFixHead)).toBe(false);
  });

  it("converge-after-fix: marker and resume-skip key to post-fix head, not stale ship", () => {
    const ledger = [{ event: "online_review_converged", prHead: postFixHead }];
    const reviewHead = onlineReviewConvergenceHeadKey({
      postFixCommitSha: postFixHead,
      snapshotHeadOid: postFixHead,
      shipPrHead: shipHead,
    });
    expect(reviewHead).toBe(postFixHead);
    expect(onlineReviewConvergedForHead(ledger, reviewHead)).toBe(true);
    expect(onlineReviewConvergedForHead(ledger, shipHead)).toBe(false);
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

  it("a fixer worker that crashes once then commits is retried after reset", async () => {
    let attempts = 0;
    let resets = 0;
    const dispatch = async (): Promise<WorkerResult> => {
      attempts += 1;
      if (attempts === 1) throw new Error("fixer worker threw on startup");
      return {
        kind: "completed",
        output: { kind: "fixer", committed: true },
      };
    };
    const result = await withMechanicalRetry(
      fixerWorkerSpec(),
      {} as DispatchContext,
      async () => dispatch(),
      {
        resetBeforeRetry: async () => {
          resets += 1;
        },
      },
    );
    expect(result.kind).toBe("completed");
    expect(attempts).toBe(2);
    expect(resets).toBe(1);
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
    expect(result.kind).toBe("failed");
    expect(result.reason).toContain("after 3 dispatch attempts");
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
          gemini: { state: "dropped", reason: "no review signal after 5 polls" },
        },
        threads: [],
        checkRuns: [],
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
      reason: "no review signal after 5 polls",
    });
  });

  it("verifyReviewerHeadMovedStopSummary mirrors cmr read-only guard wording", () => {
    const s = verifyReviewerHeadMovedStopSummary({
      headBefore: "aaa",
      headAfter: "bbb",
    });
    expect(s.reason).toBe("contract_drift");
    expect(s.summary).toContain("verify worker moved HEAD");
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
      if (cmd.includes("pulls/comments/") && cmd.includes("/reactions")) {
        return "[]";
      }
      return "[]";
    };
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
      roundTrigger: TEST_ROUND_TRIGGER,
    });
    expect(snap.bots.coderabbit.state).toBe("pending");
  });

  it("pin offline gate: synthetic snapshots refused for real GitHub PR URLs", () => {
    expect(
      offlineSyntheticPollAdmissible("https://github.com/o/r/pull/1", "o/r"),
    ).toBe(false);
    expect(() =>
      assertOfflineSyntheticPollAdmissible("https://github.com/o/r/pull/1", "o/r"),
    ).toThrow(/refused for live GitHub PR/);
    expect(() =>
      offlinePrReviewSnapshot({
        repo: "o/r",
        prUrl: "https://github.com/o/r/pull/1",
        headOid: "abc",
        pollCount: 1,
      }),
    ).toThrow(/refused for live GitHub PR/);
    expect(offlineSyntheticPollAdmissible("pr://family/offline", "o/r")).toBe(
      true,
    );
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
      if (cmd.includes("pulls/comments/") && cmd.includes("/reactions")) {
        return "[]";
      }
      return "[]";
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
});

describe("#600 r5 runOnlineReviewLoopStage — stage-level regression", () => {
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
  };

  it("happy path: converged verify → cleanup → docRelease terminates mergeable", async () => {
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage({
      poll: async () => baseSnapshot,
      dispatchVerify: async () => {
        verifyCalls += 1;
        return { kind: "verify", converged: true } satisfies VerifyResult;
      },
      dispatchFixer: async () => true,
      dispatchCleanup: async (_landing) => true,
      dispatchDocRelease: async (_landing) => true,
      applySideEffects: (verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({ ok: true, terminalState: "mergeable", round: 1 });
    expect(verifyCalls).toBe(1);
  });

  it("non-convergence terminal: persistent verify red + fixer commits exhausts round budget", async () => {
    let roundSeen = 0;
    let fixerCalls = 0;
    let verifyCalls = 0;
    const result = await runOnlineReviewLoopStage({
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
        return true;
      },
      dispatchCleanup: async (_landing) => true,
      dispatchDocRelease: async (_landing) => true,
      applySideEffects: (verify) => verify,
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
    const result = await runOnlineReviewLoopStage({
      poll: async (round) => {
        roundSeen = round;
        return { ...baseSnapshot, pollCount: round };
      },
      dispatchVerify: async (_landing, round) => {
        verifyCalls += 1;
        return {
          kind: "verify",
          converged: round > MAX_ONLINE_REVIEW_ROUNDS,
        } satisfies VerifyResult;
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return true;
      },
      dispatchCleanup: async (_landing) => true,
      dispatchDocRelease: async (_landing) => true,
      applySideEffects: (verify) => verify,
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

  it("non-convergence terminal: fixer failure raises decision gate on first round", async () => {
    const result = await runOnlineReviewLoopStage({
      poll: async () => baseSnapshot,
      dispatchVerify: async () => ({ kind: "verify", converged: false }),
      dispatchFixer: async () => false,
      dispatchCleanup: async (_landing) => true,
      dispatchDocRelease: async (_landing) => true,
      applySideEffects: (verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result).toEqual({
      ok: false,
      terminalState: "decision_gate_raised",
      round: 1,
    });
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
  });

  class HookPollBackend implements Backend {
    readonly hookCalls: string[] = [];

    async findResumeState(): Promise<undefined> {
      return undefined;
    }
    async cleanResidue(): Promise<void> {}
    async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
      return {
        number: issueNumber,
        isReadyForAgent: true,
        hasSubIssues: false,
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
    async writeLedger(): Promise<void> {}
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
    async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
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
        override async pollOnlineReviewState(input: {
          repo: string;
          prUrl: string;
          pollCount: number;
        }): Promise<OnlineReviewLandingSnapshot> {
          this.hookCalls.push(input.prUrl);
          return { ...greenHookSnapshot(), prUrl: offlinePr };
        }
        override async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
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
          return super.dispatchWorker(spec);
        }
      }
      const backend = new OfflineHookBackend();
      const result = await runOrchestrator({ issueNumber: 600, backend });
      expect(result.status).toBe("success");
      expect(backend.hookCalls).toEqual([offlinePr]);
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
    readonly reviewLoopLandings: WorkerLandingPayload[] = [];
    readonly ledger: FamilyLedgerEntry[] = [];

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

  it("happy path passes onlineReviewSnapshot landing into cleanup and docRelease", async () => {
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
      expect(backend.reviewLoopLandings).toHaveLength(2);
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

  it("family verify that moves HEAD terminates contract_drift without accepting converged output", async () => {
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
      expect(result).toEqual({
        ok: false,
        terminalState: "contract_drift",
        round: 1,
        stopSummary: expect.objectContaining({
          reason: "contract_drift",
          summary: expect.stringContaining("verify worker moved HEAD"),
        }),
      });
      expect(headReadCount).toBeGreaterThanOrEqual(2);
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
      });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("RealFamilyBackend-derived worker records cleanup landing with snapshot", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    const here = dirname(fileURLToPath(import.meta.url));
    const realPromptsDir = join(here, "..", "prompts");
    const realSoulsDir = join(here, "..", "image", "souls");
    try {
      class ProbeBackend extends RealFamilyBackend {
        readonly landings: WorkerLandingPayload[] = [];
        protected override async runFamilyReviewLoopWorker(
          spec: WorkerSpec,
          _ctx: DispatchContext,
          landing?: WorkerLandingPayload,
        ): Promise<WorkerResult> {
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
      expect(
        backend.landings.some((l) => l.onlineReviewSnapshot !== undefined),
      ).toBe(true);
      expect(backend.landings.length).toBeGreaterThanOrEqual(2);
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });
});