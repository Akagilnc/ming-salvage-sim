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
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
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
import { resolveActiveModelRoute } from "../../src/modelRoutes.js";
import { skeletonReviewLoopWorkerResult } from "../../src/reviewLoopOutcome.js";

// ─── fakes ────────────────────────────────────────────────────────────────────

function makeFamilyDocReleaseRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "family-spine-doc-"));
  const git = (args: string[]) =>
    execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  git(["init"]);
  git(["config", "user.email", "t@example.com"]);
  git(["config", "user.name", "t"]);
  writeFileSync(join(dir, "VERSION"), "1.0.0\n");
  git(["add", "."]);
  git(["commit", "-m", "doc-release"]);
  return dir;
}

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
      hasSubIssues: false,
      isClosed: false,
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
  readonly workingRepo: string;
  head = "family-base-0";
  constructor(workingRepo?: string) {
    this.workingRepo = workingRepo ?? makeFamilyDocReleaseRepo();
  }
  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.head = `+${child.childIssue}`;
    return { familyHead: this.head };
  }
  // #295 conflict-fallback seam `resolveMergeConflict` is OPTIONAL — these spine
  // tests use the deterministic (no-conflict) merge path and never reach it, so
  // the fake omits it.
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(_familyBase: string): Promise<string> {
    return this.head;
  }
  resolveFamilyWorkingRepo(): string | undefined {
    return this.workingRepo;
  }

  // #596 r2 support for full final barrier in spine tests (runVerifyCmr fresh path)
  runFamilyVerify?: (req: any) => Promise<any>;
  dispatchWorker?: (spec: any, ctx?: any) => Promise<any>;
  verifyFamilyShippedPr?: (req: any) => Promise<{ ok: boolean }>;
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

  it("already-shipped resume reports already_done instead of a generic success summary", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push(
      { childIssue: 10, status: "merged", familyHeadAfter: "family-base-0" },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: "pr://family/293-base",
        familyHeadAfter: "family-base-0",
      },
    );
    familyBackend.verifyFamilyShippedPr = async () => ({ ok: true });

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(result.status).toBe("success");
    expect(result.stopSummary).toMatchObject({
      reason: "already_done",
      summary: "family run already converged for the current family HEAD",
      metadata: {
        heads: expect.objectContaining({
          actualFamilyHead: "family-base-0",
        }),
      },
    });
    expect(singleSliceBackend.prepareBases).toEqual([]);
    const prMerged = familyBackend.ledger.filter((e) => e.status === "pr_merged");
    expect(prMerged).toHaveLength(1);
    expect(prMerged[0]).toMatchObject({
      event: "pr_merged",
      pr: "pr://family/293-base",
      familyHeadAfter: "family-base-0",
    });
  });

  it("review_loop_converged + pr_merged resume stays already_done without re-merge", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push(
      { childIssue: 10, status: "merged", familyHeadAfter: "family-base-0" },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: "pr://family/293-base",
        familyHeadAfter: "family-base-0",
      },
      {
        status: "pr_merged",
        event: "pr_merged",
        phase: "final",
        pr: "pr://family/293-base",
        prNumber: 293,
        remoteBranchName: "family/293-base",
        mergedHeadOid: "family-base-0",
        familyHeadAfter: "family-base-0",
      },
    );
    familyBackend.verifyFamilyShippedPr = async () => ({ ok: true });

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(result.status).toBe("success");
    expect(result.stopSummary?.reason).toBe("already_done");
    expect(familyBackend.ledger.filter((e) => e.status === "pr_merged")).toHaveLength(1);
  });

  it("shipped-only (bound to current head, no review_loop_converged) continues into review-loop: writes converged marker, reports already_done, no re-ship (F2)", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push(
      { childIssue: 10, status: "merged", familyHeadAfter: "family-base-0" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://family/293-base",
        familyHeadAfter: "family-base-0",
      },
    );
    familyBackend.verifyFamilyShippedPr = async () => ({ ok: true });

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(result.status).toBe("success");
    expect(result.children.every((c) => c.status === "already_done")).toBe(true);
    expect(result.stopSummary).toMatchObject({
      reason: "already_done",
      summary: "family review-loop converged during resume for the current family HEAD",
      metadata: {
        heads: expect.objectContaining({
          actualFamilyHead: "family-base-0",
        }),
      },
    });
    // Key assertion: review_loop_converged was WRITTEN by the resume path (was only pre-seeded before)
    const convergedRows = familyBackend.ledger.filter(
      (e) => e.status === "review_loop_converged",
    );
    expect(convergedRows).toHaveLength(1);
    expect(convergedRows[0]).toMatchObject({
      status: "review_loop_converged",
      event: "review_loop_converged",
      phase: "final",
      pr: "pr://family/293-base",
      familyHeadAfter: "family-base-0",
    });
    const prMerged = familyBackend.ledger.filter((e) => e.status === "pr_merged");
    expect(prMerged).toHaveLength(1);
    expect(prMerged[0]).toMatchObject({
      event: "pr_merged",
      pr: "pr://family/293-base",
      familyHeadAfter: "family-base-0",
    });
    // No child re-work (shipped resume short-circuits before verifyCmr barrier)
    expect(singleSliceBackend.prepareBases).toEqual([]);
  });

  it("review_loop_converged + pr_merged resume skips OPEN verify (B3)", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.ledger.push(
      { childIssue: 10, status: "merged", familyHeadAfter: "family-base-0" },
      {
        status: "review_loop_converged",
        event: "review_loop_converged",
        phase: "final",
        pr: "pr://family/293-base",
        familyHeadAfter: "family-base-0",
      },
      {
        status: "pr_merged",
        event: "pr_merged",
        phase: "final",
        pr: "pr://family/293-base",
        prNumber: 293,
        remoteBranchName: "family/293-base",
        mergedHeadOid: "family-base-0",
        familyHeadAfter: "family-base-0",
      },
    );
    let verifyCalled = false;
    familyBackend.verifyFamilyShippedPr = async () => {
      verifyCalled = true;
      return { ok: false, reason: "PR is MERGED but must be OPEN" };
    };

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(result.status).toBe("success");
    expect(verifyCalled).toBe(false);
    expect(familyBackend.ledger.filter((e) => e.status === "pr_merged")).toHaveLength(1);
  });

  it("pin r28: shipped resume re-enters review loop when fixer advanced HEAD with only markers", async () => {
    const shipHead = "family-base-0";
    const postFixHead = "family-base-postfix";
    const pr = "pr://family/293-base";
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.head = postFixHead;
    familyBackend.ledger.push(
      { childIssue: 10, status: "merged", familyHeadAfter: shipHead },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr,
        familyHeadAfter: shipHead,
      },
      {
        status: "online_review_round_retrigger",
        event: "online_review_round_retrigger",
        phase: "final",
        roundTriggerHeadOid: postFixHead,
        roundTriggerAt: "2026-07-08T13:00:00.000Z",
        onlineReviewRound: 2,
        pr,
      },
      {
        status: "online_review_fix_committed",
        event: "online_review_fix_committed",
        phase: "final",
        familyHeadAfter: postFixHead,
        pr,
      },
    );
    familyBackend.verifyFamilyShippedPr = async () => ({ ok: true });

    const verifyRounds: number[] = [];
    familyBackend.dispatchWorker = async (spec, ctx) => {
      if (spec.kind === "verify") {
        verifyRounds.push(ctx?.onlineReviewRound ?? 0);
        return {
          kind: "completed",
          output: { kind: "verify", converged: true },
        };
      }
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
    };

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(result.status).toBe("success");
    expect(verifyRounds).toEqual([2]);
    expect(singleSliceBackend.prepareBases).toEqual([]);
    const convergedRows = familyBackend.ledger.filter(
      (e) => e.status === "review_loop_converged",
    );
    expect(convergedRows).toHaveLength(1);
    expect(convergedRows[0]?.familyHeadAfter).toBe(postFixHead);
  });

  it("shipped-only resume records post-fix family head when in-loop fixer advanced HEAD (cmr r7)", async () => {
    const shipHead = "family-base-0";
    const postFixHead = "family-base-postfix";
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    familyBackend.head = shipHead;
    familyBackend.ledger.push(
      { childIssue: 10, status: "merged", familyHeadAfter: shipHead },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://family/293-base",
        familyHeadAfter: shipHead,
      },
    );
    familyBackend.verifyFamilyShippedPr = async () => ({ ok: true });

    let verifyPass = 0;
    familyBackend.dispatchWorker = async (spec) => {
      if (spec.kind === "verify") {
        verifyPass += 1;
        return {
          kind: "completed",
          output: { kind: "verify", converged: verifyPass >= 2 },
        };
      }
      if (spec.kind === "fixer") {
        familyBackend.head = postFixHead;
        return { kind: "completed", output: {
                  kind: "fixer",
                  committed: true,
                  fixCommitSha: "fixsha1111111111111111111111111111111111",
                } };
      }
      const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
      return skeleton ?? { kind: "failed", reason: `unexpected ${spec.kind}` };
    };

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(result.status).toBe("success");
    const convergedRows = familyBackend.ledger.filter(
      (e) => e.status === "review_loop_converged",
    );
    expect(convergedRows).toHaveLength(1);
    expect(convergedRows[0]?.familyHeadAfter).toBe(postFixHead);
    expect(singleSliceBackend.prepareBases).toEqual([]);
  });

  it("shipped stopSummary with verifiedCmrHead is copied into review_loop_converged terminal marker and visible on resume (F1 regression: makes fresh-ship path consistent)", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    const richStopSummary = {
      reason: "success",
      summary: "family shipped+loop",
      metadata: {
        heads: {
          actualFamilyHead: "family-base-0",
          verifiedCmrHead: "verified-cmr-from-fresh",
          sources: { verifiedCmrHead: "cmr_passed" },
        },
      },
    };
    familyBackend.ledger.push(
      { childIssue: 10, status: "merged", familyHeadAfter: "family-base-0" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://family/293-base",
        familyHeadAfter: "family-base-0",
        stopSummary: richStopSummary,
      },
    );
    familyBackend.verifyFamilyShippedPr = async () => ({ ok: true });

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(result.status).toBe("success");
    // regression: terminal marker preserves verifiedCmrHead (the bug was fresh-ship write omitted stopSummary; resume sibling already copied; now both paths consistent)
    expect(result.stopSummary.metadata?.heads?.verifiedCmrHead).toBe(
      "verified-cmr-from-fresh",
    );
    const convergedRows = familyBackend.ledger.filter(
      (e) => e.status === "review_loop_converged",
    );
    expect(convergedRows).toHaveLength(1);
    expect(convergedRows[0]?.stopSummary?.metadata?.heads?.verifiedCmrHead).toBe(
      "verified-cmr-from-fresh",
    );
    // No child re-work
    expect(singleSliceBackend.prepareBases).toEqual([]);
  });

  it("fresh-ship path (no pre-seeded shipped row) lets runVerifyCmr run the write at verifyCmr.ts and produces review_loop_converged carrying metadata.heads.verifiedCmrHead + material stopSummary (pins the actual fixed path, not resume copy)", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();

    // NO shipped row pre-seeded (and no converged). runFamily will merge then hit real runVerifyCmr fresh-ship path.
    // Pre-seed nothing for final markers; the cmr dispatch below will cause cmr_passed to be written with material.
    familyBackend.runFamilyVerify = async (_req: any): Promise<any> => ({ ok: true });

    const resolvedRoute = resolveActiveModelRoute();
    const declared = resolvedRoute.legCollections.cmrReview.map((l: { slug: string }) => l.slug);
    const cmrOutput = {
      kind: "cmr",
      converged: true,
      successfulLegs: declared.length > 0 ? declared : ["opus"],
      claimedFixedFindingIdentityKeys: [],
      priorFindingDispositions: [],
      evidencePaths: [],
    };
    familyBackend.dispatchWorker = async (spec: any, _ctx?: any): Promise<any> => {
      if (spec.kind === "cmr") {
        return { kind: "completed", output: cmrOutput };
      }
      if (spec.kind === "ship") {
        const prHead = familyBackend.head;
        return {
          kind: "completed",
          output: {
            kind: "ship",
            branch: "family/293-base",
            status: "pr_opened",
            pr: "pr://family/293-base-fresh",
            prHead,
          },
        };
      }
      const skeletonKinds = new Set(["verify", "fixer", "cleanup", "docRelease"]);
      if (skeletonKinds.has(spec.kind)) {
        return {
          kind: "completed",
          output:
            spec.kind === "verify"
              ? { kind: "verify", converged: true }
              : spec.kind === "fixer"
                ? {
                  kind: "fixer",
                  committed: true,
                  fixCommitSha: "fixsha1111111111111111111111111111111111",
                }
                : spec.kind === "cleanup"
                  ? { kind: "cleanup", terminal: true, ok: true, branchOutcome: "already_gone" }
                  : { kind: "docRelease", released: true },
        };
      }
      return { kind: "failed", reason: "unexpected kind in #596 r2 fresh-ship spine test" };
    };

    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
      // verifyCmr left default → real runVerifyCmr executes the fresh ship + recordReviewLoopConverged path
    });

    expect(result.status).toBe("success");
    const convergedRows = familyBackend.ledger.filter(
      (e) => e.status === "review_loop_converged",
    );
    expect(convergedRows).toHaveLength(1);
    // must carry the verifiedCmrHead from the material cmr_passed stopSummary threaded through shipped → converged
    const written = convergedRows[0];
    expect(written?.stopSummary?.metadata?.heads?.verifiedCmrHead).toBe("+10");
    // also carries material stopSummary metadata (from familyCmrPassStopSummary threaded via fresh-ship)
    expect(written?.stopSummary?.reason).toBe("success");
    expect(written?.stopSummary?.metadata?.heads?.sources?.verifiedCmrHead).toBe(
      "latest cmr_passed ledger row",
    );
    // Child work happened (fresh run, not resume short-circuit); final barrier ran via real runVerifyCmr
    expect(singleSliceBackend.prepareBases).toEqual(["family/293-base"]);
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

    // #298 acceptance-1: each merged child is recorded with the FULL schema
    // (childBranch + familyHeadAfter here; this fake reports no
    // familyHeadBefore/childHead, so compact drops those — the back-compat path).
    // The `familyHeadAfter` baseline is what makes the crash-window reconcile
    // branch ② reachable in production (cmr R1: codex-s1 + agy).
    expect(familyBackend.ledger).toEqual([
      { childIssue: 10, status: "merged", childBranch: "feat/child-10", familyHeadAfter: "+10" },
      { childIssue: 11, status: "merged", childBranch: "feat/child-11", familyHeadAfter: "+11" },
      { childIssue: 12, status: "merged", childBranch: "feat/child-12", familyHeadAfter: "+12" },
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

  it("a child that FAILS its own S0 rfa gate makes the family run incomplete, not a fabricated merge", async () => {
    // One child is not ready-for-agent → its single-slice S0 gate returns a
    // structured terminal error. The family spine records that child as failed and
    // returns an incomplete family result; it never fabricates a merge for it.
    class GateRejectChildBackend extends ChildBackend {
      override async fetchIssueMeta(issueNumber: number): Promise<IssueMeta> {
        return {
          number: issueNumber,
          isReadyForAgent: issueNumber !== 11,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
        };
      }
    }
    const singleSliceBackend = new GateRejectChildBackend();
    const familyBackend = new FakeFamilyBackend();

    const result = await runFamily({
      epic: epicWith(10, 11),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
    });

    expect(result.status).toBe("incomplete");
    expect(result.children).toEqual([
      { issue: 10, status: "merged", branch: "feat/child-10" },
      { issue: 11, status: "failed", branch: undefined },
    ]);
    expect(result.stopSummary.reason).toBe("owning_issue_still_red");
    expect(result.stopSummary.summary).toContain("#11:failed");
  });

  it("verify_failed family result preserves the barrier stop summary from the ledger", async () => {
    const singleSliceBackend = new ChildBackend();
    const familyBackend = new FakeFamilyBackend();
    const result = await runFamily({
      epic: epicWith(10),
      familyBackend,
      singleSliceBackend,
      familyBase: "family/293-base",
      verifyCmr: async ({ familyBackend: backend }) => {
        await backend.appendFamilyLedger({
          status: "aborted",
          event: "aborted",
          phase: "final",
          reason: "same-module CMR finding still red",
          familyHeadAfter: "head-after-cmr",
          stopSummary: {
            reason: "same_module_still_red",
            summary: "same-module CMR finding still red",
            repairHint: "continue the family CMR fix loop",
          },
        });
        return { ok: false, ran: true };
      },
    });

    expect(result.status).toBe("verify_failed");
    expect(result.stopSummary).toMatchObject({
      reason: "same_module_still_red",
      summary: "same-module CMR finding still red",
      repairHint: "continue the family CMR fix loop",
    });
  });
});
