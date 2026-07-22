import {
  execFileSync,
  mkdtempSync,
  rmSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  sc,
  cmrWorkerSpec,
  RealFamilyBackend,
  CmrAuth,
  runVerifyCmr,
  familyJudgeResumeSessionIdFromPriorRows,
  resumeCapableForSlug,
  resolveActiveModelRoute,
  smokeRouteModels,
  skeletonReviewLoopWorkerResult,
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
  FINDING,
  ROUND1_SESSION,
  GROK_SLUG,
  cleanups,
  mkDir,
  realRepo966,
  completedJudge,
  FamilyJudgeLedgerBackend,
  grokCmrRoute,
} from "./family-judge-session-ledger-966.shared.js";

afterEach(() => {
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

describe("#966 family judge session from ledger", () => {

  it("two consecutive final CMR rounds: round-2 judge resumes round-1 session (ledger)", async () => {
    // Round 1 opens fresh, records sessionId on cmr_reviewed / cmr_passed.
    // Round 2 is a NEW runVerifyCmr (external head advance — barrier re-entry).
    // Without ledger-derived resume, round-2 would open fresh every time.
    const backend = new FamilyJudgeLedgerBackend({
      completeness: (round) => {
        if (round === 0) {
          return completedJudge(judgeContinue([FINDING]), ROUND1_SESSION);
        }
        return completedJudge(judgeConverged(), ROUND1_SESSION);
      },
      correctness: () =>
        completedJudge(judgeConverged(), `${ROUND1_SESSION}-correctness`),
    });
    const route = await grokCmrRoute();

    const round1 = await runVerifyCmr({
      phase: "final",
      familyBase: "family/966-base",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(round1).toEqual({ ok: true, ran: true });

    const round1Completeness = backend.dispatches.filter(
      (d) => d.kind === "cmr" && d.cmrPass === "completeness",
    );
    expect(round1Completeness.length).toBeGreaterThanOrEqual(2);
    expect(round1Completeness[0]?.session).toBe("fresh");
    expect(round1Completeness[0]?.resumeSessionId).toBeUndefined();
    // Within-round fix re-open must also resume (ledger sole truth after #966).
    expect(round1Completeness[1]?.session).toBe("resume");
    expect(round1Completeness[1]?.resumeSessionId).toBe(ROUND1_SESSION);
    // Grok seat was the real dispatch model for the court.
    expect(round1Completeness[0]?.model).toBe(GROK_SLUG);
    expect(round1Completeness[1]?.model).toBe(GROK_SLUG);
    expect(resumeCapableForSlug(round1Completeness[1]!.model!)).toBe(true);

    // Ledger is the durable source: sessionId on court rows for completeness.
    expect(
      backend.ledger.some(
        (e) =>
          (e.status === "cmr_reviewed" || e.status === "cmr_passed") &&
          e.cmrPass === "completeness" &&
          e.sessionId === ROUND1_SESSION,
      ),
    ).toBe(true);

    // External head advance (not barrier-internal-only) forces re-open of courts.
    const dispatchCountAfterRound1 = backend.dispatches.length;
    backend.currentFamilyHead = "head-external-round2";
    backend.resetRoundCounters();

    const round2 = await runVerifyCmr({
      phase: "final",
      familyBase: "family/966-base",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(round2).toEqual({ ok: true, ran: true });

    const round2Completeness = backend.dispatches
      .slice(dispatchCountAfterRound1)
      .filter((d) => d.kind === "cmr" && d.cmrPass === "completeness");
    expect(round2Completeness.length).toBeGreaterThanOrEqual(1);
    // #966 core: next final-barrier round resumes the ledger session — not fresh.
    expect(round2Completeness[0]?.session).toBe("resume");
    expect(round2Completeness[0]?.resumeSessionId).toBe(ROUND1_SESSION);
    expect(round2Completeness[0]?.model).toBe(GROK_SLUG);
    // priorJudgeVerdicts still land for trajectory (even on resume).
    expect(
      (round2Completeness[0]?.priorJudgeVerdicts?.length ?? 0) > 0,
    ).toBe(true);
  });

  it("session truly absent after judge continue → fresh reopen with priorJudgeVerdicts (soul law)", async () => {
    const backend = new FamilyJudgeLedgerBackend({
      completeness: (round, ctx) => {
        if (round === 0) {
          // No sessionId on WorkerResult: next open is fresh + priors, not fail-loud.
          return { kind: "completed", output: judgeContinue([FINDING]) };
        }
        expect(ctx.resumeSessionId).toBeUndefined();
        expect((ctx.priorJudgeVerdicts?.length ?? 0) > 0).toBe(true);
        return completedJudge(judgeConverged(), "fresh-after-loss-966");
      },
    });
    const route = await grokCmrRoute();
    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/966-loss",
      familyBackend: backend,
      modelRoute: route,
    });
    expect(result).toEqual({ ok: true, ran: true });
    const opens = backend.dispatches.filter(
      (d) => d.kind === "cmr" && d.cmrPass === "completeness",
    );
    expect(opens.length).toBeGreaterThanOrEqual(2);
    expect(opens[0]?.session).toBe("fresh");
    expect(opens[0]?.resumeSessionId).toBeUndefined();
    expect(opens[1]?.session).toBe("fresh");
    expect(opens[1]?.resumeSessionId).toBeUndefined();
    expect((opens[1]?.priorJudgeVerdicts?.length ?? 0) > 0).toBe(true);
    expect(backend.dispatches.some((d) => d.kind === "coder")).toBe(true);
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "aborted" &&
          e.cmrPass === "completeness" &&
          typeof e.reason === "string" &&
          e.reason.includes("#1081") &&
          e.reason.includes("no sessionId"),
      ),
    ).toBe(false);
  });

  it("older lost continue covered by a newer verdict no longer creates resume obligation", async () => {
    const backend = new FamilyJudgeLedgerBackend({
      completeness: (round, ctx) => {
        expect(round).toBe(0);
        expect(ctx.resumeSessionId).toBeUndefined();
        return completedJudge(judgeConverged(), "replacement-session-966");
      },
      coder: () => {
        throw new Error("newest converged verdict must not route through coder-fix");
      },
    });
    backend.ledger.push(
      {
        status: "cmr_reviewed",
        event: "cmr_reviewed",
        phase: "final",
        cmrPass: "completeness",
        judgeStatus: "continue",
        reason: "older continue without sessionId is covered by a newer verdict",
      } as FamilyLedgerEntry,
      {
        status: "cmr_passed",
        event: "cmr_passed",
        phase: "final",
        cmrPass: "completeness",
        judgeStatus: "converged",
        reason: "newer verdict intentionally has no sessionId",
      } as FamilyLedgerEntry,
    );
    const route = await grokCmrRoute();

    const result = await runVerifyCmr({
      phase: "final",
      familyBase: "family/966-covered-continue",
      familyBackend: backend,
      modelRoute: route,
    });

    expect(result).toEqual({ ok: true, ran: true });
    const opens = backend.dispatches.filter(
      (d) => d.kind === "cmr" && d.cmrPass === "completeness",
    );
    expect(opens).toHaveLength(1);
    expect(opens[0]?.session).toBe("fresh");
    expect(opens[0]?.resumeSessionId).toBeUndefined();
    expect(
      backend.ledger.some(
        (e) =>
          e.status === "aborted" &&
          e.cmrPass === "completeness" &&
          typeof e.reason === "string" &&
          e.reason.includes("#1081"),
      ),
    ).toBe(false);
  });

});
