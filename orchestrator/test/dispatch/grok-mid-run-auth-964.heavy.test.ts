/**
 * #964 — mid-run grok auth death → typed failure; no headless device-auth wait.
 *
 * Seams under test (real entry, not internals):
 *   1. grokAgent buildPrintCommand — headless-only CLI shape (never interactive login form)
 *   2. Containerfile grok pin — production mechanism for fail-fast non-interactive auth
 *      (0.2.102+; 0.2.93 entered device-code wait under headless empty auth)
 *   3. Live headless empty-auth probe against real/baked grok — short hard timeout proves
 *      fail-fast ("Not signed in") rather than interactive device-auth hang
 *   4. runMergerAgent / resolveMergeConflict / mergeChild — Sandcastle AgentError becomes
 *      Action-typed failure (structured non-resolve → conflicted + reason), never uncaught
 *      FiberFailure
 *   5. public ABI — no new cause token like auth_expired
 *   6. route-smoke bare-ping shape — startup auth probe not rewritten
 *   7. Generic Worker Invocation (non-merger): dispatchFamilyWorker / dispatchWorker /
 *      withMechanicalRetry convert AgentError → host-synthesized escalated typed failure
 *      (always-on CI court; live CLI probe may soft-skip)
 *
 * Authority: #964 AC + voided owner comment (native fail-fast only; no log parse /
 * monitor kill / run fuse / auth_expired public cause). Pin 0.2.102 is the production
 * hang fix; the live probe guards regression if a hangy CLI reappears on PATH / image.
 */

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

/** Production pin (Containerfile); live probe prefers a binary matching this. */
const GROK_FAIL_FAST_PIN = "0.2.102";
/** Short hard wall — hangy device-auth wait must not survive this (8–15s band). */
const HEADLESS_AUTH_PROBE_TIMEOUT_MS = 15_000;
const DEFAULT_GROK_PROBE_IMAGE = "ming-orchestrator-coder:latest";

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

/**
 * Resolve a real grok that matches the production fail-fast pin.
 * Prefer host (GROK_BIN / PATH); fall back to docker image with baked pin.
 * Skip only when neither yields a pin-matching binary (or docker is absent).
 */
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

/** Env for empty/no credentials: isolated HOME, strip API-key auth env. */
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
      built.command,
    ],
    {
      encoding: "utf8",
      input: built.stdin,
      env: emptyAuthEnv(emptyHome),
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

  it(
    "live headless empty-auth fails fast before timeout (no device-auth hang)",
    () => {
      const pidDir = mkDir("964-timeout-child-");
      const pidFile = join(pidDir, "pid");
      const hang = runHostPipeProbe(
        "/bin/sh",
        ["-c", 'echo $$ > "$PID_FILE"; exec sleep 60'],
        { ...process.env, PID_FILE: pidFile },
        250,
      );
      expect(hang.timedOut).toBe(true);
      const childPid = Number(readFileSync(pidFile, "utf8").trim());
      let childAlive = true;
      try {
        process.kill(childPid, 0);
      } catch (error: any) {
        if (error?.code !== "ESRCH") throw error;
        childAlive = false;
      }
      expect(childAlive, `timed-out probe child ${childPid} must be reaped`).toBe(false);

      // #964 AC: real worker print shape + empty credentials must not enter
      // interactive device-code wait. Pin 0.2.102 is the production hang fix;
      // this probe exercises a real binary (host pin or baked image pin).
      // Only this live portion skips when no eligible binary is available; the
      // timeout/reap guard above is environment-independent and always runs.
      const target = resolveGrokProbeTarget();
      if (!target) {
        console.warn(
          `[#964] skip live empty-auth probe: no grok ${GROK_FAIL_FAST_PIN} on PATH/GROK_BIN ` +
            `and no docker image with that pin (set GROK_BIN or rebake ${DEFAULT_GROK_PROBE_IMAGE}; ` +
            `override image via GROK_PROBE_IMAGE). Pin ${GROK_FAIL_FAST_PIN} remains the production mechanism.`,
        );
        return;
      }

      const result = runHeadlessEmptyAuthProbe(target);
      // Must exit on its own (non-zero fail-fast), not be killed by our wall clock.
      expect(
        result.timedOut,
        `grok empty-auth hung until hard timeout (${HEADLESS_AUTH_PROBE_TIMEOUT_MS}ms) ` +
          `via ${target.kind}=${target.kind === "host" ? target.bin : target.image} ` +
          `version=${target.version}; expected native fail-fast (pin ${GROK_FAIL_FAST_PIN})`,
      ).toBe(false);
      expect(result.status, result.combined).not.toBeNull();
      expect(result.status, result.combined).not.toBe(0);
      // Fail-fast class outcome (native CLI message on pin ≥0.2.102).
      expect(result.combined).toMatch(/Not signed in|unauthenticated|Unauthorized/i);
      // Well under the wall — hang regression would burn the full timeout.
      expect(result.elapsedMs).toBeLessThan(HEADLESS_AUTH_PROBE_TIMEOUT_MS);
      expect(result.stagedFiles).toEqual([]);
    },
    HEADLESS_AUTH_PROBE_TIMEOUT_MS + 30_000,
  );

  it("live GROK_BIN target remains authoritative when PATH has no grok", ({ skip }) => {
    const result = runHeadlessEmptyAuthProbe(
      requirePinnedHostTarget(skip),
      "/usr/bin:/bin",
    );
    expect(result.status, result.combined).not.toBe(0);
    expect(result.combined).toMatch(/Not signed in|unauthenticated|Unauthorized/i);
  });

  it("live GROK_BIN target wins over a different grok on PATH", ({ skip }) => {
    const decoyDir = mkDir("964-decoy-grok-");
    const decoy = join(decoyDir, "grok");
    writeFileSync(decoy, "#!/bin/sh\necho WRONG_GROK >&2\nexit 77\n");
    chmodSync(decoy, 0o755);
    const result = runHeadlessEmptyAuthProbe(
      requirePinnedHostTarget(skip),
      `${decoyDir}:/usr/bin:/bin`,
    );
    expect(result.combined).not.toContain("WRONG_GROK");
    expect(result.combined).toMatch(/Not signed in|unauthenticated|Unauthorized/i);
  });

});

describe("#964 AgentError → Action typed failure (merger worker entry)", () => {

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

/** Non-merger family seat: runAgentSandbox throws mid-run AgentError (coder-fix path). */
class CoderAgentErrorFamilyBackend extends AgentErrorSandboxBackend {
  protected override mountShipAuth() {
    return {
      claudeToken: "tok",
      grokAuthDir: mkDir("964-coder-grok-auth-"),
    };
  }
}

describe("#964 AgentError → Action typed failure (generic Worker Invocation)", () => {

  it("dispatchFamilyWorker converts AgentError on non-merger coder seat (no uncaught throw)", async () => {
    // Real free-function Worker Invocation seam (production path for family seats).
    const route = smokedRoute();
    const be = new CoderAgentErrorFamilyBackend(baseOpts(makeRepo()));
    const result = await dispatchFamilyWorker(
      be,
      familyCoderFixWorkerSpec(route),
      { familyBase: "family/964-base", modelRoute: route },
    );
    expect(result.kind).toBe("escalated");
    if (result.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result.escalation)).toBe(true);
    expect(result.escalation.reason).toMatch(
      /agent invocation failed|Not signed in/i,
    );
  });

});
