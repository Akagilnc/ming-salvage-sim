/**
 * #602 — host-side auto-merge after online review + doc-release converges.
 */
import { describe, expect, it, vi } from "vitest";
import type { Sh } from "../src/familyDriver.js";
import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
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
  prMergedRecordFromLive,
  docReleasePathsFromCommit,
} from "../src/autoMerge.js";
import type { PrReviewSnapshot } from "../src/botPolling.js";
import {
  familyAutoMergeIncomplete,
  runFamilyAutoMergeStage,
} from "../src/family/familyAutoMerge.js";
import { familyPrMergedForHead } from "../src/family/ledger.js";
import type { FamilyBackend, FamilyLedgerEntry } from "../src/family/types.js";

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

  it("rejects spoofed VERSION/CHANGELOG prefixes and docs/.. traversal", () => {
    expect(isDocOnlyFileList(["VERSION.evil.ts"])).toBe(false);
    expect(isDocOnlyFileList(["CHANGELOG.md.evil"])).toBe(false);
    expect(isDocOnlyFileList(["docs/../orchestrator/src/runner.ts"])).toBe(false);
    expect(isDocOnlyFileList(["docs/"])).toBe(false);
  });
});

describe("#602 docReleasePathsFromCommit", () => {
  it("reads paths from a specific commit OID (not just worktree HEAD)", () => {
    const dir = mkdtempSync(join(tmpdir(), "doc-release-commit-"));
    const git = (args: string[]) =>
      execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });
    git(["init"]);
    git(["config", "user.email", "t@example.com"]);
    git(["config", "user.name", "t"]);
    writeFileSync(join(dir, "VERSION"), "1.0.0\n");
    git(["add", "."]);
    git(["commit", "-m", "doc-release"]);
    const docReleaseOid = git(["rev-parse", "HEAD"]).trim();
    writeFileSync(join(dir, "bad.ts"), "x\n");
    git(["add", "."]);
    git(["commit", "-m", "later"]);

    expect(docReleasePathsFromCommit(dir, docReleaseOid)).toEqual(["VERSION"]);
    expect(docReleasePathsFromCommit(dir, git(["rev-parse", "HEAD"]).trim())).toEqual([
      "bad.ts",
    ]);
  });
});

