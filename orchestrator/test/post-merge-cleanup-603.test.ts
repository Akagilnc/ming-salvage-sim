/**
 * #603 — post-merge cleanup worker: live verify+act, epic close, host reclaim gate.
 */
import { describe, expect, it, vi } from "vitest";
import type { Sh } from "../src/familyDriver.js";
import {
  assessBranchDeletePrecondition,
  branchTipMatchesMergedHead,
  cleanupResultFromActs,
  fetchPaginatedSubIssues,
  runPostMergeCleanup,
  shouldCloseParentIssue,
  type LiveSubIssue,
  type PostMergeCleanupActs,
} from "../src/postMergeCleanup.js";
import {
  cleanupResultReclaimEligible,
  shouldReclaimFamilyHost,
  shouldReclaimSliceHost,
  sliceCleanupTerminalForReclaim,
} from "../src/hostReclaim.js";
import type { FamilyLedgerEntry } from "../src/family/types.js";
import { isValidCleanupResult } from "../src/reviewLoopOutcome.js";
import type { CleanupResult, LedgerEntry } from "../src/types.js";

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
  });

  it("allows offline synthetic MERGED only with explicit ORCHESTRATOR_OFFLINE_REVIEW_POLL=1", () => {
    vi.stubEnv("ORCHESTRATOR_OFFLINE_REVIEW_POLL", "1");
    const closed: number[] = [];
    const result = runPostMergeCleanup({
      sh: fakeSh({
        "gh pr view": () => {
          throw new Error("offline hatch must not call live gh pr view");
        },
      }),
      repo: REPO,
      coveredIssues: [603],
      prMerged: {
        ...PR_MERGED,
        prUrl: "pr://family/offline-cleanup",
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

describe("#603 host reclaim gate — ledger precondition only (AC5)", () => {
  const terminalCleanup: CleanupResult = {
    kind: "cleanup",
    terminal: true,
    ok: true,
    branchOutcome: "deleted",
  };

  it("reclaims only on success handoff with terminal cleanup ledger row", () => {
    const ledger: LedgerEntry[] = [
      { step: "S11", output: terminalCleanup },
      { step: "S8" },
    ];
    expect(sliceCleanupTerminalForReclaim(ledger)).toBe(true);
    expect(shouldReclaimSliceHost(ledger, "success")).toBe(true);
  });

  it("does not reclaim on park / failed / malformed cleanup (negative)", () => {
    const parked: LedgerEntry[] = [
      {
        step: "S11",
        output: { kind: "cleanup", terminal: false, ok: false },
      },
    ];
    expect(sliceCleanupTerminalForReclaim(parked)).toBe(false);
    expect(shouldReclaimSliceHost(parked, "escalate")).toBe(false);

    const failed: LedgerEntry[] = [
      {
        step: "S11",
        output: { kind: "cleanup", terminal: true, ok: false },
      },
    ];
    expect(sliceCleanupTerminalForReclaim(failed)).toBe(false);
    expect(shouldReclaimSliceHost(failed, "error")).toBe(false);
  });

  it("never trusts a worker report without a persisted S11 ledger row", () => {
    expect(
      shouldReclaimSliceHost(
        [{ step: "S8" }],
        "success",
      ),
    ).toBe(false);
  });

  it("does not reclaim when last cleanup skipped branch delete with residue (tip drift)", () => {
    const driftCleanup: CleanupResult = {
      kind: "cleanup",
      terminal: false,
      ok: false,
      branchOutcome: "skipped_tip_drift",
    };
    const ledger: LedgerEntry[] = [{ step: "S11", output: driftCleanup }];
    expect(sliceCleanupTerminalForReclaim(ledger)).toBe(false);
    expect(shouldReclaimSliceHost(ledger, "success")).toBe(false);
    expect(cleanupResultReclaimEligible(driftCleanup)).toBe(false);
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
