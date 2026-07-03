/**
 * #296 — the verify-cmr hook body driven through the REAL spine (no injected
 * `verifyCmr`), against a capable `FamilyBackend` (ADR 0022 decision 3④/⑤/⑥/4).
 *
 * `runner-verify-cmr.test.ts` (#293) proves the spine WIRING with an injected
 * fake hook. Here the spine uses the DEFAULT `runVerifyCmr` module export (#296's
 * filled body) and a `FamilyBackend` that supplies the verify/cmr/PR/abort/
 * escalate capabilities — so the three acceptance criteria are proven end-to-end
 * through the actual family loop, not just the hook in isolation:
 *
 *   1. a red WAVE verify aborts before the next wave + writes `aborted` + leaves
 *      the run observably `verify_failed` (NOT a false success);
 *   2. a NOT-converged integrated cmr at the final barrier escalates续跑 (#298) +
 *      `verify_failed`;
 *   3. all green ⇒ the family PR is OPENED (止于 PR) and the run is `success` —
 *      and the spine never merges to main (no merge-to-main call exists).
 *
 * Zero container: the single-slice child runs on a fake Backend, the family
 * verify/cmr/PR all on a scriptable fake FamilyBackend — no real codex / push.
 */

import { describe, expect, it } from "vitest";
import { recordFamilyEscalated } from "../../src/family/ledger.js";
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
  FamilyAbortedEvent,
  FamilyBackend,
  FamilyEpic,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  OpenFamilyPrRequest,
  OpenFamilyPrResult,
  ReconcileGit,
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

/** A family backend with the #296 verify/cmr/PR/abort/escalate capabilities. */
class CapableFamilyBackend implements FamilyBackend {
  readonly ledger: FamilyLedgerEntry[] = [];
  readonly merges: MergeRequest[] = [];
  readonly verifyCalls: FamilyVerifyRequest[] = [];
  readonly cmrCalls: IntegratedCmrRequest[] = [];
  readonly aborted: FamilyAbortedEvent[] = [];
  readonly escalations: FamilyEscalation[] = [];
  readonly prCalls: OpenFamilyPrRequest[] = [];
  readonly verifyShippedPrCalls: Array<{ pr: string; familyBase: string; expectedHead: string }> = [];
  liveHead: string | undefined;
  shippedPrOk = true;
  shippedPrFailureReason = "shipped PR is stale";

  constructor(
    private readonly script: {
      verify?: (req: FamilyVerifyRequest) => FamilyVerifyResult;
      cmr?: (req: IntegratedCmrRequest) => IntegratedCmrResult;
    } = {},
  ) {}

  async mergeChildIntoFamilyBase(child: MergeRequest): Promise<{ familyHead: string }> {
    this.merges.push(child);
    this.liveHead = `+${child.childIssue}`;
    return { familyHead: this.liveHead };
  }
  async appendFamilyLedger(entry: FamilyLedgerEntry): Promise<void> {
    this.ledger.push(entry);
  }
  async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
    return this.ledger;
  }
  async readFamilyHead(): Promise<string> {
    if (this.liveHead === undefined) throw new Error("no live head");
    return this.liveHead;
  }
  async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
    this.verifyCalls.push(req);
    return this.script.verify?.(req) ?? { ok: true };
  }
  async runIntegratedCmr(req: IntegratedCmrRequest): Promise<IntegratedCmrResult> {
    this.cmrCalls.push(req);
    return this.script.cmr?.(req) ?? { converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] };
  }
  async openFamilyPr(req: OpenFamilyPrRequest): Promise<OpenFamilyPrResult> {
    this.prCalls.push(req);
    return { url: `pr://${req.familyBase}`, prHead: this.liveHead };
  }
  async verifyFamilyShippedPr(req: {
    pr: string;
    familyBase: string;
    expectedHead: string;
  }): Promise<{ ok: true } | { ok: false; reason: string }> {
    this.verifyShippedPrCalls.push(req);
    return this.shippedPrOk
      ? { ok: true }
      : { ok: false, reason: this.shippedPrFailureReason };
  }
  async recordAborted(event: FamilyAbortedEvent): Promise<void> {
    this.aborted.push(event);
  }
  async escalateFamily(esc: FamilyEscalation): Promise<void> {
    this.escalations.push(esc);
    await recordFamilyEscalated(this, {
      escalationKind: "decision",
      phase: "final",
      reason: esc.reason,
      familyHeadAfter: esc.familyHeadAfter,
      stopSummary: esc.stopSummary,
    });
  }
}

