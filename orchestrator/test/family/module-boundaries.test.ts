/**
 * Acceptance 4 (the most important): commander / merger / family-ledger /
 * verify-cmr are FOUR independent, extensible modules — later slices (#294 waves
 * / #295 conflict / #296 verify-cmr / #298 ledger) plug into THEIR module without
 * rewriting the family main loop.
 *
 * Proven two ways:
 *   1. each module is independently importable with its own public export(s) and
 *      a stable interface seam (a module boundary that exists, not inlined prose);
 *   2. the spine DELEGATES to each module rather than inlining its logic — so
 *      swapping a module's behaviour (its injected seam) changes the family run
 *      without touching the spine. This is the structural guarantee a downstream
 *      slice relies on: it grows its module, the spine is untouched.
 */

import { describe, expect, it } from "vitest";

// 1) Each module resolves as its own import with its own export(s).
import { selectWave } from "../../src/family/commander.js";
import { mergeChild } from "../../src/family/merger.js";
import { mergedSet, recordMerged } from "../../src/family/ledger.js";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
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

class ChildBackend implements Backend {
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

function epicWith(...issues: number[]): FamilyEpic {
  return { issue: 293, children: issues.map((issue) => ({ issue, blockedBy: [] })) };
}

// ════════════════════════════════════════════════════════════════════════════
// 1) Module-boundary existence: each seam is a real, independent export.
// ════════════════════════════════════════════════════════════════════════════

describe("acceptance 4 — four independent module seams", () => {
  it("commander, merger, family-ledger, verify-cmr each export their own seam", () => {
    expect(typeof selectWave).toBe("function"); // commander seam
    expect(typeof mergeChild).toBe("function"); // merger seam
    expect(typeof recordMerged).toBe("function"); // family-ledger seam (write)
    expect(typeof mergedSet).toBe("function"); // family-ledger seam (read)
    expect(typeof runVerifyCmr).toBe("function"); // verify-cmr seam
    expect(typeof runFamily).toBe("function"); // the spine that CALLS them
  });
});

// ════════════════════════════════════════════════════════════════════════════
// 2) Delegation: the spine routes through the modules' seams, not inlined logic.
//    Substituting a module's injected behaviour changes the run — proving the
//    spine does NOT carry its own copy of that logic.
// ════════════════════════════════════════════════════════════════════════════

describe("acceptance 4 — the spine delegates to (does not inline) each module", () => {
  it("merger seam: a FamilyBackend whose merge head differs flows straight through the spine", async () => {
    // If the spine inlined the merge, the family head couldn't be steered by the
    // injected merger seam. Here the seam stamps a custom head per child; the
    // spine's result must reflect it verbatim → the spine delegates to merger.
    class CustomHeadFamilyBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
        return { familyHead: `CUSTOM-${child.childIssue}` };
      }
      async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(entry);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
    }
    const familyBackend = new CustomHeadFamilyBackend();
    const result = await runFamily({
      epic: epicWith(10, 11),
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
    });
    // The injected merger seam's head is what the spine reports → no inlined merge.
    expect(result.familyHead).toBe("CUSTOM-11");
  });

  it("family-ledger seam: the commander's unblock truth is read from the ledger the merger writes", async () => {
    // Prove the commander↔ledger↔merger wiring is via the seams, not hardcoded:
    // a child blocked by another only merges AFTER the blocker's ledger entry
    // exists — i.e. the spine re-reads `mergedSet` from the ledger each wave.
    // (Two waves: 10 first, then 11 once 10 is in the ledger.)
    class RecordingFamilyBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      readonly mergeOrder: number[] = [];
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
    const familyBackend = new RecordingFamilyBackend();
    // 11 is blocked_by 10 → the commander must wait for 10's merged ledger entry.
    const epic: FamilyEpic = {
      issue: 293,
      children: [
        { issue: 10, blockedBy: [] },
        { issue: 11, blockedBy: [10] },
      ],
    };
    const result = await runFamily({
      epic,
      familyBackend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/293-base",
    });
    // 10 merges first; 11 unblocks only after 10's ledger entry — proving the
    // spine reads the merged set from the ledger seam between waves (not inlined).
    expect(familyBackend.mergeOrder).toEqual([10, 11]);
    expect(result.children.map((c) => c.issue)).toEqual([10, 11]);
    expect(result.children.every((c) => c.status === "merged")).toBe(true);
  });
});
