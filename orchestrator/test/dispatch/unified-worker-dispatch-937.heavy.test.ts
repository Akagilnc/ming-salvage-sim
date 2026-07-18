import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  vi,
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  dispatchWorkerWithMonitor,
  resolveCoderRecOrder,
  DEFAULT_PARK_THRESHOLD_MS,
  QuotaWaitForResetError,
  parkOrRelayQuotaWall,
  MAX_RELAY_HANDOFFS,
  canRelayHandoff,
  countRelayHandoffsInLedger,
  renderEphemeralRelayBrief,
  buildRelayHandoffLedgerEntry,
  RELAY_FOCUS_FILENAME,
  terminateSpawnedChild,
  Backend,
  CliMonitorSpawnSpec,
  WorkerResult,
  WorkerSpec,
  tempDirs,
  coderSpec,
  quotaWallError,
} from "./unified-worker-dispatch-937.shared.js";

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("#937 unified worker dispatch — ID-006 process ownership", () => {
  it("POSITIVE: adoption-record failure terminates exact ChildProcess handle", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-adopt-"));
    tempDirs.push(dir);
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 60_000)"],
        logDir: dir,
        poolId: "zai",
        stepId: "S2",
        readInstanceId: () => "test-instance",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    const killed: number[] = [];
    await expect(
      dispatchWorkerWithMonitor(backend, coderSpec(), {}, undefined, {
        onMonitorHandleSpawned: async () => {
          throw new Error("adoption persist failed");
        },
        monitorDeps: {
          readInstanceId: () => "test-instance",
          killPid: (pid, signal) => {
            killed.push(pid);
            try {
              process.kill(pid, signal);
            } catch {
              // group signal may fail in restricted sandboxes
            }
          },
          sleepMs: async () => {},
        },
      }),
    ).rejects.toThrow(/adoption persist failed/);
    expect(killed.length).toBeGreaterThan(0);
  });

  it("NEGATIVE: free-log relay tags never become a host fate throw", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-nofate-"));
    tempDirs.push(dir);
    writeFileSync(
      join(dir, "S2.log"),
      '<relay>{"decision_gate":{"state_summary":"ask human"}}</relay>\n',
    );
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.platform === "win32" ? "cmd" : "true",
        args: process.platform === "win32" ? ["/c", "exit", "0"] : [],
        logDir: dir,
        poolId: "zai",
        stepId: "S2",
        readInstanceId: () => "test-instance",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    await expect(
      dispatchWorkerWithMonitor(backend, coderSpec(), {}),
    ).resolves.toMatchObject({ result: { kind: "completed" } });
  });
});

