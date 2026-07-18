import {
  describe,
  it,
  expect,
  beforeEach,
  afterEach,
  execFileSync,
  mkdtempSync,
  writeFileSync,
  readFileSync,
  rmSync,
  statSync,
  tmpdir,
  join,
  dirname,
  fileURLToPath,
  here,
  HOOK,
  hookState,
  runHook,
} from "./commit-message-hook.shared.js";

beforeEach(() => {
  hookState.dir = mkdtempSync(join(tmpdir(), "commit-msg-hook-"));
});
afterEach(() => {
  rmSync(hookState.dir, { recursive: true, force: true });
});

describe("commit-msg hook — sandcastle: prefix", () => {
  it("is committed as an executable script", () => {
    // The image RUN chmod relies on it being shipped executable; a non-exec hook
    // is a silent no-op in-container.
    expect(statSync(HOOK).mode & 0o111).toBeGreaterThan(0);
  });

});
