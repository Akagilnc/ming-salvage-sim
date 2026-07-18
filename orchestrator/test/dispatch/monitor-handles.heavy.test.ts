import {
  spawn,
  existsSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  describe,
  expect,
  it,
  dispatchWorkerWithMonitor,
  dispatchMonitoredCliWorker,
  monitorHandleFromLedger,
  poolIdForWorker,
  readLogActivity,
  silenceWholeMinutes,
  terminateSpawnedChild,
  validateMonitorHandle,
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  LedgerEntry,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
  baseHandle,
  sleepWorker,
} from "./monitor-handles.shared.js";

describe("#684/#937 worker monitor handles", () => {
  it("dispatchMonitoredCliWorker yields a valid handle without spawn-ack timeout", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-spawn-"));
    try {
      const { handle, child } = await sleepWorker(dir, "zai", "S2");
      expect(validateMonitorHandle(handle)).toBe(true);
      expect(handle.pid).toBeGreaterThan(0);
      expect(existsSync(handle.logPath)).toBe(true);
      expect(handle.instanceId).toBe("test-instance-S2");
      await terminateSpawnedChild(child);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("terminateSpawnedChild signals the exact child (adoption-failure path)", async () => {
    const child = spawn(
      process.platform === "win32" ? "ping" : "sleep",
      process.platform === "win32" ? ["-n", "600"] : ["600"],
      { detached: true, stdio: "ignore" },
    );
    const killed: Array<{ pid: number; signal: string }> = [];
    await terminateSpawnedChild(child, {
      killPid: (pid, signal) => {
        killed.push({ pid, signal });
        // Confirm exit for ID-006 (mock ChildProcess does not get OS exit events
        // when only negative-pid group signals fire in restricted sandboxes).
        Object.defineProperty(child, "exitCode", {
          value: 1,
          configurable: true,
        });
        try {
          process.kill(pid, 0);
          process.kill(pid, signal);
        } catch {
          // group may not exist in restricted sandboxes
        }
      },
      sleepMs: async () => {},
    });
    // At least one signal attempt against the process group or handle.
    expect(killed.length + (child.killed ? 1 : 0)).toBeGreaterThan(0);
    try {
      child.kill("SIGKILL");
    } catch {
      // already reaped
    }
  });

  it("dispatchWorkerWithMonitor waits for exit only — silence does not kill", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-dispatch-"));
    try {
      const backend = {
        resolveCliMonitorDispatch: (
          _spec: WorkerSpec,
          _ctx: DispatchContext,
        ): CliMonitorSpawnSpec => ({
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

      const killed: number[] = [];
      const outcome = await dispatchWorkerWithMonitor(
        backend,
        {
          id: "S2",
          kind: "coder",
          role: "coder",
          host: "codex",
          session: "fresh",
          contextRetention: "retain",
          promptFile: "coder.md",
          maxIter: 1,
          model: "glm-5.2",
          soul: "coder",
          toolchain: [],
        } as WorkerSpec,
        {},
        undefined,
        {
          monitorDeps: {
            readInstanceId: () => "test-instance",
            killPid: (pid) => killed.push(pid),
            sleepMs: async () => {},
          },
        },
      );
      expect(outcome.result.kind).toBe("completed");
      // No idle kill path — adoption failure is the only host kill seam.
      expect(killed).toEqual([]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("NEGATIVE: free-log relay tags are not a host fate channel", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-nolog-fate-"));
    try {
      writeFileSync(
        join(dir, "S2.log"),
        '<relay>{"blocked":{"reason":"stale","state_summary":"x","remaining":"y"}}</relay>\n',
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
        dispatchWorkerWithMonitor(
          backend,
          {
            id: "S2",
            kind: "coder",
            role: "coder",
            host: "codex",
            session: "fresh",
            contextRetention: "retain",
            promptFile: "coder.md",
            maxIter: 1,
            model: "glm-5.2",
            soul: "coder",
            toolchain: [],
          } as WorkerSpec,
          {},
        ),
      ).resolves.toMatchObject({ result: { kind: "completed" } });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
