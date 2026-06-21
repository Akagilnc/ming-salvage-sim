/**
 * Crash-window reconcile (ADR 0022 decision 5, #298 acceptance 2).
 *
 * On resume the family run reconciles the ledger against the live family-base
 * HEAD BEFORE continuing, so a crash in the merge-then-write window neither
 * double-merges nor drops a merge. The three branches ADR 0022 decision 5 names:
 *
 *   ① ledger末条 familyHeadAfter === live HEAD  → trust the merged set, skip
 *      already-merged, continue (no補账, no escalate).
 *   ② live HEAD LEADS the ledger (merge landed, the `merged` write crashed — the
 *      common window): for each not-yet-accounted child,
 *        - childHead EXISTS and `git merge-base --is-ancestor childHead liveHEAD`
 *          → its merge LANDED → 补 a `status:"merged"` + `event:"reconciled"`
 *          entry (so the unblock predicate counts it — codex R3) and treat as
 *          merged;
 *        - childHead/branch does NOT exist (crashed before any child commit) →
 *          skip merge-base, treat as UNMERGED (rerun from scratch), no error;
 *        - childHead exists but is NOT an ancestor of liveHEAD → genuinely
 *          unmerged → rerun (normal, not corruption).
 *   ③ live HEAD is NOT consistent with the ledger末条 (diverged / behind /
 *      unrelated — neither equal nor a descendant) → fail-closed escalate.
 *
 * Family reconcile is WIDER than the single-slice `checkBranchHeadConsistency`
 * "mismatch → abort": branch ② does NOT abort, it补账 + continues — that is the
 * "幂等续合" the family layer needs.
 *
 * Zero-container: a fake ReconcileGit injects each scenario (live HEAD,
 * childHead existence, ancestor result) — no real git, no killed process.
 */

import { describe, expect, it } from "vitest";
import { reconcileFamilyLedger } from "../../src/family/reconcile.js";
import type {
  FamilyLedgerEntry,
  ReconcileGit,
} from "../../src/family/types.js";

/**
 * A scriptable ReconcileGit fake. `live` is the live family-base HEAD; `heads`
 * maps a child issue → its branch HEAD (absent ⇒ branch/childHead does not
 * exist); `ancestors` is the set of child HEADs that ARE ancestors of `live`.
 */
class FakeReconcileGit implements ReconcileGit {
  constructor(
    private readonly live: string,
    private readonly heads: Record<number, string>,
    private readonly ancestors: ReadonlySet<string>,
  ) {}
  async liveFamilyHead(): Promise<string> {
    return this.live;
  }
  async childHeadExists(
    childIssue: number,
  ): Promise<{ exists: boolean; childHead?: string }> {
    const head = this.heads[childIssue];
    return head === undefined ? { exists: false } : { exists: true, childHead: head };
  }
  async isAncestor(childHead: string, liveHead: string): Promise<boolean> {
    return liveHead === this.live && this.ancestors.has(childHead);
  }
}

const children = [
  { issue: 10, blockedBy: [] as number[] },
  { issue: 11, blockedBy: [] as number[] },
];

describe("reconcileFamilyLedger — branch ① ledger末条 === live HEAD", () => {
  it("trusts the merged set, plans no補账, no escalate", async () => {
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ];
    const git = new FakeReconcileGit("base1", { 10: "c10" }, new Set(["c10"]));
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([]); // nothing to补
    expect([...plan.merged].sort()).toEqual([10]); // 10 already merged
  });
});

describe("reconcileFamilyLedger — branch ② live HEAD LEADS (the crash window)", () => {
  it("ancestor confirmed → 补 a reconciled (status:'merged') entry, counted merged, no double-merge", async () => {
    // Ledger末条 says base1 (after 10). But 11's merge LANDED (live HEAD=base2,
    // c11 is an ancestor) and crashed before the `merged` write.
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ];
    const git = new FakeReconcileGit(
      "base2",
      { 10: "c10", 11: "c11" },
      // ancestors of live HEAD base2: the baseline base1 (so live LEADS — branch
      // ②) plus c10, c11 (both merges landed on the base1→base2 chain).
      new Set(["base1", "c10", "c11"]),
    );
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(false);
    // 11 is补 a reconciled entry (status:"merged", event:"reconciled").
    expect(plan.reconciled).toEqual([
      { childIssue: 11, childHead: "c11" },
    ]);
    // Both count as merged now (10 from ledger, 11 from reconcile) — 11 will NOT
    // be re-merged (no double-merge).
    expect([...plan.merged].sort()).toEqual([10, 11]);
  });

  it("childHead does NOT exist → skip merge-base, treat as UNMERGED (rerun), no error", async () => {
    // 11 crashed before ANY of its commits → branch/childHead absent.
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ];
    const git = new FakeReconcileGit(
      "base2",
      { 10: "c10" }, // 11 absent
      new Set(["base1", "c10"]), // base1 is an ancestor of base2 → live LEADS (branch ②)
    );
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([]); // 11 not补 — it never merged
    expect([...plan.merged].sort()).toEqual([10]); // only 10
    // 11 stays unmerged → the wave loop reruns it from scratch (selectWave picks
    // it because it is not in `merged`). No error, no abort.
  });

  it("childHead EXISTS but is NOT an ancestor → genuinely unmerged, rerun (no补, no escalate)", async () => {
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ];
    // 11's branch has commits (c11 exists) but its merge never landed (not an
    // ancestor of live HEAD base2). Normal: rerun, not corruption.
    const git = new FakeReconcileGit(
      "base2",
      { 10: "c10", 11: "c11" },
      new Set(["base1", "c10"]), // base1 ancestor → live LEADS; c11 NOT an ancestor
    );
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([]); // 11 not补
    expect([...plan.merged].sort()).toEqual([10]);
  });
});

describe("reconcileFamilyLedger — branch ③ inconsistent → fail-closed escalate", () => {
  it("live HEAD is neither equal NOR a descendant of ledger末条 → escalate", async () => {
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ];
    // live HEAD = "rogue" — base1 is NOT an ancestor of it (diverged history).
    const git = new FakeReconcileGit("rogue", { 10: "c10" }, new Set()); // base1 not ancestor of rogue
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(true);
  });
});

describe("reconcileFamilyLedger — thin (#293-style) entries degrade SAFELY", () => {
  it("a thin merged entry (no familyHeadAfter) → conservative clean-start, no escalate, no double-merge", async () => {
    // If the happy-path merge wrote only the thin {childIssue, status:"merged"}
    // (no familyHeadAfter baseline), reconcile cannot compute the crash window —
    // it must DEGRADE SAFELY: no escalate (not corruption), and the already-merged
    // child is still counted merged (so it is NOT re-run / re-merged). A
    // never-recorded child is simply left to the wave loop. No corruption either
    // way.
    const ledger: FamilyLedgerEntry[] = [{ childIssue: 10, status: "merged" }];
    const git = new FakeReconcileGit("base1", { 10: "c10" }, new Set(["c10"]));
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([]);
    // 10 is still counted merged (from the thin ledger entry) → not double-merged.
    expect([...plan.merged].sort()).toEqual([10]);
  });
});

describe("reconcileFamilyLedger — empty ledger (fresh resume)", () => {
  it("an empty ledger is not a crash window: nothing merged, nothing to escalate", async () => {
    // Nothing recorded yet — live HEAD is just the family base itself; treat as a
    // clean start (no merges to reconcile).
    const git = new FakeReconcileGit("base0", {}, new Set());
    const plan = await reconcileFamilyLedger([], children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([]);
    expect(plan.merged.size).toBe(0);
  });
});
