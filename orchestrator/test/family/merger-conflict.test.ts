/**
 * merger conflict fallback (ADR 0022 decision 3② "冲突才上 LLM", #295).
 *
 * #293 merger only did the no-conflict happy path: ask the {@link FamilyBackend}
 * to `git merge --no-ff` a reviewed child branch into the family base, then write
 * the merged ledger entry. #295 layers the CONFLICT FALLBACK on the SAME seam,
 * WITHOUT rewriting the spine:
 *
 *   - deterministic `git merge --no-ff` FIRST (省额度、可重放);
 *   - ONLY when that merge reports a conflict (`MergeResult.conflicted`) does the
 *     merger invoke the point-LLM resolver `backend.resolveMergeConflict` (an
 *     agent under the new `merger` soul + the `resolving-merge-conflicts` skill);
 *   - the LLM resolution is NEVER silent: the returned `MergeResult` is flagged
 *     `conflictResolvedByLlm` so the downstream family verify + integrated cmr
 *     (#296) can see this merge was LLM-resolved;
 *   - the merged ledger entry is written ONLY AFTER a clean OR an LLM-RESOLVED
 *     merge lands (ADR 0022 decision 5 ordering preserved). If resolution itself
 *     fails (throws, or returns still-conflicted), the ledger is NOT written and
 *     the failure is surfaced — not swallowed.
 *
 * Acceptance evidence:
 *  1. no-conflict child → deterministic `git merge`, resolver NEVER touched;
 *     conflicting child → resolver resolves, then merge continues.
 *  2. LLM resolution fires ONLY on a real conflict (resolver call count == #
 *     conflicting merges, 0 on the clean path).
 *  3. the LLM resolution is observable downstream (`conflictResolvedByLlm` on the
 *     result + the merge still lands on the family base + ledger), never silently
 *     swallowed; a FAILED resolution does NOT write a merged ledger entry.
 */

import { describe, expect, it } from "vitest";
import { mergeChild } from "../../src/family/merger.js";
import type {
  ConflictResolveRequest,
  FamilyBackend,
  FamilyLedgerEntry,
  MergeRequest,
  MergeResult,
} from "../../src/family/types.js";

/**
 * A fake family Backend whose deterministic merge can be told to "conflict" for
 * specific children (zero-container injection — NO real git). When the merger
 * sees `conflicted`, it must call `resolveMergeConflict`; the fake records that
 * call and returns a synthetic resolved head.
 */
class ConflictingFamilyBackend implements FamilyBackend {
  readonly merges: MergeRequest[] = [];
  readonly resolves: ConflictResolveRequest[] = [];
  readonly appended: FamilyLedgerEntry[] = [];
  private head = "base0";

  /** Child issues whose deterministic merge collides. */
  constructor(
    private readonly conflictIssues: ReadonlySet<number> = new Set(),
    /** If set, `resolveMergeConflict` rejects for these issues (resolution fails). */
    private readonly resolveFailures: ReadonlySet<number> = new Set(),
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<MergeResult> {
    this.merges.push(child);
    if (this.conflictIssues.has(child.childIssue)) {
      // Deterministic `git merge --no-ff` hit a conflict: do NOT advance the
      // head, signal it so the merger can route to the LLM resolver.
      return { familyHead: this.head, conflicted: true };
    }
    this.head = `merged-${child.childIssue}`;
    return { familyHead: this.head };
  }

  async resolveMergeConflict(req: ConflictResolveRequest): Promise<MergeResult> {
    this.resolves.push(req);
    if (this.resolveFailures.has(req.childIssue)) {
      throw new Error(`resolver could not resolve #${req.childIssue}`);
    }
    // The LLM (resolving-merge-conflicts soul) resolved + committed → head moves.
    this.head = `resolved-${req.childIssue}`;
    return { familyHead: this.head };
  }

  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.appended.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.appended;
  }
}

