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
  confirmPrMergedLive,
  mergeRecordIfHeadAligned,
  type PrMergeLiveState,
} from "../../../src/autoMerge.js";
import {
  buildExplicitLandingLiveHooks,
  classifyLandingActionResult,
  LANDING_CI_FETCH_FAILURE_LIMIT,
  LANDING_MERGED_CONFIRM_ATTEMPTS,
  recordLandingActionFailure,
  runLandingAction,
} from "../../../src/family/landing.js";
import {
  familyEscalationState,
  recordFamilyEscalated,
} from "../../../src/family/ledger.js";
import { runFamily } from "../../../src/family/runner.js";
import { runVerifyCmr } from "../../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  MergeRequest,
} from "../../../src/family/types.js";
import { decisionGateParkStopSummary } from "../../../src/stopSummary.js";
import {
  resolveRouteModels,
  routeSmokeEntries,
  type ResolvedModelRoute,
} from "../../../src/modelRoutes.js";
import { QuotaWaitForResetError } from "../../../src/quotaProbe.js";
import { skeletonReviewLoopWorkerResult } from "../../../src/reviewLoopOutcome.js";
import { completeReviewPanelLegWorker } from "../../helpers/review-panel-leg-dispatch.js";
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
import { onlineReviewDispatch } from "../../helpers/online-review-dispatch.js";

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
  pr: "https://github.com/test/repo/pull/941",
  prHead: "head-941",
};

