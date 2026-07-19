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

  it("NEGATIVE: validateMonitorHandle rejects incomplete handle shapes", () => {
    expect(validateMonitorHandle(undefined)).toBe(false);
    expect(
      validateMonitorHandle({
        pid: 1,
        logPath: "/tmp/x",
        poolId: "p",
        stepId: "S2",
        dispatchedAt: "t",
        instanceId: "",
      } as WorkerMonitorHandle),
    ).toBe(false);
    expect(
      validateMonitorHandle({
        pid: -1,
        logPath: "/tmp/x",
        poolId: "p",
        stepId: "S2",
        dispatchedAt: "t",
        instanceId: "id",
      } as WorkerMonitorHandle),
    ).toBe(false);
  });

  it("readLogActivity reports growth; silenceWholeMinutes is pure report", () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-log-"));
    try {
      const logPath = join(dir, "worker.log");
      writeFileSync(logPath, "line1\n", "utf8");
      const handle = baseHandle({ pid: process.pid, logPath });
      const first = readLogActivity(handle);
      expect(first).toBeDefined();
      writeFileSync(logPath, "line1\nline2\n", "utf8");
      const second = readLogActivity(handle);
      expect(second!.sizeBytes).toBeGreaterThan(first!.sizeBytes);

      expect(silenceWholeMinutes(Date.now() - 59_000, Date.now())).toBe(0);
      expect(silenceWholeMinutes(Date.now() - 120_000, Date.now())).toBe(2);
      // NEGATIVE: non-finite inputs yield 0 (never invent silence)
      expect(silenceWholeMinutes(Number.NaN, Date.now())).toBe(0);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("NEGATIVE: missing log is not evidence of activity", () => {
    const handle = baseHandle({
      pid: process.pid,
      logPath: join(tmpdir(), `missing-${Date.now()}.log`),
    });
    expect(readLogActivity(handle)).toBeUndefined();
  });

  it("monitorHandleFromLedger rebuilds only valid shapes", () => {
    const good: Pick<LedgerEntry, "monitorHandle"> = {
      monitorHandle: baseHandle({
        pid: 42,
        logPath: "/tmp/ledger.log",
      }),
    };
    expect(monitorHandleFromLedger(good)?.pid).toBe(42);

    const bad: Pick<LedgerEntry, "monitorHandle"> = {
      monitorHandle: {
        pid: 0,
        logPath: "/tmp/x",
        poolId: "p",
        stepId: "S2",
        dispatchedAt: "t",
        instanceId: "id",
      },
    };
    expect(monitorHandleFromLedger(bad)).toBeUndefined();
  });

  it("poolIdForWorker derives host/model identity from the worker spec", () => {
    expect(
      poolIdForWorker({
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
      } as WorkerSpec),
    ).toBe("codex/glm-5.2");
  });

  it("NEGATIVE: unconfirmed exit after SIGKILL raises worker_termination_failed", async () => {
    const { WorkerTerminationFailedError } = await import(
      "../../src/workerMonitor.js"
    );
    const child = {
      pid: 4242,
      exitCode: null as number | null,
      signalCode: null as NodeJS.Signals | null,
      kill: () => true,
    };
    await expect(
      terminateSpawnedChild(child as never, {
        killPid: () => {
          // Deliberately leave exitCode null → unconfirmed.
        },
        sleepMs: async () => {},
      }, { instanceId: "test-instance" }),
    ).rejects.toBeInstanceOf(WorkerTerminationFailedError);
    await expect(
      terminateSpawnedChild(child as never, {
        killPid: () => {},
        sleepMs: async () => {},
      }, { instanceId: "test-instance" }),
    ).rejects.toMatchObject({
      reason: "worker_termination_failed",
      pid: 4242,
      instanceId: "test-instance",
    });
  });

});
