/**
 * Wiring 1 (#291 整合缺口 1) — the merger's LLM-resolved-conflict signal reaches
 * the integrated cmr 承重闸 (ADR 0022 decision 3②/3⑥).
 *
 * The merger flags an LLM-resolved merge with `conflictResolvedByLlm` so it is
 * "不静默吞". #295 made that flag observable on the in-memory {@link MergeResult};
 * #298 widened the durable ledger. But the integrated cmr — the cross-slice 承重闸
 * that actually REVIEWS the merged family base (decision 3⑥) — had no way to know
 * WHICH children were LLM-resolved (after a context compaction only the DB / ledger
 * survives, per the project's first 铁律). This wiring closes that observability
 * gap end-to-end:
 *
 *   1. the merger writes the durable `merged` ledger entry carrying
 *      `conflictResolvedByLlm:true` for an LLM-resolved child (false/omitted for a
 *      clean deterministic merge);
 *   2. the spine, BEFORE the final-phase integrated cmr, derives the set of
 *      LLM-resolved children from the family ledger and hands it to the cmr request
 *      as `IntegratedCmrRequest.llmResolvedChildren` — so the 承重闸 can focus its
 *      cross-slice review on the merges a machine touched.
 *
 * Zero container: the single-slice child runs on a fake Backend; the family
 * merge/conflict/verify/cmr all on a scriptable fake FamilyBackend — no real git /
 * codex / push.
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
  ConflictResolveRequest,
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  MergeResult,
  OpenFamilyPrRequest,
  OpenFamilyPrResult,
} from "../../src/family/types.js";

/** A single-slice Backend that drives every child to S8(success). */
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
    return { kind: "reviewer", findings: [] };
  }
  async push(): Promise<void> {}
  async writeLedger(_e: PersistentLedgerEntry, _d: string): Promise<void> {}
}

/**
 * A capable family backend whose deterministic merge CONFLICTS for specific
 * children (routing the merger to the LLM resolver), records the integrated cmr
 * request, and supplies the #296 verify/cmr/PR capabilities.
 */
class ConflictCmrFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly prCalls: OpenFamilyPrRequest[] = [];
  private head = "base0";

  constructor(private readonly conflictIssues: ReadonlySet<number> = new Set()) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<MergeResult> {
    if (this.conflictIssues.has(child.childIssue)) {
      return { familyHead: this.head, conflicted: true };
    }
    this.head = `merged-${child.childIssue}`;
    return { familyHead: this.head, childHead: `c${child.childIssue}`, familyHeadBefore: "base0" };
  }
  async resolveMergeConflict(req: ConflictResolveRequest): Promise<MergeResult> {
    this.head = `resolved-${req.childIssue}`;
    return {
      familyHead: this.head,
      childHead: `c${req.childIssue}`,
      familyHeadBefore: "base0",
    };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async runFamilyVerify(_req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    return { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    return { converged: true };
  }
  async openFamilyPr(req: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
    this.prCalls.push(req);
    return { url: `pr://${req.familyBase}` };
  }
}

const epic: FamilyEpic = {
  issue: 291,
  children: [
    { issue: 294, blockedBy: [] }, // clean deterministic merge
    { issue: 295, blockedBy: [] }, // conflicts → LLM-resolved
  ],
};

describe("Wiring 1 — conflictResolvedByLlm flows to the integrated cmr (#291 缺口 1)", () => {
  it("an LLM-resolved child's durable ledger entry carries conflictResolvedByLlm:true; a clean child's does not", async () => {
    const backend = new ConflictCmrFamilyBackend(new Set([295]));
    await runFamily({
      epic,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });

    const byIssue = new Map(
      backend.ledger
        .filter((e) => e.status === "merged")
        .map((e) => [e.childIssue, e.conflictResolvedByLlm]),
    );
    // The conflicting child (295) was LLM-resolved → durable flag true.
    expect(byIssue.get(295)).toBe(true);
    // The clean child (294) was a deterministic merge → flag false/omitted.
    expect(byIssue.get(294) ?? false).toBe(false);
  });

  it("the spine derives IntegratedCmrRequest.llmResolvedChildren from the ledger (only the LLM-resolved child)", async () => {
    const backend = new ConflictCmrFamilyBackend(new Set([295]));
    await runFamily({
      epic,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });

    expect(backend.cmrCalls).toHaveLength(2);
    expect(backend.cmrCalls.map((c) => c.cmrPass)).toEqual([
      "completeness",
      "correctness",
    ]);
    expect(backend.cmrCalls.every((c) => c.familyBase === "family/291-base")).toBe(true);
    expect(backend.cmrCalls.every((c) => c.llmResolvedChildren?.[0] === 295)).toBe(true);
  });

  it("with NO conflicts, the cmr request omits llmResolvedChildren (no false signal)", async () => {
    const backend = new ConflictCmrFamilyBackend(/* no conflicts */);
    await runFamily({
      epic,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });

    expect(backend.cmrCalls).toHaveLength(2);
    // No LLM-resolved children → the field is omitted (an empty list would be a
    // distinct shape; we keep the back-compatible `{familyBase}`-only request).
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "completeness" },
      { familyBase: "family/291-base", cmrPass: "correctness" },
    ]);
  });
});
