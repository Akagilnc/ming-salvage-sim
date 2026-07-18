import {
  describe,
  expect,
  it,
  runVerifyCmr,
  cmrWorkerSpec,
  dispatchFamilyWorker,
  dispatchFamilyWorkerWithMonitor,
  familyCoderFixWorkerSpec,
  familyShipWorkerSpec,
  legacyDispatchFamilyWorker,
  mkdtempSync,
  rmSync,
  tmpdir,
  join,
  resolveActiveModelRoute,
  smokeRouteModels,
  DispatchContext,
  WorkerResult,
  WorkerSpec,
  legacyCmrScriptToWorkerOutput,
  liveCmrJudgeContinue,
  FamilyBackend,
  FamilyEscalation,
  FamilyLedgerEntry,
  FamilyVerifyRequest,
  FamilyVerifyResult,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  buildExplicitLandingLiveHooks,
  CMR_EVIDENCE,
  completedJudgeGreen,
  CapableFamilyBackend,
} from "./final-gate-dispatch.shared.js";

describe("#331 family verify-cmr routes cmr + PR through dispatchFamilyWorker", () => {

  it("family monitored dispatch produces and persists its handle before awaiting the child", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-family-monitor-"));
    try {
      const events: string[] = [];
      const backend = {
        resolveCliMonitorDispatch: (spec: WorkerSpec) => ({
          command: process.platform === "win32" ? "cmd" : "true",
          args: process.platform === "win32" ? ["/c", "exit", "0"] : [],
          logDir: dir,
          poolId: `claude/${spec.model}`,
          stepId: spec.id,
        }),
        awaitMonitoredCliWorker: async () => {
          events.push("awaited");
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
          } as WorkerResult;
        },
      } as unknown as FamilyBackend;

      const outcome = await dispatchFamilyWorkerWithMonitor(
        backend,
        cmrWorkerSpec(),
        { familyBase: "family/base" },
        undefined,
        {
          onMonitorHandleSpawned: async (handle) => {
            events.push(`persisted:${handle.stepId}`);
          },
        },
      );

      expect(outcome.monitorHandle).toBeDefined();
      expect(events).toEqual(["persisted:S3", "awaited"]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

});
