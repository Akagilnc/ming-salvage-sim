import { describe, expect, it } from "vitest";
import { runOnlineReviewLoopStage } from "../src/family/onlineReviewLoop.js";
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

describe("online review opaque transport (#1145 slice 1)", () => {
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
              converged: false,
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
        return { verify: { kind: "verify", converged: true } };
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