class StaticReconcileGit implements ReconcileGit {
  constructor(private readonly liveHead: string, private readonly startHead: string = "base0") {}
  async liveFamilyHead(): Promise<string> {
    return this.liveHead;
  }
  async familyBaseStartHead(): Promise<string> {
    return this.startHead;
  }
  async childHeadExists(): Promise<{ exists: boolean; childHead?: string }> {
    return { exists: false };
  }
  async isAncestor(a: string, b: string): Promise<boolean> {
    return a === b || a === this.startHead || b === this.liveHead;
  }
}

const TWO_WAVES: FamilyEpic = {
  issue: 291,
  children: [
    { issue: 294, blockedBy: [] },
    { issue: 296, blockedBy: [294] },
  ],
};

function epicWith(...issues: number[]): FamilyEpic {
  return { issue: 291, children: issues.map((issue) => ({ issue, blockedBy: [] })) };
}

describe("#296 spine integration — acceptance 1: per-wave fail-fast verify", () => {
  it("a RED wave verify aborts before the next wave, writes `aborted`, leaves the run verify_failed", async () => {
    // Wave 1 = {294}; wave 2 = {296} (blocked_by 294). Verify fails on the WAVE
    // phase → after wave 1 merges 294, the wave barrier is red → no wave 2.
    const backend = new CapableFamilyBackend({
      verify: (req) =>
        req.phase === "wave"
          ? { ok: false, errorPackage: { reason: "tsc: TS2345 cross-slice type" } }
          : { ok: true },
    });
    const result = await runFamily({
      epic: TWO_WAVES,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      // NO verifyCmr injection → the spine uses #296's real runVerifyCmr.
    });
    // Wave 1 merged 294; the red wave verify aborted before wave 2 (296 never ran).
    expect(backend.merges.map((m) => m.childIssue)).toEqual([294]);
    expect(backend.verifyCalls.map((v) => v.phase)).toEqual(["wave"]); // no "final"
    // `aborted` event written to the in-memory seam (decision 3④/5), carrying the
    // error package + (#291 缺口 2) the abort-time family head.
    expect(backend.aborted).toHaveLength(1);
    expect(backend.aborted[0]?.errorPackage.reason).toContain("TS2345");
    expect(backend.aborted[0]?.familyHeadAfter).toBe("+294"); // head after wave 1's merge
    // #291 缺口 2: the abort ALSO reaches the DURABLE ledger reconcile reads — a
    // PHASE-LEVEL entry (no childIssue), carrying phase + reason + familyHeadAfter.
    const durableAborts = backend.ledger.filter((e) => e.status === "aborted");
    expect(durableAborts).toHaveLength(1);
    expect(durableAborts[0]?.event).toBe("aborted");
    expect(durableAborts[0]?.phase).toBe("wave");
    expect("childIssue" in durableAborts[0]!).toBe(false);
    expect(durableAborts[0]?.familyHeadAfter).toBe("+294");
    expect(durableAborts[0]?.reason).toContain("TS2345");
    // Observably verify_failed at the wave phase — NOT a false success.
    expect(result.status).toBe("verify_failed");
    expect(result.failedPhase).toBe("wave");
    const byIssue = new Map(result.children.map((c) => [c.issue, c.status]));
    expect(byIssue.get(294)).toBe("merged");
    expect(byIssue.get(296)).toBe("skipped");
    // No PR opened on a red run.
    expect(backend.prCalls).toEqual([]);
  });
});

