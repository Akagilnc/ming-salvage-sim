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
import { RealFamilyBackend } from "../../src/family/realFamilyBackend.js";
import type { WorkerSpec, DispatchContext } from "../../src/types.js";

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

  it("assertClaudePanelLegAuth requires credentials-dir for claude legs (token alone insufficient)", () => {
    // Token-only no longer passes: claude-family judge workers scrub
    // CLAUDE_CODE_OAUTH_TOKEN from child processes (#1091 fix); the token
    // parameter itself was removed (#1090 cleanup), so absence of a
    // credentials dir is the only remaining gap condition.
    expect(
      assertClaudePanelLegAuth({
        reviewLegs: [{ family: "claude" }],
      }),
    ).toMatch(/credentials/i);
    // Credentials dir is the valid auth path for claude panel legs.
    expect(
      assertClaudePanelLegAuth({
        reviewLegs: [{ family: "claude" }],
        claudeAuthDir: "/tmp/cmr-claude-auth-xyz",
      }),
    ).toBeUndefined();
    // Non-claude legs are unaffected.
    expect(
      assertClaudePanelLegAuth({
        reviewLegs: [{ family: "grok" }],
      }),
    ).toBeUndefined();
  });

  it("familyReviewLoopSandboxConfig mounts claude credentials when claudeAuthDir is set", () => {
    const home = mkHome("1091-review-loop-claude-");
    // Create the claude auth dir + credentials file (ensureRegularFileForBindMount
    // requires the file to exist before docker bind-mount).
    const claudeAuthDir = join(home, "cmr-claude-auth-test");
    mkdirSync(claudeAuthDir, { recursive: true, mode: 0o700 });
    writeFileSync(
      join(claudeAuthDir, CLAUDE_CREDENTIALS_FILENAME),
      JSON.stringify({ claudeAiOauth: { accessToken: "tok" } }),
      { mode: 0o600 },
    );

    const soulsDir = join(home, "souls");
    mkdirSync(soulsDir, { recursive: true });

    // Bypass constructor validation — only the pure config method is under test.
    // Typed narrow interface so we never reach for `as any` — the repo's tests
    // exercise protected members via a typed cast on the minimal shape needed.
    type ExposedFamilyBackend = {
      opts: {
        workingRepo: string;
        familyBase: string;
        ledgerDir: string;
        repo: string;
        base: string;
        promptsDir: string;
        soulsDir: string;
        imageName: string;
        homeEnvFile: string;
      };
      familyReviewLoopSandboxConfig(
        auth: unknown,
        spec: WorkerSpec,
        ctx: DispatchContext,
      ): {
        imageName: string;
        env: Record<string, string>;
        mounts: ReadonlyArray<{
          hostPath: string;
          sandboxPath: string;
          readonly?: boolean;
        }>;
      };
    };
    const backend = Object.create(
      RealFamilyBackend.prototype,
    ) as unknown as ExposedFamilyBackend;
    backend.opts = {
      workingRepo: join(home, "repo"),
      familyBase: "family-base",
      ledgerDir: join(home, "ledger"),
      repo: "owner/repo",
      base: "main",
      promptsDir: join(home, "prompts"),
      soulsDir,
      imageName: "test-image",
      homeEnvFile: join(home, ".sc-home-env"),
    };

    const auth = {
      claudeAuthDir,
      claudeToken: "oauth-tok",
    };

    const spec = {
      id: "S9",
      kind: "verify",
      role: "verify",
      soul: "verify",
      model: "codex",
      host: "codex",
      session: "fresh",
      contextRetention: "clean",
      promptFile: "verify.md",
      maxIter: 1,
      toolchain: [],
    } as unknown as WorkerSpec;

    const ctx = { familyBase: "family-base" } as unknown as DispatchContext;

    const config = backend.familyReviewLoopSandboxConfig(auth, spec, ctx);

    expect(config.mounts).toContainEqual({
      hostPath: join(claudeAuthDir, CLAUDE_CREDENTIALS_FILENAME),
      sandboxPath: SANDBOX_CLAUDE_CREDENTIALS_FILE,
      readonly: true,
    });
  });
});