describe("#602 runFamilyAutoMergeStage", () => {
  class MinimalFamilyBackend implements FamilyBackend {
  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

    readonly ledger: FamilyLedgerEntry[] = [];
    readonly workingRepo: string;
    constructor(workingRepo?: string) {
      this.workingRepo = workingRepo ?? (() => {
        const dir = mkdtempSync(join(tmpdir(), "family-offline-doc-"));
        const git = (args: string[]) =>
          execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });
        git(["init"]);
        git(["config", "user.email", "t@example.com"]);
        git(["config", "user.name", "t"]);
        writeFileSync(join(dir, "VERSION"), "1.0.0\n");
        git(["add", "."]);
        git(["commit", "-m", "doc-release"]);
        return dir;
      })();
    }
    async mergeChildIntoFamilyBase(): Promise<{ familyHead: string }> {
      return { familyHead: "head" };
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
    resolveFamilyWorkingRepo(): string | undefined {
      return this.workingRepo;
    }
  }

  it("records pr_merged on offline happy path", async () => {
    const backend = new MinimalFamilyBackend();
    const result = await runFamilyAutoMergeStage({
      familyBackend: backend,
      familyBase: "family/base",
      convergedHeadOid: "head-ready",
      prUrl: "pr://family/offline-602",
    });
    expect(familyAutoMergeIncomplete(result)).toBe(false);
    expect(backend.ledger.filter((e) => e.status === "pr_merged")).toHaveLength(1);
    expect(backend.ledger[0]).toMatchObject({
      event: "pr_merged",
      pr: "pr://family/offline-602",
      familyHeadAfter: "head-ready",
    });
  });

  it("already_recorded when pr_merged marker exists", async () => {
    const backend = new MinimalFamilyBackend();
    backend.ledger.push({
      status: "pr_merged",
      event: "pr_merged",
      phase: "final",
      pr: "pr://family/offline-602",
      prNumber: 602,
      remoteBranchName: "feat/x",
      mergedHeadOid: "head-ready",
      familyHeadAfter: "head-ready",
    });
    const result = await runFamilyAutoMergeStage({
      familyBackend: backend,
      familyBase: "family/base",
      convergedHeadOid: "head-ready",
      prUrl: "pr://family/offline-602",
    });
    expect(result.terminalState).toBe("already_recorded");
    expect(familyAutoMergeIncomplete(result)).toBe(false);
    expect(backend.ledger.filter((e) => e.status === "pr_merged")).toHaveLength(1);
  });

  it("uses family repo HEAD for doc-release paths, not stale convergedHeadOid", async () => {
    const dir = mkdtempSync(join(tmpdir(), "family-doc-head-"));
    const git = (args: string[]) =>
      execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });
    git(["init"]);
    git(["config", "user.email", "t@example.com"]);
    git(["config", "user.name", "t"]);
    writeFileSync(join(dir, "orchestrator-src.ts"), "x\n");
    git(["add", "."]);
    git(["commit", "-m", "converged"]);
    const convergedOid = git(["rev-parse", "HEAD"]).trim();
    writeFileSync(join(dir, "VERSION"), "1.0.0\n");
    git(["add", "."]);
    git(["commit", "-m", "doc-release"]);

    const backend = new MinimalFamilyBackend(dir);
    const result = await runFamilyAutoMergeStage({
      familyBackend: backend,
      familyBase: "family/base",
      convergedHeadOid: convergedOid,
      prUrl: "pr://family/offline-602",
    });
    expect(familyAutoMergeIncomplete(result)).toBe(false);
    expect(backend.ledger.filter((e) => e.status === "pr_merged")).toHaveLength(1);
  });

  it("ADR 0123 / #735: non-doc paths no longer veto family auto-merge when released+ready", async () => {
    const dir = mkdtempSync(join(tmpdir(), "family-non-doc-"));
    const git = (args: string[]) =>
      execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });
    git(["init"]);
    git(["config", "user.email", "t@example.com"]);
    git(["config", "user.name", "t"]);
    writeFileSync(join(dir, "orchestrator-src.ts"), "x\n");
    git(["add", "."]);
    git(["commit", "-m", "non-doc release"]);
    const headOid = git(["rev-parse", "HEAD"]).trim();
    expect(docReleasePathsFromCommit(dir, headOid)).toEqual(["orchestrator-src.ts"]);

    const backend = new MinimalFamilyBackend(dir);
    const result = await runFamilyAutoMergeStage({
      familyBackend: backend,
      familyBase: "family/base",
      convergedHeadOid: headOid,
      prUrl: "pr://family/offline-602",
    });
    // Path allowlist is not a merge gate (ADR 0123). Offline synthetic still merges
    // when docReleaseCompleted + readiness hold.
    expect(result.ok).toBe(true);
    expect(familyAutoMergeIncomplete(result)).toBe(false);
    expect(backend.ledger.filter((e) => e.status === "pr_merged")).toHaveLength(1);
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
          headRepositoryOwner: { login: "Akagilnc" },
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
      headRepositoryOwnerLogin: "Akagilnc",
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

  it("accepts lowercase live state and merge status", () => {
    const readiness = assessMergeReadiness(
      {
        prNumber: 602,
        prUrl: PR_URL,
        state: "open",
        headOid: "head-ready",
        headRefName: "feat/x",
        mergeStateStatus: "clean",
      },
      readySnapshot(),
    );

    expect(readiness.ready).toBe(true);
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
  it("rejects null JSON payload at parse boundary (R2-G3)", () => {
    expect(() =>
      fetchPrMergeLiveState(
        fakeSh({ "gh pr view": () => "null" }),
        REPO,
        PR_URL,
      ),
    ).toThrow(/malformed gh pr view payload/);
  });

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
    executePrMergeCommit(sh, REPO, 602, "merged-head-1");
    expect(mergeCalls[0]).toEqual([
      "pr",
      "merge",
      "602",
      "--merge",
      "--match-head-commit",
      "merged-head-1",
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

  it("already_recorded wins over doc-release gate when marker present (R1-C4)", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({}),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "head-1",
      docReleaseCompleted: false,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: true,
      poll: async () => readySnapshot(),
      executeMerge: merge,
    });
    expect(result).toMatchObject({
      ok: true,
      terminalState: "already_recorded",
    });
    expect(merge).not.toHaveBeenCalled();
  });

  it("happy path: all gates green → merge commit + terminal record", async () => {
    let merged = false;
    let mergeArgs: string[] | undefined;
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
      "gh pr merge": (args) => {
        mergeArgs = args;
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
      docReleasePaths: ["VERSION"],
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
    expect(mergeArgs).toEqual([
      "pr",
      "merge",
      "602",
      "--merge",
      "--match-head-commit",
      "merged-head-1",
      "--repo",
      REPO,
    ]);
  });

  it("retries live merge confirmation when GitHub API lags (R1-G1)", async () => {
    let merged = false;
    let viewCount = 0;
    const sh = fakeSh({
      "gh pr view": () => {
        viewCount++;
        return JSON.stringify({
          number: 602,
          url: PR_URL,
          state: merged && viewCount >= 2 ? "MERGED" : "OPEN",
          headRefName: "feat/x",
          headRefOid: "merged-head-1",
          mergeStateStatus: merged && viewCount >= 2 ? "UNKNOWN" : "CLEAN",
        });
      },
      "gh pr merge": () => {
        merged = true;
        return "";
      },
    });
    const result = await runAutoMergeStage({
      sh,
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "merged-head-1",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION"],
      mergeConfirmRetryDelayMs: 0,
      poll: async () => readySnapshot({ headOid: "merged-head-1" }),
    });
    expect(viewCount).toBeGreaterThanOrEqual(2);
    expect(result).toMatchObject({
      ok: true,
      terminalState: "merged",
      record: { mergedHeadOid: "merged-head-1" },
    });
  });

  it("reuses pre-fetched live state across backfill and merge gate (R2-G1/G2)", async () => {
    let merged = false;
    let viewCount = 0;
    const sh = fakeSh({
      "gh pr view": () => {
        viewCount += 1;
        return JSON.stringify({
          number: 602,
          url: PR_URL,
          state: merged ? "MERGED" : "OPEN",
          headRefName: "feat/x",
          headRefOid: "merged-head-1",
          mergeStateStatus: merged ? "UNKNOWN" : "CLEAN",
        });
      },
      "gh pr merge": () => {
        merged = true;
        return "";
      },
    });
    const result = await runAutoMergeStage({
      sh,
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "merged-head-1",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION"],
      mergeConfirmRetryDelayMs: 0,
      poll: async () => readySnapshot({ headOid: "merged-head-1" }),
    });
    expect(viewCount).toBe(2);
    expect(result).toMatchObject({
      ok: true,
      terminalState: "merged",
      record: { mergedHeadOid: "merged-head-1" },
    });
  });

  it("retries merge confirmation after transient confirm throws (R2-G4)", async () => {
    let merged = false;
    let postMergeConfirmAttempts = 0;
    const sh = fakeSh({
      "gh pr view": () => {
        if (merged) {
          postMergeConfirmAttempts += 1;
          if (postMergeConfirmAttempts <= 2) {
            throw new Error("transient GitHub API error");
          }
        }
        return JSON.stringify({
          number: 602,
          url: PR_URL,
          state: merged ? "MERGED" : "OPEN",
          headRefName: "feat/x",
          headRefOid: "merged-head-1",
          mergeStateStatus: merged ? "UNKNOWN" : "CLEAN",
        });
      },
      "gh pr merge": () => {
        merged = true;
        return "";
      },
    });
    const result = await runAutoMergeStage({
      sh,
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "merged-head-1",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION"],
      mergeConfirmRetryDelayMs: 0,
      poll: async () => readySnapshot({ headOid: "merged-head-1" }),
    });
    expect(postMergeConfirmAttempts).toBe(3);
    expect(result).toMatchObject({
      ok: true,
      terminalState: "merged",
      record: { mergedHeadOid: "merged-head-1" },
    });
  });

  it("ADR 0123 / #735: non-doc paths (e.g. source + VERSION) no longer veto merge", async () => {
    let merged = false;
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: merged ? "MERGED" : "OPEN",
            headRefName: "feat/x",
            headRefOid: "head-1",
            mergeStateStatus: merged ? "UNKNOWN" : "CLEAN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "head-1",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION", "orchestrator/src/runner.ts"],
      poll: async () => readySnapshot({ headOid: "head-1" }),
      executeMerge: () => {
        merged = true;
      },
      mergeConfirmRetryDelayMs: 0,
    });
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("merged");
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

  it("resume backfill rejects MERGED when live head matches neither convergence nor doc-release tip (AC9)", async () => {
    const result = await tryResumePrMergedBackfill({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/x",
            headRefOid: "foreign-head",
            mergeStateStatus: "UNKNOWN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "expected-converged-head",
      expectedMergeHeadOid: "expected-doc-release-head",
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
    });
    expect(result).toBeUndefined();
  });

  it("resume backfill: S9 convergence key + post-doc MERGED tip → terminal marker (AC9)", async () => {
    const merge = vi.fn();
    const result = await tryResumePrMergedBackfill({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/x",
            headRefOid: "post-doc-release-head",
            mergeStateStatus: "UNKNOWN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "s9-pre-doc-head",
      expectedMergeHeadOid: "post-doc-release-head",
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      executeMerge: merge,
    });
    expect(merge).not.toHaveBeenCalled();
    expect(result?.terminalState).toBe("merged");
    expect(result?.record).toMatchObject({
      mergedHeadOid: "post-doc-release-head",
      convergedHeadOid: "s9-pre-doc-head",
    });
  });

  it("pending post-doc-release CI blocks merge at runAutoMergeStage (AC6)", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "OPEN",
            headRefName: "feat/x",
            headRefOid: "head-after-doc",
            mergeStateStatus: "CLEAN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "head-after-doc",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION"],
      poll: async () =>
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
      executeMerge: merge,
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("not_ready");
    expect(result.stopSummary?.summary).toMatch(/ci_pending/);
    expect(merge).not.toHaveBeenCalled();
  });

  it("live run fails closed when poll+live agree on foreign tip but expectedMergeHeadOid differs (R5-M2)", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "OPEN",
            headRefName: "feat/x",
            headRefOid: "foreign-tip-after-doc",
            mergeStateStatus: "CLEAN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "s9-pre-doc-head",
      expectedMergeHeadOid: "doc-release-head",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION"],
      poll: async () =>
        readySnapshot({ headOid: "foreign-tip-after-doc" }),
      executeMerge: merge,
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.summary).toMatch(
      /does not match expected post-doc-release head/i,
    );
    expect(merge).not.toHaveBeenCalled();
  });

  it("same-session live MERGED backfill rejects S9 tip alone when expected is post-doc (R1-C1)", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/x",
            headRefOid: "s9-pre-doc-head",
            mergeStateStatus: "UNKNOWN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "s9-pre-doc-head",
      expectedMergeHeadOid: "post-doc-release-head",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION"],
      poll: async () => readySnapshot({ headOid: "s9-pre-doc-head" }),
      executeMerge: merge,
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(merge).not.toHaveBeenCalled();
  });

  it("same-session live MERGED backfill succeeds when expectedMergeHeadOid is post-doc tip (R5-M1 wiring)", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/x",
            headRefOid: "post-doc-release-head",
            mergeStateStatus: "UNKNOWN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "s9-pre-doc-head",
      expectedMergeHeadOid: "post-doc-release-head",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION"],
      poll: async () => readySnapshot({ headOid: "post-doc-release-head" }),
      executeMerge: merge,
    });
    expect(merge).not.toHaveBeenCalled();
    expect(result).toMatchObject({
      ok: true,
      terminalState: "merged",
      record: {
        mergedHeadOid: "post-doc-release-head",
        convergedHeadOid: "s9-pre-doc-head",
      },
    });
  });

  it("ADR 0123 / #735: missing docReleasePaths no longer blocks live merge", async () => {
    let merged = false;
    const merge = vi.fn(() => {
      merged = true;
    });
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: merged ? "MERGED" : "OPEN",
            headRefName: "feat/x",
            headRefOid: "head-1",
            mergeStateStatus: merged ? "UNKNOWN" : "CLEAN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "head-1",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      poll: async () => readySnapshot({ headOid: "head-1" }),
      executeMerge: merge,
      mergeConfirmRetryDelayMs: 0,
    });
    // Empty-run / unverified paths are not a veto — live readiness is.
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("merged");
    expect(merge).toHaveBeenCalled();
  });

  it("re-fetches live PR head when poll snapshot head differs post-doc-release", async () => {
    let viewCalls = 0;
    let merged = false;
    const sh = fakeSh({
      "gh pr view": () => {
        viewCalls += 1;
        const headOid = viewCalls === 1 ? "pre-doc-head" : "post-doc-head";
        return JSON.stringify({
          number: 602,
          url: PR_URL,
          state: merged ? "MERGED" : "OPEN",
          headRefName: "feat/x",
          headRefOid: headOid,
          mergeStateStatus: merged ? "UNKNOWN" : "CLEAN",
        });
      },
      "gh pr merge": () => {
        merged = true;
        return "";
      },
    });
    const result = await runAutoMergeStage({
      sh,
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "post-doc-head",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION"],
      poll: async () => readySnapshot({ headOid: "post-doc-head" }),
    });
    expect(viewCalls).toBeGreaterThanOrEqual(2);
    expect(result.ok).toBe(true);
    expect(result.record?.mergedHeadOid).toBe("post-doc-head");
  });

  it("ADR 0123 / #735: offline synthetic merge does not require docReleasePaths", async () => {
    // Env hatch for unverified paths is obsolete as a merge veto; missing paths
    // no longer fail closed. Keep pin that offline synthetic still merges on readiness.
    vi.stubEnv("ORCHESTRATOR_AUTO_MERGE_ALLOW_UNVERIFIED_DOC_PATHS", "1");
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({}),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "head-1",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: true,
      poll: async () => readySnapshot(),
      executeMerge: merge,
    });
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("merged");
    expect(merge).toHaveBeenCalled();
  });

  it("ADR 0123 / #735: offline synthetic without paths merges when readiness green", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({}),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "head-1",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: true,
      poll: async () => readySnapshot(),
      executeMerge: merge,
    });
    expect(result.ok).toBe(true);
    expect(result.terminalState).toBe("merged");
    expect(merge).toHaveBeenCalled();
  });

  it("fails closed when live head still mismatches snapshot after re-fetch", async () => {
    const merge = vi.fn();
    const result = await runAutoMergeStage({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 602,
            url: PR_URL,
            state: "OPEN",
            headRefName: "feat/x",
            headRefOid: "still-stale-head",
            mergeStateStatus: "CLEAN",
          }),
      }),
      repo: REPO,
      prUrl: PR_URL,
      convergedHeadOid: "post-doc-head",
      docReleaseCompleted: true,
      priorConvergenceRecorded: true,
      prMergedMarkerPresent: false,
      offlineSynthetic: false,
      docReleasePaths: ["VERSION"],
      poll: async () => readySnapshot({ headOid: "post-doc-head" }),
      executeMerge: merge,
    });
    expect(result.ok).toBe(false);
    expect(result.terminalState).toBe("decision_gate");
    expect(result.stopSummary?.summary).toMatch(/still mismatches readiness snapshot/i);
    expect(merge).not.toHaveBeenCalled();
  });
});

