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

  it(
    "live headless empty-auth fails fast before timeout (no device-auth hang)",
    () => {
      const pidDir = mkDir("964-timeout-child-");
      const pidFile = join(pidDir, "pid");
      const hang = runHostPipeProbe(
        "/bin/sh",
        ["-c", 'echo $$ > "$PID_FILE"; exec sleep 60'],
        { ...process.env, PID_FILE: pidFile },
        2_000,
      );
      expect(hang.timedOut).toBe(true);
      const childPid = Number(readFileSync(pidFile, "utf8").trim());
      let childAlive = true;
      try {
        process.kill(childPid, 0);
      } catch (error: any) {
        if (error?.code !== "ESRCH") throw error;
        childAlive = false;
      }
      expect(childAlive, `timed-out probe child ${childPid} must be reaped`).toBe(false);

      // #964 AC: real worker print shape + empty credentials must not enter
      // interactive device-code wait. Pin 0.2.102 is the production hang fix;
      // this probe exercises a real binary (host pin or baked image pin).
      // Only this live portion skips when no eligible binary is available; the
      // timeout/reap guard above is environment-independent and always runs.
      const target = resolveGrokProbeTarget();
      if (!target) {
        console.warn(
          `[#964] skip live empty-auth probe: no grok ${GROK_FAIL_FAST_PIN} on PATH/GROK_BIN ` +
            `and no docker image with that pin (set GROK_BIN or rebake ${DEFAULT_GROK_PROBE_IMAGE}; ` +
            `override image via GROK_PROBE_IMAGE). Pin ${GROK_FAIL_FAST_PIN} remains the production mechanism.`,
        );
        return;
      }

      const result = runHeadlessEmptyAuthProbe(target);
      // Must exit on its own (non-zero fail-fast), not be killed by our wall clock.
      expect(
        result.timedOut,
        `grok empty-auth hung until hard timeout (${HEADLESS_AUTH_PROBE_TIMEOUT_MS}ms) ` +
          `via ${target.kind}=${target.kind === "host" ? target.bin : target.image} ` +
          `version=${target.version}; expected native fail-fast (pin ${GROK_FAIL_FAST_PIN})`,
      ).toBe(false);
      expect(result.status, result.combined).not.toBeNull();
      expect(result.status, result.combined).not.toBe(0);
      // Fail-fast class outcome (native CLI message on pin ≥0.2.102).
      expect(result.combined).toMatch(/Not signed in|unauthenticated|Unauthorized/i);
      // Well under the wall — hang regression would burn the full timeout.
      expect(result.elapsedMs).toBeLessThan(HEADLESS_AUTH_PROBE_TIMEOUT_MS);
      expect(result.stagedFiles).toEqual([]);
    },
    HEADLESS_AUTH_PROBE_TIMEOUT_MS + 30_000,
  );

  it("live GROK_BIN target remains authoritative when PATH has no grok", ({ skip }) => {
    const result = runHeadlessEmptyAuthProbe(
      requirePinnedHostTarget(skip),
      "/usr/bin:/bin",
    );
    expect(result.status, result.combined).not.toBe(0);
    expect(result.combined).toMatch(/Not signed in|unauthenticated|Unauthorized/i);
  });

  it("live GROK_BIN target wins over a different grok on PATH", ({ skip }) => {
    const decoyDir = mkDir("964-decoy-grok-");
    const decoy = join(decoyDir, "grok");
    writeFileSync(decoy, "#!/bin/sh\necho WRONG_GROK >&2\nexit 77\n");
    chmodSync(decoy, 0o755);
    const result = runHeadlessEmptyAuthProbe(
      requirePinnedHostTarget(skip),
      `${decoyDir}:/usr/bin:/bin`,
    );
    expect(result.combined).not.toContain("WRONG_GROK");
    expect(result.combined).toMatch(/Not signed in|unauthenticated|Unauthorized/i);
  });

});

describe("#964 AgentError → Action typed failure (merger worker entry)", () => {

  it("runMergerAgent maps AgentError to structured non-resolve (owning Action, no throw)", async () => {
    const be = new AgentErrorSandboxBackend(baseOpts(makeRepo()));
    const outcome = await be.run({
      childIssue: 964,
      childBranch: "feat/964",
    });
    expect(outcome.resolved).toBe(false);
    expect(outcome.reason).toMatch(/Not signed in|AgentError|invocation failed/i);
  });

  it("resolveMergeConflict turns AgentError into conflicted typed result with reason (no uncaught throw)", async () => {
    const be = new AgentErrorSandboxBackend(baseOpts(makeRepo()));
    const result = await be.resolveMergeConflict({
      childIssue: 964,
      childBranch: "feat/964",
    });
    expect(result.conflicted).toBe(true);
    expect(result.escalation).toBeUndefined();
    expect(result.familyHeadBefore).toBe("family-head");
    expect(result.childHead).toBe("child-head");
    // #964 S3: non-empty agent reason survives MergeResult for re-login ops.
    expect(result.reason).toMatch(/Not signed in|invocation failed/i);
  });

  it("mergeChild wires AgentError → Action-owned conflicted (no process throw)", async () => {
    // #964 S4: thinnest real entry above resolveMergeConflict (Action path).
    const be = new MergeChildAgentErrorBackend(baseOpts(makeRepo()));
    const result = await mergeChild(be, {
      childIssue: 964,
      childBranch: "feat/964",
    });
    expect(result.conflicted).toBe(true);
    expect(result.escalation).toBeUndefined();
    expect(result.conflictResolvedByLlm).toBeUndefined();
    expect(result.reason).toMatch(/Not signed in|invocation failed/i);
  });
});

describe("#964 AgentError → Action typed failure (generic Worker Invocation)", () => {

  it("dispatchFamilyWorker converts AgentError on non-merger coder seat (no uncaught throw)", async () => {
    // Real free-function Worker Invocation seam (production path for family seats).
    const route = smokedRoute();
    const be = new CoderAgentErrorFamilyBackend(baseOpts(makeRepo()));
    const result = await dispatchFamilyWorker(
      be,
      familyCoderFixWorkerSpec(route),
      { familyBase: "family/964-base", modelRoute: route },
    );
    expect(result.kind).toBe("escalated");
    if (result.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result.escalation)).toBe(true);
    expect(result.escalation.reason).toMatch(
      /agent invocation failed|Not signed in/i,
    );
  });

});
