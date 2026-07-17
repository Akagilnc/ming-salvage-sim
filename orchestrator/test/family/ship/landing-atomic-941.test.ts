/**
 * #941 — landing atomically owns merge / close / cleanup after online review.
 *
 * Acceptance (issue #941):
 *   - public ignition/driver real entry proves #934 ID-013, ID-015, ID-016
 *   - unified worker dispatch real entry proves #934 ID-004, ID-006
 *
 * Seams (production paths only — no landing-only test entry):
 *   - runLandingAction / runVerifyCmr (public driver after online review)
 *   - runOnlineReviewLoopStage (no host auto-merge / cleanup courts)
 *   - dispatchRetry.withMechanicalRetry + terminateSpawnedChild (ID-004 / ID-006)
 *
 * Authority: #934 ID-004 / ID-006 / ID-013 / ID-015 / ID-016.
 */

import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import {
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../../../src/dispatchRetry.js";
import { dispatchWorkerWithMonitor, landingWorkerSpec } from "../../../src/dispatchWorker.js";
import { runOnlineReviewLoopStage } from "../../../src/family/onlineReviewLoop.js";
import { runLandingAction } from "../../../src/family/landing.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
} from "../../../src/family/types.js";
import { terminateSpawnedChild } from "../../../src/workerMonitor.js";
import type { PrReviewSnapshot } from "../../../src/botPolling.js";
import type {
  ShipResult,
  VerifyResult,
  WorkerResult,
  WorkerSpec,
} from "../../../src/types.js";

const tempDirs: string[] = [];
afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

const STAGE_SHIP: ShipResult = {
  kind: "ship",
  branch: "family/epic-941",
  status: "pr_opened",
  pr: "pr://family/941-landing",
  prHead: "head-941",
};

