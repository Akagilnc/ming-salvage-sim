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
    // The family base head BEFORE any child merged. Defaults to `live` so a
    // fresh resume (nothing landed) reads start === live → clean start; the
    // empty-ledger-first-merge-crash scenario passes a DIFFERENT start (live
    // moved past it with an empty ledger → fail-closed escalate).
    private readonly start: string = live,
  ) {}
  async liveFamilyHead(): Promise<string> {
    return this.live;
  }
  async familyBaseStartHead(): Promise<string> {
    return this.start;
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

  it("does NOT blindly trust a HEADLESS reconciled tail entry past the baseline if the base was rewound → escalate (no漏合)", async () => {
    // The R2 mid-append crash residue: an intermediate reconcile補账条 (11) carries
    // a childHead but NO familyHeadAfter (only the LAST補账条 advances the baseline),
    // sitting AFTER the baseline-bearing entry (10, familyHeadAfter:base1). If the
    // family base is then EXTERNALLY rewound to base1 (c11 no longer in live
    // history), lastRecordedHead skips 11 (no head) → returns base1 → baseline ===
    // liveHead → branch ①. Blindly returning mergedSet={10,11} would count 11 as
    // merged though its merge is GONE → 漏合 (the wave loop skips it). Branch ① must
    // re-verify each HEADLESS merged tail entry's childHead is still an ancestor of
    // live; 11's c11 is NOT an ancestor of the rewound base1 → fail-closed escalate
    // (cmr R6: codex-s1). Acceptance-2 不漏合.
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
      { childIssue: 11, status: "merged", event: "reconciled", childHead: "c11" }, // no familyHeadAfter
    ];
    // live HEAD rewound to base1; c11 is NOT an ancestor of base1 (its merge is gone).
    const git = new FakeReconcileGit("base1", { 10: "c10", 11: "c11" }, new Set(["c10"]));
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(true);
  });

  it("escalates when a HEADLESS merged tail entry has NO childHead (unverifiable) → fail-closed", async () => {
    // Defensive branch (cmr R7: agy): a headless `status:"merged"` tail entry past
    // the baseline that carries NO childHead cannot be re-verified against live at
    // all. Branch ① must NOT trust it (that would risk漏合) — fail-closed escalate.
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
      { childIssue: 11, status: "merged", event: "reconciled" }, // headless AND no childHead
    ];
    const git = new FakeReconcileGit("base1", { 10: "c10" }, new Set(["c10"]));
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(true);
  });

  it("trusts a HEADLESS reconciled tail entry when its childHead IS still an ancestor of live (normal branch ①)", async () => {
    // Same shape, but the base was NOT rewound — c11 IS still an ancestor of the
    // live base1 (the intermediate補账条's merge is intact). Branch ① re-verifies
    // and finds it landed → trust the merged set, no escalate (the R2 mid-append
    // crash, then a clean resume where live still contains 11).
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
      { childIssue: 11, status: "merged", event: "reconciled", childHead: "c11" },
    ];
    const git = new FakeReconcileGit("base1", { 10: "c10", 11: "c11" }, new Set(["c10", "c11"]));
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(false);
    expect([...plan.merged].sort()).toEqual([10, 11]);
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
    // The plan carries the VERIFIED live HEAD, so the caller can stamp the
    // reconcile補账条 with `familyHeadAfter: liveHead` — else `lastRecordedHead`
    // on the NEXT resume returns the STALE pre-reconcile baseline and a later
    // rewind that should branch-③ escalate is silently trusted (cmr R1: codex
    // + agy, the missing-familyHeadAfter stale-baseline defect).
    expect(plan.liveHead).toBe("base2");
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
  it("a bare thin ledger row without childHead does not explain a live HEAD advance → fail-closed escalate", async () => {
    // A bare #293 thin row records child 10 as merged but carries neither
    // familyHeadAfter nor childHead. If the live family base moved past the start
    // head and no unrecorded child is reconciled, the row is not verifiable
    // evidence for what advanced the base. Fail closed instead of treating any
    // accounting row as enough to suppress the start-head safety net.
    const ledger: FamilyLedgerEntry[] = [{ childIssue: 10, status: "merged" }];
    const git = new FakeReconcileGit("base1", { 10: "c10" }, new Set(["base0", "c10"]), "base0");
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
    expect([...plan.merged].sort()).toEqual([10]);
  });

  it("a bare thin ledger row is not trusted even when live HEAD still equals the start head", async () => {
    // If nothing moved on the family base, a headless merged row without childHead
    // is not evidence that the child is actually present. Trusting it would let
    // the wave loop skip child 10 on an incomplete base.
    const ledger: FamilyLedgerEntry[] = [{ childIssue: 10, status: "merged" }];
    const git = new FakeReconcileGit("base0", { 10: "c10" }, new Set(["base0"]), "base0");
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
    expect([...plan.merged].sort()).toEqual([10]);
  });

  it("a headless accounting row with childHead can explain the live HEAD advance when verified", async () => {
    // A headless merged entry that carries childHead can be verified directly:
    // child 10's head is still an ancestor of the live family base, so the live
    // advance is attributable to an already-accounted child. No补账 and no
    // double-merge are needed.
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10" },
    ];
    const git = new FakeReconcileGit("base1", { 10: "c10" }, new Set(["base0", "c10"]), "base0");
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([]);
    expect([...plan.merged].sort()).toEqual([10]);
  });

  it("a verified headless row does not launder a separate bare thin row", async () => {
    // Child 11's row is verifiable, but child 10's bare thin row has no childHead.
    // The verified row explains its own merge only; it must not make every other
    // headless accounting row safe to trust when live moved past the start head.
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged" },
      { childIssue: 11, status: "merged", childHead: "c11" },
    ];
    const git = new FakeReconcileGit(
      "base2",
      { 10: "c10", 11: "c11" },
      new Set(["base0", "c11"]),
      "base0",
    );
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
    expect([...plan.merged].sort()).toEqual([10, 11]);
  });

  it("a verified headless ledger where an UNRECORDED child already landed →补账 it, NOT escalate, NOT double-merge", async () => {
    // A headless ledger records child 10 without a familyHeadAfter, but it carries
    // childHead and that head is still an ancestor of live. Then child 11's merge
    // landed but its ledger write crashed. Reconcile verifies the existing row and
    // 补账s only the unrecorded landed child.
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10" },
    ];
    const git = new FakeReconcileGit(
      "base2",
      { 10: "c10", 11: "c11" },
      new Set(["base0", "c10", "c11"]),
      "base0",
    );
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([{ childIssue: 11, childHead: "c11" }]);
    expect([...plan.merged].sort()).toEqual([10, 11]);
  });

  it("phase-only escalation and answer rows do not bypass the start-head safety net", async () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "escalated",
        event: "escalated",
        escalationKind: "decision",
        reason: "legacy cmr pause",
      },
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "continue",
      },
    ];
    const git = new FakeReconcileGit(
      "base1",
      {},
      new Set(["base0"]),
      "base0",
    );

    const plan = await reconcileFamilyLedger(ledger, children, git);

    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
    expect(plan.merged.size).toBe(0);
  });

  it("malformed merged rows without a childIssue do not count as accounting evidence", async () => {
    const ledger: FamilyLedgerEntry[] = [
      {
        status: "merged",
      },
    ];
    const git = new FakeReconcileGit(
      "base1",
      {},
      new Set(["base0"]),
      "base0",
    );

    const plan = await reconcileFamilyLedger(ledger, children, git);

    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
    expect(plan.merged.size).toBe(0);
  });

  it("malformed merged rows with non-numeric childIssue do not count as accounting evidence", async () => {
    const ledger = [
      {
        status: "merged",
        childIssue: null,
      },
      {
        status: "merged",
        childIssue: "10",
      },
    ] as unknown as FamilyLedgerEntry[];
    const git = new FakeReconcileGit(
      "base1",
      {},
      new Set(["base0"]),
      "base0",
    );

    const plan = await reconcileFamilyLedger(ledger, children, git);

    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
    expect(plan.merged.size).toBe(0);
  });
});

