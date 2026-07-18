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

describe("#296 spine integration — fail-safe: verify-green but a required final-barrier capability missing must NOT be success", () => {
  it("a real backend that verifies green but lacks runIntegratedCmr leaves the run cmr_failed (NOT a false success)", async () => {
    // The 承重闸 (integrated cmr, decision 3⑥) cannot run, so the run must NOT report
    // success — that would ship code the integrated cmr never reviewed. The spine
    // ignores the hook's `ran` flag and acts on `ok`, so the hook must fail-safe to
    // ok:false (verify_failed at the final phase) rather than the nothing-ran no-op.
    class VerifyOnlySpineBackend implements FamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

      readonly ledger: FamilyLedgerEntry[] = [];
      readonly verifyCalls: FamilyVerifyRequest[] = [];
      async mergeChildIntoFamilyBase(c: MergeRequest): Promise<{ familyHead: string }> {
        return { familyHead: `+${c.childIssue}` };
      }
  async resolveMergeConflict(_req?: unknown): Promise<{ familyHead: string }> {
    throw new Error("resolveMergeConflict not used in this test");
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
      // No integrated-CMR or family worker capability (a real-but-incomplete backend).
    }
    const backend = new VerifyOnlySpineBackend();
    const result = await runFamily({
      epic: epicWith(294),
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/291-base",
      // NO verifyCmr injection → the spine uses #296's real runVerifyCmr.
    });
    // Wave verify green + #961 IC checkpoint; missing CMR capability fails the
    // checkpoint (or final) with cmr_failed (#922), never success.
    expect(backend.verifyCalls.map((v) => v.phase)).toEqual([
      "wave",
      "correctness_checkpoint",
    ]);
    expect(result.status).toBe("failed");
    expect(result.stopSummary.reason).toBe("cmr_failed");
    expect(result.failedPhase).toBe("correctness_checkpoint");
  });
});