const BASE_SNAPSHOT: PrReviewSnapshot = {
  repo: "o/r",
  prNumber: 941,
  prUrl: "https://github.com/test/repo/pull/941",
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
    // Match live hook headOid ("head-941") — completion head alignment
    // (CR-7) requires family HEAD and PR tip to agree after docs.
    return "head-941";
  }
  async runFamilyVerify(): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
    const panelLeg = completeReviewPanelLegWorker(spec);
    if (panelLeg !== undefined) return panelLeg;
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
    const result = await runOnlineReviewLoopStage(STAGE_SHIP, onlineReviewDispatch({
      snapshot: BASE_SNAPSHOT,
      dispatchVerify: async () =>
        ({ kind: "verify", status: "converged" }) satisfies VerifyResult,
      dispatchFixer: async () => {
        throw new Error("fixer must not run on green converge");
      },

    }));
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

  it("NEGATIVE: cleanup catch-path leftovers are unique (no double branch_already_gone / cleanup_exception)", async () => {
    // Catch previously pushed leftovers then set cleanupOutput.skippedReasons
    // to the same list; the ok+terminal else-if re-pushed → duplicates.
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

    const gone = await runLandingAction({
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
        // Uncaught by runPostMergeCleanup → landing catch (missing-ref class).
        closeIssue: () => {
          throw new Error("HTTP 404 Reference does not exist");
        },
        deleteBranch: () => {},
        branchExists: () => true,
        fetchBranchTip: () => "head-941",
        fetchIssueState: () => "OPEN",
        fetchSubIssues: () => [{ number: 9412, state: "OPEN" }],
      },
    });

    expect(gone.ok).toBe(true);
    expect(gone.terminalState).toBe("completed");
    const goneLeftovers = gone.leftovers ?? [];
    expect(goneLeftovers.filter((l) => l === "branch_already_gone")).toHaveLength(
      1,
    );
    expect(new Set(goneLeftovers).size).toBe(goneLeftovers.length);

    const backend2 = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        return {
          kind: "completed",
          output: { kind: "landing", released: true },
        };
      }
      throw new Error(`unexpected kind ${spec.kind}`);
    });
    backend2.ledger.push({
      childIssue: 9413,
      status: "merged",
      familyHeadAfter: "head-941",
    });

    const boom = await runLandingAction({
      familyBackend: backend2,
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
          throw new Error("unexpected cleanup boom");
        },
        deleteBranch: () => {},
        branchExists: () => true,
        fetchBranchTip: () => "head-941",
        fetchIssueState: () => "OPEN",
        fetchSubIssues: () => [{ number: 9413, state: "OPEN" }],
      },
    });

    expect(boom.ok).toBe(true);
    expect(boom.terminalState).toBe("completed");
    const boomLeftovers = boom.leftovers ?? [];
    const exceptionHits = boomLeftovers.filter((l) =>
      l.startsWith("cleanup_exception:"),
    );
    expect(exceptionHits).toHaveLength(1);
    expect(exceptionHits[0]).toContain("unexpected cleanup boom");
    expect(new Set(boomLeftovers).size).toBe(boomLeftovers.length);
  });

  it("POSITIVE: docs-advanced HEAD keys pr_merged/cleanup markers; re-entry already_done", async () => {
    // Docs landing worker may push commits past review_loop_converged HEAD.
    // Markers must key the post-docs live HEAD resume will re-read — not the
    // pre-doc convergedHeadOid — or already_done / skip-remerge miss.
    const PRE_DOC = "head-pre-docs-941";
    const POST_DOC = "head-post-docs-941";
    let head = PRE_DOC;
    let landingWorkerCalls = 0;
    let mergeExecuted = 0;

    class AdvancingHeadBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
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
        return head;
      }
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "landing") {
          landingWorkerCalls += 1;
          head = POST_DOC;
          return {
            kind: "completed",
            output: { kind: "landing", released: true },
          };
        }
        throw new Error(`unexpected kind ${spec.kind}`);
      }
    }

    const backend = new AdvancingHeadBackend();
    backend.ledger.push(
      { childIssue: 9414, status: "merged", familyHeadAfter: PRE_DOC },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: STAGE_SHIP.pr!,
        familyHeadAfter: PRE_DOC,
      },
    );

    const first = await runLandingAction({
      familyBackend: backend,
      familyBase: "family/epic-941",
      convergedHeadOid: PRE_DOC,
      prUrl: STAGE_SHIP.pr!,
      familyIssue: 941,
      resolvedRoute: smokedRoute(),
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: mergeExecuted > 0 ? "MERGED" : "OPEN",
          headOid: POST_DOC,
          headRefName: "family/epic-941",
          mergeStateStatus: "CLEAN",
        }),
        executeMerge: () => {
          mergeExecuted += 1;
        },
        confirmMerged: (expectedHeadOid) => ({
          kind: "aligned" as const,
          record: {
            prUrl: STAGE_SHIP.pr!,
            prNumber: 941,
            remoteBranchName: "family/epic-941",
            mergedHeadOid: expectedHeadOid,
            convergedHeadOid: expectedHeadOid,
          },
        }),
        pollSnapshot: async () => ({
          ...BASE_SNAPSHOT,
          headOid: POST_DOC,
          checkRuns: [
            {
              id: 1,
              name: "ci",
              status: "completed",
              conclusion: "success",
              headSha: POST_DOC,
            },
          ],
          roundTriggerUsed: {
            headOid: POST_DOC,
            triggeredAt: "1970-01-01T00:00:00.000Z",
          },
        }),
        closeIssue: () => {},
        deleteBranch: () => {},
        branchExists: () => false,
        fetchIssueState: () => "CLOSED",
        fetchSubIssues: () => [{ number: 9414, state: "CLOSED" }],
      },
    });

    expect(first.ok).toBe(true);
    expect(first.terminalState).toBe("completed");
    expect(landingWorkerCalls).toBe(1);
    expect(mergeExecuted).toBe(1);

    // CR-6: docs release is durable before merge. Non-empty push stamps both
    // pre-doc (immediate crash window) and post-doc keys (dual-key resume).
    const docsReleased = backend.ledger.filter((e) => e.status === "docs_released");
    const docsHeads = docsReleased.map((e) => e.familyHeadAfter);
    expect(docsHeads).toEqual(expect.arrayContaining([PRE_DOC, POST_DOC]));
    expect(docsReleased).toHaveLength(2);

    const prMerged = backend.ledger.filter((e) => e.status === "pr_merged");
    const cleanups = backend.ledger.filter(
      (e) => e.status === "post_merge_cleanup",
    );
    expect(prMerged).toHaveLength(1);
    expect(cleanups).toHaveLength(1);
    expect(prMerged[0]?.familyHeadAfter).toBe(POST_DOC);
    expect(cleanups[0]?.familyHeadAfter).toBe(POST_DOC);

    const convergedHeads = backend.ledger
      .filter((e) => e.status === "review_loop_converged")
      .map((e) => e.familyHeadAfter);
    expect(convergedHeads).toContain(POST_DOC);

    // Re-enter with live post-doc HEAD (what resume re-reads).
    const second = await runLandingAction({
      familyBackend: backend,
      familyBase: "family/epic-941",
      convergedHeadOid: POST_DOC,
      prUrl: STAGE_SHIP.pr!,
      familyIssue: 941,
      resolvedRoute: smokedRoute(),
      live: {
        fetchState: () => {
          throw new Error("already_done must not re-fetch PR");
        },
        executeMerge: () => {
          throw new Error("already_done must not re-merge");
        },
      },
    });

    expect(second.ok).toBe(true);
    expect(second.terminalState).toBe("already_done");
    expect(landingWorkerCalls).toBe(1);
    expect(mergeExecuted).toBe(1);
    expect(
      backend.ledger.filter((e) => e.status === "pr_merged"),
    ).toHaveLength(1);
    expect(
      backend.ledger.filter((e) => e.status === "post_merge_cleanup"),
    ).toHaveLength(1);
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

  it("NEGATIVE Std S4: repeated mid-loop fetchState failures park as decision_gate", async () => {
    let fetchCalls = 0;
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
      live: {
        fetchState: () => {
          fetchCalls += 1;
          // First call enters CI-pending loop (OPEN+CLEAN + pending checks).
          // Mid-loop refresh always dies — pre-fix keep-prior would spin forever.
          if (fetchCalls === 1) {
            return {
              prNumber: 941,
              prUrl: STAGE_SHIP.pr!,
              state: "OPEN",
              headOid: "head-941",
              headRefName: "family/epic-941",
              mergeStateStatus: "CLEAN",
            };
          }
          throw new Error("gh auth dead");
        },
        executeMerge: () => {
          throw new Error("must not merge while fetch is dead");
        },
        pollSnapshot: async () => PENDING_CI_SNAPSHOT,
      },
    });

    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
    expect(result.stopSummary?.summary).toMatch(/fetch failed repeatedly/i);
    // initial + LANDING_CI_FETCH_FAILURE_LIMIT consecutive mid-loop failures
    expect(fetchCalls).toBe(1 + LANDING_CI_FETCH_FAILURE_LIMIT);
  });

  it("NEGATIVE Std R2 S1: repeated mid-loop pollSnapshot failures park as decision_gate", async () => {
    let pollCalls = 0;
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
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: "OPEN",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "CLEAN",
        }),
        executeMerge: () => {
          throw new Error("must not merge while poll is dead");
        },
        pollSnapshot: async () => {
          pollCalls += 1;
          // First poll enters CI-pending loop; subsequent polls die — pre-fix
          // would throw out of band instead of typed decision_gate.
          if (pollCalls === 1) return PENDING_CI_SNAPSHOT;
          throw new Error("gh poll auth dead");
        },
      },
    });

    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
    expect(result.stopSummary?.summary).toMatch(/poll failed repeatedly/i);
    // initial success + LANDING_CI_FETCH_FAILURE_LIMIT consecutive mid-loop failures
    expect(pollCalls).toBe(1 + LANDING_CI_FETCH_FAILURE_LIMIT);
  });

  it("NEGATIVE Std R2 S1: repeated initial pollSnapshot failures park as decision_gate", async () => {
    let pollCalls = 0;
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
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: "OPEN",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "CLEAN",
        }),
        executeMerge: () => {
          throw new Error("must not merge while poll is dead");
        },
        pollSnapshot: async () => {
          pollCalls += 1;
          throw new Error("gh poll auth dead from the start");
        },
      },
    });

    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.reason).toBe("decision_gate_park");
    expect(result.stopSummary?.summary).toMatch(/poll failed repeatedly/i);
    expect(pollCalls).toBe(LANDING_CI_FETCH_FAILURE_LIMIT);
  });

  it("NEGATIVE R3-G2: mid-loop poll failure fails closed (never merge on stale snapshot)", async () => {
    let pollCalls = 0;
    let mergeCalls = 0;
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
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: "OPEN",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "CLEAN",
        }),
        executeMerge: () => {
          mergeCalls += 1;
        },
        pollSnapshot: async () => {
          pollCalls += 1;
          // Enter CI-pending loop, then fail every subsequent poll. Fail-closed
          // must not keep a prior snapshot and treat it as ready/merge.
          if (pollCalls === 1) return PENDING_CI_SNAPSHOT;
          throw new Error("transient poll blip");
        },
      },
    });

    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.summary).toMatch(/poll failed repeatedly/i);
    expect(mergeCalls).toBe(0);
    expect(pollCalls).toBe(1 + LANDING_CI_FETCH_FAILURE_LIMIT);
  });

  it("NEGATIVE CR-7: MERGED with foreign head parks (no cleanup of wrong merge)", async () => {
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
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: "MERGED",
          headOid: "foreign-pre-docs-head",
          headRefName: "family/epic-941",
          mergeStateStatus: "UNKNOWN",
        }),
        executeMerge: () => {
          throw new Error("must not re-merge on foreign MERGED");
        },
        closeIssue: () => {
          throw new Error("must not close on foreign MERGED");
        },
        deleteBranch: () => {
          throw new Error("must not delete on foreign MERGED");
        },
      },
    });

    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.summary).toMatch(
      /does not match completion head/i,
    );
    expect(backend.ledger.some((e) => e.status === "pr_merged")).toBe(false);
  });

  it("POSITIVE CR-6: durable docs_released skips worker re-dispatch before merge", async () => {
    let landingWorkerCalls = 0;
    const mergeExecuted = { n: 0 };
    const backend = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        landingWorkerCalls += 1;
        return {
          kind: "completed",
          output: { kind: "landing", released: true },
        };
      }
      throw new Error(`unexpected ${spec.kind}`);
    });
    backend.ledger.push(
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: STAGE_SHIP.pr!,
        familyHeadAfter: "head-941",
      },
      {
        status: "docs_released",
        event: "docs_released",
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
      resolvedRoute: smokedRoute(),
      live: liveOpenHooks({ mergeExecuted }),
    });

    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("completed");
    expect(landingWorkerCalls).toBe(0);
    expect(mergeExecuted.n).toBe(1);
    // No second docs_released row on the durable re-entry path.
    expect(
      backend.ledger.filter((e) => e.status === "docs_released"),
    ).toHaveLength(1);
  });

  it("POSITIVE CR-6: HEAD advanced without docs_released infers release and skips re-dispatch", async () => {
    // Crash window: worker pushed (HEAD advanced) but docs_released never written.
    const POST = "head-941-docs";
    let landingWorkerCalls = 0;
    const mergeExecuted = { n: 0 };

    class AdvancedHeadBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [
        {
          status: "review_loop_converged",
          event: "review_loop_converged",
          phase: "final",
          pr: STAGE_SHIP.pr!,
          familyHeadAfter: "head-941",
        },
      ];
      async mergeChildIntoFamilyBase(): Promise<never> {
        throw new Error("n/a");
      }
      async resolveMergeConflict(): Promise<never> {
        throw new Error("n/a");
      }
      async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(entry);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
      async readFamilyHead(): Promise<string> {
        return POST;
      }
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        landingWorkerCalls += 1;
        throw new Error(`must not re-dispatch ${spec.kind}`);
      }
    }

    const backend = new AdvancedHeadBackend();
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
          state: mergeExecuted.n > 0 ? "MERGED" : "OPEN",
          headOid: POST,
          headRefName: "family/epic-941",
          mergeStateStatus: "CLEAN",
        }),
        executeMerge: () => {
          mergeExecuted.n += 1;
        },
        confirmMerged: (expectedHeadOid) => ({
          kind: "aligned" as const,
          record: {
            prUrl: STAGE_SHIP.pr!,
            prNumber: 941,
            remoteBranchName: "family/epic-941",
            mergedHeadOid: expectedHeadOid,
            convergedHeadOid: expectedHeadOid,
          },
        }),
        pollSnapshot: async () => ({
          ...BASE_SNAPSHOT,
          headOid: POST,
          checkRuns: [
            {
              id: 1,
              name: "ci",
              status: "completed",
              conclusion: "success",
              headSha: POST,
            },
          ],
          roundTriggerUsed: {
            headOid: POST,
            triggeredAt: "1970-01-01T00:00:00.000Z",
          },
        }),
        closeIssue: () => {},
        deleteBranch: () => {},
        branchExists: () => false,
        fetchIssueState: () => "CLOSED",
        fetchSubIssues: () => [],
      },
    });

    expect(result.ok).toBe(true);
    expect(landingWorkerCalls).toBe(0);
    expect(mergeExecuted.n).toBe(1);
    expect(
      backend.ledger.some(
        (e) => e.status === "docs_released" && e.familyHeadAfter === POST,
      ),
    ).toBe(true);
  });

  it("POSITIVE R4-CX1: live MERGED confirm retries through propagation lag", async () => {
    let confirmCalls = 0;
    const mergeExecuted = { n: 0 };
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
      live: {
        ...liveOpenHooks({ mergeExecuted }),
        confirmMerged: (expectedHeadOid) => {
          confirmCalls += 1;
          // First attempts lag as OPEN; last attempt within bound confirms.
          if (confirmCalls < LANDING_MERGED_CONFIRM_ATTEMPTS) {
            return { kind: "not_merged" as const };
          }
          return {
            kind: "aligned" as const,
            record: {
              prUrl: STAGE_SHIP.pr!,
              prNumber: 941,
              remoteBranchName: "family/epic-941",
              mergedHeadOid: expectedHeadOid,
              convergedHeadOid: expectedHeadOid,
            },
          };
        },
        // Keep fetchState OPEN so only confirmMerged drives success.
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: "OPEN",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "CLEAN",
        }),
      },
    });

    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("completed");
    expect(confirmCalls).toBe(LANDING_MERGED_CONFIRM_ATTEMPTS);
    expect(mergeExecuted.n).toBe(1);
  });

  it("POSITIVE R5-CX1: confirmed mergeRecord cleanup ignores lag OPEN live", async () => {
    // After confirm/mergeRecord proved MERGED, lag OPEN fetchState must not
    // skip issue close and stamp terminal post_merge_cleanup (resume already_done).
    const closedIssues: number[] = [];
    const mergeExecuted = { n: 0 };
    const backend = new DispatchCapableBackend(async (spec) => {
      if (spec.kind === "landing") {
        return {
          kind: "completed",
          output: { kind: "landing", released: true },
        };
      }
      throw new Error(`unexpected ${spec.kind}`);
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
      live: {
        ...liveOpenHooks({ mergeExecuted, closedIssues }),
        confirmMerged: (expectedHeadOid) => ({
          kind: "aligned" as const,
          record: {
            prUrl: STAGE_SHIP.pr!,
            prNumber: 941,
            remoteBranchName: "family/epic-941",
            mergedHeadOid: expectedHeadOid,
            convergedHeadOid: expectedHeadOid,
          },
        }),
        // Lag OPEN after confirmed MERGED — cleanup must still close issues.
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          state: "OPEN",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "CLEAN",
        }),
      },
    });

    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("completed");
    expect(mergeExecuted.n).toBe(1);
    expect(closedIssues).toContain(9411);
    expect(result.leftovers ?? []).not.toContain("pr_not_merged");
    expect(backend.ledger.some((e) => e.status === "pr_merged")).toBe(true);
    expect(
      backend.ledger.some((e) => e.status === "post_merge_cleanup"),
    ).toBe(true);

    // Terminal cleanup is legitimate only because issues actually closed.
    const resume = await runLandingAction({
      familyBackend: backend,
      familyBase: "family/epic-941",
      convergedHeadOid: "head-941",
      prUrl: STAGE_SHIP.pr!,
      resolvedRoute: smokedRoute(),
      live: {
        fetchState: () => {
          throw new Error("already_done must not re-fetch");
        },
        executeMerge: () => {
          throw new Error("already_done must not re-merge");
        },
        closeIssue: () => {
          throw new Error("already_done must not re-close");
        },
      },
    });
    expect(resume.ok).toBe(true);
    expect(resume.terminalState).toBe("already_done");
  });

  it("NEGATIVE L1: after mid-loop fetch I/O death, refresh live before assess", async () => {
    // I/O death then CI green must not assess stale CLEAN as ready — re-fetch
    // live (now BLOCKED) and park ruleset, never merge.
    let fetchCalls = 0;
    let pollCalls = 0;
    let mergeCalls = 0;
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
      live: {
        fetchState: () => {
          fetchCalls += 1;
          if (fetchCalls === 1) {
            return {
              prNumber: 941,
              prUrl: STAGE_SHIP.pr!,
              state: "OPEN",
              headOid: "head-941",
              headRefName: "family/epic-941",
              mergeStateStatus: "CLEAN",
            };
          }
          if (fetchCalls === 2) {
            // Mid-loop refresh after first ci_pending assess dies once.
            throw new Error("transient gh blip");
          }
          return {
            prNumber: 941,
            prUrl: STAGE_SHIP.pr!,
            state: "OPEN",
            headOid: "head-941",
            headRefName: "family/epic-941",
            mergeStateStatus: "BLOCKED",
          };
        },
        executeMerge: () => {
          mergeCalls += 1;
        },
        pollSnapshot: async () => {
          pollCalls += 1;
          // First poll keeps the CI-pending loop; after I/O death CI is green.
          return pollCalls === 1 ? PENDING_CI_SNAPSHOT : BASE_SNAPSHOT;
        },
        closeIssue: () => {
          throw new Error("must not close when ruleset blocked");
        },
      },
    });

    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.summary).toMatch(/ruleset_blocked/);
    expect(mergeCalls).toBe(0);
    expect(fetchCalls).toBeGreaterThanOrEqual(3);
  });

  it("POSITIVE: lowercase live MERGED is accepted (shared githubFieldEquals)", async () => {
    const mergeExecuted = { n: 0 };
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
      live: {
        fetchState: () => ({
          prNumber: 941,
          prUrl: STAGE_SHIP.pr!,
          // Already merged with non-canonical casing before executeMerge.
          state: "merged",
          headOid: "head-941",
          headRefName: "family/epic-941",
          mergeStateStatus: "UNKNOWN",
        }),
        executeMerge: () => {
          mergeExecuted.n += 1;
        },
        pollSnapshot: async () => BASE_SNAPSHOT,
        closeIssue: () => {},
        deleteBranch: () => {},
        branchExists: () => false,
        fetchIssueState: () => "CLOSED",
        fetchSubIssues: () => [],
      },
    });

    expect(result.ok).toBe(true);
    expect(mergeExecuted.n).toBe(0); // entry path accepted MERGED, no re-merge
    expect(backend.ledger.some((e) => e.status === "pr_merged")).toBe(true);
  });

  it("L2 unit: mergeRecordIfHeadAligned / confirmPrMergedLive keep mismatch distinct", () => {
    const prUrl = "https://github.com/o/r/pull/941";
    const base: PrMergeLiveState = {
      prNumber: 941,
      prUrl,
      state: "OPEN",
      headOid: "head-941",
      headRefName: "family/epic-941",
      mergeStateStatus: "CLEAN",
    };
    expect(mergeRecordIfHeadAligned(base, "head-941")).toEqual({
      kind: "not_merged",
    });
    expect(
      mergeRecordIfHeadAligned(
        { ...base, state: "MERGED", headOid: "foreign-head" },
        "head-941",
      ),
    ).toEqual({ kind: "mismatch", headOid: "foreign-head" });
    const aligned = mergeRecordIfHeadAligned(
      { ...base, state: "MERGED", headOid: "head-941" },
      "head-941",
    );
    expect(aligned.kind).toBe("aligned");
    if (aligned.kind === "aligned") {
      expect(aligned.record.mergedHeadOid).toBe("head-941");
    }

    // Production confirm must not collapse MERGED+foreign into opaque undefined.
    const shMismatch = () =>
      JSON.stringify({
        number: 941,
        url: prUrl,
        state: "MERGED",
        headRefName: "family/epic-941",
        headRefOid: "foreign-head",
        mergeStateStatus: "UNKNOWN",
      });
    expect(confirmPrMergedLive(shMismatch, "o/r", prUrl, "head-941")).toEqual({
      kind: "mismatch",
      headOid: "foreign-head",
    });

    const shOpen = () =>
      JSON.stringify({
        number: 941,
        url: prUrl,
        state: "OPEN",
        headRefName: "family/epic-941",
        headRefOid: "head-941",
        mergeStateStatus: "CLEAN",
      });
    expect(confirmPrMergedLive(shOpen, "o/r", prUrl, "head-941")).toEqual({
      kind: "not_merged",
    });

    const shAligned = () =>
      JSON.stringify({
        number: 941,
        url: prUrl,
        state: "MERGED",
        headRefName: "family/epic-941",
        headRefOid: "head-941",
        mergeStateStatus: "UNKNOWN",
      });
    const confirmed = confirmPrMergedLive(shAligned, "o/r", prUrl, "head-941");
    expect(confirmed.kind).toBe("aligned");
    if (confirmed.kind === "aligned") {
      expect(confirmed.record.mergedHeadOid).toBe("head-941");
    }
  });

});

