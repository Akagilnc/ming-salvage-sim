import {
  execFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
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
  RunResult,
  docker,
  CMR_ROUTE_FILENAME,
  CMR_FOCUS_FILENAME,
  cmrOutcomeFromResult,
  parseCmrOutcome,
  RealFamilyBackend,
  SANDBOX_AGY_DIR,
  CmrAuth,
  CmrWorkerOutcome,
  ShipAuth,
  DECISION_GATE_TAG,
  decisionGateSignalSchema,
  isReceiptRecoveryFailure,
  RECEIPT_MAX_RETRIES,
  workerReceiptSchema,
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  runScriptedStructuredOutput,
  ScriptedAgent,
  SANDBOX_CODEX_DIR,
  SANDBOX_GH_TOKEN_ENV,
  SANDBOX_GROK_DIR,
  SANDBOX_REPO_ENV,
  SPAWNED_WORKER_ENV,
  cmrWorkerSpec,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
  shipOutcomeFromResult,
  isRunnerSynthesizedFailureEscalation,
  DispatchContext,
  WorkerLandingPayload,
  WorkerResult,
  WorkerSpec,
  buildExplicitLandingLiveHooks,
  realPromptsDir,
  realSoulsDir,
  DEFAULT_CMR_LEGS,
  FROZEN_NORMAL_CMR_REVIEW_LEGS,
  STRONG_LEGS,
  EMPTY_CMR_CLOSURE,
  CMR_EVIDENCE_PATHS,
  CMR_EVIDENCE,
  VALID_CMR_VERDICT_FIELDS,
  DERIVED_EMPTY_FINDINGS_COUNT,
  sandboxRunResult,
  typedSandboxRunResult,
  cleanups,
  mkDir,
  makeBackend,
  realRepo335,
  legacyClaudeCmrSpec,
} from "./cmr-worker.shared.js";
afterEach(() => {
  vi.unstubAllEnvs();
  while (cleanups.length > 0) {
    const p = cleanups.pop();
    if (p !== undefined) rmSync(p, { recursive: true, force: true });
  }
});

// ═══════════════════ 3. dispatchWorker(cmr) — routes the skill + wraps verdict ═══════════════════

