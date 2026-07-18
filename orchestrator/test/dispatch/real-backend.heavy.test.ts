import {
  dirname,
  join,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  readFileSync,
  writeFileSync,
  homedir,
  tmpdir,
  fileURLToPath,
  afterAll,
  afterEach,
  describe,
  expect,
  it,
  vi,
  agentForSlug,
  attributeFailure,
  branchForIssue,
  candidateBranches,
  buildAuthPaths,
  buildIssueMeta,
  checkExecutableInstructionSource,
  classifyResumeError,
  cutRefFor,
  extractCoderTag,
  isReadyForAgent,
  issueNumberFromBranch,
  lastSessionId,
  matchWorktreeForBranch,
  modelIdForSlug,
  modelFamilyForSlug,
  modelIsStrongLeg,
  parseBlockedBy,
  parseSubIssueCount,
  promptsDirError,
  soulsDirError,
  REQUIRED_SOUL_FILES,
  resolveModelSlug,
  soulForStep,
  REFERENCED_PROMPT_FILES,
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_GROK_DIR,
  SANDBOX_SKILLS_DIR,
  SUPPORTED_MODEL_PROVIDER_FACTORIES,
  WORKER_IDLE_TIMEOUT_SECONDS,
  GhBlockedBy,
  GhIssueJson,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  sc,
  resolveRouteModels,
  telemetry,
  scRuntime,
  StructuredOutputError,
  DECISION_GATE_TAG,
  RECEIPT_MAX_RETRIES,
  decisionGateSignalSchema,
  isReceiptRecoveryFailure,
  workerReceiptSchema,
  CODER_RECEIPT_TAG,
  coderStationReceiptSchema,
  judgeStationReceiptSchema,
  JUDGE_RECEIPT_TAG,
  runScriptedStructuredOutput,
  ScriptedAgent,
  CODER_COMPLETED_ENVELOPE,
  CODER_NO_COMMIT_ENVELOPE,
  CODER_ESCALATE_ENVELOPE,
  AgentRunResult,
  agentRunResult,
  tempHomes,
  tempHome,
  cleanupTempHomes,
} from "./real-backend.shared.js";

afterEach(cleanupTempHomes);
afterEach(() => vi.restoreAllMocks());
afterAll(cleanupTempHomes);