describe("#296 spine integration — acceptance 2: integrated cmr gate → escalate续跑", () => {
  it("green verify but NOT-converged final cmr → escalate (#298), verify_failed, NO PR", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: false,
        reason: "阈值口径 mismatch: slice A clamps at 100, slice B at 99",
      }),
    });
    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });
    // Both children merged; wave verify green; final verify green; step5 completeness ran + red.
    expect(backend.merges.map((m) => m.childIssue)).toEqual([294, 295]);
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "completeness" },
    ]);
    expect(backend.escalations).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "aborted",
      event: "aborted",
      phase: "final",
      cmrPass: "completeness",
      reason: expect.stringContaining("阈值口径"),
      stopSummary: expect.objectContaining({ reason: "contract_drift" }),
    }));
    expect(backend.prCalls).toEqual([]);
    // Observably verify_failed at the final phase.
    expect(result.status).toBe("verify_failed");
    expect(result.failedPhase).toBe("final");
  });

  it("resumes after a committed CMR coder-fix with protected finding keys", async () => {
    const priorKey = "completeness|orchestrator/src/x.ts:12|restart final barrier";
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: (req) => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.5", "agy"],
        ...(req.priorCmrFindingIdentityKeys !== undefined
          ? {
              claimedFixedFindingIdentityKeys: [priorKey],
              priorFindingDispositions: [
                {
                  identityKey: priorKey,
                  status: "verified-closed" as const,
                  evidence: "focused regression now passes after coder-fix commit",
                },
              ],
            }
          : {}),
      }),
    });
    backend.liveHead = "head-after-cmr-fix";
    backend.ledger.push(
      {
        childIssue: 294,
        status: "merged",
        childHead: "c294",
        familyHeadAfter: "head-before-cmr-fix",
      },
      {
        status: "cmr_fix_committed",
        event: "cmr_fix_committed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadBefore: "head-before-cmr-fix",
        familyHeadAfter: "head-after-cmr-fix",
        blockingFindingIdentityKeys: [priorKey],
      } as FamilyLedgerEntry,
    );

    const result = await runFamily({
      epic: epicWith(294),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      reconcileGit: {
        async liveFamilyHead() {
          return "head-after-cmr-fix";
        },
        async familyBaseStartHead() {
          return "head-before-cmr-fix";
        },
        async childHeadExists() {
          return { exists: true, childHead: "c294" };
        },
        async isAncestor() {
          return true;
        },
      },
    });

    expect(result.status).toBe("success");
    expect(backend.cmrCalls[0]).toMatchObject({
      cmrPass: "completeness",
      priorCmrFindingIdentityKeys: [priorKey],
    });
  });

  it("CMR completed/not-converged is a machine abort, not a decision pause", async () => {
    let cmrCalls = 0;
    const seenAnswers: IntegratedCmrRequest["escalationAnswer"][] = [];
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: (req) => {
        cmrCalls += 1;
        seenAnswers.push(req.escalationAnswer);
        return cmrCalls === 1
          ? {
              converged: false,
              reason: "same-class findings need a human continue decision",
            }
          : { converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] };
      },
    });
    const input = {
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    };

    const first = await runFamily(input);

    expect(first.status).toBe("verify_failed");
    expect(backend.ledger).toContainEqual(
      expect.objectContaining({
        status: "aborted",
        event: "aborted",
        phase: "final",
        cmrPass: "completeness",
        familyHeadAfter: "+295",
        reason: expect.stringContaining("same-class findings"),
        stopSummary: expect.objectContaining({ reason: "contract_drift" }),
      }),
    );
    const callsAfterFirst = cmrCalls;

    const rerun = await runFamily(input);

    expect(rerun.status).toBe("success");
    expect(cmrCalls).toBeGreaterThan(callsAfterFirst);
    expect(seenAnswers).toEqual([undefined, undefined, undefined]);
    expect(backend.prCalls).toHaveLength(1);
  });
});

