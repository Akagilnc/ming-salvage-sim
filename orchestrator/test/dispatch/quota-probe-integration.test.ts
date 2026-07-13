import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { dispatchWorkerWithMonitor } from "../../src/dispatchWorker.js";
import { workerResultFromMonitorSidecar } from "../../src/cliMonitorHooks.js";
import {
  handleIdleThreshold,
  QuotaWaitForResetError,
  type QuotaProbeResult,
} from "../../src/quotaProbe.js";
import { HangWithLivePoolError } from "../../src/relayDispatch.js";
import type {
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

const tempDirs: string[] = [];

afterEach(() => {
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

function workerSpec(): WorkerSpec {
  return {
    id: "S2",
    kind: "coder",
    role: "coder",
    host: "codex",
    session: "fresh",
    contextRetention: "retain",
    promptFile: "coder.md",
    completionSignal: "<coder>",
    maxIter: 1,
    model: "glm-5.2",
    soul: "coder",
    toolchain: [],
  } as WorkerSpec;
}

function monitoredBackend(
  probeResult: QuotaProbeResult,
  ledger: unknown[],
): Backend {
  const backend = {
    resolveCliMonitorDispatch: (
      _spec: WorkerSpec,
      _ctx: DispatchContext,
    ): CliMonitorSpawnSpec => {
      const dir = tempDirs[0]!;
      return {
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 1000)"],
        logDir: dir,
        poolId: "zai",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance",
      };
    },
    handleMonitoredWorkerIdle: async (
      handle: WorkerMonitorHandle,
      spec: WorkerSpec,
    ): Promise<"hang" | "hang_with_live_pool" | "wait_for_reset"> => {
      const result = await handleIdleThreshold({
        modelRef: spec.model,
        worker: { pid: handle.pid, step: spec.id },
        probe: async () => probeResult,
        actions: {
          killPidTree: () => undefined,
          recordLedger: (entry) => {
            ledger.push(entry);
          },
        },
      });
      if (result.disposition.kind === "wait_for_reset") {
        throw new QuotaWaitForResetError(result);
      }
    return result.probe.kind === "ok" ? "hang_with_live_pool" : "hang";
    },
    awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
      kind: "completed",
      output: { kind: "coder", committed: true, commitsAdded: 1 },
    }),
  } as unknown as Backend;
  return backend;
}

async function runMonitored(probeResult: QuotaProbeResult, ledger: unknown[]) {
  const dir = mkdtempSync(join(tmpdir(), "quota-probe-683-"));
  tempDirs.push(dir);
  const killed: number[] = [];
  try {
    const result = await dispatchWorkerWithMonitor(
      monitoredBackend(probeResult, ledger),
      workerSpec(),
      {},
      undefined,
      {
        idleThresholdMs: 0,
        pollIntervalMs: 1,
        monitorDeps: {
          readInstanceId: () => "test-instance",
          killPid: (pid) => killed.push(pid),
          isPidAlive: (pid) => pid > 0 && !killed.includes(pid),
          listChildPids: () => [],
          readParentPid: () => undefined,
          sleepMs: async () => {},
        },
      },
    );
    return { result, killed };
  } catch (error) {
    return { error, killed };
  }
}

