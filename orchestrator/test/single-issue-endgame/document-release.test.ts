/**
 * #735 — real S12 docRelease worker + ADR 0123 (no path-allowlist merge veto).
 *
 * Public seams:
 *   - auto-merge: released + live readiness; not path allowlist
 *   - dispatch: live docRelease not unconditional stub; offline hatch only
 *   - resume/order: S12 fail re-enters; success → merge → cleanup
 */
import { describe, expect, it, vi } from "vitest";
import type { Sh } from "../../src/familyDriver.js";
import {
  runAutoMergeStage,
} from "../../src/autoMerge.js";
import type { PrReviewSnapshot } from "../../src/botPolling.js";
import {
  dispatchWorker,
  docReleaseWorkerSpec,
  legacyDispatchWorker,
} from "../../src/dispatchWorker.js";
import { offlineReviewLoopDispatchAdmissible } from "../../src/evidenceAdmissibility.js";
import {
  legacyDispatchFamilyWorker,
} from "../../src/family/dispatchFamilyWorker.js";
import { resolveRouteModels, routeSmokeEntries } from "../../src/modelRoutes.js";
import type { FamilyBackend } from "../../src/family/types.js";
import type {
  Backend,
  DispatchContext,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
} from "../../src/types.js";

const REPO = "Akagilnc/ming-salvage-sim";
const LIVE_PR = "https://github.com/Akagilnc/ming-salvage-sim/pull/735";
const OFFLINE_PR = "pr://slice/735-offline";
const SMOKED_ROUTE = resolveRouteModels(
  "normal",
  {},
  {},
  Object.fromEntries(
    routeSmokeEntries(resolveRouteModels("normal", {})).map((entry) => [
      entry.key,
      { state: "passed", at: new Date().toISOString(), cliVersion: "test" },
    ]),
  ),
);

function readySnapshot(overrides?: Partial<PrReviewSnapshot>): PrReviewSnapshot {
  return {
    repo: REPO,
    prNumber: 735,
    prUrl: LIVE_PR,
    headOid: "head-735",
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
        headSha: "head-735",
        status: "completed",
        conclusion: "success",
      },
    ],
    totalFindingCount: 0,
    quiescent: true,
    roundTriggerUsed: { headOid: "head-735", triggeredAt: "2026-07-09T00:00:00.000Z" },
    checkRunsEmptyMeans: "pending",
    ...overrides,
  };
}

function fakeSh(
  handlers: Record<string, (args: string[]) => string>,
): Sh {
  return (file, args) => {
    const key = `${file} ${args.join(" ")}`;
    for (const [pattern, fn] of Object.entries(handlers)) {
      if (key.includes(pattern)) {
        return fn(args);
      }
    }
    throw new Error(`unexpected sh call: ${key}`);
  };
}

const worktree: WorktreeHandle = {
  branch: "feat/735-doc-release-real",
  base: "main",
  path: "/resident/worktrees/issue-735",
};

// ─── ADR 0123: auto-merge no longer path-allowlist gated ─────────────────────

