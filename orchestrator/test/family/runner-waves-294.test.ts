/**
 * #294 — commander dependency-wave scheduling + ledger-merged unblock + cycle
 * fail-closed, at the family-spine level (ADR 0022 decisions 1 / 3① / 6②③).
 *
 * Three acceptance criteria:
 *   1. A dependency-chain epic schedules in TOPOLOGICAL order: a blocked child is
 *      fanned out only AFTER its blocker is merged into the family base (its
 *      `status:"merged"` ledger entry exists). Multi-wave, driven by the ledger.
 *   2. The unblock judgment is LEDGER-MERGED, not GitHub `closed`: the family
 *      ledger (not the issue's closed state) gates the next wave, AND the child's
 *      own single-slice S0 `blocked_by` check goes through the same ledger-merged
 *      口径 in family mode — a child the commander just released is NOT re-rejected
 *      by its own S0 (decision 6③).
 *   3. A `blocked_by` CYCLE → the spine fails closed (throws an escalation) before
 *      scheduling — never a silent empty-wave deadlock.
 *
 * Verified zero-container (sames form as spine.test.ts): a fake single-slice
 * Backend drives each child to S8(success), a fake FamilyBackend records merges +
 * ledger writes.
 */

import { describe, expect, it } from "vitest";
import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { runFamily } from "../../src/family/runner.js";
import { recordFamilyEscalated } from "../../src/family/ledger.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  RunInput,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";
import type {
  FamilyBackend,
  FamilyEscalation,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../src/family/types.js";

// ─── fakes ────────────────────────────────────────────────────────────────────

/**
 * A single-slice Backend that drives every child to S8(success). The merge order
 * (which child reached the family base when) is observed on the FamilyBackend, so
 * this fake only needs to honour each child's S0 gate + run it to success.
 */
class RecordingChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  pushCount = 0;

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
    return { branch: `feat/child-${issueNumber}`, base, path: `/wt/${issueNumber}` };
  }
  async writeSnapshot(): Promise<void> {}
  async runStep(spec: StepSpec): Promise<StepOutput> {
    if (spec.role === "coder") return { kind: "coder", committed: true, commitsAdded: 1 };
    return { kind: "reviewer", findings: [] };
  }
  async push(): Promise<void> {
    this.pushCount += 1;
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

/** A FamilyBackend recording merge order + the append-only ledger. */
class FakeFamilyBackend implements FamilyBackend {
  readonly mergeOrder: number[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.mergeOrder.push(child.childIssue);
    return { familyHead: `h${child.childIssue}` };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
}

class LandedWithoutMergerReportBackend extends FakeFamilyBackend {
  readonly resolverCalls: number[] = [];

  override async mergeChildIntoFamilyBase(child: MergeRequest) {
    this.mergeOrder.push(child.childIssue);
    return { familyHead: `conflicted-${child.childIssue}`, conflicted: true };
  }

  async resolveMergeConflict(request: MergeRequest) {
    this.resolverCalls.push(request.childIssue);
    // Git post-state is authoritative: both merger report channels are empty,
    // but the merge commit has already landed and the step returns clean.
    return { familyHead: `landed-${request.childIssue}` };
  }
}

class PersistentlyConflictedFamilyBackend extends FakeFamilyBackend {
  readonly resolverCalls: number[] = [];
  readonly escalationCalls: Array<{ reason: string; escalationKind?: string; phase?: string }> = [];

  override async mergeChildIntoFamilyBase(child: MergeRequest) {
    this.mergeOrder.push(child.childIssue);
    return { familyHead: `conflicted-${child.childIssue}`, conflicted: true };
  }

  async resolveMergeConflict(request: MergeRequest) {
    this.resolverCalls.push(request.childIssue);
    return { familyHead: `conflicted-${request.childIssue}`, conflicted: true };
  }

  async escalateFamily(escalation: FamilyEscalation): Promise<void> {
    this.escalationCalls.push(escalation);
    await recordFamilyEscalated(this, {
      reason: escalation.reason,
      escalationKind: escalation.escalationKind ?? "decision",
      phase: escalation.phase ?? "final",
      familyHeadAfter: escalation.familyHeadAfter,
      stopSummary: escalation.stopSummary,
    });
  }
}

class DecisionEscalatingMergerBackend extends PersistentlyConflictedFamilyBackend {
  override async resolveMergeConflict(request: MergeRequest) {
    this.resolverCalls.push(request.childIssue);
    return {
      familyHead: `conflicted-${request.childIssue}`,
      escalation: {
        reason: "choose the canonical migration",
        diagnosis: "both branches deliberately changed the same public contract",
        escalationKind: "decision" as const,
        phase: "wave" as const,
      },
    };
  }
}

// ─── acceptance 1: topological multi-wave ─────────────────────────────────────

describe("#294 acceptance 1 — dependency chain scheduled in topological order", () => {
  it("a landed merge with no merger report still records the child and continues the wave", async () => {
    const familyBackend = new LandedWithoutMergerReportBackend();
    const result = await runFamily({
      epic: {
        issue: 291,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new RecordingChildBackend(),
      familyBase: "family/291-base",
    });

    expect(familyBackend.resolverCalls).toEqual([10, 11]);
    expect(familyBackend.ledger.map((entry) => entry.childIssue)).toEqual([10, 11]);
    expect(result.status).toBe("success");
    expect(result.children.every((child) => child.status === "merged")).toBe(true);
  });

  it("parks and escalates an unresolved merger step after its bound without starting the next child", async () => {
    const familyBackend = new PersistentlyConflictedFamilyBackend();
    const result = await runFamily({
      epic: {
        issue: 291,
        children: [
          { issue: 10, blockedBy: [] },
          { issue: 11, blockedBy: [] },
        ],
      },
      familyBackend,
      singleSliceBackend: new RecordingChildBackend(),
      familyBase: "family/291-base",
    });

    expect(result.status).toBe("escalated");
    expect(familyBackend.resolverCalls).toEqual(
      Array.from({ length: MAX_DISPATCH_ATTEMPTS }, () => 10),
    );
    expect(familyBackend.mergeOrder).toEqual([10]);
    expect(familyBackend.escalationCalls).toHaveLength(1);
    expect(familyBackend.escalationCalls[0]).toEqual(
      expect.objectContaining({
        reason: "merger step for child #10 exhausted bounded still-conflicted retries",
        escalationKind: "failure",
        phase: "wave",
      }),
    );
    expect(familyBackend.ledger).toEqual([
      expect.objectContaining({
        status: "escalated",
        event: "escalated",
      }),
    ]);
    expect(result.children.find((child) => child.issue === 11)?.status).toBe("skipped");
  });

  it("durably parks a structured merger decision without retrying it", async () => {
    const familyBackend = new DecisionEscalatingMergerBackend();
    const result = await runFamily({
      epic: { issue: 291, children: [{ issue: 10, blockedBy: [] }, { issue: 11, blockedBy: [] }] },
      familyBackend,
      singleSliceBackend: new RecordingChildBackend(),
      familyBase: "family/291-base",
    });

    expect(result.status).toBe("escalated");
    expect(familyBackend.resolverCalls).toEqual([10]);
    expect(familyBackend.escalationCalls[0]).toEqual(
      expect.objectContaining({
        reason: "choose the canonical migration",
        diagnosis: "both branches deliberately changed the same public contract",
        escalationKind: "decision",
        phase: "wave",
      }),
    );
    expect(familyBackend.ledger).toContainEqual(
      expect.objectContaining({ status: "escalated", escalationKind: "decision", phase: "wave" }),
    );
    expect(result.children.find((child) => child.issue === 11)?.status).toBe("skipped");
  });

  it("a 3-link chain (10 → 11 → 12) merges in topological order across waves", async () => {
    const singleSliceBackend = new RecordingChildBackend();
    const familyBackend = new FakeFamilyBackend();
    // 12 blocked_by 11 blocked_by 10.
    const epic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 12, blockedBy: [11] },
        { issue: 11, blockedBy: [10] },
        { issue: 10, blockedBy: [] },
      ],
    };
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend,
      familyBase: "family/291-base",
    });
    // Topological merge order regardless of input order: 10, then 11, then 12.
    expect(familyBackend.mergeOrder).toEqual([10, 11, 12]);
    expect(result.children.every((c) => c.status === "merged")).toBe(true);
    expect(result.status).toBe("success");
  });

  it("a blocked child is NOT scheduled until its blocker's MERGED ledger entry exists", async () => {
    // Assert mid-flight: when 11 (blocked_by 10) is about to merge, 10 must
    // already be in the ledger as merged.
    const sawTenMergedBeforeEleven = { value: false };
    class OrderAssertingFamilyBackend extends FakeFamilyBackend {
      override async mergeChildIntoFamilyBase(child: MergeRequest) {
        if (child.childIssue === 11) {
          sawTenMergedBeforeEleven.value = this.ledger.some(
            (e) => e.childIssue === 10 && e.status === "merged",
          );
        }
        return super.mergeChildIntoFamilyBase(child);
      }
    }
    const fb = new OrderAssertingFamilyBackend();
    const epic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 11, blockedBy: [10] },
        { issue: 10, blockedBy: [] },
      ],
    };
    await runFamily({
      epic,
      familyBackend: fb,
      singleSliceBackend: new RecordingChildBackend(),
      familyBase: "family/291-base",
    });
    expect(sawTenMergedBeforeEleven.value).toBe(true);
  });
});

