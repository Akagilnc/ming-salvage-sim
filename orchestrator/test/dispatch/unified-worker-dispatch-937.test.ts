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
  readFileSync,
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
  canRelayHandoff,
  countRelayHandoffsInLedger,
  renderEphemeralRelayBrief,
  buildRelayHandoffLedgerEntry,
} from "../../src/relayDispatch.js";

/** Retired focus-file name — assert it is never produced (#937 / ID-007). */
const RELAY_FOCUS_FILENAME = ".relay-focus.md";
import {
  RECEIPT_MAX_RETRIES,
  receiptMaxRetriesForProvider,
  workerReceiptOutput,
  coderReceiptOutput,
} from "../../src/receiptRecovery.js";
import { coderStationReceiptSchema } from "../../src/stationReceiptContracts.js";
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

function quotaWallError(now: Date, resetAt: Date): QuotaWaitForResetError {
  return new QuotaWaitForResetError({
    disposition: {
      kind: "wait_for_reset",
      pool: "grok",
      resetAt,
      reason: "quota limited",
    },
    applied: {
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
    pool: "grok"
  });
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
      // #934 ID-004 / #937: canonical failed edge — attempt count only, no baton.
      expect(result.reason).toMatch(/after 6 dispatch attempts/i);
      expect(result.reason).not.toMatch(/relay candidate/i);
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

  it("POSITIVE: production attach expression maps grok→0 and codex→RECEIPT_MAX_RETRIES", async () => {
    // Production attach (realBackend.outputFor / family receiptMaxRetriesFor):
    //   provider = resolveModelSlugForPool(model, pool).provider
    //   maxRetries = receiptMaxRetriesForProvider(provider)
    //   coderReceiptOutput(schema, tag, maxRetries)
    const { resolveModelSlugForPool } = await import("../../src/modelRegistry.js");
    const { readFileSync: readSrc } = await import("node:fs");
    const realBackendSrc = readSrc(
      join(import.meta.dirname, "../../src/realBackend.ts"),
      "utf8",
    );
    const familySrc = readSrc(
      join(import.meta.dirname, "../../src/family/realFamilyBackend.ts"),
      "utf8",
    );
    // Production sites must call the provider→maxRetries seam (not hardcode 2).
    expect(realBackendSrc).toMatch(/receiptMaxRetriesForProvider\(provider\)/);
    expect(realBackendSrc).toMatch(/coderReceiptOutput\([\s\S]*maxRetries/);
    expect(familySrc).toMatch(/receiptMaxRetriesFor\(/);
    expect(familySrc).toMatch(/coderReceiptOutput\([\s\S]*this\.receiptMaxRetriesFor/);

    const attachFor = (model: string) => {
      const provider = resolveModelSlugForPool(model).provider;
      const maxRetries = receiptMaxRetriesForProvider(provider);
      return coderReceiptOutput(
        coderStationReceiptSchema(),
        "coder",
        maxRetries,
      );
    };
    expect(attachFor("grok-4.5")).toMatchObject({ tag: "coder", maxRetries: 0 });
    expect(attachFor("gpt-5.6-terra")).toMatchObject({
      tag: "coder",
      maxRetries: RECEIPT_MAX_RETRIES,
    });
    // NEGATIVE: unknown/non-resumable custom provider stays at 0
    expect(receiptMaxRetriesForProvider("agy")).toBe(0);
  });

  it("NEGATIVE: QuotaWaitForResetError does not burn onAttempt durable budget", async () => {
    const attempts: number[] = [];
    let calls = 0;
    const err = quotaWallError(
      new Date("2026-07-10T12:00:00.000Z"),
      new Date("2026-07-10T13:00:00.000Z"),
    );
    await expect(
      withMechanicalRetry(
        coderSpec(),
        {},
        async () => {
          calls += 1;
          throw err;
        },
        {
          onAttempt: async (attempt) => {
            attempts.push(attempt);
          },
          sleepMs: async () => {},
        },
      ),
    ).rejects.toBeInstanceOf(QuotaWaitForResetError);
    expect(calls).toBe(1);
    expect(attempts).toEqual([]);
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

  it("POSITIVE: long-lived silent child is never host-killed (ID-007)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-long-silence-"));
    tempDirs.push(dir);
    const killed: number[] = [];
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        // Stay alive well past former idle tiers (10/30 min) — compressed via
        // instant sleepMs inject; real wall is process exit only.
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 200)"],
        logDir: dir,
        poolId: "zai",
        stepId: "S2",
        readInstanceId: () => "test-instance-long",
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
          readInstanceId: () => "test-instance-long",
          killPid: (pid) => killed.push(pid),
          // No idle poll path remains — sleepMs is only used by terminateSpawnedChild.
          sleepMs: async () => {},
        },
      },
    );
    expect(outcome.result.kind).toBe("completed");
    expect(killed).toEqual([]);
  });

  it("POSITIVE: parkOrRelayQuotaWall prefers same-model other live pool first (ID-008)", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-park-order-"));
    tempDirs.push(dir);
    const ledger: Array<Record<string, unknown>> = [];
    const now = new Date("2026-07-10T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const err = quotaWallError(now, resetAt);

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
        {
          id: "codex-5h",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["terra@med", "luna@med"],
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

    expect(outcome.kind).toBe("relay");
    if (outcome.kind !== "relay") return;
    // Same-model alternate live pool first (cursor), not roster-next terra.
    expect(outcome.nextBaton.modelId).toBe("grok-4.5");
    expect(outcome.nextBaton.pool).toBe("cursor");
    expect(outcome.relayBrief).toMatch(/cursor/);
    expect(existsSync(join(dir, RELAY_FOCUS_FILENAME))).toBe(false);
  });

  it("NEGATIVE: no-wrap-around when only earlier roster seats are live → park", async () => {
    const dir = mkdtempSync(join(tmpdir(), "orch-937-no-wrap-"));
    tempDirs.push(dir);
    const ledger: Array<Record<string, unknown>> = [];
    const now = new Date("2026-07-10T12:00:00.000Z");
    const resetAt = new Date(now.getTime() + 2 * DEFAULT_PARK_THRESHOLD_MS);
    const err = quotaWallError(now, resetAt);

    // Current seat is terra; only earlier roster model (grok) is live → no wrap.
    const outcome = await parkOrRelayQuotaWall({
      step: "S2",
      err,
      ledger: ledger as never,
      stateDir: dir,
      sessionId: "sess",
      worktreePath: dir,
      now,
      parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
      currentModelId: "terra@med",
      currentPool: "codex-5h",
      rosterOrder: resolveCoderRecOrder(
        "Coder-Rec: grok-4.5 → terra@med → luna@med",
      ),
      pools: [
        {
          id: "grok-build",
          status: "live",
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
        {
          id: "codex-5h",
          status: "limited",
          resetAt,
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["terra@med", "luna@med"],
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

    // No later roster seat with a live pool → park (not wrap to grok).
    expect(outcome.kind).toBe("park");
    expect(existsSync(join(dir, RELAY_FOCUS_FILENAME))).toBe(false);
  });
});

describe("#937 public runOrchestrator — ID-008 review/fix stay-put", () => {
  type DispatchContext = import("../../src/types.js").DispatchContext;
  type WorktreeHandle = import("../../src/types.js").WorktreeHandle;
  type IssueMeta = import("../../src/types.js").IssueMeta;
  type StepOutput = import("../../src/types.js").StepOutput;
  type PersistentLedgerEntry = import("../../src/types.js").PersistentLedgerEntry;

  function baseStayPutBackend(
    tmp: string,
    dispatch: (
      spec: WorkerSpec,
      ctx: DispatchContext,
    ) => Promise<WorkerResult>,
    ledgerWrites: PersistentLedgerEntry[],
  ): Backend {
    const worktree: WorktreeHandle = {
      branch: "feat/937-stayput",
      base: "main",
      path: tmp,
    };
    return {
      async smokeModelRoute(route: never): Promise<never> {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route as never, async () => ({
          cliVersion: "test",
        })) as never;
      },
      async findResumeState(): Promise<undefined> {
        return undefined;
      },
      async resumeSession(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5",
        };
      },
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      },
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
        ledgerWrites.push(entry);
      },
      dispatchWorker: dispatch,
    } as Backend;
  }

  it("POSITIVE: S3 quota no-candidate stay-puts non-terminal with durable audit (#926)", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../src/reviewLoopOutcome.js"
    );

    const tmp = mkdtempSync(join(tmpdir(), "orch-937-stayput-"));
    tempDirs.push(tmp);
    const resetAt = new Date("2026-07-10T14:00:00.000Z");
    const ledgerWrites: PersistentLedgerEntry[] = [];
    let s3Hits = 0;
    let s5Hits = 0;
    let s6Hits = 0;

    const backend = baseStayPutBackend(
      tmp,
      async (spec) => {
        if (spec.id === "S2") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.id === "S3") {
          s3Hits += 1;
          throw quotaWallError(
            new Date("2026-07-10T12:00:00.000Z"),
            resetAt,
          );
        }
        if (spec.id === "S5") {
          s5Hits += 1;
          // First stay-put cycle returns to fixer desk; succeed so the run can
          // complete without a second consecutive no-baton wall.
          return {
            kind: "completed",
            output: { kind: "coder", committed: false, commitsAdded: 0 },
          };
        }
        if (spec.id === "S6") {
          s6Hits += 1;
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
      ledgerWrites,
    );

    // #926: first no-candidate stay-put is non-terminal (return via topology).
    const result = await runOrchestrator({
      issueNumber: 937,
      backend,
      relayPools: [
        {
          id: "grok-build",
          status: "limited",
          resetAt,
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
      ],
      now: () => new Date("2026-07-10T12:00:00.000Z"),
    });

    // Never terminal solely from the first no-candidate stay-put.
    expect(result.status).not.toBe("error");
    expect(s3Hits).toBe(1);
    // Topology continues to S5 (unusable→fixer) then S6 (judge) without S8 invent.
    expect(s5Hits).toBe(1);
    expect(s6Hits).toBe(1);

    const stayPutMem = result.stepLedger.find(
      (e) => e.event === "coder_advance_stay_put",
    );
    expect(stayPutMem).toMatchObject({
      event: "coder_advance_stay_put",
      reason: expect.stringMatching(/stay-put|no live baton/i),
    });
    const stayPutDisk = ledgerWrites.find(
      (e) => e.event === "coder_advance_stay_put",
    );
    expect(stayPutDisk).toMatchObject({
      event: "coder_advance_stay_put",
      reason: expect.stringMatching(/quota wall stay-put on S3/i),
    });
  });

  it("POSITIVE: S5 quota no-candidate stay-puts once and returns to judge (#926)", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../src/reviewLoopOutcome.js"
    );

    const tmp = mkdtempSync(join(tmpdir(), "orch-937-s5stay-"));
    tempDirs.push(tmp);
    const resetAt = new Date("2026-07-10T14:00:00.000Z");
    const ledgerWrites: PersistentLedgerEntry[] = [];
    let s5Hits = 0;
    let s6Hits = 0;

    const backend = baseStayPutBackend(
      tmp,
      async (spec) => {
        if (spec.id === "S2") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.id === "S3") {
          return {
            kind: "completed",
            output: {
              kind: "judge",
              status: "continue",
              findingDispositions: [
                {
                  identityKey: "correctness|x.ts:1|live",
                  action: "live",
                },
              ],
            },
          };
        }
        if (spec.id === "S5") {
          s5Hits += 1;
          throw quotaWallError(
            new Date("2026-07-10T12:00:00.000Z"),
            resetAt,
          );
        }
        if (spec.id === "S6") {
          s6Hits += 1;
          return {
            kind: "completed",
            output: { kind: "judge", status: "converged" },
          };
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
      ledgerWrites,
    );

    const result = await runOrchestrator({
      issueNumber: 937,
      backend,
      relayPools: [
        {
          id: "grok-build",
          status: "limited",
          resetAt,
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
      ],
      now: () => new Date("2026-07-10T12:00:00.000Z"),
    });

    // #926: return to judge (S6), never terminal from first stay-put; no S5 hot-loop.
    expect(result.status).not.toBe("error");
    expect(s5Hits).toBe(1);
    expect(s6Hits).toBe(1);
    expect(
      ledgerWrites.filter((e) => e.event === "coder_advance_stay_put"),
    ).toHaveLength(1);
    expect(result.errorPackage).toBeUndefined();
  });

  it("POSITIVE: second consecutive quota stay-put parks for reset — never S8 error (#926)", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../src/reviewLoopOutcome.js"
    );

    const tmp = mkdtempSync(join(tmpdir(), "orch-937-2stay-"));
    tempDirs.push(tmp);
    const resetAt = new Date("2026-07-10T14:00:00.000Z");
    const ledgerWrites: PersistentLedgerEntry[] = [];
    let s3Hits = 0;
    let s5Hits = 0;

    const backend = baseStayPutBackend(
      tmp,
      async (spec) => {
        if (spec.id === "S2") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.id === "S3" || spec.id === "S5" || spec.id === "S6") {
          if (spec.id === "S3") s3Hits += 1;
          if (spec.id === "S5") s5Hits += 1;
          throw quotaWallError(
            new Date("2026-07-10T12:00:00.000Z"),
            resetAt,
          );
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
      ledgerWrites,
    );

    const result = await runOrchestrator({
      issueNumber: 937,
      backend,
      relayPools: [
        {
          id: "grok-build",
          status: "limited",
          resetAt,
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
      ],
      now: () => new Date("2026-07-10T12:00:00.000Z"),
    });

    // After return-to-judge cycle still no baton → park (ID-001), not S8 error.
    expect(result.status).toBe("escalate");
    expect(result.status).not.toBe("error");
    expect(result.stopSummary?.reason).toBe("provider_degraded");
    expect(result.stopSummary?.summary ?? "").toMatch(/quota wait for reset/i);
    expect(
      ledgerWrites.filter((e) => e.event === "coder_advance_stay_put").length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      ledgerWrites.some((e) => e.event === "quota_wait_for_reset"),
    ).toBe(true);
    // First stay-put redispatches via topology; second parks — not infinite S5 loop.
    expect(s3Hits).toBeGreaterThanOrEqual(1);
    expect(s5Hits).toBeLessThanOrEqual(2);
  });

  it("NEGATIVE: stay-put writeLedger failure surfaces record_persist_failed", async () => {
    const { runOrchestrator } = await import("../../src/runner.js");
    const { skeletonReviewLoopWorkerResult } = await import(
      "../../src/reviewLoopOutcome.js"
    );

    const tmp = mkdtempSync(join(tmpdir(), "orch-937-stayfail-"));
    tempDirs.push(tmp);
    const resetAt = new Date("2026-07-10T14:00:00.000Z");
    const worktree: WorktreeHandle = {
      branch: "feat/937-stayfail",
      base: "main",
      path: tmp,
    };

    const backend = {
      async smokeModelRoute(route: never): Promise<never> {
        const { smokeRouteModels } = await import("../../src/modelRoutes.js");
        return smokeRouteModels(route as never, async () => ({
          cliVersion: "test",
        })) as never;
      },
      async findResumeState(): Promise<undefined> {
        return undefined;
      },
      async resumeSession(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async fetchIssueMeta(n: number): Promise<IssueMeta> {
        return {
          number: n,
          isReadyForAgent: true,
          hasSubIssues: false,
          isClosed: false,
          openBlockedBy: [],
          body: "Coder-Rec: grok-4.5",
        };
      },
      async prepareWorktree(): Promise<WorktreeHandle> {
        return worktree;
      },
      async runStep(): Promise<StepOutput> {
        return { kind: "coder", committed: true, commitsAdded: 1 };
      },
      async writeLedger(entry: PersistentLedgerEntry): Promise<void> {
        if (entry.event === "coder_advance_stay_put") {
          throw new Error("disk full");
        }
      },
      async dispatchWorker(spec: WorkerSpec): Promise<WorkerResult> {
        if (spec.id === "S2") {
          return {
            kind: "completed",
            output: { kind: "coder", committed: true, commitsAdded: 1 },
          };
        }
        if (spec.id === "S3") {
          throw quotaWallError(
            new Date("2026-07-10T12:00:00.000Z"),
            resetAt,
          );
        }
        const skeleton = skeletonReviewLoopWorkerResult(spec.kind);
        if (skeleton !== undefined) return skeleton;
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
    } as Backend;

    const result = await runOrchestrator({
      issueNumber: 937,
      backend,
      relayPools: [
        {
          id: "grok-build",
          status: "limited",
          resetAt,
          parkThresholdMs: DEFAULT_PARK_THRESHOLD_MS,
          models: ["grok-4.5"],
        },
      ],
      now: () => new Date("2026-07-10T12:00:00.000Z"),
    });

    expect(result.status).toBe("error");
    expect(result.errorPackage?.reason ?? "").toMatch(
      /record_persist_failed.*coder_advance_stay_put/i,
    );
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

  it("POSITIVE: production surface deletes idle-kill + free-log fate machinery", async () => {
    const monitor = await import("../../src/workerMonitor.js");
    const dispatch = await import("../../src/dispatchWorker.js");
    const relay = await import("../../src/relayDispatch.js");
    const probe = await import("../../src/quotaProbe.js");

    expect("killWorkerTree" in monitor).toBe(false);
    expect("collectPidTree" in monitor).toBe(false);
    expect("isWorkerIdle" in monitor).toBe(false);
    expect("isWorkerAlive" in monitor).toBe(false);
    expect("readLogTail" in monitor).toBe(false);
    expect("resolveWorkerMonitorIdleThresholdMs" in dispatch).toBe(false);
    expect("buildRelayFocusFile" in relay).toBe(false);
    expect("decideRelayAfterIdle" in relay).toBe(false);
    expect("stageRelayFocusFile" in relay).toBe(false);
    expect("HangWithLivePoolError" in relay).toBe(false);
    expect("SelfReportedRelayError" in relay).toBe(false);
    expect("tryParseActionableRelayTag" in relay).toBe(false);
    expect("parseRelayTag" in relay).toBe(false);

    // Idle→quota composition + host kill surface deleted (ID-007 / ID-006).
    const src = readFileSync(
      join(import.meta.dirname, "../../src/quotaProbe.ts"),
      "utf8",
    );
    expect(src).not.toMatch(/killPidTree\s*:/);
    expect(src).not.toMatch(/await actions\.killPidTree/);
    expect(src).not.toMatch(/function handleIdleThreshold/);
    expect(src).not.toMatch(/function withIdleQuotaProbeDisposition/);
    expect(src).not.toMatch(/export interface IdleQuotaActions/);
    expect(src).not.toMatch(/readonly killed:\s*boolean/);
    // free-log parsers must not remain as live production exports.
    const relaySrc = readFileSync(
      join(import.meta.dirname, "../../src/relayDispatch.ts"),
      "utf8",
    );
    expect(relaySrc).not.toMatch(/export class HangWithLivePoolError/);
    expect(relaySrc).not.toMatch(/export class SelfReportedRelayError/);
    expect(relaySrc).not.toMatch(/export function tryParseActionableRelayTag/);
    expect(relaySrc).not.toMatch(/export function parseRelayTag/);
    void probe;
  });
});
