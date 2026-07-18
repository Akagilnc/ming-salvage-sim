/**
 * #603 — post-merge cleanup worker: live verify+act, epic close, host reclaim gate.
 */
import { describe, expect, it, vi } from "vitest";
import type { Sh } from "../src/familyDriver.js";
import {
  assessBranchDeletePrecondition,
  branchTipMatchesMergedHead,
  cleanupResultFromActs,
  dispatchPostMergeCleanup,
  fetchPaginatedSubIssues,
  runPostMergeCleanup,
  shouldCloseParentIssue,
  type LiveSubIssue,
  type PostMergeCleanupActs,
} from "../src/postMergeCleanup.js";
import {
  cleanupResultReclaimEligible,
  shouldReclaimFamilyHost,
} from "../src/hostReclaim.js";
import type { FamilyLedgerEntry } from "../src/family/types.js";
import { isValidCleanupResult } from "../src/reviewLoopOutcome.js";
import type { CleanupResult } from "../src/types.js";

const REPO = "Akagilnc/ming-salvage-sim";
const PR_URL = "https://github.com/Akagilnc/ming-salvage-sim/pull/603";
const MERGED_HEAD = "abc1234567890def1234567890abcd1234567890ab";
const DRIFT_TIP = "def9999999999999999999999999999999999999999";

const PR_MERGED = {
  prUrl: PR_URL,
  prNumber: 603,
  remoteBranchName: "feat/issue-603",
  mergedHeadOid: MERGED_HEAD,
  convergedHeadOid: MERGED_HEAD,
};

describe("#891 offline cleanup dispatch is hermetic", () => {
  it("does not execute gh when an offline test handle carries cleanup landing", () => {
    // #941: fake-PR offline hatch deleted from dispatchPostMergeCleanup.
    // Landing Action injects liveState; unit callers must do the same.
    const sh = vi.fn<Sh>(() => {
      throw new Error("injected liveState must not execute host CLI");
    });

    const result = runPostMergeCleanup({
      sh,
      repo: REPO,
      coveredIssues: [603],
      prMerged: {
        prUrl: "pr://slice/branch-cargo/feat%2Fissue-603",
        prNumber: 603,
        remoteBranchName: "feat/issue-603",
        mergedHeadOid: MERGED_HEAD,
        convergedHeadOid: MERGED_HEAD,
      },
      liveState: {
        state: "MERGED",
        headOid: MERGED_HEAD,
        prNumber: 603,
        prUrl: "pr://slice/branch-cargo/feat%2Fissue-603",
        headRefName: "feat/issue-603",
      },
      fetchIssueState: () => "CLOSED",
      branchExists: () => false,
    });

    expect(result).toEqual({
      kind: "cleanup",
      terminal: true,
      ok: true,
      branchOutcome: "already_gone",
    });
    expect(sh).not.toHaveBeenCalled();
  });
});

