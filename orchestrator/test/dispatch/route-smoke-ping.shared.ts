import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  barePingArgv,
  barePingNonceSatisfied,
  buildBarePingPrompt,
  loadBarePingPromptTemplate,
  RealBackend,
  resolveRouteSmokeIdleTimeoutSeconds,
} from "../../src/realBackend.js";

import {
  resolveRouteModels,
  routeSmokeEntries,
  routeSmokeFailure,
  smokeRouteModels,
} from "../../src/modelRoutes.js";

import { logDriverStage, DRIVER_STAGES } from "../../src/stageLog.js";

import { runOrchestrator } from "../../src/runner.js";

import type {
  Backend,
  IssueMeta,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
} from "../../src/types.js";

const fixtureDir = dirname(fileURLToPath(import.meta.url));

const promptsDir = join(fixtureDir, "..", "..", "prompts");

const soulsDir = join(fixtureDir, "..", "..", "image", "souls");

const tempHomes: string[] = [];

function tempHome(prefix = "bare-ping-884-"): string {
  const home = mkdtempSync(join(tmpdir(), prefix));
  tempHomes.push(home);
  mkdirSync(join(home, ".codex"), { recursive: true });
  writeFileSync(join(home, ".codex", "auth.json"), "{}\n");
  writeFileSync(join(home, ".sc-claude-token"), "test-token\n");
  // #905: agy OAuth for real agy bare-ping / workers (fail-closed without it).
  // #1106: read the LIVE antigravity-cli token (no stale .sc-agy-oauth-token).
  mkdirSync(join(home, ".gemini", "antigravity-cli"), { recursive: true });
  writeFileSync(
    join(home, ".gemini", "antigravity-cli", "antigravity-oauth-token"),
    "agy-test-token\n",
  );
  // #807/#905: grok auth for SuperGrok bare-ping / workers.
  mkdirSync(join(home, ".grok"), { recursive: true });
  writeFileSync(join(home, ".grok", "auth.json"), "{}\n");
  return home;
}

class BarePingBackend extends RealBackend {
  readonly pingCalls: Array<{
    slug: string;
    cwd: string;
    prompt: string;
    nonce: string;
    /** Wall budget the production smoke path handed this shot (#1089). */
    timeoutMs: number;
  }> = [];
  private readonly pingImpl: (
    input: BarePingBackend["pingCalls"][number],
  ) => Promise<string>;

  constructor(
    home: string,
    pingImpl: (input: BarePingBackend["pingCalls"][number]) => Promise<string>,
  ) {
    super({
      sourceRepo: "/tmp/route-smoke-source",
      remote: "https://github.com/owner/route-smoke.git",
      runKey: 884,
      repo: "owner/route-smoke",
      imageName: "route-smoke-test-image",
      promptsDir,
      soulsDir,
      home,
    });
    this.pingImpl = pingImpl;
  }

  protected override cloneDirExists(): boolean {
    return true;
  }

  protected override sh(file: string, args: string[]): string {
    if (file === "git" && args[0] === "rev-parse" && args[1] === "--git-common-dir") {
      return ".git";
    }
    if (
      file === "codex" ||
      file === "claude" ||
      file === "agy" ||
      file === "grok" ||
      file === "cursor" ||
      file === "agent"
    ) {
      return "cli-test-version";
    }
    return "";
  }

  protected override async execBarePing(input: {
    readonly slug: string;
    readonly cwd: string;
    readonly prompt: string;
    readonly nonce: string;
    readonly file: string;
    readonly args: readonly string[];
    readonly stdin?: string;
    readonly timeoutMs: number;
  }): Promise<string> {
    const call = {
      slug: input.slug,
      cwd: input.cwd,
      prompt: input.prompt,
      nonce: input.nonce,
      timeoutMs: input.timeoutMs,
    };
    this.pingCalls.push(call);
    return this.pingImpl(call);
  }

  public async readProductionBarePingEnvironment(): Promise<{
    home: string | undefined;
    claudeToken: string | undefined;
  }> {
    const stdout = await super.execBarePing({
      slug: "sonnet",
      cwd: tmpdir(),
      prompt: "unused",
      nonce: "unused",
      file: process.execPath,
      args: [
        "-e",
        "process.stdout.write(JSON.stringify({home:process.env.HOME,claudeToken:process.env.CLAUDE_CODE_OAUTH_TOKEN}))",
      ],
      timeoutMs: 2_000,
    });
    return JSON.parse(stdout) as {
      home: string | undefined;
      claudeToken: string | undefined;
    };
  }
}

export {
  mkdtempSync,
  mkdirSync,
  rmSync,
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
  barePingArgv,
  barePingNonceSatisfied,
  buildBarePingPrompt,
  loadBarePingPromptTemplate,
  RealBackend,
  resolveRouteSmokeIdleTimeoutSeconds,
  resolveRouteModels,
  routeSmokeEntries,
  routeSmokeFailure,
  smokeRouteModels,
  logDriverStage,
  DRIVER_STAGES,
  runOrchestrator,
  Backend,
  IssueMeta,
  ResumeState,
  StepOutput,
  StepSpec,
  WorktreeHandle,
  fixtureDir,
  promptsDir,
  soulsDir,
  tempHomes,
  tempHome,
  BarePingBackend,
};
