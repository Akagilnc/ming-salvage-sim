/**
 * #786 — telemetry sidecar: pure writers/extractors + dispatch/collect integration.
 */

import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { dispatchWorkerWithMonitor } from "../src/dispatchWorker.js";
import { resolveRouteModels, routeSmokeEntries } from "../src/modelRoutes.js";
import {
  appendTelemetryRecord,
  buildCollectStamp,
  buildDispatchStamp,
  buildEnvironmentStamp,
  categoryFromReason,
  classifyWorkerTerminal,
  ensureEnvironmentStamp,
  extractClaudeTokens,
  extractCodexTokens,
  extractTokensFromLog,
  newLegId,
  readTelemetryRecords,
  TELEMETRY_FILENAME,
  tryAppendTelemetryRecord,
  type TelemetryCollectRecord,
  type TelemetryDispatchRecord,
  type TelemetryEnvironmentRecord,
} from "../src/telemetry.js";
import type {
  Backend,
  CliMonitorSpawnSpec,
  DispatchContext,
  WorkerResult,
  WorkerSpec,
} from "../src/types.js";

const tempDirs: string[] = [];

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function tempDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(dir);
  return dir;
}

function baseSpec(overrides: Partial<WorkerSpec> = {}): WorkerSpec {
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
    model: "gpt-5.6-terra",
    soul: "coder",
    toolchain: [],
    ...overrides,
  };
}

function smokedRoute() {
  const base = resolveRouteModels("normal", {});
  const smoke = Object.fromEntries(
    routeSmokeEntries(base).map((entry) => [
      entry.key,
      {
        state: "passed" as const,
        at: new Date().toISOString(),
        cliVersion: `cli-${entry.slug}`,
      },
    ]),
  );
  return resolveRouteModels("normal", {}, {}, smoke);
}

// ───────────────────────── pure unit tests ─────────────────────────

