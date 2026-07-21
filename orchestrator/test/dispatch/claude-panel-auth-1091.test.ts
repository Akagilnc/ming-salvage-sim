/**
 * #1091 — claude panel-leg auth: credentials dir when claude cmrReview leg present;
 * fail-closed when neither token nor credentials file is available.
 */
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  CLAUDE_CREDENTIALS_FILENAME,
  SANDBOX_CLAUDE_CREDENTIALS_FILE,
  appendClaudeAuthMount,
  assertClaudePanelLegAuth,
  provisionFamilyWorkerAuth,
} from "../../src/realBackend.js";

const tempRoots: string[] = [];
afterEach(() => {
  for (const root of tempRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

function mkHome(prefix: string): string {
  const home = mkdtempSync(join(tmpdir(), prefix));
  tempRoots.push(home);
  mkdirSync(join(home, ".sc-orchestrator"), { recursive: true, mode: 0o700 });
  writeFileSync(join(home, ".sc-home-env"), "", { mode: 0o600 });
  return home;
}

describe("#1091 claude panel-leg auth", () => {
  it("prepares claudeAuthDir with credentials when host file is present", () => {
    const home = mkHome("1091-claude-auth-");
    mkdirSync(join(home, ".claude"), { recursive: true, mode: 0o700 });
    writeFileSync(
      join(home, ".claude", CLAUDE_CREDENTIALS_FILENAME),
      JSON.stringify({ claudeAiOauth: { accessToken: "tok" } }),
      { mode: 0o600 },
    );
    writeFileSync(join(home, ".sc-claude-token"), "oauth-tok\n", { mode: 0o600 });

    const auth = provisionFamilyWorkerAuth({
      home,
      rolePrefix: "cmr",
      homeEnvFile: join(home, ".sc-home-env"),
    });
    expect(auth.claudeAuthDir).toBeTruthy();
    expect(auth.claudeAuthDir).toMatch(/cmr-claude-auth-/);
    const srcCreds = readFileSync(
      join(home, ".claude", CLAUDE_CREDENTIALS_FILENAME),
      "utf8",
    );
    const destCreds = readFileSync(
      join(auth.claudeAuthDir!, CLAUDE_CREDENTIALS_FILENAME),
      "utf8",
    );
    expect(destCreds).toBe(srcCreds);
    expect(auth.claudeToken).toBe("oauth-tok");

    const mounts: { hostPath: string; sandboxPath: string; readonly?: boolean }[] =
      [];
    appendClaudeAuthMount(mounts, auth.claudeAuthDir);
    expect(mounts).toEqual([
      {
        hostPath: join(auth.claudeAuthDir!, CLAUDE_CREDENTIALS_FILENAME),
        sandboxPath: SANDBOX_CLAUDE_CREDENTIALS_FILE,
        readonly: true,
      },
    ]);
    expect(existsSync(mounts[0]!.hostPath)).toBe(true);
  });

  it("assertClaudePanelLegAuth rejects claude legs with no token and no credentials dir", () => {
    const msg = assertClaudePanelLegAuth({
      reviewLegs: [
        { family: "claude" },
        { family: "grok" },
      ],
    });
    expect(msg).toMatch(/claude-family panel leg/i);
    expect(msg).toMatch(/credentials/i);
  });

  it("assertClaudePanelLegAuth accepts token-only or credentials-dir auth", () => {
    expect(
      assertClaudePanelLegAuth({
        reviewLegs: [{ family: "claude" }],
        claudeToken: "tok",
      }),
    ).toBeUndefined();
    expect(
      assertClaudePanelLegAuth({
        reviewLegs: [{ family: "claude" }],
        claudeAuthDir: "/tmp/cmr-claude-auth-xyz",
      }),
    ).toBeUndefined();
    expect(
      assertClaudePanelLegAuth({
        reviewLegs: [{ family: "grok" }],
      }),
    ).toBeUndefined();
  });
});