function fakeSh(handlers: Record<string, (args: string[]) => string>): Sh {
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

describe("#603 shouldCloseParentIssue", () => {
  const subs = (rows: LiveSubIssue[]) => rows;

  it("keeps parent open when an open sibling is on page 2", () => {
    const live: LiveSubIssue[] = [
      { number: 601, state: "CLOSED" },
      { number: 602, state: "CLOSED" },
      { number: 604, state: "OPEN" },
    ];
    expect(shouldCloseParentIssue(subs(live), [603])).toBe(false);
  });

  it("closes parent when family PR covers the last two open siblings", () => {
    const live: LiveSubIssue[] = [
      { number: 601, state: "CLOSED" },
      { number: 602, state: "OPEN" },
      { number: 603, state: "OPEN" },
    ];
    expect(shouldCloseParentIssue(subs(live), [602, 603])).toBe(true);
  });

  it("closes parent when every live sub-issue is already closed", () => {
    expect(
      shouldCloseParentIssue(
        subs([
          { number: 601, state: "CLOSED" },
          { number: 602, state: "closed" },
        ]),
        [603],
      ),
    ).toBe(true);
  });

  it("refuses close when live sub-issue list is empty (fail-closed)", () => {
    expect(shouldCloseParentIssue([], [603])).toBe(false);
    expect(shouldCloseParentIssue([], [])).toBe(false);
  });
});

describe("#603 assessBranchDeletePrecondition", () => {
  it("refuses delete when tip drifted past merged head (AC2)", () => {
    expect(
      assessBranchDeletePrecondition({
        prState: "MERGED",
        branchExists: true,
        branchTip: DRIFT_TIP,
        mergedHeadOid: MERGED_HEAD,
      }),
    ).toBe("skip_tip_drift");
  });

  it("treats missing branch as already_gone (AC4 idempotent)", () => {
    expect(
      assessBranchDeletePrecondition({
        prState: "MERGED",
        branchExists: false,
        mergedHeadOid: MERGED_HEAD,
      }),
    ).toBe("already_gone");
  });

  it("allows delete only when PR is MERGED and tip matches", () => {
    expect(
      assessBranchDeletePrecondition({
        prState: "MERGED",
        branchExists: true,
        branchTip: MERGED_HEAD,
        mergedHeadOid: MERGED_HEAD,
      }),
    ).toBe("may_delete");
    expect(
      assessBranchDeletePrecondition({
        prState: "OPEN",
        branchExists: true,
        branchTip: MERGED_HEAD,
        mergedHeadOid: MERGED_HEAD,
      }),
    ).toBe("skip_pr_not_merged");
  });

  it("treats MERGED case/whitespace-insensitively (landing/cleanup shared predicate)", () => {
    expect(
      assessBranchDeletePrecondition({
        prState: "merged",
        branchExists: true,
        branchTip: MERGED_HEAD,
        mergedHeadOid: MERGED_HEAD,
      }),
    ).toBe("may_delete");
    expect(
      assessBranchDeletePrecondition({
        prState: "  Merged  ",
        branchExists: true,
        branchTip: MERGED_HEAD,
        mergedHeadOid: MERGED_HEAD,
      }),
    ).toBe("may_delete");
  });
});

describe("#603 branchTipMatchesMergedHead", () => {
  it("matches exact oid only", () => {
    expect(branchTipMatchesMergedHead(MERGED_HEAD, MERGED_HEAD)).toBe(true);
    expect(branchTipMatchesMergedHead(DRIFT_TIP, MERGED_HEAD)).toBe(false);
    expect(branchTipMatchesMergedHead(undefined, MERGED_HEAD)).toBe(false);
  });
});

describe("#603 runPostMergeCleanup — live verify before act (AC1)", () => {
  it("closes covered issues and deletes branch after MERGED + tip match", () => {
    const closed: number[] = [];
    let deletedBranch: string | undefined;
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 603,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/issue-603",
            headRefOid: MERGED_HEAD,
          }),
        "gh api repos": () => {
          throw new Error("branch api should be injected");
        },
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: PR_MERGED,
      fetchIssueState: (n) => (n === 603 ? "OPEN" : "CLOSED"),
      closeIssue: (n) => {
        closed.push(n);
      },
      branchExists: () => true,
      fetchBranchTip: () => MERGED_HEAD,
      deleteBranch: (b) => {
        deletedBranch = b;
      },
    });
    expect(closed).toEqual([603]);
    expect(deletedBranch).toBe("feat/issue-603");
    expect(result).toEqual(
      expect.objectContaining({
        kind: "cleanup",
        terminal: true,
        ok: true,
        issuesClosed: [603],
        branchOutcome: "deleted",
      }),
    );
    expect(isValidCleanupResult(result)).toBe(true);
  });

  it("does not delete when tip drifted (AC2 negative)", () => {
    let deleted = false;
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 603,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/issue-603",
            headRefOid: MERGED_HEAD,
          }),
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: PR_MERGED,
      fetchIssueState: () => "CLOSED",
      branchExists: () => true,
      fetchBranchTip: () => DRIFT_TIP,
      deleteBranch: () => {
        deleted = true;
      },
    });
    expect(deleted).toBe(false);
    expect(result.branchOutcome).toBe("skipped_tip_drift");
    expect(result.terminal).toBe(false);
    expect(result.ok).toBe(false);
    expect(cleanupResultReclaimEligible(result)).toBe(false);
  });

  it("does not fabricate MERGED offline without ORCHESTRATOR_OFFLINE_REVIEW_POLL=1 (#602 parity)", () => {
    vi.stubEnv("ORCHESTRATOR_OFFLINE_REVIEW_POLL", "0");
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () => {
          throw new Error("live gh pr view must run when offline hatch is off");
        },
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: PR_MERGED,
      fetchIssueState: () => "CLOSED",
      branchExists: () => false,
    });
    expect(result.terminal).toBe(false);
    expect(result.skippedReasons?.some((r) => r.startsWith("live_pr_fetch_failed"))).toBe(
      true,
    );
    // live fetch failure is a precondition miss, not "PR not merged"
    expect(result.branchOutcome).toBe("skipped_precondition");
  });

  it("#941: liveState injection completes cleanup without gh (no offline env hatch)", () => {
    const closed: number[] = [];
    const sh = fakeSh({
      "gh pr view": () => {
        throw new Error("liveState injection must not call live gh pr view");
      },
    });
    const result = runPostMergeCleanup({
      sh,
      repo: REPO,
      coveredIssues: [603],
      prMerged: {
        ...PR_MERGED,
        prUrl: "pr://family/offline-cleanup",
      },
      liveState: {
        state: "MERGED",
        headOid: MERGED_HEAD,
        prNumber: 603,
        prUrl: "pr://family/offline-cleanup",
        headRefName: "feat/issue-603",
      },
      fetchIssueState: () => "OPEN",
      closeIssue: (n) => closed.push(n),
      branchExists: () => false,
    });
    expect(closed).toEqual([603]);
    expect(result.terminal).toBe(true);
    expect(result.ok).toBe(true);
    expect(result.branchOutcome).toBe("already_gone");
  });

  it("returns non-terminal when PR is not live MERGED (no trust of ledger alone)", () => {
    vi.stubEnv("ORCHESTRATOR_OFFLINE_REVIEW_POLL", "0");
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 603,
            url: PR_URL,
            state: "OPEN",
            headRefName: "feat/issue-603",
            headRefOid: MERGED_HEAD,
            mergeStateStatus: "CLEAN",
          }),
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: PR_MERGED,
    });
    expect(result.terminal).toBe(false);
    expect(result.ok).toBe(false);
    expect(result.branchOutcome).toBe("skipped_pr_not_merged");
  });
});

