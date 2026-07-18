import {
  describe,
  expect,
  it,
  lastCorrectnessConvergedHeadFromLedger,
  recordCmrPassed,
  runFamily,
  runVerifyCmr,
  activeModelRoute,
  modelRouteFingerprint,
  QuotaWaitForResetError,
  legacyCmrScriptToWorkerOutput,
  legacyDispatchFamilyWorker,
  buildExplicitLandingLiveHooks,
  Backend,
  DispatchContext,
  IssueMeta,
  PersistentLedgerEntry,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  WorkerResult,
  WorkerSpec,
  FamilyBackend,
  FamilyEpic,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  MergeRequest,
  mkdtempSync,
  readFileSync,
  writeFileSync,
  tmpdir,
  join,
  execFileSync,
  icQuotaParkError,
  currentRouteFingerprint,
  makeFamilyDocReleaseRepo,
  ChildBackend,
  CapableFamilyBackend,
} from "./incremental-correctness-961.shared.js";

describe("#961 lastCorrectnessConvergedHeadFromLedger — durable single source", () => {

  it("recordCmrPassed correctness writes the durable anchor readable by the helper", async () => {
    const backend = new CapableFamilyBackend();
    await recordCmrPassed(backend, {
      cmrPass: "correctness",
      familyHeadAfter: "converged-head",
      routeFingerprint: currentRouteFingerprint(),
      phase: "correctness_checkpoint",
    });
    expect(lastCorrectnessConvergedHeadFromLedger(backend.ledger)).toBe(
      "converged-head",
    );
  });
});

describe("#961 runVerifyCmr correctness_checkpoint — full-strength IC only", () => {
  it("GREEN verify + correctness → ok; no completeness pass; no ship", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      }),
    });
    const result = await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/961-base",
      familyBackend: backend,
      familyHeadAfter: "target-head",
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.verifyCalls.map((v) => v.phase)).toEqual([
      "correctness_checkpoint",
    ]);
    expect(backend.cmrCalls.map((c) => c.cmrPass)).toEqual(["correctness"]);
    expect(backend.prCalls).toEqual([]);
    const passed = backend.ledger.filter((e) => e.status === "cmr_passed");
    expect(passed).toHaveLength(1);
    expect(passed[0]?.cmrPass).toBe("correctness");
    expect(passed[0]?.phase).toBe("correctness_checkpoint");
    expect(lastCorrectnessConvergedHeadFromLedger(backend.ledger)).toBe(
      backend.currentFamilyHead,
    );
  });

  it("skips re-running correctness when already converged for current HEAD+route", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      }),
    });
    backend.currentFamilyHead = "same-head";
    backend.ledger.push({
      status: "cmr_passed",
      event: "cmr_passed",
      phase: "correctness_checkpoint",
      cmrPass: "correctness",
      familyHeadAfter: "same-head",
      routeFingerprint: currentRouteFingerprint(),
    });
    const result = await runVerifyCmr({
      phase: "correctness_checkpoint",
      familyBase: "family/961-base",
      familyBackend: backend,
      familyHeadAfter: "same-head",
    });
    expect(result).toEqual({ ok: true, ran: true });
    expect(backend.cmrCalls).toEqual([]);
  });
});