describe("merger conflict fallback — no-conflict path stays deterministic (#295 acc. 1/2)", () => {
  it("a no-conflict child merges deterministically and NEVER calls the LLM resolver", async () => {
    const backend = new ConflictingFamilyBackend(/* no conflicts */);
    const result = await mergeChild(backend, {
      childIssue: 10,
      childBranch: "feat/child-10",
    });
    // Deterministic merge happened.
    expect(backend.merges).toEqual([
      { childIssue: 10, childBranch: "feat/child-10" },
    ]);
    expect(result.familyHead).toBe("merged-10");
    // The point-LLM resolver was NEVER touched — "仅冲突才上 LLM".
    expect(backend.resolves).toEqual([]);
    // Clean merge ⇒ not LLM-resolved (no false positive downstream).
    expect(result.conflictResolvedByLlm ?? false).toBe(false);
    // Ledger written after the clean merge (decision 5 order preserved).
    expect(backend.appended).toEqual([{ childIssue: 10, status: "merged" }]);
  });
});

describe("merger conflict fallback — conflicting path routes to the LLM resolver (#295 acc. 1/2/3)", () => {
  it("a conflicting child invokes resolveMergeConflict, lands the resolved merge, and flags it LLM-resolved", async () => {
    const backend = new ConflictingFamilyBackend(new Set([11]));
    const result = await mergeChild(backend, {
      childIssue: 11,
      childBranch: "feat/child-11",
    });
    // Deterministic merge was ATTEMPTED first (省额度: LLM only after it conflicts).
    expect(backend.merges).toEqual([
      { childIssue: 11, childBranch: "feat/child-11" },
    ]);
    // The conflict routed to the point-LLM resolver with the same child identity.
    expect(backend.resolves).toEqual([
      { childIssue: 11, childBranch: "feat/child-11" },
    ]);
    // The resolved merge landed on the family base.
    expect(result.familyHead).toBe("resolved-11");
    // Observable downstream: this merge was LLM-resolved (not silently swallowed).
    expect(result.conflictResolvedByLlm).toBe(true);
    // Ledger written ONLY AFTER the resolved merge landed (decision 5).
    expect(backend.appended).toEqual([{ childIssue: 11, status: "merged" }]);
  });

  it("resolves ONLY the conflicting child in a serial run — clean children skip the LLM", async () => {
    const backend = new ConflictingFamilyBackend(new Set([11]));
    await mergeChild(backend, { childIssue: 10, childBranch: "feat/child-10" });
    await mergeChild(backend, { childIssue: 11, childBranch: "feat/child-11" });
    await mergeChild(backend, { childIssue: 12, childBranch: "feat/child-12" });
    // All three attempted the deterministic merge.
    expect(backend.merges.map((m) => m.childIssue)).toEqual([10, 11, 12]);
    // ONLY #11 (the conflicting one) reached the LLM resolver.
    expect(backend.resolves.map((r) => r.childIssue)).toEqual([11]);
    // Every child still got a merged ledger entry, in order.
    expect(backend.appended.map((e) => e.childIssue)).toEqual([10, 11, 12]);
  });
});

describe("merger conflict fallback — a FAILED resolution is not silently swallowed (#295 acc. 3)", () => {
  it("throws and does NOT write a merged ledger entry when the LLM resolver fails", async () => {
    const backend = new ConflictingFamilyBackend(new Set([13]), new Set([13]));
    await expect(
      mergeChild(backend, { childIssue: 13, childBranch: "feat/child-13" }),
    ).rejects.toThrow(/could not resolve/);
    // The resolver WAS attempted (the conflict was real, not swallowed).
    expect(backend.resolves.map((r) => r.childIssue)).toEqual([13]);
    // But NO merged ledger entry was written — an unresolved conflict must never
    // look like a clean merge (decision 5: ledger only after the merge lands).
    expect(backend.appended).toEqual([]);
  });
});