describe("family/914 CR R1 Std M1 — landing decision-park ledger (one authority)", () => {
  it("classifyLandingActionResult: decision_gate → park; landing_failed → hard_fail", () => {
    const park = classifyLandingActionResult({
      ok: false,
      terminalState: "decision_gate",
      stopSummary: decisionGateParkStopSummary({
        summary: "landing merge blocked: ruleset",
        repairHint: "fix ruleset",
      }),
    });
    expect(park).toEqual({
      kind: "park",
      stopSummary: expect.objectContaining({ reason: "decision_gate_park" }),
    });

    const hard = classifyLandingActionResult({
      ok: false,
      terminalState: "landing_failed",
      stopSummary: {
        reason: "infra_failure",
        summary: "docs worker died",
        repairHint: "retry",
      },
    });
    expect(hard.kind).toBe("hard_fail");

    expect(classifyLandingActionResult({ ok: true, terminalState: "completed" })).toEqual({
      kind: "ok",
    });
  });

  it("recordLandingActionFailure: single durable park/abort writer (no dual-write)", async () => {
    class MemBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      async mergeChildIntoFamilyBase(): Promise<never> {
        throw new Error("n/a");
      }
      async resolveMergeConflict(): Promise<never> {
        throw new Error("n/a");
      }
      async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(entry);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
      async readFamilyHead(): Promise<string> {
        return "head-941";
      }
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async dispatchWorker(): Promise<never> {
        throw new Error("n/a");
      }
    }

    const parkBackend = new MemBackend();
    const parkStop = decisionGateParkStopSummary({
      summary: "landing merge blocked: ruleset",
      repairHint: "fix ruleset",
    });
    const parked = await recordLandingActionFailure(
      parkBackend,
      {
        ok: false,
        terminalState: "decision_gate",
        stopSummary: parkStop,
      },
      { phase: "final", familyHeadAfter: "head-941" },
    );
    expect(parked.kind).toBe("park");
    expect(parkBackend.ledger.map((e) => e.status)).toEqual(["escalated"]);
    expect(parkBackend.ledger.some((e) => e.status === "aborted")).toBe(false);

    const hardBackend = new MemBackend();
    const hard = await recordLandingActionFailure(
      hardBackend,
      {
        ok: false,
        terminalState: "landing_failed",
        stopSummary: {
          reason: "merge_failed",
          summary: "landing worker failed: boom",
          repairHint: "retry",
        },
      },
      { phase: "final", familyHeadAfter: "head-941" },
    );
    expect(hard.kind).toBe("hard_fail");
    expect(hardBackend.ledger.map((e) => e.status)).toEqual(["aborted"]);
    expect(hardBackend.ledger.some((e) => e.status === "escalated")).toBe(false);
  });

  it("ledger honesty: escalated AFTER review_loop_converged is answerable; aborted-only is not", async () => {
    const converged: FamilyLedgerEntry = {
      status: "review_loop_converged",
      event: "review_loop_converged",
      phase: "final",
      pr: "https://github.com/test/repo/pull/941",
      familyHeadAfter: "head-941",
    };
    const parkStop = decisionGateParkStopSummary({
      summary: "landing merge blocked: ruleset",
      repairHint: "fix ruleset",
    });

    // Fresh-path defect shape (pre-fix): aborted after converged → hidden.
    const abortedOnly: FamilyLedgerEntry[] = [
      converged,
      {
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: parkStop.summary,
        familyHeadAfter: "head-941",
        stopSummary: parkStop,
      },
    ];
    expect(familyEscalationState(abortedOnly)).toBeUndefined();

    // Unified durable shape: escalated decision after converged → answerable.
    class MemBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [converged];
      async mergeChildIntoFamilyBase(): Promise<never> {
        throw new Error("n/a");
      }
      async resolveMergeConflict(): Promise<never> {
        throw new Error("n/a");
      }
      async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(entry);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
      async readFamilyHead(): Promise<string> {
        return "head-941";
      }
      async runFamilyVerify(): Promise<FamilyVerifyResult> {
        return { ok: true };
      }
      async dispatchWorker(): Promise<never> {
        throw new Error("n/a");
      }
    }
    const backend = new MemBackend();
    await recordFamilyEscalated(backend, {
      escalationKind: "decision",
      phase: "final",
      reason: parkStop.summary,
      familyHeadAfter: "head-941",
      stopSummary: parkStop,
    });
    expect(familyEscalationState(backend.ledger)).toMatchObject({
      escalation: {
        status: "escalated",
        event: "escalated",
        escalationKind: "decision",
      },
    });
  });

  it("POSITIVE: runFamily resume landing decision_gate writes escalated (not aborted-only)", async () => {
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

    class ParkFamilyBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      head = "family-base-941";
      resolveLandingLiveHooks() {
        return {
          fetchState: () => ({
            prNumber: 941,
            prUrl: "https://github.com/test/repo/pull/941",
            state: "OPEN",
            headOid: "family-base-941",
            headRefName: "family/epic-941",
            mergeStateStatus: "BLOCKED",
          }),
          executeMerge: () => {
            throw new Error("must not merge when ruleset blocked");
          },
          pollSnapshot: async () => BASE_SNAPSHOT,
        };
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
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.kind === "landing") {
          return {
            kind: "completed",
            output: { kind: "landing", released: true },
          };
        }
        throw new Error(`unexpected ${spec.kind}`);
      }
    }

    const familyBackend = new ParkFamilyBackend();
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
        pr: "https://github.com/test/repo/pull/941",
        familyHeadAfter: "family-base-941",
      },
    );

    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic: {
        issue: 941,
        children: [{ issue: 9411, blockedBy: [] }],
      },
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/epic-941",
    });

    expect(result.status).toBe("parked");
    expect(result.stopSummary.reason).toBe("decision_gate_park");
    const escalated = familyBackend.ledger.filter(
      (e) => e.status === "escalated" && e.event === "escalated",
    );
    expect(escalated).toHaveLength(1);
    expect(escalated[0]).toMatchObject({
      escalationKind: "decision",
      phase: "final",
    });
    // Must not leave only an aborted park that familyEscalationState cannot see.
    expect(familyEscalationState(familyBackend.ledger)).toMatchObject({
      escalation: { escalationKind: "decision" },
    });
  });

  it("POSITIVE: runVerifyCmr fresh final-barrier landing decision_gate writes escalated (not aborted-only)", async () => {
    // Mirror resume POSITIVE, but through the live fresh author: final barrier
    // records review_loop_converged then runLandingAction parks → must durable
    // recordFamilyEscalated(decision), not aborted-only.
    class FreshParkFamilyBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      head = "family-base-941";
      resolveLandingLiveHooks() {
        return {
          fetchState: () => ({
            prNumber: 941,
            prUrl: "https://github.com/test/repo/pull/941",
            state: "OPEN",
            headOid: "family-base-941",
            headRefName: "family/epic-941",
            mergeStateStatus: "BLOCKED",
          }),
          executeMerge: () => {
            throw new Error("must not merge when ruleset blocked");
          },
          pollSnapshot: async () => BASE_SNAPSHOT,
        };
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
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        const panelLeg = completeReviewPanelLegWorker(spec);
        if (panelLeg !== undefined) return panelLeg;
        if (spec.kind === "cmr") {
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
          };
        }
        if (spec.kind === "ship") {
          return {
            kind: "completed",
            output: {
              kind: "ship",
              branch: "family/epic-941",
              status: "pr_opened",
              pr: "https://github.com/test/repo/pull/941",
              prHead: this.head,
            },
          };
        }
        if (spec.kind === "landing") {
          return {
            kind: "completed",
            output: { kind: "landing", released: true },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        throw new Error(`unexpected ${spec.kind}`);
      }
    }

    const familyBackend = new FreshParkFamilyBackend();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/epic-941",
      familyBackend,
      familyHeadAfter: "family-base-941",
    });

    // Decision park: ok:false without stage-named failedStatus.
    expect(result).toMatchObject({ ok: false, ran: true });
    expect(result.failedStatus).toBeUndefined();

    // Fresh path itself authored review_loop_converged (not pre-seeded).
    expect(
      familyBackend.ledger.some(
        (e) =>
          e.status === "review_loop_converged" &&
          e.event === "review_loop_converged",
      ),
    ).toBe(true);

    const escalated = familyBackend.ledger.filter(
      (e) => e.status === "escalated" && e.event === "escalated",
    );
    expect(escalated).toHaveLength(1);
    expect(escalated[0]).toMatchObject({
      escalationKind: "decision",
      phase: "final",
    });
    // Must not leave only an aborted park that familyEscalationState cannot see.
    const abortedParks = familyBackend.ledger.filter(
      (e) =>
        e.status === "aborted" &&
        e.stopSummary?.reason === "decision_gate_park",
    );
    expect(abortedParks).toHaveLength(0);
    expect(familyEscalationState(familyBackend.ledger)).toMatchObject({
      escalation: { escalationKind: "decision" },
    });
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
    // CR-17: pin exact already-gone classification (not a hollow non-fail predicate).
    expect(leftovers).toContain("branch_already_gone");
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
  // N1: hollow terminateSpawnedChild typeof pin deleted — real ID-006 proof is
  // monitored-dispatch ownership elsewhere, not a second export smoke here.

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
        pr: "https://github.com/test/repo/pull/941",
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

    expect(result.status).toBe("completed");
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
        pr: "https://github.com/test/repo/pull/941",
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
    expect(result.status).toBe("parked");
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