describe("#296 spine integration — fail-safe: verify-green but a required final-barrier capability missing must NOT be success", () => {
  it("a real backend that verifies green but lacks runIntegratedCmr leaves the run verify_failed (NOT a false success)", async () => {
    // The 承重闸 (integrated cmr, decision 3⑥) cannot run, so the run must NOT report
    // success — that would ship code the integrated cmr never reviewed. The spine
    // ignores the hook's `ran` flag and acts on `ok`, so the hook must fail-safe to
    // ok:false (verify_failed at the final phase) rather than the nothing-ran no-op.
    class VerifyOnlySpineBackend implements FamilyBackend {
      readonly ledger: FamilyLedgerEntry[] = [];
      readonly verifyCalls: FamilyVerifyRequest[] = [];
      async mergeChildIntoFamilyBase(c: MergeRequest): Promise<{ familyHead: string }> {
        return { familyHead: `+${c.childIssue}` };
      }
      async appendFamilyLedger(e: FamilyLedgerEntry): Promise<void> {
        this.ledger.push(e);
      }
      async readFamilyLedger(): Promise<ReadonlyArray<FamilyLedgerEntry>> {
        return this.ledger;
      }
      async runFamilyVerify(req: FamilyVerifyRequest): Promise<FamilyVerifyResult> {
        this.verifyCalls.push(req);
        return { ok: true };
      }
      // NO runIntegratedCmr / openFamilyPr (a real-but-incomplete backend).
    }
    const backend = new VerifyOnlySpineBackend();
    const result = await runFamily({
      epic: epicWith(294),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      // NO verifyCmr injection → the spine uses #296's real runVerifyCmr.
    });
    // Both verify barriers ran green; the child merged; but the final barrier is red
    // because the 承重闸 cmr could not run — observably verify_failed, never success.
    expect(backend.verifyCalls.map((v) => v.phase)).toEqual(["wave", "final"]);
    expect(result.status).toBe("verify_failed");
    expect(result.failedPhase).toBe("final");
  });
});

describe("#296 spine integration — acceptance 3: all green → open PR, stop, no merge-to-main", () => {
  it("green verify + converged cmr ⇒ the family PR is opened and the run is success (止于 PR)", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    const result = await runFamily({
      epic: epicWith(294, 295, 298),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });
    // One wave (all independent): wave verify (green) then final verify (green) →
    // step5 completeness → step6 correctness → PR opened ONCE from the family base.
    expect(backend.verifyCalls.map((v) => v.phase)).toEqual(["wave", "final"]);
    expect(backend.cmrCalls).toEqual([
      { familyBase: "family/291-base", cmrPass: "completeness" },
      { familyBase: "family/291-base", cmrPass: "correctness" },
    ]);
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
    // 止于 PR: a PR was opened, but the run STOPS here — every child merged into the
    // family base, status success, no escalate. (No merge-to-main seam exists on
    // FamilyBackend at all — the family layer cannot merge to main by construction.)
    expect(result.status).toBe("success");
    expect(result.children.every((c) => c.status === "merged")).toBe(true);
    expect(backend.escalations).toEqual([]);
  });
});

describe("#291 spine — the final barrier (verify + cmr + 止于 PR) is GATED on a COMPLETE family base (online R1 Codex P1)", () => {
  // A child whose single-slice run does NOT succeed (coder commits nothing → S2
  // routes to S8 error → a non-throwing "failed") leaves the family base PARTIAL:
  // the wave loop exits with that child unmerged and finalize() marks the run
  // "incomplete". The final barrier (full verify → integrated cmr → openFamilyPr) is
  // meaningful ONLY for a COMPLETE base — running it on a partial base would open a
  // family PR missing slices, even though the returned status is not shippable. So
  // the spine must SKIP the final barrier (no final verify / cmr / PR) when not every
  // epic child is ledger-merged, and return "incomplete" honestly.
  class FailingCoderChildBackend extends ChildBackend {
    override async runStep(spec: StepSpec): Promise<StepOutput> {
      if (spec.role === "coder") return { kind: "coder", committed: false, commitsAdded: 0 };
      return { kind: "reviewer", findings: [] };
    }
  }
  it("a child that fails its single-slice run ⇒ NO final verify / cmr / PR, status incomplete", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new FailingCoderChildBackend(),
      familyBase: "family/291-base",
    });
    // Both children failed their coder step → neither merged → the family base is partial.
    expect(backend.merges).toEqual([]);
    // The final barrier is GATED: NO "final" verify, NO cmr, NO PR on a partial base.
    expect(backend.verifyCalls.map((v) => v.phase)).not.toContain("final");
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    // Honest: observably incomplete (decision 3⑤ 不静默吞), NOT a fabricated success.
    expect(result.status).toBe("incomplete");
    expect(result.children.every((c) => c.status === "failed")).toBe(true);
  });
});