describe("#602 prMergedRecordFromLive", () => {
  it("requires live headOid to match expected merge tip or convergence key", () => {
    expect(
      prMergedRecordFromLive(
        {
          prNumber: 602,
          prUrl: PR_URL,
          state: "MERGED",
          headOid: "wrong-head",
          headRefName: "feat/x",
          mergeStateStatus: "UNKNOWN",
        },
        "expected-head",
        "doc-release-head",
      ),
    ).toBeUndefined();
    expect(
      prMergedRecordFromLive(
        {
          prNumber: 602,
          prUrl: PR_URL,
          state: "MERGED",
          headOid: "doc-release-head",
          headRefName: "feat/x",
          mergeStateStatus: "UNKNOWN",
        },
        "s9-head",
        "doc-release-head",
      ),
    ).toMatchObject({
      mergedHeadOid: "doc-release-head",
      convergedHeadOid: "s9-head",
    });
    expect(
      prMergedRecordFromLive(
        {
          prNumber: 602,
          prUrl: PR_URL,
          state: "MERGED",
          headOid: "s9-head",
          headRefName: "feat/x",
          mergeStateStatus: "UNKNOWN",
        },
        "s9-head",
        "doc-release-head",
      ),
    ).toBeUndefined();
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

describe("#602 familyPrMergedForHead", () => {
  it("includes stopSummary only when defined, not when absent (R2-G7)", () => {
    const withSummary = familyPrMergedForHead(
      [
        {
          status: "pr_merged",
          event: "pr_merged",
          phase: "final",
          pr: PR_URL,
          prNumber: 602,
          remoteBranchName: "feat/x",
          mergedHeadOid: "merged-head",
          familyHeadAfter: "merged-head",
          stopSummary: {
            reason: "success",
            summary: "merged",
            repairHint: "none",
          },
        },
      ],
      "merged-head",
    );
    expect(withSummary?.stopSummary).toEqual({
      reason: "success",
      summary: "merged",
      repairHint: "none",
    });

    const withoutSummary = familyPrMergedForHead(
      [
        {
          status: "pr_merged",
          event: "pr_merged",
          phase: "final",
          pr: PR_URL,
          prNumber: 602,
          remoteBranchName: "feat/x",
          mergedHeadOid: "merged-head",
          familyHeadAfter: "merged-head",
        },
      ],
      "merged-head",
    );
    expect(withoutSummary).not.toHaveProperty("stopSummary");
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
