import { execFileSync, spawnSync } from "node:child_process";

import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";

import { tmpdir } from "node:os";

import { dirname, join } from "node:path";

import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import {
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../../src/dispatchRetry.js";

import { dispatchWorker } from "../../src/dispatchWorker.js";

import {
  dispatchFamilyWorker,
  familyCoderFixWorkerSpec,
} from "../../src/family/dispatchFamilyWorker.js";

import { buildExplicitLandingLiveHooks } from "../../src/family/landing.js";

import { mergeChild } from "../../src/family/merger.js";

import {
  RealFamilyBackend,
  type RealFamilyBackendOptions,
} from "../../src/family/realFamilyBackend.js";

import type {
  ConflictResolveRequest,
  FamilyBackend,
  MergeRequest,
  MergeResult,
} from "../../src/family/types.js";

import { grokAgent, shellEscape } from "../../src/grokAgent.js";

import {
  resolveRouteModels,
  routeSmokeEntries,
  type ResolvedModelRoute,
} from "../../src/modelRoutes.js";

import { PUBLIC_FAILED_CAUSES } from "../../src/publicResult.js";

import { barePingArgv } from "../../src/realBackend.js";

import { isRunnerSynthesizedFailureEscalation } from "../../src/runnerEscalation.js";

import {
  isSandcastleAgentError,
  workerResultFromAgentError,
} from "../../src/sandcastleAgentError.js";

import type {
  Backend,
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));

const orchestratorRoot = join(here, "..", "..");

const promptsDir = join(orchestratorRoot, "prompts");

const soulsDir = join(orchestratorRoot, "image", "souls");

const GROK_FAIL_FAST_PIN = "0.2.102";

const HEADLESS_AUTH_PROBE_TIMEOUT_MS = 15_000;

const DEFAULT_GROK_PROBE_IMAGE = "ming-orchestrator-coder:latest";

const tmpDirs: string[] = [];

function mkDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(d);
  return d;
}

function whichBinary(name: string): string | null {
  const r = spawnSync("which", [name], { encoding: "utf8" });
  if (r.status !== 0) return null;
  const p = (r.stdout ?? "").trim();
  return p.length > 0 ? p : null;
}

function hostGrokVersion(bin: string): string {
  const r = spawnSync(bin, ["--version"], {
    encoding: "utf8",
    timeout: 5_000,
  });
  return `${r.stdout ?? ""}${r.stderr ?? ""}`.trim();
}

function dockerGrokVersion(image: string): string | null {
  const r = spawnSync(
    "docker",
    ["run", "--rm", "--entrypoint", "/usr/local/bin/grok", image, "--version"],
    { encoding: "utf8", timeout: 60_000 },
  );
  if (r.status !== 0) return null;
  return `${r.stdout ?? ""}${r.stderr ?? ""}`.trim();
}

type GrokProbeTarget =
  | { kind: "host"; bin: string; version: string }
  | { kind: "docker"; image: string; version: string };

function resolveGrokProbeTarget(): GrokProbeTarget | null {
  const fromEnv = process.env.GROK_BIN?.trim();
  const hostCandidates = [
    fromEnv && existsSync(fromEnv) ? fromEnv : null,
    whichBinary("grok"),
  ].filter((p): p is string => typeof p === "string" && p.length > 0);

  for (const bin of hostCandidates) {
    const version = hostGrokVersion(bin);
    if (version.includes(GROK_FAIL_FAST_PIN)) {
      return { kind: "host", bin, version };
    }
  }

  if (!whichBinary("docker")) return null;
  const image =
    process.env.GROK_PROBE_IMAGE?.trim() || DEFAULT_GROK_PROBE_IMAGE;
  // Cheap presence check — missing image → no docker target.
  const inspect = spawnSync("docker", ["image", "inspect", image], {
    encoding: "utf8",
    timeout: 15_000,
  });
  if (inspect.status !== 0) return null;
  const version = dockerGrokVersion(image);
  if (version && version.includes(GROK_FAIL_FAST_PIN)) {
    return { kind: "docker", image, version };
  }
  return null;
}

