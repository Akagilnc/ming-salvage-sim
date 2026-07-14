import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

const fakeChildState = vi.hoisted(() => ({
  signals: [] as NodeJS.Signals[],
}));

vi.mock("node:child_process", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:child_process")>();
  return {
    ...actual,
    spawn: vi.fn(() => ({
      pid: 4242,
      exitCode: null,
      signalCode: null,
      once: vi.fn(),
      removeListener: vi.fn(),
      kill: vi.fn((signal: NodeJS.Signals) => {
        fakeChildState.signals.push(signal);
        return true;
      }),
    })),
  };
});

import { dispatchMonitoredCliWorker } from "../../src/workerMonitor.js";

afterEach(() => {
  fakeChildState.signals.length = 0;
  vi.useRealTimers();
});

describe("PR #891 r12 spawn acknowledgement timeout", () => {
  it("terminates only the child instance it spawned before rejecting", async () => {
    vi.useFakeTimers();
    const logDir = mkdtempSync(join(tmpdir(), "spawn-timeout-r12-"));
    try {
      const dispatch = dispatchMonitoredCliWorker({
        command: "fake-worker",
        args: [],
        logDir,
        poolId: "test/fake",
        completionSignal: "DONE",
        stepId: "spawn-timeout",
      });
      const rejected = expect(dispatch).rejects.toMatchObject({
        name: "ExternalCallTimeoutError",
        stage: "dispatch:spawn-timeout:spawn",
      });

      await vi.advanceTimersByTimeAsync(2_100);
      await rejected;
      expect(fakeChildState.signals).toEqual(["SIGTERM", "SIGKILL"]);
    } finally {
      rmSync(logDir, { recursive: true, force: true });
    }
  });
});
