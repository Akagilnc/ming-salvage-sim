/**
 * #913 — family auth mount ×3 DRY: single shared provision seam.
 *
 * Before: mountMergerAuth / mountCmrAuth / mountShipAuth each inlined the same
 * best-effort codex + grok + agy + claude token provision. After: one pure
 * `provisionFamilyWorkerAuth`; the three mount*Auth methods are thin wrappers.
 *
 * Seam under test: the pure helper (observable host-dir / token outputs) plus
 * the three family mount wrappers still projecting their prior public shapes.
 */

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../../src/family/realFamilyBackend.js";
import {
  CODEX_HOME_AGENTS_FILENAME,
  provisionFamilyWorkerAuth,
} from "../../../src/realBackend.js";
import { CONTAINER_CODEX_CONFIG_TOML } from "../../../src/containerCodexConfig.js";

const soulsDir = join(import.meta.dirname ?? ".", "..", "..", "..", "image", "souls");
const promptsDir = join(import.meta.dirname ?? ".", "..", "..", "..", "prompts");

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
  writeFileSync(path, "# container home env body for #913\n", "utf8");
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

describe("#913 provisionFamilyWorkerAuth — shared family auth core", () => {
  it("provisions codex + grok + agy + claude when all host sources are present", () => {
    const home = mkTemp("fam-auth-913-full-");
    seedFullHostAuth(home);
    const homeEnvFile = writeHomeEnv(home);

    const auth = provisionFamilyWorkerAuth({
      home,
      rolePrefix: "cmr",
      homeEnvFile,
      codexFast: false,
    });

    expect(auth.codexAuthDir).toBeTruthy();
    expect(auth.grokAuthDir).toBeTruthy();
    expect(auth.agyDir).toBeTruthy();
    expect(auth.claudeToken).toBe("claude-oauth-secret");

    expect(readFileSync(join(auth.codexAuthDir!, "auth.json"), "utf8")).toContain("codex");
    expect(readFileSync(join(auth.codexAuthDir!, "config.toml"), "utf8")).toContain(
      CONTAINER_CODEX_CONFIG_TOML.trim(),
    );
    expect(readFileSync(join(auth.codexAuthDir!, CODEX_HOME_AGENTS_FILENAME), "utf8")).toBe(
      readFileSync(homeEnvFile, "utf8"),
    );
    expect(readFileSync(join(auth.codexAuthDir!, CODEX_HOME_AGENTS_FILENAME), "utf8")).not.toMatch(
      /HOST OWNER/,
    );
    expect(readFileSync(join(auth.grokAuthDir!, "auth.json"), "utf8")).toContain("grok");
    expect(existsSync(join(auth.agyDir!, "antigravity-oauth-token"))).toBe(true);
    expect(auth.codexAuthDir).toMatch(/cmr-codex-auth-/);
    expect(auth.grokAuthDir).toMatch(/cmr-grok-auth-/);
  });

  it("threads codexFast into the minimal container config.toml", () => {
    const home = mkTemp("fam-auth-913-fast-");
    seedFullHostAuth(home);
    const homeEnvFile = writeHomeEnv(home);

    const fast = provisionFamilyWorkerAuth({
      home,
      rolePrefix: "ship",
      homeEnvFile,
      codexFast: true,
    });
    const slow = provisionFamilyWorkerAuth({
      home,
      rolePrefix: "ship",
      homeEnvFile,
      codexFast: false,
    });

    expect(readFileSync(join(fast.codexAuthDir!, "config.toml"), "utf8")).toContain(
      'service_tier = "fast"',
    );
    expect(readFileSync(join(slow.codexAuthDir!, "config.toml"), "utf8")).not.toContain(
      'service_tier = "fast"',
    );
  });

  it("empty $HOME degrades every field to undefined without throwing", () => {
    const home = mkTemp("fam-auth-913-empty-");
    const homeEnvFile = writeHomeEnv(home);

    let auth: ReturnType<typeof provisionFamilyWorkerAuth> | undefined;
    expect(() => {
      auth = provisionFamilyWorkerAuth({
        home,
        rolePrefix: "merger",
        homeEnvFile,
      });
    }).not.toThrow();

    expect(auth).toEqual({
      codexAuthDir: undefined,
      grokAuthDir: undefined,
      agyDir: undefined,
      claudeToken: undefined,
    });
  });

  it("blank .sc-claude-token normalizes to undefined (not empty string)", () => {
    const home = mkTemp("fam-auth-913-blank-claude-");
    writeFileSync(join(home, ".sc-claude-token"), "   \n");
    const homeEnvFile = writeHomeEnv(home);

    const auth = provisionFamilyWorkerAuth({
      home,
      rolePrefix: "merger",
      homeEnvFile,
    });
    expect(auth.claudeToken).toBeUndefined();
  });

  it("reclaims half-built codex temp dir when auth.json copy fails", () => {
    const home = mkTemp("fam-auth-913-half-codex-");
    // .codex exists but no auth.json → copy throws after mkdtemp.
    mkdirSync(join(home, ".codex"), { recursive: true });
    const homeEnvFile = writeHomeEnv(home);
    const root = join(home, ".sc-orchestrator");

    const auth = provisionFamilyWorkerAuth({
      home,
      rolePrefix: "cmr",
      homeEnvFile,
    });

    expect(auth.codexAuthDir).toBeUndefined();
    // No leaked cmr-codex-auth-* under .sc-orchestrator.
    if (existsSync(root)) {
      const leaked = readdirSync(root).filter((name) => name.startsWith("cmr-codex-auth-"));
      expect(leaked).toEqual([]);
    }
  });

  it("reclaims codex temp dir when AGENTS sidecar write fails after auth copy", () => {
    // O1 (#945 online review): mkdtemp+auth.json succeed, but missing homeEnvFile
    // makes provisionCodexHomeAgents throw — must not leave cmr-codex-auth-*.
    const home = mkTemp("fam-auth-913-sidecar-fail-");
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "auth.json"), '{"tokens":{"codex":"c"}}\n');
    const root = join(home, ".sc-orchestrator");
    const missingHomeEnv = join(home, "missing-container-home-CLAUDE.md");

    const auth = provisionFamilyWorkerAuth({
      home,
      rolePrefix: "cmr",
      homeEnvFile: missingHomeEnv,
    });

    expect(auth.codexAuthDir).toBeUndefined();
    if (existsSync(root)) {
      const leaked = readdirSync(root).filter((name) => name.startsWith("cmr-codex-auth-"));
      expect(leaked).toEqual([]);
    }
  });
});

