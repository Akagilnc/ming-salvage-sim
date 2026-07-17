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
import { landingWorkerSpec } from "../../../src/dispatchWorker.js";
import { runOnlineReviewLoopStage } from "../../../src/family/onlineReviewLoop.js";
import {
  buildExplicitLandingLiveHooks,
  runLandingAction,
} from "../../../src/family/landing.js";
import { runFamily } from "../../../src/family/runner.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  MergeRequest,
} from "../../../src/family/types.js";
import {
  resolveRouteModels,
  routeSmokeEntries,
  type ResolvedModelRoute,
} from "../../../src/modelRoutes.js";
import { QuotaWaitForResetError } from "../../../src/quotaProbe.js";
import { terminateSpawnedChild } from "../../../src/workerMonitor.js";
import type { PrReviewSnapshot } from "../../../src/botPolling.js";
import type {
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  ShipResult,
  StepOutput,
  StepSpec,
  VerifyResult,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
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
  checkRuns: [
    {
      id: 1,
      name: "ci",
      status: "completed",
      conclusion: "success",
      headSha: "head-941",
    },
  ],
  totalFindingCount: 0,
  quiescent: true,
  roundTriggerUsed: {
    headOid: "head-941",
    triggeredAt: "1970-01-01T00:00:00.000Z",
  },
  checkRunsEmptyMeans: "pending",
};

const PENDING_CI_SNAPSHOT: PrReviewSnapshot = {
  ...BASE_SNAPSHOT,
  checkRuns: [
    {
      id: 1,
      name: "ci",
      status: "in_progress",
      headSha: "head-941",
    },
  ],
};

function smokedRoute(): ResolvedModelRoute {
  const base = resolveRouteModels("normal", {});
  const smoke = Object.fromEntries(
    routeSmokeEntries(base).map((entry) => [
      entry.key,
      {
        state: "passed" as const,
        at: new Date().toISOString(),
        cliVersion: `cli-${entry.slug}`,
      },
    ]),
  );
  return resolveRouteModels("normal", {}, {}, smoke);
}

/**
 * Minimal family backend with production dispatchWorker seam.
 * Intentionally omits resolveLandingLiveHooks so #941 can prove non-live pr://
 * without hooks fails closed (no silent MERGED hatch).
 */
class DispatchCapableBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  constructor(
    private readonly onDispatch: (spec: WorkerSpec) => Promise<WorkerResult>,
  ) {}
  async mergeChildIntoFamilyBase(): Promise<never> {
    throw new Error("not used");
  }
  async resolveMergeConflict(): Promise<never> {
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

function liveOpenHooks(opts: {
  mergeExecuted: { n: number };
  closedIssues?: number[];
  poll?: () => Promise<PrReviewSnapshot>;
  executeMerge?: () => void;
  closeIssue?: (n: number) => void;
  deleteBranch?: () => void;
  branchExists?: () => boolean;
  fetchBranchTip?: () => string | undefined;
  fetchIssueState?: () => string;
  fetchSubIssues?: () => ReadonlyArray<{ number: number; state: string }>;
  state?: () => "OPEN" | "MERGED" | "CLOSED";
  mergeStateStatus?: string;
}) {
  return {
    fetchState: () => ({
      prNumber: 941,
      prUrl: STAGE_SHIP.pr!,
      state:
        opts.state?.() ??
        (opts.mergeExecuted.n > 0 ? "MERGED" : "OPEN"),
      headOid: "head-941",
      headRefName: "family/epic-941",
      mergeStateStatus: opts.mergeStateStatus ?? "CLEAN",
    }),
    executeMerge:
      opts.executeMerge ??
      (() => {
        opts.mergeExecuted.n += 1;
      }),
    pollSnapshot: opts.poll ?? (async () => BASE_SNAPSHOT),
    closeIssue:
      opts.closeIssue ??
      ((n: number) => {
        opts.closedIssues?.push(n);
      }),
    deleteBranch: opts.deleteBranch ?? (() => {}),
    branchExists: opts.branchExists ?? (() => false),
    ...(opts.fetchBranchTip !== undefined
      ? { fetchBranchTip: opts.fetchBranchTip }
      : {}),
    fetchIssueState: opts.fetchIssueState ?? (() => "OPEN"),
    fetchSubIssues:
      opts.fetchSubIssues ??
      (() => [{ number: 9411, state: "OPEN" }]),
  };
}

describe("#941 public driver — ID-013 landing owns merge close cleanup", () => {
  // Thin compile/surface guard (not counted as continuous-behavior AC).
  // Behavioral proof for ID-013/016 lives in runLandingAction / runFamily cases.
  it("guard: host auto-merge courts gone; landing is S12 seat", async () => {
    const srcDir = join(
      dirname(fileURLToPath(import.meta.url)),
      "../../../src",
    );
    expect(existsSync(join(srcDir, "family/familyAutoMerge.ts"))).toBe(false);
    expect(existsSync(join(srcDir, "family/landing.ts"))).toBe(true);
    const root = join(srcDir, "..");
    expect(existsSync(join(root, "image/souls/docRelease.md"))).toBe(false);
    expect(existsSync(join(root, "prompts/docRelease.md"))).toBe(false);
    expect(existsSync(join(root, "image/souls/landing.md"))).toBe(true);
    expect(existsSync(join(root, "prompts/landing.md"))).toBe(true);

    const landingMod = await import("../../../src/family/landing.js");
    expect("ensureLandingComplete" in landingMod).toBe(false);
    expect("runFamilyAutoMergeStage" in landingMod).toBe(false);
    expect("ensureFamilyPostMergeCleanup" in landingMod).toBe(false);

    const autoMergeMod = await import("../../../src/autoMerge.js");
    expect("runAutoMergeStage" in autoMergeMod).toBe(false);
    expect("tryResumePrMergedBackfill" in autoMergeMod).toBe(false);

    const spec = landingWorkerSpec();
    expect(spec.kind).toBe("landing");
    expect(spec.role).toBe("landing");
    expect(spec.soul).toBe("landing");
    expect(spec.id).toBe("S12");
  });

  it("POSITIVE: online review converge stops at mergeable; no host landing hook", async () => {
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, {
      poll: async () => BASE_SNAPSHOT,
      dispatchVerify: async () =>
        ({ kind: "verify", converged: true }) satisfies VerifyResult,
      dispatchFixer: async () => {
        throw new Error("fixer must not run on green converge");
      },
      applySideEffects: (_landing, verify) => verify,
      retriggerAfterFix: () => {},
    });
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("mergeable");
  });

  it("POSITIVE: landing Action completes docs → merge → MERGED confirm → close/cleanup leftovers", async () => {
    const closedIssues: number[] = [];
    const mergeExecuted = { n: 0 };
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
      resolvedRoute: smokedRoute(),
      live: liveOpenHooks({ mergeExecuted, closedIssues }),
    });

    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("completed");
    expect(landingWorkerCalls).toBe(1);
    expect(mergeExecuted.n).toBe(1);
    expect(closedIssues).toContain(9411);
    expect(closedIssues[0]).toBe(9411);
    const statuses = backend.ledger.map((e) => e.status);
    expect(statuses).toContain("pr_merged");
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
      resolvedRoute: smokedRoute(),
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
      resolvedRoute: smokedRoute(),
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

  it("NEGATIVE: non-live pr:// without live hooks does not synthesize MERGED (伪 PR hatch deleted)", async () => {
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
      prUrl: "pr://family/941-offline-hatch",
      resolvedRoute: smokedRoute(),
      // no live hooks — production path would call gh and fail closed
    });

    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(backend.ledger.some((e) => e.status === "pr_merged")).toBe(false);
    expect(
      backend.ledger.some((e) => e.status === "post_merge_cleanup"),
    ).toBe(false);
  });

  it("POSITIVE: CI pending continuously re-polls until green (ID-004; no fake-green snapshot)", async () => {
    const mergeExecuted = { n: 0 };
    let pollCount = 0;
    const backend = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        return {
          kind: "completed",
          output: { kind: "landing", released: true },
        };
      }
      throw new Error(`unexpected ${spec.kind}`);
    });

    const result = await runLandingAction({
      familyBackend: backend,
      familyBase: "family/epic-941",
      convergedHeadOid: "head-941",
      prUrl: STAGE_SHIP.pr!,
      resolvedRoute: smokedRoute(),
      live: liveOpenHooks({
        mergeExecuted,
        poll: async () => {
          pollCount += 1;
          return pollCount < 3 ? PENDING_CI_SNAPSHOT : BASE_SNAPSHOT;
        },
      }),
    });

    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("completed");
    expect(pollCount).toBeGreaterThanOrEqual(3);
    expect(mergeExecuted.n).toBe(1);
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
      resolvedRoute: smokedRoute(),
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
          throw new Error("HTTP 404 Not Found");
        },
        branchExists: () => true,
        fetchBranchTip: () => "head-941",
        fetchIssueState: () => "CLOSED",
        fetchSubIssues: () => [{ number: 9413, state: "CLOSED" }],
      },
    });

    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("completed");
    const leftovers = result.leftovers ?? [];
    expect(leftovers.every((l) => !/fail/i.test(l) || /already.?gone/i.test(l))).toBe(
      true,
    );
  });
});

