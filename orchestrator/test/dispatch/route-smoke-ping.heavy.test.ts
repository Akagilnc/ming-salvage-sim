import {
  mkdtempSync,
  mkdirSync,
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
  barePingArgv,
  barePingNonceSatisfied,
  buildBarePingPrompt,
  loadBarePingPromptTemplate,
  RealBackend,
  resolveRouteSmokeIdleTimeoutSeconds,
  resolveRouteModels,
  routeSmokeEntries,
  routeSmokeFailure,
  smokeRouteModels,
  logDriverStage,
  DRIVER_STAGES,
  runOrchestrator,
  Backend,
  IssueMeta,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  fixtureDir,
  promptsDir,
  soulsDir,
  tempHomes,
  tempHome,
  BarePingBackend,
} from "./route-smoke-ping.shared.js";

afterEach(() => {
  while (tempHomes.length > 0) {
    const h = tempHomes.pop();
    if (h !== undefined) rmSync(h, { recursive: true, force: true });
  }
  vi.restoreAllMocks();
});

describe("#884 bare-ping production smoke", () => {
  it("launches host bare ping with the same injected home and Claude token source as workers", async () => {
    const home = tempHome();
    const backend = new BarePingBackend(home, async (call) => call.nonce);

    await expect(backend.readProductionBarePingEnvironment()).resolves.toEqual({
      home,
      claudeToken: "test-token",
    });
  });

});