describe("#603 runPostMergeCleanup — branch delete idempotency (AC4)", () => {
  it("already-gone branch is terminal success and continues other steps", () => {
    const closed: number[] = [];
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 603,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/issue-603",
            headRefOid: MERGED_HEAD,
          }),
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: PR_MERGED,
      fetchIssueState: () => "OPEN",
      closeIssue: (n) => closed.push(n),
      branchExists: () => false,
      deleteBranch: () => {
        throw new Error("must not delete when branch already gone");
      },
    });
    expect(closed).toEqual([603]);
    expect(result.branchOutcome).toBe("already_gone");
    expect(result.terminal).toBe(true);
    expect(result.ok).toBe(true);
  });
});

describe("#603 runPostMergeCleanup — parent epic close (AC3)", () => {
  it("closes parent when coveredIssues finish the family set", () => {
    const closed: number[] = [];
    const issueState = new Map<number, string>([
      [366, "OPEN"],
      [602, "OPEN"],
      [603, "OPEN"],
    ]);
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 603,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/family",
            headRefOid: MERGED_HEAD,
          }),
      }),
      repo: REPO,
      coveredIssues: [602, 603],
      parentIssue: 366,
      prMerged: { ...PR_MERGED, remoteBranchName: "feat/family" },
      fetchIssueState: (n) => issueState.get(n) ?? "CLOSED",
      fetchSubIssues: () => [
        { number: 601, state: "CLOSED" },
        { number: 602, state: "OPEN" },
        { number: 603, state: "OPEN" },
      ],
      closeIssue: (n) => {
        closed.push(n);
        issueState.set(n, "CLOSED");
      },
      branchExists: () => false,
    });
    expect(closed.sort((a, b) => a - b)).toEqual([366, 602, 603]);
    expect(result.parentIssueClosed).toBe(true);
  });

  it("does not close parent when live sub-issues are empty/unobserved", () => {
    const closed: number[] = [];
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 603,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/family",
            headRefOid: MERGED_HEAD,
          }),
      }),
      repo: REPO,
      coveredIssues: [603],
      parentIssue: 366,
      prMerged: { ...PR_MERGED, remoteBranchName: "feat/family" },
      fetchIssueState: (n) => (n === 603 ? "OPEN" : "OPEN"),
      fetchSubIssues: () => [],
      closeIssue: (n) => {
        closed.push(n);
      },
      branchExists: () => false,
    });
    expect(closed).toEqual([603]);
    expect(closed).not.toContain(366);
    expect(result.parentIssueClosed).not.toBe(true);
    expect(result.terminal).toBe(true);
  });
});

