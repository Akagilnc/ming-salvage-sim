import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { dispatchWorkerWithMonitor } from "../src/dispatchWorker.js";
import {
  handleIdleThreshold,
  QuotaWaitForResetError,
  type QuotaProbeResult,
} from "../src/quotaProbe.js";
import type {
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../src/types.js";

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
    ): Promise<"hang" | "wait_for_reset"> => {
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
      return "hang";
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

  it("probe pass uses the monitor's verified pid-tree kill disposition", async () => {
    const ledger: unknown[] = [];
    const out = await runMonitored({ kind: "ok" }, ledger);

    expect(out.error).toBeUndefined();
    expect(out.killed.some((pid) => pid > 0)).toBe(true);
    expect(ledger).toEqual([]);
  });

  it("probe network error fails safe through the same hang disposition", async () => {
    const ledger: unknown[] = [];
    const out = await runMonitored(
      { kind: "error", cause: "network unavailable" },
      ledger,
    );

    expect(out.error).toBeUndefined();
    expect(out.killed.some((pid) => pid > 0)).toBe(true);
    expect(ledger).toEqual([]);
  });
});
