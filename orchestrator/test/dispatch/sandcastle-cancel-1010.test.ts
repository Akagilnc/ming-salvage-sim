/**
 * #1010 — Sandcastle cancel seam must reach the container/shell process.
 *
 * Before: abort only abandoned the host docker-exec Promise; the shell +
 * prompt temp files inside a reused container survived.
 * After: AbortSignal (and idle-timeout local abort) kill the exec child so
 * shell traps run and temps do not linger.
 *
 * Strategy under test: local patch of @ai-hero/sandcastle@0.12.0 (exact pin;
 * no bump). Cross-provider (no-sandbox always; docker when daemon+image OK).
 *
 * AC2: failure fixture asserts exit codes 7 / 129 / 130 / 143 and pre-agent
 * (pre-grok) failure propagation — through the patched sandcastle exec seam
 * (no-sandbox handle + sc.run), not only bare host spawn — #988 escalate gap.
 */

import { spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import "../../src/sandcastleCancelSeam.js"; // #1010 first
import * as sc from "@ai-hero/sandcastle";
import { noSandbox } from "@ai-hero/sandcastle/sandboxes/no-sandbox";

const TMP_PREFIX = "sc-cancel-1010-";

/** Production-shaped shell used by agent print commands that materialize stdin. */
function trapShellCommand(): string {
  // mktemp → traps → chmod → cat prompt → run `agent` (fake) → EXIT cleans.
  // HUP/INT/TERM convert to 129/130/143 so EXIT trap always runs (dash-safe).
  return (
    `prompt_file=$(mktemp) || exit $?; ` +
    `cleanup_prompt() { rm -f -- "$prompt_file"; }; ` +
    `trap cleanup_prompt EXIT; ` +
    `trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM; ` +
    `chmod 600 "$prompt_file" && cat > "$prompt_file" && ` +
    `agent --prompt-file "$prompt_file"`
  );
}

function makeFakeAgent(root: string): {
  readonly bin: string;
  readonly captured: string;
  readonly pathLog: string;
  readonly modeLog: string;
  readonly started: string;
  readonly pidLog: string;
} {
  const bin = join(root, "agent");
  const captured = join(root, "captured");
  const pathLog = join(root, "path");
  const modeLog = join(root, "mode");
  const started = join(root, "started");
  const pidLog = join(root, "pid");
  // MODE=success|failure|HUP|INT|TERM|sleep
  writeFileSync(
    bin,
    `#!/bin/sh
while [ "$#" -gt 0 ] && [ "$1" != "--prompt-file" ]; do shift; done
[ "$1" = "--prompt-file" ] || exit 2
shift
printf '%s' "$1" > "$PATH_LOG"
# portable mode bits (GNU stat -c or BSD stat -f)
if stat -c '%a' "$1" >/dev/null 2>&1; then
  stat -c '%a' "$1" > "$MODE_LOG"
else
  stat -f '%OLp' "$1" > "$MODE_LOG"
fi
cp "$1" "$CAPTURED"
printf '%s' "$$" > "$PID_LOG"
: > "$STARTED"
case "\${MODE:-success}" in
  success) exit 0 ;;
  failure) exit 7 ;;
  sleep)
    # long-lived so abort can interrupt mid-run
    sleep 30
    exit 0
    ;;
  *)
    # signal parent shell (the trap-installing sh -c) so EXIT cleanup runs
    kill -s "$MODE" "$PPID"
    exit 0
    ;;
esac
`,
  );
  chmodSync(bin, 0o755);
  return { bin, captured, pathLog, modeLog, started, pidLog };
}

function fixtureEnv(
  root: string,
  fake: ReturnType<typeof makeFakeAgent>,
  mode: string,
): Record<string, string> {
  return {
    PATH: `${root}:${process.env.PATH ?? ""}`,
    TMPDIR: root,
    MODE: mode,
    CAPTURED: fake.captured,
    PATH_LOG: fake.pathLog,
    MODE_LOG: fake.modeLog,
    STARTED: fake.started,
    PID_LOG: fake.pidLog,
  };
}

function processAlive(pid: number): boolean {
  if (!Number.isFinite(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

/**
 * Runtime bind-mount / no-sandbox create is present but omitted from the
 * public SandboxProvider type surface — same cast shape as docker cancel test.
 */
type ExecHandle = {
  exec: (
    cmd: string,
    opts?: { stdin?: string; signal?: AbortSignal },
  ) => Promise<{ stdout: string; stderr: string; exitCode: number }>;
  close: () => Promise<void>;
};

type CreateProvider = {
  create: (opts: {
    worktreePath: string;
    hostRepoPath: string;
    mounts: readonly unknown[];
    env: Record<string, string>;
  }) => Promise<ExecHandle>;
};

/** Drive trap shell through the patched no-sandbox sandcastle exec seam. */
async function runTrapViaNoSandboxExec(input: {
  readonly root: string;
  readonly mode: string;
  readonly prompt: string;
}): Promise<{
  readonly exitCode: number;
  readonly stdout: string;
  readonly stderr: string;
  readonly fake: ReturnType<typeof makeFakeAgent>;
}> {
  const fake = makeFakeAgent(input.root);
  const provider = noSandbox({
    env: fixtureEnv(input.root, fake, input.mode),
  }) as unknown as CreateProvider;
  const handle = await provider.create({
    worktreePath: input.root,
    hostRepoPath: input.root,
    mounts: [],
    env: fixtureEnv(input.root, fake, input.mode),
  });
  try {
    const result = await handle.exec(trapShellCommand(), {
      stdin: input.prompt,
    });
    return {
      exitCode: result.exitCode,
      stdout: result.stdout,
      stderr: result.stderr,
      fake,
    };
  } finally {
    await handle.close().catch(() => {});
  }
}

function initGitRepo(root: string): void {
  spawnSync("git", ["init"], { cwd: root, encoding: "utf8" });
  spawnSync("git", ["config", "user.email", "t@t.t"], { cwd: root });
  spawnSync("git", ["config", "user.name", "t"], { cwd: root });
  writeFileSync(join(root, "README"), "x\n");
  spawnSync("git", ["add", "README"], { cwd: root });
  spawnSync("git", ["commit", "-m", "init"], { cwd: root });
}

function signalExitOk(
  exitCode: number,
  mode: "HUP" | "INT" | "TERM",
): boolean {
  const want = { HUP: 129, INT: 130, TERM: 143 }[mode];
  const n = { HUP: 1, INT: 2, TERM: 15 }[mode];
  // sh may report 128+n; sandcastle close code is typically 128+n or the trap exit.
  return exitCode === want || exitCode === 128 + n;
}

describe("#1010 failure fixture via patched sandcastle exec (7 / 129 / 130 / 143 + pre-agent)", () => {
  const roots: string[] = [];
  afterEach(() => {
    for (const r of roots.splice(0)) {
      rmSync(r, { recursive: true, force: true });
    }
  });

  function scratch(): string {
    const root = mkdtempSync(join(tmpdir(), TMP_PREFIX));
    roots.push(root);
    return root;
  }

  it("no-sandbox exec: failure mode exits 7 and removes the private prompt file", async () => {
    const root = scratch();
    const prompt = "fail-prompt\n";
    const { exitCode, fake } = await runTrapViaNoSandboxExec({
      root,
      mode: "failure",
      prompt,
    });
    expect(exitCode).toBe(7);
    expect(readFileSync(fake.captured, "utf8")).toBe(prompt);
    expect(readFileSync(fake.modeLog, "utf8").trim()).toMatch(/600/);
    const promptPath = readFileSync(fake.pathLog, "utf8");
    expect(promptPath.length).toBeGreaterThan(0);
    expect(existsSync(promptPath)).toBe(false);
  });

  it.each([
    ["HUP", 129],
    ["INT", 130],
    ["TERM", 143],
  ] as const)(
    "no-sandbox exec: signal %s exits %i (or 128+n) and removes the private prompt file",
    async (mode, _code) => {
      const root = scratch();
      const prompt = `sig-${mode}\n`;
      const { exitCode, fake } = await runTrapViaNoSandboxExec({
        root,
        mode,
        prompt,
      });
      expect(signalExitOk(exitCode, mode)).toBe(true);
      const promptPath = readFileSync(fake.pathLog, "utf8");
      expect(promptPath.length).toBeGreaterThan(0);
      expect(existsSync(promptPath)).toBe(false);
    },
  );

  it("no-sandbox exec: pre-agent (pre-grok) failure propagates — exit 7, agent never starts", async () => {
    const root = scratch();
    const agentStarted = join(root, "agent-started");
    // Prerequisite check fails before agent — same class as mktemp/auth preflight miss.
    const cmd =
      `preflight() { return 7; }; ` +
      `preflight || exit $?; ` +
      `echo should-not-reach > "${agentStarted}"; exit 0`;
    const provider = noSandbox({ env: {} }) as unknown as CreateProvider;
    const handle = await provider.create({
      worktreePath: root,
      hostRepoPath: root,
      mounts: [],
      env: {},
    });
    try {
      const result = await handle.exec(cmd);
      expect(result.exitCode).toBe(7);
      expect(existsSync(agentStarted)).toBe(false);
    } finally {
      await handle.close().catch(() => {});
    }
  });

  it("sc.run product path: agent exit 7 becomes AgentError (exitCode 7), prompt cleaned", async () => {
    const root = scratch();
    initGitRepo(root);
    const fake = makeFakeAgent(root);
    const prompt = "sc-run-fail-7\n";
    const agent: sc.AgentProvider = {
      name: "cancel-fail-probe",
      env: {},
      captureSessions: false,
      buildPrintCommand() {
        return { command: trapShellCommand(), stdin: prompt };
      },
      parseStreamLine() {
        return [];
      },
    };
    let caught: unknown;
    try {
      await sc.run({
        cwd: root,
        agent,
        prompt: "unused",
        maxIterations: 1,
        completionSignal: [],
        idleTimeoutSeconds: 60,
        sandbox: noSandbox({ env: fixtureEnv(root, fake, "failure") }),
        branchStrategy: { type: "head" },
      });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeDefined();
    const msg = caught instanceof Error ? caught.message : String(caught);
    // Product seam: sandcastle surfaces non-zero agent exit as AgentError with code.
    expect(msg).toMatch(/exited with code 7|exit(?:ed)?(?:\s+with)?(?:\s+code)?\s*7|\b7\b/i);
    // Walk nested cause for structured exitCode when present.
    let node: unknown = caught;
    let sawSeven = /code 7/.test(msg);
    const seen = new Set<unknown>();
    while (node && typeof node === "object" && !seen.has(node)) {
      seen.add(node);
      const rec = node as {
        exitCode?: unknown;
        message?: unknown;
        cause?: unknown;
        error?: unknown;
      };
      if (rec.exitCode === 7) sawSeven = true;
      if (typeof rec.message === "string" && /code 7/.test(rec.message)) {
        sawSeven = true;
      }
      node = rec.cause ?? rec.error;
    }
    expect(sawSeven).toBe(true);
    if (existsSync(fake.pathLog)) {
      const promptPath = readFileSync(fake.pathLog, "utf8").trim();
      if (promptPath.length > 0) {
        expect(existsSync(promptPath)).toBe(false);
      }
    }
  }, 30_000);
});

describe("#1010 Sandcastle cancel seam — abort kills exec child (no-sandbox)", () => {
  const roots: string[] = [];
  afterEach(() => {
    for (const r of roots.splice(0)) {
      rmSync(r, { recursive: true, force: true });
    }
  });

  it("abort mid-run terminates the shell process and removes prompt temps", async () => {
    const root = mkdtempSync(join(tmpdir(), TMP_PREFIX));
    roots.push(root);
    initGitRepo(root);

    const fake = makeFakeAgent(root);
    const prompt = "cancel-me-now\n";
    const controller = new AbortController();

    const agent: sc.AgentProvider = {
      name: "cancel-probe",
      env: {},
      captureSessions: false,
      buildPrintCommand() {
        return {
          command: trapShellCommand(),
          stdin: prompt,
        };
      },
      parseStreamLine() {
        return [];
      },
    };

    const runPromise = sc.run({
      cwd: root,
      agent,
      prompt: "unused-inline-overridden-by-provider-stdin",
      maxIterations: 1,
      completionSignal: [],
      idleTimeoutSeconds: 60,
      sandbox: noSandbox({
        env: fixtureEnv(root, fake, "sleep"),
      }),
      branchStrategy: { type: "head" },
      signal: controller.signal,
    });

    // Wait until the fake agent has started (prompt materialised + pid logged).
    const deadline = Date.now() + 10_000;
    while (!existsSync(fake.started) && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 50));
    }
    expect(existsSync(fake.started)).toBe(true);
    expect(existsSync(fake.pathLog)).toBe(true);
    expect(existsSync(fake.pidLog)).toBe(true);
    const agentPid = Number.parseInt(readFileSync(fake.pidLog, "utf8").trim(), 10);
    expect(processAlive(agentPid)).toBe(true);
    const promptPath = readFileSync(fake.pathLog, "utf8").trim();
    expect(promptPath.length).toBeGreaterThan(0);
    expect(existsSync(promptPath)).toBe(true);

    controller.abort(new Error("test-abort-1010"));

    await expect(runPromise).rejects.toThrow(/test-abort-1010|abort/i);

    // Give process-group kill + EXIT trap a beat to finish.
    const cleanDeadline = Date.now() + 3_000;
    while (Date.now() < cleanDeadline && processAlive(agentPid)) {
      await new Promise((r) => setTimeout(r, 50));
    }
    await new Promise((r) => setTimeout(r, 200));

    // Process cleanup: agent shell (and its sleep child via process group) dead.
    expect(processAlive(agentPid)).toBe(false);

    // Temp cleanup: private prompt file must be gone (EXIT trap or kill).
    expect(existsSync(promptPath)).toBe(false);

    // No lingering mktemp-style files under the TMPDIR root that still hold the prompt.
    const leftovers = readdirSync(root).filter(
      (n) => n.startsWith("tmp.") || n.startsWith("tmp"),
    );
    for (const name of leftovers) {
      const full = join(root, name);
      if (existsSync(full)) {
        expect(readFileSync(full, "utf8")).not.toBe(prompt);
      }
    }
    // Prefer empty tmp leftovers after cancel.
    expect(leftovers).toEqual([]);
  }, 20_000);

  it("idle timeout fires fireExecAbort path — kills shell + prompt temps (no AbortController)", async () => {
    // P1: production cancel is not only explicit AbortController.abort — idle
    // timeout must also reach the shared exec seam. Sleep agent emits no
    // stream lines → idle timer fires → patched fireExecAbort → process group
    // kill + EXIT trap cleans prompt.
    //
    // idleTimeoutSeconds must clear sc.run worktree/setup before the timer is
    // meaningful for the agent; 2s is enough for no-sandbox start + short idle.
    const root = mkdtempSync(join(tmpdir(), TMP_PREFIX + "idle-"));
    roots.push(root);
    initGitRepo(root);

    const fake = makeFakeAgent(root);
    const prompt = "idle-timeout-cancel\n";
    const agent: sc.AgentProvider = {
      name: "idle-timeout-probe",
      env: {},
      captureSessions: false,
      buildPrintCommand() {
        return { command: trapShellCommand(), stdin: prompt };
      },
      parseStreamLine() {
        return [];
      },
    };

    // Attach handlers immediately so a fast FiberFailure is not "unhandled".
    const runOutcome = sc
      .run({
        cwd: root,
        agent,
        prompt: "unused",
        maxIterations: 1,
        completionSignal: [],
        idleTimeoutSeconds: 2,
        sandbox: noSandbox({
          env: fixtureEnv(root, fake, "sleep"),
        }),
        branchStrategy: { type: "head" },
      })
      .then(
        (value) => ({ ok: true as const, value }),
        (err: unknown) => ({ ok: false as const, err }),
      );

    const startDeadline = Date.now() + 15_000;
    while (!existsSync(fake.started) && Date.now() < startDeadline) {
      await new Promise((r) => setTimeout(r, 50));
    }
    expect(existsSync(fake.started)).toBe(true);
    const agentPid = Number.parseInt(
      readFileSync(fake.pidLog, "utf8").trim(),
      10,
    );
    expect(processAlive(agentPid)).toBe(true);
    const promptPath = readFileSync(fake.pathLog, "utf8").trim();
    expect(existsSync(promptPath)).toBe(true);

    const outcome = await runOutcome;
    expect(outcome.ok).toBe(false);
    if (outcome.ok) throw new Error("expected idle timeout rejection");
    const msg =
      outcome.err instanceof Error ? outcome.err.message : String(outcome.err);
    // AgentIdleTimeoutError surface (message varies slightly by sandcastle).
    expect(msg).toMatch(/idle|timeout/i);

    const cleanDeadline = Date.now() + 5_000;
    while (Date.now() < cleanDeadline && processAlive(agentPid)) {
      await new Promise((r) => setTimeout(r, 50));
    }
    await new Promise((r) => setTimeout(r, 200));

    expect(processAlive(agentPid)).toBe(false);
    expect(existsSync(promptPath)).toBe(false);
  }, 45_000);
});

describe("#1010 docker cancel (production-shaped, env-gated)", () => {
  const dockerOk =
    spawnSync("docker", ["info"], { encoding: "utf8" }).status === 0;
  const image =
    process.env.ORCHESTRATOR_TEST_IMAGE ?? "ming-orchestrator-coder:latest";
  const imageOk =
    dockerOk &&
    spawnSync("docker", ["image", "inspect", image], { encoding: "utf8" })
      .status === 0;

  // Gate at the it level so a missing image is an explicit skip (never a silent green).
  const skipReason = !dockerOk
    ? "docker daemon unavailable"
    : !imageOk
      ? `image ${image} missing (set ORCHESTRATOR_TEST_IMAGE or build profile image) — not silent-pass`
      : null;

  it.skipIf(skipReason !== null)(
    skipReason
      ? `abort kills docker-exec shell [skipped: ${skipReason}]`
      : "abort kills docker-exec shell inside a long-lived container",
    async () => {
      // Production shape: real docker provider handle + AbortSignal must
      // settle the host docker-exec Promise and leave no sleep grandchild
      // inside the reused container (pre-#1010: Promise abandoned, shell
      // lived on). Marker lives under agent $HOME (always writable).
      const { docker } = await import("@ai-hero/sandcastle/sandboxes/docker");
      const root = mkdtempSync(join(tmpdir(), TMP_PREFIX + "dock-"));
      try {
        // Defence in depth: never return early without skip/fail (must #1).
        const inspect = spawnSync("docker", ["image", "inspect", image], {
          encoding: "utf8",
        });
        if (inspect.status !== 0) {
          throw new Error(
            `#1010 docker cancel: image "${image}" disappeared after gate — refusing silent pass`,
          );
        }

        const provider = docker({ imageName: image }) as unknown as CreateProvider;
        const handle = await provider.create({
          worktreePath: "/home/agent/workspace",
          hostRepoPath: root,
          mounts: [],
          env: {},
        });
        try {
          const controller = new AbortController();
          const marker = "/tmp/sc-cancel-1010-live";
          const cmd =
            `prompt_file=$(mktemp) || exit $?; ` +
            `cleanup() { rm -f -- "$prompt_file" "${marker}"; }; ` +
            `trap cleanup EXIT; ` +
            `trap 'exit 129' HUP; trap 'exit 130' INT; trap 'exit 143' TERM; ` +
            `echo live > "${marker}"; ` +
            `echo x > "$prompt_file"; ` +
            `sleep 60`;

          const execPromise = handle.exec(cmd, {
            signal: controller.signal,
          });

          // Confirm the in-container marker exists before abort.
          const deadline = Date.now() + 15_000;
          let ready = false;
          while (Date.now() < deadline) {
            const check = await handle.exec(
              `test -f ${marker} && echo READY`,
              {},
            );
            if (check.stdout.includes("READY")) {
              ready = true;
              break;
            }
            await new Promise((r) => setTimeout(r, 100));
          }
          expect(ready).toBe(true);

          controller.abort(new Error("docker-abort-1010"));

          const settled = await Promise.race([
            execPromise.then(
              (r: { exitCode: number }) => ({
                kind: "ok" as const,
                code: r.exitCode,
              }),
              (e: unknown) => ({ kind: "err" as const, msg: String(e) }),
            ),
            new Promise<{ kind: "timeout" }>((r) =>
              setTimeout(() => r({ kind: "timeout" }), 8_000),
            ),
          ]);
          // Host docker-exec must settle (not hang abandoned).
          expect(settled.kind).not.toBe("timeout");

          // Allow TERM traps + child reaping (+ optional KILL pass) to finish.
          await new Promise((r) => setTimeout(r, 1200));

          // Token-tagged shell must be gone; grandchildren reaped; marker cleaned.
          const after = await handle.exec(
            `ps -eo args | grep SC_CANCEL_TOKEN | grep -v grep || true; ` +
              `ps -eo args | grep -F 'sleep 60' | grep -v grep || true; ` +
              `if test -f ${marker}; then echo MARKER_LIVE; else echo MARKER_GONE; fi`,
            {},
          );
          expect(after.stdout).not.toMatch(/SC_CANCEL_TOKEN/);
          expect(after.stdout).not.toMatch(/\bsleep 60\b/);
          expect(after.stdout).toContain("MARKER_GONE");
        } finally {
          await handle.close().catch(() => {});
        }
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    },
    90_000,
  );

  // Explicit companion: when docker is up but the image is missing, the suite
  // must not report a silent green for the production-shaped cancel case.
  it.skipIf(dockerOk && imageOk)(
    !dockerOk
      ? "docker image-missing gate (daemon unavailable — outer suite skipped)"
      : `refuses silent-pass when image ${image} is missing`,
    () => {
      if (!dockerOk) {
        // Daemon down: nothing to assert about image-missing silent-pass.
        expect(dockerOk).toBe(false);
        return;
      }
      // Docker is up and we reached this test ⇒ imageOk must be false, and
      // the production-shaped it above is skipIf-gated (not a silent pass).
      expect(imageOk).toBe(false);
      const inspect = spawnSync("docker", ["image", "inspect", image], {
        encoding: "utf8",
      });
      expect(inspect.status).not.toBe(0);
    },
  );
});

describe("#1010 cancel patch is installed on the sandcastle package", () => {
  it("dist carries the #1010 cancel marker after ensure", () => {
    // Resolve via file path (package exports omit package.json / bare entry).
    const pkgRoot = join(
      process.cwd(),
      "node_modules",
      "@ai-hero",
      "sandcastle",
    );
    const pkg = JSON.parse(
      readFileSync(join(pkgRoot, "package.json"), "utf8"),
    ) as { version: string };
    // Exact pin: package.json declares 0.12.0 (no caret) — needle shape is for this version.
    expect(pkg.version).toBe("0.12.0");

    const index = readFileSync(join(pkgRoot, "dist", "index.js"), "utf8");
    const dockerChunk = readFileSync(
      join(pkgRoot, "dist", "chunk-CP3TYXZA.js"),
      "utf8",
    );
    expect(index).toContain("#1010-sandcastle-cancel");
    expect(index).toContain("execAbortController");
    // Idle-timeout path must call fireExecAbort (P1 needle cannot rot).
    expect(index).toContain(
      'fireExecAbort(new AgentIdleTimeoutError({ message: "agent idle timeout"',
    );
    expect(dockerChunk).toContain("__scCancelWireAbortKill");
    expect(dockerChunk).toContain("detached: true");
    // Marker-bounded host-kill helper (S4) — not brace/indent strip alone.
    expect(dockerChunk).toContain("#1010-sandcastle-cancel:host-kill");
    expect(dockerChunk).toContain("#1010-sandcastle-cancel:host-kill-end");
    // nit: cancel token present on patched docker chunk
    expect(dockerChunk).toContain("SC_CANCEL_TOKEN");
    // should: in-container kill excludes self ($$) — dist holds escaped quotes
    expect(dockerChunk).toContain('[ \\"$p\\" = \\"$$\\" ]');
  });

  it("modelRegistry choke-point module loads without throwing (patch ensure path)", async () => {
    // Importing the registry must apply the cancel patch even if postinstall
    // was skipped — common import choke-point for backends that only pull types
    // or factories from modelRegistry first.
    await expect(import("../../src/modelRegistry.js")).resolves.toBeDefined();
  });
});
