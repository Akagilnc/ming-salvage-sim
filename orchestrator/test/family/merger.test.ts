/**
 * merger — thin serial `git merge --no-ff` orchestrator (ADR 0022 decision 3②,
 * #293 seam 2) + verify-cmr hook (ADR 0022 decision 3④/⑥, #293 seam 4).
 *
 * #293 merger does ONLY the no-conflict path: ask the {@link FamilyBackend} seam
 * to `git merge --no-ff` a reviewed child branch into the family base, then write
 * the merged ledger entry. #295 adds the conflict fallback by extending the
 * Backend's merge impl (and the merger's handling), not the spine.
 *
 * #293 verify-cmr is a NO-OP hook: `runVerifyCmr` exists as the seam #296 fills
 * with the family verify (typecheck + unit tests) and the integrated cmr. #293
 * just proves the seam is called and returns a clean "ok" result.
 */

import { describe, expect, it } from "vitest";
import { mergeChild } from "../../src/family/merger.js";
import { runVerifyCmr } from "../../src/family/verifyCmr.js";
import type {
  FamilyBackend,
  FamilyLedgerEntry,
  MergeRequest,
} from "../../src/family/types.js";

class FakeFamilyBackend implements FamilyBackend {
  readonly merges: MergeRequest[] = [];
  readonly appended: FamilyLedgerEntry[] = [];
  private head = "base0";

  async mergeChildIntoFamilyBase(
    child: MergeRequest,
  ): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.head = `merged-${child.childIssue}`;
    return { familyHead: this.head };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.appended.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.appended;
  }
}

describe("merger.mergeChild (#293 seam 2)", () => {
  it("merges one child branch via the Backend seam and returns the new family head", async () => {
    const backend = new FakeFamilyBackend();
    const result = await mergeChild(backend, {
      childIssue: 10,
      childBranch: "feat/child-10",
    });
    expect(backend.merges).toEqual([
      { childIssue: 10, childBranch: "feat/child-10" },
    ]);
    expect(result.familyHead).toBe("merged-10");
  });

  it("records a merged ledger entry AFTER the merge lands (ADR 0022 decision 5 order)", async () => {
    const backend = new FakeFamilyBackend();
    await mergeChild(backend, { childIssue: 10, childBranch: "feat/child-10" });
    // The merged entry is written through the Backend seam.
    expect(backend.appended).toEqual([{ childIssue: 10, status: "merged" }]);
  });

  it("merges children serially in call order", async () => {
    const backend = new FakeFamilyBackend();
    await mergeChild(backend, { childIssue: 10, childBranch: "feat/child-10" });
    await mergeChild(backend, { childIssue: 11, childBranch: "feat/child-11" });
    expect(backend.merges.map((m) => m.childIssue)).toEqual([10, 11]);
    expect(backend.appended.map((e) => e.childIssue)).toEqual([10, 11]);
  });
});

describe("verify-cmr.runVerifyCmr (#293 seam 4 — no-op hook)", () => {
  it("is a no-op hook that reports ok (the #296 seam, unfilled in #293)", async () => {
    const result = await runVerifyCmr();
    expect(result).toEqual({ ok: true, ran: false });
  });
});
