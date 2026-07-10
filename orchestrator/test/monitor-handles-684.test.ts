/**
 * #684 — monitor handles atomically produced at dispatch; judge/kill only via handle.
 */

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  dispatchWorkerWithMonitor,
} from "../src/dispatchWorker.js";
import {
  collectPidTree,
  dispatchMonitoredCliWorker,
  hasCompletionSignalInLog,
  isWorkerAlive,
  isWorkerIdle,
  killWorkerTree,
  monitorHandleFromLedger,
  poolIdForWorker,
  readLogActivity,
  validateMonitorHandle,
  type WorkerMonitorDeps,
} from "../src/workerMonitor.js";
import type {
  Backend,
  DispatchContext,
  PersistentLedgerEntry,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../src/types.js";

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
  });
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
      expect(isWorkerAlive(handle)).toBe(true);
      await killWorkerTree(handle);
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
      expect(isWorkerAlive(a.handle)).toBe(true);
      expect(isWorkerAlive(b.handle)).toBe(true);

      const killed = await killWorkerTree(a.handle);
      expect(killed.killedPids).toContain(a.handle.pid);
      expect(killed.residualPids).toEqual([]);

      expect(isWorkerAlive(a.handle)).toBe(false);
      expect(isWorkerAlive(b.handle)).toBe(true);

      await killWorkerTree(b.handle);
      expect(isWorkerAlive(b.handle)).toBe(false);
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
      });
      await new Promise((resolve) => setTimeout(resolve, 150));
      const tree = collectPidTree(handle.pid);
      expect(tree).toContain(handle.pid);
      expect(tree.length).toBeGreaterThanOrEqual(1);
      await killWorkerTree(handle);
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
    expect(result.residualPids).toContain(102);
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
      new URL("../src/workerMonitor.ts", import.meta.url),
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
        output: { kind: "coder", committed: true, commitCount: 1 },
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

  it("production dispatch source wires dispatchMonitoredCliWorker (not test-only)", () => {
    const dispatchSrc = readFileSync(
      new URL("../src/dispatchWorker.ts", import.meta.url),
      "utf8",
    );
    const runnerSrc = readFileSync(
      new URL("../src/runner.ts", import.meta.url),
      "utf8",
    );
    expect(dispatchSrc).toMatch(/dispatchMonitoredCliWorker/);
    expect(dispatchSrc).toMatch(/dispatchWorkerWithMonitor/);
    expect(runnerSrc).toMatch(/dispatchWorkerWithMonitor/);
    expect(runnerSrc).toMatch(/monitorHandle/);
  });

  it("documents re-parent-to-init residual limit in killWorkerTree", () => {
    const source = readFileSync(
      new URL("../src/workerMonitor.ts", import.meta.url),
      "utf8",
    );
    expect(source).toMatch(/re-parent/i);
    expect(source).toMatch(/PID 1|init/i);
  });
});
