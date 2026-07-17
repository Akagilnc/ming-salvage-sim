/**
 * #964 — mid-run grok auth death → typed failure; no headless device-auth wait.
 *
 * Seams under test (real entry, not internals):
 *   1. grokAgent buildPrintCommand — headless-only CLI shape (never interactive login form)
 *   2. Containerfile grok pin — fail-fast non-interactive auth CLI (0.2.102+)
 *      (canonical pin assert; Containerfile string-match only — live CLI probe not required)
 *   3. runMergerAgent / resolveMergeConflict / mergeChild — Sandcastle AgentError becomes
 *      Action-typed failure (structured non-resolve → conflicted + reason), never uncaught
 *      FiberFailure
 *   4. public ABI — no new cause token like auth_expired
 *   5. route-smoke bare-ping shape — startup auth probe not rewritten
 *
 * Authority: #964 AC + voided owner comment (native fail-fast only; no log parse /
 * monitor kill / run fuse / auth_expired public cause).
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import { MAX_DISPATCH_ATTEMPTS } from "../../src/dispatchRetry.js";
import { buildExplicitLandingLiveHooks } from "../../src/family/landing.js";
import { mergeChild } from "../../src/family/merger.js";
import {
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../src/family/realFamilyBackend.js";
import type {
  ConflictResolveRequest,
  MergeRequest,
  MergeResult,
} from "../../src/family/types.js";
import { grokAgent } from "../../src/grokAgent.js";
import { PUBLIC_FAILED_CAUSES } from "../../src/publicResult.js";
import { barePingArgv } from "../../src/realBackend.js";
import { isSandcastleAgentError } from "../../src/sandcastleAgentError.js";

const here = dirname(fileURLToPath(import.meta.url));
const orchestratorRoot = join(here, "..", "..");
const promptsDir = join(orchestratorRoot, "prompts");
const soulsDir = join(orchestratorRoot, "image", "souls");

const tmpDirs: string[] = [];
function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(d);
  return d;
}
afterEach(() => {
  for (const d of tmpDirs) rmSync(d, { recursive: true, force: true });
  tmpDirs.length = 0;
});

function makeRepo(): string {
  const repo = mkDir("964-merger-repo-");
  execFileSync("git", ["init", "-q"], { cwd: repo });
  execFileSync("git", ["config", "user.email", "t@t"], { cwd: repo });
  execFileSync("git", ["config", "user.name", "t"], { cwd: repo });
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "init"], {
    cwd: repo,
  });
  return repo;
}

function baseOpts(repo: string): RealFamilyBackendOptions {
  return {
    workingRepo: repo,
    familyBase: "family/964-base",
    ledgerDir: mkDir("964-ledger-"),
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir,
    soulsDir,
    imageName: "img",
  };
}

/** FiberFailure-shaped AgentError as observed when Sandcastle wraps sc.run. */
function fiberAgentError(message: string): Error {
  const agent = Object.assign(new Error(message), {
    name: "AgentError",
    _tag: "AgentError",
  });
  return Object.assign(
    new Error(`${message} (after ${MAX_DISPATCH_ATTEMPTS} dispatch attempts)`),
    {
      name: "(FiberFailure) AgentError",
      cause: agent,
    },
  );
}

class AgentErrorSandboxBackend extends RealFamilyBackend {
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

  public run(req: ConflictResolveRequest) {
    return this.runMergerAgent(req);
  }

  protected override async runAgentSandbox(): Promise<never> {
    throw Object.assign(
      new Error(
        "grok exited with code 1:\n\nError: Not signed in. To authenticate without a browser, run:\n  grok login --device-code",
      ),
      { name: "AgentError", _tag: "AgentError" },
    );
  }

  protected override mountMergerAuth() {
    // Pass missing-auth preflight so we reach sc.run (mid-run expiry, not absent mount).
    return {
      claudeToken: "tok",
      grokAuthDir: mkDir("964-grok-auth-"),
    };
  }

  protected override sh(file: string, args: string[]): string {
    if (file === "git" && args[0] === "rev-parse") {
      if (args[1] === this.opts.familyBase) return "family-head";
      return "child-head";
    }
    return "";
  }

  protected override mergeInProgress(): boolean {
    return true;
  }

  protected override isAncestorOf(): boolean {
    return false;
  }

  protected override isMergeCommit(): boolean {
    return false;
  }
}

/** Deterministic merge already conflicted → mergeChild routes to resolveMergeConflict. */
class MergeChildAgentErrorBackend extends AgentErrorSandboxBackend {
  override async mergeChildIntoFamilyBase(
    _child: MergeRequest,
  ): Promise<MergeResult> {
    return {
      familyHead: "family-head",
      familyHeadBefore: "family-head",
      childHead: "child-head",
      conflicted: true,
    };
  }
}

