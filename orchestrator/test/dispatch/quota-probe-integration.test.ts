/**
 * #683 / #937 — quota probe remains for explicit 429 walls; monitored dispatch
 * no longer probes/kills/relays on silence (ID-007). Free-log relay tags are
 * not a host fate channel.
 */

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { dispatchWorkerWithMonitor } from "../../src/dispatchWorker.js";
import { QuotaWaitForResetError } from "../../src/quotaProbe.js";
import type {
  Backend,
  CliMonitorSpawnSpec,
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
    maxIter: 1,
    model: "glm-5.2",
    soul: "coder",
    toolchain: [],
  } as WorkerSpec;
}

describe("#683/#937 monitored dispatch + quota composition", () => {
  it("NEGATIVE: dispatchWorkerWithMonitor does not hang-kill on silence", async () => {
    const dir = mkdtempSync(join(tmpdir(), "quota-probe-937-silence-"));
    tempDirs.push(dir);
    const killed: number[] = [];
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        // Instant exit — would have been raced by idleThresholdMs:0 before #937.
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

    const outcome = await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
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
    expect(killed).toEqual([]);
        expect(outcome).not.toBeInstanceOf(QuotaWaitForResetError);
  });

  it("NEGATIVE: free-log relay tags never become SelfReported/Hang fate", async () => {
    const dir = mkdtempSync(join(tmpdir(), "relay-log-offset-937-"));
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
        stepId: "S2",
        readInstanceId: () => "test-instance",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    await expect(
      dispatchWorkerWithMonitor(backend, workerSpec(), {}),
    ).resolves.toMatchObject({
      result: { kind: "completed" },
    });
  });
});
