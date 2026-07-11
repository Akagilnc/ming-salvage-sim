/**
 * #786 — telemetry sidecar: pure writers/extractors + dispatch/collect integration.
 */

import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { dispatchWorkerWithMonitor } from "../src/dispatchWorker.js";
import { workerResultFromMonitorSidecar } from "../src/cliMonitorHooks.js";
import { resolveRouteModels, routeSmokeEntries } from "../src/modelRoutes.js";
import {
  appendTelemetryRecord,
  buildCollectStamp,
  buildDispatchStamp,
  buildEnvironmentStamp,
  categoryFromReason,
  classifyWorkerTerminal,
  clearTelemetryRunEnvironment,
  configureTelemetryFromWorkerImage,
  configureTelemetryRunEnvironment,
  ensureEnvironmentStamp,
  extractClaudeTokens,
  extractCodexTokens,
  extractTokensFromLog,
  hashDirectoryContents,
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
  WorkerMonitorHandle,
  WorkerResult,
  WorkerSpec,
} from "../src/types.js";

const tempDirs: string[] = [];

afterEach(() => {
  clearTelemetryRunEnvironment();
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

/** Minimal environment half-row for I/O tests (nulls for optional fingerprints). */
function envRecordStub(
  overrides: Partial<TelemetryEnvironmentRecord> = {},
): TelemetryEnvironmentRecord {
  return {
    v: 1,
    phase: "environment",
    stamped_at: "t",
    runId: null,
    imageTag: null,
    imageDigest: null,
    sandboxFingerprint: null,
    soulsHash: null,
    promptHash: null,
    routeName: null,
    routeSlots: null,
    routeCmrReviewLegs: null,
    cliVersions: null,
    ...overrides,
  };
}

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

  it("escalated missing-completion-signal is honest-incomplete (not category null)", () => {
    // shipOutcome.ts: unsignaled ship → escalate (not failed). Clustering must
    // still see honest-incomplete — force-null on all escalated was a R6 bug.
    const shipReason = "ship worker did not fire its completion signal";
    const classified = classifyWorkerTerminal({
      kind: "result",
      result: {
        kind: "escalated",
        escalation: {
          reason: shipReason,
          diagnosis:
            'expected "<ship_done>", got none (no signal fired before the iteration limit)',
        },
      },
    });
    expect(classified.terminal).toBe("escalated");
    expect(classified.errorCategory).toBe("honest-incomplete");
    expect(classified.errorMessage).toBe(shipReason);

    // Pure decision escalate (no known failure signature) stays category-null.
    const decision = classifyWorkerTerminal({
      kind: "result",
      result: {
        kind: "escalated",
        escalation: {
          reason: "human must choose between two valid approaches",
          diagnosis: "both options preserve invariants",
        },
      },
    });
    expect(decision.terminal).toBe("escalated");
    expect(decision.errorCategory).toBeNull();
  });

  it("categoryFromReason does not treat issue #429 or path /429/ as quota", () => {
    expect(categoryFromReason("see issue #429 for details")).toBe(
      "unclassified",
    );
    expect(
      categoryFromReason("failed reading /tmp/runs/429/ledger.json"),
    ).toBe("unclassified");
    expect(categoryFromReason("processed item 429 of 500")).toBe(
      "unclassified",
    );
    // Real quota shapes still match.
    expect(categoryFromReason("rate limit 429 from provider")).toBe(
      "429-quota",
    );
    expect(categoryFromReason("quota wait for reset at 02:00")).toBe(
      "429-quota",
    );
    expect(categoryFromReason("provider returned HTTP 429")).toBe("429-quota");
  });

  it("categoryFromReason classifies common HTTP/status 429 wording as quota", () => {
    expect(categoryFromReason("HTTP Error 429")).toBe("429-quota");
    expect(categoryFromReason("HTTP response code 429")).toBe("429-quota");
    expect(categoryFromReason("response code 429")).toBe("429-quota");
    expect(categoryFromReason("status was 429")).toBe("429-quota");
    expect(categoryFromReason("429 Too Many Requests")).toBe("429-quota");
    expect(categoryFromReason("Too Many Requests")).toBe("429-quota");
  });

  it("categoryFromReason does not treat HTTP 429 decimal values as quota", () => {
    expect(categoryFromReason("HTTP 429.0")).toBe("unclassified");
    expect(categoryFromReason("response code 429.1")).toBe("unclassified");
    expect(categoryFromReason("status was 429.99 USD")).toBe("unclassified");
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
    expect(tryAppendTelemetryRecord(undefined, envRecordStub())).toBe(false);
  });

  it("tryAppendTelemetryRecord silently skips when ledger parent path does not exist (fake stateDir)", () => {
    // Construct a missing *ancestor* under a temp root — never hardcode host paths
    // like /resident/worktrees (pollutes hosts that already have it; breaks asserts).
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const root = tempDir("orch-786-missing-anc-");
    const fake = join(root, "no-such-parent", ".ledger-600-telemetry-r6");
    const missingParent = dirname(fake);
    expect(existsSync(missingParent)).toBe(false);
    expect(tryAppendTelemetryRecord(fake, envRecordStub())).toBe(false);
    expect(ensureEnvironmentStamp(fake, {})).toBe(false);
    expect(existsSync(missingParent)).toBe(false);
    expect(existsSync(fake)).toBe(false);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("tryAppendTelemetryRecord creates leaf ledgerDir when parent already exists", () => {
    const parent = tempDir("orch-786-parent-");
    const ledgerDir = join(parent, ".ledger-leaf");
    expect(
      tryAppendTelemetryRecord(
        ledgerDir,
        envRecordStub({ imageTag: "img:leaf" }),
      ),
    ).toBe(true);
    expect(existsSync(join(ledgerDir, TELEMETRY_FILENAME))).toBe(true);
    const records = readTelemetryRecords(ledgerDir);
    expect(records).toHaveLength(1);
    expect((records[0] as TelemetryEnvironmentRecord).imageTag).toBe("img:leaf");
  });

  it("buildEnvironmentStamp uses configured imageName and always exposes digest/sandbox/souls/prompt fields", async () => {
    const soulsDir = tempDir("orch-786-souls-");
    const promptsDir = tempDir("orch-786-prompts-");
    writeFileSync(join(soulsDir, "coder.md"), "soul-body\n", "utf8");
    writeFileSync(join(promptsDir, "coder.md"), "prompt-body\n", "utf8");
    await configureTelemetryFromWorkerImage({
      imageName: "ming-orchestrator-coder:from-imageName",
      codexFast: true,
      soulsDir,
      promptsDir,
    });
    const stamp = buildEnvironmentStamp({
      ctx: {},
      now: () => "2026-07-11T00:00:00.000Z",
    });
    expect(stamp.imageTag).toBe("ming-orchestrator-coder:from-imageName");
    // Fields always present (null only when truly unobtainable — digest often null without docker).
    expect("imageDigest" in stamp).toBe(true);
    expect("sandboxFingerprint" in stamp).toBe(true);
    expect("soulsHash" in stamp).toBe(true);
    expect("promptHash" in stamp).toBe(true);
    expect(stamp.soulsHash).toBe(hashDirectoryContents(soulsDir));
    expect(stamp.promptHash).toBe(hashDirectoryContents(promptsDir));
    expect(stamp.sandboxFingerprint).not.toBeNull();
    expect(typeof stamp.sandboxFingerprint).toBe("string");
    // Without IMAGE_TAG env, default path still stamps a tag (not null).
    clearTelemetryRunEnvironment();
    const defaultStamp = buildEnvironmentStamp({ ctx: {} });
    expect(defaultStamp.imageTag).toBe("ming-orchestrator-coder:latest");
    expect(defaultStamp.imageDigest).toBeNull();
    expect(defaultStamp.sandboxFingerprint).toBeNull();
    expect(defaultStamp.soulsHash).toBeNull();
    expect(defaultStamp.promptHash).toBeNull();
  });

  it("buildDispatchStamp model.fast follows configured codexFast, not only env", () => {
    const prev = process.env.ORCHESTRATOR_CODEX_FAST;
    delete process.env.ORCHESTRATOR_CODEX_FAST;
    try {
      configureTelemetryRunEnvironment({ codexFast: true });
      const stamp = buildDispatchStamp({
        legId: "leg-fast",
        spec: baseSpec({ model: "gpt-5.6-terra" }),
        ctx: {},
        dispatchedAt: "2026-07-11T00:00:00.000Z",
        now: () => "2026-07-11T00:00:00.000Z",
      });
      expect(stamp.model.family).toBe("codex");
      expect(stamp.model.fast).toBe(true);

      clearTelemetryRunEnvironment();
      configureTelemetryRunEnvironment({ codexFast: false });
      const off = buildDispatchStamp({
        legId: "leg-fast-off",
        spec: baseSpec({ model: "gpt-5.6-terra" }),
        ctx: {},
        dispatchedAt: "2026-07-11T00:00:00.000Z",
        now: () => "2026-07-11T00:00:00.000Z",
      });
      expect(off.model.fast).toBe(false);
    } finally {
      if (prev === undefined) delete process.env.ORCHESTRATOR_CODEX_FAST;
      else process.env.ORCHESTRATOR_CODEX_FAST = prev;
    }
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

  class ReceiverBoundTelemetryBackend {
    public readonly opts: { installs: number };

    constructor(opts: { installs: number }) {
      this.opts = opts;
    }

    // Production shape: a prototype class method that must retain `this`.
    installTelemetryRunEnvironment(): void {
      this.opts.installs += 1;
    }
  }

  it("does not reinstall telemetry environment when the ledger is already stamped", async () => {
    const dir = tempDir("orch-786-existing-env-");
    const ledgerDir = join(dir, ".ledger-786");
    const route = smokedRoute();
    mkdirSync(ledgerDir, { recursive: true });
    writeFileSync(
      join(ledgerDir, TELEMETRY_FILENAME),
      JSON.stringify(envRecordStub()) + "\n",
    );
    const backend = Object.assign(
      new ReceiverBoundTelemetryBackend({ installs: 0 }),
      quickExitBackend("done\n"),
    ) as Backend & ReceiverBoundTelemetryBackend;

    await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { stateDir: ledgerDir, modelRoute: route },
      undefined,
      {
        idleThresholdMs: 60_000,
        pollIntervalMs: 20,
        monitorDeps: {
          readInstanceId: () => "test-instance-786-existing-env",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
      },
    );

    expect(backend.opts.installs).toBe(0);
  });

  it("calls a receiver-bound backend installer asynchronously and writes the missing environment stamp", async () => {
    const dir = tempDir("orch-786-receiver-bound-env-");
    const ledgerDir = join(dir, ".ledger-786");
    const backend = Object.assign(
      new ReceiverBoundTelemetryBackend({ installs: 0 }),
      quickExitBackend("done\n"),
    ) as Backend & ReceiverBoundTelemetryBackend;

    await dispatchWorkerWithMonitor(
      backend,
      workerSpec(),
      { stateDir: ledgerDir, modelRoute: smokedRoute() },
      undefined,
      {
        idleThresholdMs: 60_000,
        pollIntervalMs: 20,
        monitorDeps: {
          readInstanceId: () => "test-instance-786-receiver-bound",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
      },
    );

    expect(backend.opts.installs).toBe(1);
    expect(readTelemetryRecords(ledgerDir).some((r) => r.phase === "environment")).toBe(true);
  });

  it("keeps quick-exit first output independent of a slow first environment fingerprint", async () => {
    const dir = tempDir("orch-786-env-after-handle-");
    const ledgerDir = join(dir, ".ledger-786");
    const binDir = join(dir, "bin");
    mkdirSync(binDir, { recursive: true });
    const dockerPath = join(binDir, "docker");
    writeFileSync(
      dockerPath,
      "#!/bin/sh\nsleep 0.25\nprintf 'sha256:telemetry-test\\n'\n",
      "utf8",
    );
    chmodSync(dockerPath, 0o755);
    const originalPath = process.env.PATH;
    process.env.PATH = `${binDir}:${originalPath ?? ""}`;
    let handlePersisted = false;
    let installerSawPersistedHandle = false;
    const backend = {
      ...quickExitBackend("first token from model\\n"),
      installTelemetryRunEnvironment: () => {
        installerSawPersistedHandle = handlePersisted;
        return configureTelemetryFromWorkerImage({
          imageName: "ming-orchestrator-coder:test",
        });
      },
    } as Backend;

    try {
      const outcome = await dispatchWorkerWithMonitor(
        backend,
        workerSpec(),
        { stateDir: ledgerDir },
        undefined,
        {
          idleThresholdMs: 60_000,
          pollIntervalMs: 5_000,
          monitorDeps: {
            readInstanceId: () => "test-instance-786-env-after-handle",
            sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 5))),
          },
          onMonitorHandleSpawned: async () => {
            handlePersisted = true;
          },
        },
      );

      expect(outcome.result.kind).toBe("completed");
      expect(installerSawPersistedHandle).toBe(true);
      const records = readTelemetryRecords(ledgerDir);
      const dispatch = records.find(
        (r) => r.phase === "dispatch",
      ) as TelemetryDispatchRecord | undefined;
      const collect = records.find(
        (r) => r.phase === "collect",
      ) as TelemetryCollectRecord | undefined;
      expect(collect?.first_output_at).not.toBeNull();
      expect(
        new Date(collect!.first_output_at!).getTime() -
          new Date(dispatch!.dispatched_at).getTime(),
      ).toBeLessThan(200);

      // The delayed first calculation must still finish before writing the
      // environment row; a prompt first-output stamp must not trade away data.
      let environment: TelemetryEnvironmentRecord | undefined;
      for (let attempt = 0; attempt < 100 && environment === undefined; attempt += 1) {
        environment = readTelemetryRecords(ledgerDir).find(
          (r) => r.phase === "environment",
        ) as TelemetryEnvironmentRecord | undefined;
        if (environment === undefined) {
          await new Promise<void>((resolve) => setTimeout(resolve, 20));
        }
      }
      expect(environment?.imageDigest).toBe("sha256:telemetry-test");
    } finally {
      if (originalPath === undefined) {
        delete process.env.PATH;
      } else {
        process.env.PATH = originalPath;
      }
    }
  });

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

  it("signal-killed CLI leg without sidecar stamps killed; with sidecar honors real result", async () => {
    const dir = tempDir("orch-786-kill-");
    const ledgerDir = join(dir, ".ledger-786");
    let mapperCalls = 0;

    // ── no usable sidecar: mapper empty-fallback → killed-by-signal ────────
    const backendNoSidecar = {
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
      // Correct semantics: mapper ALWAYS runs on signal exit. Empty-sidecar
      // fallback is rewritten to killed-by-signal for telemetry clustering.
      awaitMonitoredCliWorker: async (
        handle: WorkerMonitorHandle,
        exitCode: number | null,
      ): Promise<WorkerResult> => {
        mapperCalls += 1;
        return workerResultFromMonitorSidecar(handle, exitCode);
      },
    } as unknown as Backend;

    const outcome = await dispatchWorkerWithMonitor(
      backendNoSidecar,
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

    expect(mapperCalls).toBe(1);
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

    // ── valid completed sidecar after SIGTERM: honor real result ───────────
    const dir2 = tempDir("orch-786-kill-sidecar-");
    const ledgerDir2 = join(dir2, ".ledger-786");
    let mapperCalls2 = 0;
    const backendWithSidecar = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => {}, 60_000)"],
        logDir: dir2,
        poolId: "codex-5h",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance-kill-sc",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => {
        mapperCalls2 += 1;
        // Worker wrote a completed sidecar before the narrow-window SIGTERM.
        return {
          kind: "completed",
          output: { kind: "coder", committed: true, commitsAdded: 1 },
        };
      },
    } as unknown as Backend;

    const outcome2 = await dispatchWorkerWithMonitor(
      backendWithSidecar,
      workerSpec(),
      { stateDir: ledgerDir2 },
      undefined,
      {
        idleThresholdMs: 60_000,
        pollIntervalMs: 20,
        monitorDeps: {
          readInstanceId: () => "test-instance-kill-sc",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
        onMonitorHandleSpawned: async (handle) => {
          process.kill(handle.pid, "SIGTERM");
        },
      },
    );
    expect(mapperCalls2).toBe(1);
    expect(outcome2.result.kind).toBe("completed");
    const collect2 = readTelemetryRecords(ledgerDir2).find(
      (r) => r.phase === "collect",
    ) as TelemetryCollectRecord | undefined;
    expect(collect2?.terminal).toBe("completed");
    expect(collect2?.errorCategory).toBeNull();
  });

  it("installTelemetryRunEnvironment reinstalls child fingerprints after family overwrite", async () => {
    const childPrompts = tempDir("orch-786-child-prompts-");
    const familyPrompts = tempDir("orch-786-family-prompts-");
    writeFileSync(join(childPrompts, "a.md"), "child-prompt\n", "utf8");
    writeFileSync(join(familyPrompts, "a.md"), "family-prompt\n", "utf8");
    const childHash = hashDirectoryContents(childPrompts);
    const familyHash = hashDirectoryContents(familyPrompts);
    expect(childHash).not.toBe(familyHash);

    // Simulate familyDriver construction order: RealBackend then RealFamilyBackend.
    await configureTelemetryFromWorkerImage({
      imageName: "ming-orchestrator-coder:test",
      promptsDir: childPrompts,
    });
    await configureTelemetryFromWorkerImage({
      imageName: "ming-orchestrator-coder:test",
      promptsDir: familyPrompts,
    });
    // Without reinstall, stamp would carry family promptHash.
    expect(buildEnvironmentStamp({ ctx: {} }).promptHash).toBe(familyHash);

    const ledgerDir = join(tempDir("orch-786-env-reinstall-"), ".ledger");
    const backend = {
      installTelemetryRunEnvironment: () => {
        return configureTelemetryFromWorkerImage({
          imageName: "ming-orchestrator-coder:test",
          promptsDir: childPrompts,
        });
      },
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "process.exit(0)"],
        logDir: dirname(ledgerDir),
        poolId: "codex-5h",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance-env",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
    } as unknown as Backend;

    await dispatchWorkerWithMonitor(backend, workerSpec(), {
      stateDir: ledgerDir,
    });

    const env = readTelemetryRecords(ledgerDir).find(
      (r) => r.phase === "environment",
    ) as TelemetryEnvironmentRecord | undefined;
    expect(env).toBeDefined();
    expect(env?.promptHash).toBe(childHash);
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

  it("no orphan collect when dispatch append fails then ledger becomes writable mid-flight", async () => {
    // stampDispatch runs right after spawn (parent still missing → append false).
    // Recover the ledger parent only in onMonitorHandleSpawned (after dispatch
    // stamp). A buggy unconditional dispatchStamped=true would then let collect
    // write an unjoinable orphan half-row (review RED: expected [] received [collect]).
    const root = tempDir("orch-786-orphan-recover-");
    const mid = join(root, "recover-parent");
    const ledgerDir = join(mid, ".ledger-786");
    expect(existsSync(mid)).toBe(false);

    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "process.exit(0)"],
        logDir: root,
        poolId: "codex-5h",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance-orphan-recover",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
        sessionId: "sess-orphan-recover",
      }),
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
          readInstanceId: () => "test-instance-orphan-recover",
          sleepMs: (ms) => new Promise((r) => setTimeout(r, Math.min(ms, 20))),
        },
        onMonitorHandleSpawned: async () => {
          // Recover AFTER stampDispatch — collect path becomes writable.
          mkdirSync(ledgerDir, { recursive: true });
        },
      },
    );

    expect(outcome.result.kind).toBe("completed");
    const records = existsSync(join(ledgerDir, TELEMETRY_FILENAME))
      ? readTelemetryRecords(ledgerDir)
      : [];
    expect(records.filter((r) => r.phase === "dispatch").map((r) => r.phase)).toEqual(
      [],
    );
    expect(records.filter((r) => r.phase === "collect").map((r) => r.phase)).toEqual(
      [],
    );
  });

  it("schedules the lazy environment stamp before a throwing spawn callback", async () => {
    const dir = tempDir("orch-786-env-callback-throw-");
    const ledgerDir = join(dir, ".ledger-786");
    const backend = {
      resolveCliMonitorDispatch: (): CliMonitorSpawnSpec => ({
        command: process.execPath,
        args: ["-e", "setTimeout(() => process.exit(0), 50)"],
        logDir: dir,
        poolId: "codex-5h",
        completionSignal: "<coder>",
        stepId: "S2",
        readInstanceId: () => "test-instance-env-callback-throw",
      }),
      awaitMonitoredCliWorker: async (): Promise<WorkerResult> => ({
        kind: "completed",
        output: { kind: "coder", committed: true, commitsAdded: 1 },
      }),
      installTelemetryRunEnvironment: async () => {},
    } as unknown as Backend;

    await expect(
      dispatchWorkerWithMonitor(backend, workerSpec(), { stateDir: ledgerDir }, undefined, {
        onMonitorHandleSpawned: async () => {
          throw new Error("ledger persistence failed");
        },
      }),
    ).rejects.toThrow(/ledger persistence failed/);

    let environment: TelemetryEnvironmentRecord | undefined;
    for (let attempt = 0; attempt < 100 && environment === undefined; attempt += 1) {
      environment = readTelemetryRecords(ledgerDir).find(
        (record): record is TelemetryEnvironmentRecord => record.phase === "environment",
      );
      if (environment === undefined) {
        await new Promise<void>((resolve) => setTimeout(resolve, 5));
      }
    }
    expect(environment).toBeDefined();
  });
});
