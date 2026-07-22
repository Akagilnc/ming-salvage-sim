import {
  execFileSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  vi,
  sc,
  familyCoderFixWorkerSpec,
  familyCoderFixResumeSessionIdFromLedger,
  recordCmrFixCommitted,
  RealFamilyBackend,
  CmrAuth,
  runVerifyCmr,
  resumeCapableForSlug,
  resolveActiveModelRoute,
  smokeRouteModels,
  skeletonReviewLoopWorkerResult,
  judgeReviewLegSessionMode,
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  MergeRequest,
  DispatchContext,
  JudgeResult,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  judgeConverged,
  judgeContinue,
  sampleFinding,
  buildExplicitLandingLiveHooks,
  here,
  realPromptsDir,
  realSoulsDir,
  FINDING_R1,
  FINDING_R2,
  FIXER_SESSION,
  GROK_SLUG,
  cleanups,
  mkDir,
  realRepo979,
  completedJudge,
  completedCoder,
  FamilyCoderFixLedgerBackend,
  resumeCapableCoderFixRoute,
} from "./family-coder-fix-session-979.shared.js";

afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

describe("#979 family coder-fix chain resume from ledger", () => {
  it("same-chain second fix round resumes first-round session (real resume path)", async () => {
    // Round shape: judge continue → coder-fix (sess A) → re-open judge continue
    // → coder-fix MUST resume A → re-open judge converged.
    const backend = new FamilyCoderFixLedgerBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING_R1]), "judge-979");
        }
        if (round === 1) {
          return completedJudge(judgeContinue([FINDING_R2]), "judge-979");
        }
        return completedJudge(judgeConverged(), "judge-979");
      },
      coder: (round, ctx) => {
        if (round === 0) {
          expect(ctx.resumeSessionId).toBeUndefined();
          return completedCoder(FIXER_SESSION);
        }
        // Round 2: real resume of the first fix session.
        expect(ctx.resumeSessionId).toBe(FIXER_SESSION);
        return completedCoder(FIXER_SESSION);
      },
    });
    const route = await resumeCapableCoderFixRoute();
    expect(resumeCapableForSlug(route.slots.coderFix)).toBe(true);

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/979-base",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(result).toEqual({ ok: true, ran: true });

    const coderDispatches = backend.dispatches.filter((d) => d.kind === "coder");
    expect(coderDispatches.length).toBeGreaterThanOrEqual(2);
    expect(coderDispatches[0]?.session).toBe("fresh");
    expect(coderDispatches[0]?.resumeSessionId).toBeUndefined();
    expect(coderDispatches[0]?.model).toBe(route.slots.coderFix);

    expect(coderDispatches[1]?.session).toBe("resume");
    expect(coderDispatches[1]?.resumeSessionId).toBe(FIXER_SESSION);
    expect(coderDispatches[1]?.model).toBe(route.slots.coderFix);

    // Ledger sole truth: sessionId on cmr_fix_committed.
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "cmr_fix_committed" &&
          e.cmrPass === "completeness" &&
          e.sessionId === FIXER_SESSION,
      ),
    ).toBe(true);
  });

  it("session truly absent → second fix opens fresh (negative)", async () => {
    const backend = new FamilyCoderFixLedgerBackend({
      completeness: (round) => {
        if (round <= 1) {
          return completedJudge(
            judgeContinue([round === 0 ? FINDING_R1 : FINDING_R2]),
            "judge-979-loss",
          );
        }
        return completedJudge(judgeConverged(), "judge-979-loss");
      },
      coder: (round, ctx) => {
        // No sessionId on WorkerResult → ledger fix row has nothing to resume.
        expect(ctx.resumeSessionId).toBeUndefined();
        return completedCoder(); // deliberately omit sessionId
      },
    });
    const route = await resumeCapableCoderFixRoute();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/979-loss",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(result).toEqual({ ok: true, ran: true });

    const coderDispatches = backend.dispatches.filter((d) => d.kind === "coder");
    expect(coderDispatches.length).toBeGreaterThanOrEqual(2);
    expect(coderDispatches[0]?.session).toBe("fresh");
    expect(coderDispatches[1]?.session).toBe("fresh");
    expect(coderDispatches[1]?.resumeSessionId).toBeUndefined();
  });

  it("resume-incapable judge seat → loud terminal, not silent fresh", async () => {
    const backend = new FamilyCoderFixLedgerBackend({
      completeness: (round) => {
        if (round <= 1) {
          return completedJudge(
            judgeContinue([round === 0 ? FINDING_R1 : FINDING_R2]),
            "judge-979-incapable",
          );
        }
        return completedJudge(judgeConverged(), "judge-979-incapable");
      },
      coder: (_round, ctx) => {
        // Capability gate drops resume even when ledger has a prior id.
        expect(ctx.resumeSessionId).toBeUndefined();
        return completedCoder(FIXER_SESSION);
      },
    });
    const route = await resumeCapableCoderFixRoute();
    const mod = await import("../../../src/modelRegistry.js");
    const spy = vi.spyOn(mod, "resumeCapableForSlug").mockReturnValue(false);
    try {
      const result = await runVerifyCmr({
        phase: "final",
        familyBase: "family/979-incapable",
        familyBackend: backend,
        modelRoute: route,
      });
      expect(result).toMatchObject({ ok: false, ran: true, failedStatus: "cmr_failed" });
      const coderDispatches = backend.dispatches.filter((d) => d.kind === "coder");
      expect(coderDispatches).toHaveLength(0);
      expect(
        backend.ledger.some(
          (e) =>
            e.status === "aborted" &&
            e.cmrPass === "completeness" &&
            typeof e.reason === "string" &&
            e.reason.includes("#1081") &&
            e.reason.includes("not resume-capable"),
        ),
      ).toBe(true);
    } finally {
      spy.mockRestore();
    }
  });

  it("reviewer / cmr legs stay fresh (no regression of clean-eyes contract)", async () => {
    expect(judgeReviewLegSessionMode()).toBe("fresh");

    const backend = new FamilyCoderFixLedgerBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING_R1]), "judge-979-fresh");
        }
        return completedJudge(judgeConverged(), "judge-979-fresh");
      },
      coder: () => completedCoder(FIXER_SESSION),
    });
    const route = await resumeCapableCoderFixRoute();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/979-reviewer-fresh",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(result).toEqual({ ok: true, ran: true });

    const cmrDispatches = backend.dispatches.filter((d) => d.kind === "cmr");
    // First open is always fresh; subsequent may resume judge (#966) — that is
    // judge continuity, NOT reviewer-leg clean-eyes. Review legs themselves are
    // always fresh via judgeReviewLegSessionMode.
    expect(cmrDispatches[0]?.session).toBe("fresh");
    // Family cmr kind uses contextRetention clean via cmrWorkerSpec; pin that
    // the first open never carries a fixer resume id.
    for (const d of cmrDispatches) {
      // cmr must never inherit the fixer session id.
      if (d.resumeSessionId !== undefined) {
        expect(d.resumeSessionId).not.toBe(FIXER_SESSION);
      }
    }
  });

  it("recordCmrFixCommitted persists sessionId when provided", async () => {
    const ledger: FamilyLedgerEntry[] = [];
    const backend: Pick<FamilyBackend, "appendFamilyLedger"> = {
      async appendFamilyLedger(entry) {
        ledger.push(entry);
      },
    };
    await recordCmrFixCommitted(backend as FamilyBackend, {
      cmrPass: "completeness",
      familyHeadAfter: "abc",
      blockingFindingIdentityKeys: ["k"],
      sessionId: FIXER_SESSION,
    });
    expect(ledger[0]?.sessionId).toBe(FIXER_SESSION);
    expect(ledger[0]?.status).toBe("cmr_fix_committed");
  });

  it("recordCmrFixCommitted trims sessionId; whitespace-only is omitted", async () => {
    const ledger: FamilyLedgerEntry[] = [];
    const backend: Pick<FamilyBackend, "appendFamilyLedger"> = {
      async appendFamilyLedger(entry) {
        ledger.push(entry);
      },
    };
    await recordCmrFixCommitted(backend as FamilyBackend, {
      cmrPass: "completeness",
      familyHeadAfter: "abc",
      blockingFindingIdentityKeys: ["k"],
      sessionId: `  ${FIXER_SESSION}  `,
    });
    expect(ledger[0]?.sessionId).toBe(FIXER_SESSION);

    await recordCmrFixCommitted(backend as FamilyBackend, {
      cmrPass: "completeness",
      familyHeadAfter: "abc",
      blockingFindingIdentityKeys: ["k"],
      sessionId: "   \t",
    });
    expect(ledger[1]?.sessionId).toBeUndefined();
  });

  it("coder_advance after prior fix invalidates resume through runVerifyCmr entry", async () => {
    // Real entry (not pure-helper-only): seed ledger as a prior fix chain that
    // was later advanced; runVerifyCmr → runCmrCoderFix must open fresh.
    const backend = new FamilyCoderFixLedgerBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING_R1]), "judge-979-adv");
        }
        return completedJudge(judgeConverged(), "judge-979-adv");
      },
      coder: (_round, ctx) => {
        expect(ctx.resumeSessionId).toBeUndefined();
        return completedCoder("post-advance-fresh-979");
      },
    });
    backend.ledger.push(
      {
        status: "cmr_fix_committed",
        event: "cmr_fix_committed",
        phase: "final",
        cmrPass: "completeness",
        sessionId: FIXER_SESSION,
        ts: "2026-01-01T00:00:00.000Z",
      },
      {
        status: "coder_advance",
        event: "coder_advance",
        phase: "final",
        cmrPass: "completeness",
        fromModelId: "gpt-5.6-terra",
        toModelId: "gpt-5.6-sol",
        ts: "2026-01-01T00:01:00.000Z",
      },
    );
    const route = await resumeCapableCoderFixRoute();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/979-advance-entry",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(result).toEqual({ ok: true, ran: true });

    const coderDispatches = backend.dispatches.filter((d) => d.kind === "coder");
    expect(coderDispatches.length).toBeGreaterThanOrEqual(1);
    expect(coderDispatches[0]?.session).toBe("fresh");
    expect(coderDispatches[0]?.resumeSessionId).toBeUndefined();
  });
});