describe("#603 defaultBranchExists — missing ref vs API error", () => {
  function mergedPrSh(
    branchApi: () => string,
  ): ReturnType<typeof fakeSh> {
    return fakeSh({
      "gh pr view": () =>
        JSON.stringify({
          number: 603,
          url: PR_URL,
          state: "MERGED",
          headRefName: "feat/issue-603",
          headRefOid: MERGED_HEAD,
        }),
      "gh api repos": () => branchApi(),
    });
  }

  it("treats genuine missing ref (404) as already_gone terminal success", () => {
    const missing = Object.assign(new Error("gh api failed: Not Found"), {
      status: 1,
      stderr: 'gh: Not Found (HTTP 404)\n{"message":"Not Found"}',
    });
    const result = runPostMergeCleanup({
      sh: mergedPrSh(() => {
        throw missing;
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: PR_MERGED,
      fetchIssueState: () => "CLOSED",
      deleteBranch: () => {
        throw new Error("must not delete when branch missing");
      },
    });
    expect(result.branchOutcome).toBe("already_gone");
    expect(result.terminal).toBe(true);
    expect(result.ok).toBe(true);
  });

  it("does not map transport/API errors to already_gone (non-terminal)", () => {
    const transport = Object.assign(new Error("gh api failed: Bad Gateway"), {
      status: 1,
      stderr: "HTTP 502: Bad Gateway",
    });
    const result = runPostMergeCleanup({
      sh: mergedPrSh(() => {
        throw transport;
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: PR_MERGED,
      fetchIssueState: () => "CLOSED",
      deleteBranch: () => {
        throw new Error("must not delete on API error");
      },
    });
    expect(result.branchOutcome).not.toBe("already_gone");
    expect(result.terminal).toBe(false);
    expect(result.ok).toBe(false);
    expect(
      result.skippedReasons?.some((r) => r.startsWith("branch_ref_probe_failed")),
    ).toBe(true);
  });

  it("may_delete: concurrent delete 404/missing → already_gone terminal success", () => {
    const gone = Object.assign(new Error("gh api failed: Not Found"), {
      status: 1,
      stderr: 'gh: Not Found (HTTP 404)\n{"message":"Not Found"}',
    });
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 603,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/issue-603",
            headRefOid: MERGED_HEAD,
          }),
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: PR_MERGED,
      fetchIssueState: () => "CLOSED",
      branchExists: () => true,
      fetchBranchTip: () => MERGED_HEAD,
      deleteBranch: () => {
        throw gone;
      },
    });
    expect(result.branchOutcome).toBe("already_gone");
    expect(result.terminal).toBe(true);
    expect(result.ok).toBe(true);
  });

  it("may_delete: non-404 delete errors still fail (not already_gone)", () => {
    const boom = Object.assign(new Error("gh api failed: Forbidden"), {
      status: 1,
      stderr: "HTTP 403: Forbidden",
    });
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () =>
          JSON.stringify({
            number: 603,
            url: PR_URL,
            state: "MERGED",
            headRefName: "feat/issue-603",
            headRefOid: MERGED_HEAD,
          }),
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: PR_MERGED,
      fetchIssueState: () => "CLOSED",
      branchExists: () => true,
      fetchBranchTip: () => MERGED_HEAD,
      deleteBranch: () => {
        throw boom;
      },
    });
    expect(result.branchOutcome).not.toBe("already_gone");
    expect(result.branchOutcome).not.toBe("deleted");
    expect(result.terminal).toBe(false);
    expect(result.ok).toBe(false);
    expect(
      result.skippedReasons?.some((r) => r.startsWith("branch_delete_failed")),
    ).toBe(true);
  });
});