describe("#735 ADR 0123 auto-merge: no path-allowlist veto", () => {
  it("admits merge when released + readiness green even if paths include README/CLAUDE/TODOS", async () => {
    let merged = false;
    const merge = vi.fn(() => {
      merged = true;
    });
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 735,
            url: LIVE_PR,
            state: merged ? "MERGED" : "OPEN",
            headRefName: "feat/735-doc-release-real",
            headRefOid: "head-735",
            mergeStateStatus: merged ? "UNKNOWN" : "CLEAN",
          }),
      }),
      repo: REPO,
      prUrl: LIVE_PR,
      convergedHeadOid: "head-735",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      // Legitimate gstack-document-release surface (ADR 0123) — previously vetoed.
      docReleasePaths: ["README.md", "CLAUDE.md", "TODOS.md", "docs/adr/0123.md"],
      poll: async () => readySnapshot(),
      executeMerge: merge,
      mergeConfirmRetryDelayMs: 0,
    });
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("merged");
    expect(merge).toHaveBeenCalled();
  });

  it("admits merge when docReleasePaths is missing (empty-run tip; no path gate)", async () => {
    let merged = false;
    const merge = vi.fn(() => {
      merged = true;
    });
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 735,
            url: LIVE_PR,
            state: merged ? "MERGED" : "OPEN",
            headRefName: "feat/735-doc-release-real",
            headRefOid: "head-735",
            mergeStateStatus: merged ? "UNKNOWN" : "CLEAN",
          }),
      }),
      repo: REPO,
      prUrl: LIVE_PR,
      convergedHeadOid: "head-735",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      // No paths (empty-run / unverified) — ADR 0123: not a veto.
      poll: async () => readySnapshot(),
      executeMerge: merge,
      mergeConfirmRetryDelayMs: 0,
    });
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("merged");
    expect(merge).toHaveBeenCalled();
  });

  it("still blocks when docRelease has not completed", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({}),
      repo: REPO,
      prUrl: LIVE_PR,
      convergedHeadOid: "head-735",
      docReleaseCompleted: false,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["README.md"],
      poll: async () => readySnapshot(),
      executeMerge: merge,
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("not_ready");
    expect(result.stopSummary?.summary).toMatch(/doc-release/i);
    expect(merge).not.toHaveBeenCalled();
  });

  it("still blocks on live readiness failure (threads) after released", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 735,
            url: LIVE_PR,
            state: "OPEN",
            headRefName: "feat/735-doc-release-real",
            headRefOid: "head-735",
            mergeStateStatus: "CLEAN",
          }),
      }),
      repo: REPO,
      prUrl: LIVE_PR,
      convergedHeadOid: "head-735",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["README.md"],
      poll: async () =>
        readySnapshot({
          threads: [
            {
              id: "T1",
              threadNodeId: "PRRT_docrelease_open",
              isResolved: false,
              authorLogin: "coderabbitai",
              body: "still open",
            },
          ],
          totalFindingCount: 1,
          quiescent: false,
        }),
      executeMerge: merge,
    });
    expect(result.ok).toBe(false);
    expect(merge).not.toHaveBeenCalled();
  });
});

// ─── Dispatch: live path not unconditional stub ──────────────────────────────

