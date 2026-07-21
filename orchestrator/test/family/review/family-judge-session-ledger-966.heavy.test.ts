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
  it.each([
    {
      name: "empty rows → undefined",
      rows: [] as ReadonlyArray<{ sessionId?: string }>,
      expected: undefined,
    },
    {
      name: "blank / empty sessionId skipped",
      rows: [{ sessionId: "" }, {}],
      expected: undefined,
    },
    {
      name: "latest non-empty wins",
      rows: [
        { sessionId: "sess-old" },
        { sessionId: "sess-mid" },
        { sessionId: "sess-latest" },
      ],
      expected: "sess-latest",
    },
    {
      name: "newest missing sessionId means fresh (do not resurrect older)",
      rows: [
        { sessionId: "sess-kept" },
        { sessionId: "" },
        {},
      ],
      expected: undefined,
    },
    {
      name: "newest blank sessionId means fresh",
      rows: [{ sessionId: "sess-old" }, { sessionId: "" }],
      expected: undefined,
    },
  ])("familyJudgeResumeSessionIdFromPriorRows: $name", ({ rows, expected }) => {
    expect(familyJudgeResumeSessionIdFromPriorRows(rows)).toBe(expected);
  });

  it("production runCmrWorker passes Sandcastle resumeSession when ctx carries resumeSessionId", async () => {
    // MUST F1: verifyCmr → ctx.resumeSessionId is necessary but not sufficient —
    // RealFamilyBackend.runCmrWorker must thread resumeSession into sc.run options
    // (same field single-slice resumeSession uses). Mock FamilyBackend only proves
    // ctx shape; this traps the real production sandbox options object.
    // Default cmr seat is codex (resume-capable); claudeToken-only auth preflight
    // is enough for that provider (unlike grok, which needs grokAuthDir).
    // K2: host session must be present (existsOnHost true) or resume is dropped.
    const spec = cmrWorkerSpec("resume", "completeness");
    expect(resumeCapableForSlug(spec.model)).toBe(true);
    const repo = realRepo966();
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
        return this.runCmrWorker(workerSpec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
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
              id === ROUND1_SESSION,
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
          iterations: [{ sessionId: ROUND1_SESSION }],
          output: { station: "judge", status: "converged" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("966-cmr-resume-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(spec, {
      familyBase: "fb",
      cmrPass: "completeness",
      resumeSessionId: ROUND1_SESSION,
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBe(ROUND1_SESSION);
  });

  it("production runCmrWorker keeps fresh Sandcastle open when no resumeSessionId", async () => {
    const repo = realRepo966();
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
        return this.runCmrWorker(workerSpec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        return {
          branch: "fb",
          stdout: "",
          commits: [],
          iterations: [{ sessionId: "fresh-sess-966" }],
          output: { station: "judge", status: "converged" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("966-cmr-fresh-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(cmrWorkerSpec("fresh", "completeness"), {
      familyBase: "fb",
      cmrPass: "completeness",
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBeUndefined();
  });

  it("ledger resumeSessionId + existsOnHost false → fresh Sandcastle open with priors (K2)", async () => {
    // #966 AC4 / correctness K2: ledger may still hold a judge sessionId after
    // the host session file is gone. Forcing resumeSession causes Sandcastle
    // "session not found" loops — host must drop resume and keep priors.
    const STALE = "judge-sess-stale-missing-on-host-966";
    const repo = realRepo966();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];
    const existsCalls: Array<[string, string]> = [];
    class Backend extends RealFamilyBackend {
      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runCmrWorker(workerSpec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override agentForSpec(
        spec: WorkerSpec,
        ctx?: Pick<DispatchContext, "billingPool">,
      ): sc.AgentProvider {
        const agent = super.agentForSpec(spec, ctx);
        const baseStorage = agent.sessionStorage;
        return {
          ...agent,
          sessionStorage: {
            ...baseStorage!,
            existsOnHost: async (cwd: string, sessionId: string) => {
              existsCalls.push([cwd, sessionId]);
              return false;
            },
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
          iterations: [{ sessionId: "fresh-after-loss-966" }],
          output: { station: "judge", status: "converged" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("966-cmr-stale-session-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(cmrWorkerSpec("resume", "completeness"), {
      familyBase: "fb",
      cmrPass: "completeness",
      resumeSessionId: STALE,
      priorJudgeVerdicts: [
        {
          step: "cmr",
          status: "continue",
          sessionId: STALE,
        },
      ],
    });
    expect(existsCalls).toEqual([[repo, STALE]]);
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBeUndefined();
  });

  it("grok seat production runCmrWorker honors ledger resumeSession (true grok agent)", async () => {
    // #966 AC: "grok 席位真 resume" — not only fake backend recording + default
    // codex sandbox path. Dispatch model is grok-4.5 (resume-capable via #955),
    // production runCmrWorker → sandbox options carry resumeSession + grok agent.
    // K2: existsOnHost must affirm presence or resume is dropped for fresh open.
    const route = await grokCmrRoute();
    const spec = cmrWorkerSpec("resume", "completeness", route);
    expect(spec.model).toBe(GROK_SLUG);
    expect(resumeCapableForSlug(spec.model)).toBe(true);

    const repo = realRepo966();
    const runs: Array<Parameters<typeof sc.run>[0]> = [];
    class Backend extends RealFamilyBackend {
      public run(workerSpec: WorkerSpec, ctx: DispatchContext) {
        return this.runCmrWorker(workerSpec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        // Grok seat preflight requires grokAuthDir (providerAuth.grok).
        return {
          grokAuthDir: mkDir("966-grok-auth-"),
          claudeToken: "test-claude-panel-tok",
          providerAuth: { claude: true, grok: true, agy: false },
        };
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
              id === ROUND1_SESSION,
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
          iterations: [{ sessionId: ROUND1_SESSION }],
          output: { station: "judge", status: "converged" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }
    const be = new Backend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("966-grok-resume-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    await be.run(spec, {
      familyBase: "fb",
      cmrPass: "completeness",
      resumeSessionId: ROUND1_SESSION,
    });
    expect(runs).toHaveLength(1);
    expect(runs[0]!.resumeSession).toBe(ROUND1_SESSION);
    // Production agent binding is the real grok provider (not codex sandbox default).
    expect(runs[0]!.agent?.name).toBe("grok");
    expect(typeof runs[0]!.agent?.sessionStorage?.captureToHost).toBe("function");
    expect(typeof runs[0]!.agent?.sessionStorage?.resumeIntoSandbox).toBe(
      "function",
    );
  });
});
