/**
 * #600 — online review-loop: bot polling + verify/fixer/reverify convergence.
 */

import { describe, expect, it } from "vitest";
import { MAX_DISPATCH_ATTEMPTS, withMechanicalRetry } from "../src/dispatchRetry.js";
import { verifyWorkerSpec, fixerWorkerSpec } from "../src/dispatchWorker.js";
import type { DispatchContext, WorkerResult, WorkerSpec } from "../src/types.js";
import {
  BOT_OVERDUE_POLL_COUNT,
  BOT_POLL_INTERVAL_MS,
  BOT_RETRIGGER_COMMENT,
  droppedBotIds,
  hasDroppedBots,
  isBotQuiescent,
  isThreadEvidenceFresh,
  ONLINE_REVIEW_BOT_IDS,
  parsePrRef,
  pollPrReviewState,
  postBotRetriggerComment,
} from "../src/botPolling.js";
import {
  immediateBotPollClock,
  MAX_ONLINE_REVIEW_ROUNDS,
  retriggerBotsAndPoll,
  waitForBotQuiescence,
} from "../src/onlineReviewLoop.js";
import { route } from "../src/route.js";
import {
  buildOnlineReviewLanding,
  isReviewLoopConvergedMarker,
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
import type { Sh } from "../src/familyDriver.js";

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
        },
      ]);
    }
    if (cmd.includes("pulls/comments/") && cmd.includes("/reactions")) {
      return "[]";
    }
    if (cmd.includes("pulls/42/reviews")) {
      return JSON.stringify([
        { user: { login: "chatgpt-codex-connector[bot]" }, state: "COMMENTED" },
      ]);
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

  it("pollPrReviewState collects bot legs and marks quiescent when all complete/dropped", () => {
    const calls: string[] = [];
    const sh = ghFixture({ calls });
    const snap = pollPrReviewState(sh, {
      repo: "o/r",
      prUrl: "https://github.com/o/r/pull/42",
      pollCount: 1,
    });
    expect(snap.headOid).toBe("headsha1");
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
      if (cmd.includes("pulls/42/reviews")) {
        return JSON.stringify([
          { user: { login: "gemini-code-assist[bot]" }, state: "APPROVED" },
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
    retriggerBotsAndPoll(sh, "o/r", "https://github.com/o/r/pull/42", 2);
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