/**
 * #962 — noSandbox helper isolates GIT_CONFIG_GLOBAL off the host.
 *
 * Seam: runScriptedStructuredOutput public harness (real sc.run + noSandbox).
 * Sandcastle's setup writes `git config --global` (safe.directory / user.*);
 * with noSandbox those land on whatever GIT_CONFIG_GLOBAL points at — must be
 * a per-run private file under the harness tmpdir, never host ~/.gitconfig.
 */

import { afterEach, describe, expect, it } from "vitest";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { z } from "zod";

import { runScriptedStructuredOutput } from "./scripted-sandcastle-run.js";

describe("#962 scripted noSandbox isolates GIT_CONFIG_GLOBAL", () => {
  const cleanups: string[] = [];
  afterEach(() => {
    while (cleanups.length > 0) {
      const dir = cleanups.pop();
      if (dir !== undefined) rmSync(dir, { recursive: true, force: true });
    }
  });

  it("writes global git config into the run-private file, not host ~/.gitconfig", async () => {
    const hostGitconfig = join(homedir(), ".gitconfig");
    const hostBefore = existsSync(hostGitconfig)
      ? readFileSync(hostGitconfig)
      : null;

    const { repo, result } = await runScriptedStructuredOutput({
      tag: "probe962",
      schema: z.object({ ok: z.literal(true) }),
      emissions: [{ body: JSON.stringify({ ok: true }) }],
      maxRetries: 0,
      sessionId: "sess-962-gitconfig-iso",
      cleanups,
    });

    expect(result.output).toEqual({ ok: true });

    // Owner-pinned path: join(repo, ".test-gitconfig") inside the run tmpdir.
    const privateGitconfig = join(repo, ".test-gitconfig");
    expect(existsSync(privateGitconfig)).toBe(true);
    const privateContents = readFileSync(privateGitconfig, "utf8");
    // Git writes INI sections; Sandcastle always --add safe.directory and
    // copies harness local user.* into the isolated global file.
    expect(privateContents).toMatch(/\[safe\]/);
    expect(privateContents).toMatch(/directory\s*=/);
    expect(privateContents).toMatch(/\[user\]/);
    expect(privateContents).toMatch(/name\s*=\s*t/);
    expect(privateContents).toMatch(/email\s*=\s*t@t\.t/);

    const hostAfter = existsSync(hostGitconfig)
      ? readFileSync(hostGitconfig)
      : null;
    expect(hostAfter).toEqual(hostBefore);
  });
});