// ─── acceptance 2: ledger-merged口径, incl. child S0 (decision 6③) ─────────────

describe("#294 acceptance 2 — unblock is ledger-merged, incl. the child's own S0", () => {
  it("a released child whose GitHub blocked_by is STILL OPEN passes its own S0 (ledger-merged口径)", async () => {
    // The killer regression (ADR 0022 decision 6③ / agy R2): the commander
    // releases 11 because 10 is ledger-merged — but 11's GitHub issue still lists
    // #10 as an OPEN blocked_by (10's issue was not closed, only merged into the
    // family base). With the单片 S0 gate's GitHub-closed check unchanged, 11's own
    // S0 would re-reject it ("blocked by #10 still open") → deadlock. In family
    // mode the child S0 must use the ledger-merged口径, so 11 runs through.
    class GitHubStillBlockedBackend extends RecordingChildBackend {
      override async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        // 11 STILL shows #10 as an open blocked_by per GitHub (not closed).
        return {
          number: issueNumber,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: issueNumber === 11 ? [10] : [],
        };
      }
    }
    const singleSliceBackend = new GitHubStillBlockedBackend();
    const familyBackend = new FakeFamilyBackend();
    const epic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 11, blockedBy: [10] },
        { issue: 10, blockedBy: [] },
      ],
    };
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend,
      familyBase: "family/291-base",
    });
    // 11 ran + merged despite GitHub still listing #10 open — the ledger-merged
    //口径 released it AND its own S0 honoured the same口径.
    expect(familyBackend.mergeOrder).toEqual([10, 11]);
    expect(result.children.every((c) => c.status === "merged")).toBe(true);
    expect(result.status).toBe("success");
  });

  it("a child blocked by a TRULY-OPEN external blocker (not a family child, not merged) is still rejected by S0", async () => {
    // Soundness guard: the ledger-merged口径 only excuses blockers KNOWN merged
    // into the family base. A blocked_by issue that is NOT a family child and NOT
    // in the ledger is a genuine open blocker — the child's S0 must STILL reject
    // it (we do not blanket-skip the blocked_by check in family mode).
    class ExternalBlockerBackend extends RecordingChildBackend {
      override async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        // 10 is blocked by #999, an EXTERNAL open issue (not a family child).
        return {
          number: issueNumber,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: issueNumber === 10 ? [999] : [],
        };
      }
    }
    const singleSliceBackend = new ExternalBlockerBackend();
    const familyBackend = new FakeFamilyBackend();
    // 10 declares NO family blocked_by (999 is external, not a sibling child), so
    // the commander schedules it — but its own S0 sees the open external #999.
    const epic: FamilyEpic = {
      issue: 291,
      children: [{ issue: 10, blockedBy: [] }],
    };
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend,
      familyBase: "family/291-base",
    });

    expect(result.status).toBe("incomplete");
    expect(result.children).toEqual([{ issue: 10, status: "failed" }]);
    expect(result.stopSummary.reason).toBe("owning_issue_still_red");
    expect(result.stopSummary.summary).toContain("#10:failed");
  });
});

