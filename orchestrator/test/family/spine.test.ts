/**
 * Family spine e2e — the thinnest closure (ADR 0022 decisions 1/2/3②/6, #293).
 *
 * Acceptance criterion 1: feed a parent epic with N independent (no blocked_by)
 * ready children → ONE parallel wave is built (each child fanned out through the
 * REUSED single-slice runner) → serially merged into the family base via
 * `git merge --no-ff` → the family base contains all N children's changes.
 *
 * Verified zero-container: a fake single-slice Backend drives each child run to
 * S8(success), and a fake FamilyBackend records the merges + ledger writes. No
 * real git, no container — the same form as runner.happy-path / merge-seam.
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

// ─── fakes ────────────────────────────────────────────────────────────────────

/** A single-slice Backend that drives every child to S8(success). */
class ChildBackend implements Backend {
  readonly prepareBases: string[] = [];
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
      hasAgentBrief: true,
      hasSubIssues: false,
      openBlockedBy: [],
    };
  }
  async fetchIssueSnapshot(issueNumber: number): Promise<IssueSnapshot> {
    return { number: issueNumber, body: "b", comments: [], agentBrief: "## Agent Brief" };
  }
  async prepareWorktree(issueNumber: number, base: string): Promise<WorktreeHandle> {
    this.prepareBases.push(base);
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

/** A FamilyBackend that records merges + ledger writes (the "family base" model). */
class FakeFamilyBackend implements FamilyBackend {
  readonly merges: MergeRequest[] = [];
  readonly ledger: FamilyLedgerEntry[] = [];
  private head = "family-base-0";
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.head = `+${child.childIssue}`;
    return { familyHead: this.head };
  }
  // #295 conflict-fallback seam: these spine tests use the deterministic
  // (no-conflict) merge path, so the LLM resolver is never reached. Stub it so
  // the fake still satisfies FamilyBackend; a call would mean an unexpected
  // conflict in a clean-path test.
  async resolveMergeConflict(): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this no-conflict test");
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
}

function epicWith(...childIssues: number[]): FamilyEpic {
  return {
    issue: 293,
    children: childIssues.map((issue) => ({ issue, blockedBy: [] })),
  };
}

// ─── acceptance 1 ───────────────────────────────────────────────────────────

describe("runFamily — thinnest e2e (#293 acceptance 1)", () => {
  it("N independent children → one wave built → serially merged into family base", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();

    const result = await runFamily({
      epic: epicWith(10, 11, 12),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    // All three children merged, in wave (input) order.
    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([10, 11, 12]);
    // Each merge carried the child's reviewed branch.
    expect(familyBackend.merges.map((m) => m.childBranch)).toEqual([
      "feat/child-10",
      "feat/child-11",
      "feat/child-12",
    ]);
    // The family base accumulated all three (last merge head reflects #12).
    expect(result.familyHead).toBe("+12");
    expect(result.children.map((c) => c.status)).toEqual([
      "merged",
      "merged",
      "merged",
    ]);
    // A complete clean run is observably "success" (#293 no-op verify passes).
    expect(result.status).toBe("success");
  });

  it("each child is cut from the FAMILY base (not main) and does NOT push remotely", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();

    await runFamily({
      epic: epicWith(10, 11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    // Children cut from the family base.
    expect(singleSliceBackend.prepareBases).toEqual([
      "family/293-base",
      "family/293-base",
    ]);
    // S7 no-op: no remote push from any child.
    expect(singleSliceBackend.pushCount).toBe(0);
  });

  it("family ledger records each merged child append-only (#293 acceptance 3)", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();

    await runFamily({
      epic: epicWith(10, 11, 12),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(familyBackend.ledger).toEqual([
      { childIssue: 10, status: "merged" },
      { childIssue: 11, status: "merged" },
      { childIssue: 12, status: "merged" },
    ]);
  });

  it("a single-child epic still closes the loop (degenerate wave)", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(familyBackend.merges.map((m) => m.childIssue)).toEqual([10]);
    expect(result.children).toEqual([
      { issue: 10, status: "merged", branch: "feat/child-10" },
    ]);
  });
});

// ─── acceptance 2 ───────────────────────────────────────────────────────────

describe("runFamily — family entry accepts the epic; each child passes its OWN gate (#293 acceptance 2)", () => {
  it("the parent epic (which HAS sub-issues) is accepted — NOT rejected by the single-slice 'no sub-issues' rule", async () => {
    // The single-slice S0 gate rejects an issue WITH sub-issues. The family entry
    // reverses that for the EPIC: it never feeds the epic through single-slice S0
    // — it fans out the leaf children. So an epic with children runs fine; each
    // child (a leaf, hasSubIssues:false) passes its OWN S0 gate.
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();

    const result = await runFamily({
      epic: epicWith(10, 11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(result.children.map((c) => c.status)).toEqual(["merged", "merged"]);
  });

  it("a child that FAILS its own S0 rfa/Agent-Brief gate makes the whole family run REJECT (gate throw propagates), not a fabricated merge", async () => {
    // One child is not ready-for-agent → its single-slice S0 gate THROWS (a caller
    // input fault, same as the single-slice contract — not converted to a returned
    // "failed" RunResult). #293 thinnest: the spine does not catch that throw, so it
    // propagates out and the whole runFamily rejects. The spine never fabricates a
    // partial merge for the bad child. (A child that fails LATER — e.g. review never
    // approves — returns a non-success RunResult and IS recorded "failed"; only S0
    // gate violations throw. Catching gate throws into a per-child "failed" is a
    // downstream choice, not #293.)
    class GateRejectChildBackend extends ChildBackend {
      override async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        // Child 11 is NOT ready-for-agent (isReadyForAgent:false) → its S0 gate
        // throws on the rfa check. (It DOES have an Agent Brief — the rfa gate is
        // the one that fires; the assertion below matches /ready-for-agent/i.)
        return {
          number: issueNumber,
          isReadyForAgent: issueNumber !== 11,
          hasAgentBrief: true,
          hasSubIssues: false,
          openBlockedBy: [],
        };
      }
    }
    const singleSliceBackend = new GateRejectChildBackend();
    const familyBackend = new FakeFamilyBackend();

    // Child 11's gate throws inside runOrchestrator. #293 thinnest: the spine
    // lets that S0-gate throw propagate (it is a caller input fault, same as the
    // single-slice contract — a malformed wave is not silently swallowed). The
    // family run rejects rather than fabricating a partial merge.
    await expect(
      runFamily({
        epic: epicWith(10, 11),
        familyBackend,
        singleSliceBackend,
        familyBase: "family/293-base",
      }),
    ).rejects.toThrow(/ready-for-agent/i);
  });
});
