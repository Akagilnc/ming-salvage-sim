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

  it("keeps codexFast consumed by the single #945 provisionWorkerAuth write site", () => {
    // #945: family + slice share one provisionWorkerAuth → one
    // writeContainerCodexConfig call. Consumers pass codexFast into the seam
    // (mountAuth: this.opts.codexFast; family: provisionFamilyWorkerAuth param).
    const realSrc = readFileSync(join(here, "..", "..", "src", "realBackend.ts"), "utf8");

    const realWriteCalls: string[] = [];
    for (const match of realSrc.matchAll(/writeContainerCodexConfig\s*\(/g)) {
      const openParen = match.index! + match[0].length - 1;
      let depth = 0;
      let closeParen = -1;
      for (let index = openParen; index < realSrc.length; index += 1) {
        if (realSrc[index] === "(") depth += 1;
        if (realSrc[index] === ")" && --depth === 0) {
          closeParen = index;
          break;
        }
      }
      if (closeParen >= 0) realWriteCalls.push(realSrc.slice(match.index!, closeParen + 1));
    }
    expect(realWriteCalls).toHaveLength(1);
    expect(realWriteCalls[0]).toMatch(/\bcodexFast\b/);
    // Thin consumers still inject codexFast into the shared core.
    expect(realSrc).toMatch(/pathPolicy:\s*\{\s*kind:\s*"slice"/);
    expect(realSrc).toMatch(/codexFast:\s*this\.opts\.codexFast/);
    expect(realSrc).toMatch(/function provisionFamilyWorkerAuth/);
    expect(realSrc).toMatch(/pathPolicy:\s*\{\s*kind:\s*"family"/);
  });
});
