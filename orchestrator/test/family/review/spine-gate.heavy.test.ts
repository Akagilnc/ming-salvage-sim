import {
  describe,
  expect,
  it,
  mkdtempSync,
  writeFileSync,
  tmpdir,
  join,
  execFileSync,
  findingIdentityKey,
  legacyDispatchFamilyWorker,
  recordFamilyEscalated,
  runFamily,
  legacyCmrScriptToWorkerOutput,
  Backend,
  DispatchContext,
  Finding,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  WorkerResult,
  WorkerSpec,
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
  ReconcileGit,
  buildExplicitLandingLiveHooks,
  ChildBackend,
  makeFamilyDocReleaseRepo,
  CapableFamilyBackend,
  StaticReconcileGit,
  TWO_WAVES,
  epicWith,
} from "./spine-gate.shared.js";

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
    expect(result.status).toBe("failed");
    expect(result.failedPhase).toBe("wave");
    const byIssue = new Map(result.children.map((c) => [c.issue, c.status]));
    expect(byIssue.get(294)).toBe("merged");
    expect(byIssue.get(296)).toBe("skipped");
    // No PR opened on a red run.
    expect(backend.prCalls).toEqual([]);
  });
});

describe("#296 spine integration — acceptance 2: integrated cmr gate → escalate续跑", () => {
  it("resumes after a committed CMR coder-fix with protected finding keys", async () => {
    const priorKey = "completeness|orchestrator/src/x.ts:12|restart final barrier";
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: (req) => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
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

    expect(result.status).toBe("completed");
    expect(backend.cmrCalls[0]).toMatchObject({
      cmrPass: "completeness",
      priorCmrFindingIdentityKeys: [priorKey],
    });
  });

  it("resumes after multiple committed CMR coder-fixes with all unclosed protected finding keys", async () => {
    const firstKey = "completeness|orchestrator/src/a.ts:12|first blocker";
    const secondKey = "completeness|orchestrator/src/b.ts:34|second blocker";
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: (req) => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        ...(req.priorCmrFindingIdentityKeys !== undefined
          ? {
              claimedFixedFindingIdentityKeys: [firstKey, secondKey],
              priorFindingDispositions: [
                {
                  identityKey: firstKey,
                  status: "verified-closed" as const,
                  evidence: "first CMR blocker remained protected across resume",
                },
                {
                  identityKey: secondKey,
                  status: "verified-closed" as const,
                  evidence: "second CMR blocker remained protected across resume",
                },
              ],
            }
          : {}),
      }),
    });
    backend.liveHead = "head-after-second-cmr-fix";
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
        familyHeadAfter: "head-after-first-cmr-fix",
        blockingFindingIdentityKeys: [firstKey],
      } as FamilyLedgerEntry,
      {
        status: "cmr_reviewed",
        event: "cmr_reviewed",
        phase: "final",
        cmrPass: "completeness",
        reason: "fresh CMR found a second blocker",
        familyHeadAfter: "head-after-first-cmr-fix",
        // #604 slice 3 / ADR 0062: this seed's old fat blob had `blocking: []` (the
        // runner recovered `secondKey` from the following cmr_fix_committed row, not
        // this review row); the thin equivalent is an empty envelope.
        blockingFindingIdentityKeys: [],
      } as FamilyLedgerEntry,
      {
        status: "cmr_fix_committed",
        event: "cmr_fix_committed",
        phase: "final",
        cmrPass: "completeness",
        familyHeadBefore: "head-after-first-cmr-fix",
        familyHeadAfter: "head-after-second-cmr-fix",
        blockingFindingIdentityKeys: [secondKey],
      } as FamilyLedgerEntry,
    );

    const result = await runFamily({
      epic: epicWith(294),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      reconcileGit: {
        async liveFamilyHead() {
          return "head-after-second-cmr-fix";
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

    expect(result.status).toBe("completed");
    expect(backend.cmrCalls[0]).toMatchObject({
      cmrPass: "completeness",
      priorCmrFindingIdentityKeys: [firstKey, secondKey],
    });
  });

  it("resumes after a CMR coder-fix commit crash window with protected finding keys", async () => {
    const priorFinding: Finding = {
      severity: "medium",
      category: "correctness",
      claim_quote: "family CMR coder-fix must restart the final barrier",
      location: "orchestrator/src/family/verifyCmr.ts:runCmrCoderFix",
      suggested_fix: "restart final verify and pass the protected prior key",
      action: "fix_now",
    };
    const priorKey = findingIdentityKey(priorFinding);
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: (req) => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        ...(req.priorCmrFindingIdentityKeys !== undefined
          ? {
              claimedFixedFindingIdentityKeys: [priorKey],
              priorFindingDispositions: [
                {
                  identityKey: priorKey,
                  status: "verified-closed" as const,
                  evidence: "resume protected the coder-fix finding key",
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
        status: "cmr_reviewed",
        event: "cmr_reviewed",
        phase: "final",
        cmrPass: "completeness",
        reason: "blocking family CMR finding requires coder-fix",
        familyHeadAfter: "head-before-cmr-fix",
        // #604 slice 3 / ADR 0062: the runner recovers protected prior keys from the
        // thin `blockingFindingIdentityKeys` envelope, not the retired fat blob.
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

    expect(result.status).toBe("completed");
    expect(backend.cmrCalls[0]).toMatchObject({
      cmrPass: "completeness",
      priorCmrFindingIdentityKeys: [priorKey],
    });
  });

  it("does not resurrect older CMR coder-fix keys after a same-head re-review", async () => {
    const staleKey = "completeness|orchestrator/src/x.ts:12|already re-reviewed";
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
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
        blockingFindingIdentityKeys: [staleKey],
      } as FamilyLedgerEntry,
      {
        status: "cmr_reviewed",
        event: "cmr_reviewed",
        phase: "final",
        cmrPass: "completeness",
        reason: "same head has already been re-reviewed after the coder-fix",
        familyHeadAfter: "head-after-cmr-fix",
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

    expect(result.status).toBe("completed");
    expect(backend.cmrCalls[0]).toMatchObject({
      cmrPass: "completeness",
    });
    expect(backend.cmrCalls[0]?.priorCmrFindingIdentityKeys).toBeUndefined();
  });

  it("does not treat an aborted coder-fix evidence failure as a crash-window fix", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      }),
    });
    backend.liveHead = "head-after-bad-coder-fix";
    backend.ledger.push(
      {
        childIssue: 294,
        status: "merged",
        childHead: "c294",
        familyHeadAfter: "head-before-cmr-fix",
      },
      {
        status: "cmr_reviewed",
        event: "cmr_reviewed",
        phase: "final",
        cmrPass: "completeness",
        reason: "blocking family CMR finding requires coder-fix",
        familyHeadAfter: "head-before-cmr-fix",
        // #604 slice 3 / ADR 0062: thin equivalent of the old `blocking: []` blob —
        // an empty envelope yields no recoverable prior keys.
        blockingFindingIdentityKeys: [],
      } as FamilyLedgerEntry,
      {
        status: "aborted",
        event: "aborted",
        phase: "final",
        cmrPass: "completeness",
        reason:
          "integrated cmr completeness coder-fix repair evidence gate failed after 3 attempts",
        familyHeadAfter: "head-after-bad-coder-fix",
        stopSummary: {
          reason: "contract_drift",
          summary:
            "integrated CMR completeness coder-fix failed: repair evidence gate failed",
          repairHint:
            "repair the family CMR coder-fix worker contract, then rerun the family CMR gate",
        },
      } as FamilyLedgerEntry,
    );

    const result = await runFamily({
      epic: epicWith(294),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      reconcileGit: {
        async liveFamilyHead() {
          return "head-after-bad-coder-fix";
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

    expect(result.status).toBe("completed");
    expect(backend.cmrCalls[0]).toMatchObject({
      cmrPass: "completeness",
    });
    expect(backend.cmrCalls[0]?.priorCmrFindingIdentityKeys).toBeUndefined();
  });

  });

describe("#296 spine integration — acceptance 3: all green → open PR, stop, no merge-to-main", () => {
  it("green verify + converged cmr ⇒ the family PR is opened and the run is success (止于 PR)", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
    });
    const result = await runFamily({
      epic: epicWith(294, 295, 298),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });
    // One wave: wave verify → #961 IC checkpoint → final completeness→correctness→ship.
    expect(backend.verifyCalls.map((v) => v.phase)).toEqual([
      "wave",
      "correctness_checkpoint",
      "final",
    ]);
    // Checkpoint runs correctness early; final reuses skip or re-runs + completeness.
    const cmrPasses = backend.cmrCalls.map((c) => c.cmrPass);
    expect(cmrPasses).toContain("completeness");
    expect(cmrPasses.filter((p) => p === "correctness").length).toBeGreaterThanOrEqual(1);
    expect(cmrPasses[0]).toBe("correctness"); // checkpoint first
    expect(cmrPasses).toContain("completeness");
    expect(backend.prCalls).toEqual([{ familyBase: "family/291-base" }]);
    // 止于 PR: a PR was opened, but the run STOPS here — every child merged into the
    // family base, status success, no escalate. (No merge-to-main seam exists on
    // FamilyBackend at all — the family layer cannot merge to main by construction.)
    expect(result.status).toBe("completed");
    expect(result.children.every((c) => c.status === "merged")).toBe(true);
    expect(backend.escalations).toEqual([]);
  });
});

