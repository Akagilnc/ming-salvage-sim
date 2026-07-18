import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

// The commit-msg hook is baked into the worker image and wired via
// `git config --global core.hooksPath` (Containerfile). It tags every
// in-container commit's subject with the `sandcastle:` prefix so a family run's
// machine commits are framable (`git log --grep '^sandcastle:'`,
// orchestrator/CLAUDE.md). These tests exercise the script directly (no
// container) by running it on a temp commit-message file, the same way git
// invokes `commit-msg <path-to-COMMIT_EDITMSG>`.

const here = dirname(fileURLToPath(import.meta.url));
const HOOK = join(here, "..", "..", "image", "hooks", "commit-msg");

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "commit-msg-hook-"));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

/** Write a commit message file, run the hook on it, return the rewritten message. */
function runHook(message: string): string {
  const f = join(dir, "COMMIT_EDITMSG");
  writeFileSync(f, message);
  execFileSync("sh", [HOOK, f]);
  return readFileSync(f, "utf8");
}

describe("commit-msg hook — sandcastle: prefix", () => {
  it("is committed as an executable script", () => {
    // The image RUN chmod relies on it being shipped executable; a non-exec hook
    // is a silent no-op in-container.
    expect(statSync(HOOK).mode & 0o111).toBeGreaterThan(0);
  });

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