describe("#964 grok headless auth — native fail-fast surface", () => {
  it("grokAgent print command stays headless (prompt-file + streaming-json; no login subcommand)", () => {
    const cmd = grokAgent("grok-4.5").buildPrintCommand({
      prompt: "resolve the conflict",
      dangerouslySkipPermissions: true,
    });
    expect(cmd.command).toContain("grok ");
    expect(cmd.command).toContain("--prompt-file /dev/stdin");
    expect(cmd.command).toContain("--output-format streaming-json");
    expect(cmd.command).toContain("--always-approve");
    expect(cmd.command).not.toMatch(/\blogin\b/);
    expect(cmd.command).not.toMatch(/--device-auth|--device-code/);
    expect(cmd.stdin).toBe("resolve the conflict");
  });

  it("pins container grok to a fail-fast non-interactive release (0.2.102+)", () => {
    // Canonical pin assert (#964 CR R1 N2/N4): string-match Containerfile only.
    // 0.2.93 headless empty-auth entered device-code wait (flight3); 0.2.102
    // fails with "Not signed in" immediately. Live CLI probe not required for AC.
    const containerfile = readFileSync(
      join(orchestratorRoot, "image", "Containerfile"),
      "utf8",
    );
    expect(containerfile).toMatch(
      /npm install -g @xai-official\/grok@0\.2\.102/,
    );
    expect(containerfile).toMatch(/grok --version \| grep -F "0\.2\.102"/);
    expect(containerfile).not.toMatch(/@xai-official\/grok@0\.2\.93/);
  });

  it("route-smoke bare-ping keeps the same headless shape (startup auth not rewritten)", () => {
    const built = barePingArgv(
      "grok",
      "grok-4.5",
      "Reply with exactly: nonce-964",
    );
    expect(built.file).toBe("grok");
    expect(built.args).toContain("--prompt-file");
    expect(built.args).toContain("/dev/stdin");
    expect(built.args).toContain("--always-approve");
    expect(built.args).not.toContain("-p");
    expect(built.input).toBe("Reply with exactly: nonce-964");
  });

  it("does not introduce an auth_expired (or other new) public failed cause", () => {
    expect(PUBLIC_FAILED_CAUSES).not.toContain("auth_expired");
    expect(PUBLIC_FAILED_CAUSES).not.toContain("auth_failed");
    expect(PUBLIC_FAILED_CAUSES).not.toContain("device_auth_failed");
  });
});

describe("#964 AgentError → Action typed failure (merger worker entry)", () => {
  it("isSandcastleAgentError recognizes FiberFailure-wrapped AgentError", () => {
    expect(
      isSandcastleAgentError(fiberAgentError("grok exited with code 1")),
    ).toBe(true);
    expect(isSandcastleAgentError(new Error("plain crash"))).toBe(false);
  });

  it("runMergerAgent maps AgentError to structured non-resolve (owning Action, no throw)", async () => {
    const be = new AgentErrorSandboxBackend(baseOpts(makeRepo()));
    const outcome = await be.run({
      childIssue: 964,
      childBranch: "feat/964",
    });
    expect(outcome.resolved).toBe(false);
    expect(outcome.reason).toMatch(/Not signed in|AgentError|invocation failed/i);
  });

  it("resolveMergeConflict turns AgentError into conflicted typed result with reason (no uncaught throw)", async () => {
    const be = new AgentErrorSandboxBackend(baseOpts(makeRepo()));
    const result = await be.resolveMergeConflict({
      childIssue: 964,
      childBranch: "feat/964",
    });
    expect(result.conflicted).toBe(true);
    expect(result.escalation).toBeUndefined();
    expect(result.familyHeadBefore).toBe("family-head");
    expect(result.childHead).toBe("child-head");
    // #964 S3: non-empty agent reason survives MergeResult for re-login ops.
    expect(result.reason).toMatch(/Not signed in|invocation failed/i);
  });

  it("mergeChild wires AgentError → Action-owned conflicted (no process throw)", async () => {
    // #964 S4: thinnest real entry above resolveMergeConflict (Action path).
    const be = new MergeChildAgentErrorBackend(baseOpts(makeRepo()));
    const result = await mergeChild(be, {
      childIssue: 964,
      childBranch: "feat/964",
    });
    expect(result.conflicted).toBe(true);
    expect(result.escalation).toBeUndefined();
    expect(result.conflictResolvedByLlm).toBeUndefined();
    expect(result.reason).toMatch(/Not signed in|invocation failed/i);
  });
});
