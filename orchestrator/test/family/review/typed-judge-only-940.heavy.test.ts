import {
  existsSync,
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
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  dispatchWorkerWithMonitor,
  runOnlineReviewLoopStage,
  runVerifyCmr,
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  PrReviewSnapshot,
  Backend,
  CliMonitorSpawnSpec,
  ShipResult,
  VerifyResult,
  WorkerResult,
  WorkerSpec,
  buildExplicitLandingLiveHooks,
  tempDirs,
  STAGE_SHIP,
  BASE_SNAPSHOT,
  coderSpec,
  completedJudgeGreen,
  completedShip,
  DispatchCapableBackend,
} from "./typed-judge-only-940.shared.js";

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("#940 unified worker dispatch — ID-004 / ID-006 still hold", () => {

  it("POSITIVE: adoption-record failure terminates exact ChildProcess handle (ID-006)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-940-adopt-"));
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
    let spawnedPid: number | undefined;
    await expect(
      dispatchWorkerWithMonitor(backend, coderSpec(), {}, undefined, {
        onMonitorHandleSpawned: async (handle) => {
          spawnedPid = handle.pid;
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
    // CR-15: kill targets the exact spawn PID (process-group form is -pid).
    expect(spawnedPid).toEqual(expect.any(Number));
    expect(
      killed.some((p) => p === spawnedPid || p === -spawnedPid!),
    ).toBe(true);
  });
});