describe("#335 RealFamilyBackend.dispatchWorker — the cmr worker", () => {
  /** A backend whose container `runCmrWorker` seam is fixtured (no real sc.run). */
  class FixturedCmrBackend extends RealFamilyBackend {
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

    runCmrCalls: { spec: ReturnType<typeof cmrWorkerSpec>; ctx: DispatchContext }[] = [];
    runCoderFixCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
    runShipCalls: { spec: WorkerSpec; ctx: DispatchContext }[] = [];
    // #919 M1/M2 / #930: default Fixtured happy path is live T2 judge green.
    // Residual kind:verdict without open-count is unusable (never silent clean).
    outcome: CmrWorkerOutcome = {
      kind: "judge",
      status: "converged",
      successfulLegs: STRONG_LEGS,
      ...CMR_EVIDENCE,
    };
    protected override async runCmrWorker(
      spec: ReturnType<typeof cmrWorkerSpec>,
      ctx: DispatchContext,
    ): Promise<CmrWorkerOutcome> {
      this.runCmrCalls.push({ spec, ctx });
      return this.outcome;
    }
    // #336: a ship spec routes to the ship worker seam (NOT the cmr seam). Fixture it
    // so this test asserts the routing without a real container / host claude token
    // (the pre-#336 version relied on a host-side `git push` throwing,
    // which is now both stale and host-fragile — cmr S336 r9).
    protected override async runShipWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<ReturnType<typeof shipOutcomeFromResult>> {
      this.runShipCalls.push({ spec, ctx });
      return { kind: "shipped", branch: ctx.familyBase!, status: "pr_opened", pr: "https://github.com/test/repo/pull/9" };
    }
    protected override async runFamilyCoderFixWorker(
      spec: WorkerSpec,
      ctx: DispatchContext,
    ): Promise<WorkerResult> {
      this.runCoderFixCalls.push({ spec, ctx });
      return {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      };
    }
  }

  function fixtured(): FixturedCmrBackend {
    return new FixturedCmrBackend({
      workingRepo: mkDir("cmr-repo-"),
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "ming-orchestrator-coder:latest",
    });
  }

  it("lets Sandcastle validate the CMR receipt with its native retry budget", async () => {
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    const runs: Parameters<typeof sc.run>[0][] = [];
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

      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) { return this.runCmrWorker(spec, ctx); }
      protected override mountCmrAuth(): CmrAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(options: Parameters<typeof sc.run>[0]): Promise<Awaited<ReturnType<typeof sc.run>>> {
        runs.push(options);
        const verdict = {
          converged: true,
          findingsCount: 0,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...VALID_CMR_VERDICT_FIELDS,
        };
        return typedSandboxRunResult(verdict, {
          stdout: `<cmr>${JSON.stringify(verdict)}</cmr>`,
        });
      }
    }
    const be = new Backend({ workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("cmr-receipt-ledger-"), repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir, soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123" });
    await be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" });
    expect(runs[0]).toMatchObject({
      output: expect.objectContaining({ tag: "judge", maxRetries: 2 }),
    });
  });

  it("accepts initial-good open-count via real sc.run (no same-session resume)", async () => {
    // #899 four-case matrix: first emission already valid → one agent call.
    const good = {
      findingsCount: 0,
      findings: [],
      converged: true,
      successfulLegs: [...DEFAULT_CMR_LEGS],
      ...VALID_CMR_VERDICT_FIELDS,
    };
    const { agent, result } = await runScriptedStructuredOutput({
      tag: "judge",
      schema: workerReceiptSchema(),
      emissions: [{ body: JSON.stringify(good) }],
      maxRetries: RECEIPT_MAX_RETRIES,
      sessionId: "sess-cmr-initial-good",
      cleanups,
    });
    expect(result.output).toMatchObject({ findingsCount: 0 });
    expect(agent.callCount).toBe(1);
    expect(agent.resumedSessions).toEqual([undefined]);
  });

  it("accepts initial-good decision-gate via real sc.run (no same-session resume)", async () => {
    const good = {
      escalate: { reason: "owner choice", diagnosis: "contract fork" },
    };
    const { agent, result } = await runScriptedStructuredOutput({
      tag: DECISION_GATE_TAG,
      schema: decisionGateSignalSchema,
      emissions: [{ body: JSON.stringify(good) }],
      maxRetries: RECEIPT_MAX_RETRIES,
      sessionId: "sess-decision-initial-good",
      cleanups,
    });
    expect(result.output).toEqual(good);
    expect(agent.callCount).toBe(1);
    expect(agent.resumedSessions).toEqual([undefined]);
  });

  it("classifies Sandcastle's real non-resumable maxRetries error as recovery failure", async () => {
    // #899: real sc.run rejects maxRetries>0 on providers without sessionStorage.
    await expect(
      runScriptedStructuredOutput({
        tag: "judge",
        schema: workerReceiptSchema(),
        emissions: [{ body: JSON.stringify({ findingsCount: 0 }) }],
        maxRetries: RECEIPT_MAX_RETRIES,
        resumable: false,
        name: "grok",
        cleanups,
      }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(Error);
      expect((err as Error).message).toMatch(
        /output\.maxRetries requires an agent provider that supports session resumption/i,
      );
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
    // String-shape contract remains stable for #598 classification.
    expect(isReceiptRecoveryFailure(new Error(
      'output.maxRetries requires an agent provider that supports session resumption. The "grok" provider does not. Use claudeCode, codex, or pi, or set maxRetries to 0.',
    ))).toBe(true);
  });

  it("classifies non-resumable maxRetries as recovery failure for decision-gate too", async () => {
    // #899 four-case matrix: both typed signals share non-resumable fail-closed.
    await expect(
      runScriptedStructuredOutput({
        tag: DECISION_GATE_TAG,
        schema: decisionGateSignalSchema,
        emissions: [{ body: JSON.stringify({ escalate: { reason: "r", diagnosis: "d" } }) }],
        maxRetries: RECEIPT_MAX_RETRIES,
        resumable: false,
        name: "grok",
        cleanups,
      }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(Error);
      expect((err as Error).message).toMatch(
        /output\.maxRetries requires an agent provider that supports session resumption/i,
      );
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
  });

  it("propagates StructuredOutputError when native CMR receipt retries are exhausted", async () => {
    // #899: real sc.run exhaust (initial + maxRetries) throws StructuredOutputError;
    // the production seam surfaces that single throw → #598 (no fixer).
    const agentOut: { agent?: ScriptedAgent } = {};
    try {
      await runScriptedStructuredOutput({
        tag: "judge",
        schema: workerReceiptSchema(),
        emissions: [
          { body: JSON.stringify({ findingsCount: -1 }) },
          { body: JSON.stringify({ findingsCount: -2 }) },
          { body: JSON.stringify({ findingsCount: -3 }) },
        ],
        maxRetries: RECEIPT_MAX_RETRIES,
        sessionId: "sess-cmr-exhausted",
        cleanups,
        agentOut,
      });
      expect.unreachable("expected StructuredOutputError after maxRetries exhaust");
    } catch (err) {
      expect(err).toBeInstanceOf(sc.StructuredOutputError);
      const soe = err as sc.StructuredOutputError;
      expect(soe.tag).toBe("judge");
      expect(soe.sessionId).toBe("sess-cmr-exhausted");
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      // initial attempt + RECEIPT_MAX_RETRIES same-session resumes
      expect(agentOut.agent?.callCount).toBe(RECEIPT_MAX_RETRIES + 1);
      expect(agentOut.agent?.resumedSessions).toEqual([
        undefined,
        "sess-cmr-exhausted",
        "sess-cmr-exhausted",
      ]);
    }

    // Production boundary: after Sandcastle exhausts, the Action sees one throw.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let sandcastleCalls = 0;
    const exhausted = new sc.StructuredOutputError("bad output", {
      tag: "judge",
      rawMatched: JSON.stringify({
        converged: false,
        reason: "review finding survives malformed receipt",
        findingsCount: 1,
        successfulLegs: [...DEFAULT_CMR_LEGS],
        ...VALID_CMR_VERDICT_FIELDS,
        findings: [{
          severity: "high",
          category: "correctness",
          claim_quote: "reviewer cargo survives",
          location: "orchestrator/src/family/realFamilyBackend.ts:1606",
          suggested_fix: "preserve the landing cargo",
          action: "fix_now",
        }],
      }),
      commits: [], branch: "fb", sessionId: "sess-cmr-exhausted",
    });
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

      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) { return this.runCmrWorker(spec, ctx); }
      protected override mountCmrAuth(): CmrAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        expect(options.output).toEqual(expect.objectContaining({
          tag: "judge",
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        throw exhausted;
      }
    }
    const be = new Backend({ workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("cmr-receipt-exhausted-ledger-"), repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir, soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123" });

    await expect(be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" })).rejects.toBe(exhausted);
    expect(sandcastleCalls).toBe(1);
  });

  it("recovers open-count via real Sandcastle same-session maxRetries (bad→good)", async () => {
    // #899 Testing Decisions: inject recovery sequence at the real sc.run
    // boundary — first emission fails production schema; same session re-asks
    // and the second emission succeeds. Intermediate receipts never re-enter
    // the runner (one sc.run invocation from production's POV).
    const good = {
      findingsCount: 0,
      findings: [],
      converged: true,
      successfulLegs: [...DEFAULT_CMR_LEGS],
      ...VALID_CMR_VERDICT_FIELDS,
    };
    const { agent, result } = await runScriptedStructuredOutput({
      tag: "judge",
      schema: workerReceiptSchema(),
      emissions: [
        { body: JSON.stringify({ findingsCount: undefined }) },
        { body: JSON.stringify(good) },
      ],
      maxRetries: RECEIPT_MAX_RETRIES,
      sessionId: "same-cmr-reviewer-session",
      cleanups,
    });
    expect(result.output).toMatchObject({ findingsCount: 0 });
    // initial attempt + one same-session resume
    expect(agent.callCount).toBe(2);
    expect(agent.resumedSessions).toEqual([undefined, "same-cmr-reviewer-session"]);
  });

  it("recovers decision-gate via real Sandcastle same-session maxRetries (bad→good)", async () => {
    // #899: both typed traffic signals share Output.object maxRetries.
    const good = {
      escalate: { reason: "owner choice", diagnosis: "contract fork" },
    };
    const { agent, result } = await runScriptedStructuredOutput({
      tag: DECISION_GATE_TAG,
      schema: decisionGateSignalSchema,
      emissions: [
        { body: JSON.stringify({ escalate: { reason: "", diagnosis: "" } }) },
        { body: JSON.stringify(good) },
      ],
      maxRetries: RECEIPT_MAX_RETRIES,
      sessionId: "same-decision-session",
      cleanups,
    });
    expect(result.output).toEqual(good);
    expect(agent.callCount).toBe(2);
    expect(agent.resumedSessions).toEqual([undefined, "same-decision-session"]);
  });

  it("treats misspelled escalate key on open-count as opaque cargo (no re-ask)", async () => {
    // #899: only the exact `escalate` key is a gate. Near-miss spellings ride
    // as opaque cargo — no approximate key inference that could false-positive
    // legitimate cargo keys into a misspelled-gate failure.
    const payload = {
      findingsCount: 1,
      findings: [],
      escalte: { reason: "typo", diagnosis: "opaque cargo" },
      converged: true,
      successfulLegs: [...DEFAULT_CMR_LEGS],
      ...VALID_CMR_VERDICT_FIELDS,
    };
    const { agent, result } = await runScriptedStructuredOutput({
      tag: "judge",
      schema: workerReceiptSchema(),
      emissions: [{ body: JSON.stringify(payload) }],
      maxRetries: RECEIPT_MAX_RETRIES,
      sessionId: "same-cmr-combined-misspell-session",
      cleanups,
    });
    expect(result.output).toMatchObject({ findingsCount: 1 });
    expect(
      (result.output as { escalate?: unknown }).escalate,
    ).toBeUndefined();
    expect(agent.callCount).toBe(1);
    expect(agent.resumedSessions).toEqual([undefined]);
  });

  it("exhausts decision-gate maxRetries via real sc.run without inventing a gate", async () => {
    const agentOut: { agent?: ScriptedAgent } = {};
    try {
      await runScriptedStructuredOutput({
        tag: DECISION_GATE_TAG,
        schema: decisionGateSignalSchema,
        emissions: [
          { body: JSON.stringify({ escalate: { reason: "", diagnosis: "x" } }) },
          { body: JSON.stringify({ escalate: { reason: "r" } }) },
          { body: JSON.stringify({ escalte: { reason: "typo", diagnosis: "key" } }) },
        ],
        maxRetries: RECEIPT_MAX_RETRIES,
        sessionId: "sess-decision-exhausted",
        cleanups,
        agentOut,
      });
      expect.unreachable("expected StructuredOutputError after decision-gate exhaust");
    } catch (err) {
      expect(err).toBeInstanceOf(sc.StructuredOutputError);
      expect((err as sc.StructuredOutputError).tag).toBe(DECISION_GATE_TAG);
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      expect(agentOut.agent?.callCount).toBe(RECEIPT_MAX_RETRIES + 1);
    }
  });

  it("recovers open-count via production CMR worker + real sc.run (bad→good)", async () => {
    // #899: four-case matrix must cross the production worker boundary AND real
    // sc.run native maxRetries — not only a post-recovery fixture.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let sandcastleCalls = 0;
    const agentOut: { agent?: ScriptedAgent } = {};
    const good = {
      findingsCount: 0,
      findings: [],
      converged: true,
      successfulLegs: [...DEFAULT_CMR_LEGS],
      ...VALID_CMR_VERDICT_FIELDS,
    };
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

      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
        return this.runCmrWorker(spec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        // Production seat must bind open-count SO + maxRetries.
        expect(options.output).toEqual(expect.objectContaining({
          tag: "judge",
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        const run = await runScriptedStructuredOutput({
          tag: "judge",
          schema: workerReceiptSchema(),
          emissions: [
            { body: JSON.stringify({ findingsCount: -1 }) },
            { body: JSON.stringify(good) },
          ],
          maxRetries: RECEIPT_MAX_RETRIES,
          sessionId: "prod-cmr-recover-session",
          cleanups,
          agentOut,
        });
        return run.result;
      }
    }
    const be = new Backend({
      workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("cmr-prod-recover-ledger-"),
      repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir,
      soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123",
    });

    await expect(
      be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" }),
    ).resolves.toMatchObject({
      kind: "verdict",
      findingsCount: 0,
    });
    // One production sc.run invocation; native same-session resume is inside it.
    expect(sandcastleCalls).toBe(1);
    expect(agentOut.agent?.callCount).toBe(2);
    expect(agentOut.agent?.resumedSessions).toEqual([
      undefined,
      "prod-cmr-recover-session",
    ]);
  });

  it("fails open-count non-resumable provider via production CMR worker + real sc.run", async () => {
    // #899 four-case: unrecoverable provider must surface through production seat.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let sandcastleCalls = 0;
    let coderFixCalls = 0;
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

      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
        return this.runCmrWorker(spec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        expect(options.output).toEqual(expect.objectContaining({
          tag: "judge",
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        return (
          await runScriptedStructuredOutput({
            tag: "judge",
            schema: workerReceiptSchema(),
            emissions: [{ body: JSON.stringify({ findingsCount: 0 }) }],
            maxRetries: RECEIPT_MAX_RETRIES,
            resumable: false,
            name: "grok",
            cleanups,
          })
        ).result;
      }
      protected override async runFamilyCoderFixWorker(): Promise<WorkerResult> {
        coderFixCalls += 1;
        throw new Error("coder-fix must not run on non-resumable SO failure");
      }
    }
    const be = new Backend({
      workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("cmr-prod-nonresumable-ledger-"),
      repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir,
      soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123",
    });
    await expect(
      be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(Error);
      expect((err as Error).message).toMatch(
        /output\.maxRetries requires an agent provider that supports session resumption/i,
      );
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
    expect(sandcastleCalls).toBe(1);
    expect(coderFixCalls).toBe(0);
  });

  it("accepts initial-good open-count at the family CMR production seam", async () => {
    // #899 four-case matrix (production): first-good typed open-count through
    // production worker + real sc.run (not a post-hoc fixture).
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let sandcastleCalls = 0;
    let coderFixCalls = 0;
    const agentOut: { agent?: ScriptedAgent } = {};
    const good = {
      findingsCount: 0,
      findings: [],
      converged: true,
      successfulLegs: [...DEFAULT_CMR_LEGS],
      ...VALID_CMR_VERDICT_FIELDS,
    };
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

      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
        return this.runCmrWorker(spec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        expect(options.output).toEqual(expect.objectContaining({
          tag: "judge",
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        const run = await runScriptedStructuredOutput({
          tag: "judge",
          schema: workerReceiptSchema(),
          emissions: [{ body: JSON.stringify(good) }],
          maxRetries: RECEIPT_MAX_RETRIES,
          sessionId: "prod-cmr-initial-good-session",
          cleanups,
          agentOut,
        });
        return run.result;
      }
      protected override async runFamilyCoderFixWorker(): Promise<WorkerResult> {
        coderFixCalls += 1;
        throw new Error("coder-fix must not run on initial-good open-count");
      }
    }
    const be = new Backend({
      workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("cmr-initial-good-ledger-"),
      repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir,
      soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123",
    });
    await expect(be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" })).resolves.toMatchObject({
      kind: "verdict",
      findingsCount: 0,
    });
    expect(sandcastleCalls).toBe(1);
    expect(agentOut.agent?.callCount).toBe(1);
    expect(coderFixCalls).toBe(0);
  });

  it("#598 same-position redispatch on open-count SOE exhaust; zero fixer/next-gate", async () => {
    // #899: production seat + real sc.run exhaust (initial + maxRetries) →
    // Action throw → #598 mechanical redispatch at the same fixed position;
    // never feed empty cargo to fixer / next gate.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let sandcastleCalls = 0;
    let coderFixCalls = 0;
    let lastExhaustError: unknown;
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

      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
        return this.runCmrWorker(spec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        expect(options.output).toEqual(expect.objectContaining({
          tag: "judge",
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        try {
          await runScriptedStructuredOutput({
            tag: "judge",
            schema: workerReceiptSchema(),
            emissions: [
              { body: JSON.stringify({ findingsCount: -1 }) },
              { body: JSON.stringify({ findingsCount: -2 }) },
              { body: JSON.stringify({ findingsCount: -3 }) },
            ],
            maxRetries: RECEIPT_MAX_RETRIES,
            sessionId: `sess-cmr-soe-598-${sandcastleCalls}`,
            cleanups,
          });
          throw new Error("expected StructuredOutputError after open-count exhaust");
        } catch (err) {
          lastExhaustError = err;
          throw err;
        }
      }
      protected override async runFamilyCoderFixWorker(): Promise<WorkerResult> {
        coderFixCalls += 1;
        throw new Error("coder-fix must not run after open-count SOE");
      }
    }
    const be = new Backend({
      workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("cmr-soe-598-ledger-"),
      repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir,
      soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123",
    });
    const spec = cmrWorkerSpec();
    await expect(
      withMechanicalRetry(
        spec,
        { familyBase: "fb", cmrPass: "completeness" },
        async (s, c) => {
          // Mirror dispatchOrAbort: rethrow Action failure for #598.
          await be.run(s as ReturnType<typeof cmrWorkerSpec>, c);
          throw new Error("expected SOE throw");
        },
        { rethrowOnExhaustion: true, sleepMs: async () => {} },
      ),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(sc.StructuredOutputError);
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
    expect(sandcastleCalls).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(coderFixCalls).toBe(0);
    expect(lastExhaustError).toBeInstanceOf(sc.StructuredOutputError);
  }, 120_000);

  it("#598 same-position redispatch on T2 coder SOE exhaust; zero next-gate", async () => {
    // #899 / #919 M1: T2 coder station receipt SO on the family coder-fix seat
    // exhausts via real sc.run → Action throw → #598 mechanical redispatch at the
    // same fixed position. No human-loop park; no next-gate.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let sandcastleCalls = 0;
    let nextGateCalls = 0;
    let lastExhaustError: unknown;
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

      /** Expose the production coder-fix seat that binds T2 coder receipt SO. */
      public runFix(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        return this.runFamilyCoderFixWorker(spec, ctx);
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok" };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        expect(options.output).toEqual(expect.objectContaining({
          tag: CODER_RECEIPT_TAG,
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        try {
          await runScriptedStructuredOutput({
            tag: CODER_RECEIPT_TAG,
            schema: coderStationReceiptSchema(),
            emissions: [
              {
                body: JSON.stringify({
                  station: "familyCoderFix",
                  status: "escalate",
                  reason: "",
                  diagnosis: "",
                }),
              },
              {
                body: JSON.stringify({
                  station: "familyCoderFix",
                  status: "escalate",
                  reason: "",
                  diagnosis: "x",
                }),
              },
              {
                body: JSON.stringify({
                  station: "familyCoderFix",
                  status: "escalate",
                  reason: "r",
                  diagnosis: "",
                }),
              },
            ],
            maxRetries: RECEIPT_MAX_RETRIES,
            sessionId: `sess-coder-soe-598-${sandcastleCalls}`,
            cleanups,
          });
          throw new Error("expected StructuredOutputError after T2 coder SO exhaust");
        } catch (err) {
          lastExhaustError = err;
          throw err;
        }
      }
      protected override async runCmrWorker(): Promise<CmrWorkerOutcome> {
        nextGateCalls += 1;
        throw new Error("next CMR gate must not run after coder T2 SOE");
      }
      protected override async runShipWorker(): Promise<ReturnType<typeof shipOutcomeFromResult>> {
        nextGateCalls += 1;
        throw new Error("ship gate must not run after coder T2 SOE");
      }
    }
    const be = new Backend({
      workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("decision-soe-598-ledger-"),
      repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir,
      soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123",
    });
    const fixSpec = familyCoderFixWorkerSpec();
    await expect(
      withMechanicalRetry(
        fixSpec,
        { familyBase: "fb", cmrPass: "completeness" },
        async (s, c) => be.runFix(s, c),
        { rethrowOnExhaustion: true, sleepMs: async () => {} },
      ),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(sc.StructuredOutputError);
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
    expect(sandcastleCalls).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(nextGateCalls).toBe(0);
    expect(lastExhaustError).toBeInstanceOf(sc.StructuredOutputError);
  }, 120_000);

  it("accepts initial-good T2 coder receipt at the family coder-fix production seam", async () => {
    // #899 / #919 M1: first-good T2 coder station receipt through production
    // seat + real sc.run — one agent emission, no repair.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let sandcastleCalls = 0;
    let nextGateCalls = 0;
    const agentOut: { agent?: ScriptedAgent } = {};
    const good = {
      station: "familyCoderFix",
      status: "escalate",
      reason: "owner choice",
      diagnosis: "contract fork",
    };
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

      public runFix(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        return this.runFamilyCoderFixWorker(spec, ctx);
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok" };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        expect(options.output).toEqual(expect.objectContaining({
          tag: CODER_RECEIPT_TAG,
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        const run = await runScriptedStructuredOutput({
          tag: CODER_RECEIPT_TAG,
          schema: coderStationReceiptSchema(),
          emissions: [{ body: JSON.stringify(good) }],
          maxRetries: RECEIPT_MAX_RETRIES,
          sessionId: "prod-coder-initial-good-session",
          cleanups,
          agentOut,
        });
        return run.result;
      }
      protected override async runCmrWorker(): Promise<CmrWorkerOutcome> {
        nextGateCalls += 1;
        throw new Error("next CMR gate must not run on initial-good T2 coder receipt");
      }
    }
    const be = new Backend({
      workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("coder-initial-good-ledger-"),
      repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir,
      soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123",
    });
    await expect(
      be.runFix(familyCoderFixWorkerSpec(), { familyBase: "fb" }),
    ).resolves.toMatchObject({
      kind: "completed",
      output: {
        escalate: { reason: "owner choice", diagnosis: "contract fork" },
      },
    });
    expect(sandcastleCalls).toBe(1);
    expect(agentOut.agent?.callCount).toBe(1);
    expect(nextGateCalls).toBe(0);
  });

  it("recovers T2 coder receipt via production coder-fix + real sc.run (bad→good)", async () => {
    // #899 / #919 M1: T2 coder receipt re-ask through production seat + real sc.run.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let sandcastleCalls = 0;
    const agentOut: { agent?: ScriptedAgent } = {};
    const good = {
      station: "familyCoderFix",
      status: "escalate",
      reason: "owner choice",
      diagnosis: "contract fork",
    };
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

      public runFix(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        return this.runFamilyCoderFixWorker(spec, ctx);
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok" };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        expect(options.output).toEqual(expect.objectContaining({
          tag: CODER_RECEIPT_TAG,
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        const run = await runScriptedStructuredOutput({
          tag: CODER_RECEIPT_TAG,
          schema: coderStationReceiptSchema(),
          emissions: [
            {
              body: JSON.stringify({
                station: "familyCoderFix",
                status: "escalate",
                reason: "",
                diagnosis: "",
              }),
            },
            { body: JSON.stringify(good) },
          ],
          maxRetries: RECEIPT_MAX_RETRIES,
          sessionId: "prod-coder-recover-session",
          cleanups,
          agentOut,
        });
        return run.result;
      }
    }
    const be = new Backend({
      workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("coder-prod-recover-ledger-"),
      repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir,
      soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123",
    });
    await expect(
      be.runFix(familyCoderFixWorkerSpec(), { familyBase: "fb" }),
    ).resolves.toMatchObject({
      kind: "completed",
      output: {
        escalate: { reason: "owner choice", diagnosis: "contract fork" },
      },
    });
    expect(sandcastleCalls).toBe(1);
    expect(agentOut.agent?.callCount).toBe(2);
    expect(agentOut.agent?.resumedSessions).toEqual([
      undefined,
      "prod-coder-recover-session",
    ]);
  });

  it("fails T2 coder receipt non-resumable provider via production coder-fix + real sc.run", async () => {
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-q", "-b", "fb"], { cwd: repo });
    let sandcastleCalls = 0;
    let nextGateCalls = 0;
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

      public runFix(spec: WorkerSpec, ctx: DispatchContext): Promise<WorkerResult> {
        return this.runFamilyCoderFixWorker(spec, ctx);
      }
      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok" };
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        sandcastleCalls += 1;
        expect(options.output).toEqual(expect.objectContaining({
          tag: CODER_RECEIPT_TAG,
          maxRetries: RECEIPT_MAX_RETRIES,
        }));
        return (
          await runScriptedStructuredOutput({
            tag: CODER_RECEIPT_TAG,
            schema: coderStationReceiptSchema(),
            emissions: [{
              body: JSON.stringify({
                station: "familyCoderFix",
                status: "escalate",
                reason: "r",
                diagnosis: "d",
              }),
            }],
            maxRetries: RECEIPT_MAX_RETRIES,
            resumable: false,
            name: "grok",
            cleanups,
          })
        ).result;
      }
      protected override async runCmrWorker(): Promise<CmrWorkerOutcome> {
        nextGateCalls += 1;
        throw new Error("next CMR gate must not run on non-resumable SO failure");
      }
    }
    const be = new Backend({
      workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("coder-prod-nonresumable-ledger-"),
      repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir,
      soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123",
    });
    await expect(
      be.runFix(familyCoderFixWorkerSpec(), { familyBase: "fb" }),
    ).rejects.toSatisfy((err: unknown) => {
      expect(err).toBeInstanceOf(Error);
      expect((err as Error).message).toMatch(
        /output\.maxRetries requires an agent provider that supports session resumption/i,
      );
      expect(isReceiptRecoveryFailure(err)).toBe(true);
      return true;
    });
    expect(sandcastleCalls).toBe(1);
    expect(nextGateCalls).toBe(0);
  });

  it("cleans up family coder-fix findings if outcome landing fails", async () => {
    const repo = realRepo335();

    class FailingOutcomeLandingBackend extends RealFamilyBackend {
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

      protected override mountShipAuth(): ShipAuth {
        return { claudeToken: "tok" };
      }

      protected override prepareFamilyCoderOutcomeLanding(): {
        path: string;
        sandboxPath: string;
      } {
        throw new Error("outcome landing failed");
      }

      protected override sh(file: string, args: string[], cwd?: string): string {
        if (file === "git" && args[0] === "checkout") return "";
        if (file === "git" && args[0] === "rev-parse" && args[1] === "HEAD") {
          return "family-head-before-coder-fix";
        }
        return super.sh(file, args, cwd);
      }
    }

    const be = new FailingOutcomeLandingBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("family-coder-landing-fail-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    await expect(
      be.dispatchWorker(
        familyCoderFixWorkerSpec(),
        {
          familyBase: "fb",
          blockingFindingIdentityKeys: ["cmr-key-1"],
        },
        { fixPacketBody: "live: cmr-key-1 (ADR 0138 explicit body)" },
      ),
    ).rejects.toThrow("outcome landing failed");
    expect(existsSync(join(repo, ".orchestrator-fix-findings.json"))).toBe(false);
  });

  it.each([
    [
      "malformed reviewer",
      "cmr-reviewer-malformed",
      "sidecar" as const,
    ],
    [
      "reviewer-declared positive count with empty findings",
      "cmr-reviewer-empty-findings",
      "stdout" as const,
    ],
  ] as const)(
    "transports raw reviewer artifacts into family coder-fix findings for %s",
    (_label, reviewerSessionId, hostKind) => {
      const repo = realRepo335();
      // Host-only paths must be materialised into the sandbox cwd so the fixer
      // container can read them (#899) — write real host files then assert
      // sandbox-relative names land in the findings JSON.
      const hostDir = mkDir("raw-reviewer-host-");
      const hostStdout = join(hostDir, "reviewer.stdout");
      const hostSidecar = join(hostDir, "reviewer.sidecar");
      writeFileSync(hostStdout, "reviewer stdout body\n", "utf8");
      writeFileSync(hostSidecar, JSON.stringify({ findingsCount: 1 }), "utf8");
      const rawReviewerArtifacts =
        hostKind === "sidecar"
          ? {
              reviewerSessionId,
              sidecarPath: hostSidecar,
              statement: "the previous reviewer raw artifacts are here" as const,
            }
          : {
              reviewerSessionId,
              stdoutPath: hostStdout,
              statement: "the previous reviewer raw artifacts are here" as const,
            };

      class FixFindingsBackend extends RealFamilyBackend {
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

        public writeFixFindings(
          ctx: DispatchContext,
          landing: WorkerLandingPayload,
        ): { path: string; sandboxPath: string } {
          return this.writeFamilyFixFindingsFile(ctx, landing);
        }
      }

      const be = new FixFindingsBackend({
        workingRepo: repo,
        familyBase: "fb",
        ledgerDir: mkDir("family-coder-raw-artifacts-ledger-"),
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
      });

      const landing = be.writeFixFindings(
        { familyBase: "fb", blockingFindingIdentityKeys: [] },
        { blockingFindings: [], rawReviewerArtifacts },
      );

      const written = JSON.parse(readFileSync(landing.path, "utf8")) as {
        rawReviewerArtifacts: {
          reviewerSessionId?: string;
          stdoutPath?: string;
          sidecarPath?: string;
          statement: string;
        };
      };
      expect(written.rawReviewerArtifacts.reviewerSessionId).toBe(reviewerSessionId);
      expect(written.rawReviewerArtifacts.statement).toBe(
        "the previous reviewer raw artifacts are here",
      );
      if (hostKind === "sidecar") {
        expect(written.rawReviewerArtifacts.sidecarPath).toBe(
          ".orchestrator-raw-reviewer.sidecar",
        );
        expect(readFileSync(join(repo, ".orchestrator-raw-reviewer.sidecar"), "utf8")).toBe(
          JSON.stringify({ findingsCount: 1 }),
        );
        // Host absolute path must not leak into the findings file.
        expect(JSON.stringify(written)).not.toContain(hostSidecar);
      } else {
        expect(written.rawReviewerArtifacts.stdoutPath).toBe(
          ".orchestrator-raw-reviewer.stdout",
        );
        expect(readFileSync(join(repo, ".orchestrator-raw-reviewer.stdout"), "utf8")).toBe(
          "reviewer stdout body\n",
        );
        expect(JSON.stringify(written)).not.toContain(hostStdout);
      }
    },
  );

});

describe("#850 review r5 — production CMR dispatch applies OpenCode auth", () => {
  class AuthDispatchBackend extends RealFamilyBackend {
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

    config?: {
      env: Record<string, string>;
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    };
    runOptions?: Parameters<typeof sc.run>[0];
    outcomePath?: string;

    constructor(private readonly auth: CmrAuth, workingRepo: string) {
      super({
        workingRepo,
        familyBase: "fb",
        ledgerDir: mkDir("cmr-auth-ledger-"),
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
        familyBaseStartHead: "abc123",
      });
    }

    protected override mountCmrAuth(): CmrAuth {
      return this.auth;
    }

    protected override cmrSandbox(
      auth: CmrAuth,
      spec: Pick<WorkerSpec, "model" | "soul" | "host">,
      outcomeLanding?: { path: string; sandboxPath: string },
      ctx?: Pick<DispatchContext, "billingPool">,
    ): sc.SandboxProvider {
      this.config = this.cmrSandboxConfig(auth, spec, outcomeLanding, ctx);
      return docker(this.config);
    }

    protected override prepareCmrOutcomeLanding(
      ctx: DispatchContext,
    ): { path: string; sandboxPath: string } {
      const landing = super.prepareCmrOutcomeLanding(ctx);
      this.outcomePath = landing.path;
      return landing;
    }

    protected override async runAgentSandbox(
      options: Parameters<typeof sc.run>[0],
    ): Promise<Awaited<ReturnType<typeof sc.run>>> {
      this.runOptions = options;
      if (this.outcomePath === undefined) throw new Error("missing outcome path");
      writeFileSync(this.outcomePath, JSON.stringify({
        converged: true,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...CMR_EVIDENCE,
      }));
      return typedSandboxRunResult({
        converged: true,
        findingsCount: 0,
        successfulLegs: DEFAULT_CMR_LEGS,
        ...VALID_CMR_VERDICT_FIELDS,
      });
    }
  }

  async function dispatch(
    pool: DispatchContext["billingPool"],
    spec: WorkerSpec = cmrWorkerSpec(),
    auth: CmrAuth = { claudeToken: "test-claude-panel-tok" },
  ) {
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    const backend = new AuthDispatchBackend(auth, repo);
    await backend.dispatchWorker(spec, { familyBase: "fb", billingPool: pool });
    return { backend };
  }

  it("#905: production CMR dispatch does not inject GLM_KEY or mount opencode auth", async () => {
    vi.stubEnv("GLM_KEY", "glm-secret");
    const { backend } = await dispatch("zai");
    expect(backend.config?.env.GLM_KEY).toBeUndefined();
    expect(
      backend.config?.mounts.some((m) => m.sandboxPath.includes("opencode")),
    ).toBe(false);
  });

  it("#905: non-zai production dispatch also has no opencode transport", async () => {
    vi.stubEnv("GLM_KEY", "glm-secret");
    const { backend } = await dispatch(undefined);
    expect(backend.config?.env.GLM_KEY).toBeUndefined();
    expect(
      backend.config?.mounts.some((m) => m.sandboxPath.includes("opencode")),
    ).toBe(false);
  });

  it("#905: codex-pool production CMR dispatch has no opencode mount", async () => {
    vi.stubEnv("GLM_KEY", "glm-secret");
    const { backend } = await dispatch("codex-5h");
    expect(backend.config?.env.GLM_KEY).toBeUndefined();
    expect(
      backend.config?.mounts.some((m) => m.sandboxPath.includes("opencode")),
    ).toBe(false);
  });

  it("threads one real CMR spec into both the Agy command and its soul overlay", async () => {
    const spec: WorkerSpec = {
      ...cmrWorkerSpec(),
      model: "agy",
      host: "agy",
      soul: "verify",
    };
    const { backend } = await dispatch(
      undefined,
      spec,
      { agyDir: mkDir("agy-auth-r2-") },
    );
    const command = backend.runOptions?.agent.buildPrintCommand({
      prompt: "TASK_SENTINEL",
      dangerouslySkipPermissions: false,
    });
    expect(command?.command).toContain("agy");
    expect(command?.command).toContain("TASK_SENTINEL");
    expect(backend.config?.mounts).toContainEqual({
      hostPath: join(realSoulsDir, "verify.md"),
      sandboxPath: "/home/agent/.gemini/GEMINI.md",
      readonly: true,
    });
  });
});

// ═══════════════════ 4c. writeCmrFocusFile — exact scope + focus (codex cmr R1 F2/F3) ═══════════════════

describe("#335 writeCmrFocusFile — threads the exact diff scope + machine-resolved focus", () => {
  /** Expose the focus-file seam over a REAL temp git repo (so the exclude path resolves). */
  class FocusBackend extends RealFamilyBackend {
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

    public focus(ctx: {
      familyBase: string;
      llmResolvedChildren?: readonly number[];
      escalationAnswer?: DispatchContext["escalationAnswer"];
    }): void {
      this.writeCmrFocusFile(ctx as never);
    }
    public verifyFocus(ctx: DispatchContext): void {
      this.writeWaveVerifyFocusFile(ctx);
    }
    public routeFile(pass: "completeness" | "correctness" | undefined): void {
      const spec = cmrWorkerSpec("fresh", pass ?? "correctness");
      this.writeCmrRouteFile(pass, spec.cmrReviewLegs!);
    }
    public routeFileFromNull(): void {
      const spec = cmrWorkerSpec("fresh", "correctness");
      this.writeCmrRouteFile(null as never, spec.cmrReviewLegs!);
    }
    public routeFileFromSpec(
      pass: "completeness" | "correctness",
      spec: ReturnType<typeof cmrWorkerSpec>,
    ): void {
      this.writeCmrRouteFile(pass, spec.cmrReviewLegs!);
    }
    public onlineLanding(
      ctx: DispatchContext,
      landing: NonNullable<Parameters<FocusBackend["writeFamilyOnlineReviewLandingFile"]>[1]>,
    ): string {
      return this.writeFamilyOnlineReviewLandingFile(ctx, landing).path;
    }
  }

  function realRepo(): string {
    const repo = mkDir("cmr-focus-repo-");
    execFileSync("git", ["init", "-q"], { cwd: repo });
    return repo;
  }

  it("pins the cut-SHA scope command + names the machine-resolved children", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    be.focus({ familyBase: "feat/330-pure-scheduler", llmResolvedChildren: [42, 43] });
    const body = readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8");
    // F3: the exact scope diff is on the recorded cut SHA, NOT main...HEAD.
    expect(body).toContain("git diff abc123...feat/330-pure-scheduler");
    // F2: the machine-resolved children are named.
    expect(body).toContain("#42");
    expect(body).toContain("#43");
    // It is git-ignored (info/exclude), so the review never accidentally commits it.
    const exclude = readFileSync(join(repo, ".git", "info", "exclude"), "utf8");
    expect(exclude.split("\n")).toContain(CMR_FOCUS_FILENAME);
  });

  it.each([
    ["wave", "after the current wave's child slices merged"],
    ["correctness_checkpoint", "at the correctness checkpoint"],
    ["final", "at the final family verification barrier"],
  ] as const)("writes the real %s verify accident scope into judge focus", (phase, scope) => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
    });

    be.verifyFocus({
      familyBase: "feat/330-pure-scheduler",
      phase,
      waveVerifyFailure: `${phase} red`,
    });

    const body = readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8");
    expect(body).toContain(scope);
    expect(body).toContain(`${phase} red`);
    if (phase !== "wave") {
      expect(body).not.toContain("after merging the child slices");
    }
  });

  it("serializes an answered gate into the real online-review landing", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const path = be.onlineLanding(
      {
        familyBase: "feat/330-pure-scheduler",
        escalationAnswer: {
          event: "escalation_answered",
          answer: "defer this finding",
          source: "human",
        },
      },
      {
        onlineReviewSnapshot: { kind: "offline", findings: [] } as never,
      },
    );
    const payload = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
    expect(payload.escalationAnswer).toEqual({
      event: "escalation_answered",
      answer: "defer this finding",
      source: "human",
    });
  });

  it("writes the route file pass from dispatch context, not the prompt filename", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    be.routeFile("correctness");
    const body = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as {
      pass: string;
    };
    expect(body.pass).toBe("correctness");
  });

  it("no recorded cut SHA ⇒ FAIL-CLOSED throw, never a stale-base fallback scope (codex R3)", () => {
    // The focus file pins the EXACT cut-SHA review-scope diff (prompt contract:
    // do NOT guess main...HEAD). Emitting a
    // `main...familyBase` fallback when no cut SHA was recorded would silently
    // disable that load-bearing scope — the same fail-open the reconcile
    // `familyBaseStartHead()` predicate refuses (realFamilyBackend.ts:887-895). So
    // a missing cut SHA must THROW (the gate converts it to not-passed / escalate),
    // never write a stale-base diff command.
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      // no familyBaseStartHead
    });
    expect(() => be.focus({ familyBase: "fb" })).toThrow(/familyBaseStartHead|cut SHA/i);
    // And it did NOT write a stale-base fallback file.
    expect(() => readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8")).toThrow();
  });

  it("keeps prior finding state out of the transient focus file", () => {
    // The focus file is pass-scoped runtime input. It pins ONLY the review scope +
    // the machine-resolved-child focus; pass/closure accounting travels via the
    // worker verdict and durable ledger, never a "prior round's findings" prompt
    // block in this file.
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    be.focus({ familyBase: "feat/330-pure-scheduler", llmResolvedChildren: [42] });
    const body = readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8");
    // The full review-scope diff + the machine-resolved focus are present...
    expect(body).toContain("git diff abc123...feat/330-pure-scheduler");
    expect(body).toContain("#42");
    // ...but NO prior-findings block (the worker remembers within its own session).
    expect(body).not.toMatch(/Prior round's findings/i);
    expect(body).not.toMatch(/confirm-resolved/i);
  });

  it("writes the route-selected CMR review legs beside the focus file", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    be.routeFile("correctness");

    const route = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as unknown;
    expect(route).toEqual({
      pass: "correctness",
      reviewLegs: [
        { family: "codex", slug: "gpt-5.6-sol" },
        { family: "claude", slug: "opus" },
        { family: "agy", slug: "agy", optional: true },
      ],
    });
    const exclude = readFileSync(join(repo, ".git", "info", "exclude"), "utf8");
    expect(exclude.split("\n")).toContain(CMR_ROUTE_FILENAME);
  });

  it("freezes CMR review legs from the worker spec, not later route env", () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const spec = cmrWorkerSpec("fresh", "correctness");
    vi.stubEnv("ORCHESTRATOR_ROUTE", "claude-tight");
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    be.routeFileFromSpec("correctness", spec);

    const route = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as {
      reviewLegs: unknown;
    };
    expect(route.reviewLegs).toEqual([
      { family: "codex", slug: "gpt-5.6-sol" },
      { family: "claude", slug: "opus" },
      { family: "agy", slug: "agy", optional: true },
    ]);
  });

  it("treats null CMR route context as a legacy route-file write instead of crashing", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    expect(() => be.routeFileFromNull()).not.toThrow();
    const route = JSON.parse(readFileSync(join(repo, CMR_ROUTE_FILENAME), "utf8")) as {
      pass: string;
      reviewLegs: unknown;
    };
    expect(route.pass).toBe("legacy");
    expect(route.reviewLegs).toEqual(cmrWorkerSpec("fresh", "correctness").cmrReviewLegs);
  });

  it("threads a human escalation answer into the CMR focus file", () => {
    const repo = realRepo();
    const be = new FocusBackend({
      workingRepo: repo,
      familyBase: "feat/330-pure-scheduler",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    be.focus({
      familyBase: "feat/330-pure-scheduler",
      escalationAnswer: {
        event: "escalation_answered",
        answer: "continue-same-class",
        note: "Human says continue the same-class CMR fix loop.",
      },
    });

    const body = readFileSync(join(repo, CMR_FOCUS_FILENAME), "utf8");
    expect(body).toContain("Human escalation answer");
    expect(body).toContain("continue-same-class");
    expect(body).toContain("Human says continue the same-class CMR fix loop.");
  });
});

// ═══════════════════ 4d. runCmrWorker fail-closed on a missing cut SHA (codex R3) ═══════════════════

describe("#335 runCmrWorker — fail-closed when no cut SHA was recorded", () => {
  /** Exposes runCmrWorker and traps sc.run so we can prove it is NEVER reached. */
  class GuardBackend extends RealFamilyBackend {
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

    scRunReached = false;
    public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
      return this.runCmrWorker(spec, ctx);
    }
    protected override writeCmrFocusFile(): void {
      // If the guard is correct this is never reached; flag it if it is.
      this.scRunReached = true;
      throw new Error("writeCmrFocusFile should not run when fail-closed");
    }
  }

  it("a cmr worker with NO familyBaseStartHead ⇒ escalate, never spins the container", async () => {
    const repo = realRepo335();
    const be = new GuardBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      // no familyBaseStartHead
    });
    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb" });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/familyBaseStartHead|cut SHA/i);
    }
    // The fail-closed guard returns BEFORE any container / focus-file work.
    expect(be.scRunReached).toBe(false);
  });

  it("dispatchWorker routes that fail-closed escalate to a not-passed WorkerResult", async () => {
    const repo = realRepo335();
    const be = new GuardBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      // no familyBaseStartHead
    });
    const res = await be.dispatchWorker(cmrWorkerSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(res.escalation.reason).toMatch(/familyBaseStartHead|cut SHA/i);
      expect(isRunnerSynthesizedFailureEscalation(res.escalation)).toBe(true);
    }
  });
});

