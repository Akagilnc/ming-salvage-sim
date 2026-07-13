/**
 * #684 — monitor handles atomically produced at dispatch; judge/kill only via handle.
 */

import { spawn } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  dispatchWorkerWithMonitor,
  resolveWorkerMonitorIdleThresholdMs,
} from "../../src/dispatchWorker.js";
import {
  buildCliMonitorSpawnSpec,
  isMissingMonitorSidecarResult,
  workerResultFromMonitorSidecar,
} from "../../src/cliMonitorHooks.js";
import { RealBackend } from "../../src/realBackend.js";
import { RealFamilyBackend } from "../../src/family/realFamilyBackend.js";
import {
  collectPidTree,
  dispatchMonitoredCliWorker,
  hasCompletionSignalInLog,
  instanceMatchesHandle,
  isWorkerAlive,
  isWorkerIdle,
  killWorkerTree,
  monitorHandleFromLedger,
  pidSafeToSignal,
  poolIdForWorker,
  readLogActivity,
  validateMonitorHandle,
  type WorkerMonitorDeps,
} from "../../src/workerMonitor.js";
import type {
  Backend,
  DispatchContext,
  PersistentLedgerEntry,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

function sleepWorker(
  logDir: string,
  poolId: string,
  signal: string,
  stepId: string,
): ReturnType<typeof dispatchMonitoredCliWorker> {
  return dispatchMonitoredCliWorker({
    command: process.platform === "win32" ? "ping" : "sleep",
    args: process.platform === "win32" ? ["-n", "600"] : ["600"],
    logDir,
    poolId,
    completionSignal: signal,
    stepId,
    logBasename: `${stepId}.log`,
    readInstanceId: () => `test-instance-${stepId}`,
  });
}

function injectedDeps(handle: WorkerMonitorHandle): WorkerMonitorDeps {
  return {
    isPidAlive: (pid) => {
      try {
        process.kill(pid, 0);
        return true;
      } catch {
        return false;
      }
    },
    listChildPids: () => [],
    readInstanceId: () => handle.instanceId,
    killPid: (pid, signal) => process.kill(pid, signal),
    sleepMs: async (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  };
}

function baseHandle(
  overrides: Partial<WorkerMonitorHandle> & Pick<WorkerMonitorHandle, "pid" | "logPath">,
): WorkerMonitorHandle {
  return {
    poolId: "grok/composer",
    completionSignal: "SHIP_STEP_COMPLETE",
    stepId: "S7",
    dispatchedAt: new Date().toISOString(),
    instanceId: "test-instance",
    ...overrides,
  };
}

describe("#684 worker monitor handles", () => {
  it("uses a higher default idle tier for Claude workers and a valid env override", () => {
    const codex = {
      id: "S5",
      kind: "coder",
      role: "coder",
      host: "codex",
      session: "fresh",
      contextRetention: "retain",
      skill: "/tdd",
      promptFile: "coder.md",
      completionSignal: "CODER_STEP_COMPLETE",
      maxIter: 1,
      model: "gpt-5.6-terra",
      soul: "coder",
      toolchain: [],
    } satisfies WorkerSpec;
    const claude = { ...codex, host: "claude", model: "sonnet" } satisfies WorkerSpec;

    expect(resolveWorkerMonitorIdleThresholdMs(codex, undefined)).toBe(10 * 60 * 1000);
    expect(resolveWorkerMonitorIdleThresholdMs(claude, undefined)).toBe(30 * 60 * 1000);
    expect(resolveWorkerMonitorIdleThresholdMs(claude, "45")).toBe(45 * 1000);
    expect(resolveWorkerMonitorIdleThresholdMs(codex, "0")).toBe(10 * 60 * 1000);
    expect(resolveWorkerMonitorIdleThresholdMs(claude, "not-a-number")).toBe(30 * 60 * 1000);
  });

  it("still kills a worker that exceeds the env-overridden idle tier", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-808-idle-kill-"));
    vi.stubEnv("ORCHESTRATOR_WORKER_IDLE_SECONDS", "1");
    try {
      const spec = {
        id: "S5",
        kind: "coder",
        role: "coder",
        host: "claude",
        session: "fresh",
        contextRetention: "retain",
        skill: "/tdd",
        promptFile: "coder.md",
        completionSignal: "CODER_STEP_COMPLETE",
        maxIter: 1,
        model: "sonnet",
        soul: "coder",
        toolchain: [],
      } satisfies WorkerSpec;
      const backend = {
        resolveCliMonitorDispatch: () => ({
          command: "sleep",
          args: ["600"],
          logDir: dir,
          poolId: poolIdForWorker(spec),
          completionSignal: spec.completionSignal,
          stepId: spec.id,
          readInstanceId: () => "orch-808-test-instance",
        }),
        awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        }),
        handleMonitoredWorkerIdle: async () => "hang" as const,
      } as unknown as Backend;

      await expect(
        dispatchWorkerWithMonitor(backend, spec, {}, undefined, {
          pollIntervalMs: 1,
          monitorDeps: {
            readInstanceId: () => "orch-808-test-instance",
            listChildPids: () => [],
            readParentPid: () => undefined,
            statLog: () => ({ sizeBytes: 0, mtimeMs: Date.now() - 1_001 }),
            sleepMs: async () => {},
          },
        }),
      ).rejects.toThrow("monitored worker idle hang: S5");
    } finally {
      vi.unstubAllEnvs();
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("keeps a failed sidecar whose error mentions the old fallback prose", () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-sidecar-collision-"));
    try {
      const resultPath = join(dir, "S2.result.json");
      const reason =
        "provider failed without a WorkerResult sidecar after its own upload step";
      writeFileSync(resultPath, JSON.stringify({ kind: "failed", reason }), "utf8");

      const result = workerResultFromMonitorSidecar(
        baseHandle({ pid: process.pid, logPath: join(dir, "S2.log"), resultPath }),
        1,
      );

      expect(result).toEqual({ kind: "failed", reason });
      expect(isMissingMonitorSidecarResult(result)).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("exit 0 without a usable sidecar is retry telemetry, not malformed terminal input", () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-826-sidecar-"));
    try {
      const result = workerResultFromMonitorSidecar(
        baseHandle({
          pid: process.pid,
          logPath: join(dir, "S2.log"),
          resultPath: join(dir, "S2.result.json"),
        }),
        0,
      );

      expect(result).toMatchObject({ kind: "failed" });
      expect(isMissingMonitorSidecarResult(result)).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("dispatchMonitoredCliWorker atomically returns pid/log/pool/signal/instance handle", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-dispatch-"));
    try {
      const { handle, child } = await sleepWorker(dir, "grok/composer", "CODER_STEP_COMPLETE", "S2");
      expect(handle.pid).toBe(child.pid);
      expect(handle.pid).toBeGreaterThan(0);
      expect(handle.logPath).toBe(join(dir, "S2.log"));
      expect(existsSync(handle.logPath)).toBe(true);
      expect(handle.poolId).toBe("grok/composer");
      expect(handle.completionSignal).toBe("CODER_STEP_COMPLETE");
      expect(handle.stepId).toBe("S2");
      expect(handle.dispatchedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
      expect(typeof handle.instanceId).toBe("string");
      expect(handle.instanceId.length).toBeGreaterThan(0);
      expect(validateMonitorHandle(handle)).toBe(true);
      expect(isWorkerAlive(handle, injectedDeps(handle))).toBe(true);
      await killWorkerTree(handle, injectedDeps(handle));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("readLogActivity and isWorkerIdle judge progress only from the handle log", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-idle-"));
    try {
      const logPath = join(dir, "worker.log");
      writeFileSync(logPath, "line1\n", "utf8");
      const handle = baseHandle({ pid: process.pid, logPath });
      const first = readLogActivity(handle);
      expect(first).not.toBeUndefined();
      expect(first!.sizeBytes).toBeGreaterThan(0);
      expect(first!.mtimeMs).toBeGreaterThan(0);

      await new Promise((resolve) => setTimeout(resolve, 20));
      writeFileSync(logPath, "line1\nline2\n", "utf8");
      const second = readLogActivity(handle);
      expect(second!.sizeBytes).toBeGreaterThan(first!.sizeBytes);
      expect(isWorkerIdle(handle, 60_000, first!)).toBe(false);

      const stale = readLogActivity(handle);
      expect(isWorkerIdle(handle, 0, stale!)).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("missing log file is NOT idle — no evidence must not trigger hang kill", () => {
    const handle = baseHandle({
      pid: process.pid,
      logPath: join(tmpdir(), `orch-684-missing-${Date.now()}.log`),
    });
    expect(existsSync(handle.logPath)).toBe(false);
    expect(readLogActivity(handle)).toBeUndefined();
    // Previous snapshot is irrelevant: without a log there is no evidence of idleness.
    expect(
      isWorkerIdle(handle, 0, { sizeBytes: 0, mtimeMs: 0 }),
    ).toBe(false);
    expect(
      isWorkerIdle(handle, 60_000, { sizeBytes: 100, mtimeMs: Date.now() - 120_000 }),
    ).toBe(false);
  });

  it("hasCompletionSignalInLog detects the expected completion signal in handle log", () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-signal-"));
    try {
      const logPath = join(dir, "worker.log");
      const handle = baseHandle({ pid: 1, logPath });
      writeFileSync(logPath, "working...\n", "utf8");
      expect(hasCompletionSignalInLog(handle)).toBe(false);
      writeFileSync(logPath, "working...\nVERIFY_STEP_COMPLETE\n", "utf8");
      // completion signal on this handle is SHIP_STEP_COMPLETE — still false
      expect(hasCompletionSignalInLog(handle)).toBe(false);
      writeFileSync(logPath, "working...\nSHIP_STEP_COMPLETE\n", "utf8");
      expect(hasCompletionSignalInLog(handle)).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("killWorkerTree kills only the target pid tree — parallel workers do not cross-kill", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-parallel-"));
    try {
      const a = await sleepWorker(dir, "grok/build", "A_DONE", "worker-a");
      const b = await sleepWorker(dir, "zai/glm-5.2", "B_DONE", "worker-b");

      expect(a.handle.pid).not.toBe(b.handle.pid);
      expect(isWorkerAlive(a.handle, injectedDeps(a.handle))).toBe(true);
      expect(isWorkerAlive(b.handle, injectedDeps(b.handle))).toBe(true);

      const killed = await killWorkerTree(a.handle, injectedDeps(a.handle));
      expect(killed.killedPids).toContain(a.handle.pid);
      expect(killed.residualPids).toEqual([]);

      expect(isWorkerAlive(a.handle, { ...injectedDeps(a.handle), isPidAlive: () => false })).toBe(false);
      expect(isWorkerAlive(b.handle, injectedDeps(b.handle))).toBe(true);

      await killWorkerTree(b.handle, injectedDeps(b.handle));
      expect(isWorkerAlive(b.handle, { ...injectedDeps(b.handle), isPidAlive: () => false })).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("refuses to kill when PID was reused by a different process instance", async () => {
    const killPid = vi.fn();
    const deps: WorkerMonitorDeps = {
      isPidAlive: () => true,
      listChildPids: () => [],
      // Current process at this PID has a DIFFERENT instance id than the handle.
      readInstanceId: () => "different-process-instance",
      killPid,
      sleepMs: async () => {},
    };
    const handle = baseHandle({
      pid: 424242,
      logPath: "/tmp/unused.log",
      instanceId: "original-instance",
    });
    expect(isWorkerAlive(handle, deps)).toBe(false);
    const result = await killWorkerTree(handle, deps);
    expect(killPid).not.toHaveBeenCalled();
    expect(result.killedPids).toEqual([]);
    expect(result.residualPids).toEqual([]);
    expect(result.skippedDueToPidReuse).toBe(true);
  });

  it("accepts the documented spawned identity when the platform cannot read a live instance id", () => {
    const handle = baseHandle({
      pid: 100,
      logPath: "/tmp/worker-100.log",
      instanceId: "spawned:100:2026-07-10T07:00:00.000Z",
    });
    const deps: WorkerMonitorDeps = {
      isPidAlive: () => true,
      readInstanceId: () => undefined,
    };

    expect(instanceMatchesHandle(handle, deps)).toBe(true);
    expect(
      instanceMatchesHandle(
        { ...handle, instanceId: "spawned:101:2026-07-10T07:00:00.000Z" },
        deps,
      ),
    ).toBe(false);
  });

  it("checks every child identity before signalling, not only the root", async () => {
    const killPid = vi.fn();
    let childIdentityReads = 0;
    const deps: WorkerMonitorDeps = {
      isPidAlive: () => true,
      listChildPids: (pid) => (pid === 100 ? [101] : []),
      readParentPid: (pid) => (pid === 101 ? 100 : undefined),
      readInstanceId: (pid) => {
        if (pid === 100) return "root";
        childIdentityReads += 1;
        return childIdentityReads === 1 ? "original-child" : "reused-child";
      },
      killPid,
      sleepMs: async () => {},
    };
    const handle = baseHandle({
      pid: 100,
      logPath: "/tmp/unused.log",
      instanceId: "root",
    });

    await killWorkerTree(handle, deps);

    expect(killPid.mock.calls.some(([pid]) => pid === 101)).toBe(false);
    expect(killPid.mock.calls.some(([pid]) => pid === 100)).toBe(true);
    expect(killPid.mock.calls.some(([pid]) => typeof pid === "number" && pid < 0)).toBe(false);
  });

  it("reports re-parented children as an unverified boundary without signalling them", async () => {
    const killPid = vi.fn();
    const alive = new Set([100, 101]);
    const deps: WorkerMonitorDeps = {
      isPidAlive: (pid) => alive.has(pid),
      listChildPids: (pid) => (pid === 100 ? [101] : []),
      readParentPid: (pid) => (pid === 101 ? 1 : undefined),
      readInstanceId: () => "same-instance",
      killPid,
      sleepMs: async () => {},
    };
    const handle = baseHandle({
      pid: 100,
      logPath: "/tmp/unused.log",
      instanceId: "same-instance",
    });

    const result = await killWorkerTree(handle, deps);

    expect(killPid.mock.calls.some(([pid]) => pid === 101)).toBe(false);
    expect(killPid.mock.calls.some(([pid]) => typeof pid === "number" && pid < 0)).toBe(false);
    expect(result.unverifiedPids).toEqual([101]);
  });

  it.skipIf(process.platform === "win32")(
    "default deps report an orphaned child as unverified without signalling it",
    async () => {
      const dir = mkdtempSync(join(tmpdir(), "orch-684-default-reparent-"));
      const originalPath = process.env.PATH;
      let orphanPid: number | undefined;
      try {
        const pidFile = join(dir, "orphan.pid");
        const root = spawn(
          "bash",
          [
            "-c",
            'sleep 30 & child=$!; echo "$child" > "$1"',
            "orphan-root",
            pidFile,
          ],
          { stdio: "ignore" },
        );
        expect(root.pid).toBeDefined();
        await new Promise<void>((resolve, reject) => {
          root.once("exit", () => resolve());
          root.once("error", reject);
        });
        orphanPid = Number.parseInt(readFileSync(pidFile, "utf8").trim(), 10);
        expect(orphanPid).toBeGreaterThan(0);

        const psShim = join(dir, "ps");
        writeFileSync(
          psShim,
          `#!/bin/sh
if [ "$1" = "-o" ] && [ "$2" = "pid=" ] && [ "$4" = "${root.pid}" ]; then
  echo "${orphanPid}"
  exit 0
fi
if [ "$1" = "-o" ] && [ "$2" = "ppid=" ]; then
  echo "1"
  exit 0
fi
if [ "$1" = "-p" ]; then
  echo "same-instance"
  exit 0
fi
exit 0
`,
          "utf8",
        );
        chmodSync(psShim, 0o755);
        process.env.PATH = `${dir}:${originalPath ?? ""}`;

        const handle = baseHandle({
          pid: root.pid!,
          logPath: "/tmp/unused.log",
          instanceId: "same-instance",
        });
        const result = await killWorkerTree(handle);

        expect(result.unverifiedPids).toContain(orphanPid);
        expect(result.killedPids).not.toContain(orphanPid);
        expect(() => process.kill(orphanPid!, 0)).not.toThrow();
      } finally {
        if (originalPath === undefined) delete process.env.PATH;
        else process.env.PATH = originalPath;
        if (orphanPid !== undefined) {
          try {
            process.kill(orphanPid, "SIGKILL");
          } catch {
            // The child may have exited during the assertion or cleanup.
          }
        }
        rmSync(dir, { recursive: true, force: true });
      }
    },
  );

  it("accepts an injected instance reader for restricted dispatch tests", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-injected-id-"));
    try {
      const { handle, child } = await dispatchMonitoredCliWorker({
        command: process.platform === "win32" ? "cmd" : "sleep",
        args: process.platform === "win32" ? ["/c", "ping", "-n", "2", "127.0.0.1"] : ["2"],
        logDir: dir,
        poolId: "test/injected",
        completionSignal: "TEST_DONE",
        stepId: "injected",
        readInstanceId: () => "injected-instance",
      });
      expect(handle.instanceId).toBe("injected-instance");
      expect(isWorkerAlive(handle, {
        isPidAlive: () => true,
        readInstanceId: () => "injected-instance",
      })).toBe(true);
      await killWorkerTree(handle, {
        isPidAlive: (pid) => pid === child.pid,
        listChildPids: () => [],
        readInstanceId: () => "injected-instance",
        killPid: () => {},
        sleepMs: async () => {},
      });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("collectPidTree walks only the rooted pid subtree", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-tree-"));
    try {
      const { handle } = await dispatchMonitoredCliWorker({
        command: "bash",
        args: ["-c", "sleep 600 & wait"],
        logDir: dir,
        poolId: "grok/build",
        completionSignal: "TREE_DONE",
        stepId: "tree-worker",
        readInstanceId: () => "tree-worker-instance",
      });
      await new Promise((resolve) => setTimeout(resolve, 150));
      const tree = collectPidTree(handle.pid, {
        listChildPids: () => [],
      });
      expect(tree).toContain(handle.pid);
      expect(tree.length).toBeGreaterThanOrEqual(1);
      await killWorkerTree(handle, injectedDeps(handle));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("residual check re-collects children dynamically spawned during the kill window", async () => {
    // Pre-kill tree: 100 → 101. Root 100 refuses to die (stubborn process).
    // When 101 is SIGKILL'd it is replaced under root by late-spawned 102.
    // Residual re-collect from still-alive root must surface 102.
    const alive = new Set<number>([100, 101]);
    const children = new Map<number, number[]>([
      [100, [101]],
      [101, []],
    ]);
    let listWaves = 0;
    const deps: WorkerMonitorDeps = {
      isPidAlive: (pid) => alive.has(pid),
      listChildPids: (pid) => {
        listWaves += 1;
        return children.get(pid) ?? [];
      },
      readParentPid: (pid) => (pid === 101 || pid === 102 ? 100 : undefined),
      readInstanceId: (pid) => (alive.has(pid) ? "same" : undefined),
      killPid: (pid, _signal) => {
        if (pid === 100) {
          // Stubborn root: signals do not kill it (still same instance).
          return;
        }
        if (pid === 101) {
          alive.delete(101);
          // Dynamic child appears under still-alive root during the kill window
          // (late spawn / re-parent under root before residual re-collect).
          if (!alive.has(102)) {
            alive.add(102);
            children.set(100, [102]);
            children.set(102, []);
          }
          return;
        }
        alive.delete(pid);
      },
      sleepMs: async () => {},
    };
    const handle = baseHandle({
      pid: 100,
      logPath: "/tmp/unused.log",
      instanceId: "same",
    });
    const result = await killWorkerTree(handle, deps);
    expect(result.residualPids).toContain(100);
    expect(result.unverifiedPids).toContain(102);
    expect(result.residualPids).not.toContain(101);
    // Pre-kill collect + post-kill re-collect ⇒ more than one list wave.
    expect(listWaves).toBeGreaterThan(1);
  });

  it("monitor handle round-trips through ledger entries for resume rebuild", () => {
    const handle = baseHandle({
      pid: 4242,
      logPath: "/tmp/scratch/worker-a.log",
      dispatchedAt: "2026-07-08T12:00:00.000Z",
      instanceId: "Fri Jul  8 12:00:00 2026",
    });
    const entry: PersistentLedgerEntry = {
      step: "S7",
      sessionId: "session-1",
      prompt_hash: "hash",
      branchHEAD: "abc123",
      ts: "2026-07-08T12:00:01.000Z",
      monitorHandle: handle,
    };
    expect(monitorHandleFromLedger(entry)).toEqual(handle);
  });

  it("poolIdForWorker derives pool/model identity from the worker spec", () => {
    const spec: WorkerSpec = {
      id: "S2",
      kind: "coder",
      role: "coder",
      host: "claude",
      session: "fresh",
      contextRetention: "retain",
      promptFile: "coder.md",
      completionSignal: "CODER_STEP_COMPLETE",
      maxIter: 5,
      model: "sonnet",
      soul: "coder",
      toolchain: [],
    };
    expect(poolIdForWorker(spec)).toBe("claude/sonnet");
  });

  it("does not expose any process-name-based kill API", async () => {
    const source = readFileSync(
      new URL("../../src/workerMonitor.ts", import.meta.url),
      "utf8",
    );
    expect(source).not.toMatch(/\bpgrep\b/);
    expect(source).not.toMatch(/\bpkill\b/);
    expect(source).not.toMatch(/-f\s+["']/);
  });

  it("production dispatchWorkerWithMonitor path calls dispatchMonitoredCliWorker for CLI workers", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-prod-cli-"));
    try {
      const completed: WorkerResult = {
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "cli-session",
      };
      const backend = {
        resolveCliMonitorDispatch: (
          spec: WorkerSpec,
          ctx: DispatchContext,
        ) => ({
          command: process.platform === "win32" ? "cmd" : "true",
          args: process.platform === "win32" ? ["/c", "exit", "0"] : [],
          logDir: dir,
          poolId: poolIdForWorker(spec),
          completionSignal: spec.completionSignal,
          stepId: spec.id,
          cwd: ctx.worktree?.path,
          readInstanceId: () => "injected-production-instance",
        }),
        awaitMonitoredCliWorker: async () => completed,
      } as unknown as Backend;

      const spec: WorkerSpec = {
        id: "S2",
        kind: "coder",
        role: "coder",
        host: "claude",
        session: "fresh",
        contextRetention: "retain",
        promptFile: "coder.md",
        completionSignal: "CODER_STEP_COMPLETE",
        maxIter: 5,
        model: "sonnet",
        soul: "coder",
        toolchain: [],
      };
      const ctx: DispatchContext = {
        worktree: {
          branch: "feat/684",
          base: "main",
          path: dir,
        },
        stateDir: dir,
      };

      const outcome = await dispatchWorkerWithMonitor(backend, spec, ctx);
      expect(outcome.result).toEqual(completed);
      expect(outcome.monitorHandle).toBeDefined();
      expect(validateMonitorHandle(outcome.monitorHandle)).toBe(true);
      expect(outcome.monitorHandle!.poolId).toBe("claude/sonnet");
      expect(outcome.monitorHandle!.completionSignal).toBe("CODER_STEP_COMPLETE");
      expect(outcome.monitorHandle!.instanceId).toBe("injected-production-instance");
      expect(existsSync(outcome.monitorHandle!.logPath)).toBe(true);
      // Handle must be rebuildable from a ledger entry (resume path).
      const entry: PersistentLedgerEntry = {
        step: "S2",
        sessionId: "cli-session",
        prompt_hash: "h",
        branchHEAD: "deadbeef",
        ts: new Date().toISOString(),
        monitorHandle: outcome.monitorHandle,
      };
      expect(monitorHandleFromLedger(entry)).toEqual(outcome.monitorHandle);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("refuses to signal a child whose identity was not captured at collect time", () => {
    const handle = baseHandle({ pid: 100, logPath: "/tmp/worker.log", instanceId: "root" });
    const deps: WorkerMonitorDeps = {
      isPidAlive: () => true,
      readInstanceId: (pid) => (pid === 100 ? "root" : "reused-child"),
      readParentPid: () => 100,
    };

    expect(
      pidSafeToSignal(101, handle, new Set([100, 101]), new Map([[101, undefined]]), deps),
    ).toBe(false);
    expect(
      pidSafeToSignal(101, handle, new Set([100, 101]), new Map(), deps),
    ).toBe(false);
  });

  it("persists the monitor callback before awaiting the monitored child", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-spawn-callback-"));
    try {
      const events: string[] = [];
      const backend = {
        resolveCliMonitorDispatch: (spec: WorkerSpec) => ({
          command: process.platform === "win32" ? "cmd" : "sleep",
          args: process.platform === "win32" ? ["/c", "ping", "-n", "2", "127.0.0.1"] : ["0.2"],
          logDir: dir,
          poolId: poolIdForWorker(spec),
          completionSignal: spec.completionSignal,
          stepId: spec.id,
          readInstanceId: () => "injected-production-instance",
        }),
        awaitMonitoredCliWorker: async () => {
          events.push("awaited");
          return { kind: "completed", output: { kind: "coder", committed: true, commitsAdded: 1 } } as WorkerResult;
        },
      } as unknown as Backend;
      const spec = {
        id: "S2",
        kind: "coder",
        role: "coder",
        host: "claude",
        session: "fresh",
        contextRetention: "retain",
        promptFile: "coder.md",
        completionSignal: "CODER_STEP_COMPLETE",
        maxIter: 5,
        model: "sonnet",
        soul: "coder",
        toolchain: [],
      } satisfies WorkerSpec;

      await dispatchWorkerWithMonitor(backend, spec, { stateDir: dir }, undefined, {
        onMonitorHandleSpawned: async () => {
          events.push("spawned");
        },
      });

      expect(events).toEqual(["spawned", "awaited"]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("exposes monitored hooks on both real backend implementations", () => {
    expect(typeof RealBackend.prototype.resolveCliMonitorDispatch).toBe("function");
    expect(typeof RealBackend.prototype.awaitMonitoredCliWorker).toBe("function");
    expect(typeof RealFamilyBackend.prototype.resolveCliMonitorDispatch).toBe("function");
    expect(typeof RealFamilyBackend.prototype.awaitMonitoredCliWorker).toBe("function");
  });

  it("production dispatch source wires dispatchMonitoredCliWorker (not test-only)", () => {
    const dispatchSrc = readFileSync(
      new URL("../../src/dispatchWorker.ts", import.meta.url),
      "utf8",
    );
    const runnerSrc = readFileSync(
      new URL("../../src/runner.ts", import.meta.url),
      "utf8",
    );
    expect(dispatchSrc).toMatch(/dispatchMonitoredCliWorker/);
    expect(dispatchSrc).toMatch(/dispatchWorkerWithMonitor/);
    expect(runnerSrc).toMatch(/dispatchWorkerWithMonitor/);
    expect(runnerSrc).toMatch(/monitorHandle/);
  });

  it("only seeds a resumed monitor handle into the matching step", () => {
    const runnerSrc = readFileSync(
      new URL("../../src/runner.ts", import.meta.url),
      "utf8",
    );
    expect(runnerSrc).toMatch(
      /if \(resumeMonitorHandle\?\.stepId === step\) \{[\s\S]*?stepMonitorHandle = resumeMonitorHandle;[\s\S]*?resumeMonitorHandle = undefined;/,
    );
  });

  it("documents re-parent-to-init residual limit in killWorkerTree", () => {
    const source = readFileSync(
      new URL("../../src/workerMonitor.ts", import.meta.url),
      "utf8",
    );
    expect(source).toMatch(/re-parent/i);
    expect(source).toMatch(/PID 1|init/i);
  });

  it("allocates a distinct result sidecar for each dispatch of the same step", () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-sidecar-"));
    try {
      const spec = {
        id: "S9",
        kind: "reviewer",
        role: "reviewer",
        host: "claude",
        session: "fresh",
        contextRetention: "retain",
        promptFile: "reviewer.md",
        completionSignal: "REVIEW_STEP_COMPLETE",
        maxIter: 1,
        model: "sonnet",
        soul: "READ-ONLY",
        toolchain: [],
      } satisfies WorkerSpec;
      const first = buildCliMonitorSpawnSpec({
        backendKind: "real",
        backendOpts: {},
        spec,
        ctx: { stateDir: dir },
        runnerPath: "/tmp/runner.js",
      });
      const second = buildCliMonitorSpawnSpec({
        backendKind: "real",
        backendOpts: {},
        spec,
        ctx: { stateDir: dir },
        runnerPath: "/tmp/runner.js",
      });
      expect(first?.resultPath).toBeDefined();
      expect(second?.resultPath).toBeDefined();
      expect(first?.resultPath).not.toBe(second?.resultPath);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
