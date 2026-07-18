import { execFileSync } from "node:child_process";

import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import * as sc from "@ai-hero/sandcastle";

import { discoverSubprojects } from "../../../src/familyDriver.js";

import {
  MERGER_SOUL,
  cmrOutcomeFromResult,
  mergerOutcomeFromResult,
  type MergerAuth,
  parseCmrOutcome,
  REFERENCED_FAMILY_PROMPT_FILES,
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../../src/family/realFamilyBackend.js";

import { familyEscalationState } from "../../../src/family/ledger.js";

import { MAX_DISPATCH_ATTEMPTS } from "../../../src/dispatchRetry.js";

import {
  SANDBOX_SKILLS_DIR,
  SANDBOX_SOUL_ENV,
  soulsMount,
} from "../../../src/realBackend.js";

import type {
  ConflictResolveRequest,
  FamilyVerifyRequest,
  IntegratedCmrRequest,
  IntegratedCmrResult,
} from "../../../src/family/types.js";

import { DEFAULT_IMAGE_TAG, resolveImageTag } from "../../../src/familyDriver.js";

import { PROVISION_SUBPROCESS_TIMEOUT_MS } from "../../../src/provisionNodeModules.js";

import type { WorkerSpec } from "../../../src/types.js";

import * as telemetry from "../../../src/telemetry.js";

import { buildExplicitLandingLiveHooks } from "../../../src/family/landing.js";

const here = dirname(fileURLToPath(import.meta.url));

const realPromptsDir = join(here, "..", "..", "..", "prompts");

const realSoulsDir = join(here, "..", "..", "..", "image", "souls");

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
}

function makeRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "rfb-"));
  git(dir, "init", "-q");
  git(dir, "config", "user.email", "t@t.t");
  git(dir, "config", "user.name", "t");
  git(dir, "config", "commit.gpgsign", "false");
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: dir });
  return dir;
}

function commitFile(repo: string, file: string, content: string): string {
  execFileSync("bash", ["-c", `printf '%s' '${content}' > '${join(repo, file)}'`]);
  git(repo, "add", file);
  execFileSync("git", ["commit", "-q", "-m", `add ${file}`], { cwd: repo });
  return git(repo, "rev-parse", "HEAD");
}

const tempState = { repos: [] as string[], ledgerDirs: [] as string[] };

function trackTempDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempState.ledgerDirs.push(dir);
  return dir;
}

function trackRepo(): string {
  const r = makeRepo();
  tempState.repos.push(r);
  return r;
}

function opts(workingRepo: string, over: Partial<RealFamilyBackendOptions> = {}): RealFamilyBackendOptions {
  const ledgerDir = mkdtempSync(join(tmpdir(), "rfb-ledger-"));
  tempState.ledgerDirs.push(ledgerDir);
  return {
    workingRepo,
    familyBase: "family/293-base",
    ledgerDir,
    repo: "Akagilnc/ming-salvage-sim",
    base: "main",
    promptsDir: realPromptsDir,
    soulsDir: realSoulsDir,
    imageName: "img",
    ...over,
  };
}

class FakeSeamsBackend extends RealFamilyBackend {
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

  mergerOutcome: ReturnType<typeof mergerOutcomeFromResult> = { resolved: true };
  mergerCalls: ConflictResolveRequest[] = [];
  verifyOutcome: "green" | "red" = "green";
  verifyCalls: FamilyVerifyRequest[] = [];
  cmrResult: IntegratedCmrResult = { converged: true, successfulLegs: ["opus", "gpt-5.6-sol", "agy"] };
  cmrCalls: IntegratedCmrRequest[] = [];
  shCalls: Array<{ file: string; args: string[] }> = [];
  prViewResponse: unknown = {
    number: 777,
    url: "https://github.com/Akagilnc/ming-salvage-sim/pull/777",
    baseRefName: "main",
    headRefName: "family/293-base",
    headRefOid: " pr-head-1 ",
    headRepositoryOwner: { login: "Akagilnc" },
    state: "OPEN",
    mergeStateStatus: "CLEAN",
  };
  prListResponse: unknown = [];
  mergeInProgressFake = false;
  // STATEFUL fake of the family-base ref so the resolve postcondition (the family
  // base ref moved past familyHeadBefore + child is its ancestor) is exercised
  // realistically. `rev-parse <familyBase>` returns familyBaseHeadFake; running the
  // merger ADVANCES it to resolvedHeadFake (a landed merge moves the family base
  // ref). The default models a clean LANDED resolve.
  familyBaseHeadFake = "base-head"; // rev-parse <familyBase> — current value (mutated by the merger)
  resolvedHeadFake = "resolved-head"; // what the family base ref advances to on a landed resolve
  childHeadFake = "child-head"; // rev-parse <childBranch>
  childLandedFake = true; // isAncestorOf(childHead, familyBase ref)
  mergerLandsOnFamilyBase = true; // does running the merger advance the family base ref?

