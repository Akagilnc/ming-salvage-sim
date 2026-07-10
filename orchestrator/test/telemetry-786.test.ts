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

import { afterEach, describe, expect, it } from "vitest";

import { dispatchWorkerWithMonitor } from "../src/dispatchWorker.js";
import { resolveRouteModels, routeSmokeEntries } from "../src/modelRoutes.js";
import {
  appendTelemetryRecord,
  buildCollectStamp,
  buildDispatchStamp,
  buildEnvironmentStamp,
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

    expect(
      classifyWorkerTerminal({
        kind: "thrown",
        error: new Error("stream disconnect mid-response"),
      }).errorCategory,
    ).toBe("stream-disconnect");
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

    const e = env as TelemetryEnvironmentRecord;
    expect(e.routeName).toBe("normal");
    expect(e.cliVersions).not.toBeNull();
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
});