// ═══════ 4e. runCmrWorker fail-closed on a missing Claude WORKER auth (codex R4) ═══════

describe("#335 runCmrWorker — fail-closed when the top-level Claude worker has no auth", () => {
  /**
   * The CMR worker is the container's TOP-LEVEL claude (`agent: sc.claudeCode`), so
   * the Claude OAuth token is not a mere reviewer leg — it is the worker's OWN auth.
   * A missing token means the worker cannot start and never emits a `<cmr>` verdict;
   * letting it through would crash out of `sc.run` (NOT a structured escalate),
   * bypassing verifyCmr's escalate routing. So `runCmrWorker` must escalate BEFORE
   * spinning the container when `mountCmrAuth().claudeToken` is absent.
   */
  class NoClaudeAuthBackend extends RealFamilyBackend {
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

    scRunReached = false;
    public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
      return this.runCmrWorker(spec, ctx);
    }
    // The cut SHA IS recorded (we isolate the Claude-auth guard from the R3 guard).
    protected override mountCmrAuth(): CmrAuth {
      // codex/agy present, claude token ABSENT (the worker's own auth missing).
      return { codexAuthDir: "/x/codex", agyDir: "/x/agy" };
    }
    protected override writeCmrFocusFile(): void {
      this.scRunReached = true;
      throw new Error("writeCmrFocusFile should not run when the worker has no auth");
    }
  }

  it("no Claude worker token ⇒ escalate, never spins the container", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    const be = new NoClaudeAuthBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const outcome = await be.run(legacyClaudeCmrSpec(), { familyBase: "fb" });
    expect(outcome.kind).toBe("escalate");
    if (outcome.kind === "escalate") {
      expect(outcome.reason).toMatch(/claude|token|auth/i);
    }
    expect(be.scRunReached).toBe(false);
  });

  it("dispatchWorker routes the no-auth escalate to a not-passed WorkerResult", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    const be = new NoClaudeAuthBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });
    const res = await be.dispatchWorker(legacyClaudeCmrSpec(), { familyBase: "fb" });
    expect(res.kind).toBe("escalated");
    if (res.kind === "escalated") {
      expect(isRunnerSynthesizedFailureEscalation(res.escalation)).toBe(true);
    }
  });
});

