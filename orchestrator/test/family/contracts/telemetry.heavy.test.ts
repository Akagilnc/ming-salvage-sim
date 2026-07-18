import {
  mkdtempSync,
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
  dispatchFamilyWorkerWithMonitor,
  runFamily,
  RealFamilyBackend,
  MergerAuth,
  resolveRouteModels,
  routeSmokeEntries,
  skeletonReviewLoopWorkerResult,
  clearTelemetryRunEnvironment,
  readTelemetryRecords,
  TelemetryCollectRecord,
  TelemetryDispatchRecord,
  TelemetryEnvironmentRecord,
  TelemetryReviewRoundRecord,
  Backend,
  DispatchContext,
  IssueMeta,
  StepOutput,
  WorkerResult,
  WorkerSpec,
  WorktreeHandle,
  FamilyBackend,
  FamilyLedgerEntry,
  FamilyVerifyResult,
  MergeRequest,
  buildExplicitLandingLiveHooks,
  tempDirs,
  here,
  realPromptsDir,
  realSoulsDir,
  tempDir,
  smokedRoute,
  familySpec,
  resultFor,
  waitForEnvironment,
  COMPLETE_CMR_LEGS,
  FAMILY_HEAD,
  FamilyTelemetryBackend,
  SmokeOnlySingleSliceBackend,
} from "./telemetry.shared.js";

afterEach(() => {
  clearTelemetryRunEnvironment();
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("#786 family dispatch telemetry", () => {

  it.each([
    ["failed", "failed", { kind: "failed", reason: "worker exited 1" }, "rejected"],
  ] as const)("preserves the %s worker verdict when the runner routes it", async (_label, verdict, terminal, finalDisposition) => {
    class RejectedTerminalBackend extends FamilyTelemetryBackend {
      override async dispatchWorker(
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): Promise<WorkerResult> {
        if (spec.kind === "cmr") {
          this.ctxs.push(ctx);
          return terminal;
        }
        return super.dispatchWorker(spec, ctx);
      }
    }

    const durable = join(tempDir("orch-786-protocol-rejected-"), ".ledger-809");
    const result = await runFamily({
      epic: { issue: 809, children: [] },
      familyBackend: new RejectedTerminalBackend(durable),
      singleSliceBackend: new SmokeOnlySingleSliceBackend(),
      familyBase: "family/809-sidecar",
    });

    expect(result.status).not.toBe("completed");
    expect(
      readTelemetryRecords(durable).filter(
        (record): record is TelemetryReviewRoundRecord => record.phase === "review_round",
      ),
    ).toContainEqual(
      expect.objectContaining({
        verdict,
        finalDisposition,
      }),
    );
  });

  it.each([
    ["family CMR", "cmr", "failed", "429-quota"],
    ["family verify", "verify", "thrown", "stream-disconnect"],
  ] as const)(
    "%s writes joined dispatch/collect sidecar rows and the terminal classification",
    async (_label, kind, terminal, errorCategory) => {
      const ledgerDir = join(tempDir(`orch-786-family-${kind}-`), ".ledger");
      const backend = {
        dispatchWorker: async (spec: WorkerSpec): Promise<WorkerResult> => resultFor(spec.kind),
        installTelemetryRunEnvironment: async () => {},
      } as unknown as FamilyBackend;
      const ctx: DispatchContext = {
        familyBase: "feat/family-786",
        stateDir: ledgerDir,
        modelRoute: smokedRoute(),
      };

      if (kind === "verify") {
        await expect(
          dispatchFamilyWorkerWithMonitor(backend, familySpec(kind), ctx),
        ).rejects.toThrow(/stream disconnect/);
      } else {
        await dispatchFamilyWorkerWithMonitor(backend, familySpec(kind), ctx);
      }

      expect(await waitForEnvironment(ledgerDir)).toBeDefined();
      const records = readTelemetryRecords(ledgerDir);
      const dispatch = records.find(
        (record): record is TelemetryDispatchRecord => record.phase === "dispatch",
      );
      const collect = records.find(
        (record): record is TelemetryCollectRecord => record.phase === "collect",
      );
      expect(dispatch).toBeDefined();
      expect(collect).toMatchObject({
        legId: dispatch?.legId,
        terminal,
        errorCategory,
      });
    },
  );

  it("schedules the lazy environment stamp even when the spawn callback throws", async () => {
    const ledgerDir = join(tempDir("orch-786-family-callback-"), ".ledger");
    const backend = {
      resolveCliMonitorDispatch: (spec: WorkerSpec) => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => process.exit(0), 50)"],
        logDir: ledgerDir,
        poolId: `codex/${spec.model}`,
        stepId: spec.id,
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
      installTelemetryRunEnvironment: async () => {},
    } as unknown as FamilyBackend;

    await expect(
      dispatchFamilyWorkerWithMonitor(
        backend,
        familySpec("cmr"),
        {
          familyBase: "feat/family-786",
          stateDir: ledgerDir,
          modelRoute: smokedRoute(),
        },
        undefined,
        {
          onMonitorHandleSpawned: async () => {
            throw new Error("ledger persistence failed");
          },
        },
      ),
    ).rejects.toThrow(/ledger persistence failed/);

    expect(await waitForEnvironment(ledgerDir)).toBeDefined();
  });

  it("records first output from a monitored family CLI worker", async () => {
    const ledgerDir = join(tempDir("orch-786-family-first-output-"), ".ledger");
    const backend = {
      resolveCliMonitorDispatch: (spec: WorkerSpec) => ({
        command: process.execPath,
        args: ["-e", "process.stdout.write('family worker output\\n')"],
        logDir: ledgerDir,
        poolId: `codex/${spec.model}`,
        stepId: spec.id,
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
      installTelemetryRunEnvironment: async () => {},
    } as unknown as FamilyBackend;

    await dispatchFamilyWorkerWithMonitor(backend, familySpec("cmr"), {
      familyBase: "feat/family-786",
      stateDir: ledgerDir,
      modelRoute: smokedRoute(),
    });

    const collect = readTelemetryRecords(ledgerDir).find(
      (record): record is TelemetryCollectRecord => record.phase === "collect",
    );
    expect(collect?.first_output_at).not.toBeNull();
  });

});