function emptyAuthEnv(home: string): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...process.env, HOME: home };
  delete env.XAI_API_KEY;
  delete env.GROK_API_KEY;
  delete env.XAI_KEY;
  // Transport harness flags must never leak into the live auth probe.
  delete env.GROK_HOLD_OPEN;
  delete env.GROK_PROMPT_PATH_OUT;
  return env;
}

function requirePinnedHostTarget(
  skip: (note?: string) => never,
): Extract<GrokProbeTarget, { kind: "host" }> {
  const bin = process.env.GROK_BIN?.trim() || whichBinary("grok");
  if (!bin) {
    return skip(`[#964] unavailable: no host grok ${GROK_FAIL_FAST_PIN}`);
  }
  const version = hostGrokVersion(bin);
  if (!version.includes(GROK_FAIL_FAST_PIN)) {
    const versionLabel = version.split(/\r?\n/, 1)[0] || "no version";
    return skip(
      `[#964] unavailable: host grok is not ${GROK_FAIL_FAST_PIN} (${bin}: ${versionLabel})`,
    );
  }
  return { kind: "host", bin, version };
}

type HeadlessProbeResult = {
  status: number | null;
  signal: NodeJS.Signals | null;
  timedOut: boolean;
  combined: string;
  elapsedMs: number;
};

function runHostPipeProbe(
  bin: string,
  args: readonly string[],
  env: NodeJS.ProcessEnv,
  timeoutMs: number,
): HeadlessProbeResult {
  const t0 = Date.now();
  const result = spawnSync("/bin/bash", [
    "-c",
    'bin=$1; shift; exec "$bin" "$@" < <(printf "%s\\n" "$PROBE_INPUT")',
    "grok-headless-probe",
    bin,
    ...args,
  ], {
    encoding: "utf8",
    env: { ...env, PROBE_INPUT: "ping" },
    timeout: timeoutMs,
    maxBuffer: 2 * 1024 * 1024,
    killSignal: "SIGKILL",
  });
  const timedOut =
    result.error?.message?.includes("TIMEDOUT") === true ||
    result.signal === "SIGTERM" ||
    result.signal === "SIGKILL";
  return {
    status: result.status,
    signal: result.signal,
    timedOut,
    combined: `${result.stdout ?? ""}\n${result.stderr ?? ""}`,
    elapsedMs: Date.now() - t0,
  };
}

function runHeadlessEmptyAuthProbe(
  target: GrokProbeTarget,
  pathOverride?: string,
): {
  status: number | null;
  signal: NodeJS.Signals | null;
  timedOut: boolean;
  combined: string;
  elapsedMs: number;
  stagedFiles: string[];
} {
  const emptyHome = mkDir("964-empty-auth-home-");
  const env = emptyAuthEnv(emptyHome);
  if (pathOverride !== undefined) env.PATH = pathOverride;
  const staging = join(emptyHome, "staging");
  mkdirSync(staging);
  const built = grokAgent("grok-4.5", { captureSessions: false }).buildPrintCommand({
    prompt: "ping\n",
    dangerouslySkipPermissions: true,
  });
  const t0 = Date.now();
  if (target.kind === "host") {
    // Bind the selected binary into the production command so PATH cannot redirect it
    // (#993). Keep TMPDIR staging so prompt-file cleanup remains observable (#989).
    const selectedCommand = built.command.replace(
      "grok --prompt-file",
      `${shellEscape(target.bin)} --prompt-file`,
    );
    const r = spawnSync("bash", ["-c", selectedCommand], {
      encoding: "utf8",
      input: built.stdin,
      env: {
        ...env,
        TMPDIR: staging,
      },
      timeout: HEADLESS_AUTH_PROBE_TIMEOUT_MS,
      maxBuffer: 2 * 1024 * 1024,
      killSignal: "SIGKILL",
    });
    const timedOut =
      r.error?.message?.includes("TIMEDOUT") === true ||
      r.signal === "SIGTERM" ||
      r.signal === "SIGKILL";
    return {
      status: r.status,
      signal: r.signal,
      timedOut,
      combined: `${r.stdout ?? ""}\n${r.stderr ?? ""}`,
      elapsedMs: Date.now() - t0,
      stagedFiles: readdirSync(staging),
    };
  }
  // Docker: empty HOME mount; do NOT pass empty XAI_API_KEY= (empty string is
  // treated as present credentials → 401, not the native "Not signed in" path).
  // Entrypoint is /bin/sh so the production buildPrintCommand shell (mktemp/cat/
  // trap/grok) runs end-to-end; image default is sleep-infinity.
  const r = spawnSync(
    "docker",
    [
      "run",
      "--rm",
      "-i",
      "--user",
      "0:0",
      "--entrypoint",
      "/bin/sh",
      "-e",
      "HOME=/tmp/964-empty-home",
      "-e",
      "TMPDIR=/tmp/964-empty-home/staging",
      "-v",
      `${emptyHome}:/tmp/964-empty-home`,
      target.image,
      "-c",
      `mkdir -p "$TMPDIR" && ${built.command}`,
    ],
    {
      encoding: "utf8",
      input: built.stdin,
      // Keep the host Docker client's HOME so its selected context/socket
      // remains reachable. The container still receives only the empty HOME
      // mounted above; Docker does not forward host auth variables implicitly.
      env: process.env,
      timeout: HEADLESS_AUTH_PROBE_TIMEOUT_MS,
      maxBuffer: 2 * 1024 * 1024,
      killSignal: "SIGKILL",
    },
  );
  const timedOut =
    r.error?.message?.includes("TIMEDOUT") === true ||
    r.signal === "SIGTERM" ||
    r.signal === "SIGKILL";
  return {
    status: r.status,
    signal: r.signal,
    timedOut,
    combined: `${r.stdout ?? ""}\n${r.stderr ?? ""}`,
    elapsedMs: Date.now() - t0,
    stagedFiles: readdirSync(staging),
  };
}

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

