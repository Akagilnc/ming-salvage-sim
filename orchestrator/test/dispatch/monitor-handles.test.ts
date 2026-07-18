/**
 * #684 / #937 — monitor handles at unified worker dispatch.
 * Process ownership = exact ChildProcess / process-group; silence is
 * observational only (no idle kill / PID-tree / spawn-ack wall clock).
 */

import { spawn } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { dispatchWorkerWithMonitor } from "../../src/dispatchWorker.js";
import {
  dispatchMonitoredCliWorker,
  monitorHandleFromLedger,
  poolIdForWorker,
  readLogActivity,
  silenceWholeMinutes,
  terminateSpawnedChild,
  validateMonitorHandle,
} from "../../src/workerMonitor.js";
import type {
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  LedgerEntry,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

function baseHandle(
  overrides: Partial<WorkerMonitorHandle> &
    Pick<WorkerMonitorHandle, "pid" | "logPath">,
): WorkerMonitorHandle {
  return {
    poolId: "grok/composer",
    stepId: "S7",
    dispatchedAt: new Date().toISOString(),
    instanceId: "test-instance",
    ...overrides,
  };
}

function sleepWorker(
  logDir: string,
  poolId: string,
  stepId: string,
): ReturnType<typeof dispatchMonitoredCliWorker> {
  return dispatchMonitoredCliWorker({
    command: process.platform === "win32" ? "ping" : "sleep",
    args: process.platform === "win32" ? ["-n", "600"] : ["600"],
    logDir,
    poolId,
    stepId,
    logBasename: `${stepId}.log`,
    readInstanceId: () => `test-instance-${stepId}`,
  });
}

describe("#684/#937 worker monitor handles", () => {
  it("dispatchMonitoredCliWorker yields a valid handle without spawn-ack timeout", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-spawn-"));
    try {
      const { handle, child } = await sleepWorker(dir, "zai", "S2");
      expect(validateMonitorHandle(handle)).toBe(true);
      expect(handle.pid).toBeGreaterThan(0);
      expect(existsSync(handle.logPath)).toBe(true);
      expect(handle.instanceId).toBe("test-instance-S2");
      await terminateSpawnedChild(child);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("NEGATIVE: validateMonitorHandle rejects incomplete handle shapes", () => {
    expect(validateMonitorHandle(undefined)).toBe(false);
    expect(
      validateMonitorHandle({
        pid: 1,
        logPath: "/tmp/x",
        poolId: "p",
        stepId: "S2",
        dispatchedAt: "t",
        instanceId: "",
      } as WorkerMonitorHandle),
    ).toBe(false);
    expect(
      validateMonitorHandle({
        pid: -1,
        logPath: "/tmp/x",
        poolId: "p",
        stepId: "S2",
        dispatchedAt: "t",
        instanceId: "id",
      } as WorkerMonitorHandle),
    ).toBe(false);
  });

  it("readLogActivity reports growth; silenceWholeMinutes is pure report", () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-log-"));
    try {
      const logPath = join(dir, "worker.log");
      writeFileSync(logPath, "line1\n", "utf8");
      const handle = baseHandle({ pid: process.pid, logPath });
      const first = readLogActivity(handle);
      expect(first).toBeDefined();
      writeFileSync(logPath, "line1\nline2\n", "utf8");
      const second = readLogActivity(handle);
      expect(second!.sizeBytes).toBeGreaterThan(first!.sizeBytes);

      expect(silenceWholeMinutes(Date.now() - 59_000, Date.now())).toBe(0);
      expect(silenceWholeMinutes(Date.now() - 120_000, Date.now())).toBe(2);
      // NEGATIVE: non-finite inputs yield 0 (never invent silence)
      expect(silenceWholeMinutes(Number.NaN, Date.now())).toBe(0);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("NEGATIVE: missing log is not evidence of activity", () => {
    const handle = baseHandle({
      pid: process.pid,
      logPath: join(tmpdir(), `missing-${Date.now()}.log`),
    });
    expect(readLogActivity(handle)).toBeUndefined();
  });

  it("monitorHandleFromLedger rebuilds only valid shapes", () => {
    const good: Pick<LedgerEntry, "monitorHandle"> = {
      monitorHandle: baseHandle({
        pid: 42,
        logPath: "/tmp/ledger.log",
      }),
    };
    expect(monitorHandleFromLedger(good)?.pid).toBe(42);

    const bad: Pick<LedgerEntry, "monitorHandle"> = {
      monitorHandle: {
        pid: 0,
        logPath: "/tmp/x",
        poolId: "p",
        stepId: "S2",
        dispatchedAt: "t",
        instanceId: "id",
      },
    };
    expect(monitorHandleFromLedger(bad)).toBeUndefined();
  });

  it("poolIdForWorker derives host/model identity from the worker spec", () => {
    expect(
      poolIdForWorker({
        id: "S2",
        kind: "coder",
        role: "coder",
        host: "codex",
        session: "fresh",
        contextRetention: "retain",
        promptFile: "coder.md",
        maxIter: 1,
        model: "glm-5.2",
        soul: "coder",
        toolchain: [],
      } as WorkerSpec),
    ).toBe("codex/glm-5.2");
  });

  it("terminateSpawnedChild signals the exact child (adoption-failure path)", async () => {
    const child = spawn(
      process.platform === "win32" ? "ping" : "sleep",
      process.platform === "win32" ? ["-n", "600"] : ["600"],
      { detached: true, stdio: "ignore" },
    );
    const killed: Array<{ pid: number; signal: string }> = [];
    await terminateSpawnedChild(child, {
      killPid: (pid, signal) => {
        killed.push({ pid, signal });
        // Confirm exit for ID-006 (mock ChildProcess does not get OS exit events
        // when only negative-pid group signals fire in restricted sandboxes).
        Object.defineProperty(child, "exitCode", {
          value: 1,
          configurable: true,
        });
        try {
          process.kill(pid, 0);
          process.kill(pid, signal);
        } catch {
          // group may not exist in restricted sandboxes
        }
      },
      sleepMs: async () => {},
    });
    // At least one signal attempt against the process group or handle.
    expect(killed.length + (child.killed ? 1 : 0)).toBeGreaterThan(0);
    try {
      child.kill("SIGKILL");
    } catch {
      // already reaped
    }
  });

  it("NEGATIVE: unconfirmed exit after SIGKILL raises worker_termination_failed", async () => {
    const { WorkerTerminationFailedError } = await import(
      "../../src/workerMonitor.js"
    );
    const child = {
      pid: 4242,
      exitCode: null as number | null,
      signalCode: null as NodeJS.Signals | null,
      kill: () => true,
    };
    await expect(
      terminateSpawnedChild(child as never, {
        killPid: () => {
          // Deliberately leave exitCode null → unconfirmed.
        },
        sleepMs: async () => {},
      }, { instanceId: "test-instance" }),
    ).rejects.toBeInstanceOf(WorkerTerminationFailedError);
    await expect(
      terminateSpawnedChild(child as never, {
        killPid: () => {},
        sleepMs: async () => {},
      }, { instanceId: "test-instance" }),
    ).rejects.toMatchObject({
      reason: "worker_termination_failed",
      pid: 4242,
      instanceId: "test-instance",
    });
  });

  it("dispatchWorkerWithMonitor waits for exit only — silence does not kill", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-dispatch-"));
    try {
      const backend = {
        resolveCliMonitorDispatch: (
          _spec: WorkerSpec,
          _ctx: DispatchContext,
        ): CliMonitorSpawnSpec => ({
          command: process.platform === "win32" ? "cmd" : "true",
          args: process.platform === "win32" ? ["/c", "exit", "0"] : [],
          logDir: dir,
          poolId: "zai",
          stepId: "S2",
          readInstanceId: () => "test-instance",
        }),
        awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        }),
      } as unknown as Backend;

      const killed: number[] = [];
      const outcome = await dispatchWorkerWithMonitor(
        backend,
        {
          id: "S2",
          kind: "coder",
          role: "coder",
          host: "codex",
          session: "fresh",
          contextRetention: "retain",
          promptFile: "coder.md",
          maxIter: 1,
          model: "glm-5.2",
          soul: "coder",
          toolchain: [],
        } as WorkerSpec,
        {},
        undefined,
        {
          monitorDeps: {
            readInstanceId: () => "test-instance",
            killPid: (pid) => killed.push(pid),
            sleepMs: async () => {},
          },
        },
      );
      expect(outcome.result.kind).toBe("completed");
      // No idle kill path — adoption failure is the only host kill seam.
      expect(killed).toEqual([]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("NEGATIVE: free-log relay tags are not a host fate channel", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-nolog-fate-"));
    try {
      writeFileSync(
        join(dir, "S2.log"),
        '<relay>{"blocked":{"reason":"stale","state_summary":"x","remaining":"y"}}</relay>\n',
      );
      const backend = {
        resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
          command: process.platform === "win32" ? "cmd" : "true",
          args: process.platform === "win32" ? ["/c", "exit", "0"] : [],
          logDir: dir,
          poolId: "zai",
          stepId: "S2",
          readInstanceId: () => "test-instance",
        }),
        awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        }),
      } as unknown as Backend;

      await expect(
        dispatchWorkerWithMonitor(
          backend,
          {
            id: "S2",
            kind: "coder",
            role: "coder",
            host: "codex",
            session: "fresh",
            contextRetention: "retain",
            promptFile: "coder.md",
            maxIter: 1,
            model: "glm-5.2",
            soul: "coder",
            toolchain: [],
          } as WorkerSpec,
          {},
        ),
      ).resolves.toMatchObject({ result: { kind: "completed" } });
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
