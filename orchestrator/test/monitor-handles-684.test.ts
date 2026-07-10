/**
 * #684 — monitor handles atomically produced at dispatch; judge/kill only via handle.
 */

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

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
} from "../src/workerMonitor.js";
import type { PersistentLedgerEntry, WorkerSpec } from "../src/types.js";

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

describe("#684 worker monitor handles", () => {
  it("dispatchMonitoredCliWorker atomically returns pid/log/pool/signal handle", async () => {
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
      const handle = {
        pid: process.pid,
        logPath,
        poolId: "zai/glm-5.2",
        completionSignal: "SHIP_STEP_COMPLETE",
        stepId: "S7",
        dispatchedAt: new Date().toISOString(),
      };
      const first = readLogActivity(handle);
      expect(first.sizeBytes).toBeGreaterThan(0);
      expect(first.mtimeMs).toBeGreaterThan(0);

      await new Promise((resolve) => setTimeout(resolve, 20));
      writeFileSync(logPath, "line1\nline2\n", "utf8");
      const second = readLogActivity(handle);
      expect(second.sizeBytes).toBeGreaterThan(first.sizeBytes);
      expect(isWorkerIdle(handle, 60_000, first)).toBe(false);

      const stale = readLogActivity(handle);
      expect(isWorkerIdle(handle, 0, stale)).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("hasCompletionSignalInLog detects the expected completion signal in handle log", () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-684-signal-"));
    try {
      const logPath = join(dir, "worker.log");
      const handle = {
        pid: 1,
        logPath,
        poolId: "opencode-go/kimi",
        completionSignal: "VERIFY_STEP_COMPLETE",
        stepId: "S9",
        dispatchedAt: new Date().toISOString(),
      };
      writeFileSync(logPath, "working...\n", "utf8");
      expect(hasCompletionSignalInLog(handle)).toBe(false);
      writeFileSync(logPath, "working...\nVERIFY_STEP_COMPLETE\n", "utf8");
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

  it("monitor handle round-trips through ledger entries for resume rebuild", () => {
    const handle = {
      pid: 4242,
      logPath: "/tmp/scratch/worker-a.log",
      poolId: "grok/composer",
      completionSignal: "SHIP_STEP_COMPLETE",
      stepId: "S7",
      dispatchedAt: "2026-07-08T12:00:00.000Z",
    };
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
});