  protected override async runMergerAgent(req: ConflictResolveRequest) {
    this.mergerCalls.push(req);
    // A real landed resolve advances the family base ref; a misbehaving agent that
    // aborted/reset (mergerLandsOnFamilyBase=false) leaves it unmoved.
    if (this.mergerOutcome.resolved && this.mergerLandsOnFamilyBase) {
      this.familyBaseHeadFake = this.resolvedHeadFake;
    }
    return this.mergerOutcome;
  }
  protected override async runVerifyCommands(req: FamilyVerifyRequest): Promise<void> {
    this.verifyCalls.push(req);
    if (this.verifyOutcome === "red") {
      throw new Error("Command failed: npx vitest run\n 3 failed | 507 passed");
    }
  }
  protected override async runCmr(req: IntegratedCmrRequest) {
    this.cmrCalls.push(req);
    return this.cmrResult;
  }
  protected override mergeInProgress(_repo: string): boolean {
    return this.mergeInProgressFake;
  }
  protected override isAncestorOf(_ancestor: string, _descendant: string, _repo: string): boolean {
    return this.childLandedFake;
  }
  protected override isMergeCommit(_commit: string, _repo: string): boolean {
    return this.childLandedFake;
  }
  // Intercept the git/gh/npx subprocess seam so no real command runs.
  protected override sh(file: string, args: string[], _cwd?: string): string {
    this.shCalls.push({ file, args });
    if (file === "git" && args[0] === "rev-parse") {
      // rev-parse <familyBase> → the (stateful) family base ref; rev-parse HEAD →
      // wherever HEAD is; rev-parse <childBranch> → the child head. The resolve
      // postcondition reads the FAMILY BASE REF (codex R3), so familyHeadBefore and
      // the post-resolve familyHead both come from familyBaseHeadFake — which the
      // merger advances only on a landed resolve.
      if (args[1] === this.familyBase) return this.familyBaseHeadFake;
      if (args[1] === "HEAD") return this.resolvedHeadFake;
      return this.childHeadFake;
    }
    if (file === "gh" && args[0] === "pr" && args[1] === "create") {
      return "https://github.com/Akagilnc/ming-salvage-sim/pull/777";
    }
    if (file === "gh" && args[0] === "pr" && args[1] === "view") {
      return JSON.stringify({
        number: 777,
        url: "https://github.com/Akagilnc/ming-salvage-sim/pull/777",
        mergeStateStatus: "CLEAN",
        ...(this.prViewResponse as Record<string, unknown>),
      });
    }
    if (file === "gh" && args[0] === "pr" && args[1] === "list") {
      return JSON.stringify(this.prListResponse);
    }
    return "";
  }

  // the configured family base (RealFamilyBackend.opts is protected → accessible).
  private get familyBase(): string {
    return this.opts.familyBase;
  }

  // Expose the protected sandbox-config seam so the merger soul injection +
  // skills-mount path are unit-testable without a real container.
  public sandboxConfig(auth: any = {}) {
    return this.mergerSandboxConfig(auth);
  }

  // Expose for family-coder souls mount assertion (#372).
  public familyCoderConfig() {
    return this.familyCoderSandboxConfig(
      { codexAuthDir: "/tmp/codex", claudeToken: "tok" } as any,
      "sonnet",
      {} as any,
      { path: "/tmp/land.json", sandboxPath: ".land.json" },
    );
  }

}

export {
  execFileSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
  tmpdir,
  dirname,
  join,
  fileURLToPath,
  afterEach,
  describe,
  expect,
  it,
  vi,
  sc,
  discoverSubprojects,
  MERGER_SOUL,
  cmrOutcomeFromResult,
  mergerOutcomeFromResult,
  MergerAuth,
  parseCmrOutcome,
  REFERENCED_FAMILY_PROMPT_FILES,
  RealFamilyBackend,
  RealFamilyBackendOptions,
  familyEscalationState,
  MAX_DISPATCH_ATTEMPTS,
  SANDBOX_SKILLS_DIR,
  SANDBOX_SOUL_ENV,
  soulsMount,
  ConflictResolveRequest,
  FamilyVerifyRequest,
  IntegratedCmrRequest,
  IntegratedCmrResult,
  DEFAULT_IMAGE_TAG,
  resolveImageTag,
  PROVISION_SUBPROCESS_TIMEOUT_MS,
  WorkerSpec,
  telemetry,
  buildExplicitLandingLiveHooks,
  here,
  realPromptsDir,
  realSoulsDir,
  git,
  makeRepo,
  commitFile,
  tempState,
  trackTempDir,
  trackRepo,
  opts,
  FakeSeamsBackend,
};