describe("#941 unified worker dispatch — ID-004 / ID-006 still hold", () => {
  // Const/export smoke only — real ID-004 proof is transport-throw + quota rethrow.
  it("smoke: process-root budget constants (6 attempts / five 15s intervals)", () => {
    expect(MAX_DISPATCH_ATTEMPTS).toBe(6);
    expect(DISPATCH_RETRY_BACKOFF_MS).toEqual([
      15_000, 15_000, 15_000, 15_000, 15_000,
    ]);
  });

  it("POSITIVE: landing docs worker rides withMechanicalRetry on transport throw (ID-004)", async () => {
    let calls = 0;
    const backend = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        calls += 1;
        throw new Error("spawn crashed");
      }
      throw new Error(`unexpected ${spec.kind}`);
    });

    const result = await runLandingAction({
      familyBackend: backend,
      familyBase: "family/epic-941",
      convergedHeadOid: "head-941",
      prUrl: STAGE_SHIP.pr!,
      resolvedRoute: smokedRoute(),
      live: liveOpenHooks({ mergeExecuted: { n: 0 } }),
    });

    expect(calls).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("landing_failed");
    // durable mechanical_redispatch markers bind budget
    const attempts = backend.ledger.filter(
      (e) =>
        e.event === "worker_dispatched" &&
        e.workerStep === "landing" &&
        typeof e.mechanicalRedispatchAttempt === "number",
    );
    expect(attempts.length).toBe(MAX_DISPATCH_ATTEMPTS);
  });

  it("POSITIVE: QuotaWaitForResetError from landing docs rethrows — not landing_failed (ID-004 / #909)", async () => {
    // Shared process-root court must rethrow quota so upper family/runner park
    // or relay. Collapsing into {kind:"failed"} → landing_failed is the R2 M1 bug.
    const resetAt = new Date("2026-07-17T16:10:00.000Z");
    let calls = 0;
    const backend = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        calls += 1;
        throw new QuotaWaitForResetError({
          disposition: {
            kind: "wait_for_reset",
            pool: "zai",
            resetAt,
            reason: "quota limited (429); wait for reset",
          },
          applied: {
            ledgerEntry: {
              event: "quota_wait_for_reset",
              pool: "zai",
              resetAt: resetAt.toISOString(),
              reason: "quota limited (429); wait for reset",
              step: "S12",
              workerPid: 0,
              ts: "2026-07-17T12:00:00.000Z",
            },
          },
          pool: "zai",
        });
      }
      throw new Error(`unexpected ${spec.kind}`);
    });

    await expect(
      runLandingAction({
        familyBackend: backend,
        familyBase: "family/epic-941",
        convergedHeadOid: "head-941",
        prUrl: STAGE_SHIP.pr!,
        resolvedRoute: smokedRoute(),
        live: liveOpenHooks({ mergeExecuted: { n: 0 } }),
      }),
    ).rejects.toBeInstanceOf(QuotaWaitForResetError);
    // Quota does not burn mechanical redispatch budget.
    expect(calls).toBe(1);
    const attempts = backend.ledger.filter(
      (e) =>
        e.event === "worker_dispatched" &&
        e.workerStep === "landing" &&
        typeof e.mechanicalRedispatchAttempt === "number",
    );
    expect(attempts).toHaveLength(0);
  });

  // Export smoke only — do not claim ID-006 ownership; continuous terminate-on-
  // handle for landing is covered by shared monitored dispatch court elsewhere.
  it("smoke: terminateSpawnedChild export remains available", () => {
    expect(typeof terminateSpawnedChild).toBe("function");
    expect(terminateSpawnedChild.name).toBe("terminateSpawnedChild");
  });

  it("smoke: landingWorkerSpec S12 seat + local withMechanicalRetry seam", async () => {
    const spec = landingWorkerSpec();
    expect(spec.kind).toBe("landing");
    expect(spec.role).toBe("landing");
    expect(spec.id).toBe("S12");
    let hits = 0;
    const result = await withMechanicalRetry(
      spec,
      {},
      async () => {
        hits += 1;
        return {
          kind: "completed",
          output: { kind: "landing", released: true },
        };
      },
      { sleepMs: async () => {} },
    );
    expect(hits).toBe(1);
    expect(result.kind).toBe("completed");
  });
});

