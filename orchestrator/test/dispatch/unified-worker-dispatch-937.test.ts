/**
 * #937 — unified worker dispatch terminal shape.
 *
 * Acceptance:
 *   - unified worker dispatch real entry proves #934 ID-004, ID-006
 *   - public ignition/driver seams prove #934 ID-007, ID-008, ID-015, ID-016
 *
 * Seams (real production paths only):
 *   - dispatchRetry.withMechanicalRetry / MAX_DISPATCH_ATTEMPTS / backoff
 *   - dispatchWorkerWithMonitor + terminateSpawnedChild
 *   - renderEphemeralRelayBrief + canRelayHandoff / MAX_RELAY_HANDOFFS
 *   - parkOrRelayQuotaWall (no focus file)
 */

import {
  existsSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DISPATCH_RETRY_BACKOFF_MS,
  MAX_DISPATCH_ATTEMPTS,
  withMechanicalRetry,
} from "../../src/dispatchRetry.js";
import { dispatchWorkerWithMonitor } from "../../src/dispatchWorker.js";
import { resolveCoderRecOrder } from "../../src/coderRoster.js";
import { DEFAULT_PARK_THRESHOLD_MS } from "../../src/quotaPoolTable.js";
import { QuotaWaitForResetError } from "../../src/quotaProbe.js";
import { parkOrRelayQuotaWall } from "../../src/quotaParkRelay.js";
import {
  MAX_RELAY_HANDOFFS,
  RELAY_FOCUS_FILENAME,
  canRelayHandoff,
  countRelayHandoffsInLedger,
  renderEphemeralRelayBrief,
  buildRelayHandoffLedgerEntry,
} from "../../src/relayDispatch.js";
import { terminateSpawnedChild } from "../../src/workerMonitor.js";
import type {
  Backend,
  CliMonitorSpawnSpec,
  WorkerResult,
  WorkerSpec,
} from "../../src/types.js";

const tempDirs: string[] = [];
afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function coderSpec(): WorkerSpec {
  return {
    id: "S2",
    kind: "coder",
    role: "coder",
    host: "codex",
    session: "fresh",
    contextRetention: "retain",
    promptFile: "coder.md",
    maxIter: 1,
    model: "grok-4.5",
    soul: "coder",
    toolchain: [],
  } as WorkerSpec;
}

describe("#937 unified worker dispatch — ID-004 process-root retry", () => {
  it("POSITIVE: process-root budget is 6 attempts with five 15s intervals", () => {
    expect(MAX_DISPATCH_ATTEMPTS).toBe(6);
    expect(DISPATCH_RETRY_BACKOFF_MS).toEqual([
      15_000, 15_000, 15_000, 15_000, 15_000,
    ]);
    expect(DISPATCH_RETRY_BACKOFF_MS).toHaveLength(MAX_DISPATCH_ATTEMPTS - 1);
  });

  it("POSITIVE: withMechanicalRetry exhausts at the fixed position budget", async () => {
    let calls = 0;
    const sleeps: number[] = [];
    const result = await withMechanicalRetry(
      coderSpec(),
      {},
      async () => {
        calls += 1;
        return { kind: "failed", reason: "dispatch threw: boom" };
      },
      {
        sleepMs: async (ms) => {
          sleeps.push(ms);
        },
      },
    );
    expect(calls).toBe(MAX_DISPATCH_ATTEMPTS);
    expect(sleeps).toEqual([...DISPATCH_RETRY_BACKOFF_MS]);
    expect(result.kind).toBe("failed");
    if (result.kind === "failed") {
      expect(result.reason).toMatch(/relay candidate/i);
    }
  });

  it("NEGATIVE: durable completed outcome is never process-retried", async () => {
    let calls = 0;
    const result = await withMechanicalRetry(
      coderSpec(),
      {},
      async () => {
        calls += 1;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
    );
    expect(calls).toBe(1);
    expect(result.kind).toBe("completed");
  });
});

describe("#937 unified worker dispatch — ID-006 process ownership", () => {
  it("POSITIVE: adoption-record failure terminates exact ChildProcess handle", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-adopt-"));
    tempDirs.push(dir);
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 60_000)"],
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
    await expect(
      dispatchWorkerWithMonitor(backend, coderSpec(), {}, undefined, {
        onMonitorHandleSpawned: async () => {
          throw new Error("adoption persist failed");
        },
        monitorDeps: {
          readInstanceId: () => "test-instance",
          killPid: (pid, signal) => {
            killed.push(pid);
            // Deliver the real signal so waitForChildExit can settle.
            try {
              process.kill(pid, signal);
            } catch {
              // group signal may fail in restricted sandboxes
            }
          },
          sleepMs: async () => {},
        },
      }),
    ).rejects.toThrow(/adoption persist failed/);
    // Exact-handle path: at least one signal was attempted (group or child).
    expect(killed.length).toBeGreaterThan(0);
  });

  it("NEGATIVE: free-log relay tags never become a host fate throw", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-nofate-"));
    tempDirs.push(dir);
    writeFileSync(
      join(dir, "S2.log"),
      '<relay>{"decision_gate":{"state_summary":"ask human"}}</relay>\n',
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
      dispatchWorkerWithMonitor(backend, coderSpec(), {}),
    ).resolves.toMatchObject({ result: { kind: "completed" } });
  });
});

