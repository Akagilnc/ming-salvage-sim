import { describe, expect, it } from "vitest";
import {
  onlineReviewJudgeSessionIdFromFamilyLedger,
  runOnlineReviewLoopStage,
} from "../src/family/onlineReviewLoop.js";
import type {
  FixerResult,
  WorkerLandingPayload,
} from "../src/types.js";

const ship = {
  kind: "ship" as const,
  branch: "fix/1145",
  pr: "https://github.com/test/repo/pull/1145",
  prHead: "head-6",
};

describe("online review typed topology and opaque transport (#1145)", () => {
  it("restores the resident judge session only for the bound PR", () => {
    const oldPr = "https://github.com/test/repo/pull/5";
    const currentPr = "https://github.com/test/repo/pull/6";
    const ledger = [
      {
        status: "online_review_judge_opened",
        event: "online_review_judge_opened",
        pr: oldPr,
        sessionId: "judge-old-5",
      },
      {
        status: "online_review_judge_opened",
        event: "online_review_judge_opened",
        pr: currentPr,
        sessionId: "judge-current-6",
      },
    ];

    expect(onlineReviewJudgeSessionIdFromFamilyLedger(ledger, currentPr)).toBe(
      "judge-current-6",
    );
    expect(
      onlineReviewJudgeSessionIdFromFamilyLedger(ledger, "https://github.com/test/repo/pull/7"),
    ).toBeUndefined();
  });

  it.each([
    ["converged", "mergeable", 0],
    ["escalate", "decision_gate_raised", 0],
  ] as const)("routes %s without consulting cargo", async (status, terminalState, expectedFixers) => {
    let fixerCalls = 0;
    const result = await runOnlineReviewLoopStage(ship, {
      dispatchCollector: async () => ({ evidence: { sparse: true } }),
      dispatchVerify: async () => ({ verify: { kind: "verify", status } }),
      dispatchFixer: async () => {
        fixerCalls += 1;
        return { kind: "fixer", committed: false };
      },
    });

    expect(result.terminalState).toBe(terminalState);
    expect(fixerCalls).toBe(expectedFixers);
  });

  it("moves the judge packet to Fixer and the whole Fixer result back without reading business cargo", async () => {
    const packetBody = new Proxy(
      { scene: "current-6-only" },
      {
        get() {
          throw new Error("runner read judge packet body");
        },
      },
    );
    const fixerResult: FixerResult = Object.freeze({
      kind: "fixer",
      committed: false,
      scene: "fixer-whole-body",
    });
    let fixerLanding: WorkerLandingPayload | undefined;
    let judgeRecheckLanding: WorkerLandingPayload | undefined;
    let verifyCalls = 0;

    const result = await runOnlineReviewLoopStage(ship, {
      dispatchCollector: async () => ({
        evidence: { scene: "old-5-and-current-6" },
        cargoPointer: "fixture://collector/current-6",
      }),
      dispatchVerify: async (landing) => {
        verifyCalls += 1;
        if (verifyCalls === 1) {
          return {
            verify: {
              kind: "verify",
              status: "continue",
              onlineReviewFixPacket: packetBody,
              get fixMarkedFindingIdentityKeys(): never {
                throw new Error("runner read legacy finding keys");
              },
              get fixMarkedFindingThreads(): never {
                throw new Error("runner read legacy finding threads");
              },
            },
          };
        }
        judgeRecheckLanding = landing;
        return { verify: { kind: "verify", status: "converged" } };
      },
      dispatchFixer: async (landing) => {
        fixerLanding = landing;
        return fixerResult;
      },
    });

    expect(fixerLanding?.onlineReviewFixPacket).toBe(packetBody);
    expect(judgeRecheckLanding?.fixerResult).toBe(fixerResult);
    expect(result).toMatchObject({ ok: true, terminalState: "mergeable" });
  });
});
