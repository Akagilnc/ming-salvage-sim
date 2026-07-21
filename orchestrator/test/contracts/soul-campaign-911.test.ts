/**
 * #911 — container home environment dual-mount behavior.
 *
 * Load-bearing seams only (code paths, not markdown inventory):
 *   - home Claude mount shape + live-mount into boxConfig
 *   - codex AGENTS.md provision replaces host body with container home env
 *   - family sandboxes / auth paths use the same dual-mount helpers
 *   - missing or non-file home env fails closed at construction
 *
 * Not covered here: soul/prompt prose anchors, project CLAUDE hygiene,
 * STEP_COMPLETE wording greps, on-disk inventory lists.
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

import { afterAll, afterEach, describe, expect, it } from "vitest";

import {
  RealBackend,
  SANDBOX_CODEX_DIR,
  SANDBOX_HOME_CLAUDE_MD,
  homeClaudeMount,
  homeEnvFileFromSoulsDir,
  provisionCodexHomeAgents,
  soulsMount,
} from "../../src/realBackend.js";
import {
  RealFamilyBackend,
  SANDBOX_AGY_DIR,
} from "../../src/family/realFamilyBackend.js";
import { buildExplicitLandingLiveHooks } from "../../src/family/landing.js";

const here = dirname(fileURLToPath(import.meta.url));
const imageDir = join(here, "..", "..", "image");
const soulsDir = join(imageDir, "souls");
const homeEnvFile = join(imageDir, "home", "CLAUDE.md");
const promptsDir = join(here, "..", "..", "prompts");

const tempHomes: string[] = [];
function cleanup(): void {
  while (tempHomes.length > 0) {
    const home = tempHomes.pop();
    if (home !== undefined) rmSync(home, { recursive: true, force: true });
  }
}
afterEach(cleanup);
afterAll(cleanup);

describe("#911 container home environment dual-mount", () => {
  it("homeEnvFileFromSoulsDir resolves sibling image/home/CLAUDE.md", () => {
    expect(homeEnvFileFromSoulsDir(soulsDir)).toBe(homeEnvFile);
  });

  it("homeClaudeMount is readonly at /home/agent/.claude/CLAUDE.md", () => {
    expect(homeClaudeMount(homeEnvFile)).toEqual({
      hostPath: homeEnvFile,
      sandboxPath: SANDBOX_HOME_CLAUDE_MD,
      readonly: true,
    });
    expect(SANDBOX_HOME_CLAUDE_MD).toBe("/home/agent/.claude/CLAUDE.md");
  });

  it("provisionCodexHomeAgents writes AGENTS.md into the per-issue auth dir", () => {
    const authDir = mkdtempSync(join(tmpdir(), "codex-auth-911-"));
    tempHomes.push(authDir);
    provisionCodexHomeAgents(authDir, homeEnvFile);
    const agents = join(authDir, "AGENTS.md");
    expect(existsSync(agents)).toBe(true);
    expect(readFileSync(agents, "utf8")).toBe(readFileSync(homeEnvFile, "utf8"));
  });

  class StubBackend extends RealBackend {
    protected override cloneDirExists(): boolean {
      return true;
    }
    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
        return ".git";
      }
      return "";
    }
    public config(spec: {
      role: "coder";
      soul: "coder";
      model?: string;
    }): {
      mounts: ReadonlyArray<{ hostPath: string; sandboxPath: string; readonly?: boolean }>;
    } {
      return this.boxConfig(
        { authDir: "/tmp/auth-911", claudeToken: "tok", ghToken: "gho_test" },
        spec,
        911,
      );
    }
    public mount(issueNumber: number) {
      return this.mountAuth(issueNumber);
    }
  }

  function makeBackend(home: string): StubBackend {
    return new StubBackend({
      sourceRepo: "/tmp/source",
      remote: "https://github.com/owner/name.git",
      runKey: 911,
      repo: "owner/name",
      imageName: "ming-orchestrator-coder:latest",
      promptsDir,
      soulsDir,
      home,
    });
  }

  it("boxConfig live-mounts home CLAUDE.md (same freshness discipline as souls)", () => {
    const home = mkdtempSync(join(tmpdir(), "rb-home-911-"));
    tempHomes.push(home);
    const cfg = makeBackend(home).config({ role: "coder", soul: "coder" });
    expect(cfg.mounts).toContainEqual(homeClaudeMount(homeEnvFile));
    expect(cfg.mounts).toContainEqual(soulsMount(soulsDir));
  });

  it("mountAuth replaces AGENTS.md in the codex auth dir with the container home body", () => {
    const home = mkdtempSync(join(tmpdir(), "rb-home-911-auth-"));
    tempHomes.push(home);
    // Simulate a host AGENTS.md that must NOT leak into the worker.
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "AGENTS.md"), "# HOST OWNER AGENTS — must be replaced\n");
    writeFileSync(join(home, ".codex", "auth.json"), '{"tokens":{}}\n');

    const { authDir } = makeBackend(home).mount(911);
    expect(authDir.startsWith(join(home, ".sc-orchestrator"))).toBe(true);
    expect(existsSync(join(authDir, "AGENTS.md"))).toBe(true);
    expect(readFileSync(join(authDir, "AGENTS.md"), "utf8")).toBe(
      readFileSync(homeEnvFile, "utf8"),
    );
    expect(readFileSync(join(authDir, "AGENTS.md"), "utf8")).not.toMatch(
      /HOST OWNER AGENTS/,
    );
    // Codex mount still points at the per-issue auth dir.
    const cfg = makeBackend(home).config({ role: "coder", soul: "coder" });
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_CODEX_DIR)).toBe(true);
  });
});

describe("#911 family dual-mount (RealFamilyBackend)", () => {
  class FamilyProbe extends RealFamilyBackend {
  resolveLandingLiveHooks(input: {
    prUrl: string;
    convergedHeadOid: string;
    familyBase: string;
  }) {
    return buildExplicitLandingLiveHooks({
      prUrl: input.prUrl,
      headOid: input.convergedHeadOid,
      remoteBranchName: input.familyBase,
    });
  }

    public mergerCfg() {
      return this.mergerSandboxConfig({});
    }
    public shipCfg() {
      return this.shipSandboxConfig({ claudeToken: "tok" });
    }
    public cmrCfg() {
      return this.cmrSandboxConfig(
        { claudeToken: "tok", codexAuthDir: "/tmp/cmr-codex-911" },
        { model: "gpt-5.6-sol", host: "codex" },
      );
    }
    public familyCoderCfg() {
      return this.familyCoderSandboxConfig(
        { claudeToken: "tok" },
        "sonnet",
        {},
        { path: "/tmp/outcome-911.json", sandboxPath: "/tmp/outcome.json" },
      );
    }
    public familyReviewLoopCfg() {
      return this.familyReviewLoopSandboxConfig(
        { claudeToken: "tok" },
        {
          id: "S3",
          kind: "verify",
          role: "verify",
          soul: "verify",
          host: "claude",
          session: "fresh",
          contextRetention: "clean",
          promptFile: "judge_station.md",
          maxIter: 1,
          model: "sonnet",
          toolchain: [],
        },
        {},
      );
    }
    public mountMerger() {
      return this.mountMergerAuth();
    }
    public mountCmr() {
      return this.mountCmrAuth();
    }
    public mountShip() {
      return this.mountShipAuth();
    }
  }

  function familyOpts(over: {
    home?: string;
    homeEnvFile?: string;
    workingRepo?: string;
    ledgerDir?: string;
  } = {}) {
    const home = over.home ?? mkdtempSync(join(tmpdir(), "fam-home-911-"));
    if (!over.home) tempHomes.push(home);
    const workingRepo = over.workingRepo ?? mkdtempSync(join(tmpdir(), "fam-repo-911-"));
    if (!over.workingRepo) tempHomes.push(workingRepo);
    const ledgerDir = over.ledgerDir ?? mkdtempSync(join(tmpdir(), "fam-ledger-911-"));
    if (!over.ledgerDir) tempHomes.push(ledgerDir);
    return {
      workingRepo,
      familyBase: "family/911-base",
      ledgerDir,
      repo: "owner/name",
      base: "main",
      promptsDir,
      soulsDir,
      imageName: "img",
      home,
      homeEnvFile: over.homeEnvFile,
    };
  }

  it("family merger + ship sandboxes live-mount home CLAUDE.md", () => {
    const be = new FamilyProbe(familyOpts());
    const expected = homeClaudeMount(homeEnvFile);
    expect(be.mergerCfg().mounts).toContainEqual(expected);
    expect(be.shipCfg().mounts).toContainEqual(expected);
  });

  it("family cmr + coder-fix + review-loop sandboxes live-mount home CLAUDE.md", () => {
    const be = new FamilyProbe(familyOpts());
    const expected = homeClaudeMount(homeEnvFile);
    expect(be.cmrCfg().mounts).toContainEqual(expected);
    expect(be.familyCoderCfg().mounts).toContainEqual(expected);
    expect(be.familyReviewLoopCfg().mounts).toContainEqual(expected);
  });

  it("family mountMergerAuth writes container AGENTS.md into the codex auth dir", () => {
    const home = mkdtempSync(join(tmpdir(), "fam-auth-911-"));
    tempHomes.push(home);
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "auth.json"), '{"tokens":{}}\n');
    writeFileSync(join(home, ".codex", "AGENTS.md"), "# HOST OWNER — must be replaced\n");

    const be = new FamilyProbe(familyOpts({ home }));
    const auth = be.mountMerger();
    expect(auth.codexAuthDir).toBeTruthy();
    const agents = join(auth.codexAuthDir as string, "AGENTS.md");
    expect(existsSync(agents)).toBe(true);
    expect(readFileSync(agents, "utf8")).toBe(readFileSync(homeEnvFile, "utf8"));
    expect(readFileSync(agents, "utf8")).not.toMatch(/HOST OWNER/);
  });

  it("family mountCmrAuth + mountShipAuth write container AGENTS.md into codex auth dirs", () => {
    const home = mkdtempSync(join(tmpdir(), "fam-auth-911-cmr-ship-"));
    tempHomes.push(home);
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "auth.json"), '{"tokens":{}}\n');
    writeFileSync(join(home, ".codex", "AGENTS.md"), "# HOST OWNER — must be replaced\n");

    const be = new FamilyProbe(familyOpts({ home }));
    const expectedBody = readFileSync(homeEnvFile, "utf8");
    for (const [label, auth] of [
      ["cmr", be.mountCmr()],
      ["ship", be.mountShip()],
    ] as const) {
      expect(auth.codexAuthDir, label).toBeTruthy();
      const agents = join(auth.codexAuthDir as string, "AGENTS.md");
      expect(existsSync(agents), label).toBe(true);
      expect(readFileSync(agents, "utf8"), label).toBe(expectedBody);
      expect(readFileSync(agents, "utf8"), label).not.toMatch(/HOST OWNER/);
    }
  });

  it("missing home env file fails loud at RealFamilyBackend construction", () => {
    expect(
      () =>
        new FamilyProbe(
          familyOpts({ homeEnvFile: join(tmpdir(), "no-such-home-env-911-CLAUDE.md") }),
        ),
    ).toThrow(/home env file missing/);
  });

  it("homeEnvFile that is a directory fails construction (fail-closed dual-mount)", () => {
    const dirAsHomeEnv = mkdtempSync(join(tmpdir(), "home-env-dir-911-"));
    expect(
      () => new FamilyProbe(familyOpts({ homeEnvFile: dirAsHomeEnv })),
    ).toThrow(/home env file missing/);
  });

  it("mountShipAuth + ship sandbox include agy OAuth mount (reuse CMR seam)", () => {
    const home = mkdtempSync(join(tmpdir(), "fam-agy-ship-"));
    tempHomes.push(home);
    mkdirSync(join(home, ".codex"), { recursive: true });
    writeFileSync(join(home, ".codex", "auth.json"), '{"tokens":{}}\n');
    writeFileSync(join(home, ".sc-agy-oauth-token"), "agy-token-xyz\n");
    writeFileSync(join(home, ".sc-claude-token"), "claude-tok\n");

    class AgyShipProbe extends FamilyProbe {
      public shipCfgFor(auth: ReturnType<FamilyProbe["mountShip"]>) {
        return this.shipSandboxConfig(auth);
      }
    }
    const be = new AgyShipProbe(familyOpts({ home }));
    const auth = be.mountShip();
    expect(auth.agyDir).toBeTruthy();
    expect(existsSync(join(auth.agyDir as string, "antigravity-oauth-token"))).toBe(
      true,
    );
    const cfg = be.shipCfgFor(auth);
    expect(cfg.mounts.some((m) => m.sandboxPath === SANDBOX_AGY_DIR)).toBe(true);
    const agyMount = cfg.mounts.find((m) => m.sandboxPath === SANDBOX_AGY_DIR);
    expect(agyMount?.hostPath).toBe(auth.agyDir);
    expect(agyMount?.readonly).not.toBe(true);
  });
});
