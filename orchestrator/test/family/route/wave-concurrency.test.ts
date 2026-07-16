/**
 * #291 B7 — the family spine fans a wave out CONCURRENTLY (Promise.allSettled),
 * preserving merge order + fail-closed semantics.
 *
 *   1. A wave's children run CONCURRENTLY: the slowest child does not gate the
 *      others' START (their single-slice runs overlap), and they all still merge.
 *   2. The serial merge stays in wave order regardless of which child FINISHED
 *      its single-slice run first (a faster child does not jump the merge queue).
 *   3. A child whose single-slice run THROWS (its own S0 fail-closed) still
 *      propagates as a runFamily rejection — concurrency does not swallow it.
 *
 * Verified zero-container: a fake single-slice Backend with controllable per-child
 * latency, a fake FamilyBackend recording merge order.
 */

import { describe, expect, it } from "vitest";
import { runFamily } from "../../../src/family/runner.js";
import type {
  Backend,
  IssueMeta,
  IssueSnapshot,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../../src/types.js";
import type {
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../../src/family/types.js";

/**
 * A single-slice Backend whose prepareWorktree latency is per-issue, and which
 * records the ORDER children entered + left their (overlapping) runs so the test
 * can prove concurrency. The slowest child is started FIRST in the wave array.
 */
class LatentChildBackend implements Backend {
  async smokeModelRoute(route: any) {
    const { smokeRouteModels } = await import("../../../src/modelRoutes.js");
    return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
  }
  active = 0;
  maxActive = 0;
  readonly enterOrder: number[] = [];
  constructor(private readonly latency: Record<number, number>) {}
  async findResumeState(): Promise<undefined> {
    return undefined;
  }
  async resumeSession(spec: StepSpec): Promise<StepOutput> {
    return this.runStep(spec);
  }
  async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
    // The latency is here (S0 metadata) so the OVERLAP window spans each child's
    // run from its very first step — proving concurrent START, not just finish.
    this.active += 1;
    this.maxActive = Math.max(this.maxActive, this.active);
    this.enterOrder.push(issueNumber);
    await new Promise((r) => setTimeout(r, this.latency[issueNumber] ?? 0));
    this.active -= 1;
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
    return { kind: "judge", status: "converged" };
  }
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

class FakeFamilyBackend implements FamilyBackend {
  async runFamilyVerify(_req?: unknown): Promise<{ ok: boolean }> {
    return { ok: true };
  }

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

describe("#291 B7 — concurrent wave fan-out", () => {
  it("runs an independent wave's children CONCURRENTLY (their runs overlap)", async () => {
    // Three independent children; the FIRST in the array is the SLOWEST. If the
    // fan-out were serial, max overlap would be 1. Concurrent ⇒ all three overlap.
    const ssb = new LatentChildBackend({ 10: 40, 11: 10, 12: 10 });
    const fb = new FakeFamilyBackend();
    const epic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 10, blockedBy: [] },
        { issue: 11, blockedBy: [] },
        { issue: 12, blockedBy: [] },
      ],
    };
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic,
      familyBackend: fb,
      singleSliceBackend: ssb,
      familyBase: "family/291-base",
    });
    // Concurrency proof: all three children were in-flight at once.
    expect(ssb.maxActive).toBe(3);
    // All merged, run succeeded.
    expect(result.status).toBe("success");
    expect(result.children.every((c) => c.status === "merged")).toBe(true);
    // The serial merge preserves WAVE (input) order, regardless of finish order:
    // 12/11 finish before 10, but 10 merges first (it is first in the wave array).
    expect(fb.mergeOrder).toEqual([10, 11, 12]);
  });

  it("a child whose single-slice S0 gate fails leaves the family incomplete", async () => {
    // 11's own S0 rejects its input (an externally-blocked child slipped to
    // runChild). S0 gate failures are now structured single-slice terminal errors,
    // so the family records that child as failed instead of seeing a raw throw.
    class ThrowingChildBackend extends LatentChildBackend {
      override async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        const meta = await super.fetchIssueMeta(issueNumber);
        return issueNumber === 11 ? { ...meta, openBlockedBy: [999] } : meta;
      }
    }
    const ssb = new ThrowingChildBackend({ 10: 5, 11: 5 });
    const fb = new FakeFamilyBackend();
    const epic: FamilyEpic = {
      issue: 291,
      children: [
        { issue: 10, blockedBy: [] },
        { issue: 11, blockedBy: [] },
      ],
    };
    const result = await runFamily({
      verifyCmr: async () => ({ ok: true, ran: true }),
      epic,
      familyBackend: fb,
      singleSliceBackend: ssb,
      familyBase: "family/291-base",
    });

    expect(result.status).toBe("incomplete");
    expect(result.children).toEqual([
      { issue: 10, status: "merged", branch: "feat/child-10" },
      { issue: 11, status: "failed", branch: undefined },
    ]);
    expect(result.stopSummary.reason).toBe("owning_issue_still_red");
    expect(result.stopSummary.summary).toContain("#11:failed");
    expect(fb.mergeOrder).toEqual([10]);
  });
});