describe("#961 spine — incremental IC after batch verify green", () => {
  const TWO_WAVES: FamilyEpic = {
    issue: 961,
    children: [
      { issue: 1001, blockedBy: [] },
      { issue: 1002, blockedBy: [1001] },
    ],
  };

  it("fires a correctness checkpoint after each wave verify green; final still completeness→correctness", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      }),
    });
    const result = await runFamily({
      epic: TWO_WAVES,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/961-base",
    });
    expect(result.status).toBe("completed");

    // Wave verify ×2 + checkpoint verify ×2 + final verify
    const phases = backend.verifyCalls.map((v) => v.phase);
    expect(phases.filter((p) => p === "wave")).toHaveLength(2);
    expect(phases.filter((p) => p === "correctness_checkpoint").length).toBeGreaterThanOrEqual(
      2,
    );
    expect(phases).toContain("final");

    // Checkpoint + final correctness courts; completeness only at final.
    const cmrPasses = backend.cmrCalls.map((c) => c.cmrPass);
    const correctnessCount = cmrPasses.filter((p) => p === "correctness").length;
    const completenessCount = cmrPasses.filter((p) => p === "completeness").length;
    expect(correctnessCount).toBeGreaterThanOrEqual(2);
    expect(completenessCount).toBe(1);

    // Durable lineage anchor is last correctness-green head.
    expect(lastCorrectnessConvergedHeadFromLedger(backend.ledger)).toBeDefined();
  });

  it("checkpoint target is the verify-green HEAD; later merge is only in the next checkpoint", async () => {
    const checkpointTargets: string[] = [];
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: (req) => {
        if (req.cmrPass === "correctness") {
          // Capture head at the moment correctness court opens (target).
          checkpointTargets.push(backend.currentFamilyHead);
        }
        return {
          converged: true,
          successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
        };
      },
    });

    await runFamily({
      epic: TWO_WAVES,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/961-base",
    });

    // First correctness after wave1 must see only +1001 (not +1002).
    expect(checkpointTargets[0]).toBe("+1001");
    // A later correctness after wave2 includes +1002.
    expect(checkpointTargets.some((h) => h === "+1002")).toBe(true);
    // First checkpoint never saw wave2 merge as its target.
    expect(checkpointTargets[0]).not.toBe("+1002");
  });

  // CORR-C1 / #961: Wave1 fires IC → Wave2 coding settles in parallel → IC fails
  // before merge. Early return must drain settled wave siblings (reuse #938) so
  // executed children stay honest `ran`, not finalize residual-mapped `skipped`.
  it("CORR-C1: IC fail after next-wave settle keeps executed sibling as ran (not skipped)", async () => {
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      }),
    });
    const result = await runFamily({
      epic: TWO_WAVES,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/961-base",
      verifyCmr: async (input) => {
        if (input.phase === "wave") return { ok: true, ran: true };
        if (input.phase === "correctness_checkpoint") {
          return { ok: false, ran: true, failedStatus: "cmr_failed" };
        }
        return { ok: true, ran: true };
      },
    });

    expect(result.status).toBe("failed");
    expect(result.failedPhase).toBe("correctness_checkpoint");
    // Wave1 already merged before IC was fired.
    expect(result.children.find((c) => c.issue === 1001)).toEqual(
      expect.objectContaining({ issue: 1001, status: "merged" }),
    );
    // Wave2 child allSettled while IC was in flight — must remain honest `ran`.
    const wave2 = result.children.find((c) => c.issue === 1002);
    expect(wave2?.status).toBe("ran");
    expect(wave2?.status).not.toBe("skipped");
    expect(wave2?.branch).toEqual(expect.stringMatching(/1002/));
  });

  // CORR-C2 / #961: Wave1 fires IC → Wave2 coding settles → IC throws QuotaWait
  // park. Park return must drain/remount settled wave siblings (same honesty as
  // CORR-C1 fail path + merge-wall residualChildrenAfterDrain) so executed
  // children stay `ran`, not residual-mapped fake `skipped`.
  it("CORR-C2: IC quota-park after next-wave settle keeps executed sibling as ran (not skipped)", async () => {
    const now = new Date("2026-07-14T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 10 * 60 * 1000);
    const backend = new CapableFamilyBackend({
      verify: () => ({ ok: true }),
      cmr: () => ({
        converged: true,
        successfulLegs: ["opus", "gpt-5.6-sol", "agy"],
      }),
    });
    const result = await runFamily({
      epic: TWO_WAVES,
      familyBackend: backend,
      singleSliceBackend: new ChildBackend(),
      familyBase: "family/961-base",
      now: () => now,
      verifyCmr: async (input) => {
        if (input.phase === "wave") return { ok: true, ran: true };
        if (input.phase === "correctness_checkpoint") {
          throw icQuotaParkError(resetAt);
        }
        return { ok: true, ran: true };
      },
    });

    expect(result.status).toBe("parked");
    expect(result.stopSummary.reason).toBe("provider_degraded");
    // Wave1 already merged before IC was fired.
    expect(result.children.find((c) => c.issue === 1001)).toEqual(
      expect.objectContaining({ issue: 1001, status: "merged" }),
    );
    // Wave2 child allSettled while IC was in flight — must remain honest `ran`.
    // FamilyChildStatus `skipped` = never-ran; residual-map fake skipped is the bug.
    const wave2 = result.children.find((c) => c.issue === 1002);
    expect(wave2?.status).toBe("ran");
    expect(wave2?.status).not.toBe("skipped");
    expect(wave2?.branch).toEqual(expect.stringMatching(/1002/));
  });
});
