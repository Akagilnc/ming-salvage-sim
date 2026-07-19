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
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
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
import { grokAgent } from "../../src/grokAgent.js";
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
import {
  dockerAvailable,
  dockerUnavailableReason,
} from "./docker.shared.js";

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
 * The live test gates host Docker once before calling this resolver.
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
  return env;
}

/**
 * Production worker print shape (grokAgent buildPrintCommand): prompt-file stdin +
 * streaming-json + always-approve. Never `grok login` / device-code.
 */
const HEADLESS_PRINT_ARGS = [
  "--prompt-file",
  "/dev/stdin",
  "--output-format",
  "streaming-json",
  "--always-approve",
  "--permission-mode",
  "bypassPermissions",
] as const;

function runHeadlessEmptyAuthProbe(target: GrokProbeTarget): {
  status: number | null;
  signal: NodeJS.Signals | null;
  timedOut: boolean;
  combined: string;
  elapsedMs: number;
} {
  const emptyHome = mkDir("964-empty-auth-home-");
  const env = emptyAuthEnv(emptyHome);
  const t0 = Date.now();
  if (target.kind === "host") {
    const r = spawnSync(target.bin, [...HEADLESS_PRINT_ARGS], {
      encoding: "utf8",
      input: "ping\n",
      env,
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
    };
  }
  // Docker: empty HOME for *container* grok only (mount + -e HOME=).
  // Host docker CLI must keep real HOME — emptyAuthEnv(HOME=tmp) breaks client
  // config / socket resolution ("failed to connect to the docker API ... sock").
  // Do NOT pass empty XAI_API_KEY= into the container (empty string counts as
  // present credentials → 401, not native "Not signed in"). Host env keys are
  // not auto-forwarded by docker run unless -e is used.
  // Entrypoint = baked grok ELF (image sleep-infinity entrypoint otherwise).
  const r = spawnSync(
    "docker",
    [
      "run",
      "--rm",
      "-i",
      "--entrypoint",
      "/usr/local/bin/grok",
      "-e",
      "HOME=/tmp/964-empty-home",
      "-v",
      `${emptyHome}:/tmp/964-empty-home`,
      target.image,
      ...HEADLESS_PRINT_ARGS,
    ],
    {
      encoding: "utf8",
      input: "ping\n",
      // Real process.env so docker CLI finds its socket/context; isolation is
      // container-side via HOME mount only.
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
    // Production mechanism (#964): pin ≥0.2.102 so headless auth death fail-fasts
    // ("Not signed in") instead of interactive device-code wait (0.2.93 flight3).
    // Companion live probe below guards hang regression when a matching binary
    // is available (GROK_BIN / PATH / baked image).
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

  const liveDockerAvailable = dockerAvailable();
  const liveDockerSkipReason = dockerUnavailableReason();
  if (!liveDockerAvailable) {
    console.warn(
      `[#964] skipping container-backed live probes: ${liveDockerSkipReason}`,
    );
  }

  it.skipIf(!liveDockerAvailable)(
    liveDockerAvailable
      ? "live headless empty-auth fails fast before timeout (no device-auth hang)"
      : `live headless empty-auth fails fast before timeout [skipped: ${liveDockerSkipReason}]`,
    () => {
      // #964 AC: real worker print shape + empty credentials must not enter
      // interactive device-code wait. Pin 0.2.102 is the production hang fix;
      // this probe exercises a real binary (host pin or baked image pin).
      // Docker is live here; soft-skip only when neither target has the pin.
      const target = resolveGrokProbeTarget();
      if (!target) {
        // Loud skip reason — CI with rebaked image / host pin / live docker should not hit this.
        console.warn(
          `[#964] skip live empty-auth probe: no grok ${GROK_FAIL_FAST_PIN} on PATH/GROK_BIN, ` +
          `or no docker image with that pin ` +
            `(set GROK_BIN or rebake ${DEFAULT_GROK_PROBE_IMAGE}; ` +
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
    },
    HEADLESS_AUTH_PROBE_TIMEOUT_MS + 30_000,
  );

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
  it("workerResultFromAgentError maps AgentError to host-synthesized escalated (single court)", () => {
    const result = workerResultFromAgentError(
      fiberAgentError("Not signed in"),
      "coder",
    );
    expect(result).toBeDefined();
    expect(result!.kind).toBe("escalated");
    if (result!.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result!.escalation)).toBe(true);
    expect(result!.escalation.reason).toMatch(
      /coder agent invocation failed|Not signed in/i,
    );
    expect(workerResultFromAgentError(new Error("plain crash"), "coder")).toBe(
      undefined,
    );
  });

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

  it("withMechanicalRetry does not re-dispatch AgentError (dead credentials once)", async () => {
    const route = smokedRoute();
    const spec = familyCoderFixWorkerSpec(route);
    let attempts = 0;
    const result = await withMechanicalRetry(
      spec,
      { familyBase: "family/964-base", modelRoute: route },
      async () => {
        attempts += 1;
        throw midRunAgentError();
      },
    );
    expect(attempts).toBe(1);
    expect(result.kind).toBe("escalated");
    if (result.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result.escalation)).toBe(true);
    expect(result.escalation.reason).toMatch(/agent invocation failed|Not signed in/i);
  });

  it("dispatchWorker (single-slice seam) converts AgentError to typed failure (no throw)", async () => {
    const route = smokedRoute();
    const throwsAgent: Backend = {
      async dispatchWorker(
        _spec: WorkerSpec,
        _ctx: DispatchContext,
      ): Promise<WorkerResult> {
        throw midRunAgentError();
      },
    } as Backend;
    const spec: WorkerSpec = {
      id: "S2",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      promptFile: "coder.md",
      maxIter: 1,
      model: "gpt-5.6-terra",
      soul: "coder",
      toolchain: [],
    };
    const result = await dispatchWorker(throwsAgent, spec, {
      modelRoute: route,
    });
    expect(result.kind).toBe("escalated");
    if (result.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result.escalation)).toBe(true);
    expect(result.escalation.reason).toMatch(/coder agent invocation failed|Not signed in/i);
  });

  it("FamilyBackend method throw is converted at free-function court (cmr-class seat)", async () => {
    // Prove free-function court, not merger-only: any family dispatchWorker throw.
    const route = smokedRoute();
    const be = {
      async dispatchWorker(): Promise<WorkerResult> {
        throw fiberAgentError("Not signed in");
      },
    } as unknown as FamilyBackend;
    const result = await dispatchFamilyWorker(
      be,
      { ...familyCoderFixWorkerSpec(route), kind: "cmr", role: "verify", soul: "verify" },
      { familyBase: "family/964-base", modelRoute: route },
    );
    expect(result.kind).toBe("escalated");
    if (result.kind !== "escalated") throw new Error("expected escalated");
    expect(isRunnerSynthesizedFailureEscalation(result.escalation)).toBe(true);
  });
});
