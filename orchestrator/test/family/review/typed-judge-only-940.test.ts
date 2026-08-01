import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  dispatchWorkerWithMonitor,
  runOnlineReviewLoopStage,
  runVerifyCmr,
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  PrReviewSnapshot,
  Backend,
  CliMonitorSpawnSpec,
  ShipResult,
  VerifyResult,
  WorkerResult,
  WorkerSpec,
  buildExplicitLandingLiveHooks,
  tempDirs,
  STAGE_SHIP,
  BASE_SNAPSHOT,
  coderSpec,
  completedJudgeGreen,
  completedShip,
  DispatchCapableBackend,
} from "./typed-judge-only-940.shared.js";
import { onlineReviewDispatch } from "../../helpers/online-review-dispatch.js";

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("#940 public driver — ID-012 online review typed judge only", () => {
  it("POSITIVE: host loop has no applySideEffects/poll seams and no mechanical round cap", async () => {
    // #1145: Runner stage only routes; Online Review Action owns GH + effects.
    const loopMod = await import("../../../src/family/onlineReviewLoop.js");
    expect("MAX_ONLINE_REVIEW_ROUNDS" in loopMod).toBe(false);
    const stageSrc = readFileSync(
      join(
        dirname(fileURLToPath(import.meta.url)),
        "../../../src/family/onlineReviewLoop.ts",
      ),
      "utf8",
    );
    expect(stageSrc).not.toMatch(/readonly poll\s*:/);
    expect(stageSrc).not.toMatch(/readonly applySideEffects\s*:/);
    expect(stageSrc).not.toMatch(/dispatch\.applySideEffects/);
    expect(stageSrc).not.toMatch(/dispatch\.poll/);
  });

  it("POSITIVE: mergeable accepts converged verify without host side-effect replay (#1145)", async () => {
    // Worker reports converged after executing its own side effects; stage must
    // NOT require a host applySideEffects seam — sole owner is the Action.
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, onlineReviewDispatch({
      snapshot: BASE_SNAPSHOT,
      dispatchVerify: async () =>
        ({
          kind: "verify",
          status: "converged",
        }) satisfies VerifyResult,
      dispatchFixer: async () => {
        throw new Error("fixer must not run on converged");
      },

    }));
    expect(result).toMatchObject({
      ok: true,
      terminalState: "mergeable",
      round: 1,
      binding: "bound" as const,
    });
  });

  it("POSITIVE: continue disposition past former 3-round cap still routes until worker converges", async () => {
    let verifyCalls = 0;
    let fixerCalls = 0;
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, onlineReviewDispatch({
      snapshot: async (round) => ({ ...BASE_SNAPSHOT, pollCount: round }),
      dispatchVerify: async (_landing, round) => {
        verifyCalls += 1;
        // Former host cap was 3 fixer rounds / 4th verify-only. Round 5 still
        // continues under judge ownership and finally converges.
        if (round >= 5) {
          return { kind: "verify", status: "converged" } satisfies VerifyResult;
        }
        return {
          kind: "verify",
          status: "continue",
          findingDispositions: [
            {
              identityKey: `live:${round}`,
              threadId: String(round),
              action: "fix",
            },
          ],
          fixMarkedFindingIdentityKeys: [`live:${round}`],
        } satisfies VerifyResult;
      },
      dispatchFixer: async () => {
        fixerCalls += 1;
        return {
          kind: "fixer",
          committed: true,
          fixCommitSha: `fix-${fixerCalls}`,
        };
      },

    }));
    expect(result).toMatchObject({
      ok: true,
      terminalState: "mergeable",
      round: 5,
      binding: "bound" as const,
    });
    expect(fixerCalls).toBe(4);
    // #1145: each fixer returns to the same-round Verify (opaque cargo) before
    // three-state continue opens the next Collector — 4×(V+F+V) + final V.
    expect(verifyCalls).toBe(9);
  });

  it("POSITIVE: worker escalate (decision_gate) ends the loop without host empty-success", async () => {
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, onlineReviewDispatch({
      snapshot: BASE_SNAPSHOT,
      dispatchVerify: async () =>
        ({
          kind: "verify",
          status: "escalate",
        }) satisfies VerifyResult,
      dispatchFixer: async () => {
        throw new Error("fixer must not run after escalate disposition");
      },

    }));
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate_raised");
  });

  it("NEGATIVE: host never mints round_budget_exhausted (deleted mechanical cap)", async () => {
    let rounds = 0;
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, onlineReviewDispatch({
      snapshot: async (round) => {
        rounds = round;
        return { ...BASE_SNAPSHOT, pollCount: round };
      },
      dispatchVerify: async (_landing, round) => {
        // After many continues, worker escalates — host must not invent budget exhaust.
        if (round >= 6) {
          return {
            kind: "verify",
            status: "escalate",
          } satisfies VerifyResult;
        }
        return { kind: "verify", status: "continue" } satisfies VerifyResult;
      },
      dispatchFixer: async () => ({
        kind: "fixer",
        committed: true,
        fixCommitSha: "fix-sha",
      }),

    }));
    expect(result.terminalState).not.toBe("round_budget_exhausted");
    expect(result.terminalState).toBe("decision_gate_raised");
    expect(rounds).toBeGreaterThanOrEqual(6);
  });
});

