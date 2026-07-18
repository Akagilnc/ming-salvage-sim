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

  it("prepends `sandcastle: ` to a bare conventional-commit subject", () => {
    expect(runHook("feat(transit): #346 add fallback\n")).toBe(
      "sandcastle: feat(transit): #346 add fallback\n",
    );
  });

  it("is idempotent — an already-prefixed subject is left untouched", () => {
    const msg = "sandcastle: fix(ship): bump version\n";
    expect(runHook(msg)).toBe(msg);
  });

  it("puts `sandcastle:` FIRST, preserving an inner model prefix (claude:/codex:)", () => {
    expect(runHook("claude: feat: dedicated ship soul\n")).toBe(
      "sandcastle: claude: feat: dedicated ship soul\n",
    );
  });

  it("preserves the full multi-line body (only the subject is rewritten)", () => {
    const body =
      "feat: x\n\nF1: wrap cleanup in try/except\n\nCo-Authored-By: Someone <a@b.c>\n";
    expect(runHook(body)).toBe(
      "sandcastle: feat: x\n\nF1: wrap cleanup in try/except\n\nCo-Authored-By: Someone <a@b.c>\n",
    );
  });

  it("leaves an EMPTY message untouched so git can still abort the commit (#384 R2)", () => {
    // Prepending `sandcastle: ` to an empty message would make it non-empty and
    // defeat git's empty-message abort, creating a junk commit.
    expect(runHook("")).toBe("");
    expect(runHook("\n\n")).toBe("\n\n");
  });

  it("leaves a COMMENT-ONLY message untouched (git aborts it as empty)", () => {
    const commentOnly = "# Please enter the commit message for your changes.\n#\n";
    expect(runHook(commentOnly)).toBe(commentOnly);
  });

  it("prefixes the first CONTENT line, not a leading comment / blank line (#384 R3)", () => {
    // A leading comment or blank line must stay intact (git strips comments); the
    // prefix belongs on the actual subject below it, never on `head -n1` blindly.
    expect(runHook("# editor template comment\nfeat: real subject\n")).toBe(
      "# editor template comment\nsandcastle: feat: real subject\n",
    );
    expect(runHook("\nfeat: subject after blank\n")).toBe(
      "\nsandcastle: feat: subject after blank\n",
    );
  });
});