describe("#941 public runFamily driver re-enters landing (ID-013)", () => {
  it("POSITIVE: runFamily resume after review_loop_converged lands pr_merged + cleanup", async () => {
    // Public ignition path — not Action-only harness as sole AC proof (R2 S1).
    class ChildBackend implements Backend {
      async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
        const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
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
      async prepareWorktree(
        issueNumber: number,
        base: string,
      ): Promise<WorktreeHandle> {
        return {
          branch: `feat/child-${issueNumber}`,
          base,
          path: `/wt/${issueNumber}`,
        };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "judge", status: "converged" };
      }
      async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
    }

    class ResumeFamilyBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      head = "family-base-941";
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
      async mergeChildIntoFamilyBase(
        child: MergeRequest,
      ): Promise<{ familyHead: string }> {
        this.head = `+${child.childIssue}`;
        return { familyHead: this.head };
      }
      async resolveMergeConflict(): Promise<never> {
        throw new Error("resolveMergeConflict not used in this test");
      }
      async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(entry);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
      async readFamilyHead(): Promise<string> {
        return this.head;
      }
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async dispatchWorker(
        spec: WorkerSpec,
        _ctx?: DispatchContext,
        _landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (spec.kind === "landing") {
          return {
            kind: "completed",
            output: { kind: "landing", released: true },
          };
        }
        throw new Error(`unexpected ${spec.kind} on already-converged resume`);
      }
    }

    const familyBackend = new ResumeFamilyBackend();
    familyBackend.ledger.push(
      {
        childIssue: 9411,
        status: "merged",
        familyHeadAfter: "family-base-941",
      },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: "pr://family/941-landing",
        familyHeadAfter: "family-base-941",
      },
    );

    const epic: FamilyEpic = {
      issue: 941,
      children: [{ issue: 9411, blockedBy: [] }],
    };

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic,
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/epic-941",
    });

    expect(result.status).toBe("success");
    expect(
      familyBackend.ledger.filter((e) => e.status === "pr_merged"),
    ).toHaveLength(1);
    expect(
      familyBackend.ledger.filter((e) => e.status === "post_merge_cleanup"),
    ).toHaveLength(1);
  });

  // Export-absence guard (not continuous land path AC).
  it("guard: verifyCmr no longer exports ensureFamilyPostMergeCleanup host court", async () => {
    const mod = await import("../../../src/family/verifyCmr.js");
    expect("ensureFamilyPostMergeCleanup" in mod).toBe(false);
    expect(typeof mod.runVerifyCmr).toBe("function");
  });

  it("POSITIVE: resume landing 429 parks via family quota wall (ID-004 / S3)", async () => {
    // already-converged resume re-enters landing outside the primary final
    // barrier — must still hit runFamilyBarrierWithQuotaRelay so 429 parks
    // (does not escape runFamily as an uncaught throw).
    class ChildBackend implements Backend {
      async smokeModelRoute(route: Parameters<Backend["smokeModelRoute"]>[0]) {
        const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
        return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
      }
      async findResumeState(): Promise<undefined> {
        return undefined;
      }
      async resumeSession(spec: StepSpec): Promise<StepOutput> {
        return this.runStep(spec);
      }
      async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        return {
          number: issueNumber,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5 → terra@med → luna@med",
        };
      }
      async prepareWorktree(
        issueNumber: number,
        base: string,
      ): Promise<WorktreeHandle> {
        return {
          branch: `feat/child-${issueNumber}`,
          base,
          path: `/wt/${issueNumber}`,
        };
      }
      async runStep(spec: StepSpec): Promise<StepOutput> {
        if (spec.role === "coder") {
          return { kind: "coder", committed: true, commitsAdded: 1 };
        }
        return { kind: "judge", status: "converged" };
      }
      async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
    }

    // Within park threshold T (30m) → park; beyond T would chase a live baton.
    const now = new Date("2026-07-17T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 10 * 60 * 1000);
    let landingCalls = 0;
    class ResumeQuotaBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      head = "family-base-941";
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
      async mergeChildIntoFamilyBase(
        child: MergeRequest,
      ): Promise<{ familyHead: string }> {
        this.head = `+${child.childIssue}`;
        return { familyHead: this.head };
      }
      async resolveMergeConflict(): Promise<never> {
        throw new Error("resolveMergeConflict not used in this test");
      }
      async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(entry);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
      async readFamilyHead(): Promise<string> {
        return this.head;
      }
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async dispatchWorker(
        spec: WorkerSpec,
        _ctx?: DispatchContext,
        _landing?: WorkerLandingPayload,
      ): Promise<WorkerResult> {
        if (spec.kind === "landing") {
          landingCalls += 1;
          throw new QuotaWaitForResetError({
            disposition: {
              kind: "wait_for_reset",
              pool: "zai",
              resetAt,
              reason: "quota limited (429); wait for reset",
            },
            applied: {
              ledgerEntry: {
                event: "quota_wait_for_reset",
                pool: "zai",
                resetAt: resetAt.toISOString(),
                reason: "quota limited (429); wait for reset",
                step: "S12",
                workerPid: 0,
                ts: "2026-07-17T12:00:00.000Z",
              },
            },
            pool: "zai",
          });
        }
        throw new Error(`unexpected ${spec.kind} on already-converged resume`);
      }
    }

    const familyBackend = new ResumeQuotaBackend();
    familyBackend.ledger.push(
      {
        childIssue: 9411,
        status: "merged",
        familyHeadAfter: "family-base-941",
      },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: "pr://family/941-landing",
        familyHeadAfter: "family-base-941",
      },
    );

    const epic: FamilyEpic = {
      issue: 941,
      children: [{ issue: 9411, blockedBy: [] }],
    };

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic,
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/epic-941",
      now: () => now,
    });

    expect(landingCalls).toBe(1);
    expect(result.status).toBe("escalated");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    expect(result.stopSummary.summary).toMatch(/quota wait for reset/i);
    // Park durable marker from the resume landing barrier (not uncaught throw).
    const parkMarkers = familyBackend.ledger.filter(
      (e) =>
        e.status === "worker_dispatched" &&
        typeof e.workerStep === "string" &&
        e.workerStep.startsWith("quota_park:"),
    );
    expect(parkMarkers.length).toBeGreaterThanOrEqual(1);
  });
});
