import {
  execFileSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  writeContainerCodexConfig,
  codexFastRunLog,
  runFamilyDriver,
  Sh,
  FamilyBackend,
  MergeRequest,
  ReconcileGit,
  Backend,
  RealBackendOptions,
  RealFamilyBackendOptions,
  ResolvedModelRoute,
  OFF_STATE_CONFIG_TOML,
  FAST_STATE_CONFIG_TOML,
  tempDirs,
  makeSourceRepo,
  makeEpicSh,
  fakeBackend,
  fakeFamilyBackend,
  runAssemblyWithEnv,
} from "./container-codex-fast.shared.js";

afterEach(() => {
  delete process.env.ORCHESTRATOR_CODEX_FAST;
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

describe("#760 container Codex fast master switch", () => {
  it("drives runFamilyDriver construction with fast on and off", async () => {
    const on = await runAssemblyWithEnv(true);
    expect(on.backend.codexFast).toBe(true);
    expect(on.family.codexFast).toBe(true);
    expect(on.config).toBe(FAST_STATE_CONFIG_TOML);

    const off = await runAssemblyWithEnv(false);
    expect(off.backend.codexFast).toBe(false);
    expect(off.family.codexFast).toBe(false);
    expect(off.config).toBe(OFF_STATE_CONFIG_TOML);
  });

});