describe("#937 public driver seams — ID-007 silence + ID-008 relay", () => {

  it("POSITIVE: long-lived silent child is never host-killed (ID-007)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-long-silence-"));
    tempDirs.push(dir);
    const killed: number[] = [];
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        // Stay alive well past former idle tiers (10/30 min) — compressed via
        // instant sleepMs inject; real wall is process exit only.
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 200)"],
        logDir: dir,
        poolId: "zai",
        stepId: "S2",
        readInstanceId: () => "test-instance-long",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    const outcome = await dispatchWorkerWithMonitor(
      backend,
      coderSpec(),
      {},
      undefined,
      {
        monitorDeps: {
          readInstanceId: () => "test-instance-long",
          killPid: (pid) => killed.push(pid),
          // No idle poll path remains — sleepMs is only used by terminateSpawnedChild.
          sleepMs: async () => {},
        },
      },
    );
    expect(outcome.result.kind).toBe("completed");
    expect(killed).toEqual([]);
  });

  it("POSITIVE: public runOrchestrator — long quiet CLI worker completes without host kill (ID-007)", async () => {
    // #937 AC: public ignition/driver proof — not only the helper.
    // Production wire: runOrchestrator → dispatchWorkerWithMonitor → CLI spawn.
    // Silence must never invent host kill; process exit alone yields completed.
    const { runOrchestrator } = await import("../../src/runner.js");
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../src/reviewLoopOutcome.js"
    );
    type IssueMeta = import("../../src/types.js").IssueMeta;
    type WorktreeHandle = import("../../src/types.js").WorktreeHandle;
    type PersistentLedgerEntry = import("../../src/types.js").PersistentLedgerEntry;
    type StepOutput = import("../../src/types.js").StepOutput;
    type WorkerSpec = import("../../src/types.js").WorkerSpec;

    const dir = mkdtempSync(join(tmpdir(), "orch-937-public-silence-"));
    tempDirs.push(dir);
    const worktree: WorktreeHandle = {
      branch: "feat/937-public-silence",
      base: "main",
      path: dir,
    };
    const cliExitCodes: Array<number | null> = [];
    const processKillSpy = vi.spyOn(process, "kill").mockImplementation(
      ((_pid: number, _sig?: NodeJS.Signals | number) => true) as typeof process.kill,
    );

    const backend = {
      async smokeModelRoute(route: never): Promise<never> {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route as never, async () => ({
          cliVersion: "test",
        })) as never;
      },
      async findResumeState(): Promise<undefined> {
        return undefined;
      },
      async resumeSession(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5",
        };
      },
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      },
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger(_entry: PersistentLedgerEntry): Promise<void> {},
      // Only S2 takes the monitored CLI path (long quiet child); other agent
      // seats fall through to dispatchWorker so the public run can complete.
      resolveCliMonitorDispatch: (
        spec: WorkerSpec,
      ): CliMonitorSpawnSpec | undefined => {
        if (spec.id !== "S2") return undefined;
        return {
          command: process.execPath,
          // Quiet wall well past former idle tiers; host must wait for exit only.
          args: ["-e", "setTimeout(() => {}, 250)"],
          logDir: dir,
          poolId: "grok-build",
          stepId: "S2",
          readInstanceId: () => "public-silence-instance",
        };
      },
      awaitMonitoredCliWorker: async (
        _handle: unknown,
        exitCode: number | null,
      ): Promise<WorkerResult> => {
        cliExitCodes.push(exitCode);
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.id === "S2") {
          // Must not be used for S2 when CLI path is active.
          return {
            kind: "failed",
            reason: "S2 must use resolveCliMonitorDispatch path",
          };
        }
        if (spec.id === "S3" || spec.kind === "reviewer" || spec.role === "verify") {
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
    } as unknown as Backend;

    try {
      const result = await runOrchestrator({
        issueNumber: 937,
        backend,
        now: () => new Date("2026-07-10T12:00:00.000Z"),
      });
      expect(result.status).toBe("completed");
      // Quiet child exited 0 on its own — not signal-killed (exitCode null).
      expect(cliExitCodes).toContain(0);
      expect(cliExitCodes.every((c) => c === 0)).toBe(true);
      // Host never process.kill'd the quiet worker for silence (ID-007).
      // Adoption-failure is the only remaining host-kill seam; this path had none.
      const killArgs = processKillSpy.mock.calls.map((c) => c[1]);
      expect(killArgs.every((sig) => sig === undefined || sig === 0)).toBe(true);
    } finally {
      processKillSpy.mockRestore();
    }
  });

});

describe("#937 ID-015 / ID-016 delete boundaries", () => {
  it("NEGATIVE: terminateSpawnedChild is a no-op when the child already exited", async () => {
    const { spawn } = await import("node:child_process");
    const child = spawn(
      process.platform === "win32" ? "cmd" : "true",
      process.platform === "win32" ? ["/c", "exit", "0"] : [],
      { stdio: "ignore" },
    );
    await new Promise<void>((resolve) => child.once("exit", () => resolve()));
    const killPid = vi.fn();
    await terminateSpawnedChild(child, {
      killPid,
      sleepMs: async () => {},
    });
    expect(killPid).not.toHaveBeenCalled();
  });

});
