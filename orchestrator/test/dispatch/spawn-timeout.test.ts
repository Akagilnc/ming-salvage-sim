/**
 * #937 / #934 ID-004 — spawn acknowledgement wall clock deleted.
 * ChildProcess is the ownership token; adoption-failure cleanup uses
 * terminateSpawnedChild on the exact handle (no 120s spawn-ack reject).
 */

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

const fakeChildState = vi.hoisted(() => ({
  signals: [] as NodeJS.Signals[],
  listeners: new Map<string, Array<(...args: unknown[]) => void>>(),
}));

vi.mock("node:child_process", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:child_process")>();
  return {
    ...actual,
    spawn: vi.fn(() => {
      fakeChildState.listeners = new Map();
      return {
        pid: 4242,
        exitCode: null,
        signalCode: null,
        once: vi.fn((event: string, cb: (...args: unknown[]) => void) => {
          const list = fakeChildState.listeners.get(event) ?? [];
          list.push(cb);
          fakeChildState.listeners.set(event, list);
        }),
        removeListener: vi.fn((event: string, cb: (...args: unknown[]) => void) => {
          const list = fakeChildState.listeners.get(event) ?? [];
          fakeChildState.listeners.set(
            event,
            list.filter((fn) => fn !== cb),
          );
        }),
        kill: vi.fn((signal: NodeJS.Signals) => {
          fakeChildState.signals.push(signal);
          return true;
        }),
      };
    }),
  };
});

import {
  dispatchMonitoredCliWorker,
  terminateSpawnedChild,
} from "../../src/workerMonitor.js";

afterEach(() => {
  fakeChildState.signals.length = 0;
  fakeChildState.listeners = new Map();
});

describe("#937 spawn ownership (no spawn-ack wall clock)", () => {
  it("POSITIVE: resolves on Node spawn notification without a wall-clock reject", async () => {
    const logDir = mkdtempSync(join(tmpdir(), "spawn-937-ack-"));
    try {
      const pending = dispatchMonitoredCliWorker({
        command: "fake-worker",
        args: [],
        logDir,
        poolId: "test/fake",
        stepId: "spawn-ok",
        readInstanceId: () => "spawn-instance",
      });
      // Fire spawn asynchronously (no 120s timeout).
      queueMicrotask(() => {
        for (const cb of fakeChildState.listeners.get("spawn") ?? []) cb();
      });
      const { handle, child } = await pending;
      expect(handle.pid).toBe(4242);
      expect(handle.instanceId).toBe("spawn-instance");
      expect(child.pid).toBe(4242);
    } finally {
      rmSync(logDir, { recursive: true, force: true });
    }
  });

  it("NEGATIVE: advanceTimers never invents ExternalCallTimeoutError on spawn", async () => {
    vi.useFakeTimers();
    const logDir = mkdtempSync(join(tmpdir(), "spawn-937-no-timeout-"));
    try {
      let settled = false;
      const pending = dispatchMonitoredCliWorker({
        command: "fake-worker",
        args: [],
        logDir,
        poolId: "test/fake",
        stepId: "spawn-timeout",
        readInstanceId: () => "spawn-instance",
      }).then(
        (v) => {
          settled = true;
          return v;
        },
        (e) => {
          settled = true;
          throw e;
        },
      );
      await vi.advanceTimersByTimeAsync(120_000);
      // Still pending — no spawn-ack wall clock.
      expect(settled).toBe(false);
      // Complete via spawn so the test does not leak.
      for (const cb of fakeChildState.listeners.get("spawn") ?? []) cb();
      await pending;
    } finally {
      vi.useRealTimers();
      rmSync(logDir, { recursive: true, force: true });
    }
  });

  it("POSITIVE: terminateSpawnedChild signals the exact handle on adoption failure", async () => {
    const logDir = mkdtempSync(join(tmpdir(), "spawn-937-term-"));
    try {
      const pending = dispatchMonitoredCliWorker({
        command: "fake-worker",
        args: [],
        logDir,
        poolId: "test/fake",
        stepId: "spawn-term",
        readInstanceId: () => "spawn-instance",
      });
      queueMicrotask(() => {
        for (const cb of fakeChildState.listeners.get("spawn") ?? []) cb();
      });
      const { child } = await pending;
      await terminateSpawnedChild(child as never, {
        killPid: (pid, signal) => {
          fakeChildState.signals.push(signal);
          void pid;
        },
        sleepMs: async () => {},
      });
      expect(fakeChildState.signals.length).toBeGreaterThan(0);
    } finally {
      rmSync(logDir, { recursive: true, force: true });
    }
  });
});