describe("#603 fetchPaginatedSubIssues", () => {
  it("paginates per_page=100 until short page", () => {
    const calls: string[] = [];
    const sh = fakeSh({
      "gh api repos": (args) => {
        calls.push(args.join(" "));
        if (args.some((a) => /(?:^|[&?])page=1(?:&|$)/.test(a))) {
          return JSON.stringify(
            Array.from({ length: 100 }, (_, i) => ({
              number: i + 1,
              state: "OPEN",
            })),
          );
        }
        return JSON.stringify([{ number: 101, state: "OPEN" }]);
      },
    });
    const nodes = fetchPaginatedSubIssues(sh, REPO, 366);
    expect(nodes).toHaveLength(101);
    expect(calls.some((c) => c.includes("per_page=100"))).toBe(true);
    expect(calls.some((c) => c.includes("page=2"))).toBe(true);
  });

  it("fails closed on missing/non-finite number entries (same class as admission)", () => {
    const sh = fakeSh({
      "gh api repos": () =>
        JSON.stringify([
          { number: 1, state: "OPEN" },
          { state: "OPEN" },
        ]),
    });
    expect(() => fetchPaginatedSubIssues(sh, REPO, 366)).toThrow(
      /sub_issues entry schema error|missing or non-finite number/i,
    );
  });

  it("error indices are contiguous within a multi-entry page (pageOffset + i)", () => {
    const sh = fakeSh({
      "gh api repos": () =>
        JSON.stringify([
          { number: 1, state: "OPEN" },
          { number: 2, state: "OPEN" },
          { state: "OPEN" }, // third entry — index must be 2, not 4
        ]),
    });
    expect(() => fetchPaginatedSubIssues(sh, REPO, 366)).toThrow(
      /sub_issue\[2\]: missing or non-finite number/,
    );
  });

  it("error indices continue across pages from absolute pageOffset", () => {
    const sh = fakeSh({
      "gh api repos": (args) => {
        if (args.some((a) => /(?:^|[&?])page=1(?:&|$)/.test(a))) {
          return JSON.stringify(
            Array.from({ length: 100 }, (_, i) => ({
              number: i + 1,
              state: "OPEN",
            })),
          );
        }
        // First entry of page 2 is bad → absolute index 100
        return JSON.stringify([
          { state: "OPEN" },
          { number: 102, state: "OPEN" },
        ]);
      },
    });
    expect(() => fetchPaginatedSubIssues(sh, REPO, 366)).toThrow(
      /sub_issue\[100\]: missing or non-finite number/,
    );
  });
});

describe("#603 CleanupResult terminal vs non-terminal (AC6)", () => {
  it("cleanupResultFromActs distinguishes terminal success from retryable", () => {
    const terminal: CleanupResult = cleanupResultFromActs({
      allStepsComplete: true,
      issuesClosed: [603],
      branchOutcome: "deleted",
    });
    expect(terminal.terminal).toBe(true);
    expect(terminal.ok).toBe(true);

    const retry: CleanupResult = cleanupResultFromActs({
      allStepsComplete: false,
      skippedReasons: ["pr_not_merged"],
      branchOutcome: "skipped_pr_not_merged",
    });
    expect(retry.terminal).toBe(false);
    expect(retry.ok).toBe(false);
    expect(isValidCleanupResult(retry)).toBe(true);
  });

  it("rejects non-terminal ok:true in guard", () => {
    expect(
      isValidCleanupResult({
        kind: "cleanup",
        terminal: false,
        ok: true,
      }),
    ).toBe(false);
  });
});

describe("#603 family host reclaim gate — ledger precondition only (AC5)", () => {
  const terminalRow = (output: CleanupResult): FamilyLedgerEntry => ({
    status: "post_merge_cleanup",
    event: "post_merge_cleanup",
    phase: "final",
    familyHeadAfter: MERGED_HEAD,
    cleanupOutput: output,
  });

  it("reclaims family host only on terminal+ok post_merge_cleanup ledger row", () => {
    const ledger: FamilyLedgerEntry[] = [
      terminalRow({
        kind: "cleanup",
        terminal: true,
        ok: true,
        branchOutcome: "deleted",
      }),
    ];
    expect(shouldReclaimFamilyHost(ledger)).toBe(true);
  });

  it("does not reclaim family host on non-terminal cleanup (negative)", () => {
    const ledger: FamilyLedgerEntry[] = [
      terminalRow({
        kind: "cleanup",
        terminal: false,
        ok: false,
        branchOutcome: "skipped_tip_drift",
      }),
    ];
    expect(shouldReclaimFamilyHost(ledger)).toBe(false);
  });
});