describe("reconcileFamilyLedger — empty ledger (fresh resume)", () => {
  it("an empty ledger with live HEAD AT the base start is not a crash window: clean start", async () => {
    // Nothing recorded yet AND the live family-base HEAD is still the start head
    // (no merge landed) — a genuine fresh start, nothing to reconcile.
    const git = new FakeReconcileGit("base0", {}, new Set()); // start defaults to live
    const plan = await reconcileFamilyLedger([], children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([]);
    expect(plan.merged.size).toBe(0);
  });

  it("an empty ledger does not reconcile a zero-commit child branch whose HEAD is the base start", async () => {
    // A child branch can exist immediately after prepareWorktree but before the
    // coder commits. Its HEAD equals the family base start, which is technically
    // an ancestor of live but is not evidence that the child landed.
    const git = new FakeReconcileGit(
      "base0",
      { 10: "base0" },
      new Set(["base0"]),
      "base0",
    );
    const plan = await reconcileFamilyLedger([], children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([]);
    expect(plan.merged.size).toBe(0);
  });

  it("an empty ledger + first merge LANDED (childHead ancestor of live) →补账 it, no escalate (first-merge crash recovered)", async () => {
    // The crash window can hit the VERY FIRST merge: mergeChild lands the merge
    // on the family base THEN writes the ledger. A crash in between leaves the
    // ledger EMPTY while the family base HAS moved. The per-child reconcile loop
    // runs for the headless ledger too (cmr R5), so if the landed child's head is
    // an ancestor of live we CAN attribute the move and补账 it — NO double-merge,
    // NO needless escalate. Here child 10 landed (c10 ancestor of live base1).
    const git = new FakeReconcileGit(
      "base1", // live HEAD has moved past the base start...
      { 10: "c10" },
      new Set(["base0", "c10"]), // ...because child 10's merge (c10) landed
      "base0",
    );
    const plan = await reconcileFamilyLedger([], children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([{ childIssue: 10, childHead: "c10" }]);
    expect([...plan.merged].sort()).toEqual([10]);
  });

  it("an empty ledger only reconciles landed children when another child branch still points at the base start", async () => {
    // Child 10 exists but has no commits beyond the cut SHA. Child 11 landed and
    // advanced live. Reconcile must补账 only child 11 and leave child 10 for the
    // wave loop rather than marking both merged because both heads are ancestors.
    const git = new FakeReconcileGit(
      "base1",
      { 10: "base0", 11: "c11" },
      new Set(["base0", "c11"]),
      "base0",
    );
    const plan = await reconcileFamilyLedger([], children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([{ childIssue: 11, childHead: "c11" }]);
    expect([...plan.merged].sort()).toEqual([11]);
  });

  it("an empty ledger + live MOVED but NO child explains it → fail-closed escalate (unattributable landed merge)", async () => {
    // The base moved past its start head, but NO known child's head is an ancestor
    // of live (here child 10's branch doesn't even exist, child 11's neither) — a
    // merge landed that we cannot attribute to any epic child. With nothing to补账
    // and an empty ledger, fail-closed escalate (decision 5 真有未落/不一致 → 升级)
    // rather than silently proceed (which would let the wave loop re-run children
    // onto a base that already contains an unknown merge). This is the safety net
    // gated on ledger.length === 0 + nothing reconciled.
    const git = new FakeReconcileGit(
      "base1", // live moved past start base0...
      {}, // ...but no child branch exists to attribute it to
      new Set(["base0"]),
      "base0",
    );
    const plan = await reconcileFamilyLedger([], children, git);
    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
  });

  it("does not trust a malformed headless merged tail after a valid baseline", async () => {
    const ledger = [
      {
        status: "aborted",
        event: "aborted",
        phase: "final",
        reason: "previous barrier failed",
        familyHeadAfter: "base1",
      },
      {
        status: "merged",
        childHead: "c10",
      },
    ] as unknown as FamilyLedgerEntry[];
    const git = new FakeReconcileGit("base1", { 10: "c10" }, new Set(["c10"]));

    const plan = await reconcileFamilyLedger(ledger, children, git);

    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
  });

  it("does not trust a malformed merged row with familyHeadAfter as a baseline", async () => {
    const ledger = [
      {
        status: "merged",
        childIssue: null,
        familyHeadAfter: "base1",
      },
    ] as unknown as FamilyLedgerEntry[];
    const git = new FakeReconcileGit("base1", {}, new Set(["base0"]), "base0");

    const plan = await reconcileFamilyLedger(ledger, children, git);

    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
    expect(plan.merged.size).toBe(0);
  });

  it("does not trust phase-only answer rows with familyHeadAfter as a baseline", async () => {
    const ledger = [
      {
        status: "escalation_answered",
        event: "escalation_answered",
        phase: "final",
        answer: "continue",
        familyHeadAfter: "base1",
      },
    ] as unknown as FamilyLedgerEntry[];
    const git = new FakeReconcileGit("base1", {}, new Set(["base0"]), "base0");

    const plan = await reconcileFamilyLedger(ledger, children, git);

    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
    expect(plan.merged.size).toBe(0);
  });

  it("does not trust escalated rows missing phase as a baseline", async () => {
    const ledger = [
      {
        status: "escalated",
        event: "escalated",
        escalationKind: "decision",
        familyHeadAfter: "base1",
      },
    ] as unknown as FamilyLedgerEntry[];
    const git = new FakeReconcileGit("base1", {}, new Set(["base0"]), "base0");

    const plan = await reconcileFamilyLedger(ledger, children, git);

    expect(plan.escalate).toBe(true);
    expect(plan.reconciled).toEqual([]);
    expect(plan.merged.size).toBe(0);
  });
});

describe("reconcileFamilyLedger — full-field merged entries reach branch ② (the prod path)", () => {
  it("a FULL-field ledger (as the prod merger now writes) makes branch ②补账 REACHABLE", async () => {
    // The crux of the thin-bar gap (cmr R1: codex-s1 + agy): branch ② only fires
    // when the LAST merged entry carries `familyHeadAfter` (a baseline). The
    // production merger must therefore write FULL fields, NOT the thin
    // {childIssue, status:"merged"}. With full fields, the crash window — child
    // 11's merge landed (live HEAD=base2, c11 ancestor) but its `merged` write
    // crashed → no `11` entry — is correctly补账, NOT re-run/re-merged.
    const ledger: FamilyLedgerEntry[] = [
      { childIssue: 10, status: "merged", childHead: "c10", familyHeadAfter: "base1" },
    ];
    const git = new FakeReconcileGit(
      "base2",
      { 10: "c10", 11: "c11" },
      new Set(["base1", "c10", "c11"]),
    );
    const plan = await reconcileFamilyLedger(ledger, children, git);
    expect(plan.escalate).toBe(false);
    expect(plan.reconciled).toEqual([{ childIssue: 11, childHead: "c11" }]);
    expect([...plan.merged].sort()).toEqual([10, 11]);
    expect(plan.liveHead).toBe("base2");
  });
});
