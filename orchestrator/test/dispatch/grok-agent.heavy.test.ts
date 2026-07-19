import {
  spawn,
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  tmpdir,
  join,
  afterEach,
  describe,
  expect,
  it,
  createGrokStreamParser,
  grokAgent,
  shellEscape,
  POOL_DISPATCH_BINDINGS,
  agentForSlug,
  resolveModelSlug,
  resolveModelSlugForPool,
  barePingArgv,
  barePingNonceSatisfied,
  routeSmokeEntries,
  resolveRouteModels,
  transportDirs,
  transportDir,
  transportEnv,
  fakeGrokPath,
} from "./grok-agent.shared.js";

afterEach(() => {
  for (const dir of transportDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

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

  it("does not start Grok when prompt staging fails", async () => {
    const root = transportDir("grok-transport-staging-failure-");
    const bin = join(root, "bin");
    const staging = join(root, "staging");
    const pathOut = join(root, "prompt-path");
    const childPidOut = join(root, "child-pid");
    mkdirSync(bin);
    mkdirSync(staging);
    fakeGrokPath(bin);
    const failingCat = join(bin, "cat");
    writeFileSync(
      failingCat,
      "#!/bin/sh\necho 'simulated prompt staging write failure' >&2\nexit 42\n",
      "utf8",
    );
    chmodSync(failingCat, 0o755);
    const built = grokAgent("grok-4.5").buildPrintCommand({
      prompt: "must not reach Grok",
      dangerouslySkipPermissions: true,
    });
    const result = await new Promise<{
      code: number | null;
      stderr: string;
    }>((resolve) => {
      const child = spawn("sh", ["-c", built.command], {
        env: transportEnv(bin, staging, pathOut, childPidOut),
        stdio: ["pipe", "ignore", "pipe"],
      });
      let stderr = "";
      child.stderr.setEncoding("utf8").on("data", (chunk) => {
        stderr += chunk;
      });
      child.on("close", (code) => resolve({ code, stderr }));
      child.stdin.end(built.stdin);
    });
    expect(result.code).toBe(42);
    expect(result.stderr).toContain("simulated prompt staging write failure");
    expect(() => readFileSync(pathOut, "utf8")).toThrow();
    expect(readdirSync(staging)).toEqual([]);
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