describe("#940 public driver — ID-012 missing capability fake exits deleted", () => {
  it("POSITIVE: production path always dispatches cmr+ship via dispatchWorker (no missing-capability branch)", async () => {
    const kinds: string[] = [];
    const backend = new DispatchCapableBackend(async (spec) => {
      kinds.push(spec.kind);
      if (spec.kind === "cmr") return completedJudgeGreen();
      if (spec.kind === "ship") return completedShip();
      // Online-review / fixer / landing not fully exercised here — ship
      // returns a PR; barrier may continue into online review which needs more
      // surface. For this pin we only need cmr+ship to have been dispatched.
      return {
        kind: "failed",
        reason: `unexpected kind ${spec.kind} in #940 capability pin`,
      };
    });

    const res = await runVerifyCmr({
      phase: "final",
      familyBase: "family/940-base",
      familyBackend: backend,
    });

    // CMR completeness + correctness both go through dispatchWorker.
    expect(kinds.filter((k) => k === "cmr").length).toBeGreaterThanOrEqual(2);
    expect(kinds).toContain("ship");
    // Missing-capability stageGate strings must not appear.
    const abortReasons = backend.ledger
      .filter((e) => e.status === "aborted")
      .map((e) => e.reason ?? "");
    expect(abortReasons.join("\n")).not.toMatch(
      /backend has no (dispatchWorker|ship) capability|ship-capability-missing/i,
    );
    // Either greener path continues or later stage fails for unrelated reasons —
    // never the deleted missing-capability fake exit.
    if (res.ok === false && "failedStatus" in res) {
      expect(res.failedStatus).not.toBeUndefined();
      // ship_failed is still legal when ship worker returns failed; what is
      // illegal is the host-only "no capability" mint before dispatch.
    }
  });
});

describe("#940 unified worker dispatch — ID-004 / ID-006 still hold", () => {
  it("POSITIVE: process-root budget remains 6 attempts × five 15s intervals (ID-004)", () => {
    expect(MAX_DISPATCH_ATTEMPTS).toBe(6);
    expect(DISPATCH_RETRY_BACKOFF_MS).toEqual([
      15_000, 15_000, 15_000, 15_000, 15_000,
    ]);
  });

  it("POSITIVE: durable completed outcome is never process-retried (ID-004)", async () => {
    let calls = 0;
    const result = await withMechanicalRetry(
      coderSpec(),
      {},
      async () => {
        calls += 1;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
    );
    expect(calls).toBe(1);
    expect(result.kind).toBe("completed");
  });

});
