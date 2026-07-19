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

describe("#979 pure ledger helper — familyCoderFixResumeSessionIdFromLedger", () => {
  it.each([
    {
      name: "empty ledger → undefined",
      ledger: [] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined as string | undefined,
    },
    {
      name: "newest fix row with sessionId wins",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "old",
        },
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "latest",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: "latest",
    },
    {
      name: "newest blank sessionId means fresh (do not resurrect older)",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "kept",
        },
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined,
    },
    {
      name: "whitespace-only sessionId means fresh (trim align write path)",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "  \t  ",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined,
    },
    {
      name: "sessionId with surrounding whitespace is trimmed on read",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "  padded-sess  ",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: "padded-sess",
    },
    {
      name: "other pass fix does not supply this pass resume id",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "correctness",
          sessionId: "corr-only",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined,
    },
    {
      name: "coder_advance after fix invalidates resume (new coder fresh)",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "pre-advance",
        },
        {
          status: "coder_advance",
          event: "coder_advance",
          fromModelId: "grok-4.5",
          toModelId: "opus",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined,
    },
    {
      name: "coder_advance_stay_put does not invalidate",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "still-valid",
        },
        {
          status: "coder_advance_stay_put",
          event: "coder_advance_stay_put",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: "still-valid",
    },
    {
      // #979 R6-C1: converged court (cmr_passed) ends the findings chain —
      // do not walk past it to an older pre-pass cmr_fix_committed session.
      name: "cmr_passed ends chain — later open must not resume pre-pass session",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "pre-pass-session",
        },
        {
          status: "cmr_passed",
          event: "cmr_passed",
          cmrPass: "completeness",
        },
        // Later reopen (e.g. IC checkpoint re-entry / new findings chain) —
        // no newer fix row yet; resume must be fresh, not pre-pass-session.
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: undefined,
    },
    {
      name: "cmr_passed for other pass does not block this pass resume",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "comp-session",
        },
        {
          status: "cmr_passed",
          event: "cmr_passed",
          cmrPass: "correctness",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: "comp-session",
    },
    {
      name: "same-pass fix after cmr_passed is a new chain (resume that session)",
      ledger: [
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "old-chain",
        },
        {
          status: "cmr_passed",
          event: "cmr_passed",
          cmrPass: "completeness",
        },
        {
          status: "cmr_fix_committed",
          event: "cmr_fix_committed",
          cmrPass: "completeness",
          sessionId: "new-chain",
        },
      ] as FamilyLedgerEntry[],
      pass: "completeness",
      expected: "new-chain",
    },
  ])("$name", ({ ledger, pass, expected }) => {
    expect(familyCoderFixResumeSessionIdFromLedger(ledger, pass)).toBe(expected);
  });
});

describe("#979 production runFamilyCoderFixWorker Sandcastle resume", () => {
  it("passes Sandcastle resumeSession when ctx carries resumeSessionId + capable seat", async () => {
    // Default coderFix seat is codex (resume-capable); claudeToken-only auth
    // preflight is enough (same shape as #966 runCmrWorker production trap).
    const spec = familyCoderFixWorkerSpec(undefined, "resume");
    expect(resumeCapableForSlug(spec.model)).toBe(true);
    const repo = realRepo979();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];

    class Backend extends RealFamilyBackend {
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

      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runFamilyCoderFixWorker(workerSpec, ctx, {
          fixPacketBody: "live: k (979 resume explicit fixPacketBody)",
          blockingFindings: [FINDING_R1],
        });
      }
      protected override mountShipAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override agentForSpec(
        workerSpec: WorkerSpec,
        ctx?: Pick<DispatchContext, "billingPool">,
      ): sc.AgentProvider {
        const agent = super.agentForSpec(workerSpec, ctx);
        return {
          ...agent,
          sessionStorage: {
            ...agent.sessionStorage!,
            existsOnHost: async (_cwd: string, id: string) =>
              id === FIXER_SESSION,
          },
        };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return {
          branch: "fb",
          stdout: "",
          commits: [],
          iterations: [{ sessionId: FIXER_SESSION }],
          output: {
            station: "coderFix",
            status: "completed",
          },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }

    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("979-fix-resume-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(spec, {
      familyBase: "fb",
      resumeSessionId: FIXER_SESSION,
      blockingFindingIdentityKeys: ["k"],
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBe(FIXER_SESSION);
  });

  it("existsOnHost false → fresh Sandcastle open (drop dead session)", async () => {
    const spec = familyCoderFixWorkerSpec(undefined, "resume");
    const repo = realRepo979();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];

    class Backend extends RealFamilyBackend {
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

      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runFamilyCoderFixWorker(workerSpec, ctx, {
          fixPacketBody: "live: k (979 fresh-after-loss explicit fixPacketBody)",
          blockingFindings: [FINDING_R1],
        });
      }
      protected override mountShipAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override agentForSpec(
        workerSpec: WorkerSpec,
        ctx?: Pick<DispatchContext, "billingPool">,
      ): sc.AgentProvider {
        const agent = super.agentForSpec(workerSpec, ctx);
        return {
          ...agent,
          sessionStorage: {
            ...agent.sessionStorage!,
            existsOnHost: async () => false,
          },
        };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return {
          branch: "fb",
          stdout: "",
          commits: [],
          iterations: [{ sessionId: "fresh-after-loss-979" }],
          output: {
            station: "coderFix",
            status: "completed",
          },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }

    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("979-fix-loss-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(spec, {
      familyBase: "fb",
      resumeSessionId: "dead-session-979",
      blockingFindingIdentityKeys: ["k"],
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBeUndefined();
  });
});
