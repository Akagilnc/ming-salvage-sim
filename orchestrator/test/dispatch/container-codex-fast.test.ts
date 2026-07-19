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

  it("keeps the current config byte-identical when fast is off", async () => {
    const dir = mkdtempSync(join(tmpdir(), "codex-fast-760-off-"));
    tempDirs.push(dir);
    const path = join(dir, "config.toml");
    writeContainerCodexConfig(path, false);
    expect(readFileSync(path, "utf8")).toBe(OFF_STATE_CONFIG_TOML);
  });

  it("keeps the resolved setting visible in the run-level log line", () => {
    expect(codexFastRunLog(true)).toBe("[orchestrator] run fast=on");
    expect(codexFastRunLog(false)).toBe("[orchestrator] run fast=off");
  });
});
