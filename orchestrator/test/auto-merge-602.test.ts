/**
 * #602 — host-side auto-merge after online review + doc-release converges.
 */
import { describe, expect, it, vi } from "vitest";
import type { Sh } from "../src/familyDriver.js";
import {
  assessMergeReadiness,
  confirmPrMergedLive,
  executePrMergeCommit,
  fetchPrMergeLiveState,
  isDocOnlyFileList,
  isPrMergedMarker,
  mergeReadinessStopSummary,
  runAutoMergeStage,
  tryResumePrMergedBackfill,
} from "../src/autoMerge.js";
import type { PrReviewSnapshot } from "../src/botPolling.js";
import { docReleaseWorkerSpec } from "../src/dispatchWorker.js";
import { RealBackend, SPAWNED_WORKER_ENV } from "../src/realBackend.js";
import { stepSpecToWorkerSpec } from "../src/dispatchWorker.js";

const REPO = "Akagilnc/ming-salvage-sim";
const PR_URL = "https://github.com/Akagilnc/ming-salvage-sim/pull/602";

function readySnapshot(overrides?: Partial<PrReviewSnapshot>): PrReviewSnapshot {
  return {
    repo: REPO,
    prNumber: 602,
    prUrl: "https://github.com/Akagilnc/ming-salvage-sim/pull/602",
    headOid: "head-ready",
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
        headSha: "head-ready",
        status: "completed",
        conclusion: "success",
      },
    ],
    totalFindingCount: 0,
    quiescent: true,
    roundTriggerUsed: { headOid: "head-ready", triggeredAt: "2026-07-09T00:00:00.000Z" },
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

describe("#602 isDocOnlyFileList", () => {
  it("accepts VERSION/CHANGELOG/docs-only doc-release diffs", () => {
    expect(
      isDocOnlyFileList(["VERSION", "CHANGELOG.md", "docs/adr/0061.md"]),
    ).toBe(true);
    expect(isDocOnlyFileList(["orchestrator/CHANGELOG.md"])).toBe(true);
  });

  it("rejects non-doc paths fail-closed", () => {
    expect(isDocOnlyFileList(["orchestrator/src/runner.ts"])).toBe(false);
    expect(isDocOnlyFileList(["VERSION", "ming_sim/db.py"])).toBe(false);
  });
});