describe("#786 telemetry pure helpers", () => {
  it("extractCodexTokens parses `tokens used\\nN` and `tokens used: N`", () => {
    expect(extractCodexTokens("noise\ntokens used\n27,290\nmore")).toEqual({
      input: null,
      output: null,
      cached: null,
      total: 27290,
    });
    expect(extractCodexTokens("tokens used: 12345")).toEqual({
      input: null,
      output: null,
      cached: null,
      total: 12345,
    });
    expect(extractCodexTokens("no usage here")).toBeNull();
  });

  it("extractCodexTokens prefers the last tokens-used block", () => {
    const log = "tokens used\n100\n…work…\ntokens used\n9,999\n";
    expect(extractCodexTokens(log)?.total).toBe(9999);
  });

  it("extractClaudeTokens parses JSON-ish usage fields", () => {
    const log =
      'result {"usage":{"input_tokens":1200,"output_tokens":340,"cache_read_input_tokens":50}}';
    expect(extractClaudeTokens(log)).toEqual({
      input: 1200,
      output: 340,
      cached: 50,
      total: 1540,
    });
  });

  it("extractClaudeTokens parses human Usage lines", () => {
    const log = "Usage: input: 10 tokens output: 20 tokens cache: 3\n";
    expect(extractClaudeTokens(log)).toEqual({
      input: 10,
      output: 20,
      cached: 3,
      total: 30,
    });
  });

  it("extractTokensFromLog picks codex family first", () => {
    const log = "tokens used\n42\ninput_tokens: 1 output_tokens: 2\n";
    expect(extractTokensFromLog(log, "codex")?.total).toBe(42);
    expect(extractTokensFromLog(log, "claude")?.input).toBe(1);
  });

  it("classifyWorkerTerminal maps results and known thrown errors", () => {
    expect(
      classifyWorkerTerminal({
        kind: "result",
        result: {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
          sessionId: "sess-1",
        },
      }),
    ).toEqual({
      terminal: "completed",
      errorCategory: null,
      errorMessage: null,
      sessionId: "sess-1",
    });

    expect(
      classifyWorkerTerminal({
        kind: "result",
        result: { kind: "failed", reason: "rate limit 429 from provider" },
      }).errorCategory,
    ).toBe("429-quota");

    expect(
      classifyWorkerTerminal({
        kind: "thrown",
        error: new Error("monitored worker idle hang: S2"),
      }).errorCategory,
    ).toBe("hang-idle");

    // Real Sandcastle / realBackend idle rethrow (exact production shape).
    const realIdle =
      "Agent idle for 600 seconds — no output received. Consider increasing " +
      "the idle timeout with --idle-timeout.";
    expect(categoryFromReason(realIdle)).toBe("hang-idle");
    expect(
      classifyWorkerTerminal({
        kind: "thrown",
        error: Object.assign(new Error(realIdle), {
          name: "AgentIdleTimeoutError",
          _tag: "AgentIdleTimeoutError",
        }),
      }).errorCategory,
    ).toBe("hang-idle");
    // Message-only path (no tag) must still classify — categoryFromReason.
    expect(
      classifyWorkerTerminal({
        kind: "thrown",
        error: new Error(realIdle),
      }).errorCategory,
    ).toBe("hang-idle");

    expect(
      classifyWorkerTerminal({
        kind: "thrown",
        error: new Error("stream disconnect mid-response"),
      }).errorCategory,
    ).toBe("stream-disconnect");
  });

  it("categoryFromReason maps realBackend max-iteration completion-signal text to honest-incomplete", () => {
    // Exact shape from realBackend.assertCompletionSignal (realBackend.ts:~1095).
    const realMaxIter =
      'realBackend: step S2 did not fire its required completion ' +
      'signal — expected "<coder>", got none (no signal fired before the ' +
      "iteration limit). The agent must emit the completion signal to advance " +
      'the step (#244 "agent emit completionSignal 才进下一步"); a ' +
      "complete-but-unsignaled run (e.g. maxIter hit mid-work) does NOT advance.";
    expect(categoryFromReason(realMaxIter)).toBe("honest-incomplete");

    // ship / cmr / merger gate reasons (shipOutcome / realFamilyBackend).
    expect(
      categoryFromReason("ship worker did not fire its completion signal"),
    ).toBe("honest-incomplete");
    expect(
      categoryFromReason("cmr worker did not fire its completion signal"),
    ).toBe("honest-incomplete");
    expect(
      categoryFromReason(
        'merger agent did not fire its completion signal — expected ' +
          '"<merger_resolved>", got none (no signal fired before the iteration limit)',
      ),
    ).toBe("honest-incomplete");

    // Fragment alone (embedded in diagnosis text).
    expect(
      categoryFromReason("none (no signal fired before the iteration limit)"),
    ).toBe("honest-incomplete");

    // Must not classify as 429-quota via bare "limit" / must preserve message.
    const classified = classifyWorkerTerminal({
      kind: "thrown",
      error: new Error(realMaxIter),
    });
    expect(classified.terminal).toBe("thrown");
    expect(classified.errorCategory).toBe("honest-incomplete");
    expect(classified.errorMessage).toBe(realMaxIter);
  });

  it("categoryFromReason returns unclassified (not null) for unknown failures and keeps message", () => {
    expect(categoryFromReason("totally novel backend boom XYZ")).toBe(
      "unclassified",
    );
    const classified = classifyWorkerTerminal({
      kind: "result",
      result: { kind: "failed", reason: "weird provider glitch code 0xdead" },
    });
    expect(classified.errorCategory).toBe("unclassified");
    expect(classified.errorMessage).toBe("weird provider glitch code 0xdead");
  });

  it("appendTelemetryRecord writes atomic JSONL lines under ledgerDir", () => {
    const dir = tempDir("orch-786-write-");
    const legId = newLegId();
    appendTelemetryRecord(
      dir,
      buildEnvironmentStamp({
        ctx: {},
        imageTag: "ming-orchestrator-coder:test",
        runId: dir,
        now: () => "2026-07-11T00:00:00.000Z",
      }),
    );
    appendTelemetryRecord(
      dir,
      buildDispatchStamp({
        legId,
        spec: baseSpec(),
        ctx: { stateDir: dir },
        dispatchedAt: "2026-07-11T00:00:01.000Z",
        now: () => "2026-07-11T00:00:01.000Z",
      }),
    );
    appendTelemetryRecord(
      dir,
      buildCollectStamp({
        legId,
        completedAt: "2026-07-11T00:00:10.000Z",
        terminal: "completed",
        errorCategory: null,
        errorMessage: null,
        tokens: { input: null, output: null, cached: null, total: 99 },
        sessionId: "s1",
        logPath: join(dir, "S2.log"),
        firstOutputAt: "2026-07-11T00:00:02.000Z",
        now: () => "2026-07-11T00:00:10.000Z",
      }),
    );

    const path = join(dir, TELEMETRY_FILENAME);
    expect(existsSync(path)).toBe(true);
    const lines = readFileSync(path, "utf8").trim().split("\n");
    expect(lines).toHaveLength(3);
    const env = JSON.parse(lines[0]!) as TelemetryEnvironmentRecord;
    const dispatch = JSON.parse(lines[1]!) as TelemetryDispatchRecord;
    const collect = JSON.parse(lines[2]!) as TelemetryCollectRecord;
    expect(env.phase).toBe("environment");
    expect(env.imageTag).toBe("ming-orchestrator-coder:test");
    expect(dispatch.phase).toBe("dispatch");
    expect(dispatch.legId).toBe(legId);
    expect(dispatch.model.slug).toBe("gpt-5.6-terra");
    expect(dispatch.model.family).toBe("codex");
    expect(collect.phase).toBe("collect");
    expect(collect.legId).toBe(legId);
    expect(collect.tokens?.total).toBe(99);
    expect(collect.first_output_at).toBe("2026-07-11T00:00:02.000Z");
  });

  it("ensureEnvironmentStamp is idempotent (one environment line per ledger)", () => {
    const dir = tempDir("orch-786-env-");
    expect(ensureEnvironmentStamp(dir, {}, { imageTag: "img:a" })).toBe(true);
    expect(ensureEnvironmentStamp(dir, {}, { imageTag: "img:b" })).toBe(false);
    const records = readTelemetryRecords(dir);
    expect(records.filter((r) => r.phase === "environment")).toHaveLength(1);
    expect(
      (records[0] as TelemetryEnvironmentRecord).imageTag,
    ).toBe("img:a");
  });

  it("tryAppendTelemetryRecord returns false when ledgerDir is missing", () => {
    expect(
      tryAppendTelemetryRecord(undefined, {
        v: 1,
        phase: "environment",
        stamped_at: "t",
        runId: null,
        imageTag: null,
        routeName: null,
        routeSlots: null,
        routeCmrReviewLegs: null,
        cliVersions: null,
      }),
    ).toBe(false);
  });

  it("buildDispatchStamp records Coder-Rec order from issue body when present", () => {
    const stamp = buildDispatchStamp({
      legId: "leg-1",
      spec: baseSpec({ model: "grok-4.5" }),
      ctx: {
        issueSnapshot: {
          number: 786,
          body: "Coder-Rec: grok-4.5 → terra@med → luna@med\n\nbody",
          comments: [],
          agentBrief: "",
        },
      },
      dispatchedAt: "2026-07-11T00:00:00.000Z",
      now: () => "2026-07-11T00:00:00.000Z",
    });
    expect(stamp.issue).toBe(786);
    expect(stamp.coderRec).not.toBeNull();
    expect(stamp.coderRec?.selected).toBe("grok-4.5");
    expect(stamp.coderRec?.order?.length).toBeGreaterThan(0);
    expect(stamp.coderRec?.wasFallback).toBe(false);
  });

  it("buildEnvironmentStamp reuses route-smoke cliVersions", () => {
    const route = smokedRoute();
    const stamp = buildEnvironmentStamp({
      ctx: { modelRoute: route, stateDir: "/tmp/ledger-786" },
      imageTag: "ming-orchestrator-coder:latest",
      now: () => "2026-07-11T00:00:00.000Z",
    });
    expect(stamp.routeName).toBe("normal");
    expect(stamp.routeSlots).not.toBeNull();
    expect(stamp.cliVersions).not.toBeNull();
    expect(Object.keys(stamp.cliVersions ?? {}).length).toBeGreaterThan(0);
    // Every value is the smoke-passed cliVersion string.
    for (const v of Object.values(stamp.cliVersions ?? {})) {
      expect(v.startsWith("cli-")).toBe(true);
    }
  });
});