describe("#735 docRelease dispatch: live not unconditional stub; offline hatch", () => {
  it("docReleaseWorkerSpec invokes /gstack-document-release (not /doc-release placeholder)", () => {
    const spec = docReleaseWorkerSpec();
    expect(spec.kind).toBe("docRelease");
    expect(spec.skill).toBe("/gstack-document-release");
    expect(spec.promptFile).toBe("docRelease.md");
    expect(spec.completionSignal).toBe("DOCRELEASE_STEP_COMPLETE");
  });

  it("legacy live path with no dispatchWorker seam fails closed (no silent forever-stub)", async () => {
    const runStep = vi.fn(async (): Promise<StepOutput> => {
      throw new Error("runStep must not be reached when skeleton is the only path");
    });
    const backend = {
      async runStep(...args: unknown[]): Promise<StepOutput> {
        void args;
        return runStep();
      },
      async resumeSession(): Promise<StepOutput> {
        throw new Error("resumeSession unexpected");
      },
    } as unknown as Backend;

    const result = await legacyDispatchWorker(
      backend,
      docReleaseWorkerSpec(),
      {
        worktree,
        prUrl: LIVE_PR,
        repo: REPO,
      },
    );
    expect(result.kind).toBe("failed");
    if (result.kind === "failed") {
      expect(result.reason).toMatch(/inadmissible|unavailable/i);
    }
  });

  it("legacy offline hatch still admits skeleton released:true for pr:// test handles", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      const ctx: DispatchContext = {
        worktree,
        prUrl: OFFLINE_PR,
        repo: REPO,
      };
      expect(offlineReviewLoopDispatchAdmissible(ctx)).toBe(true);

      const backend = {
        // No dispatchWorker — forces offline skeleton path for review-loop kinds.
        async runStep(): Promise<StepOutput> {
          throw new Error("runStep must not run under offline skeleton hatch");
        },
      } as unknown as Backend;

      const result = await legacyDispatchWorker(
        backend,
        docReleaseWorkerSpec(),
        ctx,
      );
      expect(result).toEqual({
        kind: "completed",
        output: { kind: "docRelease", released: true },
      });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });

  it("when backend implements dispatchWorker, live docRelease is not short-circuited to stub by free function", async () => {
    const observed: WorkerSpec[] = [];
    const backend: Backend = {
      async smokeModelRoute(route) {
        return route;
      },
      async findResumeState() {
        return undefined;
      },
      async cleanResidue() {},
      async resumeSession(): Promise<StepOutput> {
        throw new Error("unexpected resumeSession");
      },
      async fetchIssueMeta() {
        return {
          number: 735,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      },
      async fetchIssueSnapshot() {
        return {
          number: 735,
          body: "body",
          comments: [],
          agentBrief: "brief",
        };
      },
      async prepareWorktree() {
        return worktree;
      },
      async writeSnapshot() {},
      async runStep(): Promise<StepOutput> {
        throw new Error("runStep should not be called when dispatchWorker handles docRelease");
      },
      async push() {},
      async writeLedger() {},
      async dispatchWorker(
        spec: WorkerSpec,
        _ctx: DispatchContext,
      ): Promise<WorkerResult> {
        observed.push(spec);
        // Simulate real worker success (including empty-run).
        return {
          kind: "completed",
          output: { kind: "docRelease", released: true },
        };
      },
    };

    const result = await dispatchWorker(
      backend,
      docReleaseWorkerSpec(),
      { worktree, modelRoute: SMOKED_ROUTE, prUrl: LIVE_PR, repo: REPO },
    );
    expect(observed).toHaveLength(1);
    expect(observed[0]!.kind).toBe("docRelease");
    expect(observed[0]!.skill).toBe("/gstack-document-release");
    expect(result).toEqual({
      kind: "completed",
      output: { kind: "docRelease", released: true },
    });
  });

  it("live dispatchWorker path can report released:false (skill/push failure) without silent green", async () => {
    const backend = {
      async dispatchWorker(): Promise<WorkerResult> {
        return {
          kind: "completed",
          output: { kind: "docRelease", released: false },
        };
      },
    } as unknown as Backend;

    const result = await dispatchWorker(
      backend as Backend,
      docReleaseWorkerSpec(),
      { worktree, modelRoute: SMOKED_ROUTE, prUrl: LIVE_PR, repo: REPO },
    );
    expect(result.kind).toBe("completed");
    if (result.kind === "completed") {
      expect(result.output).toEqual({ kind: "docRelease", released: false });
    }
  });

  it("live dispatchWorker path surfaces failed worker (crash) as non-completed", async () => {
    const backend = {
      async dispatchWorker(): Promise<WorkerResult> {
        return {
          kind: "failed",
          reason: "docRelease worker crashed: skill hang / non-interactive block",
        };
      },
    } as unknown as Backend;

    const result = await dispatchWorker(
      backend as Backend,
      docReleaseWorkerSpec(),
      { worktree, modelRoute: SMOKED_ROUTE, prUrl: LIVE_PR, repo: REPO },
    );
    expect(result.kind).toBe("failed");
  });

  it("family legacy live path fails closed for docRelease (no silent forever-stub)", async () => {
    const familyBackend = {} as FamilyBackend;
    const result = await legacyDispatchFamilyWorker(
      familyBackend,
      docReleaseWorkerSpec(),
      { familyBase: "family/735-base", prUrl: LIVE_PR, repo: REPO },
    );
    expect(result.kind).toBe("failed");
    if (result.kind === "failed") {
      expect(result.reason).toMatch(/inadmissible|unavailable/i);
    }
  });

  it("family legacy offline hatch still admits skeleton for pr://", async () => {
    const prev = process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
    process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = "1";
    try {
      const familyBackend = {} as FamilyBackend;
      const result = await legacyDispatchFamilyWorker(
        familyBackend,
        docReleaseWorkerSpec(),
        { familyBase: "family/735-base", prUrl: OFFLINE_PR, repo: REPO },
      );
      expect(result).toEqual({
        kind: "completed",
        output: { kind: "docRelease", released: true },
      });
    } finally {
      if (prev === undefined) {
        delete process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL;
      } else {
        process.env.ORCHESTRATOR_OFFLINE_REVIEW_POLL = prev;
      }
    }
  });
});