function smokedRoute(): ResolvedModelRoute {
  const base = resolveRouteModels("normal", {});
  const smoke = Object.fromEntries(
    routeSmokeEntries(base).map((entry) => [
      entry.key,
      {
        state: "passed" as const,
        at: new Date().toISOString(),
        cliVersion: `cli-${entry.slug}`,
      },
    ]),
  );
  return resolveRouteModels("normal", {}, {}, smoke);
}

function midRunAgentError(): Error {
  return Object.assign(
    new Error(
      "grok exited with code 1:\n\nError: Not signed in. To authenticate without a browser, run:\n  grok login --device-code",
    ),
    { name: "AgentError", _tag: "AgentError" },
  );
}

class CoderAgentErrorFamilyBackend extends AgentErrorSandboxBackend {
  protected override mountShipAuth() {
    return {
      claudeToken: "tok",
      grokAuthDir: mkDir("964-coder-grok-auth-"),
    };
  }
}

export {
  execFileSync,
  spawnSync,
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
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
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
  dispatchWorker,
  dispatchFamilyWorker,
  familyCoderFixWorkerSpec,
  buildExplicitLandingLiveHooks,
  mergeChild,
  RealFamilyBackend,
  RealFamilyBackendOptions,
  ConflictResolveRequest,
  FamilyBackend,
  MergeRequest,
  MergeResult,
  grokAgent,
  shellEscape,
  resolveRouteModels,
  routeSmokeEntries,
  ResolvedModelRoute,
  PUBLIC_FAILED_CAUSES,
  barePingArgv,
  isRunnerSynthesizedFailureEscalation,
  isSandcastleAgentError,
  workerResultFromAgentError,
  Backend,
  DispatchContext,
  WorkerResult,
  WorkerSpec,
  here,
  orchestratorRoot,
  promptsDir,
  soulsDir,
  GROK_FAIL_FAST_PIN,
  HEADLESS_AUTH_PROBE_TIMEOUT_MS,
  DEFAULT_GROK_PROBE_IMAGE,
  tmpDirs,
  mkDir,
  whichBinary,
  hostGrokVersion,
  dockerGrokVersion,
  GrokProbeTarget,
  resolveGrokProbeTarget,
  emptyAuthEnv,
  requirePinnedHostTarget,
  HeadlessProbeResult,
  runHostPipeProbe,
  runHeadlessEmptyAuthProbe,
  makeRepo,
  baseOpts,
  fiberAgentError,
  AgentErrorSandboxBackend,
  MergeChildAgentErrorBackend,
  smokedRoute,
  midRunAgentError,
  CoderAgentErrorFamilyBackend,
};
