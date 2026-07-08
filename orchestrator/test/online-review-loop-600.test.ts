/**
 * #600 — online review-loop: bot polling + verify/fixer/reverify convergence.
 */

import { describe, expect, it } from "vitest";
import {
  BOT_OVERDUE_POLL_COUNT,
  BOT_RETRIGGER_COMMENT,
  isBotQuiescent,
  ONLINE_REVIEW_BOT_IDS,
  parsePrRef,
  pollPrReviewState,
  postBotRetriggerComment,
} from "../src/botPolling.js";
import { MAX_ONLINE_REVIEW_ROUNDS } from "../src/onlineReviewLoop.js";
import { route } from "../src/route.js";
import {
  buildOnlineReviewLanding,
  verifyReviewerHeadMovedStopSummary,
} from "../src/onlineReviewLoop.js";
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
      return JSON.stringify([
        {
          author: { login: "coderabbitai[bot]" },
          body: "Summary: one nit on line 10",
        },
      ]);
    }
    if (cmd.includes("pulls/42/reviews")) {
      return JSON.stringify([
        { user: { login: "chatgpt-codex-connector[bot]" }, state: "COMMENTED" },
      ]);
    }
    if (cmd.includes("issues/42/comments") && cmd.includes("-f")) {
      return "{}";
    }
    return "[]";
  };
}

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

  it("S9 not converged at round cap → error", () => {
    expect(
      route({
        from: "S9",
        output: { kind: "verify", converged: false },
        onlineReviewRound: MAX_ONLINE_REVIEW_ROUNDS,
      }),
    ).toEqual({ kind: "handoff", status: "error" });
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
          gemini: { state: "complete", findingCount: 0 },
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