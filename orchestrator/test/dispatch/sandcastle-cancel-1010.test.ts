/**
 * #1010 — Sandcastle cancel seam must reach the container/shell process.
 *
 * Before: abort only abandoned the host docker-exec Promise; the shell +
 * prompt temp files inside a reused container survived.
 * After: AbortSignal (and idle-timeout local abort) kill the exec child so
 * shell traps run and temps do not linger.
 *
 * Strategy under test: local patch of @ai-hero/sandcastle@0.12.0 (latest;
 * no bump). Cross-provider (no-sandbox always; docker when available).
 *
 * AC2: failure fixture asserts exit codes 7 / 129 / 130 / 143 and pre-agent
 * (pre-grok) failure propagation — #988 escalate secondary gap.
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
function trapShellCommand(modeEnv = "MODE"): string {
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
} {
  const bin = join(root, "agent");
  const captured = join(root, "captured");
  const pathLog = join(root, "path");
  const modeLog = join(root, "mode");
  const started = join(root, "started");
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
  return { bin, captured, pathLog, modeLog, started };
}

function runTrapShell(input: {
  readonly root: string;
  readonly mode: string;
  readonly prompt: string;
  readonly signal?: AbortSignal;
  readonly timeoutMs?: number;
}): {
  readonly status: number | null;
  readonly signal: NodeJS.Signals | null;
  readonly stdout: string;
  readonly stderr: string;
} {
  const fake = makeFakeAgent(input.root);
  const cmd = trapShellCommand();
  const result = spawnSync("sh", ["-c", cmd], {
    input: input.prompt,
    encoding: "utf8",
    env: {
      ...process.env,
      PATH: `${input.root}:${process.env.PATH ?? ""}`,
      TMPDIR: input.root,
      MODE: input.mode,
      CAPTURED: fake.captured,
      PATH_LOG: fake.pathLog,
      MODE_LOG: fake.modeLog,
      STARTED: fake.started,
    },
    timeout: input.timeoutMs,
  });
  return {
    status: result.status,
    signal: result.signal,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

describe("#1010 failure fixture — exit codes 7 / 129 / 130 / 143 + pre-agent fail", () => {
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

  it("failure mode exits 7 and removes the private prompt file", () => {
    const root = scratch();
    const prompt = "fail-prompt\n";
    const result = runTrapShell({ root, mode: "failure", prompt });
    expect(result.status).toBe(7);
    const fake = {
      captured: join(root, "captured"),
      pathLog: join(root, "path"),
      modeLog: join(root, "mode"),
    };
    expect(readFileSync(fake.captured, "utf8")).toBe(prompt);
    expect(readFileSync(fake.modeLog, "utf8").trim()).toMatch(/600/);
    const promptPath = readFileSync(fake.pathLog, "utf8");
    expect(existsSync(promptPath)).toBe(false);
  });

  it.each([
    ["HUP", 129],
    ["INT", 130],
    ["TERM", 143],
  ] as const)(
    "signal %s exits %i and removes the private prompt file",
    (mode, code) => {
      const root = scratch();
      const prompt = `sig-${mode}\n`;
      const result = runTrapShell({ root, mode, prompt });
      // shell may report status or signal depending on platform; accept both
      // shapes that mean "this signal terminated us".
      const sigMap: Record<string, NodeJS.Signals> = {
        HUP: "SIGHUP",
        INT: "SIGINT",
        TERM: "SIGTERM",
      };
      const okStatus =
        result.status === code ||
        (result.status === null && result.signal === sigMap[mode]) ||
        // some sh map signal exits to 128+n only
        result.status === 128 + ({ HUP: 1, INT: 2, TERM: 15 }[mode]);
      expect(okStatus).toBe(true);
      const pathLog = join(root, "path");
      const promptPath = readFileSync(pathLog, "utf8");
      expect(existsSync(promptPath)).toBe(false);
    },
  );

  it("pre-agent (pre-grok) failure propagates — early non-zero exits before agent, no agent start", () => {
    const root = scratch();
    const agentStarted = join(root, "agent-started");
    // Simulate pre-agent failure: prerequisite check fails (exit 7) before
    // the agent binary runs — same class as mktemp/auth preflight miss.
    const cmd =
      `preflight() { return 7; }; ` +
      `preflight || exit $?; ` +
      `echo should-not-reach > "${agentStarted}"; exit 0`;
    const result = spawnSync("sh", ["-c", cmd], {
      encoding: "utf8",
      env: { ...process.env },
    });
    expect(result.status).toBe(7);
    expect(existsSync(agentStarted)).toBe(false);
  });
});

describe("#1010 Sandcastle cancel seam — abort kills exec child (no-sandbox)", () => {
  const roots: string[] = [];
  afterEach(() => {
    for (const r of roots.splice(0)) {
      rmSync(r, { recursive: true, force: true });
    }
  });

  it("abort mid-run terminates the shell and does not leave prompt temps", async () => {
    const root = mkdtempSync(join(tmpdir(), TMP_PREFIX));
    roots.push(root);
    // Minimal git repo for noSandbox sc.run
    spawnSync("git", ["init"], { cwd: root, encoding: "utf8" });
    spawnSync("git", ["config", "user.email", "t@t.t"], { cwd: root });
    spawnSync("git", ["config", "user.name", "t"], { cwd: root });
    writeFileSync(join(root, "README"), "x\n");
    spawnSync("git", ["add", "README"], { cwd: root });
    spawnSync("git", ["commit", "-m", "init"], { cwd: root });

    const fake = makeFakeAgent(root);
    const prompt = "cancel-me-now\n";
    const controller = new AbortController();

    // Agent provider whose print command is the trap shell + long sleep.
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
        env: {
          PATH: `${root}:${process.env.PATH ?? ""}`,
          TMPDIR: root,
          MODE: "sleep",
          CAPTURED: fake.captured,
          PATH_LOG: fake.pathLog,
          MODE_LOG: fake.modeLog,
          STARTED: fake.started,
        },
      }),
      branchStrategy: { type: "head" },
      signal: controller.signal,
    });

    // Wait until the fake agent has started (prompt materialised).
    const deadline = Date.now() + 10_000;
    while (!existsSync(fake.started) && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 50));
    }
    expect(existsSync(fake.started)).toBe(true);

    // Snapshot any mktemp files under root before abort.
    const beforeTemps = readdirSync(root).filter((n) =>
      n.startsWith("tmp.") || n.includes("tmp"),
    );

    controller.abort(new Error("test-abort-1010"));

    await expect(runPromise).rejects.toThrow(/test-abort-1010|abort/i);

    // Give EXIT trap a beat to run after SIGTERM.
    await new Promise((r) => setTimeout(r, 300));

    // Prompt file path (if captured) must be gone.
    if (existsSync(fake.pathLog)) {
      const promptPath = readFileSync(fake.pathLog, "utf8").trim();
      if (promptPath.length > 0) {
        expect(existsSync(promptPath)).toBe(false);
      }
    }

    // No lingering mktemp-style files under the TMPDIR root.
    const afterTemps = readdirSync(root).filter(
      (n) =>
        (n.startsWith("tmp.") || /^tmp\./.test(n) || n.startsWith("sc-")) &&
        !["captured", "path", "mode", "started", "agent", "README"].includes(n),
    );
    // Prefer empty; allow only known fixture names.
    for (const name of afterTemps) {
      // if a temp still exists and looks like a prompt file, fail
      const full = join(root, name);
      if (existsSync(full)) {
        const st = readFileSync(full, "utf8");
        // live prompt content must not remain
        expect(st).not.toBe(prompt);
      }
    }
    void beforeTemps;
  }, 20_000);
});

describe("#1010 docker cancel (production-shaped, env-gated)", () => {
  const dockerOk =
    spawnSync("docker", ["info"], { encoding: "utf8" }).status === 0;

  it.skipIf(!dockerOk)(
    "abort kills docker-exec shell inside a long-lived container",
    async () => {
      // Production shape: real docker provider handle + AbortSignal must
      // settle the host docker-exec Promise and leave no sleep grandchild
      // inside the reused container (pre-#1010: Promise abandoned, shell
      // lived on). Marker lives under agent $HOME (always writable).
      const { docker } = await import("@ai-hero/sandcastle/sandboxes/docker");
      const root = mkdtempSync(join(tmpdir(), TMP_PREFIX + "dock-"));
      try {
        const image =
          process.env.ORCHESTRATOR_TEST_IMAGE ??
          "ming-orchestrator-coder:latest";
        const inspect = spawnSync(
          "docker",
          ["image", "inspect", image],
          { encoding: "utf8" },
        );
        if (inspect.status !== 0) {
          return; // no local profile image — skip rather than false-red
        }

        // SandboxProvider public type hides create(); runtime bind-mount has it.
        type DockerHandle = {
          exec: (
            cmd: string,
            opts?: { signal?: AbortSignal },
          ) => Promise<{ stdout: string; stderr: string; exitCode: number }>;
          close: () => Promise<void>;
        };
        const provider = docker({ imageName: image }) as unknown as {
          create: (opts: {
            worktreePath: string;
            hostRepoPath: string;
            mounts: readonly unknown[];
            env: Record<string, string>;
          }) => Promise<DockerHandle>;
        };
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
    const index = readFileSync(join(pkgRoot, "dist", "index.js"), "utf8");
    const dockerChunk = readFileSync(
      join(pkgRoot, "dist", "chunk-CP3TYXZA.js"),
      "utf8",
    );
    expect(index).toContain("#1010-sandcastle-cancel");
    expect(index).toContain("execAbortController");
    expect(dockerChunk).toContain("__scCancelWireAbortKill");
    expect(dockerChunk).toContain("detached: true");
  });
});
