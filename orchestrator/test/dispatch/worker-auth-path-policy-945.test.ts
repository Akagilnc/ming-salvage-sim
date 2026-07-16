/**
 * #945 — single-slice mountAuth ∪ family provisionFamilyWorkerAuth → one seam.
 *
 * Shared provision core + injectable path-policy:
 *   - family: per-run mkdtemp under ~/.sc-orchestrator + rolePrefix;
 *     missing host codex ⇒ codexAuthDir undefined
 *   - slice: stable per-issue buildAuthPaths; missing host auth still
 *     leaves the codex dir (always-mount config + AGENTS)
 *
 * Credential steps (copy / config / AGENTS / grok / agy / claude) must not
 * remain inlined in two bodies.
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
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import { CONTAINER_CODEX_CONFIG_TOML } from "../../src/containerCodexConfig.js";
import {
  CODEX_HOME_AGENTS_FILENAME,
  provisionFamilyWorkerAuth,
  provisionWorkerAuth,
  RealBackend,
} from "../../src/realBackend.js";

const here = dirname(fileURLToPath(import.meta.url));
const promptsDir = join(here, "..", "..", "prompts");
const soulsDir = join(here, "..", "..", "image", "souls");

let tempRoots: string[] = [];
function mkTemp(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tempRoots.push(d);
  return d;
}
afterEach(() => {
  for (const d of tempRoots) rmSync(d, { recursive: true, force: true });
  tempRoots = [];
});

function writeHomeEnv(home: string): string {
  const path = join(home, "container-home-CLAUDE.md");
  writeFileSync(path, "# container home env body for #945\n", "utf8");
  return path;
}

function seedFullHostAuth(home: string): void {
  mkdirSync(join(home, ".codex"), { recursive: true });
  writeFileSync(join(home, ".codex", "auth.json"), '{"tokens":{"codex":"c"}}\n');
  writeFileSync(join(home, ".codex", "AGENTS.md"), "# HOST OWNER AGENTS — must not leak\n");
  mkdirSync(join(home, ".grok"), { recursive: true });
  writeFileSync(join(home, ".grok", "auth.json"), '{"tokens":{"grok":"g"}}\n');
  writeFileSync(join(home, ".sc-agy-oauth-token"), "agy-oauth-secret\n");
  writeFileSync(join(home, ".sc-claude-token"), "claude-oauth-secret\n");
}

describe("#945 provisionWorkerAuth path-policy boundaries", () => {
  it("family policy: missing host codex ⇒ codexAuthDir undefined (no always-mount)", () => {
    const home = mkTemp("auth-945-fam-no-codex-");
    // grok/claude present; codex absent
    mkdirSync(join(home, ".grok"), { recursive: true });
    writeFileSync(join(home, ".grok", "auth.json"), '{"tokens":{"grok":"g"}}\n');
    writeFileSync(join(home, ".sc-claude-token"), "claude-oauth-secret\n");
    const homeEnvFile = writeHomeEnv(home);

    const auth = provisionWorkerAuth({
      home,
      homeEnvFile,
      pathPolicy: { kind: "family", rolePrefix: "cmr" },
    });

    expect(auth.codexAuthDir).toBeUndefined();
    expect(auth.grokAuthDir).toBeTruthy();
    expect(auth.claudeToken).toBe("claude-oauth-secret");
  });

  it("slice policy: missing host codex ⇒ still always-mounts stable issue codex dir with config", () => {
    const home = mkTemp("auth-945-slice-no-codex-");
    writeFileSync(join(home, ".sc-claude-token"), "claude-oauth-secret\n");
    const homeEnvFile = writeHomeEnv(home);
    const issueNumber = 945;

    const auth = provisionWorkerAuth({
      home,
      homeEnvFile,
      pathPolicy: { kind: "slice", issueNumber },
    });

    expect(auth.codexAuthDir).toBe(
      join(home, ".sc-orchestrator", `auth-${issueNumber}`),
    );
    expect(existsSync(join(auth.codexAuthDir!, "config.toml"))).toBe(true);
    expect(readFileSync(join(auth.codexAuthDir!, "config.toml"), "utf8")).toContain(
      CONTAINER_CODEX_CONFIG_TOML.trim().slice(0, 20),
    );
    expect(existsSync(join(auth.codexAuthDir!, "auth.json"))).toBe(false);
    expect(auth.claudeToken).toBe("claude-oauth-secret");
  });

  it("same host sources → both policies materialize equivalent credential contents", () => {
    const home = mkTemp("auth-945-both-full-");
    seedFullHostAuth(home);
    const homeEnvFile = writeHomeEnv(home);

    const family = provisionWorkerAuth({
      home,
      homeEnvFile,
      pathPolicy: { kind: "family", rolePrefix: "merger" },
    });
    const slice = provisionWorkerAuth({
      home,
      homeEnvFile,
      pathPolicy: { kind: "slice", issueNumber: 945 },
    });

    expect(family.claudeToken).toBe("claude-oauth-secret");
    expect(slice.claudeToken).toBe(family.claudeToken);

    expect(readFileSync(join(family.codexAuthDir!, "auth.json"), "utf8")).toContain("codex");
    expect(readFileSync(join(slice.codexAuthDir!, "auth.json"), "utf8")).toContain("codex");
    expect(readFileSync(join(family.codexAuthDir!, CODEX_HOME_AGENTS_FILENAME), "utf8")).toBe(
      readFileSync(homeEnvFile, "utf8"),
    );
    expect(readFileSync(join(slice.codexAuthDir!, CODEX_HOME_AGENTS_FILENAME), "utf8")).toBe(
      readFileSync(homeEnvFile, "utf8"),
    );
    expect(readFileSync(join(family.grokAuthDir!, "auth.json"), "utf8")).toContain("grok");
    expect(readFileSync(join(slice.grokAuthDir!, "auth.json"), "utf8")).toContain("grok");
    expect(existsSync(join(family.agyDir!, "antigravity-oauth-token"))).toBe(true);
    expect(existsSync(join(slice.agyDir!, "antigravity-oauth-token"))).toBe(true);

    // path-policy identity (not content)
    expect(family.codexAuthDir).toMatch(/merger-codex-auth-/);
    expect(slice.codexAuthDir).toBe(join(home, ".sc-orchestrator", "auth-945"));
    expect(family.agyDir).toMatch(/merger-agy-/);
    expect(slice.agyDir).toMatch(/slice-agy-945-/);
  });

  it("provisionFamilyWorkerAuth remains the family thin wrapper over the shared core", () => {
    const home = mkTemp("auth-945-fam-wrap-");
    seedFullHostAuth(home);
    const homeEnvFile = writeHomeEnv(home);

    const viaWrap = provisionFamilyWorkerAuth({
      home,
      rolePrefix: "ship",
      homeEnvFile,
      codexFast: true,
    });
    const viaCore = provisionWorkerAuth({
      home,
      homeEnvFile,
      codexFast: true,
      pathPolicy: { kind: "family", rolePrefix: "ship" },
    });

    expect(readFileSync(join(viaWrap.codexAuthDir!, "config.toml"), "utf8")).toContain(
      'service_tier = "fast"',
    );
    expect(readFileSync(join(viaCore.codexAuthDir!, "config.toml"), "utf8")).toContain(
      'service_tier = "fast"',
    );
    expect(viaWrap.claudeToken).toBe(viaCore.claudeToken);
  });
});

describe("#945 RealBackend.mountAuth consumes shared slice path-policy (no twin body)", () => {
  class MountProbe extends RealBackend {
    protected override cloneDirExists(): boolean {
      return true;
    }
    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      return "";
    }
    public mount(issueNumber: number) {
      return this.mountAuth(issueNumber);
    }
  }

  it("mountAuth preserves stable always-mount path + credentials via shared core", () => {
    const home = mkTemp("auth-945-mount-");
    seedFullHostAuth(home);
    writeHomeEnv(home);
    // RealBackend resolves home env from soulsDir sibling; seed a real home env path
    // by writing into image/home is wrong — inject via opts.home only for auth paths.
    // provisionCodexHomeAgents needs resolveHomeEnvFile(); production uses soulsDir.
    // Write the default home env next to a temp souls layout if needed — use real soulsDir.
    const backend = new MountProbe({
      sourceRepo: "/tmp/source-945",
      remote: "https://github.com/owner/name.git",
      runKey: 945,
      repo: "owner/name",
      imageName: "img",
      promptsDir,
      soulsDir,
      home,
    });

    const auth = backend.mount(945);
    expect(auth.authDir).toBe(join(home, ".sc-orchestrator", "auth-945"));
    expect(readFileSync(join(auth.authDir, "auth.json"), "utf8")).toContain("codex");
    expect(auth.claudeToken).toBe("claude-oauth-secret");
    expect(auth.grokAuthDir).toBeTruthy();
    expect(auth.agyDir).toBeTruthy();
    expect(auth.providerAuth).toEqual({
      claude: true,
      grok: true,
      agy: true,
    });
  });
});