describe("#913 family mount*Auth wrappers share the core (public shapes)", () => {
  class Exposed extends RealFamilyBackend {
    public merger() {
      return this.mountMergerAuth();
    }
    public cmr() {
      return this.mountCmrAuth();
    }
    public ship() {
      return this.mountShipAuth();
    }
  }

  function familyOpts(home: string): RealFamilyBackendOptions {
    return {
      workingRepo: mkTemp("fam-auth-913-repo-"),
      familyBase: "family/913-base",
      ledgerDir: mkTemp("fam-auth-913-ledger-"),
      repo: "Akagilnc/ming-salvage-sim",
      base: "main",
      promptsDir,
      soulsDir,
      imageName: "img",
      home,
      homeEnvFile: writeHomeEnv(home),
    };
  }

  it("merger / cmr / ship all surface the same core credentials from one provision path", () => {
    const home = mkTemp("fam-auth-913-wrap-");
    seedFullHostAuth(home);
    const be = new Exposed(familyOpts(home));

    const merger = be.merger();
    const cmr = be.cmr();
    const ship = be.ship();

    for (const [label, auth] of [
      ["merger", merger],
      ["cmr", cmr],
      ["ship", ship],
    ] as const) {
      expect(auth.codexAuthDir, label).toBeTruthy();
      expect(auth.grokAuthDir, label).toBeTruthy();
      expect(auth.agyDir, label).toBeTruthy();
      expect(auth.claudeToken, label).toBe("claude-oauth-secret");
      expect(
        readFileSync(join(auth.codexAuthDir!, "auth.json"), "utf8"),
        label,
      ).toContain("codex");
      expect(
        readFileSync(join(auth.codexAuthDir!, "config.toml"), "utf8"),
        label,
      ).toContain('sandbox_mode = "danger-full-access"');
    }

    // Role-specific temp-dir prefixes retained (cleanup / concurrency identity).
    expect(merger.codexAuthDir).toMatch(/merger-codex-auth-/);
    expect(cmr.codexAuthDir).toMatch(/cmr-codex-auth-/);
    expect(ship.codexAuthDir).toMatch(/ship-codex-auth-/);

    // cmr + ship keep ghToken + providerAuth; merger does not invent them.
    expect("ghToken" in merger).toBe(false);
    expect("providerAuth" in merger).toBe(false);
    expect(cmr.providerAuth).toEqual({ claude: true, grok: true, agy: true });
    expect(ship.providerAuth).toEqual({ claude: true, grok: true, agy: true });
  });
});

// F7: structural greps deleted. Behavioral coverage lives above (pure
// provisionFamilyWorkerAuth + mount*Auth public shapes). Keep one adjacent
// pin: family path must not re-inline writeContainerCodexConfig (shared seam
// in realBackend owns it).
describe("#913 structural pin — family path does not re-inline codex config write", () => {
  it("realFamilyBackend has 0 writeContainerCodexConfig call sites", () => {
    const familySrc = readFileSync(
      join(import.meta.dirname ?? ".", "..", "..", "..", "src", "family", "realFamilyBackend.ts"),
      "utf8",
    );
    expect(familySrc.match(/writeContainerCodexConfig\s*\(/g) ?? []).toHaveLength(0);
  });
});