describe("#602 fetchPrMergeLiveState + assessMergeReadiness", () => {
  it("queries live mergeStateStatus/head directly — never a cache", () => {
    const calls: string[] = [];
    const sh = fakeSh({
      "gh pr view": (args) => {
        calls.push(args.join(" "));
        return JSON.stringify({
          number: 602,
          url: "https://github.com/Akagilnc/ming-salvage-sim/pull/602",
          state: "OPEN",
          headRefName: "feat/issue-602-auto-merge",
          headRefOid: "abc123",
          mergeStateStatus: "CLEAN",
          mergeable: "MERGEABLE",
        });
      },
    });
    const live = fetchPrMergeLiveState(sh, REPO, "https://github.com/Akagilnc/ming-salvage-sim/pull/602");
    expect(live).toEqual({
      prNumber: 602,
      prUrl: "https://github.com/Akagilnc/ming-salvage-sim/pull/602",
      state: "OPEN",
      headOid: "abc123",
      headRefName: "feat/issue-602-auto-merge",
      mergeStateStatus: "CLEAN",
      mergeable: "MERGEABLE",
    });
    expect(calls[0]).toContain("mergeStateStatus");
  });

  it("all objective gates green → ready", () => {
    const readiness = assessMergeReadiness(
      {
        prNumber: 602,
        prUrl: PR_URL,
        state: "OPEN",
        headOid: "head-ready",
        headRefName: "feat/x",
        mergeStateStatus: "CLEAN",
      },
      readySnapshot(),
    );
    expect(readiness.ready).toBe(true);
    expect(readiness.blockers).toEqual([]);
  });

  it("unresolved threads block merge without pretending merged", () => {
    const readiness = assessMergeReadiness(
      {
        prNumber: 602,
        prUrl: PR_URL,
        state: "OPEN",
        headOid: "head-ready",
        headRefName: "feat/x",
        mergeStateStatus: "CLEAN",
      },
      readySnapshot({
        threads: [
          {
            id: "1",
            threadNodeId: "T1",
            body: "nit",
            authorLogin: "bot",
            isResolved: false,
          },
        ],
      }),
    );
    expect(readiness.ready).toBe(false);
    expect(readiness.blockers).toContain("threads_unresolved");
  });

  it("ruleset/mergeStateStatus not CLEAN blocks merge", () => {
    const readiness = assessMergeReadiness(
      {
        prNumber: 602,
        prUrl: PR_URL,
        state: "OPEN",
        headOid: "head-ready",
        headRefName: "feat/x",
        mergeStateStatus: "BLOCKED",
      },
      readySnapshot(),
    );
    expect(readiness.ready).toBe(false);
    expect(readiness.blockers).toContain("ruleset_blocked");
  });

  it("pending post-doc-release CI blocks merge (waits for green)", () => {
    const readiness = assessMergeReadiness(
      {
        prNumber: 602,
        prUrl: PR_URL,
        state: "OPEN",
        headOid: "head-after-doc",
        headRefName: "feat/x",
        mergeStateStatus: "CLEAN",
      },
      readySnapshot({
        headOid: "head-after-doc",
        checkRuns: [
          {
            id: 1,
            name: "ci",
            headSha: "head-after-doc",
            status: "in_progress",
          },
        ],
      }),
    );
    expect(readiness.ready).toBe(false);
    expect(readiness.blockers).toContain("ci_pending");
  });
});

describe("#602 executePrMergeCommit + confirmPrMergedLive", () => {
  it("uses merge commit (not squash) and confirms via live MERGED state", () => {
    const mergeCalls: string[][] = [];
    let merged = false;
    const sh = fakeSh({
      "gh pr merge": (args) => {
        mergeCalls.push(args);
        merged = true;
        return "";
      },
      "gh pr view": () =>
        JSON.stringify({
          number: 602,
          url: PR_URL,
          state: merged ? "MERGED" : "OPEN",
          headRefName: "feat/issue-602-auto-merge",
          headRefOid: "merged-head-1",
          mergeStateStatus: merged ? "UNKNOWN" : "CLEAN",
        }),
    });
    executePrMergeCommit(sh, REPO, 602);
    expect(mergeCalls[0]).toEqual([
      "pr",
      "merge",
      "602",
      "--merge",
      "--repo",
      REPO,
    ]);
    expect(mergeCalls[0]).not.toContain("--squash");
    const confirmed = confirmPrMergedLive(sh, REPO, PR_URL, "merged-head-1");
    expect(confirmed).toEqual({
      prUrl: "https://github.com/Akagilnc/ming-salvage-sim/pull/602",
      prNumber: 602,
      remoteBranchName: "feat/issue-602-auto-merge",
      mergedHeadOid: "merged-head-1",
      convergedHeadOid: "merged-head-1",
    });
  });
});