// ───────────────────────── integration (fake backend) ─────────────────────────

describe("#786 dispatch/collect integration via dispatchWorkerWithMonitor", () => {
  function workerSpec(): WorkerSpec {
    return baseSpec({ model: "gpt-5.6-terra" });
  }

  function quickExitBackend(logPayload: string): Backend {
    const backend = {
      resolveCliMonitorDispatch: (
        _spec: WorkerSpec,
        _ctx: DispatchContext,
      ): CliMonitorSpawnSpec => {
        const dir = tempDirs[tempDirs.length - 1]!;
        // Synchronous -e script: print token line to the inherited log fd, exit 0.
        return {
          command: process.execPath,
          args: [
            "-e",
            `process.stdout.write(${JSON.stringify(logPayload)});`,
          ],
          logDir: dir,
          poolId: "codex-5h",
          completionSignal: "<coder>",
          stepId: "S2",
          readInstanceId: () => "test-instance-786",
        };
      },
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "sess-786",
      }),
    };
    // Partial fake — only the monitored-dispatch hooks are exercised.
    return backend as unknown as Backend;
  }

  it("writes environment + dispatch + collect half-rows joined by legId", async () => {
    const dir = tempDir("orch-786-integ-");
    const ledgerDir = join(dir, ".ledger-786");
    const route = smokedRoute();

    const outcome = await dispatchWorkerWithMonitor(
      quickExitBackend("working…\ntokens used\n1,234\n"),
      workerSpec(),
      {
        stateDir: ledgerDir,
        modelRoute: route,
      },
      undefined,
      {
        // Keep idle far above the instant-exit child so the exit race wins.
        idleThresholdMs: 60_000,
        pollIntervalMs: 20,
        monitorDeps: {
          readInstanceId: () => "test-instance-786",
          // Real short sleep so the event loop can deliver child 'exit'.
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
      },
    );

    expect(outcome.result.kind).toBe("completed");
    expect(existsSync(join(ledgerDir, TELEMETRY_FILENAME))).toBe(true);

    const records = readTelemetryRecords(ledgerDir);
    const env = records.find((r) => r.phase === "environment");
    const dispatch = records.find((r) => r.phase === "dispatch");
    const collect = records.find((r) => r.phase === "collect");

    expect(env).toBeDefined();
    expect(dispatch).toBeDefined();
    expect(collect).toBeDefined();

    const d = dispatch as TelemetryDispatchRecord;
    const c = collect as TelemetryCollectRecord;
    expect(d.legId).toBe(c.legId);
    expect(d.stepId).toBe("S2");
    expect(d.role).toBe("coder");
    expect(d.model.slug).toBe("gpt-5.6-terra");
    expect(d.model.family).toBe("codex");
    expect(d.poolId).toBe("codex-5h");
    expect(d.dispatched_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(c.terminal).toBe("completed");
    expect(c.errorCategory).toBeNull();
    expect(c.sessionId).toBe("sess-786");
    expect(c.logPath).toContain("S2.log");
    expect(c.completed_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    // tokens used line must be captured before any GC
    expect(c.tokens?.total).toBe(1234);
    // #786 core dimension: first-observed output (poll granularity — not true
    // TTFB) must not be null on quick-exit when the worker already wrote log
    // bytes (baseline-before-poll bug).
    expect(c.first_output_at).not.toBeNull();
    expect(c.first_output_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(Date.parse(c.first_output_at!)).toBeGreaterThanOrEqual(
      Date.parse(d.dispatched_at) - 5_000,
    );
    // Monotonic order: dispatched_at ≤ first_output_at ≤ completed_at
    // (first_output_at is poll-observed / post-exit reconcile, not true TTFB).
    const firstOutMs = Date.parse(c.first_output_at!);
    const dispatchedMs = Date.parse(d.dispatched_at);
    const completedMs = Date.parse(c.completed_at);
    expect(firstOutMs).toBeGreaterThanOrEqual(dispatchedMs);
    expect(firstOutMs).toBeLessThanOrEqual(completedMs);
    expect(dispatchedMs).toBeLessThanOrEqual(completedMs);

    const e = env as TelemetryEnvironmentRecord;
    expect(e.routeName).toBe("normal");
    expect(e.cliVersions).not.toBeNull();
  });

  it("quick-exit with log output stamps non-null first_output_at (no poll growth)", async () => {
    // Child writes and exits in the same tick — exit can win the race before the
    // idle poll loop observes size growth. first_output_at must still be set
    // (post-exit reconcile ≈ process exit time; poll-granularity semantics).
    const dir = tempDir("orch-786-quick-first-out-");
    const ledgerDir = join(dir, ".ledger-786");
    const payload =
      "first token from model\ntokens used\n99\n";

    const outcome = await dispatchWorkerWithMonitor(
      quickExitBackend(payload),
      workerSpec(),
      { stateDir: ledgerDir },
      undefined,
      {
        idleThresholdMs: 60_000,
        // Long poll would miss growth if we only watched post-baseline deltas.
        pollIntervalMs: 5_000,
        monitorDeps: {
          readInstanceId: () => "test-instance-786-quick",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 5))),
        },
      },
    );

    expect(outcome.result.kind).toBe("completed");
    const records = readTelemetryRecords(ledgerDir);
    const dispatch = records.find((r) => r.phase === "dispatch") as
      | TelemetryDispatchRecord
      | undefined;
    const collect = records.find((r) => r.phase === "collect") as
      | TelemetryCollectRecord
      | undefined;
    expect(collect).toBeDefined();
    expect(collect?.first_output_at).not.toBeNull();
    expect(collect?.tokens?.total).toBe(99);
    // Monotonic: dispatched_at ≤ first_output_at ≤ completed_at
    expect(dispatch).toBeDefined();
    const firstOutMs = Date.parse(collect!.first_output_at!);
    const dispatchedMs = Date.parse(dispatch!.dispatched_at);
    const completedMs = Date.parse(collect!.completed_at);
    expect(firstOutMs).toBeGreaterThanOrEqual(dispatchedMs);
    expect(firstOutMs).toBeLessThanOrEqual(completedMs);
    expect(dispatchedMs).toBeLessThanOrEqual(completedMs);
  });

  it("collect stamps hang-idle category when idle monitor kills the worker", async () => {
    const dir = tempDir("orch-786-hang-");
    const ledgerDir = join(dir, ".ledger-786");

    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        // Sleep long enough that idle threshold 0 fires.
        args: ["-e", "setTimeout(() => {}, 5000)"],
        logDir: dir,
        poolId: "zai",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance-hang",
      }),
      handleMonitoredWorkerIdle: async () => "hang" as const,
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: false, commitsAdded: 0 },
      }),
    } as unknown as Backend;

    const killed: number[] = [];
    await expect(
      dispatchWorkerWithMonitor(
        backend,
        workerSpec(),
        { stateDir: ledgerDir },
        undefined,
        {
          idleThresholdMs: 0,
          pollIntervalMs: 1,
          monitorDeps: {
            readInstanceId: () => "test-instance-hang",
            killPid: (pid) => killed.push(pid),
            isPidAlive: (pid) => pid > 0 && !killed.includes(pid),
            listChildPids: () => [],
            readParentPid: () => undefined,
            sleepMs: async () => {},
          },
        },
      ),
    ).rejects.toThrow(/idle hang/);

    const records = readTelemetryRecords(ledgerDir);
    const dispatch = records.find((r) => r.phase === "dispatch");
    const collect = records.find((r) => r.phase === "collect");
    expect(dispatch).toBeDefined();
    expect(collect).toBeDefined();
    expect((dispatch as TelemetryDispatchRecord).legId).toBe(
      (collect as TelemetryCollectRecord).legId,
    );
    expect((collect as TelemetryCollectRecord).terminal).toBe("thrown");
    expect((collect as TelemetryCollectRecord).errorCategory).toBe("hang-idle");
  });

  it("signal-killed CLI leg stamps killed collect row (not silent drop)", async () => {
    const dir = tempDir("orch-786-kill-");
    const ledgerDir = join(dir, ".ledger-786");

    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        // Sleep forever until external signal; we SIGTERM after spawn.
        args: ["-e", "setTimeout(() => {}, 60_000)"],
        logDir: dir,
        poolId: "codex-5h",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance-kill",
      }),
      // If the kill path wrongly falls through, await would fabricate success —
      // fail the test loudly in that case.
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => {
        throw new Error(
          "awaitMonitoredCliWorker must not run on signal-killed legs",
        );
      },
    } as unknown as Backend;

    const outcome = await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { stateDir: ledgerDir },
      undefined,
      {
        idleThresholdMs: 60_000,
        pollIntervalMs: 20,
        monitorDeps: {
          readInstanceId: () => "test-instance-kill",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
        onMonitorHandleSpawned: async (handle) => {
          // External signal kill (simulates OS/orchestrator SIGTERM of the leg).
          process.kill(handle.pid, "SIGTERM");
        },
      },
    );

    expect(outcome.result.kind).toBe("failed");
    if (outcome.result.kind === "failed") {
      expect(outcome.result.reason).toMatch(/killed by signal/i);
    }

    const records = readTelemetryRecords(ledgerDir);
    const collect = records.find((r) => r.phase === "collect") as
      | TelemetryCollectRecord
      | undefined;
    expect(collect).toBeDefined();
    expect(collect?.terminal).toBe("failed");
    expect(collect?.errorCategory).toBe("killed");
    expect(collect?.errorMessage).toMatch(/killed by signal/i);
    // Pair still present — not silently dropped.
    const dispatch = records.find((r) => r.phase === "dispatch");
    expect(dispatch).toBeDefined();
    expect((dispatch as TelemetryDispatchRecord).legId).toBe(collect?.legId);
  });

  it("dispatch half-row uses handle.dispatchedAt (post-spawn), not a pre-parse guess", async () => {
    const dir = tempDir("orch-786-dispatched-at-");
    const ledgerDir = join(dir, ".ledger-786");
    let handleDispatchedAt: string | undefined;

    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "process.exit(0)"],
        logDir: dir,
        poolId: "codex-5h",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance-ts",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { stateDir: ledgerDir },
      undefined,
      {
        idleThresholdMs: 60_000,
        pollIntervalMs: 20,
        monitorDeps: {
          readInstanceId: () => "test-instance-ts",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
        onMonitorHandleSpawned: (handle) => {
          handleDispatchedAt = handle.dispatchedAt;
        },
      },
    );

    expect(handleDispatchedAt).toBeDefined();
    const records = readTelemetryRecords(ledgerDir);
    const dispatch = records.find((r) => r.phase === "dispatch") as
      | TelemetryDispatchRecord
      | undefined;
    expect(dispatch).toBeDefined();
    expect(dispatch?.dispatched_at).toBe(handleDispatchedAt);
  });

  it("container/legacy path (no CLI monitor) still stamps dispatch+collect", async () => {
    const dir = tempDir("orch-786-legacy-");
    const ledgerDir = join(dir, ".ledger-786");
    const route = smokedRoute();

    const backend = {
      dispatchWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "legacy-sess",
      }),
    } as unknown as Backend;

    const outcome = await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { stateDir: ledgerDir, modelRoute: route },
    );

    expect(outcome.result.kind).toBe("completed");
    const records = readTelemetryRecords(ledgerDir);
    expect(records.some((r) => r.phase === "environment")).toBe(true);
    expect(records.some((r) => r.phase === "dispatch")).toBe(true);
    const collect = records.find((r) => r.phase === "collect") as
      | TelemetryCollectRecord
      | undefined;
    expect(collect?.terminal).toBe("completed");
    expect(collect?.sessionId).toBe("legacy-sess");
    expect(collect?.tokens).toBeNull();
  });

  it("fail-open: newLegId/telemetry init throw does not abort backend dispatch", async () => {
    const dir = tempDir("orch-786-failopen-");
    const ledgerDir = join(dir, ".ledger-786");
    const spy = vi
      .spyOn(globalThis.crypto, "randomUUID")
      .mockImplementation(() => {
        throw new Error("crypto.randomUUID unavailable");
      });

    try {
      const outcome = await dispatchWorkerWithMonitor(
        quickExitBackend("tokens used\n1\n"),
        workerSpec(),
        { stateDir: ledgerDir },
        undefined,
        {
          idleThresholdMs: 60_000,
          pollIntervalMs: 20,
          monitorDeps: {
            readInstanceId: () => "test-instance-failopen",
            sleepMs: (ms) =>
              new Promise((r) => setTimeout(r, Math.min(ms, 20))),
          },
        },
      );
      // Dispatch semantics unchanged — worker still completes.
      expect(outcome.result.kind).toBe("completed");
      const records = readTelemetryRecords(ledgerDir);
      // No paired dispatch/collect when legId never allocated.
      expect(records.filter((r) => r.phase === "dispatch")).toHaveLength(0);
      expect(records.filter((r) => r.phase === "collect")).toHaveLength(0);
    } finally {
      spy.mockRestore();
    }
  });

  it("no orphan collect when resolveCliMonitorDispatch throws before spawn", async () => {
    const dir = tempDir("orch-786-orphan-resolve-");
    const ledgerDir = join(dir, ".ledger-786");

    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => {
        throw new Error("resolve boom before spawn");
      },
    } as unknown as Backend;

    await expect(
      dispatchWorkerWithMonitor(backend, workerSpec(), {
        stateDir: ledgerDir,
      }),
    ).rejects.toThrow(/resolve boom before spawn/);

    const records = readTelemetryRecords(ledgerDir);
    expect(records.filter((r) => r.phase === "dispatch")).toHaveLength(0);
    expect(records.filter((r) => r.phase === "collect")).toHaveLength(0);
  });

  it("no orphan collect when spawn fails after resolve", async () => {
    const dir = tempDir("orch-786-orphan-spawn-");
    const ledgerDir = join(dir, ".ledger-786");

    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        // Empty command → spawn fails (no durable dispatch half-row).
        command: "",
        args: [],
        logDir: dir,
        poolId: "codex-5h",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance-spawn-fail",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    await expect(
      dispatchWorkerWithMonitor(backend, workerSpec(), {
        stateDir: ledgerDir,
      }),
    ).rejects.toThrow();

    const records = readTelemetryRecords(ledgerDir);
    expect(records.filter((r) => r.phase === "dispatch")).toHaveLength(0);
    expect(records.filter((r) => r.phase === "collect")).toHaveLength(0);
  });
});