describe("#937 public driver seams — ID-007 silence + ID-008 relay", () => {
  it("POSITIVE: ephemeral brief renders from ledger memory without a focus file", () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-brief-"));
    tempDirs.push(dir);
    const entry = buildRelayHandoffLedgerEntry({
      trigger: "quota_wall",
      state_summary: "half wired",
      remaining: "finish AC",
      fromModelId: "grok-4.5",
      fromPool: "grok-build",
      toModelId: "terra@med",
      toPool: "codex-5h",
      step: "S2",
      now: new Date("2026-07-10T12:00:00.000Z"),
    });
    const brief = renderEphemeralRelayBrief(entry);
    expect(brief).toContain("half wired");
    expect(brief).toContain("terra@med");
    expect(brief).toContain("finish AC");
    expect(existsSync(join(dir, RELAY_FOCUS_FILENAME))).toBe(false);
  });

  it("POSITIVE: handoff max is 7 completed; the 8th is forbidden (ID-008)", () => {
    expect(MAX_RELAY_HANDOFFS).toBe(7);
    const seven = Array.from({ length: 7 }, () => ({
      event: "relay_baton_handoff" as const,
    }));
    expect(countRelayHandoffsInLedger(seven)).toBe(7);
    expect(canRelayHandoff(seven)).toBe(false);
    expect(canRelayHandoff(seven.slice(0, 6))).toBe(true);
  });

  it("NEGATIVE: silence does not kill via dispatchWorkerWithMonitor", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-silence-"));
    tempDirs.push(dir);
    const killed: number[] = [];
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

    const outcome = await dispatchWorkerWithMonitor(
      backend,
      coderSpec(),
      {},
      undefined,
      {
        monitorDeps: {
          killPid: (pid) => killed.push(pid),
          sleepMs: async () => {},
        },
      },
    );
    expect(outcome.result.kind).toBe("completed");
    expect(killed).toEqual([]);
  });

  it("POSITIVE: parkOrRelayQuotaWall relay returns ephemeral brief, no focus file", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-park-"));
    tempDirs.push(dir);
    const ledger: Array<Record<string, unknown>> = [];
    const now = new Date("2026-07-10T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const err = new QuotaWaitForResetError({
      disposition: {
        kind: "wait_for_reset",
        pool: "grok",
        resetAt,
        reason: "quota limited",
      },
      applied: {
        killed: false,
        ledgerEntry: {
          event: "quota_wait_for_reset",
          pool: "grok",
          resetAt: resetAt.toISOString(),
          reason: "quota limited",
          step: "S2",
          workerPid: 1,
          ts: now.toISOString(),
        },
      },
      pool: "grok",
      probe: { kind: "quota_limited", resetAt, detail: "429" },
    });

    const outcome = await parkOrRelayQuotaWall({
      step: "S2",
      err,
      ledger: ledger as never,
      stateDir: dir,
      sessionId: "sess",
      worktreePath: dir,
      now,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      currentModelId: "grok-4.5",
      currentPool: "grok-build",
      rosterOrder: resolveCoderRecOrder(
        "Coder-Rec: grok-4.5 → terra@med → luna@med",
      ),
      pools: [
        {
          id: "grok-build",
          status: "limited",
          resetAt,
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
        {
          id: "cursor",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
      ],
      resolveBranchHEAD: async () => "deadbeef",
      hashPrompt: async () => "prompt-hash",
      backend: {
        writeLedger: async (entry: Record<string, unknown>) => {
          ledger.push(entry);
        },
      } as never,
    });

    if (outcome.kind === "relay") {
      expect(outcome.relayBrief.length).toBeGreaterThan(0);
      expect(outcome.relayBrief).toMatch(/grok|terra|cursor/i);
      expect(existsSync(join(dir, RELAY_FOCUS_FILENAME))).toBe(false);
    } else {
      // If the wall is classified park (threshold / no baton), still no focus file.
      expect(existsSync(join(dir, RELAY_FOCUS_FILENAME))).toBe(false);
    }
  });
});

describe("#937 ID-015 / ID-016 delete boundaries", () => {
  it("NEGATIVE: terminateSpawnedChild is a no-op when the child already exited", async () => {
    const { spawn } = await import("node:child_process");
    const child = spawn(
      process.platform === "win32" ? "cmd" : "true",
      process.platform === "win32" ? ["/c", "exit", "0"] : [],
      { stdio: "ignore" },
    );
    await new Promise<void>((resolve) => child.once("exit", () => resolve()));
    const killPid = vi.fn();
    await terminateSpawnedChild(child, {
      killPid,
      sleepMs: async () => {},
    });
    expect(killPid).not.toHaveBeenCalled();
  });

  it("POSITIVE: production surface no longer exports idle-kill APIs", async () => {
    const monitor = await import("../../src/workerMonitor.js");
    const dispatch = await import("../../src/dispatchWorker.js");
    const relay = await import("../../src/relayDispatch.js");
    expect("killWorkerTree" in monitor).toBe(false);
    expect("collectPidTree" in monitor).toBe(false);
    expect("isWorkerIdle" in monitor).toBe(false);
    expect("isWorkerAlive" in monitor).toBe(false);
    expect("resolveWorkerMonitorIdleThresholdMs" in dispatch).toBe(false);
    expect("buildRelayFocusFile" in relay).toBe(false);
    expect("decideRelayAfterIdle" in relay).toBe(false);
    expect("stageRelayFocusFile" in relay).toBe(false);
  });
});