describe("#330 spine — an already-shipped family is NOT re-shipped on resume (online review r2, codex P1)", () => {
  it("a head-bound `shipped` ledger marker for the current head ⇒ skip the final barrier", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    // Resume truth: both children already merged AND the terminal 止于-PR ship already
    // ran (a `shipped` marker on the durable ledger). The family PR is open and the
    // base carries the ship (VERSION/CHANGELOG bump) commit. Pre-fix the spine
    // re-entered the final barrier here — re-running full verify + integrated cmr and
    // re-invoking the ship worker (a DUPLICATE VERSION bump / PR attempt), because
    // nothing recorded that the family was already delivered.
    backend.ledger.push(
      { childIssue: 294, status: "merged" },
      { childIssue: 295, status: "merged" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://family/291-base",
        familyHeadAfter: "ship-head",
        stopSummary: {
          reason: "success",
          summary: "run completed successfully",
          metadata: {
            heads: {
              reportedFamilyHead: "ship-head",
              actualFamilyHead: "ship-head",
              verifiedCmrHead: "verified-cmr-head",
              sources: {
                reportedFamilyHead: "ship worker reported prHead",
                actualFamilyHead: "family head after ship worker",
                verifiedCmrHead: "latest cmr_passed ledger row",
              },
            },
          },
        },
      },
    );
    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      reconcileGit: new StaticReconcileGit("ship-head"),
    });
    // The already-shipped guard short-circuits BEFORE the final barrier.
    expect(backend.verifyCalls.map((v) => v.phase)).not.toContain("final");
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.verifyShippedPrCalls).toEqual([
      {
        pr: "pr://family/291-base",
        familyBase: "family/291-base",
        expectedHead: "ship-head",
      },
    ]);
    // No NEW ship: the prior marker stands, exactly one on the ledger (no re-bump).
    expect(backend.ledger.filter((e) => e.status === "shipped")).toHaveLength(1);
    // Honest: every child is ledger-merged ⇒ already delivered = success.
    expect(result.status).toBe("success");
    expect(result.children.every((c) => c.status === "already_done")).toBe(true);
    expect(result.stopSummary.metadata?.heads?.verifiedCmrHead).toBe(
      "verified-cmr-head",
    );
  });

  it("a current-head shipped marker whose PR no longer verifies fails closed", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.shippedPrOk = false;
    backend.shippedPrFailureReason = "PR is CLOSED but must be OPEN";
    backend.ledger.push(
      { childIssue: 294, status: "merged" },
      { childIssue: 295, status: "merged" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://family/291-base",
        familyHeadAfter: "ship-head",
      },
    );

    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      reconcileGit: new StaticReconcileGit("ship-head"),
    });

    expect(backend.verifyCalls.map((v) => v.phase)).not.toContain("final");
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.verifyShippedPrCalls).toEqual([
      {
        pr: "pr://family/291-base",
        familyBase: "family/291-base",
        expectedHead: "ship-head",
      },
    ]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "escalated",
      event: "escalated",
      phase: "final",
      escalationKind: "failure",
      reason: "family shipped marker no longer verifies: PR is CLOSED but must be OPEN",
      familyHeadAfter: "ship-head",
    }));
    expect(result.status).toBe("escalated");
    expect(result.children.every((c) => c.status === "already_done")).toBe(true);
  });

  it("a current-head shipped marker fails closed when the backend cannot re-verify the PR", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    }) as CapableFamilyBackend & { verifyFamilyShippedPr?: undefined };
    backend.verifyFamilyShippedPr = undefined;
    backend.ledger.push(
      { childIssue: 294, status: "merged" },
      { childIssue: 295, status: "merged" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://family/291-base",
        familyHeadAfter: "ship-head",
      },
    );

    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      reconcileGit: new StaticReconcileGit("ship-head"),
    });

    expect(backend.verifyCalls.map((v) => v.phase)).not.toContain("final");
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "escalated",
      event: "escalated",
      phase: "final",
      escalationKind: "failure",
      reason:
        "family ledger contains a shipped marker but this backend cannot verify the PR still covers the current family HEAD",
      familyHeadAfter: "ship-head",
    }));
    expect(result.status).toBe("escalated");
  });

  it("a legacy headless shipped marker fails closed instead of re-shipping", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.ledger.push(
      { childIssue: 294, status: "merged" },
      { childIssue: 295, status: "merged" },
      { status: "shipped", event: "shipped", phase: "final", pr: "pr://legacy" },
    );
    backend.liveHead = "new-head";

    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      reconcileGit: new StaticReconcileGit("ship-head"),
    });

    expect(backend.verifyCalls.map((v) => v.phase)).not.toContain("final");
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.ledger.filter((e) => e.status === "shipped")).toHaveLength(1);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "escalated",
      event: "escalated",
      phase: "final",
      escalationKind: "failure",
      reason: "family reconcile found the live family-base HEAD inconsistent with the ledger",
      familyHeadAfter: "ship-head",
    }));
    expect(result.status).toBe("escalated");
    expect(result.children.every((c) => c.status === "merged")).toBe(true);
  });

  it("a legacy headless shipped marker also fails closed when no reconcile seam is active", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.ledger.push(
      { childIssue: 294, status: "merged" },
      { childIssue: 295, status: "merged" },
      { status: "shipped", event: "shipped", phase: "final", pr: "pr://legacy" },
    );

    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });

    expect(backend.verifyCalls.map((v) => v.phase)).not.toContain("final");
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.ledger.filter((e) => e.status === "shipped")).toHaveLength(1);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "escalated",
      event: "escalated",
      phase: "final",
      escalationKind: "failure",
      reason:
        "family ledger contains a legacy shipped marker without familyHeadAfter; cannot prove which family HEAD the prior PR covered",
    }));
    expect(result.status).toBe("escalated");
  });

  it("a current-head shipped marker skips the final barrier even without reconcileGit", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.liveHead = "ship-head";
    backend.ledger.push(
      { childIssue: 294, status: "merged" },
      { childIssue: 295, status: "merged" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://current",
        familyHeadAfter: "ship-head",
      },
    );

    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });

    expect(backend.verifyCalls.map((v) => v.phase)).not.toContain("final");
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.verifyShippedPrCalls).toEqual([
      { pr: "pr://current", familyBase: "family/291-base", expectedHead: "ship-head" },
    ]);
    expect(backend.ledger.filter((e) => e.status === "shipped")).toHaveLength(1);
    expect(result.status).toBe("success");
    expect(result.familyHead).toBe("ship-head");
  });

  it("a bound shipped marker fails closed when the current family HEAD cannot be resolved", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.ledger.push(
      { childIssue: 294, status: "merged" },
      { childIssue: 295, status: "merged" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://current",
        familyHeadAfter: "ship-head",
      },
    );

    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });

    expect(backend.verifyCalls.map((v) => v.phase)).not.toContain("final");
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.ledger.filter((e) => e.status === "shipped")).toHaveLength(1);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "escalated",
      event: "escalated",
      phase: "final",
      escalationKind: "failure",
      reason: "family ledger contains a shipped marker but current family HEAD could not be resolved",
    }));
    expect(result.status).toBe("escalated");
  });

  it("a shipped marker for an older family HEAD does NOT skip the final barrier", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.5", "agy"] }),
    });
    backend.liveHead = "new-head";
    backend.ledger.push(
      { childIssue: 294, status: "merged", childHead: "c294", familyHeadAfter: "old-head" },
      { childIssue: 295, status: "merged", childHead: "c295" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://old",
        familyHeadAfter: "old-head",
      },
    );

    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      reconcileGit: new StaticReconcileGit("new-head"),
    });

    expect(backend.verifyCalls.map((v) => v.phase)).toContain("final");
    expect(backend.cmrCalls.map((c) => c.cmrPass)).toEqual(["completeness", "correctness"]);
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
    expect(backend.ledger.filter((e) => e.status === "shipped")).toHaveLength(2);
    expect(backend.ledger).toContainEqual(expect.objectContaining({
      status: "shipped",
      event: "shipped",
      phase: "final",
      pr: "pr://family/291-base",
      familyHeadAfter: "new-head",
    }));
    expect(result.status).toBe("success");
  });
});
