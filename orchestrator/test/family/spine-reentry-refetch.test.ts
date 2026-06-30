/**
 * Escalate-resume dependency-graph rebuild (ADR 0022 decision 4, #298
 * acceptance 3).
 *
 * When a family run escalates (cmr non-convergence / a cycle) and a human
 * answers — possibly by editing the blocked_by edges in GitHub to break a cycle
 * — the RE-ENTRY must REBUILD the dependency graph from LIVE GitHub metadata, NOT
 * trust the cached FamilyEpic (ADR 0022 decision 4: "重抓 live GitHub metadata 重
 * 建依赖图，不信缓存"; otherwise the old cycle/edges still hold and it re-escalates,
 * agy R2).
 *
 * The seam: an injected `refetchEpic` hook. When present (a re-entry), the spine
 * calls it FIRST and schedules off the LIVE graph it returns — overriding the
 * passed-in (possibly stale) epic. Absent ⇒ the passed epic is used (fresh run).
 *
 * Zero-container: the hook returns a scripted live graph; the test asserts the
 * spine scheduled off the LIVE edges, not the stale cached ones.
 */

import { describe, expect, it } from "vitest";
import { runFamily } from "../../src/family/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../src/family/types.js";

class ChildBackend implements Backend {
  readonly ran: number[] = [];
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async cleanResidue(): Promise<void> {}
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
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "## Agent Brief" };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    this.ran.push(issueNumber);
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
  }
  async push(): Promise<void> {}
  async writeLedger(): Promise<void> {}
}

class FakeFamilyBackend implements FamilyBackend {
  readonly merges: MergeRequest[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    return { familyHead: `+${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
}

describe("spine re-entry — refetch the dependency graph from live GitHub (decision 4)", () => {
  it("an unanswered family decision escalation stays paused even when refetchEpic is available", async () => {
    const staleEpic: FamilyEpic = {
      issue: 291,
      children: [{ issue: 10, blockedBy: [11] }],
    };
    const liveEpic: FamilyEpic = {
      issue: 291,
      children: [{ issue: 10, blockedBy: [] }],
    };
    const childBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push({
      status: "escalated",
      event: "escalated",
      phase: "final",
      reason: "cmr needs human disposition",
      escalationKind: "decision",
    });
    let refetched = 0;

    const result = await runFamily({
      epic: staleEpic,
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
      refetchEpic: async () => {
        refetched += 1;
        return liveEpic;
      },
    });

    expect(result.status).toBe("escalated");
    expect(refetched).toBe(0);
    expect(childBackend.ran).toEqual([]);
    expect(familyBackend.merges).toEqual([]);
  });

  it("an appended answer reopens a family decision escalation through the live refetch path", async () => {
    const staleEpic: FamilyEpic = {
      issue: 291,
      children: [{ issue: 10, blockedBy: [11] }],
    };
    const liveEpic: FamilyEpic = {
      issue: 291,
      children: [{ issue: 10, blockedBy: [] }],
    };
    const childBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push(
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        reason: "cmr needs human disposition",
        escalationKind: "decision",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "continue-same-class",
      },
    );

    const result = await runFamily({
      epic: staleEpic,
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
      refetchEpic: async () => liveEpic,
    });

    expect(result.status).toBe("success");
    expect(childBackend.ran).toEqual([10]);
    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([10]);
  });

  it("an answered family failure escalation remains terminal", async () => {
    const childBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push(
      {
        status: "escalated",
        event: "escalated",
        phase: "final",
        reason: "family base diverged from ledger",
        escalationKind: "failure",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "try-anyway",
      },
    );

    const result = await runFamily({
      epic: { issue: 291, children: [{ issue: 10, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
      refetchEpic: async () => ({
        issue: 291,
        children: [{ issue: 10, blockedBy: [] }],
      }),
    });

    expect(result.status).toBe("escalated");
    expect(childBackend.ran).toEqual([]);
    expect(familyBackend.merges).toEqual([]);
  });

  it("schedules off the LIVE edges the refetch returns, NOT the stale cached epic", async () => {
    // STALE cached epic: 11 blocked_by 10 AND 10 blocked_by 11 — a CYCLE (would
    // deadlock / escalate). A human broke it in GitHub: 11 blocked_by 10 only.
    const staleEpic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 10, blockedBy: [11] }, // cycle in the cache
        { issue: 11, blockedBy: [10] },
      ],
    };
    const liveEpic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 10, blockedBy: [] }, // human broke the cycle: 10 now unblocked
        { issue: 11, blockedBy: [10] },
      ],
    };
    const childBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    let refetched = 0;

    const result = await runFamily({
      epic: staleEpic,
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
      refetchEpic: async () => {
        refetched += 1;
        return liveEpic;
      },
    });

    // The spine re-fetched the live graph (did not trust the cache).
    expect(refetched).toBe(1);
    // Off the LIVE graph the run converges: 10 first (now unblocked), then 11.
    expect(childBackend.ran).toEqual([10, 11]);
    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([10, 11]);
    expect(result.status).toBe("success");
    // The result accounts for the LIVE children.
    expect(result.children.map((c) => c.issue).sort()).toEqual([10, 11]);
  });

  it("without refetchEpic, the passed epic is used unchanged (fresh run)", async () => {
    const epic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 10, blockedBy: [] },
        { issue: 11, blockedBy: [] },
      ],
    };
    const childBackend = new ChildBackend();
    const result = await runFamily({
      epic,
      familyBackend: new FakeFamilyBackend(),
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
    });
    expect(result.children.map((c) => c.issue).sort()).toEqual([10, 11]);
    expect(result.status).toBe("success");
  });

  it("refetch + reconcile compose: the live graph is reconciled against the ledger末条", async () => {
    // Re-entry after a crash AND a human edit. The prior run recorded 10 merged
    // (ledger末条 head=base1), then crashed before scheduling 11. Re-entry:
    //   1. refetch the LIVE graph (10 unblocked, 11 blocked_by 10);
    //   2. reconcile: ledger末条 base1 == live HEAD base1 (branch ① — nothing new
    //      landed past the ledger), so 10 is already merged, no補账;
    //   3. the wave loop runs 11 fresh (its blocker 10 is in the merged set), then
    //      10 is NOT re-run (already merged).
    const liveEpic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 10, blockedBy: [] },
        { issue: 11, blockedBy: [10] },
      ],
    };
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push({
      childIssue: 10,
      status: "merged",
      childHead: "c10",
      familyHeadAfter: "base1",
    });
    const childBackend = new ChildBackend();
    const result = await runFamily({
      epic: { issue: 291, children: [] }, // stale/empty cache
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
      refetchEpic: async () => liveEpic,
      reconcileGit: {
        async liveFamilyHead() {
          return "base1"; // == ledger末条 → branch ①
        },
        async familyBaseStartHead() {
          return "base1"; // unused on branch ① (non-empty ledger w/ familyHeadAfter)
        },
        async childHeadExists() {
          return { exists: true, childHead: "c10" };
        },
        async isAncestor() {
          return true;
        },
      },
    });

    // 10 already merged (ledger, branch ① — not re-run); 11 runs fresh after it.
    expect(childBackend.ran).toEqual([11]);
    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([11]);
    expect(result.status).toBe("success");
    expect(result.children.map((c) => c.issue).sort()).toEqual([10, 11]);
  });
});
