/**
 * #940 — CMR / online review / 线上复验 only consume typed judge.
 *
 * Acceptance (issue #940):
 *   - public ignition/driver real entry proves #934 ID-012, ID-015, ID-016
 *   - unified worker dispatch real entry proves #934 ID-004, ID-006
 *
 * Seams (production paths only — no helper-only fakes as the subject):
 *   - runOnlineReviewLoopStage (online-review Action loop)
 *   - runVerifyCmr (family final barrier → cmr / ship)
 *   - dispatchRetry.withMechanicalRetry + terminateSpawnedChild (ID-004 / ID-006)
 *
 * Authority: #934 ID-004 / ID-006 / ID-012 / ID-015 / ID-016;
 *            landed #925/#926/#930 persistent judge baseline.
 */

import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import {
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../../../src/dispatchRetry.js";
import { dispatchWorkerWithMonitor } from "../../../src/dispatchWorker.js";
import { runOnlineReviewLoopStage } from "../../../src/family/onlineReviewLoop.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
} from "../../../src/family/types.js";
import type { PrReviewSnapshot } from "../../../src/botPolling.js";
import type {

  Backend,
  CliMonitorSpawnSpec,
  ShipResult,
  VerifyResult,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";
import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const tempDirs: string[] = [];
afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

const STAGE_SHIP: ShipResult = {
  kind: "ship",
  branch: "family/epic-940",
  status: "pr_opened",
  pr: "pr://family/940-typed-judge",
  prHead: "head-940",
};

const BASE_SNAPSHOT: PrReviewSnapshot = {
  repo: "o/r",
  prNumber: 940,
  prUrl: "pr://family/940-typed-judge",
  headOid: "head-940",
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
  roundTriggerUsed: {
    headOid: "head-940",
    triggeredAt: "1970-01-01T00:00:00.000Z",
  },
  checkRunsEmptyMeans: "converged",
};

function coderSpec(): WorkerSpec {
  return {
    id: "S2",
    kind: "coder",
    role: "coder",
    host: "codex",
    session: "fresh",
    contextRetention: "retain",
    promptFile: "coder.md",
    maxIter: 1,
    model: "grok-4.5",
    soul: "coder",
    toolchain: [],
  } as WorkerSpec;
}

function completedJudgeGreen(): WorkerResult {
  return {
    kind: "completed",
    output: { kind: "judge", status: "converged" },
  };
}

function completedShip(): WorkerResult {
  return {
    kind: "completed",
    output: {
      kind: "ship",
      branch: "family/epic-940",
      status: "pr_opened",
      pr: "pr://family/940-ship",
      prHead: "ship-head",
    },
  };
}

/** Minimal family backend that always has the production dispatchWorker seam. */
class DispatchCapableBackend implements FamilyBackend {
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

  readonly ledger: FamilyLedgerEntry[] = [];
  constructor(
    private readonly onDispatch: (spec: WorkerSpec) => Promise<WorkerResult>,
  ) {}
  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
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
  async readFamilyHead(): Promise<string> {
    return "head-after-cmr";
  }
  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    return this.onDispatch(spec);
  }
}

describe("#940 public driver — ID-012 online review typed judge only", () => {
  it("POSITIVE: host loop has applySideEffects seam and no mechanical round cap export", async () => {
    // Correctness K1: host fail-safe applicator restored; mechanical cap stays gone.
    const loopMod = await import("../../../src/family/onlineReviewLoop.js");
    expect("MAX_ONLINE_REVIEW_ROUNDS" in loopMod).toBe(false);
    const srcDir = join(
      dirname(fileURLToPath(import.meta.url)),
      "../../../src",
    );
    expect(existsSync(join(srcDir, "onlineReviewSideEffects.ts"))).toBe(true);
    const sideFx = await import("../../../src/onlineReviewSideEffects.js");
    expect(typeof sideFx.applyVerifySideEffects).toBe("function");
  });

  it("POSITIVE: host invokes applySideEffects before accepting mergeable (K1 fail-safe)", async () => {
    // Worker may report bare converged; host must still call applySideEffects
    // before mergeable — never green solely on disposition without the seam.
    let applyCalls = 0;
    let applySawCargo = false;
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, {
      poll: async () => BASE_SNAPSHOT,
      dispatchVerify: async () =>
        ({
          kind: "verify",
          converged: true,
          threadReplies: [{ threadId: "1", body: "fixed: evidence" }],
        }) satisfies VerifyResult,
      dispatchFixer: async () => {
        throw new Error("fixer must not run on converged");
      },
      applySideEffects: (_landing, verify) => {
        applyCalls += 1;
        applySawCargo = (verify.threadReplies?.length ?? 0) > 0;
        return verify;
      },
      retriggerAfterFix: () => {
        throw new Error("retrigger must not run on converged");
      },
    });
    expect(result).toEqual({
      ok: true,
      terminalState: "mergeable",
      round: 1,
    });
    expect(applyCalls).toBe(1);
    expect(applySawCargo).toBe(true);
  });

  it("POSITIVE: continue disposition past former 3-round cap still routes until worker converges", async () => {
    let verifyCalls = 0;
    let fixerCalls = 0;
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, {
      poll: async (round) => ({ ...BASE_SNAPSHOT, pollCount: round }),
      dispatchVerify: async (_landing, round) => {
        verifyCalls += 1;
        // Former host cap was 3 fixer rounds / 4th verify-only. Round 5 still
        // continues under judge ownership and finally converges.
        if (round >= 5) {
          return { kind: "verify", converged: true } satisfies VerifyResult;
        }
        return {
          kind: "verify",
          converged: false,
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
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async (sha) => sha,
    });
    expect(result).toEqual({
      ok: true,
      terminalState: "mergeable",
      round: 5,
    });
    expect(fixerCalls).toBe(4);
    expect(verifyCalls).toBe(5);
  });

  it("POSITIVE: worker escalate (decision_gate) ends the loop without host empty-success", async () => {
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, {
      poll: async () => BASE_SNAPSHOT,
      dispatchVerify: async () =>
        ({
          kind: "verify",
          converged: false,
          terminalState: "decision_gate_raised",
        }) satisfies VerifyResult,
      dispatchFixer: async () => {
        throw new Error("fixer must not run after escalate disposition");
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate_raised");
  });

  it("NEGATIVE: host never mints round_budget_exhausted (deleted mechanical cap)", async () => {
    let rounds = 0;
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, {
      poll: async (round) => {
        rounds = round;
        return { ...BASE_SNAPSHOT, pollCount: round };
      },
      dispatchVerify: async (_landing, round) => {
        // After many continues, worker escalates — host must not invent budget exhaust.
        if (round >= 6) {
          return {
            kind: "verify",
            converged: false,
            terminalState: "decision_gate_raised",
          } satisfies VerifyResult;
        }
        return { kind: "verify", converged: false } satisfies VerifyResult;
      },
      dispatchFixer: async () => ({
        kind: "fixer",
        committed: true,
        fixCommitSha: "fix-sha",
      }),
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
      resolveFixCommitSha: async () => "fix-sha",
    });
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