describe("#683 integration at the real monitored dispatch path", () => {
  it("429 probes before hang judgment, parks, records reset, and does not kill", async () => {
    const ledger: unknown[] = [];
    const resetAt = new Date("2026-07-10T01:00:00.000Z");
    const out = await runMonitored({ kind: "quota_limited", resetAt }, ledger);

    expect(out.error).toBeInstanceOf(QuotaWaitForResetError);
    expect(out.killed).toEqual([]);
    expect(ledger).toEqual([
      expect.objectContaining({
        event: "quota_wait_for_reset",
        pool: "zai",
        resetAt: resetAt.toISOString(),
      }),
    ]);
  });

  it("probe pass uses the monitor's verified pid-tree kill then surfaces HangWithLivePoolError (#686)", async () => {
    const ledger: unknown[] = [];
    const out = await runMonitored({ kind: "ok" }, ledger);

    // #686: hang-with-live-pool kills the pid tree then throws a resource
    // failure so the runner relays (never mechanical-retry / never reset).
    expect(out.error).toBeInstanceOf(HangWithLivePoolError);
    expect(out.killed.some((pid) => pid > 0)).toBe(true);
    expect(ledger).toEqual([]);
  });

  it("probe network error fails safe as a plain hang, never a live-pool relay", async () => {
    const ledger: unknown[] = [];
    const out = await runMonitored(
      { kind: "error", cause: "network unavailable" },
      ledger,
    );

    expect(out.error).toBeInstanceOf(Error);
    expect(out.error).not.toBeInstanceOf(HangWithLivePoolError);
    expect(out.killed.some((pid) => pid > 0)).toBe(true);
    expect(ledger).toEqual([]);
  });

  it("missing idle probe fails safe as a plain hang, never a live-pool relay", async () => {
    const dir = mkdtempSync(join(tmpdir(), "missing-probe-686-"));
    tempDirs.push(dir);
    const killed: number[] = [];
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 1000)"],
        logDir: dir,
        poolId: "zai",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    await expect(
      dispatchWorkerWithMonitor(backend, workerSpec(), {}, undefined, {
        idleThresholdMs: 0,
        pollIntervalMs: 1,
        monitorDeps: {
          readInstanceId: () => "test-instance",
          killPid: (pid) => killed.push(pid),
          isPidAlive: (pid) => pid > 0 && !killed.includes(pid),
          listChildPids: () => [],
          readParentPid: () => undefined,
          sleepMs: async () => {},
        },
      }),
    ).rejects.not.toBeInstanceOf(HangWithLivePoolError);
    expect(killed.some((pid) => pid > 0)).toBe(true);
  });

  it("only parses relay tags emitted after this dispatch began", async () => {
    const dir = mkdtempSync(join(tmpdir(), "relay-log-offset-686-"));
    tempDirs.push(dir);
    writeFileSync(
      join(dir, "S2.log"),
      '<relay>{"blocked":{"reason":"baton A","state_summary":"stale","remaining":"do not replay"}}</relay>\n',
    );
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.platform === "win32" ? "cmd" : "true",
        args: process.platform === "win32" ? ["/c", "exit", "0"] : [],
        logDir: dir,
        poolId: "zai",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    await expect(dispatchWorkerWithMonitor(backend, workerSpec(), {})).resolves.toMatchObject({
      result: { kind: "completed" },
    });
  });

  it("observes a late idle-handler throw after child exit", async () => {
    const dir = mkdtempSync(join(tmpdir(), "quota-probe-683-race-"));
    tempDirs.push(dir);
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => unhandled.push(reason);
    process.on("unhandledRejection", onUnhandled);
    const warnings: string[] = [];
    const originalWarn = console.warn;
    console.warn = (...args: unknown[]) => warnings.push(args.map(String).join(" "));
    let releaseThrow: (() => void) | undefined;
    const throwGate = new Promise<void>((resolve) => {
      releaseThrow = resolve;
    });
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 30_000)"],
        logDir: dir,
        poolId: "zai",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance",
      }),
      handleMonitoredWorkerIdle: async (handle: WorkerMonitorHandle): Promise<"hang" | "wait_for_reset"> => {
        try {
          process.kill(handle.pid, "SIGTERM");
        } catch {
          // Child may already be gone.
        }
        await new Promise<void>((resolve) => setTimeout(resolve, 30));
        await throwGate;
        throw new QuotaWaitForResetError({
          disposition: {
            kind: "wait_for_reset",
            pool: "zai",
            resetAt: new Date("2026-07-10T02:00:00.000Z"),
            reason: "quota limited (429); wait for reset",
          },
          applied: { killed: false, ledgerEntry: { event: "quota_wait_for_reset", pool: "zai", resetAt: "2026-07-10T02:00:00.000Z", reason: "quota limited (429); wait for reset", step: "S2", workerPid: handle.pid, ts: "2026-07-10T12:00:00.000Z" } },
          pool: "zai",
          probe: { kind: "quota_limited", resetAt: new Date("2026-07-10T02:00:00.000Z"), detail: "429" },
        });
      },
      // No usable sidecar after mid-flight SIGTERM → empty-fallback, rewritten
      // to killed-by-signal. (A real completed sidecar would still win.)
      awaitMonitoredCliWorker: async (
        handle: WorkerMonitorHandle,
        exitCode: number | null,
      ): Promise<WorkerResult> => workerResultFromMonitorSidecar(handle, exitCode),
    } as unknown as Backend;

    try {
      const outcomePromise = dispatchWorkerWithMonitor(backend, workerSpec(), {}, undefined, {
        idleThresholdMs: 0,
        pollIntervalMs: 1,
        monitorDeps: {
          readInstanceId: () => "test-instance",
          listChildPids: () => [],
          readParentPid: () => undefined,
          sleepMs: async () => {},
        },
      });
      await new Promise<void>((resolve) => setTimeout(resolve, 80));
      releaseThrow?.();
      const outcome = await outcomePromise;
      await new Promise<void>((resolve) => setImmediate(resolve));
      await new Promise<void>((resolve) => setTimeout(resolve, 20));

      // Child was SIGTERM'd inside the idle handler with no sidecar → killed.
      // Late QuotaWaitForResetError must still be observed (warn) without
      // becoming an unhandledRejection.
      expect(outcome.result.kind).toBe("failed");
      if (outcome.result.kind === "failed") {
        expect(outcome.result.reason).toMatch(/killed by signal/i);
      }
      expect(unhandled).toEqual([]);
      expect(warnings.some((w) => w.includes("monitored idle handler settled after child exit"))).toBe(true);
    } finally {
      console.warn = originalWarn;
      process.off("unhandledRejection", onUnhandled);
    }
  });
});
