/**
 * family-ledger FULL schema + aborted events (ADR 0022 decision 5, #298).
 *
 * #293 recorded the thin `{childIssue, status:"merged"}`. #298 widens the writer
 * to the FULL event (childBranch / childHead / wave / familyHeadBefore /
 * familyHeadAfter) and adds `recordAborted` (a verify/cmr-failure event carrying
 * the family head at the time). The unblock predicate `mergedSet` still reads
 * `status === "merged"` only — so a reconcile補账条 (status:"merged" +
 * event:"reconciled") COUNTS, while an `aborted` event does NOT.
 *
 * Zero-IO: a fake FamilyBackend keeps the ledger in memory (no real git / file).
 */

import { describe, expect, it } from "vitest";
import { mergedSet, recordAborted, recordMerged } from "../../src/family/ledger.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../src/family/types.js";

class FakeFamilyBackend implements FamilyBackend {
  readonly appended: FamilyLedgerEntry[] = [];
  async mergeChildIntoFamilyBase(_c: MergeRequest): Promise<{ familyHead: string }> {
    return { familyHead: "head" };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.appended.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.appended;
  }
}

describe("recordMerged — full-schema event (#298)", () => {
  it("writes ALL fields when supplied (childBranch / childHead / wave / heads)", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, {
      childIssue: 10,
      childBranch: "feat/child-10",
      childHead: "c10head",
      wave: 0,
      familyHeadBefore: "base0",
      familyHeadAfter: "base1",
    });
    expect(backend.appended).toEqual([
      {
        childIssue: 10,
        status: "merged",
        childBranch: "feat/child-10",
        childHead: "c10head",
        wave: 0,
        familyHeadBefore: "base0",
        familyHeadAfter: "base1",
      },
    ]);
  });

  it("stays back-compatible: a number childIssue still writes the thin entry", async () => {
    // #293-style call (the merger before #295 fills full fields) must still work.
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, 11);
    expect(backend.appended).toEqual([{ childIssue: 11, status: "merged" }]);
  });

  it("omits undefined optional fields (no `childBranch: undefined` noise)", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, { childIssue: 12, wave: 1 });
    expect(backend.appended[0]).toEqual({ childIssue: 12, status: "merged", wave: 1 });
    expect("childBranch" in backend.appended[0]!).toBe(false);
  });
});

describe("recordAborted — verify/cmr failure event (#298)", () => {
  it("writes an aborted event carrying the family head at the time", async () => {
    const backend = new FakeFamilyBackend();
    await recordAborted(backend, { childIssue: 13, familyHeadAfter: "baseX", wave: 2 });
    expect(backend.appended).toEqual([
      { childIssue: 13, status: "aborted", familyHeadAfter: "baseX", wave: 2 },
    ]);
  });

  it("an aborted event is NOT counted as merged by the unblock predicate", async () => {
    const backend = new FakeFamilyBackend();
    await recordMerged(backend, 10);
    await recordAborted(backend, { childIssue: 11, familyHeadAfter: "baseY" });
    const set = mergedSet(await backend.readFamilyLedger());
    expect(set.has(10)).toBe(true);
    expect(set.has(11)).toBe(false); // aborted ≠ merged
  });
});

describe("mergedSet — reconcile補账条 COUNTS (decision 5 / codex R3)", () => {
  it("a status:'merged' + event:'reconciled' entry is in the merged set (no deadlock)", () => {
    const entries: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", event: "reconciled", childHead: "c10" },
      { childIssue: 11, status: "merged" },
      { childIssue: 12, status: "aborted", familyHeadAfter: "b" },
    ];
    const set = mergedSet(entries);
    // reconciled補账条 (10) counts; live merge (11) counts; aborted (12) does not.
    expect(set.has(10)).toBe(true);
    expect(set.has(11)).toBe(true);
    expect(set.has(12)).toBe(false);
  });
});
