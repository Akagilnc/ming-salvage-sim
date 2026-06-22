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
  ): Promise<{
    familyHead: string;
    familyHeadBefore: string;
    childHead: string;
  }> {
    this.merges.push(child);
    const before = this.head;
    this.head = `merged-${child.childIssue}`;
    // The Backend (which runs the real `git merge --no-ff`) is the only place
    // that knows the actual SHAs the ledger must record (#298 acceptance-1):
    // the family base HEAD before this merge, the child branch HEAD it merged,
    // and the family base HEAD after.
    return {
      familyHead: this.head,
      familyHeadBefore: before,
      childHead: `child-head-${child.childIssue}`,
    };
  }
  // #295 conflict-fallback seam `resolveMergeConflict` is OPTIONAL — this #293
  // no-conflict test merges cleanly and never reaches it (the conflict path has
  // its own coverage in merger-conflict.test.ts), so the fake omits it.
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

  it("records a FULL-field merged ledger entry AFTER the merge lands (ADR 0022 decision 5 order + #298 acceptance-1)", async () => {
    const backend = new FakeFamilyBackend();
    await mergeChild(backend, { childIssue: 10, childBranch: "feat/child-10" });
    // #298 acceptance-1: "每合一片即写一条 {childIssue, childBranch, childHead,
    // ..., familyHeadBefore, familyHeadAfter, status}". The OLD thin
    // {childIssue, status:"merged"} write (cmr R1: codex-s1 + agy) left the
    // ledger末条 WITHOUT a `familyHeadAfter` baseline → reconcile's branch ② (补账)
    // was UNREACHABLE in production → a crash-window child got RE-merged (a
    // double-merge, violating acceptance-2 "不双合"). The merger now forwards the
    // full fields the Backend reports (childHead / familyHeadBefore / familyHeadAfter).
    expect(backend.appended).toEqual([
      {
        childIssue: 10,
        status: "merged",
        childBranch: "feat/child-10",
        childHead: "child-head-10",
        familyHeadBefore: "base0",
        familyHeadAfter: "merged-10",
      },
    ]);
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
  it("is a no-op hook that reports ok at BOTH phases (the #296 seam, unfilled in #293)", async () => {
    const backend = new FakeFamilyBackend();
    // The seam takes the phase + context #296 needs (familyBase + familyBackend);
    // #293 ignores it and returns ok:true, ran:false at both the wave barrier and
    // the end-of-run barrier.
    const wave = await runVerifyCmr({
      phase: "wave",
      familyBase: "family/293-base",
      familyBackend: backend,
    });
    expect(wave).toEqual({ ok: true, ran: false });
    const final = await runVerifyCmr({
      phase: "final",
      familyBase: "family/293-base",
      familyBackend: backend,
    });
    expect(final).toEqual({ ok: true, ran: false });
  });
});