describe("#602 runAutoMergeStage", () => {
  it("waits for doc-release before merge", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({}),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "head-1",
      docReleaseCompleted: false,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      poll: async () => readySnapshot(),
      executeMerge: merge,
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("not_ready");
    expect(merge).not.toHaveBeenCalled();
  });

  it("happy path: all gates green → merge commit + terminal record", async () => {
    let merged = false;
    const sh = fakeSh({
      "gh pr view": () =>
        JSON.stringify({
          number: 602,
          url: "https://github.com/Akagilnc/ming-salvage-sim/pull/602",
          state: merged ? "MERGED" : "OPEN",
          headRefName: "feat/issue-602-auto-merge",
          headRefOid: "merged-head-1",
          mergeStateStatus: merged ? "UNKNOWN" : "CLEAN",
        }),
      "gh pr merge": () => {
        merged = true;
        return "";
      },
    });
    const result = await runAutoMergeStage({
      sh,
      repo: REPO,
      prUrl: "https://github.com/Akagilnc/ming-salvage-sim/pull/602",
      convergedHeadOid: "merged-head-1",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      poll: async () => readySnapshot({ headOid: "merged-head-1" }),
    });
    expect(result).toMatchObject({
      ok: true,
      terminalState: "merged",
      record: {
        prNumber: 602,
        remoteBranchName: "feat/issue-602-auto-merge",
        mergedHeadOid: "merged-head-1",
      },
    });
  });

  it("non-doc doc-release diff fails closed to decision gate", async () => {
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "OPEN",
            headRefName: "feat/x",
            headRefOid: "head-1",
            mergeStateStatus: "CLEAN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "head-1",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      docReleasePaths: ["VERSION", "orchestrator/src/runner.ts"],
      poll: async () => readySnapshot(),
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.summary).toMatch(/non-doc/i);
  });

  it("MERGED PR without convergence record → externally merged never converged", async () => {
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/x",
            headRefOid: "merged-head",
            mergeStateStatus: "UNKNOWN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "merged-head",
      docReleaseCompleted: true,
      priorConvergenceRecorded: false,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      poll: async () => readySnapshot(),
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("externally_merged_never_converged");
  });

  it("resume backfill: live MERGED + convergence record → terminal marker without re-merge", async () => {
    const merge = vi.fn();
    const result = await tryResumePrMergedBackfill({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/x",
            headRefOid: "merged-head",
            mergeStateStatus: "UNKNOWN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "merged-head",
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      executeMerge: merge,
    });
    expect(merge).not.toHaveBeenCalled();
    expect(result?.terminalState).toBe("merged");
    expect(result?.record?.mergedHeadOid).toBe("merged-head");
  });
});

describe("#602 isPrMergedMarker", () => {
  it("matches durable pr_merged marker for #603 cleanup precondition", () => {
    const entry = {
      event: "pr_merged" as const,
      prUrl: PR_URL,
      prNumber: 602,
      remoteBranchName: "feat/x",
      mergedHeadOid: "merged-head",
      prHead: "pre-merge-head",
    };
    expect(isPrMergedMarker(entry, "pre-merge-head")).toBe(true);
    expect(isPrMergedMarker(entry, "other-head")).toBe(false);
  });
});

describe("#602 docRelease non-interactive dispatch env", () => {
  it("docRelease worker inherits spawned-session env (no human prompt)", () => {
    class StubBackend extends RealBackend {
      protected override cloneDirExists(): boolean {
        return true;
      }
      protected override sh(file: string, args: string[]): string {
        if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
          return ".git";
        }
        return "";
      }
      public workerEnv(): Record<string, string> {
        const spec = stepSpecToWorkerSpec(docReleaseWorkerSpec());
        return this.boxConfig({ authDir: "/tmp/auth-602" }, spec, 602).env;
      }
    }
    const env = new StubBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/Akagilnc/ming-salvage-sim.git",
      runKey: 602,
      repo: REPO,
      promptsDir: "/Users/akagilnc/WorkSpace/Ming_LLM-bench-602/orchestrator/prompts",
      soulsDir: "/Users/akagilnc/WorkSpace/Ming_LLM-bench-602/orchestrator/image/souls",
    }).workerEnv();
    expect(env.OPENCLAW_SESSION).toBe(SPAWNED_WORKER_ENV.OPENCLAW_SESSION);
  });
});

describe("#602 mergeReadinessStopSummary", () => {
  it("surfaces blocker reasons for human decision gate", () => {
    const summary = mergeReadinessStopSummary(["ci_pending", "threads_unresolved"]);
    expect(summary.reason).toBe("decision_gate_park");
    expect(summary.summary).toMatch(/ci_pending/);
    expect(summary.summary).toMatch(/threads_unresolved/);
  });
});