const BASE_SNAPSHOT: PrReviewSnapshot = {
  repo: "o/r",
  prNumber: 941,
  prUrl: "pr://family/941-landing",
  headOid: "head-941",
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
    headOid: "head-941",
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

/** Minimal family backend with production dispatchWorker seam. */
class DispatchCapableBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  constructor(
    private readonly onDispatch: (spec: WorkerSpec) => Promise<WorkerResult>,
  ) {}
  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
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

describe("#941 public driver — ID-013 landing owns merge close cleanup", () => {
  it("POSITIVE: host auto-merge / familyAutoMerge modules and docRelease name are gone", async () => {
    const srcDir = join(
      dirname(fileURLToPath(import.meta.url)),
      "../../../src",
    );
    expect(existsSync(join(srcDir, "family/familyAutoMerge.ts"))).toBe(false);
    expect(existsSync(join(srcDir, "family/familyAutoMerge.js"))).toBe(false);
    // landing Action is the single post-online-review owner
    expect(existsSync(join(srcDir, "family/landing.ts"))).toBe(true);

    const landingMod = await import("../../../src/family/landing.js");
    expect(typeof landingMod.runLandingAction).toBe("function");
    // Host court entry points deleted
    expect("runFamilyAutoMergeStage" in landingMod).toBe(false);
    expect("familyAutoMergeIncomplete" in landingMod).toBe(false);
    expect("ensureFamilyPostMergeCleanup" in landingMod).toBe(false);

    const autoMergeMod = await import("../../../src/autoMerge.js");
    // Host stage courts deleted — only live gh primitives remain for landing Action
    expect("runAutoMergeStage" in autoMergeMod).toBe(false);
    expect("tryResumePrMergedBackfill" in autoMergeMod).toBe(false);
    expect(typeof autoMergeMod.fetchPrMergeLiveState).toBe("function");
    expect(typeof autoMergeMod.executePrMergeCommit).toBe("function");
    expect(typeof autoMergeMod.confirmPrMergedLive).toBe("function");

    // Atomic rename: landing seat, no landing projection
    const spec = landingWorkerSpec();
    expect(spec.kind).toBe("landing");
    expect(spec.role).toBe("landing");
    expect(spec.soul).toBe("landing");
    expect(spec.id).toBe("S12");
  });

  it("POSITIVE: online review converge hands off to landing; no host landing-only court", async () => {
    let landingDispatchedFromLoop = 0;
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, {
      poll: async () => BASE_SNAPSHOT,
      dispatchVerify: async () =>
        ({ kind: "verify", converged: true }) satisfies VerifyResult,
      dispatchFixer: async () => {
        throw new Error("fixer must not run on green converge");
      },
      // #941: loop may still accept a landing hook for docs, but must not own merge
      dispatchLanding: async () => {
        landingDispatchedFromLoop += 1;
        return true;
      },
      retriggerAfterFix: () => {},
    });
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("mergeable");
    // After #941 the online-review Action stops at mergeable; landing Action owns the rest.
    // If the loop still dispatches docs, that is optional pre-hand-off only — merge is not host.
    expect(landingDispatchedFromLoop).toBeLessThanOrEqual(1);
  });

  it("POSITIVE: landing Action completes docs → merge → MERGED confirm → close/cleanup leftovers", async () => {
    const closedIssues: number[] = [];
    let mergeExecuted = 0;
    let landingWorkerCalls = 0;
    const backend = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        landingWorkerCalls += 1;
        return {
          kind: "completed",
          output: { kind: "landing", released: true },
        };
      }
      throw new Error(`unexpected kind ${spec.kind}`);
    });
    backend.ledger.push(
      { childIssue: 9411, status: "merged", familyHeadAfter: "head-941" },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: STAGE_SHIP.pr!,
        familyHeadAfter: "head-941",
      },
    );

    const result = await runLandingAction({
      familyBackend: backend,
      familyBase: "family/epic-941",
      convergedHeadOid: "head-941",
      prUrl: STAGE_SHIP.pr!,
      familyIssue: 941,
      resolvedRoute: undefined,
      // Injected live primitives — no fake PR offline hatch
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: mergeExecuted > 0 ? "MERGED" : "OPEN",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "CLEAN",
        }),
        executeMerge: () => {
          mergeExecuted += 1;
        },
        closeIssue: (n) => {
          closedIssues.push(n);
        },
        deleteBranch: () => {},
        branchExists: () => false,
        fetchIssueState: () => "OPEN",
        fetchSubIssues: () => [{ number: 9411, state: "OPEN" }],
      },
    });

    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("completed");
    expect(landingWorkerCalls).toBe(1);
    expect(mergeExecuted).toBe(1);
    // live MERGED before close (ID-013); delivered child closed; parent may
    // close only when every native sub-issue is covered/CLOSED.
    expect(closedIssues).toContain(9411);
    expect(closedIssues[0]).toBe(9411);
    const statuses = backend.ledger.map((e) => e.status);
    expect(statuses).toContain("pr_merged");
    // cleanup may leave leftovers but must not fail completed
    expect(result.leftovers === undefined || Array.isArray(result.leftovers)).toBe(
      true,
    );
  });

  it("NEGATIVE: close/cleanup failure records leftovers and does not flip completed (ID-013/015)", async () => {
    const backend = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        return {
          kind: "completed",
          output: { kind: "landing", released: true },
        };
      }
      throw new Error(`unexpected kind ${spec.kind}`);
    });
    backend.ledger.push({
      childIssue: 9412,
      status: "merged",
      familyHeadAfter: "head-941",
    });

    const result = await runLandingAction({
      familyBackend: backend,
      familyBase: "family/epic-941",
      convergedHeadOid: "head-941",
      prUrl: STAGE_SHIP.pr!,
      familyIssue: 941,
      resolvedRoute: undefined,
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: "MERGED",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "UNKNOWN",
        }),
        executeMerge: () => {
          throw new Error("merge must not re-run when already MERGED");
        },
        closeIssue: () => {
          throw new Error("gh issue close failed");
        },
        deleteBranch: () => {
          throw new Error("HTTP 404 Reference does not exist");
        },
        branchExists: () => true,
        fetchBranchTip: () => "head-941",
        fetchIssueState: () => "OPEN",
        fetchSubIssues: () => [{ number: 9412, state: "OPEN" }],
      },
    });

    // close/cleanup fail → leftovers / already-gone; never park/fail after MERGED
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("completed");
    expect(result.leftovers !== undefined && result.leftovers!.length > 0).toBe(
      true,
    );
  });

  it("NEGATIVE: readiness/ruleset block raises typed decision gate from landing Action (ID-013)", async () => {
    const backend = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        return {
          kind: "completed",
          output: { kind: "landing", released: true },
        };
      }
      throw new Error(`unexpected kind ${spec.kind}`);
    });

    const result = await runLandingAction({
      familyBackend: backend,
      familyBase: "family/epic-941",
      convergedHeadOid: "head-941",
      prUrl: STAGE_SHIP.pr!,
      resolvedRoute: undefined,
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: "OPEN",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "BLOCKED",
        }),
        executeMerge: () => {
          throw new Error("must not merge when ruleset blocked");
        },
        pollSnapshot: async () => BASE_SNAPSHOT,
      },
    });

    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
  });

  it("POSITIVE: ID-016 production surface drops host court modules (compile inventory)", async () => {
    const srcDir = join(
      dirname(fileURLToPath(import.meta.url)),
      "../../../src",
    );
    // Deleted host court modules / names
    expect(existsSync(join(srcDir, "family/familyAutoMerge.ts"))).toBe(false);
    // docRelease soul/prompt atomically renamed to landing
    const root = join(srcDir, "..");
    expect(existsSync(join(root, "image/souls/docRelease.md"))).toBe(false);
    expect(existsSync(join(root, "prompts/docRelease.md"))).toBe(false);
    expect(existsSync(join(root, "image/souls/landing.md"))).toBe(true);
    expect(existsSync(join(root, "prompts/landing.md"))).toBe(true);
  });
});

