/**
 * #807 — grok-build pool provider: custom AgentProvider + registry wiring.
 * Route smoke is bare-ping only (#884); old bash/nonce-file evidence helpers are gone.
 */

import { spawn } from "node:child_process";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  createGrokStreamParser,
  grokAgent,
  shellEscape,
} from "../../src/grokAgent.js";
import {
  POOL_DISPATCH_BINDINGS,
  agentForSlug,
  resolveModelSlug,
  resolveModelSlugForPool,
} from "../../src/modelRegistry.js";
import { barePingArgv, barePingNonceSatisfied } from "../../src/realBackend.js";
import { routeSmokeEntries, resolveRouteModels } from "../../src/modelRoutes.js";

const transportDirs: string[] = [];
afterEach(() => {
  for (const dir of transportDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function transportDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  transportDirs.push(dir);
  return dir;
}

/** Isolated env for transport shells — never inherit test-harness hold/path vars. */
function transportEnv(
  binDir: string,
  staging: string,
  pathOut: string,
  childPidOut: string,
  extra: NodeJS.ProcessEnv = {},
): NodeJS.ProcessEnv {
  return {
    ...process.env,
    PATH: `${binDir}:${process.env.PATH ?? ""}`,
    TMPDIR: staging,
    GROK_PROMPT_PATH_OUT: pathOut,
    GROK_CHILD_PID_OUT: childPidOut,
    // Harness-only: default off so a polluted parent env cannot hang normal-exit cases.
    GROK_HOLD_OPEN: "0",
    GROK_EXIT_CODE: "0",
    ...extra,
  };
}

function fakeGrokPath(binDir: string): string {
  const path = join(binDir, "grok");
  writeFileSync(
    path,
    "#!/bin/sh\ncat \"$2\"\nprintf '%s' \"$2\" > \"$GROK_PROMPT_PATH_OUT\"\nprintf '%s' \"$$\" > \"$GROK_CHILD_PID_OUT\"\nif [ \"${GROK_HOLD_OPEN:-0}\" = 1 ]; then exec sleep 30; fi\nexit \"${GROK_EXIT_CODE:-0}\"\n",
    "utf8",
  );
  chmodSync(path, 0o755);
  return path;
}

describe("#807 grokAgent AgentProvider", () => {
  it("builds a headless grok command with a materialized stdin prompt (not sc.pi)", () => {
    const agent = grokAgent("grok-4.5");
    expect(agent.name).toBe("grok");
    const cmd = agent.buildPrintCommand({
      prompt: "echo OK",
      dangerouslySkipPermissions: true,
    });
    expect(cmd.command).toContain("grok ");
    expect(cmd.command).toContain("prompt_file=$(mktemp)");
    expect(cmd.command).toContain("cat > \"$prompt_file\"");
    expect(cmd.command).toContain("--prompt-file \"$prompt_file\"");
    expect(cmd.command).toContain("trap cleanup_prompt EXIT");
    expect(cmd.command).toContain("trap 'relay_signal TERM' TERM");
    expect(cmd.command).toContain("--output-format streaming-json");
    expect(cmd.command).toContain("--always-approve");
    expect(cmd.command).toContain("-m grok-4.5");
    expect(cmd.command).not.toMatch(/\blogin\b/);
    expect(cmd.command).not.toMatch(/--device-auth|--device-code/);
    expect(cmd.command).not.toMatch(/\bpi\b/);
    expect(cmd.stdin).toBe("echo OK");
  });

  it("stages a large prompt byte-for-byte and removes the prompt file on normal exit", async () => {
    const root = transportDir("grok-transport-normal-");
    const bin = join(root, "bin");
    const staging = join(root, "staging");
    const pathOut = join(root, "prompt-path");
    const childPidOut = join(root, "child-pid");
    mkdirSync(bin);
    mkdirSync(staging);
    fakeGrokPath(bin);
    // >128KB payload — the reason worker transport stages to a file, not argv.
    const prompt = `start-${"明".repeat(70_000)}-end`;
    const built = grokAgent("grok-4.5").buildPrintCommand({
      prompt,
      dangerouslySkipPermissions: true,
    });
    const result = await new Promise<{ stdout: string; code: number | null }>((resolve) => {
      const child = spawn("sh", ["-c", built.command], {
        env: transportEnv(bin, staging, pathOut, childPidOut),
        stdio: ["pipe", "pipe", "pipe"],
      });
      let stdout = "";
      child.stdout.setEncoding("utf8").on("data", (chunk) => {
        stdout += chunk;
      });
      child.on("close", (code) => resolve({ stdout, code }));
      child.stdin.end(built.stdin);
    });
    expect(result.code).toBe(0);
    expect(result.stdout).toBe(prompt);
    expect(readFileSync(pathOut, "utf8")).toMatch(/^.+$/);
    expect(readdirSync(staging)).toEqual([]);
  });

  it("returns a Grok failure code after reaping the child and removing the staged prompt", async () => {
    const root = transportDir("grok-transport-failure-");
    const bin = join(root, "bin");
    const staging = join(root, "staging");
    const pathOut = join(root, "prompt-path");
    const childPidOut = join(root, "child-pid");
    mkdirSync(bin);
    mkdirSync(staging);
    fakeGrokPath(bin);
    const built = grokAgent("grok-4.5").buildPrintCommand({
      prompt: "failing worker context",
      dangerouslySkipPermissions: true,
    });
    const child = spawn("sh", ["-c", built.command], {
      env: transportEnv(bin, staging, pathOut, childPidOut, {
        GROK_EXIT_CODE: "23",
      }),
      stdio: ["pipe", "ignore", "ignore"],
    });
    const pid = child.pid!;
    let grokPid: number | undefined;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      const closed = new Promise<{
        code: number | null;
        signal: NodeJS.Signals | null;
      }>((resolve) => {
        child.once("close", (code, signal) => resolve({ code, signal }));
      });
      child.stdin.end(built.stdin);
      const result = await Promise.race([
        closed,
        new Promise<never>((_resolve, reject) => {
          timeout = setTimeout(
            () =>
              reject(new Error("nonzero Grok worker did not exit within 5s")),
            5_000,
          );
        }),
      ]);
      grokPid = Number(readFileSync(childPidOut, "utf8"));
      expect(result).toEqual({ code: 23, signal: null });
      expect(readdirSync(staging)).toEqual([]);
      expect(() => process.kill(grokPid!, 0)).toThrow();
    } finally {
      if (timeout !== undefined) clearTimeout(timeout);
      for (const cleanupPid of [pid, grokPid]) {
        if (cleanupPid === undefined) continue;
        try {
          process.kill(cleanupPid, "SIGKILL");
        } catch {
          // Expected after the wrapper has reaped the failed Grok child.
        }
      }
    }
  });

  it.each(["SIGHUP", "SIGINT", "SIGTERM"] as const)(
    "removes the staged prompt and preserves %s worker interruption semantics",
    async (signal) => {
      const root = transportDir("grok-transport-term-");
      const bin = join(root, "bin");
      const staging = join(root, "staging");
      const pathOut = join(root, "prompt-path");
      const childPidOut = join(root, "child-pid");
      mkdirSync(bin);
      mkdirSync(staging);
      fakeGrokPath(bin);
      const built = grokAgent("grok-4.5").buildPrintCommand({
        prompt: "sensitive worker context",
        dangerouslySkipPermissions: true,
      });
      const child = spawn("sh", ["-c", built.command], {
        env: transportEnv(bin, staging, pathOut, childPidOut, {
          GROK_HOLD_OPEN: "1",
        }),
        stdio: ["pipe", "ignore", "ignore"],
      });
      const sentinel = spawn("sleep", ["30"], { stdio: "ignore" });
      child.stdin.end(built.stdin);
      const pid = child.pid!;
      const sentinelPid = sentinel.pid!;
      let grokPid: number | undefined;
      let timeout: ReturnType<typeof setTimeout> | undefined;
      try {
        await expect
          .poll(() => readFileSync(pathOut, "utf8"), { timeout: 5_000 })
          .toMatch(/^.+$/);
        grokPid = Number(readFileSync(childPidOut, "utf8"));
        const closed = new Promise<{
          code: number | null;
          signal: NodeJS.Signals | null;
        }>((resolve) => {
          child.once("close", (code, closeSignal) => {
            resolve({ code, signal: closeSignal });
          });
        });
        process.kill(pid, signal);
        const result = await Promise.race([
          closed,
          new Promise<never>((_resolve, reject) => {
            timeout = setTimeout(
              () => reject(new Error(`${signal} worker group did not exit within 5s`)),
              5_000,
            );
          }),
        ]);
        expect(result).toEqual({ code: null, signal });
        expect(readdirSync(staging)).toEqual([]);
        for (const endedPid of [pid, grokPid]) {
          await expect
            .poll(() => {
              try {
                process.kill(endedPid, 0);
                return true;
              } catch {
                return false;
              }
            }, { timeout: 2_000 })
            .toBe(false);
        }
        expect(() => process.kill(sentinelPid, 0)).not.toThrow();
      } finally {
        if (timeout !== undefined) clearTimeout(timeout);
        try {
          process.kill(pid, "SIGKILL");
        } catch {
          // Expected once the process group has exited; failure cleanup only.
        }
        if (grokPid !== undefined) {
          try {
            process.kill(grokPid, "SIGKILL");
          } catch {
            // Expected once relay has reaped the Grok child.
          }
        }
        try {
          process.kill(sentinelPid, "SIGKILL");
        } catch {
          // Sentinel cleanup after the survival assertion.
        }
      }
    },
    10_000,
  );

  it("emits text (not result) per chunk, then ONE accumulated result on end", () => {
    // #899 hotfix / #928: result.stdout (typed envelope / sidecar extraction
    // after clean exit) reads the LAST result event's payload. Per-chunk result
    // events made that a last-chunk roulette — the coder receipt lived in
    // earlier chunks and escalate cargo degraded to committed:false.
    const parse = createGrokStreamParser();
    expect(
      parse('{"type":"text","data":"<coder>{\\"committed\\":false}</coder>\\n"}'),
    ).toEqual([{ type: "text", text: '<coder>{"committed":false}</coder>\n' }]);
    expect(parse('{"type":"text","data":"trailing chatter"}')).toEqual([
      { type: "text", text: "trailing chatter" },
    ]);
    expect(
      parse('{"type":"end","stopReason":"EndTurn","sessionId":"sess-1"}'),
    ).toEqual([
      { type: "session_id", sessionId: "sess-1" },
      {
        type: "result",
        result: '<coder>{"committed":false}</coder>\ntrailing chatter',
      },
    ]);
  });

  it("resets the accumulator after end, so a second iteration starts clean", () => {
    const parse = createGrokStreamParser();
    parse('{"type":"text","data":"iteration one"}');
    parse('{"type":"end","sessionId":"sess-1"}');
    parse('{"type":"text","data":"iteration two"}');
    expect(parse('{"type":"end","sessionId":"sess-2"}')).toEqual([
      { type: "session_id", sessionId: "sess-2" },
      { type: "result", result: "iteration two" },
    ]);
  });

  it("falls back to the end event's own text only when no chunks accumulated", () => {
    const empty = createGrokStreamParser();
    expect(empty('{"type":"end","sessionId":"s","text":"end-text"}')).toEqual([
      { type: "session_id", sessionId: "s" },
      { type: "result", result: "end-text" },
    ]);

    const buffered = createGrokStreamParser();
    buffered('{"type":"text","data":"accumulated wins"}');
    expect(
      buffered('{"type":"end","sessionId":"s","text":"end-text"}'),
    ).toEqual([
      { type: "session_id", sessionId: "s" },
      { type: "result", result: "accumulated wins" },
    ]);
  });

  it("emits no result on an end with neither chunks nor text (raw-stdout fallback)", () => {
    const parse = createGrokStreamParser();
    expect(parse('{"type":"end","stopReason":"EndTurn"}')).toEqual([]);
  });

  it("gives each provider instance its own accumulator", () => {
    const provider = grokAgent("grok-4.5");
    const other = grokAgent("grok-4.5");
    provider.parseStreamLine!('{"type":"text","data":"mine"}');
    other.parseStreamLine!('{"type":"text","data":"theirs"}');
    expect(
      provider.parseStreamLine!('{"type":"end","sessionId":"a"}'),
    ).toEqual([
      { type: "session_id", sessionId: "a" },
      { type: "result", result: "mine" },
    ]);
  });

  it("maps run_terminal_cmd tool events to bash when present", () => {
    const parse = createGrokStreamParser();
    expect(
      parse('{"type":"tool_call","name":"run_terminal_cmd","args":"echo OK"}'),
    ).toEqual([{ type: "tool_call", name: "bash", args: "echo OK" }]);
  });

  it("shellEscape quotes unsafe tokens", () => {
    expect(shellEscape("grok-4.5")).toBe("grok-4.5");
    expect(shellEscape("a b")).toBe("'a b'");
  });
});

describe("#807 modelRegistry grok-build wiring", () => {
  it("binds the grok-build pool to the grok provider (not pi)", () => {
    expect(POOL_DISPATCH_BINDINGS["grok-build"]).toBe("grok");
    expect(resolveModelSlugForPool("grok-4.5", "grok-build")).toEqual({
      provider: "grok",
      model: "grok-4.5",
    });
    // #905: default registry is SuperGrok CLI; no cursor transit.
    expect(resolveModelSlug("grok-4.5").provider).toBe("grok");
  });

  it("agentForSlug(pool=grok-build) yields the grok CLI provider", () => {
    const agent = agentForSlug("grok-4.5", "grok-build");
    expect(agent.name).toBe("grok");
  });
});

describe("#807 grok bare-ping smoke wiring", () => {
  it("builds a one-shot grok CLI bare-ping argv (no docker/tool loop)", () => {
    const built = barePingArgv("grok", "grok-4.5", "Reply with exactly: nonce-807");
    expect(built.file).toBe("grok");
    expect(built.args).toContain("-p");
    expect(built.args).toContain("Reply with exactly: nonce-807");
    expect(built.input).toBeUndefined();
    expect(built.args).toContain("-m");
    expect(built.args).toContain("grok-4.5");
  });

  it("accepts full-line nonce stdout and rejects bare chatter", () => {
    expect(barePingNonceSatisfied("nonce-807\n", "nonce-807")).toBe(true);
    expect(barePingNonceSatisfied("nonce-807", "nonce-807")).toBe(true);
    expect(barePingNonceSatisfied("OK", "nonce-807")).toBe(false);
    expect(barePingNonceSatisfied("prefix-nonce-807-suffix", "nonce-807")).toBe(
      false,
    );
  });

  it("keeps the model slug independent from its billing pool", () => {
    const route = resolveRouteModels("normal", { coder: "grok-4.5" });
    const keys = routeSmokeEntries(route).map((e) => e.key);
    expect(keys.some((k) => k.includes("grok-4.5"))).toBe(true);
    expect(() => resolveModelSlug("grok-4.5-build")).toThrow(/unknown model slug/i);
  });

  // Container grok pin assert lives only in grok-mid-run-auth-964.test.ts (#964 AC /
  // CR R1 N2: single canonical pin test; string-match of Containerfile is enough).
});
