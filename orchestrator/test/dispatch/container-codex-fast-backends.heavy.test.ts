import {
  execFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
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
  RealFamilyBackend,
  RealFamilyBackendOptions,
  RealBackend,
  RealBackendOptions,
  buildExplicitLandingLiveHooks,
  here,
  promptsDir,
  soulsDir,
  configToml,
  tempRoots,
  tempRoot,
  git,
  makeSourceRepo,
  makeHome,
  realBackendOptions,
  familyBackendOptions,
  ExposedRealBackend,
  ExposedRealFamilyBackend,
} from "./container-codex-fast-backends.shared.js";

afterEach(() => {
  for (const root of tempRoots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("#760 real backend Codex fast write-site consumption", () => {
  it.each([true, false])("RealBackend mountAuth writes service_tier for codexFast=%s", (codexFast) => {
    const home = makeHome();
    const backend = new ExposedRealBackend(realBackendOptions(makeSourceRepo(), home, codexFast));

    backend.mountAuthForTest(760);

    const config = configToml(join(home, ".sc-orchestrator", "auth-760"));
    expect(config.includes('service_tier = "fast"')).toBe(codexFast);
  });

  it.each([true, false])("RealFamilyBackend writes service_tier at all three family sites for codexFast=%s", (codexFast) => {
    const home = makeHome();
    const backend = new ExposedRealFamilyBackend(
      familyBackendOptions(makeSourceRepo(), home, tempRoot("codex-fast-760-ledger-"), codexFast),
    );
    const auths = [
      backend.mountMergerAuthForTest(),
      backend.mountCmrAuthForTest(),
      backend.mountShipAuthForTest(),
    ];

    for (const auth of auths) {
      expect(auth.codexAuthDir).toBeDefined();
      expect(configToml(auth.codexAuthDir!)).toContain(codexFast ? 'service_tier = "fast"' : 'approval_policy = "never"');
      rmSync(auth.codexAuthDir!, { recursive: true, force: true });
    }
  });

});
