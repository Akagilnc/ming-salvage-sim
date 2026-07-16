import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { writeContainerCodexConfig } from "../../src/containerCodexConfig.js";
import {
  codexFastRunLog,
  runFamilyDriver,
  type Sh,
} from "../../src/familyDriver.js";
import type { FamilyBackend, MergeRequest, ReconcileGit } from "../../src/family/types.js";
import type { Backend } from "../../src/types.js";
import type { RealBackendOptions } from "../../src/realBackend.js";
import type { RealFamilyBackendOptions } from "../../src/family/realFamilyBackend.js";
import type { ResolvedModelRoute } from "../../src/modelRoutes.js";

const OFF_STATE_CONFIG_TOML =
  'sandbox_mode = "danger-full-access"\napproval_policy = "never"\n';
const FAST_STATE_CONFIG_TOML = `${OFF_STATE_CONFIG_TOML}service_tier = "fast"\n`;
const tempDirs: string[] = [];

afterEach(() => {
  delete process.env.ORCHESTRATOR_CODEX_FAST;
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

function makeSourceRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "codex-fast-760-source-"));
  tempDirs.push(dir);
  execFileSync("git", ["init", "-q", "-b", "main"], { cwd: dir });
  execFileSync("git", ["config", "user.email", "test@example.com"], { cwd: dir });
  execFileSync("git", ["config", "user.name", "test"], { cwd: dir });
  execFileSync("git", ["commit", "--allow-empty", "-q", "-m", "root"], { cwd: dir });
  return dir;
}

function makeEpicSh(): Sh {
  return (file, args) => {
    if (file === "gh" && args[0] === "api" && String(args[1]).includes("/sub_issues")) {
      return JSON.stringify([{ number: 1, state: "OPEN", labels: [{ name: "ready-for-agent" }] }]);
    }
    if (file === "gh" && args[0] === "api" && String(args[1]).includes("/dependencies/blocked_by")) {
      return "[]";
    }
    if (file === "gh" && args[0] === "issue" && args[1] === "view") {
      return JSON.stringify({ number: Number(args[2]), body: "", author: { login: "Akagilnc" } });
    }
    if (file === "git") {
      return execFileSync(file, args, { encoding: "utf8" }).trim();
    }
    throw new Error(`unexpected subprocess: ${file} ${args.join(" ")}`);
  };
}

function fakeBackend(sourceRepo: string): Backend {
  return {
    smokeModelRoute: async (route: ResolvedModelRoute) => {
      const { smokeRouteModels } = await import("../../src/modelRoutes.js");
      return smokeRouteModels(route, async () => ({ cliVersion: "test" }));
    },
    workingRepoPath: () => sourceRepo,
    findResumeState: async () => undefined,
    resumeSession: async () => ({ kind: "judge", status: "converged" }),
    fetchIssueMeta: async (issueNumber: number) => ({
      number: issueNumber,
      isReadyForAgent: true,
      hasSubIssues: false,
      isClosed: false,
      openBlockedBy: [],
    }),
    prepareWorktree: async (_issueNumber: number, base: string) => ({
      branch: "feat/fake-760",
      base,
      path: sourceRepo,
    }),
    runStep: async (spec: { role: string }) =>
      spec.role === "coder"
        ? { kind: "coder", committed: true, commitsAdded: 1 }
        : { kind: "judge", status: "converged" },
    writeLedger: async () => {},
  } as unknown as Backend;
}

function fakeFamilyBackend(): FamilyBackend & { reconcileGit(): ReconcileGit } {
  const ledger: unknown[] = [];
  return {
    mergeChildIntoFamilyBase: async (_request: MergeRequest) => ({
      conflicted: false,
      familyHead: "head-after-merge",
      childHead: "child-head",
    }),
    appendFamilyLedger: async (entry: unknown): Promise<void> => {
      ledger.push(entry);
    },
    readFamilyLedger: async () => ledger,
    reconcileGit: () => ({
      liveFamilyHead: async () => "head-after-merge",
      familyBaseStartHead: async () => "head-after-merge",
      childHeadExists: async () => ({ exists: false }),
      isAncestor: async () => false,
    }),
  } as unknown as FamilyBackend & { reconcileGit(): ReconcileGit };
}

async function runAssemblyWithEnv(fast: boolean): Promise<{
  backend: RealBackendOptions;
  family: RealFamilyBackendOptions;
  config: string;
}> {
  const sourceRepo = makeSourceRepo();
  if (fast) process.env.ORCHESTRATOR_CODEX_FAST = "1";
  else delete process.env.ORCHESTRATOR_CODEX_FAST;

  let backendOptions: RealBackendOptions | undefined;
  let familyOptions: RealFamilyBackendOptions | undefined;
  const configPath = join(mkdtempSync(join(tmpdir(), "codex-fast-760-config-")), "config.toml");
  tempDirs.push(configPath.slice(0, configPath.lastIndexOf("/")));

  await runFamilyDriver({
    epicIssue: 760,
    sourceRepo,
    repo: "Akagilnc/ming-salvage-sim",
    familyBase: "family/760-test",
    base: "main",
    promptsDir: "/tmp/prompts",
    familyPromptsDir: "/tmp/prompts",
    soulsDir: "/tmp/souls",
    ledgerDir: mkdtempSync(join(tmpdir(), "codex-fast-760-ledger-")),
    imageName: "test-image",
    sh: makeEpicSh(),
    realBackendFactory: (options) => {
      backendOptions = options;
      writeContainerCodexConfig(configPath, options.codexFast);
      return fakeBackend(sourceRepo) as never;
    },
    realFamilyBackendFactory: (options) => {
      familyOptions = options;
      return fakeFamilyBackend() as never;
    },
  });

  return {
    backend: backendOptions!,
    family: familyOptions!,
    config: readFileSync(configPath, "utf8"),
  };
}

describe("#760 container Codex fast master switch", () => {
  it("drives runFamilyDriver construction with fast on and off", async () => {
    const on = await runAssemblyWithEnv(true);
    expect(on.backend.codexFast).toBe(true);
    expect(on.family.codexFast).toBe(true);
    expect(on.config).toBe(FAST_STATE_CONFIG_TOML);

    const off = await runAssemblyWithEnv(false);
    expect(off.backend.codexFast).toBe(false);
    expect(off.family.codexFast).toBe(false);
    expect(off.config).toBe(OFF_STATE_CONFIG_TOML);
  });

  it("keeps the current config byte-identical when fast is off", async () => {
    const dir = mkdtempSync(join(tmpdir(), "codex-fast-760-off-"));
    tempDirs.push(dir);
    const path = join(dir, "config.toml");
    writeContainerCodexConfig(path, false);
    expect(readFileSync(path, "utf8")).toBe(OFF_STATE_CONFIG_TOML);
  });

  it("keeps the resolved setting visible in the run-level log line", () => {
    expect(codexFastRunLog(true)).toBe("[orchestrator] run fast=on");
    expect(codexFastRunLog(false)).toBe("[orchestrator] run fast=off");
  });
});