// ─── acceptance 3: cycle fail-closed through the spine ────────────────────────

describe("#294 acceptance 3 — blocked_by cycle fails closed (no deadlock)", () => {
  it("a 2-node cycle (10↔11) makes runFamily fail-closed (throws), not stall on an empty wave", async () => {
    const singleSliceBackend = new RecordingChildBackend();
    const familyBackend = new FakeFamilyBackend();
    const epic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 10, blockedBy: [11] },
        { issue: 11, blockedBy: [10] },
      ],
    };
    await expect(
      runFamily({
        epic,
        familyBackend,
        singleSliceBackend,
        familyBase: "family/291-base",
      }),
    ).rejects.toThrow(/cycle/i);
    // Fail-closed BEFORE any child fan-out / merge: nothing was merged.
    expect(familyBackend.mergeOrder).toEqual([]);
  });

  it("a cycle is detected even when an independent child could otherwise run", async () => {
    const singleSliceBackend = new RecordingChildBackend();
    const familyBackend = new FakeFamilyBackend();
    const epic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 99, blockedBy: [] },
        { issue: 10, blockedBy: [11] },
        { issue: 11, blockedBy: [10] },
      ],
    };
    await expect(
      runFamily({
        epic,
        familyBackend,
        singleSliceBackend,
        familyBase: "family/291-base",
      }),
    ).rejects.toThrow(/cycle/i);
    // No child merged — the cycle guard runs before the wave loop, so even the
    // independent #99 is not fanned out (fail-closed is whole-run).
    expect(familyBackend.mergeOrder).toEqual([]);
  });
});

// Type-only import use so unused-import lint stays quiet across edits.
type _RunInputUse = RunInput;
