import {
  execFileSync,
  spawnSync,
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
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
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  dispatchWorker,
  dispatchFamilyWorker,
  familyCoderFixWorkerSpec,
  buildExplicitLandingLiveHooks,
  mergeChild,
  RealFamilyBackend,
  RealFamilyBackendOptions,
  ConflictResolveRequest,
  FamilyBackend,
  MergeRequest,
  MergeResult,
  grokAgent,
  shellEscape,
  resolveRouteModels,
  routeSmokeEntries,
  ResolvedModelRoute,
  PUBLIC_FAILED_CAUSES,
  barePingArgv,
  isRunnerSynthesizedFailureEscalation,
  isSandcastleAgentError,
  workerResultFromAgentError,
  Backend,
  DispatchContext,
  WorkerResult,
  WorkerSpec,
  here,
  orchestratorRoot,
  promptsDir,
  soulsDir,
  GROK_FAIL_FAST_PIN,
  HEADLESS_AUTH_PROBE_TIMEOUT_MS,
  DEFAULT_GROK_PROBE_IMAGE,
  tmpDirs,
  mkDir,
  whichBinary,
  hostGrokVersion,
  dockerGrokVersion,
  GrokProbeTarget,
  resolveGrokProbeTarget,
  emptyAuthEnv,
  requirePinnedHostTarget,
  HeadlessProbeResult,
  runHostPipeProbe,
  runHeadlessEmptyAuthProbe,
  makeRepo,
  baseOpts,
  fiberAgentError,
  AgentErrorSandboxBackend,
  MergeChildAgentErrorBackend,
  smokedRoute,
  midRunAgentError,
  CoderAgentErrorFamilyBackend,
} from "./grok-mid-run-auth-964.shared.js";

afterEach(() => {
  for (const d of tmpDirs) rmSync(d, { recursive: true, force: true });
  tmpDirs.length = 0;
});

describe("#964 grok headless auth — native fail-fast surface", () => {
  it("grokAgent print command stays headless (prompt-file + streaming-json; no login subcommand)", () => {
    const cmd = grokAgent("grok-4.5").buildPrintCommand({
      prompt: "resolve the conflict",
      dangerouslySkipPermissions: true,
    });
    expect(cmd.command).toContain("grok ");
    expect(cmd.command).toContain("prompt_file=$(mktemp)");
    expect(cmd.command).toContain('cat > "$prompt_file"');
    expect(cmd.command).toContain('--prompt-file "$prompt_file"');
    expect(cmd.command).toContain("--output-format streaming-json");
    expect(cmd.command).toContain("--always-approve");
    expect(cmd.command).not.toMatch(/\blogin\b/);
    expect(cmd.command).not.toMatch(/--device-auth|--device-code/);
    expect(cmd.stdin).toBe("resolve the conflict");
  });

  it("pins container grok to a fail-fast non-interactive release (0.2.102+)", () => {
    // Production mechanism (#964): pin ≥0.2.102 so headless auth death fail-fasts
    // ("Not signed in") instead of interactive device-code wait (0.2.93 flight3).
    // Companion live probe below guards hang regression when a matching binary
    // is available (GROK_BIN / PATH / baked image).
    const containerfile = readFileSync(
      join(orchestratorRoot, "image", "Containerfile"),
      "utf8",
    );
    expect(containerfile).toMatch(
      /npm install -g @xai-official\/grok@0\.2\.102/,
    );
    expect(containerfile).toMatch(/grok --version \| grep -F "0\.2\.102"/);
    expect(containerfile).not.toMatch(/@xai-official\/grok@0\.2\.93/);
  });

  it("route-smoke bare-ping keeps the same headless shape (startup auth not rewritten)", () => {
    const built = barePingArgv(
      "grok",
      "grok-4.5",
      "Reply with exactly: nonce-964",
    );
    expect(built.file).toBe("grok");
    expect(built.args).toContain("-p");
    expect(built.args).toContain("Reply with exactly: nonce-964");
    expect(built.args).toContain("--always-approve");
    expect(built.input).toBeUndefined();
  });

  it("does not introduce an auth_expired (or other new) public failed cause", () => {
    expect(PUBLIC_FAILED_CAUSES).not.toContain("auth_expired");
    expect(PUBLIC_FAILED_CAUSES).not.toContain("auth_failed");
    expect(PUBLIC_FAILED_CAUSES).not.toContain("device_auth_failed");
  });
});

describe("#964 AgentError → Action typed failure (merger worker entry)", () => {
  it("isSandcastleAgentError recognizes FiberFailure-wrapped AgentError", () => {
    expect(
      isSandcastleAgentError(fiberAgentError("grok exited with code 1")),
    ).toBe(true);
    expect(isSandcastleAgentError(new Error("plain crash"))).toBe(false);
  });

});

describe("#964 AgentError → Action typed failure (generic Worker Invocation)", () => {
  it("workerResultFromAgentError maps AgentError to host-synthesized escalated (single court)", () => {
    const result = workerResultFromAgentError(
      fiberAgentError("Not signed in"),
      "coder",
    );
    expect(result).toBeDefined();
    expect(result!.kind).toBe("escalated");
    if (result!.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result!.escalation)).toBe(true);
    expect(result!.escalation.reason).toMatch(
      /coder agent invocation failed|Not signed in/i,
    );
    expect(workerResultFromAgentError(new Error("plain crash"), "coder")).toBe(
      undefined,
    );
  });

  it("withMechanicalRetry does not re-dispatch AgentError (dead credentials once)", async () => {
    const route = smokedRoute();
    const spec = familyCoderFixWorkerSpec(route);
    let attempts = 0;
    const result = await withMechanicalRetry(
      spec,
      { familyBase: "family/964-base", modelRoute: route },
      async () => {
        attempts += 1;
        throw midRunAgentError();
      },
    );
    expect(attempts).toBe(1);
    expect(result.kind).toBe("escalated");
    if (result.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result.escalation)).toBe(true);
    expect(result.escalation.reason).toMatch(/agent invocation failed|Not signed in/i);
  });

  it("dispatchWorker (single-slice seam) converts AgentError to typed failure (no throw)", async () => {
    const route = smokedRoute();
    const throwsAgent: Backend = {
      async dispatchWorker(
        _spec: WorkerSpec,
        _ctx: DispatchContext,
      ): Promise<WorkerResult> {
        throw midRunAgentError();
      },
    } as Backend;
    const spec: WorkerSpec = {
      id: "S2",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      promptFile: "coder.md",
      maxIter: 1,
      model: "gpt-5.6-terra",
      soul: "coder",
      toolchain: [],
    };
    const result = await dispatchWorker(throwsAgent, spec, {
      modelRoute: route,
    });
    expect(result.kind).toBe("escalated");
    if (result.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result.escalation)).toBe(true);
    expect(result.escalation.reason).toMatch(/coder agent invocation failed|Not signed in/i);
  });

  it("FamilyBackend method throw is converted at free-function court (cmr-class seat)", async () => {
    // Prove free-function court, not merger-only: any family dispatchWorker throw.
    const route = smokedRoute();
    const be = {
      async dispatchWorker(): Promise<WorkerResult> {
        throw fiberAgentError("Not signed in");
      },
    } as unknown as FamilyBackend;
    const result = await dispatchFamilyWorker(
      be,
      { ...familyCoderFixWorkerSpec(route), kind: "cmr", role: "verify", soul: "verify" },
      { familyBase: "family/964-base", modelRoute: route },
    );
    expect(result.kind).toBe("escalated");
    if (result.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result.escalation)).toBe(true);
  });
});
