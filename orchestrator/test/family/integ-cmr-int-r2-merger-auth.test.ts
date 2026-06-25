/**
 * integ-cmr int-r2 — Finding A-1 (P1): the merger worker's sandbox was missing the
 * claude OAuth token + a preflight.
 *
 * `runMergerAgent` starts a TOP-LEVEL claude worker (`sc.claudeCode(MERGER_MODEL)`)
 * under the `resolving-merge-conflicts` skill, but `mergerSandboxConfig()` injected
 * ONLY the soul env — no CLAUDE_CODE_OAUTH_TOKEN, no preflight (a stale comment even
 * claimed "auth is wired by #335/#336", which only wired cmr/ship). So a real merger
 * run would spin an UNAUTHENTICATED container that cannot start.
 *
 * This mirrors the cmr/ship workers' OWN-auth preflight (cmr-worker-335.test.ts /
 * ship-worker-336.test.ts): the merger is a claude worker, so its claude token is
 * load-bearing (NOT a degradable reviewer leg). Codex/gh are NOT needed (the merger
 * resolves + commits in place; it never pushes / opens a PR — the runner owns the
 * merge queue / ledger).
 *
 *   1. mountMergerAuth on an EMPTY $HOME ⇒ claudeToken undefined, no throw.
 *   2. mergerSandboxConfig injects CLAUDE_CODE_OAUTH_TOKEN when the token is present.
 *   3. runMergerAgent with NO claude token ⇒ structured unresolved (resolved:false,
 *      reason names the missing token), and NEVER spins the container.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  type MergerAuth,
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../src/family/realFamilyBackend.js";
import { SANDBOX_SOUL_ENV, SPAWNED_WORKER_ENV } from "../../src/realBackend.js";
import type { ConflictResolveRequest } from "../../src/family/types.js";

const here = join(import.meta.dirname ?? ".", "..", "..", "prompts");

let tmpDirs: string[] = [];
function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(d);
  return d;
}
function realRepo(): string {
  const repo = mkDir("merger-auth-repo-");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  return repo;
}
afterEach(() => {
  for (const d of tmpDirs) rmSync(d, { recursive: true, force: true });
  tmpDirs = [];
});

function baseOpts(over: Partial<RealFamilyBackendOptions> = {}): RealFamilyBackendOptions {
  return {
    workingRepo: realRepo(),
    familyBase: "family/293-base",
    ledgerDir: mkDir("merger-auth-ledger-"),
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: here,
    imageName: "img",
    ...over,
  };
}

// ─────────────── 1. mountMergerAuth — claude token best-effort ───────────────

describe("integ-cmr int-r2 A-1 — mountMergerAuth on an empty $HOME degrades, never throws", () => {
  class AuthBackend extends RealFamilyBackend {
    public auth(): MergerAuth {
      return this.mountMergerAuth();
    }
  }
  it("empty $HOME (no claude token) ⇒ claudeToken undefined, no throw", () => {
    const emptyHome = mkDir("merger-empty-home-");
    const be = new AuthBackend(baseOpts({ home: emptyHome }));
    let auth: MergerAuth | undefined;
    expect(() => {
      auth = be.auth();
    }).not.toThrow();
    expect(auth?.claudeToken).toBeUndefined();
  });
  // cmr int-r3 A: a present-but-EMPTY/blank token file must normalize to undefined
  // (so the preflight escalates) — NOT pass the `=== undefined` gate as "" and get
  // injected as CLAUDE_CODE_OAUTH_TOKEN="" (which defeats the gate). Mirrors readGhToken.
  it("present-but-empty .sc-claude-token ⇒ claudeToken undefined (not an empty string)", () => {
    const blankHome = mkDir("merger-blank-token-home-");
    writeFileSync(join(blankHome, ".sc-claude-token"), "   \n");
    const be = new AuthBackend(baseOpts({ home: blankHome }));
    expect(be.auth().claudeToken).toBeUndefined();
  });
});

// ─────────────── 2. mergerSandboxConfig — injects the claude token ───────────────

describe("integ-cmr int-r2 A-1 — mergerSandboxConfig wires CLAUDE_CODE_OAUTH_TOKEN", () => {
  class CfgBackend extends RealFamilyBackend {
    public cfg(auth: MergerAuth) {
      return this.mergerSandboxConfig(auth);
    }
  }
  it("injects CLAUDE_CODE_OAUTH_TOKEN (alongside the soul env) when the token is present", () => {
    const be = new CfgBackend(baseOpts());
    const cfg = be.cfg({ claudeToken: "merger-tok-xyz" });
    expect(cfg.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("merger-tok-xyz");
    expect(cfg.env[SANDBOX_SOUL_ENV]).toBe("merger");
  });
  it("omits the env var when the token is absent (the REQUIRE gate is the runMergerAgent preflight)", () => {
    const be = new CfgBackend(baseOpts());
    const cfg = be.cfg({});
    expect(cfg.env.CLAUDE_CODE_OAUTH_TOKEN).toBeUndefined();
    expect(cfg.env[SANDBOX_SOUL_ENV]).toBe("merger");
  });
  it("marks the merger container as an orchestrator-spawned, non-interactive session", () => {
    const be = new CfgBackend(baseOpts());
    const cfg = be.cfg({ claudeToken: "merger-tok-xyz" });
    expect(cfg.env.OPENCLAW_SESSION).toBe("1");
    expect(cfg.env.OPENCLAW_SESSION).toBe(SPAWNED_WORKER_ENV.OPENCLAW_SESSION);
  });
});

// ─────────────── 3. runMergerAgent — fail-closed on missing claude token ───────────────

describe("integ-cmr int-r2 A-1 — runMergerAgent fails-closed (structured) without a claude token", () => {
  /**
   * The merger is the container's TOP-LEVEL claude — a missing token means the
   * worker cannot start. runMergerAgent must return a STRUCTURED unresolved
   * (resolved:false + reason) and NEVER spin the container (mirrors the cmr/ship
   * worker preflight). The downstream `resolveMergeConflict` turns that into a
   * loud throw (never a phantom `merged`).
   */
  class NoClaudeMerger extends RealFamilyBackend {
    sandboxReached = false;
    public run(req: ConflictResolveRequest) {
      return this.runMergerAgent(req);
    }
    protected override mountMergerAuth(): MergerAuth {
      return {}; // claude token ABSENT
    }
    protected override mergerSandbox(): never {
      this.sandboxReached = true;
      throw new Error("mergerSandbox should not run when the worker has no auth");
    }
    // Stub the git seam so resolveMergeConflict's rev-parse pre/post reads don't hit
    // a real (non-existent) branch — the throw under test must come from the merger's
    // no-auth NON-RESOLVE, not from git.
    protected override sh(file: string, args: string[]): string {
      if (file === "git" && args[0] === "rev-parse") return "stub-sha";
      return "";
    }
    protected override mergeInProgress(): boolean {
      return false;
    }
  }

  it("no claude token ⇒ resolved:false with a token reason, container never spins", async () => {
    const be = new NoClaudeMerger(baseOpts());
    const outcome = await be.run({ childIssue: 99, childBranch: "feat/child-99" });
    expect(outcome.resolved).toBe(false);
    expect(outcome.reason ?? "").toMatch(/claude|token|CLAUDE_CODE_OAUTH_TOKEN|auth/i);
    expect(be.sandboxReached).toBe(false);
  });

  it("resolveMergeConflict surfaces the no-auth non-resolve as a loud throw (no phantom merged)", async () => {
    const be = new NoClaudeMerger(baseOpts());
    await expect(
      be.resolveMergeConflict({ childIssue: 99, childBranch: "feat/child-99" }),
    ).rejects.toThrow(/did not resolve|claude|token|auth/i);
    expect(be.sandboxReached).toBe(false);
  });
});