describe("RealBackend runStep toolchain preflight (#286)", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const realPromptsDir = join(here, "..", "..", "prompts");
  const realSoulsDir = join(here, "..", "..", "image", "souls");

  const coderSpec: StepSpec = {
    id: "S2",
    role: "coder",
    promptFile: "coder_implement.md",
    model: "gpt-5.6-sol",
    // Production seats are single-iter with decision-gate SO (#899). Keep
    // fixtures aligned so maxIter>1 cannot hide the Output.object attach path.
    maxIter: 1,
    soul: "coder",
    toolchain: ["python", "node", "npm", "typescript"],
  };
  const reviewerSpec: StepSpec = {
    id: "S3",
    // #919 S2: judge seat identity is verify.
    role: "verify",
    promptFile: "judge_station.md",
    model: "gpt-5.6-sol",
    maxIter: 1,
    soul: "verify",
    toolchain: ["node", "typescript"],
  };

  class PreflightBackend extends RealBackend {
    public agentRunReached = false;
    public agentResult?: Awaited<ReturnType<typeof sc.run>>;
    public agentResults: Array<Awaited<ReturnType<typeof sc.run>>> = [];
    public agentFailures: unknown[] = [];
    public lastAgentOptions?: Parameters<typeof sc.run>[0];
    public agentOptions: Array<Parameters<typeof sc.run>[0]> = [];
    public preflightResults = new Map<string, boolean>();
    public preflightHook?: (tool: string) => Promise<void>;
    /** Final reachable commits after the fresh worker's pinned baseline. */
    public finalGraphCommitCount = 0;

    protected override cloneDirExists(): boolean {
      return true;
    }

    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      if (file === "git" && args[0] === "rev-parse" && args[1] === "HEAD") {
        return "a".repeat(40);
      }
      if (file === "git" && args[0] === "rev-list" && args[1] === "--count") {
        return String(this.finalGraphCommitCount);
      }
      return "";
    }

    protected override async preflightToolchainTool(tool: string): Promise<void> {
      if (this.preflightHook !== undefined) return this.preflightHook(tool);
      if (this.preflightResults.get(tool) === false) {
        throw new Error(`${tool}: command not found`);
      }
    }

    protected override async runAgentSandbox(
      options: Parameters<typeof sc.run>[0],
    ): Promise<Awaited<ReturnType<typeof sc.run>>> {
      this.lastAgentOptions = options;
      this.agentOptions.push(options);
      this.agentRunReached = true;
      const queued = this.agentResults.shift();
      if (queued !== undefined) return queued;
      const failure = this.agentFailures.shift();
      if (failure !== undefined) throw failure;
      if (this.agentResult !== undefined) return this.agentResult;
      throw new Error("agent sandbox should not run during this test");
    }

    /** Typed probe for receipt decode (no `as unknown as`). */
    public probeDecodeOutput(spec: StepSpec, raw: unknown, cargo?: unknown): StepOutput {
      return this.decodeOutput(spec, raw, cargo);
    }
    /** Typed probe for typed vs cargo channel selection. */
    public probeRawOutputFor(
      result: { output?: unknown; stdout: string },
      spec: StepSpec,
      typedOutputUsed: boolean,
      options?: { outcomeLanding?: { path: string; sandboxPath: string } },
    ): unknown {
      return this.rawOutputFor(result, spec, typedOutputUsed, options);
    }
  }

  function makeBackend(home = tempHome("rb-home-286-")): PreflightBackend {
    return new PreflightBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 286,
      repo: "owner/name",
      imageName: "ming-worker:bad",
      promptsDir: realPromptsDir,
      soulsDir: realSoulsDir,
      // #748: runStep → box → mountAuth must not touch real ~/.sc-orchestrator.
      home,
    });
  }

  // ─── #899 T1: single-slice production SO four-case matrix ─────────────────
  // Family production seat coverage lives in cmr-worker.test.ts. This block
  // exercises RealBackend single-slice reviewer open-count + coder decision-gate
  // at the real sc.run boundary (scripted provider, no LLM).

  // #962: per-run GIT_CONFIG_GLOBAL isolation removes the old sequential need.
  describe("#899 single-slice production SO four-case matrix", () => {
    const cleanups: string[] = [];
    afterEach(() => {
      while (cleanups.length > 0) {
        const dir = cleanups.pop();
        if (dir !== undefined) rmSync(dir, { recursive: true, force: true });
      }
    });

    it("accepts initial-good judge verdict via real sc.run (no same-session resume)", async () => {
      const good = { station: "judge", status: "converged" };
      const { agent, result } = await runScriptedStructuredOutput({
        tag: JUDGE_RECEIPT_TAG,
        schema: judgeStationReceiptSchema(),
        emissions: [{ body: JSON.stringify(good) }],
        maxRetries: RECEIPT_MAX_RETRIES,
        sessionId: "sess-ss-review-initial-good",
        cleanups,
      });
      expect(result.output).toMatchObject(good);
      expect(agent.callCount).toBe(1);
      expect(agent.resumedSessions).toEqual([undefined]);

      // Production decode path: typed judge → kind:judge.
      const backend = makeBackend();
      expect(
        backend.probeDecodeOutput(reviewerSpec, result.output),
      ).toEqual({ kind: "judge", status: "converged" });
    });

    it("accepts initial-good coder station receipt via real sc.run (no same-session resume)", async () => {
      const good = CODER_ESCALATE_ENVELOPE;
      const { agent, result } = await runScriptedStructuredOutput({
        tag: CODER_RECEIPT_TAG,
        schema: coderStationReceiptSchema(),
        emissions: [{ body: JSON.stringify(good) }],
        maxRetries: RECEIPT_MAX_RETRIES,
        sessionId: "sess-ss-coder-initial-good",
        cleanups,
      });
      expect(result.output).toMatchObject({
        station: "coder",
        status: "escalate",
        reason: "owner choice",
        diagnosis: "contract fork",
      });
      expect(agent.callCount).toBe(1);

      const backend = makeBackend();
      expect(
        backend.probeDecodeOutput(coderSpec, result.output),
      ).toMatchObject({
        escalate: { reason: "owner choice", diagnosis: "contract fork" },
      });
    });

    it("recovers judge verdict bad→good same-session via real sc.run", async () => {
      const agentOut: { agent?: ScriptedAgent } = {};
      const good = {
        station: "judge",
        status: "continue",
        findingDispositions: [
          { identityKey: "correctness|a.ts:1|x", action: "live" },
          { identityKey: "correctness|b.ts:2|y", action: "live" },
        ],
        fixPacketBody: "live: correctness|a.ts:1|x\nlive: correctness|b.ts:2|y",
      };
      const { agent, result } = await runScriptedStructuredOutput({
        tag: JUDGE_RECEIPT_TAG,
        schema: judgeStationReceiptSchema(),
        emissions: [
          { body: JSON.stringify({ findingsCount: -1 }) },
          { body: JSON.stringify(good) },
        ],
        maxRetries: RECEIPT_MAX_RETRIES,
        sessionId: "sess-ss-review-recover",
        cleanups,
        agentOut,
      });
      expect(result.output).toMatchObject({ station: "judge", status: "continue" });
      expect(agent.callCount).toBe(2);
      expect(agent.resumedSessions).toEqual([
        undefined,
        "sess-ss-review-recover",
      ]);
      expect(agentOut.agent?.callCount).toBe(2);

      const backend = makeBackend();
      expect(
        backend.probeDecodeOutput(reviewerSpec, result.output),
      ).toMatchObject({ kind: "judge", status: "continue" });
    });

    it("recovers coder station-receipt bad→good same-session via real sc.run", async () => {
      const good = {
        station: "coder",
        status: "escalate",
        reason: "owner",
        diagnosis: "needs human",
      };
      const { agent, result } = await runScriptedStructuredOutput({
        tag: CODER_RECEIPT_TAG,
        schema: coderStationReceiptSchema(),
        emissions: [
          { body: JSON.stringify({ committed: true }) },
          { body: JSON.stringify(good) },
        ],
        maxRetries: RECEIPT_MAX_RETRIES,
        sessionId: "sess-ss-coder-recover",
        cleanups,
      });
      expect(result.output).toMatchObject(good);
      expect(agent.callCount).toBe(2);
      expect(agent.resumedSessions).toEqual([
        undefined,
        "sess-ss-coder-recover",
      ]);
    });

    it("propagates StructuredOutputError when judge maxRetries are exhausted", async () => {
      const agentOut: { agent?: ScriptedAgent } = {};
      try {
        await runScriptedStructuredOutput({
          tag: JUDGE_RECEIPT_TAG,
          schema: judgeStationReceiptSchema(),
          emissions: [
            { body: JSON.stringify({ findingsCount: -1 }) },
            { body: JSON.stringify({ status: "maybe" }) },
            { body: JSON.stringify({ station: "judge" }) },
          ],
          maxRetries: RECEIPT_MAX_RETRIES,
          sessionId: "sess-ss-review-exhausted",
          cleanups,
          agentOut,
        });
        expect.unreachable("expected StructuredOutputError after maxRetries exhaust");
      } catch (err) {
        expect(err).toBeInstanceOf(scRuntime.StructuredOutputError);
        const soe = err as scRuntime.StructuredOutputError;
        expect(soe.tag).toBe(JUDGE_RECEIPT_TAG);
        expect(isReceiptRecoveryFailure(err)).toBe(true);
        expect(agentOut.agent?.callCount).toBe(RECEIPT_MAX_RETRIES + 1);
      }
    });

    it("propagates StructuredOutputError when coder station-receipt maxRetries are exhausted", async () => {
      const agentOut: { agent?: ScriptedAgent } = {};
      try {
        await runScriptedStructuredOutput({
          tag: CODER_RECEIPT_TAG,
          schema: coderStationReceiptSchema(),
          emissions: [
            { body: JSON.stringify({ status: "maybe" }) },
            { body: JSON.stringify({ station: "coder" }) },
            { body: JSON.stringify({ station: "coder", status: "refused" }) },
          ],
          maxRetries: RECEIPT_MAX_RETRIES,
          sessionId: "sess-ss-coder-exhausted",
          cleanups,
          agentOut,
        });
        expect.unreachable("expected StructuredOutputError after maxRetries exhaust");
      } catch (err) {
        expect(err).toBeInstanceOf(scRuntime.StructuredOutputError);
        expect((err as scRuntime.StructuredOutputError).tag).toBe(CODER_RECEIPT_TAG);
        expect(isReceiptRecoveryFailure(err)).toBe(true);
        expect(agentOut.agent?.callCount).toBe(RECEIPT_MAX_RETRIES + 1);
      }
    });

    it("classifies non-resumable open-count maxRetries as recovery failure", async () => {
      await expect(
        runScriptedStructuredOutput({
          tag: JUDGE_RECEIPT_TAG,
          schema: judgeStationReceiptSchema(),
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
    });

    it("classifies non-resumable coder station-receipt maxRetries as recovery failure", async () => {
      await expect(
        runScriptedStructuredOutput({
          tag: CODER_RECEIPT_TAG,
          schema: coderStationReceiptSchema(),
          emissions: [{ body: JSON.stringify(CODER_COMPLETED_ENVELOPE) }],
          maxRetries: RECEIPT_MAX_RETRIES,
          resumable: false,
          name: "grok",
          cleanups,
        }),
      ).rejects.toSatisfy((err: unknown) => {
        expect(isReceiptRecoveryFailure(err)).toBe(true);
        return true;
      });
    });

    it("production RealBackend reviewer seat: first-good open-count via real sc.run", async () => {
      // #899 T1: cross production RealBackend.runStep boundary + real sc.run.
      const agentOut: { agent?: ScriptedAgent } = {};
      let sandcastleCalls = 0;
      class ProductionSeatBackend extends PreflightBackend {
        protected override async runAgentSandbox(
          options: Parameters<typeof scRuntime.run>[0],
        ): Promise<Awaited<ReturnType<typeof scRuntime.run>>> {
          sandcastleCalls += 1;
          this.lastAgentOptions = options;
          this.agentOptions.push(options);
          expect(options.output).toEqual(
            expect.objectContaining({ tag: "judge", maxRetries: RECEIPT_MAX_RETRIES }),
          );
          const run = await runScriptedStructuredOutput({
            tag: JUDGE_RECEIPT_TAG,
            schema: judgeStationReceiptSchema(),
            emissions: [
              { body: JSON.stringify({ station: "judge", status: "converged" }) },
            ],
            maxRetries: RECEIPT_MAX_RETRIES,
            sessionId: "prod-ss-review-initial-good",
            cleanups,
            agentOut,
          });
          return run.result;
        }
      }
      const backend = new ProductionSeatBackend({
        sourceRepo: "/tmp/source",
        remote: "https://github.com/owner/name.git",
        runKey: 899,
        repo: "owner/name",
        imageName: "img",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        home: tempHome("rb-home-ss-prod-review-"),
      });
      await expect(
        backend.runStep(reviewerSpec, {
          branch: "feat/issue-899",
          base: "main",
          path: "/tmp/worktree/issue-899",
        }),
      ).resolves.toMatchObject({
        output: { kind: "judge", status: "converged" },
      });
      expect(sandcastleCalls).toBe(1);
      expect(agentOut.agent?.callCount).toBe(1);
    });

    it("production RealBackend coder seat: station-receipt SOE exhaust → #598, zero fixer", async () => {
      let sandcastleCalls = 0;
      class ProductionSeatBackend extends PreflightBackend {
        protected override async runAgentSandbox(
          options: Parameters<typeof scRuntime.run>[0],
        ): Promise<Awaited<ReturnType<typeof scRuntime.run>>> {
          sandcastleCalls += 1;
          this.lastAgentOptions = options;
          this.agentOptions.push(options);
          expect(options.output).toEqual(
            expect.objectContaining({
              tag: CODER_RECEIPT_TAG,
              maxRetries: RECEIPT_MAX_RETRIES,
            }),
          );
          return (
            await runScriptedStructuredOutput({
              tag: CODER_RECEIPT_TAG,
              schema: coderStationReceiptSchema(),
              emissions: [
                { body: JSON.stringify({ status: "maybe" }) },
                { body: JSON.stringify({ station: "coder" }) },
                { body: JSON.stringify({ station: "coder", status: "refused" }) },
              ],
              maxRetries: RECEIPT_MAX_RETRIES,
              sessionId: "prod-ss-coder-exhausted",
              cleanups,
            })
          ).result;
        }
      }
      const backend = new ProductionSeatBackend({
        sourceRepo: "/tmp/source",
        remote: "https://github.com/owner/name.git",
        runKey: 899,
        repo: "owner/name",
        imageName: "img",
        promptsDir: realPromptsDir,
        soulsDir: realSoulsDir,
        home: tempHome("rb-home-ss-prod-coder-"),
      });
      await expect(
        backend.runStep(coderSpec, {
          branch: "feat/issue-899",
          base: "main",
          path: "/tmp/worktree/issue-899",
        }),
      ).rejects.toSatisfy((err: unknown) => {
        // Sandcastle may wrap SOE in Effect FiberFailure/ExecError under load;
        // #598 disposition uses isReceiptRecoveryFailure (cause-chain aware).
        expect(isReceiptRecoveryFailure(err)).toBe(true);
        return true;
      });
      expect(sandcastleCalls).toBe(1);
    });
  });

});
