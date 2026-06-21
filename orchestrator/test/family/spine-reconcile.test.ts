/**
 * Spine ⨉ crash-window reconcile wiring (ADR 0022 decision 5, #298 acceptance 2).
 *
 * The spine's resume ENTRY runs reconcile BEFORE the wave loop, given an injected
 * `reconcileGit` seam. Reconcile is APPEND-ONLY into the spine: it does NOT touch
 * the wave-loop structure. Its effect lands purely by APPENDING reconcile補账条
 * to the ledger — which `currentMerged` (read fresh each wave) then picks up, so
 * an already-merged / reconciled child is skipped (no double-merge) and a
 * never-merged child is re-run by the existing wave loop (no漏合).
 *
 * Three observable outcomes, all zero-container:
 *   - branch ② ancestor-confirmed → a reconciled child is NOT re-merged (its
 *     mergeChildIntoFamilyBase is never called again); the remaining child runs.
 *   - branch ② childHead absent → the child is re-run from scratch (no error).
 *   - branch ③ inconsistent → the run returns `status:"escalated"` (fail-closed),
 *     does NOT proceed to merge.
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
  ReconcileGit,
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
      hasAgentBrief: true,
      hasSubIssues: false,
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

/** A FamilyBackend pre-seeded with a ledger (the prior, crashed run's residue). */
class SeededFamilyBackend implements FamilyBackend {
  readonly merges: MergeRequest[] = [];
  readonly ledger: FamilyLedgerEntry[];
  constructor(seed: FamilyLedgerEntry[]) {
    this.ledger = [...seed];
  }
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

class FakeReconcileGit implements ReconcileGit {
  constructor(
    private readonly live: string,
    private readonly heads: Record<number, string>,
    private readonly ancestors: ReadonlySet<string>,
    // The family base head before any child merged. Defaults to `live` (a fresh
    // resume: nothing landed → start === live → clean start). These spine tests
    // all seed a NON-empty ledger, so reconcile never reaches the empty-ledger
    // start-head check — the default keeps them on their existing branch.
    private readonly start: string = live,
  ) {}
  async liveFamilyHead(): Promise<string> {
    return this.live;
  }
  async familyBaseStartHead(): Promise<string> {
    return this.start;
  }
  async childHeadExists(childIssue: number): Promise<{ exists: boolean; childHead?: string }> {
    const head = this.heads[childIssue];
    return head === undefined ? { exists: false } : { exists: true, childHead: head };
  }
  async isAncestor(childHead: string, liveHead: string): Promise<boolean> {
    return liveHead === this.live && this.ancestors.has(childHead);
  }
}

const epic: FamilyEpic = {
  issue: 291,
  children: [
    { issue: 10, blockedBy: [] },
    { issue: 11, blockedBy: [] },
  ],
};

describe("spine reconcile — branch ② ancestor-confirmed (no double-merge)", () => {
  it("a merge that landed but was unwritten is补 reconciled, NOT re-merged; the other child runs", async () => {
    // Prior run: 10 merged (ledger written), then 11 merged but CRASHED before its
    // `merged` write. Live HEAD=base2, c11 is an ancestor (11's merge landed).
    const familyBackend = new SeededFamilyBackend([
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ]);
    const childBackend = new ChildBackend();
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
      reconcileGit: new FakeReconcileGit(
        "base2",
        { 10: "c10", 11: "c11" },
        new Set(["base1", "c10", "c11"]),
      ),
    });

    // 11 was reconciled — NEVER re-merged (no double-merge) and NEVER re-run.
    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([]);
    expect(childBackend.ran).toEqual([]);
    // A reconciled補账条 for 11 was appended (status:"merged" + event:"reconciled").
    expect(
      familyBackend.ledger.find((e) => e.childIssue === 11 && e.event === "reconciled"),
    ).toMatchObject({ childIssue: 11, status: "merged", event: "reconciled", childHead: "c11" });
    // Both children end merged → success.
    expect(result.status).toBe("success");
    expect(result.children.every((c) => c.status === "merged")).toBe(true);
  });
});