describe("#291 spine — the final barrier (verify + cmr + 止于 PR) is GATED on a COMPLETE family base (online R1 Codex P1)", () => {
  // A child whose single-slice run does NOT succeed (coder commits nothing → S2
  // routes to S8 error → a non-throwing "failed") leaves the family base PARTIAL:
  // the wave loop exits with that child unmerged and finalize() marks the run
  // "incomplete". The final barrier (full verify → integrated cmr → ship worker) is
  // meaningful ONLY for a COMPLETE base — running it on a partial base would open a
  // family PR missing slices, even though the returned status is not shippable. So
  // the spine must SKIP the final barrier (no final verify / cmr / PR) when not every
  // epic child is ledger-merged, and return "incomplete" honestly.
  class FailingCoderChildBackend extends ChildBackend {
    override async runStep(spec: StepSpec): Promise<StepOutput> {
      if (spec.role === "coder") throw new Error("coder process crashed");
      return { kind: "judge", status: "converged" };
    }
  }
  it("a child that fails its single-slice run ⇒ NO final verify / cmr / PR, status incomplete", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
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
    expect(result.status).toBe("failed");
    expect(result.children.every((c) => c.status === "failed")).toBe(true);
  });
});

describe("#330 spine — shipped resume continues after the delivery checkpoint", () => {
  it("does not rerun final verify/cmr/ship", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({ converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] }),
    });
    backend.ledger.push(
      { childIssue: 294, status: "merged" },
      { childIssue: 295, status: "merged" },
      {
        status: "shipped",
        event: "shipped",
        phase: "final",
        pr: "pr://previous",
        familyHeadAfter: "ship-head",
      },
    );
    backend.liveHead = "ship-head";

    const result = await runFamily({
      epic: epicWith(294, 295),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
    });

    expect(backend.verifyCalls.map((v) => v.phase)).not.toContain("final");
    expect(backend.cmrCalls).toEqual([]);
    expect(backend.prCalls).toEqual([]);
    expect(backend.ledger.filter((entry) => entry.status === "shipped")).toHaveLength(1);
    expect(backend.ledger.some((entry) => entry.status === "review_loop_converged")).toBe(true);
    expect(result.status).toBe("completed");
  });
});