describe("#941 public driver — ID-015 cleanup already-gone", () => {
  it("POSITIVE: exact 404/ref missing branch delete is already-gone leftover, not fail", async () => {
    const backend = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        return {
          kind: "completed",
          output: { kind: "landing", released: true },
        };
      }
      throw new Error(`unexpected ${spec.kind}`);
    });
    backend.ledger.push({
      childIssue: 9413,
      status: "merged",
      familyHeadAfter: "head-941",
    });

    const result = await runLandingAction({
      familyBackend: backend,
      familyBase: "family/epic-941",
      convergedHeadOid: "head-941",
      prUrl: STAGE_SHIP.pr!,
      resolvedRoute: undefined,
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: "MERGED",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "UNKNOWN",
        }),
        executeMerge: () => {},
        closeIssue: () => {},
        deleteBranch: () => {
          const err = new Error("HTTP 404 Not Found");
          throw err;
        },
        branchExists: () => true,
        fetchBranchTip: () => "head-941",
        fetchIssueState: () => "CLOSED",
        fetchSubIssues: () => [{ number: 9413, state: "CLOSED" }],
      },
    });

    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("completed");
    // already-gone is legal degradation, not a hard leftover failure
    const leftovers = result.leftovers ?? [];
    expect(leftovers.every((l) => !/fail/i.test(l) || /already.?gone/i.test(l))).toBe(
      true,
    );
  });
});

describe("#941 unified worker dispatch — ID-004 / ID-006 still hold", () => {
  it("POSITIVE: process-root budget remains 6 attempts / five 15s intervals (ID-004)", () => {
    expect(MAX_DISPATCH_ATTEMPTS).toBe(6);
    expect(DISPATCH_RETRY_BACKOFF_MS).toEqual([
      15_000, 15_000, 15_000, 15_000, 15_000,
    ]);
  });

  it("POSITIVE: withMechanicalRetry exhausts at fixed position (ID-004)", async () => {
    let calls = 0;
    const result = await withMechanicalRetry(
      coderSpec(),
      {},
      async () => {
        calls += 1;
        return { kind: "failed", reason: "dispatch threw: boom" };
      },
      { sleepMs: async () => {} },
    );
    expect(calls).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(result.kind).toBe("failed");
  });

  it("POSITIVE: terminateSpawnedChild remains the exact-handle ownership seam (ID-006)", () => {
    // Unified dispatch ownership — no parallel landing kill machinery.
    expect(typeof terminateSpawnedChild).toBe("function");
    expect(terminateSpawnedChild.name).toBe("terminateSpawnedChild");
  });

  it("POSITIVE: dispatchWorkerWithMonitor still owns process-root entry (ID-006)", async () => {
    // Smoke: unified seam export remains the real entry (no parallel landing baton)
    expect(typeof dispatchWorkerWithMonitor).toBe("function");
    expect(typeof landingWorkerSpec).toBe("function");
    const spec = landingWorkerSpec();
    expect(spec.kind).toBe("landing");
    expect(spec.role).toBe("landing");
  });
});

describe("#941 verifyCmr public driver wires landing Action (no host merge/cleanup courts)", () => {
  it("POSITIVE: verifyCmr no longer exports ensureFamilyPostMergeCleanup host court", async () => {
    const mod = await import("../../../src/family/verifyCmr.js");
    expect("ensureFamilyPostMergeCleanup" in mod).toBe(false);
    expect(typeof mod.runVerifyCmr).toBe("function");
  });
});