describe("spine reconcile — branch ② childHead absent (rerun, no error)", () => {
  it("a child that crashed before any commit is re-run from scratch, no error", async () => {
    // Prior run: 10 merged. 11 crashed before any commit → childHead absent.
    const familyBackend = new SeededFamilyBackend([
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ]);
    const childBackend = new ChildBackend();
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
      reconcileGit: new FakeReconcileGit(
        "base2",
        { 10: "c10" }, // 11 absent
        new Set(["base1", "c10"]),
      ),
    });

    // 11 is re-run from scratch (not reconciled), then merged. 10 is NOT re-run
    // (already merged in the ledger).
    expect(childBackend.ran).toEqual([11]);
    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([11]);
    expect(result.status).toBe("success");
  });
});

describe("spine reconcile — append-loop crash idempotency (no double-merge mid-reconcile)", () => {
  it("only the LAST reconcile補账条 advances the baseline, so a mid-loop crash re-reconciles safely", async () => {
    // Two crash-window children (11, 12) both LANDED (live HEAD=base2, both
    // ancestors) but their `merged` writes crashed. Reconcile补账s BOTH. If EVERY
    // 補账条 stamped `familyHeadAfter: liveHead`, a crash AFTER writing 11 but
    // BEFORE 12 would leave the ledger末条 = {11, familyHeadAfter: base2}; the next
    // resume's `lastRecordedHead` returns base2 === live → branch ① → trusts the
    // INCOMPLETE merged set (11 only) → 12 (already landed) gets re-run + re-merged
    // = double-merge (cmr R2: agy). Guard: only the LAST補账条 carries
    // `familyHeadAfter`; the intermediate ones omit it, so a mid-loop-crash residue
    // falls back to the PRIOR real baseline (base1), live still leads → branch ②
    // re-reconciles 12 idempotently (11 already status:merged → skipped).
    const epic3: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 10, blockedBy: [] },
        { issue: 11, blockedBy: [] },
        { issue: 12, blockedBy: [] },
      ],
    };
    const familyBackend = new SeededFamilyBackend([
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ]);
    const childBackend = new ChildBackend();
    const result = await runFamily({
      epic: epic3,
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
      reconcileGit: new FakeReconcileGit(
        "base2",
        { 10: "c10", 11: "c11", 12: "c12" },
        new Set(["base1", "c10", "c11", "c12"]),
      ),
    });

    // Both 11 and 12 are reconciled (补账), NEVER re-merged or re-run.
    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([]);
    expect(childBackend.ran).toEqual([]);
    const recon = familyBackend.ledger.filter((e) => e.event === "reconciled");
    expect(recon.map((e) => e.childIssue)).toEqual([11, 12]);
    // The write-shape guard: the INTERMEDIATE補账条 (11) carries NO familyHeadAfter
    // (so a crash after it falls back to the prior baseline), only the LAST (12)
    // advances the baseline to the verified live HEAD.
    expect(recon.find((e) => e.childIssue === 11)?.familyHeadAfter).toBeUndefined();
    expect(recon.find((e) => e.childIssue === 12)?.familyHeadAfter).toBe("base2");
    expect(result.status).toBe("success");
  });
});

describe("spine reconcile — branch ③ inconsistent (fail-closed escalate)", () => {
  it("an inconsistent live HEAD returns status:'escalated' and does NOT merge", async () => {
    const familyBackend = new SeededFamilyBackend([
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ]);
    const childBackend = new ChildBackend();
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
      // live HEAD "rogue": base1 is NOT an ancestor of it (diverged) → escalate.
      reconcileGit: new FakeReconcileGit("rogue", { 10: "c10" }, new Set()),
    });

    expect(result.status).toBe("escalated");
    // Fail-closed: no child run, no merge attempted.
    expect(childBackend.ran).toEqual([]);
    expect(familyBackend.merges).toEqual([]);
  });
});

describe("spine reconcile — no reconcileGit (fresh run unchanged)", () => {
  it("without a reconcileGit seam, the spine behaves exactly as #293 (no reconcile)", async () => {
    const familyBackend = new SeededFamilyBackend([]);
    const childBackend = new ChildBackend();
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: childBackend,
      familyBase: "family/291-base",
    });
    expect(result.status).toBe("success");
    expect(childBackend.ran.sort()).toEqual([10, 11]);
  });
});