// ═══════ 4f. runCmrWorker reclaims its per-run temp auth dirs (online review r1) ═══════

describe("#335 runCmrWorker — reclaims the per-run temp auth dirs (no leak)", () => {
  /**
   * `mountCmrAuth` creates per-run codex/agy temp dirs that are only needed for the
   * lifetime of the mounted container run. They must be reclaimed on EVERY exit —
   * including the early claude-token escalate (which never reaches sc.run). 3 bots
   * flagged the leak; the try/finally in runCmrWorker is the fix.
   */
  class ReclaimBackend extends RealFamilyBackend {
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

    constructor(opts: ConstructorParameters<typeof RealFamilyBackend>[0], private readonly dirs: CmrAuth) {
      super(opts);
    }
    public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
      return this.runCmrWorker(spec, ctx);
    }
    // Real on-disk dirs but NO claude token ⇒ the early escalate fires; the finally
    // must still reclaim the two dirs.
    protected override mountCmrAuth(): CmrAuth {
      return this.dirs;
    }
  }

  it("the early no-claude-auth escalate removes codex, agy, and grok temp dirs", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const codexDir = mkDir("reclaim-codex-");
    const agyDir = mkDir("reclaim-agy-");
    const grokDir = mkDir("reclaim-grok-");
    expect(existsSync(codexDir)).toBe(true);
    expect(existsSync(agyDir)).toBe(true);
    expect(existsSync(grokDir)).toBe(true);

    const be = new ReclaimBackend(
      {
        workingRepo: realRepo335(),
        familyBase: "fb",
        ledgerDir: mkDir("cmr-ledger-"),
        repo: "Akagilnc/ming-salvage-sim",
        base: "main",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        imageName: "img",
        familyBaseStartHead: "abc123",
      },
      { codexAuthDir: codexDir, agyDir, grokAuthDir: grokDir }, // no claudeToken ⇒ early escalate
    );

    const outcome = await be.run(legacyClaudeCmrSpec(), { familyBase: "fb" });
    expect(outcome.kind).toBe("escalate");
    // The finally reclaimed BOTH per-run dirs even though sc.run never ran.
    expect(existsSync(codexDir)).toBe(false);
    expect(existsSync(agyDir)).toBe(false);
    expect(existsSync(grokDir)).toBe(false);
  });

  it("uses Sandcastle's typed CMR receipt when the sidecar cargo is malformed, then removes it", async () => {
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    let outcomePathAtRun: string | undefined;
    class OutcomeCleanupBackend extends RealFamilyBackend {
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

      public calls = 0;
      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
        return this.runCmrWorker(spec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override prepareCmrOutcomeLanding(
        ctx: DispatchContext,
      ): { path: string; sandboxPath: string } {
        const landing = super.prepareCmrOutcomeLanding(ctx);
        outcomePathAtRun = landing.path;
        return landing;
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        this.calls += 1;
        expect(options.output).toEqual(expect.objectContaining({ tag: "judge", maxRetries: 2 }));
        if (outcomePathAtRun === undefined) throw new Error("missing outcome sidecar path");
        writeFileSync(
          outcomePathAtRun,
          JSON.stringify({ converged: "not-a-verdict" }),
          "utf8",
        );
        return typedSandboxRunResult({
          converged: true,
          findingsCount: 0,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...VALID_CMR_VERDICT_FIELDS,
        }, {
          stdout: "compatibility tag intentionally absent",
        });
      }
    }
    const be = new OutcomeCleanupBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-outcome-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" });

    expect(outcome).toMatchObject({
      kind: "verdict",
      findingsCount: 0,
      successfulLegs: DEFAULT_CMR_LEGS,
    });
    expect(be.calls).toBe(1);
    expect(outcomePathAtRun).toBeDefined();
    expect(existsSync(dirname(outcomePathAtRun as string))).toBe(false);
  });

  it("attaches T2 coder station receipt SO for family coder; cargo stays opaque", async () => {
    // #899 / #919 M1: T2 coderStationReceiptSchema is attached; malformed
    // committed cargo siblings stay opaque and do not invent refuse traffic.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    let outcomePathAtRun: string | undefined;

    class FamilyCoderReceiptBackend extends RealFamilyBackend {
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

      public calls: Parameters<typeof sc.run>[0][] = [];
      public run(spec: ReturnType<typeof familyCoderFixWorkerSpec>, ctx: DispatchContext) {
        return this.runFamilyCoderFixWorker(spec, ctx);
      }
      protected override mountShipAuth(): ShipAuth { return { claudeToken: "tok" }; }
      protected override prepareFamilyCoderOutcomeLanding(): { path: string; sandboxPath: string } {
        const landing = super.prepareFamilyCoderOutcomeLanding();
        outcomePathAtRun = landing.path;
        return landing;
      }
      protected override async runAgentSandbox(
        options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        this.calls.push(options);
        if (outcomePathAtRun === undefined) throw new Error("missing outcome sidecar path");
        writeFileSync(outcomePathAtRun, JSON.stringify({ committed: "not-a-boolean" }), "utf8");
        return {
          branch: "fb",
          stdout: "family coder finished with opaque sidecar cargo",
          commits: [],
          iterations: [{ sessionId: "family-coder-malformed" }],
          // Valid T2 completed traffic; committed cargo remains opaque/tolerant.
          output: { station: "familyCoderFix", status: "completed" },
        } as Awaited<ReturnType<typeof sc.run>>;
      }
    }

    const be = new FamilyCoderReceiptBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("family-coder-receipt-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    await expect(be.run(familyCoderFixWorkerSpec(), { familyBase: "fb" })).resolves.toMatchObject({
      kind: "completed",
      output: { kind: "coder", committed: false, commitsAdded: 0 },
    });
    expect(be.calls).toHaveLength(1);
    expect(be.calls[0]!.output).toMatchObject({
      tag: CODER_RECEIPT_TAG,
      maxRetries: 2,
    });
    expect(be.calls[0]!.resumeSession).toBeUndefined();
  });

  it("keeps a single family coder invocation when sidecar cargo is absent", async () => {
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    class NoSessionBackend extends RealFamilyBackend {
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

      public calls = 0;
      public run(spec: ReturnType<typeof familyCoderFixWorkerSpec>, ctx: DispatchContext) {
        return this.runFamilyCoderFixWorker(spec, ctx);
      }
      protected override mountShipAuth(): ShipAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(): Promise<Awaited<ReturnType<typeof sc.run>>> {
        this.calls += 1;
        // Legal T2 completed traffic; cargo sidecar may still be empty.
        return typedSandboxRunResult({
          station: "familyCoderFix",
          status: "completed",
        });
      }
    }
    const be = new NoSessionBackend({ workingRepo: repo, familyBase: "fb", ledgerDir: mkDir("family-coder-no-session-ledger-"), repo: "Akagilnc/ming-salvage-sim", base: "main", promptsDir: realPromptsDir, soulsDir: realSoulsDir, imageName: "img", familyBaseStartHead: "abc123" });

    await expect(be.run(familyCoderFixWorkerSpec(), { familyBase: "fb" })).resolves.toMatchObject({
      kind: "completed", output: { kind: "coder", committed: false, commitsAdded: 0 },
    });
    expect(be.calls).toBe(1);
  });

  it("fails family coder-fix when typed decision Output.object is absent", async () => {
    // #899: SO seat without result.output must not become cargo/no-gate success.
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    class MissingTypedBackend extends RealFamilyBackend {
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

      public run(spec: ReturnType<typeof familyCoderFixWorkerSpec>, ctx: DispatchContext) {
        return this.runFamilyCoderFixWorker(spec, ctx);
      }
      protected override mountShipAuth(): ShipAuth { return { claudeToken: "tok" }; }
      protected override async runAgentSandbox(): Promise<Awaited<ReturnType<typeof sc.run>>> {
        return sandboxRunResult();
      }
    }
    const be = new MissingTypedBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("family-coder-missing-typed-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    await expect(be.run(familyCoderFixWorkerSpec(), { familyBase: "fb" })).rejects.toThrow(
      /typed traffic signal missing/,
    );
  });

  it("fails family CMR when typed open-count Output.object is absent", async () => {
    // #899: cargo/sidecar must not substitute for a missing typed receipt.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    let outcomePathAtRun: string | undefined;

    class MissingTypedCmrBackend extends RealFamilyBackend {
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

      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
        return this.runCmrWorker(spec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override prepareCmrOutcomeLanding(
        ctx: DispatchContext,
      ): { path: string; sandboxPath: string } {
        const landing = super.prepareCmrOutcomeLanding(ctx);
        outcomePathAtRun = landing.path;
        return landing;
      }
      protected override async runAgentSandbox(
        _options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomePathAtRun === undefined) throw new Error("missing outcome sidecar path");
        writeFileSync(
          outcomePathAtRun,
          JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
            ...VALID_CMR_VERDICT_FIELDS,
          }),
          "utf8",
        );
        // Sidecar cargo present but typed SO missing → fail for #598.
        return sandboxRunResult({
          stdout: `<cmr>${JSON.stringify({
            converged: true,
            successfulLegs: DEFAULT_CMR_LEGS,
            ...VALID_CMR_VERDICT_FIELDS,
          })}</cmr>`,
        });
      }
    }

    const be = new MissingTypedCmrBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-missing-typed-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    await expect(
      be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" }),
    ).rejects.toThrow(/typed traffic signal missing/);
  });

  it("a prepared but blank CMR outcome sidecar still uses the typed receipt", async () => {
    // #899: blank sidecar is cargo-only; fate comes from typed Output.object.
    vi.stubEnv("ORCHESTRATOR_ROUTE", "normal");
    const repo = realRepo335();
    execFileSync("git", ["config", "user.email", "t@t.t"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
    execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: repo });
    execFileSync("git", ["checkout", "-b", "fb"], { cwd: repo });
    let outcomePathAtRun: string | undefined;

    class BlankSidecarBackend extends RealFamilyBackend {
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

      public run(spec: ReturnType<typeof cmrWorkerSpec>, ctx: DispatchContext) {
        return this.runCmrWorker(spec, ctx);
      }
      protected override mountCmrAuth(): CmrAuth {
        return { claudeToken: "tok" };
      }
      protected override prepareCmrOutcomeLanding(
        ctx: DispatchContext,
      ): { path: string; sandboxPath: string } {
        const landing = super.prepareCmrOutcomeLanding(ctx);
        outcomePathAtRun = landing.path;
        return landing;
      }
      protected override async runAgentSandbox(
        _options: Parameters<typeof sc.run>[0],
      ): Promise<Awaited<ReturnType<typeof sc.run>>> {
        if (outcomePathAtRun === undefined) throw new Error("missing outcome sidecar path");
        expect(readFileSync(outcomePathAtRun, "utf8")).toBe("");
        const verdict = {
          converged: true,
          findingsCount: 0,
          successfulLegs: DEFAULT_CMR_LEGS,
          ...VALID_CMR_VERDICT_FIELDS,
        };
        return typedSandboxRunResult(verdict, {
          stdout: `<cmr>${JSON.stringify(verdict)}</cmr>\nfindings = 0\nCMR_STEP_COMPLETE`,
        });
      }
    }

    const be = new BlankSidecarBackend({
      workingRepo: repo,
      familyBase: "fb",
      ledgerDir: mkDir("cmr-blank-sidecar-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      imageName: "img",
      familyBaseStartHead: "abc123",
    });

    const outcome = await be.run(cmrWorkerSpec(), { familyBase: "fb", cmrPass: "completeness" });

    expect(outcome).toMatchObject({
      kind: "verdict",
      converged: true,
      findingsCount: 0,
      successfulLegs: DEFAULT_CMR_LEGS,
    });
  });
});
