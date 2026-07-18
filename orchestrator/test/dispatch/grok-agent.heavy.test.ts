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

});
